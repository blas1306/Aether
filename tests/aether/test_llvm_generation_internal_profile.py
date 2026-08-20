from __future__ import annotations

import json
from pathlib import Path

from aether.backend.llvm import LLVMBackend, LLVMGenerationProfiler
from aether.benchmark import _typed_program
from scripts.llvm_generation_internal_profile import _materialize, profile


ROOT = Path(__file__).resolve().parents[2]


def test_opt_in_profiler_preserves_llvm_text() -> None:
    path = ROOT / "benchmarks/sum_to.ae"
    typed = _typed_program(path.read_text(encoding="utf-8"), path)
    module = _materialize(typed, "O0")
    expected = LLVMBackend().emit(module, native_entry=True)
    profiler = LLVMGenerationProfiler()

    actual = LLVMBackend(profiler=profiler).emit(module, native_entry=True)

    assert actual == expected
    snapshot = profiler.snapshot()
    assert snapshot["verification"]["calls"] == 1
    assert snapshot["module_generation"]["calls"] == 1
    assert snapshot["function_lowering"]["calls"] == len(module.functions)
    assert snapshot["instruction_lowering"]["calls"] == sum(
        len(block.instructions)
        for function in module.functions
        for block in function.blocks
    )
    assert snapshot["runtime_helper_emission"]["calls"] == 1
    assert snapshot["final_text_rendering"]["calls"] == 1


def test_profile_smoke_covers_three_profiles() -> None:
    timing, structural = profile(ROOT, workload_limit=1, include_cprofile=False)

    assert timing["emissions"] == structural["emissions"] == 3
    assert {row["profile"] for row in structural["records"]} == {"O0", "O1", "O2"}
    assert all(row["llvm_bytes"] > 0 for row in structural["records"])
    assert all(row["runtime"]["helper_definitions"] > 0 for row in structural["records"])


def test_canonical_structural_profile_has_78_emissions() -> None:
    artifact = json.loads(
        (ROOT / "docs/compiler/llvm_generation_internal_performance_profile.json").read_text(
            encoding="utf-8"
        )
    )

    assert artifact["emissions"] == 78
    assert artifact["profiles"] == {"O0": 26, "O1": 26, "O2": 26}
    assert len(artifact["records"]) == 78
    assert all("seconds" not in row for row in artifact["records"])
