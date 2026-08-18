# Rust verifier companion packaging (RUST-1.2.1)

Decision: **`COMPANION_PACKAGING_FOUNDATION_READY`**. Python remains the
Initial IR verifier authority and the migration phase remains RP2. This
milestone changes packaging only; it changes neither verifier nor Initial IR
semantics.

## Product and distribution

The product, Rust crate, protocol identity, package name, and Unix executable
are `aether-ir-verifier`; Windows uses `aether-ir-verifier.exe`. It is an
internal, manually debuggable toolchain helper, not normally placed on PATH.
It accepts Initial IR through the existing subprocess protocol. It does not
parse Aether source, typecheck, optimize, replace `aether`, or use PyO3.

The one production distribution model is **B1: a platform-native binary
archive**. This keeps a normal install independent of Cargo, Python packaging,
and a source checkout. The product identity is permanent; today's native
release archive transport may later become an Aether toolchain bundle without
changing the identity or protocol. Python sdists remain developer-oriented and
neither build nor install the companion implicitly.

## Version and compatibility

The independent-semver product version has one authority:
`compiler-rs/Cargo.toml`'s `workspace.package.version`. Release tooling and the
Python adapter read it rather than duplicating it. Aether releases coordinate
an exact companion product version through `verifier-companions.json`, while
actual runtime acceptance requires identity schema 1, protocol 1, IR schema 1,
and capability `verify`. Thus upgrade or downgrade mismatches fail immediately
as an incompatible companion, without treating the program as invalid.
`--version` is human-readable; deterministic JSON is available through
`--metadata` and its backwards-compatible alias `--identity`.

## Platforms and artifacts

Public IDs and Rust targets are: `linux-x86_64` →
`x86_64-unknown-linux-gnu`, `windows-x86_64` →
`x86_64-pc-windows-msvc`, `macos-arm64` → `aarch64-apple-darwin`, and
`macos-x86_64` → `x86_64-apple-darwin`. Public names normalize amd64 to x86_64
and aarch64 to arm64. The macOS x86_64 entry is a defined build target, not a
qualification claim.

Artifacts are named
`aether-ir-verifier-<version>-<platform-id>.tar.gz`, except Windows uses ZIP.
Each contains only the binary, `manifest.json`, and GPL-3.0-only `LICENSE`.
The deterministic manifest declares product/version, protocol/schemas,
capabilities, platform/architecture, binary, release profile, binary SHA-256,
and exact executable identity. Archives use stable ordering and normalized
timestamps/ownership; a SHA-256 sidecar covers the complete archive. We claim
structural determinism, not universal cross-toolchain bit reproducibility.

The canonical command is:

```text
cargo build --manifest-path compiler-rs/Cargo.toml --release --locked --package aether-ir-verifier
python scripts/package_rust_verifier.py --executable compiler-rs/target/release/aether-ir-verifier --platform linux --arch x86_64 --output-dir dist/native
```

The script rejects debug/non-release inputs, wrong names, missing files,
non-executable Unix files, and incompatible metadata. It emits the archive,
checksum, and release-level `verifier-companions.json` beside the artifacts.

## Install, discovery, and release policy

The native toolchain installer must place the helper at
`<aether-home>/libexec/aether/aether-ir-verifier[.exe]` with its adjacent
manifest. The Aether release index formally requires the matching platform
entry. Production discovers that canonical manifest only. An explicit
developer/test override wins; PATH and source-tree fallback are forbidden.
Multiple installs therefore cannot create “first found” behavior. Missing and
incompatible companions are typed infrastructure failures.

Release bundles should ship and require the companion during RP2 so packaged
shadow/canary operation soaks before RP3. Python stays authoritative. The
workflow builds release, packages, checks metadata/checksum, unpacks outside
the checkout, and runs accepted/rejected protocol cases. Windows uses `.exe`
and ZIP; Unix preserves executable mode. macOS signing/notarization is future
release-policy work, not asserted here.

OP5 is PASS at the foundation level. OP1 remains partial because all supported
platform artifacts have not been published. RUST-1.2.2 is only execution and
evidence: build/publish the matrix, clean-install every artifact, run packaged
canaries, and close OP6/OP10. The historical RUST-1.2 artifacts remain
unchanged.
