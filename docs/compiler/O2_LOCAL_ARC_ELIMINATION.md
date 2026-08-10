# O2.9 local ARC elimination, Phase 1

O2.9 enables `LocalARCEliminator` only in O2, after proven BCE and conservative
LICM and before final SSA DCE. O0 and O1 are unchanged. The pass removes both
ends of a retain/release pair; it never changes ARC insertion, ownership
semantics, stack allocation, CFG, or any other lifecycle operation.

## Proof and eligibility

O2.8 `OwnershipEscapeAnalysis.classify_pair` is the proof authority. A pair
must be `LOCALLY_PROVABLE` (the programmatic form of the audit's
`PROVABLE_NOW`) and satisfy a second fail-closed structural audit. Both calls
must be in one block, ordered retain before release, use the same SSA value,
and have one exact provenance root. Alias `MUST_ALIAS` is insufficient.

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
always barriers in Phase 1 even when summaries exist. Unknown or contradictory
facts preserve both calls.

## Statistics and verification

The pass reports retain instructions examined, candidate pairs, Phase-1
eligible pairs, pairs eliminated, and blockers for identity, call, escape,
ownership operation, exception, aggregate, MethodResult/constructor,
interface, and unsupported structure. SSA verification runs after the pass in
the normal optimizer pipeline. Assertions recheck authority, order,
same-block scope, non-overlap and all-or-nothing removal.

## Measured delta

The immutable O2.8.5 baseline remains **53 retains / 924 releases**, including
**11 / 55** in loops and five audit-level same-block candidates. With O2.9 the
same corpus contains **49 retains / 920 releases**. Four pairs are removed.
Loop traffic remains **11 / 55**: remaining loop-local audit candidates are
phi-derived and fail the stricter exact-provenance/no-phi rule. The fifth old
site is not promoted merely to reach the upper bound.

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
