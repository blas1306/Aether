# Post-dominator SSA pipeline characterization — RUST-3.10

Decision: `RUST_SSA_POST_DOMINATOR_PERFORMANCE_CHARACTERIZED`

Baseline revision: `96c72ec9e72ad395a657c6f9aed1be19b45c95eb`.
The measured tree contains only the RUST-3.10 diagnostic implementation on that
exact baseline. No production optimization, authority, schema, protocol,
algorithm, verifier, shadow-policy, or fail-closed behavior changed.

## Result

CHK is no longer a meaningful Rust SSA bottleneck. All measured dominance work
(combined reachability/RPO, CHK idom, tree, and frontiers) is **0.0694%** of
ordinary Rust SSA lowering. CHK idom itself is **0.0186%**. A second dedicated
Rust dominator milestone is not justified.

The best next milestone is **Python-shadow performance while preserving its
independent algorithm, mandatory synchronous execution, and all verification**.
This is driven by deep CFGs, not by a policy recommendation: at 5,000 blocks,
Python lowering is 3.341 s of the 10.260 s dual-lane median. The two required
Python SSA verifier passes are even larger together (6.191 s); they must remain
independent unless a future milestone proves redundancy. A future shadow
performance milestone should therefore profile the independent Python builder
and verifier internals together before changing either implementation.

## Methodology and environment

- Release companion, two warmups, 15 measured ordinary-corpus rounds.
- Deep CFG: two warmups and seven measured rounds at 100, 1,000, 5,000,
  and 10,000 blocks; median/min/max; raw profiles retained in the JSON artifact.
- Python-only and dual-lane 10,000-block runs were explicitly not attempted:
  the mandatory Python full-set path was operationally unreasonable. Rust-only
  diagnostic characterization was retained at 10,000.
- Linux 7.1.8 x86_64, 12 logical CPUs, Python 3.14.7, rustc/cargo 1.97.1.
- Timings are local observational evidence, never semantic thresholds.
- Reachability and RPO are honestly grouped because the qualified iterative DFS
  computes them in one interleaved traversal.

Representative eight-program corpus lanes:

| Route | Median | Min | Max | Samples |
|---|---:|---:|---:|---:|
| Python-only | 150.637 ms | 149.719 ms | 170.124 ms | 15 |
| Rust-only diagnostic | 260.714 ms | 255.853 ms | 294.798 ms | 15 |
| Rust authority + Python shadow | 467.380 ms | 431.948 ms | 473.772 ms | 15 |

The manifest covers numeric/loops, collections, structs, classes/interfaces,
function values, exceptions/lifecycle, tiny inputs, and a realistic medium
program. Absolute values from RUST-3.8b/3.9a are not directly comparable.
RUST-3.9b deep-chain Rust SSA lowering is approximately comparable because the
fixture and release companion match, but the earlier campaign used fewer rounds
and coarser phase boundaries.

## Ordinary dual-lane accounting

The six categories are mutually exclusive and reconcile to **100.0000%** of
all ordinary dual-lane raw samples.

| Category | Share |
|---|---:|
| Transport / representation | 29.277% |
| Safety / verification | 23.142% |
| Rust intrinsic | 19.707% |
| Python shadow intrinsic | 18.624% |
| Canonical comparison | 9.172% |
| Orchestration | 0.078% |

The largest individual ordinary Rust-authority phase is Rust SSA lowering
(74.811 ms, 16.007%). Strict schema-v2 import follows (57.292 ms, 12.258%).
Transport/representation is the largest additive category, but much of it is a
required protocol or trust boundary; its size alone does not make every copy
removable.

Canonical work remains material at 9.172%, but is not the best next milestone:
it is the fail-closed comparison boundary. Startup is only 1.440 ms, one process
served 336 requests, and warm small Rust-only requests had a 2.657 ms median.
Session architecture is not limiting current steady state.

## Rust SSA lowering after CHK

| Component | Median aggregate | Rust-lowering share |
|---|---:|---:|
| Definite initialization | 40.060 ms | 53.273% |
| Renaming | 21.530 ms | 28.631% |
| Remaining lowering | 5.180 ms | 6.889% |
| Phi placement | 4.298 ms | 5.715% |
| Liveness | 3.540 ms | 4.707% |
| CFG construction/materialization | 0.538 ms | 0.716% |
| Reachability + RPO | 0.020 ms | 0.0267% |
| CHK idom | 0.014 ms | 0.0186% |
| Dominance frontier | 0.010 ms | 0.0130% |
| Dominator tree | 0.008 ms | 0.0111% |

Rust SSA still has measurable work, but it does not deserve the next dedicated
optimization milestone: the semantic risk is high and its deep-chain lowering
is only 98.430 ms at 5,000 blocks and 215.069 ms at 10,000. Definite
initialization and renaming are the only plausible later Rust-core targets.

## Deep-CFG scaling

| Blocks | Python-only median | Rust-only diagnostic median | Dual median |
|---:|---:|---:|---:|
| 100 | 9.496 ms | 9.870 ms | 19.366 ms |
| 1,000 | 361.803 ms | 178.939 ms | 452.013 ms |
| 5,000 | 9.688 s | 3.477 s | 10.260 s |
| 10,000 | not run | 17.279 s | not run |

For 1,000 → 5,000 blocks, the empirical ratios are 26.78× Python-only,
19.43× diagnostic Rust-only, and 22.70× dual-lane. Rust SSA lowering itself
grows about 6.36× (approximately 15.5 ms → 98.4 ms), consistent with the
post-CHK RUST-3.9b observation. For 5,000 → 10,000, Rust SSA lowering grows
about 2.18×, while the complete diagnostic Rust lane grows 4.97×.

The reason is the imported-result Python verifier: its median is 3.100 s at
5,000 and 16.438 s at 10,000. At 5,000 in dual mode, Python SSA lowering is
3.341 s, Python builder verification 3.100 s, and imported Rust verification
3.090 s. Thus deep dual-lane scaling is limited by the independent Python
shadow plus required Python verification, while deep diagnostic Rust-only
scaling is limited by imported-result verification—not CHK or Rust lowering.
Timing ratios characterize this fixture and do not prove asymptotic complexity.

## Safety boundaries

All six measured boundaries remain `REQUIRED_INDEPENDENT`:

| Boundary | Ordinary dual share | Classification |
|---|---:|---|
| Initial IR integrity check | 3.439% | REQUIRED_INDEPENDENT |
| Rust Owned SSA verifier | 2.442% | REQUIRED_INDEPENDENT |
| Strict schema-v2 import | 12.258% | REQUIRED_INDEPENDENT |
| Imported SSA Python verifier | 8.461% | REQUIRED_INDEPENDENT |
| Python builder verifier | 8.172% | REQUIRED_INDEPENDENT |
| Canonical comparison | 3.360% | REQUIRED_INDEPENDENT |

Verifier passes are quantitatively better deep-CFG targets than Rust core, but
not safer removal/merger targets: no redundancy has been proven. Schema-v2
import is a lower-risk architectural investigation than Rust core despite its
smaller individual share, but it is not the top expected deep-CFG payoff and
must retain strict validation.

## Representation and copy census

The JSON artifact maps every major transformation to its measured phase. The
request DTO snapshot, JSON framing/parsing, strict import, Python comparison
DTO, and canonical comparison representations allocate. Most cross a protocol,
trust, safety, or shadow-independence boundary. Two architectural copies merit
future investigation without being optimized here:

- Rust `OwnedSsaModule` → typed schema-v2 DTO;
- Rust response DTO → canonical comparison copy.

The latter exists to prevent canonicalization from mutating transport state;
the former enforces the frozen response schema. Any future work must retain
those semantics. The work removed by RUST-3.8a/3.9a remains absent, and the old
full dominator-set implementation remains test-only.

## Candidate ranking

| Rank | Candidate | Measured relevant share | Upside | Semantic risk | Qualification |
|---:|---|---:|---|---|---|
| 1 | Python shadow performance preserving independence | 18.624% ordinary; dominant deep component | High | Medium | High |
| 2 | Schema-v2 import efficiency | 12.258% | Medium | Low | Medium |
| 3 | Remaining transport/representation | 29.277% category, partly mandatory | Medium | Low | Medium |
| 4 | Verifier/safety-boundary redundancy | 23.142%; much larger deep | Medium | High | Very high |
| 5 | Remaining Rust SSA core | 19.707% category | Low | High | High |
| 6 | Canonical comparison | 9.172% category | Low | Medium | High |
| 7 | Companion/session architecture | startup negligible | Low | Low | Medium |
| 8 | Shadow-policy evolution | 18.624% intrinsic | High | Very high | Very high |
| 9 | Backend/optimizer outside SSA | not measured | Unknown | Unknown | Out of scope |

The recommendation is implementation performance of the Python shadow while
preserving algorithmic independence. Options to sample, configure, or retire
the shadow are recorded only as future policy alternatives and are not
recommended or implemented by RUST-3.10.

## Regression and evidence contract

Ordinary companion mode still invokes the original production entry point,
returns exactly `{ok, ssa}`, exposes no performance data, and reuses its
persistent process. Characterization uses the explicit
`--characterize-performance` command only. Rust-only remains a diagnostic
function and was not added to the authority enum.

Qualification passed `cargo test --workspace --locked`, the 116/116 historical
corpus, adversarial SSA, production stabilization, deep CFG 993/1,000/5,000,
seven diagnostic 10,000-block samples, the focused 3.8a/3.8b/3.9a regressions,
the 3.9b dominator differential, and the full Python suite (4,891 passed,
4 skipped). Formatting and whitespace gates also pass.

Raw evidence, environment metadata, complete profiles, deep samples, additive
accounting, safety classifications, copy census, removed-work gates, and
candidate ranking are in
`rust_ssa_post_dominator_performance_characterization.json`.
