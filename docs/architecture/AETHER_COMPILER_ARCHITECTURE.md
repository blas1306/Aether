# Aether compiler architecture and reconstruction audit

Status: **candidate architecture and dated repository audit**.

Audit baseline: `ad9282d` (`main`, equal to `origin/main` when inspected),
2026-09-01.  The working tree was clean.  Tags present were
`rust-verifier-v1`, `v1.0.0-rc.1`, `v1.0.0-rc.2` and `v1.0.0-rc.3`; no tag or
branch was created by this audit.

If a historical marker is desired, the recommended local annotated tag is
`pre-compiler-reconstruction` pointing to `ad9282d`, the commit immediately
before these reconstruction documents.  Create/publish it only as an explicit
repository decision; this audit did neither.

This document complements the normative
[`AETHER_V1_LANGUAGE_CHARTER.md`](AETHER_V1_LANGUAGE_CHARTER.md) and working
[`AETHER_V1_SEMANTIC_CONTRACT.md`](AETHER_V1_SEMANTIC_CONTRACT.md).  “Current”
always means the audited commit.  “Candidate” is design, not implemented fact.

## 1. Scope and evidence

The repository contained 1,328 tracked files: 609 Python, 82 Rust, 169 Aether,
315 under `tests/` and 337 under `docs/`.  Relevant implementation and evidence
were inspected in:

- `README.md`, the v1 spec/scope/native profile/frontend experiments and the
  generated capability registry;
- backend parity, IR/SSA, lifecycle, ABI, optimization, collections, strings,
  Vector/Matrix, linear algebra, exceptions and strategic roadmap documents;
- `src/aether` lexer, parser, AST, types, typechecker, module graph, capability
  gate, interpreter, Initial IR, lifecycle, SSA, optimizers, LLVM backend,
  runtime generators, CLI, diagnostics, LSP and differential harness;
- `compiler-rs` owned IR, wire DTO, lifecycle normalization, SSA lowering,
  Initial IR/SSA/refinement verifiers, transport-independent CompilerCore,
  PyO3 binding and verifier companion;
- focused and end-to-end tests, examples, exception corpus, qualification
  scripts and current Git history.

The code and tests outrank old prose for current facts.  Several documents are
valuable historical snapshots but predate profile 24, in-process transport,
Rust SSA/refinement authority or the latest Initial IR authority change.  In
particular, `IMPLEMENTATION_LANGUAGE_OWNERSHIP.md` and
`POST_RUST_4_5_COMPILER_ARCHITECTURE_AUDIT.md` describe earlier intermediate
states in some tables.  Their policies and measurements remain useful; their
pipeline snapshots are not copied as current truth.

## 2. Repository and compiler found

### 2.1 Active areas

```text
src/aether/          current Python compiler, interpreters, runtime emission, CLI
src/aether_lsp/      current Python LSP
compiler-rs/         Rust owned IR/core/verifiers and Python distribution binding
tests/               language, compiler, native, packaging and qualification tests
examples/, corpus/   executable specification and differential/dogfood sources
docs/                normative documents plus dated design/qualification history
```

`compiler-rs` is not a complete Rust compiler.  It consumes Initial IR created
by Python.  The current production system is one hybrid compiler, not two
independent frontends.

### 2.2 Current product pipeline

The source-to-native trace at the audited commit is:

```text
Python CLI/source/module loading
  -> Python lexer -> parser -> mutable TypeChecker tables
  -> CheckedProgram + entry-point normalization
  -> native capability gate (profile 24)
  -> Python Initial IR lowering
  -> schema-v1 snapshot
  -> Rust Initial IR verifier, exclusive PRE-lifecycle authority
     (persistent installed verifier subprocess)
  -> current wrapper re-admission when `SSAPipeline` receives the IR module
  -> Python lifecycle expansion
  -> normalized schema-v1 JSON bytes
  -> Rust CompilerCore through PyO3 in-process by default
       import owned IR
       lifecycle normalization (idempotent on the expanded input)
       construct owned SSA
       verify owned SSA
       verify Initial-IR-to-SSA refinement
       export schema-v2 at the adapter boundary
  -> Python schema-v2 import
  -> Python SSA generic verification + integrity gates
  -> Python Initial IR/SSA optimization selected by O0/O1/O2
  -> Python native-boundary verification
  -> Python textual LLVM + embedded runtime helper generation
  -> external clang compilation/link
  -> native artifact
  -> execute artifact only for run
```

`AETHER_RUST_CORE_TRANSPORT=companion` selects the qualified persistent
subprocess rollback for the SSA core; no automatic fallback exists.  The
Initial IR authority uses a separate installed verifier client.  Python's
Initial IR verifier, General SSA builder and refinement verifier remain
oracles/qualification tools, not the default product authority in the latest
path.  Python still owns lifecycle expansion before the Rust request,
post-import SSA objects/checks, optimizers and LLVM.

The logical authority boundary is one Rust PRE-lifecycle admission, but the
current call graph does more work than that abstraction suggests:
`LLVMBuilder.emit_llvm()` first calls `IRBackend.lower_verified()` and later
passes the resulting `IRModule` to `lower_to_verified_ssa()`;
`SSAPipeline.run(IRModule)` calls `IRBackend.admit_initial_ir()` again.  For
O1/O2, `optimize_verified()` has already expanded lifecycle before that second
admission.  This is fail-closed and covered by the broad suites, but it is a
duplicate gate with a misleading phase label, not a target architecture
property.  The new compiler should have a typed state transition that makes
re-admission of an already accepted or post-lifecycle module unrepresentable.

`aether run` and the default `aether file.ae` build a temporary native artifact
and execute it.  `aether build` runs the same compiler and retains the output.
AST and IR interpreters are explicit development backends; there is no silent
fallback.

### 2.3 Current semantic concentration

The 246-KiB `typechecker.py` combines declaration collection, aliases, module
loading, visibility, name lookup, scopes, type inference, conversions,
operator/builtin/method selection, definite initialization, exception effects,
collection ownership restrictions, shape reasoning and backend-adjacent layout
checks.  Parser nodes directly contain types from `types.py`; that same module
also contains interpreter values.  There is no isolated semantic type arena or
resolved typed tree.

Initial IR is a typed slot/CFG form with structural lifecycle operations.  SSA
is a distinct CFG representation with dominance and phi invariants.  The Rust
owned forms and verifiers are substantial reusable assets, but their schemas
were designed to import the existing Python IR, not from a clean language
model.

The LLVM printer is approximately 290 KiB and combines instruction selection,
validation, layouts, ownership/ARC emission, feature discovery, runtime helper
selection and textual LLVM.  Runtime code is generated into each module and
calls libc/libm/POSIX.  There is no versioned, separately linked runtime or
public Aether C FFI.

## 3. Principal debt and lessons

1. **Frontend authority exceeded native historically.**  The current
   capability gate prevents unsupported experiments from reaching native, but
   parser/AST/typechecker surface is still broader.  Support must be defined by
   an end-to-end native row, not a frontend component.
2. **Semantic concerns are entangled.**  Source types, interpreter values,
   resolution, inference and backend admissibility share mutable Python
   structures.  This impedes incremental compilation, parallel queries,
   stable diagnostics and generics.
3. **The middle boundary is over-serialized.**  Current correctness work
   successfully migrated to Rust, but production still materializes schema v1,
   invokes a separate verifier process, expands lifecycle in Python, enters
   Rust through PyO3, exports schema v2 and rebuilds SSA in Python objects.
4. **Admission/lifecycle phases are not type-state boundaries.**  Supported
   wrapper paths can re-run PRE-lifecycle Rust admission, including on expanded
   IR in optimized builds.  Python expands lifecycle before the core;
   Rust normalizes it again idempotently.  This is safe and qualified, but not
   the desired single owned pipeline.
5. **Verifier strength is higher than representation coherence.**  Initial IR,
   SSA and refinement verification are unusually strong assets, while opcode,
   type, effect and lifecycle definitions are repeated across Python/Rust/DTO/
   LLVM layers.
6. **Runtime and backend are coupled.**  Object headers and field indexes are
   reconstructed in multiple generators.  LLVM text and clang are practical
   bootstrap mechanisms but currently act as the runtime packaging boundary.
7. **Scientific meaning is lost too soon in places.**  Vector/Matrix shapes
   often travel as opcode metadata or immediate facts; advanced algebra is
   implemented only in the host-backed AST path.  There is no enduring buffer,
   stride, alias or layout model for fusion/BLAS selection.
8. **Generics cannot be appended cheaply.**  The parser recognizes some forms
   for rejection, but semantic types, constraints, HIR, instantiation,
   mangling, module ownership and diagnostics have no generic architecture.
9. **Compile-time costs have multiple causes.**  Prior measurement found cold
   Python import cost dominant for tiny programs, clang/link dominant for warm
   tiny builds, and Python verification/materialization dominant on the largest
   workload.  Rewriting the lexer alone would not solve the observed cost.
10. **Documentation is rich but temporally duplicated.**  Dated qualification
    documents preserve excellent evidence; summaries have sometimes lagged
    promoted code.  Generated inventories and a small set of normative
    documents should replace manually synchronized status claims.

## 4. Decisions confirmed and proposals challenged

Confirmed:

- native AOT is the product authority and `run = build + execute`;
- Rust is the bootstrap compiler core, C ABI is the runtime/FFI boundary;
- fixed-width numeric names and separate `isize`/`usize` are the correct
  foundation;
- aliases are transparent and user aliases belong before self-hosting;
- strict floating semantics are independent of optimization level;
- local inference and explicit public APIs are the right bias;
- generics, ownership facts, target layout and scientific shapes must influence
  architecture before all features are implemented;
- current compiler, interpreters, tests and qualification infrastructure are
  valuable oracles and assets, not disposable legacy.

Challenged or kept open:

- `int` cannot be selected responsibly without compatibility and performance
  evidence; neither i32 nor i64 follows automatically from the vision;
- making row/column orientation mandatory on every vector may harm ordinary
  vector use; oriented views may be better than universal orientation;
- preserving current one-based Vector/Matrix indexing alongside zero-based
  collections has substantial generic/FFI cost and needs evidence;
- immutable ARC strings are a sound baseline, but ARC must not become the
  ownership answer for every buffer/value;
- a full Rust borrow checker is not justified; Aether needs a narrower model
  shaped by views, mutation and FFI;
- `complex` need not be a primitive merely because it is scientifically core;
- clang subprocess invocation is acceptable bootstrap machinery, but not a
  semantic layer and not the final backend API;
- all of AST, HIR, MIR and SSA are justified only with distinct invariants;
  a lossless CST and a separate optimizer IR are not justified for milestone 1.

## 5. Candidate compiler pipeline

```text
source files + project/target configuration
  -> source database, lexer, parser
  -> source AST
  -> module graph + declaration/name resolution
  -> typed HIR (generics and high-level scientific operations intact)
  -> monomorphization planning + target-independent semantic checks
  -> flow MIR (CFG, places, initialization, ownership, cleanup, errors)
  -> verified SSA IR (values, effects, alias/shape/layout facts)
  -> target layout + optimization pipeline
  -> Backend interface
       -> LLVM backend -> object emission
       -> optional diagnostic backend(s), never language authorities
  -> linker/toolchain interface + versioned runtime
  -> native artifact
```

The driver owns a per-compilation `Session`: source database, target descriptor,
interned identities/types, diagnostics, dependency graph and incremental query
cache.  No semantic global state is process-wide.  Stable IDs use logical
module identity plus declaration identity, never absolute path or host object
identity.

The initial backend may emit textual LLVM and invoke clang.  Both are behind
interfaces from day one: `Backend::emit_object` (or temporary
`emit_llvm_module`) and `Toolchain::link`.  Source semantics cannot inspect the
chosen clang command or LLVM spelling.

## 6. Representation evaluation

### 6.1 Source AST — justified

| Question | Answer |
|---|---|
| Information | Source declarations, expressions, type syntax, tokens/spans, attributes and syntactic recovery nodes |
| Invariants | Parsed structure is well formed enough for recovery; every node has a source span; no name/type meaning is claimed |
| Decisions resolved | Grammar, precedence and delimiter association only |
| Preserves | User spelling, aliases, literal text and source structure needed by diagnostics |
| Eliminates | Trivia may be excluded from the compiler AST; a tooling syntax tree may retain it separately |
| Consumers | Resolver, HIR lowering, diagnostics; formatter/LSP through a stable syntax service |
| Why not adjacent | Tokens are too weak for declarations/precedence; putting symbol/type identities here recreates the current parser/type coupling |

A separate lossless syntax tree is useful for formatting and IDE refactors, but
is not required for the first compiler milestone.  It may share a parser event
stream later.

### 6.2 Typed HIR — justified

| Question | Answer |
|---|---|
| Information | Resolved `ModuleId`/`SymbolId`, canonical semantic types, generic binders/arguments/constraints, explicit conversions, selected operators/methods, mutability, high-level Array/Vector/Matrix operations and source spans |
| Invariants | Every name resolves; every expression has one type; overload/constraint choice is unique; public signatures are complete; no unsupported feature is admitted |
| Decisions resolved | Names, scopes, type inference, conversions, callable target, generic constraints and desugaring of purely syntactic sugar |
| Preserves | Generic identity, aliases for diagnostics, shape/orientation, allocation-relevant operation identity, purity/effect declarations and source provenance |
| Eliminates | Ambiguous syntax, unresolved names, implicit conversions and parser recovery nodes |
| Consumers | Semantic diagnostics, monomorphization planner, const evaluator, MIR lowering, IDE semantic queries |
| Why not adjacent | A typed AST would either mutate source nodes as today or mix syntax and canonical types. MIR is too low to provide good generic/type diagnostics or retain natural scientific operations |

HIR is the one additional layer not present cleanly today.  It is justified by
generics, tooling and the need to retain domain semantics before CFG/lifecycle.

### 6.3 Flow MIR — justified

| Question | Answer |
|---|---|
| Information | Explicit basic blocks, places/projections, values, calls, normal/exceptional edges, initialization state, copy/move/borrow operations, cleanup obligations, bounds/shape checks and still-recognizable bulk scientific operations |
| Invariants | Typed CFG; explicit terminators; definite initialization; valid place projections; ownership transitions and all exits verifiable; generic instances selected or deliberately retained |
| Decisions resolved | Evaluation order, desugared control flow, storage versus value, cleanup placement, call ownership modes, exception strategy and initial layout requirements |
| Preserves | Source spans, alias classes, borrows, shape/stride/layout constraints, effect/trap information and high-level buffer operations |
| Eliminates | Lexical scopes as execution constructs, most source syntax and implicit destruction |
| Consumers | MIR verifier/interpreter, borrow/lifecycle analysis, monomorphization completion, SSA construction, early optimizations |
| Why not adjacent | HIR cannot express path-sensitive initialization/cleanup without becoming CFG MIR. SSA alone is awkward for addressable places, partial initialization, moves and exceptional cleanup |

This is the architectural successor to current Initial IR, not a commitment to
reuse its exact opcode/schema.  Current lifecycle operations and verifier
invariants should seed it.

### 6.4 SSA IR — justified

| Question | Answer |
|---|---|
| Information | SSA values, phis/block parameters, explicit CFG/effects, memory/buffer operations, target-independent types, ownership effects, alias/shape/range facts and debug provenance |
| Invariants | Single definition, dominance, exact edge inputs, verified types/effects, no implicit lifecycle, valid high-level operation contracts |
| Decisions resolved | Promotion of eligible locals, use-def graph, control merges and concrete lifecycle actions; target layout may remain symbolic |
| Preserves | Facts required for BCE, ARC elimination, fusion, buffer reuse, SIMD/BLAS selection and later debug mapping |
| Eliminates | Source variables/places promoted to values and most structured control syntax |
| Consumers | Analyses, optimizer, verifier, backend lowering and optional differential evaluator |
| Why not adjacent | MIR place mutation obscures global value flow; LLVM is too target-specific and loses Aether ownership/shape semantics too early |

Current Rust SSA construction, dominance, verifiers and refinement work are the
strongest directly adaptable compiler assets.  New SSA should use owned
in-process Rust structures; wire schemas are adapters, not its internal API.

### 6.5 LLVM IR — backend output, not canonical Aether IR

| Question | Answer |
|---|---|
| Information | Target-layout values, calls, intrinsics, metadata and control flow in LLVM's contract |
| Invariants | Valid LLVM module for the selected target/toolchain; runtime ABI calls match generated declarations |
| Decisions resolved | Concrete layout/calling convention, instruction selection and representation lowering |
| Preserves | Debug/source metadata and carefully translated alias/FP attributes only |
| Eliminates | Aether generics, ownership model and high-level Matrix/Vector meaning unless intentionally encoded as metadata/intrinsics |
| Consumers | LLVM optimizer/object emitter or bootstrap clang, then linker |
| Why not adjacent | It is unsuitable for type diagnostics, ownership verification and portable semantic optimization; an additional post-LLVM IR would duplicate LLVM |

No independent optimizer IR beyond SSA is proposed.  No mandatory AST
interpreter is in the production pipeline.

## 7. Cross-cutting architecture

### 7.1 Type and generic representation

Types are interned immutable semantic values, separate from syntax and runtime
values.  The model includes primitive, nominal, function, reference/view,
generic parameter/application and compiler-known core types.  Physical layout
is a query of `(semantic type, target, representation attributes)`, not a field
inside every source type.

| Phase | Generic responsibility |
|---|---|
| Parser/AST | Preserve binders, arguments, constraints and source spans without guessing `<` ambiguities |
| Resolver | Assign identities and scopes for type/value parameters and constraints |
| HIR/typecheck | Build substitutions, solve explicit constraints, infer unique call arguments and diagnose ambiguity |
| MIR | Lower one generic body with substitution-aware types; retain operations needed for later instances |
| Monomorphizer | Choose canonical instances, prevent infinite expansion, own cross-module instantiations and cache keys |
| SSA/backend | Consume concrete instances or an explicitly supported shared representation; deterministic mangling includes canonical substitutions |
| ABI/modules | Reject or define exported generic ABI; record instance ownership and dependency fingerprints |

### 7.2 Memory and lifecycle

Ownership is semantic before it is operational:

```text
HIR: value/category and parameter-mode facts
MIR: explicit places, moves, borrows, initialization and cleanup edges
SSA: concrete retain/release/drop/buffer effects plus surviving proofs
runtime: allocation, ARC and foreign ownership operations behind ABI
```

The verifier, not convention, proves that every owning place is initialized
before use, moved at most once and destroyed exactly once on the applicable
exit paths.  ARC is inserted only for shared handles.  Optimizers may eliminate
ARC/copies only with ownership and alias proof.  Buffer descriptors make
contiguity, alignment, allocator, length, capacity, dimensions, strides,
layout, pinning and FFI exposure explicit as applicable.

Panic/error semantics must be decided before cleanup lowering is frozen.  MIR
must be capable of representing both normal and exceptional exits even if the
first product profile uses aborting panics.

### 7.3 Scientific optimization

HIR/MIR use semantic operations such as matrix multiply, elementwise map,
transpose/view and broadcast rather than immediately lowering every operation
to an opaque runtime call.  Operations carry shape, orientation, layout,
contiguity, alias and ownership facts.  The optimizer may then choose:

- direct scalar/vectorized loops;
- fused expression kernels;
- in-place/reused destination buffers when alias/liveness permit;
- fixed-size unrolling/specialization;
- a BLAS/LAPACK call through the runtime/FFI layer.

`y = A * x + b` must remain a graph whose allocations and consumers are
visible until buffer planning.  Implementing expression templates in source or
fusion in milestone 1 is not required.

### 7.4 Optimization and compile time

Correctness lowering and verification are always enabled.  Optimization
profiles select named pass pipelines and backend policy; relaxed floating point
is a separate axis.  Every pass declares required/preserved analyses and is
verified in development/qualification modes.

The compiler records phase timings and cache statistics from the first
milestone.  Queries are keyed by content, logical module identity, target,
profile and semantic/compiler version.  Avoid serializing between in-process
core stages.  Incrementality begins at modules/functions; whole-program
optimization is opt-in and must not contaminate normal edit-build latency.

### 7.5 Backend and toolchain

The backend interface consumes verified SSA plus target/runtime descriptions
and emits an object or a clearly temporary LLVM artifact.  It cannot accept
source AST.  LLVM is primary.  A diagnostic evaluator may consume MIR/SSA for
tests but does not confer language support.

The toolchain interface owns LLVM discovery, object format, linker selection,
libraries, response files, target triple/data layout and artifact retention.
Invoking clang remains valid during bootstrap.  Command discovery is never a
semantic decision.

### 7.6 Runtime and C ABI

Move generated runtime helpers out of the printer behind a versioned runtime
manifest.  A canonical ABI schema describes symbols, opaque handles, fixed-
width fields, ownership, errors and target availability and generates Rust/C/
Aether declarations.  Initial components should be panic/allocation, string
and raw buffer—not the scientific library ecosystem.

BLAS/LAPACK and OS/native dependencies are providers behind this boundary.
No C++ ABI crosses it; a future C++ dependency requires a narrow `extern "C"`
shim that contains exceptions and object ownership.

### 7.7 Diagnostics

Every diagnostic is a structured record with stable ID, severity/category,
primary span, labelled secondary spans, typed parameters and causal notes.
Rendering and localization are consumers.  Compiler errors do not cross phases
as arbitrary exception strings.  Unsupported/gated features identify the
first missing end-to-end capability before MIR/backend work.

Source spans survive all IRs for operations that may diagnose, trap or fail
verification.  ICEs are distinct from source rejection and include enough
reproducible phase/context data without exposing tracebacks by default.

## 8. Current feature inventory

Legend: `C` complete for the documented current subset, `P` partial or profile-
restricted, `N` absent, `G` recognized only to gate/reject, `R` reference/
oracle only.  This is a grouped audit; the executable source of current
capability states remains `src/aether/capabilities.py`, and the detailed
per-operation historical evidence is
[`BACKEND_FEATURE_PARITY.md`](../aether/BACKEND_FEATURE_PARITY.md).

| Feature group | Parser | AST | Semantic | AST eval | Initial IR | SSA | Native | Runtime | Tests | Docs |
|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| `int` i32, `double`, `boolean`, `void` subset | C | C | C | C | C | C | C | C | C | C |
| fixed-width ints, `isize`/`usize`, `char` | N | N | N | N | N | N | N | N | N | target only |
| `float`, `complex`, imaginary literals | C/P | C | C | C | P | P | G/N | N | AST/IR | experimental |
| nullable `T?`/`null` profile-24 subset | C | C | C | C | C | C | C | C | C | C |
| transparent user aliases/imported aliases | C | C | C | C | C | C | C/P | none | C | C |
| typed locals/const and assignment | C | C | C | C | C | C | C | none | C | C |
| untyped inferred local assignment | C | C | C | C | N/G | N | G | N | AST | outside v1 |
| checked integer and mixed numeric arithmetic | C | C | C | C | C | C | C | C | C | C |
| functions, recursion, returns, `void` | C | C | C | C | C | C | C | call ABI | C | C |
| abbreviated expression functions | C | C | C | C | P | P | subset | none | C/P | C |
| top-level capture-free function values | C | C | C | C | C | C | C/P | pointer | C | C |
| nested functions, lambdas, closures/bound methods | P/N | P/N | P/N | P/N | N | N | G/N | N | limited | experimental |
| `if`/`while`/short-circuit/break/continue | C | C | C | C | C | C | C | traps | C | C |
| inclusive range `for`, collection `for-in` | C | C | C | C | C/P | C/P | C/P | bounds | C | C |
| stored range and generic Iterator/Iterable | P/N | P/N | P/N | P/N | N | N | G/N | N | AST limited | proposal |
| throw/rethrow/try/catch profile 24 | C | C | C | C | C | C | C | event-out | C + corpus | C |
| modules/imports/visibility/declaration crossing | C | C | C | C | C/P | C/P | C/P | none | multi-file | C |
| imported globals and module initialization | C | C | C | C | N/G | N | G | N | AST | open/history |
| payload-free enums | C | C | C | C | C | C | C | i32 internal | C | C |
| payload enums/tagged unions/pattern matching | N | N | N | N | N | N | N | N | N | roadmap |
| structs, constructors, methods, equality | C | C | C | C | C | C | C for registered layouts | lifecycle | C | C |
| classes, ARC identity, constructors/methods | C | C | C | C | C | C | C | generated ARC | C | C |
| interfaces, witness dispatch, struct boxing | C | C | C | C | C | C | C | generated witness/box | C | C |
| tuples/destructuring | C | C | C | C | N/G | N | G | N | AST | experimental |
| `Array<T>` fixed sequence and slicing | C | C | C | C | C | C | C/P by layout | ARC buffer | C | C |
| `List<T>` growth/mutation/copy/search/sort | C | C | C | C | C | C | C/P by T/API | ARC buffer | C | C |
| Vector/Matrix core literals/index/basic ops | C | C | C | C | C/P | C/P | C/P | flat buffer | C | C |
| Vector/Matrix slicing, Matrix iteration | C/P | C/P | C/P | C/P | N/G | N | G | N | AST | experimental |
| advanced LinearAlgebra (solve/LU/QR/SVD/eigen) | calls | C | C | C via NumPy/SciPy | mostly N | N | G/N | N | AST extensive | audit |
| immutable UTF-8 string transport/Eq/concat/byteLength | C | C | C | C | C | C | C | ARC object | C | C |
| trim/split/parse/text files/process args | calls | C | C | C | C | C | C/P platform | libc/POSIX | C | C |
| interpolation/general formatting/string indexing | C/P | C/P | C/P | C/P | N/G | N | G/N | N | AST | experimental/open |
| `input` | C | C | C | C | N/G | N | N | N | AST | outside v1 |
| scalar math | calls | C | C | C | C/P | C/P | C/P | libm/intrinsics | C/P | C |
| user generics/constraints/monomorphization | G | N | N | N | N | N | N | N | rejection | roadmap |
| public C FFI | N | N | N | N | N | N | N | internal libc only | N | design only |
| O0/O1/O2 optimization profiles | CLI | — | gate | — | C | C | C | — | C | C |
| native build/run and artifact behavior | — | — | C | R | C | C | C | C | C | C |
| REPL | C | C | C | C | N | N | N | AST host | C | C |
| LSP/formatter/editor clients | C/P | C/P | P | — | N | N | N | Python tools | C/P | C/P |

### 8.1 Explicit `AST > native` inventory

The following current features have meaningful frontend/AST behavior but no
equivalent full native route, or only a narrower native subset:

- experimental `float`/`complex` and imaginary-number behavior;
- inferred untyped locals;
- nested functions and advanced callable forms (closures, bound methods,
  callable returns and builtins as values);
- imported global storage, constants requiring storage and module initializer
  execution;
- tuples and destructuring;
- interpolation/general formatting and typed `input`;
- stored ranges and general iterator protocol;
- Vector/Matrix slicing and Matrix iteration;
- most advanced `Math.LinearAlgebra` algorithms;
- portions of scalar math and platform-dependent file/process behavior;
- the AST-only REPL surface.

These are not Aether v1 support merely because they parse or run in AST.  Some
profile-24 features once listed here—exceptions, nullable, classes and
interfaces—now have native routes and must not be reported from older audits as
still AST-only.

## 9. KEEP / ADAPT / REDESIGN / DROP / NEW audit

Classification refers to the reconstruction, not file deletion during this
stage.  `DROP` means no role in the eventual canonical product; an item may
remain temporarily as oracle/rollback.

| Subsystem | Class | Current state and debt | Reusable value | Risk and recommendation |
|---|---|---|---|---|
| Lexer | ADAPT | Python lexer is Unicode-aware, location-bearing and tied to current token set | lexical corpus, escapes, numeric edge tests | Reimplement in Rust after syntax decisions; preserve exact literal text/spans |
| Parser | REDESIGN | Monolithic recursive descent constructs semantic types directly and recognizes experiments | grammar behavior, recovery tests, formatter corpus | New source-only AST/events; do not serialize Python AST as canonical schema |
| AST | REDESIGN | frozen dataclasses mix syntax with `AetherType` objects | node taxonomy and source examples | Separate source AST from typed HIR; optional lossless tooling tree later |
| Type system | REDESIGN | strings/unions of dataclasses mix source, semantic and interpreter values | nominal IDs, callable/nullable/collection lessons | Interned semantic types + independent target layout; fixed-width baseline |
| Type inference | ADAPT | useful local/contextual and abbreviated-return inference, embedded in checker | conservative policy and diagnostics corpus | Restrict and specify; add generic constraint inference without global inference |
| Typechecker | REDESIGN | 246-KiB authority mixes most frontend responsibilities | tests and resolved behavior | Query-based resolver/type analysis producing immutable HIR |
| Name resolution | REDESIGN | embedded in checker/module loading and Python maps | `ModuleId`/`SymbolId`, visibility/cycle cases | Dedicated phase/query with stable logical IDs |
| Modules/imports | REDESIGN | file resolver works; native rejects initialization/storage subset | syntax, cache/cycle/visibility tests | Define project roots and init semantics; no interpreter-only module authority |
| Diagnostics | ADAPT | public categories/codes exist; internal phases still pass exception strings | rendering contract, location tests, capability IDs | Structured diagnostic records end to end |
| AST interpreter | KEEP | broadest behavior, host Python/NumPy/SciPy can leak semantics | executable reference, REPL, differential oracle | Freeze its authority; never admit features; retire selectively after coverage |
| Initial IR | REDESIGN | mature slot/lifecycle IR and schema v1, shaped by Python transport/current types | opcode semantics, explicit places/lifecycle, corpus | Use as MIR evidence; new owned MIR need not preserve schema/opcode compatibility |
| DTO/schema transport | ADAPT | versioned v1/v2 enabled safe migrations but is still production materialization | schemas, fail-closed readers, golden transport tests | Keep for legacy differential/adapters; remove between new in-process stages |
| Rust importer | DROP | imports Python schema into owned Rust IR | validated parser and migration bridge | Transitional only; new frontend constructs owned HIR/MIR directly |
| IR verifier | ADAPT | Rust is exclusive pre-lifecycle authority; broad invariant registry | strongest correctness asset | Port invariant intent to new MIR; keep old verifier as legacy gate/oracle |
| Lifecycle lowering | ADAPT | explicit lifecycle strong; Python expansion plus Rust idempotent normalization | operations, dataflow rules, tests | Single Rust MIR authority after error/ownership model closes |
| Ownership model | REDESIGN | value structs, shared ARC handles, narrow borrows; uneven by type | lifecycle vocabulary and borrowed-for evidence | Define parameter modes/views/unique vs shared before runtime ABI |
| SSA construction | ADAPT | Rust authority with owned model; Python builders retained as oracles | dominance/phi algorithms, deep-CFG corpus | Build new SSA directly from new MIR in-process |
| SSA verifier | ADAPT | strong Rust and Python verifiers with unreachable/dominance rules | invariant/tests | One canonical Rust verifier; independent mutation tests remain |
| Refinement verifier | ADAPT | Rust proves normalized IR→SSA; Python is oracle | proof strategy and adversarial corpus | Retain during migration; specialize to MIR→SSA contract, not wire DTO equality |
| Optimization passes | ADAPT | useful O1/O2 scalar, BCE, LICM and ARC passes in Python | algorithms, proof/effect tests and measurements | Port selectively onto new SSA; add analysis preservation and scientific ops |
| LLVM backend | REDESIGN | huge Python textual printer mixes lowering/runtime/layout | native parity corpus, emitted semantics, ABI tests | Rust backend over verified SSA; bootstrap text emission allowed behind interface |
| clang/toolchain | ADAPT | correct practical compile/link subprocess, coupled to `.ll` | error mapping and build/run behavior | Isolate discovery/object/link; later LLVM object emission without semantic change |
| Runtime | REDESIGN | LLVM helpers embedded per module with private headers/symbols | checked arithmetic, ARC and IO behavior/tests | Separate versioned Rust runtime with generated C ABI; tiny C shims if justified |
| Strings | ADAPT | immutable UTF-8 ARC object is robust; indexing/text units incomplete | representation experiments, byte-aware corpus | Preserve semantic baseline; opaque ABI and explicit byte/scalar/view APIs |
| Arrays | REDESIGN | fixed contiguous mutable shared ARC handles; strong native safety subset | bounds/lifecycle/tests and contiguous layout | Decide value/share/move semantics; build on canonical buffer descriptor |
| Lists | ADAPT | broad growable API and checked runtime, layout duplicated in emitter | API/corpus/growth algorithms | Implement generic List over buffer/lifecycle traits after generics |
| Structs | ADAPT | nominal by-value fields, constructors/methods, recursive lifecycle | semantics and layout tests | Preserve value direction; add tagged unions/newtypes separately |
| Enums | REDESIGN | payload-free nominal i32 only | nominal identities and discriminant tests | Add payload enums/tagged unions and matching needed for general use/self-hosting |
| Functions as values | REDESIGN | capture-free top-level pointer subset | structural signatures/indirect-call tests | Design callable representation that can later add closures without infecting direct calls |
| FFI | NEW | no public FFI; libc use is backend implementation | native ABI audit | Add after target/layout/runtime schema; qualify first with a small C library/BLAS shape |
| CLI | ADAPT | Python CLI is functional, native default, many debug modes | UX, exit codes, run/build contract | Keep current during transition; add opt-in new driver only with first vertical compiler |
| Build/run | KEEP | already one native pipeline; temporary versus retained artifact only | exact desired semantic model | Preserve as invariant; no AST run fallback in new CLI |
| LSP | ADAPT | Python LSP has partial completion/hover/symbols and shares frontend | protocol/tests/editor clients | Keep until new compiler exposes incremental syntax/semantic queries; then thin client |
| Packaging | REDESIGN | Python language wheel plus native compiler-core wheel and companion | clean-consumer, provenance and multi-platform qualification | New compiler/runtime artifacts must be self-contained and versioned; Python tooling optional |
| Qualification infrastructure | KEEP | unusually rigorous shadow, authority, platform, artifact and fail-closed gates | direct strategic asset | Generalize to old-vs-new compiler promotion; reduce duplicated hand-written status prose |
| Scientific libraries | KEEP | valuable AST reference/dogfood; advanced LA host-dependent and non-native | algorithms, API friction reports, workloads | Freeze expansion; use as requirements/corpus after core language/buffers stabilize |

No classification is based on Python versus Rust alone.  Notably, the AST
interpreter and qualification Python are kept, while several Rust transport
components are transitional or require redesign.

## 10. Differential testing architecture

### 10.1 Harness

Every case has source bytes, project layout, target/profile, stdin/argv/files,
expected phase and an explicit comparison policy:

```text
case
  -> existing compiler native pipeline
  -> new compiler native pipeline
  -> optional AST/MIR reference evaluator (never admission authority)
  -> normalizer/comparator
```

Compare, as applicable:

- accepted/rejected and first rejecting phase;
- stable diagnostic ID, primary span and structured parameters (not necessarily
  prose);
- exported/resolved types and selected conversions;
- stdout bytes, stderr bytes, exit code and declared file effects;
- native behavior across O0/O1/O2/O3 and strict/relaxed FP as applicable;
- lifecycle/sanitizer results and allocation/copy/ARC event summaries;
- semantic IR properties (types, CFG, effects, ownership, shape), never raw
  textual equality between unrelated IR designs.

Cases are labelled `PRESERVE`, `INTENTIONAL_CHANGE`, `LEGACY_ONLY`,
`NEW_ONLY` or `OPEN_DECISION`.  An intentional difference requires a decision
ID and its own expected result.  Unknown divergence fails closed.

### 10.2 Corpus layers

1. lexical/parser golden and recovery cases;
2. positive/negative type and module cases;
3. semantic microprograms per feature/edge;
4. generated arithmetic/float/lifecycle/CFG mutations;
5. existing examples and exception corpus;
6. medium dogfoods (`Sorts`, numerical methods, structs/classes);
7. large dogfoods (`expense_tracker`) and scientific workloads;
8. ABI/target/sanitizer and performance suites.

The existing `differential.py`, `scripts/differential_parity.py`, schema
fixtures, verifier mutation campaigns and authority-promotion harnesses should
be adapted rather than replaced.

### 10.3 Native-first gate

A feature registry generated from compiler declarations maps each feature to
grammar/HIR/MIR/SSA/backend/runtime/test status.  Only `SUPPORTED` rows are
enabled in the default language profile.  `EXPERIMENTAL` requires an explicit
compiler flag and still needs a native path; frontend-only prototypes live in
tests/tools and cannot change the public parser's accepted stable grammar.

CI rejects:

- a supported row without native positive and negative evidence;
- a parser/typechecker addition with no capability classification;
- silent fallback or target-dependent acceptance not declared by the profile;
- a feature matrix manually disagreeing with the executable registry.

## 11. Transition strategy

### Phase A — contracts and harness (this stage)

- preserve all current source/compiler areas and the default CLI;
- establish charter, semantic decision ledger, architecture/audit and feature
  inventory;
- freeze a versioned differential manifest and choose the first scalar/error/
  ownership decisions needed by the vertical milestone;
- do not create empty compiler layers before their invariants can be tested.

### Phase B — first vertical Rust compiler

Create a temporary `compiler-next/` only when the milestone below begins.  It
owns source through native artifact for a deliberately tiny subset.  It may
reuse algorithms/crates, but not import Python objects or route through the
legacy Initial IR schema as its canonical pipeline.  The current CLI remains
default; an internal/new executable invokes the new compiler explicitly.

### Phase C — expand vertical slices

Add features in dependency order: explicit scalars/control, functions/modules,
aggregates/lifecycle, generics/core collections, strings/views, scientific
buffers/operations, errors/FFI.  Each slice closes parser→native plus
diagnostics/tests.  Legacy components become oracles, not fallbacks.

### Phase D — authority promotion

Promote only after corpus, platform, sanitizer, performance, packaging and
no-fallback gates succeed on an exact revision.  Switch the existing `aether`
CLI atomically.  Retain an explicitly named legacy command/configuration for a
bounded rollback window; never auto-rescue a rejected or failed new compile.

### Phase E — consolidation

After authority and rollback closure, the new area becomes `compiler/`.
Retire transitional Python/Rust DTO/companion paths proven redundant.  Keep
reference interpreters, historical evidence and useful qualification tooling.
Do not delete Git history or use orphan branches.

## 12. Self-hosting readiness

| Requirement | Needed for compiler work | Dependencies/current gap |
|---|---|---|
| payload enums/tagged unions + matching | AST/HIR/types/diagnostics | only payload-free enums today |
| generics and constraints | collections, results, compiler data structures | absent beyond rejection |
| strings, bytes and builders | source, diagnostics, mangling | strings exist; byte/char/builders/views open |
| Array/List plus maps/sets | tables, worklists, caches | Array/List exist; Map/Set absent |
| graphs/worklists | module graph, CFG, dataflow | compiler internals only, no core Aether API |
| errors/results and cleanup | every fallible compiler phase | mixed result structs/exceptions/panic; target open |
| modules/packages | compiler decomposition | module subset exists; project/init model open |
| file/path/process I/O | source/build/tooling | text/POSIX subset; binary/path portability absent |
| recursion and iterators/ranges | tree/graph algorithms | recursion/direct loops exist; general iteration absent |
| ownership/views | syntax buffers and arenas | narrow collection borrow only |
| allocation/performance controls | large compiler workloads | no public allocator/buffer control |
| deterministic serialization | caches/artifacts/bootstrap | DTO evidence exists, language library absent |

Recommended progression remains high-level stdlib/tests, then formatter/linter,
then selected parser/tooling.  Typechecking, verification, optimization and
LLVM lowering remain Rust unless a later measured ADR demonstrates a better
authority.  Stage0 Rust must build Stage1; no clean checkout depends on an
undocumented prebuilt Aether compiler.

## 13. First vertical milestone

Name: **NEXT-VERTICAL-0 — native scalar spine**.

Purpose: prove the proposed ownership of representations and the one native
pipeline, not language breadth.

Prerequisites:

- close the source spelling/width used for the milestone (`int` decision or an
  explicitly temporary legacy-i32 compatibility profile);
- choose panic behavior for checked scalar failures in this subset;
- define structured diagnostic/span and target descriptor minimums;
- version a differential manifest of approximately 20 positive/negative scalar
  programs.

Required implementation:

- new Rust driver/session, source database, lexer/parser and source AST for one
  file;
- explicit `main`, local typed bindings, integer/bool literals, arithmetic,
  comparison, `if`, return and direct helper functions;
- resolved typed HIR, flow MIR, verified SSA and LLVM backend boundaries with
  the invariants in section 6;
- Linux x86_64 object/executable via LLVM/clang bootstrap;
- `run` implemented strictly as build-to-temp plus execute in the new internal
  driver; build retains the same artifact;
- stable diagnostic IDs/spans, IR dumps for debugging and phase timings;
- old/new accepted/rejected, stdout/stderr/exit and optimization parity at O0;
- fail-closed rejection for every syntax/feature outside the slice.

Explicitly excluded: generics, strings, heap allocation, ARC, Matrix/Vector,
FFI, module initialization, exceptions/unwind, O2/O3 and self-hosting.

Exit criteria:

1. no Python object or JSON boundary inside the new source→SSA/backend path;
2. all IRs independently verified in tests;
3. same program feeds new build and run paths;
4. differential manifest has no unexplained divergence;
5. invalid features fail before unsupported lowering;
6. deterministic IR/artifact metadata across paths/host hash seeds where
   applicable;
7. compile phase timing baseline recorded;
8. current compiler and default CLI test suites remain green.

The next milestone should then add functions/modules or the first nontrivial
owned value only after its relevant semantic decisions are closed; it should
not jump directly to scientific libraries.

## 14. Scaffold decision and repository shape

No scaffold is created in this audit.  This is deliberate: `int`, literal
typing/overflow, error cleanup, parameter ownership and buffer value semantics
still influence the crate and IR boundaries.  Empty AST/HIR/MIR/SSA crates now
would encode names and dependencies without an executable invariant.

When NEXT-VERTICAL-0 starts, the temporary shape should be minimal, for example:

```text
compiler-next/
  Cargo.toml
  crates/
    aether-driver/       # session, CLI-internal build/run, toolchain
    aether-frontend/     # source AST, resolver, typed HIR
    aether-middle/       # MIR, SSA, verification, initial passes
    aether-backend-llvm/ # LLVM/object emission only
```

Do not split one crate per conceptual noun until dependency/cycle or build-time
evidence requires it.  Existing `compiler-rs` remains in place and may expose
reusable algorithms behind clean APIs; it is not renamed during the first
slice.  After promotion and consolidation, the canonical compiler should be
`compiler/`, not a permanent version-suffixed directory.

## 15. Risks and controls

| Risk | Control |
|---|---|
| Designing a new language accidentally while porting | semantic decision statuses, compatibility labels and differential corpus |
| Recreating AST > native | executable feature registry and native-first CI gate |
| Architecture layers without purpose | representation invariants/consumers in section 6; vertical milestone before expansion |
| Losing scientific optimization facts | typed HIR/MIR bulk ops and explicit shape/layout/alias metadata |
| Over-applying ARC or Rust borrowing | type-specific ownership model and Aether-focused view experiments |
| Backend/runtime ABI drift | target descriptor plus generated versioned C ABI schema |
| Compile-time regression | in-process owned IR, phase telemetry, query/cache design and no wire boundary inside core |
| Oracle bugs becoming new semantics | multiple evidence sources, native comparison and labelled intentional changes |
| Legacy maintenance becoming permanent | named authority, rollback and retirement criteria for every duplicate |
| Premature self-hosting | Stage0-first dependency inventory and formatter/high-level library progression |
| Documentation drift | normative small set + generated current inventory; dated audits remain explicitly historical |

## 16. Deliberately unchanged in this stage

- no current compiler, CLI, runtime, LSP, examples or tests were moved/deleted;
- no source-language semantics, capability profile or release version changed;
- no tag, branch, remote operation, history rewrite or Git initialization was
  performed;
- no new compiler directory/crate or empty abstraction was added;
- no scientific library expansion or Python→Rust migration milestone was
  continued mechanically;
- no public ABI, FFI syntax, generic syntax, unsafe syntax, `int` width or
  indexing-base decision was invented without evidence.
