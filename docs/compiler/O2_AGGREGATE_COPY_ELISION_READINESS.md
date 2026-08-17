# O2.11 aggregate copy-elision readiness

Status: analysis complete. Production behavior is frozen.

## Decision

`IMPROVE_COPY_ELISION_ANALYSIS_FIRST`.

Second best: `PROCEED_TO_OWNERSHIP_TRANSFER_ANALYSIS`.

O2.9.2 and O2.10 froze four sites as copy-induced/scalar-replacement
candidates. Reconciliation against lifecycle-expanded production O2 SSA shows
that none is an aggregate copy edge. Each is the single caller-side result of
`readControlLine`; there is no distinct source SSA value, destination SSA
value, materialization instruction, copy retain, or dead intermediate. The
legacy classification inferred a copy from “call result followed eventually
by release”. That is insufficient evidence for copy elision.

| ID | workload / function | legacy source | destination | definition | type | loop | owned fields | result |
|---|---|---|---|---|---|---:|---|---|
| ACE-001 | `examples/expense_tracker/Main.ae` / `decodeLedger` | callee owner, absent from caller SSA | `%336` | `body0:0` call | `ControlLineResult` | 1 | `line: String` | ownership blocked |
| ACE-002 | same | same | `%437` | `body1:0` call | `ControlLineResult` | 1 | `line: String` | ownership blocked |
| ACE-003 | same | same | `%516` | `body2:0` call | `ControlLineResult` | 2 | `line: String` | ownership blocked |
| ACE-004 | same | same | `%791` | `exit2:0` call | `ControlLineResult` | 1 | `line: String` | ownership blocked |

The deterministic JSON contains every destruction point and destination use.
All four are no-escape caller values, cross branches/joins and calls, and have
path-specific destruction. Their source lifetime is `SOURCE_LIFETIME_UNKNOWN`
because caller SSA has no separate source. Destination uniqueness is therefore
not a meaningful copy-edge fact. No exceptional edge crosses these lifetimes,
but their branch-dependent cleanup is still outside a first transfer scope.

## Canonical model and categories

Aggregate copy elision means removing an explicit `source -> destination`
value copy while transferring exactly one ownership responsibility. It is not
a source-language move, scalar replacement, ARC peephole, ABI rewrite, stack
promotion, or change to struct value semantics.

The analysis exposes the required categories: `SEMANTIC_COPY_REQUIRED`,
`OWNERSHIP_COPY_REQUIRED`, `RETURN_TEMPORARY_COPY`, `CALL_BOUNDARY_COPY`,
`LOCAL_TEMPORARY_COPY`, `RECONSTRUCTION_COPY`, `PHI_MERGE_COPY`,
`COLLECTION_STORAGE_COPY`, `METHOD_RESULT_COPY`, `CONSTRUCTOR_COPY`, and
`UNKNOWN`.

Four facts remain distinct:

1. aggregate SSA identity;
2. nested component provenance;
3. the source aggregate ownership edge;
4. the destination aggregate ownership edge.

Equal component roots do not prove a redundant copy. A transfer proof requires
one exact source edge, one destination edge that would acquire the same owner,
an immediately dead source, one semantic successor, no independent owner, and
exactly one final destruction. The reusable analysis-only API implements
classification, liveness, uniqueness, transfer, region, and profitability
queries. No production pass consumes it.

## Lifecycle, String, and ABI findings

Initial IR lifecycle operations are authoritative for value copies. Lifecycle
expansion acquires and releases owned nested fields; SSA and backend then carry
those obligations explicitly. `ControlLineResult` has four fields: owned
`String line`, scalar `LedgerStatus status`, `Int startOffset`, and `Int
nextOffset`.

The callee owns `line` before returning and the caller receives one owned
aggregate. At the four sites, caller SSA shows no duplicate retain and no
distinct source release; it only shows the releases needed for `%336`, `%437`,
`%516`, or `%791` on the applicable exit paths. Thus String immutability is
irrelevant: ownership remains significant, but there is no retain/release
handoff here to replace.

The return ABI already transports the result by value into the caller SSA
result. Current evidence is a wrapper/materialization naming issue rather than
a logical ownership copy or profitable physical copy. LLVM therefore has
nothing ownership-specific to remove at these four sites; classification is
`LLVM_ALREADY_COMPLETE`. No caller-side temporary is present. No callee-side
temporary was paired with a caller copy. A future return-transfer rule would
need a separately proven callee/caller ownership contract, not these sites.

## Other copy shapes

Local copies are the preferred eventual first class only when same-block,
straight-line, immediately dead, unique, exact, nonescaping, nonthrowing, and
ABI-invisible. The representative corpus currently supplies zero verified
instances under this definition.

`struct_set` is reconstruction, not a simple copy. Phi/join ownership is
path-sensitive. Pass-by-value call arguments may require an independent callee
value. Collection stores normally establish a container-owned value.
MethodResult wraps receiver/result ownership. Constructors include partial
initialization and rollback. All remain excluded. Multi-edge copy chains are
also excluded; the four frozen sites have chain length zero.

No candidate crosses invoke/catch/rethrow, but destruction is branch-dependent.
Future transfer must suppress source destruction and move responsibility to
the destination while retaining exactly one final release per owned component.
This milestone implements no such operation.

## Value and profitability

The four values are structurally hot (loop depths 1, 1, 2, 1) and overlap all
four O2.10 scalar-replacement candidates. However, each has zero aggregate copy
instructions, zero copy retains, zero dead intermediates, and zero proven ARC
reduction. Copy elision therefore does not currently solve their cost more
locally than scalar replacement; O2.10's overlap conclusion is rejected by
concrete SSA evidence.

The corpus census in the JSON counts aggregate origins and loop incidence. It
is deliberately not promoted into a copy census unless an explicit source and
destination edge exists.

## Exact next scope

Improve candidate discovery to recognize only explicit same-block `StructType`
copy edges. Require exact component provenance, one owned source edge, one
owned destination edge, immediate source death, unique destination, no branch,
call, exception, reconstruction, phi, MethodResult, constructor, collection
store, or ABI boundary. Expected current real candidates and ARC reduction are
both zero. A verifier must prove exactly one final release for each transferred
component before any transformation is enabled.

The machine-readable authority is
`o2_aggregate_copy_elision_readiness.json`. Regeneration is byte deterministic
at a fixed revision. Struct semantics, lifecycle expansion, ownership, ARC,
LocalARC, return/call ABI, code generation, constructors, MethodResult, and
O0/O1/O2 membership/output are unchanged.
