# PLOTS-MULTISERIES-V1 — M2 final qualification and closure

Date: 2026-11-20.

Status: **PLOTS-MULTISERIES-V1 CLOSED**.

M0 and M1 were already CLOSED. M2 corrected the scientific consumer, extended
the qualification evidence, audited ownership and recoverable atomicity, and
ran the complete workspace gates. No new chart family or compiler, Graphics,
SVG serializer, runtime, ABI, or general ownership capability was added.

## Preflight and scope

Qualification was performed on branch `main` at
`c5265f80dd3837efd46e238b0f887e07dff14fe7`. The index was empty. No branch
switch, history edit, commit, or push was performed.

The pre-existing local deletions below were preserved and excluded from this
work:

- `examples/dot.ae`;
- `examples/n-esimaDerivada.ae`;
- `examples/svd.ae`.

The implemented Plots source, its focused tests, the scientific consumer, and
the available Plots, Graphics, SVG, function-sampling, and Borrowed Invocable
architecture and closure reports were used as evidence. Graphics continues to
receive one `Scene`, and `plots.svg` still delegates that scene to the sole
`graphics.svg` pipeline.

## Historical-document status and reconstructed contract index

The following historical files remain unavailable:

- `docs/architecture/PLOTS_MULTISERIES_ARCH_1.md`;
- `docs/architecture/PLOTS_MULTISERIES_ARCH_1_REPORT.md`;
- `docs/architecture/PLOTS_MULTISERIES_M0_REPORT.md`.

M1 records the earlier exhaustive search of checkout paths, refs, reflogs,
unreachable objects, worktrees, and known local project paths. M2 found no new
verifiable source and therefore did not invent any of these documents. If an
original copy is supplied later, it can be added verbatim and identified as a
recovered historical artifact.

This M2 report and the M1 report are new reconstruction/qualification records,
not replacements presented as historical originals. The preserved,
verifiable contract index is:

| Contract | Implemented authority | Qualification evidence |
| --- | --- | --- |
| Multiple ordered line/scatter series | `plots/src/lib.ae` | `plots_multiseries_v1` |
| Flat point and descriptor arenas | `Figure2D.points`, `Figure2D.series` | repeated/simultaneous growth and IR checks |
| Shared limits, transform, clip, and painter order | `Figure2D.scene` | composition, limits, clipping, golden checks |
| Borrowed eager `addFunction` | generic `plots.addFunction` | M2 suite plus Borrowed Invocable M2/M3 |
| One Graphics/SVG pipeline | `plots.svg` delegation | Graphics Foundation and SVG Backend suites |
| Legacy Plots behavior | `line` and `plotFunction` | Plots 2D Line and Function Sampling suites |
| Scientific consumer | `examples/scientific-curve-fitting` | direct O0/O2 runs and structural SVG test |

## Normative qualification matrix

All runtime rows below execute at both O0 and O2 unless marked structural.

| Area | Cases | Result |
| --- | --- | --- |
| Composition | Line+Line, Line+Scatter, Scatter+Line, Scatter+Scatter, 24 interleaved growing series | PASS |
| Joint limits | all-series Auto, both Explicit, mixed Explicit/Auto, unequal ranges, constants | PASS |
| Exceptional data | partial non-finite line gaps, scatter skips, all-non-finite rejection | PASS |
| Line shape | multi-point runs, gaps, singleton point | PASS |
| Empty figure | explicit limits render; Auto or half-Auto without finite data rejects | PASS |
| Rendering | clipping, insertion/painter order, deterministic commands, repeated render | PASS |
| Independent styles | RGBA including alpha, line width, scatter diameter | PASS |
| Identity/lifecycle | source independence, `Figure2D` aliases, returned figure, arena growth | PASS |
| `addFunction` carriers | top-level function, capture-free lambda, capturing lvalue, fresh capturing closure | PASS |
| `addFunction` behavior | eager endpoints, exact success cardinality, callback throw, owner reuse, no partial series | PASS |
| Callable boundary | incompatible signatures, cross-package imports/forwarding, borrowed unwind | PASS |
| SVG | XML, 33-point consumer polyline, five exact markers, painter order, O0/O2 equality | PASS |

The focused command ran 60 tests across the eight Plots, Graphics, SVG, and
Borrowed Invocable test targets. The M2 target itself contains 12 tests.

## Scientific-consumer correction

M1 accidentally used a different response vector. M2 restored the normative
observations:

```text
x = [0, 1, 2, 3, 4]
y = [0, 4, 5, 8, 8]
```

The consumer still factors the five-row design matrix with productive SVD and
calls `linearAlgebra.leastSquares`. It verifies:

```text
intercept = 1
slope = 2
predicted = [1, 3, 5, 7, 9]
residuals = [-1, 1, 0, 1, -1]
SSE = 4
```

Every observed value and every computed residual is checked separately before
rendering. A different dataset with the same coefficients and SSE therefore
cannot pass.

The capturing closure is eagerly sampled into 33 line points, the line is
inserted first, and the five copied observations are inserted as scatter
second. Joint explicit limits `X: [0, 4]`, `Y: [0, 9]` keep the displayed
bounds exact despite harmless floating-point error in the SVD coefficients.
The result is one SVG and one shared transform/clip region.

Both documented checkout-local CLI commands exited `0`. O0 and O2 produced
byte-identical `curve_fit.svg` with SHA-256:

```text
938f68f00095ec06e14b4f1834d50584a1b5dfe4f3752f88f05837b9d230cc9b
```

`xmllint --noout` accepted it. Structural parsing found one polyline with 33
points followed by these five marker transforms derived from the restored
data:

```text
matrix(0.5 0 0 0.5 72 416)
matrix(0.5 0 0 0.5 208 252.44444444444446)
matrix(0.5 0 0 0.5 344 211.55555555555557)
matrix(0.5 0 0 0.5 480 88.88888888888891)
matrix(0.5 0 0 0.5 616 88.88888888888891)
```

The generated consumer SVG was evidence, not a source deliverable, and was
removed after comparison.

## Ownership and atomicity audit

`Figure2D` has two direct owning arenas and no nested owner:

```text
Buffer<DataPoint> points
Buffer<SeriesRecord> series
```

`SeriesRecord` stores an offset and length into the point arena, kind, RGBA,
and size. It does not store a borrowed span. Growth allocates replacement
arenas, copies all prior points and records in insertion order, copies the new
points, writes the new record, and only then replaces the two owned buffers and
publishes logical lengths. Offsets remain valid across reallocation because
they are indices, not addresses. Tests force point and descriptor growth both
separately and simultaneously, then verify all earlier series and their order.

Input arrays are copied. Mutating them after insertion does not affect the
figure. Class-handle aliases observe the same `Figure2D` identity, including
mutation through the by-value temporary alias passed to `addFunction`.

Validation failures for empty input, invalid style, invalid interval/count,
and all-non-finite input are recoverable exceptions. Qualification compares
the complete SVG before and after such failures: no descriptor is published,
the prior series count/order/data are unchanged, and the bytes are identical.
A callback exception unwinds the sampled temporary array before `addLine`, so
it also publishes no series. Heap allocation/free instrumentation is balanced
for success, repeated mixed growth, and caught callback unwind.

Allocation exhaustion remains a non-recoverable runtime failure. It is not
misreported as a recoverable atomic operation; no M2 contract attempts to
continue after allocator failure. All potentially failing allocations in the
recoverable append path occur before publication.

Direct owners for both buffers and the three strings are destroyed once by the
existing class lifecycle. Replacement consumes the old arena owner once.
Focused heap checks, existing owning-string/class-buffer suites, and the full
workspace suite found no leak or double destruction.

## Borrowed callback and ARC costs

`addFunction` borrows `ref C target`, calls it eagerly, and stores only sampled
`DataPoint` values. No callback or adapter is stored in the figure.

The representative capturing closure has:

```text
adapter retains: 0
closure owner releases: 1
closure destroys: 1
```

at O0 and O2, and emitted LLVM contains no `invocable_adapter`. The closure
owner remains callable after `addFunction`. The temporary `Figure2D` argument
alias is balanced by ordinary class ARC; alias identity plus balanced heap
instrumentation is verified on normal and unwind paths. Existing Borrowed
Invocable M2/M3 tests supply the broader cross-package, forwarding, nested
borrow, and unwind matrix without duplicating it here.

## SVG and legacy compatibility

No Graphics or SVG source changed. The multiseries golden is XML-valid,
byte-identical at O0/O2, has one polyline before five circles, and has SHA-256:

```text
5b9493b394b7c813f0af11ab256055412a29062f285c7c2583f0b5c4cce67cd9
```

The four legacy goldens remain byte-identical and `xmllint`-valid:

| Golden | SHA-256 |
| --- | --- |
| `parabola.svg` | `19fd5203fabfac0a89010ab9f9fbe2fb1f5c750f547d999248903930c2189023` |
| `gaps.svg` | `6595ef9dc3b745d3f34b1f16e6ca666e36b6779b48e4dc4e145458f202caea86` |
| `singleton.svg` | `28da18beb76e026647fe23d14dba5441f8355bfc064647382d62e40c4496c26b` |
| `function_sine.svg` | `378a0c57819816ed4da2183f2be975b158d7dad7e4e54cc55577a69436cff6d0` |

There is no change to legacy ticks, labels, numeric formatting, or styling.

## Project hygiene

`aether.lock` is the persistent dependency lock and remains in the scientific
example. `.aether-package.lock` is an empty transaction/coordination lock
created by CLI execution, not the dependency graph. The M1-generated instance
was removed, and the O0/O2 validation runs recreated it only transiently; it
was removed again after the runs.

The README now uses `cargo run --manifest-path compiler-next/Cargo.toml -p
aether-cli -- ...`, so the commands select the CLI built from this checkout
instead of a potentially stale separately installed `aether` executable. Both
documented commands were executed successfully.

## Final gates

All commands used writable `TMPDIR=/tmp`; Cargo compilation and test commands
used `CARGO_INCREMENTAL=0`. No command is marked PASS without execution.

| Command | Exit | Result |
| --- | ---: | --- |
| focused eight-target qualification (60 tests) | 0 | PASS |
| scientific consumer O0 | 0 | PASS |
| scientific consumer O2 | 0 | PASS |
| `cargo check --workspace` | 0 | PASS |
| `cargo test --workspace -j 1` (1053 tests) | 0 | PASS |
| `cargo fmt --all --check` | 0 | PASS |
| `cargo clippy --workspace --all-targets -j 1` | 0 | PASS with 10 pre-existing warnings |
| `git diff --check` | 0 | PASS |

The long registry test
`linear_algebra_oal_publishes_and_runs_real_qr_consumer` completed normally in
720.68 seconds. It was not interrupted or inferred from partial output.

## Files in the feature delivery

- `plots/src/lib.ae`;
- `plots/tests/golden_generator/src/main.ae`;
- `plots/tests/goldens/multiseries.svg`;
- `compiler-next/crates/aether-driver/tests/plots_multiseries_v1.rs`;
- `examples/scientific-curve-fitting/aether.toml`;
- `examples/scientific-curve-fitting/aether.lock`;
- `examples/scientific-curve-fitting/src/main.ae`;
- `examples/scientific-curve-fitting/README.md`;
- `examples/scientific-curve-fitting/REPORT.md`;
- `docs/architecture/PLOTS_MULTISERIES_M1_REPORT.md`;
- `docs/architecture/PLOTS_MULTISERIES_M2_REPORT.md`.

The three unrelated pre-existing deletions are not part of this list.

## Remaining limitations

- The three historical multiseries architecture/M0 documents remain absent;
  this is recorded rather than falsified.
- Allocator exhaustion is fail-fast and is not a recoverable atomicity case.
- The feature intentionally adds no legend, grid, secondary axis, new chart
  family, adaptive sampling, or new numeric formatting.

All functional, consumer, compatibility, ownership, and global gates required
for M2 are closed. No follow-on feature is started by this report.
