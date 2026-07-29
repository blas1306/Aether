from __future__ import annotations

from typing import Any

from aether.ir.types import IntType
from aether.ssa.model import (
    SSABasicBlock,
    SSABinaryOp,
    SSACast,
    SSAConst,
    SSAFunction,
    SSAInstruction,
    SSAModule,
    SSAValue,
)
from aether.ssa.operands import rewrite_instruction_operands

from .result import SSAOptimizationResult


class SSAAlgebraicSimplifier:
    """Apply local integer identities and rewrite all resulting SSA uses."""

    def run(self, module: SSAModule) -> SSAOptimizationResult:
        simplified = 0
        functions: list[SSAFunction] = []
        for function in module.functions:
            optimized, count = self._simplify_function(function)
            functions.append(optimized)
            simplified += count
        optimized_module = SSAModule(functions, list(module.structs))
        if optimized_module == module:
            optimized_module = module
        return SSAOptimizationResult(
            optimized_module,
            changed=optimized_module != module,
            stats={"simplified": simplified},
        )

    def _simplify_function(self, function: SSAFunction) -> tuple[SSAFunction, int]:
        constants = {
            instruction.result: instruction.value
            for block in function.blocks
            for instruction in block.instructions
            if isinstance(instruction, SSAConst)
        }
        replacements: dict[SSAValue, SSAValue] = {}
        blocks: list[SSABasicBlock] = []
        simplified_count = 0

        for block in function.blocks:
            instructions: list[SSAInstruction] = []
            for instruction in block.instructions:
                rewritten = self._rewrite_instruction(instruction, replacements)
                simplified, changed = self._simplify_instruction(
                    rewritten,
                    constants,
                    replacements,
                )
                simplified_count += int(changed)
                if simplified is None:
                    continue
                if isinstance(simplified, SSAConst):
                    constants[simplified.result] = simplified.value
                instructions.append(simplified)
            blocks.append(SSABasicBlock(block.name, instructions))

        blocks = [
            SSABasicBlock(
                block.name,
                [
                    self._rewrite_instruction(instruction, replacements)
                    for instruction in block.instructions
                ],
            )
            for block in blocks
        ]
        return (
            SSAFunction(
                function.name,
                list(function.parameters),
                function.return_type,
                blocks,
                function.entry_block,
            ),
            simplified_count,
        )

    def _simplify_instruction(
        self,
        instruction: SSAInstruction,
        constants: dict[SSAValue, Any],
        replacements: dict[SSAValue, SSAValue],
    ) -> tuple[SSAInstruction | None, bool]:
        if isinstance(instruction, SSACast) and instruction.result.type == instruction.value.type:
            replacements[instruction.result] = instruction.value
            return None, True
        if not isinstance(instruction, SSABinaryOp) or not self._is_integer(instruction):
            return instruction, False

        operator = instruction.operator
        left = instruction.left
        right = instruction.right
        if operator == "add":
            if self._is_constant(right, 0, constants, replacements):
                replacements[instruction.result] = left
                return None, True
            if self._is_constant(left, 0, constants, replacements):
                replacements[instruction.result] = right
                return None, True
        elif operator == "sub" and self._is_constant(
            right, 0, constants, replacements
        ):
            replacements[instruction.result] = left
            return None, True
        elif operator == "mul":
            if self._is_constant(left, 0, constants, replacements) or self._is_constant(
                right, 0, constants, replacements
            ):
                return SSAConst(instruction.result, 0), True
            if self._is_constant(right, 1, constants, replacements):
                replacements[instruction.result] = left
                return None, True
            if self._is_constant(left, 1, constants, replacements):
                replacements[instruction.result] = right
                return None, True
        elif (
            operator == "div"
            and instruction.result.type == left.type
            and self._is_constant(right, 1, constants, replacements)
        ):
            replacements[instruction.result] = left
            return None, True
        elif operator in {"mod", "rem"} and self._is_constant(
            right, 1, constants, replacements
        ):
            return SSAConst(instruction.result, 0), True
        elif operator == "pow":
            if self._is_constant(right, 0, constants, replacements):
                return SSAConst(instruction.result, 1), True
            if self._is_constant(right, 1, constants, replacements):
                replacements[instruction.result] = left
                return None, True
        return instruction, False

    @staticmethod
    def _is_integer(instruction: SSABinaryOp) -> bool:
        return all(
            isinstance(value.type, IntType)
            for value in (instruction.result, instruction.left, instruction.right)
        )

    def _is_constant(
        self,
        value: SSAValue,
        expected: int,
        constants: dict[SSAValue, Any],
        replacements: dict[SSAValue, SSAValue],
    ) -> bool:
        resolved = self._resolve(value, replacements)
        constant = constants.get(resolved)
        return isinstance(resolved.type, IntType) and type(constant) is int and constant == expected

    def _rewrite_instruction(
        self,
        instruction: SSAInstruction,
        replacements: dict[SSAValue, SSAValue],
    ) -> SSAInstruction:
        rewritten, _count = rewrite_instruction_operands(
            instruction,
            lambda value: self._resolve(value, replacements),
        )
        return rewritten

    @staticmethod
    def _resolve(
        value: SSAValue,
        replacements: dict[SSAValue, SSAValue],
    ) -> SSAValue:
        resolved = value
        seen: set[SSAValue] = set()
        while resolved in replacements and resolved not in seen:
            seen.add(resolved)
            resolved = replacements[resolved]
        return resolved
