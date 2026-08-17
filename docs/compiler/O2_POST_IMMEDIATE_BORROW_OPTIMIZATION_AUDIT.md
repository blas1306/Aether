# O2.9.8 — Post-immediate-borrow optimization audit

Status: audit complete, 2026-08-17. This is a read-only snapshot of production
O2 after O2.9.7. It changes no ownership, lifecycle, optimizer, backend,
code-generation, or profile behavior. Structural hotness is a deterministic
ranking heuristic, not a claimed runtime percentage.

## Decision

**Primary: `PROCEED_TO_SCALAR_REPLACEMENT_ANALYSIS`.** The exact next milestone
is analysis-only: build a field-use, escape, ownership-component, and
exception-path ledger for the four nonescaping `ControlLineResult` call-result
temporaries in `decodeLedger` (depths 1, 1, 2, and 1). Qualification requires
field-only use, no identity observation or capture, and complete normal and
exceptional destruction coverage. It explicitly excludes SROA, copy elision,
stack promotion, ARC changes, and codegen changes.

Second place is `PROCEED_TO_AGGREGATE_COPY_ELISION`: the same workload contains
four copy-induced aggregate lifetime sites, but transforming them before the
field-use ledger would combine copy semantics, component ownership, and
exception risks prematurely.

Scalar GVN/CSE (83 syntactic redundancies, 22 in loops) and affine loop work
(41 sites) rank higher under the structural heuristic, but mostly duplicate
LLVM and provide little Aether-specific enabling value. The selected analysis
instead retains Aether's aggregate ownership semantics and can qualify both
copy elision and later stack promotion.

## Current production census

| Layer | Global | In loops |
| --- | ---: | ---: |
| Explicit SSA retains | 48 | 11 |
| Explicit SSA releases | 901 | 37 |
| Backend implicit retains | 69 | 11 |

Loop ownership occurs only in `decodeLedger` and `encodeLedger`, both compiled
from `examples/expense_tracker/Main.ae`. The 59 loop operations across both
layers comprise 26 temporary-owner operations, 17 call-result releases, 11
collection-element implicit retains, and 5 copy/balancing releases. At most 19
(32.2%) are plausibly removable; that is an attribution ceiling, not dynamic
performance evidence. Exception ownership contributes six global operations
and none in a loop.

The 69 backend retains reconcile independently: 60 are owned
`ArrayGet<String>` results and nine are ownership-bearing components of
`List<Struct>` loads. Eleven of the former occur in loops. There are no current
`List<String>`, class/reference element, interface/carrier, or method-result
implicit retains. SSA-only accounting would therefore omit material traffic.

LocalARC now finds zero semantic candidates, zero structurally eligible
candidates, zero removals, and zero loop candidates. Further LocalARC
generalization is deprioritized.

## Stable `%373` audit

`%373` is the owned `String` loaded from Array root `%357` at constant index
`%372 == 0` in `decodeLedger`, block `logic.rhs38`, loop `cond0`, depth 1. The
borrow would begin at instruction 1 and end at instruction 4, argument zero of
`text.byteSlice`. It crosses one call but zero blocks, branches, stores, phis,
mutations, exception edges, and backedges. The Array owner covers the use and
there is no alias uncertainty.

Its structural hotness is 4 and its theoretical saving is exactly one backend
retain plus one explicit release. Minimum machinery is a capture/consume
summary for `text.byteSlice` argument zero and proof that the Array owner spans
normal and exceptional completion. Classification:
`CALL_SUMMARY_EXTENSION`. It remains owned; O2.9.8 does not optimize it.

## Aggregate, collection, and allocation evidence

The historical aggregate lifetime identities remain immutable. Four
`ControlLineResult` call-result temporaries are classified `COPY_INDUCED`, all
in real loops, with combined structural hotness 18. They are nonescaping,
contain ownership-bearing fields, and currently require value-copy/destruction
semantics; LLVM overlap is partial because the lifecycle calls obscure the
high-level aggregate relationship.

Beyond `Array<String>`, the implicit-retain census finds nine `List<Struct>`
component loads globally and none in loops. It finds zero `List<String>`,
`Array/List<Class>`, or `Array<Struct>` opportunities. Struct component
borrowing is semantically and ABI-wise different from the scalar String load,
so O2.9.5 must not be generalized from this evidence.

There are 19 ownership-bearing allocation-like results in loops. The existing
escape analysis classifies 11 as definite noescape and eight as mayescape; none
is proven definite escape by this audit. Four noescape results are the struct
candidates selected for deeper scalar-replacement analysis. Stack promotion
still requires identity, destructor, native/interface-boundary, and exceptional
lifetime proofs, so no allocation is promoted here.

## LICM, GVN/CSE, and loops

Re-running the existing LICM analysis on post-pipeline SSA examines 18 loops
and sees four supported read candidates but hoists zero. The remaining reads
are blocked by trap/throw, memory mod/ref, control speculation, or variant
operands. No new hot, safe ownership-preserving memory-read class is proven;
LLVM can already handle exposed low-level invariants.

The narrow pure-expression census finds 83 syntactic GVN/CSE candidates across
the corpus: same-block cases are classified `LLVM_ALREADY_ELIMINATES`, while
cross-block identities require dominance proof and are `LLVM_PARTIAL`. Twenty
two occur in loops and two real workloads are covered. Checked trap semantics
remain explicit blockers. No candidate is shown to expose an Aether ownership,
BCE, or LICM fact before an opaque runtime boundary, so a generic pass is not
the next milestone.

All 18 natural loops have canonical preheaders and single latches; none is
irreducible or has multiple latches. Seventeen have a canonical IV and are
simple counted loops; nine have multiple exits. Lack of loop canonical form is
not currently blocking optimization. Forty-one loop `add/sub/mul` sites merit
affine inspection, but checked integer overflow prevents assuming classical
strength reduction is free and LLVM overlap is substantial.

Indirect/interface calls have open target sets in this corpus; no hot exact
target case supports devirtualization. Direct calls are recorded only when an
Aether-specific ownership/BCE/LICM unlock exists; none is established merely
from function size. Normal-path exception ARC is zero in loops, so exception
machinery is not a primary optimization family.

## Family matrix

| Family | Static / loop | Weighted hotness | Workloads | Expected effect | Complexity | Risk | LLVM overlap | Enabling value |
| --- | ---: | ---: | ---: | --- | --- | --- | --- | --- |
| stable borrow | 1 / 1 | 4 | 1 | 1 retain + 1 release | MEDIUM | MEDIUM | Aether can prove more | LOW |
| ownership elision generalization | 69 / 11 | 54 | 1 | collection temporary ARC | HIGH | HIGH | Aether can prove more | MEDIUM |
| aggregate copy elision | 4 / 4 | 18 | 1 | aggregate component ARC/copies | HIGH | MEDIUM | partial | HIGH |
| stack promotion | 19 / 19 | 84 | 1 | allocation and lifecycle | HIGH | HIGH | partial | HIGH |
| memory LICM | 4 / 0 qualified | 0 | 0 | invariant reads | MEDIUM | MEDIUM | high | MEDIUM |
| GVN/CSE | 83 / 22 | 228 | 2 | redundant pure SSA | MEDIUM | LOW | high | LOW |
| loop/IV optimization | 41 / 41 | 174 | 4 | affine/index work | HIGH | MEDIUM | partial | MEDIUM |
| scalar replacement | 4 / 4 | 18 | 1 | aggregates, ARC, loads/stores | MEDIUM | MEDIUM | Aether needed earlier | HIGH |

Each row's full analysis-prerequisite, ownership, exception, verifier, backend,
LLVM, and enabling classifications is serialized in the canonical JSON.

## Reproduction and freeze

Run:

```bash
.venv/bin/python scripts/o2_post_immediate_borrow_optimization_audit.py \
  --output docs/compiler/o2_post_immediate_borrow_optimization_audit.json
```

The JSON is sorted and newline-terminated for byte-for-byte regeneration. Prior
O2.9.x reports are historical inputs and are not rewritten. O2.9.8 adds no
transformation test because it performs no transformation.
