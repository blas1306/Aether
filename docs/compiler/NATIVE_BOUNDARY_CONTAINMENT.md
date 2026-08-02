# Native boundary containment and exception hardening

Status: Milestone 6 implementation audit (2026-08-02)

This document records the fail-closed native policy implemented by
`NativeBoundaryVerifier`. It does not define an FFI, does not expose the private
runtime event ABI, and does not change source, Initial IR, lifecycle or SSA
semantics. The stable native capability profile continues to mark
`ERROR_HANDLING` unsupported; exception-bearing native programs remain available
only to internal tests.

## Boundary inventory

`SAFE` means the present implementation has a complete private contract.
`REJECTED` means the verifier diagnoses a representable unsafe form before LLVM
text is generated. `UNSUPPORTED` means there is no language/API form.
`REQUIRES FUTURE FFI` is deliberately not implemented by this milestone.

| Native boundary | Disposition | Containment and ownership |
| --- | --- | --- |
| libc, libm, LLVM intrinsics and POSIX calls | SAFE | Raw calls have no event parameter. They return ordinary values/status or enter a separate panic path. No event owner is transferred. |
| Embedded runtime helper calls | SAFE | Helpers are module-private and classified below. Only exception helpers and throwing interface thunks understand private events. |
| Generated `main` and POSIX process entry | SAFE | An event escaping Aether `main` is consumed by the private root reporter. The optional argc/argv wrapper calls a non-escaping internal program symbol. |
| Calling process `main` as a throwing function | REJECTED | `NBV-008`; process entry has no caller event-out slot. |
| Direct Aether call/invoke | SAFE | The target must be module-owned. `may_throw` targets use the private event-out convention; nonthrowing targets do not. |
| External/native `may_throw` invoke | REJECTED | `NBV-004`; foreign code cannot opt into Aether event transport. |
| Aether function values and indirect calls | SAFE | The current type system can construct function values only from module-owned Aether functions. Throwing indirect calls therefore retain compiler-owned private transport. |
| Conversion of function pointers to/from native code | REQUIRES FUTURE FFI | No provenance or callback adapter ABI exists. An internal boundary request rejects throwing/event-bearing forms. |
| Raw native callback into Aether | UNSUPPORTED | `NBV-002` for a throwing callback audit request; no public callback API is emitted. |
| Foreign callback returning an Aether event | REJECTED | `NBV-001`/`NBV-009`; the private event and its ownership cannot cross raw C. |
| Interface carrier construction and dispatch | SAFE | Witnesses, slot identities and thunks are canonical, private, versioned and module-owned. Throwing thunks use the private event slot. |
| Interface dispatch to a foreign/missing thunk target | REJECTED | `NBV-001`; every current thunk target must resolve inside the combined module. |
| Allocation and ARC helpers | SAFE | Failure/corruption is panic. Retain creates one owner; release/drop consumes one owner. No event is accepted. |
| String runtime | SAFE | Owned-result/borrowed-input rules are fixed; allocation, length and invariant failures panic. |
| Array/List runtime | SAFE | Bounds, size, allocation and ARC corruption panic. Ordinary methods cannot create an exception event. |
| Vector/Matrix runtime | SAFE | Bounds, shape and runtime corruption panic. Ordinary numerical results remain distinct from exceptions. |
| Text-file runtime | SAFE | Expected OS failures are `FileStatus`; malformed Aether storage remains panic. No event crosses POSIX. |
| Future callback placeholders in numerical APIs | REQUIRES FUTURE FFI | Aether-internal function values are supported. Passing one to native libraries requires a later containment adapter. |
| Compiler-generated equality/print/copy/drop/sort helpers | SAFE | Private helper families inherit the inventory below and have no raw event transport. |
| Public exception/error handle ABI | UNSUPPORTED | No symbols, layouts, creation, destruction or transfer rules are public. |
| Separate object/runtime boundary | REQUIRES FUTURE FFI | Current pointer identity and private symbols assume one combined LLVM module. |

## Runtime helper inventory

The executable registry is in
`src/aether/backend/llvm/native_boundary.py`. Each concrete/monomorphized helper
belongs to exactly one family and has exactly one exception behavior. Visibility
and ownership are independent facts; “public only” below describes external
system APIs, not an Aether public ABI.

| Helper family | Exception behavior | Visibility | Ownership rule |
| --- | --- | --- | --- |
| libc/libm/POSIX imports (`malloc`, `free`, stdio, files, math) | cannot throw | public only (external) | raw memory/status contract; never accepts an event |
| allocator, checked-size and ARC | may panic | internal only | allocation creates ownership; retain adds; release consumes |
| string construction, parsing, codec, split/trim/format | may panic | internal only | inputs borrowed unless named retain/release; returned strings owned |
| Array/List construction, growth, slice, index and sort | may panic | internal only | returned collections owned; element retain/drop is explicit |
| Vector/Matrix construction, index and arithmetic | may panic | internal only | collection owner remains explicit; inputs borrowed |
| text-file helpers | may panic | internal only | OS failure is status; successful read returns owned string |
| process context and argv snapshot | may panic | internal only | argv borrowed; snapshot returned owned |
| compiler-generated equality/print/copy/drop/nullable/class helpers | may panic | internal only | generated copy/retain/drop contract is type-directed |
| interface dispatch thunks | may throw Aether exception | internal only | receiver borrowed; event moves through the final private out-slot |
| `__ae_exception_{create,validate,borrow,matches,destroy,root_terminate}_v1` | may throw Aether exception | internal only | create owns, borrows do not own, destroy/root consume; invariant failure panics |
| panic and reporting helpers | may panic | internal only | `noreturn`; never creates a catchable event |
| native callback adapters | unsupported | unsupported | no transfer contract exists |

Semantic SSA builtins are individually registered as nonthrowing or panicking.
The verifier rejects any unclassified builtin (`NBV-010`), any helper marked as
throwing without private event transport, or any non-approved public helper.

## Backend verification and diagnostics

`LLVMBackend.emit` first runs the existing SSA verifier and then the native
boundary verifier, before calling the LLVM printer. It rejects:

| Code | Meaning |
| --- | --- |
| `NBV-001` | exception/event crossing a foreign boundary or interface thunk escaping the module |
| `NBV-002` | throwing raw native callback without containment |
| `NBV-003` | unsupported native invoke/boundary kind or transport |
| `NBV-004` | external invoke marked `may_throw` |
| `NBV-005` | private exception runtime ABI version mismatch |
| `NBV-006` | descriptor, concrete payload or canonical thunk identity mismatch |
| `NBV-007` | exception through a nonthrowing callback/function-pointer call |
| `NBV-008` | missing root/event-out containment, including invoking `main` |
| `NBV-009` | event ownership transferred to foreign code |
| `NBV-010` | absent or contradictory runtime-helper classification |
| `NBV-011` | private interface ABI/witness version mismatch |

These codes are internal verifier diagnostics because no current source form can
declare FFI/callback boundaries. If one reaches a public compiler boundary it is
reported as `ICE-NATIVE-BOUNDARY-001`, with the `NBV-*` detail retained as a
note. A future FFI feature must promote user-authored rejections to capability
diagnostics rather than treating them as compiler invariants.

## Event containment and panic separation

An owned event may exist only on verified exceptional SSA edges, in a private
event-out slot, or in the root reporter. libc, file, allocation, string and
collection calls never receive that slot. Interface thunks are accepted only
when compiler-generated and module-owned. Root reporting validates, borrows the
payload, reports, destroys the sole event and terminates.

Overflow, division, bounds, allocation failure, invalid size, ARC corruption,
event/descriptor corruption and ABI mismatch remain panic/fail-fast. Their
helpers have no exceptional successor and cannot enter a catch. File and parsing
status values likewise do not become `Error`.

## Runtime ABI and descriptor identity audit

The accepted private ABI remains version 1:

- event handles are opaque outside private exception helpers;
- the event header contains magic, ABI version, live state, canonical descriptor,
  owned carrier and original source location;
- a descriptor contains ABI version, full canonical source name and its canonical
  `Error` witness;
- an event has one linear owner; CFG/out-slot transfer moves rather than copies;
- carrier and witness borrows remain valid only while the event is live;
- destroy consumes the event and payload once; root reporting also consumes;
- event creation failure drops a transferred carrier before panic;
- required native alignment is provided by the allocator and canonical LP64
  erased-layout calculation; private structs are never exposed to C;
- every observing helper validates event/header/descriptor version and live state.

Exact matching by descriptor pointer is valid today because all source modules
and the embedded runtime are emitted into one LLVM module and the printer emits
one descriptor for each full canonical nominal ID. The symbol contains the full
UTF-8 ID encoded losslessly; its digest is readability only. Hash matching and
RTTI are not used. Conflicting struct/class identities, descriptor/payload
mismatch, missing witnesses and noncanonical thunks reject before LLVM.

## Separate compilation readiness

Separate compilation is not implemented. Current single-unit assumptions are:

- the module owns every callable Aether definition and interface thunk;
- throwing function-pointer values use a compiler-private signature without a
  separately versioned object ABI;
- descriptors and witnesses are unique because they are emitted once per
  combined module;
- descriptor pointer equality assumes no duplicate descriptor allocation;
- the exception runtime, live-event counter and fault hooks are emitted with the
  program and cannot disagree in version/layout;
- helper monomorphizations, class descriptors and string globals are resolved in
  one LLVM symbol namespace;
- root selection and generated `main` see the complete call/module model.

Before separate objects are accepted, a later design must specify coordinated
ABI versioning for callable/event/interface layouts; full-identity descriptor
coalescing or registration; COMDAT/linkonce/visibility rules; duplicate/conflict
diagnostics; linker retention and dead-stripping behavior; runtime symbol
ownership; object compatibility checks; and cross-DSO lifetime/thread rules.
The linker must reject incompatible versions and duplicate canonical IDs with
different layouts. Hash-only identity and best-effort linking remain forbidden.

## Remaining work before `ERROR_HANDLING`

The stable capability must stay disabled until the broader exception release
criteria are met, including supported-platform validation, public tooling and
diagnostic readiness, full optimization/capability parity, and a separately
reviewed FFI/callback containment ABI if native interoperation is introduced.
This milestone supplies containment proof and rejection policy; it does not by
itself authorize the capability.

