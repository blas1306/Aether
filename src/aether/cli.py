from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from pprint import pformat
import sys
from typing import TYPE_CHECKING, TextIO

from .errors import AetherError
from .benchmark import BenchReport, run_benchmark
from .ir import print_ir
from .pipeline import IRBackend, parse_source, prepare_typed_program, tokenize_source
from .runner import run_aether
from .session import AetherSession
from .tokens import Token
from .typechecker import TypeChecker
from .version import LANGUAGE_VERSION

if TYPE_CHECKING:
    from .ir.optimizer import OptimizationProfile, OptimizationTraceStep

EXIT_SUCCESS = 0
EXIT_LANGUAGE_ERROR = 1
EXIT_USAGE_ERROR = 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="aether",
        description="Run Aether language programs.",
        epilog=(
            "The default command is file execution: aether program.ae\n"
            "Development inspection tools: --tokens, --ast, --emit-ir, --emit-cfg, and bench"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("file", nargs="?", help="Aether source file to execute.")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--repl", action="store_true", help="Start a persistent Aether REPL.")
    modes.add_argument(
        "--tokens",
        action="store_true",
        help="Print lexer tokens instead of executing the file.",
    )
    modes.add_argument(
        "--ast",
        action="store_true",
        help="Print the parsed AST instead of executing the file.",
    )
    modes.add_argument(
        "--emit-ir",
        action="store_true",
        help="Lower the file to experimental IR, verify it, and print it.",
    )
    modes.add_argument(
        "--emit-cfg",
        action="store_true",
        help="Lower the file to experimental IR and print Graphviz DOT CFGs.",
    )
    parser.add_argument(
        "--opt",
        action="store_true",
        help="Optimize emitted IR. Currently only supported with --emit-ir.",
    )
    parser.add_argument(
        "-O",
        "--opt-level",
        choices=("0", "1", "2"),
        default=None,
        help=(
            "Optimization level for --emit-ir: 0 disables optimization, "
            "1 uses the current pipeline, 2 is reserved and aliases 1."
        ),
    )
    parser.add_argument(
        "--show-passes",
        action="store_true",
        help="With --emit-ir and an optimization level, print optimizer pass IR.",
    )
    parser.add_argument(
        "--backend",
        choices=("ast", "ir"),
        default="ast",
        help="Execution backend for files: ast (default) or ir (experimental).",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"Aether v{LANGUAGE_VERSION}",
    )
    return parser


def build_bench_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="aether bench",
        description="Measure Aether programs through development backends.",
    )
    parser.add_argument("file", help="Aether source file to benchmark.")
    parser.add_argument(
        "--iterations",
        type=_positive_int,
        default=10,
        help="Number of benchmark iterations. Defaults to 10.",
    )
    parser.add_argument(
        "--backend",
        choices=("ast", "ir", "both"),
        default="both",
        help="Backend profile to measure. Defaults to both.",
    )
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    stdin: TextIO | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    stderr = stderr or sys.stderr
    argv_list = list(sys.argv[1:] if argv is None else argv)
    if argv_list and argv_list[0] == "bench":
        return _main_bench(argv_list[1:], stdout=stdout, stderr=stderr)

    parser = build_parser()

    if stdout is sys.stdout and stderr is sys.stderr:
        args = parser.parse_args(argv_list)
    else:
        try:
            with redirect_stdout(stdout), redirect_stderr(stderr):
                args = parser.parse_args(argv_list)
        except SystemExit as exc:
            return int(exc.code)

    if args.opt_level is not None and not args.emit_ir:
        print(
            "aether: error: -O flags are currently only supported with --emit-ir.",
            file=stderr,
        )
        return EXIT_USAGE_ERROR
    if args.opt and not args.emit_ir:
        print("aether: error: --opt is currently only supported with --emit-ir.", file=stderr)
        return EXIT_USAGE_ERROR
    if args.show_passes and not (
        args.emit_ir and (args.opt or args.opt_level is not None)
    ):
        print(
            "aether: error: --show-passes requires --emit-ir --opt. "
            "Use -O0/-O1/-O2 as an alternative to --opt.",
            file=stderr,
        )
        return EXIT_USAGE_ERROR

    if args.repl:
        if args.backend != "ast":
            print("aether: error: --repl only supports --backend=ast for now.", file=stderr)
            return EXIT_USAGE_ERROR
        if args.file is not None:
            print("aether: error: --repl does not accept a file.", file=stderr)
            return EXIT_USAGE_ERROR
        return run_repl(stdin=stdin, stdout=stdout, stderr=stderr)

    if args.file is None:
        parser.print_help(file=stdout)
        return EXIT_USAGE_ERROR

    path = Path(args.file)
    source = _read_source(path, stderr=stderr)
    if source is None:
        return EXIT_USAGE_ERROR

    if args.tokens:
        return _run_language_action(
            lambda: _print_tokens(source, stdout=stdout),
            stderr=stderr,
        )
    if args.ast:
        return _run_language_action(
            lambda: _print_ast(source, stdout=stdout),
            stderr=stderr,
        )
    if args.emit_ir:
        return _run_language_action(
            lambda: _emit_ir(
                source,
                path=path,
                stdout=stdout,
                optimization_profile=_optimization_profile_from_args(
                    opt=args.opt,
                    opt_level=args.opt_level,
                ),
                show_passes=args.show_passes,
            ),
            stderr=stderr,
        )
    if args.emit_cfg:
        return _run_language_action(
            lambda: _emit_cfg(source, path=path, stdout=stdout),
            stderr=stderr,
        )
    return _run_language_action(
        lambda: _execute_file(
            source,
            path=path,
            backend=args.backend,
            stdin=stdin,
            stdout=stdout,
        ),
        stderr=stderr,
    )


def _main_bench(argv: Sequence[str], *, stdout: TextIO, stderr: TextIO) -> int:
    parser = build_bench_parser()
    if stdout is sys.stdout and stderr is sys.stderr:
        args = parser.parse_args(argv)
    else:
        try:
            with redirect_stdout(stdout), redirect_stderr(stderr):
                args = parser.parse_args(argv)
        except SystemExit as exc:
            return int(exc.code)

    path = Path(args.file)
    source = _read_source(path, stderr=stderr)
    if source is None:
        return EXIT_USAGE_ERROR

    try:
        report = run_benchmark(
            source,
            path=path,
            iterations=args.iterations,
            backend=args.backend,
        )
    except AetherError as exc:
        print(_format_language_error(exc), file=stderr)
        return EXIT_LANGUAGE_ERROR

    _print_benchmark_report(report, stdout=stdout)
    if args.backend == "ir" and report.failures:
        return EXIT_LANGUAGE_ERROR
    return EXIT_SUCCESS


def run_repl(*, stdin: TextIO, stdout: TextIO, stderr: TextIO) -> int:
    session = AetherSession(
        output_writer=stdout.write,
        input_reader=stdin.readline,
    )
    stdout.write(f"Aether v{LANGUAGE_VERSION} REPL\n")
    stdout.write("Type \\exit or \\quit to leave.\n")

    while True:
        stdout.write("aether> ")
        stdout.flush()
        line = stdin.readline()
        if line == "":
            stdout.write("\n")
            return EXIT_SUCCESS

        source = line.strip()
        if source.lower() in {"\\exit", "\\quit"}:
            return EXIT_SUCCESS
        if not source:
            continue

        try:
            session.run(source)
        except AetherError as exc:
            print(_format_language_error(exc), file=stderr)


def _execute_file(
    source: str,
    *,
    path: Path,
    backend: str,
    stdin: TextIO,
    stdout: TextIO,
) -> None:
    if backend == "ast":
        run_aether(
            source,
            source_root=path.parent,
            output_writer=stdout.write,
            input_reader=stdin.readline,
        )
        return
    if backend == "ir":
        IRBackend().run(
            prepare_typed_program(
                source,
                TypeChecker(source_root=path.parent),
            )
        )
        return
    raise ValueError(f"Unknown backend '{backend}'")


def _print_tokens(source: str, *, stdout: TextIO) -> None:
    for token in tokenize_source(source):
        print(_format_token(token), file=stdout)


def _format_token(token: Token) -> str:
    lexeme = repr(token.lexeme)
    literal = "" if token.literal is None else f" literal={token.literal!r}"
    return f"{token.line}:{token.column} {token.type.value} {lexeme}{literal}"


def _print_ast(source: str, *, stdout: TextIO) -> None:
    print(pformat(parse_source(source), width=100, sort_dicts=False), file=stdout)


def _emit_ir(
    source: str,
    *,
    path: Path,
    stdout: TextIO,
    optimization_profile: "OptimizationProfile" = "O0",
    show_passes: bool = False,
) -> None:
    typed_program = prepare_typed_program(
        source,
        TypeChecker(source_root=path.parent),
    )
    backend = IRBackend()
    module = backend.lower_verified(typed_program)
    if show_passes:
        from .ir.optimizer import build_optimizer_pipeline

        trace = build_optimizer_pipeline(optimization_profile).run_with_trace(module)
        backend.verify(trace[-1].module)
        _print_ir_trace(trace, stdout=stdout)
        return
    if optimization_profile != "O0":
        from .ir.optimizer import build_optimizer_pipeline

        module = backend.optimize_verified(
            module,
            optimizer=build_optimizer_pipeline(optimization_profile),
        )
    print(print_ir(module), file=stdout)


def _emit_cfg(source: str, *, path: Path, stdout: TextIO) -> None:
    from .analysis.cfg import CFGBuilder, DOTPrinter

    typed_program = prepare_typed_program(
        source,
        TypeChecker(source_root=path.parent),
    )
    module = IRBackend().lower(typed_program)
    builder = CFGBuilder()
    printer = DOTPrinter()
    print(
        "\n\n".join(
            printer.to_dot(builder.build(function))
            for function in module.functions
        ),
        file=stdout,
    )


def _optimization_profile_from_args(
    *,
    opt: bool,
    opt_level: str | None,
) -> "OptimizationProfile":
    if opt_level == "0":
        return "O0"
    if opt_level == "1":
        return "O1"
    if opt_level == "2":
        return "O2"
    if opt:
        return "O1"
    return "O0"


def _print_ir_trace(trace: list[OptimizationTraceStep], *, stdout: TextIO) -> None:
    separator = "=" * 40
    for index, step in enumerate(trace):
        if index:
            print(file=stdout)
        title = _format_trace_title(step)
        print(separator, file=stdout)
        print(f"=== {title} ===", file=stdout)
        print(separator, file=stdout)
        print(file=stdout)
        print(print_ir(step.module), file=stdout)


def _format_trace_title(step: OptimizationTraceStep) -> str:
    name = step.label
    if name in {"Lowered IR", "Final IR"}:
        return name
    if " / " in name:
        iteration, pass_name = name.split(" / ", 1)
        title = f"{iteration} / After {pass_name}"
    else:
        title = f"After {name}"
    status = "changed" if step.changed else "no changes"
    stats = ", ".join(f"{key}={value}" for key, value in step.stats.items())
    if stats:
        return f"{title} [{status}, {stats}]"
    return f"{title} [{status}]"


def _print_benchmark_report(report: BenchReport, *, stdout: TextIO) -> None:
    print(f"Benchmark: {report.path}", file=stdout)
    print(f"Iterations: {report.iterations}", file=stdout)
    for timing in report.timings:
        print(file=stdout)
        print(f"{timing.name}:", file=stdout)
        print(f"  total: {_format_seconds(timing.total_seconds)}", file=stdout)
        print(f"  avg: {_format_seconds(timing.average_seconds)}", file=stdout)
    for failure in report.failures:
        print(file=stdout)
        print(f"{failure.name}:", file=stdout)
        print("  error:", file=stdout)
        for line in _format_language_error(failure.error).splitlines():
            print(f"    {line}", file=stdout)


def _format_seconds(value: float) -> str:
    return f"{value:.6f}s"


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return parsed


def _read_source(path: Path, *, stderr: TextIO) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"aether: cannot read '{path}': {exc}", file=stderr)
        return None


def _run_language_action(action: Callable[[], None], *, stderr: TextIO) -> int:
    try:
        action()
    except AetherError as exc:
        print(_format_language_error(exc), file=stderr)
        return EXIT_LANGUAGE_ERROR
    return EXIT_SUCCESS


def _format_language_error(exc: AetherError) -> str:
    if exc.has_details:
        return exc.format()
    return f"{type(exc).__name__}: {exc.message}"


if __name__ == "__main__":
    raise SystemExit(main())
