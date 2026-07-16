from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from io import StringIO
from pathlib import Path
import shutil
import subprocess

import pytest

from aether.backend.llvm import LLVMBackend, LLVMBuilder, LLVMRunner
from aether.capabilities import Capability, detect_required_capabilities
from aether.errors import AetherTypeError
from aether.ir import IRCall, IRVerificationError, IRVerifier, StringType
from aether.ir.optimizer import build_optimizer_pipeline
from aether.pipeline import IRBackend, prepare_typed_program
from aether.runner import run_aether
from aether.ssa import GeneralSSABuilder, SSACall, SSAVerificationError, SSAVerifier
from aether.ssa.optimizer import SSAOptimizerPipeline
from aether.stdlib.registry import builtin_names
from aether.string_value import (
    ASCII_WHITESPACE_BYTES,
    EMPTY_STRING,
    STRING_TRIM_BUILTIN,
    StringValue,
    aether_string_trim,
)
from aether.typechecker import TypeChecker


def _typed(source: str, *, source_root: Path | None = None):
    return prepare_typed_program(source, TypeChecker(source_root=source_root))


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        (b"", b""),
        (b" \t\n\r\f\v", b""),
        (b"plain", b"plain"),
        (b"  leading", b"leading"),
        (b"trailing\t\n", b"trailing"),
        (b" \t both \r\n", b"both"),
        (b"hello \t world", b"hello \t world"),
        ("  hé🙂  ".encode(), "hé🙂".encode()),
        ("\u00a0keep\u00a0".encode(), "\u00a0keep\u00a0".encode()),
        ("\u2003keep\u2003".encode(), "\u2003keep\u2003".encode()),
        (b"  a\x00b  ", b"a\x00b"),
    ],
)
def test_runtime_trim_exact_ascii_contract(source: bytes, expected: bytes) -> None:
    value = StringValue.from_utf8(source)
    result = aether_string_trim(value)
    assert result.utf8_bytes == expected


def test_runtime_trim_whitespace_set_fast_paths_and_lifecycle() -> None:
    assert ASCII_WHITESPACE_BYTES == frozenset({0x20, 0x09, 0x0A, 0x0D, 0x0C, 0x0B})
    assert aether_string_trim(StringValue.from_utf8(b"\t \n")) is EMPTY_STRING
    assert aether_string_trim(EMPTY_STRING) is EMPTY_STRING

    value = StringValue.from_utf8(b"unchanged")
    value.claim_owner()
    result = aether_string_trim(value)
    assert result is value
    assert value.strong_count == 2
    assert value.unclaimed_owners == 1
    result.claim_owner()
    result.release()
    value.release()


def test_runtime_trim_checks_partial_result_allocation_overflow(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import aether.string_value as runtime

    value = StringValue.from_utf8(b" x ")
    monkeypatch.setattr(runtime, "MAX_STRING_LENGTH", 24)
    with pytest.raises(OverflowError, match="allocation size overflow"):
        aether_string_trim(value)


PARITY_SOURCE = '''
struct Box { string text; }

string cleaned(string text) { return text.trim(); }
void consume(string text) { println(text == "temporary"); }

int main() {
    string local = "  hello  ";
    const string constant = "\tconst\n";
    Box box = Box("\r field \f");
    Array<string> array = {" array ", "  a\x00b  "};
    List<string> values = {};
    values.push(local.trim());
    values.push(box.text.trim());
    values.push(array[0].trim());
    List<string> copied = values.copy();
    List<string> sliced = copied[0:3];
    List<string> borrowed = {};
    for string item in sliced { borrowed.push(item.trim()); }
    consume(("  temp" + "orary  ").trim());
    println(cleaned(local) == "hello");
    println(constant.trim() == "const");
    println(box.text == "\r field \f");
    println(borrowed[0] == "hello" && borrowed[1] == "field" && borrowed[2] == "array");
    println(array[1].trim().byteLength == 3 && array[1].trim() == "a\x00b");
    println("\u00a0kept\u00a0".trim() == "\u00a0kept\u00a0");
    return 0;
}
'''.replace("\\x00", "\x00")

PARITY_OUTPUT = "true\ntrue\ntrue\ntrue\ntrue\ntrue\ntrue\n"


def test_trim_ast_ir_native_local_const_return_temporary_field_and_collections() -> None:
    assert run_aether(PARITY_SOURCE).output == PARITY_OUTPUT

    typed = _typed(PARITY_SOURCE)
    ir_backend = IRBackend()
    ir_backend.run(typed)
    assert ir_backend.output == PARITY_OUTPUT

    stdout = StringIO()
    assert LLVMRunner().run(typed, stdout=stdout) == 0
    assert stdout.getvalue() == PARITY_OUTPUT


def test_typechecker_requires_string_receiver_and_zero_arguments() -> None:
    with pytest.raises(AetherTypeError, match="expects zero arguments"):
        _typed('int main() { string value = "x".trim(1); return 0; }')
    with pytest.raises(AetherTypeError, match="int.*no native method 'trim'"):
        _typed("int main() { int value = 1; value.trim(); return 0; }")
    assert STRING_TRIM_BUILTIN not in builtin_names()


def test_ir_ssa_trim_identity_signature_effects_location_and_capability() -> None:
    typed = _typed('int main() { string value = " 42 ".trim(); return value.byteLength; }')
    required = {item.capability for item in detect_required_capabilities(typed)}
    assert Capability.STRING_TRIM in required

    ir = IRBackend().lower_verified(typed)
    call = next(
        instruction
        for function in ir.functions
        for block in function.blocks
        for instruction in block.instructions
        if isinstance(instruction, IRCall) and instruction.builtin == STRING_TRIM_BUILTIN
    )
    assert call.function == STRING_TRIM_BUILTIN
    assert len(call.arguments) == 1 and isinstance(call.arguments[0].type, StringType)
    assert call.result is not None and isinstance(call.result.type, StringType)
    assert call.allocates and call.may_trap and call.reads_memory and call.writes_memory
    assert call.must_preserve and call.source_location is not None

    ssa = GeneralSSABuilder().build(ir)
    ssa_call = next(
        instruction
        for function in ssa.functions
        for block in function.blocks
        for instruction in block.instructions
        if isinstance(instruction, SSACall) and instruction.builtin == STRING_TRIM_BUILTIN
    )
    assert ssa_call.source_location == call.source_location
    assert ssa_call.must_preserve and ssa_call.allocates


def test_ir_and_ssa_verifiers_reject_malformed_trim_signature() -> None:
    ir = IRBackend().lower_verified(
        _typed('int main() { return " value ".trim().byteLength; }')
    )
    bad_ir = deepcopy(ir)
    replaced = False
    for function in bad_ir.functions:
        for block in function.blocks:
            for index, instruction in enumerate(block.instructions):
                if isinstance(instruction, IRCall) and instruction.builtin == STRING_TRIM_BUILTIN:
                    block.instructions[index] = replace(instruction, arguments=())
                    replaced = True
    assert replaced
    with pytest.raises(IRVerificationError, match="trim.*requires string"):
        IRVerifier(bad_ir).verify()

    ssa = GeneralSSABuilder().build(ir)
    bad_ssa = deepcopy(ssa)
    replaced = False
    for function in bad_ssa.functions:
        for block in function.blocks:
            for index, instruction in enumerate(block.instructions):
                if isinstance(instruction, SSACall) and instruction.builtin == STRING_TRIM_BUILTIN:
                    block.instructions[index] = replace(instruction, arguments=())
                    replaced = True
    assert replaced
    with pytest.raises(SSAVerificationError, match="trim.*requires string"):
        SSAVerifier(bad_ssa).verify()


def test_trim_keeps_parsing_strict_and_allows_explicit_cleanup() -> None:
    source = '''
int main() {
    IntParseResult direct = parseInt(" 42 ");
    IntParseResult cleaned = parseInt(" 42 ".trim());
    DoubleParseResult decimal = parseDouble("\t2.5\n".trim());
    println(direct.status == ParseStatus.InvalidFormat);
    println(cleaned.status == ParseStatus.Success && cleaned.value == 42);
    println(decimal.status == ParseStatus.Success && decimal.value == 2.5);
    return 0;
}
'''
    expected = "true\ntrue\ntrue\n"
    assert run_aether(source).output == expected
    stdout = StringIO()
    assert LLVMRunner().run(_typed(source), stdout=stdout) == 0
    assert stdout.getvalue() == expected


def test_trim_crosses_imported_function_boundary(tmp_path: Path) -> None:
    (tmp_path / "TextFacade.ae").write_text(
        "package TextFacade; public string clean(string value) { return value.trim(); }",
        encoding="utf-8",
    )
    source = '''
from TextFacade import clean;
int main() { println(clean("  module  ") == "module"); return 0; }
'''
    assert run_aether(source, source_root=tmp_path).output == "true\n"
    stdout = StringIO()
    assert LLVMRunner().run(_typed(source, source_root=tmp_path), stdout=stdout) == 0
    assert stdout.getvalue() == "true\n"


def test_llvm_trim_helper_is_length_aware_owned_and_has_exact_fast_paths() -> None:
    llvm = LLVMBuilder().emit_llvm(
        _typed('int main() { return "  value  ".trim().byteLength; }')
    )
    helper = llvm.split("define private ptr @aether_string_trim", 1)[1].split("\n}", 1)[0]
    classifier = llvm.split(
        "define private i1 @aether_string_is_ascii_whitespace", 1
    )[1].split("\n}", 1)[0]
    for byte in (32, 9, 10, 13, 12, 11):
        assert f"i8 {byte}, label %whitespace" in classifier
    assert "call void @aether_string_retain(ptr %value)" in helper
    assert "ret ptr @.aether.string.empty" in helper
    assert "call ptr @aether_string_from_utf8" in helper
    assert "@strlen" not in llvm and "@isspace" not in llvm


@pytest.mark.skipif(shutil.which("clang") is None, reason="clang is required")
@pytest.mark.parametrize("profile", ["O0", "O1", "O2"])
def test_trim_survives_ir_ssa_optimizers_and_real_clang(
    profile: str, tmp_path: Path
) -> None:
    ir = IRBackend().lower_verified(_typed(PARITY_SOURCE))
    optimized_ir = IRVerifier(build_optimizer_pipeline(profile).run(ir)).verify()
    ssa = GeneralSSABuilder().build(optimized_ir)
    optimized_ssa = SSAOptimizerPipeline(verify_after_each=True).run(ssa)
    llvm = LLVMBackend().emit(optimized_ssa)
    assert "call ptr @aether_string_trim" in llvm
    assert "call void @aether_string_release" in llvm

    llvm_path = tmp_path / f"string-trim-{profile}.ll"
    executable = tmp_path / f"string-trim-{profile}"
    llvm_path.write_text(llvm, encoding="utf-8")
    compiled = subprocess.run(
        [shutil.which("clang") or "clang", f"-{profile}", str(llvm_path), "-o", str(executable)],
        check=False,
        capture_output=True,
    )
    assert compiled.returncode == 0, compiled.stderr.decode(errors="replace")
    completed = subprocess.run([str(executable)], check=False, capture_output=True)
    assert completed.returncode == 0
    assert completed.stdout.decode() == PARITY_OUTPUT
