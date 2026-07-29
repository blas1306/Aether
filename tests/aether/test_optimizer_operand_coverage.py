from __future__ import annotations

from dataclasses import dataclass

from aether.ir.model import (
    IRBasicBlock,
    IRCast,
    IRFunction,
    IRInstruction,
    IRInterfaceConstruct,
    IRModule,
    IRParameter,
    IRReturn,
    IRValue,
    IRWitnessTable,
)
from aether.ir.operands import (
    instruction_operands as ir_instruction_operands,
    rewrite_instruction_operands as rewrite_ir_instruction_operands,
    validate_operand_coverage as validate_ir_operand_coverage,
)
from aether.ir.optimizer import AlgebraicSimplifier
from aether.ir.types import ClassRefType, InterfaceType
from aether.ssa.model import (
    SSABasicBlock,
    SSACast,
    SSAFunction,
    SSAInstruction,
    SSAInterfaceConstruct,
    SSAModule,
    SSAParameter,
    SSAPhi,
    SSAReturn,
    SSAValue,
)
from aether.ssa.operands import (
    instruction_operands as ssa_instruction_operands,
    rewrite_instruction_operands as rewrite_ssa_instruction_operands,
    validate_operand_coverage as validate_ssa_operand_coverage,
)
from aether.ssa.optimizer import (
    DeadPhiEliminator,
    SSAAlgebraicSimplifier,
    TrivialPhiEliminator,
)


@dataclass(frozen=True)
class _IRCoverageProbe(IRInstruction):
    result: IRValue
    direct: IRValue
    nested: tuple[tuple[str, IRValue], ...]


@dataclass(frozen=True)
class _SSACoverageProbe(SSAInstruction):
    result: SSAValue
    direct: SSAValue
    nested: tuple[tuple[str, SSAValue], ...]


def test_ir_instruction_hierarchy_and_nested_operands_are_structurally_covered() -> None:
    type_ = ClassRefType("Counter")
    result = IRValue("result", type_)
    first = IRValue("first", type_)
    second = IRValue("second", type_)
    replacement = IRValue("replacement", type_)
    instruction = _IRCoverageProbe(result, first, (("edge", second),))

    validate_ir_operand_coverage()
    assert ir_instruction_operands(instruction) == (first, second)

    rewritten, count = rewrite_ir_instruction_operands(
        instruction,
        lambda value: replacement if value in {first, second} else value,
    )
    assert count == 2
    assert rewritten.result is result
    assert rewritten.direct is replacement
    assert rewritten.nested == (("edge", replacement),)


def test_ssa_instruction_hierarchy_and_nested_operands_are_structurally_covered() -> None:
    type_ = InterfaceType("Value")
    result = SSAValue("result", type_)
    first = SSAValue("first", type_)
    second = SSAValue("second", type_)
    replacement = SSAValue("replacement", type_)
    instruction = _SSACoverageProbe(result, first, (("edge", second),))

    validate_ssa_operand_coverage()
    assert ssa_instruction_operands(instruction) == (first, second)

    rewritten, count = rewrite_ssa_instruction_operands(
        instruction,
        lambda value: replacement if value in {first, second} else value,
    )
    assert count == 2
    assert rewritten.result is result
    assert rewritten.direct is replacement
    assert rewritten.nested == (("edge", replacement),)


def test_dead_phi_keeps_value_used_only_as_interface_carrier() -> None:
    class_type = ClassRefType("Counter")
    interface_type = InterfaceType("Value")
    common = SSAParameter("common", class_type)
    phi_result = SSAValue("phi", class_type)
    interface_result = SSAValue("interface", interface_type)
    witness = IRWitnessTable("witness", "Value", "Counter", "class", ())
    module = SSAModule(
        [
            SSAFunction(
                "probe",
                [common],
                interface_type,
                [
                    SSABasicBlock(
                        "entry",
                        [
                            SSAPhi(phi_result, (("entry", common),)),
                            SSAInterfaceConstruct(
                                interface_result,
                                phi_result,
                                witness,
                            ),
                            SSAReturn(interface_result),
                        ],
                    )
                ],
            )
        ]
    )

    result = DeadPhiEliminator().run(module)

    assert result.changed is False
    assert isinstance(result.module.functions[0].blocks[0].instructions[0], SSAPhi)


def test_trivial_phi_and_algebraic_rewriters_update_interface_carriers() -> None:
    class_type = ClassRefType("Counter")
    interface_type = InterfaceType("Value")
    common = SSAParameter("common", class_type)
    phi_result = SSAValue("phi", class_type)
    interface_result = SSAValue("interface", interface_type)
    witness = IRWitnessTable("witness", "Value", "Counter", "class", ())
    module = SSAModule(
        [
            SSAFunction(
                "probe",
                [common],
                interface_type,
                [
                    SSABasicBlock(
                        "entry",
                        [
                            SSAPhi(phi_result, (("entry", common),)),
                            SSAInterfaceConstruct(
                                interface_result,
                                phi_result,
                                witness,
                            ),
                            SSAReturn(interface_result),
                        ],
                    )
                ],
            )
        ]
    )

    trivial = TrivialPhiEliminator().run(module)
    construct = trivial.module.functions[0].blocks[0].instructions[0]
    assert isinstance(construct, SSAInterfaceConstruct)
    assert construct.carrier is common

    cast_result = SSAValue("cast", class_type)
    algebraic_module = SSAModule(
        [
            SSAFunction(
                "probe",
                [common],
                interface_type,
                [
                    SSABasicBlock(
                        "entry",
                        [
                            SSACast(cast_result, common),
                            SSAInterfaceConstruct(
                                interface_result,
                                cast_result,
                                witness,
                            ),
                            SSAReturn(interface_result),
                        ],
                    )
                ],
            )
        ]
    )
    algebraic = SSAAlgebraicSimplifier().run(algebraic_module)
    construct = algebraic.module.functions[0].blocks[0].instructions[0]
    assert isinstance(construct, SSAInterfaceConstruct)
    assert construct.carrier is common


def test_ir_algebraic_rewriter_updates_interface_carrier_after_copy_elision() -> None:
    class_type = ClassRefType("Counter")
    interface_type = InterfaceType("Value")
    common = IRParameter("common", class_type)
    cast_result = IRValue("cast", class_type)
    interface_result = IRValue("interface", interface_type)
    witness = IRWitnessTable("witness", "Value", "Counter", "class", ())
    module = IRModule(
        [
            IRFunction(
                "probe",
                [common],
                interface_type,
                [
                    IRBasicBlock(
                        "entry",
                        [
                            IRCast(cast_result, common),
                            IRInterfaceConstruct(
                                interface_result,
                                cast_result,
                                witness,
                            ),
                            IRReturn(interface_result),
                        ],
                    )
                ],
            )
        ]
    )

    result = AlgebraicSimplifier().run(module)
    construct = result.module.functions[0].blocks[0].instructions[0]
    assert isinstance(construct, IRInterfaceConstruct)
    assert construct.carrier is common
