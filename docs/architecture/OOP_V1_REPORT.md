# OOP-V1 — concrete class identity and lifecycle

Status: **ADMITTED**, bounded native Linux x86-64 bootstrap, 2026-09-10.
Baseline for non-class comparison: `19a0dcf`. This implements the first concrete
class vertical from [OOP-ARCH-1](OOP_ARCH_1.md) and its
[design report](OOP_ARCH_1_REPORT.md), both read before implementation.
Those documents remain broader design; interfaces and inheritance are not
implemented. Structs remain nominal inline value types.

## Source admission

```aether
class Counter {
    int value;
    public init(int value) { this.value = value; }
    public mut int increment() { value = value + 1; return value; }
    public int get() { return value; }
}
int main() {
    Counter a = Counter(0);
    Counter b = a;
    b.increment();
    return a.get(); // 1
}
```

`class` is non-generic and effectively final. Classes default to module-internal;
`public class` exports a nominal type. Members default to private; `public` and
`private` are admitted. One `init` with no source result type initializes every
field. Empty classes may synthesize a zero-argument init; nonempty classes
cannot omit it. Read methods are the default and `mut` explicitly authorizes
receiver-derived mutation. `==` and `!=` compare compatible concrete identities.

Fields admit supported primitive scalars, transparent aliases, finite concrete
Copy/no-drop structs/enums with available layout and private `Buffer<int>`.
Class handles are permitted as concrete locals, by-value parameters and results,
including transparent aliases. They are not structural Copy and cannot be
stored in aggregates/containers or passed through generic applications in this
slice. No class graph edge, interface, inheritance, nullable handle, interior
reference/view, class-slot reference, user destructor or exception is admitted.
Read temporary calls work; temporary field access and temporary mut calls do not.

Runnable sources: [Counter](../../compiler-next/tests/programs/oop_v1_counter.ae)
and [Owner](../../compiler-next/tests/programs/oop_v1_owner.ae). The authoritative
contract is the [OOP-V1 semantic section](AETHER_V1_SEMANTIC_CONTRACT.md#oop-v1--concrete-class-identity-and-lifecycle).

## Implementation inventory

| Area | Files changed or added | Responsibility |
| --- | --- | --- |
| Frontend | `compiler-next/crates/aether-frontend/src/{ast.rs,parser.rs,lib.rs,types.rs,oop.rs,hir.rs,hir/classes.rs}` | Syntax, nominal types, metadata/layout/drop recipe, source checking, explicit class operations, central ownership synthesis, HIR verification and dumps |
| Middle | `compiler-next/crates/aether-middle/src/{mir.rs,mir/classes.rs,ssa.rs,ssa/classes.rs}` | Construction/publication lowering, ordered ownership effects, independent MIR/SSA checks and dumps |
| Backend | `compiler-next/crates/aether-backend-llvm/src/{lib.rs,classes.rs}` | Private pointer ABI, runtime counters/ARC, field operations, direct calls and final drop/free |
| Qualification | `compiler-next/crates/aether-driver/tests/oop_v1.rs`; frontend unit tests in `hir/classes.rs` | Native O0/O2 counters, source rejections, module identity, corrupted HIR/MIR/SSA/metadata |
| Reproduction | `compiler-next/tests/programs/oop_v1_*.ae`, `compiler-next/tests/measure-oop-v1.py` | Two examples and three cost workloads with a standalone measurement script |
| Documentation | `compiler-next/README.md`, `AETHER_V1_LANGUAGE_CHARTER.md`, `AETHER_V1_SEMANTIC_CONTRACT.md`, `AETHER_COMPILER_ARCHITECTURE.md`, this report | Bounded admission, contract, implementation and evidence |

## Required implementation account

The numbering follows the requested 52-point report.

| # | Topic | Implemented contract / evidence |
| --- | --- | --- |
| 1 | Source syntax | Concrete `class`, optional top-level `public`, private/public fields and methods, `init`, declared `mut`, construction, direct calls, identity equality; example above. |
| 2 | Changed files | Complete inventory above. Legacy compiler and OOP-ARCH-1 design are unchanged. |
| 3 | ClassId / TypeId | Kind-safe `ClassId` identifies a module-owned class. `TypeData::Class(ClassId)` is a nominal arena entry, never a struct or pointer surrogate. Transparent aliases canonicalize to it. |
| 4 | Fields | `ClassFieldInfo` carries exact FieldId, declaring ClassId, index, canonical type, visibility, target offset and span. Metadata retains exact method FunctionIds and generated destruction recipe. |
| 5 | Handle semantics | One non-null owning handle represents one strong obligation to a shared live identity. Lvalue uses Alias; fresh results Transfer. |
| 6 | Object layout | One complete allocation with aligned field payload. Empty object: size 8/align 8; one int Counter: 16/8; one Buffer<int> Owner: 24/8. Layout is bootstrap-private. |
| 7 | Header | Eight-byte unsigned strong count at offset 0. Fields start at their target-aligned offsets after it. Handle size/alignment is one target pointer (8/8 here). No descriptor is needed with concrete static destruction. |
| 8 | Initializer | Parser recognizes contextual `init`; collection assigns its exact function identity before resolution. At most one explicit init, no overload/result/delegation syntax. Internal bootstrap functions use an ignored int64 completion carrier and generated zero return; this admits no source initializer return value or new unit type. |
| 9 | Definite initialization | Source dataflow intersects Copy-field initialization at joins, checks reads, and requires all fields on completion. Owning-field state must agree at joins. Loops cannot establish new initialization. MIR/SSA independently explore initialization paths. |
| 10 | Publication | HIR Construct lowers to ObjectAlloc → InitCall → PublishObject. Unpublished ClassToken cannot escape, undergo ordinary Move/Drop or become a class handle without the unique completed-init transition. Normal exits cannot leave unpublished allocations. |
| 11 | `this` | Compiler-only borrowed receiver token, distinct from owning Class. No alias, escape, return, ordinary argument, shadow/rebind or reference formation; no method call during init. |
| 12 | Read receiver | Default declared capability; reads Copy fields and calls read methods. Writes and mut calls through this path fail. Read does not imply global immutability or purity. |
| 13 | Mut receiver | Explicit declaration permits receiver-derived writes and mut calls. It conveys neither uniqueness nor noalias. Mut calls require an addressable writable receiver. |
| 14 | Dispatch | DirectMethodCall retains exact FunctionId in semantic HIR and InstanceId after concretization. LLVM invokes the resolved bootstrap function, with no vtable or string lookup. |
| 15 | Evaluation order | HIR places receiver first; ClassOp mapping lowers it once before arguments. Native fixture inserts owner replacement and a nested argument call after receiver acquisition. |
| 16 | Keepalive | ReceiverKeepalive acquires one temporary strong obligation for lvalue/borrowed receivers, or transfers a fresh owner's token. A typed keepalive must remain live at DirectMethodCall and is dropped after the call. Dumps and native counters expose it. |
| 17 | Alias | HandleAlias explicitly retains once and creates one new owner; source remains live. Not field copying or object allocation. |
| 18 | Transfer | HandleTransfer and existing verified Move carry one obligation without retain. Publication/fresh call results also produce owned values for ordinary transfer; no mandatory retain/release pair is added. |
| 19 | Structural Copy | Class: Copy=false, Relocatable=true, Storable=true only in admitted positions, needs_drop=true. Generic Copy guarantees remain structural; compiler-only borrowed receiver tokens are not source class values. |
| 20 | Assignment | MIR evaluates/acquires RHS, moves the old destination to a cleanup temporary, installs the new owner, then drops the old owner. Buffer field replacement likewise stores new ownership before destroying old ownership. |
| 21 | Parameters | Lvalue concrete class argument aliases into callee ownership; fresh result transfers. Callee cleanup releases its obligation. Buffer arguments retain their existing consuming semantics. |
| 22 | Returns | Fresh owner transfers. Returning an owning lvalue aliases before reverse local cleanup, keeping the returned token live. Borrowed `this` cannot be returned. |
| 23 | Self-assignment | Exact class local self-assignment is recognized as a no-op. No release-before-acquire sequence exists. `this=this` is rejected. |
| 24 | Field access | Implicit unshadowed field and `this.field` resolve exact identities; parameters/locals take precedence. Public Copy fields can be accessed through local handles. Owning Buffer extraction and temporary field access are rejected. |
| 25 | Visibility | Default private members, explicit public/private, module-internal default classes. Each IR validates lexical access and exact member identity. Public class APIs cannot expose internal class types. |
| 26 | Equality | Same-ClassId pointer identity for `==`/`!=`; aliases equal, independent objects unequal. No ordering, hash, field equality or cross-class equality. |
| 27 | Local cleanup | Existing central scope cleanup emits one Drop/release per remaining owner in reverse order. Transferred old slots do not release. Early returns are qualified. |
| 28 | Final release | Decrement strong count; at zero execute verified reverse owning-field drops then exactly one allocation free. No source deinit. |
| 29 | Nested Buffer | Init consumes Buffer<int> into a private field. Alias duplication affects the handle only. Final class release destroys one Buffer descriptor/backing before freeing the object. Replacement also frees the previous Buffer. |
| 30 | Conditional ownership | Existing drop flags and MIR ownership flow integrate class locals. SSA checks selected incoming phi ownership transfers and normal-path balances, with loop alias/replacement cases. |
| 31 | HIR | ClassInfo/signatures plus Construct, FieldRead/Write, DirectMethodCall, HandleAlias/Transfer, ReceiverKeepalive and IdentityEq. Exact metadata, receiver modes and cleanup survive dumps. |
| 32 | Ownership synthesis | Central existing HIR synthesis walks ClassOp operands, distinguishing owning results from borrowed identities. Verification recomputes cleanup and compares it, including expressions nested in aggregates/mathematics. LLVM does not invent ownership. |
| 33 | MIR | Explicit ObjectAlloc, InitCall, PublishObject, field initialization/replacement, alias/transfer, keepalive, direct calls and identity comparison; ordinary Move/Drop implement matching transfer/release contracts. |
| 34 | MIR verification | Rechecks metadata/signatures/access/types, constructor protocol and definite fields, receiver capability, no Copy/escape, live token use, transfer/drop balance, nested destruction recipe and identity equality without trusting HIR admission. |
| 35 | SSA | Ordered Class operations remain ordinary effectful instructions; no pure retain/release representation. Phi nodes transfer owning obligations. No MemorySSA added. |
| 36 | SSA verification | Independent class/keepalive/direct-Buffer ledger explores paths and phi edges; rejects duplicate/discharged owners, invalid publication, wrong fields/targets/types, mut escalation, class memory slots and normal-path leaks. Existing other container/math verifiers remain authoritative for their protocols. |
| 37 | LLVM | Semantic class/token types lower to pointers; byte field offsets come from verified target layouts. Allocation, retain, typed Drop, calls and writes translate explicit verified effects. No atomic instructions, class noalias or purity attributes are introduced. |
| 38 | Runtime | Private typed object alloc helpers, one non-atomic retain helper and per-type release/drop glue use the existing aether_alloc/aether_free boundary. Count zero and maximum retain trap before arithmetic wraps. No tracing GC, weak references or RTTI. |
| 39 | ARC counters | Private alloc/retain/release/destroy/final-Buffer-field-drop globals. Tests read actual emitted counters after source main cleanup in both O0 and O2. Exact schedules below. |
| 40 | Allocation/free | Existing heap allocation/free counters independently include object and Buffer backing. One object plus one nonempty Buffer gives two allocations/two frees; replacement gives three/three. |
| 41 | Equality execution | Alias ==/!= and independent same-field-value objects execute at O0/O2. Cross-ClassId equality is rejected in source and independently corrupted MIR/SSA. |
| 42 | Native aliasing | Required Counter mutation returns 1 through the original alias. Rebinding one alias preserves the other; method arguments/returns and loop aliases remain live with exact counts. |
| 43 | Modules | Two imported public Counter classes with identical spelling/layout construct separately and return 12. Cross assignment/equality, private-field access and internal-class access fail. |
| 44 | Source negatives | 50 named source boundary cases plus four module failures and one public-signature failure: 55 rejection cases. Named cases require structured diagnostics with source spans. |
| 45 | Corruptions | 10 HIR body/cleanup mutations, eight direct metadata mutations, 21 MIR and 20 SSA mutations: 59 independent rejection cases, detailed below. |
| 46 | O0/O2 costs | Reproducible combined-operation native workloads and layout/code-size observations below. No isolated per-operation latency or zero-cost claim. |
| 47 | Non-class codegen | Six representative programs produce byte-identical LLVM versus baseline, with matching native O0/O2 exits. No ARC symbols. Two unused-class programs also execute without ARC runtime or class balance checks. |
| 48 | Test counts | 316 workspace tests: backend 7, LANGUAGE-PARITY 7, OOP integration 15, previous vertical integration 219, frontend 46, middle 22. Zero failures/ignored tests. Details below. |
| 49 | Differential | Legacy harness: 21 checked, zero failures; preserves explicitly classified intentional differences. Legacy is not an OOP oracle. |
| 50 | Accepted debt | Conservative source boundaries, bootstrap completion carrier/counters, single-thread ARC, abort-only failure, no ARC-specific optimizer, and explicit limits below. |
| 51 | Open decisions | Future public object ABI, interfaces and conversions, graph ownership/cycles, generic Alias capability, interior access and source no-result spelling remain unadmitted design work. |
| 52 | OOP-V2 | Recommend a separate flat nominal interface vertical only after freezing carrier ownership, direct-to-interface conversion, method receiver capabilities and independent witness/call verification. No interface or inheritance implementation is included here. |

## Exact native events

Each row reads counters after all source-main cleanup and checks the source
result. Counts include any explicit receiver keepalive. Final destroy count is
one per object, immediately followed by its typed free; total heap frees also
include Buffer backings.

| Scenario | Object alloc | Retain | Release | Final destroy | Final Buffer field drop | Heap alloc/free |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Empty class | 1 | 0 | 1 | 1 | 0 | 1/1 |
| `a=Counter(0); b=a;` only | 1 | 1 | 2 | 1 | 0 | 1/1 |
| Aliasing Counter + b.increment + a.get | 1 | 3 | 4 | 1 | 0 | 1/1 |
| Independent objects + equality | 2 | 0 | 2 | 2 | 0 | 2/2 |
| Aliases + == and != | 1 | 1 | 2 | 1 | 0 | 1/1 |
| Self-assignment + get | 1 | 1 | 2 | 1 | 0 | 1/1 |
| Replace a while b survives, then two gets | 2 | 3 | 5 | 2 | 0 | 2/2 |
| Lvalue argument + increment/get in callee + caller get | 1 | 4 | 5 | 1 | 0 | 1/1 |
| Fresh argument + increment/get in callee | 1 | 2 | 3 | 1 | 0 | 1/1 |
| Fresh return + caller get | 1 | 1 | 2 | 1 | 0 | 1/1 |
| Local lvalue return + caller get | 1 | 2 | 3 | 1 | 0 | 1/1 |
| Parameter lvalue return + mutation/get | 1 | 4 | 5 | 1 | 0 | 1/1 |
| Temporary read receiver | 1 | 0 | 1 | 1 | 0 | 1/1 |
| Owner Buffer + alias + marker call | 1 | 2 | 3 | 1 | 1 | 2/2 |
| Owner Buffer replacement + alias + marker | 1 | 3 | 4 | 1 | 1 | 3/3 |
| Three iterations of alias + increment, final get | 1 | 7 | 8 | 1 | 0 | 1/1 |
| Receiver kept across original-slot replacement | 2 | 1 | 3 | 2 | 0 | 2/2 |

`object_buffer_drop_count` specifically counts Buffer fields destroyed by final
class release. It does not count the old Buffer destroyed during field
replacement; the additional heap alloc/free pair qualifies that path. No
interior Buffer value is duplicated or moved out. The receiver-rebinding case
uses a verified MIR fixture because source references to class handle slots are
intentionally unavailable: the original receiver is acquired, its local owner
is replaced, a nested argument call runs, and the method still observes the
original object (result 5). Both MIR and SSA admit that fixture and native O0/O2
execute it with the counts above.

There are 30 positive class scenarios run at both O0/O2 (60 native runs), plus
two unused-class scenarios at both modes (four native runs). Two invalid strong
header fixtures (zero and maximum count) run in both modes and must terminate
by a trap signal (four further native runs). This is 68 native executions inside
the OOP integration suite, counted separately from Rust test functions and
baseline/cost measurements.

## Independent rejection evidence

The two new frontend unit tests mutate nine typed HIR operations plus one
cleanup list, and eight metadata properties: omitted/duplicated/reordered drop
steps, offset, FieldId, owning ClassId, size and missing method metadata.
The MIR suite mutates 12 lifecycle/type instructions, cross-class equality,
read-method field mutation, omitted/duplicated owning-field initialization and
five metadata recipes/offsets. SSA has ten core instruction corruptions, one
owning phi duplication, cross-class equality, read-method mutation, two owning
field-init changes and the same five metadata corruptions. Each raw IR is
verified independently; no previous verified wrapper authorizes the mutation.

Failures include implicit owner bitcopy, alias-as-transfer, missing/duplicate
release, retain/use after final release, invalid initializer or method target,
publication before init, early keepalive release, wrong ClassId/FieldId,
read-receiver mutation and invalid nested destruction order. SSA tests preserve
definition structure where needed to exercise semantic checks rather than
merely fail on a missing definition. HIR recomputation rejects missing cleanup.

Source negatives cover missing/conditional initialization, reads before init,
construction escape, visibility, read/mut misuse, invalid field/container/ref
admission, owning-field extraction, class generic applications/Copy constraints,
null/order/cross-class comparison, temporary mut calls, this rebinding/shadowing,
and consuming a Buffer twice. Ten existing container/mathematical/parity programs
are additionally compiled with an empty class local to qualify coexistence.

## Cost observations

Measured locally with rustc 1.97.1 and clang 22.1.8, Linux x86-64. Reproduce with:

```sh
python3 compiler-next/tests/measure-oop-v1.py --runs 7
```

The script builds each source, obtains the same LLVM for clang O0/O2, runs one
warmup and seven measured process invocations, requires success, and reads GNU
`size` text bytes. Timings include process startup and are descriptive samples,
not isolated ARC latency. Workloads keep compiler semantic counters enabled.

| Workload | Mode | Median ms | Min–max ms | ELF text bytes |
| --- | --- | ---: | --- | ---: |
| 1,000,000 alias + direct increment + keepalive iterations | O0 | 11.715 | 11.365–12.568 | 3289 |
| Same | O2 | 1.505 | 1.322–1.748 | 1702 |
| 100,000 allocate + alias + last-release iterations | O0 | 2.861 | 2.630–3.153 | 3185 |
| Same | O2 | 0.476 | 0.464–0.558 | 1334 |
| 100,000 object + Buffer allocate/alias/final-cleanup iterations | O0 | 3.557 | 3.058–3.881 | 3737 |
| Same | O2 | 0.468 | 0.335–0.565 | 1613 |

At O0, allocation helpers, non-atomic retain/load/store and typed release/drop
remain inspectable. The direct call has no dispatch table, but acquiring a
receiver from a local adds a retain/release pair. Fresh receivers avoid that
pair by transfer. Last release additionally branches, drops nested ownership
and frees storage. O2 can inline and remove allocation/lifecycle work whose
results are unused, or simplify balanced operations using ordinary LLVM proofs;
these samples do not measure unavoidable per-operation overhead. Semantic
qualification separately observes exact counters in both optimization modes.
No ARC-specific optimization pass or zero-cost class claim is introduced.

## Non-class equivalence and regression

A clean compiler built from `git archive 19a0dcf compiler-next` was compared
with the modified compiler using identical source paths. LLVM was byte-identical
for all six cases; each compiler's output was linked and run at O0 and O2
(24 native executions). All four exits per case matched:

| Case | LLVM bytes | Exit | LLVM SHA-256 |
| --- | ---: | ---: | --- |
| Scalar arithmetic | 4496 | 21 | `0087b707c6de7bc5ea97d3a804133aa6b8044d9490be81e9970f4c051f20a64c` |
| Inline struct | 5399 | 7 | `466b855de31cad5ee14b487db61f31b4837c8f423ae36e98476368e8817ee49f` |
| Buffer | 8749 | 7 | `4e107c2ae7971555e1c6c0370dddf77f3f22f80ac07d5032033345a76193ba7b` |
| Generic identity | 4286 | 3 | `09e7d03375868bf3bf64402e639fa8be8e84b5b354e5c08f97c0c94a128c5ae8` |
| Matrix multiplication | 19721 | 7 | `ab7ad7afd9e27f3698cc4de2d31c617f1c1e7b35430c112e16a762036f4c280c` |
| LANGUAGE-PARITY main/comments | 4197 | 0 | `8c33d79df1e5fc51c56914a4f0feeb53b197085dfc094932d1b550e7d3d48b3d` |

No class ARC symbol appeared. Unused class declarations are separately tested:
closed direct-call reachability suppresses class runtime/glue and unreachable
class-dependent functions when the entry has no class use. All source bodies
still pass semantic verification. Existing Buffer/math runtime emission policy
is unchanged; no class RC work is added to the entry wrapper.

Required checks, run from `compiler-next` for Cargo commands and repository root
for the others:

| Command | Result |
| --- | --- |
| `cargo test --workspace` | 316 passed, 0 failed, 0 ignored |
| `cargo fmt --all --check` | Pass |
| `cargo clippy --workspace --all-targets -- -D warnings` | Pass |
| `git diff --check` | Pass |
| `bash compiler-next/tests/run-differential.sh` | 21 checked, 0 failures |

The 316 tests comprise seven backend tests, seven LANGUAGE-PARITY integration
tests, 15 OOP integration tests, 219 existing vertical integration tests,
46 frontend tests and 22 middle tests. The new admission adds 17 Rust test
functions (15 integration plus two frontend) over the 299-test baseline.
Previous V0–V33, MATH-ARCH-1 and LANGUAGE-PARITY qualification remains green.
The differential harness checks only legacy-comparable cases, preserving its
intentional int/division semantic differences; OOP evidence is native counters
and independent verifier checks, not a legacy interpreter oracle.

## Accepted debt, open decisions and next vertical

The admission intentionally rejects class graph fields, borrowed/stored refs,
interior views and Buffer extraction, class-slot references, class-containing
containers/aggregates, generic classes and generic class applications. Read
method bodies cannot acquire ownership from `this`; mut is nonexclusive.
Temporary mut calls and field access are not admitted. Concrete Copy/no-drop
field layouts must already be available; this is not a general generic-field
facility. Initializer flow conservatively disallows loop-established fields
and divergent owning-field state at joins. A trap is abortive/no-unwind and can
bypass partial-init cleanup; normal publication and exit remain verified.

The internal int64 initializer completion carrier and always-present private
counters in class-using bootstrap programs are implementation debt, not public
source/API commitments. Strong RC is single-threaded and non-atomic. Header
invariant failures trap without a stable public diagnostic. No ARC-specific
elimination, weak ownership, cycle collection, public descriptor/ABI, FFI class
carrier, source destructor or exception machinery is included.

Open decisions remain source no-result spelling beyond init, public ABI/layout,
interface carrier/conversion semantics, graph ownership and cycle policy,
future generic Alias capability, and safe interior access. None is implicitly
resolved by the concrete pointer ABI or by class Storable/Relocatable properties.

OOP-V2 should qualify flat nominal interfaces as a separate vertical: exact
InterfaceId, bounded method requirements with declared receiver modes, explicit
owning carrier conversion and witness identities, direct implementation lookup,
keepalive across interface calls and independently verified ownership/drop of
the carrier. Establish its source/API contract before admission, with new
positive/negative/corruption and native counter cases. Inheritance remains a
later independent decision.
