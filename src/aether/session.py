from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path

from . import ast
from .interpreter import Function, Interpreter
from .lexer import lex
from .parser import Parser
from .result import AetherRunResult
from .symbols import FunctionSymbol, VariableSymbol
from .typechecker import TypeChecker
from .formatting import format_value
from .types import AetherValue, ArrayType, MatrixType, TransposeVectorType, TupleType, VectorType, type_to_string


@dataclass(frozen=True)
class _SessionSnapshot:
    checker_variables: dict[str, VariableSymbol]
    checker_functions: dict[str, FunctionSymbol]
    checker_expression_functions: dict[str, ast.ExpressionFunctionDeclaration]
    checker_imported_modules: set[str]
    checker_builtin_aliases: dict[str, str]
    runtime_values: dict[str, AetherValue]
    runtime_functions: dict[str, Function]
    imported_modules: set[str]
    runtime_builtin_aliases: dict[str, str]


class AetherSession:
    """Persistent Aether execution session for REPL-like workflows."""

    def __init__(
        self,
        *,
        plot_mode: str | None = None,
        plot_output_dir: str | Path | None = None,
        output_writer: Callable[[str], None] | None = None,
    ) -> None:
        self._type_checker = TypeChecker()
        self._interpreter = Interpreter(
            plot_mode=plot_mode,
            plot_output_dir=plot_output_dir,
            output_writer=output_writer,
        )

    def run(self, source: str) -> AetherRunResult:
        snapshot = self._snapshot()
        self._interpreter.clear_output()
        try:
            tokens = lex(source)
            program = Parser(tokens).parse()
            self._type_checker.check(program)
            env = self._interpreter.interpret(program)
        except Exception:
            self._restore(snapshot)
            raise
        return AetherRunResult(env=dict(env.values), output=self._interpreter.output)

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
            checker_functions=deepcopy(self._type_checker.functions),
            checker_expression_functions=deepcopy(self._type_checker.expression_functions),
            checker_imported_modules=deepcopy(self._type_checker.imported_modules),
            checker_builtin_aliases=deepcopy(self._type_checker.builtin_aliases),
            runtime_values=deepcopy(self._interpreter.global_env.variable_scope.symbols),
            runtime_functions=deepcopy(self._interpreter.global_env.functions),
            imported_modules=deepcopy(self._interpreter.imported_modules),
            runtime_builtin_aliases=deepcopy(self._interpreter.builtin_aliases),
        )

    def _restore(self, snapshot: _SessionSnapshot) -> None:
        self._type_checker.global_scope.symbols = deepcopy(snapshot.checker_variables)
        self._type_checker.functions = deepcopy(snapshot.checker_functions)
        self._type_checker.expression_functions = deepcopy(snapshot.checker_expression_functions)
        self._type_checker.imported_modules = deepcopy(snapshot.checker_imported_modules)
        self._type_checker.builtin_aliases = deepcopy(snapshot.checker_builtin_aliases)
        self._type_checker.expression_function_call_stack.clear()
        self._interpreter.global_env.variable_scope.symbols = deepcopy(snapshot.runtime_values)
        self._interpreter.global_env.functions = deepcopy(snapshot.runtime_functions)
        self._interpreter.imported_modules = deepcopy(snapshot.imported_modules)
        self._interpreter.builtin_aliases = deepcopy(snapshot.runtime_builtin_aliases)


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
    if isinstance(type_name, TupleType):
        return f"{len(value.value)}"
    return "1x1"
