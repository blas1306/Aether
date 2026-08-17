# O2.9.5 — Qualified ownership-elided `ArrayGet<String>`

> O2.9.7 adds a distinct immediate-consumer mode. The 15 direct-projection
> sites remain unchanged; see `O2_IMMEDIATE_ARRAY_STRING_BORROW.md`.

Status: implemented. O2 alone runs the dedicated
`OwnershipElidedArrayGet` pass after BCE/LICM and before LocalARC/DCE. O0 and
O1 retain normal owned extraction semantics.

The pass reuses the existing, serialized `borrowed` ownership mode on
`IRArrayGet`/`SSAArrayGet`. Lifecycle-created SSA already contains the owned
temporary release; after qualification the pass marks the get borrowed and
removes exactly that value's single matching post-use release. LLVM therefore
keeps the same bounds check and element load while suppressing its implicit
retain. No wire or Rust change is needed: the optimization is SSA-local and SSA
is not part of the cross-language wire DTO.

Qualification is deliberately narrower than the general borrow analysis. It
requires exact `Array<String>`, an owned get in a loop, one same-block semantic
use which is `SSACompareOp`, `BORROWABLE_IMMEDIATE_USE`, no reported escape,
mutation/alias, call, exception or backedge blocker, and exactly one matching
lifecycle release after the comparison. Unknown facts fail closed. This freezes
the O2.9.4 direct-projection class; the three helper-call candidates and one
stable-region candidate remain owned.

## Frozen real-site result

All rows are in `examples/expense_tracker/Main.ae`, function
`decodeLedger`; each has use count 1, last use `SSACompareOp`, no escape, and
changes from owned to borrowed with direct ARC delta `-1 retain/-1 release`.

| Block | Array root | Index | String | Depth | Bounds check |
|---|---:|---:|---:|---:|---|
| `logic.rhs46` | `%451` | `%458` | `%459` | 1 | eliminated by BCE |
| `logic.rhs47` | `%451` | `%465` | `%466` | 1 | retained |
| `logic.rhs52` | `%530` | `%537` | `%538` | 2 | eliminated by BCE |
| `merge60` | `%530` | `%631` | `%632` | 2 | retained |
| `then61` | `%530` | `%636` | `%637` | 2 | retained |
| `else61` | `%530` | `%666` | `%667` | 2 | retained |
| `then65` | `%530` | `%671` | `%672` | 2 | retained |
| `else65` | `%530` | `%694` | `%695` | 2 | retained |
| `then69` | `%530` | `%699` | `%700` | 2 | retained |
| `else69` | `%530` | `%737` | `%738` | 2 | retained |
| `then74` | `%530` | `%742` | `%743` | 2 | retained |
| `else74` | `%530` | `%754` | `%755` | 2 | retained |
| `then76` | `%530` | `%759` | `%760` | 2 | retained |
| `else76` | `%530` | `%771` | `%772` | 2 | retained |
| `then78` | `%530` | `%776` | `%777` | 2 | retained |

Result: 15 recognized, 15 qualified and 15 transformed, with 15 backend retains
prevented and 15 explicit SSA releases removed. The historical `48/919` census
counted only explicit SSA ARC calls: the ArrayGet retains were implicit in LLVM
lowering and were never part of its 48. Consequently `33/904` was an incorrect
cross-layer prediction. The measured whole-corpus SSA census is `48/919 ->
48/904`; the expense-tracker census is `34/884 -> 34/869`; and the measured loop
census is `11/55 -> 11/40`. LLVM output separately loses the 15 implicit get
retains. The companion JSON contains the exact per-site pre/post locations.

O2.9.1/O2.9.2 committed artifacts remain immutable historical baselines.
Current-state regression expectations are post-O2.9.5 and the companion JSON
makes the revision boundary explicit rather than rewriting historical results.

The verifier rejects releasing a borrowed element as an independent owner and
continues to reject escape through return/phi and mutation through a borrowed
receiver. Tests cover the positive loop comparison and the frozen immediate
helper-call rejection. Existing backend behavior proves the LLVM distinction:
owned gets call retain; borrowed gets do not, while `_array_element_pointer`
and `bounds_checked` are unchanged. This optimization is `AETHER_UNIQUE` because
LLVM cannot reconstruct the Array-owned lifetime across opaque ARC calls.
