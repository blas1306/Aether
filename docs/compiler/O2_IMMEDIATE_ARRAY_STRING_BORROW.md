# O2.9.7 — Immediate `Array<String>` Borrow Qualification

O2 extends `OwnershipElidedArrayGet` with a narrow immediate-consumer mode. An
owned `ArrayGet<String>` becomes verifier-visible borrowed storage only when its
sole semantic use is the next SSA instruction, that argument has an explicit
borrowed contract, the operations share a loop block, existing analysis proves
no escape, mutation/alias, exception, or backedge hazard, and the matching
release follows the consumer. Bounds checks are unchanged.

The canonical tri-state query is `consumer_accepts_borrowed_arg`. Its trusted
registry records no-retain, no-store, no-transfer, result relation, and
throw/panic behavior for String byte length, `parseInt`, and `parseDouble`.
Unknown/direct Aether, indirect, interface, throwing, multi-use, non-adjacent,
and ownership-consuming uses fail closed. O2.9.5 comparisons keep their
existing qualification path.

## Frozen candidates

| ID | workload/function | root/index/result | consumer | depth | result |
|---|---|---|---|---:|---|
| `IAB-001` | `examples/expense_tracker/Main.ae` / `decodeLedger` | `%357` / `%364` / `%365` | `byteLength` | 1 | qualified |
| `IAB-002` | same | `%451` / `%483` / `%484` | `parseInt` | 1 | qualified |
| `IAB-003` | same | `%530` / `%586` / `%587` | `parseInt` | 2 | qualified |

O2.9.6 proved for each: one consumer, Array lifetime coverage, no intervening
call or element/alias mutation, no escape, and no exceptional region. Each
pre-O2.9.7 site costs one backend-implicit retain and one explicit SSA release.
The stable `%373` site (root `%357`, index `%372`) is non-adjacent and remains
owned.

For three transformations the baseline changes from 48/904 to 48/901 explicit
SSA retains/releases and from 72 to 69 backend-implicit retains. All are loop
sites: loop SSA changes from 11/40 to 11/37 and implicit loop retains from 14 to
11. The backend retain and SSA cleanup are intentionally counted separately.
LLVM lacks the Array ownership fact, so the overlap class is `AETHER_UNIQUE`.

O0/O1, LocalARC, source ownership, Array/String ABI, stable-region borrowing,
and the 15 O2.9.5 direct projections are unchanged.

## Audit layering

The committed O2.9.1, O2.9.2, and O2.9.6 JSON files are immutable historical
snapshots. Their tests validate schema, canonical JSON, and the freeze that was
true at that milestone; they are not regenerated with today's production
pipeline. Current production is recorded separately in
`o2_immediate_array_string_borrow.json` and checked against live O2 output.

Repeated current generation places `%365` in `logic.rhs37` and the stable
`%373` in `logic.rhs38`. The apparent `logic.rhs37 -> logic.rhs38` movement is
the deterministic consequence of comparing snapshots from different pipeline
states, not same-state nondeterminism. Same-state regeneration and the exact
site regression produce the same block names.
