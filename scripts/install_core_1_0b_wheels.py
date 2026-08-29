#!/usr/bin/env python3
"""Select and install the exact CORE-1.0B wheels without shell globbing."""

from __future__ import annotations

import argparse
from email.parser import BytesParser
from email.policy import compat32
from pathlib import Path
import subprocess
import sys
from zipfile import BadZipFile, ZipFile

from packaging.tags import Tag, parse_tag, sys_tags
from packaging.utils import canonicalize_name, parse_wheel_filename


NATIVE_DISTRIBUTION = canonicalize_name("aether-compiler-core")
LANGUAGE_DISTRIBUTION = canonicalize_name("aether-language")
EXPECTED_VERSION = "1.0.0rc4"


class WheelSelectionError(ValueError):
    """The requested wheel set cannot be selected without guessing."""


def _wheel_metadata(path: Path) -> tuple[str, str, frozenset[Tag]]:
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
        "-m",
        "pip",
        "install",
        "--force-reinstall",
        "--no-deps",
        str(native_wheel),
        str(language_wheel),
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--native-dir", type=Path, default=Path("native-dist"))
    parser.add_argument("--language-dir", type=Path, default=Path("language-dist"))
    parser.add_argument("--python", type=Path, default=Path(sys.executable))
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

    command = concrete_install_command(args.python, native_wheel, language_wheel)
    print(f"CORE-1.0B native wheel: {native_wheel}")
    print(f"CORE-1.0B language wheel: {language_wheel}")
    subprocess.run(command, check=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
