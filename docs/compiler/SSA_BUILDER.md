# General SSA Builder for Aether IR

## Status

This document is the operational plan for migrating Aether from the current
pattern-based SSA builder to a general SSA builder based on the classic SSA
construction algorithm.

The first three migration steps are implemented as isolated infrastructure:
`aether.ssa.PhiPlacement` computes general iterated dominance-frontier phi
locations for mutable IR slots, and `aether.ssa.SSARenamer` performs
function-local dominator-tree variable renaming from those placements.
`aether.ssa.GeneralSSABuilder` now wires those phases together into an
experimental per-module builder and verifies the resulting SSA module.

These phases are still experimental. The pattern-based `SSABuilder` remains the
default builder used by the SSA pipeline and `--emit-ssa`; the general builder
is available only through an explicit inspection selector and does not replace
the default yet.

## Regression Validation

The general builder is continuously validated against the pattern-based builder
through a repository regression suite over the checked-in Aether example
programs. The suite discovers `.ae` programs under the example and benchmark
trees, lowers the currently supported subset to verified IR, and then attempts
SSA construction with both builders.

When the pattern builder accepts a program, the general builder must also
accept it, the resulting SSA must pass `SSAVerifier`, and the two modules must
match on structural properties rather than exact text: function sets,
signatures, block names, terminator shapes, return types, absence of load/store
traffic, and phi counts per block.

Programs outside the current pattern builder subset are tracked as
non-comparable for the purpose of this migration. It is acceptable for the
general builder to accept additional CFG shapes before the default changes, but
the builder default will only move from `pattern` to `general` once the
regression suite shows no pattern-supported regressions.

## Current State

Aether already has the compiler infrastructure needed to make general SSA
construction possible:

- mutable slot-based IR
- control-flow graph construction
- dominator analysis
- dominance-frontier analysis
- SSA model, printer, and verifier
- a pattern-based SSA builder
- standalone general phi placement for mutable slots
- standalone experimental DFS renaming for mutable slots
- experimental general SSA builder using phi placement plus renaming

The current `SSABuilder` supports deliberately small CFG shapes:

- linear functions
- simple acyclic `if`/`else`
- simple `while` loops

This was useful because it validated the SSA model, textual printer, verifier,
pipeline integration, and the basic slot-promotion rules before introducing the
full algorithm. It does not scale to general CFGs. Every new CFG shape would
require another recognizer, and interactions between nested branches, multiple
merge blocks, loops, and arbitrary jumps quickly become harder to maintain than
the standard SSA construction algorithm.

The general builder should replace shape recognition with CFG analysis,
dominance frontiers, phi placement, and dominator-tree variable renaming.

## Goal

The builder converts one verified mutable IR module into one verified SSA
module.

Input:

```text
Mutable IR
```

Output:

```text
SSA Module
```

Pipeline:

```text
IR
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

The result should preserve function order, parameter information, return types,
block names where practical, and enough source slot information for useful
diagnostics.

## General Rules

The general builder operates per function. Each function receives its own CFG,
dominator tree, dominance frontier, phi-placement state, and renaming stacks.

Mutable IR slots are the first class of promotable variables. A slot is
promotable when it represents local scalar state that can be converted from
load/store traffic into direct SSA values.

`IRStore(slot, value)` defines a new logical version of that slot. In SSA, the
store itself normally disappears and the slot's current version becomes the SSA
value derived from `value`.

`IRLoad(slot)` is replaced by the current visible SSA version of that slot. The
load itself normally disappears from the SSA output.

Temporary values in the current IR are already SSA-like: each temporary result
is defined once and can be copied or converted directly into the SSA model. The
builder should preserve these values as ordinary SSA definitions unless their
uses are rewritten through slot promotion.

`IRPhi` or `SSAPhi` appears only where multiple logical versions of a promoted
slot join at a CFG merge point. Phi placement is per slot or source variable,
not per temporary.

## Phi Placement

Phi placement uses the dominance frontier for each function.

For each promotable slot:

1. Find every basic block where the slot receives an `IRStore`.
2. Initialize a worklist with those definition blocks.
3. Remove a block from the worklist.
4. For each block in that block's dominance frontier, insert a phi placeholder
   for the slot if one does not already exist there.
5. Treat the inserted phi as a new definition of the slot.
6. If that phi block has not already been processed as a definition block for
   the slot, add it to the worklist.
7. Repeat until the worklist is empty.

This is the classic iterated dominance-frontier algorithm. The iteration is
important: a phi inserted at one join point may create a new definition whose
value reaches another join point farther through the CFG.

Phi placement is per slot or source variable. It should not scan temporaries as
variables needing phi nodes, because ordinary IR temporaries already have a
single definition.

Initial phi placeholders can be represented as slot-indexed pending phis:

```text
block merge0 has pending phi for slot %x
```

Variable renaming later turns each placeholder into a typed `SSAPhi` with one
incoming value per predecessor:

```text
%x3: int = phi(then0: %x1, else0: %x2)
```

Implemented API:

```python
PhiPlacement(function, cfg, dominators, dominance_frontier).place()
```

The result is a dictionary keyed by mutable slot name:

```python
{
    "x": {"merge0"},
    "i": {"cond0"},
    "sum": {"cond0"},
}
```

This phase only computes phi locations. It does not create `SSAPhi` nodes or
rewrite loads or stores by itself, and it does not affect the current
pattern-based builder output.

## Variable Renaming

Variable renaming rewrites mutable slot traffic into SSA values.

Implemented experimental API:

```python
SSARenamer(function, cfg, dominators, phi_placement).rename()
```

The result is an `SSARenameResult` containing one `SSAFunction` plus the block
to slot mapping used for emitted phis. This API operates on one function at a
time and is now used by the experimental `GeneralSSABuilder`. It is not
connected to the effective `SSABuilder`; it is reachable from `SSAPipeline` and
`--emit-ssa` only when the caller explicitly selects the experimental
`general` builder.

The builder maintains one stack per promoted slot:

```text
%x -> [%x0, %x1, ...]
%y -> [%y0, ...]
```

The renamer traverses the dominator tree from the function entry block.

Within each block:

1. Rename phi placeholders first.
   Each phi for a slot creates a fresh SSA version and pushes it onto that
   slot's stack.
2. Visit ordinary IR instructions in order.
3. When the builder sees `IRStore(slot, value)`, it creates a new SSA version
   for the slot, maps that version to the already converted SSA value, and
   pushes the new version on the slot stack.
4. When the builder sees `IRLoad(slot)`, it replaces the load result with the
   top value on that slot's stack.
5. Ordinary temporary-producing instructions are converted directly, with their
   operands rewritten through the current value map.
6. For each CFG successor, the builder completes that successor's phi operands
   using the current top value for each phi slot in the successor.
7. The builder recursively visits children in the dominator tree.
8. When leaving the block, it pops every slot version created in the block.

If a load observes an empty stack for its slot, the builder should report a
clear SSA build error. This means the mutable IR uses a slot before a reaching
definition in the promotable subset.

## Experimental General Builder

`aether.ssa.GeneralSSABuilder` is the first complete experimental wrapper for
the general construction path:

```python
GeneralSSABuilder().build_function(ir_function)
GeneralSSABuilder().build_module(ir_module)
GeneralSSABuilder().build(ir_module)
```

For each function it builds a CFG, computes dominators, computes dominance
frontiers, runs `PhiPlacement`, and runs `SSARenamer`. `build_module` then
verifies the whole `SSAModule` with `SSAVerifier`, which keeps calls between
functions valid across module boundaries. `build_function` verifies the single
function wrapped as a one-function module.

Failures from the construction phases are reported as `GeneralSSABuildError`
with the original diagnostic preserved in the message and exception cause.

The CLI exposes this builder for inspection only:

```bash
aether --emit-ssa --ssa-builder=general program.ae
```

The default remains:

```bash
aether --emit-ssa program.ae
aether --emit-ssa --ssa-builder=pattern program.ae
```

The existing pattern-based `SSABuilder` and default `--emit-ssa` CLI path still
produce the same output as before. Selecting `general` does not execute SSA,
does not enable SSA optimizations, and does not change IR lowering or backend
semantics.

## Builder Comparison

The pattern-based builder remains the default for the SSA pipeline and for
`aether --emit-ssa`. The experimental general builder is validated against that
default in the CFG shapes both builders are expected to support.

The comparison suite checks structural properties instead of exact printed SSA
text, because temporary names are not part of the intended contract between the
two builders. For common cases it verifies that both outputs pass
`SSAVerifier`, expose the same functions and signatures, keep the same block
names, remove load/store traffic, produce the same phi counts per function and
block, use equivalent block terminators, and preserve return types.

The shared comparison cases cover:

- linear functions
- arithmetic with parameters
- local store/load promotion
- simple `if`/`else` with a phi
- `if`/`else` with returns in both branches
- simple `while` loops
- `sumTo`-style loops with two phis
- modules with multiple functions and calls

The suite also keeps a stress matrix for larger CFG shapes. Those tests classify
each case as `SUPPORTED`, `PATTERN_ONLY`, `GENERAL_ONLY`, or `UNSUPPORTED`
according to the actual builders today. Unsupported cases are asserted as
current limitations instead of being forced to pass. This documents the current
experimental coverage expansion without changing the default builder, optimizer,
lowering, CLI behavior, or execution semantics.

## Current GeneralSSABuilder Coverage

Legend:

- `✓`: supported by the current test suite
- `✗`: not supported
- `△`: partially supported; see notes

| CFG shape | Pattern | General | Current classification | Notes |
| --- | --- | --- | --- | --- |
| Lineal | ✓ | ✓ | `SUPPORTED` | Both builders produce verifier-clean SSA. |
| If simple | ✓ | ✓ | `SUPPORTED` | Simple acyclic `if`/`else` remains shared coverage. |
| While simple | ✓ | ✓ | `SUPPORTED` | Includes simple loop-carried slots. |
| Nested if | ✗ | ✓ | `GENERAL_ONLY` | General places independent inner and outer merge phis. |
| Nested while | ✗ | △ | `GENERAL_ONLY` / `UNSUPPORTED` | Works when inner-loop slots have visible values on all incoming paths; loop-local slots that trigger dead phis can still fail. |
| If in while | ✗ | ✓ | `GENERAL_ONLY` | General handles loop-header phis plus the inner merge phi. |
| While in if | ✗ | △ | `GENERAL_ONLY` / `UNSUPPORTED` | Works when loop-carried slots are initialized before the branch; branch-local loop slots can still fail due non-liveness-pruned phi placement. |
| Sequential ifs | ✗ | ✓ | `GENERAL_ONLY` | General places separate phis for each merge. |
| Sequential loops | ✗ | ✓ | `GENERAL_ONLY` | General keeps loop-header phis independent across loops. |
| Multiple loop-carried slots | ✓ | ✓ | `SUPPORTED` | Current pattern while support and General both verify three loop-carried phis. |
| Several independent merges | ✗ | ✓ | `GENERAL_ONLY` | General places independent phis for separate merge blocks. |
| Large function | ✗ | ✓ | `GENERAL_ONLY` | Stress case verifies `SSAVerifier`, no load/store traffic, consistent CFG targets, and multiple phis. |
| General CFG | ✗ | △ | `GENERAL_ONLY` / `UNSUPPORTED` | Reducible structured stress CFGs pass; liveness-sensitive phi pruning is not complete. |

## Pseudocode

### `place_phis(function)`

```text
function place_phis(function):
    cfg = build_cfg(function)
    dominators = compute_dominators(cfg)
    dominance_frontier = compute_dominance_frontier(cfg, dominators)

    promoted_slots = collect_promotable_slots(function)
    def_blocks = map slot -> empty set
    placed = map block -> empty set of slots

    for block in function.blocks:
        for instr in block.instructions:
            if instr is IRStore and instr.slot in promoted_slots:
                def_blocks[instr.slot].add(block)

    for slot in promoted_slots:
        worklist = queue(def_blocks[slot])
        seen_defs = set(def_blocks[slot])

        while worklist is not empty:
            block = worklist.pop()

            for frontier_block in dominance_frontier[block]:
                if slot not in placed[frontier_block]:
                    insert_pending_phi(frontier_block, slot)
                    placed[frontier_block].add(slot)

                    if frontier_block not in seen_defs:
                        seen_defs.add(frontier_block)
                        worklist.push(frontier_block)

    return pending_phis
```

### `rename_block(block)`

```text
function rename_block(block):
    pushed_slots = []

    for phi in pending_phis[block]:
        slot = phi.slot
        value = fresh_ssa_value(slot, phi.type)
        emit_phi_definition(block, phi, value)
        slot_stack[slot].push(value)
        pushed_slots.append(slot)

    for instr in block.instructions:
        if instr is IRLoad and instr.slot is promoted:
            value = top(slot_stack[instr.slot])
            value_map[instr.result] = value
            continue

        if instr is IRStore and instr.slot is promoted:
            stored_value = rewrite_value(instr.value, value_map)
            value = fresh_ssa_value(instr.slot, type_of(stored_value))
            bind_slot_version(value, stored_value)
            slot_stack[instr.slot].push(value)
            pushed_slots.append(instr.slot)
            continue

        converted = convert_instruction(instr, value_map)
        emit(converted)
        record_results(converted, value_map)

    for successor in cfg.successors[block]:
        for phi in pending_phis[successor]:
            slot = phi.slot
            incoming = top(slot_stack[slot])
            add_phi_operand(phi, predecessor=block, value=incoming)

    for child in dominator_tree.children[block]:
        rename_block(child)

    for slot in reverse(pushed_slots):
        slot_stack[slot].pop()
```

`bind_slot_version` can be implemented either by making the fresh version alias
the stored SSA value or by emitting an explicit SSA copy-like definition if the
SSA model needs every promoted variable version to have its own defining
instruction. The verifier should define and enforce the final invariant.

## If/Else Example

Mutable IR shape:

```text
entry:
    %0: int = const 0
    store %x, %0
    %1: bool = load_or_compute_condition
    branch %1, then0, else0

then0:
    %2: int = const 1
    store %x, %2
    jump merge0

else0:
    %3: int = const 2
    store %x, %3
    jump merge0

merge0:
    %4: int = load %x
    return %4
```

SSA result:

```text
entry:
    %0: int = const 0
    %1: bool = load_or_compute_condition
    branch %1, then0, else0

then0:
    %x1: int = const 1
    jump merge0

else0:
    %x2: int = const 2
    jump merge0

merge0:
    %x3: int = phi(then0: %x1, else0: %x2)
    return %x3
```

The phi in `merge0` exists because `%x` has distinct reaching versions from
`then0` and `else0`.

## While Example

Mutable IR shape:

```text
entry:
    %0: int = const 0
    store %i, %0
    jump cond0

cond0:
    %1: int = load %i
    %2: int = load %n
    %3: bool = cmp_le %1, %2
    branch %3, body0, exit0

body0:
    %4: int = load %i
    %5: int = const 1
    %6: int = add %4, %5
    store %i, %6
    jump cond0

exit0:
    %7: int = load %i
    return %7
```

SSA result:

```text
entry:
    %i0: int = const 0
    jump cond0

cond0:
    %i1: int = phi(entry: %i0, body0: %i2)
    %3: bool = cmp_le %i1, %n
    branch %3, body0, exit0

body0:
    %5: int = const 1
    %i2: int = add %i1, %5
    jump cond0

exit0:
    return %i1
```

The loop header phi is loop-carried. It receives the initial value from
`entry` and the updated value from the back edge `body0`.

## Relationship With The Current Builder

The migration should be staged so the current pattern-based builder remains
useful while the general builder is brought up.

Phase A:

- keep the pattern-based builder as a fallback or comparison implementation
- keep existing linear, simple `if`/`else`, and simple `while` behavior stable

Phase B:

- implemented: general phi placement runs in parallel with the existing builder
- implemented: unit tests validate pending phi placement against dominance
  frontiers before rewriting all values

Phase C:

- implemented experimentally: dominator-tree DFS variable renaming
- implemented experimentally: promoted slot loads and stores are rewritten
  through per-slot stacks
- implemented experimentally: phi operands are completed for each successor
  during traversal

Phase D:

- implemented experimentally: compare renamer output with pattern-based output
  for supported linear, simple `if`/`else`, and simple `while` cases
- allow harmless naming differences when the SSA verifier and structural checks
  agree

Phase E:

- replace the pattern-based builder as the default implementation
- keep only targeted compatibility helpers that still serve diagnostics,
  testing, or migration clarity

## Validation

Every SSA module produced by the general builder must pass:

- `SSAVerifier`
- existing SSA builder and pipeline tests
- new tests covering general CFG shapes
- comparison against the pattern-based builder for cases it already supports

Validation should include nested branches, multiple merge blocks, loops with
loop-carried values, branches inside loops once supported by lowering, and
unreachable-block behavior consistent with the CFG and dominator analyses.

The builder should fail with clear `SSABuildError` messages when a function
uses a feature outside the supported promotable subset.

## Initial Limitations

The first general builder should stay conservative:

- per-function construction only
- no advanced exception control flow
- no alias analysis
- no complex memory SSA
- scalar slots first
- lists, classes, structs, and aggregate fields remain outside slot promotion
  until Aether has a safe promotion design for them

Non-promotable memory-like state can continue to live in mutable IR until the
compiler has the analyses needed to preserve semantics safely.
