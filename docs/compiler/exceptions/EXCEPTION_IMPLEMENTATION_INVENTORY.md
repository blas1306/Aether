# Exception Implementation Inventory

> Milestone: **0 — Preparation**
>
> Snapshot: repository commit `e568e98f93e84ad6529769779073351bd0e66d48`
> inspected on 2026-07-29.
>
> Scope: inventory only. No exception behavior, capability state, schema, or
> runtime contract is changed by this document.

## Classification

| Classification | Meaning |
| --- | --- |
| Direct | A later milestone must change or extend the component. |
| Parity / audit | The component may not need a new representation, but it must consume, expose, reject, or validate the new behavior consistently. |
| Migration input | Existing experimental behavior is not normative and must be deliberately replaced or retired. |
| No change required | Inspection found no exception-specific implementation obligation under the approved architecture. The finding is still recorded so it is not an assumption. |

Milestone ownership below follows
[`EXCEPTION_IMPLEMENTATION_PLAN.md`](../EXCEPTION_IMPLEMENTATION_PLAN.md).

## Frontend, semantic model, and reference execution

| Area | Relevant paths | Current responsibility | Expected impact | Existing support / finding | Owner |
| --- | --- | --- | --- | --- | --- |
| Token model and lexer | `src/aether/tokens.py`, `src/aether/lexer.py` | Defines token kinds, reserved words, built-in type spellings, locations, and lexical recovery. | Direct: retain `try`/`catch`/`throw`, add only the approved grammar-facing type behavior, and test all malformed forms. | Migration input: all three tokens already exist; `Exception` is a built-in `TYPE`. | M1 |
| Parser | `src/aether/parser.py` | Recursive-descent parsing, source locations, block depth, and recovery synchronization. | Direct: statement-only expression throw, distinct bare rethrow, typed/root catch forms, one-or-more ordered catches, nesting, and recovery. | Migration input: parses expression throw and exactly one untyped `catch (name)`; rejects `throw;`. | M1 |
| AST nodes | `src/aether/ast.py` | Frozen dataclass representation of source programs. | Direct: migrate `ThrowStatement` to distinguish new throw from rethrow and replace the single-catch shape with ordered source-located catch clauses and catch types. | Migration input: `ThrowStatement(expression)` and `TryCatchStatement(try_body, catch_name, catch_body)` exist. | M1 |
| AST traversal / visitors | `src/aether/capabilities.py`, `src/aether/typechecker.py`, `src/aether/ir/module_lowering.py`, `src/aether/ir/lowering.py`, `src/aether/backend/llvm/printer.py` | Dataclass-generic walkers plus several explicit statement dispatchers; there is no central AST visitor class. | Direct/audit: generic walkers must see new fields; explicit dispatchers must handle every new node and cannot silently omit catches or rethrow. | Reusable generic dataclass traversal; explicit paths are migration inputs. | M1–M3, M10 |
| AST equality | Dataclass-generated equality in `src/aether/ast.py`; assertions throughout `tests/aether/` | Structural AST comparison; most line/column fields participate unless declared `compare=False`. | Direct/audit: equality must cover catch order, types, binders, and rethrow identity; add focused tests. | Reusable infrastructure; no separate equality module. | M1 |
| AST serialization / debug rendering | No public AST serializer found; dataclass `repr` is the current debug form. `src/aether/ir/dto.py` serializes IR, not AST. | There is no independent persisted AST schema to migrate. | No production serializer change currently required; M1 must add coverage if a serializer appears before implementation. Debug `repr` changes naturally with the dataclasses. | Explicit no-change finding after inspection. | M1 audit |
| Source formatter | `src/aether/source_formatter.py`, `tests/aether/test_source_formatter.py` | Token/whitespace transformations and control-header migration; not a full AST pretty-printer. | Direct: canonical layout, nesting, ordered catch layout, incomplete-source handling, and idempotence. | No exception-specific formatting exists despite syntax acceptance. | M1, M10 |
| Runtime value formatting | `src/aether/formatting.py`, `src/aether/types.py` | Formats AST-interpreter values, including the experimental exception carrier. | Direct/migration: ordinary `Error` struct/class formatting remains ordinary value formatting; diagnostics must use the approved `Error.message()` path rather than preserve magic `Exception` formatting as semantics. | Migration input: `AetherExceptionValue` and `format_exception`. | M2, M8 |
| Reference/AST interpreter | `src/aether/interpreter.py`, `src/aether/runner.py`, `src/aether/session.py`, `src/aether/runtime_state.py` | Executes typed AST and implements function/loop/return control transfer using Python signals. | Direct: exact ordered matching, nested handler boundaries, catch borrow, bare rethrow, root behavior, and parity. Host implementation details must not define source semantics. | Obsolete experimental behavior: `_ThrownExceptionSignal`, string-to-`Exception` conversion, single catch-all, and root conversion to `AetherRuntimeError`. Reusable signal pattern only as a private interpreter mechanism. | M2, M11 |
| Host-language control signals | `src/aether/interpreter.py` (`_ReturnSignal`, `_BreakSignal`, `_ContinueSignal`, `_ThrownExceptionSignal`) | Uses Python exceptions to leave nested interpreter calls. | Audit: return/break/continue are unrelated host implementation details; the thrown-event signal is migration input and may remain only if it implements the frozen event state and matching independently of Python exception classes. | Mixed classification; see migration report. | M2 |
| Built-in types and interfaces | `src/aether/tokens.py`, `src/aether/types.py`, `src/aether/builtins.py`, `src/aether/stdlib/registry.py`, `src/aether/interface_abi.py`, `src/aether/native_members.py` | Defines source type spellings, runtime value types, built-ins, interface conformance/ABI helpers, and native members. | Direct: install built-in `Error` through normal interface machinery, its nonthrowing `message()` witness, existential ownership, and struct/class conformance. | Migration input: magic nominal `Exception` scalar-like type; ordinary interfaces are reusable. | M2, M8 |
| Typechecker | `src/aether/typechecker.py` | Declaration collection, aliases, conformance, expression/statement typing, return flow, and semantic diagnostics. | Direct: throwable validation, exact catch types/order, catch borrow and no-escape rules, lexical rethrow, unchecked call facts, and updated termination analysis. | Obsolete behavior: accepts only `string`/`Exception`, binds every catch as `Exception`, special-cases constructor and `.message`. | M2 |
| Symbols and scopes | `src/aether/symbols.py`, `src/aether/scope.py` | Represents variables/functions/structs/enums/interfaces and enforces lexical definitions and shadow rules. | Direct: represent catch binders with their concrete/root type and borrowed lifetime; retain catch-local no-shadowing behavior. | Reusable scope infrastructure; current `VariableSymbol(..., "Exception")` is migration input. | M2 |
| Modules and imports | `src/aether/modules.py`, module logic in `src/aether/typechecker.py`, `src/aether/interpreter.py`, `src/aether/ir/module_lowering.py` | Resolves module files, public/private declarations, aliases, checked programs, and imported runtime declarations. | Direct/audit: canonical nominal error identity across aliases/modules, imported `Error` conformance, descriptor uniqueness, and unchecked compatibility. | No exception-aware nominal descriptor contract exists. Ordinary `SymbolId`/module qualification is reusable. | M2, M3, M8 |
| Entry point | `src/aether/entry_point.py` | Normalizes scripts to `main`, validates explicit entry points, and appends synthetic return. | Parity/audit: terminating throw must participate in completion analysis; an event escaping `main` routes to root handling. | No exception-specific root contract exists outside AST interpreter conversion. | M2, M3, M8 |
| Diagnostics | `src/aether/errors.py`, `src/aether/diagnostics.py`, `docs/aether/AETHER_DIAGNOSTICS.md`, `scripts/check_diagnostics_contract.py` | Source errors, public diagnostic categories/codes, ICE containment, rendering, and debug traceback policy. | Direct: stable parser/type/IR/SSA/backend/runtime exception diagnostics and source spans; keep compiler-host exceptions distinct from Aether events. | `AetherError(Exception)` and diagnostic `Exception` annotations are unrelated host details; experimental throw errors are migration input. | M1–M11 |
| Capabilities | `src/aether/capabilities.py`, `docs/aether/AETHER_NATIVE_PROFILE_V1.md`, `docs/aether/BACKEND_CAPABILITY_PROFILES.md`, `scripts/check_capability_consistency.py`, `scripts/render_native_profile.py` | Catalogues features, detects AST requirements, gates backend use, and renders the stable native profile. | Direct/audit: detect every approved syntax/type use, remain fail-closed, and promote only in M12. | Existing `ERROR_HANDLING`; AST auxiliary profile says complete, stable native profile says unsupported. | M0, M12 |
| Differential/reference execution | `src/aether/differential.py`, `scripts/differential_parity.py`, `tests/aether/parity_corpus/` | Compares AST and native stdout/stderr/exit status at O0/O1/O2. | Direct: add catch selection, cleanup/event traces, rethrow, unhandled exception, and panic separation; do not treat AST-only legacy behavior as an oracle. | Reusable harness; no exception cases because native gate rejects them. | M6, M11 |

## Initial IR and pre-SSA lifecycle

| Area | Relevant paths | Current responsibility | Expected impact | Existing support / finding | Owner |
| --- | --- | --- | --- | --- | --- |
| Instruction effects | `src/aether/instruction_effects.py`, effect properties in `src/aether/ir/model.py` and `src/aether/ssa/model.py` | Shared `may_trap`, memory, allocation, and preservation facts for IR/SSA. | Direct: add catchable `may_throw` distinct from `may_trap`; unknown/indirect calls are conservative without making panic catchable. | No `may_throw`; current `UNKNOWN_CALL.may_trap` is reusable but insufficient. | M3 |
| Initial IR schema/model | `src/aether/ir/model.py`, `src/aether/ir/types.py`, `src/aether/ir/__init__.py` | Dataclass IR values, storage, instructions, terminators, blocks, functions, modules, and types. | Direct: opaque event type, edge kinds/payloads, invoke, pack, new throw, propagate/rethrow, exact match, borrow, transfer/destroy, and function metadata. | No exception/event operation or exceptional edge exists. | M3 |
| AST-to-IR lowering | `src/aether/ir/lowering.py`, `src/aether/ir/module_lowering.py` | Lowers checked AST/modules to explicit storage-oriented Initial IR and rejects unsupported AST features. | Direct: lower ordered/nested handlers and all call forms to explicit two-successor CFG, preserving source locations and root propagation. | Current generic unsupported-feature reporting names throw/try-catch; native capability gate normally rejects them earlier. | M3 |
| CFG utilities | `src/aether/analysis/cfg.py`, compatibility shim `src/aether/ir/cfg.py` | Builds successors/predecessors from branch/jump and emits DOT. | Direct: model edge kind and event payload; include exceptional edges in reachability and visualization. | Reusable graph structure, currently normal edges only. | M3, M5, M10 |
| Lifecycle registry and expansion | `src/aether/ir/lifecycle.py`, `docs/compiler/VALUE_LIFECYCLE_DESIGN.md` | Classifies lifecycle traits and expands generic init/copy/move/assign/destroy before SSA. | Direct: exceptional cleanup ladders, initialized-prefix rollback, event formation/transfer/borrow/destroy state, and cleanup sharing constraints. | Strong reusable normal-path lifecycle foundation; no exceptional cleanup. | M4 |
| Ownership and ARC verification (Python) | `src/aether/ir/verifier.py`, lifecycle calls/types in `src/aether/ir/model.py` | Structural, type, storage-state, ownership completion, and lifecycle validation. | Direct: exceptional exits, cleanup order, partial initialization, event linearity, borrow lifetime, and panic separation. | Reusable verification framework; no event concept. | M3–M5 |
| IR operand traversal | `src/aether/_operand_traversal.py`, `src/aether/ir/operands.py` | Enumerates/results/rewrites dataclass operands and asserts instruction coverage. | Direct: every event and edge operand must participate in use, rewrite, optimizer, and completeness checks. | Reusable generic machinery with fail-closed coverage tests. | M3, M6 |
| IR equality | `src/aether/ir/equality.py` and dataclass equality in `src/aether/ir/model.py` | Language equality capability plus structural dataclass equality used in IR tests. | Audit/direct: distinguish source `Eq` from structural compiler equality; structural comparison must include edge kind, event operands, catch order, and metadata. | No exception semantics; dataclass equality reusable. | M3 |
| IR DTO/JSON schema | `src/aether/ir/dto.py`, DTO tests under `tests/aether/test_ir_*_dto.py` | Strict versioned Python wire schema, exact fields, instruction registry completeness, JSON encoding/decoding. | Direct: version schema, encode all new types/operations/edges/effects, reject unknown old/new combinations, and preserve deterministic round trips. | Reusable strict registry; no exception tags. | M3 |
| IR printer | `src/aether/ir/printer.py` | Human-readable Initial IR. | Direct: print edge kinds, handler/event state, operations, provenance, and ownership visibly. | No exception form. | M3, M10 |
| IR interpreter | `src/aether/ir/interpreter.py` | Executes verified Initial IR and implements panic-like failures as `IRExecutionError`. | Direct: execute explicit handler dispatch/event state and root behavior while retaining panic as distinct uncatchable failure. | No catchable exception support; host `try` blocks are unrelated. | M3, M11 |
| Python verifier adapter/result | `src/aether/ir/verification_result.py`, `src/aether/ir/rust_verifier.py`, `src/aether/ir/rust_verifier_client.py` | Normalizes Python/Rust verification results and invokes the Rust authority executable. | Direct/parity: new invariants, protocol/schema version, stable diagnostics, and fail-closed mismatch behavior. | Reusable adapter/protocol. | M3–M5 |

## Initial IR optimizer audit

Every enabled Initial IR pass was inspected. None currently knows about
exceptional edges or event ownership.

| Pass | Path | Current role | Exception obligation | Owner |
| --- | --- | --- | --- | --- |
| Constant folding | `src/aether/ir/optimizer/constant_folding.py` | Folds pure constant arithmetic/comparisons/casts. | Respect `may_throw`, panic order, exact descriptor identity, and handler selection; never evaluate/suppress a throw. | M6 |
| Local constant propagation | `src/aether/ir/optimizer/local_constant_propagation.py` | Propagates constants within blocks. | Keep normal results and event values edge-local; cleanup/event uses remain uses. | M6 |
| Algebraic simplification | `src/aether/ir/optimizer/algebraic_simplification.py` | Applies algebraic identities. | Do not discard or reorder throwing/trapping operands or event operations. | M6 |
| Dead-code elimination | `src/aether/ir/optimizer/dead_code.py` | Removes unused effect-free results. | Treat throw, invoke exceptional edges, matching, cleanup, transfer, and destroy as observable roots. | M6 |
| Dead-store elimination | `src/aether/ir/optimizer/dead_store.py` | Removes overwritten/unobserved stores. | Include exceptional liveness, initialization state, destructor obligations, and partial rollback. | M6 |
| Pipeline and accounting | `src/aether/ir/optimizer/pipeline.py`, `result.py`, `__init__.py` | Selects O0/O1/O2 passes, convergence, verification, and traces. | Register pass exception-safety status, verify after each pass, and report exceptional CFG changes. | M6 |

No separate Initial IR copy propagation, ARC optimization, inlining, LICM, GVN,
or bounds-check-elimination pass exists in this snapshot. Adding those pass
families is **not required** by exception work, but any future implementation is
subject to the frozen optimizer contract before it may run on exception-bearing
IR.

## SSA and graph analysis

| Area | Relevant paths | Current responsibility | Expected impact | Existing support / finding | Owner |
| --- | --- | --- | --- | --- | --- |
| SSA representation | `src/aether/ssa/model.py`, `src/aether/ssa/__init__.py` | SSA values/instructions/phis/blocks/functions/modules mirroring Initial IR operations. | Direct after ADR: represent exceptional predecessors and edge-only result/event values, plus linear event selection. | No exception or edge-defined values. | M5 |
| Pattern SSA builder | `src/aether/ssa/builder.py` | Converts supported structured IR shapes using specialized plans. | Direct: either implement the chosen representation completely or reject exception-bearing IR explicitly. | No exception path; silent fallback is forbidden later. | M5 |
| General SSA builder | `src/aether/ssa/general_builder.py` | General storage-to-SSA conversion. | Direct: complete CFG, edge-specific definitions, cleanup blocks, and event ownership. | Reusable general foundation; currently normal CFG only. | M5 |
| Phi placement | `src/aether/ssa/phi_placement.py` | Places phis from definitions and dominance frontiers. | Direct: include exceptional predecessors and ownership-aware event joins. | No exceptional inputs. | M5 |
| Renaming | `src/aether/ssa/renaming.py` | Renames storage definitions/uses through dominator traversal. | Direct: edge operands and invoke normal/event availability; catch borrows cannot outlive event. | No exception-specific definitions. | M5 |
| CFG analysis | `src/aether/analysis/cfg.py` | Canonical CFG/predecessor/successor representation. | Direct: include both edge kinds exactly once and preserve provenance through splitting. | Normal graph only. | M3, M5 |
| Dominators | `src/aether/analysis/dominators.py` | Computes dominator tree/set over canonical CFG. | Direct: operate on complete normal+exceptional CFG. | Algorithm reusable when graph input becomes complete. | M5 |
| Dominance frontier | `src/aether/analysis/dominance_frontier.py` | Computes frontiers used by phi placement. | Direct: exceptional predecessors change frontiers. | Algorithm reusable with complete CFG. | M5 |
| SSA auxiliary analyses | `src/aether/ssa/analysis/lattice.py`, `worklist.py` | Generic lattice/worklist utilities. | Parity/audit: no exception-specific change appears necessary; consumers must enqueue exceptional executable edges and event facts correctly. | Explicit no-change finding for generic containers. | M5–M6 |
| SSA printer | `src/aether/ssa/printer.py` | Stable human-readable SSA/JSON-like rendering. | Direct: show edge kinds, edge arguments/results, handler entries, event ownership, and cleanup. | No exception form. | M5, M10 |
| SSA operand traversal | `src/aether/ssa/operands.py`, `src/aether/_operand_traversal.py` | Enumerates/replaces SSA operands and results. | Direct: include event/edge operands and retain completeness assertions. | Reusable generic machinery. | M5 |
| SSA verifier (Python) | `src/aether/ssa/verifier.py` | Definition/use, predecessor/phi, same-block order, dominance, type, and structural validation. | Direct: full-CFG dominance, exact predecessor/edge arity, edge availability, cleanup ordering, event single consumption, and borrow lifetime. | No event/exception invariants. | M5 |

## SSA optimizer audit

| Pass | Path | Current role | Exception obligation | Owner |
| --- | --- | --- | --- | --- |
| SSA constant folding | `src/aether/ssa/optimizer/constant_folding.py` | Folds constant SSA operations. | Preserve throwing/trapping evaluation and edge feasibility; descriptor folds require canonical identity proof. | M6 |
| Global constant propagation | `src/aether/ssa/optimizer/global_constant_propagation.py` | Propagates constants over CFG. | Keep facts separated by edge kind and event ownership path. | M6 |
| Algebraic simplification | `src/aether/ssa/optimizer/algebraic_simplification.py` | Applies SSA algebraic rewrites. | Preserve effects, cleanup points, handler context, and replacement dominance. | M6 |
| Dead-code elimination | `src/aether/ssa/optimizer/dead_code.py` | Removes unused effect-free definitions. | Treat all exceptional successors and event/cleanup uses as live. | M6 |
| SCCP analysis/transform | `src/aether/ssa/optimizer/sccp.py` | Tracks lattice values and executable CFG edges, then rewrites. | Add exceptional edge executability; an edge is infeasible only with a trusted nonthrow proof. | M6 |
| SCCP pass adapter | `src/aether/ssa/optimizer/sccp_pass.py` | Integrates SCCP analysis/transform with the optimizer pipeline. | Preserve verification and exceptional-change accounting. | M6 |
| Dead phi elimination | `src/aether/ssa/optimizer/dead_phi.py` | Removes unused phis. | Event/block arguments are ownership transfers and cannot be dropped if doing so leaks or bypasses consumption. | M6 |
| Trivial phi elimination | `src/aether/ssa/optimizer/trivial_phi.py` | Collapses equivalent incoming values. | Preserve edge availability, full-CFG dominance, and linear event selection. | M6 |
| Pipeline and accounting | `src/aether/ssa/optimizer/pipeline.py`, `result.py`, `__init__.py` | Runs enabled SSA passes, convergence, verification, and traces. | Require an exception-safety disposition and post-pass verification for every enabled pass. | M6 |

No separate SSA copy propagation, ARC optimization, inlining, LICM, GVN, or
bounds-check-elimination pass exists in this snapshot. The same fail-closed
future-pass rule as Initial IR applies.

## Rust schemas, importers, and verifiers

| Area | Relevant paths | Current responsibility | Expected impact | Existing support / finding | Owner |
| --- | --- | --- | --- | --- | --- |
| Rust owned IR | `compiler-rs/crates/aether-ir/src/{types,value,instruction,block,function,module,structure,constant,source}.rs` | Rust mirror of Python Initial IR. | Direct: atomic mirror of event type, effects/metadata, operations, terminators, and edge payloads. | No exception variants. | M3 |
| Rust wire schema | `compiler-rs/crates/aether-ir/src/wire.rs`, `json.rs` | Strict Serde DTOs, schema version, and JSON boundary. | Direct: version and reject unknown/partial exception representations. | Reusable fail-closed schema. | M3 |
| Rust importer | `compiler-rs/crates/aether-ir/src/importer.rs` | Converts wire DTO to owned IR while retaining typed error context. | Direct: import every new representation without semantic guessing. | No exception variants. | M3 |
| Structural verifier | `compiler-rs/crates/aether-verifier/src/{structure_verifier,structure_error,cfg}.rs` | Terminator shape, targets, blocks, CFG. | Direct: invoke/throw/propagate terminators and exceptional successors. | Normal CFG only. | M3 |
| Type/borrow verifier | `compiler-rs/crates/aether-verifier/src/{verifier,error,borrow_error}.rs` | Operation typing and borrow restrictions. | Direct: event types, match-dominated borrow, catch borrow lifetime, and call/effect agreement. | No event type. | M3–M5 |
| Lifecycle verifier | `compiler-rs/crates/aether-verifier/src/{lifecycle_verifier,lifecycle_error}.rs` | Local and dataflow lifecycle state, reachable-exit ownership completion. | Direct: exceptional exits, cleanup order, partial initialization, and linear event consumption. | Reusable state/dataflow foundation. | M4 |
| SSA/dominance verifiers | `compiler-rs/crates/aether-verifier/src/{ssa_verifier,ssa_error,dominance_verifier,dominance_error}.rs` | Definition/use and full ordinary-CFG dominance over imported Initial IR form. | Direct: exceptional predecessor sets, edge availability, event ownership, and complete CFG dominance. | No exceptional edges. | M5 |
| Return and combined verifiers | `compiler-rs/crates/aether-verifier/src/{return_verifier,return_error,combined_verifier}.rs` | Return-path rules and canonical phase/error normalization. | Direct/audit: throw/propagate are terminating exits; new phases/invariants must retain stable ordering and diagnostics. | Reusable orchestration. | M3–M5 |
| Executable/protocol | `compiler-rs/crates/aether-ir-verifier/src/{lib,main}.rs` | Versioned request/response protocol and stable verifier executable identity. | Direct: schema/protocol versioning, diagnostic mappings, and panic containment. | Reusable infrastructure. Rust `panic` catching here is a host boundary, not Aether exception behavior. | M3–M5 |
| Python extension crate | `compiler-rs/crates/aether-python/src/lib.rs` | Placeholder Python integration crate; currently no tests or exception bridge. | No immediate exception change required unless it becomes an active importer/runtime bridge before M3; then it must follow the same schema/ABI. | Explicit no-change finding. | M3 audit |

## Shadow, canary, and parity infrastructure

| Area | Relevant paths | Current responsibility | Expected impact | Existing support / finding | Owner |
| --- | --- | --- | --- | --- | --- |
| Shadow verifier | `src/aether/ir/shadow_verifier.py`, `shadow_divergences.py`, `tests/shadow_validation_harness.py`, `tests/aether/test_shadow_*` | Runs Python/Rust verification together and classifies divergences. | Direct: shared valid/invalid exception corpus, normalized invariants, no permissive fallback. | Reusable; no exception fixtures. | M3–M5, M11 |
| Rust authority/canary | `src/aether/ir/rust_verifier*.py`, `scripts/rust_verifier_{canary,soak,platform_snapshot}.py`, `tests/rust_authority_canary_harness.py`, `tests/canary/rust_verifier_canary.json` | Selects packaged verifier and measures authority/canary behavior. | Direct/audit: schema version and exception invariants must be represented in fixtures and operational evidence. | Reusable infrastructure. | M3–M5, M11 |
| Differential parity | `src/aether/differential.py`, `scripts/differential_parity.py`, `tests/aether/parity_corpus/` | AST/native observations at optimization levels. | Direct: event/cleanup-aware outcome oracle and panic/throw separation. | Reusable harness; native exception cases absent. | M6, M11 |

## LLVM backend, runtime, ABI, and FFI

| Area | Relevant paths | Current responsibility | Expected impact | Existing support / finding | Owner |
| --- | --- | --- | --- | --- | --- |
| LLVM backend entry | `src/aether/backend/llvm/backend.py`, `printer.py`, `types.py` | Converts verified SSA to textual LLVM and rejects unsupported shapes. | Direct after ADR: lower all exception operations/edges/call forms, preserve locations, enforce malformed-IR rejection, and integrate private ABI. | No exception lowering, landing pads, status outcomes, or event type. | M7 |
| Runtime helper emission | `src/aether/backend/llvm/{runtime_common,runtime,array_runtime,list_runtime,string_runtime,class_runtime,integer_runtime,io_runtime,matrix_runtime,vector_runtime,scalar_math_runtime,process_runtime,text_file_runtime}.py` | Emits in-module LLVM helpers for allocation, ARC, collections, strings, IO, math, and fail-fast panics. | Direct/audit: selected private event ABI, canonical descriptors, root reporting, and strict panic separation. Existing typed ARC helpers are reusable. | No exception runtime. Many `*_panic` helpers terminate with `exit`/`unreachable` and must remain uncatchable. | M7–M8 |
| Native layouts/descriptors | `src/aether/backend/llvm/layout.py`, `class_runtime.py`, interface/witness emission in `printer.py`, `src/aether/interface_abi.py` | Computes layouts and emits class/interface carriers and witnesses. | Direct: canonical `Error` witness and collision-safe nominal error descriptors without exposing event layout. | Reusable object/interface foundation; no exception descriptor identity. | M7–M8 |
| Build/run harness | `src/aether/backend/llvm/{build,run}.py`, `src/aether/cli.py` | Emits LLVM, invokes clang, runs binaries, and translates toolchain failures. | Parity/direct: native exception termination, source diagnostics, exit status, target strategy, and tests at O0/O1/O2. | Host `LLVMBuildError`/`LLVMRunError` are unrelated implementation exceptions. | M7, M11 |
| Native ABI documentation | `docs/compiler/AETHER_NATIVE_ABI.md` | Records current internal native layout and future narrow C boundary principles. | Direct documentation update after private runtime ABI selection; must not declare a public exception ABI. | Current document explicitly says FFI/precompiled objects are unimplemented and recommends opaque handles/status/out parameters. | M8–M9 |
| Runtime extraction | No standalone `runtime/` directory or separate runtime library exists; helpers are emitted from Python backend modules. | Current runtime is embedded into generated LLVM. | Direct architectural work in M8 according to selected ABI; do not infer that a standalone library is mandatory if ADR selects another private organization. | Explicit absence; no stack scanner. | M8 |
| FFI imports/exports/callbacks | No Aether `extern` grammar, public export ABI, callback adapter, or FFI implementation found. Callable values/interface calls are internal language mechanisms. | No current raw-C language boundary. | Direct future work: containment/rejection and explicit adapters once FFI surface exists; raw C imports are nonthrowing. | Explicit no-change-now/required-future finding. No existing exception can cross raw C because no raw-C FFI exists. | M9 |

## CLI, formatter, language service, and editor tooling

| Area | Relevant paths | Current responsibility | Expected impact | Existing support / finding | Owner |
| --- | --- | --- | --- | --- | --- |
| CLI | `src/aether/cli.py`, `src/aether/__main__.py`, `src/aether/benchmark.py`, `tests/test_aether_cli.py` | Check/run/build/emit/bench commands, backend selection, and public diagnostics. | Direct/audit: consistent source errors, root unhandled diagnostics, emit views with exceptional edges, and no AST fallback. | Native gate rejects exceptions; `--backend=ast` can execute the legacy prototype. | M7, M10–M12 |
| Source formatter | `src/aether/source_formatter.py`, LSP formatting in `src/aether_lsp/server.py` | Formats source for CLI/LSP editor clients. | Direct as above; one canonical implementation must serve CLI/editor paths. | No exception-specific formatter. | M1, M10 |
| Language service | `src/aether/language_service.py`, `src/autocomplete_engine.py`, `src/document_symbols.py` | Parse/type diagnostics, run helper, completions, member contexts, and regex-based document symbols. | Direct: `Error`, legal throw/rethrow/catch completion, catch binder symbols/types, recovery, and unchecked semantics. | Migration input: completion advertises legacy `Exception`, untyped catch snippet, and string throw. Document symbols have no catch-binder extraction. | M10 |
| LSP | `src/aether_lsp/server.py`, `run_file.py`, `tests/test_aether_lsp_*` | Diagnostics, formatting, completion, symbols, hover, definition/references/rename, and run-file transport. | Direct: expose compiler semantics/ranges consistently and add semantic exception features. Current server advertises no semantic-token capability. | Reuses compiler parser/typechecker; no exception-specific LSP behavior beyond generic keywords/completion. | M10 |
| VS Code | `vscode-extension/syntaxes/aether.tmLanguage.json`, `language-configuration.json`, `src/`, `test/`, generated `out/` | TextMate highlighting, language configuration, LSP/CLI client, commands. | Direct: update grammar/types/snippets if added, test source files, then regenerate `out/`; do not hand-edit generated output. | Migration input: highlights `try`/`catch`/`throw` and `Exception`. | M1, M10 |
| IntelliJ | `tools/intellij-aether/src/main/kotlin/com/aetherstudio/intellij/`, especially `AetherTokenTypes.kt`, highlighting/parser/typing support; tests under `src/test/` | Independent lexer/highlighter/PSI shell, typing helpers, LSP client, run configuration. | Direct: approved keywords/type, catch/rethrow typing/auto-pairing, tests, and LSP parity. | Migration input: keyword list and `Exception` type are hard-coded. Kotlin host exceptions are unrelated. | M1, M10 |
| Qt/UI editor | `src/ui/code_editor.py`, `src/ui/codemirror_editor.py`, `src/autocomplete_engine.py`, tests `tests/test_qt_*`, `tests/test_editor_api.py` | Syntax highlighting, completion popup, editor abstraction, and embedded editor choice. | Direct: replace legacy type/snippet/highlight assumptions and test incomplete/nested syntax. | Migration input: hard-coded `Exception`, `try`, `catch`, `throw`; generic UI `try/except` blocks are unrelated. | M1, M10 |
| Web/UI editor | `src/ui/web_editor/{index.html,editor.js,editor.css,README.md}`, `tools/web_editor/src/codemirror-entry.js`, generated `src/ui/web_editor/vendor/codemirror.bundle.js` | Embedded CodeMirror shell and generated editor library asset. Syntax semantics arrive primarily through shared LSP/editor services. | Parity/audit: ensure shared diagnostics/completion/formatting work; rebuild vendor bundle only if dependency/source entry changes. | No Aether grammar in the bundle entry and no exception-specific source logic; JS `try/catch` is unrelated. Bundle rebuild currently appears unnecessary. | M10 |

## CI, release, documentation, and tests

| Area | Relevant paths | Current responsibility | Expected impact | Existing support / finding | Owner |
| --- | --- | --- | --- | --- | --- |
| Local CI | `scripts/ci.py`, `docs/compiler/CI.md`, `tests/test_ci.py` | Runs consistency, docs, examples, diagnostics, compileall, pytest, benchmarks, LLVM, parity, and native builds. | Direct: add exception matrices, Rust/schema parity, editor suites where appropriate, and promotion evidence without hiding skips. | Reusable pipeline; current pre-existing examples-catalog failure is in the baseline. | M11–M12 |
| Hosted CI | `.github/workflows/rust-verifier-operational.yml`, `.github/workflows/vscode-extension.yml` | Rust verifier operational matrix and VS Code npm tests. | Direct: schema/version corpus and editor coverage; add sanitizer/target jobs at promotion. | Reusable jobs; no exception cases. | M3–M12 |
| Release scripts | `scripts/release.py`, `scripts/check_release_docs.py`, `scripts/render_native_profile.py`, `scripts/check_examples_catalog.py`, `scripts/check_capability_consistency.py`, `scripts/package_rust_verifier.py` | Packages artifacts, checks normative docs/profile/examples, and packages Rust authority. | Direct/audit: keep gate disabled, version schemas, classify legacy examples/tests, and promote atomically with release evidence. | Capability consistency currently passes with native `ERROR_HANDLING=UNSUPPORTED`. | M0, M12 |
| Normative/current docs | `docs/aether/AETHER_LANGUAGE_SPEC_V1.md`, `AETHER_NATIVE_PROFILE_V1.md`, `AETHER_FRONTEND_EXPERIMENTS.md`, `AETHER_DIAGNOSTICS.md`, `docs/compiler/AETHER_NATIVE_ABI.md`, `FEATURE_MATRIX.md`, `README.md`, `CHANGELOG.md` | Defines stable profile, experimental annex, diagnostics, ABI status, feature matrix, and release-facing behavior. | Direct staged updates: continue to label the old prototype experimental until atomic promotion; document approved semantics/runtime/FFI after implementation. | Current stable spec reserves spellings but excludes exceptions; frontend annex lists them as experimental. | M0, M10–M12 |
| Architecture docs | `docs/compiler/COMPLETE_EXCEPTION_MODEL_RFC.md`, `COMPLETE_EXCEPTION_MODEL_DECISION_LOG.md`, `CHECKED_EXCEPTIONS_ARCHITECTURE_STUDY.md`, `EXCEPTION_ARCHITECTURE_RESOLUTION.md`, `EXCEPTION_IMPLEMENTATION_PLAN.md` | Frozen authority and engineering roadmap. | Parity/audit only; implementation PRs must not edit them to reinterpret semantics. Hashes are frozen in the baseline report. | Approved input. | All |
| Python tests | `tests/aether/`, top-level `tests/`, fixtures and parity corpus | Frontend, IR, lifecycle, SSA, optimizer, native, tooling, capability, release, and UI regression coverage. | Direct: milestone-local positive/negative tests plus integrated parity/ownership/fuzz/stress evidence; replace/reclassify legacy exception tests. | `tests/aether/test_exceptions.py` certifies obsolete AST-only semantics. | M1–M12 |
| Rust tests | `compiler-rs/crates/aether-ir/tests/`, `aether-verifier/tests/`, `aether-ir-verifier/tests/fixtures/` | Wire/importer completeness and structural/type/borrow/lifecycle/dominance/SSA authority. | Direct shared exception fixtures and negative mutations. | No exception fixtures. | M3–M5, M11 |
| Editor tests | `vscode-extension/test/`, `tools/intellij-aether/src/test/`, `tests/test_qt_*`, `tests/test_aether_lsp_*`, `tests/test_editor_api.py` | Manifest/CLI/LSP/highlighting/completion/editor behavior. | Direct cross-tool syntax, diagnostics, completion, formatting, and regeneration coverage. | Partial hard-coded legacy keyword/type coverage. | M1, M10 |

## Experimental-support findings summary

| Finding | Classification | Migration note |
| --- | --- | --- |
| `try`, `catch`, `throw` token kinds and reserved keywords | Reusable infrastructure / migration input | Keep spellings and locations; replace grammar behavior in M1. |
| `Exception` as a built-in `TYPE` and runtime value | Obsolete experimental behavior | Replace with built-in `Error` interface through ordinary conformance in M2; do not alias semantics silently. |
| Single `TryCatchStatement` and expression-only `ThrowStatement` | Obsolete experimental behavior | Replace with ordered catch clauses and distinct bare rethrow in M1. |
| Typechecker string/`Exception` throw rule and universal `Exception` catch binding | Obsolete experimental behavior | Replace with non-null `Error` conformance, exact catch checks, and catch borrow rules in M2. |
| `_ThrownExceptionSignal` in AST interpreter | Migration input | A private host signal may be reusable, but Python exception matching cannot define Aether matching/ownership. |
| `AetherExceptionValue` and string-to-exception conversion | Obsolete experimental behavior | Replace by ordinary struct/class `Error` payloads and an opaque internal event. |
| AST capability marked complete and E2E-tested | Migration input | It describes auxiliary experimental behavior, not stable support. Keep native stable gate unsupported through M12. |
| IR lowerer names exception AST nodes only for unsupported-feature errors | Reusable fail-closed behavior | Replace with real lowering only in M3. |
| Tooling keyword highlighting and legacy completion/snippet/type | Migration input | Preserve keywords; replace legacy `Exception`/untyped catch/string throw guidance in M1/M10. |
| Python/Rust/Kotlin/TypeScript host exceptions for compiler/UI control and error containment | Unrelated host implementation detail | Do not migrate unless the host path specifically transports an Aether event. |
| Native panic helpers and IR `may_trap` | Reusable distinct failure infrastructure | Preserve as uncatchable panic; add separate `may_throw` and event paths. |

The per-feature migration details and responsible milestones are in
[`EXCEPTION_EXPERIMENTAL_SUPPORT_MIGRATION.md`](EXCEPTION_EXPERIMENTAL_SUPPORT_MIGRATION.md).

## Explicit no-change-required findings

Inspection supports the following limited conclusions for the current snapshot:

- No independent persisted AST serialization format exists, so there is no AST
  wire compatibility migration in M1. Structural equality/debug output still
  needs tests.
- Generic lattice and worklist containers in `src/aether/ssa/analysis/` do not
  encode control-flow semantics themselves; consumers, not the containers, need
  exception handling.
- `compiler-rs/crates/aether-python` is currently an empty integration shell and
  needs no exception code unless activated as a schema/runtime bridge.
- No public Aether FFI, raw-C imports/exports, callback adapter, or stable public
  ABI is implemented. M9 must add containment when such paths are introduced;
  there is nothing to migrate in M0.
- The web editor's CodeMirror bundle entry contains no Aether grammar. It need not
  be regenerated solely for compiler keyword changes; shared LSP/completion/editor
  behavior still requires M10 validation.
- Existing host-language `try`/`except`/`catch`, Rust `Result<_, Error>`, verifier
  error enums, and compiler diagnostic exceptions do not implement Aether
  exceptions and require no semantic migration.
- No copy propagation, ARC optimization, inlining, LICM, GVN, or bounds-check
  elimination pass exists in either optimizer tree. Exception implementation does
  not require creating those passes, but any later pass must remain disabled for
  exception-bearing IR until audited.

## Cross-language and schema parity obligations

1. Define one versioned Initial IR contract before adding exception tags.
2. Update Python model/DTO/strict JSON, Rust wire DTO/owned IR/importer, both
   verifier stacks, protocol diagnostic mappings, and shared fixtures atomically
   or behind a fail-closed version boundary.
3. Preserve exact field/order/edge/event meaning; neither importer may synthesize
   a missing exceptional successor or infer ownership.
4. Run DTO registry completeness, Rust instruction-variant completeness,
   Python/Rust accepted/rejected corpus parity, shadow, canary, and packaged
   executable tests.
5. Treat verifier disagreement as a release blocker, not as an allowed divergence.

## Editor and tooling obligations

1. Compiler parser/typechecker remain semantic authority; tooling must not create
   a second catch-matching or checked-effect model.
2. Update the CLI formatter, LSP, language-service completion, document symbols,
   Qt highlighter/completion, VS Code TextMate grammar, and IntelliJ token/highlight
   support from the same syntax checklist.
3. Represent legal bare rethrow contextually and never suggest `throws` clauses.
4. Keep diagnostic codes, ranges, catch binder types, and recovery behavior
   consistent across CLI and LSP.
5. Regenerate checked-in VS Code `out/` or web vendor assets only through their
   documented build commands when their sources actually change.

## Capability and release obligations

1. `ERROR_HANDLING` remains `UNSUPPORTED` in the sole stable Aether 1.0 native
   profile through Milestone 11.
2. The AST profile's experimental `COMPLETE` state is not stable language
   promotion and cannot be used as end-to-end evidence for the approved model.
3. Every intermediate route remains fail-closed before unsupported IR lowering;
   there is no fallback from native to AST.
4. M12 promotion must update the catalog/profile, generated native profile,
   capability tests, examples classification, specification, diagnostics, release
   notes, CI matrices, and all shipped editors together.
5. Promotion requires approved SSA/backend/runtime ADRs and zero unresolved
   correctness, ownership, verifier, parity, or C-boundary-containment defects.
