# GRAPHICS-SVG-BACKEND-V1 — reporte final de implementación

Estado: **CLOSED**, 2026-10-30.

## Resultado

Se implementó `graphics.svg` conforme a
`GRAPHICS_SVG_BACKEND_ARCH_1` y su enmienda owning. La superficie pública es
exactamente:

```aether
public string render(ref graphics.Scene scene);
public void save(ref graphics.Scene scene, ref string path);
```

`render` produce el documento SVG/XML completo en memoria y `save` usa el
mismo serializer antes de llamar a `std.File.writeText`. Los errores de texto
se publican como `GraphicsTextException` antes de abrir el destino; los errores
nominales de IO se traducen a `GraphicsIoException`.

No se modificaron Foundation, Plots, el compiler, el runtime, Core, std ni las
garantías del lenguaje.

## Desbloqueo verificado

El reproducer `reproducers/graphics_svg_owning_buffer_growth.ae`, que había
aislado E0297, ahora pasa check, build y ejecución nativa en O0/O2. El backend
usa esa capacidad general cerrada por `OWNING-STRUCT-FIELD-REPLACEMENT-V1`; no
agrega excepción ni intrinsic para Graphics.

`SvgSerializer` es un `struct` local owning. Posee directamente:

- `Buffer<uint8> output`;
- `Buffer<SerializerState> states`;
- `Buffer<graphics.Rect> clips`.

Los tres buffers crecen geométricamente mediante replacement owning. El
serializer no escapa de `render`, y el único punto de publicación es
`std.Text.fromUtf8(&serializer.output, serializer.outputLength)`.

## Implementación

El backend vive en `graphics/src/svg.ae` y mantiene la dependencia unidireccional
`graphics.svg -> graphics`. Sus propiedades principales son:

- dos traversals read-only: definitions de clip y draws;
- state privado de transform, clip e ID con push/pop exacto;
- painter order idéntico al display list, sin sorting, batching o culling;
- wrappers canónicos por draw, con clip en scene coordinates y transform
  interior;
- lowering directo de point, line, polyline, rect, path y text;
- formatting numérico único mediante `str(float64)` y canonicalización de
  ambos ceros;
- RGB `#RRGGBB`, alpha separado y orden fijo de attributes;
- escaping XML independiente para text/attributes, validación de XML 1.0 y
  quoting CSS para named font families;
- documento determinista con LF, `<defs>` obligatorio e IDs densos locales;
- ninguna lista intermedia de points/path verbs ni copia de arenas Scene.

La complejidad queda en O(commands + payload + output bytes), con peak
O(output bytes + nesting depth + clips), además del string final y los
temporales escalares de formatting ya autorizados.

## Qualification dedicada

Se agregó
`compiler-next/crates/aether-driver/tests/graphics_svg_backend_v1.rs` y la
dependencia test-only versionada `roxmltree 0.20.0`. Los goldens completos son:

- `graphics/tests/goldens/empty.svg`;
- `graphics/tests/goldens/representative.svg`.

La suite ejecuta source-to-native en O0/O2 y cubre:

- Scene vacía y viewports `0x0`, `0xh`, `wx0`;
- XML declaration, namespace, viewport/viewBox, whitespace y LF final;
- todas las variantes de `Command` y painter order DOM;
- push/pop, composición no conmutativa, transform singular, clips anidados,
  redundantes, restaurados y zero-area;
- point normal/subnormal/extremo, line degenerada con las tres caps, polyline
  grande, rect zero-area y path multi-subpath con todos los verbs;
- FillOnly, StrokeOnly, FillAndStroke, ambas fill rules, todas las caps/joins,
  miter limits y alpha 0/1/intermedio/254/255;
- signed zero, subnormales y máximos finitos;
- texto ASCII/multibyte/emoji/combining, whitespace y los cinco caracteres XML;
- generic/default/named families, spaces, comma, keyword, quotes, backslash y
  escapes XML/CSS;
- todas las variantes de weight, slant, align y baseline;
- rechazo de NUL, cada rango de control XML-invalid, U+FFFE, U+FFFF y family
  vacía; form feed en named family se representa mediante escape CSS;
- atomicidad previa a IO, traducción de IOException y bytes exactos de `save`;
- parseo XML real, resolución de clip IDs, matrices, orden DOM, points/path y
  recuperación exacta de text/family;
- equivalencia byte por byte O0/O2 contra los mismos goldens;
- growth de output/state/clips y balance global de heap allocations/frees;
- HIR/MIR/SSA/LLVM ordinarios, `ReplaceOwned`, calls directas a Text/File y
  ausencia de InterfaceCall, registry, FFI, intrinsic o Plots.

## Gates finales

Ejecutados desde `compiler-next`, salvo indicación:

| Gate | Resultado |
|---|---|
| reproducer check/build/run O0/O2 | PASS |
| `aether check ../graphics -O0/-O2` | PASS |
| `aether build ../graphics -O0/-O2` | PASS |
| `aether run ../graphics/tests/svg_consumer -O0/-O2` | PASS |
| `cargo test -p aether-driver --test graphics_svg_backend_v1` | PASS — 11/11 |
| `cargo test -p aether-driver --test graphics_foundation_v1 --test text_utf8_builder_v1` | PASS — 16/16 |
| `cargo test -p aether-driver --test owning_struct_field_replacement_v1 --test ssa_store_provenance_v1` | PASS — 21/21 |
| `cargo fmt --all -- --check` | PASS |
| Clippy sobre el test dedicado con `-D warnings` | PASS |
| `git diff --check` | PASS |

## Archivos del milestone

- `graphics/src/svg.ae` — backend productivo;
- `graphics/tests/goldens/empty.svg` — golden de Scene vacía;
- `graphics/tests/goldens/representative.svg` — golden integral;
- `graphics/tests/svg_consumer` — consumer real del package y API pública;
- `compiler-next/crates/aether-driver/tests/graphics_svg_backend_v1.rs` —
  qualification funcional, estructural, IR y resources;
- `compiler-next/crates/aether-driver/Cargo.toml` y `Cargo.lock` — parser XML
  exclusivamente test-only;
- este reporte.

No se hizo commit ni push.

## Estado final

Todos los criterios de las secciones 26–28 del ARCH y la representación owning
de la enmienda tienen evidencia reproducible. No queda bloqueo de lenguaje ni
criterio SVG pendiente dentro del alcance V1.

**Estado final: CLOSED.**
