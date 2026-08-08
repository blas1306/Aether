from __future__ import annotations

from io import StringIO
from pathlib import Path
import shutil
import subprocess

import pytest

from aether.backend.llvm import LLVMBackend, LLVMRunner
from aether.errors import AetherTypeError
from aether.ir import (
    BoolType,
    EnumType,
    IRBasicBlock,
    IRCompareOp,
    IRConst,
    IREnumConstant,
    IRFunction,
    IRModule,
    IRReturn,
    IRValue,
    IRVerificationError,
    IRVerifier,
)
from aether.ir.optimizer import build_optimizer_pipeline
from aether.pipeline import IRBackend, lower_to_verified_ssa, prepare_typed_program
from aether.runner import run_aether
from aether.ssa import (
    GeneralSSABuilder,
    SSABasicBlock,
    SSABranch,
    SSAConst,
    SSAFunction,
    SSAJump,
    SSAModule,
    SSAPhi,
    SSAReturn,
    SSAValue,
    SSAVerificationError,
    SSAVerifier,
)
from aether.ssa.optimizer import SSAOptimizerPipeline
from aether.typechecker import TypeChecker
from aether.types import EnumIdentity, EnumValue


LOCAL_SOURCE = """
enum RootStatus {
    Converged,
    MaxIterations,
    InvalidInterval,
    ZeroDerivative
}

struct RootResult {
    double value;
    int iterations;
    RootStatus status;
}

RootStatus selectStatus(boolean converged) {
    RootStatus status = RootStatus.MaxIterations;
    if (converged) {
        status = RootStatus.Converged;
    }
    return status;
}

RootResult solve(boolean converged) {
    return RootResult(1.5, 3, selectStatus(converged));
}

int main() {
    RootStatus local = selectStatus(true);
    RootResult result = solve(false);
    println(local);
    println(local == RootStatus.Converged);
    println(result.status);
    println(result.status != local);
    return 0;
}
"""

EXPECTED_LOCAL = (
    "RootStatus.Converged\n"
    "true\n"
    "RootStatus.MaxIterations\n"
    "true\n"
)


def _typed(source: str, *, source_root: Path | None = None):
    return prepare_typed_program(source, TypeChecker(source_root=source_root))


def test_ast_enum_value_keeps_nominal_runtime_identity_and_discriminant() -> None:
    result = run_aether(
        "enum Status { Ready, Waiting } Status s = Status.Waiting;"
    )

    value = result.env["s"].value
    assert isinstance(value, EnumValue)
    assert value.enum_id == EnumIdentity("__entry__", "Status")
    assert value.member_id == 1
    assert value.discriminant == 1


def test_enum_lowering_preserves_nominal_type_constant_and_phi() -> None:
    typed = _typed(LOCAL_SOURCE)
    ir = IRBackend().lower_verified(typed)
    enum_constants = [
        instruction
        for function in ir.functions
        for block in function.blocks
        for instruction in block.instructions
        if isinstance(instruction, IRConst)
        and isinstance(instruction.value, IREnumConstant)
    ]

    assert enum_constants
    assert all(isinstance(instruction.result.type, EnumType) for instruction in enum_constants)
    assert {instruction.value.discriminant for instruction in enum_constants} >= {0, 1}

    ssa = lower_to_verified_ssa(typed)
    enum_phis = [
        instruction
        for function in ssa.functions
        for block in function.blocks
        for instruction in block.instructions
        if isinstance(instruction, SSAPhi) and isinstance(instruction.result.type, EnumType)
    ]
    assert enum_phis
    assert all(
        value.type == instruction.result.type
        for instruction in enum_phis
        for _block, value in instruction.incoming
    )
    llvm = LLVMBackend().emit(ssa)
    assert "define i32 @selectStatus(i1" in llvm
    assert "phi i32" in llvm


def test_enum_constant_equality_folds_without_erasing_result_type() -> None:
    source = """
enum Status { Ready, Waiting }
int main() {
    println(Status.Ready == Status.Ready);
    println(Status.Ready != Status.Waiting);
    return 0;
}
"""
    optimized = SSAOptimizerPipeline(verify_after_each=True).run(
        lower_to_verified_ssa(_typed(source))
    )
    bool_constants = [
        instruction
        for function in optimized.functions
        for block in function.blocks
        for instruction in block.instructions
        if isinstance(instruction, SSAConst)
        and isinstance(instruction.result.type, BoolType)
    ]
    assert sum(instruction.value is True for instruction in bool_constants) >= 2


@pytest.mark.skipif(shutil.which("clang") is None, reason="clang is required")
def test_native_enum_arrays_lists_and_typed_callable_abi() -> None:
    source = """
enum Status { Ready, Waiting }
alias StatusCallable = Function<(Status), Status>;

Status keep(Status value) { return value; }
Status apply(StatusCallable callable, Status value) { return callable(value); }

int main() {
    const Status fixed = Status.Ready;
    Array<Status> array = {Status.Ready, Status.Waiting};
    List<Status> list = {Status.Waiting};
    list.push(array[0]);
    println(apply(keep, array[1]) == Status.Waiting);
    println(list.contains(Status.Ready));
    println(list[0]);
    println(fixed == Status.Ready);
    return 0;
}
"""
    expected = "true\ntrue\nStatus.Waiting\ntrue\n"
    assert run_aether(source).output == expected
    stdout = StringIO()
    stderr = StringIO()
    assert LLVMRunner().run(_typed(source), stdout=stdout, stderr=stderr) == 0
    assert stdout.getvalue() == expected
    assert stderr.getvalue() == ""


def test_ir_verifier_rejects_invalid_enum_constant_and_cross_enum_comparison() -> None:
    status = EnumType("Status", ("Ready", "Waiting"), "Status")
    other = EnumType("Other", ("Ready",), "Other")
    invalid = IRValue("invalid", status)
    module = IRModule(
        [
            IRFunction(
                "main",
                [],
                status,
                [
                    IRBasicBlock(
                        "entry",
                        [
                            IRConst(invalid, IREnumConstant("Status", "Waiting", 1, 7)),
                            IRReturn(invalid),
                        ],
                    )
                ],
            )
        ]
    )
    with pytest.raises(IRVerificationError, match="discriminant"):
        IRVerifier(module).verify()

    left = IRValue("left", status)
    right = IRValue("right", other)
    compared = IRValue("compared", BoolType())
    mixed = IRModule(
        [
            IRFunction(
                "main",
                [],
                BoolType(),
                [
                    IRBasicBlock(
                        "entry",
                        [
                            IRConst(left, IREnumConstant("Status", "Ready", 0, 0)),
                            IRConst(right, IREnumConstant("Other", "Ready", 0, 0)),
                            IRCompareOp(compared, "eq", left, right),
                            IRReturn(compared),
                        ],
                    )
                ],
            )
        ]
    )
    with pytest.raises(IRVerificationError, match="compatible operands"):
        IRVerifier(mixed).verify()


def test_imported_homonymous_enums_remain_nominally_distinct(tmp_path: Path) -> None:
    (tmp_path / "First.ae").write_text(
        "package First; public enum Status { Ready }",
        encoding="utf-8",
    )
    (tmp_path / "Second.ae").write_text(
        "package Second; public enum Status { Ready }",
        encoding="utf-8",
    )
    source = """
from First import Status as FirstStatus;
from Second import Status as SecondStatus;
FirstStatus value = SecondStatus.Ready;
"""
    with pytest.raises(AetherTypeError, match="Cannot implicitly convert"):
        run_aether(source, source_root=tmp_path)


def test_ssa_verifier_rejects_phi_between_distinct_nominal_enums() -> None:
    first = EnumType("First", ("Ready",), "First")
    second = EnumType("Second", ("Ready",), "Second")
    condition = SSAValue("condition", BoolType())
    left = SSAValue("left", first)
    right = SSAValue("right", second)
    merged = SSAValue("merged", first)
    module = SSAModule(
        [
            SSAFunction(
                "main",
                [],
                first,
                [
                    SSABasicBlock(
                        "entry",
                        [
                            SSAConst(condition, True),
                            SSAConst(left, IREnumConstant("First", "Ready", 0, 0)),
                            SSABranch(condition, "left_block", "right_block"),
                        ],
                    ),
                    SSABasicBlock("left_block", [SSAJump("merge")]),
                    SSABasicBlock(
                        "right_block",
                        [
                            SSAConst(right, IREnumConstant("Second", "Ready", 0, 0)),
                            SSAJump("merge"),
                        ],
                    ),
                    SSABasicBlock(
                        "merge",
                        [
                            SSAPhi(
                                merged,
                                (("left_block", left), ("right_block", right)),
                            ),
                            SSAReturn(merged),
                        ],
                    ),
                ],
            )
        ]
    )
    with pytest.raises(SSAVerificationError, match="Phi.*type mismatch"):
        SSAVerifier(module).verify()


@pytest.mark.skipif(shutil.which("clang") is None, reason="clang is required")
def test_native_enum_locals_returns_struct_fields_equality_and_print_match_ast() -> None:
    assert run_aether(LOCAL_SOURCE).output == EXPECTED_LOCAL
    stdout = StringIO()
    stderr = StringIO()
    assert LLVMRunner().run(_typed(LOCAL_SOURCE), stdout=stdout, stderr=stderr) == 0
    assert stdout.getvalue() == EXPECTED_LOCAL
    assert stderr.getvalue() == ""


@pytest.mark.skipif(shutil.which("clang") is None, reason="clang is required")
def test_native_enum_cross_module_aliases_signatures_and_homonyms(tmp_path: Path) -> None:
    (tmp_path / "Alpha.ae").write_text(
        """
package Alpha;
public enum Status { Ready, Waiting }
public Status keep(Status value) { return value; }
""",
        encoding="utf-8",
    )
    (tmp_path / "Beta.ae").write_text(
        """
package Beta;
public enum Status { Ready, Failed }
public Status fail() { return Status.Failed; }
""",
        encoding="utf-8",
    )
    source = """
from Alpha import Status as AlphaStatus;
from Alpha import keep;
from Beta import Status as BetaStatus;
from Beta import fail;
import Alpha as A;

int main() {
    AlphaStatus alpha = keep(AlphaStatus.Waiting);
    BetaStatus beta = fail();
    println(alpha);
    println(beta);
    println(alpha == AlphaStatus.Waiting);
    println(beta == BetaStatus.Failed);
    println(A.Status.Ready);
    return 0;
}
"""
    expected = "Status.Waiting\nStatus.Failed\ntrue\ntrue\nStatus.Ready\n"
    assert run_aether(source, source_root=tmp_path).output == expected

    stdout = StringIO()
    stderr = StringIO()
    assert LLVMRunner().run(
        _typed(source, source_root=tmp_path), stdout=stdout, stderr=stderr
    ) == 0
    assert stdout.getvalue() == expected
    assert stderr.getvalue() == ""


@pytest.mark.skipif(shutil.which("clang") is None, reason="clang is required")
@pytest.mark.parametrize("profile", ["O0", "O1", "O2"])
def test_enum_survives_ir_optimization_profiles_and_real_clang(
    profile: str,
    tmp_path: Path,
) -> None:
    typed = _typed(LOCAL_SOURCE)
    ir = IRBackend().lower_verified(typed)
    optimized_ir = IRBackend().optimize_verified(
        ir,
        optimizer=build_optimizer_pipeline(profile),
    )
    ssa = GeneralSSABuilder().build(optimized_ir)
    optimized_ssa = SSAOptimizerPipeline(verify_after_each=True).run(ssa)
    llvm = LLVMBackend().emit(optimized_ssa)
    llvm_path = tmp_path / f"enum-{profile}.ll"
    executable = tmp_path / f"enum-{profile}"
    llvm_path.write_text(llvm, encoding="utf-8")
    compiled = subprocess.run(
        [shutil.which("clang") or "clang", str(llvm_path), "-o", str(executable)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert compiled.returncode == 0, compiled.stderr
    completed = subprocess.run(
        [str(executable)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0
    assert completed.stdout == EXPECTED_LOCAL
    assert completed.stderr == ""
