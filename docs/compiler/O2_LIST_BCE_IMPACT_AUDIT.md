# O2.5.5 List BCE impact audit

This is a read-only audit at revision `5f4b2f3`. The historical O2.1.5 file and
JSON were not regenerated or changed. The current report is
`docs/compiler/o2_list_bce_impact.json`; regenerate it with
`PYTHONPATH=src python scripts/o2_impact_audit.py --output docs/compiler/o2_list_bce_impact.json`.

## Coverage and attribution

The identical 16-workload corpus contains five List checks before BCE.

| State | Total | Safe | Unsafe | Unknown | Safe |
|---|---:|---:|---:|---:|---:|
| O2.1.5 baseline | 5 | 0 | 0 | 5 | 0% |
| O2.5 current | 5 | 4 | 0 | 1 | 80% |

The four `UNKNOWN -> PROVEN_SAFE` changes comprise two improved local length
provenance sites (`list_index` and the aliased `list_set`), one summarized
nonmodifying direct-call site, and one no-alias mutation-preservation site.
There were no gains attributed to branch/loop precision, interface summaries,
or other causes.

The sole remaining unknown is the hot, nested `for value in values` check in
`benchmarks/list_for_sum.ae`: `UNKNOWN_LENGTH`/unsupported length relation. It
is not caused by mutation. In the required blocker vocabulary this is
`unsupported range/length relation` (1); MAY_ALIAS, PARAMETER_ALIAS, indirect
call, interface call, join loss, same-List mutation, exception edge, and other
are all zero in this corpus. It ranks high because it executes in a nested
loop. Of the four removals, all are one-shot/cold example code; no measured
hot-loop removal occurred. These labels are static loop-frequency proxies, not
runtime-frequency claims.

The workload mix includes List traversal and mutation, numerical and nested
loops, Array/Vector/Matrix dogfood, and direct-call alias examples. The corpus
has no List-bearing class/interface or helper-inside-List-loop check; this is a
coverage gap, not evidence that those cases optimize.

## O1/O2 and benchmark evidence

SSA inventory is 5 checked List accesses in O1 versus 1 in O2: four removed,
one preserved. LLVM inspection agrees: eliminated accesses no longer emit the
List index-check helper; the preserved traversal still does. This count is
from SSA/LLVM, not program output.

A local 10-run native sample of the real `list_for_sum` workload measured O1
at 0.476 ms/run and O2 at 0.459 ms/run (builds: 63.969 and 68.548 ms/run).
The difference is below what this startup-dominated harness can establish and
the relevant hot check was preserved, so no speedup is claimed. LLVM and
object sizes are effectively unchanged for this preserved-check case. The
five semantic scenarios requested by the milestone are covered structurally
by List BCE tests (simple fresh List, unrelated fresh mutation, read-only
direct call, opaque/modifying call, and same-List mutation); only the first
three remove checks. They are SSA unit cases, so fabricating native runtime,
LLVM-size, or object-size figures for them would be misleading.

## Conclusion

O2.5 materially improves proof coverage in the historical sample, but its
measured removals are cold. The remaining practical BCE priority is recovering
the stable List length relation for lowered `for-each` loops. No production
behavior or optimizer membership changed in this audit.
