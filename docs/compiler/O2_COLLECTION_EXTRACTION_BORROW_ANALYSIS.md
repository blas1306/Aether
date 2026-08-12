# O2.9.3 — Collection extraction borrow analysis

Status: **complete, analysis only**. Recommendation:
`IMPROVE_BORROW_ANALYSIS_FIRST`.

The audit adds a read-only `CollectionExtractionBorrowAnalysis` and a conceptual
`BorrowedAggregateView(collection_root, element_selector, aggregate_type,
borrow_start, borrow_end, invalidation_conditions)`. It is not an SSA
instruction, is not registered in an optimization profile, and is not consumed
by lifecycle expansion, LocalARC, or code generation.

## Reconciliation result

The fixed O2.9.2 set contains exactly 19 sites, all in expense-tracker
`decodeLedger`: 5 at loop depth 1 (hotness 15) and 14 at depth 2 (hotness 70),
for total structural hotness 85. The machine-readable table records every site
and every requested column in
`o2_collection_extraction_borrow_baseline.json`.

The critical result is that all 19 values are `StringType()` results of
`SSAArrayGet`, not Struct aggregate values. O2.9.2 grouped collection-element
ownership traffic under `EXTRACTION_TEMPORARY`; it did not establish that the
element was an aggregate. Consequently none of the exact 19 can honestly be
qualified by the new *aggregate* view proof from the information preserved in
that baseline. All 19 are `UNKNOWN`, with `OTHER` (candidate-kind mismatch) and
`UNKNOWN_COMPONENT_OWNERSHIP` blockers. The qualified ARC reduction is zero;
the deliberately unqualified ceiling is 19 releases. This is not a claim that
those releases are removable.

## Current collection semantics and storage

Array and List elements are stored inline in separately allocated contiguous
buffers. Indexing computes an element address, loads a value, retains an owned
payload when required, and preserves the existing bounds check and panic. Thus
source indexing returns an independent value copy; an internal view must never
be exposed as source semantics.

Array has fixed length and no operation that reallocates its data buffer.
`ArraySet` overwrites one element (retaining the replacement and releasing the
old owned payload), so it invalidates a view of that element. Whole-array
reassignment, an aliasing/unknown write, or collection destruction invalidates
all views. Fixed length does not imply immutable elements.

List owns a contiguous capacity buffer. `push` and `insert` may reserve a new
buffer, copy bytes, free the old buffer, and therefore invalidate all element
locations. `insert`, `removeAt`, `pop`, `clear`, and `reverse` also change
numeric-index element identity; they invalidate all conservatively. `set`
replaces one selected element without a required relocation and invalidates
that element; unknown index equality is treated as all/unknown. Whole-list
reassignment and destruction invalidate all views.

| Operation | Potential view effect |
|---|---|
| List push/insert/removeAt/pop/clear/reverse | all element views |
| List set | selected element; all if selector equality is unknown |
| Array set | selected element; all if selector equality is unknown |
| whole collection reassignment/destruction | all element views |
| mutation through MUST/MAY alias | same rule / conservative all |
| unknown, indirect, or interface call with visibility | unknown; blocks |

An unchanged integer index is not stable element identity after List mutation.
Constant, induction, invariant, and variant selectors are recorded separately;
none overrides invalidation. A collection owner must remain alive through the
last aggregate/component access, and initial qualification rejects any interval
crossing a backedge.

## Qualification rules

The candidate interval begins at the get and ends at the last use requiring
aggregate or component access. Same-expression and same-block intervals are
distinguished from multi-block, branch-, call-, exception-, and loop-spanning
intervals. Existing alias/mod-ref is reused; no heap SSA or new alias analysis
was introduced.

List/Array mutation, extracted-value reconstruction with `struct_set`, escape,
component escape, unknown or interface calls, exceptional regions, uncertain
aliases, collection death, and backedges block qualification. Aggregate
mutation remains an independent-value operation and is
`MUST_COPY_ELEMENT_MUTATES`; read-modify-write-back is outside this milestone.
A nested owned `struct_get` result may shorten the aggregate interval only when
current ownership evidence proves an independent owner. Unknown component
ownership fails closed. Index bounds-check timing, text, evaluation order,
panic and cleanup behavior remain untouched.

The strict readiness policy treats any intervening call as invalidating. The
API can accept summaries in order to distinguish no-access/read-only facts,
but the exact 19 were not claimed under the more permissive policy. Indirect
and interface calls remain conservative. Invoke/catch/cleanup/rethrow regions
are `MUST_COPY_EXCEPTION_LIFETIME`; exception-aware borrowing was not added.

## Design and feasibility comparison

For narrow Struct field reads, direct collection field projection is the
lowest-complexity future model: it avoids introducing a first-class borrowed
SSA aggregate and naturally competes with scalar replacement. Multiple field
reads may favor a view. Copy-elision annotations preserve value semantics more
directly but carry ownership-count and destruction-timing risk. Scalar
replacement adds split-ownership, debug, and ABI complexity. For the actual 19
String loads, extraction copy elision is a better description than an aggregate
borrow, but it first needs a dedicated owned-element proof.

The LLVM backend already obtains an element pointer before loading and needs no
collection ABI change for a future projection. It also already has an internal
`borrowed` lowering switch; this analysis never sets it. ARC calls make the
remaining ownership traffic Aether-visible, so LLVM scalarization is at best
partial and cannot independently prove removal of the retain/release contract.
Risk ranks: borrowed view high (dangling/mutation/component lifetime), copy
elision medium-high (ownership and destruction timing), scalar replacement
high (split ownership and compiler complexity).

## Decision and freeze

The exact future production threshold remains: nonescaping, read-only,
same-expression or same-block aggregate extraction; retained bounds behavior;
live collection; no component lifetime extension; no invalidating mutation,
unknown alias, call, exception edge, or backedge. The fixed 19 do not establish
that class because they are owned String extractions, so the decision is
`IMPROVE_BORROW_ANALYSIS_FIRST`, specifically by reconciling full extraction
definitions/intervals and adding owned non-Struct element semantics before any
transform is proposed.

Production remains 48 retains / 919 releases. Collection/index/value semantics,
lifecycle expansion, LocalARC, codegen, and O0/O1/O2 membership are unchanged.
No runtime or collection ABI changed, no optimization was implemented, and no
commit was created.
