# Exception Experimental-Support Migration Report

> Milestone: **0 — Preparation**
>
> This report classifies the existing frontend/AST experiment as migration input.
> It does not migrate, delete, enable, or change any behavior.

## Classification rules

| Classification | Meaning |
| --- | --- |
| Reusable infrastructure | Mechanism can support the approved architecture after review and extension. |
| Obsolete experimental behavior | Current semantics conflict with, or are materially narrower than, the frozen model and must not survive as normative behavior. |
| Migration input | Existing shape/test/tooling is useful evidence or a transition point but is not itself approved semantics. |
| Unrelated host implementation detail | A Python/Rust/Kotlin/TypeScript exception used to implement or contain the compiler/tool; it is not an Aether language exception. |

No finding in this report authorizes compatibility with the old behavior.

## Language spellings and lexical support

### `try`, `catch`, and `throw` tokens

- **Paths:** `src/aether/tokens.py`, `src/aether/lexer.py`.
- **Classification:** reusable infrastructure and migration input.
- **Current implementation:** dedicated `TRY`, `CATCH`, and `THROW` token kinds;
  all three spellings are reserved keywords and carry normal token locations.
- **Current semantics:** the lexer recognizes the spellings regardless of backend.
- **Conflict:** none at the lexical-spelling level. Downstream grammar currently
  gives them obsolete single-catch/expression-only behavior.
- **Reusable portions:** token kinds, keyword spellings, lexer location handling,
  and recovery synchronization anchors.
- **Replace later:** parser assumptions and any token consumers that assume one
  untyped catch.
- **Milestone:** M1.

### `Exception` as a built-in type spelling

- **Paths:** `src/aether/tokens.py`, `src/aether/types.py`,
  `src/aether/equality.py`, `src/aether/capabilities.py`.
- **Classification:** obsolete experimental behavior and migration input.
- **Current implementation:** `Exception` is listed beside built-in scalar and
  container types, resolves as a `TYPE` token, appears in type string allowlists,
  and receives capability-special-case treatment.
- **Current semantics:** a dedicated nominal-like runtime value with one message
  field can be declared, constructed, compared only through special cases, thrown,
  and caught by the universal experimental catch.
- **Conflict:** the approved throwable root is the built-in `Error` interface;
  ordinary structs/classes implement it, and no exception class hierarchy or
  magic standalone payload type defines the model.
- **Reusable portions:** none of the semantic special cases. The existing type
  reservation is useful only to locate every migration site.
- **Replace later:** built-in type tables, equality/type allowlists, capability
  detection, and diagnostics must use normal `Error` interface conformance.
  Whether the old spelling is rejected or handled by a separately approved
  compatibility policy must not be invented during M0.
- **Milestone:** M2 for semantic replacement; M10 for tooling; M12 for removal of
  obsolete profile/document references.

## Parser and AST

### Expression-only `ThrowStatement`

- **Paths:** `src/aether/ast.py`, `src/aether/parser.py`.
- **Classification:** migration input with obsolete omissions.
- **Current implementation:** `ThrowStatement` always owns a required expression;
  the parser errors if no expression starts after `throw`.
- **Current semantics:** `throw expression;` is statement-only, which is reusable,
  but bare `throw;` is always a syntax error.
- **Conflict:** the frozen architecture also requires bare rethrow inside a catch
  and requires it to be represented distinctly from a new throw.
- **Reusable portions:** statement placement, semicolon handling, source location,
  and expression throw node tests.
- **Replace later:** make new throw versus bare rethrow explicit in AST and parser;
  keep expression throw out of expression grammar.
- **Milestone:** M1.

### Single untyped `TryCatchStatement`

- **Paths:** `src/aether/ast.py`, `src/aether/parser.py`.
- **Classification:** obsolete experimental behavior and migration input.
- **Current implementation:** one node contains `try_body`, one `catch_name`, and
  one `catch_body`; parser requires exactly `catch (identifier)`.
- **Current semantics:** one universal catch; no explicit catch type, no multiple
  catches, no exact matching, and no ordered dispatch structure.
- **Conflict:** approved syntax requires ordered multiple catches, exact concrete
  catch matching, `Error` as explicit catch-all/root-catch sugar, and nested
  lexical handler semantics.
- **Reusable portions:** block parsing, source location on the try, catch lexical
  scope concept, and nesting afforded by ordinary blocks.
- **Replace later:** introduce a source-located catch-clause representation with
  type/binder/order; parse one or more clauses and preserve order.
- **Milestone:** M1.

### Parser recovery and synchronization

- **Paths:** `src/aether/parser.py`, parser tests in
  `tests/aether/test_exceptions.py`.
- **Classification:** reusable infrastructure.
- **Current implementation:** `try`, `catch`, and `throw` are synchronization
  tokens and existing diagnostics identify missing catch/binder/expression.
- **Current semantics:** diagnostics are tied to the legacy grammar.
- **Conflict:** current “expected expression” for every `throw;` would reject legal
  rethrow; recovery has no malformed typed/multiple-catch cases.
- **Reusable portions:** recovery framework, token locations, and diagnostic
  exception types.
- **Replace later:** grammar-specific messages, ranges, related spans, and recovery
  cases.
- **Milestone:** M1.

## Type system and flow analysis

### String and `Exception` throwable rule

- **Paths:** `src/aether/typechecker.py`, `tests/aether/test_exceptions.py`.
- **Classification:** obsolete experimental behavior.
- **Current implementation:** `_check_statement` accepts thrown values only when
  their static type is `string`, `Exception`, or unknown.
- **Current semantics:** strings are implicitly converted into exception payloads;
  user structs/classes cannot be thrown.
- **Conflict:** only non-null values implementing the built-in `Error` interface
  are throwable. Strings are not implicitly throwable; struct/class `Error`
  values are.
- **Reusable portions:** statement dispatch, expression type lookup, source
  location attachment, and ordinary interface-conformance infrastructure.
- **Replace later:** remove the string/`Exception` allowlist and validate normal
  `Error` conformance/non-nullness.
- **Milestone:** M2.

### Universal catch variable typed as `Exception`

- **Paths:** `src/aether/typechecker.py`, `src/aether/scope.py`,
  `src/aether/symbols.py`.
- **Classification:** obsolete experimental behavior with reusable scope support.
- **Current implementation:** every catch creates a child scope and defines a
  no-shadowing local `VariableSymbol(name, "Exception")`.
- **Current semantics:** the binder is always the one magic type and is available
  only in the catch body.
- **Conflict:** the binder type is the exact concrete catch type or `Error`; it is
  a catch-scoped borrow with no-escape/lifetime rules.
- **Reusable portions:** child scope, catch-only visibility, and
  `forbid_shadowing=True`.
- **Replace later:** binder type and ownership category; add borrow lifetime and
  escape validation.
- **Milestone:** M2.

### Special `Exception(...)` constructor and `.message`

- **Paths:** `src/aether/typechecker.py`, `src/aether/interpreter.py`,
  `src/aether/formatting.py`.
- **Classification:** obsolete experimental behavior.
- **Current implementation:** call typing and evaluation special-case exactly one
  string argument; field access special-cases `.message`.
- **Current semantics:** constructs a magic payload value and exposes message as a
  field.
- **Conflict:** `Error` is an interface with a nonthrowing `string message()`
  contract; ordinary error constructors and witness dispatch apply. A magic field
  or constructor cannot replace interface conformance.
- **Reusable portions:** existing ordinary struct/class constructor, method, and
  interface dispatch machinery—not the `Exception` branches themselves.
- **Replace later:** remove/quarantine special branches and route through normal
  declarations/conformance/witnesses.
- **Milestone:** M2; native witness/runtime work in M7–M8.

### Return-completeness treatment

- **Paths:** `src/aether/typechecker.py`.
- **Classification:** migration input.
- **Current implementation:** a try/catch always returns only if its try body and
  sole catch body both always return. A throw statement is not currently counted
  as an always-terminating return-flow statement.
- **Current semantics:** designed around one catch and ordinary return only.
- **Conflict:** all ordered catches, unmatched outward propagation, new throw, and
  bare rethrow are terminating control-flow alternatives under unchecked
  semantics.
- **Reusable portions:** existing structured flow analysis framework.
- **Replace later:** complete termination/unreachable analysis for all catch paths
  without adding checked throws to source signatures.
- **Milestone:** M2.

### Unchecked propagation

- **Paths:** current absence across function/interface/callable types in
  `src/aether/ast.py`, `src/aether/types.py`, `src/aether/symbols.py`,
  `src/aether/typechecker.py`.
- **Classification:** reusable absence / architecture alignment.
- **Current implementation:** functions declare no throws sets and the prototype
  propagates dynamically through interpreter calls.
- **Current semantics:** effectively unchecked.
- **Conflict:** none in source signature shape. The prototype lacks conservative
  internal `may_throw` metadata and the approved event/cleanup model.
- **Reusable portions:** function/interface/callable source types remain unchanged.
- **Replace later:** add internal conservative facts only; do not add `throws`
  clauses or effect variance.
- **Milestone:** M2–M3.

## AST interpreter and runtime values

### `_ThrownExceptionSignal`

- **Paths:** `src/aether/interpreter.py`.
- **Classification:** migration input; potentially reusable private mechanism.
- **Current implementation:** a Python `Exception` subclass carries one
  `AetherValue`; interpreter frames do not intercept it except at the legacy
  try/catch or root.
- **Current semantics:** Python stack propagation supplies non-local control flow;
  a legacy catch catches every signal and binds its payload.
- **Conflict:** Python exception classes/stack matching cannot define Aether exact
  nominal matching, event ownership, cleanup, provenance, or panic separation.
- **Reusable portions:** a private interpreter-only signal may transport an
  explicit Aether event if matching and lifecycle rules are implemented by Aether
  logic and parity tests. This does not authorize it as IR/runtime representation.
- **Replace later:** carried state, handler selection, rethrow behavior, ownership,
  and root conversion.
- **Milestone:** M2 and M11 parity.

### `AetherExceptionValue`

- **Paths:** `src/aether/types.py`, `src/aether/formatting.py`,
  `src/aether/interpreter.py`.
- **Classification:** obsolete experimental behavior.
- **Current implementation:** frozen `{message, kind="Exception"}` host dataclass.
- **Current semantics:** one payload shape for strings and constructed
  `Exception`s.
- **Conflict:** payloads are ordinary user struct/class values conforming to
  `Error`; event representation is opaque and separately owned.
- **Reusable portions:** none as a source payload model. Its existence identifies
  formatting, field access, root diagnostics, and type-conversion migration sites.
- **Replace later:** ordinary payload plus opaque event in interpreter/runtime.
- **Milestone:** M2 and M8.

### Implicit string conversion on throw

- **Paths:** `src/aether/interpreter.py::_exception_from_value`.
- **Classification:** obsolete experimental behavior.
- **Current implementation:** a thrown string is wrapped in
  `AetherExceptionValue`; an existing `Exception` is reused.
- **Current semantics:** `throw "message";` is legal.
- **Conflict:** strings do not automatically implement `Error`.
- **Reusable portions:** none semantically.
- **Replace later:** require a validated non-null `Error` value and pack it into an
  event without changing struct/class value/reference semantics.
- **Milestone:** M2; packing in M3/M8.

### Catch-all execution and propagation from catch

- **Paths:** `src/aether/interpreter.py::_execute`.
- **Classification:** obsolete experimental behavior and migration input.
- **Current implementation:** catches any `_ThrownExceptionSignal` from try, binds
  it, executes one catch; a signal raised inside that catch escapes naturally.
- **Current semantics:** one catch-all; a catch-body throw skips the same catch,
  which partially resembles the approved outer-handler rule.
- **Conflict:** no ordered exact matching, `Error` root distinction, active event
  ownership, or bare rethrow.
- **Reusable portions:** catch-body execution outside its own Python `try` block is
  a useful structural property for skipping the same handler.
- **Replace later:** explicit ordered matching, active event context, payload
  borrow, destruction on handling, and transfer on rethrow/unmatched paths.
- **Milestone:** M2.

### Unhandled root conversion

- **Paths:** `src/aether/interpreter.py::interpret`,
  `_runtime_error_from_thrown`.
- **Classification:** migration input.
- **Current implementation:** an escaping signal becomes `AetherRuntimeError`
  with message/kind.
- **Current semantics:** exposes the payload as a normal host runtime exception to
  `run_aether` callers; it has no event destruction/provenance contract.
- **Conflict:** approved root handling owns the event, obtains canonical type and
  `message()`, emits deterministic stderr, destroys once, and exits 1; library
  reference paths still need a parity-friendly observation without changing
  source behavior.
- **Reusable portions:** public diagnostic containment and test observation
  patterns.
- **Replace later:** event-aware root behavior and common parity observation.
- **Milestone:** M2 for reference behavior, M8 for native root, M11 for parity.

### Return/break/continue signals and general Python exceptions

- **Paths:** `_ReturnSignal`, `_BreakSignal`, `_ContinueSignal` and numerous
  `try`/`except` blocks under `src/`, `scripts/`, and tests.
- **Classification:** unrelated host implementation detail.
- **Current implementation:** Python non-local control and implementation error
  handling.
- **Current semantics:** not visible as Aether exceptions.
- **Conflict:** none unless a broad host `except` accidentally catches a future
  `_ThrownExceptionSignal`; such boundaries require an audit.
- **Reusable portions:** unchanged host behavior.
- **Replace later:** only narrow overly broad host boundaries that would swallow
  an Aether event.
- **Milestone:** M2/M11 audit; no blanket rewrite.

## Capability and backend boundary

### `ERROR_HANDLING` capability

- **Paths:** `src/aether/capabilities.py`,
  `tests/aether/test_backend_capabilities.py`,
  `tests/aether/test_v1_profile_audit.py`,
  `docs/aether/AETHER_NATIVE_PROFILE_V1.md`.
- **Classification:** reusable infrastructure and migration input.
- **Current implementation:** detector records throw/try-catch and `Exception`
  construction/type; auxiliary AST profile marks it `COMPLETE` and E2E-tested;
  stable native profile marks it `UNSUPPORTED`.
- **Current semantics:** legacy exceptions work only through explicit AST
  execution; native rejects them with `AE-BACKEND-ERROR_HANDLING`.
- **Conflict:** AST completeness describes obsolete semantics and cannot certify
  the approved end-to-end system. Stable rejection is correct and mandatory.
- **Reusable portions:** capability enum/catalog, requirement detector framework,
  fail-closed native validation, diagnostic code, and profile consistency checks.
- **Replace later:** detection details and evidence; remove legacy AST E2E claim or
  redefine it only when reference behavior matches the frozen model. Do not
  promote native before M12.
- **Milestone:** detection updates M1–M2; promotion M12.

### IR lowering rejection

- **Paths:** `src/aether/ir/lowering.py`, `src/aether/pipeline.py`,
  `src/aether/capabilities.py`.
- **Classification:** reusable fail-closed infrastructure.
- **Current implementation:** the lowerer can name `ThrowStatement` and
  `TryCatchStatement` in unsupported-feature diagnostics, while the native
  capability gate rejects them first.
- **Current semantics:** no Initial IR is produced for exceptions.
- **Conflict:** none for M0; later M3 must replace rejection with explicit IR only
  after M1–M2 semantics exist.
- **Reusable portions:** feature naming, gate-before-lowering, and diagnostic
  boundary.
- **Replace later:** actual lowering and operation/edge schemas.
- **Milestone:** M3.

### Absence from Initial IR, SSA, Rust IR, LLVM, and native runtime

- **Paths:** Python `src/aether/{ir,ssa,backend/llvm}/`; Rust
  `compiler-rs/crates/`.
- **Classification:** explicit absence, not reusable experimental behavior.
- **Current implementation:** no invoke/event/match/borrow/throw/propagate
  operation, exceptional edge, schema tag, verifier invariant, landing pad,
  status outcome, or runtime event helper.
- **Current semantics:** native cannot accept exceptions.
- **Conflict:** this is the implementation gap the later milestones close; it is
  not a partial semantic conflict.
- **Reusable portions:** normal CFG/lifecycle/SSA/verifier/effect/runtime helper
  frameworks described in the implementation inventory.
- **Replace later:** add the approved explicit model in M3–M8 after ADR decisions.
- **Milestone:** M3–M8.

## Tests and tooling

### Legacy exception tests

- **Paths:** `tests/aether/test_exceptions.py`.
- **Classification:** migration input and obsolete certification.
- **Current implementation:** 18 tests cover parser nodes, string throw, one
  catch-all, propagation through functions, catch scope, return/break/continue,
  `Exception(...)`, message field, and malformed legacy syntax.
- **Current semantics:** explicitly asserts `throw "boom";`, universal untyped
  catch, magic `Exception`, and rejection of `throw;`.
- **Conflict:** several assertions directly contradict the frozen architecture.
- **Reusable portions:** scope, nesting/control-flow, function propagation, and
  error-location test shapes can be rewritten against typed `Error` examples.
- **Replace later:** reclassify old cases, add frozen positive/negative cases, and
  ensure no old test claims end-to-end support.
- **Milestone:** M1–M2; integrated replacement closure M11.

### Completion and snippets

- **Paths:** `src/autocomplete_engine.py`, indirectly
  `src/aether/language_service.py` and `src/aether_lsp/server.py`.
- **Classification:** obsolete experimental guidance / migration input.
- **Current implementation:** advertises `try`, `catch`, `throw`, `Exception`;
  snippet uses `catch (e)` and throw signature uses a string literal.
- **Current semantics communicated to users:** legacy universal catch and string
  throw.
- **Conflict:** approved typed/root catches and `Error` values; unchecked semantics
  forbid `throws` suggestions.
- **Reusable portions:** completion catalog/snippet mechanism.
- **Replace later:** descriptions, snippets, types, and context-aware bare
  rethrow.
- **Milestone:** M10.

### Syntax highlighting

- **Paths:** `src/ui/code_editor.py`,
  `vscode-extension/syntaxes/aether.tmLanguage.json`,
  `tools/intellij-aether/.../AetherTokenTypes.kt`.
- **Classification:** mixed reusable keyword support and obsolete type support.
- **Current implementation:** all integrations highlight the three keywords and
  the `Exception` type.
- **Current semantics:** highlighting only; it does not establish compiler
  support.
- **Conflict:** keyword spellings remain valid, but root type must be `Error` and
  tooling must represent the approved syntax consistently.
- **Reusable portions:** keyword lists and test harnesses.
- **Replace later:** type list, catch/rethrow cases, fixtures, and generated VS
  Code output when source changes.
- **Milestone:** M1 and M10.

### Source formatter, LSP, and document symbols

- **Paths:** `src/aether/source_formatter.py`, `src/aether_lsp/server.py`,
  `src/document_symbols.py`.
- **Classification:** implementation gap.
- **Current implementation:** formatter has no exception-specific layout; LSP
  delegates diagnostics/formatting/completion; regex document symbols do not
  model catch binders.
- **Current semantics:** generic parser diagnostics reach LSP; no complete editor
  model.
- **Conflict:** later tooling must preserve catch order, scope, binding types,
  source ranges, and nested layout.
- **Reusable portions:** shared compiler analysis, LSP transport, source ranges,
  and symbol framework.
- **Replace later:** add approved exception-aware features; no independent
  matching semantics.
- **Milestone:** M10.

### Web editor host `try/catch`

- **Paths:** `src/ui/web_editor/editor.js` and generated CodeMirror vendor code.
- **Classification:** unrelated host implementation detail.
- **Current implementation:** JavaScript catches initialization/message errors.
- **Current semantics:** UI containment only.
- **Conflict:** none.
- **Reusable portions:** unchanged.
- **Replace later:** no exception-specific change appears necessary unless shared
  LSP/completion wiring changes.
- **Milestone:** M10 audit.

### Kotlin/TypeScript/Rust/Python `Error` and exception names

- **Paths:** host error types throughout `tools/`, `compiler-rs/`, `src/aether/errors.py`,
  LLVM build/run errors, verifier error enums.
- **Classification:** unrelated host implementation detail.
- **Current implementation:** normal implementation-language error propagation and
  containment.
- **Current semantics:** compiler/tool failures, not Aether `Error` interface
  values.
- **Conflict:** none; name similarity must not cause migration.
- **Reusable portions:** all, subject to normal boundary audits.
- **Replace later:** no blanket renaming or conversion.
- **Milestone:** none; component audits in the milestone that touches each path.

## Panic infrastructure

### `may_trap` and native panic helpers

- **Paths:** `src/aether/instruction_effects.py`, IR/SSA model effect properties,
  `src/aether/backend/llvm/*_runtime.py`,
  `tests/aether/parity_corpus/panic*.ae`.
- **Classification:** reusable infrastructure.
- **Current implementation:** checked arithmetic/allocation/memory operations are
  marked `may_trap`; generated LLVM panic helpers print, exit, and end in
  `unreachable`.
- **Current semantics:** fail-fast safety/invariant failure, not catchable.
- **Conflict:** none if kept separate. Reusing `may_trap` as catchable
  `may_throw`, routing panic through handler edges, or packaging panic would
  violate the architecture.
- **Reusable portions:** existing panic taxonomy, effect preservation, native
  helpers, and parity corpus.
- **Replace later:** add a distinct `may_throw` channel and tests proving catches
  never intercept panic.
- **Milestone:** M3, M6–M8, M11.

## Migration sequencing

| Milestone | Required disposition of experimental support |
| --- | --- |
| M1 | Keep lexical spellings; replace AST/parser single-catch and no-rethrow shape; add formatter/highlighter syntax coverage without enabling stable support. |
| M2 | Replace magic `Exception`/string rules with `Error` conformance, exact ordered catch typing, borrow scope, bare rethrow, and reference-interpreter semantics. |
| M3 | Replace fail-closed IR absence with explicit exceptional CFG/event operations and versioned Python/Rust schemas. |
| M4 | Add exceptional cleanup and event linearity; no legacy host unwinding may substitute for lifecycle expansion. |
| M5 | Select the ADR representation and carry edge-specific event ownership through SSA and both verifier paths. |
| M6 | Audit every listed optimizer and preserve panic/throw distinction. |
| M7–M8 | Select backend/runtime ADRs and implement opaque event transport/root handling; do not preserve `AetherExceptionValue` as an ABI. |
| M9 | Add or reject raw-C adapters explicitly; no current FFI behavior needs compatibility. |
| M10 | Replace legacy completion/type/snippets and complete LSP/editor parity. |
| M11 | Reclassify/replace legacy tests and prove reference/IR/SSA/native parity. |
| M12 | Remove remaining obsolete paths/shims and promote `ERROR_HANDLING` atomically only after all evidence is green. |
