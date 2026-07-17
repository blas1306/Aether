from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from io import StringIO
from pathlib import Path
import shutil
import subprocess

import pytest

from aether.backend.llvm import LLVMBackend, LLVMBuilder, LLVMRunner
from aether.capabilities import Capability, CapabilityState, NATIVE_CAPABILITY_PROFILE, detect_required_capabilities
from aether.collection_value import (
    collection_debug_counters,
    reset_collection_debug_counters,
)
from aether.errors import AetherRuntimeError, AetherTypeError
from aether.ir import ArrayType, IRCall, IRVerificationError, IRVerifier, StringType
from aether.ir.optimizer import build_optimizer_pipeline
from aether.pipeline import IRBackend, prepare_typed_program
from aether.runner import run_aether
from aether.ssa import GeneralSSABuilder, SSACall, SSAVerificationError, SSAVerifier
from aether.ssa.optimizer import SSAOptimizerPipeline
from aether.stdlib.registry import builtin_names
from aether.string_value import (
    EMPTY_STRING,
    STRING_SPLIT_BUILTIN,
    STRING_SPLIT_EMPTY_SEPARATOR_MESSAGE,
    StringValue,
    aether_string_split,
)
from aether.typechecker import TypeChecker


def _typed(source: str, *, source_root: Path | None = None):
    return prepare_typed_program(source, TypeChecker(source_root=source_root))


@pytest.mark.parametrize(
    ("text", "separator", "expected"),
    [
        (b"", b",", [b""]),
        (b"a", b",", [b"a"]),
        (b"a,b,c", b",", [b"a", b"b", b"c"]),
        (b"a,", b",", [b"a", b""]),
        (b",a", b",", [b"", b"a"]),
        (b"a,,b", b",", [b"a", b"", b"b"]),
        (b"same", b"same", [b"", b""]),
        (b"short", b"longer", [b"short"]),
        (b"aaaa", b"aa", [b"", b"", b""]),
        (b"ababa", b"aba", [b"", b"ba"]),
        ("uno€dos€tres".encode(), "€".encode(), [b"uno", b"dos", b"tres"]),
        (b"a\x00b\x00c", b"\x00", [b"a", b"b", b"c"]),
        (b"a\x00b--c\x00d", b"--", [b"a\x00b", b"c\x00d"]),
    ],
)
def test_runtime_split_exact_bytes_empty_fields_utf8_nul_and_overlap(
    text: bytes, separator: bytes, expected: list[bytes]
) -> None:
    result = aether_string_split(
        StringValue.from_utf8(text), StringValue.from_utf8(separator)
    )
    assert [item.utf8_bytes for item in result] == expected
    result.claim_owner()
    result.release()


def test_runtime_split_no_match_retain_empty_singleton_and_cleanup() -> None:
    value = StringValue.from_utf8(b"unchanged")
    value.claim_owner()
    result = aether_string_split(value, StringValue.literal(","))
    assert result[0] is value
    assert value.strong_count == 2
    result.claim_owner()
    result.release()
    assert value.strong_count == 1
    value.release()

    empties = aether_string_split(StringValue.literal("aaaa"), StringValue.literal("aa"))
    assert all(item is EMPTY_STRING for item in empties)
    empties.claim_owner()
    empties.release()


def test_runtime_split_long_text_and_many_parts() -> None:
    text = b",".join(str(index).encode() for index in range(2000))
    result = aether_string_split(StringValue.from_utf8(text), StringValue.literal(","))
    assert len(result) == 2000
    assert result[0].utf8_bytes == b"0"
    assert result[-1].utf8_bytes == b"1999"
    result.claim_owner()
    result.release()


def test_runtime_split_rejects_empty_separator_and_rolls_back_partial_array(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(AetherRuntimeError, match="separator cannot be empty"):
        aether_string_split(StringValue.literal("text"), EMPTY_STRING)

    reset_collection_debug_counters()
    import aether.string_value as runtime

    original = runtime.StringValue.from_utf8
    fragments: list[StringValue] = []

    def failing_from_utf8(data):
        if bytes(data) == b"b":
            raise MemoryError("injected fragment allocation failure")
        value = original(data)
        if bytes(data) == b"a":
            fragments.append(value)
        return value

    monkeypatch.setattr(runtime.StringValue, "from_utf8", failing_from_utf8)
    with pytest.raises(MemoryError, match="injected"):
        aether_string_split(StringValue.literal("a,b,c"), StringValue.literal(","))
    counters = collection_debug_counters()
    assert counters.objects_allocated == counters.objects_freed == 1
    assert counters.buffers_allocated == counters.buffers_freed == 1
    assert fragments and fragments[0]._released


def test_runtime_split_checks_array_and_fragment_allocation_overflow(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import aether.string_value as runtime

    text = StringValue.literal("a,b")
    separator = StringValue.literal(",")
    reset_collection_debug_counters()
    monkeypatch.setattr(runtime, "MAX_STRING_LENGTH", 24)
    with pytest.raises(OverflowError, match="fragment allocation size overflow"):
        aether_string_split(text, separator)
    counters = collection_debug_counters()
    assert counters.objects_allocated == counters.objects_freed == 1

    monkeypatch.setattr(runtime, "MAX_STRING_LENGTH", 8)
    with pytest.raises(OverflowError, match="Array header size overflow"):
        aether_string_split(text, separator)


PARITY_SOURCE = '''
struct Box { string text; }
struct PartsBox { Array<string> values; }

Array<string> parts(string text, string separator) { return text.split(separator); }
void consume(Array<string> values) { println(values.length == 2 && values[1] == "temporary"); }

int main() {
    string local = "a,,b,";
    const string separator = ",";
    Box box = Box("uno€dos€tres");
    Array<string> array = {"left|right", "a\0b\0c"};
    Array<string> localParts = local.split(separator);
    Array<string> utf8 = box.text.split("€");
    Array<string> nul = array[1].split("\0");
    Array<string> copied = localParts.copy();
    Array<string> sliced = copied[1:4];
    PartsBox partsBox = PartsBox(local.split(separator));
    Array<Array<string>> nested = {partsBox.values, "x|y".split("|")};
    List<string> borrowed = {};
    for (string item in sliced) { borrowed.push(item); }
    consume(("temp:" + "temporary").split(":"));
    println(localParts.length == 4 && localParts[0] == "a" && localParts[1] == "" && localParts[3] == "");
    println(parts("ababa", "aba")[1] == "ba");
    println(utf8.length == 3 && utf8[1] == "dos");
    println(nul.length == 3 && nul[0] == "a" && nul[2] == "c");
    println(copied == localParts && sliced.length == 3 && borrowed[0] == "");
    println("x,y".split(",")[0] == "x");
    println(array[0] == "left|right" && box.text == "uno€dos€tres");
    println(nested[0][1] == "" && nested[1][1] == "y");
    return 0;
}
'''

PARITY_OUTPUT = "true\n" * 9


def test_split_ast_ir_native_lifecycle_collections_temporaries_and_return() -> None:
    assert run_aether(PARITY_SOURCE).output == PARITY_OUTPUT
    typed = _typed(PARITY_SOURCE)
    ir_backend = IRBackend()
    ir_backend.run(typed)
    assert ir_backend.output == PARITY_OUTPUT
    stdout = StringIO()
    assert LLVMRunner().run(typed, stdout=stdout) == 0
    assert stdout.getvalue() == PARITY_OUTPUT


def test_typechecker_requires_exactly_one_string_separator() -> None:
    with pytest.raises(AetherTypeError, match="exactly one argument"):
        _typed('int main() { Array<string> p = "x".split(); return 0; }')
    with pytest.raises(AetherTypeError, match="string separator"):
        _typed('int main() { Array<string> p = "x".split(1); return 0; }')
    with pytest.raises(AetherTypeError, match="int.*no native method 'split'"):
        _typed("int main() { int x = 1; x.split(\",\"); return 0; }")
    assert STRING_SPLIT_BUILTIN not in builtin_names()


def test_ir_ssa_split_signature_effects_source_location_capability_and_verifiers() -> None:
    typed = _typed('int main() { return "a,b".split(",").length; }')
    required = {item.capability for item in detect_required_capabilities(typed)}
    assert Capability.STRING_SPLIT in required
    assert NATIVE_CAPABILITY_PROFILE.support_for(Capability.STRING_SPLIT).state is CapabilityState.COMPLETE

    ir = IRBackend().lower_verified(typed)
    call = next(
        instruction
        for function in ir.functions
        for block in function.blocks
        for instruction in block.instructions
        if isinstance(instruction, IRCall) and instruction.builtin == STRING_SPLIT_BUILTIN
    )
    assert call.function == STRING_SPLIT_BUILTIN
    assert len(call.arguments) == 2
    assert all(isinstance(argument.type, StringType) for argument in call.arguments)
    assert call.result is not None and call.result.type == ArrayType(StringType())
    assert call.allocates and call.may_trap and call.reads_memory and call.writes_memory
    assert call.must_preserve and call.source_location is not None

    bad_ir = deepcopy(ir)
    for function in bad_ir.functions:
        for block in function.blocks:
            for index, instruction in enumerate(block.instructions):
                if isinstance(instruction, IRCall) and instruction.builtin == STRING_SPLIT_BUILTIN:
                    block.instructions[index] = replace(instruction, arguments=instruction.arguments[:1])
    with pytest.raises(IRVerificationError, match="split.*requires"):
        IRVerifier(bad_ir).verify()

    ssa = GeneralSSABuilder().build(ir)
    ssa_call = next(
        instruction
        for function in ssa.functions
        for block in function.blocks
        for instruction in block.instructions
        if isinstance(instruction, SSACall) and instruction.builtin == STRING_SPLIT_BUILTIN
    )
    assert ssa_call.source_location == call.source_location
    assert ssa_call.must_preserve and ssa_call.allocates
    bad_ssa = deepcopy(ssa)
    for function in bad_ssa.functions:
        for block in function.blocks:
            for index, instruction in enumerate(block.instructions):
                if isinstance(instruction, SSACall) and instruction.builtin == STRING_SPLIT_BUILTIN:
                    block.instructions[index] = replace(instruction, arguments=instruction.arguments[:1])
    with pytest.raises(SSAVerificationError, match="split.*requires"):
        SSAVerifier(bad_ssa).verify()

    unused = IRBackend().lower_verified(
        _typed('int main() { "a,b".split(","); return 0; }')
    )
    optimized_unused = build_optimizer_pipeline("O2").run(unused)
    assert any(
        isinstance(instruction, IRCall)
        and instruction.builtin == STRING_SPLIT_BUILTIN
        for function in optimized_unused.functions
        for block in function.blocks
        for instruction in block.instructions
    )
    optimized_unused_ssa = SSAOptimizerPipeline(verify_after_each=True).run(
        GeneralSSABuilder().build(IRVerifier(optimized_unused).verify())
    )
    assert any(
        isinstance(instruction, SSACall)
        and instruction.builtin == STRING_SPLIT_BUILTIN
        for function in optimized_unused_ssa.functions
        for block in function.blocks
        for instruction in block.instructions
    )


def test_empty_separator_panics_consistently_in_ast_ir_and_native() -> None:
    source = 'int main() { return "text".split("").length; }'
    typed = _typed(source)
    with pytest.raises(AetherRuntimeError, match="separator cannot be empty"):
        run_aether(source)
    with pytest.raises(AetherRuntimeError, match="separator cannot be empty"):
        IRBackend().run(typed)
    stdout = StringIO()
    assert LLVMRunner().run(typed, stdout=stdout) == 1
    assert stdout.getvalue() == STRING_SPLIT_EMPTY_SEPARATOR_MESSAGE + "\n"


def test_split_crosses_module_alias_and_owned_return(tmp_path: Path) -> None:
    (tmp_path / "TextParts.ae").write_text(
        "package TextParts; public Array<string> divide(string value, string separator) "
        "{ return value.split(separator); }",
        encoding="utf-8",
    )
    source = '''
from TextParts import divide as pieces;
int main() {
    Array<string> result = pieces("left::right::", "::");
    println(result.length == 3 && result[0] == "left" && result[2] == "");
    return 0;
}
'''
    assert run_aether(source, source_root=tmp_path).output == "true\n"
    stdout = StringIO()
    assert LLVMRunner().run(_typed(source, source_root=tmp_path), stdout=stdout) == 0
    assert stdout.getvalue() == "true\n"


def test_llvm_split_helper_is_two_pass_length_aware_owned_and_array_exact() -> None:
    llvm = LLVMBuilder().emit_llvm(_typed('int main() { return "a,b".split(",").length; }'))
    helper = llvm.split("define private ptr @aether_string_split", 1)[1].split("\n}", 1)[0]
    assert "count_loop:" in helper and "split_loop:" in helper
    assert "call i32 @memcmp" in helper
    assert "call ptr @aether_array_new" in helper
    assert "call ptr @aether_string_from_utf8" in helper
    assert "call void @aether_string_retain(ptr %text)" in helper
    assert "add i64 %count_index, %separator_length" in helper
    for forbidden in ("@strlen", "@strstr", "@strtok"):
        assert forbidden not in helper


@pytest.mark.skipif(shutil.which("clang") is None, reason="clang is required")
@pytest.mark.parametrize("profile", ["O0", "O1", "O2"])
def test_split_survives_ir_ssa_optimizers_and_real_clang(profile: str, tmp_path: Path) -> None:
    ir = IRBackend().lower_verified(_typed(PARITY_SOURCE))
    optimized_ir = IRVerifier(build_optimizer_pipeline(profile).run(ir)).verify()
    optimized_ssa = SSAOptimizerPipeline(verify_after_each=True).run(
        GeneralSSABuilder().build(optimized_ir)
    )
    llvm = LLVMBackend().emit(optimized_ssa)
    assert "call ptr @aether_string_split" in llvm
    assert "call void @aether_array_release_string" in llvm

    llvm_path = tmp_path / f"string-split-{profile}.ll"
    executable = tmp_path / f"string-split-{profile}"
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
