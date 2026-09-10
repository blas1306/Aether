# OOP-OPT-1 — ARC elimination and interface devirtualization

Status: implemented and qualified on Linux x86-64, 2026-09-10. This is an
internal optimization milestone. OOP-V1/V2 source semantics, accepted/rejected
programs, diagnostics, receiver capabilities and cleanup authority are unchanged.
No frontend, source-language contract or charter admission changes are needed.

## Scope and implementation boundary (requested items 1–6)

1. **Scope:** balanced local class/interface Alias and receiver keepalive ARC,
   plus exact-provenance interface method dispatch. Correctness still works at O0.
2. **Semantics:** lvalues remain Alias, fresh owners remain Transfer. Receiver
   evaluation precedes arguments; the same object stays alive through the call
   and cleanup boundary. Last-release destruction stays at its original point.
3. **Files:** the inventory below records implementation, qualification and docs.
4. **Phase:** after VerifiedSsa, before LLVM emission. `optimize_oop` clones to
   raw SSA, derives physical decisions, then calls `verify_ssa` to obtain a new
   immutable VerifiedSsa. O2 enables this pass and clang O2; O0 is the default.
5. **Semantic versus physical:** HandleAlias, ReceiverKeepalive, InterfaceAdapt,
   HandleTransfer, Move and Drop are logical ownership/lifecycle operations.
   There are no standalone semantic Retain/Release opcodes today. Their native
   RC calls are physical implementations. Logical instructions stay unchanged;
   `ArcElision { release, owner }` suppresses an acquisition and its paired
   physical cleanup. A verified direct dispatch decision changes the native
   call target while preserving the semantic InterfaceCall requirement.
6. **Shared-owner vocabulary:** retain distinct Class/Interface and keepalive
   TypeIds, ClassId/InterfaceId checks and whole carriers. Existing ClassOp already
   shares Alias/Transfer/keepalive vocabulary. The new small physical decision
   vocabulary is shared; a new erased `SharedOwner` semantic type would weaken
   clarity without removing useful duplication, so none is introduced.

| Area | Files |
| --- | --- |
| Analysis and verification | `compiler-next/crates/aether-middle/src/ssa/oop_opt.rs`, `ssa.rs`, `lib.rs` |
| Physical lowering | `compiler-next/crates/aether-backend-llvm/src/classes.rs`, `lib.rs` |
| Profiles and CLI | `compiler-next/crates/aether-driver/src/lib.rs`, `main.rs` |
| Tests | `compiler-next/crates/aether-driver/tests/oop_opt_1.rs`; extended rebinding fixtures in `oop_v1.rs`, `oop_v2.rs` |
| Programs | `compiler-next/tests/programs/oop_opt_1_{stable,unknown,mixed}.ae` |
| Measurement | `compiler-next/tests/measure-oop-opt-1.py`, `tests/timings/oop-opt-1.json` |
| Documentation | this report, `AETHER_COMPILER_ARCHITECTURE.md`, `compiler-next/README.md` |

This boundary deliberately retains semantic operations rather than replacing an
interface receiver with an ordinary owning class value. A physical request is
untrusted metadata, not a verifier exemption or a source ownership rewrite.
Backend emission consumes only VerifiedSsa and makes no new ownership inference.

## ARC proof and destruction (items 7–10)

7. **Analysis:** scan candidates deterministically in block/instruction order.
   The independent SSA ledger establishes that the source token is owned at the
   acquisition. The optimizer follows the new token through whole-value Move or
   HandleTransfer to one Drop in the same block. It requires every intervening
   use of the independent owner to be nonconsuming, and every use of the candidate
   to be borrowing or its exact tracked transfer. Calls with owning arguments,
   returns, phi edges, unrecognized operations and ordinary free calls prevent
   candidate elision. Source names and pointer equality play no role.
8. **Keepalive:** an owning class/interface SSA token must remain independently
   owned through receiver capture, argument evaluation, call and paired cleanup.
   Replacing/transferring/dropping that token before cleanup rejects the proof.
   Previously elided tokens, including their Move chains, cannot anchor another
   elision. Borrowed receiver tokens do not count as independent strong owners.
9. **Alias:** the same bounded rule applies to HandleAlias. The alias's own
   token must reach local cleanup without escape. A later Alias may still create
   a genuinely owned escaping token; removing a preceding local alias does not
   remove that return/argument acquisition. Interface adaptation retains are
   conservatively preserved. No Alias is rewritten as source Transfer.
10. **Destruction:** no instruction moves. At each omitted release, a proven
    physical owner still prevents count zero. Its eventual final release remains
    at the original semantic boundary, including recursive Buffer cleanup.
    Scalar loads/stores, calls, traps and other cleanup keep their order. Unknown
    operations fail closed. Abortive trap paths retain their no-unwind contract.

Strong-count checks also matter: removing a checked retain must not hide an
observable overflow trap. ARC elision therefore requires an acyclic complete
compilation call graph. Edges include ordinary calls, initializers, direct methods
and every possible implementation of each called interface requirement. With
no class graph storage, globals, FFI callbacks or escaping closures in OOP-V1/V2,
static SSA definitions/parameters times maximum call depth bound live strong
obligations below u64::MAX. Recursive programs retain ARC, including unreachable
recursion in this conservative implementation. This uses the currently admitted
complete source program only to bound ARC counts; dispatch never uses the number
of implementations. New storage, callback or external-call admission must revisit
this bound. Zero-count invalidity is excluded by the physical-owner proof.

## Provenance and devirtualization (items 11–22)

11. **Analysis:** a fresh, function-local SSA fixed point; no trusted persistent
    or serialized dynamic-class facts.
12. **Lattice:** Bottom (analysis not yet resolved), Exact(ClassId), Unknown.
    Bottom joins with its other input; equal exact classes remain exact;
    different exact classes or Exact + Unknown become Unknown. Bottom never
    authorizes a rewrite.
13. **Adaptation:** verified Class-to-Interface adaptation establishes Exact(C)
    from the final concrete source ClassId and its exact verified witness.
    ObjectAlloc and PublishObject also establish exact concrete identity.
14. **Alias/Transfer:** whole-value Move, HandleAlias, HandleTransfer and
    ReceiverKeepalive preserve provenance and both carrier components.
15. **Phi:** all actual incoming edges participate, including loop backedges.
    C/C joins remain Exact(C); C/D and C/Unknown joins remain Unknown. This does
    not track object identity across a phi, only dynamic class. ARC's independent
    owner proof remains separate.
16. **Invalidation:** every optimization and verification recomputes from the
    current graph. Replacement creates new SSA definitions; old captured receivers
    keep their own facts. Stale requested decisions are rejected.
17. **Precondition:** receiver provenance must be Exact(C); the requirement's
    exact InterfaceId/RequirementId must select its verified (C,I) witness slot
    and actual method InstanceId. InterfaceId or implementer count alone is
    insufficient. Parameters and opaque function results start Unknown.
18. **Direct rewrite:** physical dispatch extracts object component zero from
    the same receiver and directly calls the verified concrete method. The
    logical InterfaceCall remains for verification; there is no new source cast
    or fabricated class owner. Concrete class calls retain their original path.
19. **Read/mut:** ordinary SSA and witness verification recheck exact requirement
    and method receiver capabilities, argument/result types and signatures.
20. **Keepalive:** devirtualization itself changes no ownership decision; an
    unsafe keepalive remains physically retained even when dispatch is exact.
21. **Witness loads:** the exact call emits neither method-slot load nor indirect
    method call. This is visible before any LLVM optimization.
22. **Witness reachability:** unchanged. Witnesses remain needed for interface
    release and are not prematurely removed from semantic IR. No optional direct
    interface-release optimization was added. Release-slot loads/indirect calls
    may remain in glue even when all method calls devirtualize. No wrappers exist.

## Required ARC and dispatch cases (items 23–27)

R/L below are native retain/release events in straight-line cases (all allocate
one object). The optimized events execute correctly with both clang O0 and O2.

| Required case | Semantic R/L | Optimized R/L | Decision / reason |
| --- | ---: | ---: | --- |
| Class read, stable local | 1/2 | 0/1 | Elide keepalive; independent owner survives |
| Class mut, stable local | 1/2 | 0/1 | Same proof; mut is not exclusivity |
| Interface read, fresh C adaptation | 1/2 | 0/1 | Exact C, stable owning carrier |
| Interface mut, lvalue C adaptation | 2/3 | 1/2 | Elide keepalive; preserve adaptation Alias |
| Class alias + mutation + original read | 3/4 | 1/2 | Elide local alias and original's keepalive; alias-backed keepalive remains |
| Interface alias + mutation + original read | 3/4 | 1/2 | Same physical-owner restriction |
| Fresh class receiver | 0/1 | 0/1 | Transfer; final release preserved |
| Class lvalue parameter + local read | 2/3 | 1/2 | Caller Alias retained; callee's stable owning parameter anchors keepalive |
| Class lvalue return + caller read | 2/3 | 1/2 | Return Alias retained; caller keepalive removed |
| Nested Buffer interface owner + read | 1/2 | 0/1 | Final release still drops one Buffer and frees both allocations |
| Unknown interface parameter + read | 2/3 | 2/3 | No caller specialization; ARC and indirect dispatch preserved |
| Opaque interface return + read | 2/3 | 2/3 | Return Alias and unknown keepalive preserved |

**23–24. Class/interface coverage:** the table is executable qualification in
`physical_arc_cases_preserve_native_results_and_final_cleanup`. Additional tests
cover reference argument mutation, aggregate/Buffer/interface results and shared
receiver mutation during argument evaluation. Conservative unrecognized aggregate
construction/Buffer allocation in an argument interval can retain keepalive even
when method dispatch devirtualizes.

**25. Non-elision:** original-slot replacement during arguments preserves its
last-live keepalive in both authoritative OOP-V1/V2 MIR fixtures. A further fixture
replaces C with D while holding C's Buffer-backed receiver; it returns C's result,
retains the old receiver and destroys both objects and one Buffer exactly once.
It has no opaque argument call that could mask the ownership proof. Returning
or passing an Alias to a non-inlined call preserves that escaping obligation.
Aliases crossing branches retain ARC, including when the original is replaced
on only one path. Final class/interface releases and nested Buffer cleanup remain.
Unknown interface carriers conservatively retain ARC. Fresh receivers transfer.
No interprocedural/inlining ownership optimization is claimed.

**26. Devirtualized:** fresh and lvalue adaptations, read and mut requirements,
alias/transfer chains, C/C phis and loop phis carrying only C. A shared-object
argument mutation test observes 4 after incrementing to 2 and then adding 2,
proving receiver/argument order. Exact native phi cases return 7 and 9 on their
respective paths. Interface return provenance is not propagated across calls;
no locally inlined return exists in the current pipeline.

**27. Non-devirtualized:** C/D phis, C/D loop merges, C/Unknown phis, opaque
interface parameters and opaque interface returns. Even a sole current conformer
does not specialize an interface parameter. Native mixed dispatch returns 16
for 7 + 9. These calls are indirect in the SSA-lowered LLVM; clang may subsequently
prove additional opportunities using its own inlining and value analysis.

## Reverification and corruption (items 28–29)

28. **Boundary:** raw transformed SsaIr passes the complete ordinary verifier
    first: metadata, types, dominance, signatures, receiver/access protocols,
    CFG ownership and final cleanup. Then the physical verifier recomputes current
    ARC/provenance decisions and rejects any request outside that derived set.
    Valid subsets are allowed so another pass may conservatively discard requests.
    A pair is represented atomically, preventing independently selectable retain
    and release suppression. Repeated optimization is deterministic/idempotent.
29. **Corruptions:** 17 new independent raw-SSA mutations attempt final-owner
    keepalive removal, a wrong/unpaired release ID, a self-owned proof, release-only
    deletion, Alias acquisition changed to Transfer without matching ownership,
    wrong ClassId, wrong MethodId, wrong requirement and read-to-mut target,
    injected exact targets for five Unknown/mixed cases, replacement-slot class
    substituted for a captured receiver, stale target decisions after valid C-to-D
    replacement, and wrong concrete type on an interface cleanup token. All reject.
    Direct concrete interface release is not an admitted physical decision;
    corrupting the typed owner to force it is rejected by existing checks.

Logical SSA instruction graphs compare equal before/after optimization. A native
checkpoint probe verifies zero Buffer/object destruction after receiver cleanup
but before scope cleanup, and one destruction after scope cleanup. A maximum-int
interface mut call still traps on checked arithmetic at both middle-end profiles
and both clang profiles. Strong-header corruption tests in OOP-V1 remain unchanged.

## Emitted LLVM and measurement (items 30–38)

Reproduce from repository root:

```sh
python3 compiler-next/tests/measure-oop-opt-1.py --runs 7
```

[Raw measurements](../../compiler-next/tests/timings/oop-opt-1.json) include all
nine existing OOP-V1/V2 cost workloads and three focused programs. Profiles are
actual driver O0/O2, not just different clang flags on identical LLVM. Every
workload executes one warmup and seven measured instrumented invocations per
profile (192 total). Source results, object destruction, Buffer destruction,
heap balance and `release = allocations + retain` are asserted. Toolchain:
rustc 1.97.1, clang 22.1.8, Linux x86-64.

**30–34. Static sites before clang.** R/L count physical retain/release call sites
in source function bodies, excluding runtime glue definitions. M/W are indirect
method calls / method-witness loads. Last-release witness loads in glue are
separate; the JSON also records module-wide indirect sites and post-clang sites.

| Workload | O0 R/L | O2 R/L | O0 M/W | O2 M/W |
| --- | --- | --- | --- | --- |
| V1 alias_direct_keepalive | 3/5 | 1/3 | 0/0 | 0/0 |
| V1 allocate_alias_last_release | 1/2 | 0/1 | 0/0 | 0/0 |
| V1 nested_buffer_last_release | 1/2 | 0/1 | 0/0 | 0/0 |
| V2 final_release | 0/1 | 0/1 | 0/0 | 0/0 |
| V2 fresh_adaptation | 0/1 | 0/1 | 0/0 | 0/0 |
| V2 interface_alias | 1/2 | 0/1 | 0/0 | 0/0 |
| V2 lvalue_adaptation | 1/2 | 1/2 | 0/0 | 0/0 |
| V2 mut_call | 1/2 | 0/1 | 1/1 | 0/0 |
| V2 read_call | 1/2 | 0/1 | 1/1 | 0/0 |
| focused mixed | 1/4 | 1/4 | 1/1 | 1/1 |
| focused stable | 4/5 | 1/2 | 2/2 | 0/0 |
| focused unknown | 2/3 | 2/3 | 1/1 | 1/1 |

**35–36. Native events and cleanup.** V2 read/mut loops execute 10,000 retains
and 10,001 releases at O0, versus zero retains and one final release at O2.
Interface-alias loops have the same reduction. V1 allocate/alias and nested
Buffer loops remove 100,000 retains and 100,000 non-final releases each, retaining
100,000 final releases. Nested Buffer drops remain 100,000. V2 final-release
workload retains all 10,000 object/Buffer destructions and 20,000 heap frees.
Focused mixed/unknown programs preserve physical event counts; stable focused
calls reduce R/L from 20,002/20,003 to 1/2. All measured source exits are zero;
focused integration tests also validate nonzero computation results explicitly.

**37–38. Instrumented executable text bytes and process median milliseconds.**

| Workload | O0 text | O2 text | O0 ms | O2 ms |
| --- | ---: | ---: | ---: | ---: |
| V1 alias_direct_keepalive | 3532 | 1727 | 8.886 | 0.405 |
| V1 allocate_alias_last_release | 3308 | 1653 | 2.12 | 0.364 |
| V1 nested_buffer_last_release | 3980 | 1683 | 3.495 | 0.616 |
| V2 final_release | 4232 | 1699 | 0.669 | 0.357 |
| V2 fresh_adaptation | 3660 | 1685 | 0.497 | 0.389 |
| V2 interface_alias | 3708 | 1644 | 0.409 | 0.505 |
| V2 lvalue_adaptation | 3708 | 1775 | 0.665 | 0.409 |
| V2 mut_call | 3708 | 1644 | 0.426 | 0.395 |
| V2 read_call | 3708 | 1644 | 0.393 | 0.39 |
| focused mixed | 4756 | 2315 | 0.424 | 0.36 |
| focused stable | 3836 | 1660 | 0.522 | 0.419 |
| focused unknown | 3800 | 1998 | 0.588 | 0.415 |

These samples include startup, instrumentation, allocator and ordinary LLVM
optimization effects. They are descriptive, not isolated operation latencies or
a causal measurement of this pass alone. Some tiny O2 samples are slower than O0;
no zero-cost or universal speedup claim is made. Raw ranges are recorded in JSON.

Qualification counters still increment on actual emitted helpers. In the
unoptimized semantic-lowering path these equal the original semantic schedules;
O2 physical elision reduces them. The old expected semantic arrays are untouched,
and their tests still pass against raw lowering at clang O0/O2. Optimized SSA
retains logical ownership events for inspection; emitted site counts and the new
physical-event measurements explicitly distinguish the two notions.

## Regression, debt and next work (items 39–44)

39. **Non-OOP equivalence:** scalar arithmetic, inline structs, Buffer, generic
    identity, Matrix multiplication and main/comments produce byte-identical LLVM
    across middle-end O0/O2. No frontend or non-OOP lowering operation changes.
40. **Tests:** `cargo test --workspace`: 340 passed, zero failures. The baseline
    was 328; OOP-OPT-1 adds 12 tests. Its native tests perform 58 executions,
    including four expected arithmetic traps; the extended authoritative rebinding
    tests add four optimized executions. OOP-V1's 15 and OOP-V2's 10 tests keep
    their exact original semantic assertions. Workspace fmt and all-target clippy
    with warnings denied pass, as does `git diff --check`.
41. **Differential:** `bash compiler-next/tests/run-differential.sh` reports
    checked=21, failures=0. No intentional-difference classifications change.
42. **Accepted debt:** ARC stays within a basic block and does not optimize
    adaptation retains, escaping arguments/returns, recursive programs or unknown
    interface owners. No inlining or return summaries. An elided local alias
    cannot anchor another elimination, so its nested keepalive may remain.
    Candidate scans and fixed points favor simple auditable proofs over a general
    effect/MemorySSA framework. Witness constants and indirect release glue remain;
    no optional concrete-release or witness-pruning pass is implemented. Runtime
    qualification counters and carrier/glue ABI remain private bootstrap details.
43. **OPEN DECISIONS:** broader ARC across CFG edges needs path-sensitive physical
    owner tracking; recursive count bounds need call/effect summaries; inlining
    must invalidate and rederive all physical requests. Foreign callbacks, owner
    graph storage and concurrent ARC require new lifetime/count assumptions.
    Public ABI, graph/cycle/weak policy, generic sharing and inheritance remain
    independent language decisions, not consequences of this optimization.
44. **Recommendation:** next consolidate physical ownership across CFG joins and
    local call specialization with explicit effect summaries and the same
    revalidation contract. Any next source-level OOP expansion should separately
    design stored class/interface ownership and cycle policy before admission.
    This milestone adds neither inheritance nor new interface features.
