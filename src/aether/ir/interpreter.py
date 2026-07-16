from __future__ import annotations

from dataclasses import dataclass, field
import math
from math import trunc
from typing import Any, Callable, NoReturn, Sequence

from aether.array_safety import checked_array_length_to_int
from aether.collection_value import CollectionObject, copy_init_value, destroy_value
from aether.errors import AetherRuntimeError
from aether.process_arguments import (
    PROCESS_ARGS_BUILTIN,
    normalize_program_arguments,
    process_args_ir_snapshot,
)
from aether.integer_arithmetic import checked_int_binary, ieee_divide
from aether.list_safety import checked_list_index_to_int, checked_list_length_to_int
from aether.stdlib.registry import call_builtin
from aether.string_value import (
    STRING_SPLIT_BUILTIN,
    STRING_TRIM_BUILTIN,
    StringValue,
    aether_string_split,
    aether_string_trim,
    as_string_value,
)
from aether.string_parsing import (
    PARSE_DOUBLE_BUILTIN,
    PARSE_INT_BUILTIN,
    PARSE_STATUS_TYPE,
    parse_double_bytes,
    parse_int_bytes,
)
from aether.text_file_io import (
    APPEND_TEXT_BUILTIN,
    FILE_STATUS_TYPE,
    READ_TEXT_BUILTIN,
    WRITE_TEXT_BUILTIN,
    append_text,
    read_text,
    write_text,
)
from aether.types import AetherValue
from aether.vector_matrix_safety import (
    MATRIX_INDEX_OUT_OF_BOUNDS,
    VECTOR_INDEX_OUT_OF_BOUNDS,
    checked_matrix_offset,
    checked_vector_offset,
)

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
    IRCompareOp,
    IRConst,
    IRCopyInit,
    IRDestroy,
    IREnumConstant,
    IRFunction,
    IRFunctionRef,
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
    IRModule,
    IRMoveInit,
    IROuterProduct,
    IRPrint,
    IRStructGet,
    IRStructNew,
    IRStructSet,
    IRMethodResultNew,
    IRMethodResultReceiver,
    IRMethodResultValue,
    IRReturn,
    IRRelocate,
    IRStorage,
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
from .types import (
    ArrayType,
    BoolType,
    ClassRefType,
    DoubleType,
    EnumType,
    FloatType,
    IntType,
    InterfaceType,
    ListType,
    MatrixType,
    MethodResultType,
    StringType,
    StructType,
    VectorType,
    VoidType,
)
from .equality import ir_eq_capability, ir_values_equal


class IRExecutionError(RuntimeError):
    """Raised when the minimal IR interpreter cannot execute validly."""


@dataclass
class _Frame:
    values: dict[IRValue, Any] = field(default_factory=dict)
    slots: dict[IRValue, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class _IRFunctionReference:
    function: IRFunction


class IRInterpreter:
    """Execute the initial Aether IR control-flow subset."""

    def __init__(
        self,
        module: IRModule,
        *,
        write_output: Callable[[str], None] | None = None,
        program_arguments: Sequence[str] = (),
    ) -> None:
        self.module = module
        self._functions = {function.name: function for function in module.functions}
        self._structs = {definition.name: definition for definition in module.structs}
        self.output = ""
        self._output_writer = write_output
        self._program_arguments = normalize_program_arguments(program_arguments)

    def call(self, function_name: str, arguments: Sequence[Any] = ()) -> Any:
        """Call an IR function by name using raw Python scalar values."""
        function = self._functions.get(function_name)
        if function is None:
            raise IRExecutionError(f"IR function '{function_name}' does not exist")

        if len(arguments) != len(function.parameters):
            raise IRExecutionError(
                f"IR function '{function_name}' expects {len(function.parameters)} "
                f"arguments, got {len(arguments)}"
            )

        frame = _Frame(
            values={
                parameter: (
                    as_string_value(argument)
                    if isinstance(parameter.type, StringType) and isinstance(argument, (str, StringValue))
                    else argument
                )
                for parameter, argument in zip(function.parameters, arguments)
            },
        )
        return self._execute(function, frame)

    def _format_print_value(
        self,
        value: Any,
        value_type: object,
        aggregate_shape: tuple[int, ...] | None,
    ) -> str:
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value_type, EnumType):
            if not isinstance(value, IREnumConstant) or value.enum_name != value_type.name:
                raise IRExecutionError("IR Enum print requires a matching nominal enum value")
            return f"{value_type.display_name or value_type.name}.{value.member_name}"
        if isinstance(value_type, VectorType):
            if not isinstance(value, list) or aggregate_shape is None:
                raise IRExecutionError("IR Vector print requires a shaped vector value")
            separator = "; " if value_type.orientation == "column" else " "
            return "[" + separator.join(
                self._format_aggregate_element(element, value_type.element)
                for element in value
            ) + "]"
        if isinstance(value_type, MatrixType):
            if not isinstance(value, list) or aggregate_shape is None or len(aggregate_shape) != 2:
                raise IRExecutionError("IR Matrix print requires a shaped matrix value")
            rows, columns = aggregate_shape
            if len(value) != rows * columns:
                raise IRExecutionError("IR Matrix print shape does not match its value")
            rendered = [
                " ".join(
                    self._format_aggregate_element(element, value_type.element)
                    for element in value[row * columns : (row + 1) * columns]
                )
                for row in range(rows)
            ]
            if rows == 1 and columns == 1:
                return self._format_aggregate_element(value[0], value_type.element)
            return "[" + "; ".join(rendered) + "]"
        if isinstance(value_type, (ArrayType, ListType)):
            if not isinstance(value, list):
                raise IRExecutionError("IR sequence print requires a sequence value")
            return "{" + ", ".join(
                self._format_aggregate_element(element, value_type.element)
                for element in value
            ) + "}"
        if isinstance(value_type, StructType):
            definition = self._structs.get(value_type.name)
            if definition is None or not isinstance(value, tuple):
                raise IRExecutionError("IR Struct print requires a declared struct value")
            fields = ", ".join(
                f"{name}={self._format_print_value(field_value, field_type, None)}"
                for (name, field_type), field_value in zip(definition.fields, value)
            )
            return f"{value_type.name}({fields})"
        return str(value)

    def _format_aggregate_element(self, value: Any, value_type: object) -> str:
        if isinstance(value_type, StringType):
            escaped = str(value).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\t", "\\t")
            return f'"{escaped}"'
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value_type, EnumType):
            return self._format_print_value(value, value_type, None)
        if isinstance(value_type, StructType):
            return self._format_print_value(value, value_type, None)
        return str(value)

    def _execute(self, function: IRFunction, frame: _Frame) -> Any:
        blocks = {block.name: block for block in function.blocks}
        current = blocks.get("entry")
        if current is None:
            raise IRExecutionError(f"IR function '{function.name}' has no entry block")

        while True:
            for instruction in current.instructions:
                returned, value, target = self._execute_instruction(instruction, frame)
                if returned:
                    if value is None and not isinstance(function.return_type, VoidType):
                        raise IRExecutionError(
                            f"IR function '{function.name}' returned void but is non-void"
                        )
                    return value
                if target is not None:
                    current = self._target_block(function, blocks, target)
                    break
            else:
                if isinstance(function.return_type, VoidType):
                    return None
                raise IRExecutionError(
                    f"IR function '{function.name}' ended without return"
                )

    def _execute_instruction(
        self,
        instruction: IRInstruction,
        frame: _Frame,
    ) -> tuple[bool, Any, str | None]:
        if isinstance(instruction, IRConst):
            frame.values[instruction.result] = (
                as_string_value(instruction.value)
                if isinstance(instruction.result.type, StringType)
                and isinstance(instruction.value, (str, StringValue))
                else instruction.value
            )
            return False, None, None

        if isinstance(instruction, IRLoad):
            if instruction.slot not in frame.slots:
                raise IRExecutionError(
                    f"IR slot '%{instruction.slot.name}' is not initialized"
                )
            frame.values[instruction.result] = frame.slots[instruction.slot]
            return False, None, None

        if isinstance(instruction, IRStore):
            frame.slots[instruction.slot] = self._value(instruction.value, frame)
            return False, None, None

        if isinstance(instruction, IRInitDefault):
            if instruction.destination in frame.slots:
                raise IRExecutionError(
                    f"init_default destination '%{instruction.destination.name}' is already alive"
                )
            frame.slots[instruction.destination] = self._default_lifecycle_value(
                instruction.destination.type
            )
            return False, None, None

        if isinstance(instruction, IRCopyInit):
            if instruction.destination in frame.slots:
                raise IRExecutionError(
                    f"copy_init destination '%{instruction.destination.name}' is already alive"
                )
            frame.slots[instruction.destination] = copy_init_value(
                self._lifecycle_value(instruction.source, frame)
            )
            return False, None, None

        if isinstance(instruction, IRMoveInit):
            if instruction.destination in frame.slots:
                raise IRExecutionError(
                    f"move_init destination '%{instruction.destination.name}' is already alive"
                )
            if instruction.source not in frame.slots:
                raise IRExecutionError(
                    f"move_init source '%{instruction.source.name}' is not alive"
                )
            frame.slots[instruction.destination] = frame.slots.pop(instruction.source)
            return False, None, None

        if isinstance(instruction, IRAssign):
            if instruction.destination not in frame.slots:
                raise IRExecutionError(
                    f"assign destination '%{instruction.destination.name}' is not alive"
                )
            replacement = copy_init_value(self._lifecycle_value(instruction.source, frame))
            old = frame.slots[instruction.destination]
            frame.slots[instruction.destination] = replacement
            destroy_value(old)
            return False, None, None

        if isinstance(instruction, IRDestroy):
            if instruction.value not in frame.slots:
                raise IRExecutionError(
                    f"destroy operand '%{instruction.value.name}' is not alive"
                )
            destroy_value(frame.slots.pop(instruction.value))
            return False, None, None

        if isinstance(instruction, IRRelocate):
            if instruction.destination in frame.slots:
                raise IRExecutionError(
                    f"relocate destination '%{instruction.destination.name}' is already alive"
                )
            if instruction.source not in frame.slots:
                raise IRExecutionError(
                    f"relocate source '%{instruction.source.name}' is not alive"
                )
            frame.slots[instruction.destination] = frame.slots.pop(instruction.source)
            return False, None, None

        if isinstance(instruction, IRBinaryOp):
            left = self._value(instruction.left, frame)
            right = self._value(instruction.right, frame)
            frame.values[instruction.result] = self._binary(
                instruction.operator,
                left,
                right,
                checked_int=isinstance(instruction.left.type, IntType)
                and isinstance(instruction.right.type, IntType)
                and instruction.may_trap,
            )
            return False, None, None

        if isinstance(instruction, IRUnaryOp):
            operand = self._value(instruction.operand, frame)
            if instruction.operator != "not" or not isinstance(operand, bool):
                raise IRExecutionError(
                    f"Unsupported IR unary operation '{instruction.operator}'"
                )
            frame.values[instruction.result] = not operand
            return False, None, None

        if isinstance(instruction, IRCompareOp):
            left = self._value(instruction.left, frame)
            right = self._value(instruction.right, frame)
            if instruction.operator in {"eq", "ne"} and ir_eq_capability(
                instruction.left.type, self._structs
            ) is not None:
                equal = ir_values_equal(
                    instruction.left.type, left, right, self._structs
                )
                frame.values[instruction.result] = (
                    equal if instruction.operator == "eq" else not equal
                )
            elif instruction.aggregate_shape is not None:
                expected = math.prod(instruction.aggregate_shape)
                if not isinstance(left, list) or not isinstance(right, list):
                    raise IRExecutionError("IR aggregate compare requires aggregate values")
                if len(left) != expected or len(right) != expected:
                    raise IRExecutionError("IR aggregate compare shape mismatch")
                equal = all(left_value == right_value for left_value, right_value in zip(left, right))
                frame.values[instruction.result] = equal if instruction.operator == "eq" else not equal
            else:
                frame.values[instruction.result] = self._compare(
                    instruction.operator,
                    left,
                    right,
                )
            return False, None, None

        if isinstance(instruction, IRCast):
            frame.values[instruction.result] = self._cast(
                self._value(instruction.value, frame),
                instruction.result.type,
            )
            return False, None, None

        if isinstance(instruction, IRCall):
            arguments = [
                self._value(argument, frame) for argument in instruction.arguments
            ]
            if instruction.builtin is not None:
                if instruction.builtin == PROCESS_ARGS_BUILTIN:
                    if arguments or instruction.result is None:
                        raise IRExecutionError("System.args requires zero arguments and a result")
                    frame.values[instruction.result] = process_args_ir_snapshot(
                        self._program_arguments
                    )
                    return False, None, None
                if instruction.builtin == "__aether_string_byte_length":
                    if len(arguments) != 1 or instruction.result is None:
                        raise IRExecutionError("IR string byteLength requires one argument and a result")
                    value = arguments[0]
                    if not isinstance(value, StringValue):
                        raise IRExecutionError("IR string byteLength requires a string value")
                    result = value.byte_length
                    if result > (1 << 31) - 1:
                        raise IRExecutionError("Aether string byte length does not fit in int")
                    frame.values[instruction.result] = result
                    return False, None, None
                if instruction.builtin == STRING_TRIM_BUILTIN:
                    if len(arguments) != 1 or instruction.result is None:
                        raise IRExecutionError("IR string trim requires one receiver and a result")
                    value = arguments[0]
                    if not isinstance(value, StringValue):
                        raise IRExecutionError("IR string trim requires a string value")
                    frame.values[instruction.result] = aether_string_trim(value)
                    return False, None, None
                if instruction.builtin == STRING_SPLIT_BUILTIN:
                    if len(arguments) != 2 or instruction.result is None:
                        raise IRExecutionError(
                            "IR string split requires receiver, separator, and result"
                        )
                    text, separator = arguments
                    if not isinstance(text, StringValue) or not isinstance(separator, StringValue):
                        raise IRExecutionError("IR string split operands must be strings")
                    frame.values[instruction.result] = aether_string_split(text, separator)
                    return False, None, None
                if instruction.builtin in {PARSE_INT_BUILTIN, PARSE_DOUBLE_BUILTIN}:
                    if len(arguments) != 1 or instruction.result is None:
                        raise IRExecutionError("IR string parsing requires one argument and a result")
                    text = arguments[0]
                    if not isinstance(text, StringValue):
                        raise IRExecutionError("IR string parsing requires a string value")
                    parsed = (
                        parse_int_bytes(text.utf8_bytes)
                        if instruction.builtin == PARSE_INT_BUILTIN
                        else parse_double_bytes(text.utf8_bytes)
                    )
                    status = int(parsed.status)
                    frame.values[instruction.result] = (
                        parsed.value,
                        IREnumConstant(
                            PARSE_STATUS_TYPE,
                            parsed.status.name,
                            status,
                            status,
                        ),
                    )
                    return False, None, None
                if instruction.builtin == READ_TEXT_BUILTIN:
                    if len(arguments) != 1 or instruction.result is None:
                        raise IRExecutionError("IR io.readText requires one argument and a result")
                    path = arguments[0]
                    if not isinstance(path, StringValue):
                        raise IRExecutionError("IR io.readText path must be string")
                    read = read_text(path)
                    status = int(read.status)
                    frame.values[instruction.result] = (
                        read.content,
                        IREnumConstant(
                            FILE_STATUS_TYPE,
                            read.status.name,
                            status,
                            status,
                        ),
                    )
                    return False, None, None
                if instruction.builtin in {WRITE_TEXT_BUILTIN, APPEND_TEXT_BUILTIN}:
                    if len(arguments) != 2 or instruction.result is None:
                        raise IRExecutionError("IR text-file write requires two arguments and a result")
                    path, content = arguments
                    if not isinstance(path, StringValue) or not isinstance(content, StringValue):
                        raise IRExecutionError("IR text-file write arguments must be string")
                    status_value = (
                        write_text(path, content)
                        if instruction.builtin == WRITE_TEXT_BUILTIN
                        else append_text(path, content)
                    )
                    status = int(status_value)
                    frame.values[instruction.result] = IREnumConstant(
                        FILE_STATUS_TYPE,
                        status_value.name,
                        status,
                        status,
                    )
                    return False, None, None
                if instruction.builtin == "__aether_retain":
                    if len(arguments) != 1 or instruction.result is not None:
                        raise IRExecutionError("IR retain requires one argument and no result")
                    copy_init_value(arguments[0])
                    return False, None, None
                if instruction.builtin == "__aether_release":
                    if len(arguments) != 1 or instruction.result is not None:
                        raise IRExecutionError("IR release requires one argument and no result")
                    destroy_value(arguments[0])
                    return False, None, None
                try:
                    result = call_builtin(
                        instruction.builtin,
                        [
                            AetherValue(self._aether_scalar_type(argument.type), value)
                            for argument, value in zip(instruction.arguments, arguments)
                        ],
                        self._output_writer or (lambda _text: None),
                    ).value
                except AetherRuntimeError as exc:
                    raise IRExecutionError(str(exc)) from exc
            else:
                result = self.call(instruction.function, arguments)
            if instruction.result is not None:
                frame.values[instruction.result] = result
            return False, None, None

        if isinstance(instruction, IRFunctionRef):
            function = self._functions.get(instruction.function)
            if function is None:
                raise IRExecutionError(
                    f"IR function reference '{instruction.function}' does not exist"
                )
            frame.values[instruction.result] = _IRFunctionReference(function)
            return False, None, None

        if isinstance(instruction, IRCallIndirect):
            reference = self._value(instruction.callee, frame)
            if not isinstance(reference, _IRFunctionReference):
                raise IRExecutionError("IR indirect call callee is not a function reference")
            arguments = [
                self._value(argument, frame) for argument in instruction.arguments
            ]
            result = self.call(reference.function.name, arguments)
            if instruction.result is not None:
                frame.values[instruction.result] = result
            return False, None, None

        if isinstance(instruction, IRPrint):
            value = self._value(instruction.value, frame)
            text = self._format_print_value(
                value,
                instruction.value.type,
                instruction.aggregate_shape,
            )
            if instruction.newline:
                text += "\n"
            self.output += text
            if self._output_writer is not None:
                self._output_writer(text)
            return False, None, None

        if isinstance(instruction, IRStructNew):
            frame.values[instruction.result] = tuple(
                copy_init_value(self._value(field, frame))
                for field in instruction.fields
            )
            return False, None, None

        if isinstance(instruction, IRStructGet):
            struct = self._value(instruction.struct, frame)
            if not isinstance(struct, tuple) or instruction.field_index >= len(struct):
                raise IRExecutionError("IR struct_get requires a valid struct value")
            frame.values[instruction.result] = struct[instruction.field_index]
            return False, None, None

        if isinstance(instruction, IRStructSet):
            struct = self._value(instruction.struct, frame)
            if not isinstance(struct, tuple) or instruction.field_index >= len(struct):
                raise IRExecutionError("IR struct_set requires a valid struct value")
            fields = list(struct)
            fields[instruction.field_index] = self._value(instruction.value, frame)
            frame.values[instruction.result] = tuple(fields)
            return False, None, None

        if isinstance(instruction, IRMethodResultNew):
            receiver = self._value(instruction.receiver, frame)
            value = None if instruction.value is None else self._value(instruction.value, frame)
            frame.values[instruction.result] = (receiver, value)
            return False, None, None

        if isinstance(instruction, IRMethodResultReceiver):
            pair = self._value(instruction.method_result, frame)
            frame.values[instruction.result] = pair[0]
            return False, None, None

        if isinstance(instruction, IRMethodResultValue):
            pair = self._value(instruction.method_result, frame)
            frame.values[instruction.result] = pair[1]
            return False, None, None

        if isinstance(instruction, IRArrayNew):
            frame.values[instruction.result] = CollectionObject(
                "Array",
                instruction.result.type.element,
                (self._value(element, frame) for element in instruction.elements),
            )
            return False, None, None

        if isinstance(instruction, IRListNew):
            frame.values[instruction.result] = CollectionObject(
                "List",
                instruction.result.type.element,
                (self._value(element, frame) for element in instruction.elements),
            )
            return False, None, None

        if isinstance(instruction, IRArrayCopy):
            array = self._value(instruction.array, frame)
            if not isinstance(array, list):
                raise IRExecutionError("IR array_copy requires an array value")
            frame.values[instruction.result] = (
                array.logical_copy()
                if isinstance(array, CollectionObject)
                else CollectionObject("Array", instruction.result.type.element, array)
            )
            return False, None, None

        if isinstance(instruction, IRListCopy):
            list_value = self._value(instruction.list_value, frame)
            if not isinstance(list_value, list):
                raise IRExecutionError("IR list_copy requires a list value")
            frame.values[instruction.result] = (
                list_value.logical_copy()
                if isinstance(list_value, CollectionObject)
                else CollectionObject("List", instruction.result.type.element, list_value)
            )
            return False, None, None

        if isinstance(instruction, IRListContains):
            list_value = self._value(instruction.list_value, frame)
            if not isinstance(list_value, list):
                raise IRExecutionError("IR list_contains requires a list value")
            value = self._value(instruction.value, frame)
            frame.values[instruction.result] = self._list_index_of(
                list_value, value, instruction.value.type
            ) >= 0
            return False, None, None

        if isinstance(instruction, IRListIndexOf):
            list_value = self._value(instruction.list_value, frame)
            if not isinstance(list_value, list):
                raise IRExecutionError("IR list_index_of requires a list value")
            value = self._value(instruction.value, frame)
            try:
                frame.values[instruction.result] = checked_list_index_to_int(
                    self._list_index_of(list_value, value, instruction.value.type)
                )
            except OverflowError as error:
                raise IRExecutionError(str(error)) from error
            return False, None, None

        if isinstance(instruction, IRListClear):
            list_value = self._value(instruction.list_value, frame)
            if not isinstance(list_value, list):
                raise IRExecutionError("IR list_clear requires a list value")
            list_value.clear()
            return False, None, None

        if isinstance(instruction, IRListPush):
            list_value = self._value(instruction.list_value, frame)
            if not isinstance(list_value, list):
                raise IRExecutionError("IR list_push requires a list value")
            list_value.append(self._value(instruction.value, frame))
            return False, None, None

        if isinstance(instruction, IRListInsert):
            list_value = self._value(instruction.list_value, frame)
            if not isinstance(list_value, list):
                raise IRExecutionError("IR list_insert requires a list value")
            index = self._value(instruction.index, frame)
            if not isinstance(index, int) or isinstance(index, bool):
                raise IRExecutionError("IR list_insert requires an int index")
            if index < 0 or index > len(list_value):
                raise IRExecutionError(
                    f"insert() index must be between 0 and length(xs); got {index} "
                    f"for List of length {len(list_value)}"
                )
            list_value.insert(index, self._value(instruction.value, frame))
            return False, None, None

        if isinstance(instruction, IRListPop):
            list_value = self._value(instruction.list_value, frame)
            if not isinstance(list_value, list):
                raise IRExecutionError("IR list_pop requires a list value")
            if not list_value:
                raise IRExecutionError("pop() cannot be used on an empty List")
            frame.values[instruction.result] = list_value.pop()
            return False, None, None

        if isinstance(instruction, IRListRemoveAt):
            list_value = self._value(instruction.list_value, frame)
            if not isinstance(list_value, list):
                raise IRExecutionError("IR list_remove_at requires a list value")
            index = self._value(instruction.index, frame)
            if not isinstance(index, int) or isinstance(index, bool):
                raise IRExecutionError("IR list_remove_at requires an int index")
            if index < 0 or index >= len(list_value):
                raise IRExecutionError(
                    f"index {index} out of bounds for List of length {len(list_value)}"
                )
            frame.values[instruction.result] = list_value.pop(index)
            return False, None, None

        if isinstance(instruction, IRListReverse):
            list_value = self._value(instruction.list_value, frame)
            if not isinstance(list_value, list):
                raise IRExecutionError("IR list_reverse requires a list value")
            list.reverse(list_value)
            return False, None, None

        if isinstance(instruction, IRSequenceSort):
            sequence = self._value(instruction.sequence, frame)
            if not isinstance(sequence, list):
                raise IRExecutionError("IR sequence_sort requires a sequence value")
            element_type = instruction.sequence.type.element
            if isinstance(element_type, DoubleType):
                sequence.sort(key=lambda value: (math.isnan(value), 0.0 if math.isnan(value) else value))
            elif isinstance(element_type, StringType):
                sequence.sort(key=lambda value: value.encode("utf-8"))
            elif isinstance(element_type, IntType):
                sequence.sort()
            else:
                raise IRExecutionError(f"IR sequence_sort does not support {element_type}")
            return False, None, None

        if isinstance(instruction, IRVectorNew):
            frame.values[instruction.result] = [
                self._value(element, frame) for element in instruction.elements
            ]
            return False, None, None

        if isinstance(instruction, IRMatrixNew):
            frame.values[instruction.result] = [
                self._value(element, frame) for element in instruction.elements
            ]
            return False, None, None

        if isinstance(instruction, IRVectorAdd):
            self._execute_vector_binary(instruction, frame, "add")
            return False, None, None

        if isinstance(instruction, IRVectorSub):
            self._execute_vector_binary(instruction, frame, "sub")
            return False, None, None

        if isinstance(instruction, IRVectorScale):
            self._execute_vector_scale(instruction, frame)
            return False, None, None

        if isinstance(instruction, IRVectorDot):
            self._execute_vector_dot(instruction, frame)
            return False, None, None

        if isinstance(instruction, IROuterProduct):
            self._execute_outer_product(instruction, frame)
            return False, None, None

        if isinstance(instruction, IRMatrixAdd):
            self._execute_matrix_binary(instruction, frame, "add")
            return False, None, None

        if isinstance(instruction, IRMatrixSub):
            self._execute_matrix_binary(instruction, frame, "sub")
            return False, None, None

        if isinstance(instruction, IRMatrixScale):
            self._execute_matrix_scale(instruction, frame)
            return False, None, None

        if isinstance(instruction, IRMatrixMatMul):
            self._execute_matrix_matmul(instruction, frame)
            return False, None, None

        if isinstance(instruction, IRMatrixVectorMul):
            self._execute_matrix_vector_mul(instruction, frame)
            return False, None, None

        if isinstance(instruction, IRVectorMatrixMul):
            self._execute_vector_matrix_mul(instruction, frame)
            return False, None, None

        if isinstance(instruction, IRArrayGet):
            array = self._value(instruction.array, frame)
            index = self._value(instruction.index, frame)
            self._check_array_index(array, index)
            frame.values[instruction.result] = array[index]
            return False, None, None

        if isinstance(instruction, IRArraySlice):
            array = self._value(instruction.array, frame)
            start = self._value(instruction.start, frame)
            end = self._value(instruction.end, frame)
            if not isinstance(array, list):
                raise IRExecutionError("IR array slicing requires an array value")
            if not isinstance(start, int) or isinstance(start, bool) or not isinstance(end, int) or isinstance(end, bool):
                raise IRExecutionError("IR array slice bounds must be int")
            if start > end:
                raise IRExecutionError("Aether panic: Array slice start is greater than end")
            if start < 0 or end < 0 or start > len(array) or end > len(array):
                raise IRExecutionError("Aether panic: Array slice index out of bounds")
            frame.values[instruction.result] = (
                array.logical_slice(start, end)
                if isinstance(array, CollectionObject)
                else CollectionObject("Array", instruction.result.type.element, array[start:end])
            )
            return False, None, None

        if isinstance(instruction, IRListSlice):
            list_value = self._value(instruction.list_value, frame)
            start = self._value(instruction.start, frame)
            end = self._value(instruction.end, frame)
            if not isinstance(list_value, list):
                raise IRExecutionError("IR list slicing requires a list value")
            if not isinstance(start, int) or isinstance(start, bool) or not isinstance(end, int) or isinstance(end, bool):
                raise IRExecutionError("IR list slice bounds must be int")
            if start > end:
                raise IRExecutionError("Aether panic: List slice start is greater than end")
            if start < 0 or end < 0 or start > len(list_value) or end > len(list_value):
                raise IRExecutionError("Aether panic: List slice index out of bounds")
            frame.values[instruction.result] = (
                list_value.logical_slice(start, end)
                if isinstance(list_value, CollectionObject)
                else CollectionObject("List", instruction.result.type.element, list_value[start:end])
            )
            return False, None, None

        if isinstance(instruction, IRListGet):
            list_value = self._value(instruction.list_value, frame)
            index = self._value(instruction.index, frame)
            self._check_list_index(list_value, index)
            frame.values[instruction.result] = list_value[index]
            return False, None, None

        if isinstance(instruction, IRListSet):
            list_value = self._value(instruction.list_value, frame)
            index = self._value(instruction.index, frame)
            self._check_list_index(list_value, index)
            list_value[index] = self._value(instruction.value, frame)
            return False, None, None

        if isinstance(instruction, IRVectorGet):
            vector = self._value(instruction.vector, frame)
            index = self._value(instruction.index, frame)
            offset = self._check_vector_index(vector, index)
            frame.values[instruction.result] = vector[offset]
            return False, None, None

        if isinstance(instruction, IRMatrixGet):
            matrix = self._value(instruction.matrix, frame)
            row = self._value(instruction.row, frame)
            column = self._value(instruction.column, frame)
            offset = self._check_matrix_index(matrix, row, column, instruction.cols)
            frame.values[instruction.result] = matrix[offset]
            return False, None, None

        if isinstance(instruction, IRVectorLength):
            vector = self._value(instruction.vector, frame)
            if not isinstance(vector, list):
                raise IRExecutionError("IR vector_length requires a vector value")
            frame.values[instruction.result] = len(vector)
            return False, None, None

        if isinstance(instruction, IRMatrixRows):
            frame.values[instruction.result] = instruction.rows
            return False, None, None

        if isinstance(instruction, IRMatrixColumns):
            frame.values[instruction.result] = instruction.columns
            return False, None, None

        if isinstance(instruction, IRArraySet):
            array = self._value(instruction.array, frame)
            index = self._value(instruction.index, frame)
            value = self._value(instruction.value, frame)
            self._check_array_index(array, index)
            array[index] = value
            return False, None, None

        if isinstance(instruction, IRVectorSet):
            vector = self._value(instruction.vector, frame)
            index = self._value(instruction.index, frame)
            value = self._value(instruction.value, frame)
            offset = self._check_vector_index(vector, index)
            vector[offset] = value
            return False, None, None

        if isinstance(instruction, IRMatrixSet):
            matrix = self._value(instruction.matrix, frame)
            row = self._value(instruction.row, frame)
            column = self._value(instruction.column, frame)
            value = self._value(instruction.value, frame)
            offset = self._check_matrix_index(matrix, row, column, instruction.cols)
            matrix[offset] = value
            return False, None, None

        if isinstance(instruction, IRArrayLength):
            array = self._value(instruction.array, frame)
            if not isinstance(array, list):
                raise IRExecutionError("IR array_length requires an array value")
            try:
                frame.values[instruction.result] = checked_array_length_to_int(len(array))
            except OverflowError as error:
                raise IRExecutionError(str(error)) from error
            return False, None, None

        if isinstance(instruction, IRListLength):
            list_value = self._value(instruction.list_value, frame)
            if not isinstance(list_value, list):
                raise IRExecutionError("IR list_length requires a list value")
            try:
                frame.values[instruction.result] = checked_list_length_to_int(len(list_value))
            except OverflowError as error:
                raise IRExecutionError(str(error)) from error
            return False, None, None

        if isinstance(instruction, IRListIsEmpty):
            list_value = self._value(instruction.list_value, frame)
            if not isinstance(list_value, list):
                raise IRExecutionError("IR list_is_empty requires a list value")
            frame.values[instruction.result] = len(list_value) == 0
            return False, None, None

        if isinstance(instruction, IRBranch):
            condition = self._value(instruction.condition, frame)
            if not isinstance(condition, bool):
                raise IRExecutionError("IR branch condition must be bool")
            return False, None, instruction.true_target if condition else instruction.false_target

        if isinstance(instruction, IRJump):
            return False, None, instruction.target

        if isinstance(instruction, IRReturn):
            if instruction.value is None:
                return True, None, None
            return True, self._value(instruction.value, frame), None

        raise IRExecutionError(f"Unsupported IR instruction {type(instruction).__name__}")

    def _lifecycle_value(self, value: IRValue, frame: _Frame) -> Any:
        if isinstance(value, IRStorage):
            if value not in frame.slots:
                raise IRExecutionError(
                    f"Lifecycle source '%{value.name}' is not alive"
                )
            return frame.slots[value]
        return self._value(value, frame)

    def _default_lifecycle_value(self, type_: object) -> Any:
        if isinstance(type_, StructType):
            definition = self._structs.get(type_.name)
            if definition is None:
                raise IRExecutionError(
                    f"Cannot default-initialize unknown struct '{type_.name}'"
                )
            return tuple(
                self._default_lifecycle_value(field_type)
                for _name, field_type in definition.fields
            )
        if isinstance(type_, ArrayType):
            return CollectionObject("Array", type_.element)
        if isinstance(type_, ListType):
            return CollectionObject("List", type_.element)
        if isinstance(type_, (VectorType, MatrixType)):
            return []
        if isinstance(type_, StringType):
            return ""
        if isinstance(type_, (DoubleType, FloatType)):
            return 0.0
        if isinstance(type_, BoolType):
            return False
        if isinstance(type_, EnumType):
            if not type_.variants:
                raise IRExecutionError(f"Enum '{type_.name}' has no default value")
            return IREnumConstant(type_.name, type_.variants[0], 0, 0)
        return 0

    def _execute_vector_binary(
        self,
        instruction: IRVectorAdd | IRVectorSub,
        frame: _Frame,
        operator: str,
    ) -> None:
        left = self._value(instruction.left, frame)
        right = self._value(instruction.right, frame)
        if not isinstance(left, list) or not isinstance(right, list):
            raise IRExecutionError(f"IR vector {operator} requires vector values")
        if len(left) != instruction.length or len(right) != instruction.length:
            raise IRExecutionError(f"IR vector {operator} operands must match instruction length")
        frame.values[instruction.result] = [
            self._binary(operator, left_value, right_value)
            for left_value, right_value in zip(left, right)
        ]

    def _execute_vector_scale(
        self,
        instruction: IRVectorScale,
        frame: _Frame,
    ) -> None:
        vector = self._value(instruction.vector, frame)
        scalar = self._value(instruction.scalar, frame)
        if not isinstance(vector, list):
            raise IRExecutionError("IR vector scale requires a vector value")
        if len(vector) != instruction.length:
            raise IRExecutionError("IR vector scale operand must match instruction length")
        frame.values[instruction.result] = [
            self._binary("mul", value, scalar)
            for value in vector
        ]

    def _execute_vector_dot(
        self,
        instruction: IRVectorDot,
        frame: _Frame,
    ) -> None:
        left = self._value(instruction.left, frame)
        right = self._value(instruction.right, frame)
        if not isinstance(left, list) or not isinstance(right, list):
            raise IRExecutionError("IR vector dot requires vector values")
        if len(left) != instruction.length or len(right) != instruction.length:
            raise IRExecutionError("IR vector dot operands must match instruction length")
        total = 0.0 if isinstance(instruction.result.type, DoubleType) else 0
        for left_value, right_value in zip(left, right):
            total = self._binary("add", total, self._binary("mul", left_value, right_value))
        frame.values[instruction.result] = total

    def _execute_outer_product(
        self,
        instruction: IROuterProduct,
        frame: _Frame,
    ) -> None:
        column = self._value(instruction.column, frame)
        row = self._value(instruction.row, frame)
        if not isinstance(column, list) or not isinstance(row, list):
            raise IRExecutionError("IR outer product requires vector values")
        if len(column) != instruction.rows or len(row) != instruction.cols:
            raise IRExecutionError("IR outer product operands must match instruction dimensions")

        result: list[Any] = []
        for row_index in range(instruction.rows):
            for col_index in range(instruction.cols):
                result.append(self._binary("mul", column[row_index], row[col_index]))
        frame.values[instruction.result] = result

    def _execute_matrix_binary(
        self,
        instruction: IRMatrixAdd | IRMatrixSub,
        frame: _Frame,
        operator: str,
    ) -> None:
        left = self._value(instruction.left, frame)
        right = self._value(instruction.right, frame)
        if not isinstance(left, list) or not isinstance(right, list):
            raise IRExecutionError(f"IR matrix {operator} requires matrix values")
        element_count = instruction.rows * instruction.cols
        if len(left) != element_count or len(right) != element_count:
            raise IRExecutionError(f"IR matrix {operator} operands must match instruction dimensions")
        frame.values[instruction.result] = [
            self._binary(operator, left_value, right_value)
            for left_value, right_value in zip(left, right)
        ]

    def _execute_matrix_scale(
        self,
        instruction: IRMatrixScale,
        frame: _Frame,
    ) -> None:
        matrix = self._value(instruction.matrix, frame)
        scalar = self._value(instruction.scalar, frame)
        if not isinstance(matrix, list):
            raise IRExecutionError("IR matrix scale requires a matrix value")
        element_count = instruction.rows * instruction.cols
        if len(matrix) != element_count:
            raise IRExecutionError("IR matrix scale operand must match instruction dimensions")
        frame.values[instruction.result] = [
            self._binary("mul", value, scalar)
            for value in matrix
        ]

    def _execute_matrix_matmul(
        self,
        instruction: IRMatrixMatMul,
        frame: _Frame,
    ) -> None:
        left = self._value(instruction.left, frame)
        right = self._value(instruction.right, frame)
        if not isinstance(left, list) or not isinstance(right, list):
            raise IRExecutionError("IR matrix matmul requires matrix values")
        if len(left) != instruction.rows * instruction.inner:
            raise IRExecutionError("IR matrix matmul left operand must match instruction dimensions")
        if len(right) != instruction.inner * instruction.cols:
            raise IRExecutionError("IR matrix matmul right operand must match instruction dimensions")

        result: list[Any] = []
        for row in range(instruction.rows):
            for col in range(instruction.cols):
                total = 0.0 if isinstance(instruction.result.type, DoubleType) else 0
                for inner in range(instruction.inner):
                    left_value = left[row * instruction.inner + inner]
                    right_value = right[inner * instruction.cols + col]
                    total = self._binary("add", total, self._binary("mul", left_value, right_value))
                result.append(total)
        frame.values[instruction.result] = result

    def _execute_matrix_vector_mul(
        self,
        instruction: IRMatrixVectorMul,
        frame: _Frame,
    ) -> None:
        matrix = self._value(instruction.matrix, frame)
        vector = self._value(instruction.vector, frame)
        if not isinstance(matrix, list) or not isinstance(vector, list):
            raise IRExecutionError("IR matrix vector mul requires matrix and vector values")
        if len(matrix) != instruction.rows * instruction.inner:
            raise IRExecutionError("IR matrix vector mul matrix operand must match instruction dimensions")
        if len(vector) != instruction.inner:
            raise IRExecutionError("IR matrix vector mul vector operand must match instruction dimensions")

        result: list[Any] = []
        for row in range(instruction.rows):
            total = 0.0 if isinstance(instruction.result.type.element, DoubleType) else 0
            for inner in range(instruction.inner):
                matrix_value = matrix[row * instruction.inner + inner]
                vector_value = vector[inner]
                total = self._binary("add", total, self._binary("mul", matrix_value, vector_value))
            result.append(total)
        frame.values[instruction.result] = result

    def _execute_vector_matrix_mul(
        self,
        instruction: IRVectorMatrixMul,
        frame: _Frame,
    ) -> None:
        vector = self._value(instruction.vector, frame)
        matrix = self._value(instruction.matrix, frame)
        if not isinstance(vector, list) or not isinstance(matrix, list):
            raise IRExecutionError("IR vector matrix mul requires vector and matrix values")
        if len(vector) != instruction.rows:
            raise IRExecutionError("IR vector matrix mul vector operand must match instruction dimensions")
        if len(matrix) != instruction.rows * instruction.cols:
            raise IRExecutionError("IR vector matrix mul matrix operand must match instruction dimensions")

        result: list[Any] = []
        for col in range(instruction.cols):
            total = 0.0 if isinstance(instruction.result.type.element, DoubleType) else 0
            for row in range(instruction.rows):
                vector_value = vector[row]
                matrix_value = matrix[row * instruction.cols + col]
                total = self._binary("add", total, self._binary("mul", vector_value, matrix_value))
            result.append(total)
        frame.values[instruction.result] = result

    @staticmethod
    def _target_block(
        function: IRFunction,
        blocks: dict[str, IRBasicBlock],
        target: str,
    ) -> IRBasicBlock:
        block = blocks.get(target)
        if block is None:
            raise IRExecutionError(
                f"IR target block '{target}' does not exist in function '{function.name}'"
            )
        return block

    @staticmethod
    def _value(value: IRValue, frame: _Frame) -> Any:
        if value not in frame.values:
            raise IRExecutionError(f"IR value '%{value.name}' is not initialized")
        return frame.values[value]

    def _list_index_of(self, list_value: list[Any], value: Any, element_type: object) -> int:
        for index, element in enumerate(list_value):
            if ir_values_equal(element_type, element, value, self._structs):
                return index
        return -1

    @staticmethod
    def _binary(
        operator: str,
        left: Any,
        right: Any,
        *,
        checked_int: bool = False,
    ) -> Any:
        if checked_int:
            try:
                return checked_int_binary(operator, left, right)
            except (OverflowError, ZeroDivisionError) as exc:
                raise IRExecutionError(str(exc)) from exc
        if operator == "add":
            return left + right
        if operator == "sub":
            return left - right
        if operator == "mul":
            return left * right
        if operator == "div":
            return ieee_divide(float(left), float(right))
        if operator in {"mod", "rem"}:
            if right == 0:
                raise IRExecutionError("IR division by zero")
            return left - trunc(left / right) * right
        IRInterpreter._unsupported_binary(operator)

    @staticmethod
    def _compare(operator: str, left: Any, right: Any) -> bool:
        if operator == "lt":
            return left < right
        if operator == "le":
            return left <= right
        if operator == "gt":
            return left > right
        if operator == "ge":
            return left >= right
        if operator == "eq":
            return left == right
        if operator == "ne":
            return left != right
        IRInterpreter._unsupported_compare(operator)

    @staticmethod
    def _cast(value: Any, target_type: object) -> Any:
        if isinstance(target_type, (FloatType, DoubleType)):
            return float(value)
        if isinstance(target_type, IntType):
            return trunc(value)
        raise IRExecutionError(f"IR cast to '{target_type}' is not supported")

    @staticmethod
    def _aether_scalar_type(type_: object) -> str:
        if isinstance(type_, IntType):
            return "int"
        if isinstance(type_, FloatType):
            return "float"
        if isinstance(type_, DoubleType):
            return "double"
        raise IRExecutionError(f"IR scalar builtin does not support argument type '{type_}'")

    @staticmethod
    def _check_array_index(array: Any, index: Any) -> None:
        if not isinstance(array, list):
            raise IRExecutionError("IR array indexing requires an array value")
        if type(index) is not int:
            raise IRExecutionError("IR array index must be int")
        if index < 0 or index >= len(array):
            raise IRExecutionError(
                f"IR array index {index} out of bounds for length {len(array)}"
            )

    @staticmethod
    def _check_list_index(list_value: Any, index: Any) -> None:
        if not isinstance(list_value, list):
            raise IRExecutionError("IR list indexing requires a list value")
        if type(index) is not int:
            raise IRExecutionError("IR List index must be int")
        if index < 0 or index >= len(list_value):
            raise IRExecutionError(
                f"List index {index} out of bounds for length {len(list_value)}"
            )

    @staticmethod
    def _check_vector_index(vector: Any, index: Any) -> int:
        if not isinstance(vector, list):
            raise IRExecutionError("IR vector indexing requires a vector value")
        if type(index) is not int:
            raise IRExecutionError("IR vector index must be int")
        try:
            return checked_vector_offset(index, len(vector))
        except IndexError as error:
            raise IRExecutionError(VECTOR_INDEX_OUT_OF_BOUNDS) from error

    @staticmethod
    def _check_matrix_index(matrix: Any, row: Any, column: Any, cols: int) -> int:
        if not isinstance(matrix, list):
            raise IRExecutionError("IR matrix indexing requires a matrix value")
        if type(row) is not int or type(column) is not int:
            raise IRExecutionError("IR matrix indices must be int")
        try:
            return checked_matrix_offset(row, column, len(matrix), cols)
        except IndexError as error:
            raise IRExecutionError(MATRIX_INDEX_OUT_OF_BOUNDS) from error
        except ValueError as error:
            raise IRExecutionError(f"IR matrix indexing has {error}") from error

    @staticmethod
    def _unsupported_binary(operator: str) -> NoReturn:
        raise IRExecutionError(f"IR binary operation '{operator}' is not supported")

    @staticmethod
    def _unsupported_compare(operator: str) -> NoReturn:
        raise IRExecutionError(f"IR compare operation '{operator}' is not supported")
