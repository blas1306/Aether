# Exception promotion corpus

This is the canonical public corpus for exception release qualification and
stable-route evidence. `ERROR_HANDLING` is `COMPLETE` in native capability
profile 24 on Linux x86_64. Positive programs are executed through
the frontend, verified Initial IR, verified SSA, and private event-out native
backend. Negative programs are rejected at their declared frontend phase.

[`catalog.json`](catalog.json) is the exhaustive machine-readable inventory and
oracle. Run it with:

```bash
PYTHONPATH=src .venv/bin/python scripts/check_exception_promotion.py
```
