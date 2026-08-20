# TEST-PERF-3 — LLVM generation internal performance profile

## Decision

The 78 unique O2.13 emissions are classified as:

    LLVM_MULTIPLE_COST_CENTERS
    LLVM_WORKLOAD_SPECIFIC_PATHOLOGY

There is no text-concatenation pathology and no O2-specific backend path.  Cost is
broadly proportional to final SSA size.  `examples/expense_tracker/Main.ae` is the
only workload-scale outlier, but its time is consistent with its 2,988–3,028 SSA
instructions rather than a distinct lowering subsystem.

This milestone changes no LLVM, SSA, optimization profile, helper, ABI, verifier,
or cache behavior.  Profiling is opt-in through `LLVMGenerationProfiler`; the
normal backend follows its former branch without creating timers.

## Scope and execution graph

The measured interval starts with a final verified SSA module and ends with LLVM
text.  The production path is:

    LLVMBuilder.emit_llvm
      -> capability validation
      -> Initial IR lowering and IR optimization
      -> verified SSA lowering and SSA optimization
      -> LLVMBackend.emit
           -> NativeBoundaryVerifier + SSAVerifier
           -> LLVMPrinter.print_module
                -> module discovery/type-layout registry
                -> function/block/instruction lowering
                -> witness, exception, ownership and collection helpers
                -> Array/List/Vector/Matrix/integer/math/I/O/string/file/
                   exception/process/class runtime sections
                -> globals and optional native entry wrapper
                -> final section join

TEST-PERF-3 measures the last subtree.  The long materialization of the expense
tracker occurs before `LLVMBackend.emit` and is not charged to textual generation.
No native compilation or execution occurs.

## Method

The O2.13 manifest has 30 workloads.  Four fail native capability validation, as
in TEST-PERF-2, leaving 26 supported workloads and 78 O0/O1/O2 emissions.  Each
record contains profile, function/block/instruction counts, instruction-family
census, LLVM bytes/lines, runtime/helper structure, phase call counts, and local
timings.  Wall-clock data lives in the local timing sidecar; the checked-in
[`llvm_generation_internal_performance_profile.json`](llvm_generation_internal_performance_profile.json)
contains deterministic structural evidence only.

Environment for the reported local run: CPython 3.14.7, Linux.  Timings are
diagnostic and never correctness assertions.

## Result

Total measured `LLVMBackend.emit` time was **5.561 s**:

| Profile | Emissions | SSA instructions | LLVM bytes | Time (s) |
|---|---:|---:|---:|---:|
| O0 | 26 | 4,434 | 1,347,047 | 1.842 |
| O1 | 26 | 4,405 | 1,344,902 | 1.829 |
| O2 | 26 | 4,377 | 1,339,233 | 1.891 |
| Total | 78 | 13,216 | 4,031,182 | 5.561 |

Across all emissions there were 261 functions and 2,163 blocks.  O2 is slightly
smaller than O0 and is not systematically slower.  The small timing inversion is
ordinary local noise; profiles produce nearly equal backend work.

Pearson correlation with runtime was 0.9995 for instruction count, 0.9987 for
block count, 0.9667 for function count, 0.9863 for LLVM bytes, and 0.9814 for LLVM
lines.  This is strong evidence of broad size-proportional behavior.

## Phase attribution

| Phase | Calls | Seconds | Share of total |
|---|---:|---:|---:|
| SSA/native-boundary verification | 78 | 1.939 | 34.9% |
| Function lowering | 261 | 1.514 | 27.2% |
| Runtime/helper emission | 78 | 1.302 | 23.4% |
| Module setup/declarations residual | 78 | 0.801 | 14.4% |
| Final text rendering (`join`) | 78 | 0.006 | 0.1% |
| Backend construction | 78 | 0.008 | 0.2% (reported separately) |

Instruction lowering is nested inside function lowering: 13,216 calls consumed
0.818 s.  Its largest family was `SSACall` (0.219 s), followed by `SSAConst`
(0.062 s), `SSAArrayGet` (0.033 s), and `SSACompareOp` (0.031 s).  No family
dominates the end-to-end cost.

Runtime/helper support contributes 3,655,149 bytes and 94,365 lines: **90.7% of
all emitted LLVM bytes**, while construction consumes 23.4% of time.  The corpus
emits 3,175 helper bodies representing 206 distinct body hashes; 181 distinct
bodies occur in more than one module.  Large identical support is therefore
real, but it is more significant for output size than Python generation time.

## Top offenders

The ten slowest emissions are:

| Workload | Profile | Time (s) | Instructions | LLVM bytes |
|---|---:|---:|---:|---:|
| expense_tracker/Main.ae | O2 | 1.217 | 2,988 | 385,081 |
| expense_tracker/Main.ae | O1 | 1.180 | 3,016 | 390,205 |
| expense_tracker/Main.ae | O0 | 1.166 | 3,028 | 391,170 |
| numerical_methods/main.ae | O2 | 0.223 | 507 | 59,169 |
| numerical_methods/main.ae | O0 | 0.207 | 519 | 59,769 |
| numerical_methods/main.ae | O1 | 0.197 | 507 | 59,169 |
| aggregate_collections/particles.ae | O0 | 0.051 | 125 | 52,770 |
| aggregate_collections/particles.ae | O2 | 0.049 | 124 | 52,746 |
| aggregate_collections/particles.ae | O1 | 0.048 | 124 | 52,746 |
| exceptions/constructor_failure.ae | O0 | 0.038 | 58 | 61,225 |

The top three by size and instruction count are the three expense-tracker
profiles.  By size they are followed by the three `owned_aggregates_arc` profiles
(65,470 bytes) and the three `constructor_failure` profiles (61,225 bytes).  By
instruction count they are followed by the three numerical-method profiles and
the three particle profiles.  Complete top-ten lists and all records are in the
local timing report and structural JSON.

The expense tracker accounts for roughly 65% of measured time and 29% of SSA
instructions.  Its superlinear-looking share is explained by repeated whole-module
analysis in addition to instruction lowering, not by one opcode family.

## Python profile and repeated analysis

`cProfile` was run on the slowest representative available outside the separately
materialized expense-tracker seed (`numerical_methods/main.ae`).  Cumulative time
was led by `LLVMBackend.emit`, `LLVMPrinter.print_module`, and SSA verification.
Within the printer, `_collect_embedded_reference_types`, `_collect_interface_types`,
and `_collect_nullable_types` each recursively traverse the same dataclass graph
(4,065 visits in the representative run).  The built-in `isinstance` accumulated
113,396 calls.  This reconciles profiler names with the architecture: repeated
module-wide type discovery is a genuine setup cost, while final string joining is
not.

Layout lookup itself is module-local and memoized by `LLVMTypeLayouts`; the audit
found no evidence that recursive layout computation dominates.  Helper bodies and
runtime declarations are rebuilt for every module, by design.  Mangling/signature
work was not a measurable independent center.

## Ranked future candidates (not implemented)

1. **Fuse the three recursive module type-discovery walks.** Expected textual
   backend benefit: up to part of the 0.801 s setup center, concentrated in large
   modules. Complexity medium, semantic risk medium, production compiler change;
   requires LLVM text byte-equality and backend qualification.
2. **Reuse immutable pre-rendered runtime/helper templates within an emission.**
   Upper measured center is 1.302 s (23.4%); realistically less because dynamic
   helpers remain module-specific. Complexity medium, semantic/ABI risk medium,
   production change; requires helper and full LLVM byte-equality qualification.
3. **Reduce verifier repeated traversal without weakening verification.** Upper
   center is 1.939 s (34.9%). Complexity high, semantic risk high, production and
   verifier change; requires a separate verifier qualification milestone. Skipping
   verification is not a candidate.
4. **Specialize high-volume call lowering only after a finer call-kind profile.**
   Upper instruction-family evidence is 0.219 s (3.9%). Complexity medium,
   semantic risk medium, production change; benefit currently small.
5. **Do not optimize final string joining.** Its ceiling is 0.006 s (0.1%).

Even eliminating all measured runtime/helper construction would recover only about
1.3 s from the 129.61 s TEST-PERF-2 dominant regeneration (about 1%).  The measured
textual backend totals 5.56 s, so most time attributed at the public
`LLVMBuilder.emit_llvm` boundary is before textual emission.  The recommended next
milestone is **TEST-PERF-3.1 — pre-backend IR/SSA materialization profile**, focused
on the expense tracker and split by capability validation, IR lowering, each IR
pass, SSA lowering, verification-after-each SSA pass, and backend emission.  It
must remain diagnostic before selecting any optimization.
