# Compiler Documentation

This directory contains technical documentation for the Aether compiler
implementation.

It is separate from `docs/aether/` on purpose:

- `docs/aether/` describes the Aether language and language-level design:
  syntax, semantics, type rules, the v0 specification, and design notes that
  define what Aether programs mean.
- `docs/compiler/` describes how the implementation is organized internally:
  compiler pipeline, IR lowering, control-flow analysis, SSA, optimizer design,
  and backend-oriented plans.

In short, `docs/aether/` is about the language contract. `docs/compiler/` is
about compiler machinery.

IR analysis helpers live under `aether.analysis`; the current CFG builder and
DOT printer are exposed by `aether.analysis.cfg`, and dominator analysis is
exposed by `aether.analysis.dominators`. Dominance frontier analysis is exposed
by `aether.analysis.dominance_frontier`.

Initial SSA model, textual printing, verification infrastructure, the legacy
pattern-based SSA builder, the default `GeneralSSABuilder`, SSA analysis
infrastructure, SCCP analysis and constant transformation, and the SSA
optimizer pipeline live under `aether.ssa`.
`aether.ssa.analysis` currently provides reusable lattice states
(`Unknown`, `Constant(value)`, and `Overdefined`) plus a duplicate-suppressing
FIFO worklist for propagation analyses. `aether.ssa.optimizer.sccp` provides
Sparse Conditional Constant Propagation facts: value lattice states,
executable blocks, and executable edges. Its transformer can replace
`SSABinaryOp`, `SSACompareOp`, and `SSAPhi` producers proven constant by SCCP
with `SSAConst` and can simplify boolean constant `SSABranch` terminators to
`SSAJump`, remove unreachable blocks, and clean phi incoming lists. `SCCPPass`
connects the SCCP analyzer and transformer to the default SSA optimizer
pipeline. The optimizer pipeline currently defaults to `SSAConstantFolder`,
`SSAGlobalConstantPropagator`, `SSAAlgebraicSimplifier`, `SCCPPass`,
`TrivialPhiEliminator`, `DeadPhiEliminator`, and `SSADeadCodeEliminator`, but
it is still not connected to CLI SSA export or execution. `SSAConstantFolder`
folds binary and comparison operations whose operands are known `SSAConst`
values; `SSAGlobalConstantPropagator` conservatively replaces globally known
constant SSA producers; `SSAAlgebraicSimplifier` applies local integer
identities such as `x + 0 -> x` and `x * 0 -> 0`; `SCCPPass` performs
edge-sensitive constant propagation, branch simplification, unreachable-block
cleanup, and phi incoming cleanup; `TrivialPhiEliminator` rewrites phis whose
incoming values are all the same SSA value; `DeadPhiEliminator` removes phis
whose results have no uses; `SSADeadCodeEliminator` removes unused pure SSA
producers while preserving calls until effect analysis exists. The internal
`aether.pipeline.SSAPipeline` prepares verified SSA modules for compiler tests
and future consumers using the general builder by default. CLI SSA export
exists for inspection; SSA execution, general copy propagation, GVN, LICM, and
effect-aware call removal are not implemented yet. The pattern builder remains
available temporarily through `--ssa-builder=pattern` for compatibility and
comparison.

Current compiler-design documents:

- [BACKEND_ARCHITECTURE_AUDIT.md](BACKEND_ARCHITECTURE_AUDIT.md): dated
  inventory of the real backend pipeline, mixed responsibilities, semantic
  duplication, Python coupling, migration blockers, and finding catalog.
- [AETHER_NATIVE_ABI.md](AETHER_NATIVE_ABI.md): descriptive contract for the
  current internal native layouts, calling conventions, ownership, runtime
  dependencies, and explicitly non-stable ABI areas.
- [BACKEND_MIGRATION_ROADMAP.md](BACKEND_MIGRATION_ROADMAP.md): phased
  Python/Rust coexistence plan with entry/exit criteria, rollback, metrics,
  sanitizers, and recommended language ownership by component.
- [BACKEND_FEATURE_PARITY.md](BACKEND_FEATURE_PARITY.md): evidence-based
  parity audit across frontend, AST, IR, SSA, LLVM/native, CLI, REPL and the
  IntelliJ tool, including characterization probes and optimizer safety gaps.
- [DOMINATORS.md](DOMINATORS.md): implemented iterative dominator analysis,
  implemented dominance frontiers, and their role in future SSA construction.
- [SSA_DESIGN.md](SSA_DESIGN.md): initial design notes for future SSA support
  in the Aether IR.
- [SSA_CONSTRUCTION.md](SSA_CONSTRUCTION.md): implemented pattern and general
  SSA builders, internal verified SSA pipeline, construction algorithm,
  verification rules, SSA optimizer pipeline infrastructure, Trivial Phi
  Elimination, Dead Phi Elimination, SSA Constant Folding, SSA Algebraic
  Simplification, SSA Dead Code Elimination, and reusable SSA analysis
  infrastructure for future propagation analyses.
- [SSA_BUILDER.md](SSA_BUILDER.md): operational migration notes for the move
  from the pattern-based SSA builder to the general dominance-frontier-based
  default.
- [SCCP.md](SCCP.md): completely implemented Sparse Conditional Constant
  Propagation over SSA, including analysis, constant transformation, branch
  simplification, unreachable-block cleanup, phi incoming cleanup, and
  integration into the SSA optimizer pipeline.
- [CONTROL_FLOW_AUDIT.md](CONTROL_FLOW_AUDIT.md): technical audit of current
  `if`, `while`, `for`, `break`, `continue`, and `return` support across IR,
  CFG, SSA, optimizers, LLVM, and tests.
- [ARRAY_SUBSYSTEM_AUDIT.md](ARRAY_SUBSYSTEM_AUDIT.md): comparative technical
  audit of `Array<T>` across frontend, interpreters, IR, SSA, optimizers, LLVM,
  runtime, tests, and documentation, using the current `List<T>` guarantees as
  the baseline.
- [LLVM_BACKEND.md](LLVM_BACKEND.md): initial textual LLVM IR backend for the
  smallest SSA subset, its type mapping, current limitations, and the fact
  that it is not connected to CLI yet.
- [MUTABLE_AGGREGATES.md](MUTABLE_AGGREGATES.md): intended mutable-reference
  semantics for `List`, `Array`, `Vector`, and `Matrix`, including aliasing,
  future indexed set operations, optimizer constraints, `const`, explicit
  copies, and runtime/GC implications.
