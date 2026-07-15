from __future__ import annotations

from dataclasses import dataclass
from typing import NoReturn

from .model import (
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
    IREnumConstant,
    IRFunction,
    IRFunctionRef,
    IRInstruction,
    IRJump,
    IRListGet,
    IRListCopy,
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
    IROuterProduct,
    IRPrint,
    IRStructGet,
    IRStructNew,
    IRStructSet,
    IRMethodResultNew,
    IRMethodResultReceiver,
    IRMethodResultValue,
    IRReturn,
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
    ComplexType,
    DoubleType,
    EnumType,
    FloatType,
    FunctionType,
    IntType,
    InterfaceType,
    IRType,
    ListType,
    MatrixType,
    MethodResultType,
    NullableType,
    StringType,
    StructType,
    VectorType,
    VoidType,
)
from .scalar_math import scalar_math_result_type


class IRVerificationError(ValueError):
    """Raised when an IR module is internally inconsistent."""


@dataclass(frozen=True)
class _State:
    values: frozenset[str]
    slots: frozenset[str]

    def intersect(self, other: _State) -> _State:
        return _State(
            values=self.values & other.values,
            slots=self.slots & other.slots,
        )


class IRVerifier:
    """Validate the initial executable Aether IR subset."""

    _TERMINATORS = (IRReturn, IRJump, IRBranch)
    _NUMERIC_TYPES = (IntType, FloatType, DoubleType, ComplexType)
    _REAL_TYPES = (IntType, FloatType, DoubleType)

    def __init__(self, module: IRModule) -> None:
        self.module = module
        self._functions: dict[str, IRFunction] = {}
        self._structs = {}

    def verify(self) -> IRModule:
        """Verify the module and return it unchanged on success."""
        self._functions = {}
        self._structs = {definition.name: definition for definition in self.module.structs}
        self._verify_module()
        return self.module

    def _verify_module(self) -> None:
        self._verify_struct_definitions()
        seen: set[str] = set()
        for function in self.module.functions:
            if function.name in seen:
                self._fail(f"Duplicate function '{function.name}'")
            seen.add(function.name)
            self._functions[function.name] = function

        for function in self.module.functions:
            self._verify_function(function)

    def _verify_struct_definitions(self) -> None:
        if len(self._structs) != len(self.module.structs):
            self._fail("Duplicate nominal struct definition")
        edges: dict[str, tuple[str, ...]] = {}
        for definition in self.module.structs:
            if not definition.name:
                self._fail("Struct definition name must not be empty")
            field_names = [name for name, _type in definition.fields]
            if len(field_names) != len(set(field_names)):
                self._fail(f"Struct '{definition.name}' has duplicate fields")
            for field_name, field_type in definition.fields:
                if isinstance(field_type, VoidType) or not self._is_valid_type(field_type):
                    self._fail(
                        f"Struct '{definition.name}' field '{field_name}' has invalid or incomplete type {field_type}"
                    )
            edges[definition.name] = tuple(
                field_type.name
                for _field_name, field_type in definition.fields
                if isinstance(field_type, StructType)
            )

        visited: set[str] = set()
        active: list[str] = []

        def visit(name: str) -> None:
            if name in visited:
                return
            if name in active:
                cycle = " -> ".join((*active[active.index(name):], name))
                self._fail(f"Recursive by-value struct layout has infinite size: {cycle}")
            active.append(name)
            for target in edges.get(name, ()):
                visit(target)
            active.pop()
            visited.add(name)

        for name in edges:
            visit(name)

    def _verify_function(self, function: IRFunction) -> None:
        self._verify_parameters(function)
        self._verify_type(function.return_type, f"return type of function '{function.name}'")

        if not function.blocks:
            self._fail(f"Function '{function.name}' has no blocks")

        blocks = self._collect_blocks(function)
        if "entry" not in blocks:
            self._fail(f"Function '{function.name}' has no entry block")

        self._verify_block_structure(function, blocks)

        value_types = self._collect_value_types(function)
        slot_types = self._collect_slot_types(function)

        self._verify_reachable_values(function, blocks, value_types, slot_types)
        self._verify_all_non_void_paths_return(function, blocks)

    def _verify_parameters(self, function: IRFunction) -> None:
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

    def _collect_blocks(self, function: IRFunction) -> dict[str, IRBasicBlock]:
        blocks: dict[str, IRBasicBlock] = {}
        for block in function.blocks:
            if block.name in blocks:
                self._fail(f"Duplicate block '{block.name}' in function '{function.name}'")
            blocks[block.name] = block
        return blocks

    def _verify_block_structure(
        self,
        function: IRFunction,
        blocks: dict[str, IRBasicBlock],
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
        function: IRFunction,
        instruction: IRInstruction,
        blocks: dict[str, IRBasicBlock],
    ) -> None:
        if isinstance(instruction, IRJump):
            if instruction.target not in blocks:
                self._fail(
                    f"Unknown jump target '{instruction.target}' in function '{function.name}'"
                )
            return

        if isinstance(instruction, IRBranch):
            for target in (instruction.true_target, instruction.false_target):
                if target not in blocks:
                    self._fail(
                        f"Unknown branch target '{target}' in function '{function.name}'"
                    )

    def _collect_value_types(self, function: IRFunction) -> dict[str, IRType]:
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
        value: IRValue,
        function: IRFunction,
    ) -> None:
        existing = value_types.get(value.name)
        if existing is not None:
            self._fail(f"Duplicate value '{self._value(value)}' in function '{function.name}'")
        value_types[value.name] = value.type

    def _collect_slot_types(self, function: IRFunction) -> dict[str, IRType]:
        slot_types: dict[str, IRType] = {}
        for block in function.blocks:
            for instruction in block.instructions:
                if not isinstance(instruction, IRStore):
                    continue
                self._verify_type(instruction.slot.type, f"slot '{self._value(instruction.slot)}'")
                existing = slot_types.get(instruction.slot.name)
                if existing is not None and existing != instruction.slot.type:
                    self._fail(
                        f"Slot '{self._value(instruction.slot)}' type mismatch: "
                        f"expected {existing}, got {instruction.slot.type}"
                    )
                slot_types[instruction.slot.name] = instruction.slot.type
        return slot_types

    def _verify_reachable_values(
        self,
        function: IRFunction,
        blocks: dict[str, IRBasicBlock],
        value_types: dict[str, IRType],
        slot_types: dict[str, IRType],
    ) -> None:
        entry = _State(
            values=frozenset(parameter.name for parameter in function.parameters),
            slots=frozenset(),
        )
        inputs: dict[str, _State] = {"entry": entry}
        worklist = ["entry"]

        while worklist:
            block_name = worklist.pop(0)
            block = blocks[block_name]
            state = inputs[block_name]
            output = self._transfer_block(
                function,
                block,
                state,
                value_types,
                slot_types,
            )

            for successor in self._successors(block):
                existing = inputs.get(successor)
                updated = output if existing is None else existing.intersect(output)
                if updated != existing:
                    inputs[successor] = updated
                    worklist.append(successor)

        unreachable_state = _State(
            values=frozenset(value_types),
            slots=frozenset(slot_types),
        )
        for block_name, block in blocks.items():
            if block_name not in inputs:
                # Unreachable blocks still get local instruction/type checks, but
                # they have no executable incoming path that can prove slot stores.
                self._transfer_block(
                    function,
                    block,
                    unreachable_state,
                    value_types,
                    slot_types,
                )

    def _transfer_block(
        self,
        function: IRFunction,
        block: IRBasicBlock,
        state: _State,
        value_types: dict[str, IRType],
        slot_types: dict[str, IRType],
    ) -> _State:
        current = state
        for instruction in block.instructions:
            current = self._transfer_instruction(
                function,
                instruction,
                current,
                value_types,
                slot_types,
            )
        return current

    def _transfer_instruction(
        self,
        function: IRFunction,
        instruction: IRInstruction,
        state: _State,
        value_types: dict[str, IRType],
        slot_types: dict[str, IRType],
    ) -> _State:
        if isinstance(instruction, IRConst):
            self._verify_const(instruction)
            return self._define_value(state, instruction.result)

        if isinstance(instruction, IRLoad):
            self._require_slot_exists(instruction.slot, slot_types)
            self._require_slot_stored(instruction.slot, state)
            self._require_type(
                instruction.result.type,
                slot_types[instruction.slot.name],
                f"Load type mismatch for slot '{self._value(instruction.slot)}'",
            )
            return self._define_value(state, instruction.result)

        if isinstance(instruction, IRStore):
            self._require_defined(instruction.value, state, value_types)
            self._require_slot_exists(instruction.slot, slot_types)
            self._require_type(
                instruction.value.type,
                slot_types[instruction.slot.name],
                f"Store type mismatch for slot '{self._value(instruction.slot)}'",
            )
            return _State(state.values, state.slots | {instruction.slot.name})

        if isinstance(instruction, IRBinaryOp):
            self._require_defined(instruction.left, state, value_types)
            self._require_defined(instruction.right, state, value_types)
            result_type = self._binary_result_type(instruction)
            self._require_type(
                instruction.result.type,
                result_type,
                f"Binary op '{instruction.operator}' result type mismatch",
            )
            return self._define_value(state, instruction.result)

        if isinstance(instruction, IRUnaryOp):
            self._require_defined(instruction.operand, state, value_types)
            self._verify_unary(instruction)
            return self._define_value(state, instruction.result)

        if isinstance(instruction, IRCompareOp):
            self._require_defined(instruction.left, state, value_types)
            self._require_defined(instruction.right, state, value_types)
            result_type = self._compare_result_type(instruction)
            self._require_type(
                instruction.result.type,
                result_type,
                f"Compare op '{instruction.operator}' result type mismatch",
            )
            return self._define_value(state, instruction.result)

        if isinstance(instruction, IRCast):
            self._require_defined(instruction.value, state, value_types)
            self._verify_cast(instruction)
            return self._define_value(state, instruction.result)

        if isinstance(instruction, IRCall):
            self._verify_call(instruction, state, value_types)
            if instruction.result is None:
                return state
            return self._define_value(state, instruction.result)

        if isinstance(instruction, IRFunctionRef):
            callee = self._functions.get(instruction.function)
            if callee is None:
                self._fail(f"Reference to undefined function '{instruction.function}'")
            expected = FunctionType(
                tuple(parameter.type for parameter in callee.parameters),
                callee.return_type,
            )
            self._require_type(
                instruction.result.type,
                expected,
                f"Function reference '{instruction.function}' type mismatch",
            )
            return self._define_value(state, instruction.result)

        if isinstance(instruction, IRCallIndirect):
            self._verify_indirect_call(instruction, state, value_types)
            if instruction.result is None:
                return state
            return self._define_value(state, instruction.result)

        if isinstance(instruction, IRPrint):
            self._require_defined(instruction.value, state, value_types)
            if not isinstance(
                instruction.value.type,
                (
                    IntType,
                    BoolType,
                    StringType,
                    DoubleType,
                    EnumType,
                    ArrayType,
                    ListType,
                    VectorType,
                    MatrixType,
                    StructType,
                ),
            ):
                self._fail(
                    "Print value must be a printable scalar or aggregate, "
                    f"got {instruction.value.type}"
                )
            if isinstance(instruction.value.type, VectorType):
                if instruction.aggregate_shape is None or len(instruction.aggregate_shape) != 1:
                    self._fail("Vector print requires one known length")
            elif isinstance(instruction.value.type, MatrixType):
                if instruction.aggregate_shape is None or len(instruction.aggregate_shape) != 2:
                    self._fail("Matrix print requires known rows and columns")
            elif instruction.aggregate_shape is not None:
                self._fail("Scalar print must not carry an aggregate shape")
            return state

        if isinstance(instruction, IRStructNew):
            definition = self._structs.get(instruction.result.type.name) if isinstance(instruction.result.type, StructType) else None
            if definition is None or len(instruction.fields) != len(definition.fields):
                self._fail("Struct new requires a declared struct and all canonical fields")
            for value, (_name, field_type) in zip(instruction.fields, definition.fields):
                self._require_defined(value, state, value_types)
                self._require_type(value.type, field_type, "Struct field type mismatch")
            return self._define_value(state, instruction.result)

        if isinstance(instruction, IRStructGet):
            self._require_defined(instruction.struct, state, value_types)
            definition = self._structs.get(instruction.struct.type.name) if isinstance(instruction.struct.type, StructType) else None
            if definition is None or not 0 <= instruction.field_index < len(definition.fields):
                self._fail("Struct get requires a valid canonical field")
            self._require_type(instruction.result.type, definition.fields[instruction.field_index][1], "Struct get result type mismatch")
            return self._define_value(state, instruction.result)

        if isinstance(instruction, IRStructSet):
            self._require_defined(instruction.struct, state, value_types)
            self._require_defined(instruction.value, state, value_types)
            definition = self._structs.get(instruction.struct.type.name) if isinstance(instruction.struct.type, StructType) else None
            if definition is None or not 0 <= instruction.field_index < len(definition.fields):
                self._fail("Struct set requires a valid canonical field")
            self._require_type(instruction.value.type, definition.fields[instruction.field_index][1], "Struct set value type mismatch")
            self._require_type(instruction.result.type, instruction.struct.type, "Struct set result type mismatch")
            return self._define_value(state, instruction.result)

        if isinstance(instruction, IRMethodResultNew):
            self._require_defined(instruction.receiver, state, value_types)
            if not isinstance(instruction.result.type, MethodResultType):
                self._fail("Method result requires MethodResultType")
            self._require_type(instruction.receiver.type, instruction.result.type.receiver, "Method receiver type mismatch")
            if isinstance(instruction.result.type.value, VoidType):
                if instruction.value is not None:
                    self._fail("Void method result cannot contain a source value")
            else:
                if instruction.value is None:
                    self._fail("Non-void method result requires a source value")
                self._require_defined(instruction.value, state, value_types)
                self._require_type(instruction.value.type, instruction.result.type.value, "Method value type mismatch")
            return self._define_value(state, instruction.result)

        if isinstance(instruction, IRMethodResultReceiver):
            self._require_defined(instruction.method_result, state, value_types)
            if not isinstance(instruction.method_result.type, MethodResultType):
                self._fail("Method receiver extraction requires MethodResultType")
            self._require_type(instruction.result.type, instruction.method_result.type.receiver, "Method receiver result mismatch")
            return self._define_value(state, instruction.result)

        if isinstance(instruction, IRMethodResultValue):
            self._require_defined(instruction.method_result, state, value_types)
            if not isinstance(instruction.method_result.type, MethodResultType):
                self._fail("Method value extraction requires MethodResultType")
            self._require_type(instruction.result.type, instruction.method_result.type.value, "Method value result mismatch")
            return self._define_value(state, instruction.result)

        if isinstance(instruction, IRArrayNew):
            self._verify_array_new(instruction, state, value_types)
            return self._define_value(state, instruction.result)

        if isinstance(instruction, IRListNew):
            self._verify_list_new(instruction, state, value_types)
            return self._define_value(state, instruction.result)

        if isinstance(instruction, IRListCopy):
            self._verify_list_copy(instruction, state, value_types)
            return self._define_value(state, instruction.result)

        if isinstance(instruction, IRListContains):
            self._verify_list_contains(instruction, state, value_types)
            return self._define_value(state, instruction.result)

        if isinstance(instruction, IRListIndexOf):
            self._verify_list_index_of(instruction, state, value_types)
            return self._define_value(state, instruction.result)

        if isinstance(instruction, IRListClear):
            self._verify_list_clear(instruction, state, value_types)
            return state

        if isinstance(instruction, IRListPush):
            self._verify_list_push(instruction, state, value_types)
            return state

        if isinstance(instruction, IRListInsert):
            self._verify_list_insert(instruction, state, value_types)
            return state

        if isinstance(instruction, IRListPop):
            self._verify_list_pop(instruction, state, value_types)
            return self._define_value(state, instruction.result)

        if isinstance(instruction, IRListRemoveAt):
            self._verify_list_remove_at(instruction, state, value_types)
            return self._define_value(state, instruction.result)

        if isinstance(instruction, IRListReverse):
            self._verify_list_reverse(instruction, state, value_types)
            return state
        if isinstance(instruction, IRSequenceSort):
            self._verify_sequence_sort(instruction, state, value_types)
            return state

        if isinstance(instruction, IRVectorNew):
            self._verify_vector_new(instruction, state, value_types)
            return self._define_value(state, instruction.result)

        if isinstance(instruction, IRMatrixNew):
            self._verify_matrix_new(instruction, state, value_types)
            return self._define_value(state, instruction.result)

        if isinstance(instruction, IRVectorAdd):
            self._verify_vector_add(instruction, state, value_types)
            return self._define_value(state, instruction.result)

        if isinstance(instruction, IRVectorSub):
            self._verify_vector_sub(instruction, state, value_types)
            return self._define_value(state, instruction.result)

        if isinstance(instruction, IRVectorScale):
            self._verify_vector_scale(instruction, state, value_types)
            return self._define_value(state, instruction.result)

        if isinstance(instruction, IRVectorDot):
            self._verify_vector_dot(instruction, state, value_types)
            return self._define_value(state, instruction.result)

        if isinstance(instruction, IROuterProduct):
            self._verify_outer_product(instruction, state, value_types)
            return self._define_value(state, instruction.result)

        if isinstance(instruction, IRMatrixAdd):
            self._verify_matrix_add(instruction, state, value_types)
            return self._define_value(state, instruction.result)

        if isinstance(instruction, IRMatrixSub):
            self._verify_matrix_sub(instruction, state, value_types)
            return self._define_value(state, instruction.result)

        if isinstance(instruction, IRMatrixScale):
            self._verify_matrix_scale(instruction, state, value_types)
            return self._define_value(state, instruction.result)

        if isinstance(instruction, IRMatrixMatMul):
            self._verify_matrix_matmul(instruction, state, value_types)
            return self._define_value(state, instruction.result)

        if isinstance(instruction, IRMatrixVectorMul):
            self._verify_matrix_vector_mul(instruction, state, value_types)
            return self._define_value(state, instruction.result)

        if isinstance(instruction, IRVectorMatrixMul):
            self._verify_vector_matrix_mul(instruction, state, value_types)
            return self._define_value(state, instruction.result)

        if isinstance(instruction, IRArrayGet):
            self._verify_array_get(instruction, state, value_types)
            return self._define_value(state, instruction.result)

        if isinstance(instruction, IRArraySlice):
            self._verify_array_slice(instruction, state, value_types)
            return self._define_value(state, instruction.result)

        if isinstance(instruction, IRListGet):
            self._verify_list_get(instruction, state, value_types)
            return self._define_value(state, instruction.result)

        if isinstance(instruction, IRVectorGet):
            self._verify_vector_get(instruction, state, value_types)
            return self._define_value(state, instruction.result)

        if isinstance(instruction, IRMatrixGet):
            self._verify_matrix_get(instruction, state, value_types)
            return self._define_value(state, instruction.result)

        if isinstance(instruction, IRVectorLength):
            self._verify_vector_length(instruction, state, value_types)
            return self._define_value(state, instruction.result)

        if isinstance(instruction, IRMatrixRows):
            self._verify_matrix_rows(instruction, state, value_types)
            return self._define_value(state, instruction.result)

        if isinstance(instruction, IRMatrixColumns):
            self._verify_matrix_columns(instruction, state, value_types)
            return self._define_value(state, instruction.result)

        if isinstance(instruction, IRArraySet):
            self._verify_array_set(instruction, state, value_types)
            return state

        if isinstance(instruction, IRListSet):
            self._verify_list_set(instruction, state, value_types)
            return state

        if isinstance(instruction, IRVectorSet):
            self._verify_vector_set(instruction, state, value_types)
            return state

        if isinstance(instruction, IRMatrixSet):
            self._verify_matrix_set(instruction, state, value_types)
            return state

        if isinstance(instruction, IRArrayLength):
            self._verify_array_length(instruction, state, value_types)
            return self._define_value(state, instruction.result)

        if isinstance(instruction, IRListLength):
            self._verify_list_length(instruction, state, value_types)
            return self._define_value(state, instruction.result)

        if isinstance(instruction, IRListIsEmpty):
            self._verify_list_is_empty(instruction, state, value_types)
            return self._define_value(state, instruction.result)

        if isinstance(instruction, IRBranch):
            self._require_defined(instruction.condition, state, value_types)
            if not isinstance(instruction.condition.type, BoolType):
                self._fail("Branch condition must be bool")
            return state

        if isinstance(instruction, IRJump):
            return state

        if isinstance(instruction, IRReturn):
            self._verify_return(function, instruction, state, value_types)
            return state

        self._fail(f"Unsupported IR instruction '{type(instruction).__name__}'")

    def _verify_call(
        self,
        instruction: IRCall,
        state: _State,
        value_types: dict[str, IRType],
    ) -> None:
        if instruction.builtin is not None:
            for argument in instruction.arguments:
                self._require_defined(argument, state, value_types)
            if instruction.result is None:
                self._fail(f"Scalar builtin '{instruction.builtin}' must produce a result")
            try:
                expected_type = scalar_math_result_type(
                    instruction.builtin,
                    tuple(argument.type for argument in instruction.arguments),
                )
            except ValueError as exc:
                self._fail(str(exc))
            if instruction.function != instruction.builtin:
                self._fail("Scalar builtin call must retain its canonical semantic name")
            if instruction.result.type != expected_type:
                self._fail(
                    f"Scalar builtin '{instruction.builtin}' result type mismatch: "
                    f"expected {expected_type}, got {instruction.result.type}"
                )
            return
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
            self._require_defined(argument, state, value_types)
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

    def _verify_indirect_call(
        self,
        instruction: IRCallIndirect,
        state: _State,
        value_types: dict[str, IRType],
    ) -> None:
        self._require_defined(instruction.callee, state, value_types)
        if not isinstance(instruction.callee.type, FunctionType):
            self._fail(f"Indirect call requires callable callee, got {instruction.callee.type}")
        signature = instruction.callee.type
        if len(instruction.arguments) != len(signature.parameter_types):
            self._fail(
                f"Indirect call expects {len(signature.parameter_types)} arguments, "
                f"got {len(instruction.arguments)}"
            )
        for index, (argument, parameter_type) in enumerate(
            zip(instruction.arguments, signature.parameter_types), start=1
        ):
            self._require_defined(argument, state, value_types)
            self._require_type(
                argument.type,
                parameter_type,
                f"Indirect call argument {index} type mismatch",
            )
        if isinstance(signature.return_type, VoidType):
            if instruction.result is not None:
                self._fail("Indirect call to void callable cannot produce a value")
        elif instruction.result is None:
            self._fail(
                f"Indirect call must produce a result of type {signature.return_type}"
            )
        else:
            self._require_type(
                instruction.result.type,
                signature.return_type,
                "Indirect call result type mismatch",
            )

    def _verify_array_new(
        self,
        instruction: IRArrayNew,
        state: _State,
        value_types: dict[str, IRType],
    ) -> None:
        if not isinstance(instruction.result.type, ArrayType):
            self._fail(f"Array new result must be array type, got {instruction.result.type}")
        for element in instruction.elements:
            self._require_defined(element, state, value_types)
            if element.type != instruction.result.type.element:
                self._fail(
                    f"Array literal element type mismatch: expected "
                    f"{instruction.result.type.element}, got {element.type}"
                )

    def _verify_list_new(
        self,
        instruction: IRListNew,
        state: _State,
        value_types: dict[str, IRType],
    ) -> None:
        if not isinstance(instruction.result.type, ListType):
            self._fail(f"List new result must be list type, got {instruction.result.type}")
        for element in instruction.elements:
            self._require_defined(element, state, value_types)
            if element.type != instruction.result.type.element:
                self._fail(
                    f"List literal element type mismatch: expected "
                    f"{instruction.result.type.element}, got {element.type}"
                )

    def _verify_vector_new(
        self,
        instruction: IRVectorNew,
        state: _State,
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
            self._require_defined(element, state, value_types)
            if element.type != instruction.result.type.element:
                self._fail(
                    f"Vector literal element type mismatch: expected "
                    f"{instruction.result.type.element}, got {element.type}"
                )

    def _verify_matrix_new(
        self,
        instruction: IRMatrixNew,
        state: _State,
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
            self._require_defined(element, state, value_types)
            if element.type != instruction.result.type.element:
                self._fail(
                    f"Matrix literal element type mismatch: expected "
                    f"{instruction.result.type.element}, got {element.type}"
                )

    def _verify_vector_add(
        self,
        instruction: IRVectorAdd,
        state: _State,
        value_types: dict[str, IRType],
    ) -> None:
        self._verify_vector_binary(instruction, state, value_types, "add")

    def _verify_vector_sub(
        self,
        instruction: IRVectorSub,
        state: _State,
        value_types: dict[str, IRType],
    ) -> None:
        self._verify_vector_binary(instruction, state, value_types, "sub")

    def _verify_vector_binary(
        self,
        instruction: IRVectorAdd | IRVectorSub,
        state: _State,
        value_types: dict[str, IRType],
        operation: str,
    ) -> None:
        self._require_defined(instruction.left, state, value_types)
        self._require_defined(instruction.right, state, value_types)
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

    def _verify_vector_scale(
        self,
        instruction: IRVectorScale,
        state: _State,
        value_types: dict[str, IRType],
    ) -> None:
        self._require_defined(instruction.vector, state, value_types)
        self._require_defined(instruction.scalar, state, value_types)
        if not isinstance(instruction.result.type, VectorType):
            self._fail(f"Vector scale result must be vector type, got {instruction.result.type}")
        if not isinstance(instruction.vector.type, VectorType):
            self._fail(f"Vector scale expects vector operand, got {instruction.vector.type}")
        if instruction.length <= 0:
            self._fail(f"Vector scale length must be positive, got {instruction.length}")
        if instruction.orientation != instruction.result.type.orientation:
            self._fail("Vector scale instruction orientation must match result type")
        if instruction.result.type != instruction.vector.type:
            self._fail(
                f"Vector scale result type mismatch: expected {instruction.vector.type}, got {instruction.result.type}"
            )
        if instruction.scalar.type != instruction.vector.type.element:
            self._fail(
                f"Vector scale scalar type mismatch: expected {instruction.vector.type.element}, got {instruction.scalar.type}"
            )

    def _verify_vector_dot(
        self,
        instruction: IRVectorDot,
        state: _State,
        value_types: dict[str, IRType],
    ) -> None:
        self._require_defined(instruction.left, state, value_types)
        self._require_defined(instruction.right, state, value_types)
        if not isinstance(instruction.left.type, VectorType) or not isinstance(instruction.right.type, VectorType):
            self._fail(
                f"Vector dot expects vector operands, got {instruction.left.type} and {instruction.right.type}"
            )
        if instruction.left.type.orientation != "row" or instruction.right.type.orientation != "column":
            self._fail("Vector dot is only defined for Vector<Row> * Vector<Column>")
        if instruction.length <= 0:
            self._fail(f"Vector dot length must be positive, got {instruction.length}")
        expected = self._numeric_binary_result_type(
            instruction.left.type.element,
            instruction.right.type.element,
        )
        if instruction.result.type != expected:
            self._fail(
                f"Vector dot result type mismatch: expected {expected}, got {instruction.result.type}"
            )

    def _verify_outer_product(
        self,
        instruction: IROuterProduct,
        state: _State,
        value_types: dict[str, IRType],
    ) -> None:
        self._require_defined(instruction.column, state, value_types)
        self._require_defined(instruction.row, state, value_types)
        if not isinstance(instruction.result.type, MatrixType):
            self._fail(f"Outer product result must be matrix type, got {instruction.result.type}")
        if not isinstance(instruction.column.type, VectorType) or not isinstance(instruction.row.type, VectorType):
            self._fail(
                f"Outer product expects vector operands, got {instruction.column.type} and {instruction.row.type}"
            )
        if instruction.column.type.orientation != "column" or instruction.row.type.orientation != "row":
            self._fail("Outer product is only defined for Vector<Column> * Vector<Row>")
        if instruction.rows <= 0 or instruction.cols <= 0:
            self._fail(f"Outer product dimensions must be positive, got {instruction.rows}x{instruction.cols}")
        expected_element = self._numeric_binary_result_type(
            instruction.column.type.element,
            instruction.row.type.element,
        )
        if instruction.result.type.element != expected_element:
            self._fail(
                f"Outer product result element type mismatch: expected "
                f"{expected_element}, got {instruction.result.type.element}"
            )

    def _verify_matrix_add(
        self,
        instruction: IRMatrixAdd,
        state: _State,
        value_types: dict[str, IRType],
    ) -> None:
        self._verify_matrix_binary(instruction, state, value_types, "add")

    def _verify_matrix_sub(
        self,
        instruction: IRMatrixSub,
        state: _State,
        value_types: dict[str, IRType],
    ) -> None:
        self._verify_matrix_binary(instruction, state, value_types, "sub")

    def _verify_matrix_binary(
        self,
        instruction: IRMatrixAdd | IRMatrixSub,
        state: _State,
        value_types: dict[str, IRType],
        operation: str,
    ) -> None:
        self._require_defined(instruction.left, state, value_types)
        self._require_defined(instruction.right, state, value_types)
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

    def _verify_matrix_scale(
        self,
        instruction: IRMatrixScale,
        state: _State,
        value_types: dict[str, IRType],
    ) -> None:
        self._require_defined(instruction.matrix, state, value_types)
        self._require_defined(instruction.scalar, state, value_types)
        if not isinstance(instruction.result.type, MatrixType):
            self._fail(f"Matrix scale result must be matrix type, got {instruction.result.type}")
        if not isinstance(instruction.matrix.type, MatrixType):
            self._fail(f"Matrix scale expects matrix operand, got {instruction.matrix.type}")
        if instruction.rows <= 0 or instruction.cols <= 0:
            self._fail(f"Matrix scale dimensions must be positive, got {instruction.rows}x{instruction.cols}")
        if instruction.result.type != instruction.matrix.type:
            self._fail(
                f"Matrix scale result type mismatch: expected {instruction.matrix.type}, got {instruction.result.type}"
            )
        if instruction.scalar.type != instruction.matrix.type.element:
            self._fail(
                f"Matrix scale scalar type mismatch: expected {instruction.matrix.type.element}, got {instruction.scalar.type}"
            )

    def _verify_matrix_matmul(
        self,
        instruction: IRMatrixMatMul,
        state: _State,
        value_types: dict[str, IRType],
    ) -> None:
        self._require_defined(instruction.left, state, value_types)
        self._require_defined(instruction.right, state, value_types)
        if not isinstance(instruction.result.type, MatrixType):
            self._fail(f"Matrix matmul result must be matrix type, got {instruction.result.type}")
        if not isinstance(instruction.left.type, MatrixType) or not isinstance(instruction.right.type, MatrixType):
            self._fail(
                f"Matrix matmul expects matrix operands, got {instruction.left.type} and {instruction.right.type}"
            )
        if instruction.rows <= 0 or instruction.inner <= 0 or instruction.cols <= 0:
            self._fail(
                f"Matrix matmul dimensions must be positive, got "
                f"{instruction.rows}x{instruction.inner} and {instruction.inner}x{instruction.cols}"
            )
        expected_element = self._numeric_binary_result_type(
            instruction.left.type.element,
            instruction.right.type.element,
        )
        if instruction.result.type.element != expected_element:
            self._fail(
                f"Matrix matmul result element type mismatch: expected "
                f"{expected_element}, got {instruction.result.type.element}"
            )

    def _verify_matrix_vector_mul(
        self,
        instruction: IRMatrixVectorMul,
        state: _State,
        value_types: dict[str, IRType],
    ) -> None:
        self._require_defined(instruction.matrix, state, value_types)
        self._require_defined(instruction.vector, state, value_types)
        if not isinstance(instruction.result.type, VectorType):
            self._fail(f"Matrix vector mul result must be vector type, got {instruction.result.type}")
        if not isinstance(instruction.matrix.type, MatrixType) or not isinstance(instruction.vector.type, VectorType):
            self._fail(
                f"Matrix vector mul expects matrix and vector operands, got "
                f"{instruction.matrix.type} and {instruction.vector.type}"
            )
        if isinstance(instruction.result.type, VectorType) and instruction.result.type.orientation != "column":
            self._fail("Matrix vector mul result must be Vector<Column>")
        if isinstance(instruction.vector.type, VectorType) and instruction.vector.type.orientation != "column":
            self._fail("Matrix vector mul operand must be Vector<Column>")
        if instruction.rows <= 0 or instruction.inner <= 0:
            self._fail(
                f"Matrix vector mul dimensions must be positive, got "
                f"{instruction.rows}x{instruction.inner} and {instruction.inner}"
            )
        expected_element = self._numeric_binary_result_type(
            instruction.matrix.type.element,
            instruction.vector.type.element,
        )
        if instruction.result.type.element != expected_element:
            self._fail(
                f"Matrix vector mul result element type mismatch: expected "
                f"{expected_element}, got {instruction.result.type.element}"
            )

    def _verify_vector_matrix_mul(
        self,
        instruction: IRVectorMatrixMul,
        state: _State,
        value_types: dict[str, IRType],
    ) -> None:
        self._require_defined(instruction.vector, state, value_types)
        self._require_defined(instruction.matrix, state, value_types)
        if not isinstance(instruction.result.type, VectorType):
            self._fail(f"Vector matrix mul result must be vector type, got {instruction.result.type}")
        if not isinstance(instruction.vector.type, VectorType) or not isinstance(instruction.matrix.type, MatrixType):
            self._fail(
                f"Vector matrix mul expects vector and matrix operands, got "
                f"{instruction.vector.type} and {instruction.matrix.type}"
            )
        if isinstance(instruction.result.type, VectorType) and instruction.result.type.orientation != "row":
            self._fail("Vector matrix mul result must be Vector<Row>")
        if isinstance(instruction.vector.type, VectorType) and instruction.vector.type.orientation != "row":
            self._fail("Vector matrix mul operand must be Vector<Row>")
        if instruction.rows <= 0 or instruction.cols <= 0:
            self._fail(
                f"Vector matrix mul dimensions must be positive, got "
                f"{instruction.rows} and {instruction.rows}x{instruction.cols}"
            )
        expected_element = self._numeric_binary_result_type(
            instruction.vector.type.element,
            instruction.matrix.type.element,
        )
        if instruction.result.type.element != expected_element:
            self._fail(
                f"Vector matrix mul result element type mismatch: expected "
                f"{expected_element}, got {instruction.result.type.element}"
            )

    def _verify_array_get(
        self,
        instruction: IRArrayGet,
        state: _State,
        value_types: dict[str, IRType],
    ) -> None:
        self._require_defined(instruction.array, state, value_types)
        self._require_defined(instruction.index, state, value_types)
        if not isinstance(instruction.array.type, ArrayType):
            self._fail(f"Array get expects array value, got {instruction.array.type}")
        if not isinstance(instruction.index.type, IntType):
            self._fail(f"Array get index must be int, got {instruction.index.type}")
        if instruction.result.type != instruction.array.type.element:
            self._fail(
                f"Array get result type mismatch: expected "
                f"{instruction.array.type.element}, got {instruction.result.type}"
            )

    def _verify_array_slice(
        self,
        instruction: IRArraySlice,
        state: _State,
        value_types: dict[str, IRType],
    ) -> None:
        self._require_defined(instruction.array, state, value_types)
        self._require_defined(instruction.start, state, value_types)
        self._require_defined(instruction.end, state, value_types)
        if not isinstance(instruction.array.type, ArrayType):
            self._fail(f"Array slice expects array value, got {instruction.array.type}")
        if not isinstance(instruction.start.type, IntType):
            self._fail(f"Array slice start must be int, got {instruction.start.type}")
        if not isinstance(instruction.end.type, IntType):
            self._fail(f"Array slice end must be int, got {instruction.end.type}")
        if instruction.result.type != instruction.array.type:
            self._fail(
                f"Array slice result type mismatch: expected "
                f"{instruction.array.type}, got {instruction.result.type}"
            )

    def _verify_list_get(
        self,
        instruction: IRListGet,
        state: _State,
        value_types: dict[str, IRType],
    ) -> None:
        self._require_defined(instruction.list_value, state, value_types)
        self._require_defined(instruction.index, state, value_types)
        if not isinstance(instruction.list_value.type, ListType):
            self._fail(f"List get expects list value, got {instruction.list_value.type}")
        if not isinstance(instruction.index.type, IntType):
            self._fail(f"List get index must be int, got {instruction.index.type}")
        if instruction.result.type != instruction.list_value.type.element:
            self._fail(
                f"List get result type mismatch: expected "
                f"{instruction.list_value.type.element}, got {instruction.result.type}"
            )

    def _verify_vector_get(
        self,
        instruction: IRVectorGet,
        state: _State,
        value_types: dict[str, IRType],
    ) -> None:
        self._require_defined(instruction.vector, state, value_types)
        self._require_defined(instruction.index, state, value_types)
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
        instruction: IRMatrixGet,
        state: _State,
        value_types: dict[str, IRType],
    ) -> None:
        self._require_defined(instruction.matrix, state, value_types)
        self._require_defined(instruction.row, state, value_types)
        self._require_defined(instruction.column, state, value_types)
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
        instruction: IRArraySet,
        state: _State,
        value_types: dict[str, IRType],
    ) -> None:
        self._require_defined(instruction.array, state, value_types)
        self._require_defined(instruction.index, state, value_types)
        self._require_defined(instruction.value, state, value_types)
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
        instruction: IRVectorSet,
        state: _State,
        value_types: dict[str, IRType],
    ) -> None:
        self._require_defined(instruction.vector, state, value_types)
        self._require_defined(instruction.index, state, value_types)
        self._require_defined(instruction.value, state, value_types)
        if not isinstance(instruction.vector.type, VectorType):
            self._fail(f"Vector set expects vector value, got {instruction.vector.type}")
        if not isinstance(instruction.index.type, IntType):
            self._fail(f"Vector set index must be int, got {instruction.index.type}")
        if instruction.value.type != instruction.vector.type.element:
            self._fail(
                f"Vector set value type mismatch: expected "
                f"{instruction.vector.type.element}, got {instruction.value.type}"
            )

    def _verify_list_set(
        self,
        instruction: IRListSet,
        state: _State,
        value_types: dict[str, IRType],
    ) -> None:
        self._require_defined(instruction.list_value, state, value_types)
        self._require_defined(instruction.index, state, value_types)
        self._require_defined(instruction.value, state, value_types)
        if not isinstance(instruction.list_value.type, ListType):
            self._fail(f"List set expects list value, got {instruction.list_value.type}")
        if not isinstance(instruction.index.type, IntType):
            self._fail(f"List set index must be int, got {instruction.index.type}")
        if instruction.value.type != instruction.list_value.type.element:
            self._fail(
                f"List set value type mismatch: expected "
                f"{instruction.list_value.type.element}, got {instruction.value.type}"
            )

    def _verify_matrix_set(
        self,
        instruction: IRMatrixSet,
        state: _State,
        value_types: dict[str, IRType],
    ) -> None:
        self._require_defined(instruction.matrix, state, value_types)
        self._require_defined(instruction.row, state, value_types)
        self._require_defined(instruction.column, state, value_types)
        self._require_defined(instruction.value, state, value_types)
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
        instruction: IRArrayLength,
        state: _State,
        value_types: dict[str, IRType],
    ) -> None:
        self._require_defined(instruction.array, state, value_types)
        if not isinstance(instruction.array.type, ArrayType):
            self._fail(f"Array length expects array value, got {instruction.array.type}")
        if not isinstance(instruction.result.type, IntType):
            self._fail(f"Array length result must be int, got {instruction.result.type}")

    def _verify_list_length(
        self,
        instruction: IRListLength,
        state: _State,
        value_types: dict[str, IRType],
    ) -> None:
        self._require_defined(instruction.list_value, state, value_types)
        if not isinstance(instruction.list_value.type, ListType):
            self._fail(f"List length expects list value, got {instruction.list_value.type}")
        if not isinstance(instruction.result.type, IntType):
            self._fail(f"List length result must be int, got {instruction.result.type}")

    def _verify_list_copy(self, instruction: IRListCopy, state: _State, value_types: dict[str, IRType]) -> None:
        self._require_defined(instruction.list_value, state, value_types)
        if not isinstance(instruction.list_value.type, ListType):
            self._fail(f"List copy expects list value, got {instruction.list_value.type}")
        self._require_type(instruction.result.type, instruction.list_value.type, "List copy result type mismatch")

    def _verify_list_contains(self, instruction: IRListContains, state: _State, value_types: dict[str, IRType]) -> None:
        self._require_defined(instruction.list_value, state, value_types)
        self._require_defined(instruction.value, state, value_types)
        if not isinstance(instruction.list_value.type, ListType):
            self._fail(f"List contains expects list value, got {instruction.list_value.type}")
        self._require_type(instruction.value.type, instruction.list_value.type.element, "List contains value type mismatch")
        if not isinstance(instruction.result.type, BoolType):
            self._fail(f"List contains result must be bool, got {instruction.result.type}")

    def _verify_list_index_of(self, instruction: IRListIndexOf, state: _State, value_types: dict[str, IRType]) -> None:
        self._require_defined(instruction.list_value, state, value_types)
        self._require_defined(instruction.value, state, value_types)
        if not isinstance(instruction.list_value.type, ListType):
            self._fail(f"List index_of expects list value, got {instruction.list_value.type}")
        self._require_type(instruction.value.type, instruction.list_value.type.element, "List index_of value type mismatch")
        if not isinstance(instruction.result.type, IntType):
            self._fail(f"List index_of result must be int, got {instruction.result.type}")

    def _verify_list_reverse(self, instruction: IRListReverse, state: _State, value_types: dict[str, IRType]) -> None:
        self._require_defined(instruction.list_value, state, value_types)
        if not isinstance(instruction.list_value.type, ListType):
            self._fail(f"List reverse expects list value, got {instruction.list_value.type}")

    def _verify_list_clear(self, instruction: IRListClear, state: _State, value_types: dict[str, IRType]) -> None:
        self._require_defined(instruction.list_value, state, value_types)
        if not isinstance(instruction.list_value.type, ListType):
            self._fail(f"List clear expects list value, got {instruction.list_value.type}")

    def _verify_list_push(self, instruction: IRListPush, state: _State, value_types: dict[str, IRType]) -> None:
        self._require_defined(instruction.list_value, state, value_types)
        self._require_defined(instruction.value, state, value_types)
        if not isinstance(instruction.list_value.type, ListType):
            self._fail(f"List push expects list value, got {instruction.list_value.type}")
        self._require_type(
            instruction.value.type,
            instruction.list_value.type.element,
            "List push value type mismatch",
        )

    def _verify_list_insert(self, instruction: IRListInsert, state: _State, value_types: dict[str, IRType]) -> None:
        self._require_defined(instruction.list_value, state, value_types)
        self._require_defined(instruction.index, state, value_types)
        self._require_defined(instruction.value, state, value_types)
        if not isinstance(instruction.list_value.type, ListType):
            self._fail(f"List insert expects list value, got {instruction.list_value.type}")
        if not isinstance(instruction.index.type, IntType):
            self._fail(f"List insert index must be int, got {instruction.index.type}")
        self._require_type(
            instruction.value.type,
            instruction.list_value.type.element,
            "List insert value type mismatch",
        )

    def _verify_list_pop(self, instruction: IRListPop, state: _State, value_types: dict[str, IRType]) -> None:
        self._require_defined(instruction.list_value, state, value_types)
        if not isinstance(instruction.list_value.type, ListType):
            self._fail(f"List pop expects list value, got {instruction.list_value.type}")
        self._require_type(
            instruction.result.type,
            instruction.list_value.type.element,
            "List pop result type mismatch",
        )

    def _verify_list_remove_at(self, instruction: IRListRemoveAt, state: _State, value_types: dict[str, IRType]) -> None:
        self._require_defined(instruction.list_value, state, value_types)
        self._require_defined(instruction.index, state, value_types)
        if not isinstance(instruction.list_value.type, ListType):
            self._fail(f"List remove_at expects list value, got {instruction.list_value.type}")
        if not isinstance(instruction.index.type, IntType):
            self._fail(f"List remove_at index must be int, got {instruction.index.type}")
        self._require_type(
            instruction.result.type,
            instruction.list_value.type.element,
            "List remove_at result type mismatch",
        )

    def _verify_sequence_sort(self, instruction: IRSequenceSort, state: _State, value_types: dict[str, IRType]) -> None:
        self._require_defined(instruction.sequence, state, value_types)
        if not isinstance(instruction.sequence.type, (ArrayType, ListType)):
            self._fail(f"Sequence sort expects array or list value, got {instruction.sequence.type}")
        if not isinstance(instruction.sequence.type.element, (IntType, DoubleType, StringType)):
            self._fail(f"Sequence sort does not support element type {instruction.sequence.type.element}")

    def _verify_list_is_empty(
        self,
        instruction: IRListIsEmpty,
        state: _State,
        value_types: dict[str, IRType],
    ) -> None:
        self._require_defined(instruction.list_value, state, value_types)
        if not isinstance(instruction.list_value.type, ListType):
            self._fail(f"List is_empty expects list value, got {instruction.list_value.type}")
        if not isinstance(instruction.result.type, BoolType):
            self._fail(f"List is_empty result must be bool, got {instruction.result.type}")

    def _verify_vector_length(
        self,
        instruction: IRVectorLength,
        state: _State,
        value_types: dict[str, IRType],
    ) -> None:
        self._require_defined(instruction.vector, state, value_types)
        if not isinstance(instruction.vector.type, VectorType):
            self._fail(f"Vector length expects vector value, got {instruction.vector.type}")
        if not isinstance(instruction.result.type, IntType):
            self._fail(f"Vector length result must be int, got {instruction.result.type}")

    def _verify_matrix_rows(
        self,
        instruction: IRMatrixRows,
        state: _State,
        value_types: dict[str, IRType],
    ) -> None:
        self._require_defined(instruction.matrix, state, value_types)
        if not isinstance(instruction.matrix.type, MatrixType):
            self._fail(f"Matrix rows expects matrix value, got {instruction.matrix.type}")
        if instruction.rows <= 0:
            self._fail(f"Matrix rows count must be positive, got {instruction.rows}")
        if not isinstance(instruction.result.type, IntType):
            self._fail(f"Matrix rows result must be int, got {instruction.result.type}")

    def _verify_matrix_columns(
        self,
        instruction: IRMatrixColumns,
        state: _State,
        value_types: dict[str, IRType],
    ) -> None:
        self._require_defined(instruction.matrix, state, value_types)
        if not isinstance(instruction.matrix.type, MatrixType):
            self._fail(f"Matrix columns expects matrix value, got {instruction.matrix.type}")
        if instruction.columns <= 0:
            self._fail(f"Matrix columns count must be positive, got {instruction.columns}")
        if not isinstance(instruction.result.type, IntType):
            self._fail(f"Matrix columns result must be int, got {instruction.result.type}")

    def _verify_return(
        self,
        function: IRFunction,
        instruction: IRReturn,
        state: _State,
        value_types: dict[str, IRType],
    ) -> None:
        if instruction.value is None:
            if not isinstance(function.return_type, VoidType):
                self._fail(
                    f"Return type mismatch: expected {function.return_type}, got void"
                )
            return

        self._require_defined(instruction.value, state, value_types)
        if instruction.value.type != function.return_type:
            self._fail(
                f"Return type mismatch: expected {function.return_type}, "
                f"got {instruction.value.type}"
            )

    def _verify_all_non_void_paths_return(
        self,
        function: IRFunction,
        blocks: dict[str, IRBasicBlock],
    ) -> None:
        if isinstance(function.return_type, VoidType):
            return

        memo: dict[str, bool] = {}
        if not self._block_returns("entry", blocks, memo, set()):
            self._fail(f"Function '{function.name}' may exit without returning a value")

    def _block_returns(
        self,
        block_name: str,
        blocks: dict[str, IRBasicBlock],
        memo: dict[str, bool],
        visiting: set[str],
    ) -> bool:
        if block_name in memo:
            return memo[block_name]
        if block_name in visiting:
            # Lowered loops jump back to their condition block; the cycle
            # itself is not a path that exits the function without returning.
            return block_name.startswith("cond") or block_name.startswith("for.cond")

        visiting.add(block_name)
        terminator = blocks[block_name].instructions[-1]
        if isinstance(terminator, IRReturn):
            result = terminator.value is not None
        elif isinstance(terminator, IRJump):
            result = self._block_returns(terminator.target, blocks, memo, visiting)
        elif isinstance(terminator, IRBranch):
            result = self._block_returns(
                terminator.true_target,
                blocks,
                memo,
                visiting,
            ) and self._block_returns(
                terminator.false_target,
                blocks,
                memo,
                visiting,
            )
        else:
            result = False

        visiting.remove(block_name)
        memo[block_name] = result
        return result

    def _verify_const(self, instruction: IRConst) -> None:
        value = instruction.value
        result_type = instruction.result.type

        if isinstance(value, IREnumConstant):
            if not isinstance(result_type, EnumType):
                self._fail(
                    f"Enum const type mismatch: expected enum {value.enum_name}, got {result_type}"
                )
            if value.enum_name != result_type.name:
                self._fail(
                    f"Enum const identity mismatch: expected {result_type.name}, got {value.enum_name}"
                )
            if not 0 <= value.member_id < len(result_type.variants):
                self._fail(
                    f"Enum const member id {value.member_id} is invalid for {result_type.name}"
                )
            if result_type.variants[value.member_id] != value.member_name:
                self._fail(
                    f"Enum const member '{value.member_name}' does not match declaration {result_type.name}"
                )
            if value.discriminant != value.member_id:
                self._fail(
                    f"Enum const discriminant {value.discriminant} is invalid for member '{value.member_name}'"
                )
            return

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

    def _binary_result_type(self, instruction: IRBinaryOp) -> IRType:
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

    def _verify_unary(self, instruction: IRUnaryOp) -> None:
        if instruction.operator != "not":
            self._fail(f"Unsupported unary operator '{instruction.operator}'")
        if not isinstance(instruction.operand.type, BoolType):
            self._fail(
                f"Unary op 'not' requires bool operand, got {instruction.operand.type}"
            )
        self._require_type(
            instruction.result.type,
            BoolType(),
            "Unary op 'not' result type mismatch",
        )

    def _compare_result_type(self, instruction: IRCompareOp) -> IRType:
        left = instruction.left.type
        right = instruction.right.type
        operator = instruction.operator

        if isinstance(left, (VectorType, MatrixType)):
            expected_rank = 1 if isinstance(left, VectorType) else 2
            shape = instruction.aggregate_shape
            if operator not in {"eq", "ne"} or left != right:
                self._fail(
                    f"Aggregate compare requires equal operands and eq/ne, got {left}, {right}, {operator}"
                )
            if shape is None or len(shape) != expected_rank or any(size <= 0 for size in shape):
                self._fail(f"Aggregate compare requires a positive rank-{expected_rank} shape")
            if not isinstance(left.element, (IntType, DoubleType, BoolType, StringType)):
                self._fail(f"Aggregate compare does not support element type {left.element}")
            return BoolType()

        if instruction.aggregate_shape is not None:
            self._fail("Scalar compare must not carry an aggregate shape")

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
            if not isinstance(left, (IntType, DoubleType, BoolType, StringType, StructType, EnumType)):
                self._fail(
                    f"Compare op '{operator}' does not support operands of type {left}"
                )
            return BoolType()

        self._fail(f"Unsupported compare operator '{operator}'")

    def _verify_cast(self, instruction: IRCast) -> None:
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
        value: IRValue,
        state: _State,
        value_types: dict[str, IRType],
    ) -> None:
        if value.name not in state.values:
            self._fail(f"Undefined value '{self._value(value)}'")

        expected_type = value_types.get(value.name)
        if expected_type is not None and expected_type != value.type:
            self._fail(
                f"Value '{self._value(value)}' type mismatch: "
                f"expected {expected_type}, got {value.type}"
            )

    def _require_slot_exists(
        self,
        slot: IRValue,
        slot_types: dict[str, IRType],
    ) -> None:
        expected_type = slot_types.get(slot.name)
        if expected_type is None:
            self._fail(f"Undefined slot '{self._value(slot)}'")
        if expected_type != slot.type:
            self._fail(
                f"Slot '{self._value(slot)}' type mismatch: "
                f"expected {expected_type}, got {slot.type}"
            )

    def _require_slot_stored(self, slot: IRValue, state: _State) -> None:
        if slot.name not in state.slots:
            self._fail(f"Slot '{self._value(slot)}' loaded before store")

    def _require_type(self, actual: IRType, expected: IRType, message: str) -> None:
        if actual != expected:
            self._fail(f"{message}: expected {expected}, got {actual}")

    @staticmethod
    def _define_value(state: _State, value: IRValue) -> _State:
        return _State(state.values | {value.name}, state.slots)

    @staticmethod
    def _instruction_result(instruction: IRInstruction) -> IRValue | None:
        if isinstance(instruction, (IRConst, IRLoad, IRBinaryOp, IRUnaryOp, IRCompareOp, IRCast, IRFunctionRef)):
            return instruction.result
        if isinstance(instruction, IRCall):
            return instruction.result
        if isinstance(instruction, IRCallIndirect):
            return instruction.result
        if isinstance(
            instruction,
            (
                IRArrayNew,
                IRArrayGet,
                IRArraySlice,
                IRListNew,
                IRListGet,
                IRListCopy,
                IRListContains,
                IRListIndexOf,
                IRVectorGet,
                IRMatrixGet,
                IRArrayLength,
                IRListLength,
                IRListIsEmpty,
                IRVectorLength,
                IRMatrixRows,
                IRMatrixColumns,
                IRVectorNew,
                IRMatrixNew,
                IRVectorAdd,
                IRVectorDot,
                IROuterProduct,
                IRVectorScale,
                IRMatrixAdd,
                IRMatrixMatMul,
                IRMatrixVectorMul,
                IRVectorMatrixMul,
                IRMatrixScale,
                IRVectorSub,
                IRMatrixSub,
                IRStructNew,
                IRStructGet,
                IRStructSet,
                IRMethodResultNew,
                IRMethodResultReceiver,
                IRMethodResultValue,
            ),
        ):
            return instruction.result
        return None

    def _numeric_binary_result_type(self, left: IRType, right: IRType) -> IRType:
        if not isinstance(left, self._NUMERIC_TYPES) or not isinstance(right, self._NUMERIC_TYPES):
            self._fail(f"Numeric operation requires numeric operands, got {left} and {right}")
        if isinstance(left, ComplexType) or isinstance(right, ComplexType):
            return ComplexType()
        if isinstance(left, DoubleType) or isinstance(right, DoubleType):
            return DoubleType()
        if isinstance(left, FloatType) or isinstance(right, FloatType):
            return FloatType()
        return IntType()

    @staticmethod
    def _successors(block: IRBasicBlock) -> tuple[str, ...]:
        terminator = block.instructions[-1]
        if isinstance(terminator, IRJump):
            return (terminator.target,)
        if isinstance(terminator, IRBranch):
            return (terminator.true_target, terminator.false_target)
        return ()

    def _verify_type(self, type_: IRType, context: str) -> None:
        if not self._is_valid_type(type_):
            self._fail(f"Invalid IR type for {context}: {type_!r}")

    def _is_valid_type(self, type_: IRType) -> bool:
        if isinstance(type_, EnumType):
            return bool(type_.name) and bool(type_.variants) and len(set(type_.variants)) == len(type_.variants)
        if isinstance(type_, StructType):
            return bool(type_.name) and type_.name in self._structs
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
                ClassRefType,
                InterfaceType,
                FunctionType,
            ),
        ):
            return True
        if isinstance(type_, NullableType):
            return self._is_valid_type(type_.inner)
        if isinstance(type_, (ListType, ArrayType, VectorType, MatrixType)):
            return self._is_valid_type(type_.element)
        if isinstance(type_, MethodResultType):
            return self._is_valid_type(type_.receiver) and self._is_valid_type(type_.value)
        return False

    @staticmethod
    def _value(value: IRValue) -> str:
        return value.name if value.name.startswith("%") else f"%{value.name}"

    @staticmethod
    def _fail(message: str) -> NoReturn:
        raise IRVerificationError(message)
