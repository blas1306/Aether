# PLOTS-MULTISERIES-V1 — M1 report

Status: **M1 CLOSED**. At the M1 boundary the parent
`PLOTS-MULTISERIES-V1` remained **PARTIAL** pending M2. M2 is now closed in
[`PLOTS_MULTISERIES_M2_REPORT.md`](PLOTS_MULTISERIES_M2_REPORT.md).

## Preflight and authority

Work was performed on branch `main` at
`c5265f80dd3837efd46e238b0f887e07dff14fe7`. No branch switch, history edit,
commit, or push was performed. The pre-existing deletions of
`examples/dot.ae`, `examples/n-esimaDerivada.ae`, and `examples/svd.ae` were
preserved.

The following expected documents could not be recovered:

- `docs/architecture/PLOTS_MULTISERIES_ARCH_1.md`;
- `docs/architecture/PLOTS_MULTISERIES_ARCH_1_REPORT.md`;
- `docs/architecture/PLOTS_MULTISERIES_M0_REPORT.md`.

They were searched in the current checkout, all configured worktrees, local
and remote refs, reflogs, unreachable Git blobs, and known project paths under
`/home/blasm`. No versioned or recoverable copy was found. The supplied M1
specification was therefore used as provisional authority; the missing
normative documents remain a documentation follow-up.

The requested `examples/scientific-curve-fitting/` project was also absent from
this checkout and from Git history/recoverable objects. It was created from the
scientific requirements in the supplied specification.

## Public API

M1 adds:

```aether
public struct ScatterStyle {
    graphics.Color color;
    float64 diameter;
}

public ScatterStyle defaultScatterStyle();

public mut void Figure2D.addScatter(
    ref Array<DataPoint> points,
    ScatterStyle style
);

public void addFunction<C: Invocable<(float64), float64>>(
    Figure2D figure,
    ref C target,
    float64 a,
    float64 b,
    usize sampleCount,
    LineStyle style
);
```

`defaultScatterStyle()` uses RGBA `(31, 119, 180, 255)` and diameter `6.0`.
`LineStyle` and `FigureOptions` are unchanged.

## Representation, ownership, and atomicity

Line and scatter series share M0's flat `Buffer<DataPoint>` arena and flat
`Buffer<SeriesRecord>` arena. `SeriesKind` now distinguishes `Line` and
`Scatter`; the record's existing RGBA and size fields hold line width or point
diameter. There is no nested buffer and no scatter-specific storage.

`addScatter` rejects empty input, non-positive/non-finite diameter, and input
without a completely finite pair. It copies every source element, publishes a
scatter record only after validation and any required allocations/copies, and
never retains the source `Array`. The shared append grows both arenas
geometrically. If either arena must grow, replacement buffers are fully
prepared before their owned fields and logical lengths are published. Failed
validation leaves the figure unchanged.

`addFunction` validates and samples with the same endpoint-preserving grid as
`plotFunction`, evaluates exactly `sampleCount` times on success, materializes
an `Array<DataPoint>`, and delegates publication to `addLine`. The callback is
borrowed and never stored. A callback exception unwinds the temporary array
without publishing a partial series. Passing the `Figure2D` class handle keeps
object identity, so aliases observe the inserted series. Function values,
closure lvalues, and fresh closures are qualified; a closure owner remains
usable after the call.

Measured closure runtime counters for the representative borrowed closure are
zero retains, one owner release, and one destroy at both O0 and O2. Heap
allocation/free counters are balanced for normal sampling, mixed arena growth,
and callback unwinding.

## Rendering, limits, and painter order

All inserted series are visited in insertion order inside one push/clip/pop
block and use the same resolved limits and transform. A later line or scatter
therefore paints above earlier series. Scatter emits one `drawPoint` command
per finite observation with its independent RGBA and diameter; non-finite
observations are skipped. Line gap/singleton behavior remains unchanged.

Automatic axes scan all finite points in all series. Explicit and mixed
Auto/Explicit axes retain the existing expansion and validation rules.
Qualification covers constant data, unequal ranges, clipping, non-finite
points, both line/scatter orders, interleaved series, and repeated rendering.
No tick, label, or axis calculation was changed.

## Scientific consumer

> M2 correction (2026-11-20): M1 accidentally reconstructed the observations
> with a different dataset. The historical paragraph below is superseded by
> the normative data and evidence recorded here; this note preserves the fact
> that the correction occurred during M2 rather than rewriting that history.

`examples/scientific-curve-fitting/` constructs the five-row design matrix,
factors it with SVD, and calls `linearAlgebra.leastSquares`. For observations
`[0, 4, 5, 8, 8]`, it checks every observed value, intercept `1`, slope `2`,
predictions `[1, 3, 5, 7, 9]`, every residual `[-1, 1, 0, 1, -1]`, and SSE
`4`.

The capturing fitted-line closure is sampled first with 33 points over
`[0, 4]`; the five observations are inserted as scatter second. Joint explicit
limits are `X: [0, 4]`, `Y: [0, 9]`, avoiding display-bound drift from the
floating-point SVD coefficients. `curve_fit.svg` contains exactly one 33-point
polyline followed by five circles. O0 and O2 produced byte-identical SVG with
SHA-256
`938f68f00095ec06e14b4f1834d50584a1b5dfe4f3752f88f05837b9d230cc9b`.
`xmllint --noout` accepted the result.

## Goldens and compatibility

The representative multiseries golden is
`plots/tests/goldens/multiseries.svg`, SHA-256
`5b9493b394b7c813f0af11ab256055412a29062f285c7c2583f0b5c4cce67cd9`.
It is XML-valid, byte-identical in O0/O2, and contains one line followed by
five points.

The four legacy goldens were regenerated only as a comparison and had no diff:

| Golden | SHA-256 |
| --- | --- |
| `parabola.svg` | `19fd5203fabfac0a89010ab9f9fbe2fb1f5c750f547d999248903930c2189023` |
| `gaps.svg` | `6595ef9dc3b745d3f34b1f16e6ca666e36b6779b48e4dc4e145458f202caea86` |
| `singleton.svg` | `28da18beb76e026647fe23d14dba5441f8355bfc064647382d62e40c4496c26b` |
| `function_sine.svg` | `378a0c57819816ed4da2183f2be975b158d7dad7e4e54cc55577a69436cff6d0` |

## Qualification and gates

All listed commands exited `0` unless noted. No gate is reported as passing
without execution.

| Gate | Result |
| --- | --- |
| M0+M1 `plots_multiseries_v1` (11 tests, O0/O2) | PASS |
| Plots 2D Line / four legacy goldens | PASS |
| Plots Function Sampling | PASS |
| Plots Invocable Integration | PASS |
| Graphics Foundation | PASS |
| Graphics SVG Backend | PASS |
| Borrowed Invocable M2 and M3 | PASS |
| Scientific consumer O0/O2 and structural SVG checks | PASS |
| External `xmllint --noout curve_fit.svg` | PASS |
| `cargo check --workspace` | PASS |
| `cargo fmt --all --check` | PASS |
| `cargo clippy --workspace --all-targets -j 1` | PASS with pre-existing warnings |
| `git diff --check` | PASS |

The focal Rust command executed 59 tests across the eight requested suites.
The complete global workspace test suite was intentionally reserved for M2 as
directed; no compiler, runtime, Linear Algebra, or Graphics source was changed.

## Files changed or added

- `plots/src/lib.ae`;
- `plots/tests/golden_generator/src/main.ae`;
- `plots/tests/goldens/multiseries.svg`;
- `compiler-next/crates/aether-driver/tests/plots_multiseries_v1.rs`;
- `examples/scientific-curve-fitting/aether.toml`;
- `examples/scientific-curve-fitting/aether.lock`;
- `examples/scientific-curve-fitting/src/main.ae`;
- `examples/scientific-curve-fitting/README.md`;
- `examples/scientific-curve-fitting/REPORT.md`;
- `docs/architecture/PLOTS_MULTISERIES_M1_REPORT.md`.
