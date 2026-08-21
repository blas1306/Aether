# RUST-3.4 Rust SSA shadow operational qualification

Decision: **RUST_SSA_SHADOW_OPERATIONALLY_BLOCKED**.

The expanded local soak discovered a new semantic difference, so qualification
stopped without changing lowering semantics. In
`tests/aether/parity_corpus/aggregates.ae`, canonical comparison reports 56
Python instructions and 55 Rust instructions in `main` / `entry`. Python
remains the only SSA authority and Rust SSA never reaches optimization or a
backend.

| Gate | Result | Evidence |
|---|---|---|
| SO1 persistent transport | PASS | 132 corpus requests with one startup |
| SO2 same-input guarantee | BLOCKED | New corpus mismatch |
| SO3 semantic differential | BLOCKED | 1 mismatch in 132 comparisons |
| SO4 fail-closed mismatch | PASS | Structured fatal `SSAShadowFailure` |
| SO5 fail-closed infrastructure | PASS | Startup, transport, timeout and malformed responses remain fatal |
| SO6 clean installation | BLOCKED | Not claimed by the checkout-local run |
| SO7 packaged discovery | PASS | Canonical platform layout; no PATH or `target/debug` fallback |
| SO8 long-session isolation | PASS | 1,000 deterministic requests, one startup |
| SO9 concurrency safety | PASS | 128 requests serialized through one synchronized process |
| SO10 cross-platform execution | BLOCKED | Matrix configured; remote execution evidence not collected locally |
| SO11 rollback | PASS | `PYTHON_SSA_ONLY` remains the default and needs no companion |
| SO12 CI integration | PASS | Fast matrix plus explicit scheduled/manual full qualification |

## Measurements

The discovered corpus contained 161 programs: 132 reached verified SSA and 29
were rejected before SSA. All 132 accepted programs were shadow-compared. There
was one semantic mismatch and no infrastructure failure.

The 1,000-request session used one process. Linux RSS was approximately
5,005,312 bytes both after startup and at the end, so it stabilized in this
observation. This is deliberately not an RSS gate. The concurrent test used 128
requests and one process, with no crossed or interleaved responses.

Observed totals on this host were 0.405 s for Python lowering, 3.307 s for the
complete Python-plus-shadow calls, and 0.169 s for canonical comparison. These
are observational rather than absolute performance gates.

The CI workflow declares Linux x86_64, Windows x86_64, macOS x86_64 and macOS
arm64 runners. Its normal shadow lane runs representative persistent and
failure coverage; the expensive full corpus is scheduled/manual on Linux.
Cross-platform execution results must still be collected before SO10 can pass.

Rollback is the configuration `PYTHON_SSA_ONLY`; no code modification is
required. RP3 is unchanged, no Rust-authority mode was activated, and no commit
was created.
