# ADR: Private Exception Runtime Event ABI

Status: Accepted

## Context and scope

The compiler and embedded native runtime need one private contract for opaque,
linearly owned exception events. This ADR defines that contract for the accepted
event-out backend. It is not a public C ABI, object-file compatibility promise or
source-language representation.

The authority is the frozen exception architecture, the accepted Initial IR/SSA
ADRs and `ADR-EXCEPTION-BACKEND-LOWERING.md`.

## Version and representation

The compiler and runtime use private exception ABI version 1. The current runtime
is emitted into one combined LLVM module, so compiler/runtime version mismatch is
checked before emission. Event and descriptor headers also contain version 1 and
are validated at every runtime entry that observes an event.

The logical private layouts are:

```text
descriptor v1 = { abi_version, canonical source name, Error witness }
event v1      = { magic, abi_version, live_state, descriptor, owned carrier,
                  original line, original column }
```

The carrier is a compiler-owned erased box for a struct `Error`, the existing
class reference for a class `Error`, or the carrier selected from an owned
`Error` interface value. Struct boxing preserves an owned snapshot; class
carriers preserve object identity. Source code and public FFI never observe
these fields.

Live state is private diagnostic hardening. State 1 is live and state 2 is
consumed. A private live-event counter and fault mask support tests; neither is
semantic state or a public symbol.

## Canonical descriptor identity

Exact matching uses descriptor pointer equality because the current compiler
combines all source modules into one LLVM module and emits exactly one descriptor
per canonical nominal ID. Separate object compilation is not supported by the
current native ABI.

The private descriptor symbol contains the byte length and complete UTF-8 nominal
ID encoded as hex. A SHA-256 prefix is only a readability/linker aid; it is never
used alone for identity. Consequently distinct nominal IDs cannot collide even
if their digest prefixes collide. The descriptor also points to the one canonical
`Error` witness selected for that nominal type. Conflicting struct/class identity,
missing witnesses and descriptor/payload disagreement fail before emission.

If separate compilation or a loadable runtime is introduced, it must first
guarantee link-time coalescing/registration of one canonical descriptor or adopt
another collision-safe full-identity comparison. Hash-only matching is forbidden.
Objects from the unsupported model must not be linked best-effort.

## Logical operations

All handles below are private opaque pointers. `owned` is a linear precondition;
`borrowed` is valid only while its event remains live. Allocation or internal
failure panics/fails fast and never creates another catchable event.

| operation / current helper | arguments and preconditions | return / ownership postcondition | allocation and failure behavior |
| --- | --- | --- | --- |
| pack owned struct Error / compiler box + `__ae_exception_create_v1` | canonical descriptor, owned or copied struct carrier, original line/column | one owned live event; carrier ownership moves into it | allocates erased carrier and event; carrier/event allocation failure is panic; an injected pre-event fault drops the carrier first |
| pack owned class Error / retain-or-move + `create_v1` | non-null class implementing `Error`, matching descriptor | one event owns that class reference and preserves identity | event allocation only; copy form retains before transfer; failure drops the transferred reference before fail-fast |
| pack owned interface Error / witness selection + `create_v1` | owned non-null interface carrier/witness | one event owns carrier and selected canonical dynamic descriptor | interface copy adapter may allocate; unknown/null descriptor or bad witness fails fast |
| validate / `__ae_exception_validate_v1` | purported borrowed live event | `void`; ownership unchanged | no allocation; null, magic/version/state/descriptor failure terminates through private panic |
| canonical exact match / `__ae_exception_matches_v1` | borrowed live event and canonical expected descriptor | `i1`; both remain borrowed | no allocation; validates event; exact pointer equality only |
| `Error` catch-all | borrowed verified event | compiler emits true for non-null valid event | no runtime allocation or ownership change; only `Error` may request catch-all |
| payload borrow / `borrow_carrier_v1`, `borrow_witness_v1` | borrowed live event after successful exact/root match | borrowed carrier, and witness for interface catch; no new owner | no allocation; invalid event fails fast |
| event transfer | one owned event on a verified SSA edge | same sole owner on successor | no runtime call or allocation |
| rethrow | active catch-owned event | same event/provenance transferred to outer exceptional continuation | no repack, retain, copy, allocation or helper call |
| destroy / `__ae_exception_destroy_v1` | one owned live event | payload/carrier dropped exactly once, event consumed and freed | no allocation; counter underflow/state/ABI corruption fails fast |
| outward propagation | owned event at function exceptional exit and valid private event slot | stores event in caller slot; callee has no owner afterward | no allocation; ordinary result is invalid on this edge |
| root report / `__ae_exception_root_terminate_v1` | sole owned event escaping `main` | no return | validates, borrows canonical name/carrier, invokes semantically non-throwing `Error.message()` once, writes the frozen diagnostic to stderr, releases message, destroys event and exits 1 |
| root reporting failure | sole root event | reporter-detected failure destroys the event and terminates; a panic inside `message()` terminates immediately under the panic contract | no recoverable return, second `Error`, or recursive exception handling |
| compiler/runtime version check | requested ABI version | printer construction succeeds only for v1 | mismatch rejects before LLVM emission |
| runtime internal failure / `__ae_exception_panic_v1` | none or invalid private state | no return | writes the private invariant panic and exits 1; never packs/catches an event |

Logical transfer, rethrow and propagation deliberately have no convenience
runtime helper: the verified CFG and selected event-out convention already
perform the ownership move. The runtime never scans the stack or invokes
language-level matching policy.

## Root behavior and provenance

The root owns the only live event after all compiler-generated frame cleanup has
run. It validates the descriptor, borrows the dynamic canonical source name and
payload, calls the approved non-throwing `Error.message()` dispatch, writes exactly:

```text
Aether unhandled exception: <canonical-type>: <message>\n
```

to stderr, releases the returned string, destroys the event once and exits 1.
The original positive line/column are stored at pack time and survive rethrow and
propagation; the frozen release diagnostic does not currently print them.

An injected message/report failure is checked before output so the fault result is
deterministic. Actual stream failure may occur after a partial host write; the
runtime still releases any message, destroys the event and enters fail-fast
termination. It never retries by throwing. A source-produced throwing
`message()` is rejected semantically, and malformed internal `may_throw`
witnesses are rejected before LLVM emission. Root reporting therefore has no
second-event containment path.

## Panic separation and attributes

Packing, matching and destruction invariant failures; allocation failure; ABI
mismatch; and reporting corruption enter fail-fast panic, never exception
propagation. Existing overflow, division, bounds, invalid-size, allocator and ARC
panic helpers have no event-out slot or handler edge. Catches therefore cannot
intercept them.

`exit`, root termination, event EH raise in the rejected prototype and private
panic are `noreturn`. No potentially throwing Aether function is declared
`nounwind`. The semantically non-throwing concrete `Error.message()` target,
its witness thunk and the root dispatch call are `nounwind`; they are not
`willreturn` because panic remains possible. Runtime match/borrow/destroy helpers
are not given speculative
`readnone`, `readonly` or `willreturn` attributes that would hide validation or
panic behavior.

## Native boundaries and privacy

Every ABI symbol and layout in this ADR is private to the emitted module. Raw C
runtime calls cannot receive or propagate an Aether event. Process root consumes
the event before returning to C. Throwing process entry calls are rejected.
Throwing exports, C callbacks, separately compiled objects and a stable public
error handle are unsupported until the later FFI milestone defines containment.

The ABI is collision-safe, opaque and versioned, but versioning is an internal
fail-closed guard rather than a compatibility promise. Future runtime extraction
may change every helper name and layout under a coordinated version change.

## Validation evidence

The native suite covers struct/class/interface packing, exact/root match, borrow,
destroy, propagation, nested and repeated rethrow, root destruction, constructor
rollback, managed payloads, O0/O1/O2, deterministic output and malformed ABI/
descriptor rejection. Both event-out and the comparison EH prototype pass the
same representative corpus under ASan with leak detection and UBSan.

Fault bits cover event allocation, descriptor lookup, message and root reporting.
The high-volume exceptional benchmark creates and destroys 2,000 events per run;
recursive tests propagate through multiple frames. Raw measurements and exact
toolchain commands are retained in
`docs/compiler/exceptions/EXCEPTION_BACKEND_COMPARISON_2026-08-02.json`.

## Consequences

- Event ownership remains explicit and linear from SSA through native execution.
- Runtime helpers do not duplicate cleanup policy or inspect Aether stacks.
- Pointer matching is accepted only for the current combined-module model.
- The rejected LLVM EH transport can reuse the same logical event operations in
  tests, but it is not part of the accepted calling convention.
- `ERROR_HANDLING` remains unsupported in the stable native capability profile.
- Public FFI, separate compilation, threading/task guarantees and capability
  promotion remain future work.
