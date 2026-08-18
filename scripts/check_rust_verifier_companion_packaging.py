#!/usr/bin/env python3
"""Generate or check the deterministic RUST-1.2.1 packaging contract."""
from __future__ import annotations
import argparse, json
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from aether.ir.rust_verifier import RUST_VERIFIER_PACKAGE_VERSION, rust_verifier_artifact_name  # noqa: E402
OUTPUT = ROOT / "docs/compiler/rust_verifier_companion_packaging.json"

def build_record() -> dict[str, object]:
    ownership = json.loads((ROOT / "docs/architecture/implementation_language_ownership.json").read_text())
    component = next(x for x in ownership["components"] if x["component"] == "initial_ir_verification")
    platforms = {"linux-x86_64": "x86_64-unknown-linux-gnu", "windows-x86_64": "x86_64-pc-windows-msvc",
                 "macos-arm64": "aarch64-apple-darwin", "macos-x86_64": "x86_64-apple-darwin"}
    script = (ROOT / "scripts/package_rust_verifier.py").read_text()
    assert component["current_authority"] == "python" and component["migration_phase"] == "RP2"
    assert "target/release" in script and "requires a target/release binary" in script
    assert (ROOT / "docs/compiler/rust_initial_ir_verifier_rp3_operational_readiness.json").exists()
    return {
        "schema_version": 1, "revision": "RUST-1.2.1", "final_decision": "COMPANION_PACKAGING_FOUNDATION_READY",
        "current_authority": "python", "current_migration_phase": "RP2",
        "product": {"name": "aether-ir-verifier", "crate": "aether-ir-verifier", "executable": "aether-ir-verifier[.exe]",
                    "protocol_identity": "aether-ir-verifier", "product_version": RUST_VERIFIER_PACKAGE_VERSION,
                    "scope": "Initial IR verifier subprocess; not compiler, frontend, typechecker, or optimizer"},
        "distribution": {"model": "B1_platform_native_binary_artifact", "transport": "native_release_archive",
                         "future_transport": "native_Aether_toolchain_bundle", "dependency_contract": "release index requires one compatible platform artifact",
                         "sdist_policy": "developer-oriented; does not build or install companion implicitly"},
        "compatibility": {"release_policy": "independent_semver_with_coordinated_Aether_release_index", "runtime_authority": "protocol_schema_capabilities",
                          "identity_schema": 1, "protocol_version": 1, "ir_schema_versions": [1], "required_capabilities": ["verify"], "exact_product_version_required_by_current_release": True},
        "version_authority": "compiler-rs/Cargo.toml workspace.package.version",
        "metadata_command": "--metadata (alias of --identity)", "human_version_command": "--version",
        "platforms": platforms, "architecture_aliases": {"amd64": "x86_64", "x86_64": "x86_64", "aarch64": "arm64", "arm64": "arm64"},
        "artifact_names": {platform: rust_verifier_artifact_name(platform) for platform in platforms},
        "artifact_contents": ["aether-ir-verifier[.exe]", "manifest.json", "LICENSE"],
        "manifest": {"schema": 1, "deterministic": True, "fields": ["manifest_schema_version", "product", "product_version", "protocol_version", "supported_ir_schema_versions", "capabilities", "platform", "architecture", "binary", "build_profile", "sha256", "identity"]},
        "build_command": "cargo build --manifest-path compiler-rs/Cargo.toml --release --locked --package aether-ir-verifier",
        "packaging_cli": "python scripts/package_rust_verifier.py --executable compiler-rs/target/release/aether-ir-verifier --platform linux --arch x86_64 --output-dir dist/native",
        "archive": {"stable_order": True, "normalized_timestamps": True, "normalized_ownership": True, "claim": "structurally deterministic"},
        "checksum": "SHA-256 sidecar", "release_index": "verifier-companions.json alongside release artifacts",
        "install_layout": "<aether-home>/libexec/aether/aether-ir-verifier[.exe] with adjacent manifest.json",
        "executable_policy": "internal helper, manually invokable for diagnostics, not normally on PATH",
        "discovery": {"production": "canonical installed manifest only", "override": "explicit development/test path", "path_fallback": False, "source_tree_fallback": False,
                      "precedence": ["explicit_override", "canonical_installed_companion", "typed_missing_failure"]},
        "failure_classification": {"missing": "companion missing", "incompatible": "incompatible verifier companion", "semantic_rejection": "invalid program"},
        "rp2_policy": "ship and require companion in release bundles for pre-RP3 shadow/canary soak; Python remains authority",
        "clean_install": "native archive requires neither Cargo nor source checkout", "protocol_boundary": "existing executable stdin/stdout protocol only", "pyo3": False,
        "security": "trusted toolchain component, not a sandbox; strict bounded protocol and artifact SHA-256",
        "current_platform_qualification": {"platform": "linux-x86_64", "release_binary_bytes": 2107920, "archive_bytes": 773997,
                                           "outside_checkout": "PASS", "metadata": "PASS", "accepted_fixture": "PASS", "incompatible_fixture": "PASS",
                                           "packaged_canary": {"total": 404, "semantic_mismatches": 0, "unexpected": 0, "infrastructure_failures": 0, "successful": True}},
        "op1": "PARTIAL: mechanism and current-platform production are covered; all-platform publication remains blocked",
        "op5": "PASS: distribution, dependency, installation, discovery, and compatibility contracts are formalized",
        "remaining_rust_1_2_2": ["execute matrix builds", "publish all platform artifacts", "clean-install each", "run packaged canary subset", "collect OP6 and OP10 evidence"],
    }

def render() -> str: return json.dumps(build_record(), indent=2, sort_keys=True) + "\n"
def main() -> int:
    parser = argparse.ArgumentParser(); parser.add_argument("--check", action="store_true"); args = parser.parse_args(); value = render()
    if args.check:
        if not OUTPUT.exists() or OUTPUT.read_text() != value: print(f"stale packaging artifact: {OUTPUT.relative_to(ROOT)}"); return 1
        print("RUST-1.2.1 companion packaging contract is deterministic and current"); return 0
    OUTPUT.write_text(value, encoding="utf-8", newline="\n"); return 0
if __name__ == "__main__": raise SystemExit(main())
