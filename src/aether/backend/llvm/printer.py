from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

from aether.ir.types import ArrayType, BoolType, DoubleType, IntType, MatrixType, StringType, VectorType, VoidType
from aether.ssa.model import (
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

from .types import LLVMBackendError, llvm_type


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
    _ARRAY_STRUCT_TYPE = "%AetherArray"

    def print_module(self, module: SSAModule) -> str:
        self._string_globals_by_value: dict[str, _StringGlobal] = {}
        self._next_string_global = 0
        self._uses_array_type = False
        self._uses_array_allocation = False

        functions = [self._print_function(function) for function in module.functions]
        globals_ = [
            self._print_string_global(global_)
            for global_ in self._string_globals_by_value.values()
        ]
        runtime = self._runtime_declarations()
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
        if isinstance(instruction, SSAArrayNew):
            return self._print_array_new(instruction)
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
        if isinstance(instruction, SSAVectorSet):
            return "\n  ".join(self._print_vector_set(instruction))
        if isinstance(instruction, SSAMatrixSet):
            return "\n  ".join(self._print_matrix_set(instruction))
        if isinstance(instruction, SSAArrayLength):
            return "\n  ".join(self._print_array_length(instruction))
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
                SSAVectorGet,
                SSAMatrixGet,
                SSAArrayLength,
                SSAVectorLength,
                SSAMatrixRows,
                SSAMatrixColumns,
                SSAVectorNew,
                SSAMatrixNew,
                SSAVectorAdd,
                SSAVectorDot,
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
            isinstance(instruction.result.type, IntType)
            and isinstance(instruction.left.type, IntType)
            and isinstance(instruction.right.type, IntType)
        ):
            operator = self._INT_BINARY_OPERATORS.get(instruction.operator)
            result_type = "i32"
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

    def _print_array_new(self, instruction: SSAArrayNew) -> str:
        if not isinstance(instruction.result.type, ArrayType):
            raise LLVMBackendError("LLVM array_new result must be ArrayType")
        return self._print_contiguous_new(
            instruction.result,
            instruction.result.type.element,
            instruction.elements,
        )

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
        label_id = self._next_synthetic_temp
        self._next_synthetic_temp += 1
        loop_label = f"vector.dot.loop.{label_id}"
        body_label = f"vector.dot.body.{label_id}"
        exit_label = f"vector.dot.exit.{label_id}"

        left_field = self._synthetic_temp("vector.dot.left.data.field")
        left_data = self._synthetic_temp("vector.dot.left.data")
        right_data = self._synthetic_temp("vector.dot.right.data")
        acc_ptr = self._synthetic_temp("vector.dot.acc.ptr")
        index_ptr = self._synthetic_temp("vector.dot.index.ptr")
        lines = [
            f"  {left_field} = getelementptr {self._ARRAY_STRUCT_TYPE}, ptr {self._operand(instruction.left)}, i32 0, i32 1",
            f"  {left_data} = load ptr, ptr {left_field}",
        ]
        right_field = self._synthetic_temp("vector.dot.right.data.field")
        lines.extend(
            [
                f"  {right_field} = getelementptr {self._ARRAY_STRUCT_TYPE}, ptr {self._operand(instruction.right)}, i32 0, i32 1",
                f"  {right_data} = load ptr, ptr {right_field}",
                f"  {acc_ptr} = alloca {result_type}",
                f"  store {result_type} {zero}, ptr {acc_ptr}",
                f"  {index_ptr} = alloca i64",
                f"  store i64 0, ptr {index_ptr}",
                f"  br label %{loop_label}",
                f"{loop_label}:",
            ]
        )
        index = self._synthetic_temp("vector.dot.index")
        condition = self._synthetic_temp("vector.dot.cond")
        lines.extend(
            [
                f"  {index} = load i64, ptr {index_ptr}",
                f"  {condition} = icmp slt i64 {index}, {instruction.length}",
                f"  br i1 {condition}, label %{body_label}, label %{exit_label}",
                f"{body_label}:",
            ]
        )

        left_ptr = self._synthetic_temp("vector.dot.left.elem")
        right_ptr = self._synthetic_temp("vector.dot.right.elem")
        loaded_left = self._synthetic_temp("vector.dot.left")
        loaded_right = self._synthetic_temp("vector.dot.right")
        lines.extend(
            [
                f"  {left_ptr} = getelementptr {left_element_type}, ptr {left_data}, i64 {index}",
                f"  {loaded_left} = load {left_element_type}, ptr {left_ptr}",
                f"  {right_ptr} = getelementptr {right_element_type}, ptr {right_data}, i64 {index}",
                f"  {loaded_right} = load {right_element_type}, ptr {right_ptr}",
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
                f"  br label %{loop_label}",
                f"{exit_label}:",
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

        result = self._new_temp(instruction.result)
        result_element_type = llvm_type(instruction.result.type.element)
        result_element_size = self._sizeof(instruction.result.type.element)
        multiply_operator = self._element_binary_operator(instruction.result.type.element, "mul")
        add_operator = self._element_binary_operator(instruction.result.type.element, "add")
        zero = "0.0" if isinstance(instruction.result.type.element, DoubleType) else "0"
        length = instruction.rows * instruction.cols
        lines = [
            f"{result} = call ptr @aether_array_new(i64 {result_element_size}, i64 {length})"
        ]

        left_data = self._synthetic_temp("matrix.matmul.left.data")
        right_data = self._synthetic_temp("matrix.matmul.right.data")
        result_data = self._synthetic_temp("matrix.matmul.result.data")
        lines.extend(self._array_data_pointer(left_data, self._operand(instruction.left)))
        lines.extend(self._array_data_pointer(right_data, self._operand(instruction.right)))
        lines.extend(self._array_data_pointer(result_data, result))

        left_element_type = llvm_type(instruction.left.type.element)
        right_element_type = llvm_type(instruction.right.type.element)
        for row in range(instruction.rows):
            for col in range(instruction.cols):
                accumulator = zero
                for inner in range(instruction.inner):
                    left_index = row * instruction.inner + inner
                    right_index = inner * instruction.cols + col
                    left_ptr = self._synthetic_temp("matrix.matmul.left.elem")
                    right_ptr = self._synthetic_temp("matrix.matmul.right.elem")
                    loaded_left = self._synthetic_temp("matrix.matmul.left")
                    loaded_right = self._synthetic_temp("matrix.matmul.right")
                    lines.append(
                        f"{left_ptr} = getelementptr {left_element_type}, ptr {left_data}, i64 {left_index}"
                    )
                    lines.append(f"{loaded_left} = load {left_element_type}, ptr {left_ptr}")
                    lines.append(
                        f"{right_ptr} = getelementptr {right_element_type}, ptr {right_data}, i64 {right_index}"
                    )
                    lines.append(f"{loaded_right} = load {right_element_type}, ptr {right_ptr}")
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
                    f"{result_ptr} = getelementptr {result_element_type}, ptr {result_data}, i64 {result_index}"
                )
                lines.append(f"store {result_element_type} {accumulator}, ptr {result_ptr}")

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

        result = self._new_temp(instruction.result)
        result_element_type = llvm_type(instruction.result.type.element)
        result_element_size = self._sizeof(instruction.result.type.element)
        matrix_element_type = llvm_type(instruction.matrix.type.element)
        vector_element_type = llvm_type(instruction.vector.type.element)
        multiply_operator = self._element_binary_operator(instruction.result.type.element, "mul")
        add_operator = self._element_binary_operator(instruction.result.type.element, "add")
        zero = "0.0" if isinstance(instruction.result.type.element, DoubleType) else "0"
        label_id = self._next_synthetic_temp
        self._next_synthetic_temp += 1
        outer_loop_label = f"matrix.vector.outer.loop.{label_id}"
        outer_body_label = f"matrix.vector.outer.body.{label_id}"
        inner_loop_label = f"matrix.vector.inner.loop.{label_id}"
        inner_body_label = f"matrix.vector.inner.body.{label_id}"
        inner_exit_label = f"matrix.vector.inner.exit.{label_id}"
        exit_label = f"matrix.vector.exit.{label_id}"

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
            f"  {result} = call ptr @aether_array_new(i64 {result_element_size}, i64 {instruction.rows})",
            f"  {matrix_field} = getelementptr {self._ARRAY_STRUCT_TYPE}, ptr {self._operand(instruction.matrix)}, i32 0, i32 1",
            f"  {matrix_data} = load ptr, ptr {matrix_field}",
            f"  {vector_field} = getelementptr {self._ARRAY_STRUCT_TYPE}, ptr {self._operand(instruction.vector)}, i32 0, i32 1",
            f"  {vector_data} = load ptr, ptr {vector_field}",
            f"  {result_field} = getelementptr {self._ARRAY_STRUCT_TYPE}, ptr {result}, i32 0, i32 1",
            f"  {result_data} = load ptr, ptr {result_field}",
            f"  {row_ptr} = alloca i64",
            f"  store i64 0, ptr {row_ptr}",
            f"  {col_ptr} = alloca i64",
            f"  {acc_ptr} = alloca {result_element_type}",
            f"  br label %{outer_loop_label}",
            f"{outer_loop_label}:",
        ]

        row = self._synthetic_temp("matrix.vector.row")
        outer_cond = self._synthetic_temp("matrix.vector.outer.cond")
        lines.extend(
            [
                f"  {row} = load i64, ptr {row_ptr}",
                f"  {outer_cond} = icmp slt i64 {row}, {instruction.rows}",
                f"  br i1 {outer_cond}, label %{outer_body_label}, label %{exit_label}",
                f"{outer_body_label}:",
                f"  store {result_element_type} {zero}, ptr {acc_ptr}",
                f"  store i64 0, ptr {col_ptr}",
                f"  br label %{inner_loop_label}",
                f"{inner_loop_label}:",
            ]
        )

        col = self._synthetic_temp("matrix.vector.col")
        inner_cond = self._synthetic_temp("matrix.vector.inner.cond")
        lines.extend(
            [
                f"  {col} = load i64, ptr {col_ptr}",
                f"  {inner_cond} = icmp slt i64 {col}, {instruction.inner}",
                f"  br i1 {inner_cond}, label %{inner_body_label}, label %{inner_exit_label}",
                f"{inner_body_label}:",
            ]
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
                f"  {matrix_ptr} = getelementptr {matrix_element_type}, ptr {matrix_data}, i64 {matrix_index}",
                f"  {loaded_matrix} = load {matrix_element_type}, ptr {matrix_ptr}",
                f"  {vector_ptr} = getelementptr {vector_element_type}, ptr {vector_data}, i64 {col}",
                f"  {loaded_vector} = load {vector_element_type}, ptr {vector_ptr}",
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
                f"  br label %{inner_loop_label}",
                f"{inner_exit_label}:",
                f"  {acc_final} = load {result_element_type}, ptr {acc_ptr}",
                f"  {result_ptr} = getelementptr {result_element_type}, ptr {result_data}, i64 {row}",
                f"  store {result_element_type} {acc_final}, ptr {result_ptr}",
                f"  {row_next} = add i64 {row}, 1",
                f"  store i64 {row_next}, ptr {row_ptr}",
                f"  br label %{outer_loop_label}",
                f"{exit_label}:",
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

        result = self._new_temp(instruction.result)
        result_element_type = llvm_type(instruction.result.type.element)
        result_element_size = self._sizeof(instruction.result.type.element)
        vector_element_type = llvm_type(instruction.vector.type.element)
        matrix_element_type = llvm_type(instruction.matrix.type.element)
        multiply_operator = self._element_binary_operator(instruction.result.type.element, "mul")
        add_operator = self._element_binary_operator(instruction.result.type.element, "add")
        zero = "0.0" if isinstance(instruction.result.type.element, DoubleType) else "0"
        label_id = self._next_synthetic_temp
        self._next_synthetic_temp += 1
        outer_loop_label = f"vector.matrix.outer.loop.{label_id}"
        outer_body_label = f"vector.matrix.outer.body.{label_id}"
        inner_loop_label = f"vector.matrix.inner.loop.{label_id}"
        inner_body_label = f"vector.matrix.inner.body.{label_id}"
        inner_exit_label = f"vector.matrix.inner.exit.{label_id}"
        exit_label = f"vector.matrix.exit.{label_id}"

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
            f"  {result} = call ptr @aether_array_new(i64 {result_element_size}, i64 {instruction.cols})",
            f"  {vector_field} = getelementptr {self._ARRAY_STRUCT_TYPE}, ptr {self._operand(instruction.vector)}, i32 0, i32 1",
            f"  {vector_data} = load ptr, ptr {vector_field}",
            f"  {matrix_field} = getelementptr {self._ARRAY_STRUCT_TYPE}, ptr {self._operand(instruction.matrix)}, i32 0, i32 1",
            f"  {matrix_data} = load ptr, ptr {matrix_field}",
            f"  {result_field} = getelementptr {self._ARRAY_STRUCT_TYPE}, ptr {result}, i32 0, i32 1",
            f"  {result_data} = load ptr, ptr {result_field}",
            f"  {col_ptr} = alloca i64",
            f"  store i64 0, ptr {col_ptr}",
            f"  {row_ptr} = alloca i64",
            f"  {acc_ptr} = alloca {result_element_type}",
            f"  br label %{outer_loop_label}",
            f"{outer_loop_label}:",
        ]

        col = self._synthetic_temp("vector.matrix.col")
        outer_cond = self._synthetic_temp("vector.matrix.outer.cond")
        lines.extend(
            [
                f"  {col} = load i64, ptr {col_ptr}",
                f"  {outer_cond} = icmp slt i64 {col}, {instruction.cols}",
                f"  br i1 {outer_cond}, label %{outer_body_label}, label %{exit_label}",
                f"{outer_body_label}:",
                f"  store {result_element_type} {zero}, ptr {acc_ptr}",
                f"  store i64 0, ptr {row_ptr}",
                f"  br label %{inner_loop_label}",
                f"{inner_loop_label}:",
            ]
        )

        row = self._synthetic_temp("vector.matrix.row")
        inner_cond = self._synthetic_temp("vector.matrix.inner.cond")
        lines.extend(
            [
                f"  {row} = load i64, ptr {row_ptr}",
                f"  {inner_cond} = icmp slt i64 {row}, {instruction.rows}",
                f"  br i1 {inner_cond}, label %{inner_body_label}, label %{inner_exit_label}",
                f"{inner_body_label}:",
            ]
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
                f"  {vector_ptr} = getelementptr {vector_element_type}, ptr {vector_data}, i64 {row}",
                f"  {loaded_vector} = load {vector_element_type}, ptr {vector_ptr}",
                f"  {matrix_ptr} = getelementptr {matrix_element_type}, ptr {matrix_data}, i64 {matrix_index}",
                f"  {loaded_matrix} = load {matrix_element_type}, ptr {matrix_ptr}",
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
                f"  br label %{inner_loop_label}",
                f"{inner_exit_label}:",
                f"  {acc_final} = load {result_element_type}, ptr {acc_ptr}",
                f"  {result_ptr} = getelementptr {result_element_type}, ptr {result_data}, i64 {col}",
                f"  store {result_element_type} {acc_final}, ptr {result_ptr}",
                f"  {col_next} = add i64 {col}, 1",
                f"  store i64 {col_next}, ptr {col_ptr}",
                f"  br label %{outer_loop_label}",
                f"{exit_label}:",
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

        result = self._new_temp(result_value)
        element_type = llvm_type(element_ir_type)
        element_size = self._sizeof(element_ir_type)
        length = len(elements)
        lines = [
            f"{result} = call ptr @aether_array_new(i64 {element_size}, i64 {length})"
        ]
        data = self._synthetic_temp("array.data")
        lines.extend(self._array_data_pointer(data, result))
        for index, element in enumerate(elements):
            element_ptr = self._synthetic_temp("array.elem")
            lines.append(
                f"{element_ptr} = getelementptr {element_type}, ptr {data}, i64 {index}"
            )
            lines.append(
                f"store {element_type} {self._operand(element)}, ptr {element_ptr}"
            )
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

        result = self._new_temp(result_value)
        element_type = llvm_type(element_ir_type)
        element_size = self._sizeof(element_ir_type)
        operator = self._element_binary_operator(element_ir_type, operator_name)
        lines = [
            f"{result} = call ptr @aether_array_new(i64 {element_size}, i64 {length})"
        ]

        left_data = self._synthetic_temp(f"{operator_name}.left.data")
        right_data = self._synthetic_temp(f"{operator_name}.right.data")
        result_data = self._synthetic_temp(f"{operator_name}.result.data")
        lines.extend(self._array_data_pointer(left_data, self._operand(left_value)))
        lines.extend(self._array_data_pointer(right_data, self._operand(right_value)))
        lines.extend(self._array_data_pointer(result_data, result))

        for index in range(length):
            left_ptr = self._synthetic_temp(f"{operator_name}.left.elem")
            right_ptr = self._synthetic_temp(f"{operator_name}.right.elem")
            result_ptr = self._synthetic_temp(f"{operator_name}.result.elem")
            loaded_left = self._synthetic_temp(f"{operator_name}.left")
            loaded_right = self._synthetic_temp(f"{operator_name}.right")
            result_element = self._synthetic_temp(f"{operator_name}.value")
            lines.append(
                f"{left_ptr} = getelementptr {element_type}, ptr {left_data}, i64 {index}"
            )
            lines.append(f"{loaded_left} = load {element_type}, ptr {left_ptr}")
            lines.append(
                f"{right_ptr} = getelementptr {element_type}, ptr {right_data}, i64 {index}"
            )
            lines.append(f"{loaded_right} = load {element_type}, ptr {right_ptr}")
            lines.append(
                f"{result_element} = {operator} {element_type} {loaded_left}, {loaded_right}"
            )
            lines.append(
                f"{result_ptr} = getelementptr {element_type}, ptr {result_data}, i64 {index}"
            )
            lines.append(f"store {element_type} {result_element}, ptr {result_ptr}")

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

        result = self._new_temp(result_value)
        element_type = llvm_type(element_ir_type)
        element_size = self._sizeof(element_ir_type)
        operator = self._element_binary_operator(element_ir_type, "mul")
        scalar = self._operand(scalar_value)
        lines = [
            f"{result} = call ptr @aether_array_new(i64 {element_size}, i64 {length})"
        ]

        aggregate_data = self._synthetic_temp(f"{operation_name}.source.data")
        result_data = self._synthetic_temp(f"{operation_name}.result.data")
        lines.extend(self._array_data_pointer(aggregate_data, self._operand(aggregate_value)))
        lines.extend(self._array_data_pointer(result_data, result))

        for index in range(length):
            aggregate_ptr = self._synthetic_temp(f"{operation_name}.source.elem")
            result_ptr = self._synthetic_temp(f"{operation_name}.result.elem")
            loaded_value = self._synthetic_temp(f"{operation_name}.source")
            result_element = self._synthetic_temp(f"{operation_name}.value")
            lines.append(
                f"{aggregate_ptr} = getelementptr {element_type}, ptr {aggregate_data}, i64 {index}"
            )
            lines.append(f"{loaded_value} = load {element_type}, ptr {aggregate_ptr}")
            lines.append(
                f"{result_element} = {operator} {element_type} {loaded_value}, {scalar}"
            )
            lines.append(
                f"{result_ptr} = getelementptr {element_type}, ptr {result_data}, i64 {index}"
            )
            lines.append(f"store {element_type} {result_element}, ptr {result_ptr}")

        return lines

    def _print_array_get(self, instruction: SSAArrayGet) -> list[str]:
        if not isinstance(instruction.array.type, ArrayType):
            raise LLVMBackendError("LLVM array_get expects an ArrayType source")
        self._uses_array_type = True

        result = self._new_temp(instruction.result)
        element_type = llvm_type(instruction.result.type)
        element_ptr = self._array_element_pointer(
            self._operand(instruction.array),
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

        result = self._new_temp(instruction.result)
        element_type = llvm_type(instruction.result.type)
        element_ptr = self._array_element_pointer(
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

        element_type = llvm_type(instruction.value.type)
        element_ptr = self._array_element_pointer(
            self._operand(instruction.array),
            instruction.index,
            instruction.value.type,
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

        element_type = llvm_type(instruction.value.type)
        element_ptr = self._array_element_pointer(
            self._operand(instruction.vector),
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
        result = self._new_temp(instruction.result)
        length64 = self._synthetic_temp("array.len64")
        lines = self._array_length64(length64, self._operand(instruction.array))
        lines.append(f"{result} = trunc i64 {length64} to i32")
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

    def _array_element_pointer(
        self,
        array: str,
        index: SSAValue,
        element_type: object,
    ) -> _ArrayPointer:
        data = self._synthetic_temp("array.data")
        index64 = self._synthetic_temp("array.index64")
        element_ptr = self._synthetic_temp("array.elem")
        llvm_element_type = llvm_type(element_type)
        lines = self._array_data_pointer(data, array)
        lines.append(f"{index64} = sext i32 {self._operand(index)} to i64")
        lines.append(
            f"{element_ptr} = getelementptr {llvm_element_type}, ptr {data}, i64 {index64}"
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
        row_offset = self._synthetic_temp("matrix.row.offset")
        linear_index = self._synthetic_temp("matrix.index")
        element_ptr = self._synthetic_temp("matrix.elem")
        llvm_element_type = llvm_type(element_type)
        lines = self._array_data_pointer(data, matrix)
        lines.append(f"{row64} = sext i32 {self._operand(row)} to i64")
        lines.append(f"{column64} = sext i32 {self._operand(column)} to i64")
        lines.append(f"{row_offset} = mul i64 {row64}, {cols}")
        lines.append(f"{linear_index} = add i64 {row_offset}, {column64}")
        lines.append(
            f"{element_ptr} = getelementptr {llvm_element_type}, ptr {data}, i64 {linear_index}"
        )
        return self._ArrayPointer(element_ptr, lines)

    def _array_data_pointer(self, result: str, array: str) -> list[str]:
        field_ptr = self._synthetic_temp("array.data.field")
        return [
            f"{field_ptr} = getelementptr {self._ARRAY_STRUCT_TYPE}, ptr {array}, i32 0, i32 1",
            f"{result} = load ptr, ptr {field_ptr}",
        ]

    def _array_length64(self, result: str, array: str) -> list[str]:
        field_ptr = self._synthetic_temp("array.len.field")
        return [
            f"{field_ptr} = getelementptr {self._ARRAY_STRUCT_TYPE}, ptr {array}, i32 0, i32 0",
            f"{result} = load i64, ptr {field_ptr}",
        ]

    def _runtime_declarations(self) -> list[str]:
        sections: list[str] = []
        if self._uses_array_type:
            sections.append(f"{self._ARRAY_STRUCT_TYPE} = type {{ i64, ptr }}")
        if self._uses_array_allocation:
            sections.append("declare noalias ptr @malloc(i64)")
            sections.append(
                "\n".join(
                    [
                        "define private ptr @aether_alloc(i64 %size) {",
                        "entry:",
                        "  %mem = call noalias ptr @malloc(i64 %size)",
                        "  ret ptr %mem",
                        "}",
                    ]
                )
            )
            sections.append(
                "\n".join(
                    [
                        "define private ptr @aether_array_new(i64 %element_size, i64 %length) {",
                        "entry:",
                        "  %array = call ptr @aether_alloc(i64 16)",
                        f"  %len_field = getelementptr {self._ARRAY_STRUCT_TYPE}, ptr %array, i32 0, i32 0",
                        "  store i64 %length, ptr %len_field",
                        "  %data_size = mul i64 %element_size, %length",
                        "  %data = call ptr @aether_alloc(i64 %data_size)",
                        f"  %data_field = getelementptr {self._ARRAY_STRUCT_TYPE}, ptr %array, i32 0, i32 1",
                        "  store ptr %data, ptr %data_field",
                        "  ret ptr %array",
                        "}",
                    ]
                )
            )
        return sections

    def _sizeof(self, type_: object) -> int:
        if isinstance(type_, (IntType, BoolType)):
            return 4 if isinstance(type_, IntType) else 1
        if isinstance(type_, DoubleType):
            return 8
        if isinstance(type_, (StringType, ArrayType, VectorType)):
            return 8
        raise LLVMBackendError(f"LLVM backend does not know the size of {type_}")

    @staticmethod
    def _element_binary_operator(type_: object, operator: str) -> str:
        if isinstance(type_, IntType):
            if operator == "add":
                return "add"
            if operator == "sub":
                return "sub"
            if operator == "mul":
                return "mul"
        if isinstance(type_, DoubleType):
            if operator == "add":
                return "fadd"
            if operator == "sub":
                return "fsub"
            if operator == "mul":
                return "fmul"
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
