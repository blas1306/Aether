from __future__ import annotations

from dataclasses import dataclass

from .types import AetherValue


@dataclass(frozen=True)
class AetherRunResult:
    env: dict[str, AetherValue]
    output: str
    exit_code: int = 0
