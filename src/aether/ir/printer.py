from __future__ import annotations

import json
from typing import Any

from .model import (
    IRBasicBlock,
    IRBinaryOp,
    IRBranch,
    IRCall,
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


class IRPrinter:
    """Produce a deterministic, human-readable representation of Aether IR."""

    def print_module(self, module: IRModule) -> str:
        return "\n\n".join(self._print_function(function) for function in module.functions)

    def _print_function(self, function: IRFunction) -> str:
        parameters = ", ".join(self._typed_value(parameter) for parameter in function.parameters)
        lines = [f"func {self._global_name(function.name)}({parameters}) -> {function.return_type} {{"]

        for index, block in enumerate(function.blocks):
            if index:
                lines.append("")
            lines.extend(self._print_block(block))

        lines.append("}")
        return "\n".join(lines)

    def _print_block(self, block: IRBasicBlock) -> list[str]:
        lines = [f"{block.name}:"]
        lines.extend(f"    {self._print_instruction(instruction)}" for instruction in block.instructions)
        return lines

    def _print_instruction(self, instruction: IRInstruction) -> str:
        if isinstance(instruction, IRConst):
            return f"{self._typed_value(instruction.result)} = const {self._literal(instruction.value)}"
        if isinstance(instruction, IRLoad):
            return f"{self._typed_value(instruction.result)} = load {self._value(instruction.slot)}"
        if isinstance(instruction, IRStore):
            return f"store {self._value(instruction.slot)}, {self._value(instruction.value)}"
        if isinstance(instruction, IRBinaryOp):
            return (
                f"{self._typed_value(instruction.result)} = {instruction.operator} "
                f"{self._value(instruction.left)}, {self._value(instruction.right)}"
            )
        if isinstance(instruction, IRCall):
            arguments = ", ".join(self._value(argument) for argument in instruction.arguments)
            call = f"call {self._global_name(instruction.function)}({arguments})"
            if instruction.result is None:
                return call
            return f"{self._typed_value(instruction.result)} = {call}"
        if isinstance(instruction, IRBranch):
            return (
                f"branch {self._value(instruction.condition)}, "
                f"{instruction.true_target}, {instruction.false_target}"
            )
        if isinstance(instruction, IRJump):
            return f"jump {instruction.target}"
        if isinstance(instruction, IRReturn):
            if instruction.value is None:
                return "return"
            return f"return {self._value(instruction.value)}"
        raise TypeError(f"Unsupported IR instruction: {type(instruction).__name__}")

    @staticmethod
    def _typed_value(value: IRValue) -> str:
        return f"{IRPrinter._value(value)}: {value.type}"

    @staticmethod
    def _value(value: IRValue) -> str:
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


def print_ir(module: IRModule) -> str:
    return IRPrinter().print_module(module)
