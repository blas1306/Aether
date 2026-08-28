# CORE-PKG-1 — Native CompilerCore distribution

Status: **CORE_NATIVE_COMPILER_CORE_DISTRIBUTION_PENDING_CI**  
Date: 2026-08-28

## Decision

The productive native distribution is named `aether-compiler-core`. Its
initial package version is `1.0.0rc4`, exactly coupled to
`aether-language==1.0.0rc4`:

```text
aether-language==1.0.0rc4
    Requires-Dist: aether-compiler-core==1.0.0rc4
```

This milestone changes packaging and discovery only. The production SSA
transport remains the persistent `aether-ssa-shadow` companion. The installed
PyO3 binding is productive but is not selected as the default transport.
CORE-1.0B therefore remains blocked and is not promoted here. CORE-1.1 is not
implemented.

## Packaging audit: before

| Area | Previous state | Classification |
|---|---|---|
| `aether-language` | Setuptools, pure `py3-none-any` wheel, version from `src/aether/version.py`; no native dependency | Python distribution (A) |
| `_aether_core` | Maturin wheel named `aether-core-qualification==0.1.0`; `QUALIFICATION_ONLY=True` | Qualification only (E) |
| `aether-ssa-shadow` | Cargo binary plus standalone archive tooling; production lookup expected `<sys.prefix>/libexec/aether/ssa-shadow` | Native compiler-core adapter (B), not installed by the language wheel |
| Aether program runtime | Python modules and emitted C/LLVM runtime support used by compiled programs | Program runtime (C), unchanged |
| Cargo `target/{debug,release}` | Checkout-local build outputs used by qualification | Development only (D/E) |

The CLI selected `ProductionRustSSALoweringClient`, which searched only its
installation prefix. Qualification could inject an absolute companion path,
but normal `pip install aether-language` did not install either native adapter.
Editable installs commonly used `pip install -e . --no-deps`; `uv.lock` knew
only the root Python project. Release builds produced one pure Python wheel and
one sdist. That is the exact condition that blocked CORE-1.0B.

VS Code executes the configured/project-venv/PATH `aether` and `aether-lsp`
entry points. IntelliJ follows the same model, independently resolving those
two commands. Neither integration locates `_aether_core` nor the companion
itself, so no IDE architecture change is required.

## Packaging architecture: after

`aether-compiler-core` is a mixed Maturin wheel containing:

- the private extension `aether_compiler_core._aether_core` plus the supported
  compatibility import `import _aether_core`;
- the stable Python wrapper `aether_compiler_core`;
- `aether_compiler_core/_native/aether-ssa-shadow[.exe]`;
- `aether_compiler_core/_native/native-core-manifest.json`;
- normal wheel metadata and RECORD hashes.

`aether_compiler_core.binding()` validates and returns the private binding.
`aether_compiler_core.companion_path()` is the stable discovery API. It uses
package resources and wheel RECORD integrity, never PATH, the current working
directory, a repository-relative path, or Cargo's target directory. There is
no automatic fallback.

`aether-language` now calls `companion_path()` only when the existing
production companion client starts. Merely having `_aether_core` installed
does not select it.

## Single CompilerCore implementation

Both adapters depend on the same workspace crate and type:

```text
aether-python::_aether_core ----\
                                > aether-verifier::CompilerCore
aether-ssa-shadow --------------/
```

The companion calls `CompilerCore.lower_verified_ssa`; the binding constructs
sessions through `CompilerCore.accept_initial_ir`. Shared API/protocol/schema
constants live beside `CompilerCore`. Source-level contract tests reject an
adapter that stops importing that implementation. No SSA, refinement,
lifecycle, Initial IR, optimizer, backend, schema, authority-mode, or Python
`GeneralSSABuilder` semantics changed.

## Version contract

The wheel and wrapper record and validate:

| Field | CORE-PKG-1 value |
|---|---|
| distribution/package version | `aether-compiler-core` / `1.0.0rc4` |
| required language version | `aether-language==1.0.0rc4` |
| native Cargo product version | `0.1.0` |
| CompilerCore API | `1` |
| protocol | `1` |
| accepted Initial IR schemas | `[1]` |
| emitted SSA schemas | `[2]` |
| build identity | explicit release revision, or detected Git revision |

The extension and generated manifest carry the same build identity. Wrapper
validation fails closed for absent/wrong distribution metadata, a missing or
wrong extension, version/API/schema mismatch, divergent build identity,
missing/corrupt manifest, absent/non-executable companion, or RECORD checksum
mismatch. The persistent client's unchanged startup identity check remains a
second protocol-v1 guard.

## Build and consumer workflows

Building native wheels requires Rust, Cargo, Maturin, and the supported Python
interpreter. `build.rs` builds the companion from the same locked workspace in
an isolated target directory and stages it in Maturin's `OUT_DIR`; an official
CI build may instead provide an explicitly built companion with the same build
identity. Building can require Rust. Installing a precompiled wheel must not.

Repository development uses a local non-editable path source for the binary
core and an editable root language package. Keeping the native member
non-editable ensures its extension and companion package resources are copied
into the environment together:

```bash
uv sync
# or explicitly
python -m pip install compiler-rs/distributions/aether-compiler-core
python -m pip install -e . --no-deps
```

The first command/build of the native path dependency requires the Rust
toolchain. Python edits in `aether-language` remain immediately visible; native
or wrapper edits require rerunning `uv sync`/the core install so the binary
resource set stays atomic. No manually copied checkout artifact is part of the
contract.

A clean release consumer installs the platform/Python core wheel together with
the pure Python language wheel. The qualification removes Cargo and rustc from
the consumer PATH, clears `PYTHONPATH`, runs outside the checkout, checks the
CLI/package provenance, imports and reuses the binding, and exercises companion
startup, three persistent requests, structured failure/recovery, and shutdown.

## Platform and Python strategy

Official CI builds native wheels for Linux x86_64, Windows x86_64, macOS
x86_64, and macOS arm64. Linux uses Maturin/auditwheel policy from the build
runner; CORE-PKG-1 does not claim a broader manylinux baseline than the wheel
tag and audit job actually establish. Every report records filename, tags,
size, and SHA-256.

CORE-PKG-1 retains interpreter-specific CPython wheels for 3.11, 3.12, 3.13,
and 3.14. PyO3 supports abi3, but enabling it changes the extension ABI and
debugging/release surface after CORE-1.0A qualified per-interpreter artifacts.
That reduction is deferred; no `abi3` feature is enabled here.

## IDE audit

VS Code and IntelliJ continue launching the `aether`/`aether-lsp` entry points
from a configured executable, project `.venv`, or PATH. Once those entry points
come from the clean wheel installation, Python imports the exact native
dependency from the same environment and its helper returns the packaged
companion. LSP startup does not directly select a transport. No plugin or
launch-schema change is necessary.

## Failure campaign

The dedicated tests and clean-install qualification cover:

- missing native distribution metadata;
- wrong native distribution version;
- missing or shadowed `_aether_core`;
- missing companion;
- incompatible/corrupt/missing native manifest;
- RECORD checksum mismatch contract;
- non-executable POSIX companion;
- incompatible wheel tags through pip/platform matrix installation;
- a source checkout or shadow module appearing before the installed binding.

All paths diagnose and stop. None falls back to a Cargo output or another
transport.

## Release ordering and failure modes

A future release must:

1. build and qualify every required `aether-compiler-core==1.0.0rc4` wheel;
2. publish that complete native wheel set;
3. verify index visibility for every supported platform/Python tag;
4. publish `aether-language==1.0.0rc4` with its exact dependency.

Publishing the language wheel first creates an uninstallable interval.
Publishing an incomplete core matrix makes only some consumers resolvable.
Replacing a native wheel in place invalidates recorded hashes/build identity.
The release must stop in all three cases; it must never relax the exact pin or
silently fall back. Nothing is published by CORE-PKG-1.

## Qualification boundary

The dedicated workflow is `.github/workflows/core-native-packaging.yml`. Its
fail-closed aggregate requires machine-readable contract, failure, source
development, four-platform, and four-Python evidence. Local success can only
produce `CORE_NATIVE_COMPILER_CORE_DISTRIBUTION_PENDING_CI`; only complete CI
closure may produce `CORE_NATIVE_COMPILER_CORE_DISTRIBUTION_QUALIFIED`.

The historical CORE-1.0A JSON/documents are unchanged and remain interpretable
as qualification of `aether-core-qualification==0.1.0`. That distribution is
retained as a separate qualification-only build, rather than silently changed
into the productive package. CORE-1.0A semantic tests are replayed against the
productive adapter in the new workflow.
