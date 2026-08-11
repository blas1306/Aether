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
    StructType,
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
    UNKNOWN_RUNTIME_HELPER = "unknown-runtime-helper"
    UNKNOWN_INDIRECT_TARGET = "unknown-indirect-target"
    UNKNOWN_INTERFACE_IMPLEMENTATION = "unknown-interface-implementation"
    PHI_MERGE = "phi-merge"
    PHI_DIFFERENT_ROOTS = "phi-different-roots"
    PHI_UNKNOWN_INPUT = "phi-unknown-input"
    PARAMETER_ALIAS = "parameter-alias"
    GLOBAL_STATE = "global-state"
    FIELD_INSENSITIVITY = "field-insensitivity"
    FIELD_BASE_MAY_ALIAS = "field-base-may-alias"
    WHOLE_OBJECT_MUTATION = "whole-object-mutation"
    UNKNOWN_FIELD_EFFECT = "unknown-field-effect"
    INTERFACE_FIELD_LAYOUT_UNKNOWN = "interface-field-layout-unknown"
    NESTED_PATH_UNSUPPORTED = "nested-path-unsupported"
    EXTERNAL_FIELD_EFFECT = "external-field-effect"
    UNSUPPORTED_INSTRUCTION = "unsupported-instruction"
    FIELD_CONTENT_UNKNOWN = "field-content-unknown"
    COLLECTION_CONTENT_UNKNOWN = "collection-content-unknown"
    INTERFACE_BOX_BOUNDARY = "interface-box-boundary"
    EXCEPTION_MERGE = "exception-merge"
    OWNERSHIP_ROLE_MISMATCH = "ownership-role-mismatch"
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


@dataclass(frozen=True, order=True)
class FieldIdentity:
    """Canonical nominal field identity; spelling alone is never identity."""
    owner: str
    name: str
    index: int

    def __str__(self) -> str:
        return f"{self.owner}.{self.name}#{self.index}"


@dataclass(frozen=True)
class ObjectLocation:
    base: m.SSAValue


@dataclass(frozen=True)
class FieldLocation:
    base: m.SSAValue
    field: FieldIdentity


@dataclass(frozen=True)
class StructFieldLocation:
    base: m.SSAValue
    field: FieldIdentity


@dataclass(frozen=True)
class CollectionStorageLocation:
    base: m.SSAValue


@dataclass(frozen=True)
class CollectionLengthLocation:
    base: m.SSAValue


MemoryLocation = (ObjectLocation | FieldLocation | StructFieldLocation
                  | CollectionStorageLocation | CollectionLengthLocation)


@dataclass(frozen=True, order=True)
class ParameterFieldEffect:
    parameter: int
    field: FieldIdentity


@dataclass(frozen=True)
class FunctionSummary:
    function: str
    read_parameters: frozenset[int] = frozenset()
    modified_parameters: frozenset[int] = frozenset()
    read_fields: frozenset[ParameterFieldEffect] = frozenset()
    modified_fields: frozenset[ParameterFieldEffect] = frozenset()
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
        def fields(values):
            return "[" + ",".join(f"{item.parameter}:{item.field}" for item in sorted(values)) + "]"
        return (f"{self.function}: read={indexes(self.read_parameters)} "
                f"modify={indexes(self.modified_parameters)} read_fields={fields(self.read_fields)} "
                f"modify_fields={fields(self.modified_fields)} return_alias={indexes(self.returned_alias_parameters)} "
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
    def __init__(self, function: m.SSAFunction, summaries: dict[str, object] | None = None):
        self.function = function
        self.summaries = summaries or {}
        self._provenance: dict[m.SSAValue, Provenance] = {}
        self._definitions: dict[m.SSAValue, object] = {}
        for index, parameter in enumerate(function.parameters):
            kind = RootKind.PARAMETER if _is_reference_like(parameter.type) else RootKind.VALUE
            # A parameter has one exact semantic identity even when another
            # parameter may alias it.  Alias uncertainty is not provenance
            # uncertainty.
            self._provenance[parameter] = Provenance(
                frozenset({ProvenanceRoot(kind, str(index))}))
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
            if not changed: break
        # Unresolved cycles and malformed/nonconverging graphs fail closed with
        # a reason determined by their defining instruction.
        for instruction in instructions:
            result = getattr(instruction, "result", None)
            if isinstance(result, m.SSAValue) and result not in self._provenance:
                reason = (UnknownReason.PHI_UNKNOWN_INPUT
                          if isinstance(instruction, m.SSAPhi)
                          else UnknownReason.UNSUPPORTED_INSTRUCTION)
                self._provenance[result] = self._unknown(result, reason)

    def _instruction_provenance(self, instruction, result):
        if not _is_reference_like(result.type):
            return Provenance(frozenset({ProvenanceRoot(RootKind.VALUE, result.name)}))
        if isinstance(instruction, m.SSAConst) and isinstance(result.type, StringType):
            return Provenance(frozenset({ProvenanceRoot(RootKind.FRESH, result.name)}))
        if isinstance(instruction, (m.SSAClassNew, m.SSAArrayNew, m.SSAListNew,
                                    m.SSAArrayCopy, m.SSAListCopy, m.SSAArraySlice,
                                    m.SSAListSlice)):
            return Provenance(frozenset({ProvenanceRoot(RootKind.FRESH, result.name)}))
        if isinstance(instruction, m.SSACast) and _is_reference_like(instruction.value.type):
            return self._provenance.get(instruction.value)
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
            reason = (UnknownReason.PHI_UNKNOWN_INPUT if reasons
                      else UnknownReason.PHI_DIFFERENT_ROOTS)
            return Provenance(roots, reason)
        if isinstance(instruction, m.SSAClassGet):
            return self._unknown(result, UnknownReason.FIELD_CONTENT_UNKNOWN)
        if isinstance(instruction, (m.SSAArrayGet, m.SSAListGet)):
            return self._unknown(result, UnknownReason.COLLECTION_CONTENT_UNKNOWN)
        if isinstance(instruction, (m.SSACall, m.SSAInvoke, m.SSACallIndirect,
                                    m.SSAInvokeIndirect, m.SSAInterfaceCall,
                                    m.SSAInvokeInterface)):
            if isinstance(instruction, (m.SSACall, m.SSAInvoke)):
                from .trusted_helpers import ReturnedIdentity, trusted_helper_contract
                contract = trusted_helper_contract(instruction.builtin)
                if contract is not None:
                    if contract.identity is ReturnedIdentity.FRESH:
                        return Provenance(frozenset({ProvenanceRoot(RootKind.FRESH, result.name)}))
                    if (contract.identity in (ReturnedIdentity.ARGUMENT, ReturnedIdentity.BORROW)
                            and contract.argument is not None
                            and contract.argument < len(instruction.arguments)):
                        return self._provenance.get(instruction.arguments[contract.argument])
                summary = self.summaries.get(instruction.function)
                if summary is not None:
                    if getattr(summary, "returns_fresh", False):
                        return Provenance(frozenset({ProvenanceRoot(RootKind.FRESH, result.name)}))
                    returned = getattr(summary, "returned_alias_parameters",
                                       getattr(summary, "returned_parameters", frozenset()))
                    if len(returned) == 1:
                        index = next(iter(returned))
                        if index < len(instruction.arguments):
                            return self._provenance.get(instruction.arguments[index])
            reason = (UnknownReason.UNKNOWN_INDIRECT_TARGET if isinstance(instruction, (m.SSACallIndirect, m.SSAInvokeIndirect))
                      else UnknownReason.UNKNOWN_INTERFACE_IMPLEMENTATION if isinstance(instruction, (m.SSAInterfaceCall, m.SSAInvokeInterface))
                      else UnknownReason.UNKNOWN_RUNTIME_HELPER if instruction.builtin is not None
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

    def location_alias(self, left: MemoryLocation, right: MemoryLocation) -> AliasRelation:
        """Alias semantic locations without making byte-layout assumptions."""
        left_base, right_base = left.base, right.base
        base_relation = self.alias(left_base, right_base)
        if base_relation is AliasRelation.NO_ALIAS:
            return AliasRelation.NO_ALIAS
        left_field = getattr(left, "field", None)
        right_field = getattr(right, "field", None)
        if left_field is not None and right_field is not None:
            if left_field != right_field:
                # Nominal fields are distinct cells even through aliases.
                return AliasRelation.NO_ALIAS
            return base_relation
        if type(left) is type(right):
            return base_relation
        # Whole-object writes overlap fields. Collection storage includes its
        # logical length, while a field cell is separate from a referenced
        # collection subsequently loaded from it.
        if isinstance(left, ObjectLocation) or isinstance(right, ObjectLocation):
            return base_relation
        collection_locations = (CollectionStorageLocation, CollectionLengthLocation)
        if isinstance(left, collection_locations) and isinstance(right, collection_locations):
            return base_relation
        return AliasRelation.NO_ALIAS

    def verify(self) -> None:
        values = tuple(self._provenance)
        for value in values:
            provenance = self.provenance(value)
            if provenance.exact and not provenance.roots:
                raise ValueError("exact provenance must have one root")
            if self.alias(value, value) is not AliasRelation.MUST_ALIAS:
                raise ValueError("an SSA value must alias itself")
            definition = self._definitions.get(value)
            if isinstance(definition, m.SSACast) and _is_reference_like(definition.value.type):
                source = self.provenance(definition.value)
                if source.exact and provenance != source:
                    raise ValueError("identity-preserving cast changed exact root")
            if isinstance(definition, m.SSAPhi) and provenance.exact:
                incoming = [self.provenance(item) for _, item in definition.incoming]
                if (not incoming or any(not item.exact for item in incoming)
                        or any(item.roots != provenance.roots for item in incoming)):
                    raise ValueError("exact phi requires identical exact incoming roots")
        for index, left in enumerate(values):
            for right in values[index:]:
                if self.alias(left, right) is not self.alias(right, left):
                    raise ValueError("alias relation must be symmetric")

    def verify_locations(self, locations: tuple[MemoryLocation, ...]) -> None:
        for location in locations:
            if self.location_alias(location, location) is not AliasRelation.MUST_ALIAS:
                raise ValueError("a semantic memory location must alias itself")
        for index, left in enumerate(locations):
            for right in locations[index:]:
                if self.location_alias(left, right) is not self.location_alias(right, left):
                    raise ValueError("location alias relation must be symmetric")

    def location_debug_string(self, location: MemoryLocation) -> str:
        kind = type(location).__name__
        field = getattr(location, "field", None)
        suffix = f", field={field}" if field is not None else ""
        provenance = self.provenance(location.base)
        roots = ",".join(f"{root.kind.value}:{root.identity}" for root in sorted(provenance.roots))
        return f"{kind}(base={location.base.name}[{roots}]{suffix})"

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

    def effects(self, instruction, target: m.SSAValue | MemoryLocation) -> ModRefDecision:
        if not isinstance(target, m.SSAValue):
            return self._location_effects(instruction, target)
        if isinstance(instruction, (m.SSACall, m.SSAInvoke)) and instruction.builtin in {
            "__aether_retain", "__aether_release"
        }:
            # Ownership metadata is not Aether-level object/collection state.
            return ModRefDecision(ModRefEffect.NO_ACCESS)
        reads, writes = self._accesses(instruction)
        read_relations = [self.aliases.alias(value, target) for value in reads]
        write_relations = [self.aliases.alias(value, target) for value in writes]
        read = any(relation is not AliasRelation.NO_ALIAS for relation in read_relations)
        write = any(relation is not AliasRelation.NO_ALIAS for relation in write_relations)
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
                read_relations = [
                    self.aliases.alias(instruction.arguments[i], target)
                    for i in (summary.read_parameters | frozenset(item.parameter for item in summary.read_fields))
                    if i < len(instruction.arguments)
                ]
                write_relations = [
                    self.aliases.alias(instruction.arguments[i], target)
                    for i in (summary.modified_parameters | frozenset(item.parameter for item in summary.modified_fields))
                    if i < len(instruction.arguments)
                ]
                read = any(relation is not AliasRelation.NO_ALIAS for relation in read_relations)
                write = any(relation is not AliasRelation.NO_ALIAS for relation in write_relations)
                if summary.touches_global_state and _is_reference_like(target.type):
                    return ModRefDecision(ModRefEffect.UNKNOWN, UnknownReason.GLOBAL_STATE)
        effect = ModRefEffect.READ_MODIFY if read and write else ModRefEffect.READ if read else ModRefEffect.MODIFY if write else ModRefEffect.NO_ACCESS
        reason = (
            UnknownReason.PARAMETER_ALIAS
            if write and AliasRelation.MAY_ALIAS in write_relations
            else None
        )
        return ModRefDecision(effect, reason)

    def _location_effects(self, instruction, target: MemoryLocation) -> ModRefDecision:
        if isinstance(instruction, (m.SSACall, m.SSAInvoke)) and instruction.builtin in {
            "__aether_retain", "__aether_release"
        }:
            return ModRefDecision(ModRefEffect.NO_ACCESS)
        if isinstance(instruction, (m.SSACallIndirect, m.SSAInvokeIndirect)):
            return ModRefDecision(ModRefEffect.UNKNOWN, UnknownReason.UNKNOWN_INDIRECT_TARGET)
        if isinstance(instruction, (m.SSAInterfaceCall, m.SSAInvokeInterface)):
            return ModRefDecision(ModRefEffect.UNKNOWN, UnknownReason.INTERFACE_FIELD_LAYOUT_UNKNOWN)
        accesses = self._location_accesses(instruction)
        read_relations = [self.aliases.location_alias(location, target) for location in accesses[0]]
        write_relations = [self.aliases.location_alias(location, target) for location in accesses[1]]
        read = any(item is not AliasRelation.NO_ALIAS for item in read_relations)
        write = any(item is not AliasRelation.NO_ALIAS for item in write_relations)
        if isinstance(instruction, (m.SSACall, m.SSAInvoke)):
            summary = self.summaries.get(instruction.function)
            if summary is None:
                if instruction.writes_memory:
                    return ModRefDecision(ModRefEffect.UNKNOWN, UnknownReason.EXTERNAL_FIELD_EFFECT)
            else:
                for item in summary.read_fields:
                    if item.parameter < len(instruction.arguments):
                        location = FieldLocation(instruction.arguments[item.parameter], item.field)
                        read |= self.aliases.location_alias(location, target) is not AliasRelation.NO_ALIAS
                for item in summary.modified_fields:
                    if item.parameter < len(instruction.arguments):
                        location = FieldLocation(instruction.arguments[item.parameter], item.field)
                        write |= self.aliases.location_alias(location, target) is not AliasRelation.NO_ALIAS
                # Coarse parameter effects mean the callee could touch any field.
                for index in summary.read_parameters:
                    if index < len(instruction.arguments):
                        read |= self.aliases.location_alias(ObjectLocation(instruction.arguments[index]), target) is not AliasRelation.NO_ALIAS
                for index in summary.modified_parameters:
                    if index < len(instruction.arguments):
                        write |= self.aliases.location_alias(ObjectLocation(instruction.arguments[index]), target) is not AliasRelation.NO_ALIAS
                if summary.touches_global_state:
                    return ModRefDecision(ModRefEffect.UNKNOWN, UnknownReason.GLOBAL_STATE)
        effect = (ModRefEffect.READ_MODIFY if read and write else ModRefEffect.READ if read
                  else ModRefEffect.MODIFY if write else ModRefEffect.NO_ACCESS)
        reason = UnknownReason.FIELD_BASE_MAY_ALIAS if write and AliasRelation.MAY_ALIAS in write_relations else None
        return ModRefDecision(effect, reason)

    def _location_accesses(self, instruction):
        if isinstance(instruction, m.SSAClassGet):
            return ([FieldLocation(instruction.object, _field_identity(instruction.object, instruction))], [])
        if isinstance(instruction, m.SSAClassSet):
            return ([], [FieldLocation(instruction.object, _field_identity(instruction.object, instruction))])
        if isinstance(instruction, m.SSAStructGet):
            return ([StructFieldLocation(instruction.struct, _field_identity(instruction.struct, instruction))], [])
        # struct_set reconstructs a new SSA aggregate; it reads the old field
        # set but does not mutate the input value's storage.
        if isinstance(instruction, m.SSAStructSet):
            return ([ObjectLocation(instruction.struct)], [])
        reads, writes = _semantic_accesses(instruction)
        return ([ObjectLocation(value) for value in reads], [ObjectLocation(value) for value in writes])

    def _accesses(self, instruction):
        return _semantic_accesses(instruction)

    def may_read(self, instruction, target): return self.effects(instruction, target).effect.may_read
    def may_modify(self, instruction, target): return self.effects(instruction, target).effect.may_modify
    def preserves_memory_fact(self, instruction, target): return not self.may_modify(instruction, target)
    def preserves_field_fact(self, instruction, base, field):
        return self.preserves_memory_fact(instruction, FieldLocation(base, field))
    def field_effects(self, summary: FunctionSummary, parameter: int):
        return (frozenset(item.field for item in summary.read_fields if item.parameter == parameter),
                frozenset(item.field for item in summary.modified_fields if item.parameter == parameter))
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


def _field_identity(base: m.SSAValue, instruction) -> FieldIdentity:
    type_ = base.type.inner if isinstance(base.type, NullableType) else base.type
    if isinstance(type_, (ClassRefType, StructType)):
        owner = type_.name
    else:
        # This cannot make two unrelated nominal types compatible.
        owner = f"<{type(type_).__name__}>"
    return FieldIdentity(owner, instruction.field_name, instruction.field_index)


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
        total_instructions = sum(len(block.instructions) for fn in functions.values() for block in fn.blocks)
        for _ in range(max(1, total_parameters + total_instructions + len(functions) * 8 + 1)):
            updated = {name: self._summarize(fn, summaries, functions) for name, fn in sorted(functions.items())}
            if updated == summaries: return updated
            summaries = updated
        raise ValueError("mod/ref summaries did not converge")

    def _summarize(self, function, summaries, functions):
        aliases = AliasAnalysis(function, summaries); parameters = list(function.parameters)
        read, modified, returned = set(), set(), set()
        read_fields, modified_fields = set(), set()
        allocates = global_state = False
        may_throw = function.may_throw; may_trap = False; reasons = set()
        for block in function.blocks:
            for instruction in block.instructions:
                may_throw |= instruction.may_throw; may_trap |= instruction.may_trap; allocates |= instruction.allocates
                accesses = _semantic_accesses(instruction)
                field_read = isinstance(instruction, m.SSAClassGet)
                field_write = isinstance(instruction, m.SSAClassSet)
                for index, parameter in enumerate(parameters):
                    if field_read and aliases.alias(parameter, instruction.object) is not AliasRelation.NO_ALIAS:
                        read_fields.add(ParameterFieldEffect(index, _field_identity(instruction.object, instruction)))
                    elif any(aliases.alias(parameter, value) is not AliasRelation.NO_ALIAS for value in accesses[0]):
                        read.add(index)
                    if field_write and aliases.alias(parameter, instruction.object) is not AliasRelation.NO_ALIAS:
                        modified_fields.add(ParameterFieldEffect(index, _field_identity(instruction.object, instruction)))
                    elif any(aliases.alias(parameter, value) is not AliasRelation.NO_ALIAS for value in accesses[1]):
                        modified.add(index)
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
                        for effect in callee.read_fields:
                            if effect.parameter < len(instruction.arguments) and aliases.alias(parameter, instruction.arguments[effect.parameter]) is not AliasRelation.NO_ALIAS:
                                read_fields.add(ParameterFieldEffect(caller_index, effect.field))
                        for effect in callee.modified_fields:
                            if effect.parameter < len(instruction.arguments) and aliases.alias(parameter, instruction.arguments[effect.parameter]) is not AliasRelation.NO_ALIAS:
                                modified_fields.add(ParameterFieldEffect(caller_index, effect.field))
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
        # A return relation is exact only when every returned path has the same
        # parameter identity.  Seeing a parameter on merely one return path is
        # not a passthrough summary.
        returned = {
            index for index, parameter in enumerate(parameters)
            if returns and all(aliases.provenance(value) == aliases.provenance(parameter)
                               for value in returns)
        }
        if returns:
            provenances = [aliases.provenance(value) for value in returns]
            fresh = (all(item.exact and next(iter(item.roots)).kind is RootKind.FRESH
                         for item in provenances)
                     and len({next(iter(item.roots)) for item in provenances}) == 1)
        return FunctionSummary(
            function=function.name, read_parameters=frozenset(read),
            modified_parameters=frozenset(modified), read_fields=frozenset(read_fields),
            modified_fields=frozenset(modified_fields),
            returned_alias_parameters=frozenset(returned), returns_fresh=fresh,
            allocates=allocates, touches_global_state=global_state,
            may_throw=may_throw, may_trap=may_trap, unknown_reasons=frozenset(reasons),
        )

    @staticmethod
    def debug_string(summaries):
        return "\n".join(summaries[name].debug_string() for name in sorted(summaries))
