# TEST-PERF-1 — O2 evidence materialization audit

Date: 2026-08-20

## Result

The 69-test pre-change O2 family took 770.57 s in the RUST-2.P1 full-suite
measurement.  With process-local O2 SSA materialization it takes 211.82 s on
the same checkout (69/69 passed): 558.75 s recovered, or 72.5%.  This is a
structural comparison, not an absolute CI performance gate.

The original full suite took 1137.36 s.  Holding its other costs constant, the
measured saving projects to about 578.61 s (49.1% faster).  Machine load and
test ordering mean that projection is not a full-suite benchmark.  The actual
post-change full run completed in 576.51 s: 4673 passed, the same 24
LeakSanitizer/ptrace environmental failures remained, and 4 were skipped.  The
two additional passes are the cache-contract tests added by this milestone.

## Inventory and duplication

The family is `tests/aether/test_o2*.py`: 69 tests before this milestone across
17 modules (71 after adding two cache-contract tests).  Fourteen generators
directly called `aether.benchmark._optimized_ssa`.  Several generators also
call earlier generators, so the expense-tracker workload was repeatedly parsed,
typed, lowered to Initial IR, converted to SSA, and optimized at O2.

The optimized run observed 165 SSA requests: 80 unique builds and 85 cache hits.
Without sharing, every request was a build.  Each `_optimized_ssa` build includes
one parse/type preparation, one Initial IR lowering, one SSA construction, and
one selected optimization pipeline.  The ranked repeated operations are:

| Rank | Operation | Before | After | Avoided |
| ---: | --- | ---: | ---: | ---: |
| 1 | parse/type/Initial IR/SSA pipeline attributable to audit `_optimized_ssa` calls | 165 | 80 | 85 |
| 2 | O2 SSA requests | 111 inferred requests | 26 builds | 85 shared requests |
| 3 | O1 SSA builds | 28 | 28 | 0 |
| 4 | O0 SSA builds used for pass traces | 26 | 26 | 0 |
| 5 | LLVM emission in O2.13 measurement | unchanged | unchanged | 0 |
| 6 | historical JSON regeneration | 0 | 0 | 0 |

The O2 request count is derived from the observed total requests minus the 28
O1 and 26 O0 unique requests.  O1/O0 workloads do not overlap at the same
profile in this run.  Direct `_build_ir`, `_typed_program`, LLVM emission, audit
analysis, and JSON rendering in `o2_measurement.py` intentionally remain
uncached: they are distinct evidence stages rather than duplicate O2 SSA
materialization.

## Architecture after consolidation

`aether.o2_evidence_materialization.optimized_ssa` is the single preparation
entry point used by all fourteen SSA-consuming O2 generators.  It materializes
only the requested profile.  Audit analysis and JSON rendering remain in their
logically separate generators.

The cache key is `(source contents, resolved diagnostic path, full frozen
OptimizationProfile)`.  Its value is the fully optimized and verified
`SSAModule`; its lifetime is the Python process, which is pytest-session-local
in normal use.  Source or compiler-configuration changes create a new key.
There is no disk cache and therefore no cross-run invalidation problem.

The frontend, IR and optimizer mutate intermediate objects while building SSA,
so no live pre-optimization object is shared.  The cached value exists only
after optimization and verification.  The O2 auditors were inspected as
read-only consumers: they construct separate CFG/dominator/loop/result objects
and do not rewrite the module.  The shared module is consequently owned by the
materializer and treated as an immutable snapshot.  The existing repeated JSON
tests exercise analyses more than once against that same snapshot and remained
byte deterministic.

Historical artifacts remain separate.  Tests which validate frozen O2.9.x and
later JSON continue to load those files directly.  The cache is used only by
current-pipeline generators and never turns a historical validation into a
regeneration.

## Timings after consolidation

The slowest calls from `pytest tests/aether/test_o2*.py --durations=20 -q` were:

| Test | Seconds |
| --- | ---: |
| checked-in O2.13 static baseline regeneration | 129.61 |
| O2.11 real-site reconciliation | 32.32 |
| immediate array/string borrow stable-region check | 30.19 |
| O2.11 byte-deterministic regeneration | 5.24 |
| aggregate lifetime real-workload reconciliation | 2.23 |
| scalar-replacement frozen-candidate reconciliation | 1.98 |
| structural ARC JSON/read-only check | 1.87 |
| structural ARC exact-pair check | 0.98 |
| structural ARC CFG/dominance check | 0.94 |
| O2.13 candidate fingerprint determinism | 0.13 |

The dominant remaining cost is O2.13's intentional Initial IR, pass-trace and
LLVM O0/O1/O2 evidence, followed by two ownership/borrow analyses.  Another
milestone could consolidate O2.13 typed-program/Initial-IR preparation, but it
should first prove that LLVM builders do not mutate typed input and preserve the
independent stage evidence.  The current 72.5% recovery already exceeds the
20% review threshold without weakening an audit.

## Validation

- 69 existing O2 tests passed; all deterministic and checked-in artifact
  comparisons were unchanged.
- 165 materialization requests produced 80 builds and 85 cache hits.
- Added structural tests prove identical evidence builds once and that source
  content/profile changes invalidate the key.
- Full suite: 4673 passed, 24 known environmental failures, 4 skipped in
  576.51 s (baseline: 4671 passed, 24 environmental failures, 4 skipped in
  1137.36 s).
- No historical measurement snapshot, optimizer profile, compiler semantics,
  Rust verifier path, or artifact JSON was changed.
