# RUST-REFINE-3 — owned SSA refinement authority promotion

Status: `RUST_REFINEMENT_AUTHORITY_PROMOTION_PENDING_CI`.

This document records the implementation-phase audit and local qualification.
It is not a formal closure and does not declare Rust promoted. Promotion requires
a new successful official `workflow_dispatch` run, replay of its official
artifacts, an independent aggregate decision, and the SHA-specific closure files.

## RUST-REFINE-2 prerequisite

GitHub was queried directly after authentication was restored. Official run
`33321791729` is workflow `rust-refine-2-shadow-qualification`, workflow ID
`345964937`, attempt 1, event `workflow_dispatch`, revision
`0bff8c0a78005d97ee5c7c2e0eb09a6a6b3b1fef`, and conclusion `success`.
All 19 jobs, including `aggregate-fail-closed`, concluded `success`.

All 19 official artifacts were freshly downloaded. Their downloaded ZIP
SHA-256 values exactly matched the GitHub digests:

| Artifact ID | Name | GitHub digest and downloaded ZIP SHA-256 |
|---:|---|---|
| 9735193744 | rust-refine-2-aggregate | d2eda833c31a55aa2ea513ccd12345bdaa2651e898a6d716c772ae028e0a47f5 |
| 9735189266 | rust-refine-2-source-install | 286796e9154b77bbdaf3b7a0a29a6ce09badd0a4a9bef007e6905b7a52da0e61 |
| 9735149015 | rust-refine-2-platform-macos-x86_64 | 421111088e79433a0c14ee0dbc2603ddde9c049e3c41fc098302c0c1155bb371 |
| 9735144382 | rust-refine-2-platform-windows-x86_64 | 8b1dec098537250aace3e8065a4dd71a75755dddd8e9f8b32bdb306dad8a9141 |
| 9735115498 | rust-refine-2-python-3.14 | 2a9eb7864b43efe4103d1e9c074485400990ad7cdb32b1c88b66d83e25fe0fa6 |
| 9735115401 | rust-refine-2-python-3.13 | 8307ef10cb1d2e225474a6ee656b855e986b1c913083a7fbbcdbc036c6fba807 |
| 9735115229 | rust-refine-2-packaged-consumer | 3b9d50b32c6b26a8ebf6e4baeef2e45cf6168f7f2b42d5343e03b64ededa3b34 |
| 9735114354 | rust-refine-2-transport-parity | dda63a596505d1677be7630b410e40f8dcb764850b4cc84656b210dc88e03a99 |
| 9735114014 | rust-refine-2-python-3.12 | 8b6edcdc680eba967a1f8ce7ccf50c568f33dce9932b2c879e361e8dc5828d56 |
| 9735113442 | rust-refine-2-production-pipeline | 6e7c82c14690c663186c28b577d15d13bb9883e1adbd81250a609b5d211a84c4 |
| 9735111171 | rust-refine-2-platform-macos-arm64 | d83858a33af090605d75fcc76b8c6b2d25ca9e710af3ae5c03faff3be8441829 |
| 9735110199 | rust-refine-2-python-3.11 | a6d8784fc721c1e1a75a540c7a575517cb78145d4a171b761586853ae6100940 |
| 9735105134 | rust-refine-2-platform-linux-x86_64 | 62d224cd43572df7dbf979518ae9e7d6ad7f2c7238878598c2175c7b566d1269 |
| 9735102904 | rust-refine-2-rust-validation | 86f060406d83bf5a8fb87ac9889fecbc07c45adcf1b027d847015bd0527c2ac1 |
| 9735096627 | rust-refine-2-historical | a0f31bd4639f990906ec494e1b5a2004b996a73c57e46a5976c52367a94a03f6 |
| 9735094319 | rust-refine-2-cost | 181fc8db638a9a04feb34cf15ae7bd3c3e0e9366aabb381e217d1fadf26cc901 |
| 9735094254 | rust-refine-2-deep-cfg | 8dfaeb205503c401a61b341016b9fd0fccace2debed4cfc80f2c4d7024b01545 |
| 9735093922 | rust-refine-2-mutations | ec58103616a119235a9263a961e60d226b849086fa632a66ff9f5c6861f610a8 |
| 9735089263 | rust-refine-2-contract | 2ccd5d123e5c02fdd693e010cf1e925031eb2029b165dcdc6f3ce802c397b78e |

The aggregate's sealed evidence ZIPs were byte-compared with the freshly
downloaded individual ZIPs. The existing RUST-REFINE-2 checker was replayed
against the official aggregate and against an independently rebuilt manifest.
Both returned `RUST_REFINEMENT_SHADOW_QUALIFIED` with no errors. Runs
`33319278847` and `33321279630` remain permanently `FAILED/BLOCKED`.

## Authority and call-site audit

The qualified baseline required all four conditions:

```text
Rust verify_owned_ssa
AND Rust verify_owned_ssa_refinement
AND Python SSAVerifier
AND Python SSARefinementVerifier
```

The productive default is `SSAPipeline` →
`lower_with_shadow_independent_rust_authority`. Before this milestone a Python
refinement rejection after Rust acceptance aborted compilation. The explicit
compatibility Rust-authority/Python-shadow path also ran Python refinement
before its canonical shadow comparison.

The complete classification relevant to the switch is:

| Location | Entry point | Classification after switch |
|---|---|---|
| `src/aether/ssa/shadow_independent.py` | `lower_with_shadow_independent_rust_authority` | production acceptance; Python refinement not executed |
| `src/aether/ssa/shadow_independent.py` | `qualify_shadow_independent_rust_ssa` | qualification; Python refinement is `oracle_only` |
| `src/aether/ssa/shadow.py` | `lower_with_rust_authority` | compatibility production acceptance; Python refinement not executed |
| `src/aether/ssa/shadow.py` | `qualify_with_python_refinement_oracle` | explicit test/qualification oracle, absent from dispatcher |
| `src/aether/ssa/refinement_verifier.py` | public verifier API | reference implementation and test/differential oracle |
| RUST-REFINE scripts/tests | direct verifier uses | tooling, tests, and qualification |

No automatic fallback or Python rescue path exists. The Python generic
`SSAVerifier` remains mandatory before and after acceptance and was not retired.

## Contract equivalence audit

Function identity, signatures, `may_throw`, structs/types, reachable CFG,
instruction preservation, load/store promotion, reaching values, provenance,
definitions/uses, phi justification, edge values, source locations,
`bounds_checked`, transferred storage, exception behavior, and lifecycle-relevant
semantics were reviewed explicitly and classified equivalent within the
qualified contract.

The observed differences are all explained:

- owned wire representation versus Python object model: representation-only;
- `missing_reachable_block`: input-domain difference, with both sides rejecting
  and Rust rejecting earlier during owned import;
- structured Rust diagnostic versus Python `ValueError`: diagnostic-only.

There is no unexplained semantic-contract difference.

## Authority switch and provenance

The minimum switch removes only Python `SSARefinementVerifier` from productive
acceptance. Rust still constructs and verifies Owned SSA, exports schema-v2,
and Python still imports it and runs the generic `SSAVerifier`. The Python
refinement implementation remains public and executable through explicit
qualification APIs.

Per-request traces now distinguish:

```text
refinement_authority = rust
rust_refinement_verification_observed = true
python_refinement_role = not_executed | oracle_only
python_refinement_verification_executed = false | true
```

The Rust observation is derived from a successful CompilerCore request; the
core publishes SSA only after both Rust verifiers succeed. Product probes also
derive authority from actual pipeline traces and mark constant-only evidence as
false.

Rust rejection remains final. The failure campaign records the structured Rust
refinement category/code, zero Python refinement calls, no rescue/fallback, and
successful recovery on the next independent request. Both `in_process` and
`companion` return the same SSA digest and rejection classification.

## Local qualification

- contract audit: PASS;
- product authority: 15 categories PASS, including throw/catch, rethrow,
  indirect invoke, interface dispatch, cleanup/unwinding, lifecycle, strings,
  arrays, lists, matrices, classes, interfaces, enums, modules, calls and phi;
- productive LLVM backend: PASS;
- transport parity: PASS with identical valid SSA digest and rejection outcome;
- directed differential: 223 cases, including 71 generated valid CFGs, zero
  acceptance divergences, zero Rust-accept/Python-reject, and zero
  Rust-reject/Python-accept;
- deterministic composed mutations: 403 generated cases, all rejected by both,
  zero accepted mutations; nine non-composable pairs are retained with stable
  seeds and generation errors;
- deep CFG: 5,000 Initial IR blocks and 5,000 SSA blocks accepted by both;
- cost characterization: four samples, with Rust refinement, schema boundary,
  remaining Python verification, and before/after totals; no correctness
  threshold and no universal speedup claim;
- affected tests: 102 passed;
- complete suite: 5,201 passed, 4 skipped, 6 warnings, exit 0. The final run was
  outside ptrace so ASan/LSan could execute and used `MPLBACKEND=Agg`, matching
  the headless CI environment.

## Official qualification design

The dedicated `.github/workflows/rust-refine-authority-promotion.yml` is manual
only and has mandatory distinct gates for the RUST-REFINE-2 prerequisite,
contract, differential, mutation campaign, production authority, no Python
rescue, transports, production pipeline, clean wheel consumer,
source/development, deep stress, cost, four platforms, four Python minors, and
aggregate fail-closed.

The aggregate requires exactly 20 non-aggregate artifacts, exact successful job
conclusions, artifact IDs, GitHub digests, downloaded ZIP SHA-256 values,
evidence hashes, run/revision/kind identity, and semantic provenance. The
dedicated checker emits only:

```text
RUST_REFINEMENT_AUTHORITY_PROMOTED
RUST_REFINEMENT_AUTHORITY_PROMOTION_BLOCKED
```

At this implementation stage no RUST-REFINE-3 run exists and no closure files
exist. The only valid current state is:

```text
RUST_REFINEMENT_AUTHORITY_PROMOTION_PENDING_CI
```
