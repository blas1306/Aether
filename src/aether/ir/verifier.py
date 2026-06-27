from __future__ import annotations

from dataclasses import dataclass
from typing import NoReturn

from .model import (
    IRBasicBlock,
    IRBinaryOp,
    IRBranch,
    IRCall,
    IRCompareOp,
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
from .types import (
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

    def verify(self) -> IRModule:
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

        for block_name, block in blocks.items():
            if block_name not in inputs:
                self._transfer_block(
                    function,
                    block,
                    entry,
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

        if isinstance(instruction, IRCall):
            self._verify_call(instruction, state, value_types)
            if instruction.result is None:
                return state
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
            # Lowered while-loops jump back to condN; the cycle itself is not a
            # path that exits the function without returning.
            return block_name.startswith("cond")

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

    def _compare_result_type(self, instruction: IRCompareOp) -> IRType:
        left = instruction.left.type
        right = instruction.right.type
        operator = instruction.operator

        if operator in {"lt", "le", "gt", "ge"}:
            if not isinstance(left, IntType) or not isinstance(right, IntType):
                self._fail(
                    f"Compare op '{operator}' requires int operands, got {left} and {right}"
                )
            return BoolType()

        if operator in {"eq", "ne"}:
            if left != right:
                self._fail(
                    f"Compare op '{operator}' requires compatible operands, "
                    f"got {left} and {right}"
                )
            if not isinstance(left, (IntType, BoolType, StringType)):
                self._fail(
                    f"Compare op '{operator}' does not support operands of type {left}"
                )
            return BoolType()

        self._fail(f"Unsupported compare operator '{operator}'")

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
        if isinstance(instruction, (IRConst, IRLoad, IRBinaryOp, IRCompareOp)):
            return instruction.result
        if isinstance(instruction, IRCall):
            return instruction.result
        return None

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
    def _value(value: IRValue) -> str:
        return value.name if value.name.startswith("%") else f"%{value.name}"

    @staticmethod
    def _fail(message: str) -> NoReturn:
        raise IRVerificationError(message)
