from __future__ import annotations

from pathlib import Path

import pytest

from aether.errors import AetherSyntaxError, AetherTypeError
from aether.runner import run_aether


def test_enum_declaration_and_assignment_prints_variant() -> None:
    result = run_aether(
        """
enum SolverStatus {
    Converged,
    MaxIterations,
    SingularMatrix
}

SolverStatus s = SolverStatus.Converged;
println(s);
"""
    )

    assert result.output == "SolverStatus.Converged\n"


def test_enum_equality_and_inequality() -> None:
    result = run_aether(
        """
enum SolverStatus {
    Converged,
    MaxIterations
}

println(SolverStatus.Converged == SolverStatus.Converged);
println(SolverStatus.Converged != SolverStatus.MaxIterations);
"""
    )

    assert result.output == "true\ntrue\n"


def test_comparing_distinct_enums_fails() -> None:
    with pytest.raises(AetherTypeError, match="Cannot compare 'SolverStatus' and 'OtherStatus'"):
        run_aether(
            """
enum SolverStatus { Converged }
enum OtherStatus { Converged }

println(SolverStatus.Converged == OtherStatus.Converged);
"""
        )


def test_assigning_variant_from_other_enum_fails() -> None:
    with pytest.raises(AetherTypeError, match="Cannot implicitly convert 'OtherStatus' to 'SolverStatus'"):
        run_aether(
            """
enum SolverStatus { Converged }
enum OtherStatus { Converged }

SolverStatus s = OtherStatus.Converged;
"""
        )


@pytest.mark.parametrize("type_name", ["int", "string", "boolean"])
def test_assigning_enum_to_primitive_fails(type_name: str) -> None:
    with pytest.raises(AetherTypeError, match=rf"Cannot implicitly convert 'SolverStatus' to '{type_name}'"):
        run_aether(
            f"""
enum SolverStatus {{ Converged }}

{type_name} value = SolverStatus.Converged;
"""
        )


def test_enum_is_not_boolean_condition() -> None:
    with pytest.raises(AetherTypeError, match="condition of 'if' must be boolean, got 'SolverStatus'"):
        run_aether(
            """
enum SolverStatus { Converged }

if SolverStatus.Converged {
    println("ok");
}
"""
        )


def test_enum_return_value_works() -> None:
    result = run_aether(
        """
enum SolverStatus { Converged }

SolverStatus solve() {
    return SolverStatus.Converged;
}

println(solve());
"""
    )

    assert result.output == "SolverStatus.Converged\n"


def test_enum_argument_works() -> None:
    result = run_aether(
        """
enum SolverStatus { Converged }

void report(SolverStatus s) {
    println(s);
}

report(SolverStatus.Converged);
"""
    )

    assert result.output == "SolverStatus.Converged\n"


def test_struct_field_can_use_enum() -> None:
    result = run_aether(
        """
enum SolverStatus { Converged }

public struct Result {
    SolverStatus status;
}

Result r = Result(SolverStatus.Converged);
println(r.status);
"""
    )

    assert result.output == "SolverStatus.Converged\n"


def test_unknown_enum_variant_fails() -> None:
    with pytest.raises(AetherTypeError, match="Enum 'SolverStatus' has no variant 'Unknown'"):
        run_aether(
            """
enum SolverStatus { Converged }

println(SolverStatus.Unknown);
"""
        )


def test_instantiating_enum_as_function_fails() -> None:
    with pytest.raises(AetherTypeError, match="Cannot instantiate enum 'SolverStatus' as a function"):
        run_aether(
            """
enum SolverStatus { Converged }

SolverStatus();
"""
        )


def test_public_enum_imported_from_package_works(tmp_path: Path) -> None:
    (tmp_path / "Solver.ae").write_text(
        """
package Solver;

public enum SolverStatus {
    Converged,
    MaxIterations
}
""",
        encoding="utf-8",
    )

    result = run_aether(
        """
import Solver;

SolverStatus s = SolverStatus.Converged;
println(s);
""",
        source_root=tmp_path,
    )

    assert result.output == "SolverStatus.Converged\n"


def test_private_enum_is_not_imported_from_package(tmp_path: Path) -> None:
    (tmp_path / "Solver.ae").write_text(
        """
package Solver;

private enum HiddenStatus {
    Secret
}
""",
        encoding="utf-8",
    )

    with pytest.raises(AetherTypeError, match="private"):
        run_aether(
            """
import Solver;

println(HiddenStatus.Secret);
""",
            source_root=tmp_path,
        )


@pytest.mark.parametrize(
    "source",
    [
        "enum E { A }\nint E() { return 1; }\n",
        "enum E { A }\nstruct E { int value; }\n",
        "enum E { A }\nalias E = int;\n",
        "enum E { A }\nconst int E = 1;\n",
    ],
)
def test_enum_top_level_collisions_fail(source: str) -> None:
    with pytest.raises(AetherTypeError, match="already defined|conflicts"):
        run_aether(source)


def test_duplicate_enum_variant_fails() -> None:
    with pytest.raises(AetherSyntaxError, match="Duplicate variant 'A'"):
        run_aether("enum E { A, A }\n")
