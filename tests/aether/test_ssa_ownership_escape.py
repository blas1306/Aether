from aether.ir.types import ClassRefType, IntType, ListType, NullableType, StringType, VoidType
from aether.ssa.analysis import (
    ArcPairClassification, EscapeMode, OwnershipEscapeAnalysis,
    OwnershipState, OwnershipSummaryAnalysis, PostDominatorAnalysis,
    AliasUnknownReason, AliasAnalysis,
)
from aether.ssa.model import (
    SSAClassNew, SSAClassSet, SSACall, SSACast, SSAConst, SSAFunction, SSAInvokeIndirect,
    SSAListNew, SSAListPush, SSAModule, SSAParameter, SSAPropagate,
    SSAPhi, SSAReturn, SSABasicBlock, SSAValue,
)


I = IntType()


def value(name, type_=I):
    return SSAValue(name, type_)


def test_fresh_local_and_return_escape_are_distinguished():
    type_ = ClassRefType("Box")
    local, returned = value("local", type_), value("returned", type_)
    function = SSAFunction("fresh", [], type_, [SSABasicBlock("entry", [
        SSAClassNew(local), SSAClassNew(returned), SSAReturn(returned),
    ])])
    analysis = OwnershipEscapeAnalysis(function)
    assert analysis.is_fresh(local)
    assert analysis.ownership_state(local, "entry") is OwnershipState.OWNED
    assert analysis.escape_modes(local) is EscapeMode.NO_ESCAPE
    assert analysis.escape_modes(returned) & EscapeMode.RETURN
    analysis.verify()


def test_field_collection_and_unknown_call_escape_modes():
    box = value("box", ClassRefType("Box")); child = value("child", ClassRefType("Child"))
    listing = value("listing", ListType(ClassRefType("Child")))
    function = SSAFunction("escapes", [], VoidType(), [SSABasicBlock("entry", [
        SSAClassNew(box), SSAClassNew(child), SSAListNew(listing),
        SSAClassSet(box, 0, "child", child), SSAListPush(listing, child),
        SSACall("external", (child,)), SSAReturn(),
    ])])
    modes = OwnershipEscapeAnalysis(function).escape_modes(child)
    assert modes & EscapeMode.FIELD
    assert modes & EscapeMode.COLLECTION
    assert modes & EscapeMode.CALL
    assert modes & EscapeMode.MAY_ESCAPE


def test_exceptional_cfg_blocks_arc_pair_and_postdominance():
    type_ = ClassRefType("Box"); obj = value("obj", type_)
    callee = value("callee", ClassRefType("Callable")); event = value("event", ClassRefType("Error"))
    function = SSAFunction("arc", [], VoidType(), [
        SSABasicBlock("entry", [SSAClassNew(obj), SSACall("retain", (obj,), builtin="__aether_retain"),
                                SSAInvokeIndirect(callee, (obj,), None, event, "normal", "cleanup")]),
        SSABasicBlock("normal", [SSACall("release", (obj,), builtin="__aether_release"), SSAReturn()]),
        SSABasicBlock("cleanup", [SSAPropagate(event)]),
    ])
    postdom = PostDominatorAnalysis(function)
    assert not postdom.post_dominates("normal", "entry")
    candidate = OwnershipEscapeAnalysis(function).candidate_arc_pairs()[0]
    assert candidate.classification in {
        ArcPairClassification.BLOCKED_BY_EXCEPTION,
        ArcPairClassification.NEEDS_ESCAPE_INFO,
    }


def test_direct_summaries_converge_for_mutual_recursion():
    type_ = ClassRefType("Box"); a = SSAParameter("a", type_); b = SSAParameter("b", type_)
    first = SSAFunction("first", [a], type_, [SSABasicBlock("entry", [SSACall("second", (a,)), SSAReturn(a)])])
    second = SSAFunction("second", [b], type_, [SSABasicBlock("entry", [SSACall("first", (b,)), SSAReturn(b)])])
    summaries = OwnershipSummaryAnalysis().compute(SSAModule([first, second]))
    assert summaries["first"].returned_parameters == frozenset({0})
    assert summaries["second"].escaping_parameters == frozenset({0})
    assert OwnershipSummaryAnalysis.debug_string(summaries) == OwnershipSummaryAnalysis.debug_string(summaries)


def test_exact_string_literal_cast_and_same_root_phi_propagate():
    string = StringType(); nullable = NullableType(string)
    literal = value("literal", string); adapted = value("adapted", nullable)
    joined = value("joined", nullable)
    function = SSAFunction("copies", [], nullable, [SSABasicBlock("entry", [
        SSAConst(literal, "x"), SSACast(adapted, literal),
        SSAPhi(joined, (("left", adapted), ("right", adapted))), SSAReturn(joined),
    ])])
    aliases = AliasAnalysis(function)
    assert aliases.provenance(literal).exact
    assert aliases.provenance(adapted) == aliases.provenance(literal)
    assert aliases.provenance(joined) == aliases.provenance(literal)


def test_phi_different_roots_and_unknown_input_fail_closed_with_precise_reasons():
    string = StringType(); left = value("left", string); right = value("right", string)
    different = value("different", string); unknown = value("unknown", string)
    mixed = value("mixed", string)
    function = SSAFunction("phis", [], string, [SSABasicBlock("entry", [
        SSAConst(left, "a"), SSAConst(right, "b"),
        SSAPhi(different, (("a", left), ("b", right))),
        SSACall("external", (), unknown),
        SSAPhi(mixed, (("a", left), ("b", unknown))), SSAReturn(mixed),
    ])])
    aliases = AliasAnalysis(function)
    assert aliases.provenance(different).reason is AliasUnknownReason.PHI_DIFFERENT_ROOTS
    assert aliases.provenance(mixed).reason is AliasUnknownReason.PHI_UNKNOWN_INPUT


def test_trusted_fresh_helper_and_untrusted_runtime_helper_are_distinct():
    string = StringType(); source = SSAParameter("source", string)
    fresh = value("fresh", string); unknown = value("unknown", string)
    function = SSAFunction("helpers", [source], string, [SSABasicBlock("entry", [
        SSACall("text.formatInt", (value("number"),), fresh,
                builtin="text.formatInt"),
        SSACall("mystery", (), unknown, builtin="__aether_mystery"), SSAReturn(fresh),
    ])])
    aliases = AliasAnalysis(function)
    assert aliases.provenance(fresh).exact
    assert aliases.provenance(unknown).reason is AliasUnknownReason.UNKNOWN_RUNTIME_HELPER
