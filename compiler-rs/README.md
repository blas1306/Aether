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
  checks cross-block uses against an entry-rooted dominator relation. Phi
  semantics, ownership/lifecycle, and optimization verification remain outside
  these passes. The next verifier step is Phase 3D: ownership/lifecycle
  verification, because the current owned IR has no phi-like instruction.
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
verifier step is Phase 3D ownership/lifecycle verification rather than an empty
Step 3C.3.
