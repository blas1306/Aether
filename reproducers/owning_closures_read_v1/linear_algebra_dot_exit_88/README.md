# linearAlgebra `dot` exit-88 reproducer

This reproduces the first failing `dot` assertion from the current
`linearAlgebra/tests/consumer/src/main.ae`. The program prints the observed
result and retains the consumer's expected value and return code. On POSIX,
the shell observes `600 mod 256 = 88`.

From `compiler-next`:

```sh
cargo run -q -p aether-cli -- run \
  ../reproducers/owning_closures_read_v1/linear_algebra_dot_exit_88 -O0
cargo run -q -p aether-cli -- run \
  ../reproducers/owning_closures_read_v1/linear_algebra_dot_exit_88 -O2
```

The mathematically correct result is `7*4 + 8*5 + 9*6 = 122`, not `54`.
