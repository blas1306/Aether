import json

from aether.ssa.analysis import (ConcreteCandidateStatus as Status,
    ConcreteOptimizationCandidate as Candidate, select_recommendation)


def _candidate(**changes):
    values = dict(family="GVN/CSE", workload="w.ae", function="f", opcode="SSABinaryOp",
        instructions=("entry:1 %a = add %x, %y", "entry:2 %b = add %x, %y"),
        operands=("x", "y"), proof=("pure", "dominates", "nontrapping"),
        transformation="replace uses(%b) -> %a; delete %b", removed=("b",),
        status=Status.TRANSFORMABLE_NOW)
    values.update(changes); return Candidate(**values)


def test_exact_verified_candidate_is_productive():
    candidate = _candidate()
    assert candidate.verify() == (True, ())
    assert candidate.productive


def test_hypothesis_only_is_not_productive():
    assert not _candidate(status=Status.HYPOTHESIS_ONLY).productive


def test_missing_exact_instruction_is_rejected():
    valid, errors = _candidate(instructions=()).verify()
    assert not valid and "missing exact instruction" in errors


def test_missing_transformation_is_rejected():
    assert not _candidate(transformation=None).productive


def test_unknown_proof_is_rejected_fail_closed():
    valid, errors = _candidate(proof=("alias UNKNOWN",)).verify()
    assert not valid and "unknown proof" in errors


def test_known_blocker_is_rejected_fail_closed():
    assert not _candidate(blockers=("may trap",)).productive


def test_historical_false_copy_candidate_remains_nontransformable():
    copy = _candidate(family="copy elision", opcode="SSACall", operands=("callee",),
        proof=("no explicit source/destination copy edge",), transformation=None,
        removed=(), status=Status.HYPOTHESIS_ONLY)
    assert not copy.productive


def test_recommendation_cannot_select_zero_candidate_family():
    assert select_recommendation((_candidate(status=Status.HYPOTHESIS_ONLY),),
        ("GVN/CSE",)) == "IMPROVE_OPTIMIZATION_MEASUREMENT_FIRST"


def test_fingerprint_and_json_are_deterministic():
    one, two = _candidate(), _candidate()
    assert one.fingerprint == two.fingerprint
    assert json.dumps(one.as_dict(), sort_keys=True) == json.dumps(two.as_dict(), sort_keys=True)
