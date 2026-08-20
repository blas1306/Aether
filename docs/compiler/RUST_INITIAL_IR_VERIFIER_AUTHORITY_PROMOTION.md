# RUST-2 — Initial IR verifier authority promotion

Final decision: **`RUST_INITIAL_IR_AUTHORITY_PROMOTED`**.

The production Initial IR verification policy is now Rust authority with the
Python verifier retained as the required RP3 shadow. The canonical switch is
`src/aether/ir/shadow_verifier.py::_AUTHORITY_CONFIGURATION`, changed from
`PYTHON_AUTHORITY_RUST_SHADOW` to `RUST_AUTHORITY_PYTHON_SHADOW`. The
architecture registry advances only from RP2 to RP3.

Both engines still execute and their normalized semantic results are compared.
A disagreement remains fatal as `VerifierSemanticDisagreement`. A Rust
semantic rejection supplies the authoritative rule, category, and available
function/block/value context. Rust startup, crash, timeout, malformed response,
or compatibility failure remains a visible fail-closed infrastructure error;
Python is never used as a silent fallback. During RP3, Python-shadow failures
remain fatal in the CI migration gate.

The qualified companion remains `aether-ir-verifier` 0.1.0, discovered from
`<aether-home>/libexec/aether/`. PATH, checkout, and Cargo target directories
are not implicit production discovery locations. Protocol 1, IR schema 1,
product/version metadata, and the `verify` capability remain mandatory.

Semantic evidence is unchanged: Python and Rust each cover 150/150 production
rules, with zero semantic divergences and three accepted diagnostic-only
divergences. The qualified 404-comparison canary has zero semantic mismatches,
unexpected results, infrastructure failures, startup failures, protocol
failures, or timeouts. OP1–OP10 and the four-platform companion qualification
remain PASS.

Rollback is one policy change back to `PYTHON_AUTHORITY_RUST_SHADOW` plus the
RP2 registry value. The Python implementation, comparison path, and tests are
not removed. This promotion does not make the compiler core fully Rust and
does not migrate the parser, typechecker, IR construction, SSA verifier,
optimizer, backend, driver, or runtime.

RP4 may later make Python shadow optional/development-only; RP5 may later make
verification Rust-only. Neither is implemented by RUST-2.
