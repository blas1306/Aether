# Sparse Conditional Constant Propagation

This document describes the design for Sparse Conditional Constant Propagation
(SCCP) over Aether SSA.

Phases 1 and 2 are implemented in `aether.ssa.optimizer.sccp`. Phase 1
computes lattice state per SSA value, executable blocks, and executable
control-flow edges for one function at a time. Phase 2 consumes those facts
and rewrites proven constant producers to `SSAConst`. SCCP is still not
connected to the SSA optimizer pipeline, CLI SSA export, or execution.

## Overview

Sparse Conditional Constant Propagation combines several related ideas:

- constant propagation through SSA values
- reachability analysis for basic blocks and control-flow edges
- simplification of branches whose conditions become known constants
- later dead-code cleanup after constants and branches have been simplified

Unlike a purely local constant folder, SCCP reasons over the reachable part of
the control-flow graph. Unlike unconditional global constant propagation, it
does not need to merge values from paths proven not to execute. This is the
main advantage for phi nodes and branch-heavy code: constants can survive
through a merge when all executable incoming edges agree, even if unreachable
incoming edges carry different values.

The current Aether implementation is per function and uses the existing SSA
analysis infrastructure in `aether.ssa.analysis`.

## Value Lattice

SCCP tracks one lattice state for each SSA value:

- `Unknown`: no useful information is known yet.
- `Constant(value)`: the SSA value is known to have one concrete constant.
- `Overdefined`: the value is reachable but cannot be represented as one
  constant.

The initial value state for most SSA results is `Unknown`. Function parameters
start as `Overdefined` because, without interprocedural information, their
runtime values are not known. `SSAConst` results start as `Constant(value)`.

Merge rules:

- `Unknown.merge(Unknown) -> Unknown`
- `Unknown.merge(Constant(x)) -> Constant(x)`
- `Constant(x).merge(Unknown) -> Constant(x)`
- `Constant(x).merge(Constant(x)) -> Constant(x)`
- `Constant(x).merge(Constant(y)) -> Overdefined` when `x != y`
- `Constant(x).merge(Overdefined) -> Overdefined`
- `Overdefined.merge(anything) -> Overdefined`

The lattice intentionally does not assume any concrete constant type beyond
the stored value. Future states can extend this domain with ranges, nullness,
type refinements, or aggregate facts without changing the core SCCP structure.

## Block And Edge State

SCCP must also track control-flow reachability. At minimum, each basic block
has an executable state:

- `Not executable`: no executable predecessor has reached the block yet.
- `Executable`: at least one executable control-flow path reaches the block.

For phi handling, the implementation should also track executable edges, not
only executable blocks. A block can be executable while only some predecessor
edges into it are executable. Phi evaluation must use that edge-level
information.

The entry block of each analyzed function starts as executable. Other blocks
start as not executable and become executable when SCCP marks an incoming edge
as executable.

## Worklists

SCCP is an iterative sparse analysis. It should use separate worklists for
different kinds of propagation:

- an instruction or value worklist for SSA instructions whose operands or
  result lattice states may have changed
- an executable edge or block worklist for control-flow edges and newly
  executable blocks

The existing `Worklist` in `aether.ssa.analysis.worklist` is suitable for
these queues because it suppresses duplicates while an item is already queued.
That keeps the analysis from repeatedly processing the same item before new
information exists, while still allowing an item to be requeued after it has
been popped and more facts have changed.

When a value state changes, users of that value should be scheduled. When an
edge becomes executable, the target block should be scheduled and phi nodes in
the target block should be reevaluated because a new incoming edge may now
matter.

## Evaluating SSA Instructions

The analysis phase should interpret SSA instructions abstractly. It should
never execute user code and should not rewrite the module directly.

### SSAConst

`SSAConst(result, value)` defines `result` as `Constant(value)`. Phase 1 also
initializes constant results this way before the worklist reaches their
containing block.

### SSABinaryOp

`SSABinaryOp` evaluates when its containing block is executable:

- if either operand is `Unknown`, the result remains `Unknown`
- if both operands are `Constant`, try to evaluate the operation with the same
  safety rules as SSA constant folding
- if evaluation succeeds, the result becomes `Constant(value)`
- if evaluation is unsupported or unsafe, the result becomes `Overdefined`
- if any operand is `Overdefined`, the result becomes `Overdefined`

Division, modulo, and remainder by zero should not be folded. In the initial
implementation, those cases should become `Overdefined` rather than assuming
undefined control-flow behavior.

### SSACompareOp

`SSACompareOp` follows the same shape as binary operations:

- unknown operands keep the result `Unknown`
- two constant operands can produce `Constant(True)` or `Constant(False)`
- unsupported comparisons or overdefined operands produce `Overdefined`

### SSAPhi

`SSAPhi` merges only incoming values from executable predecessor edges.
Incoming values from non-executable edges are ignored.

If no incoming edge is executable yet, the phi result remains `Unknown`. If
one executable incoming value is constant and every other executable incoming
value agrees, the phi result remains that `Constant(value)`. If executable
incoming values disagree, or any executable incoming value is `Overdefined`,
the phi result becomes `Overdefined`.

This edge-sensitive phi behavior is the key difference between SCCP and a
more conservative global constant propagation pass.

### SSABranch

`SSABranch(condition, true_target, false_target)` updates executable edges
according to the condition lattice state. Branch handling is described in more
detail below.

The branch instruction itself does not define an SSA value.

### SSAJump

`SSAJump(target)` marks the edge from the current block to `target` as
executable when the current block is executable.

### SSAReturn

`SSAReturn(value)` does not produce a new lattice value. If a return value is
present, evaluating the return should read that value's current lattice state
only to ensure uses are accounted for by the worklist graph. The initial
per-function SCCP pass should not infer caller facts from return values.

### SSACall

`SSACall` should be treated conservatively. If the call has a result and the
containing block is executable, the result becomes `Overdefined`.

The current SCCP implementation does not attempt interprocedural constant
propagation, builtin evaluation, effect analysis, or call removal.

## Branch Handling

SCCP marks successor edges based on the branch condition:

- `Constant(True)`: mark only the true edge executable.
- `Constant(False)`: mark only the false edge executable.
- `Overdefined`: mark both true and false edges executable.
- `Unknown`: do not mark new edges yet.

The `Unknown` case is deliberately patient. The analysis waits for more
information instead of prematurely assuming both successors are executable.
If the condition later changes to a constant or `Overdefined`, the branch is
reevaluated and the appropriate edge or edges are marked executable.

Once an edge is executable, it stays executable. SCCP facts move monotonically:
value states can move from `Unknown` to `Constant` or `Overdefined`, and from
`Constant` to `Overdefined`; executable edges and blocks are only added.

## Phi Handling

Phi nodes must consider only incoming edges from executable predecessors.
For example:

```text
merge0:
    %x = phi(then0: %a, else0: %b)
```

If only `then0 -> merge0` is executable, `%x` should be evaluated from `%a`
alone. The value on `else0 -> merge0` must not force `%x` to `Overdefined`
until that edge becomes executable.

When a new predecessor edge becomes executable, every phi in the target block
should be scheduled again. When an incoming value changes, the phi that uses
it should also be scheduled.

## Constant Transformation

After the analysis reaches a fixed point, `SCCPTransformer` can rewrite the
SSA module using the collected facts. The implemented phase 2 transformation is
deliberately narrow:

- `SSABinaryOp`, `SSACompareOp`, and `SSAPhi` producers whose result state is
  `Constant(value)` are replaced with `SSAConst(result, value)`.
- The replacement preserves the exact same `SSAValue` result, including its
  type, so existing uses remain valid and no operand rewriting is needed.
- Calls, branches, jumps, returns, and existing constants are not rewritten by
  SCCP phase 2.
- Phi replacements preserve verifier-friendly phi placement by keeping any
  remaining `SSAPhi` instructions at the start of the block and placing
  materialized constants after them.
- The transformer reports `replaced_constants`.

The CFG is intentionally left intact:

- Branches with constant conditions are not simplified to `SSAJump` yet.
- Blocks not marked executable should remain structurally present in the
  initial implementation. Full removal belongs to a future unreachable-block
  elimination pass.
- Existing or future dead-code elimination should clean up unused constants,
  obsolete computations, and dead phis after SCCP rewrites expose them.

The analysis and transformation phases are intentionally separable. Phase
separation makes it easier to test lattice results and reachable blocks
without coupling those tests to rewriting details.

## Current Limitations

The current SCCP implementation is deliberately narrow:

- per-function only
- no interprocedural propagation
- calls produce `Overdefined`
- no side-effect analysis
- no builtin evaluation
- no complete CFG simplification yet
- no unreachable-block elimination in the SCCP pass itself
- no branch pruning or replacement of constant branches with jumps
- no operand/use rewriting beyond replacing selected producers with `SSAConst`
- no integration with SSA optimization from the CLI yet

These limits keep SCCP independent of execution, backend selection, and the
current IR optimizer pipeline.

## Implementation Plan

### Phase 1: Analysis

Implement an SCCP analyzer that returns:

- lattice state per SSA value
- executable blocks
- executable control-flow edges

This phase should not mutate the input module. It should use the existing
lattice and worklist infrastructure and should have focused tests for value
states, branch reachability, and phi behavior.

### Phase 2: Constant Transformation

Implemented. `SCCPTransformer` consumes an `SSAModule` and an `SCCPResult`,
then replaces `SSABinaryOp`, `SSACompareOp`, and `SSAPhi` producers whose
result state is `Constant(value)` with `SSAConst(result, value)`. It preserves
the original result value and type, avoids CFG changes, and returns an
`SSAOptimizationResult` with `replaced_constants`.

### Phase 3: Branch Simplification

Extend the transformation pass to replace branches with constant conditions by
`SSAJump` to the known successor. Non-executable successor blocks may still
remain in the function until a later CFG cleanup pass exists.

### Phase 4: Future Unreachable Elimination

Add a separate unreachable-block elimination pass once CFG rewriting,
successor/predecessor updates, phi incoming cleanup, and verifier expectations
are ready. This should be independent from the initial SCCP analysis so it can
also serve other analyses and simplifications.

## Non-Goals

SCCP currently does not change the existing SSA optimizer pipeline, the SSA
builder, the CLI, execution behavior, the verifier, or the current local SSA
optimizations. Branch simplification, CFG cleanup, and unreachable-block
elimination remain future work.
