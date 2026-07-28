#!/usr/bin/env python3
"""Deterministic release gate for Aether's public diagnostic boundary."""

from __future__ import annotations

from io import StringIO
from pathlib import Path
import tempfile
from unittest.mock import patch

from aether.cli import main as cli_main
from aether.ir.verifier import IRVerificationError


def _run(arguments: list[str]) -> tuple[int, str, str]:
    stdout = StringIO()
    stderr = StringIO()
    code = cli_main(arguments, stdin=StringIO(), stdout=stdout, stderr=stderr)
    return code, stdout.getvalue(), stderr.getvalue()


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="aether-diagnostics-") as directory:
        root = Path(directory)
        syntax = root / "syntax.ae"
        syntax.write_text("int main( {\n", encoding="utf-8")
        code, _out, error = _run([str(syntax)])
        _require(
            code == 1 and "Aether syntax error [AE-SYNTAX-001]" in error,
            "syntax contract",
        )
        _require("Traceback" not in error, "syntax leaked traceback")

        capability = root / "capability.ae"
        capability.write_text("interface Counter { int get(); }\n", encoding="utf-8")
        code, _out, error = _run(["--check", str(capability)])
        _require(
            code == 1 and "Aether capability error" in error,
            "capability contract",
        )

        valid = root / "valid.ae"
        valid.write_text("int main() { return 0; }\n", encoding="utf-8")
        with patch(
            "aether.cli.IRBackend.lower_verified",
            side_effect=IRVerificationError("internal verifier detail"),
        ):
            code, _out, error = _run(["--emit-ir", str(valid)])
            _require(code == 70 and "ICE-IR-VERIFY-001" in error, "IR ICE contract")
            _require(
                "Traceback" not in error and "internal verifier detail" not in error,
                "ICE leaked detail",
            )
            code, _out, debug_error = _run(["--debug", "--emit-ir", str(valid)])
            _require(code == 70 and "Traceback" in debug_error, "debug traceback contract")
            _require("IRVerificationError" in debug_error, "debug cause contract")

        with patch("aether.backend.llvm.build.shutil.which", return_value=None):
            code, _out, error = _run([str(valid)])
            _require(
                code == 3 and "TOOLCHAIN-CLANG-001" in error,
                "toolchain contract",
            )
            _require(
                "internal compiler error" not in error.lower(),
                "toolchain mislabeled as ICE",
            )

    docs = (
        Path(__file__).resolve().parents[1]
        / "docs"
        / "aether"
        / "AETHER_DIAGNOSTICS.md"
    )
    _require(docs.is_file(), "diagnostics documentation is missing")
    print("PASS: public diagnostics and ICE boundary contract.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
