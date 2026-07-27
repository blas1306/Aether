from __future__ import annotations

from pathlib import Path
import shutil
import subprocess

import pytest

from aether.backend.llvm import LLVMBackend
from aether.backend.llvm.layout import LLVMTypeLayouts
from aether.class_value import (
    NativeClassObject,
    class_debug_counters,
    reset_class_debug_counters,
)
from aether.ir import (
    ArrayType,
    BoolType,
    ClassRefType,
    IRAssign,
    IRArrayNew,
    IRBasicBlock,
    IRBranch,
    IRCall,
    IRClassNew,
    IRCompareOp,
    IRConst,
    IRCopyInit,
    IRCast,
    IRDestroy,
    IRFunction,
    IRInitDefault,
    IRInterpreter,
    IRJump,
    IRListNew,
    IRLoad,
    IRModule,
    IRParameter,
    IRReturn,
    IRStorage,
    IRStructDefinition,
    IRStructNew,
    IRValue,
    IRVerificationError,
    IRVerifier,
    IntType,
    LifecycleTypeRegistry,
    ListType,
    NullableType,
    StructType,
    VoidType,
)
from aether.ir.dto import ir_module_from_dto, ir_module_to_dto
from aether.ir.lifecycle import expand_lifecycle
from aether.ir.optimizer import build_optimizer_pipeline
from aether.ssa import GeneralSSABuilder, SSAClassNew, SSACompareOp, SSAPhi
from aether.ssa.optimizer import SSAOptimizerPipeline


CLASS = ClassRefType("pkg.Widget")


def _verified(instructions: list[object], return_type=IntType()) -> IRModule:
    module = IRModule(
        [
            IRFunction(
                "main",
                [],
                return_type,
                [IRBasicBlock("entry", instructions)],
            )
        ]
    )
    return IRVerifier(module).verify()


def test_class_reference_layout_is_nominal_nontrivial_and_has_no_default() -> None:
    other = ClassRefType("pkg.Other")
    assert CLASS != other

    layout = LLVMTypeLayouts([]).layout(CLASS)
    traits = LifecycleTypeRegistry([]).traits(CLASS)
    assert layout.llvm_type == "ptr" and layout.sized
    assert not layout.trivially_copyable
    assert layout.trivially_relocatable
    assert layout.needs_destroy and layout.needs_retain
    assert layout.contains_references and layout.supported_as_collection_element
    assert not traits.trivially_copyable
    assert traits.trivially_relocatable and traits.needs_destroy
    assert not traits.supports_default

    slot = IRStorage("object", CLASS)
    with pytest.raises(IRVerificationError, match="no valid default value"):
        _verified([IRInitDefault(slot), IRReturn()], VoidType())


def test_class_allocation_requires_class_result() -> None:
    invalid = IRValue("object", IntType())
    with pytest.raises(
        IRVerificationError,
        match="Class new result must be class reference type",
    ):
        _verified([IRClassNew(invalid), IRReturn(invalid)])


def test_unused_class_allocation_is_preserved_as_an_effect() -> None:
    allocated = IRValue("allocated", CLASS)
    zero = IRValue("zero", IntType())
    module = _verified(
        [
            IRClassNew(allocated),
            IRConst(zero, 0),
            IRReturn(zero),
        ]
    )

    optimized_ir = build_optimizer_pipeline("O2").run(module)
    assert any(
        isinstance(instruction, IRClassNew)
        for instruction in optimized_ir.functions[0].blocks[0].instructions
    )
    optimized_ssa = SSAOptimizerPipeline().run(
        GeneralSSABuilder().build(module)
    )
    assert any(
        isinstance(instruction, SSAClassNew)
        for instruction in optimized_ssa.functions[0].blocks[0].instructions
    )


def test_class_dto_ssa_and_identity_comparison() -> None:
    first = IRValue("first", CLASS)
    second = IRValue("second", CLASS)
    same = IRValue("same", BoolType())
    module = IRModule(
        [
            IRFunction(
                "same",
                [],
                BoolType(),
                [
                    IRBasicBlock(
                        "entry",
                        [
                            IRClassNew(first),
                            IRClassNew(second),
                            IRCompareOp(same, "ne", first, second),
                            IRReturn(same),
                        ],
                    )
                ],
            )
        ]
    )
    assert ir_module_from_dto(ir_module_to_dto(module)) == module
    IRVerifier(module).verify()
    ssa = GeneralSSABuilder().build(module)
    instructions = ssa.functions[0].blocks[0].instructions
    assert sum(isinstance(item, SSAClassNew) for item in instructions) == 2
    assert any(isinstance(item, SSACompareOp) for item in instructions)

    expanded = expand_lifecycle(module)
    expanded_instructions = expanded.functions[0].blocks[0].instructions
    assert sum(
        isinstance(item, IRCall) and item.function == "__aether_release"
        for item in expanded_instructions
    ) == 2
    llvm = LLVMBackend().emit(GeneralSSABuilder().build(expanded))
    assert "icmp ne ptr" in llvm


def test_interpreter_alias_assignment_self_assignment_and_exact_destruction() -> None:
    reset_class_debug_counters()
    allocated = IRValue("allocated", CLASS)
    slot = IRStorage("slot", CLASS)
    alias = IRStorage("alias", CLASS)
    loaded = IRValue("loaded", CLASS)
    module = _verified(
        [
            IRClassNew(allocated),
            IRCopyInit(slot, allocated),
            IRAssign(slot, slot),
            IRCopyInit(alias, slot),
            IRLoad(loaded, alias),
            IRDestroy(alias),
            IRDestroy(slot),
            IRConst(IRValue("zero", IntType()), 0),
            IRReturn(IRValue("zero", IntType())),
        ]
    )

    assert IRInterpreter(expand_lifecycle(module)).call("main") == 0
    counters = class_debug_counters()
    assert counters.objects_allocated == counters.objects_freed == 1

    value = NativeClassObject(CLASS.name)
    assert value.retain() is value and value.strong_count == 2
    value.release()
    assert value.alive and value.strong_count == 1
    value.release()
    assert not value.alive
    with pytest.raises(RuntimeError, match="already released"):
        value.release()


def test_borrowed_parameter_and_owned_return_preserve_one_object_identity() -> None:
    reset_class_debug_counters()
    borrowed = IRParameter("borrowed", CLASS)
    return_slot = IRStorage("return_slot", CLASS)
    returned = IRValue("returned", CLASS)
    identity = IRFunction(
        "identity",
        [borrowed],
        CLASS,
        [
            IRBasicBlock(
                "entry",
                [
                    IRCopyInit(return_slot, borrowed),
                    IRLoad(returned, return_slot),
                    IRReturn(returned, return_slot),
                ],
            )
        ],
    )

    allocated = IRValue("allocated", CLASS)
    call_result = IRValue("call_result", CLASS)
    owner = IRStorage("owner", CLASS)
    zero = IRValue("zero", IntType())
    main = IRFunction(
        "main",
        [],
        IntType(),
        [
            IRBasicBlock(
                "entry",
                [
                    IRClassNew(allocated),
                    IRCall("identity", (allocated,), call_result),
                    IRCopyInit(owner, call_result),
                    IRDestroy(owner),
                    IRConst(zero, 0),
                    IRReturn(zero),
                ],
            )
        ],
    )
    module = IRVerifier(IRModule([identity, main])).verify()
    expanded = expand_lifecycle(module)

    assert IRInterpreter(expanded).call("main") == 0
    counters = class_debug_counters()
    assert counters.objects_allocated == counters.objects_freed == 1
    llvm = LLVMBackend().emit(GeneralSSABuilder().build(expanded))
    assert "define ptr @identity(ptr %borrowed)" in llvm
    assert "call ptr @identity(ptr" in llvm


def test_reassignment_releases_replaced_owner_and_keeps_self_assignment_safe() -> None:
    reset_class_debug_counters()
    first = IRValue("first", CLASS)
    second = IRValue("second", CLASS)
    slot = IRStorage("slot", CLASS)
    zero = IRValue("zero", IntType())
    module = _verified(
        [
            IRClassNew(first),
            IRClassNew(second),
            IRCopyInit(slot, first),
            IRAssign(slot, second),
            IRAssign(slot, slot),
            IRDestroy(slot),
            IRConst(zero, 0),
            IRReturn(zero),
        ]
    )

    assert IRInterpreter(expand_lifecycle(module)).call("main") == 0
    counters = class_debug_counters()
    assert counters.objects_allocated == counters.objects_freed == 2


def test_nullable_class_equality_delegates_to_object_identity() -> None:
    reset_class_debug_counters()
    nullable_class = NullableType(CLASS)
    first = IRValue("first", CLASS)
    second = IRValue("second", CLASS)
    maybe_first = IRValue("maybe_first", nullable_class)
    maybe_second = IRValue("maybe_second", nullable_class)
    different = IRValue("different", BoolType())
    module = _verified(
        [
            IRClassNew(first),
            IRClassNew(second),
            IRCast(maybe_first, first),
            IRCast(maybe_second, second),
            IRCompareOp(different, "ne", maybe_first, maybe_second),
            IRReturn(different),
        ],
        BoolType(),
    )
    expanded = expand_lifecycle(module)

    assert IRInterpreter(expanded).call("main") is True
    counters = class_debug_counters()
    assert counters.objects_allocated == counters.objects_freed == 2
    llvm = LLVMBackend().emit(GeneralSSABuilder().build(expanded))
    assert "icmp eq ptr %left.payload, %right.payload" in llvm


def test_cfg_branch_ownership_merges_through_an_ssa_phi() -> None:
    reset_class_debug_counters()
    condition = IRParameter("condition", BoolType())
    selected = IRStorage("selected", CLASS)
    then_object = IRValue("then_object", CLASS)
    else_object = IRValue("else_object", CLASS)
    loaded = IRValue("loaded", CLASS)
    same = IRValue("same", BoolType())
    function = IRFunction(
        "choose",
        [condition],
        BoolType(),
        [
            IRBasicBlock("entry", [IRBranch(condition, "then", "else")]),
            IRBasicBlock(
                "then",
                [
                    IRClassNew(then_object),
                    IRCopyInit(selected, then_object),
                    IRJump("merge"),
                ],
            ),
            IRBasicBlock(
                "else",
                [
                    IRClassNew(else_object),
                    IRCopyInit(selected, else_object),
                    IRJump("merge"),
                ],
            ),
            IRBasicBlock(
                "merge",
                [
                    IRLoad(loaded, selected),
                    IRCompareOp(same, "eq", loaded, loaded),
                    IRDestroy(selected),
                    IRReturn(same),
                ],
            ),
        ],
    )
    module = IRVerifier(IRModule([function])).verify()
    expanded = expand_lifecycle(module)

    interpreter = IRInterpreter(expanded)
    assert interpreter.call("choose", [True]) is True
    assert interpreter.call("choose", [False]) is True
    counters = class_debug_counters()
    assert counters.objects_allocated == counters.objects_freed == 2
    ssa = GeneralSSABuilder().build(expanded)
    assert any(
        isinstance(instruction, SSAPhi)
        and isinstance(instruction.result.type, ClassRefType)
        for block in ssa.functions[0].blocks
        for instruction in block.instructions
    )


def test_class_references_are_supported_in_structs_arrays_and_nullable() -> None:
    holder = IRStructDefinition("Holder", (("value", CLASS),))
    layouts = LLVMTypeLayouts([holder])
    for type_ in (
        StructType("Holder"),
        ArrayType(CLASS),
        ListType(CLASS),
        NullableType(CLASS),
    ):
        layout = layouts.layout(type_)
        assert layout.sized and layout.needs_destroy and layout.needs_retain
        assert layout.supported_as_collection_element

    object_ = IRValue("object", CLASS)
    array_object = IRValue("array_object", CLASS)
    aggregate = IRValue("holder", StructType("Holder"))
    array = IRValue("array", ArrayType(CLASS))
    list_object = IRValue("list_object", CLASS)
    list_value = IRValue("list", ListType(CLASS))
    module = IRModule(
        [
            IRFunction(
                "build",
                [],
                IntType(),
                [
                    IRBasicBlock(
                        "entry",
                        [
                            IRClassNew(object_),
                            IRStructNew(aggregate, (object_,)),
                            IRClassNew(array_object),
                            IRArrayNew(array, (array_object,)),
                            IRClassNew(list_object),
                            IRListNew(list_value, (list_object,)),
                            IRConst(IRValue("zero", IntType()), 0),
                            IRReturn(IRValue("zero", IntType())),
                        ],
                    )
                ],
            )
        ],
        [holder],
    )
    assert IRVerifier(module).verify() is module


def test_nested_class_identity_helpers_have_complete_llvm_runtime(
    tmp_path: Path,
) -> None:
    if shutil.which("clang") is None:
        pytest.skip("clang is unavailable")

    basket = IRStructDefinition("Basket", (("items", ArrayType(CLASS)),))
    basket_type = StructType("Basket")
    left = IRParameter("left", basket_type)
    right = IRParameter("right", basket_type)
    same = IRValue("same", BoolType())
    module = IRModule(
        [
            IRFunction(
                "same_basket",
                [left, right],
                BoolType(),
                [
                    IRBasicBlock(
                        "entry",
                        [
                            IRCompareOp(same, "eq", left, right),
                            IRReturn(same),
                        ],
                    )
                ],
            )
        ],
        [basket],
    )
    IRVerifier(module).verify()
    llvm = LLVMBackend().emit(GeneralSSABuilder().build(module))
    assert "icmp eq ptr %left.value, %right.value" in llvm
    assert "declare void @free(ptr)" in llvm
    assert "@__ae_class_descriptor_" in llvm

    llvm_path = tmp_path / "nested-class.ll"
    object_path = tmp_path / "nested-class.o"
    llvm_path.write_text(llvm, encoding="utf-8")
    compiled = subprocess.run(
        [
            shutil.which("clang") or "clang",
            "-x",
            "ir",
            "-c",
            str(llvm_path),
            "-o",
            str(object_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert compiled.returncode == 0, compiled.stderr


@pytest.mark.parametrize("profile", ["O0", "O1", "O2"])
def test_class_arc_survives_optimizers_and_real_clang(
    profile: str,
    tmp_path: Path,
) -> None:
    if shutil.which("clang") is None:
        pytest.skip("clang is unavailable")

    allocated = IRValue("allocated", CLASS)
    owner = IRStorage("owner", CLASS)
    alias = IRStorage("alias", CLASS)
    zero = IRValue("zero", IntType())
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
                            IRClassNew(allocated),
                            IRCopyInit(owner, allocated),
                            IRCopyInit(alias, owner),
                            IRAssign(alias, alias),
                            IRDestroy(alias),
                            IRDestroy(owner),
                            IRConst(zero, 0),
                            IRReturn(zero),
                        ],
                    )
                ],
            )
        ]
    )
    IRVerifier(module).verify()
    optimized_ir = IRVerifier(build_optimizer_pipeline(profile).run(module)).verify()
    ssa = GeneralSSABuilder().build(optimized_ir)
    optimized_ssa = SSAOptimizerPipeline(verify_after_each=True).run(ssa)
    llvm = LLVMBackend().emit(optimized_ssa)

    assert "%AetherObjectHeader = type { ptr, i64, i32, i32 }" in llvm
    assert "call void @aether_class_retain" in llvm
    assert "call void @aether_class_release" in llvm
    assert "call void @free(ptr %object)" in llvm
    llvm_path = tmp_path / f"class-{profile}.ll"
    executable = tmp_path / f"class-{profile}"
    llvm_path.write_text(llvm, encoding="utf-8")
    compiled = subprocess.run(
        [shutil.which("clang") or "clang", f"-{profile}", str(llvm_path), "-o", str(executable)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert compiled.returncode == 0, compiled.stderr
    executed = subprocess.run([str(executable)], check=False)
    assert executed.returncode == 0
