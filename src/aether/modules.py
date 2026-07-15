from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, Mapping, NewType

if TYPE_CHECKING:
    from . import ast
    from .typechecker import TypeChecker


ModuleId = NewType("ModuleId", str)


@dataclass(frozen=True, order=True)
class SymbolId:
    module: ModuleId
    name: str
    kind: str


@dataclass(frozen=True)
class QualifiedSymbol:
    id: SymbolId
    source_name: str
    qualified_name: str
    visibility: str | None
    exported: bool


@dataclass(frozen=True)
class ResolvedImport:
    visible_name: str
    canonical_name: str
    target_module: ModuleId | None
    target_symbol: SymbolId | None
    builtin: bool = False


@dataclass(frozen=True)
class CheckedModule:
    """Canonical, checked view of one source module.

    The checker remains available for backend-independent semantic queries, but
    imports are already represented by stable module/symbol identities.  A
    backend never needs to read source files or resolve import text again.
    """

    id: ModuleId
    canonical_path: Path
    program: "ast.Program"
    checker: "TypeChecker"
    dependencies: tuple[ModuleId, ...]
    declarations: tuple[QualifiedSymbol, ...]
    exported_symbols: Mapping[str, QualifiedSymbol]
    private_symbols: Mapping[str, QualifiedSymbol]
    imports: tuple[ResolvedImport, ...]
    symbol_references: Mapping[str, QualifiedSymbol]


@dataclass(frozen=True)
class CheckedProgram:
    """A complete multi-module program accepted by semantic analysis."""

    root_module: ModuleId
    modules: Mapping[ModuleId, CheckedModule]

    def module(self, module_id: ModuleId) -> CheckedModule:
        return self.modules[module_id]

    def dependency_order(self) -> tuple[ModuleId, ...]:
        """Return a deterministic dependency-first order, ending in the root."""

        ordered: list[ModuleId] = []
        visited: set[ModuleId] = set()

        def visit(module_id: ModuleId) -> None:
            if module_id in visited:
                return
            visited.add(module_id)
            module = self.modules[module_id]
            for dependency in module.dependencies:
                visit(dependency)
            ordered.append(module_id)

        visit(self.root_module)
        return tuple(ordered)


def default_source_root(source_root: str | Path | None = None) -> Path:
    if source_root is None:
        return Path.cwd()
    return Path(source_root).expanduser().resolve()


def resolve_file_module_path(module_name: str, source_root: str | Path | None = None) -> Path:
    module_path = Path(module_name.replace(".", "/"))
    if module_path.suffix == "":
        module_path = module_path.with_suffix(".ae")
    if module_path.is_absolute():
        return module_path
    return default_source_root(source_root) / module_path


def declared_top_level_names(program: object) -> set[str]:
    from . import ast

    names: set[str] = set()
    for statement in getattr(program, "statements", []):
        if isinstance(
            statement,
            (
                ast.VarDeclaration,
                ast.AliasDeclaration,
                ast.StructDeclaration,
                ast.ClassDeclaration,
                ast.InterfaceDeclaration,
                ast.EnumDeclaration,
                ast.FunctionDeclaration,
                ast.ExpressionFunctionDeclaration,
            ),
        ):
            names.add(statement.name)
    return names


def is_public_export(visibility: str | None, package_name: str | None) -> bool:
    if package_name is None:
        return True
    return visibility == "public"


def private_top_level_names(program: object) -> set[str]:
    from . import ast

    if getattr(program, "package_name", None) is None:
        return set()
    names: set[str] = set()
    for statement in getattr(program, "statements", []):
        if isinstance(
            statement,
            (
                ast.VarDeclaration,
                ast.AliasDeclaration,
                ast.StructDeclaration,
                ast.ClassDeclaration,
                ast.InterfaceDeclaration,
                ast.EnumDeclaration,
                ast.FunctionDeclaration,
                ast.ExpressionFunctionDeclaration,
            ),
        ) and not is_public_export(statement.visibility, getattr(program, "package_name", None)):
            names.add(statement.name)
    return names


def build_checked_program(
    root_program: "ast.Program",
    root_checker: "TypeChecker",
) -> CheckedProgram:
    """Materialize the canonical semantic unit from typechecker-owned modules."""

    from . import ast

    root_id = ModuleId(root_program.package_name or "__entry__")
    raw_modules: dict[ModuleId, tuple[ast.Program, TypeChecker, Path, tuple[ModuleId, ...]]] = {}

    def collect(
        module_id: ModuleId,
        program: ast.Program,
        checker: TypeChecker,
        path: Path,
    ) -> None:
        existing = raw_modules.get(module_id)
        if existing is not None:
            if existing[2] != path:
                raise ValueError(
                    f"Module identity '{module_id}' resolved to both '{existing[2]}' and '{path}'."
                )
            return
        dependencies = tuple(
            sorted(ModuleId(name) for name in _direct_file_dependencies(program, checker))
        )
        raw_modules[module_id] = (program, checker, path, dependencies)
        loaded = checker.loaded_file_modules
        for name in _direct_file_dependencies(program, checker):
            dependency_program, dependency_checker = loaded[name]
            dependency_path = resolve_file_module_path(name, checker.source_root).resolve()
            collect(ModuleId(name), dependency_program, dependency_checker, dependency_path)

    root_path = root_checker.entry_path or (root_checker.source_root / "<entry>")
    collect(root_id, root_program, root_checker, root_path)

    symbol_index: dict[str, QualifiedSymbol] = {}
    declarations_by_module: dict[ModuleId, tuple[QualifiedSymbol, ...]] = {}
    for module_id, (program, _checker, _path, _dependencies) in raw_modules.items():
        declarations: list[QualifiedSymbol] = []
        for statement in program.statements:
            kind = _declaration_kind(statement)
            if kind is None:
                continue
            exported = is_public_export(statement.visibility, program.package_name)
            symbol_id = SymbolId(module_id, statement.name, kind)
            symbol = QualifiedSymbol(
                symbol_id,
                statement.name,
                f"{module_id}.{statement.name}",
                statement.visibility,
                exported,
            )
            declarations.append(symbol)
            symbol_index[symbol.qualified_name] = symbol
        declarations_by_module[module_id] = tuple(declarations)

    checked_modules: dict[ModuleId, CheckedModule] = {}
    for module_id, (program, checker, path, dependencies) in raw_modules.items():
        declarations = declarations_by_module[module_id]
        exported = {symbol.source_name: symbol for symbol in declarations if symbol.exported}
        private = {symbol.source_name: symbol for symbol in declarations if not symbol.exported}
        resolved_imports: list[ResolvedImport] = []
        references: dict[str, QualifiedSymbol] = {
            symbol.source_name: symbol for symbol in declarations
        }

        module_imports, symbol_imports = _resolved_import_bindings(program, checker)
        for visible_name, canonical_name in module_imports:
            target_module = ModuleId(canonical_name) if ModuleId(canonical_name) in raw_modules else None
            resolved_imports.append(
                ResolvedImport(
                    visible_name,
                    canonical_name,
                    target_module,
                    None,
                    builtin=target_module is None,
                )
            )
            if target_module is not None:
                for name, symbol in (
                    (candidate.source_name, candidate)
                    for candidate in declarations_by_module[target_module]
                    if candidate.exported
                ):
                    references[f"{visible_name}.{name}"] = symbol

        for visible_name, canonical_name in symbol_imports:
            target = symbol_index.get(canonical_name)
            resolved_imports.append(
                ResolvedImport(
                    visible_name,
                    canonical_name,
                    target.id.module if target is not None else None,
                    target.id if target is not None else None,
                    builtin=target is None,
                )
            )
            if target is not None:
                references[visible_name] = target

        checked_modules[module_id] = CheckedModule(
            module_id,
            path,
            program,
            checker,
            dependencies,
            declarations,
            MappingProxyType(exported),
            MappingProxyType(private),
            tuple(resolved_imports),
            MappingProxyType(references),
        )

    return CheckedProgram(root_id, MappingProxyType(checked_modules))


def with_root_program(checked: CheckedProgram, program: "ast.Program") -> CheckedProgram:
    """Return the same semantic graph with the normalized executable root AST."""

    root = checked.modules[checked.root_module]
    modules = dict(checked.modules)
    modules[checked.root_module] = CheckedModule(
        root.id,
        root.canonical_path,
        program,
        root.checker,
        root.dependencies,
        root.declarations,
        root.exported_symbols,
        root.private_symbols,
        root.imports,
        root.symbol_references,
    )
    return CheckedProgram(checked.root_module, MappingProxyType(modules))


def _declaration_kind(statement: object) -> str | None:
    from . import ast

    kinds = (
        (ast.VarDeclaration, "global"),
        (ast.AliasDeclaration, "alias"),
        (ast.StructDeclaration, "struct"),
        (ast.ClassDeclaration, "class"),
        (ast.InterfaceDeclaration, "interface"),
        (ast.EnumDeclaration, "enum"),
        (ast.FunctionDeclaration, "function"),
        (ast.ExpressionFunctionDeclaration, "function"),
    )
    for node_type, kind in kinds:
        if isinstance(statement, node_type):
            return kind
    return None


def _direct_file_dependencies(program: "ast.Program", checker: "TypeChecker") -> tuple[str, ...]:
    from . import ast

    loaded = checker.loaded_file_modules
    dependencies: list[str] = []
    for statement in program.statements:
        candidate: str | None = None
        if isinstance(statement, ast.ImportStatement):
            candidate = statement.module_name
        elif isinstance(statement, ast.FromImportStatement):
            submodule = f"{statement.module_name}.{statement.symbol}"
            candidate = submodule if submodule in loaded else statement.module_name
        if candidate in loaded and candidate not in dependencies:
            dependencies.append(candidate)
    return tuple(dependencies)


def _resolved_import_bindings(
    program: "ast.Program",
    checker: "TypeChecker",
) -> tuple[tuple[tuple[str, str], ...], tuple[tuple[str, str], ...]]:
    from . import ast

    modules: list[tuple[str, str]] = []
    symbols: list[tuple[str, str]] = []
    for statement in program.statements:
        if isinstance(statement, ast.ImportStatement):
            modules.append(
                (
                    statement.local_binding,
                    checker.module_bindings.get(
                        statement.local_binding,
                        statement.module_name,
                    ),
                )
            )
        elif isinstance(statement, ast.FromImportStatement):
            module = checker.module_bindings.get(statement.local_binding)
            if module is not None:
                modules.append((statement.local_binding, module))
            else:
                symbols.append(
                    (
                        statement.local_binding,
                        checker.imported_symbol_origins.get(
                            statement.local_binding,
                            f"{statement.module_name}.{statement.symbol}",
                        ),
                    )
                )
    return tuple(modules), tuple(symbols)
