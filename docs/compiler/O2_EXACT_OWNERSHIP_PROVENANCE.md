# O2.8.6 exact ownership provenance expansion

O2.8.6 is analysis-only.  Exact means one unique semantic ownership root; it
does not mean that no other SSA value aliases that root.  Copies, reference
casts, and phis whose reachable inputs all have the same exact root preserve
it.  Different-root and unknown-input phis fail closed.  Field and collection
loads remain unknown because this milestone does not add heap SSA.

## Pre-change reconciliation

This table was captured from the corrected 26-candidate audit before changing
the analysis.  All rows have type `StringType`; no row crosses a field,
collection, interface, exception edge, or `MethodResult` boundary.

| Workload / function | SSA | retain -> release | root; exact; reason | definition | ownership | crossings | blocker |
|---|---:|---|---|---|---|---|---|
| expense tracker / `decodeLedger` | `626` | `merge75:0` -> `then77:3` | `unknown:626`; false; unknown external call | `SSACall(text.byteSlice)` | owned | call, runtime helper | `RUNTIME_HELPER_RETURN_UNKNOWN` |
| expense tracker / `decodeLedger` | `626` | `merge77:0` -> `then79:3` | `unknown:626`; false; unknown external call | `SSACall(text.byteSlice)` | owned | call, runtime helper | `RUNTIME_HELPER_RETURN_UNKNOWN` |
| expense tracker / `decodeLedger` | `626` | `merge79:0` -> `merge61:14` | `unknown:626`; false; unknown external call | `SSACall(text.byteSlice)` | owned | call, runtime helper | `RUNTIME_HELPER_RETURN_UNKNOWN` |
| expense tracker / `decodeLedger` | `cond2.description.phi` | `merge87:0` -> `merge87:12` | `unknown:cond2.description.phi`; false; other | `SSAPhi` | unknown | phi | `PHI_MERGE` |
| expense tracker / `decodeLedger` | `cond2.category.phi` | `merge87:1` -> `merge87:13` | `unknown:cond2.category.phi`; false; other | `SSAPhi` | unknown | phi | `PHI_MERGE` |
| expense tracker / `decodeLedger` | `cond2.date.phi` | `merge87:2` -> `merge87:11` | `unknown:cond2.date.phi`; false; other | `SSAPhi` | unknown | phi | `PHI_MERGE` |
| expense tracker / `encodeLedger` | `67` | `merge5:1` -> `then6:2` | `unknown:67`; false; unsupported instruction | `SSAConst` | unknown | none | `UNSUPPORTED_INSTRUCTION` |
| expense tracker / `readControlLine` | `29` | `merge2:5` -> `merge2:7` | `unknown:29`; false; unknown external call | `SSACall(text.byteSlice)` | owned | call, runtime helper | `RUNTIME_HELPER_RETURN_UNKNOWN` |
| expense tracker / `runUtilityCommand` | `40` | `merge3:1` -> `then4:4` | `unknown:40`; false; unsupported instruction | `SSAConst` | unknown | none | `UNSUPPORTED_INSTRUCTION` |
| expense tracker / `runDemo` | `1` | `entry:2` -> `logic.merge5:33` | `unknown:1`; false; unsupported instruction | `SSAConst` | unknown | none | `UNSUPPORTED_INSTRUCTION` |
| expense tracker / `runDemo` | `2` | `entry:4` -> `logic.merge5:32` | `unknown:2`; false; unsupported instruction | `SSAConst` | unknown | none | `UNSUPPORTED_INSTRUCTION` |
| expense tracker / `runDemo` | `3` | `entry:6` -> `logic.merge5:31` | `unknown:3`; false; unsupported instruction | `SSAConst` | unknown | runtime helper | `UNSUPPORTED_INSTRUCTION` |
| expense tracker / `runDemo` | `4` | `entry:8` -> `logic.merge5:30` | `unknown:4`; false; unsupported instruction | `SSAConst` | unknown | runtime helper | `UNSUPPORTED_INSTRUCTION` |

## Implemented model

- Reference parameters are exact parameter identities, while alias queries
  remain conservative.
- String constants, fresh allocations, and explicitly trusted fresh helpers
  introduce unique roots.
- Identity-preserving reference casts copy the source root.
- Direct fixed-point summaries distinguish a unique fresh return from a return
  aliasing exactly one parameter. Multiple alternative fresh roots are not
  summarized as one fresh identity.
- Unknown external/runtime calls, indirect/interface calls, field loads,
  collection loads, different-root phis, and unknown-input phis have distinct
  deterministic reasons.
- Trusted runtime knowledge is centralized in `trusted_helpers.py`; arbitrary
  external functions receive no contract.

The unsupported-instruction audit classified `SSAConst<String>` as an exact
fresh root and all remaining ownership-relevant fallthroughs conservatively as
`UNSUPPORTED_INSTRUCTION`. Tests cover that fail-closed behavior and the
supported propagation rules.

## Corrected audit and dry-run

The safe analysis-only result retains all 26 candidates:

| Measurement | Before | After |
|---|---:|---:|
| Semantically provable | 0 | 2 |
| Provenance blocked | 13 | 7 |
| Nested aggregate | 12 | 12 |
| Escape | 1 | 4 |
| Normal join | 0 | 1 |

Six of the 13 sites cease to be provenance-blocked; two become semantically
provable. The other four expose the next conservative escape/join blocker.
The three phi sites and four `text.byteSlice` sites remain provenance-unknown.

LocalARC dry-run: Phase 1 semantic 0, Phase 1 structural 0, Phase 2 semantic 2,
Phase 2 structural 0, and **0 pairs would be eliminated** by the current pass.

`text.byteSlice` was separately validated as a fresh string-producing runtime
operation. Enabling that trusted contract made the already-enabled production
LocalARC pass remove the same-block `readControlLine` pair during O2 compilation
(26 candidates became 25). The milestone explicitly requires stopping before
accepting such an automatic codegen change, so that contract is intentionally
not enabled here and remains `UNKNOWN_RUNTIME_HELPER`. This records the exact
boundary instead of weakening eligibility or changing the pass.
