"""Build hooks for Aether's generated package metadata."""

from __future__ import annotations

from pathlib import Path
import tomllib

from setuptools import setup
from setuptools.command.build_py import build_py as _build_py


class build_py(_build_py):
    """Embed Rust companion metadata while Cargo.toml is available."""

    def run(self) -> None:
        super().run()
        cargo_path = Path(__file__).parent / "compiler-rs" / "Cargo.toml"
        with cargo_path.open("rb") as stream:
            version = tomllib.load(stream)["workspace"]["package"]["version"]
        if not isinstance(version, str) or not version:
            raise RuntimeError("invalid Rust verifier Cargo product version")

        destination = Path(self.build_lib) / "aether" / "ir" / "_rust_verifier_metadata.py"
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(
            "# Generated from compiler-rs/Cargo.toml by setup.py; do not edit.\n"
            f"RUST_VERIFIER_PACKAGE_VERSION = {version!r}\n",
            encoding="utf-8",
        )


setup(cmdclass={"build_py": build_py})
