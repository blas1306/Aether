from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path

from . import ast
from .interpreter import Function, Interpreter
from .pipeline import execute_pipeline
from .result import AetherRunResult
from .symbols import EnumSymbol, FunctionSymbol, StructSymbol, VariableSymbol
from .typechecker import TypeChecker
from .formatting import format_value
from .types import AetherType, AetherValue, ArrayType, ListType, MatrixType, TransposeVectorType, TupleType, VectorType, type_to_string


@dataclass(frozen=True)
class _SessionSnapshot:
    checker_variables: dict[str, VariableSymbol]
    checker_constants: set[str]
    checker_functions: dict[str, FunctionSymbol]
    checker_structs: dict[str, StructSymbol]
    checker_enums: dict[str, EnumSymbol]
    checker_expression_functions: dict[str, ast.ExpressionFunctionDeclaration]
    checker_imported_modules: set[str]
    checker_builtin_aliases: dict[str, str]
    checker_builtin_constant_aliases: dict[str, str]
    checker_type_aliases: dict[str, AetherType]
    checker_imported_symbol_origins: dict[str, str]
    checker_private_imported_symbols: dict[str, set[str]]
    runtime_values: dict[str, AetherValue]
    runtime_constants: set[str]
    runtime_functions: dict[str, Function]
    runtime_structs: dict[str, ast.StructDeclaration]
    runtime_enums: dict[str, ast.EnumDeclaration]
    imported_modules: set[str]
    runtime_builtin_aliases: dict[str, str]
    runtime_builtin_constant_aliases: dict[str, str]
    runtime_type_aliases: dict[str, AetherType]
    runtime_imported_symbol_origins: dict[str, str]
    runtime_private_imported_symbols: dict[str, set[str]]


class AetherSession:
    """Persistent Aether execution session for REPL-like workflows."""

    def __init__(
        self,
        *,
        source_root: str | Path | None = None,
        plot_mode: str | None = None,
        plot_output_dir: str | Path | None = None,
        output_writer: Callable[[str], None] | None = None,
        input_reader: Callable[[], str] | None = None,
    ) -> None:
        self._type_checker = TypeChecker(source_root=source_root)
        self._interpreter = Interpreter(
            source_root=source_root,
            plot_mode=plot_mode,
            plot_output_dir=plot_output_dir,
            output_writer=output_writer,
            input_reader=input_reader,
        )

    def run(self, source: str) -> AetherRunResult:
        snapshot = self._snapshot()
        self._interpreter.clear_output()
        try:
            env = execute_pipeline(
                source,
                type_checker=self._type_checker,
                interpreter=self._interpreter,
            )
        except Exception:
            self._restore(snapshot)
            raise
        return AetherRunResult(
            env=dict(env.values),
            output=self._interpreter.output,
            exit_code=self._interpreter.last_exit_code,
        )

    def workspace_values(self) -> dict[str, AetherValue]:
        return dict(self._interpreter.global_env.values)

    def workspace_snapshot(self) -> list[dict[str, str]]:
        rows: list[dict[str, str]] = []
        for name, value in sorted(self.workspace_values().items()):
            shape = _value_shape(value)
            type_label = type_to_string(value.type_name)
            rows.append(
                {
                    "name": name,
                    "type": type_label,
                    "shape": shape,
                    "class": type_label,
                    "size": shape,
                    "summary": format_value(value),
                }
            )
        return rows

    def _snapshot(self) -> _SessionSnapshot:
        return _SessionSnapshot(
            checker_variables=deepcopy(self._type_checker.global_scope.symbols),
            checker_constants=deepcopy(self._type_checker.global_scope.constants),
            checker_functions=deepcopy(self._type_checker.functions),
            checker_structs=deepcopy(self._type_checker.structs),
            checker_enums=deepcopy(self._type_checker.enums),
            checker_expression_functions=deepcopy(self._type_checker.expression_functions),
            checker_imported_modules=deepcopy(self._type_checker.imported_modules),
            checker_builtin_aliases=deepcopy(self._type_checker.builtin_aliases),
            checker_builtin_constant_aliases=deepcopy(self._type_checker.builtin_constant_aliases),
            checker_type_aliases=deepcopy(self._type_checker.type_aliases),
            checker_imported_symbol_origins=deepcopy(self._type_checker.imported_symbol_origins),
            checker_private_imported_symbols=deepcopy(self._type_checker.private_imported_symbols),
            runtime_values=deepcopy(self._interpreter.global_env.variable_scope.symbols),
            runtime_constants=deepcopy(self._interpreter.global_env.variable_scope.constants),
            runtime_functions=deepcopy(self._interpreter.global_env.functions),
            runtime_structs=deepcopy(self._interpreter.structs),
            runtime_enums=deepcopy(self._interpreter.enums),
            imported_modules=deepcopy(self._interpreter.imported_modules),
            runtime_builtin_aliases=deepcopy(self._interpreter.builtin_aliases),
            runtime_builtin_constant_aliases=deepcopy(self._interpreter.builtin_constant_aliases),
            runtime_type_aliases=deepcopy(self._interpreter.type_aliases),
            runtime_imported_symbol_origins=deepcopy(self._interpreter.imported_symbol_origins),
            runtime_private_imported_symbols=deepcopy(self._interpreter.private_imported_symbols),
        )

    def _restore(self, snapshot: _SessionSnapshot) -> None:
        self._type_checker.global_scope.symbols = deepcopy(snapshot.checker_variables)
        self._type_checker.global_scope.constants = deepcopy(snapshot.checker_constants)
        self._type_checker.functions = deepcopy(snapshot.checker_functions)
        self._type_checker.structs = deepcopy(snapshot.checker_structs)
        self._type_checker.enums = deepcopy(snapshot.checker_enums)
        self._type_checker.expression_functions = deepcopy(snapshot.checker_expression_functions)
        self._type_checker.imported_modules = deepcopy(snapshot.checker_imported_modules)
        self._type_checker.builtin_aliases = deepcopy(snapshot.checker_builtin_aliases)
        self._type_checker.builtin_constant_aliases = deepcopy(snapshot.checker_builtin_constant_aliases)
        self._type_checker.type_aliases = deepcopy(snapshot.checker_type_aliases)
        self._type_checker.imported_symbol_origins = deepcopy(snapshot.checker_imported_symbol_origins)
        self._type_checker.private_imported_symbols = deepcopy(snapshot.checker_private_imported_symbols)
        self._type_checker.expression_function_call_stack.clear()
        self._interpreter.global_env.variable_scope.symbols = deepcopy(snapshot.runtime_values)
        self._interpreter.global_env.variable_scope.constants = deepcopy(snapshot.runtime_constants)
        self._interpreter.global_env.functions = deepcopy(snapshot.runtime_functions)
        self._interpreter.structs = deepcopy(snapshot.runtime_structs)
        self._interpreter.enums = deepcopy(snapshot.runtime_enums)
        self._interpreter.imported_modules = deepcopy(snapshot.imported_modules)
        self._interpreter.builtin_aliases = deepcopy(snapshot.runtime_builtin_aliases)
        self._interpreter.builtin_constant_aliases = deepcopy(snapshot.runtime_builtin_constant_aliases)
        self._interpreter.type_aliases = deepcopy(snapshot.runtime_type_aliases)
        self._interpreter.imported_symbol_origins = deepcopy(snapshot.runtime_imported_symbol_origins)
        self._interpreter.private_imported_symbols = deepcopy(snapshot.runtime_private_imported_symbols)


def _value_shape(value: AetherValue) -> str:
    type_name = value.type_name
    if isinstance(type_name, MatrixType):
        rows = type_name.rows
        cols = type_name.cols
        if rows is None:
            rows = len(value.value)
        if cols is None:
            cols = len(value.value[0].value) if value.value else 0
        return f"{rows}x{cols}"
    if isinstance(type_name, TransposeVectorType):
        return f"{len(value.value.value)}"
    if isinstance(type_name, VectorType):
        return f"{len(value.value)}"
    if isinstance(type_name, ArrayType):
        return f"{len(value.value)}"
    if isinstance(type_name, ListType):
        return f"{len(value.value)}"
    if isinstance(type_name, TupleType):
        return f"{len(value.value)}"
    return "1x1"
