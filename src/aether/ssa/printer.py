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
    SSAListGet,
    SSAListCopy,
    SSAListContains,
    SSAListIndexOf,
    SSAListIsEmpty,
    SSAListLength,
    SSAListNew,
    SSAListSet,
    SSAListReverse,
    SSAMatrixColumns,
    SSAMatrixAdd,
    SSAMatrixMatMul,
    SSAMatrixVectorMul,
    SSAMatrixScale,
    SSAMatrixSub,
    SSAMatrixGet,
    SSAMatrixNew,
    SSAMatrixRows,
    SSAMatrixSet,
    SSAModule,
    SSAOuterProduct,
    SSAParameter,
    SSAPhi,
    SSAReturn,
    SSAValue,
    SSAVectorGet,
    SSAVectorAdd,
    SSAVectorDot,
    SSAVectorMatrixMul,
    SSAVectorScale,
    SSAVectorSub,
    SSAVectorLength,
    SSAVectorNew,
    SSAVectorSet,
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
        if isinstance(instruction, SSAListNew):
            elements = ", ".join(self._value(element) for element in instruction.elements)
            return f"{self._typed_value(instruction.result)} = list_new [{elements}]"
        if isinstance(instruction, SSAListCopy):
            return f"{self._typed_value(instruction.result)} = list_copy {self._value(instruction.list_value)}"
        if isinstance(instruction, SSAListContains):
            return (
                f"{self._typed_value(instruction.result)} = list_contains "
                f"{self._value(instruction.list_value)}, {self._value(instruction.value)}"
            )
        if isinstance(instruction, SSAListIndexOf):
            return (
                f"{self._typed_value(instruction.result)} = list_index_of "
                f"{self._typed_value(instruction.list_value)}, {self._typed_value(instruction.value)}"
            )
        if isinstance(instruction, SSAListReverse):
            return f"list_reverse {self._value(instruction.list_value)}"
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
        if isinstance(instruction, SSAVectorAdd):
            orientation = f" {instruction.orientation}" if instruction.orientation is not None else ""
            return (
                f"{self._typed_value(instruction.result)} = vector_add{orientation} "
                f"{self._value(instruction.left)}, {self._value(instruction.right)} "
                f"length {instruction.length}"
            )
        if isinstance(instruction, SSAVectorSub):
            orientation = f" {instruction.orientation}" if instruction.orientation is not None else ""
            return (
                f"{self._typed_value(instruction.result)} = vector_sub{orientation} "
                f"{self._value(instruction.left)}, {self._value(instruction.right)} "
                f"length {instruction.length}"
            )
        if isinstance(instruction, SSAVectorScale):
            orientation = f" {instruction.orientation}" if instruction.orientation is not None else ""
            return (
                f"{self._typed_value(instruction.result)} = vector_scale{orientation} "
                f"{self._value(instruction.vector)}, {self._value(instruction.scalar)} "
                f"length {instruction.length}"
            )
        if isinstance(instruction, SSAVectorDot):
            return (
                f"{self._typed_value(instruction.result)} = vector_dot row_column "
                f"{self._value(instruction.left)}, {self._value(instruction.right)} "
                f"length {instruction.length}"
            )
        if isinstance(instruction, SSAOuterProduct):
            return (
                f"{self._typed_value(instruction.result)} = outer_product column_row "
                f"{self._value(instruction.column)}, {self._value(instruction.row)} "
                f"{instruction.rows}x{instruction.cols}"
            )
        if isinstance(instruction, SSAMatrixAdd):
            return (
                f"{self._typed_value(instruction.result)} = matrix_add "
                f"{self._value(instruction.left)}, {self._value(instruction.right)} "
                f"{instruction.rows}x{instruction.cols}"
            )
        if isinstance(instruction, SSAMatrixSub):
            return (
                f"{self._typed_value(instruction.result)} = matrix_sub "
                f"{self._value(instruction.left)}, {self._value(instruction.right)} "
                f"{instruction.rows}x{instruction.cols}"
            )
        if isinstance(instruction, SSAMatrixScale):
            return (
                f"{self._typed_value(instruction.result)} = matrix_scale "
                f"{self._value(instruction.matrix)}, {self._value(instruction.scalar)} "
                f"{instruction.rows}x{instruction.cols}"
            )
        if isinstance(instruction, SSAMatrixMatMul):
            return (
                f"{self._typed_value(instruction.result)} = matrix_matmul "
                f"{self._value(instruction.left)}, {self._value(instruction.right)} "
                f"{instruction.rows}x{instruction.inner} * {instruction.inner}x{instruction.cols}"
            )
        if isinstance(instruction, SSAMatrixVectorMul):
            return (
                f"{self._typed_value(instruction.result)} = matrix_vector_mul column "
                f"{self._value(instruction.matrix)}, {self._value(instruction.vector)} "
                f"{instruction.rows}x{instruction.inner} * {instruction.inner}"
            )
        if isinstance(instruction, SSAVectorMatrixMul):
            return (
                f"{self._typed_value(instruction.result)} = vector_matrix_mul row "
                f"{self._value(instruction.vector)}, {self._value(instruction.matrix)} "
                f"{instruction.rows} * {instruction.rows}x{instruction.cols}"
            )
        if isinstance(instruction, SSAArrayGet):
            return (
                f"{self._typed_value(instruction.result)} = array_get "
                f"{self._value(instruction.array)}, {self._value(instruction.index)}"
            )
        if isinstance(instruction, SSAListGet):
            return (
                f"{self._typed_value(instruction.result)} = list_get "
                f"{self._value(instruction.list_value)}, {self._value(instruction.index)}"
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
        if isinstance(instruction, SSAListSet):
            return (
                f"list_set {self._value(instruction.list_value)}, "
                f"{self._value(instruction.index)}, {self._value(instruction.value)}"
            )
        if isinstance(instruction, SSAVectorSet):
            return (
                f"vector_set {self._value(instruction.vector)}, "
                f"{self._value(instruction.index)}, {self._value(instruction.value)}"
            )
        if isinstance(instruction, SSAMatrixSet):
            return (
                f"matrix_set {self._value(instruction.matrix)}, {self._value(instruction.row)}, "
                f"{self._value(instruction.column)}, {self._value(instruction.value)} "
                f"cols {instruction.cols}"
            )
        if isinstance(instruction, SSAArrayLength):
            return f"{self._typed_value(instruction.result)} = array_length {self._value(instruction.array)}"
        if isinstance(instruction, SSAListLength):
            return f"{self._typed_value(instruction.result)} = list_length {self._value(instruction.list_value)}"
        if isinstance(instruction, SSAListIsEmpty):
            return f"{self._typed_value(instruction.result)} = list_is_empty {self._value(instruction.list_value)}"
        if isinstance(instruction, SSAVectorLength):
            return f"{self._typed_value(instruction.result)} = vector_length {self._value(instruction.vector)}"
        if isinstance(instruction, SSAMatrixRows):
            return (
                f"{self._typed_value(instruction.result)} = matrix_rows "
                f"{self._value(instruction.matrix)} rows {instruction.rows}"
            )
        if isinstance(instruction, SSAMatrixColumns):
            return (
                f"{self._typed_value(instruction.result)} = matrix_columns "
                f"{self._value(instruction.matrix)} columns {instruction.columns}"
            )
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
