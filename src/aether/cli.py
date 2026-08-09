from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from pprint import pformat
from io import StringIO
import sys
from typing import TYPE_CHECKING, TextIO

from .errors import AetherError
from .diagnostics import (
    DiagnosticCategory,
    EXIT_BY_CATEGORY,
    diagnostic_from_exception,
    render_diagnostic,
)
from .benchmark import BenchReport, run_benchmark
from .ir import print_ir
from .pipeline import (
    DEFAULT_SSA_BUILDER,
    IRBackend,
    IR_MAIN_RESULT_NAME,
    lower_to_verified_ssa,
    parse_source,
    prepare_typed_program,
    tokenize_source,
)
from .runner import run_aether
from .session import AetherSession
from .ssa import print_ssa
from .tokens import Token
from .typechecker import TypeChecker
from .capabilities import CAPABILITY_PROFILE_VERSION
from .version import LANGUAGE_VERSION
from .optimization import (
    DEFAULT_OPTIMIZATION_PROFILE,
    OptimizationProfile,
    optimization_profile,
)

if TYPE_CHECKING:
    from .ir.optimizer import OptimizationTraceStep

EXIT_SUCCESS = 0
EXIT_LANGUAGE_ERROR = 1
EXIT_USAGE_ERROR = 2
EXIT_TOOLCHAIN_ERROR = 3
EXIT_INTERNAL_COMPILER_ERROR = 70
EXIT_INTERRUPTED = 130


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="aether",
        description="Run Aether language programs.",
        epilog=(
            "The default command compiles and runs with LLVM: aether program.ae\n"
            "Forward program arguments explicitly: aether run program.ae -- arg1 arg2\n"
            "Development inspection tools: --tokens, --ast, --emit-ir, "
            "--emit-cfg, --emit-ssa, --emit-llvm, build, and bench"
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
    modes.add_argument(
        "--emit-ssa",
        action="store_true",
        help="Lower the file through verified IR and print verified SSA.",
    )
    modes.add_argument(
        "--emit-llvm",
        action="store_true",
        help="Print LLVM IR produced with the selected optimization profile.",
    )
    modes.add_argument(
        "--check",
        action="store_true",
        help="Check syntax, types, and native capabilities without generating code.",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Show internal details and tracebacks for compiler errors.",
    )
    parser.add_argument(
        "--ssa-builder",
        choices=("pattern", "general"),
        default=None,
        help=(
            "SSA builder for --emit-ssa: general (default) or pattern "
            "(compatibility fallback)."
        ),
    )
    parser.add_argument(
        "--opt",
        action="store_true",
        help="Deprecated alias for -O1.",
    )
    parser.add_argument(
        "-O",
        "--opt-level",
        choices=("0", "1", "2"),
        default=None,
        help=(
            "Compilation profile (default: O0): O0 disables optional Aether passes; "
            "O1 uses the conservative middle-end and clang O1; O2 uses the same "
            "Aether middle-end and clang O2."
        ),
    )
    parser.add_argument(
        "--show-passes",
        action="store_true",
        help="With --emit-ir, print the IR stages for the selected profile.",
    )
    parser.add_argument(
        "--backend",
        choices=("llvm", "ast", "ir"),
        default=None,
        help=(
            "Execution backend for files: llvm (default), ast, or ir "
            "(experimental)."
        ),
    )
    parser.add_argument(
        "--version",
        action="version",
        version=(
            f"Aether {LANGUAGE_VERSION}\n"
            f"Native capability profile {CAPABILITY_PROFILE_VERSION}"
        ),
    )
    return parser


def build_bench_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="aether bench",
        description="Measure Aether programs through development backends.",
    )
    parser.add_argument("file", help="Aether source file to benchmark.")
    parser.add_argument(
        "-O", "--opt-level", choices=("0", "1", "2"), default="0",
        help="Compilation profile for optimization-sensitive measurements (default: O0).",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Show internal details and tracebacks for compiler errors.",
    )
    parser.add_argument(
        "--iterations",
        type=_positive_int,
        default=10,
        help="Number of benchmark iterations. Defaults to 10.",
    )
    parser.add_argument(
        "--backend",
        choices=("ast", "ir", "both", "ssa", "llvm", "native", "all"),
        default="both",
        help="Backend profile to measure. Defaults to both (AST and IR).",
    )
    exit_code = parser.add_mutually_exclusive_group()
    exit_code.add_argument(
        "--expected-exit-code",
        type=int,
        default=0,
        help="Expected native executable exit code. Defaults to 0.",
    )
    exit_code.add_argument(
        "--ignore-exit-code",
        action="store_true",
        help="Explicitly ignore native executable exit codes.",
    )
    return parser


def build_native_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="aether build",
        description="Build an Aether source file to a native executable with clang.",
    )
    parser.add_argument("file", help="Aether source file to build.")
    parser.add_argument(
        "-O", "--opt-level", choices=("0", "1", "2"), default="0",
        help="Compilation profile (default: O0).",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Show internal details and tracebacks for compiler errors.",
    )
    parser.add_argument(
        "-o",
        "--output",
        help=(
            "Executable output path. Defaults to build/<source-name>."
        ),
    )
    parser.add_argument(
        "--keep-llvm",
        action="store_true",
        help="Keep the generated .ll file next to the executable output.",
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
    if argv_list and argv_list[0] == "build":
        return _main_build(argv_list[1:], stdout=stdout, stderr=stderr)
    if argv_list and argv_list[0] == "run":
        argv_list = argv_list[1:]
    argv_list, program_arguments = _split_program_arguments(argv_list)

    parser = build_parser()

    if stdout is sys.stdout and stderr is sys.stderr:
        args = parser.parse_args(argv_list)
    else:
        try:
            with redirect_stdout(stdout), redirect_stderr(stderr):
                args = parser.parse_args(argv_list)
        except SystemExit as exc:
            return int(exc.code)

    if args.ssa_builder is not None and not args.emit_ssa:
        print(
            "aether: error: --ssa-builder is only supported with --emit-ssa.",
            file=stderr,
        )
        return EXIT_USAGE_ERROR
    if args.opt and args.opt_level not in (None, "1"):
        print(
            "aether: error: --opt is an alias for -O1 and conflicts with "
            f"-O{args.opt_level}.",
            file=stderr,
        )
        return EXIT_USAGE_ERROR
    if args.emit_ssa and args.show_passes:
        print(
            "aether: error: --emit-ssa cannot be combined with --show-passes.",
            file=stderr,
        )
        return EXIT_USAGE_ERROR
    if args.emit_llvm and args.show_passes:
        print(
            "aether: error: --emit-llvm cannot be combined with --show-passes.",
            file=stderr,
        )
        return EXIT_USAGE_ERROR
    if args.show_passes and not args.emit_ir:
        print(
            "aether: error: --show-passes requires --emit-ir.",
            file=stderr,
        )
        return EXIT_USAGE_ERROR

    if args.repl:
        if args.backend not in (None, "ast"):
            print("aether: error: --repl only supports --backend=ast for now.", file=stderr)
            return EXIT_USAGE_ERROR
        if args.file is not None:
            print("aether: error: --repl does not accept a file.", file=stderr)
            return EXIT_USAGE_ERROR
        return run_repl(
            stdin=stdin,
            stdout=stdout,
            stderr=stderr,
            debug=args.debug,
        )

    if args.file is None:
        parser.print_help(file=stdout)
        return EXIT_USAGE_ERROR

    path = Path(args.file)
    profile = _optimization_profile_from_args(opt=args.opt, opt_level=args.opt_level)
    source = _read_source(path, stderr=stderr)
    if source is None:
        return EXIT_USAGE_ERROR

    if args.tokens:
        return _run_language_action(
            lambda: _print_tokens(source, stdout=stdout),
            stderr=stderr,
            path=path,
            phase="lexing",
            debug=args.debug,
        )
    if args.ast:
        return _run_language_action(
            lambda: _print_ast(source, stdout=stdout),
            stderr=stderr,
            path=path,
            phase="parsing",
            debug=args.debug,
        )
    if args.emit_ir:
        return _run_language_action(
            lambda: _emit_ir(
                source,
                path=path,
                stdout=stdout,
                optimization_profile=profile,
                show_passes=args.show_passes,
            ),
            stderr=stderr,
            path=path,
            phase=(
                "optimization"
                if args.opt or args.opt_level not in (None, "0")
                else "IR lowering"
            ),
            debug=args.debug,
        )
    if args.emit_cfg:
        return _run_language_action(
            lambda: _emit_cfg(source, path=path, stdout=stdout),
            stderr=stderr,
            path=path,
            phase="IR lowering",
            debug=args.debug,
        )
    if args.emit_ssa:
        return _run_language_action(
            lambda: _emit_ssa(
                source,
                path=path,
                stdout=stdout,
                builder=args.ssa_builder or DEFAULT_SSA_BUILDER,
                optimization_profile=profile,
            ),
            stderr=stderr,
            path=path,
            phase="SSA construction",
            debug=args.debug,
        )
    if args.emit_llvm:
        return _run_language_action(
            lambda: _emit_llvm(source, path=path, stdout=stdout, optimization_profile=profile),
            stderr=stderr,
            path=path,
            phase="LLVM emission",
            debug=args.debug,
        )
    if args.check:
        return _run_language_action(
            lambda: _check_source(source, path=path),
            stderr=stderr,
            path=path,
            phase="checking",
            debug=args.debug,
        )
    return _run_execution_action(
        lambda: _execute_file(
            source,
            path=path,
            backend=args.backend or "llvm",
            stdin=stdin,
            stdout=stdout,
            stderr=stderr,
            program_arguments=program_arguments,
            optimization_profile=profile,
        ),
        stdout=stdout,
        stderr=stderr,
        path=path,
        phase="execution",
        debug=args.debug,
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
            expected_exit_code=None if args.ignore_exit_code else args.expected_exit_code,
            optimization_profile=optimization_profile(args.opt_level),
        )
    except KeyboardInterrupt:
        return _render_interrupted(stderr)
    except Exception as exc:
        return _render_exception(
            exc,
            stderr=stderr,
            path=path,
            phase="benchmark",
            debug=args.debug,
        )

    diagnostics = [
        diagnostic_from_exception(
            failure.error,
            source_path=path,
            phase=f"benchmark: {failure.name}",
        )
        for failure in report.failures
    ]
    has_ice = any(
        item.category is DiagnosticCategory.INTERNAL_COMPILER_ERROR
        for item in diagnostics
    )
    _print_benchmark_report(
        report,
        stdout=stdout,
        include_failures=not has_ice,
    )
    if has_ice:
        for failure, diagnostic in zip(report.failures, diagnostics):
            if diagnostic.category is DiagnosticCategory.INTERNAL_COMPILER_ERROR:
                render_diagnostic(
                    diagnostic,
                    stderr=stderr,
                    exception=failure.error,
                    debug=args.debug,
                )
        return EXIT_INTERNAL_COMPILER_ERROR
    if args.backend in {"ir", "ssa", "llvm", "native"} and report.failures:
        if any(item.category is DiagnosticCategory.TOOLCHAIN for item in diagnostics):
            return EXIT_TOOLCHAIN_ERROR
        return EXIT_LANGUAGE_ERROR
    return EXIT_SUCCESS


def _main_build(argv: Sequence[str], *, stdout: TextIO, stderr: TextIO) -> int:
    parser = build_native_parser()
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

    output_path = (
        Path(args.output)
        if args.output is not None
        else _default_native_output_path(path)
    )
    try:
        result = _build_native(
            source,
            path=path,
            output_path=output_path,
            keep_llvm=args.keep_llvm,
            optimization_profile=optimization_profile(args.opt_level),
        )
    except KeyboardInterrupt:
        return _render_interrupted(stderr)
    except Exception as exc:
        return _render_exception(
            exc,
            stderr=stderr,
            path=path,
            phase="native build",
            debug=args.debug,
        )

    print(f"Built executable: {result.output_path}", file=stdout)
    if result.llvm_path is not None:
        print(f"Kept LLVM IR: {result.llvm_path}", file=stdout)
    return EXIT_SUCCESS


def _default_native_output_path(source_path: Path) -> Path:
    return Path("build") / source_path.stem


def run_repl(
    *,
    stdin: TextIO,
    stdout: TextIO,
    stderr: TextIO,
    debug: bool = False,
) -> int:
    session = AetherSession(
        output_writer=stdout.write,
        input_reader=stdin.readline,
    )
    stdout.write(f"Aether {LANGUAGE_VERSION} REPL\n")
    stdout.write("Type \\exit or \\quit to leave.\n")

    while True:
        stdout.write("aether> ")
        stdout.flush()
        try:
            line = stdin.readline()
        except KeyboardInterrupt:
            print(file=stdout)
            return _render_interrupted(stderr)
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
            _render_exception(
                exc,
                stderr=stderr,
                phase="REPL evaluation",
                debug=debug,
            )
        except KeyboardInterrupt:
            return _render_interrupted(stderr)
        except Exception as exc:
            # The session restores its snapshot before propagating.  An ICE
            # still ends the REPL because other compiler state may be unsafe.
            return _render_exception(
                exc,
                stderr=stderr,
                phase="REPL evaluation",
                debug=debug,
            )


def _execute_file(
    source: str,
    *,
    path: Path,
    backend: str,
    stdin: TextIO,
    stdout: TextIO,
    stderr: TextIO,
    program_arguments: Sequence[str] = (),
    optimization_profile: OptimizationProfile = DEFAULT_OPTIMIZATION_PROFILE,
) -> int:
    if backend == "llvm":
        return _run_native(
            source,
            path=path,
            stdout=stdout,
            stderr=stderr,
            program_arguments=program_arguments,
            optimization_profile=optimization_profile,
        )
    if backend == "ast":
        result = run_aether(
            source,
            source_root=path.parent,
            output_writer=stdout.write,
            input_reader=stdin.readline,
            program_arguments=program_arguments,
        )
        return result.exit_code
    if backend == "ir":
        ir_backend = IRBackend(
            output_writer=stdout.write,
            program_arguments=program_arguments,
        )
        typed_program = prepare_typed_program(
            source,
            TypeChecker(source_root=path.parent, entry_path=path),
        )
        if optimization_profile.ir_passes:
            from .ir.interpreter import IRInterpreter
            from .ir.optimizer import build_optimizer_pipeline
            module = ir_backend.lower_verified(typed_program)
            module = ir_backend.optimize_verified(
                module, optimizer=build_optimizer_pipeline(optimization_profile)
            )
            entry = next(item for item in module.functions if item.name == "main")
            value = IRInterpreter(
                module,
                write_output=stdout.write,
                program_arguments=program_arguments,
            ).call(entry.name)
            return int(value) if value is not None else EXIT_SUCCESS
        env = ir_backend.run(typed_program)
        result = env.lookup(IR_MAIN_RESULT_NAME)
        return int(result.value) if result is not None else EXIT_SUCCESS
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
    optimization_profile: OptimizationProfile = DEFAULT_OPTIMIZATION_PROFILE,
    show_passes: bool = False,
) -> None:
    typed_program = prepare_typed_program(
        source,
        TypeChecker(source_root=path.parent, entry_path=path),
    )
    backend = IRBackend()
    module = backend.lower_verified(typed_program)
    if show_passes:
        from .ir.lifecycle import expand_lifecycle
        from .ir.optimizer import build_optimizer_pipeline

        trace = build_optimizer_pipeline(optimization_profile).run_with_trace(
            expand_lifecycle(module)
        )
        backend.verify(trace[-1].module)
        _print_ir_trace(trace, stdout=stdout)
        return
    if optimization_profile.ir_passes:
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
        TypeChecker(source_root=path.parent, entry_path=path),
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


def _check_source(source: str, *, path: Path) -> None:
    from .capabilities import BackendIdentity, validate_backend_capabilities

    typed_program = prepare_typed_program(
        source,
        TypeChecker(source_root=path.parent, entry_path=path),
    )
    validate_backend_capabilities(typed_program, BackendIdentity.NATIVE)


def _emit_ssa(
    source: str,
    *,
    path: Path,
    stdout: TextIO,
    builder: str = DEFAULT_SSA_BUILDER,
    optimization_profile: OptimizationProfile = DEFAULT_OPTIMIZATION_PROFILE,
) -> None:
    from .errors import AetherRuntimeError
    from .ssa import GeneralSSABuildError, SSABuildError

    typed_program = prepare_typed_program(
        source,
        TypeChecker(source_root=path.parent, entry_path=path),
    )
    try:
        backend = IRBackend()
        ir_module = backend.lower_verified(typed_program)
        if optimization_profile.ir_passes:
            from .ir.optimizer import build_optimizer_pipeline
            ir_module = backend.optimize_verified(
                ir_module, optimizer=build_optimizer_pipeline(optimization_profile)
            )
        module = lower_to_verified_ssa(ir_module, builder=builder)
        from .ssa.optimizer import build_ssa_optimizer_pipeline
        module = build_ssa_optimizer_pipeline(optimization_profile).run(module)
    except SSABuildError as exc:
        raise AetherRuntimeError(str(exc), kind="ssa") from exc
    except GeneralSSABuildError as exc:
        raise AetherRuntimeError(
            f"General SSA builder failed: {exc}",
            kind="ssa",
        ) from exc
    print(print_ssa(module), file=stdout)


def _emit_llvm(source: str, *, path: Path, stdout: TextIO, optimization_profile: OptimizationProfile = DEFAULT_OPTIMIZATION_PROFILE) -> None:
    from .backend.llvm import LLVMBackend, LLVMBackendError
    from .capabilities import BackendIdentity, validate_backend_capabilities
    from .errors import AetherRuntimeError

    typed_program = prepare_typed_program(
        source,
        TypeChecker(source_root=path.parent, entry_path=path),
    )
    validate_backend_capabilities(typed_program, BackendIdentity.NATIVE)
    ir_backend = IRBackend()
    ir_module = ir_backend.lower_verified(typed_program)
    if optimization_profile.ir_passes:
        from .ir.optimizer import build_optimizer_pipeline
        ir_module = ir_backend.optimize_verified(
            ir_module, optimizer=build_optimizer_pipeline(optimization_profile)
        )
    module = lower_to_verified_ssa(ir_module, builder=DEFAULT_SSA_BUILDER)
    from .ssa.optimizer import build_ssa_optimizer_pipeline
    module = build_ssa_optimizer_pipeline(
        optimization_profile, verify_after_each=True
    ).run(module)
    try:
        from .ssa import SSACall

        uses_process_arguments = any(
            isinstance(instruction, SSACall)
            and instruction.builtin == "System.args"
            for function in module.functions
            for block in function.blocks
            for instruction in block.instructions
        )
        if sys.platform == "win32" and uses_process_arguments:
            raise AetherRuntimeError(
                "LLVM/native System.args() is not supported on Windows yet; "
                "explicit UTF-16 argv conversion is pending.",
                kind="llvm",
            )
        llvm_ir = LLVMBackend().emit(module, native_entry=uses_process_arguments)
    except LLVMBackendError as exc:
        raise AetherRuntimeError(str(exc), kind="llvm") from exc
    print(llvm_ir, file=stdout)


def _build_native(
    source: str,
    *,
    path: Path,
    output_path: Path,
    keep_llvm: bool,
    optimization_profile: OptimizationProfile = DEFAULT_OPTIMIZATION_PROFILE,
):
    from .backend.llvm import LLVMBackendError, LLVMBuilder
    from .errors import AetherRuntimeError

    typed_program = prepare_typed_program(
        source,
        TypeChecker(source_root=path.parent, entry_path=path),
    )
    try:
        return LLVMBuilder(optimization_profile=optimization_profile).build(
            typed_program,
            output_path=output_path,
            keep_llvm=keep_llvm,
        )
    except LLVMBackendError as exc:
        raise AetherRuntimeError(str(exc), kind="llvm") from exc


def _run_native(
    source: str,
    *,
    path: Path,
    stdout: TextIO,
    stderr: TextIO,
    program_arguments: Sequence[str] = (),
    optimization_profile: OptimizationProfile = DEFAULT_OPTIMIZATION_PROFILE,
) -> int:
    from .backend.llvm import LLVMBackendError, LLVMBuilder, LLVMRunError, LLVMRunner
    from .errors import AetherRuntimeError

    typed_program = prepare_typed_program(
        source,
        TypeChecker(source_root=path.parent, entry_path=path),
    )
    try:
        return LLVMRunner(
            builder=LLVMBuilder(optimization_profile=optimization_profile)
        ).run(
            typed_program,
            stdout=stdout,
            stderr=stderr,
            program_arguments=program_arguments,
        )
    except LLVMRunError as exc:
        raise AetherRuntimeError(str(exc), kind="llvm") from exc
    except LLVMBackendError as exc:
        raise AetherRuntimeError(str(exc), kind="llvm") from exc


def _optimization_profile_from_args(
    *,
    opt: bool,
    opt_level: str | None,
) -> OptimizationProfile:
    if opt_level == "0":
        return optimization_profile("O0")
    if opt_level == "1":
        return optimization_profile("O1")
    if opt_level == "2":
        return optimization_profile("O2")
    if opt:
        return optimization_profile("O1")
    return DEFAULT_OPTIMIZATION_PROFILE


def _split_program_arguments(argv: Sequence[str]) -> tuple[list[str], list[str]]:
    """Split once at the CLI boundary; shell quoting is already resolved."""

    values = list(argv)
    try:
        separator = values.index("--")
    except ValueError:
        return values, []
    return values[:separator], values[separator + 1 :]


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


def _print_benchmark_report(
    report: BenchReport,
    *,
    stdout: TextIO,
    include_failures: bool = True,
) -> None:
    print(f"Benchmark: {report.path}", file=stdout)
    print(f"Iterations: {report.iterations}", file=stdout)
    print(f"Optimization profile: {report.optimization_profile.name}", file=stdout)
    print(f"Failures: {len(report.failures)}", file=stdout)
    for timing in report.timings:
        print(file=stdout)
        print(f"{timing.name}:", file=stdout)
        print(f"  category: {timing.category}", file=stdout)
        print(f"  total: {_format_seconds(timing.total_seconds)}", file=stdout)
        print(f"  avg: {_format_seconds(timing.average_seconds)}", file=stdout)
    for failure in report.failures:
        if not include_failures:
            continue
        print(file=stdout)
        print(f"{failure.name}:", file=stdout)
        print(f"  category: {failure.category}", file=stdout)
        print("  unsupported:" if failure.unsupported else "  error:", file=stdout)
        diagnostic = diagnostic_from_exception(
            failure.error,
            source_path=report.path,
            phase=f"benchmark: {failure.name}",
        )
        rendered = StringIO()
        render_diagnostic(diagnostic, stderr=rendered)
        for line in rendered.getvalue().rstrip().splitlines():
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
    except UnicodeDecodeError as exc:
        print(
            f"aether: cannot read '{path}': source is not valid UTF-8 "
            f"(byte {exc.start})",
            file=stderr,
        )
        return None
    except OSError as exc:
        print(f"aether: cannot read '{path}': {exc}", file=stderr)
        return None


def _run_language_action(
    action: Callable[[], None],
    *,
    stderr: TextIO,
    path: Path | None = None,
    phase: str | None = None,
    debug: bool = False,
) -> int:
    try:
        action()
    except KeyboardInterrupt:
        return _render_interrupted(stderr)
    except BrokenPipeError:
        return EXIT_LANGUAGE_ERROR
    except Exception as exc:
        return _render_exception(
            exc,
            stderr=stderr,
            path=path,
            phase=phase,
            debug=debug,
        )
    return EXIT_SUCCESS


def _run_execution_action(
    action: Callable[[], int],
    *,
    stdout: TextIO,
    stderr: TextIO,
    path: Path | None = None,
    phase: str | None = None,
    debug: bool = False,
) -> int:
    try:
        return action()
    except AetherError as exc:
        if exc.message.startswith("Aether panic:"):
            print(exc.message, file=stdout)
            return EXIT_LANGUAGE_ERROR
        return _render_exception(
            exc,
            stderr=stderr,
            path=path,
            phase=phase,
            debug=debug,
        )
    except KeyboardInterrupt:
        return _render_interrupted(stderr)
    except BrokenPipeError:
        return EXIT_LANGUAGE_ERROR
    except Exception as exc:
        return _render_exception(
            exc,
            stderr=stderr,
            path=path,
            phase=phase,
            debug=debug,
        )


def _render_exception(
    exc: Exception,
    *,
    stderr: TextIO,
    path: Path | None = None,
    phase: str | None = None,
    debug: bool = False,
) -> int:
    diagnostic = diagnostic_from_exception(exc, source_path=path, phase=phase)
    render_diagnostic(
        diagnostic,
        stderr=stderr,
        exception=exc,
        debug=debug,
    )
    return EXIT_BY_CATEGORY[diagnostic.category]


def _render_interrupted(stderr: TextIO) -> int:
    print("Aether interrupted.", file=stderr)
    return EXIT_INTERRUPTED


if __name__ == "__main__":
    raise SystemExit(main())
