# GRAPHICS-SVG-BACKEND-ARCH-1 — reporte de diseño

Estado: **BLOCKED**, 2026-10-19.

Documento de arquitectura:
[GRAPHICS-SVG-BACKEND-ARCH-1](GRAPHICS_SVG_BACKEND_ARCH_1.md).

## Resultado

Se diseñó por completo el lowering read-only de `graphics.Scene` a un documento
SVG 2/XML 1.0 UTF-8 determinista. No se modificó source productivo, compiler,
runtime, Core, std, la foundation graphics ni tests ejecutables.

La API futura queda en `package graphics.svg`:

```aether
public string render(ref graphics.Scene scene);
public void save(ref graphics.Scene scene, ref string path);
```

`save` reutiliza `render` y `std.File.writeText`; los fallos externos se
traducen a `GraphicsIoException`. La dependencia es únicamente hacia
`graphics` y std, nunca desde foundation hacia el backend.

## Contrato SVG cerrado

- XML declaration UTF-8, root `svg`, namespace, width/height unitless y
  `viewBox="0 0 W H"` exactos;
- output estructural con LF, indentation, attributes y tags en orden fijo;
- float64 mediante `str`, locale-independent y shortest-round-trip, con `-0`
  canonicalizado a `0` y scientific notation permitido;
- painter order idéntico al traversal de Commands, sin sorting, batching o
  culling;
- state stack privado y mapping exacto
  `Transform2D -> matrix(m11 m12 m21 m22 tx ty)`;
- un clip determinista acumulado por `IntersectClipRect`, IDs densos y
  `clipPathUnits="userSpaceOnUse"`;
- wrapper de clip exterior y transform interior por cada draw, manteniendo el
  clip en scene coordinates y strokes/text en user space transformado;
- RGB `#RRGGBB`, alpha straight mediante fill/stroke opacity y sin
  premultiplication;
- lowering directo y único para point, line, polyline, rect, path y text;
- FillOnly/StrokeOnly/FillAndStroke, fill rules, caps, joins y miter completos;
- point como circle con scale local `0.5`, evitando underflow de radius para el
  menor diámetro finito;
- paths absolutos `M/L/C/Z`, points de polyline escritos sin lista intermedia;
- text con whitespace preservado, align/baseline/font mappings cerrados y
  shaping/font fallback delegado al viewer;
- named fonts como un único CSS quoted family request, sin font lookup ni
  embedding.

## XML y errores textuales

Se separaron escaping de text nodes, escaping de XML attributes y quoting CSS
de named families. Ampersand, angle brackets, quotes, apostrophe, TAB, LF y CR
tienen formas canónicas. UTF-8 multibyte y combining marks se conservan sin
normalización.

NUL y los controles/scalars fuera de la producción `Char` de XML 1.0 no pueden
representarse ni con character references: producen `GraphicsTextException`.
Nunca se borran ni sustituyen bytes. Una font ausente en el viewer no es error.

SVG V1 soporta todos los Commands V1; no usa
`UnsupportedGraphicsFeatureException` como escape para un renderer parcial.

## Allocation y determinism

El serializer previsto usa un `Buffer<uint8>` growable, stack proporcional a
nesting y metadata proporcional a clip count. Hace dos traversals, no muta ni
copia las arenas Scene y apunta a:

```text
O(commands + payload + output bytes) tiempo
O(output bytes + nesting depth + clip count) peak
```

IDs, whitespace, numeric formatting, colors y escaping dependen sólo de Scene.
No hay timestamps, randomness, unordered maps, locale ni host font lookup. La
qualification futura compara goldens completos y bytes O0/O2, y además parsea
XML para inspeccionar viewport, orden, transforms, clips, paths y texto. No usa
screenshots ni sólo substring checks.

## Bloqueo real

La toolchain vigente permite construir `Buffer<uint8>`, observar bytes de
strings con `std.Text.byteAt`, formatear float64 canónicamente y escribir un
`string` completo. No ofrece, sin embargo, una operación pública para publicar
un string desde un prefijo UTF-8 de bytes, un `TextBuilder.finish` equivalente
ni un join lineal dinámico.

La única alternativa source disponible sería concatenar strings dentro del
loop. Cada concat copia ambos operands, por lo que rendering sería cuadrático y
violaría expresamente el contrato. String interpolation no sirve porque su
número de fragments es estático; `List<string>` tampoco tiene join lineal y
`Buffer<string>` está excluido.

El prerrequisito aislado es una capability general de std, conceptualmente
`std.Text.fromUtf8(ref Buffer<uint8>, length) -> string` o un builder
equivalente, con validación y publicación O(n). Debe diseñarse e implementarse
fuera de graphics y sin allowlist, FFI ni intrinsic SVG.

Por ese motivo el estado correcto es **BLOCKED**. El siguiente milestone no es
todavía `GRAPHICS-SVG-BACKEND-V1`, sino el vertical general de construcción
UTF-8. Cuando cierre, el diseño SVG ya queda listo para implementación sin
reabrir Scene ni Command.

## Archivos y cierre

Se agregaron solamente:

```text
docs/architecture/GRAPHICS_SVG_BACKEND_ARCH_1.md
docs/architecture/GRAPHICS_SVG_BACKEND_ARCH_1_REPORT.md
```

BLOCKED
