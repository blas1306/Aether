# Gradual Python-to-Rust compiler migration

> Status: proposed migration policy. This document defines sequencing and
> promotion gates; it does not declare the current Python IR or SSA model a
> stable public format. No Rust workspace or production integration exists yet.

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
  values, and selected instructions carry `IRSourceLocation`. There is no
  versioned serializer or parser for this object graph.
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
| JSON | Portable and easy to debug, but needs conventions for enum tags, non-finite floats, complex values, integer limits, and bytes. | Verbose and slower; excellent corpus artifact. | Useful as a human-readable fixture rendering, not the in-process transport. |
| MessagePack | Compact and portable while retaining the schema's tags. | Less inspectable and adds a dependency; useful for a helper process. | Preferred transport if the process contingency is activated. |
| Custom binary | Maximum control and potential speed. | Highest compatibility, parser, fuzzing, and maintenance burden. | Not justified initially. |
| Printed Aether IR | Excellent for humans and existing snapshots. | `src/aether/ir/printer.py` has no matching canonical parser and text may omit internal distinctions. | Diagnostic/golden aid only. |
| Protobuf/FlatBuffers | Strong generated schema and cross-language support. | Toolchain/code generation and evolution policy are disproportionate for one in-process consumer. | Reconsider only if multiple external consumers emerge. |

The DTO schema has an explicit `ir_schema_version` field and tagged variants
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
