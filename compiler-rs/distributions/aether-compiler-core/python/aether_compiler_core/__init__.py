"""Stable productive access to Aether's native CompilerCore distribution."""

from __future__ import annotations

from base64 import urlsafe_b64encode
from hashlib import sha256
from importlib import metadata as importlib_metadata
from importlib.resources import files
import json
import os
from pathlib import Path
from types import ModuleType
from typing import Final


DISTRIBUTION_NAME: Final = "aether-compiler-core"
PACKAGE_VERSION: Final = "1.0.0rc4"
COMPILER_CORE_API_VERSION: Final = 1
PROTOCOL_VERSION: Final = 1
INPUT_SCHEMA_VERSIONS: Final = (1,)
OUTPUT_SCHEMA_VERSIONS: Final = (2,)
NATIVE_PRODUCT_VERSION: Final = "0.1.0"
LANGUAGE_DISTRIBUTION_NAME: Final = "aether-language"
LANGUAGE_VERSION: Final = "1.0.0rc4"
_MANIFEST_RELATIVE = "aether_compiler_core/_native/native-core-manifest.json"


class NativeCoreDistributionError(RuntimeError):
    """The installed native distribution is missing or incompatible."""


def _distribution() -> importlib_metadata.Distribution:
    try:
        distribution = importlib_metadata.distribution(DISTRIBUTION_NAME)
    except importlib_metadata.PackageNotFoundError as exc:
        raise NativeCoreDistributionError(
            f"{DISTRIBUTION_NAME} metadata is missing; install {DISTRIBUTION_NAME}=={PACKAGE_VERSION}"
        ) from exc
    if distribution.version != PACKAGE_VERSION:
        raise NativeCoreDistributionError(
            f"incompatible {DISTRIBUTION_NAME} version {distribution.version!r}; "
            f"expected exactly {PACKAGE_VERSION!r}"
        )
    return distribution


def _validate_language_version() -> None:
    try:
        version = importlib_metadata.version(LANGUAGE_DISTRIBUTION_NAME)
    except importlib_metadata.PackageNotFoundError:
        # The native distribution is independently inspectable. If the
        # language is present, however, compatibility is exact and mandatory.
        return
    if version != LANGUAGE_VERSION:
        raise NativeCoreDistributionError(
            f"incompatible {LANGUAGE_DISTRIBUTION_NAME} version {version!r}; "
            f"{DISTRIBUTION_NAME}=={PACKAGE_VERSION} requires exactly {LANGUAGE_VERSION!r}"
        )


def _native_module() -> ModuleType:
    try:
        import _aether_core
    except ImportError as exc:
        raise NativeCoreDistributionError(
            f"{DISTRIBUTION_NAME} is installed without its _aether_core binding"
        ) from exc
    expected = {
        "__version__": PACKAGE_VERSION,
        "NATIVE_PRODUCT_VERSION": NATIVE_PRODUCT_VERSION,
        "COMPILER_CORE_API_VERSION": COMPILER_CORE_API_VERSION,
        "PROTOCOL_VERSION": PROTOCOL_VERSION,
        "INPUT_SCHEMA_VERSIONS": INPUT_SCHEMA_VERSIONS,
        "OUTPUT_SCHEMA_VERSIONS": OUTPUT_SCHEMA_VERSIONS,
        "QUALIFICATION_ONLY": False,
    }
    mismatches: dict[str, tuple[object, object]] = {}
    for name, value in expected.items():
        if name in {"INPUT_SCHEMA_VERSIONS", "OUTPUT_SCHEMA_VERSIONS"}:
            actual_sequence = tuple(getattr(_aether_core, name, ()))
            if actual_sequence != value:
                mismatches[name] = (actual_sequence, value)
            continue
        actual = getattr(_aether_core, name, None)
        if actual != value:
            mismatches[name] = (actual, value)
    if mismatches:
        raise NativeCoreDistributionError(
            f"_aether_core version contract mismatch: {mismatches!r}"
        )
    return _aether_core


def _manifest() -> tuple[dict[str, object], Path]:
    resource = files(__package__).joinpath("_native", "native-core-manifest.json")
    path = Path(os.fspath(resource)).resolve()
    try:
        raw = path.read_bytes()
    except FileNotFoundError as exc:
        raise NativeCoreDistributionError(
            "native compiler-core metadata is missing from the installed wheel"
        ) from exc
    if len(raw) > 64 * 1024:
        raise NativeCoreDistributionError("native compiler-core metadata exceeds 65536 bytes")
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise NativeCoreDistributionError("native compiler-core metadata is corrupted") from exc
    expected = {
        "manifest_schema_version": 1,
        "distribution": DISTRIBUTION_NAME,
        "package_version": PACKAGE_VERSION,
        "compiler_core_api_version": COMPILER_CORE_API_VERSION,
        "native_product_version": NATIVE_PRODUCT_VERSION,
        "product": "aether-ssa-shadow",
        "protocol_version": PROTOCOL_VERSION,
        "input_schema_versions": list(INPUT_SCHEMA_VERSIONS),
        "language_package_version": LANGUAGE_VERSION,
        "output_schema_versions": list(OUTPUT_SCHEMA_VERSIONS),
        "wheel_record_integrity_required": True,
    }
    required = set(expected) | {"binary", "build_identity", "target"}
    if (
        not isinstance(value, dict)
        or set(value) != required
        or any(value.get(name) != expected_value for name, expected_value in expected.items())
        or not isinstance(value.get("binary"), str)
        or value["binary"] not in {"aether-ssa-shadow", "aether-ssa-shadow.exe"}
        or not isinstance(value.get("build_identity"), str)
        or not value["build_identity"]
        or not isinstance(value.get("target"), str)
        or not value["target"]
    ):
        raise NativeCoreDistributionError("native compiler-core metadata is incompatible")
    native = _native_module()
    if getattr(native, "BUILD_IDENTITY", None) != value["build_identity"]:
        raise NativeCoreDistributionError(
            "_aether_core and companion do not have the same build identity"
        )
    return value, path


def _verify_record(
    distribution: importlib_metadata.Distribution,
    path: Path,
    relative: str,
) -> None:
    entries = {
        entry.as_posix(): entry
        for entry in (distribution.files or ())
    }
    try:
        entry = entries[relative]
    except KeyError as exc:
        raise NativeCoreDistributionError(
            f"native wheel RECORD does not contain {relative}"
        ) from exc
    recorded = entry.hash
    if recorded is None or recorded.mode != "sha256":
        raise NativeCoreDistributionError(
            f"native wheel RECORD has no sha256 for {relative}"
        )
    actual = urlsafe_b64encode(sha256(path.read_bytes()).digest()).rstrip(b"=").decode("ascii")
    if actual != recorded.value:
        raise NativeCoreDistributionError(
            f"native wheel RECORD checksum mismatch for {relative}"
        )


def binding() -> ModuleType:
    """Return the validated private PyO3 binding module."""
    distribution = _distribution()
    _validate_language_version()
    native = _native_module()
    manifest, manifest_path = _manifest()
    _verify_record(distribution, manifest_path, _MANIFEST_RELATIVE)
    if getattr(native, "BUILD_IDENTITY") != manifest["build_identity"]:
        raise NativeCoreDistributionError("native build identities diverge")
    return native


def companion_path() -> Path:
    """Return the validated absolute path of the installed protocol-v1 companion."""
    distribution = _distribution()
    _validate_language_version()
    manifest, manifest_path = _manifest()
    _verify_record(distribution, manifest_path, _MANIFEST_RELATIVE)
    binary_name = str(manifest["binary"])
    binary = manifest_path.with_name(binary_name).resolve()
    expected_name = "aether-ssa-shadow.exe" if os.name == "nt" else "aether-ssa-shadow"
    if binary.name != expected_name:
        raise NativeCoreDistributionError(
            f"native compiler-core wheel contains {binary.name!r}; expected {expected_name!r}"
        )
    if not binary.is_file():
        raise NativeCoreDistributionError("native compiler-core companion is missing")
    binary_relative = f"aether_compiler_core/_native/{binary_name}"
    _verify_record(distribution, binary, binary_relative)
    if os.name != "nt" and not os.access(binary, os.X_OK):
        raise NativeCoreDistributionError("native compiler-core companion is not executable")
    return binary


def version_metadata() -> dict[str, object]:
    """Return a copy of the validated machine-readable native build contract."""
    _distribution()
    _validate_language_version()
    manifest, _ = _manifest()
    return dict(manifest)


__version__ = PACKAGE_VERSION

_BINDING_EXPORTS = {
    "CompilerCore",
    "CompilationSession",
    "AetherCoreError",
    "AetherCompilerError",
    "AetherBindingError",
    "AetherInternalCompilerError",
}


def __getattr__(name: str) -> object:
    if name not in _BINDING_EXPORTS:
        raise AttributeError(name)
    value = getattr(binding(), name)
    globals()[name] = value
    return value

__all__ = [
    "AetherBindingError",
    "AetherCompilerError",
    "AetherCoreError",
    "AetherInternalCompilerError",
    "CompilationSession",
    "CompilerCore",
    "NativeCoreDistributionError",
    "binding",
    "companion_path",
    "version_metadata",
]
