# O2.9.6 — Post-ArrayGet Hot Ownership Audit

Status: **`PROCEED_TO_IMMEDIATE_ARRAY_STRING_BORROW`**.

This is a read-only audit of the production O2 pipeline after O2.9.5. It does
not change ownership, lifecycle, Array/String semantics, LLVM lowering, runtime
ABI, LocalARC, `OwnershipElidedArrayGet`, or profile membership. The canonical
machine-readable evidence is
`o2_post_arrayget_hot_ownership_audit.json`; regenerate it with
`scripts/o2_post_arrayget_hot_ownership_audit.py`.

## Baseline and scope

The fixed productive corpus produces 48 explicit SSA retains and 904 explicit
SSA releases (952 operations) in 34 functions. Natural loops contain 11 retains
and 40 releases (51 explicit operations), all in the expense tracker, in
`Persistence.decodeLedger` and `Persistence.encodeLedger`. This exactly matches
the post-O2.9.5 reference. No baseline discrepancy had to be explained.

Backend lowering adds a separate census of 72 implicit owned-get retains: 63
ordinary reference/component retains and nine aggregate-component retains.
Fourteen occur in loops. These are deliberately not added to the SSA counters.
The audit records every explicit loop operation and every implicit backend site
with workload, function, natural-loop identity/depth, block/index, value/type,
provenance or collection root, ownership role, lifecycle origin, pairing,
semantic category, structural hotness, and blockers.

## Cost model and the 11/40 asymmetry

The canonical categories are `SSA_RETAIN`, `SSA_RELEASE`,
`BACKEND_IMPLICIT_RETAIN`, `AGGREGATE_COMPONENT_RETAIN`,
`AGGREGATE_COMPONENT_RELEASE`, `TEMPORARY_OWNER`,
`INITIAL_OWNER_RELEASE`, `COLLECTION_OWNER`, `CALL_BOUNDARY_OWNER`,
`INTERFACE_OWNER`, `EXCEPTION_OWNER`, and `OTHER`.

The 40 loop releases classify as 5 balancing explicit retains, 12 balancing
backend-owned collection extractions, 12 temporary destructions, seven
call-result cleanups, and four other lifecycle destructions. Thus the
29-operation explicit retain/release difference is expected: initial owners,
call results, aggregate/components and collection temporaries can require
destruction without a matching explicit SSA retain at that point. Net-count
arithmetic is not an ownership proof.

## O2.9.5 reconciliation and remaining Array<String>

All 15 frozen direct-projection identities are present in the exclusion table.
Each current get is borrowed, has no lifecycle release and prevents the backend
temporary retain. Its original bounds behavior and loop depth are preserved;
bounds checks remain unless BCE independently proved them unnecessary.

Exactly four O2.9.4 cases remain owned:

| Class | Count | Current cost/site | Finding |
|---|---:|---:|---|
| Immediate borrow | 3 | 1 backend retain + 1 SSA release | Owner covers the sole immediate call use; no mutation, alias mutation, exception region, backedge or consuming context was found. Ready for a bounded qualification milestone. |
| Stable region | 1 | 1 backend retain + 1 SSA release | Crosses a longer use interval. Dominance/post-dominance and lifetime-region proof make this qualitatively different; do not merge it into the immediate proof. |

O2.9.5 excluded these because its frozen production rule admits only a sole
`SSACompareOp` direct projection. That exclusion still controls current code;
the audit does not optimize the four sites. The theoretical ceiling is three
retain/release pairs for immediate qualification and one pair for the stable
region.

## Current distributions

String ownership remains dominant in the loops: 11/31 explicit retain/release
operations plus 14 implicit backend retains. Outside loops it has 25/158
explicit operations plus 49 implicit retains. Array values contribute three
loop releases; List values contribute one. The get corpus contains 79
`Array<String>` gets, ten `Array<Struct>`, thirteen `List<Struct>`, three scalar
Array gets and one scalar List get. There is no hot real-workload
`List<String>`, class/interface-element, or aggregate-element implicit get.

The post-O2.9.5 hot aggregate set is 4 extraction temporaries, 4 copy-induced
sites, and 9 escape-required sites. The prior four copy sites remain hot and
unchanged; their value-copy semantics are required today, a future copy-elision
proof could remove them, and LLVM overlap is only partial because Aether owns
the lifecycle contract. The nine escape-required identities remain hot; the
present evidence cannot safely reclassify a real or conservatively modeled
escape, so none is counted as an opportunity. The JSON retains exact identities
and reasons for both groups.

LocalARC has no remaining semantic or structural candidate in the current
corpus. MethodResult/constructor and interface ownership have zero loop
operations. Exception-related ARC has six whole-corpus operations and zero in
loops. Call-boundary ownership accounts for eleven loop operations, but no loop
site is blocked by an unknown call summary. Fresh loop allocations are listed
individually with type, depth, escape and possible stack-promotion/scalar-
replacement disposition; their broader proof/risk keeps them below the bounded
immediate-borrow work.

## Hotness and backend findings

Structural hotness is deterministic:

```text
max(1, 1 + 2*loop_depth - conditional + real_workload - test_only)
```

It is a static ranking, not measured runtime frequency. No dynamic
instrumentation was added because that would be invasive for an audit-only
milestone. Loop depth two therefore ranks above depth one, unconditional sites
above conditional sites, and real programs above probes. Every top site is in
the expense tracker. Backend owned gets, especially `Array<String>`, remain an
Aether-visible cost that the explicit SSA retain count alone hides.

`List<String>` uses the same owned-get backend rule and would need the same
owner-lifetime/mutation proof, but this corpus has no hot instance, so it is
deprioritized. The same conceptual model may later apply to class or interface
elements, but there is no current hot evidence. Struct elements require
component-wise value ownership and are a different aggregate-copy problem.

## Optimization-family decision

| Family | Hot evidence | Complexity / risk | Decision |
|---|---|---|---|
| Immediate Array<String> borrow | 3 real loop pairs | Low / low, bounded proof | **Proceed** |
| Stable-region Array<String> borrow | 1 real loop pair | High / high | Defer |
| Aggregate copy elision | 4 hot sites | High / medium; LLVM partial | Defer |
| List<String> get elision | No hot site | Medium / medium | Deprioritize |
| Reference-element get elision | No hot site | High / high | Deprioritize |
| Escape/stack promotion | Fresh allocations exist | High / high | Analyze later |
| GVN/CSE | No ownership-specific count | Medium / low; LLVM high | Do not replace bounded Aether work |
| General loop optimization | High general relevance | High / medium | Continue independently after bounded work |

The three immediate sites pass the decision threshold: they execute in a real
hot loop, admit a small owner-covered proof, remove Aether-specific ARC LLVM
cannot infer, and do not need broad path-sensitive lifetime machinery. The
single stable site fails the final criterion for its small gain. Aggregate copy
elision has comparable static count but a materially broader semantic surface.
Generic GVN/CSE, memory LICM, canonicalization, IV simplification, strength
reduction, inlining and scalar replacement remain valuable readiness items,
but none displaces this narrowly bounded next ownership milestone.

Therefore the sole recommendation is
**`PROCEED_TO_IMMEDIATE_ARRAY_STRING_BORROW`**.

## Validation and freeze

Tests cover the 48/904 and 11/40 censuses, separation of explicit and implicit
layers, complete release classification, exclusion of all 15 O2.9.5 sites,
the remaining 3+1 split, deterministic structural hotness/family ranking and
recommendation, canonical JSON serialization, and production freeze. Historical
O2.9.1–O2.9.5 artifacts remain immutable.

Before and after this audit, production SSA is 48 retains / 904 releases and
loop SSA is 11 / 40. `OwnershipElidedArrayGet`, LocalARC, lifecycle, backend,
codegen, runtime and O0/O1/O2 membership are unchanged. No transformation test
was added and no commit was created.
