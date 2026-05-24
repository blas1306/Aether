from __future__ import annotations

import argparse
import sys
from pathlib import Path

from aether import run_source


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m aether_lsp.run_file")
    parser.add_argument("path", help="Path to an .ae file to run.")
    args = parser.parse_args(argv)

    path = Path(args.path)
    try:
        source = path.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"Could not read {path}: {exc}", file=sys.stderr)
        return 2

    result = run_source(source, output_writer=_write_stdout)
    if not result.success:
        print(result.error or "Aether execution failed.", file=sys.stderr)
        return 1
    return 0


def _write_stdout(text: str) -> None:
    print(text, end="", flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
