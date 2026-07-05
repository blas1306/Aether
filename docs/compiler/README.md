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
pattern-based SSA builder, the default `GeneralSSABuilder`, and the SSA
optimizer pipeline live under `aether.ssa`. The optimizer pipeline currently
defaults to `SSAConstantFolder`, `TrivialPhiEliminator`, `DeadPhiEliminator`,
and `SSADeadCodeEliminator`, but it is still not connected to CLI SSA export or
execution. `SSAConstantFolder` folds binary and comparison operations whose
operands are known `SSAConst` values; `TrivialPhiEliminator` rewrites phis whose
incoming values are all the same SSA value; `DeadPhiEliminator` removes phis
whose results have no uses; `SSADeadCodeEliminator` removes unused pure SSA
producers while preserving calls until effect analysis exists. The internal
`aether.pipeline.SSAPipeline` prepares verified SSA modules for compiler tests
and future consumers using the general builder by default. CLI SSA export
exists for inspection; SSA execution, general copy propagation, global constant
propagation, SCCP, GVN, LICM, and effect-aware call removal are not implemented
yet. The pattern builder remains available temporarily through
`--ssa-builder=pattern` for compatibility and comparison.

Current compiler-design documents:

- [DOMINATORS.md](DOMINATORS.md): implemented iterative dominator analysis,
  implemented dominance frontiers, and their role in future SSA construction.
- [SSA_DESIGN.md](SSA_DESIGN.md): initial design notes for future SSA support
  in the Aether IR.
- [SSA_CONSTRUCTION.md](SSA_CONSTRUCTION.md): implemented pattern and general
  SSA builders, internal verified SSA pipeline, construction algorithm,
  verification rules, SSA optimizer pipeline infrastructure, Trivial Phi
  Elimination, Dead Phi Elimination, SSA Constant Folding, and SSA Dead Code
  Elimination.
- [SSA_BUILDER.md](SSA_BUILDER.md): operational migration notes for the move
  from the pattern-based SSA builder to the general dominance-frontier-based
  default.
