# SSA independent authority qualification — RUST-4.0

Decision: `RUST_SSA_INDEPENDENT_AUTHORITY_REQUIRES_VERIFIER_HARDENING`.

RUST-4.0 does **not** remove or relax the synchronous Python shadow. The campaign found well-formed, verifier-clean wrong transformations that only the Python-derived canonical comparison rejects. Removing the shadow is plausible only after an independent translation/refinement verifier closes the critical gaps.

## Baseline

Rust remains authoritative, Python remains a mandatory synchronous shadow, and every failure remains fail-closed. The baseline is RUST-3.15 at revision `7500d66a0d830542d2436b22356e0c34698f076f`, including the historical 116/116 corpus and the measured unproven low-risk upside ceiling of about 1.5%.

## Trust inventory

| Layer | Guarantee | Independence / common mode | Without Python shadow |
|---|---|---|---|
| rust_ssa_implementation | produces CFG/SSA, dominators, frontiers, phi placement, renaming and deterministic ordering | producer; no independence from itself | incorrect SSA may reach later layers |
| python_shadow_implementation | reconstructs the complete expected SSA from the same Initial IR | material implementation diversity and differential oracle | exact transformation and lifecycle equivalence lose their current oracle |
| canonical_comparison | checks alpha-normalized schema-v2 equality including instructions, CFG and metadata | independent expected value, shared comparison representation | all structurally-valid wrong-output mutations can escape |
| imported_rust_ssa_verifier | checks imported structure, types, CFG, SSA, dominance and lifecycle | independent implementation/algorithms but same Python SSA representation | malformed SSA is still checked by Rust verifier and importer; semantic equivalence is not |
| python_builder_verifier | checks the Python-produced SSA before comparison | self-verifies the oracle output | no effect if Python builder is absent |
| initial_ir_integrity_verifier | checks the pre-SSA module and freezes a same-input snapshot | independent prerequisite, not an SSA oracle | malformed input remains fail-closed but transformation correctness is not proven |
| lifecycle_verifier | checks local ARC/ownership invariants in imported SSA | independent rules; historical RC5 proved useful diversity | structurally valid but policy-wrong retain/release sequences may escape |
| schema_v2_importer | strict fields, tags, types, targets and lossless reconstruction | independent decoder sharing schema assumptions | well-formed semantic corruption is accepted |
| rust_side_verification | checks owned/schema structure, CFG shape, exact phi labels, exceptional edges and event ownership; it does not run the Initial-IR SSA namespace/dominance verifier over schema-v2 | common-mode with Rust producer and owned representation | remains, but cannot alone establish producer correctness |
| historical_corpus | 116/116 established checks and former failure reproducers | test evidence independent of runtime | regressions outside corpus can escape |
| adversarial_corpus | irreducible, exceptional, aggregate, lifecycle and malformed cases | test-only independent inputs | no per-compilation guarantee |
| randomized_differential_cfg | compares implementations over generated CFGs | high diversity but still differential/test-only | no per-compilation guarantee |
| deep_cfg_qualification | 100/1000/5000/10000 block stack-safety and determinism | test-only scale evidence | no per-compilation guarantee |
| platform_qualification | companion packaging and supported-platform behavior | operational evidence | platform regressions lose an oracle signal |
| operational_soak | repeated real-suite match/failure telemetry | operational differential evidence | future drift is no longer observed synchronously |
| rollback_modes | restores Python authority or Python-only behavior | recovery, not correctness evidence | rollback remains available but detection signal is weaker |

## Property matrix

| Property | Classification | Producer / verifiers | Independence and common mode | Without Python shadow |
|---|---|---|---|---|
| CFG preservation | `DIFFERENTIALLY_VERIFIED_ONLY` | Rust SSA lowerer; canonical comparison to Python shadow | material: it reconstructs the expected property from Initial IR; both builders can implement the same specification error; canonicalization can hide only qualified alpha/order differences | no per-compilation exactness guarantee; this property can escape |
| reachability | `REDUNDANTLY_VERIFIED` | Rust SSA lowerer; Rust-side verifier, Python imported-SSA verifier | real independent invariant derivation, but not exact-translation proof; shared schema/type assumptions can admit the same malformed meaning | the independent imported verifier can remain, but loses differential context |
| predecessor/successor consistency | `INDEPENDENTLY_VERIFIED` | Rust SSA lowerer; Python imported-SSA verifier | real independent invariant derivation, but not exact-translation proof; shared schema/type assumptions can admit the same malformed meaning | the independent imported verifier can remain, but loses differential context |
| dominance | `INDEPENDENTLY_VERIFIED` | Rust SSA lowerer; Python imported-SSA verifier | real independent invariant derivation, but not exact-translation proof; shared schema/type assumptions can admit the same malformed meaning | the independent imported verifier can remain, but loses differential context |
| immediate dominators | `TEST_ONLY` | Rust SSA lowerer; historical/adversarial/randomized/deep qualification | none at runtime; evidence exists only in qualification; test corpus can omit the same failure class | only regression evidence remains |
| dominance frontiers | `TEST_ONLY` | Rust SSA lowerer; historical/adversarial/randomized/deep qualification | none at runtime; evidence exists only in qualification; test corpus can omit the same failure class | only regression evidence remains |
| phi placement | `DIFFERENTIALLY_VERIFIED_ONLY` | Rust SSA lowerer; canonical comparison to Python shadow | material: it reconstructs the expected property from Initial IR; both builders can implement the same specification error; canonicalization can hide only qualified alpha/order differences | no per-compilation exactness guarantee; this property can escape |
| exact phi predecessor labels | `INDEPENDENTLY_VERIFIED` | Rust SSA lowerer; Python imported-SSA verifier | real independent invariant derivation, but not exact-translation proof; shared schema/type assumptions can admit the same malformed meaning | the independent imported verifier can remain, but loses differential context |
| SSA single definition | `INDEPENDENTLY_VERIFIED` | Rust SSA lowerer; Python imported-SSA verifier | real independent invariant derivation, but not exact-translation proof; shared schema/type assumptions can admit the same malformed meaning | the independent imported verifier can remain, but loses differential context |
| use dominated by definition | `INDEPENDENTLY_VERIFIED` | Rust SSA lowerer; Python imported-SSA verifier | real independent invariant derivation, but not exact-translation proof; shared schema/type assumptions can admit the same malformed meaning | the independent imported verifier can remain, but loses differential context |
| phi incoming dominance | `INDEPENDENTLY_VERIFIED` | Rust SSA lowerer; Python imported-SSA verifier | real independent invariant derivation, but not exact-translation proof; shared schema/type assumptions can admit the same malformed meaning | the independent imported verifier can remain, but loses differential context |
| type preservation | `DIFFERENTIALLY_VERIFIED_ONLY` | Rust SSA lowerer; canonical comparison to Python shadow | material: it reconstructs the expected property from Initial IR; both builders can implement the same specification error; canonicalization can hide only qualified alpha/order differences | no per-compilation exactness guarantee; this property can escape |
| parameter preservation | `DIFFERENTIALLY_VERIFIED_ONLY` | Rust SSA lowerer; canonical comparison to Python shadow | material: it reconstructs the expected property from Initial IR; both builders can implement the same specification error; canonicalization can hide only qualified alpha/order differences | no per-compilation exactness guarantee; this property can escape |
| block ordering/determinism | `DIFFERENTIALLY_VERIFIED_ONLY` | Rust SSA lowerer; canonical comparison to Python shadow | material: it reconstructs the expected property from Initial IR; both builders can implement the same specification error; canonicalization can hide only qualified alpha/order differences | no per-compilation exactness guarantee; this property can escape |
| unreachable block handling | `SHADOW_ONLY` | Rust SSA lowerer; Python shadow canonical comparison | material: it reconstructs the expected property from Initial IR; both builders can implement the same specification error; canonicalization can hide only qualified alpha/order differences | no per-compilation exactness guarantee; this property can escape |
| lifecycle/ownership invariants | `INDEPENDENTLY_VERIFIED` | Rust SSA lowerer; Python imported-SSA verifier | real independent invariant derivation, but not exact-translation proof; shared schema/type assumptions can admit the same malformed meaning | the independent imported verifier can remain, but loses differential context |
| schema-v2 integrity | `REDUNDANTLY_VERIFIED` | Rust SSA lowerer; Rust-side verifier, Python imported-SSA verifier | real independent invariant derivation, but not exact-translation proof; shared schema/type assumptions can admit the same malformed meaning | the independent imported verifier can remain, but loses differential context |
| canonical deterministic output | `DIFFERENTIALLY_VERIFIED_ONLY` | Rust SSA lowerer; canonical comparison to Python shadow | material: it reconstructs the expected property from Initial IR; both builders can implement the same specification error; canonicalization can hide only qualified alpha/order differences | no per-compilation exactness guarantee; this property can escape |

## Mutation detection matrix

Every row is a mutation of a copy of a real Rust schema-v2 result. `PYTHON_SHADOW_ONLY` means schema import and both executable invariant verifiers accepted it, while comparison with independently built Python SSA rejected it.

| Mutation | Detected by | Shadow-only |
|---|---|---|
| missing_phi | CANONICAL_COMPARISON, PYTHON_SHADOW_ONLY | yes |
| extra_phi | CANONICAL_COMPARISON, PYTHON_SHADOW_ONLY | yes |
| incorrect_phi_incoming | CANONICAL_COMPARISON, PYTHON_SHADOW_ONLY | yes |
| incorrect_predecessor | PYTHON_IMPORTED_SSA_VERIFIER, RUST_VERIFIER, CANONICAL_COMPARISON | no |
| duplicate_definition | PYTHON_IMPORTED_SSA_VERIFIER, CANONICAL_COMPARISON | no |
| use_before_definition | PYTHON_IMPORTED_SSA_VERIFIER, CANONICAL_COMPARISON | no |
| definition_not_dominating_use | PYTHON_IMPORTED_SSA_VERIFIER, CANONICAL_COMPARISON | no |
| phi_incoming_not_dominating_edge | PYTHON_IMPORTED_SSA_VERIFIER, CANONICAL_COMPARISON | no |
| incorrect_type | PYTHON_IMPORTED_SSA_VERIFIER, CANONICAL_COMPARISON | no |
| incorrect_value_rename | CANONICAL_COMPARISON, PYTHON_SHADOW_ONLY | yes |
| incorrect_block_target | PYTHON_IMPORTED_SSA_VERIFIER, CANONICAL_COMPARISON | no |
| unreachable_block_incorrectly_preserved | CANONICAL_COMPARISON, PYTHON_SHADOW_ONLY | yes |
| missing_instruction | CANONICAL_COMPARISON, PYTHON_SHADOW_ONLY | yes |
| duplicated_instruction | CANONICAL_COMPARISON, PYTHON_SHADOW_ONLY | yes |
| incorrect_return_value | CANONICAL_COMPARISON, PYTHON_SHADOW_ONLY | yes |
| ownership_lifecycle_corruption | OTHER | no |

Shadow-only mutations: `missing_phi`, `extra_phi`, `incorrect_phi_incoming`, `incorrect_value_rename`, `unreachable_block_incorrectly_preserved`, `missing_instruction`, `duplicated_instruction`, `incorrect_return_value`.

The scalar fixture cannot honestly exercise ARC corruption; that row is marked `OTHER`. Concrete ownership evidence comes from RC1–RC5 below.

### What Python uniquely guarantees today

| Guarantee | Required replacement |
|---|---|
| exact required phi placement and selected incoming values | Initial-IR slot def/use plus iterated-dominance-frontier translation validator |
| exact instruction and side-effect sequence preservation | cross-representation semantic refinement and effect-order verifier |
| returned value and value provenance preserve Initial IR meaning | value provenance/refinement certificates checked independently |
| qualified reachable/unreachable block policy | explicit cross-IR reachability preservation verifier |
| exact lifecycle retain/release policy sequence | independent ownership transfer/lifetime translation verifier |

## Historical mismatch audit

| ID | Cause | Detection at discovery | Would escape without shadow then? | Current assessment |
|---|---|---|---|---|
| RC1 | missing last-use release for owning expression temporary | CANONICAL_COMPARISON | yes | regression possible; covered by fixtures and lifecycle policy tests |
| RC2 | extra retain during nullable-owned return transfer | CANONICAL_COMPARISON | yes | regression possible; covered by fixture |
| RC3 | missing nullable class argument copy lifetime | CANONICAL_COMPARISON | yes | regression possible; covered by fixture |
| RC4 | missing lifecycle default for interface | RUST_LANE_FAILURE | no | closed by lifecycle capability support and regression fixture |
| RC5 | missing normal release of owning constructor receiver | PYTHON_IMPORTED_SSA_VERIFIER | yes | specific defect closed; class remains material because Rust verifier shared the defect |
| RC6 | LeakSanitizer under ptrace | OTHER | no | environmental, not an SSA mismatch |

The audit does not infer details absent from the recorded RUST-3.6a evidence. RC1–RC3 were exact lifecycle mismatches caught by comparison; RC5 was materially stronger evidence: Rust production plus its owned verifier accepted a missing release that the imported Python verifier rejected. The specific defects are closed by regression fixtures, but the common-mode class remains possible.

## Independent oracle and common-mode analysis

Different code is not automatically an independent proof. Python dominators and the imported verifier provide genuine independent evidence for dominance, exact phi edges, definitions and internal types because they derive invariants from the received graph. Python phi construction supplies implementation diversity, but exact phi necessity and exact instruction/lifecycle preservation are still differential evidence: the verifier does not reconstruct the intended translation.

- Rust producer and Rust verifier share owned SSA codecs, operand inventories and rule interpretations
- Python importer and imported verifier share Python SSA dataclasses and type reconstruction
- both lanes consume the same potentially malformed Initial IR after the common integrity verifier
- both boundary verifiers assume schema-v2 expresses every required semantic field
- canonical alpha-normalization intentionally hides identifier spelling and phi incoming ordering differences

## Verifier completeness gaps

| Severity | Gap | Required replacement |
|---|---|---|
| `CRITICAL` | no independent proof that Rust preserves the complete instruction/lifecycle sequence of Initial IR | Initial-IR-to-SSA semantic refinement verifier or independently specified translation validator |
| `CRITICAL` | no independent required/minimal phi-placement oracle | slot def/use plus iterated-dominance-frontier phi necessity verifier |
| `IMPORTANT` | valid unreachable-block retention/removal policy is not checked | explicit reachability preservation contract against Initial IR |
| `IMPORTANT` | parameter, block and side-effect sequence preservation is only differential | cross-representation provenance/refinement checks |
| `DEFENSE_IN_DEPTH` | Rust producer and Rust verifier share owned representations and helper assumptions | keep Python imported verifier in the future independent boundary |
| `NON_SEMANTIC` | canonical alpha-normalization hides qualified identifier spelling and phi incoming order | retain deterministic raw-output tests; no runtime semantic gate required |

Critical gaps exist and are currently covered only by differential comparison. Therefore RUST-4.0 cannot recommend removing the shadow.

## Future qualification architecture

```text
Initial IR integrity verifier
        |
        v
Rust SSA authority
        |
        v
independent structural + semantic translation verifier
        |
        v
optimizer / backend
```

The replacement verifier must check cross-representation CFG/reachability, parameters and types, required phi placement, side-effect and lifecycle sequence preservation, and value provenance. Only a later promotion milestone may move Python to CI, debug, sampling and rollback roles.

## Files created

- `docs/compiler/RUST_SSA_INDEPENDENT_AUTHORITY_QUALIFICATION.md`
- `docs/compiler/rust_ssa_independent_authority_qualification.json`
- `scripts/qualify_rust_ssa_independent_authority.py`
- `scripts/check_rust_ssa_independent_authority_qualification.py`
- `tests/aether/test_rust_ssa_independent_authority_qualification.py`

No production source file is part of RUST-4.0.

## Qualification status

- rust_4_0_checker: `PASS`
- mutation_campaign: `PASS`
- historical_116_of_116: `PASS`
- adversarial: `PASS`
- deep_cfg: `PASS`
- production_regressions: `PASS`
- authority_shadow_fail_closed_contracts: `PASS`
- rust_3_8a_through_3_15_contracts: `PASS`
- full_python_suite: `PASS`
- cargo_test_workspace_locked: `PASS`
- cargo_fmt_check: `PASS`
- git_diff_check: `PASS`

Gate notes:
- full_python_suite: unmodified environment reproduced only the 24 historical RC6 ptrace/LeakSanitizer native failures plus the then-pending new checker; with LSAN_OPTIONS=detect_leaks=0 the Rust-authority full suite passed 4941 with 4 skipped, and the finalized RUST-4.0 tests passed 6/6
- adversarial: fresh /tmp evidence passed; the older checked-in adversarial artifact is stale and was not modified
- workspace_preservation: pre-existing user changes were not modified or reverted

Production unchanged: yes.

Python shadow remains mandatory: yes.

No commit was created.
