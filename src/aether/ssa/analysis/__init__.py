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
    AggregateProvenance, ComponentPath, ComponentProvenance,
    ArcPairCandidate, ArcPairClassification, EscapeFact, EscapeMode,
    ArcPairSemanticDecision, ArcPairSemanticReason, ArcPairSemanticStatus,
    OwnershipEscapeAnalysis, OwnershipFrame, OwnershipFunctionSummary,
    OwnershipState, OwnershipSummaryAnalysis, OwnershipUnknownReason,
    PostDominatorAnalysis, has_unsupported_nested_owned_payload,
    is_reference_like,
)
from .trusted_helpers import (
    ReturnedIdentity, ReturnedOwnership, TrustedHelperContract,
    TRUSTED_HELPER_CONTRACTS, trusted_helper_contract,
)
from .aggregate_lifetime import (
    AggregateLifetimeAnalysis, AggregateLifetime, AggregateOrigin,
    ArcAttribution, ArcEvent, BorrowOpportunity, ComponentLifetime,
    EscapeKind, LifetimeCategory, MaterializationKind, ProgramPoint,
)
from .collection_extraction_borrow import (
    BorrowedAggregateView, BorrowIntervalKind, BorrowInvalidationReason,
    BorrowPoint, CollectionExtractionBorrowAnalysis, ExtractionBorrowClassification,
    ExtractionBorrowResult, FieldUseShape,
)
from .scalar_replacement import (
    AggregateUse, FieldUseKind, aggregate_field_uses,
    aggregate_reconstruction_boundaries, classify_scalar_replacement,
    scalar_replacement_profitability, scalar_replacement_region,
)
from .aggregate_copy_elision import (
    AggregateCopyCategory, AggregateCopyFact, CopySafetyClass,
    OwnershipTransferFact, SourceAfterCopy, classify_aggregate_copy,
    classify_copy_safety, copy_destination_unique, copy_elision_profitability,
    copy_elision_region, copy_ownership_transfer, copy_source_dead_after,
)
from .concrete_optimization import (
    ConcreteCandidateStatus, ConcreteOptimizationCandidate, select_recommendation,
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
    "AggregateProvenance", "ComponentPath", "ComponentProvenance",
    "ArcPairSemanticDecision", "ArcPairSemanticReason", "ArcPairSemanticStatus",
    "OwnershipEscapeAnalysis", "OwnershipFrame", "OwnershipFunctionSummary",
    "OwnershipState", "OwnershipSummaryAnalysis", "OwnershipUnknownReason",
    "PostDominatorAnalysis", "has_unsupported_nested_owned_payload",
    "is_reference_like",
    "ReturnedIdentity", "ReturnedOwnership", "TrustedHelperContract",
    "TRUSTED_HELPER_CONTRACTS", "trusted_helper_contract",
    "AggregateLifetimeAnalysis", "AggregateLifetime", "AggregateOrigin",
    "ArcAttribution", "ArcEvent", "BorrowOpportunity", "ComponentLifetime",
    "EscapeKind", "LifetimeCategory", "MaterializationKind", "ProgramPoint",
    "BorrowedAggregateView", "BorrowIntervalKind", "BorrowInvalidationReason",
    "BorrowPoint", "CollectionExtractionBorrowAnalysis", "ExtractionBorrowClassification",
    "ExtractionBorrowResult", "FieldUseShape",
    "AggregateUse", "FieldUseKind", "aggregate_field_uses",
    "aggregate_reconstruction_boundaries", "classify_scalar_replacement",
    "scalar_replacement_profitability", "scalar_replacement_region",
    "AggregateCopyCategory", "AggregateCopyFact", "CopySafetyClass",
    "OwnershipTransferFact", "SourceAfterCopy", "classify_aggregate_copy",
    "classify_copy_safety", "copy_destination_unique", "copy_elision_profitability",
    "copy_elision_region", "copy_ownership_transfer", "copy_source_dead_after",
    "ConcreteCandidateStatus", "ConcreteOptimizationCandidate", "select_recommendation",
]
