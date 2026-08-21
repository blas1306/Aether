"""Installed-environment probe for the Rust SSA shadow companion."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from aether.pipeline import IRBackend, prepare_typed_program
from aether.ssa.shadow import PersistentRustSSALoweringClient, lower_with_rust_shadow
from aether.typechecker import TypeChecker


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--companion-package", type=Path, required=True)
    parser.add_argument("source", nargs="+", type=Path)
    args = parser.parse_args()
    from aether.ssa.shadow import discover_packaged_rust_ssa_shadow
    executable = discover_packaged_rust_ssa_shadow(args.companion_package)
    compared = 0
    with PersistentRustSSALoweringClient(executable) as client:
        for path in args.source:
            source = path.read_text(encoding="utf-8")
            typed = prepare_typed_program(source, TypeChecker(source_root=path.parent))
            module = IRBackend().lower_verified(typed)
            returned, report = lower_with_rust_shadow(module, client)
            if report.classification != "match" or returned is None:
                raise RuntimeError("representative comparison did not match")
            compared += 1
        result = {"mode": "PYTHON_SSA_AUTHORITY_RUST_SHADOW", "comparisons": compared,
                  "semantic_mismatches": 0, "infrastructure_failures": 0,
                  "process_startups": client.process_start_count, "requests": client.request_count}
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
