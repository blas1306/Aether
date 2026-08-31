#!/usr/bin/env python3
"""Run the RUST-REFINE-3 probe in a checkout-isolated wheel consumer."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import tempfile
import venv


ROOT = Path(__file__).resolve().parents[1]
PROBE = ROOT / "scripts/rust_refine_3_product_probe.py"


def _commands(environment: Path) -> tuple[Path, Path]:
    directory = environment / ("Scripts" if os.name == "nt" else "bin")
    executable = "python.exe" if os.name == "nt" else "python"
    return directory / executable, directory


def _run(arguments: list[str], cwd: Path, environment: dict[str, str]) -> None:
    completed = subprocess.run(
        arguments,
        cwd=cwd,
        env=environment,
        capture_output=True,
        text=True,
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
    parser.add_argument("--local-dependency-site-packages", type=Path)
    args = parser.parse_args()
    native = args.native_wheel.resolve()
    language = args.language_wheel.resolve()
    output = args.output.resolve()
    with tempfile.TemporaryDirectory(prefix="rust-refine-3-consumer-") as raw:
        temporary = Path(raw)
        environment = temporary / "venv"
        work = temporary / "work"
        work.mkdir()
        venv.EnvBuilder(with_pip=True).create(environment)
        python, scripts = _commands(environment)
        values = os.environ.copy()
        values.pop("PYTHONPATH", None)
        values["PYTHONNOUSERSITE"] = "1"
        if args.local_dependency_site_packages is None:
            install = ["--find-links", str(native.parent), str(language)]
        else:
            completed = subprocess.run(
                [
                    str(python),
                    "-c",
                    "import sysconfig;print(sysconfig.get_path('purelib'))",
                ],
                cwd=work,
                env=values,
                capture_output=True,
                text=True,
                check=True,
            )
            marker = Path(completed.stdout.strip()) / "qualification-dependencies.pth"
            marker.write_text(
                str(args.local_dependency_site_packages.resolve()) + "\n",
                encoding="utf-8",
            )
            install = ["--no-index", "--no-deps", str(native), str(language)]
        _run(
            [
                str(python),
                "-m",
                "pip",
                "install",
                "--disable-pip-version-check",
                "--force-reinstall",
                *install,
            ],
            work,
            values,
        )
        values["PATH"] = str(scripts)
        _run(
            [
                str(python),
                str(PROBE),
                "--mode",
                "environment",
                "--kind",
                args.kind,
                "--revision",
                args.revision,
                "--run-id",
                args.run_id,
                "--root",
                str(work),
                "--repository",
                str(ROOT),
                "--role",
                args.role,
                "--platform",
                args.platform,
                "--python-minor",
                args.python_minor,
                "--wheel",
                str(native),
                "--wheel",
                str(language),
                "--output",
                str(output),
            ],
            work,
            values,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
