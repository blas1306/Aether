# O2.8.8 — Nested aggregate ownership provenance

O2.8.8 is analysis-only. It adds component provenance to
`OwnershipEscapeAnalysis`; it changes neither lifecycle expansion, ARC
insertion, code generation, nor optimization profiles. A qualification barrier
in `LocalARCEliminator` freezes every candidate unlocked by this milestone.

## Model and transfers

Aggregate SSA identity and component ownership identity are distinct:

```
AggregateProvenance = (ComponentPath -> ComponentProvenance)*
ComponentProvenance = (Provenance, OwnershipState)
ComponentPath       = FieldIdentity+
```

`FieldIdentity(owner, name, index)` makes paths nominal and deterministic. A
path denotes a semantic component in a value, not a mutable heap address.
Exactness and ownership role are component-local.

Construction derives fields from initializers. Copy/reconstruction preserves
unaffected paths; `struct_set` replaces only its selected prefix and leaves the
source unchanged. `struct_get` strips that prefix and recovers a direct
reference root. Nested structs retain finite paths. Phi merges each path
independently: identical exact roots survive; differing roots become
`PHI_DIFFERENT_ROOTS` without poisoning other components.

`MethodResult.receiver` and `.value` are independent components and the wrapper
is not their identity. Aggregate parameters can carry symbolic
`PARAMETER:index:path` roots. Direct aggregate return component summaries remain
conservative; scalar fixed-point summaries are unchanged.

## Boundaries and complexity

- Struct fields are value components; class fields remain mutable heap content.
- A `List<Struct>` has its own collection identity. No element provenance is
  inferred, and a struct loaded from a collection has no invented facts.
- Existing interface carrier/box rules remain intact; box contents are not
  modeled.
- Exceptions, rollback, partial construction, unknown calls, and recursive
  nominal cycles stop conservatively.
- There is no heap SSA, element-sensitive collection analysis, ABI change,
  inlining, or stack promotion.

The fixed point is monotone and bounded by `instructions + 1` iterations.
Transfers visit only sparse paths present in actual structure; phi does not
enumerate component combinations. Rendering sorts by SSA value and nominal
path.

## Original 12 blockers

| Function/value | Site | Category | O2.8.8 result |
|---|---|---|---|
| `ConstructionError.message` / `this` | entry:2→5 | MethodResult component | still aggregate-unknown |
| `ServiceError.message` / `this` | entry:2→5 | MethodResult component | still aggregate-unknown |
| `OwnedError.message` / `this` | entry:2→5 | MethodResult component | still aggregate-unknown |
| `loadLedger` / `%5` | then0:4→6 | collection object with aggregate elements | semantically provable; frozen |
| `decodeLedger` / `%430` | merge90:2→5 | collection object with aggregate elements | semantically provable; frozen |
| `decodeFailure` / `%0` | entry:1→3 | collection object with aggregate elements | semantically provable; frozen |
| `requireHeaderLine` / `%54` | merge5:3→5 | collection object with aggregate elements | semantically provable; frozen |
| `transactionLabel` / `transaction` | entry:0→7 | struct parameter | still aggregate-unknown |
| `loadForCommand` / `%5` | then0:3→5 | collection object with aggregate elements | semantically provable; frozen |
| `reportLoadFailure` / `loaded` | entry:0→10 | struct parameter | still aggregate-unknown |
| `runDemo` / `%93` | merge1:56→58 | struct loaded from collection | ownership-role blocked |
| `runDemo` / `%106` | merge1:67→69 | struct loaded from collection | ownership-role blocked |

The schema-v4 audit emits the full deterministic record for each row: workload,
type, loop depth, definition, crossings, component path/type, provenance,
exactness, role, primary/secondary blockers, and class/interface/collection/
exception involvement.

## Measurements and outcome

Before: 26 candidates = 2 provable, 7 provenance, 12 nested aggregate, 4
escape, 1 normal join. After: 26 = **7 provable**, 7 provenance, 7 nested
aggregate, 4 escape, 1 normal join. The five new proofs are the exact collection
objects above. Phase 1 sees five semantic candidates and Phase 2 sees two
pre-existing candidates, but freeze/structural checks yield `would_eliminate=0`.

Coverage: 69 aggregate values; 53 ownership-bearing components; 44 exact; 9
unknown; 11 nested exact; 10 MethodResult; 0 claimed call-return or constructor
result components. Production remains **53 retains / 924 releases**.

Tests cover String/List/class components, copy/get/set, nested extraction,
same/different-root phi, symbolic parameters, MethodResult receiver/result, and
the negative collection-load boundary. Recommended next: separately audit and
activate the five frozen collection-object pairs before expanding aggregate
return summaries.

