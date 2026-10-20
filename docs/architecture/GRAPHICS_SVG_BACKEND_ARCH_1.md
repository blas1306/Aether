# GRAPHICS-SVG-BACKEND-ARCH-1 — backend SVG determinista de `graphics.Scene`

Estado: **BLOCKED**, 2026-10-19.

Este milestone es exclusivamente documental. Diseña el primer backend real de
graphics, `graphics.svg`, pero no modifica source productivo, compiler,
runtime, Core, std, packages OAL ni tests ejecutables.

La autoridad de la Scene y de todos sus Commands permanece en:

- [GRAPHICS-FOUNDATION-ARCH-1](GRAPHICS_FOUNDATION_ARCH_1.md);
- [GRAPHICS-FOUNDATION-ARCH-1-REPORT](GRAPHICS_FOUNDATION_ARCH_1_REPORT.md);
- [GRAPHICS-FOUNDATION-V1-REPORT](GRAPHICS_FOUNDATION_V1_REPORT.md).

Este documento no rediseña `Scene`, `Command`, geometry, paint, text ni state.
Fija sólo su lowering a SVG/XML y la frontera pública del backend.

Las referencias de formato externo son
[XML 1.0 Fifth Edition](https://www.w3.org/TR/xml/),
[SVG 2](https://www.w3.org/TR/SVG2/), sus capítulos de
[coordinates](https://www.w3.org/TR/SVG2/coords.html),
[painting](https://www.w3.org/TR/SVG2/painting.html) y
[text](https://www.w3.org/TR/SVG2/text.html), y
[CSS Syntax Level 3](https://www.w3.org/TR/css-syntax-3/) para el quoting de
named font families. Esas especificaciones gobiernan la interpretación del
documento; la forma canónica de bytes producida por Aether la fija este ARCH.

El contrato de target se cierra por completo, pero la implementación queda
bloqueada por una capability general ausente: Aether puede observar bytes de
un `string` y construir un `Buffer<uint8>`, pero no puede publicar como
`string` un prefijo UTF-8 de ese buffer. Usar `result = result + fragment` en
el loop sería cuadrático y contradice este milestone. La sección 22 aísla el
prerrequisito; no se autoriza un intrinsic ni un privilegio para
`graphics.svg`.

## 1. Resultado y frontera pública

La superficie V1 será exactamente:

```aether
package graphics.svg;

public string render(ref graphics.Scene scene);
public void save(ref graphics.Scene scene, ref string path);
```

Se incluyen ambas operaciones:

- `render` es la operación autoritativa y devuelve un documento SVG completo;
- `save` llama al mismo serializer, obtiene primero el `string` completo y lo
  entrega a `std.File.writeText`;
- no hay serializer duplicado, stream, callback, options, registry dinámico ni
  overloads V1;
- `save` es `void`, coherente con la API vigente de `std.File.writeText`; un
  retorno `int` no aportaría información tipada útil.

`render` recibe un borrow compartido. No retiene, copia ni muta la Scene.
`save` no abre el archivo hasta que rendering, validación textual y
materialización del string finalizaron con éxito.

## 2. Package y dirección de dependencias

El backend pertenece a la misma distribución OAL que la foundation:

```text
graphics             foundation
graphics.svg         backend child
```

El futuro source puede vivir en una unidad como `graphics/src/svg.ae` con
declaración `package graphics.svg;`. El discovery vigente admite source units
descendientes bajo el root de la distribución.

Las dependencias permitidas son:

```text
graphics.svg -> graphics
graphics.svg -> std.Text
graphics.svg -> std.File       // sólo save
graphics.svg -> std.IO         // clasificación/catch de IO
```

Nunca existe el edge inverso `graphics -> graphics.svg`. No se modifica
`graphics/src/lib.ae`, no se agrega registro de backends y no hay compiler o
runtime privilege, FFI, browser embebido, renderer dinámico, vtable ni callback
por command.

## 3. Perfil de documento

El resultado es un documento XML 1.0 UTF-8 y SVG 2 autocontenido. Su prólogo y
root son normativos:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="W" height="H" viewBox="0 0 W H">
  ...
</svg>
```

Decisiones cerradas:

- se emite exactamente la declaración XML mostrada;
- no se emite BOM, doctype, comentario, metadata, `version`, CSS global ni
  namespace adicional;
- el namespace es exactamente `http://www.w3.org/2000/svg`;
- `width` y `height` contienen los números unitless de `Scene.viewport()`;
- `viewBox` es exactamente `0 0 width height`;
- no se agrega sufijo `px`, unidad física, DPI ni escala raster;
- la igualdad numérica entre viewport externo y `viewBox` establece el mapping
  inicial uno-a-uno en unidades SVG. El viewer o embedding puede escalar el
  documento completo, como permite SVG, pero el backend no reinterpreta la
  unidad de Graphics;
- no se emite `preserveAspectRatio`: con width/height y viewBox de igual ratio,
  el valor SVG inicial no agrega transformación;
- width o height cero se serializa como `0`. SVG deshabilita el rendering de un
  viewport cuyo `viewBox` tiene una dimensión cero, que coincide con la Scene
  sin área visible;
- el canvas inicial es transparente y las pinturas usan el painter model
  source-over ordinario de SVG.

Todo whitespace estructural usa LF, nunca CRLF: dos espacios por nivel, un tag
por línea y exactamente un LF final después de `</svg>`. El contenido textual
se escapa de modo que tampoco introduce saltos estructurales.

## 4. Orden determinista de elementos y attributes

El documento siempre contiene primero un único `<defs>`, incluso para una
Scene vacía. Dentro de `defs` aparece el clip inicial y luego un `clipPath` por
cada `IntersectClipRect`, en orden de traversal. Después aparecen únicamente
los draws, también en traversal estricto.

El orden de attributes es parte del formato golden, aunque XML no le asigne
semántica:

1. identity/reference (`id`, `clipPathUnits`, `clip-path`, `transform`);
2. geometry en orden natural (`x`, `y`, `width`, `height`; `x1`, `y1`, ...);
3. fill: `fill`, `fill-opacity`, `fill-rule`;
4. stroke: `stroke`, `stroke-opacity`, `stroke-width`, `stroke-linecap`,
   `stroke-linejoin`, `stroke-miterlimit`;
5. text: `font-family`, `font-size`, `font-weight`, `font-style`,
   `text-anchor`, `dominant-baseline`, `direction`, `writing-mode`,
   `xml:space`.

Un atributo no aplicable se omite sólo según las reglas explícitas de este
documento. No se usan maps, reflexión ni iteration sobre un property bag.

## 5. Autoridad numérica

Existe un único helper privado conceptual `appendNumber` para todo `float64`
finito emitido en geometry, transforms, viewport y styles.

Su policy es:

- si `value == 0.0`, emite `0`, por lo que `-0` se canonicaliza;
- para cualquier otro valor usa exactamente los bytes de `str(value)`;
- por FORMAT-V1, `str(float64)` es shortest-round-trip, locale-independent,
  usa punto decimal, `e` minúscula y signo explícito en el exponente;
- no se prohíbe scientific notation. Forzar fixed para extremos aumentaría
  tamaño, complejidad y riesgo sin beneficio SVG;
- NaN e infinities son imposibles en una Scene válida y no reciben spelling
  SVG alternativo.

Ejemplos normativos incluyen `0`, `1.5`, `1e+21`, `1e-7`,
`1.7976931348623157e+308` y `5e-324`. Los extremos finitos se escriben como
números SVG; el serializer no los clampa, satura ni narrowea.

O0 y O2 deben ejecutar las mismas operaciones float64 en el mismo orden. No se
permite `%f`, `printf`, `snprintf`, formatter C, locale ambiental ni
reassociation/fast-math.

Los integers internos —índices de clip y bytes de color— usan helpers ASCII
decimales/hex privados deterministas. No se interpolan addresses ni hashes.

## 6. XML 1.0, UTF-8 y escaping

La Scene garantiza UTF-8 válido, pero XML 1.0 admite sólo estos scalars:

```text
U+0009, U+000A, U+000D,
U+0020..U+D7FF,
U+E000..U+FFFD,
U+10000..U+10FFFF
```

El backend recorre y decodifica los spans sin normalizar Unicode. U+0000,
U+0001..U+0008, U+000B, U+000C, U+000E..U+001F, U+FFFE y U+FFFF no pueden
aparecer ni literalmente ni mediante numeric character reference en XML 1.0.
Si aparecen en text content o en una family `Named`, `render` lanza
`GraphicsTextException`.

No se borra, reemplaza, translitera ni convierte a U+FFFD ningún scalar. C1,
combining marks, noncharacters que sí caen dentro de la producción XML `Char`
y UTF-8 multibyte se conservan byte por byte.

### 6.1 Text node content

`appendTextContent` es independiente del escaper de attributes. Produce:

| Input | Output XML |
|---|---|
| `&` | `&amp;` |
| `<` | `&lt;` |
| `>` | `&gt;` |
| `"` | `&quot;` |
| `'` | `&apos;` |
| TAB | `&#9;` |
| LF | `&#10;` |
| CR | `&#13;` |
| otro XML `Char` | sus bytes UTF-8 originales |
| XML-invalid | `GraphicsTextException` |

Escapar también quotes en un text node no es necesario para well-formedness,
pero fija una forma canónica única. Las referencias de CR/LF/TAB evitan la
normalización de line endings y mantienen el formato estructural en una línea.

### 6.2 XML attribute values

Todos los attributes usan delimitador `"`. `appendXmlAttribute` aplica la
misma tabla de cinco entities y tres numeric whitespace references. Esto evita
que XML attribute-value normalization convierta TAB/LF/CR en espacios. Los
otros XML `Char` se copian en UTF-8; cualquier scalar inválido produce
`GraphicsTextException` cuando el atributo procede de Scene text.

Los attributes generados internamente contienen sólo ASCII conocido y no
pueden provocar esa excepción.

### 6.3 Atomicidad textual

La validación puede ocurrir mientras se llena el buffer privado: ningún prefijo
es observable. `render` publica sólo el string completo. Como `save` llama a
`render` antes de `writeText`, un `GraphicsTextException` no crea ni trunca el
archivo destino.

## 7. Painter order y estructura por draw

Se recorre exactamente:

```text
index = 0
while index < scene.commandCount()
    command = scene.commandAt(index)
    match command ...
    index += 1
```

No hay sorting, batching, opacity analysis, culling, eliminación de geometry
degenerada ni reordenamiento de primitives. Los comandos de state actualizan
el estado privado; cada command de dibujo emite un sibling en la misma posición
relativa.

Cada draw se aísla con estos grupos efímeros:

```xml
  <g clip-path="url(#graphics-clip-N)">
    <g transform="matrix(a b c d e f)">
      PRIMITIVE
    </g>
  </g>
```

Ambos grupos se abren inmediatamente antes de la primitive y se cierran
inmediatamente después. Se emiten incluso para clip inicial e identity
transform. Esta redundancia pequeña hace el formato canónico y resuelve dos
propiedades importantes:

- el clip wrapper vive en scene coordinates;
- el transform wrapper interior transforma geometry, stroke width y text size.

No se mantiene un árbol SVG abierto a través de varios draws. Aplicar un clip a
un grupo con múltiples primitives podría cambiar compositing/antialiasing en el
borde; un wrapper de una sola primitive conserva painter-order source-over.

`PushState`, `PopState`, `ConcatTransform` e `IntersectClipRect` no emiten por sí
mismos un nodo visible ni un newline fuera de `defs`.

## 8. State privado

El serializer comienza con:

```text
transform = identity
clipRect = Rect(0, 0, viewport.width, viewport.height)
clipId = 0
stack = empty
```

Cada entry de stack contiene exactamente `Transform2D`, el rectangle acumulado
y `clipId`.

- `PushState`: copia los tres valores y aumenta depth;
- `PopState`: restaura el último entry;
- `ConcatTransform(T)`: calcula `current = current * T` con el orden y las
  operaciones float64 de Graphics;
- `IntersectClipRect(R)`: intersecta `R` con `clipRect` en scene coordinates,
  asigna el próximo clip ID y lo vuelve current.

Una Scene pública ya está balanceada y validada. Underflow, span inválido o
valor no finito implican corrupción/bug fuera del contrato y conservan los
traps generales; no se reclasifican como backend exception.

## 9. Transform2D

La correspondencia exacta es:

```text
Graphics                   SVG
m11                        a
m12                        b
m21                        c
m22                        d
tx                         e
ty                         f
```

Por tanto:

```text
Transform2D(m11,m12,m21,m22,tx,ty)
-> matrix(m11 m12 m21 m22 tx ty)
```

SVG aplica así:

```text
x' = a*x + c*y + e
y' = b*x + d*y + f
```

que coincide literalmente con Graphics. El serializer acumula
`current=current*local`; no invierte el orden y no transpone coefficients. La
qualification usa translate/scale/shear no conmutativos y compara los seis
valores parseados, no sólo una imagen visual.

No se emite `vector-effect="non-scaling-stroke"`: SVG debe transformar el
outline y su width junto con geometry. Esto conserva scales no uniformes,
rotations, shear y transforms singulares según el contrato Graphics.

## 10. Clipping

Se hacen dos traversals read-only:

1. el primero reproduce sólo stack e intersecciones y acumula un
   `Buffer<Rect>` de definiciones;
2. el segundo reproduce state completo y emite draws, usando la misma
   numeración de IDs.

`defs` contiene siempre:

```xml
  <defs>
    <clipPath id="graphics-clip-0" clipPathUnits="userSpaceOnUse">
      <rect x="0" y="0" width="W" height="H"/>
    </clipPath>
    ...
  </defs>
```

Por cada `IntersectClipRect`, sin importar si cambia visualmente el resultado,
se emite exactamente un nuevo `clipPath` cuyo `<rect>` es la intersección
acumulada. Sus IDs son `graphics-clip-1`, `graphics-clip-2`, ... en traversal
order. No hay reuse por igualdad, hash, address o global counter.

`clipPathUnits="userSpaceOnUse"` es explícito. Como el reference está en el
grupo exterior y el transform de la primitive en su hijo, el rectangle está en
scene coordinates y no es afectado por transforms anteriores o posteriores.
Push/pop restaura el ID anterior. Intersecciones anidadas se reducen a un único
rectangle acumulado porque todos los clips V1 son rectangles axis-aligned en
el mismo espacio; eso es semánticamente exacto, no tessellation.

Un clip vacío se representa por width o height `0`. El draw permanece en el
documento bajo ese clip y no se elimina. `defs` aparece antes de cualquier
reference; no se depende de forward references.

## 11. Colors y alpha

Cada RGB se emite como `#RRGGBB`, con hex uppercase y dos dígitos por channel.
No se premultiplica ni convierte de sRGB.

Alpha usa el atributo correspondiente:

- alpha `255`: se omite `fill-opacity`/`stroke-opacity`, equivalente a `1`;
- alpha `0`: se emite `0`;
- alpha `1..254`: se emite `appendNumber(float64(alpha) / 255.0)`.

Así los 256 inputs conservan una correspondencia determinista y el valor
binary64 serializado round-trips. Fill y stroke mantienen opacities separados;
no se usa opacity de grupo porque alteraría `FillAndStroke` y compositing.

## 12. Stroke

Un `Stroke` genera, en este orden:

```text
stroke="#RRGGBB"
stroke-opacity=...           // salvo alpha 255
stroke-width=width
stroke-linecap=butt|round|square
stroke-linejoin=miter|round|bevel
stroke-miterlimit=miterLimit
```

No se emite dash, marker, vector-effect ni CSS. Width y miter limit usan la
autoridad numérica única. El transform del grupo interior se aplica al stroke
completo, de modo que un scale no uniforme no se sustituye por un width medio.

## 13. Fill y Paint

`Fill` genera:

```text
fill="#RRGGBB"
fill-opacity=...             // salvo alpha 255
fill-rule=nonzero|evenodd
```

La tabla de `Paint` es:

| Paint | Attributes |
|---|---|
| `FillOnly(fill)` | fill attrs, `stroke="none"` |
| `StrokeOnly(stroke)` | `fill="none"`, stroke attrs |
| `FillAndStroke(fill,stroke)` | fill attrs y luego stroke attrs |

SVG pinta normalmente fill antes de stroke. No se necesita duplicar la
primitive ni crear dos Commands; tampoco se emite `paint-order` porque el orden
normal ya es el contrato y no hay markers.

## 14. DrawPoint

`DrawPoint(position, diameter, color)` usa un `<circle>` filled, sin stroke.
Para no underflowear `diameter / 2` cuando el diámetro es el menor subnormal,
se preserva el operando finito y se expresa la división exacta mediante un
transform local:

```xml
<circle cx="0" cy="0" r="diameter"
        transform="matrix(0.5 0 0 0.5 x y)"
        fill="#RRGGBB" ... stroke="none"/>
```

El circle de radio `diameter` primero escala por `0.5` y luego se traslada a la
posición, por lo que su radio en el user space de la primitive es exactamente
`diameter/2`. El transform Graphics exterior se aplica después. No hay marker
semantics, catálogo Plots ni aproximación con path.

El orden real de attributes sigue geometry, transform y paint según la sección
4; el snippet sólo ilustra la semántica.

## 15. DrawLine

La representación normativa única es:

```xml
<line x1="..." y1="..." x2="..." y2="..." fill="none" ...stroke.../>
```

No se convierte a path. Extremos iguales permanecen iguales; no se elimina la
line y SVG aplica `stroke-linecap`, incluidos butt, round y square.

## 16. DrawPolyline

La representación normativa es `<polyline>`, nunca path:

```xml
<polyline points="x0,y0 x1,y1 ..." fill="none" ...stroke.../>
```

Entre X e Y hay una coma ASCII; entre points, un único espacio; no hay espacio
inicial o final. El serializer recorre `PointSpan` con `scene.pointAt(span,i)`
y escribe cada scalar directamente al buffer. No crea Array, List, string de
points ni copia intermedia de `Point`.

## 17. DrawRect

La representación normativa es:

```xml
<rect x="..." y="..." width="..." height="..." ...paint.../>
```

Width/height cero se conservan. No se baja el rect a cuatro lines o a path, no
se aplican transforms a sus cuatro corners en el serializer y no se agrega
corner radius.

## 18. DrawPath

La representación normativa es un `<path d="...">` con commands absolutos
uppercase:

| Graphics verb | Fragmento `d` |
|---|---|
| `MoveTo(p)` | `M x y` |
| `LineTo(p)` | `L x y` |
| `CubicTo(c1,c2,end)` | `C c1x c1y c2x c2y ex ey` |
| `Close` | `Z` |

Hay un único espacio entre tokens y ninguno al inicio/final. Múltiples subpaths
se conservan. El serializer recorre `PathSpan` directamente; no retessella,
aplana, agrega Close implícito ni crea una lista de verbs. Paint se emite según
la sección 13.

## 19. DrawText

Cada `TextRecord` produce un único `<text>`:

```xml
<text x="..." y="..." fill="..." font-size="..."
      ...font... text-anchor="..." dominant-baseline="..."
      direction="ltr" writing-mode="horizontal-tb"
      xml:space="preserve">CONTENT</text>
```

No se crean `tspan`, outline glyph paths ni layout box. `CONTENT` usa
`appendTextContent` sobre el `ByteSpan` original. El backend no normaliza,
segmenta ni reordena Unicode.

Mappings exactos:

| Graphics | SVG |
|---|---|
| `TextAlign.Left` | `text-anchor="start"` |
| `TextAlign.Center` | `text-anchor="middle"` |
| `TextAlign.Right` | `text-anchor="end"` |
| `TextBaseline.Alphabetic` | `dominant-baseline="alphabetic"` |
| `TextBaseline.Top` | `dominant-baseline="text-before-edge"` |
| `TextBaseline.Middle` | `dominant-baseline="central"` |
| `TextBaseline.Bottom` | `dominant-baseline="text-after-edge"` |
| `FontWeight.Normal` | `font-weight="normal"` |
| `FontWeight.Bold` | `font-weight="bold"` |
| `FontSlant.Normal` | `font-style="normal"` |
| `FontSlant.Italic` | `font-style="italic"` |

`direction="ltr"` fija que start/end implementen alineación física
left/right, no una selección implícita dependiente del texto. El viewer sigue
siendo responsable de bidi y shaping dentro de esa base direction. V1 no expone
otro writing mode o direction.

`xml:space="preserve"` se emite en cada text. TAB/LF/CR se conservan como
character references; Graphics define un run y recomienda varias primitives
para multiline layout, pero el backend no borra esos scalars.

El viewer/browser es responsable de font lookup, fallback, shaping, kerning,
glyph selection, bidi, hinting y rasterización. Diferencias métricas entre
viewers no cambian los bytes SVG deterministas y no son un error de
serialization.

## 20. Fonts

El mapping de family es:

| `StoredFontFamily` | Output |
|---|---|
| `BackendDefault` | se omite `font-family` |
| `Serif` | `font-family="serif"` |
| `SansSerif` | `font-family="sans-serif"` |
| `Monospace` | `font-family="monospace"` |
| `Named(span)` | un único CSS quoted family name |

Una family nombrada no puede emitirse como token desnudo: comas, spaces o un
nombre como `serif` cambiarían su significado. Primero se construye un CSS
double-quoted string y después se aplica escaping XML al attribute completo.

Dentro del CSS string:

- `"`, `\`, TAB, LF, CR y FORM FEED usan un escape hexadecimal CSS uppercase
  `\HEX `;
- el espacio posterior al hex siempre se emite y es consumido por el parser
  CSS; un espacio real siguiente se conserva aparte;
- los demás XML `Char` se conservan en UTF-8;
- una family vacía o que contenga un scalar XML-invalid produce
  `GraphicsTextException`.

El valor XML visible de una family `A"B` es conceptualmente
`font-family="&quot;A\22 B&quot;"`. Tras XML y CSS parsing, el request vuelve a ser
el único nombre `A"B`.

No se embeddean fonts y no se consulta disponibilidad local durante render.
Que el viewer no encuentre una named family activa fallback ordinario y nunca
produce `GraphicsTextException`.

## 21. Serializer y allocations

El serializer futuro es una class privada source-level con:

- `Buffer<uint8>` growable y logical length para output;
- `Buffer<SerializerState>` growable hasta nesting depth;
- `Buffer<Rect>` exacto/growable para clip definitions;
- counters de traversal e IDs;
- ningún reference retenido después de `render`.

El output buffer crece geométricamente con aritmética checked. Literals ASCII,
bytes Scene escapados y bytes de numeric temporaries se copian directamente.
No se usa `string + string` para construir el documento.

`str(float64)` hoy produce un owner temporal por scalar. El serializer puede
copiarlo con `std.Text.byteAt` y destruirlo inmediatamente. Esto causa
allocations escalares secuenciales, con peak O(1), pero no concatenación
cuadrática ni owner por payload persistente. Una futura API general de
format-to-writer puede eliminarlas sin cambiar este contrato SVG.

Complejidad objetivo:

```text
tiempo: O(commands + payload visitado + output bytes)
peak:   O(output bytes + nesting depth + clip count)
```

No hay allocation por `Point`, `PathVerb` o `Command`, no se copian arenas de
Scene y no se construyen listas intermedias de geometry. Al finalizar coexisten
temporalmente buffer y string final, por lo que el peak incluye ambos.

## 22. Blocker de construcción de string

La auditoría de capabilities vigentes encontró:

- `Buffer<uint8>` growable es expresable en una class privada;
- `std.Text.byteAt` permite copiar bytes desde strings;
- `str(float64)` ofrece formatting canónico correcto;
- string interpolation sólo acepta un número estático de fragments conocido
  por el frontend;
- `std.File.writeText` requiere un `string` completo;
- no existe `StringBuilder`, byte writer público, `join` lineal ni una función
  que materialice un string desde bytes UTF-8;
- `Buffer<string>` está excluido y `List<string>` no resuelve un join final;
- concat binario de strings copia ambos operands y un loop incremental sería
  O(output²).

Por tanto `render -> string` y, transitivamente, `save`, no pueden cumplir este
diseño mediante source Aether ordinario hoy.

El prerrequisito debe ser una capability general de `std.Text`, diseñada y
calificada fuera de graphics. La forma mínima conceptual es:

```aether
// Spelling no normativo; debe cerrarse en su propio milestone.
public string fromUtf8(ref Buffer<uint8> bytes, usize length);
```

Su contrato necesario es: borrow del prefijo, bounds checked, validación UTF-8
estricta, una publicación string exacta O(length), singleton para vacío,
ownership/cleanup ordinario y ninguna dependencia hacia graphics. Una
`TextBuilder.finish()` general que cumpla lo mismo también sirve.

No se implementará un opcode `SvgRender`, acceso al layout privado de string,
FFI, helper runtime reachable sólo por package name ni intrinsic autorizado por
`graphics.svg`. Hasta que la capability general cierre, el siguiente milestone
no es `GRAPHICS-SVG-BACKEND-V1`.

## 23. Save e IO

Una vez disponible la materialización:

```text
save(scene,path):
    value = render(scene)
    try std.File.writeText(path,value)
    catch std.IO.IOException -> throw graphics.GraphicsIoException()
```

`save` hereda create-or-truncate y writes potencialmente parciales de
`std.File.writeText`; no promete atomic replace, durability ni rollback. Todo
error externo nominal bajo `IOException`, incluidos not-found/permission, se
traduce a `GraphicsIoException`. Traps de overflow, OOM o corrupción no se
capturan.

Errores de rendering (`GraphicsTextException`) ocurren antes de abrir el
archivo y se propagan sin reclasificar. No se agrega path al exception porque
la jerarquía Graphics vigente no tiene payload.

## 24. Modelo de errores

| Situación | Resultado |
|---|---|
| Scene V1 válida y texto XML-representable | SVG completo |
| NUL/control XML-invalid en content/family | `GraphicsTextException` |
| named family vacía/no representable como request único | `GraphicsTextException` |
| font ausente en viewer | SVG válido; no exception |
| Command V1 válido | siempre soportado |
| IO externo de `save` | `GraphicsIoException` |
| allocation/size overflow | trap general |
| Scene/accessor corrupto fuera del contrato | trap general |

`UnsupportedGraphicsFeatureException` no se usa para omitir Commands V1. El
perfil cerrado representa geometry y transforms finitos extremos de forma
textual, incluido el diámetro extremo de DrawPoint. La excepción queda en la
jerarquía para targets futuros, no como escape de implementación parcial SVG.

## 25. Determinism

Para una misma Scene, `render` produce exactamente los mismos bytes en O0, O2
y ejecuciones distintas:

- traversal e IDs dependen sólo de índices densos;
- no hay timestamp, random, address, UUID, hash map ni global mutable;
- attributes y whitespace tienen orden fijo;
- números usan FORMAT-V1 y canonicalizan ambos ceros;
- colors usan hex uppercase fijo;
- XML/CSS escaping tiene una forma única;
- locale, timezone, fonts instaladas y viewer no participan en serialization.

`save` escribe exactamente esos bytes. El filesystem puede observar el modelo
de error de IO, pero no cambia el contenido exitoso.

## 26. Qualification funcional futura

`GRAPHICS-SVG-BACKEND-V1` debe cubrir en O0 y O2:

### Documento y Commands

- Scene vacía y `0x0`, `0xh`, `wx0`;
- XML declaration, root namespace, width/height/viewBox y LF final exactos;
- cada variante de `Command`;
- painter order exacto entre primitives solapadas;
- Push/Pop y restauración de transform/clip;
- transforms translate/scale/shear no conmutativos y singular;
- clip inicial, nested intersections, push/pop, intersección redundante y clip
  zero-area;
- IDs exactos y ausencia de reuse/hash/randomness.

### Geometry y paint

- point normal, mínimo subnormal y máximo finito;
- line normal y degenerate con las tres caps;
- polyline de dos y muchos points sin allocation/lista intermedia;
- Rect normal y dimensiones cero;
- path multi-subpath con cada verb y Close;
- FillOnly, StrokeOnly, FillAndStroke, NonZero y EvenOdd;
- todas caps/joins, miter mínimo/extremo y transform no uniforme;
- alpha 0, 1, valores intermedios, 254 y 255; RGB endpoints;
- scalars normales, signed zero, subnormales y máximos finitos.

### Text

- ASCII, multibyte, emoji y combining marks;
- whitespace inicial/interno/final, TAB, LF y CR preservados tras XML parse;
- los cinco caracteres XML especiales en content y named family;
- NUL y cada clase de control XML-invalid rechazados sin output publicado;
- generic, backend-default, named con spaces/comma/quotes/backslash y keyword
  `serif` citado como family propia;
- empty named family rechazada;
- weight, slant, align y baseline completos;
- font inexistente serializada sin consultar el host.

## 27. Goldens y validación estructural

Se usan goldens textuales pequeños para:

- empty Scene;
- una primitive de cada clase;
- state/clip/transform nesting;
- paint/style matrix representativa;
- path multi-subpath;
- escaping y text mapping.

Los goldens comparan el documento completo, no substrings. O0 y O2 se comparan
entre sí byte por byte y contra el mismo golden.

Además, una dependencia XML test-only versionada debe parsear los resultados y
comprobar:

- documento XML 1.0 well-formed y namespace SVG;
- root viewport numérico;
- orden DOM de los draws;
- matrices con seis coefficients;
- `clip-path` references que resuelven a IDs únicos;
- `points` y `d` reconstruibles;
- text node scalars exactos después de entity decoding;
- named family CSS value exacto para los casos escapados.

No se agrega parser SVG productivo. No se depende exclusivamente de substring
checks, `xmllint` ambiental ni screenshot comparison. Si el workspace todavía
no tiene parser XML aprobado, V1 debe incorporar uno sólo como dependencia de
tests o abrir ese prerrequisito; no puede declarar cierre sólo con goldens.

## 28. Gates de allocations, source e IR

La qualification debe demostrar:

- growth geométrico del output buffer y frees balanceados;
- peak/state proporcional a output + depth + clips;
- mismo número de allocations estructurales para pocos/muchos points salvo
  growth del buffer y temporales `str` documentados;
- cero copia de las cinco arenas Scene y cero mutation/accessor mutable;
- import `graphics` desde `graphics.svg` y ausencia del edge inverso;
- match estático exhaustivo sobre `graphics.Command`;
- ausencia de `InterfaceCall`, renderer registry, callback/vtable por command;
- ausencia de FFI, browser/runtime embedding, Matplotlib, Plots y graphics
  intrinsic;
- llamadas directas ordinarias a `std.Text` y `std.File`;
- equivalencia source/HIR/MIR/SSA/LLVM O0/O2 y `git diff --check`.

## 29. Fuera de scope

Quedan fuera PNG/raster, windows, GUI, interactivity, events, animation, CSS
themes o stylesheets, gradients, patterns, masks, filters, images, font
embedding, font discovery API, MathTeX, notebooks, Plots, accessibility,
metadata, links, scripts, external resources, compression SVGZ, streaming,
incremental DOM y dynamic renderer registry.

## 30. Alternativas rechazadas

| Alternativa | Motivo |
|---|---|
| concatenar `string` por fragment/command | O(output²), owners y copias intermedias |
| escribir directo a archivo | no satisface `render`; File V1 no tiene stream/append y duplicaría serializer |
| agregar intrinsic privado SVG | privilegio por package y acoplamiento compiler/runtime |
| exponer Buffers de Scene | rompe inmutabilidad y frontera pública foundation |
| resolver transforms en cada point | altera stroke/text y puede overflowear geometry |
| `vector-effect="non-scaling-stroke"` | contradice width en user space Graphics |
| clip dentro del transform group | transforma un clip definido en scene coordinates |
| un clip group para muchos draws | puede cambiar group compositing en bordes |
| IDs random/hash | rompe goldens y reproducibilidad |
| omitir draws bajo clip vacío | culling innecesario y pierde correspondencia estructural |
| CSS global/classes | abre cascade, naming y orden no necesarios |
| font lookup durante render | host-dependent y no requerido para expresar el request |
| sustituir controles inválidos | pérdida silenciosa de bytes |
| screenshots como autoridad | dependientes de viewer/fonts/raster y no prueban estructura |

## 31. Secuencia de desbloqueo

La secuencia cerrada es:

```text
TEXT-UTF8-BUILDER-ARCH-1 (o milestone general equivalente)
TEXT-UTF8-BUILDER-V1
GRAPHICS-SVG-BACKEND-V1
```

El nombre del prerrequisito no es normativo; sí lo es que la capability sea
general, viva fuera de graphics, publique un string UTF-8 en O(n) y tenga
qualification propia. Una vez disponible, este documento no requiere otra
decisión de arquitectura SVG y el milestone siguiente puede ser
`GRAPHICS-SVG-BACKEND-V1`.

Hasta entonces, `GRAPHICS-SVG-BACKEND-ARCH-1` permanece **BLOCKED**.
