from __future__ import annotations

from io import BytesIO

import pytest

from aether.backend.llvm import print_llvm
from aether.backend.llvm.layout import LLVMTypeLayouts
from aether.backend.llvm.run import LLVMRunner
from aether.collection_value import (
    MAX_STRONG_COUNT,
    array_alloc,
    collection_debug_counters,
    list_alloc,
    reset_collection_debug_counters,
)
from aether.pipeline import lower_to_verified_ssa, prepare_typed_program
from aether.ir.lifecycle import LifecycleTypeRegistry
from aether.ir.model import IRStructDefinition
from aether.ir.types import ArrayType as IRArrayType, IntType, ListType as IRListType, StructType
from aether.string_value import StringValue
from aether.typechecker import TypeChecker
from aether.types import AetherValue, ListType


def _typed(source: str):
    return prepare_typed_program(source, TypeChecker())


def test_collection_object_alloc_retain_release_and_last_owner() -> None:
    reset_collection_debug_counters()
    value = array_alloc("int")

    assert value.strong_count == 1 and value.alive
    assert value.retain() is value
    assert value.strong_count == 2
    value.release()
    assert value.strong_count == 1 and value.alive
    value.release()

    assert value.freed and not value.alive
    counters = collection_debug_counters()
    assert counters.objects_allocated == counters.objects_freed == 1
    assert counters.buffers_allocated == counters.buffers_freed == 1
    with pytest.raises(RuntimeError, match="already released"):
        value.release()


def test_collection_and_containing_struct_layouts_are_nontrivial_handles() -> None:
    collection = IRListType(IRArrayType(IntType()))
    definition = IRStructDefinition("Owner", (("items", collection),))
    layouts = LLVMTypeLayouts([definition])
    lifecycle = LifecycleTypeRegistry([definition])

    for type_ in (collection, StructType("Owner")):
        layout = layouts.layout(type_)
        traits = lifecycle.traits(type_)
        assert layout.sized and not layout.trivially_copyable
        assert layout.trivially_relocatable and layout.needs_destroy
        assert layout.needs_retain and layout.contains_references
        assert not traits.trivially_copyable
        assert traits.trivially_relocatable and traits.needs_destroy


def test_collection_reference_count_checks_overflow_and_underflow() -> None:
    overflow = list_alloc("int")
    overflow.strong_count = MAX_STRONG_COUNT
    with pytest.raises(OverflowError, match="reference count overflow"):
        overflow.retain()

    underflow = list_alloc("int")
    underflow.strong_count = 0
    with pytest.raises(RuntimeError, match="reference count underflow"):
        underflow.release()


def test_empty_mutable_collections_are_independent_objects() -> None:
    left = list_alloc("int")
    right = list_alloc("int")

    assert left is not right
    left.append(AetherValue("int", 1))
    assert len(left) == 1 and len(right) == 0

    left.release()
    right.release()


def test_nested_collection_and_string_elements_release_recursively() -> None:
    reset_collection_debug_counters()
    inner = list_alloc("int", [AetherValue("int", 7)])
    dynamic = StringValue.dynamic("owned")
    outer = list_alloc(
        ListType("int"),
        [AetherValue(ListType("int"), inner)],
    )
    strings = list_alloc("string", [AetherValue("string", dynamic)])

    assert inner.strong_count == 2
    assert dynamic.strong_count == 2
    outer.release()
    strings.release()
    assert inner.strong_count == 1 and inner.alive
    assert dynamic.strong_count == 1

    inner.release()
    dynamic.release()
    assert collection_debug_counters().objects_freed == 3


def test_list_set_clear_and_pop_apply_element_lifecycle() -> None:
    first = list_alloc("int")
    second = list_alloc("int")
    outer = list_alloc(ListType("int"), [AetherValue(ListType("int"), first)])

    outer[0] = AetherValue(ListType("int"), second)
    assert first.strong_count == 1
    assert second.strong_count == 2

    transferred = outer.pop()
    assert transferred.value is second and second.strong_count == 2
    outer.release()
    assert second.strong_count == 2
    transferred.value.release()
    first.release()
    second.release()


def test_native_rc_covers_alias_assignment_parameter_return_and_nested_release() -> None:
    source = """
List<int> identity(List<int> xs) { return xs; }
void mutate(List<int> xs) { xs.push(4); }
int main() {
    List<int> a = {1, 2, 3};
    List<int> b = a;
    List<int> c = identity(b);
    mutate(c);
    List<List<int>> nested = {c};
    return a.length + nested[0][3];
}
"""
    typed = _typed(source)
    llvm = print_llvm(lower_to_verified_ssa(typed))

    assert "%AetherList = type { i64, i64, ptr, i64 }" in llvm
    assert "@aether_list_retain_i32" in llvm
    assert "@aether_list_release_i32" in llvm
    assert "@aether_list_release_list_i32" in llvm
    assert "call void @free(ptr %data)" in llvm
    assert "call void @free(ptr %object)" in llvm
    assert LLVMRunner().run(typed, stdout=BytesIO(), stderr=BytesIO()) == 8


def test_native_collection_struct_field_copy_and_return_keep_alias_alive() -> None:
    source = """
struct State { List<int> values; }
List<int> valuesOf(State state) { return state.values; }
int main() {
    State first = State({2, 3});
    State second = first;
    List<int> values = valuesOf(second);
    values.push(5);
    return first.values[2];
}
"""
    assert LLVMRunner().run(_typed(source), stdout=BytesIO(), stderr=BytesIO()) == 5
