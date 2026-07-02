# Dominators Design for Aether IR

## Status

This document is an initial design note for dominator analysis in the Aether
compiler. It describes the concepts, notation, examples, and first algorithmic
direction needed before implementing SSA construction.

It does not implement dominators, dominance frontiers, SSA conversion, phi
placement, or new optimizations.

## What A Dominator Is

A block `A` dominates a block `B` if every path from the function entry block
to `B` passes through `A`.

This means `A` is unavoidable before reaching `B`. Every block dominates
itself, because every path from entry to `B` that reaches `B` necessarily
passes through `B`.

Dominators are function-local control-flow facts. They are computed from the
control-flow graph (CFG), not from source syntax directly.

## Notation

- `dom(B)`: the set of blocks that dominate block `B`.
- `idom(B)`: the immediate dominator of block `B`.
- dominator tree: the tree formed by connecting each non-entry block to its
  immediate dominator.
- dominance frontier: the set of blocks where dominance by a block stops being
  strict because multiple control-flow paths meet.

## If/Else Example

CFG:

```text
entry -> then
entry -> else
then -> merge
else -> merge
```

As edges:

```text
entry:
    branch cond, then, else

then:
    jump merge

else:
    jump merge

merge:
    return
```

Dominators:

```text
dom(entry) = {entry}
dom(then)  = {entry, then}
dom(else)  = {entry, else}
dom(merge) = {entry, merge}
```

`entry` dominates every block because every path starts there. `then` dominates
only itself: there is a path to `merge` through `else` that does not pass
through `then`. Likewise, `else` dominates only itself. `merge` is dominated by
`entry` and itself, but not by either branch block.

This example is the classic reason SSA needs phi nodes. Values assigned in
`then` and `else` meet at `merge`, but neither branch dominates the merge.

## While Example

CFG:

```text
entry -> cond
cond -> body
cond -> exit
body -> cond
```

As edges:

```text
entry:
    jump cond

cond:
    branch cond_value, body, exit

body:
    jump cond

exit:
    return
```

Dominators:

```text
dom(entry) = {entry}
dom(cond)  = {entry, cond}
dom(body)  = {entry, cond, body}
dom(exit)  = {entry, cond, exit}
```

Relevant facts:

- `entry` dominates every block.
- `cond` dominates `body` because the only way to enter the loop body is
  through the loop condition.
- `cond` dominates `exit` because exiting the loop requires evaluating the
  loop condition.
- `body` does not dominate `cond`, even though there is a back edge from
  `body` to `cond`, because the first path from `entry` to `cond` does not pass
  through `body`.
- `body` does not dominate `exit`, because the loop can exit immediately from
  `cond`.

Loop headers are important for SSA because loop-carried values usually need phi
nodes in the header block.

## Immediate Dominator

The immediate dominator, written `idom(B)`, is the closest strict dominator of
`B`.

A strict dominator of `B` is any dominator of `B` other than `B` itself. The
immediate dominator is the strict dominator that is nearest to `B` in the
dominance relation.

For the `if/else` example:

```text
idom(then)  = entry
idom(else)  = entry
idom(merge) = entry
```

For the `while` example:

```text
idom(cond) = entry
idom(body) = cond
idom(exit) = cond
```

The entry block has no immediate dominator.

## Dominator Tree

The dominator tree is formed by connecting each non-entry block to its
immediate dominator.

For the `while` example, the tree is:

```text
entry
  cond
    body
    exit
```

This tree is not the same thing as the CFG. The CFG describes possible runtime
control flow. The dominator tree describes unavoidable control-flow structure
from the perspective of the entry block.

SSA renaming commonly walks the dominator tree. That traversal lets the
compiler maintain the current SSA name for each variable while entering and
leaving dominated regions.

## Initially Chosen Algorithm

Aether should initially use the classic iterative dominator algorithm. It is
simple, easy to test, and appropriate for Aether v0's current IR size and
compiler maturity.

Initialization:

```text
dom(entry) = {entry}
dom(B) = all blocks, for every B != entry
```

Iteration:

```text
dom(B) = {B} union intersection(dom(P) for each predecessor P of B)
```

Repeat the iteration for all non-entry blocks until no `dom(B)` set changes.
That fixed point is the dominator solution.

Aether should not start with Lengauer-Tarjan. Lengauer-Tarjan is faster on very
large graphs, but it is more complex to implement and validate. The iterative
algorithm is enough for Aether v0 and gives the compiler a clear baseline
before optimizing the analysis itself.

Important implementation notes for the future:

- Run the analysis per function.
- Use the existing CFG as the source of predecessors and blocks.
- Treat unreachable blocks deliberately; either exclude them from the reachable
  CFG view or define their behavior explicitly in the analysis.
- Keep the result deterministic for stable tests and debug output.

## Dominance Frontier

The dominance frontier of a block `A` contains blocks where values defined
under `A` may meet values defined through other paths.

Intuitively, dominance frontier marks the boundary where `A` no longer
strictly controls all incoming flow.

In the `if/else` CFG:

```text
entry -> then
entry -> else
then -> merge
else -> merge
```

The `merge` block is in the dominance frontier of `then`, because `then`
dominates itself and reaches `merge`, but `then` does not dominate `merge`.
Likewise, `merge` is in the dominance frontier of `else`.

That is exactly where SSA may need a phi node:

```text
then:
    x1 = ...
    jump merge

else:
    x2 = ...
    jump merge

merge:
    x3 = phi [then: x1], [else: x2]
```

Dominance frontier does not by itself create phi nodes. It tells the SSA
construction algorithm where phi nodes may be required for variables assigned
in multiple control-flow regions.

## Relationship With SSA

SSA construction depends on three earlier pieces:

- CFG construction
- dominator analysis
- dominance frontier computation

Dominators help with SSA renaming. During renaming, the compiler can walk the
dominator tree and keep a stack of current names for each source variable or
promoted slot. A use can be rewritten to the current top SSA name because the
dominator walk respects where definitions are valid.

Dominance frontier helps with phi placement. If a variable is assigned in a
block, the variable may need phi nodes in that block's dominance frontier. The
algorithm repeats this process because newly inserted phi nodes are themselves
definitions that can require further merge points.

For Aether, the expected path is:

```text
slot IR -> CFG -> dominators -> dominance frontier -> phi placement -> SSA renaming
```

This keeps SSA as a later compiler form built on verified slot-based IR.

## Initial Limitations

The first dominator work should stay deliberately narrow:

- analysis is per function
- no interprocedural dominance
- no advanced exception-control-flow modeling
- no optimizer changes yet
- simple loops first
- no SSA conversion in the dominator change itself
- no phi placement in the dominator change itself

The immediate practical goal is to make control-flow facts reliable and tested.
SSA construction and global optimizations can build on that later.
