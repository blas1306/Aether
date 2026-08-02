# Aether Strategic Roadmap and Architecture Vision

> Status: strategic direction after exception release qualification.
>
> This document is a roadmap, not a statement that planned features are
> implemented. The current language contract remains the
> [Aether 1.0 Language Specification](../aether/AETHER_LANGUAGE_SPEC_V1.md) and
> the current executable boundary remains
> [native capability profile 23](../aether/AETHER_NATIVE_PROFILE_V1.md).
>
> No date in this document is a delivery commitment. Priorities express order
> and dependency, not schedule.

## Executive summary

Aether is an ahead-of-time compiled, statically typed, general-purpose
language with deliberate strengths in mathematics, numerical methods, and
simulation. Its enduring objective is:

> 100% general-purpose core and 130% mathematical ergonomics.

The project has reached a credible release-candidate architecture. The
frontend, typed Initial IR, lifecycle expansion, verified SSA, conservative
optimizers, textual LLVM generation, capability gate, and AST/native
differential tests form a coherent compiler. Native profile 23 supports a
closed end-to-end subset on Linux x86_64, including checked scalars, functions,
control flow, strings, modules without imported initialization, value structs,
reference classes, nominal interfaces, nullable values, collections, and a
core Vector/Matrix surface. The default Initial IR verifier remains Python;
the Rust verifier has reached explicit, fail-closed canary operation but is not
the product authority.

The project is not yet production-ready as a whole. It has no public ABI or
FFI, no separately versioned runtime artifact, no supported native target
beyond Linux x86_64, no production package ecosystem, limited source-level
debugging, and several incremental developer tools. Parts of the documentation
also retain historical snapshots, but those documents are explicitly
non-normative; the current specification and capability profile remain the
authority.

The remainder of the 1.x series should emphasize:

1. correctness and honest compatibility before new syntax;
2. one authoritative, generated description of capabilities;
3. a small, portable runtime with a versioned internal boundary;
4. complete ownership and lifecycle rules based on ARC for 1.x, while keeping
   explicit memory facilities and optional future tracing as evidence-driven
   research rather than prematurely adding a hybrid memory model;
5. a minimal C interoperability boundary and source-based package workflow;
6. Linux-first portability followed by ARM64, macOS, and Windows;
7. dependable LSP, formatting, testing, documentation, and build tools;
8. scientific libraries written in Aether or backed by established native
   libraries instead of a growing set of compiler builtins; and
9. optimization only after effects, aliasing, ownership, and target contracts
   make transformations demonstrably safe.

Aether 2.0 should be reserved for changes that cannot preserve 1.x source
compatibility or that require a deeper type/runtime model. Closures, algebraic
data types with full pattern matching, and structured concurrency are
candidates for that design process. User-defined generics may fit late 1.x if
a deliberately limited design preserves compatibility; otherwise they remain
a 2.0 candidate. These are not automatic commitments. Reflection, an
unbounded hybrid memory model, advanced macros, a home-grown machine-learning
stack, and a home-grown BLAS/LAPACK remain outside the language's intended
core.

## 1. Current project assessment

### 1.1 Release and language state

The repository identifies the current candidate as `1.0.0-rc.4` with native
capability profile 23. The candidate is explicitly not a declaration of
production readiness and defines no public ABI. The normative profile reports
32 complete, 31 partial, and 3 unsupported capability families. “Partial”
means that a typed detector admits a precisely documented subset; it is not
permission for best-effort lowering.

The public example catalog at the Phase 6.1 boundary contains 89 `V1_NATIVE`
examples and 16 `AST_ONLY_EXPERIMENTAL` examples, with no examples classified
as broken. This is useful evidence of breadth, but the language contract is
defined by the specification, capability profile, gate, and tests rather than
by example count.

### 1.2 Implementation inventory

| Area | Current state | Assessment |
| --- | --- | --- |
| Language implementation | Python lexer, parser, AST, multi-phase typechecker, module resolver, entry-point normalization, AST interpreter, REPL/session model, and an explicit native capability detector. The AST accepts a wider experimental surface than native. | **Mature within the v1 profile.** The closed native subset is coherent. AST-only behavior is experimental and must not silently define future language semantics. |
| Compiler pipeline | `source -> typed program -> Initial IR -> lifecycle expansion -> verified SSA -> optimization -> LLVM -> clang`. The general dominance-frontier SSA builder is the default; the pattern builder is retained for comparison. | **Mature architecture, release-candidate implementation.** Internal Python object boundaries and duplicated type/layout knowledge still limit portability and independent components. |
| Runtime | LLVM text is generated into each module. It supplies checked integer operations, allocation checks, panics, UTF-8 strings with non-atomic ARC, process arguments, text files, Array/List, Vector/Matrix, nullable, class, and interface helpers. | **Mature for the admitted Linux profile, not a production runtime product.** It is not a separate artifact, has no stable ABI, uses target-dependent layouts, and lacks concurrency-safe ownership. |
| LLVM backend | Textual LLVM consumes verified optimized SSA and invokes clang. It covers profile 23 and is exercised at clang `-O0`, `-O1`, and `-O2`. | **Mature for Linux x86_64 profile 23.** Target triple/data layout, debug metadata, cross-compilation, object compatibility, public linking, and multi-platform runtime boundaries are absent. |
| Initial IR verifier | Python verifier is the ordinary product authority. A versioned JSON IR schema, Rust importer/verifier, strict subprocess protocol, shadow comparison, packaging checks, cross-platform snapshot workflow, soak tooling, and a Rust-authority canary exist. | **Python path: mature. Rust path: advanced experimental/canary.** Rust is not the default product authority and cannot be promoted merely because the implementation exists. |
| SSA verifier | Verifies structure, definitions and uses, dominance, phi edges, types, terminators, and unreachable-block policy; it runs before LLVM and in optimizer tests. | **Mature internal component.** Its model remains an internal Python representation with no public compatibility promise. |
| Documentation | Normative v1 specification, native profile, diagnostics contract, ABI description, design RFCs, audits, release notes, and implementation guides are extensive. Consistency scripts validate release identities and generated profile content. | **Mature with an explicit authority hierarchy.** Historical matrices and implementation snapshots are explicitly non-normative; current generated summaries should continue to derive from authoritative capability data. |
| CLI and tooling | CLI can check, inspect tokens/AST/IR/CFG/SSA/LLVM, run AST/native, build, benchmark, and start a REPL. The LSP provides diagnostics, completion, formatting, symbols, hover, definition, and references. VS Code and IntelliJ clients exist. | **CLI: mature for development and RC use. LSP/editor support: incremental.** Workspace semantics, rename, semantic tokens, robust multi-file indexing, source debugging, profiling, package management, and doc generation are incomplete or absent. |
| Testing | Broad pytest and Cargo suites, negative fixtures, differential AST/native execution, optimizer regression checks, example catalog checks, release contracts, Rust verifier corpora, canary/soak tools, and microbenchmarks. | **Mature correctness culture.** Native tests may skip without clang; the main local CI is not itself a complete hosted target matrix, coverage is not a release metric, sanitizers are not a universal gate, and performance benchmarks have no stable baseline. |
| Release process | A local gate checks repository/document/capability consistency, runs tests and differential/native smokes, builds wheel and sdist, verifies contents, installs the wheel in a clean environment, and emits a manifest and checksums. It refuses dirty release builds by default. | **Mature candidate packaging, not a complete stable release service.** It does not publish, tag, sign, claim bit-for-bit reproducibility, bundle clang, or produce supported multi-platform native packages. |

### 1.3 Production-ready, mature, experimental, and absent

These labels apply to public use, not merely to code quality.

#### Production-ready

No end-to-end Aether distribution or public compiler/runtime ABI is currently
production-ready. Profile 23 is a release-candidate contract on one native
platform. Individual gates are release-grade engineering, but they do not
remove the stated platform, ABI, packaging, debugging, and operational limits.

#### Mature

- lexical analysis, parsing, source locations, type checking, entry-point
  normalization, and the stable frontend diagnostics path;
- the closed capability gate and fail-early rejection of native exclusions;
- the profile-23 path through Initial IR, lifecycle, general SSA, verification,
  conservative optimization, LLVM, and clang on Linux x86_64;
- checked integer, bounds, allocation, string, collection, nullable, class,
  and interface invariants within the supported profile;
- AST/native observable parity checks for admitted programs;
- Python Initial IR verification and SSA verification;
- normative v1/profile/diagnostics documentation and candidate artifact
  validation.

#### Experimental

- AST-only language features and host-backed scientific functionality;
- the Initial IR interpreter as a characterization tool;
- Rust verifier authority outside its explicit canary;
- `-O2` as an Aether optimization profile, because it currently adds no
  distinct Aether middle-end strength over `-O1`;
- the AST-only REPL as a model for compiled execution;
- multi-platform native support beyond the validated Linux x86_64 boundary;
- advanced linear algebra backed directly by Python/NumPy/SciPy;
- the development VS Code extension, incremental IntelliJ support, and
  workspace-wide LSP behavior;
- any internal layout, helper name, mangling scheme, IR schema revision, or
  runtime representation not explicitly versioned as a compatibility domain.

#### Intentionally absent

- a public stable ABI, precompiled Aether library format, and general FFI;
- user-defined generics, closures, lambdas, generators, and a public iterator
  protocol in the current contract; generics and the public protocol remain
  late-1.x/2.0 design candidates;
- class inheritance, interface inheritance, default methods, downcasts,
  reflection, and user-defined destructors;
- tracing GC, optional explicit arenas/regions/allocator-backed buffers, weak
  references, and concurrency-safe ARC in the current contract; the explicit
  facilities and optional tracing remain research areas;
- promotion of the implemented native catchable-exception path. Its frozen
  source semantics and private event-out architecture exist, but qualification
  blockers keep it outside the stable capability profile;
- async, threads, synchronization primitives, and a formal memory model;
- macros and general compile-time metaprogramming;
- debugger integration, stable profiler integration, a package registry, and
  a documentation generator;
- GPU execution, WebAssembly support, JIT compilation, and cross-compilation;
- a project-owned ML framework or replacements for NumPy, SciPy, BLAS, and
  LAPACK.

“Intentionally absent” does not always mean “never.” It means that the feature
is not part of the current contract and must not be inferred from a nearby
implementation detail.

## 2. Vision statement

### 2.1 Intended identity

Aether is a statically typed, ahead-of-time compiled language for programs that
combine ordinary software structure with serious numerical work. A short
numerical experiment should be able to become a multi-module native program
with domain types, errors, collections, files, tests, and deployment without
being rewritten in another language.

Aether should serve:

- numerical algorithms and simulations where predictable native execution
  matters;
- scientific utilities that need stronger structure and deployment than an
  exploratory script;
- small and medium general-purpose command-line or library programs;
- teaching and inspection of compiler behavior through readable IR, SSA, and
  diagnostics; and
- interoperability with established native scientific libraries rather than
  replacement of those libraries.

It should not try to dominate every domain. Web frameworks, GUI stacks,
database ecosystems, managed enterprise applications, hard real-time systems,
and large-scale data platforms may use Aether through packages or
interoperability, but they do not define the core language.

### 2.2 Comparable languages

Comparisons describe useful reference points, not compatibility goals:

- **Julia** is the closest comparison for mathematical ergonomics and
  scientific intent, while Aether favors an explicit ahead-of-time pipeline,
  a closed native capability contract, and static type boundaries.
- **Rust and Swift** are relevant for explicit value/reference semantics,
  ownership-aware lowering, strong diagnostics, and native library design.
  Aether does not intend to copy Rust's borrow checker or Swift's complete
  object/runtime model.
- **C++** is relevant as the native scientific ecosystem Aether must be able to
  call into, not as a model for language complexity or source compatibility.
- **Java, C#, and Kotlin** provide useful lessons for nominal interfaces,
  developer tooling, and stable library evolution, while Aether should avoid
  making a large managed runtime mandatory.
- **Python** remains an important interoperability and workflow reference for
  scientific users, but Python host behavior must not leak into stable Aether
  semantics.

### 2.3 Fundamental principles

1. **General-purpose foundations are first-class.** Modules, types, errors,
   collections, IO, testing, and tools must remain coherent even when a program
   contains no mathematics.
2. **Mathematical ergonomics use the same language.** Vector/Matrix shape,
   numerical APIs, and scalar math must integrate with ordinary types,
   functions, modules, and diagnostics.
3. **Static semantics are real contracts.** Types, mutability, identity, copy,
   aliasing, ownership, bounds, overflow, and failure behavior must survive all
   compiler stages.
4. **A feature is end-to-end or explicitly gated.** Parser acceptance, an AST
   node, an opcode, or an AST implementation alone is not language support.
5. **Correctness outranks optimizer ambition.** Traps, allocation, lifecycle,
   IO, and mutation are observable unless proven otherwise.
6. **The runtime stays small.** Representation, allocation, safety, and system
   boundaries belong in the runtime; expressible algorithms belong in
   libraries.
7. **Libraries precede syntax.** A new builtin, intrinsic, or grammar form
   needs evidence that ordinary library design cannot provide the required
   semantics or performance.
8. **Portability is designed, not assumed.** Target layout, OS boundaries,
   toolchains, and ABI differences must be explicit.
9. **Dogfood drives expansion.** Complete programs should expose the need for
   features before the grammar or runtime grows.
10. **Compatibility is a product feature.** Stable source should not be
    invalidated for aesthetic cleanup.

### 2.4 Principles that must not be compromised

- no silent fallback from native compilation to AST execution;
- no reliance on Python, LLVM, libc, or a scientific host library as an
  undocumented source of language semantics;
- no optimizer transformation that weakens safety, lifecycle, or observable
  behavior;
- no promotion of a feature without positive, negative, safety, parity, and
  documentation evidence for every applicable stage;
- no public ABI claim without an explicit version, target contract, ownership
  convention, and compatibility test suite;
- no expansion of compiler intrinsics merely to make the standard library
  easier to implement;
- no attempt to build inferior replacements for established numerical
  libraries when a stable integration boundary is the better architecture;
- no weakening of the general-purpose core to make a single mathematical
  notation convenient.

## 3. Release philosophy

### 3.1 Compatibility domains

Aether versions several distinct contracts. They must never be collapsed into
one number:

| Contract | Versioning and guarantee |
| --- | --- |
| Language source and observable semantics | Semantic Versioning through the public Aether version. Stable within a major version under the rules below. |
| Native capability profile | Independent monotonic profile number describing the exact executable subset. A bump does not by itself change language or package versions. |
| Package/distribution | PEP 440 package version derived from the public release and validated against wheel/sdist metadata. |
| Public diagnostics | Stable documented category/code contract. Wording and hints may improve unless a message is explicitly machine-readable. |
| Initial IR transport | Independently versioned internal schema/protocol. It is a compiler-component contract, not a source or public object ABI. |
| Runtime/internal compiler ABI | Unstable until a separately versioned boundary is introduced. |
| Public C ABI/FFI | Absent today. When introduced, it receives its own ABI version and target matrix. |
| Editor protocol | Standard LSP plus documented Aether extensions, versioned independently when extensions are added. |

### 3.2 Alpha

An Alpha proves architecture and semantics, not compatibility.

- Source syntax and semantics may change without migration support.
- Features may be incomplete across backends if clearly classified.
- The ABI, runtime, IR, packages, and artifacts have no compatibility
  guarantee.
- The compiler must still reject unsupported programs explicitly; Alpha is not
  permission for silent miscompilation.
- Known correctness limitations, supported hosts, and test gaps must be
  published.
- An Alpha compiler guarantee is limited to the declared experimental
  capability set and its tests.

### 3.3 Beta

A Beta is feature-complete for its proposed stable profile.

- No new language feature enters the target profile after Beta without
  returning the release to Alpha or explicitly restarting Beta qualification.
- Source syntax and type semantics are substantially frozen.
- Breaking source changes require a demonstrated correctness or evolution
  problem, release notes, a migration/rejection test, and a tool-assisted
  migration where mechanical conversion is possible.
- The native capability gate must be exhaustive for the proposed profile.
- The runtime and ABI may still change internally; no cross-version binary
  compatibility is implied.
- The compiler must pass the full positive, negative, parity, optimizer, and
  clean-install suites for the supported target.

### 3.4 Release Candidate

A Release Candidate is a build believed to satisfy the stable contract.

- RC1 freezes the language specification, capability profile, public
  diagnostics, supported targets, and release contents.
- Later RCs accept correctness, security, documentation, packaging, and
  portability fixes within that contract.
- No intentional source break is allowed after RC1. An unavoidable break
  requires an RFC, migration tooling, a new qualification window, and an
  explicit statement that the previous RC contract was superseded.
- No new feature may be enabled merely because the frontend already accepts
  it.
- Internal ABI/layout changes remain allowed because 1.0 does not promise
  object compatibility, but they require full rebuild and parity evidence.
- A compiler that accepts a conforming program and then fails in lowering,
  verification, LLVM, or clang has a release-blocking compiler defect.

### 3.5 Stable 1.0

Stable 1.0 establishes the source and semantic baseline.

- Every conforming 1.0 source program must continue to parse, type-check, and
  preserve specified observable behavior in later 1.x compilers, subject only
  to documented bug and security fixes.
- Aether source dependencies are rebuilt from source. 1.0 does not promise
  cross-release object, LLVM IR, runtime, mangling, or layout compatibility.
- Stable 1.0 guarantees only the targets listed in its release profile.
- Optimization levels must preserve semantics. They do not guarantee a
  specific speedup, instruction sequence, or bit-for-bit executable.
- The compiler must produce a documented source/capability/toolchain
  diagnostic or a valid artifact. An ICE is always a compiler bug.
- Build reproducibility claims must be exact. Until bit-for-bit
  reproducibility is validated, manifests record inputs and hashes without
  claiming deterministic bytes.

### 3.6 Evolution within 1.x

The 1.x series is additive and source-compatible.

- Minor releases may add syntax only when it is unambiguous for every valid
  1.x program and old behavior does not change.
- New APIs, targets, diagnostics, optimizer passes, and capability families may
  be added behind explicit gates and feature-complete tests.
- Existing stable APIs may be deprecated but not removed during 1.x.
- Deprecation warnings must identify a replacement and remain available for at
  least two minor releases; removal waits for 2.0 unless a security issue makes
  continued support unsafe.
- Tightening acceptance is allowed only for programs that violated an existing
  normative rule or depended on an implementation bug. Such changes require a
  compatibility note and regression corpus.
- Public ABI compatibility is not retroactively implied. If a stable C ABI is
  introduced in a 1.x release, that ABI is versioned from its introduction.
- A newer compiler must be able to identify which profile a dependency or
  artifact requires and fail clearly when it cannot satisfy it.

### 3.7 Evolution in 2.0

2.0 is the place for justified source or semantic breaks, not a periodic
rewrite.

- Every breaking proposal requires an accepted RFC, alternatives, ecosystem
  impact, a migration story, and end-to-end implementation evidence.
- A 2.0 compiler should diagnose or migrate 1.x constructs where mechanical
  conversion is possible.
- The complete 1.x conformance corpus must be classified as unchanged,
  migrated, deliberately rejected, or corrected; silent loss is unacceptable.
- Internal rewrites do not require 2.0 unless they change a public contract.
- Fundamental principles in the vision remain binding across the major
  version.

## 4. Compiler roadmap

Priority levels are relative:

- **Critical:** required to establish a trustworthy stable baseline.
- **High:** unlocks major 1.x value or removes a structural risk.
- **Medium:** valuable after the critical foundations are stable.
- **Low:** compatible convenience work that must not displace foundations.
- **Research:** investigate before promising a release feature.

| Category | Work | Priority | Rationale |
| --- | --- | --- | --- |
| Core language | Keep one executable capability authority and generate profile tables, tests, examples, and tooling metadata from it. | Critical | Prevents frontend/backend/document drift and makes compatibility reviewable. |
| Core language | Complete compiled module storage and exactly-once initialization for globals/constants/top-level initialization. | High | Converts the current partial module model into a dependable general-purpose foundation. |
| Core language | Consolidate typed-program metadata so lowering does not depend on the live Python typechecker/AST for backend facts. | High | Establishes a portable, testable frontend/backend boundary. |
| Core language | Unify lowering and analysis for the existing built-in `for-in` sources without exposing a public Iterator protocol. | Medium | Removes duplicated iteration machinery while preserving the current language surface. |
| Core language | Evaluate basic scalar/payloadless-enum `match` and add `do-while` only through normal end-to-end promotion. | Low | Both are compatible conveniences; neither should delay correctness, runtime, module, or tooling work. |
| Core language | Remove the legacy pattern SSA builder after the general builder has an explicit retirement gate and corpus equivalence. | Medium | Reduces duplicate semantics and maintenance risk. |
| Runtime | Define a canonical type-layout/lifecycle descriptor shared by lowering, verifiers, LLVM, and runtime generation. | Critical | Eliminates hard-coded layout knowledge spread across layers. |
| Runtime | Separate runtime primitives behind a versioned internal C-compatible ABI, with opaque handles and per-target artifacts. | High | Enables portability, sanitizer testing, smaller generated modules, and eventual FFI. |
| Runtime | Complete uniform lifecycle semantics for Vector/Matrix and every supported aggregate. | High | Required before safe optimization or external ABI exposure. |
| Optimization | Make optimization profiles honest: define Aether `O0`, `O1`, and `O2` pass sets and connect them consistently to inspection and native builds. | High | Users must not infer strength from an alias. |
| Optimization | Introduce explicit call/effect summaries and alias/escape facts before aggressive passes. | High | Inlining, GVN, LICM, ARC elimination, and bounds elimination depend on sound effects. |
| LLVM | Emit explicit target triple/data layout and validate supported LLVM/clang versions. | Critical | Required for reproducible target behavior and any second native platform. |
| LLVM | Add debug locations, function/source maps, and stable panic frames for developer builds. | High | Enables source debugging and useful native diagnostics. |
| LLVM | Separate target-independent codegen from OS/runtime lowering. | High | Prevents POSIX assumptions from leaking into Windows, macOS, WASI, or ARM work. |
| Diagnostics | Preserve one public diagnostic model from lexer through linker/toolchain, including import and backend provenance. | Critical | Stable failures are part of the compiler contract. |
| Diagnostics | Add actionable fix hints and structured output without exposing host exceptions. | Medium | Improves IDE and CI integration while retaining stable codes. |
| Tooling | Build a persistent workspace semantic index shared by LSP, formatter, doc generator, and package tooling. | High | Regex/document-local services do not scale to real projects. |
| Tooling | Define a source package manifest, lockfile semantics, dependency resolution, and reproducible source builds before a registry. | High | A source-compatible ecosystem is needed before binary package promises. |
| Testing | Require per-feature positive, negative, boundary, optimizer, AST/native, and target tests; generate coverage reports by capability rather than line count alone. | Critical | Measures semantic completion instead of implementation presence. |
| Testing | Add sanitizer, fuzz/property, mutation, and miscompilation reduction workflows. | High | Memory/lifecycle and optimizer bugs need independent detection methods. |
| Testing | Establish performance baselines with noise policy and no-regression thresholds for selected workloads. | Medium | Makes optimization work evidence-based without turning microbenchmarks into language guarantees. |
| Documentation | Preserve the authority hierarchy and automate non-normative banners/version stamps for historical audits. | Critical | Historical material is valuable evidence, but it must remain clearly distinct from the current normative profile. |
| Documentation | Generate language/API/reference pages from checked declarations and capability data where possible. | Medium | Reduces manual duplication and prepares a documentation generator. |

## 5. Language roadmap

Classification means:

- **Completed:** part of the current profile in the stated scope.
- **Planned for 1.x:** compatible work that fits the existing model.
- **Possible for 1.x:** compatible optional work that must still earn
  end-to-end promotion and may be deferred.
- **Candidate for late 1.x or 2.0:** design may fit an additive late-1.x
  subset, but moves to 2.0 if it requires incompatible semantics.
- **Candidate for 2.0:** requires design and may be rejected; it is not a
  promise.
- **Research:** an intentionally open design area, not a release commitment.
- **Out of scope:** not a strategic language goal without new evidence.

| Language area | Classification | Direction and boundary |
| --- | --- | --- |
| Exceptions | **Implemented internally; promotion blocked for 1.x** | Frozen semantics, explicit cleanup, verified SSA, private event-out lowering, runtime and boundary containment exist. Resolve the capability over-rejection, Initial IR `may_throw`/lifecycle disagreements, public tooling gaps and integrated release evidence before promotion. `finally`, hierarchies, resumable exceptions, public FFI and general unwinding are not implied. Result/status types remain preferred for expected numerical failures. |
| Basic scalar/payloadless-enum `match` | **Possible for 1.x** | A non-destructuring match over scalar constants and today's payloadless enums may be added compatibly, with exhaustiveness or explicit default rules and ordinary control-flow lowering. It is optional and lower priority than completing the stable foundations. |
| Full algebraic pattern matching | **Candidate for 2.0** | Payload destructuring, guards, nested patterns, bindings, and exhaustiveness over algebraic data types belong with a future payload-enum/ADT design. Basic `match` does not pre-commit that representation or syntax. |
| `do-while` | **Planned for 1.x (low priority)** | Add only as compatible loop syntax with the same control-flow, `break`/`continue`, verifier, optimizer, formatter, and tooling guarantees as existing loops. It must not displace higher-priority 1.x work. |
| Internal iteration unification | **Planned for 1.x** | Unify compiler lowering/analysis for current built-in ranges and collections, preserving borrowed-element and mutation rules. This is an internal architecture improvement and does not expose iterator objects or a public protocol. |
| Public `Iterable`/`Iterator` protocol | **Candidate for late 1.x or 2.0** | A public protocol for user-defined and non-indexable sources depends on generic constraints, lifecycle, mutation rules, and error behavior. It may fit late 1.x only as a compatible, deliberately limited design; otherwise it belongs in 2.0. |
| Generators | **Out of scope** | They would add suspended frames, hidden allocation, exception/cancellation semantics, and closure-like lifecycle without a demonstrated core need. |
| Closures | **Candidate for 2.0** | Capture-free top-level function values are complete. Captured environments require an explicit descriptor, escape/lifecycle rules, and ABI; do not infer them from function pointers. |
| Lambdas | **Candidate for 2.0** | Evaluate together with closures and callable returns. Expression-function declarations remain named functions, not lambdas. |
| Class inheritance | **Out of scope** | Prefer interfaces and composition. Identity/reference classes are complete without inheritance; override chains, downcasts, and fragile base layouts would substantially expand the object model. |
| Traits/interfaces | **Completed** | Nominal interfaces with class carriers, owned struct boxing, witness dispatch, and lifecycle are complete. Interface inheritance, default implementations, associated types, and trait-style compile-time specialization are separate future proposals, not part of this classification. |
| Reflection | **Out of scope** | Manual ALPT1 serialization is deliberately not reflection. Static metadata for tooling or FFI may exist without a runtime reflective object model. |
| Async | **Candidate for 2.0** | Consider only after threading, synchronization, cancellation, ownership across tasks, and platform event loops have stable contracts. No “async syntax first” path. |
| Modules | **Planned for 1.x** | Cross-file declarations, imports, aliases, privacy, cycles, and supported native calls/types exist. Complete global storage and exactly-once initialization while preserving current source syntax. |
| User-defined generics | **Candidate for late 1.x or 2.0** | Privileged `Array<T>`, `List<T>`, and mathematical types do not constitute a general generic system. A limited additive design may fit late 1.x; any design that breaks source compatibility or requires a new runtime/type identity model waits for 2.0. A proposal must cover specialization/erasure, constraints, diagnostics, code size, ABI, and separate compilation. |
| Ownership | **Planned for 1.x** | Complete and regularize the existing internal value lifecycle and ARC model. Public borrow syntax, a general borrow checker, and user destructors are not 1.x commitments. Unrestricted source-level `malloc`/`free` is rejected because it would bypass lifecycle and safety. |
| Optional explicit memory facilities | **Research** | Arenas, lexical regions, allocator-backed buffers, and similarly scoped facilities may be explored for measured scientific/system workloads. Any proposal must retain checked sizing, deterministic cleanup, alias/lifetime safety, and clear FFI interaction without becoming unrestricted manual allocation. |
| Garbage collection | **Research** | Strong ARC remains the 1.x baseline. Optional future tracing may be evaluated for measured cycles, concurrency, or ARC costs; it is neither promised nor permanently ruled out. Avoid an unbounded hybrid model and require explicit rooting, FFI, pause, ownership, and ABI semantics before adoption. |
| FFI | **Planned for 1.x** | Introduce a deliberately small C ABI: stable scalar rules, opaque handles, explicit ownership, error transport, and target-specific validation. C++/Python wrappers should be external layers over it. |
| SIMD | **Candidate for 2.0** | Prefer optimizer vectorization and external kernel libraries before source-level SIMD types or intrinsics. A source feature needs portable lane semantics and fallback behavior. |
| Compile-time evaluation | **Candidate for 2.0** | Current constant folding is an optimizer, not user-visible evaluation. A future restricted evaluator must be deterministic, bounded, side-effect-free, target-aware, and unnecessary for ordinary module constants. |
| Macros | **Out of scope** | Advanced metaprogramming is a stated non-goal. Repetition should first be addressed with functions, generics, code generation tools, or library design. |

Additional 1.x language work should prioritize completing already approved
semantics: module initialization, uniform ownership, basic native errors,
portable process/filesystem boundaries, and minimal FFI. Low-priority
`do-while`, basic `match`, or a deliberately limited late-1.x generic/iterator
design must still be additive, justified by dogfood, and promoted end to end.
Frontend experiments must either receive an end-to-end promotion RFC or remain
explicitly outside the stable language.

## 6. Scientific computing roadmap

### 6.1 Layering policy

Scientific features belong in one of three places:

1. **Standard/extended library:** portable algorithms expressible in Aether,
   with stable types and deterministic contracts.
2. **Compiler/runtime support:** representation, checked shapes, contiguous
   storage, vectorization, and FFI primitives that libraries cannot implement
   safely or efficiently.
3. **External integration:** large, hardware-specific, or independently
   evolving libraries such as BLAS, LAPACK, FFT implementations, optimization
   suites, ML frameworks, and GPU runtimes.

The existing AST path through Python, NumPy, SciPy, SymPy, and Matplotlib is
valuable for experiments but must not become an accidental native language
contract. Stable scientific APIs either need an Aether implementation or an
explicit native external dependency with a defined compatibility boundary.

### 6.2 Capability areas

| Area | Standard/extended library candidates | Compiler/runtime features | External integration |
| --- | --- | --- | --- |
| Core numerical methods | Bisection, Newton, secant, interpolation, quadrature, finite differences, convergence/status types, tolerance policies, and reusable scalar callables. Start from the existing Numerical Methods dogfood. | Efficient capture-free callbacks, checked arithmetic behavior, stable floating formatting, optimization of small numeric loops. Closures are not required for the first library. | Optional comparison/acceleration through established scientific packages; no mandatory dependency for basic methods. |
| Linear algebra | Stable Vector/Matrix construction, shapes/orientation, transpose, dot/inner/norm, matrix multiplication, solve status, and small-matrix algorithms in an extended `math.linalg` library. | Canonical Vector/Matrix descriptors with shape and ownership, contiguous layout, bounds/shape elimination, alias metadata, vectorization, and C FFI. | BLAS/LAPACK for dense kernels and decompositions. Sparse, distributed, and vendor-accelerated backends belong in packages. |
| Statistics | Descriptive statistics, numerically stable online moments, covariance/correlation, sampling helpers, and explicit missing-data policy in an extended library. | Reproducible random primitives and optimized reductions; no statistics-specific syntax. | Advanced distributions, inference, data frames, and specialized estimators in packages using established native libraries where appropriate. |
| Optimization | Bracketing, one-dimensional minimization, gradient-free small solvers, result/status records, and common stopping criteria. | Callable performance, loop optimization, optional autodiff research only if demanded by real packages. | Mature nonlinear, constrained, mixed-integer, and large sparse solvers through C ABI adapters. Do not reimplement complete solver suites. |
| Differential equations | Basic fixed-step explicit ODE integrators and shared result/event records are extended-library candidates after numerical APIs stabilize. | Efficient callback invocation, owned work buffers, reliable floating behavior, and possibly stack/arena allocation proven by escape analysis. | Adaptive/stiff ODE, DAE, PDE, sparse Jacobian, and domain-specific solvers in external packages. |
| Signal processing | Small convolution/windowing utilities and well-defined sample/buffer types may enter an extended library. | Bounds elimination, SIMD/vectorization, contiguous slices/views only after ownership design. | FFT, filter-design suites, codecs, and device IO through established libraries and packages. |
| Machine learning support | Core tensor-independent numerical utilities only; no Aether-owned ML framework. | FFI, stable buffers, shape metadata, profiling, and optional accelerator abstractions after CPU semantics mature. | Interoperate with existing inference/training runtimes and model formats through packages. Framework-specific APIs evolve outside the stdlib. |
| GPU support | No core or standard-library API in 1.x. | Research portable memory/address-space, kernel, error, and synchronization contracts only after CPU ABI and SIMD are stable. | Initial support should use external CUDA/HIP/OpenCL/Vulkan/portable compute ecosystems through packages, not a new Aether GPU runtime. |

### 6.3 Scientific quality requirements

Every stable numerical API must specify:

- accepted types and numeric promotion;
- shape/orientation rules;
- overflow, NaN, infinity, signed-zero, and domain behavior;
- tolerance and convergence semantics;
- deterministic/reproducible guarantees and their limits;
- allocation, mutation, aliasing, and ownership;
- error transport through status/results or exceptions;
- reference cases, property tests, adversarial cases, and accuracy bounds; and
- whether results depend on an external library, version, target, or floating
  environment.

Performance alone is not completion. A fast API with ambiguous numerical
semantics or an unstable host dependency remains experimental.

## 7. Runtime roadmap

### 7.1 Memory management and ownership

Strong, non-atomic ARC remains the 1.x baseline for strings, Array/List,
classes, interface carriers/boxes, and other reference-like values. Structs
remain value types whose lifecycle is composed from their fields. Parameters
are borrowed by default, owning copies retain, moves/returns transfer, and
owning locals are destroyed on normal exit.

The 1.x work is to make that model uniform:

- one canonical layout/lifecycle registry;
- complete Vector/Matrix ownership and shape-bearing descriptors;
- retain-before-release and cleanup correctness on all control-flow paths;
- clear cycle policy for reference classes;
- optional debug checks for over-release, leaked ownership, and invalid object
  headers;
- no unrestricted user-visible `malloc`/`free`; optional arenas, regions, and
  allocator-backed buffers remain research; and
- no promise that internal ARC operations or headers are ABI-visible.

### 7.2 Allocator

The current checked `malloc`/`free` behavior should move behind runtime
allocation functions. The first allocator contract should provide checked size
calculation, alignment, zero-size rules, allocation failure behavior, and
diagnostic counters in debug builds. A custom general-purpose allocator is not
a goal. Pluggable allocators, arenas, lexical regions, and allocator-backed
buffers are research areas to consider only when scientific workloads and
escape analysis provide evidence and the design cannot bypass lifecycle
safety.

### 7.3 GC strategy

No tracing GC is planned for 1.x. ARC's inability to collect cycles must be
documented, and language/library designs should avoid hidden cycles.

Before any future GC proposal, collect evidence for:

- real cyclic object graphs that cannot be redesigned;
- ARC overhead after retain/release optimization;
- concurrency requirements that make non-atomic ARC insufficient;
- pause-time and throughput requirements; and
- FFI/rooting implications.

Future optional tracing is not permanently ruled out. A collector would be a
major runtime/ABI decision and must not silently coexist with explicit
facilities or ARC as an unbounded hybrid.

### 7.4 Threading and synchronization

Threading is intentionally unavailable while ARC is non-atomic and no memory
model exists. A safe sequence is:

1. define data-race and memory-order semantics;
2. decide send/share rules for values and reference objects;
3. select atomic ARC, ownership transfer, isolation, or another proven model;
4. add runtime thread/TLS and panic behavior;
5. add mutex, condition, atomic, and channel primitives; and
6. only then evaluate async tasks and executors.

Threading APIs belong in an extended concurrency library over a small runtime
primitive set.

### 7.5 Diagnostics and panic handling

Native safety panics currently print a stable public message and terminate with
exit code 1 without unwinding Aether frames. Preserve this fail-fast contract
for unrecoverable invariant failures in 1.x.

Improve the runtime with:

- source locations and compact stack frames in debug artifacts;
- an allocation/lifecycle diagnostic mode;
- normalized OS/toolchain errors;
- deterministic panic formatting across supported targets;
- a strict separation between panic and catchable language exceptions; and
- no dependence on libc formatting for public semantics unless normalized.

Catchable exceptions, if promoted, require normal-path and exceptional-path
cleanup and cannot be implemented by catching the current process-terminating
panic. Their source semantics must remain independent of a specific platform
unwinding ABI; an implementation may use control-flow/status lowering,
platform tables, or another verified strategy while preserving the same
observable contract.

### 7.6 Portability

Separate three runtime layers:

- target-independent object/lifecycle primitives;
- target ABI/layout adaptation; and
- OS services for process arguments, paths, files, clocks, threads, and
  networking.

Use opaque handles at runtime boundaries. Do not expose current object headers,
field indices, mangled names, or LLVM aggregate calling conventions. Every
supported target requires sanitizer or equivalent memory checks, parity tests,
toolchain version bounds, and platform-specific failure injection.

## 8. Optimization roadmap

The current compiler already has constant folding, local/global constant
propagation, algebraic simplification, SCCP, dead store/code elimination, and
phi cleanup. The next steps depend more on sound analysis than on adding pass
names.

| Optimization family | Expected impact | Prerequisites and policy |
| --- | --- | --- |
| Inlining | **Very high** for small numerical functions and abstraction removal | Typed effect summaries, recursion/budget controls, debug provenance, code-size metrics, and post-pass verification. |
| Bounds-check elimination | **Very high** for loops over Array/List/Vector/Matrix | Range analysis, immutable length/shape facts, alias/mutation tracking, and proofs that preserve panic order. |
| Loop canonicalization and induction-variable optimization | **Very high** | Canonical loop IR/SSA, overflow-aware induction reasoning, and exact range-step semantics. |
| Vectorization | **Very high** for scientific kernels | Canonical layouts, alias/alignment facts, target features, reduction semantics, floating-point policy, and scalar fallback. Prefer LLVM vectorization before source SIMD. |
| ARC retain/release optimization | **High** | Ownership dataflow, escape facts, call summaries, exceptional-exit cleanup policy, and lifecycle verifier coverage. It may remove only provably redundant operations. |
| Escape analysis | **High** | Complete allocation/capture model and alias graph. Enables stack/arena placement and ARC reduction but must not change identity or lifetime. |
| Alias analysis | **High enabling value** | Canonical type/layout descriptors, reference/value semantics, borrowed markers, mutation summaries, and FFI conservatism. |
| LICM | **High** for numerical loops | Effect/alias analysis and trap-order rules. Loads, allocation, panics, IO, ARC, and mutable shapes cannot move without proof. |
| Devirtualization | **Medium to high** | Closed-world or exact-type facts for interfaces/classes, witness stability, and fallback dispatch. Avoid assumptions incompatible with separate packages. |
| GVN / common subexpression elimination | **Medium to high** | Typed value numbering, memory/effect SSA or equivalent, floating-point equivalence rules, and panic preservation. |
| Interprocedural constant propagation | **Medium** | Module graph, call graph, specialization budget, and separate-compilation policy. |
| Scalar replacement of aggregates | **Medium** | Escape/alias analysis and complete lifecycle reconstruction, especially for structs containing reference fields. |
| Strength reduction and reassociation | **Medium** | Checked integer overflow and conservative IEEE floating rules. Fast-math must never be implicit. |
| Dead call/allocation elimination | **Medium** | Precise purity, allocation observability, panic, lifecycle, and FFI summaries. Calls remain effectful by default. |

Optimization rollout rules:

1. define the transformation's semantic preconditions;
2. implement analysis separately from rewriting where practical;
3. verify IR/SSA after the pass;
4. add differential, randomized, boundary, and reduction tests;
5. measure representative programs and code size;
6. enable in an experimental profile first; and
7. promote only with zero known semantic divergence.

`-O0`, `-O1`, and `-O2` promise equivalent language behavior, not identical
panic timing when the specification leaves timing unobservable, identical
floating instruction sequences, or guaranteed speedups.

## 9. Tooling roadmap

### 9.1 Essential

| Tool | Essential direction |
| --- | --- |
| LSP | Replace document-local/regex-heavy discovery with compiler-owned workspace indexing. Preserve frontend diagnostics and add robust cross-file definition/references, rename, import completion, semantic tokens, code actions, cancellation, incremental invalidation, and capability-profile diagnostics. |
| IDE plugins | Keep VS Code and IntelliJ thin clients of the shared LSP/CLI. Publish only after executable discovery, version compatibility, native/AST labeling, platform packaging, and integration tests are reliable. Do not duplicate parser/type semantics in plugins. |
| Formatter | Define canonical formatting for stable syntax, require idempotence and comment preservation, expose the same engine through CLI and LSP, and treat formatting changes as reviewed compatibility events. |
| Testing tools | Add a distributed `testing` module and `aether test` runner with discovery, assertions, fixtures/lifecycle, filtering, deterministic exit status, and native execution. Compiler tests remain separate from user testing APIs. |
| Package/build tooling | Define project manifest, source roots, module identity, dependency constraints, lockfile, offline cache, build profiles, and reproducible source builds. A public registry is not required for the first useful package workflow. |

### 9.2 Nice to have

| Tool | Direction |
| --- | --- |
| Documentation generator | Generate API pages from typed declarations and doc comments, resolve links through the workspace index, record required language/profile versions, and support static output. |
| Debugger | Emit DWARF or platform-equivalent source locations and integrate initially with existing debuggers. A custom debugger should not precede correct debug metadata and runtime frames. |
| Profiler | Provide symbol/source maps and allocation/ARC counters compatible with existing system profilers before building a custom UI. |
| Benchmarking tools | Add machine-readable results, environment capture, warm-up/noise policy, statistical comparison, code-size metrics, and stored baselines. Keep correctness tests independent. |
| REPL | Improve multiline input and workspace imports while keeping its AST-only status explicit until compiled state and lifecycle can be defined honestly. |

### 9.3 Long-term

- a signed, indexed public package registry with provenance and yanking policy;
- package vulnerability/advisory tooling;
- richer source debugger support for Aether values, interfaces, and async tasks
  if async ever exists;
- integrated CPU, allocation, ARC, and numerical-kernel profiling;
- automated migration tooling between major language editions; and
- remote/cross build orchestration after the local target model is stable.

## 10. Platform roadmap

### 10.1 Target priorities

| Platform | Priority | Intended support |
| --- | --- | --- |
| Linux x86_64 | **Primary / current** | Stable 1.0 baseline. Continue clang-based native builds, broaden distro/libc evidence, and make toolchain bounds explicit. |
| Linux ARM64 | **High** | First architecture expansion because it exercises pointer/layout assumptions and serves modern servers and developer hardware without changing the OS boundary. |
| macOS ARM64 | **High** | Primary macOS target. Requires Mach-O toolchain validation, path/file durability semantics, deployment target policy, and runtime packaging. |
| Windows x86_64 | **High** | Required mainstream platform after OS abstractions exist. Requires UTF-16 arguments/paths, Windows file replacement/durability, process/error mapping, COFF/debug info, and MSVC/clang-cl ABI policy. |
| macOS x86_64 | **Medium / compatibility** | Support only while demand and CI availability justify it; do not let an aging architecture define new ABI design. |
| WebAssembly/WASI | **Long-term research** | Start with WASI command-line programs, not browsers. Requires a distinct filesystem/process/panic/thread capability profile and a linker/runtime plan. Browser APIs belong in packages. |

Android, iOS, 32-bit architectures, embedded bare metal, and GPUs are not
current platform commitments.

### 10.2 Platform assumptions

- Source semantics should be target-independent except where a capability is
  explicitly platform-specific.
- `int` remains checked signed i32 and `double` remains IEEE binary64 across
  targets.
- Pointer size, aggregate layout, calling convention, path encoding, errno/OS
  errors, atomic file replacement, and toolchain object format are
  target-dependent.
- Endianness is not currently a user-visible assumption; serialization formats
  must define byte order explicitly.
- Native builds may initially require a system LLVM/clang-compatible toolchain,
  but installation must report the exact missing/incompatible component.

### 10.3 ABI implications

Before the second stable native target:

1. emit and validate `target triple` and `target datalayout`;
2. specify scalar, aggregate, nullable, interface, and callback calling rules;
3. replace exposed internal headers with opaque runtime handles/accessors;
4. version runtime and FFI symbols;
5. decide per-target object compatibility and minimum toolchain versions;
6. test struct padding, bool representation, enum discriminants, alignment,
   varargs exclusion, and ownership across the boundary; and
7. require source rebuild when ABI compatibility is not promised.

Cross-platform source compatibility does not imply that one binary or object
file runs or links everywhere.

## 11. Standard library roadmap

### 11.1 Library tiers

- **Core library:** ships and versions with the compiler. It is small,
  portable, required for ordinary programs, and subject to the strongest 1.x
  compatibility policy.
- **Extended library:** maintained by the Aether project but can release and
  depend separately. It contains larger algorithms, OS-sensitive APIs, and
  scientific domains.
- **External ecosystem:** independently evolving packages and bindings,
  especially where dependencies, hardware, protocols, or domain breadth would
  burden the language distribution.

### 11.2 Area placement

| Area | Core library | Extended library | External ecosystem |
| --- | --- | --- | --- |
| Collections | `Array`, `List`, ranges used by control flow, basic algorithms, equality, copy/slice, and iteration over built-in containers. | `Map`, `Set`, `Queue`, `Stack`, heaps, specialized containers after hashing/generic design. | Persistent, concurrent, domain-specific, database, and distributed collections. |
| Strings/text | Immutable UTF-8 string, byte length, equality, concatenation, trim/split/parsing, formatting primitives with stable rules. | Unicode normalization, graphemes, regex, codecs, builders, locale-aware operations. | Large text processing, natural-language, templating, and document formats. |
| Math | Checked scalar operations, real scalar functions/constants, numeric traits internal to approved types. | Special functions, numerical methods, complex library if generics/operators support it. | Symbolic algebra, arbitrary precision, specialized scientific domains. |
| Linear algebra | Vector/Matrix core representation and small shape-safe operations needed by the language profile. | `math.linalg` algorithms and stable BLAS/LAPACK-backed dense operations. | Sparse/distributed matrices, vendor kernels, domain packages, GPU tensors. |
| Statistics | Minimal reduction primitives shared with math. | Descriptive statistics, distributions selected by evidence, online algorithms, sampling. | Inference frameworks, data frames, econometrics, probabilistic programming. |
| Files | Paths, UTF-8 text read/write/append/atomic operations, normalized statuses needed by ordinary programs. | Binary IO, buffered streams, directories, metadata, watching, temporary files, archives. | Virtual filesystems, cloud/object storage, database/storage engines. |
| Networking | No mandatory 1.0 surface. A minimal portable socket/URL foundation may enter core only when platform behavior is normalized. | HTTP client/server primitives, TLS adapters, DNS, async integration if available. | Protocol frameworks, RPC, web stacks, cloud SDKs. |
| Concurrency | No 1.0 surface. Small thread/atomic primitives only after a memory model exists. | Channels, pools, synchronization utilities, task runtime. | Distributed runtimes and specialized schedulers. |
| Serialization | Stable manual byte/text primitives and explicit status types. No reflection dependency. | JSON/CSV and schema-driven formats with explicit versioning and limits. | Protobuf/MessagePack/domain schemas, databases, migrations, object mappers. |
| Random | A stable reproducible PRNG interface, explicit seed/state, and basic uniform sampling. | Distributions, quasi-random sequences, parallel streams, statistical tests. | Cryptographic providers, hardware RNG integration, specialized simulation packages. |
| Date/time | Minimal monotonic/system clocks only if needed by core tooling. | Calendar, duration, timezone database integration, formatting/parsing. | Domain calendars, scheduling frameworks, time-series databases. |
| Testing | Assertions, test declaration/discovery, deterministic runner contract, temporary resources, and basic property hooks. | Property testing, fuzz adapters, snapshots, mocks, benchmark integration. | Domain test frameworks, distributed test services, hardware labs. |

### 11.3 Standard library design rules

- Prefer Aether source over compiler builtins when performance and safety are
  adequate.
- Intrinsics require representation, safety, or essential optimization
  justification.
- Core APIs must work on every stable target or expose a compile-time
  capability distinction.
- External dependencies must be explicit and versioned; the core library must
  not silently load Python scientific packages.
- Stable APIs specify complexity where users depend on it.
- Random, numerical, text, and serialization APIs specify reproducibility and
  locale/encoding behavior.
- Experimental modules use an explicit namespace or package channel and do not
  acquire 1.x stability accidentally.

## 12. Governance

### 12.1 Versioning

- Use Semantic Versioning for the language and distribution.
- Keep capability profile, diagnostic contract, IR protocol/schema, runtime
  ABI, and public FFI ABI as distinct versioned domains.
- Publish a compatibility table in every release.
- Treat a capability-profile bump as an auditable change to the native
  boundary, not as a substitute for release notes.

### 12.2 Release cadence

Use a quality-gated release train rather than date promises:

- patch releases on demand for correctness, security, documentation, and
  packaging fixes that preserve behavior;
- minor releases after their additive capability set, migration impact, and
  target matrix satisfy the full gate;
- RCs only when all planned features are complete and frozen;
- major releases only for approved incompatibilities that cannot reasonably be
  delivered additively.

Regularity is desirable, but an incomplete backend or undocumented semantic
change must not be shipped to satisfy cadence.

### 12.3 Documentation policy

Authority order:

1. language specification and stable library reference;
2. native capability profile and supported-platform profile;
3. public diagnostics and ABI/FFI contracts;
4. release notes;
5. generated feature matrices;
6. implementation/design documents;
7. dated audits and historical notes.

Every document must declare its class and last validated release/profile.
Historical documents are explicitly non-normative evidence, not competing
statements of the current profile; visible classification/version banners keep
that boundary clear. Generated tables must be checked in CI. A feature cannot
be stable unless syntax, semantics, limits, platforms, and examples are
documented together.

### 12.4 Deprecation and compatibility policy

- Deprecations need a diagnostic code, reason, replacement, migration example,
  and first/last supported version.
- Stable 1.x source features are not removed in 1.x.
- A deprecated API remains functional for at least two minor releases and
  normally until the next major.
- Security fixes may accelerate removal, but require a dedicated advisory and
  the safest available migration.
- Bug compatibility is not guaranteed when behavior contradicts the spec,
  violates safety, or causes miscompilation; corrections require explicit
  notes and regression cases.
- Diagnostic wording, optimizer output, performance, and internal IR/ABI are
  not stable unless separately declared.

### 12.5 Contribution workflow

1. Start with a minimal problem statement and real Aether program.
2. For public syntax, semantics, runtime ABI, standard-library core, or
   compatibility changes, write an RFC with alternatives and migration impact.
3. Update the capability model before enabling backend behavior.
4. Implement all applicable stages; do not merge frontend-only stable claims.
5. Add positive, negative, boundary, safety, optimizer, parity, and platform
   tests.
6. Update specification/profile/diagnostics/library documentation and examples.
7. Run local CI, Cargo checks where applicable, editor/tooling checks for
   affected contracts, and release-artifact smoke tests.
8. Dogfood meaningful features in a complete program.
9. Require review from the owners of language semantics and the affected
   compiler/runtime/tooling area.
10. Record compatibility and release-note impact before promotion.

Small internal refactors do not need an RFC, but they still preserve the same
verification and regression gates.

## 13. Risk assessment

| Risk | Consequence | Mitigation |
| --- | --- | --- |
| Compiler complexity and duplicated semantics | Frontend, IR, SSA, LLVM, runtime, and tools disagree; fixes multiply. | Canonical typed metadata, generated capability data, structural operand/effect visitors, removal of legacy paths, and explicit ownership of each invariant. |
| Runtime growth | Every library operation becomes an intrinsic/helper, making portability and ABI stability unmanageable. | Enforce the builtin/runtime/stdlib boundary; require representation or safety justification; move algorithms to Aether source or packages. |
| Platform portability | Host-dependent paths, file semantics, aggregate layout, and toolchain behavior cause silent divergence. | Explicit targets/data layouts, OS abstraction, per-target capability profiles, cross-platform CI, failure injection, and no unsupported claims. |
| Optimization correctness | Miscompilation changes panics, NaN behavior, mutation, allocation, or lifecycle. | Sound effect/alias/ownership analyses, verifier after every pass, differential/random testing, pass bisection, and staged opt-in profiles. |
| Ownership/lifecycle defects | Leaks, double frees, use-after-free, cycle leaks, or unsafe concurrency. | Canonical lifecycle IR, Rust runtime boundary where useful, sanitizers, debug ARC counters, property tests, and no threading before a memory model. |
| ABI ossification | Provisional layouts become depended on before they can support targets or FFI. | Keep current ABI explicitly internal, use opaque handles, version the first public ABI, test layout/calling conventions, and rebuild from source by default. |
| Documentation drift | Users rely on historical claims and tooling exposes the wrong profile. | Authority hierarchy, document banners, generated matrices, release/profile stamps, link checking, and CI consistency tests. |
| Testing scalability | A broad suite becomes slow, flaky, or skips the paths that matter. | Capability-indexed shards, deterministic fixtures, required clang/target jobs, test impact metadata, nightly fuzz/sanitizer/soak runs, and retained minimal reproducers. |
| Python/Rust verifier divergence | Two authorities accept different IR or report incompatible diagnostics. | Keep one explicit authority, mandatory shadow comparison during transition, versioned protocol, deterministic corpus, fail-closed canary, and configuration-only rollback. |
| Scientific semantic drift | NumPy/SciPy host behavior becomes an undocumented language promise. | Define Aether numeric contracts, isolate host-backed experiments, use explicit external adapters, and test independent reference cases. |
| Ecosystem fragmentation | IDEs, formatter, package tools, and libraries reimplement parsing or module rules. | Shared compiler workspace service and LSP, thin editor clients, one module resolver, and version negotiation. |
| Performance pressure | Premature SIMD, GPU, JIT, allocator, or unsafe shortcuts destabilize semantics. | Baselines, profiling, representative dogfood, external optimized libraries, and evidence-gated research proposals. |
| Release supply chain | Unsigned, irreproducible, or host-contaminated artifacts undermine trust. | Locked dependencies, provenance/manifest, checksums and later signing, clean builders, artifact content checks, reproducibility work, and staged publication. |

## 14. Long-term prioritized roadmap

### 14.1 Near-term

1. **Finish stable 1.0 qualification.** Re-run all profile-23, parity,
   optimizer, clean-install, documentation, and supported-platform gates with
   no accepted-program backend failures. This turns the current RC architecture
   into a defensible baseline.
2. **Maintain documentation authority.** Preserve explicit non-normative
   classification for historical compiler matrices and generate current
   feature summaries from the capability source. Users must be able to
   identify the current truth without reconstructing history.
3. **Decide Rust Initial IR verifier authority by evidence.** Complete the
   predeclared canary window and three-platform operational checks; either
   promote deliberately or retain Python authority. Indefinite ambiguous
   dual-authority status is a maintenance risk.
4. **Specify explicit targets and toolchain bounds.** Add target triple/data
   layout and make Linux x86_64 assumptions executable. This is a prerequisite
   for every portability and ABI step.
5. **Canonicalize type layout and lifecycle metadata.** Remove repeated field
   indices/layout decisions from compiler/runtime layers before they become a
   public boundary.
6. **Ship a minimal testing workflow.** The language needs native tests and
   assertions to grow its own stdlib and packages without using Python pytest
   as the user model.
7. **Make optimization profiles truthful.** Document and connect distinct pass
   pipelines or stop presenting `O2` as stronger than `O1`.

### 14.2 Medium-term

1. **Complete module initialization.** Globals/constants/top-level module state
   are the largest remaining gap in the general-purpose module model.
2. **Extract a versioned internal runtime boundary.** Opaque handles and a
   tested runtime ABI unlock sanitizer coverage, smaller outputs, portability,
   and eventual FFI.
3. **Introduce minimal C FFI.** This unlocks BLAS/LAPACK and system libraries
   without forcing scientific dependencies into the compiler.
4. **Add Linux ARM64 and macOS ARM64, then Windows x86_64.** Port in an order
   that separately exposes architecture and OS assumptions.
5. **Build workspace-grade LSP and canonical formatting.** Real multi-module
   projects require consistent navigation, rename, capability diagnostics, and
   formatting.
6. **Define source package manifests and lockfiles.** Enable reproducible local
   dependencies before building a registry or promising binary packages.
7. **Move numerical methods and stable linear algebra APIs into Aether
   libraries.** Use dogfood to validate callables, modules, results, ownership,
   and FFI.
8. **Promote basic native exceptions only if cleanup is complete.** Do not let
   source syntax force any specific or unsafe platform unwinding ABI.

### 14.3 Long-term

1. **Develop sound interprocedural optimization.** Effects, aliasing, escape
   analysis, inlining, ARC elimination, bounds elimination, LICM, and
   vectorization provide the largest performance path for scientific code.
2. **Stabilize an extended standard library.** Collections, text, paths,
   random, date/time, statistics, linear algebra, and testing should grow at
   the library layer with clear dependency weight.
3. **Add source debugging and profiler integration.** Native programs need
   source locations and observable allocation/ARC behavior before the language
   can support larger applications comfortably.
4. **Establish a governed package ecosystem.** Add publishing, provenance,
   signing, advisories, and a registry only after source package semantics are
   stable.
5. **Evaluate public iterators and generics for late 1.x or 2.0.** Keep
   internal iteration unification separate, and use stdlib experience to decide
   whether limited additive designs fit 1.x or deeper models justify 2.0.
6. **Evaluate WASI.** A portable command-line profile is the most constrained
   path to WebAssembly and should precede browser-specific APIs.

### 14.4 Future research

- payload enums, algebraic data types, and full exhaustive pattern matching;
- user-defined generics and constraint/interface interaction beyond any
  limited late-1.x subset;
- captured closures, callable returns, and environment ownership;
- a concurrency memory model, thread-safe ownership, structured concurrency,
  and async;
- portable SIMD and automatic vectorization quality;
- GPU/offload package interfaces and memory transfer semantics;
- restricted deterministic compile-time evaluation;
- arenas, lexical regions, allocator-backed buffers, and scoped explicit
  memory facilities;
- cycle management or optional tracing GC if measurements justify it;
- incremental/parallel compilation and stable module cache formats;
- link-time optimization and whole-package devirtualization; and
- WASI/browser capability separation.

Research items become roadmap commitments only after an RFC, prototype,
measured use case, compatibility analysis, and end-to-end implementation plan.

## 15. Success criteria

Milestones are capability gates, not dates.

### 15.1 Alpha

An Aether Alpha milestone is achieved when:

- the intended language subset has a written draft specification;
- every accepted feature is labeled by backend stage and unsupported forms
  fail explicitly;
- source can pass lexer, parser, typechecker, and at least one execution path;
- deterministic positive and negative tests cover every advertised feature;
- crashes and host exceptions are converted to classified compiler
  diagnostics at public boundaries; and
- artifacts identify their version and experimental platform assumptions.

### 15.2 Beta

An Aether Beta milestone is achieved when:

- the proposed stable language feature set and native capability profile are
  frozen and exhaustive;
- every admitted capability has applicable frontend, IR, verifier, SSA,
  optimizer, LLVM/runtime, and native tests;
- all excluded frontend experiments fail at the capability gate before
  lowering;
- at least two multi-module dogfood programs—one scientific and one
  general-purpose—pass AST/native observable parity;
- the full supported-target suite has zero known critical correctness,
  memory-safety, or miscompilation defects;
- normative specification, diagnostics, platform, and release documents pass
  automated consistency checks; and
- clean-install artifacts run without a source checkout.

### 15.3 Stable 1.0

Aether 1.0 is achieved when:

- all RC-frozen language/profile requirements pass without waiver on Linux
  x86_64 and the documented clang range;
- every conforming example and differential case passes native compilation at
  each promised optimization level with matching specified stdout, stderr,
  exit code, panic, and file results;
- no stable-profile program accepted by the gate is known to fail in lowering,
  verification, code generation, clang, or runtime;
- there are zero open critical/high correctness or memory-safety defects in
  the stable profile;
- the Python/Rust Initial IR authority decision is explicit, tested, and has a
  documented rollback or retirement path;
- wheel and sdist content validation, clean-environment install, native smoke,
  manifest, and checksum verification all pass from a clean revision;
- the release declares exact source compatibility, ABI non-guarantees,
  supported targets, dependencies, and reproducibility status; and
- historical documents are explicitly classified as non-normative and current
  release documents identify the specification/profile authorities.

### 15.4 Stable 1.1

Aether 1.1 is achieved when:

- the complete 1.0 conformance and dogfood corpus compiles and preserves
  behavior without source changes;
- at least one additive 1.x capability is promoted through every applicable
  stage and recorded by a new capability profile;
- a supported `aether test` workflow and core testing module run user tests
  natively;
- canonical formatting is available through CLI and LSP with idempotence and
  comment-preservation tests;
- module/package dependency behavior is documented sufficiently for
  reproducible multi-module source builds; and
- no 1.0 stable API or syntax is removed.

Module initialization, minimal C FFI, or a second target may qualify as the
additive capability, but none should be declared complete without its own
end-to-end gate.

### 15.5 Stable 2.0

Aether 2.0 is achieved when:

- every intentional 1.x incompatibility has an accepted RFC, release-note
  entry, diagnostic, and migration path;
- the full 1.x conformance corpus is mechanically classified as unchanged,
  migrated, deliberately rejected, or corrected, with no unexamined cases;
- at least one major-version capability that could not safely fit 1.x is
  implemented end-to-end and demonstrates its need in a complete program;
- source, package, runtime ABI, FFI ABI, and target compatibility domains are
  separately versioned and documented;
- all supported targets pass the same language conformance requirements, with
  platform-specific capability differences declared explicitly;
- optimization and memory-management changes retain differential, sanitizer,
  and verifier evidence; and
- the stable vision principles in this document remain intact.

2.0 is not successful merely because it contains more syntax. It is successful
when a justified major capability is delivered without losing the
correctness, transparency, mathematical coherence, and general-purpose
foundation established by 1.x.
