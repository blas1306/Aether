from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import os
from pathlib import Path
import subprocess
import tempfile
from time import perf_counter
from typing import TYPE_CHECKING

from .errors import AetherError, AetherRuntimeError
from .interpreter import Interpreter
from .pipeline import ASTBackend, IRBackend, SSAPipeline, prepare_typed_program
from .typechecker import TypeChecker

if TYPE_CHECKING:
    from .ir.model import IRModule
    from .pipeline import TypedProgram
    from .ssa import SSAModule


BenchBackend = str


@dataclass(frozen=True)
class BenchTiming:
    name: str
    category: str
    total_seconds: float
    average_seconds: float


@dataclass(frozen=True)
class BenchFailure:
    name: str
    category: str
    error: AetherError
    unsupported: bool = False


@dataclass(frozen=True)
class BenchReport:
    path: Path
    iterations: int
    timings: tuple[BenchTiming, ...]
    failures: tuple[BenchFailure, ...]


def run_benchmark(
    source: str,
    *,
    path: Path,
    iterations: int,
    backend: BenchBackend,
    expected_exit_code: int | None = 0,
) -> BenchReport:
    """Measure the requested compiler profiles without combining build and runtime."""
    if iterations < 1:
        raise ValueError("iterations must be at least 1")
    if backend not in {"ast", "ir", "both", "ssa", "llvm", "native", "all"}:
        raise ValueError(f"unknown benchmark backend: {backend}")

    timings: list[BenchTiming] = []
    failures: list[BenchFailure] = []

    if backend in {"ast", "both", "all"}:
        _append_measurement(
            timings,
            failures,
            "AST parse/typecheck",
            "frontend",
            iterations,
            lambda: _typed_program(source, path),
        )
        try:
            ast_program = _typed_program(source, path)
        except Exception as exc:
            failures.append(
                BenchFailure("AST execute", "runtime", _benchmark_error(exc, "AST setup"))
            )
        else:
            _append_measurement(
                timings,
                failures,
                "AST execute",
                "runtime",
                iterations,
                lambda: _run_ast(ast_program, path),
            )
    if backend in {"ir", "both", "all"}:
        _append_measurement(
            timings,
            failures,
            "IR lower/verify",
            "middle-end",
            iterations,
            lambda: _build_ir(source, path),
        )
        try:
            ir_module = _build_ir(source, path)
        except Exception as exc:
            failures.append(
                BenchFailure("IR execute", "runtime", _benchmark_error(exc, "IR setup"))
            )
        else:
            _append_measurement(
                timings,
                failures,
                "IR execute",
                "runtime",
                iterations,
                lambda: _run_ir(ir_module),
            )
        _append_measurement(
            timings,
            failures,
            "IR O1 optimize",
            "middle-end",
            iterations,
            lambda: _run_ir_o1_optimizer(source, path),
        )
    if backend in {"ssa", "all"}:
        _append_measurement(
            timings,
            failures,
            "SSA build",
            "middle-end",
            iterations,
            lambda: _build_ssa(source, path),
        )
        _append_measurement(
            timings,
            failures,
            "SSA optimize",
            "middle-end",
            iterations,
            lambda: _optimize_ssa(source, path),
        )
    if backend in {"llvm", "all"}:
        _append_measurement(
            timings,
            failures,
            "LLVM emit",
            "codegen",
            iterations,
            lambda: _emit_llvm(source, path),
        )

    if backend in {"native", "all"}:
        _measure_native_profiles(
            source,
            path=path,
            iterations=iterations,
            expected_exit_code=expected_exit_code,
            timings=timings,
            failures=failures,
        )

    return BenchReport(path, iterations, tuple(timings), tuple(failures))


def _measure(
    name: str,
    category: str,
    iterations: int,
    action: Callable[[], None],
) -> BenchTiming:
    started = perf_counter()
    for _ in range(iterations):
        action()
    total = perf_counter() - started
    return BenchTiming(name, category, total, total / iterations)


def _measure_or_fail(
    name: str,
    category: str,
    iterations: int,
    action: Callable[[], None],
    *,
    unsupported: bool = False,
) -> tuple[BenchTiming | None, BenchFailure | None]:
    try:
        return _measure(name, category, iterations, action), None
    except Exception as exc:
        return None, BenchFailure(
            name,
            category,
            _benchmark_error(exc, name),
            unsupported=unsupported or _is_missing_clang(exc),
        )


def _append_measurement(
    timings: list[BenchTiming],
    failures: list[BenchFailure],
    name: str,
    category: str,
    iterations: int,
    action: Callable[[], None],
) -> None:
    timing, failure = _measure_or_fail(name, category, iterations, action)
    if timing is not None:
        timings.append(timing)
    elif failure is not None:
        failures.append(failure)


def _run_ast(typed_program: TypedProgram, path: Path) -> None:
    interpreter = Interpreter(source_root=path.parent, output_writer=lambda _text: None)
    ASTBackend(interpreter).run(typed_program)


def _build_ir(source: str, path: Path) -> IRModule:
    return IRBackend().lower_verified(_typed_program(source, path))


def _run_ir(module: IRModule) -> None:
    from .ir.interpreter import IRExecutionError, IRInterpreter

    entry = next((function for function in module.functions if function.name == "main"), None)
    if entry is None or entry.parameters:
        raise AetherRuntimeError(
            "IR benchmark input has no normalized executable entry point.",
            kind="bench",
        )
    try:
        IRInterpreter(module).call(entry.name)
    except IRExecutionError as exc:
        raise AetherRuntimeError(f"IR interpreter failed: {exc}", kind="ir") from exc


def _run_ir_o1_optimizer(source: str, path: Path) -> None:
    from .ir.optimizer import build_optimizer_pipeline

    backend = IRBackend()
    module = backend.lower_verified(_typed_program(source, path))
    backend.optimize_verified(module, optimizer=build_optimizer_pipeline("O1"))


def _build_ssa(source: str, path: Path) -> None:
    SSAPipeline().run(_typed_program(source, path))


def _optimized_ssa(source: str, path: Path) -> SSAModule:
    from .ssa import SSAVerifier
    from .ssa.optimizer import SSAOptimizerPipeline

    module = SSAPipeline().run(_typed_program(source, path)).ssa_module
    return SSAVerifier(SSAOptimizerPipeline().run(module)).verify()


def _optimize_ssa(source: str, path: Path) -> None:
    _optimized_ssa(source, path)


def _emit_llvm(source: str, path: Path) -> None:
    from .backend.llvm import LLVMBackend

    LLVMBackend().emit(_optimized_ssa(source, path))


def _build_native(source: str, path: Path, output_path: Path) -> None:
    from .backend.llvm import LLVMBuilder

    LLVMBuilder().build(
        _typed_program(source, path),
        output_path=output_path,
        keep_llvm=False,
    )


def _measure_native_profiles(
    source: str,
    *,
    path: Path,
    iterations: int,
    expected_exit_code: int | None,
    timings: list[BenchTiming],
    failures: list[BenchFailure],
) -> None:
    suffix = ".exe" if os.name == "nt" else ""
    with tempfile.TemporaryDirectory(prefix="aether-bench-") as temporary_dir:
        executable = Path(temporary_dir) / f"program{suffix}"
        build_timing, build_failure = _measure_or_fail(
            "Native build",
            "codegen",
            iterations,
            lambda: _build_native(source, path, executable),
        )
        if build_timing is not None:
            timings.append(build_timing)
        elif build_failure is not None:
            failures.append(build_failure)

        # Native runtime has a separate, untimed setup build. Compilation is
        # deliberately never part of the runtime interval.
        try:
            _build_native(source, path, executable)
        except Exception as exc:
            failures.append(
                BenchFailure(
                    "Native run",
                    "runtime",
                    _benchmark_error(exc, "Native run setup"),
                    unsupported=_is_missing_clang(exc),
                )
            )
            return

        run_timing, run_failure = _measure_or_fail(
            "Native run",
            "runtime",
            iterations,
            lambda: _run_native_executable(executable, expected_exit_code),
        )
        if run_timing is not None:
            timings.append(run_timing)
        elif run_failure is not None:
            failures.append(run_failure)


def _run_native_executable(executable: Path, expected_exit_code: int | None) -> None:
    try:
        completed = subprocess.run(
            [str(executable)],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
    except OSError as exc:
        raise AetherRuntimeError(
            f"Native benchmark executable could not run: {exc}",
            kind="bench-native",
        ) from exc
    if expected_exit_code is not None and completed.returncode != expected_exit_code:
        detail = completed.stderr.decode(errors="replace").strip()
        message = (
            "Native benchmark executable returned exit code "
            f"{completed.returncode}; expected {expected_exit_code}."
        )
        if detail:
            message = f"{message} stderr: {detail}"
        raise AetherRuntimeError(message, kind="bench-native")


def _typed_program(source: str, path: Path) -> TypedProgram:
    return prepare_typed_program(source, TypeChecker(source_root=path.parent))


def _benchmark_error(exc: Exception, profile: str) -> AetherError:
    if isinstance(exc, AetherError):
        return exc
    return AetherRuntimeError(f"{profile} failed: {exc}", kind="bench")


def _is_missing_clang(exc: Exception) -> bool:
    return "clang is required" in str(exc).lower()
