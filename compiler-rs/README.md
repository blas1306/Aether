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
  lifecycle pass checks certain source-ordered storage transitions inside each
  block. Phi semantics, inter-block lifecycle merging, cleanup completeness,
  and optimization verification remain outside these passes.
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
