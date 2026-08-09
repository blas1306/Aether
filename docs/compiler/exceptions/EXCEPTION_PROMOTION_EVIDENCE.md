# ERQ-006 exception promotion evidence

> Classification: **Release evidence**  
> Scope: stable-route correctness evidence for the profile-24 promotion. It
> does not define a public ABI or FFI surface.

## Result

The canonical [exception corpus](../../../corpus/exceptions/catalog.json)
contains 11 positive and 9 negative programs. Every positive program is
checked at the frontend and executed by the frontend interpreter, verified
Initial IR, optimized verified Initial IR, verified SSA, optimized verified
SSA, and the private event-out native backend at clang O0/O1/O2. The generated
[differential report](EXCEPTION_PROMOTION_DIFFERENTIAL_REPORT.json) records the
byte-exact observations and selected handlers. Every negative program is
rejected with an exact diagnostic class, message, line, and column.

Coverage includes throw and bare rethrow; typed, ordered, root, nested, and
unmatched catches; function, method, recursive, interface, and indirect
propagation; struct and class errors; constructors and constructor failure;
`Error.message()`; root reporting and panic separation; cleanup, ARC, and
nested owned Array/List payloads; and rethrow chains. The catalog is exhaustive
over the corpus and maps every requirement to at least one small source file.

## Validation method

The release check parses and typechecks each source once, verifies Initial IR
and SSA before execution, runs both optimizer pipelines with verification, and
compares stdout, stderr, handler markers, termination class, message, exit
status, cleanup disposition, and ownership disposition for every stage. Native
O0 runs tagged ownership cases under ASan, UBSan, and leak detection; verified
lifecycle/event linearity supplies the structural ownership evidence at IR and
SSA. Any mismatch names the case, stage, field, expected value, and actual
value.

The same check proves that every positive case requires the promoted
`ERROR_HANDLING` capability and is admitted by the stable native route, every
negative diagnostic remains exact, all
documentation references resolve, and every `.ae` file is cataloged. Run:

```bash
PYTHONPATH=src .venv/bin/python scripts/check_exception_promotion.py
```

## Availability and limitations

`ERROR_HANDLING` is **COMPLETE** in native capability profile 24. The stable CLI
uses the qualified event-out route after verified SSA; the gate rejects any
regression back to a capability diagnostic or non-stable execution path.

Native execution evidence is limited to the supported Linux x86_64/clang
environment. Sanitizer instrumentation is applied at O0 to the ownership-tagged
subset, while all corpus cases still run natively at O0/O1/O2. The frontend
interpreter is the semantic oracle; canonical ownership proof comes from
lifecycle/SSA verification and native sanitizers rather than Python host memory
accounting.

Features excluded by the accepted exception design remain unsupported and are
not blockers for this evidence: `finally`, exception hierarchies, checked or
resumable exceptions, arbitrary thrown values, raw-C unwinding, and public
exception ABI/FFI. No remaining implementation blocker is claimed by ERQ-006;
the completed promotion does not broaden any of those exclusions.
