from __future__ import annotations

from dataclasses import dataclass
from math import trunc
from typing import Any

from aether.ssa.analysis import Constant, LatticeState, Overdefined, Unknown, Worklist
from aether.ssa.model import (
    SSABasicBlock,
    SSABinaryOp,
    SSABranch,
    SSACall,
    SSACompareOp,
    SSAConst,
    SSAFunction,
    SSAInstruction,
    SSAJump,
    SSAModule,
    SSAPhi,
    SSAReturn,
    SSAValue,
)

from .result import SSAOptimizationResult


InstructionRef = tuple[str, int]
Edge = tuple[str, str]


@dataclass(frozen=True)
class SCCPResult:
    """Fixed-point SCCP facts for one SSA function."""

    _states: dict[SSAValue, LatticeState]
    executable_blocks: set[str]
    executable_edges: set[Edge]

    def state(self, value: SSAValue) -> LatticeState:
        return self._states.get(value, Unknown())


class SCCPAnalyzer:
    """Analysis-only Sparse Conditional Constant Propagation for SSA."""

    _BINARY_OPERATORS = {"add", "sub", "mul", "div", "mod", "rem"}
    _COMPARE_OPERATORS = {"lt", "le", "gt", "ge", "eq", "ne"}

    def __init__(self, function_or_module: SSAFunction | SSAModule) -> None:
        self.function: SSAFunction | None = None
        if isinstance(function_or_module, SSAFunction):
            self.function = function_or_module

        self._blocks: dict[str, SSABasicBlock] = {}
        self._states: dict[SSAValue, LatticeState] = {}
        self._users: dict[SSAValue, set[InstructionRef]] = {}
        self._instruction_worklist: Worklist[InstructionRef] = Worklist()
        self._block_worklist: Worklist[str] = Worklist()
        self._executable_blocks: set[str] = set()
        self._executable_edges: set[Edge] = set()

    def analyze(self) -> SCCPResult:
        if self.function is None:
            raise ValueError("SCCPAnalyzer.analyze() requires an SSAFunction")
        return self.analyze_function(self.function)

    def analyze_function(self, function: SSAFunction) -> SCCPResult:
        self.function = function
        self._blocks = {block.name: block for block in function.blocks}
        self._states = {}
        self._users = {}
        self._instruction_worklist = Worklist()
        self._block_worklist = Worklist()
        self._executable_blocks = set()
        self._executable_edges = set()

        self._initialize_states(function)
        self._collect_users(function)
        self._mark_block_executable(function.entry_block)

        while not self._block_worklist.empty() or not self._instruction_worklist.empty():
            while not self._block_worklist.empty():
                self._schedule_block(self._block_worklist.pop())

            if not self._instruction_worklist.empty():
                block_name, instruction_index = self._instruction_worklist.pop()
                if block_name not in self._executable_blocks:
                    continue
                self._evaluate_instruction(block_name, instruction_index)

        return SCCPResult(
            dict(self._states),
            set(self._executable_blocks),
            set(self._executable_edges),
        )

    def _initialize_states(self, function: SSAFunction) -> None:
        for parameter in function.parameters:
            self._states[parameter] = Overdefined()

        for block in function.blocks:
            for instruction in block.instructions:
                result = self._instruction_result(instruction)
                if result is None:
                    continue
                if isinstance(instruction, SSAConst):
                    self._states[result] = Constant(instruction.value)
                else:
                    self._states.setdefault(result, Unknown())

    def _collect_users(self, function: SSAFunction) -> None:
        for block in function.blocks:
            for index, instruction in enumerate(block.instructions):
                ref = (block.name, index)
                for operand in self._instruction_operands(instruction):
                    self._users.setdefault(operand, set()).add(ref)

    def _mark_block_executable(self, block_name: str) -> None:
        if block_name in self._executable_blocks:
            return
        self._executable_blocks.add(block_name)
        self._block_worklist.push(block_name)

    def _mark_edge_executable(self, from_block: str, to_block: str) -> None:
        edge = (from_block, to_block)
        if edge in self._executable_edges:
            return

        self._executable_edges.add(edge)
        already_executable = to_block in self._executable_blocks
        self._mark_block_executable(to_block)
        if already_executable:
            self._schedule_phis(to_block)

    def _schedule_block(self, block_name: str) -> None:
        block = self._blocks.get(block_name)
        if block is None:
            return
        for index, _instruction in enumerate(block.instructions):
            self._instruction_worklist.push((block_name, index))

    def _schedule_phis(self, block_name: str) -> None:
        block = self._blocks.get(block_name)
        if block is None:
            return
        for index, instruction in enumerate(block.instructions):
            if not isinstance(instruction, SSAPhi):
                break
            self._instruction_worklist.push((block_name, index))

    def _schedule_users(self, value: SSAValue) -> None:
        for ref in self._users.get(value, set()):
            self._instruction_worklist.push(ref)

    def _evaluate_instruction(self, block_name: str, instruction_index: int) -> None:
        block = self._blocks[block_name]
        instruction = block.instructions[instruction_index]

        if isinstance(instruction, SSAConst):
            self._set_state(instruction.result, Constant(instruction.value))
            return

        if isinstance(instruction, SSABinaryOp):
            self._set_state(instruction.result, self._evaluate_binary(instruction))
            return

        if isinstance(instruction, SSACompareOp):
            self._set_state(instruction.result, self._evaluate_compare(instruction))
            return

        if isinstance(instruction, SSAPhi):
            self._set_state(instruction.result, self._evaluate_phi(block_name, instruction))
            return

        if isinstance(instruction, SSACall):
            if instruction.result is not None:
                self._set_state(instruction.result, Overdefined())
            return

        if isinstance(instruction, SSABranch):
            self._evaluate_branch(block_name, instruction)
            return

        if isinstance(instruction, SSAJump):
            self._mark_edge_executable(block_name, instruction.target)
            return

        if isinstance(instruction, SSAReturn):
            return

    def _set_state(self, value: SSAValue, state: LatticeState) -> None:
        current = self._states.get(value, Unknown())
        updated = current.merge(state)
        if updated == current:
            return
        self._states[value] = updated
        self._schedule_users(value)

    def _evaluate_binary(self, instruction: SSABinaryOp) -> LatticeState:
        left = self._state(instruction.left)
        right = self._state(instruction.right)

        if isinstance(left, Overdefined) or isinstance(right, Overdefined):
            return Overdefined()
        if isinstance(left, Unknown) or isinstance(right, Unknown):
            return Unknown()
        if not isinstance(left, Constant) or not isinstance(right, Constant):
            return Overdefined()

        operator = instruction.operator
        if operator not in self._BINARY_OPERATORS:
            return Overdefined()
        if operator in {"div", "mod", "rem"} and right.value == 0:
            return Overdefined()

        try:
            return Constant(self._evaluate_binary_values(operator, left.value, right.value))
        except (ArithmeticError, TypeError, ValueError):
            return Overdefined()

    def _evaluate_compare(self, instruction: SSACompareOp) -> LatticeState:
        left = self._state(instruction.left)
        right = self._state(instruction.right)

        if isinstance(left, Overdefined) or isinstance(right, Overdefined):
            return Overdefined()
        if isinstance(left, Unknown) or isinstance(right, Unknown):
            return Unknown()
        if not isinstance(left, Constant) or not isinstance(right, Constant):
            return Overdefined()

        operator = instruction.operator
        if operator not in self._COMPARE_OPERATORS:
            return Overdefined()

        try:
            return Constant(self._evaluate_compare_values(operator, left.value, right.value))
        except (ArithmeticError, TypeError, ValueError):
            return Overdefined()

    def _evaluate_phi(self, block_name: str, instruction: SSAPhi) -> LatticeState:
        state: LatticeState = Unknown()
        seen_executable_incoming = False

        for incoming_block, incoming_value in instruction.incoming:
            if (incoming_block, block_name) not in self._executable_edges:
                continue
            seen_executable_incoming = True
            state = state.merge(self._state(incoming_value))

        if not seen_executable_incoming:
            return Unknown()
        return state

    def _evaluate_branch(self, block_name: str, instruction: SSABranch) -> None:
        condition = self._state(instruction.condition)
        if isinstance(condition, Constant):
            if bool(condition.value):
                self._mark_edge_executable(block_name, instruction.true_target)
            else:
                self._mark_edge_executable(block_name, instruction.false_target)
            return

        if isinstance(condition, Overdefined):
            self._mark_edge_executable(block_name, instruction.true_target)
            self._mark_edge_executable(block_name, instruction.false_target)

    def _state(self, value: SSAValue) -> LatticeState:
        return self._states.get(value, Unknown())

    @staticmethod
    def _instruction_result(instruction: SSAInstruction) -> SSAValue | None:
        if isinstance(instruction, (SSAConst, SSABinaryOp, SSACompareOp, SSAPhi)):
            return instruction.result
        if isinstance(instruction, SSACall):
            return instruction.result
        return None

    @staticmethod
    def _instruction_operands(instruction: SSAInstruction) -> tuple[SSAValue, ...]:
        if isinstance(instruction, SSABinaryOp):
            return (instruction.left, instruction.right)
        if isinstance(instruction, SSACompareOp):
            return (instruction.left, instruction.right)
        if isinstance(instruction, SSAPhi):
            return tuple(value for _block_name, value in instruction.incoming)
        if isinstance(instruction, SSABranch):
            return (instruction.condition,)
        if isinstance(instruction, SSACall):
            return instruction.arguments
        if isinstance(instruction, SSAReturn) and instruction.value is not None:
            return (instruction.value,)
        return ()

    @staticmethod
    def _evaluate_binary_values(operator: str, left: Any, right: Any) -> Any:
        if operator == "add":
            return left + right
        if operator == "sub":
            return left - right
        if operator == "mul":
            return left * right
        if operator == "div":
            return left / right
        if operator in {"mod", "rem"}:
            return left - trunc(left / right) * right
        raise AssertionError(f"Unsupported foldable SSA binary operator: {operator}")

    @staticmethod
    def _evaluate_compare_values(operator: str, left: Any, right: Any) -> bool:
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
        raise AssertionError(f"Unsupported foldable SSA compare operator: {operator}")


class SCCPTransformer:
    """Rewrite SSA producers whose SCCP lattice state is a known constant."""

    def __init__(self, module: SSAModule, result: SCCPResult) -> None:
        self.module = module
        self.result = result

    def run(self) -> SSAOptimizationResult:
        updated_functions: list[SSAFunction] = []
        replaced_constants = 0

        for function in self.module.functions:
            updated_function, function_replaced = self._transform_function(function)
            updated_functions.append(updated_function)
            replaced_constants += function_replaced

        if replaced_constants == 0:
            return SSAOptimizationResult(
                self.module,
                changed=False,
                stats={"replaced_constants": 0},
            )

        return SSAOptimizationResult(
            SSAModule(updated_functions),
            changed=True,
            stats={"replaced_constants": replaced_constants},
        )

    def _transform_function(self, function: SSAFunction) -> tuple[SSAFunction, int]:
        updated_blocks: list[SSABasicBlock] = []
        replaced_constants = 0

        for block in function.blocks:
            updated_block, block_replaced = self._transform_block(block)
            updated_blocks.append(updated_block)
            replaced_constants += block_replaced

        if replaced_constants == 0:
            return function, 0

        return (
            SSAFunction(
                function.name,
                list(function.parameters),
                function.return_type,
                updated_blocks,
                function.entry_block,
            ),
            replaced_constants,
        )

    def _transform_block(self, block: SSABasicBlock) -> tuple[SSABasicBlock, int]:
        remaining_phis: list[SSAInstruction] = []
        replaced_phis: list[SSAInstruction] = []
        instructions: list[SSAInstruction] = []
        replaced_constants = 0
        index = 0

        while index < len(block.instructions) and isinstance(block.instructions[index], SSAPhi):
            instruction = block.instructions[index]
            replacement = self._constant_replacement(instruction)
            if replacement is None:
                remaining_phis.append(instruction)
            else:
                replaced_phis.append(replacement)
                replaced_constants += 1
            index += 1

        instructions.extend(remaining_phis)
        instructions.extend(replaced_phis)

        for instruction in block.instructions[index:]:
            replacement = self._constant_replacement(instruction)
            if replacement is None:
                instructions.append(instruction)
                continue

            instructions.append(replacement)
            replaced_constants += 1

        if replaced_constants == 0:
            return block, 0

        return SSABasicBlock(block.name, instructions), replaced_constants

    def _constant_replacement(self, instruction: SSAInstruction) -> SSAConst | None:
        if not isinstance(instruction, (SSABinaryOp, SSACompareOp, SSAPhi)):
            return None

        state = self.result.state(instruction.result)
        if not isinstance(state, Constant):
            return None

        return SSAConst(instruction.result, state.value)
