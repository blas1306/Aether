from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar, Protocol

from . import ast
from .errors import AetherRuntimeError, IRBackendUnsupportedFeatureError
from .interpreter import Environment, Interpreter
from .lexer import lex
from .parser import Parser
from .tokens import Token
from .typechecker import TypeChecker
from .types import AetherType, AetherValue

if TYPE_CHECKING:
    from .ir.model import IRFunction
    from .ir.model import IRModule
    from .ir.types import IRType


IR_MAIN_RESULT_NAME = "__ir_main_result"


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


class IROptimizer(Protocol):
    """Internal boundary for IR-to-IR optimization passes or pipelines."""

    def run(self, module: IRModule) -> IRModule:
        """Return an optimized IR module."""
        ...


@dataclass(frozen=True)
class ASTBackend:
    """Current production backend backed by the AST interpreter."""

    interpreter: Interpreter

    name: ClassVar[str] = "ast"

    def run(self, typed_program: TypedProgram) -> Environment:
        return run_ast_backend(typed_program.program, self.interpreter)


class IRBackend:
    """Experimental executable IR backend for the current scalar function subset."""

    name: ClassVar[str] = "ir"

    def lower(self, typed_program: TypedProgram) -> IRModule:
        from .ir.lowering import IRLowerer

        return IRLowerer().lower(typed_program.program)

    def verify(self, module: IRModule) -> IRModule:
        from .ir.verifier import IRVerificationError, IRVerifier

        try:
            return IRVerifier(module).verify()
        except IRVerificationError as exc:
            raise AetherRuntimeError(
                f"IR verifier rejected module: {exc}",
                kind="ir",
            ) from exc

    def lower_verified(self, typed_program: TypedProgram) -> IRModule:
        return self.verify(self.lower(typed_program))

    def optimize_verified(
        self,
        module: IRModule,
        optimizer: IROptimizer | None = None,
    ) -> IRModule:
        from .ir.optimizer import OptimizerPipeline

        pipeline = optimizer if optimizer is not None else OptimizerPipeline()
        return self.verify(pipeline.run(module))

    def run(self, typed_program: TypedProgram) -> Environment:
        from .ir.interpreter import IRExecutionError, IRInterpreter
        from .ir.types import VoidType

        module = self.lower_verified(typed_program)
        entry = _ir_entry_point(module)

        try:
            result = IRInterpreter(module).call(entry.name)
        except IRExecutionError as exc:
            raise AetherRuntimeError(
                f"IR interpreter failed: {exc}",
                kind="ir",
            ) from exc

        env = Environment()
        if not isinstance(entry.return_type, VoidType):
            env.define(
                IR_MAIN_RESULT_NAME,
                AetherValue(_aether_type(entry.return_type), result),
            )
        return env


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


def _ir_entry_point(module: IRModule) -> IRFunction:
    function = next(
        (candidate for candidate in module.functions if candidate.name == "main"),
        None,
    )
    if function is None:
        raise IRBackendUnsupportedFeatureError(
            "IR backend execution requires a zero-argument main() function."
        )
    if function.parameters:
        raise IRBackendUnsupportedFeatureError(
            "IR backend entry point main() must not declare parameters yet."
        )
    return function


def _aether_type(type_: IRType) -> AetherType:
    from .ir.types import BoolType, ComplexType, DoubleType, FloatType, IntType, StringType

    if isinstance(type_, IntType):
        return "int"
    if isinstance(type_, FloatType):
        return "float"
    if isinstance(type_, DoubleType):
        return "double"
    if isinstance(type_, ComplexType):
        return "complex"
    if isinstance(type_, BoolType):
        return "boolean"
    if isinstance(type_, StringType):
        return "string"
    raise IRBackendUnsupportedFeatureError(
        f"IR backend cannot publish main() result of type '{type_}' yet."
    )
