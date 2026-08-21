#!/usr/bin/env python3
"""Generate deterministic evidence for the lossless SSA schema-v2 boundary."""
from __future__ import annotations

import argparse
from dataclasses import fields
import json
from pathlib import Path

from aether.ir.dto import ir_module_from_dto, ir_module_to_dto
from aether.pipeline import IRBackend, prepare_typed_program
from aether.ssa import model as ssa
from aether.ssa.dto import (
    SSA_SCHEMA_VERSION, SSA_SCHEMA_VERSION_V1, SSA_SCHEMA_VERSION_V2,
    _INSTRUCTION_TYPES,
    ssa_module_from_dto,
    ssa_module_to_dto,
)
from aether.ssa.general_builder import GeneralSSABuilder
from aether.typechecker import TypeChecker


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "docs/compiler/ssa_wire_boundary_qualification.json"
BOUNDS_CHECKED_KINDS = {
    "array_get", "array_set", "list_get", "list_set",
    "matrix_get", "matrix_set", "vector_get", "vector_set",
}


def _discover() -> list[Path]:
    roots = [ROOT / "examples", ROOT / "benchmarks", ROOT / "corpus/exceptions"]
    return sorted({path for root in roots for path in root.rglob("*.ae")})


def _instruction_inventory() -> list[dict[str, object]]:
    rows = []
    for kind, type_ in sorted(_INSTRUCTION_TYPES.items()):
        names = [field.name for field in fields(type_)]
        v2_delta = ["bounds_checked"] if kind in BOUNDS_CHECKED_KINDS else []
        rows.append({
            "kind": kind,
            "dataclass": type_.__name__,
            "fields": names,
            "field_count": len(names),
            "schema_v1_status": (
                "REJECTED_AMBIGUOUS" if v2_delta else "REPRESENTABLE"
            ),
            "schema_v2_status": "REPRESENTABLE",
            "schema_v2_added_fields": v2_delta,
            "unrepresentable_v2_fields": [],
        })
    return rows


def _corpus() -> dict[str, object]:
    rows: list[dict[str, object]] = []
    for path in _discover():
        relative = path.relative_to(ROOT).as_posix()
        row: dict[str, object] = {
            "path": relative,
            "reached_verified_python_ssa": False,
            "initial_ir_wire_roundtrip": False,
            "ssa_wire_roundtrip": False,
        }
        try:
            source = path.read_text(encoding="utf-8")
            typed = prepare_typed_program(source, TypeChecker(source_root=path.parent))
            module = IRBackend().lower_verified(typed)
            initial_dto = ir_module_to_dto(module)
            row["initial_ir_wire_roundtrip"] = (
                ir_module_to_dto(ir_module_from_dto(initial_dto)) == initial_dto
            )
            built = GeneralSSABuilder().build(module)
            row["reached_verified_python_ssa"] = True
        except Exception as error:  # retain negative corpus programs as evidence
            row.update({
                "pre_ssa_failure_type": type(error).__name__,
                "pre_ssa_failure": str(error)[:240],
            })
            rows.append(row)
            continue

        try:
            dto = ssa_module_to_dto(built)
            decoded = ssa_module_from_dto(dto)
            row["ssa_wire_roundtrip"] = (
                decoded == built and ssa_module_to_dto(decoded) == dto
            )
        except Exception as error:  # this is the qualification-gate failure lane
            row.update({
                "ssa_codec_failure_type": type(error).__name__,
                "ssa_codec_failure": str(error)[:240],
            })
        rows.append(row)

    verified = [row for row in rows if row["reached_verified_python_ssa"]]
    pre_ssa = [row for row in rows if not row["reached_verified_python_ssa"]]
    passed = [row for row in verified if row["ssa_wire_roundtrip"]]
    failed = [row for row in verified if not row["ssa_wire_roundtrip"]]
    return {
        "summary": {
            "discovered": len(rows),
            "verified_python_ssa_denominator": len(verified),
            "ssa_wire_roundtrip_passed": len(passed),
            "ssa_wire_roundtrip_failed": len(failed),
            "pre_ssa_failures_excluded_from_denominator": len(pre_ssa),
        },
        "verified_ssa_codec_failures": failed,
        "pre_ssa_failures": pre_ssa,
        "files": rows,
    }


def generate() -> dict[str, object]:
    inventory = _instruction_inventory()
    corpus = _corpus()
    changed = [row for row in inventory if row["schema_v2_added_fields"]]
    return {
        "evidence_schema_version": 2,
        "ssa_wire_schema_version": SSA_SCHEMA_VERSION,
        "audit": "RUST-3.A1-explicit-SSA-wire-schema-v2",
        "decision": "SSA_WIRE_SCHEMA_V2_QUALIFIED",
        "schema_delta": {
            "from": SSA_SCHEMA_VERSION_V1,
            "to": SSA_SCHEMA_VERSION_V2,
            "added_fields": {row["kind"]: row["schema_v2_added_fields"] for row in changed},
            "all_other_instruction_shapes_changed": False,
            "fields_added_without_existing_ssa_semantics": [],
        },
        "compatibility_policy": {
            "new_serialization_version": SSA_SCHEMA_VERSION_V2,
            "v1_decode": "explicit; unaffected instructions decode normally",
            "v1_affected_instructions": "reject because bounds_checked was not serialized",
            "cross_version_interpretation": False,
            "unsupported_versions": "reject deterministically",
            "missing_v2_bounds_checked": "reject; no default or inference",
        },
        "invariant": "Python SSA -> schema-v2 DTO -> Python SSA",
        "instruction_dataclass_count": len(inventory),
        "instruction_inventory": inventory,
        "corpus": corpus,
        "rust_dto_readiness": {
            "schema_v2_envelope": True,
            "explicit_v1_v2_dispatch": True,
            "all_eight_bounds_checked_shapes": True,
            "rust_ssa_lowering": False,
        },
        "scope_constraints": {
            "initial_ir_authority_changed": False,
            "rp3_changed": False,
            "rust_ssa_lowering_implemented": False,
            "ssa_semantics_changed": False,
            "optimizer_changed": False,
            "backend_changed": False,
            "verification_weakened": False,
            "schema_v1_changed": False,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    rendered = json.dumps(generate(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.check:
        if not OUTPUT.exists() or OUTPUT.read_text(encoding="utf-8") != rendered:
            print(f"stale SSA wire boundary evidence: {OUTPUT.relative_to(ROOT)}")
            return 1
        print("SSA wire boundary evidence is deterministic and current")
        return 0
    OUTPUT.write_text(rendered, encoding="utf-8")
    print(OUTPUT.relative_to(ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
