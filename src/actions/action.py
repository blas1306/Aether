from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


@dataclass
class AppAction:
    id: str
    label: str
    callback: Callable[[], None]
    shortcut: str | None = None
    enabled: Callable[[], bool] | None = None
    description: str = ""
