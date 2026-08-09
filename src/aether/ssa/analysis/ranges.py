"""Conservative path-sensitive integer range and comparison facts."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from aether.integer_arithmetic import INT_MAX, INT_MIN
from aether.ir.types import IntType
from aether.ssa.cfg import predecessors, reverse_postorder, successor_edges
from aether.ssa.model import (
    SSABinaryOp, SSABranch, SSACompareOp, SSAConst, SSAFunction, SSAPhi, SSAValue,
)
from .loops import LoopAnalysis


class ProofResult(Enum):
    PROVEN_TRUE = "proven_true"
    PROVEN_FALSE = "proven_false"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class SymbolicBound:
    """An inclusive bound ``value + offset``; value=None denotes a constant."""
    value: SSAValue | None
    offset: int = 0

    def __str__(self) -> str:
        if self.value is None:
            return str(self.offset)
        return self.value.name if self.offset == 0 else f"{self.value.name}{self.offset:+d}"


@dataclass(frozen=True)
class IntegerRange:
    lower: SymbolicBound | None = None
    upper: SymbolicBound | None = None

    @classmethod
    def unknown(cls) -> "IntegerRange": return cls()
    @classmethod
    def exact(cls, value: int) -> "IntegerRange":
        bound = SymbolicBound(None, value); return cls(bound, bound)
    @property
    def is_unknown(self) -> bool: return self.lower is None and self.upper is None
    @property
    def constant(self) -> int | None:
        if self.lower == self.upper and self.lower is not None and self.lower.value is None:
            return self.lower.offset
        return None
    def join(self, other: "IntegerRange") -> "IntegerRange":
        lower = self.lower if self.lower == other.lower else None
        upper = self.upper if self.upper == other.upper else None
        if self.lower and other.lower and self.lower.value is None and other.lower.value is None:
            lower = SymbolicBound(None, min(self.lower.offset, other.lower.offset))
        if self.upper and other.upper and self.upper.value is None and other.upper.value is None:
            upper = SymbolicBound(None, max(self.upper.offset, other.upper.offset))
        return IntegerRange(lower, upper)
    def shifted(self, amount: int) -> "IntegerRange":
        def shift(bound):
            if bound is None: return None
            offset = bound.offset + amount
            if not INT_MIN <= offset <= INT_MAX: return None
            return SymbolicBound(bound.value, offset)
        return IntegerRange(shift(self.lower), shift(self.upper))
    def __str__(self) -> str:
        if self.is_unknown: return "unknown"
        if self.constant is not None: return f"exact({self.constant})"
        return f"[{self.lower or '-inf'}, {self.upper or '+inf'}]"


@dataclass(frozen=True)
class Relation:
    left: SSAValue
    operator: str
    right: SSAValue


@dataclass(frozen=True)
class RangeAnalysisResult:
    _ranges: dict[str, dict[SSAValue, IntegerRange]]
    _relations: dict[str, frozenset[Relation]]
    iterations: int

    def range_of(self, value: SSAValue, block: str) -> IntegerRange:
        return self._ranges.get(block, {}).get(value, IntegerRange.unknown())

    def prove(self, left: SSAValue, operator: str, right: SSAValue, block: str) -> ProofResult:
        relation = Relation(left, operator, right)
        relations = self._relations.get(block, frozenset())
        if relation in relations or Relation(right, _swap(operator), left) in relations:
            return ProofResult.PROVEN_TRUE
        negated = _negate(operator)
        if Relation(left, negated, right) in relations or Relation(right, _swap(negated), left) in relations:
            return ProofResult.PROVEN_FALSE
        left_range, right_range = self.range_of(left, block), self.range_of(right, block)
        return _prove_ranges(left_range, operator, right_range)

    def prove_less_than(self, left, right, block): return self.prove(left, "lt", right, block)
    def prove_less_equal(self, left, right, block): return self.prove(left, "le", right, block)
    def prove_equal(self, left, right, block): return self.prove(left, "eq", right, block)
    def prove_nonnegative(self, value: SSAValue, block: str) -> ProofResult:
        lower = self.range_of(value, block).lower
        if lower is not None and lower.value is None and lower.offset >= 0: return ProofResult.PROVEN_TRUE
        upper = self.range_of(value, block).upper
        if upper is not None and upper.value is None and upper.offset < 0: return ProofResult.PROVEN_FALSE
        return ProofResult.UNKNOWN

    def debug_string(self) -> str:
        lines = []
        for block in self._ranges:
            entries = ", ".join(f"{value.name}={fact}" for value, fact in sorted(self._ranges[block].items(), key=lambda item: item[0].name) if not fact.is_unknown)
            relations = ", ".join(f"{r.left.name} {r.operator} {r.right.name}" for r in sorted(self._relations.get(block, ()), key=lambda r: (r.left.name, r.operator, r.right.name)))
            lines.append(f"{block}: ranges[{entries}] facts[{relations}]")
        return "\n".join(lines)


class RangeAnalysis:
    """Forward fixed point. Joins intersect predicates and widen range bounds."""
    def compute(self, function: SSAFunction) -> RangeAnalysisResult:
        blocks = {block.name: block for block in function.blocks}; pred = predecessors(function)
        definitions = {instruction.result: instruction for block in function.blocks for instruction in block.instructions if isinstance(getattr(instruction, "result", None), SSAValue)}
        induction = {
            iv.value: iv
            for loop in LoopAnalysis().compute(function).loops
            for iv in loop.induction_variables
        }
        ranges: dict[str, dict[SSAValue, IntegerRange]] = {name: {} for name in blocks}
        relations: dict[str, frozenset[Relation]] = {name: frozenset() for name in blocks}
        order = reverse_postorder(function); limit = max(1, len(blocks) * 8); iterations = 0
        changed = True
        while changed and iterations < limit:
            changed = False; iterations += 1
            for name in order:
                incoming_maps = []; incoming_relations = []
                for edge in pred[name]:
                    edge_ranges = dict(ranges[edge.source]); edge_relations = set(relations[edge.source])
                    _refine_edge(blocks[edge.source], name, definitions, edge_ranges, edge_relations, edge.kind)
                    incoming_maps.append(edge_ranges); incoming_relations.append(edge_relations)
                state = _join_maps(incoming_maps) if incoming_maps else {}
                facts = frozenset(set.intersection(*incoming_relations)) if incoming_relations else frozenset()
                for instruction in blocks[name].instructions:
                    if isinstance(instruction, SSAConst) and isinstance(instruction.result.type, IntType) and isinstance(instruction.value, int) and not isinstance(instruction.value, bool):
                        state[instruction.result] = IntegerRange.exact(instruction.value)
                    elif isinstance(instruction, SSAPhi):
                        iv = induction.get(instruction.result)
                        if iv is not None:
                            initial = ranges[next(source for source, value in instruction.incoming if value == iv.initial_value)].get(iv.initial_value, IntegerRange.unknown())
                            state[instruction.result] = IntegerRange(initial.lower, None) if iv.step > 0 else IntegerRange(None, initial.upper)
                        else:
                            incoming = [ranges[source].get(value, IntegerRange.unknown()) for source, value in instruction.incoming]
                            state[instruction.result] = _join_ranges(incoming)
                    elif isinstance(instruction, SSABinaryOp) and isinstance(instruction.result.type, IntType):
                        state[instruction.result] = _binary_range(instruction, state)
                if state != ranges[name] or facts != relations[name]:
                    ranges[name] = state; relations[name] = facts; changed = True
        # Hitting the cap fails closed: facts still monotonically conservative.
        return RangeAnalysisResult(ranges, relations, iterations)


def _join_ranges(items):
    if not items: return IntegerRange.unknown()
    result = items[0]
    for item in items[1:]: result = result.join(item)
    return result

def _join_maps(maps):
    if not maps: return {}
    keys = set().union(*(item.keys() for item in maps)); return {key: _join_ranges([item.get(key, IntegerRange.unknown()) for item in maps]) for key in keys}

def _binary_range(instruction, state):
    left, right = state.get(instruction.left, IntegerRange.unknown()), state.get(instruction.right, IntegerRange.unknown())
    if instruction.operator == "add":
        if right.constant is not None: return left.shifted(right.constant)
        if left.constant is not None: return right.shifted(left.constant)
    if instruction.operator == "sub" and right.constant is not None: return left.shifted(-right.constant)
    return IntegerRange.unknown()

def _refine_edge(block, target, definitions, ranges, relations, kind):
    if kind != "normal" or not block.instructions or not isinstance(block.instructions[-1], SSABranch): return
    branch = block.instructions[-1]; compare = definitions.get(branch.condition)
    if not isinstance(compare, SSACompareOp): return
    operator = compare.operator if target == branch.true_target else _negate(compare.operator)
    relations.add(Relation(compare.left, operator, compare.right))
    right_constant = ranges.get(compare.right, IntegerRange.unknown()).constant
    left_constant = ranges.get(compare.left, IntegerRange.unknown()).constant
    if right_constant is not None:
        current = ranges.get(compare.left, IntegerRange.unknown())
        if operator == "lt": ranges[compare.left] = IntegerRange(current.lower, SymbolicBound(None, right_constant - 1))
        elif operator == "le": ranges[compare.left] = IntegerRange(current.lower, SymbolicBound(None, right_constant))
        elif operator == "gt": ranges[compare.left] = IntegerRange(SymbolicBound(None, right_constant + 1), current.upper)
        elif operator == "ge": ranges[compare.left] = IntegerRange(SymbolicBound(None, right_constant), current.upper)
        elif operator == "eq": ranges[compare.left] = IntegerRange.exact(right_constant)
    elif operator in {"lt", "le"}:
        current = ranges.get(compare.left, IntegerRange.unknown()); ranges[compare.left] = IntegerRange(current.lower, SymbolicBound(compare.right, -1 if operator == "lt" else 0))
    if left_constant is not None:
        _refine_value_against_constant(compare.right, _swap(operator), left_constant, ranges)

def _refine_value_against_constant(value, operator, constant, ranges):
    current = ranges.get(value, IntegerRange.unknown())
    if operator == "lt": ranges[value] = IntegerRange(current.lower, SymbolicBound(None, constant - 1))
    elif operator == "le": ranges[value] = IntegerRange(current.lower, SymbolicBound(None, constant))
    elif operator == "gt": ranges[value] = IntegerRange(SymbolicBound(None, constant + 1), current.upper)
    elif operator == "ge": ranges[value] = IntegerRange(SymbolicBound(None, constant), current.upper)
    elif operator == "eq": ranges[value] = IntegerRange.exact(constant)

def _prove_ranges(left, operator, right):
    lc, rc = left.constant, right.constant
    if lc is not None and rc is not None:
        result = {"lt": lc < rc, "le": lc <= rc, "gt": lc > rc, "ge": lc >= rc, "eq": lc == rc, "ne": lc != rc}[operator]
        return ProofResult.PROVEN_TRUE if result else ProofResult.PROVEN_FALSE
    if left.upper and right.lower and left.upper.value is None and right.lower.value is None:
        if operator == "lt" and left.upper.offset < right.lower.offset: return ProofResult.PROVEN_TRUE
        if operator == "le" and left.upper.offset <= right.lower.offset: return ProofResult.PROVEN_TRUE
    return ProofResult.UNKNOWN

def _negate(operator): return {"lt":"ge", "le":"gt", "gt":"le", "ge":"lt", "eq":"ne", "ne":"eq"}[operator]
def _swap(operator): return {"lt":"gt", "le":"ge", "gt":"lt", "ge":"le", "eq":"eq", "ne":"ne"}[operator]
