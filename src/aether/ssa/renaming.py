from __future__ import annotations

from dataclasses import dataclass, field
from typing import NoReturn

from aether.analysis.cfg import CFG
from aether.analysis.dominators import DominatorResult
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
    IRMatrixColumns,
    IRMatrixAdd,
    IRMatrixScale,
    IRMatrixSub,
    IRMatrixGet,
    IRMatrixNew,
    IRMatrixRows,
    IRMatrixSet,
    IRReturn,
    IRStore,
    IRValue,
    IRVectorGet,
    IRVectorAdd,
    IRVectorDot,
    IRVectorScale,
    IRVectorSub,
    IRVectorLength,
    IRVectorNew,
    IRVectorSet,
)
from aether.ir.types import IRType

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
    SSAMatrixScale,
    SSAMatrixSub,
    SSAMatrixGet,
    SSAMatrixNew,
    SSAMatrixRows,
    SSAMatrixSet,
    SSAParameter,
    SSAPhi,
    SSAReturn,
    SSAValue,
    SSAVectorGet,
    SSAVectorAdd,
    SSAVectorDot,
    SSAVectorScale,
    SSAVectorSub,
    SSAVectorLength,
    SSAVectorNew,
    SSAVectorSet,
)


_MISSING = object()


class SSARenameError(ValueError):
    """Raised when general SSA renaming cannot safely promote slot IR."""


@dataclass(frozen=True)
class SSARenameResult:
    """Experimental result for one function-local SSA renaming run."""

    function: SSAFunction
    phi_slots_by_block: dict[str, tuple[str, ...]]


@dataclass
class _PhiState:
    slot_name: str
    result: SSAValue
    incoming: list[tuple[str, SSAValue]] = field(default_factory=list)


class SSARenamer:
    """Convert one slot-based IR function into SSA with dominator-tree DFS.

    This is intentionally standalone. It consumes phi locations computed
    elsewhere, rewrites loads and stores with per-slot stacks, and returns an
    ``SSAFunction`` for the general builder.
    """

    def __init__(
        self,
        function: IRFunction,
        cfg: CFG,
        dominators: DominatorResult,
        phi_placement: dict[str, set[str]],
    ) -> None:
        self.function = function
        self.cfg = cfg
        self.dominators = dominators
        self.phi_placement = phi_placement

        self._blocks = {block.name: block for block in function.blocks}
        self._block_order = {
            block.name: index for index, block in enumerate(function.blocks)
        }
        self._successors = self._build_successors()
        self._slot_types: dict[str, IRType] = {}
        self._stacks: dict[str, list[SSAValue]] = {}
        self._value_map: dict[str, SSAValue] = {}
        self._definitions: set[str] = set()
        self._phi_states: dict[str, list[_PhiState]] = {}
        self._ssa_instructions: dict[str, list[SSAInstruction]] = {}
        self._visited: set[str] = set()

    def rename(self) -> SSARenameResult:
        self._validate_cfg()
        self._slot_types = self._collect_slot_types()
        self._initialize_parameters()
        self._initialize_phi_states()

        if not self.function.blocks:
            self._fail(f"Function '{self.function.name}' has no entry block.")

        entry = self.function.blocks[0].name
        self._rename_block(entry)
        self._verify_all_reachable_blocks_visited(entry)

        ssa_function = SSAFunction(
            self.function.name,
            [
                SSAParameter(parameter.name, parameter.type)
                for parameter in self.function.parameters
            ],
            self.function.return_type,
            self._assemble_blocks(),
            entry,
        )
        return SSARenameResult(
            ssa_function,
            {
                block_name: tuple(phi.slot_name for phi in phis)
                for block_name, phis in self._phi_states.items()
                if phis
            },
        )

    def _rename_block(self, block_name: str) -> None:
        if block_name in self._visited:
            return
        self._visited.add(block_name)

        block = self._blocks[block_name]
        pushed_slots: list[str] = []
        bound_values: list[tuple[str, SSAValue | object]] = []
        instructions: list[SSAInstruction] = []

        for phi in self._phi_states.get(block_name, ()):
            self._bind_value(phi.result.name, phi.result, bound_values)
            self._push_slot(phi.slot_name, phi.result)
            pushed_slots.append(phi.slot_name)

        for instruction in block.instructions:
            converted = self._convert_instruction(
                instruction,
                pushed_slots,
                bound_values,
            )
            if converted is not None:
                instructions.append(converted)

        self._ssa_instructions[block_name] = instructions
        self._add_successor_phi_incomings(block_name)

        for child in self._dominator_children(block_name):
            self._rename_block(child)

        for slot_name in reversed(pushed_slots):
            self._pop_slot(slot_name)
        for value_name, previous in reversed(bound_values):
            if previous is _MISSING:
                self._value_map.pop(value_name, None)
            else:
                self._value_map[value_name] = previous

    def _convert_instruction(
        self,
        instruction: IRInstruction,
        pushed_slots: list[str],
        bound_values: list[tuple[str, SSAValue | object]],
    ) -> SSAInstruction | None:
        if isinstance(instruction, IRConst):
            result = self._define_value(instruction.result)
            self._bind_value(result.name, result, bound_values)
            return SSAConst(result, instruction.value)

        if isinstance(instruction, IRBinaryOp):
            result = self._define_value(instruction.result)
            left = self._resolve_value(instruction.left)
            right = self._resolve_value(instruction.right)
            self._bind_value(result.name, result, bound_values)
            return SSABinaryOp(result, instruction.operator, left, right)

        if isinstance(instruction, IRCompareOp):
            result = self._define_value(instruction.result)
            left = self._resolve_value(instruction.left)
            right = self._resolve_value(instruction.right)
            self._bind_value(result.name, result, bound_values)
            return SSACompareOp(result, instruction.operator, left, right)

        if isinstance(instruction, IRCast):
            result = self._define_value(instruction.result)
            value = self._resolve_value(instruction.value)
            self._bind_value(result.name, result, bound_values)
            return SSACast(result, value)

        if isinstance(instruction, IRCall):
            arguments = tuple(
                self._resolve_value(argument) for argument in instruction.arguments
            )
            result = None
            if instruction.result is not None:
                result = self._define_value(instruction.result)
                self._bind_value(result.name, result, bound_values)
            return SSACall(instruction.function, arguments, result)

        if isinstance(instruction, IRArrayNew):
            result = self._define_value(instruction.result)
            elements = tuple(
                self._resolve_value(element) for element in instruction.elements
            )
            self._bind_value(result.name, result, bound_values)
            return SSAArrayNew(result, elements)

        if isinstance(instruction, IRVectorNew):
            result = self._define_value(instruction.result)
            elements = tuple(
                self._resolve_value(element) for element in instruction.elements
            )
            self._bind_value(result.name, result, bound_values)
            return SSAVectorNew(result, elements, instruction.orientation)

        if isinstance(instruction, IRMatrixNew):
            result = self._define_value(instruction.result)
            elements = tuple(
                self._resolve_value(element) for element in instruction.elements
            )
            self._bind_value(result.name, result, bound_values)
            return SSAMatrixNew(result, elements, instruction.rows, instruction.cols)

        if isinstance(instruction, IRVectorAdd):
            result = self._define_value(instruction.result)
            left = self._resolve_value(instruction.left)
            right = self._resolve_value(instruction.right)
            self._bind_value(result.name, result, bound_values)
            return SSAVectorAdd(result, left, right, instruction.length, instruction.orientation)

        if isinstance(instruction, IRVectorSub):
            result = self._define_value(instruction.result)
            left = self._resolve_value(instruction.left)
            right = self._resolve_value(instruction.right)
            self._bind_value(result.name, result, bound_values)
            return SSAVectorSub(result, left, right, instruction.length, instruction.orientation)

        if isinstance(instruction, IRVectorScale):
            result = self._define_value(instruction.result)
            vector = self._resolve_value(instruction.vector)
            scalar = self._resolve_value(instruction.scalar)
            self._bind_value(result.name, result, bound_values)
            return SSAVectorScale(result, vector, scalar, instruction.length, instruction.orientation)

        if isinstance(instruction, IRVectorDot):
            result = self._define_value(instruction.result)
            left = self._resolve_value(instruction.left)
            right = self._resolve_value(instruction.right)
            self._bind_value(result.name, result, bound_values)
            return SSAVectorDot(result, left, right, instruction.length)

        if isinstance(instruction, IRMatrixAdd):
            result = self._define_value(instruction.result)
            left = self._resolve_value(instruction.left)
            right = self._resolve_value(instruction.right)
            self._bind_value(result.name, result, bound_values)
            return SSAMatrixAdd(result, left, right, instruction.rows, instruction.cols)

        if isinstance(instruction, IRMatrixSub):
            result = self._define_value(instruction.result)
            left = self._resolve_value(instruction.left)
            right = self._resolve_value(instruction.right)
            self._bind_value(result.name, result, bound_values)
            return SSAMatrixSub(result, left, right, instruction.rows, instruction.cols)

        if isinstance(instruction, IRMatrixScale):
            result = self._define_value(instruction.result)
            matrix = self._resolve_value(instruction.matrix)
            scalar = self._resolve_value(instruction.scalar)
            self._bind_value(result.name, result, bound_values)
            return SSAMatrixScale(result, matrix, scalar, instruction.rows, instruction.cols)

        if isinstance(instruction, IRArrayGet):
            result = self._define_value(instruction.result)
            array = self._resolve_value(instruction.array)
            index = self._resolve_value(instruction.index)
            self._bind_value(result.name, result, bound_values)
            return SSAArrayGet(result, array, index)

        if isinstance(instruction, IRVectorGet):
            result = self._define_value(instruction.result)
            vector = self._resolve_value(instruction.vector)
            index = self._resolve_value(instruction.index)
            self._bind_value(result.name, result, bound_values)
            return SSAVectorGet(result, vector, index)

        if isinstance(instruction, IRMatrixGet):
            result = self._define_value(instruction.result)
            matrix = self._resolve_value(instruction.matrix)
            row = self._resolve_value(instruction.row)
            column = self._resolve_value(instruction.column)
            self._bind_value(result.name, result, bound_values)
            return SSAMatrixGet(result, matrix, row, column, instruction.cols)

        if isinstance(instruction, IRVectorLength):
            result = self._define_value(instruction.result)
            vector = self._resolve_value(instruction.vector)
            self._bind_value(result.name, result, bound_values)
            return SSAVectorLength(result, vector)

        if isinstance(instruction, IRMatrixRows):
            result = self._define_value(instruction.result)
            matrix = self._resolve_value(instruction.matrix)
            self._bind_value(result.name, result, bound_values)
            return SSAMatrixRows(result, matrix, instruction.rows)

        if isinstance(instruction, IRMatrixColumns):
            result = self._define_value(instruction.result)
            matrix = self._resolve_value(instruction.matrix)
            self._bind_value(result.name, result, bound_values)
            return SSAMatrixColumns(result, matrix, instruction.columns)

        if isinstance(instruction, IRArraySet):
            array = self._resolve_value(instruction.array)
            index = self._resolve_value(instruction.index)
            value = self._resolve_value(instruction.value)
            return SSAArraySet(array, index, value)

        if isinstance(instruction, IRVectorSet):
            vector = self._resolve_value(instruction.vector)
            index = self._resolve_value(instruction.index)
            value = self._resolve_value(instruction.value)
            return SSAVectorSet(vector, index, value)

        if isinstance(instruction, IRMatrixSet):
            matrix = self._resolve_value(instruction.matrix)
            row = self._resolve_value(instruction.row)
            column = self._resolve_value(instruction.column)
            value = self._resolve_value(instruction.value)
            return SSAMatrixSet(matrix, row, column, value, instruction.cols)

        if isinstance(instruction, IRArrayLength):
            result = self._define_value(instruction.result)
            array = self._resolve_value(instruction.array)
            self._bind_value(result.name, result, bound_values)
            return SSAArrayLength(result, array)

        if isinstance(instruction, IRStore):
            value = self._resolve_value(instruction.value)
            if value.type != instruction.slot.type:
                self._fail(
                    f"Store to slot '{self._ir_value(instruction.slot)}' type mismatch: "
                    f"expected {instruction.slot.type}, got {value.type}."
            )
            self._push_slot(instruction.slot.name, value)
            pushed_slots.append(instruction.slot.name)
            return None

        if isinstance(instruction, IRLoad):
            value = self._top_slot(instruction.slot)
            if value.type != instruction.result.type:
                self._fail(
                    f"Load from slot '{self._ir_value(instruction.slot)}' type mismatch: "
                    f"expected {instruction.result.type}, got {value.type}."
                )
            self._bind_value(instruction.result.name, value, bound_values)
            return None

        if isinstance(instruction, IRReturn):
            value = None
            if instruction.value is not None:
                value = self._resolve_value(instruction.value)
            return SSAReturn(value)

        if isinstance(instruction, IRBranch):
            condition = self._resolve_value(instruction.condition)
            return SSABranch(condition, instruction.true_target, instruction.false_target)

        if isinstance(instruction, IRJump):
            return SSAJump(instruction.target)

        self._fail(f"Unsupported IR instruction '{type(instruction).__name__}'.")

    def _add_successor_phi_incomings(self, block_name: str) -> None:
        for successor in self._successors[block_name]:
            for phi in self._phi_states.get(successor, ()):
                value = self._current_slot_value(phi.slot_name)
                if value is None:
                    self._fail(
                        f"Phi for slot '%{phi.slot_name}' in successor '{successor}' "
                        f"needs incoming from block '{block_name}', but no value is visible."
                    )
                if value.type != phi.result.type:
                    self._fail(
                        f"Cannot add incoming for phi '%{phi.result.name}' from block "
                        f"'{block_name}': expected {phi.result.type}, got {value.type}."
                    )
                phi.incoming.append((block_name, value))

    def _assemble_blocks(self) -> list[SSABasicBlock]:
        blocks: list[SSABasicBlock] = []
        for block in self.function.blocks:
            if block.name not in self._visited:
                continue

            phis = [
                SSAPhi(phi.result, tuple(phi.incoming))
                for phi in self._phi_states.get(block.name, ())
            ]
            blocks.append(
                SSABasicBlock(block.name, phis + self._ssa_instructions[block.name])
            )
        return blocks

    def _initialize_parameters(self) -> None:
        for parameter in self.function.parameters:
            value = SSAParameter(parameter.name, parameter.type)
            if value.name in self._definitions:
                self._fail(
                    f"Duplicate parameter '{value.name}' in function "
                    f"'{self.function.name}'."
                )
            self._definitions.add(value.name)
            self._value_map[value.name] = value

    def _initialize_phi_states(self) -> None:
        for slot_name, block_names in sorted(self.phi_placement.items()):
            slot_type = self._slot_types.get(slot_name)
            if slot_type is None:
                self._fail(f"Phi placement references unknown slot '%{slot_name}'.")

            for block_name in sorted(block_names, key=self._block_index):
                if block_name not in self._blocks:
                    self._fail(
                        f"Phi placement for slot '%{slot_name}' references unknown "
                        f"block '{block_name}'."
                    )
                result = self._fresh_phi_value(slot_name, block_name, slot_type)
                self._phi_states.setdefault(block_name, []).append(
                    _PhiState(slot_name, result)
                )

        for block_name, phis in self._phi_states.items():
            phis.sort(key=lambda phi: phi.slot_name)
            seen: set[str] = set()
            for phi in phis:
                if phi.slot_name in seen:
                    self._fail(
                        f"Duplicate phi placement for slot '%{phi.slot_name}' "
                        f"in block '{block_name}'."
                    )
                seen.add(phi.slot_name)

    def _fresh_phi_value(
        self,
        slot_name: str,
        block_name: str,
        slot_type: IRType,
    ) -> SSAValue:
        preferred = self._first_load_name(block_name, slot_name)
        if preferred is None:
            preferred = f"{block_name}.{slot_name}.phi"
        name = self._fresh_name(preferred)
        value = SSAValue(name, slot_type)
        self._definitions.add(name)
        return value

    def _first_load_name(self, block_name: str, slot_name: str) -> str | None:
        for instruction in self._blocks[block_name].instructions:
            if isinstance(instruction, IRLoad) and instruction.slot.name == slot_name:
                return instruction.result.name
        return None

    def _fresh_name(self, preferred: str) -> str:
        if preferred not in self._definitions:
            return preferred

        index = 1
        while f"{preferred}.{index}" in self._definitions:
            index += 1
        return f"{preferred}.{index}"

    def _collect_slot_types(self) -> dict[str, IRType]:
        slot_types: dict[str, IRType] = {}
        for block in self.function.blocks:
            for instruction in block.instructions:
                slot: IRValue | None = None
                if isinstance(instruction, IRStore):
                    slot = instruction.slot
                elif isinstance(instruction, IRLoad):
                    slot = instruction.slot

                if slot is None:
                    continue

                existing = slot_types.get(slot.name)
                if existing is not None and existing != slot.type:
                    self._fail(
                        f"Slot '%{slot.name}' has incompatible declared types "
                        f"{existing} and {slot.type}."
                    )
                slot_types[slot.name] = slot.type

        return slot_types

    def _define_value(self, value: IRValue) -> SSAValue:
        if value.name in self._definitions:
            self._fail(f"Duplicate SSA value '{self._ir_value(value)}'.")
        ssa_value = SSAValue(value.name, value.type)
        self._definitions.add(value.name)
        return ssa_value

    def _bind_value(
        self,
        name: str,
        value: SSAValue,
        bound_values: list[tuple[str, SSAValue | object]],
    ) -> None:
        bound_values.append((name, self._value_map.get(name, _MISSING)))
        self._value_map[name] = value

    def _resolve_value(self, value: IRValue) -> SSAValue:
        ssa_value = self._value_map.get(value.name)
        if ssa_value is None:
            self._fail(f"Use of undefined IR value '{self._ir_value(value)}'.")
        return ssa_value

    def _top_slot(self, slot: IRValue) -> SSAValue:
        value = self._current_slot_value(slot.name)
        if value is None:
            self._fail(f"Load from uninitialized slot '{self._ir_value(slot)}'.")
        return value

    def _current_slot_value(self, slot_name: str) -> SSAValue | None:
        stack = self._stacks.get(slot_name)
        if not stack:
            return None
        return stack[-1]

    def _push_slot(self, slot_name: str, value: SSAValue) -> None:
        self._stacks.setdefault(slot_name, []).append(value)

    def _pop_slot(self, slot_name: str) -> None:
        stack = self._stacks[slot_name]
        stack.pop()
        if not stack:
            del self._stacks[slot_name]

    def _build_successors(self) -> dict[str, list[str]]:
        successors = {block.name: [] for block in self.function.blocks}
        for edge in self.cfg.edges:
            if edge.source in successors:
                successors[edge.source].append(edge.target)
        return successors

    def _dominator_children(self, block_name: str) -> list[str]:
        children = self.dominators.dominator_tree_children(block_name)
        return sorted(children, key=self._block_index)

    def _block_index(self, block_name: str) -> int:
        return self._block_order.get(block_name, len(self._block_order))

    def _validate_cfg(self) -> None:
        block_names = set(self._blocks)
        cfg_nodes = [node.name for node in self.cfg.nodes]
        if len(cfg_nodes) != len(set(cfg_nodes)):
            self._fail(f"CFG for function '{self.function.name}' has duplicate nodes.")
        if set(cfg_nodes) != block_names:
            self._fail(
                f"CFG nodes for function '{self.function.name}' do not match IR blocks."
            )
        for edge in self.cfg.edges:
            if edge.source not in block_names:
                self._fail(f"CFG edge references unknown source block '{edge.source}'.")
            if edge.target not in block_names:
                self._fail(f"CFG edge references unknown target block '{edge.target}'.")

    def _verify_all_reachable_blocks_visited(self, entry: str) -> None:
        reachable = self._reachable_blocks(entry)
        missing = reachable - self._visited
        if missing:
            names = ", ".join(sorted(missing, key=self._block_index))
            self._fail(f"Dominator-tree DFS did not visit reachable block(s): {names}.")

    def _reachable_blocks(self, entry: str) -> set[str]:
        reachable: set[str] = set()
        worklist = [entry]
        while worklist:
            block_name = worklist.pop()
            if block_name in reachable:
                continue
            reachable.add(block_name)
            worklist.extend(
                successor
                for successor in self._successors[block_name]
                if successor not in reachable
            )
        return reachable

    @staticmethod
    def _ir_value(value: IRValue) -> str:
        return value.name if value.name.startswith("%") else f"%{value.name}"

    @staticmethod
    def _fail(message: str) -> NoReturn:
        raise SSARenameError(message)
