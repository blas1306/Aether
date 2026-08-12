"""Read-only aggregate lifetime and ARC attribution analysis.

The analysis deliberately describes the lifecycle-expanded SSA as it exists.
It is not registered in an optimization profile and none of its facts are
consumed by a transforming pass.
"""
from __future__ import annotations

from dataclasses import dataclass, fields
from enum import Enum

from aether.ir.types import MethodResultType, StructType
from aether.ssa import model as m
from aether.ssa.cfg import successor_edges

from .loops import LoopAnalysis
from .ownership_escape import ComponentPath, OwnershipEscapeAnalysis, OwnershipState, is_reference_like


class LifetimeCategory(Enum):
    SEMANTIC_OWNER = "SEMANTIC_OWNER"
    AGGREGATE_COPY = "AGGREGATE_COPY"
    COLLECTION_EXTRACTION_TEMPORARY = "COLLECTION_EXTRACTION_TEMPORARY"
    STRUCT_RECONSTRUCTION_TEMPORARY = "STRUCT_RECONSTRUCTION_TEMPORARY"
    METHOD_RESULT_TEMPORARY = "METHOD_RESULT_TEMPORARY"
    CALL_RESULT_TEMPORARY = "CALL_RESULT_TEMPORARY"
    PHI_MERGE_VALUE = "PHI_MERGE_VALUE"
    LOOP_CARRIED_AGGREGATE = "LOOP_CARRIED_AGGREGATE"
    RETURN_VALUE = "RETURN_VALUE"
    ESCAPING_AGGREGATE = "ESCAPING_AGGREGATE"
    DESTRUCTION_ONLY = "DESTRUCTION_ONLY"
    UNKNOWN = "UNKNOWN"


class AggregateOrigin(Enum):
    SOURCE_LOCAL = "SOURCE_LOCAL"
    STRUCT_CONSTRUCTOR = "STRUCT_CONSTRUCTOR"
    COLLECTION_EXTRACTION = "COLLECTION_EXTRACTION"
    FUNCTION_RETURN = "FUNCTION_RETURN"
    METHOD_RETURN = "METHOD_RETURN"
    METHOD_RESULT_COMPONENT = "METHOD_RESULT_COMPONENT"
    STRUCT_COPY = "STRUCT_COPY"
    STRUCT_RECONSTRUCTION = "STRUCT_RECONSTRUCTION"
    PHI = "PHI"
    PARAMETER = "PARAMETER"
    CONSTANT_DEFAULT = "CONSTANT_DEFAULT"
    UNKNOWN = "UNKNOWN"


class EscapeKind(Enum):
    NONE = "NO_ESCAPE"
    RETURN = "RETURN"
    FIELD_STORE = "FIELD_STORE"
    COLLECTION_STORE = "COLLECTION_STORE"
    CALL = "CALL"
    INTERFACE = "INTERFACE"
    EXCEPTION = "EXCEPTION"
    UNKNOWN = "UNKNOWN"


class ArcAttribution(Enum):
    CONSTRUCT = "CONSTRUCT"
    COPY = "COPY"
    EXTRACT = "EXTRACT"
    FIELD_ACQUIRE = "FIELD_ACQUIRE"
    FIELD_RELEASE = "FIELD_RELEASE"
    TEMPORARY_DESTROY = "TEMPORARY_DESTROY"
    AGGREGATE_DESTROY = "AGGREGATE_DESTROY"
    RETURN_TRANSFER = "RETURN_TRANSFER"
    PARAMETER_COPY = "PARAMETER_COPY"
    PHI_MERGE = "PHI_MERGE"
    RECONSTRUCTION = "RECONSTRUCTION"
    COLLECTION_STORE = "COLLECTION_STORE"
    COLLECTION_EXTRACTION = "COLLECTION_EXTRACTION"
    UNKNOWN = "UNKNOWN"


class BorrowOpportunity(Enum):
    MUST_OWN = "MUST_OWN"
    COULD_BORROW_INTERNAL_TEMPORARY = "COULD_BORROW_INTERNAL_TEMPORARY"
    UNKNOWN = "UNKNOWN"


class MaterializationKind(Enum):
    SEMANTICALLY_REQUIRED = "SEMANTICALLY_REQUIRED"
    REPRESENTATION_INDUCED = "REPRESENTATION_INDUCED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class ProgramPoint:
    block: str
    instruction: int


@dataclass(frozen=True)
class ComponentLifetime:
    path: ComponentPath
    provenance: tuple[str, ...]
    exact: bool
    ownership_role: OwnershipState
    retain_events: tuple[ProgramPoint, ...]
    release_events: tuple[ProgramPoint, ...]
    escapes: bool


@dataclass(frozen=True)
class ArcEvent:
    point: ProgramPoint
    kind: str
    value: m.SSAValue
    attribution: ArcAttribution
    component_path: ComponentPath | None = None


@dataclass(frozen=True)
class AggregateLifetime:
    value: m.SSAValue
    instance: str
    origin: AggregateOrigin
    primary_category: LifetimeCategory
    secondary_reasons: tuple[LifetimeCategory, ...]
    definition: ProgramPoint | None
    first_use: ProgramPoint | None
    last_use: ProgramPoint | None
    destruction_points: tuple[ProgramPoint, ...]
    loop_depth: int
    loop_id: str | None
    crosses_branch: bool
    crosses_join: bool
    crosses_call: bool
    crosses_backedge: bool
    crosses_exceptional_edge: bool
    crosses_return: bool
    escape: EscapeKind
    components: tuple[ComponentLifetime, ...]
    arc_events: tuple[ArcEvent, ...]
    borrow_opportunity: BorrowOpportunity
    materialization: MaterializationKind


def _aggregate(type_) -> bool:
    return isinstance(type_, (StructType, MethodResultType))


def _values(instruction) -> tuple[m.SSAValue, ...]:
    result = []
    for item in fields(instruction):
        if item.name in {"result", "exception"}: continue
        value = getattr(instruction, item.name)
        if isinstance(value, m.SSAValue): result.append(value)
        elif isinstance(value, tuple):
            for nested in value:
                if isinstance(nested, m.SSAValue): result.append(nested)
                elif isinstance(nested, tuple): result.extend(x for x in nested if isinstance(x, m.SSAValue))
    return tuple(result)


class AggregateLifetimeAnalysis:
    """Conservative block-aware lifetime census for aggregate SSA instances."""

    def __init__(self, function: m.SSAFunction, structs=()):
        self.function = function
        self.structs = tuple(structs)
        self.ownership = OwnershipEscapeAnalysis(function, structs=self.structs)
        self.loops = LoopAnalysis().compute(function)
        self.blocks = {block.name: block for block in function.blocks}
        self.order = {block.name: n for n, block in enumerate(function.blocks)}
        self.definitions = {getattr(i, "result", None): (b.name, n, i)
                            for b in function.blocks for n, i in enumerate(b.instructions)
                            if getattr(i, "result", None) is not None}
        self.uses = {value: [] for value in self.definitions}
        for parameter in function.parameters: self.uses.setdefault(parameter, [])
        for block in function.blocks:
            for index, instruction in enumerate(block.instructions):
                for value in _values(instruction): self.uses.setdefault(value, []).append((block.name, index, instruction))
        self._lifetimes = {value: self._build(value) for value in
                           sorted((v for v in self.uses if _aggregate(v.type)), key=lambda v: v.name)}

    def _origin(self, value):
        entry = self.definitions.get(value)
        if entry is None: return AggregateOrigin.PARAMETER
        instruction = entry[2]
        if isinstance(instruction, m.SSAStructNew): return AggregateOrigin.STRUCT_CONSTRUCTOR
        if isinstance(instruction, (m.SSAListGet, m.SSAArrayGet, m.SSAListPop, m.SSAListRemoveAt)): return AggregateOrigin.COLLECTION_EXTRACTION
        if isinstance(instruction, m.SSAStructSet): return AggregateOrigin.STRUCT_RECONSTRUCTION
        if isinstance(instruction, m.SSAPhi): return AggregateOrigin.PHI
        if isinstance(instruction, m.SSAMethodResultNew): return AggregateOrigin.METHOD_RETURN
        if isinstance(instruction, (m.SSAMethodResultReceiver, m.SSAMethodResultValue)): return AggregateOrigin.METHOD_RESULT_COMPONENT
        if isinstance(instruction, (m.SSACall, m.SSAInvoke, m.SSACallIndirect, m.SSAInvokeIndirect,
                                    m.SSAInterfaceCall, m.SSAInvokeInterface)): return AggregateOrigin.FUNCTION_RETURN
        if isinstance(instruction, (m.SSAConst,)): return AggregateOrigin.CONSTANT_DEFAULT
        return AggregateOrigin.UNKNOWN

    def _escape(self, value):
        uses = self.uses.get(value, ())
        if any(isinstance(i, m.SSAReturn) for _, _, i in uses): return EscapeKind.RETURN
        if any(isinstance(i, m.SSAClassSet) and i.value == value for _, _, i in uses): return EscapeKind.FIELD_STORE
        if any(isinstance(i, (m.SSAArraySet, m.SSAListSet, m.SSAListPush, m.SSAListInsert)) and i.value == value for _, _, i in uses): return EscapeKind.COLLECTION_STORE
        if any(isinstance(i, (m.SSAInterfaceCall, m.SSAInvokeInterface, m.SSAInterfaceConstruct)) for _, _, i in uses): return EscapeKind.INTERFACE
        if any(isinstance(i, (m.SSAThrow, m.SSARethrow, m.SSAPropagate)) for _, _, i in uses): return EscapeKind.EXCEPTION
        if any(isinstance(i, (m.SSACall, m.SSAInvoke, m.SSACallIndirect, m.SSAInvokeIndirect)) and
               getattr(i, "builtin", None) not in {"__aether_retain", "__aether_release"} for _, _, i in uses): return EscapeKind.CALL
        return EscapeKind.UNKNOWN if self.ownership.may_escape(value) else EscapeKind.NONE

    def _component_rows(self, value, arcs):
        aggregate = self.ownership.aggregate_provenance(value)
        rows = []
        for path, fact in sorted(aggregate.components, key=lambda pair: str(pair[0])):
            roots = tuple(f"{root.kind.value}:{root.identity}" for root in sorted(fact.provenance.roots))
            # Lifecycle expansion operates on flattened reference values.  Only
            # attach an event when exact provenance proves the same component.
            related = [event for event in arcs if self.ownership.provenance(event.value) == fact.provenance]
            rows.append(ComponentLifetime(path, roots, fact.provenance.exact, fact.ownership,
                tuple(e.point for e in related if e.kind == "retain"),
                tuple(e.point for e in related if e.kind == "release"),
                self.ownership.may_escape(value)))
        return tuple(rows)

    def _build(self, value):
        definition = self.definitions.get(value); uses = self.uses.get(value, [])
        points = [(b, n) for b, n, _ in uses]
        defpoint = ProgramPoint(definition[0], definition[1]) if definition else None
        first = ProgramPoint(*min(points, key=lambda p: (self.order[p[0]], p[1]))) if points else None
        last = ProgramPoint(*max(points, key=lambda p: (self.order[p[0]], p[1]))) if points else None
        origin = self._origin(value); loop = self.loops.loop_for_block(definition[0]) if definition else None
        use_loops = [self.loops.loop_for_block(b) for b, _, _ in uses]
        carried = bool(loop and any(item and item.header == loop.header and b in item.latches
                                    for (b, _, _), item in zip(uses, use_loops))) or (
            isinstance(definition[2], m.SSAPhi) if definition else False) and bool(loop)
        escaping = self._escape(value)
        categories = []
        primary = {
            AggregateOrigin.COLLECTION_EXTRACTION: LifetimeCategory.COLLECTION_EXTRACTION_TEMPORARY,
            AggregateOrigin.STRUCT_RECONSTRUCTION: LifetimeCategory.STRUCT_RECONSTRUCTION_TEMPORARY,
            AggregateOrigin.METHOD_RETURN: LifetimeCategory.METHOD_RESULT_TEMPORARY,
            AggregateOrigin.FUNCTION_RETURN: LifetimeCategory.CALL_RESULT_TEMPORARY,
            AggregateOrigin.PHI: LifetimeCategory.PHI_MERGE_VALUE,
        }.get(origin, LifetimeCategory.SEMANTIC_OWNER if origin in {AggregateOrigin.PARAMETER, AggregateOrigin.STRUCT_CONSTRUCTOR} else LifetimeCategory.UNKNOWN)
        if carried: categories.append(LifetimeCategory.LOOP_CARRIED_AGGREGATE); primary = LifetimeCategory.LOOP_CARRIED_AGGREGATE
        if escaping is EscapeKind.RETURN: categories.append(LifetimeCategory.RETURN_VALUE)
        elif escaping is not EscapeKind.NONE: categories.append(LifetimeCategory.ESCAPING_AGGREGATE)
        arcs = []
        for block in self.function.blocks:
            for index, instruction in enumerate(block.instructions):
                if isinstance(instruction, (m.SSACall, m.SSAInvoke)) and instruction.builtin in {"__aether_retain", "__aether_release"} and instruction.arguments:
                    operand = instruction.arguments[0]
                    if operand == value:
                        attr = self._attribution(origin, instruction.builtin.endswith("release"))
                        arcs.append(ArcEvent(ProgramPoint(block.name, index), instruction.builtin.removeprefix("__aether_"), operand, attr))
        destroys = tuple(e.point for e in arcs if e.kind == "release")
        same_block = definition and all(b == definition[0] for b, _, _ in uses)
        immediate = origin is AggregateOrigin.COLLECTION_EXTRACTION and same_block and len([u for u in uses if not (isinstance(u[2], (m.SSACall, m.SSAInvoke)) and getattr(u[2], "builtin", None) == "__aether_release")]) <= 2 and escaping is EscapeKind.NONE
        borrow = BorrowOpportunity.COULD_BORROW_INTERNAL_TEMPORARY if immediate else BorrowOpportunity.MUST_OWN if escaping is not EscapeKind.NONE else BorrowOpportunity.UNKNOWN
        materialization = MaterializationKind.REPRESENTATION_INDUCED if immediate else MaterializationKind.SEMANTICALLY_REQUIRED if escaping is not EscapeKind.NONE else MaterializationKind.UNKNOWN
        blocks = {b for b, _, _ in uses} | ({definition[0]} if definition else set())
        instructions = [i for b in blocks for i in self.blocks[b].instructions]
        return AggregateLifetime(value, f"{self.function.name}:%{value.name}", origin, primary,
            tuple(sorted(set(categories), key=lambda x: x.value)), defpoint, first, last, destroys,
            max((x.depth for x in use_loops if x), default=loop.depth if loop else 0), loop.header if loop else None,
            len(blocks) > 1, any(len(successor_edges(self.blocks[p])) > 1 for p in blocks),
            any(isinstance(i, (m.SSACall, m.SSAInvoke, m.SSACallIndirect, m.SSAInvokeIndirect,
                              m.SSAInterfaceCall, m.SSAInvokeInterface)) for i in instructions), carried,
            any(isinstance(i, (m.SSAInvoke, m.SSAInvokeIndirect, m.SSAInvokeInterface)) for i in instructions),
            escaping is EscapeKind.RETURN, escaping, self._component_rows(value, arcs), tuple(arcs), borrow, materialization)

    @staticmethod
    def _attribution(origin, release):
        if release: return ArcAttribution.TEMPORARY_DESTROY if origin in {AggregateOrigin.COLLECTION_EXTRACTION, AggregateOrigin.FUNCTION_RETURN, AggregateOrigin.METHOD_RETURN} else ArcAttribution.AGGREGATE_DESTROY
        return {AggregateOrigin.STRUCT_CONSTRUCTOR: ArcAttribution.CONSTRUCT,
                AggregateOrigin.COLLECTION_EXTRACTION: ArcAttribution.COLLECTION_EXTRACTION,
                AggregateOrigin.STRUCT_RECONSTRUCTION: ArcAttribution.RECONSTRUCTION,
                AggregateOrigin.PHI: ArcAttribution.PHI_MERGE,
                AggregateOrigin.PARAMETER: ArcAttribution.PARAMETER_COPY}.get(origin, ArcAttribution.UNKNOWN)

    def aggregate_origin(self, value): return self._lifetimes[value].origin
    def aggregate_lifetime(self, value): return self._lifetimes[value]
    def component_lifetime(self, value, path):
        return next((x for x in self._lifetimes[value].components if x.path == path), None)
    def aggregate_escape(self, value): return self._lifetimes[value].escape
    def aggregate_arc_attribution(self, value): return self._lifetimes[value].arc_events
    def classify_materialization(self, value): return self._lifetimes[value].materialization
    def classify_copy(self, value): return self._lifetimes[value].primary_category
    def same_semantic_aggregate_value(self, left, right):
        a, b = self.ownership.aggregate_provenance(left), self.ownership.aggregate_provenance(right)
        return bool(a.components) and a == b
    def lifetimes(self): return tuple(self._lifetimes[v] for v in sorted(self._lifetimes, key=lambda x: x.name))
    def debug_string(self):
        lines = []
        for lifetime in self.lifetimes():
            lines.append(f"{self.function.name} {lifetime.instance} origin={lifetime.origin.value} category={lifetime.primary_category.value} escape={lifetime.escape.value} loop={lifetime.loop_id or '-'}")
            for component in lifetime.components:
                lines.append(f"  {component.path} roots=[{','.join(component.provenance)}] exact={str(component.exact).lower()} ownership={component.ownership_role.value}")
            for event in lifetime.arc_events:
                lines.append(f"  arc {event.point.block}:{event.point.instruction} {event.kind} {event.attribution.value}")
        return "\n".join(lines)
