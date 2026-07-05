# SSA Construction Plan for Aether IR

## Status

This document specifies how Aether should construct SSA from the current
slot-based IR. It is an implementation plan, not an introductory SSA design
note.

Initial SSA infrastructure now exists under `src/aether/ssa/`:

- `model.py` defines the value-based SSA model.
- `printer.py` defines deterministic textual SSA output.
- `verifier.py` defines a minimum structural and type verifier for manually
  built SSA modules.
- `builder.py` defines the phase-1 SSA builder for linear functions, the
  phase-2 builder for simple acyclic `if`/`else` functions, and the phase-3
  builder for simple lowered `while` loops.
- `general_builder.py` defines a Cytron-style builder that wires
  CFG construction, dominators, dominance frontiers, `PhiPlacement`,
  `SSARenamer`, and `SSAVerifier` together as the effective default SSA
  builder.
- `phi_placement.py` defines standalone general phi placement over mutable IR
  slots using CFG, dominators, and dominance frontiers.
- `renaming.py` defines standalone dominator-tree DFS variable renaming over
  the phi-placement result.
- `__init__.py` exposes the public SSA model and printer API.
- `aether.pipeline.lower_to_verified_ssa` and `SSAPipeline` provide an
  internal compiler pipeline from `TypedProgram` or verified `IRModule` to a
  verified `SSAModule`, with `builder="general"` as the default and
  `builder="pattern"` available as a temporary compatibility fallback.

The explicit pattern fallback is intentionally shape-based. It converts
functions with a single `entry` block and no `branch`, `jump`, `if`, `while`,
loop, or phi requirements. It also accepts two deliberately small control-flow
shapes: simple acyclic `if`/`else` with an optional merge block and simple
lowered `while` loops with loop-header phi nodes for loop-carried promoted
slots. The implementation remains stabilized around explicit helpers for slot
state, block emission, instruction conversion, pattern detection, and phi
construction so it can continue serving comparison and migration diagnostics
while `GeneralSSABuilder` is the default construction path.

The current compiler still lowers to slot IR, verifies slot IR, interprets slot
IR, and runs the existing local optimizer pipeline over slot IR. SSA is not used
by the backend yet. It can be inspected from the CLI with
`aether --emit-ssa program.ae`, which prints the verified SSA module and exits.
That inspection path uses `GeneralSSABuilder` by default.
`aether --emit-ssa --ssa-builder=pattern program.ae` selects the older
pattern-based builder explicitly for compatibility and comparison.
`PhiPlacement`, `SSARenamer`, and `GeneralSSABuilder` are still not wired into
execution, optimization, or backend selection.

## Implemented Phase 1

`aether.ssa.SSABuilder` converts the linear subset of slot IR into SSA:

- `IRModule` to `SSAModule`
- `IRFunction` with exactly one `entry` block to `SSAFunction`
- `IRParameter` to `SSAParameter`
- `IRConst` to `SSAConst`
- `IRBinaryOp` to `SSABinaryOp`
- `IRCompareOp` to `SSACompareOp`
- `IRCall` to `SSACall`
- `IRReturn` to `SSAReturn`

It also performs simple block-local slot promotion:

- `IRStore(slot, value)` records the current SSA value for that slot.
- `IRLoad(result, slot)` aliases `result` to the current SSA value for that
  slot.
- No `load` or `store` instruction is emitted in SSA.
- Loading a slot before any store raises `SSABuildError`.

Example:

```text
entry:
    %0: int = const 5
    store %x, %0
    %1: int = load %x
    %2: int = const 3
    %3: int = add %1, %2
    return %3
```

becomes:

```text
entry:
    %0: int = const 5
    %2: int = const 3
    %3: int = add %0, %2
    return %3
```

Current limitations of the effective pattern-based builder:

- no dominance-frontier usage in the effective pattern-based builder
- no general multiple-block functions
- no nested branches, nested loops, general CFG, or arbitrary loops
- no SSA optimizer or backend integration

General phi placement and dominator-tree variable renaming are wired together
by `GeneralSSABuilder`.
They are used by default `--emit-ssa` through `GeneralSSABuilder`; they are not
used by the explicit `--ssa-builder=pattern` fallback.

Current supported subset:

- linear functions with exactly one `entry` block
- simple acyclic `if`/`else` where both branches return, or both branches jump
  to one merge block
- simple lowered `while` with `entry -> cond`, `cond -> body/exit`,
  `body -> cond`, and `exit` returning

Everything else remains unsupported by the explicit pattern fallback. The
default general builder derives phi placement from dominance frontiers and
performs variable renaming with a dominator-tree DFS instead of matching these
local shapes directly.

## Implemented Phase 2

`aether.ssa.SSABuilder` also supports a single acyclic `if`/`else` shape:

```text
entry:
    ...
    branch %cond, then0, else0

then0:
    ...
    jump merge0

else0:
    ...
    jump merge0

merge0:
    ...
    return ...
```

It also accepts the related form where both `then0` and `else0` return directly
and no merge block exists. This keeps early-return `if`/`else` functions in SSA
without introducing unnecessary phi nodes.

Phase 2 promotes slots across the two branches with explicit branch-local state.
This is a local approximation of the later dominance-frontier behavior, not the
general algorithm:

- The entry block produces the incoming slot state.
- The then and else blocks each receive a copy of that state.
- Stores inside a branch update only that branch's slot state.
- At the merge, equal incoming SSA values are reused directly.
- Different incoming SSA values of the same type produce an `SSAPhi` at the
  top of the merge block.
- If only one branch assigns a slot, the previous entry value is used for the
  other branch when it exists.
- If a slot is missing on some path and later loaded, the builder raises
  `SSABuildError`.

Example:

```text
entry:
    %0: int = const 0
    store %y, %0
    %1: bool = cmp_gt %x, %0
    branch %1, then0, else0

then0:
    %2: int = const 1
    store %y, %2
    jump merge0

else0:
    %3: int = const 2
    store %y, %3
    jump merge0

merge0:
    %4: int = load %y
    return %4
```

becomes:

```text
entry:
    %0: int = const 0
    %1: bool = cmp_gt %x, %0
    branch %1, then0, else0

then0:
    %2: int = const 1
    jump merge0

else0:
    %3: int = const 2
    jump merge0

merge0:
    %4: int = phi(then0: %2, else0: %3)
    return %4
```

## Implemented Phase 3

`aether.ssa.SSABuilder` also supports the simple `while` CFG shape produced by
the current IR lowering:

```text
entry:
    ...
    jump cond0

cond0:
    ...
    branch %cond, body0, exit0

body0:
    ...
    jump cond0

exit0:
    ...
    return ...
```

Phase 3 deliberately recognizes this shape directly instead of doing general
dominance-frontier phi placement. Its loop-header phis are a temporary
pattern-specific form of loop-carried renaming. The builder:

- builds the entry block first and records the slot values before the loop
- finds slots stored in the body and read by the condition, by the exit block,
  or before their first body store
- creates one `SSAPhi` per such loop-carried slot at the start of `cond0`
- uses the pre-loop value for the `entry` incoming edge
- uses the final body value for the `body0` incoming edge
- rewrites loads in `cond0`, `body0`, and `exit0` to the correct SSA value
- rejects a loop-carried slot that has no value before the loop

Example:

```text
entry:
    store %n, %n
    jump cond0

cond0:
    %0: int = load %n
    %1: int = const 0
    %2: bool = cmp_gt %0, %1
    branch %2, body0, exit0

body0:
    %3: int = load %n
    %4: int = const 1
    %5: int = sub %3, %4
    store %n, %5
    jump cond0

exit0:
    %6: int = load %n
    return %6
```

becomes:

```text
entry:
    jump cond0

cond0:
    %0: int = phi(entry: %n, body0: %5)
    %1: int = const 0
    %2: bool = cmp_gt %0, %1
    branch %2, body0, exit0

body0:
    %4: int = const 1
    %5: int = sub %0, %4
    jump cond0

exit0:
    return %0
```

The supported loop form is intentionally narrow:

- exactly one simple loop per function
- no nested loops
- no `if` inside the loop body
- no `while` inside an `if`
- no `break` or `continue`; those are rejected by IR lowering before SSA
- no loop CFG with extra predecessors, extra exits, or a body edge that does
  not jump back to the condition block
- no general phi placement or dominance-frontier-based renaming

Any other CFG shape still raises:

```text
SSABuildError(
    "SSA builder phase 3 only supports linear functions, simple acyclic "
    "if/else, and simple while loops."
)
```

That includes nested `if`, nested `while`, multiple merge blocks, merge blocks
with more than two predecessors, and arbitrary branch/jump layouts.

## Current IR State

Aether's experimental IR currently models mutable local state with slots.

A slot is a named storage location for a source-level local variable or
assigned parameter. Instructions write to slots with `IRStore` and read from
slots with `IRLoad`.

Simplified current IR:

```text
entry:
    %0: int = const 1
    store %x, %0
    %1: int = load %x
    %2: int = const 2
    %3: int = add %1, %2
    store %x, %3
    %4: int = load %x
    return %4
```

Meaning:

- `%x` is a mutable slot.
- `store %x, %0` makes the slot hold `%0`.
- `load %x` reads whichever value is currently stored in `%x`.
- Multiple stores can assign the same source variable over time.

This shape is useful for lowering and interpretation, but it hides global
use-definition facts behind memory-like slot operations.

## SSA Goal

The SSA builder should convert promotable slot traffic into direct SSA values.
For scalar local slots that do not escape, `IRStore` and `IRLoad` should
disappear from the SSA form.

Slot IR:

```text
entry:
    %0: int = const 1
    store %x, %0
    %1: int = load %x
    %2: int = const 2
    %3: int = add %1, %2
    store %x, %3
    %4: int = load %x
    return %4
```

SSA:

```text
entry:
    x0: int = const 1
    c0: int = const 2
    x1: int = add x0, c0
    return x1
```

The important change is that uses name values directly. There is no separate
mutable slot read for `x`; each use points to the SSA definition that reaches
it.

Non-promotable state can remain in the lower slot IR until Aether has alias
analysis and a clearer memory model. The first SSA builder should focus on
local scalar slots.

## Initial SSA IR

The SSA package defines a separate model instead of mutating the existing slot
IR in place. The current builder constructs this model for the supported linear
and simple acyclic `if`/`else` subsets. Full CFG-based construction is still
future work.

### SSAModule

`SSAModule` owns the converted SSA functions for one lowered module. It should
preserve module-level metadata needed by later compiler phases, such as source
names, function ordering, and type information.

### SSAFunction

`SSAFunction` represents one function in SSA form. It should contain:

- the function name
- parameter values
- return type
- ordered SSA basic blocks
- an entry block name
- any mapping back to source slots useful for diagnostics

### SSABasicBlock

`SSABasicBlock` represents a basic block after SSA conversion. It should
contain:

- block name
- phi instructions at the top of the block
- ordinary SSA instructions after phi instructions
- one terminator
- predecessor and successor names, or links derived from the CFG

Phi instructions must appear before ordinary instructions because they define
values selected by control-flow entry into the block.

### SSAValue

`SSAValue` is the identity of a single SSA definition. It should carry:

- a stable unique id or printed name
- type
- defining instruction or parameter origin
- optional source slot name for promoted variables

The first implementation can use readable names such as `x0`, `x1`, and `x2`
for promoted locals, plus compiler-generated names for temporary expression
values.

### SSAPhi

`SSAPhi` is the SSA instruction for control-flow merges.

Example:

```text
merge0:
    %x2: int = phi(then0: %x0, else0: %x1)
    return %x2
```

Each phi must define one `SSAValue` and contain one incoming value for each
reachable predecessor of its block.

## Construction Pipeline

The implemented internal pipeline is intentionally smaller than the full SSA
construction algorithm:

```text
Typed AST
  ->
IR Lowering
  ->
IR Verification
  ->
SSA Builder
  ->
SSA Verification
  ->
SSAModule
```

This path is available through `aether.pipeline.lower_to_verified_ssa` and
`aether.pipeline.SSAPipeline`. It accepts either a checked `TypedProgram`, in
which case it lowers and verifies slot IR first, or an `IRModule`, in which case
it verifies the IR before building SSA. The helper defaults to
`builder="general"` and also accepts `builder="pattern"` as a temporary
compatibility fallback. The CLI inspection mode `aether --emit-ssa program.ae`
uses the same pipeline with the general builder by default. The command
`aether --emit-ssa --ssa-builder=pattern program.ae` selects the pattern
fallback explicitly. Both modes then print the exact output of
`aether.ssa.print_ssa`. They do not change IR backend execution, AST backend
execution, language semantics, or optimizer behavior.

The full intended future pipeline is:

```text
Typed AST
  ->
IR Lowering
  ->
CFG
  ->
Dominators
  ->
Dominance Frontier
  ->
Phi Placement
  ->
Variable Renaming
  ->
SSA Verification
```

Pipeline responsibilities:

- `IR Lowering` produces the current verified slot IR.
- `CFG` provides block order, predecessors, successors, and the entry block.
- `Dominators` provide immediate dominators and the dominator tree.
- `Dominance Frontier` identifies merge points for definitions.
- `Phi Placement` inserts phi placeholders for promoted slots.
- `Variable Renaming` rewrites slot loads and stores into SSA values.
- `SSA Verification` checks the resulting SSA invariants.

SSA construction remains a compiler conversion step. The only public connection
is inspection through `aether --emit-ssa`; it should not change the semantics of
the existing slot IR backend.

There is currently no SSA interpreter, no SSA backend, and no SSA optimizer
pipeline.

## Phi Placement

Phi placement is implemented as `aether.ssa.PhiPlacement` and uses the already
implemented dominance frontier analysis.

For each promotable slot:

1. Find the set of blocks that assign the slot with `IRStore`.
2. Initialize a worklist with those definition blocks.
3. For each block `B` removed from the worklist, inspect each block `F` in
   `DF(B)`.
4. If block `F` does not already have a phi for that slot, insert a phi
   placeholder for the slot in `F`.
5. Treat that phi as a new definition of the slot; if `F` was not already in
   the processed definition set, add `F` to the worklist.

This is the standard iterated dominance-frontier algorithm. It inserts the
minimal phi set for the definition blocks under the current CFG and dominance
facts, before pruning any phi that later proves unnecessary.

Initial phi placeholders can be slot-based:

```text
merge0:
    phi %x
```

Variable renaming will later turn the placeholder into a typed SSA definition
with incoming values:

```text
merge0:
    x2: int = phi [then0: x0], [else0: x1]
```

Phi placement should ignore unreachable blocks for the first implementation,
matching the current dominator and dominance-frontier treatment of unreachable
CFG nodes.

The implemented phi-placement phase returns placement information only:

```python
{
    "x": {"merge0"},
    "i": {"cond0"},
    "sum": {"cond0"},
}
```

It does not create `SSAPhi` instructions by itself, change `SSABuilder`, or
affect `--emit-ssa`.

## Variable Renaming

Variable renaming turns promoted slots into versioned SSA values.

The standalone implementation is `aether.ssa.SSARenamer`:

```python
SSARenamer(function, cfg, dominators, phi_placement).rename()
```

It operates per function, consumes the `slot -> blocks` placement dictionary,
and returns an `SSARenameResult` containing an `SSAFunction`. It is tested with
linear code, simple `if`/`else`, loop-carried `while` values, `sumTo`,
nested-if placement, and selected negative cases. It also compares its output
with the current pattern-based builder for linear, simple `if`/`else`, and
simple `while` cases.

This renamer is wired into the default `GeneralSSABuilder`. It is not wired
into the explicit pattern fallback, IR lowering, optimizers, or execution.

The builder should maintain one stack per promoted slot:

```text
%x -> [x0, x1, ...]
%y -> [y0, ...]
```

The renamer walks the dominator tree with DFS, starting from the entry block.
For each block:

1. Rename phi placeholders in the block first.
   Each phi for slot `%x` creates a fresh definition such as `x2` and pushes it
   on `%x`'s stack.
2. Rewrite ordinary instructions in block order.
   A `load %x` is replaced by the current top of `%x`'s stack.
   A `store %x, value` creates a fresh SSA version for `%x`, records that the
   new version is defined by `value`, and pushes it on `%x`'s stack.
3. For each CFG successor, fill that successor's phi operands using the current
   top value for each phi slot.
4. Recursively visit children in the dominator tree.
5. When leaving the block, pop the versions created in this block.

Versioning example for one variable:

```text
x
  ->
x0
  ->
x1
  ->
x2
```

An if/else rewrite should look like:

```text
entry:
    x0: int = const 0
    branch c0, then0, else0

then0:
    x1: int = const 1
    jump merge0

else0:
    x2: int = const 2
    jump merge0

merge0:
    x3: int = phi [then0: x1], [else0: x2]
    return x3
```

The stack discipline ensures every load sees the nearest dominating
definition. The dominator-tree traversal ensures values are available in all
dominated blocks and are removed when the traversal leaves their valid region.

## General Builder

`aether.ssa.GeneralSSABuilder` is the default construction wrapper:

```python
GeneralSSABuilder().build_function(ir_function)
GeneralSSABuilder().build_module(ir_module)
GeneralSSABuilder().build(ir_module)
```

Its implemented pipeline is:

```text
IRFunction
  ->
CFGBuilder
  ->
DominatorAnalysis
  ->
DominanceFrontierAnalysis
  ->
PhiPlacement
  ->
SSARenamer
  ->
SSAFunction
```

`build_module` applies that sequence to each function and verifies the final
`SSAModule` with `SSAVerifier`. The builder wraps construction and verification
failures in `GeneralSSABuildError` while preserving the original message and
exception cause.

This is now the effective SSA builder. It does not alter IR lowering,
optimization, execution, or backend semantics. The pattern-based `SSABuilder`
remains available temporarily for compatibility, comparison, and migration
diagnostics. The CLI selector is available for inspection:

```bash
aether --emit-ssa program.ae
aether --emit-ssa --ssa-builder=general program.ae
aether --emit-ssa --ssa-builder=pattern program.ae
```

`general` is the default when no selector is provided. The intended future is
to retire Pattern once it no longer adds diagnostic or migration value.

## SSA Verification

The initial SSA verifier is implemented as `aether.ssa.SSAVerifier`. It rejects
malformed hand-built SSA modules before any automatic builder or SSA optimizer
exists.

It currently verifies:

- Each `SSAValue` has exactly one definition.
- Function parameters count as definitions.
- Function names, parameter names, and block names are unique in their scopes.
- Each function has at least one block and an `entry` block.
- Each block ends in `SSABranch`, `SSAJump`, or `SSAReturn`.
- Branch and jump targets exist.
- Each phi appears at the start of its block before ordinary instructions.
- Each phi incoming predecessor names a real predecessor of the phi block.
- Phi incoming block names exist and are not duplicated.
- Each phi has at least one incoming value.
- Each used value is defined somewhere in the function.
- Each phi result type matches all incoming value types.
- Each ordinary instruction result type matches its operands and opcode rules.
- Terminator operands are defined and have the expected types.
- Calls target existing SSA functions and match callee arity, argument types,
  and return type.

Future verifier work should add deeper builder-facing invariants:

- Each phi has exactly one incoming edge value per reachable predecessor.
- Each incoming phi value is defined along the corresponding predecessor edge.
- Each non-phi use is dominated by its definition.
- No `IRLoad` or `IRStore` remains for slots promoted into SSA.

The verifier should report block names, value names, and instruction context in
diagnostics so SSA bugs are easy to localize.

## Future Architecture

The SSA implementation lives under a dedicated package:

```text
src/aether/ssa/
    __init__.py
    builder.py
    general_builder.py
    model.py
    optimizer/
        __init__.py
        pipeline.py
        result.py
    phi_placement.py
    printer.py
    renaming.py
    verifier.py
```

Current responsibilities:

- `model.py`: dataclasses or immutable model objects for SSA modules,
  functions, blocks, values, instructions, and phi nodes.
- `printer.py`: deterministic textual SSA output for tests and debugging.
- `verifier.py`: minimum structural, use-definition, phi, call, and type checks
  for manually built SSA.
- `builder.py`: phase-1 conversion from verified linear slot IR into SSA.
  Phase 2 additionally handles simple acyclic `if`/`else` and inserts `SSAPhi`
  nodes in the supported merge block. Phase 3 additionally handles the current
  simple lowered `while` shape and inserts `SSAPhi` nodes in the supported loop
  header.
- `general_builder.py`: default general construction wrapper that uses
  CFG, dominators, dominance frontiers, `PhiPlacement`, `SSARenamer`, and
  `SSAVerifier`.
- `optimizer/`: initial SSA optimizer pipeline infrastructure with
  `SSAOptimizationResult`, `SSAOptimizationTraceStep`, fixed-point iteration,
  convergence errors, and the first real SSA optimization pass:
  `DeadPhiEliminator`. The optimizer is not wired into the CLI or default
  compilation.
- `phi_placement.py`: standalone Cytron-style iterated dominance-frontier phi
  placement for mutable IR slots. This computes `slot -> blocks`.
- `renaming.py`: standalone variable renaming over the dominator tree. It
  consumes `slot -> blocks`, emits an `SSAFunction`, rewrites promotable slot
  loads/stores, and completes phi incoming values.
- `aether.pipeline.SSAPipeline`: internal `TypedProgram`/`IRModule` to verified
  `SSAModule` preparation. It defaults to `builder="general"` and exposes
  `builder="pattern"` as a temporary compatibility fallback.
- `aether --emit-ssa`: CLI inspection mode that uses the verified SSA pipeline
  and textual SSA printer. It defaults to the general builder; use
  `--ssa-builder=pattern` to inspect the compatibility fallback.

The future effective full builder may consume existing analysis results instead
of recomputing CFG or dominators internally. That would keep the construction
step testable and make analysis ownership explicit.

## SSA Optimizer Infrastructure

`aether.ssa.optimizer` now provides SSA optimizer infrastructure plus the first
real SSA optimization pass:

- `SSAOptimizationResult(module, changed, stats)`
- `SSAOptimizationTraceStep(label, module, changed, stats)`
- `SSAOptimizerPipeline(passes=None, iterative=False, max_iterations=10)`
- `DeadPhiEliminator().run(module)`

The default SSA optimizer pipeline currently runs `DeadPhiEliminator`. Running
it on modules without removable phi nodes returns the same `SSAModule`; trace
output records `Initial SSA`, the `DeadPhiEliminator` step, and `Final SSA`
around any custom pass entries. The pipeline supports custom passes and
iterative fixed-point execution for tests and future development, but it is not
connected to the CLI, not used by `--emit-ssa`, and not connected to execution.

Dead Phi Elimination removes only `SSAPhi` instructions whose result has no
uses in the containing function. Uses are collected from binary operands,
compare operands, call arguments, phi incoming values, branch conditions, and
return values. The pass reports `removed_phis` in its stats and intentionally
does not remove constants, arithmetic, comparisons, calls, branches, jumps, or
returns.

Copy propagation, global constant propagation, SCCP, GVN, LICM, and general SSA
dead-code elimination are not implemented yet.

## Future SSA Optimizations

Once SSA construction and verification are stable, these optimizations can be
built on top of SSA:

- Global Constant Propagation: propagate constants across basic blocks using
  direct use-definition chains.
- Copy Propagation: replace uses of trivial copies with their original SSA
  values.
- SCCP: combine sparse conditional reachability with constant propagation
  through branches and phi nodes.
- GVN: reuse equivalent pure computations across dominated regions.
- LICM: move loop-invariant pure computations out of loops using dominance and
  loop information.

These should be introduced one at a time after the SSA model, construction, and
verification rules stay stable. Dead Phi Elimination is intentionally narrow and
does not change current lowering, CLI inspection, or execution semantics.

## Not Implemented Yet

This initial SSA construction milestone does not include:

- changes to the current IR lowering semantics
- changes to the current IR verifier
- changes to the current IR interpreter
- changes to the current optimizer pipeline
- execution from SSA
- phi lowering back to slot IR
- memory SSA
- alias analysis
- aggregate promotion
- SSA copy propagation, global constant propagation, SCCP, GVN, and LICM
- native code generation

A future builder implementation should build SSA as an internal representation
from verified slot IR, verify it, and print or test it independently before any
runtime or optimization behavior depends on it.
