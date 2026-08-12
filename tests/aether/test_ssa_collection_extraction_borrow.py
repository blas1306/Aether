from aether.ir.types import ArrayType, IntType, ListType, StructType, VoidType
from aether.ssa.analysis import (
    BorrowInvalidationReason, CollectionExtractionBorrowAnalysis,
    ExtractionBorrowClassification,
)
from aether.ssa.model import (
    SSAArrayGet, SSAArrayNew, SSABasicBlock, SSAConst, SSAFunction, SSAListGet,
    SSAListNew, SSAListPush, SSAReturn, SSAValue,
)


I = IntType()


def value(name, type_=I): return SSAValue(name, type_)


def test_immediate_array_extraction_is_an_analysis_only_view():
    struct = StructType("Pair")
    item, array, index, extracted = value("item", struct), value("array", ArrayType(struct)), value("index"), value("extracted", struct)
    function = SSAFunction("immediate", [], VoidType(), [SSABasicBlock("entry", [
        SSAArrayNew(array, (item,)), SSAConst(index, 0), SSAArrayGet(extracted, array, index), SSAReturn(),
    ])])
    analysis = CollectionExtractionBorrowAnalysis(function)
    assert analysis.classify_extraction_borrow(extracted) is ExtractionBorrowClassification.BORROWABLE_IMMEDIATE_USE
    view = analysis.extraction_borrow_interval(extracted)
    assert view.collection_root == array and view.element_selector == index
    assert not hasattr(view, "pointer")


def test_list_mutation_blocks_a_stable_borrow():
    struct = StructType("Pair")
    item, listing, index, extracted = value("item", struct), value("list", ListType(struct)), value("index"), value("extracted", struct)
    function = SSAFunction("mutation", [], VoidType(), [SSABasicBlock("entry", [
        SSAListNew(listing, (item,)), SSAConst(index, 0), SSAListGet(extracted, listing, index),
        SSAListPush(listing, item), SSAReturn(extracted),
    ])])
    result = CollectionExtractionBorrowAnalysis(function)
    assert result.classify_extraction_borrow(extracted) is ExtractionBorrowClassification.MUST_COPY_ESCAPES
    assert BorrowInvalidationReason.COLLECTION_MUTATION in result.borrow_invalidation_reason(extracted)
    assert not result.collection_stable_during(extracted)
