from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Callable

from aether.ir.types import ArrayType, BoolType, DoubleType, IntType, ListType, MatrixType, StringType, VectorType, VoidType
from aether.ssa.model import (
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
    SSACompareOp,
    SSAConst,
    SSAFunction,
    SSAInstruction,
    SSAJump,
    SSAListGet,
    SSAListCopy,
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
    SSAParameter,
    SSAPrint,
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

from .types import LLVMBackendError, llvm_type
from .array_runtime import LLVMArrayRuntime
from .io_runtime import LLVMRuntimeIO
from .integer_runtime import LLVMIntegerRuntime
from .list_runtime import (
    LLVMListRuntime,
    list_contains_helper_name,
    list_index_of_helper_name,
)
from .matrix_runtime import LLVMMatrixRuntime
from .runtime import sequence_sort_helper_name
from .runtime_common import LLVMRuntimeCommon, aggregate_helper_suffix
from .vector_runtime import LLVMVectorRuntime


@dataclass(frozen=True)
class _StringGlobal:
    name: str
    size: int
    initializer: str


class LLVMPrinter:
    """Emit textual LLVM IR for the first minimal SSA subset."""

    _INT_BINARY_OPERATORS = {
        "add": "add",
        "sub": "sub",
        "mul": "mul",
        "div": "sdiv",
        "mod": "srem",
        "rem": "srem",
    }
    _DOUBLE_BINARY_OPERATORS = {
        "add": "fadd",
        "sub": "fsub",
        "mul": "fmul",
        "div": "fdiv",
    }
    _INT_COMPARE_OPERATORS = {
        "lt": "slt",
        "le": "sle",
        "gt": "sgt",
        "ge": "sge",
        "eq": "eq",
        "ne": "ne",
    }
    _DOUBLE_COMPARE_OPERATORS = {
        "lt": "olt",
        "le": "ole",
        "gt": "ogt",
        "ge": "oge",
        "eq": "oeq",
        "ne": "one",
    }
    _IDENTIFIER_RE = re.compile(r"^[A-Za-z_$._][A-Za-z0-9_$._-]*$")
    _LIST_STRUCT_TYPE = "%AetherList"

    def print_module(self, module: SSAModule) -> str:
        self._string_globals_by_value: dict[str, _StringGlobal] = {}
        self._next_string_global = 0
        self._uses_array_type = False
        self._uses_array_allocation = False
        self._uses_array_indexing = False
        self._uses_array_slicing = False
        self._uses_array_length_conversion = False
        self._uses_vector_indexing = False
        self._uses_matrix_indexing = False
        self._vector_equality_types: set[object] = set()
        self._matrix_equality_types: set[object] = set()
        self._vector_print_types: set[object] = set()
        self._matrix_print_types: set[object] = set()
        self._uses_list_type = False
        self._uses_list_allocation = False
        self._uses_list_copy = False
        self._uses_list_push = False
        self._uses_list_insert = False
        self._uses_list_pop = False
        self._uses_list_remove_at = False
        self._uses_list_reverse = False
        self._uses_list_indexing = False
        self._uses_list_length_conversion = False
        self._sequence_sort_types: set[object] = set()
        self._list_contains_types: set[object] = set()
        self._list_index_of_types: set[object] = set()
        self._uses_print = False
        self._checked_int_operators: set[str] = set()

        functions = [self._print_function(function) for function in module.functions]
        globals_ = [
            self._print_string_global(global_)
            for global_ in self._string_globals_by_value.values()
        ]
        array_runtime = LLVMArrayRuntime(
            uses_type=self._uses_array_type,
            uses_allocation=self._uses_array_allocation,
            uses_indexing=self._uses_array_indexing,
            uses_slicing=self._uses_array_slicing,
            uses_length_conversion=self._uses_array_length_conversion,
        )
        list_runtime = LLVMListRuntime(
            _uses_list_type=self._uses_list_type,
            _uses_list_allocation=self._uses_list_allocation,
            _uses_list_copy=self._uses_list_copy,
            _uses_list_push=self._uses_list_push,
            _uses_list_insert=self._uses_list_insert,
            _uses_list_pop=self._uses_list_pop,
            _uses_list_remove_at=self._uses_list_remove_at,
            _uses_list_reverse=self._uses_list_reverse,
            _uses_list_indexing=self._uses_list_indexing,
            _uses_list_length_conversion=self._uses_list_length_conversion,
            _sequence_sort_types=frozenset(self._sequence_sort_types),
            _list_contains_types=frozenset(self._list_contains_types),
            _list_index_of_types=frozenset(self._list_index_of_types),
        )
        uses_list_growth = self._uses_list_push or self._uses_list_insert
        uses_allocation = bool(
            self._uses_array_allocation
            or self._uses_list_allocation
            or self._uses_array_slicing
            or uses_list_growth
            or self._sequence_sort_types
        )
        common_runtime = LLVMRuntimeCommon(
            uses_allocation=uses_allocation,
            uses_checked_allocation_size=bool(
                self._uses_array_allocation
                or self._uses_list_allocation
                or self._uses_array_slicing
                or self._sequence_sort_types
            ),
            uses_panic=bool(
                uses_allocation
                or self._checked_int_operators
                or self._uses_array_indexing
                or self._uses_array_slicing
                or self._uses_list_indexing
                or self._uses_list_pop
                or self._uses_list_remove_at
                or self._uses_array_length_conversion
                or self._uses_list_length_conversion
                or self._list_index_of_types
                or self._uses_vector_indexing
                or self._uses_matrix_indexing
            ),
            uses_free_and_memcpy=bool(self._sequence_sort_types or uses_list_growth or self._uses_array_slicing),
            uses_memmove=self._uses_list_insert or self._uses_list_remove_at,
            sequence_sort_types=frozenset(self._sequence_sort_types),
        )
        runtime = list_runtime.declarations(common_runtime, array_runtime)
        LLVMVectorRuntime(
            self._uses_vector_indexing,
            frozenset(self._vector_equality_types),
            frozenset(self._vector_print_types),
        ).append(runtime, common_runtime)
        LLVMMatrixRuntime(
            self._uses_matrix_indexing,
            frozenset(self._matrix_equality_types),
            frozenset(self._matrix_print_types),
        ).append(runtime, common_runtime)
        LLVMIntegerRuntime(frozenset(self._checked_int_operators)).append(runtime, common_runtime)
        LLVMRuntimeIO(enabled=self._uses_print).append(runtime)
        sections = runtime + globals_ + functions
        return "\n\n".join(sections)

    def _print_function(self, function: SSAFunction) -> str:
        self._constants: dict[str, str] = {}
        self._values: dict[str, str] = {
            self._key(parameter): self._parameter_name(parameter)
            for parameter in function.parameters
        }
        self._next_temp = 0
        self._next_synthetic_temp = 0
        self._collect_function_values(function)

        return_type = llvm_type(function.return_type)
        parameters = ", ".join(
            f"{llvm_type(parameter.type)} {self._parameter_name(parameter)}"
            for parameter in function.parameters
        )
        lines = [f"define {return_type} {self._global_name(function.name)}({parameters}) {{"]

        for block in function.blocks:
            lines.extend(self._print_block(block, function))

        lines.append("}")
        return "\n".join(lines)

    def _collect_function_values(self, function: SSAFunction) -> None:
        for block in function.blocks:
            for instruction in block.instructions:
                if isinstance(instruction, SSAConst):
                    self._record_const(instruction)
                    continue

                result = self._instruction_result(instruction)
                if result is not None:
                    self._reserve_temp(result)

    def _print_block(self, block: SSABasicBlock, function: SSAFunction) -> list[str]:
        lines = [self._label_definition(block.name)]
        for instruction in block.instructions:
            emitted = self._print_instruction(instruction, function)
            if emitted is not None:
                lines.append(f"  {emitted}")
        return lines

    def _print_instruction(
        self,
        instruction: SSAInstruction,
        function: SSAFunction,
    ) -> str | None:
        if isinstance(instruction, SSAConst):
            self._record_const(instruction)
            return None
        if isinstance(instruction, SSABinaryOp):
            return self._print_binary_op(instruction)
        if isinstance(instruction, SSACompareOp):
            return self._print_compare_op(instruction)
        if isinstance(instruction, SSACast):
            return self._print_cast(instruction)
        if isinstance(instruction, SSAReturn):
            return self._print_return(instruction, function)
        if isinstance(instruction, SSAPhi):
            return self._print_phi(instruction)
        if isinstance(instruction, SSABranch):
            return self._print_branch(instruction)
        if isinstance(instruction, SSAJump):
            return self._print_jump(instruction)
        if isinstance(instruction, SSACall):
            return self._print_call(instruction)
        if isinstance(instruction, SSAPrint):
            return self._print_print(instruction)
        if isinstance(instruction, SSAArrayNew):
            return self._print_array_new(instruction)
        if isinstance(instruction, SSAListNew):
            return self._print_list_new(instruction)
        if isinstance(instruction, SSAListCopy):
            return self._print_list_copy(instruction)
        if isinstance(instruction, SSAListContains):
            return self._print_list_contains(instruction)
        if isinstance(instruction, SSAListIndexOf):
            return self._print_list_index_of(instruction)
        if isinstance(instruction, SSAListClear):
            return self._print_list_clear(instruction)
        if isinstance(instruction, SSAListPush):
            return "\n  ".join(self._print_list_push(instruction))
        if isinstance(instruction, SSAListInsert):
            return "\n  ".join(self._print_list_insert(instruction))
        if isinstance(instruction, SSAListPop):
            return "\n  ".join(self._print_list_pop(instruction))
        if isinstance(instruction, SSAListRemoveAt):
            return "\n  ".join(self._print_list_remove_at(instruction))
        if isinstance(instruction, SSAListReverse):
            return self._print_list_reverse(instruction)
        if isinstance(instruction, SSASequenceSort):
            return self._print_sequence_sort(instruction)
        if isinstance(instruction, SSAVectorNew):
            return self._print_vector_new(instruction)
        if isinstance(instruction, SSAMatrixNew):
            return self._print_matrix_new(instruction)
        if isinstance(instruction, SSAVectorAdd):
            return "\n  ".join(self._print_vector_add(instruction))
        if isinstance(instruction, SSAVectorSub):
            return "\n  ".join(self._print_vector_sub(instruction))
        if isinstance(instruction, SSAVectorScale):
            return "\n  ".join(self._print_vector_scale(instruction))
        if isinstance(instruction, SSAVectorDot):
            return "\n".join(self._print_vector_dot(instruction))
        if isinstance(instruction, SSAOuterProduct):
            return "\n".join(self._print_outer_product(instruction))
        if isinstance(instruction, SSAMatrixAdd):
            return "\n  ".join(self._print_matrix_add(instruction))
        if isinstance(instruction, SSAMatrixSub):
            return "\n  ".join(self._print_matrix_sub(instruction))
        if isinstance(instruction, SSAMatrixScale):
            return "\n  ".join(self._print_matrix_scale(instruction))
        if isinstance(instruction, SSAMatrixMatMul):
            return "\n  ".join(self._print_matrix_matmul(instruction))
        if isinstance(instruction, SSAMatrixVectorMul):
            return "\n".join(self._print_matrix_vector_mul(instruction))
        if isinstance(instruction, SSAVectorMatrixMul):
            return "\n".join(self._print_vector_matrix_mul(instruction))
        if isinstance(instruction, SSAArrayGet):
            return "\n  ".join(self._print_array_get(instruction))
        if isinstance(instruction, SSAArraySlice):
            return self._print_array_slice(instruction)
        if isinstance(instruction, SSAListGet):
            return "\n  ".join(self._print_list_get(instruction))
        if isinstance(instruction, SSAVectorGet):
            return "\n  ".join(self._print_vector_get(instruction))
        if isinstance(instruction, SSAMatrixGet):
            return "\n  ".join(self._print_matrix_get(instruction))
        if isinstance(instruction, SSAVectorLength):
            return "\n  ".join(self._print_vector_length(instruction))
        if isinstance(instruction, SSAMatrixRows):
            return self._print_matrix_rows(instruction)
        if isinstance(instruction, SSAMatrixColumns):
            return self._print_matrix_columns(instruction)
        if isinstance(instruction, SSAArraySet):
            return "\n  ".join(self._print_array_set(instruction))
        if isinstance(instruction, SSAListSet):
            return "\n  ".join(self._print_list_set(instruction))
        if isinstance(instruction, SSAVectorSet):
            return "\n  ".join(self._print_vector_set(instruction))
        if isinstance(instruction, SSAMatrixSet):
            return "\n  ".join(self._print_matrix_set(instruction))
        if isinstance(instruction, SSAArrayLength):
            return "\n  ".join(self._print_array_length(instruction))
        if isinstance(instruction, SSAListLength):
            return "\n  ".join(self._print_list_length(instruction))
        if isinstance(instruction, SSAListIsEmpty):
            return "\n  ".join(self._print_list_is_empty(instruction))
        self._unsupported(type(instruction).__name__)

    def _record_const(self, instruction: SSAConst) -> None:
        llvm_type(instruction.result.type)
        self._constants[self._key(instruction.result)] = self._literal(
            instruction.value,
            instruction.result,
        )

    @staticmethod
    def _instruction_result(instruction: SSAInstruction) -> SSAValue | None:
        if isinstance(instruction, SSABinaryOp | SSACompareOp | SSACast | SSAPhi):
            return instruction.result
        if isinstance(instruction, SSACall):
            return instruction.result
        if isinstance(
            instruction,
            (
                SSAArrayNew,
                SSAArrayGet,
                SSAArraySlice,
                SSAListNew,
                SSAListGet,
                SSAListCopy,
                SSAListContains,
                SSAListIndexOf,
                SSAListPop,
                SSAListRemoveAt,
                SSAVectorGet,
                SSAMatrixGet,
                SSAArrayLength,
                SSAListLength,
                SSAListIsEmpty,
                SSAVectorLength,
                SSAMatrixRows,
                SSAMatrixColumns,
                SSAVectorNew,
                SSAMatrixNew,
                SSAVectorAdd,
                SSAVectorDot,
                SSAOuterProduct,
                SSAVectorScale,
                SSAMatrixAdd,
                SSAMatrixMatMul,
                SSAMatrixVectorMul,
                SSAVectorMatrixMul,
                SSAMatrixScale,
                SSAVectorSub,
                SSAMatrixSub,
            ),
        ):
            return instruction.result
        return None

    def _print_binary_op(self, instruction: SSABinaryOp) -> str:
        if (
            isinstance(instruction.result.type, StringType)
            or isinstance(instruction.left.type, StringType)
            or isinstance(instruction.right.type, StringType)
        ):
            raise LLVMBackendError(
                "LLVM backend does not support string binary operations yet; "
                "only string literals as ptr values are supported"
            )

        if (
            isinstance(instruction.left.type, IntType)
            and isinstance(instruction.right.type, IntType)
        ):
            if instruction.operator not in self._INT_BINARY_OPERATORS:
                operator = None
            else:
                if instruction.operator == "div" and not isinstance(instruction.result.type, DoubleType):
                    raise LLVMBackendError("LLVM checked int division result must be double")
                if instruction.operator != "div" and not isinstance(instruction.result.type, IntType):
                    raise LLVMBackendError("LLVM checked int arithmetic result must be int")
                self._checked_int_operators.add(instruction.operator)
                helper = LLVMIntegerRuntime.helper_name(instruction.operator)
                result_type = llvm_type(instruction.result.type)
                result = self._new_temp(instruction.result)
                left = self._operand(instruction.left)
                right = self._operand(instruction.right)
                return f"{result} = call {result_type} @{helper}(i32 {left}, i32 {right})"
        elif (
            isinstance(instruction.result.type, DoubleType)
            and isinstance(instruction.left.type, DoubleType)
            and isinstance(instruction.right.type, DoubleType)
        ):
            operator = self._DOUBLE_BINARY_OPERATORS.get(instruction.operator)
            result_type = "double"
        else:
            raise LLVMBackendError(
                "LLVM backend only supports homogeneous i32 or double binary operations"
            )

        if operator is None:
            raise LLVMBackendError(
                f"LLVM backend does not support binary operator '{instruction.operator}'"
            )

        result = self._new_temp(instruction.result)
        left = self._operand(instruction.left)
        right = self._operand(instruction.right)
        return f"{result} = {operator} {result_type} {left}, {right}"

    def _print_compare_op(self, instruction: SSACompareOp) -> str:
        if instruction.aggregate_shape is not None:
            self._uses_array_type = True
            if isinstance(instruction.left.type, VectorType):
                prefix = "vector"
                element_type = instruction.left.type.element
                self._vector_equality_types.add(element_type)
            elif isinstance(instruction.left.type, MatrixType):
                prefix = "matrix"
                element_type = instruction.left.type.element
                self._matrix_equality_types.add(element_type)
            else:
                raise LLVMBackendError("LLVM aggregate compare expects VectorType or MatrixType")
            length = 1
            for size in instruction.aggregate_shape:
                length *= size
            result = self._new_temp(instruction.result)
            helper = f"aether_{prefix}_equal_{aggregate_helper_suffix(element_type)}"
            left = self._operand(instruction.left)
            right = self._operand(instruction.right)
            if instruction.operator == "eq":
                return f"{result} = call i1 @{helper}(ptr {left}, ptr {right}, i64 {length})"
            if instruction.operator == "ne":
                equal = self._synthetic_temp(f"{prefix}.equal")
                return "\n  ".join(
                    [
                        f"{equal} = call i1 @{helper}(ptr {left}, ptr {right}, i64 {length})",
                        f"{result} = xor i1 {equal}, true",
                    ]
                )
            raise LLVMBackendError("LLVM aggregate compare only supports eq/ne")

        if (
            isinstance(instruction.left.type, StringType)
            or isinstance(instruction.right.type, StringType)
        ):
            raise LLVMBackendError(
                "LLVM backend does not support string comparisons yet; "
                "only string literals as ptr values are supported"
            )

        if (
            isinstance(instruction.result.type, BoolType)
            and isinstance(instruction.left.type, IntType)
            and isinstance(instruction.right.type, IntType)
        ):
            operation = "icmp"
            predicate = self._INT_COMPARE_OPERATORS.get(instruction.operator)
            operand_type = "i32"
        elif (
            isinstance(instruction.result.type, BoolType)
            and isinstance(instruction.left.type, DoubleType)
            and isinstance(instruction.right.type, DoubleType)
        ):
            operation = "fcmp"
            predicate = self._DOUBLE_COMPARE_OPERATORS.get(instruction.operator)
            operand_type = "double"
        else:
            raise LLVMBackendError(
                "LLVM backend only supports i32 or double comparisons producing i1"
            )

        if predicate is None:
            raise LLVMBackendError(
                f"LLVM backend does not support compare operator '{instruction.operator}'"
            )

        result = self._new_temp(instruction.result)
        left = self._operand(instruction.left)
        right = self._operand(instruction.right)
        return f"{result} = {operation} {predicate} {operand_type} {left}, {right}"

    def _print_cast(self, instruction: SSACast) -> str:
        if isinstance(instruction.value.type, IntType) and isinstance(
            instruction.result.type,
            DoubleType,
        ):
            operator = "sitofp"
        elif isinstance(instruction.value.type, DoubleType) and isinstance(
            instruction.result.type,
            IntType,
        ):
            operator = "fptosi"
        else:
            raise LLVMBackendError(
                "LLVM backend only supports casts from i32 to double "
                "or double to i32"
            )

        result = self._new_temp(instruction.result)
        source_type = llvm_type(instruction.value.type)
        target_type = llvm_type(instruction.result.type)
        value = self._operand(instruction.value)
        return f"{result} = {operator} {source_type} {value} to {target_type}"

    def _print_phi(self, instruction: SSAPhi) -> str:
        if not instruction.incoming:
            raise LLVMBackendError("LLVM backend does not support phi with no incoming values")

        result_type = llvm_type(instruction.result.type)
        result = self._new_temp(instruction.result)
        incoming = ", ".join(
            f"[ {self._operand(value)}, %{self._label_name(block)} ]"
            for block, value in instruction.incoming
        )
        return f"{result} = phi {result_type} {incoming}"

    def _print_return(self, instruction: SSAReturn, function: SSAFunction) -> str:
        if instruction.value is None:
            if not isinstance(function.return_type, VoidType):
                raise LLVMBackendError(
                    "LLVM backend does not support empty return from non-void function"
                )
            return "ret void"

        if isinstance(function.return_type, VoidType):
            raise LLVMBackendError(
                "LLVM backend does not support value return from void function"
            )

        return_type = llvm_type(function.return_type)
        value_type = llvm_type(instruction.value.type)
        if value_type != return_type:
            raise LLVMBackendError(
                "LLVM backend does not support return type mismatches"
            )
        return f"ret {return_type} {self._operand(instruction.value)}"

    def _print_branch(self, instruction: SSABranch) -> str:
        if not isinstance(instruction.condition.type, BoolType):
            raise LLVMBackendError(
                "LLVM backend only supports bool/i1 branch conditions"
            )

        condition = self._operand(instruction.condition)
        true_target = self._label_operand(instruction.true_target)
        false_target = self._label_operand(instruction.false_target)
        return f"br i1 {condition}, {true_target}, {false_target}"

    def _print_jump(self, instruction: SSAJump) -> str:
        return f"br {self._label_operand(instruction.target)}"

    def _print_call(self, instruction: SSACall) -> str:
        arguments = ", ".join(
            f"{llvm_type(argument.type)} {self._operand(argument)}"
            for argument in instruction.arguments
        )
        callee = self._global_name(instruction.function)
        if instruction.result is None:
            return f"call void {callee}({arguments})"

        return_type = llvm_type(instruction.result.type)
        if isinstance(instruction.result.type, VoidType):
            raise LLVMBackendError(
                "LLVM backend does not support assigning void call results"
            )
        result = self._new_temp(instruction.result)
        return f"{result} = call {return_type} {callee}({arguments})"

    def _print_print(self, instruction: SSAPrint) -> str:
        self._uses_print = True
        suffix = "ln" if instruction.newline else ""
        value = self._operand(instruction.value)
        call_result = self._synthetic_temp("print.result")

        if isinstance(instruction.value.type, VectorType):
            self._uses_array_type = True
            if instruction.aggregate_shape is None or len(instruction.aggregate_shape) != 1:
                raise LLVMBackendError("LLVM Vector print requires a known length")
            element_type = instruction.value.type.element
            self._vector_print_types.add(element_type)
            helper = f"aether_vector_print_{aggregate_helper_suffix(element_type)}"
            column = "true" if instruction.value.type.orientation == "column" else "false"
            newline = "true" if instruction.newline else "false"
            return (
                f"call void @{helper}(ptr {value}, i64 {instruction.aggregate_shape[0]}, "
                f"i1 {column}, i1 {newline})"
            )
        if isinstance(instruction.value.type, MatrixType):
            self._uses_array_type = True
            if instruction.aggregate_shape is None or len(instruction.aggregate_shape) != 2:
                raise LLVMBackendError("LLVM Matrix print requires known dimensions")
            element_type = instruction.value.type.element
            self._matrix_print_types.add(element_type)
            helper = f"aether_matrix_print_{aggregate_helper_suffix(element_type)}"
            rows, columns = instruction.aggregate_shape
            newline = "true" if instruction.newline else "false"
            return (
                f"call void @{helper}(ptr {value}, i64 {rows}, i64 {columns}, i1 {newline})"
            )

        if isinstance(instruction.value.type, IntType):
            return (
                f"{call_result} = call i32 (ptr, ...) @printf("
                f"ptr @.aether.io.int{suffix}, i32 {value})"
            )
        if isinstance(instruction.value.type, DoubleType):
            return (
                f"{call_result} = call i32 (ptr, ...) @printf("
                f"ptr @.aether.io.double{suffix}, double {value})"
            )
        if isinstance(instruction.value.type, StringType):
            return (
                f"{call_result} = call i32 (ptr, ...) @printf("
                f"ptr @.aether.io.string{suffix}, ptr {value})"
            )
        if isinstance(instruction.value.type, BoolType):
            selected = self._synthetic_temp("print.bool")
            return "\n  ".join(
                [
                    f"{selected} = select i1 {value}, ptr @.aether.io.true, ptr @.aether.io.false",
                    f"{call_result} = call i32 (ptr, ...) @printf("
                    f"ptr @.aether.io.string{suffix}, ptr {selected})",
                ]
            )
        raise LLVMBackendError(
            "LLVM print only supports int, boolean, string, and double; "
            f"got {instruction.value.type}"
        )

    def _print_array_new(self, instruction: SSAArrayNew) -> str:
        if not isinstance(instruction.result.type, ArrayType):
            raise LLVMBackendError("LLVM array_new result must be ArrayType")
        return self._print_contiguous_new(
            instruction.result,
            instruction.result.type.element,
            instruction.elements,
        )

    def _print_list_new(self, instruction: SSAListNew) -> str:
        if not isinstance(instruction.result.type, ListType):
            raise LLVMBackendError("LLVM list_new result must be ListType")
        self._uses_list_type = True
        self._uses_list_allocation = True

        element_type = llvm_type(instruction.result.type.element)
        element_size = self._sizeof(instruction.result.type.element)
        length = len(instruction.elements)
        result = self._new_temp(instruction.result)
        data = self._synthetic_temp("list.data")
        data_field = self._synthetic_temp("list.data.field")
        lines = [
            f"{result} = call ptr @aether_list_new(i64 {element_size}, i64 {length})",
        ]
        lines.extend(self._load_list_data(data, result, data_field))

        def emit_element(index: int) -> None:
            element = instruction.elements[index]
            element_ptr = self._synthetic_temp("list.elem")
            lines.append(
                self._element_pointer_line(element_ptr, element_type, data, index)
            )
            lines.append(self._store_element_line(element_type, self._operand(element), element_ptr))

        self._for_each_element(length, emit_element)
        return "\n  ".join(lines)

    def _print_list_copy(self, instruction: SSAListCopy) -> str:
        if not isinstance(instruction.list_value.type, ListType):
            raise LLVMBackendError("LLVM list_copy expects a ListType source")
        if instruction.result.type != instruction.list_value.type:
            raise LLVMBackendError("LLVM list_copy result type must match source type")
        self._uses_list_type = True
        self._uses_list_allocation = True
        self._uses_list_copy = True
        result = self._new_temp(instruction.result)
        size = self._sizeof(instruction.list_value.type.element)
        return f"{result} = call ptr @aether_list_copy(ptr {self._operand(instruction.list_value)}, i64 {size})"

    def _print_list_contains(self, instruction: SSAListContains) -> str:
        if not isinstance(instruction.list_value.type, ListType):
            raise LLVMBackendError("LLVM list_contains expects a ListType source")
        if instruction.value.type != instruction.list_value.type.element:
            raise LLVMBackendError("LLVM list_contains value type must match list element type")
        self._uses_list_type = True
        self._list_contains_types.add(instruction.value.type)
        result = self._new_temp(instruction.result)
        helper = list_contains_helper_name(instruction.value.type)
        value_type = llvm_type(instruction.value.type)
        return (
            f"{result} = call i1 @{helper}(ptr {self._operand(instruction.list_value)}, "
            f"{value_type} {self._operand(instruction.value)})"
        )

    def _print_list_index_of(self, instruction: SSAListIndexOf) -> str:
        if not isinstance(instruction.list_value.type, ListType):
            raise LLVMBackendError("LLVM list_index_of expects a ListType source")
        if instruction.value.type != instruction.list_value.type.element:
            raise LLVMBackendError("LLVM list_index_of value type must match list element type")
        self._uses_list_type = True
        self._list_index_of_types.add(instruction.value.type)
        result = self._new_temp(instruction.result)
        helper = list_index_of_helper_name(instruction.value.type)
        value_type = llvm_type(instruction.value.type)
        return (
            f"{result} = call i32 @{helper}(ptr {self._operand(instruction.list_value)}, "
            f"{value_type} {self._operand(instruction.value)})"
        )

    def _print_list_reverse(self, instruction: SSAListReverse) -> str:
        if not isinstance(instruction.list_value.type, ListType):
            raise LLVMBackendError("LLVM list_reverse expects a ListType source")
        self._uses_list_type = True
        self._uses_list_reverse = True
        size = self._sizeof(instruction.list_value.type.element)
        return f"call void @aether_list_reverse(ptr {self._operand(instruction.list_value)}, i64 {size})"

    def _print_list_clear(self, instruction: SSAListClear) -> str:
        if not isinstance(instruction.list_value.type, ListType):
            raise LLVMBackendError("LLVM list_clear expects a ListType source")
        self._uses_list_type = True
        length_field = self._synthetic_temp("list.clear.length_field")
        return "\n  ".join(
            self._store_list_length(
                "0", self._operand(instruction.list_value), length_field
            )
        )

    def _print_list_push(self, instruction: SSAListPush) -> list[str]:
        if not isinstance(instruction.list_value.type, ListType):
            raise LLVMBackendError("LLVM list_push expects a ListType source")
        if instruction.value.type != instruction.list_value.type.element:
            raise LLVMBackendError("LLVM list_push value type must match list element type")
        self._uses_list_type = True
        self._uses_list_push = True
        list_value = self._operand(instruction.list_value)
        element_type = llvm_type(instruction.value.type)
        element_size = self._sizeof(instruction.value.type)
        old_length = self._synthetic_temp("list.push.old_length")
        data_field = self._synthetic_temp("list.push.data_field")
        data = self._synthetic_temp("list.push.data")
        element_ptr = self._synthetic_temp("list.push.element")
        new_length = self._synthetic_temp("list.push.new_length")
        length_field = self._synthetic_temp("list.push.length_field")
        return [
            f"{old_length} = call i64 @aether_list_prepare_push(ptr {list_value}, i64 {element_size})",
            *self._load_list_data(data, list_value, data_field),
            f"{element_ptr} = getelementptr {element_type}, ptr {data}, i64 {old_length}",
            f"store {element_type} {self._operand(instruction.value)}, ptr {element_ptr}",
            f"{new_length} = add i64 {old_length}, 1",
            *self._store_list_length(new_length, list_value, length_field),
        ]

    def _print_list_insert(self, instruction: SSAListInsert) -> list[str]:
        if not isinstance(instruction.list_value.type, ListType):
            raise LLVMBackendError("LLVM list_insert expects a ListType source")
        if not isinstance(instruction.index.type, IntType):
            raise LLVMBackendError("LLVM list_insert index must be int")
        if instruction.value.type != instruction.list_value.type.element:
            raise LLVMBackendError("LLVM list_insert value type must match list element type")
        self._uses_list_type = True
        self._uses_list_insert = True
        list_value = self._operand(instruction.list_value)
        index = self._operand(instruction.index)
        element_type = llvm_type(instruction.value.type)
        element_size = self._sizeof(instruction.value.type)
        index64 = self._synthetic_temp("list.insert.index64")
        old_length = self._synthetic_temp("list.insert.old_length")
        data_field = self._synthetic_temp("list.insert.data_field")
        data = self._synthetic_temp("list.insert.data")
        source = self._synthetic_temp("list.insert.source")
        destination = self._synthetic_temp("list.insert.destination")
        elements_to_move = self._synthetic_temp("list.insert.elements_to_move")
        bytes_to_move = self._synthetic_temp("list.insert.bytes_to_move")
        element_ptr = self._synthetic_temp("list.insert.element")
        new_length = self._synthetic_temp("list.insert.new_length")
        length_field = self._synthetic_temp("list.insert.length_field")
        return [
            self._list_index64_line(index64, index),
            f"{old_length} = call i64 @aether_list_prepare_insert(ptr {list_value}, i64 {index64}, i64 {element_size})",
            *self._load_list_data(data, list_value, data_field),
            f"{source} = getelementptr {element_type}, ptr {data}, i64 {index64}",
            f"{destination} = getelementptr {element_type}, ptr {source}, i64 1",
            f"{elements_to_move} = sub i64 {old_length}, {index64}",
            f"{bytes_to_move} = mul i64 {elements_to_move}, {element_size}",
            f"call void @llvm.memmove.p0.p0.i64(ptr {destination}, ptr {source}, i64 {bytes_to_move}, i1 false)",
            f"{element_ptr} = getelementptr {element_type}, ptr {data}, i64 {index64}",
            f"store {element_type} {self._operand(instruction.value)}, ptr {element_ptr}",
            f"{new_length} = add i64 {old_length}, 1",
            *self._store_list_length(new_length, list_value, length_field),
        ]

    def _print_list_pop(self, instruction: SSAListPop) -> list[str]:
        if not isinstance(instruction.list_value.type, ListType):
            raise LLVMBackendError("LLVM list_pop expects a ListType source")
        if instruction.result.type != instruction.list_value.type.element:
            raise LLVMBackendError("LLVM list_pop result type must match list element type")
        self._uses_list_type = True
        self._uses_list_pop = True
        list_value = self._operand(instruction.list_value)
        element_type = llvm_type(instruction.result.type)
        new_length = self._synthetic_temp("list.pop.new_length")
        data_field = self._synthetic_temp("list.pop.data_field")
        data = self._synthetic_temp("list.pop.data")
        element_ptr = self._synthetic_temp("list.pop.element")
        result = self._new_temp(instruction.result)
        length_field = self._synthetic_temp("list.pop.length_field")
        return [
            f"{new_length} = call i64 @aether_list_prepare_pop(ptr {list_value})",
            *self._load_list_data(data, list_value, data_field),
            f"{element_ptr} = getelementptr {element_type}, ptr {data}, i64 {new_length}",
            f"{result} = load {element_type}, ptr {element_ptr}",
            *self._store_list_length(new_length, list_value, length_field),
        ]

    def _print_list_remove_at(self, instruction: SSAListRemoveAt) -> list[str]:
        if not isinstance(instruction.list_value.type, ListType):
            raise LLVMBackendError("LLVM list_remove_at expects a ListType source")
        if not isinstance(instruction.index.type, IntType):
            raise LLVMBackendError("LLVM list_remove_at index must be int")
        if instruction.result.type != instruction.list_value.type.element:
            raise LLVMBackendError("LLVM list_remove_at result type must match list element type")
        self._uses_list_type = True
        self._uses_list_remove_at = True
        list_value = self._operand(instruction.list_value)
        index = self._operand(instruction.index)
        element_type = llvm_type(instruction.result.type)
        element_size = self._sizeof(instruction.result.type)
        index64 = self._synthetic_temp("list.remove_at.index64")
        old_length = self._synthetic_temp("list.remove_at.old_length")
        new_length = self._synthetic_temp("list.remove_at.new_length")
        data_field = self._synthetic_temp("list.remove_at.data_field")
        data = self._synthetic_temp("list.remove_at.data")
        removed_ptr = self._synthetic_temp("list.remove_at.removed")
        result = self._new_temp(instruction.result)
        source = self._synthetic_temp("list.remove_at.source")
        elements_to_move = self._synthetic_temp("list.remove_at.elements_to_move")
        bytes_to_move = self._synthetic_temp("list.remove_at.bytes_to_move")
        length_field = self._synthetic_temp("list.remove_at.length_field")
        return [
            self._list_index64_line(index64, index),
            f"{old_length} = call i64 @aether_list_prepare_remove_at(ptr {list_value}, i64 {index64}, i64 {element_size})",
            f"{new_length} = sub i64 {old_length}, 1",
            *self._load_list_data(data, list_value, data_field),
            f"{removed_ptr} = getelementptr {element_type}, ptr {data}, i64 {index64}",
            f"{result} = load {element_type}, ptr {removed_ptr}",
            f"{source} = getelementptr {element_type}, ptr {removed_ptr}, i64 1",
            f"{elements_to_move} = sub i64 {new_length}, {index64}",
            f"{bytes_to_move} = mul i64 {elements_to_move}, {element_size}",
            f"call void @llvm.memmove.p0.p0.i64(ptr {removed_ptr}, ptr {source}, i64 {bytes_to_move}, i1 false)",
            *self._store_list_length(new_length, list_value, length_field),
        ]

    def _print_sequence_sort(self, instruction: SSASequenceSort) -> str:
        sequence_type = instruction.sequence.type
        if not isinstance(sequence_type, (ArrayType, ListType)):
            raise LLVMBackendError("LLVM sequence_sort expects an ArrayType or ListType source")
        element_type = sequence_type.element
        helper = sequence_sort_helper_name(element_type)
        self._sequence_sort_types.add(element_type)
        sequence = self._operand(instruction.sequence)
        data = self._synthetic_temp("sort.data")
        length = self._synthetic_temp("sort.length")
        if isinstance(sequence_type, ArrayType):
            self._uses_array_type = True
            lines = self._array_data_pointer(data, sequence)
            lines.extend(self._array_length64(length, sequence))
        else:
            self._uses_list_type = True
            lines = self._list_data_pointer(data, sequence)
            lines.extend(self._list_length64(length, sequence))
        lines.append(f"call void @{helper}(ptr {data}, i64 {length})")
        return "\n  ".join(lines)

    def _print_vector_new(self, instruction: SSAVectorNew) -> str:
        if not isinstance(instruction.result.type, VectorType):
            raise LLVMBackendError("LLVM vector_new result must be VectorType")
        if instruction.result.type.orientation not in {"row", "column"}:
            raise LLVMBackendError("LLVM vector_new requires row or column orientation")
        if instruction.orientation != instruction.result.type.orientation:
            raise LLVMBackendError("LLVM vector_new instruction orientation must match result type")
        return self._print_contiguous_new(
            instruction.result,
            instruction.result.type.element,
            instruction.elements,
        )

    def _print_matrix_new(self, instruction: SSAMatrixNew) -> str:
        if not isinstance(instruction.result.type, MatrixType):
            raise LLVMBackendError("LLVM matrix_new result must be MatrixType")
        if instruction.rows <= 0 or instruction.cols <= 0:
            raise LLVMBackendError("LLVM matrix_new requires positive dimensions")
        if len(instruction.elements) != instruction.rows * instruction.cols:
            raise LLVMBackendError("LLVM matrix_new element count must match dimensions")
        return self._print_contiguous_new(
            instruction.result,
            instruction.result.type.element,
            instruction.elements,
        )

    def _print_vector_add(self, instruction: SSAVectorAdd) -> list[str]:
        self._validate_vector_binary(instruction, "add")
        return self._print_contiguous_binary(
            instruction.result,
            instruction.left,
            instruction.right,
            instruction.result.type.element,
            instruction.length,
            "add",
        )

    def _print_vector_sub(self, instruction: SSAVectorSub) -> list[str]:
        self._validate_vector_binary(instruction, "sub")
        return self._print_contiguous_binary(
            instruction.result,
            instruction.left,
            instruction.right,
            instruction.result.type.element,
            instruction.length,
            "sub",
        )

    def _validate_vector_binary(
        self,
        instruction: SSAVectorAdd | SSAVectorSub,
        operation: str,
    ) -> None:
        if not isinstance(instruction.result.type, VectorType):
            raise LLVMBackendError(f"LLVM vector_{operation} result must be VectorType")
        if instruction.result.type != instruction.left.type or instruction.result.type != instruction.right.type:
            raise LLVMBackendError(f"LLVM vector_{operation} requires matching vector operand and result types")
        if instruction.length <= 0:
            raise LLVMBackendError(f"LLVM vector_{operation} requires a positive length")
        if instruction.orientation != instruction.result.type.orientation:
            raise LLVMBackendError(f"LLVM vector_{operation} instruction orientation must match result type")

    def _print_vector_scale(self, instruction: SSAVectorScale) -> list[str]:
        self._validate_vector_scale(instruction)
        return self._print_contiguous_scale(
            instruction.result,
            instruction.vector,
            instruction.scalar,
            instruction.result.type.element,
            instruction.length,
            "vector.scale",
        )

    def _validate_vector_scale(self, instruction: SSAVectorScale) -> None:
        if not isinstance(instruction.result.type, VectorType):
            raise LLVMBackendError("LLVM vector_scale result must be VectorType")
        if instruction.result.type != instruction.vector.type:
            raise LLVMBackendError("LLVM vector_scale requires matching vector operand and result types")
        if instruction.scalar.type != instruction.result.type.element:
            raise LLVMBackendError("LLVM vector_scale scalar type must match vector element type")
        if instruction.length <= 0:
            raise LLVMBackendError("LLVM vector_scale requires a positive length")
        if instruction.orientation != instruction.result.type.orientation:
            raise LLVMBackendError("LLVM vector_scale instruction orientation must match result type")

    def _print_vector_dot(self, instruction: SSAVectorDot) -> list[str]:
        self._validate_vector_dot(instruction)
        self._uses_array_type = True

        result = self._new_temp(instruction.result)
        result_type = llvm_type(instruction.result.type)
        left_element_type = llvm_type(instruction.left.type.element)
        right_element_type = llvm_type(instruction.right.type.element)
        multiply_operator = self._element_binary_operator(instruction.result.type, "mul")
        add_operator = self._element_binary_operator(instruction.result.type, "add")
        zero = "0.0" if isinstance(instruction.result.type, DoubleType) else "0"
        labels = self._linear_loop_labels("vector.dot")

        left_field = self._synthetic_temp("vector.dot.left.data.field")
        left_data = self._synthetic_temp("vector.dot.left.data")
        right_data = self._synthetic_temp("vector.dot.right.data")
        acc_ptr = self._synthetic_temp("vector.dot.acc.ptr")
        index_ptr = self._synthetic_temp("vector.dot.index.ptr")
        lines = [
            LLVMArrayRuntime.data_pointer_line(left_field, self._operand(instruction.left), indent="  "),
            f"  {left_data} = load ptr, ptr {left_field}",
        ]
        right_field = self._synthetic_temp("vector.dot.right.data.field")
        lines.extend(
            [
                LLVMArrayRuntime.data_pointer_line(right_field, self._operand(instruction.right), indent="  "),
                f"  {right_data} = load ptr, ptr {right_field}",
                f"  {acc_ptr} = alloca {result_type}",
                f"  store {result_type} {zero}, ptr {acc_ptr}",
                f"  {index_ptr} = alloca i64",
                f"  store i64 0, ptr {index_ptr}",
                f"  br label %{labels.loop}",
                f"{labels.loop}:",
            ]
        )
        index = self._synthetic_temp("vector.dot.index")
        condition = self._synthetic_temp("vector.dot.cond")
        lines.extend(
            self._linear_loop_check(
                index,
                index_ptr,
                condition,
                instruction.length,
                labels,
                indent="  ",
            )
        )

        left_ptr = self._synthetic_temp("vector.dot.left.elem")
        right_ptr = self._synthetic_temp("vector.dot.right.elem")
        loaded_left = self._synthetic_temp("vector.dot.left")
        loaded_right = self._synthetic_temp("vector.dot.right")
        lines.extend(
            [
                self._element_pointer_line(left_ptr, left_element_type, left_data, index, indent="  "),
                self._load_element_line(loaded_left, left_element_type, left_ptr, indent="  "),
                self._element_pointer_line(right_ptr, right_element_type, right_data, index, indent="  "),
                self._load_element_line(loaded_right, right_element_type, right_ptr, indent="  "),
            ]
        )
        left_operand = self._coerce_scalar(lines, loaded_left, instruction.left.type.element, instruction.result.type, "vector.dot.left.cast")
        right_operand = self._coerce_scalar(lines, loaded_right, instruction.right.type.element, instruction.result.type, "vector.dot.right.cast")
        product = self._synthetic_temp("vector.dot.product")
        acc_current = self._synthetic_temp("vector.dot.acc")
        acc_next = self._synthetic_temp("vector.dot.acc.next")
        index_next = self._synthetic_temp("vector.dot.index.next")
        lines.extend(
            [
                f"  {product} = {multiply_operator} {result_type} {left_operand}, {right_operand}",
                f"  {acc_current} = load {result_type}, ptr {acc_ptr}",
                f"  {acc_next} = {add_operator} {result_type} {acc_current}, {product}",
                f"  store {result_type} {acc_next}, ptr {acc_ptr}",
                f"  {index_next} = add i64 {index}, 1",
                f"  store i64 {index_next}, ptr {index_ptr}",
                f"  br label %{labels.loop}",
                f"{labels.exit}:",
                f"  {result} = load {result_type}, ptr {acc_ptr}",
            ]
        )
        return lines

    def _validate_vector_dot(self, instruction: SSAVectorDot) -> None:
        if not isinstance(instruction.left.type, VectorType) or not isinstance(instruction.right.type, VectorType):
            raise LLVMBackendError("LLVM vector_dot expects vector operands")
        if instruction.left.type.orientation != "row" or instruction.right.type.orientation != "column":
            raise LLVMBackendError("LLVM vector_dot is only defined for Vector<Row> * Vector<Column>")
        if instruction.length <= 0:
            raise LLVMBackendError("LLVM vector_dot requires a positive length")
        if not isinstance(instruction.result.type, (IntType, DoubleType)):
            raise LLVMBackendError("LLVM vector_dot only supports int or double results")
        if not isinstance(instruction.left.type.element, (IntType, DoubleType)):
            raise LLVMBackendError("LLVM vector_dot only supports int or double left elements")
        if not isinstance(instruction.right.type.element, (IntType, DoubleType)):
            raise LLVMBackendError("LLVM vector_dot only supports int or double right elements")

    def _print_outer_product(self, instruction: SSAOuterProduct) -> list[str]:
        self._validate_outer_product(instruction)
        self._uses_array_type = True
        self._uses_array_allocation = True

        result = self._new_temp(instruction.result)
        result_element_type = llvm_type(instruction.result.type.element)
        result_element_size = self._sizeof(instruction.result.type.element)
        column_element_type = llvm_type(instruction.column.type.element)
        row_element_type = llvm_type(instruction.row.type.element)
        multiply_operator = self._element_binary_operator(instruction.result.type.element, "mul")
        labels = self._double_loop_labels("outer.product")
        length = instruction.rows * instruction.cols

        column_field = self._synthetic_temp("outer.product.column.data.field")
        column_data = self._synthetic_temp("outer.product.column.data")
        row_field = self._synthetic_temp("outer.product.row.data.field")
        row_data = self._synthetic_temp("outer.product.row.data")
        result_field = self._synthetic_temp("outer.product.result.data.field")
        result_data = self._synthetic_temp("outer.product.result.data")
        row_index_ptr = self._synthetic_temp("outer.product.row.index.ptr")
        col_index_ptr = self._synthetic_temp("outer.product.col.index.ptr")
        lines = [
            f"  {result} = call ptr @aether_array_new(i64 {result_element_size}, i64 {length})",
            LLVMArrayRuntime.data_pointer_line(column_field, self._operand(instruction.column), indent="  "),
            f"  {column_data} = load ptr, ptr {column_field}",
            LLVMArrayRuntime.data_pointer_line(row_field, self._operand(instruction.row), indent="  "),
            f"  {row_data} = load ptr, ptr {row_field}",
            LLVMArrayRuntime.data_pointer_line(result_field, result, indent="  "),
            f"  {result_data} = load ptr, ptr {result_field}",
            f"  {row_index_ptr} = alloca i64",
            f"  store i64 0, ptr {row_index_ptr}",
            f"  {col_index_ptr} = alloca i64",
            f"  br label %{labels.outer_loop}",
            f"{labels.outer_loop}:",
        ]

        row_index = self._synthetic_temp("outer.product.row.index")
        outer_cond = self._synthetic_temp("outer.product.outer.cond")
        lines.extend(
            self._double_loop_outer_check(
                row_index,
                row_index_ptr,
                outer_cond,
                instruction.rows,
                labels,
                indent="  ",
            )
            + [
                f"  store i64 0, ptr {col_index_ptr}",
                f"  br label %{labels.inner_loop}",
                f"{labels.inner_loop}:",
            ]
        )

        col_index = self._synthetic_temp("outer.product.col.index")
        inner_cond = self._synthetic_temp("outer.product.inner.cond")
        lines.extend(
            self._double_loop_inner_check(
                col_index,
                col_index_ptr,
                inner_cond,
                instruction.cols,
                labels,
                indent="  ",
            )
        )

        column_ptr = self._synthetic_temp("outer.product.column.elem")
        row_ptr = self._synthetic_temp("outer.product.row.elem")
        loaded_column = self._synthetic_temp("outer.product.column")
        loaded_row = self._synthetic_temp("outer.product.row")
        row_offset = self._synthetic_temp("outer.product.row.offset")
        result_index = self._synthetic_temp("outer.product.result.index")
        result_ptr = self._synthetic_temp("outer.product.result.elem")
        lines.extend(
            [
                self._element_pointer_line(column_ptr, column_element_type, column_data, row_index, indent="  "),
                self._load_element_line(loaded_column, column_element_type, column_ptr, indent="  "),
                self._element_pointer_line(row_ptr, row_element_type, row_data, col_index, indent="  "),
                self._load_element_line(loaded_row, row_element_type, row_ptr, indent="  "),
            ]
        )
        column_operand = self._coerce_scalar(
            lines,
            loaded_column,
            instruction.column.type.element,
            instruction.result.type.element,
            "outer.product.column.cast",
        )
        row_operand = self._coerce_scalar(
            lines,
            loaded_row,
            instruction.row.type.element,
            instruction.result.type.element,
            "outer.product.row.cast",
        )
        product = self._synthetic_temp("outer.product.product")
        col_next = self._synthetic_temp("outer.product.col.next")
        row_next = self._synthetic_temp("outer.product.row.next")
        lines.extend(
            [
                f"  {product} = {multiply_operator} {result_element_type} {column_operand}, {row_operand}",
                f"  {row_offset} = mul i64 {row_index}, {instruction.cols}",
                f"  {result_index} = add i64 {row_offset}, {col_index}",
                self._element_pointer_line(result_ptr, result_element_type, result_data, result_index, indent="  "),
                self._store_element_line(result_element_type, product, result_ptr, indent="  "),
                f"  {col_next} = add i64 {col_index}, 1",
                f"  store i64 {col_next}, ptr {col_index_ptr}",
                f"  br label %{labels.inner_loop}",
                f"{labels.inner_exit}:",
                f"  {row_next} = add i64 {row_index}, 1",
                f"  store i64 {row_next}, ptr {row_index_ptr}",
                f"  br label %{labels.outer_loop}",
                f"{labels.exit}:",
            ]
        )
        return lines

    def _validate_outer_product(self, instruction: SSAOuterProduct) -> None:
        if not isinstance(instruction.result.type, MatrixType):
            raise LLVMBackendError("LLVM outer_product result must be MatrixType")
        if not isinstance(instruction.column.type, VectorType) or not isinstance(instruction.row.type, VectorType):
            raise LLVMBackendError("LLVM outer_product expects vector operands")
        if instruction.column.type.orientation != "column" or instruction.row.type.orientation != "row":
            raise LLVMBackendError("LLVM outer_product is only defined for Vector<Column> * Vector<Row>")
        if instruction.rows <= 0 or instruction.cols <= 0:
            raise LLVMBackendError("LLVM outer_product requires positive dimensions")
        if not isinstance(instruction.result.type.element, (IntType, DoubleType)):
            raise LLVMBackendError("LLVM outer_product only supports int or double results")
        if not isinstance(instruction.column.type.element, (IntType, DoubleType)):
            raise LLVMBackendError("LLVM outer_product only supports int or double column elements")
        if not isinstance(instruction.row.type.element, (IntType, DoubleType)):
            raise LLVMBackendError("LLVM outer_product only supports int or double row elements")

    def _coerce_scalar(
        self,
        lines: list[str],
        value: str,
        source_type: object,
        target_type: object,
        prefix: str,
    ) -> str:
        if source_type == target_type:
            return value
        if isinstance(source_type, IntType) and isinstance(target_type, DoubleType):
            result = self._synthetic_temp(prefix)
            lines.append(f"  {result} = sitofp i32 {value} to double")
            return result
        raise LLVMBackendError(f"LLVM backend cannot coerce {source_type} to {target_type}")

    def _print_matrix_add(self, instruction: SSAMatrixAdd) -> list[str]:
        self._validate_matrix_binary(instruction, "add")
        return self._print_contiguous_binary(
            instruction.result,
            instruction.left,
            instruction.right,
            instruction.result.type.element,
            instruction.rows * instruction.cols,
            "add",
        )

    def _print_matrix_sub(self, instruction: SSAMatrixSub) -> list[str]:
        self._validate_matrix_binary(instruction, "sub")
        return self._print_contiguous_binary(
            instruction.result,
            instruction.left,
            instruction.right,
            instruction.result.type.element,
            instruction.rows * instruction.cols,
            "sub",
        )

    def _validate_matrix_binary(
        self,
        instruction: SSAMatrixAdd | SSAMatrixSub,
        operation: str,
    ) -> None:
        if not isinstance(instruction.result.type, MatrixType):
            raise LLVMBackendError(f"LLVM matrix_{operation} result must be MatrixType")
        if instruction.result.type != instruction.left.type or instruction.result.type != instruction.right.type:
            raise LLVMBackendError(f"LLVM matrix_{operation} requires matching matrix operand and result types")
        if instruction.rows <= 0 or instruction.cols <= 0:
            raise LLVMBackendError(f"LLVM matrix_{operation} requires positive dimensions")

    def _print_matrix_scale(self, instruction: SSAMatrixScale) -> list[str]:
        self._validate_matrix_scale(instruction)
        return self._print_contiguous_scale(
            instruction.result,
            instruction.matrix,
            instruction.scalar,
            instruction.result.type.element,
            instruction.rows * instruction.cols,
            "matrix.scale",
        )

    def _validate_matrix_scale(self, instruction: SSAMatrixScale) -> None:
        if not isinstance(instruction.result.type, MatrixType):
            raise LLVMBackendError("LLVM matrix_scale result must be MatrixType")
        if instruction.result.type != instruction.matrix.type:
            raise LLVMBackendError("LLVM matrix_scale requires matching matrix operand and result types")
        if instruction.scalar.type != instruction.result.type.element:
            raise LLVMBackendError("LLVM matrix_scale scalar type must match matrix element type")
        if instruction.rows <= 0 or instruction.cols <= 0:
            raise LLVMBackendError("LLVM matrix_scale requires positive dimensions")

    def _print_matrix_matmul(self, instruction: SSAMatrixMatMul) -> list[str]:
        self._validate_matrix_matmul(instruction)
        self._uses_array_type = True
        self._uses_array_allocation = True

        result_element_type = llvm_type(instruction.result.type.element)
        length = instruction.rows * instruction.cols
        allocation = self._aggregate_allocation(
            instruction.result,
            instruction.result.type.element,
            length,
        )
        result = allocation.result
        multiply_operator = self._element_binary_operator(instruction.result.type.element, "mul")
        add_operator = self._element_binary_operator(instruction.result.type.element, "add")
        zero = "0.0" if isinstance(instruction.result.type.element, DoubleType) else "0"
        lines = [allocation.line]

        left_data = self._synthetic_temp("matrix.matmul.left.data")
        right_data = self._synthetic_temp("matrix.matmul.right.data")
        result_data = self._synthetic_temp("matrix.matmul.result.data")
        lines.extend(self._array_data_pointer(left_data, self._operand(instruction.left)))
        lines.extend(self._array_data_pointer(right_data, self._operand(instruction.right)))
        lines.extend(self._array_data_pointer(result_data, result))

        left_element_type = llvm_type(instruction.left.type.element)
        right_element_type = llvm_type(instruction.right.type.element)

        def emit_cell(row: int, col: int) -> None:
            accumulator = zero
            for inner in range(instruction.inner):
                left_index = row * instruction.inner + inner
                right_index = inner * instruction.cols + col
                left_ptr = self._synthetic_temp("matrix.matmul.left.elem")
                right_ptr = self._synthetic_temp("matrix.matmul.right.elem")
                loaded_left = self._synthetic_temp("matrix.matmul.left")
                loaded_right = self._synthetic_temp("matrix.matmul.right")
                lines.append(
                    self._element_pointer_line(left_ptr, left_element_type, left_data, left_index)
                )
                lines.append(self._load_element_line(loaded_left, left_element_type, left_ptr))
                lines.append(
                    self._element_pointer_line(right_ptr, right_element_type, right_data, right_index)
                )
                lines.append(self._load_element_line(loaded_right, right_element_type, right_ptr))
                left_operand = self._coerce_scalar(
                    lines,
                    loaded_left,
                    instruction.left.type.element,
                    instruction.result.type.element,
                    "matrix.matmul.left.cast",
                )
                right_operand = self._coerce_scalar(
                    lines,
                    loaded_right,
                    instruction.right.type.element,
                    instruction.result.type.element,
                    "matrix.matmul.right.cast",
                )
                product = self._synthetic_temp("matrix.matmul.product")
                summed = self._synthetic_temp("matrix.matmul.sum")
                lines.append(
                    f"{product} = {multiply_operator} {result_element_type} {left_operand}, {right_operand}"
                )
                lines.append(
                    f"{summed} = {add_operator} {result_element_type} {accumulator}, {product}"
                )
                accumulator = summed
            result_index = row * instruction.cols + col
            result_ptr = self._synthetic_temp("matrix.matmul.result.elem")
            lines.append(
                self._element_pointer_line(result_ptr, result_element_type, result_data, result_index)
            )
            lines.append(self._store_element_line(result_element_type, accumulator, result_ptr))

        self._for_each_matrix_element(instruction.rows, instruction.cols, emit_cell)

        return lines

    def _validate_matrix_matmul(self, instruction: SSAMatrixMatMul) -> None:
        if not isinstance(instruction.result.type, MatrixType):
            raise LLVMBackendError("LLVM matrix_matmul result must be MatrixType")
        if not isinstance(instruction.left.type, MatrixType) or not isinstance(instruction.right.type, MatrixType):
            raise LLVMBackendError("LLVM matrix_matmul expects matrix operands")
        if instruction.rows <= 0 or instruction.inner <= 0 or instruction.cols <= 0:
            raise LLVMBackendError("LLVM matrix_matmul requires positive dimensions")
        if not isinstance(instruction.result.type.element, (IntType, DoubleType)):
            raise LLVMBackendError("LLVM matrix_matmul only supports int or double results")
        if not isinstance(instruction.left.type.element, (IntType, DoubleType)):
            raise LLVMBackendError("LLVM matrix_matmul only supports int or double left elements")
        if not isinstance(instruction.right.type.element, (IntType, DoubleType)):
            raise LLVMBackendError("LLVM matrix_matmul only supports int or double right elements")

    def _print_matrix_vector_mul(self, instruction: SSAMatrixVectorMul) -> list[str]:
        self._validate_matrix_vector_mul(instruction)
        self._uses_array_type = True
        self._uses_array_allocation = True

        result_element_type = llvm_type(instruction.result.type.element)
        allocation = self._aggregate_allocation(
            instruction.result,
            instruction.result.type.element,
            instruction.rows,
            indent="  ",
        )
        result = allocation.result
        matrix_element_type = llvm_type(instruction.matrix.type.element)
        vector_element_type = llvm_type(instruction.vector.type.element)
        multiply_operator = self._element_binary_operator(instruction.result.type.element, "mul")
        add_operator = self._element_binary_operator(instruction.result.type.element, "add")
        zero = "0.0" if isinstance(instruction.result.type.element, DoubleType) else "0"
        labels = self._double_loop_labels("matrix.vector")

        matrix_field = self._synthetic_temp("matrix.vector.matrix.data.field")
        matrix_data = self._synthetic_temp("matrix.vector.matrix.data")
        vector_field = self._synthetic_temp("matrix.vector.vector.data.field")
        vector_data = self._synthetic_temp("matrix.vector.vector.data")
        result_field = self._synthetic_temp("matrix.vector.result.data.field")
        result_data = self._synthetic_temp("matrix.vector.result.data")
        row_ptr = self._synthetic_temp("matrix.vector.row.ptr")
        col_ptr = self._synthetic_temp("matrix.vector.col.ptr")
        acc_ptr = self._synthetic_temp("matrix.vector.acc.ptr")
        lines = [
            allocation.line,
            LLVMArrayRuntime.data_pointer_line(matrix_field, self._operand(instruction.matrix), indent="  "),
            f"  {matrix_data} = load ptr, ptr {matrix_field}",
            LLVMArrayRuntime.data_pointer_line(vector_field, self._operand(instruction.vector), indent="  "),
            f"  {vector_data} = load ptr, ptr {vector_field}",
            LLVMArrayRuntime.data_pointer_line(result_field, result, indent="  "),
            f"  {result_data} = load ptr, ptr {result_field}",
            f"  {row_ptr} = alloca i64",
            f"  store i64 0, ptr {row_ptr}",
            f"  {col_ptr} = alloca i64",
            f"  {acc_ptr} = alloca {result_element_type}",
            f"  br label %{labels.outer_loop}",
            f"{labels.outer_loop}:",
        ]

        row = self._synthetic_temp("matrix.vector.row")
        outer_cond = self._synthetic_temp("matrix.vector.outer.cond")
        lines.extend(
            self._double_loop_outer_check(
                row,
                row_ptr,
                outer_cond,
                instruction.rows,
                labels,
                indent="  ",
            )
            + [
                f"  store {result_element_type} {zero}, ptr {acc_ptr}",
                f"  store i64 0, ptr {col_ptr}",
                f"  br label %{labels.inner_loop}",
                f"{labels.inner_loop}:",
            ]
        )

        col = self._synthetic_temp("matrix.vector.col")
        inner_cond = self._synthetic_temp("matrix.vector.inner.cond")
        lines.extend(
            self._double_loop_inner_check(
                col,
                col_ptr,
                inner_cond,
                instruction.inner,
                labels,
                indent="  ",
            )
        )

        row_offset = self._synthetic_temp("matrix.vector.row.offset")
        matrix_index = self._synthetic_temp("matrix.vector.matrix.index")
        matrix_ptr = self._synthetic_temp("matrix.vector.matrix.elem")
        vector_ptr = self._synthetic_temp("matrix.vector.vector.elem")
        loaded_matrix = self._synthetic_temp("matrix.vector.matrix")
        loaded_vector = self._synthetic_temp("matrix.vector.vector")
        lines.extend(
            [
                f"  {row_offset} = mul i64 {row}, {instruction.inner}",
                f"  {matrix_index} = add i64 {row_offset}, {col}",
                self._element_pointer_line(matrix_ptr, matrix_element_type, matrix_data, matrix_index, indent="  "),
                self._load_element_line(loaded_matrix, matrix_element_type, matrix_ptr, indent="  "),
                self._element_pointer_line(vector_ptr, vector_element_type, vector_data, col, indent="  "),
                self._load_element_line(loaded_vector, vector_element_type, vector_ptr, indent="  "),
            ]
        )
        matrix_operand = self._coerce_scalar(
            lines,
            loaded_matrix,
            instruction.matrix.type.element,
            instruction.result.type.element,
            "matrix.vector.matrix.cast",
        )
        vector_operand = self._coerce_scalar(
            lines,
            loaded_vector,
            instruction.vector.type.element,
            instruction.result.type.element,
            "matrix.vector.vector.cast",
        )
        product = self._synthetic_temp("matrix.vector.product")
        acc_current = self._synthetic_temp("matrix.vector.acc")
        acc_next = self._synthetic_temp("matrix.vector.acc.next")
        col_next = self._synthetic_temp("matrix.vector.col.next")
        acc_final = self._synthetic_temp("matrix.vector.acc.final")
        result_ptr = self._synthetic_temp("matrix.vector.result.elem")
        row_next = self._synthetic_temp("matrix.vector.row.next")
        lines.extend(
            [
                f"  {product} = {multiply_operator} {result_element_type} {matrix_operand}, {vector_operand}",
                f"  {acc_current} = load {result_element_type}, ptr {acc_ptr}",
                f"  {acc_next} = {add_operator} {result_element_type} {acc_current}, {product}",
                f"  store {result_element_type} {acc_next}, ptr {acc_ptr}",
                f"  {col_next} = add i64 {col}, 1",
                f"  store i64 {col_next}, ptr {col_ptr}",
                f"  br label %{labels.inner_loop}",
                f"{labels.inner_exit}:",
                f"  {acc_final} = load {result_element_type}, ptr {acc_ptr}",
                self._element_pointer_line(result_ptr, result_element_type, result_data, row, indent="  "),
                self._store_element_line(result_element_type, acc_final, result_ptr, indent="  "),
                f"  {row_next} = add i64 {row}, 1",
                f"  store i64 {row_next}, ptr {row_ptr}",
                f"  br label %{labels.outer_loop}",
                f"{labels.exit}:",
            ]
        )
        return lines

    def _validate_matrix_vector_mul(self, instruction: SSAMatrixVectorMul) -> None:
        if not isinstance(instruction.result.type, VectorType):
            raise LLVMBackendError("LLVM matrix_vector_mul result must be VectorType")
        if instruction.result.type.orientation != "column":
            raise LLVMBackendError("LLVM matrix_vector_mul result must be Vector<Column>")
        if not isinstance(instruction.matrix.type, MatrixType) or not isinstance(instruction.vector.type, VectorType):
            raise LLVMBackendError("LLVM matrix_vector_mul expects matrix and vector operands")
        if instruction.vector.type.orientation != "column":
            raise LLVMBackendError("LLVM matrix_vector_mul only supports Matrix * Vector<Column>")
        if instruction.rows <= 0 or instruction.inner <= 0:
            raise LLVMBackendError("LLVM matrix_vector_mul requires positive dimensions")
        if not isinstance(instruction.result.type.element, (IntType, DoubleType)):
            raise LLVMBackendError("LLVM matrix_vector_mul only supports int or double results")
        if not isinstance(instruction.matrix.type.element, (IntType, DoubleType)):
            raise LLVMBackendError("LLVM matrix_vector_mul only supports int or double matrix elements")
        if not isinstance(instruction.vector.type.element, (IntType, DoubleType)):
            raise LLVMBackendError("LLVM matrix_vector_mul only supports int or double vector elements")

    def _print_vector_matrix_mul(self, instruction: SSAVectorMatrixMul) -> list[str]:
        self._validate_vector_matrix_mul(instruction)
        self._uses_array_type = True
        self._uses_array_allocation = True

        result_element_type = llvm_type(instruction.result.type.element)
        allocation = self._aggregate_allocation(
            instruction.result,
            instruction.result.type.element,
            instruction.cols,
            indent="  ",
        )
        result = allocation.result
        vector_element_type = llvm_type(instruction.vector.type.element)
        matrix_element_type = llvm_type(instruction.matrix.type.element)
        multiply_operator = self._element_binary_operator(instruction.result.type.element, "mul")
        add_operator = self._element_binary_operator(instruction.result.type.element, "add")
        zero = "0.0" if isinstance(instruction.result.type.element, DoubleType) else "0"
        labels = self._double_loop_labels("vector.matrix")

        vector_field = self._synthetic_temp("vector.matrix.vector.data.field")
        vector_data = self._synthetic_temp("vector.matrix.vector.data")
        matrix_field = self._synthetic_temp("vector.matrix.matrix.data.field")
        matrix_data = self._synthetic_temp("vector.matrix.matrix.data")
        result_field = self._synthetic_temp("vector.matrix.result.data.field")
        result_data = self._synthetic_temp("vector.matrix.result.data")
        col_ptr = self._synthetic_temp("vector.matrix.col.ptr")
        row_ptr = self._synthetic_temp("vector.matrix.row.ptr")
        acc_ptr = self._synthetic_temp("vector.matrix.acc.ptr")
        lines = [
            allocation.line,
            LLVMArrayRuntime.data_pointer_line(vector_field, self._operand(instruction.vector), indent="  "),
            f"  {vector_data} = load ptr, ptr {vector_field}",
            LLVMArrayRuntime.data_pointer_line(matrix_field, self._operand(instruction.matrix), indent="  "),
            f"  {matrix_data} = load ptr, ptr {matrix_field}",
            LLVMArrayRuntime.data_pointer_line(result_field, result, indent="  "),
            f"  {result_data} = load ptr, ptr {result_field}",
            f"  {col_ptr} = alloca i64",
            f"  store i64 0, ptr {col_ptr}",
            f"  {row_ptr} = alloca i64",
            f"  {acc_ptr} = alloca {result_element_type}",
            f"  br label %{labels.outer_loop}",
            f"{labels.outer_loop}:",
        ]

        col = self._synthetic_temp("vector.matrix.col")
        outer_cond = self._synthetic_temp("vector.matrix.outer.cond")
        lines.extend(
            self._double_loop_outer_check(
                col,
                col_ptr,
                outer_cond,
                instruction.cols,
                labels,
                indent="  ",
            )
            + [
                f"  store {result_element_type} {zero}, ptr {acc_ptr}",
                f"  store i64 0, ptr {row_ptr}",
                f"  br label %{labels.inner_loop}",
                f"{labels.inner_loop}:",
            ]
        )

        row = self._synthetic_temp("vector.matrix.row")
        inner_cond = self._synthetic_temp("vector.matrix.inner.cond")
        lines.extend(
            self._double_loop_inner_check(
                row,
                row_ptr,
                inner_cond,
                instruction.rows,
                labels,
                indent="  ",
            )
        )

        row_offset = self._synthetic_temp("vector.matrix.row.offset")
        matrix_index = self._synthetic_temp("vector.matrix.matrix.index")
        vector_ptr = self._synthetic_temp("vector.matrix.vector.elem")
        matrix_ptr = self._synthetic_temp("vector.matrix.matrix.elem")
        loaded_vector = self._synthetic_temp("vector.matrix.vector")
        loaded_matrix = self._synthetic_temp("vector.matrix.matrix")
        lines.extend(
            [
                f"  {row_offset} = mul i64 {row}, {instruction.cols}",
                f"  {matrix_index} = add i64 {row_offset}, {col}",
                self._element_pointer_line(vector_ptr, vector_element_type, vector_data, row, indent="  "),
                self._load_element_line(loaded_vector, vector_element_type, vector_ptr, indent="  "),
                self._element_pointer_line(matrix_ptr, matrix_element_type, matrix_data, matrix_index, indent="  "),
                self._load_element_line(loaded_matrix, matrix_element_type, matrix_ptr, indent="  "),
            ]
        )
        vector_operand = self._coerce_scalar(
            lines,
            loaded_vector,
            instruction.vector.type.element,
            instruction.result.type.element,
            "vector.matrix.vector.cast",
        )
        matrix_operand = self._coerce_scalar(
            lines,
            loaded_matrix,
            instruction.matrix.type.element,
            instruction.result.type.element,
            "vector.matrix.matrix.cast",
        )
        product = self._synthetic_temp("vector.matrix.product")
        acc_current = self._synthetic_temp("vector.matrix.acc")
        acc_next = self._synthetic_temp("vector.matrix.acc.next")
        row_next = self._synthetic_temp("vector.matrix.row.next")
        acc_final = self._synthetic_temp("vector.matrix.acc.final")
        result_ptr = self._synthetic_temp("vector.matrix.result.elem")
        col_next = self._synthetic_temp("vector.matrix.col.next")
        lines.extend(
            [
                f"  {product} = {multiply_operator} {result_element_type} {vector_operand}, {matrix_operand}",
                f"  {acc_current} = load {result_element_type}, ptr {acc_ptr}",
                f"  {acc_next} = {add_operator} {result_element_type} {acc_current}, {product}",
                f"  store {result_element_type} {acc_next}, ptr {acc_ptr}",
                f"  {row_next} = add i64 {row}, 1",
                f"  store i64 {row_next}, ptr {row_ptr}",
                f"  br label %{labels.inner_loop}",
                f"{labels.inner_exit}:",
                f"  {acc_final} = load {result_element_type}, ptr {acc_ptr}",
                self._element_pointer_line(result_ptr, result_element_type, result_data, col, indent="  "),
                self._store_element_line(result_element_type, acc_final, result_ptr, indent="  "),
                f"  {col_next} = add i64 {col}, 1",
                f"  store i64 {col_next}, ptr {col_ptr}",
                f"  br label %{labels.outer_loop}",
                f"{labels.exit}:",
            ]
        )
        return lines

    def _validate_vector_matrix_mul(self, instruction: SSAVectorMatrixMul) -> None:
        if not isinstance(instruction.result.type, VectorType):
            raise LLVMBackendError("LLVM vector_matrix_mul result must be VectorType")
        if instruction.result.type.orientation != "row":
            raise LLVMBackendError("LLVM vector_matrix_mul result must be Vector<Row>")
        if not isinstance(instruction.vector.type, VectorType) or not isinstance(instruction.matrix.type, MatrixType):
            raise LLVMBackendError("LLVM vector_matrix_mul expects vector and matrix operands")
        if instruction.vector.type.orientation != "row":
            raise LLVMBackendError("LLVM vector_matrix_mul only supports Vector<Row> * Matrix")
        if instruction.rows <= 0 or instruction.cols <= 0:
            raise LLVMBackendError("LLVM vector_matrix_mul requires positive dimensions")
        if not isinstance(instruction.result.type.element, (IntType, DoubleType)):
            raise LLVMBackendError("LLVM vector_matrix_mul only supports int or double results")
        if not isinstance(instruction.vector.type.element, (IntType, DoubleType)):
            raise LLVMBackendError("LLVM vector_matrix_mul only supports int or double vector elements")
        if not isinstance(instruction.matrix.type.element, (IntType, DoubleType)):
            raise LLVMBackendError("LLVM vector_matrix_mul only supports int or double matrix elements")

    def _print_contiguous_new(
        self,
        result_value: SSAValue,
        element_ir_type: object,
        elements: tuple[SSAValue, ...],
    ) -> str:
        self._uses_array_type = True
        self._uses_array_allocation = True

        element_type = llvm_type(element_ir_type)
        length = len(elements)
        allocation = self._aggregate_allocation(result_value, element_ir_type, length)
        result = allocation.result
        lines = [allocation.line]
        data = self._synthetic_temp("array.data")
        lines.extend(self._array_data_pointer(data, result))

        def emit_element(index: int) -> None:
            element = elements[index]
            element_ptr = self._synthetic_temp("array.elem")
            lines.append(
                self._element_pointer_line(element_ptr, element_type, data, index)
            )
            lines.append(self._store_element_line(element_type, self._operand(element), element_ptr))

        self._for_each_element(length, emit_element)
        return "\n  ".join(lines)

    def _print_contiguous_binary(
        self,
        result_value: SSAValue,
        left_value: SSAValue,
        right_value: SSAValue,
        element_ir_type: object,
        length: int,
        operator_name: str,
    ) -> list[str]:
        self._uses_array_type = True
        self._uses_array_allocation = True

        element_type = llvm_type(element_ir_type)
        allocation = self._aggregate_allocation(result_value, element_ir_type, length)
        result = allocation.result
        operator = self._element_binary_operator(element_ir_type, operator_name)
        lines = [allocation.line]

        left_data = self._synthetic_temp(f"{operator_name}.left.data")
        right_data = self._synthetic_temp(f"{operator_name}.right.data")
        result_data = self._synthetic_temp(f"{operator_name}.result.data")
        lines.extend(self._array_data_pointer(left_data, self._operand(left_value)))
        lines.extend(self._array_data_pointer(right_data, self._operand(right_value)))
        lines.extend(self._array_data_pointer(result_data, result))

        def emit_element(index: int) -> None:
            left_ptr = self._synthetic_temp(f"{operator_name}.left.elem")
            right_ptr = self._synthetic_temp(f"{operator_name}.right.elem")
            result_ptr = self._synthetic_temp(f"{operator_name}.result.elem")
            loaded_left = self._synthetic_temp(f"{operator_name}.left")
            loaded_right = self._synthetic_temp(f"{operator_name}.right")
            result_element = self._synthetic_temp(f"{operator_name}.value")
            lines.append(
                self._element_pointer_line(left_ptr, element_type, left_data, index)
            )
            lines.append(self._load_element_line(loaded_left, element_type, left_ptr))
            lines.append(
                self._element_pointer_line(right_ptr, element_type, right_data, index)
            )
            lines.append(self._load_element_line(loaded_right, element_type, right_ptr))
            lines.append(
                f"{result_element} = {operator} {element_type} {loaded_left}, {loaded_right}"
            )
            lines.append(
                self._element_pointer_line(result_ptr, element_type, result_data, index)
            )
            lines.append(self._store_element_line(element_type, result_element, result_ptr))

        self._for_each_element(length, emit_element)

        return lines

    def _print_contiguous_scale(
        self,
        result_value: SSAValue,
        aggregate_value: SSAValue,
        scalar_value: SSAValue,
        element_ir_type: object,
        length: int,
        operation_name: str,
    ) -> list[str]:
        self._uses_array_type = True
        self._uses_array_allocation = True

        element_type = llvm_type(element_ir_type)
        allocation = self._aggregate_allocation(result_value, element_ir_type, length)
        result = allocation.result
        operator = self._element_binary_operator(element_ir_type, "mul")
        scalar = self._operand(scalar_value)
        lines = [allocation.line]

        aggregate_data = self._synthetic_temp(f"{operation_name}.source.data")
        result_data = self._synthetic_temp(f"{operation_name}.result.data")
        lines.extend(self._array_data_pointer(aggregate_data, self._operand(aggregate_value)))
        lines.extend(self._array_data_pointer(result_data, result))

        def emit_element(index: int) -> None:
            aggregate_ptr = self._synthetic_temp(f"{operation_name}.source.elem")
            result_ptr = self._synthetic_temp(f"{operation_name}.result.elem")
            loaded_value = self._synthetic_temp(f"{operation_name}.source")
            result_element = self._synthetic_temp(f"{operation_name}.value")
            lines.append(
                self._element_pointer_line(aggregate_ptr, element_type, aggregate_data, index)
            )
            lines.append(self._load_element_line(loaded_value, element_type, aggregate_ptr))
            lines.append(
                f"{result_element} = {operator} {element_type} {loaded_value}, {scalar}"
            )
            lines.append(
                self._element_pointer_line(result_ptr, element_type, result_data, index)
            )
            lines.append(self._store_element_line(element_type, result_element, result_ptr))

        self._for_each_element(length, emit_element)

        return lines

    def _print_array_get(self, instruction: SSAArrayGet) -> list[str]:
        if not isinstance(instruction.array.type, ArrayType):
            raise LLVMBackendError("LLVM array_get expects an ArrayType source")
        self._uses_array_type = True
        self._uses_array_indexing = True

        result = self._new_temp(instruction.result)
        element_type = llvm_type(instruction.result.type)
        element_ptr = self._array_element_pointer(
            self._operand(instruction.array),
            instruction.index,
            instruction.result.type,
            check_bounds=True,
        )
        return element_ptr.lines + [
            f"{result} = load {element_type}, ptr {element_ptr.value}"
        ]

    def _print_array_slice(self, instruction: SSAArraySlice) -> str:
        if not isinstance(instruction.array.type, ArrayType):
            raise LLVMBackendError("LLVM array_slice expects an ArrayType source")
        self._uses_array_type = True
        self._uses_array_allocation = True
        self._uses_array_slicing = True
        result = self._new_temp(instruction.result)
        element_size = self._sizeof(instruction.array.type.element)
        return (
            f"{result} = call ptr @aether_array_slice(ptr {self._operand(instruction.array)}, "
            f"i32 {self._operand(instruction.start)}, i32 {self._operand(instruction.end)}, "
            f"i64 {element_size})"
        )

    def _print_list_get(self, instruction: SSAListGet) -> list[str]:
        if not isinstance(instruction.list_value.type, ListType):
            raise LLVMBackendError("LLVM list_get expects a ListType source")
        self._uses_list_type = True
        self._uses_list_indexing = True

        result = self._new_temp(instruction.result)
        element_type = llvm_type(instruction.result.type)
        element_ptr = self._list_element_pointer(
            self._operand(instruction.list_value),
            instruction.index,
            instruction.result.type,
        )
        return element_ptr.lines + [
            f"{result} = load {element_type}, ptr {element_ptr.value}"
        ]

    def _print_vector_get(self, instruction: SSAVectorGet) -> list[str]:
        if not isinstance(instruction.vector.type, VectorType):
            raise LLVMBackendError("LLVM vector_get expects a VectorType source")
        self._uses_array_type = True
        self._uses_vector_indexing = True

        result = self._new_temp(instruction.result)
        element_type = llvm_type(instruction.result.type)
        element_ptr = self._vector_element_pointer(
            self._operand(instruction.vector),
            instruction.index,
            instruction.result.type,
        )
        return element_ptr.lines + [
            f"{result} = load {element_type}, ptr {element_ptr.value}"
        ]

    def _print_matrix_get(self, instruction: SSAMatrixGet) -> list[str]:
        if not isinstance(instruction.matrix.type, MatrixType):
            raise LLVMBackendError("LLVM matrix_get expects a MatrixType source")
        if instruction.cols <= 0:
            raise LLVMBackendError("LLVM matrix_get requires a positive column count")
        self._uses_array_type = True
        self._uses_matrix_indexing = True

        result = self._new_temp(instruction.result)
        element_type = llvm_type(instruction.result.type)
        element_ptr = self._matrix_element_pointer(
            self._operand(instruction.matrix),
            instruction.row,
            instruction.column,
            instruction.cols,
            instruction.result.type,
        )
        return element_ptr.lines + [
            f"{result} = load {element_type}, ptr {element_ptr.value}"
        ]

    def _print_array_set(self, instruction: SSAArraySet) -> list[str]:
        if not isinstance(instruction.array.type, ArrayType):
            raise LLVMBackendError("LLVM array_set expects an ArrayType source")
        self._uses_array_type = True
        self._uses_array_indexing = True

        element_type = llvm_type(instruction.value.type)
        element_ptr = self._array_element_pointer(
            self._operand(instruction.array),
            instruction.index,
            instruction.value.type,
            check_bounds=True,
        )
        return element_ptr.lines + [
            f"store {element_type} {self._operand(instruction.value)}, ptr {element_ptr.value}"
        ]

    def _print_vector_set(self, instruction: SSAVectorSet) -> list[str]:
        if not isinstance(instruction.vector.type, VectorType):
            raise LLVMBackendError("LLVM vector_set expects a VectorType source")
        if instruction.value.type != instruction.vector.type.element:
            raise LLVMBackendError("LLVM vector_set value type must match vector element type")
        self._uses_array_type = True
        self._uses_vector_indexing = True

        element_type = llvm_type(instruction.value.type)
        element_ptr = self._vector_element_pointer(
            self._operand(instruction.vector),
            instruction.index,
            instruction.value.type,
        )
        return element_ptr.lines + [
            f"store {element_type} {self._operand(instruction.value)}, ptr {element_ptr.value}"
        ]

    def _print_list_set(self, instruction: SSAListSet) -> list[str]:
        if not isinstance(instruction.list_value.type, ListType):
            raise LLVMBackendError("LLVM list_set expects a ListType source")
        if instruction.value.type != instruction.list_value.type.element:
            raise LLVMBackendError("LLVM list_set value type must match list element type")
        self._uses_list_type = True
        self._uses_list_indexing = True

        element_type = llvm_type(instruction.value.type)
        element_ptr = self._list_element_pointer(
            self._operand(instruction.list_value),
            instruction.index,
            instruction.value.type,
        )
        return element_ptr.lines + [
            f"store {element_type} {self._operand(instruction.value)}, ptr {element_ptr.value}"
        ]

    def _print_matrix_set(self, instruction: SSAMatrixSet) -> list[str]:
        if not isinstance(instruction.matrix.type, MatrixType):
            raise LLVMBackendError("LLVM matrix_set expects a MatrixType source")
        if instruction.cols <= 0:
            raise LLVMBackendError("LLVM matrix_set requires a positive column count")
        if instruction.value.type != instruction.matrix.type.element:
            raise LLVMBackendError("LLVM matrix_set value type must match matrix element type")
        self._uses_array_type = True
        self._uses_matrix_indexing = True

        element_type = llvm_type(instruction.value.type)
        element_ptr = self._matrix_element_pointer(
            self._operand(instruction.matrix),
            instruction.row,
            instruction.column,
            instruction.cols,
            instruction.value.type,
        )
        return element_ptr.lines + [
            f"store {element_type} {self._operand(instruction.value)}, ptr {element_ptr.value}"
        ]

    def _print_array_length(self, instruction: SSAArrayLength) -> list[str]:
        self._uses_array_type = True
        self._uses_array_length_conversion = True
        result = self._new_temp(instruction.result)
        length64 = self._synthetic_temp("array.len64")
        lines = self._array_length64(length64, self._operand(instruction.array))
        lines.append(f"{result} = call i32 @aether_array_length_to_int(i64 {length64})")
        return lines

    def _print_list_length(self, instruction: SSAListLength) -> list[str]:
        if not isinstance(instruction.list_value.type, ListType):
            raise LLVMBackendError("LLVM list_length expects a ListType source")
        self._uses_list_type = True
        self._uses_list_length_conversion = True
        result = self._new_temp(instruction.result)
        length64 = self._synthetic_temp("list.len64")
        lines = self._list_length64(length64, self._operand(instruction.list_value))
        lines.append(f"{result} = call i32 @aether_list_length_to_int(i64 {length64})")
        return lines

    def _print_list_is_empty(self, instruction: SSAListIsEmpty) -> list[str]:
        if not isinstance(instruction.list_value.type, ListType):
            raise LLVMBackendError("LLVM list_is_empty expects a ListType source")
        self._uses_list_type = True
        result = self._new_temp(instruction.result)
        length64 = self._synthetic_temp("list.empty.len64")
        lines = self._list_length64(length64, self._operand(instruction.list_value))
        lines.append(f"{result} = icmp eq i64 {length64}, 0")
        return lines

    def _print_vector_length(self, instruction: SSAVectorLength) -> list[str]:
        if not isinstance(instruction.vector.type, VectorType):
            raise LLVMBackendError("LLVM vector_length expects a VectorType source")
        self._uses_array_type = True
        result = self._new_temp(instruction.result)
        length64 = self._synthetic_temp("vector.len64")
        lines = self._array_length64(length64, self._operand(instruction.vector))
        lines.append(f"{result} = trunc i64 {length64} to i32")
        return lines

    def _print_matrix_rows(self, instruction: SSAMatrixRows) -> str:
        if not isinstance(instruction.matrix.type, MatrixType):
            raise LLVMBackendError("LLVM matrix_rows expects a MatrixType source")
        result = self._new_temp(instruction.result)
        return f"{result} = add i32 0, {instruction.rows}"

    def _print_matrix_columns(self, instruction: SSAMatrixColumns) -> str:
        if not isinstance(instruction.matrix.type, MatrixType):
            raise LLVMBackendError("LLVM matrix_columns expects a MatrixType source")
        result = self._new_temp(instruction.result)
        return f"{result} = add i32 0, {instruction.columns}"

    @dataclass(frozen=True)
    class _ArrayPointer:
        value: str
        lines: list[str]

    @dataclass(frozen=True)
    class _AggregateAllocation:
        result: str
        line: str

    @dataclass(frozen=True)
    class _LoopLabels:
        loop: str
        body: str
        exit: str

    @dataclass(frozen=True)
    class _DoubleLoopLabels:
        outer_loop: str
        outer_body: str
        inner_loop: str
        inner_body: str
        inner_exit: str
        exit: str

    def _aggregate_allocation(
        self,
        result_value: SSAValue,
        element_ir_type: object,
        length: int,
        *,
        indent: str = "",
    ) -> _AggregateAllocation:
        result = self._new_temp(result_value)
        element_size = self._sizeof(element_ir_type)
        return self._AggregateAllocation(
            result,
            f"{indent}{result} = call ptr @aether_array_new(i64 {element_size}, i64 {length})",
        )

    def _linear_loop_labels(self, prefix: str) -> _LoopLabels:
        label_id = self._next_synthetic_temp
        self._next_synthetic_temp += 1
        return self._LoopLabels(
            f"{prefix}.loop.{label_id}",
            f"{prefix}.body.{label_id}",
            f"{prefix}.exit.{label_id}",
        )

    def _double_loop_labels(self, prefix: str) -> _DoubleLoopLabels:
        label_id = self._next_synthetic_temp
        self._next_synthetic_temp += 1
        return self._DoubleLoopLabels(
            f"{prefix}.outer.loop.{label_id}",
            f"{prefix}.outer.body.{label_id}",
            f"{prefix}.inner.loop.{label_id}",
            f"{prefix}.inner.body.{label_id}",
            f"{prefix}.inner.exit.{label_id}",
            f"{prefix}.exit.{label_id}",
        )

    def _linear_loop_check(
        self,
        index: str,
        index_ptr: str,
        condition: str,
        limit: int,
        labels: _LoopLabels,
        *,
        indent: str = "",
    ) -> list[str]:
        return [
            f"{indent}{index} = load i64, ptr {index_ptr}",
            f"{indent}{condition} = icmp slt i64 {index}, {limit}",
            f"{indent}br i1 {condition}, label %{labels.body}, label %{labels.exit}",
            f"{labels.body}:",
        ]

    def _double_loop_outer_check(
        self,
        index: str,
        index_ptr: str,
        condition: str,
        limit: int,
        labels: _DoubleLoopLabels,
        *,
        indent: str = "",
    ) -> list[str]:
        return [
            f"{indent}{index} = load i64, ptr {index_ptr}",
            f"{indent}{condition} = icmp slt i64 {index}, {limit}",
            f"{indent}br i1 {condition}, label %{labels.outer_body}, label %{labels.exit}",
            f"{labels.outer_body}:",
        ]

    def _double_loop_inner_check(
        self,
        index: str,
        index_ptr: str,
        condition: str,
        limit: int,
        labels: _DoubleLoopLabels,
        *,
        indent: str = "",
    ) -> list[str]:
        return [
            f"{indent}{index} = load i64, ptr {index_ptr}",
            f"{indent}{condition} = icmp slt i64 {index}, {limit}",
            f"{indent}br i1 {condition}, label %{labels.inner_body}, label %{labels.inner_exit}",
            f"{labels.inner_body}:",
        ]

    @staticmethod
    def _for_each_element(length: int, emit: Callable[[int], None]) -> None:
        for index in range(length):
            emit(index)

    @staticmethod
    def _for_each_matrix_element(
        rows: int,
        cols: int,
        emit: Callable[[int, int], None],
    ) -> None:
        for row in range(rows):
            for col in range(cols):
                emit(row, col)

    @staticmethod
    def _element_pointer_line(
        result: str,
        element_type: str,
        data: str,
        index: int | str,
        *,
        indent: str = "",
    ) -> str:
        return f"{indent}{result} = getelementptr {element_type}, ptr {data}, i64 {index}"

    @staticmethod
    def _load_element_line(
        result: str,
        element_type: str,
        pointer: str,
        *,
        indent: str = "",
    ) -> str:
        return f"{indent}{result} = load {element_type}, ptr {pointer}"

    @staticmethod
    def _store_element_line(
        element_type: str,
        value: str,
        pointer: str,
        *,
        indent: str = "",
    ) -> str:
        return f"{indent}store {element_type} {value}, ptr {pointer}"

    def _array_element_pointer(
        self,
        array: str,
        index: SSAValue,
        element_type: object,
        *,
        check_bounds: bool = False,
    ) -> _ArrayPointer:
        data = self._synthetic_temp("array.data")
        index64 = self._synthetic_temp("array.index64")
        element_ptr = self._synthetic_temp("array.elem")
        llvm_element_type = llvm_type(element_type)
        lines = [LLVMArrayRuntime.index64_line(index64, self._operand(index))]
        if check_bounds:
            lines.append(f"call void @aether_array_check_index(ptr {array}, i64 {index64})")
        lines.extend(self._array_data_pointer(data, array))
        lines.append(
            f"{element_ptr} = getelementptr {llvm_element_type}, ptr {data}, i64 {index64}"
        )
        return self._ArrayPointer(element_ptr, lines)

    def _list_element_pointer(
        self,
        list_value: str,
        index: SSAValue,
        element_type: object,
    ) -> _ArrayPointer:
        data = self._synthetic_temp("list.data")
        index64 = self._synthetic_temp("list.index64")
        element_ptr = self._synthetic_temp("list.elem")
        llvm_element_type = llvm_type(element_type)
        lines = [self._list_index64_line(index64, self._operand(index))]
        lines.append(f"call void @aether_list_check_index(ptr {list_value}, i64 {index64})")
        lines.extend(self._list_data_pointer(data, list_value))
        lines.append(
            f"{element_ptr} = getelementptr {llvm_element_type}, ptr {data}, i64 {index64}"
        )
        return self._ArrayPointer(element_ptr, lines)

    def _vector_element_pointer(
        self,
        vector: str,
        index: SSAValue,
        element_type: object,
    ) -> _ArrayPointer:
        data = self._synthetic_temp("vector.data")
        public_index64 = self._synthetic_temp("vector.index64")
        offset = self._synthetic_temp("vector.offset")
        element_ptr = self._synthetic_temp("vector.elem")
        llvm_element_type = llvm_type(element_type)
        lines = [LLVMArrayRuntime.index64_line(public_index64, self._operand(index))]
        lines.append(
            f"{offset} = call i64 @aether_vector_check_index(ptr {vector}, i64 {public_index64})"
        )
        lines.extend(self._array_data_pointer(data, vector))
        lines.append(
            f"{element_ptr} = getelementptr {llvm_element_type}, ptr {data}, i64 {offset}"
        )
        return self._ArrayPointer(element_ptr, lines)

    def _matrix_element_pointer(
        self,
        matrix: str,
        row: SSAValue,
        column: SSAValue,
        cols: int,
        element_type: object,
    ) -> _ArrayPointer:
        data = self._synthetic_temp("matrix.data")
        row64 = self._synthetic_temp("matrix.row64")
        column64 = self._synthetic_temp("matrix.column64")
        linear_index = self._synthetic_temp("matrix.index")
        element_ptr = self._synthetic_temp("matrix.elem")
        llvm_element_type = llvm_type(element_type)
        lines = [f"{row64} = sext i32 {self._operand(row)} to i64"]
        lines.append(f"{column64} = sext i32 {self._operand(column)} to i64")
        lines.append(
            f"{linear_index} = call i64 @aether_matrix_check_index("
            f"ptr {matrix}, i64 {row64}, i64 {column64}, i64 {cols})"
        )
        lines.extend(self._array_data_pointer(data, matrix))
        lines.append(
            f"{element_ptr} = getelementptr {llvm_element_type}, ptr {data}, i64 {linear_index}"
        )
        return self._ArrayPointer(element_ptr, lines)

    def _array_data_pointer(self, result: str, array: str) -> list[str]:
        field_ptr = self._synthetic_temp("array.data.field")
        return [
            LLVMArrayRuntime.data_pointer_line(field_ptr, array),
            f"{result} = load ptr, ptr {field_ptr}",
        ]

    def _list_field_pointer_line(
        self,
        result: str,
        list_value: str,
        field_index: int,
    ) -> str:
        return (
            f"{result} = getelementptr {self._LIST_STRUCT_TYPE}, "
            f"ptr {list_value}, i32 0, i32 {field_index}"
        )

    def _load_list_data(
        self,
        result: str,
        list_value: str,
        field_ptr: str,
    ) -> list[str]:
        return [
            self._list_field_pointer_line(field_ptr, list_value, 2),
            f"{result} = load ptr, ptr {field_ptr}",
        ]

    def _list_data_pointer(self, result: str, list_value: str) -> list[str]:
        return self._load_list_data(
            result,
            list_value,
            self._synthetic_temp("list.data.field"),
        )

    def _array_length64(self, result: str, array: str) -> list[str]:
        field_ptr = self._synthetic_temp("array.len.field")
        return [
            LLVMArrayRuntime.length_pointer_line(field_ptr, array),
            f"{result} = load i64, ptr {field_ptr}",
        ]

    def _list_length64(self, result: str, list_value: str) -> list[str]:
        field_ptr = self._synthetic_temp("list.len.field")
        return [
            self._list_field_pointer_line(field_ptr, list_value, 0),
            f"{result} = load i64, ptr {field_ptr}",
        ]

    def _store_list_length(
        self,
        value: str,
        list_value: str,
        field_ptr: str,
    ) -> list[str]:
        return [
            self._list_field_pointer_line(field_ptr, list_value, 0),
            f"store i64 {value}, ptr {field_ptr}",
        ]

    @staticmethod
    def _list_index64_line(result: str, index: str) -> str:
        return f"{result} = sext i32 {index} to i64"

    def _sizeof(self, type_: object) -> int:
        if isinstance(type_, (IntType, BoolType)):
            return 4 if isinstance(type_, IntType) else 1
        if isinstance(type_, DoubleType):
            return 8
        if isinstance(type_, (StringType, ArrayType, ListType, VectorType, MatrixType)):
            return 8
        raise LLVMBackendError(f"LLVM backend does not know the size of {type_}")

    @staticmethod
    def _element_binary_operator(type_: object, operator: str) -> str:
        operations = {
            (IntType, "add"): "add",
            (IntType, "sub"): "sub",
            (IntType, "mul"): "mul",
            (DoubleType, "add"): "fadd",
            (DoubleType, "sub"): "fsub",
            (DoubleType, "mul"): "fmul",
        }
        if isinstance(type_, IntType):
            selected = operations.get((IntType, operator))
            if selected is not None:
                return selected
        if isinstance(type_, DoubleType):
            selected = operations.get((DoubleType, operator))
            if selected is not None:
                return selected
        raise LLVMBackendError(
            f"LLVM backend does not support vector/matrix {operator} for {type_}"
        )

    def _operand(self, value: SSAValue) -> str:
        key = self._key(value)
        if key in self._constants:
            return self._constants[key]
        if key in self._values:
            return self._values[key]
        return self._local_name(value.name)

    def _new_temp(self, value: SSAValue) -> str:
        existing = self._values.get(self._key(value))
        if existing is not None:
            return existing
        return self._reserve_temp(value)

    def _reserve_temp(self, value: SSAValue) -> str:
        key = self._key(value)
        existing = self._values.get(key)
        if existing is not None:
            return existing
        name = f"%{self._next_temp}"
        self._next_temp += 1
        self._values[key] = name
        return name

    def _synthetic_temp(self, prefix: str) -> str:
        name = f"%{prefix}.{self._next_synthetic_temp}"
        self._next_synthetic_temp += 1
        return name

    def _literal(self, value: Any, result: SSAValue) -> str:
        if isinstance(result.type, IntType):
            if isinstance(value, bool) or not isinstance(value, int):
                raise LLVMBackendError(
                    "LLVM backend does not support non-int SSAConst values"
                )
            return str(value)
        if isinstance(result.type, BoolType):
            if not isinstance(value, bool):
                raise LLVMBackendError(
                    "LLVM backend does not support non-bool SSAConst values"
                )
            return "1" if value else "0"
        if isinstance(result.type, DoubleType):
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise LLVMBackendError(
                    "LLVM backend does not support non-double SSAConst values"
                )
            return self._double_literal(float(value))
        if isinstance(result.type, StringType):
            if not isinstance(value, str):
                raise LLVMBackendError(
                    "LLVM backend does not support non-string SSAConst values"
                )
            return self._string_global(value).name
        raise LLVMBackendError(
            f"LLVM backend does not support SSAConst of type {result.type}"
        )

    def _string_global(self, value: str) -> _StringGlobal:
        existing = self._string_globals_by_value.get(value)
        if existing is not None:
            return existing

        encoded = value.encode("utf-8") + b"\x00"
        global_ = _StringGlobal(
            name=f"@.str.{self._next_string_global}",
            size=len(encoded),
            initializer=self._escape_string_initializer(encoded),
        )
        self._next_string_global += 1
        self._string_globals_by_value[value] = global_
        return global_

    @staticmethod
    def _print_string_global(global_: _StringGlobal) -> str:
        return (
            f"{global_.name} = private unnamed_addr constant "
            f"[{global_.size} x i8] c\"{global_.initializer}\""
        )

    @staticmethod
    def _escape_string_initializer(value: bytes) -> str:
        chunks: list[str] = []
        for byte in value:
            if byte in {0x22, 0x5C} or byte < 0x20 or byte > 0x7E:
                chunks.append(f"\\{byte:02X}")
            else:
                chunks.append(chr(byte))
        return "".join(chunks)

    @staticmethod
    def _double_literal(value: float) -> str:
        literal = repr(value)
        if "e" in literal or "E" in literal:
            return format(value, ".17e")
        if "." not in literal:
            return f"{literal}.0"
        return literal

    @classmethod
    def _parameter_name(cls, parameter: SSAParameter) -> str:
        raw = cls._strip_percent(parameter.name)
        if raw.isdigit():
            return f"%arg{raw}"
        return cls._local_name(raw)

    @classmethod
    def _local_name(cls, name: str) -> str:
        raw = cls._strip_percent(name)
        if not raw:
            raise LLVMBackendError("LLVM backend does not support empty SSA value names")
        if cls._IDENTIFIER_RE.match(raw) or raw.isdigit():
            return f"%{raw}"
        raise LLVMBackendError(f"LLVM backend does not support SSA value name '{name}'")

    @classmethod
    def _label_operand(cls, name: str) -> str:
        raw = cls._strip_percent(name)
        if not raw:
            raise LLVMBackendError("LLVM backend does not support empty block labels")
        if cls._IDENTIFIER_RE.match(raw) or raw.isdigit():
            return f"label %{raw}"
        raise LLVMBackendError(f"LLVM backend does not support block label '{name}'")

    @classmethod
    def _label_definition(cls, name: str) -> str:
        raw = cls._strip_percent(name)
        if not raw:
            raise LLVMBackendError("LLVM backend does not support empty block labels")
        if cls._IDENTIFIER_RE.match(raw) or raw.isdigit():
            return f"{raw}:"
        raise LLVMBackendError(f"LLVM backend does not support block label '{name}'")

    @classmethod
    def _label_name(cls, name: str) -> str:
        raw = cls._strip_percent(name)
        if not raw:
            raise LLVMBackendError("LLVM backend does not support empty block labels")
        if cls._IDENTIFIER_RE.match(raw) or raw.isdigit():
            return raw
        raise LLVMBackendError(f"LLVM backend does not support block label '{name}'")

    @staticmethod
    def _global_name(name: str) -> str:
        raw = name[1:] if name.startswith("@") else name
        if not raw:
            raise LLVMBackendError("LLVM backend does not support empty function names")
        return f"@{raw}"

    @staticmethod
    def _strip_percent(name: str) -> str:
        return name[1:] if name.startswith("%") else name

    @staticmethod
    def _key(value: SSAValue) -> str:
        return value.name[1:] if value.name.startswith("%") else value.name

    @staticmethod
    def _unsupported(feature: str) -> None:
        raise LLVMBackendError(f"LLVM backend does not support {feature}")


def print_llvm(module: SSAModule) -> str:
    return LLVMPrinter().print_module(module)
