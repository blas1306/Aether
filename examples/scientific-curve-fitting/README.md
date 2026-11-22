# Scientific curve fitting

This example fits a straight line to five observations:

```text
x = [0, 1, 2, 3, 4]
y = [0, 4, 5, 8, 8]
```

The design matrix has one column for the intercept and one for `x`.
`linearAlgebra.leastSquares` solves the overdetermined system with Aether's
production SVD-based implementation. Matrix-vector multiplication produces the
predictions, vector subtraction produces the residuals, and
`linearAlgebra.dot` computes their sum of squared errors (SSE).

The result is `y = 1 + 2x`, with predictions `[1, 3, 5, 7, 9]`, residuals
`[-1, 1, 0, 1, -1]`, and SSE `4`.

The plotting half demonstrates `plots.figure`, a capturing closure passed to
`plots.addFunction`, `Figure2D.addScatter`, and `plots.svg.save`. The fitted
line is sampled at 33 points and added before the five observations, so the red
markers are painted over the blue line. Both series share one viewport with
explicit limits `X: [0, 4]` and `Y: [0, 9]`.

From the repository root, run either optimization level with the CLI built from
this checkout:

```text
cargo run --manifest-path compiler-next/Cargo.toml -p aether-cli -- run examples/scientific-curve-fitting -O0
cargo run --manifest-path compiler-next/Cargo.toml -p aether-cli -- run examples/scientific-curve-fitting -O2
```

The program prints the fitted equation, SSE, and output path, then writes
`curve_fit.svg` in the current directory. Open that file in a browser or SVG
viewer: the blue line is the least-squares model and the five red circles are
the original observations. Points above or below the line correspond to
positive or negative residuals, respectively.
