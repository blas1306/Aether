from __future__ import annotations

from dataclasses import dataclass, field
from math import trunc
from typing import Any, NoReturn, Sequence

from .model import (
    IRBinaryOp,
    IRCall,
    IRConst,
    IRFunction,
    IRInstruction,
    IRLoad,
    IRModule,
    IRReturn,
    IRStore,
    IRValue,
)
from .types import VoidType


class IRExecutionError(RuntimeError):
    """Raised when the minimal IR interpreter cannot execute validly."""


@dataclass
class _Frame:
    values: dict[IRValue, Any] = field(default_factory=dict)
    slots: dict[IRValue, Any] = field(default_factory=dict)


class IRInterpreter:
    """Execute the initial single-block Aether IR subset."""

    def __init__(self, module: IRModule) -> None:
        self.module = module
        self._functions = {function.name: function for function in module.functions}

    def call(self, function_name: str, arguments: Sequence[Any] = ()) -> Any:
        """Call an IR function by name using raw Python scalar values."""
        function = self._functions.get(function_name)
        if function is None:
            raise IRExecutionError(f"IR function '{function_name}' does not exist")

        if len(arguments) != len(function.parameters):
            raise IRExecutionError(
                f"IR function '{function_name}' expects {len(function.parameters)} "
                f"arguments, got {len(arguments)}"
            )

        frame = _Frame(
            values=dict(zip(function.parameters, arguments)),
        )
        return self._execute(function, frame)

    def _execute(self, function: IRFunction, frame: _Frame) -> Any:
        entry = next((block for block in function.blocks if block.name == "entry"), None)
        if entry is None:
            raise IRExecutionError(f"IR function '{function.name}' has no entry block")

        for instruction in entry.instructions:
            returned, value = self._execute_instruction(instruction, frame)
            if returned:
                if value is None and not isinstance(function.return_type, VoidType):
                    raise IRExecutionError(
                        f"IR function '{function.name}' returned void but is non-void"
                    )
                return value

        if isinstance(function.return_type, VoidType):
            return None
        raise IRExecutionError(
            f"IR function '{function.name}' ended without return"
        )

    def _execute_instruction(
        self,
        instruction: IRInstruction,
        frame: _Frame,
    ) -> tuple[bool, Any]:
        if isinstance(instruction, IRConst):
            frame.values[instruction.result] = instruction.value
            return False, None

        if isinstance(instruction, IRLoad):
            if instruction.slot not in frame.slots:
                raise IRExecutionError(
                    f"IR slot '%{instruction.slot.name}' is not initialized"
                )
            frame.values[instruction.result] = frame.slots[instruction.slot]
            return False, None

        if isinstance(instruction, IRStore):
            frame.slots[instruction.slot] = self._value(instruction.value, frame)
            return False, None

        if isinstance(instruction, IRBinaryOp):
            left = self._value(instruction.left, frame)
            right = self._value(instruction.right, frame)
            frame.values[instruction.result] = self._binary(
                instruction.operator,
                left,
                right,
            )
            return False, None

        if isinstance(instruction, IRCall):
            arguments = [
                self._value(argument, frame) for argument in instruction.arguments
            ]
            result = self.call(instruction.function, arguments)
            if instruction.result is not None:
                frame.values[instruction.result] = result
            return False, None

        if isinstance(instruction, IRReturn):
            value = (
                None
                if instruction.value is None
                else self._value(instruction.value, frame)
            )
            return True, value

        raise IRExecutionError(
            f"IR instruction '{type(instruction).__name__}' is not supported"
        )

    @staticmethod
    def _value(value: IRValue, frame: _Frame) -> Any:
        if value not in frame.values:
            raise IRExecutionError(f"IR value '%{value.name}' is not initialized")
        return frame.values[value]

    @staticmethod
    def _binary(operator: str, left: Any, right: Any) -> Any:
        if operator == "add":
            return left + right
        if operator == "sub":
            return left - right
        if operator == "mul":
            return left * right
        if operator == "div":
            if right == 0:
                raise IRExecutionError("IR division by zero")
            return left / right
        if operator in {"mod", "rem"}:
            if right == 0:
                raise IRExecutionError("IR division by zero")
            return left - trunc(left / right) * right
        IRInterpreter._unsupported_binary(operator)

    @staticmethod
    def _unsupported_binary(operator: str) -> NoReturn:
        raise IRExecutionError(f"IR binary operation '{operator}' is not supported")
