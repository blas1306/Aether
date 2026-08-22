from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from aether.ssa import authority_probe


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/qualify_rust_ssa_authority_platform.py"


def _platform_module():
    spec = importlib.util.spec_from_file_location(
        "rust_ssa_authority_platform", SCRIPT
    )
    assert spec is not None and spec.loader is not None
    scripts = str(ROOT / "scripts")
    sys.path.insert(0, scripts)
    try:
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    finally:
        sys.path.remove(scripts)
    return module


def test_probe_failure_exposes_bounded_stdout_and_stderr(
    monkeypatch, capsys, tmp_path: Path
) -> None:
    platform = _platform_module()
    limit = platform.MAX_PROBE_DIAGNOSTIC_CHARACTERS
    stdout = "stdout-start\n" + "o" * (limit * 2) + "\nstdout-end"
    stderr = "stderr-start\n" + "e" * (limit * 2) + "\nstderr-end"

    def fail(*_args, **_kwargs):
        return subprocess.CompletedProcess(
            ["probe"], 23, stdout=stdout, stderr=stderr
        )

    monkeypatch.setattr(platform.subprocess, "run", fail)
    returncode, observation = platform._run_probe(
        ["probe"], cwd=tmp_path, env={}
    )

    diagnostics = capsys.readouterr().err
    assert returncode == 23
    assert observation is None
    assert "aether-ssa-authority-probe exited with status 23" in diagnostics
    assert "stdout-start" in diagnostics and "stdout-end" in diagnostics
    assert "stderr-start" in diagnostics and "stderr-end" in diagnostics
    assert diagnostics.count("...[truncated; original_chars=") == 2
    assert len(diagnostics) < 2 * limit + 300


def test_successful_probe_parses_final_json_observation(
    monkeypatch, tmp_path: Path
) -> None:
    platform = _platform_module()
    expected = {"comparisons": 16, "mode": "RUST_SSA_AUTHORITY_PYTHON_SHADOW"}

    def succeed(*_args, **_kwargs):
        return subprocess.CompletedProcess(
            ["probe"],
            0,
            stdout="earlier informational output\n" + json.dumps(expected) + "\n",
            stderr="",
        )

    monkeypatch.setattr(platform.subprocess, "run", succeed)
    returncode, observation = platform._run_probe(
        ["probe"], cwd=tmp_path, env={}
    )

    assert returncode == 0
    assert observation == expected


def test_probe_failure_remains_a_qualification_failure(
    monkeypatch, tmp_path: Path
) -> None:
    platform = _platform_module()

    def fail(*_args, **_kwargs):
        return subprocess.CompletedProcess(
            ["probe"], 7, stdout="context", stderr="failure"
        )

    monkeypatch.setattr(platform.subprocess, "run", fail)
    qualification_returncode, observation = platform._run_probe(
        ["probe"], cwd=tmp_path, env={}
    )

    assert qualification_returncode == 7
    assert qualification_returncode != 0
    assert observation is None


def test_clean_probe_environment_keeps_host_toolchain_path_but_not_python_paths(
    tmp_path: Path,
) -> None:
    platform = _platform_module()
    environment = tmp_path / "clean-venv"
    checkout = tmp_path / "checkout"
    toolchain = tmp_path / "toolchain-bin"
    host_path = os.pathsep.join(
        (str(checkout / "bin"), str(toolchain))
    )
    platform.ROOT = checkout

    isolated = platform._clean_probe_environment(
        environment,
        host_environment={
            "PATH": host_path,
            "PYTHONPATH": str(tmp_path / "checkout" / "src"),
            "PYTHONHOME": str(tmp_path / "checkout-python"),
            "LIB": "host-sdk-libraries",
        },
    )

    path_entries = isolated["PATH"].split(os.pathsep)
    expected_scripts = environment / ("Scripts" if sys.platform == "win32" else "bin")
    assert path_entries == [str(expected_scripts), str(toolchain)]
    assert "PYTHONPATH" not in isolated
    assert "PYTHONHOME" not in isolated
    assert isolated["LIB"] == "host-sdk-libraries"


def test_native_compile_failure_keeps_both_ends_of_clang_diagnostics(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    limit = authority_probe.MAX_CLANG_DIAGNOSTIC_CHARACTERS
    stderr = "linker-start\n" + "e" * (limit * 2) + "\nlinker-end"
    stdout = "driver-start\n" + "o" * (limit * 2) + "\ndriver-end"

    def fail(*_args, **_kwargs):
        return subprocess.CompletedProcess(
            ["clang"], 1120, stdout=stdout, stderr=stderr
        )

    monkeypatch.setattr(authority_probe.subprocess, "run", fail)
    with pytest.raises(RuntimeError) as raised:
        authority_probe._compile_and_run(
            tmp_path / "clang", "define i32 @main() { ret i32 0 }", tmp_path, "sample"
        )

    diagnostic = str(raised.value)
    assert "exit status 1120" in diagnostic
    assert "linker-start" in diagnostic and "linker-end" in diagnostic
    assert "driver-start" in diagnostic and "driver-end" in diagnostic
    assert diagnostic.count("...[truncated; original_chars=") == 2
    assert len(diagnostic) < 2 * limit + 300
