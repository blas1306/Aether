#!/usr/bin/env python3
"""Qualify Python SSA -> schema-v2 -> Rust owned SSA -> schema-v2 -> Python SSA."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from aether.pipeline import IRBackend, prepare_typed_program
from aether.ssa.dto import _INSTRUCTION_TYPES, ssa_module_from_dto, ssa_module_to_dto
from aether.ssa.general_builder import GeneralSSABuilder
from aether.typechecker import TypeChecker

OUTPUT = ROOT / "docs/compiler/rust_owned_ssa_model_qualification.json"
BINARY = ROOT / "compiler-rs/target/debug/examples/ssa_owned_roundtrip"


def discover() -> list[Path]:
    roots = [ROOT / "examples", ROOT / "benchmarks", ROOT / "corpus/exceptions"]
    return sorted({path for root in roots for path in root.rglob("*.ae")})


def generate() -> dict[str, object]:
    subprocess.run(["cargo", "build", "-p", "aether-ir", "--example", "ssa_owned_roundtrip"],
                   cwd=ROOT / "compiler-rs", check=True, stdout=subprocess.DEVNULL)
    rows: list[dict[str, object]] = []
    for path in discover():
        try:
            source = path.read_text(encoding="utf-8")
            typed = prepare_typed_program(source, TypeChecker(source_root=path.parent))
            initial = IRBackend().lower_verified(typed)
            built = GeneralSSABuilder().build(initial)
        except Exception:
            continue
        dto = ssa_module_to_dto(built)
        encoded = json.dumps(dto, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        run = subprocess.run([BINARY], input=encoded, capture_output=True)
        passed = False
        error = None
        if run.returncode == 0:
            returned = json.loads(run.stdout)
            passed = returned == dto and ssa_module_from_dto(returned) == built
            if not passed:
                error = "structural or Python semantic comparison failed"
        else:
            error = run.stderr.decode(errors="replace")[:300]
        rows.append({"path": path.relative_to(ROOT).as_posix(), "passed": passed,
                     **({"error": error} if error else {})})
    passed = sum(row["passed"] for row in rows)
    inventory = sorted(_INSTRUCTION_TYPES)
    decision = "RUST_OWNED_SSA_MODEL_QUALIFIED" if passed == len(rows) and len(inventory) == 77 else "RUST_OWNED_SSA_MODEL_BLOCKED"
    return {
        "evidence_schema_version": 1,
        "audit": "RUST-3.C-rust-owned-SSA-model",
        "decision": decision,
        "instruction_count": len(inventory),
        "instruction_inventory": inventory,
        "corpus": {"verified_python_ssa_denominator": len(rows), "passed": passed,
                   "failed": len(rows) - passed, "files": rows},
        "codec": {"path": "Python SSA -> schema-v2 -> Rust owned SSA -> schema-v2 -> Python SSA",
                  "deterministic_ordered_collections": True, "schema_v1_policy_changed": False},
        "scope": {"rust_ssa_lowering_implemented": False, "authority_changed": False,
                  "ssa_semantics_changed": False},
    }


def main() -> int:
    report = generate()
    rendered = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if "--check" in sys.argv:
        if not OUTPUT.exists() or OUTPUT.read_text(encoding="utf-8") != rendered:
            print("stale Rust owned SSA qualification evidence")
            return 1
    else:
        OUTPUT.write_text(rendered, encoding="utf-8")
    print(f"{report['decision']}: {report['corpus']['passed']}/{report['corpus']['verified_python_ssa_denominator']}")
    return 0 if report["decision"] == "RUST_OWNED_SSA_MODEL_QUALIFIED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
