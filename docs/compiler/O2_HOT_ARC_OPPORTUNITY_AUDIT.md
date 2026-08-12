# O2.9.1 — Hot ARC opportunity audit

Status: **complete, analysis only**. Final recommendation:
`PROCEED_TO_AGGREGATE_LIFETIME_ANALYSIS`. No ARC insertion/elimination,
ownership rule, pass profile, or code generation changed. The complete
967-operation census and all 66 loop records are in
`o2_hot_arc_opportunity_audit.json`; reproduce it with
`python scripts/o2_hot_arc_opportunity_audit.py --output docs/compiler/o2_hot_arc_opportunity_audit.json`.

## Method and definitions

The script observes lifecycle-expanded SSA produced by the real O2 pipeline.
It does not run a rewrite. Two unsupported legacy numerical examples are
reported as corpus failures, as in earlier audits. The successful corpus
exactly reproduces the O2.8.9 baseline.

`STRUCTURAL_HOTNESS` is an estimate, not profiling:
`max(1, 1 + 2*natural_loop_depth - conditional + real_workload - test_only)`.
Conditional means outside the header/latch. All measured counts are `null`;
instrumentation was skipped because it would require invasive codegen work.
Entries are tagged `REAL_WORKLOAD`, `SYNTHETIC_PROBE`, or `TEST_ONLY`.

Loop roles have these precise meanings: `PER_ITERATION_LOCAL` is created and
consumed within an iteration; `LOOP_CARRIED_OWNER` survives a backedge;
`LOOP_INVARIANT_IDENTITY` is defined outside the loop (without implying an
invariant ownership edge); `LOOP_VARIANT_IDENTITY` changes in the loop;
`CONTAINER_ELEMENT_OWNERSHIP` is collection/extracted-element lifecycle;
`AGGREGATE_TEMPORARY` is struct/wrapper lifecycle;
`CALL_BOUNDARY_OWNERSHIP` crosses a call; `EXCEPTION_LIFETIME` depends on an
exceptional edge; `DESTRUCTION_ONLY` is a final release without explicit
retain; `UNKNOWN_LOOP_ROLE` declines unsupported inference.

`BALANCED_PER_ITERATION` requires a same-loop dominating retain and
postdominating release without a backedge. `BALANCED_ACROSS_MULTIPLE_ITERATIONS`
crosses one; `BALANCED_ONLY_AT_LOOP_EXIT` leaves the loop;
`PATH_DEPENDENT_BALANCE` lacks postdominance; otherwise it is
`UNKNOWN_BALANCE`. A common provenance root alone never creates a pair.

## Baseline and distributions

| Census | Retains | Releases | Total |
|---|---:|---:|---:|
| All O2 | 48 | 919 | 967 |
| Natural loops | 11 | 55 | 66 |
| Outside loops | 37 | 864 | 901 |

ARC occurs in 34 functions. Loop ARC occurs in two functions of one real
workload: expense-tracker `decodeLedger` (54 sites) and `encodeLedger` (12).

| Type | All | Loop |
|---|---:|---:|
| Struct/aggregate | 409 | 5 |
| String | 240 | 57 |
| Array | 218 | 3 |
| List | 89 | 1 |
| Class | 8 | 0 |
| Interface | 3 | 0 |

No Vector/Matrix loop ARC occurs. Interface ARC is cold and too small to
justify interface work.

## Release asymmetry and lifecycle source

Only 21/919 releases match an explicit retained edge. The release census is
623 lifecycle-generated result/owner destructions, 185 initial-owner
destructions, 76 collection-element destructions, 21 matching explicit
retains, six return/MethodResult cleanups, six temporary destructions, and two
aggregate-field destructions. Thus 48/919 is expected consumption of initial
ownership, not evidence of missing retains. Pair elimination cannot remove
those releases alone.

## Complete loop classification

All 11 loop retains are Strings:

| Function | Sites | Count | Role | Blocker | Balance |
|---|---|---:|---|---|---|
| `decodeLedger` | `merge50:4,6,8` | 3 | per-iteration local | no pair | unknown |
| `decodeLedger` | `merge75:0`, `merge77:0` | 2 | call boundary | provenance | loop exit |
| `decodeLedger` | `merge79:0` | 1 | call boundary | provenance | across iterations |
| `decodeLedger` | `merge87:0,1,2` | 3 | loop variant | provenance | per iteration |
| `encodeLedger` | `merge5:1` | 1 | per-iteration local | escape | per iteration |
| `encodeLedger` | `then6:1` | 1 | per-iteration local | no pair | unknown |

All 55 releases are enumerated in JSON: 27 collection-element destructions,
17 lifecycle-generated releases, six temporary destructions, and five paired
releases. Across both kinds, roles are 27 container-element, 11 call-boundary,
10 loop-variant, eight destruction-only, five aggregate-temporary, and five
per-iteration-local sites.

Seven canonical candidates touch loops: three balance per iteration, one is
path-dependent, one balances across iterations, and two only after leaving the
retain's loop. Six are provenance blocked and one escape blocked. None is
currently eligible. No speculative pair was formed.

## Identity, collections, allocations, and blockers

No loop retain proves the same invariant ownership edge on every iteration.
Stable SSA/object identity is distinct from stable ownership: calls, escape,
phis, and fresh-owner creation remain relevant. Retain hoisting/release sinking
is therefore not proposed.

Collection/aggregate lifecycle groups 32/66 loop operations. The dominant
mechanism is Array element extraction followed by temporary/nested String
destruction, not ownership of the Array/List object. There are eight fresh
loop destructions; stack promotion or ARC elision requires a later escape and
lifetime proof. Exact escape/provenance reasons, alias/mod-ref buckets, and
exception adjacency are recorded per site in JSON. Hot provenance loss is
concentrated in call results and phi/collection transport. Exception and
interface traffic is not meaningfully hot.

## Top ranked sites

All top ten are real expense-tracker sites in a depth-two loop.

| # | Site | Kind/type and role | Hotness | Blocker / family |
|---:|---|---|---:|---|
| 1 | `decodeLedger merge61:14` | release String, call | 6 | provenance |
| 2 | `decodeLedger merge61:15` | release Array, destruction | 6 | initial owner |
| 3 | `decodeLedger merge61:16` | release Struct, temporary | 6 | aggregate lifetime |
| 4 | `decodeLedger else61:4` | release String element | 5 | aggregate lifetime |
| 5 | `decodeLedger else65:4` | release String element | 5 | aggregate lifetime |
| 6 | `decodeLedger else69:4` | release String element | 5 | aggregate lifetime |
| 7 | `decodeLedger else74:4` | release String element | 5 | aggregate lifetime |
| 8 | `decodeLedger else76:4` | release String element | 5 | aggregate lifetime |
| 9 | `decodeLedger logic.rhs52:4` | release String element | 5 | aggregate lifetime |
| 10 | `decodeLedger logic.rhs53:3` | release String element | 5 | aggregate lifetime |

ARC runtime calls are `AETHER_UNIQUE`; aggregate lowering is `LLVM_PARTIAL`.
LLVM may simplify exposed aggregates but cannot infer Aether nested ownership.

## Decision matrix and non-ARC comparison

| Family | Dynamic relevance | Hot coverage | Effort/risk | LLVM | Enabling value |
|---|---|---|---|---|---|
| Aggregate lifetime analysis | high | 32 loop sites | high/high | partial | high |
| Provenance improvement | medium | 5 grouped sites | medium/high | unique | medium |
| Escape improvement | medium | 21 grouped sites | high/high | unique | high |
| Local/loop pair elimination | low | 0 eligible | high/high | unique | low now |
| Memory LICM | high | non-ARC reads/checks | high/medium | partial | high |
| GVN/CSE | medium | non-ARC | high/medium | converges | medium |
| General loop optimization | high | broad loops | medium-high/medium | partial | high |

JSON preserves, without an unexplained combined score, static and loop counts,
hotness coverage, dependency analyses, complexity, risk, LLVM overlap, and
real/synthetic distribution for each populated family.

## Recommendation

**`PROCEED_TO_AGGREGATE_LIFETIME_ANALYSIS`**. The basis is dynamic structure,
not the largest static blocker: 32/66 loop operations and most top-ranked sites
are collection-element or aggregate-temporary lifecycle, whereas only five
loop releases match loop retains and no pair is eligible. Local pair,
interface, or exception-aware work would miss the dominant repeated cost. A
bounded next audit should prove element-copy/nested-field temporary lifetimes,
and stop if that requires heap SSA, path-sensitive ownership, new exception
semantics, or changed lifecycle rules.

## O2.9.2 follow-up

Aggregate lifetime analysis now reconciles all 32 sites as 19 extraction
temporaries, four copy-induced results, and nine escape-required conservative
sites. The superseding recommendation is
`PROCEED_TO_COLLECTION_EXTRACTION_BORROW_ANALYSIS`; see
`O2_AGGREGATE_LIFETIME_ANALYSIS.md`. Historical O2.9.1 evidence above remains
unchanged.
