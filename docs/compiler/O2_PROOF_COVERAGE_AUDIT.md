# O2.1.5 proof coverage audit

O2.2 now transforms the supported Array, Vector, and Matrix index candidates
classified `PROVEN_SAFE`. List, slicing, and non-SSA-visible general shape
checks remain transformation limitations. This analysis baseline is unchanged.

Baseline revision: `0478b475eddefa73f246590a5ecc69258ca57e29`.

The checked machine-readable baseline is
`docs/compiler/o2_proof_coverage_baseline.json`. Regenerate it with:

```sh
uv run python scripts/o2_proof_coverage.py \
  --output docs/compiler/o2_proof_coverage_baseline.json
```

## Method

The internal auditor runs after the existing O2 Initial-IR and SSA pipelines,
then reads the unmodified SSA with the O2.1 loop, range, and shape analyses. It
records each runtime check in deterministic function/block/instruction order.
`UNKNOWN` always fails closed. The auditor is not registered as an optimizer
pass or CLI command and cannot remove, replace, or fold a check.

The corpus contains the Array/List/Vector/Matrix benchmarks, simple and nested
loops, break/continue, alias/mutation examples, numerical-method and
ProbandoNR dogfood, LLVM collection examples, and one small slice probe. All 16 entries compiled;
entries which contain no relevant SSA check remain in the corpus and contribute
zero rather than silently disappearing.

## Runtime-check inventory

| Source construct | SSA instruction | Runtime behavior | O2.1 query |
|---|---|---|---|
| Array get/set | `SSAArrayGet` / `SSAArraySet` | bounds panic, zero-based | range + Array length |
| List get/set | `SSAListGet` / `SSAListSet` | bounds panic, zero-based | range + mutable List length |
| List insert/remove/pop | `SSAListInsert` / `SSAListRemoveAt` / `SSAListPop` | method bounds/empty panic | range + mutable List length |
| Vector get/set | `SSAVectorGet` / `SSAVectorSet` | bounds panic, one-based | range + vector shape |
| Matrix get/set row | `SSAMatrixGet` / `SSAMatrixSet` | matrix bounds panic, one-based | range + row shape |
| Matrix get/set column | same instruction, separate check record | matrix bounds panic, one-based | range + column shape |
| Array/List slice | `SSAArraySlice` / `SSAListSlice` | `0 <= start <= end <= length` panic | ranges + collection length |

Vector orientation, vector binary-operation length, dot/inner-product length,
matrix binary-operation shape, matrix multiplication, matrix/vector products,
outer product, and solve/left-division were inspected. In the current compiler,
their accepted dimensions/orientations are type-checking or lowering metadata;
the native backend validates compiler IR but emits no user-visible runtime
compatibility check. They are therefore compile-time-only and are not counted.
There is currently no solve/left-division SSA instruction. This is an important
zero result for the “general shape checks” domain, not missing discovery.

## Baseline results

| Domain | Total | Safe | Unsafe | Unknown | Safe % | Dominant unknown cause |
|---|---:|---:|---:|---:|---:|---|
| Array | 4 | 4 | 0 | 0 | 100% | — |
| List | 5 | 0 | 0 | 5 | 0% | unknown length (3), call invalidation (2) |
| Vector | 3 | 3 | 0 | 0 | 100% | — |
| Matrix | 6 | 6 | 0 | 0 | 100% | — |
| Slicing | 2 | 1 | 0 | 1 | 50% | mutable List length unavailable (1) |
| General shape | 0 | 0 | 0 | 0 | 0% | no runtime check is emitted |

Loop context: simple natural loops have 2/2 safe checks; the sampled nested
context has 1/2 safe; outside loops has 11/16 safe. No relevant check occurred
inside the sampled exceptional CFG. The checked JSON retains every record so
future corpora and analysis changes can be compared without scraping this text.

Array's canonical counted-loop pattern proves both `0 <= i` and
`i < length(a)`. Vector and Matrix checks backed by constructor/type shape are
also fully proven in this sample. List facts are deliberately invalidated after
mutation or a memory-writing/unknown call; no no-alias or mod/ref assumption is
made. Joins, irreducible regions, invokes, and missing relations have dedicated
reason codes, but this corpus did not produce enough such sites to quantify
them responsibly.

## LLVM correlation and relevance

The Aether LLVM printer still emits bounds helpers for SSA get/set operations;
the audit runs before and independently of clang optimization. Constant sites
may subsequently disappear at clang `-O2`, while loop-carried checks are the
more valuable Aether-side opportunity because the language analysis retains
collection length/shape relations that LLVM need not reconstruct. Machine-code
absence is not used as proof.

Opportunity ranking:

- **HIGH:** Array and Matrix checks in benchmark loops (including matrix-mul).
- **MEDIUM:** Vector indexing; sampled sites are provable but less loop-hot.
- **LOW now:** List BCE, until modest mod/ref/alias precision preserves lengths.
- **NONE now:** general shape-check elimination, because no such runtime checks
  are currently emitted.

The decision rule is domain-sensitive: proceed when there are proven-safe
checks in important loops, semantics are represented directly in SSA, and the
implementation is a local check rewrite; do not require a global percentage.
List work should wait when invalidation dominates, and shape work should wait
until a real runtime check exists.

## Recommendation

**PROCEED_TO_O2_2_BCE**

Start with Array and fixed-shape Vector/Matrix indexing. Keep List elimination
out of the first slice unless O2.2 also gains separately reviewed mod/ref
evidence. This recommendation predicts opportunity, not a speedup; no check was
removed and no benchmark performance claim is made by O2.1.5.
