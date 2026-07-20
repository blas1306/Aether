from __future__ import annotations

import pytest

from aether.ir import (
    IRBasicBlock,
    IRCall,
    IRConst,
    IRFunction,
    IRListClear,
    IRModule,
    IRReturn,
    IRSourceLocation,
    IRValue,
    IRVerificationError,
    IRVerifier,
    IntType,
    VerifierCategory,
    VerifierFailure,
    VerifierLocation,
    VerifierSeverity,
    rejected_verifier_result,
    verify_module_normalized,
)


def _accepted_module(value_name: str) -> IRModule:
    result = IRValue(value_name, IntType())
    return IRModule(
        [
            IRFunction(
                "main",
                [],
                IntType(),
                [IRBasicBlock("entry", [IRConst(result, 0), IRReturn(result)])],
            )
        ]
    )


def _invalid_list_clear(value_name: str) -> IRModule:
    value = IRValue(value_name, IntType())
    return IRModule(
        [
            IRFunction(
                "main",
                [],
                IntType(),
                [
                    IRBasicBlock(
                        "entry",
                        [IRConst(value, 0), IRListClear(value), IRReturn(value)],
                    )
                ],
            )
        ]
    )


def test_normalized_failures_have_deterministic_ordering() -> None:
    early = VerifierFailure(
        "IRV-006",
        VerifierSeverity.ERROR,
        VerifierCategory.DEFINITIONS,
        VerifierLocation(2, 3, "module.ae"),
        (VerifierLocation(5, 8, "module.ae"),),
    )
    earlier_location = VerifierFailure(
        "IRV-006",
        VerifierSeverity.ERROR,
        VerifierCategory.DEFINITIONS,
        VerifierLocation(1, 3, "module.ae"),
    )
    late = VerifierFailure(
        "IRV-100",
        VerifierSeverity.ERROR,
        VerifierCategory.COLLECTIONS,
    )

    forward = rejected_verifier_result((late, early, earlier_location))
    reverse = rejected_verifier_result((earlier_location, early, late))

    assert forward == reverse
    assert forward.failures == (earlier_location, early, late)
    assert forward.failures[1].secondary_locations == (
        VerifierLocation(5, 8, "module.ae"),
    )


def test_current_verifier_preserves_invariant_severity_category_and_location() -> None:
    result_value = IRValue("result", IntType())
    location = IRSourceLocation(line=7, column=11, path="example.ae")
    module = IRModule(
        [
            IRFunction(
                "main",
                [],
                IntType(),
                [
                    IRBasicBlock(
                        "entry",
                        [
                            IRCall("missing", (), result_value, source_location=location),
                            IRReturn(result_value),
                        ],
                    )
                ],
            )
        ]
    )

    normalized = verify_module_normalized(module)

    assert not normalized.accepted
    assert normalized.failures == (
        VerifierFailure(
            "IRV-052",
            VerifierSeverity.ERROR,
            VerifierCategory.CALLS,
            VerifierLocation(7, 11, "example.ae"),
        ),
    )
    assert normalized.failures[0].secondary_locations == ()


def test_equivalent_failures_with_distinct_python_objects_normalize_identically() -> None:
    first = verify_module_normalized(_invalid_list_clear("first"))
    second = verify_module_normalized(_invalid_list_clear("second"))

    assert first == second
    assert first.failures[0].invariant_id == "IRV-100"


def test_accepted_modules_normalize_identically() -> None:
    first = verify_module_normalized(_accepted_module("first"))
    second = verify_module_normalized(_accepted_module("second"))

    assert first == second
    assert first.accepted
    assert first.failures == ()


def test_normalization_does_not_change_current_verifier_error_text() -> None:
    module = _invalid_list_clear("value")

    with pytest.raises(IRVerificationError) as raised:
        IRVerifier(module).verify()

    assert str(raised.value) == "List clear expects list value, got int"
