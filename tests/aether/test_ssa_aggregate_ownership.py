from aether.ir.model import IRStructDefinition
from aether.ir.types import ClassRefType, IntType, ListType, MethodResultType, StringType, StructType, VoidType
from aether.ssa.analysis import ComponentPath, EscapeMode, FieldIdentity, OwnershipEscapeAnalysis, OwnershipState
from aether.ssa.model import (
    SSABasicBlock, SSAClassNew, SSACall, SSAConst, SSAFunction, SSAListGet, SSAListNew,
    SSAMethodResultNew, SSAMethodResultReceiver, SSAMethodResultValue,
    SSAParameter, SSAPhi, SSAReturn, SSAStructGet, SSAStructNew, SSAStructSet,
    SSAValue,
)


def v(name, type_):
    return SSAValue(name, type_)


def path(owner, name, index):
    return ComponentPath((FieldIdentity(owner, name, index),))


def test_struct_string_list_and_class_components_keep_independent_roots():
    record = StructType("Record")
    definition = IRStructDefinition("Record", (("name", StringType()), ("items", ListType(IntType())),
                                                   ("object", ClassRefType("Box"))))
    name, items, obj, aggregate = v("name", StringType()), v("items", ListType(IntType())), v("obj", ClassRefType("Box")), v("s", record)
    function = SSAFunction("components", [], VoidType(), [SSABasicBlock("entry", [
        SSAConst(name, "a"), SSAListNew(items), SSAClassNew(obj),
        SSAStructNew(aggregate, (name, items, obj)), SSAReturn(),
    ])])
    analysis = OwnershipEscapeAnalysis(function, structs=(definition,))
    roots = [analysis.component_provenance(aggregate, path("Record", field, index)).provenance
             for index, field in enumerate(("name", "items", "object"))]
    assert all(item.exact for item in roots)
    assert len({next(iter(item.roots)) for item in roots}) == 3


def test_struct_get_and_copy_recover_component_identity():
    record = StructType("Record"); definition = IRStructDefinition("Record", (("name", StringType()),))
    source, aggregate, copied, extracted = v("source", StringType()), v("s", record), v("copy", record), v("out", StringType())
    function = SSAFunction("copy", [], StringType(), [SSABasicBlock("entry", [
        SSAConst(source, "a"), SSAStructNew(aggregate, (source,)),
        SSAStructSet(copied, aggregate, 0, "name", source),
        SSAStructGet(extracted, copied, 0, "name"), SSAReturn(extracted),
    ])])
    analysis = OwnershipEscapeAnalysis(function, structs=(definition,))
    assert analysis.provenance(extracted) == analysis.provenance(source)


def test_struct_set_preserves_unaffected_and_replaces_changed_component():
    pair = StructType("Pair"); definition = IRStructDefinition("Pair", (("left", StringType()), ("right", StringType())))
    left, old, new = v("left", StringType()), v("old", StringType()), v("new", StringType())
    before, after = v("before", pair), v("after", pair)
    function = SSAFunction("set", [], VoidType(), [SSABasicBlock("entry", [
        SSAConst(left, "l"), SSAConst(old, "o"), SSAConst(new, "n"),
        SSAStructNew(before, (left, old)), SSAStructSet(after, before, 1, "right", new), SSAReturn(),
    ])])
    analysis = OwnershipEscapeAnalysis(function, structs=(definition,))
    assert analysis.component_provenance(after, path("Pair", "left", 0)).provenance == analysis.provenance(left)
    assert analysis.component_provenance(after, path("Pair", "right", 1)).provenance == analysis.provenance(new)
    assert analysis.component_provenance(before, path("Pair", "right", 1)).provenance == analysis.provenance(old)


def test_nested_struct_extraction_preserves_nested_reference():
    inner, outer = StructType("Inner"), StructType("Outer")
    definitions = (IRStructDefinition("Inner", (("items", ListType(IntType())),)),
                   IRStructDefinition("Outer", (("inner", inner),)))
    items, inside, outside, extracted_inner, extracted_items = (v("items", ListType(IntType())), v("inside", inner),
        v("outside", outer), v("inner.out", inner), v("items.out", ListType(IntType())))
    function = SSAFunction("nested", [], VoidType(), [SSABasicBlock("entry", [
        SSAListNew(items), SSAStructNew(inside, (items,)), SSAStructNew(outside, (inside,)),
        SSAStructGet(extracted_inner, outside, 0, "inner"),
        SSAStructGet(extracted_items, extracted_inner, 0, "items"), SSAReturn(),
    ])])
    analysis = OwnershipEscapeAnalysis(function, structs=definitions)
    assert analysis.provenance(extracted_items) == analysis.provenance(items)


def test_aggregate_phi_is_component_wise_exact_or_unknown():
    record = StructType("Record"); definition = IRStructDefinition("Record", (("name", StringType()),))
    same, other = v("same", StringType()), v("other", StringType())
    a, b, c, exact, mixed = (v(name, record) for name in ("a", "b", "c", "exact", "mixed"))
    function = SSAFunction("phis", [], VoidType(), [SSABasicBlock("entry", [
        SSAConst(same, "s"), SSAConst(other, "o"), SSAStructNew(a, (same,)), SSAStructNew(b, (same,)),
        SSAStructNew(c, (other,)), SSAPhi(exact, (("a", a), ("b", b))),
        SSAPhi(mixed, (("a", a), ("c", c))), SSAReturn(),
    ])])
    analysis = OwnershipEscapeAnalysis(function, structs=(definition,)); component = path("Record", "name", 0)
    assert analysis.component_provenance(exact, component).provenance.exact
    assert not analysis.component_provenance(mixed, component).provenance.exact


def test_aggregate_parameter_has_symbolic_borrowed_components():
    record = StructType("Record"); definition = IRStructDefinition("Record", (("name", StringType()),))
    parameter = SSAParameter("record", record)
    analysis = OwnershipEscapeAnalysis(SSAFunction("parameter", [parameter], VoidType(), [SSABasicBlock("entry", [SSAReturn()])]),
                                       structs=(definition,))
    fact = analysis.component_provenance(parameter, path("Record", "name", 0))
    assert fact.provenance.exact and fact.ownership is OwnershipState.BORROWED


def test_method_result_components_are_independent():
    receiver_type = StructType("Receiver"); definition = IRStructDefinition("Receiver", (("name", StringType()),))
    name, receiver = v("name", StringType()), v("receiver", receiver_type)
    result_value, wrapper = v("value", StringType()), v("wrapper", MethodResultType(receiver_type, StringType()))
    receiver_out, value_out = v("receiver.out", receiver_type), v("value.out", StringType())
    function = SSAFunction("method", [], VoidType(), [SSABasicBlock("entry", [
        SSAConst(name, "r"), SSAConst(result_value, "v"), SSAStructNew(receiver, (name,)),
        SSAMethodResultNew(wrapper, receiver, result_value),
        SSAMethodResultReceiver(receiver_out, wrapper), SSAMethodResultValue(value_out, wrapper), SSAReturn(),
    ])])
    analysis = OwnershipEscapeAnalysis(function, structs=(definition,))
    assert analysis.provenance(value_out) == analysis.provenance(result_value)
    assert analysis.component_provenance(receiver_out, path("Receiver", "name", 0)).provenance == analysis.provenance(name)


def test_struct_loaded_from_collection_has_no_invented_component_facts():
    record = StructType("Record"); definition = IRStructDefinition("Record", (("name", StringType()),))
    listing, index, loaded = v("list", ListType(record)), v("index", IntType()), v("loaded", record)
    function = SSAFunction("collection", [], VoidType(), [SSABasicBlock("entry", [
        SSAListNew(listing), SSAListGet(loaded, listing, index), SSAReturn(),
    ])])
    analysis = OwnershipEscapeAnalysis(function, structs=(definition,))
    assert analysis.aggregate_provenance(loaded).components == ()


def test_aggregate_escape_propagates_to_known_reference_components():
    record = StructType("Record"); definition = IRStructDefinition("Record", (("name", StringType()),))
    name, aggregate, extracted = v("name", StringType()), v("record", record), v("out", StringType())
    function = SSAFunction("escape", [], VoidType(), [SSABasicBlock("entry", [
        SSAConst(name, "a"), SSAStructNew(aggregate, (name,)),
        SSACall("unknown", (aggregate,)), SSAStructGet(extracted, aggregate, 0, "name"), SSAReturn(),
    ])])
    analysis = OwnershipEscapeAnalysis(function, structs=(definition,))
    assert analysis.escape_modes(aggregate) & EscapeMode.CALL
    assert analysis.escape_modes(extracted) & EscapeMode.CALL
