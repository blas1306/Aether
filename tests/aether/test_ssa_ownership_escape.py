from aether.ir.types import ClassRefType, IntType, ListType, VoidType
from aether.ssa.analysis import (
    ArcPairClassification, EscapeMode, OwnershipEscapeAnalysis,
    OwnershipState, OwnershipSummaryAnalysis, PostDominatorAnalysis,
)
from aether.ssa.model import (
    SSAClassNew, SSAClassSet, SSACall, SSAFunction, SSAInvokeIndirect,
    SSAListNew, SSAListPush, SSAModule, SSAParameter, SSAPropagate,
    SSAReturn, SSABasicBlock, SSAValue,
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
