from __future__ import annotations

import inspect

from aether.backend.llvm.array_runtime import LLVMArrayRuntime
from aether.backend.llvm.list_runtime import LLVMListRuntime
from aether.backend.llvm.matrix_runtime import LLVMMatrixRuntime
from aether.backend.llvm.printer import LLVMPrinter, print_llvm
from aether.backend.llvm.runtime_common import LLVMRuntimeCommon
from aether.backend.llvm.vector_runtime import LLVMVectorRuntime
from aether.pipeline import lower_to_verified_ssa, prepare_typed_program
from aether.typechecker import TypeChecker


def _emit(source: str) -> str:
    typed = prepare_typed_program(source, TypeChecker())
    return print_llvm(lower_to_verified_ssa(typed))


def test_array_runtime_owns_array_layout_helpers() -> None:
    source = inspect.getsource(LLVMArrayRuntime)

    assert 'STRUCT_TYPE = "%AetherArray"' in source
    assert "aether_array_new" in source
    assert "aether_array_check_index" in source
    assert "aether_array_length_to_int" in source
    assert "Array index out of bounds" in source
    assert "Array length does not fit in int" in source


def test_list_runtime_does_not_define_array_helpers() -> None:
    source = inspect.getsource(LLVMListRuntime)

    assert "define private ptr @aether_array_new" not in source
    assert "define private void @aether_array_check_index" not in source
    assert "Aether panic: Array" not in source


def test_common_runtime_owns_shared_allocation_and_sort_helpers() -> None:
    source = inspect.getsource(LLVMRuntimeCommon)

    assert "aether_checked_mul_i64" in source
    assert "aether_checked_allocation_bytes" in source
    assert "aether_alloc" in source
    assert "sequence_sort_helper" in source


def test_vector_and_matrix_runtimes_own_their_semantic_helpers() -> None:
    vector_source = inspect.getsource(LLVMVectorRuntime)
    matrix_source = inspect.getsource(LLVMMatrixRuntime)

    assert "aether_vector_check_index" in vector_source
    assert "Vector index out of bounds" not in inspect.getsource(LLVMArrayRuntime)
    assert "aether_matrix_check_index" in matrix_source
    assert "row_valid" in matrix_source
    assert "column_valid" in matrix_source


def test_printer_delegates_runtime_generation() -> None:
    source = inspect.getsource(LLVMPrinter.print_module)

    assert "LLVMArrayRuntime(" in source
    assert "LLVMListRuntime(" in source
    assert "LLVMVectorRuntime(" in source
    assert "LLVMMatrixRuntime(" in source
    assert "LLVMRuntimeCommon(" in source


def test_mixed_array_and_list_module_keeps_layouts_and_unique_declarations() -> None:
    llvm = _emit(
        """
int main() {
    Array<int> array = {3, 1, 2};
    List<int> list = {6, 4, 5};
    array.sort();
    list.sort();
    return array[0] + list[0] + array.length + list.length;
}
"""
    )

    assert llvm.count("%AetherArray = type { i64, ptr, i64 }") == 1
    assert llvm.count("%AetherList = type { i64, i64, ptr, i64 }") == 1
    assert llvm.count("declare noalias ptr @malloc(i64)") == 1
    assert llvm.count("declare void @free(ptr)") == 1
    assert llvm.count("declare void @llvm.memcpy.p0.p0.i64") == 1
    assert llvm.count("declare void @exit(i32) noreturn") == 1
    assert llvm.count("define private void @aether_sort_i32") == 1
