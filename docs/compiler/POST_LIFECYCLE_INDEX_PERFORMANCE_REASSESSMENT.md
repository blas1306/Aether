# TEST-PERF-3.3 — Post lifecycle-index performance reassessment

Date: 2026-08-20

## Result

The fresh 26-workload/78-profile regeneration completed in **8.684 s wall
clock**. Its measured compiler work was **8.121 s pre-LLVM** plus **0.428 s
LLVM emission**; the remaining **0.135 s** is audit/harness overhead. These are
new measurements, not values obtained by subtracting historical profiles.

The lifecycle pathology is structurally gone. A focused, newly lowered
`expense_tracker/Main.ae` module made **17,709 queries**, built **26 indexes**
for **26 functions**, and therefore performed **26 full discovery scans**, in
**0.050 s** of Initial IR verification. Across all verifier invocations in the
regeneration there were 92,627 queries and 435 index builds/scans. The former
17,709 full rescans cannot occur through the indexed predicate.

Decision: **FURTHER_OPTIMIZATION_NOT_COST_EFFECTIVE**.

## Fresh stage profile

The manifest contains 30 entries; the same four native-unsupported programs as
TEST-PERF-3.1 failed closed, leaving 26 workloads and 78 O0/O1/O2 records.

| Stage | Seconds | Wall % |
| --- | ---: | ---: |
| frontend / parsing / type analysis | 0.199 | 2.29% |
| Initial IR construction | 0.244 | 2.80% |
| Initial IR verification (including post-IR verification) | 0.344 | 3.96% |
| lifecycle / ownership processing | 0.139 | 1.60% |
| SSA construction | 0.374 | 4.30% |
| SSA verification | 1.996 | 22.98% |
| optimization, excluding embedded verification | 4.827 | 55.58% |
| `LLVMBackend.emit` | 0.428 | 4.93% |
| audit / test harness overhead | 0.135 | 1.55% |
| **total wall** | **8.684** | **100.00%** |

Profile totals were O0 0.675 s, O1 1.380 s, and O2 6.494 s. The backend is no
longer a five-second component on this run: all 78 emissions took 0.428 s.
Optimization is now the largest category, but that is expected work and no
individual pass or workload exhibited evidence of a size-dependent
superlinear cliff. In particular, the diagnostic evidence does not justify a
new optimization merely from its percentage after removal of the old hotspot.

## Expense tracker reassessment

The source has 9,273 characters and lowers to 26 functions, 475 blocks and
4,203 Initial IR instructions. Base SSA contains 3,028 instructions at O0 and
3,016 at O1/O2; final O2 SSA contains 2,988 instructions.

| Expense tracker stage | O0 | O1 | O2 |
| --- | ---: | ---: | ---: |
| frontend share | 0.034 s | 0.034 s | 0.034 s |
| Initial IR construction | 0.041 s | 0.042 s | 0.042 s |
| initial + post-IR verification | 0.051 s | 0.096 s | 0.098 s |
| lifecycle expansion | 0 | 0.037 s | 0.040 s |
| SSA construction | 0.110 s | 0.069 s | 0.070 s |
| optimization (inclusive pipeline timing) | 0.035 s | 0.452 s | 5.265 s |
| LLVM emission | 0.092 s | 0.091 s | 0.093 s |
| total | 0.434 s | 0.892 s | 5.712 s |

The program remains the largest workload and consequently contributes most of
O2 optimization time, but verification and emission now scale with its much
larger IR/SSA rather than with query count multiplied by IR size. The previous
workload-specific-pathology classification is retired.

## Repeated-prefix and mutation audit

Frontend preparation is already performed once per workload by this audit.
`source -> typed representation` therefore costs 0.199 s in total and has zero
O0/O1/O2 duplication in the measured driver. `typed representation -> Initial
IR` plus first verification is the repeated 0.458 s reported below. The raw
`SSA construction` total is 0.374 s, but it is not a profile-independent prefix
because profile-specific IR work precedes it.
Across the three profiles, repeated Initial IR lowering plus its first
verification cost 0.458 s. Keeping one such result per workload gives a
**0.309 s theoretical upper bound**; allowing for ownership, lookup and copying
costs, the deliberately generous realistically recoverable estimate is
**0.232 s** (2.7% of this regeneration).

The broader phrase “Initial IR to base SSA” is not a common immutable prefix in
the current pipeline. O1 and O2 perform lifecycle expansion and profile-driven
IR optimization before SSA construction, while O0 does not. IR and SSA passes
return rewritten modules and iterative pipelines feed each result into the
next pass. Verification attaches state only to verifier instances, not the
module, but that does not make optimizer inputs safely shareable. Sharing
would therefore require proving every selected pass non-mutating or cloning an
IR/SSA graph at each branch; cloning would consume part of the 0.309 s ceiling
and add ownership and invalidation complexity. As a scale check, ten local
`deepcopy` trials of the expense-tracker graphs averaged 0.031 s for Initial IR
and 0.025 s for base SSA (ranges 0.028–0.052 s and 0.022–0.046 s). Even before
bookkeeping, a few such copies consume a material fraction of the recoverable
budget. Profile-specific lowering begins
before base SSA exists. The maximum available saving is too small to justify
that work.

## Full-suite projection and validation scope

The full suite was not run, so no exact runtime is claimed. TEST-PERF-1's
inventory observed 80 unique SSA builds and 85 cache hits; TEST-PERF-3.3 does
not change either count. A naïve comparison of the historical 129.61 s O2.13
dominant regeneration with this instrumented 8.684 s run suggests that the
O2.13 family can recover on the order of two minutes, but they are differently
instrumented benchmarks and that delta must not be treated as an exact suite
projection. Prefix sharing itself could recover at most about 0.31 s per full
78-record regeneration, so its expected suite impact is immaterial.

The machine-readable evidence, including all per-workload records, is in
[`post_lifecycle_index_performance_reassessment.json`](post_lifecycle_index_performance_reassessment.json).
