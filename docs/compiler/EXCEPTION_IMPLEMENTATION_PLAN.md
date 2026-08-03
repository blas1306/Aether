# Exception Implementation Plan

- **Status:** Engineering roadmap
- **Phase:** 7.1 — Complete Exception Model
- **Authority:** `EXCEPTION_ARCHITECTURE_RESOLUTION.md` and its referenced
  architecture documents
- **Nature:** Implementation plan, not an RFC

## Planning contract

This plan implements the frozen exception architecture. It does not reopen language
design. In particular, Aether exceptions are unchecked; `Error` is a built-in
interface; `throw` is statement-only; catches use exact concrete-type matching with
an `Error` catch-all; exception events have linear ownership; cleanup is explicit
before SSA; panic remains a separate, non-recoverable mechanism; and exceptions
must not cross raw C boundaries.

The three decisions intentionally left to implementation engineering are the SSA
edge representation, the backend lowering strategy, and the private runtime ABI.
Each must be recorded before the affected milestone begins. These records are
implementation ADRs, not language RFCs: they may choose different mechanisms on
different backends only if all approved source semantics, ownership rules, cleanup
ordering, diagnostics, and FFI containment remain identical.

Exceptions remain behind the `ERROR_HANDLING` capability until Milestone 12. No
intermediate milestone may silently enable partially implemented behavior in the
stable capability profile. Tests are added with the milestone that introduces the
behavior; Milestone 11 closes cross-layer gaps and supplies system-level evidence.

## Milestone dependency graph

```text
M0 Preparation
├── M1 Syntax/AST ──> M2 Typechecker ──> M3 Initial IR ──> M4 Lifecycle
│                                                      └──> M5 SSA ──> M6 Optimizers
├── SSA representation ADR ────────────────────────────────────────┘
├── backend/runtime ADRs ───────────────────────────────> M7 Backend + M8 Runtime
│                                                         └──────────────> M9 FFI
└── M1 + M2 ──────────────────────────────────────────────────────> M10 Tooling

M1–M10 test evidence ──> M11 Integrated testing ──> M12 Capability promotion
```

Milestone numbering expresses review order, not an absolute serialization rule.
The backend and runtime must be developed together after their shared ABI contract
is selected. Tooling work can proceed once syntax and semantic diagnostics are
stable. Every milestone depends on the frozen architecture and on the continued
validity of all earlier milestone acceptance criteria.

# Milestone 0 — Preparation

## Goal

Turn the approved architecture into a complete, reviewable work inventory without
changing compiler, runtime, or tool behavior.

## Scope

- Review the four exception architecture documents and extract a frozen-semantics
  checklist used by every later review.
- Inventory all affected components:
  - tokens, lexer, parser, AST, formatting, equality, and AST interpretation;
  - built-in types, symbols, scopes, type checking, modules, entry-point handling,
    capabilities, diagnostics, and differential execution;
  - Initial IR model, effect metadata, lowering, CFG analysis, lifecycle expansion,
    operand traversal, serialization, printing, interpretation, and verification;
  - Python and Rust IR schemas, importers, structural/lifecycle/dominance/SSA
    verifiers, and shadow/canary comparison paths;
  - SSA construction, dominance/frontier analysis, renaming, phi or block-argument
    placement, printing, and verification;
  - every Initial IR and SSA optimizer;
  - LLVM lowering, runtime support, native layout/type descriptors, build/run
    harnesses, and the native ABI documentation;
  - FFI adapters, formatter, language service, LSP, editor highlighters,
    completion, CLI views, capability profiles, CI, release scripts, and tests.
- Identify existing experimental exception support and document how each part will
  be replaced or retired. Existing `try`/`catch`/`throw` tokens, single-catch AST,
  string/`Exception` checks, and host-language interpreter signals are migration
  inputs, not approved semantics.
- Prepare implementation ADR templates and decision criteria for:
  1. exceptional SSA edge/value representation;
  2. LLVM/backend propagation strategy;
  3. the private runtime event ABI.
- Capture a baseline of all relevant test suites and supported toolchains.

## Dependencies

- The frozen RFC, decision log, checked-exception study, and architecture
  resolution.
- Current strategic roadmap, capability profiles, native ABI notes, and CI policy.
- Agreement that this milestone performs no behavior-changing work.

## Deliverables

- Reviewed component inventory with named owners or work areas.
- The dependency graph above, refined with repository-level tasks where needed.
- Frozen-semantics review checklist.
- Experimental-support migration inventory.
- Three implementation ADR templates with measurable comparison criteria.
- Baseline test and toolchain report.

## Acceptance criteria

- Every compiler stage and every independent representation of Aether programs has
  an identified exception impact or an explicit “no change required” finding.
- Python/Rust schema and verifier parity, editor integrations, capability gating,
  and FFI are present in the inventory.
- No observable behavior, source file, generated artifact, or capability profile
  has changed.
- Later milestones have no unresolved architectural dependency; only the three
  approved implementation choices remain open.

## Required tests

- Run and record the existing parser, typechecker, IR, lifecycle, SSA, optimizer,
  backend, runtime, language-service, capability, Python/Rust parity, and native
  suites.
- Record LLVM/Clang and Rust toolchain versions used by CI.
- Hash or otherwise identify the baseline exception architecture documents so
  accidental edits are detectable.

## Risks

- Treating experimental support as normative could preserve semantics the
  architecture explicitly superseded.
- Missing a parallel schema, verifier, or editor frontend could produce partial
  end-to-end support.
- An implementation ADR could accidentally encode a language change. The frozen
  semantics checklist must be mandatory in each ADR review.

# Milestone 1 — Lexer / Parser / AST

## Goal

Represent the frozen exception syntax accurately, with complete source locations
and lossless formatting, while leaving semantic validation to later stages.

## Scope

- Recognize `throw`, `try`, and `catch` consistently in the lexer and token model.
- Parse statement-only `throw expression;` and bare `throw;`.
- Parse `try` followed by one or more ordered catches and support nesting in any
  statement block.
- Represent typed catch clauses with their required lexical binding, the
  `catch (name)` sugar for `catch (Error name)`, ordered multiple catches, and
  bare rethrow context in AST nodes.
- Represent built-in `Error` interface references through the normal type syntax;
  no parser-only exception type hierarchy is introduced.
- Replace or migrate the experimental single untyped catch AST without accepting
  its old semantics accidentally.
- Update AST traversal, equality, source formatting, diagnostic recovery, syntax
  highlighting, and any AST serialization or debug rendering.

## Dependencies

- Milestone 0 inventory and frozen syntax checklist.
- Existing block, type-reference, binding, and source-span conventions.
- A settled canonical surface spelling for catch clauses as already specified by
  the RFC; this milestone does not invent alternate syntax.

## Deliverables

- Lexer/token updates and complete AST node definitions.
- Parser productions for throws, bare rethrows, multiple catches, and nested
  try/catch.
- Parser recovery at missing expressions, delimiters, types, bindings, blocks, and
  catch clauses.
- Canonical formatter output and updated syntax definitions for all shipped editor
  integrations.
- AST visitor/equality/debug-printer coverage for every new node and field.

## Acceptance criteria

- All legal exception forms parse into ordered, source-located ASTs.
- `throw` is accepted only as a statement; bare `throw;` is represented distinctly
  from throwing an expression.
- Multiple catches retain source order, and nested constructs retain lexical
  structure.
- Formatter output is stable and idempotent.
- Parser tests, formatter tests, and syntax-highlighting tests are green.
- The stable capability remains disabled; parsing alone does not imply the feature
  is ready for compilation.

## Required tests

- Positive parser cases for expression throw, bare rethrow, typed catch bindings,
  root-catch sugar, multiple catches, and deeply nested try/catch.
- Negative and recovery cases for `throw` in expression position, missing thrown
  expressions, malformed catch headers, absent catch bodies, and a `try` without a
  catch; verify that `finally` is not accepted as exception syntax in 1.x.
- AST equality/traversal and source-span tests.
- Formatter golden tests and parse–format–parse idempotence tests.
- Token/highlighting tests for VS Code and IntelliJ, plus shared LSP completion
  and diagnostics tests.

## Risks

- Grammar recovery around `throw;` can consume the next statement or generate
  misleading errors.
- A lossy catch AST can prevent later exact-match and ordering diagnostics.
- Hand-maintained editor grammars can drift from the compiler grammar.
- Broad parser changes could make the experimental syntax appear supported before
  downstream stages are ready; capability gates must remain fail-closed.

# Milestone 2 — Typechecker

## Goal

Enforce the approved user-visible exception rules while preserving unchecked
semantics: a function may throw without declaring an exception effect in its source
signature.

## Scope

- Install `Error` as the built-in root interface and validate conforming struct and
  class declarations through ordinary interface conformance.
- Reject thrown values whose non-null static type does not implement `Error`.
- Validate catch types, bindings, ordering, duplicates, and reachability under
  exact concrete-type matching plus the `Error` catch-all.
- Validate bare rethrow only inside the dynamic handler body of an active catch;
  nested functions, callbacks, or unrelated lexical blocks do not inherit that
  permission.
- Type catch bindings according to the caught concrete type or `Error` catch-all,
  enforce their catch-scoped borrow and no-shadowing rule, and prevent the borrow
  from escaping except through an ordinary owning copy.
- Preserve multiple-catch source order and nested-handler semantics.
- Keep panic typing and control-flow behavior distinct from throw.
- Model exception-producing operations conservatively for internal control-flow
  analysis without exposing `throws` clauses, catch-or-declare rules, exception
  sets in interface requirements, or exception effects in function types.
- Update the AST/reference interpreter where it is used for semantic parity so it
  obeys the frozen rules rather than host-language exception matching.

## Dependencies

- Milestone 1 AST and source locations.
- Existing built-in interface, conformance, method, constructor, nullable, and
  control-flow analyses.
- The architecture resolution selecting unchecked exceptions.

## Deliverables

- Built-in `Error` interface registration and conforming-type validation.
- Throw, catch, ordering, exact-match, and rethrow semantic checks.
- Stable diagnostic identifiers, primary spans, and actionable related spans.
- Internal conservative “may throw” facts where later lowering needs them; these
  facts remain compiler metadata, not source-level contracts.
- Updated semantic/reference-interpreter behavior and removal or quarantine of the
  old string/experimental `Exception` rules.

## Acceptance criteria

- Valid struct and class errors, nested handlers, multiple catches, exact matches,
  catch-all handling, and legal rethrows typecheck.
- Invalid thrown values, nullable errors, malformed catch types, duplicate or
  structurally unreachable catches, and out-of-handler rethrows are rejected at
  the correct source location.
- No declaration is rejected merely because it may throw, and no public function,
  method, interface, callback, or constructor type gains a checked exception
  component.
- Panic remains outside catch matching.
- Positive and negative semantic suites are green with stable diagnostics.

## Required tests

- Positive tests for struct/class `Error` conformance, polymorphic `Error` catches,
  methods, constructors, nested scopes, callbacks, and higher-order calls.
- Negative tests for primitive/string throws, nullable throws, non-`Error` catch
  types, duplicate exact catches, catches after `Error`, and bare rethrow outside a
  catch or inside a nested function.
- Tests proving exact matching does not use class inheritance or interface
  assignability other than the root catch-all rule.
- Tests proving unchecked source compatibility: overrides, interface methods, and
  function values do not change type when their bodies begin to throw.
- Diagnostic snapshot and interpreter parity tests.

## Risks

- Reusing normal subtype matching for catches would violate exact matching.
- Internal throw summaries could leak into source signatures and accidentally
  create checked exceptions.
- Lexical implementation of rethrow can be too permissive across nested function
  boundaries.
- Special-casing `Error` outside the normal interface machinery could diverge from
  ordinary struct/class conformance.

# Milestone 3 — Initial IR

## Goal

Make exceptional control flow and exception-event ownership explicit in Initial IR
so every downstream stage can reason about it without reconstructing hidden edges.

## Scope

- Add a distinct catchable `may_throw` effect to the instruction-effect model;
  retain panic/trap as a separate effect with separate semantics.
- Define Initial IR operations and terminators for:
  - invoking a potentially throwing operation with normal and exceptional
    successors;
  - packing a validated `Error` value into an opaque exception event;
  - throwing a new event;
  - propagating an existing event;
  - exact descriptor matching and the `Error` catch-all;
  - borrowing the caught payload and transferring or destroying the event.
- Represent handler entry and event flow explicitly. Normal results exist only on
  normal edges; exception events exist only on exceptional edges.
- Lower ordered catches, nested handlers, legal rethrow, unhandled propagation,
  returns, and loop exits into explicit CFG structure.
- Extend CFG analysis, operand traversal, cloning/equality, printers, DTO/JSON
  schemas, interpreters, and all verifier entry points.
- Update both Python and Rust IR consumers atomically; old schemas must reject new
  constructs rather than ignore them.
- Mark unknown or indirect calls conservatively until a proven internal summary
  says they cannot throw.

## Dependencies

- Milestone 2 semantic AST.
- The frozen exception-event state machine and matching rules.
- A versioned schema plan shared by Python and Rust tooling.
- Runtime-neutral event operations; no LLVM mechanism is selected here.

## Deliverables

- Initial IR instruction/terminator and edge-kind model.
- Lowering for throw, rethrow, try/catch, ordinary calls, and root propagation.
- Effect summaries that distinguish catchable throw from panic/trap.
- CFG and verifier rules for successor shape, event use, handler structure, and
  terminated blocks.
- Updated IR printer, interpreter, DTO/schema, Python verifier, Rust importer and
  verifier, and shadow/canary fixtures.

## Acceptance criteria

- Printed IR exposes every normal and exceptional successor.
- No potentially throwing instruction relies on an implicit fallthrough or hidden
  handler table in Initial IR.
- The verifier rejects missing successors, wrong-edge values, malformed handler
  chains, illegal event use, and schema mismatches.
- The IR interpreter implements the same handler selection and propagation as the
  semantic/reference interpreter.
- Python and Rust verification agree on valid and invalid exception fixtures.
- IR verifier, printer, interpreter, serialization, and parity suites are green.

## Required tests

- Golden lowering tests for new throw, rethrow, multiple and nested catches,
  catch-all, propagation, calls in expressions, calls in loop conditions, returns,
  breaks, and continues.
- IR verifier rejection tests for malformed edge arity/kinds, missing events,
  normal results on exceptional edges, duplicate event consumption, and handler
  fallthrough.
- Printer round-trip or stable-golden tests and DTO/JSON compatibility tests.
- Python/Rust valid-invalid fixture parity, shadow, and canary tests.
- IR interpreter parity tests for caught and unhandled failures and for panic
  bypassing catches.

## Risks

- Treating exception edges as metadata instead of CFG edges would invalidate later
  dominance and optimization.
- Combining `may_throw` with `may_trap` would permit catching panic or suppressing
  required cleanup.
- Schema changes can split Python and Rust definitions of valid IR.
- Overly optimistic call summaries can remove propagation paths; conservative
  summaries can enlarge CFGs but remain correct.

# Milestone 4 — Lifecycle

## Goal

Guarantee deterministic ARC cleanup on every exceptional path, including
construction rollback, while maintaining exactly one owner of a live exception
event.

## Scope

- Extend pre-SSA lifecycle planning to compute cleanup ladders for exceptional
  edges as well as return, break, continue, and normal scope exit.
- Clean initialized locals and temporaries in strict reverse initialization order
  from the throw point to the selected handler boundary; continue outward when no
  catch matches.
- Roll back only initialized parts of structs, classes, arrays, lists, interface
  boxes, nullable wrappers, and constructor aggregates.
- Define event ownership transitions: acquire or form the event before source-value
  cleanup, transfer it along exactly one exceptional edge, borrow its payload
  during matching/handling, and destroy it exactly once when consumed.
- Make rethrow transfer the existing event without repacking, copying, or changing
  descriptor identity.
- Integrate exceptional cleanup with nested scopes and all early exits without
  changing panic’s approved no-cleanup behavior.
- Extend lifecycle expansion and verification; shared cleanup blocks are allowed
  only when their initialized-object set, order, event state, and destination are
  equivalent.

## Dependencies

- Milestone 3 explicit exceptional CFG.
- Existing ARC ownership categories, initialization-state tracking, destructor
  registry, and lifecycle expander.
- Frozen cleanup ordering and linear event-ownership rules.

## Deliverables

- Exceptional cleanup planning and expansion.
- Partial-initialization rollback for every owning aggregate category.
- Event-state tracking across pack, transfer, borrow, catch, rethrow, destroy, and
  root propagation.
- Lifecycle verifier checks and debug annotations suitable for diagnosing cleanup
  paths.
- Reference traces for cleanup ordering used by IR, runtime, and native tests.

## Acceptance criteria

- Every initialized owned value is released exactly once on every exceptional
  route; no uninitialized field or element is released.
- Cleanup occurs in the architecture-specified reverse order before handler entry
  or outward propagation.
- Exactly one live owner exists for every event, including nested catch and
  rethrow paths.
- Normal, return, break, and continue cleanup behavior is unchanged.
- Panic remains distinct and does not accidentally enter exception cleanup.
- Lifecycle verification and ARC invariants pass for all supported owning types.

## Required tests

- Cleanup-order traces for nested scopes, temporaries, shadowed locals, return,
  break, continue, caught throw, unmatched throw, and rethrow.
- Fault injection at every constructor/collection initialization step.
- Ownership tests for arrays, lists, structs, classes, interface boxes, nullable
  owners, and combinations nested several levels deep.
- Event consume/rethrow/root-transfer tests that detect leaks, double destruction,
  payload use after destroy, and descriptor mutation.
- Negative lifecycle fixtures for missing, duplicated, reordered, or premature
  cleanup.

## Risks

- Path-insensitive initialization tracking can destroy values that were never
  initialized.
- Cleanup-block merging can silently change order or event ownership.
- Repacking on rethrow can duplicate ownership and lose identity.
- Cleanup code itself must not introduce a second recoverable exception path; its
  failure policy must follow the frozen runtime/lifecycle contract.

# Milestone 5 — SSA

## Goal

Convert the complete exceptional CFG to verified SSA without losing edge-specific
values, handler reachability, cleanup order, or linear ownership.

## Scope

- Select and record the SSA edge representation ADR before implementation.
- Make predecessor, dominator, dominance-frontier, reachability, and loop analyses
  include both normal and exceptional edges.
- Represent normal results and exception events as edge-specific values using the
  selected phi/block-argument design.
- Extend general SSA construction, definition placement, renaming, operand
  traversal, printing, and verification.
- Preserve event ownership across merges: a merge may select one incoming owner,
  but it may not duplicate, drop, or simultaneously expose incoming events.
- Specify behavior for handler entries with multiple throwing predecessors,
  critical exceptional edges, unreachable handlers, and cleanup blocks.
- Either extend the pattern/fallback SSA builder to exceptions or make it reject
  exception-bearing IR explicitly; silent fallback is prohibited.

## Dependencies

- Milestone 3 IR edge semantics.
- Milestone 4 expanded cleanup and event-state rules.
- Approved SSA representation ADR.
- CFG and dominance utilities that accept all edge kinds.

## Deliverables

- Exception-aware SSA builder and analysis graph.
- Selected phi or block-argument representation for edge values and ownership
  transfers.
- SSA printer and operand APIs that expose edge kinds and values.
- SSA verifier rules for dominance, predecessor completeness, edge arity, value
  availability, event linearity, and cleanup structure.
- Explicit handling or rejection in every alternate SSA construction path.

## Acceptance criteria

- SSA construction succeeds for valid nested handler and cleanup CFGs.
- Every exceptional predecessor participates in dominance and merge validation.
- A normal call result is unavailable on the exceptional path, and an event is
  unavailable on the normal path.
- Handler merges preserve exactly one event owner.
- Invalid dominance, missing edge arguments, duplicate ownership, and malformed
  predecessor sets are rejected.
- SSA verification passes before and after every enabled SSA transformation.

## Required tests

- Diamond, loop, nested-handler, multi-invoke-handler, cleanup-ladder, critical-edge,
  unreachable-block, and root-propagation SSA fixtures.
- Dominance/frontier tests where only exceptional edges make a block reachable.
- Ownership-aware merge tests with positive and negative event cases.
- Builder parity tests between supported construction paths, or fail-closed tests
  for deliberately unsupported fallback paths.
- Printer golden tests and verifier mutation tests for edge kind, arity,
  predecessor, dominance, and ownership defects.

## Risks

- Existing analyses that inspect only `jump` and `branch` will compute invalid
  dominance.
- Conventional phis can appear to duplicate linear values unless ownership
  transfer is defined per incoming edge.
- Critical-edge splitting can reorder cleanup or detach an event from its owner.
- Unreachable handler cleanup can hide malformed IR if the verifier skips it.

# Milestone 6 — Optimizers

## Goal

Make every enabled optimization preserve exceptional behavior, observable cleanup,
panic ordering, and event ownership. Optimization opportunity is subordinate to
correctness.

## Scope

All pass managers, effect queries, CFG mutators, operand visitors, and the following
passes require an explicit exception audit. “No transformation needed” is valid
only with a reviewed legality argument and regression test.

| Pass or family | Required changes | Legality conditions | Minimum regression tests |
|---|---|---|---|
| Initial IR constant folding | Teach the pass the new operations and effect split; fold only pure operands and descriptor comparisons proven by canonical identity. | Must not evaluate, suppress, duplicate, or move a `may_throw`/panic operation; must retain the same selected handler. | Fold around, but not through, throwing calls; exact-match true/false cases; panic/throw ordering. |
| Initial IR local constant propagation | Propagate values through blocks while respecting normal versus exceptional definitions. | A normal result cannot propagate onto an exceptional edge; event values cannot propagate onto normal edges; cleanup uses remain uses. | Invoke result/event edge separation and handler-local propagation. |
| Initial IR algebraic simplification | Classify exception/event operations as non-algebraic and preserve evaluation order. | A rewrite is legal only when it removes no potentially throwing operand evaluation and changes no cleanup point. | Identity/annihilator expressions whose discarded operands may throw or panic. |
| Initial IR dead-code elimination | Use `may_throw`, panic, cleanup, ownership, and event consumption as observable effects. | A potentially throwing call, event transition, cleanup, or handler-dispatch operation is never dead merely because its normal result is unused. | Unused throwing call, unused caught payload, unmatched propagation, cleanup-only blocks. |
| Initial IR dead-store elimination | Include exceptional exits in liveness and destructor obligations. | A store may be removed only if neither normal nor exceptional paths observe its value or initialization/cleanup state. | Store followed by throw; partial initialization; overwritten owning field before exceptional exit. |
| SSA constant folding | Mirror Initial IR effect rules and preserve edge-specific availability. | Folding cannot collapse an exceptional successor unless non-throwing behavior is proven by a trusted invariant. | Folded branch around invokes and event match operations. |
| SSA global constant propagation | Propagate across the complete CFG and represent exceptional executability. | Facts from a normal edge cannot enter an exceptional predecessor and vice versa; ownership facts are path-sensitive. | Handler joins and values defined only on one edge kind. |
| SSA algebraic simplification | Preserve operand evaluation and event operations. | Same effect and cleanup constraints as Initial IR, plus SSA dominance of replacements. | Throwing operands in simplified arithmetic/boolean forms. |
| SSA dead-code elimination | Treat all exceptional successors and event/cleanup uses as live roots. | Removing a definition cannot remove a possible throw, panic, cleanup, descriptor check, transfer, or destruction. | Unused invoke result with caught and unhandled exceptional paths. |
| SCCP and SCCP pass integration | Add exceptional edges to the executable-edge lattice and update phi/block-argument evaluation. | An exceptional edge is infeasible only with a sound proof that its operation cannot throw; “not observed in tests” is not proof. | Constant branches surrounding throws, handler feasibility, loop-carried exceptional edges. |
| Dead-phi and trivial-phi cleanup | Support the selected edge representation and linear values. | A phi/block argument can collapse only if dominance and event ownership remain valid; it cannot convert selection into duplication. | Multiple throwing predecessors carrying the same/different event SSA names. |
| Optimizer pipelines and result accounting | Run verification after each pass in debug/CI configurations and classify exceptional CFG changes. | Pipelines may not invoke a pass lacking an exception-safety declaration. | O0/O1/O2 pass-by-pass verification and differential parity. |

Copy propagation, ARC optimization, inlining, LICM, GVN, and bounds-check
elimination are part of the global optimizer contract even if a family is not yet
enabled in the repository. This milestone does not require adding an otherwise
unplanned pass. If one is introduced before promotion, it remains disabled for
exception-bearing IR until its row below is implemented and tested.

| Planned family | Required changes | Legality conditions | Minimum regression tests |
|---|---|---|---|
| Copy propagation | Traverse all edge operands and recognize event values as linear. | Replacement must dominate every normal/exceptional use and preserve one event owner. | Handler joins, edge-local call results, event copies rejected or collapsed safely. |
| ARC optimization | Include exceptional liveness, initialization state, cleanup ladders, and event-owned payloads. | Retain/release removal or motion must preserve presence and observable order on every exceptional exit. | Caught/unhandled/rethrown cleanup traces and partial aggregate rollback. |
| Inlining | Remap handler regions, cleanup scopes, exceptional continuations, event values, and root propagation. | The inlined CFG must select the same handler and perform the same cleanup in the same order. | Throwing callee in normal, nested-try, constructor, indirect, and rethrow contexts. |
| LICM | Model throw, panic, allocation, cleanup, and handler observability in loop invariance. | No such operation moves across a loop or try boundary unless nonfailure and unchanged ordering are proven. | Zero-iteration loops, first/later-iteration throws, loop-local catches, panic checks. |
| GVN | Include effects, handler context, provenance requirements, and event identity in value numbering. | Operations may merge only when throw timing, selected handler, panic, side effects, cleanup, and identity are unchanged. | Equivalent-looking calls in different handler regions and descriptor/event operations. |
| Bounds-check elimination | Keep failed bounds checks classified as panic, not exception. | Eliminate only with a proof the check succeeds on every relevant normal and exceptional predecessor. | Bounds facts invalidated by loops/calls and proof that panic never reaches catch. |

## Dependencies

- Milestone 5 verified SSA.
- Centralized instruction effects from Milestone 3.
- Lifecycle and event-ownership rules from Milestone 4.
- A test harness capable of pass-by-pass verification and differential execution.

## Deliverables

- Exception-safety audit for every enabled pass and pipeline.
- Updated effect/CFG/operand handling and transformation legality guards.
- Pass-level regression corpus described above.
- A registry or equivalent review mechanism preventing an unaudited pass from
  running on exception-bearing IR.
- Optimization parity results at all supported levels.

## Acceptance criteria

- The complete optimizer corpus passes with exceptions at every supported
  optimization level.
- IR/SSA verification succeeds after each enabled pass.
- Reference, IR interpreter, optimized IR/SSA, and native executions agree on
  result, selected catch, cleanup trace, panic versus throw, and unhandled outcome.
- No enabled optimizer lacks an explicit exception-safety disposition.
- Planned optimizer families remain disabled for exception-bearing code until
  their contract is implemented and tested.

## Required tests

- Every row in the table above.
- Cross-pass tests combining folding, propagation, DCE, SCCP, phi cleanup, and
  exceptional loops.
- Metamorphic tests comparing pass permutations that are otherwise supported.
- Ownership traces before and after optimization.
- O0/O1/O2 differential tests for caught, rethrown, unhandled, and panicking paths.
- Regression seeds for every optimizer miscompile found during implementation.

## Risks

- A single stale effect query can silently delete or reorder a throw.
- Normal-only liveness and reachability assumptions can erase handlers or cleanup.
- Verification only at pipeline end makes the responsible pass difficult to
  identify.
- Conservatism may initially reduce optimization. That is acceptable until a
  stronger proof is implemented.

# Milestone 7 — LLVM Backend

## Goal

Lower the verified exception IR to LLVM using the selected backend strategy while
preserving the backend-independent language semantics and integrating with the
private runtime contract.

## Scope

- Complete and approve the backend-lowering ADR using the strategies studied by
  the architecture documents. The ADR selects a mechanism; it cannot alter source
  semantics.
- Lower invoke-style control flow, normal and exceptional successors, ordered
  handlers, exact descriptor matching, cleanup blocks, rethrow, propagation, and
  root handling.
- Cover every potentially throwing call form: direct, indirect, interface-dispatch,
  constructor, runtime helper, callback adapter, and any synthesized call.
- Materialize event operations through the private runtime ABI without exposing
  event representation in public language semantics.
- Preserve panic as a separate fail-fast path and mark runtime/LLVM behavior so it
  cannot be caught as an Aether exception.
- Emit correct source locations and stable backend diagnostics for unsupported or
  malformed exception IR.
- Validate all supported targets and optimization modes; no backend may rely on
  runtime stack scanning.

## Dependencies

- Milestones 3–6.
- Approved backend strategy and private runtime ABI ADRs.
- At least the minimal runtime event, matching, transfer, destruction, and root
  contract from Milestone 8; Milestones 7 and 8 are expected to co-develop.
- Supported LLVM/Clang version matrix and native ABI constraints.

## Deliverables

- LLVM lowering for all exception IR operations and edge forms.
- Handler and cleanup emission with runtime calls or backend constructs required by
  the selected strategy.
- Descriptor references and root propagation/termination integration.
- Backend verifier checks and diagnostics for impossible IR states.
- Native fixtures and LLVM golden/structural tests at supported optimization
  levels.
- ADR documenting why the selected mechanism satisfies the frozen semantics and
  how alternate backends may remain compatible.

## Acceptance criteria

- Generated modules pass the LLVM verifier.
- Native positive, negative-runtime, cleanup, rethrow, nested-handler, and
  unhandled tests pass at all supported compiler optimization levels.
- Native observable behavior matches the AST/IR reference paths.
- Panic cannot enter an exception handler.
- No generated code depends on an undocumented public exception representation or
  scans the stack in the Aether runtime.
- LLVM verifier and native test suites are green.

## Required tests

- Structural LLVM tests for invoke/call sites, normal and exceptional blocks,
  handler dispatch, cleanup, event transfer, and root paths.
- Native tests covering each call form and combinations with returns, loops,
  constructors, interfaces, collections, and partial initialization.
- O0/O1/O2 parity and repeated-build determinism tests.
- Malformed-IR backend rejection tests.
- Cross-platform tests for each supported target/toolchain, including runtime
  termination output and exit status.

## Risks

- Backend mechanisms may have platform-specific unwinding or personality
  requirements even though Aether semantics are platform-independent.
- Duplicating lifecycle policy in LLVM lowering can disagree with pre-SSA cleanup.
- Incorrect LLVM attributes can let LLVM assume that throwing operations return
  normally or that panic unwinds.
- A private ABI chosen too narrowly can make later backend or FFI work brittle.

# Milestone 8 — Runtime

## Goal

Provide the minimal runtime machinery for opaque, linearly owned exception events,
canonical type matching, explicit propagation, and deterministic root termination.

## Scope

- Implement the private opaque event representation selected by the runtime ABI
  ADR.
- Provide operations to pack an owned `Error`, obtain canonical descriptor
  identity for matching, borrow the payload, transfer ownership, destroy an event,
  and propagate it through explicit compiler-generated control flow.
- Ensure descriptor identity is canonical across modules and linked artifacts.
- Provide root handling for unhandled exceptions with deterministic diagnostics,
  cleanup completion, destruction, and process termination.
- Keep panic handling separate; panic may use separate reporting infrastructure but
  is never converted into a catchable event.
- Define failure policy for event allocation, diagnostic formatting, and runtime
  internal invariants. Such failures must not recursively create recoverable
  exceptions.
- Add debug ownership counters, event IDs, and fault-injection hooks where useful
  for tests; production semantics remain opaque.
- Do not implement runtime stack scanning. The compiler-generated CFG performs
  propagation and cleanup.

## Dependencies

- Milestones 3 and 4 event state and cleanup contract.
- Approved private runtime ABI ADR.
- Backend integration requirements from Milestone 7; both milestones proceed
  against one shared contract.
- Existing ARC allocator, type descriptor, string/diagnostic, and termination
  facilities.

## Deliverables

- Opaque event runtime API and implementation.
- Canonical descriptor registration/identity support.
- Event destruction and root termination support.
- Separate panic and unhandled-exception reporting paths.
- Debug/fault-injection instrumentation and runtime ownership documentation.
- Backend-facing ABI tests without elevating the ABI to language semantics.

## Acceptance criteria

- Every event and owned payload is destroyed exactly once on catch consumption or
  root termination; rethrow and propagation do not duplicate it.
- Exact descriptor matching is stable across modules and optimization levels.
- Runtime propagation performs no stack scan and invokes no language-level
  matching policy absent explicit compiler requests.
- Panic is not packaged as an event.
- Allocation or reporting failures terminate through the approved fail-fast path
  without recursion.
- Ownership instrumentation is clean and stress tests pass.

## Required tests

- Unit tests for pack, descriptor lookup, exact match, borrow, transfer, destroy,
  rethrow, and root termination.
- Cross-module descriptor identity tests for struct and class errors.
- ARC leak/double-free/use-after-free tests with nested event payloads.
- Fault injection for event allocation, message construction, descriptor failures,
  and root reporting.
- Deep explicit propagation, repeated catch/rethrow, multi-thread or task tests if
  those execution modes are supported, and high-volume stress tests.
- Sanitizer and platform termination-output tests.

## Risks

- Descriptor duplication across modules can make exact catches nondeterministic.
- Error reporting can allocate or fail recursively while handling an unhandled
  exception.
- Runtime convenience helpers can accidentally absorb cleanup policy that belongs
  in compiler-generated CFG.
- Debug instrumentation can mask ownership bugs unless production-mode stress
  tests also run.

# Milestone 9 — FFI

## Goal

Contain every Aether exception at raw C boundaries and provide explicit,
ownership-safe adapters for imports, exports, and callbacks.

## Scope

- Define the implementation-level FFI containment contract without declaring the
  final stable public ABI.
- Treat raw C imports as nonthrowing in the Aether exception sense; C failure is
  represented by declared status/result conventions, not by an Aether event.
- Generate or require wrappers for throwing Aether exports that catch at the
  boundary and convert success/failure to an explicit status plus an
  ownership-defined opaque error handle or caller-selected policy.
- Wrap Aether callbacks passed to C so an exception is contained before returning
  through the raw C frame.
- Reject any export, import annotation, function-pointer conversion, or callback
  path that could permit an unwrapped exception event to cross raw C.
- Require adapters around foreign mechanisms such as C++ exceptions; raw foreign
  unwinding entering Aether is not an Aether exception.
- Document ownership, destruction, reentrancy, thread-affinity if any, and panic
  behavior at each adapter boundary.

## Dependencies

- Milestones 7 and 8.
- The runtime event ownership API.
- Existing or planned native export/import and callback machinery.
- A reviewed adapter contract for status values and opaque handles.

## Deliverables

- Import, export, and callback containment checks and wrappers.
- Explicit conversion and error-handle lifecycle helpers where supported.
- Compile-time diagnostics for unsafe or unsupported boundary declarations.
- C harnesses and foreign-language adapter fixtures.
- FFI documentation distinguishing expected `Result`/status failures, recoverable
  Aether exceptions, and panic.

## Acceptance criteria

- No Aether exception crosses a raw C frame in either direction.
- Every boundary outcome has defined ownership and destruction responsibilities.
- Throwing exports and callbacks are either contained by a generated/declared
  adapter or rejected.
- Foreign unwinding is caught by an appropriate foreign adapter or rejected as
  unsupported.
- C harness tests prove normal, error, reentrant callback, and panic behavior.

## Required tests

- C-to-Aether exports with success, caught error conversion, unhandled-at-wrapper
  conversion, and caller destruction of an error handle.
- Aether-to-C imports using status/result values.
- C callbacks into Aether that throw, rethrow internally, and return normally.
- Nested and reentrant boundary calls.
- Negative compile tests for raw throwing function pointers and missing adapters.
- Sanitizer tests for error-handle leaks/double destruction and platform tests
  proving no foreign unwinder crosses the boundary.

## Risks

- Implicit conversion of exceptions to status values can hide policy and ownership.
- Callback paths are easy to omit from containment audits.
- C++ or platform unwinders can bypass Aether cleanup if treated as compatible.
- A provisional adapter can accidentally become a de facto stable ABI; it must be
  labeled private until separately approved.

# Milestone 10 — Tooling

## Goal

Provide complete, consistent authoring, formatting, navigation, completion, and
diagnostic support for the frozen exception syntax and semantics.

## Scope

- Complete formatter support beyond the minimal Milestone 1 grammar updates,
  including stable layout for multiple and nested catches.
- Extend language-service/LSP parsing, diagnostics, semantic tokens, hover,
  navigation, completion, document symbols, and code actions where appropriate.
- Offer context-aware completion for `throw`, `try`, `catch`, `Error` types, and
  legal bare rethrow; do not suggest checked-exception declarations.
- Keep command-line diagnostics, LSP diagnostics, and AST/typechecker diagnostic
  codes and source ranges consistent.
- Update VS Code and IntelliJ syntax sources and tests while keeping their
  shared LSP completion and diagnostics behavior aligned.
- Update IR/CFG/SSA visualization labels so exceptional edges and event ownership
  are distinguishable.

## Dependencies

- Milestones 1 and 2 for syntax and stable diagnostic contracts.
- Milestones 3 and 5 for IR/SSA visualization.
- Existing formatter and language-service protocols.

## Deliverables

- Formatter and formatting snapshots.
- LSP semantic features, completion, diagnostics, and recovery behavior.
- Updated editor grammars/configurations/snippets and generated assets where
  applicable.
- Exception-aware compiler visualization output.
- Cross-tool consistency matrix.

## Acceptance criteria

- Editor support is complete across all shipped integrations.
- Formatting is idempotent and consistent between CLI and editor requests.
- Syntax and semantic diagnostics have matching codes, ranges, and meaning across
  CLI and LSP.
- Completion is context-correct and reflects unchecked semantics.
- Exceptional CFG edges are visible in compiler diagnostic/visualization tools.
- Tooling suites and editor fixtures are green.

## Required tests

- Formatter golden, idempotence, incomplete-source, and nested-layout tests.
- LSP diagnostic, semantic-token, hover, completion, navigation, and incremental
  edit tests.
- Golden tokenization tests for VS Code and IntelliJ definitions.
- Cross-tool diagnostic parity tests.
- IR/CFG/SSA visualization snapshots for normal, caught, rethrown, and unhandled
  paths.

## Risks

- Tooling may implement its own partial parser and drift from compiler grammar.
- Completion that suggests `throws` clauses would contradict unchecked semantics.
- Generated editor assets can be edited directly and later overwritten.
- Diagnostics can expose backend implementation terminology instead of source
  semantics.

# Milestone 11 — Testing

## Goal

Produce complete end-to-end evidence that exceptions preserve semantics, ownership,
verification, optimization parity, native behavior, and FFI containment under
normal and adversarial conditions.

## Scope

Milestone-local tests remain mandatory. This milestone builds the integrated matrix,
fills cross-layer gaps, adds long-running and generative coverage, and defines the
release evidence retained for capability promotion.

| Area | Required matrix |
|---|---|
| Parser/formatter | Every legal form, malformed-token recovery, statement-only throw, bare rethrow, ordered/multiple/nested catches, round-trip and idempotence. |
| Typechecker | Struct/class errors, invalid throws/catches, exact match, catch-all ordering, lexical rethrow, unchecked overrides/interfaces/function values, diagnostic stability. |
| Initial IR | Lowering goldens, explicit edge shape, event state, schema round-trip, invalid verifier mutations, interpreter behavior. |
| Lifecycle/ARC | Cleanup order for every owner kind and early exit, partial initialization at every step, catch/rethrow/root ownership traces, leak/double-release rejection. |
| SSA | Exceptional predecessor/dominance/frontier cases, edge-specific values, ownership-aware merges, critical edges, unreachable handlers, verifier mutations. |
| Optimizers | Per-pass legality, pass combinations, O0/O1/O2 parity, event/cleanup traces, regression seeds, post-pass verification. |
| Runtime | Pack/match/borrow/transfer/destroy, cross-module descriptors, root termination, allocation/reporting faults, deep propagation and repeated rethrow. |
| LLVM/native | LLVM verification, each call form, nested cleanup, all supported targets/toolchains and optimization levels, deterministic termination. |
| FFI | Imports, exports, callbacks, reentrancy, status/error-handle ownership, foreign-adapter cases, proof that raw C is never crossed. |
| Parity | AST/reference, Initial IR interpreter, SSA/optimized paths, and native code agree on output, catch selection, cleanup, panic/throw, and exit status. |
| Stress | Deep nesting, wide catch lists, long propagation chains, large ownership graphs, repeated failures, cross-module programs, resource pressure. |
| Fuzz | Parser and formatter, typed AST generation, IR/SSA verifier mutation, optimizer differential testing, event-state sequences, FFI wrapper generation. |
| Sanitizers | Address, undefined-behavior, leak, and thread sanitizers where supported, plus allocator poisoning and runtime ownership counters. |

The corpus must explicitly separate expected failures represented by `Result` or
status values, recoverable exceptional failures, and panic/invariant failures. It
must also replace or clearly reclassify old experimental exception tests so they
cannot certify obsolete behavior.

## Dependencies

- Functional completion of Milestones 1–10.
- Reproducible reference/interpreter and native runners.
- CI capacity for sanitizer, fuzz smoke, stress, and multi-optimization jobs.
- A triage process for minimizing and retaining failing seeds.

## Deliverables

- Versioned test matrix with traceability from frozen decisions to cases.
- Unified parity corpus and outcome/cleanup trace format.
- Fuzz targets, seed corpora, mutation strategies, and crash minimization workflow.
- Sanitizer and stress CI jobs with documented time budgets.
- Promotion evidence report listing platforms, toolchains, optimization levels,
  excluded cases, and zero known semantic divergences.

## Acceptance criteria

- Every matrix cell has automated coverage or a documented, approved
  not-applicable rationale.
- No known divergence exists among reference, IR, optimized, and native execution.
- Python/Rust verifiers agree on the shared valid and invalid corpus.
- Sanitizer runs are clean; stress tests meet their repetition/depth thresholds;
  fuzz smoke runs produce no unresolved crash or verifier escape.
- Tests contain no unconditional skips for core exception behavior.
- Every resolved defect has a minimized permanent regression.

## Required tests

- The complete table above.
- Cross-product suites for catch shape, owner type, exit kind, call kind,
  optimization level, and backend target using representative pairwise coverage
  plus targeted full combinations on critical paths.
- Fault-injection sweeps at each event allocation and aggregate initialization
  point.
- Negative corpus mutation proving each IR, lifecycle, SSA, and FFI verifier rule
  is exercised.
- Long-running nightly fuzz and stress jobs plus bounded presubmit smoke versions.

## Risks

- A large matrix can create false confidence if all paths share the same flawed
  oracle; independent interpreters and structural verifiers are required.
- Nondeterministic cleanup traces or toolchain output can make CI flaky.
- Fuzzing syntactically invalid programs only will miss ownership and optimizer
  defects; typed and verifier-aware generators are necessary.
- Excessive presubmit cost can encourage disabling tests; tiered smoke/nightly
  budgets should be explicit.

# Milestone 12 — Capability Promotion

## Goal

Enable exceptions in the stable capability profile only after the full
implementation and its evidence are complete, reviewed, documented, and green.

## Scope

- Audit every frozen decision against implementation and tests.
- Confirm all three implementation ADRs are approved and accurately document the
  shipped mechanisms without changing language semantics.
- Update language/compiler documentation, capability manifests, generated profile
  artifacts, examples, diagnostics references, native/FFI notes, and release notes.
- Remove temporary experimental paths and fail-closed exceptions to the feature
  gate.
- Promote `ERROR_HANDLING` atomically across parser-to-native support; there is no
  parser-only, interpreter-only, or backend-only stable profile.

## Dependencies

- Accepted completion of Milestones 0–11.
- Complete promotion evidence report.
- Green release and capability-consistency pipelines.
- Documentation and compatibility review.

## Deliverables

- Signed promotion checklist and traceability report.
- Updated capability profile and generated consistency artifacts.
- Final user/compiler/runtime/FFI documentation and examples.
- CI and release configuration treating exceptions as a stable supported feature.
- Removal of obsolete experimental exception behavior and temporary compatibility
  shims not intentionally retained.

## Acceptance criteria

The following checklist is exact; every item must be checked before promotion:

- [ ] Implementation is complete from lexer through native runtime and tooling.
- [ ] Frozen language semantics are implemented without exceptions or undocumented
      extensions.
- [ ] Initial IR, lifecycle, SSA, and Python/Rust verification are complete.
- [ ] Every enabled optimizer has passed its exception-safety audit.
- [ ] Backend lowering and runtime ownership are verified on every supported target.
- [ ] FFI imports, exports, and callbacks contain exceptions at raw C boundaries.
- [ ] Reference, IR, optimized, and native parity is complete at supported
      optimization levels.
- [ ] Ownership, partial-initialization, stress, fuzz-smoke, and sanitizer suites
      are green.
- [ ] Formatter, LSP, completion, diagnostics, and shipped syntax highlighters are
      complete.
- [ ] Language, compiler, runtime, FFI, diagnostic, and roadmap documentation is
      updated.
- [ ] SSA representation, backend lowering, and private runtime ABI ADRs are
      approved.
- [ ] Capability manifests and generated profiles agree.
- [ ] Presubmit, nightly, release, and platform CI are green with no core exception
      skips.
- [ ] No unresolved correctness, ownership, verifier, parity, or boundary-containment
      defect remains.
- [ ] Stable capability promotion has received the required maintainer approval.

## Required tests

- Run the complete Milestone 11 matrix from a clean release configuration.
- Run capability consistency, generated-profile freshness, documentation-link,
  package, install, and release smoke tests.
- Compile and execute stable-profile examples on every supported native target.
- Verify negative feature-gate behavior in the previous profile and positive
  behavior in the promoted profile.
- Repeat the Python/Rust verifier parity and FFI containment suites on release
  artifacts rather than only development-tree binaries.

## Risks

- Premature promotion can make an internal representation or provisional ABI a
  compatibility commitment.
- Updating only one capability manifest can produce profile-dependent behavior.
- Removing the gate can expose an untested compiler route that bypasses lifecycle
  or verification.
- Documentation lag can cause users to rely on obsolete experimental semantics.

# Estimated implementation order

The expected mainline order is:

1. Complete Milestone 0 and approve the work inventory.
2. Land syntax/AST and semantic validation in Milestones 1–2 while keeping the
   feature gated.
3. Land Initial IR and lifecycle in Milestones 3–4. These establish the semantic
   control-flow and ownership foundation and must not be bypassed for backend
   convenience.
4. Approve the SSA representation ADR, then complete Milestone 5.
5. Audit and update all optimizers in Milestone 6.
6. Approve the backend/runtime ADRs, then co-develop Milestones 7–8.
7. Add FFI containment in Milestone 9 and finish tooling in Milestone 10.
8. Close the integrated matrix in Milestone 11.
9. Promote the capability atomically in Milestone 12.

# Critical path

The critical path is:

```text
frozen semantics
  -> semantic AST/type checking
  -> explicit Initial IR
  -> lifecycle cleanup and event ownership
  -> exception-aware SSA
  -> optimizer legality
  -> backend/runtime integration
  -> native and FFI parity
  -> capability promotion
```

Initial IR and lifecycle are the highest-leverage gates. Backend work must not
invent implicit cleanup to start early, and SSA/optimizer work must not model only
normal predecessors. The backend strategy and private runtime ABI need approval
before their implementations merge, but their evaluation can begin during
Milestones 3–5.

# Parallelizable work

- After Milestone 0, editor grammar fixtures and parser test cases can be prepared
  alongside Milestone 1.
- Typechecker diagnostic fixtures and Error-conformance tests can proceed once the
  AST shape is stable.
- Python/Rust schema and verifier work can proceed in parallel against one
  versioned Milestone 3 contract, with mandatory shared fixtures before merge.
- Runtime event prototypes and backend strategy experiments can run in parallel
  with SSA/optimizer work, but cannot define source semantics or merge as stable
  behavior before the relevant ADRs and lifecycle contract are approved.
- Milestones 7 and 8 should be implemented concurrently against a shared ABI test
  suite.
- LSP, completion, formatter, and editor integrations can proceed after Milestones
  1–2; CFG visualization waits for Milestones 3 and 5.
- Fuzz generators, sanitizer jobs, stress harnesses, and parity infrastructure can
  be built throughout the project even though final closure occurs in Milestone 11.

# Suggested pull-request boundaries

Pull requests should remain reviewable and keep the capability disabled until the
final promotion. A suggested sequence is:

1. Preparation inventory, dependency graph, baseline, and ADR templates.
2. Lexer/parser/AST plus parser tests.
3. Formatter and syntax-highlighter syntax support.
4. Built-in `Error` and typechecker/diagnostic semantics.
5. Initial IR model, effect taxonomy, CFG, printer, and schema.
6. Initial IR lowering, interpreter, Python/Rust verifiers, and shared fixtures.
7. Lifecycle cleanup, partial initialization, and event-ownership verification.
8. SSA representation ADR and exception-aware SSA construction/verification.
9. Initial IR optimizer audit and regressions.
10. SSA optimizer audit, SCCP/phi work, and optimization parity.
11. Backend/runtime ADRs and minimal ABI contract.
12. Runtime event/descriptors/root handling with ownership tests.
13. LLVM lowering and native integration.
14. FFI import/export/callback containment.
15. LSP, completion, diagnostics, visualizations, and remaining editor support.
16. Integrated parity, stress, fuzz, sanitizer, and platform hardening.
17. Documentation, release evidence, and atomic capability promotion.

Where a schema or ABI spans repositories or languages, its producer, consumer, and
shared tests belong in the same atomic pull request or in a deliberately
version-gated sequence that fails closed. No pull request may claim exception
support complete based on a single compiler stage, and no implementation pull
request may alter a frozen language decision without a new RFC.
