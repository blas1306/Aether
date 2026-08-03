# Exception promotion corpus

This is the canonical public corpus for exception release qualification. It is
not a language-profile declaration: `ERROR_HANDLING` remains unsupported in
the stable native capability profile. Positive programs are executed through
the frontend, verified Initial IR, verified SSA, and private event-out native
backend. Negative programs are rejected at their declared frontend phase.

[`catalog.json`](catalog.json) is the exhaustive machine-readable inventory and
oracle. Run it with:

```bash
PYTHONPATH=src .venv/bin/python scripts/check_exception_promotion.py
```
