# Rust Initial IR to SSA full differential qualification — RUST-3.1e

Decision: `RUST_SSA_LOWERING_BLOCKED`

The complete 116-program historical verified-SSA corpus was retained. Both
lanes consumed the same Initial IR schema-v1 DTO. The Rust lane normalized,
lowered to `OwnedSsaModule`, called `aether_verifier::verify_owned_ssa`, emitted
schema-v2, and imported that document in Python. The Python lane used
`GeneralSSABuilder` and its authoritative SSA verification.

The qualification is blocked by genuine semantic differences, not temporary
names. Lifecycle normalization matches in 96/116 programs and differs in 20.
Representative missing Rust operations include the retain after an owning
`class_get` and releases when owning results or operands reach their final use.
SSA canonical comparison passes 90/116 and differs in 26. All 116 Rust results
pass `verify_owned_ssa` and import through the Python schema-v2 codec; exact
Python reserialization matches 106/116 (the remaining optional-field spelling
differences are retained as evidence). Concrete Rust output is deterministic in
116/116 repeated runs.

During this attempt two implementation defects were fixed without changing the
normative policies: exceptional target-event placeholders are no longer
resolved as ordinary SSA operands, and trivial return-transfer storage is
folded after Rust lifecycle expansion. The latter reduced lifecycle mismatches
from 89 to 20. These fixes are insufficient for qualification, so no production
authority is switched.

Component and negative Rust tests pass, including all six pseudos, phi and
bounds shapes, malformed phi/targets, mixed lifecycle domains, and exceptional
edge arguments. The adversarial qualification remains blocked because required
ownership/exception shapes occur among the real differential failures.

Machine-readable evidence, exact per-file first mismatches, and observable lane
timings are in `rust_ssa_lowering_full_qualification.json`. Internal Rust phase
timings for CFG, dominance/frontiers, liveness/definite initialization, phi
placement and renaming are not claimed while the correctness gate is blocked.

Python remains production SSA lowering authority. RP3 is unchanged. All prior
RUST-3.1 blocked artifacts are preserved unchanged. No commit was created.
