from __future__ import annotations

from .lattice import Constant, LatticeState, Overdefined, Unknown
from .worklist import Worklist
from .loops import (
    InductionVariable,
    IrreducibleRegion,
    LoopAnalysis,
    LoopAnalysisResult,
    NaturalLoop,
)
from .ranges import (
    IntegerRange,
    ProofResult,
    RangeAnalysis,
    RangeAnalysisResult,
    Relation,
    SymbolicBound,
)
from .shapes import (
    LengthFact,
    MatrixShapeFact,
    ShapeAnalysis,
    ShapeAnalysisResult,
    VectorShapeFact,
)
from .proof_coverage import (
    CheckKind,
    CheckProof,
    CheckRecord,
    CoverageReport,
    ProofCoverageAudit,
    UnknownReason,
)
from .alias_modref import (
    AliasAnalysis, AliasRelation, FunctionSummary, ModRefAnalysis,
    CollectionLengthLocation, CollectionStorageLocation, FieldIdentity,
    FieldLocation, MemoryLocation, ModRefDecision, ModRefEffect,
    ObjectLocation, ParameterFieldEffect, Provenance, ProvenanceRoot, RootKind,
    StructFieldLocation,
    SummaryAnalysis, UnknownReason as AliasUnknownReason,
)
from .ownership_escape import (
    ArcPairCandidate, ArcPairClassification, EscapeFact, EscapeMode,
    ArcPairSemanticDecision, ArcPairSemanticReason, ArcPairSemanticStatus,
    OwnershipEscapeAnalysis, OwnershipFrame, OwnershipFunctionSummary,
    OwnershipState, OwnershipSummaryAnalysis, OwnershipUnknownReason,
    PostDominatorAnalysis, has_unsupported_nested_owned_payload,
    is_reference_like,
)

__all__ = [
    "Constant",
    "LatticeState",
    "Overdefined",
    "Unknown",
    "Worklist",
    "InductionVariable",
    "IrreducibleRegion",
    "LoopAnalysis",
    "LoopAnalysisResult",
    "NaturalLoop",
    "IntegerRange",
    "ProofResult",
    "RangeAnalysis",
    "RangeAnalysisResult",
    "Relation",
    "SymbolicBound",
    "LengthFact",
    "MatrixShapeFact",
    "ShapeAnalysis",
    "ShapeAnalysisResult",
    "VectorShapeFact",
    "CheckKind",
    "CheckProof",
    "CheckRecord",
    "CoverageReport",
    "ProofCoverageAudit",
    "UnknownReason",
    "AliasAnalysis", "AliasRelation", "FunctionSummary", "ModRefAnalysis",
    "ModRefDecision", "ModRefEffect", "Provenance", "ProvenanceRoot",
    "RootKind", "SummaryAnalysis", "AliasUnknownReason", "FieldIdentity",
    "FieldLocation", "StructFieldLocation", "ObjectLocation",
    "CollectionStorageLocation", "CollectionLengthLocation", "MemoryLocation",
    "ParameterFieldEffect",
    "ArcPairCandidate", "ArcPairClassification", "EscapeFact", "EscapeMode",
    "ArcPairSemanticDecision", "ArcPairSemanticReason", "ArcPairSemanticStatus",
    "OwnershipEscapeAnalysis", "OwnershipFrame", "OwnershipFunctionSummary",
    "OwnershipState", "OwnershipSummaryAnalysis", "OwnershipUnknownReason",
    "PostDominatorAnalysis", "has_unsupported_nested_owned_payload",
    "is_reference_like",
]
