# PLOTS-ARCH-1 — reporte de diseño

Estado: **ARQUITECTURA E IMPLEMENTACIÓN V1 CLOSED**, revalidado 2026-10-31.

Documento normativo: [PLOTS-ARCH-1](PLOTS_ARCH_1.md). Implementación y
evidencia: [PLOTS-2D-LINE-V1](PLOTS_2D_LINE_V1_REPORT.md).

## Resultado

El diseño del primer vertical nativo se implementó sin ampliar su alcance:
una serie XY lineal, una `Figure2D` explícita e inmutable, construcción de una
`graphics.Scene` nueva por llamada y un adapter `plots.svg` que delega al
backend oficial.

El bloqueo histórico `E0401` quedó resuelto por
`OOP-OWNING-STRING-FIELDS-V1`. La Figure posee el Buffer de samples y los tres
owners `string`; no conserva borrows de los argumentos. La qualification
integral O0/O2 demuestra mutation-after-call, aliases ARC, cleanup, geometría,
painter order, goldens XML y equivalencia byte por byte.

## Decisiones preservadas

- `DataPoint(x,y)` mantiene unidos los samples y separa data coordinates de
  `graphics.Point`.
- Auto limits usan pares finitos; explicit limits habilitan clipping sin
  descartar samples.
- NaN e infinities separan runs y nunca llegan a Graphics.
- Intervals degenerados se expanden por la regla fija 5%/1 unit.
- La transformación materializada conserva stroke width en scene units e
  invierte Y.
- Layout, cinco ticks, textos y painter order son deterministas.
- Las polylines se construyen incrementalmente sin arrays transformados.
- SVG sólo se obtiene mediante `graphics.svg.render/save`.

No existen current figure, registry, cache, backend de sesión, Python, NumPy,
Matplotlib, FFI ni intrinsics específicos. Scatter, histogram, bar, grids,
nice ticks, log axes, múltiples series, themes, notebooks e interactividad
siguen fuera del milestone.

## Qualification

El consumer externo y el package pasan check/build/run O0/O2. La suite
dedicada pasa 5/5, los tres goldens completos se parsean como XML y coinciden
byte por byte entre modos, y HIR/MIR/SSA/LLVM conservan las operaciones
generales de ownership. `cargo test --workspace -j 1`, rustfmt, Clippy sin
regresiones y `git diff --check` también pasan.

No se modificaron compiler, runtime, Core, std, Graphics, Plots legacy ni
ejemplos personales. No se hizo commit ni push.

**Estado final: PLOTS-ARCH-1 CLOSED; PLOTS-2D-LINE-V1 CLOSED.**
