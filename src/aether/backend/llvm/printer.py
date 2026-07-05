from __future__ import annotations

import re
from typing import Any

from aether.ir.types import BoolType, IntType, VoidType
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
    SSAParameter,
    SSAPhi,
    SSAReturn,
    SSAValue,
)

from .types import LLVMBackendError, llvm_type


class LLVMPrinter:
    """Emit textual LLVM IR for the first minimal SSA subset."""

    _BINARY_OPERATORS = {
        "add": "add",
        "sub": "sub",
        "mul": "mul",
        "div": "sdiv",
        "mod": "srem",
        "rem": "srem",
    }
    _COMPARE_OPERATORS = {
        "lt": "slt",
        "le": "sle",
        "gt": "sgt",
        "ge": "sge",
        "eq": "eq",
        "ne": "ne",
    }
    _IDENTIFIER_RE = re.compile(r"^[A-Za-z_$._][A-Za-z0-9_$._-]*$")

    def print_module(self, module: SSAModule) -> str:
        return "\n\n".join(self._print_function(function) for function in module.functions)

    def _print_function(self, function: SSAFunction) -> str:
        self._constants: dict[str, str] = {}
        self._values: dict[str, str] = {
            self._key(parameter): self._parameter_name(parameter)
            for parameter in function.parameters
        }
        self._next_temp = 0

        return_type = llvm_type(function.return_type)
        parameters = ", ".join(
            f"{llvm_type(parameter.type)} {self._parameter_name(parameter)}"
            for parameter in function.parameters
        )
        lines = [f"define {return_type} {self._global_name(function.name)}({parameters}) {{"]

        for block in function.blocks:
            lines.extend(self._print_block(block, function))

        lines.append("}")
        return "\n".join(lines)

    def _print_block(self, block: SSABasicBlock, function: SSAFunction) -> list[str]:
        lines = [self._label_definition(block.name)]
        for instruction in block.instructions:
            emitted = self._print_instruction(instruction, function)
            if emitted is not None:
                lines.append(f"  {emitted}")
        return lines

    def _print_instruction(
        self,
        instruction: SSAInstruction,
        function: SSAFunction,
    ) -> str | None:
        if isinstance(instruction, SSAConst):
            self._record_const(instruction)
            return None
        if isinstance(instruction, SSABinaryOp):
            return self._print_binary_op(instruction)
        if isinstance(instruction, SSACompareOp):
            return self._print_compare_op(instruction)
        if isinstance(instruction, SSAReturn):
            return self._print_return(instruction, function)
        if isinstance(instruction, SSAPhi):
            self._unsupported("phi")
        if isinstance(instruction, SSABranch):
            return self._print_branch(instruction)
        if isinstance(instruction, SSAJump):
            return self._print_jump(instruction)
        if isinstance(instruction, SSACall):
            self._unsupported("call")
        self._unsupported(type(instruction).__name__)

    def _record_const(self, instruction: SSAConst) -> None:
        llvm_type(instruction.result.type)
        self._constants[self._key(instruction.result)] = self._literal(
            instruction.value,
            instruction.result,
        )

    def _print_binary_op(self, instruction: SSABinaryOp) -> str:
        operator = self._BINARY_OPERATORS.get(instruction.operator)
        if operator is None:
            raise LLVMBackendError(
                f"LLVM backend does not support binary operator '{instruction.operator}'"
            )
        if not (
            isinstance(instruction.result.type, IntType)
            and isinstance(instruction.left.type, IntType)
            and isinstance(instruction.right.type, IntType)
        ):
            raise LLVMBackendError(
                "LLVM backend does not support non-int binary operations"
            )

        result = self._new_temp(instruction.result)
        left = self._operand(instruction.left)
        right = self._operand(instruction.right)
        return f"{result} = {operator} i32 {left}, {right}"

    def _print_compare_op(self, instruction: SSACompareOp) -> str:
        predicate = self._COMPARE_OPERATORS.get(instruction.operator)
        if predicate is None:
            raise LLVMBackendError(
                f"LLVM backend does not support compare operator '{instruction.operator}'"
            )
        if not (
            isinstance(instruction.result.type, BoolType)
            and isinstance(instruction.left.type, IntType)
            and isinstance(instruction.right.type, IntType)
        ):
            raise LLVMBackendError(
                "LLVM backend only supports i32 integer comparisons producing i1"
            )

        result = self._new_temp(instruction.result)
        left = self._operand(instruction.left)
        right = self._operand(instruction.right)
        return f"{result} = icmp {predicate} i32 {left}, {right}"

    def _print_return(self, instruction: SSAReturn, function: SSAFunction) -> str:
        if instruction.value is None:
            if not isinstance(function.return_type, VoidType):
                raise LLVMBackendError(
                    "LLVM backend does not support empty return from non-void function"
                )
            return "ret void"

        if isinstance(function.return_type, VoidType):
            raise LLVMBackendError(
                "LLVM backend does not support value return from void function"
            )

        return_type = llvm_type(function.return_type)
        value_type = llvm_type(instruction.value.type)
        if value_type != return_type:
            raise LLVMBackendError(
                "LLVM backend does not support return type mismatches"
            )
        return f"ret {return_type} {self._operand(instruction.value)}"

    def _print_branch(self, instruction: SSABranch) -> str:
        if not isinstance(instruction.condition.type, BoolType):
            raise LLVMBackendError(
                "LLVM backend only supports bool/i1 branch conditions"
            )

        condition = self._operand(instruction.condition)
        true_target = self._label_operand(instruction.true_target)
        false_target = self._label_operand(instruction.false_target)
        return f"br i1 {condition}, {true_target}, {false_target}"

    def _print_jump(self, instruction: SSAJump) -> str:
        return f"br {self._label_operand(instruction.target)}"

    def _operand(self, value: SSAValue) -> str:
        key = self._key(value)
        if key in self._constants:
            return self._constants[key]
        if key in self._values:
            return self._values[key]
        return self._local_name(value.name)

    def _new_temp(self, value: SSAValue) -> str:
        name = f"%{self._next_temp}"
        self._next_temp += 1
        self._values[self._key(value)] = name
        return name

    def _literal(self, value: Any, result: SSAValue) -> str:
        if isinstance(result.type, IntType):
            if isinstance(value, bool) or not isinstance(value, int):
                raise LLVMBackendError(
                    "LLVM backend does not support non-int SSAConst values"
                )
            return str(value)
        if isinstance(result.type, BoolType):
            if not isinstance(value, bool):
                raise LLVMBackendError(
                    "LLVM backend does not support non-bool SSAConst values"
                )
            return "1" if value else "0"
        raise LLVMBackendError(
            f"LLVM backend does not support SSAConst of type {result.type}"
        )

    @classmethod
    def _parameter_name(cls, parameter: SSAParameter) -> str:
        raw = cls._strip_percent(parameter.name)
        if raw.isdigit():
            return f"%arg{raw}"
        return cls._local_name(raw)

    @classmethod
    def _local_name(cls, name: str) -> str:
        raw = cls._strip_percent(name)
        if not raw:
            raise LLVMBackendError("LLVM backend does not support empty SSA value names")
        if cls._IDENTIFIER_RE.match(raw) or raw.isdigit():
            return f"%{raw}"
        raise LLVMBackendError(f"LLVM backend does not support SSA value name '{name}'")

    @classmethod
    def _label_operand(cls, name: str) -> str:
        raw = cls._strip_percent(name)
        if not raw:
            raise LLVMBackendError("LLVM backend does not support empty block labels")
        if cls._IDENTIFIER_RE.match(raw) or raw.isdigit():
            return f"label %{raw}"
        raise LLVMBackendError(f"LLVM backend does not support block label '{name}'")

    @classmethod
    def _label_definition(cls, name: str) -> str:
        raw = cls._strip_percent(name)
        if not raw:
            raise LLVMBackendError("LLVM backend does not support empty block labels")
        if cls._IDENTIFIER_RE.match(raw) or raw.isdigit():
            return f"{raw}:"
        raise LLVMBackendError(f"LLVM backend does not support block label '{name}'")

    @staticmethod
    def _global_name(name: str) -> str:
        raw = name[1:] if name.startswith("@") else name
        if not raw:
            raise LLVMBackendError("LLVM backend does not support empty function names")
        return f"@{raw}"

    @staticmethod
    def _strip_percent(name: str) -> str:
        return name[1:] if name.startswith("%") else name

    @staticmethod
    def _key(value: SSAValue) -> str:
        return value.name[1:] if value.name.startswith("%") else value.name

    @staticmethod
    def _unsupported(feature: str) -> None:
        raise LLVMBackendError(f"LLVM backend does not support {feature}")


def print_llvm(module: SSAModule) -> str:
    return LLVMPrinter().print_module(module)
