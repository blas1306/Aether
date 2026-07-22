"""Characterize the current Python IRV-024 recursive approximation."""

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


@pytest.mark.parametrize("optional_return", [False, True])
@pytest.mark.parametrize(
    ("header", "accepted"),
    [
        ("cond", True),
        ("for.cond", True),
        ("loop", False),
        ("arbitrary_name", False),
        ("xyz", False),
    ],
)
def test_python_irv_024_cycle_result_depends_on_revisited_block_name(
    header: str,
    accepted: bool,
    optional_return: bool,
) -> None:
    module = _cycle_module(header, optional_return=optional_return)

    if accepted:
        assert IRVerifier(module).verify() is module
    else:
        with pytest.raises(
            IRVerificationError,
            match="may exit without returning a value",
        ):
            IRVerifier(module).verify()


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
def test_python_irv_024_accepts_lowering_names_but_rejects_isomorphic_renaming(
    source: str,
    expected_names: list[str],
) -> None:
    module = _lower(source)
    function = module.functions[0]
    assert [block.name for block in function.blocks] == expected_names
    assert IRVerifier(module).verify() is module

    renamed = IRModule([_rename_non_entry_blocks(function)])
    with pytest.raises(
        IRVerificationError,
        match="may exit without returning a value",
    ):
        IRVerifier(renamed).verify()
