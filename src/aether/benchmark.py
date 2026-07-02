from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter

from .errors import AetherError, AetherRuntimeError
from .interpreter import Interpreter
from .pipeline import ASTBackend, IRBackend, prepare_typed_program
from .typechecker import TypeChecker


BenchBackend = str


@dataclass(frozen=True)
class BenchTiming:
    name: str
    total_seconds: float
    average_seconds: float


@dataclass(frozen=True)
class BenchFailure:
    name: str
    error: AetherError


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
) -> BenchReport:
    """Measure frontend plus backend work for a small Aether program."""
    if iterations < 1:
        raise ValueError("iterations must be at least 1")

    timings: list[BenchTiming] = []
    failures: list[BenchFailure] = []

    if backend in {"ast", "both"}:
        timings.append(_measure("AST backend", iterations, lambda: _run_ast(source, path)))

    if backend in {"ir", "both"}:
        ir_timing, ir_failure = _measure_or_fail(
            "IR backend",
            iterations,
            lambda: _run_ir(source, path),
        )
        if ir_timing is not None:
            timings.append(ir_timing)
            optimizer_timing, optimizer_failure = _measure_or_fail(
                "IR O1 optimizer (not executed)",
                iterations,
                lambda: _run_ir_o1_optimizer(source, path),
            )
            if optimizer_timing is not None:
                timings.append(optimizer_timing)
            elif optimizer_failure is not None:
                failures.append(optimizer_failure)
        elif ir_failure is not None:
            failures.append(ir_failure)

    return BenchReport(
        path=path,
        iterations=iterations,
        timings=tuple(timings),
        failures=tuple(failures),
    )


def _measure(name: str, iterations: int, action: Callable[[], None]) -> BenchTiming:
    started = perf_counter()
    for _ in range(iterations):
        action()
    total = perf_counter() - started
    return BenchTiming(name, total, total / iterations)


def _measure_or_fail(
    name: str,
    iterations: int,
    action: Callable[[], None],
) -> tuple[BenchTiming | None, BenchFailure | None]:
    try:
        return _measure(name, iterations, action), None
    except AetherError as exc:
        return None, BenchFailure(name, exc)


def _run_ast(source: str, path: Path) -> None:
    typed_program = prepare_typed_program(
        source,
        TypeChecker(source_root=path.parent),
    )
    interpreter = Interpreter(source_root=path.parent, output_writer=lambda _text: None)
    env = ASTBackend(interpreter).run(typed_program)
    main = env.get_function("main")
    if main is not None:
        if main.declaration.parameters:
            raise AetherRuntimeError(
                "Benchmark AST entry point main() must not declare parameters.",
                kind="bench",
            )
        interpreter._call_user_function("main", [], env)


def _run_ir(source: str, path: Path) -> None:
    IRBackend().run(
        prepare_typed_program(
            source,
            TypeChecker(source_root=path.parent),
        )
    )


def _run_ir_o1_optimizer(source: str, path: Path) -> None:
    from .ir.optimizer import build_optimizer_pipeline

    typed_program = prepare_typed_program(
        source,
        TypeChecker(source_root=path.parent),
    )
    backend = IRBackend()
    module = backend.lower_verified(typed_program)
    backend.optimize_verified(module, optimizer=build_optimizer_pipeline("O1"))
