from __future__ import annotations

import shutil
from io import StringIO
from pathlib import Path

import pytest

from aether.differential import OPTIMIZATION_LEVELS, discover_cases, run_corpus
from aether.pipeline import IRBackend, IR_MAIN_RESULT_NAME, prepare_typed_program
from aether.runner import run_aether
from aether.typechecker import TypeChecker


def test_profile_22_differential_corpus_is_nonempty_and_named() -> None:
    names = {case.name for case in discover_cases()}
    assert names == {
        "aggregates",
        "arguments",
        "files",
        "language_core",
        "modules/Main",
        "panic",
        "panic_division_zero",
        "panic_integer_overflow",
        "panic_list_insert",
        "panic_list_pop",
        "panic_list_remove",
        "panic_split",
        "scalars",
        "strings",
    }


@pytest.mark.skipif(shutil.which("clang") is None, reason="clang is required")
def test_profile_22_ast_native_observations_match_at_every_optimization_level() -> None:
    results = run_corpus()
    assert len(results) == 14
    assert all(tuple(result.native) == OPTIMIZATION_LEVELS for result in results)


def test_language_core_matches_ast_and_internal_ir_interpreter() -> None:
    source_path = Path(__file__).parent / "parity_corpus" / "language_core.ae"
    source = source_path.read_text(encoding="utf-8")
    expected = "11\n120\n9\n7\n6\ntrue\naether\n2.5\n4.0\n"

    ast_result = run_aether(source, source_root=source_path.parent)
    ir_stdout = StringIO()
    ir_backend = IRBackend(output_writer=ir_stdout.write)
    environment = ir_backend.run(
        prepare_typed_program(
            source,
            TypeChecker(source_root=source_path.parent, entry_path=source_path),
        )
    )

    assert ast_result.exit_code == 0
    assert ast_result.output == expected
    assert environment.lookup(IR_MAIN_RESULT_NAME).value == 0
    assert ir_stdout.getvalue() == expected
