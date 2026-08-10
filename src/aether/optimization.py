from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class OptimizationLevel(str, Enum):
    O0 = "O0"
    O1 = "O1"
    O2 = "O2"

    @classmethod
    def parse(cls, value: OptimizationLevel | str) -> OptimizationLevel:
        if isinstance(value, cls):
            return value
        normalized = value.upper()
        if not normalized.startswith("O"):
            normalized = f"O{normalized}"
        try:
            return cls(normalized)
        except ValueError as exc:
            raise ValueError(f"Unknown optimization profile '{value}'.") from exc


@dataclass(frozen=True)
class OptimizationProfile:
    """The single compilation-wide optimization contract."""

    level: OptimizationLevel
    ir_passes: tuple[str, ...]
    ssa_passes: tuple[str, ...]
    clang_level: str

    @property
    def name(self) -> str:
        return self.level.value


IR_O1_PASSES = (
    "ConstantFolder",
    "LocalConstantPropagator",
    "ConstantFolder",
    "AlgebraicSimplifier",
    "DeadCodeEliminator",
    "DeadStoreEliminator",
    "DeadCodeEliminator",
)
SSA_O1_PASSES = (
    "SSAConstantFolder",
    "SSAGlobalConstantPropagator",
    "SSAAlgebraicSimplifier",
    "SCCPPass",
    "TrivialPhiEliminator",
    "DeadPhiEliminator",
    "SSADeadCodeEliminator",
)
SSA_O2_PASSES = SSA_O1_PASSES + (
    "ProvenBoundsCheckEliminator",
    "LoopInvariantCodeMotion",
    "LocalARCEliminator",
    "SSADeadCodeEliminator",
)

PROFILES = {
    OptimizationLevel.O0: OptimizationProfile(OptimizationLevel.O0, (), (), "0"),
    OptimizationLevel.O1: OptimizationProfile(
        OptimizationLevel.O1, IR_O1_PASSES, SSA_O1_PASSES, "1"
    ),
    OptimizationLevel.O2: OptimizationProfile(
        OptimizationLevel.O2, IR_O1_PASSES, SSA_O2_PASSES, "2"
    ),
}
DEFAULT_OPTIMIZATION_PROFILE = PROFILES[OptimizationLevel.O0]


def optimization_profile(
    value: OptimizationProfile | OptimizationLevel | str,
) -> OptimizationProfile:
    if isinstance(value, OptimizationProfile):
        return value
    return PROFILES[OptimizationLevel.parse(value)]
