#!/usr/bin/env python3
"""Build and verify unpublished Aether release artifacts."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from pathlib import PurePosixPath
import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile
import tomllib
import venv
import zipfile


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from aether.capabilities import CAPABILITY_PROFILE_VERSION  # noqa: E402
from aether.version import LANGUAGE_VERSION, PACKAGE_VERSION, RELEASE_TAG  # noqa: E402


DIST = ROOT / "dist"
SUPPORTED_NATIVE_PLATFORMS = ("Linux x86_64",)
REQUIRED_WHEEL_PATHS = (
    "aether/cli.py",
    "aether/pipeline.py",
    "aether/typechecker.py",
    "aether/interpreter.py",
    "aether/stdlib/core.py",
    "aether/stdlib/io.py",
    "aether/backend/llvm/runtime.py",
    "aether/backend/llvm/string_runtime.py",
    "aether_lsp/server.py",
)
REQUIRED_WHEEL_SUFFIXES = (
    "share/doc/aether/README.md",
    "share/doc/aether/CHANGELOG.md",
    "share/doc/aether/LICENSE",
    "share/doc/aether/AETHER_LANGUAGE_SPEC_V1.md",
    "share/doc/aether/AETHER_NATIVE_PROFILE_V1.md",
    "share/doc/aether/AETHER_FRONTEND_EXPERIMENTS.md",
    "share/doc/aether/AETHER_DIAGNOSTICS.md",
    "share/doc/aether/AETHER_1_0_0_RC4_RELEASE_NOTES.md",
    "share/doc/aether/EXCEPTION_PROMOTION_EVIDENCE.md",
    "share/doc/aether/EXCEPTION_PROMOTION_DIFFERENTIAL_REPORT.json",
    "share/aether/examples/README.md",
    "share/aether/examples/v1_examples_manifest.json",
    "share/aether/examples/hello.ae",
    "share/aether/corpus/exceptions/README.md",
    "share/aether/corpus/exceptions/catalog.json",
)
FORBIDDEN_ARCHIVE_PARTS = frozenset(
    {
        ".git",
        ".venv",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        "__pycache__",
        "build",
        "dist",
    }
)
FORBIDDEN_CREDENTIAL_NAMES = frozenset(
    {".env", ".pypirc", "credentials.json", "id_rsa", "id_ed25519"}
)
FORBIDDEN_BINARY_SUFFIXES = (
    ".a",
    ".bc",
    ".dll",
    ".dylib",
    ".exe",
    ".ll",
    ".o",
    ".obj",
    ".so",
)
FORBIDDEN_TEMP_SUFFIXES = (".bak", ".swp", ".temp", ".tmp", "~")
DEPRECATED_MODULE_NAMES = frozenset(
    {
        "app_preferences.py",
        "language_runtime.py",
        "main.py",
        "numeric_format.py",
        "qt_app.py",
    }
)
EXPECTED_ENTRY_POINTS = {
    "aether": "aether.cli:main",
    "aether-lsp": "aether_lsp.server:main",
}
FORBIDDEN_DEPENDENCIES = ("pyside", "pyqt", "platformdirs")


class ReleaseError(RuntimeError):
    pass


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--version",
        default=LANGUAGE_VERSION,
        help="Public Aether version (defaults to the canonical package version).",
    )
    parser.add_argument(
        "--allow-dirty",
        action="store_true",
        help="Allow a development build and record dirty_worktree=true.",
    )
    parser.add_argument(
        "--skip-gates",
        action="store_true",
        help="Development only: skip CI gates but still build and smoke-test artifacts.",
    )
    return parser


def _run(
    command: list[str],
    *,
    cwd: Path = ROOT,
    env: dict[str, str] | None = None,
    capture: bool = False,
) -> subprocess.CompletedProcess[str]:
    print("$ " + " ".join(command), flush=True)
    completed = subprocess.run(
        command,
        cwd=cwd,
        env=env,
        check=False,
        text=True,
        capture_output=capture,
    )
    if completed.returncode != 0:
        detail = "\n".join(
            part.strip() for part in (completed.stdout, completed.stderr) if part.strip()
        )
        raise ReleaseError(
            f"command failed with exit code {completed.returncode}: {' '.join(command)}"
            + (f"\n{detail}" if detail else "")
        )
    return completed


def _git(*arguments: str) -> str:
    return _run(["git", *arguments], capture=True).stdout.strip()


def _dirty_worktree() -> bool:
    return bool(_git("status", "--porcelain=v1", "--untracked-files=all"))


def _build_timestamp(commit: str) -> tuple[str, str, str]:
    source_epoch = os.environ.get("SOURCE_DATE_EPOCH")
    policy = "SOURCE_DATE_EPOCH environment"
    if source_epoch is None:
        source_epoch = _git("show", "-s", "--format=%ct", commit)
        policy = "git commit timestamp"
    try:
        timestamp = datetime.fromtimestamp(int(source_epoch), tz=timezone.utc)
    except (ValueError, OSError) as exc:
        raise ReleaseError(f"invalid SOURCE_DATE_EPOCH: {source_epoch!r}") from exc
    return timestamp.isoformat().replace("+00:00", "Z"), policy, source_epoch


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _public_example_paths() -> tuple[str, ...]:
    manifest = json.loads(
        (ROOT / "examples" / "v1_examples_manifest.json").read_text(encoding="utf-8")
    )
    return tuple(str(entry["path"]) for entry in manifest["entries"])


def _exception_corpus_paths() -> tuple[str, ...]:
    catalog = json.loads(
        (ROOT / "corpus" / "exceptions" / "catalog.json").read_text(
            encoding="utf-8"
        )
    )
    return tuple(
        "corpus/exceptions/" + str(entry["path"])
        for group in ("positive", "negative")
        for entry in catalog[group]
    )


def _project_metadata() -> dict[str, object]:
    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))[
        "project"
    ]


def _wheel_payload(names: set[str]) -> set[str]:
    """Return content relevant to runtime/packaging parity, excluding build records."""
    return {
        name
        for name in names
        if not name.endswith("/")
        and not name.endswith(".dist-info/RECORD")
        and not name.endswith(".dist-info/WHEEL")
    }


def compare_wheel_contents(direct: Path, reconstructed: Path) -> None:
    with zipfile.ZipFile(direct) as direct_archive, zipfile.ZipFile(
        reconstructed
    ) as reconstructed_archive:
        direct_names = _wheel_payload(set(direct_archive.namelist()))
        reconstructed_names = _wheel_payload(set(reconstructed_archive.namelist()))
        if direct_names != reconstructed_names:
            missing = sorted(direct_names - reconstructed_names)
            extra = sorted(reconstructed_names - direct_names)
            raise ReleaseError(
                "wheel rebuilt from sdist has a different content manifest; "
                f"missing={missing}, extra={extra}"
            )
        changed = sorted(
            name
            for name in direct_names
            if direct_archive.read(name) != reconstructed_archive.read(name)
        )
        if changed:
            raise ReleaseError(
                "wheel rebuilt from sdist has materially different files: "
                + ", ".join(changed)
            )
def _unsafe_archive_names(names: set[str], *, wheel: bool) -> list[str]:
    unsafe: list[str] = []
    for name in names:
        path = PurePosixPath(name.rstrip("/"))
        parts = tuple(part.lower() for part in path.parts)
        basename = parts[-1] if parts else ""
        if path.is_absolute() or ".." in parts:
            unsafe.append(name)
            continue
        if FORBIDDEN_ARCHIVE_PARTS.intersection(parts):
            unsafe.append(name)
            continue
        if wheel and ({"tests", "fixtures"}.intersection(parts)):
            unsafe.append(name)
            continue
        if basename in FORBIDDEN_CREDENTIAL_NAMES:
            unsafe.append(name)
            continue
        if basename.endswith(FORBIDDEN_BINARY_SUFFIXES + FORBIDDEN_TEMP_SUFFIXES):
            unsafe.append(name)
            continue
        if _is_deprecated_tooling_path(path, wheel=wheel):
            unsafe.append(name)
    return sorted(unsafe)


def _is_deprecated_tooling_path(path: PurePosixPath, *, wheel: bool) -> bool:
    parts = tuple(part.lower() for part in path.parts)
    if "legacy" in parts:
        return True
    deprecated_sequences = (
        ("src", "ui"),
        ("src", "editor"),
        ("src", "actions"),
        ("src", "repl"),
        ("tools", "web_editor"),
    )
    if any(
        parts[index : index + len(sequence)] == sequence
        for sequence in deprecated_sequences
        for index in range(len(parts) - len(sequence) + 1)
    ):
        return True
    if wheel and parts and parts[0] in {"ui", "editor", "actions", "repl"}:
        return True
    basename = parts[-1] if parts else ""
    if basename not in DEPRECATED_MODULE_NAMES:
        return False
    return (wheel and len(parts) == 1) or (
        len(parts) >= 2 and parts[-2] == "src"
    )


def verify_wheel(wheel: Path) -> None:
    checkout_bytes = str(ROOT.resolve()).encode()
    with zipfile.ZipFile(wheel) as archive:
        names = set(archive.namelist())
        unsafe = _unsafe_archive_names(names, wheel=True)
        if unsafe:
            raise ReleaseError("wheel contains forbidden paths: " + ", ".join(unsafe))
        for required in REQUIRED_WHEEL_PATHS:
            if required not in names:
                raise ReleaseError(f"wheel is missing required runtime file: {required}")
        for suffix in REQUIRED_WHEEL_SUFFIXES:
            if not any(name.endswith(suffix) for name in names):
                raise ReleaseError(f"wheel is missing essential documentation: {suffix}")
        for example in _public_example_paths():
            installed = "share/aether/" + example
            if not any(name.endswith(installed) for name in names):
                raise ReleaseError(f"wheel is missing public example: {example}")
        for corpus_path in _exception_corpus_paths():
            installed = "share/aether/" + corpus_path
            if not any(name.endswith(installed) for name in names):
                raise ReleaseError(
                    f"wheel is missing exception corpus program: {corpus_path}"
                )
        metadata_names = [name for name in names if name.endswith(".dist-info/METADATA")]
        if len(metadata_names) != 1:
            raise ReleaseError("wheel must contain exactly one METADATA file")
        metadata = archive.read(metadata_names[0]).decode("utf-8")
        if f"Version: {PACKAGE_VERSION}\n" not in metadata:
            raise ReleaseError("wheel metadata does not contain the canonical package version")
        normalized_metadata = metadata.casefold()
        if any(dependency in normalized_metadata for dependency in FORBIDDEN_DEPENDENCIES):
            raise ReleaseError("wheel metadata contains a deprecated Qt IDE dependency")
        entry_points = [name for name in names if name.endswith(".dist-info/entry_points.txt")]
        entry_point_data = archive.read(entry_points[0]) if len(entry_points) == 1 else b""
        parsed_entry_points = {
            line.split("=", 1)[0].strip(): line.split("=", 1)[1].strip()
            for line in entry_point_data.decode("utf-8").splitlines()
            if "=" in line and not line.lstrip().startswith("[")
        }
        if parsed_entry_points != EXPECTED_ENTRY_POINTS:
            raise ReleaseError(
                "wheel entry points differ from the supported public surface: "
                f"{parsed_entry_points}"
            )
        project = _project_metadata()
        if f"Requires-Python: {project['requires-python']}\n" not in metadata:
            raise ReleaseError("wheel metadata has an unexpected Python requirement")
        leaked = [
            name
            for name in names
            if not name.endswith("/")
            and not name.endswith(".pyc")
            and checkout_bytes in archive.read(name)
        ]
        if leaked:
            raise ReleaseError(
                "wheel embeds the source checkout path in: " + ", ".join(leaked)
            )


def verify_sdist(sdist: Path) -> None:
    with tarfile.open(sdist, "r:gz") as archive:
        members = archive.getmembers()
        names = {member.name for member in members}
        unsafe = _unsafe_archive_names(names, wheel=False)
        if unsafe:
            raise ReleaseError("sdist contains forbidden paths: " + ", ".join(unsafe))
        checkout_bytes = str(ROOT.resolve()).encode()
        leaked: list[str] = []
        for member in members:
            if not member.isfile():
                continue
            stream = archive.extractfile(member)
            if stream is not None and checkout_bytes in stream.read():
                leaked.append(member.name)
        if leaked:
            raise ReleaseError(
                "sdist embeds the source checkout path in: " + ", ".join(leaked)
            )
    required_suffixes = (
        "/LICENSE",
        "/README.md",
        "/CHANGELOG.md",
        "/docs/aether/AETHER_LANGUAGE_SPEC_V1.md",
        "/docs/aether/AETHER_NATIVE_PROFILE_V1.md",
        "/docs/aether/AETHER_FRONTEND_EXPERIMENTS.md",
        "/docs/aether/AETHER_DIAGNOSTICS.md",
        "/docs/aether/AETHER_1_0_0_RC4_RELEASE_NOTES.md",
        "/docs/aether/AETHER_EXAMPLES_CATALOG_AUDIT.md",
        "/docs/compiler/exceptions/EXCEPTION_PROMOTION_EVIDENCE.md",
        "/docs/compiler/exceptions/EXCEPTION_PROMOTION_DIFFERENTIAL_REPORT.json",
        "/corpus/exceptions/README.md",
        "/corpus/exceptions/catalog.json",
        "/examples/README.md",
        "/examples/v1_examples_manifest.json",
        "/scripts/release.py",
        "/scripts/ci.py",
        "/scripts/check_examples_catalog.py",
        "/scripts/check_exception_promotion.py",
        "/scripts/check_diagnostics_contract.py",
        "/scripts/differential_parity.py",
        "/src/aether/cli.py",
        "/src/aether/pipeline.py",
        "/src/aether/backend/llvm/runtime.py",
        "/src/aether/stdlib/core.py",
        "/src/aether_lsp/server.py",
        "/tests/fixtures/invalid/list_slice_assignment.ae",
        "/tests/fixtures/invalid/list_slice_assignment.json",
    )
    for suffix in required_suffixes:
        if not any(name.endswith(suffix) for name in names):
            raise ReleaseError(f"sdist is missing required file: {suffix}")
    for example in _public_example_paths():
        if not any(name.endswith("/" + example) for name in names):
            raise ReleaseError(f"sdist is missing public example: {example}")
    for corpus_path in _exception_corpus_paths():
        if not any(name.endswith("/" + corpus_path) for name in names):
            raise ReleaseError(
                f"sdist is missing exception corpus program: {corpus_path}"
            )


def _venv_commands(environment: Path) -> tuple[Path, Path]:
    if os.name == "nt":
        return environment / "Scripts" / "python.exe", environment / "Scripts" / "aether.exe"
    return environment / "bin" / "python", environment / "bin" / "aether"


def _write_smoke_sources(root: Path) -> dict[str, Path]:
    sources = {
        "hello": 'println("wheel-native");\n',
        "Support": (
            "package Support; public string message() { return \"module-ok\"; }\n"
        ),
        "module": (
            "import Support; int main() { println(Support.message()); return 0; }\n"
        ),
        "core": (
            "import System; int main() { "
            "string value = \"  alpha,beta  \".trim(); "
            "Array<string> parts = value.split(\",\"); "
            "List<int> values = {1}; values.push(2); "
            "println(parts[0]); println(values.length); "
            "println(System.args()[0]); return 0; }\n"
        ),
        "files": (
            "import io; int main() { "
            'FileStatus saved = io.writeText("smoke.txt", "hé"); '
            'FileReadResult loaded = io.readText("smoke.txt"); '
            "println(saved); println(loaded.content); return 0; }\n"
        ),
        "rejected": (
            'struct SmokeError implements Error { string message() { return "smoke"; } } '
            'int main() { throw SmokeError(); }\n'
        ),
    }
    paths: dict[str, Path] = {}
    for name, source in sources.items():
        path = root / f"{name}.ae"
        path.write_text(source, encoding="utf-8")
        paths[name] = path
    return paths


def _expect(
    command: list[str],
    *,
    cwd: Path,
    expected_stdout: str | None = None,
    expected_code: int = 0,
    stderr_contains: str | None = None,
    env: dict[str, str],
) -> None:
    completed = subprocess.run(
        command,
        cwd=cwd,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != expected_code:
        raise ReleaseError(
            f"smoke command returned {completed.returncode}, expected {expected_code}: "
            f"{' '.join(command)}\nstdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
        )
    if expected_stdout is not None and completed.stdout != expected_stdout:
        raise ReleaseError(
            f"unexpected smoke stdout for {' '.join(command)}: {completed.stdout!r}"
        )
    if stderr_contains is not None and stderr_contains not in completed.stderr:
        raise ReleaseError(
            f"smoke stderr does not contain {stderr_contains!r}: {completed.stderr!r}"
        )


def clean_install_smoke(wheel: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="aether-wheel-smoke-") as temporary:
        temporary_root = Path(temporary)
        environment = temporary_root / "venv"
        work = temporary_root / "work"
        work.mkdir()
        venv.EnvBuilder(with_pip=True, clear=False).create(environment)
        python, aether = _venv_commands(environment)
        smoke_env = os.environ.copy()
        smoke_env.pop("PYTHONPATH", None)
        smoke_env["PYTHONNOUSERSITE"] = "1"
        _run(
            [
                str(python),
                "-m",
                "pip",
                "install",
                "--disable-pip-version-check",
                str(wheel),
            ],
            cwd=work,
            env=smoke_env,
        )
        paths = _write_smoke_sources(work)
        _expect(
            [str(aether), "--help"],
            cwd=work,
            env=smoke_env,
        )
        _expect(
            [str(aether), "--version"],
            cwd=work,
            expected_stdout=(
                f"Aether {LANGUAGE_VERSION}\n"
                f"Native capability profile {CAPABILITY_PROFILE_VERSION}\n"
            ),
            env=smoke_env,
        )
        aether_lsp = aether.with_name(
            "aether-lsp.exe" if os.name == "nt" else "aether-lsp"
        )
        _expect([str(aether_lsp), "--help"], cwd=work, env=smoke_env)
        resource_probe = _run(
            [
                str(python),
                "-c",
                (
                    "import json, pathlib, sysconfig; "
                    "root=pathlib.Path(sysconfig.get_path('data'))/'share'/'aether'; "
                    "manifest=json.loads((root/'examples'/'v1_examples_manifest.json').read_text()); "
                    "assert all((root/e['path']).is_file() for e in manifest['entries']); "
                    "catalog=json.loads((root/'corpus'/'exceptions'/'catalog.json').read_text()); "
                    "assert all((root/'corpus'/'exceptions'/e['path']).is_file() "
                    "for group in ('positive','negative') for e in catalog[group]); "
                    "assert (root/'examples'/'LeetCode'/'isPalindrome.ae').is_file(); "
                    "import aether; assert 'site-packages' in pathlib.Path(aether.__file__).as_posix(); "
                    "print(root)"
                ),
            ],
            cwd=work,
            env=smoke_env,
            capture=True,
        )
        installed_resources = Path(resource_probe.stdout.strip())
        _expect(
            [str(aether), "--backend=ast", str(paths["hello"])],
            cwd=work,
            expected_stdout="wheel-native\n",
            env=smoke_env,
        )
        _expect(
            [str(aether), str(paths["hello"])],
            cwd=work,
            expected_stdout="wheel-native\n",
            env=smoke_env,
        )
        _expect(
            [str(aether), str(installed_resources / "examples/LeetCode/isPalindrome.ae")],
            cwd=work,
            env=smoke_env,
        )
        _expect(
            [str(aether), str(paths["module"])],
            cwd=work,
            expected_stdout="module-ok\n",
            env=smoke_env,
        )
        _expect(
            [str(aether), str(paths["core"]), "--", "argument-ok"],
            cwd=work,
            expected_stdout="alpha\n2\nargument-ok\n",
            env=smoke_env,
        )
        _expect(
            [str(aether), str(paths["files"])],
            cwd=work,
            expected_stdout="FileStatus.Success\nhé\n",
            env=smoke_env,
        )
        _expect(
            [str(aether), str(paths["rejected"])],
            cwd=work,
            expected_code=1,
            stderr_contains="AE-BACKEND-ERROR_HANDLING",
            env=smoke_env,
        )
        _run([str(python), "-m", "compileall", "-q", str(environment)], cwd=work, env=smoke_env)
        probe = _run(
            [
                str(python),
                "-c",
                (
                    "import importlib.metadata as m; "
                    "print(m.version('aether-language')); "
                    "import aether; print(aether.__version__)"
                ),
            ],
            cwd=work,
            env=smoke_env,
            capture=True,
        )
        if probe.stdout.splitlines() != [PACKAGE_VERSION, PACKAGE_VERSION]:
            raise ReleaseError(f"installed package version mismatch: {probe.stdout!r}")


def rebuild_wheel_from_sdist(sdist: Path, output: Path, *, env: dict[str, str]) -> Path:
    output.mkdir(parents=True, exist_ok=True)
    _run(
        [
            sys.executable,
            "-m",
            "pip",
            "wheel",
            "--disable-pip-version-check",
            "--no-deps",
            "--wheel-dir",
            str(output),
            str(sdist),
        ],
        cwd=output,
        env=env,
    )
    wheels = sorted(output.glob("*.whl"))
    if len(wheels) != 1:
        raise ReleaseError("sdist reconstruction must produce exactly one wheel")
    verify_wheel(wheels[0])
    return wheels[0]


def _copy_artifact(source: Path, destination: Path) -> None:
    if destination.exists():
        if sha256(source) == sha256(destination):
            return
        raise ReleaseError(
            f"refusing to overwrite existing artifact with different bytes: {destination}"
        )
    shutil.copy2(source, destination)


def _artifact_record(path: Path) -> dict[str, object]:
    return {
        "filename": path.name,
        "size": path.stat().st_size,
        "sha256": sha256(path),
    }


def manifest_payload(
    *,
    commit: str,
    dirty: bool,
    timestamp: str,
    timestamp_policy: str,
    source_epoch: str,
    artifacts: tuple[Path, Path],
    gates_skipped: bool,
) -> dict[str, object]:
    gate_status = "skipped-development" if gates_skipped else "passed"
    return {
        "schema_version": 1,
        "language_version": LANGUAGE_VERSION,
        "package_version": PACKAGE_VERSION,
        "release_tag": RELEASE_TAG,
        "capability_profile_version": CAPABILITY_PROFILE_VERSION,
        "git_commit": commit,
        "dirty_worktree": dirty,
        "build_timestamp": timestamp,
        "build_timestamp_policy": timestamp_policy,
        "python_version": platform.python_version(),
        "build_platform": platform.platform(),
        "supported_native_platforms": list(SUPPORTED_NATIVE_PLATFORMS),
        "reproducibility": {
            "source_date_epoch": int(source_epoch),
            "bit_for_bit_claimed": False,
        },
        "test_summary": {
            "release_gates": gate_status,
            "clean_install_smoke": "passed",
            "wheel_contents": "passed",
            "sdist_contents": "passed",
            "documentation_integrity": gate_status,
        },
        "differential_parity_summary": {
            "profile": CAPABILITY_PROFILE_VERSION,
            "programs": 12,
            "optimization_levels": ["O0", "O1", "O2"],
            "comparisons": 36,
            "status": gate_status,
        },
        "artifacts": [_artifact_record(path) for path in artifacts],
    }


def build_release(args: argparse.Namespace) -> tuple[Path, ...]:
    if args.version != LANGUAGE_VERSION:
        raise ReleaseError(
            f"requested version {args.version!r} does not match canonical {LANGUAGE_VERSION!r}"
        )
    commit = _git("rev-parse", "HEAD")
    dirty = _dirty_worktree()
    if dirty and not args.allow_dirty:
        raise ReleaseError("worktree is dirty; commit changes or pass --allow-dirty for a development build")
    if args.skip_gates and not args.allow_dirty:
        raise ReleaseError("--skip-gates requires --allow-dirty")

    if not args.skip_gates:
        _run([sys.executable, str(ROOT / "scripts" / "ci.py")])

    timestamp, timestamp_policy, source_epoch = _build_timestamp(commit)
    build_env = os.environ.copy()
    build_env["SOURCE_DATE_EPOCH"] = source_epoch
    with tempfile.TemporaryDirectory(prefix="aether-release-build-") as temporary:
        temporary_dist = Path(temporary) / "dist"
        _run(
            [
                sys.executable,
                "-m",
                "build",
                "--wheel",
                "--sdist",
                "--outdir",
                str(temporary_dist),
                str(ROOT),
            ],
            cwd=Path(temporary),
            env=build_env,
        )
        wheels = sorted(temporary_dist.glob("*.whl"))
        sdists = sorted(temporary_dist.glob("*.tar.gz"))
        if len(wheels) != 1 or len(sdists) != 1:
            raise ReleaseError("build must produce exactly one wheel and one sdist")
        wheel, sdist = wheels[0], sdists[0]
        expected_stem = f"aether_language-{PACKAGE_VERSION}"
        if not wheel.name.startswith(expected_stem) or not sdist.name.startswith(
            f"aether_language-{PACKAGE_VERSION}"
        ):
            raise ReleaseError(
                f"artifact names do not contain package version {PACKAGE_VERSION}: "
                f"{wheel.name}, {sdist.name}"
            )
        verify_wheel(wheel)
        verify_sdist(sdist)
        clean_install_smoke(wheel)
        reconstructed = rebuild_wheel_from_sdist(
            sdist, Path(temporary) / "sdist-wheel", env=build_env
        )
        compare_wheel_contents(wheel, reconstructed)
        clean_install_smoke(reconstructed)

        DIST.mkdir(parents=True, exist_ok=True)
        final_wheel = DIST / wheel.name
        final_sdist = DIST / sdist.name
        _copy_artifact(wheel, final_wheel)
        _copy_artifact(sdist, final_sdist)

    manifest_path = DIST / f"aether-{LANGUAGE_VERSION}-manifest.json"
    manifest = manifest_payload(
        commit=commit,
        dirty=dirty,
        timestamp=timestamp,
        timestamp_policy=timestamp_policy,
        source_epoch=source_epoch,
        artifacts=(final_wheel, final_sdist),
        gates_skipped=args.skip_gates,
    )
    encoded = json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    if manifest_path.exists() and manifest_path.read_text(encoding="utf-8") != encoded:
        raise ReleaseError(f"refusing to overwrite different manifest: {manifest_path}")
    manifest_path.write_text(encoded, encoding="utf-8")

    checksums_path = DIST / f"aether-{LANGUAGE_VERSION}-SHA256SUMS"
    checksummed = (final_wheel, final_sdist, manifest_path)
    checksums = "".join(f"{sha256(path)}  {path.name}\n" for path in checksummed)
    if checksums_path.exists() and checksums_path.read_text(encoding="utf-8") != checksums:
        raise ReleaseError(f"refusing to overwrite different checksums: {checksums_path}")
    checksums_path.write_text(checksums, encoding="utf-8")
    _run(["sha256sum", "--check", str(checksums_path)], cwd=DIST)
    return final_wheel, final_sdist, manifest_path, checksums_path


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        artifacts = build_release(args)
    except ReleaseError as exc:
        print(f"release failed: {exc}", file=sys.stderr)
        return 1
    print(f"PASS: built and verified Aether {LANGUAGE_VERSION} without publishing.")
    for artifact in artifacts:
        print(artifact.relative_to(ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
