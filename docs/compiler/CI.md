# Local Continuous Integration

Aether has a small, repository-local continuous-integration runner. From the
repository root, run:

```bash
python scripts/ci.py
```

On systems where the virtual environment is the available Python interpreter,
the equivalent command is:

```bash
.venv/bin/python scripts/ci.py
```

The runner is independent of GitHub Actions and other hosted CI systems. It
stops at the first failure, names the failed stage, and returns that command's
non-zero exit code.

## Pipeline

The stages run in this order:

1. `git diff --check` detects whitespace errors.
2. `PYTHONPATH=src .venv/bin/pytest` runs the complete test suite.
3. Three representative scalar, control-flow, and vector benchmarks run with
   `--iterations 1 --backend both`.
4. The same categories of examples pass through `aether --emit-llvm` as an
   LLVM-emission smoke check.
5. Those examples are compiled to temporary native executables with `aether
   build` and clang.

The native outputs live in a temporary directory and are removed when the
pipeline ends. LLVM emission does not require clang. If clang is not on
`PATH`, the runner prints a warning, skips only the native stage, and continues
with every check that can still run.

Useful options are:

```text
--skip-tests
--skip-bench
--skip-llvm
--skip-native
--verbose
```

`--verbose` prints each command and streams its output. Without it, successful
command output stays quiet; output from a failed command is shown with the
failed stage.

## When to use it

Run the local CI command before committing or handing off compiler changes. It
is also a convenient final validation after a refactor because it combines
repository hygiene, correctness tests, quick pipeline timings, LLVM emission,
and native compilation behind one command.

Use `pytest` directly while developing or diagnosing a specific behavior. It
is the correctness suite and provides focused test selection, fixtures, and
failure details. The CI runner invokes the complete pytest suite but is not a
replacement for targeted test commands.

Use `aether bench` directly for performance investigation. Benchmarks report
approximate timings and are not correctness tests or stable cross-machine
performance comparisons. Local CI runs only three representative programs for
one iteration; it does not retain results or compare them with a baseline.

## Adding a stage

Keep stages deterministic, fast, and local:

1. Add its command or commands to `build_stages()` in `scripts/ci.py` at the
   required position.
2. Give the stage a short report name.
3. Add or update mocked-subprocess tests in `tests/test_ci.py` to cover its
   order, failure propagation, and exit code.
4. Document the new command and any optional external dependency here.

Do not hide failures inside a stage. A required command must return non-zero so
the runner can stop and report it clearly.
