# ADR: Exception Backend Lowering Strategy

Status: Proposed

## Context

Before native lowering, verified SSA will already contain complete normal and
exceptional control flow, explicit cleanup, exact matching operations, canonical
nominal identity, and linearly owned opaque events. The LLVM backend needs a
machine-level transport strategy that preserves that contract on every supported
target and optimization level.

This ADR selects implementation machinery only. Backend convenience cannot alter
source semantics, cleanup ordering, diagnostics, panic separation, or raw-C
containment.

Authority:

- `docs/compiler/EXCEPTION_ARCHITECTURE_RESOLUTION.md`
- `docs/compiler/COMPLETE_EXCEPTION_MODEL_RFC.md`, especially §§10–13
- `docs/compiler/EXCEPTION_IMPLEMENTATION_PLAN.md`, Milestone 7
- `docs/compiler/exceptions/EXCEPTION_FROZEN_SEMANTICS_CHECKLIST.md`

## Frozen constraints

- The backend consumes an already explicit, verified exceptional CFG.
- Lifecycle cleanup is compiler-generated before SSA; LLVM lowering does not
  discover owners or source handler scope.
- Matching is exact canonical nominal identity with `Error` as the explicit
  catch-all.
- Event ownership remains linear through calls, cleanup, catches, rethrow, and
  root propagation.
- Event representation and helper ABI remain private and opaque.
- Panic is fail-fast, uncatchable, and never converted to an event.
- The runtime never scans the stack for Aether owners.
- Exceptions never cross raw C frames.
- Direct, indirect, interface, constructor, runtime-helper, and callback-adapter
  call forms obey one semantic contract.
- Observable source behavior is identical across target-specific lowering
  strategies.

## Decision: Pending

The ADR must select and justify the strategy for the initial supported target
matrix, define any permitted target-specific variation, and identify its exact
dependency on the private runtime ABI before Milestone 7 implementation is
accepted.

## Candidate options

Only the strategy families studied by the approved RFC are candidates.

### Option A: LLVM `invoke` with landing pads or funclets

Use LLVM native exceptional control flow, a personality function, and
target-appropriate Itanium/DWARF landing pads or Windows funclets.

### Option B: Status-value lowering

Return an internal outcome containing either the ordinary result or an owned event,
then branch through explicit cleanup/handler CFG.

### Option C: Explicit dual-continuation/CPS lowering

Use separate normal and exceptional continuations under a compiler-owned calling
convention.

### Option D: Exception out-parameter plus explicit CFG

Return a small status while writing the owned event to a caller-provided slot;
retain the ordinary result or its own out parameter separately.

### Option E: `setjmp`/`longjmp`-style transport

Use runtime handler registration and nonlocal jumps only with a verified explicit
cleanup protocol and compelling target evidence.

No candidate is preferred by this template. The approved RFC requires prototypes
of at least LLVM EH and one explicit status/out-slot strategy before selection.

## Evaluation criteria

1. Correctness under the full frozen-semantics checklist.
2. Sanitizer results and leak/double-destroy/use-after-free evidence.
3. Linux x86_64 and the next planned target, including platform EH differences.
4. Normal-path cost, throw-path cost, code size, and register pressure.
5. Direct, indirect, recursive, interface, constructor, callback, and aggregate
   return behavior.
6. Cleanup ordering and event ownership under nested/rethrown/unhandled paths.
7. Optimization stability at clang/LLVM `-O0`, `-O1`, and `-O2`.
8. LLVM verifier compatibility and resistance to incorrect `nounwind`/attribute
   assumptions.
9. Debug stack quality and source-location reporting.
10. FFI containment and proof that no raw C frame observes propagation.
11. Portability to targets without native unwind support.
12. Calling-convention, separate-compilation, and tail-call implications.
13. Runtime ABI complexity, versioning pressure, and avoidance of an accidental
    public ABI.
14. Deterministic root termination and panic separation.

## Consequences

Pending the decision:

- No exception-bearing backend path is approved.
- Runtime prototypes may gather evidence but cannot establish source semantics or
  a stable ABI.

After approval:

- LLVM lowering, runtime event operations, native tests, and target documentation
  must implement the selected contract together.
- A target-specific alternate strategy is permissible only when the ADR defines
  the compatibility boundary and tests prove identical source behavior.
- The selected calling convention and helpers remain private implementation
  details.
- M9 FFI wrappers must contain the chosen transport before entering raw C.

## Validation requirements

- The same verified SSA corpus lowered through LLVM EH and at least one explicit
  status/out-slot prototype.
- Structural LLVM tests for calls/invokes, both successor kinds, handler dispatch,
  cleanup, event transfer, rethrow, and root paths.
- Native reference/IR/SSA parity at O0/O1/O2.
- All call forms, returns, loops, constructors, interfaces, collections, partial
  initialization, nesting, and repeated rethrow.
- Malformed-IR rejection; backend must not repair invalid ownership or CFG.
- Cross-platform/toolchain matrix and repeated-build determinism.
- Panic-bypasses-catch tests.
- Raw-C containment harnesses or fail-closed boundary tests.
- Debugger/stack and sanitizer evidence used in the candidate comparison.

## Decision deadline / owning milestone

**Deadline:** before exception-bearing LLVM/backend lowering is merged.

**Owning milestone:** **Milestone 7 — LLVM Backend**.
