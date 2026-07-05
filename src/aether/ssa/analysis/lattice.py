from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class LatticeState:
    """Base class for SSA value information lattice states."""

    def merge(self, other: LatticeState) -> LatticeState:
        raise NotImplementedError


@dataclass(frozen=True)
class Unknown(LatticeState):
    """No useful information is known for an SSA value yet."""

    def merge(self, other: LatticeState) -> LatticeState:
        return other

    def __repr__(self) -> str:
        return "Unknown"

    __str__ = __repr__


@dataclass(frozen=True)
class Constant(LatticeState):
    """An SSA value is known to have one concrete constant value."""

    value: Any

    def merge(self, other: LatticeState) -> LatticeState:
        if isinstance(other, Unknown):
            return self
        if isinstance(other, Constant):
            if self.value == other.value:
                return self
            return Overdefined()
        if isinstance(other, Overdefined):
            return other
        return other.merge(self)

    def __repr__(self) -> str:
        return f"Constant({self.value!r})"

    __str__ = __repr__


@dataclass(frozen=True)
class Overdefined(LatticeState):
    """Conflicting information means the SSA value is not a single constant."""

    def merge(self, other: LatticeState) -> LatticeState:
        return self

    def __repr__(self) -> str:
        return "Overdefined"

    __str__ = __repr__
