from __future__ import annotations

import json
from typing import Any

from .model import (
    SSAArrayCopy,
    SSAArrayGet,
    SSAArrayLength,
    SSAArrayNew,
    SSAArraySlice,
    SSAArraySet,
    SSABasicBlock,
    SSABinaryOp,
    SSABranch,
    SSACast,
    SSACall,
    SSACallIndirect,
    SSACatchEntry,
    SSAClassGet,
    SSAClassNew,
    SSAClassSet,
    SSACompareOp,
    SSAConst,
    SSAExceptionDestroy,
    SSAExceptionMatch,
    SSAExceptionPayload,
    SSAFunction,
    SSAFunctionRef,
    SSAInterfaceCall,
    SSAInterfaceConstruct,
    SSAInvoke,
    SSAInvokeIndirect,
    SSAInvokeInterface,
    SSAInstruction,
    SSAJump,
    SSAListGet,
    SSAListCopy,
    SSAListSlice,
    SSAListContains,
    SSAListClear,
    SSAListPop,
    SSAListPush,
    SSAListInsert,
    SSAListRemoveAt,
    SSAListIndexOf,
    SSAListIsEmpty,
    SSAListLength,
    SSAListNew,
    SSAListSet,
    SSAListReverse,
    SSASequenceSort,
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
    SSAPackException,
    SSAParameter,
    SSAPrint,
    SSAStructGet,
    SSAStructNew,
    SSAStructSet,
    SSAMethodResultNew,
    SSAMethodResultReceiver,
    SSAMethodResultValue,
    SSAPhi,
    SSAPropagate,
    SSARethrow,
    SSAReturn,
    SSAThrow,
    SSAUnaryOp,
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
from aether.ir.model import IREnumConstant


class SSAPrinter:
    """Produce a deterministic, human-readable representation of Aether SSA."""

    def print_module(self, module: SSAModule) -> str:
        structs = [
            f"struct @{definition.name} {{ "
            + ", ".join(f"{name}: {type_}" for name, type_ in definition.fields)
            + " }"
            for definition in module.structs
        ]
        return "\n\n".join([*structs, *(self._print_function(function) for function in module.functions)])

    def _print_function(self, function: SSAFunction) -> str:
        parameters = ", ".join(self._typed_value(parameter) for parameter in function.parameters)
        effect = " may_throw" if function.may_throw else ""
        lines = [
            f"func {self._global_name(function.name)}({parameters}) -> "
            f"{function.return_type}{effect} {{"
        ]

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
        if isinstance(instruction, SSAUnaryOp):
            return (
                f"{self._typed_value(instruction.result)} = {instruction.operator} "
                f"{self._value(instruction.operand)}"
            )
        if isinstance(instruction, SSACompareOp):
            shape = (
                " shape " + "x".join(str(size) for size in instruction.aggregate_shape)
                if instruction.aggregate_shape is not None
                else ""
            )
            return (
                f"{self._typed_value(instruction.result)} = cmp_{instruction.operator} "
                f"{self._value(instruction.left)}, {self._value(instruction.right)}{shape}"
            )
        if isinstance(instruction, SSACast):
            return (
                f"{self._typed_value(instruction.result)} = cast "
                f"{self._value(instruction.value)}"
            )
        if isinstance(instruction, SSACall):
            arguments = ", ".join(self._value(argument) for argument in instruction.arguments)
            operation = "builtin" if instruction.builtin is not None else "call"
            call = f"{operation} {self._global_name(instruction.function)}({arguments})"
            if instruction.result is None:
                return call
            return f"{self._typed_value(instruction.result)} = {call}"
        if isinstance(instruction, SSAInvoke):
            arguments = ", ".join(
                self._value(argument) for argument in instruction.arguments
            )
            result = (
                "void"
                if instruction.result is None
                else self._typed_value(instruction.result)
            )
            return (
                f"invoke {self._global_name(instruction.function)}({arguments}) -> "
                f"normal {instruction.normal_target} "
                f"{self._edge_arguments(instruction.normal_arguments, result)}, "
                f"exceptional {instruction.exceptional_target} "
                f"{self._edge_arguments(instruction.exceptional_arguments)}"
            )
        if isinstance(instruction, SSAFunctionRef):
            return (
                f"{self._typed_value(instruction.result)} = function_ref "
                f"{self._global_name(instruction.function)}"
            )
        if isinstance(instruction, SSACallIndirect):
            arguments = ", ".join(self._value(argument) for argument in instruction.arguments)
            call = f"call_indirect {self._value(instruction.callee)}({arguments})"
            if instruction.result is None:
                return call
            return f"{self._typed_value(instruction.result)} = {call}"
        if isinstance(instruction, SSAInvokeIndirect):
            arguments = ", ".join(
                self._value(argument) for argument in instruction.arguments
            )
            result = (
                "void"
                if instruction.result is None
                else self._typed_value(instruction.result)
            )
            return (
                f"invoke_indirect {self._value(instruction.callee)}({arguments}) -> "
                f"normal {instruction.normal_target} "
                f"{self._edge_arguments(instruction.normal_arguments, result)}, "
                f"exceptional {instruction.exceptional_target} "
                f"{self._edge_arguments(instruction.exceptional_arguments)}"
            )
        if isinstance(instruction, SSAPrint):
            operation = "println" if instruction.newline else "print"
            shape = (
                " shape " + "x".join(str(size) for size in instruction.aggregate_shape)
                if instruction.aggregate_shape is not None
                else ""
            )
            return f"{operation} {self._value(instruction.value)}{shape}"
        if isinstance(instruction, SSAStructNew):
            return f"{self._typed_value(instruction.result)} = struct_new [" + ", ".join(self._value(value) for value in instruction.fields) + "]"
        if isinstance(instruction, SSAClassNew):
            return f"{self._typed_value(instruction.result)} = class_new"
        if isinstance(instruction, SSAInterfaceConstruct):
            return (
                f"{self._typed_value(instruction.result)} = interface_construct "
                f"{self._value(instruction.carrier)}, "
                f"witness @{instruction.witness.symbol} "
                f"[{instruction.witness.interface_id} <- "
                f"{instruction.witness.concrete_type_id}]"
            )
        if isinstance(instruction, SSAInterfaceCall):
            arguments = ", ".join(
                self._value(argument) for argument in instruction.arguments
            )
            call = (
                f"interface_call {self._value(instruction.receiver)} "
                f"slot {instruction.slot.index} "
                f"[{instruction.slot.method_id}]({arguments})"
            )
            if instruction.result is None:
                return call
            return f"{self._typed_value(instruction.result)} = {call}"
        if isinstance(instruction, SSAInvokeInterface):
            arguments = ", ".join(
                self._value(argument) for argument in instruction.arguments
            )
            result = (
                "void"
                if instruction.result is None
                else self._typed_value(instruction.result)
            )
            return (
                f"invoke_interface {self._value(instruction.receiver)} "
                f"slot {instruction.slot.index} "
                f"[{instruction.slot.method_id}]({arguments}) -> "
                f"normal {instruction.normal_target} "
                f"{self._edge_arguments(instruction.normal_arguments, result)}, "
                f"exceptional {instruction.exceptional_target} "
                f"{self._edge_arguments(instruction.exceptional_arguments)}"
            )
        if isinstance(instruction, SSAClassGet):
            return (
                f"{self._typed_value(instruction.result)} = class_get "
                f"{self._value(instruction.object)}, "
                f"{instruction.field_name}#{instruction.field_index}"
            )
        if isinstance(instruction, SSAClassSet):
            operation = "class_init" if instruction.initialize else "class_set"
            return (
                f"{operation} {self._value(instruction.object)}, "
                f"{instruction.field_name}#{instruction.field_index}, "
                f"{self._value(instruction.value)}"
            )
        if isinstance(instruction, SSAStructGet):
            return f"{self._typed_value(instruction.result)} = struct_get {self._value(instruction.struct)}, {instruction.field_name}#{instruction.field_index}"
        if isinstance(instruction, SSAStructSet):
            return f"{self._typed_value(instruction.result)} = struct_set {self._value(instruction.struct)}, {instruction.field_name}#{instruction.field_index}, {self._value(instruction.value)}"
        if isinstance(instruction, SSAMethodResultNew):
            value = "" if instruction.value is None else f", {self._value(instruction.value)}"
            return f"{self._typed_value(instruction.result)} = method_result {self._value(instruction.receiver)}{value}"
        if isinstance(instruction, SSAMethodResultReceiver):
            return f"{self._typed_value(instruction.result)} = method_receiver {self._value(instruction.method_result)}"
        if isinstance(instruction, SSAMethodResultValue):
            return f"{self._typed_value(instruction.result)} = method_value {self._value(instruction.method_result)}"
        if isinstance(instruction, SSAArrayNew):
            elements = ", ".join(self._value(element) for element in instruction.elements)
            return f"{self._typed_value(instruction.result)} = array_new [{elements}]"
        if isinstance(instruction, SSAListNew):
            elements = ", ".join(self._value(element) for element in instruction.elements)
            return f"{self._typed_value(instruction.result)} = list_new [{elements}]"
        if isinstance(instruction, SSAArrayCopy):
            return f"{self._typed_value(instruction.result)} = array_copy {self._value(instruction.array)}"
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
        if isinstance(instruction, SSAListClear):
            return f"list_clear {self._value(instruction.list_value)}"
        if isinstance(instruction, SSAListPush):
            return f"list_push {self._value(instruction.list_value)}, {self._value(instruction.value)}"
        if isinstance(instruction, SSAListInsert):
            return (
                f"list_insert {self._value(instruction.list_value)}, "
                f"{self._value(instruction.index)}, {self._value(instruction.value)}"
            )
        if isinstance(instruction, SSAListPop):
            return f"{self._typed_value(instruction.result)} = list_pop {self._value(instruction.list_value)}"
        if isinstance(instruction, SSAListRemoveAt):
            return (
                f"{self._typed_value(instruction.result)} = list_remove_at "
                f"{self._value(instruction.list_value)}, {self._value(instruction.index)}"
            )
        if isinstance(instruction, SSAListReverse):
            return f"list_reverse {self._value(instruction.list_value)}"
        if isinstance(instruction, SSASequenceSort):
            return f"sequence_sort {self._value(instruction.sequence)}"
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
                f"{self._typed_value(instruction.result)} = "
                f"{'borrow_element array' if instruction.borrowed else 'array_get'} "
                f"{self._value(instruction.array)}, {self._value(instruction.index)}"
            )
        if isinstance(instruction, SSAArraySlice):
            return (
                f"{self._typed_value(instruction.result)} = array_slice "
                f"{self._value(instruction.array)}, {self._value(instruction.start)}, "
                f"{self._value(instruction.end)}"
            )
        if isinstance(instruction, SSAListSlice):
            return (
                f"{self._typed_value(instruction.result)} = list_slice "
                f"{self._value(instruction.list_value)}, {self._value(instruction.start)}, "
                f"{self._value(instruction.end)}"
            )
        if isinstance(instruction, SSAListGet):
            return (
                f"{self._typed_value(instruction.result)} = "
                f"{'borrow_element list' if instruction.borrowed else 'list_get'} "
                f"{self._value(instruction.list_value)}, {self._value(instruction.index)}"
            )
        if isinstance(instruction, SSAVectorGet):
            return (
                f"{self._typed_value(instruction.result)} = vector_get "
                f"{self._value(instruction.vector)}, {self._value(instruction.index)} base 1"
            )
        if isinstance(instruction, SSAMatrixGet):
            return (
                f"{self._typed_value(instruction.result)} = matrix_get "
                f"{self._value(instruction.matrix)}, {self._value(instruction.row)}, "
                f"{self._value(instruction.column)} cols {instruction.cols} base 1"
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
                f"{self._value(instruction.index)}, {self._value(instruction.value)} base 1"
            )
        if isinstance(instruction, SSAMatrixSet):
            return (
                f"matrix_set {self._value(instruction.matrix)}, {self._value(instruction.row)}, "
                f"{self._value(instruction.column)}, {self._value(instruction.value)} "
                f"cols {instruction.cols} base 1"
            )
        if isinstance(instruction, SSAArrayLength):
            return f"{self._typed_value(instruction.result)} = array_length {self._value(instruction.array)}"
        if isinstance(instruction, SSAListLength):
            return f"{self._typed_value(instruction.result)} = list_length {self._value(instruction.list_value)}"
        if isinstance(instruction, SSAListIsEmpty):
            return f"{self._typed_value(instruction.result)} = list_is_empty {self._value(instruction.list_value)}"
        if isinstance(instruction, SSAPackException):
            descriptor = (
                "dynamic"
                if instruction.dynamic_type is None
                else self._global_name(instruction.dynamic_type)
            )
            return (
                f"{self._typed_value(instruction.result)} = exception_pack "
                f"{self._value(instruction.payload)} descriptor {descriptor}"
            )
        if isinstance(instruction, SSACatchEntry):
            catches = ", ".join(
                self._global_name(catch_type)
                for catch_type in instruction.catch_types
            )
            return (
                f"catch_entry {instruction.handler_id} "
                f"{self._typed_value(instruction.event)} [{catches}]"
            )
        if isinstance(instruction, SSAExceptionMatch):
            mode = "catch_all" if instruction.catch_all else "exact"
            return (
                f"{self._typed_value(instruction.result)} = exception_match {mode} "
                f"{self._value(instruction.event)}, "
                f"{self._global_name(instruction.catch_type)}"
            )
        if isinstance(instruction, SSAExceptionPayload):
            return (
                f"{self._typed_value(instruction.result)} = exception_borrow "
                f"{self._value(instruction.event)} as "
                f"{self._global_name(instruction.catch_type)}"
            )
        if isinstance(instruction, SSAExceptionDestroy):
            return f"exception_destroy {self._value(instruction.event)}"
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
        if isinstance(instruction, (SSAThrow, SSARethrow, SSAPropagate)):
            operation = {
                SSAThrow: "throw",
                SSARethrow: "rethrow",
                SSAPropagate: "propagate",
            }[type(instruction)]
            if instruction.target is None:
                return f"{operation} {self._value(instruction.event)} -> unwind"
            return (
                f"{operation} {self._value(instruction.event)} -> exceptional "
                f"{instruction.target} "
                f"{self._edge_arguments(instruction.exceptional_arguments)}"
            )
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
    def _edge_arguments(
        arguments: tuple[SSAValue, ...],
        empty_label: str | None = None,
    ) -> str:
        if arguments:
            return "[" + ", ".join(SSAPrinter._value(value) for value in arguments) + "]"
        return f"[{empty_label}]" if empty_label is not None else "[]"

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


def print_ssa(module: SSAModule) -> str:
    return SSAPrinter().print_module(module)
