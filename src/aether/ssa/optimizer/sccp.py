from __future__ import annotations

from dataclasses import dataclass
from math import trunc
from typing import Any

from aether.ir.types import DoubleType, IntType, StringType
from aether.ssa.analysis import Constant, LatticeState, Overdefined, Unknown, Worklist
from aether.ssa.model import (
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

        if isinstance(instruction, SSACast):
            self._set_state(instruction.result, self._evaluate_cast(instruction))
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
        if isinstance(instruction.left.type, StringType) or isinstance(
            instruction.right.type,
            StringType,
        ):
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
        if isinstance(instruction.left.type, StringType) or isinstance(
            instruction.right.type,
            StringType,
        ):
            return Overdefined()

        try:
            return Constant(self._evaluate_compare_values(operator, left.value, right.value))
        except (ArithmeticError, TypeError, ValueError):
            return Overdefined()

    def _evaluate_cast(self, instruction: SSACast) -> LatticeState:
        value = self._state(instruction.value)

        if isinstance(value, Overdefined):
            return Overdefined()
        if isinstance(value, Unknown):
            return Unknown()
        if not isinstance(value, Constant):
            return Overdefined()

        try:
            if isinstance(instruction.result.type, DoubleType):
                return Constant(float(value.value))
            if isinstance(instruction.result.type, IntType):
                return Constant(trunc(value.value))
        except (ArithmeticError, TypeError, ValueError):
            return Overdefined()
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
        if isinstance(instruction, (SSAConst, SSABinaryOp, SSACompareOp, SSACast, SSAPhi)):
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
        if isinstance(instruction, SSACast):
            return (instruction.value,)
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
    """Rewrite SSA using known constant facts from SCCP."""

    def __init__(self, module: SSAModule, result: SCCPResult) -> None:
        self.module = module
        self.result = result

    def run(self) -> SSAOptimizationResult:
        updated_functions: list[SSAFunction] = []
        replaced_constants = 0
        simplified_branches = 0
        removed_blocks = 0
        removed_phi_incomings = 0

        for function in self.module.functions:
            (
                updated_function,
                function_replaced,
                function_simplified,
                function_removed_blocks,
                function_removed_phi_incomings,
            ) = self._transform_function(function)
            updated_functions.append(updated_function)
            replaced_constants += function_replaced
            simplified_branches += function_simplified
            removed_blocks += function_removed_blocks
            removed_phi_incomings += function_removed_phi_incomings

        stats = {
            "replaced_constants": replaced_constants,
            "simplified_branches": simplified_branches,
            "removed_blocks": removed_blocks,
            "removed_phi_incomings": removed_phi_incomings,
        }

        if (
            replaced_constants == 0
            and simplified_branches == 0
            and removed_blocks == 0
            and removed_phi_incomings == 0
        ):
            return SSAOptimizationResult(
                self.module,
                changed=False,
                stats=stats,
            )

        return SSAOptimizationResult(
            SSAModule(updated_functions),
            changed=True,
            stats=stats,
        )

    def _transform_function(
        self,
        function: SSAFunction,
    ) -> tuple[SSAFunction, int, int, int, int]:
        updated_blocks: list[SSABasicBlock] = []
        replaced_constants = 0
        simplified_branches = 0
        removed_phi_incomings = 0
        executable_blocks = set(self.result.executable_blocks)
        executable_blocks.add(function.entry_block)
        removed_block_names = {
            block.name for block in function.blocks if block.name not in executable_blocks
        }

        for block in function.blocks:
            if block.name in removed_block_names:
                continue
            updated_block, block_replaced, block_simplified = self._transform_block(block)
            updated_block, block_removed_phi_incomings = self._cleanup_phi_incomings(
                function,
                updated_block,
                removed_block_names,
            )
            self._verify_live_targets(function, updated_block, removed_block_names)
            updated_blocks.append(updated_block)
            replaced_constants += block_replaced
            simplified_branches += block_simplified
            removed_phi_incomings += block_removed_phi_incomings

        removed_blocks = len(removed_block_names)

        if (
            replaced_constants == 0
            and simplified_branches == 0
            and removed_blocks == 0
            and removed_phi_incomings == 0
        ):
            return function, 0, 0, 0, 0

        return (
            SSAFunction(
                function.name,
                list(function.parameters),
                function.return_type,
                updated_blocks,
                function.entry_block,
            ),
            replaced_constants,
            simplified_branches,
            removed_blocks,
            removed_phi_incomings,
        )

    def _transform_block(self, block: SSABasicBlock) -> tuple[SSABasicBlock, int, int]:
        remaining_phis: list[SSAInstruction] = []
        replaced_phis: list[SSAInstruction] = []
        instructions: list[SSAInstruction] = []
        replaced_constants = 0
        simplified_branches = 0
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
            branch_replacement = self._branch_replacement(instruction)
            if branch_replacement is not None:
                instructions.append(branch_replacement)
                simplified_branches += 1
                continue

            replacement = self._constant_replacement(instruction)
            if replacement is None:
                instructions.append(instruction)
                continue

            instructions.append(replacement)
            replaced_constants += 1

        if replaced_constants == 0 and simplified_branches == 0:
            return block, 0, 0

        return SSABasicBlock(block.name, instructions), replaced_constants, simplified_branches

    def _constant_replacement(self, instruction: SSAInstruction) -> SSAConst | None:
        if not isinstance(instruction, (SSABinaryOp, SSACompareOp, SSACast, SSAPhi)):
            return None

        state = self.result.state(instruction.result)
        if not isinstance(state, Constant):
            return None

        return SSAConst(instruction.result, state.value)

    def _branch_replacement(self, instruction: SSAInstruction) -> SSAJump | None:
        if not isinstance(instruction, SSABranch):
            return None

        state = self.result.state(instruction.condition)
        if not isinstance(state, Constant) or not isinstance(state.value, bool):
            return None

        if state.value:
            return SSAJump(instruction.true_target)
        return SSAJump(instruction.false_target)

    def _cleanup_phi_incomings(
        self,
        function: SSAFunction,
        block: SSABasicBlock,
        removed_block_names: set[str],
    ) -> tuple[SSABasicBlock, int]:
        if not removed_block_names:
            return block, 0

        instructions: list[SSAInstruction] = []
        removed_phi_incomings = 0
        changed = False

        for instruction in block.instructions:
            if not isinstance(instruction, SSAPhi):
                instructions.append(instruction)
                continue

            incoming = tuple(
                (incoming_block, incoming_value)
                for incoming_block, incoming_value in instruction.incoming
                if incoming_block not in removed_block_names
            )
            removed_count = len(instruction.incoming) - len(incoming)
            removed_phi_incomings += removed_count

            if removed_count == 0:
                instructions.append(instruction)
                continue

            changed = True
            if not incoming:
                raise ValueError(
                    "SCCP cleanup removed all incoming values from phi "
                    f"'{instruction.result.name}' in block '{block.name}' "
                    f"of function '{function.name}'"
                )
            instructions.append(SSAPhi(instruction.result, incoming))

        if not changed:
            return block, removed_phi_incomings
        return SSABasicBlock(block.name, instructions), removed_phi_incomings

    def _verify_live_targets(
        self,
        function: SSAFunction,
        block: SSABasicBlock,
        removed_block_names: set[str],
    ) -> None:
        if not removed_block_names or not block.instructions:
            return

        terminator = block.instructions[-1]
        if isinstance(terminator, SSAJump):
            targets = (terminator.target,)
        elif isinstance(terminator, SSABranch):
            targets = (terminator.true_target, terminator.false_target)
        else:
            return

        removed_targets = sorted(target for target in targets if target in removed_block_names)
        if removed_targets:
            raise ValueError(
                "SCCP cleanup would leave terminator in block "
                f"'{block.name}' of function '{function.name}' targeting removed "
                f"block(s): {', '.join(removed_targets)}"
            )
