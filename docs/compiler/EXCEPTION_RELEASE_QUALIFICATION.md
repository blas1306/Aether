# Exception Release Qualification

> Classification: **Audit**. Date: **2026-08-02**; ERQ-006 update:
> **2026-08-03**.
>
> Baseline: commit `83da5fb` (`feat(exceptions): enforce native boundary
> containment`). This report qualifies the existing implementation; it does not
> change exception semantics, Initial IR, SSA, the accepted ADRs, the private
> runtime ABI, or backend architecture.

## Decision

# DO NOT PROMOTE

`ERROR_HANDLING` remains `UNSUPPORTED` in native capability profile 23.
ERQ-001 through ERQ-007 are now closed by the implementation, tooling,
integrated corpus and artifact checks. This does not authorize promotion:
maintainer approval and the atomic capability/profile change remain a separate
decision.

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

Hotfix C closes ERQ-004 without changing this promotion decision. Capability
detection now records observable native exception semantics, not nominal
compatibility with `Error`. Ordinary `Error` declarations, values, containers,
nullable values and non-throwing interface dispatch remain within the normal
struct/class/interface capabilities; exception control flow and propagation
continue to produce `AE-BACKEND-ERROR_HANDLING` before IR on the stable route.

Hotfix D closes ERQ-005 without changing this promotion decision. Completion,
hover, document symbols and both shipped highlighters now expose only the
current `Error`-based exception surface. Unsupported rename, semantic-token,
incremental-parse and workspace-index behavior is classified explicitly in
[`EXCEPTION_TOOLING_QUALIFICATION.md`](EXCEPTION_TOOLING_QUALIFICATION.md).

ERQ-006 closes the integrated-evidence gap without changing this promotion
decision. The packaged public corpus and deterministic report are described in
[`EXCEPTION_PROMOTION_EVIDENCE.md`](exceptions/EXCEPTION_PROMOTION_EVIDENCE.md).

## Qualification issues

| ID | Blocking finding | Evidence | Required evidence to close |
| --- | --- | --- | --- |
| ERQ-001 | **CLOSED by Hotfix A.** The typechecker had accepted throwing `Error.message()` implementations; interpreter/runtime/backend code and positive IR/SSA/native tests had modeled a second event. | `test_error_message_implementation_cannot_throw`; `test_error_message_rejects_transitive_throwing_helper`; `test_root_reporter_calls_error_message_as_nonthrowing`; negative native qualification tests | The semantic diagnostic, non-throwing root call, backend invariant, panic separation and documentation consistency tests now enforce one rule. |
| ERQ-002 | **CLOSED by Hotfix B.** Initial IR had selected interface `invoke` from module-wide exception use while function `may_throw` came from a separate call-graph scan, producing IRV-144. | `test_interface_dispatch_only_function_has_consistent_nonthrowing_effect`; `test_interface_exception_effects.py` | The semantic effect summary, carried interface-slot fact, strict IR/SSA verifier checks and LLVM structural regressions now enforce one decision. |
| ERQ-003 | **CLOSED by Hotfix B.** The recorded case used a later `Error.message()` dispatch whose artificial exceptional edge created the incompatible lifecycle join. The slot is semantically nonthrowing, so correct Initial IR has no such edge. | `test_nested_rethrow_mutation_with_later_error_message_verifies`; AST/IR observation is `24\nlater\n` | The same canonical slot effect that closes ERQ-002 removes the unreachable edge; lifecycle rules and verifier strength are unchanged. |
| ERQ-004 | **CLOSED by Hotfix C.** `implements Error` had been classified as native exception syntax even when the program used only ordinary interface semantics. | `test_error_conformance_only_is_release_qualified_as_ordinary_interface_use`; focused positive, negative, mixed, nested-interface, container, nullable and example regressions | The detector now emits only for exception control/effect semantics. Struct/class conformance and ordinary `Error` value use no longer produce `AE-BACKEND-ERROR_HANDLING`; throw/rethrow/try/catch and throwing call/invoke cases remain gated. |
| ERQ-005 | **CLOSED by Hotfix D.** Completion/highlighting had advertised `Exception`, only the implicit root-catch sugar, and string throw; catch binders lacked tooling evidence. | `test_completion_items_include_exception_keywords`, `test_lsp_completion_uses_current_exception_surface_only`, `test_lsp_catch_binder_completion_hover_symbols_and_navigation`, VS Code manifest tests and IntelliJ lexer tests | Completion now favors explicit typed/root catches, `Error`, throwable values and bare rethrow while the parser retains approved `catch (name)` sugar; catch binders and `Error.message()` have focused evidence; unsupported protocol features are classified rather than advertised. |
| ERQ-006 | **CLOSED by integrated release evidence.** The stable route remains gated, while the explicit internal qualification route executes the public corpus without implying promotion. | `corpus/exceptions/catalog.json`; `scripts/check_exception_promotion.py`; `EXCEPTION_PROMOTION_DIFFERENTIAL_REPORT.json` | Eleven positive and nine negative programs pass exhaustive catalog, exact diagnostic, frontend/IR/SSA/native O0/O1/O2 differential and sanitizer gates. |
| ERQ-007 | **CLOSED by artifact verification.** Public examples and the ERQ-006 corpus are packaged exhaustively. | `pyproject.toml`; `MANIFEST.in`; `release.py::verify_wheel`; `release.py::verify_sdist` | Wheel and sdist content verification passes against both machine-readable catalogs. |

Hotfixes A–D and ERQ-006 close ERQ-001 through ERQ-007 without altering lifecycle,
Initial IR or SSA representation, or the private runtime ABI layout/version.

## 1. Architecture audit

| Stage | Result | Finding and evidence |
| --- | --- | --- |
| Frontend | PASS | Expression throw, bare rethrow, typed/root catches, ordering, nesting, recovery and formatting are covered by `test_exceptions.py`, `test_source_formatter.py` and LSP formatter tests. |
| Typechecker | PASS | Core conformance, exact matching and catch rules pass. Throwing direct/transitive `Error.message()` implementations receive `AE-ERROR-MESSAGE-NONTHROWING`. |
| AST interpreter | PASS | Representative handling, mutation, dynamic identity and provenance behave deterministically. Former ERQ-003 now agrees with verified Initial IR. |
| Capability gate | PASS for Hotfix C | The gate remains fail-closed for exception semantics and admits ordinary `Error` interface use without exposing `ERROR_HANDLING`. |
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

No unresolved semantic disagreement remains in the qualified architecture.

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
- Throwing function and constructor bodies, plus direct, indirect and interface
  calls whose effects require exception propagation, remain gated because the
  checked program contains native exception semantics.
- No stable native exception program passes the current gate.
- Struct/class conformance to `Error`, `Error.message()` calls, parameters,
  returns, storage, nullable values, containers and ordinary interface dispatch
  do not record `ERROR_HANDLING` (ERQ-004 closed).
- Capability detection now satisfies the “nothing weaker or stronger” gate for
  the accepted exception architecture.
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

- 90 `V1_NATIVE`;
- 17 `AST_ONLY_EXPERIMENTAL`;
- 0 broken/unclassified.

`pruebaException.ae` requires `AE-BACKEND-ERROR_HANDLING` and remains AST-only
experimental. `Sorts/IllegalArgumentException.ae` only declares an ordinary
`Error` implementation and is now a non-runnable `V1_NATIVE` module. The two tracked
least-squares examples `minCuad.ae` and `minCuad2.ae` were missing from the
manifest; they were added as non-runnable AST-only frontend/plotting
experiments without modifying either example. Stale capability sets and
runtime hashes were refreshed through the canonical manifest updater.

## 7. Tooling audit

| Tool | Result | Qualification |
| --- | --- | --- |
| Formatter | PASS | Typed/root/multiple catches and bare rethrow format idempotently. |
| Syntax highlighting | PASS for the supported lexical surface | VS Code and IntelliJ highlight `try`, `catch`, `throw` and `Error`; neither advertises `Exception`. Semantic tokens are explicitly unsupported. |
| LSP diagnostics | PASS frontend | Reuses parser/typechecker and suppresses host tracebacks; no promoted native exception contract exists. |
| LSP formatting | PASS | Multiple typed handlers are covered. |
| LSP hover | PASS for qualified exception contexts | Catch-binder types and root `Error.message()` have focused tests; hover remains document-local. |
| Completion | PASS for qualified exception contexts | Uses `Error`, typed/root catch snippets, throwable-value syntax and bare rethrow; no checked-exception syntax is suggested. |
| Document symbols | PASS for catch binders | Typed catch binders are scoped symbols with hover, definition and reference evidence. |
| Parser recovery | PASS | Malformed typed catches, missing delimiters/expressions and illegal rethrow are covered. |
| IntelliJ | PASS for qualified integration; structurally partial | Lexer/highlighting and shared-LSP integration cover the exception surface. PSI remains a file shell and is not presented as structural parsing. |
| VS Code | PASS by source inspection; execution environment pending | Grammar and manifest tests cover the exception surface. Runtime test status is recorded per validation environment. |

The detailed supported/unsupported matrix is in
[`EXCEPTION_TOOLING_QUALIFICATION.md`](EXCEPTION_TOOLING_QUALIFICATION.md).
ERQ-005 is closed; the intentionally unsupported areas are not advertised.

## 8. Release audit

- Capability profile 23 and generated native profile agree on
  `error-handling = UNSUPPORTED`.
- Release scripts run capability, documentation, ERQ-006 exception evidence,
  example, diagnostic, compileall, pytest, parity, LLVM and native gates before
  packaging.
- Wheel/sdist metadata derives from the canonical version and verifies required
  runtime files, normative docs and the complete public example manifest.
- Wheel and sdist content verification cover every public example and every
  positive/negative ERQ-006 corpus source (ERQ-007 closed).
- The exception qualification gate is part of local CI and the corpus/report
  are shipped in release artifacts (ERQ-006 closed).
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

- The obsolete source-level `Exception` type is neither a compiler type nor an
  editor/completion entry (ERQ-005 closed).
- The LLVM EH implementation is reachable only through an explicit test-only
  opt-in and is documented as comparison evidence, not production transport.
- Event-out is the sole production internal lowering strategy.
- The old AST exception path now implements the approved Error/event semantics
  and remains an auxiliary interpreter, not a stable profile.
- No historical document, accepted ADR or comparison artifact was deleted.

## 11. Remaining milestones and estimated scope

ERQ-006 and ERQ-007 have no remaining implementation milestone. Promotion,
profile/version changes and maintainer approval remain deliberately separate.

## 12. Files modified by qualification and hotfixes

The original qualification changed only audit/evidence files. Hotfix A added
the semantic `Error.message()` guard and nonthrowing backend enforcement.
Hotfix B adds the shared semantic exception-effect summary, carries its
interface-slot fact through Initial IR/DTO/SSA, strengthens Python and Rust
consistency checks, removes LLVM-side inference, and adds focused cross-stage
regressions. Capability state, public language surface, lifecycle, IR/SSA
representation and runtime ABI remain unchanged.
Hotfix C removes nominal `Error` conformance as a capability trigger, adds
positive/negative/mixed release regressions, and reconciles the public example
catalog and normative detection rule. It does not promote the capability or
change exception architecture.
Hotfix D updates only supported tooling sources, documentation and focused
tests. It removes stale advertised syntax, adds catch-binder language-service
evidence and records unsupported capabilities without changing compiler
semantics or the native capability state.

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
| Full Python suite | **4427 passed, 12 failed, 4 skipped** in the ERQ-006 environment. All 12 failures are pre-existing assertions in `test_import_aliases.py`: the current vector orientation prints a column (`[1.0; 2.0]`) while those tests expect a row (`[1.0 2.0]`). No ERQ-006 file touches that behavior. |
| Hotfix D focused tooling/CLI/release selection | **219 passed**, covering formatter, language service, LSP, CLI, run-file and release-contract behavior. |
| Capability/exception/release regressions | **234 passed**: positive, negative, mixed, module, nested-interface, container, nullable, `Error.message()`, propagation, IR/SSA/native and ERQ-004 qualification coverage. |
| Focused compiler suites | **282 IR**, **72 SSA**, **84 backend/native** and **116 Rust-adapter/shadow** tests passed. |
| Initial IR / SSA repository regression | 117 programs discovered; 101 lowered to IR, 67 comparable across builders, all admitted general-builder programs verified. |
| Rust verifier | The prior qualification passed the full workspace. The ERQ-006 rerun is an environment limitation because `cargo` is not installed. Python/Rust verifier protocol fixtures and adapter tests still pass in the Python suite. |
| LLVM/native | Clang 21.1.8 compiled and ran the generated O2 stress program twice with byte-identical output/status; the broader Python native suite introduced no failure. |
| Optimizers | Initial IR and SSA optimizer suites passed in the full run; generated qualification runs the verifier after optimized IR and after every SSA pass. |
| Tooling | IntelliJ Gradle tests passed. VS Code tests were not runnable because neither Node nor npm is installed in this environment. Frontend/LSP/formatter/CLI focused tests all passed. |
| Documentation/capabilities/examples/diagnostics | All four standalone contract checkers passed after manifest/document reconciliation. |
| Packaging | Current wheel and sdist content verification pass for public examples, the ERQ-006 corpus and its evidence reports (ERQ-007 closed). |
| Static hygiene | `compileall` passed for `src`, `tests` and `scripts`; `git diff --check` passed. |

Introduced failures: **0**. Pre-existing failures: **12**. Environment
limitations: VS Code tooling could not run without Node/npm, Rust could not
rerun without Cargo, and native execution evidence is Linux x86_64 only.

Toolchains used for the ERQ-006 rerun: Python 3.14.4, clang 21.1.8, Java
25.0.3 and Gradle 9.3.0. Cargo/Node/npm were unavailable.

## 15. Commit policy

No commit was created by this qualification.
