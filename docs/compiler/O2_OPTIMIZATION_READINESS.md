# O2 optimization readiness audit

O2.8.8 adds analysis-only nested aggregate provenance. Five collection-object
candidates become semantically provable, but a qualification barrier keeps
them frozen. Production stays at 53 retains / 924 releases; O0/O1/O2 membership
is unchanged. See `O2_NESTED_AGGREGATE_OWNERSHIP_PROVENANCE.md`.

Update for O2.2: the first proof-gated transform is enabled only in O2. The
exact scope, ordering, and conservative limitations are documented in
`O2_BOUNDS_CHECK_ELIMINATION.md`; the broader readiness cautions below remain.

O2.9 update: O2 contains a fail-closed `LocalARCEliminator` after BCE and LICM
and before final DCE. The corrected canonical semantic audit currently proves
zero Phase-1 or Phase-2 production candidates, so O2 eliminates zero ARC pairs
and remains at 53 retains / 924 releases. See
`O2_ARC_OPPORTUNITY_AUDIT_CURRENT.md`. O0 and O1 remain unchanged.

Status: audit complete, 2026-08-09. This document describes the compiler at
the audited revision; it does not change the optimization-profile contract and
does not implement an optimization family.

## Executive decision

Aether is not ready for a broad, transformation-heavy O2 middle-end. It is
ready to build the analysis substrate for one. The highest-value first target
is collection-loop optimization: loop discovery/canonicalization, a modest
alias/effect analysis, integer ranges, and then bounds-check elimination (BCE)
with exact panic-order preservation. Ownership dataflow and direct-call
summaries should follow; they enable conservative ARC pair elimination and a
small inliner. Generic GVN, LICM, scalar replacement, induction-variable
rewriting, and vectorization should remain downstream LLVM work until Aether
has evidence that its semantic information makes them materially better.

No current optimizer unsoundness, O1 behavior divergence, ownership violation,
or floating-point ambiguity affecting an enabled pass was found. This is not a
proof of absence. In particular, the initial-IR `DeadStoreEliminator` is
intentionally very narrow: it is block-local and declines every `may_throw`
function. That conservatism must not be relaxed without lifecycle and
exception-aware dataflow.

## 1. Canonical current O1 pipeline

The source of truth is `src/aether/optimization.py`. Both pass pipelines run to
a fixed point (maximum ten iterations); verified SSA is checked after every
pass. O2 currently uses exactly this middle-end and changes only clang `-O1` to
`-O2`.

```text
typed AST
  -> lower initial IR -> verify
  -> [fixed point, max 10]
       ConstantFolder
       LocalConstantPropagator
       ConstantFolder
       AlgebraicSimplifier
       DeadCodeEliminator
       DeadStoreEliminator
       DeadCodeEliminator
  -> verify / lifecycle expansion as required by the backend
  -> GeneralSSABuilder (CFG + dominators + frontier + phi placement/rename)
  -> verify
  -> [fixed point, max 10; verify after every pass]
       SSAConstantFolder
       SSAGlobalConstantPropagator
       SSAAlgebraicSimplifier
       SCCPPass
       TrivialPhiEliminator
       DeadPhiEliminator
       SSADeadCodeEliminator
  -> LLVM lowering and runtime/helper emission
  -> clang -O1
```

There is no separate optional "backend preparation" optimization pass. SSA
construction, verification, lifecycle lowering, LLVM ABI lowering, and helper
emission are correctness/code-generation stages. Clang's `-O1` pipeline is the
only backend optimizer in the O1 profile.

### Initial-IR pass inventory

| # | Pass and implementation | Exact purpose and dependencies | Scope / CFG | Semantic assumptions | O1 / required |
|---|---|---|---|---|---|
| 1,3 | `ConstantFolder`, `ir/optimizer/constant_folding.py` | Fold literal unary/binary/compare/cast operations using checked integer arithmetic and IEEE power; second run consumes constants exposed by propagation. Operand types and literal map only. | Local scan across each function; no CFG change. | Refuses integer overflow/divide-by-zero and nullable/aggregate comparisons; therefore does not erase traps. No alias/ownership assumption. Floating folds retain source operation order. | Enabled; optional. |
| 2 | `LocalConstantPropagator`, `ir/optimizer/local_constant_propagation.py` | Substitute constants through block-local storage/value uses. Uses operand traversal and local invalidation. | Local/basic-block; no CFG change. | Does not reason through calls, aliases, ownership, or exceptional paths. | Enabled; optional. |
| 4 | `AlgebraicSimplifier`, `ir/optimizer/algebraic_simplification.py` | Integer-only identities, redundant same-type casts, and complete use rewriting. | Function scan but value-local; no CFG change. | Excludes FP identities. Operands must be SSA-like values, not storage aliases; preserve-worthy instructions are not targeted. | Enabled; optional. |
| 5,7 | `DeadCodeEliminator`, `ir/optimizer/dead_code.py` | Backward liveness from all non-removable instructions; remove unused pure result producers. Second run cleans values exposed by DSE. Depends on exhaustive operand traversal and `must_preserve`/effects. | Function-global use graph; no CFG change. | Any side effect, trap, throw, allocation/lifecycle action marked `must_preserve` is a root. No alias claim. | Enabled; optional. |
| 6 | `DeadStoreEliminator`, `ir/optimizer/dead_store.py` | Remove an `IRStore` overwritten or killed before a same-slot load, within one block. | Block-local; no CFG change. | Disabled for an entire throwing function; lifecycle operations, control transfer, loads, and initialization/move/destroy/relocate are barriers. Slot-name identity only; no general alias reasoning. | Enabled; optional. |

### SSA pass inventory

| # | Pass and implementation | Exact purpose and dependencies | Scope / CFG | Semantic assumptions | O1 / required |
|---|---|---|---|---|---|
| 1 | `SSAConstantFolder`, `ssa/optimizer/constant_folding.py` | SSA counterpart of literal folding. | Value-local; no CFG change. | Same checked-integer, trap, FP, nullable, and aggregate restrictions as IR folding. | Enabled; optional. |
| 2 | `SSAGlobalConstantPropagator`, `ssa/optimizer/global_constant_propagation.py` | Substitute constants through SSA uses across blocks. | Intraprocedural global; no CFG change. | SSA definition identity removes storage alias ambiguity; calls remain opaque. | Enabled; optional. |
| 3 | `SSAAlgebraicSimplifier`, `ssa/optimizer/algebraic_simplification.py` | Integer identities and cast/use cleanup. | Intraprocedural/value-local; no CFG change. | No FP reassociation; no memory/ownership assumptions. | Enabled; optional. |
| 4 | `SCCPPass`, `ssa/optimizer/sccp{,_pass}.py` | Sparse conditional constant propagation: executable-edge/block discovery, constant lattice evaluation, branch simplification, unreachable-block removal, and phi incoming repair. | Intraprocedural global; **changes CFG**. | Calls/invokes and their results are overdefined; exceptional results/edges remain semantic. Only modeled pure scalar operations fold; traps are not speculated. | Enabled; optional. |
| 5 | `TrivialPhiEliminator`, `ssa/optimizer/trivial_phi.py` | Replace phis whose non-self incoming values are one identical SSA value. | Intraprocedural; no CFG change. | Relies on verified phi predecessor/value invariants. | Enabled; optional. |
| 6 | `DeadPhiEliminator`, `ssa/optimizer/dead_phi.py` | Remove transitively unused phi cycles/definitions. | Intraprocedural use graph; no CFG change. | Phis are pure and ownership-neutral representations, not lifecycle actions. | Enabled; optional. |
| 7 | `SSADeadCodeEliminator`, `ssa/optimizer/dead_code.py` | Remove unused pure SSA result producers. | Intraprocedural; no CFG change. | `must_preserve` is authoritative for side effects, traps, throws, allocation and lifecycle. | Enabled; optional. |

All optional passes preserve correctness; none is required to make valid IR or
SSA. CFG construction, dominance/frontiers, phi placement/renaming, IR/SSA
verification, lifecycle expansion, exception ABI lowering, and LLVM lowering
are correctness-required.

## 2. Existing analysis inventory

The classifications describe usefulness for optimization, not test quality.

| Analysis | State | Evidence and limitation |
|---|---|---|
| CFG | **COMPLETE** | `analysis/cfg.py` models normal and exceptional successors for the present terminators. Function-local; no incremental update API or loop metadata. |
| Reachability | **PARTIAL** | Internal worklists in dominance/frontier and SCCP; SCCP exposes executable blocks/edges. No canonical reusable analysis/preservation contract. |
| Dominance | **COMPLETE** | `analysis/dominators.py`: dominator sets, idom, tree, reachability, including isolated unreachable blocks. Function-local. |
| Dominance frontier | **COMPLETE** | `analysis/dominance_frontier.py`; used for phi placement, normal and exceptional CFG edges included. |
| SCCP lattice/value facts | **COMPLETE** for scalar SCCP, **PARTIAL** generally | unknown/constant/overdefined plus executable edges; no ranges, shapes, references, memory, call summaries, or FP algebra facts. |
| Instruction effects | **PARTIAL** | IR/SSA instructions expose `has_side_effects`, `may_trap`, memory read/write and allocation facts; several builtins are refined. Unknown calls remain deliberately broad. No location sets, capture, release, or per-argument effects. |
| `may_throw` | **PARTIAL** | Function, interface slot, call/invoke and verifier/ABI metadata exist; `Error.message` is enforced nonthrowing. It is a boolean, not a throw-set or path-sensitive summary. |
| `may_trap` / panic | **PARTIAL** | Per-instruction effects protect DCE and folding; no trap kind/order dependency graph and helper calls obscure high-level checks downstream. |
| Ownership/lifecycle | **PARTIAL** | Explicit init/copy/move/assign/destroy/relocate, type lifecycle traits, expansion to retain/release, exception-event ownership verification and cleanup ladders are strong correctness metadata. There is no optimizer ownership lattice/dataflow or ARC provenance. |
| Borrow information | **LOCAL ONLY** | Typechecker prevents borrowed for-in element mutation/escape; IR get carries `borrowed` and `borrow_scope`, checked by verifier. Parameters do not expose a general borrow/noescape contract to optimizers. |
| Mutation/effects | **PARTIAL** | Typed checks include struct-method mutation analysis and collection iteration restrictions; instruction read/write flags exist. No mod/ref regions, call summaries, or mutation epochs. |
| Type/layout | **COMPLETE** for lowering, **PARTIAL** for optimization | Nominal and collection/shape types, lifecycle traits, interface carrier/layout and LLVM layouts are present. Dynamic collection length/capacity and field-sensitive value facts are absent. |
| Interface dispatch | **PARTIAL** | Witness has interface/concrete identity, carrier kind, deterministic slots, box layout and ownership adapters. No propagated exact-type set or closed/open-world summary. |
| Call graph | **PARTIAL (O2.4)** | Direct calls participate in deterministic recursive mod/ref summaries; indirect target sets remain open. |
| Escape/capture | **ABSENT** | Borrow verifier handles one prohibited escape case; it is not allocation escape analysis. |
| Alias | **PARTIAL (O2.7)** | Conservative SSA provenance, nominal one-level field locations, three-way alias queries and target-relative mod/ref exist as opt-in analysis; deep paths, globals, escape and exact indirect targets remain coarse/absent. |
| Loop discovery/canonical form | **ABSENT** | CFG and dominance can support natural-loop discovery, but there are no backedge, loop forest, irreducibility, preheader, latch or exit analyses/transforms. |
| Integer range/value range | **ABSENT** | SCCP constants and typechecking of literal ranges are not interval analysis. |
| Collection shape | **PARTIAL / LOCAL ONLY** | Static Vector/Matrix shapes and dynamic Array/List length operations exist; no SSA shape equivalence or mutation invalidation. |
| FP policy metadata | **ABSENT** | Current semantics are strict by construction; there is no fast/contract/reassociate flag. |

There is also no analysis manager, cache invalidation protocol, or pass-declared
analysis usage. O2 analysis work should introduce explicit immutable results and
recompute after CFG-changing passes before attempting sophisticated transforms.

## 3. Candidate matrix

Complexity and impact are relative: L/M/H. “LLVM” means clang/LLVM `-O2` can
normally perform the low-level form if Aether exposes it without opaque helpers.

| Candidate | Aether workload / needed facts | Hazards and LLVM/Aether value | Complexity; perf; size | Decision |
|---|---|---|---|---|
| Function inlining | `mix`, `clampScore`, `sumTo`, Newton function helpers, methods; direct call graph, costs, ABI/ownership/effects | Recursion, invokes/event-out, cleanups, moved/borrowed values, source provenance. LLVM handles direct LLVM functions well, but function-value/interface calls and ownership boundaries can hide facts. | H; M-H; increases | **P1**, tiny safe direct inliner only after summaries; otherwise LLVM |
| ARC retain/release elimination | Class/string/Array/List copies, interface carriers, temporaries | Release timing, deinit side effects/traps, exceptions, cleanup ladders, partial init, aliases and FFI. LLVM cannot infer Aether ownership reliably. | H; H on ownership-heavy code; neutral/smaller | **P1** after ownership dataflow |
| Bounds-check elimination | `array_sum`, `list_for_sum`, `list_push`, Vector/Matrix/Newton kernels | Preserve first failing check and panic ordering; length may mutate/alias/call; 0-based Array/List versus current Vector/Matrix conventions. LLVM may inline helpers but lacks borrow/shape semantics. | M-H; H scientific/collection loops; smaller | **P0** after loop/range/effects |
| LICM | nested loops, length/shape loads, numerical kernels | May-throw/trap cannot be hoisted across observable operations; memory aliases, ARC lifetime, FP exception behavior. LLVM is strong once alias/effects are visible. Aether value: hoist proven immutable collection shape/check operands. | H; M; neutral | **P2**, semantic/check-focused; defer generic LICM |
| GVN | repeated length/shape/field expressions | Requires dominators, expression keys, memory SSA/epochs, alias/effects and trap equivalence. LLVM already strong. | H; M; smaller | **DEFER TO LLVM**; consider high-level shape-value numbering later |
| CSE | repeated scalar/shape expressions in a block | Local effects/traps and memory invalidation. LLVM handles scalar CSE. | M; L-M; smaller | **DEFER TO LLVM** |
| Dead allocation elimination | unused temporary vectors/matrices/strings/interface boxes | Allocation failure/trap, destructor and identity observability, escape/capture. LLVM cannot see all runtime ownership semantics. | H; M-H; smaller | **P2** after escape/ownership |
| Escape analysis | class/interface box/temporary aggregate sites | Calls, returns, fields, closures/function values, FFI; identity means nonescape does not alone permit elimination. | H; enabling; neutral | **P1 analysis**, transformations P2 |
| Alias analysis | every memory/collection optimization | See section 9; native calls and unknown calls clobber/capture. | M-H; enabling; neutral | **P0 analysis** (minimal local/mod-ref) |
| Scalar replacement (SROA) | short-lived structs, interface boxed structs, temporary Vector/Matrix | Address/identity, ownership per field, exceptional partial initialization. LLVM handles exposed aggregates; Aether is useful for boxed/value-semantic aggregates. | H; M; may grow/shrink | **P2** |
| Loop canonicalization | all benchmark loops and collection traversal | Must retain exceptional edges and cleanup blocks; irreducible CFG policy. Enables most proposed work. | M; enabling; slight growth | **P0** |
| Induction-variable optimization | `sum_to`, countdown, nested loops, indexing | Checked integer overflow/trap semantics make widening/reassociation unsafe; range endpoints/step and exits. LLVM handles canonical IVs well. | H; M; neutral | **DEFER TO LLVM** after canonicalization; Aether only facts for BCE |
| Interprocedural constant propagation | constant arguments to small helpers (`mix`, `clampScore`) | Recursion/SCCs, separate compilation, code cloning and ownership/effects. LLVM LTO/inlining does this better. | H; L-M; grows | **DEFER TO LLVM/O3** |
| Devirtualization | locally constructed interface values and stable witnesses | Open-world packages, boxed versus class carrier, throws and ownership adapters. Aether retains witness identity LLVM may not reconstruct. | M-H; M-H; neutral/smaller | **P1**, local exact-witness only |
| Redundant interface-box elimination | struct value immediately boxed, dispatched, dropped | Value ownership/copy/drop, identity, escape and exceptional cleanup. High-level win unavailable to LLVM. | H; M-H; smaller | **P2** after escape + devirt + ownership |
| Nullable/tag check elimination | repeated dominated checks on nullable reference-like values | Mutation/alias/calls may replace value; preserve panic/exception order. LLVM may remove obvious repeated branches; Aether has tag semantics. | M; M; smaller | **P1** via generic predicate facts |
| Runtime shape-check elimination | repeated Vector/Matrix compatibility checks | Shape mutation/alias/calls; check ordering and exact panic. Static nominal/dimensional facts are Aether-only. | M; H in linear algebra; smaller | **P0** for statically proved shape, then range framework |
| Vectorization-enabling transforms | dot products, matrix multiply, numerical reductions | Strict FP prohibits reassociation/reduction reorder; checks/calls/ARC inhibit loop vectorizer. LLVM should vectorize legalized canonical loops. | H; potentially H; may grow | **DEFER TO LLVM**; Aether exposes no-check/noalias loops |

Not recommended for current O2: a home-grown generic GVN/CSE suite,
interprocedural constant propagation, generic IV rewriting, or a vectorizer.
They duplicate LLVM while the missing semantic analyses remain the real
constraint.

## 4. Workload evidence

The audited deterministic suite contains `arithmetic`, `if_else`, `sum_to`,
`while_countdown`, `nested_loops`, `array_sum`, `list_for_sum`, `list_push`,
`vector_dot`, and `matrix_mul`. The Newton/Raphson dogfood in
`examples/ProbandoNR` adds indirect function-value calls and a returned struct;
`examples/SNL.ae` and least-squares examples add Vector/Matrix construction,
indexing and linear algebra. Exception, interface/class, struct, nullable and
ownership cases are primarily correctness tests/corpora, not timed workloads.

Inspection gives concrete hot-operation candidates, not measured attribution:

* `array_sum` performs 2,000 indexed loads plus repeated length reads; the
  loop condition is the natural proof source for BCE if no mutation occurs.
* `list_for_sum` uses a borrow-constrained traversal, a particularly strong
  source-level non-mutation fact that is not yet an optimizer fact.
* `list_push` is allocation/reallocation and mutation dominated; BCE alone is
  not the main target.
* `vector_dot` repeatedly constructs fixed-shape values and calls a helper;
  shape/allocation elimination plus downstream vectorization matter more than
  scalar algebra folding.
* `matrix_mul` repeatedly allocates a result and executes nested arithmetic and
  index/shape checks; it combines all proposed enablers.
* Newton uses indirect calls `f`/`df` in its convergence loop, strict FP
  division/power, and returns an aggregate; indirect-call overhead is plausible
  but cannot be called a bottleneck without a long-running benchmark.
* Recursive and class/interface-heavy programs have correctness coverage but no
  representative performance benchmark. This is a measurement gap.

A five-repetition native smoke measurement on the audit host produced:

| Program | O1 run avg | O2 run avg | O1 build avg | O2 build avg |
|---|---:|---:|---:|---:|
| `array_sum` | 0.465 ms | 0.516 ms | 70.464 ms | 73.736 ms |
| `vector_dot` | 0.564 ms | 0.489 ms | 65.324 ms | 64.491 ms |

All executions passed. These sub-millisecond process measurements contradict
each other in direction and are dominated by launch/noise; they are evidence
that the existing harness/program sizes cannot establish O2 runtime wins, not
evidence for a regression or speedup. Generated IR inspection confirms the
current Aether O1/O2 middle-end identity by profile definition; only clang's
level differs.

Likely cost centres must therefore be validated with scaled kernels and code
metrics: collection runtime/helper calls and checks, allocation/copy/release,
interface/indirect dispatch, and nested numerical loop bodies.

## 5. Inlining readiness

The IR represents direct calls, indirect function-value calls, direct methods
as lowered functions, constructors, interface calls/invokes and exceptional
successors. It also retains `may_throw`, source locations on calls, function
ownership operations, witness slots, borrowed iteration scope, and explicit
event-out behavior in lowering. These are necessary but insufficient.

Missing prerequisites are a call graph with recursion SCCs; a per-function
summary (throw/trap, read/write/allocate, capture, ownership transfer); stable
formal ownership modes; a block/value cloner that preserves source provenance;
exceptional CFG/cleanup remapping; and a cost/budget model. Debug provenance is
call-site only and has no inline-stack representation.

The minimum safe O2 inliner is deliberately small:

1. direct, resolved, non-recursive calls only (exclude an entire recursive SCC);
2. nonthrowing callee and ordinary `IRCall` only initially—no invoke/event-out,
   handler, constructor failure, interface thunk, or cleanup cloning;
3. scalar or trivially value-semantic parameters/results with no borrowed
   parameter, owned-result transfer, class/interface carrier, or lifecycle
   operation initially;
4. single return, verified CFG, fresh names, call-site plus original source
   provenance;
5. small instruction threshold, per-caller and module growth budgets; and
6. reverify IR and SSA, then rerun SCCP/DCE.

Methods/constructors become eligible only when they satisfy those rules.
Indirect calls require exact-callee propagation; interface calls require the
devirtualization proof first. LLVM should remain the default direct inliner;
an Aether inliner earns its place only when it exposes Aether-only ownership,
shape or dispatch facts.

## 6. ARC readiness

Lifecycle expansion can produce apparently redundant retain/release sequences
around copies, assignments, short-lived temporaries, interface carrier copies,
class values, strings, Array/List and nullable reference-like values. Obvious
syntactic candidates include retain immediately followed by release with no
intervening escape, self-assignment's retain-before-release sequence, a copied
temporary killed before use, and an interface box copied then dropped.
Syntactic adjacency alone is not a safe proof.

Required ownership dataflow is a forward lattice per owned identity/location:
uninitialized, owned(+1), borrowed, moved/consumed, released, escaped/unknown,
merged conservatively at phis and CFG joins. It needs copy/move provenance,
liveness to the last use, alias sets, capture/mod-ref call summaries, destructor
effects, and separate normal/exceptional edge states. Retain/release deletion
must preserve object lifetime and observable deinitialization order, not merely
net reference count.

Exception cleanup ladders and rethrow transfer event/object ownership; partial
constructor initialization owns only completed fields; an alias can observe a
premature destructor; and FFI/native calls must capture and mutate unless an
ABI annotation proves otherwise. Interface boxes have payload adapters and
class carriers differ from boxed structs. Self-assignment specifically requires
retaining before releasing unless non-alias is proven. These constraints make
local ownership dataflow plus conservative alias/capture summaries the minimum,
with pair elimination initially restricted to one block, one identity, no call,
no exceptional edge, and non-observable destructor timing.

## 7. Bounds-check readiness

Array/List indexing and slicing use runtime checks; Vector and Matrix indexing
uses dedicated helpers with shape/index checks. List mutation changes length and
may reallocate. Vector/Matrix static type shapes provide some compile-time facts,
while Array/List lengths are dynamic. `for-in` over Array/List forbids structural
mutation and borrowed elements cannot escape, but that fact is not exported as
an optimizer analysis. Slicing has ordering and endpoint checks in addition to
element bounds.

SCCP is insufficient for `while (i < a.length) a[i]`: it knows constants, not
intervals or the relationship between the branch and the indexed successor.
Required analysis is dominance-scoped predicate/range propagation over checked
integers, with intervals plus symbolic bounds (`0 <= i < length(a)`), canonical
phi/IV recognition, and collection shape/length identities. Every write/call is
tagged with a mutation epoch; length facts are killed by structural mutation,
possible aliases, unknown/interface/indirect/native calls, or replacement of
the collection. Element writes need not kill length but may trap and still
constrain motion.

The first BCE should remove a check only when an equivalent dominating check or
the immediately dominating loop predicate proves it on every path, and when no
invalidating operation intervenes. It must not move a panic earlier/later,
coalesce distinguishable slice errors, or remove an earlier failing check in
favor of a later one. Static Vector/Matrix literal dimensions and canonical
Array/List traversal are the first promotion cases.

## 8. Loop readiness

CFG, reachability and dominators are robust enough to identify backedges
(`header` dominates `latch`) and natural-loop block sets. Nothing currently
constructs those sets or handles nested/irreducible loops. The minimal layer is:

* a loop forest with headers, latches, bodies, nesting, exits and exceptional
  exits;
* an explicit irreducible-loop classification (analyze conservatively; do not
  transform initially);
* canonical preheader insertion and dedicated latch/exit handling with phi
  repair and immediate reverification;
* LoopSimplify-style invariants documented for normal and exceptional CFG;
* scalar-evolution-lite recognition of `{start,+,step}` checked-integer phis;
* preserved/invalidated analysis declarations.

That enables range proofs and semantic LICM. It does not itself authorize
moving traps, ownership operations or memory accesses.

## 9. Actual alias model and minimum O2 analysis

* Structs are value-semantic, but nested owned fields require lifecycle actions;
  distinct SSA struct values are not automatically disjoint after address-like
  lowering.
* Classes have reference identity and arbitrary aliases; field mutation is
  visible through aliases.
* Strings are reference-like owned values. Treat their backing storage as
  immutable only where the builtin contract says so; trim/split allocate/mutate
  runtime state as modeled.
* Array/List values own mutable collection storage. Assignment/copy and element
  access semantics must determine whether storage is shared; absent a proof,
  assume aliases. List structural calls invalidate length/capacity/data facts.
* Vector/Matrix are shaped value containers, but lowering/runtime allocations
  and nested lifecycle types prevent blanket pointer noalias assumptions.
* Interfaces backed by classes alias their class carrier. Boxed structs have an
  owned payload and box identity/adapter lifecycle; copies may allocate.
* Borrowed iteration elements alias their collection element for a bounded
  scope and cannot escape or be used for mutation as currently verified.
* Unknown direct calls, function values, interface calls, and native boundaries
  may read/write/capture reachable memory unless summarized.

Useful cheap facts are SSA scalar nonalias, disjoint local stack/storage slots,
fresh allocation versus pre-existing nonescaped values, distinct nonescaped
fresh allocations, field-path disjointness within a value aggregate, immutable
static shape, and borrow-scope collection identity. Type alone must not claim
that two class/collection references do not alias.

O2 needs level 2 below, not flow-sensitive or interprocedural points-to:

1. noalias-by-value/type facts for scalars, values and disjoint local storage;
2. **recommended:** function-local alias classes plus instruction/call mod-ref,
   fresh-allocation and capture-unknown, with conservative merge at phis;
3. flow-sensitive points-to/field sensitivity—P2/research;
4. interprocedural aliasing—research; use summaries instead.

## 10. Escape readiness

Allocation sites include classes, struct-backed interface boxes, strings and
string operations, Array/List storage, and temporary Vector/Matrix/aggregates.
The IR marks allocation effects but does not give all sites a common allocation
identity or capture semantics. Add allocation-site IDs and a conservative
intraprocedural escape graph: return, store into escaping object/global,
capturing call, interface conversion, function closure/environment, and native
call escape; local load/store/copy and known nocapture calls do not.

Nonescaping class instances may be stack allocated but identity (`==`, self
references, weak/native observation if introduced) must remain stable during
their lifetime. Boxed structs can be scalar-replaced only if interface identity,
witness dispatch, copy/drop adapters and address observation remain equivalent.
Strings and collections require dynamic size/backing storage and are poor first
stack-promotion candidates. Fixed temporary aggregates and short-lived
interface boxes are better later targets. Do not promote or eliminate allocation
until allocation failure/trap semantics and destructor timing are specified.

## 11. Devirtualization readiness

`IRInterfaceConstruct` carries exact interface ID, concrete type ID, carrier
kind, witness symbol and ordered slots. Exact type can therefore be known at a
construction site and propagated through local copies/phis when all incoming
witnesses are identical. A final witness or whole current module can improve a
proof, but module closure must not be treated as language closure: future
separate compilation/packages may add implementations.

The safe first transform is local exact-witness devirtualization only: a
dominating construction reaches the call without an unknown store/call and all
merged paths name the same witness/slot. Rewrite to the recorded concrete
target while preserving boxed/class receiver adaptation, ownership, `may_throw`
and invoke successors. Closed-world class-hierarchy or “only implementation in
this build” reasoning is not O2-safe without an explicit visibility/sealing
contract.

## 12. Exception-aware constraints

Optimization legality needs an ordered effect model, not only purity:

```text
normal effects: read/write/allocate/retain/release
abrupt effects: panic(trap kind) | throw(event type/ownership)
control effects: handler selection + normal/exceptional successor
```

Inlining, LICM, GVN/CSE of trapping expressions, BCE/check elimination, ARC,
allocation elimination and devirtualization all need explicit exceptional
effects. They must preserve which panic/exception happens first, event ownership
on each edge, cleanup/destructor order, replacement exceptions during cleanup,
rethrow identity, partial initialization and handler selection. Panic never
becomes a catchable event. `Error.message()` remains nonthrowing in summaries
and transformed witnesses. SCCP/DCE may delete unreachable code or unused pure
values but may not erase a reachable throw/trap/lifecycle action.

## 13. Floating-point policy

Current enabled Aether algebraic simplification is integer-only. Constant
folding evaluates the same scalar operation without reassociation and declines
trapping integer folds. There is no fast-math flag; treat FP as strict IEEE-like
source order, including NaN, infinities and signed zero.

Without a new policy: literal folding with exactly equivalent rounding is
legal; dead unused nontrapping FP computation is legal; control-independent
loads/stores may be optimized under normal alias/effect rules; and SIMD of
lane-independent operations is legal if it does not speculate traps or change
per-element order. Reassociation, reciprocal approximations, reduction
reordering, contraction to FMA (unless the source operation is explicitly
fused), and transformations changing NaN/signed-zero behavior are illegal.
Future `contract`, `reassociate`, `no-nans`, reciprocal and approximate modes
must be explicit user-visible policy, separately testable; do not enable
`fast-math` wholesale.

## 14. LLVM delegation boundary

Delegate scalar CSE/GVN, ordinary direct inlining, scalar replacement of already
visible LLVM aggregates, loop unrolling/rotation, IV simplification, strength
reduction, machine-level LICM and vectorization to clang/LLVM `-O2`. Aether
should instead expose stable facts via simple IR, attributes/metadata where
sound, and removal of semantically redundant runtime barriers.

Aether-side work is justified for ownership/ARC, bounds and panic equivalence,
nominal witness identity, boxed carriers, static/dynamic collection shape,
borrow-proven nonmutation, exception event ownership, and high-level value
semantics. Even there, transform only the high-level obstruction and let LLVM
finish the low-level optimization.

## 15. Measurement plan

Use a pinned clang version/target/CPU governor, isolated core where possible,
and report hardware, OS and compiler revision. Compile once for runtime tests.
Warm up 5 process runs (or 1 s, whichever is longer), then collect at least 30
samples; make each sample run the kernel long enough to exceed 100 ms. Report
median, MAD, p95 and bootstrap 95% confidence interval. Compare interleaved
O1/O2 runs. Accept <=2% noise only; flag >=3% median regression with a CI not
crossing zero, and require >=5% repeatable win to promote a pass. Preserve every
program's result/exception/panic/output as the correctness oracle.

| Benchmark group | Isolation/oracle | Code metrics |
|---|---|---|
| canonical Array/List/Vector index loops, sliced edge cases | range+BCE; checksum plus exact first panic cases | checks/helper calls, branches, loop instructions |
| nested loops, invariant length/shape reads | loop form + semantic LICM; checksum | preheaders, loads/checks in body |
| dot, axpy, matrix multiply, transpose/solve/Newton | scientific end-to-end; tolerance only where language/test already permits, otherwise bit/result exact | vector instructions, loop body, allocations |
| retain/copy/drop chains, self-assignment, nullable refs, class/string/Array/List | ARC; destructor counters/order plus leak/ASan gate | retain/release counts, allocations |
| local/nonlocal interface construction and calls (class + boxed struct) | devirtualization/box elimination; dispatch result and lifecycle counters | indirect calls, boxes, code size |
| direct/indirect/recursive/mutually recursive small functions | inliner/call summaries; exact return/exception | calls, text size, compile time |
| temporary structs/classes/collections | escape/DAE/SROA; identity, destruction and failure cases | malloc/free, stack bytes, loads/stores |
| exception-heavy mirrors | optimization safety; exact event/handler/cleanup trace | exceptional blocks, landing/cleanup size |

Also track Aether IR/SSA instruction/block/phi counts, LLVM IR checks/calls,
native `.text`, compile time, peak RSS, allocations and ARC operations. Run
sanitizers on correctness variants, not timed samples. Existing benchmark
semantics stay unchanged; add scaled siblings rather than editing them.

## 16. Derived dependency graph

```text
reusable CFG + dominance + exceptional reachability
  -> loop forest + canonical form
       -> IV/range + predicate facts <- collection shape/length identities
             <- local alias classes + mod/ref + mutation epochs
             -> bounds/shape/tag-check elimination
             -> expose canonical no-check loops -> LLVM vectorizer

instruction effects + call graph/SCCs
  -> per-function throw/trap/mod-ref/capture/ownership summaries
       -> minimum safe inliner -> SCCP/DCE and LLVM
       -> local exact-witness propagation -> devirtualization

lifecycle provenance + local alias/capture + exceptional ownership dataflow
  -> conservative ARC pair elimination
  -> escape analysis
       -> dead allocation / interface-box elimination
       -> scalar replacement / stack promotion

analysis preservation/invalidation + verifier gates support every transform
```

## 17. Priorities

**P0:** analysis manager/invalidation discipline; reusable exceptional CFG and
reachability; loop forest/canonicalization; local alias/mod-ref/capture facts;
integer predicate/range and collection length/shape facts; static shape-check
and canonical-loop BCE. These directly serve the existing numerical suite.

**P1:** call graph/SCC/effect summaries; ownership dataflow; conservative local
ARC pair elimination; intraprocedural escape analysis; local exact-witness
devirtualization; dominated nullable/tag checks; only then assess the minimum
safe inliner.

**P2:** semantic LICM, redundant interface-box/dead-allocation elimination,
SROA/stack promotion, broader ARC and shape-value numbering.

**RESEARCH:** flow-sensitive/interprocedural alias analysis, identity-aware
class promotion, throwing/invoke inlining, whole-program devirtualization,
user-controlled relaxed FP.

**DEFER TO LLVM:** generic GVN/CSE, generic direct inlining, IV optimization,
interprocedural constant propagation/LTO, generic LICM/SROA and vectorization.

**NOT RECOMMENDED:** enabling fast-math implicitly, closed-world dispatch based
only on today's module, deleting ARC by net-count arithmetic, or hoisting/
coalescing checks without panic-order proof.

## 18. Staged O2 roadmap and promotion gates

1. **Measurement and analysis contracts.** Add scaled benchmarks/code metrics,
   analysis result interfaces, invalidation tests, reusable reachability and
   exceptional CFG tests. No O2 transform. Promote when O1 is unchanged and
   analysis results are deterministic and verifier-clean.
2. **Loops and semantic values.** Add loop forest, irreducibility reporting,
   preheaders/latches with phi repair, local alias/mod-ref/mutation epochs,
   range predicates and shape/length identities. Test nested/multiple-exit and
   exceptional loops, checked overflow, collection mutation and every index
   convention. Promote analyses before consumers.
3. **First O2 transforms.** Eliminate statically redundant shape checks and
   dominated/canonical-loop bounds checks without moving operations. Differential
   tests must cover exact panic order and alias invalidation; require >=5% wins
   in affected long kernels, no >=3% regression, and stable code-size/compile
   time. O2 may remain identical to O1 until these gates pass.
4. **Calls and dispatch.** Add call graph/SCC and conservative effects/capture,
   exact-witness propagation, then local devirtualization. Test open-world
   boundaries, class/box adapters, recursion and throwing slots. Promote only
   on reduced indirect calls plus measured interface wins.
5. **Ownership.** Add normal/exceptional ownership dataflow and ARC provenance;
   enable block-local proven pair elimination. Gate with lifecycle verifier,
   exception promotion, destructor-order fixtures, sanitizer/leak runs and
   ownership-heavy benchmarks.
6. **Escape and allocation.** Add allocation IDs and escape graph, then attempt
   dead boxes/aggregates. Stack promotion/SROA and semantic LICM remain opt-in
   experiments until identity, allocation-failure and cleanup semantics pass.
7. **Reassess.** Compare generated LLVM and native profiles. Add an Aether pass
   only where measurements demonstrate information LLVM cannot recover.

No unfinished or unsafe pass becomes part of O2: each stage ships analysis
independently or leaves the current truthful O1-middle-end/clang-`-O2` profile
intact.

## 19. Risks and stop conditions

The dominant risks are panic-order changes from BCE/LICM; lifetime/destructor
changes from ARC/escape/inlining; losing exception-event ownership or cleanup
edges; treating value semantics as physical nonalias; assuming a closed world;
checked-integer overflow changes in IV/range transforms; and accidental FP
reassociation. Any differential semantic failure, verifier failure, lifecycle
imbalance, handler/cleanup divergence, or ambiguity in allocation failure/
destructor observability stops promotion. A discovery of current O1 unsoundness
must be reported and remediated separately, not hidden in an O2 pass.

## 20. Explicitly deferred work

This audit does not implement an inliner, ARC elimination, BCE, loop transform,
alias/escape analysis, devirtualization, allocation promotion, GVN/CSE, LICM,
SROA, IV transform, IPCP or vectorizer. It does not change language semantics,
safety, IR/SSA design, public profile mapping, benchmark semantics, FP policy,
package assumptions or LLVM flags.

## 21. Audit validation record

The audit ran 247 focused optimizer, operand-coverage, profile and SCCP tests;
all passed. ERQ-006 passed its frontend/IR/SSA mode (11 positive, 9 negative,
44 differential comparisons). Its native sanitizer mode could not run in this
execution environment because LeakSanitizer reported that it cannot operate
under ptrace; this is an environmental limitation, not a semantic mismatch
observed in Aether output. Capability consistency and release-documentation
integrity passed, as did `git diff --check`. The two O1/O2 native smoke pairs
above had zero failures. Because production code and benchmark semantics are
unchanged, a complete suite was not run.

## O2.6 update

O2 now adds conservative non-speculative scalar LICM after proven BCE and
before DCE. O0/O1 remain unchanged. See `O2_LICM.md`; it supersedes historical
statements in this readiness audit that LICM is not implemented.

## O2.8 update

Exception-aware ownership/escape analysis now exists without enabling a
transform. Status is `IMPROVE_OWNERSHIP_ANALYSIS_FIRST`; see
`O2_OWNERSHIP_ESCAPE_ANALYSIS.md`.

## O2.8.5 update

The productive-corpus ARC opportunity audit found a nonzero conservative local
scope. Status is `PROCEED_TO_LOCAL_ARC_ELIMINATION`, limited to exact-identity,
exception-free pairs satisfying all O2.8 proof gates. See
`O2_ARC_OPPORTUNITY_AUDIT.md`; this milestone changes no ARC operation or
optimization-profile membership.
