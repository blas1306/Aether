from __future__ import annotations

from io import StringIO
from pathlib import Path
import shutil
import subprocess

import pytest

from aether.backend.llvm import LLVMBuilder, LLVMRunner
from aether.pipeline import IRBackend, prepare_typed_program
from aether.runner import run_aether
from aether.typechecker import TypeChecker


ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = ROOT / "examples" / "expense_tracker"


def _quote(value: str) -> str:
    return (
        '"'
        + value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\t", "\\t")
        + '"'
    )


def _typed(source: str):
    return prepare_typed_program(source, TypeChecker(source_root=EXAMPLE))


def _ledger(fields: list[tuple[str, str, str]] | None = None, *, count: str = "1") -> str:
    if fields is None:
        fields = [
            ("id", "int", "7"),
            ("type", "enum", "Expense"),
            ("amount", "double", "19.95"),
            ("category", "string", "food"),
            ("description", "string", "Lunch"),
            ("date", "string", "2026-07-16"),
        ]
    chunks = [
        "AETHER-PERSISTENCE\n",
        "format-version 1\n",
        "application aether.expense-tracker\n",
        "schema expense-ledger\n",
        "schema-revision 1\n",
        "schema-min-reader 1\n",
        f"record-count {count}\n",
        "end-header\n",
    ]
    if count != "0":
        chunks.append(f"record transaction {len(fields)}\n")
        for name, type_name, payload in fields:
            chunks.append(
                f"field {name} {type_name} {len(payload.encode('utf-8'))}\n{payload}\n"
            )
        chunks.append("end-record\n")
    chunks.append("end-file\n")
    return "".join(chunks)


ROUNDTRIP_SOURCE = '''
from Persistence import LedgerDecodeResult;
from Persistence import LedgerEncodeResult;
from Persistence import LedgerStatus;
from Persistence import decodeLedger;
from Persistence import encodeLedger;
from Transaction import Transaction;
from Transaction import TransactionType;

int main() {
    List<Transaction> values = {};
    values.push(Transaction(
        -2147483648, TransactionType.Expense, "línea 1\nlínea 2\0tail",
        19.95, "comida=almuerzo:🙂", "2026-07-16"
    ));
    values.push(Transaction(
        2147483647, TransactionType.Income, "", 1.0e-200, "", ""
    ));
    LedgerEncodeResult encoded = encodeLedger(values);
    LedgerDecodeResult decoded = decodeLedger(encoded.content);
    LedgerDecodeResult trailing = decodeLedger(encoded.content + "x");
    LedgerEncodeResult reencoded = encodeLedger(decoded.transactions);
    println(encoded.status == LedgerStatus.Success);
    println(decoded.status == LedgerStatus.Success);
    println(decoded.transactions == values);
    println(reencoded.content == encoded.content);
    println(decoded.byteOffset == 0);
    println(trailing.status == LedgerStatus.TrailingData &&
        trailing.byteOffset == encoded.content.byteLength &&
        trailing.transactions.length == 0);
    return 0;
}
'''


def test_alpt1_roundtrip_canonical_ast_ir_and_native() -> None:
    ast = run_aether(ROUNDTRIP_SOURCE, source_root=EXAMPLE)
    assert ast.exit_code == 0
    assert ast.output == "true\n" * 6

    backend = IRBackend()
    backend.run(_typed(ROUNDTRIP_SOURCE))
    assert backend.output == ast.output

    if shutil.which("clang") is not None:
        stdout = StringIO()
        assert LLVMRunner().run(_typed(ROUNDTRIP_SOURCE), stdout=stdout) == 0
        assert stdout.getvalue() == ast.output


def test_alpt1_empty_ledger_and_unknown_field_are_valid() -> None:
    unknown_fields = [
        ("date", "string", "2026-07-16"),
        ("description", "string", "Lunch"),
        ("future-note", "opaque", "line 1\nline 2\0x"),
        ("amount", "double", "19.95"),
        ("type", "enum", "Expense"),
        ("category", "string", "food"),
        ("id", "int", "7"),
    ]
    source = f'''
from Persistence import LedgerDecodeResult;
from Persistence import LedgerEncodeResult;
from Persistence import LedgerStatus;
from Persistence import decodeLedger;
from Persistence import encodeLedger;
from Transaction import Transaction;
int main() {{
    List<Transaction> values = {{}};
    LedgerEncodeResult encoded = encodeLedger(values);
    LedgerDecodeResult empty = decodeLedger({_quote(_ledger(count="0"))});
    LedgerDecodeResult extended = decodeLedger({_quote(_ledger(unknown_fields))});
    println(empty.status == LedgerStatus.Success && empty.transactions.length == 0);
    println(encoded.status == LedgerStatus.Success && encoded.content == {_quote(_ledger(count="0"))});
    println(extended.status == LedgerStatus.Success && extended.transactions.length == 1);
    println(extended.transactions[0].date == "2026-07-16");
    return 0;
}}
'''
    assert run_aether(source, source_root=EXAMPLE).output == "true\n" * 4


def test_alpt1_corruption_matrix_is_fail_closed() -> None:
    base_fields = [
        ("id", "int", "7"),
        ("type", "enum", "Expense"),
        ("amount", "double", "19.95"),
        ("category", "string", "food"),
        ("description", "string", "Lunch"),
        ("date", "string", "2026-07-16"),
    ]
    duplicate = base_fields + [("id", "int", "8")]
    cases = [
        ("", "EmptyFile"),
        (_ledger().replace("AETHER-PERSISTENCE", "AETHER-PERSISTENCE-X", 1), "InvalidMagic"),
        (_ledger().replace("format-version 1", "format-version 2", 1), "UnsupportedFormatVersion"),
        (_ledger().replace("schema expense-ledger", "schema other-ledger", 1), "UnsupportedSchema"),
        (_ledger().replace("schema-revision 1", "schema-revision 2", 1), "UnsupportedSchemaRevision"),
        (_ledger().replace("schema-min-reader 1", "schema-min-reader 2", 1), "IncompatibleReader"),
        (_ledger().replace("record-count 1", "record-count 01", 1), "InvalidRecordCount"),
        (_ledger().replace("record-count 1", "record-count 999999999999", 1), "InvalidRecordCount"),
        (_ledger().replace("application aether.expense-tracker\n", "application aether.expense-tracker\napplication aether.expense-tracker\n", 1), "DuplicateHeader"),
        (_ledger().replace("end-header\n", "optional-note enabled\noptional-note enabled\nend-header\n", 1), "DuplicateHeader"),
        (_ledger(base_fields[:-1]), "MissingField"),
        (_ledger(duplicate), "DuplicateField"),
        (_ledger([(n, "string" if n == "id" else t, p) for n, t, p in base_fields]), "TypeMismatch"),
        (_ledger([("id", "int", "01"), *base_fields[1:]]), "InvalidInteger"),
        (_ledger([("id", "int", "2147483648"), *base_fields[1:]]), "InvalidInteger"),
        (_ledger([base_fields[0], ("type", "enum", "expense"), *base_fields[2:]]), "InvalidEnum"),
        (_ledger([*base_fields[:2], ("amount", "double", "NaN"), *base_fields[3:]]), "InvalidDouble"),
        (_ledger([*base_fields[:2], ("amount", "double", "1e309"), *base_fields[3:]]), "InvalidDouble"),
        (_ledger([*base_fields[:2], ("amount", "double", "0"), *base_fields[3:]]), "InvalidDouble"),
        (_ledger() + " ", "TrailingData"),
        (_ledger().replace("field id int 1", "field id int -1", 1), "InvalidLength"),
        (_ledger().replace("field id int 1", "field id int 999999999999", 1), "InvalidLength"),
        (_ledger().replace("field description string 5", "field description string 500", 1), "UnexpectedEnd"),
        (_ledger().replace("7\nfield type", "7Xfield type", 1), "InvalidFieldHeader"),
        (_ledger().replace("record transaction 6", "record other 6", 1), "InvalidRecordHeader"),
        (_ledger().replace("end-record\n", "", 1), "IncompleteRecord"),
        (_ledger()[:-12], "UnexpectedEnd"),
    ]
    statements = []
    for index, (content, expected) in enumerate(cases):
        statements.append(
            f"LedgerDecodeResult r{index} = decodeLedger({_quote(content)});\n"
            f"println(r{index}.status == LedgerStatus.{expected} && "
            f"r{index}.transactions.length == 0);"
        )
    source = '''
from Persistence import LedgerDecodeResult;
from Persistence import LedgerStatus;
from Persistence import decodeLedger;
from Transaction import Transaction;
int main() {
''' + "\n".join(statements) + '''
    return 0;
}
'''
    result = run_aether(source, source_root=EXAMPLE)
    assert result.exit_code == 0
    assert result.output == "true\n" * len(cases)


def test_alpt1_encoder_rejects_nonfinite_and_signed_zero_structurally() -> None:
    source = '''
from Persistence import LedgerEncodeResult;
from Persistence import LedgerStatus;
from Persistence import encodeLedger;
from Transaction import Transaction;
from Transaction import TransactionType;
int main() {
    List<Transaction> values = {};
    values.push(Transaction(1, TransactionType.Expense, "x", 1.0 / 0.0, "c", "d"));
    LedgerEncodeResult infinity = encodeLedger(values);
    values.clear();
    values.push(Transaction(2, TransactionType.Expense, "x", 0.0 / 0.0, "c", "d"));
    LedgerEncodeResult nan = encodeLedger(values);
    values.clear();
    values.push(Transaction(3, TransactionType.Expense, "x", -0.0, "c", "d"));
    LedgerEncodeResult zero = encodeLedger(values);
    println(infinity.status == LedgerStatus.InvalidDouble && infinity.content == "");
    println(nan.status == LedgerStatus.InvalidDouble && nan.content == "");
    println(zero.status == LedgerStatus.InvalidDouble && zero.content == "");
    return 0;
}
'''
    assert run_aether(source, source_root=EXAMPLE).output == "true\n" * 3


def test_alpt1_save_encode_failure_does_not_touch_filesystem(tmp_path: Path) -> None:
    path = tmp_path / "encode-failure.alpt"
    path.write_bytes(b"existing-ledger")
    source = f'''
from Persistence import LedgerStatus;
from Persistence import saveLedger;
from Transaction import Transaction;
from Transaction import TransactionType;
int main() {{
    List<Transaction> values = {{}};
    values.push(Transaction(1, TransactionType.Expense, "bad", 1.0 / 0.0, "c", "d"));
    println(saveLedger({_quote(str(path))}, values) == LedgerStatus.InvalidDouble);
    return 0;
}}
'''
    assert run_aether(source, source_root=EXAMPLE).output == "true\n"
    assert path.read_bytes() == b"existing-ledger"


def test_alpt1_load_maps_invalid_utf8_and_save_is_not_attempted(tmp_path: Path) -> None:
    path = tmp_path / "invalid.alpt"
    path.write_bytes(b"AETHER-PERSISTENCE\n\xff")
    source = (EXAMPLE / "Main.ae").read_text(encoding="utf-8")
    before = path.read_bytes()
    result = run_aether(
        source,
        source_root=EXAMPLE,
        program_arguments=[
            str(path), "add", "expense", "1", "2.0", "food", "Lunch", "2026-07-16"
        ],
    )
    assert result.exit_code == 3
    assert "LedgerStatus.InvalidUtf8" in result.output
    assert path.read_bytes() == before


@pytest.mark.skipif(shutil.which("clang") is None, reason="clang is required")
def test_alpt1_native_two_process_dogfood(tmp_path: Path) -> None:
    ledger = tmp_path / "native.alpt"
    ast_ledger = tmp_path / "ast.alpt"
    typed = _typed((EXAMPLE / "Main.ae").read_text(encoding="utf-8"))
    commands = [
        [str(ledger), "add", "expense", "1", "20.5", "food", "Dinner", "2026-07-16"],
        [str(ledger), "add", "income", "2", "100", "work", "Salary", "2026-07-17"],
    ]
    for arguments in commands:
        stdout = StringIO()
        assert LLVMRunner().run(typed, stdout=stdout, program_arguments=arguments) == 0
        assert stdout.getvalue().startswith("transaction added:")
        ast_arguments = [str(ast_ledger), *arguments[1:]]
        assert run_aether(
            (EXAMPLE / "Main.ae").read_text(encoding="utf-8"),
            source_root=EXAMPLE,
            program_arguments=ast_arguments,
        ).exit_code == 0
    assert ledger.read_bytes() == ast_ledger.read_bytes()
    stdout = StringIO()
    assert LLVMRunner().run(
        typed, stdout=stdout, program_arguments=[str(ledger), "summary"]
    ) == 0
    output = stdout.getvalue()
    assert "income: 100" in output
    assert "expenses: 20.5" in output
    assert ledger.read_bytes().endswith(b"end-file\n")


@pytest.mark.skipif(shutil.which("clang") is None, reason="clang is required")
@pytest.mark.parametrize("optimization", ["-O0", "-O1", "-O2"])
def test_alpt1_generated_runtime_compiles_with_clang_profiles(
    tmp_path: Path, optimization: str
) -> None:
    llvm = LLVMBuilder().emit_llvm(_typed(ROUNDTRIP_SOURCE))
    llvm_path = tmp_path / f"alpt1-{optimization[-1]}.ll"
    executable = tmp_path / f"alpt1-{optimization[-1]}"
    llvm_path.write_text(llvm, encoding="utf-8")
    compiled = subprocess.run(
        [shutil.which("clang") or "clang", optimization, str(llvm_path), "-o", str(executable)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert compiled.returncode == 0, compiled.stderr
    completed = subprocess.run([str(executable)], capture_output=True, text=True, check=False)
    assert completed.returncode == 0
    assert completed.stdout == "true\n" * 6
