from __future__ import annotations

from typing import NoReturn

from aether.ir.types import (
    ArrayType,
    BoolType,
    ClassRefType,
    ComplexType,
    DoubleType,
    EnumType,
    FloatType,
    IntType,
    InterfaceType,
    IRType,
    ListType,
    MatrixType,
    NullableType,
    StringType,
    StructType,
    VectorType,
    VoidType,
)

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
    SSAMatrixColumns,
    SSAMatrixAdd,
    SSAMatrixSub,
    SSAMatrixGet,
    SSAMatrixNew,
    SSAMatrixRows,
    SSAMatrixSet,
    SSAModule,
    SSAPhi,
    SSAReturn,
    SSAValue,
    SSAVectorGet,
    SSAVectorAdd,
    SSAVectorSub,
    SSAVectorLength,
    SSAVectorNew,
    SSAVectorSet,
)


class SSAVerificationError(ValueError):
    """Raised when an SSA module is internally inconsistent."""


class SSAVerifier:
    """Validate hand-built Aether SSA modules."""

    _TERMINATORS = (SSABranch, SSAJump, SSAReturn)
    _NUMERIC_TYPES = (IntType, FloatType, DoubleType, ComplexType)
    _REAL_TYPES = (IntType, FloatType, DoubleType)

    def __init__(self, module: SSAModule) -> None:
        self.module = module
        self._functions: dict[str, SSAFunction] = {}

    def verify(self) -> SSAModule:
        """Verify the module and return it unchanged on success."""
        self._functions = {}
        self._verify_module()
        return self.module

    def _verify_module(self) -> None:
        seen: set[str] = set()
        for function in self.module.functions:
            if function.name in seen:
                self._fail(f"Duplicate function '{function.name}'")
            seen.add(function.name)
            self._functions[function.name] = function

        for function in self.module.functions:
            self._verify_function(function)

    def _verify_function(self, function: SSAFunction) -> None:
        self._verify_type(function.return_type, f"return type of function '{function.name}'")
        self._verify_parameters(function)

        if not function.blocks:
            self._fail(f"Function '{function.name}' has no blocks")

        blocks = self._collect_blocks(function)
        if "entry" not in blocks:
            self._fail(f"Function '{function.name}' has no entry block")

        self._verify_block_structure(function, blocks)
        predecessors = self._predecessors(blocks)
        value_types = self._collect_value_types(function)

        for block in function.blocks:
            self._verify_phi_placement(function, block)
            self._verify_instructions(function, block, blocks, predecessors, value_types)

    def _verify_parameters(self, function: SSAFunction) -> None:
        seen: set[str] = set()
        for parameter in function.parameters:
            if parameter.name in seen:
                self._fail(
                    f"Duplicate parameter '{parameter.name}' in function '{function.name}'"
                )
            seen.add(parameter.name)
            self._verify_type(
                parameter.type,
                f"parameter '{parameter.name}' of function '{function.name}'",
            )

    def _collect_blocks(self, function: SSAFunction) -> dict[str, SSABasicBlock]:
        blocks: dict[str, SSABasicBlock] = {}
        for block in function.blocks:
            if block.name in blocks:
                self._fail(f"Duplicate block '{block.name}' in function '{function.name}'")
            blocks[block.name] = block
        return blocks

    def _verify_block_structure(
        self,
        function: SSAFunction,
        blocks: dict[str, SSABasicBlock],
    ) -> None:
        for block in function.blocks:
            if not block.instructions:
                self._fail(
                    f"Block '{block.name}' in function '{function.name}' has no terminator"
                )

            for index, instruction in enumerate(block.instructions):
                if isinstance(instruction, self._TERMINATORS):
                    if index != len(block.instructions) - 1:
                        self._fail(f"Instruction after terminator in block '{block.name}'")
                    self._verify_terminator_targets(function, instruction, blocks)
                    break
            else:
                self._fail(
                    f"Block '{block.name}' in function '{function.name}' has no terminator"
                )

    def _verify_terminator_targets(
        self,
        function: SSAFunction,
        instruction: SSAInstruction,
        blocks: dict[str, SSABasicBlock],
    ) -> None:
        if isinstance(instruction, SSAJump):
            if instruction.target not in blocks:
                self._fail(
                    f"Unknown jump target '{instruction.target}' in function '{function.name}'"
                )
            return

        if isinstance(instruction, SSABranch):
            for target in (instruction.true_target, instruction.false_target):
                if target not in blocks:
                    self._fail(
                        f"Unknown branch target '{target}' in function '{function.name}'"
                    )

    def _predecessors(
        self,
        blocks: dict[str, SSABasicBlock],
    ) -> dict[str, set[str]]:
        predecessors: dict[str, set[str]] = {name: set() for name in blocks}
        for block in blocks.values():
            for successor in self._successors(block):
                predecessors[successor].add(block.name)
        return predecessors

    def _collect_value_types(self, function: SSAFunction) -> dict[str, IRType]:
        value_types: dict[str, IRType] = {}
        for parameter in function.parameters:
            self._define_value_type(value_types, parameter, function)

        for block in function.blocks:
            for instruction in block.instructions:
                result = self._instruction_result(instruction)
                if result is None:
                    continue
                self._verify_type(result.type, f"value '{self._value(result)}'")
                self._define_value_type(value_types, result, function)

        return value_types

    def _define_value_type(
        self,
        value_types: dict[str, IRType],
        value: SSAValue,
        function: SSAFunction,
    ) -> None:
        existing = value_types.get(value.name)
        if existing is not None:
            self._fail(f"Duplicate value '{self._value(value)}' in function '{function.name}'")
        value_types[value.name] = value.type

    def _verify_phi_placement(self, function: SSAFunction, block: SSABasicBlock) -> None:
        seen_non_phi = False
        for instruction in block.instructions:
            if isinstance(instruction, self._TERMINATORS):
                return
            if isinstance(instruction, SSAPhi):
                if seen_non_phi:
                    self._fail(
                        f"Phi instruction after non-phi instruction in block '{block.name}'"
                    )
                continue
            seen_non_phi = True

    def _verify_instructions(
        self,
        function: SSAFunction,
        block: SSABasicBlock,
        blocks: dict[str, SSABasicBlock],
        predecessors: dict[str, set[str]],
        value_types: dict[str, IRType],
    ) -> None:
        for instruction in block.instructions:
            if isinstance(instruction, SSAConst):
                self._verify_const(instruction)
                continue

            if isinstance(instruction, SSABinaryOp):
                self._require_defined(instruction.left, value_types)
                self._require_defined(instruction.right, value_types)
                result_type = self._binary_result_type(instruction)
                self._require_type(
                    instruction.result.type,
                    result_type,
                    f"Binary op '{instruction.operator}' result type mismatch",
                )
                continue

            if isinstance(instruction, SSACompareOp):
                self._require_defined(instruction.left, value_types)
                self._require_defined(instruction.right, value_types)
                self._verify_compare(instruction)
                continue

            if isinstance(instruction, SSACast):
                self._require_defined(instruction.value, value_types)
                self._verify_cast(instruction)
                continue

            if isinstance(instruction, SSACall):
                self._verify_call(instruction, value_types)
                continue

            if isinstance(instruction, SSAArrayNew):
                self._verify_array_new(instruction, value_types)
                continue

            if isinstance(instruction, SSAVectorNew):
                self._verify_vector_new(instruction, value_types)
                continue

            if isinstance(instruction, SSAMatrixNew):
                self._verify_matrix_new(instruction, value_types)
                continue

            if isinstance(instruction, SSAVectorAdd):
                self._verify_vector_add(instruction, value_types)
                continue

            if isinstance(instruction, SSAVectorSub):
                self._verify_vector_sub(instruction, value_types)
                continue

            if isinstance(instruction, SSAMatrixAdd):
                self._verify_matrix_add(instruction, value_types)
                continue

            if isinstance(instruction, SSAMatrixSub):
                self._verify_matrix_sub(instruction, value_types)
                continue

            if isinstance(instruction, SSAArrayGet):
                self._verify_array_get(instruction, value_types)
                continue

            if isinstance(instruction, SSAVectorGet):
                self._verify_vector_get(instruction, value_types)
                continue

            if isinstance(instruction, SSAMatrixGet):
                self._verify_matrix_get(instruction, value_types)
                continue

            if isinstance(instruction, SSAVectorLength):
                self._verify_vector_length(instruction, value_types)
                continue

            if isinstance(instruction, SSAMatrixRows):
                self._verify_matrix_rows(instruction, value_types)
                continue

            if isinstance(instruction, SSAMatrixColumns):
                self._verify_matrix_columns(instruction, value_types)
                continue

            if isinstance(instruction, SSAArraySet):
                self._verify_array_set(instruction, value_types)
                continue

            if isinstance(instruction, SSAVectorSet):
                self._verify_vector_set(instruction, value_types)
                continue

            if isinstance(instruction, SSAMatrixSet):
                self._verify_matrix_set(instruction, value_types)
                continue

            if isinstance(instruction, SSAArrayLength):
                self._verify_array_length(instruction, value_types)
                continue

            if isinstance(instruction, SSAPhi):
                self._verify_phi(instruction, block, blocks, predecessors, value_types)
                continue

            if isinstance(instruction, SSABranch):
                self._require_defined(instruction.condition, value_types)
                if not isinstance(instruction.condition.type, BoolType):
                    self._fail("Branch condition must be bool")
                continue

            if isinstance(instruction, SSAJump):
                continue

            if isinstance(instruction, SSAReturn):
                self._verify_return(function, instruction, value_types)
                continue

            self._fail(f"Unsupported SSA instruction '{type(instruction).__name__}'")

    def _verify_compare(self, instruction: SSACompareOp) -> None:
        result_type = self._compare_operand_result_type(instruction)
        self._require_type(
            instruction.result.type,
            BoolType(),
            f"Compare op '{instruction.operator}' result type mismatch",
        )
        self._require_type(
            instruction.result.type,
            result_type,
            f"Compare op '{instruction.operator}' result type mismatch",
        )

    def _verify_call(
        self,
        instruction: SSACall,
        value_types: dict[str, IRType],
    ) -> None:
        callee = self._functions.get(instruction.function)
        if callee is None:
            self._fail(f"Call to undefined function '{instruction.function}'")

        expected = len(callee.parameters)
        actual = len(instruction.arguments)
        if actual != expected:
            self._fail(
                f"Function '{instruction.function}' expects {expected} arguments, got {actual}"
            )

        for index, (argument, parameter) in enumerate(
            zip(instruction.arguments, callee.parameters),
            start=1,
        ):
            self._require_defined(argument, value_types)
            if argument.type != parameter.type:
                self._fail(
                    f"Argument {index} to function '{instruction.function}' type mismatch: "
                    f"expected {parameter.type}, got {argument.type}"
                )

        if isinstance(callee.return_type, VoidType):
            if instruction.result is not None:
                self._fail(
                    f"Call to void function '{instruction.function}' cannot produce a value"
                )
            return

        if instruction.result is None:
            self._fail(
                f"Call to function '{instruction.function}' must produce a result "
                f"of type {callee.return_type}"
            )

        if instruction.result.type != callee.return_type:
            self._fail(
                f"Call result type mismatch: expected {callee.return_type}, "
                f"got {instruction.result.type}"
            )

    def _verify_array_new(
        self,
        instruction: SSAArrayNew,
        value_types: dict[str, IRType],
    ) -> None:
        if not isinstance(instruction.result.type, ArrayType):
            self._fail(f"Array new result must be array type, got {instruction.result.type}")
        for element in instruction.elements:
            self._require_defined(element, value_types)
            if element.type != instruction.result.type.element:
                self._fail(
                    f"Array literal element type mismatch: expected "
                    f"{instruction.result.type.element}, got {element.type}"
                )

    def _verify_vector_new(
        self,
        instruction: SSAVectorNew,
        value_types: dict[str, IRType],
    ) -> None:
        if not isinstance(instruction.result.type, VectorType):
            self._fail(f"Vector new result must be vector type, got {instruction.result.type}")
        if instruction.result.type.orientation not in {"row", "column"}:
            self._fail(f"Vector new requires row or column orientation, got {instruction.result.type}")
        if instruction.orientation not in {"row", "column"}:
            self._fail(f"Vector new requires row or column instruction orientation, got {instruction.orientation}")
        if instruction.orientation != instruction.result.type.orientation:
            self._fail(
                f"Vector new orientation mismatch: result type is {instruction.result.type.orientation}, "
                f"instruction is {instruction.orientation}"
            )
        for element in instruction.elements:
            self._require_defined(element, value_types)
            if element.type != instruction.result.type.element:
                self._fail(
                    f"Vector literal element type mismatch: expected "
                    f"{instruction.result.type.element}, got {element.type}"
                )

    def _verify_matrix_new(
        self,
        instruction: SSAMatrixNew,
        value_types: dict[str, IRType],
    ) -> None:
        if not isinstance(instruction.result.type, MatrixType):
            self._fail(f"Matrix new result must be matrix type, got {instruction.result.type}")
        if instruction.rows <= 0 or instruction.cols <= 0:
            self._fail(f"Matrix new dimensions must be positive, got {instruction.rows}x{instruction.cols}")
        if len(instruction.elements) != instruction.rows * instruction.cols:
            self._fail(
                f"Matrix new element count mismatch: expected {instruction.rows * instruction.cols}, "
                f"got {len(instruction.elements)}"
            )
        for element in instruction.elements:
            self._require_defined(element, value_types)
            if element.type != instruction.result.type.element:
                self._fail(
                    f"Matrix literal element type mismatch: expected "
                    f"{instruction.result.type.element}, got {element.type}"
                )

    def _verify_vector_add(
        self,
        instruction: SSAVectorAdd,
        value_types: dict[str, IRType],
    ) -> None:
        self._verify_vector_binary(instruction, value_types, "add")

    def _verify_vector_sub(
        self,
        instruction: SSAVectorSub,
        value_types: dict[str, IRType],
    ) -> None:
        self._verify_vector_binary(instruction, value_types, "sub")

    def _verify_vector_binary(
        self,
        instruction: SSAVectorAdd | SSAVectorSub,
        value_types: dict[str, IRType],
        operation: str,
    ) -> None:
        self._require_defined(instruction.left, value_types)
        self._require_defined(instruction.right, value_types)
        if not isinstance(instruction.result.type, VectorType):
            self._fail(f"Vector {operation} result must be vector type, got {instruction.result.type}")
        if not isinstance(instruction.left.type, VectorType) or not isinstance(instruction.right.type, VectorType):
            self._fail(
                f"Vector {operation} expects vector operands, got {instruction.left.type} and {instruction.right.type}"
            )
        if instruction.length <= 0:
            self._fail(f"Vector {operation} length must be positive, got {instruction.length}")
        if instruction.left.type.orientation != instruction.right.type.orientation:
            self._fail(f"Vector {operation} operands must have the same orientation")
        if instruction.orientation != instruction.result.type.orientation:
            self._fail(f"Vector {operation} instruction orientation must match result type")
        if instruction.result.type != instruction.left.type:
            self._fail(
                f"Vector {operation} result type mismatch: expected {instruction.left.type}, got {instruction.result.type}"
            )
        if instruction.right.type != instruction.left.type:
            self._fail(
                f"Vector {operation} operand type mismatch: expected {instruction.left.type}, got {instruction.right.type}"
            )

    def _verify_matrix_add(
        self,
        instruction: SSAMatrixAdd,
        value_types: dict[str, IRType],
    ) -> None:
        self._verify_matrix_binary(instruction, value_types, "add")

    def _verify_matrix_sub(
        self,
        instruction: SSAMatrixSub,
        value_types: dict[str, IRType],
    ) -> None:
        self._verify_matrix_binary(instruction, value_types, "sub")

    def _verify_matrix_binary(
        self,
        instruction: SSAMatrixAdd | SSAMatrixSub,
        value_types: dict[str, IRType],
        operation: str,
    ) -> None:
        self._require_defined(instruction.left, value_types)
        self._require_defined(instruction.right, value_types)
        if not isinstance(instruction.result.type, MatrixType):
            self._fail(f"Matrix {operation} result must be matrix type, got {instruction.result.type}")
        if not isinstance(instruction.left.type, MatrixType) or not isinstance(instruction.right.type, MatrixType):
            self._fail(
                f"Matrix {operation} expects matrix operands, got {instruction.left.type} and {instruction.right.type}"
            )
        if instruction.rows <= 0 or instruction.cols <= 0:
            self._fail(f"Matrix {operation} dimensions must be positive, got {instruction.rows}x{instruction.cols}")
        if instruction.result.type != instruction.left.type:
            self._fail(
                f"Matrix {operation} result type mismatch: expected {instruction.left.type}, got {instruction.result.type}"
            )
        if instruction.right.type != instruction.left.type:
            self._fail(
                f"Matrix {operation} operand type mismatch: expected {instruction.left.type}, got {instruction.right.type}"
            )

    def _verify_array_get(
        self,
        instruction: SSAArrayGet,
        value_types: dict[str, IRType],
    ) -> None:
        self._require_defined(instruction.array, value_types)
        self._require_defined(instruction.index, value_types)
        if not isinstance(instruction.array.type, ArrayType):
            self._fail(f"Array get expects array value, got {instruction.array.type}")
        if not isinstance(instruction.index.type, IntType):
            self._fail(f"Array get index must be int, got {instruction.index.type}")
        if instruction.result.type != instruction.array.type.element:
            self._fail(
                f"Array get result type mismatch: expected "
                f"{instruction.array.type.element}, got {instruction.result.type}"
            )

    def _verify_vector_get(
        self,
        instruction: SSAVectorGet,
        value_types: dict[str, IRType],
    ) -> None:
        self._require_defined(instruction.vector, value_types)
        self._require_defined(instruction.index, value_types)
        if not isinstance(instruction.vector.type, VectorType):
            self._fail(f"Vector get expects vector value, got {instruction.vector.type}")
        if not isinstance(instruction.index.type, IntType):
            self._fail(f"Vector get index must be int, got {instruction.index.type}")
        if instruction.result.type != instruction.vector.type.element:
            self._fail(
                f"Vector get result type mismatch: expected "
                f"{instruction.vector.type.element}, got {instruction.result.type}"
            )

    def _verify_matrix_get(
        self,
        instruction: SSAMatrixGet,
        value_types: dict[str, IRType],
    ) -> None:
        self._require_defined(instruction.matrix, value_types)
        self._require_defined(instruction.row, value_types)
        self._require_defined(instruction.column, value_types)
        if not isinstance(instruction.matrix.type, MatrixType):
            self._fail(f"Matrix get expects matrix value, got {instruction.matrix.type}")
        if not isinstance(instruction.row.type, IntType):
            self._fail(f"Matrix get row index must be int, got {instruction.row.type}")
        if not isinstance(instruction.column.type, IntType):
            self._fail(f"Matrix get column index must be int, got {instruction.column.type}")
        if instruction.cols <= 0:
            self._fail(f"Matrix get column count must be positive, got {instruction.cols}")
        if instruction.result.type != instruction.matrix.type.element:
            self._fail(
                f"Matrix get result type mismatch: expected "
                f"{instruction.matrix.type.element}, got {instruction.result.type}"
            )

    def _verify_array_set(
        self,
        instruction: SSAArraySet,
        value_types: dict[str, IRType],
    ) -> None:
        self._require_defined(instruction.array, value_types)
        self._require_defined(instruction.index, value_types)
        self._require_defined(instruction.value, value_types)
        if not isinstance(instruction.array.type, ArrayType):
            self._fail(f"Array set expects array value, got {instruction.array.type}")
        if not isinstance(instruction.index.type, IntType):
            self._fail(f"Array set index must be int, got {instruction.index.type}")
        if instruction.value.type != instruction.array.type.element:
            self._fail(
                f"Array set value type mismatch: expected "
                f"{instruction.array.type.element}, got {instruction.value.type}"
            )

    def _verify_vector_set(
        self,
        instruction: SSAVectorSet,
        value_types: dict[str, IRType],
    ) -> None:
        self._require_defined(instruction.vector, value_types)
        self._require_defined(instruction.index, value_types)
        self._require_defined(instruction.value, value_types)
        if not isinstance(instruction.vector.type, VectorType):
            self._fail(f"Vector set expects vector value, got {instruction.vector.type}")
        if not isinstance(instruction.index.type, IntType):
            self._fail(f"Vector set index must be int, got {instruction.index.type}")
        if instruction.value.type != instruction.vector.type.element:
            self._fail(
                f"Vector set value type mismatch: expected "
                f"{instruction.vector.type.element}, got {instruction.value.type}"
            )

    def _verify_matrix_set(
        self,
        instruction: SSAMatrixSet,
        value_types: dict[str, IRType],
    ) -> None:
        self._require_defined(instruction.matrix, value_types)
        self._require_defined(instruction.row, value_types)
        self._require_defined(instruction.column, value_types)
        self._require_defined(instruction.value, value_types)
        if not isinstance(instruction.matrix.type, MatrixType):
            self._fail(f"Matrix set expects matrix value, got {instruction.matrix.type}")
        if not isinstance(instruction.row.type, IntType):
            self._fail(f"Matrix set row index must be int, got {instruction.row.type}")
        if not isinstance(instruction.column.type, IntType):
            self._fail(f"Matrix set column index must be int, got {instruction.column.type}")
        if instruction.cols <= 0:
            self._fail(f"Matrix set column count must be positive, got {instruction.cols}")
        if instruction.value.type != instruction.matrix.type.element:
            self._fail(
                f"Matrix set value type mismatch: expected "
                f"{instruction.matrix.type.element}, got {instruction.value.type}"
            )

    def _verify_array_length(
        self,
        instruction: SSAArrayLength,
        value_types: dict[str, IRType],
    ) -> None:
        self._require_defined(instruction.array, value_types)
        if not isinstance(instruction.array.type, ArrayType):
            self._fail(f"Array length expects array value, got {instruction.array.type}")
        if not isinstance(instruction.result.type, IntType):
            self._fail(f"Array length result must be int, got {instruction.result.type}")

    def _verify_vector_length(
        self,
        instruction: SSAVectorLength,
        value_types: dict[str, IRType],
    ) -> None:
        self._require_defined(instruction.vector, value_types)
        if not isinstance(instruction.vector.type, VectorType):
            self._fail(f"Vector length expects vector value, got {instruction.vector.type}")
        if not isinstance(instruction.result.type, IntType):
            self._fail(f"Vector length result must be int, got {instruction.result.type}")

    def _verify_matrix_rows(
        self,
        instruction: SSAMatrixRows,
        value_types: dict[str, IRType],
    ) -> None:
        self._require_defined(instruction.matrix, value_types)
        if not isinstance(instruction.matrix.type, MatrixType):
            self._fail(f"Matrix rows expects matrix value, got {instruction.matrix.type}")
        if instruction.rows <= 0:
            self._fail(f"Matrix rows count must be positive, got {instruction.rows}")
        if not isinstance(instruction.result.type, IntType):
            self._fail(f"Matrix rows result must be int, got {instruction.result.type}")

    def _verify_matrix_columns(
        self,
        instruction: SSAMatrixColumns,
        value_types: dict[str, IRType],
    ) -> None:
        self._require_defined(instruction.matrix, value_types)
        if not isinstance(instruction.matrix.type, MatrixType):
            self._fail(f"Matrix columns expects matrix value, got {instruction.matrix.type}")
        if instruction.columns <= 0:
            self._fail(f"Matrix columns count must be positive, got {instruction.columns}")
        if not isinstance(instruction.result.type, IntType):
            self._fail(f"Matrix columns result must be int, got {instruction.result.type}")

    def _verify_phi(
        self,
        instruction: SSAPhi,
        block: SSABasicBlock,
        blocks: dict[str, SSABasicBlock],
        predecessors: dict[str, set[str]],
        value_types: dict[str, IRType],
    ) -> None:
        if not instruction.incoming:
            self._fail(f"Phi '{self._value(instruction.result)}' has no incoming values")

        seen_blocks: set[str] = set()
        for incoming_block, value in instruction.incoming:
            if incoming_block not in blocks:
                self._fail(
                    f"Phi incoming block '{incoming_block}' does not exist "
                    f"in function block '{block.name}'"
                )
            if incoming_block in seen_blocks:
                self._fail(
                    f"Duplicate incoming block '{incoming_block}' "
                    f"for phi '{self._value(instruction.result)}'"
                )
            seen_blocks.add(incoming_block)

            if incoming_block not in predecessors[block.name]:
                self._fail(
                    f"Phi incoming block '{incoming_block}' is not a predecessor "
                    f"of block '{block.name}'"
                )

            self._require_defined(value, value_types)
            if value.type != instruction.result.type:
                self._fail(
                    f"Phi '{self._value(instruction.result)}' type mismatch: "
                    f"expected {instruction.result.type}, got {value.type}"
                )

    def _verify_return(
        self,
        function: SSAFunction,
        instruction: SSAReturn,
        value_types: dict[str, IRType],
    ) -> None:
        if instruction.value is None:
            if not isinstance(function.return_type, VoidType):
                self._fail(
                    f"Return type mismatch: expected {function.return_type}, got void"
                )
            return

        self._require_defined(instruction.value, value_types)
        if instruction.value.type != function.return_type:
            self._fail(
                f"Return type mismatch: expected {function.return_type}, "
                f"got {instruction.value.type}"
            )

    def _verify_const(self, instruction: SSAConst) -> None:
        value = instruction.value
        result_type = instruction.result.type

        if isinstance(value, bool):
            expected: IRType | tuple[type[IRType], ...] = BoolType()
        elif isinstance(value, int):
            expected = IntType()
        elif isinstance(value, float):
            expected = (FloatType, DoubleType)
        elif isinstance(value, complex):
            expected = ComplexType()
        elif isinstance(value, str):
            expected = StringType()
        elif value is None:
            return
        else:
            return

        if isinstance(expected, tuple):
            if not isinstance(result_type, expected):
                expected_text = " or ".join(str(type_()) for type_ in expected)
                self._fail(
                    f"Const type mismatch: expected {expected_text}, got {result_type}"
                )
            return

        if result_type != expected:
            self._fail(f"Const type mismatch: expected {expected}, got {result_type}")

    def _binary_result_type(self, instruction: SSABinaryOp) -> IRType:
        left = instruction.left.type
        right = instruction.right.type
        operator = instruction.operator

        if operator == "add" and isinstance(left, StringType) and isinstance(right, StringType):
            return StringType()

        if operator in {"add", "sub", "mul", "div", "rem", "mod"}:
            if not isinstance(left, self._NUMERIC_TYPES) or not isinstance(
                right,
                self._NUMERIC_TYPES,
            ):
                self._fail(
                    f"Binary op '{operator}' requires compatible operands, "
                    f"got {left} and {right}"
                )
            if operator in {"rem", "mod"} and (
                not isinstance(left, self._REAL_TYPES)
                or not isinstance(right, self._REAL_TYPES)
            ):
                self._fail(
                    f"Binary op '{operator}' requires compatible operands, "
                    f"got {left} and {right}"
                )
            if operator == "div" and isinstance(left, IntType) and isinstance(right, IntType):
                return DoubleType()
            if isinstance(left, ComplexType) or isinstance(right, ComplexType):
                return ComplexType()
            if isinstance(left, DoubleType) or isinstance(right, DoubleType):
                return DoubleType()
            if isinstance(left, FloatType) or isinstance(right, FloatType):
                return FloatType()
            return IntType()

        if operator in {"eq", "ne"}:
            if left != right:
                self._fail(
                    f"Binary op '{operator}' requires compatible operands, "
                    f"got {left} and {right}"
                )
            return BoolType()

        if operator in {"lt", "le", "gt", "ge"}:
            if not isinstance(left, self._REAL_TYPES) or not isinstance(
                right,
                self._REAL_TYPES,
            ):
                self._fail(
                    f"Binary op '{operator}' requires compatible operands, "
                    f"got {left} and {right}"
                )
            return BoolType()

        if operator in {"and", "or"}:
            if not isinstance(left, BoolType) or not isinstance(right, BoolType):
                self._fail(
                    f"Binary op '{operator}' requires compatible operands, "
                    f"got {left} and {right}"
                )
            return BoolType()

        self._fail(f"Unsupported binary operator '{operator}'")

    def _compare_operand_result_type(self, instruction: SSACompareOp) -> IRType:
        left = instruction.left.type
        right = instruction.right.type
        operator = instruction.operator

        if operator in {"lt", "le", "gt", "ge"}:
            if not (
                isinstance(left, IntType)
                and isinstance(right, IntType)
                or isinstance(left, DoubleType)
                and isinstance(right, DoubleType)
            ):
                self._fail(
                    f"Compare op '{operator}' requires int or double operands, got {left} and {right}"
                )
            return BoolType()

        if operator in {"eq", "ne"}:
            if left != right:
                self._fail(
                    f"Compare op '{operator}' requires compatible operands, "
                    f"got {left} and {right}"
                )
            if not isinstance(left, (IntType, DoubleType, BoolType, StringType)):
                self._fail(
                    f"Compare op '{operator}' does not support operands of type {left}"
                )
            return BoolType()

        self._fail(f"Unsupported compare operator '{operator}'")

    def _verify_cast(self, instruction: SSACast) -> None:
        source = instruction.value.type
        target = instruction.result.type
        if (
            isinstance(source, IntType)
            and isinstance(target, DoubleType)
            or isinstance(source, DoubleType)
            and isinstance(target, IntType)
        ):
            return
        self._fail(f"Cast requires int/double operands, got {source} to {target}")

    def _require_defined(
        self,
        value: SSAValue,
        value_types: dict[str, IRType],
    ) -> None:
        expected_type = value_types.get(value.name)
        if expected_type is None:
            self._fail(f"Undefined value '{self._value(value)}'")
        if expected_type != value.type:
            self._fail(
                f"Value '{self._value(value)}' type mismatch: "
                f"expected {expected_type}, got {value.type}"
            )

    def _require_type(self, actual: IRType, expected: IRType, message: str) -> None:
        if actual != expected:
            self._fail(f"{message}: expected {expected}, got {actual}")

    @staticmethod
    def _instruction_result(instruction: SSAInstruction) -> SSAValue | None:
        if isinstance(instruction, (SSAConst, SSABinaryOp, SSACompareOp, SSACast, SSAPhi)):
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
                SSAMatrixAdd,
                SSAVectorSub,
                SSAMatrixSub,
            ),
        ):
            return instruction.result
        return None

    @staticmethod
    def _successors(block: SSABasicBlock) -> tuple[str, ...]:
        terminator = block.instructions[-1]
        if isinstance(terminator, SSAJump):
            return (terminator.target,)
        if isinstance(terminator, SSABranch):
            return (terminator.true_target, terminator.false_target)
        return ()

    def _verify_type(self, type_: IRType, context: str) -> None:
        if not self._is_valid_type(type_):
            self._fail(f"Invalid SSA type for {context}: {type_!r}")

    def _is_valid_type(self, type_: IRType) -> bool:
        if isinstance(
            type_,
            (
                IntType,
                FloatType,
                DoubleType,
                BoolType,
                StringType,
                VoidType,
                ComplexType,
                StructType,
                ClassRefType,
                InterfaceType,
                EnumType,
            ),
        ):
            return True
        if isinstance(type_, NullableType):
            return self._is_valid_type(type_.inner)
        if isinstance(type_, (ListType, ArrayType, VectorType, MatrixType)):
            return self._is_valid_type(type_.element)
        return False

    @staticmethod
    def _value(value: SSAValue) -> str:
        return value.name if value.name.startswith("%") else f"%{value.name}"

    @staticmethod
    def _fail(message: str) -> NoReturn:
        raise SSAVerificationError(message)
