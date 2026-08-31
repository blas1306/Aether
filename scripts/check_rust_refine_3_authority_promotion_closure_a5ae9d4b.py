#!/usr/bin/env python3
"""Fail-closed checker for the SHA-specific RUST-REFINE-3 closure."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


PROMOTED = "RUST_REFINEMENT_AUTHORITY_PROMOTED"
BLOCKED = "RUST_REFINEMENT_AUTHORITY_PROMOTION_BLOCKED"
REVISION = "a5ae9d4b3a50843faf68bdeb4d8afc227b900bc9"
RUN_ID = "33361044254"
R2_RUN_ID = "33321791729"
R2_REVISION = "0bff8c0a78005d97ee5c7c2e0eb09a6a6b3b1fef"

EXPECTED_JOBS = {
    "production-authority": 99392308403,
    "authority-contract": 99392308522,
    "mutation-adversarial": 99392308536,
    "platform-windows-x86_64": 99392308539,
    "no-python-rescue": 99392308575,
    "prerequisite-rust-refine-2": 99392308588,
    "platform-macos-x86_64": 99392308593,
    "source-development": 99392308595,
    "platform-macos-arm64": 99392308604,
    "python-3.13": 99392308616,
    "python-3.11": 99392308619,
    "directed-differential": 99392308625,
    "python-3.14": 99392308629,
    "python-3.12": 99392308633,
    "production-pipeline": 99392308690,
    "platform-linux-x86_64": 99392308718,
    "deep-stress": 99392308733,
    "cost-characterization": 99392308777,
    "packaged-clean-consumer": 99392308855,
    "transport-parity": 99392308899,
    "aggregate-fail-closed": 99393581364,
}

# name: (artifact ID, downloaded ZIP SHA-256, extracted evidence SHA-256)
EXPECTED_ARTIFACTS = {
    "rust-refine-3-prerequisite": (9746687963, "6186a47eff05cc80578824c91592709f29e150af231df360c7d84c504b036f0c", "80b11e8b84e5f21fbbba5abe910190fc706f42a6c8620bdf1aa9f48c9694c03f"),
    "rust-refine-3-contract": (9746686127, "30b1f03b626938c299784fadc0d119cd624fb2f9e76dff681e0c6f4396b9ff88", "302bc50fa69e7fb4218f709a3ebc7f4cf0828543dc0d4aec1cd30d1c93be45e3"),
    "rust-refine-3-differential": (9746704632, "e08465bf618f22febdbcd1a57c66b5a09adec4e39de7472b0269ba91ba6f2789", "7c68a21dd29ac18703b229e043dfb8139e4db24e3763788b48c2971feb1f05b2"),
    "rust-refine-3-mutations": (9746699087, "d66793ec401a0869eac6a6b11a503e8f7539a0830d92d8c96f522f9548e29843", "ee2ce84c7c969d376ee1867e4e33cb964f4712b2b79b3648b929393454ded065"),
    "rust-refine-3-production-authority": (9746727881, "1e548764265e5ecd1328c65d8c33b54ef5560497c1ef3597d55ae456230c84e4", "603846528df6dc13f610ab314d24ed22dde2e95893773926bd323907a0de2835"),
    "rust-refine-3-no-python-rescue": (9746724303, "4f95fe99f6a180e5f857fb2fb8ce27aaa1dce9efaded6ee9552d48e415ce282e", "ce31d1e963d5607b2a26f87d163b56d73bb313457e6c2b3943135afc10df4996"),
    "rust-refine-3-transport": (9746729075, "567b52a8e66c078c35c12f840738075c9f64aa9deec2772c445ac0d34022676d", "8e82df267a031cedce66286ff18a37b927b76cbf8772c9e5d51822f54c60af73"),
    "rust-refine-3-production-pipeline": (9746729063, "ae1caddbda38616f3bb82f057860a8397dca811f83bd361e2358dc929bb4dc91", "6d0d9224c985cf518efd35b01750373a684fcf2ebbc9994e15e4ced246620749"),
    "rust-refine-3-packaged": (9746722917, "be3e04ce7698d6941101e69b356ee6e7e14130fd306951f060dbbcd12e2e2eb5", "35bd8e69628b858afd3a22548b1e6fa9a6a0c8eb6c9cb69b2724362436404d69"),
    "rust-refine-3-source": (9746824954, "90071c2228135f2dae96c69e8e857f300d8cde7f51fce6661d9c69179d892368", "4ca9c8c12e86e4b980bfea10d8f37ca074ee85987145f8d8adfab5ca52f70688"),
    "rust-refine-3-deep": (9746699856, "c9dad0ff95a2fbfff9daafb05e2cb5fc443bc8416804abbfc8010e54bd66153d", "9442305f1441e6117bb12b98ccd0ef673f25ff6963a72366a941005e10cbedc5"),
    "rust-refine-3-cost": (9746698853, "f8bbf1f30c3a5ab8f7c37b89f9e1bf130aa8a227f97234085f1f363a31df117a", "f48667cf1ac85be07eb532781f938be3acce4cfbeb39f47186eadcf74d6c4a5e"),
    "rust-refine-3-platform-linux-x86_64": (9746730463, "ff3315e13aafc56f05cf064efac5b53992b6baa67bb51106da5ea85ac12d54cb", "5279a77f98691a730bd87a763f9b5ff163fdb0082e64781dd2e235295b3fb76d"),
    "rust-refine-3-platform-windows-x86_64": (9746770964, "9cca873f20f137988ddd4420313b15e67d5f5cf23926bd4ae82267148ab278cb", "218598d112797e0401d24523a92b1d2a70b717425b1e347d51479d47357569d2"),
    "rust-refine-3-platform-macos-x86_64": (9746794858, "22a526d6a9057f3d376544b3544a5c034f6ef9b78d21f11cb0c195f7a5a9e7f5", "7efb3c57660dbb745a0860b8dc3af22630848d7429ea0e0cdd9976b038e878dd"),
    "rust-refine-3-platform-macos-arm64": (9746721663, "59ec58d02fd9bdf12436c0bf587a48d41e5c08892aef5b8b43c8fe81ee8bb3bb", "c1967bae683a6df343867417e085eddbe67f6c32734aca1a80ee2ad09cbfeb7e"),
    "rust-refine-3-python-3.11": (9746730227, "41d332c448caf4ee766329fd5d562d3915847db2ea7ae526267f13132ffae7b7", "51c65938fb4bff27abe4987096acc607bd556774a1ebc146ced8a478cd42cf67"),
    "rust-refine-3-python-3.12": (9746720200, "c30dbd6da497796fd3d9ad0f0e8f398f52c219fea95881d2d7fa24a025df8cef", "df5f82ddb6f0779cef6f45560d1407bec98273cd73d7b9c16f67ac9785590d64"),
    "rust-refine-3-python-3.13": (9746719099, "5b6e0c1f6a430c65b723f8aa6ddb5329b84f683fadd321ca9c00e9445fcc427b", "a4bec8f8363f475774cc61203f36e1ad1b3e69781663675adde260ceb405615e"),
    "rust-refine-3-python-3.14": (9746733788, "dbbb93c63fc5e95f74b58c8408a67c0f70628a4dae9af6f58c8e915ebd79461a", "fef5bf05fa7cd6cc72ffe02921f616507a870818b37676a342efd8258fbcc961"),
}


def check(closure: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    if (
        closure.get("artifact_schema_version") != 1
        or closure.get("milestone") != "RUST-REFINE-3"
        or closure.get("kind") != "formal_authority_promotion_closure"
        or closure.get("closure_revision") != REVISION
    ):
        errors.append("closure identity mismatch")

    run = closure.get("source_run", {})
    if (
        str(run.get("id")) != RUN_ID
        or run.get("revision") != REVISION
        or run.get("workflow") != "rust-refine-3-authority-promotion"
        or run.get("workflow_id") != 346335540
        or run.get("event") != "workflow_dispatch"
        or run.get("attempt") != 1
        or run.get("status") != "completed"
        or run.get("conclusion") != "success"
    ):
        errors.append("official run identity or conclusion mismatch")

    jobs = closure.get("jobs", [])
    indexed_jobs = {
        row.get("name"): row for row in jobs if isinstance(row, dict)
    }
    if set(indexed_jobs) != set(EXPECTED_JOBS):
        errors.append("mandatory job set mismatch")
    for name, job_id in EXPECTED_JOBS.items():
        row = indexed_jobs.get(name, {})
        if row.get("id") != job_id or row.get("conclusion") != "success":
            errors.append(f"job not sealed successful: {name}")

    artifacts = closure.get("artifacts", [])
    indexed_artifacts = {
        row.get("name"): row for row in artifacts if isinstance(row, dict)
    }
    if set(indexed_artifacts) != set(EXPECTED_ARTIFACTS):
        errors.append("mandatory producer artifact set mismatch")
    for name, (artifact_id, zip_hash, evidence_hash) in EXPECTED_ARTIFACTS.items():
        row = indexed_artifacts.get(name, {})
        if (
            row.get("id") != artifact_id
            or row.get("revision") != REVISION
            or str(row.get("run_id")) != RUN_ID
            or row.get("status") != "PASS"
            or row.get("github_digest") != f"sha256:{zip_hash}"
            or row.get("zip_sha256") != zip_hash
            or row.get("evidence_sha256") != evidence_hash
        ):
            errors.append(f"artifact seal mismatch: {name}")

    aggregate = closure.get("aggregate_artifact", {})
    if (
        aggregate.get("id") != 9746832507
        or aggregate.get("name") != "rust-refine-3-aggregate"
        or aggregate.get("github_digest")
        != "sha256:ce7a15047e878ecad9a5e3638225d4f0f826ee79e3644c8b4abb645d90780b6f"
        or aggregate.get("zip_sha256")
        != "ce7a15047e878ecad9a5e3638225d4f0f826ee79e3644c8b4abb645d90780b6f"
        or aggregate.get("manifest_sha256")
        != "979f1b5d4b3a64b1a9963bbb9701fa206362827075512b6103104f1cac101d02"
        or aggregate.get("decision_sha256")
        != "3295b419e772c03462210ff4e13479023e15643af370dc73330b030597eae3be"
    ):
        errors.append("aggregate artifact seal mismatch")

    prerequisite = closure.get("prerequisite", {})
    if (
        str(prerequisite.get("run_id")) != R2_RUN_ID
        or prerequisite.get("revision") != R2_REVISION
        or prerequisite.get("artifact_count") != 19
        or prerequisite.get("official_decision")
        != "RUST_REFINEMENT_SHADOW_QUALIFIED"
        or prerequisite.get("replay_decision")
        != "RUST_REFINEMENT_SHADOW_QUALIFIED"
        or prerequisite.get("independent_decision")
        != "RUST_REFINEMENT_SHADOW_QUALIFIED"
    ):
        errors.append("RUST-REFINE-2 prerequisite seal mismatch")
    if prerequisite.get("historical_failed_runs") != {
        "33319278847": "FAILED/BLOCKED",
        "33321279630": "FAILED/BLOCKED",
        "33360257587": "FAILED/BLOCKED",
    }:
        errors.append("historical failed run was lost or reinterpreted")

    history = closure.get("implementation_history", {})
    if history != {
        "implementation_commit": "1db406d152870602532ab5fbbbb6c62ea75db76e",
        "failed_run": "33360257587",
        "failed_run_status": "FAILED/BLOCKED",
        "corrective_commit_and_qualified_revision": REVISION,
    }:
        errors.append("implementation or failed-run history mismatch")

    if closure.get("api_snapshot_sha256") != {
        "run": "e21ca31a5fee0910a269f5a19180ae2a7651efaea5499ae43b3cd71c35c366e0",
        "jobs": "a2444d09885fd808271d0954ac9fda664b0961c8963670e0b909794f1e188581",
        "artifacts": "1ae513183e20321e541d15941884149a189a313e4c35d94524cec9fc6c7c7ccb",
    }:
        errors.append("GitHub API snapshot seal mismatch")

    decisions = closure.get("decision_recomposition", {})
    decision_hashes: set[str] = set()
    for label in ("official", "replay", "independent"):
        row = decisions.get(label, {})
        if (
            row.get("decision") != PROMOTED
            or row.get("passed") is not True
            or row.get("errors") != 0
        ):
            errors.append(f"{label} aggregate decision mismatch")
        decision_hashes.add(str(row.get("sha256")))
    if decision_hashes != {
        "3295b419e772c03462210ff4e13479023e15643af370dc73330b030597eae3be"
    }:
        errors.append("aggregate decisions are not byte-identical")
    if (
        decisions.get("embedded_zips_byte_identical") is not True
        or decisions.get("manifest_fields_independently_matched") is not True
    ):
        errors.append("independent artifact recomposition mismatch")

    evidence = closure.get("evidence_results", {})
    required_evidence = {
        "contract": "PASS",
        "directed_differential": "PASS",
        "mutation_adversarial": "PASS",
        "production_authority": "PASS",
        "no_python_rescue": "PASS",
        "transport_parity": "PASS",
        "production_pipeline": "PASS",
        "packaged_clean_consumer": "PASS",
        "source_development": "PASS",
        "deep_stress": "PASS",
        "cost_characterization": "PASS",
    }
    if any(evidence.get(name) != value for name, value in required_evidence.items()):
        errors.append("mandatory semantic evidence is not PASS")
    if (
        evidence.get("rust_accept_python_reject") != 0
        or evidence.get("rust_reject_python_accept") != 0
        or evidence.get("acceptance_divergences") != 0
        or evidence.get("valid_acceptance_regressions") != 0
        or evidence.get("accepted_mutations") != 0
    ):
        errors.append("acceptance or mutation safety gate failed")
    if (
        evidence.get("directed_cases") != 223
        or evidence.get("property_generated_cases") != 71
        or evidence.get("mutation_cases") != 403
        or evidence.get("mutations_rejected_by_both") != 403
        or evidence.get("productive_categories") != 15
        or evidence.get("deep_cfg_blocks") != 5000
        or evidence.get("cost_samples") != 4
        or evidence.get("cost_threshold_enforced") is not False
        or evidence.get("universal_speedup_claimed") is not False
        or evidence.get("source_full_suite")
        != {
            "passed": 5204,
            "skipped": 12,
            "warnings": 1,
            "log_sha256": "3b5666778035f20718ec50647a8de747b5f8b2ac7253c05a4f908a7c3239d83b",
        }
    ):
        errors.append("campaign counts, cost policy, or full-suite seal mismatch")

    transports = closure.get("transport_matrix", [])
    if {
        (
            row.get("requested"),
            row.get("observed"),
            row.get("status"),
            row.get("automatic_fallback"),
        )
        for row in transports
    } != {
        ("in_process", "in_process", "PASS", False),
        ("companion", "companion", "PASS", False),
    }:
        errors.append("transport matrix mismatch")

    packaged = closure.get("packaged_clean_consumer", {})
    if packaged != {
        "status": "PASS",
        "checkout_importable": False,
        "cargo_required": False,
        "rustc_required": False,
        "exact_dependency_resolution": True,
        "binding_available": True,
        "companion_available": True,
        "both_transports": True,
    }:
        errors.append("packaged clean-consumer seal mismatch")

    platforms = closure.get("platform_matrix", [])
    if {
        (
            row.get("platform"),
            row.get("target"),
            row.get("python_patch"),
            row.get("status"),
        )
        for row in platforms
    } != {
        ("linux-x86_64", "x86_64-unknown-linux-gnu", "3.13.15", "PASS"),
        ("windows-x86_64", "x86_64-pc-windows-msvc", "3.13.15", "PASS"),
        ("macos-x86_64", "x86_64-apple-darwin", "3.13.15", "PASS"),
        ("macos-arm64", "aarch64-apple-darwin", "3.13.14", "PASS"),
    }:
        errors.append("platform matrix mismatch")
    pythons = closure.get("python_matrix", [])
    if {
        (row.get("minor"), row.get("patch"), row.get("status"))
        for row in pythons
    } != {
        ("3.11", "3.11.16", "PASS"),
        ("3.12", "3.12.14", "PASS"),
        ("3.13", "3.13.15", "PASS"),
        ("3.14", "3.14.7", "PASS"),
    }:
        errors.append("Python matrix mismatch")

    authority = closure.get("authority_provenance", {})
    if (
        authority.get("productive_refinement_authority") != "rust"
        or authority.get("rust_refinement_verification_observed") is not True
        or authority.get("productive_python_refinement_role") != "not_executed"
        or authority.get("qualification_python_refinement_role") != "oracle_only"
        or authority.get("python_refinement_productive") is not False
        or authority.get("python_rescue_attempted") is not False
        or authority.get("automatic_fallback") is not False
        or authority.get("derived_from_case_traces") is not True
        or authority.get("constant_only_evidence") is not False
        or authority.get("python_refinement_implementation_retained") is not True
        or authority.get("python_ssa_verifier_retained") is not True
    ):
        errors.append("authority provenance mismatch")

    eligibility = closure.get("promotion_eligibility", {})
    checks = eligibility.get("checks", {})
    required_checks = {
        "prerequisite_rust_refine_2_revalidated",
        "all_21_jobs_success",
        "all_21_artifacts_official_and_hashed",
        "official_aggregate_promoted",
        "official_replay_promoted",
        "independent_recomposition_promoted",
        "rust_productive_authority_observed",
        "python_refinement_oracle_only",
        "zero_acceptance_divergences",
        "zero_valid_acceptance_regressions",
        "no_python_rescue_or_fallback",
        "clean_packaged_consumer",
        "both_transports",
        "complete_platform_matrix",
        "complete_python_matrix",
        "python_ssa_verifier_retained",
    }
    if (
        eligibility.get("eligible") is not True
        or eligibility.get("blockers") != []
        or set(checks) != required_checks
        or not all(value is True for value in checks.values())
    ):
        errors.append("promotion eligibility is incomplete")
    if closure.get("final_decision") != PROMOTED:
        errors.append("closure final decision mismatch")

    decision = PROMOTED if not errors else BLOCKED
    return {"decision": decision, "passed": not errors, "errors": errors}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--closure",
        type=Path,
        default=Path(__file__).resolve().parents[1]
        / "docs/compiler/rust_refine_3_authority_promotion_closure_a5ae9d4b.json",
    )
    args = parser.parse_args()
    try:
        closure = json.loads(args.closure.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        result = {"decision": BLOCKED, "passed": False, "errors": [str(error)]}
    else:
        result = check(closure)
    print(result["decision"])
    for error in result["errors"]:
        print(f"BLOCKED: {error}")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
