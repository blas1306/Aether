# RUST-1 — Initial IR verifier authority readiness

## Decision

`KEEP_RUST_SHADOW`

The repository is at **RP2**: Python is the production Initial IR verifier
authority and Rust is the required shadow/canary implementation.  This audit
does not change that policy.  “Authority” means that its acceptance or
rejection alone decides whether compilation continues.  A shadow is evidence,
never a fallback.  An authority infrastructure failure must fail closed.

## Evidence and result

The deterministic audit found 150 stable rule identifiers in the production
Python verifier and its code-audited umbrella-rule inventory. Python maps all
150. The Rust verifier source provides direct rule-ID evidence for 124; 26 production IDs do not have equivalent
mapping evidence.  They include exception/effect/call rules IRV-131–IRV-148 as
well as several shared data-flow rule families.  Under the RUST-1 stop
conditions this incomplete negative-rule coverage is sufficient to block
promotion, even though the existing canary evidence is strong.

The checked-in canary establishes 140 real Rust-authority observations: 65
matching accepts, 72 matching semantic rejects, and three documented
diagnostic-only divergences.  This is valuable RP2 evidence but cannot prove
that every production responsibility rejects an invalid input equivalently.
No historical counts beyond repository artifacts are claimed.

The machine-readable source of truth is
[`rust_initial_ir_verifier_authority_readiness.json`](rust_initial_ir_verifier_authority_readiness.json).
It enumerates all production rule IDs, all 84 concrete Python Initial IR
instruction classes, and all 19 concrete type classes.  Regenerate or verify it
with:

```console
python scripts/check_rust_verifier_authority_readiness.py
python scripts/check_rust_verifier_authority_readiness.py --check
```

## Responsibility map

| Component | Current responsibility |
| --- | --- |
| `aether-ir` | Owned IR representation, wire DTOs, schema-v1 import |
| `aether-verifier` | Rust structural, type, CFG, return, SSA-wire, lifecycle, borrow, exception, and aggregate checks |
| `aether-ir-verifier` | Versioned stdin/stdout executable protocol and diagnostic transport |
| `aether-python` | Future-facing PyO3 boundary; absent from production and not required for promotion |

Python's production verifier remains the canonical responsibility inventory.
Initial IR does not impose SSA phi/dominance rules: those belong to the SSA
verifier.  Initial IR does check block/terminator/CFG structure, definition and
definite-initialization flow, types and operands, calls and returns, aggregates,
collections and linear algebra, ownership/borrows, and exception-event flow.

## Parity findings

- Wire/type/instruction import is broadly covered by DTO and Rust importer
  completeness tests.  Protocol v1 and IR schema v1 are checked explicitly;
  malformed input and incompatible versions are distinct from semantic reject.
- CFG, all-path return, lifecycle, borrowed `ArrayGet<String>`, aggregate
  metadata, collections, calls, and exception paths have positive and negative
  differential examples.  The canary shows agreement for its bounded corpus.
- Initial IR dominance is definition-availability data flow, not SSA dominance.
  SSA dominance remains a separate component and authority.
- Rust diagnostics transport stable IRV category identifiers and structured
  function/block/instruction context.  Exact prose is not a compatibility gate.
- The subprocess boundary is acceptable for an initial promotion: it has
  bounded timeout, output/request limits, executable identity, process failure,
  malformed response, and version mismatch classifications.  PyO3 is not a
  prerequisite.
- Repository evidence does not release-qualify packaged verifier binaries for
  every supported installation/platform.  Timing evidence is intentionally not
  embedded in the deterministic artifact; no pathological regression is shown,
  but performance is not a promotion proof.

## Blocking gaps

1. **RULE_COVERAGE (critical):** 26 Python production rule families lack direct
   Rust mapping evidence.  Every one needs an equivalent implementation and a
   semantically invalid, structurally transportable negative fixture.
2. **PACKAGING / PLATFORM (critical):** installed-product binary discovery and
   availability are not release-qualified for all supported targets.
3. **CI (critical):** RP2 workspace, protocol, corpus and canary tests exist,
   but a production RP3 authority-mode/package gate does not.

Consequently semantic parity, negative coverage, packaging, and RP3 CI gates
fail.  Wire/protocol classification, explicit fail-closed policy, centralized
configuration, and rollback design pass.  There are no `UNKNOWN` production
rules: uncovered rules are explicitly classified `RUST_WEAKER_INVALID`.

## Shadow, failure, and rollback model

The coordinator distinguishes both accept, both reject, each directional
semantic disagreement, Rust integration/infrastructure failure, and unavailable
or skipped Rust.  Current production remains Python-authoritative.  The
test-only Rust-authority canary fails closed and never silently retries Python.

Rollback after a future RP3 promotion should change the single immutable
`VerifierAuthorityConfiguration` back to
`PYTHON_AUTHORITY_RUST_SHADOW`, preserve comparison telemetry, and ship that
configuration/patch independently of unrelated compiler migrations.  No
per-compilation fallback should be introduced.

Python shadow retirement for RP4/RP5 requires complete negative-rule parity,
zero unresolved semantic divergence across the repository corpus and release
soak evidence, stable contextual diagnostics, qualified package/platform
binaries, and CI coverage of authority failure.  Today Python verifier callers
are production (`IRBackend` direct verification), oracle/shadow (coordinator
and canary), tests (IR and differential suites), and documentation; none are
removed by this audit.

## Exact next milestone

RUST-2 must not start as an authority switch yet.  First close the recorded
rule, packaging/platform, and CI blockers and regenerate this artifact.  Once
all nine gates pass, RUST-2 may be narrowly scoped to selecting
`RUST_AUTHORITY_PYTHON_SHADOW` at the centralized production switch, preserving
fail-closed behavior, disagreement telemetry, Python shadow execution,
packaging checks, tests, documentation, and the explicit rollback switch.  It
must not migrate SSA, optimization, parsing, typechecking, or other compiler
components.
