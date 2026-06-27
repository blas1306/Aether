from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from pprint import pformat
import sys
from typing import TextIO

from .errors import AetherError
from .ir import print_ir
from .pipeline import IRBackend, parse_source, prepare_typed_program, tokenize_source
from .runner import run_aether
from .session import AetherSession
from .tokens import Token
from .typechecker import TypeChecker
from .version import LANGUAGE_VERSION

EXIT_SUCCESS = 0
EXIT_LANGUAGE_ERROR = 1
EXIT_USAGE_ERROR = 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="aether",
        description="Run Aether language programs.",
        epilog=(
            "The default command is file execution: aether program.ae\n"
            "Development inspection tools: --tokens and --ast"
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
    parser = build_parser()

    if stdout is sys.stdout and stderr is sys.stderr:
        args = parser.parse_args(argv)
    else:
        try:
            with redirect_stdout(stdout), redirect_stderr(stderr):
                args = parser.parse_args(argv)
        except SystemExit as exc:
            return int(exc.code)

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
            lambda: _emit_ir(source, path=path, stdout=stdout),
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


def _emit_ir(source: str, *, path: Path, stdout: TextIO) -> None:
    typed_program = prepare_typed_program(
        source,
        TypeChecker(source_root=path.parent),
    )
    module = IRBackend().lower_verified(typed_program)
    print(print_ir(module), file=stdout)


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
