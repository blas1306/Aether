# PLOTS-TICK-LABEL-FORMAT-V1

Estado: **CLOSED**, 2026-11-22.

## Resultado

`Figure2D.scene()` presenta ahora los cinco ticks de cada eje con una política
decimal contextual. La política usa `std.Format.fixed(float64, usize)` y
`std.Format.scientific(float64, usize)` de FORMAT-V2 para todo rounding; Plots
no implementa rounding mediante casts, escalado del valor, sumas de `0.5` ni
un formatter decimal alternativo.

El bloqueo registrado el 2026-11-20 queda resuelto por FORMAT-V2, cerrado el
2026-11-21. Se preservó ese vertical preexistente sin modificar compiler,
runtime ni `str(float*)`. Los cambios de producto de esta tarea están
localizados en la generación privada de texto de ticks dentro de Plots.

Los valores, límites, cinco posiciones, transformaciones, datos científicos,
geometría, clipping, painter order, comandos de Scene y atributos numéricos SVG
no cambian. Sólo cambiaron ocho contenidos textuales de ticks en dos goldens.

## Política matemática final

Para cada eje, la selección del formato materializa exactamente:

```text
t[i] = minimum + (maximum - minimum) * i / 4,  i = 0..4
```

mediante el helper `tickValue` existente. Un valor que compara igual a cero se
canonicaliza a `+0.0`, como antes. No se modifican el locator, los límites ni
las posiciones gráficas.

1. Se obtiene el menor `spacing = t[i] - t[i-1]` estrictamente positivo. Los
   ticks binary64 repetidos no contribuyen al spacing y pueden compartir texto.
   Si no existe spacing positivo se selecciona inmediatamente el fallback
   canónico para todo el eje.
2. El orden decimal `e = floor(log10(spacing))` se obtiene sin logaritmos ni
   casts: una copia positiva se escala por diez dentro de las cotas cerradas
   `[-324, 309]`. Los contadores y cálculos de precisión usan `int` y sus rangos
   máximos son pequeños, por lo que no pueden desbordar.
3. El primer quantum conceptual es `10^(e-1)`, una década menor que el spacing.
   Para fixed esto produce `max(0, 1-e)` cifras fraccionarias. Para scientific,
   si `m` es el orden decimal de la mayor magnitud del eje, se solicitan
   `clamp(m-e+1, 0, 16)` cifras tras el punto, es decir, hasta 17 cifras
   significativas.
4. Fixed se usa sólo cuando todos los valores no nulos están en el rango de
   órdenes legible `[-6, 20]`, la precisión inicial no supera 12 cifras
   fraccionarias y la longitud prevista no supera 24 bytes. Esto impide pedir
   strings fixed desproporcionados para subnormales, magnitudes extremas o
   intervalos muy estrechos. Los demás ejes usan scientific.
5. FORMAT-V2 redondea el binary64 exacto con nearest, ties-to-even. Plots sólo
   retira ceros fraccionarios finales y el punto que quede solo; no toca la
   mantisa, el exponente ni el resultado del rounding. Cero se presenta como
   `0`, también en un eje scientific.
6. Los cinco candidatos se comprueban como conjunto. Cada texto se convierte
   con `std.Text.parseDouble`; todo tick distinto de cero debe seguir siendo no
   cero y cada par de ticks binary64 distintos debe conservar orden numérico
   estricto. Para ticks binary64 iguales se exige el mismo valor parseado. No
   se usa orden lexicográfico.
7. Ante colisión, inversión, underflow/overflow de parseo o pérdida a cero se
   agrega una cifra y se reintenta. Scientific termina en 17 cifras
   significativas; fixed aplica la cota equivalente, compensando ceros
   iniciales en valores menores que uno.
8. Si ningún candidato acotado demuestra el contrato, todo el eje usa
   `str(t[i])`. El fallback canónico es determinista, round-trip y nunca mezcla
   políticas dentro del eje.

La selección retorna únicamente un `TickFormat` Copy (`canonical`, `fixed`,
`precision`). Los strings se materializan al dibujar cada tick. Este diseño
evita retener agregados owning a través de fronteras que pueden propagar unwind
y no requiere ampliar las capacidades del compilador.

## Binary64, decimal comunicado y texto

La implementación distingue tres niveles:

- `t[i]` es el binary64 que determina el valor del tick y permanece intacto;
- FORMAT-V2 obtiene el decimal redondeado contextual que se comunica;
- `trimTickText` cambia sólo la ortografía de ese mismo decimal retirando ceros
  fraccionarios redundantes.

`parseDouble` redondea el decimal candidato nuevamente a binary64. Por ello no
es una prueba de comparación decimal exacta entre strings arbitrarios. Aquí se
usa de forma conservadora: se exige orden binary64 estricto de los resultados,
de modo que dos decimales distintos que colapsen al mismo binary64 son
rechazados y fuerzan más precisión o fallback. La estructura de fixed y
scientific proviene exclusivamente de FORMAT-V2.

## Casos numéricos calificados

La suite `plots_tick_label_format_v1.rs` compila y ejecuta el package real en O0
y O2 y compara SVG byte a byte entre ambos modos. Cubre:

| Caso | Resultado observado |
| --- | --- |
| `1.0000000000000002` con spacing amplio | `1` |
| `4.999999999999999` con spacing amplio | `5` |
| `6.999999999999998` con spacing amplio | `7` |
| enteros negativos/positivos y cero | `-1, -0.5, 0, 0.5, 1` |
| cuartos | `0, 0.25, 0.5, 0.75, 1` |
| cerca de cero, `0..4e-7` | `0, 1e-7, 2e-7, 3e-7, 4e-7` |
| borde fixed, `1e-6..5e-6` | fixed `0.000001` a `0.000005` |
| intervalo de pocos ULP alrededor de uno | cinco posiciones ordenadas sin colisión |
| subnormales | scientific compacto, parseable y ordenado |
| `1e100..5e100` | `1e+100` a `5e+100` |
| carry alrededor de diez | `9.9996, 9.9998, 10, 10.0002, 10.0004` |
| ticks binary64 repetidos cerca de `1e20` | repetición permitida; endpoints distintos |

También quedan cubiertos signed zero mediante la canonicalización a `0`,
transiciones fixed/scientific, valores próximos a potencias de diez, trimming,
carry, aumento de precisión, unicidad, orden y presencia del fallback canónico.
Un valor negativo o positivo no nulo que redondee a cero no puede ser aceptado.

La prueba subnormal usa una Figure vacía con límites explícitos para aislar el
formatter. Una serie sobre un span subnormal puede seguir encontrando el
`PlotRangeException` preexistente si el factor de transformación geométrica
desborda; esa limitación no pertenece al texto de ticks y no fue modificada.

## Compatibilidad de Scene, SVG y goldens

Se calificaron line legacy, `plotFunction`, invocables, multiseries, límites
Auto/Explicit/mixtos y el consumer scientific curve fitting. Las pruebas de
comandos y los SVG confirman que permanecen byte-idénticos:

- viewport, plot rectangle, transforms y clip paths;
- datos, polylines, points, markers y estilos;
- cantidad, posición y longitud de tick marks;
- painter order y cardinalidad de comandos;
- títulos, nombres de ejes y atributos numéricos SVG.

Los goldens `parabola.svg`, `gaps.svg` y `singleton.svg` no cambiaron. Sólo se
actualizaron:

- `function_sine.svg`: los ticks X `-pi, -pi/2, pi/2, pi` pasan a
  `-3.1, -1.6, 1.6, 3.1`;
- `multiseries.svg`: las mismas cuatro sustituciones de texto.

En ambos diffs, el tick central `0`, los cinco ticks Y, datos, geometría,
atributos y textos no relacionados permanecen idénticos. Los outputs completos
son byte-idénticos entre O0 y O2.

## Qualification ejecutada

Ejecutada desde `compiler-next`:

```text
cargo test -p aether-driver \
  --test plots_2d_line_v1 \
  --test plots_function_sampling_v1 \
  --test plots_invocable_integration_v1 \
  --test plots_multiseries_v1 \
  --test plots_tick_label_format_v1
```

Resultado: **PASS**, 33 pruebas, 0 fallos.

Suites de dependencia e integración:

```text
cargo test -p aether-driver \
  --test graphics_foundation_v1 \
  --test graphics_svg_backend_v1 \
  --test format_v1 \
  --test format_v2 \
  --test numeric_parsing_v1 \
  --test module_std_v1
```

Resultado: **PASS**, 50 pruebas, 0 fallos.

Gates generales:

| Gate | Resultado |
| --- | --- |
| `cargo check --workspace` | PASS |
| `cargo fmt --all --check` | PASS |
| `cargo clippy --workspace --all-targets -j 1` | PASS; 10 warnings preexistentes, ninguno de esta tarea |
| `git diff --check` | PASS |

No se ejecutó `cargo test --workspace`: el cambio está localizado en Plots y se
ejecutaron las suites completas de Plots, Graphics/SVG, FORMAT-V1/V2, parsing y
módulos, incluidas sus matrices O0/O2. El workspace completo ya había sido
calificado por FORMAT-V2 en el checkout preservado; no se declara una nueva
ejecución global como PASS.

## Archivos modificados

- `plots/src/lib.ae`: selección contextual, formatting, trimming, validación y
  fallback privados; aplicación exclusiva a los textos X/Y de ticks.
- `compiler-next/crates/aether-driver/tests/plots_tick_label_format_v1.rs`:
  qualification numérica, SVG y O0/O2.
- `plots/tests/goldens/function_sine.svg`: cuatro textos X actualizados.
- `plots/tests/goldens/multiseries.svg`: cuatro textos X actualizados.
- `docs/reports/PLOTS_TICK_LABEL_FORMAT_V1_REPORT.md`: cierre y evidencia.

Se preservaron los cambios ajenos preexistentes de FORMAT-V2 bajo
`compiler-next` y `docs/architecture/FORMAT_V2_REPORT.md`, así como los demás
reportes no versionados. No se modificaron ejemplos personales, Graphics, SVG,
otras OAL, API pública ni compiler como parte de este vertical.

## Limitaciones

La política no es un nice tick locator: conserva exactamente los cinco ticks
existentes. Tampoco ofrece configuración pública de precisión, callback de
formatting, exponent offset, escalas logarítmicas, grids ni unidades. El
umbral fixed/scientific y las cotas de legibilidad son política privada V1.

El fallback completo puede conservar spellings canónicos largos en intervalos
extremos; esto es deliberado cuando la simplificación no puede demostrar
unicidad y orden. No se inició otro vertical.
