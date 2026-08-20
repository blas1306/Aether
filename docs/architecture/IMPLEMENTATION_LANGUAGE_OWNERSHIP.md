# ARCH-1: implementation language ownership and self-hosting boundaries

Status: **Accepted** (2026-08-18). This document and its companion
`implementation_language_ownership.json` are normative. Earlier migration
documents remain historical evidence; where they differ on future ownership,
this decision governs. This milestone changes no compiler behavior, ABI,
optimization profile, or implementation authority.

## Decision in one sentence

Aether adopts **one canonical implementation per responsibility**: Rust is the
long-term compiler core and preferred runtime implementation, a generated C ABI
is the stable native boundary, C++ is dependency-adapter-only, Python remains
development tooling but leaves the distributed production path, and Aether
owns high-level libraries and selected tools without duplicating core semantic
authorities.

A duplicate is permitted only by a written migration contract naming the
authority, shadow/oracle, parity corpus and criteria, promotion gate, rollback,
and retirement condition. It must have an owner and bounded retirement window.
Two indefinite authorities are forbidden. Similar operations in different
layers are not duplicate authority when their contracts differ: for example, a
runtime bounds trap, an optimizer bounds-check proof, and a public checked-index
API have distinct responsibilities.

## Repository audit (current fact)

### Python

`src/aether` is the production implementation. It owns the lexer, parser and
AST; symbols, scopes, modules, name resolution and typechecking; Initial IR and
lowering; CFG; SSA model, construction, verification and analyses; O0/O1/O2
optimization; LLVM text generation/backend orchestration; diagnostics, CLI,
interpreter, language service and source formatter. Backend modules generate
embedded LLVM runtime helpers for strings, arrays, lists, classes, exceptions,
I/O, scalar math, vectors and matrices and declare libc/OS functions such as
allocation and file operations. Python also owns packaging, release/audit
scripts, benchmark analysis, test orchestration, and the Rust verifier client,
shadow coordinator, canary and packaging tools. The wheel currently requires
Python 3.11 plus NumPy, SciPy, SymPy and Matplotlib.

### Rust

`compiler-rs` is an isolated workspace, not a second production compiler.

| Crate | Actual responsibility |
| --- | --- |
| `aether-ir` | Owned Rust Initial IR, schema-v1 import, JSON/wire DTOs, including the SSA wire representation. |
| `aether-verifier` | Combined and focused structure, type, CFG, dominance, SSA, lifecycle/borrow, and all-path-return verification over owned Rust IR. Its Initial IR verifier owns production authority. |
| `aether-ir-verifier` | Protocol-v1 library and bounded stdin/stdout executable that imports schema-v1 IR and invokes the combined verifier. |
| `aether-python` | Empty future integration seam; no PyO3 binding or production integration exists. |

Python↔Rust differential tests, a shadow coordinator, content-identified
platform packaging, operational CI, soak tooling and an explicit fail-closed
Rust-authority canary exist. The checked-in production/default dual-verifier
policy is Rust authority with required Python shadow. Therefore Initial IR
verification is **RP3**. Initial IR and
SSA Rust representations/verifiers are RP1 infrastructure where they are not
on the production authority path.

### C, C++, and Aether

There is no checked-in production C runtime. Runtime code is currently emitted
as LLVM by Python and calls C-compatible libc/OS symbols. The native ABI and
object layouts are documented/compiler-owned concepts, not a generated public
C header. Native numerical behavior currently reaches Python dependencies;
there is no established BLAS/LAPACK C ABI in Aether. The only repository-owned
`.c` found is a numerical example; C snippets in tests are fixtures. There is
no repository-owned core C++ implementation or required C++ library adapter.
Vendored/tool dependencies do not establish Aether ownership.

Aether source currently comprises examples, exception corpora, benchmarks and
tests, including numerical methods, linear algebra demonstrations, collections,
classes, expense tracking and algorithms. There is not yet a canonical
self-hosted stdlib/compiler/tool implementation. These programs demonstrate
expressiveness and are dogfooding assets, not infrastructure authority.

## Normative target architecture

```text
 Aether high-level layer
 stdlib / tests / formatter / later tools / optional parser
                       | versioned schema, generated binding, or CLI
                       v
 Rust compiler core
 frontend bootstrap / typed IR / verification / SSA / analyses / optimizer
 diagnostics / driver / LLVM orchestration
                       |
                       v
                     LLVM

 Aether or generated native code
             | stable generated C ABI
             v
 Rust runtime + exceptional small C portability shims
             | C ABI
             v
 OS / libc / BLAS / LAPACK / native libraries
             ^
             | extern "C" shim only when unavoidable
        isolated C++ dependency

 Python: repository automation, experiments, analysis and migration oracles;
         absent from the eventual production distribution execution path.
```

## Language policies

### Rust

| Responsibility | Classification | Reason |
| --- | --- | --- |
| IR model, verifier, CFG, dominance, SSA construction/verifier | `RUST_CANONICAL` | Shared semantic invariants need one safe, fast owned representation; substantial verifier infrastructure already exists. |
| Analyses and optimizer | `RUST_CANONICAL` | Tight graph/IR integration, performance and correctness outweigh self-hosting value. |
| Typechecking internals | `RUST_CANONICAL` | It defines language semantics and must not diverge from bootstrap. |
| Diagnostics infrastructure and serialization/protocol | `RUST_CANONICAL` | Stable identities/schemas and all compiler phases need them. Rendering may be Aether. |
| LLVM lowering/backend orchestration | `RUST_CANONICAL` | Native APIs, platform/toolchain handling and performance belong beside the core. |
| Compiler driver internals | `RUST_LIKELY` | Enables a Python-free distribution; high-level project orchestration may self-host separately. |
| Lexer, parser, AST, resolver and lowering | `RUST_LIKELY` | Rust is the reliable Stage0 owner; parser/AST may later gain a measured self-host implementation. Resolver/lowering remain core unless a later ADR proves benefit. |
| LSP | `RUST_LIKELY` | It consumes incremental semantic data and benefits from the core, while JSON-RPC keeps editor clients separate. |
| High-level stdlib/tools | `NOT_RUST` by default | These are useful Aether dogfooding surfaces. Rust remains valid where compiler-internal access or performance requires it. |
| Experimental prototypes | `RUST_OPTIONAL` | Choice is local; prototypes acquire no authority without promotion. |

This does not require moving every frontend piece forever. The intended model
is Python → Rust Stage0, then optionally Rust bootstrap/reference parser plus a
qualified Aether parser. Typechecking, semantic lowering and optimizer remain
canonical Rust even in a substantially self-hosted system.

### C and runtime

**C denotes an ABI, not necessarily an implementation language.** Its role is
stable FFI headers, opaque handles and low-level entry points to the OS/libc,
allocators, BLAS/LAPACK, plugins and native extensions. It is not a compiler
implementation language.

Runtime options were compared as follows:

| Option | Strength | Cost |
| --- | --- | --- |
| C implementation + C ABI | Small, universal toolchain and excellent portability/debugger/sanitizer support | Manual ownership safety and more risky growth. |
| Rust implementation + C ABI | Memory safety, good sanitizers, typed ownership and natural compiler integration | Rust bootstrap/toolchain, panic containment and possibly larger binaries. |
| Rust plus small C adaptation | Retains safety for ownership-heavy logic and permits exceptional platform shims | Two build languages and a seam to govern. |

The primary choice is **Rust implementation + generated C ABI**, with small C
portability/adaptation files allowed only when platform evidence justifies
them. Static linking, size measurement, symbols and supported-target packaging
are release gates. BLAS/LAPACK interoperability is through their stable C or
provider ABI; Aether must not reimplement kernels merely to avoid native code.
The first C milestone is exactly **a runtime ABI architecture audit and
canonical schema design**, covering String and Array handles first; it does not
yet create the runtime or change the ABI.

A native C dependency requires a supported license, stable ABI, target/platform
and packaging plan, ownership/error/callback contract and reproducible version
policy. Bindings must state buffer shape/stride, mutability, lifetime and who
allocates/frees.

### C++

C++ is `DEPENDENCY_ADAPTER_ONLY`, not core and not an optional general runtime
language. It is admitted only when no viable C API exists, the dependency adds
material value, its toolchain can be packaged, and a narrow adapter can safely
translate ownership and errors. The invariant is:

```text
Aether <-> C ABI <-> extern "C" C++ shim <-> C++ library
```

No mangled names, STL types, templates, compiler-specific object layout or C++
exceptions cross the Aether ABI. The shim catches all exceptions, destroys C++
objects on its side and returns a documented status/error payload. There is
**NO_CURRENT_CPP_MILESTONE** because the repository has no qualifying need.

### Python

`PYTHON_PERMANENT_TOOLING` includes release/repository automation, benchmark
and evidence analysis, test orchestration, one-off generators and experimental
prototypes. `PYTHON_TRANSITIONAL` includes the production compiler, Initial IR
authority/oracle, shadow comparison and current packaging/integration path.
`PYTHON_TO_RETIRE` includes lexer/parser/typechecker, IR/SSA, verifier,
performance-sensitive analyses/optimizer, LLVM backend and driver from the
production path after their individual promotions. Tooling may continue to use
arbitrary pinned Python dependencies; build dependencies must be declared and
reproducible; eventual core release/runtime packages may not require Python or
arbitrary Python libraries.

The target is final state **B**: development uses Python, but the distributed
compiler and runtime do not require it. Python is not required to disappear
from the repository.

## Self-hosting policy

Self-hosting means selected production responsibilities are implemented in
Aether through a documented Stage0 path; it does not mean 100% Aether code.

| Level | Definition |
| --- | --- |
| SH0 | Aether compiles user programs only. Current infrastructure is here. |
| SH1 | Substantial high-level stdlib and tests are Aether. |
| SH2 | User-facing tools such as formatter/linter/package tools are Aether. |
| SH3 | Lexer/parser or another frontend portion is Aether, with Rust Stage0 reference/bootstrap. |
| SH4 | Selected non-authoritative compiler services/analyses are Aether. Core semantics need a separate authority ADR. |
| SH5 | A substantial primary compiler implementation can compile its own Aether components. |
| SH6 | Source-buildable Rust Stage0 builds Stage1; Stage1 builds Stage2; defined reproducibility or semantic-equivalence gates pass. |

Every self-host candidate needs language/stdlib expressiveness, acceptable
performance, a non-circular bootstrap path, differential or golden tests and a
concrete maintenance/dogfooding benefit. A component may only use the
documented bootstrap language subset supported by Stage0. A clean checkout
must never require an undocumented preinstalled Aether binary.

Stage0 is the source-buildable/distributed Rust compiler. It compiles Aether
self-hosted sources into Stage1. Later Stage1 builds the same sources into
Stage2; reproducible bytes where feasible, otherwise normalized IR/behavioral
equivalence, are an SH6 gate. Bootstrap artifacts must be versioned,
content-identified and reproducibly regenerable from source.

### Candidate matrix

| Candidate | Proposed language | Suitability / timeframe | Prerequisites | Bootstrap risk and reason |
| --- | --- | --- | --- | --- |
| Math, numerical methods, collection/text algorithms | Aether | High / early | Stable stdlib modules, generics/collections as needed, tests | Low; ideal dogfooding above primitives. |
| LinearAlgebra high-level | Aether | High / early-medium | Dense buffers, shapes, error API, native binding | Low; orchestration belongs in Aether, kernels do not. |
| Formatter | Aether | High / **first serious target** | Stable parser/syntax protocol, String, collections, file I/O, golden/idempotence corpus | Low-medium; deterministic and semantically non-authoritative. |
| Linter | Aether | High / medium | Stable syntax plus read-only semantic query API | Medium; must consume type/verifier results, never duplicate them. |
| Test helpers/corpus/bench workloads | Aether | High / early | Assertions, timing and process APIs where needed | Low; early dogfooding. Runner/evidence analysis may stay Python/Rust. |
| Benchmark harness | Aether + Python analysis | Medium / medium | Clock, subprocess, artifact format | Low-medium; measurement in Aether, statistical reporting may stay Python. |
| Package manager | Aether | Medium / late | Filesystem, HTTP, TLS, hashing, config, solver, subprocess | Medium-high; useful but broad bootstrap surface. |
| Build orchestration | Aether | Medium / late | Graphs, incremental metadata, config, compiler CLI | Medium; invokes Rust core rather than embedding it. |
| Lexer/parser | Rust then optional Aether | Medium / late | Frozen syntax schema, diagnostics, differential corpus, Stage0 | High; divergence/circularity require shadow promotion. |
| Typechecker | Rust | Low / not planned | N/A | Very high semantic risk; remain canonical Rust. |
| Diagnostics formatting | Aether optional | Medium / medium-late | Versioned diagnostic records/localization | Medium; identities/origins remain Rust. |
| IR/SSA verifier, analyses, optimizer | Rust | Low / not planned | N/A | High correctness/performance coupling; no self-host benefit now. |
| LLVM lowering | Rust | Low / not planned | N/A | High native/toolchain coupling. |
| Runtime high-level utilities | Aether | Medium / later | Stable runtime primitives | Medium; safe above ABI. |
| Allocator, ARC, String/collection storage, exceptions, threads/atomics | Rust + C ABI | Low / not initially | ABI schema, sanitizer and platform qualification | Critical bootstrap/ownership boundary. |
| FFI declarations/wrappers | Generated + Aether façade | High / medium | Canonical ABI schema/generator | Low if generated; manual four-way structs are forbidden. |

The formatter is the one first serious self-host milestone. Its gate is a stable
read-only syntax representation (preferably generated from a versioned schema),
adequate String/collection/file APIs, a Rust/Python oracle during migration,
idempotence and golden-corpus parity, and an explicit retirement date for the
Python formatter after promotion. Parser/compiler-core self-hosting is not the
first target.

The stdlib split is high-level algorithm versus primitive. Math composition,
statistics, numerical methods, collection/text algorithms, data structures,
parsing helpers and filesystem convenience APIs should preferentially be
Aether. Allocation, syscalls, atomics and optimized native kernels remain below
the C ABI. Linear algebra specifically is:

```text
Aether API, validation, result types and algorithm composition
        -> generated C-compatible numerical binding
        -> Rust layout/ownership adapter when necessary
        -> external BLAS/LAPACK provider
```

Efficient algorithms expressible in Aether stay in Aether; only measured
kernels cross the native boundary.

## Boundaries, data, errors and ownership

Use in-process Rust APIs inside the compiler core. Use versioned wire schemas
for migration/shadow processes and for self-hosted tools that benefit from
decoupling (`Compiler.Syntax`, diagnostics, selected read-only semantic facts).
Use generated Aether bindings over opaque C handles at runtime/native FFI. Use
CLI/JSON artifacts between build/package orchestration and the compiler. Do not
expose Rust object layout directly or make self-hosted tools import unstable
`Compiler.IR` by default. A narrow versioned `Compiler.AST`/syntax schema is
acceptable; raw mutable IR is not. Generated bindings are preferable to four
hand-maintained declarations.

A future canonical ABI schema—not Rust, C, C++ or Aether copies—owns String,
Array, List, class/interface references, exceptions and native-buffer ABI
definitions. It generates Rust declarations, C headers, Aether `extern`
declarations and any C++ shim declarations. Until that milestone, current
compiler/backend documents remain descriptive authority and no new public ABI
is implied by this ADR.

Every pointer/buffer parameter and return is classified as borrowed,
transferred, retained/shared, caller-owned or callee-owned, with allocator,
release function, mutability, length/capacity and callback lifetime explicit.
Only the allocating domain frees unless an ABI function explicitly transfers
ownership. Aether ownership rules inform generated signatures; foreign code
must never infer them.

No raw exception crosses a language ABI. Rust catches/contains panic at every
FFI entry; C++ catches all exceptions in its shim; C reports explicit status;
native errors become typed Aether runtime errors; Aether exceptions cross only
through the versioned runtime exception contract. Destructors run before error
translation and error payload ownership is explicit.

## Component ownership and migration method

| Component | Current | Transitional | Long-term | Method / stable boundary |
| --- | --- | --- | --- | --- |
| Lexer, parser, AST | Python | Rust golden/differential port | Rust Stage0; optional Aether parser | Tokens/versioned syntax schema; parser needs differential migration. |
| Resolver, typechecker, lowering | Python | Rust | Rust | Golden corpus plus differential for semantic phases; typed core API. |
| Initial IR model | Python, Rust owned shadow model | Versioned schema parity | Rust | Schema/wire protocol. |
| Initial IR verifier | Rust authority, Python shadow | RP3→RP4→RP5 | Rust | `DIFFERENTIAL_MIGRATION`, protocol v1+. |
| SSA construction | Python | Rust port | Rust | Golden normalized SSA corpus. |
| SSA verifier | Python authority, Rust implementation off production path | Rust differential qualification | Rust | SSA wire/owned API. |
| Analyses, optimizer | Python | Pass-by-pass Rust ports | Rust | Golden/differential according to semantic risk; owned IR. |
| LLVM backend | Python | Rust backend qualification | Rust | Normalized LLVM/native behavior corpus. |
| Driver | Python | Rust CLI | Rust | Stable CLI/compiler API. |
| Diagnostic identity | Python | Versioned Rust records | Rust; Aether may render | Diagnostic schema. |
| Runtime ABI / implementation | LLVM declarations/helpers generated by Python | ABI schema, then Rust runtime | Generated C ABI / Rust | ABI conformance and sanitizer corpus. |
| Stdlib / LinearAlgebra high-level | Python builtins/dependencies and Aether examples | Aether modules | Aether | Module API to native C ABI. |
| Formatter | Python | Aether shadow with golden corpus | Aether | Syntax schema; temporary Python oracle. |
| LSP | Python | Rust | Rust core with editor clients separate | LSP JSON-RPC. |
| Package/build tools | Python scripts/CLI | Aether after prerequisites | Aether | Compiler CLI/artifact schemas. |
| Benchmark/release tooling | Python | Aether workloads optional | Python permitted | Files/artifacts; `NO_PORT_NEEDED`. |
| C++ dependency | None | None until approved dependency | Isolated adapter only | `extern "C"`. |

The machine-readable registry is deliberately smaller than an implementation
manifest: it records actual current authority, target, phase, legal shadows and
boundary. Its test rejects duplicate responsibility names, unknown languages or
phases, authority-as-shadow and shadows in stable/RP0 states. Aspirational Rust
code is never recorded as current production authority.

## Migration and retirement

The standard Rust/Python phases are: RP0 Python only; RP1 Python authority plus
Rust shadow; RP2 Python authority plus required/qualified Rust canary; RP3 Rust
authority plus Python shadow; RP4 Rust authority with Python available only in
an explicit development fallback mode; RP5 Rust-only production and retired
Python implementation. A fallback must never silently choose semantics based
on machine health. Rollback changes an explicit deployment policy/version.

Use `DIFFERENTIAL_MIGRATION` for semantic authorities (verifiers, typechecker,
parser where diagnostics/acceptance matter), `DIRECT_PORT_WITH_GOLDEN_CORPUS`
for deterministic utilities and isolated transforms, and `NO_PORT_NEEDED` for
permanent Python tooling or responsibilities intentionally owned by Aether.

RUST-2 enacted the separately qualified authority switch. RP3 retains Python
as a required shadow for soak evidence and explicit rollback; a later,
separately approved milestone may enact RP4 or RP5.

That verifier is also the first Python production authority to retire. Switch
only after the audit: RP3 keeps Python shadow for a release-window defined by
the promotion ADR; rollback explicitly restores the known-good Python policy;
RP4 restricts Python to opt-in development; RP5 removes it only after the
window has zero disqualifying divergence and release/rollback evidence is
archived. No Python code is deleted by ARCH-1.

Recommended sequence:

1. Accept ARCH-1 and enforce the registry (this milestone).
2. Complete Initial IR verifier authority-readiness and promote to RP3 (done).
3. Audit and design the canonical runtime ABI schema (String/Array first).
4. Qualify one further coherent Rust core boundary—owned Initial IR through
   verification—without requiring a wholesale compiler rewrite.
5. Resume normal language and substantial stdlib work; build SH1 dogfooding and
   formatter prerequisites in parallel with incremental migrations.
6. Promote the formatter as the first SH2 component, then consider lints,
   package/build tools and only later parser self-hosting.
7. Port SSA, analyses, optimizer, backend and driver by value/risk, not as a
   feature-development blockade.

Migration is **enough for the next wave** once (a) the Initial IR Rust verifier
has an approved authority-readiness result and explicit promotion/rollback
plan, (b) runtime ABI ownership and schema direction are frozen by an audit,
and (c) the owned Initial IR→verification boundary has a named canonical target
and passing consistency gates. Rust need not already be production authority,
and Python need not be eliminated. At that threshold large stdlib/language
features may resume if each new responsibility is registered and does not
expand a retiring Python authority without a migration plan.

## Immediate milestone decisions

The Initial IR verifier is at RP3 (Rust authority, Python shadow).
The RUST-1 qualification result is `KEEP_RUST_SHADOW`; see
[`RUST_INITIAL_IR_VERIFIER_AUTHORITY_READINESS.md`](../compiler/RUST_INITIAL_IR_VERIFIER_AUTHORITY_READINESS.md)
and its deterministic JSON artifact. This readiness reference does not change
the authority recorded in the registry.

RUST-1.1 subsequently established
`RUST_VERIFIER_SEMANTIC_PARITY_COMPLETE`. Initial IR verification nevertheless
remains at RP2 with Python authority; packaging/platform qualification and an
RP3 authority CI gate remain separate operational blockers.

RUST-1.2.1 freezes `aether-ir-verifier` as a separately versioned B1 native
companion archive. Its packaging foundation and dependency contract are ready;
RUST-1.2.2 subsequently qualified the four official platform release artifacts
and clean-install contract. RUST-1.3 now records
`READY_FOR_RP3_AUTHORITY_SWITCH`; see
[`RUST_INITIAL_IR_VERIFIER_RP3_FINAL_QUALIFICATION.md`](../compiler/RUST_INITIAL_IR_VERIFIER_RP3_FINAL_QUALIFICATION.md).
RUST-2 used that readiness result to change the default authority and phase;
see [`RUST_INITIAL_IR_VERIFIER_AUTHORITY_PROMOTION.md`](../compiler/RUST_INITIAL_IR_VERIFIER_AUTHORITY_PROMOTION.md).

- First Rust: Initial IR verifier authority-readiness audit.
- First C/C ABI: runtime ABI architecture and canonical schema audit, starting
  with String/Array; no implementation.
- First serious self-host: formatter after syntax/String/collection/file-I/O
  and golden/idempotence prerequisites.
- C++: `NO_CURRENT_CPP_MILESTONE`.

ARCH-1 creates only this ADR, its registry and an architecture consistency
test. It performs no migration, self-hosting, C/C++ addition, ABI or semantic
change, optimizer/O0/O1/O2 change, deletion, or commit.
