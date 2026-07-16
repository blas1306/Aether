from __future__ import annotations

from io import StringIO
from pathlib import Path
import shutil
import subprocess

import pytest

from aether.backend.llvm import LLVMBackend, LLVMBuilder, LLVMRunner
from aether.errors import AetherTypeError
from aether.ir import IRBinaryOp, IRCall, IRVerifier, StringType
from aether.ir.optimizer import build_optimizer_pipeline
from aether.pipeline import IRBackend, prepare_typed_program
from aether.runner import run_aether
from aether.ssa import GeneralSSABuilder, SSABinaryOp
from aether.ssa.optimizer import SSAOptimizerPipeline
from aether.string_value import EMPTY_STRING, StringValue, aether_string_concat
from aether.typechecker import TypeChecker


def _typed(source: str, *, source_root: Path | None = None):
    return prepare_typed_program(source, TypeChecker(source_root=source_root))


def test_runtime_concat_bytes_empty_fast_paths_and_owned_contract() -> None:
    left = StringValue.from_utf8(b"h\x00\xc3\xa9")
    right = StringValue.from_utf8("🙂".encode())

    result = aether_string_concat(left, right)
    assert result.utf8_bytes == b"h\x00\xc3\xa9" + "🙂".encode()
    assert result.strong_count == 1
    assert result is not left and result is not right

    right.claim_owner()
    same_right = aether_string_concat(EMPTY_STRING, right)
    assert same_right is right
    assert right.strong_count == 2
    assert right.unclaimed_owners == 1
    same_right.claim_owner()
    same_right.release()
    right.release()

    assert aether_string_concat(EMPTY_STRING, EMPTY_STRING) is EMPTY_STRING


def test_runtime_concat_checks_length_and_allocation_overflow(monkeypatch: pytest.MonkeyPatch) -> None:
    import aether.string_value as runtime

    left = StringValue.from_utf8(b"ab")
    right = StringValue.from_utf8(b"cd")
    monkeypatch.setattr(runtime, "MAX_STRING_LENGTH", 3)
    with pytest.raises(OverflowError, match="concatenation length overflow"):
        aether_string_concat(left, right)

    monkeypatch.setattr(runtime, "MAX_STRING_LENGTH", 28)
    with pytest.raises(OverflowError, match="allocation size overflow"):
        aether_string_concat(left, right)


@pytest.mark.parametrize(
    ("literal", "expected"),
    [
        ('""', 0),
        ('"abc"', 3),
        ('"é"', 2),
        ('"€"', 3),
        ('"🙂"', 4),
        ('"a\x00b"', 3),
        ('"é" + "🙂"', 6),
    ],
)
def test_byte_length_is_utf8_byte_count_in_ast_and_native(literal: str, expected: int) -> None:
    source = f"int main() {{ string value = {literal}; println(value.byteLength); return 0; }}"
    assert run_aether(source).output == f"{expected}\n"
    stdout = StringIO()
    assert LLVMRunner().run(_typed(source), stdout=stdout) == 0
    assert stdout.getvalue() == f"{expected}\n"


@pytest.mark.parametrize(
    "source",
    [
        'int main() { string bad = "count: " + 3; return 0; }',
        'int main() { string bad = 3 + " items"; return 0; }',
        'int main() { string bad = "flag: " + true; return 0; }',
    ],
)
def test_typechecker_rejects_implicit_string_conversions(source: str) -> None:
    with pytest.raises(AetherTypeError, match="cannot mix string with non-string"):
        _typed(source)


def test_ir_ssa_and_effects_identify_concat_and_byte_length() -> None:
    typed = _typed(
        'string join(string a, string b) { return a + b; } '
        'int main() { string value = join("a", "b") + "c"; return value.byteLength; }'
    )
    ir = IRBackend().lower_verified(typed)
    concat = next(
        instruction
        for function in ir.functions
        for block in function.blocks
        for instruction in block.instructions
        if isinstance(instruction, IRBinaryOp) and isinstance(instruction.result.type, StringType)
    )
    assert concat.allocates and concat.may_trap and concat.reads_memory
    assert concat.source_location is not None
    byte_length = next(
        instruction
        for function in ir.functions
        for block in function.blocks
        for instruction in block.instructions
        if isinstance(instruction, IRCall) and instruction.builtin == "__aether_string_byte_length"
    )
    assert byte_length.may_trap and byte_length.reads_memory

    ssa = GeneralSSABuilder().build(ir)
    ssa_concat = next(
        instruction
        for function in ssa.functions
        for block in function.blocks
        for instruction in block.instructions
        if isinstance(instruction, SSABinaryOp) and isinstance(instruction.result.type, StringType)
    )
    assert ssa_concat.must_preserve
    assert ssa_concat.source_location == concat.source_location


COMPOSITE_SOURCE = '''
struct Person { string fullName; }

string join(string left, string right) { return left + right; }
void consume(string value) { println(value); }

int main() {
    string first = "Ada";
    string last = "Lovelace";
    Person person = Person(first + " " + last);
    Array<string> names = {first + last, person.fullName};
    List<string> values = {};
    values.push(first + "-" + last);
    List<string> sliced = values[0:1];
    consume(first + last);
    println(person.fullName);
    println(names[0]);
    println(sliced[0]);
    println(join(first, last).byteLength);
    return 0;
}
'''


def test_concat_temporary_return_struct_array_list_and_slice_match_ast_native() -> None:
    expected = "AdaLovelace\nAda Lovelace\nAdaLovelace\nAda-Lovelace\n11\n"
    assert run_aether(COMPOSITE_SOURCE).output == expected
    stdout = StringIO()
    assert LLVMRunner().run(_typed(COMPOSITE_SOURCE), stdout=stdout) == 0
    assert stdout.getvalue() == expected


@pytest.mark.skipif(shutil.which("clang") is None, reason="clang is required")
@pytest.mark.parametrize("profile", ["O0", "O1", "O2"])
def test_concat_survives_ir_ssa_profiles_and_real_clang(profile: str, tmp_path: Path) -> None:
    ir = IRBackend().lower_verified(_typed(COMPOSITE_SOURCE))
    optimized_ir = IRVerifier(build_optimizer_pipeline(profile).run(ir)).verify()
    ssa = GeneralSSABuilder().build(optimized_ir)
    optimized_ssa = SSAOptimizerPipeline(verify_after_each=True).run(ssa)
    llvm = LLVMBackend().emit(optimized_ssa)
    assert "call ptr @aether_string_concat" in llvm
    assert "call void @aether_string_release" in llvm

    llvm_path = tmp_path / f"string-concat-{profile}.ll"
    executable = tmp_path / f"string-concat-{profile}"
    llvm_path.write_text(llvm, encoding="utf-8")
    compiled = subprocess.run(
        [shutil.which("clang") or "clang", f"-{profile}", str(llvm_path), "-o", str(executable)],
        check=False,
        capture_output=True,
    )
    assert compiled.returncode == 0, compiled.stderr.decode(errors="replace")
    completed = subprocess.run([str(executable)], check=False, capture_output=True)
    assert completed.returncode == 0
    assert completed.stdout.decode() == "AdaLovelace\nAda Lovelace\nAdaLovelace\nAda-Lovelace\n11\n"


def test_imported_concat_alias_and_byte_length_run_native(tmp_path: Path) -> None:
    (tmp_path / "Text.ae").write_text(
        "package Text; public alias TextValue = string; "
        "public TextValue join(TextValue left, TextValue right) { return left + right; }",
        encoding="utf-8",
    )
    source = '''
from Text import TextValue;
from Text import join;
int main() {
    TextValue value = join("é", "🙂");
    println(value);
    println(value.byteLength);
    return 0;
}
'''
    assert run_aether(source, source_root=tmp_path).output == "é🙂\n6\n"
    stdout = StringIO()
    assert LLVMRunner().run(_typed(source, source_root=tmp_path), stdout=stdout) == 0
    assert stdout.getvalue() == "é🙂\n6\n"


def test_llvm_runtime_uses_checked_single_allocation_concat_without_c_string_apis() -> None:
    llvm = LLVMBuilder().emit_llvm(
        _typed('string join(string a, string b) { return a + b; } int main() { return join("a", "b").byteLength; }')
    )
    helper = llvm.split("define private ptr @aether_string_concat", 1)[1].split("\n}", 1)[0]
    assert helper.count("call noalias ptr @malloc") == 1
    assert "@llvm.uadd.with.overflow.i64" in helper
    assert helper.count("@llvm.memcpy.p0.p0.i64") == 2
    assert "call void @aether_string_retain" in helper
    # strlen is confined to the POSIX argv boundary; Aether string semantics
    # remain length-aware and the concat helper never calls it.
    assert "@strlen" not in helper
    assert "@strcat" not in llvm
    assert "@sprintf" not in llvm


def test_native_owned_temporaries_release_after_borrow_and_chain_but_return_transfers() -> None:
    llvm = LLVMBuilder().emit_llvm(
        _typed(
            'string chain(string a, string b, string c) { return a + b + c; } '
            'void consume(string value) {} '
            'int main() { consume("a" + "b"); return chain("c", "d", "e").byteLength; }'
        )
    )
    chain = llvm.split("define ptr @chain", 1)[1].split("\n}", 1)[0]
    main = llvm.split("define i32 @__aether_program_main", 1)[1].split("\n}", 1)[0]

    assert chain.count("call ptr @aether_string_concat") == 2
    assert chain.count("call void @aether_string_release") == 1
    assert "ret ptr %1" in chain
    assert "call void @consume(ptr %0)\n  call void @aether_string_release(ptr %0)" in main
    assert "call void @aether_string_release(ptr %1)" in main
