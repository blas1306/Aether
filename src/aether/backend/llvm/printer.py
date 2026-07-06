from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

from aether.ir.types import BoolType, DoubleType, IntType, StringType, VoidType
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
    SSAParameter,
    SSAPhi,
    SSAReturn,
    SSAValue,
)

from .types import LLVMBackendError, llvm_type


@dataclass(frozen=True)
class _StringGlobal:
    name: str
    size: int
    initializer: str


class LLVMPrinter:
    """Emit textual LLVM IR for the first minimal SSA subset."""

    _INT_BINARY_OPERATORS = {
        "add": "add",
        "sub": "sub",
        "mul": "mul",
        "div": "sdiv",
        "mod": "srem",
        "rem": "srem",
    }
    _DOUBLE_BINARY_OPERATORS = {
        "add": "fadd",
        "sub": "fsub",
        "mul": "fmul",
        "div": "fdiv",
    }
    _INT_COMPARE_OPERATORS = {
        "lt": "slt",
        "le": "sle",
        "gt": "sgt",
        "ge": "sge",
        "eq": "eq",
        "ne": "ne",
    }
    _DOUBLE_COMPARE_OPERATORS = {
        "lt": "olt",
        "le": "ole",
        "gt": "ogt",
        "ge": "oge",
        "eq": "oeq",
        "ne": "one",
    }
    _IDENTIFIER_RE = re.compile(r"^[A-Za-z_$._][A-Za-z0-9_$._-]*$")

    def print_module(self, module: SSAModule) -> str:
        self._string_globals_by_value: dict[str, _StringGlobal] = {}
        self._next_string_global = 0

        functions = [self._print_function(function) for function in module.functions]
        globals_ = [
            self._print_string_global(global_)
            for global_ in self._string_globals_by_value.values()
        ]
        sections = globals_ + functions
        return "\n\n".join(sections)

    def _print_function(self, function: SSAFunction) -> str:
        self._constants: dict[str, str] = {}
        self._values: dict[str, str] = {
            self._key(parameter): self._parameter_name(parameter)
            for parameter in function.parameters
        }
        self._next_temp = 0
        self._collect_function_values(function)

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

    def _collect_function_values(self, function: SSAFunction) -> None:
        for block in function.blocks:
            for instruction in block.instructions:
                if isinstance(instruction, SSAConst):
                    self._record_const(instruction)
                    continue

                result = self._instruction_result(instruction)
                if result is not None:
                    self._reserve_temp(result)

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
        if isinstance(instruction, SSACast):
            return self._print_cast(instruction)
        if isinstance(instruction, SSAReturn):
            return self._print_return(instruction, function)
        if isinstance(instruction, SSAPhi):
            return self._print_phi(instruction)
        if isinstance(instruction, SSABranch):
            return self._print_branch(instruction)
        if isinstance(instruction, SSAJump):
            return self._print_jump(instruction)
        if isinstance(instruction, SSACall):
            return self._print_call(instruction)
        self._unsupported(type(instruction).__name__)

    def _record_const(self, instruction: SSAConst) -> None:
        llvm_type(instruction.result.type)
        self._constants[self._key(instruction.result)] = self._literal(
            instruction.value,
            instruction.result,
        )

    @staticmethod
    def _instruction_result(instruction: SSAInstruction) -> SSAValue | None:
        if isinstance(instruction, SSABinaryOp | SSACompareOp | SSACast | SSAPhi):
            return instruction.result
        if isinstance(instruction, SSACall):
            return instruction.result
        return None

    def _print_binary_op(self, instruction: SSABinaryOp) -> str:
        if (
            isinstance(instruction.result.type, StringType)
            or isinstance(instruction.left.type, StringType)
            or isinstance(instruction.right.type, StringType)
        ):
            raise LLVMBackendError(
                "LLVM backend does not support string binary operations yet; "
                "only string literals as ptr values are supported"
            )

        if (
            isinstance(instruction.result.type, IntType)
            and isinstance(instruction.left.type, IntType)
            and isinstance(instruction.right.type, IntType)
        ):
            operator = self._INT_BINARY_OPERATORS.get(instruction.operator)
            result_type = "i32"
        elif (
            isinstance(instruction.result.type, DoubleType)
            and isinstance(instruction.left.type, DoubleType)
            and isinstance(instruction.right.type, DoubleType)
        ):
            operator = self._DOUBLE_BINARY_OPERATORS.get(instruction.operator)
            result_type = "double"
        else:
            raise LLVMBackendError(
                "LLVM backend only supports homogeneous i32 or double binary operations"
            )

        if operator is None:
            raise LLVMBackendError(
                f"LLVM backend does not support binary operator '{instruction.operator}'"
            )

        result = self._new_temp(instruction.result)
        left = self._operand(instruction.left)
        right = self._operand(instruction.right)
        return f"{result} = {operator} {result_type} {left}, {right}"

    def _print_compare_op(self, instruction: SSACompareOp) -> str:
        if (
            isinstance(instruction.left.type, StringType)
            or isinstance(instruction.right.type, StringType)
        ):
            raise LLVMBackendError(
                "LLVM backend does not support string comparisons yet; "
                "only string literals as ptr values are supported"
            )

        if (
            isinstance(instruction.result.type, BoolType)
            and isinstance(instruction.left.type, IntType)
            and isinstance(instruction.right.type, IntType)
        ):
            operation = "icmp"
            predicate = self._INT_COMPARE_OPERATORS.get(instruction.operator)
            operand_type = "i32"
        elif (
            isinstance(instruction.result.type, BoolType)
            and isinstance(instruction.left.type, DoubleType)
            and isinstance(instruction.right.type, DoubleType)
        ):
            operation = "fcmp"
            predicate = self._DOUBLE_COMPARE_OPERATORS.get(instruction.operator)
            operand_type = "double"
        else:
            raise LLVMBackendError(
                "LLVM backend only supports i32 or double comparisons producing i1"
            )

        if predicate is None:
            raise LLVMBackendError(
                f"LLVM backend does not support compare operator '{instruction.operator}'"
            )

        result = self._new_temp(instruction.result)
        left = self._operand(instruction.left)
        right = self._operand(instruction.right)
        return f"{result} = {operation} {predicate} {operand_type} {left}, {right}"

    def _print_cast(self, instruction: SSACast) -> str:
        if isinstance(instruction.value.type, IntType) and isinstance(
            instruction.result.type,
            DoubleType,
        ):
            operator = "sitofp"
        elif isinstance(instruction.value.type, DoubleType) and isinstance(
            instruction.result.type,
            IntType,
        ):
            operator = "fptosi"
        else:
            raise LLVMBackendError(
                "LLVM backend only supports casts from i32 to double "
                "or double to i32"
            )

        result = self._new_temp(instruction.result)
        source_type = llvm_type(instruction.value.type)
        target_type = llvm_type(instruction.result.type)
        value = self._operand(instruction.value)
        return f"{result} = {operator} {source_type} {value} to {target_type}"

    def _print_phi(self, instruction: SSAPhi) -> str:
        if not instruction.incoming:
            raise LLVMBackendError("LLVM backend does not support phi with no incoming values")

        result_type = llvm_type(instruction.result.type)
        result = self._new_temp(instruction.result)
        incoming = ", ".join(
            f"[ {self._operand(value)}, %{self._label_name(block)} ]"
            for block, value in instruction.incoming
        )
        return f"{result} = phi {result_type} {incoming}"

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

    def _print_call(self, instruction: SSACall) -> str:
        arguments = ", ".join(
            f"{llvm_type(argument.type)} {self._operand(argument)}"
            for argument in instruction.arguments
        )
        callee = self._global_name(instruction.function)
        if instruction.result is None:
            return f"call void {callee}({arguments})"

        return_type = llvm_type(instruction.result.type)
        if isinstance(instruction.result.type, VoidType):
            raise LLVMBackendError(
                "LLVM backend does not support assigning void call results"
            )
        result = self._new_temp(instruction.result)
        return f"{result} = call {return_type} {callee}({arguments})"

    def _operand(self, value: SSAValue) -> str:
        key = self._key(value)
        if key in self._constants:
            return self._constants[key]
        if key in self._values:
            return self._values[key]
        return self._local_name(value.name)

    def _new_temp(self, value: SSAValue) -> str:
        existing = self._values.get(self._key(value))
        if existing is not None:
            return existing
        return self._reserve_temp(value)

    def _reserve_temp(self, value: SSAValue) -> str:
        key = self._key(value)
        existing = self._values.get(key)
        if existing is not None:
            return existing
        name = f"%{self._next_temp}"
        self._next_temp += 1
        self._values[key] = name
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
        if isinstance(result.type, DoubleType):
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise LLVMBackendError(
                    "LLVM backend does not support non-double SSAConst values"
                )
            return self._double_literal(float(value))
        if isinstance(result.type, StringType):
            if not isinstance(value, str):
                raise LLVMBackendError(
                    "LLVM backend does not support non-string SSAConst values"
                )
            return self._string_global(value).name
        raise LLVMBackendError(
            f"LLVM backend does not support SSAConst of type {result.type}"
        )

    def _string_global(self, value: str) -> _StringGlobal:
        existing = self._string_globals_by_value.get(value)
        if existing is not None:
            return existing

        encoded = value.encode("utf-8") + b"\x00"
        global_ = _StringGlobal(
            name=f"@.str.{self._next_string_global}",
            size=len(encoded),
            initializer=self._escape_string_initializer(encoded),
        )
        self._next_string_global += 1
        self._string_globals_by_value[value] = global_
        return global_

    @staticmethod
    def _print_string_global(global_: _StringGlobal) -> str:
        return (
            f"{global_.name} = private unnamed_addr constant "
            f"[{global_.size} x i8] c\"{global_.initializer}\""
        )

    @staticmethod
    def _escape_string_initializer(value: bytes) -> str:
        chunks: list[str] = []
        for byte in value:
            if byte in {0x22, 0x5C} or byte < 0x20 or byte > 0x7E:
                chunks.append(f"\\{byte:02X}")
            else:
                chunks.append(chr(byte))
        return "".join(chunks)

    @staticmethod
    def _double_literal(value: float) -> str:
        literal = repr(value)
        if "e" in literal or "E" in literal:
            return format(value, ".17e")
        if "." not in literal:
            return f"{literal}.0"
        return literal

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

    @classmethod
    def _label_name(cls, name: str) -> str:
        raw = cls._strip_percent(name)
        if not raw:
            raise LLVMBackendError("LLVM backend does not support empty block labels")
        if cls._IDENTIFIER_RE.match(raw) or raw.isdigit():
            return raw
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
