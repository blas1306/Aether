# SSA Construction Plan for Aether IR

## Status

This document specifies how Aether should construct SSA from the current
slot-based IR. It is an implementation plan, not an introductory SSA design
note.

No code is implemented by this document. The current compiler still lowers to
slot IR, verifies slot IR, interprets slot IR, and runs the existing local
optimizer pipeline over slot IR.

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

## Proposed SSA IR

The future SSA package should define a separate model instead of mutating the
existing slot IR in place.

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

### IRPhi

`IRPhi` should be the SSA instruction for control-flow merges.

Example:

```text
merge0:
    x2: int = phi [then0: x0], [else0: x1]
    return x2
```

Each phi must define one `SSAValue` and contain one incoming value for each
reachable predecessor of its block.

## Construction Pipeline

The full intended pipeline is:

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

SSA construction should be a compiler-internal conversion step. It should not
change the CLI or the semantics of the existing slot IR backend when first
introduced.

## Phi Placement

Phi placement should use the already implemented dominance frontier analysis.

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

## Variable Renaming

Variable renaming turns promoted slots into versioned SSA values.

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

## SSA Verification

The SSA verifier should reject malformed SSA before any SSA optimizer runs.

It should verify:

- Each `SSAValue` has exactly one definition.
- Function parameters count as definitions.
- Each phi appears at the start of its block before ordinary instructions.
- Each phi has exactly one incoming edge value per reachable predecessor.
- Each phi incoming predecessor names a real predecessor of the phi block.
- Each incoming phi value is defined along the corresponding predecessor edge.
- Each non-phi use is dominated by its definition.
- Each phi result type matches all incoming value types.
- Each ordinary instruction result type matches its operands and opcode rules.
- Terminator operands are defined and have the expected types.
- No `IRLoad` or `IRStore` remains for slots promoted into SSA.

The verifier should report block names, value names, and instruction context in
diagnostics so SSA bugs are easy to localize.

## Future Architecture

The future SSA implementation should live under a dedicated package:

```text
src/aether/ssa/
    model.py
    builder.py
    verifier.py
    printer.py
```

Suggested responsibilities:

- `model.py`: dataclasses or immutable model objects for SSA modules,
  functions, blocks, values, instructions, and phi nodes.
- `builder.py`: conversion from verified slot IR plus CFG, dominators, and
  dominance frontiers into SSA.
- `verifier.py`: structural, dominance, phi, and type checks for SSA.
- `printer.py`: deterministic textual SSA output for tests and debugging.

The builder should consume existing analysis results instead of recomputing CFG
or dominators internally. That keeps the construction step testable and makes
analysis ownership explicit.

## Future SSA Optimizations

Once SSA construction and verification are stable, these optimizations can be
built on top of SSA:

- Global Constant Propagation: propagate constants across basic blocks using
  direct use-definition chains.
- Copy Propagation: replace uses of trivial copies with their original SSA
  values.
- CSE: reuse equivalent pure expressions with the same operands.
- SCCP: combine sparse conditional reachability with constant propagation
  through branches and phi nodes.
- LICM: move loop-invariant pure computations out of loops using dominance and
  loop information.

These should not be introduced in the initial SSA construction change. The
first milestone is correct SSA form plus a verifier.

## Not Implemented Yet

The SSA construction milestone should not include:

- changes to the current IR lowering semantics
- changes to the current IR verifier
- changes to the current IR interpreter
- changes to the current optimizer pipeline
- new CLI flags
- execution from SSA
- phi lowering back to slot IR
- memory SSA
- alias analysis
- aggregate promotion
- global optimizations
- native code generation

The first implementation should build SSA as an internal representation from
verified slot IR, verify it, and print or test it independently before any
runtime or optimization behavior depends on it.
