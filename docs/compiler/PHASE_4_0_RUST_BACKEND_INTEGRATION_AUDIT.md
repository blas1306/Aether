# Phase 4.0 — Rust Backend Integration Audit and Execution Plan

Date: 2026-07-21  
Repository revision audited: `53d3946` (`rust-verifier-v1`)  
Status: audit complete; production remains Python-authoritative

## Executive decision

The smallest safe integration point is `IRBackend.verify()` in
`src/aether/pipeline.py`. Every production path that consumes verified Initial
IR already crosses that method, directly or through `SSAPipeline`, with one
intentional exception: `--emit-cfg` lowers unverified IR for inspection.

Use a subprocess adapter first and the existing canonical schema-v1 JSON as the
only process boundary. This is the shortest route to Python-only, Rust-only,
and Python-authoritative shadow modes, and it isolates Rust process failures.
It is not the preferred permanent boundary: once semantic and packaging gates
are satisfied, replace the process client with a PyO3 client behind the same
Python interface. The mode coordinator, normalized result, mismatch records,
and compiler call sites must not depend on which Rust transport is active.

Do not switch the default in this phase. The default remains `python`. Do not
silently fall back from explicit `rust` mode. Shadow mode always returns or
raises according to Python and records Rust differences out of band.

The smallest safe next implementation phase is **4.1, Combined Rust verifier
API and diagnostic normalization**. The individual Rust passes are complete,
but there is no public combined entry point, no aggregate error type, and no
complete invariant-ID adapter. Building a process or PyO3 layer before that API
would duplicate policy at the transport boundary.

## 1. Current production pipeline map

### 1.1 Frontend and Initial IR

The installed `aether` command is declared by `pyproject.toml` as
`aether.cli:main`. The source-to-Initial-IR path is:

```text
aether.cli.main
  -> command-specific helper in aether.cli
  -> prepare_typed_program(source, TypeChecker(...))
     -> parse_source
        -> tokenize_source -> lexer.lex
        -> Parser(...).parse
     -> typecheck_program -> TypeChecker.check
     -> build_checked_program
     -> normalize_entry_point
     -> with_root_program
     -> TypedProgram
  -> IRBackend.lower / lower_verified
     -> IRLowerer.lower_checked_program
        -> combine_checked_program
        -> IRLowerer.lower
        -> IRModule (Initial IR)
  -> IRBackend.verify
     -> Python IRVerifier(module).verify
```

Exact owners:

| Stage | File | Entry point |
| --- | --- | --- |
| CLI dispatch | `src/aether/cli.py` | `main` (line 217) |
| Lexer | `src/aether/lexer.py` | `lex` (line 245) |
| Parser wrapper | `src/aether/pipeline.py` | `parse_source` (line 208) |
| Parser | `src/aether/parser.py` | `Parser.parse` (line 22) |
| Frontend orchestration | `src/aether/pipeline.py` | `prepare_typed_program` (line 219) |
| Typechecker | `src/aether/typechecker.py` | `TypeChecker.check` (line 135) |
| Checked multi-module graph | `src/aether/modules.py` | `build_checked_program` (line 158) |
| Multi-module combination | `src/aether/ir/module_lowering.py` | `combine_checked_program` (line 37) |
| Initial IR lowering | `src/aether/ir/lowering.py` | `IRLowerer.lower_checked_program` (line 291), `lower` (line 302) |
| Python Initial IR verifier | `src/aether/ir/verifier.py` | `IRVerifier.verify` (line 185) |
| Compiler verification boundary | `src/aether/pipeline.py` | `IRBackend.verify` (line 99), `lower_verified` (line 110) |

`prepare_typed_program` typechecks imports and materializes a `CheckedProgram`
before entry-point normalization. Initial IR lowering consumes that checked
multi-module unit and combines modules; the Rust verifier must therefore accept
the resulting complete `IRModule`, not source files or AST objects.

### 1.2 Optimization, SSA, LLVM, and native execution

The real default command is native LLVM execution, not the AST interpreter:

```text
cli.main
  -> _execute_file(backend="llvm")
  -> _run_native
  -> prepare_typed_program
  -> LLVMRunner.run
  -> LLVMBuilder.build
  -> LLVMBuilder.emit_llvm
     -> validate_backend_capabilities(NATIVE)
     -> lower_to_verified_ssa
        -> SSAPipeline.run
        -> IRBackend.lower_verified
           -> IRLowerer.lower_checked_program
           -> IRBackend.verify -> Python IRVerifier
        -> GeneralSSABuilder.build
           -> expand_lifecycle
           -> CFG/dominators/frontier/phi placement/renaming
           -> SSAVerifier
        -> SSAPipeline.verify -> SSAVerifier
     -> SSAOptimizerPipeline(verify_after_each=True)
     -> LLVMBackend.emit -> LLVMPrinter.print_module
  -> clang
  -> temporary native executable
```

Relevant middle-end and backend entry points:

| Area | File | Entry point and relationship |
| --- | --- | --- |
| Initial IR optimization | `src/aether/ir/optimizer/pipeline.py` | `OptimizerPipeline.run`; used by `IRBackend.optimize_verified` after `expand_lifecycle`, then Python IR verification runs again |
| Initial lifecycle expansion | `src/aether/ir/lifecycle.py` | `expand_lifecycle`; used before Initial IR optimization and inside the general SSA builder |
| SSA pipeline | `src/aether/pipeline.py` | `SSAPipeline.run` (line 193), `lower_to_verified_ssa` (line 232) |
| Default SSA lowering | `src/aether/ssa/general_builder.py` | `GeneralSSABuilder.build`/`build_module` (lines 29–38) |
| Compatibility SSA lowering | `src/aether/ssa/builder.py` | `SSABuilder.build` (line 212), selected only with `builder="pattern"` |
| SSA verification | `src/aether/ssa/verifier.py` | `SSAVerifier.verify` |
| SSA optimization | `src/aether/ssa/optimizer/pipeline.py` | `SSAOptimizerPipeline.run`; verifies input and, by default, every pass result |
| LLVM facade | `src/aether/backend/llvm/backend.py` | `LLVMBackend.emit` |
| LLVM/native preparation | `src/aether/backend/llvm/build.py` | `LLVMBuilder.emit_llvm` (line 58), `build` (line 97) |
| Native execution | `src/aether/backend/llvm/run.py` | `LLVMRunner.run` (line 23) |

The Rust work in this audit concerns only Initial IR. Owned SSA/Phi verification
remains outside this boundary. Existing Python SSA verification and LLVM
behavior must not be selected by `--ir-verifier`.

### 1.3 CLI routes and current controls

`src/aether/cli.py` owns three argparse parsers: `build_parser`,
`build_bench_parser`, and `build_native_parser`.

| Route/control | Current path through Initial IR verification |
| --- | --- |
| `aether file.ae` / `aether run file.ae` | Default `--backend=llvm`; Python Initial IR verifier, SSA, LLVM, clang, run |
| `--backend=llvm` | Same as default |
| `--backend=ir` | `IRBackend.run` -> lower and Python-verify -> IR interpreter |
| `--backend=ast` | AST interpreter only; no Initial IR |
| `--emit-ir` | Lower and Python-verify; `--opt`/`-O1`/`-O2` also expand, optimize, and verify the result |
| `--emit-cfg` | Lowers with `IRBackend.lower` and deliberately does **not** verify |
| `--emit-ssa` | Python-verified Initial IR -> selected SSA builder -> Python SSA verifier |
| `--emit-llvm` | Python-verified Initial IR -> default SSA -> SSA optimizer -> LLVM text |
| `--check` | Parse, typecheck, native capability check only; no Initial IR |
| `aether build` | Same compiler path as LLVM emission, then clang |
| `aether bench` | Backend-dependent development timings; IR/SSA/LLVM/native profiles cross Python Initial IR verification |
| `--ssa-builder={general,pattern}` | Only controls `--emit-ssa`; unrelated to Initial IR verifier selection |
| `--opt`, `-O0/1/2`, `--show-passes` | Only Initial IR inspection optimization controls; no verifier implementation selector exists |

The REPL and `run_aether`/`AetherSession` use `execute_pipeline` and the AST
backend, so they do not currently generate Initial IR. LSP diagnostics use
`analyze_source`; they also do not reach Initial IR. They should not grow an
independent verifier selector.

## 2. Existing integration inventory

| Capability | Status | Evidence |
| --- | --- | --- |
| Canonical Python DTO generation | **Implemented** | `src/aether/ir/dto.py`: complete schema-v1 encoders/decoders, `ir_module_to_dto`, registry completeness checks |
| Canonical JSON serialization | **Implemented** | `ir_module_to_json`/`ir_module_from_json`; UTF-8, sorted keys, two-space indentation, finite numbers, duplicate-key rejection, trailing newline |
| Rust wire DTO | **Implemented** | `compiler-rs/crates/aether-ir/src/wire.rs`, Serde schema-v1 types |
| Rust owned IR import | **Implemented** | `aether-ir::import_module` in `importer.rs` |
| Strict Rust JSON import | **Implemented** | `aether-ir::import_module_json` in `json.rs`; separates JSON, wire, schema-version, and owned-import errors |
| Rust verifier passes | **Implemented individually** | `verify_module_structure`, `verify_module_types`, `verify_module_ssa`, `verify_module_dominance`, `verify_module_lifecycle`, `verify_module_returns` |
| Combined Rust verifier | **Absent** | `aether-verifier/src/lib.rs` exports only independent pass entry points |
| Typed Rust diagnostics | **Implemented per pass** | Pass-specific typed wrappers retain module/function/block/instruction context and `Error::source` chains |
| Stable invariant ID on every Rust failure | **Partial** | IDs are explicit for borrow rules and IRV-026, but most typed variants need an adapter mapping to `IRV-NNN` |
| Rust diagnostic serialization | **Absent** | Errors implement `Display`/`Error`, not Serde; no external result schema exists |
| Python normalized verifier result | **Implemented, Python-only** | `src/aether/ir/verification_result.py`: accepted/rejected, invariant ID, category, severity, locations |
| Message/context in Python normalized result | **Partial** | The normalized Python type does not carry deterministic message or IR function/block/instruction context |
| Rust executable invocation | **Absent** | No Rust binary target and no Python Rust-verifier subprocess client |
| PyO3 integration | **Documentation-only placeholder** | `aether-python` is a four-line crate with no dependencies; no `pyo3`, exported module, or build backend |
| C ABI/other FFI | **Absent** | No headers, exported ABI, unsafe boundary, loader, or packaging evidence |
| Differential corpus | **Implemented as test index** | `tests/aether/rust_migration/manifest.yaml`: 130 cases (64 valid, 66 invalid) |
| Corpus materializer | **Partial/test-only** | `benchmarks/ir_verifier.py` intercepts selected Python `IRVerifier.verify` calls |
| Rust differential consumer | **Absent** | The materializer benchmarks only Python and never serializes/invokes Rust |
| Shadow coordinator/result adapter | **Absent** | No product or test harness runs both verifier implementations |
| Rust packaging | **Absent** | Python wheel is `py3-none-any`; sdist manifest does not include `compiler-rs` |
| Rust CI | **Absent** | `scripts/ci.py` has no Cargo stage; the only hosted workflow is for the VS Code extension |

The migration corpus is strong semantic evidence, but it is not yet a
transport corpus. Two invalid entries deliberately construct Python object
states that the canonical DTO rejects before serialization:

- `lifecycle-non-storage-destination`: puts `IRValue` where schema v1 requires
  exact `IRStorage`;
- `integer-constant-out-of-range`: puts an integer outside the schema's signed
  32-bit constant domain.

Those tests remain valid Python-verifier unit tests. The real adapter corpus
needs equivalent schema-boundary expectations or post-JSON mutations; it must
not weaken the canonical DTO to transport impossible owned-IR states.

## 3. Integration option comparison

| Property | A. Subprocess + canonical JSON | B. PyO3 extension | C. C ABI/other FFI |
| --- | --- | --- | --- |
| Repository readiness | High at data boundary; JSON importer exists. Binary/protocol absent. | Low-to-medium; placeholder crate and roadmap exist, bindings/build absent. | None; no supporting code or build policy. |
| Implementation complexity | Low-to-medium | Medium-to-high | High |
| Build complexity | Add one binary crate/target and build it before shadow tests; later package one binary per platform | Add PyO3 and mixed Python/Rust build backend; build ABI/platform wheels and editable installs | Add stable ABI, allocation/string ownership rules, dynamic loading, headers, and platform linker work |
| Per-call startup | Measured about 1.07 ms on the audit host | No process startup | No process startup |
| Serialization | Existing canonical DTO + JSON required | Initially keep canonical JSON to avoid a second object mapping; direct conversion can be evaluated later | Requires a new buffer/ABI representation or still uses JSON |
| Diagnostic fidelity | Exact if response protocol carries structured fields | Exact; native Python values/exceptions are convenient | Possible, but manual ABI structs and memory ownership add risk |
| Crash isolation | Best: panic/abort/signal is confined to child process | Lower: panic must be caught; abort terminates Python | Lower and more failure-prone at the boundary |
| Platform support | Normal executable per target; discovery and executable permissions need tests | Normal CPython/platform extension wheel matrix | Most linker/loader variation and weakest repository evidence |
| Packaging impact | Current pure wheel becomes platform-specific or gains a platform helper artifact; release script currently forbids binaries | Current pure wheel becomes CPython/platform-specific; release script currently forbids `.so`/`.dll`/`.dylib` | Same platform-wheel issue plus ABI distribution |
| Testability | Excellent black-box protocol, crash, timeout, malformed-output tests | Excellent API tests, but real crashes are harder to contain | Expensive integration testing |
| Long-term suitability | Good as a debug/fallback transport; repeated process startup is unnecessary in steady state | Best fit for regular compiler calls once packaging is reliable | Not justified |

### Recommendation

- **Short term:** Option A, subprocess. It reuses the completed interchange
  format, maximizes crash isolation during shadowing, and does not force the
  Python packaging backend to change before semantic integration is proven.
- **Long term:** Option B, PyO3, behind the same Python `RustVerifierClient`
  protocol. Start by accepting canonical JSON; optimize away JSON only after a
  measured reason and a separate design review.
- **They should not be the same transport.** The short-term goal is safe
  observation. The long-term goal is a low-overhead installed compiler. Keeping
  transport behind one interface makes replacement local.
- **Do not pursue Option C.** The workspace forbids unsafe code, and no current
  repository evidence compensates for the extra ABI and ownership surface.

## 4. Recommended architecture

### 4.1 Rust library API

Add an aggregate API to `aether-verifier`, conceptually:

```rust
pub fn verify_module(module: &IRModule) -> Result<(), IRVerificationError>;

pub enum IRVerificationError {
    Structure(ModuleStructureVerificationError),
    Types(ModuleTypeVerificationError),
    Ssa(ModuleSSAError),
    Dominance(ModuleDominanceError),
    Lifecycle(ModuleLifecycleVerificationError),
    Returns(ModuleReturnVerificationError),
}
```

The exact type may use boxed variants if size warrants it. It must:

- run passes in one documented deterministic order;
- expose `phase()`, `invariant_id()`, and structured context accessors;
- keep deterministic `Display` output;
- implement `Error::source()` so Rust tests can downcast through the original
  typed chain;
- return only program-verification failures, never import/protocol failures;
- return the borrowed module unchanged only at a Python convenience layer, not
  as the Rust semantic result.

The provisional pass order is structure, types, SSA, dominance, lifecycle,
returns. Before freezing it, multi-invalid fixtures must compare this order with
Python's interleaved per-function order. Single-invariant corpus parity is not
enough to claim identical first-failure behavior.

Add a separate normalization adapter rather than redesigning every existing
error:

```text
RustVerificationFailure
  phase
  invariant_id (optional only until every typed variant is mapped)
  module context
  function name/index (optional)
  block name/index (optional)
  instruction kind/index (optional)
  deterministic message
```

All known Initial IR semantic variants should have an invariant ID before Rust
mode is exposed. `None` is acceptable only for a newly discovered internal
classification gap and must fail a normalization unit test, not silently enter
shadow comparison.

### 4.2 External subprocess protocol

Add a small binary that depends on `aether-ir` and `aether-verifier`:

```text
stdin:  one UTF-8 canonical IRModule schema-v1 JSON document
stdout: one UTF-8 verifier-response JSON document
stderr: captured implementation detail; never normal product output
```

The response needs independent version fields:

```json
{
  "protocol_version": 1,
  "ir_schema_version": 1,
  "status": "accepted"
}
```

or:

```json
{
  "protocol_version": 1,
  "ir_schema_version": 1,
  "status": "rejected",
  "failure": {
    "phase": "lifecycle",
    "invariant_id": "IRV-048",
    "function": "main",
    "block": "entry",
    "instruction_index": 4,
    "instruction_kind": "IRDestroy",
    "message": "..."
  }
}
```

Exit code zero means a valid request produced either semantic outcome. A
nonzero exit is an integration failure: malformed request, schema mismatch,
panic/internal error, or protocol failure. Wrap the top-level verifier call in
`catch_unwind` for unwind builds; Python must still recognize abrupt exit or
signal as an integration failure.

The Python subprocess client must use argument arrays, `stdin`, captured output,
no shell, a finite timeout, a bounded response, and exact response field
validation. A 30-second default timeout is conservative for the initial
developer integration; record elapsed time so it can be revised from evidence.

Do not invoke Cargo from the compiler at runtime. CI and a session-scoped test
fixture build the helper once. Installed Rust/shadow mode discovers a helper
shipped with the same package version; a developer-only explicit path override
is allowed. Normal Python-only tests require no Rust build.

### 4.3 Python coordinator

Add a transport-neutral module such as `src/aether/ir/verifier_backend.py` with:

```text
IRVerifierMode = python | rust | shadow
VerifierOutcome = Accepted | Rejected(VerifierFailure)
RustVerifierClient.verify_json(json) -> VerifierOutcome
VerifierMismatchRecord
IRVerificationCoordinator.verify(module, stage) -> module or raises
```

Inject the coordinator into `IRBackend`; keep `IRBackend()` equivalent to the
current Python implementation. Propagate the same configuration through
`SSAPipeline`, `lower_to_verified_ssa`, `LLVMBuilder`, `LLVMRunner`, CLI helpers,
and benchmark profiles. Do not add independent selection logic to LLVM, SSA,
LSP, or the Rust transport.

The coordinator owns exactly one canonical serialization per Rust invocation.
It also tags the boundary (`initial` or `post_optimization`) because
`IRBackend.optimize_verified` verifies expanded/optimized Initial IR a second
time.

### 4.4 Shadow semantics

Python remains authoritative in every shadow branch:

| Python | Rust | Product result | Record |
| --- | --- | --- | --- |
| Accept | Accept | Continue | Optional matched counter only |
| Reject | Reject | Raise the original Python diagnostic | Record only if normalized failures differ |
| Accept | Reject | Continue | `python_accept_rust_reject` mismatch |
| Reject | Accept | Raise the original Python diagnostic | `python_reject_rust_accept` mismatch |
| Accept or reject | Integration failure | Preserve the Python result | `rust_integration_failure` |

The coordinator must capture the Python outcome before raising, run Rust
independently, record comparison, then reproduce the current Python return or
exception. It must never turn shadow into implicit fallback semantics.

`VerifierMismatchRecord` should include:

- record/protocol/IR schema versions;
- boundary stage and mode;
- stable SHA-256 of canonical JSON, not an unconditional full IR dump;
- Python and Rust normalized outcomes;
- classification and whether it matches a reviewed expected discrepancy;
- Rust process exit/timeout/protocol summary for integration failures;
- optional reproduction path only in explicit CI/debug collection.

Normal users get no warning or stderr output for shadow matches or mismatches.
The default sink is a null sink. Development may use Python logging at debug
level. CI uses an in-memory or JSONL collector and fails the dedicated shadow
job if unexpected records remain. Strictness belongs to that CI assertion, not
to production control flow, so a Python rejection keeps its current diagnostic.

The intentional IRV-024 label-insensitivity improvement must be an exact,
reviewed expected-discrepancy entry tied to the characterization fixture and
invariant. Do not suppress all IRV-024 differences.

### 4.5 Configuration

Use one explicit selector on every CLI parser that reaches Initial IR:

```text
--ir-verifier=python|rust|shadow
```

Default: `python`.

Add it to the main parser, `aether build`, and `aether bench`. It is valid for
IR/SSA/LLVM/native paths and rejected as irrelevant with AST-only, REPL,
`--tokens`, `--ast`, and `--check` if explicitly non-Python. Preserve the
current `--emit-cfg` behavior; either reject Rust/shadow there or document that
the route does not verify. Rejecting is clearer.

For CI and non-CLI integration tests, support `AETHER_IR_VERIFIER` with the same
three values, with explicit API/CLI configuration taking precedence. An unset
environment always means Python. Keep these transport settings separate:

- `AETHER_RUST_VERIFIER_PATH`: developer/test override only;
- `AETHER_RUST_VERIFIER_TIMEOUT_SECONDS`: bounded developer/CI tuning;
- no product-facing strict flag initially; the dedicated CI collector is the
  strict gate.

Configuration parsing must happen once. Libraries receive an immutable config;
they do not reread environment variables at every verification.

## 5. Failure handling contract

Separate semantic rejection from infrastructure failure in both types and
wire status.

| Condition | Classification | Python mode | Rust mode | Shadow mode |
| --- | --- | --- | --- | --- |
| Python/Rust verifier rejects IR | Program verification failure; in the accepted-source compiler pipeline this is an ICE | Preserve current `IRVerificationError` chain | Raise a compatibility `IRVerificationError` carrying Rust structured failure so public code remains `ICE-IR-VERIFY-001` | Python decides; record mismatch if outcomes/failures differ |
| Python DTO encoder rejects module | Integration boundary failure | Not applicable | Rust integration ICE; no fallback | Record; preserve Python outcome |
| Invalid JSON / invalid wire shape | Integration boundary failure | Not applicable | Rust integration ICE | Record; preserve Python outcome |
| Rust owned import failure | Integration boundary failure | Not applicable | Rust integration ICE | Record; preserve Python outcome |
| Schema/protocol version mismatch | Compatibility failure | Not applicable | Rust integration ICE with both versions in debug data | Record; preserve Python outcome |
| Helper missing/not executable | Packaging/discovery failure | Not applicable | Rust integration ICE; do not label it as missing clang | Record; preserve Python outcome |
| Timeout | Infrastructure failure | Not applicable | Terminate helper and raise Rust integration ICE | Terminate helper, record, preserve Python outcome |
| Rust panic/abort/signal | Internal Rust integration failure | Not applicable | Rust integration ICE | Record, preserve Python outcome |
| Malformed/trailing/oversized stdout | Protocol failure | Not applicable | Rust integration ICE | Record, preserve Python outcome |

Add a distinct internal diagnostic such as `ICE-IR-RUST-001` for integration
failures. It must remain exit code 70 and hide stderr/raw IR unless `--debug` is
active. Semantic Rust rejection should retain the established
`ICE-IR-VERIFY-001` public behavior.

## 6. Required implementation phases

### 4.1 Combined Rust verifier API

- Add aggregate `verify_module` and `IRVerificationError`.
- Freeze pass order and test multi-invalid first-failure determinism.
- Add phase, invariant-ID, and context normalization for every typed failure.
- Preserve every existing source chain and independent pass API.
- No Python or compiler behavior changes.

Exit gate: all Rust tests pass; every semantic error variant is normalized; the
intentional IRV-024 difference has an explicit test.

### 4.2 External adapter and protocol

- Add the helper binary and versioned JSON response DTO.
- Compose strict JSON import with combined verification.
- Add malformed JSON, invalid DTO, import, schema, panic, and deterministic
  response tests.
- Add release-size and cold/warm process timing probes.

Exit gate: a Python test can send the checked-in golden JSON and distinguish
accept, reject, and integration failure without importing product pipeline code.

### 4.3 Python integration boundary

- Add immutable config, coordinator, normalized Rust result, client protocol,
  subprocess client, and integration-error hierarchy.
- Inject it at `IRBackend.verify` and propagate through SSA/LLVM/native callers.
- Keep constructor and function defaults Python-compatible.
- Keep `--emit-cfg`, AST, REPL, and LSP behavior unchanged.

Exit gate: direct unit/integration tests can select all three modes through an
injected fake client; default tests observe no changed call or diagnostic.

### 4.4 Shadow mode

- Add mismatch records and pluggable null/debug/collecting sinks.
- Compare acceptance first, then normalized invariant/context.
- Preserve the exact original Python exception object on rejection.
- Add reviewed expected-discrepancy matching for the single IRV-024 case.

Exit gate: every truth-table branch and Rust-unavailable branch is tested, and
normal CLI stdout/stderr is byte-for-byte unchanged.

### 4.5 CLI/config selection

- Add `--ir-verifier` to the main, build, and benchmark parsers.
- Add environment parsing once at the outer boundary.
- Validate irrelevant route combinations.
- Default to Python in all APIs and commands.

Exit gate: CLI contract tests cover default, explicit modes, invalid values,
subcommands, and program-argument splitting.

### 4.6 Corpus, CI, and packaging

- Convert the current collector into a reusable materializer or checked-in DTO
  snapshot generator with provenance.
- Classify the two non-serializable negative cases as schema-boundary tests.
- Run all 128 transportable cases through the real adapter and assert the one
  exact expected IRV-024 difference.
- Add Cargo fmt, clippy, check, and test stages to `scripts/ci.py` and hosted CI.
- Build the helper once before shadow tests; never once per pytest case.
- Include `compiler-rs` in sdist and ship/locate a version-matched helper in
  platform wheels. Update archive allowlists, clean-install, uninstall, and
  offline tests.

Exit gate: clean Linux x86_64 wheel install runs Python, Rust, and strict shadow
smokes; artifact discovery never depends on a checkout or manual Cargo command.

### 4.7 Rust verifier opt-in

- Document Rust mode as experimental.
- Run real valid/invalid compiler E2E tests, not only hand-built IR.
- Collect duration and failure telemetry only in opt-in CI/development sinks.
- Keep Python default and provide a central rollback to Python.

Exit gate: no unexpected corpus mismatch, no packaging failures, deterministic
diagnostics, and no downstream SSA/LLVM/native behavioral difference.

### 4.8 PyO3 transport and eventual default

- Implement `aether-python` as a PyO3 client of the same combined Rust API.
- Initially accept canonical JSON and return the same normalized response shape.
- Build a CPython/platform wheel matrix and clean editable installs.
- Compare in-process and subprocess results before retiring process transport
  from normal use.
- Change the default only in a separate reviewed release after all supported
  platforms pass and rollback is rehearsed.

Python verifier removal is not part of Phase 4.0. It remains the shadow oracle
through the default transition.

## 7. Testing plan

### Rust unit tests

- combined pass success and each phase failure;
- stable pass/first-failure order, including two invalidities in different
  functions;
- invariant mapping for every error leaf and instruction-dependent rule;
- module/function/block/instruction context extraction;
- deterministic message and repeated result;
- `Error::source` downcasts to original typed leaves;
- response serialization and protocol/schema handshake.

### Python unit and integration tests

- config precedence and default `python`;
- Python mode never constructs or calls a Rust client;
- Rust accept/reject and integration-error mapping;
- all five shadow truth-table branches;
- Python rejection preserves the original exception/diagnostic;
- null sink is silent; collector captures stable records;
- helper missing, permission denied, timeout, signal, nonzero exit, invalid UTF-8,
  invalid/trailing/oversized JSON response;
- `IRBackend.verify` at initial and post-optimization stages;
- CLI main/build/bench propagation and irrelevant-mode rejection.

### Corpus tests

- all 64 valid transportable cases accepted by both;
- 64 transportable invalid cases, with the reviewed IRV-024 difference exact;
- two unencodable cases asserted as DTO/schema-boundary failures;
- strict JSON duplicate keys, invalid numbers, unknown fields, invalid schema;
- deterministic response bytes/outcome over repeated runs;
- no broad allowlist for IRV-024.

### End-to-end tests

- compile representative valid Aether source under Python, Rust, and shadow;
- reject a deliberately injected invalid Initial IR under each mode;
- run `--emit-ir`, `--emit-ssa`, `--emit-llvm`, default run, and `build`;
- compare SSA text, LLVM text, executable stdout/stderr/exit code, and retained
  native behavior across verifier selections;
- clean-wheel artifact discovery and version mismatch;
- confirm AST, REPL, LSP, `--check`, and `--emit-cfg` do not change.

## 8. Performance observations

These are local engineering measurements, not a benchmark guarantee. Host:
CPython 3.14.4, Linux x86_64, AMD Ryzen 5 7535HS, 12 logical CPUs; Rust release
profile uses the pinned 1.85.1 toolchain.

### Python baseline

The existing `benchmarks/ir_verifier.py --rounds 10 --warmup 1` materialized all
130 cases and reported:

- 64 accepted, 66 rejected;
- 72.200 microseconds per Python verification;
- median full-corpus round 9.324 ms.

### DTO and JSON

For the 128 serializable corpus modules, 50 local rounds reported:

| Operation | Median per module |
| --- | ---: |
| Python `ir_module_to_dto` | 24.293 us |
| Canonical `json.dumps` from a prepared DTO | 26.046 us |
| Full `ir_module_to_json` | 52.360 us |

Payload sizes total 678,610 bytes: minimum 259, median 2,400, mean 5,301.6,
maximum 31,836 bytes.

### Rust import, verification, and process

A temporary release-mode audit helper composed the six current passes in the
provisional order and was removed after measurement. Across 100 rounds of the
128 serializable modules:

- strict Rust JSON import: approximately 32.30 us/module;
- combined fail-fast Rust passes: approximately 6.48 us/module;
- outcome: 65 Rust accepts versus 64 expected Python accepts; the only
  difference was `non-void-path-without-return`, the documented intentional
  IRV-024 improvement;
- empty helper startup median: 1.066 ms;
- startup + import + verification for a median-sized 2,403-byte module: median
  0.977 ms (timer/process noise makes this effectively a roughly 1 ms cost);
- temporary stripped release helper size: about 1.71 MB.

The canonical in-process data path already costs roughly 91 us/module
(DTO+JSON+Rust import+Rust verify), excluding PyO3 or process transport. That is
larger than the 72 us Python verifier baseline, so theoretical Rust speed alone
does not justify the integration. In shadow mode the extra roughly 1 ms process
startup dominates verifier execution. This is acceptable for initial CLI/CI
shadowing and negligible beside clang, but not attractive for repeated
language-service or small incremental calls. It supports subprocess short term
and PyO3 long term.

Do not change canonical JSON formatting merely for these measurements. If
payload cost becomes material, first measure warm persistent-process batching
or PyO3 JSON calls; a second wire format would create more risk than the current
payload sizes justify.

## 9. Packaging and developer workflow

Current state:

- `pyproject.toml` uses `setuptools.build_meta`, package discovery under `src`,
  and produces a `py3-none-any` wheel;
- `MANIFEST.in` does not include `compiler-rs`;
- `scripts/release.py` expects exactly one wheel and one sdist and explicitly
  rejects `.so`, `.dll`, `.dylib`, and `.exe` archive members;
- Rust workspace packages are version `0.0.0`, unpublished, and pin Rust 1.85.1;
- `scripts/ci.py` runs Python/docs/LLVM/native gates but no Cargo commands;
- hosted `.github/workflows` contains only the VS Code extension job;
- declared native release support is Linux x86_64 with clang on `PATH`.

For the subprocess phase, add a deterministic build command that produces the
helper once, then pass its resolved path to the session/test configuration.
Normal `pytest` remains Python-only. A dedicated shadow job builds release (or
an explicitly chosen CI profile) once and reuses it for the entire corpus.

For installed opt-in Rust mode, build platform wheels containing a helper whose
protocol and package versions are validated at startup. Discovery must use
installed package metadata/resources, not `target/release`, current working
directory, or `PATH`. The developer override must never be used implicitly in a
release artifact.

For PyO3, select one mixed-project build authority. The existing migration
roadmap proposes `setuptools-rust` and names maturin as the alternative; run a
small wheel/editable-install prototype before committing. Do not maintain
independent metadata in setuptools and maturin.

Release tests must be updated to permit and require the intended native member,
inspect platform tags, install into a clean environment, check the schema and
protocol handshake, run all verifier modes, and verify uninstall. The sdist
must include the Rust workspace and document the Rust toolchain requirement.

## 10. Risks and blockers

1. **No combined Rust API.** Transport code would otherwise own semantic pass
   policy and duplicate it across subprocess and PyO3.
2. **Incomplete invariant normalization.** Typed Rust errors are rich, but most
   do not directly expose `IRV-NNN`; diagnostic parity cannot be asserted yet.
3. **First-failure ordering.** Six module-wide passes do not automatically match
   Python's interleaved function verification for multi-invalid modules.
4. **Two corpus cases cannot cross schema v1.** They need boundary expectations,
   not schema weakening.
5. **Known IRV-024 difference.** It must be narrowly classified so it does not
   make shadow CI permanently noisy or hide unrelated return regressions.
6. **Packaging is currently pure Python and rejects native files.** Neither
   subprocess nor PyO3 can ship without deliberate release-contract changes.
7. **No Rust CI or hosted compiler CI.** Local success alone is insufficient for
   a default change.
8. **Artifact version skew.** Package version, protocol version, IR schema
   version, and Rust workspace version currently have no runtime handshake.
9. **Subprocess cost.** Approximately 1 ms per verifier call dominates the Rust
   work and compounds when post-optimization verification also runs.
10. **Explicit Rust mode cannot fall back.** Missing/corrupt artifacts must be a
    clear ICE; otherwise an opt-in result is not trustworthy.
11. **Rust panic policy.** `catch_unwind` covers unwind panics but not aborts or
    signals; the Python client must handle abrupt child termination.
12. **Scope creep into SSA.** Owned SSA/Phi remains deferred and must not be
    accidentally selected by the Initial IR option.

## 11. Documentation changes required during implementation

- Update `compiler-rs/README.md` after each completed Phase 4 step; it currently
  correctly states that `aether-python` has no bindings or integration.
- Extend `docs/compiler/BACKEND_RUST_MIGRATION.md` with the final combined API,
  transport protocol, mode lifecycle, and promotion evidence.
- Document `--ir-verifier`, environment precedence, helper discovery, and
  experimental support in `README.md` and `docs/guia_de_uso.md` only when the
  flags land.
- Add protocol and schema compatibility policy to compiler docs.
- Update `docs/compiler/CI.md` with Cargo and strict-shadow stages.
- Update release notes, release contract, supported artifact matrix, and sdist
  toolchain instructions before distributing Rust mode.
- Record the exact IRV-024 expected discrepancy beside the differential corpus.

## 12. Final recommendation

Implement Phase 4.1 next and nothing broader in the same change. It is small,
fully Rust-local, leaves production behavior untouched, and creates the one
semantic API both transports need. Then add a subprocess protocol and test it
against the real corpus before modifying `IRBackend` or argparse.

The promotion sequence is:

```text
combined Rust API
  -> versioned subprocess adapter
  -> injected Python coordinator
  -> silent Python-authoritative shadow
  -> CLI/config and strict shadow CI
  -> packaged Rust opt-in
  -> PyO3 transport
  -> separately reviewed Rust default
```

At no point should shadow change the product decision, explicit Rust mode fall
back silently, or the Rust Initial IR selector alter SSA/LLVM semantics.

## 13. Audit validation

The following checks passed on the audited revision with only this report and
its documentation index entry left in the worktree:

```text
cargo check --workspace
cargo test --workspace
cargo fmt --all --check
cargo clippy --workspace --all-targets --all-features -- -D warnings
```

Relevant Python pipeline, DTO, verifier, CLI, and LLVM integration selection:

```text
988 passed in 9.68s
```

The migration-corpus materialization used by the performance audit also passed
all 123 selected owning tests and captured all 130 indexed verifier calls. The
Python verifier baseline then checked the complete corpus for 10 measured
rounds without outcome drift.

`git diff --check` passed. The temporary Rust measurement helper was deleted;
no compiler implementation, mode flag, default, generated artifact, or commit
was added by this audit.
