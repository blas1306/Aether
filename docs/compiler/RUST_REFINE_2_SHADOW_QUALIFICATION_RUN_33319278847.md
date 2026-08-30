# RUST-REFINE-2 official run 33319278847

## Immutable decision

GitHub Actions run `33319278847`, attempt 1, executed revision
`e2aa961e24eb50bea6d18ce5302576b8e77b2cf5` from `main` on 2026-08-30. Its
historical conclusion is `FAILED` and its milestone decision is permanently:

```text
RUST_REFINEMENT_SHADOW_QUALIFICATION_BLOCKED
```

This run is partial evidence only. It is not a qualification, must not be
reinterpreted as PASS, and must not be rerun as a substitute for a new manual
qualification run.

The official log archive consumed for the diagnosis had SHA-256
`e3020cb5564e01957287812a320337efae35ca92da9bf10ca0d7327990345d8d`.

## contract-and-baseline

The job ran on GitHub-hosted Ubuntu 24.04.4 (`ubuntu-24.04` image
`20260823.283.1`) with CPython 3.13.15. Its working directory was
`/home/runner/work/Aether/Aether`. Relevant environment values were:

```text
CARGO_TERM_COLOR=always
AETHER_COMPILER_CORE_BUILD_IDENTITY=e2aa961e24eb50bea6d18ce5302576b8e77b2cf5
PYTHONUNBUFFERED=1
pythonLocation=/opt/hostedtoolcache/Python/3.13.15/x64
Python_ROOT_DIR=/opt/hostedtoolcache/Python/3.13.15/x64
LD_LIBRARY_PATH=/opt/hostedtoolcache/Python/3.13.15/x64/lib
```

Before the failure, the job had only checked out the repository and run
`actions/setup-python`; it had installed no Python project dependencies. The
failing command and exit code were:

```text
python scripts/qualify_rust_refine_2_shadow.py --mode contract \
  --revision e2aa961e24eb50bea6d18ce5302576b8e77b2cf5 \
  --run-id 33319278847 \
  --output qualification/rust-refine-2/contract.json
exit code: 1
```

The complete relevant import traceback was:

```text
scripts/qualify_rust_refine_2_shadow.py:35
  _load(... scripts/qualify_rust_refine_1_shadow.py)
scripts/qualify_rust_refine_1_shadow.py:25
  from aether.ir.dto import ir_module_to_dto
src/aether/__init__.py:5
  from .language_service import ...
src/aether/language_service.py:14
  from .runner import run_aether
src/aether/runner.py:8
  from .session import AetherSession
src/aether/session.py:9
  from .interpreter import Function, Interpreter
src/aether/interpreter.py:10
  from plot_backend import PlotBackend
src/plot_backend.py:7
  import numpy as np
ModuleNotFoundError: No module named 'numpy'
```

`numpy==2.4.2` is a normal runtime dependency declared both in
`pyproject.toml` and `requirements.txt`. The job was executing repository code
before provisioning the repository runtime environment. The expected artifact
was `rust-refine-2-contract`, sourced from
`qualification/rust-refine-2/contract.json`. It was not produced because the
qualifier failed during module import before `main()` could write the file.

Classification: **qualification harness defect**. The remediation installs the
declared repository runtime requirements before running the contract qualifier;
it does not add an isolated ad-hoc NumPy install.

## source-development-install

The job ran on GitHub-hosted Ubuntu 24.04.4 (`ubuntu-24.04` image
`20260823.283.1`) with CPython 3.13.15. Its working directory was
`/home/runner/work/Aether/Aether`. It inherited the same common variables as
the contract job and also had `CARGO_HOME=/home/runner/.cargo` and
`CARGO_INCREMENTAL=0`.

Before the suite, the job successfully installed exactly the following packages
through its explicit pip steps:

```text
contourpy==1.3.3
cycler==0.12.1
fonttools==4.63.0
iniconfig==2.3.0
kiwisolver==1.5.1
matplotlib==3.10.8
maturin==1.15.0
mpmath==1.3.0
numpy==2.4.2
packaging==26.3
pillow==12.3.0
pluggy==1.6.0
pygments==2.21.0
pyparsing==3.3.2
pytest==9.1.1
python-dateutil==2.9.0.post0
scipy==1.17.1
six==1.17.0
sympy==1.14.0
aether-compiler-core==1.0.0rc4  # locally built wheel
aether-language==1.0.0rc4       # editable, --no-deps
```

It did not install the declared `dev` dependency group, so the environment did
not contain the required setuptools build backend. It also did not build the
repository test suite's debug SSA companion or release IR verifier.

The failing command was:

```text
set -o pipefail
mkdir -p qualification/rust-refine-2
python -m pytest -q tests | tee qualification/rust-refine-2/full-pytest.log
exit code: 1
```

The result was `4 failed, 5175 passed, 13 skipped in 315.13s`. Each failure is
individually classified below.

### 1. test_mutation_campaign_has_no_semantic_or_acceptance_divergence

Exact test:
`tests/aether/test_rust_refine_1_shadow.py::test_mutation_campaign_has_no_semantic_or_acceptance_divergence`.

The qualifier created `PersistentRustSSALoweringClient` with
`compiler-rs/target/debug/aether-ssa-shadow --persistent`.
`subprocess.Popen`/`os.posix_spawn` raised `FileNotFoundError: [Errno 2]`, which
`src/aether/ssa/shadow.py:326` wrapped as
`RuntimeError: Rust SSA companion startup failure`. The job had never built
that executable.

It passes in the normal full-suite CI environment, which builds the debug
`aether-ssa-shadow` first. It failed only in this source-development job.
Classification: **qualification harness defect** (missing repository-test
build prerequisite), not a source install or RUST-REFINE defect.

### 2. test_known_input_domain_divergence_is_explicit_and_fail_closed

Exact test:
`tests/aether/test_rust_refine_1_shadow.py::test_known_input_domain_divergence_is_explicit_and_fail_closed`.

The stack and cause were the same executable lookup path as failure 1:
`subprocess.Popen` -> `os.posix_spawn` -> `FileNotFoundError` for
`compiler-rs/target/debug/aether-ssa-shadow`, wrapped as
`RuntimeError: Rust SSA companion startup failure`.

It passes in the normal full-suite CI environment and failed only in this job.
Classification: **qualification harness defect** (missing repository-test
build prerequisite), not a RUST-REFINE acceptance divergence.

### 3. test_packaging_script_produces_resolvable_release_archive

Exact test:
`tests/aether/test_rust_verifier_operational.py::test_packaging_script_produces_resolvable_release_archive`.

The test invoked:

```text
python scripts/package_rust_verifier.py \
  --output <temporary-directory> \
  --executable compiler-rs/target/release/aether-ir-verifier \
  --platform linux --arch x86_64
```

`package_rust_verifier()` called `_require_release_binary()`, which raised:

```text
RuntimeError: verifier release binary does not exist:
/home/runner/work/Aether/Aether/compiler-rs/target/release/aether-ir-verifier
```

The subprocess exited 1 and the test assertion failed. The normal full-suite
CI environment builds this release binary first; this job did not.
Classification: **qualification harness defect** (missing repository-test
build prerequisite), not a packaging product defect.

### 4. test_clean_wheel_install_has_rust_verifier_metadata

Exact test:
`tests/test_installed_wheel.py::test_clean_wheel_install_has_rust_verifier_metadata`.

The test intentionally executed the source wheel build without isolation:

```text
python -m pip wheel --no-deps --no-build-isolation \
  --wheel-dir <temporary-directory>/wheel <repository-root>
```

Pip reached `prepare_metadata_for_build_wheel` and
`pyproject_hooks._call_hook`, then raised:

```text
pip._vendor.pyproject_hooks._impl.BackendUnavailable:
Cannot import 'setuptools.build_meta'
```

The subprocess exited 2 and the assertion failed. `setuptools>=77` is already
declared in both `[build-system].requires` and the repository `dev` dependency
group. Build isolation was deliberately disabled by the test, so the
source-development test environment must install its declared dev group.

It passes in the normal repository environment, which contains setuptools,
and failed only in this incompletely provisioned source-development job.
Classification: **qualification harness defect/environment defect caused by
the harness**; it is not a source wheel defect.

The expected logical artifact was `qualification/rust-refine-2/source.json`,
with `full-pytest.log` as supporting evidence. The log was uploaded, but
`source.json` was not produced because the fail-closed pipeline stopped after
pytest exited 1 and skipped the product probe. Therefore the published
`rust-refine-2-source-install` ZIP contained only the failing log and could not
serve as mandatory PASS evidence.

The remediation installs the declared `dev` dependency group, builds the debug
SSA companion and release IR verifier demanded by the full repository suite,
and continues to run all tests. No tests are excluded.

## Dependency/environment contracts

The workflow intentionally retains three distinct environment classes:

| Environment class | Jobs | Installation contract |
| --- | --- | --- |
| repository/test | contract and repository qualification jobs | Runtime requirements from `requirements.txt`; jobs running the full suite additionally install `[dependency-groups].dev` and build the test binaries they exercise. |
| source-development | `source-development-install`, pipeline and transport source probes | Local native core wheel plus editable language checkout; runtime requirements are installed before `--no-deps`. The full-suite job also uses the declared dev group. |
| packaged consumer | dedicated packaged, platform and Python-matrix jobs | Build both wheels, then let the clean-consumer harness resolve/install the exact wheel metadata in an isolated temporary environment without importing the checkout. |

The classes are not artificially homogenized: clean consumers remain wheel
consumers, while source/repository jobs receive only the dependencies and build
prerequisites required by their stated contract.

## Aggregate and partial evidence

The aggregate correctly failed closed. It recorded `contract-and-baseline` and
`source-development-install` as failed, found the mandatory contract artifact
absent and source evidence non-PASS/incomplete, emitted
`RUST_REFINEMENT_SHADOW_QUALIFICATION_BLOCKED`, and exited 1. The aggregate and
its twelve adversarial tests were not weakened.

The run published 18 official ZIPs. All 18 downloaded ZIP hashes matched the
GitHub artifact digests. Sixteen of eighteen logical evidence gates passed.
Historical differential evidence had zero acceptance divergences; the semantic
mutation campaign had 33/33 reject/reject outcomes and its non-semantic control
was accept/accept. All platform and Python matrix jobs passed, and the packaged
clean consumer executed both Rust and Python verification. These facts remain
partial evidence and do not change the blocked decision.

## Authority preservation

This remediation changes only qualification workflow provisioning and its
documentation/regression coverage. It does not modify Rust verifier behavior,
SSA construction, optimizers, backends, runtime, schemas, protocols or
transports. Python `SSARefinementVerifier` remains mandatory and no Rust
refinement authority is promoted.
