from __future__ import annotations

from io import StringIO
from pathlib import Path
import shutil
import subprocess

import pytest

from aether.backend.llvm import LLVMBackend, LLVMBuilder, LLVMRunner
from aether.errors import AetherTypeError
from aether.ir import IRCall, IRVerifier, StringType, StructType
from aether.ir.optimizer import build_optimizer_pipeline
from aether.pipeline import IRBackend, prepare_typed_program
from aether.runner import run_aether
from aether.ssa import GeneralSSABuilder, SSACall
from aether.ssa.optimizer import SSAOptimizerPipeline
from aether.string_parsing import ParseStatus, parse_double_bytes, parse_int_bytes
from aether.typechecker import TypeChecker


def _typed(source: str):
    return prepare_typed_program(source, TypeChecker())


@pytest.mark.parametrize(
    ("text", "value", "status"),
    [
        (b"0", 0, ParseStatus.Success),
        (b"123", 123, ParseStatus.Success),
        (b"-123", -123, ParseStatus.Success),
        (b"+123", 123, ParseStatus.Success),
        (b"2147483647", 2147483647, ParseStatus.Success),
        (b"-2147483648", -2147483648, ParseStatus.Success),
        (b"2147483648", 0, ParseStatus.OutOfRange),
        (b"-2147483649", 0, ParseStatus.OutOfRange),
        (b"999999999999x", 0, ParseStatus.InvalidFormat),
        (b"", 0, ParseStatus.Empty),
        (b"+", 0, ParseStatus.InvalidFormat),
        (b"-", 0, ParseStatus.InvalidFormat),
        (b" 12 ", 0, ParseStatus.InvalidFormat),
        (b"1e2", 0, ParseStatus.InvalidFormat),
        (b"1.0", 0, ParseStatus.InvalidFormat),
        (b"1_000", 0, ParseStatus.InvalidFormat),
        (b"12\x003", 0, ParseStatus.InvalidFormat),
        ("１２".encode(), 0, ParseStatus.InvalidFormat),
    ],
)
def test_int_parser_contract(text: bytes, value: int, status: ParseStatus) -> None:
    parsed = parse_int_bytes(text)
    assert parsed.status == status
    assert parsed.value == value


@pytest.mark.parametrize(
    ("text", "status"),
    [
        (b"123", ParseStatus.Success),
        (b"-123", ParseStatus.Success),
        (b"123.5", ParseStatus.Success),
        (b".5", ParseStatus.Success),
        (b"5.", ParseStatus.Success),
        (b"1e10", ParseStatus.Success),
        (b"1E10", ParseStatus.Success),
        (b"-2.5e-3", ParseStatus.Success),
        (b"+2.5E+3", ParseStatus.Success),
        (b"1e-9999", ParseStatus.Success),
        (b"", ParseStatus.Empty),
        (b"+", ParseStatus.InvalidFormat),
        (b".", ParseStatus.InvalidFormat),
        (b"1..2", ParseStatus.InvalidFormat),
        (b"1e", ParseStatus.InvalidFormat),
        (b" 1", ParseStatus.InvalidFormat),
        (b"1,5", ParseStatus.InvalidFormat),
        (b"1\x002", ParseStatus.InvalidFormat),
        ("é".encode(), ParseStatus.InvalidFormat),
        (b"NaN", ParseStatus.InvalidFormat),
        (b"Infinity", ParseStatus.InvalidFormat),
        (b"-Infinity", ParseStatus.InvalidFormat),
        (b"1e309", ParseStatus.OutOfRange),
    ],
)
def test_double_parser_contract(text: bytes, status: ParseStatus) -> None:
    parsed = parse_double_bytes(text)
    assert parsed.status == status
    if status is not ParseStatus.Success:
        assert parsed.value == 0.0


PARITY_SOURCE = '''
struct ParseBox { IntParseResult identifier; DoubleParseResult amount; }

IntParseResult parseIdentifier(string text) { return parseInt(text); }

int main() {
    IntParseResult max = parseIdentifier("2147483647");
    IntParseResult min = parseInt("-2147483648");
    IntParseResult badInt = parseInt("12\x00tail");
    DoubleParseResult decimal = parseDouble("-2.5e-3");
    DoubleParseResult signedZero = parseDouble("-0");
    DoubleParseResult underflow = parseDouble("1e-9999");
    DoubleParseResult overflow = parseDouble("1e309");
    ParseBox box = ParseBox(max, decimal);
    Array<DoubleParseResult> amounts = {decimal, underflow};
    List<IntParseResult> ids = {min, box.identifier};
    List<IntParseResult> copied = ids.copy();
    List<IntParseResult> sliced = copied[0:2];
    int successes = 0;
    for IntParseResult item in sliced {
        if item.status == ParseStatus.Success { successes = successes + 1; }
    }
    println(max.value);
    println(min.value);
    println(badInt.status);
    println(decimal.status == ParseStatus.Success);
    println(decimal.value < -0.0024 && decimal.value > -0.0026);
    println(signedZero.status == ParseStatus.Success && 1.0 / signedZero.value < 0.0);
    println(underflow.status == ParseStatus.Success && underflow.value == 0.0);
    println(overflow.status);
    println(amounts[0].status == ParseStatus.Success);
    println(successes);
    return 0;
}
'''

PARITY_OUTPUT = (
    "2147483647\n"
    "-2147483648\n"
    "ParseStatus.InvalidFormat\n"
    "true\n"
    "true\n"
    "true\n"
    "true\n"
    "ParseStatus.OutOfRange\n"
    "true\n"
    "2\n"
)


def test_ast_ir_and_native_parity_with_structs_lists_copy_slice_and_return() -> None:
    assert run_aether(PARITY_SOURCE).output == PARITY_OUTPUT

    typed = _typed(PARITY_SOURCE)
    ir_backend = IRBackend()
    ir_backend.run(typed)
    assert ir_backend.output == PARITY_OUTPUT

    stdout = StringIO()
    assert LLVMRunner().run(typed, stdout=stdout) == 0
    assert stdout.getvalue() == PARITY_OUTPUT


def test_full_status_matrix_matches_ast_ir_and_native() -> None:
    cases = [
        ("IntParseResult", "parseInt", "0", "Success"),
        ("IntParseResult", "parseInt", "+123", "Success"),
        ("IntParseResult", "parseInt", "2147483648", "OutOfRange"),
        ("IntParseResult", "parseInt", "-2147483649", "OutOfRange"),
        ("IntParseResult", "parseInt", "999999999999x", "InvalidFormat"),
        ("IntParseResult", "parseInt", "", "Empty"),
        ("IntParseResult", "parseInt", "-", "InvalidFormat"),
        ("IntParseResult", "parseInt", " 12 ", "InvalidFormat"),
        ("IntParseResult", "parseInt", "1.0", "InvalidFormat"),
        ("IntParseResult", "parseInt", "1e2", "InvalidFormat"),
        ("IntParseResult", "parseInt", "12\x003", "InvalidFormat"),
        ("IntParseResult", "parseInt", "é", "InvalidFormat"),
        ("DoubleParseResult", "parseDouble", ".5", "Success"),
        ("DoubleParseResult", "parseDouble", "5.", "Success"),
        ("DoubleParseResult", "parseDouble", "+2.5E+3", "Success"),
        ("DoubleParseResult", "parseDouble", "", "Empty"),
        ("DoubleParseResult", "parseDouble", ".", "InvalidFormat"),
        ("DoubleParseResult", "parseDouble", "1e", "InvalidFormat"),
        ("DoubleParseResult", "parseDouble", "1,5", "InvalidFormat"),
        ("DoubleParseResult", "parseDouble", "NaN", "InvalidFormat"),
        ("DoubleParseResult", "parseDouble", "Infinity", "InvalidFormat"),
        ("DoubleParseResult", "parseDouble", "1e309", "OutOfRange"),
        ("DoubleParseResult", "parseDouble", "1e-9999", "Success"),
    ]
    lines = ["int main() {"]
    expected_lines: list[str] = []
    for index, (result_type, callee, text, status) in enumerate(cases):
        escaped = text.replace("\\", "\\\\").replace('"', '\\"')
        lines.append(f'{result_type} result{index} = {callee}("{escaped}");')
        lines.append(f"println(result{index}.status);")
        expected_lines.append(f"ParseStatus.{status}")
    lines.append("return 0; }")
    source = "\n".join(lines)
    expected = "\n".join(expected_lines) + "\n"

    assert run_aether(source).output == expected
    typed = _typed(source)
    ir_backend = IRBackend()
    ir_backend.run(typed)
    assert ir_backend.output == expected
    stdout = StringIO()
    assert LLVMRunner().run(typed, stdout=stdout) == 0
    assert stdout.getvalue() == expected


@pytest.mark.parametrize("callee", ["parseInt", "parseDouble"])
def test_typechecker_requires_exactly_one_string(callee: str) -> None:
    result_type = "IntParseResult" if callee == "parseInt" else "DoubleParseResult"
    with pytest.raises(AetherTypeError, match="expects a string argument"):
        _typed(f"int main() {{ {result_type} bad = {callee}(12); return 0; }}")
    with pytest.raises(AetherTypeError, match="expects exactly one argument"):
        _typed(f"int main() {{ {result_type} bad = {callee}(); return 0; }}")


def test_result_fields_are_nominal_and_unknown_fields_are_diagnosed() -> None:
    with pytest.raises(AetherTypeError, match="IntParseResult.*no field 'error'"):
        _typed(
            'int main() { IntParseResult result = parseInt("1"); '
            'println(result.error); return 0; }'
        )


def test_ir_ssa_builtin_identity_effects_layout_and_source_location() -> None:
    ir = IRBackend().lower_verified(
        _typed('int main() { IntParseResult result = parseInt("42"); return result.value; }')
    )
    call = next(
        instruction
        for function in ir.functions
        for block in function.blocks
        for instruction in block.instructions
        if isinstance(instruction, IRCall) and instruction.builtin == "parseInt"
    )
    assert call.function == "parseInt"
    assert isinstance(call.arguments[0].type, StringType)
    assert call.result is not None and call.result.type == StructType("IntParseResult")
    assert call.reads_memory and not call.may_trap and not call.allocates
    assert call.source_location is not None

    ssa = GeneralSSABuilder().build(ir)
    ssa_call = next(
        instruction
        for function in ssa.functions
        for block in function.blocks
        for instruction in block.instructions
        if isinstance(instruction, SSACall) and instruction.builtin == "parseInt"
    )
    assert ssa_call.source_location == call.source_location
    assert ssa_call.reads_memory


@pytest.mark.skipif(shutil.which("clang") is None, reason="clang is required")
@pytest.mark.parametrize("profile", ["O0", "O1", "O2"])
def test_parsing_survives_optimizers_and_real_clang(profile: str, tmp_path: Path) -> None:
    ir = IRBackend().lower_verified(_typed(PARITY_SOURCE))
    optimized_ir = IRVerifier(build_optimizer_pipeline(profile).run(ir)).verify()
    ssa = GeneralSSABuilder().build(optimized_ir)
    optimized_ssa = SSAOptimizerPipeline(verify_after_each=True).run(ssa)
    llvm = LLVMBackend().emit(optimized_ssa)
    assert "call %struct.IntParseResult @aether_parse_int" in llvm
    assert "call %struct.DoubleParseResult @aether_parse_double" in llvm
    assert "@strtod_l" in llvm and "@newlocale" in llvm
    assert "@strlen" not in llvm

    llvm_path = tmp_path / f"string-parsing-{profile}.ll"
    executable = tmp_path / f"string-parsing-{profile}"
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


def test_native_runtime_is_length_aware_and_uses_explicit_c_locale() -> None:
    llvm = LLVMBuilder().emit_llvm(
        _typed('int main() { return parseInt("1").value + int(parseDouble("2.0").value); }')
    )
    assert "call i64 @aether_string_byte_length" in llvm
    assert "@aether_string_data" in llvm
    assert '@.aether.locale.c' in llvm
    assert "call ptr @newlocale(i32 2" in llvm
    assert "call double @strtod_l" in llvm
    assert "@strlen" not in llvm


def test_parse_results_cross_module_boundaries_in_ast_and_native(tmp_path: Path) -> None:
    (tmp_path / "ParsingFacade.ae").write_text(
        "package ParsingFacade; "
        "public IntParseResult identifier(string text) { return parseInt(text); } "
        "public DoubleParseResult amount(string text) { return parseDouble(text); }",
        encoding="utf-8",
    )
    source = '''
from ParsingFacade import identifier;
from ParsingFacade import amount;
int main() {
    IntParseResult id = identifier("7");
    DoubleParseResult value = amount("12.5");
    println(id.status == ParseStatus.Success && id.value == 7);
    println(value.status == ParseStatus.Success && value.value == 12.5);
    return 0;
}
'''
    expected = "true\ntrue\n"
    assert run_aether(source, source_root=tmp_path).output == expected
    typed = prepare_typed_program(source, TypeChecker(source_root=tmp_path))
    stdout = StringIO()
    assert LLVMRunner().run(typed, stdout=stdout) == 0
    assert stdout.getvalue() == expected
