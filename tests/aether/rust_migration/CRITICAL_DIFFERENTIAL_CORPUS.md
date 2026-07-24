# Phase 4.5A critical differential corpus

## Result

The focused corpus covers all 13 Phase 4.5A blockers with 13 distinct,
schema-v1-transportable requests. Python and Rust reject every case with the
same invariant ID. Shadow comparison classifies every case as
`MATCH_REJECTED_SEMANTIC`: the invariant and category match, while Python's
normalized failure intentionally lacks the structural context supplied by
Rust. Exact comparison is therefore unavailable without changing
normalization, and no expectation was weakened for convenience.

| Family | Fixture | Expected invariant | Expected classification | Secondary invariants |
| --- | --- | --- | --- | --- |
| `ssa/` | `critical-ssa-duplicate-value` | IRV-009 | `MATCH_REJECTED_SEMANTIC` | — |
| `storage/` | `critical-storage-inconsistent-slot-type` | IRV-010 | `MATCH_REJECTED_SEMANTIC` | — |
| `ssa/` | `critical-ssa-invalid-declared-type` | IRV-011 | `MATCH_REJECTED_SEMANTIC` | — |
| `borrow/` | `critical-borrow-owning-store-without-retain` | IRV-040 | `MATCH_REJECTED_SEMANTIC` | IRV-037, IRV-038 |
| `borrow/` | `critical-borrow-mutation-receiver` | IRV-042 | `MATCH_REJECTED_SEMANTIC` | IRV-037, IRV-038 |
| `builtins/` | `critical-builtins-read-result-layout` | IRV-063 | `MATCH_REJECTED_SEMANTIC` | IRV-062 |
| `builtins/` | `critical-builtins-retain-scalar` | IRV-066 | `MATCH_REJECTED_SEMANTIC` | — |
| `builtins/` | `critical-builtins-scalar-alias` | IRV-067 | `MATCH_REJECTED_SEMANTIC` | — |
| `ssa/` | `critical-ssa-aggregate-compare-shape` | IRV-075 | `MATCH_REJECTED_SEMANTIC` | — |
| `structs/` | `critical-structs-incomplete-construction` | IRV-079 | `MATCH_REJECTED_SEMANTIC` | — |
| `structs/` | `critical-structs-field-read-result` | IRV-080 | `MATCH_REJECTED_SEMANTIC` | — |
| `structs/` | `critical-structs-field-update-value` | IRV-081 | `MATCH_REJECTED_SEMANTIC` | — |
| `method_result/` | `critical-method-result-missing-value` | IRV-082 | `MATCH_REJECTED_SEMANTIC` | — |

## Reuse and duplication

Five cases reuse existing focused materializers:

- IRV-040 and IRV-042 reuse the borrow-verifier modules;
- IRV-066 and IRV-067 reuse `_builtin_call_module`; and
- IRV-075 reuses the aggregate-metadata `_verify` builder.

The other eight cases share one single-block module helper, one canonical
`Pair` definition, and one normalized-rejection assertion. No DTO snapshot,
subprocess request, or malformed module is copied into the migration fixture
directory. This preserves the existing corpus contract: pytest owns each
module shape, and the manifest indexes the one selected verifier invocation.

## Determinism and authority

The focused integration test serializes every case twice, asserts protocol
version 1 and IR schema version 1, executes each request twice through the
subprocess verifier and shadow coordinator, and checks identical request
hashes and semantic snapshots. It also asserts that all 13 hashes are distinct.

Python remains authoritative. Rust is observational, Python verification is
still executed and returned or re-raised, and this corpus adds no rollout,
fallback, protocol, DTO, verifier, PyO3, or compiler-pipeline behavior.
