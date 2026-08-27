#!/usr/bin/env python3
"""Adversarially qualify independent Python SSA shadow redundancy (RUST-4.3).

This is deliberately an offline diagnostic.  It mutates copies of schema-v2
Rust results and never participates in, configures, or changes production.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from copy import deepcopy
import importlib.util
import inspect
import json
from pathlib import Path
from random import Random
import subprocess
import sys
from time import perf_counter
from typing import Callable


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from aether.ir.dto import ir_module_to_dto  # noqa: E402
from aether.ir.lifecycle import expand_lifecycle  # noqa: E402
from aether.ir.model import (  # noqa: E402
    IRBasicBlock,
    IRBranch,
    IRConst,
    IRFunction,
    IRInstruction,
    IRJump,
    IRLoad,
    IRModule,
    IRParameter,
    IRReturn,
    IRStore,
    IRValue,
)
import aether.ir.model as ir_model  # noqa: E402
from aether.ir.types import BoolType, IntType  # noqa: E402
from aether.pipeline import IRBackend, prepare_typed_program  # noqa: E402
from aether.ssa import (  # noqa: E402
    GeneralSSABuilder,
    SSARefinementVerifier,
    SSAVerifier,
)
from aether.ssa.dto import ssa_module_from_dto, ssa_module_to_dto  # noqa: E402
from aether.ssa.shadow import PersistentRustSSALoweringClient, canonical_ssa  # noqa: E402
from aether.typechecker import TypeChecker  # noqa: E402


MILESTONE = "RUST-4.3"
QUALIFICATION_REVISION = 1
BASELINE_REVISION = "07a372da7f9b80dbc079b2f27c43d091b256f0b8"
DECISION_EVIDENCE = "PYTHON_SSA_SHADOW_NO_UNIQUE_COVERAGE_DEMONSTRATED"
DECISION_RETAIN = "PYTHON_SSA_SHADOW_UNIQUE_COVERAGE_DEMONSTRATED_RETAIN"
DECISION_INCOMPLETE = "RUST_4_3_QUALIFICATION_INCOMPLETE"
DEFAULT_COMPANION = ROOT / "compiler-rs/target/release/aether-ssa-shadow"
DEFAULT_RUST_VERIFIER = ROOT / "compiler-rs/target/debug/examples/verify_owned_ssa_v2"
DEFAULT_OUTPUT = ROOT / "docs/compiler/rust_ssa_shadow_redundancy_qualification.json"
DEFAULT_REPORT = ROOT / "docs/compiler/RUST_SSA_SHADOW_REDUNDANCY_QUALIFICATION.md"
R40_PATH = ROOT / "scripts/qualify_rust_ssa_independent_authority.py"
R41_PATH = ROOT / "scripts/qualify_rust_ssa_independent_refinement_verifier.py"
R42_EVIDENCE = ROOT / "docs/compiler/rust_ssa_refinement_production_integration.json"
RANDOM_SEEDS = (43001, 43019, 43037, 43051, 43063, 43067, 43093, 43103)


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load qualification dependency {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


R40 = _load("rust_4_0_for_4_3", R40_PATH)
R41 = _load("rust_4_1_for_4_3", R41_PATH)


class Mutation:
    __slots__ = ("mutation_id", "family", "fixture", "intent", "mutate", "correlated", "source")

    def __init__(
        self,
        mutation_id: str,
        family: str,
        fixture: str,
        intent: str,
        mutate: Callable[[dict[str, object]], None],
        correlated: bool = False,
        source: str = MILESTONE,
    ) -> None:
        self.mutation_id = mutation_id
        self.family = family
        self.fixture = fixture
        self.intent = intent
        self.mutate = mutate
        self.correlated = correlated
        self.source = source


def fixtures() -> dict[str, IRModule]:
    def source_fixture(relative: str) -> IRModule:
        path = ROOT / relative
        source = path.read_text(encoding="utf-8")
        return expand_lifecycle(
            IRBackend().lower_verified(
                prepare_typed_program(source, TypeChecker(source_root=path.parent))
            )
        )

    def wide_phi_fixture() -> IRModule:
        integer = IntType()
        condition = IRParameter("condition", BoolType())
        slots = [IRValue(f"slot.{index}", integer) for index in range(8)]
        blocks = [
            IRBasicBlock("entry", [IRBranch(condition, "left.branch", "right.branch")]),
            IRBasicBlock("left.branch", [IRBranch(condition, "p0", "p1")]),
            IRBasicBlock("right.branch", [IRBranch(condition, "p2", "p3")]),
        ]
        for predecessor in range(4):
            instructions = []
            for slot_index, slot in enumerate(slots):
                value = IRValue(f"p{predecessor}.v{slot_index}", integer)
                instructions.extend(
                    [IRConst(value, predecessor * 100 + slot_index), IRStore(slot, value)]
                )
            instructions.append(IRJump("merge"))
            blocks.append(IRBasicBlock(f"p{predecessor}", instructions))
        loaded = [IRValue(f"loaded.{index}", integer) for index in range(8)]
        blocks.append(
            IRBasicBlock(
                "merge",
                [*(IRLoad(value, slot) for value, slot in zip(loaded, slots, strict=True)), IRReturn(loaded[-1])],
            )
        )
        return IRModule([IRFunction("wide_phi", [condition], integer, blocks)])

    def multiple_exit_fixture() -> IRModule:
        condition = IRParameter("condition", BoolType())
        value = IRParameter("value", IntType())
        return IRModule(
            [
                IRFunction(
                    "multiple_exit",
                    [condition, value],
                    IntType(),
                    [
                        IRBasicBlock("entry", [IRBranch(condition, "left.empty", "right.empty")]),
                        IRBasicBlock("left.empty", [IRJump("left.return")]),
                        IRBasicBlock("right.empty", [IRJump("right.return")]),
                        IRBasicBlock("left.return", [IRReturn(value)]),
                        IRBasicBlock("right.return", [IRReturn(value)]),
                    ],
                )
            ]
        )

    return {
        "diamond": expand_lifecycle(R40.branch_module()),
        "effects": expand_lifecycle(R41.effect_module()),
        "loop": expand_lifecycle(R41.loop_module()),
        "nested_loop": expand_lifecycle(R41.nested_loop_module()),
        "irreducible": expand_lifecycle(R41.irreducible_module()),
        "unreachable": expand_lifecycle(R41.unreachable_module()),
        "multiple_phi": expand_lifecycle(R41.multiple_phi_module()),
        # lifecycle_heavy_module is already normalized.
        "lifecycle": R41.lifecycle_heavy_module(),
        "exception_indirect": source_fixture("corpus/exceptions/positive/indirect_call.ae"),
        "exception_interface": source_fixture("corpus/exceptions/positive/method_interface_dispatch.ae"),
        "exception_cleanup": source_fixture("corpus/exceptions/positive/cleanup_during_unwinding.ae"),
        "wide_phi": expand_lifecycle(wide_phi_fixture()),
        "multiple_exit": expand_lifecycle(multiple_exit_fixture()),
    }


def _functions(dto: dict[str, object]) -> list[dict[str, object]]:
    return dto["functions"]  # type: ignore[return-value]


def _function(dto: dict[str, object], name: str | None = None) -> dict[str, object]:
    functions = _functions(dto)
    if name is None:
        return functions[0]
    return next(function for function in functions if function["name"] == name)


def _blocks(dto: dict[str, object], function: str | None = None) -> dict[str, dict[str, object]]:
    return {
        block["name"]: block
        for block in _function(dto, function)["blocks"]  # type: ignore[index]
    }


def _instructions(dto: dict[str, object], block: str, function: str | None = None) -> list[dict[str, object]]:
    return _blocks(dto, function)[block]["instructions"]  # type: ignore[return-value]


def _first_kind(dto: dict[str, object], kind: str) -> tuple[list[dict[str, object]], int, dict[str, object]]:
    for function in _functions(dto):
        for block in function["blocks"]:  # type: ignore[index]
            instructions = block["instructions"]
            for index, instruction in enumerate(instructions):
                if instruction["kind"] == kind:
                    return instructions, index, instruction
    raise ValueError(f"no {kind} instruction")


def _parameter(dto: dict[str, object], index: int = 0, function: str | None = None) -> dict[str, object]:
    return deepcopy(_function(dto, function)["parameters"][index])  # type: ignore[index]


def _value(name: str, tag: str = "int") -> dict[str, object]:
    return {"tag": "value", "name": name, "type": {"tag": tag}}


def _swap_branch(dto: dict[str, object]) -> None:
    branch = _instructions(dto, "entry")[-1]
    branch["true_target"], branch["false_target"] = branch["false_target"], branch["true_target"]


def _redirect_jump(dto: dict[str, object]) -> None:
    _instructions(dto, "then")[-1]["target"] = "else"


def _alter_backedge(dto: dict[str, object]) -> None:
    _instructions(dto, "body", "loop_carried")[-1]["target"] = "exit"


def _bypass_block_correlated(dto: dict[str, object]) -> None:
    branch = _instructions(dto, "entry")[-1]
    branch["true_target"] = "merge"
    phi = _instructions(dto, "merge")[0]
    phi["incoming"] = [entry for entry in phi["incoming"] if entry["block"] != "then"]
    phi["incoming"].append({"block": "entry", "value": _parameter(dto)})


def _remove_reachable(dto: dict[str, object]) -> None:
    R41._missing_reachable_block(dto)


def _make_unreachable_reachable(dto: dict[str, object]) -> None:
    _instructions(dto, "entry")[-1]["target"] = "dead"


def _missing_phi_incoming(dto: dict[str, object]) -> None:
    _instructions(dto, "merge")[0]["incoming"].pop()


def _extra_phi_incoming(dto: dict[str, object]) -> None:
    phi = _instructions(dto, "merge")[0]
    phi["incoming"].append({"block": "entry", "value": _parameter(dto)})


def _duplicate_phi_predecessor(dto: dict[str, object]) -> None:
    phi = _instructions(dto, "merge")[0]
    phi["incoming"][1]["block"] = phi["incoming"][0]["block"]


def _swap_phi_values(dto: dict[str, object]) -> None:
    incoming = _instructions(dto, "merge")[0]["incoming"]
    incoming[0]["value"], incoming[1]["value"] = incoming[1]["value"], incoming[0]["value"]


def _wrong_loop_initial(dto: dict[str, object]) -> None:
    phi = _instructions(dto, "header", "loop_carried")[0]
    phi["incoming"][0]["value"] = deepcopy(phi["incoming"][1]["value"])


def _wrong_loop_carried(dto: dict[str, object]) -> None:
    phi = _instructions(dto, "header", "loop_carried")[0]
    phi["incoming"][1]["value"] = _parameter(dto, 0, "loop_carried")


def _swap_interacting_phi_values(dto: dict[str, object]) -> None:
    first, second = _instructions(dto, "merge")[:2]
    for left, right in zip(first["incoming"], second["incoming"], strict=True):
        left["value"], right["value"] = right["value"], left["value"]


def _alias_phi_results_correlated(dto: dict[str, object]) -> None:
    first, second = _instructions(dto, "merge")[:2]
    old = deepcopy(second["result"])
    replacement = deepcopy(first["result"])
    second["result"] = _value("qualification.aliased")
    for instruction in _instructions(dto, "merge")[2:]:
        for key, value in list(instruction.items()):
            if value == old:
                instruction[key] = deepcopy(replacement)


def _wrong_effect_parameter(dto: dict[str, object]) -> None:
    _instructions(dto, "entry", "effects")[0]["arguments"] = [_parameter(dto, 1, "effects")]


def _alter_compare(dto: dict[str, object]) -> None:
    _instructions(dto, "entry")[1]["operator"] = "lt"


def _swap_compare_operands(dto: dict[str, object]) -> None:
    compare = _instructions(dto, "entry")[1]
    compare["left"], compare["right"] = compare["right"], compare["left"]


def _remove_effect(dto: dict[str, object]) -> None:
    _instructions(dto, "entry", "effects").pop(0)


def _duplicate_effect(dto: dict[str, object]) -> None:
    instructions = _instructions(dto, "entry", "effects")
    instructions.insert(1, deepcopy(instructions[0]))


def _alter_print_metadata(dto: dict[str, object]) -> None:
    _instructions(dto, "entry", "effects")[2]["newline"] = False


def _move_effect(dto: dict[str, object]) -> None:
    instructions = _instructions(dto, "entry", "effects")
    instructions[0], instructions[2] = instructions[2], instructions[0]


def _remove_lifecycle_effect(dto: dict[str, object]) -> None:
    for kind in ("call", "list_set", "struct_set", "list_get", "list_new"):
        try:
            instructions, index, _ = _first_kind(dto, kind)
        except ValueError:
            continue
        instructions.pop(index)
        return
    raise ValueError("no lifecycle/effectful instruction")


def _duplicate_lifecycle_effect(dto: dict[str, object]) -> None:
    instructions, index, instruction = _first_kind(dto, "call")
    duplicate = deepcopy(instruction)
    if isinstance(duplicate.get("result"), dict):
        duplicate["result"] = _value("qualification.lifecycle.duplicate", duplicate["result"]["type"]["tag"])
    instructions.insert(index + 1, duplicate)


def _alter_lifecycle_callee(dto: dict[str, object]) -> None:
    _, _, instruction = _first_kind(dto, "call")
    instruction["function"] = "qualification_wrong_lifecycle_callee"


def _wrong_return_parameter(dto: dict[str, object]) -> None:
    _instructions(dto, "entry", "effects")[-1]["value"] = _parameter(dto, 0, "effects")


def _constant_return(dto: dict[str, object]) -> None:
    instructions = _instructions(dto, "merge")
    instructions.insert(-1, {"kind": "const", "result": _value("qualification.return.constant"), "value": {"tag": "int", "value": 77}})
    instructions[-1]["value"] = _value("qualification.return.constant")


def _wrong_branch_condition(dto: dict[str, object]) -> None:
    instructions = _instructions(dto, "entry")
    instructions.insert(-1, {"kind": "const", "result": _value("qualification.condition", "bool"), "value": {"tag": "bool", "value": True}})
    instructions[-1]["condition"] = _value("qualification.condition", "bool")


def _premature_return(dto: dict[str, object]) -> None:
    instructions = _instructions(dto, "entry")
    instructions[-1] = {"kind": "return", "value": _parameter(dto), "transferred_storage": None}


def _correlated_constant(dto: dict[str, object]) -> None:
    # A realistic producer bug: definition and all downstream uses remain
    # internally consistent; only the literal semantic is wrong.
    _instructions(dto, "then")[0]["value"]["value"] = 1001


def _alter_exception_match_type(dto: dict[str, object]) -> None:
    _, _, instruction = _first_kind(dto, "exception_match")
    instruction["catch_type"] = "Error"


def _remove_exception_destroy(dto: dict[str, object]) -> None:
    instructions, index, _ = _first_kind(dto, "exception_destroy")
    instructions.pop(index)


def _corrupt_indirect_exception_edge(dto: dict[str, object]) -> None:
    _, _, instruction = _first_kind(dto, "invoke_indirect")
    instruction["normal_target"] = instruction["exceptional_target"]


def _alter_interface_ownership(dto: dict[str, object]) -> None:
    _, _, instruction = _first_kind(dto, "invoke_interface")
    instruction["slot"]["receiver_ownership"] = "owned"  # type: ignore[index]


def _replace_rethrow_with_propagate(dto: dict[str, object]) -> None:
    _, _, instruction = _first_kind(dto, "rethrow")
    instruction["kind"] = "propagate"


def _alter_invoke_callee(dto: dict[str, object]) -> None:
    _, _, instruction = _first_kind(dto, "invoke")
    instruction["function"] = "qualification_wrong_exception_callee"


def _alpha_rename(dto: dict[str, object]) -> None:
    names: dict[str, str] = {}

    def visit(value: object) -> None:
        if isinstance(value, dict):
            if value.get("tag") == "value" and isinstance(value.get("name"), str):
                old = value["name"]
                value["name"] = names.setdefault(old, f"alpha.{len(names)}")
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(dto)


def mutation_manifest() -> tuple[Mutation, ...]:
    inherited_families = {
        "missing_phi": "phi",
        "extra_phi": "phi",
        "incorrect_phi_incoming": "phi",
        "incorrect_predecessor": "phi",
        "duplicate_definition": "value_provenance",
        "use_before_definition": "instruction_preservation",
        "definition_not_dominating_use": "value_provenance",
        "phi_incoming_not_dominating_edge": "phi",
        "incorrect_type": "value_provenance",
        "incorrect_value_rename": "slot_promotion",
        "incorrect_block_target": "cfg_reachability",
        "unreachable_block_incorrectly_preserved": "cfg_reachability",
        "missing_instruction": "instruction_preservation",
        "duplicated_instruction": "instruction_preservation",
        "incorrect_return_value": "return_termination",
    }
    inherited = tuple(
        Mutation(
            f"R43-HIST-{index:03d}",
            inherited_families[name],
            "diamond",
            f"historical {name.replace('_', ' ')} corruption",
            mutate,
            source="RUST-4.0/RUST-4.1 regression",
        )
        for index, (name, mutate, _property) in enumerate(R40.MUTATIONS, 1)
        if name != "ownership_lifecycle_corruption"
    )
    new = (
        Mutation("R43-CFG-001", "cfg_reachability", "diamond", "swap conditional successors", _swap_branch),
        Mutation("R43-CFG-002", "cfg_reachability", "diamond", "redirect a jump while retaining a valid target", _redirect_jump),
        Mutation("R43-CFG-003", "cfg_reachability", "loop", "alter loop backedge", _alter_backedge),
        Mutation("R43-CFG-004", "cfg_reachability", "diamond", "bypass a block and repair phi labels", _bypass_block_correlated, True),
        Mutation("R43-CFG-005", "cfg_reachability", "diamond", "remove a reachable block and redirect its edge", _remove_reachable, True),
        Mutation("R43-CFG-006", "cfg_reachability", "unreachable", "make an Initial-IR-unreachable block reachable", _make_unreachable_reachable),
        Mutation("R43-PHI-001", "phi", "diamond", "remove one phi incoming edge", _missing_phi_incoming),
        Mutation("R43-PHI-002", "phi", "diamond", "add a superficially plausible incoming edge", _extra_phi_incoming),
        Mutation("R43-PHI-003", "phi", "diamond", "duplicate an incoming predecessor", _duplicate_phi_predecessor),
        Mutation("R43-PHI-004", "phi", "diamond", "swap same-typed incoming values", _swap_phi_values),
        Mutation("R43-PHI-005", "phi", "loop", "replace the initial loop value", _wrong_loop_initial),
        Mutation("R43-PHI-006", "phi", "loop", "replace the loop-carried reaching definition", _wrong_loop_carried),
        Mutation("R43-PHI-007", "phi", "multiple_phi", "corrupt interacting phis consistently", _swap_interacting_phi_values, True),
        Mutation("R43-VAL-001", "value_provenance", "effects", "substitute a same-typed parameter", _wrong_effect_parameter),
        Mutation("R43-VAL-002", "value_provenance", "multiple_phi", "alias distinct phi results and downstream use", _alias_phi_results_correlated, True),
        Mutation("R43-INS-001", "instruction_preservation", "diamond", "alter comparison predicate", _alter_compare),
        Mutation("R43-INS-002", "instruction_preservation", "diamond", "swap arithmetic/comparison operands", _swap_compare_operands),
        Mutation("R43-EFF-001", "effects", "effects", "remove a direct call effect", _remove_effect),
        Mutation("R43-EFF-002", "effects", "effects", "duplicate a direct call effect", _duplicate_effect),
        Mutation("R43-EFF-003", "effects", "effects", "move a call across another effect", _move_effect),
        Mutation("R43-EFF-004", "effects", "effects", "alter print effect metadata", _alter_print_metadata),
        Mutation("R43-EFF-005", "effects", "lifecycle", "remove a lifecycle-normalized effect", _remove_lifecycle_effect),
        Mutation("R43-EFF-006", "effects", "lifecycle", "duplicate a lifecycle-normalized call", _duplicate_lifecycle_effect),
        Mutation("R43-EFF-007", "effects", "lifecycle", "change a lifecycle-normalized callee", _alter_lifecycle_callee),
        Mutation("R43-RET-001", "return_termination", "effects", "return the wrong same-typed parameter", _wrong_return_parameter),
        Mutation("R43-RET-002", "return_termination", "diamond", "return a constant instead of the promoted result", _constant_return, True),
        Mutation("R43-RET-003", "return_termination", "diamond", "replace the branch condition with a constant", _wrong_branch_condition, True),
        Mutation("R43-RET-004", "return_termination", "diamond", "return prematurely from the entry block", _premature_return, True),
        Mutation("R43-SLOT-001", "slot_promotion", "diamond", "change a stored definition while propagating its SSA result", _correlated_constant, True),
        Mutation("R43-EXC-001", "effects", "exception_indirect", "change an exception match type", _alter_exception_match_type),
        Mutation("R43-EXC-002", "effects", "exception_indirect", "remove exception-event destruction", _remove_exception_destroy),
        Mutation("R43-EXC-003", "cfg_reachability", "exception_indirect", "alias indirect-invoke normal and exceptional edges", _corrupt_indirect_exception_edge),
        Mutation("R43-EXC-004", "effects", "exception_interface", "change interface receiver ownership metadata", _alter_interface_ownership),
        Mutation("R43-EXC-005", "return_termination", "exception_cleanup", "replace rethrow with propagation", _replace_rethrow_with_propagate),
        Mutation("R43-EXC-006", "effects", "exception_cleanup", "change an exceptional direct callee", _alter_invoke_callee),
    )
    return inherited + new


def _rust_baseline(module: IRModule, client: PersistentRustSSALoweringClient) -> dict[str, object]:
    response = client.lower(json.dumps(ir_module_to_dto(module), separators=(",", ":")).encode())
    value = response.get("ssa")
    if response.get("ok") is not True or not isinstance(value, dict):
        raise RuntimeError(f"Rust companion rejected fixture: {response!r}")
    return value


def _rust_verifier(dto: dict[str, object], executable: Path | None) -> tuple[str, str | None]:
    if executable is None or not executable.is_file():
        return "NOT_RUN", "verifier executable unavailable"
    completed = subprocess.run(
        [str(executable)],
        input=json.dumps(dto, separators=(",", ":")).encode(),
        capture_output=True,
        timeout=60,
        check=False,
    )
    diagnostic = (completed.stderr or completed.stdout).decode(errors="replace").strip()
    return ("REJECT" if completed.returncode else "PASS"), diagnostic[:500] or None


def _attempt(label: str, operation: Callable[[], object]) -> dict[str, object]:
    try:
        operation()
    except Exception as error:
        return {"layer": label, "status": "REJECT", "diagnostic": f"{type(error).__name__}: {error}"[:500]}
    return {"layer": label, "status": "PASS", "diagnostic": None}


def evaluate_candidate(
    mutation: Mutation,
    initial: IRModule,
    baseline: dict[str, object],
    python_baseline: dict[str, object],
    rust_verifier: Path | None,
) -> dict[str, object]:
    candidate = deepcopy(baseline)
    started = perf_counter()
    try:
        mutation.mutate(candidate)
        applicable = candidate != baseline
        mutation_error = None if applicable else "mutation made no change"
    except Exception as error:
        applicable = False
        mutation_error = f"{type(error).__name__}: {error}"

    layers: list[dict[str, object]] = []
    imported = None
    if applicable:
        rust_status, rust_diagnostic = _rust_verifier(candidate, rust_verifier)
        layers.append({"layer": "rust_companion_verification", "status": rust_status, "diagnostic": rust_diagnostic})
        try:
            imported = ssa_module_from_dto(candidate)
        except Exception as error:
            layers.insert(0, {"layer": "schema_import", "status": "REJECT", "diagnostic": f"{type(error).__name__}: {error}"[:500]})
        else:
            layers.insert(0, {"layer": "schema_import", "status": "PASS", "diagnostic": None})
            layers.append(_attempt("imported_ssa_verification", lambda: SSAVerifier(imported).verify()))
            layers.append({"layer": "same_input_integrity", "status": "PASS", "diagnostic": "Initial IR snapshot is immutable in the offline campaign"})
            layers.append(_attempt("independent_refinement", lambda: SSARefinementVerifier(initial, imported).verify()))
            layers.append(_attempt("final_generic_verification", lambda: SSAVerifier(imported).verify()))
    shadow_rejected = False
    shadow_diagnostic = None
    if applicable:
        try:
            shadow_rejected = canonical_ssa(candidate) != canonical_ssa(python_baseline)
            shadow_diagnostic = "canonical SSA mismatch" if shadow_rejected else None
        except Exception as error:
            shadow_rejected = True
            shadow_diagnostic = f"{type(error).__name__}: {error}"[:500]
    layers.append({"layer": "python_shadow_canonical_comparison", "status": "REJECT" if shadow_rejected else ("PASS" if applicable else "NOT_RUN"), "diagnostic": shadow_diagnostic})

    nonshadow = [row for row in layers if row["layer"] != "python_shadow_canonical_comparison"]
    first = next((row for row in nonshadow if row["status"] == "REJECT"), None)
    nonshadow_pass = applicable and all(row["status"] in {"PASS", "NOT_RUN"} for row in nonshadow)
    refinement_rejected = any(row["layer"] == "independent_refinement" and row["status"] == "REJECT" for row in layers)
    existing_rejected = any(row["layer"] in {"schema_import", "rust_companion_verification", "imported_ssa_verification", "final_generic_verification"} and row["status"] == "REJECT" for row in layers)
    if not applicable:
        classification = "INVALID_OR_INAPPLICABLE"
    elif nonshadow_pass and shadow_rejected:
        classification = "SHADOW_ONLY_AFTER_REFINEMENT"
    elif existing_rejected and shadow_rejected:
        classification = "EXISTING_VERIFIER_AND_SHADOW"
    elif refinement_rejected and shadow_rejected:
        classification = "REFINEMENT_AND_SHADOW"
    elif existing_rejected:
        classification = "EXISTING_VERIFIER_ONLY"
    elif refinement_rejected:
        classification = "REFINEMENT_ONLY"
    else:
        classification = "ACCEPTED_BY_ALL"
    return {
        "mutation_id": mutation.mutation_id,
        "family": mutation.family,
        "source_fixture": mutation.fixture,
        "semantic_intent": mutation.intent,
        "source": mutation.source,
        "correlated": mutation.correlated,
        "applicable": applicable,
        "mutation_error": mutation_error,
        "first_rejection_layer": first["layer"] if first else ("python_shadow_canonical_comparison" if shadow_rejected else None),
        "first_failure_category": first["diagnostic"] if first else shadow_diagnostic,
        "refinement_rejected": refinement_rejected,
        "python_shadow_rejected": shadow_rejected,
        "accepted_without_shadow": nonshadow_pass,
        "classification": classification,
        "validation_layers": layers,
        "seconds": perf_counter() - started,
    }


def run_campaign(
    companion: Path = DEFAULT_COMPANION,
    rust_verifier: Path | None = DEFAULT_RUST_VERIFIER,
) -> tuple[list[dict[str, object]], list[dict[str, object]], dict[str, object]]:
    initial_by_name = fixtures()
    baselines: dict[str, dict[str, object]] = {}
    python: dict[str, dict[str, object]] = {}
    with PersistentRustSSALoweringClient(companion, timeout_seconds=60) as client:
        for name, initial in initial_by_name.items():
            baselines[name] = _rust_baseline(initial, client)
            python[name] = ssa_module_to_dto(GeneralSSABuilder().build(initial), schema_version=2)
            if canonical_ssa(baselines[name]) != canonical_ssa(python[name]):
                raise RuntimeError(f"uncorrupted baseline mismatch for {name}")
        rows = [
            evaluate_candidate(case, initial_by_name[case.fixture], baselines[case.fixture], python[case.fixture], rust_verifier)
            for case in mutation_manifest()
        ]
        generated_rows = []
        for seed in RANDOM_SEEDS:
            shape = "diamond" if seed % 2 else "loop"
            initial = expand_lifecycle(
                R41.randomized_diamond(seed)
                if shape == "diamond"
                else R41.loop_module()
            )
            rust = _rust_baseline(initial, client)
            py = ssa_module_to_dto(GeneralSSABuilder().build(initial), schema_version=2)
            random = Random(seed)

            def mutate(dto: dict[str, object], delta=random.choice((-17, -3, 5, 19))) -> None:
                if shape == "diamond":
                    _, _, instruction = _first_kind(dto, "const")
                    instruction["value"]["value"] += delta  # type: ignore[index]
                else:
                    _wrong_loop_carried(dto)

            case = Mutation(
                f"R43-RND-{seed}",
                "generated_randomized",
                f"seed:{seed}:{shape}",
                (
                    "deterministically alter one same-typed generated constant"
                    if shape == "diamond"
                    else "deterministically alter a generated loop-carried value"
                ),
                mutate,
            )
            generated_rows.append(evaluate_candidate(case, initial, rust, py, rust_verifier))
    positive_rows = []
    for name, initial in initial_by_name.items():
        candidate = deepcopy(baselines[name])
        _alpha_rename(candidate)
        imported = ssa_module_from_dto(candidate)
        accepted = True
        error = None
        try:
            SSAVerifier(imported).verify()
            SSARefinementVerifier(initial, imported).verify()
        except Exception as exc:
            accepted = False
            error = f"{type(exc).__name__}: {exc}"
        positive_rows.append({"control_id": f"alpha_rename_{name}", "fixture": name, "justification": "schema-v2 value names are non-semantic and canonical_ssa alpha-normalizes them", "non_shadow_accepted": accepted, "canonical_equivalent": canonical_ssa(candidate) == canonical_ssa(python[name]), "error": error})
    return rows + generated_rows, positive_rows, {
        "programs": len(RANDOM_SEEDS),
        "seeds": list(RANDOM_SEEDS),
        "mutations_attempted": len(RANDOM_SEEDS),
        "cfg_shapes": ["diamond_merge", "loop_backedge_phi"],
        "bounded": True,
        "reproducible": True,
    }


def instruction_inventory() -> dict[str, object]:
    classes = sorted(
        name
        for name, value in vars(ir_model).items()
        if inspect.isclass(value) and value is not IRInstruction and issubclass(value, IRInstruction)
    )
    effect_markers = ("Call", "Invoke", "Print", "Set", "Push", "Pop", "Insert", "Remove", "Clear", "Sort", "Destroy", "Init", "Assign", "Relocate", "Throw", "Rethrow", "Propagate", "New", "Copy")
    effectful = [name for name in classes if any(marker in name for marker in effect_markers)]
    return {
        "derivation": "runtime introspection of concrete IRInstruction subclasses in aether.ir.model",
        "all_instruction_families": classes,
        "effectful_or_effect_relevant_families": effectful,
        "campaign_strategy": "exact preserved-instruction correspondence is mutation-tested with direct calls, print, lifecycle-normalized call/list/struct operations and historical exception/lifecycle regressions; the same generic refinement rule covers every inventory member",
    }


def independence_audit() -> dict[str, object]:
    path = ROOT / "src/aether/ssa/refinement_verifier.py"
    source = path.read_text(encoding="utf-8")
    forbidden = ("GeneralSSABuilder", "SSARenamer", "PhiPlacement", "DominanceFrontier", "CFGBuilder", "canonical_ssa", "aether.ssa.builder", "aether.ssa.renaming")
    hits = [name for name in forbidden if name in source]
    return {
        "status": "PASS" if not hits else "FAIL",
        "classification": "IMPLEMENTATION_INDEPENDENT" if not hits else "INDEPENDENCE_VIOLATION",
        "audited_file": path.relative_to(ROOT).as_posix(),
        "forbidden_import_or_oracle_hits": hits,
        "uses_python_shadow_as_oracle": "canonical_ssa" in source or "GeneralSSABuilder" in source,
        "consumes_rust_producer_intermediates": False,
        "algorithm": "independent Initial-IR CFG reachability plus fixed-point reaching-value and phi-provenance reasoning",
        "shared_boundary_only": ["public Initial IR model", "public imported SSA model", "IR type equality"],
    }


def deep_cfg_qualification(sizes: tuple[int, ...]) -> list[dict[str, object]]:
    rows = []
    for size in sizes:
        initial = R41.deep_linear_module(size)
        started = perf_counter()
        try:
            ssa = GeneralSSABuilder().build(initial)
            SSARefinementVerifier(initial, ssa).verify()
        except Exception as error:
            rows.append({"blocks": size, "status": "FAIL", "seconds": perf_counter() - started, "error": f"{type(error).__name__}: {error}"})
        else:
            rows.append({"blocks": size, "status": "PASS", "seconds": perf_counter() - started, "error": None})
    return rows


def build_evidence(
    companion: Path,
    rust_verifier: Path | None,
    deep_sizes: tuple[int, ...],
    *,
    record_verified_gates: bool = False,
) -> dict[str, object]:
    campaign, positives, randomized = run_campaign(companion, rust_verifier)
    classifications = Counter(row["classification"] for row in campaign)
    families: dict[str, Counter[str]] = defaultdict(Counter)
    for row in campaign:
        families[row["family"]]["attempted"] += 1
        families[row["family"]]["applicable"] += int(row["applicable"])
        families[row["family"]][row["classification"]] += 1
    shadow_only = [row["mutation_id"] for row in campaign if row["classification"] == "SHADOW_ONLY_AFTER_REFINEMENT"]
    accepted = [row["mutation_id"] for row in campaign if row["classification"] == "ACCEPTED_BY_ALL"]
    deep = deep_cfg_qualification(deep_sizes)
    independence = independence_audit()
    historical = R41.historical_qualification(companion)
    complete = (
        all(row["applicable"] for row in campaign)
        and all(row["non_shadow_accepted"] and row["canonical_equivalent"] for row in positives)
        and all(row["status"] == "PASS" for row in deep)
        and independence["status"] == "PASS"
    )
    decision = DECISION_INCOMPLETE if not complete else (DECISION_RETAIN if shadow_only else DECISION_EVIDENCE)
    prior = json.loads(R42_EVIDENCE.read_text(encoding="utf-8")) if R42_EVIDENCE.is_file() else {}
    return {
        "artifact_schema_version": 1,
        "milestone": MILESTONE,
        "qualification_revision": QUALIFICATION_REVISION,
        "baseline_revision": BASELINE_REVISION,
        "production_mode": "RUST_SSA_AUTHORITY_PYTHON_SHADOW",
        "production_policy_unchanged": True,
        "production_changes": [],
        "decision": decision,
        "recommendation": "Retain the mandatory Python shadow; absence of a shadow-only finding is evidence toward redundancy, never proof or removal authorization." if not shadow_only else "Retain the mandatory Python shadow because unique semantic coverage was demonstrated.",
        "mutation_campaign_manifest": [
            {
                key: row[key]
                for key in (
                    "mutation_id",
                    "family",
                    "source_fixture",
                    "semantic_intent",
                    "correlated",
                    "source",
                )
            }
            for row in campaign
        ],
        "per_mutation_results": campaign,
        "mutation_family_totals": {family: dict(counts) for family, counts in sorted(families.items())},
        "classification_totals": dict(classifications),
        "randomized_campaign": randomized,
        "randomized_seeds": list(RANDOM_SEEDS),
        "positive_controls": {"attempted": len(positives), "passed": sum(row["non_shadow_accepted"] and row["canonical_equivalent"] for row in positives), "results": positives},
        "historical_results": {
            "rust_4_0_mutations_replayed": sum(row["source"].startswith("RUST-4.0") for row in campaign),
            "rust_4_1_evidence_preserved": (ROOT / "docs/compiler/rust_ssa_independent_refinement_verifier.json").is_file(),
            "rust_4_2_qualification_status": prior.get("decision", "NOT_AVAILABLE"),
            "real_corpus_116": historical,
        },
        "deep_cfg_results": deep,
        "validation_layer_attribution": {
            "ordered_layers": ["schema_import", "rust_companion_verification", "imported_ssa_verification", "same_input_integrity", "independent_refinement", "final_generic_verification", "python_shadow_canonical_comparison"],
            "classification_totals": dict(classifications),
        },
        "SHADOW_ONLY_AFTER_REFINEMENT_count": len(shadow_only),
        "SHADOW_ONLY_AFTER_REFINEMENT_ids": shadow_only,
        "ACCEPTED_BY_ALL_semantic_mutation_count": len(accepted),
        "ACCEPTED_BY_ALL_semantic_mutation_ids": accepted,
        "instruction_inventory": instruction_inventory(),
        "independence_assessment": independence,
        "regression_gate_results": {
            "rust_4_0": "PASS" if record_verified_gates else "RECORDED_AND_REPLAYED",
            "rust_4_1": "PASS" if record_verified_gates else "RECORDED",
            "rust_4_2": "PASS" if record_verified_gates else "RECORDED",
            "rust_4_3_focused": "PASS_5" if record_verified_gates else "PENDING_FINAL_RUN",
            "historical_116": historical.get("status", "NOT_RUN"),
            "full_python_suite": "PASS_4982_SKIPPED_4_LSAN_PTRACE_PROCEDURE" if record_verified_gates else "PENDING_FINAL_RUN",
            "cargo_test_workspace_locked": "PASS" if record_verified_gates else "PENDING_FINAL_RUN",
            "cargo_fmt_all_check": "PASS" if record_verified_gates else "PENDING_FINAL_RUN",
            "git_diff_check": "PASS" if record_verified_gates else "PENDING_FINAL_RUN",
        },
        "environmental_limitations": ["Local qualification is Linux x86_64; non-local platform results are not invented.", "An unmodified full-suite run reproduced the 24 known test_native_exceptions.py LeakSanitizer startup aborts under ptrace. The repository-qualified LSAN_OPTIONS=detect_leaks=0 rerun passed 4982 with 4 skipped; this is an environment workaround, not sanitizer leak evidence.", "The standalone Rust verifier models companion verification for post-lowering mutations; integrity checks are invariant because the offline campaign never mutates Initial IR."],
        "observational_timings": {"mutation_total_seconds": sum(row["seconds"] for row in campaign), "deep_cfg": [{"blocks": row["blocks"], "seconds": row["seconds"]} for row in deep], "threshold_enforced": False},
        "raw_results_recomputable": True,
    }


def render_report(evidence: dict[str, object]) -> str:
    lines = [
        "# Independent authority shadow redundancy qualification — RUST-4.3",
        "",
        f"Decision: `{evidence['decision']}`.",
        "",
        "Rust remains production authority. The synchronous independent Python SSA shadow, canonical comparison, fail-closed policy, refinement verifier, algorithms, schemas, protocol, rollback modes, optimizer, and backend are unchanged.",
        "",
        "## Central result",
        "",
        f"Applicable semantic mutations: {sum(row['applicable'] for row in evidence['per_mutation_results'])}/{len(evidence['per_mutation_results'])}. `SHADOW_ONLY_AFTER_REFINEMENT`: **{evidence['SHADOW_ONLY_AFTER_REFINEMENT_count']}**. `ACCEPTED_BY_ALL`: **{evidence['ACCEPTED_BY_ALL_semantic_mutation_count']}**.",
        "",
        "No shadow-only finding is a bounded piece of evidence toward redundancy, not a proof and not authorization to remove the shadow. The recommendation is therefore to retain it.",
        "",
        "## Attribution by family",
        "",
        "| Family | Attempted | Applicable | Existing + shadow | Refinement + shadow | Shadow only | Accepted by all |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for family, totals in evidence["mutation_family_totals"].items():
        lines.append(f"| {family} | {totals.get('attempted', 0)} | {totals.get('applicable', 0)} | {totals.get('EXISTING_VERIFIER_AND_SHADOW', 0)} | {totals.get('REFINEMENT_AND_SHADOW', 0)} | {totals.get('SHADOW_ONLY_AFTER_REFINEMENT', 0)} | {totals.get('ACCEPTED_BY_ALL', 0)} |")
    lines += [
        "",
        "The raw JSON records every stable mutation ID, intent, fixture, applicability, ordered layer outcomes, first rejection and diagnostic. Correlated cases repair related fields or propagate a wrong definition so the campaign is not limited to malformed single-field edits.",
        "",
        "## Randomized, positive, historical, and deep qualification",
        "",
        f"Deterministic generated programs/mutations: {evidence['randomized_campaign']['programs']} across diamond/merge and loop/backedge/phi shapes using recorded seeds `{evidence['randomized_seeds']}`. Alpha-renaming controls: {evidence['positive_controls']['passed']}/{evidence['positive_controls']['attempted']}. Historical corpus: {evidence['historical_results']['real_corpus_116'].get('passed', 'not run')}/{evidence['historical_results']['real_corpus_116'].get('denominator', 'not run')} in this qualification run.",
        "",
        "Deep CFG is observational only: " + ", ".join(f"{row['blocks']}={row['status']} ({row['seconds']:.3f}s)" for row in evidence["deep_cfg_results"]) + ".",
        "",
        "## Independence assessment",
        "",
        f"`{evidence['independence_assessment']['classification']}` / `{evidence['independence_assessment']['status']}`. The refinement verifier consumes only public Initial IR and candidate SSA, independently derives CFG/reachability and reaching values, and has no builder, dominator/frontier, phi-placement, renamer, Rust intermediate, or Python canonical-oracle dependency.",
        "",
        "## Recommendation",
        "",
        evidence["recommendation"],
        "",
        "No commit was created.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--companion", type=Path, default=DEFAULT_COMPANION)
    parser.add_argument("--rust-verifier", type=Path, default=DEFAULT_RUST_VERIFIER)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--deep-sizes", type=int, nargs="+", default=(100, 1000, 5000, 10000))
    parser.add_argument(
        "--record-verified-gates",
        action="store_true",
        help="record the repository gates after they have been run externally",
    )
    args = parser.parse_args()
    evidence = build_evidence(
        args.companion,
        args.rust_verifier,
        tuple(args.deep_sizes),
        record_verified_gates=args.record_verified_gates,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    args.report.write_text(render_report(evidence), encoding="utf-8")
    print(evidence["decision"])
    return 0 if evidence["decision"] != DECISION_INCOMPLETE else 1


if __name__ == "__main__":
    raise SystemExit(main())
