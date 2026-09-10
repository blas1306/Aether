# OOP-V2 — flat nominal class-backed interfaces

Status: **QUALIFIED / ADMITTED**, Linux x86-64 native bootstrap, 2026-09-10.
This is the second bounded OOP implementation vertical. OOP-V1 remains authority
for object identity, class lifecycle, non-atomic ARC, Alias/Transfer, receiver
capabilities, direct class calls and visibility. OOP-ARCH-1 remains broader design.

The requested `Counter` / `CounterAccess` program returns **1**. The interface
and class carriers refer to the same object. There is no wrapper allocation,
struct boxing, class/interface inheritance, `open` or `override` admission.

## Implementation inventory (requested report items 1–39)

| Item | Implemented contract and evidence |
| --- | --- |
| 1. Syntax | `interface I { int get(); mut int inc(); }`, `public interface`, and `class C : I1, I2`. Empty interfaces are allowed. Bodies, fields, unsupported modifiers and generic/interface relation syntax are rejected. |
| 2. Files | Frontend `interfaces.rs`, `ast.rs`, `parser.rs`, `types.rs`, `hir.rs`, `hir/classes.rs`, `oop.rs`, exports in `lib.rs`; middle `mir.rs`, `mir/classes.rs`, `ssa/classes.rs`; backend `lib.rs`, `classes.rs`; driver `tests/oop_v2.rs`, updated obsolete interface rejection in `tests/oop_v1.rs`; eight `oop_v2_*.ae` fixtures and `tests/measure-oop-v2.py`; this report, README, charter, semantic contract and compiler architecture. |
| 3. InterfaceId | Kind-safe `InterfaceId(u32)`, allocated per module declaration. `TypeData::Interface` is distinct from class, struct, tuple and pointer. Imported same-spelled interfaces remain distinct. Transparent aliases retain the canonical ID. |
| 4. Requirements | `RequirementInfo` records `RequirementId { interface, index }`, name, canonical parameter/result TypeIds, receiver mutability and source span. Parameter reference modes are part of canonical TypeIds. |
| 5. Relations | Resolved colon-list targets populate `ClassInfo.interfaces`. Only canonical InterfaceIds qualify. Duplicate IDs, including aliases, are rejected; a class target reports inheritance not yet admitted. No structural conformance exists. |
| 6. Exact matching | Each witness slot names one method on its exact concrete class. Name, public visibility, parameter count/types/modes and result type must match. ClassMethodInfo contracts are independently checked against actual function signatures in each phase. |
| 7. Receiver matching | Read and mut requirements must match implementation declaration modes exactly. No weakening, strengthening, variance or overload selection. |
| 8. Visibility | Requirements are implicitly public; redundant `public` is accepted. Interfaces default to internal; `public interface` permits imported use. A private matching method cannot implement a requirement. Public class conformance/API and public interface contracts cannot expose internal object types. |
| 9. Adaptation | HIR `ClassOp::InterfaceAdapt` carries concrete ClassId, target InterfaceId, WitnessId, source and explicit transfer flag. The declared relation and witness are checked before LLVM. |
| 10. Lvalue adaptation | Unwrap the source's pending class Alias and perform exactly one adaptation retain; source owner stays live. No double retain and no object copy. |
| 11. Fresh adaptation | Fresh construction/call ownership is consumed by Transfer; conversion adds zero retains. |
| 12. Carrier | One owning semantic interface value; private LLVM `{ ptr object, ptr witness }`, 16 bytes/alignment 8 on Linux x86-64. Class handles remain one pointer with their unchanged eight-byte count header. |
| 13. Witness | Immutable compiler-generated `WitnessInfo` per exact ClassId/InterfaceId, with explicit WitnessId and verified slot recipes. It owns no strong reference. |
| 14. Slots | Requirement declaration order determines private method slots. RequirementId remains semantic authority. Numeric slot must equal that requirement's verified index; LLVM reserves physical slot zero for concrete release, so methods use index + 1. |
| 15. Direct class calls | `DirectMethodCall` continues to name a concrete function instance and emits a direct call, even when the class implements interfaces. |
| 16. Interface dispatch | `InterfaceCall` records RequirementId (including InterfaceId), verified slot, typed receiver/arguments and expression/instruction result type. Dynamic selection loads that slot from the receiver's witness. No strings survive as target authority. |
| 17. Adapters | No thunk is necessary for this bootstrap: concrete and erased receivers both lower to `ptr`, and all remaining parameter/result types match exactly. An ABI-changing target would require typed adapters before admission there. |
| 18. Read calls | Read interface calls accept ordinary readable locals and fresh results. They do not grant mutation or imply purity. |
| 19. Mut calls | Mut requirements require writable local carriers. They grant shared object access, not uniqueness/exclusivity/noalias. Mutation is visible through the original class and other interface aliases. |
| 20. Keepalive | Internal `TypeData::InterfaceKeepalive { interface, mutable }` retains both carrier components before arguments; its strong object obligation lasts through the indirect call. A fresh read receiver transfers. Native MIR rearrangement qualifies rebinding/releasing the original owner during argument evaluation. |
| 21. Alias | Typed HandleAlias on interface lvalues retains the object once and preserves witness metadata. Interfaces never satisfy structural Copy. |
| 22. Transfer | Typed HandleTransfer and ordinary verified Move consume existing obligations. Fresh interface call/return results do not add an Alias retain. |
| 23. Parameters | Concrete interface by-value parameters are admitted. Interface and conforming class lvalues alias into the callee; fresh class/interface results transfer. Callee cleanup releases its object obligation. Exact scalar/reference/value/Buffer/interface method parameters are qualified. |
| 24. Returns | Concrete interface returns are admitted, including methods returning interface values. Lvalue class/interface returns acquire before local cleanup; fresh results transfer with witness identity intact. Borrowed returns remain forbidden. |
| 25. Equality | Interface `==` and `!=` are rejected with a source-spanned diagnostic. No cross-interface identity comparison is defined. Concrete class equality is unchanged. |
| 26. Cleanup | Existing typed Drop releases one object token; assignment acquires and publishes before dropping the previous carrier, and exact self-assignment is a no-op. Conditional scopes and loop owners follow existing cleanup dataflow. |
| 27. Final destruction | Release loads the concrete drop function from witness slot zero and passes only the original object pointer. The final token destroys the exact concrete class and frees it once. Witnesses are never released. |
| 28. Buffer cleanup | `oop_v2_owner.ae` returns an interface after all class locals have been cleaned. Final interface release destroys its private Buffer once, frees Buffer backing once and frees the class once. Fresh adaptation is separately qualified. |
| 29. ARC counters | Native assertions read object allocation, retain, release, destruction, Buffer-field drop and total heap allocation/free counters after main cleanup. Exact counts below pass at O0 and O2. |
| 30. Wrapper evidence | Every measured total heap allocation is accounted for by class objects and Buffer backing. All wrapper deltas are zero. Adaptation emits retain-if-Alias plus two insertvalue operations; it emits no allocation. Witnesses are static constants. |
| 31. HIR | InterfaceAdapt/InterfaceCall are explicit ClassOp variants; typed Alias/Transfer/keepalive retain authority. Parsed AST dumps also show interface declarations. |
| 32. HIR verifier | Independently verifies all class/interface metadata, method signatures, adaptation/slot/result/capability contracts, source Alias versus Transfer and owner cleanup before lowering. Nine operation corruptions and fifteen metadata corruptions fail. |
| 33. MIR | Whole interface carriers retain semantic TypeIds. Interface adaptation/alias/keepalive/calls are ordered Class operations; ordinary Move/Drop carries exact transfer/release. Call receiver cleanup occurs after arguments and call. |
| 34. MIR verifier | Revalidates metadata/signatures/operations and ordered owner obligations. Fourteen operation/cleanup corruptions plus thirteen independently applied metadata/destruction corruptions fail. No semantic operation can construct arbitrary object/witness halves, allocate an interface wrapper or release a witness. |
| 35. SSA | Whole typed interface owners and keepalives participate in the existing path-sensitive owner ledger. Moves and executed phi edges transfer a single obligation; interface calls remain ordered effects. |
| 36. SSA verifier | Independently revalidates witness and signature authority, result/receiver/slot types and ownership. Thirteen operation corruptions, thirteen metadata/destruction corruptions, one owning-phi duplication and one missing release of an interface call result without local adaptation fail. Stale owner use and premature keepalive drops fail the same ledger. |
| 37. LLVM carrier | Lowering to a pointer pair happens after VerifiedSsa. Alias/keepalive extraction retains only object; transfers preserve both components. No raw pointer-pair authority exists in unverified semantic IR. |
| 38. LLVM calls | Extract object/witness, GEP verified method index + 1, load target, call with exact receiver/argument/result ABI. Release separately loads slot zero. No name lookup, RTTI API, atomics, GC or noalias claim. |
| 39. Metadata emission | Only witnesses selected by reachable adaptations are emitted as `internal constant` arrays. Reachability includes their target methods. Unused interface declarations/functions add no interface helpers to direct-class-only/scalar programs; reachable interface signatures still receive necessary cleanup glue even for uninhabited recursive returns. |

## Source, corruption and execution evidence (items 40–46)

**40. Positive source tests.** The primary native table has 23 programs:
lvalue adaptation, fresh adaptation, interface alias, shared mutation, two
interfaces, read, mut, empty interface, fresh/local/class returns, interface and
class lvalue arguments, fresh class/interface arguments, temporary read receiver,
fresh Buffer owner, returned sole Buffer owner, conditional cleanup, replacement,
self-assignment, loop cleanup and transparent alias. Five further native programs
qualify exact scalar, reference, struct, Buffer and interface method signatures.
Two-module execution proves independent nominal identities. Direct codegen and
unused-interface tests cover unchanged concrete calls and reachability.

**41. Negative source tests.** The table contains 39 named rejections: structural
conformance, missing/private/wrong-parameter/wrong-result/wrong-arity/wrong-reference-
mode implementations, both read/mut mismatches, duplicate relations and aliased
duplicates, class and interface inheritance, default body, field, init, generic
interface/method, struct conformance, unrelated class, different nominal interface,
struct/enum/class/container storage, both equality operators, null, ref/view,
implements, extends, override, private/static/duplicate requirements, incompatible
same-name requirements, Copy-bound use and temporary mut calls. All carry spans.
Three additional module cases reject cross-module same-shape conversions and
inaccessible internal interfaces. The old OOP-V1 “interface is unsupported” test
now rejects a generic interface; its other 15 regression tests remain intact.

**42. Metadata corruption.** Fifteen frontend variants cover wrong ClassId,
InterfaceId, missing/duplicate/reordered slot, wrong RequirementId/MethodId,
private target, wrong receiver/parameter/result, absent nominal relation,
duplicate relation and invalid WitnessId. Thirteen variants are separately
applied to MIR and SSA, including a cleared concrete destruction recipe.

**43. HIR corruption.** Nine mutations change adaptation interface/witness,
Alias to Transfer, call requirement/result/slot/receiver, receiver capability,
and a direct class call into an interface call without adaptation. Each rejects
without MIR lowering. Metadata corruption also runs verify_hir directly.

**44. MIR corruption.** Fourteen mutations independently change adaptation
ClassId/InterfaceId/witness/source/ownership, call slot/requirement/receiver/args,
move keepalive release before call, duplicate or remove release, replace Alias
with Use, and remove mut capability. Metadata corruption additionally substitutes
incompatible targets and skips concrete destruction. A valid rearranged MIR
fixture rebinds the original carrier between keepalive and argument call, then
passes MIR/SSA and executes correctly.

**45. SSA corruption.** Thirteen mutations independently alter adaptation
identity/witness/ownership, call slot/requirement/receiver/result, call/drop order,
duplicate/missing release, Alias without acquisition and receiver capability.
A separate conditional fixture duplicates one incoming owner across two phis and
is rejected. Metadata mutations are performed on fresh clones of valid SSA,
independently of MIR rejection. A further mutation removes cleanup from a plain
interface-returning call with no local adaptation; this still requires SSA token
accounting and is rejected. Since interface values cannot be split in semantic
IR, mismatched object/witness pairs, witness-as-owner release and wrapper creation
must attempt invalid typed sources/results/operations; backend pointers are not
accepted as substitute semantic proof. This qualification does not purport to
validate arbitrary LLVM edits made after the VerifiedSsa trust boundary.

**46. Native profiles.** 31 native programs/fixtures execute under both `-O0`
and `-O2` (62 executions per integration-suite run): 23 primary programs, five
exact-signature programs, one module fixture, one rebound-keepalive fixture and
one unused-interface program. Thirty of these assert exact runtime counters; the
unused-interface fixture asserts native exit 0 and absence of ARC machinery.
The six cost workloads execute seven times in both profiles (84 executions).
The required standalone Counter fixture returns 1, and the sole-owner fixture
returns 7. Toolchain: rustc/cargo 1.97.1, clang 22.1.8, Linux x86-64.

### Exact native ARC counts

Counts are total events, including explicit receiver keepalives. Columns:
A=object allocations, R=retains, L=releases, D=final destroys, B=Buffer-field drops,
H/F=total heap allocations/frees. Wrapper allocations are zero in every row.
Keepalive retains are distinguished in the notes; witnesses never retain.

| Scenario | A | R | L | D | B | H/F | Retain explanation |
| --- | ---: | ---: | ---: | ---: | ---: | --- | --- |
| Class lvalue → interface, no call | 1 | 1 | 2 | 1 | 0 | 1/1 | One adaptation Alias |
| Fresh class → interface, no call | 1 | 0 | 1 | 1 | 0 | 1/1 | Transfer |
| Interface alias, no call | 1 | 1 | 2 | 1 | 0 | 1/1 | One interface Alias |
| Shared mutation then class read | 1 | 3 | 4 | 1 | 0 | 1/1 | One adaptation + two keepalives |
| Two interfaces, three reads/mutations | 1 | 5 | 6 | 1 | 0 | 1/1 | Two adaptations + three keepalives |
| Interface read or mut | 1 | 1 | 2 | 1 | 0 | 1/1 | One keepalive |
| Read on fresh interface result | 1 | 0 | 1 | 1 | 0 | 1/1 | Receiver transfers |
| Fresh Buffer owner, interface read | 1 | 1 | 2 | 1 | 1 | 2/2 | One keepalive |
| Returned sole Buffer owner, read | 1 | 3 | 4 | 1 | 1 | 2/2 | Adaptation + return Alias + keepalive |
| Original interface rebound during arguments | 2 | 1 | 3 | 2 | 0 | 2/2 | One keepalive protects the old object |

The complete expected arrays for all native cases are executable assertions in
`crates/aether-driver/tests/oop_v2.rs`.

## Performance observation (47)

Reproduce from repository root:

```sh
python3 compiler-next/tests/measure-oop-v2.py --runs 7
```

Each workload executes 10,000 iterations. The script asserts exact counters for
every run and reports process medians/ranges, ELF text bytes and remaining static
indirect-call sites in LLVM after the selected optimization profile. Timing
includes process startup and instrumentation; it is not isolated operation
latency. Witness-load and indirect-call event counts describe semantic lowering
before optimization; O2 may inline/devirtualize/eliminate actual instructions.
There is **no zero-cost abstraction claim**.

| Workload | Objects | Retains | Releases | Destroys | Buffer drops | Heap A/F | Method-slot loads | Release-slot loads | Semantic indirect calls | Wrappers |
| --- | ---: | ---: | ---: | ---: | ---: | --- | ---: | ---: | ---: | ---: |
| lvalue_adaptation | 1 | 10000 | 10001 | 1 | 0 | 1/1 | 0 | 10000 | 10000 | 0 |
| fresh_adaptation | 10000 | 0 | 10000 | 10000 | 0 | 10000/10000 | 0 | 10000 | 10000 | 0 |
| interface_alias | 1 | 10000 | 10001 | 1 | 0 | 1/1 | 0 | 10001 | 10001 | 0 |
| read_call | 1 | 10000 | 10001 | 1 | 0 | 1/1 | 10000 | 10001 | 20001 | 0 |
| mut_call | 1 | 10000 | 10001 | 1 | 0 | 1/1 | 10000 | 10001 | 20001 | 0 |
| final_release | 10000 | 0 | 10000 | 10000 | 10000 | 20000/20000 | 0 | 10000 | 10000 | 0 |

Event counts are identical at O0/O2. For read/mut workloads all 10,000 retains
are receiver keepalives. Final release includes fresh construction and private
Buffer allocation/cleanup; it is not an isolated release microbenchmark.

| Workload | Profile | ELF text bytes | Static indirect call sites after optimization | Median process ms | Range ms |
| --- | --- | ---: | ---: | ---: | --- |
| lvalue_adaptation | O0 | 3798 | 3 | 0.743 | 0.618–1.256 |
| lvalue_adaptation | O2 | 1836 | 0 | 0.623 | 0.549–0.803 |
| fresh_adaptation | O0 | 3750 | 3 | 0.78 | 0.704–1.206 |
| fresh_adaptation | O2 | 1729 | 0 | 0.591 | 0.51–0.855 |
| interface_alias | O0 | 3798 | 3 | 0.688 | 0.616–0.889 |
| interface_alias | O2 | 1819 | 0 | 0.62 | 0.534–0.856 |
| read_call | O0 | 3814 | 4 | 0.474 | 0.404–0.894 |
| read_call | O2 | 1910 | 0 | 0.443 | 0.341–0.699 |
| mut_call | O0 | 3814 | 4 | 0.507 | 0.434–0.743 |
| mut_call | O2 | 1830 | 0 | 0.62 | 0.338–0.795 |
| final_release | O0 | 4322 | 3 | 1.064 | 0.642–1.175 |
| final_release | O2 | 1743 | 0 | 0.37 | 0.328–0.802 |

These small, startup-dominated samples are descriptive and scheduling-sensitive.
Instrumentation is part of the reported executable size. Static site counts are
not dynamic call counts, and optimized devirtualization does not change source
ownership or witness semantics.

## Regression and remaining scope (items 48–53)

**48. Non-interface regressions.** The complete workspace covers V0–V33,
MATH-ARCH-1, LANGUAGE-PARITY-1 and OOP-V1, including scalar code, inline structs,
Buffer ownership and mathematical Matrix multiplication. All pass. Direct-class
emission has no interface dispatch/witness helpers when unreachable, and source
language boundaries outside this admission remain unchanged.

**49. Exact counts.** `cargo test --workspace`: **328 passed, 0 failed**
(baseline 316 plus 10 OOP-V2 integration tests and two frontend tests). The OOP-V1
integration suite remains 15 tests. OOP-V2's table iterations are separate from
Cargo test counts: 39 primary source negatives, 23 primary native positives,
five additional exact-signature positives, nine HIR operation mutations,
fifteen frontend metadata mutations, fourteen MIR operation mutations, thirteen
SSA operation mutations, thirteen metadata mutations in each of MIR/SSA and
one SSA phi mutation and one result-only SSA cleanup mutation. Module and
reachability cases are described above.
`cargo fmt --all --check`, `cargo clippy --workspace --all-targets -- -D warnings`
and `git diff --check` pass.

**50. Differential status.** `bash compiler-next/tests/run-differential.sh`:
**checked=21, failures=0**. Legacy and native expected exit/rejection outcomes
match the existing differential manifest.

**51. Accepted debt.** Carrier/witness layout and slot-zero release convention
are private Linux x86-64 bootstrap details. The shared ClassOp and historical
`contains_class` topology query now cover class-backed interface owners as well;
they do not turn interfaces into classes. Static per-class drop glue is reused;
there is no new object descriptor. Runtime qualification counters remain as in
OOP-V1; process timings include them. No optimization is required for correctness.
The source cannot currently express replacement of the original carrier during
argument evaluation because carrier-slot refs are excluded; this lifetime case
is therefore qualified by a verified MIR rearrangement and native execution.
The backend trusts VerifiedSsa and does not reverify arbitrary externally edited
LLVM. Unsupported raw pairing/wrapper/witness-release semantics are rejected by
representation and typed ownership checks rather than implemented as operations.

**52. OPEN DECISIONS.** Public ABI and cross-target thunk policy, interface
identity equality across different interfaces, graph/aggregate storage and cycle
policy, generic conformance, explicit interface-to-interface conversion and any
future interface inheritance/default-method model remain unadmitted. No behavior
for these is inferred from the private carrier layout. Existing trap/no-unwind
and single-thread ARC restrictions remain unchanged.

**53. Next milestone recommendation.** First consolidate this admitted subset
with a bounded optimization/verification milestone: study safe ARC elimination
and devirtualization against the exact ownership/keepalive counter corpus, and
extract the shared owner vocabulary if useful. Treat inheritance as a separate
future architecture/admission decision with its own lifecycle and override
contract; this implementation introduces none of it.
