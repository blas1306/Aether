from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar, Literal, Protocol

from . import ast
from .capabilities import BackendIdentity, validate_backend_capabilities
from .errors import AetherRuntimeError, IRBackendUnsupportedFeatureError
from .entry_point import normalize_entry_point
from .interpreter import Environment, Interpreter
from .lexer import lex
from .modules import CheckedProgram, build_checked_program, with_root_program
from .parser import Parser
from .tokens import Token
from .typechecker import TypeChecker
from .types import AetherType, AetherValue

if TYPE_CHECKING:
    from .ir.model import IRFunction
    from .ir.model import IRModule
    from .ir.shadow_verifier import (
        ShadowVerificationStage,
        VerifierAuthorityPipeline,
    )
    from .ir.types import IRType
    from .ssa import SSAModule


IR_MAIN_RESULT_NAME = "__ir_main_result"
SSABuilderName = Literal["pattern", "general"]
DEFAULT_SSA_BUILDER: SSABuilderName = "general"


@dataclass(frozen=True)
class TypedProgram:
    """A parsed program after the current typechecker has accepted it."""

    program: ast.Program
    checker: TypeChecker
    checked_program: CheckedProgram


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
class SSACompileResult:
    """Internal SSA preparation result for compiler-only consumers."""

    ir_module: IRModule
    ssa_module: SSAModule


@dataclass(frozen=True)
class ASTBackend:
    """Current production backend backed by the AST interpreter."""

    interpreter: Interpreter

    name: ClassVar[str] = "ast"

    def run(self, typed_program: TypedProgram) -> Environment:
        validate_backend_capabilities(typed_program, BackendIdentity.AST)
        return run_ast_backend(typed_program.program, self.interpreter)


class IRBackend:
    """Experimental executable IR backend for the current scalar function subset."""

    name: ClassVar[str] = "ir"

    def __init__(
        self,
        *,
        output_writer: Callable[[str], None] | None = None,
        program_arguments: Sequence[str] = (),
        shadow_verifier: VerifierAuthorityPipeline | None = None,
    ) -> None:
        self.output_writer = output_writer
        self.program_arguments = tuple(program_arguments)
        self.verification_pipeline = shadow_verifier
        self.last_initial_ir_authority_provenance: object | None = None
        # Compatibility attribute for the existing explicit shadow harness.
        self.shadow_verifier = shadow_verifier
        self.output = ""

    def lower(self, typed_program: TypedProgram) -> IRModule:
        from .ir.lowering import IRLowerer

        return IRLowerer().lower_checked_program(typed_program.checked_program)

    def verify(
        self,
        module: IRModule,
        *,
        stage: ShadowVerificationStage | None = None,
    ) -> IRModule:
        from .ir.shadow_verifier import (
            AuthoritativeVerificationError,
            ShadowVerificationStage,
        )
        from .ir.verifier import IRVerificationError, IRVerifier

        try:
            if (
                self.verification_pipeline is None
                or stage is ShadowVerificationStage.POST_OPTIMIZATION
            ):
                return IRVerifier(module).verify()
            if stage is None:
                stage = ShadowVerificationStage.INITIAL
            return self.verification_pipeline.verify(module, stage=stage)
        except (IRVerificationError, AuthoritativeVerificationError) as exc:
            location = getattr(exc, "source_location", None)
            raise AetherRuntimeError(
                f"IR verifier rejected module: {exc}",
                line=getattr(location, "line", None),
                column=getattr(location, "column", None),
                kind="ir",
            ) from exc

    def lower_verified(self, typed_program: TypedProgram) -> IRModule:
        module = self.lower(typed_program)
        if self.verification_pipeline is not None:
            return self.verify(module)

        return self.admit_initial_ir(module)

    def admit_initial_ir(self, module: IRModule) -> IRModule:
        """Apply the exclusive Rust product authority to pre-lifecycle IR."""

        # RUST-IR-3 product admission: the module is exactly the object emitted
        # by IRLowerer (or supplied to the internal compiler boundary). Rust
        # verify_module alone decides before lifecycle expansion or SSA.
        from .ir.shadow_verifier import (
            AuthoritativeVerificationError,
            ShadowVerificationStage,
            production_initial_ir_admission_pipeline,
        )
        from .ir.verifier import IRVerificationError

        pipeline = production_initial_ir_admission_pipeline()
        try:
            verified = pipeline.verify(
                module,
                stage=ShadowVerificationStage.INITIAL,
            )
            self.last_initial_ir_authority_provenance = getattr(
                pipeline, "last_provenance", None
            )
            return verified
        except (IRVerificationError, AuthoritativeVerificationError) as exc:
            self.last_initial_ir_authority_provenance = getattr(
                pipeline, "last_provenance", None
            )
            location = getattr(exc, "source_location", None)
            raise AetherRuntimeError(
                f"IR verifier rejected module: {exc}",
                line=getattr(location, "line", None),
                column=getattr(location, "column", None),
                kind="ir",
            ) from exc

    def optimize_verified(
        self,
        module: IRModule,
        optimizer: IROptimizer | None = None,
    ) -> IRModule:
        from .ir.lifecycle import expand_lifecycle
        from .ir.optimizer import OptimizerPipeline

        pipeline = (
            optimizer
            if optimizer is not None
            else OptimizerPipeline(iterative=True)
        )
        # LifecycleExpander remains the productive lifecycle authority. The
        # resulting post-lifecycle representation is outside Rust Initial IR's
        # contract and Python IRVerifier is no longer a productive gate.
        optimized = pipeline.run(expand_lifecycle(module))
        if self.verification_pipeline is None:
            return optimized
        from .ir.shadow_verifier import ShadowVerificationStage

        # Explicit custom/debug coordinators preserve their post-optimization
        # oracle behavior without affecting the default product path.
        return self.verify(optimized, stage=ShadowVerificationStage.POST_OPTIMIZATION)

    def run(self, typed_program: TypedProgram) -> Environment:
        from .ir.interpreter import IRExecutionError, IRInterpreter
        from .ir.types import VoidType

        module = self.lower_verified(typed_program)
        entry = _ir_entry_point(module)
        self.output = ""
        interpreter = IRInterpreter(
            module,
            write_output=self.output_writer,
            program_arguments=self.program_arguments,
        )

        try:
            result = interpreter.call(entry.name)
        except IRExecutionError as exc:
            self.output = interpreter.output
            raise AetherRuntimeError(
                f"IR interpreter failed: {exc}",
                kind="ir",
            ) from exc
        self.output = interpreter.output

        env = Environment()
        if not isinstance(entry.return_type, VoidType):
            env.define(
                IR_MAIN_RESULT_NAME,
                AetherValue(_aether_type(entry.return_type), result),
            )
        return env


class SSAPipeline:
    """Internal TypedProgram/IRModule to verified SSA pipeline."""

    def __init__(self, *, builder: SSABuilderName = DEFAULT_SSA_BUILDER,
                 authority_configuration: object | None = None,
                 rust_shadow_client: object | None = None) -> None:
        self.builder = builder
        self.authority_configuration = authority_configuration
        self.rust_shadow_client = rust_shadow_client
        self.last_authority_report: object | None = None
        self.last_returned_ssa_origin: str | None = None

    def lower_ir(self, typed_program: TypedProgram) -> IRModule:
        return IRBackend().lower_verified(typed_program)

    def build(self, module: IRModule) -> SSAModule:
        from .ssa import GeneralSSABuilder, SSABuilder
        from .ssa.shadow import (
            SSALoweringAuthorityConfiguration, SSALoweringAuthorityMode,
            default_rust_ssa_lowering_client,
            lower_with_rust_authority,
            lower_with_rust_shadow,
        )
        from .ssa.shadow_independent import (
            lower_with_shadow_independent_rust_authority,
        )

        if self.builder == "pattern":
            self.last_returned_ssa_origin = "python_pattern_builder"
            return SSABuilder().build(module)
        if self.builder == "general":
            configuration = self.authority_configuration
            if configuration is None:
                configuration = SSALoweringAuthorityConfiguration()
            if not isinstance(configuration, SSALoweringAuthorityConfiguration):
                raise TypeError("authority_configuration must be an SSALoweringAuthorityConfiguration")
            if configuration.mode is SSALoweringAuthorityMode.PYTHON_SSA_AUTHORITY_RUST_SHADOW:
                client = (
                    self.rust_shadow_client
                    if self.rust_shadow_client is not None
                    else default_rust_ssa_lowering_client()
                )
                authoritative, report = lower_with_rust_shadow(module, client)  # type: ignore[arg-type]
                self.last_authority_report = report
                self.last_returned_ssa_origin = "python_general_ssa_builder"
                return authoritative  # type: ignore[return-value]
            if configuration.mode is SSALoweringAuthorityMode.RUST_SSA_AUTHORITY_PYTHON_SHADOW:
                client = (
                    self.rust_shadow_client
                    if self.rust_shadow_client is not None
                    else default_rust_ssa_lowering_client()
                )
                authoritative, report = lower_with_rust_authority(module, client)  # type: ignore[arg-type]
                self.last_authority_report = report
                self.last_returned_ssa_origin = "rust_schema_v2_import"
                return authoritative  # type: ignore[return-value]
            if configuration.mode is SSALoweringAuthorityMode.RUST_SSA_AUTHORITY_REFINEMENT_VERIFIED:
                client = (
                    self.rust_shadow_client
                    if self.rust_shadow_client is not None
                    else default_rust_ssa_lowering_client()
                )
                authoritative, trace = lower_with_shadow_independent_rust_authority(
                    module, client  # type: ignore[arg-type]
                )
                self.last_authority_report = trace
                self.last_returned_ssa_origin = "rust_schema_v2_import"
                return authoritative
            if configuration.mode is SSALoweringAuthorityMode.PYTHON_SSA_ONLY:
                self.last_returned_ssa_origin = "python_general_ssa_builder"
                return GeneralSSABuilder().build(module)
            raise AssertionError("unhandled SSA lowering authority mode")
        raise ValueError(f"Unknown SSA builder '{self.builder}'.")

    def verify(self, module: SSAModule) -> SSAModule:
        from .ssa import SSAVerificationError, SSAVerifier

        try:
            return SSAVerifier(module).verify()
        except SSAVerificationError as exc:
            raise AetherRuntimeError(
                f"SSA verifier rejected module: {exc}",
                kind="ssa",
            ) from exc

    def run(self, program: TypedProgram | IRModule) -> SSACompileResult:
        if isinstance(program, TypedProgram):
            ir_module = self.lower_ir(program)
        else:
            ir_module = IRBackend().admit_initial_ir(program)

        ssa_module = self.verify(self.build(ir_module))
        return SSACompileResult(ir_module, ssa_module)


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
    checked_program = typecheck_program(program, checker)
    semantic_program = build_checked_program(checked_program, checker)
    normalized = normalize_entry_point(checked_program, checker)
    return TypedProgram(
        normalized,
        checker,
        with_root_program(semantic_program, normalized),
    )


def lower_to_verified_ssa(
    program: TypedProgram | IRModule,
    *,
    builder: SSABuilderName = DEFAULT_SSA_BUILDER,
) -> SSAModule:
    """Prepare verified SSA for internal compiler consumers only."""
    return SSAPipeline(builder=builder).run(program).ssa_module


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
            "IR backend cannot execute a declaration-only module without an entry point."
        )
    if function.parameters:
        raise IRBackendUnsupportedFeatureError(
            "Normalized IR entry point main() must not declare parameters."
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
