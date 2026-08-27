# Independent authority shadow redundancy qualification — RUST-4.3

Decision: `PYTHON_SSA_SHADOW_NO_UNIQUE_COVERAGE_DEMONSTRATED`.

Rust remains production authority. The synchronous independent Python SSA shadow, canonical comparison, fail-closed policy, refinement verifier, algorithms, schemas, protocol, rollback modes, optimizer, and backend are unchanged.

## Central result

Applicable semantic mutations: 58/58. `SHADOW_ONLY_AFTER_REFINEMENT`: **0**. `ACCEPTED_BY_ALL`: **0**.

No shadow-only finding is a bounded piece of evidence toward redundancy, not a proof and not authorization to remove the shadow. The recommendation is therefore to retain it.

## Attribution by family

| Family | Attempted | Applicable | Existing + shadow | Refinement + shadow | Shadow only | Accepted by all |
|---|---:|---:|---:|---:|---:|---:|
| cfg_reachability | 9 | 9 | 7 | 2 | 0 | 0 |
| effects | 11 | 11 | 5 | 6 | 0 | 0 |
| generated_randomized | 8 | 8 | 0 | 8 | 0 | 0 |
| instruction_preservation | 5 | 5 | 1 | 4 | 0 | 0 |
| phi | 12 | 12 | 7 | 5 | 0 | 0 |
| return_termination | 6 | 6 | 0 | 6 | 0 | 0 |
| slot_promotion | 2 | 2 | 0 | 2 | 0 | 0 |
| value_provenance | 5 | 5 | 3 | 2 | 0 | 0 |

The raw JSON records every stable mutation ID, intent, fixture, applicability, ordered layer outcomes, first rejection and diagnostic. Correlated cases repair related fields or propagate a wrong definition so the campaign is not limited to malformed single-field edits.

## Randomized, positive, historical, and deep qualification

Deterministic generated programs/mutations: 8 across diamond/merge and loop/backedge/phi shapes using recorded seeds `[43001, 43019, 43037, 43051, 43063, 43067, 43093, 43103]`. Alpha-renaming controls: 13/13. Historical corpus: 116/116 in this qualification run.

Deep CFG is observational only: 100=PASS (0.004s), 1000=PASS (0.041s), 5000=PASS (0.241s), 10000=PASS (0.527s).

## Independence assessment

`IMPLEMENTATION_INDEPENDENT` / `PASS`. The refinement verifier consumes only public Initial IR and candidate SSA, independently derives CFG/reachability and reaching values, and has no builder, dominator/frontier, phi-placement, renamer, Rust intermediate, or Python canonical-oracle dependency.

## Recommendation

Retain the mandatory Python shadow; absence of a shadow-only finding is evidence toward redundancy, never proof or removal authorization.

No commit was created.
