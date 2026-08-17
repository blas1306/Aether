"""Read-only aggregate-copy classification and ownership-transfer facts.

This module deliberately has no rewriting API.  It records aggregate value
identity and ownership-edge identity separately so a future optimizer cannot
turn provenance equality into an implicit move.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from aether.ssa import model as m


class AggregateCopyCategory(Enum):
    SEMANTIC_COPY_REQUIRED = "SEMANTIC_COPY_REQUIRED"
    OWNERSHIP_COPY_REQUIRED = "OWNERSHIP_COPY_REQUIRED"
    RETURN_TEMPORARY_COPY = "RETURN_TEMPORARY_COPY"
    CALL_BOUNDARY_COPY = "CALL_BOUNDARY_COPY"
    LOCAL_TEMPORARY_COPY = "LOCAL_TEMPORARY_COPY"
    RECONSTRUCTION_COPY = "RECONSTRUCTION_COPY"
    PHI_MERGE_COPY = "PHI_MERGE_COPY"
    COLLECTION_STORAGE_COPY = "COLLECTION_STORAGE_COPY"
    METHOD_RESULT_COPY = "METHOD_RESULT_COPY"
    CONSTRUCTOR_COPY = "CONSTRUCTOR_COPY"
    UNKNOWN = "UNKNOWN"


class SourceAfterCopy(Enum):
    SOURCE_DEAD_IMMEDIATELY = "SOURCE_DEAD_IMMEDIATELY"
    SOURCE_USED_FIELD_ONLY = "SOURCE_USED_FIELD_ONLY"
    SOURCE_USED_AS_WHOLE = "SOURCE_USED_AS_WHOLE"
    SOURCE_ESCAPES = "SOURCE_ESCAPES"
    SOURCE_LIFETIME_UNKNOWN = "SOURCE_LIFETIME_UNKNOWN"


class CopySafetyClass(Enum):
    TRANSFER_ELIDABLE = "TRANSFER_ELIDABLE"
    COPY_REQUIRED = "COPY_REQUIRED"
    RETURN_TRANSFER_CANDIDATE = "RETURN_TRANSFER_CANDIDATE"
    LOCAL_TRANSFER_CANDIDATE = "LOCAL_TRANSFER_CANDIDATE"
    OWNERSHIP_BLOCKED = "OWNERSHIP_BLOCKED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class OwnershipTransferFact:
    component_roots_exact: bool
    source_owned_edges: int
    destination_owned_edges: int
    source_dead: bool
    destination_unique: bool
    independent_owner_required: bool = False
    path_or_exception_ambiguity: bool = False

    @property
    def balanced(self) -> bool:
        return (self.component_roots_exact and self.source_owned_edges == 1 and
                self.destination_owned_edges == 1 and self.source_dead and
                self.destination_unique and not self.independent_owner_required and
                not self.path_or_exception_ambiguity)


@dataclass(frozen=True)
class AggregateCopyFact:
    source: m.SSAValue | None
    destination: m.SSAValue
    instruction: m.SSAInstruction
    category: AggregateCopyCategory
    source_liveness: SourceAfterCopy
    destination_unique: bool
    transfer: OwnershipTransferFact | None = None
    crosses_return_abi: bool = False


def classify_aggregate_copy(instruction: m.SSAInstruction) -> AggregateCopyCategory:
    if isinstance(instruction, m.SSAStructSet): return AggregateCopyCategory.RECONSTRUCTION_COPY
    if isinstance(instruction, m.SSAPhi): return AggregateCopyCategory.PHI_MERGE_COPY
    if isinstance(instruction, m.SSAMethodResultNew): return AggregateCopyCategory.METHOD_RESULT_COPY
    if isinstance(instruction, m.SSAStructNew): return AggregateCopyCategory.CONSTRUCTOR_COPY
    if isinstance(instruction, (m.SSAArraySet, m.SSAListSet, m.SSAListPush, m.SSAListInsert)):
        return AggregateCopyCategory.COLLECTION_STORAGE_COPY
    if isinstance(instruction, (m.SSACall, m.SSAInvoke, m.SSACallIndirect,
                                m.SSAInvokeIndirect, m.SSAInterfaceCall,
                                m.SSAInvokeInterface)):
        return AggregateCopyCategory.RETURN_TEMPORARY_COPY if instruction.result is not None else AggregateCopyCategory.CALL_BOUNDARY_COPY
    return AggregateCopyCategory.UNKNOWN


def copy_source_dead_after(fact: AggregateCopyFact) -> bool:
    return fact.source_liveness is SourceAfterCopy.SOURCE_DEAD_IMMEDIATELY


def copy_destination_unique(fact: AggregateCopyFact) -> bool:
    return fact.destination_unique


def copy_ownership_transfer(fact: AggregateCopyFact) -> OwnershipTransferFact | None:
    return fact.transfer


def copy_elision_region(fact: AggregateCopyFact) -> str:
    if fact.crosses_return_abi: return "RETURN_HANDOFF"
    if fact.transfer and fact.transfer.path_or_exception_ambiguity: return "PATH_SENSITIVE"
    return "LOCAL" if fact.source is not None else "UNKNOWN"


def copy_elision_profitability(fact: AggregateCopyFact) -> dict[str, int]:
    owned = fact.transfer.destination_owned_edges if fact.transfer else 0
    return {"aggregate_copies": 1, "owned_field_retains": owned,
            "owned_field_releases": owned, "potential_arc_operations_removed": owned * 2}


def classify_copy_safety(fact: AggregateCopyFact) -> CopySafetyClass:
    if fact.category in {AggregateCopyCategory.RECONSTRUCTION_COPY,
                         AggregateCopyCategory.PHI_MERGE_COPY,
                         AggregateCopyCategory.COLLECTION_STORAGE_COPY,
                         AggregateCopyCategory.METHOD_RESULT_COPY,
                         AggregateCopyCategory.CONSTRUCTOR_COPY,
                         AggregateCopyCategory.SEMANTIC_COPY_REQUIRED,
                         AggregateCopyCategory.OWNERSHIP_COPY_REQUIRED}:
        return CopySafetyClass.COPY_REQUIRED
    if fact.transfer is None: return CopySafetyClass.OWNERSHIP_BLOCKED
    if not fact.transfer.balanced: return CopySafetyClass.OWNERSHIP_BLOCKED
    if fact.crosses_return_abi or fact.category is AggregateCopyCategory.RETURN_TEMPORARY_COPY:
        return CopySafetyClass.RETURN_TRANSFER_CANDIDATE
    if fact.category is AggregateCopyCategory.LOCAL_TEMPORARY_COPY:
        return CopySafetyClass.LOCAL_TRANSFER_CANDIDATE
    return CopySafetyClass.TRANSFER_ELIDABLE
