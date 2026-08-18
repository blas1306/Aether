# RUST-1.2.2 — Cross-Platform Release Qualification

Final decision: **CROSS_PLATFORM_COMPANION_BLOCKED**

Authority: **Python**. Migration phase: **RP2**.

| Platform | Rust target | Result | Evidence provenance |
|---|---|---|---|
| linux-x86_64 | `x86_64-unknown-linux-gnu` | BLOCKED | none |
| windows-x86_64 | `x86_64-pc-windows-msvc` | BLOCKED | none |
| macos-arm64 | `aarch64-apple-darwin` | BLOCKED | none |
| macos-x86_64 | `x86_64-apple-darwin` | BLOCKED | none |

The canonical release build and packaging commands are recorded in the machine-readable report. OP1, OP6, and OP10 remain blocked until all four current-contract reports are imported.

The workflow runs the full 404-case canary on Linux and a representative installed-artifact subset everywhere. It uploads archives, checksums, manifests, and qualification reports; it does not publish a public release.

To finish: run the `Rust verifier cross-platform qualification` workflow, download its `cross-platform-qualification` artifact, and run `python scripts/check_rust_verifier_cross_platform_qualification.py --evidence-dir <reports> --write --require-qualified`.
