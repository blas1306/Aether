# RUST-3.1f lifecycle differential qualification

Decision: `RUST_LIFECYCLE_DIFFERENTIAL_QUALIFIED`

The original gate had 20 failing programs out of 116. Classification by the
first semantic root cause (not merely by file) produced four clusters:

| Root cause | Programs | Policy rule |
|---|---:|---|
| Aggregate field ownership acquisition/transfer | 15 | Destructible borrowed fields are retained; owned temporaries are consumed; unused owned aggregate results are released. |
| Owning versus borrowed `class_get` projection | 2 | A destructible `class_get` result is an owned temporary and receives a retain. |
| Last-use/consumer disposition | 2 | Remaining-use census releases owned temporaries at consuming or final uses. |
| Interface carrier ownership acquisition | 1 | Borrowed class carriers are retained; owned carriers transfer; struct carriers follow aggregate ownership. |

The implementation now derives a whole-function owned-result, operand-use and
remaining-use census, then applies ownership through the lifecycle primitives:
aggregate construction/update, projections, calls, collection consumers,
printing, comparisons, copy/move/assignment/destruction and return transfer.
Nested default construction also allocates generated names in policy order.

Final gates:

- lifecycle semantic parity: **116/116**;
- post-lifecycle canonical SSA parity: **106/116** (the 10 remaining cases are
  preserved for the next SSA milestone);
- Rust verifier plus Python schema-v2 import: **116/116**;
- concrete Rust determinism: **116/116**;
- Python exact reserialization: **106/116**.

All 10 reserialization failures lose an instruction `source_location` when a
Rust schema-v2 DTO is imported and emitted through the Python codec. This is
actual round-trip metadata loss, not byte ordering and not lifecycle semantic
inequality. The affected program set happens to equal the remaining SSA set;
the first round-trip divergence in every case is `source_location: object ->
null`.

Adversarial coverage includes owning and borrowed class projections, aggregate
and interface acquisition, recursive/nested aggregates, copy, move, assign,
destroy, last and repeated uses, branches, loops, return transfer,
`transferred_storage`, and normal/exceptional constructor continuations. The
focused Rust lifecycle tests and the frozen policy adversarial tests pass.

No lifecycle or SSA policy, Initial-IR/SSA schema, verifier semantics, Python
lowering authority, or RP3 behavior was changed. No commit was created.
