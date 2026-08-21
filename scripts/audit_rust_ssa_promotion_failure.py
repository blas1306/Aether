#!/usr/bin/env python3
"""Inspect RUST-3.6a minimized reproducers without changing SSA semantics."""

from __future__ import annotations

import argparse
from difflib import unified_diff
import json
from pathlib import Path
from typing import Any

from aether.ir.dto import ir_module_from_dto, ir_module_to_dto
from aether.pipeline import IRBackend, SSAPipeline, prepare_typed_program
from aether.ssa import GeneralSSABuilder, SSAVerifier
from aether.ssa.dto import ssa_module_from_dto, ssa_module_to_dto
from aether.ssa.optimizer import SSAOptimizerPipeline
from aether.ssa.shadow import (
    SSALoweringAuthorityConfiguration,
    SSALoweringAuthorityMode,
    SSAShadowFailure,
    canonical_ssa,
    production_rust_ssa_lowering_client,
)
from aether.typechecker import TypeChecker


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FIXTURES = ROOT / "tests/fixtures/rust_ssa_promotion_failure"


def _first_difference(left: Any, right: Any, path: str = "$") -> str | None:
    if type(left) is not type(right):
        return path
    if isinstance(left, dict):
        if left.keys() != right.keys():
            return path
        for key in left:
            difference = _first_difference(left[key], right[key], f"{path}.{key}")
            if difference:
                return difference
    elif isinstance(left, list):
        if len(left) != len(right):
            return path
        for index, (left_item, right_item) in enumerate(zip(left, right)):
            difference = _first_difference(
                left_item, right_item, f"{path}[{index}]"
            )
            if difference:
                return difference
    elif left != right:
        return path
    return None


def _instruction_diff(python: dict[str, Any], rust: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    for py_function, rs_function in zip(python["functions"], rust["functions"]):
        for py_block, rs_block in zip(py_function["blocks"], rs_function["blocks"]):
            if py_block["instructions"] == rs_block["instructions"]:
                continue
            py_lines = [
                json.dumps(item, sort_keys=True)
                for item in py_block["instructions"]
            ]
            rs_lines = [
                json.dumps(item, sort_keys=True)
                for item in rs_block["instructions"]
            ]
            lines.extend(
                unified_diff(
                    py_lines,
                    rs_lines,
                    fromfile=f"python:{py_function['name']}:{py_block['name']}",
                    tofile=f"rust:{rs_function['name']}:{rs_block['name']}",
                    lineterm="",
                )
            )
            return lines
    return lines


def _mode_result(ir_module: object, mode: SSALoweringAuthorityMode) -> dict[str, Any]:
    pipeline = SSAPipeline(
        authority_configuration=SSALoweringAuthorityConfiguration(mode)
    )
    try:
        result = pipeline.run(ir_module)  # type: ignore[arg-type]
    except SSAShadowFailure as exc:
        return {
            "outcome": "fail_closed",
            "returned_ssa_origin": None,
            "mismatch_status": exc.report.classification,
            "phase": exc.report.phase,
            "diagnostic": exc.report.first_difference,
        }
    SSAOptimizerPipeline(verify_after_each=True).run(result.ssa_module)
    return {
        "outcome": "optimizer_pass",
        "returned_ssa_origin": pipeline.last_returned_ssa_origin,
        "mismatch_status": (
            getattr(pipeline.last_authority_report, "classification", None)
            or "not_compared"
        ),
        "phase": "post_optimizer",
        "diagnostic": None,
    }


def inspect_fixture(path: Path) -> dict[str, Any]:
    typed = prepare_typed_program(
        path.read_text(encoding="utf-8"), TypeChecker(source_root=path.parent)
    )
    initial_ir = IRBackend().lower_verified(typed)
    initial_dto = ir_module_to_dto(initial_ir)
    payload = json.dumps(
        initial_dto, sort_keys=True, separators=(",", ":")
    ).encode()

    python_ssa = GeneralSSABuilder().build(ir_module_from_dto(initial_dto))
    SSAVerifier(python_ssa).verify()
    python_dto = ssa_module_to_dto(python_ssa, schema_version=2)

    response = production_rust_ssa_lowering_client().lower(payload)
    rust_error = None
    rust_dto = response.get("ssa") if response.get("ok") is True else None
    rust_ssa = None
    rust_verification = "not_reached"
    if isinstance(rust_dto, dict):
        rust_ssa = ssa_module_from_dto(rust_dto)
        try:
            SSAVerifier(rust_ssa).verify()
            rust_verification = "pass"
        except Exception as exc:  # diagnostic tool records the exact boundary
            rust_verification = f"fail: {exc}"
    else:
        rust_error = str(response.get("error", "malformed Rust response"))

    canonical_equal = False
    first_difference = None
    instruction_diff: list[str] = []
    if isinstance(rust_dto, dict):
        python_canonical = canonical_ssa(python_dto)
        rust_canonical = canonical_ssa(rust_dto)
        first_difference = _first_difference(python_canonical, rust_canonical)
        canonical_equal = first_difference is None
        instruction_diff = _instruction_diff(python_canonical, rust_canonical)

    comparison_reached = rust_error is None and rust_verification == "pass"
    optimizer_blocked = not comparison_reached or not canonical_equal

    return {
        "fixture": str(path.relative_to(ROOT)),
        "boundaries": {
            "A_verified_initial_ir": "pass",
            "B_lifecycle_normalized_initial_ir": (
                "rust_lane_failure"
                if rust_error
                else "divergent_lifecycle_operations"
                if not canonical_equal
                else "pass"
            ),
            "C_pre_import_rust_owned_ssa": (
                "not_reached" if rust_error else "produced_and_rust_verified"
            ),
            "D_schema_v2_dto": "not_reached" if rust_dto is None else "produced",
            "E_python_imported_rust_ssa": (
                "not_reached"
                if rust_ssa is None
                else "produced_and_verified"
                if rust_verification == "pass"
                else rust_verification
            ),
            "F_authoritative_python_ssa": "verified",
            "G_canonical_ssa": (
                "not_reached"
                if not comparison_reached
                else "equal"
                if canonical_equal
                else "divergent"
            ),
            "H_optimizer_input": "blocked" if optimizer_blocked else "reachable",
            "I_post_optimizer_ssa": (
                "blocked" if optimizer_blocked else "not_run_by_audit"
            ),
            "J_backend_native": (
                "blocked" if optimizer_blocked else "not_run_by_audit"
            ),
        },
        "rust_lane_error": rust_error,
        "python_import_verification": rust_verification,
        "canonical_equal": canonical_equal,
        "first_difference": first_difference,
        "instruction_diff": instruction_diff,
        "mode_matrix": {
            mode.name: _mode_result(initial_ir, mode)
            for mode in SSALoweringAuthorityMode
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("fixtures", nargs="*", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    fixtures = args.fixtures or sorted(DEFAULT_FIXTURES.glob("*.ae"))
    report = {"fixtures": [inspect_fixture(path.resolve()) for path in fixtures]}
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
