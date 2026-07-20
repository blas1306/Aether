from __future__ import annotations

from io import StringIO
from pathlib import Path

import pytest

from aether.cli import (
    EXIT_INTERNAL_COMPILER_ERROR,
    EXIT_INTERRUPTED,
    EXIT_LANGUAGE_ERROR,
    EXIT_SUCCESS,
    main,
)
from aether.ir.verifier import IRVerificationError
from aether.ssa.verifier import SSAVerificationError


def _run(arguments: list[str]) -> tuple[int, str, str]:
    stdout = StringIO()
    stderr = StringIO()
    code = main(arguments, stdin=StringIO(), stdout=stdout, stderr=stderr)
    return code, stdout.getvalue(), stderr.getvalue()


def _source(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "contract.ae"
    path.write_text(text, encoding="utf-8")
    return path


@pytest.mark.parametrize(
    ("text", "heading"),
    [
        ("int main( {\n", "Aether syntax error [AE-SYNTAX-001]"),
        ('int main() { int value = "bad"; return value; }\n', "Aether type error [AE-TYPE-001]"),
        ("class Counter { int value; }\n", "Aether capability error [AE-BACKEND-CLASSES]"),
    ],
)
def test_source_diagnostics_are_categorized_without_traceback(
    tmp_path: Path,
    text: str,
    heading: str,
) -> None:
    path = _source(tmp_path, text)

    code, stdout, stderr = _run(["--check", str(path)])

    assert code == EXIT_LANGUAGE_ERROR
    assert stdout == ""
    assert heading in stderr
    assert "Traceback" not in stderr


def test_check_accepts_native_source_without_codegen(tmp_path: Path, monkeypatch) -> None:
    path = _source(tmp_path, "int main() { return 0; }\n")
    monkeypatch.setattr(
        "aether.ir.lowering.IRLowerer.lower",
        lambda *_args, **_kwargs: pytest.fail("--check reached lowering"),
    )

    assert _run(["--check", str(path)]) == (EXIT_SUCCESS, "", "")


def test_ir_verifier_failure_is_sanitized_ice_and_debug_keeps_cause(
    tmp_path: Path,
    monkeypatch,
) -> None:
    path = _source(tmp_path, "int main() { return 0; }\n")

    def fail(*_args, **_kwargs):
        raise IRVerificationError("secret invalid IR dump")

    monkeypatch.setattr("aether.cli.IRBackend.lower_verified", fail)

    code, _stdout, stderr = _run(["--emit-ir", str(path)])
    assert code == EXIT_INTERNAL_COMPILER_ERROR
    assert "ICE-IR-VERIFY-001" in stderr
    assert "secret invalid IR dump" not in stderr
    assert "Traceback" not in stderr

    code, _stdout, stderr = _run(["--debug", "--emit-ir", str(path)])
    assert code == EXIT_INTERNAL_COMPILER_ERROR
    assert "Phase: IR verification" in stderr
    assert "Traceback" in stderr
    assert "IRVerificationError: secret invalid IR dump" in stderr


def test_ssa_verifier_failure_is_sanitized_ice(tmp_path: Path, monkeypatch) -> None:
    path = _source(tmp_path, "int main() { return 0; }\n")

    def fail(*_args, **_kwargs):
        raise SSAVerificationError("secret invalid SSA dump")

    monkeypatch.setattr("aether.cli.lower_to_verified_ssa", fail)
    code, _stdout, stderr = _run(["--emit-ssa", str(path)])

    assert code == EXIT_INTERNAL_COMPILER_ERROR
    assert "ICE-SSA-VERIFY-001" in stderr
    assert "secret invalid SSA dump" not in stderr
    assert "Traceback" not in stderr


def test_unexpected_exception_and_keyboard_interrupt_have_distinct_boundaries(
    tmp_path: Path,
    monkeypatch,
) -> None:
    path = _source(tmp_path, "int main() { return 0; }\n")

    monkeypatch.setattr(
        "aether.cli._print_ast",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("private detail")),
    )
    code, _stdout, stderr = _run(["--ast", str(path)])
    assert code == EXIT_INTERNAL_COMPILER_ERROR
    assert "ICE-UNEXPECTED-001" in stderr
    assert "private detail" not in stderr
    assert "Traceback" not in stderr

    monkeypatch.setattr(
        "aether.cli._print_ast",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(KeyboardInterrupt()),
    )
    code, _stdout, stderr = _run(["--ast", str(path)])
    assert code == EXIT_INTERRUPTED
    assert stderr == "Aether interrupted.\n"
