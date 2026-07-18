from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]


def _llvm_from_fresh_process(hash_seed: str) -> bytes:
    script = r"""
from aether.backend.llvm.build import LLVMBuilder
from aether.pipeline import prepare_typed_program
from aether.typechecker import TypeChecker
import sys

source = r'''
struct Item { int number; string label; }
int main() {
    List<Item> items = {Item(2, "two"), Item(1, "one")};
    List<Item> copied = items.copy();
    println(copied);
    return 0;
}
'''
typed = prepare_typed_program(source, TypeChecker())
sys.stdout.buffer.write(LLVMBuilder().emit_llvm(typed).encode("utf-8"))
"""
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(ROOT / "src")
    environment["PYTHONHASHSEED"] = hash_seed
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=ROOT,
        env=environment,
        check=False,
        capture_output=True,
    )
    assert completed.returncode == 0, completed.stderr.decode(errors="replace")
    return completed.stdout


def test_llvm_emission_is_stable_across_python_hash_seeds() -> None:
    assert _llvm_from_fresh_process("1") == _llvm_from_fresh_process("8675309")
