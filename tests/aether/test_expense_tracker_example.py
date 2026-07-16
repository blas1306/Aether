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
    "numeric strings parsed: true",
    "invalid amount handled: true",
    "expense added: true",
    "non-positive rejected: true",
    "two transactions: true",
    "income total: true",
    "expense total: true",
    "balance: true",
    "expense filter: true",
    "copy equality: true",
    "slice equality: true",
    "contains transaction: true",
    "index transaction: true",
    "copy independent: true",
    "slice independent: true",
    "empty summary: true",
    "dynamic label: true",
    "label byte length: true",
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


def test_expense_tracker_consumes_real_add_arguments_without_persistence() -> None:
    result = run_aether(
        _source("Main.ae"),
        source_root=EXAMPLE,
        program_arguments=[
            "add", "expense", " 3 ", "19.95", " food ", " Lunch with friends "
        ],
    )

    assert result.exit_code == 0
    assert result.output.splitlines() == [
        "transaction added: food: Lunch with friends",
        "note: transactions are not persisted between processes",
    ]


def test_expense_tracker_reports_expected_cli_errors() -> None:
    cases = [
        (["add", "expense"], "insufficient arguments:"),
        (["add", "expense", "bad", "2.0", "food", "Dinner"], "invalid ID: bad"),
        (["add", "expense", "1", "bad", "food", "Dinner"], "invalid amount: bad"),
        (["unknown"], "unknown command: unknown"),
    ]
    for arguments, expected in cases:
        result = run_aether(
            _source("Main.ae"),
            source_root=EXAMPLE,
            program_arguments=arguments,
        )
        assert result.exit_code == 2
        assert result.output.startswith(expected)


def test_expense_tracker_persists_and_verifies_explicit_summary(tmp_path: Path) -> None:
    path = tmp_path / "summary.txt"
    result = run_aether(
        _source("Main.ae"),
        source_root=EXAMPLE,
        program_arguments=["persist-check", str(path)],
    )

    assert result.exit_code == 0
    assert result.output == "summary persisted and verified: true\n"
    assert path.read_bytes() == (
        b"income=1500.0\nexpenses=250.0\nbalance=1250.0\nverified\n"
    )


@pytest.mark.skipif(shutil.which("clang") is None, reason="clang is required")
def test_expense_tracker_native_persistence_check(tmp_path: Path) -> None:
    path = tmp_path / "native-summary.txt"
    stdout = StringIO()
    stderr = StringIO()
    assert LLVMRunner().run(
        _typed("Main.ae"),
        stdout=stdout,
        stderr=stderr,
        program_arguments=["persist-check", str(path)],
    ) == 0
    assert stdout.getvalue() == "summary persisted and verified: true\n"
    assert stderr.getvalue() == ""
    assert path.read_bytes().endswith(b"verified\n")


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

    assert native_lines[:20] == MAIN_OUTPUT[:20]
    assert native_lines[20].startswith("#1 | TransactionType.Income | 2026-07-01 | work | Salary | 1500")
    assert native_lines[21].startswith("#2 | TransactionType.Expense | 2026-07-15 | food | Dinner | 250")
    assert stderr.getvalue() == ""

    llvm = LLVMBuilder().emit_llvm(typed)
    assert "@aether_list_prepare_push" in llvm
    assert "ptrtoint (ptr getelementptr (%struct." in llvm
