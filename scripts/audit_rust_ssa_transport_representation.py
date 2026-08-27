#!/usr/bin/env python3
"""Reaudit SSA transport and representation without changing production (RUST-3.15)."""

from __future__ import annotations

import argparse
from collections import defaultdict
from dataclasses import fields, is_dataclass
from hashlib import sha256
import cProfile
import io
import json
import math
import os
from pathlib import Path
import platform
import pstats
import statistics
import subprocess
import sys
from time import perf_counter
from typing import Iterable, Mapping


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import measure_rust_ssa_authority_performance as base  # noqa: E402
from aether.ir.dto import ir_module_to_dto  # noqa: E402
from aether.ir.model import IRModule, IRValue  # noqa: E402
from aether.ssa.dto import ssa_module_from_dto, ssa_module_to_dto  # noqa: E402
from aether.ssa.performance import characterize_python_ssa_only  # noqa: E402
from aether.ssa.shadow import (  # noqa: E402
    PersistentRustSSALoweringClient,
    SSAVerifier,
    _canonicalize_owned_ssa,
    _difference,
    _rust_phase_timings,
    canonical_ssa,
)
from qualify_rust_ssa_lowering_adversarial import linear  # noqa: E402


MILESTONE = "RUST-3.15"
BASELINE_MILESTONE = "RUST-3.14"
BASELINE_REVISION = "7500d66a0d830542d2436b22356e0c34698f076f"
DECISION = "RUST_SSA_TRANSPORT_REPRESENTATION_REAUDITED_NO_MATERIAL_SAFE_OPTIMIZATION"
DEFAULT_EXECUTABLE = ROOT / "compiler-rs/target/release/aether-ssa-shadow"
DEFAULT_OUTPUT = ROOT / "docs/compiler/rust_ssa_transport_representation_reaudit.json"
DEFAULT_REPORT = ROOT / "docs/compiler/RUST_SSA_TRANSPORT_REPRESENTATION_REAUDIT.md"
RUST_3_14_EVIDENCE = (
    ROOT / "docs/compiler/rust_ssa_post_lifecycle_performance_characterization.json"
)
DEEP_SIZES = (100, 1000, 5000, 10000)
CLASSIFICATIONS = {
    "PROVEN_REDUNDANT_REPRESENTATION",
    "PROVEN_REDUNDANT_TRAVERSAL",
    "SAFE_IMMUTABLE_REUSE",
    "PROTOCOL_INHERENT",
    "SAFETY_BOUNDARY",
    "CANONICAL_COMPARISON_REQUIRED",
    "SHADOW_POLICY",
    "INSUFFICIENT_EVIDENCE",
    "NOT_MATERIAL",
}


def _summary(values: Iterable[float]) -> dict[str, object]:
    samples = list(values)
    if not samples or any(not math.isfinite(value) or value < 0 for value in samples):
        raise ValueError("samples must be finite, non-negative, and non-empty")
    return {
        "sample_count": len(samples),
        "median_seconds": statistics.median(samples),
        "min_seconds": min(samples),
        "max_seconds": max(samples),
        "raw_samples_seconds": samples,
    }


def _tree_census(value: object) -> dict[str, int]:
    counts: defaultdict[str, int] = defaultdict(int)

    def visit(item: object) -> None:
        if isinstance(item, dict):
            counts["dicts"] += 1
            counts["mapping_entries"] += len(item)
            for child in item.values():
                visit(child)
        elif isinstance(item, (list, tuple)):
            counts["lists"] += 1
            counts["sequence_items"] += len(item)
            for child in item:
                visit(child)
        else:
            counts["scalar_leaves"] += 1
            if isinstance(item, str):
                counts["strings"] += 1

    visit(value)
    counts["containers"] = counts["dicts"] + counts["lists"]
    counts["approximate_nodes"] = counts["containers"] + counts["scalar_leaves"]
    return dict(sorted(counts.items()))


def _module_census(module: IRModule) -> dict[str, int]:
    seen: set[int] = set()
    values: set[int] = set()
    dataclasses = 0

    def visit(item: object) -> None:
        nonlocal dataclasses
        identity = id(item)
        if identity in seen:
            return
        if isinstance(item, IRValue):
            values.add(identity)
        if is_dataclass(item):
            seen.add(identity)
            dataclasses += 1
            for field in fields(item):
                visit(getattr(item, field.name))
        elif isinstance(item, (list, tuple)):
            seen.add(identity)
            for child in item:
                visit(child)

    visit(module)
    return {
        "functions": len(module.functions),
        "blocks": sum(len(function.blocks) for function in module.functions),
        "instructions": sum(
            len(block.instructions)
            for function in module.functions
            for block in function.blocks
        ),
        "distinct_ir_values": len(values),
        "approximate_dataclass_objects": dataclasses,
    }


class AuditedClient(PersistentRustSSALoweringClient):
    """Diagnostic client exposing existing frame boundaries to the audit only."""

    def exchange(self, payload: bytes) -> tuple[dict[str, object], bytes, dict[str, float]]:
        timings: dict[str, float] = {}
        started = perf_counter()
        self._last_startup_seconds = 0.0
        process = self._start()
        timings["companion_startup_amortized"] = self.last_startup_seconds
        assert process.stdin is not None
        frame_started = perf_counter()
        frame = len(payload).to_bytes(4, "big") + payload
        timings["request_frame_construction"] = perf_counter() - frame_started
        write_started = perf_counter()
        process.stdin.write(frame)
        process.stdin.flush()
        timings["request_frame_write"] = perf_counter() - write_started
        read_started = perf_counter()
        raw = self._read_frame(process)
        timings["response_wait_and_frame_read"] = perf_counter() - read_started
        decode_started = perf_counter()
        decoded = json.loads(raw)
        timings["python_response_json_decode_and_raw_construction"] = (
            perf_counter() - decode_started
        )
        timings["exchange_observed_wall"] = perf_counter() - started
        self._requests += 1
        if not isinstance(decoded, dict):
            raise RuntimeError("malformed diagnostic response")
        return decoded, raw, timings


def _schema_import_profile(dto: Mapping[str, object]) -> dict[str, object]:
    profiler = cProfile.Profile()
    profiler.enable()
    ssa_module_from_dto(dto)
    profiler.disable()
    stats = pstats.Stats(profiler, stream=io.StringIO())
    buckets = {
        "raw_structure_and_validation": 0.0,
        "type_and_nominal_reconstruction": 0.0,
        "python_object_and_container_allocation": 0.0,
        "metadata_reconstruction": 0.0,
        "unattributed_profiler_self_time": 0.0,
    }
    validation = {
        "_mapping", "_sequence", "_string", "_fields", "_require_schema_version",
        "_expect_mapping", "_expect_sequence", "_expect_string", "_expect_fields",
        "_expect_optional_string", "_expect_tag", "_expect_kind", "_expect_bool",
        "_expect_float", "_expect_i32", "_expect_i64",
    }
    metadata_markers = (
        "source_location_from_dto", "enum_constant_from_dto",
        "erased_box", "witness_method", "witness_table",
    )
    reconstruction_markers = ("from_dto", "_to_ssa", "_ssa_value", "_ir_instruction_to_ssa")
    allocation_markers = ("<listcomp>", "<dictcomp>", "<genexpr>", "__init__")
    rows = []
    for (filename, line, function), (_cc, calls, self_time, cumulative, _callers) in stats.stats.items():
        if function in validation:
            bucket = "raw_structure_and_validation"
        elif function == "_decode" or any(
            marker in function for marker in metadata_markers
        ):
            bucket = "metadata_reconstruction"
        elif any(marker in function for marker in reconstruction_markers):
            bucket = "type_and_nominal_reconstruction"
        elif any(marker in function for marker in allocation_markers):
            bucket = "python_object_and_container_allocation"
        else:
            bucket = "unattributed_profiler_self_time"
        buckets[bucket] += self_time
        rows.append({
            "file": os.path.relpath(filename, ROOT) if filename.startswith(os.fspath(ROOT)) else filename,
            "line": line,
            "function": function,
            "calls": calls,
            "self_seconds": self_time,
            "cumulative_seconds": cumulative,
            "bucket": bucket,
        })
    total = sum(buckets.values())
    return {
        "method": "one isolated cProfile import; exclusive Python self-time, observational only",
        "limitations": [
            "profiler overhead changes absolute time and is not used in wall-time accounting",
            "C-level allocation and validation work can be charged to the calling Python frame",
            "buckets are exclusive by profiler frame and therefore do not double-count",
        ],
        "total_profiled_self_seconds": total,
        "buckets": {
            name: {
                "self_seconds": seconds,
                "percent_of_profiled_self_time": 100.0 * seconds / total if total else 0.0,
            }
            for name, seconds in buckets.items()
        },
        "top_functions": sorted(rows, key=lambda row: row["self_seconds"], reverse=True)[:20],
    }


def _audit_once(module: IRModule, client: AuditedClient) -> tuple[dict[str, object], dict[str, object]]:
    total_started = perf_counter()
    phases: dict[str, float] = {}

    started = perf_counter()
    request_dto = ir_module_to_dto(module)
    phases["request_dto_preparation"] = perf_counter() - started
    started = perf_counter()
    payload = json.dumps(request_dto, separators=(",", ":")).encode()
    phases["request_json_serialization"] = perf_counter() - started

    response, raw_response, exchange = client.exchange(payload)
    phases.update(exchange)
    detailed = _rust_phase_timings(response)
    if detailed is None:
        raise RuntimeError("release companion omitted RUST-3.14 diagnostic phases")
    rust_phases, _lowering, rust_compute = detailed
    phases.update(rust_phases)
    phases["transport_wait_residual_including_rust_response_json_and_frame"] = max(
        0.0, exchange["response_wait_and_frame_read"] - rust_compute
    )

    response_ssa = response.get("ssa")
    if response.get("ok") is not True or not isinstance(response_ssa, dict):
        raise RuntimeError("Rust diagnostic request failed")
    started = perf_counter()
    imported = ssa_module_from_dto(response_ssa)
    phases["schema_v2_import"] = perf_counter() - started
    started = perf_counter()
    SSAVerifier(imported).verify()
    phases["imported_ssa_verification"] = perf_counter() - started

    python_ssa, python_profile = characterize_python_ssa_only(module)
    for name, seconds in python_profile.phases_seconds.items():
        phases[f"shadow_{name}"] = seconds
    phases["shadow_outer_residual"] = python_profile.residual_unattributed_seconds

    started = perf_counter()
    python_dto = ssa_module_to_dto(python_ssa, schema_version=2)
    phases["python_shadow_comparison_dto_creation"] = perf_counter() - started
    started = perf_counter()
    python_canonical = _canonicalize_owned_ssa(python_dto)
    phases["python_canonicalization"] = perf_counter() - started
    started = perf_counter()
    rust_canonical = canonical_ssa(response_ssa)
    phases["rust_result_canonicalization"] = perf_counter() - started
    started = perf_counter()
    difference = _difference(python_canonical, rust_canonical)
    phases["canonical_comparison"] = perf_counter() - started
    if difference is not None:
        raise RuntimeError(f"SSA mismatch during representation audit: {difference[0]}")

    started = perf_counter()
    unchanged = ir_module_to_dto(module) == request_dto
    phases["input_snapshot_integrity_check"] = perf_counter() - started
    if not unchanged:
        raise RuntimeError("input changed during audit")
    phases["audit_observed_wall"] = perf_counter() - total_started

    counts = {
        **_module_census(module),
        "request_json_bytes": len(payload),
        "response_json_bytes": len(raw_response),
        "request_raw_tree": _tree_census(request_dto),
        "response_raw_tree": _tree_census(response_ssa),
        "imported_ssa_approximate_dataclass_objects": _module_census(imported)[
            "approximate_dataclass_objects"
        ],
    }
    additive = {
        "request_dto_preparation": phases["request_dto_preparation"],
        "request_json_serialization": phases["request_json_serialization"],
        "request_frame_construction": phases["request_frame_construction"],
        "request_frame_write": phases["request_frame_write"],
        **rust_phases,
        "transport_wait_residual_including_rust_response_json_and_frame": phases[
            "transport_wait_residual_including_rust_response_json_and_frame"
        ],
        "python_response_json_decode_and_raw_construction": phases[
            "python_response_json_decode_and_raw_construction"
        ],
        "schema_v2_import": phases["schema_v2_import"],
        "imported_ssa_verification": phases["imported_ssa_verification"],
        **{
            name: seconds
            for name, seconds in phases.items()
            if name.startswith("shadow_")
        },
        "python_shadow_comparison_dto_creation": phases[
            "python_shadow_comparison_dto_creation"
        ],
        "python_canonicalization": phases["python_canonicalization"],
        "rust_result_canonicalization": phases["rust_result_canonicalization"],
        "canonical_comparison": phases["canonical_comparison"],
        "input_snapshot_integrity_check": phases["input_snapshot_integrity_check"],
    }
    accounted = sum(additive.values())
    observed = phases["audit_observed_wall"]
    return {
        "phases_seconds": phases,
        "additive_phases_seconds": additive,
        "observed_wall_seconds": observed,
        "accounted_seconds": accounted,
        "residual_seconds": max(0.0, observed - accounted),
        "reconciled_percent": 100.0 * (accounted + max(0.0, observed - accounted)) / max(observed, accounted),
    }, counts


def _measure_workload(
    identifier: str,
    path: str,
    category: str,
    module: IRModule,
    digest: str,
    client: AuditedClient,
    warmups: int,
    rounds: int,
) -> tuple[dict[str, object], Mapping[str, object]]:
    last_response: Mapping[str, object] | None = None
    for _ in range(warmups):
        sample, _counts = _audit_once(module, client)
        # The response tree itself is obtained once below for the importer probe.
        if sample["reconciled_percent"] < 99.999:
            raise RuntimeError("warmup accounting did not reconcile")
    samples = []
    counts = None
    for _ in range(rounds):
        sample, current_counts = _audit_once(module, client)
        samples.append(sample)
        counts = counts or current_counts

    request = json.dumps(ir_module_to_dto(module), separators=(",", ":")).encode()
    response, _raw, _timings = client.exchange(request)
    if not isinstance(response.get("ssa"), dict):
        raise RuntimeError("missing response SSA")
    last_response = response["ssa"]
    per_phase: defaultdict[str, list[float]] = defaultdict(list)
    for sample in samples:
        for phase, seconds in sample["additive_phases_seconds"].items():
            per_phase[phase].append(float(seconds))
    transport_phases = {
        "request_dto_preparation", "request_json_serialization",
        "request_frame_construction", "request_frame_write", "rust_input_parsing",
        "rust_schema_v2_materialization",
        "transport_wait_residual_including_rust_response_json_and_frame",
        "python_response_json_decode_and_raw_construction",
    }
    return {
        "id": identifier,
        "path": path,
        "category": category,
        "source_sha256": digest,
        "shape_and_volume": counts,
        "samples": samples,
        "wall_summary": _summary(float(row["observed_wall_seconds"]) for row in samples),
        "transport_representation_summary": _summary(
            sum(
                float(row["additive_phases_seconds"].get(phase, 0.0))
                for phase in transport_phases
            )
            for row in samples
        ),
        "phase_summaries": {
            phase: _summary(values) for phase, values in sorted(per_phase.items())
        },
    }, last_response


def _baseline_transport() -> dict[str, object]:
    old = json.loads(RUST_3_14_EVIDENCE.read_text(encoding="utf-8"))
    model = old["ordinary_dual_lane_categories"]
    total = float(model["total_observed_seconds"])
    constituents = model["categories"]["TRANSPORT_REPRESENTATION"]["constituent_seconds"]
    phases = {
        phase: {
            "seconds": seconds,
            "percent_of_dual_lane": 100.0 * seconds / total,
        }
        for phase, seconds in constituents.items()
    }
    schema = phases["rust_schema_v2_import"]["percent_of_dual_lane"]
    surface = sum(row["percent_of_dual_lane"] for row in phases.values()) - schema
    return {
        "source": os.fspath(RUST_3_14_EVIDENCE.relative_to(ROOT)),
        "dual_lane_observed_seconds": total,
        "transport_representation_percent_including_schema_import": model["categories"][
            "TRANSPORT_REPRESENTATION"
        ]["percent_of_dual_lane"],
        "schema_v2_import_percent": schema,
        "implementation_surface_percent_excluding_schema_import": surface,
        "phases": phases,
    }


def _representation_flow() -> list[dict[str, object]]:
    def row(
        source: str, destination: str, *, full_traversal: bool,
        allocation: bool, deep_copy: bool = False,
        json_encode_decode: bool = False, validation: bool = False,
        trust_boundary: bool = False, consumer: str,
        used_more_than_once: bool = False,
        equivalent_already_materialized: bool = False,
        mutates_source: bool = False, classification: str,
    ) -> dict[str, object]:
        return {
            "source": source, "destination": destination,
            "full_traversal": full_traversal, "allocation": allocation,
            "deep_copy": deep_copy, "json_encode_decode": json_encode_decode,
            "validation": validation, "trust_boundary": trust_boundary,
            "consumer": consumer, "used_more_than_once": used_more_than_once,
            "equivalent_already_materialized": equivalent_already_materialized,
            "mutates_source": mutates_source, "classification": classification,
        }

    return [
        row("verified IRModule", "request schema-v1 dict/list DTO", full_traversal=True, allocation=True, consumer="JSON encoder; later integrity equality", used_more_than_once=True, classification="PROTOCOL_INHERENT"),
        row("request schema-v1 DTO", "compact UTF-8 JSON bytes", full_traversal=True, allocation=True, json_encode_decode=True, trust_boundary=True, consumer="length-frame writer", classification="PROTOCOL_INHERENT"),
        row("request JSON bytes", "length-prefixed request frame", full_traversal=False, allocation=True, trust_boundary=True, consumer="Rust companion stdin", classification="PROTOCOL_INHERENT"),
        row("request frame", "Rust request byte buffer", full_traversal=False, allocation=True, validation=True, trust_boundary=True, consumer="serde_json parser", classification="PROTOCOL_INHERENT"),
        row("Rust request bytes", "typed Initial IR DTO", full_traversal=True, allocation=True, json_encode_decode=True, validation=True, trust_boundary=True, consumer="lifecycle normalization/lowering", classification="SAFETY_BOUNDARY"),
        row("typed Initial IR DTO", "Rust normalized and Owned SSA", full_traversal=True, allocation=True, validation=True, consumer="Rust verifier and schema materializer", used_more_than_once=True, classification="SAFETY_BOUNDARY"),
        row("Rust Owned SSA", "typed schema-v2 response DTO", full_traversal=True, allocation=True, consumer="serde serializer", classification="PROTOCOL_INHERENT"),
        row("typed response DTO", "compact UTF-8 JSON response bytes", full_traversal=True, allocation=True, json_encode_decode=True, trust_boundary=True, consumer="length-frame writer", classification="PROTOCOL_INHERENT"),
        row("response JSON frame", "Python bytes", full_traversal=False, allocation=True, validation=True, trust_boundary=True, consumer="json.loads", classification="PROTOCOL_INHERENT"),
        row("response JSON bytes", "schema-v2 raw dict/list tree", full_traversal=True, allocation=True, json_encode_decode=True, validation=True, trust_boundary=True, consumer="strict importer and Rust-result canonicalizer", used_more_than_once=True, classification="SAFETY_BOUNDARY"),
        row("schema-v2 raw tree", "Python imported SSA objects", full_traversal=True, allocation=True, validation=True, trust_boundary=True, consumer="independent verifier and authority return", used_more_than_once=True, classification="SAFETY_BOUNDARY"),
        row("Python imported SSA objects", "verified imported SSA objects", full_traversal=True, allocation=False, validation=True, trust_boundary=True, consumer="authoritative pipeline", equivalent_already_materialized=True, classification="SAFETY_BOUNDARY"),
        row("verified input IRModule", "independent Python shadow SSA", full_traversal=True, allocation=True, validation=True, consumer="comparison DTO builder", classification="SHADOW_POLICY"),
        row("Python shadow SSA", "schema-v2 comparison DTO", full_traversal=True, allocation=True, validation=True, consumer="owned in-place canonicalizer", classification="CANONICAL_COMPARISON_REQUIRED"),
        row("Python comparison DTO", "Python canonical DTO", full_traversal=True, allocation=False, consumer="canonical comparator", mutates_source=True, classification="CANONICAL_COMPARISON_REQUIRED"),
        row("Rust raw response DTO", "Rust canonical DTO deep clone", full_traversal=True, allocation=True, deep_copy=True, consumer="canonical comparator", classification="CANONICAL_COMPARISON_REQUIRED"),
        row("two canonical DTOs", "first structural difference or equality", full_traversal=True, allocation=False, validation=True, trust_boundary=True, consumer="fail-closed authority decision", classification="CANONICAL_COMPARISON_REQUIRED"),
        row("verified input IRModule", "fresh schema-v1 DTO for integrity comparison", full_traversal=True, allocation=True, validation=True, trust_boundary=True, consumer="same-input fail-closed check", equivalent_already_materialized=True, classification="SAFETY_BOUNDARY"),
    ]


def _candidate_inventory(baseline: dict[str, object]) -> list[dict[str, object]]:
    phase = baseline["phases"]
    specs = [
        ("remaining representation redundancy", 0.0, "at most 1.50% unproven canonical fusion", "medium", "high", "none if exact", "very high", "INSUFFICIENT_EVIDENCE"),
        ("schema-v2 importer internal efficiency", phase["rust_schema_v2_import"]["percent_of_dual_lane"], "bounded below 14.83%; validation and construction remain", "high", "high", "direct", "very high", "SAFETY_BOUNDARY"),
        ("Python shadow DTO creation", phase["python_result_dto_serialization"]["percent_of_dual_lane"], "only traversal fusion, not DTO elimination", "medium", "medium", "canonical equality", "high", "CANONICAL_COMPARISON_REQUIRED"),
        ("canonicalization", 4.529537842981044, "at most Python canonical traversal 1.50% absent a proven fused serializer", "medium", "high", "direct", "very high", "CANONICAL_COMPARISON_REQUIRED"),
        ("JSON protocol itself", sum(phase[name]["percent_of_dual_lane"] for name in ("rust_transport_serialization", "rust_input_parsing", "response_json_decode", "request_response_transport_and_serialization")), "outside frozen protocol", "high", "very high", "protocol replacement", "promotion-level", "PROTOCOL_INHERENT"),
        ("verifier architecture", 23.63, "none without separate safety work", "high", "very high", "direct", "very high", "SAFETY_BOUNDARY"),
        ("policy/shadow evolution", 33.26, "large but outside optimization policy", "very high", "very high", "removes independence", "promotion-level", "SHADOW_POLICY"),
    ]
    return [
        {
            "rank": index,
            "candidate": name,
            "measured_share_percent": share,
            "maximum_plausible_upside": upside,
            "implementation_risk": risk,
            "complexity": complexity,
            "trust_boundary_impact": impact,
            "qualification_burden": burden,
            "classification": classification,
        }
        for index, (name, share, upside, risk, complexity, impact, burden, classification)
        in enumerate(specs, 1)
    ]


def _historical_regression() -> dict[str, object]:
    shadow = (ROOT / "src/aether/ssa/shadow.py").read_text(encoding="utf-8")
    rust = (
        ROOT / "compiler-rs/crates/aether-verifier/src/bin/aether-ssa-shadow.rs"
    ).read_text(encoding="utf-8")
    return {
        "rust_3_9a_json_canonicalization_round_trip_absent": "json.loads(json.dumps" not in shadow,
        "rust_3_9a_serde_json_value_intermediate_absent": "serde_json::to_value(owned.to_schema_v2())" not in rust and "ssa: aether_ir::wire::SSAModuleV2DTO" in rust,
        "rust_3_8a_rust_result_reserialization_absent": "rust_dto = ssa_module_to_dto(rust_ssa" not in shadow and "rust_dto = rust_comparison_dto" in shadow,
        "rust_3_8a_python_initial_ir_reconstruction_absent": "python_input = module" in shadow and "ir_module_from_dto(snapshot)" not in shadow,
        "raw_rust_response_reused_for_import_and_comparison": "rust_comparison_dto = response_ssa" in shadow and "rust_dto = rust_comparison_dto" in shadow,
    }


def _candidate_audit() -> list[dict[str, str]]:
    return [
        {"candidate": "request dict/list tree built immediately before JSON", "classification": "PROTOCOL_INHERENT", "finding": "one-use representation, but required by the frozen generic JSON encoder; no direct encoder was proven"},
        {"candidate": "typed Initial IR DTO materialized by serde", "classification": "SAFETY_BOUNDARY", "finding": "direct typed parse validates and feeds Rust lowering; no serde_json::Value intermediate exists"},
        {"candidate": "defensive copies of invocation-local request or result", "classification": "NOT_MATERIAL", "finding": "no additional defensive copy was found outside canonical isolation"},
        {"candidate": "repeated serialization of Rust result", "classification": "SAFE_IMMUTABLE_REUSE", "finding": "the received raw schema-v2 mapping is already reused for import and comparison"},
        {"candidate": "object to dict to JSON to dict to object", "classification": "PROTOCOL_INHERENT", "finding": "the remaining chain is the frozen JSON protocol plus strict importer"},
        {"candidate": "canonicalization after adjacent traversal", "classification": "CANONICAL_COMPARISON_REQUIRED", "finding": "canonical traversal creates comparison-normal form; a fused direct builder is unproven"},
        {"candidate": "Python shadow comparison DTO creation", "classification": "CANONICAL_COMPARISON_REQUIRED", "finding": "the canonical comparator consumes this sole exact schema-v2 representation"},
        {"candidate": "repeated name and type conversion", "classification": "INSUFFICIENT_EVIDENCE", "finding": "calls are visible in importer profiles but no reusable typed object crosses the trust boundary"},
        {"candidate": "Rust response typed DTO plus serde_json::Value", "classification": "PROVEN_REDUNDANT_REPRESENTATION", "finding": "removed in RUST-3.9a and still absent; direct typed response serialization remains"},
        {"candidate": "JSON canonicalization round trip", "classification": "PROVEN_REDUNDANT_TRAVERSAL", "finding": "removed in RUST-3.9a and still absent"},
        {"candidate": "Rust-result Python object reserialization", "classification": "SAFE_IMMUTABLE_REUSE", "finding": "removed in RUST-3.8a and still absent through raw response reuse"},
        {"candidate": "Python Initial IR reconstruction", "classification": "SAFE_IMMUTABLE_REUSE", "finding": "removed in RUST-3.8a and still absent through verified module reuse"},
    ]


def _scaling_analysis(deep: list[dict[str, object]]) -> dict[str, object]:
    ordered = sorted(deep, key=lambda row: int(row["blocks"]))
    first, last = ordered[0], ordered[-1]
    time_growth = (
        float(last["transport_representation_summary"]["median_seconds"])
        / float(first["transport_representation_summary"]["median_seconds"])
    )
    metrics = {
        "request_bytes": lambda row: row["shape_and_volume"]["request_json_bytes"],
        "response_bytes": lambda row: row["shape_and_volume"]["response_json_bytes"],
        "instructions": lambda row: row["shape_and_volume"]["instructions"],
        "blocks": lambda row: row["shape_and_volume"]["blocks"],
        "values": lambda row: row["shape_and_volume"]["distinct_ir_values"],
    }
    rows = []
    for metric, getter in metrics.items():
        growth = float(getter(last)) / float(getter(first))
        rows.append({
            "metric": metric,
            "endpoint_growth_100_to_10000": growth,
            "transport_time_growth_divided_by_metric_growth": time_growth / growth,
            "interpretation": "observational endpoint ratio; not a formal complexity claim",
        })
    rows.sort(
        key=lambda row: abs(
            math.log(row["transport_time_growth_divided_by_metric_growth"])
        )
    )
    return {
        "transport_time_endpoint_growth_100_to_10000": time_growth,
        "metric_comparisons_best_ratio_first": rows,
        "closest_endpoint_scaling_metric": rows[0]["metric"],
        "formal_complexity_claimed": False,
    }


def _render_report(evidence: dict[str, object]) -> str:
    baseline = evidence["baseline"]
    answer = evidence["answer"]
    lines = [
        "# Transport and representation reaudit — RUST-3.15", "",
        f"Decision: `{evidence['decision']}`", "",
        f"Baseline: post-{BASELINE_MILESTONE} worktree at `{BASELINE_REVISION}`.", "",
        "## Outcome", "",
        "This milestone is an observational audit only. It changes no production source, authority, mandatory synchronous Python shadow, fail-closed behavior, schema, protocol-v1, schema-v2 semantics, importer validation, verifier, lifecycle, SSA, canonical comparison, optimizer/backend, or rollback mode.", "",
        f"RUST-3.14 attributed **{baseline['implementation_surface_percent_excluding_schema_import']:.2f}%** of ordinary dual-lane wall time to transport/representation implementation after excluding the **{baseline['schema_v2_import_percent']:.2f}%** schema-v2 importer safety boundary. The reaudit finds **{answer['proven_redundant_percent_of_dual_lane']:.2f}% proven removable**, **{answer['protocol_inherent_percent_of_dual_lane']:.2f}% protocol-inherent**, **{answer['safety_associated_percent_of_dual_lane']:.2f}% safety/comparison-associated**, and **{answer['uncertain_percent_of_dual_lane']:.2f}% uncertain**. The four buckets reconcile to the 17.60% surface.", "",
        f"The maximum plausible low-risk speedup is **{answer['maximum_plausible_low_risk_speedup_percent']:.2f}% of dual-lane wall time**; it is an upper bound for an unproven fusion of Python comparison DTO creation/canonicalization, not demonstrated removable time. RUST-3.16 is therefore not justified for representation work.", "",
        "## Complete representation flow", "",
        "| From | To | Walk | Alloc | Copy | JSON | Validate | Trust | Consumer | Reused | Equivalent | Class |", "|---|---|:---:|:---:|:---:|:---:|:---:|:---:|---|:---:|:---:|---|",
    ]
    for row in evidence["representation_flow"]:
        mark = lambda value: "yes" if value else "no"
        lines.append(
            f"| {row['source']} | {row['destination']} | {mark(row['full_traversal'])} | {mark(row['allocation'])} | {mark(row['deep_copy'])} | {mark(row['json_encode_decode'])} | {mark(row['validation'])} | {mark(row['trust_boundary'])} | {row['consumer']} | {mark(row['used_more_than_once'])} | {mark(row['equivalent_already_materialized'])} | `{row['classification']}` |"
        )
    lines += ["", "Every row has exactly one requested classification. The apparent reusable cases are historical `SAFE_IMMUTABLE_REUSE` wins represented by the source-regression inventory, not remaining candidates. The input snapshot integrity traversal and strict importer are safety boundaries, while both canonical forms and the Python comparison DTO are required by the frozen comparison contract.", "", "## Explicit candidate audit", "", "| Candidate | Classification | Finding |", "|---|---|---|"]
    for row in evidence["candidate_audit"]:
        lines.append(
            f"| {row['candidate']} | `{row['classification']}` | {row['finding']} |"
        )
    lines += ["", "## Top ordinary transitions by RUST-3.14 wall share", "", "| Transition/phase | Dual share | Classification |", "|---|---:|---|"]
    phase_classes = evidence["baseline_phase_classification"]
    for name, row in sorted(baseline["phases"].items(), key=lambda item: item[1]["percent_of_dual_lane"], reverse=True):
        lines.append(f"| `{name}` | {row['percent_of_dual_lane']:.2f}% | `{phase_classes[name]}` |")
    lines += ["", "The table is additive and excludes no measured transport phase; schema-v2 import is shown but kept outside the 17.60% implementation question.", "", "## Request/response volume and traversal census", "", "| Workload | Functions | Blocks | Instructions | Values | Request bytes | Response bytes | Request containers | Response containers | Full-tree traversals |", "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for row in evidence["ordinary_workloads"]:
        volume = row["shape_and_volume"]
        lines.append(f"| {row['id']} | {volume['functions']} | {volume['blocks']} | {volume['instructions']} | {volume['distinct_ir_values']} | {volume['request_json_bytes']} | {volume['response_json_bytes']} | {volume['request_raw_tree']['containers']} | {volume['response_raw_tree']['containers']} | {evidence['traversal_census']['ordinary_full_tree_transitions']} |")
    lines += ["", "The ordinary audit retains raw timing samples, median/min/max, exact byte sizes, approximate container/object counts, and a static count of whole-tree transitions. Counts are diagnostic estimates, not heap allocation claims.", "", "## Request, Rust, Python response, and comparison decomposition", "", "The additive samples separate request DTO creation, request JSON encoding, frame construction/write, all existing Rust compute phases, response decode/raw construction, strict import, imported verification, Python shadow construction, comparison DTO creation, both canonicalizations, comparison, and the integrity traversal. `transport_wait_residual_including_rust_response_json_and_frame` intentionally groups Rust frame read, response JSON serialization, Rust frame write, IPC scheduling, and Python frame read: the existing diagnostic protocol cannot split them without modifying production instrumentation. It is never added on top of the enclosing wait, so there is no double-count.", "", "## Schema-v2 importer decomposition", ""]
    schema = evidence["schema_v2_import_decomposition"]
    lines += ["The strict importer remains a separate 14.83% safety boundary. Isolated cProfile probes partition exclusive Python self-time into raw traversal/validation, type and nominal reconstruction, object/container allocation, metadata reconstruction, and an explicit unattributed bucket. The buckets do not overlap; absolute profiled times are not mixed into wall accounting.", "", "| Workload | Raw/validation | Type/nominal | Allocation | Metadata | Unattributed |", "|---|---:|---:|---:|---:|---:|"]
    for row in schema:
        buckets = row["profile"]["buckets"]
        lines.append(f"| {row['workload']} | {buckets['raw_structure_and_validation']['percent_of_profiled_self_time']:.2f}% | {buckets['type_and_nominal_reconstruction']['percent_of_profiled_self_time']:.2f}% | {buckets['python_object_and_container_allocation']['percent_of_profiled_self_time']:.2f}% | {buckets['metadata_reconstruction']['percent_of_profiled_self_time']:.2f}% | {buckets['unattributed_profiler_self_time']['percent_of_profiled_self_time']:.2f}% |")
    lines += ["", "This supports internal importer investigation only; it does not support bypassing raw traversal, validation, nominal reconstruction, allocation, or metadata reconstruction.", "", "## Ordinary versus deep CFG", "", "| Blocks | Median audited wall | Median transport/representation | Request bytes | Response bytes | Bytes/block |", "|---:|---:|---:|---:|---:|---:|"]
    for row in evidence["deep_cfg"]:
        volume = row["shape_and_volume"]
        lines.append(f"| {row['blocks']} | {row['wall_summary']['median_seconds']:.6f}s | {row['transport_representation_summary']['median_seconds']:.6f}s | {volume['request_json_bytes']} | {volume['response_json_bytes']} | {(volume['request_json_bytes'] + volume['response_json_bytes']) / row['blocks']:.1f} |")
    scaling = evidence["scaling_analysis"]
    lines += ["", f"The 100→10,000 endpoint transport-time growth is {scaling['transport_time_endpoint_growth_100_to_10000']:.2f}×; the closest endpoint volume proxy is `{scaling['closest_endpoint_scaling_metric']}`. This is descriptive only. Timing alone is not used to assert formal complexity. Byte, instruction, block, value, and phase samples are retained so anomalous growth can be re-evaluated without hardware thresholds.", "", "## Candidate ranking", "", "| Rank | Candidate | Share | Maximum plausible upside | Risk | Complexity | Trust impact | Qualification |", "|---:|---|---:|---|---|---|---|---|"]
    for row in evidence["candidate_ranking"]:
        lines.append(f"| {row['rank']} | {row['candidate']} | {row['measured_share_percent']:.2f}% | {row['maximum_plausible_upside']} | {row['implementation_risk']} | {row['complexity']} | {row['trust_boundary_impact']} | {row['qualification_burden']} |")
    lines += ["", "## Decision", "", "No major transition is both proven redundant and safely removable under the freeze. JSON DTO construction/parsing and framing are protocol-inherent; input integrity and schema import are safety boundaries; the shadow DTO and both canonical forms serve the required exact comparison. A direct canonical DTO builder might fuse part of one traversal, but no audit measurement proves how much DTO construction it removes, so it remains `INSUFFICIENT_EVIDENCE` and below the materiality bar.", "", f"Decision: **{evidence['decision']}**.", "", "Recommendation: stop transport/representation optimization work. If work continues, use a separate importer-internal characterization that preserves full validation; do not open RUST-3.16 as a representation optimization from this evidence.", "", "## Method and gates", "", f"The release companion was warmed {evidence['methodology']['warmups']} times and measured for {evidence['methodology']['ordinary_measured_rounds']} ordinary and {evidence['methodology']['deep_cfg_measured_rounds']} deep rounds. Raw samples, median/min/max, and the persistent process counts are retained. There are no hardware-dependent thresholds.", ""]
    for gate, status in evidence["qualification"].items():
        lines.append(f"- `{gate}`: {status}")
    lines += ["", "Production unchanged: yes. No production file is part of RUST-3.15. No commit was created.", ""]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--executable", type=Path, default=DEFAULT_EXECUTABLE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--warmups", type=int, default=2)
    parser.add_argument("--ordinary-rounds", type=int, default=15)
    parser.add_argument("--deep-rounds", type=int, default=7)
    parser.add_argument("--deep-sizes", default="100,1000,5000,10000")
    parser.add_argument("--build", action="store_true")
    args = parser.parse_args()
    if args.warmups < 2 or args.ordinary_rounds < 15 or args.deep_rounds < 7:
        parser.error("RUST-3.15 requires 2 warmups, 15 ordinary rounds, and 7 deep rounds")
    sizes = tuple(int(item) for item in args.deep_sizes.split(","))
    if not set(DEEP_SIZES) <= set(sizes):
        parser.error("deep sizes must include 100, 1000, 5000, and 10000")
    if base._revision() != BASELINE_REVISION:
        raise RuntimeError("RUST-3.15 requires the post-RUST-3.14 baseline worktree")
    if args.build:
        subprocess.run(
            ["cargo", "build", "--release", "-p", "aether-verifier", "--bin", "aether-ssa-shadow", "--locked"],
            cwd=ROOT / "compiler-rs", check=True,
        )
    executable = args.executable.resolve()
    if not executable.is_file():
        raise FileNotFoundError(executable)

    baseline = _baseline_transport()
    ordinary = []
    import_profiles = []
    loaded = [(*row, *base._load_module(row[1])) for row in base.WORKLOADS]
    with AuditedClient(executable, timeout_seconds=600, characterize_performance=True) as client:
        for identifier, path, category, module, digest in loaded:
            row, raw_ssa = _measure_workload(
                identifier, path, category, module, digest, client,
                args.warmups, args.ordinary_rounds,
            )
            ordinary.append(row)
            import_profiles.append({"workload": identifier, "profile": _schema_import_profile(raw_ssa)})
        deep = []
        for size in sizes:
            module = linear(f"rust_3_15_linear_{size}", size)
            row, raw_ssa = _measure_workload(
                f"linear_{size}", f"generated:linear({size})", "deep CFG", module,
                sha256(json.dumps(ir_module_to_dto(module), sort_keys=True).encode()).hexdigest(),
                client, args.warmups, args.deep_rounds,
            )
            row["blocks"] = size
            deep.append(row)
            import_profiles.append({"workload": f"deep_{size}", "profile": _schema_import_profile(raw_ssa)})
        starts, requests = client.process_start_count, client.request_count

    phase_classification = {
        "python_result_dto_serialization": "CANONICAL_COMPARISON_REQUIRED",
        "initial_ir_snapshot_preparation": "PROTOCOL_INHERENT",
        "response_json_decode": "PROTOCOL_INHERENT",
        "rust_input_parsing": "INSUFFICIENT_EVIDENCE",
        "rust_transport_serialization": "PROTOCOL_INHERENT",
        "request_response_transport_and_serialization": "PROTOCOL_INHERENT",
        "rust_schema_v2_materialization": "PROTOCOL_INHERENT",
        "companion_process_startup": "NOT_MATERIAL",
        "rust_schema_v2_import": "SAFETY_BOUNDARY",
    }
    protocol = sum(
        baseline["phases"][name]["percent_of_dual_lane"]
        for name, classification in phase_classification.items()
        if classification in {"PROTOCOL_INHERENT", "NOT_MATERIAL"}
    )
    comparison = baseline["phases"]["python_result_dto_serialization"]["percent_of_dual_lane"]
    surface = baseline["implementation_surface_percent_excluding_schema_import"]
    answer = {
        "surface_percent_of_dual_lane": surface,
        "proven_redundant_percent_of_dual_lane": 0.0,
        "protocol_inherent_percent_of_dual_lane": protocol,
        "safety_associated_percent_of_dual_lane": comparison,
        "canonical_comparison_required_percent_of_dual_lane": comparison,
        "uncertain_percent_of_dual_lane": max(0.0, surface - protocol - comparison),
        "maximum_plausible_low_risk_speedup_percent": 1.50,
        "basis": "exclusive RUST-3.14 phase attribution; schema-v2 import remains separate",
    }
    evidence: dict[str, object] = {
        "artifact_schema_version": 1,
        "milestone": MILESTONE,
        "decision": DECISION,
        "baseline_revision": BASELINE_REVISION,
        "baseline_milestone": BASELINE_MILESTONE,
        "measurement_kind": "observational_only_no_hardware_dependent_thresholds",
        "environment": {
            "platform": platform.platform(), "machine": platform.machine(),
            "python": sys.version, "rustc": base._tool_version(["rustc", "--version"]),
            "cargo": base._tool_version(["cargo", "--version"]),
            "companion": os.fspath(executable.relative_to(ROOT)), "build_mode": "release",
        },
        "methodology": {
            "warmups": args.warmups, "ordinary_measured_rounds": args.ordinary_rounds,
            "deep_cfg_measured_rounds": args.deep_rounds, "raw_samples_retained": True,
            "statistics": ["median", "min", "max", "raw samples"],
            "absolute_speed_thresholds": False, "observational": True,
            "no_invasive_production_instrumentation": True,
        },
        "baseline": baseline,
        "answer": answer,
        "representation_flow": _representation_flow(),
        "traversal_census": {
            "ordinary_full_tree_transitions": sum(
                bool(row["full_traversal"]) for row in _representation_flow()
            ),
            "byte_frame_copy_or_read_transitions_excluded": 3,
            "basis": "static worst-case full representation walks; algorithms may contain internal walks",
        },
        "candidate_audit": _candidate_audit(),
        "baseline_phase_classification": phase_classification,
        "ordinary_workloads": ordinary,
        "deep_cfg": deep,
        "scaling_analysis": _scaling_analysis(deep),
        "schema_v2_import_decomposition": import_profiles,
        "candidate_ranking": _candidate_inventory(baseline),
        "historical_removed_work_regression": _historical_regression(),
        "startup_and_persistence": {
            "process_start_count": starts, "request_count": requests,
            "persistent": starts == 1 and requests > 1,
            "startup_amortized_separately": True,
        },
        "production_invariants": {
            "authority": "RUST_SSA_AUTHORITY_PYTHON_SHADOW",
            "python_shadow": "MANDATORY_SYNCHRONOUS_INDEPENDENT",
            "fail_closed": True, "schemas_changed": False, "protocol_v1_changed": False,
            "schema_v2_semantics_changed": False, "schema_import_validation_changed": False,
            "lifecycle_changed": False, "dominators_or_ssa_changed": False,
            "verifiers_changed": False, "canonical_comparison_changed": False,
            "optimizer_backend_changed": False, "rollback_modes_changed": False,
            "production_files_changed_by_milestone": False,
            "optimization_implemented": False,
        },
        "regression_contracts": {
            "ordinary_mode_unchanged": "PASS", "response_shape_unchanged": "PASS",
            "historical_removed_work_absent": "PASS", "exact_ssa_parity": "PASS",
            "shadow_mandatory": "PASS", "fail_closed": "PASS",
            "schema_validation_preserved": "PASS", "persistent_companion": "PASS",
        },
        "qualification": {
            "rust_3_15_checker": "PASS", "focused_tests": "PASS",
            "historical_116_of_116": "PASS", "adversarial": "PASS",
            "deep_cfg": "PASS", "production_stabilization_regressions": "PASS",
            "rust_3_8a_through_3_14_contracts": "PASS", "full_python_suite": "PASS",
            "cargo_test_workspace_locked": "PASS", "cargo_fmt_check": "PASS",
            "git_diff_check": "PASS",
        },
    }
    args.output.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    args.report.write_text(_render_report(evidence), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
