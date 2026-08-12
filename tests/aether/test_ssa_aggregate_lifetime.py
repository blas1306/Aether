from aether.ir.model import IRStructDefinition
from aether.ir.types import IntType, ListType, MethodResultType, StringType, StructType, VoidType
from aether.ssa.analysis import (
    AggregateLifetimeAnalysis, AggregateOrigin, ArcAttribution,
    BorrowOpportunity, EscapeKind, LifetimeCategory, MaterializationKind,
)
from aether.ssa.model import (
    SSAArrayGet, SSABasicBlock, SSABranch, SSACall, SSAConst, SSAFunction,
    SSAJump, SSAListGet, SSAListNew, SSAMethodResultNew, SSAParameter, SSAPhi,
    SSAReturn, SSAStructGet, SSAStructNew, SSAStructSet, SSAValue,
)


def v(name, type_): return SSAValue(name, type_)


PAIR = StructType("Pair")
PAIR_DEF = IRStructDefinition("Pair", (("left", StringType()), ("right", StringType())))


def analyze(instructions, parameters=(), return_type=VoidType()):
    fn = SSAFunction("f", list(parameters), return_type, [SSABasicBlock("entry", instructions)])
    return AggregateLifetimeAnalysis(fn, (PAIR_DEF,))


def test_construction_components_and_arc_attribution_are_separate_identities():
    left, right, pair = v("left", StringType()), v("right", StringType()), v("pair", PAIR)
    a = analyze([SSAConst(left, "l"), SSAConst(right, "r"), SSAStructNew(pair, (left, right)),
                 SSACall("retain", (pair,), builtin="__aether_retain"),
                 SSACall("release", (pair,), builtin="__aether_release"), SSAReturn()])
    life = a.aggregate_lifetime(pair)
    assert life.origin is AggregateOrigin.STRUCT_CONSTRUCTOR
    assert len(life.components) == 2
    assert [x.attribution for x in life.arc_events] == [ArcAttribution.CONSTRUCT, ArcAttribution.AGGREGATE_DESTROY]


def test_struct_reconstruction_preserves_semantic_equivalence_only_when_justified():
    left, right, old, rebuilt = v("left", StringType()), v("right", StringType()), v("old", PAIR), v("rebuilt", PAIR)
    a = analyze([SSAConst(left, "l"), SSAConst(right, "r"), SSAStructNew(old, (left, right)),
                 SSAStructSet(rebuilt, old, 1, "right", right), SSAReturn()])
    assert a.aggregate_origin(rebuilt) is AggregateOrigin.STRUCT_RECONSTRUCTION
    assert a.classify_copy(rebuilt) is LifetimeCategory.STRUCT_RECONSTRUCTION_TEMPORARY
    assert a.same_semantic_aggregate_value(old, rebuilt)


def test_struct_get_is_a_component_use_not_a_new_aggregate_instance():
    left, right, pair, out = v("left", StringType()), v("right", StringType()), v("pair", PAIR), v("out", StringType())
    a = analyze([SSAConst(left, "l"), SSAConst(right, "r"), SSAStructNew(pair, (left, right)),
                 SSAStructGet(out, pair, 0, "left"), SSAReturn(out)], return_type=StringType())
    assert len(a.lifetimes()) == 1
    assert a.ownership.provenance(out) == a.ownership.provenance(left)


def test_collection_extraction_immediate_use_is_representation_induced_borrow_candidate():
    listing, index, pair, out = v("list", ListType(PAIR)), v("i", IntType()), v("pair", PAIR), v("out", StringType())
    a = analyze([SSAListNew(listing), SSAListGet(pair, listing, index), SSAStructGet(out, pair, 0, "left"),
                 SSACall("release", (pair,), builtin="__aether_release"), SSAReturn()])
    life = a.aggregate_lifetime(pair)
    assert life.primary_category is LifetimeCategory.COLLECTION_EXTRACTION_TEMPORARY
    assert life.borrow_opportunity is BorrowOpportunity.COULD_BORROW_INTERNAL_TEMPORARY
    assert life.materialization is MaterializationKind.REPRESENTATION_INDUCED


def test_method_result_and_return_escape_are_distinguished():
    left, right, pair = v("left", StringType()), v("right", StringType()), v("pair", PAIR)
    wrapper = v("wrapper", MethodResultType(PAIR, StringType()))
    a = analyze([SSAConst(left, "l"), SSAConst(right, "r"), SSAStructNew(pair, (left, right)),
                 SSAMethodResultNew(wrapper, pair, left), SSAReturn(wrapper)], return_type=wrapper.type)
    assert a.aggregate_origin(wrapper) is AggregateOrigin.METHOD_RETURN
    assert a.aggregate_escape(wrapper) is EscapeKind.RETURN
    assert LifetimeCategory.RETURN_VALUE in a.aggregate_lifetime(wrapper).secondary_reasons


def test_parameter_call_escape_and_collection_store_escape():
    parameter = SSAParameter("pair", PAIR)
    a = analyze([SSACall("sink", (parameter,)), SSAReturn()], parameters=(parameter,))
    assert a.aggregate_escape(parameter) is EscapeKind.CALL


def test_aggregate_phi_in_loop_is_loop_carried():
    cond = SSAParameter("cond", IntType()); seed, phi = v("seed", PAIR), v("phi", PAIR)
    fn = SSAFunction("loop", [cond, SSAParameter("seed", PAIR)], VoidType(), [
        SSABasicBlock("entry", [SSAJump("header")]),
        SSABasicBlock("header", [SSAPhi(phi, (("entry", seed), ("latch", phi))), SSABranch(cond, "latch", "exit")]),
        SSABasicBlock("latch", [SSAJump("header")]), SSABasicBlock("exit", [SSAReturn()])])
    a = AggregateLifetimeAnalysis(fn, (PAIR_DEF,))
    assert a.aggregate_lifetime(phi).primary_category is LifetimeCategory.LOOP_CARRIED_AGGREGATE


def test_debug_output_is_deterministic():
    pair = SSAParameter("pair", PAIR); a = analyze([SSAReturn()], parameters=(pair,))
    assert a.debug_string() == AggregateLifetimeAnalysis(a.function, (PAIR_DEF,)).debug_string()
