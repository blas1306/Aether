# O2.9.4 — String collection extraction ownership audit

Status: **complete, analysis only**. Decision:
`PROCEED_TO_OWNERSHIP_ELIDED_ARRAY_GET`.

This audit reconstructs the exact 19 O2.9.2 identities in production O2 SSA.
It changes no lowering, lifecycle rule, optimizer, runtime, ABI, or codegen.
The deterministic per-site ledger is
`o2_string_collection_extraction_audit.json`.

## Canonical ownership semantics

`string` is an immutable, reference-like value. Assignment/copy preserves the
value but creates an independent ownership edge when the destination must
outlive the source edge; retain increments and release decrements the strong
count, with destruction at zero. Immutability proves that bytes do not change,
not that a pointer remains alive. Parameters and method/interface receivers are
borrowed for the call; owned results transfer an owner. Returning, storing in a
field/collection/interface payload, or passing to a capturing/unknown callee
therefore requires an independent owner. Owned struct fields and collection
elements retain their values and release them when replaced or destroyed.

`Array<string>` is an array object plus a contiguous buffer whose inline slots
contain String references. The Array owns every stored String. Construction and
`ArraySet` acquire the new element; set releases the replaced element after a
successful bounds check. Array destruction walks the elements in reverse and
releases each before freeing storage. Fixed length stabilizes addresses, but
does not stabilize element lifetime.

Ordinary `ArrayGet<string>` has source-level value semantics and returns an
owned String. Initial IR emits `array_get` with `borrowed=false`. Lifecycle
marks its managed result owned and inserts its eventual release. SSA preserves
the flag and release. LLVM performs the existing bounds check when
`bounds_checked=true`, computes the element address, loads the pointer, and
calls String retain. The lifecycle release closes precisely that extracted
owner. It is not the Array's final element release.

## Representative end-to-end trace

For `string x = arr[i]`, lowering evaluates `arr` and `i`, then emits an
`IRArrayGet(x, arr, i, borrowed=false)`. Lifecycle expands this to the get plus
an `__aether_release(x)` at the last owned use/scope exit (and preserves cleanup
on exits). SSA renames the values without changing ownership. LLVM emits:

1. the retained or BCE-eliminated bounds check, without moving panic timing;
2. header/data addressing and a pointer-sized slot load;
3. `__aether_retain` for the independent extracted owner;
4. uses of that pointer;
5. the lifecycle `__aether_release`.

There is no byte copy and no second String object. The retain/release represent
the local extraction owner; the Array continues to own its slot separately.
If `x` survives element replacement, alias mutation, Array destruction or
reassignment, that owner is required. If the sole use is immediate while the
exact Array and slot owner stay live, materializing it is lowering traffic.

## Exact 19-site reconciliation

All sites are in `examples/expense_tracker/Main.ae`, function `decodeLedger`;
all are inside loops, have one use, do not escape, cross no mutation, exception
edge or backedge, and use loop-invariant Array SSA roots. Five are at loop depth
1 and fourteen at depth 2. Each currently costs exactly one ArrayGet retain and
one lifecycle release per execution. The JSON ledger records, for every site,
workload/function/block/depth, exact Array root, index and String SSA values,
bounds status, first/last use, calls, escape, mutation, ownership requirement,
ARC alternatives and ranking.

| Category | Sites | Shape |
|---|---:|---|
| `DIRECT_PROJECTION_CANDIDATE` | 15 | immediate String comparison |
| `IMMEDIATE_BORROW_CANDIDATE` | 3 | byte length or `parseInt` call |
| `STABLE_REGION_BORROW_CANDIDATE` | 1 | constants then `text.byteSlice` |
| owned/escape/unknown categories | 0 | none in the fixed set |

The 15 comparisons are the smallest, highest-confidence class and dominate the
depth-2 sites. The three immediate calls are next; their known helper contracts
borrow String arguments and return independent results. The one stable-region
case remains same-block and mutation-free but is deliberately ranked last.
There are no local-variable, escaping, or owner-required cases among these 19;
the audit tests those shapes independently and they remain owned when lifetime
independence is needed.

## Invalidation and calls

A borrow is invalid after same-element `ArraySet`; a different-element set is
safe only when exact Array identity and unequal indices are proven. Unknown
index equality, Array reassignment/destruction, and MUST/MAY alias mutation
invalidate conservatively. `NO_ALIAS` mutation does not. Immutability changes
none of those lifetime rules. Known printing, comparison, byte-length,
byte-slice and parse helpers borrow arguments for the call. A callee that
retains establishes its own edge; one that stores, an indirect/interface call,
or an unknown summary blocks the candidate. Exceptional cleanup cannot depend
on a borrow surviving its owner.

Four of the sites retain bounds checks and three have BCE-proven checks removed;
the ledger contains the exact value for all 19. Ownership qualification must
neither remove nor move a check and must preserve panic and cleanup timing.

## Model choice and feasibility

| Model | Assessment |
|---|---|
| General `Borrowed<string>` SSA | Broad reuse, but unnecessary new ownership/verifier complexity |
| Specialized element projection | Natural for comparisons, but creates a second operation/model |
| Ownership-elided `ArrayGet` | Smallest: reuse existing `borrowed` flag, verifier and LLVM load path |

Aether already models borrowed Array/List elements for `for` iteration; IR and
SSA verifiers reject their escape or mutation, lifecycle does not own them, and
LLVM suppresses the retain. Parameters, struct projections, catch payloads,
interface receivers and runtime helpers also use borrowed conventions. Thus an
ownership-elided get reuses machinery and needs no runtime/collection ABI
change. The backend already computes the same pointer and load. LLVM can erase
pointer temporaries (`LLVM_PARTIAL`) but cannot remove opaque ARC calls while
reconstructing Aether's owner proof; all 19 are `AETHER_NEEDED`.

## ARC correction, predicate, and decision

O2.9.3's ceiling of 19 releases is verified: each is destruction of an owned
extraction temporary, not an initial or container owner. The complete paired
ceiling is therefore **19 retains and 19 releases**. No final Array-owned
element release is counted or removable. Structurally, every site qualifies;
this is a theoretical future reduction, not a production change.

The minimum future predicate is: exact `Array<string>` identity; Array alive
through the sole/non-escaping use; no required independent local owner; exact
slot not replaced; no unknown-index or alias mutation; no Array destruction or
reassignment; known borrowing callees only; no escape, exception-lifetime
dependency or backedge-spanning borrow; existing bounds-check position; and
borrow-verifier acceptance. Existing alias/mod-ref, ownership/escape and loop
analyses must supply those facts. `UNKNOWN` remains owned.

The smallest useful implementation would annotate already-proven ArrayGet
sites as borrowed, so the decision is `PROCEED_TO_OWNERSHIP_ELIDED_ARRAY_GET`.
Production remains **48 retains / 919 releases**. No production optimization,
String/Array behavior, lifecycle, LocalARC, O0/O1/O2 membership, runtime ABI or
code generation changed in this milestone.

## O2.9.5 follow-up

The frozen 15 direct projections are now implemented by the O2-only
`OwnershipElidedArrayGet` pass. See `O2_OWNERSHIP_ELIDED_ARRAY_STRING_GET.md`.
This section does not alter the historical O2.9.4 measurements above.
