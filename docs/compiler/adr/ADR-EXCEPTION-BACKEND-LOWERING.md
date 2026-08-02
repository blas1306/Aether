# ADR: Exception Backend Lowering Strategy

Status: Accepted

## Context

Verified SSA already contains complete normal and exceptional control flow,
compiler-generated cleanup, exact matching, edge-defined normal/event values and
linear event ownership. This ADR selects only the private machine transport. It
does not alter the frozen source, Initial IR, lifecycle or SSA contracts.

Authority:

- `docs/compiler/EXCEPTION_ARCHITECTURE_RESOLUTION.md`
- `docs/compiler/EXCEPTION_IMPLEMENTATION_PLAN.md`, Milestones 7 and 8
- `docs/compiler/exceptions/EXCEPTION_FROZEN_SEMANTICS_CHECKLIST.md`
- `docs/compiler/adr/ADR-EXCEPTION-SSA-REPRESENTATION.md`

## Decision

Aether selects **exception event out-slot plus explicit CFG** for the initial
private native lowering.

A `may_throw` Aether function other than process `main` receives one final
private `ptr %__ae_exception_out` parameter. The caller initializes that slot to
null. A normal return leaves it null and transports the ordinary result through
the existing LLVM return value. Exceptional return stores the sole owned event
in the slot and returns an unspecified zero/null/`zeroinitializer` value of the
ordinary return type; that value is unavailable on the verified exceptional
edge. Thus slot nullity is the private status result without adding a second
source-visible result.

The caller loads the slot and branches to the SSA normal or exceptional
successor. Direct invokes call the known private signature. Indirect invokes use
the corresponding internal function-pointer signature. Interface invokes call a
private thunk whose final slot follows the same rule. Struct `MethodResult`,
ordinary aggregate returns and constructors retain their existing target ABI;
only the private event slot is added to calls proven `may_throw`. Recursion and
mutual recursion need no special state. No global or TLS current event exists.

Functions and call sites proven nonthrowing keep the ordinary call ABI. `main`
contains an escaping event at the process root and invokes private root
termination rather than exposing a throwing C entry point.

Every module is verified by `SSAVerifier` immediately before LLVM printing. The
backend consumes SSA cleanup blocks exactly as supplied; it does not synthesize,
discover, reorder or repair ownership cleanup.

The Itanium LLVM EH implementation remains isolated behind
`LLVM_EH_PROTOTYPE` for internal comparison tests. It is not a production
transport or a fallback.

## Strategies prototyped

### Event-out

- Operations: pack, exact/root match, payload borrow, destroy, throw, rethrow,
  propagation, root termination and direct/indirect/interface invoke.
- Event: opaque `ptr` owned by exactly one SSA edge or private out-slot.
- Ordinary result: existing LLVM return, including aggregates and
  `MethodResult`.
- Exceptional result/status: non-null event out-slot; ordinary return is ignored.
- Runtime: private allocator/lifecycle/descriptor/root helpers only.
- Containment: transport is explicit and cannot unwind through raw C.
- Temporary limitation: private signatures and descriptors exist in one combined
  LLVM module; separate object ABI and public callbacks are not supported.

### LLVM EH prototype

- Operations: the same event operations and verified cleanup CFG.
- Transport: `__cxa_allocate_exception`/`__cxa_throw` carries the original event;
  callers use LLVM `invoke`, `landingpad`, `__gxx_personality_v0`,
  `__cxa_begin_catch`/`end_catch`, and `resume` for foreign exceptions.
- Direct, indirect and interface invoke, constructors, aggregate returns,
  recursion and root containment execute in the comparison corpus.
- The platform unwinder transports only the opaque event. It does not discover
  Aether owners; explicit SSA cleanup remains authoritative.
- Target assumptions: demonstrated only for the Itanium C++ ABI on Linux x86_64
  and linked against `libstdc++.so.6`. Windows funclets/SEH were not implemented.
  No macOS, ARM64 or WASI result is claimed.
- Temporary shortcuts: C++ `void*` type information is used as a transport tag;
  the prototype has no supported separate-compilation, foreign adapter or public
  callback boundary.

Status-value aggregates, CPS/dual continuations, and `setjmp`/`longjmp` were
reviewed but not implemented because neither supplied a correctness or
portability advantage over the explicit out-slot prototype. `setjmp` would also
introduce handler-registration state that the selected design does not need.

## Shared corpus and correctness

Both prototypes are emitted from the same `SSAModule` object after verification.
The shared native corpus covers:

- normal calls and direct, indirect and interface invokes;
- exact struct/class catches, ordered catches and `Error` catch-all;
- nested handlers, sibling skipping, nested rethrow and replacement events;
- propagation through several frames, recursion and mutual recursion;
- successful and failing struct/class construction and partial initialization;
- `Array`, `List`, interface and nullable owned fields;
- struct snapshots, class identity, `MethodResult` and aggregate returns;
- root-unhandled reporting, reporting failure and panic bypass.

The accepted Initial IR and SSA suites retain the source/IR/SSA observations for
the same semantic categories. Native comparison asserts equal exit status,
stdout and stderr for both transports at O0/O1/O2. ASan/LSan/UBSan runs cover
nested managed ownership, constructor rollback, replacement/rethrow, root
destruction and both transports. No selected-catch, ordering, identity,
snapshot, owner-count, cleanup, continuation, root or panic divergence was
observed.

Fault injection covers event allocation, descriptor lookup, `message()` and
root reporting. A pre-event fault drops the transferred carrier before fail-fast
termination. Reporting faults destroy the root event once and do not recursively
throw. The allocator's existing fail-fast path covers payload allocation
failure. ABI mismatch is rejected before emission. Repeated creation/rethrow,
deep propagation and high-volume creation execute without sanitizer findings.

## Performance and code generation

Raw commands, every timing sample, object sizes and outputs are retained in
`docs/compiler/exceptions/EXCEPTION_BACKEND_COMPARISON_2026-08-02.json` and are
reproducible with:

```text
PYTHONPATH=src .venv/bin/python scripts/compare_exception_lowering.py --runs 9
```

Environment: Linux 7.0.0 x86_64, Ubuntu Clang 21.1.8, Python 3.14.4. Timings are
wall-clock engineering samples, not statistically controlled benchmarks.

| corpus | opt | event-out run ms | EH run ms | event-out object | EH object | event-out executable | EH executable |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| normal | O0 | 5.078 | 3.198 | 13,960 B | 15,560 B | 20,960 B | 21,600 B |
| normal | O1 | 0.553 | 1.287 | 2,672 B | 2,728 B | 16,224 B | 16,232 B |
| normal | O2 | 0.562 | 1.443 | 2,184 B | 2,240 B | 16,176 B | 16,184 B |
| exceptional | O0 | 0.608 | 3.385 | 14,032 B | 15,656 B | 20,968 B | 21,608 B |
| exceptional | O1 | 0.660 | 3.215 | 2,680 B | 9,256 B | 16,232 B | 17,072 B |
| exceptional | O2 | 0.715 | 3.286 | 2,184 B | 9,008 B | 16,176 B | 17,072 B |

Event-out emitted 43 functions and 8 exception helpers; EH emitted 44 and 9.
Event-out LLVM was 44,184/44,821 bytes for the normal/exceptional probes; EH was
45,506/46,150. Clang compile medians are recorded separately from link medians.
Register pressure was not measured reliably; emitted shape shows one caller
alloca plus load/test on throwing calls for event-out, versus EH tables and
landing-pad trampolines for EH. Performance did not override correctness.

## Portability and maintenance

Only Linux x86_64 is demonstrated.

- Linux ARM64 and macOS ARM64: event-out is strongly supported by architecture
  because it requires only ordinary target calls and pointer-sized slots; the
  complete Aether runtime has not been tested there. Itanium EH is plausible but
  depends on each platform's personality/unwinder/linker details.
- Windows x86_64: event-out is strongly supported by architecture, subject to
  the rest of the runtime. The EH prototype is not portable because Windows
  requires funclets/SEH rather than these landing pads.
- WASI/targets without unwind: event-out is architecturally viable; the process,
  allocation and diagnostic runtime still require target ports. Native EH is
  unavailable or speculative.

Event-out avoids personality functions, unwind tables, C++ runtime linkage and
LLVM-version-sensitive EH forms. It maps directly to the already explicit SSA
CFG, is easier to verify, and gives one coherent transport on unwind and
non-unwind targets. Native EH can provide good debugger unwind stacks, but adds
platform-specific lowering, foreign-exception containment and a larger test
matrix without removing Aether's explicit cleanup.

## Runtime and FFI implications

The selected transport uses the private versioned event ABI in
`ADR-EXCEPTION-RUNTIME-ABI.md`. Symbols, layout, sentinel returns and out-slot
placement are not public ABI.

Raw imports and runtime helpers are nonthrowing in the Aether exception model and
never receive an event slot. The process root consumes any escaping event.
Invoking process `main` as a throwing callable is rejected. There is currently no
public export/callback exception ABI; paths that would expose an event through
raw C remain unsupported until the FFI milestone supplies explicit containment.

Foreign native exceptions are not Aether events. The rejected EH prototype
resumes them only inside its test domain; production event-out code neither
catches nor creates foreign unwinds.

## Fail-closed and panic contract

Before emission the verifier and printer reject malformed/unverified SSA,
call/invoke effect mismatches, missing or aliased successors, wrong edge
arguments, invalid event types/uses/dispositions, malformed catch entries,
descriptor inconsistency, runtime ABI mismatch, unsupported lowering strategy
and a known raw-C escape through process entry. Unknown public FFI/callback
transport is unsupported rather than emitted best-effort.

Overflow, division, bounds, invalid size, allocation and ARC invariant helpers
remain panic operations with no exceptional successor. Exception-runtime ABI or
internal failures call a distinct fail-fast path. Potentially throwing Aether
functions are not marked `nounwind`; panic/exit helpers are `noreturn` where
required. Catches cannot intercept either path.

## Consequences

- Event-out is the single production native exception transport.
- The LLVM EH code remains test-only comparison evidence and may be removed when
  maintaining it no longer pays for its evidence value.
- Cleanup correctness remains exclusively upstream of LLVM.
- Stable native `ERROR_HANDLING` remains unsupported; internal tests bypass the
  capability gate explicitly.
- Separate compilation, stable objects, public FFI handles and callback wrappers
  remain later milestones.
