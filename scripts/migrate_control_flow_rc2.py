#!/usr/bin/env python3
"""Token-aware migration of rc.1 control-flow headers to Aether 1.0 syntax."""

from __future__ import annotations

import argparse
import io
from pathlib import Path
import re
import sys
import tokenize


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = REPOSITORY_ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from aether.errors import AetherSyntaxError  # noqa: E402
from aether.source_formatter import migrate_control_flow_headers  # noqa: E402


PYTHON_STRING_RE = re.compile(r"(?i)^([rub]*)(\"\"\"|'''|\"|')")


def migrate_source(source: str) -> tuple[str, int]:
    return migrate_control_flow_headers(source)


def migrate_python_strings(source: str) -> tuple[str, int]:
    """Migrate only Python string-token payloads, leaving code and comments intact."""
    line_offsets = _line_offsets(source)
    replacements: list[tuple[int, int, str]] = []
    migrated = 0
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type != tokenize.STRING:
            continue
        match = PYTHON_STRING_RE.match(token.string)
        if match is None or "f" in match.group(1).lower() or "b" in match.group(1).lower():
            continue
        quote = match.group(2)
        body_start = match.end()
        body_end = len(token.string) - len(quote)
        body = token.string[body_start:body_end]
        try:
            migrated_body, count = migrate_source(body)
        except AetherSyntaxError:
            continue
        if not count:
            continue
        start = line_offsets[token.start[0] - 1] + token.start[1]
        end = line_offsets[token.end[0] - 1] + token.end[1]
        replacements.append(
            (start, end, token.string[:body_start] + migrated_body + quote)
        )
        migrated += count
    for start, end, replacement in sorted(replacements, reverse=True):
        source = source[:start] + replacement + source[end:]
    return source, migrated


def _line_offsets(source: str) -> list[int]:
    offsets = [0]
    for index, char in enumerate(source):
        if char == "\n":
            offsets.append(index + 1)
    return offsets


def _aether_files(paths: list[str]) -> list[Path]:
    if paths:
        candidates = [Path(path) for path in paths]
    else:
        candidates = [REPOSITORY_ROOT]
    files: set[Path] = set()
    for candidate in candidates:
        if candidate.is_dir():
            files.update(candidate.rglob("*.ae"))
        elif candidate.suffix == ".ae":
            files.add(candidate)
    return sorted(
        path
        for path in files
        if not any(part in {"build", "dist", ".venv", "venv", ".intellijPlatform"} for part in path.parts)
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*")
    parser.add_argument("--check", action="store_true", help="Report files that still require migration.")
    parser.add_argument(
        "--python-strings",
        action="store_true",
        help="Migrate Aether control-flow found inside Python string tokens.",
    )
    args = parser.parse_args(argv)

    changed_files = 0
    changed_headers = 0
    files = (
        sorted(Path(path) for path in args.paths if Path(path).suffix == ".py")
        if args.python_strings and args.paths
        else sorted((REPOSITORY_ROOT / "tests").rglob("*.py"))
        if args.python_strings
        else _aether_files(args.paths)
    )
    for path in files:
        source = path.read_text(encoding="utf-8")
        migrated_source, count = (
            migrate_python_strings(source) if args.python_strings else migrate_source(source)
        )
        if not count:
            continue
        changed_files += 1
        changed_headers += count
        print(f"{path}: {count} header(s)")
        if not args.check:
            path.write_text(migrated_source, encoding="utf-8")

    print(f"{changed_files} file(s), {changed_headers} header(s)")
    return 1 if args.check and changed_files else 0


if __name__ == "__main__":
    raise SystemExit(main())
