"""Clean-install probe for production Rust-authoritative SSA lowering."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile

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


def _compile_and_run(
    clang: Path, llvm: str, directory: Path, stem: str
) -> tuple[int, str, str]:
    llvm_path = directory / f"{stem}.ll"
    executable = directory / (f"{stem}.exe" if os.name == "nt" else stem)
    llvm_path.write_text(llvm, encoding="utf-8")
    built = subprocess.run(
        [
            str(clang),
            "-O0",
            "-Wno-override-module",
            str(llvm_path),
            "-o",
            str(executable),
        ],
        capture_output=True,
        text=True,
    )
    if built.returncode != 0:
        raise RuntimeError(
            f"clang rejected representative LLVM: {built.stderr[:500]}"
        )
    completed = subprocess.run(
        [str(executable)], capture_output=True, text=True, timeout=30
    )
    return completed.returncode, completed.stdout, completed.stderr


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--clang", type=Path)
    parser.add_argument("--native-count", type=int, default=0)
    parser.add_argument("source", nargs="+", type=Path)
    args = parser.parse_args()
    if args.native_count < 0 or args.native_count > len(args.source):
        raise ValueError("native-count must select a prefix of the supplied sources")
    if args.native_count and (args.clang is None or not args.clang.is_file()):
        raise RuntimeError(
            "an absolute clang executable is required for native comparisons"
        )

    if (
        SSALoweringAuthorityConfiguration().mode
        is not SSALoweringAuthorityMode.RUST_SSA_AUTHORITY_PYTHON_SHADOW
    ):
        raise RuntimeError("repository default is not Rust-authority/Python-shadow mode")

    client = production_rust_ssa_lowering_client()
    origins: list[str] = []
    fixture_mode_matrices = 0
    llvm_modules = 0
    native_comparisons = 0
    with tempfile.TemporaryDirectory(prefix="aether-ssa-native-") as raw_native:
        native_directory = Path(raw_native)
        for index, path in enumerate(args.source):
            source = path.read_text(encoding="utf-8")
            typed = prepare_typed_program(
                source, TypeChecker(source_root=path.parent)
            )
            initial_ir = IRBackend().lower_verified(typed)
            pipeline = SSAPipeline(rust_shadow_client=client)
            compile_result = pipeline.run(initial_ir)
            if pipeline.last_returned_ssa_origin != "rust_schema_v2_import":
                raise RuntimeError(
                    "SSA returned to the optimizer did not originate from Rust"
                )
            optimized = SSAOptimizerPipeline(verify_after_each=True).run(
                compile_result.ssa_module
            )
            llvm = LLVMBackend().emit(optimized)
            if not llvm.strip():
                raise RuntimeError("backend produced an empty LLVM module")
            origins.append(pipeline.last_returned_ssa_origin)
            llvm_modules += 1

            python_authority_pipeline = SSAPipeline(
                authority_configuration=SSALoweringAuthorityConfiguration(
                    SSALoweringAuthorityMode.PYTHON_SSA_AUTHORITY_RUST_SHADOW
                ),
                rust_shadow_client=client,
            )
            python_authority_ssa = python_authority_pipeline.run(
                initial_ir
            ).ssa_module
            python_only_pipeline = SSAPipeline(
                authority_configuration=SSALoweringAuthorityConfiguration(
                    SSALoweringAuthorityMode.PYTHON_SSA_ONLY
                )
            )
            python_only_ssa = python_only_pipeline.run(initial_ir).ssa_module
            if (
                python_authority_pipeline.last_returned_ssa_origin
                != "python_general_ssa_builder"
                or python_only_pipeline.last_returned_ssa_origin
                != "python_general_ssa_builder"
                or ssa_module_to_dto(python_authority_ssa)
                != ssa_module_to_dto(python_only_ssa)
            ):
                raise RuntimeError("promotion fixture three-mode matrix diverged")
            fixture_mode_matrices += 1

            if index < args.native_count:
                python_optimized = SSAOptimizerPipeline(verify_after_each=True).run(
                    python_authority_ssa
                )
                python_llvm = LLVMBackend().emit(python_optimized)
                assert args.clang is not None
                rust_observation = _compile_and_run(
                    args.clang, llvm, native_directory, f"rust-{index}"
                )
                python_observation = _compile_and_run(
                    args.clang, python_llvm, native_directory, f"python-{index}"
                )
                if rust_observation[0] != 0 or rust_observation != python_observation:
                    raise RuntimeError(
                        "native observable output differs from Python authority"
                    )
                native_comparisons += 1

    default_pipeline = SSAPipeline(rust_shadow_client=client)
    default_ssa = default_pipeline.run(IRModule()).ssa_module
    if default_pipeline.last_returned_ssa_origin != "rust_schema_v2_import":
        raise RuntimeError("production default did not return Rust-origin SSA")
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
        ssa_module_to_dto(default_ssa) == ssa_module_to_dto(python_only)
        == ssa_module_to_dto(python_authority)
    ):
        raise RuntimeError("SSA rollback configurations diverged")
    result = {
        "mode": "RUST_SSA_AUTHORITY_PYTHON_SHADOW",
        "comparisons": len(origins),
        "returned_ssa_origins": origins,
        "optimizer_handoffs": len(origins),
        "backend_handoffs": llvm_modules,
        "native_baseline_comparisons": native_comparisons,
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
        "repository_default": "RUST_SSA_AUTHORITY_PYTHON_SHADOW",
        "default_returned_ssa_origin": "rust_schema_v2_import",
        "semantic_mismatches": 0,
        "infrastructure_failures": 0,
        "process_startups": client.process_start_count,
        "requests": client.request_count,
    }
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
