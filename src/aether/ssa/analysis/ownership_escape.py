"""Conservative, exception-aware ownership and escape analysis.

This is deliberately analysis-only.  It describes ownership edges represented
by the current SSA; it neither inserts nor removes lifecycle operations.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, Flag, auto

from aether.ir.types import ArrayType, ClassRefType, InterfaceType, ListType, NullableType, StringType
from aether.ssa import model as m
from aether.ssa.cfg import predecessors, reachable_blocks, successor_edges

from .alias_modref import AliasAnalysis, Provenance, ProvenanceRoot, RootKind


class OwnershipState(Enum):
    OWNED = "owned"
    BORROWED = "borrowed"
    CONSUMED = "consumed"
    UNKNOWN = "unknown"


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
                 summaries: dict[str, OwnershipFunctionSummary] | None = None):
        self.function = function
        self.summaries = summaries or {}
        self.aliases = AliasAnalysis(function)
        self._states: dict[m.SSAValue, OwnershipState] = {}
        self._escapes: dict[ProvenanceRoot, EscapeFact] = {}
        self._in: dict[str, OwnershipFrame] = {}
        self._out: dict[str, OwnershipFrame] = {}
        self._exception_reachable = self._exceptional_reachability()
        self._analyze()

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
            if is_reference_like(parameter.type): self._states[parameter] = OwnershipState.BORROWED
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
                    self._transfer(instruction, state, name, index)
                frame = OwnershipFrame(tuple(sorted(state.items(), key=lambda item: item[0].name)))
                if self._out.get(name) != frame: self._out[name] = frame; changed = True
            if not changed: break
        else:
            for value in self._states: self._states[value] = OwnershipState.UNKNOWN

    def _set_escape(self, value: m.SSAValue, mode: EscapeMode, block: str, index: int,
                    reason: OwnershipUnknownReason, *, exceptional: bool | None = None) -> None:
        if not is_reference_like(value.type): return
        exceptional = block in self._exception_reachable if exceptional is None else exceptional
        for root in self.aliases.provenance(value).roots:
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
            else: state[result] = OwnershipState.UNKNOWN
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

    def provenance(self, value: m.SSAValue) -> Provenance: return self.aliases.provenance(value)
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
        returns_fresh = any(isinstance(i, m.SSAReturn) and i.value is not None and analysis.is_fresh(i.value)
                            for b in function.blocks for i in b.instructions)
        exceptional = any(analysis.escape_fact(parameter).exceptional for parameter in parameters)
        return OwnershipFunctionSummary(function.name, frozenset(retained), frozenset(consumed), frozenset(field),
            frozenset(collection), frozenset(returned), frozenset(escaping), returns_fresh, exceptional, frozenset(reasons))

    @staticmethod
    def debug_string(summaries):
        return "\n".join(summaries[name].debug_string() for name in sorted(summaries))
