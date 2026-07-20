from __future__ import annotations

# This PEP 440 value is the only hand-maintained Aether release identity.
# Setuptools can read the literal without importing the package in an isolated
# build. User-facing tools derive the hyphenated language spelling below.
PACKAGE_VERSION = "1.0.0rc3"


def _language_version(package_version: str) -> str:
    marker = "rc"
    if marker not in package_version:
        return package_version
    release, candidate = package_version.rsplit(marker, 1)
    if not release or not candidate.isdigit():
        raise RuntimeError(f"Invalid Aether PEP 440 version: {package_version!r}")
    return f"{release}-rc.{candidate}"


LANGUAGE_VERSION = _language_version(PACKAGE_VERSION)
RELEASE_TAG = f"v{LANGUAGE_VERSION}"
__version__ = PACKAGE_VERSION
