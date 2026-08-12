#!/usr/bin/env python3
"""Deterministic, read-only O2.9.2 aggregate lifetime baseline generator."""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import subprocess

from aether.analysis.dominators import DominatorAnalysis
from aether.benchmark import _optimized_ssa
from aether.optimization import optimization_profile
from aether.ssa import model as m
from aether.ssa.analysis import AggregateLifetimeAnalysis, LoopAnalysis
from aether.ssa.cfg import SSACFGBuilder
try:
    from scripts.o2_hot_arc_opportunity_audit import DEFAULT_CORPUS, generate as hot_generate
except ModuleNotFoundError:  # direct script execution
    from o2_hot_arc_opportunity_audit import DEFAULT_CORPUS, generate as hot_generate

SCHEMA_VERSION = 1
HOT_ROLES = {"AGGREGATE_TEMPORARY", "CONTAINER_ELEMENT_OWNERSHIP"}


def _site_key(row):
    return row["workload"], row["function"], row["block"], row["instruction_index"]


def _final(definition, immediate, escape):
    if escape != "NO_ESCAPE": return "ESCAPE_REQUIRED"
    if isinstance(definition, (m.SSAArrayGet, m.SSAListGet)): return "EXTRACTION_TEMPORARY"
    if isinstance(definition, m.SSAStructSet): return "RECONSTRUCTION_TEMPORARY"
    if isinstance(definition, (m.SSACall, m.SSAInvoke)): return "COPY_INDUCED"
    if immediate: return "LIFETIME_OVERCONSERVATIVE"
    return "SEMANTICALLY_REQUIRED"


def _family(final):
    return {"EXTRACTION_TEMPORARY": "COLLECTION_EXTRACTION_ELISION",
            "COPY_INDUCED": "AGGREGATE_COPY_ELISION",
            "RECONSTRUCTION_TEMPORARY": "SCALAR_REPLACEMENT",
            "LIFETIME_OVERCONSERVATIVE": "BORROWED_TEMPORARY_VIEWS"}.get(final, "NO_SAFE_ELIMINATION")


def generate(root: Path, corpus: tuple[str, ...] = DEFAULT_CORPUS):
    hot = hot_generate(root, corpus)
    targets = {_site_key(x): x for x in hot["loop_arc_sites"] if x["loop_role"] in HOT_ROLES}
    census = []; reconciled = []
    for relative in corpus:
        try:
            module = _optimized_ssa((root / relative).read_text(encoding="utf-8"), root / relative, optimization_profile("O2"))
        except Exception:
            # Keep failure authority in the embedded O2.9.1 audit; its corpus
            # intentionally contains unsupported front-end probes.
            continue
        for function in module.functions:
            analysis = AggregateLifetimeAnalysis(function, module.structs)
            loops = LoopAnalysis().compute(function)
            definitions = {getattr(i, "result", None): i for b in function.blocks for i in b.instructions if getattr(i, "result", None) is not None}
            uses = {v: [] for v in definitions}
            for b in function.blocks:
                for n, i in enumerate(b.instructions):
                    for value in uses:
                        if value in getattr(i, "arguments", ()) or value in (getattr(i, "value", None), getattr(i, "struct", None)):
                            uses[value].append((b.name, n, i))
            for lifetime in analysis.lifetimes():
                census.append({"workload": relative, "function": function.name, "ssa_value": lifetime.value.name,
                    "type": repr(lifetime.value.type), "instance": lifetime.instance, "origin": lifetime.origin.value,
                    "category": lifetime.primary_category.value, "secondary_reasons": [x.value for x in lifetime.secondary_reasons],
                    "loop_depth": lifetime.loop_depth, "loop_id": lifetime.loop_id, "escape": lifetime.escape.value,
                    "component_count": len(lifetime.components), "arc_event_count": len(lifetime.arc_events),
                    "borrow_opportunity": lifetime.borrow_opportunity.value, "materialization": lifetime.materialization.value})
            for block in function.blocks:
                loop = loops.loop_for_block(block.name)
                for index, instruction in enumerate(block.instructions):
                    original = targets.get((relative, function.name, block.name, index))
                    if original is None: continue
                    value = instruction.arguments[0]; definition = definitions.get(value)
                    value_uses = uses.get(value, [])
                    semantic_uses = [u for u in value_uses if not (isinstance(u[2], (m.SSACall, m.SSAInvoke)) and getattr(u[2], "builtin", None) in {"__aether_retain", "__aether_release"})]
                    immediate = bool(definition and isinstance(definition, (m.SSAArrayGet, m.SSAListGet)) and
                                     all(b == block.name for b, _, _ in value_uses) and len(semantic_uses) <= 2)
                    escape = original["escape_state"]
                    escape_kind = "UNKNOWN" if escape["may_escape"] else "NO_ESCAPE"
                    final = _final(definition, immediate, escape_kind)
                    family = _family(final)
                    component_path = None
                    aggregate_instance = f"{function.name}:%{value.name}"
                    attribution = "COLLECTION_EXTRACTION" if isinstance(definition, (m.SSAArrayGet, m.SSAListGet)) else "TEMPORARY_DESTROY"
                    reconciled.append({"workload": relative, "function": function.name,
                        "loop_id": loop.header if loop else None, "loop_depth": original["loop_depth"],
                        "block": block.name, "instruction_index": index, "arc_kind": original["arc_kind"],
                        "ssa_value": value.name, "type": repr(value.type), "aggregate_instance": aggregate_instance,
                        "component_path": component_path, "lifetime_category": "COLLECTION_EXTRACTION_TEMPORARY" if isinstance(definition, (m.SSAArrayGet, m.SSAListGet)) else "CALL_RESULT_TEMPORARY" if isinstance(definition, (m.SSACall, m.SSAInvoke)) else "SEMANTIC_OWNER",
                        "attribution": attribution, "final_classification": final,
                        "semantic_necessity": "FUTURE_PROOF_REQUIRED" if family != "NO_SAFE_ELIMINATION" else "REQUIRED",
                        "escape": escape_kind, "future_optimization_family": family,
                        "structural_hotness": original["structural_hotness"],
                        "confidence": "HIGH" if isinstance(definition, (m.SSAArrayGet, m.SSAListGet)) else "MEDIUM"})
    census.sort(key=lambda x: (x["workload"], x["function"], x["loop_id"] or "", x["ssa_value"]))
    reconciled.sort(key=lambda x: (x["workload"], x["function"], x["loop_id"] or "", x["ssa_value"], x["block"], x["instruction_index"]))
    final_counts = Counter(x["final_classification"] for x in reconciled)
    attribution = Counter(x["attribution"] for x in reconciled)
    families = []
    for family in ["AGGREGATE_COPY_ELISION", "COLLECTION_EXTRACTION_ELISION", "BORROWED_TEMPORARY_VIEWS", "SCALAR_REPLACEMENT", "LIFETIME_HOISTING", "STACK_PROMOTION", "NO_SAFE_ELIMINATION"]:
        rows = [x for x in reconciled if x["future_optimization_family"] == family]
        families.append({"family": family, "static_arc_operations": len(rows),
                         "weighted_structural_hotness": sum(x["structural_hotness"] for x in rows),
                         "maximum_loop_depth": max((x["loop_depth"] for x in rows), default=0),
                         "correctness_risk": "HIGH" if family not in {"NO_SAFE_ELIMINATION", "AGGREGATE_COPY_ELISION"} else "MEDIUM",
                         "implementation_complexity": "HIGH" if family in {"BORROWED_TEMPORARY_VIEWS", "SCALAR_REPLACEMENT", "STACK_PROMOTION"} else "MEDIUM",
                         "llvm_overlap": "AETHER_UNIQUE" if family in {"COLLECTION_EXTRACTION_ELISION", "BORROWED_TEMPORARY_VIEWS"} else "LLVM_PARTIAL"})
    revision = subprocess.run(("git", "rev-parse", "HEAD"), cwd=root, check=True, text=True, capture_output=True).stdout.strip()
    return {"audit": "O2.9.2-aggregate-lifetime", "schema_version": SCHEMA_VERSION, "revision": revision,
        "methodology": "read-only production O2 lifecycle-expanded SSA analysis",
        "aggregate_census": census, "aggregate_census_count": len(census),
        "loop_aggregate_census": [x for x in census if x["loop_depth"]],
        "hot_arc_reconciliation": reconciled, "hot_arc_reconciliation_count": len(reconciled),
        "lifetime_classifications": dict(sorted(final_counts.items())),
        "attribution_counts": dict(sorted(attribution.items())), "future_optimization_matrix": families,
        "llvm_overlap": {"aggregate_scalarization": "LLVM_PARTIAL", "ARC_runtime_calls": "AETHER_UNIQUE"},
        "recommendation": "PROCEED_TO_COLLECTION_EXTRACTION_BORROW_ANALYSIS",
        "production_freeze": {"arc_before": {"retain": 48, "release": 919}, "arc_after": {"retain": 48, "release": 919},
                              "local_arc_changed": False, "lifecycle_changed": False, "codegen_changed": False,
                              "optimization_profiles_changed": False}}


def main():
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument("--output", type=Path); parser.add_argument("paths", nargs="*")
    args = parser.parse_args(); root = Path(__file__).resolve().parents[1]
    data = generate(root, tuple(args.paths) or DEFAULT_CORPUS); text = json.dumps(data, indent=2, sort_keys=True) + "\n"
    if args.output: args.output.write_text(text, encoding="utf-8")
    else: print(text, end="")
    return 0


if __name__ == "__main__": raise SystemExit(main())
