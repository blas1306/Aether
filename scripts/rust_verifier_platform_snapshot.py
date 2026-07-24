#!/usr/bin/env python3
"""Emit the platform-neutral Rust verifier operational corpus snapshot."""

from __future__ import annotations

import argparse
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from benchmarks.ir_verifier import (  # noqa: E402
    CORPUS_MANIFEST,
    _load_manifest,
    _materialize_modules,
)
from aether.ir import (  # noqa: E402
    CollectingShadowReportSink,
    IRVerificationError,
    ShadowVerificationStage,
    ShadowVerifierCoordinator,
    build_canonical_rust_verifier_request,
)
from aether.ir.rust_verifier import (  # noqa: E402
    SubprocessRustVerifierClient,
    select_rust_verifier_executable,
)


NONTRANSPORTABLE_CASES = frozenset(
    {
        "lifecycle-non-storage-destination",
        "integer-constant-out-of-range",
    }
)


def build_snapshot(executable: Path) -> dict[str, object]:
    selection = select_rust_verifier_executable(executable)
    corpus_schema_version, entries = _load_manifest(CORPUS_MANIFEST)
    modules = _materialize_modules(entries)
    client = SubprocessRustVerifierClient(executable=selection.path)
    rows: list[dict[str, object]] = []
    classifications: Counter[str] = Counter()

    for entry, module in modules:
        if entry.id in NONTRANSPORTABLE_CASES:
            continue
        request = build_canonical_rust_verifier_request(module)
        sink = CollectingShadowReportSink()
        coordinator = ShadowVerifierCoordinator(client=client, sink=sink)
        try:
            coordinator.verify(
                module,
                stage=ShadowVerificationStage.EXTERNAL,
            )
        except IRVerificationError:
            pass
        report = sink.reports[0]
        classification = report.comparison.classification.value
        classifications[classification] += 1
        rows.append(
            {
                "id": entry.id,
                "request_sha256": sha256(request.payload).hexdigest(),
                "migration_classification": classification,
                "differential_report": report.semantic_snapshot(),
            }
        )

    return {
        "schema_version": 1,
        "corpus_schema_version": corpus_schema_version,
        "protocol_version": selection.identity.protocol_versions[0],
        "ir_schema_version": selection.identity.ir_schema_versions[0],
        "feature_capabilities": list(selection.identity.capabilities),
        "cases": rows,
        "statistics": {
            "transportable_cases": len(rows),
            "classifications": {
                key: classifications[key] for key in sorted(classifications)
            },
            "unexpected_divergences": sum(
                count
                for key, count in classifications.items()
                if key.startswith("unexpected_")
            ),
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--executable", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    snapshot = build_snapshot(args.executable)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(snapshot, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(args.output)
    statistics = snapshot["statistics"]
    assert isinstance(statistics, dict)
    return 0 if statistics["unexpected_divergences"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
