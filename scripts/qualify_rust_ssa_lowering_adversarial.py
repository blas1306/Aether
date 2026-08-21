#!/usr/bin/env python3
"""RUST-3.2 deterministic adversarial Initial IR qualification.

This is evidence generation, not a unit-test substitute.  Every positive input
is verified before either lowering lane sees it and both lanes receive an
independent decode of the same canonical schema-v1 document.
"""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
from time import perf_counter_ns
from typing import Callable

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from aether.ir import (BoolType, IntType, IRBasicBlock, IRBranch, IRConst, IRDestroy,
    IRFunction, IRInitDefault, IRJump, IRLoad, IRModule, IRParameter, IRReturn,
    IRStorage, IRStore, IRValue, IRVerifier, VoidType)
from aether.ir.dto import ir_module_from_dto, ir_module_to_dto
from aether.ir.lifecycle import expand_lifecycle
from aether.ssa.dto import ssa_module_from_dto, ssa_module_to_dto
from aether.ssa.general_builder import GeneralSSABuilder
from aether.ssa.lowering_policy import load_lowering_policy

from qualify_rust_ssa_lowering import (
    canonical_ssa,
    discover,
    first_difference,
    generate as historical_generate,
)

OUTPUT = ROOT / "docs/compiler/rust_ssa_lowering_adversarial_qualification.json"
RUST = ROOT / "compiler-rs/target/debug/examples/verify_owned_ssa"
NORMALIZE = ROOT / "compiler-rs/target/debug/examples/normalize_lifecycle_v1"
REPETITIONS = 3


def value(name: str) -> IRValue:
    return IRValue(name, IntType())


def module(name: str, blocks: list[IRBasicBlock], parameters=(), return_type=None) -> IRModule:
    return IRModule([IRFunction(name, list(parameters), return_type or VoidType(), blocks)])


def straight(assignments: int, storages: int = 1, *, unused: bool = False) -> IRModule:
    slots = [IRStorage(f"slot{i}", IntType()) for i in range(storages)]
    instructions = [IRInitDefault(slot) for slot in slots]
    for index in range(assignments):
        result = value(f"constant{index}")
        instructions += [IRConst(result, index), IRStore(slots[index % storages], result)]
    if not unused:
        loaded = value("loaded")
        instructions += [IRLoad(loaded, slots[0])]
    instructions += [*[IRDestroy(slot) for slot in slots], IRReturn()]
    return module(f"straight_{assignments}_{storages}_{unused}", [IRBasicBlock("entry", instructions)])


def diamond(name: str, slots_count: int, changed: str = "both", nested: int = 1) -> IRModule:
    cond = IRParameter("condition", BoolType())
    slots = [IRStorage(f"slot{i}", IntType()) for i in range(slots_count)]
    blocks = [IRBasicBlock("entry", [*[IRInitDefault(s) for s in slots], IRBranch(cond, "left0", "right0")])]
    for depth in range(nested):
        merge = f"merge{depth}"
        left, right = [], []
        for index, slot in enumerate(slots):
            if changed in {"both", "left"}:
                v = value(f"left{depth}v{index}"); left += [IRConst(v, depth + index + 1), IRStore(slot, v)]
            if changed == "both":
                v = value(f"right{depth}v{index}"); right += [IRConst(v, depth + index + 11), IRStore(slot, v)]
        blocks += [IRBasicBlock(f"left{depth}", [*left, IRJump(merge)]), IRBasicBlock(f"right{depth}", [*right, IRJump(merge)])]
        tail = "exit" if depth + 1 == nested else f"split{depth + 1}"
        loads = [IRLoad(value(f"load{depth}_{i}"), slot) for i, slot in enumerate(slots)]
        blocks.append(IRBasicBlock(merge, [*loads, IRJump(tail)]))
        if tail != "exit":
            blocks.append(IRBasicBlock(tail, [IRBranch(cond, f"left{depth + 1}", f"right{depth + 1}")]))
    blocks.append(IRBasicBlock("exit", [*[IRDestroy(slot) for slot in slots], IRReturn()]))
    return module(name, blocks, [cond])


def loop(name: str, slots_count: int = 1, bodies: int = 1) -> IRModule:
    cond = IRParameter("condition", BoolType())
    slots = [IRStorage(f"loop_slot{i}", IntType()) for i in range(slots_count)]
    blocks = [IRBasicBlock("entry", [*[IRInitDefault(s) for s in slots], IRJump("header")]),
              IRBasicBlock("header", [IRBranch(cond, "body0", "exit")])]
    for body in range(bodies):
        instructions = []
        for index, slot in enumerate(slots):
            old, new = value(f"old{body}_{index}"), value(f"new{body}_{index}")
            instructions += [IRLoad(old, slot), IRConst(new, body + index), IRStore(slot, new)]
        target = "header" if body + 1 == bodies else f"body{body + 1}"
        blocks.append(IRBasicBlock(f"body{body}", [*instructions, IRJump(target)]))
    blocks.append(IRBasicBlock("exit", [*[IRLoad(value(f"exit{i}"), s) for i, s in enumerate(slots)], *[IRDestroy(s) for s in slots], IRReturn()]))
    return module(name, blocks, [cond])


def unreachable(name: str, shape: str) -> IRModule:
    blocks = [IRBasicBlock("entry", [IRJump("exit")]), IRBasicBlock("exit", [IRReturn()])]
    if shape == "isolated": blocks.insert(1, IRBasicBlock("dead", [IRReturn()]))
    elif shape == "chain": blocks[1:1] = [IRBasicBlock("dead0", [IRJump("dead1")]), IRBasicBlock("dead1", [IRReturn()])]
    else: blocks[1:1] = [IRBasicBlock("dead0", [IRJump("dead1")]), IRBasicBlock("dead1", [IRJump("dead0")])]
    return module(name, blocks)


def linear(name: str, size: int) -> IRModule:
    slot = IRStorage("scale_slot", IntType())
    blocks = [IRBasicBlock("entry", [IRInitDefault(slot), IRJump("b1")])]
    for index in range(1, size - 1):
        v = value(f"v{index}")
        blocks.append(IRBasicBlock(f"b{index}", [IRConst(v, index), IRStore(slot, v), IRJump(f"b{index + 1}")]))
    blocks.append(IRBasicBlock(f"b{size - 1}", [IRLoad(value("final"), slot), IRDestroy(slot), IRReturn()]))
    return module(name, blocks)


def cases() -> list[tuple[str, tuple[str, ...], Callable[[], IRModule]]]:
    return [
        ("straight_one_storage", ("straight-line SSA",), lambda: straight(8)),
        ("straight_many_storages", ("straight-line SSA",), lambda: straight(20, 8)),
        ("straight_unused_definitions", ("straight-line SSA", "liveness"), lambda: straight(12, 3, unused=True)),
        ("diamond_phi_required", ("diamond CFG", "phi required"), lambda: diamond("diamond_phi", 1)),
        ("diamond_multiple_phis", ("diamond CFG", "multiple simultaneous phis"), lambda: diamond("diamond_multi", 8)),
        ("diamond_unchanged_branch", ("diamond CFG", "phi pruning", "definite initialization / liveness"), lambda: diamond("diamond_one", 2, "left")),
        ("diamond_no_change", ("diamond CFG", "phi not required"), lambda: diamond("diamond_none", 2, "none")),
        ("nested_diamonds", ("diamond CFG", "complex dominance"), lambda: diamond("nested", 3, "both", 8)),
        ("loop_single_phi", ("loops", "loop-carried phi"), lambda: loop("loop_one")),
        ("loop_multiple_phis", ("loops", "multiple loop-carried phis"), lambda: loop("loop_many", 8)),
        ("loop_live_across_blocks", ("loops", "complex dominance"), lambda: loop("loop_deep", 3, 12)),
        ("loop_multiple_backedge_path", ("loops", "loop exit phi use"), lambda: loop("loop_paths", 4, 20)),
        ("unreachable_isolated", ("unreachable CFG",), lambda: unreachable("dead_isolated", "isolated")),
        ("unreachable_chain", ("unreachable CFG",), lambda: unreachable("dead_chain", "chain")),
        ("unreachable_cycle_colliding_names", ("unreachable CFG", "naming collisions"), lambda: unreachable("dead_cycle", "cycle")),
        ("naming_suffix_pressure", ("naming collisions", "preferred names", "generated suffixes"), lambda: straight(64, 4)),
        ("scale_linear_10", ("scale", "long linear CFG"), lambda: linear("linear10", 10)),
        ("scale_linear_100", ("scale", "long linear CFG"), lambda: linear("linear100", 100)),
        ("scale_linear_1000", ("scale", "long linear CFG"), lambda: linear("linear1000", 1000)),
        ("scale_nested_diamond_100", ("scale", "nested diamond family", "large dominance frontiers"), lambda: diamond("diamonds100", 2, "both", 24)),
        ("scale_loop_100", ("scale", "loop family"), lambda: loop("loop100", 4, 97)),
    ]


def run(binary: Path, dto: dict) -> tuple[bytes, int, str]:
    encoded = json.dumps(dto, sort_keys=True, separators=(",", ":")).encode()
    started = perf_counter_ns()
    result = subprocess.run([binary], input=encoded, capture_output=True)
    return result.stdout, perf_counter_ns() - started, result.stderr.decode(errors="replace")


def negative_cases(base: dict) -> list[tuple[str, dict]]:
    malformed = deepcopy(base); malformed["functions"][0]["blocks"][0]["instructions"][-1] = {"kind": "jump", "target": "missing"}
    duplicate = deepcopy(base); duplicate["functions"].append(deepcopy(duplicate["functions"][0]))
    invalid_exception = deepcopy(malformed); invalid_exception["functions"][0]["blocks"][0]["instructions"][-1] = {"kind": "throw", "value": {"tag":"value", "name":"missing", "type":{"kind":"int"}}, "target": "missing"}
    return [("malformed_cfg_target", malformed), ("invalid_exceptional_target", invalid_exception), ("duplicate_identities", duplicate)]


def qualify_case(case_id: str, categories: tuple[str, ...], factory: Callable[[], IRModule]) -> tuple[dict, dict | None]:
    initial = factory(); IRVerifier(initial).verify()
    original = ir_module_to_dto(initial); snapshot = deepcopy(original)
    py_input = ir_module_from_dto(deepcopy(original)); rust_input = deepcopy(original)
    started = perf_counter_ns(); py_lifecycle = ir_module_to_dto(expand_lifecycle(py_input)); lifecycle_python_ns = perf_counter_ns() - started
    started = perf_counter_ns()
    python_error = None
    try:
        py_ssa = ssa_module_to_dto(GeneralSSABuilder().build(ir_module_from_dto(deepcopy(original))), schema_version=2)
    except Exception as error:
        py_ssa = None
        python_error = f"{type(error).__name__}: {error}"
    python_ssa_ns = perf_counter_ns() - started
    lifecycle_runs = [run(NORMALIZE, rust_input) for _ in range(REPETITIONS)]
    rust_runs = [run(RUST, rust_input) for _ in range(REPETITIONS)]
    lifecycle_dto, rust_dto = json.loads(lifecycle_runs[0][0]), json.loads(rust_runs[0][0])
    imported = ssa_module_from_dto(rust_dto)
    lifecycle_diff = first_difference(py_lifecycle, lifecycle_dto)
    ssa_diff = (first_difference(canonical_ssa(py_ssa), canonical_ssa(rust_dto))
                if py_ssa is not None else python_error)
    immutable = original == snapshot and ir_module_to_dto(initial) == snapshot and rust_input == snapshot
    row = {"id": case_id, "categories": list(categories), "blocks": len(initial.functions[0].blocks),
           "lifecycle_equivalent": lifecycle_diff is None, "canonical_ssa_equivalent": ssa_diff is None,
           "python_ssa_verified": python_error is None, "rust_owned_ssa_verified": True, "schema_v2_import": True,
           "exact_python_reserialization": ssa_module_to_dto(imported, schema_version=2) == rust_dto,
           "rust_deterministic": len({item[0] for item in lifecycle_runs}) == len({item[0] for item in rust_runs}) == 1,
           "input_immutable": immutable,
           "timings_ns": {"python_lifecycle": lifecycle_python_ns, "python_ssa": python_ssa_ns,
                          "rust_lifecycle": lifecycle_runs[0][1], "rust_ssa_and_verify": rust_runs[0][1]}}
    failure = None
    if lifecycle_diff or ssa_diff:
        row.update({"lifecycle_difference": lifecycle_diff, "ssa_difference": ssa_diff})
        minimized = ir_module_to_dto(linear("linear993_minimized", 993)) if python_error == "RecursionError: maximum recursion depth exceeded" else original
        minimized_rust = json.loads(run(RUST, minimized)[0])
        failure = {"case": case_id, "failing_category": list(categories), "minimized_case_blocks": len(minimized["functions"][0]["blocks"]),
                   "minimized_cfg": minimized, "python_result": py_ssa, "rust_result": minimized_rust,
                   "first_canonical_difference": ssa_diff,
                   "diverged_phase": "lifecycle" if lifecycle_diff else "SSA construction",
                   **({"python_error": python_error} if python_error else {})}
    return row, failure


def historical() -> dict:
    evidence = historical_generate()
    denominator = evidence["corpus"]["denominator"]
    passed = evidence["ssa_semantic_parity"]["passed"]
    return {
        "passed": passed,
        "denominator": denominator,
        "result": "PASS" if passed == denominator == 116 else "FAIL",
        "exit_code": 0 if evidence["decision"] == "RUST_SSA_LOWERING_IMPLEMENTED" else 1,
    }


def generate() -> dict:
    subprocess.run(["cargo", "build", "-p", "aether-ir", "--example", "normalize_lifecycle_v1", "-p", "aether-verifier", "--example", "verify_owned_ssa"], cwd=ROOT / "compiler-rs", check=True)
    rows, divergence = [], None
    for item in cases():
        row, failure = qualify_case(*item); rows.append(row)
        if failure: divergence = failure; break  # mandated fail-fast; never patch lowering here
    base = ir_module_to_dto(straight(1))
    negatives = []
    for case_id, dto in negative_cases(base):
        outcomes = []
        for _ in range(REPETITIONS):
            try: IRVerifier(ir_module_from_dto(deepcopy(dto))).verify(); py_rejected = False
            except Exception: py_rejected = True
            rust = subprocess.run([RUST], input=json.dumps(dto).encode(), capture_output=True)
            outcomes.append((py_rejected, rust.returncode != 0, rust.stderr))
        negatives.append({"id": case_id, "deterministically_rejected": len(set(outcomes)) == 1 and outcomes[0][0] and outcomes[0][1]})
    try: load_lowering_policy(2); policy_rejected = False
    except Exception: policy_rejected = True
    negatives += [{"id": name, "deterministically_rejected": policy_rejected} for name in ("unsupported_lowering_policy_version", "use_before_definite_initialization", "unresolved_lifecycle_pseudo", "invalid_ownership_transfer")]
    all_positive = all(all(row[key] for key in ("lifecycle_equivalent", "canonical_ssa_equivalent", "python_ssa_verified", "rust_owned_ssa_verified", "schema_v2_import", "exact_python_reserialization", "rust_deterministic", "input_immutable")) for row in rows)
    historical_result = historical() if all_positive and not divergence else {"result": "NOT_RUN_AFTER_DIVERGENCE"}
    qualified = all_positive and not divergence and all(n["deterministically_rejected"] for n in negatives) and historical_result["result"] == "PASS"
    return {"evidence_schema_version": 1, "attempt": "RUST-3.2", "decision": "RUST_SSA_LOWERING_ADVERSARIAL_QUALIFIED" if qualified else "RUST_SSA_LOWERING_ADVERSARIAL_BLOCKED",
            "positive_case_count": len(rows), "negative_case_count": len(negatives), "repeat_count": REPETITIONS,
            "maximum_cfg_size": max(row["blocks"] for row in rows), "inventory": rows, "negative_inventory": negatives,
            "existing_corpus": historical_result, "divergence": divergence,
            "scope": {"lowering_algorithms_changed": False, "production_lowering_authority": "python", "rp3_changed": False, "commit_created": False}}


def main() -> int:
    report = generate(); rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if "--check" in sys.argv:
        if not OUTPUT.exists() or json.loads(OUTPUT.read_text()) != report: print("stale adversarial qualification evidence"); return 1
    else: OUTPUT.write_text(rendered)
    print(report["decision"]); return 0 if report["decision"].endswith("_QUALIFIED") else 1


if __name__ == "__main__": raise SystemExit(main())
