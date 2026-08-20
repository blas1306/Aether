# TEST-PERF-2 — O2.13 LLVM evidence performance audit

Date: 2026-08-20

## Decision

`O2_13_NO_SAFE_REUSE_OPPORTUNITY` for the dominant checked-in-baseline test.
One complete regeneration makes 78 distinct LLVM requests: 26 supported
workloads times the genuinely distinct O0, O1 and O2 profiles. There is no
native compilation or execution in that test. Across the five O2.13 tests,
the first two workloads are regenerated four times, producing 18 duplicate
LLVM requests, but the measured duplicate subset is negligible beside the
129.61 s full regeneration. This is category **B, test-harness consolidation**,
not evidence for a broad LLVM cache.

## Inventory and execution graph

O2.13 consists of the five tests in `tests/aether/test_o2_measurement.py`, the
generator `scripts/o2_measurement.py`, the 30-entry
`benchmarks/o2_workloads.json` manifest and the deterministic
`docs/compiler/o2_measurement_baseline.json`. The optional runtime artifact is
`docs/compiler/o2_runtime_measurements.json`; normal tests neither regenerate
nor compare it.

The static path actually executed per supported workload is:

```text
source
  +-> typed frontend -> Initial IR census
  +-> shared SSA(O0) -> O2 pass trace -> evidence analyses
  +-> shared SSA(O1) ------------------> evidence analyses
  +-> typed frontend (once) -> [LLVMBuilder O0, O1, O2]
         each: Initial IR -> profile IR passes -> SSA -> profile SSA passes
               -> verified SSA-to-LLVM textual emission
report -> deterministic JSON rendering
```

Four unsupported workloads stop after Initial IR failure. LLVMBuilder does not
consume the cached O2 evidence module: it constructs a private IR/SSA graph
from the typed program for every profile. Therefore LLVM lowering cannot mutate
or corrupt cached O2 evidence. A regression test also runs the O2 trace from a
cached O0 snapshot, verifies its representation remains unchanged, and verifies
the cache still returns the same object. SSA passes return replacement frozen
dataclasses; analysis consumers build separate results.

The opt-in runtime path is different: for every selected benchmarkable
workload/profile it calls `_build_native`, which repeats typed preparation and
LLVM generation, invokes clang once, then runs the executable once per warmup
and repetition. The pytest smoke selects zero workloads, so its native compile
and execution counts are both zero.

## Counts

| Operation | Full baseline test | Entire five-test module |
| --- | ---: | ---: |
| Workloads requested | 30 | 36 workload-generations |
| Supported workload-generations | 26 | 32 |
| Shared-SSA requests | 52 (26 O0, 26 O1) | 64 |
| LLVM lowerings | 78 | 96 |
| LLVM textual emissions | 78 | 96 |
| Exact duplicate LLVM requests | 0 | 18 |
| Native compiler invocations | 0 | 0 |
| Native executable invocations | 0 | 0 |
| Report constructions | 1 | 4 |
| JSON serializations | 0 (the test compares Python values) | 0 |

The module count follows its exact calls: one two-workload generation, two
more two-workload generations in the determinism test, one full generation,
and one empty runtime smoke. Exact LLVM identity is source bytes + canonical
diagnostic path + complete frozen optimization profile + backend/compiler
configuration + target/platform. O0/O1/O2 are not duplicates.

TEST-PERF-1 shares O0/O1 requests where the same source/path/profile has already
been requested in the pytest process. A cold standalone full regeneration has
52 builds and zero hits; session ordering may turn some of the six earlier
two-workload requests into hits. The O2 trace deliberately starts from O0 and
runs the traced O2 pipeline; it is not an accidental independent O2 rebuild.

## Timing evidence

The comparable post-TEST-PERF-1 pytest sample records approximately 129.9 s for
the five-test O2.13 module, including 129.61 s for
`test_checked_in_static_baseline_is_exactly_regenerated`, and 0.13 s for the
two-workload fingerprint/determinism test. The five-test O2.13 module is thus
dominated by its single complete static regeneration. Native compilation and
native execution contribute exactly zero to that cost.

`scripts/o2_13_performance_audit.py` provides opt-in stage counters and timings,
including the ten slowest individual operations. A full run attempted on the
current constrained container was cancelled after 20 minutes and is excluded:
it is not comparable evidence. No absolute timing is asserted in CI.

The structural breakdown is decisive even without treating overlapping nested
timers as additive: 78 unique LLVM generations dominate the complete test,
while evidence analysis and one JSON serialization are local in-process work.
The first-two-workload repeated test takes only a small fraction of the full
regeneration sample, so consolidating its 18 duplicate emissions cannot recover
material suite time. Per-workload/profile rankings should be collected on an
unconstrained host with the included auditor before selecting production work.

## Reuse designs considered

A possible LLVM materialization value would be immutable LLVM UTF-8 text with a
session lifetime. Its key must include source bytes, canonical diagnostic path,
the complete optimization profile, all lowering/backend feature configuration,
target triple/platform and compiler revision. It must never be keyed by path
alone. The current audit does **not** implement it because the dominant test has
zero exact duplicate requests.

A future native key would additionally include LLVM bytes, resolved clang path
and version, compiler/linker flags, runtime linkage and relevant environment.
No native cache is justified by this test path.

## Opportunity classification

1. **C — production compiler performance:** 78 unique required LLVM pipelines;
   this is the dominant remaining cost and needs finer profiling, not caching.
2. **B — test-harness consolidation:** 18 duplicate emissions for the first two
   workloads across tests; safe in principle but negligible in measured impact.
3. **D — required integration cost:** opt-in native compilation/execution must
   remain real when runtime measurements are explicitly requested.
4. **A — safe structural reuse:** none significant in full regeneration after
   TEST-PERF-1 SSA sharing.
5. **E — unknown:** ranking unique workload/profile LLVM costs on an
   unconstrained measurement host.

The safest next milestone is **TEST-PERF-2.1: profile unique LLVM generation by
workload/profile inside LLVMBuilder**, separating frontend/IR, SSA lowering and
printer/runtime-section emission. Do not add LLVM or native caching. Expected
recoverable suite time from currently proven duplication is less than the
two-workload determinism test (well below one second in the comparable sample);
the 129.61 s dominant cost is presently classified as unique required compiler
work.

## Determinism and validation

Instrumentation is out-of-band and never enters the canonical report. The
auditor compares regenerated UTF-8 bytes with the checked-in baseline on full
runs. Its regression test additionally snapshots baseline bytes before and
after a one-workload audit. No historical artifact, optimization profile,
compiler/runtime/ABI behavior, RP3 path or timeout was changed.
