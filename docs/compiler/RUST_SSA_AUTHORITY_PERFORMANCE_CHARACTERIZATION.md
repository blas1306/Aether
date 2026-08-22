# Rust SSA authority performance characterization — RUST-3.7b

Decision: `RUST_SSA_PERFORMANCE_CHARACTERIZED`

## Result

Revision `808f6a4ce97025ed203bd6f411ff7291db449211` was measured from verified
Initial IR on Linux x86_64 with the release Rust companion. The representative
eight-workload suite produced these medians:

- `PYTHON_SSA_ONLY`: **162.546 ms**
- diagnostic Rust authoritative lane without Python shadow: **304.283 ms**
- `RUST_SSA_AUTHORITY_PYTHON_SHADOW`: **702.864 ms**
- dual-lane / Python-only: **4.324x**
- diagnostic Rust-only / Python-only: **1.872x**

These numbers characterize this machine and run; they are not semantic gates or
portable absolute expectations. The full raw samples, bounded statistics,
environment and manifest are in
`docs/compiler/rust_ssa_authority_performance_characterization.json`.

The primary conclusion is that Rust SSA itself is not the whole dual-lane cost.
Intrinsic Rust work accounted for 18.33% of all observed dual-lane time. Python
shadow duplicated work accounted for 35.42%, migration-safety verification and
comparison for 29.11%, transport/serialization/import for 16.71%, and measured
orchestration residual for 0.43%. These additive percentages use all 56
dual-lane samples, rather than summing independently selected medians.

## Semantic and authority isolation

Instrumentation is opt-in. The ordinary companion command and response remain
unchanged. Diagnostic Rust phase metadata is enabled only by
`--characterize-performance`; the Python coordinator ignores absent or invalid
timing metadata and timing never selects or modifies an SSA result.

The Rust-only measurement is a named diagnostic function. It is not present in
`SSALoweringAuthorityMode`, cannot be selected by `SSAPipeline`, and does not
weaken the production default. Production remains Rust-authoritative with a
mandatory synchronous Python shadow and fail-closed comparison. Both rollback
modes are unchanged.

No SSA, lifecycle, ownership, schema-v2, canonicalization, optimizer or backend
semantics were changed. The non-diagnostic companion still returns exactly the
original `{"ok": true, "ssa": ...}` shape.

## Methodology and environment

Each source workload used two warmup rounds and seven measured rounds. Lane
starting order rotated each round. Statistics report median, minimum and
maximum; conclusions do not claim precision beyond the monotonic wall clocks.
Deep CFG used two warmups and three measured rounds per size. Canonical SSA
digests were checked across Python-only, diagnostic Rust-only and dual-lane on
every warmup and measured execution.

Environment: Linux 7.1.8 x86_64, 12 logical CPUs, Python 3.14.7, rustc 1.97.1,
Cargo 1.97.1, release companion. The persistent companion served 160 requests
with one process startup.

Timings begin at verified Initial IR. Frontend, optimizer and backend work are
outside this boundary. The final Rust response byte serialization and
bidirectional pipe activity cannot be separated at the existing semantic
boundary, so they are honestly reported together as
`request_response_transport_and_serialization`.

## Workload stratification

| Class | Versioned program | Python-only median (ms) | Rust-only diagnostic (ms) | Dual-lane median (ms) |
|---|---|---:|---:|---:|
| tiny/scalar | `benchmarks/arithmetic.ae` | 1.447 | 2.774 | 6.171 |
| numeric iterative | `benchmarks/nested_loops.ae` | 1.497 | 2.620 | 5.292 |
| collection-heavy | `benchmarks/list_for_sum.ae` | 1.833 | 3.744 | 7.493 |
| struct-heavy | `examples/structs/custom_constructor_and_equality.ae` | 1.357 | 3.049 | 6.910 |
| class/interface-heavy | `examples/classes/implements_interface.ae` | 1.107 | 2.145 | 4.881 |
| function-value/indirect-call | `corpus/exceptions/positive/indirect_call.ae` | 1.901 | 3.366 | 7.248 |
| exception/lifecycle-heavy | `corpus/exceptions/positive/cleanup_during_unwinding.ae` | 3.190 | 5.196 | 10.912 |
| realistic medium | `examples/expense_tracker/Main.ae` | 149.052 | 281.614 | 652.866 |

The realistic medium program dominates the aggregate, so the per-class values
must accompany the representative-suite total.

## Phase ranking

The leading independently measured phase medians, divided by the dual-lane
representative median, were:

1. Rust SSA lowering: 89.042 ms, 12.67%
2. Python shadow input reconstruction: 61.505 ms, 8.75%
3. Rust schema-v2 import: 60.884 ms, 8.66%
4. Python lifecycle normalization: 49.647 ms, 7.06%
5. Python verification of imported Rust SSA: 42.589 ms, 6.06%
6. Python builder verification: 41.031 ms, 5.84%
7. Python SSA lowering: 40.673 ms, 5.79%
8. Python shadow verification: 40.105 ms, 5.71%
9. Python result DTO serialization: 34.113 ms, 4.85%
10. Rust result DTO serialization: 32.314 ms, 4.60%

Per-phase medians are ranked independently and therefore are not expected to
sum to the median of total wall time. The additive cost categories above use
the raw per-sample totals and do sum to 100%.

The two Python verification phases are distinct measured executions: the
`GeneralSSABuilder` verifies internally, and the shadow coordinator verifies
the returned Python object again. Imported Rust SSA verification is another
separate safety boundary.

## Persistent companion startup and steady state

The dedicated cold diagnostic Rust request took 5.306 ms, including 1.181 ms
of companion process startup (22.3% of that request). The comparable steady
tiny/scalar diagnostic Rust-only median was 2.774 ms. Startup is paid once;
all steady-state workload samples recorded zero startup and the same process
served the complete 160-request session.

After startup, serialization, IPC, Rust compute, response JSON decoding and
schema import remain individually visible except for the combined final
response-byte serialization/IPC phase noted above.

## Scaling characterization

The existing versioned deep-CFG generator
`scripts/qualify_rust_ssa_lowering_adversarial.py::linear` was measured at the
already qualified sizes 993, 1000 and 5000:

| Blocks | Python-only median (s) | Dual-lane median (s) | Rust lowering median (s) |
|---:|---:|---:|---:|
| 993 | 0.384 | 0.850 | 0.239 |
| 1000 | 0.364 | 0.892 | 0.241 |
| 5000 | 9.742 | 21.125 | 7.199 |

The 993 and 1000 results are similar. From 1000 to 5000, a 5x block increase
produced 26.75x Python-only time and 23.67x dual-lane time. This is empirical
superlinear growth, not a formal asymptotic claim. It is consistent with the
known explicit dominator sets documented as `O(V^2)` space in both current SSA
implementations; Rust lowering, Python lowering and repeated verifiers all
become dominant on the 5000-block fixture.

## Optimization candidates (not implemented)

1. **Prove and remove redundant Python verifier executions.** Addresses the
   two approximately 5.8% Python shadow verification phases. Expected mechanism:
   keep one qualified verifier at an immutable boundary. Correctness risk is
   medium, architectural risk low, mandatory shadow preserved, no protocol or
   schema change. Priority 1.
2. **Reuse an immutable same-input snapshot for the Python shadow.** Addresses
   the 8.75% Python input reconstruction phase by avoiding JSON decode/import.
   Correctness and architectural risk are medium because aliasing and input
   identity must remain fail-closed. Mandatory shadow preserved; no schema or
   protocol change expected. Priority 2.
3. **Share immutable DTO and canonical forms.** Addresses the two result DTO
   serializations and two canonicalizations (about 15.4% by independent phase
   medians). Correctness and architectural risk are medium due to cache
   invalidation/aliasing. Mandatory shadow preserved; no protocol/schema change.
   Priority 3.
4. **Replace explicit dominator sets in a separately qualified algorithm
   milestone.** Addresses the strongly superlinear deep-CFG lowering phases.
   Correctness risk high, architectural risk medium, shadow preserved, no wire
   change. Priority 4.
5. **Profile lower-allocation response decoding/schema import.** Addresses
   Rust schema-v2 import and response decode. Correctness risk high because the
   importer is fail-closed; architectural risk medium; shadow preserved; may
   require a protocol change. Priority 5.
6. **Future Python-shadow sampling/removal.** It would address the 35.42%
   duplicated-work category, but is explicitly unauthorized here, would not
   preserve the mandatory shadow, and has very high correctness and
   architectural risk. Priority 6/future only.

No optimization above was implemented in RUST-3.7b.

## Qualification executed

- Focused authority, mandatory-shadow, fail-closed, rollback, instrumentation,
  companion and RUST-3.7a stabilization tests: 39 passed.
- Frozen historical Rust-authority corpus: 116/116 programs passed canonical
  parity, lifecycle parity, both verifiers, schema import/reserialization,
  determinism and Rust-origin return.
- Production stabilization regression families: 194 tests across all eight
  families passed under `RUST_SSA_AUTHORITY_PYTHON_SHADOW`.
- Rust `cargo test --workspace --locked`: passed, including the permanent
  5000-block stack-safe lowering and verification regression.
- Release companion diagnostic/ordinary response equivalence: passed.
- `cargo fmt --all -- --check` and `git diff --check`: passed.

## Limitations

- Wall-clock samples are inherently machine- and load-dependent.
- The aggregate is representative of the checked-in manifest, not every Aether
  program distribution.
- Rust response byte encoding and IPC are combined at the current boundary.
- Deep-CFG results support engineering prioritization, not a complexity proof.
- Cross-platform performance values were not required to match and this report
  contains one Linux x86_64 characterization run.
