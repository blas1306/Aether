from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import re

import pytest

from aether.ir import model as ir_model
from aether.ir.dto import (
    IR_INSTRUCTION_DTO_BY_TAG,
    IR_INSTRUCTION_DTO_REGISTRY,
    IR_INSTRUCTION_TAGS,
    IRInstructionDTORegistryEntry,
    ir_instruction_to_dto,
    validate_instruction_dto_registry,
)


EXPECTED_CLASS_TAGS: tuple[tuple[str, str], ...] = (
    ("IRConst", "const"),
    ("IRLoad", "load"),
    ("IRStore", "store"),
    ("IRInitDefault", "init_default"),
    ("IRCopyInit", "copy_init"),
    ("IRMoveInit", "move_init"),
    ("IRAssign", "assign"),
    ("IRDestroy", "destroy"),
    ("IRRelocate", "relocate"),
    ("IRBinaryOp", "binary_op"),
    ("IRUnaryOp", "unary_op"),
    ("IRCompareOp", "compare_op"),
    ("IRCast", "cast"),
    ("IRCall", "call"),
    ("IRInvoke", "invoke"),
    ("IRFunctionRef", "function_ref"),
    ("IRCallIndirect", "call_indirect"),
    ("IRInvokeIndirect", "invoke_indirect"),
    ("IRPrint", "print"),
    ("IRStructNew", "struct_new"),
    ("IRClassNew", "class_new"),
    ("IRClassGet", "class_get"),
    ("IRClassSet", "class_set"),
    ("IRInterfaceConstruct", "interface_construct"),
    ("IRInterfaceCall", "interface_call"),
    ("IRInvokeInterface", "invoke_interface"),
    ("IRStructGet", "struct_get"),
    ("IRStructSet", "struct_set"),
    ("IRMethodResultNew", "method_result_new"),
    ("IRMethodResultReceiver", "method_result_receiver"),
    ("IRMethodResultValue", "method_result_value"),
    ("IRArrayNew", "array_new"),
    ("IRListNew", "list_new"),
    ("IRArrayCopy", "array_copy"),
    ("IRListCopy", "list_copy"),
    ("IRListContains", "list_contains"),
    ("IRListIndexOf", "list_index_of"),
    ("IRListClear", "list_clear"),
    ("IRListPush", "list_push"),
    ("IRListInsert", "list_insert"),
    ("IRListRemoveAt", "list_remove_at"),
    ("IRListPop", "list_pop"),
    ("IRListReverse", "list_reverse"),
    ("IRSequenceSort", "sequence_sort"),
    ("IRArrayGet", "array_get"),
    ("IRArraySlice", "array_slice"),
    ("IRListSlice", "list_slice"),
    ("IRListGet", "list_get"),
    ("IRArraySet", "array_set"),
    ("IRListSet", "list_set"),
    ("IRArrayLength", "array_length"),
    ("IRListLength", "list_length"),
    ("IRListIsEmpty", "list_is_empty"),
    ("IRPackException", "exception_pack"),
    ("IRCatchEntry", "catch_entry"),
    ("IRExceptionMatch", "exception_match"),
    ("IRExceptionPayload", "exception_payload"),
    ("IRExceptionDestroy", "exception_destroy"),
    ("IRThrow", "throw"),
    ("IRRethrow", "rethrow"),
    ("IRPropagate", "propagate"),
    ("IRVectorNew", "vector_new"),
    ("IRMatrixNew", "matrix_new"),
    ("IRVectorAdd", "vector_add"),
    ("IRVectorSub", "vector_sub"),
    ("IRVectorScale", "vector_scale"),
    ("IRVectorDot", "vector_dot"),
    ("IROuterProduct", "outer_product"),
    ("IRMatrixAdd", "matrix_add"),
    ("IRMatrixSub", "matrix_sub"),
    ("IRMatrixScale", "matrix_scale"),
    ("IRMatrixMatMul", "matrix_mat_mul"),
    ("IRMatrixVectorMul", "matrix_vector_mul"),
    ("IRVectorMatrixMul", "vector_matrix_mul"),
    ("IRVectorGet", "vector_get"),
    ("IRMatrixGet", "matrix_get"),
    ("IRVectorLength", "vector_length"),
    ("IRMatrixRows", "matrix_rows"),
    ("IRMatrixColumns", "matrix_columns"),
    ("IRVectorSet", "vector_set"),
    ("IRMatrixSet", "matrix_set"),
    ("IRBranch", "branch"),
    ("IRJump", "jump"),
    ("IRReturn", "return"),
)

RUST_INSTRUCTION_SOURCE = (
    Path(__file__).parents[2]
    / "compiler-rs"
    / "crates"
    / "aether-ir"
    / "src"
    / "instruction.rs"
)


def _all_instruction_subclasses() -> set[type[ir_model.IRInstruction]]:
    pending = list(ir_model.IRInstruction.__subclasses__())
    found: set[type[ir_model.IRInstruction]] = set()
    while pending:
        instruction_type = pending.pop()
        if instruction_type not in found:
            if instruction_type.__module__ == ir_model.__name__:
                found.add(instruction_type)
            pending.extend(instruction_type.__subclasses__())
    return found


def _rust_instruction_variants(source: str) -> tuple[str, ...]:
    source_without_comments = re.sub(r"/\*.*?\*/", "", source, flags=re.DOTALL)
    source_without_comments = re.sub(r"//[^\n]*", "", source_without_comments)
    declaration = re.search(
        r"\bpub\s+enum\s+IRInstruction\s*\{",
        source_without_comments,
    )
    assert declaration is not None, "Rust IRInstruction enum declaration not found"

    opening_brace = source_without_comments.index("{", declaration.start())
    depth = 0
    closing_brace = None
    for index in range(opening_brace, len(source_without_comments)):
        if source_without_comments[index] == "{":
            depth += 1
        elif source_without_comments[index] == "}":
            depth -= 1
            if depth == 0:
                closing_brace = index
                break
    assert closing_brace is not None, "Rust IRInstruction enum is not closed"

    body = source_without_comments[opening_brace + 1 : closing_brace]
    variants: list[str] = []
    depth = 0
    for line in body.splitlines():
        if depth == 0:
            variant = re.match(r"\s*(IR[A-Za-z0-9_]+)\s*(?:\{|,)", line)
            if variant is not None:
                variants.append(variant.group(1))
        depth += line.count("{") - line.count("}")
    return tuple(variants)


def _expected_python_types() -> tuple[type[ir_model.IRInstruction], ...]:
    return tuple(getattr(ir_model, name) for name, _ in EXPECTED_CLASS_TAGS)


def test_registry_is_the_exact_stable_84_variant_contract() -> None:
    actual = tuple(
        (entry.instruction_type.__name__, entry.tag)
        for entry in IR_INSTRUCTION_DTO_REGISTRY
    )

    assert len(EXPECTED_CLASS_TAGS) == 84
    assert actual == EXPECTED_CLASS_TAGS
    assert tuple(entry.rust_variant for entry in IR_INSTRUCTION_DTO_REGISTRY) == tuple(
        name for name, _ in EXPECTED_CLASS_TAGS
    )


def test_registry_classes_and_tags_are_unique_and_bidirectional() -> None:
    instruction_types = tuple(
        entry.instruction_type for entry in IR_INSTRUCTION_DTO_REGISTRY
    )
    tags = tuple(entry.tag for entry in IR_INSTRUCTION_DTO_REGISTRY)

    assert len(instruction_types) == len(set(instruction_types)) == 84
    assert len(tags) == len(set(tags)) == 84
    assert set(IR_INSTRUCTION_TAGS.items()) == set(zip(instruction_types, tags))
    assert set(IR_INSTRUCTION_DTO_BY_TAG) == set(tags)
    assert all(
        IR_INSTRUCTION_DTO_BY_TAG[entry.tag] is entry
        for entry in IR_INSTRUCTION_DTO_REGISTRY
    )
    assert all(
        callable(entry.encoder) and callable(entry.decoder)
        for entry in IR_INSTRUCTION_DTO_REGISTRY
    )


def test_every_concrete_python_instruction_has_dto_support() -> None:
    model_types = _all_instruction_subclasses()
    expected_types = set(_expected_python_types())

    assert len(model_types) == 84
    assert model_types == expected_types
    validate_instruction_dto_registry(
        IR_INSTRUCTION_DTO_REGISTRY,
        python_instruction_types=model_types,
        expected_tags=(tag for _, tag in EXPECTED_CLASS_TAGS),
    )


def test_registry_is_synchronized_with_rust_instruction_enum() -> None:
    rust_variants = _rust_instruction_variants(
        RUST_INSTRUCTION_SOURCE.read_text(encoding="utf-8")
    )

    assert len(rust_variants) == 84
    validate_instruction_dto_registry(
        IR_INSTRUCTION_DTO_REGISTRY,
        rust_variants=rust_variants,
    )


def test_registry_validator_identifies_missing_and_duplicate_python_variants() -> None:
    with pytest.raises(
        ValueError,
        match=r"Python instruction variants missing DTO support: IRConst",
    ):
        validate_instruction_dto_registry(
            IR_INSTRUCTION_DTO_REGISTRY[1:],
            python_instruction_types=_expected_python_types(),
        )

    duplicate_tag_entry = replace(
        IR_INSTRUCTION_DTO_REGISTRY[1],
        tag=IR_INSTRUCTION_DTO_REGISTRY[0].tag,
    )
    registry_with_duplicate = (
        IR_INSTRUCTION_DTO_REGISTRY[0],
        duplicate_tag_entry,
        *IR_INSTRUCTION_DTO_REGISTRY[2:],
    )
    with pytest.raises(
        ValueError,
        match=r"duplicate stable DTO tags: 'const' \(IRConst, IRLoad\)",
    ):
        validate_instruction_dto_registry(registry_with_duplicate)

    duplicate_class_entry = replace(
        IR_INSTRUCTION_DTO_REGISTRY[1],
        instruction_type=IR_INSTRUCTION_DTO_REGISTRY[0].instruction_type,
    )
    with pytest.raises(
        ValueError,
        match=r"duplicate Python instruction classes: IRConst \(2 entries\)",
    ):
        validate_instruction_dto_registry(
            (
                IR_INSTRUCTION_DTO_REGISTRY[0],
                duplicate_class_entry,
                *IR_INSTRUCTION_DTO_REGISTRY[2:],
            )
        )


def test_registry_validator_identifies_rust_drift_and_name_mismatches() -> None:
    rust_variants = tuple(name for name, _ in EXPECTED_CLASS_TAGS)
    drifted_rust_variants = (*rust_variants[1:], "IRFuture")
    with pytest.raises(ValueError) as error:
        validate_instruction_dto_registry(
            IR_INSTRUCTION_DTO_REGISTRY,
            rust_variants=drifted_rust_variants,
        )
    assert "Rust variants missing in Python DTO: IRFuture" in str(error.value)
    assert "Python DTO variants missing in Rust: IRConst" in str(error.value)

    with pytest.raises(
        ValueError,
        match=r"duplicate Rust IRInstruction variants: IRConst",
    ):
        validate_instruction_dto_registry(
            IR_INSTRUCTION_DTO_REGISTRY,
            rust_variants=(*rust_variants, "IRConst"),
        )

    mismatched_entry: IRInstructionDTORegistryEntry = replace(
        IR_INSTRUCTION_DTO_REGISTRY[0],
        rust_variant="IRFuture",
    )
    with pytest.raises(
        ValueError,
        match=r"mismatched Python/Rust variant names: IRConst -> IRFuture",
    ):
        validate_instruction_dto_registry(
            (mismatched_entry, *IR_INSTRUCTION_DTO_REGISTRY[1:])
        )


def test_unsupported_instruction_subclass_still_fails_explicitly() -> None:
    class IRFuture(ir_model.IRInstruction):
        pass

    with pytest.raises(
        TypeError,
        match=r"Unsupported IR instruction for schema v1: IRFuture",
    ):
        ir_instruction_to_dto(IRFuture())
