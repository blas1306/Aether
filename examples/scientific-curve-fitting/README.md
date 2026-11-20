# Scientific curve fitting

This example fits a straight line to five observations with
`linearAlgebra.leastSquares` over an SVD factorization. It keeps the full
scientific path—design matrix, fitted coefficients, predictions, residuals and
the expected SSE of `4`—and renders the result with the Plots multiseries API.
The normative observations are `x = [0, 1, 2, 3, 4]` and
`y = [0, 4, 5, 8, 8]`; the fitted values are `[1, 3, 5, 7, 9]` and the
residuals are `[-1, 1, 0, 1, -1]`.

The fitted curve is sampled eagerly at 33 points through a capturing closure.
The observations are then added as scatter points, so insertion order keeps the
markers visible above the line. Joint explicit limits are `X: [0, 4]` and
`Y: [0, 9]`, avoiding display-bound drift from floating-point SVD
coefficients.

From the repository root:

```text
cargo run --manifest-path compiler-next/Cargo.toml -p aether-cli -- run examples/scientific-curve-fitting -O0
cargo run --manifest-path compiler-next/Cargo.toml -p aether-cli -- run examples/scientific-curve-fitting -O2
```

These commands use the CLI from this checkout rather than any separately
installed `aether` binary. Each run writes one deterministic `curve_fit.svg`
in the current working directory.
