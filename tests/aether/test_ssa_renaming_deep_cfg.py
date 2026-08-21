from __future__ import annotations

import ast
import inspect
import textwrap

import pytest

from aether.analysis.cfg import CFGBuilder
from aether.analysis.dominance_frontier import DominanceFrontierAnalysis
from aether.analysis.dominators import DominatorAnalysis
from aether.ir import (
    BoolType,
    IntType,
    IRBasicBlock,
    IRBranch,
    IRConst,
    IRFunction,
    IRJump,
    IRLoad,
    IRParameter,
    IRReturn,
    IRStore,
    IRValue,
)
from aether.ssa import GeneralSSABuilder, SSARenamer
from aether.ssa.phi_placement import PhiPlacement
from aether.ssa.renaming import _MISSING


def _linear_function(size: int) -> IRFunction:
    slot = IRValue("scale_slot", IntType())
    blocks = [IRBasicBlock("entry", [IRConst(IRValue("v0", IntType()), 0), IRStore(slot, IRValue("v0", IntType())), IRJump("b1")])]
    for index in range(1, size - 1):
        value = IRValue(f"v{index}", IntType())
        blocks.append(IRBasicBlock(f"b{index}", [IRConst(value, index), IRStore(slot, value), IRJump(f"b{index + 1}")]))
    loaded = IRValue("final", IntType())
    blocks.append(IRBasicBlock(f"b{size - 1}", [IRLoad(loaded, slot), IRReturn(loaded)]))
    return IRFunction(f"linear_{size}", [], IntType(), blocks)


def _diamond_function() -> IRFunction:
    condition = IRParameter("condition", BoolType())
    slot = IRValue("slot", IntType())
    left = IRValue("value", IntType())
    right = IRValue("value.1", IntType())
    loaded = IRValue("merged", IntType())
    return IRFunction(
        "diamond",
        [condition],
        IntType(),
        [
            IRBasicBlock("entry", [IRBranch(condition, "left", "right")]),
            IRBasicBlock("left", [IRConst(left, 1), IRStore(slot, left), IRJump("merge")]),
            IRBasicBlock("right", [IRConst(right, 2), IRStore(slot, right), IRJump("merge")]),
            IRBasicBlock("merge", [IRLoad(loaded, slot), IRReturn(loaded)]),
        ],
    )


class _RecursiveReferenceRenamer(SSARenamer):
    """The pre-SSA-ROBUST-1 traversal, retained only as a test oracle."""

    def _rename_blocks(self, entry: str) -> None:
        self._rename_reference_block(entry)

    def _rename_reference_block(self, block_name: str) -> None:
        if block_name in self._visited:
            return
        self._visited.add(block_name)
        pushed_slots = []
        bound_values = []
        instructions = []
        for phi in self._phi_states.get(block_name, ()):
            self._bind_value(phi.result.name, phi.result, bound_values)
            self._push_slot(phi.slot_name, phi.result)
            pushed_slots.append(phi.slot_name)
        for instruction in self._blocks[block_name].instructions:
            converted = self._convert_instruction(instruction, pushed_slots, bound_values)
            if converted is not None:
                instructions.append(converted)
        self._ssa_instructions[block_name] = instructions
        self._add_successor_phi_incomings(block_name)
        for child in self._dominator_children(block_name):
            self._rename_reference_block(child)
        for slot_name in reversed(pushed_slots):
            self._pop_slot(slot_name)
        for value_name, previous in reversed(bound_values):
            if previous is _MISSING:
                self._value_map.pop(value_name, None)
            else:
                self._value_map[value_name] = previous


def _rename(function: IRFunction, renamer_type=SSARenamer):
    cfg = CFGBuilder().build(function)
    dominators = DominatorAnalysis(cfg).compute()
    frontier = DominanceFrontierAnalysis(cfg, dominators).compute()
    placement = PhiPlacement(function, cfg, dominators, frontier).place()
    return renamer_type(function, cfg, dominators, placement).rename()


@pytest.mark.parametrize("factory", [lambda: _linear_function(100), _diamond_function])
def test_iterative_renaming_is_exactly_equal_to_recursive_reference(factory) -> None:
    function = factory()
    assert _rename(function) == _rename(function, _RecursiveReferenceRenamer)


@pytest.mark.parametrize("size", [100, 993, 1000, 5000])
def test_production_builder_handles_deep_linear_dominator_trees(size: int) -> None:
    result = GeneralSSABuilder().build_function(_linear_function(size))
    assert len(result.blocks) == size


def test_production_renamer_has_no_recursive_dominator_tree_descent() -> None:
    tree = ast.parse(textwrap.dedent(inspect.getsource(SSARenamer._rename_blocks)))
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)]
    assert not any(
        isinstance(call.func, ast.Attribute)
        and call.func.attr == SSARenamer._rename_blocks.__name__
        for call in calls
    )
