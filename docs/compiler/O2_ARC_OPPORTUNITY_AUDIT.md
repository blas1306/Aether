# O2.8.5 ownership precision and ARC opportunity audit

## Decision

**PROCEED_TO_LOCAL_ARC_ELIMINATION**.

The first pass may consider only an exact SSA identity in one function, with
no escape or consume between retain and release, complete dominance and
post-dominance, and no ambiguous phi, nested aggregate, call, store, invoke,
throw, cleanup, catch, or rethrow. The measured upper bound is 12 real pairs;
the deliberately stricter same-block/no-effect fast path contains 5 pairs.
This audit implements no such pass.

## Methodology and corpus

[`o2_arc_opportunity_audit.py`](../../scripts/o2_arc_opportunity_audit.py)
compiles a fixed productive corpus to lifecycle-expanded O2 SSA, applies the
read-only O2.8 ownership/escape and complete-CFG post-dominance analyses, and
records exact-identity candidate pairs. Static loop nesting is the dynamic
relevance proxy: depth 2 is HIGH, depth 1 MEDIUM, and outside loops LOW. Every
reported candidate is tagged `REAL_WORKLOAD`; synthetic probes are used only
by instrumentation tests.

The corpus covers classes, structs, Array/List, strings, interfaces,
constructors, the expense tracker, numerical methods, ProbandoNR sources, and
exception ownership. The two legacy numerical sources recorded as failures
use assignments outside the admitted IR subset; this is explicit in the JSON
and they contribute no counts. The expense tracker is the dominant productive
sample. Counts are tied to corpus revision
`2d4401cb79a9a786b224d38bfc616fe66ce96b0e`.

## Ownership and lifecycle inventory

Initial IR expresses semantic copy/move/destroy operations and has no explicit
retain/release calls. Lifecycle expansion introduces ARC bookkeeping; the SSA
inventory contains **53 retains and 924 releases**. The count is intentionally
not treated as 53 redundant pairs: releases include required destruction of
independent owners and cleanup. SSA preserves those operations. LLVM lowers
them to typed runtime helpers and cannot generally recover Aether ownership.

Source copy/move/destroy is source-semantic; recursive destroy and constructor
rollback are lifecycle-required; typed helper calls and reference-count header
updates are backend-only; expanded retain/release calls are ARC bookkeeping.
Constructor receiver cleanup, `MethodResult` package/extract, interface
carrier/box ownership, and exception payload/event operations retain their
special lifecycle contracts. Unrelated destructors are never counted as ARC
pair candidates.

## Traffic and relevance

The measured 977 explicit ARC operations include **11 retains and 55 releases
inside loops**. Of 26 candidate pairs, 19 are outside loops, 4 have loop depth
1, and 3 have loop depth 2. The expense tracker contributes 22 candidates and
928 ARC operations, so the recommendation is not based on synthetic probes.
Numerical methods contribute no candidate pairs; strings show 1 retain and 6
releases but no pair; basic Array/List loop samples show releases but no pair.
No exact runtime speedup is claimed. A removed pair would reduce two static ARC
calls at that site; loop candidates have the strongest call-frequency proxy.

Candidate classification:

| Classification | Count |
|---|---:|
| PROVABLE_NOW | 12 |
| BLOCKED_METHODRESULT | 3 |
| BLOCKED_NESTED_AGGREGATE | 4 |
| BLOCKED_NORMAL_JOIN | 3 |
| BLOCKED_ESCAPE_UNKNOWN | 3 |
| BLOCKED_INTERFACE_BOX | 1 |

The strict same-block fast path has **5** candidates. A simple straight-line
multi-block region has **3**. Excluding all exception regions leaves **12**
currently provable candidates. Four provable candidates are in loops (three at
depth 1 and one at depth 2); the remaining nested-loop pairs are blocked by
normal joins. This changes the O2.6.2 conclusion, whose smaller corpus found no
loop pair.

## Precision audits

`MethodResult` combines the updated struct receiver and optional secondary
result. Receiver transfer, aggregate copies, extraction, and exceptional exit
remain governed by lifecycle lowering. Three apparent local pairs around
message methods are conservatively `BLOCKED_METHODRESULT`, not proofs.
Constructor success transfers its initialized receiver; failure and partial
initialization require rollback, including from an active catch. No historical
IRV-150 behavior changes, and no constructor pair is independently provable in
this corpus.

Nested aggregate provenance currently distinguishes neither aggregate owner
from every recursively owned field nor field-cell identity from referenced
object identity. Four pairs would be the measured upper bound unlocked by
precise recursive provenance. Interface construction likewise escapes its
carrier into a class-backed carrier or fresh struct box; one pair remains
blocked. Interface arguments and returns are conservatively owned/borrowed by
the existing ABI.

At normal if/else, phi, multiple-predecessor, and loop-backedge joins, differing
ownership states join to UNKNOWN. Three candidates are lost solely at normal
joins. No measured candidate is lost solely at an exceptional join, although
invoke/catch/cleanup/rethrow edges remain in the dataflow and are excluded from
the first pass. Edge-sensitive states or event-specific facts are preferable
future precision mechanisms; this audit adds no path-sensitive transform.

Escape uncertainty blocks three pairs. The observed reasons are conservative
call/interface escape; return, field and collection stores remain explicit
escape categories. Known direct summaries are used, while unknown direct,
indirect, and interface calls may retain/store/consume. This audit does not
strengthen call summaries. String concatenation/interpolation and collection
copy/parameter/return traffic is largely required temporary or value-copy
lifecycle traffic rather than a proven local balance.

Exception cleanup ladders, event ownership, catch payload borrows, rethrow,
propagation, and constructor rollback are `SEMANTICALLY_REQUIRED` unless an
exact complete-CFG proof says otherwise. None is targeted by the first pass.

## Precision scorecard

| Area | Current precision | Blocked | Potential unlocked | Risk | Cost |
|---|---|---:|---:|---|---|
| MethodResult + constructors | coarse package provenance | 3 | 3 | medium | medium |
| Nested aggregates | aggregate-level | 4 | 4 | medium | high |
| Normal joins | state equality or UNKNOWN | 3 | 3 | medium | medium |
| Exceptional joins | complete CFG, coarse merge | 0 | 0 | high | high |
| Call summaries | known direct; conservative otherwise | 0 pair-only | 0 | medium | medium |
| Interface boxes | carrier/box coarse provenance | 1 | 1 | high | high |

Although nested aggregates are the largest precision delta (4), precision work
is not a prerequisite for the 12 already proven pairs. The exact next milestone
is therefore a `LocalRetainReleaseEliminator` restricted to the gates in the
decision section, with an expected maximum unlock of **12 pairs** (24 static
ARC calls), starting with the 5-pair same-block fast path.

## LLVM overlap and invariants

Classification is `LLVM_CANNOT_SEE_OWNERSHIP`: typed ARC helpers and destruction
semantics prevent assuming LLVM removes these pairs. Per-site optimized-LLVM
comparison remains a required implementation validation, so no runtime benefit
is asserted here. The deterministic evidence is
[`o2_arc_opportunity_audit.json`](o2_arc_opportunity_audit.json).

Production codegen is unchanged. ARC insertion/removal is unchanged. O0/O1/O2
pass membership is unchanged. There is no stack promotion, scalar replacement,
inlining, devirtualization, ownership semantic change, or commit in this
milestone.
