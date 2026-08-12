"""Read-only collection extraction borrow qualification.

The objects in this module describe a hypothetical internal view.  They are
deliberately not SSA instructions and are not consumed by any optimization.
"""
from __future__ import annotations

from dataclasses import dataclass, fields
from enum import Enum

from aether.ir.types import ArrayType, ListType, StructType
from aether.ssa import model as m

from .alias_modref import AliasRelation, ModRefAnalysis, ModRefEffect
from .loops import LoopAnalysis
from .ownership_escape import OwnershipEscapeAnalysis, is_reference_like


class ExtractionBorrowClassification(Enum):
    BORROWABLE_IMMEDIATE_USE = "BORROWABLE_IMMEDIATE_USE"
    BORROWABLE_STABLE_REGION = "BORROWABLE_STABLE_REGION"
    MUST_COPY_LIFETIME_EXTENDS = "MUST_COPY_LIFETIME_EXTENDS"
    MUST_COPY_COLLECTION_MUTATES = "MUST_COPY_COLLECTION_MUTATES"
    MUST_COPY_ELEMENT_MUTATES = "MUST_COPY_ELEMENT_MUTATES"
    MUST_COPY_ESCAPES = "MUST_COPY_ESCAPES"
    MUST_COPY_CALL_INVALIDATION = "MUST_COPY_CALL_INVALIDATION"
    MUST_COPY_EXCEPTION_LIFETIME = "MUST_COPY_EXCEPTION_LIFETIME"
    MUST_COPY_ALIAS_UNCERTAINTY = "MUST_COPY_ALIAS_UNCERTAINTY"
    UNKNOWN = "UNKNOWN"


class BorrowInvalidationReason(Enum):
    COLLECTION_MUTATION = "COLLECTION_MUTATION"
    ELEMENT_REPLACEMENT = "ELEMENT_REPLACEMENT"
    COLLECTION_ALIAS_MUTATION = "COLLECTION_ALIAS_MUTATION"
    UNKNOWN_CALL = "UNKNOWN_CALL"
    INTERFACE_CALL = "INTERFACE_CALL"
    AGGREGATE_ESCAPE = "AGGREGATE_ESCAPE"
    COMPONENT_ESCAPE = "COMPONENT_ESCAPE"
    AGGREGATE_MUTATION = "AGGREGATE_MUTATION"
    BORROW_CROSSES_BACKEDGE = "BORROW_CROSSES_BACKEDGE"
    COLLECTION_LIFETIME = "COLLECTION_LIFETIME"
    EXCEPTION_REGION = "EXCEPTION_REGION"
    UNKNOWN_COMPONENT_OWNERSHIP = "UNKNOWN_COMPONENT_OWNERSHIP"
    INDEX_IDENTITY_UNSTABLE = "INDEX_IDENTITY_UNSTABLE"
    OTHER = "OTHER"


class BorrowIntervalKind(Enum):
    SAME_EXPRESSION = "SAME_EXPRESSION"
    SAME_BASIC_BLOCK = "SAME_BASIC_BLOCK"
    STRAIGHT_LINE_MULTI_BLOCK = "STRAIGHT_LINE_MULTI_BLOCK"
    BRANCH_SPANNING = "BRANCH_SPANNING"
    LOOP_CARRIED = "LOOP_CARRIED"
    CALL_SPANNING = "CALL_SPANNING"
    EXCEPTION_SPANNING = "EXCEPTION_SPANNING"


class FieldUseShape(Enum):
    ONE_FIELD_READ = "ONE_FIELD_READ"
    MULTIPLE_FIELD_READS = "MULTIPLE_FIELD_READS"
    WHOLE_AGGREGATE_READ = "WHOLE_AGGREGATE_READ"
    AGGREGATE_COMPARE = "AGGREGATE_COMPARE"
    METHOD_RECEIVER = "METHOD_RECEIVER"
    AGGREGATE_MUTATION = "AGGREGATE_MUTATION"
    PASS_AGGREGATE = "PASS_AGGREGATE"
    RETURN_AGGREGATE = "RETURN_AGGREGATE"
    MIXED = "MIXED"


@dataclass(frozen=True)
class BorrowPoint:
    block: str
    instruction: int


@dataclass(frozen=True)
class BorrowedAggregateView:
    collection_root: m.SSAValue
    element_selector: m.SSAValue
    aggregate_type: object
    borrow_start: BorrowPoint
    borrow_end: BorrowPoint
    invalidation_conditions: tuple[BorrowInvalidationReason, ...]


@dataclass(frozen=True)
class ExtractionBorrowResult:
    value: m.SSAValue
    view: BorrowedAggregateView
    collection_kind: str
    interval_kind: BorrowIntervalKind
    classification: ExtractionBorrowClassification
    blocker_reasons: tuple[BorrowInvalidationReason, ...]
    field_use_shape: FieldUseShape
    total_uses: int
    direct_field_reads: int
    scalar_field_reads: int
    owned_field_reads: int
    aggregate_level_uses: int
    mutation_uses: int
    escape_uses: int
    calls: tuple[BorrowPoint, ...]
    collection_mutations: tuple[BorrowPoint, ...]
    alias_uncertainty: bool
    exceptional_edges: bool
    crosses_backedge: bool
    bounds_check: str
    index_form: str
    nested_owned_component_count: int


def _operands(instruction):
    result = []
    for field in fields(instruction):
        if field.name in {"result", "exception"}: continue
        item = getattr(instruction, field.name)
        if isinstance(item, m.SSAValue): result.append(item)
        elif isinstance(item, tuple):
            for nested in item:
                if isinstance(nested, m.SSAValue): result.append(nested)
                elif isinstance(nested, tuple): result.extend(x for x in nested if isinstance(x, m.SSAValue))
    return tuple(result)


_CALLS = (m.SSACall, m.SSAInvoke, m.SSACallIndirect, m.SSAInvokeIndirect,
          m.SSAInterfaceCall, m.SSAInvokeInterface)
_EXCEPTING = (m.SSAInvoke, m.SSAInvokeIndirect, m.SSAInvokeInterface)
_LIST_ALL = (m.SSAListPush, m.SSAListInsert, m.SSAListRemoveAt, m.SSAListPop,
             m.SSAListClear, m.SSAListReverse)


class CollectionExtractionBorrowAnalysis:
    """Conservatively qualify Array/List get results without changing SSA."""

    def __init__(self, function: m.SSAFunction, structs=(), summaries=None):
        self.function = function
        self.structs = tuple(structs)
        self.loops = LoopAnalysis().compute(function)
        self.modref = ModRefAnalysis(function, summaries)
        self.ownership = OwnershipEscapeAnalysis(function, structs=self.structs)
        self.blocks = {b.name: b for b in function.blocks}
        self.order = {b.name: n for n, b in enumerate(function.blocks)}
        self.definitions = {}
        self.uses = {}
        for block in function.blocks:
            for index, instruction in enumerate(block.instructions):
                value = getattr(instruction, "result", None)
                if isinstance(value, m.SSAValue): self.definitions[value] = (block.name, index, instruction)
        for block in function.blocks:
            for index, instruction in enumerate(block.instructions):
                for value in _operands(instruction): self.uses.setdefault(value, []).append((block.name, index, instruction))
        self._results = {}
        for value, definition in self.definitions.items():
            if isinstance(definition[2], (m.SSAArrayGet, m.SSAListGet)):
                self._results[value] = self._classify(value, definition)

    def extractions(self):
        return tuple(self._results[v] for v in sorted(self._results, key=lambda x: x.name))

    def classify_extraction_borrow(self, value): return self._results[value].classification
    def extraction_borrow_interval(self, value): return self._results[value].view
    def borrow_invalidation_reason(self, value): return self._results[value].blocker_reasons
    def collection_stable_during(self, value): return not self._results[value].collection_mutations and not self._results[value].alias_uncertainty
    def component_outlives_borrow(self, value, path):
        # An escaping projection is intentionally failed closed.  Field ARC can
        # establish an independent owner in future, but that proof is not made here.
        row = self._results[value]
        return BorrowInvalidationReason.COMPONENT_ESCAPE in row.blocker_reasons

    def _between(self, start, end):
        sb, si = start; eb, ei = end
        if sb != eb: return []  # multi-block scheduling is deliberately conservative
        return [(sb, n, item) for n, item in enumerate(self.blocks[sb].instructions) if si < n < ei]

    def _classify(self, value, definition):
        db, di, get = definition
        collection = get.array if isinstance(get, m.SSAArrayGet) else get.list_value
        uses = self.uses.get(value, [])
        semantic = [u for u in uses if not (isinstance(u[2], (m.SSACall, m.SSAInvoke)) and
                    getattr(u[2], "builtin", None) in {"__aether_retain", "__aether_release"})]
        ordered = sorted(semantic or uses, key=lambda x: (self.order[x[0]], x[1]))
        end = (ordered[-1][0], ordered[-1][1]) if ordered else (db, di)
        between = self._between((db, di), end)
        calls = [(b, n, i) for b, n, i in between if isinstance(i, _CALLS)]
        exceptions = any(isinstance(i, _EXCEPTING) for _, _, i in between)
        loop = self.loops.loop_for_block(db)
        crosses_backedge = bool(loop and any(b in loop.latches and b != db for b, _, _ in semantic))
        field_reads = [u for u in semantic if isinstance(u[2], m.SSAStructGet) and u[2].struct == value]
        mutations = [u for u in semantic if isinstance(u[2], m.SSAStructSet) and u[2].struct == value]
        escapes = [u for u in semantic if isinstance(u[2], (m.SSAReturn, m.SSAClassSet, m.SSAArraySet,
                   m.SSAListSet, m.SSAListPush, m.SSAListInsert, m.SSAInterfaceConstruct))]
        component_escape = any(self.ownership.may_escape(getattr(u[2], "result", value)) for u in field_reads)
        collection_mutations = []
        alias_uncertainty = False
        for b, n, instruction in between:
            if isinstance(instruction, _LIST_ALL + (m.SSAListSet, m.SSAArraySet)):
                target = getattr(instruction, "list_value", getattr(instruction, "array", None))
                relation = self.modref.aliases.alias(target, collection) if target else AliasRelation.NO_ALIAS
                if relation is not AliasRelation.NO_ALIAS:
                    collection_mutations.append((b, n, instruction))
                    alias_uncertainty |= relation is AliasRelation.MAY_ALIAS
            elif instruction.writes_memory:
                decision = self.modref.effects(instruction, collection)
                if decision.effect.may_modify:
                    collection_mutations.append((b, n, instruction))
                    alias_uncertainty |= decision.effect is ModRefEffect.UNKNOWN
        reasons = []
        if mutations: reasons.append(BorrowInvalidationReason.AGGREGATE_MUTATION)
        if escapes or self.ownership.may_escape(value): reasons.append(BorrowInvalidationReason.AGGREGATE_ESCAPE)
        if component_escape: reasons.append(BorrowInvalidationReason.COMPONENT_ESCAPE)
        if collection_mutations: reasons.append(BorrowInvalidationReason.COLLECTION_MUTATION)
        if alias_uncertainty: reasons.append(BorrowInvalidationReason.COLLECTION_ALIAS_MUTATION)
        if calls: reasons.append(BorrowInvalidationReason.UNKNOWN_CALL)
        if exceptions: reasons.append(BorrowInvalidationReason.EXCEPTION_REGION)
        if crosses_backedge: reasons.append(BorrowInvalidationReason.BORROW_CROSSES_BACKEDGE)
        same_block = all(b == db for b, _, _ in semantic)
        immediate = same_block and (not semantic or end[1] <= di + 2)
        if BorrowInvalidationReason.AGGREGATE_MUTATION in reasons: classification = ExtractionBorrowClassification.MUST_COPY_ELEMENT_MUTATES
        elif BorrowInvalidationReason.AGGREGATE_ESCAPE in reasons or BorrowInvalidationReason.COMPONENT_ESCAPE in reasons: classification = ExtractionBorrowClassification.MUST_COPY_ESCAPES
        elif BorrowInvalidationReason.EXCEPTION_REGION in reasons: classification = ExtractionBorrowClassification.MUST_COPY_EXCEPTION_LIFETIME
        elif BorrowInvalidationReason.COLLECTION_ALIAS_MUTATION in reasons: classification = ExtractionBorrowClassification.MUST_COPY_ALIAS_UNCERTAINTY
        elif BorrowInvalidationReason.COLLECTION_MUTATION in reasons: classification = ExtractionBorrowClassification.MUST_COPY_COLLECTION_MUTATES
        elif BorrowInvalidationReason.UNKNOWN_CALL in reasons: classification = ExtractionBorrowClassification.MUST_COPY_CALL_INVALIDATION
        elif BorrowInvalidationReason.BORROW_CROSSES_BACKEDGE in reasons: classification = ExtractionBorrowClassification.MUST_COPY_LIFETIME_EXTENDS
        elif not same_block: classification = ExtractionBorrowClassification.UNKNOWN
        elif immediate: classification = ExtractionBorrowClassification.BORROWABLE_IMMEDIATE_USE
        else: classification = ExtractionBorrowClassification.BORROWABLE_STABLE_REGION
        if mutations: shape = FieldUseShape.AGGREGATE_MUTATION
        elif escapes and any(isinstance(u[2], m.SSAReturn) for u in escapes): shape = FieldUseShape.RETURN_AGGREGATE
        elif len(field_reads) == 1: shape = FieldUseShape.ONE_FIELD_READ
        elif len(field_reads) > 1: shape = FieldUseShape.MULTIPLE_FIELD_READS
        elif any(type(u[2]).__name__ == "SSACompare" for u in semantic): shape = FieldUseShape.AGGREGATE_COMPARE
        elif any(isinstance(u[2], _CALLS) for u in semantic): shape = FieldUseShape.PASS_AGGREGATE
        else: shape = FieldUseShape.WHOLE_AGGREGATE_READ
        if exceptions: interval = BorrowIntervalKind.EXCEPTION_SPANNING
        elif crosses_backedge: interval = BorrowIntervalKind.LOOP_CARRIED
        elif calls: interval = BorrowIntervalKind.CALL_SPANNING
        elif not same_block: interval = BorrowIntervalKind.BRANCH_SPANNING
        elif immediate: interval = BorrowIntervalKind.SAME_EXPRESSION
        else: interval = BorrowIntervalKind.SAME_BASIC_BLOCK
        index_def = self.definitions.get(get.index)
        index_form = "CONSTANT" if index_def and isinstance(index_def[2], m.SSAConst) else "LOOP_INDUCTION" if loop else "VARIANT"
        owned = sum(1 for item in field_reads if is_reference_like(item[2].result.type))
        view = BorrowedAggregateView(collection, get.index, value.type, BorrowPoint(db, di), BorrowPoint(*end), tuple(reasons))
        return ExtractionBorrowResult(value, view, "Array" if isinstance(get, m.SSAArrayGet) else "List", interval,
            classification, tuple(reasons), shape, len(semantic), len(field_reads), len(field_reads)-owned, owned,
            len(semantic)-len(field_reads), len(mutations), len(escapes), tuple(BorrowPoint(b,n) for b,n,_ in calls),
            tuple(BorrowPoint(b,n) for b,n,_ in collection_mutations), alias_uncertainty, exceptions, crosses_backedge,
            "RETAINED" if get.bounds_checked else "ELIMINATED", index_form, owned if isinstance(value.type, StructType) else int(is_reference_like(value.type)))
