# GRAPHICS-FOUNDATION-ARCH-1 — reporte de cierre

Estado: **ARQUITECTURA CERRADA; NO IMPLEMENTADA**, 2026-10-19.

Documento normativo:
[GRAPHICS-FOUNDATION-ARCH-1](GRAPHICS_FOUNDATION_ARCH_1.md).

## Resultado

Se cerró una foundation 2D backend-independent basada en un builder mutable
one-shot que produce una `Scene` inmutable. La Scene es una display list
secuencial, no un retained scene graph: no hay nodo heap, identity, árbol,
dirty state ni dispatch dinámico por primitive.

La representación final contiene buffers contiguos de Commands, points de
polylines, PathVerbs, text records y bytes UTF-8. Line, Rect, transforms y
styles viajan inline. El orden de comandos es painter's order determinista y
el traversal cuesta O(commands + payload visitado), sin allocation por point.

No se modificó source productivo, compiler, runtime, Core, std, OAL ni tests.

## Contratos cerrados

- Coordenadas lógicas float64, origen top-left, X derecha, Y abajo.
- Viewport finito y no negativo; zero width/height válido.
- `Transform2D` afín especializada de seis scalars, column-vector y
  `current=current*local`.
- `Color` RGBA byte, RGB sRGB encoded, alpha lineal, straight alpha.
- Source-over y painter's order; sin blend modes.
- `Fill` con NonZero/EvenOdd y `Stroke` con width positivo, cap, join y miter
  limit; dash se difiere.
- Point visible como disco, line, compact polyline, Rect y Path.
- Path con MoveTo/LineTo/CubicTo/Close; sin copiar la superficie SVG.
- Text UTF-8 no ASCII-only, con position, size, color, physical alignment,
  baseline y request pequeño de font; shaping/bidi/fallback pertenecen al
  backend.
- Clip rectangular en scene coordinates y state explícito
  Push/Pop/Concat/Intersect, balanceado al congelar.
- Geometry no finita se rechaza. Plots segmenta/decide NaN e infinities antes
  de llamar a graphics.
- Imagen raster queda fuera de V1 porque no es necesaria para Plots inicial y
  abriría prematuramente pixel/decode/resource ownership.

## Ownership y costes

`SceneBuilder` posee arenas growable privadas y las implementa con
`Buffer<T>`/counters ordinarios. `finish` valida, copia prefijos a hasta cinco
buffers exactos, publica una Scene independiente, sella todos los aliases del
builder y libera su working storage. Esta copia final es O(total) y queda
visible; no se promete zero-copy.

Scene es una class final inmutable. Sus strong handles siguen Alias/ARC normal;
la última release destruye buffers y objeto. Backends reciben `ref Scene` y
recorren accessors que retornan payloads Copy, sin borrowed views escapables.

Agregar una polyline desde Array/view copia O(n) points para que Scene sea
self-contained. Las APIs incrementales de polyline/path evitan owners
temporales. Text copia contenido y named family a un byte arena: no retiene
strings fuente ni asigna un string por command.

## Backend y packages

No hay `Renderer` interface obligatoria, callbacks, registry ni vtable. Cada
backend define free functions estáticas —por ejemplo el futuro
`graphics.svg.render(ref Scene)`— y hace match exhaustivo sobre `Command`.
Foundation no contiene tags, attributes, CSS, XML, IDs ni formatting SVG.

La distribución será la OAL ordinaria `graphics`: foundation en package root
`graphics` y backend futuro en child `graphics.svg`, con dependencia sólo
hacia adentro. No pertenece a Core/std y no recibe privilegios. Si algún día
SVG necesita versionado independiente, las reglas del package manager exigen
otro root de registry; V1 elige una family/version común.

## Errores y lenguaje

Se distinguen `InvalidGeometryException`, `InvalidSceneStateException`,
`UnsupportedGraphicsFeatureException`, `GraphicsTextException` y
`GraphicsIoException`. Los estados cerrables por enums/structs no crean
exceptions. Bounds, overflow de allocation y OOM conservan traps generales.

Todo se expresa con structs/enums, concrete Buffers Copy, classes finales,
references, loops, exceptions y byte access existentes. No hay graphics
intrinsic ni cambio de compiler autorizado. Se registra como limitación futura
del lenguaje el almacenamiento general de class handles dentro de retained
aggregate/class graphs; no bloquea Scene V1 ni su traversal por un backend.

## Qualification acordada

El V1 probará commands/state/transforms/clips, todos los styles, Path, bytes
textuales exactos, copies y lifetimes de inputs, aliases/sealing, spans,
allocations por arena, viewport cero, extreme finite, rechazo exhaustivo de
NaN/Inf, equivalencia O0/O2 y ausencia source/IR de vocabulario/backend SVG o
dispatch dinámico.

Foundation no usa screenshots. Golden SVG corresponde al milestone del
backend y comparación de imágenes al eventual raster renderer.

## Secuencia siguiente

```text
GRAPHICS-FOUNDATION-V1
GRAPHICS-SVG-BACKEND-ARCH-1
GRAPHICS-SVG-BACKEND-V1
PLOTS-ARCH-1
```

CLOSED
