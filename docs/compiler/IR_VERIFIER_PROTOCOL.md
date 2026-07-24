# Initial IR Verifier Subprocess Protocol

Phase 4.2A defines protocol version 1 and the standalone
`aether-ir-verifier` executable. Phase 4.2B adds an explicitly called,
bounded Python subprocess adapter and Phase 4.2C stabilizes a transport-neutral
client over it, both described in
[PYTHON_RUST_VERIFIER_ADAPTER.md](PYTHON_RUST_VERIFIER_ADAPTER.md). The normal
Python compiler pipeline still does not discover, select, invoke, or shadow
this executable.

## Package and executable

The Cargo package and produced executable are both named
`aether-ir-verifier`. Build from `compiler-rs/`:

```console
cargo build -p aether-ir-verifier
cargo build --release -p aether-ir-verifier
```

The development artifacts are produced by Cargo under `target/debug/` and
`target/release/`. Protocol and library code never contain those
repository-relative paths. Phase 4.2B receives an explicitly resolved
development executable. The Phase 4.2B development helper searches `PATH` only
when its caller requests that source and searches a Cargo development location
only when given an explicit repository root. It never infers the current
working directory or compiler configuration.

## Stdin and stdout

The process reads all of stdin as exactly one UTF-8 JSON request, writes
exactly one compact UTF-8 JSON response followed by `\n` to stdout, and then
terminates. Normal operation writes nothing to stderr. There is no streaming,
batching, command-line request mode, or normal logging.

For example:

```console
cargo run -p aether-ir-verifier < request.json
cat request.json | target/debug/aether-ir-verifier
```

Repeated execution with the same request produces byte-for-byte identical
stdout. Object field order is fixed by the response DTO; context fields that
are unavailable are emitted explicitly as `null`.

## Request version 1

```json
{
  "protocol_version": 1,
  "operation": "verify",
  "module": {
    "schema_version": 1,
    "functions": [],
    "structs": []
  }
}
```

The request has exactly the three shown top-level fields. `operation` has one
supported spelling, `verify`. `module` is the existing canonical
`IRModuleDTO`, not a protocol-specific duplicate.

The IR schema version is deliberately not copied to an
`ir_schema_version` field in the outer request: the canonical module envelope
already requires `schema_version`. Protocol version and IR schema version
therefore evolve independently without two possibly conflicting schema values
in one request. Protocol v1 supports only IR schema v1.

Parsing rejects non-UTF-8 input, empty input, trailing JSON, duplicate object
keys at every depth, missing/unknown protocol fields, invalid canonical DTO
fields, and unsupported versions before importing the owned Rust IR.

## Response envelope

Every response carries `protocol_version: 1` and exactly one of three status
values.

Accepted:

```json
{"protocol_version":1,"status":"accepted"}
```

Semantic rejection:

```json
{
  "protocol_version": 1,
  "status": "rejected",
  "diagnostic": {
    "phase": "types",
    "category": "returns",
    "invariant": "IRV-026",
    "message": "...",
    "context": {
      "function_index": 0,
      "function_name": "main",
      "block_index": 0,
      "block_name": "entry",
      "instruction_index": 0,
      "instruction_kind": "return"
    }
  }
}
```

Protocol, schema, import, normalization, or internal failure:

```json
{
  "protocol_version": 1,
  "status": "error",
  "error": {
    "kind": "unsupported_protocol_version",
    "message": "unsupported protocol version 2; expected 1"
  }
}
```

Only `aether_verifier::verify_module` decides semantic acceptance. The
executable does not call or order individual verifier passes.

## Stable wire spellings

Status values are `accepted`, `rejected`, and `error`.

Verification phases are `structure`, `types`, `ssa`, `dominance`,
`lifecycle`, and `returns`.

Diagnostic categories are `definitions`, `types`, `cfg`, `instructions`,
`returns`, `lifecycle`, `data_flow`, `borrowing`, `calls`, `builtins`,
`constants`, `operators`, `structs`, `method_results`, `collections`, and
`linear_algebra`.

Instruction kinds use the existing schema-v1 instruction tags:

```text
const, load, store, init_default, copy_init, move_init, assign, destroy,
relocate, binary_op, unary_op, compare_op, cast, call, function_ref,
call_indirect, print, struct_new, struct_get, struct_set, method_result_new,
method_result_receiver, method_result_value, array_new, list_new, array_copy,
list_copy, list_contains, list_index_of, list_clear, list_push, list_insert,
list_remove_at, list_pop, list_reverse, sequence_sort, vector_new, matrix_new,
vector_add, vector_sub, vector_scale, vector_dot, outer_product, matrix_add,
matrix_sub, matrix_scale, matrix_mat_mul, matrix_vector_mul,
vector_matrix_mul, array_get, array_slice, list_slice, list_get, vector_get,
matrix_get, vector_length, matrix_rows, matrix_columns, array_set, list_set,
vector_set, matrix_set, array_length, list_length, list_is_empty, branch,
jump, return
```

Infrastructure error kinds are:

| Kind | Meaning |
| --- | --- |
| `empty_input` | stdin contains no non-whitespace bytes |
| `malformed_json` | input is not exactly one strict UTF-8 JSON value |
| `request_schema` | the protocol envelope has an invalid shape |
| `unsupported_protocol_version` | `protocol_version` is not 1 |
| `unsupported_ir_schema_version` | embedded `module.schema_version` is not 1 |
| `unsupported_operation` | `operation` is not `verify` |
| `module_schema` | `module` is not a canonical schema-v1 DTO |
| `module_import` | a valid DTO cannot be represented by the owned Rust IR |
| `normalization` | a semantic failure lacks required stable classification |
| `input_io` | stdin could not be read |
| `internal` | an unwind panic reached the executable boundary |

These strings are explicit mappings. Rust enum names, `Debug`, and derived
`Display` output are not protocol spellings.

## Semantic invariant policy

A `rejected` response always has an `IRV-NNN` invariant. If
`VerificationFailure::invariant_id()` is unexpectedly absent, or a future
non-exhaustive phase/category has no reviewed wire spelling, the result is
`status: "error"` with kind `normalization`. Serializing such a gap as an
ordinary semantic rejection could make differential verification trust an
incompletely normalized result.

## Exit codes and panic boundary

Exit code 0 means the executable emitted a valid response, including
`rejected` and `error`. Semantic rejection is a successfully processed
protocol outcome, and recoverable malformed/version/schema/import/internal
requests still have a structured response.

A nonzero exit is reserved for a process-level condition that prevents a
valid response from being emitted, currently response serialization or stdout
write/flush failure. Abrupt termination by the operating system retains its
ordinary signal/process status.

The executable catches Rust unwind panics at its outer request boundary,
temporarily suppresses the default panic hook, and returns the stable
`internal` response without exposing the payload or a backtrace. This does not
and cannot catch builds configured with `panic=abort`, allocation aborts,
signals, or forced termination. Library panic behavior is unchanged.

## Fixture and corpus boundary

Small checked-in protocol fixtures cover acceptance, semantic rejection,
IRV-026 storage return, the intentional IRV-024 loop result, malformed JSON,
both version failures, import failure, invalid operation, and an out-of-range
integer case that fails at the canonical schema boundary.

The migration corpus has 130 indexed Python cases. Of those, 128 cross schema
v1. The two excluded cases remain explicit schema-boundary tests:
`lifecycle-non-storage-destination` uses a value where the schema requires
storage, and `integer-constant-out-of-range` exceeds the signed 32-bit constant
domain. The protocol does not weaken the DTO to carry them.

The Phase 4.2A comparison of those 128 transportable cases has no unexpected
acceptance/rejection difference. Exact first-invariant parity is intentionally
not universal. Outcome comparison and rejection-diagnostic comparison are
separate operations: a future shadow mode must first compare `accepted` versus
`rejected`, and only then compare invariant IDs when both sides reject.
Human-readable `message` values are presentation, not semantic identity.

The outcome report retains one known mismatch:
`non-void-path-without-return` is rejected by Python with IRV-024 and accepted
by Rust's intentional graph analysis. Manifest schema version 2 records that
Rust outcome explicitly; it is not an unexpected difference. Of the remaining
two-sided rejections, 60 have exact first-invariant matches and three have the
documented diagnostic divergences below.

Corpus manifest schema version 2 records three explicit diagnostic
compatibility expectations:

| Case | Python first invariant | Rust first invariant | Compatibility classification |
| --- | --- | --- | --- |
| `return-storage-after-move` | IRV-050 | IRV-026 | First-failure ordering difference. The semantic rejection agrees and both detected rules are valid. |
| `undefined-slot` | IRV-031 | IRV-032 | Representation/import-model diagnostic difference. Rust normalizes the load slot as storage and reports uninitialized storage; this is the previously documented intentional IRV-031 difference. |
| `inconsistent-branch-initialization` | IRV-036 | IRV-028 | Lifecycle dataflow semantic difference. Rust preserves possible merge states and permits later repair, while Python rejects divergence immediately; this is the previously documented IRV-036 improvement. |

These pairs are affirmative compatibility expectations, not ignored cases.
The corpus comparison reports outcome mismatches, exact diagnostic matches,
documented diagnostic divergences, and unexpected diagnostic divergences
separately. A known case is documented only when its observed Python/Rust pair
equals the pair in the manifest; any other pair remains unexpected.

Phases 4.2B and 4.2C add the isolated Python subprocess adapter and neutral
client contract, but no compiler integration, shadow mode, verifier-selection
CLI, production packaging discovery, automatic fallback, or PyO3 binding.
Those remain later work.
