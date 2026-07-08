from __future__ import annotations

from dataclasses import dataclass, field
from typing import NoReturn

from aether.ir.model import (
    IRArrayGet,
    IRArrayLength,
    IRArrayNew,
    IRArraySet,
    IRBasicBlock,
    IRBinaryOp,
    IRBranch,
    IRCast,
    IRCall,
    IRCompareOp,
    IRConst,
    IRFunction,
    IRInstruction,
    IRJump,
    IRLoad,
    IRMatrixNew,
    IRModule,
    IRReturn,
    IRStore,
    IRValue,
    IRVectorNew,
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
    SSAMatrixNew,
    SSAModule,
    SSAParameter,
    SSAPhi,
    SSAReturn,
    SSAValue,
    SSAVectorNew,
)


class SSABuildError(ValueError):
    """Raised when slot IR cannot be converted by the pattern SSA builder."""


@dataclass
class _BuildState:
    """Mutable conversion state for the currently emitted SSA path.

    ``value_map`` maps IR value names to the SSA definitions already visible on
    this path. ``slot_values`` is the current promoted value for each mutable IR
    slot. ``incomplete_slots`` marks slots that exist on at least one incoming
    path but not all of them; a later load must fail clearly instead of choosing
    an arbitrary value.
    """

    value_map: dict[str, SSAValue]
    slot_values: dict[str, SSAValue]
    incomplete_slots: set[str] = field(default_factory=set)

    def copy(self) -> "_BuildState":
        return _BuildState(
            dict(self.value_map),
            dict(self.slot_values),
            set(self.incomplete_slots),
        )


@dataclass(frozen=True)
class _SimpleIfElse:
    entry: IRBasicBlock
    then_block: IRBasicBlock
    else_block: IRBasicBlock
    merge_block: IRBasicBlock | None


@dataclass(frozen=True)
class _SimpleWhile:
    entry: IRBasicBlock
    condition_block: IRBasicBlock
    body_block: IRBasicBlock
    exit_block: IRBasicBlock


@dataclass(frozen=True)
class _SlotMerge:
    instructions: list[SSAInstruction]
    slot_values: dict[str, SSAValue]
    incomplete_slots: set[str]


@dataclass(frozen=True)
class _LoopPhiPlan:
    slot_names: list[str]
    values: dict[str, SSAValue]


class SSABuilder:
    """Convert supported slot IR patterns into value-based SSA.

    This builder is intentionally pattern-based until Aether grows the general
    CFG/dominator/dominance-frontier pipeline. Keep the accepted shapes strict:
    broadening them here risks silently producing incorrect SSA without the
    full Cytron-style placement and renaming algorithm.
    """

    _SUPPORTED_CFG_MESSAGE = (
        "SSA builder phase 3 only supports linear functions, simple acyclic "
        "if/else, and simple while loops."
    )

    def build(self, module: IRModule) -> SSAModule:
        return SSAModule([self._build_function(function) for function in module.functions])

    def _build_function(self, function: IRFunction) -> SSAFunction:
        parameters = self._parameters(function)

        if self._is_linear_function(function):
            return self._build_linear_function(function, parameters)

        simple_if_else = self._match_simple_if_else(function)
        if simple_if_else is not None:
            return SSAFunction(
                function.name,
                parameters,
                function.return_type,
                self._build_simple_if_else_blocks(simple_if_else, parameters),
            )

        simple_while = self._match_simple_while(function)
        if simple_while is not None:
            return SSAFunction(
                function.name,
                parameters,
                function.return_type,
                self._build_simple_while_blocks(simple_while, parameters),
            )

        self._fail(self._SUPPORTED_CFG_MESSAGE)

    @staticmethod
    def _parameters(function: IRFunction) -> list[SSAParameter]:
        return [
            SSAParameter(parameter.name, parameter.type)
            for parameter in function.parameters
        ]

    @staticmethod
    def _initial_state(parameters: list[SSAParameter]) -> _BuildState:
        return _BuildState({parameter.name: parameter for parameter in parameters}, {})

    def _build_linear_function(
        self,
        function: IRFunction,
        parameters: list[SSAParameter],
    ) -> SSAFunction:
        block = function.blocks[0]
        return SSAFunction(
            function.name,
            parameters,
            function.return_type,
            [self._build_ssa_block(block, self._initial_state(parameters))],
        )

    def _build_ssa_block(
        self,
        block: IRBasicBlock,
        state: _BuildState,
        prefix: list[SSAInstruction] | None = None,
    ) -> SSABasicBlock:
        instructions = list(prefix or ())
        instructions.extend(self._build_block_instructions(block, state))
        return SSABasicBlock(block.name, instructions)

    def _is_linear_function(self, function: IRFunction) -> bool:
        if len(function.blocks) != 1 or function.blocks[0].name != "entry":
            return False

        block = function.blocks[0]
        return not any(
            isinstance(instruction, (IRBranch, IRJump))
            for instruction in block.instructions
        )

    def _match_simple_if_else(self, function: IRFunction) -> _SimpleIfElse | None:
        if len(function.blocks) not in {3, 4}:
            return None
        if not function.blocks or function.blocks[0].name != "entry":
            return None

        blocks = {block.name: block for block in function.blocks}
        if len(blocks) != len(function.blocks):
            return None

        entry = function.blocks[0]
        branch = self._terminator(entry)
        if not isinstance(branch, IRBranch):
            return None
        if self._has_control_flow_before_terminator(entry):
            return None

        then_block = blocks.get(branch.true_target)
        else_block = blocks.get(branch.false_target)
        if then_block is None or else_block is None:
            return None
        if then_block is entry or else_block is entry or then_block is else_block:
            return None

        then_terminator = self._terminator(then_block)
        else_terminator = self._terminator(else_block)
        if self._has_control_flow_before_terminator(then_block):
            return None
        if self._has_control_flow_before_terminator(else_block):
            return None

        if isinstance(then_terminator, IRReturn) and isinstance(
            else_terminator,
            IRReturn,
        ):
            if len(function.blocks) != 3:
                return None
            if set(blocks) != {"entry", then_block.name, else_block.name}:
                return None
            return _SimpleIfElse(entry, then_block, else_block, None)

        if not isinstance(then_terminator, IRJump) or not isinstance(
            else_terminator,
            IRJump,
        ):
            return None
        if then_terminator.target != else_terminator.target:
            return None
        if then_terminator.target in {entry.name, then_block.name, else_block.name}:
            return None

        merge_block = blocks.get(then_terminator.target)
        if merge_block is None:
            return None
        if len(function.blocks) != 4:
            return None
        if set(blocks) != {
            entry.name,
            then_block.name,
            else_block.name,
            merge_block.name,
        }:
            return None
        if not isinstance(self._terminator(merge_block), IRReturn):
            return None
        if self._has_control_flow_before_terminator(merge_block):
            return None

        return _SimpleIfElse(entry, then_block, else_block, merge_block)

    def _match_simple_while(self, function: IRFunction) -> _SimpleWhile | None:
        if len(function.blocks) != 4:
            return None
        if not function.blocks or function.blocks[0].name != "entry":
            return None

        blocks = {block.name: block for block in function.blocks}
        if len(blocks) != len(function.blocks):
            return None

        entry = function.blocks[0]
        entry_terminator = self._terminator(entry)
        if not isinstance(entry_terminator, IRJump):
            return None
        if self._has_control_flow_before_terminator(entry):
            return None

        condition_block = blocks.get(entry_terminator.target)
        if condition_block is None or condition_block is entry:
            return None

        condition_terminator = self._terminator(condition_block)
        if not isinstance(condition_terminator, IRBranch):
            return None
        if self._has_control_flow_before_terminator(condition_block):
            return None

        body_block = blocks.get(condition_terminator.true_target)
        exit_block = blocks.get(condition_terminator.false_target)
        if body_block is None or exit_block is None:
            return None
        if len({entry.name, condition_block.name, body_block.name, exit_block.name}) != 4:
            return None

        body_terminator = self._terminator(body_block)
        if not isinstance(body_terminator, IRJump):
            return None
        if body_terminator.target != condition_block.name:
            return None
        if self._has_control_flow_before_terminator(body_block):
            return None

        if not isinstance(self._terminator(exit_block), IRReturn):
            return None
        if self._has_control_flow_before_terminator(exit_block):
            return None

        if set(blocks) != {
            entry.name,
            condition_block.name,
            body_block.name,
            exit_block.name,
        }:
            return None

        return _SimpleWhile(entry, condition_block, body_block, exit_block)

    def _build_simple_if_else_blocks(
        self,
        simple_if_else: _SimpleIfElse,
        parameters: list[SSAParameter],
    ) -> list[SSABasicBlock]:
        entry_state = self._initial_state(parameters)
        entry_block = self._build_ssa_block(simple_if_else.entry, entry_state)

        then_state = entry_state.copy()
        then_block = self._build_ssa_block(
            simple_if_else.then_block,
            then_state,
        )

        else_state = entry_state.copy()
        else_block = self._build_ssa_block(
            simple_if_else.else_block,
            else_state,
        )

        blocks = [entry_block, then_block, else_block]

        if simple_if_else.merge_block is None:
            return blocks

        merge_state = _BuildState(dict(entry_state.value_map), {})
        slot_merge = self._merge_slot_states(
            simple_if_else.merge_block,
            simple_if_else.then_block.name,
            then_state.slot_values,
            simple_if_else.else_block.name,
            else_state.slot_values,
            entry_state.slot_values,
        )
        merge_state.slot_values = slot_merge.slot_values
        merge_state.incomplete_slots = slot_merge.incomplete_slots
        blocks.append(
            self._build_ssa_block(
                simple_if_else.merge_block,
                merge_state,
                slot_merge.instructions,
            )
        )

        return blocks

    def _build_simple_while_blocks(
        self,
        simple_while: _SimpleWhile,
        parameters: list[SSAParameter],
    ) -> list[SSABasicBlock]:
        entry_state = self._initial_state(parameters)
        entry_block = self._build_ssa_block(simple_while.entry, entry_state)

        phi_plan = self._plan_loop_phis(simple_while, entry_state)

        condition_state = _BuildState(
            dict(entry_state.value_map),
            dict(entry_state.slot_values),
            set(entry_state.incomplete_slots),
        )
        for slot_name, phi_value in phi_plan.values.items():
            condition_state.slot_values[slot_name] = phi_value
            condition_state.value_map[phi_value.name] = phi_value

        condition_instructions = self._build_block_instructions(
            simple_while.condition_block,
            condition_state,
        )

        body_state = condition_state.copy()
        body_instructions = self._build_block_instructions(
            simple_while.body_block,
            body_state,
        )
        phi_instructions = self._build_loop_phi_instructions(
            simple_while,
            entry_state,
            body_state,
            phi_plan,
        )

        exit_state = _BuildState(
            dict(entry_state.value_map),
            dict(condition_state.slot_values),
            set(condition_state.incomplete_slots),
        )
        exit_instructions = self._build_block_instructions(
            simple_while.exit_block,
            exit_state,
        )

        return [
            entry_block,
            SSABasicBlock(
                simple_while.condition_block.name,
                phi_instructions + condition_instructions,
            ),
            SSABasicBlock(simple_while.body_block.name, body_instructions),
            SSABasicBlock(simple_while.exit_block.name, exit_instructions),
        ]

    def _build_block_instructions(
        self,
        block: IRBasicBlock,
        state: _BuildState,
    ) -> list[SSAInstruction]:
        instructions: list[SSAInstruction] = []

        for instruction in block.instructions:
            ssa_instruction = self._convert_instruction(instruction, state)
            if ssa_instruction is not None:
                instructions.append(ssa_instruction)

        return instructions

    def _convert_instruction(
        self,
        instruction: IRInstruction,
        state: _BuildState,
    ) -> SSAInstruction | None:
        pure_instruction = self._convert_pure_instruction(instruction, state)
        if pure_instruction is not None:
            return pure_instruction

        if self._apply_slot_instruction(instruction, state):
            return None

        terminator = self._convert_terminator(instruction, state)
        if terminator is not None:
            return terminator

        self._fail(f"Unsupported IR instruction '{type(instruction).__name__}'.")

    def _convert_pure_instruction(
        self,
        instruction: IRInstruction,
        state: _BuildState,
    ) -> SSAInstruction | None:
        if isinstance(instruction, IRConst):
            result = self._define_value(instruction.result, state.value_map)
            return SSAConst(result, instruction.value)

        if isinstance(instruction, IRBinaryOp):
            result = self._define_value(instruction.result, state.value_map)
            left = self._resolve_value(instruction.left, state.value_map)
            right = self._resolve_value(instruction.right, state.value_map)
            return SSABinaryOp(result, instruction.operator, left, right)

        if isinstance(instruction, IRCompareOp):
            result = self._define_value(instruction.result, state.value_map)
            left = self._resolve_value(instruction.left, state.value_map)
            right = self._resolve_value(instruction.right, state.value_map)
            return SSACompareOp(result, instruction.operator, left, right)

        if isinstance(instruction, IRCast):
            result = self._define_value(instruction.result, state.value_map)
            value = self._resolve_value(instruction.value, state.value_map)
            return SSACast(result, value)

        if isinstance(instruction, IRCall):
            arguments = tuple(
                self._resolve_value(argument, state.value_map)
                for argument in instruction.arguments
            )
            result = None
            if instruction.result is not None:
                result = self._define_value(instruction.result, state.value_map)
            return SSACall(instruction.function, arguments, result)

        if isinstance(instruction, IRArrayNew):
            result = self._define_value(instruction.result, state.value_map)
            elements = tuple(
                self._resolve_value(element, state.value_map)
                for element in instruction.elements
            )
            return SSAArrayNew(result, elements)

        if isinstance(instruction, IRVectorNew):
            result = self._define_value(instruction.result, state.value_map)
            elements = tuple(
                self._resolve_value(element, state.value_map)
                for element in instruction.elements
            )
            return SSAVectorNew(result, elements, instruction.orientation)

        if isinstance(instruction, IRMatrixNew):
            result = self._define_value(instruction.result, state.value_map)
            elements = tuple(
                self._resolve_value(element, state.value_map)
                for element in instruction.elements
            )
            return SSAMatrixNew(result, elements, instruction.rows, instruction.cols)

        if isinstance(instruction, IRArrayGet):
            result = self._define_value(instruction.result, state.value_map)
            array = self._resolve_value(instruction.array, state.value_map)
            index = self._resolve_value(instruction.index, state.value_map)
            return SSAArrayGet(result, array, index)

        if isinstance(instruction, IRArraySet):
            array = self._resolve_value(instruction.array, state.value_map)
            index = self._resolve_value(instruction.index, state.value_map)
            value = self._resolve_value(instruction.value, state.value_map)
            return SSAArraySet(array, index, value)

        if isinstance(instruction, IRArrayLength):
            result = self._define_value(instruction.result, state.value_map)
            array = self._resolve_value(instruction.array, state.value_map)
            return SSAArrayLength(result, array)

        return None

    def _apply_slot_instruction(
        self,
        instruction: IRInstruction,
        state: _BuildState,
    ) -> bool:
        if isinstance(instruction, IRStore):
            state.slot_values[instruction.slot.name] = self._resolve_value(
                instruction.value,
                state.value_map,
            )
            state.incomplete_slots.discard(instruction.slot.name)
            return True

        if isinstance(instruction, IRLoad):
            value = state.slot_values.get(instruction.slot.name)
            if value is None:
                if instruction.slot.name in state.incomplete_slots:
                    self._fail(
                        f"Load from slot '{self._value(instruction.slot)}' "
                        "is not defined on all paths."
                    )
                self._fail(
                    f"Load from uninitialized slot '{self._value(instruction.slot)}'."
                )
            state.value_map[instruction.result.name] = value
            return True

        return False

    def _convert_terminator(
        self,
        instruction: IRInstruction,
        state: _BuildState,
    ) -> SSAInstruction | None:
        if isinstance(instruction, IRReturn):
            value = None
            if instruction.value is not None:
                value = self._resolve_value(instruction.value, state.value_map)
            return SSAReturn(value)

        if isinstance(instruction, IRBranch):
            condition = self._resolve_value(instruction.condition, state.value_map)
            return SSABranch(
                condition,
                instruction.true_target,
                instruction.false_target,
            )

        if isinstance(instruction, IRJump):
            return SSAJump(instruction.target)

        return None

    def _merge_slot_states(
        self,
        merge_block: IRBasicBlock,
        then_name: str,
        then_slots: dict[str, SSAValue],
        else_name: str,
        else_slots: dict[str, SSAValue],
        entry_slots: dict[str, SSAValue],
    ) -> _SlotMerge:
        phi_names = self._first_merge_load_names(merge_block)
        instructions: list[SSAInstruction] = []
        merged_slots: dict[str, SSAValue] = {}
        incomplete_slots: set[str] = set()

        slot_names = set(entry_slots) | set(then_slots) | set(else_slots)
        for slot_name in sorted(slot_names):
            then_value = then_slots.get(slot_name, entry_slots.get(slot_name))
            else_value = else_slots.get(slot_name, entry_slots.get(slot_name))

            if then_value is None or else_value is None:
                incomplete_slots.add(slot_name)
                continue

            phi = self._create_merge_phi(
                slot_name,
                then_name,
                then_value,
                else_name,
                else_value,
                phi_names,
                merge_block,
            )
            if phi is None:
                merged_slots[slot_name] = then_value
                continue

            instructions.append(phi)
            merged_slots[slot_name] = phi.result

        return _SlotMerge(instructions, merged_slots, incomplete_slots)

    def _create_merge_phi(
        self,
        slot_name: str,
        then_name: str,
        then_value: SSAValue,
        else_name: str,
        else_value: SSAValue,
        phi_names: dict[str, str],
        merge_block: IRBasicBlock,
    ) -> SSAPhi | None:
        if then_value == else_value:
            return None

        if then_value.type != else_value.type:
            self._fail(
                f"Cannot create phi for slot '%{slot_name}' with incompatible "
                f"types {then_value.type} and {else_value.type}."
            )

        result_name = phi_names.get(slot_name)
        if result_name is None:
            result_name = self._fresh_phi_name(slot_name, merge_block)
        result = SSAValue(result_name, then_value.type)
        return SSAPhi(result, ((then_name, then_value), (else_name, else_value)))

    @staticmethod
    def _first_merge_load_names(block: IRBasicBlock) -> dict[str, str]:
        names: dict[str, str] = {}
        for instruction in block.instructions:
            if isinstance(instruction, IRLoad):
                names.setdefault(instruction.slot.name, instruction.result.name)
        return names

    def _plan_loop_phis(
        self,
        simple_while: _SimpleWhile,
        entry_state: _BuildState,
    ) -> _LoopPhiPlan:
        phi_names = self._first_loop_load_names(simple_while)
        phis: dict[str, SSAValue] = {}

        for slot_name in self._loop_phi_slots(simple_while):
            entry_value = entry_state.slot_values.get(slot_name)
            if entry_value is None:
                self._fail(
                    f"Loop-carried slot '%{slot_name}' is not initialized before "
                    "the loop."
                )

            result_name = phi_names.get(slot_name)
            if result_name is None:
                result_name = self._fresh_phi_name(
                    slot_name,
                    simple_while.condition_block,
                )
            phis[slot_name] = SSAValue(result_name, entry_value.type)

        return _LoopPhiPlan(sorted(phis), phis)

    def _build_loop_phi_instructions(
        self,
        simple_while: _SimpleWhile,
        entry_state: _BuildState,
        body_state: _BuildState,
        phi_plan: _LoopPhiPlan,
    ) -> list[SSAInstruction]:
        instructions: list[SSAInstruction] = []

        for slot_name in phi_plan.slot_names:
            entry_value = entry_state.slot_values[slot_name]
            body_value = body_state.slot_values.get(slot_name)
            if body_value is None:
                self._fail(
                    f"Loop-carried slot '%{slot_name}' is not defined by the loop body."
                )
            if entry_value.type != body_value.type:
                self._fail(
                    f"Cannot create phi for slot '%{slot_name}' with incompatible "
                    f"types {entry_value.type} and {body_value.type}."
                )
            instructions.append(
                SSAPhi(
                    phi_plan.values[slot_name],
                    (
                        (simple_while.entry.name, entry_value),
                        (simple_while.body_block.name, body_value),
                    ),
                )
            )

        return instructions

    def _loop_phi_slots(self, simple_while: _SimpleWhile) -> list[str]:
        stored_in_body = self._stored_slots(simple_while.body_block)
        loaded_in_condition = self._loaded_slots(simple_while.condition_block)
        loaded_in_exit = self._loaded_slots(simple_while.exit_block)
        loaded_before_store = self._loaded_before_first_store(simple_while.body_block)

        return sorted(
            stored_in_body
            & (loaded_in_condition | loaded_in_exit | loaded_before_store)
        )

    @staticmethod
    def _stored_slots(block: IRBasicBlock) -> set[str]:
        return {
            instruction.slot.name
            for instruction in block.instructions
            if isinstance(instruction, IRStore)
        }

    @staticmethod
    def _loaded_slots(block: IRBasicBlock) -> set[str]:
        return {
            instruction.slot.name
            for instruction in block.instructions
            if isinstance(instruction, IRLoad)
        }

    @staticmethod
    def _loaded_before_first_store(block: IRBasicBlock) -> set[str]:
        stored: set[str] = set()
        loaded_before_store: set[str] = set()
        for instruction in block.instructions:
            if isinstance(instruction, IRLoad) and instruction.slot.name not in stored:
                loaded_before_store.add(instruction.slot.name)
            elif isinstance(instruction, IRStore):
                stored.add(instruction.slot.name)
        return loaded_before_store

    @staticmethod
    def _first_loop_load_names(simple_while: _SimpleWhile) -> dict[str, str]:
        names: dict[str, str] = {}
        for block in (
            simple_while.condition_block,
            simple_while.body_block,
            simple_while.exit_block,
        ):
            for instruction in block.instructions:
                if isinstance(instruction, IRLoad):
                    names.setdefault(instruction.slot.name, instruction.result.name)
        return names

    @staticmethod
    def _fresh_phi_name(slot_name: str, block: IRBasicBlock) -> str:
        return f"{block.name}.{slot_name}.phi"

    @staticmethod
    def _terminator(block: IRBasicBlock) -> IRInstruction | None:
        if not block.instructions:
            return None
        terminator = block.instructions[-1]
        if isinstance(terminator, (IRBranch, IRJump, IRReturn)):
            return terminator
        return None

    @staticmethod
    def _has_control_flow_before_terminator(block: IRBasicBlock) -> bool:
        return any(
            isinstance(instruction, (IRBranch, IRJump, IRReturn))
            for instruction in block.instructions[:-1]
        )

    @staticmethod
    def _define_value(
        value: IRValue,
        value_map: dict[str, SSAValue],
    ) -> SSAValue:
        ssa_value = SSAValue(value.name, value.type)
        value_map[value.name] = ssa_value
        return ssa_value

    @staticmethod
    def _resolve_value(
        value: IRValue,
        value_map: dict[str, SSAValue],
    ) -> SSAValue:
        ssa_value = value_map.get(value.name)
        if ssa_value is None:
            raise SSABuildError(f"Use of undefined IR value '{SSABuilder._value(value)}'.")
        return ssa_value

    @staticmethod
    def _value(value: IRValue) -> str:
        return value.name if value.name.startswith("%") else f"%{value.name}"

    @staticmethod
    def _fail(message: str) -> NoReturn:
        raise SSABuildError(message)
