# O2.6.2 next-optimization opportunity audit

Status: audit complete, 2026-08-09. This milestone changes no optimizer,
pipeline membership, ownership rule, language semantic, or code-generation
behavior. The machine-readable evidence is
`o2_next_optimization_audit.json`; regenerate it with
`PYTHONPATH=src .venv/bin/python scripts/o2_next_optimization_audit.py
--output docs/compiler/o2_next_optimization_audit.json`.

## Method and workload

The auditor compiles the 16 established O2 proof-coverage workloads to O1 SSA,
runs proven BCE followed by an isolated O2.6.1 LICM observation, and compares
the resulting final O2 SSA. It inventories loop reads, lifecycle calls, call
forms and callee sizes without rewriting them. The set covers Array/List,
Vector/Matrix and nested-loop benchmarks, LLVM examples, numerical methods,
Newton-Raphson, alias probes and slice checks. There were no corpus failures.

The census is static. “Hot” means syntactically inside a natural loop; it does
not pretend to be sampled frequency. Runtime was not claimed where workload
duration was below a useful noise floor. For the sole affected workload,
`benchmarks/array_sum.ae`, emitted O1 and O2 LLVM was independently passed
through clang 22.1.8 `-O2`: both optimized modules had 50 counted LLVM
instructions and both objects were 1,560 bytes.

## O2.6.1 measured impact and LLVM overlap

Across 15 natural loops, LICM examined 200 value-producing instructions. There
were three eligible immutable metadata reads: two remained blocked and one
`Array.length` was hoisted. No `List.length`, `Vector.length`, `Matrix.rows`,
or `Matrix.columns` read moved. Six scalar constants also moved. Only
`benchmarks/array_sum.ae` was affected, so hot-loop relevance is one loop in
the audited set. Aggregate SSA instruction count was unchanged at 898 in both
O1 and O2; placement changed, not work count.

The immutable-read blocker totals are two control/speculation failures. The
complete LICM census also records 76 control failures, 35 may-trap operations,
10 may-throw operations, 57 unsupported kinds and 15 variant operands. These
are overlapping pass-level opportunities, not all immutable reads.

The affected Array case is **LLVM_CONVERGES**: raw emitted LLVM differed by one
instruction (140 versus 139), but clang produced the same 50-instruction count
and identical object size. The optimized textual modules differed only in
non-semantic/profile material, so this audit finds no `AETHER_UNIQUE` runtime
benefit. The other eligible sites are **NO_EFFECT** because Aether did not move
them. O2.6.1 therefore mostly duplicates LLVM for the only measured success;
no runtime benefit is claimed merely from the move.

## General memory-read opportunity

Five remaining element reads occur in loops: two `ArrayGet`, two `ListGet`,
and one `MatrixGet`. All five have a varying base or index. Two still carry a
bounds check and require BCE first. There were no invariant-address,
already-nontrapping reads immediately implementable in this corpus, and no
class/struct/interface-carrier field read inside its loops.

For a future candidate the answers must all be yes: the read and address are
loop invariant; mod/ref proves no relevant writer; BCE has set
`bounds_checked=false`; the operation is nonthrowing; base identity is stable;
the loop is dynamically relevant; and Aether retains value beyond LLVM's
ordinary load LICM. A checked `ArrayGet`/`ListGet` must stay in place because
moving it can change panic order or make a zero-trip loop trap.

Current O2.4 locations identify a whole semantic object. They cannot distinguish
`obj.a` from `obj.b`. Although this workload set exposes zero blocked loop field
reads, the limitation is structural and a field-read LICM must not be built on
the zero count. Unknown direct summaries, indirect calls, interface calls,
parameter aliases and phi merges remain fail-closed blockers. Immutable-looking
elements are not immutable metadata.

## ARC traffic and readiness

O1 SSA contains 2 retains and 16 releases in the audited set, plus no explicit
exception destroys. None is syntactically inside a natural loop. Releases are
concentrated in Array/List `main` functions; the two retains occur in the alias
examples (`identity` and `main`). There is consequently low measured dynamic
value for a first ARC pass in these numerical and collection loops. The corpus
does not justify extrapolating zero traffic to string-, class-, interface-box-,
constructor-, or owned-struct-heavy programs; those categories need dedicated
successful native probes before promotion.

The two apparent retain/release balances are classified
`NEEDS_OWNERSHIP_DATAFLOW`, not redundant. Alias identity is not ownership-count
equivalence. A safe pass needs value-specific ownership state, consuming-use
and escape facts, dominance/post-dominance, and normal plus exceptional path
accounting. Invokes, cleanup, rethrow, constructor failure, partial
initialization and normal/exceptional joins prevent textual pairing. Parameters,
returns, interface boxes and heap stores need escape summaries; a strictly local
temporary may avoid full escape analysis only when every use is visible and no
call or store can escape it.

The smallest plausible later pass is local same-value retain/release pair
elimination, restricted to no intervening escape or consuming use and with an
explicit proof that every normal and exceptional path preserves required
cleanup. O2.4 alone cannot supply this proof. ARC correctness risk is
**VERY HIGH**: a wrong result is a use-after-free, double free or leak.

## Call graph and inlining readiness

The O1 modules contain 57 direct and 19 indirect calls, no interface calls in
this corpus, no mutually recursive pair, and five statically known,
nonrecursive, nonthrowing small/tiny call sites. The function-size thresholds
are derived per module from SSA instruction-count quartile and median; in the
aggregate the distribution is 18 tiny, 3 small, 5 medium and 5 large functions.
Source lines were not used.

A first inliner would have to be intra-current-module only, preserving future
separate compilation. It should accept only direct, nonrecursive, nonthrowing
tiny callees. Indirect calls remain indirect; interface dispatch requires
devirtualization and is not part of this opportunity. May-throw callees require
CFG cloning of invoke normal/exceptional successors, event-out values, cleanup,
catch dispatch and rethrow and are excluded from a first pass.

SSA lifecycle instructions could be cloned literally only after receiver,
borrowed/owned parameter, owned return and `MethodResult` identities are renamed
without duplicating cleanup. Constructor receiver lifecycle needs separate
proof. Existing instruction source locations preserve callee origin, but there
is no inlining provenance stack combining callee and call-site locations; that
must be designed before tooling-quality inlining.

LLVM already receives direct function bodies in one module and performs its
own `-O2` inlining. Aether inlining is unique only when it exposes Aether-level
BCE, semantic mod/ref or future ownership facts before lowering. No measured
site in this corpus establishes that enabling win, so ordinary call-overhead
inlining is classified **LLVM already handles it**.

## Numerical and general-program findings

Numerical workloads are dominated by varying element addresses and scalar
loop work. O2.6.1 moved only one length read, LLVM converged, and no ARC traffic
was in a loop. Tiny helpers exist, but LLVM overlap is high. The measured next
gain is therefore analysis that can expose stable locations across calls, not
another broad transform.

Collection/alias examples account for all lifecycle traffic but none is hot.
The corpus has indirect calls, while interface-heavy, class-heavy,
string-temporary, constructor-heavy and expense-style workloads are
underrepresented. This is itself an evidence gap: a general-language decision
cannot safely promote ARC or inlining based only on the numerical set.

## Comparative opportunity and risk

| Direction | candidates | hot value | LLVM overlap | complexity | risk | Aether-specific value |
|---|---|---|---|---|---|---|
| General read LICM | low; 0 immediately ready | medium potential | high in measured case | medium | medium (stale read/panic movement) | semantic field/collection mod-ref |
| ARC optimization | medium static traffic, 0 proven pairs | low measured | low | high | very high | ownership and exception semantics |
| Inlining | 5 narrow sites | medium potential | high | very high | high | earlier BCE/LICM/ARC exposure |

The ordinal rubric considers real candidate count, loop relevance, expected
runtime and code-size effects, unique semantic information, LLVM overlap,
implementation cost, correctness risk, prerequisites and enabling value. It
deliberately avoids arbitrary numeric weights.

Dependencies are:

```text
memory-read LICM -> field-sensitive locations -> call mod/ref summaries
                 -> BCE-proven nontrapping access -> existing LICM
ARC elimination  -> ownership dataflow -> escape/consume summaries
                 -> exception-path ownership -> dominance/post-dominance
inlining         -> CFG cloning + SSA renaming -> lifecycle preservation
                 -> exception/event edge replacement -> provenance + size policy
```

## Recommendation

**PRIMARY: IMPROVE_ANALYSIS_FIRST**

The exact first scope is field-sensitive memory locations plus ownership
dataflow and exception-aware escape/call summaries, with no transform enabled.
Add representative class/string/interface/constructor probes and rerun this
audit. That work is shared infrastructure and resolves the largest evidence
and correctness gaps without duplicating LLVM.

**SECONDARY:** re-audit only invariant, `bounds_checked=false`
`ArrayGet`/`ListGet` after field-sensitive mod/ref exists. Continue delegating
ordinary direct inlining to LLVM meanwhile.

O2.7 follow-up: nominal field precision now exposes synthetic `obj.a` reads as
preserved across writes/calls limited to `obj.b`. No measured general-read
candidate is immediately implementable yet because nested loaded-reference
provenance, speculation/trap safety, and ownership/escape facts remain missing.
The old immediately-ready count was 0 and remains 0; field sensitivity is the
specific newly satisfied prerequisite, not a transformation authorization.

No stop condition was observed: current LICM/BCE and ARC generation did not
show semantic divergence or unsoundness, and metadata did not contradict
execution. The audit does identify insufficient ownership analysis for ARC
elimination, which is why it recommends analysis rather than that transform.

## Validation and modified files

Modified artifacts are this report, `o2_next_optimization_audit.json`, the
read-only generator, and its contract test. The focused audit test, LICM,
alias/mod-ref, BCE, ownership/lifecycle, exception promotion, optimization
profile, capability, documentation, compileall and diff checks form the
validation set. No historical baseline was modified and no commit was created.
Production code generation and O0/O1/O2 pass membership are unchanged.

## O2.8 follow-up

Separate ownership/escape domains, exceptional CFG dataflow, recursive direct
summaries, post-dominance, and diagnostic ARC pairing are now implemented. No
transform consumes them. The conclusion remains
`IMPROVE_OWNERSHIP_ANALYSIS_FIRST` pending nested aggregate and constructor
precision plus production-corpus metrics.
