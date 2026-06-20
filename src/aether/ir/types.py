from __future__ import annotations

from dataclasses import dataclass


class IRType:
    """Base class for all Aether IR types."""

    def __str__(self) -> str:
        raise NotImplementedError


@dataclass(frozen=True)
class IntType(IRType):
    def __str__(self) -> str:
        return "int"


@dataclass(frozen=True)
class FloatType(IRType):
    def __str__(self) -> str:
        return "float"


@dataclass(frozen=True)
class DoubleType(IRType):
    def __str__(self) -> str:
        return "double"


@dataclass(frozen=True)
class BoolType(IRType):
    def __str__(self) -> str:
        return "bool"


@dataclass(frozen=True)
class StringType(IRType):
    def __str__(self) -> str:
        return "string"


@dataclass(frozen=True)
class VoidType(IRType):
    def __str__(self) -> str:
        return "void"


@dataclass(frozen=True)
class ComplexType(IRType):
    def __str__(self) -> str:
        return "complex"


@dataclass(frozen=True)
class NullableType(IRType):
    inner: IRType

    def __str__(self) -> str:
        return f"nullable<{self.inner}>"


@dataclass(frozen=True)
class ListType(IRType):
    element: IRType

    def __str__(self) -> str:
        return f"list<{self.element}>"


@dataclass(frozen=True)
class ArrayType(IRType):
    element: IRType

    def __str__(self) -> str:
        return f"array<{self.element}>"


@dataclass(frozen=True)
class VectorType(IRType):
    element: IRType

    def __str__(self) -> str:
        return f"vector<{self.element}>"


@dataclass(frozen=True)
class MatrixType(IRType):
    element: IRType

    def __str__(self) -> str:
        return f"matrix<{self.element}>"


@dataclass(frozen=True)
class StructType(IRType):
    name: str

    def __str__(self) -> str:
        return f"struct {self.name}"


@dataclass(frozen=True)
class ClassRefType(IRType):
    name: str

    def __str__(self) -> str:
        return f"class {self.name}"


@dataclass(frozen=True)
class InterfaceType(IRType):
    name: str

    def __str__(self) -> str:
        return f"interface {self.name}"


@dataclass(frozen=True)
class EnumType(IRType):
    name: str

    def __str__(self) -> str:
        return f"enum {self.name}"
