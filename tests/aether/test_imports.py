from __future__ import annotations

import os
from pathlib import Path

import pytest

from aether import run_aether
from aether.errors import AetherTypeError


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

    assert result.output == "[1;\n 2]\n"


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
println(matmul([1 2], [3; 4]));
"""
    )

    assert result.output == "[1 3;\n 2 4]\n11\n"


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
