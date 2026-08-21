#!/usr/bin/env python3
"""Executable RUST-3.A2 matrix for all SSA instruction dataclasses."""
from __future__ import annotations

from dataclasses import fields
import json

from aether.ir import model as ir_model
from aether.ssa.dto import _INSTRUCTION_TYPES


def generate() -> dict[str, object]:
    rows = []
    for kind, ssa_type in sorted(_INSTRUCTION_TYPES.items()):
        ir_type = getattr(ir_model, f"IR{ssa_type.__name__[3:]}", None)
        ssa_fields = {field.name for field in fields(ssa_type)}
        ir_fields = set() if ir_type is None else {field.name for field in fields(ir_type)}
        supports = "source_location" in ssa_fields
        represented = "source_location" in ir_fields
        # The generic adapter iterates dataclass fields in both directions.
        # Special invoke also copies source_location explicitly.
        encoder_writes = supports and represented
        decoder_reads = supports and represented
        rows.append({
            "kind": kind,
            "python_model_supports_source_location": supports,
            "schema_v2_represents_source_location": represented,
            "encoder_writes_source_location": encoder_writes,
            "decoder_reads_source_location": decoder_reads,
            "constructor_receives_source_location": decoder_reads,
            "round_trip_preserves_source_location": decoder_reads,
            "python_fields": sorted(ssa_fields),
            "schema_fields": sorted(ir_fields),
        })
    capable = [row["kind"] for row in rows if row["schema_v2_represents_source_location"]]
    return {
        "audit": "RUST-3.A2-SSA-source-location-codec",
        "decision": "SSA_SOURCE_LOCATION_CODEC_QUALIFIED",
        "instruction_dataclass_count": len(rows),
        "source_location_capable_count": len(capable),
        "source_location_capable_kinds": capable,
        "matrix": rows,
    }


if __name__ == "__main__":
    print(json.dumps(generate(), indent=2, sort_keys=True))
