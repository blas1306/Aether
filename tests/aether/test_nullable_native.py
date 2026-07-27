from __future__ import annotations

from io import StringIO
import re
import shutil
import subprocess

import pytest

from aether import ast
from aether.backend.llvm import LLVMBackend, LLVMRunner, print_llvm
from aether.backend.llvm.layout import LLVMTypeLayouts
from aether.errors import AetherSyntaxError, AetherTypeError
from aether.ir import (
    IRCast,
    IRConst,
    IRInterpreter,
    IRModule,
    IRVerificationError,
    IRVerifier,
    IntType,
    LifecycleTypeRegistry,
    NullableType,
    StringType,
)
from aether.ir.dto import ir_module_from_dto, ir_module_to_dto
from aether.ir.optimizer import OptimizerPipeline, build_optimizer_pipeline
from aether.pipeline import (
    IRBackend,
    lower_to_verified_ssa,
    parse_source,
    prepare_typed_program,
)
from aether.runner import run_aether
from aether.ssa import GeneralSSABuilder, SSAPhi, SSAVerifier
from aether.ssa.optimizer import SSAOptimizerPipeline
from aether.typechecker import TypeChecker
from aether.types import (
    AetherValue,
    NullableType as SourceNullableType,
    NullableValue,
)


SOURCE = """
int? choose(boolean present, int value) {
    int? result = null;
    if (present) {
        result = value;
    }
    return result;
}

int main() {
    int? first = choose(false, 7);
    int? second = choose(true, 9);
    println(first);
    println(first == null);
    println(second);
    println(second != null);
    return 0;
}
"""


def _typed(source: str = SOURCE):
    return prepare_typed_program(source, TypeChecker())


def _all_ir_instructions(module: IRModule):
    return (
        instruction
        for function in module.functions
        for block in function.blocks
        for instruction in block.instructions
    )


def test_parser_preserves_nullable_declarations_parameters_and_returns() -> None:
    program = parse_source(
        "string? identity(string? value) { string? local = value; return local; }"
    )
    function = program.statements[0]

    assert isinstance(function, ast.FunctionDeclaration)
    assert function.return_type == SourceNullableType("string")
    assert function.parameters[0].type_name == SourceNullableType("string")
    assert isinstance(function.body[0], ast.VarDeclaration)
    assert function.body[0].type_name == SourceNullableType("string")

    with pytest.raises(AetherSyntaxError):
        parse_source("int?? value = null;")
    with pytest.raises(AetherSyntaxError):
        parse_source("void? value = null;")


def test_typechecker_nullable_conversions_and_sound_diagnostic() -> None:
    _typed(
        """
double? widen(int value) { return value; }
int? echo(int? value) { return value; }
int main() {
    int? local = 4;
    local = null;
    println(echo(local));
    println(widen(3));
    return 0;
}
"""
    )

    with pytest.raises(
        AetherTypeError,
        match=r"Cannot implicitly convert 'int\?' to 'int'",
    ):
        _typed(
            """
int main() {
    int? maybe = 1;
    if (maybe != null) {
        int invalid = maybe;
    }
    return 0;
}
"""
        )


def test_ast_nullable_values_use_an_explicit_tagged_representation() -> None:
    nullable_int = SourceNullableType("int")
    absent = AetherValue(nullable_int, None)
    present = AetherValue(nullable_int, 7)

    assert absent.value == NullableValue(False)
    assert present.value == NullableValue(True, 7)
    assert run_aether("int? x = null; println(x); x = 7; println(x);").output == (
        "null\n7\n"
    )


def test_ir_nullable_constants_casts_round_trip_and_execute() -> None:
    module = IRBackend().lower_verified(_typed())
    instructions = tuple(_all_ir_instructions(module))

    assert any(
        isinstance(instruction, IRConst)
        and isinstance(instruction.result.type, NullableType)
        and instruction.value is None
        for instruction in instructions
    )
    assert any(
        isinstance(instruction, IRCast)
        and isinstance(instruction.result.type, NullableType)
        for instruction in instructions
    )
    dto = ir_module_to_dto(module)
    assert {"tag": "null"} in [
        instruction["value"]
        for function in dto["functions"]
        for block in function["blocks"]
        for instruction in block["instructions"]
        if instruction["kind"] == "const"
    ]
    assert IRVerifier(ir_module_from_dto(dto)).verify()

    interpreter = IRInterpreter(module)
    assert interpreter.call("main") == 0
    assert interpreter.output == "null\ntrue\n9\ntrue\n"


def test_ir_rejects_untyped_null_and_lifecycle_inherits_payload_traits() -> None:
    from aether.ir import IRBasicBlock, IRFunction, IRReturn, IRValue

    result = IRValue("value", IntType())
    invalid = IRModule(
        [
            IRFunction(
                "main",
                [],
                IntType(),
                [IRBasicBlock("entry", [IRConst(result, None), IRReturn(result)])],
            )
        ]
    )
    with pytest.raises(IRVerificationError, match="Null const requires nullable result type"):
        IRVerifier(invalid).verify()

    registry = LifecycleTypeRegistry([])
    nullable_int = registry.traits(NullableType(IntType()))
    nullable_string = registry.traits(NullableType(StringType()))
    assert nullable_int.trivially_copyable
    assert nullable_int.supports_default
    assert not nullable_int.needs_destroy
    assert not nullable_string.trivially_copyable
    assert nullable_string.supports_default
    assert nullable_string.needs_destroy


def test_ssa_renaming_phi_verification_and_optimizers_preserve_nullable() -> None:
    ir_module = IRBackend().lower_verified(_typed())
    optimized_ir = OptimizerPipeline(iterative=True).run(ir_module)
    ssa_module = lower_to_verified_ssa(optimized_ir)

    assert any(
        isinstance(instruction, SSAPhi)
        and isinstance(instruction.result.type, NullableType)
        for function in ssa_module.functions
        for block in function.blocks
        for instruction in block.instructions
    )
    optimized = SSAOptimizerPipeline(iterative=True).run(ssa_module)
    assert SSAVerifier(optimized).verify() is optimized


def test_llvm_uses_named_tagged_aggregate_and_preserves_function_abi() -> None:
    nullable_int = NullableType(IntType())
    layout = LLVMTypeLayouts([]).layout(nullable_int)
    assert layout.llvm_type.startswith("%nullable.int.")
    assert layout.sized
    assert layout.trivially_copyable
    assert not layout.needs_destroy
    assert layout.size_operand == (
        f"ptrtoint (ptr getelementptr ({layout.llvm_type}, ptr null, i64 1) to i64)"
    )

    llvm = print_llvm(lower_to_verified_ssa(_typed()))
    nullable_name = re.search(r"(%nullable\.int\.[0-9a-f]+) = type \{ i1, i32 \}", llvm)
    assert nullable_name is not None
    aggregate = re.escape(nullable_name.group(1))
    assert re.search(rf"define {aggregate} @choose\(i1 [^,]+, i32 [^)]+\)", llvm)
    assert "zeroinitializer" in llvm
    assert "inttoptr" not in llvm


@pytest.mark.skipif(shutil.which("clang") is None, reason="clang is required")
def test_native_nullable_end_to_end_struct_string_and_collection_values() -> None:
    source = """
struct Label {
    int id;
    string text;
}

Label? label(boolean present) {
    if (present) {
        return Label(4, "four");
    }
    return null;
}

string? text(boolean present) {
    if (present) {
        return "hello";
    }
    return null;
}

int main() {
    Label? a = label(true);
    Label? b = label(false);
    List<int?> values = {null, 2, null};
    println(a);
    println(b);
    println(a == Label(4, "four"));
    println(b == null);
    println(text(true));
    println(text(false));
    println(values);
    println(values[0] == null);
    println(values[1] == 2);
    return 0;
}
"""
    expected = (
        "Label(id=4, text=four)\n"
        "null\n"
        "true\n"
        "true\n"
        "hello\n"
        "null\n"
        "{null, 2, null}\n"
        "true\n"
        "true\n"
    )
    assert run_aether(source).output == expected

    stdout = StringIO()
    stderr = StringIO()
    assert LLVMRunner().run(_typed(source), stdout=stdout, stderr=stderr) == 0
    assert stdout.getvalue() == expected
    assert stderr.getvalue() == ""


@pytest.mark.skipif(shutil.which("clang") is None, reason="clang is required")
@pytest.mark.parametrize("profile", ["O0", "O1", "O2"])
def test_nullable_survives_optimizer_profiles_and_real_clang(
    profile: str, tmp_path
) -> None:
    source = """
string? choose(boolean present) {
    if (present) { return "kept"; }
    return null;
}
int main() {
    string? value = choose(true);
    println(value);
    println(value != null);
    value = null;
    println(value);
    return 0;
}
"""
    ir = IRBackend().lower_verified(_typed(source))
    optimized_ir = IRVerifier(build_optimizer_pipeline(profile).run(ir)).verify()
    ssa = GeneralSSABuilder().build(optimized_ir)
    optimized_ssa = SSAOptimizerPipeline(verify_after_each=True).run(ssa)
    llvm = LLVMBackend().emit(optimized_ssa)
    llvm_path = tmp_path / f"nullable-{profile}.ll"
    executable = tmp_path / f"nullable-{profile}"
    llvm_path.write_text(llvm, encoding="utf-8")
    compiled = subprocess.run(
        [shutil.which("clang") or "clang", str(llvm_path), "-o", str(executable)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert compiled.returncode == 0, compiled.stderr
    completed = subprocess.run(
        [str(executable)], check=False, capture_output=True, text=True
    )
    assert completed.returncode == 0
    assert completed.stdout == "kept\ntrue\nnull\n"
