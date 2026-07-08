from __future__ import annotations

import json
from typing import Any

from .model import (
    SSAArrayGet,
    SSAArrayLength,
    SSAArrayNew,
    SSAArraySet,
    SSABasicBlock,
    SSABinaryOp,
    SSABranch,
    SSACast,
    SSACall,
    SSACompareOp,
    SSAConst,
    SSAFunction,
    SSAInstruction,
    SSAJump,
    SSAMatrixGet,
    SSAMatrixNew,
    SSAModule,
    SSAParameter,
    SSAPhi,
    SSAReturn,
    SSAValue,
    SSAVectorGet,
    SSAVectorNew,
)


class SSAPrinter:
    """Produce a deterministic, human-readable representation of Aether SSA."""

    def print_module(self, module: SSAModule) -> str:
        return "\n\n".join(self._print_function(function) for function in module.functions)

    def _print_function(self, function: SSAFunction) -> str:
        parameters = ", ".join(self._typed_value(parameter) for parameter in function.parameters)
        lines = [f"func {self._global_name(function.name)}({parameters}) -> {function.return_type} {{"]

        for index, block in enumerate(function.blocks):
            if index:
                lines.append("")
            lines.extend(self._print_block(block))

        lines.append("}")
        return "\n".join(lines)

    def _print_block(self, block: SSABasicBlock) -> list[str]:
        lines = [f"{block.name}:"]
        lines.extend(f"    {self._print_instruction(instruction)}" for instruction in block.instructions)
        return lines

    def _print_instruction(self, instruction: SSAInstruction) -> str:
        if isinstance(instruction, SSAConst):
            return f"{self._typed_value(instruction.result)} = const {self._literal(instruction.value)}"
        if isinstance(instruction, SSABinaryOp):
            return (
                f"{self._typed_value(instruction.result)} = {instruction.operator} "
                f"{self._value(instruction.left)}, {self._value(instruction.right)}"
            )
        if isinstance(instruction, SSACompareOp):
            return (
                f"{self._typed_value(instruction.result)} = cmp_{instruction.operator} "
                f"{self._value(instruction.left)}, {self._value(instruction.right)}"
            )
        if isinstance(instruction, SSACast):
            return (
                f"{self._typed_value(instruction.result)} = cast "
                f"{self._value(instruction.value)}"
            )
        if isinstance(instruction, SSACall):
            arguments = ", ".join(self._value(argument) for argument in instruction.arguments)
            call = f"call {self._global_name(instruction.function)}({arguments})"
            if instruction.result is None:
                return call
            return f"{self._typed_value(instruction.result)} = {call}"
        if isinstance(instruction, SSAArrayNew):
            elements = ", ".join(self._value(element) for element in instruction.elements)
            return f"{self._typed_value(instruction.result)} = array_new [{elements}]"
        if isinstance(instruction, SSAVectorNew):
            elements = ", ".join(self._value(element) for element in instruction.elements)
            orientation = f" {instruction.orientation}" if instruction.orientation is not None else ""
            return f"{self._typed_value(instruction.result)} = vector_new{orientation} [{elements}]"
        if isinstance(instruction, SSAMatrixNew):
            elements = ", ".join(self._value(element) for element in instruction.elements)
            return (
                f"{self._typed_value(instruction.result)} = matrix_new "
                f"{instruction.rows}x{instruction.cols} [{elements}]"
            )
        if isinstance(instruction, SSAArrayGet):
            return (
                f"{self._typed_value(instruction.result)} = array_get "
                f"{self._value(instruction.array)}, {self._value(instruction.index)}"
            )
        if isinstance(instruction, SSAVectorGet):
            return (
                f"{self._typed_value(instruction.result)} = vector_get "
                f"{self._value(instruction.vector)}, {self._value(instruction.index)}"
            )
        if isinstance(instruction, SSAMatrixGet):
            return (
                f"{self._typed_value(instruction.result)} = matrix_get "
                f"{self._value(instruction.matrix)}, {self._value(instruction.row)}, "
                f"{self._value(instruction.column)} cols {instruction.cols}"
            )
        if isinstance(instruction, SSAArraySet):
            return (
                f"array_set {self._value(instruction.array)}, "
                f"{self._value(instruction.index)}, {self._value(instruction.value)}"
            )
        if isinstance(instruction, SSAArrayLength):
            return f"{self._typed_value(instruction.result)} = array_length {self._value(instruction.array)}"
        if isinstance(instruction, SSAPhi):
            incoming = ", ".join(
                f"{block_name}: {self._value(value)}"
                for block_name, value in instruction.incoming
            )
            return f"{self._typed_value(instruction.result)} = phi({incoming})"
        if isinstance(instruction, SSABranch):
            return (
                f"branch {self._value(instruction.condition)}, "
                f"{instruction.true_target}, {instruction.false_target}"
            )
        if isinstance(instruction, SSAJump):
            return f"jump {instruction.target}"
        if isinstance(instruction, SSAReturn):
            if instruction.value is None:
                return "return"
            return f"return {self._value(instruction.value)}"
        raise TypeError(f"Unsupported SSA instruction: {type(instruction).__name__}")

    @staticmethod
    def _typed_value(value: SSAValue) -> str:
        return f"{SSAPrinter._value(value)}: {value.type}"

    @staticmethod
    def _value(value: SSAValue) -> str:
        return value.name if value.name.startswith("%") else f"%{value.name}"

    @staticmethod
    def _global_name(name: str) -> str:
        return name if name.startswith("@") else f"@{name}"

    @staticmethod
    def _literal(value: Any) -> str:
        if value is None:
            return "null"
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, str):
            return json.dumps(value, ensure_ascii=False)
        return str(value)


def print_ssa(module: SSAModule) -> str:
    return SSAPrinter().print_module(module)
