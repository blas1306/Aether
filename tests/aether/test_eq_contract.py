from __future__ import annotations

from io import StringIO
from pathlib import Path
import shutil
import subprocess

import pytest

from aether.backend.llvm import LLVMBackend, LLVMRunner
from aether.capabilities import BackendCapabilityError, Capability
from aether.equality import aether_values_equal
from aether.errors import AetherTypeError
from aether.ir import IRCompareOp, IRInterpreter, IRVerifier
from aether.ir.optimizer import build_optimizer_pipeline
from aether.pipeline import IRBackend, prepare_typed_program
from aether.runner import run_aether
from aether.ssa import GeneralSSABuilder
from aether.ssa.optimizer import SSAOptimizerPipeline
from aether.string_value import StringValue
from aether.typechecker import TypeChecker
from aether.types import AetherValue


def _typed(source: str):
    return prepare_typed_program(source, TypeChecker())


def _all_outputs(source: str) -> tuple[str, str, str]:
    ast_output = run_aether(source).output
    ir = IRBackend().lower_verified(_typed(source))
    interpreter = IRInterpreter(ir)
    assert interpreter.call("main") == 0
    if shutil.which("clang") is None:
        pytest.skip("clang is required")
    stdout = StringIO()
    assert LLVMRunner().run(_typed(source), stdout=stdout) == 0
    return ast_output, interpreter.output, stdout.getvalue()


@pytest.mark.parametrize(
    ("source", "message"),
    [
        (
            "class Box {} int main(){ Box a=Box(); Box b=Box(); println(a==b); return 0; }",
            "Type Box does not define equality.",
        ),
        (
            "class Box {} int main(){ List<Box> xs={}; Box x=Box(); println(xs.contains(x)); return 0; }",
            "List<Box>.contains requires Eq(Box).",
        ),
        (
            "int f(int x){return x;} int main(){ int(int) fn=f; println(fn==fn); return 0; }",
            "Type int(int) does not define equality.",
        ),
        (
            "class Box {} struct Bad { Box value; } int main(){ Bad a=Bad(Box()); println(a==a); return 0; }",
            "Type Bad does not define equality.",
        ),
    ],
)
def test_eq_rejects_types_without_a_semantic_contract(source: str, message: str) -> None:
    with pytest.raises(AetherTypeError, match=message.replace("(", r"\(").replace(")", r"\)")):
        _typed(source)


def test_struct_collections_copy_slice_search_and_nested_eq_match_all_backends() -> None:
    source = r'''
enum Kind { Food, Travel }
struct Transaction { int id; string label; Kind kind; }
int main() {
    const List<Transaction> original = {
        Transaction(1, "coffee", Kind.Food),
        Transaction(2, "bus", Kind.Travel)
    };
    List<Transaction> copied = original.copy();
    List<Transaction> sliced = original[0:2];
    println(original == copied);
    println(original == sliced);
    println(copied.contains(Transaction(2, "bus", Kind.Travel)));
    println(copied.indexOf(Transaction(2, "bus", Kind.Travel)));
    copied[1] = Transaction(3, "train", Kind.Travel);
    println(original != copied);
    for (Transaction item in original) {
        println(sliced.contains(item));
    }
    List<List<int>> nestedA = {{1}, {2}};
    List<List<int>> nestedB = {{1}, {2}};
    Array<List<string>> mixedA = {{"x"}};
    Array<List<string>> mixedB = {{"x"}};
    println(nestedA == nestedB);
    println(mixedA == mixedB);
    return 0;
}
'''
    expected = "true\ntrue\ntrue\n1\ntrue\ntrue\ntrue\ntrue\ntrue\n"
    assert _all_outputs(source) == (expected, expected, expected)


def test_ieee_equality_nan_and_signed_zero_float_is_rejected_by_native_profile() -> None:
    source = """
int main() {
    double nan = 0.0 / 0.0;
    double positive = 0.0;
    double negative = -0.0;
    float floatNan = float(nan);
    float floatPositive = float(positive);
    float floatNegative = float(negative);
    List<double> values = {nan, positive};
    println(nan == nan);
    println(nan != nan);
    println(positive == negative);
    println(values.contains(nan));
    println(values.indexOf(negative));
    println(floatNan != floatNan);
    println(floatPositive == floatNegative);
    return 0;
}
"""
    expected = "false\ntrue\ntrue\nfalse\n1\ntrue\ntrue\n"
    assert run_aether(source).output == expected
    interpreter = IRInterpreter(IRBackend().lower_verified(_typed(source)))
    assert interpreter.call("main") == 0
    assert interpreter.output == expected

    with pytest.raises(BackendCapabilityError) as captured:
        LLVMRunner().run(_typed(source), stdout=StringIO())

    issue = next(
        issue
        for issue in captured.value.issues
        if issue.requirement.capability is Capability.PRIMITIVE_TYPES
    )
    assert "type 'float' has no stable LLVM/native ABI" in (issue.requirement.detail or "")


def test_string_eq_dispatcher_is_handle_fast_and_embedded_nul_safe() -> None:
    shared = StringValue.from_utf8(b"a\0b")
    distinct = StringValue.from_utf8(b"a\0b")
    different = StringValue.from_utf8(b"a\0c")
    assert aether_values_equal(AetherValue("string", shared), AetherValue("string", shared))
    assert aether_values_equal(AetherValue("string", shared), AetherValue("string", distinct))
    assert not aether_values_equal(AetherValue("string", shared), AetherValue("string", different))


def test_ir_keeps_typed_collection_equality_and_memory_read_effects() -> None:
    ir = IRBackend().lower_verified(
        _typed("int main(){ List<List<int>> a={{1}}; List<List<int>> b={{1}}; println(a==b); return 0; }")
    )
    comparison = next(
        instruction
        for function in ir.functions
        for block in function.blocks
        for instruction in block.instructions
        if isinstance(instruction, IRCompareOp)
    )
    assert str(comparison.left.type) == "list<list<int>>"
    assert comparison.reads_memory and not comparison.has_side_effects and not comparison.may_trap


@pytest.mark.skipif(shutil.which("clang") is None, reason="clang is required")
def test_imported_struct_alias_keeps_nominal_eq_and_native_helper_identity(tmp_path: Path) -> None:
    (tmp_path / "Ledger.ae").write_text(
        """
package Ledger;
public struct Transaction { int id; string label; }
public Transaction make(int id, string label) { return Transaction(id, label); }
""",
        encoding="utf-8",
    )
    source = """
from Ledger import Transaction;
from Ledger import make;
alias Tx = Transaction;
int main() {
    Tx first = make(1, "coffee");
    Tx second = make(1, "coffee");
    List<Tx> values = {first};
    println(first == second);
    println(values.contains(second));
    return 0;
}
"""
    checker = TypeChecker(source_root=tmp_path)
    typed = prepare_typed_program(source, checker)
    assert run_aether(source, source_root=tmp_path).output == "true\ntrue\n"
    stdout = StringIO()
    assert LLVMRunner().run(typed, stdout=stdout) == 0
    assert stdout.getvalue() == "true\ntrue\n"


@pytest.mark.skipif(shutil.which("clang") is None, reason="clang is required")
@pytest.mark.parametrize("profile", ["O0", "O1", "O2"])
def test_eq_survives_optimizer_profiles_and_real_clang(profile: str, tmp_path: Path) -> None:
    source = "struct Item { int n; string s; } int main(){ List<Item> a={Item(1,\"x\")}; List<Item> b=a.copy(); println(a==b); println(a.contains(Item(1,\"x\"))); return 0; }"
    ir = IRBackend().lower_verified(_typed(source))
    optimized_ir = IRVerifier(build_optimizer_pipeline(profile).run(ir)).verify()
    ssa = GeneralSSABuilder().build(optimized_ir)
    optimized_ssa = SSAOptimizerPipeline(verify_after_each=True).run(ssa)
    llvm = LLVMBackend().emit(optimized_ssa)
    assert llvm.count("define private i1 @__ae_eq_struct_4_Item") == 1
    llvm_path = tmp_path / f"eq-{profile}.ll"
    executable = tmp_path / f"eq-{profile}"
    llvm_path.write_text(llvm, encoding="utf-8")
    compiled = subprocess.run(
        [shutil.which("clang") or "clang", str(llvm_path), "-o", str(executable)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert compiled.returncode == 0, compiled.stderr
    completed = subprocess.run([str(executable)], check=False, capture_output=True, text=True)
    assert completed.returncode == 0
    assert completed.stdout == "true\ntrue\n"
