# Independent SSA refinement verifier — RUST-4.1

Decision: `RUST_SSA_INDEPENDENT_REFINEMENT_VERIFIER_QUALIFIED`.

## Baseline and architecture

Baseline revision: `7500d66a0d830542d2436b22356e0c34698f076f` (current HEAD when RUST-4.1 began). The verifier is an opt-in qualification/test API; production lowering does not call it.

```text
lifecycle-normalized Initial IR
        |
        v
Rust-produced, schema-v2-imported SSA
        |
        v
independent cross-IR refinement verifier
```

## Formal refinement relation

Reachability is computed directly from Initial IR terminators. The SSA must contain exactly those blocks, in source order, with the same entry and edge-bearing terminators. Each reachable non-slot instruction corresponds exactly once to the same SSA opcode in the same block and relative order. Scalar metadata is equal; value operands are compared by provenance rather than spelling.

`IRLoad` and `IRStore` are `PROMOTED_AWAY`; all other reachable instructions are `PRESERVED`, phis are `SYNTHESIZED_PHI`, and invoke/throw edge arguments plus checked-index flags are `STRUCTURALLY_TRANSFORMED`.

A forward fixed-point reaching-value analysis derives each slot's semantic value at every block edge. It is not dominance-frontier phi placement and does not build expected SSA. A received phi is legal only when its exact predecessor/value relation can be matched one-to-one to a promoted slot. Preserved operands, calls, branches, effects and returns must carry the same Initial-IR provenance.

| Transformation | Required input/output relation |
|---|---|
| unreachable-block elimination | SSA blocks equal the independently reachable Initial IR blocks; reachable blocks cannot disappear and unreachable blocks cannot remain |
| promoted load/store elimination | every IRLoad/IRStore disappears and every load-backed use equals the independently computed reaching slot value |
| non-promoted instruction preservation | every reachable non-IRLoad/IRStore instruction occurs exactly once with the corresponding SSA opcode and equal semantic fields |
| phi creation | each phi has exact CFG predecessors and admits a distinct promoted slot whose predecessor reaching values equal its incoming provenance |
| SSA renaming | spelling is irrelevant for preserved results; every operand resolves to the same Initial IR origin set |
| reachable CFG preservation | entry, reachable block sequence and all successor targets are preserved |
| terminator preservation | branch, jump, invoke, throw/rethrow/propagate and return opcode/targets/operands correspond exactly |
| constant preservation | literal payload and result type are equal |
| call preservation | direct, indirect and interface callee/slot, arguments, result type, builtin and exceptional targets are equal |
| side-effect preservation | all non-slot instructions retain exact block-local relative order, so calls, prints, mutations and lifecycle calls cannot disappear, duplicate or reorder |
| return preservation | each SSAReturn operand has exactly the provenance of its corresponding IRReturn after slot promotion |
| type preservation | function, parameter, result, phi, slot and operand types remain equal |
| parameter preservation | parameter count, order, names and types are exact; their uses retain parameter-index provenance |
| lifecycle-normalized assumption | the verifier consumes the exact normalized producer input and rejects remaining lifecycle pseudo-instructions or transferred_storage |

Effectful coverage follows the real IR inventory: direct/indirect/interface calls and invokes, prints, aggregate/class/collection mutations, exception operations, and normalized lifecycle retain/release calls. `IRStore` is the sole slot store promoted away; collection and object stores are preserved.

## Mutation campaign

| Mutation | Source | Detected by | Shadow-only |
|---|---|---|---|
| missing_phi | RUST-4.0 | REFINEMENT_VERIFIER, PYTHON_SHADOW | no |
| extra_phi | RUST-4.0 | REFINEMENT_VERIFIER, PYTHON_SHADOW | no |
| incorrect_phi_incoming | RUST-4.0 | REFINEMENT_VERIFIER, PYTHON_SHADOW | no |
| incorrect_predecessor | RUST-4.0 | EXISTING_SSA_VERIFIER, REFINEMENT_VERIFIER, PYTHON_SHADOW, OTHER | no |
| duplicate_definition | RUST-4.0 | EXISTING_SSA_VERIFIER, REFINEMENT_VERIFIER, PYTHON_SHADOW | no |
| use_before_definition | RUST-4.0 | EXISTING_SSA_VERIFIER, REFINEMENT_VERIFIER, PYTHON_SHADOW | no |
| definition_not_dominating_use | RUST-4.0 | EXISTING_SSA_VERIFIER, REFINEMENT_VERIFIER, PYTHON_SHADOW | no |
| phi_incoming_not_dominating_edge | RUST-4.0 | EXISTING_SSA_VERIFIER, REFINEMENT_VERIFIER, PYTHON_SHADOW | no |
| incorrect_type | RUST-4.0 | EXISTING_SSA_VERIFIER, REFINEMENT_VERIFIER, PYTHON_SHADOW | no |
| incorrect_value_rename | RUST-4.0 | REFINEMENT_VERIFIER, PYTHON_SHADOW | no |
| incorrect_block_target | RUST-4.0 | EXISTING_SSA_VERIFIER, REFINEMENT_VERIFIER, PYTHON_SHADOW | no |
| unreachable_block_incorrectly_preserved | RUST-4.0 | REFINEMENT_VERIFIER, PYTHON_SHADOW | no |
| missing_instruction | RUST-4.0 | REFINEMENT_VERIFIER, PYTHON_SHADOW | no |
| duplicated_instruction | RUST-4.0 | REFINEMENT_VERIFIER, PYTHON_SHADOW | no |
| incorrect_return_value | RUST-4.0 | REFINEMENT_VERIFIER, PYTHON_SHADOW | no |
| ownership_lifecycle_corruption | RUST-4.0 | OTHER | no |
| wrong_phi_incoming_value | RUST-4.1 | REFINEMENT_VERIFIER, PYTHON_SHADOW | no |
| wrong_phi_predecessor | RUST-4.1 | EXISTING_SSA_VERIFIER, REFINEMENT_VERIFIER, PYTHON_SHADOW, OTHER | no |
| duplicate_phi | RUST-4.1 | REFINEMENT_VERIFIER, PYTHON_SHADOW | no |
| missing_preserved_instruction | RUST-4.1 | REFINEMENT_VERIFIER, PYTHON_SHADOW | no |
| duplicated_preserved_instruction | RUST-4.1 | REFINEMENT_VERIFIER, PYTHON_SHADOW | no |
| reordered_side_effecting_instructions | RUST-4.1 | REFINEMENT_VERIFIER, PYTHON_SHADOW | no |
| wrong_constant | RUST-4.1 | REFINEMENT_VERIFIER, PYTHON_SHADOW | no |
| wrong_call_target | RUST-4.1 | REFINEMENT_VERIFIER, PYTHON_SHADOW | no |
| wrong_call_argument | RUST-4.1 | REFINEMENT_VERIFIER, PYTHON_SHADOW | no |
| wrong_branch_target | RUST-4.1 | EXISTING_SSA_VERIFIER, REFINEMENT_VERIFIER, PYTHON_SHADOW | no |
| wrong_return | RUST-4.1 | REFINEMENT_VERIFIER, PYTHON_SHADOW | no |
| wrong_parameter | RUST-4.1 | REFINEMENT_VERIFIER, PYTHON_SHADOW | no |
| wrong_type | RUST-4.1 | EXISTING_SSA_VERIFIER, REFINEMENT_VERIFIER, PYTHON_SHADOW | no |
| missing_reachable_block | RUST-4.1 | EXISTING_SSA_VERIFIER, REFINEMENT_VERIFIER, PYTHON_SHADOW, OTHER | no |
| retained_unreachable_block | RUST-4.1 | REFINEMENT_VERIFIER, PYTHON_SHADOW | no |
| duplicated_block | RUST-4.1 | EXISTING_SSA_VERIFIER, REFINEMENT_VERIFIER, PYTHON_SHADOW, OTHER | no |
| incorrect_promoted_value | RUST-4.1 | REFINEMENT_VERIFIER, PYTHON_SHADOW | no |
| incorrect_rename_structurally_valid | RUST-4.1 | REFINEMENT_VERIFIER, PYTHON_SHADOW | no |

RUST-4.0 `PYTHON_SHADOW_ONLY`: 8 before, 0 after. Newly discovered semantic shadow-only cases: 0.

## False positives and performance

The positive qualification accepted 116/116 historical cases plus 40 adversarial/seeded/lifecycle cases and every requested deep row. Ordinary verifier-only time was 0.004435s; Python construction was measured separately. No production threshold is enforced.

| Blocks | Verifier seconds | Status |
|---:|---:|---|
| 100 | 0.001886 | PASS |
| 1000 | 0.008787 | PASS |
| 5000 | 0.044230 | PASS |
| 10000 | 0.092361 | PASS |

## Independence audit

Classification: `STRONG`.

The verifier shares public dataclasses and type equality with the producer boundary. It shares no SSA-construction algorithm and consumes no producer intermediate. In particular it does not import CFGBuilder, dominators, frontiers, PhiPlacement, SSARenamer or GeneralSSABuilder. Its reaching-value fixed point and received-phi provenance union are relational analyses, not construction of expected SSA.

Remaining common-mode risks:

- Initial IR and SSA model fields can omit the same semantic fact
- the formal lowering contract itself can be wrong
- both sides trust IRType equality
- lifecycle normalization must supply the exact producer input
- the existing schema importer precedes verification

## Production and gates

Production unchanged: yes. Authority unchanged: yes. Fail-closed unchanged: yes. Schemas/protocol unchanged: yes. Rust and Python SSA algorithms unchanged: yes. Optimizer/backend and rollback modes unchanged: yes.

Python shadow remains mandatory: yes.

- rust_4_1_checker: `PASS`
- rust_4_0_campaign_reused: `PASS`
- expanded_mutation_campaign: `PASS`
- false_positive_qualification: `PASS`
- historical_116_of_116: `PASS`
- adversarial: `PASS`
- randomized_seeded_cfg: `PASS`
- deep_cfg: `PASS`
- production_regressions_and_authority_contracts: `PASS_173_OF_173`
- historical_exact_revision_artifacts: `STALE_AS_EXPECTED_NOT_REWRITTEN`
- rust_4_0_checker: `PASS`
- full_python_suite: `PASS_4956_SKIPPED_4`
- cargo_test_workspace_locked: `PASS`
- cargo_fmt_check: `PASS`
- git_diff_check: `PASS`

Gate notes:

- historical_exact_revision_artifacts: RUST-3.x aggregate checkers bind evidence hashes to older qualification revisions; current HEAD/worktree intentionally makes byte-for-byte --check stale. Their current regression/authority/fail-closed tests passed and no historical artifact was regenerated.
- full_python_suite: LSAN_OPTIONS=detect_leaks=0: 4956 passed, 4 skipped, 6 plotting warnings
- targeted_contracts: 173 passed across SSA, dominance, exceptions, RUST-4.0, authority promotion and production stabilization tests

No commit was created.
