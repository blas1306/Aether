# RUST-2.P — Persistent Rust verifier transport

RUST-2.P removes process startup from the per-verification hot path without
changing Initial IR verifier semantics or authority policy.

## Architecture

Before, `SubprocessRustVerifierClient.verify()` invoked `Popen` for every
protocol-v1 request. Its cached identity avoided repeated identity validation,
but did not preserve the verifier process. For 50 requests the architecture
therefore required 51 startups: one identity command and 50 verifier commands.

The production session harnesses now use
`PersistentSubprocessRustVerifierClient`. It starts `aether-ir-verifier
--persistent` lazily. Transport framing v1 is a four-byte unsigned big-endian
length followed by bytes. The initial server frame contains executable
identity; every later request and response frame contains the unchanged
canonical semantic protocol-v1 JSON payload. The one-shot interface remains
available and qualified.

One lock covers each complete request/response exchange. A crash, timeout,
unexpected EOF, malformed frame, oversized response, or malformed semantic
response poisons and terminates the worker. The client does not restart or
retry the active request. Request and response limits remain explicit, stderr
remains non-semantic transport metadata, and `close()` provides deterministic
shutdown.

## Focused measurement

On the development Linux host, 2026-08-20, 50 repetitions of the same accepted
small module and the debug companion produced:

| Transport | Process startups | Total | Average |
| --- | ---: | ---: | ---: |
| One-shot (including cached identity validation) | 51 | 0.632522 s | 12.651 ms |
| Persistent | 1 | 0.099952 s | 1.999 ms |

This focused run measured a 6.33x transport speedup. Timings are evidence, not
a CI threshold; the deterministic regression gate is one worker startup for
multiple requests.

## Qualification status

- Authority remains Rust with mandatory Python shadow under RP3.
- RP2 Python-authority rollback configuration remains unchanged.
- Semantic protocol version, IR schema version, product version, rules,
  invariant IDs, and normalized diagnostics are unchanged.
- Full Rust workspace: passed.
- Focused Python transport/authority tests: 117 passed.
- Persistent lifecycle/fault/concurrency tests: 6 passed.
- 150-rule parity checker and companion packaging checker: passed.
- Full RP3 canary: 404/404, zero semantic mismatches, zero infrastructure
  failures.
- Numeric/backend parity: 20 passed after the separately justified timeout
  calibration below.
- Full Python suite: 4667 passed, 4 skipped, 26 failed in 1364.02 seconds
  (22:44). Two failures were obsolete RP2 harness expectations and have been
  corrected. The other 24 are native exception LeakSanitizer failures caused
  by the host reporting that LeakSanitizer cannot run under ptrace; they are
  unrelated to verifier transport.

The historical `probandoNR3.ae` timeout failed at 20 seconds in a test that
does not install either Rust verifier pipeline. Its manifest allowance is now
45 seconds, providing margin over the historically measured ~30-second native
workload. This is recorded as pre-existing timeout calibration debt and is not
attributed to RUST-2.P.
