from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from math import trunc
import os
from pathlib import Path
import sys

from plot_backend import PlotBackend

from . import ast
from .errors import AetherError, AetherInputError, AetherRuntimeError, AetherSyntaxError, AetherTypeError
from .formatting import format_value
from .integer_arithmetic import checked_int_binary, checked_int_negate, ieee_divide
from .lexer import lex
from .modules import is_public_export, private_top_level_names, resolve_file_module_path
from .native_members import native_member_set, native_method, native_property
from .parser import Parser
from .scope import Scope
from .stdlib import BuiltinFunction, is_builtin, is_builtin_constant, is_builtin_namespace, make_builtins
from .stdlib.math.linear_algebra import matmul_builtin
from .stdlib.registry import get_builtin_constant
from .tokens import AETHER_TYPES, PRIMITIVE_TYPES
from .types import (
    AetherType,
    AetherExceptionValue,
    ClassInstance,
    ClassType,
    EnumIdentity,
    EnumType,
    EnumValue,
    FunctionType,
    InterfaceType,
    AetherRange,
    AetherValue,
    ArrayType,
    ListType,
    MatrixType,
    NUMERIC_TYPES,
    REAL_NUMERIC_TYPES,
    NullType,
    NullableType,
    RangeType,
    StructInstance,
    TupleType,
    VOID_VALUE,
    TransposeVectorType,
    VectorType,
    array_element_type,
    coerce_array_literal_value,
    coerce_implicit,
    coerce_list_value,
    coerce_matrix_value,
    coerce_return_value,
    coerce_vector_value,
    contains_struct_value,
    copy_value,
    is_array_type,
    is_indexable_type,
    is_list_type,
    is_matrix_type,
    is_vector_like_type,
    list_element_type,
    matrix_row_type,
    promote_numeric,
    type_to_string,
)
from .vector_matrix_safety import (
    MATRIX_INDEX_OUT_OF_BOUNDS,
    VECTOR_INDEX_OUT_OF_BOUNDS,
    checked_matrix_offset,
    checked_vector_offset,
)


LINEAR_ALGEBRA_MODULE = "Math.LinearAlgebra"
LINEAR_ALGEBRA_SOLVE = "Math.LinearAlgebra.solve"
LINEAR_ALGEBRA_CONJTRANSPOSE = "Math.LinearAlgebra.conjtranspose"


@dataclass
class Function:
    declaration: ast.FunctionDeclaration | ast.ExpressionFunctionDeclaration
    closure: "Environment | None" = None
    builtin_aliases: dict[str, str] | None = None
    builtin_constant_aliases: dict[str, str] | None = None
    imported_modules: set[str] | None = None
    module_bindings: dict[str, str] | None = None
    qualified_values: dict[str, AetherValue] | None = None
    qualified_structs: dict[str, ast.StructDeclaration | ast.ClassDeclaration] | None = None
    qualified_enums: dict[str, ast.EnumDeclaration] | None = None
    type_aliases: dict[str, AetherType] | None = None
    structs: dict[str, ast.StructDeclaration] | None = None
    struct_methods: dict[str, dict[str, "Function"]] | None = None
    enums: dict[str, ast.EnumDeclaration] | None = None
    interfaces: dict[str, ast.InterfaceDeclaration] | None = None


@dataclass(frozen=True)
class FunctionReference:
    name: str
    signature: FunctionType
    function: Function
    interpreter: "Interpreter"
    environment: None = None

    @property
    def arity(self) -> int:
        return len(self.signature.parameter_types)

    def call(self, args: list[AetherValue]) -> AetherValue:
        return self.interpreter._call_function(self.name, self.function, args)


@dataclass(frozen=True)
class _PlotsFunctionReference:
    """Legacy AST-only adapter; it is intentionally not a typed callable value."""

    name: str
    arity: int
    callback: Callable[[list[AetherValue]], AetherValue]

    def call(self, args: list[AetherValue]) -> AetherValue:
        return self.callback(args)


@dataclass
class Environment:
    parent: "Environment | None" = None
    variable_scope: Scope[AetherValue] | None = None
    method_receiver: AetherValue | None = None

    def __post_init__(self) -> None:
        if self.variable_scope is None:
            parent_scope = self.parent.variable_scope if self.parent is not None else None
            self.variable_scope = Scope(parent=parent_scope)
        self.functions: dict[str, Function] = {}

    @property
    def values(self) -> dict[str, AetherValue]:
        return self.variable_scope.symbols

    def define(self, name: str, value: AetherValue, *, forbid_shadowing: bool = False, is_const: bool = False) -> None:
        if contains_struct_value(value):
            value = copy_value(value)
        self.variable_scope.define_local(name, value, forbid_shadowing=forbid_shadowing, is_const=is_const)

    def assign(self, name: str, value: AetherValue, *, array_literal_context: bool = False) -> None:
        scope = self.variable_scope.resolve_scope(name)
        if scope is None:
            if contains_struct_value(value):
                value = copy_value(value)
            self.variable_scope.define_local(name, value)
            return
        if scope.is_const(name):
            raise AetherTypeError(f"Cannot assign to constant '{name}'.")
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


class _BreakSignal(Exception):
    pass


class _ContinueSignal(Exception):
    pass


class _ThrownExceptionSignal(Exception):
    def __init__(self, value: AetherValue) -> None:
        self.value = value


class _FunctionContext:
    def __init__(self, interpreter: "Interpreter", function: Function) -> None:
        self.interpreter = interpreter
        self.function = function
        self.previous_builtin_aliases: dict[str, str] = {}
        self.previous_builtin_constant_aliases: dict[str, str] = {}
        self.previous_imported_modules: set[str] = set()
        self.previous_module_bindings: dict[str, str] = {}
        self.previous_qualified_values: dict[str, AetherValue] = {}
        self.previous_qualified_structs: dict[str, ast.StructDeclaration | ast.ClassDeclaration] = {}
        self.previous_qualified_enums: dict[str, ast.EnumDeclaration] = {}
        self.previous_type_aliases: dict[str, AetherType] = {}
        self.previous_structs: dict[str, ast.StructDeclaration] = {}
        self.previous_struct_methods: dict[str, dict[str, Function]] = {}
        self.previous_enums: dict[str, ast.EnumDeclaration] = {}
        self.previous_interfaces: dict[str, ast.InterfaceDeclaration] = {}

    def __enter__(self) -> None:
        self.previous_builtin_aliases = self.interpreter.builtin_aliases
        self.previous_builtin_constant_aliases = self.interpreter.builtin_constant_aliases
        self.previous_imported_modules = self.interpreter.imported_modules
        self.previous_module_bindings = self.interpreter.module_bindings
        self.previous_qualified_values = self.interpreter.qualified_values
        self.previous_qualified_structs = self.interpreter.qualified_structs
        self.previous_qualified_enums = self.interpreter.qualified_enums
        self.previous_type_aliases = self.interpreter.type_aliases
        self.previous_structs = self.interpreter.structs
        self.previous_struct_methods = self.interpreter.struct_methods
        self.previous_enums = self.interpreter.enums
        self.previous_interfaces = self.interpreter.interfaces
        self.interpreter.builtin_aliases = {
            **self.previous_builtin_aliases,
            **(self.function.builtin_aliases or {}),
        }
        self.interpreter.builtin_constant_aliases = {
            **self.previous_builtin_constant_aliases,
            **(self.function.builtin_constant_aliases or {}),
        }
        self.interpreter.imported_modules = {
            *self.previous_imported_modules,
            *(self.function.imported_modules or set()),
        }
        self.interpreter.module_bindings = {
            **self.previous_module_bindings,
            **(self.function.module_bindings or {}),
        }
        self.interpreter.qualified_values = {
            **self.previous_qualified_values,
            **(self.function.qualified_values or {}),
        }
        self.interpreter.qualified_structs = {
            **self.previous_qualified_structs,
            **(self.function.qualified_structs or {}),
        }
        self.interpreter.qualified_enums = {
            **self.previous_qualified_enums,
            **(self.function.qualified_enums or {}),
        }
        self.interpreter.type_aliases = {
            **self.previous_type_aliases,
            **(self.function.type_aliases or {}),
        }
        self.interpreter.structs = {
            **self.previous_structs,
            **(self.function.structs or {}),
        }
        self.interpreter.struct_methods = {
            **self.previous_struct_methods,
            **(self.function.struct_methods or {}),
        }
        self.interpreter.enums = {
            **self.previous_enums,
            **(self.function.enums or {}),
        }
        self.interpreter.interfaces = {
            **self.previous_interfaces,
            **(self.function.interfaces or {}),
        }

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.interpreter.builtin_aliases = self.previous_builtin_aliases
        self.interpreter.builtin_constant_aliases = self.previous_builtin_constant_aliases
        self.interpreter.imported_modules = self.previous_imported_modules
        self.interpreter.module_bindings = self.previous_module_bindings
        self.interpreter.qualified_values = self.previous_qualified_values
        self.interpreter.qualified_structs = self.previous_qualified_structs
        self.interpreter.qualified_enums = self.previous_qualified_enums
        self.interpreter.type_aliases = self.previous_type_aliases
        self.interpreter.structs = self.previous_structs
        self.interpreter.struct_methods = self.previous_struct_methods
        self.interpreter.enums = self.previous_enums
        self.interpreter.interfaces = self.previous_interfaces


class Interpreter:
    def __init__(
        self,
        *,
        source_root: str | Path | None = None,
        import_stack: tuple[str, ...] = (),
        plot_mode: str | None = None,
        plot_output_dir: str | Path | None = None,
        output_writer: Callable[[str], None] | None = None,
        input_reader: Callable[[], str] | None = None,
    ) -> None:
        self.global_env = Environment()
        self.output_parts: list[str] = []
        self.output_writer = output_writer
        self._uses_default_input_reader = input_reader is None
        self.input_reader = input_reader or sys.stdin.readline
        self.plot_backend = PlotBackend(
            plot_mode=_default_plot_mode(plot_mode),
            output_dir=_default_plot_output_dir(plot_output_dir),
        )
        self.builtins: dict[str, BuiltinFunction] = make_builtins(
            self._write_output,
            plot_backend=self.plot_backend,
        )
        self.builtin_aliases: dict[str, str] = {}
        self.builtin_constant_aliases: dict[str, str] = {}
        self.imported_modules: set[str] = set()
        self.module_bindings: dict[str, str] = {}
        self.qualified_values: dict[str, AetherValue] = {}
        self.qualified_structs: dict[str, ast.StructDeclaration | ast.ClassDeclaration] = {}
        self.qualified_enums: dict[str, ast.EnumDeclaration] = {}
        self._loaded_file_modules: dict[str, tuple[ast.Program, "Interpreter"]] = {}
        self.type_aliases: dict[str, AetherType] = {}
        self.structs: dict[str, ast.StructDeclaration] = {}
        self.struct_methods: dict[str, dict[str, Function]] = {}
        self.enums: dict[str, ast.EnumDeclaration] = {}
        self._enum_identity_by_declaration_id: dict[int, EnumIdentity] = {}
        self._module_identity = import_stack[-1] if import_stack else "__entry__"
        self.interfaces: dict[str, ast.InterfaceDeclaration] = {}
        self.source_root = Path(source_root).expanduser().resolve() if source_root is not None else Path.cwd()
        self.import_stack = import_stack
        self.imported_symbol_origins: dict[str, str] = {}
        self.private_imported_symbols: dict[str, set[str]] = {}
        self._interpret_depth = 0
        self.current_return_type: AetherType | None = None
        self.last_exit_code = 0

    def interpret(self, program: ast.Program) -> Environment:
        self._module_identity = program.package_name or (self.import_stack[-1] if self.import_stack else "__entry__")
        self._interpret_depth += 1
        self.last_exit_code = 0
        try:
            for statement in program.statements:
                if isinstance(statement, ast.ImportStatement):
                    self._import_module_statement(statement)
                elif isinstance(statement, ast.FromImportStatement):
                    self._from_import(statement)
            for statement in program.statements:
                self._execute(statement, self.global_env)
            if program.entry_point is not None:
                self.last_exit_code = self._invoke_entry_point(program.entry_point)
            return self.global_env
        except _ThrownExceptionSignal as signal:
            raise self._runtime_error_from_thrown(signal.value) from None
        finally:
            self._interpret_depth -= 1
            if self._interpret_depth == 0:
                self.plot_backend.wait_for_interactive_plots()

    def _invoke_entry_point(self, name: str) -> int:
        function = self.global_env.get_function(name)
        if function is None or not isinstance(function.declaration, ast.FunctionDeclaration):
            raise AetherRuntimeError(f"Program entry point '{name}' is not defined.")
        declaration = function.declaration
        if declaration.synthetic:
            result = self._execute_synthetic_entry(declaration)
        else:
            result = self._call_user_function(name, [], self.global_env)
        if result.type_name != "int" or isinstance(result.value, bool):
            raise AetherRuntimeError("Program entry point 'main' did not return int.")
        return int(result.value)

    def _execute_synthetic_entry(self, declaration: ast.FunctionDeclaration) -> AetherValue:
        previous_return_type = self.current_return_type
        self.current_return_type = "int"
        try:
            try:
                # Script variables intentionally remain in the session/global
                # environment, preserving the existing REPL and IDE workspace UX.
                self._execute_block(declaration.body, self.global_env)
            except _ReturnSignal as signal:
                return coerce_return_value(signal.value, "int")
        finally:
            self.current_return_type = previous_return_type
        raise AetherRuntimeError("Synthetic program entry point ended without returning a value.")

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
            declared_type = self._resolve_type_aliases(statement.type_name) if statement.type_name is not None else None
            if isinstance(statement.initializer, ast.MatrixLiteral):
                if not statement.initializer.rows and declared_type is not None and is_array_type(declared_type):
                    env.define(
                        statement.name,
                        AetherValue(declared_type, []),
                        forbid_shadowing=True,
                        is_const=statement.is_const,
                    )
                    return
                value = self._evaluate_matrix_literal(
                    statement.initializer,
                    env,
                    declared_type if isinstance(declared_type, (MatrixType, VectorType)) else None,
                )
                if declared_type is None:
                    env.define(statement.name, value, forbid_shadowing=True, is_const=statement.is_const)
                    return
                env.define(
                    statement.name,
                    coerce_implicit(value, declared_type),
                    forbid_shadowing=True,
                    is_const=statement.is_const,
                )
                return
            if isinstance(statement.initializer, ast.ArrayLiteral):
                value = self._evaluate_array_literal(
                    statement.initializer,
                    env,
                    declared_type if declared_type is not None and is_array_type(declared_type) else None,
                )
                if declared_type is None:
                    env.define(statement.name, value, forbid_shadowing=True, is_const=statement.is_const)
                    return
                coerced = coerce_array_literal_value(value, declared_type) if is_array_type(declared_type) else coerce_implicit(value, declared_type)
                env.define(statement.name, coerced, forbid_shadowing=True, is_const=statement.is_const)
                return
            if isinstance(statement.initializer, ast.ListLiteral):
                if declared_type is not None and is_array_type(declared_type):
                    value = self._evaluate_braced_array_literal(statement.initializer, env, declared_type)
                    env.define(statement.name, value, forbid_shadowing=True, is_const=statement.is_const)
                    return
                value = self._evaluate_list_literal(
                    statement.initializer,
                    env,
                    declared_type if declared_type is not None and is_list_type(declared_type) else None,
                )
                if declared_type is None:
                    env.define(statement.name, value, forbid_shadowing=True, is_const=statement.is_const)
                    return
                coerced = coerce_list_value(value, declared_type) if is_list_type(declared_type) else coerce_implicit(value, declared_type)
                env.define(statement.name, coerced, forbid_shadowing=True, is_const=statement.is_const)
                return
            if declared_type is None:
                env.define(
                    statement.name,
                    self._evaluate(statement.initializer, env),
                    forbid_shadowing=True,
                    is_const=statement.is_const,
                )
                return
            value = self._evaluate_with_expected_type(statement.initializer, env, declared_type)
            if (
                declared_type == "float"
                and isinstance(statement.initializer, ast.Literal)
                and value.type_name == "double"
            ):
                env.define(
                    statement.name,
                    AetherValue("float", float(value.value)),
                    forbid_shadowing=True,
                    is_const=statement.is_const,
                )
                return
            env.define(
                statement.name,
                coerce_implicit(value, declared_type),
                forbid_shadowing=True,
                is_const=statement.is_const,
            )
            return
        if isinstance(statement, ast.AliasDeclaration):
            self.type_aliases[statement.name] = statement.target_type
            return
        if isinstance(statement, (ast.StructDeclaration, ast.ClassDeclaration)):
            self.structs[statement.name] = statement
            self.struct_methods[statement.name] = {
                method.name: self._function(method, env)
                for method in statement.methods
            }
            return
        if isinstance(statement, ast.InterfaceDeclaration):
            self.interfaces[statement.name] = statement
            return
        if isinstance(statement, ast.EnumDeclaration):
            self.enums[statement.name] = statement
            self._enum_identity_by_declaration_id[id(statement)] = EnumIdentity(
                self._module_identity,
                statement.name,
            )
            return
        if isinstance(statement, ast.Assignment):
            if isinstance(statement.name, ast.MatrixIndexExpression):
                self._assign_matrix_index(
                    ast.MatrixIndexAssignment(
                        statement.name.matrix,
                        statement.name.row,
                        statement.name.column,
                        statement.expression,
                        statement.line,
                        statement.column,
                    ),
                    env,
                )
                return
            if isinstance(statement.name, ast.IndexExpression):
                self._assign_index(
                    ast.IndexAssignment(
                        statement.name.array,
                        statement.name.index,
                        statement.expression,
                        statement.line,
                        statement.column,
                    ),
                    env,
                )
                return
            implicit_field = self._implicit_method_field(statement.name, env)
            if implicit_field is not None:
                self._assign_implicit_method_field(statement.name, statement.expression, env)
                return
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
            if isinstance(statement.expression, ast.ListLiteral) and current is not None and (
                is_list_type(current.type_name) or is_array_type(current.type_name)
            ):
                value = (
                    self._evaluate_braced_array_literal(statement.expression, env, current.type_name)
                    if is_array_type(current.type_name)
                    else self._evaluate_list_literal(statement.expression, env, current.type_name)
                )
                env.assign(statement.name, value)
                return
            if current is not None:
                env.assign(statement.name, self._evaluate_with_expected_type(statement.expression, env, current.type_name))
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
        if isinstance(statement, ast.FieldAssignment):
            self._assign_field(statement, env)
            return
        if isinstance(statement, ast.ExpressionStatement):
            self._evaluate(statement.expression, env)
            return
        if isinstance(statement, ast.ImportStatement):
            return
        if isinstance(statement, ast.FromImportStatement):
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
                try:
                    self._execute_block(statement.body, Environment(parent=env))
                except _ContinueSignal:
                    continue
                except _BreakSignal:
                    break
            return
        if isinstance(statement, ast.ForInStatement):
            iterable = self._evaluate(statement.iterable, env)
            for item in _iterable_values(iterable):
                loop_env = Environment(parent=env)
                loop_env.define(statement.variable, item, forbid_shadowing=True)
                try:
                    self._execute_block(statement.body, loop_env)
                except _ContinueSignal:
                    continue
                except _BreakSignal:
                    break
            return
        if isinstance(statement, ast.FunctionDeclaration):
            env.define_function(self._function(statement, env))
            return
        if isinstance(statement, ast.ExpressionFunctionDeclaration):
            env.define_function(self._function(statement, env))
            return
        if isinstance(statement, ast.ReturnStatement):
            value = AetherValue("void", VOID_VALUE)
            if statement.expression is not None:
                if self.current_return_type is not None and self.current_return_type != "void":
                    value = self._evaluate_with_expected_type(statement.expression, env, self.current_return_type)
                else:
                    value = self._evaluate(statement.expression, env)
            raise _ReturnSignal(value)
        if isinstance(statement, ast.BreakStatement):
            raise _BreakSignal()
        if isinstance(statement, ast.ContinueStatement):
            raise _ContinueSignal()
        if isinstance(statement, ast.ThrowStatement):
            raise _ThrownExceptionSignal(self._exception_from_value(self._evaluate(statement.expression, env), statement))
        if isinstance(statement, ast.TryCatchStatement):
            try:
                self._execute_block(statement.try_body, Environment(parent=env))
            except _ThrownExceptionSignal as signal:
                catch_env = Environment(parent=env)
                catch_env.define(statement.catch_name, signal.value, forbid_shadowing=True)
                self._execute_block(statement.catch_body, catch_env)
            return
        raise AetherRuntimeError(f"Unsupported statement {statement!r}.")

    def _execute_block(self, statements: list[ast.Statement], env: Environment) -> None:
        for statement in statements:
            self._execute(statement, env)

    def _function(
        self,
        declaration: ast.FunctionDeclaration | ast.ExpressionFunctionDeclaration,
        env: Environment,
    ) -> Function:
        return Function(
            declaration,
            env,
            dict(self.builtin_aliases),
            dict(self.builtin_constant_aliases),
            set(self.imported_modules),
            dict(self.module_bindings),
            dict(self.qualified_values),
            dict(self.qualified_structs),
            dict(self.qualified_enums),
            dict(self.type_aliases),
            dict(self.structs),
            {name: dict(methods) for name, methods in self.struct_methods.items()},
            dict(self.enums),
            dict(self.interfaces),
        )

    def _evaluate(self, expression: ast.Expression, env: Environment) -> AetherValue:
        if isinstance(expression, ast.Literal):
            return AetherValue(expression.type_name, expression.value)
        if isinstance(expression, ast.InterpolatedString):
            return AetherValue("string", self._interpolate_string(expression, env))
        if isinstance(expression, ast.Identifier):
            if expression.name == "this":
                receiver = self._method_receiver_value(env)
                if receiver is not None:
                    return receiver
            try:
                return env.get(expression.name)
            except AetherRuntimeError as exc:
                if env.get_function(expression.name) is not None:
                    return self._function_reference_value(expression.name, env)
                field_value = self._implicit_method_field(expression.name, env)
                if field_value is not None:
                    return field_value
                builtin_constant = get_builtin_constant(self.builtin_constant_aliases.get(expression.name, expression.name))
                if builtin_constant is not None:
                    return builtin_constant
                raise _with_source_location(exc, expression) from exc
        if isinstance(expression, ast.UnaryExpression):
            operand = self._evaluate(expression.operand, env)
            try:
                if expression.operator == "-":
                    return _negate_value(operand)
                if expression.operator == "'":
                    if LINEAR_ALGEBRA_MODULE not in self.imported_modules:
                        raise AetherRuntimeError("Operator \"'\" requires import Math.LinearAlgebra.", kind="import")
                    return self.builtins[LINEAR_ALGEBRA_CONJTRANSPOSE]([operand])
                if expression.operator == "!":
                    if operand.type_name != "boolean" or not isinstance(operand.value, bool):
                        raise AetherRuntimeError(
                            "Unary operator '!' requires a boolean operand."
                        )
                    return AetherValue("boolean", not operand.value)
                raise AetherRuntimeError(f"Unsupported unary operator '{expression.operator}'.")
            except AetherError as exc:
                raise _with_source_location(exc, expression) from exc
        if isinstance(expression, ast.BinaryExpression):
            if expression.operator in {"&&", "||"}:
                try:
                    return self._evaluate_logical(expression, env)
                except AetherError as exc:
                    raise _with_source_location(exc, expression) from exc
            left = self._evaluate(expression.left, env)
            right = self._evaluate(expression.right, env)
            try:
                return self._evaluate_binary(left, expression.operator, right)
            except AetherError as exc:
                raise _with_source_location(exc, expression) from exc
        if isinstance(expression, ast.RangeExpression):
            return self._evaluate_range(expression, env)
        if isinstance(expression, ast.CallExpression):
            try:
                return self._evaluate_call(expression, env)
            except AetherError as exc:
                raise _with_source_location(exc, expression) from exc
        if isinstance(expression, ast.MethodCall):
            try:
                return self._evaluate_method_call(expression, env)
            except AetherError as exc:
                raise _with_source_location(exc, expression) from exc
        if isinstance(expression, ast.InputCall):
            raise AetherInputError(
                "input() requires a typed assignment context.",
                line=expression.line,
                column=expression.column,
                hint="assign input() to a variable with an explicit or existing type.",
                kind="input",
            )
        if isinstance(expression, ast.ArrayLiteral):
            return self._evaluate_array_literal(expression, env)
        if isinstance(expression, ast.ListLiteral):
            return self._evaluate_list_literal(expression, env)
        if isinstance(expression, ast.TupleLiteral):
            return self._evaluate_tuple_literal(expression, env)
        if isinstance(expression, ast.MatrixLiteral):
            return self._evaluate_matrix_literal(expression, env)
        if isinstance(expression, ast.IndexExpression):
            try:
                return self._read_index(expression.array, expression.index, env)
            except AetherError as exc:
                raise _with_source_location(exc, expression) from exc
        if isinstance(expression, ast.SliceExpression):
            try:
                return self._read_array_slice(expression, env)
            except AetherError as exc:
                raise _with_source_location(exc, expression) from exc
        if isinstance(expression, ast.MatrixIndexExpression):
            try:
                return self._read_matrix_index(expression.matrix, expression.row, expression.column, env)
            except AetherError as exc:
                raise _with_source_location(exc, expression) from exc
        if isinstance(expression, ast.FieldAccess):
            constant_name = _field_access_path(expression)
            constant_root = _field_access_root_name(expression)
            canonical_member = self._resolve_module_member(constant_name) if constant_name is not None else None
            if canonical_member is not None:
                if env.get_function(canonical_member) is not None:
                    return self._function_reference_value(canonical_member, env)
                value = self.qualified_values.get(canonical_member)
                if value is not None:
                    return value
                enum_name, _, variant_name = canonical_member.rpartition(".")
                enum_declaration = self.qualified_enums.get(enum_name)
                if enum_declaration is not None:
                    if variant_name not in {variant.name for variant in enum_declaration.variants}:
                        raise AetherTypeError(
                            f"Enum '{enum_declaration.name}' has no variant '{variant_name}'.",
                            line=expression.line,
                            column=expression.column,
                        )
                    return AetherValue(
                        EnumType(
                            enum_declaration.name,
                            self._enum_identity(enum_declaration),
                        ),
                        self._make_enum_value(enum_declaration, variant_name),
                    )
                builtin_constant = get_builtin_constant(canonical_member)
                if builtin_constant is not None:
                    return builtin_constant
                raise AetherRuntimeError(
                    f"Module '{canonical_member.rsplit('.', 1)[0]}' has no exported symbol "
                    f"'{canonical_member.rsplit('.', 1)[1]}'.",
                    line=expression.line,
                    column=expression.column,
                    kind="import",
                )
            if isinstance(expression.target, ast.Identifier) and env.lookup(expression.target.name) is None:
                enum_value = self._enum_variant_value(expression.target.name, expression.field_name, expression)
                if enum_value is not None:
                    return enum_value
            if constant_name is not None and constant_root is not None and env.lookup(constant_root) is None:
                builtin_constant = get_builtin_constant(constant_name)
                if builtin_constant is not None:
                    return builtin_constant
            return self._read_field(expression.target, expression.field_name, env)
        raise AetherRuntimeError(f"Unsupported expression {expression!r}.")

    def _evaluate_with_expected_type(
        self,
        expression: ast.Expression,
        env: Environment,
        expected_type: AetherType,
    ) -> AetherValue:
        if isinstance(expression, ast.InputCall):
            return self._evaluate_input_call(expression, env, expected_type)
        if isinstance(expected_type, ArrayType) and isinstance(expression, (ast.ArrayLiteral, ast.ListLiteral)):
            return self._evaluate_braced_array_literal(expression, env, expected_type)
        if isinstance(expected_type, ListType) and isinstance(expression, ast.ListLiteral):
            return self._evaluate_list_literal(expression, env, expected_type)
        if isinstance(expected_type, (MatrixType, VectorType)) and isinstance(expression, ast.MatrixLiteral):
            return self._evaluate_matrix_literal(expression, env, expected_type)
        return self._evaluate(expression, env)

    def _evaluate_input_call(
        self,
        expression: ast.InputCall,
        env: Environment,
        expected_type: AetherType,
    ) -> AetherValue:
        if not _is_supported_input_target_type(expected_type):
            raise AetherInputError(
                f"input() supports int, float, string, boolean, Vector, and Matrix targets, got '{type_to_string(expected_type)}'.",
                line=expression.line,
                column=expression.column,
                hint="use input() only with a supported scalar, Vector<T>, or Matrix<T> target.",
                kind="input",
            )
        if len(expression.arguments) > 1:
            raise AetherTypeError("input(...) expects zero or one argument.", line=expression.line, column=expression.column, kind="arity")
        if expression.arguments:
            prompt = self._evaluate(expression.arguments[0], env)
            if prompt.type_name != "string":
                raise AetherTypeError(
                    f"input(...) prompt must be string, got '{type_to_string(prompt.type_name)}'.",
                    line=expression.line,
                    column=expression.column,
                    hint="wrap the prompt in quotes or build a string expression.",
                    kind="input",
                )
            self._write_prompt(str(prompt.value))
        raw = self.input_reader()
        if raw == "":
            raise AetherInputError("input() reached end of file.", line=expression.line, column=expression.column, kind="input")
        text = raw[:-1] if raw.endswith("\n") else raw
        if text.endswith("\r"):
            text = text[:-1]
        try:
            return self._convert_input_text(text, expected_type, env)
        except AetherInputError as exc:
            raise _with_source_location(exc, expression) from exc

    def _convert_input_text(self, text: str, target_type: AetherType, env: Environment) -> AetherValue:
        if isinstance(target_type, (VectorType, MatrixType)):
            return self._convert_matrix_input_text(text, target_type, env)
        return _convert_scalar_input_text(text, target_type)

    def _convert_matrix_input_text(
        self,
        text: str,
        target_type: VectorType | MatrixType,
        env: Environment,
    ) -> AetherValue:
        try:
            expression = Parser(lex(text.strip())).parse_expression()
            if not isinstance(expression, ast.MatrixLiteral):
                raise AetherTypeError("expected a vector or matrix literal")
            return self._evaluate_matrix_literal(expression, env, target_type)
        except (AetherSyntaxError, AetherTypeError, AetherRuntimeError) as exc:
            raise AetherInputError(
                f'cannot convert "{text}" to {type_to_string(target_type)}: {_raw_error_message(exc)}',
                hint="enter a bracket literal such as [1, 2, 3] for Vector<T> or [1 2; 3 4] for Matrix<T>.",
                kind="input",
            ) from exc

    def _write_prompt(self, prompt: str) -> None:
        if self.output_writer is None and self._uses_default_input_reader:
            print(prompt, end="", flush=True)
            return
        self._write_output(prompt)

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

    def _evaluate_braced_array_literal(
        self,
        expression: ast.ArrayLiteral | ast.ListLiteral,
        env: Environment,
        target_type: ArrayType,
    ) -> AetherValue:
        target_element_type = target_type.element_type
        elements: list[AetherValue] = []
        for element in expression.elements:
            if isinstance(target_element_type, ArrayType) and isinstance(element, (ast.ArrayLiteral, ast.ListLiteral)):
                elements.append(self._evaluate_braced_array_literal(element, env, target_element_type))
                continue
            elements.append(self._evaluate(element, env))
        return coerce_array_literal_value(AetherValue(target_type, elements), target_type)

    def _evaluate_list_literal(
        self,
        expression: ast.ListLiteral,
        env: Environment,
        target_type: AetherType | None = None,
    ) -> AetherValue:
        elements = [self._evaluate(element, env) for element in expression.elements]
        if target_type is not None and is_list_type(target_type):
            value = (
                AetherValue(target_type, elements)
                if not elements
                else AetherValue(_list_type_from_values(elements), elements)
            )
            return coerce_list_value(value, target_type)
        if not elements:
            raise AetherTypeError("Cannot infer type of empty list literal.")
        inferred_type = _list_type_from_values(elements)
        return coerce_list_value(AetherValue(inferred_type, elements), inferred_type)

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
            orientation = expression.orientation
            if (
                isinstance(target_type, VectorType)
                and target_type.orientation == "column"
                and len(expression.rows) == 1
                and expression.uses_commas
            ):
                orientation = "column"
            value = AetherValue(VectorType(element_type, len(vector_elements), orientation), vector_elements)
            if isinstance(target_type, VectorType):
                return coerce_vector_value(value, target_type)
            if isinstance(target_type, MatrixType):
                legacy_rows = [AetherValue(row_type, [element]) for element in vector_elements]
                legacy_value = AetherValue(MatrixType(element_type, len(legacy_rows), 1, vector=True), legacy_rows)
                return coerce_matrix_value(legacy_value, target_type)
            return value
        if len(rows) == 1:
            value = AetherValue(VectorType(element_type, row_lengths[0], "row"), list(rows[0].value))
            if isinstance(target_type, VectorType):
                return coerce_vector_value(value, target_type)
            if isinstance(target_type, MatrixType):
                return coerce_matrix_value(_vector_to_matrix_value(value), target_type)
            return value
        if all(length == 1 for length in row_lengths):
            value = AetherValue(VectorType(element_type, len(rows), "column"), [row.value[0] for row in rows])
            if isinstance(target_type, VectorType):
                return coerce_vector_value(value, target_type)
            if isinstance(target_type, MatrixType):
                return coerce_matrix_value(_vector_to_matrix_value(value), target_type)
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
            if isinstance(array_value.type_name, ListType):
                return self._read_list_slice(array_value, index_expression, env)
            return self._read_vector_slice(array_value, index_expression, env)
        index_value = self._evaluate(index_expression, env)
        index = self._require_index(array_value, index_value)
        if isinstance(array_value.type_name, (VectorType, TransposeVectorType)):
            return _vector_elements(array_value)[index]
        if isinstance(array_value.type_name, MatrixType) and array_value.type_name.vector:
            return _vector_elements(array_value)[index]
        if isinstance(array_value.type_name, MatrixType):
            raise AetherTypeError("Matrix values require two-dimensional indexing with A[i, j].")
        return array_value.value[index]

    def _read_array_slice(self, expression: ast.SliceExpression, env: Environment) -> AetherValue:
        array_value = self._evaluate(expression.collection, env)
        if not isinstance(array_value.type_name, ArrayType):
            range_expression = ast.RangeExpression(expression.start, expression.end)
            if isinstance(array_value.type_name, ListType):
                return self._read_list_slice(array_value, range_expression, env)
            return self._read_vector_slice(array_value, range_expression, env)
        start_value = self._evaluate(expression.start, env)
        end_value = self._evaluate(expression.end, env)
        if start_value.type_name != "int" or end_value.type_name != "int":
            raise AetherTypeError("Array slice bounds must be int.")
        start = start_value.value
        end = end_value.value
        if start < 0 or start > end or end > len(array_value.value):
            raise AetherRuntimeError("Aether panic: Array slice out of bounds")
        return AetherValue(array_value.type_name, list(array_value.value[start:end]))

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
        indices = self._slice_indices(index_expression, env, len(elements), "Vector", base=1)
        sliced = [elements[index] for index in indices]
        if isinstance(vector_value.type_name, TransposeVectorType):
            vector = AetherValue(VectorType(vector_value.type_name.element_type, len(sliced), "row"), sliced)
            return AetherValue(TransposeVectorType(vector_value.type_name.element_type, len(sliced)), vector)
        element_type = _vector_element_type(vector_value)
        orientation = vector_value.type_name.orientation if isinstance(vector_value.type_name, VectorType) else None
        return AetherValue(VectorType(element_type, len(sliced), orientation), sliced)

    def _read_list_slice(
        self,
        list_value: AetherValue,
        index_expression: ast.Expression,
        env: Environment,
    ) -> AetherValue:
        if not isinstance(index_expression, ast.RangeExpression):
            raise AetherTypeError("List slices require explicit start and end.")
        start = self._evaluate_list_slice_component(index_expression.start, env, "start")
        end = self._evaluate_list_slice_component(index_expression.end, env, "end")
        step = (
            self._evaluate_list_slice_component(index_expression.step, env, "step")
            if index_expression.step is not None
            else 1
        )
        if step == 0:
            raise AetherRuntimeError("List slice step cannot be 0.")
        if start < 0 or end < 0:
            raise AetherRuntimeError("negative list slice index is not supported.")

        length = len(list_value.value)
        selected: list[AetherValue] = []
        index = start
        while index <= end if step > 0 else index >= end:
            if index >= length:
                raise AetherRuntimeError(f"List slice index {index} out of bounds for length {length} (0-based).")
            selected.append(list_value.value[index])
            index += step
        return AetherValue(list_value.type_name, selected)

    def _evaluate_list_slice_component(self, expression: ast.Expression, env: Environment, label: str) -> int:
        value = self._evaluate(expression, env)
        if value.type_name != "int":
            raise AetherTypeError(f"List slice {label} must be int, got '{type_to_string(value.type_name)}'.")
        return value.value

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
            return self._slice_indices(expression, env, size, label, base=1)
        value = self._evaluate(expression, env)
        if value.type_name != "int":
            raise AetherTypeError(f"{label} index must be int or slice, got '{type_to_string(value.type_name)}'.")
        index = value.value - 1
        if index < 0 or index >= size:
            raise AetherRuntimeError(MATRIX_INDEX_OUT_OF_BOUNDS)
        return index

    def _slice_indices(self, expression: ast.Expression, env: Environment, size: int, label: str, *, base: int) -> list[int]:
        if isinstance(expression, ast.FullSlice):
            return list(range(size))
        range_value = self._evaluate_range(expression, env) if isinstance(expression, ast.RangeExpression) else self._evaluate(expression, env)
        if not isinstance(range_value.type_name, RangeType) or not isinstance(range_value.value, AetherRange):
            raise AetherTypeError(f"{label} slice must be ':' or an int range.")
        requested_indices = [element.value for element in range_value.value]
        indices = [index - base for index in requested_indices]
        for requested_index, index in zip(requested_indices, indices):
            if index < 0 or index >= size:
                raise AetherRuntimeError(f"{label} index {requested_index} out of bounds for {size} ({_base_label(base)}).")
        return indices

    def _assign_index(self, statement: ast.IndexAssignment, env: Environment) -> None:
        array_value = self._evaluate(statement.array, env)
        index_value = self._evaluate(statement.index, env)
        index = self._require_index(array_value, index_value)
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
            if isinstance(array_value.type_name, ArrayType)
            else list_element_type(array_value.type_name)
        )
        if is_array_type(element_type) and isinstance(array_value.type_name, MatrixType):
            raise AetherTypeError("Assigning a whole matrix row is not supported yet.")
        value = self._evaluate_with_expected_type(statement.expression, env, element_type)
        if isinstance(array_value.type_name, VectorType):
            array_value.value[index] = coerce_implicit(value, element_type)
            return
        if isinstance(array_value.type_name, MatrixType) and array_value.type_name.vector:
            _assign_vector_element(array_value, index, coerce_implicit(value, element_type))
            return
        array_value.value[index] = coerce_implicit(value, element_type)

    def _assign_destructuring(self, statement: ast.DestructuringAssignment, env: Environment) -> None:
        value = self._evaluate(statement.expression, env)
        if isinstance(value.type_name, TupleType):
            elements = list(value.value)
        elif isinstance(value.type_name, (VectorType, TransposeVectorType)) or (
            isinstance(value.type_name, MatrixType) and _is_vector_like_matrix(value)
        ):
            elements = _vector_elements(value)
        else:
            raise AetherTypeError(f"Cannot destructure value of type {type_to_string(value.type_name)}.")
        if len(elements) != len(statement.names):
            raise AetherTypeError(f"Destructuring expected {len(elements)} values but got {len(statement.names)}.")
        for name, element in zip(statement.names, elements):
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

    def _assign_field(self, statement: ast.FieldAssignment, env: Environment) -> None:
        struct_value = self._evaluate(statement.target, env)
        instance = self._require_struct_instance(struct_value, statement.field_name)
        if statement.field_name not in instance.fields:
            raise AetherTypeError(f"Struct '{instance.type_name}' has no field '{statement.field_name}'.")
        field_type = instance.fields[statement.field_name].type_name
        value = self._evaluate_with_expected_type(statement.expression, env, field_type)
        instance.fields[statement.field_name] = coerce_implicit(value, field_type)

    def _assign_implicit_method_field(self, field_name: str, expression: ast.Expression, env: Environment) -> None:
        receiver = self._method_receiver_value(env)
        if receiver is None or not isinstance(receiver.value, (StructInstance, ClassInstance)):
            raise AetherRuntimeError(f"Undefined variable '{field_name}'.")
        instance = receiver.value
        if field_name not in instance.fields:
            raise AetherRuntimeError(f"Undefined variable '{field_name}'.")
        field_type = instance.fields[field_name].type_name
        value = self._evaluate_with_expected_type(expression, env, field_type)
        instance.fields[field_name] = coerce_implicit(value, field_type)

    def _require_index(self, array_value: AetherValue, index_value: AetherValue) -> int:
        if not is_indexable_type(array_value.type_name):
            raise AetherTypeError(f"Cannot index non-indexable value of type '{type_to_string(array_value.type_name)}'.")
        if index_value.type_name != "int":
            raise AetherTypeError(f"Index must be int, got '{type_to_string(index_value.type_name)}'.")
        length = _indexable_length(array_value)
        if isinstance(array_value.type_name, (VectorType, TransposeVectorType)) or (
            isinstance(array_value.type_name, MatrixType) and array_value.type_name.vector
        ):
            try:
                return checked_vector_offset(index_value.value, length)
            except IndexError as error:
                raise AetherRuntimeError(VECTOR_INDEX_OUT_OF_BOUNDS) from error
        base = _index_base(array_value.type_name)
        index = index_value.value - base
        if index < 0 or index >= length:
            label = _indexable_label(array_value.type_name)
            raise AetherRuntimeError(
                f"{label} index {index_value.value} out of bounds for length {length} ({_base_label(base)})."
            )
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
        try:
            offset = checked_matrix_offset(row, column, rows * cols, cols)
        except IndexError as error:
            raise AetherRuntimeError(MATRIX_INDEX_OUT_OF_BOUNDS) from error
        return divmod(offset, cols)

    def _evaluate_call(self, expression: ast.CallExpression, env: Environment) -> AetherValue:
        indirect = env.lookup(expression.callee) if "." not in expression.callee else None
        if indirect is not None:
            if not isinstance(indirect.value, FunctionReference) or not isinstance(
                indirect.type_name, FunctionType
            ):
                raise AetherRuntimeError(
                    f"Value '{expression.callee}' of type '{type_to_string(indirect.type_name)}' is not callable."
                )
            if expression.keyword_arguments:
                raise AetherRuntimeError("Indirect calls do not accept keyword arguments.")
            if len(expression.arguments) != indirect.value.arity:
                raise AetherRuntimeError(
                    f"Callable '{expression.callee}' expects {indirect.value.arity} arguments "
                    f"but got {len(expression.arguments)}."
                )
            args = [
                self._evaluate_with_expected_type(argument, env, parameter_type)
                for argument, parameter_type in zip(
                    expression.arguments, indirect.value.signature.parameter_types
                )
            ]
            return indirect.value.call(args)
        canonical_callee = self._resolve_module_member(expression.callee)
        builtin_name = self.builtin_aliases.get(expression.callee, canonical_callee or expression.callee)
        builtin_is_visible = "." not in expression.callee or canonical_callee is not None
        named_args = {name: self._evaluate(value, env) for name, value in expression.keyword_arguments.items()}
        if expression.callee == "Exception":
            if named_args:
                raise AetherRuntimeError("Exception(...) does not accept keyword arguments.")
            args = [self._evaluate(arg, env) for arg in expression.arguments]
            return self._construct_exception(args, expression)
        if builtin_is_visible and builtin_name in self.builtins:
            args = [
                self._evaluate_builtin_argument(arg, env, builtin_name)
                for arg in expression.arguments
            ]
            return self._call(builtin_name, args, named_args, env)
        method_value = self._evaluate_dotted_native_method_call(expression, env)
        if method_value is not None:
            return method_value
        if named_args:
            raise AetherRuntimeError(f"Function '{expression.callee}' does not accept keyword arguments.")
        if self._constructor_enum(expression.callee) is not None:
            raise AetherRuntimeError(
                f"Cannot instantiate enum '{expression.callee}' as a function.",
                line=expression.line,
                column=expression.column,
            )
        if self._constructor_interface(expression.callee) is not None:
            raise AetherRuntimeError(
                f"Cannot instantiate interface '{expression.callee}' as a function.",
                line=expression.line,
                column=expression.column,
            )
        struct = self.qualified_structs.get(canonical_callee) if canonical_callee is not None else None
        if struct is None:
            struct = self._constructor_struct(expression.callee)
        if struct is not None:
            constructor_parameters = (
                struct.constructor.parameters
                if struct.constructor is not None
                else struct.fields
            )
            args = [
                self._evaluate_with_expected_type(arg, env, self._resolve_type_aliases(parameter.type_name))
                for arg, parameter in zip(expression.arguments, constructor_parameters)
            ]
            if len(args) != len(expression.arguments):
                args = [self._evaluate(arg, env) for arg in expression.arguments]
            return self._construct_struct(struct, args)
        receiver = self._method_receiver_value(env)
        if receiver is not None and "." not in expression.callee:
            method = self._struct_method_function(receiver.type_name, expression.callee)
            if method is not None:
                return self._call_struct_method(receiver, method, expression.arguments, named_args, env, expression)
        resolved_callee = canonical_callee or expression.callee
        function = env.get_function(resolved_callee)
        if function is not None and isinstance(function.declaration, ast.FunctionDeclaration) and len(
            expression.arguments
        ) == len(function.declaration.parameters):
            try:
                parameter_types = [
                    self._resolve_type_aliases(parameter.type_name)
                    for parameter in function.declaration.parameters
                ]
            except AetherTypeError:
                args = [self._evaluate(arg, env) for arg in expression.arguments]
            else:
                args = [
                    self._evaluate_with_expected_type(arg, env, parameter_type)
                    for arg, parameter_type in zip(expression.arguments, parameter_types)
                ]
        else:
            args = [self._evaluate(arg, env) for arg in expression.arguments]
        return self._call(resolved_callee, args, {}, env)

    def _evaluate_dotted_native_method_call(
        self,
        expression: ast.CallExpression,
        env: Environment,
    ) -> AetherValue | None:
        receiver = _dotted_call_receiver(expression.callee, expression.line, expression.column)
        if receiver is None:
            return None
        root_name, target, method_name = receiver
        if env.lookup(root_name) is None:
            return None
        return self._evaluate_method_call(
            ast.MethodCall(
                target,
                method_name,
                expression.arguments,
                expression.keyword_arguments,
                expression.line,
                expression.column,
            ),
            env,
        )

    def _evaluate_method_call(self, expression: ast.MethodCall, env: Environment) -> AetherValue:
        receiver = self._evaluate(expression.target, env)
        if isinstance(receiver.value, (StructInstance, ClassInstance)):
            method = self._struct_method_function(receiver.value.type_name, expression.method_name)
            if method is None:
                if expression.method_name in receiver.value.fields:
                    raise AetherTypeError(f"{expression.method_name} is a field, not a method.")
                kind = "Class" if isinstance(receiver.value, ClassInstance) else "Struct"
                raise AetherTypeError(f"{kind} '{receiver.value.type_name}' has no method '{expression.method_name}'.")
            named_args = {name: self._evaluate(value, env) for name, value in expression.keyword_arguments.items()}
            return self._call_struct_method(receiver, method, expression.arguments, named_args, env, expression)
        members = native_member_set(receiver.type_name)
        if members is None:
            raise AetherTypeError(
                f"Type '{type_to_string(receiver.type_name)}' has no native method '{expression.method_name}'."
            )
        if expression.method_name in members.properties:
            raise AetherTypeError(f"{expression.method_name} is a property, not a method.")
        method = native_method(receiver.type_name, expression.method_name)
        if method is None:
            raise AetherTypeError(
                f"Type '{type_to_string(receiver.type_name)}' has no native method '{expression.method_name}'."
            )
        args = [receiver, *[self._evaluate(arg, env) for arg in expression.arguments]]
        named_args = {name: self._evaluate(value, env) for name, value in expression.keyword_arguments.items()}
        return self._call(method.builtin_name, args, named_args, env)

    def _constructor_struct(self, callee: str) -> ast.StructDeclaration | ast.ClassDeclaration | None:
        try:
            resolved = self._resolve_type_aliases(callee)
        except AetherTypeError:
            return None
        if isinstance(resolved, ClassType):
            return self.structs.get(resolved.name)
        if isinstance(resolved, str):
            return self.structs.get(resolved)
        return None

    def _constructor_enum(self, callee: str) -> ast.EnumDeclaration | None:
        try:
            resolved = self._resolve_type_aliases(callee)
        except AetherTypeError:
            return None
        if isinstance(resolved, EnumType):
            return self.enums.get(resolved.name)
        return None

    def _constructor_interface(self, callee: str) -> ast.InterfaceDeclaration | None:
        try:
            resolved = self._resolve_type_aliases(callee)
        except AetherTypeError:
            return None
        if isinstance(resolved, InterfaceType):
            return self.interfaces.get(resolved.name)
        return None

    def _construct_struct(
        self,
        declaration: ast.StructDeclaration | ast.ClassDeclaration,
        args: list[AetherValue],
    ) -> AetherValue:
        constructor = declaration.constructor
        parameters = constructor.parameters if constructor is not None else declaration.fields
        if len(args) != len(parameters):
            kind = "Class" if isinstance(declaration, ast.ClassDeclaration) else "Struct"
            raise AetherRuntimeError(
                f"{kind} '{declaration.name}' constructor expects {len(parameters)} arguments but got {len(args)}."
            )
        if constructor is not None:
            return self._construct_with_explicit_constructor(declaration, constructor, args)
        fields: dict[str, AetherValue] = {}
        field_order: list[str] = []
        for field, arg in zip(declaration.fields, args):
            field_type = self._resolve_type_aliases(field.type_name)
            fields[field.name] = coerce_implicit(arg, field_type)
            field_order.append(field.name)
        if isinstance(declaration, ast.ClassDeclaration):
            return AetherValue(ClassType(declaration.name), ClassInstance(declaration.name, fields, tuple(field_order)))
        return AetherValue(declaration.name, StructInstance(declaration.name, fields, tuple(field_order)))

    def _construct_with_explicit_constructor(
        self,
        declaration: ast.StructDeclaration | ast.ClassDeclaration,
        constructor: ast.ConstructorDeclaration,
        args: list[AetherValue],
    ) -> AetherValue:
        fields = {
            field.name: self._default_field_value(self._resolve_type_aliases(field.type_name))
            for field in declaration.fields
        }
        field_order = tuple(field.name for field in declaration.fields)
        if isinstance(declaration, ast.ClassDeclaration):
            instance: StructInstance | ClassInstance = ClassInstance(declaration.name, fields, field_order)
            receiver = AetherValue(ClassType(declaration.name), instance)
        else:
            instance = StructInstance(declaration.name, fields, field_order)
            receiver = AetherValue(declaration.name, instance)
        local_env = Environment(parent=self.global_env, method_receiver=receiver)
        local_env.define("this", receiver, is_const=True)
        for parameter, arg in zip(constructor.parameters, args):
            parameter_type = self._resolve_type_aliases(parameter.type_name)
            local_env.define(parameter.name, coerce_implicit(arg, parameter_type))
        previous_return_type = self.current_return_type
        self.current_return_type = "void"
        try:
            try:
                self._execute_block(constructor.body, local_env)
            except _ReturnSignal as signal:
                coerce_return_value(signal.value, "void")
        finally:
            self.current_return_type = previous_return_type
        return receiver

    def _default_field_value(self, type_name: AetherType) -> AetherValue:
        if type_name == "int":
            return AetherValue(type_name, 0)
        if type_name in {"float", "double"}:
            return AetherValue(type_name, 0.0)
        if type_name == "complex":
            return AetherValue(type_name, 0j)
        if type_name == "boolean":
            return AetherValue(type_name, False)
        if type_name == "string":
            return AetherValue(type_name, "")
        if isinstance(type_name, (ArrayType, ListType, MatrixType, VectorType)):
            return AetherValue(type_name, [])
        return AetherValue(type_name, None)

    def _enum_variant_value(
        self,
        enum_name: str,
        variant_name: str,
        location: object | None = None,
    ) -> AetherValue | None:
        declaration = self.enums.get(enum_name)
        if declaration is None:
            private_message = self._private_import_message(enum_name)
            if private_message is not None:
                raise AetherRuntimeError(
                    private_message,
                    line=getattr(location, "line", None),
                    column=getattr(location, "column", None),
                    kind="name",
                )
            return None
        if variant_name not in {variant.name for variant in declaration.variants}:
            raise AetherTypeError(
                f"Enum '{enum_name}' has no variant '{variant_name}'.",
                line=getattr(location, "line", None),
                column=getattr(location, "column", None),
            )
        return AetherValue(
            EnumType(enum_name, self._enum_identity(declaration)),
            self._make_enum_value(declaration, variant_name),
        )

    def _enum_identity(self, declaration: ast.EnumDeclaration) -> EnumIdentity:
        identity = self._enum_identity_by_declaration_id.get(id(declaration))
        if identity is None:
            identity = EnumIdentity(self._module_identity, declaration.name)
            self._enum_identity_by_declaration_id[id(declaration)] = identity
        return identity

    def _make_enum_value(
        self,
        declaration: ast.EnumDeclaration,
        variant_name: str,
        *,
        display_name: str | None = None,
    ) -> EnumValue:
        variants = tuple(variant.name for variant in declaration.variants)
        try:
            member_id = variants.index(variant_name)
        except ValueError as exc:
            raise AetherTypeError(
                f"Enum '{declaration.name}' has no variant '{variant_name}'."
            ) from exc
        return EnumValue(
            display_name or declaration.name,
            variant_name,
            self._enum_identity(declaration),
            member_id,
            member_id,
        )

    def _read_field(self, target: ast.Expression, field_name: str, env: Environment) -> AetherValue:
        struct_value = self._evaluate(target, env)
        if isinstance(struct_value.value, AetherExceptionValue):
            if field_name == "message":
                return AetherValue("string", struct_value.value.message)
            if field_name == "kind":
                return AetherValue("string", struct_value.value.kind)
            raise AetherTypeError(f"Exception has no field '{field_name}'.")
        members = native_member_set(struct_value.type_name)
        if members is not None:
            native = native_property(struct_value.type_name, field_name)
            if native is not None:
                return self._call(native.builtin_name, [struct_value], {}, env)
            if field_name in members.methods:
                raise AetherTypeError(f"{field_name} is a method and must be called.")
            raise AetherTypeError(
                f"Type '{type_to_string(struct_value.type_name)}' has no native property '{field_name}'."
            )
        instance = self._require_struct_instance(struct_value, field_name)
        if field_name not in instance.fields:
            if self._struct_method_function(instance.type_name, field_name) is not None:
                raise AetherTypeError(f"{field_name} is a method and must be called.")
            kind = "Class" if isinstance(instance, ClassInstance) else "Struct"
            raise AetherTypeError(f"{kind} '{instance.type_name}' has no field '{field_name}'.")
        return instance.fields[field_name]

    def _require_struct_instance(self, value: AetherValue, field_name: str) -> StructInstance | ClassInstance:
        if isinstance(value.value, (StructInstance, ClassInstance)):
            return value.value
        raise AetherTypeError(
            f"Cannot access field '{field_name}' on non-struct value of type '{type_to_string(value.type_name)}'."
        )

    def _evaluate_builtin_argument(self, expression: ast.Expression, env: Environment, builtin_name: str) -> AetherValue:
        if builtin_name.startswith("Plots.") and isinstance(expression, ast.Identifier):
            if env.lookup(expression.name) is None and env.get_function(expression.name) is not None:
                return self._plots_function_reference_value(expression.name, env)
        return self._evaluate(expression, env)

    def _plots_function_reference_value(self, name: str, env: Environment) -> AetherValue:
        function = env.get_function(name)
        if function is None:
            raise AetherRuntimeError(f"Undefined function '{name}'.")

        def call(args: list[AetherValue]) -> AetherValue:
            return self._call_user_function(name, args, env)

        return AetherValue(
            "function",
            _PlotsFunctionReference(name, len(function.declaration.parameters), call),
        )

    def _function_reference_value(self, name: str, env: Environment) -> AetherValue:
        function = env.get_function(name)
        if function is None:
            raise AetherRuntimeError(f"Undefined function '{name}'.")
        declaration = function.declaration
        if not isinstance(declaration, ast.FunctionDeclaration):
            raise AetherRuntimeError(
                f"Function '{name}' has no concrete signature and cannot be used as a callable value."
            )
        signature = FunctionType(
            tuple(self._resolve_type_aliases(parameter.type_name) for parameter in declaration.parameters),
            self._resolve_type_aliases(declaration.return_type),
        )
        canonical_name = self.imported_symbol_origins.get(
            name, self._resolve_module_member(name) or name
        )
        return AetherValue(
            signature,
            FunctionReference(canonical_name, signature, function, self),
        )

    def _call(
        self,
        callee: str,
        args: list[AetherValue],
        named_args: dict[str, AetherValue],
        env: Environment,
    ) -> AetherValue:
        builtin_name = self.builtin_aliases.get(callee, self._resolve_module_member(callee) or callee)
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
        return self._call_function(callee, function, args)

    def _call_function(self, callee: str, function: Function, args: list[AetherValue]) -> AetherValue:
        declaration = function.declaration
        if len(args) != len(declaration.parameters):
            raise AetherRuntimeError(
                f"Function '{callee}' expects {len(declaration.parameters)} arguments but got {len(args)}."
            )
        with self._function_context(function):
            if isinstance(declaration, ast.ExpressionFunctionDeclaration):
                local_env = Environment(parent=function.closure or self.global_env)
                for parameter, arg in zip(declaration.parameters, args):
                    local_env.define(parameter.name, arg)
                return self._evaluate(declaration.expression, local_env)
            local_env = Environment(parent=function.closure or self.global_env)
            for parameter, arg in zip(declaration.parameters, args):
                local_env.define(parameter.name, coerce_implicit(arg, self._resolve_type_aliases(parameter.type_name)))
            return_type = self._resolve_type_aliases(declaration.return_type)
            previous_return_type = self.current_return_type
            self.current_return_type = return_type
            try:
                try:
                    self._execute_block(declaration.body, local_env)
                except _ReturnSignal as signal:
                    return coerce_return_value(signal.value, return_type)
            finally:
                self.current_return_type = previous_return_type
            if return_type == "void":
                return AetherValue("void", VOID_VALUE)
            raise AetherRuntimeError(f"Function '{callee}' ended without returning a value.")

    def _call_struct_method(
        self,
        receiver: AetherValue,
        function: Function,
        argument_expressions: list[ast.Expression],
        named_args: dict[str, AetherValue],
        env: Environment,
        location: object | None = None,
    ) -> AetherValue:
        if named_args:
            raise AetherRuntimeError(
                f"Method '{function.declaration.name}' does not accept keyword arguments.",
                line=getattr(location, "line", None),
                column=getattr(location, "column", None),
            )
        declaration = function.declaration
        if not isinstance(declaration, ast.FunctionDeclaration):
            raise AetherRuntimeError(f"Invalid struct method '{declaration.name}'.")
        if len(argument_expressions) != len(declaration.parameters):
            raise AetherRuntimeError(
                f"Method '{declaration.name}' expects {len(declaration.parameters)} arguments "
                f"but got {len(argument_expressions)}.",
                line=getattr(location, "line", None),
                column=getattr(location, "column", None),
                kind="arity",
            )
        with self._function_context(function):
            parameter_types = [
                self._resolve_type_aliases(parameter.type_name)
                for parameter in declaration.parameters
            ]
            args = [
                self._evaluate_with_expected_type(argument, env, parameter_type)
                for argument, parameter_type in zip(argument_expressions, parameter_types)
            ]
            if isinstance(receiver.value, ClassInstance):
                method_receiver = AetherValue(ClassType(receiver.value.type_name), receiver.value)
            elif isinstance(receiver.value, StructInstance):
                method_receiver = AetherValue(receiver.value.type_name, receiver.value)
            else:
                method_receiver = receiver
            local_env = Environment(parent=function.closure or self.global_env, method_receiver=method_receiver)
            local_env.define("this", method_receiver, is_const=True)
            for parameter, parameter_type, arg in zip(declaration.parameters, parameter_types, args):
                local_env.define(parameter.name, coerce_implicit(arg, parameter_type))
            return_type = self._resolve_type_aliases(declaration.return_type)
            previous_return_type = self.current_return_type
            self.current_return_type = return_type
            try:
                try:
                    self._execute_block(declaration.body, local_env)
                except _ReturnSignal as signal:
                    return coerce_return_value(signal.value, return_type)
            finally:
                self.current_return_type = previous_return_type
            if return_type == "void":
                return AetherValue("void", VOID_VALUE)
            raise AetherRuntimeError(f"Method '{declaration.name}' ended without returning a value.")

    def _struct_method_function(self, struct_name: AetherType, method_name: str) -> Function | None:
        if isinstance(struct_name, ClassType):
            return self.struct_methods.get(struct_name.name, {}).get(method_name)
        if isinstance(struct_name, str):
            return self.struct_methods.get(struct_name, {}).get(method_name)
        return None

    def _method_receiver_value(self, env: Environment) -> AetherValue | None:
        cursor: Environment | None = env
        while cursor is not None:
            if cursor.method_receiver is not None and isinstance(cursor.method_receiver.value, (StructInstance, ClassInstance)):
                return cursor.method_receiver
            cursor = cursor.parent
        return None

    def _method_receiver_env(self, env: Environment) -> Environment | None:
        cursor: Environment | None = env
        while cursor is not None:
            if cursor.method_receiver is not None and isinstance(cursor.method_receiver.value, (StructInstance, ClassInstance)):
                return cursor
            cursor = cursor.parent
        return None

    def _lookup_before_method_receiver(self, name: str, env: Environment) -> AetherValue | None:
        receiver_env = self._method_receiver_env(env)
        if receiver_env is None:
            return None
        cursor: Environment | None = env
        while cursor is not None:
            if name in cursor.values:
                return cursor.values[name]
            if cursor is receiver_env:
                return None
            cursor = cursor.parent
        return None

    def _implicit_method_field(self, name: str, env: Environment) -> AetherValue | None:
        receiver = self._method_receiver_value(env)
        if receiver is None or not isinstance(receiver.value, (StructInstance, ClassInstance)):
            return None
        if self._lookup_before_method_receiver(name, env) is not None:
            return None
        return receiver.value.fields.get(name)

    def _is_method_receiver_field_target(self, expression: ast.Expression, env: Environment) -> bool:
        root_name = _assignment_root_name(expression)
        if root_name == "this" and self._method_receiver_value(env) is not None:
            return True
        return root_name is not None and self._implicit_method_field(root_name, env) is not None

    def _function_context(self, function: Function) -> "_FunctionContext":
        return _FunctionContext(self, function)

    def _evaluate_binary(self, left: AetherValue, operator: str, right: AetherValue) -> AetherValue:
        if operator in {"+", "-", ".+", ".-", "*", ".*", "/", "%", "^"}:
            return self._numeric_or_string_binary(left, operator, right)
        if operator == "\\":
            if LINEAR_ALGEBRA_MODULE not in self.imported_modules:
                raise AetherRuntimeError(
                    "Operator '\\' requires module 'Math.LinearAlgebra'.",
                    hint="import Math.LinearAlgebra;",
                    kind="import",
                )
            return self.builtins[LINEAR_ALGEBRA_SOLVE]([left, right])
        if operator in {"==", "!="}:
            if isinstance(left.value, ClassInstance) or isinstance(right.value, ClassInstance):
                raise AetherTypeError("Class equality is not supported yet.")
            if isinstance(left.value, StructInstance) or isinstance(right.value, StructInstance):
                if (
                    not isinstance(left.value, StructInstance)
                    or not isinstance(right.value, StructInstance)
                    or left.value.type_name != right.value.type_name
                ):
                    raise AetherTypeError(
                        f"Cannot compare '{type_to_string(left.type_name)}' and '{type_to_string(right.type_name)}' "
                        f"with '{operator}'."
                    )
                result = _values_equal(left, right)
                return AetherValue("boolean", result if operator == "==" else not result)
            if not _types_comparable_for_equality(left.type_name, right.type_name):
                raise AetherTypeError(
                    f"Cannot compare '{type_to_string(left.type_name)}' and '{type_to_string(right.type_name)}' "
                    f"with '{operator}'."
                )
            result = _values_equal(left, right)
            return AetherValue("boolean", result if operator == "==" else not result)
        if operator in {"<", "<=", ">", ">="}:
            if left.type_name not in REAL_NUMERIC_TYPES or right.type_name not in REAL_NUMERIC_TYPES:
                raise AetherTypeError(f"Operator '{operator}' requires real numeric operands.")
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
        if operator == "%" and (left.type_name not in REAL_NUMERIC_TYPES or right.type_name not in REAL_NUMERIC_TYPES):
            raise AetherTypeError("Operator '%' requires real numeric operands.")
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
        if (
            left.type_name == "int"
            and right.type_name == "int"
            and operator in {"+", "-", "*", "/", "%"}
        ):
            operation = {"+": "add", "-": "sub", "*": "mul", "/": "div", "%": "rem"}[operator]
            try:
                value = checked_int_binary(operation, left.value, right.value)
            except (OverflowError, ZeroDivisionError) as exc:
                raise AetherRuntimeError(str(exc)) from exc
        elif operator == "+":
            value = left.value + right.value
        elif operator == "-":
            value = left.value - right.value
        elif operator == "*":
            value = left.value * right.value
        elif operator == "/":
            if result_type == "complex":
                if right.value == 0:
                    raise AetherRuntimeError("Operator '/' is undefined for divisor zero.", kind="arithmetic")
                value = left.value / right.value
            else:
                value = ieee_divide(float(left.value), float(right.value))
        elif operator == "%":
            if right.value == 0:
                raise AetherRuntimeError("Operator '%' is undefined for divisor zero.")
            if left.type_name == "int" and right.type_name == "int":
                quotient = abs(left.value) // abs(right.value)
                if (left.value < 0) != (right.value < 0):
                    quotient = -quotient
                value = left.value - quotient * right.value
            else:
                value = left.value - trunc(left.value / right.value) * right.value
        elif operator == "^":
            if left.type_name == "int" and right.type_name == "int" and right.value < 0:
                result_type = "double"
            value = left.value**right.value
        else:
            raise AetherRuntimeError(f"Unsupported numeric operator '{operator}'.")
        return _coerced_numeric_result(value, result_type)

    def _import_module_statement(self, statement: ast.ImportStatement) -> None:
        self._load_module(statement.module_name)
        self.module_bindings[statement.local_binding] = statement.module_name
        self.imported_modules.add(statement.module_name)

    def _load_module(self, module_name: str) -> tuple[ast.Program, "Interpreter"] | None:
        if is_builtin_namespace(module_name):
            self.imported_modules.add(module_name)
            return None
        cached = self._loaded_file_modules.get(module_name)
        if cached is not None:
            return cached
        if module_name in self.import_stack:
            raise AetherRuntimeError(f"Cyclic import involving '{module_name}'.")
        module_path = resolve_file_module_path(module_name, self.source_root)
        if not module_path.is_file():
            raise AetherRuntimeError(f"Module '{module_name}' not found.")
        source = module_path.read_text(encoding="utf-8")
        tokens = lex(source)
        program = Parser(tokens).parse()
        if program.package_name is not None and program.package_name != module_name:
            raise AetherRuntimeError(
                f"Module '{module_name}' declares package '{program.package_name}'."
            )
        module_interpreter = Interpreter(
            source_root=self.source_root,
            import_stack=(*self.import_stack, module_name),
            plot_mode=self.plot_backend.plot_mode,
            plot_output_dir=self.plot_backend.output_dir,
            output_writer=self.output_writer,
            input_reader=self.input_reader,
        )
        module_interpreter.interpret(program)
        loaded = (program, module_interpreter)
        self._loaded_file_modules[module_name] = loaded
        # Imported functions retain declaration objects from their defining
        # module (including transitively imported enum declarations).  Copy
        # the semantic identities alongside those closures so executing the
        # function in the caller cannot accidentally re-home an enum to the
        # entry module.
        self._enum_identity_by_declaration_id.update(
            module_interpreter._enum_identity_by_declaration_id
        )
        self._record_qualified_module_exports(module_name, program, module_interpreter)
        self.imported_modules.add(module_name)
        return loaded

    def _from_import(self, statement: ast.FromImportStatement) -> None:
        module_name = statement.module_name
        candidate_module = f"{module_name}.{statement.symbol}"
        if is_builtin_namespace(candidate_module) or resolve_file_module_path(candidate_module, self.source_root).is_file():
            self._load_module(candidate_module)
            self.module_bindings[statement.local_binding] = candidate_module
            self.imported_modules.add(candidate_module)
            return
        loaded = self._load_module(module_name)
        local_name = statement.local_binding
        canonical_name = f"{module_name}.{statement.symbol}"
        if is_builtin(canonical_name):
            self.builtin_aliases[local_name] = canonical_name
        elif is_builtin_constant(canonical_name):
            self.builtin_constant_aliases[local_name] = canonical_name
        elif loaded is not None:
            program, module_interpreter = loaded
            if statement.symbol in private_top_level_names(program):
                raise AetherRuntimeError(
                    f"Symbol '{statement.symbol}' is not public in module '{module_name}'.",
                    line=statement.symbol_line,
                    column=statement.symbol_column,
                    kind="import",
                )
            if canonical_name in self.global_env.functions:
                self.global_env.functions[local_name] = self.global_env.functions[canonical_name]
            elif canonical_name in self.qualified_values:
                value = self.qualified_values[canonical_name]
                is_const = module_interpreter.global_env.variable_scope.is_const(statement.symbol)
                self.global_env.define(local_name, value, is_const=is_const)
            elif statement.symbol in self._exported_structs(program, module_interpreter):
                self.structs[local_name] = replace(
                    module_interpreter.structs[statement.symbol],
                    name=local_name,
                )
                self.struct_methods[local_name] = dict(module_interpreter.struct_methods.get(statement.symbol, {}))
            elif statement.symbol in self._exported_enums(program, module_interpreter):
                declaration = module_interpreter.enums[statement.symbol]
                self.enums[local_name] = declaration
                self._enum_identity_by_declaration_id[id(declaration)] = module_interpreter._enum_identity(
                    declaration
                )
            elif statement.symbol in self._exported_interfaces(program, module_interpreter):
                self.interfaces[local_name] = module_interpreter.interfaces[statement.symbol]
            elif statement.symbol in self._exported_aliases(program, module_interpreter):
                target_type = module_interpreter.type_aliases[statement.symbol]
                if isinstance(target_type, str) and target_type in module_interpreter.structs:
                    self.structs[local_name] = replace(module_interpreter.structs[target_type], name=local_name)
                    self.struct_methods[local_name] = dict(module_interpreter.struct_methods.get(target_type, {}))
                else:
                    self.type_aliases[local_name] = target_type
            else:
                raise AetherRuntimeError(
                    f"Module '{module_name}' has no exported symbol '{statement.symbol}'.",
                    line=statement.symbol_line,
                    column=statement.symbol_column,
                    kind="import",
                )
        else:
            raise AetherRuntimeError(
                f"Module '{module_name}' has no exported symbol '{statement.symbol}'.",
                line=statement.symbol_line,
                column=statement.symbol_column,
                kind="import",
            )
        self.imported_symbol_origins[local_name] = canonical_name
        self.imported_modules.add(module_name)

    def _record_qualified_module_exports(
        self,
        module_name: str,
        program: ast.Program,
        module_interpreter: "Interpreter",
    ) -> None:
        for name, modules in module_interpreter.private_imported_symbols.items():
            self.private_imported_symbols.setdefault(name, set()).update(modules)
        for name in private_top_level_names(program):
            self.private_imported_symbols.setdefault(name, set()).add(module_name)
        for name, value in self._exported_values(program, module_interpreter).items():
            self.qualified_values[f"{module_name}.{name}"] = value
        for name, function in self._exported_functions(program, module_interpreter).items():
            self.global_env.functions[f"{module_name}.{name}"] = function
        for name, declaration in self._exported_structs(program, module_interpreter).items():
            self.qualified_structs[f"{module_name}.{name}"] = declaration
        for name, declaration in self._exported_enums(program, module_interpreter).items():
            self.qualified_enums[f"{module_name}.{name}"] = declaration
            self._enum_identity_by_declaration_id[id(declaration)] = module_interpreter._enum_identity(
                declaration
            )

    def _resolve_module_member(self, visible_name: str | None) -> str | None:
        if visible_name is None:
            return None
        for binding in sorted(self.module_bindings, key=len, reverse=True):
            if visible_name == binding:
                return self.module_bindings[binding]
            if visible_name.startswith(binding + "."):
                return self.module_bindings[binding] + visible_name[len(binding) :]
        return None

    def _exported_values(
        self,
        program: ast.Program,
        module_interpreter: "Interpreter",
    ) -> dict[str, AetherValue]:
        if program.package_name is None:
            return dict(module_interpreter.global_env.values)
        exports: dict[str, AetherValue] = {}
        for statement in program.statements:
            if isinstance(statement, ast.VarDeclaration) and is_public_export(statement.visibility, program.package_name):
                exports[statement.name] = module_interpreter.global_env.get(statement.name)
        return exports

    def _exported_functions(
        self,
        program: ast.Program,
        module_interpreter: "Interpreter",
    ) -> dict[str, Function]:
        if program.package_name is None:
            return dict(module_interpreter.global_env.functions)
        exports: dict[str, Function] = {}
        for statement in program.statements:
            if isinstance(statement, (ast.FunctionDeclaration, ast.ExpressionFunctionDeclaration)) and is_public_export(
                statement.visibility,
                program.package_name,
            ):
                exports[statement.name] = module_interpreter.global_env.functions[statement.name]
        return exports

    def _exported_structs(
        self,
        program: ast.Program,
        module_interpreter: "Interpreter",
    ) -> dict[str, ast.StructDeclaration]:
        if program.package_name is None:
            return dict(module_interpreter.structs)
        exports: dict[str, ast.StructDeclaration] = {}
        for statement in program.statements:
            if isinstance(statement, (ast.StructDeclaration, ast.ClassDeclaration)) and is_public_export(statement.visibility, program.package_name):
                exports[statement.name] = module_interpreter.structs[statement.name]
        return exports

    def _exported_enums(
        self,
        program: ast.Program,
        module_interpreter: "Interpreter",
    ) -> dict[str, ast.EnumDeclaration]:
        if program.package_name is None:
            return dict(module_interpreter.enums)
        exports: dict[str, ast.EnumDeclaration] = {}
        for statement in program.statements:
            if isinstance(statement, ast.EnumDeclaration) and is_public_export(statement.visibility, program.package_name):
                exports[statement.name] = module_interpreter.enums[statement.name]
        return exports

    def _exported_interfaces(
        self,
        program: ast.Program,
        module_interpreter: "Interpreter",
    ) -> dict[str, ast.InterfaceDeclaration]:
        if program.package_name is None:
            return dict(module_interpreter.interfaces)
        exports: dict[str, ast.InterfaceDeclaration] = {}
        for statement in program.statements:
            if isinstance(statement, ast.InterfaceDeclaration) and is_public_export(statement.visibility, program.package_name):
                exports[statement.name] = module_interpreter.interfaces[statement.name]
        return exports

    def _exported_aliases(
        self,
        program: ast.Program,
        module_interpreter: "Interpreter",
    ) -> dict[str, AetherType]:
        if program.package_name is None:
            return dict(module_interpreter.type_aliases)
        exports: dict[str, AetherType] = {}
        for statement in program.statements:
            if isinstance(statement, ast.AliasDeclaration) and is_public_export(statement.visibility, program.package_name):
                exports[statement.name] = module_interpreter.type_aliases[statement.name]
        return exports

    def _require_boolean(self, value: AetherValue, construct: str) -> None:
        if value.type_name != "boolean":
            raise AetherTypeError(f"The condition of '{construct}' must be boolean, got '{value.type_name}'.")

    def _construct_exception(self, args: list[AetherValue], location: object | None = None) -> AetherValue:
        if len(args) != 1:
            raise AetherRuntimeError(
                f"Exception(...) expects 1 argument but got {len(args)}.",
                line=getattr(location, "line", None),
                column=getattr(location, "column", None),
                kind="arity",
            )
        message = args[0]
        if message.type_name != "string":
            raise AetherTypeError(
                f"Exception(...) message must be string, got '{type_to_string(message.type_name)}'.",
                line=getattr(location, "line", None),
                column=getattr(location, "column", None),
            )
        return AetherValue("Exception", AetherExceptionValue(str(message.value)))

    def _exception_from_value(self, value: AetherValue, location: object | None = None) -> AetherValue:
        if value.type_name == "string":
            return AetherValue("Exception", AetherExceptionValue(str(value.value)))
        if value.type_name == "Exception" and isinstance(value.value, AetherExceptionValue):
            return value
        raise AetherTypeError(
            f"throw expects string or Exception, got '{type_to_string(value.type_name)}'.",
            line=getattr(location, "line", None),
            column=getattr(location, "column", None),
        )

    def _runtime_error_from_thrown(self, value: AetherValue) -> AetherRuntimeError:
        if isinstance(value.value, AetherExceptionValue):
            return AetherRuntimeError(value.value.message, kind=value.value.kind)
        return AetherRuntimeError(format_value(value), kind="Exception")

    def _resolve_type_aliases(self, type_name: AetherType | None, resolving: tuple[str, ...] = ()) -> AetherType:
        if type_name is None:
            raise AetherTypeError("Cannot infer type in this declaration.")
        if isinstance(type_name, str):
            if type_name in self.type_aliases:
                if type_name in resolving:
                    cycle_name = resolving[0] if resolving else type_name
                    raise AetherTypeError(f"Cyclic type alias involving '{cycle_name}'.")
                return self._resolve_type_aliases(self.type_aliases[type_name], (*resolving, type_name))
            if type_name in self.structs:
                declaration = self.structs[type_name]
                return ClassType(type_name) if isinstance(declaration, ast.ClassDeclaration) else type_name
            if type_name in self.enums:
                declaration = self.enums[type_name]
                return EnumType(type_name, self._enum_identity(declaration))
            if type_name in self.interfaces:
                return InterfaceType(type_name)
            if type_name not in AETHER_TYPES:
                private_message = self._private_import_message(type_name)
                if private_message is not None:
                    raise AetherTypeError(private_message)
                raise AetherTypeError(f"Unknown type '{type_name}'.")
            return type_name
        if isinstance(type_name, ArrayType):
            return ArrayType(self._resolve_type_aliases(type_name.element_type, resolving))
        if isinstance(type_name, ListType):
            return ListType(self._resolve_type_aliases(type_name.element_type, resolving))
        if isinstance(type_name, NullableType):
            return NullableType(self._resolve_type_aliases(type_name.base_type, resolving))
        if isinstance(type_name, TupleType):
            return TupleType(tuple(self._resolve_type_aliases(element, resolving) for element in type_name.element_types))
        if isinstance(type_name, FunctionType):
            return FunctionType(
                tuple(
                    self._resolve_type_aliases(element, resolving)
                    for element in type_name.parameter_types
                ),
                (
                    "void"
                    if type_name.return_type == "void"
                    else self._resolve_type_aliases(type_name.return_type, resolving)
                ),
            )
        if isinstance(type_name, MatrixType):
            element_type = self._resolve_vector_matrix_element_type(type_name.element_type, resolving)
            return MatrixType(element_type, type_name.rows, type_name.cols, type_name.vector)
        if isinstance(type_name, VectorType):
            element_type = self._resolve_vector_matrix_element_type(type_name.element_type, resolving)
            return VectorType(element_type, type_name.length, type_name.orientation)
        if isinstance(type_name, TransposeVectorType):
            element_type = self._resolve_vector_matrix_element_type(type_name.element_type, resolving)
            return TransposeVectorType(element_type, type_name.length)
        if isinstance(type_name, RangeType):
            return RangeType(self._resolve_vector_matrix_element_type(type_name.element_type, resolving))
        return type_name

    def _private_import_message(self, name: str) -> str | None:
        """Check if a symbol was imported but is private, and return an error message if so."""
        modules = self.private_imported_symbols.get(name)
        if not modules:
            return None
        module_list = "', '".join(sorted(modules))
        return f"Symbol '{name}' is private in imported module '{module_list}'."

    def _resolve_vector_matrix_element_type(self, element_type: str, resolving: tuple[str, ...] = ()) -> str:
        resolved = self._resolve_type_aliases(element_type, resolving)
        if not isinstance(resolved, str) or resolved not in PRIMITIVE_TYPES:
            raise AetherTypeError(f"Expected primitive element type, got '{type_to_string(resolved)}'.")
        return resolved

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
        if value.type_name.orientation == "row":
            return _ConcatBlockValue(value.type_name.element_type, [list(value.value)], "vector")
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
        and all(row[0].col_count == 1 for row in blocks)
    )


def _single_vector_block_elements(block: _ConcatBlockValue) -> list[AetherValue]:
    return [row[0] for row in block.rows]


def _default_plot_mode(mode: str | None) -> str:
    token = (mode or os.environ.get("AETHER_PLOT_MODE") or "interactive").strip().lower()
    return "document" if token == "document" else "interactive"


def _default_plot_output_dir(output_dir: str | Path | None) -> str | Path:
    return output_dir or os.environ.get("AETHER_PLOT_DIR") or "."


def _convert_scalar_input_text(text: str, target_type: AetherType) -> AetherValue:
    if target_type == "string":
        return AetherValue("string", text)
    stripped = text.strip()
    try:
        if target_type == "int":
            if not stripped or stripped.lstrip("+-").isdigit() is False:
                raise ValueError
            return AetherValue("int", int(stripped, 10))
        if target_type == "float":
            return AetherValue("float", float(stripped))
        if target_type == "boolean":
            if stripped == "true":
                return AetherValue("boolean", True)
            if stripped == "false":
                return AetherValue("boolean", False)
            raise ValueError
    except ValueError as exc:
        raise AetherInputError(
            f'cannot convert "{text}" to {type_to_string(target_type)}',
            hint=_input_conversion_hint(target_type),
            kind="input",
        ) from exc
    raise AetherInputError(
        f"input() supports int, float, string, boolean, Vector, and Matrix targets, got '{type_to_string(target_type)}'.",
        hint="use input() only with a supported scalar, Vector<T>, or Matrix<T> target.",
        kind="input",
    )


def _input_conversion_hint(target_type: AetherType) -> str | None:
    if target_type == "int":
        return "enter a whole number, for example 42."
    if target_type == "float":
        return "enter a numeric value, for example 3.14."
    if target_type == "boolean":
        return "enter exactly true or false."
    return None


def _raw_error_message(exc: BaseException) -> str:
    return getattr(exc, "message", str(exc))


def _field_access_path(expression: ast.Expression) -> str | None:
    if isinstance(expression, ast.Identifier):
        return expression.name
    if isinstance(expression, ast.FieldAccess):
        target = _field_access_path(expression.target)
        if target is None:
            return None
        return f"{target}.{expression.field_name}"
    return None


def _field_access_root_name(expression: ast.Expression) -> str | None:
    if isinstance(expression, ast.Identifier):
        return expression.name
    if isinstance(expression, ast.FieldAccess):
        return _field_access_root_name(expression.target)
    return None


def _dotted_call_receiver(callee: str, line: int = 1, column: int = 1) -> tuple[str, ast.Expression, str] | None:
    parts = callee.split(".")
    if len(parts) < 2:
        return None
    root_name = parts[0]
    target: ast.Expression = ast.Identifier(root_name, line, column)
    for part in parts[1:-1]:
        target = ast.FieldAccess(target, part, line, column)
    return root_name, target, parts[-1]


def _assignment_root_name(expression: ast.Expression) -> str | None:
    if isinstance(expression, ast.Identifier):
        return expression.name
    if isinstance(expression, ast.IndexExpression):
        return _assignment_root_name(expression.array)
    if isinstance(expression, ast.SliceExpression):
        return _assignment_root_name(expression.collection)
    if isinstance(expression, ast.MatrixIndexExpression):
        return _assignment_root_name(expression.matrix)
    if isinstance(expression, ast.FieldAccess):
        return _assignment_root_name(expression.target)
    return None


def _with_source_location(exc: AetherError, node: object | None) -> AetherError:
    if exc.message.startswith("Aether panic:"):
        return exc
    line, column = _source_location(node)
    return type(exc)(
        exc.message,
        line=exc.line if isinstance(exc.line, int) else line,
        column=exc.column if isinstance(exc.column, int) else column,
        hint=exc.hint or _hint_for_error_message(exc.message),
        kind=exc.kind or _kind_for_error_message(exc.message),
    )


def _source_location(node: object | None) -> tuple[int, int]:
    if node is None:
        return 1, 1
    line = getattr(node, "line", None)
    column = getattr(node, "column", None)
    if isinstance(line, int) and isinstance(column, int):
        return max(1, line), max(1, column)
    column_position = getattr(node, "column_position", None)
    if isinstance(line, int) and isinstance(column_position, int):
        return max(1, line), max(1, column_position)
    return 1, 1


def _hint_for_error_message(message: str) -> str | None:
    lowered = message.lower()
    if "out of bounds" in lowered:
        return "Aether uses zero-based indexing; valid indices run from 0 to length - 1."
    if "undefined variable" in lowered:
        return "declare the variable before using it, or check the spelling."
    if "undefined function" in lowered:
        return "define the function before calling it, import its module, or check the spelling."
    if "expects" in lowered and "arguments" in lowered:
        return "check the function declaration and pass exactly the declared parameters."
    if "divisor zero" in lowered or "division by zero" in lowered:
        return "check the divisor before performing the operation."
    if "same shape" in lowered and "matri" in lowered:
        return "matrix addition and elementwise operations require equal shapes."
    if "compatible matrix shapes" in lowered or "compatible matrix and vector shapes" in lowered:
        return "matrix multiplication requires the left column count to match the right row count."
    if "requires numeric operands" in lowered or "not defined for" in lowered:
        return "check operand types or use an explicit conversion before applying the operator."
    return None


def _kind_for_error_message(message: str) -> str | None:
    lowered = message.lower()
    if "input()" in lowered or "cannot convert" in lowered:
        return "input"
    if "undefined variable" in lowered or "undefined function" in lowered:
        return "name"
    if "out of bounds" in lowered:
        return "index"
    if "shape" in lowered or "length" in lowered:
        return "shape"
    if "argument" in lowered:
        return "arity"
    if "operator" in lowered or "operand" in lowered:
        return "operator"
    return None


def _is_supported_input_target_type(type_name: AetherType) -> bool:
    return type_name in {"int", "float", "string", "boolean"} or isinstance(type_name, (VectorType, MatrixType))


def _iterable_values(value: AetherValue) -> list[AetherValue] | AetherRange:
    if isinstance(value.type_name, RangeType):
        if not isinstance(value.value, AetherRange):
            raise AetherRuntimeError("Invalid range value.")
        return value.value
    if isinstance(value.type_name, ArrayType):
        return list(value.value)
    if isinstance(value.type_name, ListType):
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


def _index_base(type_name: AetherType) -> int:
    if isinstance(type_name, (VectorType, TransposeVectorType, MatrixType)):
        return 1
    return 0


def _indexable_label(type_name: AetherType) -> str:
    if isinstance(type_name, ListType):
        return "List"
    if isinstance(type_name, (VectorType, TransposeVectorType)):
        return "Vector"
    if isinstance(type_name, MatrixType):
        return "Vector" if type_name.vector else "Matrix"
    return "Array"


def _base_label(base: int) -> str:
    return "1-based" if base == 1 else "0-based"


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


def _list_type_from_values(elements: list[AetherValue]) -> ListType:
    element_types = [element.type_name for element in elements]
    primitive_types = [element_type for element_type in element_types if isinstance(element_type, str)]
    list_types = [element_type for element_type in element_types if isinstance(element_type, ListType)]
    array_types = [element_type for element_type in element_types if isinstance(element_type, ArrayType)]
    structured_types = [
        element_type
        for element_type in element_types
        if not isinstance(element_type, (str, ArrayType, ListType))
    ]
    groups = sum(bool(group) for group in (primitive_types, list_types, array_types, structured_types))
    if groups != 1:
        raise AetherTypeError("List literals must contain homogeneous compatible element types.")
    if primitive_types:
        return ListType(_common_list_primitive_type(primitive_types))
    if list_types:
        first = list_types[0]
        if all(element_type == first for element_type in list_types):
            return ListType(first)
    if array_types:
        first = array_types[0]
        if all(element_type == first for element_type in array_types):
            return ListType(first)
    if structured_types:
        first = structured_types[0]
        if all(element_type == first for element_type in structured_types):
            return ListType(first)
    raise AetherTypeError("List literals must contain homogeneous compatible element types.")


def _vector_to_matrix_value(value: AetherValue) -> AetherValue:
    if not isinstance(value.type_name, VectorType):
        raise AetherTypeError(f"Expected vector type, got '{type_to_string(value.type_name)}'.")
    row_type = ArrayType(value.type_name.element_type)
    if value.type_name.orientation == "row":
        rows = [AetherValue(row_type, list(value.value))]
        return AetherValue(MatrixType(value.type_name.element_type, 1, len(value.value)), rows)
    rows = [AetherValue(row_type, [element]) for element in value.value]
    return AetherValue(MatrixType(value.type_name.element_type, len(value.value), 1, vector=True), rows)


def _common_primitive_type(primitive_types: list[AetherType]) -> str:
    if not all(isinstance(type_name, str) for type_name in primitive_types):
        raise AetherTypeError("Array literals must contain homogeneous compatible element types.")
    unique_types = set(primitive_types)
    if len(unique_types) == 1:
        return primitive_types[0]
    if unique_types <= NUMERIC_TYPES:
        if "complex" in unique_types:
            return "complex"
        if "double" in unique_types:
            return "double"
        if "float" in unique_types:
            return "float"
        return "int"
    raise AetherTypeError("Array literals must contain homogeneous compatible element types.")


def _common_list_primitive_type(primitive_types: list[AetherType]) -> str:
    try:
        return _common_primitive_type(primitive_types)
    except AetherTypeError as exc:
        raise AetherTypeError("List literals must contain homogeneous compatible element types.") from exc


def _types_comparable_for_equality(left_type: AetherType, right_type: AetherType) -> bool:
    if left_type == right_type:
        return True
    if isinstance(left_type, NullType):
        return isinstance(right_type, NullableType)
    if isinstance(right_type, NullType):
        return isinstance(left_type, NullableType)
    if isinstance(left_type, NullableType) and isinstance(right_type, NullableType):
        return _types_comparable_for_equality(left_type.base_type, right_type.base_type)
    if isinstance(left_type, NullableType):
        return _types_comparable_for_equality(left_type.base_type, right_type)
    if isinstance(right_type, NullableType):
        return _types_comparable_for_equality(left_type, right_type.base_type)
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
    if isinstance(left_type, ListType) and isinstance(right_type, ListType):
        return _types_comparable_for_equality(left_type.element_type, right_type.element_type)
    if isinstance(left_type, MatrixType) and isinstance(right_type, MatrixType):
        return left_type.rows == right_type.rows and left_type.cols == right_type.cols and _types_comparable_for_equality(
            left_type.element_type,
            right_type.element_type,
        )
    if (
        is_array_type(left_type)
        or is_array_type(right_type)
        or is_list_type(left_type)
        or is_list_type(right_type)
        or is_matrix_type(left_type)
        or is_matrix_type(right_type)
    ):
        return False
    return left_type in NUMERIC_TYPES and right_type in NUMERIC_TYPES


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
        if left.type_name.orientation == "row" and right.type_name.orientation == "column":
            return _dot_product(left, right)
        if left.type_name.orientation == "column" and right.type_name.orientation == "row":
            return matmul_builtin([left, right])
        raise AetherTypeError(
            "Operator '*' between Vector operands is only defined for Vector<Row> * Vector<Column> "
            "or Vector<Column> * Vector<Row>; "
            "use Math.LinearAlgebra.matmul(...) for other algebraic products or '.*' for elementwise multiplication."
        )
    if isinstance(left.type_name, VectorType) and isinstance(right.type_name, MatrixType):
        if left.type_name.orientation == "row":
            return matmul_builtin([left, right])
        raise AetherTypeError("Operator '*' does not implement Column * Matrix.")
    if isinstance(left.type_name, MatrixType) and isinstance(right.type_name, MatrixType):
        return matmul_builtin([left, right])
    if isinstance(left.type_name, MatrixType) and isinstance(right.type_name, VectorType):
        if right.type_name.orientation != "column":
            raise AetherTypeError("Operator '*' is only defined for Matrix * Vector<Column>, not Matrix * Vector<Row>.")
        return matmul_builtin([left, right])
    if isinstance(left.type_name, TransposeVectorType) and isinstance(right.type_name, VectorType):
        return _dot_product(left.value, right)
    if isinstance(left.type_name, TransposeVectorType) and isinstance(right.type_name, MatrixType):
        return _transpose_vector_matrix_multiply(left.value, right)
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


def _negate_value(value: AetherValue) -> AetherValue:
    if value.type_name == "int":
        try:
            return AetherValue("int", checked_int_negate(value.value))
        except OverflowError as exc:
            raise AetherRuntimeError(str(exc)) from exc
    if value.type_name in NUMERIC_TYPES:
        return AetherValue(value.type_name, -value.value)
    if isinstance(value.type_name, VectorType):
        return _negate_vector(value)
    if isinstance(value.type_name, TransposeVectorType):
        vector = _negate_vector(value.value)
        return AetherValue(TransposeVectorType(vector.type_name.element_type, len(vector.value)), vector)
    if isinstance(value.type_name, MatrixType):
        return _negate_matrix(value)
    raise AetherTypeError("Unary '-' requires a numeric operand.")


def _negate_vector(vector: AetherValue) -> AetherValue:
    element_type = _numeric_vector_scalar_type(vector.type_name)
    return AetherValue(
        VectorType(element_type, len(vector.value)),
        [AetherValue(element.type_name, -element.value) for element in vector.value],
    )


def _negate_matrix(matrix: AetherValue) -> AetherValue:
    element_type = _numeric_matrix_scalar_type(matrix.type_name)
    row_type = ArrayType(element_type)
    rows = [
        AetherValue(
            row_type,
            [AetherValue(element.type_name, -element.value) for element in row.value],
        )
        for row in matrix.value
    ]
    return AetherValue(
        MatrixType(element_type, matrix.type_name.rows, matrix.type_name.cols, matrix.type_name.vector),
        rows,
    )


def _scale_vector(vector: AetherValue, scalar: AetherValue) -> AetherValue:
    if not isinstance(vector.type_name, VectorType) or scalar.type_name not in NUMERIC_TYPES:
        raise AetherTypeError("Vector scaling requires a numeric scalar and a numeric vector.")
    if vector.type_name.element_type not in NUMERIC_TYPES:
        raise AetherTypeError("Vector operations require numeric elements.")
    result_element_type = promote_numeric(vector.type_name.element_type, scalar.type_name, "*")
    return AetherValue(
        VectorType(result_element_type, len(vector.value), vector.type_name.orientation),
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


def _transpose_vector_matrix_multiply(left_transpose: AetherValue, matrix: AetherValue) -> AetherValue:
    left = left_transpose
    rows, cols = _matrix_shape(matrix)
    if len(left.value) != rows:
        raise AetherTypeError(f"Operator '*' requires compatible row Vector and Matrix shapes, got {len(left.value)} and {rows}x{cols}.")
    left_element_type = _numeric_vector_scalar_type(left.type_name)
    matrix_element_type = _numeric_matrix_scalar_type(matrix.type_name)
    result_element_type = promote_numeric(left_element_type, matrix_element_type, "*")
    result: list[AetherValue] = []
    for col_index in range(cols):
        total = 0
        for row_index in range(rows):
            total += left.value[row_index].value * matrix.value[row_index].value[col_index].value
        result.append(_coerced_numeric_result(total, result_element_type))
    vector = AetherValue(VectorType(result_element_type, len(result), "row"), result)
    return AetherValue(TransposeVectorType(result_element_type, len(result)), vector)


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
    if result_type == "complex":
        return AetherValue("complex", complex(value))  # type: ignore[arg-type]
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
        if scalar_value.value == 0:
            raise AetherRuntimeError("Operator '/' is undefined for divisor zero.", kind="arithmetic")
        result = element.value / scalar_value.value
    else:
        raise AetherRuntimeError(f"Unsupported scalar array operator '{operator}'.")
    return _coerced_numeric_result(result, result_element_type)


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
    return _coerced_numeric_result(result, result_element_type)


def _values_equal(left: AetherValue, right: AetherValue) -> bool:
    if isinstance(left.value, ClassInstance) or isinstance(right.value, ClassInstance):
        raise AetherTypeError("Class equality is not supported yet.")
    if isinstance(left.value, StructInstance) or isinstance(right.value, StructInstance):
        if (
            not isinstance(left.value, StructInstance)
            or not isinstance(right.value, StructInstance)
            or left.value.type_name != right.value.type_name
        ):
            return False
        return all(
            _values_equal(left.value.fields[field_name], right.value.fields[field_name])
            for field_name in left.value.field_order
        )
    if isinstance(left.type_name, NullableType):
        if left.value is None:
            return right.value is None
        left = AetherValue(left.type_name.base_type, left.value)
    if isinstance(right.type_name, NullableType):
        if right.value is None:
            return left.value is None
        right = AetherValue(right.type_name.base_type, right.value)
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
    if isinstance(left.type_name, ListType) and isinstance(right.type_name, ListType):
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
