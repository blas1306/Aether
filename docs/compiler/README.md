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

Initial SSA model, textual printing, verification infrastructure, the phase-1
linear-function SSA builder, and the phase-2 simple `if`/`else` builder live
under `aether.ssa`, along with phase-3 support for simple `while` loops. The
internal `aether.pipeline.SSAPipeline` prepares verified SSA modules for
compiler tests and future consumers. CLI SSA export exists for inspection; SSA
execution, general CFG-based SSA construction, and SSA optimizations are not
implemented yet.

Current compiler-design documents:

- [DOMINATORS.md](DOMINATORS.md): implemented iterative dominator analysis,
  implemented dominance frontiers, and their role in future SSA construction.
- [SSA_DESIGN.md](SSA_DESIGN.md): initial design notes for future SSA support
  in the Aether IR.
- [SSA_CONSTRUCTION.md](SSA_CONSTRUCTION.md): implemented linear, simple
  `if`/`else`, and simple `while` SSA builder, internal verified SSA pipeline,
  planned full construction algorithm, and verification rules.
- [SSA_BUILDER.md](SSA_BUILDER.md): operational migration plan for replacing
  the current pattern-based SSA builder with a general dominance-frontier-based
  builder.
