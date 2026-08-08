from __future__ import annotations

import importlib.util
from io import StringIO
from pathlib import Path
import sys
import zipfile

import pytest

from aether.capabilities import CAPABILITY_PROFILE_VERSION
from aether.cli import main as cli_main
from aether.version import LANGUAGE_VERSION, PACKAGE_VERSION, RELEASE_TAG, __version__


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
    assert PACKAGE_VERSION == "1.0.0rc4"
    assert LANGUAGE_VERSION == "1.0.0-rc.4"
    assert RELEASE_TAG == "v1.0.0-rc.4"
    assert __version__ == PACKAGE_VERSION


def test_release_script_defaults_to_the_canonical_version() -> None:
    release = _load_script("release.py")

    assert release.build_parser().parse_args([]).version == LANGUAGE_VERSION


def test_cli_version_uses_language_and_capability_identities() -> None:
    stdout = StringIO()
    stderr = StringIO()

    assert cli_main(["--version"], stdout=stdout, stderr=stderr) == 0
    assert stdout.getvalue() == (
        f"Aether {LANGUAGE_VERSION}\n"
        f"Native capability profile {CAPABILITY_PROFILE_VERSION}\n"
    )
    assert stderr.getvalue() == ""


def test_native_profile_document_is_generated_from_current_profile() -> None:
    renderer = _load_script("render_native_profile.py")

    assert renderer.check_document()
    rendered = renderer.render_capability_table()
    assert f"Profile schema/version: `{CAPABILITY_PROFILE_VERSION}`" in rendered


def test_normative_documents_and_historical_classification_are_integral() -> None:
    checker = _load_script("check_release_docs.py")
    assert checker.check() == []


def test_documentation_checker_rejects_interface_status_contradiction(
    monkeypatch,
) -> None:
    checker = _load_script("check_release_docs.py")
    native_profile = ROOT / "docs" / "aether" / "AETHER_NATIVE_PROFILE_V1.md"
    original_read_text = Path.read_text

    def contradictory_read_text(path: Path, *args, **kwargs) -> str:
        text = original_read_text(path, *args, **kwargs)
        if path == native_profile:
            return text.replace(
                "| `interfaces` | **COMPLETE**",
                "| `interfaces` | **UNSUPPORTED**",
            )
        return text

    monkeypatch.setattr(Path, "read_text", contradictory_read_text)

    assert any(
        "known documentation contradiction" in error
        for error in checker.check()
    )


def test_release_manifest_uses_canonical_versions_and_platform(tmp_path: Path) -> None:
    release = _load_script("release.py")
    assert release.LANGUAGE_VERSION == LANGUAGE_VERSION
    assert release.PACKAGE_VERSION == PACKAGE_VERSION
    assert release.RELEASE_TAG == RELEASE_TAG
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
    assert manifest["release_tag"] == RELEASE_TAG
    assert manifest["capability_profile_version"] == CAPABILITY_PROFILE_VERSION
    assert manifest["dirty_worktree"] is True
    assert manifest["reproducibility"]["bit_for_bit_claimed"] is False


def test_packaging_declares_dynamic_canonical_version_and_essential_docs() -> None:
    metadata = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert 'dynamic = ["version"]' in metadata
    assert 'version = { attr = "aether.version.PACKAGE_VERSION" }' in metadata
    assert '"docs/aether/AETHER_LANGUAGE_SPEC_V1.md"' in metadata
    assert '"docs/aether/AETHER_NATIVE_PROFILE_V1.md"' in metadata
    assert '"docs/aether/AETHER_FRONTEND_EXPERIMENTS.md"' in metadata
    assert '"docs/aether/AETHER_DIAGNOSTICS.md"' in metadata
    assert '"docs/aether/AETHER_1_0_0_RC4_RELEASE_NOTES.md"' in metadata
    assert '"docs/compiler/exceptions/EXCEPTION_PROMOTION_EVIDENCE.md"' in metadata
    assert '"corpus/exceptions/catalog.json"' in metadata
    assert '"CHANGELOG.md"' in metadata
    assert '"LICENSE"' in metadata
    assert '"README.md"' in metadata
    assert '"examples/v1_examples_manifest.json"' in metadata
    assert '"examples/README.md"' in metadata
    assert '"share/aether/examples/LeetCode"' in metadata
    assert '"share/aether/examples/llvm"' in metadata
    assert str(ROOT) not in metadata


def test_packaging_excludes_deprecated_qt_and_legacy_surfaces() -> None:
    metadata = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    lowered = metadata.casefold()
    assert "pyside" not in lowered
    assert "pyqt" not in lowered
    assert "platformdirs" not in lowered
    assert "studio =" not in lowered
    assert 'aether = "aether.cli:main"' in metadata
    assert 'aether-lsp = "aether_lsp.server:main"' in metadata

    removed_paths = (
        "legacy",
        "docs/legacy",
        "src/qt_app.py",
        "src/main.py",
        "src/ui",
        "src/editor",
        "src/actions",
        "src/repl",
        "src/app_preferences.py",
        "src/language_runtime.py",
        "src/numeric_format.py",
        "tools/web_editor",
    )
    assert all(not (ROOT / path).exists() for path in removed_paths)
    assert (ROOT / "src/aether_lsp/server.py").is_file()
    assert (ROOT / "vscode-extension/package.json").is_file()
    assert (ROOT / "tools/intellij-aether/build.gradle.kts").is_file()


def test_release_archive_policy_rejects_deprecated_tooling_paths() -> None:
    release = _load_script("release.py")
    names = {
        "aether-1.0.0/legacy/src/parser.py",
        "aether-1.0.0/src/ui/editor.py",
        "aether-1.0.0/src/qt_app.py",
        "aether-1.0.0/tools/web_editor/package.json",
    }

    assert release._unsafe_archive_names(names, wheel=False) == sorted(names)


def test_public_packaging_expectations_come_from_canonical_manifest() -> None:
    release = _load_script("release.py")
    paths = release._public_example_paths()

    assert "examples/LeetCode/isPalindrome.ae" in paths
    assert len(paths) == len(set(paths))
    assert all((ROOT / path).is_file() for path in paths)


def test_wheel_from_sdist_comparison_fails_closed(tmp_path: Path) -> None:
    release = _load_script("release.py")
    direct = tmp_path / "direct.whl"
    rebuilt = tmp_path / "rebuilt.whl"
    with zipfile.ZipFile(direct, "w") as archive:
        archive.writestr("aether/cli.py", "direct")
        archive.writestr("pkg.dist-info/RECORD", "ignored")
    with zipfile.ZipFile(rebuilt, "w") as archive:
        archive.writestr("aether/cli.py", "rebuilt")
        archive.writestr("pkg.dist-info/RECORD", "also ignored")

    with pytest.raises(release.ReleaseError, match="materially different"):
        release.compare_wheel_contents(direct, rebuilt)
