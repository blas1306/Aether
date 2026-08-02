#!/usr/bin/env python3
"""Reproduce the Linux x86_64 exception-backend comparison.

The script lowers each source once to verified SSA, emits both private
transports from that same object, and records compiler/runtime measurements as
JSON.  It is an engineering probe, not a stable benchmark contract.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import platform
import shutil
import statistics
import subprocess
import tempfile
import time

from aether.backend.llvm import LLVMBackend, LLVMPrinter
from aether.backend.llvm.exception_abi import ExceptionLoweringStrategy
from aether.ir import IRLowerer
from aether.pipeline import parse_source
from aether.ssa import GeneralSSABuilder
from aether.typechecker import TypeChecker


ERROR = """
struct ProbeError implements Error {
    string text;
    string message() { return text; }
}
"""

SOURCES = {
    "normal": ERROR
    + """
int maybeFail(boolean fail) {
    if (fail) { throw ProbeError("unexpected"); }
    return 1;
}
int main() {
    int total = 0;
    int i = 0;
    while (i < 200000) {
        total = total + maybeFail(false);
        i = i + 1;
    }
    println(total);
    return 0;
}
""",
    "exceptional": ERROR
    + """
void fail() { throw ProbeError("expected"); }
int main() {
    int count = 0;
    int i = 0;
    while (i < 2000) {
        try { fail(); }
        catch (ProbeError error) { count = count + 1; }
        i = i + 1;
    }
    println(count);
    return 0;
}
""",
}


def _verified_ssa(source: str):
    program = parse_source(source)
    TypeChecker().check(program)
    return GeneralSSABuilder().build(IRLowerer().lower(program))


def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, check=False, capture_output=True, text=True)


def _median_runtime(executable: Path, repetitions: int) -> tuple[float, str, str, int]:
    samples = []
    last: subprocess.CompletedProcess[str] | None = None
    for _ in range(repetitions):
        started = time.perf_counter_ns()
        last = _run([str(executable)])
        samples.append((time.perf_counter_ns() - started) / 1_000_000)
    assert last is not None
    return statistics.median(samples), last.stdout, last.stderr, last.returncode


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=9)
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()

    clang = shutil.which("clang")
    if clang is None:
        raise SystemExit("clang is required")
    clang_version = _run([clang, "--version"]).stdout.splitlines()[0]
    report: dict[str, object] = {
        "host": {
            "platform": platform.platform(),
            "machine": platform.machine(),
            "clang": clang_version,
        },
        "commands": {
            "reproduce": "PYTHONPATH=src .venv/bin/python scripts/compare_exception_lowering.py --runs 9",
            "compile_event_out": "clang -O<0|1|2> module.ll -o program",
            "compile_llvm_eh": "clang -O<0|1|2> module.ll -o program -l:libstdc++.so.6",
        },
        "measurements": [],
    }

    with tempfile.TemporaryDirectory(prefix="aether-exception-comparison-") as raw:
        root = Path(raw)
        for corpus_name, source in SOURCES.items():
            module = _verified_ssa(source)
            for strategy in ExceptionLoweringStrategy:
                llvm = LLVMBackend(
                    LLVMPrinter(exception_strategy=strategy)
                ).emit(module)
                for optimization in ("0", "1", "2"):
                    stem = f"{corpus_name}-{strategy.value}-O{optimization}"
                    llvm_path = root / f"{stem}.ll"
                    executable = root / stem
                    llvm_path.write_text(llvm, encoding="utf-8")
                    command = [
                        clang,
                        f"-O{optimization}",
                        "-Wno-override-module",
                        str(llvm_path),
                        "-o",
                        str(executable),
                    ]
                    if strategy is ExceptionLoweringStrategy.LLVM_EH_PROTOTYPE:
                        command.append("-l:libstdc++.so.6")
                    compile_samples = []
                    built: subprocess.CompletedProcess[str] | None = None
                    for _ in range(3):
                        started = time.perf_counter_ns()
                        built = _run(command)
                        compile_samples.append(
                            (time.perf_counter_ns() - started) / 1_000_000
                        )
                    assert built is not None
                    if built.returncode != 0:
                        raise SystemExit(built.stderr)
                    runtime_ms, stdout, stderr, returncode = _median_runtime(
                        executable, arguments.runs
                    )
                    report["measurements"].append(
                        {
                            "corpus": corpus_name,
                            "strategy": strategy.value,
                            "optimization": f"O{optimization}",
                            "llvm_bytes": len(llvm.encode("utf-8")),
                            "llvm_lines": len(llvm.splitlines()),
                            "binary_bytes": executable.stat().st_size,
                            "compile_median_ms": round(
                                statistics.median(compile_samples), 3
                            ),
                            "run_median_ms": round(runtime_ms, 3),
                            "returncode": returncode,
                            "stdout": stdout,
                            "stderr": stderr,
                        }
                    )

    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if arguments.output is not None:
        arguments.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
