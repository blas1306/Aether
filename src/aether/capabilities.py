from __future__ import annotations

from dataclasses import dataclass, fields, is_dataclass
from enum import Enum
from types import MappingProxyType
from typing import TYPE_CHECKING, Mapping

from . import ast
from .errors import AetherError
from .types import (
    AetherType,
    ArrayType,
    ClassType,
    EnumType,
    FunctionType,
    InterfaceType,
    ListType,
    MatrixType,
    NullType,
    NullableType,
    TransposeVectorType,
    TupleType,
    VectorType,
)
from .scalar_math import (
    EXPERIMENTAL_SCALAR_MATH_FUNCTIONS,
    SCALAR_MATH_OPERATIONS,
)

if TYPE_CHECKING:
    from .pipeline import TypedProgram


CAPABILITY_PROFILE_VERSION = "4"


class BackendIdentity(str, Enum):
    AST = "ast"
    NATIVE = "native"


class CapabilityState(str, Enum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    UNSUPPORTED = "unsupported"


class Capability(str, Enum):
    PRIMITIVE_TYPES = "primitive-types"
    VARIABLES_AND_CONST = "variables-and-const"
    ARITHMETIC = "arithmetic"
    INTEGER_SAFETY = "integer-safety"
    FUNCTIONS = "functions"
    VOID_FUNCTIONS = "void-functions"
    FUNCTION_VALUES = "function-values"
    RETURN = "return"
    IF = "if"
    WHILE = "while"
    FOR = "for"
    FOR_IN = "for-in"
    BREAK = "break"
    CONTINUE = "continue"
    STRINGS = "strings"
    PRINT = "print"
    INPUT = "input"
    PROCESS_ARGUMENTS = "process-arguments"
    MODULES = "modules"
    IMPORTS = "imports"
    STRUCTS = "structs"
    STRUCT_CONSTRUCTORS = "struct-constructors"
    STRUCT_METHODS = "struct-methods"
    CLASSES = "classes"
    CLASS_CONSTRUCTORS = "class-constructors"
    CLASS_METHODS = "class-methods"
    INTERFACES = "interfaces"
    ENUMS = "enums"
    ARRAY = "array"
    ARRAY_SLICING = "array-slicing"
    LIST = "list"
    VECTOR = "vector"
    MATRIX = "matrix"
    SCALAR_MATH = "scalar-math"
    GENERICS = "generics"
    ERROR_HANDLING = "error-handling"
    FILES = "files"
    OPTIMIZATION_PROFILES = "optimization-profiles"


@dataclass(frozen=True)
class CapabilityDefinition:
    capability: Capability
    description: str
    diagnostic_code: str


@dataclass(frozen=True)
class CapabilitySupport:
    state: CapabilityState
    description: str


@dataclass(frozen=True)
class BackendCapabilityProfile:
    backend: BackendIdentity
    version: str
    capabilities: Mapping[Capability, CapabilitySupport]

    def __post_init__(self) -> None:
        if not self.version:
            raise ValueError("Capability profile version must not be empty.")
        unknown = set(self.capabilities) - set(Capability)
        missing = set(Capability) - set(self.capabilities)
        if unknown:
            raise ValueError(f"Unknown backend capabilities: {sorted(map(str, unknown))}")
        if missing:
            names = ", ".join(sorted(capability.value for capability in missing))
            raise ValueError(f"Backend profile is missing capabilities: {names}")
        for capability, support in self.capabilities.items():
            if not isinstance(capability, Capability):
                raise ValueError(f"Unknown backend capability: {capability!r}")
            if not isinstance(support.state, CapabilityState):
                raise ValueError(
                    f"Invalid state for capability '{capability.value}': {support.state!r}"
                )
        object.__setattr__(self, "capabilities", MappingProxyType(dict(self.capabilities)))

    def support_for(self, capability: Capability) -> CapabilitySupport:
        if not isinstance(capability, Capability):
            raise ValueError(f"Unknown backend capability: {capability!r}")
        return self.capabilities[capability]


def _definition(capability: Capability, description: str) -> CapabilityDefinition:
    code = "AE-BACKEND-" + capability.value.upper().replace("-", "_")
    return CapabilityDefinition(capability, description, code)


CAPABILITY_CATALOG: Mapping[Capability, CapabilityDefinition] = MappingProxyType(
    {
        definition.capability: definition
        for definition in (
            _definition(Capability.PRIMITIVE_TYPES, "Primitive scalar and nullable types."),
            _definition(Capability.VARIABLES_AND_CONST, "Variable and const declarations."),
            _definition(Capability.ARITHMETIC, "Scalar arithmetic and comparisons."),
            _definition(Capability.INTEGER_SAFETY, "Checked i32 arithmetic and division."),
            _definition(Capability.FUNCTIONS, "Typed functions, parameters, calls, and recursion."),
            _definition(Capability.VOID_FUNCTIONS, "Functions and calls returning void."),
            _definition(
                Capability.FUNCTION_VALUES,
                "Typed top-level callable values plus AST expression-function compatibility.",
            ),
            _definition(Capability.RETURN, "Function return statements."),
            _definition(Capability.IF, "Conditional control flow."),
            _definition(Capability.WHILE, "While loops."),
            _definition(Capability.FOR, "Inclusive integer range loops."),
            _definition(Capability.FOR_IN, "Iteration over collection values."),
            _definition(Capability.BREAK, "Loop break statements."),
            _definition(Capability.CONTINUE, "Loop continue statements."),
            _definition(Capability.STRINGS, "String values and string operations."),
            _definition(Capability.PRINT, "print and println output."),
            _definition(Capability.INPUT, "Typed input calls."),
            _definition(Capability.PROCESS_ARGUMENTS, "Access to process arguments."),
            _definition(Capability.MODULES, "Package and module units."),
            _definition(Capability.IMPORTS, "Module and symbol imports."),
            _definition(Capability.STRUCTS, "Struct values and fields."),
            _definition(Capability.STRUCT_CONSTRUCTORS, "Struct constructors."),
            _definition(Capability.STRUCT_METHODS, "Struct methods and this."),
            _definition(Capability.CLASSES, "Reference-semantics classes."),
            _definition(Capability.CLASS_CONSTRUCTORS, "Class constructors."),
            _definition(Capability.CLASS_METHODS, "Class methods and this."),
            _definition(Capability.INTERFACES, "Interfaces, conformance, and dispatch."),
            _definition(Capability.ENUMS, "Enums without payloads."),
            _definition(Capability.ARRAY, "Array values and operations."),
            _definition(Capability.ARRAY_SLICING, "Array and collection slicing."),
            _definition(Capability.LIST, "List values and operations."),
            _definition(Capability.VECTOR, "Vector values and operations."),
            _definition(Capability.MATRIX, "Matrix values and operations."),
            _definition(Capability.SCALAR_MATH, "Scalar mathematical functions and constants."),
            _definition(Capability.GENERICS, "User-defined generic declarations."),
            _definition(Capability.ERROR_HANDLING, "throw and try/catch error handling."),
            _definition(Capability.FILES, "Language-level file input and output."),
            _definition(Capability.OPTIMIZATION_PROFILES, "Selectable compiler optimization profiles."),
        )
    }
)

if len(CAPABILITY_CATALOG) != len(Capability):
    raise RuntimeError("The backend capability catalog contains duplicate or missing entries.")


def _profile(
    backend: BackendIdentity,
    states: Mapping[Capability, CapabilityState],
) -> BackendCapabilityProfile:
    return BackendCapabilityProfile(
        backend=backend,
        version=CAPABILITY_PROFILE_VERSION,
        capabilities={
            capability: CapabilitySupport(
                states[capability],
                CAPABILITY_CATALOG[capability].description,
            )
            for capability in Capability
        },
    )


_AST_UNSUPPORTED = {
    Capability.PROCESS_ARGUMENTS,
    Capability.GENERICS,
    Capability.FILES,
    Capability.OPTIMIZATION_PROFILES,
}
_AST_PARTIAL = {Capability.FUNCTION_VALUES}
AST_CAPABILITY_PROFILE = _profile(
    BackendIdentity.AST,
    {
        capability: (
            CapabilityState.UNSUPPORTED
            if capability in _AST_UNSUPPORTED
            else CapabilityState.PARTIAL
            if capability in _AST_PARTIAL
            else CapabilityState.COMPLETE
        )
        for capability in Capability
    },
)

_NATIVE_COMPLETE = {
    Capability.INTEGER_SAFETY,
    Capability.VOID_FUNCTIONS,
    Capability.RETURN,
    Capability.IF,
    Capability.WHILE,
    Capability.FOR,
    Capability.BREAK,
    Capability.CONTINUE,
}
_NATIVE_UNSUPPORTED = {
    Capability.INPUT,
    Capability.PROCESS_ARGUMENTS,
    Capability.CLASSES,
    Capability.CLASS_CONSTRUCTORS,
    Capability.CLASS_METHODS,
    Capability.INTERFACES,
    Capability.ENUMS,
    Capability.GENERICS,
    Capability.ERROR_HANDLING,
    Capability.FILES,
}
NATIVE_CAPABILITY_PROFILE = _profile(
    BackendIdentity.NATIVE,
    {
        capability: (
            CapabilityState.COMPLETE
            if capability in _NATIVE_COMPLETE
            else CapabilityState.UNSUPPORTED
            if capability in _NATIVE_UNSUPPORTED
            else CapabilityState.PARTIAL
        )
        for capability in Capability
    },
)

BACKEND_CAPABILITY_PROFILES: Mapping[BackendIdentity, BackendCapabilityProfile] = (
    MappingProxyType(
        {
            BackendIdentity.AST: AST_CAPABILITY_PROFILE,
            BackendIdentity.NATIVE: NATIVE_CAPABILITY_PROFILE,
        }
    )
)

# COMPLETE is intentionally tied to an explicit E2E evidence registration. The
# tests assert this invariant; adding a capability here requires adding or citing
# an end-to-end backend test in tests/aether/test_backend_capabilities.py.
E2E_TESTED_CAPABILITIES: Mapping[BackendIdentity, frozenset[Capability]] = MappingProxyType(
    {
        BackendIdentity.AST: frozenset(
            {
                Capability.PRIMITIVE_TYPES,
                Capability.VARIABLES_AND_CONST,
                Capability.ARITHMETIC,
                Capability.INTEGER_SAFETY,
                Capability.FUNCTIONS,
                Capability.VOID_FUNCTIONS,
                Capability.RETURN,
                Capability.IF,
                Capability.WHILE,
                Capability.FOR,
                Capability.FOR_IN,
                Capability.BREAK,
                Capability.CONTINUE,
                Capability.STRINGS,
                Capability.PRINT,
                Capability.INPUT,
                Capability.MODULES,
                Capability.IMPORTS,
                Capability.STRUCTS,
                Capability.STRUCT_CONSTRUCTORS,
                Capability.STRUCT_METHODS,
                Capability.CLASSES,
                Capability.CLASS_CONSTRUCTORS,
                Capability.CLASS_METHODS,
                Capability.INTERFACES,
                Capability.ENUMS,
                Capability.ARRAY,
                Capability.ARRAY_SLICING,
                Capability.LIST,
                Capability.VECTOR,
                Capability.MATRIX,
                Capability.SCALAR_MATH,
                Capability.ERROR_HANDLING,
            }
        ),
        BackendIdentity.NATIVE: frozenset(
            {
                Capability.INTEGER_SAFETY,
                Capability.VOID_FUNCTIONS,
                Capability.RETURN,
                Capability.IF,
                Capability.WHILE,
                Capability.FOR,
                Capability.BREAK,
                Capability.CONTINUE,
            }
        ),
    }
)


@dataclass(frozen=True)
class CapabilityRequirement:
    capability: Capability
    line: int
    column: int
    detail: str | None = None
    requires_complete_support: bool = False


@dataclass(frozen=True)
class BackendCapabilityIssue:
    backend: BackendIdentity
    requirement: CapabilityRequirement
    state: CapabilityState
    diagnostic_code: str
    message: str
    hint: str | None


class BackendCapabilityError(AetherError):
    """One or more valid language features are unavailable in a backend."""

    def __init__(self, issues: tuple[BackendCapabilityIssue, ...]) -> None:
        if not issues:
            raise ValueError("BackendCapabilityError requires at least one issue.")
        first = issues[0]
        super().__init__(
            first.message,
            line=first.requirement.line,
            column=first.requirement.column,
            hint=first.hint,
            kind=first.diagnostic_code,
        )
        self.issues = issues

    def format(self) -> str:
        if len(self.issues) == 1:
            return super().format()
        lines = ["BackendCapabilityError [backend-capability]:"]
        for issue in self.issues:
            requirement = issue.requirement
            lines.append(
                f"  line {requirement.line}, column {requirement.column} "
                f"[{issue.diagnostic_code}] {issue.message}"
            )
            if issue.hint:
                lines.append(f"    Hint: {issue.hint}")
        return "\n".join(lines)


_SCALAR_MATH_FUNCTIONS = frozenset(SCALAR_MATH_OPERATIONS)
_FUNCTION_PLOT_BUILTINS = {"Plots.plot", "Plots.plot!"}


class _CapabilityDetector:
    def __init__(self, typed_program: TypedProgram) -> None:
        self.typed_program = typed_program
        self.checker = typed_program.checker
        self._requirements: dict[Capability, CapabilityRequirement] = {}
        self._function_depth = 0

    def detect(self) -> tuple[CapabilityRequirement, ...]:
        checked = self.typed_program.checked_program
        for module_id in checked.dependency_order():
            module = checked.modules[module_id]
            self._visit(module.program)
            if module_id != checked.root_module:
                self._record_imported_initialization_requirements(module.program)
        return tuple(self._requirements.values())

    def _record_imported_initialization_requirements(self, program: ast.Program) -> None:
        declarations = (
            ast.AliasDeclaration,
            ast.ClassDeclaration,
            ast.EnumDeclaration,
            ast.ExpressionFunctionDeclaration,
            ast.FunctionDeclaration,
            ast.FromImportStatement,
            ast.ImportStatement,
            ast.InterfaceDeclaration,
            ast.StructDeclaration,
        )
        for statement in program.statements:
            detail: str | None = None
            if isinstance(statement, ast.VarDeclaration):
                detail = "imported top-level globals/constants and module initialization"
            elif not isinstance(statement, declarations):
                detail = "executable statements in an imported module"
            if detail is None:
                continue
            self._record(
                Capability.MODULES,
                statement,
                detail=detail,
                requires_complete_support=True,
            )
            self._record(
                Capability.IMPORTS,
                statement,
                detail=detail,
                requires_complete_support=True,
            )
            return

    def _record(
        self,
        capability: Capability,
        node: object,
        *,
        detail: str | None = None,
        requires_complete_support: bool = False,
    ) -> None:
        line, column = _source_location(node)
        current = self._requirements.get(capability)
        requirement = CapabilityRequirement(
            capability,
            line,
            column,
            detail,
            requires_complete_support,
        )
        if current is None or (
            requires_complete_support and not current.requires_complete_support
        ):
            self._requirements[capability] = requirement

    def _visit(self, node: object) -> None:
        if node is None or isinstance(node, (str, int, float, bool, bytes, Enum)):
            return
        if isinstance(node, dict):
            for value in node.values():
                self._visit(value)
            return
        if isinstance(node, (list, tuple)):
            for value in node:
                self._visit(value)
            return

        self._record_node(node)
        if isinstance(node, ast.FunctionDeclaration):
            self._function_depth += 1
            try:
                self._visit_dataclass(node)
            finally:
                self._function_depth -= 1
            return
        self._visit_dataclass(node)

    def _visit_dataclass(self, node: object) -> None:
        if not is_dataclass(node):
            return
        for field in fields(node):
            self._visit(getattr(node, field.name))

    def _record_node(self, node: object) -> None:
        if isinstance(node, ast.Program):
            if node.package_name is not None:
                self._record(Capability.MODULES, node, detail="package declaration")
            return
        if isinstance(node, (ast.ImportStatement, ast.FromImportStatement)):
            self._record(Capability.MODULES, node, detail="imported module")
            self._record(Capability.IMPORTS, node, detail="import declaration")
            return
        if isinstance(node, ast.VarDeclaration):
            self._record(
                Capability.VARIABLES_AND_CONST,
                node,
                detail="inferred variable declaration" if node.type_name is None else None,
                requires_complete_support=node.type_name is None,
            )
            self._record_type(node.type_name, node)
            return
        if isinstance(node, ast.Parameter):
            self._record_type(node.type_name, node)
            return
        if isinstance(node, ast.InterfaceMethodSignature):
            self._record_type(node.return_type, node)
            for parameter in node.parameters:
                self._record_type(parameter.type_name, node)
            return
        if isinstance(node, ast.FunctionDeclaration):
            if not node.synthetic:
                self._record(
                    Capability.FUNCTIONS,
                    node,
                    detail="nested function" if self._function_depth else None,
                    requires_complete_support=self._function_depth > 0,
                )
            if node.return_type == "void":
                self._record(Capability.VOID_FUNCTIONS, node)
            self._record_type(node.return_type, node)
            for parameter in node.parameters:
                self._record_type(parameter.type_name, node)
            return
        if isinstance(node, ast.ExpressionFunctionDeclaration):
            self._record(
                Capability.FUNCTION_VALUES,
                node,
                detail="expression function",
                requires_complete_support=True,
            )
            return
        if isinstance(node, ast.ReturnStatement):
            self._record(Capability.RETURN, node)
            return
        if isinstance(node, ast.IfStatement):
            self._record(Capability.IF, node)
            return
        if isinstance(node, ast.WhileStatement):
            self._record(Capability.WHILE, node)
            return
        if isinstance(node, ast.ForInStatement):
            capability = Capability.FOR if isinstance(node.iterable, ast.RangeExpression) else Capability.FOR_IN
            self._record(capability, node)
            return
        if isinstance(node, ast.BreakStatement):
            self._record(Capability.BREAK, node)
            return
        if isinstance(node, ast.ContinueStatement):
            self._record(Capability.CONTINUE, node)
            return
        if isinstance(node, ast.StructDeclaration):
            self._record(Capability.STRUCTS, node)
            if node.constructor is not None:
                self._record(Capability.STRUCT_CONSTRUCTORS, node.constructor)
            if node.methods:
                self._record(Capability.STRUCT_METHODS, node.methods[0])
            for field in node.fields:
                self._record_type(field.type_name, field)
            return
        if isinstance(node, ast.ClassDeclaration):
            self._record(Capability.CLASSES, node)
            if node.constructor is not None:
                self._record(Capability.CLASS_CONSTRUCTORS, node.constructor)
            if node.methods:
                self._record(Capability.CLASS_METHODS, node.methods[0])
            for field in node.fields:
                self._record_type(field.type_name, field)
            return
        if isinstance(node, ast.InterfaceDeclaration):
            self._record(Capability.INTERFACES, node)
            return
        if isinstance(node, ast.EnumDeclaration):
            self._record(Capability.ENUMS, node)
            return
        if isinstance(node, (ast.ThrowStatement, ast.TryCatchStatement)):
            self._record(Capability.ERROR_HANDLING, node)
            return
        if isinstance(node, ast.InterpolatedString):
            self._record(
                Capability.STRINGS,
                node,
                detail="interpolated string",
                requires_complete_support=True,
            )
            return
        if isinstance(node, ast.Literal):
            self._record_type(node.type_name, node)
            if node.type_name == "string":
                self._record(Capability.STRINGS, node)
            return
        if isinstance(node, ast.Identifier):
            canonical = self._canonical_name(node.name, constants=True)
            if canonical == "Math.pi":
                self._record(Capability.SCALAR_MATH, node)
            return
        if isinstance(node, ast.FieldAccess):
            dotted = _dotted_name(node)
            if dotted is not None and self._canonical_name(dotted, constants=True) == "Math.pi":
                self._record(Capability.SCALAR_MATH, node)
            return
        if isinstance(node, ast.BinaryExpression):
            self._record(Capability.ARITHMETIC, node)
            if _contains_int_literal(node):
                self._record(Capability.INTEGER_SAFETY, node)
            if node.operator == "%" and _contains_double_literal(node):
                self._record(
                    Capability.ARITHMETIC,
                    node,
                    detail="double remainder",
                    requires_complete_support=True,
                )
            if node.operator in {"+", "==", "!="} and _contains_string_literal(node):
                detail = (
                    "string binary operations"
                    if node.operator == "+"
                    else "string comparisons"
                )
                self._record(
                    Capability.STRINGS,
                    node,
                    detail=detail,
                    requires_complete_support=True,
                )
            return
        if isinstance(node, ast.UnaryExpression):
            self._record(Capability.ARITHMETIC, node)
            return
        if isinstance(node, ast.InputCall):
            self._record(Capability.INPUT, node)
            return
        if isinstance(node, ast.CallExpression):
            self._record_call(node)
            return
        if isinstance(node, ast.ArrayLiteral):
            self._record(Capability.ARRAY, node)
            return
        if isinstance(node, ast.ListLiteral):
            self._record(Capability.LIST, node)
            return
        if isinstance(node, ast.MatrixLiteral):
            self._record(Capability.VECTOR if node.vector else Capability.MATRIX, node)
            return
        if isinstance(node, ast.SliceExpression):
            self._record(Capability.ARRAY_SLICING, node)

    def _record_call(self, call: ast.CallExpression) -> None:
        canonical = self._canonical_name(call.callee)
        if canonical in {"print", "println"}:
            self._record(Capability.PRINT, call)
        if canonical in _SCALAR_MATH_FUNCTIONS:
            experimental = canonical in EXPERIMENTAL_SCALAR_MATH_FUNCTIONS
            self._record(
                Capability.SCALAR_MATH,
                call,
                detail=(
                    f"experimental scalar builtin '{canonical}'"
                    if experimental
                    else None
                ),
                requires_complete_support=experimental,
            )
        if (
            canonical in _FUNCTION_PLOT_BUILTINS
            and call.arguments
            and isinstance(call.arguments[0], ast.Identifier)
            and call.arguments[0].name in self.checker.functions
        ):
            self._record(
                Capability.FUNCTION_VALUES,
                call.arguments[0],
                detail="function passed as a value",
                requires_complete_support=True,
            )
        symbol = self.checker.structs.get(call.callee)
        if symbol is not None:
            self._record(
                Capability.CLASS_CONSTRUCTORS if symbol.kind == "class" else Capability.STRUCT_CONSTRUCTORS,
                call,
            )

    def _canonical_name(self, visible_name: str, *, constants: bool = False) -> str:
        aliases = (
            self.checker.builtin_constant_aliases
            if constants
            else self.checker.builtin_aliases
        )
        canonical = aliases.get(visible_name)
        if canonical is not None:
            return canonical
        root, separator, remainder = visible_name.partition(".")
        module = self.checker.module_bindings.get(root)
        if module is not None and separator:
            return f"{module}.{remainder}"
        return visible_name

    def _record_type(self, type_name: AetherType | None, node: object) -> None:
        if isinstance(type_name, FunctionType):
            self._record(
                Capability.FUNCTION_VALUES,
                node,
                detail="typed capture-free top-level callable",
            )
            for parameter_type in type_name.parameter_types:
                self._record_type(parameter_type, node)
            self._record_type(type_name.return_type, node)
            return
        if type_name is None:
            return
        if isinstance(type_name, ArrayType):
            self._record(Capability.ARRAY, node)
            self._record_type(type_name.element_type, node)
            return
        if isinstance(type_name, ListType):
            self._record(Capability.LIST, node)
            self._record_type(type_name.element_type, node)
            return
        if isinstance(type_name, (VectorType, TransposeVectorType)):
            self._record(Capability.VECTOR, node)
            self._record_type(type_name.element_type, node)
            return
        if isinstance(type_name, MatrixType):
            self._record(Capability.MATRIX, node)
            self._record_type(type_name.element_type, node)
            return
        if isinstance(type_name, TupleType):
            for element_type in type_name.element_types:
                self._record_type(element_type, node)
            return
        if isinstance(type_name, ClassType):
            self._record(Capability.CLASSES, node)
            return
        if isinstance(type_name, InterfaceType):
            self._record(Capability.INTERFACES, node)
            return
        if isinstance(type_name, EnumType):
            self._record(Capability.ENUMS, node)
            return
        if isinstance(type_name, NullableType):
            self._record(
                Capability.PRIMITIVE_TYPES,
                node,
                detail="nullable type",
                requires_complete_support=True,
            )
            self._record_type(type_name.base_type, node)
            return
        if isinstance(type_name, NullType) or type_name in {"float", "complex"}:
            self._record(
                Capability.PRIMITIVE_TYPES,
                node,
                detail=f"type '{type_name}'",
                requires_complete_support=True,
            )
            return
        if isinstance(type_name, str) and type_name in {
            "int",
            "double",
            "boolean",
            "string",
            "void",
            "Exception",
        }:
            self._record(Capability.PRIMITIVE_TYPES, node)


def detect_required_capabilities(
    typed_program: TypedProgram,
) -> tuple[CapabilityRequirement, ...]:
    """Return deduplicated capabilities required by a checked Aether program."""
    return _CapabilityDetector(typed_program).detect()


def backend_capability_issues(
    typed_program: TypedProgram,
    backend: BackendIdentity,
) -> tuple[BackendCapabilityIssue, ...]:
    profile = BACKEND_CAPABILITY_PROFILES[backend]
    issues: list[BackendCapabilityIssue] = []
    for requirement in detect_required_capabilities(typed_program):
        support = profile.support_for(requirement.capability)
        partial_subset_is_supported = (
            backend is BackendIdentity.AST
            and requirement.capability is Capability.FUNCTION_VALUES
        )
        rejected = support.state is CapabilityState.UNSUPPORTED or (
            support.state is CapabilityState.PARTIAL
            and requirement.requires_complete_support
            and not partial_subset_is_supported
        )
        if not rejected:
            continue
        definition = CAPABILITY_CATALOG[requirement.capability]
        state_label = "does not support" if support.state is CapabilityState.UNSUPPORTED else "has only partial support for"
        detail = f" ({requirement.detail})" if requirement.detail else ""
        backend_label = "AST" if backend is BackendIdentity.AST else "LLVM/native"
        if (
            backend is BackendIdentity.NATIVE
            and requirement.capability is Capability.STRINGS
            and requirement.detail in {"string binary operations", "string comparisons"}
        ):
            message = (
                f"LLVM backend does not support {requirement.detail} yet; "
                "capability 'strings' is partial in LLVM/native."
            )
        else:
            message = (
                f"The {backend_label} backend {state_label} capability "
                f"'{requirement.capability.value}'{detail}."
            )
        hint = _ast_hint(typed_program, requirement, backend)
        issues.append(
            BackendCapabilityIssue(
                backend,
                requirement,
                support.state,
                definition.diagnostic_code,
                message,
                hint,
            )
        )
    return tuple(issues)


def validate_backend_capabilities(
    typed_program: TypedProgram,
    backend: BackendIdentity,
) -> None:
    """Reject backend-incompatible features before backend-specific lowering."""
    issues = backend_capability_issues(typed_program, backend)
    if issues:
        raise BackendCapabilityError(issues)


def _ast_hint(
    typed_program: TypedProgram,
    requirement: CapabilityRequirement,
    backend: BackendIdentity,
) -> str | None:
    if backend is BackendIdentity.AST:
        return None
    ast_support = AST_CAPABILITY_PROFILE.support_for(requirement.capability)
    ast_rejected = ast_support.state is CapabilityState.UNSUPPORTED or (
        ast_support.state is CapabilityState.PARTIAL
        and requirement.requires_complete_support
        and requirement.capability is not Capability.FUNCTION_VALUES
    )
    if ast_rejected:
        return None
    return (
        "This is valid Aether for the current AST profile; run it with "
        "'aether --backend=ast'."
    )


def _contains_string_literal(node: object) -> bool:
    if isinstance(node, ast.Literal):
        return node.type_name == "string"
    if isinstance(node, ast.BinaryExpression):
        return _contains_string_literal(node.left) or _contains_string_literal(node.right)
    return False


def _contains_double_literal(node: object) -> bool:
    if isinstance(node, ast.Literal):
        return node.type_name == "double"
    if isinstance(node, ast.UnaryExpression):
        return _contains_double_literal(node.operand)
    if isinstance(node, ast.BinaryExpression):
        return _contains_double_literal(node.left) or _contains_double_literal(node.right)
    return False


def _contains_int_literal(node: object) -> bool:
    if isinstance(node, ast.Literal):
        return node.type_name == "int"
    if isinstance(node, ast.UnaryExpression):
        return _contains_int_literal(node.operand)
    if isinstance(node, ast.BinaryExpression):
        return _contains_int_literal(node.left) or _contains_int_literal(node.right)
    return False


def _dotted_name(node: object) -> str | None:
    if isinstance(node, ast.Identifier):
        return node.name
    if isinstance(node, ast.FieldAccess):
        target = _dotted_name(node.target)
        return f"{target}.{node.field_name}" if target is not None else None
    return None


def _source_location(node: object) -> tuple[int, int]:
    line = getattr(node, "line", None)
    column = getattr(node, "column", None)
    if isinstance(line, int) and isinstance(column, int):
        return max(1, line), max(1, column)
    column_position = getattr(node, "column_position", None)
    if isinstance(line, int) and isinstance(column_position, int):
        return max(1, line), max(1, column_position)
    if isinstance(node, ast.ExpressionStatement):
        return _source_location(node.expression)
    if isinstance(node, (ast.IfStatement, ast.WhileStatement)):
        return _source_location(node.condition)
    if isinstance(node, ast.ForInStatement):
        return _source_location(node.iterable)
    if isinstance(node, (ast.ArrayLiteral, ast.ListLiteral)) and node.elements:
        return _source_location(node.elements[0])
    if isinstance(node, ast.MatrixLiteral) and node.rows and node.rows[0]:
        return _source_location(node.rows[0][0])
    if isinstance(node, ast.Program) and node.statements:
        return _source_location(node.statements[0])
    return 1, 1
