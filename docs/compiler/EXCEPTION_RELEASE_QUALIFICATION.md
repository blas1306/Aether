# Exception Release Qualification

> Classification: **Audit**. Date: **2026-08-02**.
>
> Baseline: commit `83da5fb` (`feat(exceptions): enforce native boundary
> containment`). This report qualifies the existing implementation; it does not
> change exception semantics, Initial IR, SSA, the accepted ADRs, the private
> runtime ABI, or backend architecture.

## Decision

# DO NOT PROMOTE

`ERROR_HANDLING` remains `UNSUPPORTED` in native capability profile 23.
Promotion is blocked by semantic and pipeline disagreements, an over-strong
capability detector, and incomplete public tooling. Internal native execution
is substantial and the admitted corpus is healthy, but implementation presence
is not release qualification.

No public FFI was added and no private runtime symbol or layout was promoted to
a public contract.

Hotfix A closes ERQ-001 without changing this promotion decision. The
typechecker now rejects any `Error.message()` implementation whose local call
graph may produce an Aether exception with
`AE-ERROR-MESSAGE-NONTHROWING`. Root lowering calls the witness as non-throwing
with no event-out slot or unwind edge; malformed internal `may_throw` witnesses
are rejected before LLVM emission. Panic remains fail-fast and
`ERROR_HANDLING` remains `UNSUPPORTED`.

Hotfix B closes ERQ-002 without changing this promotion decision. One semantic
exception-effect summary now owns function and interface-slot `may_throw` facts.
Initial IR records that decision in function metadata, interface call shape and
witness-slot metadata; SSA preserves it; Python/Rust verifiers reject
disagreements; LLVM consumes it without method-name or module-wide inference.
`Error.message()` now remains an ordinary interface call at every stage.

## Blocking issues

| ID | Blocking finding | Evidence | Required evidence to close |
| --- | --- | --- | --- |
| ERQ-001 | **CLOSED by Hotfix A.** The typechecker had accepted throwing `Error.message()` implementations; interpreter/runtime/backend code and positive IR/SSA/native tests had modeled a second event. | `test_error_message_implementation_cannot_throw`; `test_error_message_rejects_transitive_throwing_helper`; `test_root_reporter_calls_error_message_as_nonthrowing`; negative native qualification tests | The semantic diagnostic, non-throwing root call, backend invariant, panic separation and documentation consistency tests now enforce one rule. |
| ERQ-002 | **CLOSED by Hotfix B.** Initial IR had selected interface `invoke` from module-wide exception use while function `may_throw` came from a separate call-graph scan, producing IRV-144. | `test_interface_dispatch_only_function_has_consistent_nonthrowing_effect`; `test_interface_exception_effects.py` | The semantic effect summary, carried interface-slot fact, strict IR/SSA verifier checks and LLVM structural regressions now enforce one decision. |
| ERQ-003 | **CLOSED by Hotfix B.** The recorded case used a later `Error.message()` dispatch whose artificial exceptional edge created the incompatible lifecycle join. The slot is semantically nonthrowing, so correct Initial IR has no such edge. | `test_nested_rethrow_mutation_with_later_error_message_verifies`; AST/IR observation is `24\nlater\n` | The same canonical slot effect that closes ERQ-002 removes the unreachable edge; lifecycle rules and verifier strength are unchanged. |
| ERQ-004 | `implements Error` alone is classified as native exception syntax. A program that only calls the ordinary `message()` interface is rejected with `AE-BACKEND-ERROR_HANDLING`. | `test_error_conformance_only_records_capability_release_blocker`; detector branches in `capabilities.py` for struct/class conformance | Detect the operations that require exception transport, not ordinary `Error` conformance; prove no false positive or false negative across declarations, modules and all exception statements/calls. |
| ERQ-005 | Shipped completion/highlighting still advertises the removed experimental `Exception` type and invalid legacy snippets such as untyped `catch (e)` and `throw "message"`. Catch binders have no dedicated symbol/hover/completion evidence. | `autocomplete_engine.py`, Qt keyword table, VS Code grammar, IntelliJ token table | Replace obsolete guidance with `Error` and typed/root catch forms; add CLI/LSP/Qt/VS Code/IntelliJ fixtures for completion, hover, symbols, recovery and diagnostics. |
| ERQ-006 | Exceptions are absent from the executable release/differential corpus because the stable gate correctly rejects them; existing native tests bypass the gate. | `differential.py` calls `validate_backend_capabilities`; native exception helpers lower directly | After ERQ-001–005, add an atomic promotion candidate whose public CLI, wheel-installed CLI and differential corpus exercise exceptions at O0/O1/O2 without a bypass. |
| ERQ-007 | The wheel builds, but release verification rejects it because a public catalog entry is absent from the artifact. | `verify_wheel` reports `wheel is missing public example: examples/LeetCode/isPalindrome.ae`; `pyproject.toml` has no `share/aether/examples/LeetCode` data-file entry | Make wheel contents derive from, or be exhaustively checked against, the authoritative manifest; then verify both wheel and sdist in isolated installed smoke tests. |

Hotfixes A and B close ERQ-001 through ERQ-003 without altering lifecycle,
Initial IR or SSA representation, or the private runtime ABI layout/version.

## 1. Architecture audit

| Stage | Result | Finding and evidence |
| --- | --- | --- |
| Frontend | PASS | Expression throw, bare rethrow, typed/root catches, ordering, nesting, recovery and formatting are covered by `test_exceptions.py`, `test_source_formatter.py` and LSP formatter tests. |
| Typechecker | PASS for Hotfix A; qualification still blocked | Core conformance, exact matching and catch rules pass. Throwing direct/transitive `Error.message()` implementations receive `AE-ERROR-MESSAGE-NONTHROWING`. |
| AST interpreter | PASS | Representative handling, mutation, dynamic identity and provenance behave deterministically. Former ERQ-003 now agrees with verified Initial IR. |
| Capability gate | **FAIL** | Fail-closed placement is correct, but ERQ-004 rejects an ordinary interface-only program. |
| Initial IR lowering | PASS for the qualified effect cases | ERQ-002/003 now generate verifier-valid IR because nonthrowing interface dispatch has no exceptional edge. |
| Lifecycle expansion | PASS for the qualified corpus | Constructor rollback, ordinary exceptional cleanup and the former ERQ-003 case pass without lifecycle changes. |
| Initial IR verifier | PASS as a detector | It rejects both invalid generated forms with stable `IRV-144`/`IRV-036`; the disagreement is that valid typed source generated them. |
| SSA lowering | PASS for verified inputs | Direct/indirect/interface invokes, edge-defined results/events, handlers and ownership lower correctly for every Initial IR program admitted by the verifier. Blocked Initial IR programs cannot reach SSA. |
| SSA verifier | PASS for verified inputs | Exceptional CFG, dominance, event linearity and constructor cleanup mutation tests pass in Python and Rust. |
| SSA interpreter | PASS for verified inputs | Matches Initial IR on the admitted exception corpus and generated stress corpus. |
| Optimizers | PASS for verified inputs | See the per-pass matrix below. |
| LLVM lowering | PASS internal | Event-out is the production internal transport; the opt-in EH prototype is comparison-only. Both agree on the shared verified corpus. |
| Runtime | PASS internal | Pack/match/borrow/destroy, root termination, fault injection, provenance, dynamic name and panic separation pass internal tests. Root message dispatch cannot form or recursively handle a second event. |
| Native boundary verifier | PASS | Process root consumes events, raw-C event slots are rejected, foreign/public surfaces fail closed, and the private ABI remains private. |
| Native execution | PASS for internal admitted corpus | Linux x86_64 clang O0/O1/O2 and sanitizer tests pass, including generated stress. The public capability route remains intentionally blocked. |

Because the table contains semantic disagreements, the architecture gate fails.

## 2. Semantic parity matrix

Legend: PASS means identical observations for every stage that admits the case;
BLOCKED means at least one required representative program does not reach every
stage. Cleanup order is checked through explicit IR/SSA instruction order,
linear ownership verification and sanitizer evidence because Aether has no
user destructor hook that could print cleanup directly.

| Representative behavior | Result | Observable evidence |
| --- | --- | --- |
| successful execution / nonthrowing path | PASS | AST, Initial IR, SSA, event-out and comparison EH produce the same stdout/stderr/status. |
| direct throw | PASS | Exact handler receives the payload; root case exits 1 when unhandled. |
| ordered multiple catches | PASS | Wrong handlers produce no output; exact handler precedes `Error` catch-all. |
| nested catches | PASS | Generated 24-level no-mutation stress is deterministic across AST/IR/SSA/optimized/native. |
| rethrow | PASS | Same event and original provenance move outward; sibling catches are skipped. |
| nested rethrow | PASS for the qualified cases | Mutation plus later nonthrowing `Error.message()` now verifies and matches AST observation; genuinely throwing invokes retain explicit cleanup edges. |
| struct payloads | PASS | Owned snapshot semantics and `message()` output agree. |
| class payloads | PASS | Reference identity and dynamic nominal descriptor agree. |
| interface dispatch | PASS internally | Throwing, nonthrowing, mixed, nested, returned-interface, struct/class and multiple-interface dispatch preserve one semantic slot effect through IR, SSA and LLVM. |
| successful constructors | PASS | Struct/class construction and ordinary results survive event-out and EH comparison. |
| constructor failure | PASS | Partial fields and caller/callee receivers roll back under ASan/LSan/UBSan. |
| `MethodResult` | PASS | Receiver/value extraction and exceptional call ABI agree. |
| owned aggregates | PASS | Struct aggregates, strings, interfaces and nullable fields retain/drop correctly in admitted cases. |
| `Array` / `List` | PASS | Managed fields, nested values and constructor rollback pass verifier and sanitizer evidence. |
| nullable | PASS | Tagged nullable payload in owned exception aggregates preserves value/absence and cleanup. |
| propagation | PASS | Deep and mutual recursion, several frames and 2,000 repeated events are deterministic. |
| root handling | PASS internal | Exact stderr `Aether unhandled exception: <type>: <message>\n`, exit 1 and event destruction. |
| panic | PASS | Overflow/division/bounds and private invariant failures bypass catches and remain distinct from exception events. |
| stdout / stderr / exit status | PASS for admitted corpus | Byte-exact assertions exist at AST/IR/SSA/native and O0/O1/O2; generated stress runs twice identically. |
| observable mutation | PASS for the qualified cases | Common catch mutation and the former ERQ-003 case agree across AST and verified Initial IR. |
| cleanup order | PASS for admitted corpus | Explicit ladders, event terminal disposition and sanitizer tests pass; Hotfix B adds no lifecycle rewrite. |
| `Error.message()` | PASS for Hotfix A | Struct/class/interface dispatch remains normal; throwing bodies and transitive throwing helpers are rejected semantically, root lowering is a non-throwing call, and malformed internal witnesses fail before emission. |
| dynamic type | PASS | Exact concrete descriptor matching and `Error` catch-all agree for struct/class/interface carriers. |
| original provenance | PASS internal | Bare rethrow preserves the original line/column; replacement throw creates new provenance. |

## 3. Optimizer compatibility matrix

| Pass | Exceptional edge/event policy | Result |
| --- | --- | --- |
| Initial IR constant folding | Folds scalar operations only; trapping arithmetic is not folded; exception operations are untouched. | PASS |
| Initial IR local constant propagation | Rewrites structural operands without moving or deleting terminators/events. | PASS |
| Initial IR algebraic simplification | Simplifies value operations; structural rewrite reaches exceptional operands; effectful instructions remain. | PASS |
| Initial IR DCE | Removes only result-producing instructions whose effects do not require preservation. Pack/destroy/throw/rethrow/propagate/invoke remain. | PASS |
| Initial IR dead-store elimination | Block-local store analysis treats control transfers and lifecycle operations as boundaries; cleanup is retained. | PASS |
| SSA constant folding | Scalar-only, with checked arithmetic; no exceptional operation is folded. | PASS |
| SSA global constant propagation | Structural operands are rewritten; event values are overdefined/not scalar constants. | PASS |
| SSA algebraic simplification | Pure scalar identities only; no event or cleanup removal. | PASS |
| SCCP | Every invoke conservatively marks normal and exceptional edges executable; throw/rethrow/propagate mark their exceptional target. | PASS |
| trivial-phi elimination | Rewrites all structural uses; does not merge handlers or invent edge availability. | PASS |
| dead-phi elimination | Liveness includes exceptional successor operands. | PASS |
| SSA DCE | `must_preserve` retains invokes, event operations, cleanup and control flow. | PASS |
| CFG rewrite coverage | SCCP repairs executable block/edge and phi sets; verifier runs after every SSA pass in qualification tests. | PASS |

No inlining, LICM, GVN, ARC elimination, copy propagation, bounds-check
elimination or handler-merge pass exists. They are not silently treated as
compatible; future introduction requires a new audit.

## 4. Capability audit

- Throw, bare rethrow and try/catch each produce
  `AE-BACKEND-ERROR_HANDLING` before IR on the stable route.
- No stable native exception program passes the current gate.
- The gate is over-strong: struct/class declaration with `implements Error`
  also records `ERROR_HANDLING`, even without exception control flow
  (ERQ-004).
- Therefore capability detection fails the “nothing weaker or stronger” gate.
- The state remains `UNSUPPORTED`; no profile version or generated capability
  table was changed.

## 5. Documentation audit

Current references now distinguish internal implementation from stable
availability:

- language spec and native profile continue to exclude exceptions;
- current feature matrix records internal IR/SSA/LLVM/runtime support and the
  failed qualification;
- backend parity identifies its older “no IR/native” rows as historical and
  carries the current qualification update;
- roadmap records “implemented internally; promotion blocked”;
- release notes explicitly preserve the RC4 boundary;
- native ABI documentation states that the event ABI remains private and links
  only to the containment policy;
- accepted ADRs were not changed;
- architecture/design snapshots remain classified as RFC, design, audit or
  historical rather than normative release promises.

The original ERQ-001 contradiction remains recorded as historical audit
evidence. Hotfix A aligned implementation to the frozen non-throwing rule; it
did not change the accepted architecture.

## 6. Example audit

The schema-2 manifest now covers all 107 public `.ae` files:

- 89 `V1_NATIVE`;
- 18 `AST_ONLY_EXPERIMENTAL`;
- 0 broken/unclassified.

`pruebaException.ae` and `Sorts/IllegalArgumentException.ae` require
`AE-BACKEND-ERROR_HANDLING` and remain AST-only experimental. The two tracked
least-squares examples `minCuad.ae` and `minCuad2.ae` were missing from the
manifest; they were added as non-runnable AST-only frontend/plotting
experiments without modifying either example. Stale capability sets and
runtime hashes were refreshed through the canonical manifest updater.

## 7. Tooling audit

| Tool | Result | Qualification |
| --- | --- | --- |
| Formatter | PASS | Typed/root/multiple catches and bare rethrow format idempotently. |
| Syntax highlighting | PARTIAL | Keywords and `Error` are highlighted, but Qt/VS Code/IntelliJ still advertise obsolete `Exception`. |
| LSP diagnostics | PASS frontend | Reuses parser/typechecker and suppresses host tracebacks; no promoted native exception contract exists. |
| LSP formatting | PASS | Multiple typed handlers are covered. |
| LSP hover | INCOMPLETE | No dedicated evidence for catch-binder type or `Error` exception context. |
| Completion | **FAIL** | Suggests obsolete `Exception`, untyped `catch (e)`, and string throw. |
| Document symbols | INCOMPLETE | No catch-binder symbol extraction evidence. |
| Parser recovery | PASS | Malformed typed catches, missing delimiters/expressions and illegal rethrow are covered. |
| IntelliJ | PARTIAL | Keyword highlighting and general LSP client pass; obsolete `Exception` remains and no semantic catch fixtures exist. |
| VS Code | PARTIAL / environment-limited | Grammar covers exception keywords but retains `Exception`; Node/npm were unavailable in this environment. |
| Qt editor | PARTIAL | Keyword highlighting passes; shared completion remains obsolete. |

Tooling support is not stable and blocks promotion.

## 8. Release audit

- Capability profile 23 and generated native profile agree on
  `error-handling = UNSUPPORTED`.
- Release scripts run capability, documentation, example, diagnostic,
  compileall, pytest, parity, LLVM and native gates before packaging.
- Wheel/sdist metadata derives from the canonical version and verifies required
  runtime files, normative docs and the complete public example manifest.
- A clean wheel builds, but its content verification fails because
  `examples/LeetCode/isPalindrome.ae` is cataloged and not packaged (ERQ-007).
- No exception qualification gate is yet part of the installed-wheel smoke
  corpus (ERQ-006).
- Hosted CI covers Rust verifier operation and VS Code independently, but does
  not run a single required exception promotion matrix across Python, Rust,
  sanitizer, editors, packaging and installed-wheel execution.
- Diagnostic containment has `ICE-NATIVE-BOUNDARY-001`; public source
  diagnostic coverage for a promoted exception profile is incomplete.

No release metadata was changed to imply exception support.

## 9. Stress-test summary

The generated qualification corpus covers 24 nested catches/rethrows, 12
ordered concrete handlers plus the selected handler, recursion depth 48, 500
throws, 250 interface dispatches, two 128-element nested arrays, two 32-element
nested lists, and mixed struct/class `Error` payloads. It compares AST,
verified Initial IR, optimized Initial IR, verified SSA, per-pass-verified
optimized SSA and clang O2 native output, then runs the binary twice to prove
determinism.

Existing native sanitizer tests additionally cover recursion depth 64, 2,000
events, constructor failures at multiple initialization points, `MethodResult`,
nullable/owned aggregates, event allocation/reporting fault injection and
event-out versus LLVM EH at O0/O1/O2.

Stress testing originally produced ERQ-002 and ERQ-003, demonstrating why a
green happy-path corpus is insufficient for promotion. Hotfix B closes both by
removing exceptional edges from dispatches the semantic authority proves
nonthrowing.

## 10. Cross-version audit

- The obsolete source-level `Exception` type is no longer a compiler type, but
  stale editor/completion references remain and are classified under ERQ-005.
- The LLVM EH implementation is reachable only through an explicit test-only
  opt-in and is documented as comparison evidence, not production transport.
- Event-out is the sole production internal lowering strategy.
- The old AST exception path now implements the approved Error/event semantics
  and remains an auxiliary interpreter, not a stable profile.
- No historical document, accepted ADR or comparison artifact was deleted.

## 11. Remaining milestones and estimated scope

1. **Capability correction (small):** remove ordinary `Error` conformance false
   positives and add exhaustive syntax/module tests.
2. **Tooling completion (medium):** completion, hover, symbols, recovery and
   fixtures across LSP, Qt, VS Code and IntelliJ; remove obsolete `Exception`.
3. **Packaging correction (small):** make the wheel/sdist public example set
   agree with the authoritative manifest and run isolated artifact validation.
4. **Integrated promotion candidate (medium):** public differential corpus,
   sanitizer jobs, wheel-installed CLI, CI/release gate and diagnostics.
5. **Repeat release qualification (small after the above):** rerun every matrix;
   only then may profile state, version, normative spec and examples be changed
   atomically.

Estimated aggregate scope: **medium**, dominated by tooling, packaging and
integrated cross-tool evidence rather than backend transport.

## 12. Files modified by qualification and hotfixes

The original qualification changed only audit/evidence files. Hotfix A added
the semantic `Error.message()` guard and nonthrowing backend enforcement.
Hotfix B adds the shared semantic exception-effect summary, carries its
interface-slot fact through Initial IR/DTO/SSA, strengthens Python and Rust
consistency checks, removes LLVM-side inference, and adds focused cross-stage
regressions. Capability state, public language surface, lifecycle, IR/SSA
representation and runtime ABI remain unchanged.

## 13. Risks retained

- Additional shared-cleanup merge shapes remain an audit risk even though the
  former ERQ-003 shape now contains no artificial exceptional edge.
- Internal native tests bypassing the stable gate can conceal integration and
  packaging gaps.
- Historical ERQ-001 evidence can be mistaken for current behavior unless its
  Hotfix A closure is read with the original qualification finding.
- Only Linux x86_64 native execution is supported; cross-target architecture
  plausibility is not execution evidence.
- Lack of public FFI is intentional. Future FFI needs a separate reviewed
  containment contract and does not block keeping the current profile disabled.

## 14. Test and environment summary

| Area | Result |
| --- | --- |
| Full Python suite | **4514 passed, 12 failed, 4 skipped**. All 12 failures are pre-existing assertions in `test_import_aliases.py`: the current vector orientation prints a column (`[1.0; 2.0]`) while those tests expect a row (`[1.0 2.0]`). No Hotfix B file touches that behavior. |
| Qualification/effect regressions | **11 passed**: generated cross-stage/native stress, the former ERQ-002/003 cases, ERQ-004 evidence, documentation authority and six focused semantic/IR/SSA/LLVM interface-effect tests. |
| Focused compiler suites | **282 IR**, **72 SSA**, **84 backend/native** and **116 Rust-adapter/shadow** tests passed. |
| Initial IR / SSA repository regression | 117 programs discovered; 101 lowered to IR, 67 comparable across builders, all admitted general-builder programs verified. |
| Rust verifier | `cargo test --workspace --locked` passed every unit, integration and documentation test, including exception and SSA wire-verifier suites. |
| LLVM/native | Clang 21.1.8 compiled and ran the generated O2 stress program twice with byte-identical output/status; the broader Python native suite introduced no failure. |
| Optimizers | Initial IR and SSA optimizer suites passed in the full run; generated qualification runs the verifier after optimized IR and after every SSA pass. |
| Tooling | IntelliJ Gradle tests passed. VS Code tests were not runnable because neither Node nor npm is installed in this environment. Frontend/LSP/formatter Python tests passed apart from the unrelated vector assertions above. |
| Documentation/capabilities/examples/diagnostics | All four standalone contract checkers passed after manifest/document reconciliation. |
| Packaging | Wheel build succeeded; `verify_wheel` then failed on the missing public LeetCode example (ERQ-007). |
| Static hygiene | `compileall` passed for `src`, `tests` and `scripts`; `git diff --check` passed. |

Introduced failures: **0**. Pre-existing failures: **12**. Environment
limitations: VS Code tooling could not run without Node/npm; execution evidence
is Linux x86_64 only. The wheel content rejection is a repository release
defect, not an environment limitation.

Toolchains used: Python 3.14.4, clang 21.1.8, Rust 1.85.1, Java 25.0.3 and
Gradle 9.3.0. The packaged Rust verifier reports protocol 1 / IR schema 1.

## 15. Commit policy

No commit was created by this qualification.
