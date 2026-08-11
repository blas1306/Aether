# O2.9 local ARC elimination, Phases 1 and 2

O2.9 enables `LocalARCEliminator` only in O2, after proven BCE and conservative
LICM and before final SSA DCE. O0 and O1 are unchanged. The pass removes both
ends of a retain/release pair; it never changes ARC insertion, ownership
semantics, stack allocation, CFG, or any other lifecycle operation.

## Proof and eligibility

O2.8 `OwnershipEscapeAnalysis.classify_pair` is the proof authority. A pair
must be `LOCALLY_PROVABLE` (the programmatic form of the audit's
`PROVABLE_NOW`) and satisfy a second fail-closed structural audit. Both calls
use the same SSA value with exactly one exact provenance root. Alias
`MUST_ALIAS` is insufficient.

Phase 1 handles ordered pairs in one block. Phase 2 handles distinct blocks
only when the retain block dominates the release block, the release block
post-dominates the retain block, and walking the canonical CFG yields one
acyclic chain of unconditional normal `jump` edges. Every entered block has
exactly one predecessor, so branches, joins, alternate exits and loop
backedges fail closed. The walk uses the existing CFG, dominance,
post-dominance and reachability infrastructure; it does not infer order from
the block list.

The intervening region must contain no call/invoke, may-throw operation,
exception pack/destroy/catch/throw/rethrow/propagation, store, return, interface
construction, MethodResult operation, side effect, memory write, or other
ownership operation. Struct/nested aggregate values, interface values,
constructors and MethodResult values are excluded. Phis fail exact-provenance
eligibility. Destroy and exception destroy are not release forms; the only
eligible instructions are direct SSA calls whose builtin is exactly
`__aether_retain` and `__aether_release`.

Same-block pairs in loops are permitted because the proof and region are
recomputed on the complete loop CFG; a loop-carried phi is rejected. Calls are
always barriers in both phases even when summaries exist. Unknown or contradictory
facts preserve both calls.

## Statistics and verification

The pass separately reports same-block and multi-block candidates/eliminations,
plus blockers for nonunique path, branch, join, dominance, post-dominance,
backedge, identity, call, escape, ownership operation, exception, aggregate,
MethodResult/constructor, interface, and unsupported structure. SSA verification runs after the pass in
the normal optimizer pipeline. Assertions recheck authority, order,
same-block scope, non-overlap and all-or-nothing removal.

## Measured delta

The immutable O2.8.5 baseline is **53 retains / 924 releases**. The corrected
canonical analysis proves zero productive pairs, so current O2 also measures
**53 / 924** and eliminates zero pairs. Phase 1 and Phase 2 each have zero
eligible production-corpus candidates. The pass remains enabled as dormant,
fail-closed infrastructure; no candidate is promoted to preserve a historical
count. See `O2_ARC_OPPORTUNITY_AUDIT_CURRENT.md`.

LLVM sees typed Aether runtime calls with observable lifecycle semantics and
cannot generally infer this ownership cancellation. This gives Aether-specific
static value (eight fewer calls), but no runtime speedup is claimed.

Qualification requires programmatic SSA inspection, O1/O2 semantic parity,
native class/string/Array/List and exception regression, the exception
promotion gate, and representative ASan/LSan/UBSan runs. If LSan is unavailable
under ptrace, its external command must be reported and sanitizer qualification
must remain unclaimed.

In the managed validation environment, the sanitizer-backed native exception
suite stops with `LeakSanitizer does not work under ptrace`; therefore this
revision does **not** claim LSan qualification. Run the following outside
ptrace to complete it:

```sh
PYTHONPATH=.:src UV_CACHE_DIR=/tmp/aether-uv-cache uv run pytest \
  tests/aether/test_native_exceptions.py \
  tests/aether/test_exception_promotion_evidence.py \
  tests/aether/test_exception_release_qualification.py -q
```

The non-native exception-promotion gate passes 44 frontend/IR/SSA differential
comparisons. Focused optimizer/lifecycle tests and native class/string/Array/
List probes pass; no sanitizer finding other than the ptrace infrastructure
failure was observed.
