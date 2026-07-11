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
  IR O1 optimizer profile. `both` retains its original meaning: `ast` + `ir`.
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

## Programs

- `arithmetic.ae`: repeated integer arithmetic and a function call.
- `if_else.ae`: repeated nested conditional selection.
- `sum_to.ae`: loop-carried summation.
- `while_countdown.ae`: a longer countdown loop.
- `array_sum.ae`: indexed `Array<int>` traversal.
- `list_for_sum.ae`: `for` traversal over `List<int>`.
- `vector_dot.ae`: repeated row/column vector dot products.
- `matrix_mul.ae`: repeated matrix multiplication and indexing.
- `nested_loops.ae`: nested loop control flow.

Each file defines parameterless `main()`, performs no input or timed-loop
printing, validates its result internally, and returns a small controlled exit
code.
