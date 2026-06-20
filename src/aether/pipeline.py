from __future__ import annotations

from . import ast
from .interpreter import Environment, Interpreter
from .lexer import lex
from .parser import Parser
from .tokens import Token
from .typechecker import TypeChecker


def tokenize_source(source: str) -> list[Token]:
    """Run the lexical stage of the Aether pipeline."""
    return lex(source)


def parse_source(source: str) -> ast.Program:
    """Run the lexical and parsing stages of the Aether pipeline."""
    return Parser(tokenize_source(source)).parse()


def execute_pipeline(
    source: str,
    *,
    type_checker: TypeChecker,
    interpreter: Interpreter,
) -> Environment:
    """Run the canonical Aether pipeline with the supplied runtime state."""
    program = parse_source(source)
    type_checker.check(program)
    return interpreter.interpret(program)

