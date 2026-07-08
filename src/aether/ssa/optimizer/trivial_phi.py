from __future__ import annotations

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
    SSAModule,
    SSAPhi,
    SSAReturn,
    SSAValue,
)

from .result import SSAOptimizationResult


class TrivialPhiEliminator:
    """Remove phi nodes whose incoming values are all the same SSA value."""

    def run(self, module: SSAModule) -> SSAOptimizationResult:
        updated_functions: list[SSAFunction] = []
        removed_trivial_phis = 0
        rewritten_uses = 0

        for function in module.functions:
            replacements = self._collect_replacements(function)
            if not replacements:
                updated_functions.append(function)
                continue

            updated_blocks: list[SSABasicBlock] = []
            function_removed_phis = 0
            function_rewritten_uses = 0

            for block in function.blocks:
                instructions: list[SSAInstruction] = []
                block_changed = False

                for instruction in block.instructions:
                    if (
                        isinstance(instruction, SSAPhi)
                        and instruction.result in replacements
                    ):
                        function_removed_phis += 1
                        block_changed = True
                        continue

                    rewritten, instruction_rewritten_uses = self._rewrite_instruction(
                        instruction,
                        replacements,
                    )
                    function_rewritten_uses += instruction_rewritten_uses
                    if rewritten is not instruction:
                        block_changed = True
                    instructions.append(rewritten)

                if block_changed:
                    updated_blocks.append(SSABasicBlock(block.name, instructions))
                else:
                    updated_blocks.append(block)

            updated_functions.append(
                SSAFunction(
                    function.name,
                    list(function.parameters),
                    function.return_type,
                    updated_blocks,
                    function.entry_block,
                )
            )
            removed_trivial_phis += function_removed_phis
            rewritten_uses += function_rewritten_uses

        changed = removed_trivial_phis > 0 or rewritten_uses > 0
        if not changed:
            return SSAOptimizationResult(
                module,
                changed=False,
                stats={
                    "removed_trivial_phis": 0,
                    "rewritten_uses": 0,
                },
            )

        return SSAOptimizationResult(
            SSAModule(updated_functions),
            changed=True,
            stats={
                "removed_trivial_phis": removed_trivial_phis,
                "rewritten_uses": rewritten_uses,
            },
        )

    def _collect_replacements(self, function: SSAFunction) -> dict[SSAValue, SSAValue]:
        candidates: dict[SSAValue, SSAValue] = {}
        for block in function.blocks:
            for instruction in block.instructions:
                if not isinstance(instruction, SSAPhi):
                    continue
                common_value = self._trivial_common_value(instruction)
                if common_value is not None:
                    candidates[instruction.result] = common_value

        replacements: dict[SSAValue, SSAValue] = {}
        for result, replacement in candidates.items():
            resolved = self._resolve_candidate_replacement(
                replacement,
                candidates,
                seen={result},
            )
            if resolved is not None and resolved != result:
                replacements[result] = resolved
        return replacements

    def _trivial_common_value(self, instruction: SSAPhi) -> SSAValue | None:
        if not instruction.incoming:
            return None

        first_value = instruction.incoming[0][1]
        if first_value == instruction.result:
            return None

        for _block_name, value in instruction.incoming[1:]:
            if value == instruction.result or value != first_value:
                return None

        return first_value

    def _resolve_candidate_replacement(
        self,
        value: SSAValue,
        candidates: dict[SSAValue, SSAValue],
        *,
        seen: set[SSAValue],
    ) -> SSAValue | None:
        current = value
        while current in candidates:
            if current in seen:
                return None
            seen.add(current)
            current = candidates[current]
        return current

    def _rewrite_instruction(
        self,
        instruction: SSAInstruction,
        replacements: dict[SSAValue, SSAValue],
    ) -> tuple[SSAInstruction, int]:
        if isinstance(instruction, SSAConst):
            return instruction, 0

        if isinstance(instruction, SSABinaryOp):
            left, left_rewritten = self._rewrite_value(instruction.left, replacements)
            right, right_rewritten = self._rewrite_value(instruction.right, replacements)
            if not left_rewritten and not right_rewritten:
                return instruction, 0
            return (
                SSABinaryOp(instruction.result, instruction.operator, left, right),
                int(left_rewritten) + int(right_rewritten),
            )

        if isinstance(instruction, SSACompareOp):
            left, left_rewritten = self._rewrite_value(instruction.left, replacements)
            right, right_rewritten = self._rewrite_value(instruction.right, replacements)
            if not left_rewritten and not right_rewritten:
                return instruction, 0
            return (
                SSACompareOp(instruction.result, instruction.operator, left, right),
                int(left_rewritten) + int(right_rewritten),
            )

        if isinstance(instruction, SSACast):
            value, rewritten = self._rewrite_value(instruction.value, replacements)
            if not rewritten:
                return instruction, 0
            return SSACast(instruction.result, value), 1

        if isinstance(instruction, SSACall):
            arguments = []
            rewritten_uses = 0
            for argument in instruction.arguments:
                rewritten_argument, rewritten = self._rewrite_value(
                    argument,
                    replacements,
                )
                arguments.append(rewritten_argument)
                rewritten_uses += int(rewritten)
            if rewritten_uses == 0:
                return instruction, 0
            return (
                SSACall(
                    instruction.function,
                    tuple(arguments),
                    instruction.result,
                ),
                rewritten_uses,
            )

        if isinstance(instruction, SSAArrayNew):
            elements = []
            rewritten_uses = 0
            for element in instruction.elements:
                rewritten_element, rewritten = self._rewrite_value(element, replacements)
                elements.append(rewritten_element)
                rewritten_uses += int(rewritten)
            if rewritten_uses == 0:
                return instruction, 0
            return SSAArrayNew(instruction.result, tuple(elements)), rewritten_uses

        if isinstance(instruction, SSAArrayGet):
            array, array_rewritten = self._rewrite_value(instruction.array, replacements)
            index, index_rewritten = self._rewrite_value(instruction.index, replacements)
            if not array_rewritten and not index_rewritten:
                return instruction, 0
            return (
                SSAArrayGet(instruction.result, array, index),
                int(array_rewritten) + int(index_rewritten),
            )

        if isinstance(instruction, SSAArraySet):
            array, array_rewritten = self._rewrite_value(instruction.array, replacements)
            index, index_rewritten = self._rewrite_value(instruction.index, replacements)
            value, value_rewritten = self._rewrite_value(instruction.value, replacements)
            if not array_rewritten and not index_rewritten and not value_rewritten:
                return instruction, 0
            return (
                SSAArraySet(array, index, value),
                int(array_rewritten) + int(index_rewritten) + int(value_rewritten),
            )

        if isinstance(instruction, SSAArrayLength):
            array, rewritten = self._rewrite_value(instruction.array, replacements)
            if not rewritten:
                return instruction, 0
            return SSAArrayLength(instruction.result, array), 1

        if isinstance(instruction, SSAPhi):
            incoming = []
            rewritten_uses = 0
            for block_name, value in instruction.incoming:
                rewritten_value, rewritten = self._rewrite_value(value, replacements)
                incoming.append((block_name, rewritten_value))
                rewritten_uses += int(rewritten)
            if rewritten_uses == 0:
                return instruction, 0
            return SSAPhi(instruction.result, tuple(incoming)), rewritten_uses

        if isinstance(instruction, SSABranch):
            condition, rewritten = self._rewrite_value(
                instruction.condition,
                replacements,
            )
            if not rewritten:
                return instruction, 0
            return (
                SSABranch(
                    condition,
                    instruction.true_target,
                    instruction.false_target,
                ),
                1,
            )

        if isinstance(instruction, SSAJump):
            return instruction, 0

        if isinstance(instruction, SSAReturn):
            if instruction.value is None:
                return instruction, 0
            value, rewritten = self._rewrite_value(instruction.value, replacements)
            if not rewritten:
                return instruction, 0
            return SSAReturn(value), 1

        return instruction, 0

    def _rewrite_value(
        self,
        value: SSAValue,
        replacements: dict[SSAValue, SSAValue],
    ) -> tuple[SSAValue, bool]:
        replacement = replacements.get(value)
        if replacement is None:
            return value, False
        return replacement, True
