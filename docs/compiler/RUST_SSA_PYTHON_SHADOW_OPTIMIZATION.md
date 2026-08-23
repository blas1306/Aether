# Python shadow performance optimization — RUST-3.11

Decision: `RUST_SSA_PYTHON_SHADOW_OPTIMIZED`

Baseline revision: `55dc4c5b12c6312fa8c1d143b964691c38c3c1de`.

## Outcome

The mandatory synchronous `GeneralSSABuilder` shadow remains exact and fail-closed, but deep-CFG Python latency no longer scales through millions of Python `set` entries. At 5,000 blocks, Python-shadow median fell from 6.578 s to 0.362 s (18.19×), dual-lane median fell from 10.324 s to 1.034 s (9.98×), and fresh-process peak RSS fell from 1,375,420 KiB to 93,604 KiB (14.69×). The formerly impractical 10,000-block case now completes at 0.805 s Python-only and 2.442 s dual-lane median.

Ordinary-workload improvement is intentionally modest: the eight-workload aggregate Python median improved from 0.12135 s to 0.11517 s (1.054×), while dual-lane moved from 0.48249 s to 0.48106 s (1.003×, effectively neutral at local-noise scale). The optimization targets deep CFG scaling and does not claim an ordinary total-pipeline breakthrough.

## Audit and dependency map

The audit was completed before implementation. The detailed machine-readable map is in `rust_ssa_python_shadow_optimization.json`; its dependency chain is:

1. lifecycle normalization;
2. CFG construction;
3. reachability;
4. full-set dominator fixed point;
5. immediate-dominator derivation;
6. dominator tree;
7. dominance frontiers;
8. liveness;
9. definite initialization;
10. phi placement;
11. iterative renaming;
12. result assembly;
13. builder verification.

Before RUST-3.11, dominance used block-name strings and a `set[str]` for every block's full dominator relation. A linear 5,000-block CFG contains 12,502,500 dominance memberships: pointer payload alone is a 100,020,000-byte lower bound, excluding Python set tables, strings, temporary intersections, and the verifier's independent analysis. Immediate-dominator derivation then enumerated all strict dominators again. `cProfile` at 1,000 blocks showed two dominance computations—the builder and its required verifier—not a duplicate verification of one unchanged object.

Ordinary code was dominated by lifecycle normalization and builder verification both before and after. On the realistic-medium fixture, definite initialization and renaming were the next substantial lowering phases. Deep CFG was dominated before by full-set dominance/idom in lowering and verification; after optimization the largest phases are lifecycle normalization and verification, followed by renaming.

## Implemented changes

Each implemented change was classified before coding:

| Change | Classification |
|---|---|
| Compilation-local, source-order integer block indexes | `REPRESENTATION_ONLY` |
| Python integer bit masks for the existing full-set equations | `DATA_STRUCTURE_ONLY` |
| Depth-mask idom derivation from full dominator cardinality | `PYTHON_ALGORITHM_INDEPENDENT` |
| Reuse Python reachability in frontier construction | `TRAVERSAL_OPTIMIZATION` |
| Immutable frontier/tree-child views for internal consumers | `DATA_STRUCTURE_ONLY` |
| Opt-in detailed phase timing | `REPRESENTATION_ONLY` |

External queries and SSA continue to use block names. Integer identity is local to one Python computation and cannot leak into schemas, names, predecessor labels, or canonical output. The production path performs no timing calls unless instrumentation is explicitly supplied.

The bit-mask implementation is not CHK. It preserves the original Python monotone full-dominator-set fixed point, with intersection expressed as integer `&`. Immediate dominators are independently derived from the mathematical property that a node with depth `d` has an immediate dominator at depth `d-1`; depth masks locate that candidate without enumerating the complete strict-dominator set.

## Phase result

One instrumented 1,000-block deep run illustrates attribution (seconds; single diagnostic run, separate from repeated wall medians):

| Phase | Before | After |
|---|---:|---:|
| Dominator fixed point | 0.03121 | 0.00107 |
| Immediate-dominator derivation | 0.05426 | 0.00082 |
| Dominator tree | 0.00428 | 0.00088 |
| Dominance frontier | 0.00450 | 0.00102 |
| Builder verification (includes its own dominance) | 0.11652 | 0.02834 |
| Renaming | 0.01252 | 0.01241 |
| Definite initialization | 0.00218 | 0.00299 |

The new bottleneck is no longer dominance. Deep shadow work is led by lifecycle normalization and verification, then renaming. On ordinary multi-slot programs, definite initialization remains material and is a future evidence-driven candidate.

## Repeated performance results

All results used two warmups. Deep CFG used seven measured rounds; ordinary workloads used fifteen. Raw samples, min/max, environment, and phase profiles are in the JSON evidence.

| Blocks | Python before | Python after | Speedup | Rust-only diagnostic before | After | Speedup | Dual before | Dual after | Speedup |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 100 | 0.00718 | 0.00561 | 1.28× | 0.01039 | 0.00918 | 1.13× | 0.01954 | 0.01775 | 1.10× |
| 1,000 | 0.23562 | 0.05792 | 4.07× | 0.17176 | 0.08555 | 2.01× | 0.44498 | 0.16456 | 2.70× |
| 5,000 | 6.57848 | 0.36171 | 18.19× | 3.58053 | 0.51853 | 6.91× | 10.32406 | 1.03426 | 9.98× |
| 10,000 | impractical | 0.80519 | — | impractical | 1.15221 | — | impractical | 2.44200 | — |

“Rust-only diagnostic” still performs required Python-side verification of imported Rust SSA; it is not a claim that Rust code itself changed. Its deep improvement comes from the Python verifier using the compact independent dominance analysis. No Rust implementation was optimized in this milestone.

## Differential and independence qualification

`ReferenceDominatorAnalysis` freezes the pre-RUST-3.11 set equations and result representation as a qualification-only path. Fixed seeds 3, 11, 29, 47, and 101 compare reachable blocks, complete dominator sets, idom, tree children, and frontiers on reproducible CFGs containing loops, joins, and unreachable regions. Phi-focused, loop, unreachable, and deep-linear builders require exact schema-v2 SSA DTO equality between reference and optimized analysis.

The Python implementation imports no Rust dominance/SSA internals, starts no Rust process, uses no FFI, and consumes no Rust-derived reachability, idom, frontier, liveness, or phi information. Rust uses CHK; Python uses full-set dataflow. A representation/indexing defect could still exist independently, but the central convergence and idom bug classes differ, so the shadow retains meaningful oracle diversity.

The following alternatives were rejected:

- Porting CHK to Python or consuming Rust analysis: would reduce oracle independence.
- Removing builder verification: crosses a required safety boundary; it is not duplicate verification of the same unchanged Python SSA object.
- Sampling or skipping large shadows: forbidden and unnecessary after this change.
- Rewriting liveness and definite initialization now: insufficient evidence for the added semantic risk; the targeted deep-CFG win is already proven.

## Correctness and policy closure

Qualification results are recorded in the JSON artifact and enforced by `scripts/check_rust_ssa_python_shadow_optimization.py`. Local Linux qualification is the initial platform result; the normal official CI matrix remains required for release closure.

Rust remains authoritative in `RUST_SSA_AUTHORITY_PYTHON_SHADOW`. The Python shadow remains mandatory and synchronous. Any Python failure or semantic mismatch remains fail-closed. Source locations, `bounds_checked`, lifecycle, ownership, phi values and predecessor labels, deterministic naming, schemas (Initial IR v1, SSA v2, protocol v1), optimizer/backend behavior, and rollback modes are unchanged. Python does not consume Rust analysis. No commit was created.
