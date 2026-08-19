from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys
import sysconfig
import textwrap
import venv


ROOT = Path(__file__).resolve().parents[1]


def test_clean_wheel_install_has_rust_verifier_metadata(
    tmp_path: Path,
    rust_verifier_executable: Path,
) -> None:
    wheel_directory = tmp_path / "wheel"
    subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "wheel",
            "--no-deps",
            "--no-build-isolation",
            "--wheel-dir",
            str(wheel_directory),
            str(ROOT),
        ],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    wheel = next(wheel_directory.glob("aether_language-*.whl"))
    environment = tmp_path / "venv"
    venv.EnvBuilder(with_pip=True).create(environment)
    scripts = environment / ("Scripts" if os.name == "nt" else "bin")
    python = scripts / ("python.exe" if os.name == "nt" else "python")
    clean_site_packages = subprocess.run(
        [str(python), "-c", "import sysconfig; print(sysconfig.get_path('purelib'))"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    # Reuse the test environment's installed third-party wheels without exposing
    # its editable Aether checkout; nested .pth files are not processed here.
    (Path(clean_site_packages) / "test-dependencies.pth").write_text(
        sysconfig.get_path("purelib") + "\n",
        encoding="utf-8",
    )
    subprocess.run(
        [str(python), "-m", "pip", "install", "--no-deps", str(wheel)],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )

    clean_environment = os.environ.copy()
    clean_environment.pop("PYTHONPATH", None)
    completed = subprocess.run(
        [str(scripts / ("aether.exe" if os.name == "nt" else "aether")), "--version"],
        cwd=tmp_path,
        env=clean_environment,
        check=True,
        capture_output=True,
        text=True,
    )
    assert completed.stdout

    package = tmp_path / "verifier-package"
    package.mkdir()
    executable_name = (
        "aether-ir-verifier.exe" if os.name == "nt" else "aether-ir-verifier"
    )
    shutil.copy2(rust_verifier_executable, package / executable_name)
    qualification = textwrap.dedent(
        """
        import json
        from pathlib import Path

        from aether.ir import (
            RUST_VERIFIER_PACKAGE_VERSION,
            canonical_rust_verifier_platform_id,
            discover_packaged_rust_verifier,
            rust_verifier_package_manifest,
        )

        package = Path("verifier-package")
        executable = next(
            path for path in package.iterdir() if path.name != "manifest.json"
        )
        manifest = rust_verifier_package_manifest(
            executable,
            platform_tag=canonical_rust_verifier_platform_id(),
        )
        (package / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        selection = discover_packaged_rust_verifier(package)
        assert RUST_VERIFIER_PACKAGE_VERSION == "0.1.0"
        assert selection.identity.version == "0.1.0"
        assert selection.identity.protocol_versions == (1,)
        assert selection.identity.ir_schema_versions == (1,)
        assert selection.identity.capabilities == ("verify",)
        """
    )
    subprocess.run(
        [str(python), "-c", qualification],
        cwd=tmp_path,
        env=clean_environment,
        check=True,
        capture_output=True,
        text=True,
    )
