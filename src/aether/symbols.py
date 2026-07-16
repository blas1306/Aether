from __future__ import annotations

from dataclasses import dataclass

from .types import AetherType, EnumIdentity


@dataclass(frozen=True)
class VariableSymbol:
    name: str
    type_name: AetherType | None
    is_const: bool = False
    visibility: str | None = None
    is_borrowed_iteration: bool = False
    collection_origin: int | None = None


@dataclass(frozen=True)
class FunctionSymbol:
    name: str
    return_type: AetherType | None
    parameters: tuple[VariableSymbol, ...]
    visibility: str | None = None
    is_mutating: bool = False


@dataclass(frozen=True)
class StructSymbol:
    name: str
    fields: tuple[VariableSymbol, ...]
    visibility: str | None = None
    methods: tuple[FunctionSymbol, ...] = ()
    implements: tuple[str, ...] = ()
    kind: str = "struct"
    constructor: FunctionSymbol | None = None


@dataclass(frozen=True)
class EnumSymbol:
    name: str
    variants: tuple[str, ...]
    visibility: str | None = None
    identity: EnumIdentity | None = None


@dataclass(frozen=True)
class InterfaceSymbol:
    name: str
    methods: tuple[FunctionSymbol, ...]
    visibility: str | None = None
