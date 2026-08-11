# O2.8.9 — Qualified nested-aggregate ARC

O2.8.9 replaces the O2.8.8 blanket `List<Struct>`/`Array<Struct>` LocalARC
barrier with one fail-closed ownership-transfer predicate. It does not infer
element identity. The proven identity is the collection object, and the exact
aggregate component path is the destination struct field.

## Frozen candidate census

All five candidates are same-block, loop-depth zero, exact fresh owned
`List<Transaction>` roots. The retain dominates the field construction and the
release; the release post-dominates the retain. Each interval has one normal
path, no branch, join, phi, call, store, exception edge, backedge, or use after
the release. Four intervals contain only `struct_new`; `decodeLedger` also
contains one release of a proven-disjoint exact root.

| Candidate ID | Function | Value/root | Aggregate component | Retain → release | Classification |
|---|---|---|---|---|---|
| `O2.8.9-0fe4ecee97801ace` | `decodeFailure` | `%0` / `fresh:0` | `LedgerDecodeResult.transactions#0` | `entry:1` → `entry:3` | `PHASE1_SAME_BLOCK` |
| `O2.8.9-cfb2ee2dbfb4e5ab` | `requireHeaderLine` | `%54` / `fresh:54` | `LedgerDecodeResult.transactions#0` | `merge5:3` → `merge5:5` | `PHASE1_SAME_BLOCK` |
| `O2.8.9-35a43942d4be3ea0` | `decodeLedger` | `%430` / `fresh:430` | `LedgerDecodeResult.transactions#0` | `merge90:2` → `merge90:5` | `REQUIRES_AGGREGATE_EXTENSION` |
| `O2.8.9-8d1044436c6547ed` | `loadLedger` | `%5` / `fresh:5` | `LedgerLoadResult.transactions#0` | `then0:4` → `then0:6` | `PHASE1_SAME_BLOCK` |
| `O2.8.9-414e920be1713e5f` | `loadForCommand` | `%5` / `fresh:5` | `LedgerLoadResult.transactions#0` | `then0:3` → `then0:5` | `PHASE1_SAME_BLOCK` |

The IDs are deterministic audit identifiers derived from function, locations,
component path and exact root. They are not consulted by production
qualification.

## Ownership proof

The lifecycle expansion represents a copy into an owned struct field as
`retain(source); struct_new(... source ...); release(source)`. When the source
owner is dead after that release, deleting the pair changes this copy followed
by destruction into an ownership transfer. The destination field keeps the
original single edge, and its eventual aggregate destruction still consumes
that edge exactly once. List storage and each `Transaction` component are not
part of this proof.

Qualification requires all of the following:

- a fresh, exact, single, owned `List<Struct>` or `Array<Struct>` root;
- one same-block `struct_new` field use between retain and release;
- exact equality between that field's component provenance and the ARC operand;
- no source use after release, including successor blocks;
- no loop/backedge, call, store, exception, reconstruction, interface,
  MethodResult, or ambiguous provenance;
- at most a release of another exact, root-disjoint value in the interval.

Thus four candidates reuse Phase 1. The fifth uses only the narrow disjoint
release allowance. Phase 2 qualifies zero candidates. The two historical
branch-heavy semantic candidates remain rejected.

## Traffic

The production corpus changes from **53 retains / 924 releases** to **48 / 919**,
exactly one operation of each kind for every accepted pair. Loop traffic stays
**11 retains / 55 releases**; none of the five pairs is in a loop.

Each removal is exposed through `SSAOptimizationResult.transformation_log`
with its candidate ID, function, component path, exact root, locations, route,
and ownership proof.

## Validation

Focused LocalARC, aggregate-provenance, audit and optimizer tests pass (125
tests). An O2 native probe with `List<Struct>` elements containing both String
and List fields produced the expected output under ASan/UBSan with no UAF,
double-free or undefined behavior. Standalone LSan reports 76 bytes in the
element's nested fields; the identical O1 control reports the same allocations
and byte count, so this is recorded as a pre-existing nested-element lifecycle
leak rather than attributed to O2.8.9. The ARC traffic delta itself is exactly
the five qualified pairs described above.
