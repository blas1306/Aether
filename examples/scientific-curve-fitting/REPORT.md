# Scientific curve fitting report

The example is the compact consumer for the
`SCIENTIFIC-CURVE-FITTING-ERGONOMICS-V1` qualification. Its design matrix
contains an intercept column and `x = [0, 1, 2, 3, 4]`; the response is
`[0, 4, 5, 8, 8]`.

The direct `leastSquares(design, observed)` overload remains SVD-backed. It
produces, within the qualification tolerance, intercept `1`, slope `2`,
predictions `[1, 3, 5, 7, 9]`, residuals `[-1, 1, 0, 1, -1]`, and SSE `4`.
The example calculates SSE with `dot(residuals, residuals)`.

Exhaustive checks no longer live inside the introductory program. The external
driver qualification verifies every datum and scientific result independently,
runs the consumer at O0 and O2, parses the generated XML, checks the 33-point
polyline and five marker coordinates, painter order, explicit viewport limits,
byte determinism, and closure ownership/lifetime behavior.

The capturing closure is evaluated eagerly by `plots.addFunction`. The line is
inserted before the scatter observations, and both use one viewport with limits
`X: [0, 4]`, `Y: [0, 9]`.
