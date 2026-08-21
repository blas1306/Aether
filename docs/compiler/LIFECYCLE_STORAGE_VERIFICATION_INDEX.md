# TEST-PERF-3.2 — Lifecycle Storage Verification Index

## Semantic audit

`IRVerifier._is_lifecycle_storage` previously classified a name by scanning only
the blocks and instructions of the supplied `IRFunction`. Membership is true
when an `IRStorage` with that name occurs as the destination, source, or value
of `IRInitDefault`, `IRCopyInit`, `IRMoveInit`, `IRAssign`, `IRDestroy`, or
`IRRelocate`.

Consequently:

- membership is a function-local property of the Initial IR and its canonical
  identity remains `(function object, storage name)`;
- instruction order and block reachability do not affect membership;
- lifecycle expansion is not required (and expansion replaces these
  instructions only after this verification stage);
- module-level declarations and lifecycle type metadata do not affect it;
- the verifier does not mutate the module, functions, blocks, instructions, or
  storage definitions while verifying, so definitions cannot appear or
  disappear during the pass.

The index is therefore constructed after function structure and storage types
have been collected, before reachable-value dataflow starts. It is a
`frozenset[str]` stored under the exact function object's identity in the
verifier instance. It is cleared at the start of every `verify()` call and
cannot outlive or be reused for another verification unit.

## Complexity and structural evidence

For `Q` membership queries over `N` instructions, the former predicate was
approximately `O(Q*N)`. Construction is now `O(N)`, followed by average `O(1)`
set membership for each query, for `O(N + Q)` overall.

The regression tests retain the old scan as a test-only reference and compare
it with the index across all six lifecycle instruction categories,
non-lifecycle names, and identical storage spelling in different functions.
A large branching CFG separately proves that queries grow while index builds
remain exactly one per verified function; no wall-clock threshold is used.

## Focused measurements

Measurements below are local and observational, not CI requirements. The
before values are the TEST-PERF-3.1 measurements on the same workload shape.

| Measurement | Before | After |
|---|---:|---:|
| `expense_tracker/Main.ae` lifecycle queries | 17,709 | 17,709 |
| lifecycle full scans / index builds | 17,709 | 26 |
| focused Initial IR verification | 87.79–90.81 s | 0.074 s |
| full 26-workload, 78-profile Initial IR verification | 450.05 s | 0.209 s |
| full regeneration pre-LLVM | 537.51 s | 8.137 s |
| `expense_tracker/Main.ae` O2 pre-LLVM | 242.87 s | 5.616 s |
| small `sumTo.ae` O0 pre-LLVM | 0.011 s profiled baseline | 0.0067 s |

The after regeneration covered the same 30 manifest entries, 26 supported
workloads, and 78 O0/O1/O2 records. O0/O1/O2 still independently reconstruct
Initial IR and base SSA; this milestone does not alter that boundary.
