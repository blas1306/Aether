# SCIENTIFIC-CURVE-FITTING-ERGONOMICS-V1

Fecha: 2026-11-22.

Estado: **CLOSED**.

## Alcance y preflight

La refactorización se realizó en `main`, sobre `bf1e614613700f686258efdb99cfd684e2746de2`.
El worktree contenía previamente el archivo no versionado
`docs/reports/SCIENTIFIC_PLOTS_ERGONOMICS_AUDIT_V1.md`; se preservó sin
modificar. No se cambió compiler, runtime, Graphics, Plots ni Linear Algebra.

Se inspeccionaron el consumer, su README y reporte, la qualification de Plots
Multiseries y las superficies públicas vigentes. `leastSquares(Matrix, Vector)`
factoriza internamente mediante la SVD productiva y `dot(Vector, Vector)` admite
los dos residuos columna, por lo que no fue necesaria ninguna API nueva.

## Simplificación del ejemplo

El consumer ya no materializa una SVD que no reutiliza y ahora expresa el flujo
científico directamente:

```aether
var coefficients = la.leastSquares(design, observed);
var predicted = design * coefficients;
var residuals = observed - predicted;
float64 sse = la.dot(residuals, residuals);
```

Se eliminaron del programa las comprobaciones repetitivas del dataset,
coeficientes, cinco residuos, SSE y closure. También se eliminó el loop manual
de acumulación. El consumer conserva únicamente el cálculo, una salida breve,
la closure capturante y la construcción lineal de la figura.

La visualización mantiene una curva de 33 muestras, cinco observaciones
scatter, curva antes que markers, un solo viewport y límites explícitos
`X: [0, 4]`, `Y: [0, 9]`. Continúa exportando un único `curve_fit.svg` mediante
`plots.svg.save`.

## Qualification trasladada

`plots_multiseries_v1.rs` contiene ahora un fixture científico separado que
comprueba externamente, con tolerancia absoluta `1e-10`:

- la matriz de diseño y las cinco observaciones exactas;
- intercepto `1` y pendiente `2`;
- predicciones `[1, 3, 5, 7, 9]`;
- residuos `[-1, 1, 0, 1, -1]`;
- SSE `4` calculado con `dot`.

La prueba enlaza el fixture al consumer comprobando su dataset y las operaciones
científicas canónicas en el source incluido. El consumer real se ejecuta en O0
y O2. Su SVG se parsea como XML y se verifican una polyline de 33 puntos, cinco
markers con sus coordenadas exactas, orden de pintado, extremos transformados
para los límites explícitos y bytes idénticos entre optimizaciones.

La closure del consumer real también se ejecuta sobre LLVM instrumentado: el
callback prestado no agrega retains, se libera y destruye exactamente una vez,
y el heap queda balanceado en O0/O2. Las pruebas generales de Plots continúan
cubriendo sampling eager, atomicidad y reutilización de closures.

## Resultado

El resultado científico preservado es:

```text
x = [0, 1, 2, 3, 4]
y = [0, 4, 5, 8, 8]
intercept = 1
slope = 2
predicted = [1, 3, 5, 7, 9]
residuals = [-1, 1, 0, 1, -1]
SSE = 4
```

O0 y O2 generaron XML válido y el mismo SHA-256:

```text
0e40b2bbfe5d6fcda3bd3566f4fa934a061b0df57e86e0ca12759963a9e4a82d
```

## Gates

Ejecutados y aprobados:

```text
cargo run --manifest-path compiler-next/Cargo.toml -p aether-cli -- run examples/scientific-curve-fitting -O0
cargo run --manifest-path compiler-next/Cargo.toml -p aether-cli -- run examples/scientific-curve-fitting -O2
cargo test --manifest-path compiler-next/Cargo.toml -p aether-driver --test plots_multiseries_v1 --test format_v2 --test plots_tick_label_format_v1
xmllint --noout curve_fit.svg
sha256sum curve_fit.svg
cargo check --manifest-path compiler-next/Cargo.toml --workspace
cargo fmt --manifest-path compiler-next/Cargo.toml --all --check
git diff --check
```

Los runs del consumer y la validación XML se hicieron en un directorio temporal
para no introducir artefactos al worktree. No se ejecutaron Clippy ni todos los
tests del workspace: el cambio efectivo está limitado al consumer, documentos
y una suite de integración ya ejecutada íntegramente; `cargo check --workspace`
cubrió la compilación global.

## Archivos modificados

- `examples/scientific-curve-fitting/src/main.ae`;
- `examples/scientific-curve-fitting/README.md`;
- `examples/scientific-curve-fitting/REPORT.md`;
- `compiler-next/crates/aether-driver/tests/plots_multiseries_v1.rs`;
- `docs/reports/SCIENTIFIC_CURVE_FITTING_ERGONOMICS_V1_REPORT.md`.

## Limitaciones pendientes

La salida usa el formato shortest de `str`, por lo que hace visible el redondeo
binario de los coeficientes SVD (`1.0000000000000002` y
`1.9999999999999996`). La qualification compara con tolerancia y el README
presenta los valores matemáticos. No se agregó formateo ni se amplió el lenguaje
porque no es necesario para demostrar el ajuste y queda fuera de este milestone.
