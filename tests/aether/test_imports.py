from __future__ import annotations

import os
from pathlib import Path

import pytest

from aether import run_aether
from aether.errors import AetherSyntaxError, AetherTypeError
from aether.lexer import lex
from aether.parser import Parser


def test_import_builtin_math_namespaces_is_allowed() -> None:
    result = run_aether("import Math; import Math.LinearAlgebra; println(Math.mod(7, 3));")

    assert result.output == "1\n"


def test_import_builtin_namespace_can_end_with_newline() -> None:
    result = run_aether(
        """
import Math.LinearAlgebra
println(Math.LinearAlgebra.transpose([1 2]));
"""
    )

    assert result.output == "[1; 2]\n"


def test_import_builtin_namespace_can_end_at_eof() -> None:
    result = run_aether("import Math.LinearAlgebra")

    assert result.output == ""


def test_import_builtin_namespace_exposes_unqualified_members() -> None:
    result = run_aether(
        """
import Math.LinearAlgebra
A = [1 2; 3 4];
B = transpose(A);
println(B);
println(transpose([1; 2]));
"""
    )

    assert result.output == "[1 3; 2 4]\n[1 2]\n"


def test_builtin_namespace_members_require_import_for_unqualified_calls() -> None:
    with pytest.raises(AetherTypeError, match="Undefined function 'transpose'"):
        run_aether("transpose([1 2]);")


def test_import_file_from_subfolder_loads_module_source(tmp_path: Path) -> None:
    module_folder = tmp_path / "ejemplos"
    module_folder.mkdir()
    module_path = module_folder / "SistemaLineal.ae"
    module_path.write_text(
        """
        int a = 2;
        int b = 3;
        int sum(int x, int y) {
            return x + y;
        }
        """.strip(),
        encoding="utf-8",
    )

    current_dir = os.getcwd()
    try:
        os.chdir(tmp_path)
        result = run_aether("import ejemplos.SistemaLineal; println(sum(a, b));")
    finally:
        os.chdir(current_dir)

    assert result.output == "5\n"


def test_package_declaration_is_recorded() -> None:
    program = Parser(
        lex(
            """
package My.Module;

public int f(int x) {
    return x + 1;
}
"""
        )
    ).parse()

    assert program.package_name == "My.Module"


def test_import_public_function_from_packaged_file(tmp_path: Path) -> None:
    module_folder = tmp_path / "Math"
    module_folder.mkdir()
    (module_folder / "Utils.ae").write_text(
        """
package Math.Utils;

public int inc(int x) {
    return x + 1;
}
""",
        encoding="utf-8",
    )

    result = run_aether("import Math.Utils;\nprintln(inc(3));", source_root=tmp_path)

    assert result.output == "4\n"


def test_public_function_can_use_private_helper_in_same_package(tmp_path: Path) -> None:
    module_folder = tmp_path / "Math"
    module_folder.mkdir()
    (module_folder / "Utils.ae").write_text(
        """
package Math.Utils;

private int hiddenInc(int x) {
    return x + 1;
}

public int incTwice(int x) {
    return hiddenInc(hiddenInc(x));
}
""",
        encoding="utf-8",
    )

    result = run_aether("import Math.Utils;\nprintln(incTwice(3));", source_root=tmp_path)

    assert result.output == "5\n"


def test_imported_public_function_keeps_module_builtin_import_context(tmp_path: Path) -> None:
    (tmp_path / "M.ae").write_text(
        """
package M;
import Math.LinearAlgebra;

public double len(Vector<double, Column> v) {
    return norm(v);
}
""",
        encoding="utf-8",
    )

    result = run_aether("import M;\nprintln(len([3; 4]));", source_root=tmp_path)

    assert result.output == "5.0\n"


def test_imported_public_function_keeps_private_type_alias_context(tmp_path: Path) -> None:
    (tmp_path / "M.ae").write_text(
        """
package M;

private alias Real = double;

public Real twice(Real x) {
    return x * 2.0;
}
""",
        encoding="utf-8",
    )

    result = run_aether("import M;\nprintln(twice(2.5));", source_root=tmp_path)

    assert result.output == "5.0\n"


def test_private_function_is_not_exported_from_packaged_file(tmp_path: Path) -> None:
    module_folder = tmp_path / "Math"
    module_folder.mkdir()
    (module_folder / "Utils.ae").write_text(
        """
package Math.Utils;

private int hidden(int x) {
    return x * x;
}
""",
        encoding="utf-8",
    )

    with pytest.raises(AetherTypeError, match="private"):
        run_aether("import Math.Utils;\nprintln(hidden(3));", source_root=tmp_path)


def test_default_visibility_is_private_inside_package(tmp_path: Path) -> None:
    module_folder = tmp_path / "Math"
    module_folder.mkdir()
    (module_folder / "Utils.ae").write_text(
        """
package Math.Utils;

int hidden(int x) {
    return x * x;
}
""",
        encoding="utf-8",
    )

    with pytest.raises(AetherTypeError, match="private"):
        run_aether("import Math.Utils;\nprintln(hidden(3));", source_root=tmp_path)


def test_public_alias_is_imported_from_package(tmp_path: Path) -> None:
    module_folder = tmp_path / "Math"
    module_folder.mkdir()
    (module_folder / "Types.ae").write_text(
        """
package Math.Types;

public alias Real = double;
""",
        encoding="utf-8",
    )

    result = run_aether("import Math.Types;\nReal x = 2.5;\nprintln(x);", source_root=tmp_path)

    assert result.output == "2.5\n"


def test_public_const_is_imported_from_package(tmp_path: Path) -> None:
    (tmp_path / "Config.ae").write_text(
        """
package Config;

public const int DEFAULT_ITER = 100;
""",
        encoding="utf-8",
    )

    result = run_aether("import Config;\nprintln(DEFAULT_ITER);", source_root=tmp_path)

    assert result.output == "100\n"


def test_missing_file_module_import_reports_clear_error(tmp_path: Path) -> None:
    with pytest.raises(AetherTypeError, match="Module 'Does.Not.Exist' not found"):
        run_aether("import Does.Not.Exist;", source_root=tmp_path)


def test_duplicate_package_declaration_fails() -> None:
    with pytest.raises(AetherSyntaxError, match="Duplicate package declaration"):
        Parser(lex("package A;\npackage B;\n")).parse()


def test_package_after_declaration_fails() -> None:
    with pytest.raises(AetherSyntaxError, match="Package declaration must appear before"):
        Parser(lex("x = 1;\npackage A;\n")).parse()


def test_file_import_cycle_fails(tmp_path: Path) -> None:
    (tmp_path / "A.ae").write_text("package A;\nimport B;\npublic int a() { return 1; }\n", encoding="utf-8")
    (tmp_path / "B.ae").write_text("package B;\nimport A;\npublic int b() { return 2; }\n", encoding="utf-8")

    with pytest.raises(AetherTypeError, match="Cyclic import involving 'A'"):
        run_aether("import A;", source_root=tmp_path)


def test_collision_between_file_imports_fails(tmp_path: Path) -> None:
    (tmp_path / "A.ae").write_text("package A;\npublic int f(int x) { return x + 1; }\n", encoding="utf-8")
    (tmp_path / "B.ae").write_text("package B;\npublic int f(int x) { return x + 2; }\n", encoding="utf-8")

    with pytest.raises(AetherTypeError, match="Import collision for symbol 'f'"):
        run_aether("import A;\nimport B;\nprintln(f(3));", source_root=tmp_path)


def test_collision_between_local_symbol_and_import_fails(tmp_path: Path) -> None:
    (tmp_path / "A.ae").write_text("package A;\npublic int f(int x) { return x + 1; }\n", encoding="utf-8")

    with pytest.raises(AetherTypeError, match="conflicts with an existing symbol"):
        run_aether("int f = 1;\nimport A;", source_root=tmp_path)


def test_script_without_package_keeps_legacy_file_import_exports(tmp_path: Path) -> None:
    (tmp_path / "Legacy.ae").write_text(
        """
int a = 2;
int doubleIt(int x) {
    return x * 2;
}
""",
        encoding="utf-8",
    )

    result = run_aether("import Legacy;\nprintln(doubleIt(a));", source_root=tmp_path)

    assert result.output == "4\n"
