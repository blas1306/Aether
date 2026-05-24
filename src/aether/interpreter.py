from __future__ import annotations

from dataclasses import dataclass
from math import trunc
import os
from pathlib import Path

from plot_backend import PlotBackend

from . import ast
from .errors import AetherRuntimeError, AetherTypeError
from .formatting import format_value
from .lexer import lex
from .parser import Parser
from .scope import Scope
from .stdlib import BuiltinFunction, is_builtin_namespace, make_builtins
from .stdlib.registry import builtin_aliases_for_import
from .types import (
    AetherType,
    AetherRange,
    AetherValue,
    ArrayType,
    MatrixType,
    NUMERIC_TYPES,
    RangeType,
    array_element_type,
    coerce_array_literal_value,
    coerce_implicit,
    coerce_matrix_value,
    is_array_type,
    is_indexable_type,
    is_matrix_type,
    matrix_row_type,
    promote_numeric,
    type_to_string,
)


LINEAR_ALGEBRA_MODULE = "Math.LinearAlgebra"
LINEAR_ALGEBRA_SOLVE = "Math.LinearAlgebra.solve"


@dataclass
class Function:
    declaration: ast.FunctionDeclaration | ast.ExpressionFunctionDeclaration


@dataclass
class Environment:
    parent: "Environment | None" = None
    variable_scope: Scope[AetherValue] | None = None

    def __post_init__(self) -> None:
        if self.variable_scope is None:
            parent_scope = self.parent.variable_scope if self.parent is not None else None
            self.variable_scope = Scope(parent=parent_scope)
        self.functions: dict[str, Function] = {}

    @property
    def values(self) -> dict[str, AetherValue]:
        return self.variable_scope.symbols

    def define(self, name: str, value: AetherValue, *, forbid_shadowing: bool = False) -> None:
        self.variable_scope.define_local(name, value, forbid_shadowing=forbid_shadowing)

    def assign(self, name: str, value: AetherValue, *, array_literal_context: bool = False) -> None:
        scope = self.variable_scope.resolve_scope(name)
        if scope is None:
            self.variable_scope.define_local(name, value)
            return
        current = scope.symbols[name]
        if array_literal_context:
            scope.symbols[name] = coerce_array_literal_value(value, current.type_name)
            return
        scope.symbols[name] = coerce_implicit(value, current.type_name)

    def get(self, name: str) -> AetherValue:
        return self.variable_scope.require(name)

    def lookup(self, name: str) -> AetherValue | None:
        return self.variable_scope.lookup(name)

    def define_function(self, function: Function) -> None:
        self.functions[function.declaration.name] = function

    def get_function(self, name: str) -> Function | None:
        if name in self.functions:
            return self.functions[name]
        if self.parent is not None:
            return self.parent.get_function(name)
        return None


class _ReturnSignal(Exception):
    def __init__(self, value: AetherValue) -> None:
        self.value = value


class Interpreter:
    def __init__(self, *, plot_mode: str | None = None, plot_output_dir: str | Path | None = None) -> None:
        self.global_env = Environment()
        self.output_parts: list[str] = []
        self.plot_backend = PlotBackend(
            plot_mode=_default_plot_mode(plot_mode),
            output_dir=_default_plot_output_dir(plot_output_dir),
        )
        self.builtins: dict[str, BuiltinFunction] = make_builtins(
            self.output_parts.append,
            plot_backend=self.plot_backend,
        )
        self.builtin_aliases: dict[str, str] = {}
        self.imported_modules: set[str] = set()

    def interpret(self, program: ast.Program) -> Environment:
        for statement in program.statements:
            self._execute(statement, self.global_env)
        return self.global_env

    @property
    def output(self) -> str:
        return "".join(self.output_parts)

    def clear_output(self) -> None:
        self.output_parts.clear()

    def _execute(self, statement: ast.Statement, env: Environment) -> None:
        if isinstance(statement, ast.VarDeclaration):
            if isinstance(statement.initializer, ast.MatrixLiteral):
                if not statement.initializer.rows and is_array_type(statement.type_name):
                    env.define(statement.name, AetherValue(statement.type_name, []), forbid_shadowing=True)
                    return
                value = self._evaluate_matrix_literal(
                    statement.initializer,
                    env,
                    statement.type_name if isinstance(statement.type_name, MatrixType) else None,
                )
                env.define(statement.name, coerce_implicit(value, statement.type_name), forbid_shadowing=True)
                return
            if isinstance(statement.initializer, ast.ArrayLiteral):
                value = self._evaluate_array_literal(
                    statement.initializer,
                    env,
                    statement.type_name if is_array_type(statement.type_name) else None,
                )
                coerced = (
                    coerce_array_literal_value(value, statement.type_name)
                    if is_array_type(statement.type_name)
                    else coerce_implicit(value, statement.type_name)
                )
                env.define(statement.name, coerced, forbid_shadowing=True)
                return
            value = self._evaluate(statement.initializer, env)
            if (
                statement.type_name == "float"
                and isinstance(statement.initializer, ast.Literal)
                and value.type_name == "double"
            ):
                env.define(statement.name, AetherValue("float", float(value.value)), forbid_shadowing=True)
                return
            env.define(statement.name, coerce_implicit(value, statement.type_name), forbid_shadowing=True)
            return
        if isinstance(statement, ast.Assignment):
            current = env.lookup(statement.name)
            if isinstance(statement.expression, ast.MatrixLiteral) and current is not None:
                if not statement.expression.rows and is_array_type(current.type_name):
                    env.assign(statement.name, AetherValue(current.type_name, []))
                    return
                value = self._evaluate_matrix_literal(
                    statement.expression,
                    env,
                    current.type_name if isinstance(current.type_name, MatrixType) else None,
                )
                env.assign(statement.name, value)
                return
            if isinstance(statement.expression, ast.ArrayLiteral) and current is not None and is_array_type(current.type_name):
                value = self._evaluate_array_literal(statement.expression, env, current.type_name)
                env.assign(statement.name, value, array_literal_context=True)
                return
            env.assign(statement.name, self._evaluate(statement.expression, env))
            return
        if isinstance(statement, ast.IndexAssignment):
            self._assign_index(statement, env)
            return
        if isinstance(statement, ast.MatrixIndexAssignment):
            self._assign_matrix_index(statement, env)
            return
        if isinstance(statement, ast.ExpressionStatement):
            self._evaluate(statement.expression, env)
            return
        if isinstance(statement, ast.ImportStatement):
            self._import_module(statement.module_name)
            return
        if isinstance(statement, ast.IfStatement):
            condition = self._evaluate(statement.condition, env)
            self._require_boolean(condition, "if")
            if condition.value:
                self._execute_block(statement.body, Environment(parent=env))
            elif statement.else_body is not None:
                self._execute_block(statement.else_body, Environment(parent=env))
            return
        if isinstance(statement, ast.WhileStatement):
            while True:
                condition = self._evaluate(statement.condition, env)
                self._require_boolean(condition, "while")
                if not condition.value:
                    break
                self._execute_block(statement.body, Environment(parent=env))
            return
        if isinstance(statement, ast.ForInStatement):
            iterable = self._evaluate(statement.iterable, env)
            for item in _iterable_values(iterable):
                loop_env = Environment(parent=env)
                loop_env.define(statement.variable, item, forbid_shadowing=True)
                self._execute_block(statement.body, loop_env)
            return
        if isinstance(statement, ast.FunctionDeclaration):
            env.define_function(Function(statement))
            return
        if isinstance(statement, ast.ExpressionFunctionDeclaration):
            env.define_function(Function(statement))
            return
        if isinstance(statement, ast.ReturnStatement):
            raise _ReturnSignal(self._evaluate(statement.expression, env))
        raise AetherRuntimeError(f"Unsupported statement {statement!r}.")

    def _execute_block(self, statements: list[ast.Statement], env: Environment) -> None:
        for statement in statements:
            self._execute(statement, env)

    def _evaluate(self, expression: ast.Expression, env: Environment) -> AetherValue:
        if isinstance(expression, ast.Literal):
            return AetherValue(expression.type_name, expression.value)
        if isinstance(expression, ast.InterpolatedString):
            return AetherValue("string", self._interpolate_string(expression, env))
        if isinstance(expression, ast.Identifier):
            return env.get(expression.name)
        if isinstance(expression, ast.UnaryExpression):
            operand = self._evaluate(expression.operand, env)
            if expression.operator == "-":
                if operand.type_name not in {"int", "float", "double"}:
                    raise AetherTypeError("Unary '-' requires a numeric operand.")
                return AetherValue(operand.type_name, -operand.value)
            raise AetherRuntimeError(f"Unsupported unary operator '{expression.operator}'.")
        if isinstance(expression, ast.BinaryExpression):
            if expression.operator in {"&&", "||"}:
                return self._evaluate_logical(expression, env)
            left = self._evaluate(expression.left, env)
            right = self._evaluate(expression.right, env)
            return self._evaluate_binary(left, expression.operator, right)
        if isinstance(expression, ast.RangeExpression):
            return self._evaluate_range(expression, env)
        if isinstance(expression, ast.CallExpression):
            args = [self._evaluate(arg, env) for arg in expression.arguments]
            return self._call(expression.callee, args, env)
        if isinstance(expression, ast.ArrayLiteral):
            return self._evaluate_array_literal(expression, env)
        if isinstance(expression, ast.MatrixLiteral):
            return self._evaluate_matrix_literal(expression, env)
        if isinstance(expression, ast.IndexExpression):
            return self._read_index(expression.array, expression.index, env)
        if isinstance(expression, ast.MatrixIndexExpression):
            return self._read_matrix_index(expression.matrix, expression.row, expression.column, env)
        raise AetherRuntimeError(f"Unsupported expression {expression!r}.")

    def _evaluate_range(self, expression: ast.RangeExpression, env: Environment) -> AetherValue:
        start = self._evaluate(expression.start, env)
        end = self._evaluate(expression.end, env)
        step = self._evaluate(expression.step, env) if expression.step is not None else AetherValue("int", 1)
        for label, value in (("start", start), ("end", end), ("step", step)):
            if value.type_name != "int":
                raise AetherTypeError(f"Range {label} must be int, got '{type_to_string(value.type_name)}'.")
        return AetherValue(RangeType("int"), AetherRange(start.value, step.value, end.value))

    def _evaluate_array_literal(
        self,
        expression: ast.ArrayLiteral,
        env: Environment,
        target_type: AetherType | None = None,
    ) -> AetherValue:
        elements = [self._evaluate(element, env) for element in expression.elements]
        if target_type is not None and is_array_type(target_type):
            value = (
                AetherValue(target_type, elements)
                if not elements
                else AetherValue(_array_type_from_values(elements), elements)
            )
            return coerce_array_literal_value(value, target_type)
        if not elements:
            raise AetherTypeError("Cannot infer type of empty array literal.")
        inferred_type = _array_type_from_values(elements)
        return coerce_array_literal_value(AetherValue(inferred_type, elements), inferred_type)

    def _evaluate_matrix_literal(
        self,
        expression: ast.MatrixLiteral,
        env: Environment,
        target_type: MatrixType | None = None,
    ) -> AetherValue:
        if not expression.rows:
            raise AetherTypeError("Cannot infer type of empty matrix literal.")
        row_lengths = [len(row) for row in expression.rows]
        if any(length == 0 for length in row_lengths) or any(length != row_lengths[0] for length in row_lengths):
            raise AetherTypeError("Matrix literals must be rectangular; ragged rows are not supported.")
        evaluated_rows = [[self._evaluate(element, env) for element in row] for row in expression.rows]
        flat_elements = [element for row in evaluated_rows for element in row]
        element_type = _common_primitive_type([element.type_name for element in flat_elements])
        row_type = ArrayType(element_type)
        rows: list[AetherValue] = []
        for row in evaluated_rows:
            coerced_row = coerce_array_literal_value(AetherValue(ArrayType(element_type), row), row_type)
            rows.append(coerced_row)
        if expression.vector:
            vector_rows = [
                AetherValue(row_type, [element])
                for row in rows
                for element in row.value
            ]
            value = AetherValue(MatrixType(element_type, len(vector_rows), 1, vector=True), vector_rows)
            return coerce_matrix_value(value, target_type) if target_type is not None else value
        inferred_type = MatrixType(element_type, len(rows), row_lengths[0])
        value = AetherValue(inferred_type, rows)
        return coerce_matrix_value(value, target_type) if target_type is not None else value

    def _read_index(self, array_expression: ast.Expression, index_expression: ast.Expression, env: Environment) -> AetherValue:
        array_value = self._evaluate(array_expression, env)
        index_value = self._evaluate(index_expression, env)
        index = self._require_array_index(array_value, index_value)
        if isinstance(array_value.type_name, MatrixType) and array_value.type_name.vector:
            return _vector_elements(array_value)[index]
        if isinstance(array_value.type_name, MatrixType):
            raise AetherTypeError("Matrix values require two-dimensional indexing with A[i, j].")
        return array_value.value[index]

    def _read_matrix_index(
        self,
        matrix_expression: ast.Expression,
        row_expression: ast.Expression,
        column_expression: ast.Expression,
        env: Environment,
    ) -> AetherValue:
        matrix_value = self._evaluate(matrix_expression, env)
        row_value = self._evaluate(row_expression, env)
        column_value = self._evaluate(column_expression, env)
        row, column = self._require_matrix_indices(matrix_value, row_value, column_value)
        return matrix_value.value[row].value[column]

    def _assign_index(self, statement: ast.IndexAssignment, env: Environment) -> None:
        array_value = self._evaluate(statement.array, env)
        index_value = self._evaluate(statement.index, env)
        index = self._require_array_index(array_value, index_value)
        value = self._evaluate(statement.expression, env)
        if isinstance(array_value.type_name, MatrixType) and not array_value.type_name.vector:
            raise AetherTypeError("Matrix values require two-dimensional indexing with A[i, j].")
        element_type = (
            array_value.type_name.element_type
            if isinstance(array_value.type_name, MatrixType) and array_value.type_name.vector
            else matrix_row_type(array_value.type_name)
            if isinstance(array_value.type_name, MatrixType)
            else array_element_type(array_value.type_name)
        )
        if is_array_type(element_type):
            raise AetherTypeError("Assigning a whole matrix row is not supported yet.")
        if isinstance(array_value.type_name, MatrixType) and array_value.type_name.vector:
            _assign_vector_element(array_value, index, coerce_implicit(value, element_type))
            return
        array_value.value[index] = coerce_implicit(value, element_type)

    def _assign_matrix_index(self, statement: ast.MatrixIndexAssignment, env: Environment) -> None:
        matrix_value = self._evaluate(statement.matrix, env)
        row_value = self._evaluate(statement.row, env)
        column_value = self._evaluate(statement.column_index, env)
        row, column = self._require_matrix_indices(matrix_value, row_value, column_value)
        value = self._evaluate(statement.expression, env)
        matrix_type = matrix_value.type_name
        if not isinstance(matrix_type, MatrixType):
            raise AetherTypeError(f"Two-dimensional indexing expects a matrix, got '{type_to_string(matrix_type)}'.")
        matrix_value.value[row].value[column] = coerce_implicit(value, matrix_type.element_type)

    def _require_array_index(self, array_value: AetherValue, index_value: AetherValue) -> int:
        if not is_indexable_type(array_value.type_name):
            raise AetherTypeError(f"Cannot index non-indexable value of type '{type_to_string(array_value.type_name)}'.")
        if index_value.type_name != "int":
            raise AetherTypeError(f"Array index must be int, got '{type_to_string(index_value.type_name)}'.")
        index = index_value.value
        if index < 0 or index >= len(array_value.value):
            raise AetherRuntimeError(f"Array index {index} out of bounds for length {len(array_value.value)}.")
        return index

    def _require_matrix_indices(
        self,
        matrix_value: AetherValue,
        row_value: AetherValue,
        column_value: AetherValue,
    ) -> tuple[int, int]:
        if not isinstance(matrix_value.type_name, MatrixType):
            raise AetherTypeError(f"Two-dimensional indexing expects a matrix, got '{type_to_string(matrix_value.type_name)}'.")
        if row_value.type_name != "int" or column_value.type_name != "int":
            raise AetherTypeError(
                f"Matrix indices must be int, got '{type_to_string(row_value.type_name)}' "
                f"and '{type_to_string(column_value.type_name)}'."
            )
        row = row_value.value
        column = column_value.value
        rows = len(matrix_value.value)
        cols = len(matrix_value.value[0].value) if matrix_value.value else 0
        if row < 0 or row >= rows:
            raise AetherRuntimeError(f"Matrix row index {row} out of bounds for {rows} rows.")
        if column < 0 or column >= cols:
            raise AetherRuntimeError(f"Matrix column index {column} out of bounds for {cols} columns.")
        return row, column

    def _call(self, callee: str, args: list[AetherValue], env: Environment) -> AetherValue:
        builtin_name = self.builtin_aliases.get(callee, callee)
        builtin = self.builtins.get(builtin_name)
        if builtin is not None:
            return builtin(args)
        function = env.get_function(callee)
        if function is None:
            raise AetherRuntimeError(f"Undefined function '{callee}'.")
        declaration = function.declaration
        if len(args) != len(declaration.parameters):
            raise AetherRuntimeError(
                f"Function '{callee}' expects {len(declaration.parameters)} arguments but got {len(args)}."
            )
        if isinstance(declaration, ast.ExpressionFunctionDeclaration):
            local_env = Environment(parent=self.global_env)
            for parameter, arg in zip(declaration.parameters, args):
                local_env.define(parameter.name, arg, forbid_shadowing=True)
            return self._evaluate(declaration.expression, local_env)
        local_env = Environment(parent=self.global_env)
        for parameter, arg in zip(declaration.parameters, args):
            local_env.define(parameter.name, coerce_implicit(arg, parameter.type_name), forbid_shadowing=True)
        try:
            self._execute_block(declaration.body, local_env)
        except _ReturnSignal as signal:
            return coerce_implicit(signal.value, declaration.return_type)
        raise AetherRuntimeError(f"Function '{callee}' ended without returning a value.")

    def _evaluate_binary(self, left: AetherValue, operator: str, right: AetherValue) -> AetherValue:
        if operator in {"+", "-", "*", "/", "%", "^"}:
            return self._numeric_or_string_binary(left, operator, right)
        if operator == "\\":
            if LINEAR_ALGEBRA_MODULE not in self.imported_modules:
                raise AetherRuntimeError("Operator '\\' requires import Math.LinearAlgebra.")
            return self.builtins[LINEAR_ALGEBRA_SOLVE]([left, right])
        if operator in {"==", "!="}:
            if not _types_comparable_for_equality(left.type_name, right.type_name):
                raise AetherTypeError(
                    f"Cannot compare '{type_to_string(left.type_name)}' and '{type_to_string(right.type_name)}' "
                    f"with '{operator}'."
                )
            result = _values_equal(left, right)
            return AetherValue("boolean", result if operator == "==" else not result)
        if operator in {"<", "<=", ">", ">="}:
            if left.type_name not in {"int", "float", "double"} or right.type_name not in {"int", "float", "double"}:
                raise AetherTypeError(f"Operator '{operator}' requires numeric operands.")
            return AetherValue("boolean", _compare_values(left.value, operator, right.value))
        raise AetherRuntimeError(f"Unsupported binary operator '{operator}'.")

    def _evaluate_logical(self, expression: ast.BinaryExpression, env: Environment) -> AetherValue:
        left = self._evaluate(expression.left, env)
        self._require_boolean(left, f"operator '{expression.operator}'")
        if expression.operator == "&&" and not left.value:
            return AetherValue("boolean", False)
        if expression.operator == "||" and left.value:
            return AetherValue("boolean", True)
        right = self._evaluate(expression.right, env)
        self._require_boolean(right, f"operator '{expression.operator}'")
        if expression.operator == "&&":
            return AetherValue("boolean", right.value)
        if expression.operator == "||":
            return AetherValue("boolean", right.value)
        raise AetherRuntimeError(f"Unsupported logical operator '{expression.operator}'.")

    def _numeric_or_string_binary(self, left: AetherValue, operator: str, right: AetherValue) -> AetherValue:
        if operator == "+" and left.type_name == "string" and right.type_name == "string":
            return AetherValue("string", left.value + right.value)
        array_array_result = _evaluate_array_array_binary(left, operator, right)
        if array_array_result is not None:
            return array_array_result
        scalar_array_result = _evaluate_scalar_array_binary(left, operator, right)
        if scalar_array_result is not None:
            return scalar_array_result
        if operator == "%" and (left.type_name not in NUMERIC_TYPES or right.type_name not in NUMERIC_TYPES):
            raise AetherTypeError("Operator '%' requires numeric operands.")
        if left.type_name == "string" or right.type_name == "string":
            raise AetherTypeError(f"Operator '{operator}' cannot mix string with non-string values.")
        if left.type_name == "boolean" or right.type_name == "boolean":
            raise AetherTypeError(f"Operator '{operator}' cannot be applied to boolean values.")
        if (
            is_array_type(left.type_name)
            or is_array_type(right.type_name)
            or is_matrix_type(left.type_name)
            or is_matrix_type(right.type_name)
        ):
            raise AetherTypeError(f"Operator '{operator}' requires numeric operands.")
        result_type = promote_numeric(left.type_name, right.type_name, operator)
        if operator == "+":
            value = left.value + right.value
        elif operator == "-":
            value = left.value - right.value
        elif operator == "*":
            value = left.value * right.value
        elif operator == "/":
            value = left.value / right.value
        elif operator == "%":
            if right.value == 0:
                raise AetherRuntimeError("Operator '%' is undefined for divisor zero.")
            value = left.value - trunc(left.value / right.value) * right.value
        elif operator == "^":
            if left.type_name == "int" and right.type_name == "int" and right.value < 0:
                result_type = "double"
            value = left.value**right.value
        else:
            raise AetherRuntimeError(f"Unsupported numeric operator '{operator}'.")
        if result_type == "int":
            value = int(value)
        else:
            value = float(value)
        return AetherValue(result_type, value)

    def _import_module(self, module_name: str) -> None:
        if module_name in self.imported_modules:
            return
        if is_builtin_namespace(module_name):
            self.builtin_aliases.update(builtin_aliases_for_import(module_name))
            self.imported_modules.add(module_name)
            return
        module_path = Path(module_name.replace(".", "/"))
        if module_path.suffix == "":
            module_path = module_path.with_suffix(".ae")
        if not module_path.is_absolute():
            module_path = Path.cwd() / module_path
        if not module_path.is_file():
            raise AetherRuntimeError(f"Module '{module_name}' not found.")
        source = module_path.read_text(encoding="utf-8")
        tokens = lex(source)
        program = Parser(tokens).parse()
        self.interpret(program)
        self.imported_modules.add(module_name)

    def _require_boolean(self, value: AetherValue, construct: str) -> None:
        if value.type_name != "boolean":
            raise AetherTypeError(f"The condition of '{construct}' must be boolean, got '{value.type_name}'.")

    def _interpolate_string(self, expression: ast.InterpolatedString, env: Environment) -> str:
        parts: list[str] = []
        for part in expression.parts:
            if isinstance(part, str):
                parts.append(part)
                continue
            parts.append(format_value(self._evaluate(part, env)))
        return "".join(parts)


def _default_plot_mode(mode: str | None) -> str:
    token = (mode or os.environ.get("AETHER_PLOT_MODE") or "interactive").strip().lower()
    return "document" if token == "document" else "interactive"


def _default_plot_output_dir(output_dir: str | Path | None) -> str | Path:
    return output_dir or os.environ.get("AETHER_PLOT_DIR") or "."


def _iterable_values(value: AetherValue) -> list[AetherValue] | AetherRange:
    if isinstance(value.type_name, RangeType):
        if not isinstance(value.value, AetherRange):
            raise AetherRuntimeError("Invalid range value.")
        return value.value
    if isinstance(value.type_name, ArrayType):
        return list(value.value)
    if isinstance(value.type_name, MatrixType) and _is_vector_like_matrix(value):
        return _vector_elements(value)
    raise AetherTypeError(f"Cannot iterate over value of type '{type_to_string(value.type_name)}'.")


def _is_vector_like_matrix(value: AetherValue) -> bool:
    if not isinstance(value.type_name, MatrixType):
        return False
    rows = len(value.value)
    cols = len(value.value[0].value) if value.value else 0
    return value.type_name.vector or rows == 1 or cols == 1


def _vector_elements(value: AetherValue) -> list[AetherValue]:
    rows = value.value
    if not rows:
        return []
    if len(rows) == 1:
        return list(rows[0].value)
    if len(rows[0].value) == 1:
        return [row.value[0] for row in rows]
    raise AetherTypeError(f"Cannot iterate over value of type '{type_to_string(value.type_name)}'.")


def _assign_vector_element(value: AetherValue, index: int, element: AetherValue) -> None:
    rows = value.value
    if len(rows) == 1:
        rows[0].value[index] = element
        return
    rows[index].value[0] = element


def _array_type_from_values(elements: list[AetherValue]) -> ArrayType:
    element_types = [element.type_name for element in elements]
    primitive_types = [element_type for element_type in element_types if isinstance(element_type, str)]
    array_types = [element_type for element_type in element_types if isinstance(element_type, ArrayType)]
    if primitive_types and array_types:
        raise AetherTypeError("Array literals must contain homogeneous compatible element types.")
    if primitive_types:
        return ArrayType(_common_primitive_type(primitive_types))
    if array_types:
        if any(is_array_type(element_type.element_type) for element_type in array_types):
            raise AetherTypeError("Arrays nested deeper than 2D are not supported in Aether v0.")
        row_lengths = [len(element.value) for element in elements]
        if row_lengths and any(length != row_lengths[0] for length in row_lengths):
            raise AetherTypeError("Matrix literals must be rectangular; ragged arrays are not supported.")
        return ArrayType(ArrayType(_common_primitive_type([element_type.element_type for element_type in array_types])))
    raise AetherTypeError("Array literals must contain homogeneous compatible element types.")


def _common_primitive_type(primitive_types: list[AetherType]) -> str:
    if not all(isinstance(type_name, str) for type_name in primitive_types):
        raise AetherTypeError("Array literals must contain homogeneous compatible element types.")
    unique_types = set(primitive_types)
    if len(unique_types) == 1:
        return primitive_types[0]
    if unique_types <= NUMERIC_TYPES:
        if "double" in unique_types:
            return "double"
        if "float" in unique_types:
            return "float"
        return "int"
    raise AetherTypeError("Array literals must contain homogeneous compatible element types.")


def _types_comparable_for_equality(left_type: AetherType, right_type: AetherType) -> bool:
    if left_type == right_type:
        return True
    if isinstance(left_type, ArrayType) and isinstance(right_type, ArrayType):
        return _types_comparable_for_equality(left_type.element_type, right_type.element_type)
    if isinstance(left_type, MatrixType) and isinstance(right_type, MatrixType):
        return left_type.rows == right_type.rows and left_type.cols == right_type.cols and _types_comparable_for_equality(
            left_type.element_type,
            right_type.element_type,
        )
    if is_array_type(left_type) or is_array_type(right_type) or is_matrix_type(left_type) or is_matrix_type(right_type):
        return False
    return left_type in {"int", "float", "double"} and right_type in {"int", "float", "double"}


def _evaluate_scalar_array_binary(left: AetherValue, operator: str, right: AetherValue) -> AetherValue | None:
    left_is_matrix = is_matrix_type(left.type_name)
    right_is_matrix = is_matrix_type(right.type_name)
    if not left_is_matrix and not right_is_matrix:
        return None
    if left_is_matrix and right_is_matrix:
        return None
    if operator not in {"*", "/"}:
        return None
    if operator == "/" and right_is_matrix:
        return None
    matrix_value = left if left_is_matrix else right
    scalar_value = right if left_is_matrix else left
    if not isinstance(matrix_value.type_name, MatrixType) or scalar_value.type_name not in NUMERIC_TYPES:
        return None
    element_type = _numeric_matrix_scalar_type(matrix_value.type_name)
    result_element_type = promote_numeric(element_type, scalar_value.type_name, operator)
    result_type = MatrixType(
        result_element_type,
        matrix_value.type_name.rows,
        matrix_value.type_name.cols,
        matrix_value.type_name.vector,
    )
    return AetherValue(result_type, _map_matrix_scalar(matrix_value, scalar_value, operator, result_element_type))


def _evaluate_array_array_binary(left: AetherValue, operator: str, right: AetherValue) -> AetherValue | None:
    if not is_matrix_type(left.type_name) or not is_matrix_type(right.type_name):
        return None
    if operator not in {"+", "-"}:
        return None
    if not isinstance(left.type_name, MatrixType) or not isinstance(right.type_name, MatrixType):
        return None
    if len(left.value) != len(right.value) or (
        left.value and right.value and len(left.value[0].value) != len(right.value[0].value)
    ):
        raise AetherRuntimeError(
            f"Matrix operands for '{operator}' must have the same shape, got "
            f"{len(left.value)}x{len(left.value[0].value) if left.value else 0} and "
            f"{len(right.value)}x{len(right.value[0].value) if right.value else 0}."
        )
    left_element_type = _numeric_matrix_scalar_type(left.type_name)
    right_element_type = _numeric_matrix_scalar_type(right.type_name)
    result_element_type = promote_numeric(left_element_type, right_element_type, operator)
    result_type = MatrixType(result_element_type, left.type_name.rows, left.type_name.cols, left.type_name.vector and right.type_name.vector)
    return AetherValue(result_type, _map_matrix_matrix(left, right, operator, result_element_type))


def _numeric_matrix_scalar_type(matrix_type: MatrixType) -> str:
    if matrix_type.element_type not in NUMERIC_TYPES:
        raise AetherTypeError("Matrix operations require numeric elements.")
    return matrix_type.element_type


def _map_matrix_scalar(
    matrix_value: AetherValue,
    scalar_value: AetherValue,
    operator: str,
    result_element_type: str,
) -> list[AetherValue]:
    mapped: list[AetherValue] = []
    row_type = ArrayType(result_element_type)
    for row in matrix_value.value:
        row_elements = [
            _apply_scalar_to_element(element, scalar_value, operator, result_element_type)
            for element in row.value
        ]
        mapped.append(AetherValue(row_type, row_elements))
    return mapped


def _apply_scalar_to_element(
    element: AetherValue,
    scalar_value: AetherValue,
    operator: str,
    result_element_type: str,
) -> AetherValue:
    if element.type_name not in NUMERIC_TYPES:
        raise AetherTypeError("Scalar operations require numeric array elements.")
    if operator == "*":
        result = element.value * scalar_value.value
    elif operator == "/":
        result = element.value / scalar_value.value
    else:
        raise AetherRuntimeError(f"Unsupported scalar array operator '{operator}'.")
    if result_element_type == "int":
        result = int(result)
    else:
        result = float(result)
    return AetherValue(result_element_type, result)


def _map_matrix_matrix(
    left: AetherValue,
    right: AetherValue,
    operator: str,
    result_element_type: str,
) -> list[AetherValue]:
    if len(left.value) != len(right.value):
        raise AetherRuntimeError(
            f"Array operands for '{operator}' must have the same shape, got lengths "
            f"{len(left.value)} and {len(right.value)}."
        )
    mapped: list[AetherValue] = []
    row_type = ArrayType(result_element_type)
    for left_row, right_row in zip(left.value, right.value):
        if len(left_row.value) != len(right_row.value):
            raise AetherRuntimeError(f"Matrix operands for '{operator}' must have the same shape.")
        row_elements = [
            _apply_array_element_operator(left_element, operator, right_element, result_element_type)
            for left_element, right_element in zip(left_row.value, right_row.value)
        ]
        mapped.append(AetherValue(row_type, row_elements))
    return mapped


def _apply_array_element_operator(
    left: AetherValue,
    operator: str,
    right: AetherValue,
    result_element_type: str,
) -> AetherValue:
    if left.type_name not in NUMERIC_TYPES or right.type_name not in NUMERIC_TYPES:
        raise AetherTypeError("Array arithmetic requires numeric elements.")
    if operator == "+":
        result = left.value + right.value
    elif operator == "-":
        result = left.value - right.value
    else:
        raise AetherRuntimeError(f"Unsupported array operator '{operator}'.")
    if result_element_type == "int":
        result = int(result)
    else:
        result = float(result)
    return AetherValue(result_element_type, result)


def _values_equal(left: AetherValue, right: AetherValue) -> bool:
    if isinstance(left.type_name, MatrixType) and isinstance(right.type_name, MatrixType):
        if len(left.value) != len(right.value):
            return False
        return all(_values_equal(left_row, right_row) for left_row, right_row in zip(left.value, right.value))
    if isinstance(left.type_name, ArrayType) and isinstance(right.type_name, ArrayType):
        if len(left.value) != len(right.value):
            return False
        return all(_values_equal(left_element, right_element) for left_element, right_element in zip(left.value, right.value))
    return left.value == right.value


def _compare_values(left: object, operator: str, right: object) -> bool:
    if operator == "<":
        return left < right  # type: ignore[operator]
    if operator == "<=":
        return left <= right  # type: ignore[operator]
    if operator == ">":
        return left > right  # type: ignore[operator]
    if operator == ">=":
        return left >= right  # type: ignore[operator]
    raise AetherRuntimeError(f"Unsupported comparison operator '{operator}'.")
