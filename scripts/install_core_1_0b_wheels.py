#!/usr/bin/env python3
"""Select and install the exact CORE-1.0B wheels without shell globbing."""

from __future__ import annotations

import argparse
from email.parser import BytesParser
from email.policy import compat32
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys
from zipfile import BadZipFile, ZipFile

from packaging.requirements import InvalidRequirement, Requirement
from packaging.tags import Tag, parse_tag, sys_tags
from packaging.utils import canonicalize_name, parse_wheel_filename


NATIVE_DISTRIBUTION = canonicalize_name("aether-compiler-core")
LANGUAGE_DISTRIBUTION = canonicalize_name("aether-language")
EXPECTED_VERSION = "1.0.0rc4"


class WheelSelectionError(ValueError):
    """The requested wheel set cannot be selected without guessing."""


def _read_wheel_metadata(path: Path):
    try:
        with ZipFile(path) as archive:
            metadata_members = [
                name
                for name in archive.namelist()
                if name.endswith(".dist-info/METADATA")
            ]
            wheel_members = [
                name
                for name in archive.namelist()
                if name.endswith(".dist-info/WHEEL")
            ]
            if len(metadata_members) != 1 or len(wheel_members) != 1:
                raise WheelSelectionError(
                    "wheel must contain exactly one dist-info/METADATA and WHEEL"
                )
            metadata = BytesParser(policy=compat32).parsebytes(
                archive.read(metadata_members[0])
            )
            wheel_metadata = BytesParser(policy=compat32).parsebytes(
                archive.read(wheel_members[0])
            )
    except (BadZipFile, OSError) as error:
        raise WheelSelectionError(f"cannot read wheel metadata: {error}") from error

    return metadata, wheel_metadata


def _wheel_metadata(path: Path) -> tuple[str, str, frozenset[Tag]]:
    metadata, wheel_metadata = _read_wheel_metadata(path)

    distribution = metadata.get("Name")
    version = metadata.get("Version")
    raw_tags = wheel_metadata.get_all("Tag", [])
    if not distribution or not version or not raw_tags:
        raise WheelSelectionError("wheel metadata is missing Name, Version, or Tag")
    try:
        tags = frozenset(
            tag for raw_tag in raw_tags for tag in parse_tag(raw_tag.strip())
        )
    except ValueError as error:
        raise WheelSelectionError(f"invalid WHEEL Tag metadata: {error}") from error
    return distribution, version, tags


def declared_runtime_requirements(
    native_wheel: Path, language_wheel: Path
) -> tuple[str, ...]:
    """Return active, pinned non-Aether requirements from exact wheel metadata."""
    selected: dict[str, str] = {}
    exact_native_requirement_seen = False
    for wheel in (native_wheel, language_wheel):
        metadata, _wheel_metadata_message = _read_wheel_metadata(wheel)
        for raw_requirement in metadata.get_all("Requires-Dist", []):
            try:
                requirement = Requirement(raw_requirement)
            except InvalidRequirement as error:
                raise WheelSelectionError(
                    f"invalid Requires-Dist in {wheel.name}: {raw_requirement!r}"
                ) from error
            if requirement.marker is not None and not requirement.marker.evaluate(
                {"extra": ""}
            ):
                continue
            name = canonicalize_name(requirement.name)
            if name == NATIVE_DISTRIBUTION:
                specifiers = list(requirement.specifier)
                if not (
                    wheel == language_wheel
                    and requirement.url is None
                    and len(specifiers) == 1
                    and specifiers[0].operator == "=="
                    and specifiers[0].version == EXPECTED_VERSION
                ):
                    raise WheelSelectionError(
                        "aether-language must require the selected native wheel "
                        f"exactly at {EXPECTED_VERSION}"
                    )
                exact_native_requirement_seen = True
                continue
            if name == LANGUAGE_DISTRIBUTION:
                raise WheelSelectionError(
                    "wheel metadata must not resolve aether-language from an index"
                )
            specifiers = list(requirement.specifier)
            if (
                requirement.url is not None
                or len(specifiers) != 1
                or specifiers[0].operator != "=="
                or specifiers[0].version.endswith(".*")
            ):
                raise WheelSelectionError(
                    "clean-consumer runtime dependencies must be exact pins; "
                    f"found {raw_requirement!r} in {wheel.name}"
                )
            rendered = str(requirement)
            previous = selected.get(name)
            if previous is not None and previous != rendered:
                raise WheelSelectionError(
                    f"conflicting runtime requirements for {name}: "
                    f"{previous!r} and {rendered!r}"
                )
            selected[name] = rendered
    if not exact_native_requirement_seen:
        raise WheelSelectionError(
            "aether-language wheel is missing its exact "
            f"aether-compiler-core=={EXPECTED_VERSION} dependency"
        )
    return tuple(selected[name] for name in sorted(selected))


def runtime_dependency_install_command(
    python: Path, requirements: tuple[str, ...]
) -> list[str]:
    return [
        str(python),
        "-I",
        "-m",
        "pip",
        "install",
        "--disable-pip-version-check",
        *requirements,
    ]


def _inspect_wheel(
    path: Path,
    expected_distribution: str,
    expected_version: str,
    supported: frozenset[Tag],
) -> dict[str, object]:
    result: dict[str, object] = {
        "filename": path.name,
        "eligible": False,
    }
    try:
        filename_distribution, filename_version, _build, filename_tags = (
            parse_wheel_filename(path.name)
        )
        metadata_distribution, metadata_version, metadata_tags = _wheel_metadata(path)
        filename_distribution = canonicalize_name(filename_distribution)
        metadata_distribution = canonicalize_name(metadata_distribution)
        matching_tags = filename_tags & supported
        if filename_distribution != expected_distribution:
            result["reason"] = "unexpected filename distribution"
        elif metadata_distribution != expected_distribution:
            result["reason"] = "unexpected METADATA distribution"
        elif str(filename_version) != expected_version:
            result["reason"] = "unexpected filename version"
        elif metadata_version != expected_version:
            result["reason"] = "unexpected METADATA version"
        elif filename_tags != metadata_tags:
            result["reason"] = "filename and WHEEL metadata tags differ"
        elif not matching_tags:
            result["reason"] = "wheel tags are incompatible with this interpreter"
        else:
            result["eligible"] = True
            result["reason"] = "exact distribution/version with compatible tags"
    except (ValueError, WheelSelectionError) as error:
        result["reason"] = str(error)
    return result


def select_exact_wheel(
    directory: Path,
    distribution: str,
    version: str = EXPECTED_VERSION,
    *,
    supported: frozenset[Tag] | None = None,
) -> Path:
    """Return one exact compatible wheel or fail closed on zero/ambiguity."""
    normalized_distribution = canonicalize_name(distribution)
    candidates = (
        sorted(directory.glob("*.whl"), key=lambda path: path.name)
        if directory.is_dir()
        else []
    )
    supported_tags = supported if supported is not None else frozenset(sys_tags())
    inspections = [
        _inspect_wheel(
            candidate, normalized_distribution, version, supported_tags
        )
        for candidate in candidates
    ]
    eligible = [
        candidate
        for candidate, inspection in zip(candidates, inspections, strict=True)
        if inspection["eligible"] is True
    ]
    summary = (
        "; ".join(
            f"{candidate.name}: {inspection['reason']}"
            for candidate, inspection in zip(candidates, inspections, strict=True)
        )
        or "directory contains no wheel files"
    )
    if not eligible:
        raise WheelSelectionError(
            f"no compatible {normalized_distribution}=={version} wheel in "
            f"{directory}: {summary}"
        )
    if len(eligible) != 1:
        raise WheelSelectionError(
            f"ambiguous compatible {normalized_distribution}=={version} wheels "
            f"({len(eligible)}) in {directory}: {summary}"
        )
    return eligible[0].resolve()


def concrete_install_command(
    python: Path, native_wheel: Path, language_wheel: Path
) -> list[str]:
    return [
        str(python),
        "-I",
        "-m",
        "pip",
        "install",
        "--force-reinstall",
        "--no-deps",
        str(native_wheel),
        str(language_wheel),
    ]


def _installed_environment(python: Path) -> dict[str, object]:
    script = (
        "import importlib.metadata as m, json, sys; "
        "print(json.dumps({'python_executable': sys.executable, "
        "'python_version': sys.version, "
        "'distributions': sorted([{'name': d.metadata['Name'], "
        "'version': d.version} for d in m.distributions()], "
        "key=lambda x: x['name'].lower())}, sort_keys=True))"
    )
    completed = subprocess.run(
        [str(python), "-I", "-c", script],
        check=True,
        capture_output=True,
        text=True,
    )
    value = json.loads(completed.stdout)
    if not isinstance(value, dict):
        raise RuntimeError("installed environment inventory is not an object")
    return value


def _wheel_record(path: Path) -> dict[str, object]:
    distribution, version, _tags = _wheel_metadata(path)
    return {
        "distribution": distribution,
        "version": version,
        "path": str(path),
        "sha256": sha256(path.read_bytes()).hexdigest(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--native-dir", type=Path, default=Path("native-dist"))
    parser.add_argument("--language-dir", type=Path, default=Path("language-dist"))
    parser.add_argument("--python", type=Path, default=Path(sys.executable))
    parser.add_argument("--revision")
    parser.add_argument("--ci-run-id")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        native_wheel = select_exact_wheel(
            args.native_dir, NATIVE_DISTRIBUTION
        )
        language_wheel = select_exact_wheel(
            args.language_dir, LANGUAGE_DISTRIBUTION
        )
    except WheelSelectionError as error:
        parser.error(str(error))

    try:
        runtime_requirements = declared_runtime_requirements(
            native_wheel, language_wheel
        )
    except WheelSelectionError as error:
        parser.error(str(error))

    print(f"CORE-1.0B native wheel: {native_wheel}")
    print(f"CORE-1.0B language wheel: {language_wheel}")
    print(
        "CORE-1.0B runtime requirements: "
        + (", ".join(runtime_requirements) or "none")
    )
    if runtime_requirements:
        subprocess.run(
            runtime_dependency_install_command(args.python, runtime_requirements),
            check=True,
        )
    subprocess.run(
        concrete_install_command(args.python, native_wheel, language_wheel),
        check=True,
    )
    subprocess.run([str(args.python), "-I", "-m", "pip", "check"], check=True)
    if args.output is not None:
        environment = _installed_environment(args.python)
        record = {
            "artifact_schema_version": 1,
            "kind": "core_1_0b_clean_consumer_install",
            "milestone": "CORE-1.0B",
            "status": "PASS",
            "exact_revision": args.revision,
            "ci_run_id": args.ci_run_id,
            "wheels": {
                "aether-compiler-core": _wheel_record(native_wheel),
                "aether-language": _wheel_record(language_wheel),
            },
            "runtime_requirements_from_wheel_metadata": list(
                runtime_requirements
            ),
            "installed_distributions": environment["distributions"],
            "python_executable": environment["python_executable"],
            "python_version": environment["python_version"],
            "installation_order": [
                "runtime_dependencies_from_wheel_metadata",
                "exact_aether_wheels_with_no_deps",
            ],
            "aether_index_resolution_permitted": False,
            "dependency_validation": "pip check PASS",
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(record, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
