# Exception Release Qualification v2

> Classification: independent audit. Date: 2026-08-08.
> Tested revision: `d7b959559d37c294afe7dda3246489622c6c0c71` plus the
> qualification-only corpus and lockfile corrections listed below.

## Decision

# DO NOT PROMOTE

The implementation evidence rebuilt by this audit is clean, but the release
decision cannot be `PROMOTE`: the complete Python suite did not finish and the
current VS Code and IntelliJ clients could not be executed in this environment.
Those missing current results leave the requested full-suite and supported-tooling
claims incomplete. `ERROR_HANDLING` remains `UNSUPPORTED`; this audit makes no
capability/profile or exception-semantics change.

## ERQ revalidation

| ERQ | Original defect | Implemented resolution | Current regression/gate | Current result | Status |
| --- | --- | --- | --- | --- | --- |
| ERQ-001 | `Error.message()` implementations could throw and root reporting modeled a second event. | Transitive nonthrowing check, ordinary root witness call, and backend fail-closed invariant. | `test_exception_semantics.py`, `test_exception_release_qualification.py`, native exception tests. | Focused selection passed; native sanitizer selection 54/54. | CLOSED |
| ERQ-002 | Interface invoke selection and function `may_throw` authority disagreed (IRV-144). | One semantic effect summary is carried through interface slots, IR, SSA and LLVM. | `test_interface_exception_effects.py`, IR/SSA/native suites, Rust type verifier. | Focused tests and Rust workspace passed. | CLOSED |
| ERQ-003 | A spurious exceptional `Error.message()` edge produced a lifecycle join inconsistency. | Canonical nonthrowing slot removes that edge; lifecycle verification remains strict. | Nested rethrow/mutation regressions and lifecycle/native constructor cases. | Focused tests and 54/54 sanitizer-backed native tests passed. | CLOSED |
| ERQ-004 | Merely implementing or carrying `Error` falsely required `ERROR_HANDLING`. | Capability detection records executable exception control/effect semantics only. | Capability qualification tests and `check_capability_consistency.py`. | PASS. | CLOSED |
| ERQ-005 | Tooling advertised stale exception names/forms and lacked catch-binder evidence. | CLI/LSP/highlighters use the frozen `Error` surface and binder contracts. | Focused CLI/LSP/tooling tests; client manifests; Gradle/npm suites. | Exception-focused CLI/LSP tests pass; VS Code/IntelliJ current executions unavailable. | CLOSED, tooling rerun incomplete |
| ERQ-006 | No public, reproducible cross-stage promotion corpus/evidence. | Packaged 11-positive/9-negative corpus and deterministic differential/sanitizer gate. | `scripts/check_exception_promotion.py`. | Initially regressed on obsolete `void()` syntax; corrected to `Function<(), void>`, then PASS: 77 comparisons. | CLOSED after qualification correction |
| ERQ-007 | Artifacts did not prove exhaustive examples/corpus contents and clean installation. | Manifest-driven wheel/sdist checks, rebuild-from-sdist and isolated smoke installs. | `scripts/release.py` verification. | PASS on fresh artifacts under `/tmp/aether-erq-v2-dist`. | CLOSED |

No closed ERQ implementation defect was reproduced after correcting the stale
public corpus source. The committed ERQ-006 JSON was not accepted as evidence
until the gate itself ran successfully.

## Semantic, frontend and panic audit

PASS for the tested surface. Focused semantic/release tests and the positive and
negative public corpus revalidated throwable `Error` conformance, nonthrowing
`message()`, rejection of null/non-Error throws, exact nominal ordered catches,
root `catch(Error)`, binder scope/immutability/borrow rules, legal and illegal
rethrow, provenance preservation, sibling-handler exclusion, nested control,
constructors, methods, recursion, direct/indirect/interface calls, and mixed
throwing/nonthrowing implementations. `finally` remains unsupported. Panic is
still fail-fast and uncatchable; exception execution does not absorb bounds,
division, overflow, allocation, or invariant panics.

Malformed throw/catch forms and native-boundary forms remain rejected. No new
language semantics were added.

## Initial IR, lifecycle and SSA audit

PASS for the qualified cases. The focused IR, lifecycle, SSA, backend and release
selection passed apart from sandbox-induced LeakSanitizer failures; the identical
native suite passed 54/54 outside ptrace. Tests cover IRV-149 event linearity,
normal/exceptional invoke successors, direct/indirect/interface effects, exact
dispatch, borrow/destroy/throw/rethrow/propagate, serialization and malformed
ownership rejection. They also cover IRV-150 constructor rollback, partial and
nested owned fields, arrays/lists, struct/class receivers, construction inside an
active catch, and mutable state across exceptional edges.

SSA DTO/wire exceptional edges, handler phis, dominance, ownership, invokes and
effect preservation passed in Python-focused tests and the complete Rust
workspace. The ERQ-006 gate compares verified Initial IR and SSA before and after
their optimization pipelines, including constant propagation/folding, DCE and
CFG simplification.

## Backend, runtime, sanitizers and native boundary

PASS on the claimed Linux x86_64 native platform with clang. The stable internal
strategy remains event-out; LLVM EH remains an explicit test-only comparison
strategy. Native tests cover direct, indirect and interface transport,
nonthrowing calls, `Error.message()`, event packing/matching/borrowing/destruction,
propagation, root reporting, malformed private ABI inputs and fail-fast runtime
fault injection. The architecture tests continue to reject hidden TLS/global
exception state and public/raw-C event transport.

Sanitizer result: PASS, 54/54 native exception tests outside the sandbox, plus
the seven sanitizer programs in the ERQ-006 gate. No leak, UAF, double-free or
ownership diagnostic was reported. Runs inside the sandbox are invalid evidence
because LeakSanitizer explicitly aborts under ptrace.

Native-boundary/FFI result: PASS for the implemented boundary. Throwable foreign
calls/callbacks, external `may_throw`, private event transport and malformed
descriptor/witness/runtime ABI forms remain rejected; no FFI support was added.

## Differential and capability evidence

`scripts/check_exception_promotion.py` passed with 11 positive programs, 9
negative programs and 77 exact comparisons across frontend, Initial IR,
optimized Initial IR, SSA, optimized SSA, and native O0/O1/O2. The first run
found that `positive/indirect_call.ae` still used the superseded `void()` callable
syntax introduced before the canonical `Function<(), void>` spelling. This was
a real release-evidence regression and was repaired before accepting the result.

`check_capability_consistency.py` passed. Ordinary `Error` declarations, values,
arguments, results, containers, nullable values and nonthrowing interface use do
not trigger the capability. Throw/rethrow/try/catch and throwing calls do. The
stable native route still rejects all executable exception programs with
`AE-BACKEND-ERROR_HANDLING`.

## Tooling and packaging

CLI and exception-focused LSP contracts passed. Seven unrelated LSP inlay-hint
tests currently return no hints; they do not affect exception correctness but
are current tooling regressions. Node/npm are unavailable, so the VS Code suite
was not rerun. IntelliJ could not run because the configured Gradle user cache is
read-only; repository CI definitions are corroborating, not a substitute for a
current successful execution. Qt/CodeMirror/MathTeX obligations were not revived.

Fresh wheel and sdist verification passed: canonical 114-example manifest,
public exception corpus and evidence, `LeetCode/isPalindrome.ae`, dependency
metadata, absence of legacy paths, clean wheel installation, `aether` and
`aether-lsp` entry points, wheel rebuilt from sdist, second clean install, and
checksums. Artifacts were written outside the repository to
`/tmp/aether-erq-v2-dist`. The release helper printed PASS and then raised only
because its final display assumes artifacts are below the repository; all build
and verification work had completed.

## Rust verifier and portability

`cargo test --workspace --locked`: PASS, including exception ownership and SSA
wire cases and Python/Rust contract coverage. No observed verifier divergence.

The exact stable native claim is Linux x86_64 only
(`SUPPORTED_NATIVE_PLATFORMS = ("Linux x86_64",)`). That platform was tested.
Windows is explicitly unsupported; macOS and other targets are not claimed.
Portability therefore adds no promotion blocker and no platform claim was
broadened.

## Full-suite and contract results

| Check | Result | Classification |
| --- | --- | --- |
| ERQ-006 promotion gate | PASS: 11 positive, 9 negative, 77 comparisons | Current exception evidence |
| Native exception suite | PASS: 54/54 outside ptrace | Current exception evidence |
| Focused exception/release/tooling selection | 437 passed, with 24 sanitizer failures under ptrace and 7 unrelated LSP inlay-hint failures | Environment limitation plus unrelated current tooling failures; native rerun passed |
| Complete Python suite | Interrupted at 64% after 411.33 s: 2898 passed, 12 failed | Incomplete release evidence |
| Twelve Python failures | `test_import_aliases.py` expects row output while current semantics prints a column | Pre-existing and unrelated to exceptions |
| Rust workspace | PASS | Current verifier evidence |
| Capability, docs, examples, diagnostics | PASS for all four standalone gates | Current release evidence |
| Packaging | PASS on fresh wheel/sdist/rebuilt wheel/installations | Current packaging evidence |
| `compileall` and `git diff --check` | PASS | Static hygiene |
| VS Code | Not run: Node/npm unavailable | Environment limitation; blocks complete tooling claim |
| IntelliJ | Not run: Gradle cache read-only | Environment limitation; blocks complete tooling claim |

The complete Python run was interrupted after making no progress for several
minutes in an interpreter test. Its only reported failures were the twelve known
vector-orientation assertions, but unexecuted tests cannot be called passing.

## Contradictions, limitations and remaining risks

Source/document searches found no normative contradiction that promotes
`ERROR_HANDLING`, makes `Error.message()` throwing, exposes LLVM EH as stable,
or revives Qt/legacy tooling. Historical/experimental documents remain labeled
as such. The principal new contradiction was operational: committed ERQ-006
evidence said PASS while its callable corpus source no longer parsed; the source
is corrected in this qualification.

Remaining blockers to a `PROMOTE` decision are exact and evidence-related:

1. complete the current Python suite and classify its terminal result;
2. run the current VS Code suite with Node/npm;
3. run the current IntelliJ suite with a writable Gradle environment;
4. preferably repair or explicitly baseline the seven unrelated LSP inlay-hint
   failures before making a broad supported-tooling release claim.

These limitations are blockers under the qualification decision rule because
the task explicitly requires current full-suite and supported-tooling evidence.
They do not establish a new exception semantic, ownership, backend or runtime
defect.

## Files changed during qualification

- `corpus/exceptions/positive/indirect_call.ae`: migrated the ERQ-006 indirect
  callable to canonical `Function<(), void>` syntax.
- `uv.lock`: reconciled dependency metadata with the already-removed Qt/PyQt
  surface while preparing a clean release environment.
- `docs/compiler/EXCEPTION_RELEASE_QUALIFICATION_V2.md`: this report.

No accepted ADR was modified. `ERROR_HANDLING` remains `UNSUPPORTED`. No commit
was created.
