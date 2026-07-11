from __future__ import annotations

import importlib.util
from io import StringIO
from pathlib import Path
import subprocess
import sys

import pytest

CI_PATH = Path(__file__).resolve().parents[1] / "scripts" / "ci.py"
SPEC = importlib.util.spec_from_file_location("aether_local_ci", CI_PATH)
assert SPEC is not None and SPEC.loader is not None
ci = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = ci
SPEC.loader.exec_module(ci)


def completed(returncode: int = 0) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess([], returncode, stdout="", stderr="")


def test_parse_args_supports_all_pipeline_options() -> None:
    args = ci.parse_args(
        [
            "--skip-tests",
            "--skip-bench",
            "--skip-llvm",
            "--skip-native",
            "--verbose",
        ]
    )

    assert args.skip_tests
    assert args.skip_bench
    assert args.skip_llvm
    assert args.skip_native
    assert args.verbose


def test_pipeline_runs_stages_in_declared_order(monkeypatch: pytest.MonkeyPatch) -> None:
    commands: list[list[str]] = []

    def fake_run(command: list[str], **_kwargs) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        return completed()

    monkeypatch.setattr(ci.subprocess, "run", fake_run)
    output = StringIO()

    exit_code = ci.run_pipeline(ci.parse_args([]), which=lambda _name: "/usr/bin/clang", stdout=output)

    assert exit_code == 0
    assert commands[0] == ["git", "diff", "--check"]
    assert commands[1] == [str(ci.ROOT / ".venv" / "bin" / "pytest")]
    assert [command[3] for command in commands[2:5]] == ["bench"] * 3
    assert [command[3] for command in commands[5:8]] == ["--emit-llvm"] * 3
    assert [command[3] for command in commands[8:11]] == ["build"] * 3
    assert output.getvalue().index("OK tests") < output.getvalue().index("OK benchmarks")
    assert output.getvalue().index("OK benchmarks") < output.getvalue().index("OK llvm")
    assert output.getvalue().index("OK llvm") < output.getvalue().index("OK native")


def test_pipeline_stops_and_propagates_command_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    commands: list[list[str]] = []

    def fake_run(command: list[str], **_kwargs) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        if len(commands) == 2:
            return subprocess.CompletedProcess(command, 7, stdout="", stderr="pytest failed")
        return completed()

    monkeypatch.setattr(ci.subprocess, "run", fake_run)
    output = StringIO()

    exit_code = ci.run_pipeline(ci.parse_args([]), which=lambda _name: "/usr/bin/clang", stdout=output)

    assert exit_code == 7
    assert len(commands) == 2
    assert "pytest failed" in output.getvalue()
    assert "CI failed at stage: tests" in output.getvalue()


@pytest.mark.parametrize(
    ("runner", "expected"),
    [
        (lambda *_args, **_kwargs: completed(), 0),
        (lambda *_args, **_kwargs: completed(3), 3),
    ],
)
def test_pipeline_exit_codes(runner, expected: int) -> None:
    args = ci.parse_args(["--skip-tests", "--skip-bench", "--skip-llvm", "--skip-native"])

    assert ci.run_pipeline(args, runner=runner, which=lambda _name: None, stdout=StringIO()) == expected
