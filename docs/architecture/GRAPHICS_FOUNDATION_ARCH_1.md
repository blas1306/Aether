# GRAPHICS-FOUNDATION-ARCH-1 — foundation gráfica 2D backend-independent

Estado: **ARQUITECTURA CERRADA; NO IMPLEMENTADA**, 2026-10-19.

Este milestone es exclusivamente documental. Define una representación gráfica
2D pequeña para que Plots produzca escenas y para que backends posteriores las
rendericen. No modifica source productivo, compiler, runtime, Core, std,
packages OAL ni tests ejecutables.

La arquitectura deliberadamente no diseña Plots, axes, ticks, legends,
MathTeX, notebooks, UI, ventanas, eventos, animación, rasterización, 3D ni GPU.
Esas capas pueden consumir o bajar a esta foundation, pero no forman parte de
su API.

Son autoridades de lenguaje y distribución:

- [AETHER-V1-SEMANTIC-CONTRACT](AETHER_V1_SEMANTIC_CONTRACT.md), para owners,
  aggregates, payload enums, references, `Buffer<T>`, classes y exceptions;
- [MODULE-STD-ARCH-1](MODULE_STD_ARCH_1.md), para separación entre lenguaje,
  Core, std y packages;
- [PACKAGE-MANAGER-ARCH-1](PACKAGE_MANAGER_ARCH_1.md), para packages OAL sin
  privilegios;
- [TEXT-BYTE-ACCESS-ARCH-1](TEXT_BYTE_ACCESS_ARCH_1.md), para observación exacta
  de bytes UTF-8 sin inventar un segundo tipo de string.

## 1. Decisión resumida

La foundation usa este pipeline:

```text
Plots / UI futura / documento futuro
        |
        | construye
        v
graphics.SceneBuilder
        |
        | finish: valida y congela
        v
graphics.Scene                    // display list inmutable
        |
        | traversal read-only
        v
graphics.svg / raster futuro / window futuro / GPU futuro
```

La decisión concreta es un **builder mutable que produce una display list
inmutable y compacta**. No se adopta un retained scene graph en V1:

- no hay nodo heap por primitive;
- no hay parent/children, identity de nodo, dirty flags ni edición in-place;
- el orden de pintura es exactamente el orden de comandos;
- los payloads variables viven en arenas contiguas owned por `Scene`;
- una UI futura puede conservar su propio árbol y bajarlo a una nueva `Scene`
  cuando cambie; no se obliga a que graphics sea también su object model.

`Scene` no conoce SVG, XML, PNG, pixels, ventanas, toolkits, APIs nativas ni
GPU. Un backend tampoco se registra dentro de la scene. Cada backend ofrece
free functions estáticas que recorren la misma superficie read-only.

## 2. Alcance V1

La foundation representa:

- coordenadas y puntos 2D;
- puntos dibujables, lines y polylines;
- rectangles;
- paths lineales y cúbicos;
- text UTF-8 de una sola primitive, sin layout de párrafos;
- transforms afines 2D;
- clipping rectangular;
- fill y stroke;
- color RGBA sRGB;
- viewport y orden de composición.

No incluye imagen raster en V1. Plots V1 no la necesita, y admitirla obligaría
a cerrar prematuramente pixel format, row stride, color space del bitmap,
ownership de bytes, decoding y referencias externas. Una futura
`DrawImage(ImageId, destination)` puede agregarse sin cambiar ningún comando
existente, siempre con bytes/handle owned y contrato explícito; no se reserva
un URI string como sustituto.

También quedan fuera circles/ellipses generales, arcs, quadratic Bézier,
gradients, patterns, blend modes, shadows, filters, masks, dash patterns,
groups con opacity, hit testing y medición pública de text. El punto dibujable
descrito abajo es la única primitive circular V1.

## 3. Sistema de coordenadas canónico

Una `Scene` tiene exactamente un `Viewport`:

```aether
public struct Viewport {
    float64 width;
    float64 height;
}
```

La semántica canónica es:

- origen `(0,0)` en la esquina superior izquierda del viewport;
- `x` crece hacia la derecha;
- `y` crece hacia abajo;
- una unidad es una **logical graphics unit**, no pixel, point tipográfico,
  milímetro ni unidad de datos científicos;
- el viewport ocupa `[0,width] x [0,height]` en esas unidades;
- width/height deben ser finitos y no negativos;
- un viewport con width o height cero es válido y produce una salida sin área
  visible, no un error.

El backend decide cómo las unidades lógicas se mapean al target. Un SVG puede
usar el viewport como `viewBox`; un raster requiere options explícitas para
elegir pixel dimensions o scale; una ventana puede mapearlo a logical pixels.
La foundation no contiene DPI.

Plots conserva autoridad sobre sus data coordinates. Para una gráfica con eje
Y matemático creciente hacia arriba, Plots emite la transformación de datos al
viewport, incluida la inversión de Y. Graphics nunca interpreta un `Point`
como dato científico.

## 4. Escalar gráfico

El escalar V1 es **`float64` fijo** para posiciones, sizes, widths y matrices.
No se crea `GraphicsScalar`, no se parametriza `Scene<T>` y no se usa
`Matrix<T>`.

Razones:

- datos científicos Aether usan frecuentemente `float64`; conservarlos evita
  narrowing antes de clipping/lowering;
- `float32` pierde precisión visible al combinar domains grandes con offsets
  pequeños y transforms sucesivos;
- una scene generic duplicaría comandos, builders y backends sin que SVG,
  raster o GPU puedan evitar elegir una representación concreta;
- una estructura afín especializada evita shape checks, allocation y la
  convención ambigua de una Matrix general.

`float32` se ensancha exactamente a `float64`. Integers y otros valores son
convertidos explícitamente por el consumer antes de entrar a graphics. Un
backend que necesite `float32` puede narrow durante lowering; si el target no
puede representar un valor finito debe reportar `NumericRange`, nunca saturar,
envolver ni producir comportamiento indefinido silenciosamente.

## 5. Geometry nominal

Los valores base son pequeños aggregates Copy:

```aether
public struct Point {
    float64 x;
    float64 y;
}

public struct Line {
    Point from;
    Point to;
}

public struct Rect {
    float64 x;
    float64 y;
    float64 width;
    float64 height;
}
```

`Rect.x/y` nombran la esquina top-left en el espacio donde se declara. Width y
height son no negativos. Los cuatro límites deben permanecer finitos; no basta
que cada field aislado sea finito si `x+width` o `y+height` desborda a
infinito.

Un rectangle degenerado con width o height cero es válido. Un line con ambos
extremos iguales también es válido y conserva la semántica del line cap. Esos
casos no reciben una excepción especial.

`DrawPoint` sí es visible: dibuja un disco filled centrado en `Point`, con
diameter lógico estrictamente positivo y un `Color`. No significa “un punto
matemático infinitesimal” ni adopta un marker catalog de Plots. Otros markers
futuros se forman con paths.

## 6. Transformación afín 2D

La representación especializada es:

```aether
public struct Transform2D {
    float64 m11;
    float64 m12;
    float64 m21;
    float64 m22;
    float64 tx;
    float64 ty;
}
```

Conceptualmente usa column vectors:

```text
| x' |   | m11 m21 tx | | x |
| y' | = | m12 m22 ty | | y |
| 1  |   |  0   0   1 | | 1 |

x' = m11*x + m21*y + tx
y' = m12*x + m22*y + ty
```

Identity es `(1,0,0,1,0,0)`. `concat(T)` actualiza
`current = current * T`: una geometría local primero recibe `T` y luego el
transform previamente vigente. Esta convención es normativa y se prueba con
translate/scale/rotate no conmutativos.

Todos los componentes deben ser finitos. Una transformación singular es
válida: puede colapsar geometry a una line o point. El builder rechaza una
composición cuyo `Transform2D` resultante deje de ser finito, pero no intenta
invertir matrices ni impone un determinant mínimo.

Stroke width y text size pertenecen al mismo user space que su primitive y son
transformados con ella. Un scale no uniforme puede producir un outline no
uniforme; el backend debe transformar la geometría stroked, no reemplazar esa
semántica por un único width promedio.

## 7. Color y composición

`Color` tiene cuatro componentes byte:

```aether
public struct Color {
    uint8 red;
    uint8 green;
    uint8 blue;
    uint8 alpha;
}
```

El contrato es:

- RGB contiene componentes sRGB encoded de 0 a 255;
- alpha contiene coverage lineal de 0 transparente a 255 opaco;
- la representación es **straight alpha**, no premultiplied;
- el orden lógico es RGBA independientemente del byte order o pixel format del
  backend;
- no hay ICC profiles, wide gamut, HDR ni color management avanzado V1.

Bytes evitan estados inválidos, NaN y tolerancias de comparación en styles. Un
backend raster puede convertir a linear/premultiplied internamente, pero no
cambia el contrato público. El compositing V1 es painter's order con
source-over. No hay blend-mode seleccionable.

## 8. Fill y Stroke

Los estilos mínimos son nominales y Copy:

```aether
public enum FillRule {
    NonZero,
    EvenOdd,
}

public struct Fill {
    Color color;
    FillRule rule;
}

public enum LineCap {
    Butt,
    Round,
    Square,
}

public enum LineJoin {
    Miter,
    Round,
    Bevel,
}

public struct Stroke {
    Color color;
    float64 width;
    LineCap cap;
    LineJoin join;
    float64 miterLimit;
}

public enum Paint {
    FillOnly(Fill),
    StrokeOnly(Stroke),
    FillAndStroke(Fill, Stroke),
}
```

Stroke width debe ser finito y estrictamente positivo. Width cero no significa
“hairline del device”, porque eso cambia entre SVG, raster y GPU. Miter limit
debe ser finito y al menos `1`. En `FillAndStroke`, fill se ejecuta primero y
stroke después dentro del mismo command.

Dash queda fuera de V1. Incluirlo exige ownership de una secuencia variable,
validación de longitudes/offset y semántica bajo transforms. Se agregará como
style/arena aditiva si Plots lo prioriza; no se codifica un dash SVG string ni
un sentinel dentro de `Stroke`.

## 9. Paths

V1 sí necesita paths. Rectangles y polylines cubren Plots básico, pero cubic
Bézier permite curvas suaves y shapes reutilizables por consumers futuros sin
convertir la foundation en una copia de SVG.

Los verbs son:

```aether
public enum PathVerb {
    MoveTo(Point),
    LineTo(Point),
    CubicTo(Point control1, Point control2, Point end),
    Close,
}
```

Reglas:

- cada subpath comienza con `MoveTo`;
- `LineTo`, `CubicTo` y `Close` requieren un subpath activo;
- `Close` une conceptualmente el current point al primer point del subpath y
  deja ese primero como current point;
- un nuevo `MoveTo` comienza otro subpath;
- fill trata subpaths abiertos como cerrados sólo para calcular interior;
- stroke no agrega un segmento de cierre si no existe `Close`;
- todos los points son finitos.

Cubic Bézier se incluye porque todos los targets previstos pueden bajarlo de
forma directa o tessellarlo, y porque aproximar curvas suaves sólo con
polylines obliga al consumer a elegir una tolerancia dependiente del target.
Quadratic Bézier puede convertirse exactamente a cubic. Arcs, circles y
ellipses generales no entran: el consumer puede aproximarlos con cubics o un
milestone posterior puede agregar primitives con semántica propia. No se copia
el catálogo de path commands SVG.

Los verbs de todos los paths de una Scene se almacenan en una única arena; un
`DrawPath` lleva un `PathSpan`, no un owner por path.

## 10. Polylines y arenas

Una polyline se guarda como un rango contiguo de `Point`:

```aether
public struct PointSpan { usize start; usize length; }
public struct PathSpan  { usize start; usize length; }
public struct ByteSpan  { usize start; usize length; }
```

Son tipos nominales diferentes para no mezclar arenas. Sólo `SceneBuilder`
crea spans publicados en commands. Una polyline necesita al menos dos points;
una secuencia de uno usa `DrawPoint` si esa era la intención.

La API cómoda puede recibir `ref Array<Point>` o una view contigua durante la
llamada, pero **siempre copia** esos points a la arena del builder. No retiene
el borrow ni la dirección del Array. La API incremental
`beginPolyline/addPoint/endPolyline` evita construir el Array temporal y
escribe en la misma arena.

La elección deliberada es self-contained Scene. No existe una variante
borrowed de `DrawPolyline`: requeriría que cada backend fuera generic sobre el
lifetime del producer, impediría conservar/renderizar la Scene después y
volvería inseguro compartirla con UI o export. Un futuro recurso externo debe
tener owner/keepalive explícito y no cambiar esta variante.

## 11. Text

`DrawText` significa una primitive de **un run textual**, no un paragraph o
layout box. Su semántica pública contiene:

- bytes exactos de un `string` Aether UTF-8 válido;
- anchor position;
- size lógico positivo;
- color;
- alineación física horizontal `Left`, `Center` o `Right`;
- baseline `Alphabetic`, `Top`, `Middle` o `Bottom`;
- un font request conceptual;
- el transform vigente.

El request V1 es pequeño:

```aether
public enum FontFamily {
    BackendDefault,
    Serif,
    SansSerif,
    Monospace,
    Named(string),
}

public enum FontWeight { Normal, Bold }
public enum FontSlant  { Normal, Italic }
public enum TextAlign  { Left, Center, Right }
public enum TextBaseline { Alphabetic, Top, Middle, Bottom }

public struct FontRequest {
    FontFamily family;
    FontWeight weight;
    FontSlant slant;
}

public struct TextStyle {
    float64 size;
    Color color;
    FontRequest font;
    TextAlign align;
    TextBaseline baseline;
}
```

`TextStyle` es input lógico. Al agregar el command, el builder copia contenido
y family name a una arena UTF-8 única y almacena `ByteSpan`s Copy en un
`TextRecord`. Así `Command` y el buffer de records permanecen Copy/no-drop y no
hay allocation por text primitive dentro de la Scene final.

No se normaliza Unicode, no se restringe a ASCII y no se interpreta MathTeX.
La foundation no hace shaping, bidi completo, font fallback avanzado,
line-breaking, wrap, glyph caching ni medición. El backend elige/resuelve la
font, forma glyphs y coloca el run respetando anchor/alignment/baseline. Debe
preservar whitespace de contenido; no puede aplicar por accidente el collapse
de whitespace de su formato.

LF, CR, NUL y otros controles siguen siendo bytes UTF-8 válidos para la
foundation. Un backend cuyo formato o text engine no pueda representarlos
reporta `GraphicsTextException`; no los borra ni sustituye silenciosamente.
Multiline layout se expresa por varios `DrawText` colocados por el consumer
hasta que exista una capa textual superior.

## 12. Clipping y state

La display list comienza con:

```text
transform = identity
clip      = viewport rectangle
```

Los comandos de state son:

```text
PushState
PopState
ConcatTransform(Transform2D)
IntersectClipRect(Rect)
```

`PushState` copia transform y clip actuales en una stack lógica.
`PopState` los restaura. Underflow es inválido y `finish` exige stack
balanceada.

`IntersectClipRect` recibe un rectangle en **coordenadas canónicas de la
Scene**, no en el user space transformado. Lo intersecta con el clip vigente y
no queda afectado por transforms posteriores. Esta decisión hace explícito el
caso central de Plots: transformar datos mientras la caja de axes permanece
fija. También evita que “rectangular clip” se convierta implícitamente en un
paralelogramo por una rotación. Clip paths o clips locales transformados quedan
para una extensión aditiva.

Un clip vacío es válido y convierte draws posteriores en no-ops observables
sólo por ausencia de pixels/output visual. El command permanece en la Scene.

Se eligió state explícito y scoped frente a repetir transform/clip resueltos en
cada primitive. Resolver todo a global perdería cubic/path intent, duplicaría
state, dificultaría una UI que baje grupos y puede alterar strokes bajo
transforms no uniformes. El modelo no es state oculto del builder: cada cambio
es un command serializable, ordenado e inspeccionable.

## 13. Display list concreta

La forma semántica de `Command` es:

```aether
public enum Command {
    PushState,
    PopState,
    ConcatTransform(Transform2D),
    IntersectClipRect(Rect),
    DrawPoint(Point position, float64 diameter, Color color),
    DrawLine(Line line, Stroke stroke),
    DrawPolyline(PointSpan points, Stroke stroke),
    DrawRect(Rect rectangle, Paint paint),
    DrawPath(PathSpan verbs, Paint paint),
    DrawText(usize textRecord),
}
```

El spelling final del índice textual puede ser un wrapper nominal `TextId`; no
cambia su semántica de índice interno. No se expone un constructor de `Scene`
que acepte Commands arbitrarios.

El painter's order es estricto. Dos draws no se reordenan aunque parezcan
opacos o no solapados. Un backend puede batch/reordenar sólo si demuestra que
el resultado source-over, clipping y state es idéntico.

La Scene posee cinco buffers exactos y contiguos:

```text
Buffer<Command>     commands
Buffer<Point>       polylinePoints
Buffer<PathVerb>    pathVerbs
Buffer<TextRecord>  textRecords
Buffer<uint8>       utf8Bytes
```

Styles, lines, rects y transforms caben inline en Command. Los ranges se
validan una vez al congelar. El traversal es determinista y O(commands +
polyline points + path verbs + text bytes consumidos).

No se promete un layout binario ni formato persistente de esos buffers. Son
representación source/semántica V1. Una serialización futura recorre commands y
payloads en orden; nunca dumps de memoria, discriminants internos o addresses.

## 14. `SceneBuilder` y `Scene`

### 14.1 Builder

`SceneBuilder` es un objeto mutable, one-shot y no thread-safe. Posee buffers
geométricamente crecientes para las cinco arenas, logical lengths, stack de
state y estado de path/polyline abierto. Sus fields son privados.

La implementación ordinaria prevista usa `Buffer<T>` concreto y counters, no
un node por primitive. Cuando una arena agota capacity:

1. calcula capacity nueva con aritmética checked;
2. crea un `Buffer<T>` nuevo con un fill interno válido;
3. copia exactamente el prefijo lógico Copy;
4. publica buffer/capacity nuevos;
5. libera el backing anterior mediante replacement ordinario.

Esto reproduce storage growable dentro de la abstracción sin pedir raw
pointers, un allocator público ni compiler magic. Las APIs mutadoras son
métodos `mut` directos, no virtuales.

`finish()`:

1. comprueba que no haya path/polyline abierto y que state depth sea cero;
2. asigna buffers exactos para cada prefijo lógico;
3. copia linealmente los valores Copy;
4. construye una `Scene` válida con initializer no público;
5. marca el builder `sealed` y vacía sus buffers de trabajo.

Por la semántica class de Aether puede haber aliases del mismo builder.
`finish()` sella todos esos aliases; cualquier mutación o segundo finish lanza
`InvalidSceneStateException`. La Scene final no aliasa storage mutable del
builder.

### 14.2 Scene

`Scene` es una class final con fields privados, sólo métodos read y ninguna
operación de mutación. Posee viewport y los cinco buffers exactos. Una variable
`Scene` posee un strong handle; copiar un lvalue crea el Alias ARC ordinario y
la última release destruye buffers y objeto. No existen ciclos internos.

Los accessors públicos son conceptualmente:

```text
viewport()
commandCount(), commandAt(i)
pointAt(span, i)
pathVerbAt(span, i)
textRecordAt(i)
utf8ByteAt(span, i)
```

Todos retornan valores Copy. No retornan references/views que escapen ni
exponen Buffers mutables. El índice inválido es un programming error y conserva
el trap bounds general. Un backend obtiene los spans sólo desde commands/records
de la misma Scene, por lo que un traversal correcto no dispara ese trap.

La class allocation es una allocation fija por Scene, no por command. Sus read
methods tienen receiver exacto y dispatch estático. Un backend normalmente
recibe `ref Scene`, por lo que traversal no crea Scene Alias/retain por item.

### 14.3 Figure

No existe `Figure` en este milestone. Plots puede construir y retornar una
`Scene`; un futuro `Figure` de Plots poseerá o compartirá ese handle y metadata
de plotting en su propia capa. Scene no posee consumer, backend, target ni
output.

El compiler actual todavía restringe aggregates/class graphs que almacenan
class handles. Esa limitación puede afectar una Figure/UI retained futura,
pero no la foundation V1 ni un backend que recibe una Scene. Se registra como
capability de lenguaje futura; este ARCH no autoriza modificar compiler y no
contamina graphics con un wrapper alternativo.

## 15. Ownership y costes visibles

La tabla normativa es:

| Operación | Ownership | Copias / allocations visibles |
|---|---|---|
| crear builder | builder posee arenas growable | 1 class allocation; buffers lazy |
| agregar line/rect/point | copia aggregates Copy al command arena | amortized O(1); growth ocasional |
| agregar polyline desde Array/view | borrow sólo durante call; Scene nunca lo retiene | O(n) copia de Points |
| polyline incremental | cada Point se copia una vez al arena | O(n), sin Array temporal |
| agregar path incremental | cada PathVerb se copia una vez | O(v), sin owner por path |
| agregar text | borrows de string/style sólo durante call | O(bytes) copia UTF-8; sin string owner por command |
| `finish` | Scene nueva independiente; builder queda sealed | O(total arena entries), hasta 5 backings exactos + 1 object |
| Alias de Scene | shared strong handle inmutable | O(1), retain/release ordinario |
| render | borrow de Scene | O(commands + payload visitado), cero allocation por point |
| Drop Scene | última release destruye arenas | O(1) descriptor drops + frees; payloads son Copy |

Peak durante `finish` incluye buffers de capacity del builder y buffers exactos
de Scene simultáneamente. Después de publicar Scene se vacía el builder y se
libera su storage. V1 elige esta copia final porque entrega inmutabilidad real y
Buffers exactos usando capabilities actuales; una futura primitive general
`List.intoBuffer` podría eliminarla sin cambiar API ni semántica.

No se ofrece `polylineBorrowed`. No hay allocation por Point, PathVerb o
Command, sólo por crecimiento de arena. Text y named font family copian bytes;
no conservan Alias ARC del string fuente.

## 16. Validación, NaN e infinities

Graphics recibe geometry válida. El builder rechaza con
`InvalidGeometryException`:

- cualquier coordinate, size, transform coefficient o style scalar NaN/Inf;
- viewport negativo;
- Rect negativo o con límites no finitos;
- point diameter, text size o stroke width no positivos;
- miter limit menor que 1;
- polyline con menos de dos points;
- secuencia Path inválida.

La finitud se puede comprobar en Aether ordinario con un helper privado
equivalente a `(x - x) == +0` para `float64`; no se agrega intrinsic
`isFinite`. Todas las validaciones que pueden fallar se ejecutan antes de
publicar cambios de builder relacionados, salvo allocation failure abortiva.

Plots es responsable de interpretar datos científicos no finitos. En
particular, separa una serie en runs finitos, omite/marca muestras según su API
y llama a graphics sólo con esos runs. Graphics no ignora NaN, no corta una
polyline automáticamente y no transforma Inf en un límite del viewport.

Valores finitos extremos son válidos. La foundation los preserva exactamente
en float64. Si aplicar geometry a un target excede el range interno de ese
backend, éste reporta `UnsupportedGraphicsFeatureException` o un subtipo
backend-specific más preciso; no cambia la Scene. SVG normalmente puede conservar los
operandos y transforms finitos como números textuales sin hacer ese narrowing.

## 17. Modelo de errores

Las categorías públicas mínimas son nominales:

```text
InvalidGeometryException
InvalidSceneStateException
GraphicsBackendException
    UnsupportedGraphicsFeatureException
    GraphicsTextException
    GraphicsIoException
```

`InvalidGeometryException` cubre runtime input que los tipos escalares no
pueden prevenir, como NaN o width negativo. `InvalidSceneStateException` cubre
underflow/unbalanced state, verbs fuera de path, operaciones después de
`finish` y otros usos inválidos del builder. Color channels, line caps, joins,
fill rules y paint presence no necesitan exceptions porque sus tipos hacen el
estado inválido inrepresentable.

`UnsupportedGraphicsFeatureException` significa que el target concreto no
puede preservar un command válido; nunca habilita degradación silenciosa.
`GraphicsTextException` cubre font resolution/shaping/encoding del backend.
`GraphicsIoException` cubre escritura/export externa. Los backends pueden
declarar subtipos más precisos, pero no reutilizan invalid geometry para IO o
fonts.

Bounds, integer overflow de sizes y allocation failure conservan los traps
generales del lenguaje. Un backend V1 que se anuncie conforme debe soportar
todos los Commands V1; “unsupported” queda para límites reales del target, no
para publicar un renderer parcial sin documentarlo.

## 18. Frontera del backend

No existe una interface `Renderer` obligatoria ni callbacks por command. La
forma preferida es un free function backend-specific:

```aether
// Conceptual; se cierra en el ARCH del backend.
public string graphics.svg.render(ref graphics.Scene scene);
```

Un backend que escribe a archivo puede ofrecer otra función/options y reportar
IO. Ambos hacen:

```text
for commandIndex in 0 .. scene.commandCount
    command = scene.commandAt(commandIndex)
    match command
        ... obtener ranges por accessors y bajar al target ...
```

El match es estático sobre el payload enum nominal. No hay string dispatch,
reflection, vtable, boxing, registry global ni call indirecta por primitive.
Una aplicación que quiera elegir backend dinámicamente puede envolver estas
free functions en su propia política; no se cobra ese coste a todos.

La foundation define el significado de Commands y la validez de Scene. Cada
backend define options, output, escaping, encoding y failures de target. No se
permite que el backend modifique Scene durante render.

## 19. Compatibilidad con SVG posterior

El futuro backend SVG puede traducir directamente:

| Graphics | Lowering SVG posible, no normativo para foundation |
|---|---|
| DrawPoint | `circle` |
| DrawLine | `line` o `path` |
| DrawPolyline | `polyline` o `path` |
| DrawRect | `rect` |
| DrawPath | `path d=...` |
| DrawText | `text` con escaping y whitespace preservado |
| ConcatTransform | `transform`/grupo |
| IntersectClipRect | `clipPath` + grupo/reference interna |
| Fill/Stroke | attributes/style generados por backend |

CubicTo evita aproximar curvas en SVG. Rectangle y polyline separados evitan
inflar el path arena y permiten tags directos, pero el backend puede bajarlos a
path si conserva semántica.

No se necesita otra primitive exclusivamente SVG. IDs de clip, nesting de
`g`, formatting decimal, namespaces, attributes, XML escaping, `viewBox` y
serialización pertenecen a `graphics.svg`. Ningún tag, attribute name, URI,
CSS string ni fragmento XML entra a `graphics`.

## 20. Raster, ventanas y GPU futuros

La display list no promete que esos backends sean fáciles, sólo evita
bloquearlos:

- raster puede recorrer painter's order, mantener state stack y scan
  convert/tessellate paths sin reinterpretar SVG;
- una ventana puede renderizar una Scene por frame y decidir fuera de graphics
  cuándo invalidar o presentar;
- GPU puede bajar Commands a batches/buffers propios, siempre preservando
  order, clips y source-over;
- UI retained conserva su tree/layout/events y produce Scene; no fuerza
  identity/event handlers dentro del display list;
- documentos/notebooks pueden componer Scenes o pedir output a un backend sin
  que text se vuelva ASCII o SVG markup.

No se agregan device objects, command queues, surfaces, textures, swapchains,
threads ni resource interfaces hasta que un backend real los necesite.

## 21. Package boundary

La distribución elegida es una **OAL ordinaria `graphics`**:

```text
package graphics;       // foundation, este milestone
package graphics.svg;   // backend futuro dentro de la misma family/version
```

La foundation ocupa el root para evitar el redundante `graphics.core`. El
child backend importa/depende sólo hacia adentro; `graphics` nunca importa
`graphics.svg`. Otros children futuros pueden ser `graphics.raster` o adapters
reales si se justifican.

Según el package manager vigente, una versión publicada posee un único root y
sus descendants. Por eso `graphics.svg` como child implica una distribución
OAL/version family común. Si en el futuro se exige versionado/instalación
independiente del SVG backend, debe usarse otro root de registry, por ejemplo
`graphicsSvg`; dos packages no pueden contribuir competitivamente al mismo
root `graphics`. V1 elige la family común y no inventa esa separación.

Graphics no pertenece a Core porque no introduce semántica de lenguaje,
literal, ownership, primitive numérica ni operación que el compiler deba
reconocer. Tampoco pertenece a std: es una capa de dominio evolucionable con
backends opcionales. Ser OAL expresa ownership/distribución, no privilegios,
ABI especial, prelude ni intrinsics.

## 22. Implementabilidad en Aether ordinario

Foundation V1 se expresa con:

- structs y payload enums nominales;
- concrete `Buffer<T>` de payloads Copy;
- classes finales con fields privados y métodos directos;
- references para inputs prestados;
- loops, checked arithmetic y exceptions ordinarias;
- byte access UTF-8 de `std.Text` al construir text records.

No requiere raw pointers, FFI, compiler-known graphics types, custom drop,
generic associated types, reflection ni intrinsics gráficos. `Transform2D` es
source ordinario y no modifica `Matrix<T>`.

Capability real ausente registrada: almacenar handles class dentro de otros
aggregates/classes sigue restringido y será necesario para ciertos retained
models futuros. No se resuelve aquí. Tampoco se requiere retornar un borrowed
view desde Scene: accessors Copy evitan depender de lifetimes escapables.

La implementación `GRAPHICS-FOUNDATION-V1` debe detenerse y abrir un milestone
de lenguaje separado si descubre que un `Buffer` de alguno de los aggregates
Copy cerrados o un field Buffer privado de class no está admitido realmente.
No se autoriza un opcode, runtime graphics ni allowlist por package como atajo.

## 23. Performance V1

Objetivos verificables:

- construcción amortized O(commands + points + verbs + text bytes);
- `finish` O(commands + points + verbs + text records + bytes);
- traversal O(commands + payload visitado);
- cero allocation por Point durante build o render;
- cero node allocation por primitive;
- polyline points y PathVerbs contiguos;
- iteration determinista en insertion order;
- cero deep copy o string allocation durante render de foundation;
- ningún dispatch dinámico requerido;
- command/state stack memory del backend O(nesting depth), no O(commands),
  fuera del output que produzca.

V1 acepta la copia exacta de `finish`, los growth reallocations amortized, la
class allocation de builder y la class allocation de Scene. Estos costes son
parte pública de la expectativa y no se describen como zero-copy.

## 24. Qualification futura

`GRAPHICS-FOUNDATION-V1` debe incluir tests sin screenshot comparison.

### 24.1 Commands y state

- insertion/painter order exacto;
- Scene vacía;
- Push/Pop balanceado, nesting y underflow;
- composición no conmutativa de translate/scale/rotate;
- transform singular y rechazo de composición no finita;
- clips anidados/intersectados en scene coordinates;
- clip vacío conservado;
- finish con state/path/polyline abierto rechazado;
- segundo finish y mutación de alias sealed rechazados.

### 24.2 Geometry y style

- Point, line igual-degenerate, polyline de 2/n points;
- rechazo de polyline 0/1;
- Rect normal y zero width/height;
- FillOnly/StrokeOnly/FillAndStroke y orden fill-then-stroke;
- todas las caps, joins, fill rules, alpha endpoints y miter limits;
- Path multi-subpath con Move/Line/Cubic/Close;
- rechazo independiente de cada secuencia Path inválida;
- ausencia de dash, arc/image commands en superficie V1.

### 24.3 Text

- bytes exactos ASCII, multibyte y combining marks;
- whitespace inicial/interno/final preservado;
- NUL/LF/CR preservados en Scene;
- generic y named font requests;
- alignment/baseline/weight/slant preservados;
- source string y family modificados/released después del add sin afectar
  Scene;
- cero Alias string retained por Scene.

### 24.4 Ownership y storage

- mutar el Array fuente tras agregar una polyline no cambia la Scene;
- destruir fuentes antes de render es seguro;
- aliases de Scene observan el mismo contenido inmutable;
- última release libera una vez objeto y cinco backings no vacíos;
- allocation counters demuestran arenas, no allocation por primitive/point;
- spans exactos, contiguos, no solapados accidentalmente y dentro de arena;
- render traversal no asigna ni muta Scene.

### 24.5 Límites y backend independence

- viewport `0×0`, `0×h`, `w×0`;
- coordinates negativas y extreme finite preservadas;
- cada NaN, `+Inf` y `-Inf` rechazado en position, Rect, transform, width,
  miter, diameter y text size;
- consumer independiente recorre toda Scene sólo por accessors y payload
  enums;
- source/IR scan sin `svg`, XML tags/attributes, PNG, toolkit, OS/GPU API,
  callbacks renderer, reflection o graphics intrinsic;
- O0/O2 con orden, valores y lifecycle equivalentes;
- `git diff --check`.

La foundation prueba semántica estructural, no pixels. Golden SVG pertenece al
backend SVG; raster image comparison pertenece al backend raster.

## 25. Alternativas rechazadas

| Alternativa | Motivo |
|---|---|
| retained scene graph V1 | identity/tree/editing y allocations sin necesidad de Plots V1 |
| primitive object/interface por node | heap + dynamic dispatch por draw |
| Scene mutable pública | invalida spans/state y obliga revalidación en cada backend |
| borrowed polyline dentro de Scene | lifetime/keepalive y render diferido inseguros |
| globals resueltas por primitive | duplica state y altera semántica de stroke/path |
| Canvas callbacks como backend | call indirecta obligatoria y difícil inspección/serialización |
| generic `Scene<T>` | code bloat y backend igualmente debe elegir scalar |
| `float32` público | precisión insuficiente para data transforms científicos |
| Color float | estados no finitos/tolerancias sin beneficio V1 |
| premultiplied Color público | filtra una decisión raster y complica SVG |
| `Matrix<float64>` para transform | shape/layout/checks generales innecesarios |
| path SVG completo | acoplamiento a un backend y superficie excesiva |
| raster image/URI V1 | pixel/decoding/resource ownership sin consumer inmediato |
| graphics en Core/std | no requiere semántica/compiler/toolchain privilegiada |

## 26. Secuencia posterior

El orden cerrado es:

```text
GRAPHICS-FOUNDATION-V1
GRAPHICS-SVG-BACKEND-ARCH-1
GRAPHICS-SVG-BACKEND-V1
PLOTS-ARCH-1
```

`GRAPHICS-FOUNDATION-V1` implementará solamente tipos, builder, Scene,
validación y qualification estructural descritos aquí. No debe adelantar
serialization SVG ni un demo de Plots dentro del package.

`GRAPHICS-SVG-BACKEND-ARCH-1` cerrará escaping XML, decimal formatting,
clip IDs, font/CSS mapping, output string/file, errors y qualification del
target usando la Scene ya estable. Sólo después `PLOTS-ARCH-1` decidirá data
mapping, axes, series, ticks, legends y tratamiento público de NaN/Inf.

## 27. Fuera de scope confirmado

Quedan expresamente fuera: Plots API, chart types, axes, ticks, legends,
series, layout general, widgets, GUI, events, animation, font engine, MathTeX,
notebooks, documentos, image decoding, rasterization, native windowing, 3D,
GPU, shaders, retained node identity, hit testing, accessibility y compiler
magic.
