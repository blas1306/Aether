# O2.9.2 — Aggregate lifetime analysis foundation

Status: **complete, analysis only**. Primary recommendation:
`PROCEED_TO_COLLECTION_EXTRACTION_BORROW_ANALYSIS`.

The implementation is a read-only consumer of lifecycle-expanded SSA. It is
not in O0/O1/O2, is not called by LocalARC, and cannot alter lifecycle
expansion or code generation. Reproduce the evidence with
`python scripts/o2_aggregate_lifetime_analysis.py --output docs/compiler/o2_aggregate_lifetime_baseline.json`.

## Lifetime and identity model

An aggregate SSA result is an aggregate instance; it is not an ownership root
for every nested reference. Each instance records definition, ordered
first/last use, destruction points, loop/depth, conservative CFG crossings,
escape, origin, category, materialization and borrow opportunity. Ambiguous
CFG intervals remain conservative.

Canonical categories are `SEMANTIC_OWNER`, `AGGREGATE_COPY`,
`COLLECTION_EXTRACTION_TEMPORARY`, `STRUCT_RECONSTRUCTION_TEMPORARY`,
`METHOD_RESULT_TEMPORARY`, `CALL_RESULT_TEMPORARY`, `PHI_MERGE_VALUE`,
`LOOP_CARRIED_AGGREGATE`, `RETURN_VALUE`, `ESCAPING_AGGREGATE`,
`DESTRUCTION_ONLY`, and `UNKNOWN`. Origins cover source/constructor,
collection extraction, function/method return, MethodResult component,
copy/reconstruction, phi, parameter, constant/default and unknown.

The component ledger uses nominal field paths and O2.8.8 provenance. It records
exact roots, ownership role, attributable retain/release points and escape.
`same_semantic_aggregate_value` is separate from ownership identity and only
succeeds for equal, nonempty component ledgers. LocalARC never consumes it.

## Semantics found

- `struct_new` creates a value-semantic owner. Independent nested roots remain
  distinct; initialization rollback remains governed by lifecycle expansion.
- A struct copy may legitimately need independent nested owners. `struct_set`
  reuses unaffected provenance and replaces the selected component; its ARC is
  reconstruction traffic, not automatically redundant.
- `struct_get` preserves component provenance. Ownership calls around the
  result determine whether another owner exists.
- List/Array extraction creates a new aggregate SSA instance. Unknown
  element-sensitive roots remain unknown. Immediate get/decompose/destroy
  shapes are representation-induced candidates, but are not changed to borrows.
- Aggregate phis merge component facts; loop phis are loop-carried. A phi does
  not by itself prove acquisition of a new owner.
- MethodResult receiver, result and wrapper are distinct. Wrapper escape is
  distinct from component escape.
- Parameters are symbolic borrowed inputs. Calls, returns, field/collection
  stores, interfaces and exceptions are separate escape classes.
- Copy chains are observable through origin and cautious semantic equivalence;
  no transform consumes them.

ARC attribution supports construct, copy, extract, field acquire/release,
temporary/aggregate destroy, return transfer, parameter copy, phi merge,
reconstruction, collection store and collection extraction. Component
attribution requires exactly matching provenance.

## Exact hot-ARC reconciliation

All 32 O2.9.1 sites belong to expense-tracker `decodeLedger`. Every row is in
`o2_aggregate_lifetime_baseline.json` with workload/function/loop, operation,
SSA/type, aggregate instance, component path, category, attribution,
necessity, escape, future family, confidence and structural hotness.

| Final classification | Sites | Weighted hotness |
|---|---:|---:|
| `EXTRACTION_TEMPORARY` | 19 | 85 |
| `COPY_INDUCED` | 4 | 18 |
| `ESCAPE_REQUIRED` | 9 | 36 |
| **Total** | **32** | **139** |

All 27 Array-get releases are attributed to collection extraction. Nineteen
are nonescaping under current proof and are theoretical extraction-elision
candidates. Nine retain conservative escape evidence and are not claimed
removable. Four call-result struct destructions are copy-induced candidates.
“Candidate” never means currently safe.

## Future matrix and safety

| Family | Sites | Hotness | Main risk | LLVM |
|---|---:|---:|---|---|
| Aggregate copy elision | 4 | 18 | losing legitimate independent ownership | partial |
| Collection extraction elision/borrowing | 19 | 85 | dangling fields or mutation invalidation | Aether-unique |
| Borrowed temporary views | 0 separately proven | 0 | dangling internal view | Aether-unique |
| Scalar replacement | 0 | 0 | ownership splitting and ABI interaction | partial |
| Lifetime hoisting | 0 | 0 | destruction/exception timing | partial |
| Stack promotion | 0 | 0 | escaping identity/destructors | partial |
| No safe elimination | 9 | 36 | semantic ownership loss | partial |

LLVM may scalarize exposed aggregate data (`LLVM_PARTIAL`), but Aether ARC
runtime calls and collection ownership are `AETHER_UNIQUE`; LLVM cannot recover
nested ownership hidden behind those calls.

Collection extraction borrowing is the best next analysis because it covers
19/32 sites and 85/139 hotness units. It must prove collection mutation cannot
invalidate a view, fields cannot outlive it, and exceptional cleanup remains
equivalent. Stop before source borrows, element-sensitive heap SSA, ABI or
lifecycle changes.

## Limitations and freeze

The analysis is block/edge-aware, not a precise path scheduler or
element-sensitive collection analysis. Unknown roots and escapes stay unknown;
the audit is structural, not dynamic profiling. Production remains 48 retains
and 919 releases. LocalARC, lifecycle expansion, O0/O1/O2 membership and
codegen are unchanged.
