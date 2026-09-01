# Initial IR pre-lifecycle shadow verification

RUST-IR-1 integrates Rust Initial IR admission into ordinary product lowering.
Compilation now requires both verifiers to accept:

```text
Python IRLowerer
  -> Python IRVerifier
  -> Rust aether_verifier::verify_module (same pre-lifecycle snapshot)
  -> Python LifecycleExpander
  -> existing post-lifecycle schema-v1 transport
  -> CompilerCore / Rust lifecycle normalization / owned SSA verification
```

This is a synchronous double fail-closed gate. Python rejection, Rust
rejection, Rust infrastructure failure, request-construction failure, or an
acceptance disagreement blocks compilation. There is no rescue, override, or
automatic fallback. Python `IRVerifier` remains mandatory and Python
`LifecycleExpander` remains product lifecycle authority.

## Exact boundary

`IRBackend.lower_verified()` receives the exact `IRModule` object emitted by
`IRLowerer`. The coordinator first verifies that object with Python, then
serializes that same unchanged object once with `ir_module_to_dto()` and sends
the canonical protocol-v1 request to Rust. The snapshot retains lifecycle
pseudo-operations, `IRStorage`, `transferred_storage`, borrow flags/scopes,
types, CFG and exceptional edges, metadata, source locations, functions and
struct definitions.

The serializer is only a verification snapshot. It does not replace the
Python object and Rust does not return a rewritten module. Lifecycle expansion
and all downstream stages continue to consume the existing Python-owned
module.

The schema-v1 structures are currently reusable on both sides of lifecycle
expansion and have no phase discriminator. That does not make the semantic
domains equal. `verify_module` is a pre-lifecycle verifier. Post-lifecycle and
post-optimization checks remain Python-only; the Rust gate is never inferred
from an arbitrary schema-v1 `IRModule` passed later to SSA.

## Native execution and transports

The productive `aether-compiler-core` wheel contains both
`aether-ir-verifier` and the existing `aether-ssa-shadow` companion. The stable
wrapper validates each executable against wheel `RECORD`. Initial IR admission
uses the existing persistent framed verifier client and unchanged verifier
protocol v1. No PyO3 method or CompilerCore protocol operation was added.

This verifier process is an admission operation independent of the later SSA
transport selector. Consequently both `in_process` and `companion` SSA paths
cross the same gate before `LifecycleExpander`; neither transport changes its
selection, payload, fallback policy, or lifecycle normalization behavior.

Tests may provide the internal exact-path qualification variable
`AETHER_INTERNAL_RUST_INITIAL_IR_QUALIFICATION_EXECUTABLE`. It has no discovery
fallback: absent that test-only override, production resolves only the
RECORD-validated executable from `aether-compiler-core`.

## Provenance and diagnostics

Every dual observation can emit an immutable `ShadowVerificationReport` with
the request SHA-256, client kind, protocol/schema versions, stage, Python and
Rust outcomes, comparison classification, serialization time, Rust invocation
time, and total gate time. Tests instrument the real stage calls and require
the observed order `Python verifier -> Rust verifier -> LifecycleExpander`.

Rust semantic errors preserve category, phase, invariant code, function,
block, and instruction context from protocol v1. When the reported instruction
has an `IRSourceLocation`, the product boundary recovers that location from the
unchanged Python snapshot without changing the protocol. Diagnostic prose is
not used as semantic identity.

## Differential boundary

The migration corpus contains 142 indexed cases: 140 schema-v1 transportable
cases and two explicit representation-domain exclusions. The transportable
set consists of 65 shared acceptances and 75 shared semantic rejections. The
only documented diagnostic differences are `undefined-slot`,
`return-storage-after-move`, and `inconsistent-branch-initialization`; they do
not change acceptance. The excluded lifecycle-destination shape and Python
integer outside schema-v1 i32 are classified as representation-domain
differences, not verifier divergences.

The borrow-to-owned regression demonstrates the phase contract directly: its
original pre-lifecycle IR is accepted by both verifiers, while applying the
Rust Initial IR verifier to the Python-expanded form produces `IRV-041`. That
post-lifecycle rejection is a contract-boundary regression test, not an
expected product failure.

The next milestone is `RUST-IR-2 PRE-LIFECYCLE INITIAL IR SHADOW
QUALIFICATION`. RUST-IR-1 does not implement that qualification or promote
exclusive Rust authority.
