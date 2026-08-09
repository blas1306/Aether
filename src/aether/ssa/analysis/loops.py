"""Dominance based, read-only loop analysis for SSA functions.

The implementation deliberately describes only natural loops.  Cyclic SCCs
which have no single dominating header are reported as irreducible regions.
Building the CFG and computing dominance are delegated to the compiler's
existing canonical analyses.
"""
from __future__ import annotations

from dataclasses import dataclass

from aether.analysis.dominators import DominatorAnalysis
from aether.ir.types import IntType
from aether.ssa.cfg import SSACFGBuilder, predecessors, successor_edges
from aether.ssa.model import SSABinaryOp, SSAConst, SSAFunction, SSAPhi, SSAValue


@dataclass(frozen=True)
class InductionVariable:
    value: SSAValue
    initial_value: SSAValue
    step: int
    update: SSABinaryOp
    direction: str
    loop_header: str


@dataclass(frozen=True)
class NaturalLoop:
    header: str
    backedges: tuple[tuple[str, str], ...]
    latches: frozenset[str]
    body: frozenset[str]
    exiting_blocks: frozenset[str]
    exit_blocks: frozenset[str]
    preheader: str | None
    parent_header: str | None
    child_headers: tuple[str, ...]
    depth: int
    induction_variables: tuple[InductionVariable, ...] = ()


@dataclass(frozen=True)
class IrreducibleRegion:
    blocks: frozenset[str]
    entry_blocks: frozenset[str]


@dataclass(frozen=True)
class LoopAnalysisResult:
    loops: tuple[NaturalLoop, ...]
    irreducible_regions: tuple[IrreducibleRegion, ...]

    def loop_with_header(self, header: str) -> NaturalLoop | None:
        return next((loop for loop in self.loops if loop.header == header), None)

    def loop_for_block(self, block: str) -> NaturalLoop | None:
        containing = [loop for loop in self.loops if block in loop.body]
        return max(containing, key=lambda loop: loop.depth, default=None)

    def induction_variables(self, loop: NaturalLoop | str) -> tuple[InductionVariable, ...]:
        header = loop if isinstance(loop, str) else loop.header
        found = self.loop_with_header(header)
        return () if found is None else found.induction_variables

    def verify(self) -> None:
        by_header = {loop.header: loop for loop in self.loops}
        for loop in self.loops:
            if loop.header not in loop.body or not loop.latches <= loop.body:
                raise ValueError(f"invalid natural loop {loop.header}")
            if loop.parent_header is not None:
                parent = by_header.get(loop.parent_header)
                if parent is None or not loop.body < parent.body:
                    raise ValueError(f"invalid parent for loop {loop.header}")
            for iv in loop.induction_variables:
                if iv.loop_header != loop.header or iv.step == 0:
                    raise ValueError(f"invalid induction variable in {loop.header}")

    def debug_string(self) -> str:
        lines: list[str] = []
        for loop in sorted(self.loops, key=lambda item: (item.depth, item.header)):
            preheader = loop.preheader or "<none>"
            lines.append(
                f"loop {loop.header} depth={loop.depth} preheader={preheader} "
                f"latches={','.join(sorted(loop.latches))} body={','.join(sorted(loop.body))} "
                f"exits={','.join(sorted(loop.exit_blocks))}"
            )
            for iv in sorted(loop.induction_variables, key=lambda item: item.value.name):
                lines.append(
                    f"  iv {iv.value.name} init={iv.initial_value.name} "
                    f"step={iv.step:+d} direction={iv.direction} update={iv.update.result.name}"
                )
        for region in self.irreducible_regions:
            lines.append(
                f"irreducible blocks={','.join(sorted(region.blocks))} "
                f"entries={','.join(sorted(region.entry_blocks))}"
            )
        return "\n".join(lines)


class LoopAnalysis:
    """Compute natural loops in O(V+E) graph work plus dominance cost."""

    def compute(self, function: SSAFunction) -> LoopAnalysisResult:
        cfg = SSACFGBuilder().build(function)
        dom = DominatorAnalysis(cfg, entry_block=function.entry_block).compute()
        pred = predecessors(function)
        blocks = {block.name: block for block in function.blocks}
        order = {block.name: index for index, block in enumerate(function.blocks)}
        succ = {name: tuple(edge.target for edge in successor_edges(block)) for name, block in blocks.items()}

        latches: dict[str, set[str]] = {}
        for edge in cfg.edges:
            if dom.is_reachable(edge.source) and dom.dominates(edge.target, edge.source):
                latches.setdefault(edge.target, set()).add(edge.source)

        bodies: dict[str, set[str]] = {}
        for header, header_latches in latches.items():
            body = {header, *header_latches}
            work = list(header_latches)
            while work:
                node = work.pop()
                for edge in pred[node]:
                    if edge.source not in body:
                        body.add(edge.source)
                        if edge.source != header:
                            work.append(edge.source)
            bodies[header] = body

        parent: dict[str, str | None] = {}
        for header, body in bodies.items():
            supersets = [other for other, other_body in bodies.items() if body < other_body]
            parent[header] = min(supersets, key=lambda item: len(bodies[item]), default=None)

        definitions = _definitions(function)
        raw: list[NaturalLoop] = []
        for header in sorted(bodies, key=order.get):
            body = bodies[header]
            outside_preds = {edge.source for edge in pred[header] if edge.source not in body}
            preheader = None
            if len(outside_preds) == 1:
                candidate = next(iter(outside_preds))
                if len(succ[candidate]) == 1 and succ[candidate][0] == header:
                    preheader = candidate
            exiting = {node for node in body if any(target not in body for target in succ[node])}
            exits = {target for node in exiting for target in succ[node] if target not in body}
            parent_header = parent[header]
            depth = 1
            cursor = parent_header
            while cursor is not None:
                depth += 1
                cursor = parent[cursor]
            ivs = _induction_variables(header, body, latches[header], blocks[header], definitions)
            raw.append(NaturalLoop(
                header, tuple((latch, header) for latch in sorted(latches[header], key=order.get)),
                frozenset(latches[header]), frozenset(body), frozenset(exiting), frozenset(exits),
                preheader, parent_header,
                tuple(sorted((child for child, value in parent.items() if value == header), key=order.get)),
                depth, ivs,
            ))

        result = LoopAnalysisResult(tuple(raw), _irreducible_regions(function, dom, bodies))
        result.verify()
        return result


def _definitions(function: SSAFunction) -> dict[str, tuple[str, object]]:
    result: dict[str, tuple[str, object]] = {}
    for block in function.blocks:
        for instruction in block.instructions:
            value = getattr(instruction, "result", None)
            if isinstance(value, SSAValue):
                result[value.name] = (block.name, instruction)
    return result


def _constant(value: SSAValue, definitions: dict[str, tuple[str, object]]) -> int | None:
    definition = definitions.get(value.name)
    if definition and isinstance(definition[1], SSAConst) and isinstance(definition[1].value, int):
        return definition[1].value
    return None


def _induction_variables(header: str, body: set[str], latches: set[str], block, definitions) -> tuple[InductionVariable, ...]:
    result: list[InductionVariable] = []
    for phi in block.instructions:
        if not isinstance(phi, SSAPhi) or not isinstance(phi.result.type, IntType):
            continue
        initial = [(source, value) for source, value in phi.incoming if source not in body]
        updates = [(source, value) for source, value in phi.incoming if source in latches]
        if len(initial) != 1 or not updates:
            continue
        recognized: list[tuple[int, SSABinaryOp]] = []
        for source, value in updates:
            definition = definitions.get(value.name)
            if definition is None or definition[0] not in body or not isinstance(definition[1], SSABinaryOp):
                break
            update = definition[1]
            left_const, right_const = _constant(update.left, definitions), _constant(update.right, definitions)
            step = None
            if update.operator == "add":
                if update.left == phi.result and right_const is not None:
                    step = right_const
                elif update.right == phi.result and left_const is not None:
                    step = left_const
            elif update.operator == "sub" and update.left == phi.result and right_const is not None:
                step = -right_const
            if step is None or step == 0:
                break
            recognized.append((step, update))
        if len(recognized) == len(updates) and len({step for step, _ in recognized}) == 1:
            step, update = recognized[0]
            result.append(InductionVariable(phi.result, initial[0][1], step, update, "increasing" if step > 0 else "decreasing", header))
    return tuple(result)


def _irreducible_regions(function, dom, natural_bodies) -> tuple[IrreducibleRegion, ...]:
    # Tarjan SCC; a cyclic SCC not wholly represented by a natural loop is
    # irreducible when it has multiple external entry blocks.
    blocks = {block.name: block for block in function.blocks if dom.is_reachable(block.name)}
    succ = {name: [edge.target for edge in successor_edges(block) if edge.target in blocks] for name, block in blocks.items()}
    index = 0; stack: list[str] = []; on_stack: set[str] = set(); indexes = {}; low = {}; components = []
    def visit(node: str) -> None:
        nonlocal index
        indexes[node] = low[node] = index; index += 1; stack.append(node); on_stack.add(node)
        for target in succ[node]:
            if target not in indexes:
                visit(target); low[node] = min(low[node], low[target])
            elif target in on_stack:
                low[node] = min(low[node], indexes[target])
        if low[node] == indexes[node]:
            component = set()
            while True:
                item = stack.pop(); on_stack.remove(item); component.add(item)
                if item == node: break
            components.append(component)
    for node in blocks:
        if node not in indexes: visit(node)
    pred = predecessors(function); regions = []
    natural_sets = [set(body) for body in natural_bodies.values()]
    for component in components:
        cyclic = len(component) > 1 or any(node in succ[node] for node in component)
        if not cyclic or any(component <= body for body in natural_sets): continue
        entries = {node for node in component if any(edge.source not in component for edge in pred[node])}
        if len(entries) > 1:
            regions.append(IrreducibleRegion(frozenset(component), frozenset(entries)))
    return tuple(sorted(regions, key=lambda region: sorted(region.blocks)))
