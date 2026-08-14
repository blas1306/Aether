from aether.ir.types import ArrayType, ClassRefType, IntType, ListType, StringType, StructType, VoidType
from aether.ssa.analysis import (
    BorrowInvalidationReason, CollectionExtractionBorrowAnalysis,
    ExtractionBorrowClassification,
)
from aether.ssa.model import (
    SSAArrayGet, SSAArrayNew, SSAArraySet, SSABasicBlock, SSACall, SSAClassSet,
    SSAConst, SSAFunction, SSAListGet, SSAListNew, SSAListPush, SSAParameter,
    SSAReturn, SSAValue,
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


def _string_get(tail, *, parameters=()):
    string = StringType(); item = value("item", string)
    array = value("array", ArrayType(string)); index = value("index"); extracted = value("extracted", string)
    instructions = [SSAArrayNew(array, (item,)), SSAConst(index, 0), SSAArrayGet(extracted, array, index)]
    instructions.extend(tail(array, index, extracted, item)); instructions.append(SSAReturn())
    return CollectionExtractionBorrowAnalysis(SSAFunction(
        "string_get", list(parameters), VoidType(), [SSABasicBlock("entry", instructions)]
    )), extracted


def test_array_string_immediate_use_and_borrowing_call_are_candidates():
    analysis, extracted = _string_get(lambda a, i, x, item: [
        SSACall("__aether_string_byte_length", (x,), value("length"),
                builtin="__aether_string_byte_length")])
    assert analysis.classify_extraction_borrow(extracted) is ExtractionBorrowClassification.BORROWABLE_IMMEDIATE_USE


def test_array_set_same_or_other_unknown_index_invalidates_string_borrow():
    for replacement_index in ("index", "other"):
        def tail(array, index, extracted, item, replacement_index=replacement_index):
            selected = index if replacement_index == "index" else value("other")
            prefix = [] if selected is index else [SSAConst(selected, 1)]
            return prefix + [SSAArraySet(array, selected, item),
                             SSACall("observe", (extracted,), builtin="__aether_string_byte_length")]
        analysis, extracted = _string_get(tail)
        assert BorrowInvalidationReason.COLLECTION_MUTATION in analysis.borrow_invalidation_reason(extracted)


def test_string_return_and_field_store_escape_require_owner():
    string = StringType(); item = value("item", string); array = value("array", ArrayType(string))
    index = value("index"); extracted = value("extracted", string)
    returned = SSAFunction("return_escape", [], string, [SSABasicBlock("entry", [
        SSAArrayNew(array, (item,)), SSAConst(index, 0), SSAArrayGet(extracted, array, index), SSAReturn(extracted)])])
    assert CollectionExtractionBorrowAnalysis(returned).classify_extraction_borrow(extracted) is ExtractionBorrowClassification.MUST_COPY_ESCAPES
    box = value("box", ClassRefType("Box"))
    stored = SSAFunction("field_escape", [SSAParameter("box", box.type)], VoidType(), [SSABasicBlock("entry", [
        SSAArrayNew(array, (item,)), SSAConst(index, 0), SSAArrayGet(extracted, array, index),
        SSAClassSet(box, 0, "text", extracted), SSAReturn()])])
    assert CollectionExtractionBorrowAnalysis(stored).classify_extraction_borrow(extracted) is ExtractionBorrowClassification.MUST_COPY_ESCAPES
