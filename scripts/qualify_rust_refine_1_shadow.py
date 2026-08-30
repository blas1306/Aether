#!/usr/bin/env python3
"""Differential qualification for the RUST-REFINE-1 shadow verifier.

The adapter serialization in this script exists only to place the same pair in
two processes.  The Rust verifier itself consumes normalized owned Initial IR
and ``OwnedSsaModule`` directly.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from aether.ir.dto import ir_module_to_dto  # noqa: E402
from aether.ir.lifecycle import expand_lifecycle  # noqa: E402
from aether.pipeline import IRBackend, prepare_typed_program  # noqa: E402
from aether.ssa import SSARefinementVerifier  # noqa: E402
from aether.ssa.dto import ssa_module_from_dto  # noqa: E402
from aether.ssa.shadow import PersistentRustSSALoweringClient  # noqa: E402
from aether.typechecker import TypeChecker  # noqa: E402


COMPANION = ROOT / "compiler-rs/target/debug/aether-ssa-shadow"
RUST_VERIFIER = (
    ROOT / "compiler-rs/target/debug/examples/verify_owned_ssa_refinement"
)
ORACLE_QUALIFIER = (
    ROOT / "scripts/qualify_rust_ssa_independent_refinement_verifier.py"
)


def _load_oracle_qualification():
    spec = importlib.util.spec_from_file_location(
        "rust_refine_1_oracle_cases", ORACLE_QUALIFIER
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load existing refinement qualification cases")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ORACLE = _load_oracle_qualification()


def _rust_outcome(initial, ssa: dict[str, object]) -> dict[str, object]:
    payload = {
        "initial": ir_module_to_dto(initial),
        "ssa": ssa,
    }
    completed = subprocess.run(
        [str(RUST_VERIFIER)],
        input=json.dumps(payload, separators=(",", ":")).encode(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=60,
    )
    if completed.returncode != 0:
        return {
            "accepted": False,
            "category": "schema_or_adapter_rejection",
            "phase": "pair_import",
            "message": completed.stderr.decode(errors="replace"),
        }
    response = json.loads(completed.stdout)
    if response["ok"] is True:
        return {
            "accepted": True,
            "category": None,
            "phase": None,
        }
    error = response["error"]
    return {
        "accepted": False,
        "category": "ssa_refinement_verification",
        "phase": "refinement_verification",
        "detail_category": error["category"],
        "detail_phase": error["phase"],
        "function": error["function"],
        "block": error["block"],
        "instruction": error["instruction_index"],
        "source_location": error["source_location"],
        "code": error["code"],
        "message": error["message"],
    }


def _python_context(message: str) -> dict[str, object]:
    function = re.search(r"function '([^']+)'", message)
    block = re.search(r"block '([^']+)'", message)
    instruction = re.search(r"instruction (\d+)", message)
    return {
        "function": function.group(1) if function else None,
        "block": block.group(1) if block else None,
        "instruction": int(instruction.group(1)) if instruction else None,
    }


def _python_outcome(initial, ssa: dict[str, object]) -> dict[str, object]:
    try:
        imported = ssa_module_from_dto(ssa)
    except Exception as error:
        return {
            "accepted": False,
            "category": "schema_or_adapter_rejection",
            "phase": "pair_import",
            "message": f"{type(error).__name__}: {error}",
        }
    try:
        SSARefinementVerifier(initial, imported).verify()
    except Exception as error:
        message = str(error)
        return {
            "accepted": False,
            "category": "ssa_refinement_verification",
            "phase": "refinement_verification",
            **_python_context(message),
            "source_location": None,
            "message": message,
        }
    return {"accepted": True, "category": None, "phase": None}


def _classification(
    rust: dict[str, object], python: dict[str, object]
) -> str:
    if rust["accepted"] != python["accepted"]:
        return "acceptance_divergence"
    if rust["accepted"] is True:
        return "agreement"
    if {rust["phase"], python["phase"]} == {
        "pair_import",
        "refinement_verification",
    }:
        return "input_domain_divergence"
    if (rust["category"], rust["phase"]) != (
        python["category"],
        python["phase"],
    ):
        return "category_or_phase_divergence"
    for field in ("function", "block", "instruction", "source_location"):
        expected = python.get(field)
        if expected is not None and rust.get(field) != expected:
            return "diagnostic_context_divergence"
    return "agreement"


def _rust_baseline(client, initial) -> dict[str, object]:
    response = client.lower(
        json.dumps(ir_module_to_dto(initial), separators=(",", ":")).encode()
    )
    ssa = response.get("ssa")
    if response.get("ok") is not True or not isinstance(ssa, dict):
        raise RuntimeError(f"CompilerCore rejected differential input: {response!r}")
    return ssa


def mutation_campaign() -> list[dict[str, object]]:
    fixtures = {
        "branch": expand_lifecycle(ORACLE.RUST_4_0.branch_module()),
        "effects": expand_lifecycle(ORACLE.effect_module()),
    }
    rows: list[dict[str, object]] = []
    with PersistentRustSSALoweringClient(
        COMPANION, timeout_seconds=60
    ) as client:
        baselines = {
            name: _rust_baseline(client, initial)
            for name, initial in fixtures.items()
        }
        for fixture, initial in fixtures.items():
            rust = _rust_outcome(initial, baselines[fixture])
            python = _python_outcome(initial, baselines[fixture])
            rows.append(
                {
                    "case": f"valid_{fixture}",
                    "kind": "valid",
                    "rust": rust,
                    "python": python,
                    "classification": _classification(rust, python),
                }
            )
        for case in ORACLE.mutation_cases():
            candidate = deepcopy(baselines[case.fixture])
            case.mutate(candidate)
            initial = fixtures[case.fixture]
            rust = _rust_outcome(initial, candidate)
            python = _python_outcome(initial, candidate)
            rows.append(
                {
                    "case": case.name,
                    "kind": "semantic_mutation" if case.semantic else "other_mutation",
                    "fixture": case.fixture,
                    "rust": rust,
                    "python": python,
                    "classification": _classification(rust, python),
                }
            )
    return rows


def historical_campaign() -> list[dict[str, object]]:
    roots = (ROOT / "examples", ROOT / "benchmarks", ROOT / "corpus/exceptions")
    paths = sorted({path for root in roots for path in root.rglob("*.ae")})
    rows: list[dict[str, object]] = []
    with PersistentRustSSALoweringClient(
        COMPANION, timeout_seconds=60
    ) as client:
        for path in paths:
            try:
                source = path.read_text(encoding="utf-8")
                initial = IRBackend().lower_verified(
                    prepare_typed_program(
                        source, TypeChecker(source_root=path.parent)
                    )
                )
            except Exception:
                continue
            normalized = expand_lifecycle(initial)
            ssa = _rust_baseline(client, initial)
            rust = _rust_outcome(normalized, ssa)
            python = _python_outcome(normalized, ssa)
            rows.append(
                {
                    "case": path.relative_to(ROOT).as_posix(),
                    "kind": "historical_valid",
                    "rust": rust,
                    "python": python,
                    "classification": _classification(rust, python),
                }
            )
    return rows


def qualify(include_historical: bool = True) -> dict[str, object]:
    mutations = mutation_campaign()
    historical = historical_campaign() if include_historical else []
    rows = [*mutations, *historical]
    divergences = [row for row in rows if row["classification"] != "agreement"]
    semantic_divergences = [
        row
        for row in divergences
        if row["classification"] != "input_domain_divergence"
    ]
    return {
        "milestone": "RUST-REFINE-1",
        "mode": "SHADOW",
        "oracle": "src/aether/ssa/refinement_verifier.py",
        "mutation_rows": len(mutations),
        "historical_rows": len(historical),
        "accepted_by_both": sum(
            row["rust"]["accepted"] is True
            and row["python"]["accepted"] is True
            for row in rows
        ),
        "rejected_by_both": sum(
            row["rust"]["accepted"] is False
            and row["python"]["accepted"] is False
            for row in rows
        ),
        "divergences": divergences,
        "semantic_divergences": semantic_divergences,
        "status": "PASS" if not semantic_divergences else "DIVERGENCE",
        "rows": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mutations-only", action="store_true")
    parser.add_argument("--json", action="store_true")
    arguments = parser.parse_args()
    report = qualify(include_historical=not arguments.mutations_only)
    if arguments.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(
            f"{report['status']}: {report['mutation_rows']} mutation/fixture rows, "
            f"{report['historical_rows']} historical rows, "
            f"{len(report['divergences'])} divergences"
        )
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
