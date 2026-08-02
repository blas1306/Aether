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
import re
import shutil
import statistics
import subprocess
import sys
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


def _runtime_samples(
    executable: Path, repetitions: int
) -> tuple[list[float], str, str, int]:
    samples: list[float] = []
    last: subprocess.CompletedProcess[str] | None = None
    for _ in range(repetitions):
        started = time.perf_counter_ns()
        last = _run([str(executable)])
        samples.append((time.perf_counter_ns() - started) / 1_000_000)
    assert last is not None
    return samples, last.stdout, last.stderr, last.returncode


def _elapsed_ms(command: list[str]) -> tuple[float, subprocess.CompletedProcess[str]]:
    started = time.perf_counter_ns()
    completed = _run(command)
    return (time.perf_counter_ns() - started) / 1_000_000, completed


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
            "python": sys.version.splitlines()[0],
        },
        "commands": {
            "reproduce": "PYTHONPATH=src .venv/bin/python scripts/compare_exception_lowering.py --runs 9",
            "compile": "clang -O<0|1|2> -c module.ll -o module.o",
            "link_event_out": "clang module.o -o program",
            "link_llvm_eh": "clang module.o -o program -l:libstdc++.so.6",
        },
        "measurements": [],
    }

    with tempfile.TemporaryDirectory(prefix="aether-exception-comparison-") as raw:
        root = Path(raw)
        for corpus_name, source in SOURCES.items():
            ssa_started = time.perf_counter_ns()
            module = _verified_ssa(source)
            ssa_ms = (time.perf_counter_ns() - ssa_started) / 1_000_000
            for strategy in ExceptionLoweringStrategy:
                emission_started = time.perf_counter_ns()
                llvm = LLVMBackend(
                    LLVMPrinter(
                        exception_strategy=strategy,
                        allow_test_exception_strategy=True,
                    )
                ).emit(module)
                emission_ms = (time.perf_counter_ns() - emission_started) / 1_000_000
                for optimization in ("0", "1", "2"):
                    stem = f"{corpus_name}-{strategy.value}-O{optimization}"
                    llvm_path = root / f"{stem}.ll"
                    object_path = root / f"{stem}.o"
                    executable = root / stem
                    llvm_path.write_text(llvm, encoding="utf-8")
                    compile_command = [
                        clang,
                        f"-O{optimization}",
                        "-Wno-override-module",
                        "-c",
                        str(llvm_path),
                        "-o", str(object_path),
                    ]
                    link_command = [clang, str(object_path), "-o", str(executable)]
                    if strategy is ExceptionLoweringStrategy.LLVM_EH_PROTOTYPE:
                        link_command.append("-l:libstdc++.so.6")
                    compile_samples: list[float] = []
                    built: subprocess.CompletedProcess[str] | None = None
                    for _ in range(3):
                        elapsed, built = _elapsed_ms(compile_command)
                        compile_samples.append(elapsed)
                    assert built is not None
                    if built.returncode != 0:
                        raise SystemExit(built.stderr)
                    link_samples: list[float] = []
                    linked: subprocess.CompletedProcess[str] | None = None
                    for _ in range(3):
                        elapsed, linked = _elapsed_ms(link_command)
                        link_samples.append(elapsed)
                    assert linked is not None
                    if linked.returncode != 0:
                        raise SystemExit(linked.stderr)
                    runtime_samples, stdout, stderr, returncode = _runtime_samples(
                        executable, arguments.runs
                    )
                    generated_functions = len(
                        re.findall(r"(?m)^define\s", llvm)
                    )
                    runtime_helpers = len(
                        re.findall(r"(?m)^define private .*@__ae_exception_", llvm)
                    )
                    report["measurements"].append(
                        {
                            "corpus": corpus_name,
                            "strategy": strategy.value,
                            "optimization": f"O{optimization}",
                            "llvm_bytes": len(llvm.encode("utf-8")),
                            "llvm_lines": len(llvm.splitlines()),
                            "object_bytes": object_path.stat().st_size,
                            "binary_bytes": executable.stat().st_size,
                            "generated_functions": generated_functions,
                            "exception_runtime_helpers": runtime_helpers,
                            "ssa_build_ms": round(ssa_ms, 3),
                            "llvm_emission_ms": round(emission_ms, 3),
                            "clang_compile_samples_ms": [
                                round(sample, 3) for sample in compile_samples
                            ],
                            "compile_median_ms": round(
                                statistics.median(compile_samples), 3
                            ),
                            "link_samples_ms": [
                                round(sample, 3) for sample in link_samples
                            ],
                            "link_median_ms": round(
                                statistics.median(link_samples), 3
                            ),
                            "runtime_samples_ms": [
                                round(sample, 3) for sample in runtime_samples
                            ],
                            "run_median_ms": round(
                                statistics.median(runtime_samples), 3
                            ),
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
