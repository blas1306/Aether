"""Independent Initial-IR to SSA refinement verification.

This verifier intentionally does not import the SSA builder, CFG builder,
dominators, dominance frontiers, phi placement, or renamer.  It proves a
cross-representation relation instead: reachable CFG structure and preserved
instructions must correspond exactly, while a forward reaching-value analysis
explains promoted loads/stores and the phis that join their values.

The input contract is lifecycle-normalized Initial IR.  Keeping normalization
outside this module makes the exact input observed by the producer explicit
and avoids silently verifying a different program.
"""

from __future__ import annotations

from dataclasses import fields
from typing import Hashable, Iterable, Mapping

from aether.ir.model import (
    IRBasicBlock,
    IRBranch,
    IRFunction,
    IRInstruction,
    IRInvoke,
    IRInvokeIndirect,
    IRInvokeInterface,
    IRJump,
    IRLoad,
    IRModule,
    IRPropagate,
    IRRethrow,
    IRReturn,
    IRStore,
    IRThrow,
    IRValue,
)
from aether.ssa.model import (
    SSAFunction,
    SSAInstruction,
    SSAModule,
    SSAPhi,
    SSAValue,
)


Origin = tuple[Hashable, ...]
Provenance = frozenset[Origin]


class SSARefinementVerificationError(ValueError):
    """The received SSA is not a justified refinement of the Initial IR."""


class SSARefinementVerifier:
    """Verify a lifecycle-normalized Initial IR module against produced SSA.

    This API is deliberately opt-in.  No production lowering path invokes it
    in RUST-4.1.
    """

    def __init__(self, initial: IRModule, ssa: SSAModule) -> None:
        self.initial = initial
        self.ssa = ssa

    def verify(self) -> SSAModule:
        self._verify_module_metadata()
        for initial_function, ssa_function in zip(
            self.initial.functions, self.ssa.functions, strict=True
        ):
            _FunctionRefinementVerifier(initial_function, ssa_function).verify()
        return self.ssa

    def _verify_module_metadata(self) -> None:
        if len(self.initial.functions) != len(self.ssa.functions):
            self._fail(
                "function count changed: "
                f"Initial IR has {len(self.initial.functions)}, SSA has "
                f"{len(self.ssa.functions)}"
            )
        if self.initial.structs != self.ssa.structs:
            self._fail("module struct definitions changed")

    @staticmethod
    def _fail(message: str) -> None:
        raise SSARefinementVerificationError(message)


class _FunctionRefinementVerifier:
    def __init__(self, initial: IRFunction, ssa: SSAFunction) -> None:
        self.initial = initial
        self.ssa = ssa
        self._initial_blocks = {block.name: block for block in initial.blocks}
        self._ssa_blocks = {block.name: block for block in ssa.blocks}
        self._successors: dict[str, tuple[str, ...]] = {}
        self._predecessors: dict[str, set[str]] = {}
        self._reachable: tuple[str, ...] = ()
        self._initial_origins: dict[str, Provenance] = {}
        self._load_origins: dict[tuple[str, int], Provenance] = {}
        self._load_origins_by_name: dict[str, Provenance] = {}
        self._slot_out: dict[str, dict[str, Provenance]] = {}
        self._slot_types: dict[str, object] = {}
        self._ssa_origins: dict[str, Provenance] = {}
        self._aligned: list[
            tuple[str, int, IRInstruction, SSAInstruction]
        ] = []

    def verify(self) -> None:
        self._verify_function_metadata()
        self._derive_cfg()
        self._verify_cfg_refinement()
        self._index_initial_origins()
        self._analyze_promoted_slots()
        self._align_preserved_instructions()
        self._index_ssa_preserved_origins()
        self._derive_phi_origins()
        self._verify_phis()
        self._verify_preserved_instructions()

    def _context(self, message: str) -> str:
        return f"function '{self.initial.name}': {message}"

    def _fail(self, message: str) -> None:
        raise SSARefinementVerificationError(self._context(message))

    def _verify_function_metadata(self) -> None:
        if self.initial.name != self.ssa.name:
            self._fail(
                f"function identity changed to '{self.ssa.name}'"
            )
        if self.initial.return_type != self.ssa.return_type:
            self._fail("return type changed")
        if self.initial.may_throw != self.ssa.may_throw:
            self._fail("may_throw contract changed")
        if len(self.initial.parameters) != len(self.ssa.parameters):
            self._fail("parameter count changed")
        for index, (initial, ssa) in enumerate(
            zip(self.initial.parameters, self.ssa.parameters, strict=True)
        ):
            if initial.name != ssa.name or initial.type != ssa.type:
                self._fail(f"parameter {index} changed")
            origin = frozenset({("parameter", index, initial.name)})
            self._initial_origins[initial.name] = origin
            self._ssa_origins[ssa.name] = origin

    def _derive_cfg(self) -> None:
        if not self.initial.blocks:
            self._fail("Initial IR has no entry block")
        if len(self._initial_blocks) != len(self.initial.blocks):
            self._fail("Initial IR contains duplicate block names")
        if len(self._ssa_blocks) != len(self.ssa.blocks):
            self._fail("SSA contains duplicate block names")

        for block in self.initial.blocks:
            successors = self._terminator_successors(block)
            for target in successors:
                if target not in self._initial_blocks:
                    self._fail(
                        f"block '{block.name}' targets missing block '{target}'"
                    )
            self._successors[block.name] = successors

        entry = self.initial.blocks[0].name
        seen: set[str] = set()
        worklist = [entry]
        while worklist:
            block_name = worklist.pop()
            if block_name in seen:
                continue
            seen.add(block_name)
            worklist.extend(reversed(self._successors[block_name]))
        self._reachable = tuple(
            block.name for block in self.initial.blocks if block.name in seen
        )
        self._predecessors = {name: set() for name in self._reachable}
        for source in self._reachable:
            for target in self._successors[source]:
                if target in seen:
                    self._predecessors[target].add(source)

    def _terminator_successors(self, block: IRBasicBlock) -> tuple[str, ...]:
        if not block.instructions:
            self._fail(f"block '{block.name}' has no terminator")
        terminator = block.instructions[-1]
        if isinstance(terminator, IRBranch):
            return tuple(dict.fromkeys((terminator.true_target, terminator.false_target)))
        if isinstance(terminator, IRJump):
            return (terminator.target,)
        if isinstance(terminator, (IRInvoke, IRInvokeIndirect, IRInvokeInterface)):
            return tuple(
                dict.fromkeys(
                    (terminator.normal_target, terminator.exceptional_target)
                )
            )
        if isinstance(terminator, (IRThrow, IRRethrow, IRPropagate)):
            return () if terminator.target is None else (terminator.target,)
        if isinstance(terminator, IRReturn):
            return ()
        self._fail(
            f"block '{block.name}' ends in unsupported terminator "
            f"{type(terminator).__name__}"
        )

    def _verify_cfg_refinement(self) -> None:
        expected = list(self._reachable)
        actual = [block.name for block in self.ssa.blocks]
        if actual != expected:
            self._fail(
                "reachable block sequence changed: "
                f"expected {expected!r}, got {actual!r}"
            )
        if self.ssa.entry_block != expected[0]:
            self._fail(
                f"entry changed from '{expected[0]}' to '{self.ssa.entry_block}'"
            )

    @staticmethod
    def _definition_fields(instruction: object) -> tuple[str, ...]:
        result: list[str] = []
        for descriptor in fields(instruction):
            value = getattr(instruction, descriptor.name)
            if not isinstance(value, (IRValue, SSAValue)):
                continue
            if descriptor.name == "result" or descriptor.metadata.get("ir_definition"):
                result.append(descriptor.name)
        return tuple(result)

    def _index_initial_origins(self) -> None:
        for block_name in self._reachable:
            block = self._initial_blocks[block_name]
            for index, instruction in enumerate(block.instructions):
                if isinstance(instruction, (IRLoad, IRStore)):
                    if instruction.slot.name in self._slot_types:
                        if self._slot_types[instruction.slot.name] != instruction.slot.type:
                            self._fail(
                                f"slot '{instruction.slot.name}' changes type"
                            )
                    else:
                        self._slot_types[instruction.slot.name] = instruction.slot.type
                    continue
                for field_name in self._definition_fields(instruction):
                    value = getattr(instruction, field_name)
                    if value.name in self._initial_origins:
                        self._fail(f"Initial IR value '{value.name}' is defined twice")
                    self._initial_origins[value.name] = frozenset(
                        {("instruction", block_name, index, field_name)}
                    )

    def _analyze_promoted_slots(self) -> None:
        """Compute slot reaching *values*, independently of phi placement."""

        entry = self._reachable[0]
        block_in: dict[str, dict[str, Provenance]] = {
            name: {slot: frozenset() for slot in self._slot_types}
            for name in self._reachable
        }
        block_out: dict[str, dict[str, Provenance]] = {
            name: {slot: frozenset() for slot in self._slot_types}
            for name in self._reachable
        }
        loads: dict[tuple[str, int], Provenance] = {}
        loads_by_name: dict[str, Provenance] = {}
        maximum = max(1, len(self._reachable) * (len(self._slot_types) + 1) * 4)
        for _iteration in range(maximum):
            changed = False
            for block_name in self._reachable:
                if block_name == entry:
                    incoming: dict[str, Provenance] = {
                        slot: frozenset({("uninitialized", slot)})
                        for slot in self._slot_types
                    }
                else:
                    incoming = self._join_slot_states(
                        block_out[pred]
                        for pred in self._predecessors[block_name]
                    )
                aliases = {**self._initial_origins, **loads_by_name}
                state = dict(incoming)
                block = self._initial_blocks[block_name]
                for index, instruction in enumerate(block.instructions):
                    if isinstance(instruction, IRLoad):
                        value = state.get(instruction.slot.name, frozenset())
                        if loads.get((block_name, index)) != value:
                            changed = True
                        aliases[instruction.result.name] = value
                        loads[(block_name, index)] = value
                        loads_by_name[instruction.result.name] = value
                    elif isinstance(instruction, IRStore):
                        value = aliases.get(instruction.value.name)
                        state[instruction.slot.name] = value or frozenset()
                if incoming != block_in[block_name] or state != block_out[block_name]:
                    block_in[block_name] = incoming
                    block_out[block_name] = state
                    changed = True
            if not changed:
                self._slot_out = block_out
                self._load_origins = loads
                self._load_origins_by_name = loads_by_name
                empty_loads = [
                    self._initial_blocks[block_name].instructions[index].result.name
                    for (block_name, index), value in loads.items()
                    if not value
                    or any(origin[0] == "uninitialized" for origin in value)
                ]
                if empty_loads:
                    self._fail(
                        "promoted loads have no reaching value: "
                        + ", ".join(sorted(empty_loads))
                    )
                return
        self._fail("reaching-value dataflow did not converge")

    @staticmethod
    def _join_slot_states(
        states: Iterable[Mapping[str, Provenance]],
    ) -> dict[str, Provenance]:
        materialized = list(states)
        if not materialized:
            return {}
        all_slots: set[str] = set()
        for state in materialized:
            all_slots.update(state)
        return {
            slot: frozenset().union(
                *(state.get(slot, frozenset()) for state in materialized)
            )
            for slot in all_slots
        }

    def _align_preserved_instructions(self) -> None:
        for block_name in self._reachable:
            initial_instructions = [
                (index, instruction)
                for index, instruction in enumerate(
                    self._initial_blocks[block_name].instructions
                )
                if not isinstance(instruction, (IRLoad, IRStore))
            ]
            ssa_instructions = self._ssa_blocks[block_name].instructions
            first_non_phi = 0
            while (
                first_non_phi < len(ssa_instructions)
                and isinstance(ssa_instructions[first_non_phi], SSAPhi)
            ):
                first_non_phi += 1
            if any(
                isinstance(instruction, SSAPhi)
                for instruction in ssa_instructions[first_non_phi:]
            ):
                self._fail(f"block '{block_name}' has a non-prefix phi")
            preserved = ssa_instructions[first_non_phi:]
            if len(initial_instructions) != len(preserved):
                self._fail(
                    f"block '{block_name}' preserved instruction count changed: "
                    f"expected {len(initial_instructions)}, got {len(preserved)}"
                )
            for (index, initial), ssa in zip(
                initial_instructions, preserved, strict=True
            ):
                expected_kind = "SSA" + type(initial).__name__[2:]
                if type(ssa).__name__ != expected_kind:
                    self._fail(
                        f"block '{block_name}' instruction {index} changed opcode "
                        f"from {type(initial).__name__} to {type(ssa).__name__}"
                    )
                self._aligned.append((block_name, index, initial, ssa))

    def _index_ssa_preserved_origins(self) -> None:
        for block_name, index, initial, ssa in self._aligned:
            initial_definitions = self._definition_fields(initial)
            ssa_definitions = self._definition_fields(ssa)
            if initial_definitions != ssa_definitions:
                self._fail(
                    f"block '{block_name}' instruction {index} definition shape changed"
                )
            for field_name in initial_definitions:
                initial_value = getattr(initial, field_name)
                ssa_value = getattr(ssa, field_name)
                if initial_value.type != ssa_value.type:
                    self._fail(
                        f"block '{block_name}' instruction {index} result type changed"
                    )
                if ssa_value.name in self._ssa_origins:
                    self._fail(f"SSA value '{ssa_value.name}' is defined twice")
                self._ssa_origins[ssa_value.name] = self._initial_origins[
                    initial_value.name
                ]

    def _derive_phi_origins(self) -> None:
        phis = [
            instruction
            for block in self.ssa.blocks
            for instruction in block.instructions
            if isinstance(instruction, SSAPhi)
        ]
        for phi in phis:
            if phi.result.name in self._ssa_origins:
                self._fail(f"SSA value '{phi.result.name}' is defined twice")
            self._ssa_origins[phi.result.name] = frozenset()

        maximum = max(1, len(phis) * (len(self._initial_origins) + 1) + 1)
        for _iteration in range(maximum):
            changed = False
            for phi in phis:
                value = frozenset().union(
                    *(self._ssa_origins.get(incoming.name, frozenset())
                      for _block, incoming in phi.incoming)
                )
                if value != self._ssa_origins[phi.result.name]:
                    self._ssa_origins[phi.result.name] = value
                    changed = True
            if not changed:
                return
        self._fail("SSA phi provenance did not converge")

    def _verify_phis(self) -> None:
        for block_name in self._reachable:
            phis = [
                instruction
                for instruction in self._ssa_blocks[block_name].instructions
                if isinstance(instruction, SSAPhi)
            ]
            predecessors = self._predecessors[block_name]
            candidates: list[set[str]] = []
            for phi in phis:
                if len(predecessors) < 2:
                    self._fail(
                        f"phi '{phi.result.name}' in block '{block_name}' has no "
                        "control-flow join to justify it"
                    )
                incoming = dict(phi.incoming)
                if len(incoming) != len(phi.incoming) or set(incoming) != predecessors:
                    self._fail(
                        f"phi '{phi.result.name}' in block '{block_name}' does not "
                        "have exactly one incoming per predecessor"
                    )
                matching_slots: set[str] = set()
                for slot, slot_type in self._slot_types.items():
                    if phi.result.type != slot_type:
                        continue
                    if all(
                        slot in self._slot_out[pred]
                        and incoming[pred].type == slot_type
                        and self._ssa_origins.get(incoming[pred].name)
                        == self._slot_out[pred][slot]
                        for pred in predecessors
                    ):
                        matching_slots.add(slot)
                if not matching_slots:
                    self._fail(
                        f"phi '{phi.result.name}' in block '{block_name}' is not "
                        "justified by any promoted slot"
                    )
                if not self._ssa_origins[phi.result.name]:
                    self._fail(
                        f"phi '{phi.result.name}' in block '{block_name}' has no "
                        "value provenance"
                    )
                candidates.append(matching_slots)
            if not self._has_distinct_slot_assignment(candidates):
                self._fail(
                    f"block '{block_name}' has duplicate or ambiguous extra phis"
                )

    @staticmethod
    def _has_distinct_slot_assignment(candidates: list[set[str]]) -> bool:
        assigned: dict[str, int] = {}

        def assign(phi_index: int, visited: set[str]) -> bool:
            for slot in sorted(candidates[phi_index]):
                if slot in visited:
                    continue
                visited.add(slot)
                previous = assigned.get(slot)
                if previous is None or assign(previous, visited):
                    assigned[slot] = phi_index
                    return True
            return False

        return all(assign(index, set()) for index in range(len(candidates)))

    def _verify_preserved_instructions(self) -> None:
        for block_name, index, initial, ssa in self._aligned:
            initial_definitions = set(self._definition_fields(initial))
            ssa_fields = {descriptor.name for descriptor in fields(ssa)}
            for descriptor in fields(initial):
                name = descriptor.name
                initial_value = getattr(initial, name)
                if name in initial_definitions:
                    continue
                if name == "transferred_storage":
                    if initial_value is not None:
                        self._fail(
                            "input is not lifecycle-normalized: return still "
                            "carries transferred_storage"
                        )
                    continue
                if name in {"target_event", "exceptional_target_event"}:
                    continue
                if name == "may_throw_effect":
                    continue
                if name not in ssa_fields:
                    self._fail(
                        f"block '{block_name}' instruction {index} lost field '{name}'"
                    )
                self._compare_field(
                    initial_value,
                    getattr(ssa, name),
                    block_name,
                    index,
                    name,
                )
            self._verify_synthesized_fields(
                initial, ssa, block_name, index, ssa_fields
            )

    def _compare_field(
        self,
        initial: object,
        ssa: object,
        block_name: str,
        index: int,
        field_name: str,
    ) -> None:
        if isinstance(initial, IRValue):
            if not isinstance(ssa, SSAValue):
                self._fail(
                    f"block '{block_name}' instruction {index} field "
                    f"'{field_name}' is no longer a value"
                )
            expected = self._expected_initial_value(initial, block_name, index)
            actual = self._ssa_origins.get(ssa.name)
            if initial.type != ssa.type or actual != expected:
                self._fail(
                    f"block '{block_name}' instruction {index} field "
                    f"'{field_name}' changed value provenance"
                )
            return
        if isinstance(initial, tuple):
            if not isinstance(ssa, tuple) or len(initial) != len(ssa):
                self._fail(
                    f"block '{block_name}' instruction {index} field "
                    f"'{field_name}' changed arity"
                )
            for position, (left, right) in enumerate(zip(initial, ssa, strict=True)):
                self._compare_field(
                    left, right, block_name, index, f"{field_name}[{position}]"
                )
            return
        if initial != ssa:
            self._fail(
                f"block '{block_name}' instruction {index} field "
                f"'{field_name}' changed"
            )

    def _expected_initial_value(
        self, value: IRValue, block_name: str, instruction_index: int
    ) -> Provenance | None:
        direct = self._initial_origins.get(value.name)
        if direct is not None:
            return direct
        return self._load_origins_by_name.get(value.name)

    def _verify_synthesized_fields(
        self,
        initial: IRInstruction,
        ssa: SSAInstruction,
        block_name: str,
        index: int,
        ssa_fields: set[str],
    ) -> None:
        initial_fields = {descriptor.name for descriptor in fields(initial)}
        allowed_extra: set[str] = set()
        if "bounds_checked" in ssa_fields and not getattr(ssa, "bounds_checked"):
            self._fail(
                f"block '{block_name}' instruction {index} disabled bounds checks"
            )
        if "bounds_checked" in ssa_fields:
            allowed_extra.add("bounds_checked")
        if isinstance(initial, (IRInvoke, IRInvokeIndirect, IRInvokeInterface)):
            allowed_extra.update(("normal_arguments", "exceptional_arguments"))
            expected_normal = () if initial.result is None else (getattr(ssa, "result"),)
            if getattr(ssa, "normal_arguments") != expected_normal:
                self._fail(
                    f"block '{block_name}' instruction {index} changed normal edge value"
                )
            if getattr(ssa, "exceptional_arguments") != (getattr(ssa, "exception"),):
                self._fail(
                    f"block '{block_name}' instruction {index} changed exceptional edge value"
                )
        if isinstance(initial, (IRThrow, IRRethrow, IRPropagate)):
            allowed_extra.add("exceptional_arguments")
            expected = () if initial.target is None else (getattr(ssa, "event"),)
            if getattr(ssa, "exceptional_arguments") != expected:
                self._fail(
                    f"block '{block_name}' instruction {index} changed transfer edge value"
                )
        unexpected = ssa_fields - initial_fields - allowed_extra
        if unexpected:
            self._fail(
                f"block '{block_name}' instruction {index} has unjustified fields: "
                + ", ".join(sorted(unexpected))
            )


def verify_ssa_refinement(initial: IRModule, ssa: SSAModule) -> SSAModule:
    """Convenience opt-in entry point."""

    return SSARefinementVerifier(initial, ssa).verify()
