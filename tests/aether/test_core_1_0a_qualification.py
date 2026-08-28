from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/core-in-process.yml"
CHECKER = ROOT / "scripts/check_core_1_0a_in_process.py"


def _checker():
    spec = importlib.util.spec_from_file_location("core_1_0a_checker", CHECKER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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
