"""Conservative Aether-level alias and mod/ref analysis.

This module deliberately models semantic objects (class objects and collection
storage), not native addresses.  It is analysis infrastructure: no optimizer
pipeline imports it.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from aether.ir.types import (
    ArrayType, ClassRefType, InterfaceType, ListType, NullableType, StringType,
)
from aether.ssa import model as m


class AliasRelation(Enum):
    MUST_ALIAS = "must-alias"
    NO_ALIAS = "no-alias"
    MAY_ALIAS = "may-alias"


class ModRefEffect(Enum):
    NO_ACCESS = "no-access"
    READ = "read"
    MODIFY = "modify"
    READ_MODIFY = "read-modify"
    UNKNOWN = "unknown"

    @property
    def may_read(self) -> bool:
        return self in (ModRefEffect.READ, ModRefEffect.READ_MODIFY, ModRefEffect.UNKNOWN)

    @property
    def may_modify(self) -> bool:
        return self in (ModRefEffect.MODIFY, ModRefEffect.READ_MODIFY, ModRefEffect.UNKNOWN)


class UnknownReason(Enum):
    UNKNOWN_EXTERNAL_CALL = "unknown-external-call"
    UNKNOWN_INDIRECT_TARGET = "unknown-indirect-target"
    UNKNOWN_INTERFACE_IMPLEMENTATION = "unknown-interface-implementation"
    PHI_MERGE = "phi-merge"
    PARAMETER_ALIAS = "parameter-alias"
    GLOBAL_STATE = "global-state"
    FIELD_INSENSITIVITY = "field-insensitivity"
    UNSUPPORTED_INSTRUCTION = "unsupported-instruction"
    OTHER = "other"


class RootKind(Enum):
    FRESH = "fresh"
    PARAMETER = "parameter"
    VALUE = "value"
    INTERFACE_CARRIER = "interface-carrier"
    UNKNOWN = "unknown"


@dataclass(frozen=True, order=True)
class ProvenanceRoot:
    kind: RootKind
    identity: str


@dataclass(frozen=True)
class Provenance:
    roots: frozenset[ProvenanceRoot]
    reason: UnknownReason | None = None

    @property
    def exact(self) -> bool:
        return len(self.roots) == 1 and self.reason is None


@dataclass(frozen=True)
class ModRefDecision:
    effect: ModRefEffect
    reason: UnknownReason | None = None


@dataclass(frozen=True)
class FunctionSummary:
    function: str
    read_parameters: frozenset[int] = frozenset()
    modified_parameters: frozenset[int] = frozenset()
    returned_alias_parameters: frozenset[int] = frozenset()
    returns_fresh: bool = False
    allocates: bool = False
    touches_global_state: bool = False
    may_throw: bool = False
    may_trap: bool = False
    unknown_reasons: frozenset[UnknownReason] = frozenset()

    def debug_string(self) -> str:
        def indexes(values): return "[" + ",".join(map(str, sorted(values))) + "]"
        reasons = ",".join(item.value for item in sorted(self.unknown_reasons, key=lambda x: x.value))
        return (f"{self.function}: read={indexes(self.read_parameters)} "
                f"modify={indexes(self.modified_parameters)} return_alias={indexes(self.returned_alias_parameters)} "
                f"fresh={str(self.returns_fresh).lower()} allocates={str(self.allocates).lower()} "
                f"global={str(self.touches_global_state).lower()} throw={str(self.may_throw).lower()} "
                f"trap={str(self.may_trap).lower()} unknown=[{reasons}]")


_REFERENCE_TYPES = (ClassRefType, ArrayType, ListType, InterfaceType, StringType)


def _is_reference_like(type_) -> bool:
    if isinstance(type_, NullableType):
        return _is_reference_like(type_.inner)
    return isinstance(type_, _REFERENCE_TYPES)


class AliasAnalysis:
    """Flow-insensitive SSA provenance with conservative phi joins.

    Queries are O(number of provenance roots), normally O(1).  Fresh roots are
    only considered disjoint from other fresh roots created in this function;
    parameters and unknown results remain MAY_ALIAS.
    """
    def __init__(self, function: m.SSAFunction):
        self.function = function
        self._provenance: dict[m.SSAValue, Provenance] = {}
        self._definitions: dict[m.SSAValue, object] = {}
        for index, parameter in enumerate(function.parameters):
            kind = RootKind.PARAMETER if _is_reference_like(parameter.type) else RootKind.VALUE
            self._provenance[parameter] = Provenance(frozenset({ProvenanceRoot(kind, str(index))}),
                UnknownReason.PARAMETER_ALIAS if kind is RootKind.PARAMETER else None)
        self._compute()

    def _compute(self) -> None:
        instructions = [instruction for block in self.function.blocks for instruction in block.instructions]
        for instruction in instructions:
            result = getattr(instruction, "result", None)
            if isinstance(result, m.SSAValue): self._definitions[result] = instruction
        for _ in range(max(1, len(instructions) + 1)):
            changed = False
            for instruction in instructions:
                result = getattr(instruction, "result", None)
                if not isinstance(result, m.SSAValue): continue
                value = self._instruction_provenance(instruction, result)
                if value is not None and self._provenance.get(result) != value:
                    self._provenance[result] = value; changed = True
            if not changed: return
        # A malformed/nonconverging graph fails closed.
        for instruction in instructions:
            result = getattr(instruction, "result", None)
            if isinstance(result, m.SSAValue) and result not in self._provenance:
                self._provenance[result] = self._unknown(result, UnknownReason.OTHER)

    def _instruction_provenance(self, instruction, result):
        if not _is_reference_like(result.type):
            return Provenance(frozenset({ProvenanceRoot(RootKind.VALUE, result.name)}))
        if isinstance(instruction, (m.SSAClassNew, m.SSAArrayNew, m.SSAListNew,
                                    m.SSAArrayCopy, m.SSAListCopy, m.SSAArraySlice,
                                    m.SSAListSlice)):
            return Provenance(frozenset({ProvenanceRoot(RootKind.FRESH, result.name)}))
        if isinstance(instruction, m.SSAInterfaceConstruct):
            carrier = self.provenance(instruction.carrier)
            # Class-backed interfaces retain carrier identity. Struct-backed
            # interfaces own a fresh box created by interface construction.
            if isinstance(instruction.carrier.type, ClassRefType):
                return Provenance(carrier.roots, carrier.reason)
            return Provenance(frozenset({ProvenanceRoot(RootKind.FRESH, result.name)}))
        if isinstance(instruction, m.SSAPhi):
            incoming = [self._provenance.get(value) for _, value in instruction.incoming]
            if not incoming or any(item is None for item in incoming): return None
            roots = frozenset().union(*(item.roots for item in incoming if item))
            reasons = {item.reason for item in incoming if item and item.reason}
            if len(roots) == 1 and not reasons: return Provenance(roots)
            return Provenance(roots, UnknownReason.PHI_MERGE)
        if isinstance(instruction, (m.SSACall, m.SSAInvoke, m.SSACallIndirect,
                                    m.SSAInvokeIndirect, m.SSAInterfaceCall,
                                    m.SSAInvokeInterface)):
            reason = (UnknownReason.UNKNOWN_INDIRECT_TARGET if isinstance(instruction, (m.SSACallIndirect, m.SSAInvokeIndirect))
                      else UnknownReason.UNKNOWN_INTERFACE_IMPLEMENTATION if isinstance(instruction, (m.SSAInterfaceCall, m.SSAInvokeInterface))
                      else UnknownReason.UNKNOWN_EXTERNAL_CALL)
            return self._unknown(result, reason)
        return self._unknown(result, UnknownReason.UNSUPPORTED_INSTRUCTION)

    @staticmethod
    def _unknown(value, reason):
        return Provenance(frozenset({ProvenanceRoot(RootKind.UNKNOWN, value.name)}), reason)

    def provenance(self, value: m.SSAValue) -> Provenance:
        return self._provenance.get(value, self._unknown(value, UnknownReason.OTHER))

    def alias(self, left: m.SSAValue, right: m.SSAValue) -> AliasRelation:
        if left == right: return AliasRelation.MUST_ALIAS
        if not _is_reference_like(left.type) or not _is_reference_like(right.type):
            return AliasRelation.NO_ALIAS
        a, b = self.provenance(left), self.provenance(right)
        if a.exact and b.exact and a.roots == b.roots: return AliasRelation.MUST_ALIAS
        if a.exact and b.exact:
            ar, br = next(iter(a.roots)), next(iter(b.roots))
            if ar.kind is RootKind.FRESH and br.kind is RootKind.FRESH:
                return AliasRelation.NO_ALIAS
        if a.roots.isdisjoint(b.roots) and all(root.kind is RootKind.FRESH for root in a.roots | b.roots):
            return AliasRelation.NO_ALIAS
        return AliasRelation.MAY_ALIAS

    def verify(self) -> None:
        values = tuple(self._provenance)
        for value in values:
            if self.alias(value, value) is not AliasRelation.MUST_ALIAS:
                raise ValueError("an SSA value must alias itself")
        for index, left in enumerate(values):
            for right in values[index:]:
                if self.alias(left, right) is not self.alias(right, left):
                    raise ValueError("alias relation must be symmetric")

    def debug_string(self) -> str:
        lines = []
        for value, provenance in sorted(self._provenance.items(), key=lambda item: item[0].name):
            roots = ",".join(
                f"{root.kind.value}:{root.identity}"
                for root in sorted(provenance.roots, key=lambda root: (root.kind.value, root.identity))
            )
            reason = f" reason={provenance.reason.value}" if provenance.reason else ""
            lines.append(f"{value.name}: [{roots}]{reason}")
        return "\n".join(lines)


class ModRefAnalysis:
    """Alias-specific effects layered over ``InstructionEffects``."""
    def __init__(self, function: m.SSAFunction, summaries: dict[str, FunctionSummary] | None = None):
        self.aliases = AliasAnalysis(function)
        self.summaries = summaries or {}

    def effects(self, instruction, target: m.SSAValue) -> ModRefDecision:
        if isinstance(instruction, (m.SSACall, m.SSAInvoke)) and instruction.builtin in {
            "__aether_retain", "__aether_release"
        }:
            # Ownership metadata is not Aether-level object/collection state.
            return ModRefDecision(ModRefEffect.NO_ACCESS)
        reads, writes = self._accesses(instruction)
        read = any(self.aliases.alias(value, target) is not AliasRelation.NO_ALIAS for value in reads)
        write = any(self.aliases.alias(value, target) is not AliasRelation.NO_ALIAS for value in writes)
        if isinstance(instruction, (m.SSACallIndirect, m.SSAInvokeIndirect)):
            return ModRefDecision(ModRefEffect.UNKNOWN, UnknownReason.UNKNOWN_INDIRECT_TARGET)
        if isinstance(instruction, (m.SSAInterfaceCall, m.SSAInvokeInterface)):
            return ModRefDecision(ModRefEffect.UNKNOWN, UnknownReason.UNKNOWN_INTERFACE_IMPLEMENTATION)
        if isinstance(instruction, (m.SSACall, m.SSAInvoke)):
            summary = self.summaries.get(instruction.function)
            if summary is None:
                if instruction.builtin is not None and not instruction.writes_memory:
                    read = read or (instruction.reads_memory and target in instruction.arguments)
                elif instruction.writes_memory:
                    return ModRefDecision(ModRefEffect.UNKNOWN, UnknownReason.UNKNOWN_EXTERNAL_CALL)
            else:
                read = any(i < len(instruction.arguments) and self.aliases.alias(instruction.arguments[i], target) is not AliasRelation.NO_ALIAS for i in summary.read_parameters)
                write = any(i < len(instruction.arguments) and self.aliases.alias(instruction.arguments[i], target) is not AliasRelation.NO_ALIAS for i in summary.modified_parameters)
                if summary.touches_global_state and _is_reference_like(target.type):
                    return ModRefDecision(ModRefEffect.UNKNOWN, UnknownReason.GLOBAL_STATE)
        effect = ModRefEffect.READ_MODIFY if read and write else ModRefEffect.READ if read else ModRefEffect.MODIFY if write else ModRefEffect.NO_ACCESS
        return ModRefDecision(effect)

    def _accesses(self, instruction):
        return _semantic_accesses(instruction)

    def may_read(self, instruction, target): return self.effects(instruction, target).effect.may_read
    def may_modify(self, instruction, target): return self.effects(instruction, target).effect.may_modify
    def preserves_memory_fact(self, instruction, target): return not self.may_modify(instruction, target)
    def preserves_length_fact(self, instruction, collection):
        return isinstance(collection.type, ArrayType) or not self.may_modify(instruction, collection)
    def preserves_shape_fact(self, instruction, value): return not self.may_modify(instruction, value)
    def loop_may_modify(self, instructions, target): return any(self.may_modify(item, target) for item in instructions)


def _semantic_accesses(instruction):
    read, write = [], []
    for name in ("array", "list_value", "vector", "matrix", "object", "sequence"):
        value = getattr(instruction, name, None)
        if isinstance(value, m.SSAValue):
            if instruction.reads_memory: read.append(value)
            if instruction.writes_memory: write.append(value)
    return read, write


class SummaryAnalysis:
    """Deterministic monotone fixed point over direct calls.

    Each iteration only adds effects.  With P total parameters and F summary
    flags the height is O(P+F); each iteration scans every instruction, giving
    O((P+F)*I) worst-case time and O(P+F) summary storage.
    """
    def compute(self, module: m.SSAModule) -> dict[str, FunctionSummary]:
        functions = {function.name: function for function in module.functions}
        summaries = {name: FunctionSummary(name, may_throw=fn.may_throw) for name, fn in functions.items()}
        total_parameters = sum(len(fn.parameters) for fn in functions.values())
        for _ in range(max(1, total_parameters + len(functions) * 8 + 1)):
            updated = {name: self._summarize(fn, summaries, functions) for name, fn in sorted(functions.items())}
            if updated == summaries: return updated
            summaries = updated
        raise ValueError("mod/ref summaries did not converge")

    def _summarize(self, function, summaries, functions):
        aliases = AliasAnalysis(function); parameters = list(function.parameters)
        read, modified, returned = set(), set(), set(); allocates = global_state = False
        may_throw = function.may_throw; may_trap = False; reasons = set()
        for block in function.blocks:
            for instruction in block.instructions:
                may_throw |= instruction.may_throw; may_trap |= instruction.may_trap; allocates |= instruction.allocates
                accesses = _semantic_accesses(instruction)
                for index, parameter in enumerate(parameters):
                    if any(aliases.alias(parameter, value) is not AliasRelation.NO_ALIAS for value in accesses[0]): read.add(index)
                    if any(aliases.alias(parameter, value) is not AliasRelation.NO_ALIAS for value in accesses[1]): modified.add(index)
                if isinstance(instruction, (m.SSACall, m.SSAInvoke)):
                    callee = summaries.get(instruction.function)
                    if callee is None:
                        for index, parameter in enumerate(parameters):
                            passed = any(
                                aliases.alias(parameter, argument) is not AliasRelation.NO_ALIAS
                                for argument in instruction.arguments
                            )
                            if passed and instruction.reads_memory: read.add(index)
                            if passed and instruction.writes_memory: modified.add(index)
                        if instruction.writes_memory:
                            global_state = True; reasons.add(UnknownReason.UNKNOWN_EXTERNAL_CALL)
                        continue
                    may_throw |= callee.may_throw; may_trap |= callee.may_trap; allocates |= callee.allocates; global_state |= callee.touches_global_state; reasons.update(callee.unknown_reasons)
                    for caller_index, parameter in enumerate(parameters):
                        for callee_index in callee.read_parameters:
                            if callee_index < len(instruction.arguments) and aliases.alias(parameter, instruction.arguments[callee_index]) is not AliasRelation.NO_ALIAS: read.add(caller_index)
                        for callee_index in callee.modified_parameters:
                            if callee_index < len(instruction.arguments) and aliases.alias(parameter, instruction.arguments[callee_index]) is not AliasRelation.NO_ALIAS: modified.add(caller_index)
                elif isinstance(instruction, (m.SSACallIndirect, m.SSAInvokeIndirect)):
                    global_state = True; reasons.add(UnknownReason.UNKNOWN_INDIRECT_TARGET)
                    for index, parameter in enumerate(parameters):
                        if _is_reference_like(parameter.type): read.add(index); modified.add(index)
                elif isinstance(instruction, (m.SSAInterfaceCall, m.SSAInvokeInterface)):
                    global_state = True; reasons.add(UnknownReason.UNKNOWN_INTERFACE_IMPLEMENTATION)
                    for index, parameter in enumerate(parameters):
                        if _is_reference_like(parameter.type): read.add(index); modified.add(index)
                elif isinstance(instruction, m.SSAReturn) and instruction.value:
                    for index, parameter in enumerate(parameters):
                        if aliases.alias(parameter, instruction.value) is AliasRelation.MUST_ALIAS: returned.add(index)
        fresh = False
        returns = [item.value for block in function.blocks for item in block.instructions if isinstance(item, m.SSAReturn) and item.value]
        if returns:
            fresh = all(any(root.kind is RootKind.FRESH for root in aliases.provenance(value).roots) and aliases.provenance(value).exact for value in returns)
        return FunctionSummary(function.name, frozenset(read), frozenset(modified), frozenset(returned), fresh, allocates, global_state, may_throw, may_trap, frozenset(reasons))

    @staticmethod
    def debug_string(summaries):
        return "\n".join(summaries[name].debug_string() for name in sorted(summaries))
