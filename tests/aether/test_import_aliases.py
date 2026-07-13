from __future__ import annotations

from pathlib import Path

import pytest

from aether import run_aether
from aether.ast import FromImportStatement, ImportStatement
from aether.errors import AetherSyntaxError, AetherTypeError
from aether.lexer import lex
from aether.parser import Parser


SOLVE_INPUT = "[2 0; 0 4], [2; 8]"


@pytest.mark.parametrize(
    ("import_source", "call"),
    [
        ("import Math.LinearAlgebra;", "Math.LinearAlgebra.solve"),
        ("import Math.LinearAlgebra as LA;", "LA.solve"),
        ("from Math.LinearAlgebra import solve;", "solve"),
        ("from Math.LinearAlgebra import solve as linearSolve;", "linearSolve"),
        ("from Math import LinearAlgebra;", "LinearAlgebra.solve"),
        ("from Math import LinearAlgebra as LA;", "LA.solve"),
    ],
)
def test_import_forms_resolve_solve(import_source: str, call: str) -> None:
    result = run_aether(f"{import_source}\nprintln({call}({SOLVE_INPUT}));")

    assert result.output == "[1.0 2.0]\n"


def test_import_ast_preserves_paths_aliases_and_locations() -> None:
    program = Parser(
        lex("import Math.LinearAlgebra as LA;\nfrom Math.LinearAlgebra import solve as linearSolve;")
    ).parse()

    module_import = program.statements[0]
    assert isinstance(module_import, ImportStatement)
    assert module_import.module_path == ("Math", "LinearAlgebra")
    assert module_import.module_name == "Math.LinearAlgebra"
    assert module_import.local_binding == "LA"
    assert (module_import.alias_line, module_import.alias_column) == (1, 30)

    symbol_import = program.statements[1]
    assert isinstance(symbol_import, FromImportStatement)
    assert symbol_import.module_path == ("Math", "LinearAlgebra")
    assert symbol_import.symbol == "solve"
    assert symbol_import.local_binding == "linearSolve"
    assert (symbol_import.symbol_line, symbol_import.symbol_column) == (2, 32)


@pytest.mark.parametrize("keyword", ["from", "as"])
def test_new_import_keywords_are_reserved(keyword: str) -> None:
    with pytest.raises(AetherSyntaxError):
        Parser(lex(f"int {keyword} = 1;")).parse()


def test_plain_module_import_does_not_expose_members_unqualified() -> None:
    with pytest.raises(AetherTypeError, match="Undefined function 'solve'"):
        run_aether(f"import Math.LinearAlgebra; solve({SOLVE_INPUT});")


def test_module_alias_hides_original_qualified_binding() -> None:
    with pytest.raises(AetherTypeError, match="Undefined function 'Math.LinearAlgebra.solve'"):
        run_aether(f"import Math.LinearAlgebra as LA; Math.LinearAlgebra.solve({SOLVE_INPUT});")


def test_qualified_builtin_requires_a_visible_module_binding() -> None:
    with pytest.raises(AetherTypeError, match="Undefined function 'Math.LinearAlgebra.solve'"):
        run_aether(f"Math.LinearAlgebra.solve({SOLVE_INPUT});")


def test_ordinary_variable_cannot_masquerade_as_module() -> None:
    with pytest.raises(AetherTypeError, match="no native method 'solve'"):
        run_aether(f"int LA = 5; LA.solve({SOLVE_INPUT});")


def test_symbol_alias_hides_original_symbol() -> None:
    with pytest.raises(AetherTypeError, match="Undefined function 'solve'"):
        run_aether(f"from Math.LinearAlgebra import solve as linearSolve; solve({SOLVE_INPUT});")


def test_canonical_and_alias_module_bindings_can_coexist() -> None:
    result = run_aether(
        f"import Math.LinearAlgebra; import Math.LinearAlgebra as LA; "
        f"println(Math.LinearAlgebra.solve({SOLVE_INPUT})); println(LA.solve({SOLVE_INPUT}));"
    )

    assert result.output == "[1.0 2.0]\n[1.0 2.0]\n"


@pytest.mark.parametrize(
    "source",
    [
        "import Math.LinearAlgebra as LA; int LA = 5;",
        "int LA = 5; import Math.LinearAlgebra as LA;",
        "from Math.LinearAlgebra import solve; int solve(int x) { return x; }",
        "int solve(int x) { return x; } from Math.LinearAlgebra import solve;",
        "import Math.LinearAlgebra as M; import Math as M;",
        "import Math.LinearAlgebra as LA; import Math.LinearAlgebra as LA;",
    ],
)
def test_import_collisions_are_order_independent(source: str) -> None:
    with pytest.raises(AetherTypeError, match=r"Symbol '.+' is already defined in this scope"):
        run_aether(source)


def test_wildcard_and_multiple_symbol_imports_are_rejected() -> None:
    with pytest.raises(AetherSyntaxError, match="Wildcard imports are not supported"):
        Parser(lex("from Math.LinearAlgebra import *;")).parse()
    with pytest.raises(AetherSyntaxError, match="Expected ';' or newline"):
        Parser(lex("from Math.LinearAlgebra import solve, norm;")).parse()


@pytest.mark.parametrize(
    "import_source",
    [
        "import Math.LinearAlgebra;",
        "import Math.LinearAlgebra as LA;",
        "from Math.LinearAlgebra import solve;",
        "from Math.LinearAlgebra import norm;",
        "from Math import LinearAlgebra as LA;",
    ],
)
def test_any_successful_provider_import_enables_leftdivide(import_source: str) -> None:
    result = run_aether(f"{import_source}\nx = [2 0; 0 4] \\ [2; 8];\nprintln(x);")

    assert result.output == "[1.0 2.0]\n"


def test_file_module_exports_are_explicitly_bound(tmp_path: Path) -> None:
    (tmp_path / "Tools.ae").write_text(
        """
package Tools;
public const int OFFSET = 2;
public alias Real = double;
public int inc(int x) { return x + OFFSET; }
private int hidden(int x) { return x; }
""",
        encoding="utf-8",
    )

    assert run_aether("import Tools as T; println(T.inc(3)); println(T.OFFSET);", source_root=tmp_path).output == "5\n2\n"
    assert run_aether("from Tools import inc as plus; println(plus(3));", source_root=tmp_path).output == "5\n"
    assert run_aether("from Tools import OFFSET; println(OFFSET);", source_root=tmp_path).output == "2\n"
    assert run_aether("from Tools import Real; Real x = 2.5; println(x);", source_root=tmp_path).output == "2.5\n"


def test_missing_and_private_file_exports_report_import_errors(tmp_path: Path) -> None:
    (tmp_path / "Tools.ae").write_text(
        "package Tools; private int hidden(int x) { return x; }",
        encoding="utf-8",
    )

    with pytest.raises(AetherTypeError, match="is not public in module 'Tools'"):
        run_aether("from Tools import hidden;", source_root=tmp_path)
    with pytest.raises(AetherTypeError, match="has no exported symbol 'missing'"):
        run_aether("from Tools import missing;", source_root=tmp_path)


def test_qualified_module_access_supports_exported_enums(tmp_path: Path) -> None:
    (tmp_path / "Solver.ae").write_text(
        "package Solver; public enum Status { Ok, Failed }",
        encoding="utf-8",
    )

    result = run_aether("import Solver; println(Solver.Status.Ok);", source_root=tmp_path)

    assert result.output == "Status.Ok\n"


def test_imported_function_keeps_its_qualified_module_context(tmp_path: Path) -> None:
    (tmp_path / "Config.ae").write_text(
        "package Config; public const int OFFSET = 4;",
        encoding="utf-8",
    )
    (tmp_path / "Wrapper.ae").write_text(
        """
package Wrapper;
import Config as C;
public int offset() { return C.OFFSET; }
""",
        encoding="utf-8",
    )

    result = run_aether("import Wrapper as W; println(W.offset());", source_root=tmp_path)

    assert result.output == "4\n"
