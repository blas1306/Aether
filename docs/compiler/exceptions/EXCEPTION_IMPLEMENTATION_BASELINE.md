# Exception Implementation Baseline

> Milestone: **0 — Preparation**
>
> Captured: **2026-07-29**, timezone `America/Montevideo`
>
> Repository commit before Milestone 0 documentation:
> `e568e98f93e84ad6529769779073351bd0e66d48`
>
> Behavioral changes in this milestone: **none**

## Baseline interpretation

The working tree was clean before the Milestone 0 documents were created. The
complete Python test run was performed before any milestone file existed and
therefore provides the pre-change behavioral baseline.

One repository failure was present at that point: the manifest entry for
`examples/SNL.ae` omits two capabilities now detected by the native capability
analyzer. The same failure was reproduced in isolation and by the examples
catalog checker. It is unrelated to exceptions and was not changed because this
milestone is documentation-only.

All other executable suites available in the environment passed. The VS Code
suite could not start because Node.js/npm are not installed.

## Environment

| Item | Observed value |
| --- | --- |
| Host | `Laptop-Blas` |
| Kernel | `Linux 7.0.0-28-generic #28-Ubuntu SMP PREEMPT_DYNAMIC Sun Jun 21 01:01:36 UTC 2026 x86_64` |
| OS | Ubuntu 26.04 LTS (Resolute Raccoon) |
| Architecture | `x86_64` |
| CPUs visible | 12 |
| Display session | Wayland |
| Project Python | CPython 3.14.4 (`.venv/bin/python`) |
| pytest | 9.1.1; pluggy 1.6.0 |
| System `python` / `pytest` | Not on `PATH`; all Python commands use the project virtual environment. |
| Rust toolchain selected by `compiler-rs/rust-toolchain.toml` | `rustc 1.85.1 (4eb161250 2025-03-15)` |
| Cargo selected in `compiler-rs/` | `cargo 1.85.1 (d73d2caf9 2024-12-31)` |
| Rustup default outside `compiler-rs/` | 1.95.0; not used for the workspace baseline |
| Rust command path | `/home/blas_1306/.cargo/bin/{rustc,cargo}`; Cargo is not on the shell `PATH`. |
| Clang | Ubuntu clang 21.1.8 (`x86_64-pc-linux-gnu`) |
| LLVM | `llvm-config-21 21.1.8` |
| Java | OpenJDK 25.0.3 |
| Gradle wrapper | 9.3.0, as reported by the checked-in wrapper execution |
| Node.js / npm | Not installed / not on `PATH` |

## Architecture-document identity

The approved inputs were not edited. Their SHA-256 identities at baseline are:

| Document | SHA-256 |
| --- | --- |
| `docs/compiler/COMPLETE_EXCEPTION_MODEL_RFC.md` | `3450ae8533871f236b4b13f82482c0a0ce78dc8bafee6fa7d1525faea1af61c6` |
| `docs/compiler/COMPLETE_EXCEPTION_MODEL_DECISION_LOG.md` | `306c69f858668b6ea0f03cfe23e333c9f0bee667adb9ee79c04c44f1a684e06e` |
| `docs/compiler/CHECKED_EXCEPTIONS_ARCHITECTURE_STUDY.md` | `838d1d4b7fa1c0b8420716cc171b948c4268b807799c1862942b14a4636ad65b` |
| `docs/compiler/EXCEPTION_ARCHITECTURE_RESOLUTION.md` | `4c89113bc4f2bf35be2965a0640af53efed271faebf12358d49aeb34bfc577a2` |
| `docs/compiler/EXCEPTION_IMPLEMENTATION_PLAN.md` | `83ae27d1252a6799105d340fcedb61ae6507f6dd011560a5bcec6e203b36bf10` |

## Test summary

| Suite | Exact command | Passed | Failed | Skipped | Xfailed | Duration / result |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| Complete Python suite | `PYTHONPATH=src .venv/bin/python -m pytest -ra` | 4,337 | 1 | 4 | 0 | 225.64 s |
| Reproduction of baseline failure | `PYTHONPATH=src .venv/bin/python -m pytest -q 'tests/aether/test_v1_profile_audit.py::test_every_example_matches_its_manifest_classification[examples/SNL.ae]'` | 0 | 1 | 0 | 0 | 0.35 s |
| Rust workspace | `cd compiler-rs && /home/blas_1306/.cargo/bin/cargo test --workspace` | 299 | 0 | 0 | 0 | 0.49 s on cached rebuild/re-run |
| IntelliJ plugin | `./gradlew test --console=plain` | 35 | 0 | 0 | 0 | 38 s |
| VS Code extension | `cd vscode-extension && npm test` | N/A | N/A | N/A | N/A | Not started: `node` and `npm` are unavailable. |

The Rust total counts all test targets reported by `cargo test --workspace`;
doc-test targets contained zero tests. The IntelliJ count comes from
`tools/intellij-aether/build/test-results/test/TEST-com.aetherstudio.intellij.AetherCommandLineTest.xml`.

### Python skips

| Count | Reason |
| ---: | --- |
| 3 | Rust-authority canary requires explicit activation (`tests/aether/test_rust_authority_canary.py`). |
| 1 | Newton system example is experimental (`tests/test_example_smoke.py`). |

No test was marked xfail in the complete run.

## Local CI and pipeline checks

The canonical local CI command was started without rerunning pytest:

```text
PYTHONPATH=src .venv/bin/python scripts/ci.py --skip-tests --verbose
```

It stopped, as designed, at the pre-existing examples-catalog mismatch after
41.80 seconds.

| CI stage / relevant check | Exact command | Result |
| --- | --- | --- |
| Whitespace | `git diff --check` | Passed before Milestone 0 files were added. |
| Capability consistency | `PYTHONPATH=src .venv/bin/python scripts/check_capability_consistency.py` | Passed. |
| Release-document consistency | `PYTHONPATH=src .venv/bin/python scripts/check_release_docs.py` | Passed. |
| Examples catalog | `PYTHONPATH=src .venv/bin/python scripts/check_examples_catalog.py` | Failed with the same pre-existing `examples/SNL.ae` capability mismatch. |
| Diagnostics contract | `PYTHONPATH=src .venv/bin/python scripts/check_diagnostics_contract.py` | Passed when run separately after CI stopped. |
| Python compileall | `PYTHONPATH=src .venv/bin/python -m compileall -q src scripts` | Passed when run separately. |
| Differential parity | `PYTHONPATH=src .venv/bin/python scripts/differential_parity.py` | Passed: 14 programs, 42 AST/native comparisons across O0/O1/O2. |

### Quick benchmark checks

The following commands all completed with `Failures: 0`:

```text
PYTHONPATH=src .venv/bin/python -m aether bench benchmarks/arithmetic.ae --iterations 1 --backend both
PYTHONPATH=src .venv/bin/python -m aether bench benchmarks/sum_to.ae --iterations 1 --backend both
PYTHONPATH=src .venv/bin/python -m aether bench benchmarks/vector_dot.ae --iterations 1 --backend both
```

| Program | AST parse/typecheck | AST execute | IR lower/verify | IR execute | IR O1 optimize |
| --- | ---: | ---: | ---: | ---: | ---: |
| `arithmetic.ae` | 0.002750 s | 0.110222 s | 0.004927 s | 0.116528 s | 0.007206 s |
| `sum_to.ae` | 0.002579 s | 0.061852 s | 0.004299 s | 0.041508 s | 0.007219 s |
| `vector_dot.ae` | 0.002724 s | 0.119628 s | 0.004860 s | 0.054874 s | 0.007191 s |

These are smoke timings, not performance commitments.

### LLVM emission and native build checks

LLVM emission passed for all seven current CI fixtures using:

```text
PYTHONPATH=src .venv/bin/python -m aether --emit-llvm examples/llvm/arithmetic.ae
PYTHONPATH=src .venv/bin/python -m aether --emit-llvm examples/llvm/countdown.ae
PYTHONPATH=src .venv/bin/python -m aether --emit-llvm examples/llvm/list_clear.ae
PYTHONPATH=src .venv/bin/python -m aether --emit-llvm examples/llvm/list_insert.ae
PYTHONPATH=src .venv/bin/python -m aether --emit-llvm examples/llvm/list_push.ae
PYTHONPATH=src .venv/bin/python -m aether --emit-llvm examples/llvm/list_remove_at.ae
PYTHONPATH=src .venv/bin/python -m aether --emit-llvm examples/llvm/vector_dot.ae
```

Native builds with Clang 21.1.8 passed for the same seven inputs using the
canonical command shape:

```text
PYTHONPATH=src .venv/bin/python -m aether build <fixture> -o <temporary-directory>/<fixture-stem>
```

Outputs were temporary baseline artifacts and are not repository files.

## Pre-existing failure

### `examples/SNL.ae` manifest capability mismatch

Observed failure:

```text
expected=[
  AE-BACKEND-ARITHMETIC,
  AE-BACKEND-MATRIX,
  AE-BACKEND-VECTOR
]
actual=[
  AE-BACKEND-ARITHMETIC,
  AE-BACKEND-FUNCTION_VALUES,
  AE-BACKEND-MATRIX,
  AE-BACKEND-MODULES,
  AE-BACKEND-VECTOR
]
```

Affected checks:

- `tests/aether/test_v1_profile_audit.py::
  test_every_example_matches_its_manifest_classification[examples/SNL.ae]`
- `scripts/check_examples_catalog.py`
- consequently the complete local CI pipeline, which stops at that checker.

Investigation:

- The capability detector now reports `AE-BACKEND-FUNCTION_VALUES` and
  `AE-BACKEND-MODULES` for the example.
- The example manifest still lists only arithmetic/matrix/vector.
- The isolated test reproduces deterministically.
- The failure existed while the working tree was clean and before any Milestone 0
  document was created.
- It is unrelated to `ERROR_HANDLING`, exception architecture, or this
  documentation-only change.

Disposition: recorded as pre-existing. Fixing the example manifest would be an
unrelated repository behavior/data change and is outside this milestone.

## Capability-gate baseline

Observed with:

```text
PYTHONPATH=src .venv/bin/python -c 'from aether.capabilities import BACKEND_CAPABILITY_PROFILES, Capability; print("\n".join(f"{backend.value}: {profile.support_for(Capability.ERROR_HANDLING).state.value}" for backend, profile in BACKEND_CAPABILITY_PROFILES.items()))'
```

Result:

| Profile | `ERROR_HANDLING` state | Interpretation |
| --- | --- | --- |
| `native` | `UNSUPPORTED` | This is the sole normative stable Aether 1.0 profile. Exception syntax is rejected before IR lowering. |
| `ast` | `COMPLETE` | Auxiliary/reference frontend profile with the obsolete experimental implementation; it is not a stable language profile or promotion evidence. |

Additional evidence:

- `scripts/check_capability_consistency.py` passes.
- `docs/aether/AETHER_NATIVE_PROFILE_V1.md` renders `error-handling` as
  `UNSUPPORTED`.
- `tests/aether/test_backend_capabilities.py` covers detection and native
  rejection.
- `docs/aether/AETHER_FRONTEND_EXPERIMENTS.md` explicitly classifies
  `throw`/`try`/`catch` as non-normative experiments.

Conclusion: **`ERROR_HANDLING` remains disabled in every stable capability
profile.** No profile or capability source was modified in Milestone 0.

## Milestone-caused failures

None.

Post-document validation repeated:

```text
PYTHONPATH=src .venv/bin/python -m pytest -q -ra
```

Result: **4,337 passed, 1 failed, 4 skipped, 0 xfailed in 223.68
seconds**. The sole failure was the same
`test_every_example_matches_its_manifest_classification[examples/SNL.ae]`
manifest mismatch, with the same two extra capability codes. No Milestone 0
regression was introduced.

The following post-document consistency checks also passed:

```text
PYTHONPATH=src .venv/bin/python scripts/check_capability_consistency.py
PYTHONPATH=src .venv/bin/python scripts/check_release_docs.py
PYTHONPATH=src .venv/bin/python scripts/check_diagnostics_contract.py
git diff --check
```
