import json
from pathlib import Path

from aether.ir.types import ArrayType, IntType, MethodResultType, StringType, StructType
from aether.ssa import model as m
from aether.ssa.analysis.aggregate_copy_elision import (
    AggregateCopyCategory as Category, AggregateCopyFact, CopySafetyClass,
    OwnershipTransferFact, SourceAfterCopy, classify_aggregate_copy,
    classify_copy_safety, copy_destination_unique, copy_elision_profitability,
    copy_elision_region, copy_source_dead_after,
)
from scripts.o2_aggregate_copy_elision_readiness import generate


S = StructType("S")


def _local(owned=0, *, dead=True, unique=True, ambiguous=False):
    source, destination = m.SSAValue("a", S), m.SSAValue("b", S)
    transfer = OwnershipTransferFact(True, 1 if owned else 0, 1 if owned else 0,
                                     dead, unique, path_or_exception_ambiguity=ambiguous)
    # Scalar-only aggregates have no ownership edge and need no ownership transfer.
    if not owned: transfer = OwnershipTransferFact(True, 1, 1, dead, unique,
                                                    path_or_exception_ambiguity=ambiguous)
    return AggregateCopyFact(source, destination, m.SSAStructNew(destination, ()),
        Category.LOCAL_TEMPORARY_COPY, SourceAfterCopy.SOURCE_DEAD_IMMEDIATELY if dead
        else SourceAfterCopy.SOURCE_USED_AS_WHOLE, unique, transfer)


def test_scalar_only_local_copy_analysis_api():
    fact = _local()
    assert copy_source_dead_after(fact) and copy_destination_unique(fact)
    assert classify_copy_safety(fact) is CopySafetyClass.LOCAL_TRANSFER_CANDIDATE


def test_string_bearing_local_copy_requires_balanced_owned_edge():
    fact = _local(owned=1)
    assert fact.transfer.balanced
    assert copy_elision_profitability(fact)["potential_arc_operations_removed"] == 2


def test_source_still_used_is_blocked():
    assert classify_copy_safety(_local(owned=1, dead=False)) is CopySafetyClass.OWNERSHIP_BLOCKED


def test_multiple_destinations_are_blocked():
    assert classify_copy_safety(_local(owned=1, unique=False)) is CopySafetyClass.OWNERSHIP_BLOCKED


def test_return_temporary_and_callee_return_region():
    result = m.SSAValue("r", S); call = m.SSACall("callee", result=result)
    assert classify_aggregate_copy(call) is Category.RETURN_TEMPORARY_COPY
    fact = AggregateCopyFact(None, result, call, Category.RETURN_TEMPORARY_COPY,
        SourceAfterCopy.SOURCE_LIFETIME_UNKNOWN, True, None, True)
    assert classify_copy_safety(fact) is CopySafetyClass.OWNERSHIP_BLOCKED
    assert copy_elision_region(fact) == "RETURN_HANDOFF"


def test_call_argument_copy_category_can_be_explicit():
    value = m.SSAValue("s", S)
    fact = AggregateCopyFact(value, value, m.SSACall("sink", (value,)),
        Category.CALL_BOUNDARY_COPY, SourceAfterCopy.SOURCE_LIFETIME_UNKNOWN, False)
    assert classify_copy_safety(fact) is CopySafetyClass.OWNERSHIP_BLOCKED


def test_collection_storage_copy():
    array = m.SSAValue("xs", ArrayType(S)); index = m.SSAValue("i", IntType()); value = m.SSAValue("s", S)
    assert classify_aggregate_copy(m.SSAArraySet(array, index, value)) is Category.COLLECTION_STORAGE_COPY


def test_struct_set_is_reconstruction_not_copy():
    source, field, result = m.SSAValue("s", S), m.SSAValue("x", IntType()), m.SSAValue("r", S)
    assert classify_aggregate_copy(m.SSAStructSet(result, source, 0, "x", field)) is Category.RECONSTRUCTION_COPY


def test_phi_copy_is_separate():
    value, result = m.SSAValue("s", S), m.SSAValue("p", S)
    assert classify_aggregate_copy(m.SSAPhi(result, (("left", value),))) is Category.PHI_MERGE_COPY


def test_exception_path_blocks_transfer():
    assert classify_copy_safety(_local(owned=1, ambiguous=True)) is CopySafetyClass.OWNERSHIP_BLOCKED


def test_method_result_is_excluded():
    receiver, result = m.SSAValue("s", S), m.SSAValue("mr", MethodResultType(S, IntType()))
    assert classify_aggregate_copy(m.SSAMethodResultNew(result, receiver)) is Category.METHOD_RESULT_COPY


def test_constructor_result_is_excluded():
    result = m.SSAValue("s", S)
    assert classify_aggregate_copy(m.SSAStructNew(result, ())) is Category.CONSTRUCTOR_COPY


def test_copy_chain_requires_individual_unique_edges():
    first, second = _local(owned=1), _local(owned=1)
    assert all(classify_copy_safety(x) is CopySafetyClass.LOCAL_TRANSFER_CANDIDATE for x in (first, second))


def test_o211_reconciles_exact_four_real_sites_as_no_explicit_copy_edges():
    root = Path(__file__).resolve().parents[2]
    report = generate(root, ("examples/expense_tracker/Main.ae",))
    rows = report["exact_four_candidates"]
    assert [(x["candidate_id"], x["ssa_destination_value"]) for x in rows] == [
        ("ACE-001", "336"), ("ACE-002", "437"), ("ACE-003", "516"), ("ACE-004", "791")]
    assert all(x["copy_materialization_instruction"] is None for x in rows)
    assert {x["safety_class"] for x in rows} == {"OWNERSHIP_BLOCKED"}
    assert report["recommendation"] == "IMPROVE_COPY_ELISION_ANALYSIS_FIRST"


def test_report_regeneration_is_byte_deterministic(tmp_path):
    root = Path(__file__).resolve().parents[2]
    one = json.dumps(generate(root, ("examples/expense_tracker/Main.ae",)), indent=2, sort_keys=True) + "\n"
    two = json.dumps(generate(root, ("examples/expense_tracker/Main.ae",)), indent=2, sort_keys=True) + "\n"
    assert one == two
