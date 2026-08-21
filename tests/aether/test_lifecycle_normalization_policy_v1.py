from __future__ import annotations

import pytest

from aether.ir import (
    IRAssign, IRBasicBlock, IRCall, IRCopyInit, IRDestroy, IRFunction,
    IRInitDefault, IRLoad, IRModule, IRMoveInit, IRRelocate, IRReturn,
    IRStorage, IRStore, IRValue, IntType, InterfaceType, StringType, VoidType,
    expand_lifecycle,
)
from aether.ssa.lifecycle_normalization_policy import (
    LIFECYCLE_NORMALIZATION_POLICY_VERSION,
    LifecycleNormalizationPolicyError,
    check_lifecycle_normalization_policy_v1,
    load_lifecycle_normalization_policy,
)


def _module(instructions):
    return IRModule([IRFunction("f", [], VoidType(), [IRBasicBlock("entry", instructions)])])


def _instructions(module):
    return module.functions[0].blocks[0].instructions


def test_policy_version_inventory_and_rejection() -> None:
    policy = load_lifecycle_normalization_policy()
    assert LIFECYCLE_NORMALIZATION_POLICY_VERSION == 1
    assert policy["instruction_inventory"] == [
        "IRInitDefault", "IRCopyInit", "IRMoveInit", "IRAssign",
        "IRDestroy", "IRRelocate",
    ]
    assert check_lifecycle_normalization_policy_v1() == ()
    with pytest.raises(LifecycleNormalizationPolicyError, match="Unsupported"):
        load_lifecycle_normalization_policy(2)


def test_exact_primitive_expansions_and_input_immutability() -> None:
    a, b, c = (IRStorage(name, IntType()) for name in "abc")
    value = IRValue("value", IntType())
    original = _module([
        IRInitDefault(a), IRCopyInit(b, a), IRAssign(a, value),
        IRMoveInit(c, b), IRDestroy(a), IRRelocate(b, c, 1), IRReturn(),
    ])
    before = repr(original)
    expanded = expand_lifecycle(original)
    assert repr(original) == before
    assert [type(item).__name__ for item in _instructions(expanded)] == [
        "IRConst", "IRStore", "IRLoad", "IRStore", "IRStore", "IRLoad",
        "IRStore", "IRLoad", "IRStore", "IRReturn",
    ]


def test_exact_owned_copy_assign_destroy_order() -> None:
    source, destination = (IRStorage(name, StringType()) for name in ("source", "destination"))
    expanded = expand_lifecycle(_module([
        IRInitDefault(source), IRInitDefault(destination),
        IRCopyInit(destination := IRStorage("copy", StringType()), source),
        IRAssign(source, destination), IRDestroy(source), IRDestroy(destination),
        IRReturn(),
    ]))
    names = [
        (type(item).__name__, item.function if isinstance(item, IRCall) else None)
        for item in _instructions(expanded)
    ]
    assert names[4:7] == [("IRLoad", None), ("IRCall", "__aether_retain"), ("IRStore", None)]
    assert names[7:12] == [
        ("IRLoad", None), ("IRCall", "__aether_retain"), ("IRLoad", None),
        ("IRStore", None), ("IRCall", "__aether_release"),
    ]
    assert sum(name == ("IRCall", "__aether_release") for name in names) == 3


def test_interface_copy_uses_owned_copy_helper() -> None:
    parameter = IRValue("p", InterfaceType("I"))
    slot = IRStorage("slot", parameter.type)
    expanded = expand_lifecycle(_module([IRCopyInit(slot, parameter), IRDestroy(slot), IRReturn()]))
    assert [item.function for item in _instructions(expanded) if isinstance(item, IRCall)] == [
        "__aether_interface_copy_owned", "__aether_release"
    ]


def test_helper_sentinel_is_stable_but_policy_is_single_pass() -> None:
    value = IRValue("v", StringType())
    normalized = _module([IRCall("__aether_retain", (value,), None, "__aether_retain"), IRReturn()])
    assert expand_lifecycle(normalized) is normalized
    assert load_lifecycle_normalization_policy()["idempotence"]["domain"].startswith("single-pass only")
