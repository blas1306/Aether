# Initial IR → Rust SSA lowering readiness

## Decision

`RUST_SSA_LOWERING_NOT_READY`

This is an audit result, not a change of authority or implementation. Initial IR
verification remains Rust-authoritative at RP3. No optimizer, backend, SSA
semantics, or Rust lowering code is changed.

The deterministic machine-readable record is
[`rust_ssa_lowering_readiness.json`](rust_ssa_lowering_readiness.json). Regenerate
or check it with:

```bash
python scripts/audit_rust_ssa_lowering_readiness.py
python scripts/audit_rust_ssa_lowering_readiness.py --check
```

## What Python does today

`GeneralSSABuilder` is the production construction path. For every function it
runs, in order: lifecycle expansion, CFG construction, entry-rooted dominators,
dominance frontiers, pruned Cytron phi placement, dominator-tree renaming, and
SSA verification. The input module is not mutated; lifecycle expansion and SSA
construction allocate replacement objects.

CFG construction retains the Initial IR block order. It recognizes jump and
branch edges, both normal and exceptional continuations of direct/indirect/
interface invokes, optional exceptional targets of throw/rethrow/propagate, and
no successor for return. Unreachable blocks are isolated by dominator analysis.
Phi insertion uses iterated dominance frontiers but prunes slots that are neither
live-in nor definitely initialized. Renaming uses per-slot stacks, value bindings,
a dominator-tree walk, collision-aware preferred names, sorted dominator children,
and deterministic block assembly. Phi operands remain predecessor-labelled.

The JSON inventory lists all 84 Initial IR instruction dataclasses and all 77 SSA
instruction dataclasses, including the six lifecycle pseudo-instructions which
must be normalized before direct renaming. It also freezes aggregate shape,
nominal struct, class/interface witness, erased-layout, function-value,
indirect-call, exception, source-location and transferred-storage fields.

## Purity and hidden state

The lowering is referentially deterministic for a valid module and does not
mutate it, so it is conceptually pure. The honest contract is nevertheless:

```text
lower(verified_initial_ir, lowering_policy_v1)
    -> verified_ssa | deterministic_error
```

`InitialIRModule -> SSAModule` hides required state: lifecycle rules, the
instruction-effect registry, the CFG terminator table, naming policy, and
verifier policy. It also hides a precondition: `GeneralSSABuilder` verifies its
output but does not verify Initial IR itself. The production caller must supply
verified Initial IR. These policies should be frozen/versioned or passed through
a construction context before parity work starts; they are configuration, not
mutable compilation state.

## Blocking findings

Rust has a complete Initial IR schema-v1 wire/importer and explicit SSA
schema-v1/schema-v2 DTOs. It does
not have an owned SSA model with phi semantics, a lowering entry point,
lifecycle expansion, lowering CFG, dominance-frontier analysis, phi insertion,
or renaming. Its existing dominance verifier is not a substitute for these
construction algorithms.

RUST-3.A1 closed the SSA wire defect: schema-v2 requires `bounds_checked` on all
eight affected collection/vector/matrix operations, and Python and Rust DTOs
dispatch versions explicitly. Effects remain Python behavior rather than a
serialized lowering contract, and debug metadata is only present on selected
instructions.

The corpus contains 144 files across examples, benchmarks, expense tracker,
numerical workloads, exceptions, structs/classes/interfaces, String/Array/List,
and function values. Of these, 116 reach verified Initial IR and Python SSA.
Initial IR DTO round-trip is lossless for all 116, as is SSA schema-v2 DTO
round-trip (116/116, 100.00%). No file has yet completed
the requested end-to-end Rust SSA path, so the demonstrated Rust round-trip rate
is 0/116 (0.00%). Negative exception fixtures and frontend/IR-unsupported legacy
examples remain in the denominator only as discovered corpus and are recorded
with their failure stage.

Category details and per-file evidence are in the JSON. Notable SSA-codec rates
are: exceptions 100%, function values 100%, structs/classes/interfaces 90%,
numerical workloads 50%, expense tracker 40%, and String/Array/List 30.30%.

## Future differential

Both lanes must begin with the same verified Initial IR DTO. The Python lane
builds Python SSA; the Rust lane imports that DTO, runs the future Rust lowering,
serializes Rust SSA, and imports it back into Python. Both results are verified
before comparison.

Comparison must not use accidental temporary names. Canonicalize reachable CFGs
from entry, match successor edges by kind and structural destination, then
alpha-rename parameters and results in dominance preorder. Canonicalize each phi
as predecessor/value pairs sorted by canonical predecessor. Compare instruction
kind, types, constants, canonical operands, targets, aggregate metadata,
class/interface witness metadata, source locations, ownership calls,
`transferred_storage`, and exceptional edge kinds. Compare unreachable blocks as
a separately ordered multiset. Retained block order, raw numbering, raw phi order
and repeated-run bytes remain separate determinism assertions: they must not be
mistaken for semantic equivalence.

Parity may proceed only after the architecture and semantic rules marked as gaps
exist in Rust, and corpus plus adversarial lowering tests
exercise normal/exceptional CFG, loop and merge phis, collision renaming,
ownership transfer, aggregates/interfaces, and indirect calls.
