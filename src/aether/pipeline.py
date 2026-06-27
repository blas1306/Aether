from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar, Protocol

from . import ast
from .interpreter import Environment, Interpreter
from .lexer import lex
from .parser import Parser
from .tokens import Token
from .typechecker import TypeChecker

if TYPE_CHECKING:
    from .ir.model import IRModule


@dataclass(frozen=True)
class TypedProgram:
    """A parsed program after the current typechecker has accepted it."""

    program: ast.Program
    checker: TypeChecker


class PipelineBackend(Protocol):
    """Internal execution backend boundary for typed Aether programs."""

    name: ClassVar[str]

    def run(self, typed_program: TypedProgram) -> Environment:
        """Execute or compile a typed program through this backend."""
        ...


@dataclass(frozen=True)
class ASTBackend:
    """Current production backend backed by the AST interpreter."""

    interpreter: Interpreter

    name: ClassVar[str] = "ast"

    def run(self, typed_program: TypedProgram) -> Environment:
        return run_ast_backend(typed_program.program, self.interpreter)


class IRBackend:
    """Experimental IR backend placeholder, intentionally not public CLI state."""

    name: ClassVar[str] = "ir"

    def lower(self, typed_program: TypedProgram) -> IRModule:
        from .ir.lowering import IRLowerer

        return IRLowerer().lower(typed_program.program)

    def run(self, typed_program: TypedProgram) -> Environment:
        raise NotImplementedError(
            "The IR backend is experimental and is not connected to the public pipeline."
        )


def tokenize_source(source: str) -> list[Token]:
    """Run the lexical stage of the Aether pipeline."""
    return lex(source)


def parse_source(source: str) -> ast.Program:
    """Run the lexical and parsing stages of the Aether pipeline."""
    return Parser(tokenize_source(source)).parse()


def typecheck_program(program: ast.Program, checker: TypeChecker) -> ast.Program:
    """Run semantic analysis over a parsed program."""
    checker.check(program)
    return program


def prepare_typed_program(source: str, checker: TypeChecker) -> TypedProgram:
    """Run the frontend stages and return the checked program boundary."""
    program = parse_source(source)
    return TypedProgram(typecheck_program(program, checker), checker)


def run_ast_backend(program: ast.Program, interpreter: Interpreter) -> Environment:
    """Execute a checked program with the current AST interpreter backend."""
    return interpreter.interpret(program)


def execute_pipeline(
    source: str,
    *,
    type_checker: TypeChecker,
    interpreter: Interpreter,
) -> Environment:
    """Run the canonical Aether pipeline with the supplied runtime state."""
    typed_program = prepare_typed_program(source, type_checker)
    backend: PipelineBackend = ASTBackend(interpreter)
    return backend.run(typed_program)
