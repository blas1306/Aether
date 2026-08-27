# Shadow-independent production qualification — RUST-4.4

Decision: `RUST_SSA_SHADOW_INDEPENDENT_QUALIFICATION_INCOMPLETE`.

This milestone does not change production policy. Ordinary production still requires the synchronous Python SSA shadow and canonical Rust/Python comparison.

## Qualification path

The explicit qualification-only API executes verified Initial IR, lifecycle normalization, Rust lowering and Rust-side verification, schema-v2 import, imported verification, same-input integrity, independent refinement, a second integrity check, and final generic verification. It does not import or execute the Python SSA builder and does not call canonical Rust/Python comparison.

## Local evidence

Positive controls: 13/13. Historical: 116/116. Semantic mutations: 58; production shadow dependencies: 0; invalid accepted by both: 0.

Deep CFG sizes: [100, 1000, 5000, 10000]. Persistent/soak: `PASS`. Concurrency: `PASS`. Independence: `STRONG`.

## Why the checked-in decision is incomplete

The checked-in artifact claims only the platform actually executed locally. The workflow prepares Linux x86_64, Windows x86_64, macOS x86_64, and macOS arm64 artifacts, but those results must be generated and aggregated at the exact qualification revision. The evidence records each required regression gate, and any non-PASS gate remains blocking. No platform result is invented.

## Recommendation

Do not change production policy. Aggregate exact-revision CI platform artifacts and complete all regression gates before a later transition milestone.
