#!/usr/bin/env python3
"""Install exact product wheels outside the checkout and run RUST-IR-3 probes."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import tempfile
import venv


ROOT = Path(__file__).resolve().parents[1]
PROBE = ROOT / "scripts/rust_ir_3_product_probe.py"


def _commands(environment: Path) -> tuple[Path, Path]:
    directory = environment / ("Scripts" if os.name == "nt" else "bin")
    return directory / ("python.exe" if os.name == "nt" else "python"), directory


def _run(arguments: list[str], cwd: Path, environment: dict[str, str]) -> None:
    completed = subprocess.run(
        arguments,
        cwd=cwd,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode:
        raise RuntimeError(
            f"command failed ({completed.returncode}): {' '.join(arguments)}\n"
            f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--native-wheel", type=Path, required=True)
    parser.add_argument("--language-wheel", type=Path, required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--kind", required=True)
    parser.add_argument("--role", required=True)
    parser.add_argument("--platform", required=True)
    parser.add_argument("--python-minor", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    native = args.native_wheel.resolve()
    language = args.language_wheel.resolve()
    with tempfile.TemporaryDirectory(prefix="rust-ir-3-consumer-") as raw:
        temporary = Path(raw)
        environment_path = temporary / "venv"
        work = temporary / "work"
        work.mkdir()
        venv.EnvBuilder(with_pip=True).create(environment_path)
        python, scripts = _commands(environment_path)
        environment = os.environ.copy()
        environment.pop("PYTHONPATH", None)
        environment.pop("AETHER_INTERNAL_RUST_INITIAL_IR_QUALIFICATION_EXECUTABLE", None)
        environment["PYTHONNOUSERSITE"] = "1"
        _run(
            [
                str(python), "-m", "pip", "install",
                "--disable-pip-version-check", "--force-reinstall",
                "--find-links", str(native.parent), str(language),
            ],
            work,
            environment,
        )
        environment["PATH"] = str(scripts)
        _run(
            [
                str(python), str(PROBE), "--mode", "environment",
                "--kind", args.kind, "--revision", args.revision,
                "--run-id", args.run_id, "--repository", str(ROOT),
                "--role", args.role, "--platform", args.platform,
                "--python-minor", args.python_minor,
                "--wheel", str(native), "--wheel", str(language),
                "--output", str(output),
            ],
            work,
            environment,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
