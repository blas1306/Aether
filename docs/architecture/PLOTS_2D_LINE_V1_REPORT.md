# PLOTS-2D-LINE-V1 — reporte de implementación y qualification

Estado: **CLOSED**, 2026-10-31.

Documento normativo: [PLOTS-ARCH-1](PLOTS_ARCH_1.md).

## Resultado

El vertical nativo de plotting 2D quedó implementado como package OAL
`plots`, con adapter `plots.svg`. Expone exactamente `DataPoint`, `Limits`,
`LimitMode`, `LineStyle`, `FigureOptions`, `defaultOptions`, `Figure2D`,
`line`, `Figure2D.scene`, `plots.svg.render` y `plots.svg.save`.

`Figure2D` posee un `Buffer<DataPoint>` exacto y tres fields owning `string`.
No retiene el `Array`, `FigureOptions`, referencias interiores ni storage del
caller. Los aliases de Figure conservan identidad ARC; cada `scene()` publica
una Scene nueva e independiente. La copia textual desde `FigureOptions`
reconstruye bytes UTF-8 mediante las APIs generales `std.Text.byteAt` y
`std.Text.fromUtf8`, incluidos UTF-8 y U+0000, antes de instalar los owners en
la class.

La representación privada materializa viewport y estilo como sus componentes
Copy escalares. Esto evita retener aggregates importados en fields de class y
no cambia la superficie, el ownership ni la semántica pública del contrato.
Los datos permanecen en el `Buffer<DataPoint>` privado normativo y los textos
son owners directos de la class.

No se modificaron compiler, runtime, Core, std, Graphics Foundation, Graphics
SVG, Plots legacy ni ejemplos personales. No se hizo commit ni push.

## Preflight revalidado

Los dos projects `reproducers/plots_preflight` y
`reproducers/plots_preflight_positive` pasaron `check`, `build` y `run` en O0
y O2. El reproducer antes bloqueado confirma la admisión general del field
owning `string`; el positivo conserva la evidencia de Buffer privado, copia de
samples, aliases ARC, `scene()` y delegación SVG. El reproducer de
transformación pasó en ambos modos con el orden numérico normativo.

## Implementación geométrica

La implementación conserva el contrato de PLOTS-ARCH-1:

- auto limits sobre pares finitos y explicit limits autoritativos;
- expansión degenerada `max(1, abs(c)*0.05)` con fallback unilateral;
- rechazo nominal de spans y transformaciones no representables;
- segmentación por NaN, +Inf y -Inf sin conexión entre finite runs;
- transformación `xv = L + (x-xmin)*sx` e Y invertido en el orden fijado;
- margins `72/24/48/64`, cinco ticks por eje y labels mediante `str`;
- background, clip de datos, runs, frame, ticks, labels y title en painter
  order normativo;
- polyline incremental sin arrays temporales de points transformados;
- `DrawPoint` para todo finite run aislado;
- estilo Butt/Miter/4 y diámetro singleton `max(2, line.width)`.

`plots.svg` sólo crea la Scene temporal y llama directamente a
`graphics.svg.render/save`. No contiene XML, inspección de Commands, caché,
estado global ni dependencia Python.

## Ownership, lifecycle y errores

El consumer y la suite dedicada mutan samples y los tres textos de options
después de `line`; la Figure y sus Scenes conservan los valores originales.
Dos llamadas a `scene()` retornan identidades distintas. Los tests de error en
O0/O2 ejercen cleanup de temporales y owners durante construcción y lowering.
Las suites globales de owning string fields, class Buffer fields, exceptions y
ARC volvieron a pasar dentro de `cargo test --workspace`.

La clasificación observada es exacta:

| Condición | Excepción |
|---|---|
| input vacío | `EmptySeriesException` |
| ningún par finito | `NoFiniteDataException` |
| viewport o line width inválido | `InvalidFigureException` |
| explicit endpoints no finitos o invertidos | `InvalidLimitsException` |
| span, expansión o transformación no representable | `PlotRangeException` |
| texto SVG inválido | `graphics.GraphicsTextException` sin reclasificar |

## Qualification dedicada

`compiler-next/crates/aether-driver/tests/plots_2d_line_v1.rs` contiene cinco
gates integrales y pasa 5/5:

1. consumer público real O0/O2;
2. categorías nominales de error y propagación de Graphics;
3. runs, singleton, clipping, anchors, transformación y painter order exactos;
4. tres goldens SVG completos, XML válido y bytes idénticos O0/O2;
5. inspección HIR/MIR/SSA/LLVM y pureza nativa.

Los goldens versionados son:

- `plots/tests/goldens/parabola.svg`, curva matemática rotulada y legible;
- `plots/tests/goldens/gaps.svg`, múltiples runs y singletons por NaN;
- `plots/tests/goldens/singleton.svg`, ambos domains degenerados.

La inspección de Commands verifica clip entre push/pop, puntos transformados
fuera y dentro del plotRect, ausencia de conexiones sobre gaps, orden de runs,
frame posterior a datos, diez ticks, diez tick labels, axis labels, rotación Y
y title. Los casos de limits cubren auto, explicit, degenerados, overflow de
span y overflow de transformación.

HIR/MIR/SSA contienen `Buffer` y `StringFieldAlias`; LLVM contiene cleanup de
strings y calls ordinarias de SceneBuilder. Source e IR no incorporan Python,
NumPy, Matplotlib, FFI, registry, builtin Plots, intrinsic ni allowlist.

## Gates finales

Ejecutados con `CARGO_INCREMENTAL=0`, `TMPDIR=/home/blasm/tmp`, artefactos en
`compiler-next/target` y paralelismo Cargo `-j 1`:

| Gate | Resultado |
|---|---|
| preflight negativo histórico y positivo `check/build/run -O0/-O2` | PASS |
| transformación preflight `run -O0/-O2` | PASS |
| package `plots` `check/build -O0/-O2` | PASS |
| consumer externo `check/build/run -O0/-O2` | PASS |
| qualification dedicada | PASS — 5/5 |
| goldens O0/O2, comparación completa y XML | PASS — 3/3 |
| `cargo test --workspace -j 1` | PASS completo, incluidos 220/220 verticales y doc-tests |
| `cargo fmt --all -- --check` | PASS |
| `cargo clippy --workspace --all-targets -j 1` | PASS con warnings preexistentes; cero warnings del test Plots |
| `git diff --check` | PASS |

Los warnings Clippy preexistentes permanecen en las categorías ya registradas:
`assert_is_empty`, `needless_borrows_for_generic_args`, `match_same_arms`,
`too_many_lines` y afines en código ajeno. El único warning inicialmente
señalado en el test nuevo (`needless_raw_string_hashes`) se corrigió antes del
cierre y la repetición de Clippy no reportó `plots_2d_line_v1.rs`.

## Archivos del milestone

- `plots/aether.toml`, lockfile y `plots/src/lib.ae`;
- `plots/src/svg.ae`;
- `plots/tests/consumer`;
- `plots/tests/golden_generator`;
- `plots/tests/goldens/*.svg`;
- `compiler-next/crates/aether-driver/tests/plots_2d_line_v1.rs`;
- este reporte y la actualización de estado de PLOTS-ARCH-1.

Todos los criterios esenciales de PLOTS-ARCH-1 §19 tienen evidencia O0/O2 y
los gates globales permanecen verdes.

**Estado final: PLOTS-2D-LINE-V1 CLOSED.**
