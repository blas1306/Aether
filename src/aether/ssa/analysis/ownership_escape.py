"""Conservative, exception-aware ownership and escape analysis.

This is deliberately analysis-only.  It describes ownership edges represented
by the current SSA; it neither inserts nor removes lifecycle operations.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, Flag, auto

from aether.ir.types import (
    ArrayType, ClassRefType, InterfaceType, ListType, MethodResultType,
    NullableType, StringType, StructType,
)
from aether.ssa import model as m
from aether.ssa.cfg import predecessors, reachable_blocks, successor_edges

from .alias_modref import (
    AliasAnalysis, FieldIdentity, Provenance, ProvenanceRoot, RootKind,
    UnknownReason as AliasUnknownReason,
)


class OwnershipState(Enum):
    OWNED = "owned"
    BORROWED = "borrowed"
    CONSUMED = "consumed"
    UNKNOWN = "unknown"


@dataclass(frozen=True, order=True)
class ComponentPath:
    """Nominal path to a component of a value-semantic aggregate.

    This is deliberately not a memory address.  Each step includes its nominal
    owner and index, so equally named fields in unrelated structs cannot be
    confused.
    """

    fields: tuple[FieldIdentity, ...]

    def child(self, field: FieldIdentity) -> ComponentPath:
        return ComponentPath(self.fields + (field,))

    def __str__(self) -> str:
        return ".".join(str(item) for item in self.fields)


@dataclass(frozen=True)
class ComponentProvenance:
    provenance: Provenance
    ownership: OwnershipState = OwnershipState.UNKNOWN


@dataclass(frozen=True)
class AggregateProvenance:
    """Sparse, deterministic component facts for one aggregate SSA value."""

    components: tuple[tuple[ComponentPath, ComponentProvenance], ...] = ()

    def component(self, path: ComponentPath) -> ComponentProvenance | None:
        return dict(self.components).get(path)


class EscapeMode(Flag):
    NO_ESCAPE = 0
    RETURN = auto()
    FIELD = auto()
    COLLECTION = auto()
    CALL = auto()
    INTERFACE = auto()
    GLOBAL_OR_MODULE = auto()
    EXCEPTION = auto()
    MAY_ESCAPE = auto()
    UNKNOWN = auto()


class OwnershipUnknownReason(Enum):
    UNKNOWN_CALL_ESCAPE = "unknown-call-escape"
    INDIRECT_CALL_ESCAPE = "indirect-call-escape"
    INTERFACE_ESCAPE = "interface-escape"
    FIELD_ESCAPE = "field-escape"
    COLLECTION_ESCAPE = "collection-escape"
    RETURN_ESCAPE = "return-escape"
    EXCEPTION_PATH_OWNERSHIP = "exception-path-ownership"
    PHI_OWNERSHIP_MERGE = "phi-ownership-merge"
    ALIAS_UNCERTAINTY = "alias-uncertainty"
    NESTED_AGGREGATE = "nested-aggregate"
    MISSING_POSTDOMINANCE = "missing-postdominance"
    OTHER = "other"


class ArcPairClassification(Enum):
    LOCALLY_PROVABLE = "locally-provable"
    NEEDS_ESCAPE_INFO = "needs-escape-info"
    NEEDS_PATH_SENSITIVE_OWNERSHIP = "needs-path-sensitive-ownership"
    BLOCKED_BY_EXCEPTION = "blocked-by-exception"
    BLOCKED_BY_ALIAS = "blocked-by-alias"
    NOT_REDUNDANT = "not-redundant"


class ArcPairSemanticStatus(Enum):
    SEMANTICALLY_PROVABLE = "semantically-provable"
    NOT_SEMANTICALLY_PROVABLE = "not-semantically-provable"


class ArcPairSemanticReason(Enum):
    PROVENANCE_UNKNOWN = "provenance-unknown"
    METHODRESULT = "methodresult"
    NESTED_AGGREGATE = "nested-aggregate"
    INTERFACE = "interface"
    CONSTRUCTOR_LIFECYCLE = "constructor-lifecycle"
    ESCAPE = "escape"
    OWNERSHIP_CONFLICT = "ownership-conflict"
    EXCEPTION_LIFETIME = "exception-lifetime"
    NORMAL_JOIN = "normal-join"
    ALIAS = "alias"
    NOT_REDUNDANT = "not-redundant"


@dataclass(frozen=True)
class ArcPairSemanticDecision:
    """Canonical, phase-independent ARC pair safety decision."""

    status: ArcPairSemanticStatus
    reasons: frozenset[ArcPairSemanticReason] = frozenset()
    provenance: Provenance | None = None
    escape: EscapeFact | None = None
    ownership: OwnershipState = OwnershipState.UNKNOWN

    @property
    def semantically_provable(self) -> bool:
        return self.status is ArcPairSemanticStatus.SEMANTICALLY_PROVABLE


@dataclass(frozen=True)
class EscapeFact:
    modes: EscapeMode = EscapeMode.NO_ESCAPE
    normal: bool = False
    exceptional: bool = False
    first_point: str | None = None
    reasons: frozenset[OwnershipUnknownReason] = frozenset()

    @property
    def may_escape(self) -> bool:
        return self.modes != EscapeMode.NO_ESCAPE


@dataclass(frozen=True)
class OwnershipFrame:
    states: tuple[tuple[m.SSAValue, OwnershipState], ...] = ()

    def state(self, value: m.SSAValue) -> OwnershipState:
        return dict(self.states).get(value, OwnershipState.UNKNOWN)


@dataclass(frozen=True)
class ArcPairCandidate:
    value: m.SSAValue
    retain_block: str
    retain_index: int
    release_block: str
    release_index: int
    classification: ArcPairClassification
    reasons: frozenset[OwnershipUnknownReason] = frozenset()

    def debug_string(self) -> str:
        reasons = ",".join(sorted(reason.value for reason in self.reasons))
        return (f"{self.value.name}: {self.retain_block}:{self.retain_index} -> "
                f"{self.release_block}:{self.release_index} {self.classification.value} [{reasons}]")


@dataclass(frozen=True)
class OwnershipFunctionSummary:
    function: str
    retained_parameters: frozenset[int] = frozenset()
    consumed_parameters: frozenset[int] = frozenset()
    stored_field_parameters: frozenset[int] = frozenset()
    stored_collection_parameters: frozenset[int] = frozenset()
    returned_parameters: frozenset[int] = frozenset()
    escaping_parameters: frozenset[int] = frozenset()
    returns_fresh: bool = False
    may_escape_exceptionally: bool = False
    unknown_reasons: frozenset[OwnershipUnknownReason] = frozenset()

    def debug_string(self) -> str:
        show = lambda values: "[" + ",".join(map(str, sorted(values))) + "]"
        reasons = ",".join(sorted(reason.value for reason in self.unknown_reasons))
        return (f"{self.function}: retain={show(self.retained_parameters)} "
                f"consume={show(self.consumed_parameters)} field={show(self.stored_field_parameters)} "
                f"collection={show(self.stored_collection_parameters)} return={show(self.returned_parameters)} "
                f"escape={show(self.escaping_parameters)} fresh={str(self.returns_fresh).lower()} "
                f"exceptional={str(self.may_escape_exceptionally).lower()} unknown=[{reasons}]")


_REFERENCE_TYPES = (ClassRefType, ArrayType, ListType, InterfaceType, StringType)


def is_reference_like(type_) -> bool:
    return is_reference_like(type_.inner) if isinstance(type_, NullableType) else isinstance(type_, _REFERENCE_TYPES)


def has_unsupported_nested_owned_payload(type_) -> bool:
    if isinstance(type_, NullableType):
        return has_unsupported_nested_owned_payload(type_.inner)
    if isinstance(type_, (ArrayType, ListType)):
        element = type_.element
        return (is_reference_like(element)
                or isinstance(element, (StructType, MethodResultType))
                or has_unsupported_nested_owned_payload(element))
    return False


def _call_arguments(instruction) -> tuple[m.SSAValue, ...]:
    arguments = getattr(instruction, "arguments", ())
    receiver = getattr(instruction, "receiver", None)
    return ((receiver,) if isinstance(receiver, m.SSAValue) else ()) + tuple(arguments)


class PostDominatorAnalysis:
    """Post-dominators over the complete normal and exceptional SSA CFG."""

    def __init__(self, function: m.SSAFunction):
        self.function = function
        self._sets = self._compute()

    def _compute(self) -> dict[str, frozenset[str]]:
        reachable = set(reachable_blocks(self.function)); blocks = {b.name: b for b in self.function.blocks}
        if not reachable:
            return {}
        exit_node = "<exit>"; universe = reachable | {exit_node}
        successors = {}
        for name in reachable:
            targets = {e.target for e in successor_edges(blocks[name]) if e.target in reachable}
            successors[name] = targets or {exit_node}
        result = {name: ({name} if name == exit_node else set(universe)) for name in universe}
        changed = True
        while changed:
            changed = False
            for name in sorted(reachable):
                value = {name} | set.intersection(*(result[target] for target in successors[name]))
                if value != result[name]:
                    result[name] = value; changed = True
        return {name: frozenset(values) for name, values in result.items() if name != exit_node}

    def post_dominates(self, post_dominator: str, block: str) -> bool:
        return post_dominator in self._sets.get(block, frozenset())


class OwnershipEscapeAnalysis:
    """Block/edge-sensitive, join-by-union ownership foundation.

    Parameters are borrowed by the current ABI. Fresh allocations and owned
    call results start owned. Collection borrows and caught payloads are
    borrowed. Unknown calls fail closed by marking reference arguments as
    MAY_ESCAPE. Escape facts are accumulated per provenance root so aliases do
    not accidentally create independent ownership counts.
    """

    def __init__(self, function: m.SSAFunction,
                 summaries: dict[str, OwnershipFunctionSummary] | None = None,
                 structs: tuple[object, ...] | list[object] = ()):
        self.function = function
        self.summaries = summaries or {}
        self.aliases = AliasAnalysis(function, self.summaries)
        self._structs = {item.name: item for item in structs}
        self._aggregate: dict[m.SSAValue, AggregateProvenance] = {}
        self._component_results: dict[m.SSAValue, ComponentProvenance] = {}
        self._states: dict[m.SSAValue, OwnershipState] = {}
        self._escapes: dict[ProvenanceRoot, EscapeFact] = {}
        self._in: dict[str, OwnershipFrame] = {}
        self._out: dict[str, OwnershipFrame] = {}
        self._before: dict[tuple[str, int], OwnershipFrame] = {}
        self._exception_reachable = self._exceptional_reachability()
        self._analyze_aggregate_provenance()
        self._analyze()

    @staticmethod
    def _component_fact(value: m.SSAValue, aliases: AliasAnalysis,
                        ownership: OwnershipState = OwnershipState.UNKNOWN) -> ComponentProvenance:
        provenance = aliases.provenance(value)
        if ownership is OwnershipState.UNKNOWN and provenance.exact:
            kind = next(iter(provenance.roots)).kind
            if kind is RootKind.FRESH: ownership = OwnershipState.OWNED
            elif kind is RootKind.PARAMETER: ownership = OwnershipState.BORROWED
        return ComponentProvenance(provenance, ownership)

    @staticmethod
    def _aggregate_of(items: dict[ComponentPath, ComponentProvenance]) -> AggregateProvenance:
        return AggregateProvenance(tuple(sorted(items.items(), key=lambda item: item[0])))

    def _field(self, owner, index: int, name: str) -> FieldIdentity:
        owner_name = owner.name if isinstance(owner, StructType) else str(owner)
        return FieldIdentity(owner_name, name, index)

    def _prefix(self, field: FieldIdentity, aggregate: AggregateProvenance) -> dict[ComponentPath, ComponentProvenance]:
        return {ComponentPath((field,) + path.fields): fact
                for path, fact in aggregate.components}

    def _parameter_components(self, parameter: m.SSAValue, index: int,
                              type_, active: frozenset[str] = frozenset()) -> dict[ComponentPath, ComponentProvenance]:
        if not isinstance(type_, StructType) or type_.name in active:
            return {}
        definition = self._structs.get(type_.name)
        if definition is None:
            return {}
        result = {}
        for field_index, (name, field_type) in enumerate(definition.fields):
            field = self._field(type_, field_index, name); path = ComponentPath((field,))
            if is_reference_like(field_type):
                root = ProvenanceRoot(RootKind.PARAMETER, f"{index}:{path}")
                result[path] = ComponentProvenance(Provenance(frozenset({root})), OwnershipState.BORROWED)
            elif isinstance(field_type, StructType):
                nested = self._parameter_components(parameter, index, field_type, active | {type_.name})
                result.update(self._prefix(field, self._aggregate_of(nested)))
        return result

    def _analyze_aggregate_provenance(self) -> None:
        """Monotone, component-wise aggregate propagation over SSA values."""
        for index, parameter in enumerate(self.function.parameters):
            facts = self._parameter_components(parameter, index, parameter.type)
            if facts: self._aggregate[parameter] = self._aggregate_of(facts)
        instructions = [item for block in self.function.blocks for item in block.instructions]
        for _ in range(max(1, len(instructions) + 1)):
            changed = False
            for instruction in instructions:
                result = getattr(instruction, "result", None)
                if not isinstance(result, m.SSAValue): continue
                facts = self._aggregate_instruction(instruction)
                if facts is not None and self._aggregate.get(result) != facts:
                    self._aggregate[result] = facts; changed = True
            if not changed: break

    def _aggregate_instruction(self, instruction) -> AggregateProvenance | None:
        result = instruction.result
        if isinstance(instruction, m.SSAStructNew):
            items = {}
            for index, value in enumerate(instruction.fields):
                name = str(index)
                definition = self._structs.get(result.type.name) if isinstance(result.type, StructType) else None
                if definition is not None and index < len(definition.fields): name = definition.fields[index][0]
                field = self._field(result.type, index, name); path = ComponentPath((field,))
                if is_reference_like(value.type): items[path] = self._component_fact(value, self.aliases)
                if value in self._aggregate: items.update(self._prefix(field, self._aggregate[value]))
            return self._aggregate_of(items)
        if isinstance(instruction, m.SSAStructSet):
            base = dict(self._aggregate.get(instruction.struct, AggregateProvenance()).components)
            field = self._field(instruction.struct.type, instruction.field_index, instruction.field_name)
            base = {path: fact for path, fact in base.items()
                    if not path.fields or path.fields[0] != field}
            path = ComponentPath((field,))
            if is_reference_like(instruction.value.type):
                base[path] = self._component_fact(instruction.value, self.aliases)
            if instruction.value in self._aggregate:
                base.update(self._prefix(field, self._aggregate[instruction.value]))
            return self._aggregate_of(base)
        if isinstance(instruction, m.SSAStructGet):
            source = self._aggregate.get(instruction.struct)
            if source is None: return None
            field = self._field(instruction.struct.type, instruction.field_index, instruction.field_name)
            direct = source.component(ComponentPath((field,)))
            if direct is not None:
                self._component_results[result] = direct
            if not isinstance(result.type, StructType): return None
            return self._aggregate_of({ComponentPath(path.fields[1:]): fact
                for path, fact in source.components if path.fields and path.fields[0] == field
                and len(path.fields) > 1})
        if isinstance(instruction, m.SSAMethodResultNew):
            receiver = FieldIdentity("MethodResult", "receiver", 0)
            items = self._prefix(receiver, self._aggregate.get(instruction.receiver, AggregateProvenance()))
            if is_reference_like(instruction.receiver.type):
                items[ComponentPath((receiver,))] = self._component_fact(instruction.receiver, self.aliases)
            if instruction.value is not None:
                value_field = FieldIdentity("MethodResult", "value", 1)
                if is_reference_like(instruction.value.type):
                    items[ComponentPath((value_field,))] = self._component_fact(instruction.value, self.aliases)
                items.update(self._prefix(value_field, self._aggregate.get(instruction.value, AggregateProvenance())))
            return self._aggregate_of(items)
        if isinstance(instruction, (m.SSAMethodResultReceiver, m.SSAMethodResultValue)):
            source = self._aggregate.get(instruction.method_result)
            if source is None: return None
            wanted = "receiver" if isinstance(instruction, m.SSAMethodResultReceiver) else "value"
            direct = next((fact for path, fact in source.components
                           if len(path.fields) == 1 and path.fields[0].name == wanted), None)
            if direct is not None:
                self._component_results[result] = direct
            if not isinstance(result.type, StructType): return None
            return self._aggregate_of({ComponentPath(path.fields[1:]): fact
                for path, fact in source.components if path.fields and path.fields[0].name == wanted
                and len(path.fields) > 1})
        if isinstance(instruction, m.SSAPhi) and isinstance(result.type, (StructType, MethodResultType)):
            incoming = [self._aggregate.get(value) for _, value in instruction.incoming]
            if not incoming or any(item is None for item in incoming): return None
            maps = [dict(item.components) for item in incoming if item is not None]
            paths = set().union(*(item.keys() for item in maps)); merged = {}
            for path in paths:
                facts = [item.get(path) for item in maps]
                if any(item is None for item in facts):
                    continue
                provenances = [item.provenance for item in facts if item is not None]
                ownerships = [item.ownership for item in facts if item is not None]
                if all(item.exact for item in provenances) and all(item == provenances[0] for item in provenances):
                    role = ownerships[0] if all(item is ownerships[0] for item in ownerships) else OwnershipState.UNKNOWN
                    merged[path] = ComponentProvenance(provenances[0], role)
                else:
                    roots = frozenset().union(*(item.roots for item in provenances))
                    merged[path] = ComponentProvenance(Provenance(roots, AliasUnknownReason.PHI_DIFFERENT_ROOTS))
            return self._aggregate_of(merged)
        if isinstance(instruction, m.SSACast):
            return self._aggregate.get(instruction.value)
        return None

    def _exceptional_reachability(self) -> set[str]:
        blocks = {block.name: block for block in self.function.blocks}; work = []
        for block in self.function.blocks:
            work.extend(edge.target for edge in successor_edges(block) if edge.kind == "exceptional")
        seen = set()
        while work:
            name = work.pop()
            if name in seen or name not in blocks: continue
            seen.add(name); work.extend(edge.target for edge in successor_edges(blocks[name]))
        return seen

    @staticmethod
    def _join_state(left: OwnershipState, right: OwnershipState) -> OwnershipState:
        return left if left is right else OwnershipState.UNKNOWN

    def _analyze(self) -> None:
        for parameter in self.function.parameters:
            if is_reference_like(parameter.type) or isinstance(parameter.type, (StructType, MethodResultType)):
                self._states[parameter] = OwnershipState.BORROWED
        pred = predecessors(self.function); blocks = {block.name: block for block in self.function.blocks}
        order = reachable_blocks(self.function)
        for _ in range(max(1, len(order) * (len(self._states) + 4))):
            changed = False
            for name in order:
                incoming = [dict(self._out[e.source].states) for e in pred[name] if e.source in self._out]
                state = dict(incoming[0]) if incoming else dict(self._states)
                for other in incoming[1:]:
                    for value in set(state) | set(other):
                        state[value] = self._join_state(state.get(value, OwnershipState.UNKNOWN), other.get(value, OwnershipState.UNKNOWN))
                frame = OwnershipFrame(tuple(sorted(state.items(), key=lambda item: item[0].name)))
                if self._in.get(name) != frame: self._in[name] = frame; changed = True
                for index, instruction in enumerate(blocks[name].instructions):
                    self._before[(name, index)] = OwnershipFrame(tuple(sorted(
                        state.items(), key=lambda item: item[0].name)))
                    self._transfer(instruction, state, name, index)
                frame = OwnershipFrame(tuple(sorted(state.items(), key=lambda item: item[0].name)))
                if self._out.get(name) != frame: self._out[name] = frame; changed = True
            if not changed: break
        else:
            for value in self._states: self._states[value] = OwnershipState.UNKNOWN

    def _set_escape(self, value: m.SSAValue, mode: EscapeMode, block: str, index: int,
                    reason: OwnershipUnknownReason, *, exceptional: bool | None = None) -> None:
        aggregate = self._aggregate.get(value)
        if not is_reference_like(value.type) and aggregate is None: return
        exceptional = block in self._exception_reachable if exceptional is None else exceptional
        roots = set(self.provenance(value).roots)
        if aggregate is not None:
            roots.update(root for _, fact in aggregate.components
                         for root in fact.provenance.roots)
        for root in roots:
            old = self._escapes.get(root, EscapeFact())
            point = old.first_point or f"{block}:{index}"
            self._escapes[root] = EscapeFact(old.modes | mode, old.normal or not exceptional,
                old.exceptional or exceptional, point, old.reasons | {reason})

    def _transfer(self, instruction, state, block, index) -> None:
        result = getattr(instruction, "result", None)
        if isinstance(result, m.SSAValue) and is_reference_like(result.type):
            if isinstance(instruction, (m.SSAExceptionPayload,)) or (
                isinstance(instruction, (m.SSAArrayGet, m.SSAListGet)) and instruction.borrowed
            ): state[result] = OwnershipState.BORROWED
            elif isinstance(instruction, (m.SSAClassNew, m.SSAArrayNew, m.SSAListNew,
                    m.SSAArrayCopy, m.SSAListCopy, m.SSAArraySlice, m.SSAListSlice,
                    m.SSAInterfaceConstruct, m.SSACall, m.SSAInvoke, m.SSACallIndirect,
                    m.SSAInvokeIndirect, m.SSAInterfaceCall, m.SSAInvokeInterface)):
                state[result] = OwnershipState.OWNED
            elif isinstance(instruction, m.SSAPhi):
                states = [state.get(value, OwnershipState.UNKNOWN) for _, value in instruction.incoming]
                state[result] = states[0] if states and all(item is states[0] for item in states) else OwnershipState.UNKNOWN
            elif isinstance(instruction, m.SSACast):
                state[result] = state.get(instruction.value, OwnershipState.UNKNOWN)
            elif isinstance(instruction, m.SSAConst) and isinstance(result.type, StringType):
                state[result] = OwnershipState.OWNED
            else: state[result] = OwnershipState.UNKNOWN
            previous = self._states.get(result)
            self._states[result] = state[result] if previous is None else self._join_state(previous, state[result])
        elif isinstance(result, m.SSAValue) and isinstance(result.type, (StructType, MethodResultType)):
            if isinstance(instruction, (m.SSAStructNew, m.SSAStructSet, m.SSAMethodResultNew)):
                state[result] = OwnershipState.OWNED
            elif isinstance(instruction, (m.SSAStructGet, m.SSAMethodResultReceiver,
                                          m.SSAMethodResultValue, m.SSACast)):
                source = getattr(instruction, "struct", getattr(instruction, "method_result",
                         getattr(instruction, "value", None)))
                state[result] = state.get(source, OwnershipState.UNKNOWN)
            elif isinstance(instruction, m.SSAPhi):
                states = [state.get(value, OwnershipState.UNKNOWN) for _, value in instruction.incoming]
                state[result] = states[0] if states and all(item is states[0] for item in states) else OwnershipState.UNKNOWN
            else:
                state[result] = OwnershipState.UNKNOWN
            previous = self._states.get(result)
            self._states[result] = state[result] if previous is None else self._join_state(previous, state[result])
        if isinstance(instruction, m.SSAReturn) and instruction.value is not None:
            self._set_escape(instruction.value, EscapeMode.RETURN, block, index, OwnershipUnknownReason.RETURN_ESCAPE)
        elif isinstance(instruction, m.SSAClassSet):
            self._set_escape(instruction.value, EscapeMode.FIELD, block, index, OwnershipUnknownReason.FIELD_ESCAPE)
        elif isinstance(instruction, (m.SSAArraySet, m.SSAListSet, m.SSAListPush, m.SSAListInsert)):
            self._set_escape(instruction.value, EscapeMode.COLLECTION, block, index, OwnershipUnknownReason.COLLECTION_ESCAPE)
        elif isinstance(instruction, m.SSAInterfaceConstruct):
            self._set_escape(instruction.carrier, EscapeMode.INTERFACE, block, index, OwnershipUnknownReason.INTERFACE_ESCAPE)
        if isinstance(instruction, (m.SSAThrow, m.SSARethrow, m.SSAPropagate)):
            self._set_escape(instruction.event, EscapeMode.EXCEPTION, block, index,
                             OwnershipUnknownReason.EXCEPTION_PATH_OWNERSHIP, exceptional=True)
            state[instruction.event] = OwnershipState.CONSUMED
        if isinstance(instruction, m.SSAExceptionDestroy): state[instruction.event] = OwnershipState.CONSUMED
        if isinstance(instruction, (m.SSACall, m.SSAInvoke, m.SSACallIndirect, m.SSAInvokeIndirect,
                                    m.SSAInterfaceCall, m.SSAInvokeInterface)):
            self._apply_call(instruction, state, block, index)

    def _apply_call(self, instruction, state, block, index) -> None:
        arguments = _call_arguments(instruction)
        builtin = getattr(instruction, "builtin", None)
        if builtin == "__aether_retain": return
        if builtin == "__aether_release":
            if arguments: state[arguments[0]] = OwnershipState.CONSUMED
            return
        summary = self.summaries.get(getattr(instruction, "function", ""))
        if summary is not None:
            for parameter in summary.escaping_parameters:
                if parameter < len(arguments):
                    self._set_escape(arguments[parameter], EscapeMode.CALL, block, index, OwnershipUnknownReason.UNKNOWN_CALL_ESCAPE)
                    if summary.may_escape_exceptionally and isinstance(instruction, (m.SSAInvoke, m.SSAInvokeIndirect, m.SSAInvokeInterface)):
                        self._set_escape(arguments[parameter], EscapeMode.CALL, block, index,
                                         OwnershipUnknownReason.EXCEPTION_PATH_OWNERSHIP, exceptional=True)
            for parameter in summary.consumed_parameters:
                if parameter < len(arguments): state[arguments[parameter]] = OwnershipState.CONSUMED
            return
        if getattr(instruction, "builtin", None) is not None and not instruction.writes_memory:
            return
        reason = (OwnershipUnknownReason.INDIRECT_CALL_ESCAPE
                  if isinstance(instruction, (m.SSACallIndirect, m.SSAInvokeIndirect))
                  else OwnershipUnknownReason.INTERFACE_ESCAPE
                  if isinstance(instruction, (m.SSAInterfaceCall, m.SSAInvokeInterface))
                  else OwnershipUnknownReason.UNKNOWN_CALL_ESCAPE)
        mode = EscapeMode.INTERFACE | EscapeMode.MAY_ESCAPE if reason is OwnershipUnknownReason.INTERFACE_ESCAPE else EscapeMode.CALL | EscapeMode.MAY_ESCAPE
        for argument in arguments:
            self._set_escape(argument, mode, block, index, reason)
            if isinstance(instruction, (m.SSAInvoke, m.SSAInvokeIndirect, m.SSAInvokeInterface)):
                self._set_escape(argument, mode, block, index,
                                 OwnershipUnknownReason.EXCEPTION_PATH_OWNERSHIP, exceptional=True)

    def ownership_state(self, value: m.SSAValue, block: str | None = None) -> OwnershipState:
        if block is not None and block in self._out: return self._out[block].state(value)
        return self._states.get(value, OwnershipState.UNKNOWN)

    def ownership_state_before(self, value: m.SSAValue, block: str,
                               index: int) -> OwnershipState:
        return self._before.get((block, index), OwnershipFrame()).state(value)

    def provenance(self, value: m.SSAValue) -> Provenance:
        component = self._component_results.get(value)
        return component.provenance if component is not None else self.aliases.provenance(value)
    def aggregate_provenance(self, value: m.SSAValue) -> AggregateProvenance:
        return self._aggregate.get(value, AggregateProvenance())

    def component_provenance(self, value: m.SSAValue,
                             path: ComponentPath) -> ComponentProvenance | None:
        return self.aggregate_provenance(value).component(path)

    def aggregate_coverage(self) -> dict[str, int]:
        facts = [fact for aggregate in self._aggregate.values()
                 for _, fact in aggregate.components]
        nested = [path for aggregate in self._aggregate.values()
                  for path, _ in aggregate.components if len(path.fields) > 1]
        definitions = {getattr(item, "result", None): item
                       for block in self.function.blocks for item in block.instructions}
        phi_values = {value for value in self._aggregate
                      if isinstance(definitions.get(value), m.SSAPhi)}
        method_values = {value for value in self._aggregate
                         if isinstance(definitions.get(value), (m.SSAMethodResultNew,
                                                               m.SSAMethodResultReceiver,
                                                               m.SSAMethodResultValue))}
        return {
            "aggregate_values_inspected": len(self._aggregate),
            "ownership_bearing_components": len(facts),
            "exact_components": sum(fact.provenance.exact for fact in facts),
            "unknown_components": sum(not fact.provenance.exact for fact in facts),
            "nested_exact_components": sum(1 for aggregate in self._aggregate.values()
                for path, fact in aggregate.components
                if len(path.fields) > 1 and fact.provenance.exact),
            "phi_preserved_components": sum(fact.provenance.exact
                for value in phi_values for _, fact in self._aggregate[value].components),
            "call_return_components": 0,
            "method_result_components": sum(len(self._aggregate[value].components)
                                            for value in method_values),
            "constructor_result_components": 0,
        }
    def is_fresh(self, value: m.SSAValue) -> bool:
        provenance = self.provenance(value)
        return provenance.exact and next(iter(provenance.roots)).kind is RootKind.FRESH
    def escape_fact(self, value: m.SSAValue) -> EscapeFact:
        facts = [self._escapes.get(root, EscapeFact()) for root in self.provenance(value).roots]
        modes = EscapeMode.NO_ESCAPE; normal = exceptional = False; point = None; reasons = set()
        for fact in facts:
            modes |= fact.modes; normal |= fact.normal; exceptional |= fact.exceptional
            point = point or fact.first_point; reasons.update(fact.reasons)
        return EscapeFact(modes, normal, exceptional, point, frozenset(reasons))
    def escape_modes(self, value: m.SSAValue) -> EscapeMode: return self.escape_fact(value).modes
    def may_escape(self, value: m.SSAValue) -> bool: return self.escape_fact(value).may_escape

    def candidate_arc_pairs(self) -> tuple[ArcPairCandidate, ...]:
        postdom = PostDominatorAnalysis(self.function); pending = []; result = []
        for block in self.function.blocks:
            for index, instruction in enumerate(block.instructions):
                if not isinstance(instruction, (m.SSACall, m.SSAInvoke)) or not instruction.arguments: continue
                if instruction.builtin == "__aether_retain": pending.append((instruction.arguments[0], block.name, index))
                elif instruction.builtin == "__aether_release":
                    value = instruction.arguments[0]
                    match = next((item for item in reversed(pending) if item[0] == value), None)
                    if match is None: continue
                    pending.remove(match); _, retain_block, retain_index = match
                    fact = self.escape_fact(value); reasons = set(fact.reasons)
                    if fact.exceptional: classification = ArcPairClassification.BLOCKED_BY_EXCEPTION
                    elif fact.may_escape: classification = ArcPairClassification.NEEDS_ESCAPE_INFO
                    elif not postdom.post_dominates(block.name, retain_block):
                        classification = ArcPairClassification.NEEDS_PATH_SENSITIVE_OWNERSHIP
                    elif retain_block == block.name and retain_index >= index:
                        classification = ArcPairClassification.NOT_REDUNDANT
                    else: classification = ArcPairClassification.LOCALLY_PROVABLE
                    result.append(ArcPairCandidate(value, retain_block, retain_index, block.name, index,
                                                   classification, frozenset(reasons)))
        return tuple(result)

    def classify_pair(self, pair: ArcPairCandidate) -> ArcPairClassification:
        """Return the authoritative O2.8 classification for ``pair``.

        Transformations deliberately query this method instead of trusting a
        classification copied or reconstructed by a caller.
        """
        for candidate in self.candidate_arc_pairs():
            if candidate == pair:
                return candidate.classification
        return ArcPairClassification.NOT_REDUNDANT

    def classify_arc_pair(self, pair: ArcPairCandidate) -> ArcPairSemanticDecision:
        """Classify mandatory semantic safety before any phase structure check.

        This is the sole authority consumed by audits and productive ARC
        transforms.  In particular, an unknown provenance reason can never be
        promoted merely because the retain and release use the same SSA name.
        """
        provenance = self.provenance(pair.value)
        escape = self.escape_fact(pair.value)
        ownership = self.ownership_state_before(
            pair.value, pair.retain_block, pair.retain_index,
        )
        reasons: set[ArcPairSemanticReason] = set()
        if not provenance.exact or len(provenance.roots) != 1:
            reasons.add(ArcPairSemanticReason.PROVENANCE_UNKNOWN)
        type_ = pair.value.type
        if isinstance(type_, MethodResultType):
            reasons.add(ArcPairSemanticReason.METHODRESULT)
        # A collection object's identity is independent of its aggregate
        # elements.  Element-sensitive provenance remains intentionally out of
        # scope, but must not poison ARC reasoning about the collection itself.
        if isinstance(type_, (StructType, MethodResultType)):
            reasons.add(ArcPairSemanticReason.NESTED_AGGREGATE)
        if isinstance(type_, InterfaceType):
            reasons.add(ArcPairSemanticReason.INTERFACE)
        lowered_name = self.function.name.lower()
        if "constructor" in lowered_name or lowered_name.endswith(".__init__"):
            reasons.add(ArcPairSemanticReason.CONSTRUCTOR_LIFECYCLE)
        classification = self.classify_pair(pair)
        if escape.may_escape or classification is ArcPairClassification.NEEDS_ESCAPE_INFO:
            reasons.add(ArcPairSemanticReason.ESCAPE)
        if escape.exceptional or classification is ArcPairClassification.BLOCKED_BY_EXCEPTION:
            reasons.add(ArcPairSemanticReason.EXCEPTION_LIFETIME)
        if classification is ArcPairClassification.NEEDS_PATH_SENSITIVE_OWNERSHIP:
            reasons.add(ArcPairSemanticReason.NORMAL_JOIN)
        if classification is ArcPairClassification.BLOCKED_BY_ALIAS:
            reasons.add(ArcPairSemanticReason.ALIAS)
        if classification is ArcPairClassification.NOT_REDUNDANT:
            reasons.add(ArcPairSemanticReason.NOT_REDUNDANT)
        if ownership in (OwnershipState.CONSUMED, OwnershipState.UNKNOWN):
            reasons.add(ArcPairSemanticReason.OWNERSHIP_CONFLICT)
        status = (ArcPairSemanticStatus.NOT_SEMANTICALLY_PROVABLE if reasons
                  else ArcPairSemanticStatus.SEMANTICALLY_PROVABLE)
        return ArcPairSemanticDecision(status, frozenset(reasons), provenance,
                                       escape, ownership)

    def verify(self) -> None:
        for frame in (*self._in.values(), *self._out.values()):
            for value, state in frame.states:
                if state is OwnershipState.BORROWED and self.is_fresh(value):
                    raise ValueError("fresh value cannot be an independent borrowed owner")
        for pair in self.candidate_arc_pairs():
            if pair.classification is ArcPairClassification.LOCALLY_PROVABLE and self.escape_fact(pair.value).exceptional:
                raise ValueError("ARC candidate omitted an exceptional ownership path")

    def debug_string(self) -> str:
        lines = []
        for value in sorted(self._states, key=lambda item: item.name):
            fact = self.escape_fact(value); modes = ",".join(mode.name.lower() for mode in EscapeMode if mode and fact.modes & mode)
            roots = ",".join(f"{root.kind.value}:{root.identity}" for root in sorted(self.provenance(value).roots))
            reasons = ",".join(sorted(reason.value for reason in fact.reasons))
            lines.append(f"{value.name}: {self.ownership_state(value).value} roots=[{roots}] escape=[{modes}] reasons=[{reasons}]")
        lines.extend("arc " + pair.debug_string() for pair in self.candidate_arc_pairs())
        return "\n".join(lines)


class OwnershipSummaryAnalysis:
    """Monotone direct-call summary fixed point, including recursive SCCs."""

    def compute(self, module: m.SSAModule) -> dict[str, OwnershipFunctionSummary]:
        functions = {function.name: function for function in module.functions}
        summaries = {name: OwnershipFunctionSummary(name) for name in functions}
        limit = 1 + sum(len(fn.parameters) * 7 + sum(len(b.instructions) for b in fn.blocks) for fn in functions.values())
        for _ in range(max(1, limit)):
            updated = {name: self._summarize(fn, summaries) for name, fn in sorted(functions.items())}
            if updated == summaries: return updated
            summaries = updated
        raise ValueError("ownership summaries did not converge")

    def _summarize(self, function, summaries):
        analysis = OwnershipEscapeAnalysis(function, summaries); parameters = list(function.parameters)
        retained = set(); consumed = set(); field = set(); collection = set(); returned = set(); escaping = set(); reasons = set()
        for block in function.blocks:
            for instruction in block.instructions:
                for index, parameter in enumerate(parameters):
                    if isinstance(instruction, (m.SSACall, m.SSAInvoke)) and instruction.builtin == "__aether_retain" and instruction.arguments and instruction.arguments[0] == parameter: retained.add(index)
                    if isinstance(instruction, m.SSAClassSet) and instruction.value == parameter: field.add(index)
                    if isinstance(instruction, (m.SSAArraySet, m.SSAListSet, m.SSAListPush, m.SSAListInsert)) and instruction.value == parameter: collection.add(index)
                    if isinstance(instruction, m.SSAReturn) and instruction.value == parameter: returned.add(index)
                    if analysis.may_escape(parameter): escaping.add(index); reasons.update(analysis.escape_fact(parameter).reasons)
                    if analysis.ownership_state(parameter, block.name) is OwnershipState.CONSUMED: consumed.add(index)
        returns = [i.value for b in function.blocks for i in b.instructions
                   if isinstance(i, m.SSAReturn) and i.value is not None]
        returned = {
            index for index, parameter in enumerate(parameters)
            if returns and all(analysis.provenance(value) == analysis.provenance(parameter)
                               for value in returns)
        }
        return_provenance = [analysis.provenance(value) for value in returns]
        returns_fresh = bool(return_provenance) and all(
            item.exact and next(iter(item.roots)).kind is RootKind.FRESH
            for item in return_provenance
        ) and len({next(iter(item.roots)) for item in return_provenance}) == 1
        exceptional = any(analysis.escape_fact(parameter).exceptional for parameter in parameters)
        return OwnershipFunctionSummary(function.name, frozenset(retained), frozenset(consumed), frozenset(field),
            frozenset(collection), frozenset(returned), frozenset(escaping), returns_fresh, exceptional, frozenset(reasons))

    @staticmethod
    def debug_string(summaries):
        return "\n".join(summaries[name].debug_string() for name in sorted(summaries))
