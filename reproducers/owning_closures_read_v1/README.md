# OWNING-CLOSURES-READ-V1 preflight reproducers

These inputs isolate the two source-level prerequisites without changing the
compiler.

From `compiler-next`:

```bash
cargo run -q -p aether-cli -- check ../reproducers/owning_closures_read_v1/automatic_copy_capture.ae
cargo run -q -p aether-cli -- check ../reproducers/owning_closures_read_v1/explicit_capture_clause.ae
```

The first reaches semantic analysis and is rejected with `E0359`: the existing
anonymous-function vertical deliberately analyzes its synthetic declaration
outside the creator's lexical scope. The second is rejected by the parser
because `capture(...)` is not part of the current lambda grammar.

The ABI blocker has no executable producer/consumer reproducer in the current
pipeline. `CompilationSession` loads every reachable package source and
`LlvmTextBackend` emits one LLVM module. There is no compiler-produced package
interface/object metadata to corrupt or compare across two independently
compiled packages. This absence is the blocker described in
`docs/architecture/OWNING_CLOSURES_READ_V1_REPORT.md`.
