# Aether compiler Rust workspace

This workspace is the isolated home for native Aether compiler components. It
establishes the project structure and development policy only: the production
compiler remains entirely on its existing Python path.

## Crates

- `aether-ir` owns the language-independent Rust representation of Aether IR.
  It contains no verifier, parser, serializer, DTO, or compiler integration.
- `aether-verifier` provides independently callable passes for declaration and
  instruction-local type consistency, function/block structure and basic local
  CFG validity, and function-local SSA definition/use validity in owned Aether
  IR. The SSA pass checks unique parameter/result definitions, exact named
  references, and same-block definition-before-use. The dominance pass then
  checks cross-block uses against an entry-rooted dominator relation. The local
  lifecycle passes provide focused local checks, deterministic inter-block CFG
  state merging, and ownership-completeness checks at every reachable return.
  The all-path return pass independently verifies IRV-024 for non-void
  functions. Phi semantics, cleanup insertion, and optimization verification
  remain outside these passes.
- `aether-python` will provide the eventual Python integration boundary. It does
  not contain PyO3 bindings or compiler integration yet.

The dependency direction will be from integration crates toward core compiler
crates. The core IR crate must not depend on Python.

## Development

The workspace pins its Rust toolchain and keeps shared edition, minimum Rust
version, lint, formatting, and build-profile settings in the workspace root.
Run workspace commands from this directory:

```console
cargo fmt --all --check
cargo clippy --workspace --all-targets --all-features
cargo check --workspace
cargo test --workspace
```

## Phase 3 Step 3C.2: dominance verifier

Step 3C.2 is complete. `verify_module_dominance(&IRModule)` and
`verify_function_dominance(&IRFunction)` are borrowed, non-mutating, independently
callable APIs. The function API invokes only the function-local Step 3B
structural prerequisite and Step 3C.1 SSA prerequisite. It wraps their complete
typed error chains, so direct calls on malformed IR do not construct an
ambiguous CFG or panic. It does not run the type verifier or create a mandatory
all-phases pipeline.

The CFG uses exact block names, the block named exactly `entry` as its root,
successors in terminator field order, and unique predecessors in retained
source-block order. A simple iterative set algorithm computes reachability and
dominators. Diagnostics never depend on map or set iteration: functions,
blocks, instructions, and operands are visited in retained order. Operand
errors retain both their stable ordinal and their instruction field name.

Parameters are entry definitions available throughout the retained function,
including unreachable blocks. Instruction results must dominate every
cross-block ordinary use. Same-block definition-before-use remains Step 3C.1's
responsibility and is not diagnosed a second way. Matching Python SSA verifier
behavior, unreachable blocks are isolated in the entry-rooted dominator result:
a same-block definition/use may pass, but every ordinary cross-block use in an
unreachable block is rejected, including uses within one unreachable cycle.
Reachable uses of unreachable definitions and unreachable uses of reachable
instruction definitions are also rejected.

Python inspection found two distinct systems. The initial-IR verifier uses
forward state intersection for reachable value availability; the explicit
dominator implementation and dominance verifier operate on Python SSA IR. The
Rust owned representation is still the initial-IR enum, but Step 3C.1 already
defines its immutable result values as one function-local SSA namespace, so
Step 3C.2 applies the Python ordinary SSA-use dominance rule to that namespace.
Python SSA has `SSAPhi` with predecessor-edge-sensitive operands. The current
owned Rust `IRInstruction` has no phi-like variant, so this step introduces no
phi abstraction, predecessor-to-phi matching, or edge-sensitive operand rule.

The new typed errors are `ModuleDominanceError`, `FunctionDominanceError`,
`BlockDominanceError`, `DominanceRuleError`, and `DominanceUseLocation`.
`DefinitionDoesNotDominateUse` retains the identifier, exact definition and use
locations, entry block, instruction kind, operand order, and operand field. All
nested `Error::source()` links remain downcastable.

Phi validation, SSA construction/renaming, dominance frontiers, post-dominance,
ownership, borrowing, lifecycle/storage data flow, optimizer invariants,
importer and schema behavior, compiler-pipeline integration, LLVM, and PyO3 are
unchanged. Since no current owned instruction has phi semantics, the next real
verifier step was Phase 3D ownership/lifecycle verification rather than an
empty Step 3C.3.

## Phase 3 Step 3D.1: local storage lifecycle verifier

Step 3D.1 is complete. `verify_module_local_lifecycle(&IRModule)` and
`verify_function_local_lifecycle(&IRModule, &IRFunction)` borrow their inputs,
do not mutate IR, and are independently callable. No prerequisite pass runs:
local lifecycle does not need a valid CFG, SSA namespace, or dominator result,
and nominal lifecycle traits are classified directly from the module's ordered
struct definitions.

Storage is implicit in the owned initial IR rather than declared in a function
slot table. A deterministic index takes its first type from `load`/`store` slot
fields, lifecycle storage fields, or `return.transferred_storage`, and later
uses of the same storage name must retain that type. Parameters and instruction
results remain a separate immutable SSA namespace and begin no storage
lifetime. There are no globals or aggregate-field storage references in the
owned model.

The canonical local effects are:

| instruction | storage precondition | local post-state |
| --- | --- | --- |
| `load slot` | slot must be live when its state is known | unchanged |
| `store slot, value` | none; this is raw initialization/overwrite | initialized |
| `init_default dst` | destination not already live; type supports default | initialized |
| `copy_init dst, source` | destination not already live; storage source live when known; exact source type | destination initialized; source unchanged |
| `move_init dst, src` | distinct storage, destination not live, source live, exact type | destination initialized; source moved |
| `assign dst, source` | destination and any storage source live when known; exact source type | destination initialized; source unchanged |
| `destroy value` | storage live when known | destroyed |
| `relocate dst, src, count` | positive count, distinct storage, destination not live, source live, exact relocatable type | destination initialized; source moved |
| return transfer | transferred storage live, non-void, and exact returned-value type | unchanged at the terminating instruction |

All storage in a block named exactly `entry` begins known `Uninitialized`.
Every other block begins `Unknown`, including retained unreachable blocks.
`Unknown` satisfies neither the live nor invalid predicates: a first load,
assignment, destroy, initialization, move, or relocation is accepted because
its predecessor state is deferred, but the successful local operation creates
a definite fact for following instructions. This catches a local load after
destroy/move, double initialization, assignment or destroy before entry-block
initialization, double destroy, invalid aliases/counts/types, and storage type
conflicts without guessing at predecessor states.

The type classifier mirrors Python's `LifecycleTypeRegistry`: scalar and enum
types are trivial; string and Array/List handles support default and trivial
relocation while retaining managed copy/destroy behavior; Vector default needs
row/column orientation; Matrix is relocatable but has no dimension-free
default; Function is relocatable without a default; structs and method results
compose recursively; ClassRef/Interface/Nullable currently have no defined
lifecycle layout. Copy, move, assign, and destroy remain valid for both trivial
and managed non-void types. Only default and relocation consult their specific
traits.

Owned `IRCopyInit.source` and `IRAssign.source` use the tagged
`LifecycleSource::{Value, Storage}` representation. Canonical wire `value` and
`parameter` tags import as `Value`; `storage` imports as `Storage`. The SSA pass
therefore checks only immutable sources, while the lifecycle pass checks only
storage-source state. Identifier spelling is never used to infer a namespace,
so same-named SSA and storage entities remain distinct. The canonical JSON and
wire DTO contracts are unchanged.

Predecessor propagation, join merging, loop fixed points, branch consistency,
full move/return ownership, and cleanup on every exit remain deferred. In
particular, loads at merges and loops are accepted from `Unknown`, whether all,
some, or no predecessors initialize the slot. The next step is **Phase 3 Step
3D.2: inter-block lifecycle data flow and CFG state merging**.

## Phase 3 Step 3D.2: inter-block lifecycle data flow

Step 3D.2 is complete. `verify_module_lifecycle(&IRModule)` and
`verify_function_lifecycle(&IRModule, &IRFunction)` preserve the 3D.1 local
APIs and add a forward fixed point over the shared validated CFG. Structure is
the only prerequisite. SSA definitions and dominance remain separate because
the lifecycle domain tracks explicit storage only.

Reachable entry storage starts `Uninitialized`. Block entries join predecessor
exits with a finite powerset of `Uninitialized`, `Initialized`, `Moved`, and
`Destroyed`; union is deterministic, commutative, idempotent, and monotone.
The FIFO worklist is seeded in retained block order, supports entry-not-first,
self-loops, multiple back-edges and duplicate branch targets, and terminates
without widening. Matching Python IRV-022, every retained unreachable block is
checked independently with all collected slots `Initialized`; unreachable
edges do not propagate state between blocks or components.

Propagation and validation share the 3D.1 operation table. The analysis first
converges without diagnostics, then replays blocks in source order. A path-
sensitive precondition must hold for every possible incoming state;
`InvalidMergedState` reports the stable set. Total `store` overwrites any
incoming state, so it can repair a divergent join. Storage-tagged copy/assign
sources are checked; immutable SSA sources and same-spelled storage remain
separate. Managed and trivial types follow the same state flow. For managed
storage this proves only the slot-state transition: a hand-authored raw store
can still leak an overwritten owner or lack the retain required for its input.
Normal lifecycle expansion discharges copy/assign ownership around the raw
stores it emits; complete ownership and leak guarantees remain deferred.

Python's initial-IR verifier was inspected. Its early IRV-036 edge check occurs
during convergence and rejects even join blocks beginning with total `store`;
the Rust pass deliberately fixes this order-sensitive conflict with IRV-034 by
validating after convergence. Python's all-slots-live unreachable seed is a
documented IRV-022 policy, not an inferred executable fact, and Rust reproduces
it exactly in the complete pass. The focused 3D.1 local pass still uses
`Unknown` outside `entry` because it performs no reachability analysis.

Function-exit cleanup/leak guarantees were added by Step 3D.3. Lifecycle
expansion, destruction insertion, ownership/borrow inference, ARC optimization,
importer/schema and owned-IR changes, pipeline integration, LLVM, and PyO3
remain out of scope for Step 3D.2 itself.

## Phase 3 Step 3D.3: function-exit ownership completeness

Step 3D.3 is complete. The existing `verify_module_lifecycle(&IRModule)` and
`verify_function_lifecycle(&IRModule, &IRFunction)` APIs now consume the
stabilized Step 3D.2 exit maps after source-ordered transition validation. They
inspect every entry-reachable block terminated by `return`; jumps and branches
are not function exits, and retained unreachable returns do not create an
executable cleanup obligation. Structural verification continues to reject
implicit fallthrough, so void functions also have explicit return terminators.
The focused 3D.1 local APIs deliberately remain exit-agnostic.

A slot is covered when it participates in generic lifecycle IR
(`init_default`, `copy_init`, `move_init`, `assign`, `destroy`, or `relocate`).
At a reachable return it must be `Uninitialized`, `Moved`, or `Destroyed`, or it
must be the exact live `return.transferred_storage`. Any exit state containing
`Initialized` is incomplete otherwise, including a join such as
`{Initialized, Destroyed}`. Return transfer requires a live non-void slot and a
returned value of exactly the slot type. Matching Python, the verifier does not
infer that the returned SSA value came from that storage; the explicit marker
is the ownership contract. Move and relocation transfer ownership only between
slots: the source becomes `Moved`, the destination becomes `Initialized`, and
only a later return marker can transfer the destination out of the function.

Python applies this completion rule to every lifecycle slot, not only types
whose runtime destructor is non-trivial. Rust therefore requires explicit
completion for trivial `int`, scalar, enum, vector, and matrix lifecycle
storage too. `String`, `Array`, and `List` are managed owners; nominal structs
and method-result storage are managed recursively when any nested field needs
destruction. Destroy ends the entire aggregate slot lifetime; the current IR
has no independently tracked field-storage path, while branch-dependent whole-
aggregate destruction is reported as a mixed terminal state. Parameters and
ordinary temporaries are immutable SSA values, not slots, and are outside this
storage-exit check unless lowering copies them into `IRStorage`. Compiler-owned
temporary-value releases remain lifecycle-expansion behavior after verification.

`LifecycleRuleError::IncompleteOwnershipAtExit` reports the slot name and type,
exit block and return location, actual and expected terminal-state sets,
managed/trivial ownership reason, and the last lifecycle transition retained by
the data-flow fact. `LifecycleStorageRole::ExitOwner` identifies this context,
and `OwnershipCompletionReason` is public. Existing module, function, block,
and rule `Error::source()` chains remain complete and downcastable. Diagnostics
are selected in retained block and lexicographic slot-name order after
convergence, matching Python's sorted missing-cleanup list.

This step is verification only. It does not insert cleanup, rewrite IR, expand
lifecycle operations, infer ownership, perform borrow/alias analysis, optimize
ARC, change the importer/schema, integrate a pipeline, or touch LLVM. The next
recommended verifier work is borrowing/escape completeness and the remaining
non-lifecycle IRV rule families, followed by an explicitly scoped differential
integration phase; cleanup insertion belongs to lowering/lifecycle expansion,
not this verifier.

## Phase 3 Step 3E.1: non-void all-path return verification

Step 3E.1 is complete. `verify_module_returns(&IRModule)` and
`verify_function_returns(&IRFunction)` borrow their inputs and independently
verify IRV-024. Function verification invokes only the Step 3B structural
prerequisite needed to resolve an unambiguous CFG. It does not invoke type, SSA,
dominance, or lifecycle verification and does not add a combined verifier
pipeline.

Void functions are exempt after structural validation. For a non-void
function, analysis begins at the block named exactly `entry`; unreachable
blocks impose no all-path return obligation. A valued `IRReturn` proves the
path, while a valueless `IRReturn` fails it. Jumps follow their target and both
branch targets must prove a return in true-before-false order. This pass checks
only value presence: operand definition, type agreement, storage transfer, and
cleanup remain owned by their existing verifier families.

The pass performs a depth-first reachability walk with a visited-block set.
Cycles are non-exiting paths regardless of block spelling, so they impose no
return obligation by themselves. Block labels other than the structurally
reserved `entry` label are identifiers only; `cond`, `for.cond`, and arbitrary
bijections of non-entry labels have identical semantics. A LIFO worklist visits
true before false targets for deterministic diagnostics.

Python's `_block_returns` is a recursive syntactic approximation, not a
mathematical all-path analysis. On a back-edge it returns true only when the
revisited block starts with `cond` or `for.cond`, making normal lowered loops
accepted but isomorphic renamed loops rejected. The Rust pass does not preserve
that nominal implementation bug because the IR label contract assigns no
semantics to those prefixes.

Typed failures are `ModuleReturnVerificationError`,
`FunctionReturnVerificationError`, and `ReturnPathRuleError`. They report a
reachable valueless return with stable block and instruction context and preserve
structural prerequisite sources through downcastable
`Error::source()` chains.

This step changes no canonical JSON, DTO, importer, lifecycle expansion, SSA,
optimizer, compiler-pipeline, LLVM, or PyO3 behavior. Other remaining verifier
families stay deferred.
