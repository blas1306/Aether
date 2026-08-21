# RUST-3.6a Rust SSA promotion failure root-cause audit

Decision: `RUST_SSA_PROMOTION_FAILURES_CLASSIFIED`

The failed RUST-3.6 promotion has been rolled back safely. The repository
default is `PYTHON_SSA_AUTHORITY_RUST_SHADOW`; it returns verified Python SSA
only after the synchronous Rust lane matches. `PYTHON_SSA_ONLY` preserves the
historical production behavior, and `RUST_SSA_AUTHORITY_PYTHON_SHADOW` remains
available as an explicit fail-closed qualification mode. The Rust-authority
implementation and the failed-promotion artifacts were not removed or
rewritten. Initial IR verification remains Rust RP3 authority.

## Inventory result

The same focused nine-file selection recorded by RUST-3.6 produces 42 failing
pytest node IDs in this execution environment. Boundary instrumentation splits
that headline number into 18 deterministic SSA promotion blockers and 24
native LeakSanitizer harness aborts. The latter all report that LeakSanitizer
cannot operate under `ptrace`; with `LSAN_OPTIONS=detect_leaks=0`, the complete
`test_native_exceptions.py` module is 54/54 passing. They are therefore
accounted for at boundary J, but are not exceptional-cleanup SSA divergences.
This corrects the earlier aggregate artifact's `environmental_failures: 0`
classification without altering that historical artifact.

The machine-readable artifact lists all 42 node IDs and their results:
[`rust_ssa_promotion_failure_root_cause_audit.json`](rust_ssa_promotion_failure_root_cause_audit.json).

## Root-cause clusters

| Cause | Tests | First divergence | Comparator | Normative owner |
| --- | ---: | --- | --- | --- |
| RC1: Rust omits last-use release of an owning expression temporary after a borrowed projection/interface use | 10 | B, lifecycle-normalized Initial IR | Detects all 10 | Rust violates owned-temporary lifecycle policy |
| RC2: Rust retains a nullable owning aggregate during return transfer | 1 | B | Detects | Rust violates return-transfer policy |
| RC3: Rust omits the copy-lifetime retain/release around a nullable class constructor argument | 1 | B | Detects | Rust violates constructor-argument lifecycle policy |
| RC4: Rust's lifecycle registry has no default for interface values | 2 | B | Not reached | Rust lifecycle capability implementation |
| RC5: Rust omits the normal release of an owning struct constructor receiver | 4 | B | Not reached; imported verifier stops first | Rust lowering defect plus Rust Owned SSA verifier discrepancy |
| RC6: LeakSanitizer startup abort under `ptrace` | 24 | J, native behavior | Not authority-specific | Test execution environment |

No case has canonical equality followed by different optimizer or backend
behavior. Twelve SSA cases reach canonical comparison and are rejected there.
Two stop during Rust lifecycle normalization, and four are accepted by the
Rust Owned verifier but rejected by Python verification immediately after the
schema-v2 import. All 18 SSA cases stop before optimizer entry.

## Boundary localization

The boundary labels used by the audit are:

1. A — verified Initial IR
2. B — lifecycle-normalized Initial IR
3. C — pre-import Rust Owned SSA
4. D — schema-v2 DTO
5. E — Python-imported Rust `SSAModule`
6. F — authoritative Python `SSAModule`
7. G — canonical SSA
8. H — optimizer input
9. I — post-optimizer SSA
10. J — backend/native behavior

For RC1–RC5, A is common and verified. The first differing operation is
introduced (or omitted) by Rust lifecycle normalization at B. DTO/import
inspection shows no codec loss: where C is produced, D and E preserve the Rust
instruction stream. RC5 is especially useful: Rust produces and verifies C,
schema-v2 preserves it, then the Python verifier at E diagnoses the absent
constructor receiver release. A downstream patch would hide an upstream
lifecycle and verifier defect, so none was made.

RC6 reaches native execution. Its first divergent observable state is the
sanitizer's process-startup stderr, including a process-specific PID. Disabling
leak detection changes 24 failures to passes without changing source, IR, SSA,
optimizer, backend, exception mode, or authority configuration.

## Concrete first differences

- RC1: Python emits `__aether_release` immediately after the final borrowed use
  of an owned call result (for example `split(...).length`,
  `identity(values).length`, or `identity(interface).get()`); Rust omits it.
- RC2: Rust emits an additional `__aether_retain` on the nullable aggregate
  immediately before `return`; Python transfers the existing ownership.
- RC3: Python emits `retain(nullable-class-argument)`, constructor call,
  `release(nullable-class-argument)`; Rust emits only the call.
- RC4: Rust stops with `type 'Interface { name: "Readable" }' has no lifecycle
  default`; Python constructs and verifies the interface phi/lifecycle form.
- RC5: Python emits `release(receiver)` after the struct constructor call and
  before `method_result_receiver`; Rust omits it. Python's verifier reports
  that the constructor receiver lacks exactly one normal release.

Block order, instruction order outside these lifecycle operations,
value/result identities after alpha normalization, phi placement, source
locations, `transferred_storage`, aggregate/interface metadata, witness data,
box layout, and schema-v2 reserialization did not produce an earlier
divergence in the minimized cases.

## Minimized reproducers and mode matrix

The minimized source fixtures are under
[`tests/fixtures/rust_ssa_promotion_failure`](../../tests/fixtures/rust_ssa_promotion_failure).
Run their boundary and three-mode audit with:

```text
.venv/bin/python scripts/audit_rust_ssa_promotion_failure.py
```

RC1 has three small shapes because the same last-use defect crosses aggregate,
builtin-call, and interface-call representations. RC2–RC5 each have one
source-level reproducer.

| Mode | Returned origin on affected reproducers | Mismatch | Downstream |
| --- | --- | --- | --- |
| `PYTHON_SSA_ONLY` | `python_general_ssa_builder` | Not compared | Optimizer passes |
| `PYTHON_SSA_AUTHORITY_RUST_SHADOW` | None | 12 mismatch, 2 Rust-lane failure, 4 imported-verifier failure | Fail closed before optimizer |
| `RUST_SSA_AUTHORITY_PYTHON_SHADOW` | None | Same diagnostics | Fail closed before optimizer |

Thus prior shadow qualification could have detected every SSA defect had these
program shapes been in its corpus. RUST-3.3/RUST-3.4 missed RC1–RC5 because of
corpus coverage gaps; this is not a canonicalizer blind spot or an
authority-only import path. RC5 additionally reveals a verifier discrepancy:
the Rust Owned verifier accepts a constructor receiver state rejected by the
qualified Python boundary verifier. RC6 was incorrectly aggregated into the
promotion count rather than being normalized as sanitizer harness output.

## Policy judgment and scope

Existing qualified lifecycle rules are sufficient to judge RC1–RC5. Rust is
the violating implementation in each case; RC5 also belongs to the Rust Owned
SSA verifier. No missing normative rule was found, and Python was not treated
as correct merely because it is Python: the decisions follow transfer,
last-use destruction, constructor receiver, and lifecycle capability checks
already enforced by the verified boundary.

This milestone changes no Rust or Python lowering semantics, lifecycle policy,
schema, canonical comparison, optimizer, or backend. It restores only the safe
authority default, updates the ownership registry to SSA RP2/Python authority,
adds a regression for Python-origin return plus fail-closed Rust mismatch
detection, and adds diagnostic evidence/reproducers. No cross-platform
authority qualification or commit was created.
