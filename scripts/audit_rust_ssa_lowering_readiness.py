#!/usr/bin/env python3
"""Generate the deterministic Initial IR -> Rust SSA readiness audit.

This is an analysis-only tool.  It exercises the authoritative Python lowering
and both Python wire codecs; it does not invoke an optimizer or a backend.
"""
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import fields, is_dataclass
import inspect
import json
from pathlib import Path
import re

from aether.ir import model as ir
from aether.ir.dto import ir_module_from_dto, ir_module_to_dto
from aether.pipeline import IRBackend, prepare_typed_program
from aether.ssa import model as ssa
from aether.ssa.dto import ssa_module_from_dto, ssa_module_to_dto
from aether.ssa.general_builder import GeneralSSABuilder
from aether.typechecker import TypeChecker


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "docs/compiler/rust_ssa_lowering_readiness.json"
SCHEMA_VERSION = 1
CLASSIFICATIONS = {
    "RUST_READY", "WIRE_GAP", "SEMANTIC_GAP", "ARCHITECTURE_GAP", "TEST_GAP"
}


def _concrete_subclasses(base: type) -> list[type]:
    pending = list(base.__subclasses__())
    found: set[type] = set()
    while pending:
        item = pending.pop()
        pending.extend(item.__subclasses__())
        if is_dataclass(item):
            found.add(item)
    return sorted(found, key=lambda item: item.__name__)


def _shape(type_: type) -> dict[str, object]:
    return {
        "name": type_.__name__,
        "fields": [field.name for field in fields(type_)],
    }


def _renamer_input_types() -> set[str]:
    source = inspect.getsource(__import__("aether.ssa.renaming", fromlist=["SSARenamer"]).SSARenamer._convert_instruction)
    return set(re.findall(r"isinstance\(instruction, (IR[A-Za-z0-9_]+)\)", source))


def _rules() -> list[dict[str, str]]:
    rows = [
        ("SSA-001", "initial_ir_wire", "RUST_READY", "Rust owns a strict schema-v1 Initial IR DTO/importer."),
        ("SSA-002", "ssa_wire", "RUST_READY", "Explicit Python and Rust schema-v2 DTOs preserve bounds_checked for all eight affected SSA instructions; Rust lowering remains out of scope."),
        ("SSA-003", "owned_rust_ssa_model", "ARCHITECTURE_GAP", "Rust has wire DTOs but no owned SSA model capable of representing SSAPhi."),
        ("SSA-004", "rust_lowering_entrypoint", "ARCHITECTURE_GAP", "No Rust InitialIR -> SSA lowering entry point exists."),
        ("SSA-005", "lifecycle_expansion", "SEMANTIC_GAP", "Python expands lifecycle pseudo-instructions before CFG/SSA; Rust has no parity transform."),
        ("SSA-006", "cfg_construction", "SEMANTIC_GAP", "Python recognizes normal and exceptional terminators; no Rust construction parity exists."),
        ("SSA-007", "dominators", "SEMANTIC_GAP", "Rust verifies dominance on owned Initial IR but has no lowering-time SSA dominator contract."),
        ("SSA-008", "dominance_frontiers", "SEMANTIC_GAP", "No Rust dominance-frontier implementation for lowering."),
        ("SSA-009", "pruned_phi_placement", "SEMANTIC_GAP", "No Rust live-in/definite-initialization filtered Cytron phi placement."),
        ("SSA-010", "ssa_renaming", "SEMANTIC_GAP", "No Rust dominator-tree renaming or slot stack implementation."),
        ("SSA-011", "deterministic_block_order", "TEST_GAP", "Python retains source block order, but cross-language parity is not frozen by a differential corpus."),
        ("SSA-012", "deterministic_value_numbering", "TEST_GAP", "Python uses collision-aware preferred names/counters; Rust parity and normalization tests are absent."),
        ("SSA-013", "deterministic_phi_order", "TEST_GAP", "Phi assembly is sorted, but cross-language predecessor/instruction order parity is untested."),
        ("SSA-014", "exception_cfg", "SEMANTIC_GAP", "Wire carries invoke/throw/rethrow/propagate edges; Rust lowering behavior is absent."),
        ("SSA-015", "ownership_metadata", "SEMANTIC_GAP", "Wire preserves lifecycle calls and transferred_storage, but Rust lowering has no ownership parity."),
        ("SSA-016", "aggregate_metadata", "RUST_READY", "Schema v1 carries aggregate_shape and nominal struct metadata."),
        ("SSA-017", "class_interface_metadata", "RUST_READY", "Schema v1 carries class ops, witness slots/tables and erased layouts."),
        ("SSA-018", "function_values_indirect_calls", "RUST_READY", "Both wire schemas represent function_ref, call_indirect and invoke_indirect."),
        ("SSA-019", "source_debug_metadata", "WIRE_GAP", "Only selected call/binary operations carry source_location; SSA has no module/function/block debug scope model."),
        ("SSA-020", "side_effect_contract", "SEMANTIC_GAP", "Effects are Python class/property behavior and are not serialized as a lowering contract."),
        ("SSA-021", "pre_verification", "ARCHITECTURE_GAP", "GeneralSSABuilder does not itself verify Initial IR; correctness depends on its caller."),
        ("SSA-022", "post_verification", "RUST_READY", "Python GeneralSSABuilder always executes SSAVerifier after module construction."),
        ("SSA-023", "semantic_ssa_comparator", "TEST_GAP", "No alpha/CFG-isomorphism semantic comparator exists for the future differential."),
        ("SSA-024", "rust_corpus_roundtrip", "TEST_GAP", "No end-to-end corpus test currently sends Initial IR to Rust and receives SSA."),
        ("SSA-025", "pure_function_contract", "ARCHITECTURE_GAP", "The result is deterministic for valid input, but implicit policy/code tables and required pre-verification are outside the value argument."),
    ]
    return [
        {"id": id_, "capability": capability, "classification": classification, "evidence": evidence}
        for id_, capability, classification, evidence in rows
    ]


def _discover() -> list[Path]:
    roots = [ROOT / "examples", ROOT / "benchmarks", ROOT / "corpus/exceptions"]
    return sorted({path for root in roots for path in root.rglob("*.ae")})


def _tags(path: Path, source: str) -> list[str]:
    relative = path.relative_to(ROOT).as_posix().lower()
    tags = {"examples"}
    if "expense_tracker" in relative:
        tags.add("expense_tracker")
    if any(x in relative for x in ("numerical", "minimos", "nonlinear", "matrix", "vector", "miller", "primo", "roots")):
        tags.add("numerical_workloads")
    if "exception" in relative or re.search(r"\b(throw|catch|rethrow)\b", source):
        tags.add("exceptions")
    if re.search(r"\b(struct|class|interface)\b", source):
        tags.add("structs_classes_interfaces")
    if re.search(r"\b(String|Array|List)\b", source):
        tags.add("string_array_list")
    if "indirect_call" in relative or re.search(r"\bFunction\s*[<(]", source):
        tags.add("function_values")
    return sorted(tags)


def _corpus() -> dict[str, object]:
    rows: list[dict[str, object]] = []
    for path in _discover():
        source = path.read_text(encoding="utf-8")
        row: dict[str, object] = {
            "path": path.relative_to(ROOT).as_posix(), "tags": _tags(path, source),
            "initial_ir": False, "python_ssa": False, "initial_wire_lossless": False,
            "ssa_wire_lossless": False, "rust_ssa_roundtrip_demonstrated": False,
        }
        try:
            typed = prepare_typed_program(source, TypeChecker(source_root=path.parent))
            module = IRBackend().lower_verified(typed)
            row["initial_ir"] = True
            initial_dto = ir_module_to_dto(module)
            row["initial_wire_lossless"] = ir_module_to_dto(ir_module_from_dto(initial_dto)) == initial_dto
            built = GeneralSSABuilder().build(module)
            row["python_ssa"] = True
            ssa_dto = ssa_module_to_dto(built)
            row["ssa_wire_lossless"] = ssa_module_to_dto(ssa_module_from_dto(ssa_dto)) == ssa_dto
            row["instruction_count"] = sum(len(block.instructions) for fn in built.functions for block in fn.blocks)
            row["ssa_instruction_types"] = sorted({type(ins).__name__ for fn in built.functions for block in fn.blocks for ins in block.instructions})
        except Exception as error:  # corpus measurement must retain negative programs
            row["failure_stage"] = "initial_ir" if not row["initial_ir"] else "python_ssa"
            row["failure_type"] = type(error).__name__
            row["failure"] = str(error)[:240]
        rows.append(row)

    def summary(selected: list[dict[str, object]]) -> dict[str, object]:
        total = len(selected)
        counts = {key: sum(bool(row[key]) for row in selected) for key in (
            "initial_ir", "python_ssa", "initial_wire_lossless", "ssa_wire_lossless",
            "rust_ssa_roundtrip_demonstrated")}
        denominator = counts["python_ssa"]
        return {
            "discovered": total, **counts,
            "python_ssa_wire_eligible_percent": round(100 * counts["ssa_wire_lossless"] / denominator, 2) if denominator else 0.0,
            "demonstrated_rust_roundtrip_percent": round(100 * counts["rust_ssa_roundtrip_demonstrated"] / denominator, 2) if denominator else 0.0,
        }

    categories = ["examples", "expense_tracker", "numerical_workloads", "exceptions", "structs_classes_interfaces", "string_array_list", "function_values"]
    return {
        "summary": summary(rows),
        "by_category": {tag: summary([row for row in rows if tag in row["tags"]]) for tag in categories},
        "files": rows,
    }


def generate() -> dict[str, object]:
    ir_types = _concrete_subclasses(ir.IRInstruction)
    ssa_types = _concrete_subclasses(ssa.SSAInstruction)
    handled = _renamer_input_types()
    rules = _rules()
    counts = Counter(row["classification"] for row in rules)
    corpus = _corpus()
    blockers = sorted(row["id"] for row in rules if row["classification"] in {"WIRE_GAP", "SEMANTIC_GAP", "ARCHITECTURE_GAP", "TEST_GAP"})
    return {
        "schema_version": SCHEMA_VERSION,
        "audit": "Initial-IR-to-Rust-SSA-lowering-readiness",
        "scope_constraints": {
            "authority_changed": False, "rp3_changed": False, "optimizer_changed": False,
            "backend_changed": False, "ssa_semantics_changed": False, "rust_lowering_implemented": False,
        },
        "verdict": "RUST_SSA_LOWERING_NOT_READY" if blockers else "PROCEED_TO_RUST_SSA_LOWERING_PARITY",
        "purity": {
            "conceptually_pure": True,
            "mathematical_signature": "lower(verified_initial_ir, lowering_policy_v1) -> verified_ssa | deterministic_error",
            "implicit_inputs": ["lifecycle expansion policy", "instruction effect registry", "CFG terminator table", "name-allocation policy", "verifier policy"],
            "input_mutated": False,
            "note": "InitialIRModule -> SSAModule is adequate only after freezing policy and requiring verified input; the current API hides those preconditions.",
        },
        "inventories": {
            "initial_ir_instruction_types": [{**_shape(type_), "renamer_direct": type_.__name__ in handled, "normalized_by_lifecycle": type_.__name__ in {"IRInitDefault", "IRCopyInit", "IRMoveInit", "IRAssign", "IRDestroy", "IRRelocate"}} for type_ in ir_types],
            "ssa_instruction_types": [_shape(type_) for type_ in ssa_types],
            "container_types_consumed": ["IRModule", "IRFunction", "IRBasicBlock", "IRParameter", "IRValue", "IRStorage", "IRStructDefinition", "IRType hierarchy"],
            "container_types_produced": ["SSAModule", "SSAFunction", "SSABasicBlock", "SSAParameter", "SSAValue", "IRStructDefinition (retained)", "IRType hierarchy (retained)"],
            "python_internal_dependencies": ["aether.ir.lifecycle.expand_lifecycle", "aether.analysis.cfg.CFGBuilder", "aether.analysis.dominators.DominatorAnalysis", "aether.analysis.dominance_frontier.DominanceFrontierAnalysis", "aether.ssa.phi_placement.PhiPlacement", "aether.ssa.renaming.SSARenamer", "aether.ssa.verifier.SSAVerifier", "aether.instruction_effects", "aether.ir.dto", "aether.ssa.dto"],
            "serializable_boundaries": ["Python Initial IR schema-v1 JSON", "Rust Initial IR schema-v1 DTO/importer", "Python SSA schema-v2 JSON (explicit v1 compatibility decode)", "Rust SSA schema-v2 DTO (wire only; no owned SSA conversion)"],
        },
        "algorithm": {
            "order": ["expand_lifecycle", "CFGBuilder", "DominatorAnalysis", "DominanceFrontierAnalysis", "PhiPlacement", "SSARenamer", "SSAVerifier"],
            "cfg_edges": ["jump:normal", "branch:true/false normal", "invoke*:normal+exceptional", "throw/rethrow/propagate:optional exceptional", "return:none"],
            "phi": "iterated dominance frontier, pruned by live-in or definitely-initialized slot dataflow",
            "renaming": "dominator-tree traversal with value bindings and per-slot stacks; source block order retained",
            "mutation": "input is not mutated; lifecycle expansion and SSA construction allocate new frozen dataclasses/lists",
            "pre_verifier": "not called by GeneralSSABuilder; production lower_to_verified_ssa expects caller/pipeline verified Initial IR",
            "post_verifier": "SSAVerifier always called by GeneralSSABuilder.build_module/build_function",
        },
        "differential_design": {
            "python_lane": ["verified Python Initial IR", "Python GeneralSSABuilder", "Python SSA DTO"],
            "rust_lane": ["same canonical Initial IR DTO", "Rust importer", "future Rust lowering", "Rust SSA DTO", "Python SSA importer"],
            "comparison": ["verify both outputs", "canonicalize reachable CFG from entry", "match successors by edge kind and structural target", "alpha-rename parameters/results in dominance preorder", "sort phi incoming pairs by canonical predecessor", "compare opcode, IR type, constants, metadata, effects-relevant operands and exceptional edges", "retain source function/block order only as a separate determinism assertion"],
            "must_not_ignore": ["exception edge kind", "phi predecessor association", "ownership calls", "transferred_storage", "aggregate_shape", "witness metadata", "source_location"],
        },
        "rules": rules,
        "classification_counts": {key: counts[key] for key in sorted(CLASSIFICATIONS)},
        "blocking_rule_ids": blockers,
        "corpus": corpus,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    rendered = json.dumps(generate(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.check:
        if not OUTPUT.exists() or OUTPUT.read_text(encoding="utf-8") != rendered:
            print(f"stale readiness artifact: {OUTPUT.relative_to(ROOT)}")
            return 1
        print("Rust SSA lowering readiness artifact is deterministic and current")
        return 0
    OUTPUT.write_text(rendered, encoding="utf-8")
    print(OUTPUT.relative_to(ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
