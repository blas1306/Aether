from __future__ import annotations

from typing import Any

from aether.ir.model import (
    IRBasicBlock,
    IRBinaryOp,
    IRCast,
    IRConst,
    IRFunction,
    IRInstruction,
    IRModule,
    IRStorage,
    IRValue,
)
from aether.ir.operands import rewrite_instruction_operands
from aether.ir.types import IntType

from .result import OptimizationResult


class AlgebraicSimplifier:
    """Apply local integer identities and rewrite all resulting IR uses."""

    def run(self, module: IRModule) -> OptimizationResult:
        simplified = 0
        functions: list[IRFunction] = []
        for function in module.functions:
            optimized, count = self._simplify_function(function)
            functions.append(optimized)
            simplified += count
        optimized_module = IRModule(functions, list(module.structs))
        if optimized_module == module:
            optimized_module = module
        return OptimizationResult(
            optimized_module,
            changed=optimized_module != module,
            stats={"simplified": simplified},
        )

    def _simplify_function(self, function: IRFunction) -> tuple[IRFunction, int]:
        constants = {
            instruction.result.name: instruction.value
            for block in function.blocks
            for instruction in block.instructions
            if isinstance(instruction, IRConst)
        }
        replacements: dict[str, IRValue] = {}
        blocks: list[IRBasicBlock] = []
        simplified_count = 0

        for block in function.blocks:
            instructions: list[IRInstruction] = []
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
                if isinstance(simplified, IRConst):
                    constants[simplified.result.name] = simplified.value
                instructions.append(simplified)
            blocks.append(IRBasicBlock(block.name, instructions))

        blocks = [
            IRBasicBlock(
                block.name,
                [
                    self._rewrite_instruction(instruction, replacements)
                    for instruction in block.instructions
                ],
            )
            for block in blocks
        ]
        return (
            IRFunction(
                function.name,
                list(function.parameters),
                function.return_type,
                blocks,
                function.may_throw,
            ),
            simplified_count,
        )

    def _simplify_instruction(
        self,
        instruction: IRInstruction,
        constants: dict[str, Any],
        replacements: dict[str, IRValue],
    ) -> tuple[IRInstruction | None, bool]:
        if isinstance(instruction, IRCast) and instruction.result.type == instruction.value.type:
            replacements[instruction.result.name] = instruction.value
            return None, True
        if not isinstance(instruction, IRBinaryOp) or not self._is_integer(instruction):
            return instruction, False

        operator = instruction.operator
        left = instruction.left
        right = instruction.right
        if operator == "add":
            if self._is_constant(right, 0, constants, replacements):
                replacements[instruction.result.name] = left
                return None, True
            if self._is_constant(left, 0, constants, replacements):
                replacements[instruction.result.name] = right
                return None, True
        elif operator == "sub" and self._is_constant(
            right, 0, constants, replacements
        ):
            replacements[instruction.result.name] = left
            return None, True
        elif operator == "mul":
            if self._is_constant(left, 0, constants, replacements) or self._is_constant(
                right, 0, constants, replacements
            ):
                return IRConst(instruction.result, 0), True
            if self._is_constant(right, 1, constants, replacements):
                replacements[instruction.result.name] = left
                return None, True
            if self._is_constant(left, 1, constants, replacements):
                replacements[instruction.result.name] = right
                return None, True
        elif (
            operator == "div"
            and instruction.result.type == left.type
            and self._is_constant(right, 1, constants, replacements)
        ):
            replacements[instruction.result.name] = left
            return None, True
        elif operator in {"mod", "rem"} and self._is_constant(
            right, 1, constants, replacements
        ):
            return IRConst(instruction.result, 0), True
        elif operator == "pow":
            if self._is_constant(right, 0, constants, replacements):
                return IRConst(instruction.result, 1), True
            if self._is_constant(right, 1, constants, replacements):
                replacements[instruction.result.name] = left
                return None, True
        return instruction, False

    @staticmethod
    def _is_integer(instruction: IRBinaryOp) -> bool:
        return all(
            isinstance(value.type, IntType)
            for value in (instruction.result, instruction.left, instruction.right)
        )

    def _is_constant(
        self,
        value: IRValue,
        expected: int,
        constants: dict[str, Any],
        replacements: dict[str, IRValue],
    ) -> bool:
        resolved = self._resolve(value, replacements)
        constant = constants.get(resolved.name)
        return isinstance(resolved.type, IntType) and type(constant) is int and constant == expected

    def _rewrite_instruction(
        self,
        instruction: IRInstruction,
        replacements: dict[str, IRValue],
    ) -> IRInstruction:
        rewritten, _count = rewrite_instruction_operands(
            instruction,
            lambda value: (
                value
                if isinstance(value, IRStorage)
                else self._resolve(value, replacements)
            ),
        )
        return rewritten

    @staticmethod
    def _resolve(
        value: IRValue,
        replacements: dict[str, IRValue],
    ) -> IRValue:
        resolved = value
        seen: set[str] = set()
        while resolved.name in replacements and resolved.name not in seen:
            seen.add(resolved.name)
            resolved = replacements[resolved.name]
        return resolved
