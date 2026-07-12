#!/usr/bin/env python3
"""Run Aether's local continuous-integration checks."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Sequence
from typing import TextIO


ROOT = Path(__file__).resolve().parents[1]
BENCHMARKS = (
    Path("benchmarks/arithmetic.ae"),
    Path("benchmarks/sum_to.ae"),
    Path("benchmarks/vector_dot.ae"),
)
LLVM_EXAMPLES = (
    Path("examples/llvm/arithmetic.ae"),
    Path("examples/llvm/countdown.ae"),
    Path("examples/llvm/list_clear.ae"),
    Path("examples/llvm/list_insert.ae"),
    Path("examples/llvm/list_push.ae"),
    Path("examples/llvm/vector_dot.ae"),
)


@dataclass(frozen=True)
class Stage:
    name: str
    commands: tuple[tuple[str, ...], ...]
    env: dict[str, str] | None = None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the complete local CI pipeline for Aether.",
    )
    parser.add_argument("--skip-tests", action="store_true", help="Skip pytest.")
    parser.add_argument(
        "--skip-bench", action="store_true", help="Skip quick benchmarks."
    )
    parser.add_argument(
        "--skip-llvm", action="store_true", help="Skip LLVM emission smoke tests."
    )
    parser.add_argument(
        "--skip-native", action="store_true", help="Skip native clang builds."
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show commands and their output while they run.",
    )
    return parser


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    return build_parser().parse_args(argv)


def _python_env() -> dict[str, str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "src")
    return env


def _pytest_command() -> tuple[str, ...]:
    if os.name == "nt":
        executable = ROOT / ".venv" / "Scripts" / "pytest.exe"
    else:
        executable = ROOT / ".venv" / "bin" / "pytest"
    return (str(executable),)


def build_stages(
    args: argparse.Namespace,
    *,
    native_output_dir: Path,
) -> tuple[Stage, ...]:
    python = sys.executable
    env = _python_env()
    stages = [Stage("whitespace", (("git", "diff", "--check"),))]

    if not args.skip_tests:
        stages.append(Stage("tests", (_pytest_command(),), env))

    if not args.skip_bench:
        commands = tuple(
            (
                python,
                "-m",
                "aether",
                "bench",
                str(path),
                "--iterations",
                "1",
                "--backend",
                "both",
            )
            for path in BENCHMARKS
        )
        stages.append(Stage("benchmarks", commands, env))

    if not args.skip_llvm:
        commands = tuple(
            (python, "-m", "aether", "--emit-llvm", str(path))
            for path in LLVM_EXAMPLES
        )
        stages.append(Stage("llvm", commands, env))

    if not args.skip_native:
        commands = tuple(
            (
                python,
                "-m",
                "aether",
                "build",
                str(path),
                "-o",
                str(native_output_dir / path.stem),
            )
            for path in LLVM_EXAMPLES
        )
        stages.append(Stage("native", commands, env))

    return tuple(stages)


def _format_command(command: Sequence[str]) -> str:
    return " ".join(command)


def _print_failure_output(completed: subprocess.CompletedProcess[str], stream: TextIO) -> None:
    if completed.stdout:
        print(completed.stdout.rstrip(), file=stream)
    if completed.stderr:
        print(completed.stderr.rstrip(), file=stream)


def run_pipeline(
    args: argparse.Namespace,
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]] | None = None,
    which: Callable[[str], str | None] = shutil.which,
    stdout: TextIO = sys.stdout,
) -> int:
    if runner is None:
        runner = subprocess.run
    started = time.perf_counter()
    clang_available = which("clang") is not None

    if not clang_available and not args.skip_native:
        print("WARNING: clang was not found; native checks will be skipped.", file=stdout)

    with tempfile.TemporaryDirectory(prefix="aether-ci-") as temporary_dir:
        stages = build_stages(args, native_output_dir=Path(temporary_dir))
        for stage in stages:
            if stage.name == "native" and not clang_available:
                print("- native (skipped: clang not found)", file=stdout)
                continue

            for command in stage.commands:
                if args.verbose:
                    print(f"$ {_format_command(command)}", file=stdout)
                try:
                    completed = runner(
                        list(command),
                        cwd=ROOT,
                        env=stage.env,
                        check=False,
                        capture_output=not args.verbose,
                        text=True,
                    )
                except OSError as exc:
                    print(f"FAIL {stage.name}: could not run command: {exc}", file=stdout)
                    print(f"CI failed at stage: {stage.name}", file=stdout)
                    print(f"Total time: {time.perf_counter() - started:.2f}s", file=stdout)
                    return 1

                if completed.returncode != 0:
                    print(
                        f"FAIL {stage.name}: command exited with "
                        f"code {completed.returncode}",
                        file=stdout,
                    )
                    if not args.verbose:
                        _print_failure_output(completed, stdout)
                    print(f"CI failed at stage: {stage.name}", file=stdout)
                    print(f"Total time: {time.perf_counter() - started:.2f}s", file=stdout)
                    return completed.returncode

            print(f"OK {stage.name}", file=stdout)

    print(f"Total time: {time.perf_counter() - started:.2f}s", file=stdout)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    return run_pipeline(parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
