#!/usr/bin/env python3
"""Check the deterministic contracts of the frozen O2 profile (no benchmarks)."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from aether.optimization import IR_O1_PASSES, PROFILES, SSA_O1_PASSES, SSA_O2_PASSES, OptimizationLevel

EXPECTED_IR = [
    "ConstantFolder", "LocalConstantPropagator", "ConstantFolder",
    "AlgebraicSimplifier", "DeadCodeEliminator", "DeadStoreEliminator",
    "DeadCodeEliminator",
]
EXPECTED_SSA_O1 = [
    "SSAConstantFolder", "SSAGlobalConstantPropagator",
    "SSAAlgebraicSimplifier", "SCCPPass", "TrivialPhiEliminator",
    "DeadPhiEliminator", "SSADeadCodeEliminator",
]
EXPECTED_O2_SUFFIX = [
    "ProvenBoundsCheckEliminator", "LoopInvariantCodeMotion",
    "OwnershipElidedArrayGet", "LocalARCEliminator",
    "SSADeadCodeEliminator",
]
FINAL_DECISIONS = {"O2_FREEZE_QUALIFIED", "O2_FREEZE_BLOCKED"}


def _require(condition: bool, message: str, errors: list[str]) -> None:
    if not condition:
        errors.append(message)


def check(root: Path = ROOT, *, regenerate: bool = True) -> list[str]:
    errors: list[str] = []
    artifact_path = root / "docs/compiler/o2_qualification.json"
    freeze_path = root / "docs/compiler/O2_OPTIMIZATION_PROFILE_FREEZE.md"
    manifest_path = root / "benchmarks/o2_workloads.json"
    baseline_path = root / "docs/compiler/o2_measurement_baseline.json"
    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    artifact_text = artifact_path.read_text(encoding="utf-8")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    freeze = freeze_path.read_text(encoding="utf-8")

    _require(list(IR_O1_PASSES) == EXPECTED_IR, "IR O1 order changed", errors)
    _require(list(SSA_O1_PASSES) == EXPECTED_SSA_O1, "SSA O1 order changed", errors)
    _require(list(SSA_O2_PASSES) == EXPECTED_SSA_O1 + EXPECTED_O2_SUFFIX, "SSA O2 order changed", errors)
    expected = {
        "O0": {"ir_passes": [], "ssa_passes": [], "clang_level": "0"},
        "O1": {"ir_passes": EXPECTED_IR, "ssa_passes": EXPECTED_SSA_O1, "clang_level": "1"},
        "O2": {"ir_passes": EXPECTED_IR, "ssa_passes": EXPECTED_SSA_O1 + EXPECTED_O2_SUFFIX, "clang_level": "2"},
    }
    actual = {level.value: {"ir_passes": list(profile.ir_passes), "ssa_passes": list(profile.ssa_passes), "clang_level": profile.clang_level}
              for level, profile in PROFILES.items()}
    _require(actual == expected, "production profiles disagree with frozen membership", errors)
    _require(artifact.get("schema_version") == 1, "qualification schema_version must be 1", errors)
    _require(artifact.get("pipelines") == expected, "qualification pipeline snapshot is stale", errors)
    _require(artifact.get("final_decision") in FINAL_DECISIONS, "invalid final decision", errors)
    _require(artifact.get("reopen_criteria_version") == 1, "unknown reopen policy", errors)
    _require(artifact_text == json.dumps(artifact, indent=2, sort_keys=True) + "\n",
             "qualification artifact is not canonical deterministic JSON", errors)
    if artifact.get("final_decision") == "O2_FREEZE_QUALIFIED":
        _require(artifact.get("sanitizers", {}).get("status") == "PASS", "qualified freeze requires sanitizer PASS", errors)
        _require(artifact.get("exception_gate", {}).get("status") == "PASS", "qualified freeze requires native ERQ-006 PASS", errors)
        _require(artifact.get("python_suite", {}).get("status") == "PASS", "qualified freeze requires full Python PASS", errors)
        _require(artifact.get("packaging", {}).get("status") == "PASS", "qualified freeze requires packaging PASS", errors)

    workloads = manifest.get("workloads", [])
    paths = [row.get("path") for row in workloads]
    _require(len(workloads) == 30 and len(set(paths)) == 30, "workload corpus must contain 30 unique entries", errors)
    _require(all((root / path).is_file() for path in paths), "workload manifest contains a missing path", errors)
    corpus = baseline.get("corpus", {})
    _require(corpus.get("workloads") == 30 and corpus.get("supported_ssa") == 26 and len(corpus.get("unsupported", [])) == 4,
             "static baseline corpus is not the frozen 30/26/4 contract", errors)
    digest = hashlib.sha256(baseline_path.read_bytes()).hexdigest()
    _require(artifact.get("static_baseline", {}).get("sha256") == digest, "static baseline hash mismatch", errors)
    for phrase in ("O2_FREEZE_", "TRANSFORMABLE_NOW", "HYPOTHESIS_ONLY", "higher optimization profile", "LLVM"):
        _require(phrase in freeze, f"freeze document missing policy phrase: {phrase}", errors)
    for historical in artifact.get("historical_artifacts", []):
        _require((root / historical).is_file(), f"missing historical artifact: {historical}", errors)

    if regenerate:
        with tempfile.TemporaryDirectory(prefix="aether-o2-final-") as directory:
            generated = Path(directory) / "baseline.json"
            proc = subprocess.run([sys.executable, str(root / "scripts/o2_measurement.py"), "--mode", "static-only", "--output", str(generated)],
                                  cwd=root, text=True, capture_output=True)
            _require(proc.returncode == 0, f"static regeneration failed: {proc.stderr.strip()}", errors)
            if proc.returncode == 0:
                _require(generated.read_bytes() == baseline_path.read_bytes(), "static baseline is not byte-for-byte reproducible", errors)
    return errors


def main() -> int:
    errors = check(regenerate="--no-regenerate" not in sys.argv[1:])
    if errors:
        for error in errors:
            print(f"FAIL: {error}")
        print("O2_FREEZE_BLOCKED")
        return 1
    print("O2 qualification static contracts: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
