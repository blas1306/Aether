from __future__ import annotations

from pathlib import Path
import shutil
import subprocess

import pytest

from aether.backend.llvm import LLVMBuildError
from aether.benchmark import run_benchmark


SOURCE = """
int main() {
    int total = 0;
    int i = 0;
    while i < 10 {
        total = total + i;
        i = i + 1;
    }
    if total == 45 {
        return 0;
    } else {
        return 1;
    }
}
"""

BENCHMARK_PATHS = sorted(Path("benchmarks").glob("*.ae"))


@pytest.mark.parametrize(
    ("backend", "expected_names"),
    [
        ("ast", {"AST parse/typecheck", "AST execute"}),
        ("ir", {"IR lower/verify", "IR execute", "IR O1 optimize"}),
        ("both", {"AST parse/typecheck", "AST execute", "IR lower/verify", "IR execute", "IR O1 optimize"}),
        ("ssa", {"SSA build", "SSA optimize"}),
        ("llvm", {"LLVM emit"}),
    ],
)
def test_benchmark_profiles_keep_legacy_modes_and_add_compiler_layers(
    backend: str,
    expected_names: set[str],
) -> None:
    report = run_benchmark(
        SOURCE,
        path=Path("profile.ae"),
        iterations=1,
        backend=backend,
    )

    assert {timing.name for timing in report.timings} == expected_names
    assert report.failures == ()
    assert all(timing.total_seconds >= 0 for timing in report.timings)
    assert all(timing.average_seconds == timing.total_seconds for timing in report.timings)


def test_native_build_iterations_and_runtime_setup_are_separate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    build_paths: list[Path] = []
    run_commands: list[list[str]] = []

    def fake_build(_source: str, _path: Path, output_path: Path) -> None:
        build_paths.append(output_path)
        output_path.touch()

    def fake_run(command: list[str], **_kwargs) -> subprocess.CompletedProcess[bytes]:
        run_commands.append(command)
        return subprocess.CompletedProcess(command, 0, b"", b"")

    monkeypatch.setattr("aether.benchmark._build_native", fake_build)
    monkeypatch.setattr("aether.benchmark.subprocess.run", fake_run)

    report = run_benchmark(
        SOURCE,
        path=Path("native.ae"),
        iterations=3,
        backend="native",
    )

    assert [timing.name for timing in report.timings] == ["Native build", "Native run"]
    assert report.failures == ()
    assert len(build_paths) == 4  # 3 measured builds + 1 untimed runtime setup build
    assert len(run_commands) == 3
    assert len(set(build_paths)) == 1
    assert not build_paths[0].parent.exists()


def test_missing_clang_marks_native_profiles_unsupported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def missing_clang(_source: str, _path: Path, _output_path: Path) -> None:
        raise LLVMBuildError("clang is required to build native executables.")

    monkeypatch.setattr("aether.benchmark._build_native", missing_clang)

    report = run_benchmark(
        SOURCE,
        path=Path("native.ae"),
        iterations=2,
        backend="native",
    )

    assert report.timings == ()
    assert [failure.name for failure in report.failures] == ["Native build", "Native run"]
    assert all(failure.unsupported for failure in report.failures)


@pytest.mark.parametrize(("expected_exit_code", "has_failure"), [(0, True), (None, False)])
def test_native_executable_exit_code_can_be_validated_or_explicitly_ignored(
    monkeypatch: pytest.MonkeyPatch,
    expected_exit_code: int | None,
    has_failure: bool,
) -> None:
    def fake_build(_source: str, _path: Path, output_path: Path) -> None:
        output_path.touch()

    def failed_run(command: list[str], **_kwargs) -> subprocess.CompletedProcess[bytes]:
        return subprocess.CompletedProcess(command, 7, b"", b"program failed")

    monkeypatch.setattr("aether.benchmark._build_native", fake_build)
    monkeypatch.setattr("aether.benchmark.subprocess.run", failed_run)

    report = run_benchmark(
        SOURCE,
        path=Path("native.ae"),
        iterations=2,
        backend="native",
        expected_exit_code=expected_exit_code,
    )

    assert (any(failure.name == "Native run" for failure in report.failures)) is has_failure
    if has_failure:
        assert "returned exit code 7; expected 0" in str(report.failures[-1].error)
    else:
        assert [timing.name for timing in report.timings] == ["Native build", "Native run"]


def test_all_non_native_profiles_continue_when_native_is_unsupported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def missing_clang(_source: str, _path: Path, _output_path: Path) -> None:
        raise LLVMBuildError("clang is required to build native executables.")

    monkeypatch.setattr("aether.benchmark._build_native", missing_clang)
    report = run_benchmark(
        SOURCE,
        path=Path("all.ae"),
        iterations=1,
        backend="all",
    )

    assert {timing.name for timing in report.timings} >= {
        "AST execute",
        "IR execute",
        "SSA build",
        "SSA optimize",
        "LLVM emit",
    }
    assert [failure.name for failure in report.failures] == ["Native build", "Native run"]


@pytest.mark.parametrize("backend", ["both", "ssa", "llvm"])
@pytest.mark.parametrize(
    "path",
    BENCHMARK_PATHS,
    ids=lambda path: path.stem,
)
def test_repository_benchmarks_process_through_declared_non_native_layers(
    path: Path,
    backend: str,
) -> None:
    report = run_benchmark(
        path.read_text(encoding="utf-8"),
        path=path,
        iterations=1,
        backend=backend,
    )

    assert report.timings
    assert report.failures == ()


@pytest.mark.skipif(shutil.which("clang") is None, reason="clang is not available")
@pytest.mark.parametrize("path", BENCHMARK_PATHS, ids=lambda path: path.stem)
def test_repository_benchmarks_process_through_native_layer(path: Path) -> None:
    report = run_benchmark(
        path.read_text(encoding="utf-8"),
        path=path,
        iterations=1,
        backend="native",
    )

    assert [timing.name for timing in report.timings] == ["Native build", "Native run"]
    assert report.failures == ()
