# RUST-1.2.2 — Cross-Platform Release Qualification

Final decision: **CROSS_PLATFORM_COMPANION_QUALIFIED**

Authority: **Python**. Migration phase: **RP2**.

| Platform | Rust target | Result | Evidence provenance |
|---|---|---|---|
| linux-x86_64 | `x86_64-unknown-linux-gnu` | PASS | CI execution |
| windows-x86_64 | `x86_64-pc-windows-msvc` | PASS | CI execution |
| macos-arm64 | `aarch64-apple-darwin` | PASS | CI execution |
| macos-x86_64 | `x86_64-apple-darwin` | PASS | CI execution |

The canonical release build and packaging commands are recorded in the machine-readable report. All four current-contract reports are imported and OP1, OP6, and OP10 pass.

The workflow runs the full 404-case canary on Linux and a representative installed-artifact subset everywhere. It uploads archives, checksums, manifests, and qualification reports; it does not publish a public release.

The checked aggregate is the canonical RUST-1.2.2 evidence consumed by RUST-1.3.
