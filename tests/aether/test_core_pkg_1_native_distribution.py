from __future__ import annotations

import importlib.util
import builtins
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

from aether.ssa.shadow import (
    ProductionRustSSALoweringClient,
    default_rust_ssa_lowering_client,
)


ROOT = Path(__file__).resolve().parents[2]
NATIVE = ROOT / "compiler-rs/distributions/aether-compiler-core"
RUST_ADAPTER = ROOT / "compiler-rs/crates/aether-python"
WRAPPER = NATIVE / "python/aether_compiler_core/__init__.py"


def load_wrapper():
    spec = importlib.util.spec_from_file_location(
        "aether_compiler_core", WRAPPER, submodule_search_locations=[str(WRAPPER.parent)]
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_productive_distribution_name_and_exact_language_dependency() -> None:
    native = (NATIVE / "pyproject.toml").read_text(encoding="utf-8")
    language = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert 'name = "aether-compiler-core"' in native
    assert 'version = "1.0.0rc4"' in native
    assert '"aether-compiler-core==1.0.0rc4"' in language
    assert "aether-core-qualification" not in native


def test_native_wheel_declares_binding_wrapper_and_companion_outputs() -> None:
    metadata = (NATIVE / "pyproject.toml").read_text(encoding="utf-8")
    assert 'module-name = "aether_compiler_core._aether_core"' in metadata
    assert 'python-packages = ["aether_compiler_core", "_aether_core"]' in metadata
    assert 'from = "out-dir"' in metadata
    assert "aether-ssa-shadow*" in metadata
    assert "native-core-manifest.json" in metadata


def test_both_native_adapters_use_the_same_compiler_core_crate() -> None:
    binding = (RUST_ADAPTER / "src/lib.rs").read_text(encoding="utf-8")
    companion = (
        ROOT / "compiler-rs/crates/aether-verifier/src/bin/aether-ssa-shadow.rs"
    ).read_text(encoding="utf-8")
    cargo = (RUST_ADAPTER / "Cargo.toml").read_text(encoding="utf-8")
    assert "aether-verifier = { path = \"../aether-verifier\" }" in cargo
    assert "CompilerCore" in binding
    assert "CompilerCore" in companion
    assert "lower_verified_ssa" in companion
    assert '"--distribution-metadata"' in companion
    assert "AETHER_COMPILER_CORE_BUILD_IDENTITY" in companion


def test_productive_binding_is_not_qualification_only() -> None:
    binding = (RUST_ADAPTER / "src/lib.rs").read_text(encoding="utf-8")
    assert 'module.add("QUALIFICATION_ONLY", false)' in binding
    assert 'features = ["productive-distribution"]' in (
        NATIVE / "pyproject.toml"
    ).read_text(encoding="utf-8")


def test_python_compatibility_keeps_interpreter_specific_wheels() -> None:
    cargo = (RUST_ADAPTER / "Cargo.toml").read_text(encoding="utf-8")
    assert "abi3" not in cargo
    assert 'requires-python = ">=3.11"' in (NATIVE / "pyproject.toml").read_text()


def test_production_default_remains_companion() -> None:
    assert isinstance(default_rust_ssa_lowering_client(), ProductionRustSSALoweringClient)


def test_production_discovery_uses_stable_native_package_helper() -> None:
    source = (ROOT / "src/aether/ssa/shadow.py").read_text(encoding="utf-8")
    production = source[source.index("class ProductionRustSSALoweringClient"):source.index("_PRODUCTION_RUST_SSA_CLIENT")]
    assert "from aether_compiler_core import companion_path" in production
    assert "executable = companion_path()" in production
    assert "_aether_core" not in production


def test_wrapper_fails_closed_on_missing_distribution(monkeypatch) -> None:
    wrapper = load_wrapper()

    def missing(_name: str):
        raise wrapper.importlib_metadata.PackageNotFoundError

    monkeypatch.setattr(wrapper.importlib_metadata, "distribution", missing)
    with pytest.raises(wrapper.NativeCoreDistributionError, match="metadata is missing"):
        wrapper._distribution()


def test_wrapper_fails_closed_on_wrong_distribution_version(monkeypatch) -> None:
    wrapper = load_wrapper()
    monkeypatch.setattr(
        wrapper.importlib_metadata,
        "distribution",
        lambda _name: SimpleNamespace(version="1.0.0rc3"),
    )
    with pytest.raises(wrapper.NativeCoreDistributionError, match="expected exactly"):
        wrapper._distribution()


def test_wrapper_fails_closed_on_wrong_language_version(monkeypatch) -> None:
    wrapper = load_wrapper()
    monkeypatch.setattr(wrapper.importlib_metadata, "version", lambda _name: "1.0.0rc3")
    with pytest.raises(wrapper.NativeCoreDistributionError, match="requires exactly"):
        wrapper._validate_language_version()


def test_wrapper_fails_closed_on_missing_or_corrupt_manifest(tmp_path: Path, monkeypatch) -> None:
    wrapper = load_wrapper()
    package = tmp_path / "aether_compiler_core"
    (package / "_native").mkdir(parents=True)
    monkeypatch.setattr(wrapper, "files", lambda _package: package)
    with pytest.raises(wrapper.NativeCoreDistributionError, match="metadata is missing"):
        wrapper._manifest()
    (package / "_native/native-core-manifest.json").write_text("not-json", encoding="utf-8")
    with pytest.raises(wrapper.NativeCoreDistributionError, match="corrupted"):
        wrapper._manifest()
    (package / "_native/native-core-manifest.json").write_text(
        json.dumps({"manifest_schema_version": 999}), encoding="utf-8"
    )
    with pytest.raises(wrapper.NativeCoreDistributionError, match="incompatible"):
        wrapper._manifest()


def test_source_checkout_shadow_fails_closed_instead_of_finding_another_companion(
    tmp_path: Path, monkeypatch
) -> None:
    wrapper = load_wrapper()
    shadow_package = tmp_path / "aether_compiler_core"
    shadow_package.mkdir()
    monkeypatch.setattr(wrapper, "files", lambda _package: shadow_package)
    with pytest.raises(wrapper.NativeCoreDistributionError, match="metadata is missing"):
        wrapper._manifest()


def test_wrapper_fails_closed_on_missing_binding(monkeypatch) -> None:
    wrapper = load_wrapper()
    original_import = builtins.__import__

    def blocked(name, *args, **kwargs):
        if name == "_aether_core":
            raise ImportError("missing extension")
        return original_import(name, *args, **kwargs)

    monkeypatch.delitem(sys.modules, "_aether_core", raising=False)
    monkeypatch.setattr(builtins, "__import__", blocked)
    with pytest.raises(wrapper.NativeCoreDistributionError, match="without its _aether_core"):
        wrapper._native_module()


def test_wrapper_fails_closed_on_shadow_binding(monkeypatch) -> None:
    wrapper = load_wrapper()
    monkeypatch.setitem(sys.modules, "_aether_core", SimpleNamespace(__version__="shadow"))
    with pytest.raises(wrapper.NativeCoreDistributionError, match="version contract mismatch"):
        wrapper._native_module()


def test_wrapper_fails_closed_on_record_checksum_mismatch(tmp_path: Path) -> None:
    wrapper = load_wrapper()
    path = tmp_path / "aether-ssa-shadow"
    path.write_bytes(b"corrupted")

    class Entry:
        hash = SimpleNamespace(mode="sha256", value="wrong")

        @staticmethod
        def as_posix() -> str:
            return "aether_compiler_core/_native/aether-ssa-shadow"

    distribution = SimpleNamespace(files=[Entry()])
    with pytest.raises(wrapper.NativeCoreDistributionError, match="checksum mismatch"):
        wrapper._verify_record(
            distribution,
            path,
            "aether_compiler_core/_native/aether-ssa-shadow",
        )


def test_wrapper_fails_closed_on_missing_companion(tmp_path: Path, monkeypatch) -> None:
    wrapper = load_wrapper()
    manifest_path = tmp_path / "native-core-manifest.json"
    manifest_path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(wrapper, "_distribution", lambda: object())
    monkeypatch.setattr(
        wrapper,
        "_manifest",
        lambda: ({"binary": "aether-ssa-shadow"}, manifest_path),
    )
    monkeypatch.setattr(wrapper, "_verify_record", lambda *_args: None)
    with pytest.raises(wrapper.NativeCoreDistributionError, match="companion is missing"):
        wrapper.companion_path()


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX executable bit contract")
def test_wrapper_fails_closed_on_non_executable_companion(tmp_path: Path, monkeypatch) -> None:
    wrapper = load_wrapper()
    manifest_path = tmp_path / "native-core-manifest.json"
    binary = tmp_path / "aether-ssa-shadow"
    binary.write_bytes(b"binary")
    binary.chmod(0o644)
    monkeypatch.setattr(wrapper, "_distribution", lambda: object())
    monkeypatch.setattr(
        wrapper,
        "_manifest",
        lambda: ({"binary": binary.name}, manifest_path),
    )
    monkeypatch.setattr(wrapper, "_verify_record", lambda *_args: None)
    with pytest.raises(wrapper.NativeCoreDistributionError, match="not executable"):
        wrapper.companion_path()


def test_core_pkg_checker_requires_all_machine_readable_evidence(tmp_path: Path) -> None:
    path = ROOT / "scripts/check_core_pkg_1_native_distribution.py"
    spec = importlib.util.spec_from_file_location("core_pkg_1_checker", path)
    assert spec is not None and spec.loader is not None
    checker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(checker)
    aggregate, errors = checker.check(tmp_path)
    assert aggregate["decision"] == checker.BLOCKED
    assert errors
    assert aggregate["production_transport"] == "companion"
    assert aggregate["in_process_promoted"] is False


def test_required_artifacts_and_dedicated_workflow_exist() -> None:
    for relative in (
        "docs/compiler/CORE_PKG_1_NATIVE_COMPILER_CORE_DISTRIBUTION.md",
        "docs/compiler/core_pkg_1_native_compiler_core_distribution.json",
        "scripts/qualify_core_pkg_1_native_distribution.py",
        "scripts/project_core_pkg_1_binding_guard.py",
        "scripts/check_core_pkg_1_native_distribution.py",
        ".github/workflows/core-native-packaging.yml",
    ):
        assert (ROOT / relative).is_file()
