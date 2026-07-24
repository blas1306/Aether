"""Characterize graph-semantic Python IRV-024 verification."""

from __future__ import annotations

from dataclasses import replace

import pytest

from aether.ir import (
    BoolType,
    IRBasicBlock,
    IRBranch,
    IRFunction,
    IRJump,
    IRLowerer,
    IRModule,
    IRParameter,
    IRReturn,
    IRVerificationError,
    IRVerifier,
    IntType,
)
from aether.pipeline import parse_source
from aether.typechecker import TypeChecker


def _cycle_module(header: str, *, optional_return: bool) -> IRModule:
    condition = IRParameter("condition", BoolType())
    value = IRParameter("value", IntType())
    header_terminator = (
        IRBranch(condition, "return_block", header)
        if optional_return
        else IRJump(header)
    )
    blocks = [
        IRBasicBlock("entry", [IRJump(header)]),
        IRBasicBlock(header, [header_terminator]),
    ]
    if optional_return:
        blocks.append(IRBasicBlock("return_block", [IRReturn(value)]))
    return IRModule([IRFunction("cycle", [condition, value], IntType(), blocks)])


@pytest.mark.parametrize(
    "header",
    ["cond", "for.cond", "loop", "arbitrary_name", "xyz"],
)
@pytest.mark.parametrize("optional_return", [False, True])
def test_python_irv_024_cycle_result_is_independent_of_block_name(
    header: str,
    optional_return: bool,
) -> None:
    module = _cycle_module(header, optional_return=optional_return)

    assert IRVerifier(module).verify() is module


def test_python_irv_024_accepts_entry_self_loop() -> None:
    module = IRModule(
        [
            IRFunction(
                "spin",
                [],
                IntType(),
                [IRBasicBlock("entry", [IRJump("entry")])],
            )
        ]
    )

    assert IRVerifier(module).verify() is module


def test_python_irv_024_accepts_infinite_cycle_plus_valued_exit() -> None:
    module = _cycle_module("arbitrary_header", optional_return=True)

    assert IRVerifier(module).verify() is module


@pytest.mark.parametrize("header", ["cond", "for.cond", "loop", "arbitrary_name", "xyz"])
def test_python_irv_024_ignores_unreachable_cycles_regardless_of_name(header: str) -> None:
    value = IRParameter("value", IntType())
    module = IRModule(
        [
            IRFunction(
                "unreachable_cycle",
                [value],
                IntType(),
                [
                    IRBasicBlock("entry", [IRReturn(value)]),
                    IRBasicBlock(header, [IRJump(header)]),
                ],
            )
        ]
    )

    assert IRVerifier(module).verify() is module


def _lower(source: str) -> IRModule:
    program = parse_source(source)
    TypeChecker().check(program)
    return IRLowerer().lower(program)


def _rename_non_entry_blocks(function: IRFunction) -> IRFunction:
    mapping = {
        block.name: "entry" if block.name == "entry" else f"arbitrary_{index}"
        for index, block in enumerate(function.blocks)
    }
    blocks: list[IRBasicBlock] = []
    for block in function.blocks:
        instructions = []
        for instruction in block.instructions:
            if isinstance(instruction, IRJump):
                instruction = replace(instruction, target=mapping[instruction.target])
            elif isinstance(instruction, IRBranch):
                instruction = replace(
                    instruction,
                    true_target=mapping[instruction.true_target],
                    false_target=mapping[instruction.false_target],
                )
            instructions.append(instruction)
        blocks.append(IRBasicBlock(mapping[block.name], instructions))
    return IRFunction(
        f"{function.name}_renamed",
        function.parameters,
        function.return_type,
        blocks,
    )


def _finite_missing_return_function() -> IRFunction:
    condition = IRParameter("condition", BoolType())
    value = IRParameter("value", IntType())
    return IRFunction(
        "finite_exit",
        [condition, value],
        IntType(),
        [
            IRBasicBlock("entry", [IRBranch(condition, "valued", "missing")]),
            IRBasicBlock("valued", [IRReturn(value)]),
            IRBasicBlock("missing", [IRReturn()]),
        ],
    )


@pytest.mark.parametrize(
    ("source", "expected_names"),
    [
        (
            """
int countDown(int n) {
    while (n > 0) {
        n = n - 1;
    }
    return n;
}
""",
            ["entry", "cond0", "body0", "exit0"],
        ),
        (
            """
int sumTo(int n) {
    int total = 0;
    for (i in 1:n) {
        total = total + i;
    }
    return total;
}
""",
            [
                "entry",
                "for.cond0",
                "for.body0",
                "for.inc0",
                "for.advance0",
                "for.exit0",
            ],
        ),
    ],
)
def test_python_irv_024_graph_isomorphism_preserves_accepted_outcome(
    source: str,
    expected_names: list[str],
) -> None:
    module = _lower(source)
    function = module.functions[0]
    assert [block.name for block in function.blocks] == expected_names
    assert IRVerifier(module).verify() is module

    renamed = IRModule([_rename_non_entry_blocks(function)])
    assert IRVerifier(renamed).verify() is renamed


def test_python_irv_024_arbitrary_renaming_preserves_rejected_outcome() -> None:
    function = _finite_missing_return_function()

    for candidate in (function, _rename_non_entry_blocks(function)):
        with pytest.raises(
            IRVerificationError,
            match="Return type mismatch: expected int, got void",
        ):
            IRVerifier(IRModule([candidate])).verify()


def test_python_irv_024_rejects_reachable_valueless_return() -> None:
    module = IRModule(
        [
            IRFunction(
                "missing",
                [],
                IntType(),
                [IRBasicBlock("entry", [IRReturn()])],
            )
        ]
    )

    with pytest.raises(
        IRVerificationError,
        match="Return type mismatch: expected int, got void",
    ):
        IRVerifier(module).verify()


def test_python_irv_024_rejects_finite_missing_return_path() -> None:
    module = IRModule([_finite_missing_return_function()])

    with pytest.raises(
        IRVerificationError,
        match="Return type mismatch: expected int, got void",
    ):
        IRVerifier(module).verify()
