from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from .result import AetherRunResult
from .session import AetherSession


def run_aether(
    source: str,
    *,
    plot_mode: str | None = None,
    plot_output_dir: str | Path | None = None,
    output_writer: Callable[[str], None] | None = None,
    input_reader: Callable[[], str] | None = None,
) -> AetherRunResult:
    return AetherSession(
        plot_mode=plot_mode,
        plot_output_dir=plot_output_dir,
        output_writer=output_writer,
        input_reader=input_reader,
    ).run(source)
