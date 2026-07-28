from __future__ import annotations

import json
from typing import Any

from .model import (
    IRAssign,
    IRArrayCopy,
    IRArrayGet,
    IRArrayLength,
    IRArrayNew,
    IRArraySlice,
    IRArraySet,
    IRBasicBlock,
    IRBinaryOp,
    IRBranch,
    IRCast,
    IRCall,
    IRCallIndirect,
    IRClassGet,
    IRClassNew,
    IRClassSet,
    IRCompareOp,
    IRConst,
    IRCopyInit,
    IRDestroy,
    IREnumConstant,
    IRFunction,
    IRFunctionRef,
    IRInterfaceConstruct,
    IRInstruction,
    IRInitDefault,
    IRJump,
    IRListGet,
    IRListCopy,
    IRListSlice,
    IRListContains,
    IRListClear,
    IRListPop,
    IRListPush,
    IRListInsert,
    IRListRemoveAt,
    IRListIndexOf,
    IRListIsEmpty,
    IRListLength,
    IRListNew,
    IRListSet,
    IRListReverse,
    IRSequenceSort,
    IRLoad,
    IRMatrixColumns,
    IRMatrixAdd,
    IRMatrixMatMul,
    IRMatrixVectorMul,
    IRMatrixScale,
    IRMatrixSub,
    IRMatrixGet,
    IRMatrixNew,
    IRMatrixRows,
    IRMatrixSet,
    IROuterProduct,
    IRModule,
    IRMoveInit,
    IRPrint,
    IRStructGet,
    IRStructNew,
    IRStructSet,
    IRMethodResultNew,
    IRMethodResultReceiver,
    IRMethodResultValue,
    IRReturn,
    IRRelocate,
    IRStore,
    IRUnaryOp,
    IRValue,
    IRVectorGet,
    IRVectorAdd,
    IRVectorDot,
    IRVectorMatrixMul,
    IRVectorScale,
    IRVectorSub,
    IRVectorLength,
    IRVectorNew,
    IRVectorSet,
)


class IRPrinter:
    """Produce a deterministic, human-readable representation of Aether IR."""

    def print_module(self, module: IRModule) -> str:
        structs = [
            f"struct @{definition.name} {{ "
            + ", ".join(f"{name}: {type_}" for name, type_ in definition.fields)
            + " }"
            for definition in module.structs
        ]
        functions = [self._print_function(function) for function in module.functions]
        return "\n\n".join([*structs, *functions])

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
        if isinstance(instruction, IRInitDefault):
            return f"init_default {self._typed_value(instruction.destination)}"
        if isinstance(instruction, IRCopyInit):
            return (
                f"copy_init {self._typed_value(instruction.destination)}, "
                f"{self._value(instruction.source)}"
            )
        if isinstance(instruction, IRMoveInit):
            return (
                f"move_init {self._typed_value(instruction.destination)}, "
                f"{self._value(instruction.source)}"
            )
        if isinstance(instruction, IRAssign):
            return (
                f"assign {self._typed_value(instruction.destination)}, "
                f"{self._value(instruction.source)}"
            )
        if isinstance(instruction, IRDestroy):
            return f"destroy {self._typed_value(instruction.value)}"
        if isinstance(instruction, IRRelocate):
            return (
                f"relocate {self._typed_value(instruction.destination)}, "
                f"{self._value(instruction.source)}, {instruction.count}"
            )
        if isinstance(instruction, IRBinaryOp):
            return (
                f"{self._typed_value(instruction.result)} = {instruction.operator} "
                f"{self._value(instruction.left)}, {self._value(instruction.right)}"
            )
        if isinstance(instruction, IRUnaryOp):
            return (
                f"{self._typed_value(instruction.result)} = {instruction.operator} "
                f"{self._value(instruction.operand)}"
            )
        if isinstance(instruction, IRCompareOp):
            shape = (
                " shape " + "x".join(str(size) for size in instruction.aggregate_shape)
                if instruction.aggregate_shape is not None
                else ""
            )
            return (
                f"{self._typed_value(instruction.result)} = cmp_{instruction.operator} "
                f"{self._value(instruction.left)}, {self._value(instruction.right)}{shape}"
            )
        if isinstance(instruction, IRCast):
            return (
                f"{self._typed_value(instruction.result)} = cast "
                f"{self._value(instruction.value)}"
            )
        if isinstance(instruction, IRCall):
            arguments = ", ".join(self._value(argument) for argument in instruction.arguments)
            operation = "builtin" if instruction.builtin is not None else "call"
            call = f"{operation} {self._global_name(instruction.function)}({arguments})"
            if instruction.result is None:
                return call
            return f"{self._typed_value(instruction.result)} = {call}"
        if isinstance(instruction, IRFunctionRef):
            return (
                f"{self._typed_value(instruction.result)} = function_ref "
                f"{self._global_name(instruction.function)}"
            )
        if isinstance(instruction, IRCallIndirect):
            arguments = ", ".join(self._value(argument) for argument in instruction.arguments)
            call = f"call_indirect {self._value(instruction.callee)}({arguments})"
            if instruction.result is None:
                return call
            return f"{self._typed_value(instruction.result)} = {call}"
        if isinstance(instruction, IRPrint):
            operation = "println" if instruction.newline else "print"
            shape = (
                " shape " + "x".join(str(size) for size in instruction.aggregate_shape)
                if instruction.aggregate_shape is not None
                else ""
            )
            return f"{operation} {self._value(instruction.value)}{shape}"
        if isinstance(instruction, IRStructNew):
            fields = ", ".join(self._value(value) for value in instruction.fields)
            return f"{self._typed_value(instruction.result)} = struct_new [{fields}]"
        if isinstance(instruction, IRClassNew):
            return f"{self._typed_value(instruction.result)} = class_new"
        if isinstance(instruction, IRInterfaceConstruct):
            return (
                f"{self._typed_value(instruction.result)} = interface_construct "
                f"{self._value(instruction.carrier)}, "
                f"witness @{instruction.witness.symbol} "
                f"[{instruction.witness.interface_id} <- "
                f"{instruction.witness.concrete_type_id}]"
            )
        if isinstance(instruction, IRClassGet):
            return (
                f"{self._typed_value(instruction.result)} = class_get "
                f"{self._value(instruction.object)}, "
                f"{instruction.field_name}#{instruction.field_index}"
            )
        if isinstance(instruction, IRClassSet):
            operation = "class_init" if instruction.initialize else "class_set"
            return (
                f"{operation} {self._value(instruction.object)}, "
                f"{instruction.field_name}#{instruction.field_index}, "
                f"{self._value(instruction.value)}"
            )
        if isinstance(instruction, IRStructGet):
            return (
                f"{self._typed_value(instruction.result)} = struct_get "
                f"{self._value(instruction.struct)}, {instruction.field_name}#{instruction.field_index}"
            )
        if isinstance(instruction, IRStructSet):
            return (
                f"{self._typed_value(instruction.result)} = struct_set "
                f"{self._value(instruction.struct)}, {instruction.field_name}#{instruction.field_index}, "
                f"{self._value(instruction.value)}"
            )
        if isinstance(instruction, IRMethodResultNew):
            value = "" if instruction.value is None else f", {self._value(instruction.value)}"
            return (
                f"{self._typed_value(instruction.result)} = method_result "
                f"{self._value(instruction.receiver)}{value}"
            )
        if isinstance(instruction, IRMethodResultReceiver):
            return (
                f"{self._typed_value(instruction.result)} = method_receiver "
                f"{self._value(instruction.method_result)}"
            )
        if isinstance(instruction, IRMethodResultValue):
            return (
                f"{self._typed_value(instruction.result)} = method_value "
                f"{self._value(instruction.method_result)}"
            )
        if isinstance(instruction, IRArrayNew):
            elements = ", ".join(self._value(element) for element in instruction.elements)
            return f"{self._typed_value(instruction.result)} = array_new [{elements}]"
        if isinstance(instruction, IRListNew):
            elements = ", ".join(self._value(element) for element in instruction.elements)
            return f"{self._typed_value(instruction.result)} = list_new [{elements}]"
        if isinstance(instruction, IRArrayCopy):
            return f"{self._typed_value(instruction.result)} = array_copy {self._value(instruction.array)}"
        if isinstance(instruction, IRListCopy):
            return f"{self._typed_value(instruction.result)} = list_copy {self._value(instruction.list_value)}"
        if isinstance(instruction, IRListContains):
            return (
                f"{self._typed_value(instruction.result)} = list_contains "
                f"{self._value(instruction.list_value)}, {self._value(instruction.value)}"
            )
        if isinstance(instruction, IRListIndexOf):
            return (
                f"{self._typed_value(instruction.result)} = list_index_of "
                f"{self._typed_value(instruction.list_value)}, {self._typed_value(instruction.value)}"
            )
        if isinstance(instruction, IRListClear):
            return f"list_clear {self._value(instruction.list_value)}"
        if isinstance(instruction, IRListPush):
            return f"list_push {self._value(instruction.list_value)}, {self._value(instruction.value)}"
        if isinstance(instruction, IRListInsert):
            return (
                f"list_insert {self._value(instruction.list_value)}, "
                f"{self._value(instruction.index)}, {self._value(instruction.value)}"
            )
        if isinstance(instruction, IRListPop):
            return f"{self._typed_value(instruction.result)} = list_pop {self._value(instruction.list_value)}"
        if isinstance(instruction, IRListRemoveAt):
            return (
                f"{self._typed_value(instruction.result)} = list_remove_at "
                f"{self._value(instruction.list_value)}, {self._value(instruction.index)}"
            )
        if isinstance(instruction, IRListReverse):
            return f"list_reverse {self._value(instruction.list_value)}"
        if isinstance(instruction, IRSequenceSort):
            return f"sequence_sort {self._value(instruction.sequence)}"
        if isinstance(instruction, IRVectorNew):
            elements = ", ".join(self._value(element) for element in instruction.elements)
            orientation = f" {instruction.orientation}" if instruction.orientation is not None else ""
            return f"{self._typed_value(instruction.result)} = vector_new{orientation} [{elements}]"
        if isinstance(instruction, IRMatrixNew):
            elements = ", ".join(self._value(element) for element in instruction.elements)
            return (
                f"{self._typed_value(instruction.result)} = matrix_new "
                f"{instruction.rows}x{instruction.cols} [{elements}]"
            )
        if isinstance(instruction, IRVectorAdd):
            orientation = f" {instruction.orientation}" if instruction.orientation is not None else ""
            return (
                f"{self._typed_value(instruction.result)} = vector_add{orientation} "
                f"{self._value(instruction.left)}, {self._value(instruction.right)} "
                f"length {instruction.length}"
            )
        if isinstance(instruction, IRVectorSub):
            orientation = f" {instruction.orientation}" if instruction.orientation is not None else ""
            return (
                f"{self._typed_value(instruction.result)} = vector_sub{orientation} "
                f"{self._value(instruction.left)}, {self._value(instruction.right)} "
                f"length {instruction.length}"
            )
        if isinstance(instruction, IRVectorScale):
            orientation = f" {instruction.orientation}" if instruction.orientation is not None else ""
            return (
                f"{self._typed_value(instruction.result)} = vector_scale{orientation} "
                f"{self._value(instruction.vector)}, {self._value(instruction.scalar)} "
                f"length {instruction.length}"
            )
        if isinstance(instruction, IRVectorDot):
            return (
                f"{self._typed_value(instruction.result)} = vector_dot row_column "
                f"{self._value(instruction.left)}, {self._value(instruction.right)} "
                f"length {instruction.length}"
            )
        if isinstance(instruction, IROuterProduct):
            return (
                f"{self._typed_value(instruction.result)} = outer_product column_row "
                f"{self._value(instruction.column)}, {self._value(instruction.row)} "
                f"{instruction.rows}x{instruction.cols}"
            )
        if isinstance(instruction, IRMatrixAdd):
            return (
                f"{self._typed_value(instruction.result)} = matrix_add "
                f"{self._value(instruction.left)}, {self._value(instruction.right)} "
                f"{instruction.rows}x{instruction.cols}"
            )
        if isinstance(instruction, IRMatrixSub):
            return (
                f"{self._typed_value(instruction.result)} = matrix_sub "
                f"{self._value(instruction.left)}, {self._value(instruction.right)} "
                f"{instruction.rows}x{instruction.cols}"
            )
        if isinstance(instruction, IRMatrixScale):
            return (
                f"{self._typed_value(instruction.result)} = matrix_scale "
                f"{self._value(instruction.matrix)}, {self._value(instruction.scalar)} "
                f"{instruction.rows}x{instruction.cols}"
            )
        if isinstance(instruction, IRMatrixMatMul):
            return (
                f"{self._typed_value(instruction.result)} = matrix_matmul "
                f"{self._value(instruction.left)}, {self._value(instruction.right)} "
                f"{instruction.rows}x{instruction.inner} * {instruction.inner}x{instruction.cols}"
            )
        if isinstance(instruction, IRMatrixVectorMul):
            return (
                f"{self._typed_value(instruction.result)} = matrix_vector_mul column "
                f"{self._value(instruction.matrix)}, {self._value(instruction.vector)} "
                f"{instruction.rows}x{instruction.inner} * {instruction.inner}"
            )
        if isinstance(instruction, IRVectorMatrixMul):
            return (
                f"{self._typed_value(instruction.result)} = vector_matrix_mul row "
                f"{self._value(instruction.vector)}, {self._value(instruction.matrix)} "
                f"{instruction.rows} * {instruction.rows}x{instruction.cols}"
            )
        if isinstance(instruction, IRArrayGet):
            return (
                f"{self._typed_value(instruction.result)} = "
                f"{'borrow_element array' if instruction.borrowed else 'array_get'} "
                f"{self._value(instruction.array)}, {self._value(instruction.index)}"
            )
        if isinstance(instruction, IRArraySlice):
            return (
                f"{self._typed_value(instruction.result)} = array_slice "
                f"{self._value(instruction.array)}, {self._value(instruction.start)}, "
                f"{self._value(instruction.end)}"
            )
        if isinstance(instruction, IRListSlice):
            return (
                f"{self._typed_value(instruction.result)} = list_slice "
                f"{self._value(instruction.list_value)}, {self._value(instruction.start)}, "
                f"{self._value(instruction.end)}"
            )
        if isinstance(instruction, IRListGet):
            return (
                f"{self._typed_value(instruction.result)} = "
                f"{'borrow_element list' if instruction.borrowed else 'list_get'} "
                f"{self._value(instruction.list_value)}, {self._value(instruction.index)}"
            )
        if isinstance(instruction, IRVectorGet):
            return (
                f"{self._typed_value(instruction.result)} = vector_get "
                f"{self._value(instruction.vector)}, {self._value(instruction.index)} base 1"
            )
        if isinstance(instruction, IRMatrixGet):
            return (
                f"{self._typed_value(instruction.result)} = matrix_get "
                f"{self._value(instruction.matrix)}, {self._value(instruction.row)}, "
                f"{self._value(instruction.column)} cols {instruction.cols} base 1"
            )
        if isinstance(instruction, IRArraySet):
            return (
                f"array_set {self._value(instruction.array)}, "
                f"{self._value(instruction.index)}, {self._value(instruction.value)}"
            )
        if isinstance(instruction, IRListSet):
            return (
                f"list_set {self._value(instruction.list_value)}, "
                f"{self._value(instruction.index)}, {self._value(instruction.value)}"
            )
        if isinstance(instruction, IRVectorSet):
            return (
                f"vector_set {self._value(instruction.vector)}, "
                f"{self._value(instruction.index)}, {self._value(instruction.value)} base 1"
            )
        if isinstance(instruction, IRMatrixSet):
            return (
                f"matrix_set {self._value(instruction.matrix)}, {self._value(instruction.row)}, "
                f"{self._value(instruction.column)}, {self._value(instruction.value)} "
                f"cols {instruction.cols} base 1"
            )
        if isinstance(instruction, IRArrayLength):
            return f"{self._typed_value(instruction.result)} = array_length {self._value(instruction.array)}"
        if isinstance(instruction, IRListLength):
            return f"{self._typed_value(instruction.result)} = list_length {self._value(instruction.list_value)}"
        if isinstance(instruction, IRListIsEmpty):
            return f"{self._typed_value(instruction.result)} = list_is_empty {self._value(instruction.list_value)}"
        if isinstance(instruction, IRVectorLength):
            return f"{self._typed_value(instruction.result)} = vector_length {self._value(instruction.vector)}"
        if isinstance(instruction, IRMatrixRows):
            return (
                f"{self._typed_value(instruction.result)} = matrix_rows "
                f"{self._value(instruction.matrix)} rows {instruction.rows}"
            )
        if isinstance(instruction, IRMatrixColumns):
            return (
                f"{self._typed_value(instruction.result)} = matrix_columns "
                f"{self._value(instruction.matrix)} columns {instruction.columns}"
            )
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
            transfer = (
                f" transfer {self._value(instruction.transferred_storage)}"
                if instruction.transferred_storage is not None
                else ""
            )
            return f"return {self._value(instruction.value)}{transfer}"
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
        if isinstance(value, IREnumConstant):
            return f"{value.enum_name}.{value.member_name}#{value.discriminant}"
        if value is None:
            return "null"
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, str):
            return json.dumps(value, ensure_ascii=False)
        return str(value)


def print_ir(module: IRModule) -> str:
    return IRPrinter().print_module(module)
