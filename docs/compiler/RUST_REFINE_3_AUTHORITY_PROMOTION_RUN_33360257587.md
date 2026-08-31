# RUST-REFINE-3 official run 33360257587 — FAILED/BLOCKED

This is the immutable failure record for the first official RUST-REFINE-3
qualification. It is not a closure and does not promote Rust authority.

## Run identity and decision

- workflow: `rust-refine-3-authority-promotion` (`346335540`);
- event/attempt: `workflow_dispatch`, attempt 1;
- revision: `1db406d152870602532ab5fbbbb6c62ea75db76e`;
- created: `2026-08-31T05:21:29Z`;
- completed: `2026-08-31T05:28:51Z`;
- GitHub conclusion: `failure`;
- official aggregate: `RUST_REFINEMENT_AUTHORITY_PROMOTION_BLOCKED`;
- official aggregate replay: `RUST_REFINEMENT_AUTHORITY_PROMOTION_BLOCKED`;
- independently rebuilt aggregate: `RUST_REFINEMENT_AUTHORITY_PROMOTION_BLOCKED`.

All three decisions contained the same 71 fail-closed errors. The official,
replayed, and independently recomposed decision JSON files were byte-identical,
with SHA-256
`3e34d0ea9fe792fdfd5020d1f889ab4b4cfe60b48948f1831b611a5442fa3ea9`.

## Jobs

| Job ID | Job | Conclusion |
|---:|---|---|
| 99390098771 | prerequisite-rust-refine-2 | failure |
| 99390098845 | authority-contract | failure |
| 99390098685 | directed-differential | success |
| 99390098804 | mutation-adversarial | success |
| 99390098763 | production-authority | success |
| 99390098809 | no-python-rescue | success |
| 99390098859 | transport-parity | success |
| 99390098822 | production-pipeline | success |
| 99390098793 | packaged-clean-consumer | failure |
| 99390098749 | source-development | failure |
| 99390098911 | deep-stress | success |
| 99390098786 | cost-characterization | success |
| 99390098875 | platform-linux-x86_64 | failure |
| 99390098864 | platform-windows-x86_64 | failure |
| 99390098806 | platform-macos-x86_64 | failure |
| 99390098836 | platform-macos-arm64 | failure |
| 99390098912 | python-3.11 | failure |
| 99390098818 | python-3.12 | failure |
| 99390098931 | python-3.13 | failure |
| 99390098921 | python-3.14 | failure |
| 99391258623 | aggregate-fail-closed | failure |

No failed, missing, skipped, cancelled, or neutral mandatory job was treated as
passing.

## Official artifacts

Exactly the ten artifacts published by this run were freshly downloaded from
GitHub. No pre-existing local artifact was substituted. Each GitHub digest
matched the independently computed downloaded ZIP SHA-256.

| Artifact ID | Name | ZIP SHA-256 / GitHub digest | Evidence SHA-256 |
|---:|---|---|---|
| 9746570335 | rust-refine-3-aggregate | 86eee08fad19a7442a8becc9ad11b57c4d6a9e54ed7ff1249053eeb26fffa1fa | decision: 3e34d0ea9fe792fdfd5020d1f889ab4b4cfe60b48948f1831b611a5442fa3ea9; manifest: 5416a1d25be2b10c135bf575707ab7bba35796cf257e2306564c96bf438e2a52 |
| 9746566206 | rust-refine-3-source | 8d80109516b7926cb802c2b57bd50cf07561a6d9c904c5a8807634d7a892e6ce | no complete evidence; job failed |
| 9746481065 | rust-refine-3-transport | 416d6840cac7d64017ad53cc5e0d8493b73ee07162324aa1c5df8777b08550d1 | f3658a5d6cf75835864ef3bf131f48d82c942c0c2855f62dd28ee76033feacbf |
| 9746478606 | rust-refine-3-production-pipeline | 841181dad9dc5f3b64645705bd48633ee9cd7bb997b4a03c43889e007a2c92cd | 7d10051735f0ca3c1ef93f37f85de5ebe2d1c86a303c923a173cf77b7e00f63d |
| 9746475426 | rust-refine-3-production-authority | 89167532649de0aabbafe03f7e7e0b45dec119377953b929d93b1434ba441680 | 921984a0b64072008ebef8fa93ca2edf17dd3dae56b754ab0e642958d346d64a |
| 9746465543 | rust-refine-3-no-python-rescue | 0b0d156118561104efd575c376c0e37a8601ac84f6a5c6492eb7f008659b6753 | ae778339f59a58502b2ffd6236522b9096d6203cadd30ef581433c1c708dcf3d |
| 9746456734 | rust-refine-3-differential | 99735cd9abea897737bfc5a039e9c03cbbef61a9430571a30d5c3e99305b3bb5 | 17bde919039d182611ce4aa6b781e9dff39c0424378dc447b6eb5e02246ea78a |
| 9746452724 | rust-refine-3-cost | 3d0803eb46859ae928a1b2f31601783ce8077e8db1f0283124ae4b694d127d54 | 575cf7610842a5315002de04333783792fd311ab6c8ce591f3f3a076e6873b4e |
| 9746450330 | rust-refine-3-mutations | 01f49fcf0f14e63c0afd632020a441b60c20e87e53d874fcbb8dcbcc7279e21e | ad812fffdc7726c63bfc4c93b7161bdb10f86c5d7b179a6888db68d04951ae7a |
| 9746450276 | rust-refine-3-deep | bbc30e33f78f1744664f3d697cd299786bd17cea8971d8c2438e8a46215dc1c0 | c2b542cf9fe2403c798def4e6abaeb1978c21af2616df688f18fad191b50a79f |

The aggregate expected 20 non-aggregate artifacts. Eleven were absent and the
published source artifact contained no complete evidence, so the independent
manifest retained them as missing instead of inferring results.

## Reproducible causes and disposition

Two qualification-harness defects were reproduced independently:

1. stdlib-only prerequisite and contract jobs eagerly loaded the RUST-REFINE-1
   and RUST-REFINE-2 differential modules, importing optional `numpy` before
   executing their isolated gates;
2. the clean-consumer qualification oracle passed `TypedProgram` to
   `qualify_shadow_independent_rust_ssa`, which requires lowered `IRModule`.

The corrected harness lazily loads differential dependencies and lowers the
typed program before invoking the explicit Python oracle. Regression tests run
the stdlib-only gates with `python -S` and assert the oracle receives
`IRModule`. These corrections do not change the authority decision for this
run: `33360257587` remains permanently `FAILED/BLOCKED`. They require a new
commit and a new official qualification run.
