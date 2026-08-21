# TEST-PERF-3.1 — Pre-LLVM IR/SSA materialization performance profile

## Decision

The dominant classifications are:

    INITIAL_IR_VERIFICATION_DOMINATES
    PROFILE_INDEPENDENT_WORK_REPEATED
    WORKLOAD_SPECIFIC_PRE_LLVM_PATHOLOGY

Python Initial IR verification, not LLVM generation, consumes the missing time.
The pathology is concentrated in `examples/expense_tracker/Main.ae`. O2 also has
a secondary SSA ownership/ARC cost, so the detailed result is
`MULTIPLE_PRE_LLVM_COST_CENTERS`, with one overwhelmingly dominant center.

This milestone changes no compiler, verifier, optimizer, lifecycle, ownership,
backend, cache, or ABI behavior. Timings are observational and are never test
assertions.

## Actual path and cache boundary

The profiled native evidence path is:

    source load -> parse/AST -> type check/import resolution
      -> Initial IR lower -> Python IR verify
      -> [O1/O2: lifecycle expand -> IR optimize -> Python IR verify]
      -> SSA build -> Python SSA verify
      -> profile SSA pipeline (input/pass verification enabled)
      -> final Python SSA verify -> LLVMBackend.emit

The Rust authority verifier is not invoked on this path. There is no DTO or JSON
roundtrip, `deepcopy`, or defensive serialization in the measured materializer.
Optimizer passes return immutable reconstructed modules, but reconstruction is
not the dominant measured center.

TEST-PERF-1's exact boundary is
`aether.o2_evidence_materialization._materialize`: the cached value is final,
optimized and verified SSA, keyed by source contents, canonical path, and the
complete frozen optimization profile. Cache lookup itself requires no parse,
type check, IR, SSA, serialization, or expensive representation key. A direct
hit therefore repeats none of those operations. However, O2.13 callers can and
do prepare typed programs independently before making other evidence requests,
and `LLVMBuilder.emit_llvm` does not use that cache. O0/O1/O2 have distinct keys
and independently rebuild their common IR/base-SSA prefix.

## Method and structural evidence

[`pre_llvm_ir_ssa_materialization_profile.py`](../../scripts/pre_llvm_ir_ssa_materialization_profile.py)
profiles all 30 manifest entries. The same four native-unsupported workloads as
TEST-PERF-3 are reported fail-closed, leaving 26 workloads and 78 O0/O1/O2
records. Source/AST, Initial IR, base SSA, and final SSA counts are checked into
[`pre_llvm_ir_ssa_materialization_performance_profile.json`](pre_llvm_ir_ssa_materialization_performance_profile.json).
Machine-dependent timing stays in a local sidecar.

The profile shares frontend preparation once per workload, matching O2.13's
three-profile LLVM loop, and deliberately preserves the current independent
IR/SSA materialization for every profile. Environment: Linux, CPython 3.14.7.

Exact operations for the 26 supported workloads were:

| Operation | Calls |
|---|---:|
| source load / parse / AST construction / type check | 26 each |
| module/import-resolution frontend boundary | 26 |
| Initial IR lowering | 78 |
| Initial IR verifier | 130 (78 initial + 52 post-IR optimization) |
| lifecycle expansion | 52 (O1/O2) |
| SSA construction | 78 |
| SSA verifier | 874, including optimizer input/pass checks |
| optimizer runs O0 / O1 / O2 | 26 each |
| LLVM backend handoffs | 78 |

Thus the profile-independent typed-program prefix is shared, but Initial IR and
base SSA are rebuilt three times. O1 and O2 also repeat the same lifecycle and
IR optimization prefix. A TEST-PERF-1 hit itself does not repeat materialization;
the uncached LLVM evidence route and profile-specific cache keys are the relevant
boundaries.

## Timing result

The isolated 78-record run took 544.24 s wall time. Additive measured materializer
intervals account for **542.64 s**: **537.51 s pre-LLVM** and **5.13 s in
`LLVMBackend.emit`**. This run is not directly interchangeable with the older
129.61 s pytest sample: it isolates every unique profile materialization on the
current machine. Its stage proportions and operation counts identify the cause.

| Stage | Seconds | Share of pre-LLVM |
|---|---:|---:|
| Initial IR verification | 267.20 | 49.7% |
| post-IR-optimization verification | 182.85 | 34.0% |
| SSA optimization, including embedded checks | 68.87 | 12.8% |
| SSA construction | 4.33 | 0.8% |
| IR optimization | 3.43 | 0.6% |
| Initial IR lowering | 3.09 | 0.6% |
| semantic/type analysis | 2.14 | 0.4% |
| final SSA verification | 1.87 | 0.3% |
| initial SSA verification | 1.86 | 0.3% |
| lifecycle expansion | 1.56 | 0.3% |
| parsing/AST + source loading | 0.32 | 0.1% |
| pipeline construction | 0.01 | <0.1% |

The separately reported 20.12 s of SSA optimizer embedded verification is nested
inside the 68.87 s optimizer interval and must not be added again.

| Profile | Records | Pre-LLVM (s) | LLVM emit (s) | Total (s) |
|---|---:|---:|---:|---:|
| O0 | 26 | 93.71 | 1.72 | 95.43 |
| O1 | 26 | 191.58 | 1.77 | 193.35 |
| O2 | 26 | 252.23 | 1.64 | 253.87 |

The O2 SSA pass-exclusive leaders were `OwnershipElidedArrayGet` (19.47 s),
`LocalARCEliminator` (18.46 s), `ProvenBoundsCheckEliminator` (5.97 s), and
`LoopInvariantCodeMotion` (2.40 s). Pass timings exclude the pipeline's
post-pass verifier time. Pass order and membership were unchanged.

## Expense tracker and scaling

`expense_tracker/Main.ae` has 9,273 source characters, 795 AST nodes, 26 IR
functions, 475 IR blocks, and 4,203 Initial IR instructions. Its base SSA has
3,028 instructions at O0 and 3,016 at O1/O2; final O2 has 2,988.

| Profile | Pre-LLVM (s) | Largest costs |
|---|---:|---|
| O0 | 91.28 | initial IR verify 87.79 s |
| O1 | 186.19 | initial/post IR verify 87.49/90.44 s |
| O2 | 242.87 | initial/post IR verify 90.81/91.78 s; SSA optimize 55.79 s |

Its 520.34 s are **96.8%** of all pre-LLVM time. Pearson correlation of total
pre-LLVM time is 0.89 with source length, 0.88 with AST nodes, 0.92 with Initial
IR instructions, and 0.93 with base/final SSA instructions. Those correlations
are lower than TEST-PERF-3's 0.9995 backend result because verifier behavior is
superlinear on the largest control-flow graph.

## cProfile reconciliation

A focused cProfile of one expense-tracker Initial IR verification took 293.82 s
under profiler overhead. `IRVerifier._verify_reachable_values` accounted for
293.27 s. It called `_is_lifecycle_storage` 17,709 times; that helper repeatedly
scanned function blocks/instructions, executing its generator expressions about
22.0 million and 39.3 million times. This directly reconciles the stage timer
with a concrete algorithmic hotspot. On representative `sumTo.ae` O0, the full
pre-LLVM cProfile took 0.011 s; IR/SSA verifier frames led cumulative time but
all verifier work totaled only 0.0047 s. The aggregate corpus outside expense
tracker used only 17.17 s pre-LLVM.

A cProfile of the complete regeneration was not practical: profiling just one
87.8 s expense-tracker verifier call inflated it to 293.8 s. The complete run
would add many hours of profiler-distorted evidence. The unprofiled full stage
instrumentation plus focused large/small cProfiles is therefore the comparable
evidence set.

## Recommendation

The safest TEST-PERF-3.2 milestone is narrowly scoped: precompute the set of
lifecycle-storage names once per function inside Initial IR reachable-value
verification, then reuse it at CFG merge points. Preserve every verifier rule,
diagnostic, execution count at the verifier boundary, and Rust/Python authority
behavior; add equivalence and adversarial CFG/lifecycle regressions.

This removes repeated pure classification work rather than skipping verification.
The measured hotspot covers almost all of the 450.05 s IR-verifier time locally;
a conservative recoverable estimate is **80–90% of pre-LLVM time** on the
expense-tracker-heavy regeneration (roughly 100–112 s when scaled to the prior
~124 s pre-LLVM sample). Common-prefix reuse across O0/O1/O2 is a separate later
opportunity and should not be combined with the verifier fix.
