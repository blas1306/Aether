# Scientific curve fitting report

## Result

The design matrix contains an intercept column and the coordinates `0` through
`4`. The response is `[0, 4, 5, 8, 8]`. SVD-backed least squares produces, to
the checked tolerance:

- intercept: `1`;
- slope: `2`;
- predicted values: `[1, 3, 5, 7, 9]`;
- residuals: `[-1, 1, 0, 1, -1]`;
- SSE: `4`.

The executable checks every observed value and every residual independently,
so another dataset with the same coefficients and SSE cannot satisfy the
consumer contract.

The capturing `fittedLine` closure is borrowed by `plots.addFunction`, sampled
exactly 33 times, and remains usable after sampling. The resulting line is
inserted first. Five copied observations are inserted with `addScatter`
afterward, preserving painter order. Both series therefore use one transform,
one clipping region, and joint explicit limits `X: [0, 4]`, `Y: [0, 9]`.
Explicit limits keep the SVG axes exact even when the SVD result differs from
the mathematical coefficients by rounding error.

This consumer traces the first CLOSED Borrowed Invocable result into a
scientific application: the callback owner is neither stored nor consumed, and
the SVG is deterministic in O0 and O2.
