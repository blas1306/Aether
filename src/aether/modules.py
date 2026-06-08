from __future__ import annotations

from pathlib import Path


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
                ast.EnumDeclaration,
                ast.FunctionDeclaration,
                ast.ExpressionFunctionDeclaration,
            ),
        ) and not is_public_export(statement.visibility, getattr(program, "package_name", None)):
            names.add(statement.name)
    return names
