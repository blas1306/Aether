# SSA Design for Aether IR

## Status

This document is an initial design note. It describes why Aether should grow a
Static Single Assignment (SSA) form, how that form relates to the current IR,
and what compiler analyses are needed first.

It does not implement SSA. Dominator analysis now exists in
`aether.analysis.dominators`, and dominance frontier computation exists in
`aether.analysis.dominance_frontier`; phi insertion, SSA renaming, and new
optimizer passes remain pending.

## What SSA Is

Static Single Assignment is an intermediate representation discipline where
each logical value is assigned exactly once.

In a mutable source language, the same variable can be assigned many times:

```aether
int x = 1;
x = x + 1;
x = x * 2;
```

In SSA, each assignment becomes a new versioned value:

```text
x0 = 1
x1 = x0 + 1
x2 = x1 * 2
```

The original source variable `x` still exists at the language level, but the
compiler works with a graph of immutable value definitions. Every use points to
one definition, which makes data flow explicit.

## Why Aether Needs SSA

Aether already has:

- a production AST backend
- an experimental IR backend
- IR lowering, verification, and interpretation
- local optimization passes
- control-flow graph emission

The current optimizer can do useful local work, but it is limited by the IR's
mutable slot model. Global reasoning across branches, loops, and basic blocks
requires knowing which definition reaches each use. SSA makes that information
direct.

SSA is especially important before Aether grows a stronger native backend. A
native code generator, register allocator, and global optimizer all benefit
from an IR where values, uses, and control-flow merges are explicit.

## Relationship With The Current Slot-Based IR

The current experimental IR represents variables and assigned parameters using
mutable slots:

```text
%0: int = const 1
store %x, %0
%1: int = load %x
%2: int = const 2
%3: int = add %1, %2
store %x, %3
%4: int = load %x
return %4
```

This shape is simple to lower from Aether v0 and easy to interpret. It also
matches source-language mutation closely.

SSA should be treated as a later compiler form derived from this lower-level
slot/load/store IR, not as a replacement for the initial lowering boundary.
That gives Aether a conservative pipeline:

```text
AST -> checked AST -> slot IR -> verified slot IR -> CFG -> SSA IR -> SSA opts
```

The first SSA conversion can focus on scalar local slots whose addresses do not
escape. More complex memory-like state can remain in slots until Aether has
alias analysis, aggregate lowering, and a clearer memory model.

## Phi Nodes

A phi node represents a value that depends on which predecessor block control
flow came from.

Consider:

```aether
int main() {
    int x = 0;

    if x == 0 {
        x = 1;
    } else {
        x = 2;
    }

    return x;
}
```

After the `if`, the final value of `x` is either `1` or `2`. SSA cannot reuse
the same mutable `x`, so the merge block needs a phi:

```text
entry:
    branch %cond, then0, else0

then0:
    x1 = const 1
    jump merge0

else0:
    x2 = const 2
    jump merge0

merge0:
    x3 = phi [then0: x1], [else0: x2]
    return x3
```

The phi says: if execution entered `merge0` from `then0`, use `x1`; if it
entered from `else0`, use `x2`.

Phi nodes are not ordinary runtime function calls. They are compiler IR nodes
that describe control-flow-dependent value selection.

## If/Else Example

Source:

```aether
int main() {
    int x = 10;

    if x > 0 {
        x = x + 1;
    } else {
        x = x - 1;
    }

    return x;
}
```

Current slot-style IR shape, simplified:

```text
entry:
    %0 = const 10
    store %x, %0
    %1 = load %x
    %2 = const 0
    %3 = cmp_gt %1, %2
    branch %3, then0, else0

then0:
    %4 = load %x
    %5 = const 1
    %6 = add %4, %5
    store %x, %6
    jump merge0

else0:
    %7 = load %x
    %8 = const 1
    %9 = sub %7, %8
    store %x, %9
    jump merge0

merge0:
    %10 = load %x
    return %10
```

Possible SSA shape:

```text
entry:
    x0 = const 10
    c0 = const 0
    c1 = cmp_gt x0, c0
    branch c1, then0, else0

then0:
    one0 = const 1
    x1 = add x0, one0
    jump merge0

else0:
    one1 = const 1
    x2 = sub x0, one1
    jump merge0

merge0:
    x3 = phi [then0: x1], [else0: x2]
    return x3
```

The important difference is that the final `return` no longer loads from a
mutable slot. It returns the specific merged SSA value `x3`.

## While Example

Source:

```aether
int sumTo(int n) {
    int i = 0;
    int acc = 0;

    while i <= n {
        acc = acc + i;
        i = i + 1;
    }

    return acc;
}
```

Loops need phi nodes in the loop header because each loop-carried value has two
possible sources:

- the initial value from before the loop
- the updated value from the previous iteration

Possible SSA shape:

```text
entry:
    n0 = param n
    i0 = const 0
    acc0 = const 0
    jump cond0

cond0:
    i1 = phi [entry: i0], [body0: i2]
    acc1 = phi [entry: acc0], [body0: acc2]
    c0 = cmp_le i1, n0
    branch c0, body0, exit0

body0:
    acc2 = add acc1, i1
    one0 = const 1
    i2 = add i1, one0
    jump cond0

exit0:
    return acc1
```

The header phi nodes model the loop-carried state. On the first visit to
`cond0`, `i1` is `i0` and `acc1` is `acc0`. On later visits, they are the
values produced by the previous `body0` iteration.

## Analyses Needed Before SSA

SSA construction depends on several control-flow analyses.

### Control-Flow Graph

A CFG is a graph of basic blocks and control-flow edges. Aether already has
initial function-local CFG infrastructure and DOT emission.

SSA construction should use the CFG as the structural source of truth:

- blocks are SSA placement and renaming units
- predecessor lists drive phi operands
- successor lists drive traversal and validation

### Dominators

A block `A` dominates block `B` when every path from the function entry to `B`
must pass through `A`.

Dominance is the core relation used to prove that a value definition is
available at a use. If definition `d` dominates use `u`, then all executions
that reach `u` must have passed through `d`.

### Immediate Dominators

The immediate dominator of a block is its closest strict dominator. It is the
parent relation used to build the dominator tree.

For each block except the entry block, there should be exactly one immediate
dominator in a reachable CFG.

### Dominator Tree

The dominator tree organizes blocks by immediate-dominator parentage.

SSA renaming usually walks this tree. During that walk, the compiler maintains
a stack of current SSA names for each source slot. When entering a block, new
definitions push names; uses read the current top name; when leaving the block,
definitions are popped.

### Dominance Frontier

The dominance frontier of a block identifies where definitions from different
control-flow paths may meet.

Phi insertion uses dominance frontiers. If a slot is assigned in block `A`, phi
nodes for that slot may be needed in blocks in `A`'s dominance frontier. The
algorithm repeats until all required merge points are covered.

Aether already has this analysis as a prerequisite for SSA construction. The
current frontier result is a control-flow fact only; it does not insert phi
nodes or rename variables.

## Optimizations Enabled By SSA

### Global Constant Propagation

In slot IR, a `load %x` may have many possible reaching stores. In SSA, each
use names the exact definition or a phi that combines definitions.

That makes it much easier to propagate constants across blocks:

```text
x1 = const 4
x2 = add x1, x1
```

can become:

```text
x1 = const 4
x2 = const 8
```

For phi nodes, propagation can reason over all incoming values. A phi whose
incoming values are all the same constant can become that constant.

### Copy Propagation

SSA makes copies explicit:

```text
y1 = x1
z1 = add y1, c1
```

can become:

```text
z1 = add x1, c1
```

Because SSA values are immutable, replacing uses of `y1` with `x1` is usually a
local use-def rewrite rather than a memory reasoning problem.

### Common Subexpression Elimination

SSA helps identify repeated pure expressions:

```text
a1 = add x1, y1
a2 = add x1, y1
```

If the operation is pure and the operands are the same SSA values, the second
expression can reuse the first result:

```text
a1 = add x1, y1
a2 = a1
```

or all uses of `a2` can be rewritten to `a1`.

### Dead Code Elimination

In SSA, unused pure definitions are easy to find: if an instruction defines a
value with no uses and has no side effects, it can be removed.

This is stronger than local dead-code elimination because use lists naturally
span the whole function. Phi nodes also become removable when their results are
unused.

### Future Native Backend

A future native backend can use SSA as a bridge from high-level IR to machine
code:

- SSA values approximate virtual registers.
- Use-def chains help instruction selection and scheduling.
- Phi nodes can later be lowered into block-edge copies or parallel copies.
- Global optimization can run before register allocation.
- Type information attached to SSA values can guide ABI and machine
  instruction choices.

SSA is not a complete native backend by itself, but it is a strong intermediate
form for building one.

## What Is Not Implemented Yet

This document intentionally does not add:

- phi placement
- SSA renaming
- SSA verification
- SSA textual printing
- SSA optimizer passes
- memory SSA
- alias analysis
- loop analysis
- register allocation
- native code generation
- changes to the current AST backend
- changes to the current IR backend
- changes to tests or benchmarks

The next practical compiler step is to build phi placement on top of the
existing CFG, dominator, and dominance-frontier analyses. SSA conversion should
come after that foundation is stable.
