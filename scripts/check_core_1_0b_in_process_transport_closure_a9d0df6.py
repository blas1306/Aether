#!/usr/bin/env python3
"""Fail-closed checker for the official CORE-1.0B closure at a9d0df6."""

from __future__ import annotations

import argparse
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EVIDENCE = (
    ROOT
    / "docs/compiler/core_1_0b_in_process_production_transport_promotion_closure_a9d0df6.json"
)
DEFAULT_REPORT = (
    ROOT
    / "docs/compiler/CORE_1_0B_IN_PROCESS_PRODUCTION_TRANSPORT_PROMOTION_CLOSURE_A9D0DF6.md"
)

RUN_ID = 33293548667
REVISION = "a9d0df6eeec081cc8baf881450e5e3a30db9d020"
WORKFLOW_NAME = "core-in-process-production-transport-promotion"
WORKFLOW_PATH = ".github/workflows/core-in-process-promotion.yml"
PROMOTED = "CORE_IN_PROCESS_PRODUCTION_TRANSPORT_PROMOTED"
BLOCKED = "CORE_IN_PROCESS_PRODUCTION_TRANSPORT_PROMOTION_BLOCKED"
CORE_PKG_1_DECISION = "CORE_NATIVE_COMPILER_CORE_DISTRIBUTION_QUALIFIED"
CORE_PKG_1_RUN = 33216160463
CORE_PKG_1_REVISION = "77417e7751482fc5a88a7d4207e99d67692da043"
AGGREGATE_SHA256 = "4a0f7ab6ea6967fa0d5190f9a0f75f47e23b4170b45d944e550c360c7cb6baaa"
SHA256 = re.compile(r"[0-9a-f]{64}")

EXPECTED_JOBS = {
    "affected-rust-4-5": 99209237775,
    "differential-both-transports": 99209237798,
    "production-default-in-process": 99209237814,
    "sessions-concurrency": 99209237824,
    "blocker-resolution": 99209237827,
    "no-fallback": 99209237836,
    "explicit-companion-rollback": 99209237853,
    "python-compatibility (3.13)": 99209237860,
    "transport-parity": 99209237871,
    "source-development-install": 99209237875,
    "clean-install-platform (macos-arm64, macos-15)": 99209237878,
    "clean-install-platform (macos-x86_64, macos-15-intel)": 99209237880,
    "packaged-clean-consumer": 99209237896,
    "python-compatibility (3.11)": 99209237943,
    "python-compatibility (3.14)": 99209237946,
    "clean-install-platform (windows-x86_64, windows-latest)": 99209237954,
    "clean-install-platform (linux-x86_64, ubuntu-latest)": 99209237970,
    "python-compatibility (3.12)": 99209237992,
    "production-pipeline": 99209493921,
    "aggregate-fail-closed": 99209748688,
}

# artifact ID, GitHub/archive digest, size, source job, source job ID, files.
EXPECTED_ARTIFACTS = {
    "core-1-0b-aggregate": (
        9726749933,
        "0de046fd8ac8fdbe181a206737b6b36d565ee061165b556ee14ef25ef9cb87c0",
        822,
        "aggregate-fail-closed",
        99209748688,
        {"aggregate.json": AGGREGATE_SHA256},
    ),
    "core-1-0b-platform-macos-x86_64": (
        9726742173,
        "50ef5ac1f74fa26b9efd3e0b1ac81717dd5558962c56b9a959e18e8751e8dfc0",
        4812,
        "clean-install-platform (macos-x86_64, macos-15-intel)",
        99209237880,
        {
            "consumer-macos-x86_64-companion.json": "f8a70eaa974b23478e77009d79f45874797051d5f7253e7db04dbbf4c92daa76",
            "consumer-macos-x86_64-in-process.json": "6fb4b470399ec65a4c1341ea72ef71f9e2b6a54412698abe1f363b8170843f2e",
            "platform-macos-x86_64.json": "22840303b2173b7fca3ac0b26e04d704b6d3583dd346f45d91ef2836658d7a91",
        },
    ),
    "core-1-0b-platform-windows-x86_64": (
        9726741419,
        "a43a422f2b5fce45faa8e0fb99abdd977c2e8282a04023c9ddb81da6d3dc9e72",
        4825,
        "clean-install-platform (windows-x86_64, windows-latest)",
        99209237954,
        {
            "consumer-windows-x86_64-companion.json": "b48469ee8d2a2d003af359ada7d28dc80a846322992d720edb2525bbd9410449",
            "consumer-windows-x86_64-in-process.json": "63e4bb6f0335d275ca16a1d243547461d27e05f27e18b9fcb5f26a86a9b0093a",
            "platform-windows-x86_64.json": "e9fd66c684be974753b696796d00133ffc41b41b09a971e5e2e4cba6c84bd329",
        },
    ),
    "core-1-0b-functional": (
        9726722333,
        "8d10012ee7c7486cc4a9e2ee49645c3c19b76182afc65af23b0113b7d3f521ab",
        4318,
        "transport-parity",
        99209237871,
        {"functional.json": "49e7d8c11f23bf59671a924c13ba893cc2210672386c3691e21e0398c0fb139f"},
    ),
    "core-1-0b-python-3.14": (
        9726720570,
        "56736d6e29df0e9ea5b2f4043de6ea761351f8b627410aacddfb20f4ce151cfd",
        4747,
        "python-compatibility (3.14)",
        99209237946,
        {
            "consumer-python-3.14-companion.json": "28f9fe8045e9f4a9ec40e78216c51b4835a595d69d00b1ef1d8a987c656bfb0c",
            "consumer-python-3.14-in-process.json": "d71a2d0cf29a67aec5e3342f2de0835bdc659cadb4701af01db7b2efb7af7b84",
            "python-3.14.json": "465e7ca9321616f2a5058b6fc0c306be908224b59641256aabe042274026cde4",
        },
    ),
    "core-1-0b-platform-linux-x86_64": (
        9726720304,
        "477c237807616176310bdadc2cd102e3263832a1e15b108a246b3c205ae6dc09",
        4748,
        "clean-install-platform (linux-x86_64, ubuntu-latest)",
        99209237970,
        {
            "consumer-linux-x86_64-companion.json": "7d74db5a21272f2b9048232c75e05593ac5fe5640dc319f02f99023147fd4725",
            "consumer-linux-x86_64-in-process.json": "051d6a0525efc229638e2aac365772f08e21f31d534354b1ed94441729a5f13a",
            "platform-linux-x86_64.json": "a741fe6cda90524ce733a122a77a2dfdcf67b91cb903d2784ea12081e9273a02",
        },
    ),
    "core-1-0b-python-3.13": (
        9726720110,
        "53066d20768621d00802b1c3e3d2890d9f6069561a455af44a0dc6b3228bf9c3",
        4744,
        "python-compatibility (3.13)",
        99209237860,
        {
            "consumer-python-3.13-companion.json": "46641774db82b62d356f5e2243026bf256ec741ce0b476dcd5de4193e717620b",
            "consumer-python-3.13-in-process.json": "e5ef16d0387571a22a012f4cad1a0c7c6c60d30abf3da857629881eae8a1a331",
            "python-3.13.json": "704088988617f654392e5c20cf295dba31e7d177dfc12d1de41d3a9cfab8ae31",
        },
    ),
    "core-1-0b-development-install": (
        9726719670,
        "e431dc495c4efd0c4936aa1f628870abe7d2f09d5bea4ad2b3887f624676b702",
        3026,
        "source-development-install",
        99209237875,
        {"development-install.json": "b30409f589d8c268813b8858247356299e0b83511ca48252b0fd42c3967784fa"},
    ),
    "core-1-0b-python-3.11": (
        9726719635,
        "7c9f867841f87985048d178311f9bfcb7b02be2299909d86f9a3bb4e15dde705",
        4735,
        "python-compatibility (3.11)",
        99209237943,
        {
            "consumer-python-3.11-companion.json": "cbd9b9969b8481d3f0a10a4776079a25d18f7d0192bbbce0522cc18f13bcf570",
            "consumer-python-3.11-in-process.json": "290485094e57561f2d9147fd37df37561f9f2f62653ddede22d0127abcae528e",
            "python-3.11.json": "7b6e1d200a0f32df130f65bcf429488ad6f13e6d36a6663c84ff8913ecaf7053",
        },
    ),
    "core-1-0b-packaged-consumer": (
        9726717779,
        "e0e02fb6b47c4cc27275fb428b49c8ea7d33c7b3d8e7a751479373328fe4ed9b",
        3946,
        "packaged-clean-consumer",
        99209237896,
        {
            "core-1.0b-packaged-companion.json": "2d634f35b0af3bc834b5f1de0d889ee978ebca2f17e1767324a822c3d242c0bd",
            "core-1.0b-packaged-default.json": "60caab2e778afe576042289dbd8f08caa594cd5772935d2dc381955d6b1c7f0b",
            "core-1.0b-packaged-install.json": "0dfb4a045c7ca7323d4853d2a271c5038604b5f6a9ed4097d5c80c5a719337d8",
        },
    ),
    "core-1-0b-python-3.12": (
        9726716078,
        "7f8e23f3d2be195c646c6c0bd78793b312dba907789a429fdcc04a2fb8d632a1",
        4737,
        "python-compatibility (3.12)",
        99209237992,
        {
            "consumer-python-3.12-companion.json": "b278b68ad9b641cc9915c3fe3ed0503f5753f60156df40ce7e90103ba19ddda4",
            "consumer-python-3.12-in-process.json": "a00016d2baa3b4d6e291a1f7ea89b572aaea07f092e2d63d0ee7c4607e605b61",
            "python-3.12.json": "e6983c392af71d0930f4aa752eedea71241ef8cccd2f49f6fd968ebd208807d5",
        },
    ),
    "core-1-0b-platform-macos-arm64": (
        9726714595,
        "557e1cc1c25e302f5c47fe08f129e241ef975f0b8dc34cf2cacf98149bb1abcc",
        4791,
        "clean-install-platform (macos-arm64, macos-15)",
        99209237878,
        {
            "consumer-macos-arm64-companion.json": "7a0c498bdc7ae97eab4a86fae2059d0157c437ba07c671e4cb3f132837ccb506",
            "consumer-macos-arm64-in-process.json": "ef9add9161e0d70b85ae0c4f536cecd92f284c9d7b904b85f8d6ec8e6cb9fcb0",
            "platform-macos-arm64.json": "013e933e0b407892dc413acb51a881267d20c150cd836c6e08e00d6ecd3404a8",
        },
    ),
    "core-1-0b-blocker-resolution": (
        9726696549,
        "1363606b54bbfd9e08a5d1268391425e9496ad4ef6e21074f0990f150b1eb0ed",
        698,
        "blocker-resolution",
        99209237827,
        {"blocker-resolution.json": "0df74351f7a7bd74aa0e9bf8cd4947ec921897760f505cfdc889f72bdee630ae"},
    ),
}


def _sha256(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _load(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"closure evidence is not an object: {path}")
    return value


def _job_check(value: object) -> bool:
    if not isinstance(value, list) or len(value) != len(EXPECTED_JOBS):
        return False
    observed: dict[str, int] = {}
    for row in value:
        if not isinstance(row, dict) or not (
            row.get("status") == "completed"
            and row.get("conclusion") == "success"
            and row.get("head_sha") == REVISION
            and isinstance(row.get("id"), int)
            and isinstance(row.get("name"), str)
        ):
            return False
        observed[str(row["name"])] = int(row["id"])
    return observed == EXPECTED_JOBS


def _artifact_check(value: object) -> bool:
    if not isinstance(value, list) or len(value) != len(EXPECTED_ARTIFACTS):
        return False
    observed = {
        str(row.get("artifact_name")): row
        for row in value
        if isinstance(row, dict)
    }
    if set(observed) != set(EXPECTED_ARTIFACTS):
        return False
    for name, spec in EXPECTED_ARTIFACTS.items():
        artifact_id, digest, size, source_job, source_job_id, files = spec
        row = observed[name]
        extracted = row.get("extracted_files")
        extracted_map = {
            str(item.get("filename")): str(item.get("sha256"))
            for item in extracted
            if isinstance(item, dict)
        } if isinstance(extracted, list) else {}
        if name == "core-1-0b-aggregate":
            expected_record = (
                ["core_1_0b_transport_aggregate"],
                PROMOTED,
                REVISION,
                RUN_ID,
                "aggregate",
                ["official_decision"],
            )
        elif name == "core-1-0b-blocker-resolution":
            expected_record = (
                ["core_pkg_1_native_compiler_core_distribution_closure_check"],
                "PASS",
                CORE_PKG_1_REVISION,
                CORE_PKG_1_RUN,
                "blocker_resolution",
                ["CORE-PKG-1"],
            )
        elif name == "core-1-0b-functional":
            expected_record = (
                ["core_1_0b_transport_lane"],
                "PASS",
                REVISION,
                RUN_ID,
                "functional",
                ["full_functional"],
            )
        elif name == "core-1-0b-development-install":
            expected_record = (
                ["core_1_0b_transport_lane"],
                "PASS",
                REVISION,
                RUN_ID,
                "development_install",
                ["source_development_install"],
            )
        elif name == "core-1-0b-packaged-consumer":
            expected_record = (
                [
                    "core_1_0b_clean_consumer_install",
                    "core_1_0b_packaged_clean_consumer",
                ],
                "PASS",
                REVISION,
                RUN_ID,
                "packaged_clean_consumer",
                ["install", "in_process", "companion"],
            )
        elif name.startswith("core-1-0b-platform-"):
            expected_record = (
                ["core_1_0b_transport_lane", "core_1_0b_packaged_consumer"],
                "PASS",
                REVISION,
                RUN_ID,
                "platform",
                ["lane", "in_process", "companion"],
            )
        else:
            expected_record = (
                ["core_1_0b_transport_lane", "core_1_0b_packaged_consumer"],
                "PASS",
                REVISION,
                RUN_ID,
                "python_compatibility",
                ["lane", "in_process", "companion"],
            )
        if not (
            row.get("artifact_id") == artifact_id
            and row.get("archive_filename") == f"{name}.zip"
            and row.get("archive_size_bytes") == size
            and row.get("github_digest_sha256") == digest
            and row.get("archive_sha256") == digest
            and row.get("digest_verified") is True
            and row.get("source_job") == source_job
            and row.get("source_job_id") == source_job_id
            and row.get("validation_result") == "PASS"
            and extracted_map == files
            and row.get("record_kinds") == expected_record[0]
            and row.get("record_status") == expected_record[1]
            and row.get("record_revision") == expected_record[2]
            and row.get("record_ci_run_id") == expected_record[3]
            and row.get("record_role") == expected_record[4]
            and row.get("record_subgates") == expected_record[5]
        ):
            return False
    return True


def _downloaded_artifacts_check(archive_dir: Path) -> bool:
    expected_names = {f"{name}.zip" for name in EXPECTED_ARTIFACTS}
    if not archive_dir.is_dir():
        return False
    actual = {path.name for path in archive_dir.iterdir() if path.is_file()}
    if actual != expected_names:
        return False
    return all(
        _sha256(archive_dir / f"{name}.zip") == spec[1]
        and (archive_dir / f"{name}.zip").stat().st_size == spec[2]
        for name, spec in EXPECTED_ARTIFACTS.items()
    )


def _find_exactly_one(root: Path, filename: str) -> Path | None:
    matches = list(root.rglob(filename))
    return matches[0] if len(matches) == 1 else None


def _downloaded_evidence_check(evidence_dir: Path) -> bool:
    if not evidence_dir.is_dir():
        return False
    for spec in EXPECTED_ARTIFACTS.values():
        for filename, digest in spec[5].items():
            path = _find_exactly_one(evidence_dir, filename)
            if path is None or _sha256(path) != digest:
                return False

    checker_path = ROOT / "scripts/check_core_1_0b_in_process_transport.py"
    spec = importlib.util.spec_from_file_location("core_1_0b_checker", checker_path)
    if spec is None or spec.loader is None:
        return False
    checker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(checker)
    aggregate, errors = checker.check(
        evidence_dir,
        exact_revision=REVISION,
        ci_run_id=str(RUN_ID),
        ci_closure=True,
    )
    rendered = (json.dumps(aggregate, indent=2, sort_keys=True) + "\n").encode()
    official = _find_exactly_one(evidence_dir, "aggregate.json")
    return bool(
        not errors
        and aggregate.get("decision") == PROMOTED
        and sha256(rendered).hexdigest() == AGGREGATE_SHA256
        and official is not None
        and official.read_bytes() == rendered
    )


def _source_snapshot_check(value: object) -> bool:
    if not isinstance(value, dict) or not value:
        return False
    for relative, digest in value.items():
        path = ROOT / str(relative)
        if not (
            isinstance(digest, str)
            and SHA256.fullmatch(digest)
            and path.is_file()
            and _sha256(path) == digest
        ):
            return False
    return True


def build_record(
    evidence_path: Path = DEFAULT_EVIDENCE,
    report_path: Path = DEFAULT_REPORT,
    *,
    archive_dir: Path | None = None,
    evidence_dir: Path | None = None,
) -> dict[str, object]:
    try:
        evidence = _load(evidence_path)
    except Exception as exc:
        return {
            "kind": "core_1_0b_in_process_transport_closure_check",
            "passed": False,
            "decision": BLOCKED,
            "errors": [f"cannot load closure evidence: {exc}"],
        }

    official_run = evidence.get("official_run")
    core_pkg = evidence.get("core_pkg_1_prerequisite")
    aggregate = evidence.get("aggregate_validation")
    transport = evidence.get("transport_contract")
    sessions = evidence.get("sessions_concurrency")
    functional = evidence.get("functional_qualification")
    structured = evidence.get("structured_failure_campaign")
    performance = evidence.get("performance_characterization")
    packaged = evidence.get("packaged_clean_consumer")
    source_install = evidence.get("source_development_install")
    scope = evidence.get("scope")

    checks: dict[str, bool] = {
        "schema_and_milestone": evidence.get("artifact_schema_version") == 1
        and evidence.get("kind") == "core_1_0b_in_process_transport_promotion_closure"
        and evidence.get("milestone") == "CORE-1.0B",
        "official_run_identity": isinstance(official_run, dict)
        and official_run
        == {
            "run_id": RUN_ID,
            "run_attempt": 1,
            "workflow_name": WORKFLOW_NAME,
            "workflow_path": WORKFLOW_PATH,
            "event": "workflow_dispatch",
            "branch": "main",
            "head_sha": REVISION,
            "status": "completed",
            "conclusion": "success",
            "created_at": "2026-08-30T04:55:20Z",
            "run_started_at": "2026-08-30T04:55:20Z",
            "updated_at": "2026-08-30T05:01:03Z",
            "html_url": "https://github.com/blas1306/Aether/actions/runs/33293548667",
        },
        "required_jobs": _job_check(evidence.get("run_jobs")),
        "artifact_manifest": _artifact_check(evidence.get("artifact_manifest")),
        "core_pkg_1_prerequisite": isinstance(core_pkg, dict)
        and core_pkg.get("decision") == CORE_PKG_1_DECISION
        and core_pkg.get("run_id") == CORE_PKG_1_RUN
        and core_pkg.get("revision") == CORE_PKG_1_REVISION
        and core_pkg.get("recomputed") is True
        and core_pkg.get("exact_version_contract")
        == "aether-language==1.0.0rc4 requires aether-compiler-core==1.0.0rc4",
        "aggregate_official_and_recomposed": isinstance(aggregate, dict)
        and aggregate.get("official_decision") == PROMOTED
        and aggregate.get("recomposed_decision") == PROMOTED
        and aggregate.get("official_errors") == []
        and aggregate.get("official_sha256") == AGGREGATE_SHA256
        and aggregate.get("recomposed_sha256") == AGGREGATE_SHA256
        and aggregate.get("byte_identical") is True
        and aggregate.get("input_artifacts") == 12,
        "transport_contract": isinstance(transport, dict)
        and transport.get("default_requested") == "in_process"
        and transport.get("default_observed") == "in_process"
        and transport.get("explicit_rollback_requested") == "companion"
        and transport.get("explicit_rollback_observed") == "companion"
        and transport.get("automatic_fallback") is False
        and transport.get("mismatch_fails_closed") is True
        and transport.get("invalid_selection_fails_closed") is True
        and transport.get("companion_protocol") == 1
        and transport.get("companion_remains_available") is True,
        "sessions_concurrency": isinstance(sessions, dict)
        and sessions.get("status") == "PASS"
        and sessions.get("concurrent_requests") == 32
        and sessions.get("compiler_core_reused") is True
        and sessions.get("rust_owned_sessions_per_request") is True
        and sessions.get("cross_session_state_leak_observed") is False,
        "functional_qualification": isinstance(functional, dict)
        and functional.get("status") == "PASS"
        and functional.get("historical") == "116/116 both transports"
        and functional.get("production_pipeline") == "116/116 both transports"
        and functional.get("deep_cfg") == [993, 1000, 5000, 10000]
        and functional.get("representative_failures") == 6
        and functional.get("differential_both_transports") is True
        and functional.get("divergence_fail_closed") is True
        and functional.get("refinement_corruption_fail_closed") is True
        and functional.get("affected_rust_gates") == "PASS"
        and functional.get("production_pipeline_job") == "PASS",
        "structured_failure_campaign": isinstance(structured, dict)
        and structured.get("status") == "PASS"
        and structured.get("cases")
        == [
            "malformed_initial_ir_json",
            "non_object_binding_input",
            "unsupported_schema",
            "unknown_root_field",
            "invalid_cfg_target",
            "duplicate_function",
        ]
        and structured.get("compared_contract")
        == ["accept_reject", "structured_error_category", "phase", "source_location"]
        and structured.get("textual_identity_required") is False,
        "performance_characterization": isinstance(performance, dict)
        and performance.get("correctness_gate") is False
        and set(performance.get("transports", {})) == {"in_process", "companion"}
        and performance.get("workloads")
        == ["ordinary", "deep_cfg_1000", "historical_116", "real_ae_expense_tracker"]
        and performance.get("phases")
        == ["conversion", "core", "ipc_protocol", "result_conversion"],
        "platform_matrix": isinstance(evidence.get("platform_matrix"), list)
        and {
            row.get("platform")
            for row in evidence.get("platform_matrix", [])
            if isinstance(row, dict) and row.get("status") == "PASS"
        }
        == {"linux-x86_64", "windows-x86_64", "macos-x86_64", "macos-arm64"}
        and all(
            row.get("default_observed") == "in_process"
            and row.get("rollback_observed") == "companion"
            and row.get("consumer_without_cargo_or_rustc") is True
            and row.get("matching_build_identity") == REVISION
            for row in evidence.get("platform_matrix", [])
            if isinstance(row, dict)
        ),
        "python_matrix": isinstance(evidence.get("python_matrix"), list)
        and {
            row.get("minor"): row.get("patch")
            for row in evidence.get("python_matrix", [])
            if isinstance(row, dict) and row.get("status") == "PASS"
        }
        == {"3.11": "3.11.16", "3.12": "3.12.14", "3.13": "3.13.15", "3.14": "3.14.7"}
        and all(
            row.get("default_observed") == "in_process"
            and row.get("rollback_observed") == "companion"
            for row in evidence.get("python_matrix", [])
            if isinstance(row, dict)
        ),
        "packaged_clean_consumer": isinstance(packaged, dict)
        and packaged.get("status") == "PASS"
        and packaged.get("artifact_kind") == "core_1_0b_packaged_clean_consumer"
        and packaged.get("artifact_role") == "packaged_clean_consumer"
        and packaged.get("dedicated_records")
        == ["core-1.0b-packaged-default.json", "core-1.0b-packaged-companion.json"]
        and packaged.get("install_manifest") == "core-1.0b-packaged-install.json"
        and packaged.get("matrix_records_cannot_substitute") is True
        and packaged.get("language_version") == "1.0.0rc4"
        and packaged.get("native_version") == "1.0.0rc4"
        and packaged.get("native_build_identity") == REVISION
        and packaged.get("aether_index_resolution_permitted") is False
        and packaged.get("cargo_available") is False
        and packaged.get("rustc_available") is False
        and packaged.get("outside_checkout") is True
        and packaged.get("default_observed") == "in_process"
        and packaged.get("rollback_observed") == "companion"
        and packaged.get("in_process_companion_starts") == 0
        and packaged.get("companion_process_starts") == 1
        and packaged.get("companion_pyo3_calls") == 0
        and packaged.get("request_count_each") == 3
        and packaged.get("handled_failure_recovery") is True
        and packaged.get("representative_compilation") is True
        and packaged.get("matching_output_sha256")
        == "2522a8877eaac3b97be8dc43413396514a8a5ac5ae0637da4da5c770b7bcf5b2"
        and packaged.get("companion_from_installed_package") is True,
        "source_development_install": isinstance(source_install, dict)
        and source_install.get("status") == "PASS"
        and source_install.get("source_checkout") is True
        and source_install.get("native_build_install") is True
        and source_install.get("editable_language_install") is True
        and source_install.get("binding_discovery") is True
        and source_install.get("companion_discovery") is True
        and source_install.get("default_observed") == "in_process"
        and source_install.get("rollback_observed") == "companion",
        "historical_failed_runs": evidence.get("historical_failed_runs")
        == [
            {
                "run_id": 33264243543,
                "conclusion": "failure",
                "decision": BLOCKED,
                "retrospectively_promoted": False,
            },
            {
                "run_id": 33265815894,
                "conclusion": "failure",
                "decision": BLOCKED,
                "packaged_clean_consumer": "failure",
                "aggregate_fail_closed": "failure",
                "emitted_promoted_aggregate_valid": False,
                "retrospectively_promoted": False,
            },
            {
                "run_id": 33293069494,
                "conclusion": "failure",
                "decision": BLOCKED,
                "defect_class": "qualification_harness",
                "cause": "packaged install manifest filename mismatch",
                "retrospectively_promoted": False,
            },
        ],
        "scope": isinstance(scope, dict)
        and scope.get("in_process_is_production_default") is True
        and scope.get("companion_is_explicit_rollback") is True
        and scope.get("companion_removable") is False
        and scope.get("protocol_v1_removable") is False
        and scope.get("automatic_fallback") is False
        and scope.get("core_1_1_authorized") is False
        and scope.get("universal_platform_support") is False
        and scope.get("universal_python_support") is False
        and scope.get("universal_semantic_correctness") is False
        and scope.get("universal_thread_safety") is False
        and scope.get("universal_performance_superiority") is False
        and scope.get("production_semantics_changed_beyond_transport_promotion") is False,
        "source_snapshot": _source_snapshot_check(evidence.get("source_snapshot")),
        "closure_report": report_path.is_file()
        and evidence.get("closure_report_sha256") == _sha256(report_path),
        "downloaded_evidence_arguments": (archive_dir is None) == (evidence_dir is None),
    }
    if archive_dir is not None and evidence_dir is not None:
        checks["downloaded_artifact_zips"] = _downloaded_artifacts_check(archive_dir)
        checks["downloaded_and_recomposed_evidence"] = _downloaded_evidence_check(evidence_dir)

    prerequisites_pass = all(checks.values())
    checks["decision_recomputes"] = (
        evidence.get("decision") == (PROMOTED if prerequisites_pass else BLOCKED)
        and evidence.get("final_decision") == (PROMOTED if prerequisites_pass else BLOCKED)
    )
    passed = all(checks.values()) and evidence.get("decision") == PROMOTED
    return {
        "artifact_schema_version": 1,
        "kind": "core_1_0b_in_process_transport_closure_check",
        "passed": passed,
        "decision": PROMOTED if passed else BLOCKED,
        "exact_revision": REVISION,
        "run_id": RUN_ID,
        "checks": checks,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", type=Path, default=DEFAULT_EVIDENCE)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--archive-dir", type=Path)
    parser.add_argument("--evidence-dir", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--require-promoted", action="store_true")
    args = parser.parse_args()
    record = build_record(
        args.evidence,
        args.report,
        archive_dir=args.archive_dir,
        evidence_dir=args.evidence_dir,
    )
    rendered = json.dumps(record, indent=2, sort_keys=True) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(record["decision"])
    return 0 if record["passed"] and (not args.require_promoted or record["decision"] == PROMOTED) else 1


if __name__ == "__main__":
    raise SystemExit(main())
