# OOP-ARCH-1 — design report

Completed 2026-09-10 as a **documentation-only architecture milestone**.
The deliverable is [OOP_ARCH_1.md](OOP_ARCH_1.md). Its syntax and compiler
operations are proposals, not implemented or qualified language features.
No classes/interfaces, parser changes, runtime code or test fixtures were added.

## Outcome

Recommend existing value structs, identity-bearing class handles managed by
non-atomic intrusive ARC, and nominal method-only interfaces whose initial
values share the underlying class identity. Ordinary class lvalue assignment
aliases with an explicit compiler ownership operation; it does not satisfy the
structural `Copy` capability. Classes and methods are final by default, with
later `open`/`override` support. Read receivers are the default; mutation requires
a declared `mut` signature. Prefer a single `:` relation list and `init` without
repeating the enclosing class name.

The smallest proposed implementation validates concrete class identity and
lifecycle, including a privately owned Buffer's final cleanup. The next step
validates flat class-backed interfaces; inheritance follows separately. This
report does not authorize treating any of those steps as already implemented.

## Evidence and important findings

The [design's source inventory](OOP_ARCH_1.md#1-problem-and-authority) links the
required reconstruction documents and actual compiler sources. Current nominal
struct/enum IDs, generic substitution, type-property derivation, HIR ownership
synthesis, MIR/SSA verification and LLVM recursive drop glue were inspected.
The LANGUAGE-PARITY-1 report is prior qualification evidence only; its reported
299 tests are not a test run for this documentation milestone.

Three repository-specific findings materially shape the proposal:

- `ref mut` already permits aliasing and confers no uniqueness or LLVM `noalias`
  promise. Importing Rust-exclusive receiver semantics would be a redesign.
- Current ownership analysis frequently branches on `guarantees_copy`; class
  aliasing requires a new explicit use category and cleanup accounting, not
  simply setting a Copy flag or lowering classes as ordinary struct pointers.
- The legacy parser already accepts both `implements` and `:` for interface
  conformance. Its inspected class representation does not establish stateful
  base inheritance. Legacy interface receiver mutability is discovered by
  scanning implementations, which the proposal replaces with declared contracts.

Legacy evidence also includes native strong counts, initialized-field cleanup,
private default members, a single constructor plus synthesized positional
construction, const access paths, nominal class/struct interfaces and erased
interface ownership adapters. These are identified as historical findings,
not reconstruction authority or newly executed tests.

Primary language references were checked for the requested C++/C#/Java/Kotlin
dispatch comparison, Rust receiver comparison and Swift ARC cycle illustration.
Links appear beside the comparisons in the design; Aether's recommendations are
engineering judgments, not conclusions dictated by those languages.

## Required decision coverage

Each of the 50 requested report topics has a corresponding numbered design
section. This matrix records the outcome and the exact destination for review.

| # | Topic and outcome | Design detail |
|---|---|---|
| 1 | Problem: identity and sharing consistent with static native value/lifecycle contracts | [Problem](OOP_ARCH_1.md#1-problem-and-authority) |
| 2 | Legacy: shared class handles, RC, private members, constructors, nominal interfaces; no assumed stateful inheritance | [Legacy model](OOP_ARCH_1.md#2-legacy-model-evidence-not-authority) |
| 3 | Preserve alias-visible identity, nominal contracts, encapsulation, deterministic shared lifetime | [Preserved ideas](OOP_ARCH_1.md#3-ideas-preserved) |
| 4 | Change inferred mutation, constructor exposure and interface implementation scanning; bound struct boxing | [Intentional changes](OOP_ARCH_1.md#4-ideas-intentionally-changed-or-bounded) |
| 5 | Struct = value; class = owned identity; interface = nominal behavior plus adapted owning carrier | [Three roles](OOP_ARCH_1.md#5-struct-versus-class-versus-interface) |
| 6 | Counter aliases observe the increment; no inline payload copy | [Identity](OOP_ARCH_1.md#6-class-identity) |
| 7 | Evaluate RC, intrusive/control-block representation, unique/shared, regions, manual and hybrid | [Alternatives](OOP_ARCH_1.md#7-ownership-alternatives) |
| 8 | Recommend compiler-managed non-atomic intrusive ARC in a single-thread profile | [Ownership choice](OOP_ARCH_1.md#8-recommended-initial-ownership) |
| 9 | Alias owning lvalues, transfer fresh owners, acquire before replacement/release | [Assignment](OOP_ARCH_1.md#9-assignment-and-aliasing) |
| 10 | Compare `extends`/`implements`, colon, constructor-like bases and separate blocks | [Syntax alternatives](OOP_ARCH_1.md#10-inheritance-syntax-alternatives) |
| 11 | One colon list; resolver classifies types, checks duplicate identities and rejects wrong kinds | [Relation syntax](OOP_ARCH_1.md#11-recommended-relation-syntax) |
| 12 | At most one stateful open base and any number of interfaces | [Cardinality](OOP_ARCH_1.md#12-class-inheritance-cardinality) |
| 13 | Public instance requirements only; no fields, construction or advanced members | [Interface contract](OOP_ARCH_1.md#13-minimal-interface-contract) |
| 14 | Explicit nominal conformance, exact signatures/capabilities; matching alone is insufficient | [Conformance](OOP_ARCH_1.md#14-nominal-conformance) |
| 15 | Multiple acyclic interface parents later; canonical diamond identity and conflict rejection | [Interface inheritance](OOP_ARCH_1.md#15-interface-inheritance) |
| 16 | Default bodies deferred; free functions can share implementation meanwhile | [Default methods](OOP_ARCH_1.md#16-default-interface-implementations) |
| 17 | Non-virtual/non-overridable by default, open methods opt in | [Dispatch defaults](OOP_ARCH_1.md#17-dispatch-defaults-and-language-comparison) |
| 18 | Mandatory override for inherited class slots; no redundant override for conformance alone | [Override](OOP_ARCH_1.md#18-override-rules) |
| 19 | Classes final by default; add open/override with inheritance, defer sealed/abstract/explicit final | [Modifiers](OOP_ARCH_1.md#19-open-final-and-sealed) |
| 20 | Private members, internal new top-level types, explicit public; protected later | [Visibility](OOP_ARCH_1.md#20-visibility) |
| 21 | `init`, complete field initialization, explicit base arguments, one initializer, no private-field positional synthesis | [Construction](OOP_ARCH_1.md#21-constructors) |
| 22 | Implicit member access, local shadowing and explicit this; no construction escape/calls on this | [Receiver identity](OOP_ARCH_1.md#22-this-and-initialization-escape) |
| 23 | Read/default versus declared mut, no uniqueness, capability-preserving aliases and receiver keepalive | [Mutability](OOP_ARCH_1.md#23-receiver-capabilities-and-mutability) |
| 24 | Inline fields with existing value/storage rules; narrow first subset and no interior refs/views | [Fields](OOP_ARCH_1.md#24-field-access-and-admissible-storage) |
| 25 | Allocate/init/publish, release at cleanup, last-release dynamic destruction; future nonthrowing deinit | [Lifecycle](OOP_ARCH_1.md#25-lifecycle-and-destruction) |
| 26 | Strong cycles leak; graph/weak design later, no collector or nullable side feature | [Cycles](OOP_ARCH_1.md#26-cycles) |
| 27 | Private header/count/descriptor/payload concept; no public ABI or runtime arena IDs | [Object layout](OOP_ARCH_1.md#27-conceptual-physical-representation) |
| 28 | Upcast retains/transfers same complete object, no slicing; handle-slot refs invariant | [Base values](OOP_ARCH_1.md#28-base-class-values-and-conversions) |
| 29 | Object pointer plus witness, one owned token, no wrapper; dynamic witness selection | [Interface values](OOP_ARCH_1.md#29-interface-values) |
| 30 | Verified virtual slots; direct calls where semantically known, devirtualization with proof | [Virtual dispatch](OOP_ARCH_1.md#30-virtual-class-dispatch) |
| 31 | Requirement/witness dispatch, exact receiver/ownership ABI, derived overrides reflected later | [Interface dispatch](OOP_ARCH_1.md#31-interface-dispatch) |
| 32 | Identity equality for statically compatible handles; RTTI/downcast semantics deferred | [Equality](OOP_ARCH_1.md#32-equality-and-future-type-tests) |
| 33 | Alias distinct from Copy, Relocatable/Storable/drop properties and all requested operation costs | [Copy and costs](OOP_ARCH_1.md#33-copy-move-and-performance-contract) |
| 34 | Compatible canonical class/interface applications, per-instance layout/witnesses; generic admission deferred | [Generics](OOP_ARCH_1.md#34-generic-classes-and-interfaces) |
| 35 | Static methods/fields deferred, no global initialization side effect | [Statics](OOP_ARCH_1.md#35-static-members) |
| 36 | Explicit accessors first; properties need visible effects and evaluation rules | [Properties](OOP_ARCH_1.md#36-properties) |
| 37 | Identity behavior uses methods; algorithms/free functions remain first-class organization | [Methods/functions](OOP_ARCH_1.md#37-methods-and-free-functions) |
| 38 | Module-owned nominal IDs, direct imports, transparent aliases, no package system | [Modules](OOP_ARCH_1.md#38-modules-and-nominal-identity) |
| 39 | Class base/interface/value exceptions all remain possible; independent EXCEPTION-ARCH-1 | [Exceptions](OOP_ARCH_1.md#39-exceptions-connection) |
| 40 | Every normal handle valid/non-null; no null/Option/question-mark type admission | [Nullability](OOP_ARCH_1.md#40-nullability-boundary) |
| 41 | Opaque FFI ownership, explicit future unsafe/region/stack/allocator modes remain possible | [Low-level control](OOP_ARCH_1.md#41-low-level-compatibility) |
| 42 | HIR owns nominal resolution, contracts, use categories, adaptation and obligations | [HIR](OOP_ARCH_1.md#42-hir-implications) |
| 43 | MIR owns explicit path operations, object versus slot projections, publication and cleanup | [MIR](OOP_ARCH_1.md#43-mir-implications) |
| 44 | SSA preserves exact types/effects, ownership at joins and proof-required optimizations | [SSA](OOP_ARCH_1.md#44-ssa-implications) |
| 45 | LLVM/runtime lower verified operations to private layout/RC; no semantic reconstruction | [LLVM/runtime](OOP_ARCH_1.md#45-llvm-and-runtime-implications) |
| 46 | Independent identity/graph/slot/init/receiver/token/drop/witness verification and negative IR cases | [Verifiers](OOP_ARCH_1.md#46-fail-closed-verifier-obligations) |
| 47 | OOP-V1 proposal: concrete final class, direct methods, scalar/value fields plus private Buffer lifecycle | [First vertical](OOP_ARCH_1.md#47-first-implementation-vertical-concrete-class-identity) |
| 48 | OOP-V2 proposal: flat class-backed interfaces before stateful inheritance | [Second vertical](OOP_ARCH_1.md#48-second-implementation-vertical-flat-nominal-interfaces) |
| 49 | Named gates for read-only ownership, interior borrows, graphs, generics, modifiers, FFI and errors | [Open decisions](OOP_ARCH_1.md#49-open-decisions-and-admission-gates) |
| 50 | Comfortable identity semantics with explicit costs/capabilities; preserve values and native verification | [Philosophy](OOP_ARCH_1.md#50-fit-with-aether-philosophy) |

## Changes and validation

Only these documentation paths belong to this milestone:

| File | Change |
|---|---|
| `docs/architecture/OOP_ARCH_1.md` | Full decision proposal, evidence, costs, verification obligations and bounded future verticals |
| `docs/architecture/OOP_ARCH_1_REPORT.md` | This outcome, coverage and validation record |
| `docs/architecture/AETHER_V1_LANGUAGE_CHARTER.md` | Cross-reference clearly marked design-only |
| `docs/architecture/AETHER_V1_SEMANTIC_CONTRACT.md` | Cross-reference; existing admitted semantics retained |
| `docs/architecture/AETHER_COMPILER_ARCHITECTURE.md` | Cross-reference to future phase implications and report |

Validation performed: all 50 numbered design sections and report rows checked;
local Markdown links and section anchors checked; balanced code fences checked;
`git diff --check` passed; the changed-file inventory was checked against the
documentation-only allowlist. Existing unrelated untracked `FaCAether` and
`FaCAetherO0` were preserved. No parser/frontend/MIR/SSA/LLVM/runtime/test file
was changed. No compiler regression, differential or native test suite was run,
because this milestone changes no executable behavior. Future qualification
criteria in sections 47–48 are plans, not passing results.

## Accepted limitations

ARC introduces traffic and potentially long synchronous destruction cascades;
strong cycles are not reclaimed. A separate Alias use category complicates the
current binary Copy/move analysis. Read-only ownership and alias-safe interior
storage access are deliberately bounded instead of left for backend guesswork.
Thread transfer, public ABI, generics, user destructors, weak handles and nullable
or exception values remain independent admission work. No implementation or
benchmark claim is made by this report.
