#!/usr/bin/env python3
"""Regenerate the embedded numeric parser IR with the canonical LLVM dialect."""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "compiler-next/crates/aether-backend-llvm/src/numeric_parse_runtime.c"
OUTPUT = ROOT / "compiler-next/crates/aether-backend-llvm/src/numeric_parse_runtime.inc"
CANONICAL_LLVM_MAJOR = 21


def clang_major(clang: str) -> int:
    result = subprocess.run(
        [clang, "--version"], check=True, text=True, capture_output=True
    )
    match = re.search(r"clang version (\d+)", result.stdout)
    if match is None:
        raise RuntimeError(f"could not determine LLVM version from {clang} --version")
    return int(match.group(1))


def embedded_ir(clang: str) -> str:
    major = clang_major(clang)
    if major != CANONICAL_LLVM_MAJOR:
        raise RuntimeError(
            f"numeric runtime generation requires Clang {CANONICAL_LLVM_MAJOR}.x; "
            f"found {major}.x"
        )

    environment = os.environ.copy()
    environment["LC_ALL"] = "C"
    with tempfile.TemporaryDirectory(prefix="aether-numeric-runtime-") as directory:
        raw_path = Path(directory) / "numeric_parse_runtime.ll"
        subprocess.run(
            [
                clang,
                "--target=x86_64-pc-linux-gnu",
                "-O1",
                "-S",
                "-emit-llvm",
                "-fno-math-errno",
                str(SOURCE),
                "-o",
                str(raw_path),
            ],
            check=True,
            env=environment,
        )
        raw = raw_path.read_text(encoding="utf-8")

    body_start = raw.index("%struct.Big = type")
    metadata_start = raw.index("!llvm.module.flags =")
    body = raw[body_start:metadata_start].rstrip() + "\n"
    body = body.replace(
        "define dso_local { i32, i64 } @aether_numeric_parse_double",
        "define internal { i32, i64 } @aether_numeric_parse_double",
        1,
    )
    body = re.sub(r", !(?:tbaa(?:\.struct)?|llvm\.loop) !\d+", "", body)
    body = re.sub(
        r"; Function Attrs: mustprogress nocallback nofree nounwind "
        r"willreturn memory\(argmem: readwrite\)\n"
        r"declare void @llvm\.memcpy\.p0\.p0\.i64\([^\n]+\) #3\n\n",
        "",
        body,
        count=1,
    )
    return body


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--clang", default="clang", help="Clang 21 executable")
    parser.add_argument(
        "--check", action="store_true", help="check that the committed fragment is current"
    )
    arguments = parser.parse_args()

    try:
        generated = embedded_ir(arguments.clang)
    except (OSError, subprocess.CalledProcessError, RuntimeError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2

    if arguments.check:
        committed = OUTPUT.read_text(encoding="utf-8")
        if committed != generated:
            print(
                f"error: {OUTPUT.relative_to(ROOT)} is stale; regenerate with {Path(__file__).name}",
                file=sys.stderr,
            )
            return 1
        return 0

    OUTPUT.write_text(generated, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
