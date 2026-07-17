from __future__ import annotations

import importlib.util
from io import StringIO
from pathlib import Path
import sys

from aether.capabilities import CAPABILITY_PROFILE_VERSION
from aether.cli import main as cli_main
from aether.version import LANGUAGE_VERSION, PACKAGE_VERSION, __version__


ROOT = Path(__file__).resolve().parents[1]


def _load_script(name: str):
    path = ROOT / "scripts" / name
    spec = importlib.util.spec_from_file_location(f"aether_test_{path.stem}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_canonical_version_maps_public_and_python_metadata() -> None:
    assert PACKAGE_VERSION == "1.0.0rc1"
    assert LANGUAGE_VERSION == "1.0.0-rc.1"
    assert __version__ == PACKAGE_VERSION


def test_cli_version_uses_language_and_capability_identities() -> None:
    stdout = StringIO()
    stderr = StringIO()

    assert cli_main(["--version"], stdout=stdout, stderr=stderr) == 0
    assert stdout.getvalue() == (
        f"Aether {LANGUAGE_VERSION}\n"
        f"Native capability profile {CAPABILITY_PROFILE_VERSION}\n"
    )
    assert stderr.getvalue() == ""


def test_native_profile_document_is_generated_from_profile_22() -> None:
    renderer = _load_script("render_native_profile.py")

    assert renderer.check_document()
    rendered = renderer.render_capability_table()
    assert f"Profile schema/version: `{CAPABILITY_PROFILE_VERSION}`" in rendered


def test_normative_documents_and_historical_classification_are_integral() -> None:
    checker = _load_script("check_release_docs.py")
    assert checker.check() == []


def test_release_manifest_uses_canonical_versions_and_platform(tmp_path: Path) -> None:
    release = _load_script("release.py")
    assert release.LANGUAGE_VERSION == LANGUAGE_VERSION
    assert release.PACKAGE_VERSION == PACKAGE_VERSION
    assert release.CAPABILITY_PROFILE_VERSION == CAPABILITY_PROFILE_VERSION
    assert release.SUPPORTED_NATIVE_PLATFORMS == ("Linux x86_64",)
    wheel = tmp_path / "candidate.whl"
    sdist = tmp_path / "candidate.tar.gz"
    wheel.write_bytes(b"wheel")
    sdist.write_bytes(b"sdist")

    manifest = release.manifest_payload(
        commit="0" * 40,
        dirty=True,
        timestamp="2026-07-16T00:00:00Z",
        timestamp_policy="test",
        source_epoch="0",
        artifacts=(wheel, sdist),
        gates_skipped=False,
    )

    assert manifest["language_version"] == LANGUAGE_VERSION
    assert manifest["package_version"] == PACKAGE_VERSION
    assert manifest["capability_profile_version"] == CAPABILITY_PROFILE_VERSION
    assert manifest["dirty_worktree"] is True
    assert manifest["reproducibility"]["bit_for_bit_claimed"] is False


def test_packaging_declares_dynamic_canonical_version_and_essential_docs() -> None:
    metadata = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert 'dynamic = ["version"]' in metadata
    assert 'version = { attr = "aether.version.PACKAGE_VERSION" }' in metadata
    assert '"docs/aether/AETHER_LANGUAGE_SPEC_V1.md"' in metadata
    assert '"docs/aether/AETHER_NATIVE_PROFILE_V1.md"' in metadata
    assert str(ROOT) not in metadata
