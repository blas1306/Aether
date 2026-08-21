# RUST-3.1 Rust Initial IR -> SSA lowering

Decision: `RUST_SSA_LOWERING_BLOCKED`

## Blocking contract gap

Historical result: this section records why RUST-3.1 correctly stopped. It has
not been rewritten as though lowering had proceeded.

The frozen `lowering_policy_v1` does not specify the exact lifecycle
normalization required by RUST-3.1.  Its machine-readable lifecycle rule gives
only:

- the six input instruction kinds;
- a phase-order requirement;
- a reference to `aether.ir.lifecycle.expand_lifecycle` and
  `LifecycleTypeRegistry` as the owner; and
- a high-level description (type-directed expansion, reverse aggregate order).

It does not enumerate the emitted instruction sequences, temporary naming,
default constants, builtin calls, source-location propagation, aggregate
rollback behavior, or ownership operations for each supported type and each of
the six pseudo-instructions.  Those decisions currently exist only in the
Python implementation in `src/aether/ir/lifecycle.py`.

This is insufficient to implement the requested "exact expansion semantics"
without treating Python implementation details as the specification.  The
RUST-3.1 instructions explicitly prohibit doing that and require stopping when
the frozen policy is incomplete.  Consequently, implementing or differentially
qualifying the subsequent CFG, dominance, liveness, phi-placement, renaming,
and verification pipeline would falsely claim policy-v1 compliance.

## Required resolution

Qualify a new immutable policy artifact (or a versioned supplement to v1) that
defines, for every lifecycle operation and supported type category:

1. the exact ordered ordinary-IR expansion;
2. generated-name rules and collision handling;
3. constants and builtin identities;
4. ownership and source-location propagation;
5. aggregate field traversal and partial-failure rollback; and
6. error behavior for unsupported or structurally impossible cases.

The artifact needs independent behavioral fixtures, not implementation anchors
to Python methods.  Once qualified, Rust can implement it and use Python only
as the differential reference lane.

## RUST-3.B1 follow-up

The prerequisite above is now satisfied by
[`lifecycle_normalization_policy_v1.json`](lifecycle_normalization_policy_v1.json)
and its 116/116 corpus plus adversarial qualification evidence. This resolves
the lifecycle-contract blocker only. The historical `RUST_SSA_LOWERING_BLOCKED`
decision remains valid, RUST-3.1 is not marked implemented, and no Rust
normalizer or lowering code was added.

## Milestone status

- Lowering API: not added; doing so would expose an incomplete implementation.
- Lifecycle coverage: blocked by the normative gap above.
- CFG through SSA verification: not started after the mandated stop.
- 77-instruction coverage: not claimed.
- Corpus denominator: expected 116; not run because the first mandatory phase
  cannot be implemented from the frozen contract.
- Semantic parity and determinism: not claimed.
- Performance: not measured for an incomplete pipeline.
- Production Python lowering authority: unchanged.
- RP3 Initial IR verification authority: unchanged.
- SSA schema-v2 and all compiler/backend semantics: unchanged.
