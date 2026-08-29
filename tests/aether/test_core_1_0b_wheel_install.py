from __future__ import annotations

import importlib.util
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
from zipfile import ZIP_DEFLATED, ZipFile

from packaging.tags import sys_tags
import pytest


ROOT = Path(__file__).resolve().parents[2]
INSTALLER = ROOT / "scripts/install_core_1_0b_wheels.py"
WORKFLOW = ROOT / ".github/workflows/core-in-process-promotion.yml"


def _installer_module():
    spec = importlib.util.spec_from_file_location("core_1_0b_wheels", INSTALLER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_wheel(
    directory: Path,
    distribution: str,
    tag: str,
    *,
    version: str = "1.0.0rc4",
    build: str = "",
    metadata_distribution: str | None = None,
    requires_dist: tuple[str, ...] | None = None,
) -> Path:
    filename_distribution = distribution.replace("-", "_")
    build_component = f"-{build}" if build else ""
    wheel = directory / (
        f"{filename_distribution}-{version}{build_component}-{tag}.whl"
    )
    dist_info = f"{filename_distribution}-{version}.dist-info"
    with ZipFile(wheel, "w", compression=ZIP_DEFLATED) as archive:
        requirements = (
            ("aether-compiler-core==1.0.0rc4",)
            if requires_dist is None and distribution == "aether-language"
            else requires_dist or ()
        )
        archive.writestr(
            f"{dist_info}/METADATA",
            "Metadata-Version: 2.1\n"
            f"Name: {metadata_distribution or distribution}\n"
            f"Version: {version}\n"
            + "".join(
                f"Requires-Dist: {requirement}\n"
                for requirement in requirements
            ),
        )
        archive.writestr(
            f"{dist_info}/WHEEL",
            "Wheel-Version: 1.0\n"
            "Generator: CORE-1.0B regression test\n"
            "Root-Is-Purelib: true\n"
            f"Tag: {tag}\n",
        )
        archive.writestr(f"{dist_info}/RECORD", "")
    return wheel


def test_selects_exact_native_and_language_wheels(tmp_path: Path) -> None:
    installer = _installer_module()
    native_dir = tmp_path / "native-dist"
    language_dir = tmp_path / "language-dist"
    native_dir.mkdir()
    language_dir.mkdir()
    native = _write_wheel(
        native_dir, "aether-compiler-core", str(next(sys_tags()))
    )
    language = _write_wheel(language_dir, "aether-language", "py3-none-any")

    assert installer.select_exact_wheel(
        native_dir, "aether-compiler-core"
    ) == native.resolve()
    assert installer.select_exact_wheel(
        language_dir, "aether-language"
    ) == language.resolve()


def test_wheel_selection_fails_closed_on_zero_or_ambiguous_candidates(
    tmp_path: Path,
) -> None:
    installer = _installer_module()
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(installer.WheelSelectionError, match="no compatible"):
        installer.select_exact_wheel(empty, "aether-compiler-core")

    native_dir = tmp_path / "native-dist"
    native_dir.mkdir()
    tag = str(next(sys_tags()))
    _write_wheel(native_dir, "aether-compiler-core", tag, build="1")
    _write_wheel(native_dir, "aether-compiler-core", tag, build="2")
    with pytest.raises(installer.WheelSelectionError, match="ambiguous compatible"):
        installer.select_exact_wheel(native_dir, "aether-compiler-core")


def test_wheel_selection_rejects_wrong_metadata_identity(tmp_path: Path) -> None:
    installer = _installer_module()
    native_dir = tmp_path / "native-dist"
    native_dir.mkdir()
    _write_wheel(
        native_dir,
        "aether-compiler-core",
        str(next(sys_tags())),
        metadata_distribution="substituted-core",
    )

    with pytest.raises(installer.WheelSelectionError, match="no compatible"):
        installer.select_exact_wheel(native_dir, "aether-compiler-core")


def test_installer_passes_concrete_paths_without_powershell_globbing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    installer = _installer_module()
    native_dir = tmp_path / "native-dist"
    language_dir = tmp_path / "language-dist"
    native_dir.mkdir()
    language_dir.mkdir()
    native = _write_wheel(
        native_dir, "aether-compiler-core", str(next(sys_tags()))
    )
    language = _write_wheel(language_dir, "aether-language", "py3-none-any")
    windows_python = Path(r"C:\consumer\Scripts\python.exe")
    calls: list[tuple[list[str], bool]] = []

    def fake_run(command: list[str], *, check: bool):
        calls.append((command, check))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(installer.subprocess, "run", fake_run)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            str(INSTALLER),
            "--native-dir",
            str(native_dir),
            "--language-dir",
            str(language_dir),
            "--python",
            str(windows_python),
        ],
    )

    assert installer.main() == 0
    assert calls == [
        (
            [
                str(windows_python),
                "-I",
                "-m",
                "pip",
                "install",
                "--force-reinstall",
                "--no-deps",
                str(native.resolve()),
                str(language.resolve()),
            ],
            True,
        ),
        ([str(windows_python), "-I", "-m", "pip", "check"], True),
    ]
    assert all("*" not in argument for argument in calls[0][0])


def test_installer_derives_runtime_dependencies_then_installs_exact_wheels(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    installer = _installer_module()
    native_dir = tmp_path / "native-dist"
    language_dir = tmp_path / "language-dist"
    native_dir.mkdir()
    language_dir.mkdir()
    native = _write_wheel(
        native_dir, "aether-compiler-core", str(next(sys_tags()))
    )
    language = _write_wheel(
        language_dir,
        "aether-language",
        "py3-none-any",
        requires_dist=(
            "aether-compiler-core==1.0.0rc4",
            "numpy==2.4.2",
            "conditional-runtime==7; python_version < '1'",
        ),
    )
    calls: list[list[str]] = []

    def fake_run(command: list[str], *, check: bool):
        assert check is True
        calls.append(command)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(installer.subprocess, "run", fake_run)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            str(INSTALLER),
            "--native-dir",
            str(native_dir),
            "--language-dir",
            str(language_dir),
            "--python",
            sys.executable,
        ],
    )

    assert installer.main() == 0
    assert calls == [
        [
            sys.executable,
            "-I",
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "numpy==2.4.2",
        ],
        installer.concrete_install_command(
            Path(sys.executable), native.resolve(), language.resolve()
        ),
        [sys.executable, "-I", "-m", "pip", "check"],
    ]
    assert all(
        "aether-language" not in argument
        and "aether-compiler-core" not in argument
        for argument in calls[0]
    )


def test_installer_installs_both_concrete_wheels_into_clean_venv(
    tmp_path: Path,
) -> None:
    native_dir = tmp_path / "native-dist"
    language_dir = tmp_path / "language-dist"
    native_dir.mkdir()
    language_dir.mkdir()
    _write_wheel(native_dir, "aether-compiler-core", str(next(sys_tags())))
    _write_wheel(language_dir, "aether-language", "py3-none-any")
    consumer = tmp_path / "consumer"
    subprocess.run([sys.executable, "-m", "venv", str(consumer)], check=True)
    python = consumer / (
        "Scripts/python.exe" if sys.platform == "win32" else "bin/python"
    )

    subprocess.run(
        [
            sys.executable,
            str(INSTALLER),
            "--native-dir",
            str(native_dir),
            "--language-dir",
            str(language_dir),
            "--python",
            str(python),
        ],
        check=True,
    )
    installed = subprocess.run(
        [
            str(python),
            "-c",
            "import importlib.metadata as m; "
            "print(m.version('aether-compiler-core'), "
            "m.version('aether-language'))",
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    assert installed.stdout.strip() == "1.0.0rc4 1.0.0rc4"


def test_workflow_uses_portable_installer_for_every_two_wheel_install() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")

    assert text.count("python scripts/install_core_1_0b_wheels.py") == 3
    assert "native-dist/*.whl language-dist/*.whl" not in text
