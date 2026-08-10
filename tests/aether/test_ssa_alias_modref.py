from __future__ import annotations

from aether.ir.types import ClassRefType, IntType, ListType, StructType, VoidType
from aether.ssa.analysis import (
    AliasAnalysis, AliasRelation, AliasUnknownReason, ModRefAnalysis,
    FieldIdentity, FieldLocation, ModRefEffect, ShapeAnalysis,
    StructFieldLocation, SummaryAnalysis,
)
from aether.ssa.model import (
    SSAClassGet, SSAClassNew, SSAClassSet, SSAConst, SSAFunction, SSAInvokeIndirect, SSAListCopy,
    SSAListGet, SSAListLength, SSAListNew, SSAListPush, SSAModule, SSAParameter,
    SSAPhi, SSAReturn, SSABasicBlock, SSACall, SSAStructGet, SSAStructSet, SSAValue,
)

I = IntType()


def value(name, type_=I): return SSAValue(name, type_)


def test_alias_lattice_fresh_copies_parameters_and_phi() -> None:
    class_type = ClassRefType("Box"); list_type = ListType(I)
    parameter = SSAParameter("parameter", class_type)
    first, second, merged = value("first", class_type), value("second", class_type), value("merged", class_type)
    listing, copied = value("listing", list_type), value("copied", list_type)
    function = SSAFunction("aliases", [parameter], VoidType(), [
        SSABasicBlock("entry", [
            SSAClassNew(first), SSAClassNew(second),
            SSAPhi(merged, (("left", first), ("right", parameter))),
            SSAListNew(listing), SSAListCopy(copied, listing), SSAReturn(),
        ])
    ])
    analysis = AliasAnalysis(function)
    assert analysis.alias(first, first) is AliasRelation.MUST_ALIAS
    assert analysis.alias(first, second) is AliasRelation.NO_ALIAS
    assert analysis.alias(first, parameter) is AliasRelation.MAY_ALIAS
    assert analysis.alias(first, merged) is AliasRelation.MAY_ALIAS
    assert analysis.alias(listing, copied) is AliasRelation.NO_ALIAS
    assert analysis.alias(value("x"), value("y")) is AliasRelation.NO_ALIAS
    analysis.verify()
    assert "phi-merge" in analysis.debug_string()


def test_modref_and_fact_preservation_are_alias_specific() -> None:
    list_type = ListType(I); item = value("item")
    first, second, length, got = value("first", list_type), value("second", list_type), value("length"), value("got")
    mutation = SSAListPush(second, item); read = SSAListGet(got, first, item)
    function = SSAFunction("effects", [], VoidType(), [SSABasicBlock("entry", [
        SSAConst(item, 0), SSAListNew(first), SSAListNew(second),
        SSAListLength(length, first), read, mutation, SSAReturn(),
    ])])
    analysis = ModRefAnalysis(function)
    assert analysis.effects(read, first).effect is ModRefEffect.READ
    assert analysis.effects(mutation, second).effect is ModRefEffect.READ_MODIFY
    assert analysis.effects(mutation, first).effect is ModRefEffect.NO_ACCESS
    assert analysis.preserves_length_fact(mutation, first)
    assert not analysis.preserves_length_fact(mutation, second)


def test_unknown_indirect_call_invalidates_even_on_exception_edge() -> None:
    list_type = ListType(I); listing = SSAParameter("listing", list_type)
    callee = value("callee", ClassRefType("Callable")); event = value("event", ClassRefType("Error"))
    invoke = SSAInvokeIndirect(callee, (listing,), None, event, "normal", "exceptional")
    function = SSAFunction("invoke", [listing], VoidType(), [SSABasicBlock("entry", [invoke])])
    decision = ModRefAnalysis(function).effects(invoke, listing)
    assert decision.effect is ModRefEffect.UNKNOWN
    assert decision.reason is AliasUnknownReason.UNKNOWN_INDIRECT_TARGET


def test_direct_summaries_converge_through_mutual_recursion() -> None:
    list_type = ListType(I); a = SSAParameter("a", list_type); b = SSAParameter("b", list_type)
    one = value("one"); pop = SSAListPush(a, one)
    first = SSAFunction("first", [a], VoidType(), [SSABasicBlock("entry", [
        SSAConst(one, 1), pop, SSACall("second", (a,)), SSAReturn(),
    ])])
    second = SSAFunction("second", [b], VoidType(), [SSABasicBlock("entry", [
        SSACall("first", (b,)), SSAReturn(),
    ])])
    summaries = SummaryAnalysis().compute(SSAModule([first, second]))
    assert summaries["first"].modified_parameters == frozenset({0})
    assert summaries["second"].modified_parameters == frozenset({0})
    assert SummaryAnalysis.debug_string(summaries) == SummaryAnalysis.debug_string(summaries)


def test_known_readonly_call_preserves_list_fact() -> None:
    list_type = ListType(I); parameter = SSAParameter("parameter", list_type); length = value("length")
    reader = SSAFunction("reader", [parameter], I, [SSABasicBlock("entry", [
        SSAListLength(length, parameter), SSAReturn(length),
    ])])
    listing = value("listing", list_type); call = SSACall("reader", (listing,), length)
    caller = SSAFunction("caller", [], VoidType(), [SSABasicBlock("entry", [SSAListNew(listing), call, SSAReturn()])])
    summaries = SummaryAnalysis().compute(SSAModule([reader, caller]))
    analysis = ModRefAnalysis(caller, summaries)
    assert summaries["reader"].read_parameters == frozenset({0})
    assert analysis.preserves_length_fact(call, listing)
    assert ShapeAnalysis().compute(caller, analysis).length_of(listing, "entry") is not None


def test_nominal_field_locations_compose_with_base_aliases() -> None:
    box = ClassRefType("Box"); obj = value("obj", box); alias = value("alias", box)
    merged = SSAPhi(alias, (("left", obj), ("right", obj)))
    function = SSAFunction("fields", [], VoidType(), [SSABasicBlock("entry", [
        SSAClassNew(obj), merged, SSAReturn(),
    ])])
    aliases = AliasAnalysis(function)
    a = FieldIdentity("Box", "a", 0); b = FieldIdentity("Box", "b", 1)
    assert aliases.location_alias(FieldLocation(obj, a), FieldLocation(alias, a)) is AliasRelation.MUST_ALIAS
    assert aliases.location_alias(FieldLocation(obj, a), FieldLocation(alias, b)) is AliasRelation.NO_ALIAS
    assert FieldIdentity("Other", "a", 0) != a

    left = SSAParameter("left", box); right = SSAParameter("right", box)
    parameter_function = SSAFunction("parameter_fields", [left, right], VoidType(), [
        SSABasicBlock("entry", [SSAReturn()]),
    ])
    parameter_aliases = AliasAnalysis(parameter_function)
    assert parameter_aliases.location_alias(FieldLocation(left, a), FieldLocation(right, a)) is AliasRelation.MAY_ALIAS
    assert parameter_aliases.location_alias(FieldLocation(left, a), FieldLocation(right, b)) is AliasRelation.NO_ALIAS
    parameter_aliases.verify_locations((FieldLocation(left, a), FieldLocation(right, a)))
    assert "Box.a#0" in parameter_aliases.location_debug_string(FieldLocation(left, a))


def test_class_field_modref_preserves_distinct_field_fact() -> None:
    box = ClassRefType("Box"); obj = value("obj", box); item = value("item"); got = value("got")
    set_b = SSAClassSet(obj, 1, "b", item)
    get_a = SSAClassGet(got, obj, 0, "a")
    function = SSAFunction("field_effects", [], VoidType(), [SSABasicBlock("entry", [
        SSAClassNew(obj), SSAConst(item, 1), get_a, set_b, SSAReturn(),
    ])])
    analysis = ModRefAnalysis(function)
    a = FieldIdentity("Box", "a", 0); b = FieldIdentity("Box", "b", 1)
    assert analysis.effects(get_a, FieldLocation(obj, a)).effect is ModRefEffect.READ
    assert analysis.effects(set_b, FieldLocation(obj, a)).effect is ModRefEffect.NO_ACCESS
    assert analysis.effects(set_b, FieldLocation(obj, b)).effect is ModRefEffect.MODIFY
    assert analysis.preserves_field_fact(set_b, obj, a)


def test_direct_summary_retains_field_precision_and_exceptional_effects() -> None:
    box = ClassRefType("Box"); parameter = SSAParameter("box", box); one = value("one")
    writer = SSAFunction("writer", [parameter], VoidType(), [SSABasicBlock("entry", [
        SSAConst(one, 1), SSAClassSet(parameter, 1, "b", one), SSAReturn(),
    ])], may_throw=True)
    obj = value("obj", box); call = SSACall("writer", (obj,))
    caller = SSAFunction("caller_fields", [], VoidType(), [SSABasicBlock("entry", [
        SSAClassNew(obj), call, SSAReturn(),
    ])])
    summaries = SummaryAnalysis().compute(SSAModule([writer, caller]))
    summary = summaries["writer"]
    assert summary.modified_parameters == frozenset()
    assert summary.may_throw
    analysis = ModRefAnalysis(caller, summaries)
    assert analysis.preserves_field_fact(call, obj, FieldIdentity("Box", "a", 0))
    assert not analysis.preserves_field_fact(call, obj, FieldIdentity("Box", "b", 1))


def test_struct_set_reconstructs_without_mutating_input_field_storage() -> None:
    pair = StructType("Pair"); original = value("original", pair); updated = value("updated", pair)
    item = value("item"); got = value("got")
    set_right = SSAStructSet(updated, original, 1, "right", item)
    get_left = SSAStructGet(got, original, 0, "left")
    function = SSAFunction("struct_fields", [], VoidType(), [SSABasicBlock("entry", [
        SSAConst(item, 1), get_left, set_right, SSAReturn(),
    ])])
    analysis = ModRefAnalysis(function)
    left = StructFieldLocation(original, FieldIdentity("Pair", "left", 0))
    assert analysis.effects(get_left, left).effect is ModRefEffect.READ
    assert analysis.preserves_memory_fact(set_right, left)
