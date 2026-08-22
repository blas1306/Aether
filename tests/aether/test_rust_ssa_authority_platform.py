from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess
import sys


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
