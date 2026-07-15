from __future__ import annotations

import pytest

from aether.backend.llvm import print_llvm
from aether.ir import IRListIndexOf, IRListLength
from aether.ir.optimizer import OptimizerPipeline
from aether.list_safety import (
    ALLOCATION_FAILURE_MESSAGE,
    ALLOCATION_OVERFLOW_MESSAGE,
    INT32_MAX,
    LIST_INDEX_OVERFLOW_MESSAGE,
    LIST_LENGTH_OVERFLOW_MESSAGE,
    UINT64_MAX,
    checked_allocation,
    checked_i64_multiply,
    checked_list_index_to_int,
    checked_list_length_to_int,
)
from aether.pipeline import lower_to_verified_ssa, prepare_typed_program
from aether.ir import IRLowerer
from aether.ssa import SSAListIndexOf, SSAListLength
from aether.ssa.optimizer import SSAOptimizerPipeline
from aether.typechecker import TypeChecker


def _typed(source: str):
    return prepare_typed_program(source, TypeChecker())


def _instructions(module):
    return [
        instruction
        for function in module.functions
        for block in function.blocks
        for instruction in block.instructions
    ]


def test_checked_i64_multiply_accepts_valid_sizes_and_rejects_wraparound() -> None:
    assert checked_i64_multiply(3, 8) == 24
    assert checked_i64_multiply(UINT64_MAX, 1) == UINT64_MAX

    with pytest.raises(OverflowError, match=ALLOCATION_OVERFLOW_MESSAGE):
        checked_i64_multiply(UINT64_MAX, 2)
    with pytest.raises(OverflowError, match=ALLOCATION_OVERFLOW_MESSAGE):
        checked_i64_multiply(-1, 8)


def test_checked_allocation_reports_mocked_failure_without_oom() -> None:
    calls: list[int] = []

    def fail(size: int):
        calls.append(size)
        return None

    with pytest.raises(MemoryError, match=ALLOCATION_FAILURE_MESSAGE):
        checked_allocation(64, fail)

    assert calls == [64]
    assert checked_allocation(0, fail) is None
    assert calls == [64]


def test_checked_list_int_conversions_cover_boundaries_and_sentinel() -> None:
    assert checked_list_length_to_int(0) == 0
    assert checked_list_length_to_int(INT32_MAX) == INT32_MAX
    assert checked_list_index_to_int(-1) == -1
    assert checked_list_index_to_int(INT32_MAX) == INT32_MAX

    with pytest.raises(OverflowError, match=LIST_LENGTH_OVERFLOW_MESSAGE):
        checked_list_length_to_int(INT32_MAX + 1)
    with pytest.raises(OverflowError, match=LIST_INDEX_OVERFLOW_MESSAGE):
        checked_list_index_to_int(INT32_MAX + 1)


def test_list_new_and_copy_check_bytes_before_allocation_and_memcpy() -> None:
    llvm = print_llvm(
        lower_to_verified_ssa(
            _typed("int main(){ List<int> xs={1,2,3}; List<int> ys=xs.copy(); return ys.length; }")
        )
    )

    new_start = llvm.index("define private ptr @aether_list_new")
    new_end = llvm.index("\n}", new_start)
    new_helper = llvm.index("call i64 @aether_checked_allocation_bytes", new_start, new_end)
    new_header = llvm.index(
        "call ptr @aether_alloc(i64 ptrtoint (ptr getelementptr (%AetherList",
        new_start,
        new_end,
    )
    new_data = llvm.index("call ptr @aether_alloc(i64 %data_size)", new_start, new_end)
    assert new_helper < new_header < new_data

    copy_start = llvm.index("define private ptr @aether_list_copy")
    copy_end = llvm.index("\n}", copy_start)
    copy_helper = llvm.index("call i64 @aether_checked_allocation_bytes", copy_start, copy_end)
    copy_allocation = llvm.index("call ptr @aether_list_new", copy_start, copy_end)
    copy_memcpy = llvm.index("call void @llvm.memcpy", copy_start, copy_end)
    assert copy_helper < copy_allocation < copy_memcpy
    assert "br i1 %has_bytes, label %copy_elements, label %done" in llvm[copy_start:copy_end]


def test_sort_checks_total_and_run_bytes_and_avoids_wrapping_offsets() -> None:
    llvm = print_llvm(
        lower_to_verified_ssa(
            _typed("int main(){ List<int> xs={3,1,2}; xs.sort(); return xs[0]; }")
        )
    )
    start = llvm.index("define private void @aether_sort_i32")
    end = llvm.index("\n}", start)
    helper = llvm[start:end]

    assert helper.index("call i64 @aether_checked_allocation_bytes") < helper.index(
        "call ptr @aether_alloc(i64 %bytes)"
    )
    assert "call i64 @aether_checked_mul_i64(i64 %run_length, i64 4)" in helper
    assert "%mid_raw = add" not in helper
    assert "%right_raw = add" not in helper
    assert "shl i64 %width" not in helper
    assert "br i1 %can_double, label %double_width, label %clamp_width" in helper


def test_length_and_index_of_emit_checked_i64_to_i32_conversions() -> None:
    llvm = print_llvm(
        lower_to_verified_ssa(
            _typed("int main(){ List<int> xs={4,5}; return xs.length+xs.indexOf(5); }")
        )
    )

    assert "define private i32 @aether_list_length_to_int" in llvm
    assert "call i32 @aether_list_length_to_int" in llvm
    assert "Aether panic: List length does not fit in int" in llvm
    assert "define private i64 @aether_list_search_int" in llvm
    assert "define private i32 @aether_list_index_of_int" in llvm
    assert "call i32 @aether_list_index_to_int" in llvm
    assert "Aether panic: List index does not fit in int" in llvm


def test_contains_uses_i64_search_without_checked_index_conversion() -> None:
    llvm = print_llvm(
        lower_to_verified_ssa(
            _typed("int main(){ List<int> xs={1,2}; if(xs.contains(2)){return 1;} return 0; }")
        )
    )

    assert "define private i64 @aether_list_search_int" in llvm
    assert "call i64 @aether_list_search_int" in llvm
    assert "@aether_list_index_to_int" not in llvm
    assert "icmp sge i64 %index, 0" in llvm


def test_dce_preserves_unused_length_and_index_of_because_they_may_trap() -> None:
    source = "int main(){ List<int> xs={1,2}; int n=xs.length; int i=xs.indexOf(2); return 0; }"
    typed = _typed(source)
    optimized_ir = OptimizerPipeline().run(IRLowerer().lower(typed.program))
    optimized_ssa = SSAOptimizerPipeline().run(lower_to_verified_ssa(typed))

    assert any(isinstance(item, IRListLength) for item in _instructions(optimized_ir))
    assert any(isinstance(item, IRListIndexOf) for item in _instructions(optimized_ir))
    assert any(isinstance(item, SSAListLength) for item in _instructions(optimized_ssa))
    assert any(isinstance(item, SSAListIndexOf) for item in _instructions(optimized_ssa))
