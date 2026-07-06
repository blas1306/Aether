from __future__ import annotations

from io import StringIO
from pathlib import Path
import shutil
import subprocess

import pytest

from aether.cli import EXIT_SUCCESS, main


ROOT_DIR = Path(__file__).resolve().parents[1]
LLVM_EXAMPLES_DIR = ROOT_DIR / "examples" / "llvm"
LLVM_EXAMPLES = sorted(LLVM_EXAMPLES_DIR.glob("*.ae"))

EXPECTED_EXIT_CODES = {
    "arithmetic.ae": 23,
    "countdown.ae": 0,
    "gcd_iterative.ae": 6,
    "identity_call.ae": 23,
    "max.ae": 12,
    "return_5.ae": 5,
    "sum_to_n.ae": 15,
}


def run_cli(argv: list[str]) -> tuple[int, str, str]:
    stdout = StringIO()
    stderr = StringIO()
    exit_code = main(argv, stdout=stdout, stderr=stderr)
    return exit_code, stdout.getvalue(), stderr.getvalue()


def test_llvm_example_exit_code_table_matches_files() -> None:
    assert [path.name for path in LLVM_EXAMPLES] == sorted(EXPECTED_EXIT_CODES)


@pytest.mark.parametrize("example_path", LLVM_EXAMPLES, ids=lambda path: path.name)
def test_llvm_example_builds_and_runs_with_expected_exit_code(
    example_path: Path,
    tmp_path: Path,
) -> None:
    if shutil.which("clang") is None:
        pytest.skip("clang is not available")

    output = tmp_path / example_path.stem
    expected_exit_code = EXPECTED_EXIT_CODES[example_path.name]

    exit_code, stdout, stderr = run_cli(
        ["build", str(example_path), "-o", str(output)]
    )

    assert exit_code == EXIT_SUCCESS
    assert stdout == f"Built executable: {output.resolve()}\n"
    assert stderr == ""

    completed = subprocess.run(
        [str(output)],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert completed.returncode == expected_exit_code
    assert completed.stdout == ""
    assert completed.stderr == ""
