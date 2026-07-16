from __future__ import annotations

from io import StringIO
from pathlib import Path
import shutil

import pytest

from aether.backend.llvm import LLVMBuilder, LLVMRunner
from aether.errors import AetherTypeError
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
    "copy independent: true",
    "slice independent: true",
    "empty summary: true",
    "transactions:",
    "#1 | TransactionType.Income | 2026-07-01 | work | Salary | 1500.0",
    "#2 | TransactionType.Expense | 2026-07-15 | food | Dinner | 250.0",
]


def _source(name: str) -> str:
    return (EXAMPLE / name).read_text(encoding="utf-8")


def _typed(name: str):
    return prepare_typed_program(_source(name), TypeChecker(source_root=EXAMPLE))


def test_expense_tracker_ast_covers_ledger_reports_filtering_and_listing() -> None:
    result = run_aether(_source("Main.ae"), source_root=EXAMPLE)

    assert result.exit_code == 0
    assert result.output.splitlines() == MAIN_OUTPUT


def test_expense_tracker_for_in_transaction_is_read_only() -> None:
    source = """
from Transaction import Transaction;
void invalidReport(List<Transaction> transactions) {
    for Transaction transaction in transactions {
        transaction.amount = 0.0;
    }
}
int main() { return 0; }
"""
    with pytest.raises(AetherTypeError, match="Cannot mutate borrowed iteration element 'transaction'"):
        prepare_typed_program(source, TypeChecker(source_root=EXAMPLE))


@pytest.mark.skipif(shutil.which("clang") is None, reason="clang is required")
def test_expense_tracker_full_native_runs_list_of_struct_with_same_validations() -> None:
    stdout = StringIO()
    stderr = StringIO()
    typed = _typed("Main.ae")
    assert LLVMRunner().run(typed, stdout=stdout, stderr=stderr) == 0
    native_lines = stdout.getvalue().splitlines()

    assert native_lines[:12] == MAIN_OUTPUT[:12]
    assert native_lines[12].startswith("#1 | TransactionType.Income | 2026-07-01 | work | Salary | 1500")
    assert native_lines[13].startswith("#2 | TransactionType.Expense | 2026-07-15 | food | Dinner | 250")
    assert stderr.getvalue() == ""

    llvm = LLVMBuilder().emit_llvm(typed)
    assert "@aether_list_prepare_push" in llvm
    assert "ptrtoint (ptr getelementptr (%struct." in llvm
