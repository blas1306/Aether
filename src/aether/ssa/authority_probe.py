"""Clean-install probe for production Rust-authoritative SSA lowering."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from aether.backend.llvm import LLVMBackend
from aether.ir.model import IRModule
from aether.pipeline import IRBackend, SSAPipeline, prepare_typed_program
from aether.ssa.dto import ssa_module_to_dto
from aether.ssa.optimizer import SSAOptimizerPipeline
from aether.ssa.shadow import (
    SSALoweringAuthorityConfiguration,
    SSALoweringAuthorityMode,
    production_rust_ssa_lowering_client,
)
from aether.typechecker import TypeChecker


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", nargs="+", type=Path)
    args = parser.parse_args()

    if (
        SSALoweringAuthorityConfiguration().mode
        is not SSALoweringAuthorityMode.PYTHON_SSA_AUTHORITY_RUST_SHADOW
    ):
        raise RuntimeError("repository default is not the safe Python-authority mode")

    client = production_rust_ssa_lowering_client()
    origins: list[str] = []
    fixture_mode_matrices = 0
    llvm_modules = 0
    for path in args.source:
        source = path.read_text(encoding="utf-8")
        typed = prepare_typed_program(source, TypeChecker(source_root=path.parent))
        initial_ir = IRBackend().lower_verified(typed)
        pipeline = SSAPipeline(
            authority_configuration=SSALoweringAuthorityConfiguration(
                SSALoweringAuthorityMode.RUST_SSA_AUTHORITY_PYTHON_SHADOW
            ),
            rust_shadow_client=client,
        )
        compile_result = pipeline.run(initial_ir)
        if pipeline.last_returned_ssa_origin != "rust_schema_v2_import":
            raise RuntimeError("SSA returned to the optimizer did not originate from Rust")
        optimized = SSAOptimizerPipeline(verify_after_each=True).run(
            compile_result.ssa_module
        )
        llvm = LLVMBackend().emit(optimized)
        if not llvm.strip():
            raise RuntimeError("backend produced an empty LLVM module")
        origins.append(pipeline.last_returned_ssa_origin)
        llvm_modules += 1

        safe_pipeline = SSAPipeline(rust_shadow_client=client)
        safe_ssa = safe_pipeline.run(initial_ir).ssa_module
        python_only_pipeline = SSAPipeline(
            authority_configuration=SSALoweringAuthorityConfiguration(
                SSALoweringAuthorityMode.PYTHON_SSA_ONLY
            )
        )
        python_only_ssa = python_only_pipeline.run(initial_ir).ssa_module
        if (
            safe_pipeline.last_returned_ssa_origin
            != "python_general_ssa_builder"
            or python_only_pipeline.last_returned_ssa_origin
            != "python_general_ssa_builder"
            or ssa_module_to_dto(safe_ssa)
            != ssa_module_to_dto(python_only_ssa)
        ):
            raise RuntimeError("promotion fixture three-mode matrix diverged")
        fixture_mode_matrices += 1

    safe_default_pipeline = SSAPipeline(rust_shadow_client=client)
    safe_default = safe_default_pipeline.run(IRModule()).ssa_module
    if safe_default_pipeline.last_returned_ssa_origin != "python_general_ssa_builder":
        raise RuntimeError("safe default did not return Python-origin SSA")
    python_only = SSAPipeline(
        authority_configuration=SSALoweringAuthorityConfiguration(
            SSALoweringAuthorityMode.PYTHON_SSA_ONLY
        )
    ).run(IRModule()).ssa_module
    python_authority = SSAPipeline(
        authority_configuration=SSALoweringAuthorityConfiguration(
            SSALoweringAuthorityMode.PYTHON_SSA_AUTHORITY_RUST_SHADOW
        ),
        rust_shadow_client=client,
    ).run(IRModule()).ssa_module
    if not (
        ssa_module_to_dto(safe_default) == ssa_module_to_dto(python_only)
        == ssa_module_to_dto(python_authority)
    ):
        raise RuntimeError("SSA rollback configurations diverged")
    result = {
        "mode": "RUST_SSA_AUTHORITY_PYTHON_SHADOW",
        "comparisons": len(origins),
        "returned_ssa_origins": origins,
        "optimizer_handoffs": len(origins),
        "backend_handoffs": llvm_modules,
        "fixture_mode_matrix_checks": fixture_mode_matrices,
        "rollback_modes": [
            "PYTHON_SSA_AUTHORITY_RUST_SHADOW",
            "PYTHON_SSA_ONLY",
        ],
        "modes_exercised": [
            "PYTHON_SSA_ONLY",
            "PYTHON_SSA_AUTHORITY_RUST_SHADOW",
            "RUST_SSA_AUTHORITY_PYTHON_SHADOW",
        ],
        "repository_default": "PYTHON_SSA_AUTHORITY_RUST_SHADOW",
        "default_returned_ssa_origin": "python_general_ssa_builder",
        "semantic_mismatches": 0,
        "infrastructure_failures": 0,
        "process_startups": client.process_start_count,
        "requests": client.request_count,
    }
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
