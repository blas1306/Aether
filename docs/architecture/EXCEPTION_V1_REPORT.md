# EXCEPTION-V1 — implementation report

Status: implemented and qualified for Linux x86-64 at O0/O2.

## Surface and core type

The admitted surface is `throw expression;`, `try { ... } catch (Type name) { ... }` with one or more ordered catches, and bare `throw;` inside a catch. There are no `throws`, `errors E`, checked exceptions, `finally`, generic exceptions, or new OOP surface.

`Exception` is a compiler-provided public `open class` with a public empty initializer. It is injected only for a program that uses the exception surface or derives from `Exception`; declaring another `Exception` is rejected. Throw and catch types must be concrete classes nominally derived from this core class. A catch covered by an earlier equal/base catch is rejected.

## Throw, catch, rethrow and ownership

HIR retains `Throw`, ordered `Try`/`HirCatch`, exact `ClassId`/`CatchId`, and `Rethrow`. A fresh class owner is `Transfer`; throwing an lvalue first creates the normal ARC `HandleAlias`. The native event owns the transferred payload until catch completion or root termination. A catch binding acquires its own alias, which follows ordinary lexical cleanup. Bare rethrow reuses the active event and payload; it neither allocates a replacement record nor consults TLS/global state.

Dynamic matching reads the payload's canonical class descriptor and accepts the exact class or a nominal base, in source catch order. `catch (Exception e)` therefore catches every Aether exception and no arithmetic, bounds, allocation, or ARC trap.

## Exceptional CFG and LLVM transport

MIR instructions that may throw carry an explicit `unwind` successor. MIR blocks identify landing pads and distinguish catch-dispatch pads from cleanup-only pads. `ExceptionEventId`, `ExceptionMatches`, `CatchBindAlias`, `EndCatch`, `Throw`, `Rethrow`, `ResumeUnwind`, and `ForwardUnwind` make event flow inspectable. Cleanup blocks are emitted before handler dispatch or propagation.

SSA preserves those normal/unwind edges and event identities. Call results exist only after the normal `invoke` continuation; the exceptional successor receives the event. MIR and SSA verifiers reject noncanonical/unknown events, invalid landing-pad predecessors, missing or spurious unwind edges, invalid throw classes, broken catch bindings, malformed forwarding, and invalid rethrow context in HIR.

The backend uses the Linux Itanium EH ABI as physical transport: LLVM `invoke`, `landingpad`, `resume`, `__gxx_personality_v0`, and the `__cxa_*` throw/catch/rethrow entry points. A small private record contains the Aether payload pointer; its destructor releases that payload. Matching remains Aether descriptor logic, not C++ RTTI semantics. The driver links `libstdc++` only when generated LLVM references the personality. Exception-free programs emit no Aether EH runtime, personality, landing pads, or `__cxa_*` references.

## Cleanup and root behavior

Exceptional pads execute compiler-authored cleanup for ordinary owning locals, Buffer owners, fully initialized class owners, and direct-method receiver keepalives. Drop flags preserve exactly-once behavior across normal and exceptional paths. Root catches only the transported Aether record, reports `unhandled Aether exception` to stderr, completes the event, and exits deterministically with status 70.

Throw/try/catch and potentially throwing direct or method calls are rejected inside `init` with E0436, because partial-construction rollback is intentionally not part of this vertical. Virtual and interface invokes in exception-enabled programs are rejected with E0437.

## Qualification

`crates/aether-driver/tests/exception_v1.rs` covers exact and base catches, source ordering/unreachable catches, fresh Transfer, lvalue Alias, propagation through two direct frames, nested catch plus bare rethrow to an outer handler, Buffer/class cleanup, direct-method receiver cleanup, deterministic unhandled root, non-catchable traps, malformed MIR/SSA event metadata, invalid source forms, O0/O2 native execution, and zero EH emission for an exception-free program. `tests/programs/exception_v1_smoke.ae` is the compact native fixture.

The full workspace tests, rustfmt check, clippy with warnings denied, diff check, and differential suite are the release gates for this report.

## Deferred decisions

Constructor unwind/partial rollback, `finally`, virtual/interface/indirect invokes, generic exceptions, async/threads, user destructors, public FFI, and diagnostic payload features such as messages, causes, or stack traces remain deferred. The private Itanium record and exit status 70 are implementation ABI choices for this bootstrap vertical, not a public Aether ABI.
