from __future__ import annotations

from dataclasses import replace
from typing import Any

from aether.ir.model import (
    IRBasicBlock,
    IRBinaryOp,
    IRBranch,
    IRCall,
    IRCompareOp,
    IRConst,
    IRFunction,
    IRInstruction,
    IRLoad,
    IRModule,
    IRReturn,
    IRStore,
    IRValue,
)
from aether.ir.types import IntType


class AlgebraicSimplifier:
    """Apply local integer algebraic identities to IR binary operations."""

    def run(self, module: IRModule) -> IRModule:
        functions = [self._simplify_function(function) for function in module.functions]
        return IRModule(functions)

    def _simplify_function(self, function: IRFunction) -> IRFunction:
        constants = self._collect_constants(function)
        replacements: dict[str, IRValue] = {}
        blocks: list[IRBasicBlock] = []

        for block in function.blocks:
            instructions: list[IRInstruction] = []
            for instruction in block.instructions:
                rewritten = self._rewrite_instruction(instruction, replacements)
                simplified = self._simplify_instruction(
                    rewritten,
                    constants,
                    replacements,
                )
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

        return IRFunction(
            function.name,
            list(function.parameters),
            function.return_type,
            blocks,
        )

    @staticmethod
    def _collect_constants(function: IRFunction) -> dict[str, Any]:
        constants: dict[str, Any] = {}
        for block in function.blocks:
            for instruction in block.instructions:
                if isinstance(instruction, IRConst):
                    constants[instruction.result.name] = instruction.value
        return constants

    def _simplify_instruction(
        self,
        instruction: IRInstruction,
        constants: dict[str, Any],
        replacements: dict[str, IRValue],
    ) -> IRInstruction | None:
        if not isinstance(instruction, IRBinaryOp):
            return instruction
        if not self._is_integer_operation(instruction):
            return instruction

        operator = instruction.operator
        left = instruction.left
        right = instruction.right

        if operator == "add":
            if self._is_zero(right, constants, replacements):
                replacements[instruction.result.name] = left
                return None
            if self._is_zero(left, constants, replacements):
                replacements[instruction.result.name] = right
                return None

        if operator == "sub":
            if self._is_zero(right, constants, replacements):
                replacements[instruction.result.name] = left
                return None

        if operator == "mul":
            if self._is_zero(left, constants, replacements) or self._is_zero(
                right,
                constants,
                replacements,
            ):
                return IRConst(instruction.result, 0)
            if self._is_one(right, constants, replacements):
                replacements[instruction.result.name] = left
                return None
            if self._is_one(left, constants, replacements):
                replacements[instruction.result.name] = right
                return None

        if operator == "div":
            if (
                instruction.result.type == left.type
                and self._is_one(right, constants, replacements)
            ):
                replacements[instruction.result.name] = left
                return None

        if operator in {"mod", "rem"}:
            if self._is_one(right, constants, replacements):
                return IRConst(instruction.result, 0)

        return instruction

    @staticmethod
    def _is_integer_operation(instruction: IRBinaryOp) -> bool:
        return (
            isinstance(instruction.result.type, IntType)
            and isinstance(instruction.left.type, IntType)
            and isinstance(instruction.right.type, IntType)
        )

    def _is_zero(
        self,
        value: IRValue,
        constants: dict[str, Any],
        replacements: dict[str, IRValue],
    ) -> bool:
        return self._integer_constant(value, constants, replacements) == 0

    def _is_one(
        self,
        value: IRValue,
        constants: dict[str, Any],
        replacements: dict[str, IRValue],
    ) -> bool:
        return self._integer_constant(value, constants, replacements) == 1

    def _integer_constant(
        self,
        value: IRValue,
        constants: dict[str, Any],
        replacements: dict[str, IRValue],
    ) -> int | None:
        resolved = self._resolve(value, replacements)
        if not isinstance(resolved.type, IntType):
            return None
        constant = constants.get(resolved.name)
        if type(constant) is int:
            return constant
        return None

    def _rewrite_instruction(
        self,
        instruction: IRInstruction,
        replacements: dict[str, IRValue],
    ) -> IRInstruction:
        if isinstance(instruction, (IRConst, IRLoad)):
            return instruction
        if isinstance(instruction, IRStore):
            return replace(instruction, value=self._resolve(instruction.value, replacements))
        if isinstance(instruction, IRBinaryOp):
            return replace(
                instruction,
                left=self._resolve(instruction.left, replacements),
                right=self._resolve(instruction.right, replacements),
            )
        if isinstance(instruction, IRCompareOp):
            return replace(
                instruction,
                left=self._resolve(instruction.left, replacements),
                right=self._resolve(instruction.right, replacements),
            )
        if isinstance(instruction, IRCall):
            return replace(
                instruction,
                arguments=tuple(
                    self._resolve(argument, replacements)
                    for argument in instruction.arguments
                ),
            )
        if isinstance(instruction, IRBranch):
            return replace(
                instruction,
                condition=self._resolve(instruction.condition, replacements),
            )
        if isinstance(instruction, IRReturn):
            if instruction.value is None:
                return instruction
            return replace(
                instruction,
                value=self._resolve(instruction.value, replacements),
            )
        return instruction

    def _resolve(
        self,
        value: IRValue,
        replacements: dict[str, IRValue],
    ) -> IRValue:
        resolved = value
        seen: set[str] = set()
        while resolved.name in replacements and resolved.name not in seen:
            seen.add(resolved.name)
            resolved = replacements[resolved.name]
        return resolved
