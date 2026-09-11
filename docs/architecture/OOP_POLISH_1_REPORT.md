# OOP-POLISH-1 — immediate-base calls and exact class devirtualization

Status: **IMPLEMENTED / QUALIFIED**, native Linux x86-64 bootstrap, 2026-09-10.
OOP-V1 remains authoritative for class identity and ARC, OOP-V2 for interface
carriers, OOP-V3 for inheritance/slots/dynamic destruction, and OOP-OPT-1 for
the verified physical optimization boundary. This milestone adds no other OOP
feature.

## What was implemented

Derived instance methods may use `base.method(arguments)`. Resolution selects
the implementation visible on the immediate base class and invokes that exact
implementation directly. For a virtual method this deliberately bypasses the
dynamic descriptor; in a three-level hierarchy a call in C selects B's override
when B overrides the slot, or the inherited A implementation otherwise.

`base` is not a value. It cannot be assigned, stored, returned, passed, borrowed
or converted. Base calls are unavailable outside derived methods and during
initialization. Private base methods remain private to their declaring class.
A mut target requires a mut current receiver; read calls do not grant mutation.

OOP-OPT-1 now also devirtualizes class `VirtualCall` instructions when the
existing provenance fixed point proves `Exact(ClassId)`. The proof uses no
implementer count, finality inference or closed-world dispatch assumption.

## HIR, MIR and SSA representation

`ClassOp::BaseMethodCall` carries:

- the current derived `ClassId`;
- its immediate base `ClassId`;
- the exact method declaration/instance identity;
- `Option<VirtualSlotId>` from the selected method;
- the current borrowed receiver and source-ordered arguments.

HIR resolves these facts before lowering. MIR maps the declaration target to
the exact `InstanceId`; SSA preserves the same operation as an ordered effect.
All three verifiers independently reconstruct the immediate-base relation,
effective target, slot, method signature, result type, visibility, receiver
read/mut capability and argument ownership.

Unlike an ordinary dot call, `BaseMethodCall` does not create a
`ReceiverKeepalive`, handle Alias/Transfer, `ClassUpcast` or receiver cleanup.
It passes the current borrowed `this`. The caller of the enclosing method
already owns the keepalive that spans the whole method body, including
left-to-right evaluation of the base-call arguments and the nested call. MIR
therefore consumes owning arguments normally but never consumes or drops the
base-call receiver.

LLVM lowers `BaseMethodCall` to a typed direct call of the verified symbol. It
does not load the object descriptor or virtual slot and emits no retain/release,
upcast, wrapper or base allocation for the operation.

## Exact class provenance and physical dispatch

The pre-existing lattice remains `Bottom | Exact(ClassId) | Unknown`:

| SSA source/join | Result |
| --- | --- |
| allocation/publication of Dog | `Exact(Dog)` |
| Alias, Transfer, upcast or receiver keepalive | preserves input |
| Dog / Dog phi, including loop backedges | `Exact(Dog)` |
| Dog / Cat phi | `Unknown` |
| exact / Unknown phi | `Unknown` |
| class parameter or opaque result | `Unknown` |

For a `VirtualCall`, only `Exact(C)` plus its preserved `VirtualSlotId` may
select `virtual_implementation(C, slot)`. The physical request records slot,
exact class and exact target `InstanceId`. The logical `VirtualCall` remains
unchanged, so receiver capability, arguments, result, ownership and keepalive
are still checked by the ordinary SSA verifier. `optimize_oop` derives requests
on raw cloned SSA and calls the full `verify_ssa` boundary again. The physical
verifier recomputes current provenance and rejects stale or fabricated requests.

At LLVM lowering, an admitted class decision calls the effective override
directly using the same receiver and arguments. Unknown calls retain descriptor
load, slot load and indirect invocation. Interface devirtualization and ARC
elision keep their OOP-OPT-1 behavior.

## Devirtualized and non-devirtualized cases

Devirtualized at O2:

- a fresh Dog transferred/upcast to an Animal local;
- Alias/Transfer/keepalive chains preserving exact Dog provenance;
- Dog/Dog conditional phis;
- virtual read and mut calls, including Buffer argument/result contracts already
  covered by the OOP-V3/OOP-OPT suites.

Kept indirect:

- an Animal by-value parameter, even when every current caller passes Dog;
- opaque class results;
- Dog/Cat and exact/Unknown phis;
- any Bottom fact while the fixed point is unresolved.

## Qualification and corruptions

Positive base-call qualification covers a nonvirtual immediate-base method, a
virtual base implementation bypassing the derived override, three-level
selection of the immediate base override, and read/mut receiver capability.
The three reusable programs are
`oop_polish_1_base.ae`, `oop_polish_1_multilevel.ae` and
`oop_polish_1_mut.ae`. Native counter assertions prove that the nested base call
adds no retain/release; only ordinary outer calls contribute keepalive ARC.

Eight added source negatives reject outside-method use, initializer use, a root
class without a base, private-base access, read-to-mut escalation, storage,
return and argument passing of `base`.

Independent malformed-IR qualification includes:

- HIR: wrong immediate base ClassId and wrong method identity;
- MIR: wrong immediate base ClassId and wrong target InstanceId;
- SSA: the same two independent target corruptions;
- OOP optimization: wrong override target, wrong VirtualSlotId and a stale Dog
  decision copied onto an otherwise valid Cat-provenance graph.

The Unknown parameter and mixed Dog/Cat phi tests also inject no decision and
verify that emitted LLVM stays indirect. Dog/Dog verifies exact-join behavior.

## O0 and O2

O0 retains semantic virtual class dispatch and inspectable ARC, except that
`base.method` is intrinsically direct at every profile. O2 runs the extended
OOP-OPT pass, re-verifies SSA and emits direct class calls only for exact
provenance. Base-call programs and exact/Unknown/mixed dispatch programs execute
under clang O0 and O2; driver O0 and O2 profiles are both exercised.

Qualification results:

| Command | Result |
| --- | --- |
| `cargo test --workspace` | 358 passed, 0 failed, 0 ignored |
| OOP-V3 integration | 16 passed |
| Frontend unit tests | 50 passed |
| `cargo fmt --all --check` | pass |
| `cargo clippy --workspace --all-targets -- -D warnings` | pass |
| `git diff --check` | pass |
| `bash compiler-next/tests/run-differential.sh` | checked 21, failures 0 |

## Unchanged behavior and remaining debt

Dynamic destruction is unchanged: every final class/interface release still
loads the concrete descriptor destruction target and drops the complete derived
object. Base calls do not create a separately destructible subobject or alter
strong counts.

The provenance analysis remains function-local and does not summarize returns
or specialize parameters. Unknown and mixed values remain indirect. ARC
elision retains its existing same-block/conservative limitations. Physical
descriptor tables and bootstrap ABI remain private.

Still unimplemented: protected, explicit abstract/sealed/final, RTTI/downcasts,
class graph fields, generic classes, user destructors, exceptions and
nullability. No behavior for those features is inferred from this milestone.
