from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from .types import AetherType


@dataclass(frozen=True)
class Program:
    statements: list["Statement"]


class Statement(Protocol):
    pass


class Expression(Protocol):
    pass


@dataclass(frozen=True)
class Parameter:
    type_name: AetherType
    name: str


@dataclass(frozen=True)
class ExpressionParameter:
    name: str


@dataclass(frozen=True)
class VarDeclaration:
    type_name: AetherType
    name: str
    initializer: Expression
    line: int = 1
    column: int = 1


@dataclass(frozen=True)
class Assignment:
    name: str
    expression: Expression
    line: int = 1
    column: int = 1


@dataclass(frozen=True)
class IndexAssignment:
    array: Expression
    index: Expression
    expression: Expression
    line: int = 1
    column: int = 1


@dataclass(frozen=True)
class MatrixIndexAssignment:
    matrix: Expression
    row: Expression
    column_index: Expression
    expression: Expression
    line: int = 1
    column: int = 1


@dataclass(frozen=True)
class ExpressionStatement:
    expression: Expression


@dataclass(frozen=True)
class ImportStatement:
    module_name: str


@dataclass(frozen=True)
class IfStatement:
    condition: Expression
    body: list[Statement]
    else_body: list[Statement] | None = None


@dataclass(frozen=True)
class WhileStatement:
    condition: Expression
    body: list[Statement]


@dataclass(frozen=True)
class ForInStatement:
    variable: str
    iterable: Expression
    body: list[Statement]


@dataclass(frozen=True)
class FunctionDeclaration:
    return_type: AetherType
    name: str
    parameters: list[Parameter]
    body: list[Statement]


@dataclass(frozen=True)
class ExpressionFunctionDeclaration:
    name: str
    parameters: list[ExpressionParameter]
    expression: Expression


@dataclass(frozen=True)
class ReturnStatement:
    expression: Expression
    line: int = 1
    column: int = 1


@dataclass(frozen=True)
class Literal:
    value: object
    type_name: str


@dataclass(frozen=True)
class InterpolatedString:
    parts: list[str | Expression]
    line: int = 1
    column: int = 1


@dataclass(frozen=True)
class Identifier:
    name: str


@dataclass(frozen=True)
class UnaryExpression:
    operator: str
    operand: Expression


@dataclass(frozen=True)
class BinaryExpression:
    left: Expression
    operator: str
    right: Expression
    line: int = 1
    column: int = 1


@dataclass(frozen=True)
class RangeExpression:
    start: Expression
    end: Expression
    step: Expression | None = None


@dataclass(frozen=True)
class FullSlice:
    pass


@dataclass(frozen=True)
class CallExpression:
    callee: str
    arguments: list[Expression]
    keyword_arguments: dict[str, Expression] = field(default_factory=dict)


@dataclass(frozen=True)
class ArrayLiteral:
    elements: list[Expression]


@dataclass(frozen=True)
class MatrixLiteral:
    rows: list[list[Expression]]
    vector: bool = False


@dataclass(frozen=True)
class IndexExpression:
    array: Expression
    index: Expression


@dataclass(frozen=True)
class MatrixIndexExpression:
    matrix: Expression
    row: Expression
    column: Expression
