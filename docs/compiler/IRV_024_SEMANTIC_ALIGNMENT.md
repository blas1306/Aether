# IRV-024 Semantic Alignment — Phase 4.5C

## Decision

IRV-024 is an entry-reachable control-flow graph property:

- every reachable exit of a non-void function is a return carrying a value;
- a reachable cycle is non-exiting and is not a missing return;
- unreachable regions do not create a return-path obligation; and
- non-entry block names have no semantic meaning.

Rust already implemented this contract with a visited-set graph traversal.
Python's historical recursive approximation recognized a revisited block as a
cycle only when its name began with `cond` or `for.cond`. Isomorphic CFGs could
therefore receive different outcomes after arbitrary renaming. IR v1 specifies
no such naming convention, so Phase 4.5C selects Rust's behavior as the
specification reference and aligns Python.

This is a specification alignment, not preservation of historical
implementation compatibility. The old behavior is retained in the migration
documents and retired rule hash, rather than silently erased.

## Implementation boundary

Python's `_verify_all_non_void_paths_return` now walks successors from `entry`
with a visited set. A LIFO worklist retains true-before-false deterministic
traversal. It has no cases for `cond`, `for.cond`, or other label spelling.

The verifier pipeline and ordering remain unchanged. IRV-025 still checks
return operand presence and exact type, structural verification still forbids
implicit fallthrough, and retained unreachable blocks still receive their
independent IRV-022 local instruction/type checks. IRV-024 itself ignores
unreachable regions exactly as the Rust return pass does.

Regression coverage includes graph-isomorphic lowering-shaped while and for
CFGs, arbitrary accepted and rejected renamings, an entry self-loop, pure and
optional-return cycles under several names, a cycle with a valued exit,
reachable valueless returns, finite missing-return exits, and unreachable
cycles. Existing compiler suites continue to cover ordinary conditionals,
while and for lowering, nested loops, recursive control flow, unreachable
regions, infinite loops, and finite exits.

## Corpus and shadow policy

The existing `non-void-path-without-return` case remains as the canonical
schema-v1 transport. It moved from the invalid manifest list to the valid list
and now classifies `MATCH_ACCEPTED`. Its canonical DTO transport, subprocess
execution, shadow comparison, request hashing, and semantic snapshot remain
active.

The former `intentional_irv_024_graph_analysis` outcome expectation and the
exact shadow rule for request hash
`d635f6fc4c9e933e20442539c12409fcdc3de3da0938927f6b784c3002550baa`
were removed from executable policy. The hash remains recorded here and in the
Phase 4.3 document as history. Three unrelated documented diagnostic
divergences remain unchanged; no documented outcome divergence remains.

## Authority

Phase 4.5C changes neither authority selection nor rollout state. The single
internal configuration remains Python authority with Rust shadow. Python
continues to determine compiler acceptance, diagnostics, and exit behavior.
Rust remains observational, comparison and reporting remain active, and there
is no fallback, rollout, environment policy, PyO3 binding, or Python-code
removal.

## Validation record

The Phase 4.5C validation completed with:

- 143 migration modules materialized, with 65 Python acceptances and 78 Python
  rejections;
- all 141 schema-v1-transportable cases exercised through the real Rust
  subprocess and shadow coordinator;
- 65 `MATCH_ACCEPTED`, 73 exact first-invariant rejection matches, three
  unchanged documented diagnostic divergences, zero documented outcome
  divergences, and zero unexpected divergences;
- deterministic canonical request hashing and semantic snapshots for the
  aligned IRV-024 transport;
- focused characterization, critical differential, authority-pipeline,
  compiler-control-flow, example, and benchmark suites passing; and
- `cargo fmt`, `cargo check`, `cargo test`, `cargo clippy -D warnings`, and
  `git diff --check` passing.
