from __future__ import annotations

from dataclasses import dataclass, field
from typing import Generic, TypeVar

from .errors import AetherRuntimeError, AetherTypeError


T = TypeVar("T")


@dataclass
class Scope(Generic[T]):
    parent: "Scope[T] | None" = None
    symbols: dict[str, T] = field(default_factory=dict)
    constants: set[str] = field(default_factory=set)

    def define_local(self, name: str, symbol: T, *, forbid_shadowing: bool = False, is_const: bool = False) -> None:
        if self.exists_local(name):
            raise AetherTypeError(f"Variable '{name}' is already defined in this scope.")
        if forbid_shadowing and self.exists_in_parent(name):
            raise AetherTypeError(f"Variable '{name}' already exists in an outer scope; shadowing is not allowed.")
        self.symbols[name] = symbol
        if is_const:
            self.constants.add(name)

    def exists_local(self, name: str) -> bool:
        return name in self.symbols

    def exists_in_parent(self, name: str) -> bool:
        return self.parent is not None and self.parent.resolve_scope(name) is not None

    def resolve_scope(self, name: str) -> "Scope[T] | None":
        if name in self.symbols:
            return self
        if self.parent is None:
            return None
        return self.parent.resolve_scope(name)

    def lookup(self, name: str) -> T | None:
        scope = self.resolve_scope(name)
        if scope is None:
            return None
        return scope.symbols[name]

    def require(self, name: str) -> T:
        symbol = self.lookup(name)
        if symbol is None:
            raise AetherRuntimeError(f"Undefined variable '{name}'.")
        return symbol

    def assign_existing(self, name: str, symbol: T) -> bool:
        scope = self.resolve_scope(name)
        if scope is None:
            return False
        if scope.is_const(name):
            raise AetherTypeError(f"Cannot assign to constant '{name}'.")
        scope.symbols[name] = symbol
        return True

    def is_const(self, name: str) -> bool:
        scope = self.resolve_scope(name)
        return scope is not None and name in scope.constants

    def as_dict(self) -> dict[str, T]:
        return dict(self.symbols)
