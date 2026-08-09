# Aether compiler benchmarks

These deterministic programs exercise the current compiler pipeline. They are
development benchmarks, not correctness tests or a stable performance suite.
Results from different machines, operating systems, compiler versions, or
toolchains are not directly comparable.

Run one program with a reasonable iteration count:

```bash
aether bench benchmarks/sum_to.ae --iterations 20 --backend all
```

The profiles are grouped as `frontend`, `middle-end`, `codegen`, and `runtime`:

- `ast` measures AST parsing/typechecking and AST execution separately.
- `ir` measures IR lowering/verification, IR execution, and the non-executed
  IR optimizer profile selected with `-O` (O0 by default). `both` retains its original meaning: `ast` + `ir`.
- `ssa` measures verified general SSA construction and verified SSA
  optimization.
- `llvm` measures the pipeline through optimized SSA and LLVM emission.
- `native` reports two distinct numbers. **Native build** measures source to
  typed program, SSA, SSA optimization, LLVM emission, and clang. **Native
  run** compiles once outside the timed interval and then runs that same
  temporary executable for every measured iteration.
- `all` selects every profile above.

Native programs are expected to return exit code 0 by default. Use
`--expected-exit-code N` to validate another code or `--ignore-exit-code` to
explicitly disable validation. Missing clang is reported as unsupported while
non-native profiles continue. Temporary LLVM and executable files are removed.

Use enough iterations that timer noise is small relative to the workload, but
remember that `Native build` invokes clang once per iteration.

Benchmark reports include the selected optimization profile. Compilation-aware
measurements use the same Aether pass registry and clang mapping as run/build;
select it with `-O0`, `-O1`, or `-O2`.

## Python IR verifier baseline

The Phase 0 verifier benchmark measures only calls to the current Python
`IRVerifier`. It materializes the valid and invalid modules indexed by
`tests/aether/rust_migration/manifest.yaml` through their owning pytest tests,
then performs warm-up and measured verifier rounds. Corpus materialization,
pytest, source parsing, lowering, IR execution, optimization, SSA, and native
compilation are outside the timed interval.

From the repository root, with the project dependencies and pytest available,
rerun the baseline with:

```bash
.venv/bin/python benchmarks/ir_verifier.py --rounds 10 --warmup 1
```

The report includes the modules verified per round, accepted and rejected
counts, total measured verification time, average time per module, throughput,
the distribution of full-corpus round times, and the Python, OS, and CPU
environment. Keep the command, corpus schema, and environment the same when
comparing results. Increase `--rounds` when collecting a more stable local or CI
baseline; warm-up rounds are validated but never included in reported timings.

## Programs

- `arithmetic.ae`: repeated integer arithmetic and a function call.
- `if_else.ae`: repeated nested conditional selection.
- `sum_to.ae`: loop-carried summation.
- `while_countdown.ae`: a longer countdown loop.
- `array_sum.ae`: indexed `Array<int>` traversal.
- `list_for_sum.ae`: `for` traversal over `List<int>`.
- `list_push.ae`: 256 appends with internal result validation and no loop output.
- `vector_dot.ae`: repeated row/column vector dot products.
- `matrix_mul.ae`: repeated matrix multiplication and indexing.
- `nested_loops.ae`: nested loop control flow.

Each file defines parameterless `main()`, performs no input or timed-loop
printing, validates its result internally, and returns a small controlled exit
code.
