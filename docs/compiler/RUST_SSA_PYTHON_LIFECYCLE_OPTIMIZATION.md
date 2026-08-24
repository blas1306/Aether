# Python lifecycle normalization optimization — RUST-3.13

Decision: `RUST_SSA_PYTHON_LIFECYCLE_OPTIMIZED`.

RUST-3.13 removes one narrowly proven source of redundant Python work while preserving every authority, shadow, verification, failure, schema, ownership, lifecycle, SSA, and backend boundary frozen by the milestone. The change is invocation-local and does not consume Rust analysis.

## Audit

The Python entry point receives a verified ordered Initial IR module. It first scans for an internal ARC helper sentinel, then creates a module-local `LifecycleTypeRegistry`. Each function formerly performed the following work:

1. scan every instruction to collect used values, remaining operand-use counts, and ownership-producing results;
2. scan all instruction fields again to reserve every value name, including results and destinations;
3. rewrite instructions in block order, update ownership state, synthesize defaults/loads/stores/retains/releases, fold trivial return transfer, and build fresh blocks/functions;
4. scan the normalized function for constructor invokes and create the required exceptional cleanup trampolines and normal-edge releases;
5. construct a fresh module while retaining struct order.

The first scan redundantly called the same reflective operand collector twice per instruction: once to create a temporary `set` for `_used_values`, and once to update `_remaining_uses`. The rewrite called it a third time only to subtract those same occurrences. All three results were determined solely by the immutable input instruction.

The accepted change collects one occurrence tuple per instruction, updates the used set and counter from it, and reuses it during the ordered rewrite. This removes two reflective walks and one transient set per ordinary instruction. Managed equality retains its additional current-instruction multiplicity calculation because that value participates in last-use ownership semantics.

The following work was deliberately preserved:

- the whole-function ownership/use census, because last-use behavior depends on future occurrences;
- the separate name census, because results and destinations reserve names even when they are not operands;
- fresh normalized IR reconstruction and return-transfer folding;
- constructor invoke repair over normalized output;
- registry trait computation, whose cache was already local to one expander;
- Initial IR verification, Python builder verification, imported Rust SSA verification, canonical comparison, and the mandatory synchronous Python shadow.

Reusing verifier results, Rust lifecycle facts, or state across compilations was rejected as a safety or independence violation. Merging the name and operand representations and skipping constructor repair were rejected because equivalence was not sufficiently demonstrated for their added complexity.

This is a mechanical traversal optimization, not a change to lifecycle representation or algorithm. The permanent measurement tool therefore uses the exact RUST-3.12 Git blob as its differential reference; no second production oracle was added.

## Qualification method

Baseline `b5987ef192f3a68a92bb5149787513939dcfcd16` and the worktree implementation were executed in the same Python process on the same machine. Before/after order alternated. A full garbage collection ran outside each separately timed route to prevent one measured route from shifting collection work into the next. The ordinary corpus used one warmup and seven retained rounds; deep CFG used one warmup and five retained rounds at 100, 1,000, 5,000, and 10,000 blocks. One persistent instrumented Rust companion served all 176 dual-lane requests.

Every timed execution compared both lifecycle-normalized IR and canonical SSA digests. Raw samples, min/median/max, worktree identity, audit classifications, adversarial coverage, and invariants are in `rust_ssa_python_lifecycle_optimization.json`. There are no hardware-dependent acceptance thresholds.

## Performance

The ordinary row is the per-round sum across eight representative workloads. Values are medians in seconds; speedup is before/after.

| Regime | Metric | Before | After | Speedup |
|---|---:|---:|---:|---:|
| Ordinary corpus | lifecycle normalization | 0.191002 | 0.095622 | 2.00× |
| Ordinary corpus | Python-only total | 0.569448 | 0.448102 | 1.27× |
| Ordinary corpus | Python shadow | 0.460740 | 0.390800 | 1.18× |
| Ordinary corpus | dual-lane total | 1.856509 | 1.582458 | 1.17× |

Direct lifecycle normalization fell from 10.29% to 6.04% of the ordinary dual median. Individual tiny workloads remain noisy, but all eight showed a positive direct lifecycle median; the aggregate phase and all three aggregate pipeline views improved.

| Deep blocks | Lifecycle before | Lifecycle after | Lifecycle speedup | Python-only speedup | Shadow speedup | Dual speedup |
|---:|---:|---:|---:|---:|---:|---:|
| 100 | 0.010900 | 0.007425 | 1.47× | 1.26× | 1.23× | 1.00× |
| 1,000 | 0.096070 | 0.059787 | 1.61× | 1.11× | 1.09× | 1.02× |
| 5,000 | 0.459320 | 0.252137 | 1.82× | 0.91× | 0.98× | 0.95× |
| 10,000 | 0.590402 | 0.535854 | 1.10× | 0.83× | 1.34× | 1.14× |

The target phase improved at every deep size. End-to-end deep results are regime- and noise-sensitive because lifecycle is only one component and the mandatory safety work dominates; 5,000-block totals moved slightly against the optimization while the target phase improved 1.82×, and 10,000-block Python-only moved against it while shadow and dual improved. No conclusion is based on those noisy total medians alone. The structural removal and the ordinary aggregate demonstrate useful work elimination without an architectural complication.

## Semantics and safety

Reference and optimized runs produced identical normalized IR, final SSA, and canonical SSA for scalar, string, array, list, struct, class/interface, indirect-call, exception/lifecycle, realistic, and deep-CFG inputs. Directed tests cover repeated stores, invalid initialization, partial branches, loop-carried state, conditional transfer, multiple exits, exceptions, unreachable definitions, nested aggregates, alias-like self-assignment, many storages, wide/deep CFG, and invalid lifecycle input. Invalid input preserves exception type/message and the semantic failure boundary.

Explicit sequence tests pass for A→B, B→A, A→A, repeated compilations, failure→valid, and valid→failure. The cache is a local variable inside `_expand_function`; there is no global or cross-compilation state.

Rust remains authoritative. The Python shadow remains mandatory, synchronous, fail-closed, and independent. Schemas, companion protocol, canonicalization/comparison, lifecycle and ownership semantics, all verifiers, phi placement, renaming, Rust CHK, Python bit-mask/full-set dominance, optimizer/backend, rollback modes, and promotion/requalification policy are unchanged.

## Gates and files

The RUST-3.13 checker validates raw samples and summaries, comparable before/after methodology, exact baseline, audit categories, adversarial coverage, invocation independence, source structure, mandatory shadow/verifiers, fail-closed behavior, frozen invariants, and the absence of hardware speed gates. The focused milestone tests additionally load the exact baseline normalizer and compare representative normalized IR and invalid diagnostics.

The qualification reference is the checked-in exact blob from baseline `b5987ef192f3a68a92bb5149787513939dcfcd16`, frozen at `tests/fixtures/rust_3_13/lifecycle_b5987ef192f3a68a92bb5149787513939dcfcd16.py` with SHA-256 `8b142a0e81145084a5017b38444e7c76fb619ec5c874791166f00dcf42037ada`. Ordinary qualification verifies that digest and never reads Git history. Maintainers who have the historical object can additionally run `python scripts/measure_rust_ssa_python_lifecycle_optimization.py --verify-reference-fixture` to compare the fixture byte-for-byte with the original blob.

Changed files:

- `src/aether/ir/lifecycle.py`
- `scripts/measure_rust_ssa_python_lifecycle_optimization.py`
- `scripts/check_rust_ssa_python_lifecycle_optimization.py`
- `tests/aether/test_rust_ssa_python_lifecycle_optimization.py`
- `tests/fixtures/rust_3_13/lifecycle_b5987ef192f3a68a92bb5149787513939dcfcd16.py`
- `docs/compiler/rust_ssa_python_lifecycle_optimization.json`
- `docs/compiler/RUST_SSA_PYTHON_LIFECYCLE_OPTIMIZATION.md`

The regression campaign passes the RUST-3.13 checker/tests, RUST-3.8a through RUST-3.12 contracts, historical 116/116 and adversarial/deep qualifications, production stabilization/regressions, the full Python suite, locked Rust workspace tests, Rust formatting, and `git diff --check`. The sandboxed full-suite run reached 4,892 passed and 4 skipped but reported 24 `test_native_exceptions.py` infrastructure failures because LSAN cannot run under ptrace; rerunning that complete 54-test file outside ptrace passed 54/54, yielding an effective full result of 4,916 passed and 4 skipped.

## Recommendation

Keep this optimization narrowly scoped. Further attempts to reuse verifier, Rust, or cross-invocation facts would cross the explicit safety budget. If another implementation milestone is justified, profile the remaining Python lifecycle rewrite/name census independently; do not target mandatory verification or shadow policy under the lifecycle label.
