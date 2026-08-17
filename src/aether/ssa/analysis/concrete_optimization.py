"""Fail-closed evidence model for concrete optimization audits.

This module is analysis-only.  It deliberately does not expose a rewrite API.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
import json


class ConcreteCandidateStatus(str, Enum):
    TRANSFORMABLE_NOW = "TRANSFORMABLE_NOW"
    ANALYSIS_BLOCKED = "ANALYSIS_BLOCKED"
    SEMANTIC_BLOCKED = "SEMANTIC_BLOCKED"
    STRUCTURAL_BLOCKED = "STRUCTURAL_BLOCKED"
    LLVM_ALREADY_COMPLETE = "LLVM_ALREADY_COMPLETE"
    HYPOTHESIS_ONLY = "HYPOTHESIS_ONLY"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class ConcreteOptimizationCandidate:
    family: str
    workload: str
    function: str
    opcode: str
    instructions: tuple[str, ...]
    operands: tuple[str, ...]
    proof: tuple[str, ...]
    transformation: str | None
    removed: tuple[str, ...] = ()
    replaced: tuple[str, ...] = ()
    moved: tuple[str, ...] = ()
    blockers: tuple[str, ...] = ()
    loop_depth: int = 0
    block_role: str = "NON_LOOP"
    llvm_overlap: str = "UNKNOWN"
    structural_hotness: int = 1
    status: ConcreteCandidateStatus = ConcreteCandidateStatus.UNKNOWN

    @property
    def fingerprint(self) -> str:
        stable = {
            "workload": self.workload, "function": self.function,
            "family": self.family, "opcode": self.opcode,
            "operands": self.operands, "block_role": self.block_role,
        }
        digest = hashlib.sha256(json.dumps(stable, sort_keys=True,
            separators=(",", ":")).encode()).hexdigest()[:16]
        return f"{self.family.upper()}-{digest}"

    def verify(self) -> tuple[bool, tuple[str, ...]]:
        """Independently reject incomplete or uncertain productive claims."""
        errors: list[str] = []
        if not self.workload or not self.function: errors.append("missing exact location")
        if not self.instructions: errors.append("missing exact instruction")
        if not self.operands: errors.append("missing current operands")
        if not self.proof: errors.append("missing proof obligation")
        if not self.transformation: errors.append("missing exact transformation")
        if not (self.removed or self.replaced or self.moved): errors.append("missing exact effect")
        if self.blockers: errors.append("known blocker")
        if any("UNKNOWN" in item.upper() for item in self.proof): errors.append("unknown proof")
        return not errors, tuple(errors)

    @property
    def productive(self) -> bool:
        valid, _ = self.verify()
        return self.status is ConcreteCandidateStatus.TRANSFORMABLE_NOW and valid

    def as_dict(self) -> dict:
        valid, errors = self.verify()
        return {
            "fingerprint": self.fingerprint, "family": self.family,
            "workload": self.workload, "function": self.function,
            "opcode": self.opcode, "instructions": list(self.instructions),
            "operands": list(self.operands), "loop_depth": self.loop_depth,
            "block_role": self.block_role, "proof": list(self.proof),
            "transformation": self.transformation, "removed": list(self.removed),
            "replaced": list(self.replaced), "moved": list(self.moved),
            "blockers": list(self.blockers), "llvm_overlap": self.llvm_overlap,
            "structural_hotness": self.structural_hotness,
            "status": self.status.value, "verified": valid,
            "verification_errors": list(errors), "productive": self.productive,
        }


def select_recommendation(candidates: tuple[ConcreteOptimizationCandidate, ...],
                          family_order: tuple[str, ...]) -> str:
    """Select only a family backed by independently verified candidates."""
    mapping = {
        "GVN/CSE": "PROCEED_TO_GVN_CSE", "memory LICM": "PROCEED_TO_MEMORY_LICM",
        "IV/loop": "PROCEED_TO_LOOP_IV_OPTIMIZATION",
        "allocation/stack": "PROCEED_TO_STACK_PROMOTION",
        "allocation elision": "PROCEED_TO_ALLOCATION_ELISION",
        "collection ownership": "PROCEED_TO_COLLECTION_OWNERSHIP_ELISION",
        "ownership": "PROCEED_TO_OWNERSHIP_ANALYSIS_EXTENSION",
    }
    for family in family_order:
        if any(item.family == family and item.productive for item in candidates):
            return mapping[family]
    return "IMPROVE_OPTIMIZATION_MEASUREMENT_FIRST"
