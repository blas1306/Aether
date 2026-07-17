from __future__ import annotations

from dataclasses import replace
from io import StringIO
from pathlib import Path
import shutil

import pytest

from aether.backend.llvm import LLVMBuilder, LLVMRunner
from aether.capabilities import (
    BackendIdentity,
    Capability,
    CapabilityState,
    NATIVE_CAPABILITY_PROFILE,
    backend_capability_issues,
)
from aether.errors import AetherTypeError
from aether.ir import (
    FunctionType as IRFunctionType,
    IRCallIndirect,
    IRFunctionRef,
    IRInterpreter,
    IRVerificationError,
    IRVerifier,
    print_ir,
)
from aether.ir.optimizer import build_optimizer_pipeline
from aether.pipeline import IRBackend, lower_to_verified_ssa, prepare_typed_program
from aether.runner import run_aether
from aether.ssa import (
    SSACallIndirect,
    SSAFunctionRef,
    SSAPhi,
    SSAValue,
    SSAVerificationError,
    SSAVerifier,
    print_ssa,
)
from aether.ssa.optimizer import SSAOptimizerPipeline
from aether.typechecker import TypeChecker
from aether.types import FunctionType


_HAS_CLANG = shutil.which("clang") is not None


def _typed(source: str, *, source_root: Path | None = None):
    return prepare_typed_program(source, TypeChecker(source_root=source_root))


def _ir(source: str, *, source_root: Path | None = None):
    return IRBackend().lower_verified(_typed(source, source_root=source_root))


def _instructions(module):
    return [
        instruction
        for function in module.functions
        for block in function.blocks
        for instruction in block.instructions
    ]


def test_function_type_is_structural_exact_and_has_stable_text() -> None:
    zero = FunctionType((), "void")
    one = FunctionType(("double",), "double")
    many = FunctionType(("int", "double"), "int")

    assert str(zero) == "void()"
    assert str(one) == "double(double)"
    assert str(many) == "int(int, double)"
    assert one == FunctionType(("double",), "double")
    assert one != FunctionType(("int",), "double")


def test_callable_alias_zero_multiple_and_void_signatures_typecheck() -> None:
    source = """
alias Producer = int();
alias Combiner = int(int, int);
alias Action = void(int);
int produce() { return 3; }
int combine(int left, int right) { return left + right; }
void consume(int value) { println(value); }
int apply(Producer p, Combiner c, Action a) {
    int value = c(p(), 4);
    a(value);
    return value;
}
int main() { return apply(produce, combine, consume); }
"""
    typed = _typed(source)

    ast = run_aether(source)
    assert ast.exit_code == 7
    assert ast.output == "7\n"
    interpreter = IRInterpreter(_ir(source))
    assert interpreter.call("main") == 7
    assert interpreter.output == "7\n"
    if _HAS_CLANG:
        stdout = StringIO()
        assert LLVMRunner().run(typed, stdout=stdout, stderr=StringIO()) == 7
        assert stdout.getvalue() == "7\n"


@pytest.mark.parametrize(
    ("source", "message"),
    [
        (
            "double f(double x){return x;} double apply(int(int) g){return 0.0;} "
            "int main(){apply(f);return 0;}",
            "Cannot implicitly convert 'double(double)' to 'int(int)'",
        ),
        (
            "double f(double x,double y){return x+y;} "
            "double apply(double(double) g){return g(1.0);} "
            "int main(){apply(f);return 0;}",
            "Cannot implicitly convert 'double(double, double)' to 'double(double)'",
        ),
        (
            "double apply(double(double) f){return f(1.0, 2.0);} int main(){return 0;}",
            "Callable 'f' expects 1 arguments but got 2",
        ),
        (
            "double apply(double(double) f){return f(1.0);} "
            "int main(){double value=3.0; apply(value); return 0;}",
            "Cannot implicitly convert 'double' to 'double(double)'",
        ),
        (
            "double(double) maker(){ return square; } "
            "double square(double x){return x*x;} int main(){return 0;}",
            "Returning callable values is not supported yet",
        ),
        (
            "double apply(double(double) f){return f(1.0);} "
            "int main(){apply(sin); return 0;}",
            "Undefined variable 'sin'",
        ),
    ],
    ids=(
        "signature-types",
        "signature-arity",
        "indirect-call-arity",
        "non-callable",
        "callable-return",
        "builtin-reference",
    ),
)
def test_callable_type_errors_are_specific(source: str, message: str) -> None:
    with pytest.raises(AetherTypeError, match=message.replace("(", r"\(").replace(")", r"\)")):
        _typed(source)


def test_ast_callable_values_can_be_passed_stored_shadow_names_and_recurse() -> None:
    source = """
int factorial(int value) {
    if (value <= 1) { return 1; }
    return value * factorial(value - 1);
}
int apply(int(int) operation, int value) { return operation(value); }
int main() {
    int(int) factorial = factorial;
    return apply(factorial, 5);
}
"""

    assert run_aether(source).exit_code == 120


def test_user_function_reference_is_not_confused_with_same_named_builtin() -> None:
    source = """
double sin(double value) { return value + 1.0; }
double apply(double(double) operation, double value) { return operation(value); }
int main() { return int(apply(sin, 2.0)); }
"""

    assert run_aether(source).exit_code == 3
    assert IRInterpreter(_ir(source)).call("main") == 3
    assert "function_ref @sin" in print_ir(_ir(source))


def test_ir_ssa_and_optimizers_preserve_refs_indirect_calls_and_callable_phi() -> None:
    source = """
double plusOne(double value) { return value + 1.0; }
double timesTwo(double value) { return value * 2.0; }
double chooseAndApply(boolean chooseSecond, double value) {
    double(double) operation = plusOne;
    if (chooseSecond) { operation = timesTwo; }
    return operation(value);
}
int main() { return int(chooseAndApply(true, 4.0)); }
"""
    ir = _ir(source)
    ir_instructions = _instructions(ir)
    assert sum(isinstance(item, IRFunctionRef) for item in ir_instructions) == 2
    assert any(isinstance(item, IRCallIndirect) for item in ir_instructions)
    assert "function_ref @plusOne" in print_ir(ir)
    assert "call_indirect" in print_ir(ir)
    assert IRInterpreter(ir).call("main") == 8

    ssa = SSAVerifier(lower_to_verified_ssa(ir)).verify()
    ssa_instructions = _instructions(ssa)
    assert any(isinstance(item, SSAFunctionRef) for item in ssa_instructions)
    assert any(isinstance(item, SSACallIndirect) for item in ssa_instructions)
    assert any(
        isinstance(item, SSAPhi) and isinstance(item.result.type, IRFunctionType)
        for item in ssa_instructions
    )
    assert "call_indirect" in print_ssa(ssa)

    optimized = SSAVerifier(
        SSAOptimizerPipeline(iterative=True, verify_after_each=True).run(ssa)
    ).verify()
    optimized_instructions = _instructions(optimized)
    assert any(isinstance(item, SSAFunctionRef) for item in optimized_instructions)
    assert any(isinstance(item, SSACallIndirect) for item in optimized_instructions)

    for profile in ("O0", "O1", "O2"):
        effective = IRVerifier(build_optimizer_pipeline(profile).run(_ir(source))).verify()
        assert IRInterpreter(effective).call("main") == 8


def test_ir_and_ssa_verifiers_reject_invalid_indirect_callable_operands() -> None:
    source = """
double identity(double value) { return value; }
double apply(double(double) operation, double value) { return operation(value); }
int main() { return int(apply(identity, 2.0)); }
"""
    ir = _ir(source)
    indirect = next(item for item in _instructions(ir) if isinstance(item, IRCallIndirect))
    for function in ir.functions:
        for block in function.blocks:
            for index, instruction in enumerate(block.instructions):
                if instruction is indirect:
                    block.instructions[index] = replace(indirect, arguments=())

    with pytest.raises(IRVerificationError, match="expects 1 arguments, got 0"):
        IRVerifier(ir).verify()

    valid_ssa = lower_to_verified_ssa(_ir(source))
    ssa_indirect = next(
        item for item in _instructions(valid_ssa) if isinstance(item, SSACallIndirect)
    )
    missing = SSAValue("%missing_callable", ssa_indirect.callee.type)
    for function in valid_ssa.functions:
        for block in function.blocks:
            for index, instruction in enumerate(block.instructions):
                if instruction is ssa_indirect:
                    block.instructions[index] = replace(ssa_indirect, callee=missing)

    with pytest.raises(SSAVerificationError, match="Undefined value"):
        SSAVerifier(valid_ssa).verify()


def test_struct_by_value_and_void_callable_match_ast_ir_and_native() -> None:
    source = """
struct Point { int x; int y; }
int sum(Point point) { return point.x + point.y; }
void printPoint(Point point) { println(point.x, point.y); }
int apply(int(Point) operation, Point point) { return operation(point); }
void invoke(void(Point) action, Point point) { action(point); }
int main() {
    Point point = Point(2, 3);
    invoke(printPoint, point);
    return apply(sum, point);
}
"""
    ast = run_aether(source)
    assert ast.output == "23\n"
    assert ast.exit_code == 5

    ir = _ir(source)
    callable_types = [
        parameter.type
        for function in ir.functions
        for parameter in function.parameters
        if isinstance(parameter.type, IRFunctionType)
    ]
    assert {str(value) for value in callable_types} == {
        "int(struct Point)",
        "void(struct Point)",
    }
    interpreter = IRInterpreter(ir)
    assert interpreter.call("main") == 5
    assert interpreter.output == "23\n"

    if _HAS_CLANG:
        output = StringIO()
        assert LLVMRunner().run(_typed(source), stdout=output, stderr=StringIO()) == 5
        assert output.getvalue() == "23\n"


def test_imported_alias_homonyms_and_semantic_mangling_match_ast_native(
    tmp_path: Path,
) -> None:
    (tmp_path / "Left.ae").write_text(
        "package Left; public int transform(int value) { return value + 1; }",
        encoding="utf-8",
    )
    (tmp_path / "Right.ae").write_text(
        "package Right; public int transform(int value) { return value * 10; }",
        encoding="utf-8",
    )
    source = """
from Left import transform as increment;
import Right as R;
int apply(int(int) operation, int value) { return operation(value); }
int main() { return apply(increment, 2) + apply(R.transform, 3); }
"""
    typed = _typed(source, source_root=tmp_path)

    assert run_aether(source, source_root=tmp_path).exit_code == 33
    llvm = LLVMBuilder().emit_llvm(typed)
    assert "Left__function_9_transform" in llvm
    assert "Right__function_9_transform" in llvm
    if _HAS_CLANG:
        assert LLVMRunner().run(typed) == 33


def test_private_imported_function_remains_inaccessible_as_callable(tmp_path: Path) -> None:
    (tmp_path / "Hidden.ae").write_text(
        "package Hidden; private int secret(int value) { return value; }",
        encoding="utf-8",
    )
    source = "from Hidden import secret; int apply(int(int) f){return f(1);}"

    with pytest.raises(AetherTypeError, match="not public"):
        _typed(source, source_root=tmp_path)


def test_native_capability_profile_accepts_typed_top_level_subset() -> None:
    source = """
int increment(int value) { return value + 1; }
int apply(int(int) operation, int value) { return operation(value); }
int main() { return apply(increment, 3); }
"""
    typed = _typed(source)

    assert NATIVE_CAPABILITY_PROFILE.support_for(Capability.FUNCTION_VALUES).state is CapabilityState.PARTIAL
    assert not any(
        issue.requirement.capability is Capability.FUNCTION_VALUES
        for issue in backend_capability_issues(typed, BackendIdentity.NATIVE)
    )
    assert "call i32 %" in LLVMBuilder().emit_llvm(typed)
