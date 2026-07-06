from __future__ import annotations

import os
from pathlib import Path
import subprocess
import tempfile
from typing import BinaryIO, TextIO

from .build import LLVMBuildError, LLVMBuilder


class LLVMRunError(Exception):
    """Raised when native LLVM build-and-run orchestration fails."""


class LLVMRunner:
    """Run typed Aether programs as temporary native executables."""

    def __init__(self, *, builder: LLVMBuilder | None = None) -> None:
        self._builder = builder or LLVMBuilder()

    def run(
        self,
        typed_program: object,
        *,
        stdout: TextIO | BinaryIO | None = None,
        stderr: TextIO | BinaryIO | None = None,
    ) -> int:
        suffix = ".exe" if os.name == "nt" else ""
        with tempfile.TemporaryDirectory(prefix="aether-run-") as temporary_dir:
            executable_path = Path(temporary_dir) / f"program{suffix}"
            try:
                self._builder.build(
                    typed_program,
                    output_path=executable_path,
                    keep_llvm=False,
                )
            except LLVMBuildError as exc:
                raise LLVMRunError(str(exc)) from exc

            return self._run_executable(
                executable_path,
                stdout=stdout,
                stderr=stderr,
            )

    def _run_executable(
        self,
        executable_path: Path,
        *,
        stdout: TextIO | BinaryIO | None,
        stderr: TextIO | BinaryIO | None,
    ) -> int:
        stdout_target = _subprocess_stream(stdout)
        stderr_target = _subprocess_stream(stderr)
        capture_stdout = stdout is not None and stdout_target is None
        capture_stderr = stderr is not None and stderr_target is None

        try:
            completed = subprocess.run(
                [str(executable_path)],
                check=False,
                stdout=subprocess.PIPE if capture_stdout else stdout_target,
                stderr=subprocess.PIPE if capture_stderr else stderr_target,
            )
        except OSError as exc:
            raise LLVMRunError(f"failed to execute temporary native program: {exc}") from exc

        if capture_stdout:
            _write_captured(stdout, completed.stdout)
        if capture_stderr:
            _write_captured(stderr, completed.stderr)
        return completed.returncode


def _subprocess_stream(
    stream: TextIO | BinaryIO | None,
) -> TextIO | BinaryIO | None:
    if stream is None:
        return None
    try:
        stream.fileno()
    except (AttributeError, OSError):
        return None
    return stream


def _write_captured(
    stream: TextIO | BinaryIO | None,
    output: bytes | None,
) -> None:
    if stream is None or not output:
        return
    try:
        stream.write(output)  # type: ignore[arg-type]
    except TypeError:
        stream.write(output.decode(errors="replace"))  # type: ignore[arg-type]
    stream.flush()
