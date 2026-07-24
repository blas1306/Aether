# Initial IR Shadow Verification

Phase 4.3 adds an opt-in, Python-authoritative shadow mode for the Initial IR
verifier. It is a development observation mechanism, not a verifier selector:
Python remains the only verifier that can accept or reject compilation.

Shadow mode is **disabled by default**. `IRBackend()` still constructs no Rust
client, performs no executable discovery or canonical serialization, computes
no request hash, and emits no report. There is no environment-variable or CLI
activation and no automatic fallback.

## Execution and authority

An explicitly configured `ShadowVerifierCoordinator` performs these operations
sequentially:

1. Run `IRVerifier(module).verify()` exactly once.
2. Normalize an ordinary `IRVerificationError` into a message-free outcome.
3. Build exactly one canonical protocol-v1 request and hash its complete
   payload with lowercase SHA-256.
4. Call the explicitly supplied `RustVerifierClient`.
5. Classify the observation and emit one immutable report.
6. Return the module accepted by Python, or re-raise the original Python error
   object with its traceback and cause chain.

Only `IRVerificationError` is an ordinary authoritative rejection. An
unexpected Python `AssertionError`, `TypeError`, `ValueError`, or other
implementation error propagates immediately and Rust is not invoked.
Classifier, registry, and report-construction bugs also propagate; they are not
misreported as transport failures.

Rust acceptance, rejection, disagreement, timeout, process failure, protocol
failure, malformed response, or non-strict sink failure cannot change the
Python result. The coordinator does not print, log globally, transmit data, or
modify emitted IR/SSA/LLVM/native artifacts.

## Programmatic enablement

The executable must be selected explicitly:

```python
from aether.ir import (
    CollectingShadowReportSink,
    ShadowVerifierCoordinator,
)
from aether.ir.rust_verifier import SubprocessRustVerifierClient
from aether.pipeline import IRBackend

sink = CollectingShadowReportSink()
client = SubprocessRustVerifierClient(
    executable="/explicit/development/path/aether-ir-verifier",
)
coordinator = ShadowVerifierCoordinator(client=client, sink=sink)
backend = IRBackend(shadow_verifier=coordinator)
```

This integration does not call
`discover_rust_verifier_executable()`. Packaged executable discovery, PyO3,
concurrency, stable user-facing configuration, telemetry, and Rust authority
remain outside Phase 4.3.

## Outcomes and classification

Python normalization retains the invariant and category from
`VerifierFailure`. Phase and function/block/instruction context are optional.
The current Python error API does not expose that structural context, so the
normalizer records `None`; it never derives context from message text or
invents it. The original `IRVerificationError` stays only in coordinator
control flow and is not retained in reports.

Rust diagnostics use the transport-neutral normalized fields. Message prose,
source paths, invocation metadata, and timings never participate in identity.
The closed classifications are:

- `MATCH_ACCEPTED`
- `MATCH_REJECTED_EXACT`
- `MATCH_REJECTED_SEMANTIC`
- `DOCUMENTED_DIAGNOSTIC_DIVERGENCE`
- `DOCUMENTED_OUTCOME_DIVERGENCE`
- `UNEXPECTED_DIAGNOSTIC_DIVERGENCE`
- `UNEXPECTED_OUTCOME_DIVERGENCE`
- `RUST_INFRASTRUCTURE_FAILURE`
- `RUST_INTEGRATION_FAILURE`
- `SHADOW_SKIPPED`
- `SHADOW_COORDINATOR_FAILURE` (reserved for a future controlled reporting
  mechanism; current internal bugs propagate)

An exact rejection match means the complete available keys are equal. A
semantic rejection match requires equal invariant IDs, no category or phase
contradiction, agreement on every structural field available on both sides,
and missing context on one side. A different invariant, category, phase, or
shared structural value is an unexpected diagnostic divergence unless one
exact reviewed rule matches.

The original Phase 4.3 set of 128 transportable corpus observations split into
64 accepted matches, 60 semantic rejection matches, three documented
diagnostic divergences, and one documented outcome divergence. The rejection
matches are semantic because Rust reports structural context that the current
Python exception API does not expose. The two nontransportable DTO-boundary
cases are represented explicitly by test-harness `SHADOW_SKIPPED`
observations.

Phase 4.5C later resolved that sole outcome divergence by aligning Python
IRV-024 with Rust's graph semantics. The current 141-case baseline is 65
accepted matches, 73 semantic rejection matches, three documented diagnostic
divergences, and zero documented outcome divergences.

## Hash-scoped documented divergences

`shadow_divergences.py` owns an immutable production registry. It does not
import the test manifest. Every rule matches all of:

- stable rule ID;
- exact SHA-256 of the complete canonical request;
- complete expected Python and Rust outcome keys;
- protocol version;
- IR schema version;
- documented diagnostic or outcome classification.

The registry now contains only the three reviewed schema-v1 diagnostic cases:

| Rule | Canonical request SHA-256 |
| --- | --- |
| Python IRV-031 / Rust IRV-032 | `65b64a4021d20766e845fb23e48fd90c4992cf0f23936298e147f8b4eb6c095e` |
| Python IRV-050 / Rust IRV-026 | `90c0a3fccf6b737179d1feef9c32d11b3874edfccc3914facbd0df1d904803d9` |
| Python IRV-036 / Rust IRV-028 | `2b1463ad529acf1b86dccd04c89408431826d51d0a0bba8739830c4e46d30d1f` |

A matching invariant pair with a different hash, context, version, or outcome
direction is not documented.

The retired IRV-024 rule used request hash
`d635f6fc4c9e933e20442539c12409fcdc3de3da0938927f6b784c3002550baa`.
It remains recorded here as migration history, but is no longer executable
policy because both verifiers accept that graph.

## Reports, sinks, stages, and privacy

`ShadowVerificationReport` is frozen and contains the authoritative normalized
outcome, Rust-safe observation, comparison, and operational metadata. Reports
retain only the request hash, client kind, protocol/schema versions, compiler
stage, lightweight monotonic timings, optional documented rule ID, and a
bounded normalized failure kind/summary. They do not contain source, full IR,
request bytes, arbitrary stderr, environment values, PIDs, home directories,
or temporary paths.

`semantic_snapshot()` excludes timings, making repeated semantic reports
deterministic. `NullShadowReportSink` and `CollectingShadowReportSink` implement
the explicit `ShadowReportSink` protocol. Sink failures are ignored by default
and are not recursively reported. A narrow `strict_sink_errors=True` test mode
can expose a sink exception after a Python acceptance; an already determined
Python rejection still wins.

`IRBackend` labels normal lowering/verification as `INITIAL` and verification
after IR optimization as `POST_OPTIMIZATION`. Direct coordinator use defaults
to `EXTERNAL`. Repeated calls emit repeated reports even when their request
hashes are equal. `--emit-cfg`, direct `IRVerifier` calls, AST, REPL, and LSP
paths remain outside shadow mode.

Infrastructure failures are valid Rust protocol responses whose outcome is
non-semantic. Integration failures occur while constructing the request or
invoking/decoding the configured transport. Both are reported safely and both
follow Python.

## Current transition boundary

The reports provide initial parity evidence only. Before Rust can become
authoritative, an extended validation phase still needs production packaging
and executable selection, sustained parity/performance review, a policy for
unexpected divergence, and an explicit authority transition design. Phase 4.3
does not implement any of those decisions.
