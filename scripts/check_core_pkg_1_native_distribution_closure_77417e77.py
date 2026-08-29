#!/usr/bin/env python3
"""Fail-closed checker for the official CORE-PKG-1 closure at 77417e77."""

from __future__ import annotations

import argparse
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import re
import shutil
import tempfile


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EVIDENCE = ROOT / "docs/compiler/core_pkg_1_native_compiler_core_distribution_closure_77417e77.json"
DEFAULT_REPORT = ROOT / "docs/compiler/CORE_PKG_1_NATIVE_COMPILER_CORE_DISTRIBUTION_CLOSURE_77417E77.md"

RUN_ID = 33216160463
REVISION = "77417e7751482fc5a88a7d4207e99d67692da043"
WORKFLOW_NAME = "core-native-packaging"
QUALIFIED = "CORE_NATIVE_COMPILER_CORE_DISTRIBUTION_QUALIFIED"
BLOCKED = "CORE_NATIVE_COMPILER_CORE_DISTRIBUTION_BLOCKED"
HISTORICAL_RUN_ID = 33188797944
HISTORICAL_REVISION = "b219d60d1afe38bea560495536401e9997a4ea5a"
SHA256 = re.compile(r"[0-9a-f]{64}")

EXPECTED_JOBS = {
    "package-contract": 99000115209,
    "companion-installed-rollback": 99000114903,
    "source-development-install": 99000115138,
    "failure-campaign": 99000115208,
    "binding-installed-smoke": 99000115397,
    "aggregate-fail-closed": 99001462219,
    "clean-install-platform (linux-x86_64, ubuntu-latest)": 99000115347,
    "clean-install-platform (windows-x86_64, windows-latest)": 99000115116,
    "clean-install-platform (macos-x86_64, macos-15-intel)": 99000115159,
    "clean-install-platform (macos-arm64, macos-15)": 99000115358,
    "python-compatibility (3.11)": 99000115194,
    "python-compatibility (3.12)": 99000115225,
    "python-compatibility (3.13)": 99000115384,
    "python-compatibility (3.14)": 99000115341,
}

# artifact ID, GitHub/archive digest, source job, extracted file hashes.
EXPECTED_ARTIFACTS = {
    "core-pkg-1-aggregate": (
        9703572314,
        "a92971fc62bc74b24b840059d64611dd915dbf77406aa150afe495c3ef4d12c6",
        "aggregate-fail-closed",
        {"aggregate.json": "d59339b4705091df3ffbce72fc2c99b390a44433d449525ed7bb0fb0ef07a0f6"},
    ),
    "core-pkg-1-platform-macos-x86_64": (
        9703566500,
        "0f513c1132df98b1fbb587be2774fb88ad61d7d50df4807d9c28ddc99ad0143d",
        "clean-install-platform (macos-x86_64, macos-15-intel)",
        {"platform-macos-x86_64.json": "80c52ec595b570c9750c66eea964b0731d25dc7b14e642e66349191120d033f9"},
    ),
    "core-pkg-1-contract": (
        9703547555,
        "df70a0599185745152ea821be40c1fd7b7c971fead6dc1a9c7bd7940f8fbfb97",
        "package-contract",
        {"contract.json": "442b7ed1a53d7b27681d4e93ae2c8355a161d855b924098d1d9e1a693937542d"},
    ),
    "core-pkg-1-platform-windows-x86_64": (
        9703523966,
        "23c8bb544ac360803cceba939df6ae34f22a0278723a5c2739d2c1c2c130f042",
        "clean-install-platform (windows-x86_64, windows-latest)",
        {"platform-windows-x86_64.json": "8c54d6c25c94aacb76d11f837f42529ae699d89bab1938afb982b83a290f0e9d"},
    ),
    "core-pkg-1-platform-macos-arm64": (
        9703484287,
        "49e4aa9fd5f4bd9a2f1c6118cf9095a422d7e750e12356d7d06e806211484270",
        "clean-install-platform (macos-arm64, macos-15)",
        {"platform-macos-arm64.json": "3ef8fbce54a1ed1c411cefec4b239fa7e15938652202decdc718de72559d40aa"},
    ),
    "core-pkg-1-python-3.14": (
        9703471366,
        "926109369126414200567861f458c6e472a0e9a77576d80e4dcc2a97b8d70014",
        "python-compatibility (3.14)",
        {"python-3.14.json": "2c0d614813a6cbcaa5c21a22a6a18934b7b1c34e66d1316c35a4f2fe8ae04dd1"},
    ),
    "core-pkg-1-python-3.13": (
        9703470254,
        "af7e929ef0c1a086a7b610fddc191026a5b5e6aff1e0f4e6504515e2025b8c6e",
        "python-compatibility (3.13)",
        {"python-3.13.json": "c13c3bfe8f3de4518ae3dc5f44a48fd6fa2b159472160fe91b7cc481f1308a66"},
    ),
    "core-pkg-1-binding": (
        9703468423,
        "160e9447fe60cd29e86b48a9c57d405e7ec18846c373ce775f6c5610195e38ad",
        "binding-installed-smoke",
        {
            "binding.json": "e352844253d09c738f95dab76e972dd60810f909e9e79c58e0c47606eeea71eb",
            "core-1-0a-production-check.json": "02321fefd39ceeb58e430245195aa7e2e3dc8b30d411f2849495d48b1b981fb7",
            "core-1-0a-production.json": "aafedcc204215333e288d7d5cb1765eaebdbc82ef996ca0ac616f26953f22832",
        },
    ),
    "core-pkg-1-python-3.11": (
        9703467588,
        "be4494f2ab890cad510fee121016ba1e6ff8327c359b9f9bd8eba0ebd9e0385e",
        "python-compatibility (3.11)",
        {"python-3.11.json": "d9257b260db4de34e497b35b8216b26cca1587213617eb85591ddf6af5cb4eac"},
    ),
    "core-pkg-1-python-3.12": (
        9703465913,
        "56fa5890feed832a5351eac6d70e48158968b55178edae8d223c6bb4c1481063",
        "python-compatibility (3.12)",
        {"python-3.12.json": "78755ca736ead944432d761723cf270f7dc037447fb77406be797b83cc3179fb"},
    ),
    "core-pkg-1-source": (
        9703458937,
        "55f743fdcea0ad297479350d660c2d1634344abcf1bc0af1775ca836802fbeb3",
        "source-development-install",
        {"source.json": "d390f126c9ce4b155beb4803c0381a9dba7ea77a914f85ee813245553aeb9708"},
    ),
    "core-pkg-1-companion": (
        9703458761,
        "1169c9009bd814949cebe4fbbcea102f600f12386f3cafcd46ece9610e73c767",
        "companion-installed-rollback",
        {"companion.json": "094877b45e6ccea31a79657217d49e01cd753cc620082f1a640df6a4a1d5cb0f"},
    ),
    "core-pkg-1-platform-linux-x86_64": (
        9703456798,
        "5c246fbfa1cca2e1626c85f08817eea0115a4d391cb7c1079ca3aa4ace32fb8f",
        "clean-install-platform (linux-x86_64, ubuntu-latest)",
        {"platform-linux-x86_64.json": "2bfc178e403f9f365f1d0a5394f8dab195e48ec5299abe7a8e5434850497eec2"},
    ),
    "core-pkg-1-failures": (
        9703424671,
        "7e4020f4256d07299e9b09ddcb20a6abfd4f1e2a4bcdb2fe93cb779e461ffd8e",
        "failure-campaign",
        {"failures.json": "4aafa28a804199e60ade57c99b9e578f908c68ca7584d68fc4c2f495607c7911"},
    ),
}

EXPECTED_ARTIFACT_SIZES = {
    "core-pkg-1-aggregate": 1234,
    "core-pkg-1-platform-macos-x86_64": 1569,
    "core-pkg-1-contract": 220,
    "core-pkg-1-platform-windows-x86_64": 1587,
    "core-pkg-1-platform-macos-arm64": 1567,
    "core-pkg-1-python-3.14": 1487,
    "core-pkg-1-python-3.13": 1490,
    "core-pkg-1-binding": 2741,
    "core-pkg-1-python-3.11": 1489,
    "core-pkg-1-python-3.12": 1488,
    "core-pkg-1-source": 223,
    "core-pkg-1-companion": 227,
    "core-pkg-1-platform-linux-x86_64": 1499,
    "core-pkg-1-failures": 226,
}

EXPECTED_PLATFORMS = {
    "linux-x86_64": (
        "3.13.15",
        "aether_compiler_core-1.0.0rc4-cp313-cp313-linux_x86_64.whl",
        "cp313-cp313-linux_x86_64",
        "a7feb938478448bc8c3aadd163911021b2b8721aca28ba2e4342593efe34808b",
        "e90ce72964cafd8851aee940b97736fa74e774d068af03df7502e3da199c5ea0",
        "x86_64-unknown-linux-gnu",
    ),
    "windows-x86_64": (
        "3.13.15",
        "aether_compiler_core-1.0.0rc4-cp313-cp313-win_amd64.whl",
        "cp313-cp313-win_amd64",
        "1fc31019293bdb743b68a6873a36e99b48bb50ba9cc14b0487c5a43b1a332fb4",
        "832e5cfb9a67faac5374b0f73f47d64c268226be505226ac774d7f195ab552b5",
        "x86_64-pc-windows-msvc",
    ),
    "macos-x86_64": (
        "3.13.15",
        "aether_compiler_core-1.0.0rc4-cp313-cp313-macosx_10_12_x86_64.whl",
        "cp313-cp313-macosx_10_12_x86_64",
        "44ec45f349ea231020ab40a9fe217d3b92404eddd1659fc611d083bfc8d52868",
        "c038bd095951e983be498fcf8f3781af35598dc859a43dfe1f8d1da9ce15490b",
        "x86_64-apple-darwin",
    ),
    "macos-arm64": (
        "3.13.14",
        "aether_compiler_core-1.0.0rc4-cp313-cp313-macosx_11_0_arm64.whl",
        "cp313-cp313-macosx_11_0_arm64",
        "0e72293c3d0490cb019af69cc5f3461df39b289a22822844a0be297e47b93556",
        "79d0c090b01790ee718c702115635caa41d20f5e94990cfad34b04e4066a1863",
        "aarch64-apple-darwin",
    ),
}

EXPECTED_PYTHONS = {
    "3.11": ("3.11.16", "aether_compiler_core-1.0.0rc4-cp311-cp311-linux_x86_64.whl", "06e08e166c14da86071a5ea3324a1b8196790158319592036c26636ef2910de2", "db73125af67a9225f9b11e3fa15595d26bfcf2d937f50cdf6025cbd01c2cbc96"),
    "3.12": ("3.12.14", "aether_compiler_core-1.0.0rc4-cp312-cp312-linux_x86_64.whl", "20384d5c0d42ba3e7039b9bf50c622c1ef0592b24e990fb4d497dc790dc0e8ba", "c65ff4a4c09d2850d3db92c979b6dacc9295e5d5f5082a8377f98e1b6cc683aa"),
    "3.13": ("3.13.15", "aether_compiler_core-1.0.0rc4-cp313-cp313-linux_x86_64.whl", "deb3f9921c15af6bcd5b50a212381050a75cef2c0da956575a5772a7d07aa56f", "b3e5cb921480493418e35c22140fbb54316f9c4d003e5198b315281291b86789"),
    "3.14": ("3.14.7", "aether_compiler_core-1.0.0rc4-cp314-cp314-linux_x86_64.whl", "09a0424ed8d1fba2225f473eae1779220939d28bc8d687d5a1174ec75404ed50", "e14ad2f93f3b4f2941b201ce9b5c2f58cb1cefcc4a608475466d7eb3f49e70bb"),
}

EXPECTED_SOURCE_SNAPSHOT = {
    ".github/workflows/core-native-packaging.yml": "583a18f7327cac20ceac58ea706ed610c754faa0cee5076a7b071fb7545cffad",
    "compiler-rs/distributions/aether-compiler-core/pyproject.toml": "93a09f7e5527836560486eb94d2cae3e96858b6d7cf09e6622860e12770e72c5",
    "compiler-rs/distributions/aether-compiler-core/python/aether_compiler_core/__init__.py": "6d863f858387d05c47c12875825664fc2ef84f7b82a6f1a3177b7b7de6fda06a",
    "docs/compiler/CORE_PKG_1_NATIVE_COMPILER_CORE_DISTRIBUTION.md": "cf9557da2c82643c4f17ca83ab54ab95ea92e04a72a317c28c0774feca7356bb",
    "docs/compiler/core_pkg_1_native_compiler_core_distribution.json": "86272d4972bdd1dd6f39c282531e7a76b23f7129b408049caf2afe5cbd1a6b98",
    "pyproject.toml": "d6b99f5176953ebed6b4d3da1c44767b4cdca22c299d6f9df4f56084fe673977",
    "scripts/check_core_pkg_1_native_distribution.py": "156b7a29f37ed14b9687ebeef85973a7b13df41fe4b7aa0edc7a00286a49c0b8",
    "src/aether/ssa/shadow.py": "6c692e6cef00b3295a0b665a947ae689ef602f91d7654455b2bd667e2f9fe5fa",
}

EXPECTED_FAILURE_CASES = {
    "missing native distribution metadata",
    "native distribution version mismatch",
    "language/native version mismatch",
    "missing, malformed, or incompatible native manifest",
    "source checkout package shadowing",
    "missing binding",
    "shadow binding version mismatch",
    "wheel RECORD checksum mismatch",
    "missing companion",
    "non-executable companion on POSIX",
    "missing native wheel candidate",
    "ambiguous native wheel candidates",
    "incompatible CPython wheel",
}

EXPECTED_ELIGIBILITY = {
    "aggregate_qualified_and_reproducible",
    "all_artifact_archives_match_github_digests",
    "all_extracted_files_hashed",
    "all_required_artifacts_present",
    "all_required_jobs_success",
    "binding_smoke_qualified",
    "companion_rollback_qualified",
    "compiler_core_identity_consistent",
    "cpython_3_11_through_3_14_qualified",
    "exact_revision_gate",
    "failure_campaign_qualified",
    "four_platform_clean_consumers_qualified",
    "historical_failed_run_preserved",
    "ide_cli_scope_recorded",
    "known_warnings_classified",
    "package_contract_qualified",
    "production_companion_default_preserved",
    "run_conclusion_success",
    "source_development_install_qualified",
}


def _digest(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _load(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("closure evidence must be a JSON object")
    return value


def _all_true(value: object) -> bool:
    return isinstance(value, dict) and bool(value) and all(item is True for item in value.values())


def _check_eligibility(evidence: dict[str, object]) -> bool:
    value = evidence.get("eligibility_checks")
    return isinstance(value, dict) and set(value) == EXPECTED_ELIGIBILITY and _all_true(value)


def _check_run(evidence: dict[str, object]) -> bool:
    run = evidence.get("official_run")
    return isinstance(run, dict) and run == {
        "artifact_count": 14,
        "branch": "main",
        "conclusion": "success",
        "created_at": "2026-08-28T22:16:52Z",
        "event": "workflow_dispatch",
        "head_sha": REVISION,
        "html_url": f"https://github.com/blas1306/Aether/actions/runs/{RUN_ID}",
        "run_attempt": 1,
        "run_id": RUN_ID,
        "run_started_at": "2026-08-28T22:16:52Z",
        "short_sha": "77417e77",
        "status": "completed",
        "updated_at": "2026-08-28T22:23:27Z",
        "workflow_name": WORKFLOW_NAME,
        "workflow_path": ".github/workflows/core-native-packaging.yml",
    }


def _check_jobs(evidence: dict[str, object]) -> bool:
    rows = evidence.get("run_jobs")
    if not isinstance(rows, list) or len(rows) != len(EXPECTED_JOBS):
        return False
    actual: dict[str, tuple[object, object, object, object]] = {}
    for row in rows:
        if not isinstance(row, dict):
            return False
        actual[str(row.get("name"))] = (
            row.get("id"), row.get("status"), row.get("conclusion"), row.get("head_sha")
        )
    return actual == {
        name: (job_id, "completed", "success", REVISION)
        for name, job_id in EXPECTED_JOBS.items()
    }


def _check_artifacts(evidence: dict[str, object]) -> bool:
    rows = evidence.get("artifact_manifest")
    if not isinstance(rows, list) or len(rows) != len(EXPECTED_ARTIFACTS):
        return False
    actual = {str(row.get("artifact_name")): row for row in rows if isinstance(row, dict)}
    if set(actual) != set(EXPECTED_ARTIFACTS):
        return False
    for name, (artifact_id, digest, source_job, files) in EXPECTED_ARTIFACTS.items():
        row = actual[name]
        extracted = row.get("extracted_files")
        if not isinstance(extracted, list):
            return False
        actual_files = {
            str(item.get("filename")): item.get("sha256")
            for item in extracted
            if isinstance(item, dict)
        }
        if not (
            row.get("artifact_id") == artifact_id
            and row.get("archive_filename") == f"{name}.zip"
            and row.get("archive_size_bytes") == EXPECTED_ARTIFACT_SIZES[name]
            and row.get("github_digest_sha256") == digest
            and row.get("archive_sha256") == digest
            and row.get("digest_verified") is True
            and row.get("exact_revision") == REVISION
            and row.get("source_job") == source_job
            and row.get("source_job_id") == EXPECTED_JOBS[source_job]
            and row.get("validation_result") == "PASS"
            and actual_files == files
            and SHA256.fullmatch(digest)
            and all(SHA256.fullmatch(str(value)) for value in actual_files.values())
        ):
            return False
    return True


def _check_aggregate(evidence: dict[str, object]) -> bool:
    row = evidence.get("official_aggregate_validation")
    return isinstance(row, dict) and row == {
        "aggregate_artifact_id": 9703572314,
        "aggregate_decision": QUALIFIED,
        "aggregate_errors": [],
        "aggregate_file_sha256": "d59339b4705091df3ffbce72fc2c99b390a44433d449525ed7bb0fb0ef07a0f6",
        "checker": "scripts/check_core_pkg_1_native_distribution.py",
        "checker_sha256": "156b7a29f37ed14b9687ebeef85973a7b13df41fe4b7aa0edc7a00286a49c0b8",
        "comparison": "byte-identical",
        "exact_revision": REVISION,
        "input_artifact_count": 13,
        "official_and_recomputed_byte_identical": True,
        "recomputed_decision": QUALIFIED,
        "recomputed_file_sha256": "d59339b4705091df3ffbce72fc2c99b390a44433d449525ed7bb0fb0ef07a0f6",
        "run_id": RUN_ID,
        "validation_result": "PASS",
    }


def _check_package_contract(evidence: dict[str, object]) -> bool:
    row = evidence.get("package_contract")
    if not isinstance(row, dict):
        return False
    historical = row.get("historical_qualification_distribution")
    contents = row.get("native_contents")
    tests = row.get("contract_job_tests")
    return bool(
        row.get("contract_artifact_status") == "PASS"
        and row.get("language_distribution") == "aether-language"
        and row.get("language_version") == "1.0.0rc4"
        and row.get("native_distribution") == "aether-compiler-core"
        and row.get("native_version") == "1.0.0rc4"
        and row.get("native_dependency") == "aether-compiler-core==1.0.0rc4"
        and row.get("native_dependency_exact") is True
        and contents == {
            "installed_companion": True,
            "native_version_manifest": True,
            "pyo3_binding": True,
            "stable_python_wrapper": "aether_compiler_core",
        }
        and historical == {
            "name": "aether-core-qualification",
            "qualification_only": True,
            "separate_from_productive_distribution": True,
            "version": "0.1.0",
        }
        and tests == {"passed": 19, "status": "PASS"}
        and row.get("validation_result") == "PASS"
    )


def _check_identity(evidence: dict[str, object]) -> bool:
    row = evidence.get("compiler_core_identity")
    return isinstance(row, dict) and bool(
        row.get("package_version") == "1.0.0rc4"
        and row.get("native_product_version") == "0.1.0"
        and row.get("compiler_core_api_version") == 1
        and row.get("protocol_version") == 1
        and row.get("input_schema_versions") == [1]
        and row.get("output_schema_versions") == [2]
        and row.get("build_identity") == REVISION
        and row.get("binding_build_identity") == REVISION
        and row.get("manifest_build_identity") == REVISION
        and row.get("companion_build_identity") == REVISION
        and row.get("single_core_implementation") == "aether-verifier::CompilerCore"
        and row.get("binding_and_companion_same_contract") is True
        and "do not claim universal semantic identity" in str(row.get("scope"))
        and row.get("validation_result") == "PASS"
    )


def _check_platforms(evidence: dict[str, object]) -> bool:
    rows = evidence.get("platform_matrix")
    if not isinstance(rows, list) or len(rows) != 4:
        return False
    actual = {str(row.get("platform")): row for row in rows if isinstance(row, dict)}
    if set(actual) != set(EXPECTED_PLATFORMS):
        return False
    for platform, expected in EXPECTED_PLATFORMS.items():
        python, wheel, tag, wheel_hash, language_hash, target = expected
        row = actual[platform]
        if not (
            row.get("python_version") == python
            and row.get("native_wheel") == wheel
            and row.get("native_wheel_tag") == tag
            and row.get("native_wheel_sha256") == wheel_hash
            and row.get("language_wheel") == "aether_language-1.0.0rc4-py3-none-any.whl"
            and row.get("language_wheel_sha256") == language_hash
            and row.get("target") == target
            and row.get("dependency_resolution") == "pip_resolved_from_language_wheel"
            and row.get("binding_import") == "PASS"
            and row.get("stable_wrapper") == "PASS"
            and row.get("companion_discovery") == "installed package"
            and row.get("companion_execution_and_rollback") == "PASS"
            and row.get("consumer_without_cargo_or_rustc") is True
            and row.get("checkout_not_used") is True
            and row.get("production_transport") == "companion"
            and row.get("version_and_build_identity") == "PASS"
            and row.get("status") == "PASS"
        ):
            return False
    return True


def _check_pythons(evidence: dict[str, object]) -> bool:
    rows = evidence.get("python_matrix")
    if not isinstance(rows, list) or len(rows) != 4:
        return False
    actual = {str(row.get("minor")): row for row in rows if isinstance(row, dict)}
    if set(actual) != set(EXPECTED_PYTHONS):
        return False
    for minor, (python, wheel, wheel_hash, language_hash) in EXPECTED_PYTHONS.items():
        row = actual[minor]
        if not (
            row.get("platform") == "linux-x86_64"
            and row.get("python_version") == python
            and row.get("native_wheel") == wheel
            and row.get("native_wheel_sha256") == wheel_hash
            and row.get("language_wheel_sha256") == language_hash
            and row.get("binding_import") == "PASS"
            and row.get("stable_wrapper") == "PASS"
            and row.get("companion_and_smoke") == "PASS"
            and row.get("version_contract") == "PASS"
            and row.get("consumer_without_cargo_or_rustc") is True
            and row.get("status") == "PASS"
        ):
            return False
    return True


def _check_binding(evidence: dict[str, object]) -> bool:
    row = evidence.get("binding_installed_smoke")
    return isinstance(row, dict) and bool(
        row.get("status") == "PASS"
        and row.get("compatibility_import") == "_aether_core"
        and row.get("private_import") == "aether_compiler_core._aether_core"
        and row.get("qualification_only") is False
        and row.get("compiler_core_constructed") is True
        and row.get("protocol_version") == 1
        and row.get("production_regression_gate_count") == 9
        and row.get("shared_core_guard_count") == 4
        and row.get("required_job_steps") == {
            "Project checked production guard into CORE-PKG-1 evidence": "success",
            "Replay CORE-1.0A regression lanes without promoting in-process": "success",
            "Validate exact CORE-1.0A production evidence": "success",
        }
        and row.get("exact_core_1_0a_production_evidence") == "PASS"
        and row.get("upstream_decision") == "CORE_IN_PROCESS_PRODUCTION_GUARD_QUALIFIED"
        and row.get("production_guard_projected") is True
    )


def _check_companion(evidence: dict[str, object]) -> bool:
    row = evidence.get("companion_installed_rollback")
    return isinstance(row, dict) and bool(
        row.get("dedicated_artifact_detail_level") == "marker-only"
        and row.get("dedicated_artifact_status") == "PASS"
        and row.get("detailed_protocol_and_rollback_source") == "all four clean-consumer artifacts"
        and row.get("discovered_from_installed_package") is True
        and row.get("repository_relative_lookup") is False
        and row.get("executable_exists") is True
        and row.get("startup_without_request_fails") is True
        and row.get("protocol_v1") is True
        and row.get("failure_recovery") is True
        and row.get("persistent_process_start_count") == 1
        and row.get("persistent_request_count") == 3
        and row.get("shutdown") is True
        and row.get("status") == "PASS"
    )


def _check_source_install(evidence: dict[str, object]) -> bool:
    row = evidence.get("source_development_install")
    return isinstance(row, dict) and bool(
        row.get("dedicated_artifact_detail_level") == "marker-only"
        and row.get("dedicated_artifact_status") == "PASS"
        and row.get("environment") == "ubuntu-latest, CPython 3.13.15, Rust 1.85"
        and row.get("native_install") == "pip install from compiler-rs/distributions/aether-compiler-core source directory"
        and row.get("language_install") == "editable source checkout with --no-deps"
        and row.get("binding_import") == "PASS"
        and row.get("companion_discovery") == "PASS"
        and row.get("scope") == "This qualifies the recorded source/editable workflow only."
        and row.get("status") == "PASS"
    )


def _check_cli_ide_scope(evidence: dict[str, object]) -> bool:
    row = evidence.get("cli_and_ide_scope")
    return isinstance(row, dict) and row == {
        "cli": {
            "entry_point_executed_end_to_end": False,
            "qualified_evidence": (
                "clean consumers imported the installed language package and exercised "
                "ProductionRustSSALoweringClient with the installed companion"
            ),
            "scope": "installed package/production-client qualification; not a CLI execution lane",
        },
        "source_install": {
            "executed": True,
            "environment": "ubuntu-latest, CPython 3.13.15, Rust 1.85",
            "scope": "the recorded native source plus editable language install workflow only",
        },
        "vscode": {
            "audit_only": True,
            "cross_platform_execution": False,
            "entry_points": ["aether", "aether-lsp"],
            "integration_change_required": False,
        },
        "intellij": {
            "audit_only": True,
            "cross_platform_execution": False,
            "entry_points": ["aether", "aether-lsp"],
            "integration_change_required": False,
        },
    }


def _check_failure_campaign(evidence: dict[str, object]) -> bool:
    row = evidence.get("failure_campaign")
    return isinstance(row, dict) and bool(
        row.get("dedicated_artifact_detail_level") == "marker-only"
        and row.get("dedicated_artifact_status") == "PASS"
        and row.get("passed") == 13
        and row.get("deselected") == 14
        and set(row.get("cases", [])) == EXPECTED_FAILURE_CASES
        and row.get("platform_scope") == "ubuntu-latest; the executable-bit case is POSIX-only"
        and row.get("status") == "PASS"
    )


def _check_production_guard(evidence: dict[str, object]) -> bool:
    row = evidence.get("production_architecture_guard")
    return isinstance(row, dict) and row == {
        "authority_modes_unchanged": True,
        "automatic_fallback": False,
        "companion_remains_production_and_rollback": True,
        "compiler_core_semantics_unchanged": True,
        "in_process_promoted": False,
        "lifecycle_unchanged": True,
        "production_default_changed": False,
        "production_transport": "companion",
        "protocol_v1_preserved": True,
        "pyo3_available_productively": True,
        "pyo3_is_production_default": False,
        "refinement_unchanged": True,
        "schemas_unchanged": True,
    }


def _check_historical(evidence: dict[str, object]) -> bool:
    row = evidence.get("historical_failed_run")
    return isinstance(row, dict) and bool(
        row.get("run_id") == HISTORICAL_RUN_ID
        and row.get("exact_revision") == HISTORICAL_REVISION
        and row.get("branch") == "main"
        and row.get("status") == "FAILED"
        and row.get("conclusion") == "failure"
        and row.get("aggregate_decision") == BLOCKED
        and row.get("immutable") is True
        and row.get("relationship") == "independent earlier qualification; not overwritten or reinterpreted"
        and row.get("revealed_qualification_or_ci_harness_defects_later_corrected") is True
        and row.get("causes") == [
            "binding-installed-smoke failed its CORE-1.0A production replay",
            "the binding evidence artifact was consequently absent",
            "aggregate-fail-closed blocked on the missing core_pkg_1_binding_smoke evidence",
        ]
    )


def _check_warnings(evidence: dict[str, object]) -> bool:
    row = evidence.get("known_warnings_and_limitations")
    if not isinstance(row, dict):
        return False
    node = row.get("node_js_runtime")
    return bool(
        isinstance(node, dict)
        and node == {
            "actions_target": "Node.js 20",
            "affected_actions": [
                "actions/checkout@v4",
                "actions/setup-python@v5",
                "actions/download-artifact@v4",
                "actions/upload-artifact@v4",
            ],
            "classification": "CI maintenance warning",
            "core_pkg_1_failure": False,
            "executed_runtime": "Node.js 24",
            "observed": True,
        }
        and row.get("performance_characterization_available") is False
        and row.get("rust_required_in_build_environment") is True
        and row.get("rust_or_cargo_required_by_clean_consumer") is False
        and row.get("universal_platform_compatibility_claimed") is False
        and row.get("universal_python_compatibility_claimed") is False
    )


def _check_scope(evidence: dict[str, object]) -> bool:
    scope = evidence.get("scope")
    blocker = evidence.get("core_1_0b_distribution_blocker")
    performance = evidence.get("performance")
    return bool(
        isinstance(scope, dict)
        and scope == {
            "companion_can_be_removed": False,
            "core_1_0b_promoted": False,
            "core_1_1_authorized_or_implemented": False,
            "distribution_blocker_resolved_for_tested_matrix": True,
            "native_distribution_qualified_for_tested_matrix": True,
            "pyo3_is_production_default": False,
            "semantic_changes_in_closure": False,
            "universal_platform_or_python_correctness": False,
        }
        and blocker == {
            "previous_blocker": "CORE_IN_PROCESS_PRODUCTION_TRANSPORT_PROMOTION_BLOCKED",
            "blocker_reason": "production installation did not guarantee `_aether_core`",
            "resolution": QUALIFIED,
            "permitted_consequence": "CORE-1.0B may resume qualification/promotion work",
            "historical_blocker": "_aether_core was not part of normal aether-language installations",
            "resolved_for_qualified_matrix": True,
            "result": "The distribution blocker that stopped CORE-1.0B is resolved for the qualified platform/Python matrix.",
            "core_1_0b_promoted": False,
        }
        and isinstance(performance, dict)
        and performance.get("characterization_available") is False
        and performance.get("correctness_gate") is False
    )


def verify_historical_closure_integrity(evidence: dict[str, object]) -> bool:
    """Verify the source hashes sealed into the qualified historical closure.

    The expected mapping is pinned in this checker and the closure separately
    records the official run and revision.  Consuming that record must not
    require the historical Git object to be present in a later shallow clone.
    """
    return evidence.get("source_snapshot") == EXPECTED_SOURCE_SNAPSHOT


def verify_current_source_matches_qualified_revision(root: Path = ROOT) -> bool:
    """Compare a worktree with the source snapshot qualified at ``REVISION``."""
    return all(
        (root / name).is_file() and _digest(root / name) == digest
        for name, digest in EXPECTED_SOURCE_SNAPSHOT.items()
    )


def _check_source_snapshot(
    evidence: dict[str, object], root: Path | None = None
) -> bool:
    """Backward-compatible name for historical closure integrity verification."""
    del root
    return verify_historical_closure_integrity(evidence)


def _check_report(report_path: Path) -> bool:
    if not report_path.is_file():
        return False
    report = report_path.read_text(encoding="utf-8")
    required = (
        QUALIFIED,
        str(RUN_ID),
        REVISION,
        str(HISTORICAL_RUN_ID),
        "CORE-1.0B remains unpromoted",
        "CORE-1.1 was not implemented",
        "14 artifacts",
        "byte-identical",
        "CI maintenance warning",
    )
    return all(token in report for token in required)


def verify_downloaded_official_evidence(
    archive_dir: Path, evidence_dir: Path
) -> dict[str, bool]:
    """Verify optional freshly downloaded ZIPs/files and reproduce the aggregate."""
    archives_ok = True
    files_ok = True
    for name, (_artifact_id, digest, _job, files) in EXPECTED_ARTIFACTS.items():
        archive = archive_dir / f"{name}.zip"
        archives_ok &= (
            archive.is_file()
            and archive.stat().st_size == EXPECTED_ARTIFACT_SIZES[name]
            and _digest(archive) == digest
        )
        for filename, expected_hash in files.items():
            matches = list(evidence_dir.rglob(filename))
            files_ok &= len(matches) == 1 and _digest(matches[0]) == expected_hash

    aggregate_matches = False
    checker_ready = False
    try:
        with tempfile.TemporaryDirectory(prefix="core-pkg-1-closure-") as raw:
            temporary = Path(raw)
            flat = temporary / "evidence"
            flat.mkdir()
            for name, (_artifact_id, _digest_value, _job, files) in EXPECTED_ARTIFACTS.items():
                if name == "core-pkg-1-aggregate":
                    continue
                for filename in files:
                    matches = list(evidence_dir.rglob(filename))
                    if len(matches) != 1:
                        raise ValueError(f"expected one {filename}, found {len(matches)}")
                    shutil.copy2(matches[0], flat / filename)
            checker_path = ROOT / "scripts/check_core_pkg_1_native_distribution.py"
            spec = importlib.util.spec_from_file_location("core_pkg_1_official_checker", checker_path)
            if spec is None or spec.loader is None:
                raise ValueError("could not load official checker")
            checker = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(checker)
            aggregate, errors = checker.check(flat, ci_closure=True)
            recomputed = (json.dumps(aggregate, indent=2, sort_keys=True) + "\n").encode()
            official_matches = list(evidence_dir.rglob("aggregate.json"))
            checker_ready = aggregate.get("decision") == QUALIFIED and errors == []
            aggregate_matches = len(official_matches) == 1 and official_matches[0].read_bytes() == recomputed
    except Exception:
        checker_ready = False
        aggregate_matches = False
    return {
        "downloaded_archives": archives_ok,
        "downloaded_extracted_files": files_ok,
        "downloaded_checker_qualified": checker_ready,
        "downloaded_aggregate_byte_identical": aggregate_matches,
    }


def build_record(
    evidence_path: Path = DEFAULT_EVIDENCE,
    report_path: Path = DEFAULT_REPORT,
    *,
    root: Path = ROOT,
    archive_dir: Path | None = None,
    official_evidence_dir: Path | None = None,
) -> dict[str, object]:
    evidence = _load(evidence_path)
    checks = {
        "schema_and_milestone": (
            evidence.get("artifact_schema_version") == 1
            and evidence.get("kind") == "core_pkg_1_native_compiler_core_distribution_closure"
            and evidence.get("milestone") == "CORE-PKG-1"
            and evidence.get("closure_date") == "2026-08-28"
        ),
        "official_run_identity": _check_run(evidence),
        "required_jobs": _check_jobs(evidence),
        "artifact_manifest": _check_artifacts(evidence),
        "official_aggregate": _check_aggregate(evidence),
        "package_contract": _check_package_contract(evidence),
        "compiler_core_identity": _check_identity(evidence),
        "platform_matrix": _check_platforms(evidence),
        "python_matrix": _check_pythons(evidence),
        "binding_installed_smoke": _check_binding(evidence),
        "companion_installed_rollback": _check_companion(evidence),
        "source_development_install": _check_source_install(evidence),
        "cli_and_ide_scope": _check_cli_ide_scope(evidence),
        "failure_campaign": _check_failure_campaign(evidence),
        "production_companion_default_guard": _check_production_guard(evidence),
        "historical_failed_run": _check_historical(evidence),
        "known_warnings_and_limitations": _check_warnings(evidence),
        "closure_scope": _check_scope(evidence),
        "source_snapshot": verify_historical_closure_integrity(evidence),
        "closure_report": _check_report(report_path),
        "declared_eligibility": _check_eligibility(evidence),
    }
    if (archive_dir is None) != (official_evidence_dir is None):
        checks["downloaded_evidence_arguments"] = False
    elif archive_dir is not None and official_evidence_dir is not None:
        checks.update(verify_downloaded_official_evidence(archive_dir, official_evidence_dir))

    qualification_eligible = all(checks.values())
    expected_decision = QUALIFIED if qualification_eligible else BLOCKED
    checks["decision_recomputes"] = (
        evidence.get("decision") == expected_decision
        and evidence.get("final_decision") == expected_decision
    )
    passed = qualification_eligible and all(checks.values())
    return {
        "artifact_schema_version": 1,
        "kind": "core_pkg_1_native_compiler_core_distribution_closure_check",
        "run_id": RUN_ID,
        "exact_revision": REVISION,
        "checks": checks,
        "qualification_eligible": qualification_eligible,
        "passed": passed,
        "decision": QUALIFIED if passed else BLOCKED,
        "current_source_identity": {
            "matches_qualified_revision": verify_current_source_matches_qualified_revision(
                root
            ),
            "required_for_historical_qualification": False,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", type=Path, default=DEFAULT_EVIDENCE)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--archive-dir", type=Path)
    parser.add_argument("--official-evidence-dir", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--require-qualified", action="store_true")
    args = parser.parse_args()
    try:
        record = build_record(
            args.evidence,
            args.report,
            archive_dir=args.archive_dir,
            official_evidence_dir=args.official_evidence_dir,
        )
    except Exception as error:
        record = {
            "artifact_schema_version": 1,
            "kind": "core_pkg_1_native_compiler_core_distribution_closure_check",
            "run_id": RUN_ID,
            "exact_revision": REVISION,
            "checks": {"evidence_load": False},
            "qualification_eligible": False,
            "passed": False,
            "decision": BLOCKED,
            "error": str(error),
        }
    rendered = json.dumps(record, indent=2, sort_keys=True) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(record["decision"])
    for name, passed in record["checks"].items():
        if not passed:
            print(f"- {name}: FAIL")
    return 1 if args.require_qualified and not record["passed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
