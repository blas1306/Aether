from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import sys
from zipfile import ZIP_DEFLATED, ZipFile

from packaging.tags import sys_tags
import pytest


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/core-in-process.yml"
CHECKER = ROOT / "scripts/check_core_1_0a_in_process.py"
PACKAGING_QUALIFIER = ROOT / "scripts/qualify_core_1_0a_packaging.py"


def _checker():
    spec = importlib.util.spec_from_file_location("core_1_0a_checker", CHECKER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _packaging_qualifier():
    spec = importlib.util.spec_from_file_location(
        "core_1_0a_packaging", PACKAGING_QUALIFIER
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_wheel(
    directory: Path,
    distribution: str,
    version: str,
    tag: str,
    *,
    metadata_name: str | None = None,
    module: str | None = None,
) -> Path:
    filename_distribution = distribution.replace("-", "_")
    wheel = directory / f"{filename_distribution}-{version}-{tag}.whl"
    dist_info = f"{filename_distribution}-{version}.dist-info"
    records = [
        f"{dist_info}/METADATA,,",
        f"{dist_info}/WHEEL,,",
        f"{dist_info}/RECORD,,",
    ]
    with ZipFile(wheel, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr(
            f"{dist_info}/METADATA",
            "Metadata-Version: 2.1\n"
            f"Name: {metadata_name or distribution}\n"
            f"Version: {version}\n",
        )
        archive.writestr(
            f"{dist_info}/WHEEL",
            "Wheel-Version: 1.0\n"
            "Generator: CORE-1.0A regression test\n"
            "Root-Is-Purelib: true\n"
            f"Tag: {tag}\n",
        )
        if module is not None:
            archive.writestr("_aether_core.py", module)
            records.insert(0, "_aether_core.py,,")
        archive.writestr(f"{dist_info}/RECORD", "\n".join(records) + "\n")
    return wheel


def test_workflow_keeps_qualification_lanes_separate_and_fail_closed() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    for job in (
        "semantic-parity:",
        "production-companion-regression:",
        "session-concurrency-soak:",
        "clean-install-platform:",
        "python-compatibility:",
        "aggregate-qualification:",
    ):
        assert job in text
    for platform_id in (
        "linux-x86_64",
        "windows-x86_64",
        "macos-x86_64",
        "macos-arm64",
    ):
        assert platform_id in text
    assert 'python: ["3.11", "3.12", "3.13", "3.14"]' in text
    assert "--require-qualified" in text
    assert "rust-ssa-shadow.yml" not in text
    assert "maturin develop" not in text
    assert text.count("--out native-dist") == 3
    assert text.count(
        "pip install --no-index --no-deps --find-links native-dist "
        "aether-core-qualification"
    ) == 3
    assert text.count("--companion") == 5


def test_wheel_selection_ignores_unrelated_project_wheel(tmp_path: Path) -> None:
    qualifier = _packaging_qualifier()
    compatible_tag = str(next(sys_tags()))
    unrelated = _write_wheel(
        tmp_path, "aether-language", "1.0.0rc4", "py3-none-any"
    )
    binding = _write_wheel(
        tmp_path, "aether-core-qualification", "0.1.0", compatible_tag
    )

    selected, reason, candidates = qualifier._select_wheel(
        sorted((unrelated, binding), key=lambda path: path.name)
    )

    assert selected == binding.resolve()
    assert reason["metadata_distribution"] == "aether-core-qualification"
    assert reason["matching_interpreter_tags"] == [compatible_tag]
    assert [item["filename"] for item in candidates] == sorted(
        (unrelated.name, binding.name)
    )


def test_wheel_selection_fails_closed_without_candidates() -> None:
    qualifier = _packaging_qualifier()
    with pytest.raises(qualifier.WheelSelectionError, match="no compatible"):
        qualifier._select_wheel([])


def test_wheel_selection_fails_closed_on_ambiguous_binding_wheels(
    tmp_path: Path,
) -> None:
    qualifier = _packaging_qualifier()
    compatible_tag = str(next(sys_tags()))
    candidates = [
        _write_wheel(
            tmp_path, "aether-core-qualification", version, compatible_tag
        )
        for version in ("0.1.0", "0.2.0")
    ]
    with pytest.raises(qualifier.WheelSelectionError, match="ambiguous compatible"):
        qualifier._select_wheel(candidates)


def test_wheel_selection_fails_closed_on_incompatible_cpython_wheel(
    tmp_path: Path,
) -> None:
    qualifier = _packaging_qualifier()
    incompatible = _write_wheel(
        tmp_path, "aether-core-qualification", "0.1.0", "cp38-cp38-any"
    )
    with pytest.raises(
        qualifier.WheelSelectionError, match="incompatible with the current interpreter"
    ):
        qualifier._select_wheel([incompatible])


def test_wheel_installs_with_rust_blocked_and_system_path_preserved(
    tmp_path: Path,
) -> None:
    qualifier = _packaging_qualifier()
    wheel = _write_wheel(
        tmp_path,
        "aether-core-qualification",
        "0.1.0",
        "py3-none-any",
        module="QUALIFICATION_ONLY = True\n",
    )
    venv = tmp_path / "venv"
    subprocess.run([sys.executable, "-m", "venv", str(venv)], check=True)
    scripts = venv / ("Scripts" if os.name == "nt" else "bin")
    python = scripts / ("python.exe" if os.name == "nt" else "python")
    base = dict(os.environ)
    base.pop("PYTHONPATH", None)
    environment, blockers = qualifier._install_environment(base, scripts)

    assert base.get("PATH", os.defpath) in environment["PATH"]
    assert qualifier._resolves_to(
        shutil.which("cargo", path=environment["PATH"]), blockers["cargo"]
    )
    subprocess.run(
        [
            str(python),
            "-m",
            "pip",
            "install",
            "--no-index",
            "--no-deps",
            "--only-binary=:all:",
            str(wheel),
        ],
        check=True,
        env=environment,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        [
            str(python),
            "-c",
            "import _aether_core; assert _aether_core.QUALIFICATION_ONLY is True",
        ],
        check=True,
        env=environment,
    )
    cargo = subprocess.run(
        [str(blockers["cargo"]), "--version"], check=False, env=environment
    )
    assert cargo.returncode != 0


def test_checker_blocks_missing_evidence(tmp_path: Path) -> None:
    aggregate, errors = _checker().check(tmp_path)
    assert aggregate["decision"] == "CORE_IN_PROCESS_BOUNDARY_QUALIFICATION_BLOCKED"
    assert errors
    assert aggregate["production_default_changed"] is False
    assert aggregate["in_process_is_production_default"] is False
    assert aggregate["companion_remains_production_and_rollback"] is True


def test_adapters_share_core_without_making_binding_the_default() -> None:
    companion = (
        ROOT / "compiler-rs/crates/aether-verifier/src/bin/aether-ssa-shadow.rs"
    ).read_text(encoding="utf-8")
    binding = (ROOT / "compiler-rs/crates/aether-python/src/lib.rs").read_text(
        encoding="utf-8"
    )
    core = (
        ROOT / "compiler-rs/crates/aether-verifier/src/compiler_core.rs"
    ).read_text(encoding="utf-8")
    selector = (ROOT / "src/aether/ssa/shadow.py").read_text(encoding="utf-8")
    assert "lower_verified_ssa(initial)" in companion
    assert "CompilerCore.accept_initial_ir(initial_ir)" in binding
    assert "pyo3" not in core
    assert "InProcessRustSSALoweringClient" not in selector
    assert "qualification_structured_errors: bool = False" in selector
    assert '#[serde(skip_serializing_if = "Option::is_none")]' in companion
