#!/usr/bin/env python3
"""Probe an installed CORE-PKG-1 wheel pair without repository imports."""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--repository", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    repository = args.repository.resolve()
    if any(Path(item or ".").resolve() == repository for item in sys.path):
        raise RuntimeError("source checkout is importable in the clean consumer")

    import _aether_core
    import aether
    from aether.ssa.shadow import (
        PersistentRustSSALoweringClient,
        ProductionRustSSALoweringClient,
        default_rust_ssa_lowering_client,
    )
    import aether_compiler_core

    for imported in (Path(aether.__file__).resolve(), Path(aether_compiler_core.__file__).resolve()):
        if imported.is_relative_to(repository):
            raise RuntimeError(f"clean consumer imported source checkout: {imported}")

    payload = args.fixture.read_bytes()
    core = aether_compiler_core.CompilerCore()
    first_session = core.accept_initial_ir_schema_v1(payload)
    first_session.lower_ssa()
    first = json.loads(bytes(first_session.export_ssa_schema_v2()))
    second_session = core.accept_initial_ir_schema_v1(payload)
    second_session.lower_ssa()
    second = json.loads(bytes(second_session.export_ssa_schema_v2()))
    try:
        core.accept_initial_ir_schema_v1(b"{}")
    except aether_compiler_core.AetherBindingError as error:
        structured_failure = {
            name: getattr(error, name)
            for name in ("kind", "category", "phase", "code")
        }
    else:
        raise RuntimeError("malformed binding input did not fail closed")

    companion = aether_compiler_core.companion_path()
    companion_metadata_process = subprocess.run(
        [str(companion), "--distribution-metadata"],
        check=True,
        capture_output=True,
        text=True,
    )
    companion_metadata = json.loads(companion_metadata_process.stdout)
    with PersistentRustSSALoweringClient(companion) as client:
        companion_first = client.lower(payload)
        companion_failure = client.lower(b"{}")
        companion_recovery = client.lower(payload)
        companion_state = {
            "process_start_count": client.process_start_count,
            "request_count": client.request_count,
            "process_id": client.process_id,
        }
    companion_shutdown = client._process is None

    default = default_rust_ssa_lowering_client()
    default_response = default.lower(payload)
    default.close()
    default_proof = {
        "class": type(default).__name__,
        "is_companion_client": isinstance(default, ProductionRustSSALoweringClient),
        "response_matches": default_response.get("ssa") == first,
    }

    metadata = aether_compiler_core.version_metadata()
    result = {
        "status": "PASS",
        "language_distribution_version": importlib.metadata.version("aether-language"),
        "native_distribution_version": importlib.metadata.version("aether-compiler-core"),
        "binding": {
            "extension": str(Path(_aether_core.__file__).resolve()),
            "ordinary_lowering": first == second,
            "structured_failure": structured_failure,
            "repeated_reuse": first == second,
            "qualification_only": _aether_core.QUALIFICATION_ONLY,
        },
        "companion": {
            "path": str(companion),
            "distribution_metadata": companion_metadata,
            "ordinary_lowering": companion_first.get("ssa") == first,
            "protocol_v1_failure_shape": sorted(companion_failure),
            "failure_recovery": companion_recovery.get("ssa") == first,
            "persistent_reuse": companion_state,
            "shutdown": companion_shutdown,
        },
        "native_metadata": metadata,
        "production_transport": default_proof,
        "consumer": {
            "cargo_available": shutil.which("cargo") is not None,
            "rustc_available": shutil.which("rustc") is not None,
            "repository_importable": False,
            "cwd": str(Path.cwd()),
        },
    }
    valid = (
        result["language_distribution_version"] == "1.0.0rc4"
        and result["native_distribution_version"] == "1.0.0rc4"
        and result["binding"]["ordinary_lowering"] is True
        and result["binding"]["qualification_only"] is False
        and result["companion"]["ordinary_lowering"] is True
        and result["companion"]["distribution_metadata"] == {
            "build_identity": result["native_metadata"]["build_identity"],
            "compiler_core_api_version": 1,
            "input_schema_versions": [1],
            "output_schema_versions": [2],
            "product": "aether-ssa-shadow",
            "product_version": "0.1.0",
            "protocol_version": 1,
        }
        and result["companion"]["protocol_v1_failure_shape"] == ["error", "ok"]
        and result["companion"]["failure_recovery"] is True
        and result["companion"]["persistent_reuse"]["process_start_count"] == 1
        and result["companion"]["persistent_reuse"]["request_count"] == 3
        and result["companion"]["shutdown"] is True
        and result["production_transport"]["is_companion_client"] is True
        and result["production_transport"]["response_matches"] is True
        and result["consumer"]["cargo_available"] is False
        and result["consumer"]["rustc_available"] is False
    )
    if not valid:
        result["status"] = "FAIL"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(result["status"])
    if not valid:
        print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
