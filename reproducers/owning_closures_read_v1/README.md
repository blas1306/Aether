# OWNING-CLOSURES-READ-V1 preflight reproducers

These inputs isolate the two source-level prerequisites without changing the
compiler.

From `compiler-next`:

```bash
cargo run -q -p aether-cli -- check ../reproducers/owning_closures_read_v1/automatic_copy_capture.ae
cargo run -q -p aether-cli -- check ../reproducers/owning_closures_read_v1/explicit_capture_clause.ae
```

Current PARTIAL implementation result: both reach semantic analysis and are
rejected with `E0359`. The explicit clause is now parsed and retained in AST;
the remaining shared failure is that the existing anonymous-function vertical
still analyzes its synthetic declaration outside the creator's lexical scope.
Neither reproducer is a functional PASS yet.

The ABI blocker has no executable producer/consumer reproducer in the current
pipeline. `CompilationSession` loads every reachable package source and
`LlvmTextBackend` emits one LLVM module. There is no compiler-produced package
interface/object metadata to corrupt or compare across two independently
compiled packages. This absence is the blocker described in
`docs/architecture/OWNING_CLOSURES_READ_V1_REPORT.md`.
