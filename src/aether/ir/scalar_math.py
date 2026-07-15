from __future__ import annotations

from .types import ComplexType, DoubleType, FloatType, IntType, IRType


REAL_TYPES = (IntType, FloatType, DoubleType)
NUMERIC_TYPES = (IntType, FloatType, DoubleType, ComplexType)


def scalar_math_result_type(name: str, arguments: tuple[IRType, ...]) -> IRType:
    if name in {"sin", "cos", "tan", "exp", "ln", "log", "sqrt"}:
        if len(arguments) != 1 or not isinstance(arguments[0], REAL_TYPES):
            raise ValueError(f"builtin '{name}' expects one real numeric argument")
        return DoubleType()
    if name == "abs":
        if len(arguments) != 1 or not isinstance(arguments[0], NUMERIC_TYPES):
            raise ValueError("builtin 'abs' expects one numeric argument")
        return DoubleType() if isinstance(arguments[0], ComplexType) else arguments[0]
    if name in {"Math.floor", "Math.ceil"}:
        if len(arguments) != 1 or not isinstance(arguments[0], REAL_TYPES):
            raise ValueError(f"builtin '{name}' expects one real numeric argument")
        return IntType()
    if name == "Math.factorial":
        if len(arguments) != 1 or not isinstance(arguments[0], IntType):
            raise ValueError("builtin 'Math.factorial' expects one int argument")
        return IntType()
    if name == "Math.mod":
        if len(arguments) != 2 or not all(isinstance(type_, REAL_TYPES) for type_ in arguments):
            raise ValueError("builtin 'Math.mod' expects two real numeric arguments")
        if isinstance(arguments[0], DoubleType) or isinstance(arguments[1], DoubleType):
            return DoubleType()
        if isinstance(arguments[0], FloatType) or isinstance(arguments[1], FloatType):
            return FloatType()
        return IntType()
    raise ValueError(f"unknown scalar math builtin '{name}'")
