# O2.13 — Optimization measurement and workload expansion

Status: measurement/corpus/instrumentation only. The deterministic source of
truth is `o2_measurement_baseline.json`; regenerate it with
`.venv/bin/python scripts/o2_measurement.py --mode static-only`.

## Corpus and support

The O2.12 corpus contained 15 workloads. The canonical O2.13 manifest contains
30: 7 real programs, 17 realistic kernels and 6 synthetic probes. It covers 16
primary categories (parsing is deliberately a secondary tag on the real
expense tracker rather than an artificial standalone program). Existing
programs were reused; public examples were not filled with benchmark-only
sources.

Initial IR and SSA support 26/30. Four real inputs are retained and explicitly
reported as unsupported: the bisection program uses a module-scope `Plots`
identifier, `newton_system` and `probandoNR` assign outside local scope, and
Miller–Rabin requires `InputCall`. These are compiler/language support gaps,
not instrumentation gaps, so O2.13 does not close them.

The supported corpus has 30 natural loops. Static loop rows expose depth,
blocks, preheader, latches, exits, IVs, calls, reads, writes, traps/checks, ARC,
allocations, arithmetic, branches, unconditional-body status and a separate
backedge-dominating-operation proxy. No opaque hotness score is used.

## Stage and ownership measurement

Every supported workload records Initial IR, raw/pre-O2 SSA, O1 SSA and O2
SSA censuses. Categories include scalar work, calls, branches, phis, reads,
writes, allocations, ARC, collections, structs, classes, interfaces and
exceptions. The O2 trace attributes candidates and transformations to every
pass and iteration. It therefore separates Aether O1→O2 from the clang level;
runtime collection separately builds Aether O0/O1/O2, whose profiles map to
clang 0/1/2. LLVM textual byte and instruction-line sizes are stored per
workload and level; runtime rows store executable sizes. Standalone object size
is omitted because the current build API does not expose a stable object.

Across the expanded corpus, explicit post-O2 SSA contains 53 retains and 910
releases globally, including 11 retains and 37 releases in loops. Backend
implicit sites remain separate: 92 ArrayGet and 23 ListGet sites are visible
to the conservative census. These are sites, not an assertion that all emits
survive LLVM. Allocation sites are split as 70 String, 6 Array, 42 List, 6
class, 3 interface boxes, 171 other, with loop locality per workload. Escape
state is fail-closed (`unknown`) unless proven.

The pass trace finds first-iteration corpus impact in BCE (6 workloads), LICM
(6), OwnershipElidedArrayGet (1), LocalARC (1), DCE (5), and constant folding
(3). Twenty-four workloads have identical O1/O2 instruction censuses and are
O2 dead zones; the JSON retains the exact list and pass stats. A matching
census does not imply byte-identical IR, only no category-count delta.

## Opportunity and blocker measurement

Repeated expressions name exact instruction pairs, dominance, purity, trap and
memory dependence, LLVM overlap and O2.12 concrete transformability. The two
observed groups are not transformable: checked/trapping semantics prevent the
exact deletion proof. Thus the expanded corpus still contains zero verified
`TRANSFORMABLE_NOW` future candidates. Fingerprints use workload, function,
opcode, operator/operands and loop role rather than SSA result numbers.

Memory reads and allocations remain measurements, not automatic LICM/GVN or
stack candidates. Call-summary, alias/mod-ref and exception/trap blocker maps
are explicit and exact counts default to zero rather than inferred claims.
LLVM overlap uses only `SURVIVES_LLVM`, `LLVM_REMOVES`, `LLVM_PARTIAL`,
`NOT_COMPARABLE`, or `UNKNOWN`. A future Aether pass is eligible only if cost
survives LLVM, uses Aether-only semantics, unlocks another Aether pass, crosses
opaque runtime helpers, or relies on Aether ownership/lifecycle information.

## Runtime protocol

Runtime is opt-in: `--mode runtime` or `--mode full`. Each selected workload is
built separately at Aether O0/O1/O2, warmed up, and run repeatedly. Exit code,
stdout hash and stderr hash must match across all levels before timings are
accepted. Records keep command, source-default workload size, warmups,
repetitions, wall/user/system samples, median, minimum and spread. Full timing
is intentionally absent from normal unit tests and the deterministic static
baseline. See `O2_RUNTIME_MEASUREMENT_REPORT.md` for interpretation rules.

## Recommendation and exact next milestone

The single recommendation is `PAUSE_AETHER_O2_RELY_ON_LLVM`. No future pass has
an exact verified transformation after expansion; the only repeated scalar
hypotheses are semantically blocked, and implementing a pass would violate the
O2.12 evidence rule. The exact next milestone is therefore not a production
transformation: retain the 30-workload baseline, verify LLVM survival for any
new exact candidate, and reopen a listed direction only when a candidate has a
complete rewrite and proof. Expected static effect is zero; scope is
measurement only; semantic risk is low. Required gates are manifest closure,
deterministic regeneration and exact LLVM-survival verification.

Historical O2.10/O2.11/O2.12 artifacts were not rewritten. Optimizer profile
membership, production ownership/lifecycle, ARC, backend, ABI and generated
code were not changed, and no commit is created by the tooling.
