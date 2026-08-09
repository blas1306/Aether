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
from .optimization import DEFAULT_OPTIMIZATION_PROFILE, OptimizationProfile

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
    error: Exception
    unsupported: bool = False


@dataclass(frozen=True)
class BenchReport:
    path: Path
    iterations: int
    timings: tuple[BenchTiming, ...]
    failures: tuple[BenchFailure, ...]
    optimization_profile: OptimizationProfile = DEFAULT_OPTIMIZATION_PROFILE


def run_benchmark(
    source: str,
    *,
    path: Path,
    iterations: int,
    backend: BenchBackend,
    expected_exit_code: int | None = 0,
    optimization_profile: OptimizationProfile = DEFAULT_OPTIMIZATION_PROFILE,
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
            f"IR {optimization_profile.name} optimize",
            "middle-end",
            iterations,
            lambda: _run_ir_optimizer(source, path, optimization_profile),
        )
    if backend in {"ssa", "all"}:
        _append_measurement(
            timings,
            failures,
            "SSA build",
            "middle-end",
            iterations,
            lambda: _build_ssa(source, path, optimization_profile),
        )
        _append_measurement(
            timings,
            failures,
            "SSA optimize",
            "middle-end",
            iterations,
            lambda: _optimize_ssa(source, path, optimization_profile),
        )
    if backend in {"llvm", "all"}:
        _append_measurement(
            timings,
            failures,
            "LLVM emit",
            "codegen",
            iterations,
            lambda: _emit_llvm(source, path, optimization_profile),
        )

    if backend in {"native", "all"}:
        _measure_native_profiles(
            source,
            path=path,
            iterations=iterations,
            expected_exit_code=expected_exit_code,
            timings=timings,
            failures=failures,
            optimization_profile=optimization_profile,
        )

    return BenchReport(path, iterations, tuple(timings), tuple(failures), optimization_profile)


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


def _run_ir_optimizer(source: str, path: Path, profile: OptimizationProfile) -> None:
    from .ir.optimizer import build_optimizer_pipeline

    backend = IRBackend()
    module = backend.lower_verified(_typed_program(source, path))
    backend.optimize_verified(module, optimizer=build_optimizer_pipeline(profile))


def _build_ssa(source: str, path: Path, profile: OptimizationProfile) -> None:
    _optimized_ssa(source, path, profile)


def _optimized_ssa(source: str, path: Path, profile: OptimizationProfile) -> SSAModule:
    from .ssa import SSAVerifier
    from .ssa.optimizer import build_ssa_optimizer_pipeline

    typed = _typed_program(source, path)
    ir_backend = IRBackend()
    ir = ir_backend.lower_verified(typed)
    if profile.ir_passes:
        from .ir.optimizer import build_optimizer_pipeline
        ir = ir_backend.optimize_verified(ir, optimizer=build_optimizer_pipeline(profile))
    module = SSAPipeline().run(ir).ssa_module
    return SSAVerifier(build_ssa_optimizer_pipeline(profile).run(module)).verify()


def _optimize_ssa(source: str, path: Path, profile: OptimizationProfile) -> None:
    _optimized_ssa(source, path, profile)


def _emit_llvm(source: str, path: Path, profile: OptimizationProfile) -> None:
    from .backend.llvm import LLVMBuilder
    from .capabilities import BackendIdentity, validate_backend_capabilities

    typed_program = _typed_program(source, path)
    validate_backend_capabilities(typed_program, BackendIdentity.NATIVE)
    LLVMBuilder(optimization_profile=profile).emit_llvm(typed_program)


def _build_native(source: str, path: Path, output_path: Path, profile: OptimizationProfile) -> None:
    from .backend.llvm import LLVMBuilder

    LLVMBuilder(optimization_profile=profile).build(
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
    optimization_profile: OptimizationProfile,
) -> None:
    suffix = ".exe" if os.name == "nt" else ""
    with tempfile.TemporaryDirectory(prefix="aether-bench-") as temporary_dir:
        executable = Path(temporary_dir) / f"program{suffix}"
        build_timing, build_failure = _measure_or_fail(
            "Native build",
            "codegen",
            iterations,
            lambda: _build_native(source, path, executable, optimization_profile),
        )
        if build_timing is not None:
            timings.append(build_timing)
        elif build_failure is not None:
            failures.append(build_failure)

        # Native runtime has a separate, untimed setup build. Compilation is
        # deliberately never part of the runtime interval.
        try:
            _build_native(source, path, executable, optimization_profile)
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
    return prepare_typed_program(
        source,
        TypeChecker(source_root=path.parent, entry_path=path),
    )


def _benchmark_error(exc: Exception, profile: str) -> Exception:
    del profile
    # Preserve the original exception and cause chain.  The public CLI boundary
    # owns classification and sanitization; wrapping here used to turn compiler
    # bugs into user-visible runtime strings.
    return exc


def _is_missing_clang(exc: Exception) -> bool:
    return "clang is required" in str(exc).lower()
