from __future__ import annotations

import pytest

from aether.ir import (
    ArrayType,
    IRCopyInit,
    IRArrayGet,
    IRBasicBlock,
    IRCall,
    IRDestroy,
    IRFunction,
    IRJump,
    IRListGet,
    IRListNew,
    IRListPush,
    IRModule,
    IRParameter,
    IRPrint,
    IRReturn,
    IRStorage,
    IRStore,
    IRValue,
    IRVerificationError,
    IRVerifier,
    IntType,
    ListType,
    StringType,
    VoidType,
)


def _borrow_error(module: IRModule, invariant: str) -> IRVerificationError:
    with pytest.raises(IRVerificationError) as raised:
        IRVerifier(module).verify()
    failure = raised.value.normalized_failure
    assert failure is not None
    assert failure.invariant_id == invariant
    assert failure.category.value == "borrowing"
    return raised.value


@pytest.mark.parametrize(
    ("borrowed", "scope", "invariant"),
    [
        (True, None, "IRV-037"),
        (True, "", "IRV-037"),
        (True, "other", "IRV-038"),
        (False, "entry", "IRV-039"),
        (False, "", "IRV-039"),
    ],
)
def test_python_borrow_scope_contract(
    borrowed: bool,
    scope: str | None,
    invariant: str,
) -> None:
    collection_type = ListType(IntType())
    collection = IRParameter("collection", collection_type)
    index = IRParameter("index", IntType())
    result = IRValue("element", IntType())
    module = IRModule(
        [
            IRFunction(
                "scope",
                [collection, index],
                VoidType(),
                [
                    IRBasicBlock(
                        "entry",
                        [
                            IRListGet(result, collection, index, borrowed, scope),
                            IRReturn(),
                        ],
                    )
                ],
            )
        ]
    )

    _borrow_error(module, invariant)


@pytest.mark.parametrize(
    ("element_type", "retained", "accepted"),
    [
        (IntType(), False, True),
        (StringType(), False, False),
        (StringType(), True, True),
    ],
)
def test_python_owning_store_rule_is_managed_and_same_block(
    element_type,
    retained: bool,
    accepted: bool,
) -> None:
    collection_type = ArrayType(element_type)
    collection = IRParameter("collection", collection_type)
    index = IRParameter("index", IntType())
    result = IRValue("element", element_type)
    instructions = [IRArrayGet(result, collection, index, True, "entry")]
    if retained:
        instructions.append(
            IRCall(
                "__aether_retain",
                (result,),
                builtin="__aether_retain",
            )
        )
    instructions.extend((IRStore(IRValue("saved", element_type), result), IRReturn()))
    module = IRModule(
        [
            IRFunction(
                "store",
                [collection, index],
                VoidType(),
                [IRBasicBlock("entry", instructions)],
            )
        ]
    )

    if accepted:
        assert IRVerifier(module).verify() is module
    else:
        _borrow_error(module, "IRV-040")


def test_python_return_rejects_borrow_even_after_retain() -> None:
    collection_type = ListType(StringType())
    collection = IRParameter("collection", collection_type)
    index = IRParameter("index", IntType())
    result = IRValue("element", StringType())
    module = IRModule(
        [
            IRFunction(
                "escape",
                [collection, index],
                StringType(),
                [
                    IRBasicBlock(
                        "entry",
                        [
                            IRListGet(result, collection, index, True, "entry"),
                            IRCall(
                                "__aether_retain",
                                (result,),
                                builtin="__aether_retain",
                            ),
                            IRReturn(result),
                        ],
                    )
                ],
            )
        ]
    )

    _borrow_error(module, "IRV-041")


def test_python_rejects_mutation_only_when_borrow_is_receiver() -> None:
    inner_type = ListType(IntType())
    outer_type = ListType(inner_type)
    outer = IRParameter("outer", outer_type)
    index = IRParameter("index", IntType())
    item = IRParameter("item", IntType())
    borrowed = IRValue("borrowed", inner_type)
    module = IRModule(
        [
            IRFunction(
                "mutation",
                [outer, index, item],
                VoidType(),
                [
                    IRBasicBlock(
                        "entry",
                        [
                            IRListGet(borrowed, outer, index, True, "entry"),
                            IRListPush(borrowed, item),
                            IRReturn(),
                        ],
                    )
                ],
            )
        ]
    )

    _borrow_error(module, "IRV-042")


def test_python_allows_cross_block_read_aggregate_call_copy_and_multiple_consumers() -> None:
    element_type = ListType(IntType())
    outer_type = ListType(element_type)
    outer = IRParameter("outer", outer_type)
    index = IRParameter("index", IntType())
    borrowed = IRValue("borrowed", element_type)
    aggregate = IRValue("aggregate", ListType(element_type))
    copied = IRStorage("copied", element_type)
    observer = IRFunction(
        "observe",
        [IRParameter("value", element_type)],
        VoidType(),
        [IRBasicBlock("entry", [IRReturn()])],
    )
    caller = IRFunction(
        "boundaries",
        [outer, index],
        VoidType(),
        [
            IRBasicBlock(
                "entry",
                [
                    IRListGet(borrowed, outer, index, True, "entry"),
                    IRJump("use"),
                ],
            ),
            IRBasicBlock(
                "use",
                [
                    IRListNew(aggregate, (borrowed,)),
                    IRCall("observe", (borrowed,)),
                    IRCopyInit(copied, borrowed),
                    IRPrint(borrowed),
                    IRDestroy(copied),
                    IRReturn(),
                ],
            ),
        ],
    )
    module = IRModule([observer, caller])

    assert IRVerifier(module).verify() is module


def test_python_invalid_non_collection_source_is_a_type_rule_not_a_borrow_rule() -> None:
    source = IRParameter("source", IntType())
    index = IRParameter("index", IntType())
    borrowed = IRValue("borrowed", IntType())
    module = IRModule(
        [
            IRFunction(
                "invalid_source",
                [source, index],
                VoidType(),
                [
                    IRBasicBlock(
                        "entry",
                        [
                            IRArrayGet(borrowed, source, index, True, "entry"),
                            IRReturn(),
                        ],
                    )
                ],
            )
        ]
    )

    with pytest.raises(IRVerificationError) as raised:
        IRVerifier(module).verify()
    failure = raised.value.normalized_failure
    assert failure is not None
    assert failure.category.value == "collections"
    assert failure.invariant_id == "IRV-087"
