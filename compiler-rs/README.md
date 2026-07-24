# Aether compiler Rust workspace

This workspace is the isolated home for native Aether compiler components. It
establishes the project structure and development policy only: the production
compiler remains entirely on its existing Python path.

## Crates

- `aether-ir` owns the language-independent Rust representation of Aether IR.
  It contains no verifier, parser, serializer, DTO, or compiler integration.
- `aether-verifier` provides a canonical combined module verifier plus
  independently callable passes for declaration and
  instruction-local type consistency, function/block structure and basic local
  CFG validity, and function-local SSA definition/use validity in owned Aether
  IR. The SSA pass checks unique parameter/result definitions, exact named
  references, and same-block definition-before-use. The dominance pass then
  checks cross-block uses against an entry-rooted dominator relation. The local
  lifecycle passes provide focused local checks, deterministic inter-block CFG
  state merging, and ownership-completeness checks at every reachable return.
  The all-path return pass independently verifies IRV-024 for non-void
  functions. The type pass also verifies retained aggregate compare/print
  shapes, vector/matrix dimensions, matrix literal cardinality, canonical
  builtin identity, the retain/release call contract, and Python-parity element
  lifecycle support for collection copy and list-slice operations. The same
  pass now completes borrowed array/list element scope, direct store/return
  escape, and mutation-receiver parity for IRV-037–042, and rejects storage
  return operands under IRV-026. Phi semantics, cleanup insertion, and
  optimization verification remain outside these passes.
- `aether-ir-verifier` provides protocol v1 and the standalone
  `aether-ir-verifier` stdin/stdout executable. It embeds the existing
  schema-v1 module DTO, imports the owned IR, and calls only the combined
  verifier API. It is not connected to the Python compiler.
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

At the time Step 3E.1 was implemented, Python's `_block_returns` was a recursive
syntactic approximation rather than a mathematical all-path analysis. On a
back-edge it returned true only when the revisited block started with `cond` or
`for.cond`, making normal lowered loops accepted but isomorphic renamed loops
rejected. The Rust pass did not preserve that nominal implementation bug
because the IR label contract assigns no semantics to those prefixes. Phase
4.5C subsequently aligned Python to this graph behavior.

Typed failures are `ModuleReturnVerificationError`,
`FunctionReturnVerificationError`, and `ReturnPathRuleError`. They report a
reachable valueless return with stable block and instruction context and preserve
structural prerequisite sources through downcastable
`Error::source()` chains.

This step changes no canonical JSON, DTO, importer, lifecycle expansion, SSA,
optimizer, compiler-pipeline, LLVM, or PyO3 behavior. Other remaining verifier
families stay deferred.

## Phase 3 Step 3E.2: aggregate metadata verification

Step 3E.2 is complete. The existing instruction-local type verifier now closes
the metadata portions of IRV-075–076, IRV-078, and IRV-107–124 without adding a
second aggregate pass. Aggregate element types, operand compatibility, numeric
promotion, and orientation remain in their existing checks; the new logic
validates only retained shape, dimension, and cardinality fields.

Compare follows the Python initial-IR contract exactly. Scalar operands carry
no aggregate shape. Vector and matrix equality/inequality comparisons require
positive rank-one and rank-two shapes respectively. Print differs deliberately:
vectors require exactly one retained dimension and matrices exactly two, but
Python does not require those print dimensions to be positive. Every other
printable type carries no shape.

All signed vector lengths retained by vector add/subtract, scale, and dot must
be positive. Matrix construction, outer product, matrix add/subtract, scale,
matrix multiplication, matrix-vector/vector-matrix multiplication, element
get/set stride metadata, and row/column queries validate each retained matrix
dimension for positivity. Matrix literals additionally require exactly
`rows * columns` flat elements; the product is computed as `i128` in diagnostics
so malformed large signed metadata cannot overflow verification. `IRVectorNew`
has no signed length metadata, and matching Python, an empty vector literal is
valid.

Typed leaf failures are `TypeRuleError::InvalidAggregateShape`,
`InvalidVectorLength`, `InvalidMatrixDimensions`, and
`InvalidMatrixCardinality`. They retain the offending field/value and expected
rank, positivity, or element count. Existing instruction, block, function, and
module wrappers continue to retain the exact `InstructionKind` and complete
downcastable `Error::source()` chain.

Focused Rust tests cover scalar/vector/matrix compare and print, rank and
positivity boundaries, every retained vector/matrix dimension field, empty and
positive vector construction, exact/short/long matrix literals, and `1x1`,
`1xN`, and `Nx1` matrices. Python characterization tests pin the less-obvious
print-positivity and empty-vector behavior. No Python aggregate-metadata verifier
bug was found, and no aggregate metadata gap remains in IRV-075–076, IRV-078, or the
metadata portions of IRV-107–124.

Remaining initial-IR verifier work includes borrowed-element scope/escape rules
(IRV-037–042), the lifecycle-trait portions of collection copy/slice rules, and
canonical builtin semantic-name checks. This step does not alter canonical JSON,
Python or Rust wire DTOs, the importer, lifecycle, ownership, the borrow
verifier, SSA, dominance, optimizer, pipeline integration, LLVM, or PyO3
behavior.

## Phase 3 Step 3E.3: canonical builtin identity and retain/release

Step 3E.3 extends the existing instruction-local type verifier; it does not add
a second builtin pass. Every builtin-tagged `IRCall` now requires exact string
identity between `function` and `builtin` before the existing builtin signature,
result, and layout rules run. A different builtin with a compatible signature,
a user function with that signature, an alias, and a renamed function are all
rejected. The check is name-based: builtin calls do not resolve the module
function table, so a same-named user declaration neither supplies an alias nor
shadows a canonical builtin-tagged call. A renamed semantic `builtin` tag is not
an alias and falls through to the existing unsupported-builtin rule.

`__aether_retain` and `__aether_release` share the same Python initial-IR
contract: their function name is canonical, they have exactly one argument,
they produce no result, and the argument's top-level type is `string`, `struct`,
`method_result`, `array`, or `list`. This is a shallow type-family allowlist,
not a recursive lifecycle-trait query; arrays/lists of scalar elements and
structs with only scalar fields are accepted. Primitive scalars, enums, vectors,
matrices, nullable values, and all other top-level types are rejected. Runtime
retain/release behavior and lifecycle transfer semantics are unchanged.

Typed leaves are `TypeRuleError::InvalidBuiltinIdentity`,
`InvalidRetainReleaseSignature`, and `InvalidRetainReleaseType`. They retain the
semantic builtin, expected and actual function identity, argument/result shape,
or offending type as applicable. Existing instruction, block, function, and
module wrappers preserve `IRCall` identity and the complete downcastable
`Error::source()` chain.

No builtin-verifier gap remains in IRV-055–067. Remaining initial-IR verifier
families are borrowed-element scope/escape rules (IRV-037–042) and the
lifecycle-trait portions of collection copy/slice rules. This phase changes no
importer, canonical JSON, Python or Rust wire DTO, ownership/lifecycle transfer,
borrow verifier, optimizer, compiler pipeline, LLVM backend, or PyO3 behavior.

## Phase 3 Step 3E.4: collection lifecycle capability verification

Step 3E.4 extends the existing instruction-local type verifier and reuses its
shared lifecycle registry. Matching Python IRV-091, IRV-094, and IRV-097,
`IRArrayCopy`, `IRListCopy`, and `IRListSlice` require the direct element
type's lifecycle traits to have no error reason. `IRArraySlice` does not perform
this check. No separate collection verifier or combined verifier pipeline was
introduced.

The Python rule does not require a named operation such as copy-init, assign,
destroy, move-init, or relocate. Its only capability is a defined lifecycle
classification, represented by `LifecycleTraits.reason is None`. Scalars,
strings, collection handles, functions, and defined structs/method-results are
accepted. Matrix elements, unoriented vector elements, class/interface values,
nullable values, void, and unresolved structs carry an error reason and are
rejected when they reach this instruction-local rule.

The check is shallow. A nested array/list is accepted without inspecting its
element, and aggregate composition does not propagate a child lifecycle error
reason. Consequently a defined struct containing a class, interface, nullable,
or otherwise unsupported field remains accepted as a collection element. This
is intentional parity with Python rather than stronger recursive validation.

`TypeRuleError::MissingCollectionLifecycleCapability` retains the exact
`InstructionKind`, `CollectionKind`, element `IRType`, missing
`CollectionLifecycleCapability`, and lifecycle-registry reason. Existing
instruction, block, function, and module wrappers preserve deterministic
rendering and the complete downcastable `Error::source()` chain.

Focused Rust tests cover scalar, managed string, struct, function, and nested
collection elements; direct class, matrix, and nullable failures; the
`IRArraySlice` exclusion; deterministic rendering; and downcasting. Python
characterization tests freeze the previously uncovered direct-only rule and
array-slice exclusion. No Python verifier bug was discovered; the shallow
aggregate and nested-collection behavior is surprising but is the actual
documented contract. No collection lifecycle-capability gap remains.

Remaining initial-IR verifier work is borrowed-element scope and escape
verification (IRV-037–042). This phase changes no importer, canonical JSON,
Python or Rust wire DTO, ownership transfer, runtime, optimizer, compiler
pipeline, LLVM backend, or PyO3 behavior.

## Phase 3 Step 3E.5: borrowed-element scope and escape verification

Step 3E.5 extends the existing type-verifier traversal with the Python
initial-IR verifier's function-wide borrowed-element scan. It recognizes only
`IRArrayGet` and `IRListGet` instructions whose `borrowed` flag is true. The
source collection, index, and result remain subject to their existing ordinary
type and SSA/data-flow rules; constants, temporaries, aggregates, and managed
values do not receive a separate borrow-source classification.

IRV-037 requires a non-empty `borrow_scope`, IRV-038 requires that scope to
equal the exact name of the block containing the get, and IRV-039 forbids any
scope (including an empty string) on an owned get. The scope describes the
definition block only. Python does not reject later uses in another dominated
block, compute lexical or CFG borrow ends, or invalidate a borrow when storage
is moved or destroyed. Nested borrowed gets, repeated reads, copy-init,
aggregate construction, and type-correct direct/indirect calls remain accepted.

IRV-040 is narrower than a general escape rule. Only direct `IRStore` of a
borrow whose lifecycle traits need destruction is rejected, and an earlier
`__aether_retain` of that value in the same block permits the store. Scalar and
other trivially destroyed values need no acquisition. Acquisition is reset at
each block; release does not acquire, and retain does not permit a direct
return. IRV-041 rejects returning a borrowed result by exact value name in any
block. IRV-042 rejects only mutation receivers for array set; list set, push,
insert, remove-at, pop, clear, and reverse; sequence sort; and struct set.

This intentionally is not a general borrow checker. Python permits a borrow as
an aggregate element or call argument and does not track use-after-scope,
borrow-after-move, consumers, aliasing, globals, reborrow lifetimes, or generic
storage/escape paths. The owned Rust IR has no global-assignment instruction.
Adding any of those restrictions would exceed IRV-037–042 and break parity.

Typed borrow leaves are `BorrowRuleError`, with `BorrowRule` retaining the exact
IRV-037–042 identifier. Each variant exposes the borrowed value, definition and
consumer instruction locations, declared/defining scope, type when lifecycle
classification matters, and prohibited mutation kind. `TypeRuleError::BorrowViolation`
links the borrow leaf into the existing instruction, block, function, and module
`Error::source()` chain, preserving deterministic rendering and downcasting.
The implementation reuses the shared lifecycle registry's `needs_destroy`
classification and the existing stable instruction-location representation; it
introduces no CFG, dominance, ownership, or lifecycle analysis.

Focused Rust tests cover local, nested, and cross-block borrows; ordinary
dominance; same-block acquisition; all six failures; every Python mutation
receiver family; direct return after retain; aggregate/call/copy boundaries;
invalid ordinary sources/calls; deterministic diagnostics; and full
downcasting. Python characterization tests freeze the previously uncovered
scope, managed-store, same-block retain, aggregate/call/copy, cross-block, and
invalid-source boundaries. No new Python verifier bug was found; the missing
general escape and lifetime checks are the already documented boundary of the
IRV-037–042 contract.

All initial-IR semantic verifier families identified by the verifier audit are
now implemented in Rust. The remaining verifier work is the parity audit and
differential corpus review, followed by separately scoped PyO3 and compiler-
pipeline integration. This phase changes no importer, canonical JSON, Python or
Rust wire DTO, ownership/lifecycle model, optimizer, runtime, compiler pipeline,
or LLVM backend.

## Phase 4.1: combined verifier API and diagnostic normalization

`aether_verifier::verify_module(&IRModule) -> VerificationResult` is now the
canonical public entry point for complete Rust Initial IR verification.
`VerificationResult` is `Result<(), VerificationFailure>`: success is `Ok(())`;
failure exposes the detecting `VerificationPhase`, semantic
`VerificationErrorCategory`, optional stable `IRV-NNN` identifier,
`VerificationContext`, deterministic message, and original typed
`VerificationError`. The original module-level error remains available through
`VerificationFailure::underlying_error()` and the standard `Error::source()`
chain.

The fixed fail-fast order is:

1. structure;
2. types;
3. SSA;
4. dominance;
5. lifecycle;
6. returns.

This order establishes CFG structure before CFG consumers and establishes the
SSA namespace before dominance. Each complete semantic pass runs once.
Dominance, lifecycle, and return analysis use crate-private
prerequisite-satisfied adapters in the combined path, while their existing
public APIs retain their defensive prerequisite checks and remain independently
callable. The focused local-lifecycle API is not a seventh complete pass; its
rules are included by the complete lifecycle analysis.

Normalization is an adapter over existing typed diagnostics. It does not
replace pass-specific errors or verification logic. Module-level errors have an
empty optional context; function, block, and instruction fields are populated
when the underlying diagnostic identifies them. IRV identifiers and categories
follow the Initial IR invariant inventory where the typed leaf or retained
instruction identifies the rule unambiguously. Repeated verification of the
same immutable module produces equal classification, context, invariant, and
message values.

No compiler integration or transport is part of Phase 4.1. The API is intended
to be consumed later by a subprocess protocol, a PyO3 adapter, and shadow-mode
comparison, but none of those consumers exists yet. Python remains the
production verifier, and no CLI/configuration behavior changes.

## Phase 4.2A: versioned protocol and standalone executable

The `aether-ir-verifier` package produces an executable of the same name.
Protocol version 1 reads exactly one JSON request from stdin and writes exactly
one compact JSON response plus a newline to stdout. The request fields are
`protocol_version`, `operation: "verify"`, and `module`. The embedded module is
the existing `IRModuleDTO` and carries its own `schema_version: 1`; the outer
envelope does not duplicate the IR schema version.

The response statuses are `accepted`, `rejected`, and `error`. Semantic
rejections carry explicit phase, category, `IRV-NNN`, deterministic message,
and nullable function/block/instruction context. Protocol-exposed phases,
categories, instruction kinds, statuses, and infrastructure error kinds use
explicit mappings rather than Rust enum formatting. A missing invariant or
unknown future diagnostic classification becomes a `normalization` error.

Exit code 0 means one valid response was emitted, including semantic rejection
and recoverable infrastructure errors. Nonzero is reserved for inability to
serialize or write that response. The outer executable catches unwind panics
and emits a stable `internal` error without a panic payload; library panic
behavior is unchanged.

Build with:

```console
cargo build -p aether-ir-verifier
cargo build --release -p aether-ir-verifier
```

The complete wire contract and discovery boundary are documented in
`../docs/compiler/IR_VERIFIER_PROTOCOL.md`. No Python subprocess invocation,
compiler selection, CLI option, shadow mode, packaging discovery, or PyO3
binding is implemented in Phase 4.2A.

After the Phase 4.5C IRV-024 alignment, the 141 schema-v1-compatible migration
cases have no acceptance/rejection differences: 65 are accepted by both.
The former `non-void-path-without-return` Python-IRV-024/Rust-accepted result
is retained as an ordinary accepted corpus case and no outcome-divergence rule
remains. Exact first-invariant parity is intentionally not universal: the
corpus manifest records `undefined-slot` as the known
IRV-031/IRV-032 representation/import-model difference,
`return-storage-after-move` as the valid IRV-050/IRV-026 first-failure ordering
difference, and `inconsistent-branch-initialization` as the known
IRV-036/IRV-028 lifecycle-dataflow improvement. Future shadow comparison must
compare outcomes separately from invariant IDs, must not use messages as
semantic identity, and must surface any pair other than these exact
expectations as unexpected.
