from __future__ import annotations

from dataclasses import fields, is_dataclass, replace
from typing import Any

from .. import ast
from ..errors import IRBackendUnsupportedFeatureError
from ..modules import CheckedModule, CheckedProgram, QualifiedSymbol, SymbolId
from ..types import (
    ArrayType,
    ClassType,
    EnumType,
    InterfaceType,
    ListType,
    MatrixType,
    NullableType,
    RangeType,
    TransposeVectorType,
    TupleType,
    VectorType,
)


def mangle_symbol(symbol: SymbolId) -> str:
    """Return a stable, path-independent internal/LLVM symbol name."""

    module = "_".join(_encode_component(part) for part in str(symbol.module).split("."))
    return f"__ae_m{module}__{symbol.kind}_{_encode_component(symbol.name)}"


def _encode_component(component: str) -> str:
    return f"{len(component)}_{component}"


def combine_checked_program(checked: CheckedProgram) -> ast.Program:
    """Canonicalize a checked graph into one collision-free IR input module.

    This is intentionally a combined-module strategy.  Imports have already
    been resolved by semantic analysis; this pass only translates semantic
    identities into stable backend names.
    """

    if len(checked.modules) == 1:
        return checked.modules[checked.root_module].program

    rewritten: list[ast.Statement] = []
    for module_id in checked.dependency_order():
        module = checked.modules[module_id]
        is_root = module_id == checked.root_module
        _reject_native_module_initialization(module, is_root=is_root)
        rewriter = _ModuleRewriter(module, checked, is_root=is_root)
        for statement in module.program.statements:
            if isinstance(statement, (ast.ImportStatement, ast.FromImportStatement)):
                continue
            rewritten.append(rewriter.statement(statement, top_level=True))
    return ast.Program(rewritten, entry_point="main")


def _reject_native_module_initialization(module: CheckedModule, *, is_root: bool) -> None:
    if is_root:
        return
    declarations = (
        ast.AliasDeclaration,
        ast.ClassDeclaration,
        ast.EnumDeclaration,
        ast.ExpressionFunctionDeclaration,
        ast.FunctionDeclaration,
        ast.ImportStatement,
        ast.FromImportStatement,
        ast.InterfaceDeclaration,
        ast.StructDeclaration,
    )
    for statement in module.program.statements:
        if isinstance(statement, ast.VarDeclaration):
            raise IRBackendUnsupportedFeatureError(
                f"LLVM/native module '{module.id}' cannot compile top-level globals or constants yet; "
                f"'{statement.name}' requires module storage/initialization."
            )
        if not isinstance(statement, declarations):
            raise IRBackendUnsupportedFeatureError(
                f"LLVM/native module '{module.id}' cannot compile executable top-level statements yet; "
                "module initialization remains outside the supported subset."
            )


class _ModuleRewriter:
    def __init__(
        self,
        module: CheckedModule,
        checked: CheckedProgram,
        *,
        is_root: bool,
    ) -> None:
        self.module = module
        self.checked = checked
        self.is_root = is_root
        self.method_names: set[str] = set()

    def statement(self, node: ast.Statement, *, top_level: bool = False) -> ast.Statement:
        if isinstance(node, ast.FunctionDeclaration):
            name = node.name
            if top_level:
                if self.is_root and node.name == "main":
                    name = "main"
                else:
                    symbol = self._own_symbol(node.name, "function")
                    name = mangle_symbol(symbol.id)
            return replace(
                node,
                name=name,
                return_type=self.type_name(node.return_type),
                parameters=[self.parameter(parameter) for parameter in node.parameters],
                body=[self.statement(statement) for statement in node.body],
            )
        if isinstance(node, ast.StructDeclaration):
            symbol = self._own_symbol(node.name, "struct") if top_level else None
            previous_method_names = self.method_names
            self.method_names = {method.name for method in node.methods}
            try:
                methods = [self.statement(method) for method in node.methods]
                constructor = (
                    self.constructor(node.constructor)
                    if node.constructor is not None
                    else None
                )
            finally:
                self.method_names = previous_method_names
            return replace(
                node,
                name=mangle_symbol(symbol.id) if symbol is not None else node.name,
                fields=[self.struct_field(field) for field in node.fields],
                methods=methods,
                constructor=constructor,
                implements=[self.type_name(name) for name in node.implements],
            )
        if isinstance(node, ast.AliasDeclaration):
            symbol = self._own_symbol(node.name, "alias") if top_level else None
            return replace(
                node,
                name=mangle_symbol(symbol.id) if symbol is not None else node.name,
                target_type=self.type_name(node.target_type),
            )
        if isinstance(node, ast.VarDeclaration):
            return replace(
                node,
                type_name=self.type_name(node.type_name),
                initializer=self.value(node.initializer),
            )
        return self.value(node)

    def parameter(self, node: ast.Parameter) -> ast.Parameter:
        return replace(node, type_name=self.type_name(node.type_name))

    def struct_field(self, node: ast.StructField) -> ast.StructField:
        return replace(node, type_name=self.type_name(node.type_name))

    def constructor(self, node: ast.ConstructorDeclaration) -> ast.ConstructorDeclaration:
        return replace(
            node,
            parameters=[self.parameter(parameter) for parameter in node.parameters],
            body=[self.statement(statement) for statement in node.body],
        )

    def type_name(self, type_name: Any) -> Any:
        if isinstance(type_name, str):
            symbol = self.module.symbol_references.get(type_name)
            if symbol is not None and symbol.id.kind in {"alias", "struct", "class", "interface", "enum"}:
                return mangle_symbol(symbol.id)
            return type_name
        if isinstance(type_name, ArrayType):
            return ArrayType(self.type_name(type_name.element_type))
        if isinstance(type_name, ListType):
            return ListType(self.type_name(type_name.element_type))
        if isinstance(type_name, NullableType):
            return NullableType(self.type_name(type_name.base_type))
        if isinstance(type_name, TupleType):
            return TupleType(tuple(self.type_name(item) for item in type_name.element_types))
        if isinstance(type_name, VectorType):
            return VectorType(
                self.type_name(type_name.element_type),
                type_name.length,
                type_name.orientation,
            )
        if isinstance(type_name, TransposeVectorType):
            return TransposeVectorType(
                self.type_name(type_name.element_type),
                type_name.length,
            )
        if isinstance(type_name, MatrixType):
            return MatrixType(
                self.type_name(type_name.element_type),
                type_name.rows,
                type_name.cols,
                type_name.vector,
            )
        if isinstance(type_name, RangeType):
            return RangeType(self.type_name(type_name.element_type))
        if isinstance(type_name, ClassType):
            return ClassType(self.type_name(type_name.name))
        if isinstance(type_name, InterfaceType):
            return InterfaceType(self.type_name(type_name.name))
        if isinstance(type_name, EnumType):
            return EnumType(self.type_name(type_name.name))
        return type_name

    def value(self, node: Any) -> Any:
        if node is None or isinstance(node, (str, int, float, bool, bytes)):
            return node
        if isinstance(node, list):
            return [self.value(item) for item in node]
        if isinstance(node, tuple):
            return tuple(self.value(item) for item in node)
        if isinstance(node, dict):
            return {key: self.value(item) for key, item in node.items()}
        if isinstance(node, ast.CallExpression):
            symbol = self.module.symbol_references.get(node.callee)
            callee = (
                mangle_symbol(symbol.id)
                if symbol is not None
                and symbol.id.kind in {"function", "struct", "alias"}
                and not ("." not in node.callee and node.callee in self.method_names)
                else node.callee
            )
            return replace(
                node,
                callee=callee,
                arguments=[self.value(argument) for argument in node.arguments],
                keyword_arguments={key: self.value(value) for key, value in node.keyword_arguments.items()},
            )
        if isinstance(node, ast.FunctionDeclaration):
            return self.statement(node)
        if isinstance(node, ast.VarDeclaration):
            return self.statement(node)
        if not is_dataclass(node):
            return node
        changes = {field.name: self.value(getattr(node, field.name)) for field in fields(node)}
        return replace(node, **changes)

    def _own_symbol(self, name: str, kind: str) -> QualifiedSymbol:
        symbol = self.module.symbol_references.get(name)
        if symbol is None or symbol.id.module != self.module.id or symbol.id.kind != kind:
            raise ValueError(f"Missing semantic identity for {kind} '{self.module.id}.{name}'.")
        return symbol
