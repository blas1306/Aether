from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

from aether.backend.llvm import LLVMBuilder
from aether.cli import EXIT_SUCCESS, EXIT_USAGE_ERROR, main
from aether.ir.optimizer import build_optimizer_pipeline
from aether.optimization import (
    DEFAULT_OPTIMIZATION_PROFILE,
    IR_O1_PASSES,
    PROFILES,
    SSA_O1_PASSES,
    SSA_O2_PASSES,
    OptimizationLevel,
    optimization_profile,
)
from aether.ssa.optimizer import build_ssa_optimizer_pipeline


def test_registry_defines_truthful_middle_end_and_clang_mapping() -> None:
    assert DEFAULT_OPTIMIZATION_PROFILE is PROFILES[OptimizationLevel.O0]
    assert PROFILES[OptimizationLevel.O0].ir_passes == ()
    assert PROFILES[OptimizationLevel.O0].ssa_passes == ()
    assert tuple(PROFILES[level].clang_level for level in OptimizationLevel) == (
        "0", "1", "2"
    )
    assert PROFILES[OptimizationLevel.O1].ir_passes == IR_O1_PASSES
    assert PROFILES[OptimizationLevel.O2].ir_passes == IR_O1_PASSES
    assert PROFILES[OptimizationLevel.O1].ssa_passes == SSA_O1_PASSES
    assert PROFILES[OptimizationLevel.O2].ssa_passes == SSA_O2_PASSES
    assert SSA_O2_PASSES == SSA_O1_PASSES + (
        "ProvenBoundsCheckEliminator",
        "LoopInvariantCodeMotion",
        "SSADeadCodeEliminator",
    )


@pytest.mark.parametrize("level", OptimizationLevel)
def test_pipeline_factories_exactly_follow_registry(level: OptimizationLevel) -> None:
    profile = PROFILES[level]
    ir = build_optimizer_pipeline(profile)
    ssa = build_ssa_optimizer_pipeline(profile)
    assert tuple(type(item).__name__ for item in ir._passes) == profile.ir_passes
    assert tuple(type(item).__name__ for item in ssa._passes) == profile.ssa_passes


@pytest.mark.parametrize("level", ("0", "1", "2"))
def test_build_maps_profile_to_clang(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, level: str
) -> None:
    commands: list[list[str]] = []
    monkeypatch.setattr("aether.backend.llvm.build.shutil.which", lambda _: "/clang")
    monkeypatch.setattr(
        "aether.backend.llvm.build.subprocess.run",
        lambda command, **_: commands.append(command)
        or subprocess.CompletedProcess(command, 0, "", ""),
    )
    source = tmp_path / "main.ae"
    source.write_text("int main() { return 0; }\n", encoding="utf-8")
    assert main(["build", str(source), f"-O{level}"]) == EXIT_SUCCESS
    assert commands[0].count(f"-O{level}") == 1


def test_legacy_opt_is_o1_and_conflicts_with_other_explicit_level(tmp_path: Path) -> None:
    source = tmp_path / "main.ae"
    source.write_text("int main() { return 1 + 1; }\n", encoding="utf-8")
    assert main(["--emit-ir", "--opt", str(source)]) == EXIT_SUCCESS
    assert main(["--emit-ir", "--opt", "-O0", str(source)]) == EXIT_USAGE_ERROR


def test_profile_parser_rejects_invalid_level() -> None:
    with pytest.raises(ValueError, match="Unknown optimization profile"):
        optimization_profile("O3")
