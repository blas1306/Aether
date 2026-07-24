# Gradual Python-to-Rust compiler migration

> Status: Phase 3, Step 3E.5 borrowed-element scope and escape verification complete.
> The isolated Rust workspace now has independently callable type, structure,
> SSA, dominance, local lifecycle, and CFG-propagated lifecycle verifier passes
> over the complete owned IR. Steps 3E.1–3E.5 close all-path returns, aggregate
> metadata, canonical builtin/retain-release, collection lifecycle, and
> borrowed-element IRV-037–042 parity. The parity audit is next.
> Cleanup insertion, PyO3, compiler-pipeline integration, LLVM, and
> production integration remain unimplemented. This document defines sequencing
> and promotion gates and does not declare the Python IR or SSA model a stable
> public format.

## 1. Decision summary

The migration keeps Python as the compiler driver and frontend while moving
well-bounded internal compiler components to Rust one at a time. The first
component is the IR verifier. The initial integration mechanism is one in-process
PyO3 extension, called once per `IRModule`, with Rust rebuilding an owned module
from a versioned, tagged DTO tree. Python objects and references are not retained
by Rust. The contingency, if native-extension packaging proves unacceptable, is
the same logical contract carried to a separate helper process.

The provisional workspace location is `compiler-rs/`. It describes the scope
better than `backend/rust/`: IR, CFG, verification, SSA, and optimization are
compiler internals, not only code-generation backends. The existing LLVM backend
remains in place until the IR and SSA migrations have stabilized.

These are closed directions for the first experiment, subject to an ADR before
production integration. They are not authorization to add Rust in this
documentation-only change.

## 2. Current architecture

The detailed repository audit is in
[BACKEND_ARCHITECTURE_AUDIT.md](BACKEND_ARCHITECTURE_AUDIT.md). The current
pipeline boundary is `TypedProgram` in `src/aether/pipeline.py`. Source is parsed
and checked in Python; native compilation lowers a `CheckedProgram` to Python
dataclasses for IR and SSA and ultimately emits textual LLVM.

```text
UTF-8 source
  -> src/aether/lexer.py / src/aether/tokens.py
  -> src/aether/parser.py -> src/aether/ast.py
  -> src/aether/typechecker.py + module and symbol analysis
  -> entry-point normalization -> TypedProgram / CheckedProgram
       |-> AST interpreter -> Python runtime values
       |
       `-> AST-to-IR lowering -> IRModule
             -> IR verification
             |-> IR interpreter
             |-> optional IR optimization for IR tooling
             `-> lifecycle expansion -> CFG/dominance/frontier
                   -> phi placement and SSA renaming -> SSAModule
                   -> SSA verification and optimization
                   -> textual LLVM IR plus generated native runtime
                   -> clang/linker -> native executable
```

The layers relevant to this migration are:

- **Frontend.** `src/aether/lexer.py` produces tokens from source,
  `src/aether/parser.py` builds nodes from `src/aether/ast.py`, and
  `src/aether/typechecker.py` performs semantic checking. Symbols and scopes live
  in `src/aether/symbols.py` and `src/aether/scope.py`.
- **Modules and semantic program.** `src/aether/modules.py` resolves and checks
  source modules and constructs `CheckedProgram`; `src/aether/entry_point.py`
  normalizes the root entry point. `prepare_typed_program()` in
  `src/aether/pipeline.py` coordinates these stages.
- **AST execution.** `src/aether/interpreter.py`, `src/aether/types.py`, and the
  helpers under `src/aether/stdlib/` implement the wider AST execution path. It
  remains an important independent semantic oracle, but is not on the native
  compilation path after type checking.
- **AST-to-IR lowering.** `src/aether/ir/lowering.py` and
  `src/aether/ir/module_lowering.py` lower the checked program. They know about
  builtins, modules, storage, cleanup, source locations, aggregate shapes, and
  nominal types; this is not yet a language-independent boundary.
- **IR model.** `src/aether/ir/model.py` defines mutable module/function/block
  containers and instruction dataclasses. `src/aether/ir/types.py` defines the
  IR types. `IRStorage` distinguishes owning addressable storage from immutable
  values, and selected instructions carry `IRSourceLocation`. The versioned
  dictionary DTO and its canonical JSON fixture encoding live in
  `src/aether/ir/dto.py`; JSON is not the compiler's internal representation.
- **IR verification and execution.** `src/aether/ir/verifier.py` verifies
  structure, types, data flow, builtin contracts, aggregate metadata, and
  lifecycle rules. `src/aether/ir/interpreter.py` executes verified IR with
  Python runtime helpers. `src/aether/ir/lifecycle.py` expands lifecycle actions.
- **IR optimization.** `src/aether/ir/optimizer/` contains constant folding,
  local constant propagation, algebraic simplification, dead-code elimination,
  and dead-store elimination. This pipeline is currently exposed mainly through
  IR inspection/benchmark paths; native compilation uses the SSA optimizer.
- **CFG and SSA construction.** `src/aether/analysis/cfg.py`,
  `src/aether/analysis/dominators.py`, and
  `src/aether/analysis/dominance_frontier.py` provide the structural analyses.
  `src/aether/ssa/general_builder.py` is the default Cytron-style path and uses
  `src/aether/ssa/phi_placement.py` and `src/aether/ssa/renaming.py`. The older
  pattern builder in `src/aether/ssa/builder.py` remains an explicit comparison
  path.
- **SSA model, verifier, and analysis.** `src/aether/ssa/model.py` mirrors most
  IR operations in value form and adds phi nodes. `src/aether/ssa/verifier.py`
  checks types, CFG structure, phi completeness, definitions, and dominance.
  `src/aether/ssa/analysis/` contains lattice and worklist support.
- **SSA optimization.** `src/aether/ssa/optimizer/` implements constant folding,
  global constant propagation, algebraic simplification, SCCP, trivial-phi and
  dead-phi elimination, and dead-code elimination. `SSAOptimizerPipeline`
  verifies after every pass when used by native compilation.
- **LLVM emission.** `src/aether/backend/llvm/backend.py` delegates to the large
  textual printer in `src/aether/backend/llvm/printer.py`. Type and layout logic
  live in `src/aether/backend/llvm/types.py` and
  `src/aether/backend/llvm/layout.py`. `src/aether/backend/llvm/build.py` applies
  the native capability gate, obtains verified optimized SSA, emits LLVM, and
  invokes external `clang`; `src/aether/backend/llvm/run.py` runs a temporary
  executable.
- **Runtime.** The AST runtime consists of Python values and helpers used by the
  interpreter. The native runtime is LLVM text generated by files such as
  `src/aether/backend/llvm/string_runtime.py`,
  `src/aether/backend/llvm/array_runtime.py`,
  `src/aether/backend/llvm/list_runtime.py`,
  `src/aether/backend/llvm/integer_runtime.py`, and
  `src/aether/backend/llvm/text_file_runtime.py`. It is included in emitted
  modules rather than shipped as a separately versioned runtime library. The
  current ABI constraints are described in
  [AETHER_NATIVE_ABI.md](AETHER_NATIVE_ABI.md).
- **CLI, LSP, IDEs, and packaging.** `src/aether/cli.py` owns user-visible mode
  selection, output, and exit codes. `src/aether/diagnostics.py` maps exceptions
  to public diagnostics and maps internal compiler errors to exit code 70.
  `src/aether_lsp/server.py` provides the language server. The VS Code extension
  in `vscode-extension/` invokes `aether` and `aether-lsp`; the IntelliJ plugin
  lives in `tools/intellij-aether/`. `pyproject.toml` uses setuptools, finds
  packages under `src`, and exposes `aether` and `aether-lsp`. The current wheel
  is pure Python; `scripts/release.py` builds and inspects wheel/sdist artifacts.

The repository currently declares and release-checks native execution only for
Linux x86_64 with external `clang`. Windows and macOS are therefore migration
targets, not currently verified native platforms.

## 3. Goals and non-goals

The migration seeks:

- stronger internal types for IR and SSA and fewer representable invalid states;
- explicit, maintainable invariants for verification, CFG analysis, SSA, and
  optimization;
- better verifier and optimizer performance where measurement demonstrates it;
- a path to safe parallel analysis when a pass actually benefits from it;
- reproducible compiler components and platform-specific artifacts;
- less critical compiler work performed dynamically in Python;
- incremental replacement with differential evidence and a localized rollback;
- unchanged source language, CLI behavior, diagnostics contract, IDE behavior,
  textual IR contract, native output, and platform policy unless separately
  approved.

It does **not** seek to rewrite the frontend first, change Aether syntax or
semantics, replace LLVM, move the whole repository to Rust at once, or maintain
two complete compilers indefinitely. It must not reduce portability, introduce
one FFI call per instruction, or treat Rust as justification for premature
parallelism or optimization.

Python initially retains lexing, parsing, AST ownership, type checking, module
resolution, initial lowering, CLI/LSP/developer tools, pipeline coordination,
and high-level user presentation. Rust is introduced for an importable owned IR
model, IR verification, CFG analysis, SSA model/construction/verification,
dominance, and individual optimizers. LLVM emission or runtime components are
considered only after these contracts settle.

Starting with the parser would mix grammar recovery, source locations, and
diagnostic compatibility before a stable boundary exists. Starting with the
CLI or LSP would add little compiler safety while risking all user entry points.
The module system combines filesystem behavior and semantic state. The complete
LLVM backend combines emission, layouts, ownership, runtime discovery, and
toolchain orchestration. The string runtime has ABI, allocation, ARC, UTF-8, and
platform concerns. Each is a poorer first experiment than a deterministic
verifier that neither executes nor generates code.

## 4. Migration phases

Each phase is independently reviewable. A later phase does not begin until the
preceding exit criteria that affect it are met.

| Phase | Scope and dependencies | Main risk | Validation and completion criterion | Rollback |
| --- | --- | --- | --- | --- |
| **0 — Contract and baseline** | Inventory IR instructions/types/invariants, assign invariant identifiers, capture valid and invalid corpora, record diagnostics, define the DTO schema, and benchmark the Python verifier. Depends only on the current repository. | Freezing accidental behavior as intended semantics. | Every verifier rule is classified as contract, implementation detail, or known issue; representative fixtures and baseline measurements are reproducible. | Documentation/schema changes only; revise before any consumer exists. |
| **1 — Minimal Rust workspace** | Create `compiler-rs/`, toolchain policy, formatting/lint/test CI, and initially one `aether-ir` crate, with no production call path. Depends on Phase 0 decisions. | Build complexity before value is demonstrated. | Clean checkout can format, lint, test, and build on the agreed CI targets without changing CLI behavior or artifacts. | Remove the isolated workspace and CI jobs; Python remains untouched. |
| **2 — Owned IR model and adapter** | Implement types, values/storage, blocks, functions, instructions, terminators, struct layouts, source spans, schema validation, and whole-module conversion. | Python and Rust models drift or conversion loses data. | Round-trip/canonical snapshot tests cover every current variant and reject unknown versions/tags; no Python reference remains in the Rust module. | Disable/remove only the adapter; Python model remains canonical. |
| **3 — IR verifier** | Implement structural, typing, data-flow, builtin, aggregate, and lifecycle checks behind explicit `python`, `rust`, and `shadow` selection. Depends on the complete model subset it checks. | False acceptance is more serious than extra rejection; diagnostics can diverge. | Full valid/invalid corpus has no unexplained semantic mismatch; crashes and mismatches are surfaced; opt-in and rollback are tested. | Set the localized selector to `python`; never silently retry after Rust failure. |
| **4 — CFG and structural analysis** | Move successor/predecessor construction, reachability, and then dominance/frontier algorithms corresponding to `src/aether/analysis/`. | Edge ordering or unreachable-block semantics changes SSA. | Graph and dominator results compare canonically on generated and hand-written CFGs, including loops, diamonds, unreachable blocks, and malformed targets. | Select Python analysis as a unit; retain serialized comparison fixtures. |
| **5 — SSA** | Add owned SSA, lifecycle-expanded IR conversion, general SSA construction, phi placement, renaming, use-def information, and SSA verification. The pattern builder stays only as an existing comparison aid. | Phi edge semantics or dominance-sensitive uses diverge. | Printed/canonical SSA is equivalent where naming is normalized; both verifiers accept it; stress and dominance suites have no unexplained mismatch. | Switch the SSA boundary back to the Python general builder and verifier together. |
| **6 — Optimizers** | Migrate one pass at a time: IR constant folding, local constant propagation, algebraic simplification, DCE, dead-store elimination; then SSA constant folding, global constant propagation, algebraic simplification, SCCP, trivial/dead phi elimination, and DCE. | Behavior differs despite semantically equivalent text, or effects are modeled incorrectly. | Per-pass semantic equivalence, verifier-after-pass, fixed-point/determinism tests, and performance measurements pass before each pass is promoted. | Feature-select each pass independently and restore the Python pass order. |
| **7 — Product integration** | Make validated Rust components the default, keep Python temporarily as the test oracle, and remove dual production work. | A packaging/platform case missed by CI reaches users. | Promotion criteria in Section 13 pass on every supported release platform and rollback has been rehearsed. | One configuration change restores the Python component in a patch release while the shared contract remains unchanged. |
| **8 — Backend and runtime** | Only after stable IR/SSA: assess LLVM support/emission and specific runtime components against [BACKEND_MIGRATION_ROADMAP.md](BACKEND_MIGRATION_ROADMAP.md). Do not introduce Rust LLVM bindings merely to start this phase. | Scope expands into ABI, memory management, and platform work simultaneously. | A separately approved design identifies a measurable reason, stable ABI/layout boundary, parity corpus, and platform packaging plan for each component. | Keep textual LLVM/backend/runtime generation in Python; roll back per component, not the entire migration. |

## 5. Why the IR verifier is first

`IRVerifier` has a whole-module input, a success/error result, deterministic
behavior, no code-generation side effects, and extensive negative tests in
`tests/aether/test_ir_verifier.py` and lifecycle tests. It can be called in
shadow mode without changing the module used by later stages. It exercises the
Rust IR model before an optimizer can rewrite anything, and a feature selector
limits the impact of failure.

The current verifier in `src/aether/ir/verifier.py` enforces these real rule
families:

- nominal struct definitions are unique and named; field names are unique;
  fields have valid non-void types; referenced struct layouts exist; recursive
  by-value layouts cannot have infinite size;
- function names, parameter names, block names, and value definitions are unique;
  functions contain blocks and a block named `entry`; parameter, return, value,
  storage, aggregate, function, enum, callable, nullable, and method-result types
  are checked for validity;
- every block ends in `IRReturn`, `IRJump`, or `IRBranch`; no instruction follows
  a terminator; jump and branch targets exist; branch conditions are boolean;
- values are defined before use on executable paths, have consistent types, and
  mutable slots exist, retain one type, and are definitely initialized before
  load. Merge states use intersection, so a store on only one incoming path is
  insufficient;
- non-void functions return a value of the declared type on every exiting path;
  return operands and transferred storage obey value/storage and type rules;
- direct and indirect calls have an existing callable/signature, correct arity,
  compatible argument types, and correct void/non-void result behavior. Builtins
  additionally retain canonical names, signatures, layouts, and result ownership;
- constants, arithmetic, comparisons, casts, printing shapes, structs,
  method-result operations, arrays, lists, vectors, and matrices satisfy their
  opcode-specific type, orientation, dimension, index, shape, and result rules;
- lifecycle storage is initialized, live, moved, relocated, assigned, destroyed,
  and transferred consistently across CFG paths. Required cleanup is present at
  return. Borrowed iteration elements do not escape as owned values or permit
  mutation without the required acquisition/copy.

The verifier does **not** require every IR block to be reachable. Unreachable
blocks still receive local instruction/type checks, but reachability is not an
IR validity condition. Phi completeness, single SSA definitions, and dominance
of uses are SSA-verifier rules in `src/aether/ssa/verifier.py`, not IR-verifier
rules, and must not be attributed to this first component.

The complete Phase 0, Step 1 rule inventory, including the canonical stable
`IRV-NNN` identifiers, categories, and current Python locations, is maintained
in [IR_VERIFIER_INVARIANTS.md](IR_VERIFIER_INVARIANTS.md). Those identifiers are
metadata for future differential verification; the Python verifier does not
emit them yet.

## 6. Integration mechanism

| Alternative | Strengths | Costs and risks | Decision |
| --- | --- | --- | --- |
| **PyO3 extension** | One whole-module call, low transport overhead, natural Python orchestration, Rust-owned model, straightforward exception containment and opt-in selection. | Platform wheels replace the current universal wheel; debugging spans Python/Rust; CPython ABI/version compatibility must be managed. | **Selected initially.** Use a narrow extension surface and consider `abi3` only after compatibility testing. |
| **Separate helper process** | Strong crash isolation, independent runtime/ABI, inspectable protocol, easy side-by-side executable debugging. | Startup and serialization overhead, stdin/stdout framing, protocol/version negotiation, binary discovery, and another artifact per platform. | **Contingency.** Reuse the same logical schema if extension packaging or CPython coupling fails an approved gate. |
| **C ABI library** | Language-neutral and potentially stable for multiple hosts. | Manual ownership/error conventions, serialization still needed, unsafe boundary, weak Python ergonomics, and more ABI surface than required. | Rejected for the first integration. It may suit a future runtime ABI, not this verifier. |
| **Rust driver rewrite** | Eventually removes Python orchestration from compilation. | Immediately pulls in CLI, frontend, modules, diagnostics, LSP interaction, and packaging; rollback becomes coarse. | Explicitly out of scope until individual components have proven boundaries. |

Conceptually the selected path is:

```text
Python pipeline
  -> build one versioned ModuleDTO
  -> PyO3 extension call (one call per module)
  -> owned Rust IR -> Rust verifier
  -> structured VerifyOutcome / internal failure
  -> Python diagnostic and pipeline adapter
```

The extension API must be coarse. No API may require Python to call Rust once
per instruction or operand. A function-sized call is acceptable for isolated
tests or later parallel analysis; the product boundary is a module/compilation
unit.

## 7. IR interchange contract

| Representation | Type fidelity and stability | Inspection/performance | Initial use |
| --- | --- | --- | --- |
| Arbitrary direct Python dataclasses | Preserves current objects but couples Rust to Python class names and constructor details; no independent schema. | No byte serialization, but conversion code becomes reflection-heavy. | Rejected. |
| **Versioned tagged DTO converted by PyO3** | Explicit enums/tags, exact integer bounds, explicit optional values, layouts and spans; Rust immediately owns validated data. | Inspectable as Python primitives; one tree walk and no encoding/decoding bytes. | **Selected.** |
| JSON | Portable and easy to debug; schema v1 defines canonical ordering, formatting, finite numbers, complex-value tags, integer limits, and strict UTF-8. | Verbose and slower; excellent corpus artifact. | Canonical golden/corpus encoding only, not the DTO tree or in-process transport. |
| MessagePack | Compact and portable while retaining the schema's tags. | Less inspectable and adds a dependency; useful for a helper process. | Preferred transport if the process contingency is activated. |
| Custom binary | Maximum control and potential speed. | Highest compatibility, parser, fuzzing, and maintenance burden. | Not justified initially. |
| Printed Aether IR | Excellent for humans and existing snapshots. | `src/aether/ir/printer.py` has no matching canonical parser and text may omit internal distinctions. | Diagnostic/golden aid only. |
| Protobuf/FlatBuffers | Strong generated schema and cross-language support. | Toolchain/code generation and evolution policy are disproportionate for one in-process consumer. | Reconsider only if multiple external consumers emerge. |

The root DTO schema has an explicit `schema_version` field and tagged variants
for every type, constant, instruction, and terminator. A version mismatch or
unknown tag is a boundary error, never interpreted approximately. Collections
use deterministic ordered sequences unless lookup semantics require a map;
maps have canonical key rules. Names and source paths are Unicode strings
converted to owned Rust strings. Aether string constants are preserved as
Unicode/UTF-8 according to the existing compiler contract. `int` is range-checked
as signed i32; `float`/`double` conversion preserves the Python `f64` value;
complex constants use explicit real and imaginary fields; enum constants retain
nominal name, member name/id, and discriminant. Struct field order, vector
orientation, matrix dimensions, builtin semantic names, and optional aggregate
shape are never inferred at the boundary.

`IRSourceLocation` currently contains line, column, and optional path and is only
present on selected instructions. The schema must preserve that absence rather
than manufacture a location. A future span range may be added as a versioned,
backward-compatible field after diagnostic ownership is decided.

### Instruction DTO completeness

Schema v1 covers all 68 current concrete Python `IRInstruction` variants.
`IR_INSTRUCTION_DTO_REGISTRY` is the authoritative, deterministic mapping from
each exact Python instruction class to its stable DTO tag, encoder/decoder, and
corresponding Rust `IRInstruction` variant. When an instruction is added, the
same change must add its registry entry and codec branch and update the explicit
68-variant contract expectation; the completeness test discovers unregistered
Python subclasses, and a lightweight Rust source audit reports drift in either
direction. Subclasses never inherit another instruction's DTO representation.

The DTO boundary validates schema version, tags, fields, primitive kinds, and
transport ranges only. It deliberately preserves semantically invalid but
well-shaped IR so `IRVerifier` remains responsible for operators, types,
dimensions, control-flow targets, ownership, and other `IRV-*` invariants.

### Basic-block DTO

Phase 1, Step 3D adds complete schema-v1 conversion for the current
`IRBasicBlock` model. Python and Rust both define exactly two fields: a string
`name`, which is the block identity used by control-flow targets, and an ordered
instruction sequence. The stable primitive representation is:

```text
{
  "name": <string>,
  "instructions": [<InstructionDTO>, ...]
}
```

The instruction list uses the existing instruction DTO conversion element by
element and retains its original order. A terminator has no separate block
field: when present, it remains an ordinary `branch`, `jump`, or `return`
instruction at its original list position. The current model has no block ID,
label distinct from `name`, parameters/arguments, source location, or metadata,
so the DTO does not manufacture any of them. Schema version remains a property
of the enclosing interchange contract rather than being repeated in each block.

The block boundary validates only the requested schema version, exact required
fields, unexpected fields, the string name, instruction sequence shape, and
every nested instruction DTO. It intentionally accepts empty blocks, blocks
without a terminator, multiple terminators, instructions after a terminator,
and references to absent successors whenever those values are structurally
representable. Terminator placement, reachability, dominance, successor
existence, CFG consistency, and instruction semantics remain `IRVerifier`
responsibilities so their stable `IRV-*` diagnostics are preserved.

### Function DTO

Phase 1, Step 3E adds complete schema-v1 conversion for the current
`IRFunction` model. Inspection of the Python dataclass and Rust struct found the
same four fields in the same order: a string `name`, an ordered sequence of
`IRParameter` values named `parameters`, an `IRType` named `return_type`, and an
ordered sequence of `IRBasicBlock` values named `blocks`. The stable primitive
representation is:

```text
{
  "name": <string>,
  "parameters": [<ParameterDTO>, ...],
  "return_type": <TypeDTO>,
  "blocks": [<BasicBlockDTO>, ...]
}
```

The function conversion composes the existing parameter, type, and basic-block
converters. Parameter and block order is retained exactly; neither sequence is
sorted, deduplicated, or normalized. Schema version remains at the enclosing
interchange-contract level and is not repeated in each function object.

The current function model has no function-level storage/local declarations,
explicit entry-block field, visibility or linkage, builtin/external/method/
constructor/mutability flags, receiver information, attributes, metadata, or
source location. Storage and source locations can still occur inside nested
instructions and are preserved there by their existing DTO mappings. Entry
identity remains the existing semantic convention that a block is named
`entry`; the DTO does not derive or manufacture a separate entry field.

The function boundary validates only the requested schema version, exact
required fields, unexpected fields, primitive kinds, parameter and block
sequence shape, and every nested parameter, type, block, and instruction DTO.
It intentionally accepts structurally representable functions with no blocks,
no entry block, duplicate parameter or block names, incompatible returns,
unreachable blocks, malformed control flow, invalid parameter use, and invalid
ownership or lifecycle behavior. Those are semantic `IRVerifier`
responsibilities, preserving its stable `IRV-*` diagnostics.

The Python/Rust field synchronization check is test-only: it inspects Python
dataclass fields and resolved type hints, reads the Rust `IRFunction` source in
the test process, and compares exact field names, order, and compatible type
shapes with field-specific drift diagnostics. Production Python code does not
read or depend on Rust source files.

### Module DTO

Phase 1, Step 3F completes the schema-v1 Python DTO tree at its root. Inspection
of the actual Python dataclass and Rust struct found exactly the same two fields
in the same order:

- `functions`: an ordered `list[IRFunction]` in Python and
  `Vec<IRFunction>` in Rust;
- `structs`: an ordered `list[IRStructDefinition]` in Python and
  `Vec<IRStructDefinition>` in Rust.

The current module model has no module identity or name, enum definitions,
imports, external declarations, separate type-layout table, source-file or path
table, metadata, or attributes. Step 3F does not manufacture any of those
conventional compiler-module fields. Enums remain represented where they
actually occur today: `EnumType` and `IREnumConstant` nested in existing IR
entities. Source paths remain nested in instruction `IRSourceLocation` values.
Nominal layout information consists solely of ordered `IRStructDefinition`
values, each containing a string `name` and ordered `(field name, IRType)`
pairs.

The complete stable root envelope is:

```text
{
  "schema_version": 1,
  "functions": [<FunctionDTO>, ...],
  "structs": [
    {
      "name": <string>,
      "fields": [
        {"name": <string>, "type": <TypeDTO>},
        ...
      ]
    },
    ...
  ]
}
```

`schema_version` occurs exactly once, on this root envelope. The single schema
constant remains `IR_SCHEMA_VERSION = 1`; functions, struct definitions,
fields, blocks, instructions, values, constants, types, and source locations do
not repeat it. Encoding with an unsupported requested version and decoding an
envelope whose version is unsupported or not an integer both raise
`IRDTOSchemaVersionError`. Missing or unexpected envelope fields remain ordinary
structural `IRDTOError` failures.

`ir_module_to_dto()` and `ir_module_from_dto()` compose the existing nested
function mappings and the nominal struct-definition mapping. Function, struct,
and struct-field order is preserved exactly. Encoding does not sort,
deduplicate, resolve, or normalize any module entity, and repeated encoding of
the same module produces equal primitive DTO trees.

The module boundary validates only interchange structure: the exact root and
nested fields, primitive kinds, ordered sequence shape, nested DTO structure,
the root schema version, and existing integer-width rules. It intentionally
accepts duplicate function or struct names, duplicate fields, unresolved or
recursive nominal references, missing entry functions or blocks, inconsistent
types or layouts, and invalid CFG, instruction, ownership, or function
semantics whenever they are structurally representable. Those remain
`IRVerifier` responsibilities so stable `IRV-*` diagnostics survive the DTO
round trip.

The Python/Rust synchronization check remains test-only. It resolves Python
dataclass type hints and reads the Rust `IRModule` and `IRStructDefinition`
declarations during tests, comparing exact field names, field order, and
compatible collection and element shapes. Drift reports identify the affected
model and each missing, unexpected, reordered, or type-mismatched field.
Production Python never parses or depends on Rust source files.

### Step 3G root contract audit and canonical JSON

Phase 1, Step 3G confirms that schema v1 is complete for the current Python IR
root: modules, nominal struct definitions, functions, blocks, all 68 registered
instructions, every nested type and constant variant, values, storage,
parameters, and supported source locations. Root scenarios cover multiple
nested struct definitions; multiple void and non-void functions and blocks;
direct and indirect calls; lifecycle, collection, vector, matrix, method-result,
and control-flow operations; and return storage transfers. One registry-driven
module contains all 68 instruction classes. The audit derives that set from
`IR_INSTRUCTION_DTO_REGISTRY`; it does not maintain a second instruction
inventory.

Automated component checks walk every DTO category reachable from `IRModule`.
They require an encoder and decoder, an explicit JSON-primitive dictionary/list
shape with stable tags or fields, a focused exact round trip, and rejection of a
malformed tag or shape. Type coverage is checked against `IR_TYPE_TAGS`, and
instruction coverage against `IR_INSTRUCTION_DTO_REGISTRY`. Root tests continue
to prove the validation boundary by decoding structurally valid modules that
`IRVerifier` later rejects.

`ir_module_to_json()` and `ir_module_from_json()` provide the stable wire
rendering of the existing dictionary DTO. The schema-v1 canonical JSON rules
are:

- JSON text is UTF-8 and contains only standard JSON values; Python's `NaN`,
  positive or negative `Infinity`, overflow-to-infinity number spellings, and
  unpaired non-UTF-8 surrogate text are rejected;
- object keys are sorted lexicographically at every level;
- indentation is exactly two spaces, key separators are `": "`, there is no
  trailing whitespace, and the document ends with one newline;
- non-ASCII characters are emitted directly rather than ASCII-escaped;
- arrays retain DTO list order exactly; no function, struct, field, parameter,
  block, instruction, argument, or element list is sorted or normalized;
- duplicate object keys are rejected at every depth before DTO decoding;
- the root object is passed through the existing strict DTO decoder, including
  its exact fields and `schema_version` check;
- malformed JSON and UTF-8 failures are reported as `IRDTOJSONError`, a focused
  `IRDTOError`, rather than leaking `json.JSONDecodeError` or Unicode exceptions.

Input JSON may use other valid whitespace or object-key order; decoding followed
by encoding produces the canonical form. JSON remains only a fixture and future
interchange encoding over the dictionary contract. The compiler does not use it
as its internal DTO representation or pipeline transport.

The checked-in human-readable schema-v1 golden is
`tests/aether/rust_migration/fixtures/ir_module_v1_golden.json`. It contains a
struct with nested field types and a function with parameters, storage, a source
location, two blocks, branch control flow, a constant, and a storage-transferring
return. Tests independently build the Python model and compare its canonical
bytes with that file, then decode the file and require byte-identical canonical
re-encoding. The expected fixture is never generated inside the test.

For a future IR field or instruction, extend the Python model and semantics in
its owning change, then update the existing DTO encoder and decoder, its exact
field/tag shape, focused round-trip and malformed-input cases, the root audit
module, and the golden only when the small fixture benefits from the new shape.
New instructions must be added to `IR_INSTRUCTION_DTO_REGISTRY`; no parallel
instruction list is permitted. Run the complete DTO/root audit and verifier
suites before updating an equivalent Rust consumer.

Keep schema version 1 only when old and new readers agree on the exact meaning
and required shape of every accepted document. Bump the root `schema_version`
when a required field or variant is added or removed, a tag or field is renamed,
a primitive/range/optionality/order rule changes, or an existing value gains a
different meaning. A purely internal refactor that leaves canonical DTO/JSON
bytes and validation behavior unchanged does not require a bump. Additive fields
also require a bump under the current exact-field policy because v1 readers
reject unknown fields.

### Step 4A Rust wire DTO layer

The Rust wire representation now lives in
`compiler-rs/crates/aether-ir/src/wire.rs`. It uses serde-derived, exact-field
structs and internally tagged enums for the module, struct definitions and
fields, functions, blocks, all 18 type tags, values, storage, parameters,
constants, source locations, and all 68 instruction `kind` tags. Required
nullable fields use a transparent wrapper so an explicit JSON `null` remains
distinct from an omitted field. Fixed-rank shape arrays retain their schema-v1
wire lengths, unknown tags and fields are rejected, and the root preserves and
checks `schema_version` 1.

The three migration layers remain deliberately distinct:

- **Wire DTO:** the serde model is only the versioned interchange tree. It
  decodes and encodes the frozen Python JSON shape and performs structural
  schema rejection, but does not verify CFG, types, ownership, dominance,
  layouts, or references.
- **Rust IR:** the existing owned model in `aether-ir` is the representation
  intended for Rust compiler components. It is not the serialization format and
  has no serde coupling.
- **Importer:** DTO-to-Rust-IR conversion is a separate adapter. Step 4B.1
  implements its type-only slice; later slices will rebuild the remaining owned
  model without changing either frozen wire shape.

Rust tests deserialize the existing Python golden fixture directly, compare its
JSON value with Rust re-serialization, require deterministic typed and textual
round trips, exercise every instruction and type tag, and reject malformed JSON,
unknown tags, missing required fields, and unexpected fields. No second golden
fixture is generated or maintained. At the Step 4A boundary, DTO-to-Rust-IR
import, the Rust verifier, PyO3, pipeline integration, lowering, optimization,
and interpretation remained out of scope.

### Step 4B.1 Rust wire DTO-to-IR type importer

The type-only importer now lives in
`compiler-rs/crates/aether-ir/src/importer.rs`, separate from both the serde wire
model and the owned type declarations. `TryFrom<IRTypeDTO>` and
`TryFrom<&IRTypeDTO>` support consuming and borrowed callers, while the public
`import_type()` helper gives later adapter layers a named entry point. Both
forms are fallible because schema-v1 can structurally carry a `method_result`
whose receiver is not a struct, but the owned `MethodResultType` cannot
represent that combination.

All 18 current wire variants are reconstructed deterministically. Function
parameter order, enum variant order, nominal names, enum display names, vector
orientation, and every recursively nested element, inner, parameter, return,
receiver, and result type are retained exactly in owned `String`, `Vec`, and
`Box` storage. A non-struct method-result receiver produces
`IRImportError::MethodResultReceiverNotStruct`, including when reached inside a
nested type. No other type rule is imposed here: empty or unknown nominal
names, duplicate enum variants, unusual vector orientations, void aggregate
elements, missing struct definitions, and layout validity remain verifier
concerns.

Focused Rust tests cover every individual variant, deeply nested recursive
shapes, borrowed and consuming conversion, a serde wire round trip, repeated
deterministic reconstruction, exact optional and ordered-field preservation,
and directly and recursively embedded structurally impossible method-result
receivers. Step 4B.1 does not import values, constants, instructions, blocks,
functions, struct definitions, or modules and adds no PyO3 or verifier behavior.

### Step 4B.2 Rust foundational DTO-to-IR importer

The importer now also reconstructs the foundational owned entities consumed by
instructions and function declarations. Public consuming and borrowed
`TryFrom` implementations cover all six constant variants, enum-constant
metadata, all three value tags, the single storage tag, the single parameter
tag, and source locations. Named helpers provide the same entry points for
constants, enum constants, values, storage, parameters, source locations, and
nullable source-location fields. Every nested `type` field delegates to the
Step 4B.1 type importer.

Names, identifiers, strings, booleans, enum member metadata, `i32` constant and
enum integers, `i64` source coordinates, optional paths, and finite `f64` bit
patterns are copied without normalization or narrowing. The wire DTO already
uses the owned integer widths, so JSON outside those widths fails structural DTO
decoding before import. Programmatically constructed non-finite floating-point
DTOs are rejected by `IRImportError::NonFiniteConstantFloat`; the serde wire
contract also rejects NaN and infinity. Nested incompatible type shapes retain
value/storage/parameter field context through dedicated importer error variants.

The generic foundational `import_value` path converges the three wire value
tags on owned `IRValue`, whose model stores only name and type; dedicated
storage and parameter DTOs reconstruct `IRStorage` and `IRParameter`.
Instruction-specific lifecycle sources are the exception added with Step
3D.1: `copy_init` and `assign` preserve wire `storage` as
`LifecycleSource::Storage`, while wire `value` and `parameter` become
`LifecycleSource::Value`. Import does not resolve names or infer kind from
identifier spelling.

Phase 3E.6 later applies the same tagged representation narrowly to
`IRReturn.value`, allowing IRV-026 to reject canonical `storage` operands even
when a same-named SSA value exists. Other ordinary instruction operands retain
the generic `IRValue` normalization described above.

Focused tests deserialize foundational entities from JSON where applicable and
cover every constant and value variant, storage, primitive and recursively
nested parameters, present and absent source locations, explicit null paths,
exact strings and identifiers, integer boundaries, finite floating-point bit
preservation, consuming and borrowed conversions, deterministic repeated
reconstruction, structural importer errors, and successful import of unresolved
references. Step 4B.3A begins the instruction importer; block, function,
struct-definition, and module import remain later steps.

### Step 4B.3A Rust lifecycle instruction importer

The instruction importer now exposes `import_instruction()` plus consuming and
borrowed `TryFrom<IRInstructionDTO>` implementations. It reconstructs 9 of the
68 schema-v1 instruction variants: `const`, `load`, `store`, `init_default`,
`copy_init`, `move_init`, `assign`, `destroy`, and `relocate`. The remaining 59
kinds fail explicitly with `IRImportError::UnsupportedInstruction`; they are
never dropped or approximated during this incremental implementation.

Each supported field delegates to the existing constant, value, storage, type,
and optional-source-location importers. Result and operand identities,
destination and source storage, constants, recursively nested types, signed
relocation counts, optional locations, and retained declaration ordering are
copied exactly. Nested structural failures are wrapped by
`IRImportError::InstructionField`, which reports both the instruction kind and
the exact offending field while preserving the typed source error. The existing
non-struct method-result receiver error remains the focused failure for an owned
type shape that cannot represent its wire input; no owned IR or wire schema
change was needed.

Import remains a structural adapter, not a verifier. It does not resolve value
or storage names, compare source and destination types, require a load slot to
be initialized, model later use after moves, enforce lifecycle or ownership
correctness, check dominance, or validate instruction placement. Consequently,
semantically invalid but structurally representable lifecycle instructions are
accepted for the verifier to diagnose later. Neither verifier nor compiler
pipeline behavior changes in this step.

Focused tests cover all nine variants through borrowed and consuming paths,
JSON-to-wire-to-owned conversion, present and absent source locations, primitive
and nested types, ordered enum metadata, exact constant/value/storage retention,
repeatable reconstruction, unresolved names, representable type mismatches,
nested field context, unsupported-kind rejection, and source DTO immutability.
Basic blocks, functions, struct definitions, modules, PyO3, verifier rules, and
pipeline integration remain later work.

### Step 4B.3B Rust operator and cast instruction importer

The same `import_instruction()` dispatch and its borrowed and consuming
`TryFrom<IRInstructionDTO>` paths now also reconstruct `binary_op`, `unary_op`,
`compare_op`, and `cast`. Together with Step 4B.3A, the importer supports 13 of
the 68 schema-v1 instruction variants. The other 55 kinds continue to return
`IRImportError::UnsupportedInstruction`; no parallel dispatch path was added.

The frozen wire fields are retained exactly: binary operations carry `result`,
`operator`, ordered `left` and `right` operands, and nullable
`source_location`; unary operations carry `result`, `operator`, and `operand`;
comparisons carry `result`, `operator`, ordered `left` and `right` operands, and
nullable `aggregate_shape`; casts carry target-typed `result` and source-typed
`value`. Every result and operand delegates to the foundational value and type
importers, and binary locations delegate to the optional source-location
importer. Nested failures therefore retain the instruction kind, exact field,
and typed source through the existing `IRImportError::InstructionField`. No new
import error or owned-model change was required.

The owned binary, unary, and comparison variants already store their operator
as an unrestricted owned `String`, matching the wire DTO representation.
Known spellings are copied without normalization, and structurally valid unknown
spellings are copied unchanged for the verifier to accept or reject. Comparison
shape entries and their ordering are likewise copied without interpretation.
The importer does not check operator/type combinations, operand compatibility,
result types, cast legality, dominance, or definition order. Structurally
representable mismatches import successfully, and verifier and compiler-pipeline
behavior remain unchanged.

Focused tests cover the operator inventories exercised by the frozen DTO
contract, representative casts, exact operand order, primitive and recursively
nested result/operand types, present and absent binary source locations, present
and absent comparison shapes, borrowed and consuming conversion,
JSON-to-wire-to-owned reconstruction, deterministic repeated reconstruction, DTO
immutability, unknown operator spellings, structurally valid type mismatches,
nested contextual failures, and continued rejection of a later instruction as
unsupported. Step 4B.3C adds calls and output. Blocks, functions, modules,
verifier logic, PyO3, and compiler-pipeline integration remain later work.

### Step 4B.3C Rust call-family instruction importer

The existing `import_instruction()` dispatch and its borrowed and consuming
`TryFrom<IRInstructionDTO>` implementations now reconstruct `call`,
`function_ref`, `call_indirect`, and `print`. The importer therefore supports
17 / 68 schema-v1 instruction variants; the remaining 51 kinds continue to
return `IRImportError::UnsupportedInstruction`, with no additional dispatcher.

The actual wire and owned fields align without a representation change. Direct
calls preserve `function`, ordered `arguments`, nullable `result`, nullable
`builtin`, and nullable `source_location`. Function references preserve their
typed `result` and exact `function` name. Indirect calls preserve the typed
`callee`, ordered `arguments`, and nullable `result`. Print instructions
preserve their typed `value`, `newline`, and nullable ordered
`aggregate_shape`. Empty argument lists remain empty, and function signatures
embedded in value types continue through the existing value and recursive type
importers unchanged. Optional locations continue through the existing
source-location importer.

Nested value/type failures retain the instruction kind and exact field through
`IRImportError::InstructionField`; no new importer error was required. Import
does not resolve direct function names, require indirect callees to exist or be
callable, validate signatures or builtins, count arguments, compare argument or
return types, or otherwise perform verifier work. Structurally representable
invalid calls import successfully. Verifier and compiler-pipeline behavior are
unchanged.

Focused tests cover direct calls with and without results, zero, one, and many
arguments, exact argument ordering, function references, indirect calls, print
instructions, nested function and collection types, all nullable call-family
fields, optional source locations, borrowed and consuming conversion,
JSON-to-wire-to-owned reconstruction, deterministic reconstruction, DTO
immutability, unresolved function names, signature and result mismatches,
nested contextual failures, and continued `UnsupportedInstruction` rejection
for struct instructions. The next planned instruction-importer family is
structs and method results. Collections, linear algebra, control flow, blocks,
functions, modules, verifier logic, PyO3, and pipeline integration remain later
work.

### Step 4B.3D Rust struct-family instruction importer

The existing `import_instruction()` dispatch and its borrowed and consuming
`TryFrom<IRInstructionDTO>` implementations now also reconstruct `struct_new`,
`struct_get`, `struct_set`, `method_result_new`, `method_result_receiver`, and
`method_result_value`. The struct importer is complete, bringing support to
23 / 68 schema-v1 instruction variants. The remaining 45 kinds continue to
return `IRImportError::UnsupportedInstruction`; no second dispatch mechanism
was introduced. The next instruction-importer family is collections.

The actual wire and owned layouts align directly. Struct construction preserves
typed `result` values and ordered `fields`; field reads and functional field
updates preserve typed `result` and `struct` values, signed `field_index`, exact
`field_name`, and, for updates, the replacement `value`. Method-result
construction preserves typed `result` and `receiver` values plus nullable
`value`; both extraction instructions preserve typed `result` and
`method_result` values. These variants have no source-location field. All nested
values and types continue through the existing recursive value and type
importers, and the nullable method value uses the existing optional-value path.

Nested structural failures retain the instruction kind and exact field through
`IRImportError::InstructionField`; the owned model can otherwise represent all
valid wire layouts in this family, so no new importer error was required. Names,
field spellings, field order, indices, receiver identities, result identities,
and nullable values are copied without normalization.

Import remains intentionally separate from verification. It does not resolve
struct definitions or field names, check duplicate or missing constructor
fields, compare field/value types, validate method receivers, or apply ownership
rules. Unknown names and structurally representable invalid combinations import
successfully for later verifier handling. Verifier and compiler behavior are
unchanged.

Focused tests cover every struct and method-result instruction, ordered and
duplicate constructor fields, recursively nested field and method-result values,
present and absent method values, exact field metadata, borrowed and consuming
conversion, deterministic JSON-to-wire-to-owned reconstruction, repeated import,
DTO immutability, unknown struct and field names, representable type mismatches,
nested contextual failures, and continued `UnsupportedInstruction` rejection
for collection instructions. Collections, linear algebra, control flow, blocks,
functions, modules, verifier logic, PyO3, and pipeline integration remain later
work.

### Step 4B.3E Rust collection instruction importer

The existing `import_instruction()` dispatch and its borrowed and consuming
`TryFrom<IRInstructionDTO>` implementations now reconstruct all 22 collection
instructions in the frozen schema-v1 contract. Together with the earlier
families, the importer supports 45 / 68 instruction variants. The remaining 23
linear-algebra and control-flow kinds still return
`IRImportError::UnsupportedInstruction`; no collection-specific dispatcher or
second conversion architecture was added. The next importer family is linear
algebra.

The actual array fields are: `array_new(result, elements)`,
`array_copy(result, array, source_location)`,
`array_get(result, array, index, borrowed, borrow_scope, source_location)`,
`array_slice(result, array, start, end, source_location)`,
`array_set(array, index, value)`, and `array_length(result, array)`. The actual
list fields are: `list_new(result, elements)`,
`list_copy(result, list_value, source_location)`,
`list_contains(result, list_value, value)`,
`list_index_of(result, list_value, value)`, `list_clear(list_value)`,
`list_push(list_value, value)`, `list_insert(list_value, index, value)`,
`list_remove_at(result, list_value, index)`,
`list_pop(result, list_value)`, `list_reverse(list_value)`,
`list_slice(result, list_value, start, end, source_location)`,
`list_get(result, list_value, index, borrowed, borrow_scope, source_location)`,
`list_set(list_value, index, value)`, `list_length(result, list_value)`, and
`list_is_empty(result, list_value)`. The shared operation is
`sequence_sort(sequence)`.

The frozen collection DTOs carry no separate element-type, length, capacity,
slice-step, comparator, ordering, or sort-direction fields. Indices and slice
bounds are typed `IRValueDTO` operands rather than integer metadata. Wire and
owned layouts match directly, including nullable `borrow_scope`, nullable
source locations, booleans, ordered constructor elements, and all nested value
types, so no owned-model change, integer conversion, or new importer error was
needed. The implementation reuses the existing value, ordered-value-vector,
optional-source-location, and contextual `InstructionField` helpers.

Import remains a structural boundary rather than a verifier. It deliberately
does not resolve names; require arrays, lists, or mutable operands; validate
element/result/index types; check bounds or slice coherence; prove non-empty
lists before `pop`; or validate whether a sequence can be sorted. Every
structurally representable mismatch is retained for verifier or runtime-safety
diagnosis. Verifier and compiler-pipeline behavior are unchanged.

Focused tests cover every collection variant through JSON-to-wire-to-owned,
borrowed, and consuming paths; empty, singleton, and ordered multi-element
constructors; primitive, nominal struct, and nested collection types; copies,
queries, mutation operations, slices, sorting, nullable borrow scopes, present
and absent source locations, deterministic reconstruction, DTO immutability,
unresolved names, invalid-but-representable semantics, and contextual nested
errors. A coverage audit asserts exactly 22 collection additions and confirms
all 23 later linear-algebra and control-flow variants remain explicitly
unsupported.

### Step 4B.3F Rust linear algebra instruction importer

The existing `import_instruction()` dispatch and its borrowed and consuming
`TryFrom<IRInstructionDTO>` implementations now reconstruct all 20 linear
algebra instructions in the frozen schema-v1 contract. Together with the prior
families, the importer supports 65 / 68 instruction variants. Only `branch`,
`jump`, and `return` remain explicitly unsupported; control flow is the next
instruction family.

The actual constructor fields are `vector_new(result, elements, orientation)`
and `matrix_new(result, elements, shape[rows, cols])`. Vector arithmetic is
`vector_add(result, left, right, shape[length], orientation)`,
`vector_sub(result, left, right, shape[length], orientation)`,
`vector_scale(result, vector, scalar, shape[length], orientation)`, and
`vector_dot(result, left, right, shape[length])`. The outer product is
`outer_product(result, column, row, shape[rows, cols])`.

Matrix arithmetic is `matrix_add(result, left, right, shape[rows, cols])`,
`matrix_sub(result, left, right, shape[rows, cols])`,
`matrix_scale(result, matrix, scalar, shape[rows, cols])`,
`matrix_mat_mul(result, left, right, shape[rows, inner, cols])`,
`matrix_vector_mul(result, matrix, vector, shape[rows, inner])`, and
`vector_matrix_mul(result, vector, matrix, shape[rows, cols])`. Element and
dimension operations are `vector_get(result, vector, index)`,
`matrix_get(result, matrix, row, column, shape[cols])`,
`vector_length(result, vector)`, `matrix_rows(result, matrix, shape[rows])`,
`matrix_columns(result, matrix, shape[columns])`,
`vector_set(vector, index, value)`, and
`matrix_set(matrix, row, column, value, shape[cols])`.

These instruction DTOs do not contain separate element-type, transpose,
general-metadata, or source-location fields. Element types remain embedded in
each typed result or operand. The only nullable instruction metadata is
`orientation` on vector construction, addition, subtraction, and scaling.
Fixed-size wire `shape` arrays map positionally to the owned named dimension
fields without reordering, normalization, or reshaping. Ordered constructor
elements and all result, operand, index, row, column, and scalar values continue
through the existing value, ordered-value-vector, recursive-type, nullable, and
contextual `InstructionField` helpers. Wire and owned layouts can represent the
same data, so no helper, importer error, wire-schema change, or owned-IR change
was required.

Import remains a structural adapter rather than a verifier. It does not check
dimensions, vector lengths, multiplication compatibility, orientations or
transpose correctness, invertibility, determinant domains, scalar or element
compatibility, mutability or ownership, dominance, or use-before-definition.
Negative, zero, extreme, and mutually inconsistent shapes, arbitrary
orientation spellings, unresolved values, and operand/result type mismatches
therefore import unchanged for later verifier diagnosis. Verifier and compiler
pipeline behavior are unchanged.

Focused tests cover every linear algebra variant through deterministic
JSON-to-wire-to-owned reconstruction and both borrowed and consuming paths;
representative ordered vectors and matrices; recursively nested element types;
present and absent orientation metadata; exact positional shape retention;
scalar and index operands; repeated reconstruction; DTO immutability;
invalid-but-representable dimensions, shapes, orientations, and type
combinations; and contextual nested importer errors. A coverage audit asserts
exactly 20 additions and confirms that exactly the three control-flow variants
remain unsupported.

### Step 4B.3G Rust control-flow instruction importer

The existing `import_instruction()` dispatch and its borrowed and consuming
`TryFrom<IRInstructionDTO>` implementations now reconstruct all three
control-flow instructions. This completes conversion coverage for all 68 / 68
frozen schema-v1 instruction variants. At this step the defensive
`IRImportError::UnsupportedInstruction` type still existed, although no current
`IRInstructionDTO` variant could reach it. Phase 2 Step 4B.3H performs the final
instruction importer completeness audit and resolves that dead path.

The actual control-flow fields are
`branch(condition, true_target, false_target)`, `jump(target)`, and
`return(value, transferred_storage)`. The return `value` is a nullable
`IRValueDTO`, and `transferred_storage` is a nullable `IRStorageDTO`. Wire and
owned layouts match directly, so no wire-schema or owned-IR change was needed.
Conditions and return values reuse the existing value and optional-value
importers; transferred storage reuses the storage importer; and nested failures
retain the instruction kind and exact field through
`IRImportError::InstructionField`. Destination strings, including empty,
unusual, unresolved, and identical branch targets, are copied exactly.

Import remains a structural adapter rather than a verifier. It does not check
that destination blocks exist, require branch targets to differ, require a
boolean condition, compare return values with a function return type, enforce
terminator placement or uniqueness, determine reachability, construct or
validate a CFG, or check dominance. Structurally representable invalid
control-flow instructions therefore import successfully. Basic-block,
function, and module importing remain unimplemented, and verifier, CFG, and
compiler-pipeline behavior are unchanged.

Focused tests cover branches, jumps, valued and empty returns, exact and
identical targets, empty and unusual unresolved destinations, primitive and
recursively nested condition and return types, nullable transferred storage,
borrowed and consuming conversions, deterministic JSON-to-wire-to-owned
reconstruction, repeated conversion, DTO immutability,
invalid-but-representable semantics, and contextual nested value and storage
errors. The existing authoritative 68-case wire inventory now also asserts that
every frozen instruction variant reaches a successful import path without
duplicating that inventory.

### Step 4B.3H Rust instruction importer completeness audit

Phase 2 Step 4B.3 is complete at an authoritative 68 / 68 frozen schema-v1
instruction variants. Completeness is enforced in layers: the conversion and
wire-kind matches are compile-time exhaustive and contain no wildcard arm; the
existing 68-case wire inventory remains the single authoritative list of wire
tags and checks exact tag uniqueness, deserialization, deterministic wire
round-trip, and successful borrowed and consuming import; and an exhaustive
wire-to-owned identity map asserts that every inventory case reaches its
intended owned `IRInstruction` variant. The identity map derives its own count
and is intentionally a variant mapping rather than a duplicated list of wire
tags. Consequently a wire-enum addition requires explicit importer and identity
mapping changes before compilation succeeds, while omitted or duplicate tags,
wrong owned variants, failed conversions, and any count other than 68 fail the
audit clearly.

`IRImportError::UnsupportedInstruction` was removed. Once every closed wire
enum variant had an exhaustive conversion arm, the error had no constructor,
caller, or concrete future-facing use; retaining it would have advertised an
unreachable public outcome. Future wire variants must add an explicit conversion
arm instead of falling through a wildcard. `import_instruction()` and the
borrowed and consuming `TryFrom<IRInstructionDTO>` APIs remain unchanged, as do
the remaining typed importer errors.

Cross-family audit tests preserve ordered vectors; present and absent nullable
values, storage, and source locations; booleans and signed integer metadata;
strings and names byte-for-byte; positional and aggregate shapes; borrow flags
and scopes; and return transferred storage. Nested failures across scalar,
ordered-vector, nested-signature/type, and control-flow instructions retain the
instruction kind, field name, and typed source-error chain. The importer has no
panic or string-only error path.

The importer remains only a structural adapter. It deliberately accepts
representable unresolved names and targets, incompatible operand and return
types, invalid collection indices, invalid linear-algebra shapes and
dimensions, and non-boolean branch conditions. Those are verifier
responsibilities; this audit adds no verifier, CFG, or compiler-pipeline
behavior and changes neither the frozen schema nor owned IR semantics. The next
step is basic-block importing.

### Step 4C Rust basic-block importer

The first hierarchical importer reconstructs an owned `IRBasicBlock` from an
`IRBasicBlockDTO` through the public `import_basic_block()` helper and borrowed
and consuming `TryFrom` implementations. Inspection confirmed that both models
have exactly two fields: `name: String` and an ordered instruction vector. The
importer copies the block name byte-for-byte and delegates every vector element
to the completed `import_instruction()` path without sorting, deduplicating,
normalizing, inserting instructions, or otherwise changing the sequence. Empty
and duplicate instruction sequences therefore remain exactly representable.
There is no nullable field or additional block metadata in the frozen DTO, so
neither the wire schema nor the owned block model changed.

An instruction conversion failure is wrapped in
`IRImportError::BasicBlockInstruction`, retaining the exact block name, the
zero-based instruction index, and the underlying typed importer error. Nested
field failures consequently preserve the complete block/index,
instruction-kind/field, and focused source-error chain without panics or
string-only errors.

Basic-block import remains structural reconstruction rather than verification.
It accepts empty blocks, missing or multiple terminators, instructions after a
terminator, unusual instruction ordering, unresolved targets, and independently
imported blocks with duplicate names. It does not check terminator placement,
reachability, CFG correctness, dominance, block uniqueness, or naming rules,
and it does not infer entry blocks or construct a CFG. Those remain verifier
responsibilities. Focused tests cover exact names, empty/single/multiple and
duplicate instruction vectors, ordering, invalid-but-representable control
flow, owned and borrowed conversion, deterministic JSON-to-wire-to-owned
conversion, DTO immutability, wire round trips, and contextual nested failures.
At completion of Step 4C, function importing was the next hierarchical layer;
module importing, verifier logic, CFG construction, compiler-pipeline
integration, and PyO3 remained out of scope.

### Step 4D Rust function importer

Phase 2 Step 4D is complete. Inspection of the actual Rust models found the
same four function-container fields on both sides of the boundary. The frozen
wire `IRFunctionDTO` has `name: String`, ordered
`parameters: Vec<IRParameterDTO>`, `return_type: IRTypeDTO`, and ordered
`blocks: Vec<IRBasicBlockDTO>`. The owned `IRFunction` has `name: String`,
ordered `parameters: Vec<IRParameter>`, `return_type: IRType`, and ordered
`blocks: Vec<IRBasicBlock>`. The sole representational difference is therefore
the intended conversion from nested wire DTO types to nested owned IR types.
There is no entry-block field, function metadata, storage summary, or CFG data
in either function model, and no frozen-contract mismatch required an owned IR
change.

The public `import_function()` helper and borrowed and consuming
`TryFrom<IRFunctionDTO>` paths reconstruct those four fields hierarchically
through the existing parameter, type, and basic-block importers. They retain
the function name byte-for-byte, preserve parameter and block order, and keep
empty vectors and duplicate names. They do not select or synthesize an entry
block, insert returns, normalize names, reorder or deduplicate contents, or
derive storage and control-flow information.

Nested failures add typed hierarchical context. `FunctionParameter` retains
the exact function name, zero-based parameter index, and the complete
parameter/type source chain. `FunctionReturnType` retains the function name,
the exact `return_type` field name, and the type source. `FunctionBasicBlock`
retains the function name, zero-based block index, exact block name, and the
complete basic-block/instruction/field source chain. Every wrapper participates
in `Error::source()`; no failure is flattened into a string and no importer
path panics.

Function import is structural reconstruction, not verification. It accepts no
blocks, no entry block, duplicate parameter or block names, mismatched declared
and returned types, invalid terminator placement, disconnected or unreachable
blocks, unresolved targets, and other invalid-but-representable contents. Name
uniqueness, parameter use, return compatibility, CFG connectivity, terminator
rules, dominance, reachability, and ownership or lifecycle semantics remain
verifier responsibilities. Focused tests cover empty, single, multiple,
duplicate, primitive, and recursively nested contents; exact ordering and raw
names; invalid-but-representable functions; deterministic JSON-to-wire-to-owned
conversion; borrowed DTO immutability; all conversion paths; contextual
failures; and complete typed source downcasting. Module importing is the next
step. Verifier logic, CFG construction, compiler-pipeline integration, schema
changes, PyO3, and owned IR semantic changes remain out of scope.

### Step 4E Rust module importer

Phase 2 Step 4E is complete. Inspection of the concrete Rust declarations found
that the frozen wire root contains `schema_version: i64`, ordered
`functions: Vec<IRFunctionDTO>`, and ordered
`structs: Vec<IRStructDefinitionDTO>`, in that order. The owned `IRModule`
contains ordered `functions: Vec<IRFunction>` and ordered
`structs: Vec<IRStructDefinition>`. Schema version is deliberately an envelope
concern and is therefore not stored in the owned compiler model. No module
name, imports, linkage, entry point, enum table, metadata, or layout data exists
in either actual model.

The wire `IRStructDefinitionDTO` contains `name: String` and ordered
`fields: Vec<IRStructFieldDTO>`; each field DTO contains `name: String` and
`type: IRTypeDTO`. The owned `IRStructDefinition` contains `name: String` and
ordered `fields: Vec<(String, IRType)>`. Thus the only struct-definition
representation mismatch is the intentional conversion of each named field DTO
into an owned `(field name, field type)` pair. Empty field vectors are supported
by both representations.

`schema_version` is a signed 64-bit integer and the only supported value is the
existing `IR_SCHEMA_VERSION = 1`. Wire deserialization already rejects any
other version. Because all `IRModuleDTO` fields are public and callers can
construct one directly, `import_module()` also rejects a non-v1 value with
`IRImportError::UnsupportedSchemaVersion`, preserving both the received and
supported versions. It does not silently normalize the envelope or duplicate
the wire check for successfully deserialized JSON.

The public `import_module()` and `import_struct_definition()` helpers, plus
borrowed and consuming `TryFrom` implementations, complete deterministic
wire-to-owned reconstruction. They reuse the type and function importers and
retain struct, field, and function order exactly, including empty sequences,
duplicate names, and raw strings. No declaration is sorted, deduplicated,
resolved, synthesized, or selected as an entry point.

Nested structural failures retain the complete typed context and
`Error::source()` chain. `ModuleStructDefinition` records the zero-based struct
index and exact struct name; `StructDefinitionField` adds the exact struct name,
zero-based field index, exact field name, and type-import source;
`ModuleFunction` records the zero-based function index, exact function name,
and existing function-import source. No module importer path panics or flattens
a nested error into a string.

Module import remains a structural boundary. Duplicate struct, field, and
function names; unknown or recursive nominal struct references; missing main
functions; and invalid-but-representable nested function or CFG contents import
successfully. Type-name resolution and cross-function/module calls belong to
symbol resolution and linking; struct legality and layout belong to the layout
phase; function, instruction, CFG, and other semantic invariants belong to the
verifier. The importer performs none of those jobs and does not invoke them.

Focused tests cover empty, struct-only, function-only, and mixed modules;
ordered and duplicate definitions and fields; primitive and recursive types;
unknown and self-recursive nominal references; invalid-but-representable
functions; both conversion ownership paths; source DTO immutability;
deterministic JSON conversion; direct unsupported-version construction; and
full contextual source-error downcasting. An integration-style test imports the
unchanged canonical schema-v1 golden JSON and verifies both top-level contents
and deeply nested types and instructions. The next step is the full
Python-JSON-to-Rust-owned-IR integration audit. Verifier execution, CFG
construction, layout, linkage, compiler-pipeline integration, PyO3, and an owned
IR exporter remain out of scope.

### Step 4F complete JSON-to-owned-IR integration audit

Phase 2 Step 4F is complete. `aether-ir` now exposes the small public
`import_module_json(&str)` convenience boundary. It composes one narrow strict
JSON decoder, the existing serde `IRModuleDTO`, and the existing
`import_module()` adapter; it does not introduce a second importer architecture.
The input is UTF-8 Rust text by construction. Non-standard/non-finite number
spellings, malformed JSON, and trailing input are rejected before DTO decoding.

The strict decoder exists only for this IR JSON boundary. Unlike a plain
`serde_json::from_str`, it detects duplicate object keys at every nesting level,
including duplicates inside fields that the wire DTO would subsequently reject
as unknown. Direct serde use by unrelated code is unchanged. After strict JSON
parsing, serde continues to enforce every required root and nested field,
explicit required nullable fields, exact tagged variants, primitive kinds,
fixed shapes, unknown-field rejection, and schema v1.

`IRModuleJsonImportError` preserves the boundary layers without string
flattening:

- `Json` wraps the original `serde_json::Error` for syntax, duplicate-key,
  trailing-input, and non-finite-number failures;
- `Wire` wraps the original `serde_json::Error` for a valid JSON tree that does
  not satisfy the frozen DTO shape, including missing or unknown fields and
  instruction tags;
- `SchemaVersion` wraps the typed `IRImportError::UnsupportedSchemaVersion` and
  retains both received and supported versions;
- `Import` wraps the complete contextual `IRImportError` chain for a wire DTO
  that the owned model cannot structurally represent.

Every wrapper implements `Error::source()`. A tested deeply nested failure
retains module function, function block, block instruction, instruction field,
value type, and invalid method-result receiver context all the way to the leaf.

The canonical golden
`tests/aether/rust_migration/fixtures/ir_module_v1_golden.json` is imported
through the complete boundary. Assertions cover its schema version, exact
struct and field ordering, nested array/struct and list/string types, function,
parameter and return types, block ordering, lifecycle initialization and source
location, branch targets, integer constant, and return value plus transferred
storage. A second end-to-end constructed document exercises UTF-8 names, nested
nullable/list/enum types, enum metadata and constants, explicit nullable call
fields, aggregate shape, borrow flag/scope, optional source path, and absent
return operands. Repeated imports compare equal using the owned model's existing
structural equality; no map iteration order participates.

The Phase 0 migration corpus was audited as follows:

- covered JSON module fixture: `ir_module_v1_golden.json` (the only JSON file in
  `tests/aether/rust_migration/fixtures/`), with a test that discovers and
  imports every JSON fixture in that directory;
- excluded `tests/aether/rust_migration/manifest.yaml`: it is a YAML index of
  pytest materializers and verifier expectations, not an `IRModuleDTO` JSON
  fixture;
- excluded source tests referenced by that manifest: they construct Python
  modules dynamically and no checked-in per-case module DTO JSON snapshots
  currently exist;
- excluded JSON elsewhere in `tests/`: those files belong to diagnostics,
  editor, release, or source-program fixtures and are not canonical migration
  module DTOs.

The existing cross-language golden generation is already reproducible and does
not need redesign: `tests/aether/test_ir_module_json.py` constructs a
representative Python `IRModule`, encodes it with `ir_module_to_json()`, and
compares it byte-for-byte with the checked-in golden. It also decodes and
canonically re-encodes the fixture byte-for-byte. Rust consumes that same file;
there is no Rust-specific golden and no generated fixture update in this step.

Import remains deliberately structural. An end-to-end test imports a module
with duplicate function names and no blocks, proving that semantic verifier
rules are not executed. No verifier, CFG, compiler pipeline, PyO3, exporter,
lowering, or owned-IR semantic behavior is connected or changed.

The complete schema-v1 cross-language contract is now audited, including its
existing Python byte generator/consumer test, so a separate Step 4G would add
no meaningful remaining contract work. The next planned migration step is
**Phase 3 verifier integration**, beginning behind the documented isolated
selection and differential-testing boundary rather than coupling verification
to this importer.

### Phase 3 Step 3A Rust IR type verifier — complete

Phase 3 Step 3A is complete. The `aether-verifier` crate now exposes the
borrowed, layered API `verify_module_types(&IRModule)`,
`verify_function_types(&IRModule, &IRFunction)`, and
`verify_block_types(&IRModule, &IRFunction, &IRBasicBlock)`. Module traversal
delegates to the function API, and function traversal delegates to the block
API; there is one instruction dispatch and no duplicate hierarchy walk. The
pass returns `Result<(), ...>` and never mutates the owned IR.

The implemented pass enforces exactly these invariants:

- struct field types use the Python verifier's type grammar, are non-void, and
  direct by-value struct layouts are finite; function parameter and return
  types and every instruction result type use that same grammar. As in Python,
  `FunctionType` signatures are not recursively type-validated;
- constants agree with their result type, including complete enum identity,
  member, and discriminant checks;
- loads and stores have exact slot/value type agreement, without checking slot
  existence, initialization, or liveness;
- scalar binary, unary, comparison, and cast operands/results follow the
  Python operator allowlists, exact-coercion rules, integer-division result,
  equality capability, numeric promotion, and cast allowlist;
- direct calls and function references resolve against the module and match
  parameter count/types and result presence/type; indirect calls require a
  `FunctionType` callee and exactly match its signature; non-lifecycle builtin
  calls match the Python verifier's argument and result signatures, including
  parsing/text-result layouts and scalar-math result rules;
- print operands belong to the Python verifier's printable type set;
- struct construction, field read, and field update use a declared nominal
  struct, canonical field count/index, exact field value/result types, and an
  exact struct result type; method-result construction and extraction match
  receiver/value component types and void result presence;
- array and list construction, get/set, slice, length, copy, membership,
  index lookup, clear, reverse, push, insert, pop, remove-at, emptiness, and
  sorting enforce their instruction-local container, index, element, result,
  equality-capability, and sortable-element type rules. Lifecycle capability
  portions of copy/slice are excluded;
- vector and matrix construction, arithmetic, scaling, multiplication,
  indexing, mutation, and size queries enforce aggregate operand/result kinds,
  exact or promoted element compatibility, scalar/index types, and vector
  orientation compatibility. Dimension, element-count, and shape metadata are
  excluded;
- `IRBranch` requires an exact `bool` condition type while leaving both target
  names unresolved, and `IRJump` has no additional type rule; and
- each `IRReturn` locally agrees with its containing function's declared return
  type, including value presence for void/non-void returns. Return placement,
  path coverage, storage transfer, and cleanup are excluded.

Errors are typed rather than rendered early. `ModuleTypeVerificationError`,
`FunctionTypeVerificationError`, `BlockTypeVerificationError`, and
`InstructionTypeVerificationError` retain the function name, block name,
zero-based instruction index, exact `InstructionKind`, and a typed
`TypeRuleError` containing the offending field plus expected/actual types when
the rule is a type mismatch. Every wrapper implements `Error::source()`, so a
nested module failure retains the complete module-to-rule source chain.
Traversal is deterministic and uses source vector order; duplicate declaration
lookup deliberately matches the Python verifier's last-definition dictionary
behavior while duplicate-name rejection remains deferred.

The Python verifier was classified before migration. The following checks are
intentionally **not** part of Step 3A:

- CFG: block presence, the `entry` block, reachability, block ordering,
  terminator presence/finality, jump/branch target resolution, CFG
  connectivity, and all-path return analysis;
- definitions and data flow: duplicate or empty declaration names, duplicate
  fields/parameters/blocks/values, undefined values or slots, name-to-type
  agreement, definition-before-use, slot stores, and merge-state consistency;
- dominance and SSA: dominance, phi placement/completeness, SSA
  single-definition rules, and edge-use semantics;
- ownership/lifecycle: borrowed-element scopes and escapes, lifecycle
  instructions and retain/release calls, storage initialization/move/destroy
  state, relocation traits/counts, copy/slice lifecycle traits, transfer
  storage, and cleanup at returns;
- non-type metadata and structure: aggregate print/compare shapes, matrix and
  vector dimension positivity, matrix literal element counts, retained
  row/column/length metadata, and canonical builtin semantic-name preservation;
  and
- every optimization invariant and all optimizer, CFG, LLVM, pipeline, PyO3,
  and code-generation integration.

Consequently, the Step 3A pass intentionally accepts modules that the complete
Python `IRVerifier` rejects for one of those deferred reasons. Within the
migrated type checks, acceptance/rejection follows the Python verifier; no
Python-verifier bug or intentional type-semantic deviation was discovered.
Importer behavior, the wire schema, canonical JSON, compiler pipeline, LLVM
backend, and owned IR semantics are unchanged.

### Phase 3 Step 3B Rust IR structural and basic-CFG verifier — complete

Phase 3 Step 3B is complete. The `aether-verifier` crate now also exposes
`verify_module_structure(&IRModule)` and
`verify_function_structure(&IRModule, &IRFunction)`. These APIs borrow and do
not mutate the owned IR. They remain fully independent of
`verify_module_types`, `verify_function_types`, and `verify_block_types`; no
mandatory combined verifier or compiler-pipeline integration was introduced.

The pass was derived from the structural subset of
`src/aether/ir/verifier.py`. It enforces these rules:

- nominal struct names and function names are unique at module level; nominal
  struct names are non-empty; struct field names are unique; parameter names
  and block names are unique within their function. Duplicate detection retains
  both the later and earlier source indices and completes before CFG target
  lookup can become ambiguous;
- every function contains at least one block and contains a block named exactly
  `entry`. This is the actual Python IR convention, not a first-block alias.
  `entry` may occur at any position in the retained block vector;
- the complete and only terminator set is `IRBranch`, `IRJump`, and `IRReturn`.
  Every block, including an otherwise empty block, must contain exactly one of
  these instructions in final position. A non-terminator in final position is
  not inferred to terminate the block, and no instruction may follow a
  terminator; and
- `IRBranch.true_target`, `IRBranch.false_target`, and `IRJump.target` are
  resolved by exact, case-sensitive raw-name equality against the unique blocks
  of the same function. True targets are checked before false targets, and
  `IRReturn` contributes no successor edge. Self-loops and back edges are valid.

The Python IR verifier does not reject unreachable blocks. It performs local
instruction checks in those blocks with a separate unreachable state, so this
Rust pass likewise accepts unreachable trailing blocks and unreachable cycles.
Reachability rejection is explicitly deferred rather than invented here.

Diagnostics preserve source/vector order at every level: structs, fields,
functions, parameters, blocks, instructions, branch true/false targets, and
unreachable acceptance are independent of hash-table iteration. The typed
hierarchy consists of `ModuleStructureVerificationError`,
`FunctionStructureVerificationError`, `BlockStructureVerificationError`, and
`ControlFlowRuleError`; it retains function/block names and indices, relevant
instruction indices and exact `InstructionKind`, raw target names, earlier
conflicting declaration indices, and expected/actual block termination shapes.
Every nested wrapper exposes its typed cause through `Error::source()`.

Acceptance and rejection match the inspected Python structural checks. One
diagnostic refinement is deliberate: when a block contains two terminators,
Rust reports the typed `MultipleTerminators` cause with both indices and kinds;
Python currently reports the broader "instruction after terminator" failure.
Both reject the same input. No Python structural bug was discovered.

The Step 3A type verifier remains independently callable and unchanged in
scope. In particular, branch-condition boolean validation and return-value type
validation remain type rules and are not duplicated here. Conversely, a
type-invalid but structurally well-formed function can pass Step 3B, and a
type-correct function with a missing terminator can fail Step 3B.

The following invariants remain intentionally deferred: CFG reachability and
connectivity requirements; all-path return analysis; value/slot uniqueness and
definition-before-use; SSA single-definition, phi, predecessor, renaming, and
dominance rules; ownership, borrowing, storage initialization, transfer,
cleanup, and lifecycle rules; aggregate/layout and optimizer invariants; and
all importer, wire-schema, canonical-JSON, owned-IR, compiler-pipeline, LLVM,
PyO3, and production-integration changes. Phase 3 Step 3C.1, described next,
is the isolated follow-up that owns SSA definition/use verification.

### Phase 3 Step 3C.1 Rust IR SSA definition-before-use verifier — complete

Phase 3 Step 3C.1 is complete. The `aether-verifier` crate now exposes the
borrowed, non-mutating APIs `verify_module_ssa(&IRModule)` and
`verify_function_ssa(&IRFunction)`. Module traversal delegates to function
verification, function verification collects one definition namespace and then
delegates source-ordered reference checks to each block and instruction. The
pass remains independent of the Step 3A type verifier and Step 3B structural
verifier: it neither invokes those passes nor introduces a combined pipeline.

An SSA **definition** is exactly one of the following in the owned Rust IR:

- an `IRParameter`, available before the function's first instruction; or
- the `IRValue` in an instruction's structural `result` field, available only
  after that instruction. `IRCall` and `IRCallIndirect` define a value only when
  their optional result is `Some`. All other result-bearing variants, including
  `IRConst`, `IRLoad`, `IRFunctionRef`, collection/aggregate operations, and
  `IRListPop`/`IRListRemoveAt`, define their retained result. Instructions with
  no result field and calls with `None` introduce no SSA definition.

The implementation reuses the exhaustive `instruction_result` classifier
already used by the type verifier, rather than maintaining a second producer
allowlist. The owned enum has no common operand iterator, so Step 3C.1 uses one
exhaustive verifier-local operand match. Rust exhaustiveness forces every new
instruction variant to classify its immutable value operands explicitly.

An SSA **use** is an immutable `IRValue` operand: scalar operands; direct-call
arguments; an indirect callee and its arguments; print, struct, method-result,
collection, and linear-algebra inputs; `IRStore.value`; the `Value` sources of
`IRCopyInit` and `IRAssign`; a branch condition; or an optional return value.
Operand vectors are checked in retained field/vector order. Instruction results
are definitions, not uses. `IRStorage` destinations/sources, load/store slot
names, transferred return storage, constant payloads and literal values,
function and block symbol strings, source locations, and other metadata are not
SSA uses. In particular, an `IRFunctionRef` result defines a temporary SSA value;
the referenced function-name string is a module symbol whose resolution remains
the Step 3A type verifier's responsibility.

Parameters and instruction results share one exact, case-sensitive,
function-local namespace. The pass reports the first repeated definition in
parameter/block/instruction source order and retains both definition locations.
After uniqueness succeeds, it checks uses in block/instruction/operand source
order. A use must resolve to a parameter or instruction result and must carry
the definition's exact `IRType`; this name-to-type agreement is reference
validity, not a repetition of Step 3A's instruction-local type rules. Within one
block, the defining instruction index must be strictly less than the use index,
so an instruction cannot use its own result. Results become available to the
next instruction immediately. Constant payloads do not require definitions.

Step 3C.1 deliberately makes no cross-block availability judgment. A definition
in any other retained block satisfies name resolution regardless of CFG path,
reachability, retained block order, or whether it dominates the use. This means
diamond/sibling uses that require a phi in executable SSA are accepted here.
The pass does not build a CFG, predecessor map, or dominator tree and does not
inspect phi nodes; the current owned initial-IR enum has no phi variant. These
rules belong to **Phase 3 Step 3C.2: Dominance verification**, alongside
edge-sensitive behavior once an owned phi representation exists.

Typed failures are `ModuleSSAError`, `FunctionSSAError`, `BlockSSAError`, and
`SSADefinitionError`. They retain function and block names, function/block and
instruction indices, exact `InstructionKind`, the SSA identifier, ordered
defining and duplicate-definition locations, and exact use locations including
operand index. Reference type mismatches retain expected and actual types.
Every nested wrapper implements `Error::source()`, preserving a downcastable
module-to-function-to-block-to-leaf chain. Diagnostics use vectors for emission
order; hash maps are used only for exact keyed lookup, never iteration.

Python inspection separated three behaviors. Both `src/aether/ir/verifier.py`
and `src/aether/ssa/verifier.py` collect parameters and instruction results into
a function-wide namespace, reject duplicates and unresolved value names, and
require a use to carry its definition's type. The SSA verifier also performs
same-block ordering in its dominance phase; that local rule is implemented here
without migrating cross-block dominance. The initial-IR verifier instead uses
CFG state intersection for reachable cross-block availability, while the SSA
verifier performs full ordinary-use and phi-edge dominance. Those stronger
cross-block behaviors are intentionally deferred, so Step 3C.1 accepts some
modules rejected by either complete Python verifier.

One existing Python initial-IR classifier bug was confirmed and is not copied:
its `_instruction_result` omits `IRListPop` and `IRListRemoveAt` even though its
instruction transfer treats both results as definitions. As a result, the
Python initial-IR verifier can miss duplicate definitions involving those two
results. The Python SSA verifier and the owned Rust result structure both treat
them as definitions; Step 3C.1 follows that actual semantic model and has a
focused regression test. No Python source was changed.

Dominance, dominator construction, phi placement/completeness/edge semantics,
predecessor analysis, reachability/data-flow merging, ownership, borrowing,
storage initialization/liveness, lifecycle, optimizer assumptions, importer,
wire schema, canonical JSON, owned IR semantics, compiler pipeline, LLVM, and
PyO3 are unchanged. The next step is **Phase 3 Step 3C.2: Dominance
verification**.

### Phase 3 Step 3C.2 Rust IR dominance verifier — complete

Phase 3 Step 3C.2 is complete. The `aether-verifier` crate now exposes
`verify_module_dominance(&IRModule)` and
`verify_function_dominance(&IRFunction)`. Both borrow their input and do not
mutate the IR. The pass remains independently callable and no mandatory
all-verifier pipeline was added. To remain safe when invoked directly, function
dominance first invokes only the function-local Step 3B structural verification
needed for an unambiguous CFG and Step 3C.1 SSA verification needed for a
unique, resolved definition namespace. Failures are wrapped as typed
prerequisite errors with their original, downcastable `Error::source()` chains.
The Step 3A type verifier is not invoked, so structurally and SSA-valid IR can be
dominance-assessed even when an unrelated instruction-local type rule is
invalid.

Python inspection confirmed that dominance has two different manifestations.
`src/aether/ir/verifier.py` verifies the initial executable IR using forward CFG
state and predecessor-state intersection; it has no explicit dominator pass.
`src/aether/ssa/verifier.py` constructs a CFG, runs
`aether.analysis.dominators.DominatorAnalysis`, and applies ordinary block
dominance plus edge-sensitive phi availability to Python SSA IR. Step 3C.2
copies the ordinary-use SSA behavior. This is appropriate for the owned Rust IR
because Step 3C.1 already classifies parameters and immutable instruction
results as one function-local SSA namespace. It does not copy Python phi rules:
Python SSA contains `SSAPhi`, but the current owned Rust `IRInstruction` enum has
no phi-like variant or edge-sensitive operand.

The function-local CFG records a block index for each exact name, uses the block
named exactly `entry` even when it is not first in retained order, preserves
jump or true/false successor order, and builds unique predecessor vectors in
retained source-block order. A branch whose two target fields are equal remains
valid as established by Step 3B; it contributes one effective predecessor. A
simple fixed-point set algorithm initializes `Dom(entry) = {entry}`, initializes
other reachable blocks to the reachable set, and repeatedly intersects the
dominator sets of reachable predecessors. This intentionally favors reviewable,
deterministic behavior over a more complex dominator-tree algorithm.

Parameters are definitions at function entry and are accepted in every valid
use, including uses in unreachable blocks. An instruction result used in a
different block must have a defining block that dominates the use block.
Same-block ordering remains exclusively Step 3C.1's diagnostic; Step 3C.2 does
not duplicate or contradict it. SSA operand extraction was narrowly shared with
Step 3C.1 and now retains each operand's field name while preserving the exact
existing field/vector traversal order. Constants, literal payloads, storage
operands, raw function names, and block target names remain outside the SSA-use
model.

Unreachable behavior follows the authoritative Python Initial IR verifier's
IRV-022 policy. Dominator analysis represents each unreachable block as a
self-root, but cross-block dominance is enforced only for entry-reachable use
blocks. Every collected value is locally available in a retained unreachable
block, including values defined in another unreachable component or in a
reachable block. A reachable use of an unreachable definition remains invalid.
This distinction matters for lowering-created dead loop increment blocks after
an unconditional return from the loop body.

Typed diagnostics are `ModuleDominanceError`, `FunctionDominanceError`,
`BlockDominanceError`, `DominanceRuleError`, and `DominanceUseLocation`.
`DefinitionDoesNotDominateUse` preserves function, use block name/index,
instruction name/index, operand index and field, exact SSA identifier,
definition and use locations, and the `entry` convention. Traversal selects the
first failure in function/block/instruction/operand source order; internal graph
collections do not select diagnostics. Repeated verification therefore yields
equal typed errors.

Focused tests cover parameters, diamonds, linear CFGs, multiple returns, loops,
self-loops, multiple back edges, entry definitions, loop-header definitions,
sibling/merge/ancestor failures, first-error ordering, exact case-sensitive
names, duplicate branch targets, `entry` outside vector position zero, every
documented unreachable case, prerequisite wrapping, same-block pass boundaries,
type-invalid independence, lifecycle deferral, module order, and complete
downcastable source chains.

No Python verifier bug or unavoidable ordinary-dominance parity difference was
found. Phi validation and predecessor-to-phi matching were not introduced;
there is no current owned representation on which a separate Step 3C.3 could
operate. The next real verifier work is therefore **Phase 3D:
ownership/lifecycle verification**. SSA renaming, dominance frontiers,
post-dominance, optimizer invariants, importer behavior, DTO/wire schema,
canonical JSON, owned IR semantics, compiler pipeline, LLVM, and PyO3 remain
unchanged.

### Phase 3 Step 3D.1 Rust IR local slot-state/lifecycle verifier — complete

Phase 3 Step 3D.1 adds the borrowed, non-mutating APIs
`verify_module_local_lifecycle(&IRModule)` and
`verify_function_local_lifecycle(&IRModule, &IRFunction)`. The function API
accepts the module because nominal struct lifecycle traits require module
definitions, matching the established shape of `verify_function_types`. The
pass is independently callable and runs no prerequisite pass: structure, SSA,
and dominance cannot establish any additional within-block fact, and invoking
them would make unrelated malformed IR mask a local lifecycle diagnostic.

Inspection covered `src/aether/ir/verifier.py`, `src/aether/ir/lifecycle.py`,
`src/aether/ir/model.py`, `src/aether/ir/lowering.py`, the lifecycle expansion
and LLVM layout/emission paths, Python SSA slot promotion, lifecycle tests and
`VALUE_LIFECYCLE_DESIGN.md`, plus the owned IR importer/value/instruction model
and all prior Rust verifier helpers. Python emits lifecycle before SSA,
expands it before LLVM, and performs local transfer plus predecessor
intersection and exit cleanup in one initial-IR verifier. Rust intentionally
extracts only the locally provable subset here.

#### Storage model and canonical effects

The owned initial IR has no explicit slot declaration list. Function-local
storage is implicitly introduced by the storage roles of `load`, `store`, the
six lifecycle opcodes, and `return.transferred_storage`. A deterministic index
records first occurrence and type in function/block/instruction/field order;
map iteration never chooses a diagnostic. A repeated name with another type is
reported at the conflicting operand with both locations. This representation
has no module globals, separate address objects, or aggregate-field storage.
Because every storage-role occurrence introduces the implicit function-local
slot, `UnknownStorage` and `DuplicateStorage` are not representable rules.

Storage and immutable SSA values are separate namespaces. Parameters begin as
available SSA values but do not initialize same-named storage. Temporary and
instruction-result values do not carry slot lifecycle state. Owned
`copy_init` and `assign` source fields use
`LifecycleSource::{Value, Storage}`. The importer maps canonical wire `value`
and `parameter` to `Value` and maps wire `storage` to `Storage`; no namespace is
inferred from a name.

| operation | reads storage | initializes destination | requires live destination | consumes source | destroys | type policy |
| --- | --- | --- | --- | --- | --- | --- |
| `load` | slot | no | no | no | no | lifecycle pass only checks slot state |
| `store` | no | yes, unconditionally | no | no | no | raw pre-SSA slot initialization/overwrite |
| `init_default` | no | yes | no | no | no | non-void and `supports_default` |
| `copy_init` | source only when tagged storage | yes | no | no | no | source storage live when known; exact source/destination type; trivial and managed allowed |
| `move_init` | source | yes | no | yes, to `Moved` | no | exact non-void type; self alias forbidden |
| `assign` | source only when tagged storage | no | yes | no | no | source storage live when known; exact source/destination type; self assignment remains valid |
| `destroy` | target's live value | no | target must be live | no | yes, to `Destroyed` | every non-void type, including trivial types |
| `relocate` | source | yes | no | yes, to `Moved` | no | positive count, exact trivially-relocatable type, self alias forbidden |
| return transfer | transferred storage | no | storage must be live | ownership leaves at terminator; no following local state | no | non-void and same type as returned value |

`store` follows actual Python behavior: it is neither lifecycle `assign` nor
`copy_init`; it makes the raw slot live even after an earlier destroy or move,
and repeated stores are allowed. `copy_init` leaves its immutable source alive.
`move_init` and `relocate` invalidate storage sources. `destroy` is valid and
tracked even when the type's generated destruction hook is a no-op. No
lifecycle check is restricted solely to managed types.

The local trait registry reproduces Python classification. Int/float/double/
bool/complex/enum support default and trivial relocation. String and Array/List
handles support default and relocation while retaining non-trivial copy and
destroy semantics. Vector supports default only with `row` or `column`
orientation and remains relocatable; Matrix remains relocatable without a
dimension-free default; Function is relocatable without a default;
ClassRef/Interface/Nullable have no current lifecycle layout; Void has no
storage. Struct and MethodResult traits compose recursively in field order.

#### Block-entry policy and diagnostics

The state lattice is `Unknown`, `Uninitialized`, `Initialized`, `Moved`, and
`Destroyed`. All indexed storage starts `Uninitialized` in a block named
exactly `entry`, matching Python's empty entry slot set. Every non-entry block,
reachable or not, starts `Unknown` because predecessor propagation is Step
3D.2. `Unknown` is neither assumed valid nor invalid. A precondition on it is
therefore accepted, while the operation's successful postcondition becomes a
local fact. For example, a first destroy in a merge block is deferred, but a
second destroy or load later in that same block is certainly invalid.

Typed diagnostics are `ModuleLifecycleError`, `FunctionLifecycleError`,
`BlockLifecycleError`, and `LifecycleRuleError`, with public
`LocalSlotState`, `LifecycleOperation`, `LifecycleStorageRole`, and
`LifecycleInstructionLocation` context. Implemented leaf rules cover storage
type conflict, lifecycle source/destination type mismatch, invalid default or
relocation type, invalid relocation count, forbidden move/relocate self alias,
double initialization, use before known entry initialization, local use after
move/destroy, assignment to known-uninitialized storage, destroy of
known-uninitialized storage, double destroy, and return-transfer type mismatch.
Errors retain function/block/instruction indices and names, instruction kind,
field role, identifier, type, previous and attempted states, and exact prior
and current transition locations where a prior local transition exists. All
wrapper `Error::source()` chains remain downcastable and repeated runs produce
equal errors.

#### Fidelity correction and next step

The lifecycle-source audit classified the previous importer collapse as an
owned-IR fidelity bug. The smallest correction adds `LifecycleSource` only to
owned `copy_init`/`assign` and their importer/verifier paths. Canonical JSON,
Python DTOs, and Rust wire DTOs already carried the exact tag and did not
change. Regression fixtures cover value, parameter, and storage sources;
uninitialized, moved, and destroyed storage; managed copies; and identical SSA
and storage spellings. Storage sources no longer become undefined SSA uses,
and same-named SSA definitions cannot mask invalid storage state.

Python still propagates state through its CFG, intersects predecessor states,
rejects inconsistent branch lifecycle state, and checks complete cleanup at
returns. Step 3D.1 deliberately does none of that CFG, loop, or cleanup work.
Tests show that merge/loop reads and branch-dependent initialization, destroy,
or move are accepted as `Unknown`, while the same invalid transitions are
rejected once established in one block.

The next recommended step is **Phase 3 Step 3D.2: inter-block lifecycle data
flow and CFG state merging**. Predecessor propagation, fixed points, join
merging, loop-carried state, complete move/return ownership, cleanup/leak
guarantees, borrowing, alias analysis, optimizer invariants, pipeline
integration, LLVM behavior, PyO3, wire schema, canonical JSON, and DTO contract
remain unchanged.

### Phase 3 Step 3D.2 Rust IR inter-block lifecycle data flow — complete

Step 3D.2 adds `verify_module_lifecycle(&IRModule)` and
`verify_function_lifecycle(&IRModule, &IRFunction)` while preserving both
3D.1 local APIs. The complete pass invokes only function structural
verification: a validated CFG is required, while immutable SSA definitions and
dominance are separate namespaces and remain independently callable. Typed
`FunctionLifecycleVerificationError` and `ModuleLifecycleVerificationError`
wrappers preserve structural-prerequisite and block-rule `Error::source()`
chains.

Inspection covered Python `src/aether/ir/verifier.py` (`_State`,
`_verify_reachable_values`, lifecycle instruction transfer, storage-source
checks, return transfer and unreachable handling), Python lifecycle expansion,
CFG/SSA tests and utilities, and the owned Rust CFG, lifecycle verifier,
instruction model, importer and lowering sites. Python represents live, moved,
and destroyed as separate definite sets, intersects incoming states, starts
entry storage absent/uninitialized, and deliberately gives each unreachable
block one all-slots-live non-propagated IRV-022 state. It also reports IRV-036
while edges are still being
processed. That early report is order-sensitive and rejects a join block whose
first instruction is an unconditional raw `store`, even though the transfer
overwrites every incoming state. Rust treats this as a confirmed analysis-timing
bug: it converges first and validates once, allowing total transfers to repair
uncertainty while still rejecting path-sensitive reads.

The Rust domain is the finite powerset of `Uninitialized`, `Initialized`,
`Moved`, and `Destroyed`; the empty set is fixed-point bottom. `Unknown` remains
reserved for focused local verification. Join is set union, so it is
deterministic, commutative, idempotent, and monotone.
Function entry contributes `Uninitialized` for every implicitly indexed slot.
SSA parameters are not storage and do not affect this state. Each block exit is
computed by the same canonical 3D.1 transition table used for final validation:
`store` is a total `Initialized` transfer; init/copy initialize destinations;
move/relocate initialize destinations and move storage sources; assign leaves a
valid destination initialized; destroy produces `Destroyed`; loads and return
transfers do not change slot state. For managed storage the total raw-store rule
proves slot state only. A hand-authored raw store can still leak an overwritten
owner or omit an input retain; lifecycle expansion supplies retain/release for
the managed copy/assign stores it emits, while complete ownership and leak
guarantees remain deferred.

A stable FIFO worklist starts with reachable blocks in retained order. The
entry is found by exact name and need not be stored first. Predecessors and
successors come from shared `cfg.rs`; duplicate branch edges are deduplicated
for predecessor merging and cannot destabilize convergence. Entry state is
also joined on back-edges, which correctly models self-loops and repeated entry
execution. The finite domain needs no widening. After convergence, blocks and
instructions are replayed in function/block/instruction/field order. Merged
precondition failures use `LifecycleRuleError::InvalidMergedState` with the
complete `PossibleSlotStates` set and required state; worklist order never
selects the user-visible error.

Only entry-reachable components participate in the fixed point. Python IRV-022
deliberately checks every retained unreachable block independently with all
collected values and slots available. Rust now reproduces the storage half of
that policy exactly: every slot starts `Initialized`, and unreachable edges,
cycles, and self-loops do not propagate facts between blocks. This can reject a
first initialization in dead code, but it is an explicit local-checking policy,
not a statement that an executable path initialized the slot. The 3D.1 local
API continues to use `Unknown` for non-entry blocks because it has no CFG
reachability information.

Trivial and managed types use identical state-flow rules. Lifecycle traits are
still consulted only for operations that need them, and tagged
`LifecycleSource::Storage` sources participate in slot state while immutable
value sources do not. Tests cover all-predecessor and partial initialization,
moved/destroyed storage sources, raw-store repair, independent unreachable
components, entry-not-first, duplicate targets, stable diagnostics, loop-carried
live state, zero-iteration exits, move on a back-edge, and self-loop convergence.

Complete cleanup on every return and leak detection were the next 3D.3 slice.
Destruction insertion, lifecycle expansion, ARC optimization, ownership
inference, borrowing, new alias analysis, importer/schema changes, pipeline
integration, LLVM, and PyO3 remained intentionally unchanged in 3D.2.

### Phase 3 Step 3D.3 function-exit ownership completeness — complete

Step 3D.3 extends the existing `verify_module_lifecycle(&IRModule)` and
`verify_function_lifecycle(&IRModule, &IRFunction)` APIs. No new analysis or
pipeline API was added. After the 3D.2 fixed point converges and every retained
block has been replayed for deterministic transition diagnostics, the verifier
reads the already-stabilized exit-state map for each entry-reachable `return`
block. Each return is checked independently in retained block order; therefore
one valid early return cannot hide a leaking later return. Conditional returns,
loop exits, recursive functions, constructors, and lowered methods need no
special CFG rule because they are ordinary `IRFunction` returns. Structural
verification disallows implicit fallthrough, and void functions leave through
an explicit bare return. Retained unreachable returns still receive Python's
independent all-slots-live local checks but are excluded from ownership
completion because no executable path reaches them.

The ownership domain remains the 3D.2 slot domain. A storage name participates
in the exit contract only after appearing in `init_default`, `copy_init`,
`move_init`, `assign`, `destroy`, or `relocate`, matching Python's
`_is_lifecycle_storage`. Raw load/store-only slots are not newly classified as
generic lifecycle owners, although a raw store to an already-classified slot
updates its state and can create an exit leak. A covered slot is complete in
`Uninitialized`, `Moved`, or `Destroyed`. `Initialized` is valid only when the
same return names that exact live slot as `transferred_storage`; a mixed state
containing `Initialized`, such as `{Initialized, Destroyed}`, is incomplete.
This makes branch-dependent partial whole-aggregate destruction observable at
the exit without rerunning or duplicating transfer analysis.

Return transfer is explicit and intentionally narrow. The marker must refer to
live non-void storage and its type must equal the returned SSA value type.
Python and Rust do not prove provenance from the transferred slot to the
returned SSA value. `move_init` and `relocate` move ownership between storage
slots, leaving the source `Moved` and destination `Initialized`; they do not
transfer ownership outside the function until the destination is named by a
return marker. Copy and assignment do not consume a storage source. There is no
separate ownership-transfer opcode in the current owned IR. Compiler-generated
retain/release, defaulting of moved managed values, and temporary-value cleanup
remain post-verification lifecycle-expansion behavior.

Python `src/aether/ir/verifier.py`, `lifecycle.py`, `lowering.py`, `model.py`,
`cfg.py`, and `interpreter.py` were inspected together with lifecycle,
interpreter, verifier, lowering, and control-flow tests. Verification occurs on
generic lifecycle IR before `expand_lifecycle()`; both SSA builders invoke
expansion after this boundary. Python requires completion for all lifecycle
storage, including trivial types. Rust matches that behavior: `String`,
`Array`, and `List` need destruction; structs and method-result storage inherit
managed status recursively from nested fields; trivial scalar, enum, vector,
and matrix slots still need an explicit terminal lifecycle state even though
their destructor expands to no runtime work. Parameters and ordinary temporary
results are SSA values rather than storage and are not exit owners unless copied
into a slot. Destroy completes the aggregate slot as a unit because the current
IR has no field-path storage state.

The new leaf diagnostic is
`LifecycleRuleError::IncompleteOwnershipAtExit`. It retains slot identifier and
type, exit block and return location, actual and expected state sets, an
`OwnershipCompletionReason`, and the last transition location when 3D.2 could
preserve it. `LifecycleStorageRole::ExitOwner` identifies the block wrapper.
All existing module/function/block/rule `Error::source()` links remain
downcastable. Exit failures use retained block order and lexicographic slot-name
order, matching Python's sorted missing-cleanup names and remaining independent
of worklist order.

Step 3D.3 does not insert destruction, rewrite IR, expand lifecycle operations,
optimize ARC, infer ownership, add borrowing or alias analysis, change LLVM,
alter importer/schema contracts, or integrate the production pipeline. The
next recommended verifier work is borrowing/escape completeness and remaining
Python IRV rule-family parity, followed by a separately authorized differential
integration step. Cleanup insertion stays in lowering/lifecycle expansion.

### Phase 3 Step 3E.1 non-void all-path return verification — complete

Step 3E.1 adds the borrowed, non-mutating APIs
`verify_module_returns(&IRModule)` and
`verify_function_returns(&IRFunction)`. They implement only IRV-024 and remain
independently callable; no combined verifier or compiler-pipeline integration
was added. The function API invokes the Step 3B function-local structural
prerequisite so block names, final terminators, targets, and `entry` are
unambiguous. Structural failures retain their complete typed source chains.
No type, SSA, dominance, or lifecycle pass is invoked.

Void functions are exempt once their structure is valid. Non-void analysis is
rooted at the block named exactly `entry`, wherever it occurs in the retained
block vector. A valued `IRReturn` proves a path; a valueless `IRReturn` does
not. A jump follows its single target, and a branch requires both true and false
targets to prove a return in retained field order. Unreachable blocks are not
visited and therefore create no return-path obligation, matching Python
IRV-024 rather than inventing a reachability requirement.

This family intentionally checks only whether a return value is present. The
value's declared type, definition, same-block ordering, dominance, and any
transferred-storage contract remain the independent Step 3A, 3C, and 3D rules.
Consequently, return verification can accept a valued return whose operand is
otherwise type- or SSA-invalid, while those dedicated passes reject it.

The Rust pass uses a depth-first entry-reachability walk. A visited set makes
every cycle a non-exiting path regardless of label spelling; all reachable
return terminators must carry a value. The LIFO worklist enqueues false before
true targets so true-target traversal remains first for deterministic failure
selection. This is linear in blocks plus CFG edges and requires no data-flow
lattice or fixed point.

Audit found that Python's `_block_returns` is nominally sensitive. Its recursive
visiting-set check returns true for a revisited block only when the block name
starts with `cond` or `for.cond`; all other revisited labels return false.
Consequently Python accepts lowering-shaped `cond0` and `for.cond0` loops but
rejects bijectively renamed isomorphic graphs. IR v1 defines labels as branch
and jump identifiers with no runtime meaning, while deterministic loop names
are only lowering output. Rust therefore follows the structural IR contract
rather than preserving this Python naming heuristic.

`ReturnPathRuleError::ValuelessReturn` retains the stable block name and index
plus the return instruction index. `FunctionReturnVerificationError` adds the
declared non-void type and entry convention or wraps a structural prerequisite;
`ModuleReturnVerificationError` retains the first failing function in source
order. Every wrapper exposes a downcastable `Error::source()`.

Focused tests cover single and multiple returns, jumps and branches,
true-before-false failure ordering, pure and optional-return cycles under
`cond`, `for.cond`, `loop`, `arbitrary_name`, and `xyz`, bijectively renamed
while- and for-shaped CFGs, unreachable invalid components, void exemption,
structural prerequisites, verifier-family independence, module ordering, and
diagnostic determinism. Separate Python characterization tests record its
current nominal sensitivity for the same graphs and for actual lowered loops.

Canonical JSON, Python DTOs, Rust wire DTOs, importer semantics, lifecycle
expansion, SSA construction, optimizer behavior, compiler integration, LLVM,
and PyO3 are unchanged. No other verifier family is included in this step.

### Phase 3 Step 3E.2 aggregate metadata verification — complete

Step 3E.2 extends the existing borrowed, non-mutating type-verifier APIs; it
does not introduce a second aggregate verifier or a combined pipeline. Existing
scalar/vector/matrix type, operand, orientation, equality, and numeric-promotion
checks remain the sole owners of those rules. This step adds only the retained
metadata contract from Python's initial-IR verifier.

Python inspection established these exact behaviors:

- scalar compare and scalar/non-vector/non-matrix print carry no aggregate
  shape, including no present-but-empty shape;
- vector and matrix compare support their existing equality contract only with
  positive shapes of exact rank one and two;
- vector and matrix print require shapes of exact rank one and two, but do not
  test dimension positivity, so zero and negative print dimensions remain
  accepted for parity;
- the signed `length` on vector add/subtract, scale, and dot is positive;
- every retained row, inner, column, or matrix-stride dimension on matrix
  construction/arithmetic/multiplication/indexing/query instructions is
  positive; and
- a matrix literal is a flat element sequence whose count is exactly
  `rows * columns`. No other layout consistency is checked. `IRVectorNew` has
  no retained signed length and Python accepts zero elements.

The Rust dispatcher passes those fields into the existing instruction-specific
verification helpers. Narrow shared helpers implement shape rank/presence,
vector-length positivity, and ordered matrix-dimension positivity without
duplicating element-type rules. Matrix cardinality uses an `i128` product,
preserving the Python arbitrary-precision comparison boundary for all retained
`i64` dimensions without verifier overflow.

The new typed leaves are `TypeRuleError::InvalidAggregateShape`,
`InvalidVectorLength`, `InvalidMatrixDimensions`, and
`InvalidMatrixCardinality`. They expose actual retained metadata plus the
required rank, positivity property, or expected/actual element counts. The
existing `InstructionTypeVerificationError`, block, function, and module
wrappers retain exact instruction identity and complete downcastable source
chains.

Rust tests cover scalar, vector, and matrix compare/print; missing, empty,
wrong-rank, zero, and negative shapes; every vector length and matrix dimension
field; matrix literal underflow/overflow; empty vector literals; and `1x1`,
`1xN`, and `Nx1` boundaries. Focused Python characterization tests were added
where prior coverage did not freeze compare/print shape and empty-vector
behavior. No Python verifier bug was discovered. There are no remaining
aggregate metadata gaps in IRV-075–076, IRV-078, or the metadata portions of
IRV-107–124.

Remaining initial-IR verifier work includes borrowed-element scope/escape rules
(IRV-037–042), the lifecycle-trait portions of collection copy/slice rules, and
canonical builtin semantic-name checks. Importer, canonical JSON, Python DTOs,
Rust wire DTOs, lifecycle, ownership, borrow-verifier behavior, optimizer, LLVM,
compiler-pipeline integration, and PyO3 remain unchanged.

### Phase 3 Step 3E.3 canonical builtin identity and retain/release — complete

Step 3E.3 extends the existing borrowed, non-mutating type-verifier APIs and
their single builtin dispatch. It adds no second builtin verifier and invokes
no other verifier family.

Python inspection separated three contracts. Existing signature checks validate
argument/result types, parsing and file-result layouts, and scalar-math result
selection. Canonical identity is independent: for every builtin family in
IRV-055–067, the retained `IRCall.function` string must equal
`IRCall.builtin` exactly. Consequently a different builtin with the same
signature, a compatible user function, an alias, or a renamed function is
rejected. The verifier does not resolve a builtin-tagged call through the module
function dictionary, so a user declaration with the exact canonical spelling
does not shadow the builtin and does not change acceptance. If both the function
and semantic builtin tag are renamed, exact identity alone is insufficient: the
renamed tag is handled by the existing unsupported scalar-builtin path.

Python IRV-066 gives retain and release the same shallow semantic contract.
`__aether_retain` and `__aether_release` retain canonical identity, take exactly
one argument, and produce no result. The accepted top-level types are exactly
`StringType`, `StructType`, `MethodResultType`, `ArrayType`, and `ListType`.
The verifier does not recursively ask whether a struct field or collection
element needs runtime destruction; scalar-only structs and collections are
therefore accepted. Primitive scalars, enums, vectors, matrices, nullable,
function, class/interface, void, and other top-level types are rejected. This
phase changes verification only and does not alter runtime ARC or ownership
transfer.

The new deterministic typed leaves are
`TypeRuleError::InvalidBuiltinIdentity`,
`InvalidRetainReleaseSignature`, and `InvalidRetainReleaseType`. They expose the
semantic builtin, expected/actual function spelling, retained argument/result
shape, and offending type as applicable. Existing `InstructionKind::IRCall`,
block, function, and module wrappers preserve the complete downcastable source
chain.

Focused Rust tests cover every builtin family's identity gate, canonical calls,
same-signature wrong builtins and user functions, aliases, renaming, the exact
retain/release allowlist, primitive/enum/aggregate/unsupported types, arity,
unexpected results, deterministic rendering, and structured downcasting.
Python characterization tests freeze the previously uncovered name-only lookup
and shallow retain/release behavior. No Python verifier bug was discovered, and
no builtin gap remains in IRV-055–067.

Remaining initial-IR verifier families are borrowed-element scope/escape rules
(IRV-037–042) and the lifecycle-trait portions of collection copy/slice rules.
Importer, canonical JSON, Python DTOs, Rust wire DTOs, lifecycle transfer,
ownership, borrow verification, optimizer, LLVM, compiler-pipeline integration,
and PyO3 remain unchanged.

### Phase 3 Step 3E.4 collection lifecycle capability verification — complete

Phase 3 Step 3E.4 closes the lifecycle-trait portions of IRV-091, IRV-094, and
IRV-097 in the existing instruction-local type verifier. The verifier reuses
`LifecycleTypeRegistry`; it adds neither a collection-specific pass nor a
combined pipeline. `IRArrayCopy`, `IRListCopy`, and `IRListSlice` inspect the
direct element type. `IRArraySlice` performs only its existing operand, bound,
and result-type checks and deliberately has no lifecycle-capability gate.

Python does not query `copy_init`, `assign`, `destroy`, `move_init`, `relocate`,
`trivially_copyable`, `trivially_relocatable`, `needs_destroy`, or
`supports_default` individually for these collection instructions. The exact
contract is only that `LifecycleTypeRegistry.traits(element).reason` is `None`.
Rust represents that as the single typed collection capability `Lifecycle` and
retains the registry's rejection reason in the diagnostic.

This classification is shallow and contains two important Python behaviors.
Array/List elements advertise lifecycle support at the handle level regardless
of their own element type, so nested collections containing unsupported types
are accepted. Defined struct and method-result aggregate traits do not propagate
child error reasons, so structs containing class/interface/nullable fields are
also accepted. Function values have no default but their Python lifecycle
traits have no error reason, so they are accepted. Direct matrix, unoriented
vector, class, interface, nullable, void, and unresolved-struct elements have a
reason and are rejected when otherwise valid IR reaches the rule. Rust does not
strengthen any of these cases recursively.

The deterministic typed leaf
`TypeRuleError::MissingCollectionLifecycleCapability` exposes the exact
`InstructionKind`, `CollectionKind`, element `IRType`, required
`CollectionLifecycleCapability`, and lifecycle reason. The existing instruction,
block, function, and module errors preserve the full downcastable source chain.
Focused Rust tests cover supported scalar, managed, struct, function, and nested
elements; direct unsupported managed, matrix, and nullable elements; the
array-slice exclusion; stable diagnostics; and downcasting. Added Python
characterization tests freeze the direct-only rule and instruction set.

No Python verifier bug was discovered. The non-recursive aggregate and nested
collection behavior is counterintuitive but consistent with the current
`LifecycleTypeRegistry` implementation and is now explicitly characterized.
There are no remaining collection lifecycle-capability gaps. Remaining
initial-IR verifier work is borrowed-element scope/escape verification
(IRV-037–042). Importer, canonical JSON, DTO/wire models, lifecycle transfer,
ownership transfer, runtime, optimizer, pipeline integration, LLVM, and PyO3
remain unchanged.

### Step 3E.5: borrowed-element scope and escape parity

Step 3E.5 completes the final semantic verifier family before the parity audit.
The existing type-verifier traversal now performs the same two source-order
scans as Python's `_verify_borrowed_elements`; no standalone borrow data-flow
engine or combined compiler pipeline was added. The first scan records only
borrowed `IRArrayGet` and `IRListGet` results. The second applies the narrow
store, return, and mutation-receiver rules by exact result name. The shared
lifecycle registry supplies the existing recursive `needs_destroy` fact for
IRV-040.

The exact Python contract is:

- IRV-037 rejects a missing or empty scope on a borrowed collection get.
- IRV-038 requires the declared scope to equal the defining block's exact name.
- IRV-039 rejects any non-`None` scope on an owned get, including `""`.
- IRV-040 rejects direct `IRStore` of a destruction-requiring borrow unless an
  `__aether_retain` for that value occurred earlier in the consumer block.
- IRV-041 rejects direct return of the borrowed value even after retain.
- IRV-042 rejects borrowed receivers of array set; list set, push, insert,
  remove-at, pop, clear, and reverse; sequence sort; and struct set.

Borrow scope is definition-block metadata, not a lexical or CFG lifetime.
Cross-block reads are accepted when the ordinary SSA/dominance rules make the
value available. Python has no use-after-end, borrow-after-move, unique-consumer,
alias, generic call-consumer, global-storage, or general aggregate-escape check
in initial IR. A borrowed collection can be the source of another borrowed get;
copy-init, repeated reads, aggregate construction, and type-correct calls are
accepted. `IRStore` of a trivial borrowed value is accepted without retain;
retain acquisition is block-local; release does not acquire. Invalid non-array/
list sources and invalid calls remain their existing collection/call rules, not
new borrow diagnostics. The owned IR contains no global-assignment variant.

`BorrowRuleError` is the typed borrow leaf and `BorrowRule` carries the exact
IRV identifier. Diagnostics retain the borrow-producing instruction, borrowed
value and type where relevant, definition/consumer locations, declared and
defining scopes, and mutation consumer. `TypeRuleError::BorrowViolation`
preserves the existing downcastable instruction/block/function/module source
chain. Deterministic selection follows function, block, and instruction source
order; no diagnostic depends on hash iteration.

Focused Rust tests cover local, nested, cross-block, and dominated uses;
same-block retain/store acquisition; scope failures; managed versus trivial
stores; return after retain; all mutation receiver variants; accepted aggregate,
call, copy-init, and repeated-use boundaries; ordinary invalid sources/calls;
stable rendering; and downcasting. Added Python characterization tests pin the
previously under-covered scope, lifecycle, cross-block, aggregate, call, copy,
and invalid-source behavior. No new Python verifier bug was discovered. Its
lack of general lifetime and escape analysis is surprising but was already an
explicit boundary in `IR_VERIFIER_INVARIANTS.md`, so Rust preserves it.

There are no remaining borrow verifier gaps in IRV-037–042 and no remaining
semantic verifier implementation families from the prior audit. Next is the
parity audit and differential corpus review. Importer, canonical JSON, Python
DTOs, Rust wire DTOs, ownership/lifecycle models, optimizer, runtime, pipeline
integration, LLVM, PyO3, and production integration remain unchanged.

## 8. Ownership and memory

Python creates the DTO snapshot and owns it for the duration of the extension
call. PyO3 reads it, validates it, and copies/converts it into an owned Rust
module. Rust collections own their strings, vectors, maps, blocks,
instructions, types, layouts, and spans. The verifier borrows only from that
owned Rust module. The result contains owned immutable diagnostic data that
PyO3 converts back to Python values; Python then owns the converted result.

Rust must not retain `PyObject`, borrowed Python strings/buffers, callbacks, or
interior pointers after the call unless a later ADR demonstrates a concrete
need and lifetime proof. No raw pointer is part of the extension API. Recursive
type shapes are represented by validated owned IDs or acyclic values, not
reference cycles. Panics and allocation failures are handled at the extension
boundary as described below.

This concerns **compiler memory** only. It does not decide how programs written
in Aether manage memory. Aether's runtime choices—current explicit lifecycle and
native reference counting, or any future GC/ARC/manual policy—remain separate
language/runtime design decisions.

## 9. Diagnostics and internal errors

Rust does not print to stdout or stderr. It returns diagnostics independent of
presentation, conceptually:

```text
Diagnostic
  code / invariant_id
  severity and category
  message plus structured arguments
  primary span (optional)
  secondary spans (ordered)
  notes (ordered)
  help (optional)
```

Python initially continues to own `CompilerDiagnostic`, rendering, colors, CLI
and LSP conversion, and exit codes through `src/aether/diagnostics.py`. Today an
IR verifier failure caused by accepted source maps to `ICE-IR-VERIFY-001` and
exit code 70. The adapter must preserve that public behavior. Direct verifier
corpus tests can compare finer invariant identifiers even when the compiler
boundary intentionally presents only the stable ICE code.

Compatibility has two levels:

1. **Semantic:** both implementations accept or reject the same module and
   identify the same failed invariant family.
2. **Diagnostic:** stable code/invariant ID, equivalent location and message,
   and deterministic ordering agree. Exact prose is required only for explicit
   public diagnostic contract tests; it must not prevent a separately reviewed
   message improvement.

Expected invalid input is returned as a value, not a Rust panic. `panic!` is not
used for user- or verifier-detectable errors. No unwind may cross FFI. The
extension boundary catches a panic where unwinding is supported and maps it to
an internal Rust-extension failure; build configuration must define controlled
abort behavior where it is not. Python then uses the existing ICE path and exit
code 70, with safe context and `--debug` details. It must not hide a panic by
rerunning Python and accepting the module.

## 10. Differential testing and shadow mode

Phase 0 creates a versioned corpus from current tests, lowering output,
`examples/`, and `tests/aether/parity_corpus/`. The valid side includes scalar
and aggregate programs, functions/callables, enums, structs, arrays, lists,
strings, vector/matrix shapes, builtins, lifecycle, control flow, and modules
that lower successfully. The invalid side includes missing/duplicate blocks,
bad terminators/targets, undefined or mistyped values and slots, incompatible
calls/returns, invalid constants/layouts/shapes, lifecycle leaks/use-after-move,
borrow escapes, and every established negative Python-verifier fixture.

For each module, normalize both outcomes to acceptance plus ordered invariant
IDs, spans, and relevant structured fields. Compare:

```text
Python IRVerifier(module) -> normalized result A
Rust verifier(snapshot)   -> normalized result B
compare A and B -> match or explicit migration discrepancy
```

A discrepancy is never discarded because later code happened to work. The
report records schema version, fixture/mutation seed, Python and Rust outcomes,
and the smallest available IR reproduction. Expected differences require a
tracked decision: fix Rust, characterize a Python bug and fix it separately, or
version the intended contract.

The handwritten corpus is extended with property-based generation of valid and
near-valid typed IR, mutation of one invariant at a time, deserializer fuzzing,
verifier fuzzing, and determinism checks across repeated runs and hash seeds.
Future Rust tools may include `proptest`, `cargo-fuzz`, and `criterion`; adding
them requires the dependency policy in Section 17.

Shadow verification means both verifiers run and compare, while the configured
authoritative implementation alone supplies the product decision. It is for CI
and optionally development, not permanent production work. A conceptual
selector is:

```text
AETHER_IR_VERIFIER=python   # initial local/product default
AETHER_IR_VERIFIER=rust     # explicit opt-in, later default
AETHER_IR_VERIFIER=shadow   # CI and development comparison
```

Final names may change. Initially CI runs the full differential job in shadow;
normal production uses Python. During opt-in, Rust failures are visible errors.
After promotion, normal production uses Rust only and CI still invokes Python as
an oracle. `fallback` is a separate explicit development mode if ever needed;
it is not another name for shadow and is never silent. A crash yields an ICE. A
mismatch fails shadow CI. Operational rollback changes the central selector to
Python and ships that decision; it does not depend on reverting months of model,
test, and optimizer work.

## 11. Packaging and platform policy

The current `pyproject.toml` uses `setuptools.build_meta`, installs packages from
`src`, declares console scripts, and builds a `py3-none-any` wheel. A PyO3
extension changes that artifact into platform- and Python-compatible wheels.
Editable installs must build the extension from source or expose an explicit
Python-only developer mode. The CLI, LSP, VS Code extension, and IntelliJ plugin
must continue to import/invoke the same Python entry points and must not select
verifier implementations themselves.

For the selected PyO3 integration, the provisional packaging direction is
`setuptools-rust` plus a wheel matrix, because it preserves the existing
setuptools package discovery, scripts, and data-file/release logic with the
smallest conceptual change. `maturin` is the preferred alternative to evaluate
if mixed-project wheel production, editable installs, or cross-platform repair
are materially more reliable in a prototype. It must replace—not coexist with—a
second source of wheel metadata. An included helper binary matches only the
process contingency and adds binary discovery/version checks. A separately
downloaded helper is rejected because offline `pip install`, reproducibility,
and IDE environments would become harder to guarantee.

Future packaging CI must build, repair where required, install into a clean
environment, run `aether --version`, run compiler/LSP smoke tests, verify the
extension schema handshake, inspect archive contents, and test uninstall. It
must also preserve sdist development from source with a documented Rust
toolchain requirement. `scripts/release.py` and release-contract tests will
need deliberate updates only in the implementation phase; this task does not
change them.

Platform categories are:

| Platform | Current evidence | Rust migration status |
| --- | --- | --- |
| Linux x86_64 | Current declared/verified native platform with external `clang`. | Verified target once Rust wheel, tests, and native compiler corpus pass in CI. |
| Windows x86_64 | Not a currently supported native platform; known process-argument and text-path work remains. | Required migration packaging target, initially experimental. Rust integration passing does not imply Aether native runtime support. |
| macOS x86_64 | No current native support evidence. | Required migration packaging target, initially experimental. |
| macOS arm64 | No current native support evidence. | Required migration packaging target, initially experimental. |

A Rust component cannot become mandatory by default until its artifacts install
and its relevant compiler tests pass on every platform officially supported by
Aether at that time. Platform targets, verified platforms, and experimental
artifacts must remain separately labeled. Expanding Aether native-runtime
support is a distinct project from making the compiler extension importable.

## 12. Performance measurement

Phase 0 records distributions, not a single best run, for Python IR verification,
total compilation, DTO conversion, peak memory, CLI startup, extension import,
and wheel/sdist size. Repeat after each promoted component. Measure cold and warm
processes, small and large modules, dense CFGs, many functions/types/layouts,
large aggregate instruction sets, and invalid modules that generate one or many
diagnostics. Separate extension import from the first verifier call and separate
transport from verification.

The programs under `benchmarks/` help exercise end-to-end compilation and native
execution, and `src/aether/benchmark.py` already exposes internal stages. Program
execution benchmarks do not substitute for compiler-internal verifier/optimizer
benchmarks. No numeric speedup or size budget is set before the baseline exists.
A regression may be accepted only with a documented reason, user impact, and
approved budget.

## 13. Promotion and retirement criteria

Component states are `experimental -> shadow -> opt-in -> default -> legacy
oracle -> removed`. Moving to default requires all of the following:

- complete functional parity for the component's declared input surface;
- the complete valid corpus accepted and invalid corpus rejected as intended;
- zero unexplained mismatches, deterministic results, and stable diagnostic IDs;
- property/mutation coverage and a defined, recorded fuzzing period without a
  relevant unresolved crash, hang, or false acceptance;
- no unjustified performance, memory, startup, or artifact-size regression;
- installable and tested packaging on all supported release platforms;
- green Python, Rust, differential, real compiler, CLI, LSP, and packaging CI;
- documented schema, ownership/error policy, explicit selection, and tested
  rollback.

Python does not disappear when Rust becomes default. It first becomes a legacy
test oracle. Removal requires at least one normal release cycle with Rust as the
default, no unresolved parity issue, corpus independence from Python internals,
debugging/diagnostics that no longer require the old implementation, confirmed
rollback to the previous release or component version without it, and an
approved maintenance decision. Removal includes deleting the dual flag and old
implementation together so they do not become permanent parallel sources of
truth.

## 14. IR change policy during coexistence

While both models exist, every IR change must:

- update the schema and compatibility/version decision;
- update Python and Rust models/verifiers in the same feature series;
- add valid, invalid, round-trip, differential, and diagnostic fixtures;
- update effect, lifecycle, printing, SSA, optimizer, and backend consumers as
  applicable;
- document Python/Rust impact in the PR and keep semantic feature work separate
  from mechanical migration when practical;
- avoid an instruction or invariant that exists in only one implementation.

Schema readers reject unknown required variants. Additive optional metadata can
remain compatible only when its default has defined semantics; otherwise the
schema version changes. One implementation is authoritative at runtime, but the
contract and fixtures—not either language's class layout—are the source of
truth.

## 15. Risk register

| Risk | Probability | Impact | Mitigation | Warning signal |
| --- | --- | --- | --- | --- |
| IR model divergence | High | High | Versioned schema, exhaustive variant tests, dual-change policy. | Adapter special cases or unexplained mismatch. |
| Expensive conversion | Medium | Medium | Whole-module DTO, benchmark transport separately, avoid reflection/per-op calls. | Conversion approaches verifier time or dominates small builds. |
| Diagnostic inconsistency | High | High | Stable invariant IDs, normalized outcomes, Python presentation ownership. | Same rejection with different code/span/order. |
| Wheel/platform failure | High | High | Build/install matrix and release smoke before default. | Source install works but wheel import fails. |
| Increased build complexity | High | Medium | Minimal workspace/dependencies; retain one packaging authority. | Multiple toolchains generate conflicting metadata. |
| Two sources of truth persist | High | High | Promotion/retirement dates and mandatory dual-change checklist. | Features repeatedly land in only one verifier. |
| Ownership/FFI bug | Medium | High | Rust-owned copies, no retained Python references/raw pointers, minimal unsafe. | Refcount-sensitive or nondeterministic crashes. |
| Windows incompatibility | High | High | Early Windows wheel CI; separate compiler-extension and native-runtime claims. | Import/path/Unicode failures appear late. |
| CI duration growth | High | Medium | Tier PR/nightly/release jobs and cache immutable inputs. | Shadow/fuzz jobs become routinely skipped. |
| Migration scope expands | Medium | High | Phase gates and per-component ADRs. | Verifier PR also changes parser/runtime/backend. |
| Premature optimization | Medium | Medium | Baseline first; require profiles and representative modules. | Custom binary schema before transport is measured. |
| Excess CPython coupling | Medium | High | Narrow PyO3 API, DTO primitives, test supported Python versions; process contingency. | Rust imports internal dataclass types directly. |
| Exception/panic crossing | Medium | High | Structured errors and panic containment; no unwind across FFI. | Python sees aborts or opaque `SystemError`. |
| Simultaneous semantic change | High | High | Separate migration/features and characterize old/new behavior. | Parity decision cannot identify intended behavior. |

## 16. Future workspace structure

The initial shape should be deliberately small:

```text
compiler-rs/
  Cargo.toml
  Cargo.lock
  rust-toolchain.toml
  README.md
  crates/
    aether-ir/
      Cargo.toml
      src/
    aether-python/          # added with Phase 3 integration
      Cargo.toml
      src/
```

`aether-ir` is created first and initially contains the owned IR, schema
validation, and verifier modules. Splitting `aether-ir-verifier` before a second
consumer needs that boundary creates ceremony without isolation value.
`aether-python` owns only PyO3 conversion and exported functions and depends on
`aether-ir`; the core crate never depends on Python. Future `aether-ssa`,
`aether-diagnostics`, optimizer, LLVM-support, or runtime crates are postponed
until their dependency boundaries and reuse justify them. Crate dependencies
flow from bindings/backends toward core models and diagnostics; cycles are
forbidden.

Shared language-agnostic snapshots and invalid fixtures should live under a
future repository-level `tests/aether/rust_migration/`, adjacent to the Python
tests rather than hidden in a binding crate. Rust-only unit/property tests live
with their crate. `backend-rs/` is rejected because CFG/SSA/verifiers are not a
backend; `rust/` is too vague if other Rust tooling arrives; placing it under
`src/aether/backend/` would incorrectly make Cargo sources part of the Python
package tree.

## 17. Rust dependency, safety, and reproducibility policy

Use the standard library where sufficient. Every dependency needs a stated
purpose, maintained status, compatible license, security review, and a reason
its behavior is preferable to a small local abstraction. Avoid large
frameworks, async runtimes without measured concurrent I/O, and LLVM bindings
during the verifier/SSA phases. A workspace lockfile is committed for
reproducible application/extension builds. Toolchain and MSRV policy are pinned
and changed deliberately; supported Rust versions are tested rather than
assumed.

Likely scoped tools are `serde` for schema-derived data, `thiserror` for typed
errors, `pyo3` for the extension, and `setuptools-rust` for initial packaging.
`maturin` is the packaging contingency described above. `proptest`,
`cargo-fuzz`, and `criterion` serve property tests, fuzzing, and benchmarks;
they are development dependencies and do not automatically enter the shipped
extension.

Required gates include `cargo fmt --check`, Clippy with an agreed warning
policy, unit/integration/doc tests, dependency/license review, and `cargo audit`
or an approved maintained alternative. Release inputs record Rust and Python
versions and honor a reproducible timestamp policy. Release artifacts are
rebuilt/compared where practical.

Production code is safe Rust by default. Any `unsafe` block must be isolated to
the narrowest module, document its invariants and ownership/lifetime assumptions,
have focused tests (and Miri/sanitizer coverage when applicable), and receive a
specific review. PyO3's internal unsafe implementation does not justify unsafe
in Aether code.

## 18. Future CI schedule

Every PR runs Python tests affected by the change, Rust formatting, Clippy, Rust
tests, schema/fixture tests, the differential verifier corpus, and Linux wheel
build/install smoke. Once artifacts exist, platform wheel smoke for the support
matrix is required on PRs that touch Rust, packaging, or release code.

Nightly jobs run the full cross-platform matrix, larger generated/mutation
corpora, scheduled fuzzing with retained seeds, determinism checks, and compiler
benchmarks with trend reporting. Before a release, run all Python and Rust tests,
the complete differential corpus, supported-platform wheel/sdist builds and
clean installs, CLI/LSP/IDE-facing smoke, native compiler examples where the
platform is supported, security/license checks, reproducibility checks, and a
rollback rehearsal. Benchmarks and fuzzing may be scheduled rather than block
every PR, but unresolved relevant findings block promotion/release.

## 19. Open decisions

The first direction is sufficiently closed to start Phase 0/1, but these details
remain explicit decision points:

| Question | Options | Provisional recommendation | Decision deadline |
| --- | --- | --- | --- |
| CPython compatibility | Per-version PyO3 wheels; `abi3`; process helper. | Start with supported per-version wheels; test `abi3` before adopting it. | Before publishing the first opt-in wheel. |
| DTO implementation shape | Python dataclasses; typed mappings/tuples; generated adapter. | Explicit typed primitive mapping first; generate only after schema repetition is measured. | Before Phase 2 code review. |
| Diagnostic schema | Extend current `CompilerDiagnostic`; add an internal migration diagnostic DTO; immediately replace public model. | Add an internal rich DTO and adapt to the current public model. | Before the first Rust verifier rule. |
| Source spans | Preserve point locations; introduce start/end ranges now; use source IDs. | Preserve current optional locations first and reserve versioned range/source-ID fields. | Before schema v1 is frozen for shadow CI. |
| Rust model identity | Names; numeric IDs; interned arenas. | Owned typed IDs internally, with names preserved for deterministic diagnostics. | During Phase 2, before optimizer-oriented APIs. |
| Packaging backend | `setuptools-rust`; `maturin`. | Prototype `setuptools-rust`; switch to maturin only from measured wheel/editable evidence. | Before Phase 3 integration lands. |
| MSRV | Latest stable; fixed older MSRV; rolling window. | Pin a documented version for the experiment, then choose MSRV from supported builders/users. | Before Phase 1 CI becomes required. |
| Python verifier removal date | Fixed release; evidence-based release gate. | Evidence-based, no earlier than one release cycle after Rust default. | When Rust enters `default`. |

Use Architecture Decision Records for decisions that are expensive to reverse.
The repository does not currently require an ADR format, so this task creates no
ADRs. Proposed records are: **ADR-001 Python–Rust integration mechanism**,
**ADR-002 IR interchange representation**, **ADR-003 diagnostic ownership**, and
**ADR-004 Rust workspace and packaging layout**.

## 20. Immediate plan

Each item should be one or a small number of commits:

1. Approve this document and record unresolved objections.
2. Capture the Python IR-verifier rule inventory and timing/memory baseline.
3. Build checked-in valid and invalid IR fixtures from current tests and lowering.
4. Assign stable invariant IDs and define normalized differential outcomes.
5. Specify the versioned ModuleDTO, including all current variants and locations.
6. Write ADR-001 through ADR-004 with the prototype decisions above.
7. Create the minimal `compiler-rs/` workspace and `aether-ir` crate, without
   product integration.
8. Implement the smallest complete owned IR model slice and schema rejection.
9. Implement structural verification for modules, functions, blocks,
   terminators, and targets.
10. Add the PyO3 adapter and shadow mode to tests, still defaulting to Python.
11. Expand type, call, aggregate, data-flow, borrow, and lifecycle coverage until
    the complete verifier corpus matches.
12. Promote the verifier from experimental to opt-in only after packaging and
    rollback smoke pass.

The next technical commit after approval is therefore **Phase 0: a Python
verifier baseline plus a versioned valid/invalid fixture manifest**. It is not a
`Cargo.toml` commit and does not alter product behavior.

## 21. Completion checklist for this strategy

This strategy answers why and what to migrate, preserves the frontend and LLVM
initially, orders component replacement, selects PyO3 and a versioned whole-module
DTO, keeps diagnostics presented by Python, defines differential/shadow testing,
specifies future packaging and platform gates, localizes rollback, sets Rust
promotion and Python retirement criteria, selects the IR verifier as the first
component, and identifies the next technical commit. Any implementation proposal
that changes one of those closed directions must update this document and record
the decision before code makes it costly to reverse.

## 22. Phase 4.1 implementation status

Phase 4.1 adds the Rust-only public API
`aether_verifier::verify_module(&IRModule) -> VerificationResult`. The result is
`Result<(), VerificationFailure>` and does not return or mutate the borrowed
module. A failure carries:

- the pass in `VerificationPhase`;
- the invariant-inventory category in `VerificationErrorCategory`;
- an optional stable `IRV-NNN` identifier;
- optional retained function, block, and instruction fields in
  `VerificationContext`;
- a deterministic human-readable message;
- the original module-level typed error in `VerificationError`, preserved
  through `underlying_error()` and `Error::source()`.

The canonical fail-fast order is structure, types, SSA, dominance, lifecycle,
then returns. Structure is required before CFG consumers; SSA is required before
dominance. The combined path runs each complete semantic pass once and uses
crate-private prerequisite-satisfied adapters for downstream passes. Existing
public pass APIs remain independent and keep their defensive prerequisite
behavior. Focused local lifecycle verification remains an independent diagnostic
API and is not repeated by the combined entry point because complete lifecycle
analysis already includes its semantic checks.

Diagnostic normalization is deliberately an adapter rather than a redesign of
the pass-specific errors. Context comes from the existing typed wrapper chains.
Invariant IDs and categories come from typed leaves where present and otherwise
from the retained instruction contract when it is unambiguous. The normalized
failure derives equality, and tests pin pass selection, invariant/category and
context propagation, repeated-result determinism, and exact message rendering.

This phase does not add subprocess execution, a wire response protocol, PyO3,
compiler calls, CLI flags, or shadow mode. The combined API is the future common
semantic boundary for those consumers. Before subprocess integration, Phase 4.2
must define and version the request and response protocol, map every
protocol-exposed failure without an invariant gap, add canonical JSON transport
fixtures, and test cross-language first-failure behavior for multi-invalid
modules.

## 23. Phase 4.2A implementation status

Phase 4.2A adds the isolated `aether-ir-verifier` Cargo package and executable.
Protocol version 1 accepts exactly one strict UTF-8 JSON request on stdin:
`protocol_version: 1`, `operation: "verify"`, and the existing canonical
`IRModuleDTO` as `module`. Because that DTO already contains
`schema_version: 1`, the outer request deliberately does not duplicate the IR
schema version. The binary imports through `aether_ir::import_module` and calls
only `aether_verifier::verify_module`; it does not orchestrate passes.

One compact JSON response plus a newline is emitted on stdout. `accepted` and
`rejected` are semantic outcomes; `error` distinguishes empty/malformed input,
request shape, protocol version, IR schema version, operation, module schema,
owned-IR import, diagnostic normalization, stdin I/O, and internal unwind
failure. All status, phase, category, instruction-kind, and error-kind
spellings are explicit protocol mappings. Semantic rejection requires an
invariant ID. An absent invariant or unknown future phase/category becomes a
normalization error instead of an ordinary rejection.

Exit code 0 means a structured response was emitted, including `rejected` and
recoverable `error` responses. Nonzero is reserved for failure to serialize or
write a response. The outer binary catches unwind panics with the default panic
hook suppressed and emits a stable internal error; aborts and signals retain
normal process behavior. Tests invoke the real binary, require empty stderr,
lock exact accepted bytes and wire spellings, cover protocol/schema/import and
semantic fixtures, and compare repeated stdout byte for byte.

The detailed contract is
[IR_VERIFIER_PROTOCOL.md](IR_VERIFIER_PROTOCOL.md). Python subprocess
invocation, compiler/CLI verifier selection, shadow mode, installed-artifact
discovery, packaging changes, and PyO3 remain explicitly outside Phase 4.2A.
Phase 4.2B is the Python subprocess adapter consuming this boundary.

The Phase 4.2A corpus follow-up confirms no unexpected acceptance/rejection
difference across all 128 schema-v1-compatible cases. The outcome report keeps
the known `non-void-path-without-return` Python-IRV-024/Rust-accepted graph
analysis result explicit. Exact first-invariant parity is intentionally not
universal. Manifest schema version 2 records three compatibility pairs rather
than treating them collectively as fail-fast ordering:

- `return-storage-after-move`: Python IRV-050 / Rust IRV-026 is a
  first-failure ordering difference; both rules and the shared rejection are
  valid;
- `undefined-slot`: Python IRV-031 / Rust IRV-032 is the previously documented
  representation/import-model difference because the Rust import normalizes
  the load slot as storage and reports it uninitialized;
- `inconsistent-branch-initialization`: Python IRV-036 / Rust IRV-028 is the
  previously documented lifecycle-dataflow improvement: Rust retains possible
  merge states and permits a later total transfer to repair them, while Python
  rejects the divergence immediately.

A future shadow mode must compare outcomes before diagnostics, compare stable
invariant IDs rather than messages, and report exact matches, these exact
documented pairs, other diagnostic divergences, and outcome mismatches
separately. The three pairs are explicit expectations, not suppression rules.
