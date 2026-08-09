# Exception release baseline remediation

This note records the baseline repair performed before rerunning Exception
Release Qualification v2. It is not Qualification v2 evidence.

## Numeric observations

Canonical native observations were collected from current source by emitting
LLVM and compiling it with clang at O0, O1, and O2. All three levels agreed.

- `examples/ProbandoNR/probandoNR2.ae`: exit 0; stdout
  `x = 0.567143290409784\nres = 2.22044604925031e-16\niter = 5\n`;
  stderr empty; stdout SHA-256
  `0dcb8ae02b60898d165254901b40e4d19ef4b334b0b6e2aef25f3f4f6bec09d6`.
- `examples/ProbandoNR/probandoNR3.ae`: exit 0; stdout
  `268446292.68508\n`; stderr empty; stdout SHA-256
  `34a1022fe64062666a9c435f02b3075fa20015676376fe1ebc8d63af695f2498`.
- Both empty stderr observations hash to
  `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`.

The previous manifest stdout hashes were stale. The full million-iteration NR3
workload remains a native release observation. Its catalog entry excludes AST
parity because interpreting that performance workload is not a useful smoke
contract.

## LeakSanitizer environment

The Codex sandbox runs under ptrace restrictions that make LeakSanitizer abort.
Sanitizer tests remain enabled and unchanged; a sandbox LSan abort is not a pass
or valid release evidence. Run these exact commands in a normal local or CI
environment outside ptrace to collect current evidence:

```bash
PYTHONPATH=src .venv/bin/python -m pytest -q tests/aether/test_native_exceptions.py
PYTHONPATH=src .venv/bin/python scripts/check_exception_promotion.py
```

The commands retain `ASAN_OPTIONS=detect_leaks=1` in their existing harnesses,
so ASan, UBSan, and LSan remain fail-closed.
