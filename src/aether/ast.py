from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from .types import AetherType

Visibility = str | None


@dataclass(frozen=True)
class Program:
    statements: list["Statement"]
    package_name: str | None = None
    entry_point: str | None = None


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
    type_name: AetherType | None
    name: str
    initializer: Expression
    line: int = 1
    column: int = 1
    is_const: bool = False
    visibility: Visibility = None


@dataclass(frozen=True)
class AliasDeclaration:
    name: str
    target_type: AetherType
    line: int = 1
    column: int = 1
    visibility: Visibility = None


@dataclass(frozen=True)
class StructField:
    name: str
    type_name: AetherType
    line: int = 1
    column: int = 1
    visibility: Visibility = None


@dataclass(frozen=True)
class StructDeclaration:
    name: str
    fields: list[StructField]
    line: int = 1
    column: int = 1
    visibility: Visibility = None
    methods: list["FunctionDeclaration"] = field(default_factory=list)
    implements: list[str] = field(default_factory=list)
    constructor: "ConstructorDeclaration | None" = None


@dataclass(frozen=True)
class ConstructorDeclaration:
    parameters: list[Parameter]
    body: list["Statement"]
    visibility: Visibility = None
    line: int = 1
    column: int = 1


@dataclass(frozen=True)
class ClassDeclaration:
    name: str
    fields: list[StructField]
    line: int = 1
    column: int = 1
    visibility: Visibility = None
    methods: list["FunctionDeclaration"] = field(default_factory=list)
    implements: list[str] = field(default_factory=list)
    constructor: ConstructorDeclaration | None = None


@dataclass(frozen=True)
class InterfaceMethodSignature:
    return_type: AetherType
    name: str
    parameters: list[Parameter]
    line: int = 1
    column: int = 1


@dataclass(frozen=True)
class InterfaceDeclaration:
    name: str
    methods: list[InterfaceMethodSignature]
    line: int = 1
    column: int = 1
    visibility: Visibility = None


@dataclass(frozen=True)
class EnumVariant:
    name: str
    line: int = 1
    column: int = 1


@dataclass(frozen=True)
class EnumDeclaration:
    name: str
    variants: list[EnumVariant]
    line: int = 1
    column: int = 1
    visibility: Visibility = None


@dataclass(frozen=True)
class Assignment:
    name: str | Expression
    expression: Expression
    line: int = 1
    column: int = 1


@dataclass(frozen=True)
class DestructuringAssignment:
    names: list[str]
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
class FieldAssignment:
    target: Expression
    field_name: str
    expression: Expression
    line: int = 1
    column: int = 1


@dataclass(frozen=True)
class ExpressionStatement:
    expression: Expression


@dataclass(frozen=True)
class ImportStatement:
    module_name: str
    line: int = 1
    column: int = 1


@dataclass(frozen=True)
class IfStatement:
    condition: Expression
    body: list[Statement]
    else_body: list[Statement] | None = None
    line: int = 1
    column: int = 1


@dataclass(frozen=True)
class WhileStatement:
    condition: Expression
    body: list[Statement]
    line: int = 1
    column: int = 1


@dataclass(frozen=True)
class ForInStatement:
    variable: str
    iterable: Expression
    body: list[Statement]
    line: int = 1
    column: int = 1
    variable_type: AetherType | None = None


@dataclass(frozen=True)
class FunctionDeclaration:
    return_type: AetherType
    name: str
    parameters: list[Parameter]
    body: list[Statement]
    visibility: Visibility = None
    line: int = 1
    column: int = 1
    synthetic: bool = False


@dataclass(frozen=True)
class ExpressionFunctionDeclaration:
    name: str
    parameters: list[ExpressionParameter]
    expression: Expression
    visibility: Visibility = None
    line: int = 1
    column: int = 1


@dataclass(frozen=True)
class ReturnStatement:
    expression: Expression | None = None
    line: int = 1
    column: int = 1


@dataclass(frozen=True)
class BreakStatement:
    line: int = 1
    column: int = 1


@dataclass(frozen=True)
class ContinueStatement:
    line: int = 1
    column: int = 1


@dataclass(frozen=True)
class ThrowStatement:
    expression: Expression
    line: int = 1
    column: int = 1


@dataclass(frozen=True)
class TryCatchStatement:
    try_body: list[Statement]
    catch_name: str
    catch_body: list[Statement]
    line: int = 1
    column: int = 1


@dataclass(frozen=True)
class Literal:
    value: object
    type_name: AetherType


@dataclass(frozen=True)
class InterpolatedString:
    parts: list[str | Expression]
    line: int = 1
    column: int = 1


@dataclass(frozen=True)
class Identifier:
    name: str
    line: int = 1
    column: int = 1


@dataclass(frozen=True)
class UnaryExpression:
    operator: str
    operand: Expression
    line: int = 1
    column: int = 1


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
    line: int = 1
    column: int = 1


@dataclass(frozen=True)
class MethodCall:
    target: Expression
    method_name: str
    arguments: list[Expression]
    keyword_arguments: dict[str, Expression] = field(default_factory=dict)
    line: int = 1
    column: int = 1


@dataclass(frozen=True)
class InputCall:
    arguments: list[Expression]
    line: int = 1
    column: int = 1


@dataclass(frozen=True)
class ArrayLiteral:
    elements: list[Expression]


@dataclass(frozen=True)
class ListLiteral:
    elements: list[Expression]


@dataclass(frozen=True)
class TupleLiteral:
    elements: list[Expression]


@dataclass(frozen=True)
class MatrixLiteral:
    rows: list[list[Expression]]
    vector: bool = False
    orientation: str | None = None
    uses_commas: bool = False


@dataclass(frozen=True)
class IndexExpression:
    array: Expression
    index: Expression
    line: int = 1
    column: int = 1


@dataclass(frozen=True)
class SliceExpression:
    collection: Expression
    start: Expression
    end: Expression
    line: int = 1
    column: int = 1


@dataclass(frozen=True)
class MatrixIndexExpression:
    matrix: Expression
    row: Expression
    column: Expression
    line: int = 1
    column_position: int = 1


@dataclass(frozen=True)
class FieldAccess:
    target: Expression
    field_name: str
    line: int = 1
    column: int = 1
