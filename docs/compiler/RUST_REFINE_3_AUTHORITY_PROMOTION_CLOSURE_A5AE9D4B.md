# RUST-REFINE-3 — authority promotion closure a5ae9d4b

Decision: `RUST_REFINEMENT_AUTHORITY_PROMOTED`.

This closure seals revision
`a5ae9d4b3a50843faf68bdeb4d8afc227b900bc9` and official GitHub Actions run
[`33361044254`](https://github.com/blas1306/Aether/actions/runs/33361044254).
The run was a new `workflow_dispatch`, attempt 1, of
`rust-refine-3-authority-promotion` (`346335540`), completed `success` on
2026-08-31. Promotion follows artifact verification and independent
recomposition; it is not inferred from the workflow conclusion.

## Prerequisite and immutable history

RUST-REFINE-2 run `33321791729`, revision
`0bff8c0a78005d97ee5c7c2e0eb09a6a6b3b1fef`, was revalidated from all 19
official artifacts. GitHub IDs and digests matched freshly downloaded ZIP
SHA-256 values. The official checker replay and independently rebuilt decision
both returned `RUST_REFINEMENT_SHADOW_QUALIFIED`.

Historical runs remain immutable:

- `33319278847`: `FAILED/BLOCKED`;
- `33321279630`: `FAILED/BLOCKED`;
- RUST-REFINE-3 run `33360257587`: `FAILED/BLOCKED`.

The failed RUST-REFINE-3 run was not rerun or reinterpreted. Its corrections
were committed separately as `a5ae9d4b3a50843faf68bdeb4d8afc227b900bc9`
and qualified in a new run.

## Authority boundary and implementation

The baseline productive acceptance required Rust Owned SSA verification, Rust
refinement verification, Python `SSAVerifier`, and Python
`SSARefinementVerifier`. The call-site and contract audits classified the
productive, qualification, test, diagnostic, tooling, compatibility, and dead
paths before the switch.

The qualified productive path is now:

```text
lifecycle normalization
→ Rust Owned SSA lowering and verify_owned_ssa
→ Rust verify_owned_ssa_refinement
→ schema-v2 export/import
→ Python SSAVerifier
→ accept
```

Python `SSARefinementVerifier` is not executed as a productive acceptance
condition. It remains available through explicit test/qualification APIs with
role `oracle_only`. Python `SSAVerifier` remains mandatory and was not retired.
No companion, schema, protocol, fallback, construction, optimizer, backend, or
runtime semantics were removed or promoted by this milestone.

The contract audit covered function identity, signatures, `may_throw`,
structs/types, reachable CFG, preserved instructions, load/store promotion,
reaching values, provenance, definitions/uses, phi justification, edge values,
source locations, `bounds_checked`, transferred storage, exceptions, and
lifecycle behavior. The only differences were representation-only,
diagnostic-only, or the known input-domain case `missing_reachable_block`, for
which both sides reject and Rust rejects earlier. There were no unexplained
semantic-contract differences.

## Official evidence

All 21 jobs concluded `success`: the 12 individually named functional gates,
four platform jobs, four CPython jobs, and `aggregate-fail-closed`. Their exact
job IDs are sealed in the
[machine-readable closure](rust_refine_3_authority_promotion_closure_a5ae9d4b.json).

All 21 official artifacts were downloaded into a fresh directory through their
GitHub artifact IDs. No pre-existing local artifact was used. For every
artifact, the downloaded ZIP SHA-256 matched its GitHub digest. The 20 producer
artifacts also have their extracted evidence SHA-256 sealed in the JSON
closure. The aggregate identity is:

- artifact ID `9746832507`;
- ZIP SHA-256 and GitHub digest
  `ce7a15047e878ecad9a5e3638225d4f0f826ee79e3644c8b4abb645d90780b6f`;
- manifest SHA-256
  `979f1b5d4b3a64b1a9963bbb9701fa206362827075512b6103104f1cac101d02`;
- decision SHA-256
  `3295b419e772c03462210ff4e13479023e15643af370dc73330b030597eae3be`.

The aggregate-embedded producer ZIPs were byte-identical to the 20 producer
artifacts downloaded independently. All sealed manifest fields—artifact ID,
source job, kind, run, revision, status, GitHub digest, ZIP SHA-256, and
evidence SHA-256—matched the independently rebuilt manifest.

The three fail-closed decisions were byte-identical and had zero errors:

| Decision source | Result |
|---|---|
| Official aggregate | `RUST_REFINEMENT_AUTHORITY_PROMOTED` |
| Checker replay against official aggregate | `RUST_REFINEMENT_AUTHORITY_PROMOTED` |
| Independently rebuilt aggregate | `RUST_REFINEMENT_AUTHORITY_PROMOTED` |

## Qualification results

- Directed differential: 223 cases, 71 property-generated, zero acceptance
  divergences, zero Rust-accept/Python-reject, and zero
  Rust-reject/Python-accept.
- Mutation/adversarial: 403 deterministic composed cases, all rejected by both
  implementations; zero accepted mutations. Nine stable non-composable pairs
  remained generation errors and were not counted as executed mutations.
- Positive/productive coverage: 15 language/CFG categories, zero valid
  acceptance regressions, plus a successful end-to-end LLVM backend case.
- Rust rejection: structured `ssa_refinement_verification` error, compilation
  blocked, zero Python refinement calls, no rescue, no automatic fallback, and
  successful next-request recovery.
- Transport parity: requested and observed `in_process` and `companion`, equal
  valid SSA digest, equal rejection class, and no fallback.
- Clean packaged consumer: checkout not importable, Cargo/rustc not required,
  exact native dependency, binding and companion present, both transports,
  productive Rust authority, and explicit Python oracle qualification.
- Source/development: editable language package and native product passed both
  transports and the explicit oracle. The complete suite reported 5,204
  passed, 12 skipped, one warning.
- Deep stress: 5,000 Initial IR blocks and 5,000 SSA blocks accepted by Rust and
  Python qualification.
- Cost: four samples measured Rust refinement, schema boundary, remaining
  Python verification, and before/after totals. No correctness threshold or
  universal speedup claim was made.

The platform matrix passed on Linux x86_64, Windows x86_64, macOS x86_64, and
macOS arm64. Each clean consumer observed Rust productive authority, Python
refinement absent from productive acceptance, explicit `oracle_only`
qualification, both transports, adversarial rejection, and no fallback.

The CPython matrix passed with exact versions 3.11.16, 3.12.14, 3.13.15, and
3.14.7. Platform gate patch versions and native target triples are sealed in
the JSON closure.

## Authority provenance and decision boundary

Authority is derived from executed per-case traces, not a constant: successful
CompilerCore requests observed Rust refinement before publication; imported
SSA reported `rust_schema_v2_import`; productive traces recorded
`python_refinement_role=not_executed`; explicit qualification traces recorded
`python_refinement_role=oracle_only`; and injected Rust rejection never invoked
Python refinement or fallback.

Every mandatory gate is therefore satisfied for the qualified revision and
matrices. Rust is promoted as productive authority for Initial IR → Owned SSA
refinement. This is not a universal correctness proof and does not authorize a
later milestone. Python `SSARefinementVerifier` remains as oracle/reference;
Python `SSAVerifier` remains in productive acceptance.

Final decision:

```text
RUST_REFINEMENT_AUTHORITY_PROMOTED
```
