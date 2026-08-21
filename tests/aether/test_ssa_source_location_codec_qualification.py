from __future__ import annotations

import importlib.util
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[2] / "scripts/audit_ssa_source_location_codec.py"
SPEC = importlib.util.spec_from_file_location("audit_ssa_source_location_codec", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
generate = MODULE.generate


def test_all_77_instruction_codec_paths_are_audited() -> None:
    report = generate()
    rows = report["matrix"]
    assert report["instruction_dataclass_count"] == len(rows) == 77
    assert len({row["kind"] for row in rows}) == 77


def test_schema_source_locations_have_complete_python_codec_paths() -> None:
    report = generate()
    assert report["source_location_capable_kinds"] == [
        "array_copy", "array_get", "array_slice", "binary_op", "call",
        "invoke", "list_copy", "list_get", "list_slice", "pack_exception",
    ]
    represented = [
        row for row in report["matrix"]
        if row["schema_v2_represents_source_location"]
    ]
    assert len(represented) == 10
    for row in represented:
        assert row["python_model_supports_source_location"]
        assert row["encoder_writes_source_location"]
        assert row["decoder_reads_source_location"]
        assert row["constructor_receives_source_location"]
        assert row["round_trip_preserves_source_location"]
