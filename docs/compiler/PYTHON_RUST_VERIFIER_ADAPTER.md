# Python clients for the Rust Initial IR verifier

Phase 4.2B adds an isolated, opt-in Python subprocess adapter for the
`aether-ir-verifier` executable. Phase 4.2C adds a transport-neutral client
boundary over that adapter. Normal compilation still calls the Python verifier:
neither layer is referenced by `IRBackend.verify()`, compiler configuration,
the CLI, or automatic fallback/shadow logic.

## Transport-neutral client API

Stable integration types live in `aether.ir.rust_verifier_client` and are also
exported by `aether.ir`:

```python
from aether.ir import (
    RustVerifierAcceptedOutcome,
    RustVerifierRejectedOutcome,
    build_canonical_rust_verifier_request,
)
from aether.ir.rust_verifier import SubprocessRustVerifierClient

request = build_canonical_rust_verifier_request(module)
client = SubprocessRustVerifierClient(
    executable="/explicit/path/to/aether-ir-verifier",
)
invocation = client.verify(request)

if isinstance(invocation.outcome, RustVerifierRejectedOutcome):
    invariant = invocation.outcome.diagnostic.invariant_id
```

`RustVerifierClient` is a runtime-checkable structural protocol with one
`verify(CanonicalRustVerifierRequest) -> RustVerifierInvocation` method.
Timeouts, byte limits, executable commands, extension loading, and other
transport configuration do not appear in that method. A future PyO3 client can
therefore implement the same interface without pretending to own process
configuration.

### Canonical request lifecycle

`build_canonical_rust_verifier_request()` calls `ir_module_to_dto()` once and
encodes the complete protocol-v1 envelope once. Its immutable result contains:

- deterministic compact UTF-8 JSON bytes, including the trailing newline;
- protocol version;
- IR interchange schema version.

The same object can be passed to subprocess or a future extension client and
reused for hashing or comparison metadata. No client rematerializes the module.
DTO materialization, JSON construction, and canonical encoding failures become
`RustVerifierRequestConstructionError` with a deterministic public message and
the original error retained as `__cause__`.

### Outcomes, invocation metadata, and comparison

Neutral outcomes are frozen dataclasses:

- `RustVerifierAcceptedOutcome`;
- `RustVerifierRejectedOutcome`, containing
  `RustVerifierNormalizedDiagnostic`;
- `RustVerifierInfrastructureFailure`, containing a neutral failure kind and
  message.

`RustVerifierInvocation` stores an outcome separately from
`RustVerifierInvocationMetadata`. Common metadata contains the client kind,
optional duration, protocol version, and IR schema version. Optional
client-specific details are nested under `transport_metadata`.
`SubprocessRustVerifierInvocationMetadata` retains stderr, exit code, and the
wire error kind needed by the legacy view. A PyO3-style client leaves this
field empty and does not invent stderr, exit-code, or executable values.

Semantic or shadow-style comparison must call
`rust_verifier_outcome_comparison_key(invocation.outcome)`. Rejected outcomes
delegate to `diagnostic.comparison_key()`, whose identity is:

```text
invariant_id, phase, category,
function_index, function_name,
block_index, block_name,
instruction_index, instruction_kind
```

The diagnostic message is retained for presentation but excluded from
identity. Message wording is implementation-specific and cannot establish or
break Python/Rust parity. The typed comparison key can directly represent
documented diagnostic divergence pairs without prose matching. Source
locations and severity are not synthesized; they can be added later outside
the core key when both implementations provide them.

### Protocol errors versus neutral infrastructure failures

Protocol-v1 error kinds remain wire DTO details in `aether.ir.rust_verifier`.
The subprocess client maps all of them explicitly:

| Protocol-v1 kind | Neutral kind |
| --- | --- |
| `empty_input`, `malformed_json`, `request_schema` | `invalid_request` |
| `unsupported_protocol_version`, `unsupported_ir_schema_version` | `incompatible_version` |
| `unsupported_operation` | `unsupported_operation` |
| `module_schema`, `module_import`, `normalization` | `invalid_module` |
| `input_io` | `input_io` |
| `internal` | `internal` |

This smaller classification does not require every future transport to
reproduce subprocess protocol failure modes.

## Low-level subprocess compatibility API

Phase 4.2B APIs remain available from `aether.ir.rust_verifier` and retain
their existing behavior:

```python
result = verify_module_with_rust(
    module,
    executable="/explicit/path/to/aether-ir-verifier",
    timeout_seconds=5.0,
)
```

`verify_module_with_rust()` now constructs one canonical request, invokes
`SubprocessRustVerifierClient`, and translates the neutral invocation back to
the exact Phase 4.2B result view:

- `RustVerifierAccepted`;
- `RustVerifierRejected`, containing the decoded wire
  `RustVerifierDiagnostic`;
- `RustVerifierProtocolError`, containing
  `RustVerifierProtocolErrorKind`.

These legacy variants continue to carry `RustVerifierTransportMetadata`.
Existing equality, stderr access, and
`except RustVerifierAdapterError` behavior are unchanged. The detailed
commands, limits, discovery helper, protocol enums, wire results, and transport
exceptions remain low-level subprocess API. They are temporarily retained at
the `aether.ir` root for Phase 4.2B compatibility, but no further
transport-specific root exports are added.

`executable` may be one path/string or a command sequence. A command sequence
is passed directly to `subprocess.Popen`; it is never parsed by a shell.

## Protocol results versus adapter failures

An exit-zero response with `status: "error"` is a trustworthy protocol result,
not an exception. Its stable kinds cover request/schema/import/normalization,
input I/O, and contained Rust internal errors.

Failures for which no response can be trusted use this exception hierarchy:

```text
RustVerifierIntegrationError
├── RustVerifierRequestConstructionError
└── RustVerifierAdapterError
    ├── RustVerifierExecutableNotFound
    ├── RustVerifierSpawnFailure
    ├── RustVerifierTimeout
    ├── RustVerifierOutputLimitExceeded
    ├── RustVerifierRequestTooLarge
    ├── RustVerifierProcessFailure
    └── RustVerifierInvalidResponse
```

A nonzero exit always raises `RustVerifierProcessFailure`, even if stdout looks
like protocol JSON. Exceptions retain only bounded stdout/stderr excerpts and
their normalized messages do not include executable paths or
platform-specific spawn prose.

## Wire request and response boundary

Request construction calls the existing `ir_module_to_dto()` canonical
materializer. It does not walk IR instructions independently. The result is
wrapped in the exact protocol-v1 envelope, encoded as deterministic compact
JSON with sorted keys, strict UTF-8, standard finite numbers, and one trailing
newline:

```json
{"protocol_version":1,"operation":"verify","module":{"schema_version":1}}
```

The abbreviated `module` above stands for the complete canonical DTO.
Canonical DTO/materialization errors occur before process creation.

Response decoding accepts exactly one UTF-8 JSON value plus optional trailing
whitespace. It rejects duplicate keys, non-standard JSON constants, trailing
text or a second value, an incompatible protocol version, unknown status,
phase/category/instruction/error spellings, a malformed `IRV-NNN` invariant,
wrong nullable context types, and missing, forbidden, or additional fields.
Human-readable response messages are never used as identity.

## Transport policy and limits

Defaults are:

| Control | Default |
| --- | ---: |
| Timeout | 5 seconds |
| Encoded request | 16 MiB |
| stdout | 1 MiB |
| stderr | 256 KiB |

Timeouts must be finite and positive; booleans are rejected rather than treated
as numbers. Byte limits must be positive integers.

The adapter starts the child with piped stdin/stdout/stderr, no shell, and no
interactive input. Dedicated threads write the bounded request and drain both
output streams concurrently, preventing pipe deadlock without accumulating
unbounded output. A timeout or output-limit event terminates and reaps the
child, escalating to a kill after a short grace period. Truncated stdout is
never decoded.

The child inherits the caller's environment because the standalone executable
has no adapter-specific environment contract. The adapter does not set or read
a verifier-selection environment variable, does not set a working directory,
and does not depend on the caller's current directory.

## Executable discovery

The core verification call never performs discovery. The optional development
helper has explicit deterministic precedence:

1. `executable=...`, validated as an executable file;
2. `PATH`, only when `search_path=True`;
3. `<repository_root>/compiler-rs/target/<debug|release>/aether-ir-verifier`,
   only when `repository_root` is supplied.

The helper does not inspect compiler configuration, a global backend
environment variable, the current working directory, or a developer-specific
absolute path. Production packaging/discovery remains future work.

## Tests and development workflow

Fast transport tests use controlled processes launched through
`sys.executable`. They cover accepted/rejected/error results, strict response
shape validation, malformed/empty/extra stdout, timeout, bounded stdout and
stderr, nonzero exit, exit-zero stderr, spawn failures, and discovery.
Client-layer tests additionally cover one canonical materialization, failure
wrapping and causes, structural fake PyO3 compatibility, metadata separation,
message-free diagnostic identity, and all protocol-error mappings.

The real-binary tests build and resolve the development executable explicitly:

```console
cd compiler-rs
cargo build -p aether-ir-verifier
cd ..
.venv/bin/pytest -q \
  tests/aether/test_rust_verifier_adapter_integration.py
```

That suite checks real acceptance, rejection, protocol import error,
determinism, empty normal stderr, and all 128 schema-v1-transportable manifest
cases through both the compatibility API and the neutral subprocess client.
Both paths produce 64 accepted cases, 60 exact diagnostic matches, three
documented diagnostic divergences, one documented outcome mismatch, and no
unexpected divergence, adapter failure, protocol error, or neutral
infrastructure failure. The two DTO-boundary cases remain explicit and are
asserted to fail canonical materialization rather than being silently skipped.

## Production boundary and next phase

Phase 4.2C adds no verifier backend selector, shadow comparison, CLI option,
automatic fallback, environment-driven production switch, packaged executable
resolver, or PyO3 binding. Calling the compatibility function or explicitly
constructing a client is still the only way to invoke Rust from Python.

`discover_rust_verifier_executable()` remains a development helper. Its
current explicit/PATH/repository precedence is not the production packaging
contract. Production must eventually use a separately designed,
version-matched bundled-artifact resolver.

Phase 4.3 now provides the explicitly injected, Python-authoritative shadow
mode documented in
[INITIAL_IR_SHADOW_VERIFICATION.md](INITIAL_IR_SHADOW_VERIFICATION.md). It
keeps transport failures separate from semantic outcomes, uses exact
canonical-request hashes for reviewed divergences, and leaves the default
compiler path disabled. This adapter remains the bounded transport underneath
that coordinator; it does not acquire authority or automatic discovery.
