from __future__ import annotations

from collections.abc import Callable
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
    TupleType,
    TransposeVectorType,
    VectorType,
    array_element_type,
    coerce_array_literal_value,
    coerce_implicit,
    coerce_matrix_value,
    coerce_return_value,
    coerce_vector_value,
    is_array_type,
    is_indexable_type,
    is_matrix_type,
    is_vector_like_type,
    matrix_row_type,
    promote_numeric,
    type_to_string,
)


LINEAR_ALGEBRA_MODULE = "Math.LinearAlgebra"
LINEAR_ALGEBRA_SOLVE = "Math.LinearAlgebra.solve"
LINEAR_ALGEBRA_CONJTRANSPOSE = "Math.LinearAlgebra.conjtranspose"


@dataclass
class Function:
    declaration: ast.FunctionDeclaration | ast.ExpressionFunctionDeclaration


@dataclass(frozen=True)
class FunctionReference:
    name: str
    arity: int
    call: Callable[[list[AetherValue]], AetherValue]


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
    def __init__(
        self,
        *,
        plot_mode: str | None = None,
        plot_output_dir: str | Path | None = None,
        output_writer: Callable[[str], None] | None = None,
    ) -> None:
        self.global_env = Environment()
        self.output_parts: list[str] = []
        self.output_writer = output_writer
        self.plot_backend = PlotBackend(
            plot_mode=_default_plot_mode(plot_mode),
            output_dir=_default_plot_output_dir(plot_output_dir),
        )
        self.builtins: dict[str, BuiltinFunction] = make_builtins(
            self._write_output,
            plot_backend=self.plot_backend,
        )
        self.builtin_aliases: dict[str, str] = {}
        self.imported_modules: set[str] = set()
        self._interpret_depth = 0

    def interpret(self, program: ast.Program) -> Environment:
        self._interpret_depth += 1
        try:
            for statement in program.statements:
                self._execute(statement, self.global_env)
            return self.global_env
        finally:
            self._interpret_depth -= 1
            if self._interpret_depth == 0:
                self.plot_backend.wait_for_interactive_plots()

    @property
    def output(self) -> str:
        return "".join(self.output_parts)

    def clear_output(self) -> None:
        self.output_parts.clear()

    def _write_output(self, text: str) -> None:
        self.output_parts.append(text)
        if self.output_writer is not None:
            self.output_writer(text)

    def _execute(self, statement: ast.Statement, env: Environment) -> None:
        if isinstance(statement, ast.VarDeclaration):
            if isinstance(statement.initializer, ast.MatrixLiteral):
                if not statement.initializer.rows and is_array_type(statement.type_name):
                    env.define(statement.name, AetherValue(statement.type_name, []), forbid_shadowing=True)
                    return
                value = self._evaluate_matrix_literal(
                    statement.initializer,
                    env,
                    statement.type_name if isinstance(statement.type_name, (MatrixType, VectorType)) else None,
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
                    current.type_name if isinstance(current.type_name, (MatrixType, VectorType)) else None,
                )
                env.assign(statement.name, value)
                return
            if isinstance(statement.expression, ast.ArrayLiteral) and current is not None and is_array_type(current.type_name):
                value = self._evaluate_array_literal(statement.expression, env, current.type_name)
                env.assign(statement.name, value, array_literal_context=True)
                return
            env.assign(statement.name, self._evaluate(statement.expression, env))
            return
        if isinstance(statement, ast.DestructuringAssignment):
            self._assign_destructuring(statement, env)
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
            if expression.operator == "'":
                if LINEAR_ALGEBRA_MODULE not in self.imported_modules:
                    raise AetherRuntimeError("Operator \"'\" requires import Math.LinearAlgebra.")
                return self.builtins[LINEAR_ALGEBRA_CONJTRANSPOSE]([operand])
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
            return self._evaluate_call(expression, env)
        if isinstance(expression, ast.ArrayLiteral):
            return self._evaluate_array_literal(expression, env)
        if isinstance(expression, ast.TupleLiteral):
            return self._evaluate_tuple_literal(expression, env)
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

    def _evaluate_tuple_literal(self, expression: ast.TupleLiteral, env: Environment) -> AetherValue:
        elements = tuple(self._evaluate(element, env) for element in expression.elements)
        if len(elements) < 2:
            raise AetherTypeError("Tuple literals require at least two elements.")
        return AetherValue(TupleType(tuple(element.type_name for element in elements)), elements)

    def _evaluate_matrix_literal(
        self,
        expression: ast.MatrixLiteral,
        env: Environment,
        target_type: AetherType | None = None,
    ) -> AetherValue:
        if not expression.rows:
            raise AetherTypeError("Cannot infer type of empty matrix literal.")
        row_lengths = [len(row) for row in expression.rows]
        if any(length == 0 for length in row_lengths):
            raise AetherTypeError("Matrix literals must be rectangular; ragged rows are not supported.")
        evaluated_rows = [[self._evaluate(element, env) for element in row] for row in expression.rows]
        flat_elements = [element for row in evaluated_rows for element in row]
        if not all(isinstance(element.type_name, str) for element in flat_elements):
            value = _evaluate_matrix_concat_literal(expression, evaluated_rows)
            if isinstance(target_type, VectorType):
                return coerce_vector_value(value, target_type)
            if isinstance(target_type, MatrixType):
                return coerce_matrix_value(value, target_type)
            return value
        if any(length != row_lengths[0] for length in row_lengths):
            raise AetherTypeError("Matrix literals must be rectangular; ragged rows are not supported.")
        element_type = _common_primitive_type([element.type_name for element in flat_elements])
        row_type = ArrayType(element_type)
        rows: list[AetherValue] = []
        for row in evaluated_rows:
            coerced_row = coerce_array_literal_value(AetherValue(ArrayType(element_type), row), row_type)
            rows.append(coerced_row)
        if expression.vector:
            vector_elements = [element for row in rows for element in row.value]
            value = AetherValue(VectorType(element_type, len(vector_elements)), vector_elements)
            if isinstance(target_type, VectorType):
                return coerce_vector_value(value, target_type)
            if isinstance(target_type, MatrixType):
                legacy_rows = [AetherValue(row_type, [element]) for element in vector_elements]
                legacy_value = AetherValue(MatrixType(element_type, len(legacy_rows), 1, vector=True), legacy_rows)
                return coerce_matrix_value(legacy_value, target_type)
            return value
        inferred_type = MatrixType(element_type, len(rows), row_lengths[0])
        value = AetherValue(inferred_type, rows)
        if isinstance(target_type, VectorType):
            return coerce_vector_value(value, target_type)
        if isinstance(target_type, MatrixType):
            return coerce_matrix_value(value, target_type)
        return value

    def _read_index(self, array_expression: ast.Expression, index_expression: ast.Expression, env: Environment) -> AetherValue:
        array_value = self._evaluate(array_expression, env)
        if isinstance(index_expression, ast.FullSlice) or isinstance(index_expression, ast.RangeExpression):
            return self._read_vector_slice(array_value, index_expression, env)
        index_value = self._evaluate(index_expression, env)
        index = self._require_array_index(array_value, index_value)
        if isinstance(array_value.type_name, (VectorType, TransposeVectorType)):
            return _vector_elements(array_value)[index]
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
        row_selector = self._matrix_index_selector(matrix_value, row_expression, env, axis=0)
        column_selector = self._matrix_index_selector(matrix_value, column_expression, env, axis=1)
        if isinstance(row_selector, int) and isinstance(column_selector, int):
            return matrix_value.value[row_selector].value[column_selector]
        row_indices = [row_selector] if isinstance(row_selector, int) else row_selector
        column_indices = [column_selector] if isinstance(column_selector, int) else column_selector
        if isinstance(row_selector, int) or isinstance(column_selector, int):
            elements = [
                matrix_value.value[row].value[column]
                for row in row_indices
                for column in column_indices
            ]
            return AetherValue(VectorType(matrix_value.type_name.element_type, len(elements)), elements)
        row_type = ArrayType(matrix_value.type_name.element_type)
        rows = [
            AetherValue(row_type, [matrix_value.value[row].value[column] for column in column_indices])
            for row in row_indices
        ]
        return AetherValue(MatrixType(matrix_value.type_name.element_type, len(rows), len(column_indices)), rows)

    def _read_vector_slice(
        self,
        vector_value: AetherValue,
        index_expression: ast.Expression,
        env: Environment,
    ) -> AetherValue:
        if not is_vector_like_type(vector_value.type_name):
            raise AetherTypeError(f"Cannot slice non-vector value of type '{type_to_string(vector_value.type_name)}'.")
        elements = _vector_elements(vector_value)
        indices = self._slice_indices(index_expression, env, len(elements), "Vector")
        sliced = [elements[index] for index in indices]
        if isinstance(vector_value.type_name, TransposeVectorType):
            vector = AetherValue(VectorType(vector_value.type_name.element_type, len(sliced)), sliced)
            return AetherValue(TransposeVectorType(vector_value.type_name.element_type, len(sliced)), vector)
        element_type = _vector_element_type(vector_value)
        return AetherValue(VectorType(element_type, len(sliced)), sliced)

    def _matrix_index_selector(
        self,
        matrix_value: AetherValue,
        expression: ast.Expression,
        env: Environment,
        *,
        axis: int,
    ) -> int | list[int]:
        if not isinstance(matrix_value.type_name, MatrixType):
            raise AetherTypeError(f"Two-dimensional indexing expects a matrix, got '{type_to_string(matrix_value.type_name)}'.")
        size = len(matrix_value.value) if axis == 0 else len(matrix_value.value[0].value) if matrix_value.value else 0
        label = "Matrix row" if axis == 0 else "Matrix column"
        if isinstance(expression, ast.FullSlice) or isinstance(expression, ast.RangeExpression):
            return self._slice_indices(expression, env, size, label)
        value = self._evaluate(expression, env)
        if value.type_name != "int":
            raise AetherTypeError(f"{label} index must be int or slice, got '{type_to_string(value.type_name)}'.")
        index = value.value
        if index < 0 or index >= size:
            raise AetherRuntimeError(f"{label} index {index} out of bounds for {size}.")
        return index

    def _slice_indices(self, expression: ast.Expression, env: Environment, size: int, label: str) -> list[int]:
        if isinstance(expression, ast.FullSlice):
            return list(range(size))
        range_value = self._evaluate_range(expression, env) if isinstance(expression, ast.RangeExpression) else self._evaluate(expression, env)
        if not isinstance(range_value.type_name, RangeType) or not isinstance(range_value.value, AetherRange):
            raise AetherTypeError(f"{label} slice must be ':' or an int range.")
        indices = [element.value for element in range_value.value]
        for index in indices:
            if index < 0 or index >= size:
                raise AetherRuntimeError(f"{label} index {index} out of bounds for {size}.")
        return indices

    def _assign_index(self, statement: ast.IndexAssignment, env: Environment) -> None:
        array_value = self._evaluate(statement.array, env)
        index_value = self._evaluate(statement.index, env)
        index = self._require_array_index(array_value, index_value)
        value = self._evaluate(statement.expression, env)
        if isinstance(array_value.type_name, TransposeVectorType):
            raise AetherTypeError("Cannot assign through a transposed vector view.")
        if isinstance(array_value.type_name, MatrixType) and not array_value.type_name.vector:
            raise AetherTypeError("Matrix values require two-dimensional indexing with A[i, j].")
        element_type = (
            array_value.type_name.element_type
            if isinstance(array_value.type_name, VectorType)
            else array_value.type_name.element_type
            if isinstance(array_value.type_name, TransposeVectorType)
            else
            array_value.type_name.element_type
            if isinstance(array_value.type_name, MatrixType) and array_value.type_name.vector
            else matrix_row_type(array_value.type_name)
            if isinstance(array_value.type_name, MatrixType)
            else array_element_type(array_value.type_name)
        )
        if is_array_type(element_type):
            raise AetherTypeError("Assigning a whole matrix row is not supported yet.")
        if isinstance(array_value.type_name, VectorType):
            array_value.value[index] = coerce_implicit(value, element_type)
            return
        if isinstance(array_value.type_name, MatrixType) and array_value.type_name.vector:
            _assign_vector_element(array_value, index, coerce_implicit(value, element_type))
            return
        array_value.value[index] = coerce_implicit(value, element_type)

    def _assign_destructuring(self, statement: ast.DestructuringAssignment, env: Environment) -> None:
        value = self._evaluate(statement.expression, env)
        if not isinstance(value.type_name, TupleType):
            raise AetherTypeError(f"Cannot destructure value of type {type_to_string(value.type_name)}.")
        if len(value.value) != len(statement.names):
            raise AetherTypeError(f"Destructuring expected {len(value.value)} values but got {len(statement.names)}.")
        for name, element in zip(statement.names, value.value):
            env.assign(name, element)

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
        length = _indexable_length(array_value)
        if index < 0 or index >= length:
            raise AetherRuntimeError(f"Array index {index} out of bounds for length {length}.")
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

    def _evaluate_call(self, expression: ast.CallExpression, env: Environment) -> AetherValue:
        builtin_name = self.builtin_aliases.get(expression.callee, expression.callee)
        named_args = {name: self._evaluate(value, env) for name, value in expression.keyword_arguments.items()}
        if builtin_name in self.builtins:
            args = [
                self._evaluate_builtin_argument(arg, env, builtin_name)
                for arg in expression.arguments
            ]
            return self._call(expression.callee, args, named_args, env)
        if named_args:
            raise AetherRuntimeError(f"Function '{expression.callee}' does not accept keyword arguments.")
        args = [self._evaluate(arg, env) for arg in expression.arguments]
        return self._call(expression.callee, args, {}, env)

    def _evaluate_builtin_argument(self, expression: ast.Expression, env: Environment, builtin_name: str) -> AetherValue:
        if builtin_name.startswith("Plots.") and isinstance(expression, ast.Identifier):
            if env.lookup(expression.name) is None and env.get_function(expression.name) is not None:
                return self._function_reference_value(expression.name, env)
        return self._evaluate(expression, env)

    def _function_reference_value(self, name: str, env: Environment) -> AetherValue:
        function = env.get_function(name)
        if function is None:
            raise AetherRuntimeError(f"Undefined function '{name}'.")

        def call(args: list[AetherValue]) -> AetherValue:
            return self._call_user_function(name, args, env)

        return AetherValue("function", FunctionReference(name, len(function.declaration.parameters), call))

    def _call(
        self,
        callee: str,
        args: list[AetherValue],
        named_args: dict[str, AetherValue],
        env: Environment,
    ) -> AetherValue:
        builtin_name = self.builtin_aliases.get(callee, callee)
        builtin = self.builtins.get(builtin_name)
        if builtin is not None:
            if named_args:
                if not builtin_name.startswith("Plots."):
                    raise AetherRuntimeError(f"Builtin '{callee}' does not accept keyword arguments.")
                args = [*args, AetherValue("__kwargs__", named_args)]
            return builtin(args)
        if named_args:
            raise AetherRuntimeError(f"Function '{callee}' does not accept keyword arguments.")
        return self._call_user_function(callee, args, env)

    def _call_user_function(self, callee: str, args: list[AetherValue], env: Environment) -> AetherValue:
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
                local_env.define(parameter.name, arg)
            return self._evaluate(declaration.expression, local_env)
        local_env = Environment(parent=self.global_env)
        for parameter, arg in zip(declaration.parameters, args):
            local_env.define(parameter.name, coerce_implicit(arg, parameter.type_name))
        try:
            self._execute_block(declaration.body, local_env)
        except _ReturnSignal as signal:
            return coerce_return_value(signal.value, declaration.return_type)
        raise AetherRuntimeError(f"Function '{callee}' ended without returning a value.")

    def _evaluate_binary(self, left: AetherValue, operator: str, right: AetherValue) -> AetherValue:
        if operator in {"+", "-", ".+", ".-", "*", ".*", "/", "%", "^"}:
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
        if operator in {"+", "-"}:
            algebraic_result = _evaluate_algebraic_addition(left, operator, right)
            if algebraic_result is not None:
                return algebraic_result
        if operator == "*":
            algebraic_result = _evaluate_algebraic_multiplication(left, right)
            if algebraic_result is not None:
                return algebraic_result
        if operator in {".+", ".-", ".*"}:
            return _evaluate_elementwise_binary(left, operator[1], right, operator)
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


@dataclass(frozen=True)
class _ConcatBlockValue:
    element_type: str
    rows: list[list[AetherValue]]
    vector_kind: str | None = None

    @property
    def row_count(self) -> int:
        return len(self.rows)

    @property
    def col_count(self) -> int:
        return len(self.rows[0]) if self.rows else 0


def _evaluate_matrix_concat_literal(
    expression: ast.MatrixLiteral,
    evaluated_rows: list[list[AetherValue]],
) -> AetherValue:
    if expression.vector:
        if len(evaluated_rows) == 1 or any(len(row) != 1 for row in evaluated_rows):
            raise AetherTypeError("Matrix concatenation with ',' is not supported for matrix or vector blocks.")

    block_rows = [[_concat_block_value(value) for value in row] for row in evaluated_rows]
    element_type = _common_primitive_type([block.element_type for row in block_rows for block in row])
    if _is_pure_vector_vcat_literal(expression, block_rows):
        elements = [
            coerce_implicit(element, element_type)
            for block_row in block_rows
            for element in _single_vector_block_elements(block_row[0])
        ]
        return AetherValue(VectorType(element_type, len(elements)), elements)

    rows: list[list[AetherValue]] = []
    row_widths: list[int] = []
    for block_row in block_rows:
        row_height = _concat_block_row_height(block_row)
        row_widths.append(sum(block.col_count for block in block_row))
        for row_index in range(row_height):
            rows.append(
                [
                    coerce_implicit(element, element_type)
                    for block in block_row
                    for element in block.rows[row_index]
                ]
            )
    if row_widths and any(width != row_widths[0] for width in row_widths):
        raise AetherTypeError("Concatenated matrix rows must have the same number of columns.")
    row_type = ArrayType(element_type)
    matrix_rows = [AetherValue(row_type, row) for row in rows]
    return AetherValue(MatrixType(element_type, len(matrix_rows), row_widths[0] if row_widths else 0), matrix_rows)


def _concat_block_value(value: AetherValue) -> _ConcatBlockValue:
    if isinstance(value.type_name, str):
        return _ConcatBlockValue(value.type_name, [[value]])
    if isinstance(value.type_name, VectorType):
        return _ConcatBlockValue(value.type_name.element_type, [[element] for element in value.value], "vector")
    if isinstance(value.type_name, TransposeVectorType):
        return _ConcatBlockValue(value.type_name.element_type, [list(value.value.value)], "transpose_vector")
    if isinstance(value.type_name, MatrixType):
        return _ConcatBlockValue(
            value.type_name.element_type,
            [list(row.value) for row in value.value],
            "matrix_vector" if value.type_name.vector else None,
        )
    raise AetherTypeError("Matrix concatenation only supports scalar, Vector<T>, TransposeVector<T>, and Matrix<T> blocks.")


def _concat_block_row_height(blocks: list[_ConcatBlockValue]) -> int:
    heights = [block.row_count for block in blocks]
    if heights and any(height != heights[0] for height in heights):
        raise AetherTypeError("Concatenated matrix blocks in a row must have the same number of rows.")
    return heights[0] if heights else 0


def _is_pure_vector_vcat_literal(expression: ast.MatrixLiteral, blocks: list[list[_ConcatBlockValue]]) -> bool:
    return (
        expression.vector
        and len(blocks) > 1
        and all(len(row) == 1 for row in blocks)
        and all(row[0].vector_kind == "vector" for row in blocks)
    )


def _single_vector_block_elements(block: _ConcatBlockValue) -> list[AetherValue]:
    return [row[0] for row in block.rows]


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
    if isinstance(value.type_name, VectorType):
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
    if isinstance(value.type_name, VectorType):
        return list(value.value)
    if isinstance(value.type_name, TransposeVectorType):
        return list(value.value.value)
    rows = value.value
    if not rows:
        return []
    if len(rows) == 1:
        return list(rows[0].value)
    if len(rows[0].value) == 1:
        return [row.value[0] for row in rows]
    raise AetherTypeError(f"Cannot iterate over value of type '{type_to_string(value.type_name)}'.")


def _vector_element_type(value: AetherValue) -> str:
    if isinstance(value.type_name, (VectorType, TransposeVectorType, MatrixType)):
        return value.type_name.element_type
    raise AetherTypeError(f"Expected vector, got '{type_to_string(value.type_name)}'.")


def _indexable_length(value: AetherValue) -> int:
    if isinstance(value.type_name, TransposeVectorType):
        return len(value.value.value)
    if isinstance(value.type_name, VectorType):
        return len(value.value)
    return len(value.value)


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
    if isinstance(left_type, VectorType) and isinstance(right_type, VectorType):
        return left_type.length == right_type.length and _types_comparable_for_equality(
            left_type.element_type,
            right_type.element_type,
        )
    if isinstance(left_type, TransposeVectorType) and isinstance(right_type, TransposeVectorType):
        return left_type.length == right_type.length and _types_comparable_for_equality(
            left_type.element_type,
            right_type.element_type,
        )
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


def _evaluate_algebraic_addition(left: AetherValue, operator: str, right: AetherValue) -> AetherValue | None:
    if isinstance(left.type_name, VectorType) and isinstance(right.type_name, VectorType):
        return _elementwise_vector_vector(left, operator, right, operator)
    if isinstance(left.type_name, TransposeVectorType) and isinstance(right.type_name, TransposeVectorType):
        vector = _elementwise_vector_vector(left.value, operator, right.value, operator)
        return AetherValue(TransposeVectorType(vector.type_name.element_type, len(vector.value)), vector)
    return None


def _evaluate_algebraic_multiplication(left: AetherValue, right: AetherValue) -> AetherValue | None:
    if _is_numeric_scalar(left) and _is_numeric_scalar(right):
        return None
    if _is_numeric_scalar(left) and isinstance(right.type_name, VectorType):
        return _scale_vector(right, left)
    if _is_numeric_scalar(right) and isinstance(left.type_name, VectorType):
        return _scale_vector(left, right)
    if _is_numeric_scalar(left) and isinstance(right.type_name, TransposeVectorType):
        vector = _scale_vector(right.value, left)
        return AetherValue(TransposeVectorType(vector.type_name.element_type, len(vector.value)), vector)
    if _is_numeric_scalar(right) and isinstance(left.type_name, TransposeVectorType):
        vector = _scale_vector(left.value, right)
        return AetherValue(TransposeVectorType(vector.type_name.element_type, len(vector.value)), vector)
    if isinstance(left.type_name, VectorType) and isinstance(right.type_name, VectorType):
        raise AetherTypeError("Operator '*' between Vector and Vector is ambiguous; use transpose(v) * w for dot product, v * transpose(w) for outer product, or v .* w for elementwise multiplication.")
    if isinstance(left.type_name, MatrixType) and isinstance(right.type_name, MatrixType):
        return _matrix_multiply(left, right)
    if isinstance(left.type_name, MatrixType) and isinstance(right.type_name, VectorType):
        return _matrix_vector_multiply(left, right)
    if isinstance(left.type_name, TransposeVectorType) and isinstance(right.type_name, VectorType):
        return _dot_product(left.value, right)
    if isinstance(left.type_name, VectorType) and isinstance(right.type_name, TransposeVectorType):
        return _outer_product(left, right.value)
    return None


def _evaluate_elementwise_binary(
    left: AetherValue,
    operator: str,
    right: AetherValue,
    label: str,
) -> AetherValue:
    if _is_numeric_scalar(left) and _is_numeric_scalar(right):
        return _apply_array_element_operator(left, operator, right, promote_numeric(left.type_name, right.type_name, operator))
    if _is_numeric_scalar(left) and isinstance(right.type_name, VectorType):
        return _map_vector_scalar(right, left, operator, label, scalar_on_left=True)
    if _is_numeric_scalar(right) and isinstance(left.type_name, VectorType):
        return _map_vector_scalar(left, right, operator, label, scalar_on_left=False)
    if _is_numeric_scalar(left) and isinstance(right.type_name, TransposeVectorType):
        vector = _map_vector_scalar(right.value, left, operator, label, scalar_on_left=True)
        return AetherValue(TransposeVectorType(vector.type_name.element_type, len(vector.value)), vector)
    if _is_numeric_scalar(right) and isinstance(left.type_name, TransposeVectorType):
        vector = _map_vector_scalar(left.value, right, operator, label, scalar_on_left=False)
        return AetherValue(TransposeVectorType(vector.type_name.element_type, len(vector.value)), vector)
    if _is_numeric_scalar(left) and isinstance(right.type_name, MatrixType):
        return _map_matrix_scalar_elementwise(right, left, operator, scalar_on_left=True)
    if _is_numeric_scalar(right) and isinstance(left.type_name, MatrixType):
        return _map_matrix_scalar_elementwise(left, right, operator, scalar_on_left=False)
    if isinstance(left.type_name, VectorType) and isinstance(right.type_name, VectorType):
        return _elementwise_vector_vector(left, operator, right, label)
    if isinstance(left.type_name, TransposeVectorType) and isinstance(right.type_name, TransposeVectorType):
        vector = _elementwise_vector_vector(left.value, operator, right.value, label)
        return AetherValue(TransposeVectorType(vector.type_name.element_type, len(vector.value)), vector)
    if isinstance(left.type_name, MatrixType) and isinstance(right.type_name, MatrixType):
        left_rows, left_cols = _matrix_shape(left)
        right_rows, right_cols = _matrix_shape(right)
        if left_rows != right_rows or left_cols != right_cols:
            raise AetherRuntimeError(
                f"Matrix operands for '{label}' must have the same shape, got {left_rows}x{left_cols} and {right_rows}x{right_cols}."
            )
        left_element_type = _numeric_matrix_scalar_type(left.type_name)
        right_element_type = _numeric_matrix_scalar_type(right.type_name)
        result_element_type = promote_numeric(left_element_type, right_element_type, operator)
        return AetherValue(
            MatrixType(result_element_type, left_rows, left_cols),
            _map_matrix_matrix(left, right, operator, result_element_type),
        )
    raise AetherTypeError(
        f"Operator '{label}' is not defined for '{type_to_string(left.type_name)}' and '{type_to_string(right.type_name)}'."
    )


def _is_numeric_scalar(value: AetherValue) -> bool:
    return value.type_name in NUMERIC_TYPES


def _scale_vector(vector: AetherValue, scalar: AetherValue) -> AetherValue:
    if not isinstance(vector.type_name, VectorType) or scalar.type_name not in NUMERIC_TYPES:
        raise AetherTypeError("Vector scaling requires a numeric scalar and a numeric vector.")
    if vector.type_name.element_type not in NUMERIC_TYPES:
        raise AetherTypeError("Vector operations require numeric elements.")
    result_element_type = promote_numeric(vector.type_name.element_type, scalar.type_name, "*")
    return AetherValue(
        VectorType(result_element_type, len(vector.value)),
        [
            _apply_array_element_operator(element, "*", scalar, result_element_type)
            for element in vector.value
        ],
    )


def _map_vector_scalar(
    vector: AetherValue,
    scalar: AetherValue,
    operator: str,
    label: str,
    *,
    scalar_on_left: bool,
) -> AetherValue:
    if not isinstance(vector.type_name, VectorType) or scalar.type_name not in NUMERIC_TYPES:
        raise AetherTypeError(f"Operator '{label}' requires a vector and a numeric scalar.")
    vector_element_type = _numeric_vector_scalar_type(vector.type_name)
    result_element_type = promote_numeric(vector_element_type, scalar.type_name, operator)
    return AetherValue(
        VectorType(result_element_type, len(vector.value)),
        [
            _apply_array_element_operator(
                scalar if scalar_on_left else element,
                operator,
                element if scalar_on_left else scalar,
                result_element_type,
            )
            for element in vector.value
        ],
    )


def _map_matrix_scalar_elementwise(
    matrix: AetherValue,
    scalar: AetherValue,
    operator: str,
    *,
    scalar_on_left: bool,
) -> AetherValue:
    if not isinstance(matrix.type_name, MatrixType) or scalar.type_name not in NUMERIC_TYPES:
        raise AetherTypeError("Matrix elementwise scalar operation requires a numeric scalar.")
    matrix_element_type = _numeric_matrix_scalar_type(matrix.type_name)
    result_element_type = promote_numeric(matrix_element_type, scalar.type_name, operator)
    row_type = ArrayType(result_element_type)
    rows = [
        AetherValue(
            row_type,
            [
                _apply_array_element_operator(
                    scalar if scalar_on_left else element,
                    operator,
                    element if scalar_on_left else scalar,
                    result_element_type,
                )
                for element in row.value
            ],
        )
        for row in matrix.value
    ]
    return AetherValue(MatrixType(result_element_type, matrix.type_name.rows, matrix.type_name.cols), rows)


def _elementwise_vector_vector(left: AetherValue, operator: str, right: AetherValue, label: str) -> AetherValue:
    if len(left.value) != len(right.value):
        raise AetherRuntimeError(f"Vector operands for '{label}' must have the same length, got {len(left.value)} and {len(right.value)}.")
    left_element_type = _numeric_vector_scalar_type(left.type_name)
    right_element_type = _numeric_vector_scalar_type(right.type_name)
    result_element_type = promote_numeric(left_element_type, right_element_type, operator)
    return AetherValue(
        VectorType(result_element_type, len(left.value)),
        [
            _apply_array_element_operator(left_element, operator, right_element, result_element_type)
            for left_element, right_element in zip(left.value, right.value)
        ],
    )


def _matrix_multiply(left: AetherValue, right: AetherValue) -> AetherValue:
    left_rows, left_cols = _matrix_shape(left)
    right_rows, right_cols = _matrix_shape(right)
    if left_cols != right_rows:
        raise AetherTypeError(f"Operator '*' requires compatible matrix shapes, got {left_rows}x{left_cols} and {right_rows}x{right_cols}.")
    left_element_type = _numeric_matrix_scalar_type(left.type_name)
    right_element_type = _numeric_matrix_scalar_type(right.type_name)
    result_element_type = promote_numeric(left_element_type, right_element_type, "*")
    row_type = ArrayType(result_element_type)
    result_rows: list[AetherValue] = []
    for row_index in range(left_rows):
        result_elements: list[AetherValue] = []
        for col_index in range(right_cols):
            total = 0
            for inner_index in range(left_cols):
                total += left.value[row_index].value[inner_index].value * right.value[inner_index].value[col_index].value
            result_elements.append(_coerced_numeric_result(total, result_element_type))
        result_rows.append(AetherValue(row_type, result_elements))
    return AetherValue(MatrixType(result_element_type, left_rows, right_cols), result_rows)


def _matrix_vector_multiply(matrix: AetherValue, vector: AetherValue) -> AetherValue:
    rows, cols = _matrix_shape(matrix)
    if cols != len(vector.value):
        raise AetherTypeError(f"Operator '*' requires compatible Matrix and Vector shapes, got {rows}x{cols} and {len(vector.value)}.")
    matrix_element_type = _numeric_matrix_scalar_type(matrix.type_name)
    vector_element_type = _numeric_vector_scalar_type(vector.type_name)
    result_element_type = promote_numeric(matrix_element_type, vector_element_type, "*")
    result: list[AetherValue] = []
    for row_index in range(rows):
        total = 0
        for col_index in range(cols):
            total += matrix.value[row_index].value[col_index].value * vector.value[col_index].value
        result.append(_coerced_numeric_result(total, result_element_type))
    return AetherValue(VectorType(result_element_type, len(result)), result)


def _dot_product(left_transpose: AetherValue, right: AetherValue) -> AetherValue:
    left = left_transpose
    if len(left.value) != len(right.value):
        raise AetherTypeError(f"Operator '*' requires vectors with the same length for dot product, got {len(left.value)} and {len(right.value)}.")
    left_element_type = _numeric_vector_scalar_type(left.type_name)
    right_element_type = _numeric_vector_scalar_type(right.type_name)
    result_element_type = promote_numeric(left_element_type, right_element_type, "*")
    total = sum(left_element.value * right_element.value for left_element, right_element in zip(left.value, right.value))
    return _coerced_numeric_result(total, result_element_type)


def _outer_product(left: AetherValue, right_transpose: AetherValue) -> AetherValue:
    left_element_type = _numeric_vector_scalar_type(left.type_name)
    right_element_type = _numeric_vector_scalar_type(right_transpose.type_name)
    result_element_type = promote_numeric(left_element_type, right_element_type, "*")
    row_type = ArrayType(result_element_type)
    rows = [
        AetherValue(
            row_type,
            [
                _coerced_numeric_result(left_element.value * right_element.value, result_element_type)
                for right_element in right_transpose.value
            ],
        )
        for left_element in left.value
    ]
    return AetherValue(MatrixType(result_element_type, len(left.value), len(right_transpose.value)), rows)


def _matrix_shape(value: AetherValue) -> tuple[int, int]:
    return len(value.value), len(value.value[0].value) if value.value else 0


def _numeric_vector_scalar_type(vector_type: AetherType) -> str:
    if not isinstance(vector_type, VectorType):
        raise AetherTypeError(f"Expected vector type, got '{type_to_string(vector_type)}'.")
    if vector_type.element_type not in NUMERIC_TYPES:
        raise AetherTypeError("Vector operations require numeric elements.")
    return vector_type.element_type


def _coerced_numeric_result(value: object, result_type: str) -> AetherValue:
    if result_type == "int":
        return AetherValue("int", int(value))  # type: ignore[arg-type]
    return AetherValue(result_type, float(value))  # type: ignore[arg-type]


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
    elif operator == "*":
        result = left.value * right.value
    else:
        raise AetherRuntimeError(f"Unsupported array operator '{operator}'.")
    if result_element_type == "int":
        result = int(result)
    else:
        result = float(result)
    return AetherValue(result_element_type, result)


def _values_equal(left: AetherValue, right: AetherValue) -> bool:
    if isinstance(left.type_name, VectorType) and isinstance(right.type_name, VectorType):
        if len(left.value) != len(right.value):
            return False
        return all(
            _values_equal(left_element, right_element)
            for left_element, right_element in zip(left.value, right.value)
        )
    if isinstance(left.type_name, TransposeVectorType) and isinstance(right.type_name, TransposeVectorType):
        return _values_equal(left.value, right.value)
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
