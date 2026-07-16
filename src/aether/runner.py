from __future__ import annotations

from collections.abc import Callable
from collections.abc import Sequence
from pathlib import Path

from .result import AetherRunResult
from .session import AetherSession


def run_aether(
    source: str,
    *,
    source_root: str | Path | None = None,
    plot_mode: str | None = None,
    plot_output_dir: str | Path | None = None,
    output_writer: Callable[[str], None] | None = None,
    input_reader: Callable[[], str] | None = None,
    program_arguments: Sequence[str] | None = None,
) -> AetherRunResult:
    return AetherSession(
        source_root=source_root,
        plot_mode=plot_mode,
        plot_output_dir=plot_output_dir,
        output_writer=output_writer,
        input_reader=input_reader,
        program_arguments=tuple(program_arguments or ()),
    ).run(source)
