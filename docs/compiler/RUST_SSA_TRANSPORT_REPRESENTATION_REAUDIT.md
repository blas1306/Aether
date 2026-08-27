# Transport and representation reaudit — RUST-3.15

Decision: `RUST_SSA_TRANSPORT_REPRESENTATION_REAUDITED_NO_MATERIAL_SAFE_OPTIMIZATION`

Baseline: post-RUST-3.14 worktree at `7500d66a0d830542d2436b22356e0c34698f076f`.

## Outcome

This milestone is an observational audit only. It changes no production source, authority, mandatory synchronous Python shadow, fail-closed behavior, schema, protocol-v1, schema-v2 semantics, importer validation, verifier, lifecycle, SSA, canonical comparison, optimizer/backend, or rollback mode.

RUST-3.14 attributed **17.60%** of ordinary dual-lane wall time to transport/representation implementation after excluding the **14.83%** schema-v2 importer safety boundary. The reaudit finds **0.00% proven removable**, **7.85% protocol-inherent**, **8.26% safety/comparison-associated**, and **1.49% uncertain**. The four buckets reconcile to the 17.60% surface.

The maximum plausible low-risk speedup is **1.50% of dual-lane wall time**; it is an upper bound for an unproven fusion of Python comparison DTO creation/canonicalization, not demonstrated removable time. RUST-3.16 is therefore not justified for representation work.

## Complete representation flow

| From | To | Walk | Alloc | Copy | JSON | Validate | Trust | Consumer | Reused | Equivalent | Class |
|---|---|:---:|:---:|:---:|:---:|:---:|:---:|---|:---:|:---:|---|
| verified IRModule | request schema-v1 dict/list DTO | yes | yes | no | no | no | no | JSON encoder; later integrity equality | yes | no | `PROTOCOL_INHERENT` |
| request schema-v1 DTO | compact UTF-8 JSON bytes | yes | yes | no | yes | no | yes | length-frame writer | no | no | `PROTOCOL_INHERENT` |
| request JSON bytes | length-prefixed request frame | no | yes | no | no | no | yes | Rust companion stdin | no | no | `PROTOCOL_INHERENT` |
| request frame | Rust request byte buffer | no | yes | no | no | yes | yes | serde_json parser | no | no | `PROTOCOL_INHERENT` |
| Rust request bytes | typed Initial IR DTO | yes | yes | no | yes | yes | yes | lifecycle normalization/lowering | no | no | `SAFETY_BOUNDARY` |
| typed Initial IR DTO | Rust normalized and Owned SSA | yes | yes | no | no | yes | no | Rust verifier and schema materializer | yes | no | `SAFETY_BOUNDARY` |
| Rust Owned SSA | typed schema-v2 response DTO | yes | yes | no | no | no | no | serde serializer | no | no | `PROTOCOL_INHERENT` |
| typed response DTO | compact UTF-8 JSON response bytes | yes | yes | no | yes | no | yes | length-frame writer | no | no | `PROTOCOL_INHERENT` |
| response JSON frame | Python bytes | no | yes | no | no | yes | yes | json.loads | no | no | `PROTOCOL_INHERENT` |
| response JSON bytes | schema-v2 raw dict/list tree | yes | yes | no | yes | yes | yes | strict importer and Rust-result canonicalizer | yes | no | `SAFETY_BOUNDARY` |
| schema-v2 raw tree | Python imported SSA objects | yes | yes | no | no | yes | yes | independent verifier and authority return | yes | no | `SAFETY_BOUNDARY` |
| Python imported SSA objects | verified imported SSA objects | yes | no | no | no | yes | yes | authoritative pipeline | no | yes | `SAFETY_BOUNDARY` |
| verified input IRModule | independent Python shadow SSA | yes | yes | no | no | yes | no | comparison DTO builder | no | no | `SHADOW_POLICY` |
| Python shadow SSA | schema-v2 comparison DTO | yes | yes | no | no | yes | no | owned in-place canonicalizer | no | no | `CANONICAL_COMPARISON_REQUIRED` |
| Python comparison DTO | Python canonical DTO | yes | no | no | no | no | no | canonical comparator | no | no | `CANONICAL_COMPARISON_REQUIRED` |
| Rust raw response DTO | Rust canonical DTO deep clone | yes | yes | yes | no | no | no | canonical comparator | no | no | `CANONICAL_COMPARISON_REQUIRED` |
| two canonical DTOs | first structural difference or equality | yes | no | no | no | yes | yes | fail-closed authority decision | no | no | `CANONICAL_COMPARISON_REQUIRED` |
| verified input IRModule | fresh schema-v1 DTO for integrity comparison | yes | yes | no | no | yes | yes | same-input fail-closed check | no | yes | `SAFETY_BOUNDARY` |

Every row has exactly one requested classification. The apparent reusable cases are historical `SAFE_IMMUTABLE_REUSE` wins represented by the source-regression inventory, not remaining candidates. The input snapshot integrity traversal and strict importer are safety boundaries, while both canonical forms and the Python comparison DTO are required by the frozen comparison contract.

## Explicit candidate audit

| Candidate | Classification | Finding |
|---|---|---|
| request dict/list tree built immediately before JSON | `PROTOCOL_INHERENT` | one-use representation, but required by the frozen generic JSON encoder; no direct encoder was proven |
| typed Initial IR DTO materialized by serde | `SAFETY_BOUNDARY` | direct typed parse validates and feeds Rust lowering; no serde_json::Value intermediate exists |
| defensive copies of invocation-local request or result | `NOT_MATERIAL` | no additional defensive copy was found outside canonical isolation |
| repeated serialization of Rust result | `SAFE_IMMUTABLE_REUSE` | the received raw schema-v2 mapping is already reused for import and comparison |
| object to dict to JSON to dict to object | `PROTOCOL_INHERENT` | the remaining chain is the frozen JSON protocol plus strict importer |
| canonicalization after adjacent traversal | `CANONICAL_COMPARISON_REQUIRED` | canonical traversal creates comparison-normal form; a fused direct builder is unproven |
| Python shadow comparison DTO creation | `CANONICAL_COMPARISON_REQUIRED` | the canonical comparator consumes this sole exact schema-v2 representation |
| repeated name and type conversion | `INSUFFICIENT_EVIDENCE` | calls are visible in importer profiles but no reusable typed object crosses the trust boundary |
| Rust response typed DTO plus serde_json::Value | `PROVEN_REDUNDANT_REPRESENTATION` | removed in RUST-3.9a and still absent; direct typed response serialization remains |
| JSON canonicalization round trip | `PROVEN_REDUNDANT_TRAVERSAL` | removed in RUST-3.9a and still absent |
| Rust-result Python object reserialization | `SAFE_IMMUTABLE_REUSE` | removed in RUST-3.8a and still absent through raw response reuse |
| Python Initial IR reconstruction | `SAFE_IMMUTABLE_REUSE` | removed in RUST-3.8a and still absent through verified module reuse |

## Top ordinary transitions by RUST-3.14 wall share

| Transition/phase | Dual share | Classification |
|---|---:|---|
| `rust_schema_v2_import` | 14.83% | `SAFETY_BOUNDARY` |
| `python_result_dto_serialization` | 8.26% | `CANONICAL_COMPARISON_REQUIRED` |
| `initial_ir_snapshot_preparation` | 3.47% | `PROTOCOL_INHERENT` |
| `response_json_decode` | 1.92% | `PROTOCOL_INHERENT` |
| `rust_input_parsing` | 1.49% | `INSUFFICIENT_EVIDENCE` |
| `rust_transport_serialization` | 1.47% | `PROTOCOL_INHERENT` |
| `request_response_transport_and_serialization` | 0.86% | `PROTOCOL_INHERENT` |
| `rust_schema_v2_materialization` | 0.14% | `PROTOCOL_INHERENT` |
| `companion_process_startup` | 0.00% | `NOT_MATERIAL` |

The table is additive and excludes no measured transport phase; schema-v2 import is shown but kept outside the 17.60% implementation question.

## Request/response volume and traversal census

| Workload | Functions | Blocks | Instructions | Values | Request bytes | Response bytes | Request containers | Response containers | Full-tree traversals |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| tiny_scalar | 2 | 7 | 52 | 39 | 8883 | 5691 | 292 | 178 | 15 |
| numeric_iterative | 1 | 9 | 47 | 30 | 7195 | 5351 | 237 | 170 | 15 |
| collection_heavy | 1 | 10 | 59 | 39 | 9273 | 7090 | 308 | 225 | 15 |
| struct_heavy | 2 | 2 | 53 | 43 | 10383 | 7173 | 310 | 207 | 15 |
| class_interface_heavy | 3 | 3 | 28 | 20 | 6153 | 5034 | 171 | 119 | 15 |
| indirect_call | 4 | 13 | 35 | 22 | 7049 | 7348 | 210 | 201 | 15 |
| exception_lifecycle | 4 | 17 | 58 | 34 | 10959 | 12183 | 314 | 321 | 15 |
| realistic_medium | 26 | 475 | 4203 | 2291 | 974990 | 779893 | 20845 | 16359 | 15 |

The ordinary audit retains raw timing samples, median/min/max, exact byte sizes, approximate container/object counts, and a static count of whole-tree transitions. Counts are diagnostic estimates, not heap allocation claims.

## Request, Rust, Python response, and comparison decomposition

The additive samples separate request DTO creation, request JSON encoding, frame construction/write, all existing Rust compute phases, response decode/raw construction, strict import, imported verification, Python shadow construction, comparison DTO creation, both canonicalizations, comparison, and the integrity traversal. `transport_wait_residual_including_rust_response_json_and_frame` intentionally groups Rust frame read, response JSON serialization, Rust frame write, IPC scheduling, and Python frame read: the existing diagnostic protocol cannot split them without modifying production instrumentation. It is never added on top of the enclosing wait, so there is no double-count.

## Schema-v2 importer decomposition

The strict importer remains a separate 14.83% safety boundary. Isolated cProfile probes partition exclusive Python self-time into raw traversal/validation, type and nominal reconstruction, object/container allocation, metadata reconstruction, and an explicit unattributed bucket. The buckets do not overlap; absolute profiled times are not mixed into wall accounting.

| Workload | Raw/validation | Type/nominal | Allocation | Metadata | Unattributed |
|---|---:|---:|---:|---:|---:|
| tiny_scalar | 24.96% | 43.96% | 11.20% | 0.15% | 19.74% |
| numeric_iterative | 24.91% | 43.18% | 11.46% | 0.06% | 20.40% |
| collection_heavy | 25.04% | 43.98% | 11.02% | 0.18% | 19.78% |
| struct_heavy | 23.86% | 44.92% | 11.67% | 0.03% | 19.52% |
| class_interface_heavy | 21.97% | 46.94% | 11.34% | 0.08% | 19.67% |
| indirect_call | 22.31% | 46.39% | 10.76% | 0.29% | 20.25% |
| exception_lifecycle | 22.35% | 44.65% | 12.65% | 0.39% | 19.97% |
| realistic_medium | 25.95% | 40.05% | 14.22% | 0.48% | 19.29% |
| deep_100 | 24.50% | 40.46% | 12.95% | 0.00% | 22.10% |
| deep_1000 | 24.76% | 40.47% | 13.10% | 0.00% | 21.66% |
| deep_5000 | 26.51% | 39.16% | 13.07% | 0.00% | 21.27% |
| deep_10000 | 34.15% | 34.85% | 11.78% | 0.00% | 19.23% |

This supports internal importer investigation only; it does not support bypassing raw traversal, validation, nominal reconstruction, allocation, or metadata reconstruction.

## Ordinary versus deep CFG

| Blocks | Median audited wall | Median transport/representation | Request bytes | Response bytes | Bytes/block |
|---:|---:|---:|---:|---:|---:|
| 100 | 0.020000s | 0.001894s | 31291 | 17863 | 491.5 |
| 1000 | 0.191934s | 0.017752s | 317489 | 176277 | 493.8 |
| 5000 | 1.177566s | 0.091902s | 1609486 | 896286 | 501.2 |
| 10000 | 2.710530s | 0.174840s | 3224487 | 1796293 | 502.1 |

The 100→10,000 endpoint transport-time growth is 92.31×; the closest endpoint volume proxy is `blocks`. This is descriptive only. Timing alone is not used to assert formal complexity. Byte, instruction, block, value, and phase samples are retained so anomalous growth can be re-evaluated without hardware thresholds.

## Candidate ranking

| Rank | Candidate | Share | Maximum plausible upside | Risk | Complexity | Trust impact | Qualification |
|---:|---|---:|---|---|---|---|---|
| 1 | remaining representation redundancy | 0.00% | at most 1.50% unproven canonical fusion | medium | high | none if exact | very high |
| 2 | schema-v2 importer internal efficiency | 14.83% | bounded below 14.83%; validation and construction remain | high | high | direct | very high |
| 3 | Python shadow DTO creation | 8.26% | only traversal fusion, not DTO elimination | medium | medium | canonical equality | high |
| 4 | canonicalization | 4.53% | at most Python canonical traversal 1.50% absent a proven fused serializer | medium | high | direct | very high |
| 5 | JSON protocol itself | 5.74% | outside frozen protocol | high | very high | protocol replacement | promotion-level |
| 6 | verifier architecture | 23.63% | none without separate safety work | high | very high | direct | very high |
| 7 | policy/shadow evolution | 33.26% | large but outside optimization policy | very high | very high | removes independence | promotion-level |

## Decision

No major transition is both proven redundant and safely removable under the freeze. JSON DTO construction/parsing and framing are protocol-inherent; input integrity and schema import are safety boundaries; the shadow DTO and both canonical forms serve the required exact comparison. A direct canonical DTO builder might fuse part of one traversal, but no audit measurement proves how much DTO construction it removes, so it remains `INSUFFICIENT_EVIDENCE` and below the materiality bar.

Decision: **RUST_SSA_TRANSPORT_REPRESENTATION_REAUDITED_NO_MATERIAL_SAFE_OPTIMIZATION**.

Recommendation: stop transport/representation optimization work. If work continues, use a separate importer-internal characterization that preserves full validation; do not open RUST-3.16 as a representation optimization from this evidence.

## Method and gates

The release companion was warmed 2 times and measured for 15 ordinary and 7 deep rounds. Raw samples, median/min/max, and the persistent process counts are retained. There are no hardware-dependent thresholds.

- `rust_3_15_checker`: PASS
- `focused_tests`: PASS
- `historical_116_of_116`: PASS
- `adversarial`: PASS
- `deep_cfg`: PASS
- `production_stabilization_regressions`: PASS
- `rust_3_8a_through_3_14_contracts`: PASS
- `full_python_suite`: PASS
- `cargo_test_workspace_locked`: PASS
- `cargo_fmt_check`: PASS
- `git_diff_check`: PASS

Production unchanged: yes. No production file is part of RUST-3.15. No commit was created.
