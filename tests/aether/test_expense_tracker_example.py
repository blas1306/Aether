from __future__ import annotations

from io import StringIO
from pathlib import Path
import shutil

import pytest

from aether.backend.llvm import LLVMBackendError, LLVMRunner
from aether.pipeline import prepare_typed_program
from aether.runner import run_aether
from aether.typechecker import TypeChecker


ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = ROOT / "examples" / "expense_tracker"
MAIN_OUTPUT = [
    "income added: true",
    "expense added: true",
    "non-positive rejected: true",
    "two transactions: true",
    "income total: true",
    "expense total: true",
    "balance: true",
    "expense filter: true",
    "empty summary: true",
    "transactions:",
    "#1 | TransactionType.Income | 2026-07-01 | work | Salary | 1500.0",
    "#2 | TransactionType.Expense | 2026-07-15 | food | Dinner | 250.0",
]
NATIVE_SUBSET_OUTPUT = [
    "native enum in struct: true",
    "native string field: Dinner",
    "native income: true",
    "native expenses: true",
    "native balance: true",
]


def _source(name: str) -> str:
    return (EXAMPLE / name).read_text(encoding="utf-8")


def _typed(name: str):
    return prepare_typed_program(_source(name), TypeChecker(source_root=EXAMPLE))


def test_expense_tracker_ast_covers_ledger_reports_filtering_and_listing() -> None:
    result = run_aether(_source("Main.ae"), source_root=EXAMPLE)

    assert result.exit_code == 0
    assert result.output.splitlines() == MAIN_OUTPUT


def test_expense_tracker_native_subset_matches_ast() -> None:
    ast_result = run_aether(_source("NativeSubset.ae"), source_root=EXAMPLE)

    assert ast_result.output.splitlines() == NATIVE_SUBSET_OUTPUT

    if shutil.which("clang") is None:
        pytest.skip("clang is required")
    stdout = StringIO()
    stderr = StringIO()
    assert LLVMRunner().run(_typed("NativeSubset.ae"), stdout=stdout, stderr=stderr) == 0
    assert stdout.getvalue().splitlines() == NATIVE_SUBSET_OUTPUT
    assert stderr.getvalue() == ""


@pytest.mark.skipif(shutil.which("clang") is None, reason="clang is required")
def test_expense_tracker_full_native_exposes_list_of_struct_runtime_gap() -> None:
    with pytest.raises(
        LLVMBackendError,
        match=r"LLVM backend does not know the size of struct .*Transaction",
    ):
        LLVMRunner().run(_typed("Main.ae"))
