from __future__ import annotations

from typing import NoReturn

from aether.ir.model import (
    IRBasicBlock,
    IRBinaryOp,
    IRBranch,
    IRCall,
    IRCompareOp,
    IRConst,
    IRFunction,
    IRInstruction,
    IRJump,
    IRLoad,
    IRModule,
    IRReturn,
    IRStore,
    IRValue,
)

from .model import (
    SSABasicBlock,
    SSABinaryOp,
    SSACall,
    SSACompareOp,
    SSAConst,
    SSAFunction,
    SSAInstruction,
    SSAModule,
    SSAParameter,
    SSAReturn,
    SSAValue,
)


class SSABuildError(ValueError):
    """Raised when slot IR cannot be converted by the current SSA builder."""


class SSABuilder:
    """Convert the phase-1 linear subset of slot IR into value-based SSA."""

    _LINEAR_ONLY_MESSAGE = "SSA builder phase 1 only supports linear functions."

    def build(self, module: IRModule) -> SSAModule:
        return SSAModule([self._build_function(function) for function in module.functions])

    def _build_function(self, function: IRFunction) -> SSAFunction:
        block = self._require_linear_entry_block(function)
        parameters = [
            SSAParameter(parameter.name, parameter.type)
            for parameter in function.parameters
        ]
        value_map = {parameter.name: parameter for parameter in parameters}
        slot_values: dict[str, SSAValue] = {}
        instructions = self._build_block_instructions(block, value_map, slot_values)

        return SSAFunction(
            function.name,
            parameters,
            function.return_type,
            [SSABasicBlock(block.name, instructions)],
        )

    def _require_linear_entry_block(self, function: IRFunction) -> IRBasicBlock:
        if len(function.blocks) != 1 or function.blocks[0].name != "entry":
            self._fail(self._LINEAR_ONLY_MESSAGE)

        block = function.blocks[0]
        for instruction in block.instructions:
            if isinstance(instruction, (IRBranch, IRJump)):
                self._fail(self._LINEAR_ONLY_MESSAGE)
        return block

    def _build_block_instructions(
        self,
        block: IRBasicBlock,
        value_map: dict[str, SSAValue],
        slot_values: dict[str, SSAValue],
    ) -> list[SSAInstruction]:
        instructions: list[SSAInstruction] = []

        for instruction in block.instructions:
            if isinstance(instruction, IRConst):
                result = self._define_value(instruction.result, value_map)
                instructions.append(SSAConst(result, instruction.value))
                continue

            if isinstance(instruction, IRBinaryOp):
                result = self._define_value(instruction.result, value_map)
                left = self._resolve_value(instruction.left, value_map)
                right = self._resolve_value(instruction.right, value_map)
                instructions.append(
                    SSABinaryOp(result, instruction.operator, left, right)
                )
                continue

            if isinstance(instruction, IRCompareOp):
                result = self._define_value(instruction.result, value_map)
                left = self._resolve_value(instruction.left, value_map)
                right = self._resolve_value(instruction.right, value_map)
                instructions.append(
                    SSACompareOp(result, instruction.operator, left, right)
                )
                continue

            if isinstance(instruction, IRCall):
                arguments = tuple(
                    self._resolve_value(argument, value_map)
                    for argument in instruction.arguments
                )
                result = None
                if instruction.result is not None:
                    result = self._define_value(instruction.result, value_map)
                instructions.append(SSACall(instruction.function, arguments, result))
                continue

            if isinstance(instruction, IRStore):
                slot_values[instruction.slot.name] = self._resolve_value(
                    instruction.value,
                    value_map,
                )
                continue

            if isinstance(instruction, IRLoad):
                value = slot_values.get(instruction.slot.name)
                if value is None:
                    self._fail(
                        f"Load from uninitialized slot '{self._value(instruction.slot)}'."
                    )
                value_map[instruction.result.name] = value
                continue

            if isinstance(instruction, IRReturn):
                value = None
                if instruction.value is not None:
                    value = self._resolve_value(instruction.value, value_map)
                instructions.append(SSAReturn(value))
                continue

            self._fail(f"Unsupported IR instruction '{type(instruction).__name__}'.")

        return instructions

    @staticmethod
    def _define_value(
        value: IRValue,
        value_map: dict[str, SSAValue],
    ) -> SSAValue:
        ssa_value = SSAValue(value.name, value.type)
        value_map[value.name] = ssa_value
        return ssa_value

    @staticmethod
    def _resolve_value(
        value: IRValue,
        value_map: dict[str, SSAValue],
    ) -> SSAValue:
        ssa_value = value_map.get(value.name)
        if ssa_value is None:
            raise SSABuildError(f"Use of undefined IR value '{SSABuilder._value(value)}'.")
        return ssa_value

    @staticmethod
    def _value(value: IRValue) -> str:
        return value.name if value.name.startswith("%") else f"%{value.name}"

    @staticmethod
    def _fail(message: str) -> NoReturn:
        raise SSABuildError(message)
