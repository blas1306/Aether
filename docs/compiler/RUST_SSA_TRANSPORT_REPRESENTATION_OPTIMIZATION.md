# Rust SSA transport and representation optimization — RUST-3.9a

## Decision

`RUST_SSA_TRANSPORT_REPRESENTATION_OPTIMIZED`

Baseline revision: `14902424f91b0a8cd622a12be114484d541a0705` (RUST-3.8b). The optimized tree is the uncommitted RUST-3.9a change on that revision. No authority, semantic, validation, verification, lifecycle, lowering, optimizer, backend, discovery, packaging, schema, or protocol contract changed.

## Representation-flow audit

| Transition | Allocation / traversal | JSON / copy / normalization | Ownership and later use |
|---|---|---|---|
| `IRModule` → Python schema-v1 snapshot | New dictionaries and lists; full traversal | Deep representational copy; no JSON or lifecycle normalization | Required immutable reference value for transport and the post-lane integrity check; traversed twice more (encode and equality check) |
| snapshot → request bytes | New byte buffer; full traversal | JSON encode; no semantic normalization | Required by protocol-v1 and owned until the framed write completes |
| request bytes → Rust `IRModuleDTO` | New typed Rust tree; full traversal | JSON decode and string/collection allocation | Required because the companion owns the request beyond the input buffer; traversed by normalization/lowering |
| Rust DTO → normalized Initial IR | New normalized tree; full traversal | Lifecycle normalization and semantic work | Required semantic boundary; traversed by SSA lowering |
| normalized IR → `OwnedSsaModule` | New owned SSA graph; full algorithmic traversal | SSA lowering, not a representational copy | Required Rust authority representation; traversed by verifier and response materializer |
| owned SSA → typed schema-v2 DTO | New typed DTO; full traversal | Nominal/type/value materialization | Required wire representation; traversed by the response encoder |
| typed response → response bytes | New byte buffer; full traversal | JSON encode | Required by protocol-v1. Before RUST-3.9a an equivalent `serde_json::Value` tree was allocated and traversed between these two forms |
| response bytes → Python response mapping | New dictionaries/lists; full traversal | JSON decode | Required by protocol-v1; the `ssa` subtree is traversed by the strict importer and comparison |
| schema-v2 mapping → Python `SSAModule` | New object graph; full traversal | Strict field/type validation and nominal/type reconstruction | Required safety boundary and authoritative return value; traversed by `SSAVerifier` and later compiler stages |
| imported Rust SSA → comparison input | No conversion | The already-received, subsequently validated schema-v2 mapping is reused | Safe only because canonicalization clones it and never mutates the client response |
| Python shadow SSA → schema-v2 DTO | New dictionaries/lists; full traversal | DTO serialization | Required today to retain every schema-v2 semantic field during symmetric comparison |
| Rust comparison DTO → canonical Rust DTO | New dictionaries/lists; one full clone/rewrite traversal plus definition scan | Fused copy and alpha-renaming; no JSON | Compilation-local canonical tree, then traversed by equality/difference reporting |
| Python comparison DTO → canonical Python DTO | No new tree; one full rewrite traversal plus definition scan | In-place alpha-renaming of a newly allocated, unshared DTO | Safe immutable/owned reuse; then traversed by equality/difference reporting |

The JSON request encode, Rust request decode, Rust response encode, and Python response decode remain unavoidable under protocol-v1. The schema-v2 import and both Python/Rust verification boundaries remain unchanged.

## Candidate audit

| Candidate | Classification | Result |
|---|---|---|
| Initial IR transport serialization | `PROTOCOL_INTERNAL_OPTIMIZATION` | Removed key sorting only; JSON and the exact schema-v1 snapshot remain |
| JSON request construction | `PROVEN_REDUNDANT_TRAVERSAL` | Avoided the sorting pass; compact JSON framing is unchanged |
| Companion request parsing | `SAFETY_BOUNDARY_DO_NOT_TOUCH` | Typed serde decoding remains |
| Response schema-v2 materialization | `PROVEN_REDUNDANT_REPRESENTATION` | Removed the intermediate `serde_json::Value` tree; typed schema-v2 is serialized directly |
| Response transport | `PROTOCOL_INTERNAL_OPTIMIZATION` | Same length-framed JSON protocol; direct typed serialization reduces allocation |
| Python JSON decoding | `PROTOCOL_INTERNAL_OPTIMIZATION` | Audited, unchanged; a mapping is required by the strict importer |
| Response DTO/object construction | `SAFETY_BOUNDARY_DO_NOT_TOUCH` | Strict schema-v2 import remains complete |
| Schema-v2 importer input | `SAFE_IMMUTABLE_REUSE` | Its validated source mapping is reused only as canonicalization input; import is not bypassed |
| Rust DTO used by comparison | `PROVEN_REDUNDANT_REPRESENTATION` | JSON encode/decode deep-copy sequence replaced by fused clone plus rename |
| Python shadow DTO used by comparison | `SAFE_IMMUTABLE_REUSE` | Newly allocated DTO is canonicalized in place instead of JSON-copying it |

Rejected changes include bypassing or trusting the schema-v2 importer, removing either verifier, comparing the imported Rust object against a differently encoded Python form, sharing mutable canonical trees, replacing JSON, changing framing, caching across compilations, changing lifecycle/lowering/dominator algorithms, and eliminating the Initial IR integrity traversal. They are safety/semantic boundaries or lack sufficient isolation evidence.

## Implemented optimizations

1. Canonical copying and alpha-renaming are fused for the received Rust DTO. This removes JSON encoding, JSON decoding, and one separate rewrite traversal while preserving a detached canonical tree.
2. The freshly serialized Python shadow DTO is canonicalized in place. It is compilation-local and has no external owner, so the JSON deep-copy round trip was representationally redundant.
3. The Rust companion serializes a typed `SSAModuleV2DTO` response directly. The previous typed DTO → `serde_json::Value` → bytes chain became typed DTO → bytes.
4. Initial IR request JSON retains compact protocol-v1 encoding but no longer sorts object keys. JSON object ordering has no schema semantics; Python DTO construction remains deterministic.

## Measurement

Both sides used the same machine, workload manifest, release companion profile, rotated ordering, 2 warmups, and 15 measured rounds. Timing is observational, not a correctness gate. Full samples, extrema, category accounting, and phase deltas are in the JSON evidence.

| Metric | Before | After | Change |
|---|---:|---:|---:|
| Python-only suite median | 157.410 ms | 159.213 ms | +1.803 ms (unmodified lane/noise) |
| Diagnostic Rust-only median | 295.836 ms | 281.370 ms | −14.466 ms |
| Rust authority + Python shadow median | 501.601 ms | 500.634 ms | −0.967 ms (−0.193%) |
| Dual/Python ratio | 3.187× | 3.144× | −0.042× |
| Rust/Python ratio | 1.879× | 1.767× | −0.112× |

The small wall-time change is noisy, but every claimed architectural target has a direct phase-level effect:

| Affected phase | Before | After | Median change |
|---|---:|---:|---:|
| Request JSON serialization | 9.293 ms | 6.752 ms | −2.540 ms / −27.34% |
| Rust schema-v2 materialization | 3.145 ms | 0.800 ms | −2.345 ms / −74.57% |
| Response transport + serialization | 15.429 ms | 5.306 ms | −10.124 ms / −65.61% |
| Python canonicalization | 19.322 ms | 7.457 ms | −11.865 ms / −61.41% |
| Rust canonicalization | 20.415 ms | 15.837 ms | −4.578 ms / −22.42% |
| Python result DTO serialization | 30.354 ms | 30.451 ms | +0.097 ms / +0.32%; unchanged by design |
| Schema-v2 import | 60.559 ms | 62.047 ms | +1.488 ms / +2.46%; unchanged code, observed noise |

Transport/import fell from 23.210% to 22.079% (−1.131 percentage points) and comparison fell from 17.570% to 16.067% (−1.503 points). The new largest additive category is safety/verification at 22.462%. The new largest individual phase remains Rust SSA lowering at 85.932 ms, followed by schema-v2 import at 62.047 ms.

## Correctness and isolation evidence

- New RUST-3.9a tests cover legacy-canonical equivalence, response immutability, nested nominal data, mutation of both lane results, consecutive compilations, failure followed by success, 32 concurrent callers, and absence of the Rust `Value` intermediary.
- Existing persistent-session tests cover 500 consecutive requests and 64 concurrent requests through one companion.
- RUST-3.8a redundant-work and RUST-3.8b characterization/checker regressions pass.
- Historical authority corpus: 116/116 PASS.
- Promotion lifecycle fixtures and production stabilization regressions: PASS.
- Deep CFG 993/1000/5000 and `cargo test --workspace --locked`: PASS.
- Full Python suite, clean-install Linux qualification, formatting, and diff hygiene are recorded in the JSON evidence.

No compilation retains a canonical tree or response mapping. Imported authoritative modules are freshly reconstructed for each request. Mutation tests prove that changing the original Initial IR after snapshot creation fails closed and that changing either result cannot affect a later compilation.

## Required analysis and next milestone

1. Redundant transitions: typed schema-v2 → JSON `Value` → response bytes, and DTO → JSON bytes → equivalent DTO solely to copy before canonicalization.
2. Eliminated work: two JSON copy round trips, their full encode/decode traversals, one separate canonical rewrite traversal for Rust, and request key sorting.
3. Unavoidable JSON: both transport encode/decode pairs remain under protocol-v1.
4. Schema-v2 import: implementation unchanged; measured +1.488 ms, treated as noise rather than an optimization claim.
5. Python shadow serialization: unchanged (+0.097 ms); its following canonicalization fell 11.865 ms.
6. New dual/Python ratio: 3.144× in the local same-machine campaign.
7. Largest phase: Rust SSA lowering, 85.932 ms.
8. Largest category: safety/verification, 22.462%.
9. Further low-risk representation work is not the best next target. Direct canonical serialization could remove the remaining 30.451 ms Python DTO phase, but it would couple canonical equality to a second schema encoder and needs a dedicated semantic design/qualification.
10. Recommended next milestone: **(d) Rust SSA/dominators**, conservatively scoped and broadly qualified. It is the largest individual phase and prior deep-CFG evidence already justifies a dedicated algorithmic milestone. Verifier architecture remains a safety-boundary candidate, not a timing-driven removal target.

Linux is qualified locally. The companion implementation is portable and packaging/discovery were untouched, but official Windows and macOS CI is still required for multiplatform release sign-off.
