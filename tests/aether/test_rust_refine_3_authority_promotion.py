from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import zipfile

import pytest

from aether.ir.model import IRModule
from aether.pipeline import SSAPipeline
from aether.ssa.dto import ssa_module_to_dto
from aether.ssa.model import SSAModule
from aether.ssa.shadow_independent import (
    ShadowIndependentRustAuthorityFailure,
    lower_with_shadow_independent_rust_authority,
    qualify_shadow_independent_rust_ssa,
)


ROOT = Path(__file__).resolve().parents[2]
CHECKER = ROOT / "scripts/check_rust_refine_3_authority_promotion.py"
WORKFLOW = ROOT / ".github/workflows/rust-refine-authority-promotion.yml"
QUALIFIER = ROOT / "scripts/qualify_rust_refine_3_authority_promotion.py"
PROBE = ROOT / "scripts/rust_refine_3_product_probe.py"
REVISION = "1" * 40
RUN_ID = "12345"
PLATFORMS = ("linux-x86_64", "windows-x86_64", "macos-x86_64", "macos-arm64")
PYTHONS = ("3.11", "3.12", "3.13", "3.14")


def _load_checker():
    spec = importlib.util.spec_from_file_location("rust_refine_3_checker", CHECKER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_path(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class StaticClient:
    def __init__(self, responses: list[dict[str, object]] | None = None) -> None:
        success = {
            "ok": True,
            "ssa": ssa_module_to_dto(SSAModule(), schema_version=2),
        }
        self.responses = list(responses or [success])
        self.last = success

    def lower(self, _payload: bytes) -> dict[str, object]:
        if self.responses:
            self.last = self.responses.pop(0)
        return deepcopy(self.last)


def test_productive_refinement_authority_is_rust_and_python_is_not_called(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def reject(*_args: object, **_kwargs: object) -> None:
        nonlocal calls
        calls += 1
        raise AssertionError("Python refinement entered productive acceptance")

    monkeypatch.setattr(
        "aether.ssa.shadow_independent.verify_ssa_refinement",
        reject,
    )
    ssa, trace = lower_with_shadow_independent_rust_authority(
        IRModule(),
        StaticClient(),
    )
    assert ssa.functions == []
    assert calls == 0
    assert trace.refinement_authority == "rust"
    assert trace.rust_refinement_verification_observed is True
    assert trace.python_refinement_role == "not_executed"
    assert trace.python_refinement_verification_executed is False
    assert trace.stage_execution_counts["imported_ssa_verification"] == 1
    assert trace.final_generic_verification_executed is True


def test_python_refinement_remains_an_explicit_qualification_oracle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def accept(_initial: object, ssa: object) -> object:
        nonlocal calls
        calls += 1
        return ssa

    monkeypatch.setattr(
        "aether.ssa.shadow_independent.verify_ssa_refinement",
        accept,
    )
    _ssa, trace = qualify_shadow_independent_rust_ssa(
        IRModule(),
        StaticClient(),
    )
    assert calls == 1
    assert trace.refinement_authority == "rust"
    assert trace.python_refinement_role == "oracle_only"
    assert trace.python_refinement_verification_executed is True
    assert trace.stage_execution_counts["python_refinement_oracle"] == 1


def test_rust_rejection_is_final_no_python_rescue_and_next_request_recovers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def rescue(*_args: object, **_kwargs: object) -> None:
        nonlocal calls
        calls += 1

    monkeypatch.setattr(
        "aether.ssa.shadow_independent.verify_ssa_refinement",
        rescue,
    )
    success = {
        "ok": True,
        "ssa": ssa_module_to_dto(SSAModule(), schema_version=2),
    }
    client = StaticClient(
        [
            {
                "ok": False,
                "error": "Rust refinement rejected",
                "diagnostic": {
                    "category": "ssa_refinement_verification",
                    "code": "SSA-REFINE-TEST",
                },
            },
            success,
        ]
    )
    with pytest.raises(ShadowIndependentRustAuthorityFailure) as caught:
        SSAPipeline(rust_shadow_client=client).run(IRModule())
    assert caught.value.trace.failed_stage == "rust_ssa_lowering_and_verification"
    rejection = json.loads(caught.value.detail)
    assert rejection["diagnostic"]["category"] == "ssa_refinement_verification"
    assert rejection["diagnostic"]["code"] == "SSA-REFINE-TEST"
    assert calls == 0
    result = SSAPipeline(rust_shadow_client=client).run(IRModule())
    assert result.ssa_module.functions == []
    assert calls == 0


def test_product_probe_lowers_typed_program_before_explicit_oracle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: list[IRModule] = []

    def qualify(initial: IRModule, _client: object):
        assert isinstance(initial, IRModule)
        observed.append(initial)
        return SSAModule(), SimpleNamespace(
            accepted=True,
            refinement_authority="rust",
            python_refinement_role="oracle_only",
            python_refinement_verification_executed=True,
        )

    monkeypatch.setattr(
        "aether.ssa.shadow_independent.qualify_shadow_independent_rust_ssa",
        qualify,
    )
    probe = _load_path("rust_refine_3_product_probe_test", PROBE)
    result = probe._qualification_oracle(probe.SCALAR_SOURCE, ROOT, object())
    assert len(observed) == 1
    assert result["accepted"] is True
    assert result["python_refinement_role"] == "oracle_only"


def test_stdlib_only_gates_do_not_import_differential_dependencies(
    tmp_path: Path,
) -> None:
    decision = tmp_path / "r2-decision.json"
    api = tmp_path / "r2-artifacts.json"
    decision.write_text(
        json.dumps(
            {
                "decision": "RUST_REFINEMENT_SHADOW_QUALIFIED",
                "passed": True,
                "run_id": "33321791729",
                "revision": "0bff8c0a78005d97ee5c7c2e0eb09a6a6b3b1fef",
            }
        ),
        encoding="utf-8",
    )
    api.write_text(
        json.dumps(
            {
                "artifacts": [
                    {
                        "id": index,
                        "digest": f"sha256:{index:064x}",
                    }
                    for index in range(1, 20)
                ]
            }
        ),
        encoding="utf-8",
    )
    for mode, extra in (
        ("contract", []),
        (
            "prerequisite",
            [
                "--prerequisite-decision",
                str(decision),
                "--prerequisite-artifacts-api",
                str(api),
            ],
        ),
    ):
        completed = subprocess.run(
            [
                sys.executable,
                "-S",
                str(QUALIFIER),
                "--mode",
                mode,
                "--revision",
                REVISION,
                "--run-id",
                RUN_ID,
                "--output",
                str(tmp_path / f"{mode}.json"),
                *extra,
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        assert completed.returncode == 0, completed.stderr
def _base(kind: str) -> dict[str, object]:
    return {
        "artifact_schema_version": 1,
        "milestone": "RUST-REFINE-3",
        "kind": kind,
        "revision": REVISION,
        "run_id": RUN_ID,
        "status": "PASS",
        "passed": True,
    }


def _product(kind: str) -> dict[str, object]:
    case = {
        "accepted": True,
        "returned_ssa_origin": "rust_schema_v2_import",
        "refinement_authority": "rust",
        "rust_refinement_verification_observed": True,
        "python_refinement_role": "not_executed",
        "python_refinement_verification_executed": False,
        "python_ssa_verifier_executed": True,
    }
    return {
        **_base(kind),
        "cases": [case],
        "python_refinement_absence": {
            "compilation_accepted": True,
            "python_refinement_calls": 0,
            "python_rejection_could_block": False,
        },
        "no_python_rescue": {
            "rust_rejection_blocked": True,
            "python_refinement_calls": 0,
            "python_rescue_attempted": False,
            "subsequent_recovery_succeeded": True,
            "automatic_fallback": False,
            "structured_error": {
                "classification": "rust_lowering_or_verifier_failure",
                "diagnostic": {
                    "category": "ssa_refinement_verification",
                    "code": "SSA-REFINE-TEST",
                },
            },
        },
        "full_backend": {
            "accepted": True,
            "llvm_generated": True,
            "returncode": 0,
        },
        "authority_provenance": {
            "refinement_authority": "rust",
            "python_refinement_role": "not_executed",
            "derived_from_case_traces": True,
            "constant_only_evidence": False,
        },
    }


def _environment(kind: str, role: str, platform: str, python: str) -> dict[str, object]:
    valid = {
        "accepted": True,
        "refinement_authority": "rust",
        "rust_refinement_verification_observed": True,
        "python_refinement_verification_executed": False,
    }
    rescue = {
        "rust_rejection_blocked": True,
        "python_rescue_attempted": False,
    }
    oracle = {
        "accepted": True,
        "refinement_authority": "rust",
        "python_refinement_role": "oracle_only",
        "python_refinement_verification_executed": True,
    }
    rows = [
        {
            "requested_transport": value,
            "observed_transport": value,
            "automatic_fallback": False,
            "valid_case": valid,
            "no_python_rescue": rescue,
            "qualification_oracle": oracle,
        }
        for value in ("in_process", "companion")
    ]
    targets = {
        "linux-x86_64": "x86_64-unknown-linux-gnu",
        "windows-x86_64": "x86_64-pc-windows-msvc",
        "macos-x86_64": "x86_64-apple-darwin",
        "macos-arm64": "aarch64-apple-darwin",
    }
    return {
        **_base(kind),
        "role": role,
        "platform": platform,
        "python_minor": python,
        "python_patch": f"{python}.9",
        "transport_rows": rows,
        "product_binding": True,
        "companion_installed": True,
        "exact_dependency_resolution": True,
        "native_manifest": {"target": targets[platform]},
        "authority_provenance": {
            "refinement_authority": "rust",
            "python_refinement_role": "not_executed",
            "derived_from_case_traces": True,
        },
        "checkout_importable": kind == "source_development",
        "cargo_required_by_consumer": kind == "source_development",
        "rustc_required_by_consumer": kind == "source_development",
        "wheels": [{}, {}],
        "full_python_suite": "PASS" if kind == "source_development" else None,
    }


def _valid_records() -> dict[str, dict[str, object]]:
    records: dict[str, dict[str, object]] = {
        "rust-refine-3-prerequisite": {
            **_base("prerequisite"),
            "prerequisite": {
                "decision": "RUST_REFINEMENT_SHADOW_QUALIFIED",
                "run_id": "33321791729",
                "revision": "0bff8c0a78005d97ee5c7c2e0eb09a6a6b3b1fef",
                "official_artifact_count": 19,
            },
            "historical_runs": {
                "33319278847": "FAILED/BLOCKED",
                "33321279630": "FAILED/BLOCKED",
            },
        },
        "rust-refine-3-contract": {
            **_base("authority_contract"),
            "promoted_productive_refinement_authority": "rust",
            "python_ssa_verifier_retired": False,
            "python_refinement_implementation_deleted": False,
            "unexplained_semantic_contract_differences": [],
            "checks": {"all": True},
        },
        "rust-refine-3-differential": {
            **_base("directed_differential"),
            "case_count": 223,
            "property_generated_case_count": 71,
            "rust_accept_python_reject": [],
            "rust_reject_python_accept": [],
            "acceptance_divergences": [],
            "known_input_domain_divergence_fail_closed": True,
        },
        "rust-refine-3-mutations": {
            **_base("mutation_adversarial"),
            "deterministic": True,
            "generated_case_count": 403,
            "both_reject_count": 403,
            "rust_accept_python_reject": [],
            "rust_reject_python_accept": [],
            "accepted_mutations": [],
        },
        "rust-refine-3-production-authority": _product("production_authority"),
        "rust-refine-3-no-python-rescue": _product("no_python_rescue"),
        "rust-refine-3-production-pipeline": _product("production_pipeline"),
        "rust-refine-3-transport": {
            **_base("transport_parity"),
            "rows": [
                {
                    "requested_transport": value,
                    "observed_transport": value,
                    "status": "PASS",
                    "valid_output_sha256": "a" * 64,
                    "rejection_classification": "rust_lowering_or_verifier_failure",
                    "automatic_fallback": False,
                }
                for value in ("in_process", "companion")
            ],
        },
        "rust-refine-3-packaged": _environment(
            "packaged_clean_consumer", "dedicated", "linux-x86_64", "3.13"
        ),
        "rust-refine-3-source": _environment(
            "source_development", "source", "linux-x86_64", "3.13"
        ),
        "rust-refine-3-deep": {
            **_base("deep_stress"),
            "initial_ir_blocks": 5000,
            "ssa_blocks": 5000,
            "rust_result": "accept",
            "python_result": "accept",
        },
        "rust-refine-3-cost": {
            **_base("cost_characterization"),
            "samples": [{}, {}, {}, {}],
            "threshold_enforced": False,
            "universal_speedup_claimed": False,
        },
    }
    for platform in PLATFORMS:
        records[f"rust-refine-3-platform-{platform}"] = _environment(
            "platform_qualification", "platform", platform, "3.13"
        )
    for version in PYTHONS:
        records[f"rust-refine-3-python-{version}"] = _environment(
            "python_compatibility", "python_compatibility", "linux-x86_64", version
        )
    return records


def _manifest(root: Path) -> Path:
    checker = _load_checker()
    records = _valid_records()
    entries = []
    for index, (name, (job, kind)) in enumerate(checker.expected().items(), 1):
        evidence = root / "downloaded" / name / "evidence.json"
        evidence.parent.mkdir(parents=True, exist_ok=True)
        evidence.write_text(json.dumps(records[name]), encoding="utf-8")
        archive = root / "zips" / f"{name}.zip"
        archive.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(archive, "w") as bundle:
            bundle.write(evidence, "evidence.json")
        archive_hash = sha256(archive.read_bytes()).hexdigest()
        entries.append(
            {
                "artifact_id": index,
                "name": name,
                "source_job": job,
                "kind": kind,
                "run_id": RUN_ID,
                "revision": REVISION,
                "status": "PASS",
                "github_digest": f"sha256:{archive_hash}",
                "downloaded_zip": archive.relative_to(root).as_posix(),
                "downloaded_zip_sha256": archive_hash,
                "extracted_evidence": evidence.relative_to(root).as_posix(),
                "extracted_evidence_sha256": sha256(evidence.read_bytes()).hexdigest(),
            }
        )
    jobs = {job: "success" for job, _kind in checker.BASE.values()}
    jobs.update({"platform-qualification": "success", "python-compatibility": "success"})
    manifest = {
        "artifact_schema_version": 1,
        "milestone": "RUST-REFINE-3",
        "kind": "official_artifact_manifest",
        "revision": REVISION,
        "run_id": RUN_ID,
        "job_results": jobs,
        "artifacts": entries,
        "aggregate_claim": "RUST_REFINEMENT_AUTHORITY_PROMOTED",
    }
    path = root / "artifact-manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return path


def test_checker_accepts_complete_authority_evidence(tmp_path: Path) -> None:
    result = _load_checker().check(_manifest(tmp_path))
    assert result["decision"] == "RUST_REFINEMENT_AUTHORITY_PROMOTED"
    assert result["errors"] == []


@pytest.mark.parametrize(
    ("corruption", "expected"),
    [
        ("wrong_run", "wrong run"),
        ("wrong_revision", "wrong revision"),
        ("wrong_kind", "wrong artifact kind"),
        ("wrong_digest", "GitHub digest mismatch"),
        ("failed_job", "mandatory job missing"),
        ("invalid_prerequisite", "prerequisite is invalid"),
        ("python_authority", "Python refinement remains productive"),
        ("rust_authority_absent", "invalid authority case provenance"),
        ("rust_accept_python_reject", "directed differential failed"),
        ("rust_reject_python_accept", "directed differential failed"),
        ("mutation_accepted", "mutation/adversarial campaign failed"),
        ("fallback", "Rust rejection was rescued"),
        ("missing_platform", "mandatory artifact set mismatch"),
        ("missing_python", "mandatory artifact set mismatch"),
        ("missing_clean_consumer", "mandatory artifact set mismatch"),
        ("incomplete_provenance", "incomplete authority provenance"),
    ],
)
def test_checker_blocks_adversarial_corruption(
    tmp_path: Path,
    corruption: str,
    expected: str,
) -> None:
    checker = _load_checker()
    path = _manifest(tmp_path)
    manifest = json.loads(path.read_text(encoding="utf-8"))
    missing = {
        "missing_platform": "rust-refine-3-platform-macos-arm64",
        "missing_python": "rust-refine-3-python-3.14",
        "missing_clean_consumer": "rust-refine-3-packaged",
    }
    if corruption in missing:
        manifest["artifacts"] = [
            row
            for row in manifest["artifacts"]
            if row["name"] != missing[corruption]
        ]
    elif corruption == "failed_job":
        manifest["job_results"]["authority-contract"] = "failure"
    else:
        target_name = {
            "invalid_prerequisite": "rust-refine-3-prerequisite",
            "python_authority": "rust-refine-3-production-authority",
            "rust_authority_absent": "rust-refine-3-production-authority",
            "rust_accept_python_reject": "rust-refine-3-differential",
            "rust_reject_python_accept": "rust-refine-3-differential",
            "mutation_accepted": "rust-refine-3-mutations",
            "fallback": "rust-refine-3-no-python-rescue",
            "incomplete_provenance": "rust-refine-3-production-authority",
        }.get(corruption, "rust-refine-3-contract")
        row = next(item for item in manifest["artifacts"] if item["name"] == target_name)
        evidence = path.parent / row["extracted_evidence"]
        record = json.loads(evidence.read_text(encoding="utf-8"))
        if corruption == "wrong_run":
            row["run_id"] = "999"
        elif corruption == "wrong_revision":
            row["revision"] = "2" * 40
        elif corruption == "wrong_kind":
            row["kind"] = "wrong"
        elif corruption == "wrong_digest":
            row["github_digest"] = "sha256:" + "0" * 64
        elif corruption == "invalid_prerequisite":
            record["prerequisite"]["decision"] = (
                "RUST_REFINEMENT_SHADOW_QUALIFICATION_BLOCKED"
            )
        elif corruption == "python_authority":
            record["python_refinement_absence"]["python_refinement_calls"] = 1
        elif corruption == "rust_authority_absent":
            record["cases"][0]["rust_refinement_verification_observed"] = False
        elif corruption == "rust_accept_python_reject":
            record["rust_accept_python_reject"] = [{"seed": "bad"}]
        elif corruption == "rust_reject_python_accept":
            record["rust_reject_python_accept"] = [{"seed": "bad"}]
        elif corruption == "mutation_accepted":
            record["accepted_mutations"] = [{"seed": "bad"}]
        elif corruption == "fallback":
            record["no_python_rescue"]["python_rescue_attempted"] = True
        elif corruption == "incomplete_provenance":
            record["authority_provenance"]["derived_from_case_traces"] = False
        if record != json.loads(evidence.read_text(encoding="utf-8")):
            evidence.write_text(json.dumps(record), encoding="utf-8")
            row["extracted_evidence_sha256"] = sha256(evidence.read_bytes()).hexdigest()
    path.write_text(json.dumps(manifest), encoding="utf-8")
    result = checker.check(path)
    assert result["decision"] == "RUST_REFINEMENT_AUTHORITY_PROMOTION_BLOCKED"
    assert any(expected in error for error in result["errors"])


def test_workflow_has_all_mandatory_gates_and_is_dispatch_only() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")
    assert "workflow_dispatch:" in source
    for gate in (
        "prerequisite-rust-refine-2",
        "authority-contract",
        "directed-differential",
        "mutation-adversarial",
        "production-authority",
        "no-python-rescue",
        "transport-parity",
        "production-pipeline",
        "packaged-clean-consumer",
        "source-development",
        "deep-stress",
        "cost-characterization",
        "platform-qualification",
        "python-compatibility",
        "aggregate-fail-closed",
    ):
        assert f"  {gate}:" in source
    assert "33321791729" in source
    assert "check_rust_refine_3_authority_promotion.py" in source
