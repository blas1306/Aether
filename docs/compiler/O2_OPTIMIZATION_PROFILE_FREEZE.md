# O2 optimization profile freeze

Status: **O2_FREEZE_QUALIFIED**. This is the normative current O2 document. The
pipeline and its deterministic contracts pass. Required native sanitizer and
exception results are supplied by the accepted maintainer evidence in
`EXCEPTION_RELEASE_QUALIFICATION_V2.md`. This is a hard decision, not a softer
recommendation.

## Exact profiles

The production authority is `src/aether/optimization.py`; all nonempty pass
lists run iteratively to a fixed point and SSA is verified after every pass.

| Profile | Initial IR passes, in order | SSA passes, in order | clang |
|---|---|---|---|
| O0 | none | none | `-O0` |
| O1 | `ConstantFolder`, `LocalConstantPropagator`, `ConstantFolder`, `AlgebraicSimplifier`, `DeadCodeEliminator`, `DeadStoreEliminator`, `DeadCodeEliminator` | `SSAConstantFolder`, `SSAGlobalConstantPropagator`, `SSAAlgebraicSimplifier`, `SCCPPass`, `TrivialPhiEliminator`, `DeadPhiEliminator`, `SSADeadCodeEliminator` | `-O1` |
| O2 | exactly the O1 IR list | exactly the O1 SSA list, then `ProvenBoundsCheckEliminator`, `LoopInvariantCodeMotion`, `OwnershipElidedArrayGet`, `LocalARCEliminator`, `SSADeadCodeEliminator` | `-O2` |

There is no experimental or test-only production pass. The default for direct
execution, `run`, `build`, `bench`, and `--emit-ir/ssa/llvm` is O0. Every route
uses the same profile object. Deprecated `--opt` means O1. Emits observe the
selected pipeline; backend selection does not silently change the profile.
Correctness-required lowering, lifecycle expansion and verification are not
optional optimizations. O0 changes no O2 metadata.

## Frozen pass contracts

### Proven bounds-check elimination (BCE)

The pass consumes point-sensitive range and shape/length facts from
`ProofCoverageAudit`. Only an exact `PROVEN_SAFE` result clears the
`bounds_checked` flag. `UNKNOWN` and `PROVEN_UNSAFE` leave the checked access
and its observable panic path intact. It supports Array get/set, Vector get/set
and Matrix get/set; List and slices currently produce zero transformations.
Arrays use `0 <= i < length`; Vector and Matrix use one-based bounds. Matrix row
and column are proved independently, but the combined helper is removed only
when both succeed. O0/O1 always retain these checks.

The pass does not remove orientation, shape-compatibility, allocation or slice
helper checks, and does not invent alias/purity facts. Checked-overflow,
mutation, calls and exception-edge uncertainty fail closed. The ordinary SSA
verifier runs after it and again after cleanup.

### Loop-invariant code motion (LICM)

LICM uses natural-loop, dominance, existing canonical preheader, range/shape,
and fresh alias/mod-ref information. It never creates a preheader or speculates.
Operands must be loop-invariant and the original block must dominate every
latch and exit. The scalar allowlist is `SSAConst`, `SSAUnaryOp`, scalar
`SSACompareOp`, plus dynamically nontrapping `SSABinaryOp` and `SSACast`.
Eligible immutable reads are only `SSAArrayLength`, `SSAListLength`,
`SSAVectorLength`, `SSAMatrixRows`, and `SSAMatrixColumns`, subject to the
collection-specific mod/ref proof.

All calls/invokes, allocation, element or field accesses, stores, ARC,
ownership transfer, phis, terminators and exception operations are excluded.
Checked integer overflow/division/modulo, string concatenation and checked
double-to-int conversions are excluded. Floating point remains IEEE ordered:
no reassociation, FMA contraction, reduction reordering or fast-math. Unknown
alias, mutation, exceptional, latch or exit facts preserve the instruction.

### Ownership-elided Array get

The only supported element type is `Array<String>`. Direct projection admits
the frozen 15 sites whose owned temporary has a sole nonescaping aggregate
projection use. Immediate borrow admits the frozen three sites whose sole
consumer has a read-only borrowed-String contract. Both require exact
provenance, Array lifetime coverage, no mutation/alias invalidation, no escape,
no ownership-consuming use, and safe loop/backedge and exception regions.
Unknown facts preserve owned lowering. The stable-region `%373` case remains
owned. No List, Vector, Matrix, other Array element type or unrelated consumer
is transformed. Borrow qualification is independent of BCE: a checked access
remains checked unless BCE proves it safe.

### Local ARC

The semantic authority is the current pair classifier,
`OwnershipEscapeAnalysis.classify_pair()` (the canonical API corresponding to
the historical `classify_arc_pair()` contract). Exact same-value provenance
and an owned role are required. Phase 1 handles ordered same-block pairs. Phase
2 handles only an acyclic, unconditional, single-predecessor multi-block chain
where retain dominates release and release post-dominates retain. The region
must contain no call, throw/trap, write, ownership operation, aggregate,
interface, constructor, MethodResult, branch/join, alternate exit or backedge.
Unknown, escape, exception, provenance or path ambiguity retains both calls.
Nested/structurally complex historical candidates remain blocked. The current
30-workload corpus has zero productive removals; dormant fail-closed membership
is intentional.

### DCE interaction

The final DCE cleans values made dead by qualified transformations. Its closed
effect model preserves trapping instructions, checked accesses with observable
panic, effectful memory reads, ARC/lifecycle operations, and exception
operations unless the model explicitly declares an instruction removable.
Verification after every SSA pass guards structure, dominance, types,
ownership/lifecycle and exceptional CFG contracts.

## Analysis inventory

Production-critical analyses are dominance and post-dominance, natural loops,
point-sensitive ranges, shapes/lengths, alias/mod-ref, instruction effects,
ownership/escape, exact aggregate/component provenance, and consumer ownership
contracts. Field-sensitive effects are production-critical for available
mod/ref queries but deliberately not consumed to hoist arbitrary fields.
Proof-coverage, opportunity census and LLVM-overlap measurement are audit-only.
Scalar-replacement and aggregate-copy-elision readiness analyses are future-use
only. Freeze removes none of this infrastructure.

## Corpus, parity and performance

`benchmarks/o2_workloads.json` is canonical: 30 workloads (7 real, 17 realistic
kernels, 6 synthetic), 20 benchmarkable, and 26 supported through Initial IR
and SSA. The four gaps are Initial IR gaps: external/global identifier `Plots`,
two assignments outside local scope (`f1`, `solNR`), and unsupported
`InputCall`. They are measurement gaps and do not expand semantics here.

The deterministic baseline is `o2_measurement_baseline.json`; it observes 30
natural loops and zero new `TRANSFORMABLE_NOW` opportunities. Numeric parity
uses the language's declared output contract; O2 introduces no fast-math.
Qualification compares exit code, stdout and stderr for O0/O1/O2. The checked-in
runtime subset uses warmup, repeated samples, median/min/spread, output hashes
and executable size. Small kernels are noise-sensitive and should be batched.

The conservative regression rule is: no clear, reproducible material O2
regression against O1 on a real workload without an explanation separating the
Aether SSA delta, clang `-O1`/`-O2`, code size and timer noise. Classify each as
faster, equivalent/noise or slower. **O2 is a higher optimization profile, not
a guarantee that every workload runs faster than O1.** Its contract is semantic
preservation, a qualified pipeline, and no known systematic harmful regression.

## Validation and evidence

The machine-readable results are in `o2_qualification.json`. The static
checker, focused O2 tests, full Python suite, exception promotion/native tests,
ownership/lifecycle tests, ASan/LSan/UBSan outside ptrace, locked Rust workspace
tests (including integration/doctests), official VS Code tests, IntelliJ build,
wheel/sdist clean-install and capability/release-doc checks form the release
gate. A skipped or environment-blocked gate is not invented as PASS. The
accepted maintainer qualification at revision `7d59895781ccb5678d131cdfd1184ce73ae34a71`
records 54/54 native exception tests under ASan/LSan/UBSan outside ptrace, the
seven sanitizer-tagged ERQ-006 programs with no leak/UAF/double-free/ownership
finding, full ERQ-006 (11 positive, 9 negative, 77 comparisons), full Python
4468 passed/4 skipped/0 failed, Rust, tooling and packaging PASS. The current
O2 static checker and qualification tests pass. Therefore the decision is
`O2_FREEZE_QUALIFIED`.

Maintainers rerun static measurement with
`python scripts/o2_measurement.py --mode static-only`, the representative
runtime subset with `--mode runtime --runtime-limit 3`, the complete
benchmarkable set with `--mode runtime --runtime-limit 20`, and deterministic
freeze checks with `python scripts/check_o2_qualification.py`.

## Aether/LLVM boundary

Aether owns transformations requiring language facts: bounds, ownership and
lifetime, selected collection contracts and conservative semantic LICM. LLVM
remains the primary authority for GVN/CSE, SROA, generic induction-variable and
loop transforms, scalar replacement, instruction combining, vectorization and
backend-specific optimization. Aether does not add a generic pass because a
mature compiler normally has one. Evidence must show that the cost survives
LLVM, that Aether has unique semantic knowledge, or that it enables another
Aether-specific optimization.

## Concrete-opportunity policy and reopen criteria

A productive candidate requires an exact workload, exact SSA instruction,
exact proof, exact before/after transformation, and verifier/fail-closed story.
`HYPOTHESIS_ONLY` never justifies a production pass.

Reopen criteria, version 1: at least one of the following must hold:

1. A new/expanded real workload yields a verified `TRANSFORMABLE_NOW` candidate.
2. A language feature creates a semantic optimization opportunity.
3. A cost survives LLVM because runtime/helper opacity blocks it.
4. A measurable regression identifies an Aether-specific need.
5. New analysis makes a previously `ANALYSIS_BLOCKED` candidate concretely transformable.
6. Platform or backend evolution changes the opportunity.

Checklist completeness is not a reopen criterion.

## Historical chronology

Historical conclusions are immutable inputs: readiness
(`O2_OPTIMIZATION_READINESS.md`), analysis foundation, BCE, alias/mod-ref and
field-sensitive effects, LICM, ownership/escape and LocalARC, workload
measurement, scalar-replacement investigation, aggregate copy-elision
investigation, concrete-opportunity reconciliation, O2.13 workload expansion,
and this final freeze. The exact retained paths are enumerated by
`o2_qualification.json`; this current index does not rewrite them.
