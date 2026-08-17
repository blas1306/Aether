# O2.10 — Scalar Replacement Readiness

## Decision

**Primary: `PROCEED_TO_AGGREGATE_COPY_ELISION_INSTEAD`.**

**Second best: `IMPROVE_SCALAR_REPLACEMENT_ANALYSIS_FIRST`.** There is no real
`SAFE_SCALAR_ONLY` candidate in the frozen O2.9.8 set. All four sites are the
same ownership-bearing, ABI-visible call-result shape, and all four overlap the
copy-elision census. Ownership-aware scalar replacement would require component
lifetime scheduling that current proofs do not provide. Unknown is intentionally
preferred to widening the pass.

This milestone is analysis only. It changes no optimizer, lifecycle expansion,
ARC, struct lowering, backend, ABI, or O0/O1/O2 profile.

## Frozen real candidates

The candidate IDs sort by workload, function and numeric SSA value. The source
is the checked-in O2.9.8 `scalar_replacement_candidates` array; the new analysis
asserts that every value still exists.

| ID | workload / function | value | definition | loop | reads / destroys | escape | readiness |
|---|---|---:|---|---:|---:|---|---|
| SR-001 | `examples/expense_tracker/Main.ae` / `decodeLedger` | `%336` | `readControlLine` call in `body0:0` | 1 | 10 / 5 | NO_ESCAPE | OWNERSHIP_AWARE_REQUIRED |
| SR-002 | same | `%437` | call in `body1:0` | 1 | 7 / 23 | NO_ESCAPE | OWNERSHIP_AWARE_REQUIRED |
| SR-003 | same | `%516` | call in `body2:0` | 2 | 15 / 17 | NO_ESCAPE | OWNERSHIP_AWARE_REQUIRED |
| SR-004 | same | `%791` | call in `exit2:0` | 1 | 7 / 4 | NO_ESCAPE | OWNERSHIP_AWARE_REQUIRED |

Every value has nominal type `ControlLineResult` with fields `line: String`,
`status: LedgerStatus`, `startOffset: Int`, and `nextOffset: Int`. Exactly one
field is ownership-bearing. All four fields are read; there are no dead fields,
aggregate phis, struct sets, equality operations, stores, returns, method uses,
or non-lifecycle call uses. Releases are mutually exclusive CFG destruction
sites, not a dynamic count. Exact points, lifetimes and the component ownership
ledger are in the JSON artifact.

The primary canonical class is `REFERENCE_BEARING`; secondary properties are
`METHOD_RESULT_LIKE`, `ABI_VISIBLE_ORIGIN`, and `CALL_RESULT`. Construction is a
function return rather than `struct_new`, so exact incoming field SSA values are
unknown at the caller. Destruction releases the `String` component and cannot be
split without new lifecycle proof. The values are loop-local but not
loop-carried: `%516` is merely nested at depth two. Their replacement region is
branch-spanning. They need no reconstruction after definition because semantic
uses are field-only, but decomposition at the defining call would itself require
an ABI change or callee/result decomposition.

## Canonical model and non-goals

Scalar replacement means forwarding independent SSA components for a struct
value and omitting aggregate materialization where no observable whole-value
semantics require it. `struct_get(s, i)` can then map directly to component `i`;
`struct_set(s, i, v)` can forward all other components and replace component
`i`; and an aggregate copy can forward components. Reference component
forwarding does not elide its ownership edges.

This is not source decomposition, stack allocation, heap promotion, general
mem2reg, copy elision by itself, or a change to value semantics. Checked integer
overflow and floating-point ordering remain properties of the component
operations; scalar replacement must not expose padding or layout at an ABI
boundary.

## Observability and use rules

An aggregate is observable as a whole when it is returned or passed by value,
stored in a collection/class field, boxed into an interface, structurally
compared, hashed or printed as an aggregate, serialized, passed through FFI,
used as a full method receiver, represented as constructor/`MethodResult`
state, merged by an aggregate phi, or has an address/reference exposed. Such a
site is either a reconstruction boundary or a rejection point.

Uses are classified as `FIELD_READ`, `FIELD_WRITE`, `WHOLE_AGGREGATE_COPY`,
`WHOLE_AGGREGATE_COMPARE`, `CALL_ARGUMENT`, `RETURN`, `STORE`,
`METHOD_RECEIVER`, `PHI`, `DESTRUCTION`, or `OTHER`. A field-only candidate has
only field reads/writes after lifecycle destruction is ignored; field-dominant
means those outnumber whole uses; any other semantic use makes the whole value
observed. A first pass should accept only field-only values.

## Construction, get, set, copy, phi and loops

Direct `struct_new` offers an exact field-to-SSA mapping. Constructors, calls,
collection extraction, copies, default values, `MethodResult` components and
phis need explicit provenance. Nested field paths may be treated as one opaque
component initially; recursive flattening is deferred. Repeated gets can expose
GVN/CSE, but gets after a reconstruction need a fresh mapping.

Value-semantic `struct_set` is naturally representable by component forwarding,
and whole copies by forwarding all components. Owned components retain their
independent copy/destruction obligations. Aggregate phis could become one phi
per field only with identical predecessors and available incoming components;
exceptional and loop phis are excluded from a first pass. No frozen candidate
contains a set, copy or phi.

All 18 natural loops reported by O2.9.8 have preheaders and one latch, but these
four aggregate values do not cross a backedge. Consequently no real
field-specific induction, LICM, dead-field or BCE/range opportunity is claimed.
Repeated `status`, `startOffset` and `nextOffset` reads provide only a possible
GVN/CSE cleanup after a future decomposition.

## Calls, methods, constructors, equality and storage

The four aggregates originate at the `readControlLine` return ABI. No aggregate
is later passed, returned, stored, boxed, compared, or used as a receiver. A
first scalar-only pass must reject aggregate calls/returns, receiver use,
constructor rollback, equality, interface boxing and storage. Reconstruction
at one boundary may eventually qualify as `SAFE_WITH_RECONSTRUCTION_BOUNDARY`,
but these candidates need decomposition at their origin, not just a later
rebuild. Method receivers may additionally require `MethodResult`
reconstruction and are excluded without an ABI change.

## Ownership and ARC

Scalar-only destruction is empty. For `ControlLineResult`, destruction releases
the owned `line`. The existing component ledger records provenance, exactness,
ownership role, escape and retain/release sources; it does not prove an
independent component lifetime suitable for a transform. Scalarization therefore
has no proven ARC reduction and could add ARC if split naively. It is classified
`AETHER_NEEDED_FOR_OWNERSHIP`: LLVM may remove native insert/extract/copy
mechanics, but it cannot recover Aether's ownership obligations from an already
lowered retain/release schedule.

## Profitability and LLVM overlap

The structural proxy records constructions, gets, sets, copies, destruction
sites, field/used/dead counts, loop depth, and reconstruction boundaries. The
four sites total 4 constructions, 39 field reads, 0 sets, 0 aggregate copies,
0 dead fields and 49 CFG destruction sites. These are static sites, not runtime
speedups. Ordinary scalar mechanics may already converge under LLVM SROA;
Aether-specific value would be earlier field reasoning and ownership-aware copy
handling. No optimized LLVM claim beyond `AETHER_NEEDED_FOR_OWNERSHIP` is made.

## Coverage and copy-elision comparison

The JSON contains the deterministic representative-corpus census for
scalar-only local/non-escaping, scalar-only escaping, ownership-bearing local,
nested, ABI-visible and other aggregates. It is context, not permission to
broaden the frozen set.

The four scalar candidates and the four O2.9.8 copy-induced candidates overlap
one-for-one. Scalar replacement could conceptually subsume their component
forwarding, but ownership-aware SROA needs call-result and destruction
machinery. Copy elision targets the measured temporary copy/destruction cause
more narrowly. Scalar-only SROA has medium CFG/verifier complexity and low
ownership risk but affects zero frozen candidates; copy elision has medium
implementation complexity and risk and affects four.

## Readiness classes and future scope

`SAFE_SCALAR_ONLY` requires scalar fields, no escape, field-only uses, and no
unsupported call/return/store/equality/phi/method/constructor complexity.
`SAFE_WITH_RECONSTRUCTION_BOUNDARY` permits a small explicit rebuild set.
`OWNERSHIP_AWARE_REQUIRED` needs component ownership scheduling;
`NOT_REPLACEABLE` is dominated by whole semantics; `UNKNOWN` fails closed.

If a later census provides a real `SAFE_SCALAR_ONLY` candidate, the exact first
production hypothesis is: nominal scalar-only struct; local noescape value;
direct known field construction; field-only uses; straight-line or same-block
CFG; no phi, call, return, store, equality, method, complex constructor, nested
aggregate or reconstruction; loops only when the value is not loop-carried.
The verifier must prove complete field mapping, dominance, type equality and no
remaining aggregate use. Expected affected frozen candidates: zero.

The immediate next milestone instead is aggregate-copy-elision analysis limited
to SR-001..SR-004, preserving the call ABI and all field ownership/lifecycle
edges. Stop if it requires ABI changes, ownership splitting, heap SSA,
constructor rollback redesign, exception-aware reconstruction or general
path-sensitive aggregate state.

## Artifacts and validation contract

Reusable read-only APIs are `classify_scalar_replacement`,
`aggregate_field_uses`, `aggregate_reconstruction_boundaries`,
`scalar_replacement_region`, and `scalar_replacement_profitability`. Tests name
all fifteen required synthetic shapes and directly exercise scalar-only,
repeated-get and ownership-bearing behavior, plus the four real candidates.
The JSON is emitted with sorted keys and stable candidate order; regenerating it
must be byte-for-byte identical.

Validation covers the new tests, struct/value-semantics/backend tests,
ownership/escape/aggregate-lifetime/alias/loop/SSA/optimizer/exception/profile
tests, capability and documentation checks, `compileall`, and
`git diff --check`. Since the new module is not imported by an optimizer and no
profile or production file is changed, production behavior, ownership,
lifecycle, backend output, and O0/O1/O2 membership remain unchanged. No commit
is created.
