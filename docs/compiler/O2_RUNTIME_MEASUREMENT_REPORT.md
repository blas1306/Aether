# O2 runtime measurement report

O2.13 keeps noisy timing out of `o2_measurement_baseline.json`. Collect a small
representative subset with:

```bash
.venv/bin/python scripts/o2_measurement.py --mode runtime --runtime-limit 3
```

Use `--mode full` for static and runtime artifacts together. Runtime JSON is
machine-local evidence: it records Python/platform basics, warmups, repeated
wall/user/system samples, median, minimum, spread, commands, workload size,
executable size and output hashes. A row has timings only when O0/O1/O2 exit code, stdout and stderr
are identical. Very short results should be classified as noise-dominated;
increase harness repetitions instead of changing public example semantics.

No checked-in timing is claimed to be portable or byte-for-byte reproducible.
O1→O2 speed differences must not be attributed to Aether without separating
the Aether SSA delta from clang `-O1`→`-O2`; O2.13 reports correlation only and
never claims a causal speedup for an unimplemented transformation.
