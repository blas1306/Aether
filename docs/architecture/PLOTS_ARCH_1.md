# PLOTS-ARCH-1 — arquitectura nativa de plotting 2D

Estado: **ARQUITECTURA CERRADA; IMPLEMENTACIÓN BLOQUEADA**, enmendado
2026-10-31.

> **Enmienda normativa 1 (2026-10-31).** La API y la representación objetivo
> de Plots se preservan, pero los fields `title`, `xLabel` y `yLabel` de
> `Figure2D` dependen de `OOP-OWNING-STRING-FIELDS-V1`. El lenguaje vigente los
> rechaza con `E0401`; por tanto, toda frase de este documento que describa esos
> fields, su copia o su destrucción especifica comportamiento objetivo, no una
> capability ya admitida. `PLOTS-2D-LINE-V1` permanece **BLOCKED** y no autoriza
> implementación productiva hasta que esa dependencia general se implemente y
> califique. No se admite workaround específico de Plots.

Este documento diseña el primer vertical nativo de Plots para Aether:
`PLOTS-2D-LINE-V1`. La autoridad implementada de Graphics Foundation y del
backend SVG permanece cerrada y no se modifica.

Autoridades inspeccionadas:

- `graphics/src/lib.ae`;
- `graphics/src/svg.ae`;
- `GRAPHICS_FOUNDATION_ARCH_1.md` y su cierre V1;
- `GRAPHICS_SVG_BACKEND_ARCH_1.md`, su enmienda owning y su cierre V1;
- el builtin AST legacy de `src/aether/stdlib/plots.py`;
- el backend host legacy de `src/plot_backend.py`;
- los contratos vigentes de packages, class handles, references, ownership,
  `Array<T>`, `Buffer<T>`, strings y exceptions.

No se autoriza en este milestone ningún cambio de compiler, runtime, Core,
std, Graphics Foundation o SVG.

## 1. Decisión resumida

Plots será una OAL nativa ordinaria, explícita y backend-independent:

```text
Array<DataPoint> prestado
        |
        v  copia validada
plots.Figure2D.scene() --> graphics.Scene --graphics.svg--> string / archivo
```

`Figure2D` es un objeto explícito. No existen current figure, current axes,
`hold`, registry por número, backend de sesión ni estado global. La figura
posee una copia de los datos y configuración necesarios para construir una
Scene. Su método read `scene()` produce una Scene inmutable nueva. El adapter
`plots.svg` entrega esa Scene al serializer público de `graphics.svg`; no
serializa XML ni inspecciona Commands.

`PLOTS-2D-LINE-V1` contiene exactamente una serie lineal XY. Esa restricción
mantiene cerrado el primer vertical y no intenta reproducir la superficie
Matplotlib/Octave del builtin legacy.

## 2. Fronteras de responsabilidad

### 2.1 Plots

Plots es autoridad sobre:

- significado de coordenadas científicas X/Y;
- almacenamiento y validación de samples;
- política de NaN e infinities;
- límites automáticos, límites solicitados y expansión degenerada;
- layout del plot area dentro del viewport;
- transformación data-to-viewport, incluida inversión de Y;
- ejes, ticks, tick labels, title y axis labels;
- clipping del contenido de datos;
- estilo mínimo de la serie y painter order del chart;
- traducción de una figura a Commands públicos de Graphics;
- errores propios de dominio.

Plots no conoce XML, tags SVG, clip IDs, escaping, fonts instaladas, archivos
PNG, ventanas, display interactivo ni pixel buffers.

### 2.2 Graphics Foundation

Graphics es autoridad sobre:

- geometría finita en logical graphics units;
- `Viewport`, `Point`, `Rect`, `Stroke`, `TextStyle` y demás valores gráficos;
- `SceneBuilder`, su state stack y construcción incremental de polylines;
- copia de points/text a arenas y publicación de `Scene` inmutable;
- clipping rectangular en scene coordinates;
- Commands secuenciales y painter order;
- validación gráfica y lifecycle de builder/Scene.

Graphics no interpreta límites científicos, no calcula ticks, no decide cómo
tratar NaN y no sabe qué Command forma un eje.

### 2.3 SVG

`graphics.svg` es la única autoridad sobre:

- recorrido de una `graphics.Scene` y lowering SVG/XML;
- formato numérico del documento, escaping y encoding;
- clip definitions e IDs;
- mapping de strokes, text, transforms y colors;
- `render(ref Scene) -> string` y `save(ref Scene, ref string)`;
- `GraphicsTextException` y `GraphicsIoException` propios del target.

Plots no duplica, envuelve parcialmente ni copia el serializer.

## 3. Package y dirección de dependencias

La distribución propuesta usa una OAL root `plots`:

```aether
package plots;
import graphics;
```

El adapter opcional del mismo family/version usa:

```aether
package plots.svg;
import plots;
import graphics;
import graphics.svg;
```

La dirección normativa es:

```text
plots.svg -> plots -> graphics
     |                  ^
     +----> graphics.svg|
              -> graphics
```

Ni `graphics` ni `graphics.svg` importan `plots`. El package `plots` tampoco
importa `graphics.svg`, por lo que construir y consumir Scenes no obliga a
depender de un formato de exportación.

Como el package manager no permite que dos distribuciones contribuyan al mismo
root, `plots.svg` pertenece inicialmente a la misma distribución/version de
`plots`. Si se requiriera versionado independiente debe elegirse otro root; no
se soluciona con packages parciales competitivos.

## 4. Superficie V1 propuesta

Las firmas públicas normativas son las siguientes. Los cuerpos se omiten en
este bloque de arquitectura; el bloque no pretende ser por sí solo una source
unit compilable:

```aether
package plots;

import graphics;

public struct DataPoint {
    float64 x;
    float64 y;
}

public struct Limits {
    float64 minimum;
    float64 maximum;
}

enum LimitMode {
    Auto,
    Explicit(Limits),
}

public struct LineStyle {
    graphics.Color color;
    float64 width;
}

public struct FigureOptions {
    graphics.Viewport viewport;
    LimitMode xLimits;
    LimitMode yLimits;
    string title;
    string xLabel;
    string yLabel;
    LineStyle line;
}

public class Figure2D {
    // Private representation described in section 5.
    public graphics.Scene scene();
}

public FigureOptions defaultOptions();
public Figure2D line(ref Array<DataPoint> points, ref FigureOptions options);
```

El adapter SVG agrega, sin serializer propio:

```aether
package plots.svg;

import plots;

public string render(ref plots.Figure2D figure);
public void save(ref plots.Figure2D figure, ref string path);
```

`render` y `save` construyen una Scene mediante `(*figure).scene()` y llaman
respectivamente a `graphics.svg.render(&scene)` o
`graphics.svg.save(&scene, path)`.

No se usan argumentos nombrados ni default parameters en user functions. El
`FigureOptions` explícito evita depender de esas capabilities y hace visible
la configuración completa.

### 4.1 Defaults V1

`defaultOptions()` retorna:

- viewport `640 x 480`;
- ambos limits en `Auto`;
- title, X label e Y label vacíos;
- línea RGBA `(31, 119, 180, 255)`;
- line width `2.0`.

Una string vacía omite su primitive textual; no reserva un espacio distinto
del margin fijo V1.

### 4.2 Ejemplo válido en sintaxis Aether vigente

```aether
package lineExample;

import plots as p;
import plots.svg as psvg;

int main() {
    Array<p.DataPoint> samples = {
        p.DataPoint(0.0, 0.0),
        p.DataPoint(1.0, 1.0),
        p.DataPoint(2.0, 4.0),
        p.DataPoint(3.0, 9.0)
    };

    p.FigureOptions options = p.defaultOptions();
    options.title = "Cuadrados";
    options.xLabel = "x";
    options.yLabel = "x*x";
    options.xLimits = p.LimitMode.Explicit(p.Limits(0.0, 3.0));

    p.Figure2D figure = p.line(&samples, &options);
    string path = "cuadrados.svg";
    psvg.save(&figure, &path);
    return 0;
}
```

Mutar `samples` u `options` después de `line` no cambia `figure`.

## 5. Representación de la primera serie

La unidad lógica es `DataPoint(float64 x, float64 y)`, no dos owners paralelos
ni `graphics.Point`. Esto evita estados con longitudes X/Y diferentes y
mantiene separadas data coordinates de scene coordinates.

`Figure2D` posee conceptualmente:

```text
Buffer<DataPoint> samples
usize sampleCount
Viewport viewport
LimitMode xLimits
LimitMode yLimits
string title
string xLabel
string yLabel
LineStyle line
```

`DataPoint`, `Limits`, `LimitMode` y `LineStyle` son Copy/no-drop. Por ello
`Buffer<DataPoint>` es compatible con el predicado vigente de Buffer y con un
field privado de class. Las strings serán owners ordinarios directos de la
class, no elements del Buffer, una vez cerrada la dependencia
`OOP-OWNING-STRING-FIELDS-V1`. No son class handles y no se infiere su admisión
a partir de ARC de objetos.

`line` presta el `Array<DataPoint>` y `FigureOptions` sólo durante la call,
crea un Buffer exacto y copia cada point una vez. No retiene references,
views, el descriptor Array ni storage del caller. La figura es un class handle
normal: asignarla a otra variable crea un Alias ARC de la misma identidad.

V1 no ofrece mutadores. La figura publicada es lógicamente inmutable; crear
otra configuración produce otra figura. Esto elimina dirty state, invalidación
de cache y diferencias observables entre aliases. `scene()` es un método read
de la class, de modo que puede recorrer su Buffer privado sin publicar un
interior reference ni volver públicos sus fields.

## 6. Validación de construcción

`line` valida antes de publicar la figura:

- `points` debe contener al menos un elemento;
- viewport width/height deben ser finitos y suficientemente grandes para el
  plot area de la sección 9;
- line width debe ser finito y estrictamente positivo;
- cada explicit limit endpoint debe ser finito;
- para explicit limits, `minimum <= maximum`;
- strings se conservan exactamente como strings Aether válidos; Graphics/SVG
  deciden después si el target puede representar un control textual.

Los samples pueden contener valores no finitos. Esa aceptación es deliberada:
son separadores de runs y nunca se reenvían a Graphics.

La validación completa y la copia deben terminar antes de retornar el handle.
Un throw durante construcción destruye los owners parciales conforme al
lifecycle ordinario y no publica una figura a medio inicializar.

## 7. Política de samples no finitos

Un sample es **finito emparejado** si y sólo si `x` e `y` son finitos. Se usa
la comprobación source ordinaria equivalente a `(value - value) == 0.0`.

Un sample donde cualquiera de los componentes es NaN o infinity:

- no participa en extrema automáticos;
- no se transforma;
- no se entrega a `SceneBuilder`;
- termina el finite run actual;
- no produce conexión visual a través del gap.

No se clampa, sustituye ni interpreta infinity como un límite. Si no existe
ningún sample finito emparejado, `line` o `scene` —la implementación debe elegir
un único punto y probarlo— lanza `NoFiniteDataException`. La decisión preferida
es validar esto en `line`, para que toda `Figure2D` publicada sea renderizable.

Aunque ambos ejes tengan explicit limits, una serie sin samples finitos sigue
siendo inválida en V1. Un chart de ejes sin datos será una API distinta futura,
no una interpretación accidental de `line`.

## 8. Límites automáticos, explícitos y degenerados

### 8.1 Límites raw

Para cada eje:

- `Auto` obtiene minimum y maximum sobre todos los samples finitos emparejados;
- `Explicit(Limits(a,b))` usa exactamente `a,b` como autoridad inicial y no
  fuerza inclusión de los datos;
- `a > b`, NaN o infinity son inválidos.

Samples fuera de explicit limits se conservan en la serie y son recortados por
el clip; no se eliminan durante almacenamiento.

### 8.2 Intervalo no degenerado

Si `minimum < maximum`, V1 usa esos endpoints sin padding automático. Esto
mantiene ticks, geometría y goldens completamente predecibles. Una extensión
futura puede agregar padding como opción explícita sin cambiar esta semántica.

Además se exige que `span = maximum - minimum` sea finito y positivo. Dos
endpoints finitos cuyo span desborda no forman un domain representable para la
transformación V1 y producen `PlotRangeException`.

### 8.3 Intervalo degenerado

Si `minimum == maximum == c`, se expande determinísticamente:

```text
d = max(1.0, abs(c) * 0.05)
candidate = [c - d, c + d]
```

Si un endpoint de `candidate` no es finito, se usa el intervalo unilateral
finito `[c-d,c]` o `[c,c+d]`. El resultado debe tener dos endpoints finitos y
span finito positivo; de lo contrario se lanza `PlotRangeException`.

La misma regla se aplica a degeneración automática y explícita. Por tanto una
serie de un punto y un explicit range `[5,5]` tienen semántica definida, no una
división por cero ni un límite silently widened distinto.

### 8.4 Invariantes del domain resuelto

Antes de layout se cumple para X e Y:

```text
finite(minimum)
finite(maximum)
minimum < maximum
finite(maximum - minimum)
maximum - minimum > 0
```

## 9. Viewport y layout fijo V1

Graphics usa origen top-left. Plots reserva, en logical graphics units:

```text
left margin    = 72
right margin   = 24
top margin     = 48
bottom margin  = 64
```

Para viewport `(Vw,Vh)`:

```text
plotLeft   = 72
plotTop    = 48
plotWidth  = Vw - 96
plotHeight = Vh - 112
plotRect   = Rect(plotLeft, plotTop, plotWidth, plotHeight)
```

Plots exige `plotWidth > 0` y `plotHeight > 0`. Aunque Graphics admite un
viewport de área cero, una figura con axes, ticks y labels no tiene layout
V1 útil y se rechaza como `InvalidFigureException`.

Los margins son deliberadamente fijos porque Graphics no publica text
measurement. V1 no promete que labels arbitrariamente largos nunca se
solapen. El contenido sigue siendo válido y determinista.

## 10. Transformación data-to-viewport

Sean los límites resueltos `xmin,xmax,ymin,ymax` y el plot area
`L,T,W,H`. Para cada point finito:

```text
sx = W / (xmax - xmin)
sy = H / (ymax - ymin)

xv = L     + (x - xmin) * sx
yv = T + H - (y - ymin) * sy
```

La resta de Y es normativa: data Y crece hacia arriba y scene Y crece hacia
abajo. Los anchors son exactos en aritmética real:

```text
xmin -> L        xmax -> L + W
ymin -> T + H    ymax -> T
```

La implementación debe ordenar las operaciones como están escritas y usar
`float64`. Antes de entregar un point a Graphics comprueba que `xv` e `yv` son
finitos. Un overflow intermedio o resultado no finito produce
`PlotRangeException`; no se clampa silenciosamente.

Plots transforma los points explícitamente antes de agregarlos al builder. No
usa un `ConcatTransform` de escala de datos para la serie, porque en Graphics
stroke width pertenece al user space y una escala de datos cambiaría el grosor
visible de la línea. El stroke V1 permanece constante en scene units.

## 11. Ejes, ticks y etiquetas mínimos

Cada eje tiene exactamente cinco ticks, incluidos ambos endpoints. Para
`i = 0..4`:

```text
value(i) = minimum + (maximum - minimum) * float64(i) / 4.0
```

Se canonicaliza cualquier resultado igual a cero como `+0.0` antes de llamar
a `str`, evitando label `-0`. El label es `str(value)`; no hay formatter,
locale, scientific-notation policy adicional ni significant digits option.

Los ticks se posicionan aplicando la misma transformación. V1 dibuja:

- borde rectangular del plot area con stroke de 1 unit;
- cinco tick marks X de 6 units hacia abajo;
- cinco tick marks Y de 6 units hacia la izquierda;
- tick labels X centrados, top baseline, a 10 units del borde inferior;
- tick labels Y alineados right, middle baseline, a 10 units del borde
  izquierdo;
- title centrado en `(L + W/2, 24)` con middle baseline cuando no es vacío;
- X label centrado en `(L + W/2, Vh - 18)` con middle baseline cuando no es
  vacío;
- Y label centrado en `(24, T + H/2)`, rotado -90 degrees, cuando no es vacío.

Tick labels usan size 12, axis labels 14 y title 16, color negro y
`SansSerif`. El Y label se dibuja localmente en `(0,0)` bajo
`Transform2D(0,-1,1,0,24,T+H/2)`. La rotación usa `pushState`,
`concatTransform`, `drawText`, `popState`; no altera clipping ni primitives
posteriores.

No hay minor ticks, grid, tick selection “nice”, exponent offset, units,
secondary axes, log scale ni text collision solver en V1.

## 12. Clipping, polylines y painter order

La secuencia normativa de construcción es:

1. fondo blanco del viewport;
2. `pushState`;
3. `intersectClipRect(plotRect)` en scene coordinates;
4. finite runs de la serie, en input order;
5. `popState`;
6. borde de axes;
7. tick marks;
8. tick labels;
9. axis labels;
10. title.

El clip se instala antes de los draws de datos y se restaura antes de axes y
texto. Es correcto respecto al contrato de Graphics: `IntersectClipRect`
recibe scene coordinates y no depende de transforms. El borde se dibuja
después de la serie para que una línea sobre un límite no tape el frame.

No se precortan segmentos con un algoritmo geométrico propio. Se transforman
los endpoints finitos y Graphics/SVG aplican el clip rectangular. Esto preserva
correctamente la intersección de segmentos que cruzan el plot area aunque
ambos endpoints estén fuera.

Cada finite run de longitud al menos dos se emite exclusivamente mediante:

```aether
builder.beginPolyline();
builder.addPolylinePoint(...);
// ...
builder.endPolyline(stroke);
```

No se construye un `Array<graphics.Point>` temporal. Los points pasan una vez
al arena incremental de `SceneBuilder` y luego siguen el `finish` ordinario de
Graphics.

## 13. Cero, uno y múltiples points

- **Cero samples:** `line` lanza `EmptySeriesException`. No crea figura ni
  Scene vacía.
- **Un sample finito:** los dos ejes degenerados se expanden según la sección
  8 y el sample se dibuja con `drawPoint`, usando diámetro igual a
  `max(2.0, line.width)`. Es un fallback de visibilidad de una serie lineal
  degenerada, no una API scatter ni un marker configurable.
- **Múltiples samples:** cada finite run de longitud >= 2 es una polyline
  incremental. Un run aislado por gaps no finitos se dibuja con el mismo
  fallback `drawPoint`. Nunca se conectan runs.

El orden entre runs y singleton points es exactamente el orden de aparición en
la entrada. No se ordena por X, no se deduplican points y X puede decrecer.
Points consecutivos iguales son válidos.

## 14. Estilo V1

Sólo se expone color RGBA y line width. El stroke se construye con:

```text
cap        = Butt
join       = Miter
miterLimit = 4.0
```

No se parsean strings `fmt`, nombres de colors, markers ni linestyles. No hay
alpha separado: está contenido en `graphics.Color`. Dash queda fuera porque
Graphics V1 no lo representa.

Axes/text usan un theme fijo V1. Exponer theme completo, fonts o layout sería
una extensión posterior y no condiciona la representación de datos.

## 15. Exportación SVG

La implementación de `plots.svg` es un adapter delgado:

```text
render(figure):
    scene = (*figure).scene()
    return graphics.svg.render(&scene)

save(figure, path):
    scene = (*figure).scene()
    graphics.svg.save(&scene, path)
```

No lee `scene.commandAt`, no crea XML, no cambia extensiones, no crea
directorios y no captura exceptions de Graphics. Un mismo Figure genera los
mismos Commands y el mismo SVG byte-for-byte en O0/O2 bajo el mismo compiler.

El retorno de `render` pertenece al caller. `save` presta el path durante la
call. La Scene temporal vive hasta que el serializer termina y luego se libera
normalmente.

## 16. Ownership y costes

| Operación | Ownership | Coste visible |
|---|---|---|
| `line(points, options)` | borrows call-scoped; Figure copia datos y strings | O(n) y un Buffer exacto |
| alias de Figure | shared class handle ARC | O(1) retain/release |
| `figure.scene()` | receiver read; Scene nueva owner | O(n + commands + text bytes) |
| finite run >= 2 | points pretransformados se copian al arena incremental | O(run length), sin Array temporal |
| `graphics.SceneBuilder.finish` | Scene independiente | copia exacta definida por Graphics |
| `plots.svg.render` | borrow Figure, Scene temporal, string owner | coste de scene + serializer SVG |
| drop Figure | última release destruye strings, Buffer y objeto | una vez por identidad |

No existe reference almacenada en Figure o Scene. El adapter SVG recibe
`ref Figure2D` e invoca su método read a través del borrowed handle, sin crear
un Alias por point.

V1 no cachea la Scene dentro de Figure. Cada llamada a `scene`, `render` o
`save` reconstruye el display list de forma determinista.

## 17. Modelo de errores

Plots declara categorías nominales propias:

```aether
public open class PlotException : Exception {
    public init() {}
}

public class EmptySeriesException : PlotException {
    public init() : base() {}
}

public class NoFiniteDataException : PlotException {
    public init() : base() {}
}

public class InvalidFigureException : PlotException {
    public init() : base() {}
}

public class InvalidLimitsException : PlotException {
    public init() : base() {}
}

public class PlotRangeException : PlotException {
    public init() : base() {}
}
```

Clasificación:

| Condición | Error |
|---|---|
| input vacío | `EmptySeriesException` |
| ningún par finito | `NoFiniteDataException` |
| viewport sin plot area o width de línea inválido | `InvalidFigureException` |
| explicit endpoint no finito o min > max | `InvalidLimitsException` |
| span/expansión/transformación no representable | `PlotRangeException` |
| bug de protocolo del builder | `graphics.InvalidSceneStateException` |
| geometría gráfica inválida que escapó validación Plots | `graphics.InvalidGeometryException` |
| texto no representable por SVG | `graphics.GraphicsTextException` |
| fallo de escritura | `graphics.GraphicsIoException` |

Plots no captura y reclasifica exceptions de Graphics/SVG. Hacerlo perdería la
categoría real del backend. Bounds, allocation failure y overflow de tamaños
conservan traps generales del lenguaje.

## 18. Relación con Plots legacy

El builtin legacy y `PlotBackend` host son una autoridad de compatibilidad a
auditar, no una API a copiar. V1 nativo rechaza deliberadamente:

- singleton global de backend y current figure;
- figures numeradas;
- `plot!`, `hold` y clearing implícito;
- elección interactive/document del proceso;
- Matplotlib, NumPy y callbacks Python;
- `savefig` PNG y nombres autogenerados;
- strings `fmt` y dictionaries de keywords;
- coerción dinámica de arrays, vectors y matrices;
- sampling de function values;
- scatter, bar, histogram y legends.

La correspondencia inicial es únicamente una serie XY lineal, title, axis
labels, limits y export SVG explícita.

## 19. Qualification de `PLOTS-2D-LINE-V1`

### 19.1 Matriz

| Área | Evidencia O0 | Evidencia O2 | Criterio |
|---|---:|---:|---|
| API/package consumer | sí | sí | check/build/run de consumer externo |
| 0/1/N samples | sí | sí | exceptions o Commands esperados |
| limits auto/explicit | sí | sí | extrema y anchors exactos |
| degenerate X/Y/both | sí | sí | expansión normativa, sin división por cero |
| NaN/+Inf/-Inf | sí | sí | gaps, extrema finitos, rechazo all-nonfinite |
| transform | sí | sí | cuatro corners, interior y Y invertido |
| clipping | sí | sí | segmentos cruzando cada borde y corner |
| runs | sí | sí | sin conexión sobre gaps; orden exacto |
| axes/ticks/text | sí | sí | cinco ticks, positions y strings exactos |
| painter order | sí | sí | command traversal exacto |
| ownership | sí | sí | mutation-after-call no altera Figure/Scene |
| lifecycle | sí | sí | aliases, normal/throw, heap balance |
| SVG | sí | sí | golden completo y XML parseado |
| native purity | sí | sí | source/IR sin Python/Matplotlib/FFI |

### 19.2 Qualification geométrica

Los tests inspeccionan `graphics.Scene`, no sólo screenshots:

- viewport y plotRect exactos;
- clip command entre push/pop y antes de datos;
- número y spans de `DrawPolyline`;
- transformed points con tolerancia float64 definida;
- singleton `DrawPoint` y diámetro;
- frame/ticks/text después del pop;
- tick endpoint labels y zero canonicalizado;
- Y label dentro de un state transform balanceado;
- absence de raw NaN/Inf en todos los Commands y records.

Se incluyen domains positivos, negativos, cruzando cero, magnitudes pequeñas,
degenerados, explicit clipping y finite extremes que deben producir
`PlotRangeException`.

### 19.3 Qualification visual

Goldens SVG completos cubren al menos:

- línea creciente con title y labels;
- Y invertido observable;
- singleton;
- múltiples runs por NaN;
- explicit limits recortando segmentos;
- alpha y line width no default.

Cada golden se genera en O0 y O2, se compara byte-for-byte entre modos y contra
el archivo versionado, y se parsea como XML. Una inspección raster opcional
puede ayudar al review humano, pero no reemplaza assertions geométricas/DOM y
no forma parte del runtime productivo.

### 19.4 Qualification nativa e IR

Los gates deben demostrar:

- `aether check/build/run` del package y consumer en O0/O2;
- misma secuencia de Commands, values y exceptions en ambos modos;
- mismo SVG completo en ambos modos;
- `Buffer<DataPoint>` privado y copies sin reference escapada;
- uso de `SceneBuilder.beginPolyline/addPolylinePoint/endPolyline`;
- calls directas a `graphics.svg.render/save` desde el adapter;
- ausencia de builtin `Plots`, `src/plot_backend.py`, Python, NumPy,
  Matplotlib, FFI, registry, intrinsic o package allowlist;
- HIR/MIR/SSA/LLVM verificables y `git diff --check`.

## 20. Limitaciones concretas vigentes

### 20.1 No bloquean el diseño de este V1

1. **Class handles en retained graphs.** El lenguaje no admite en general
   guardar class handles dentro de aggregates/classes. Por ello `Figure2D` no
   puede poseer/cachear una `graphics.Scene` ni una colección de series como
   objetos class. V1 guarda datos Copy y reconstruye Scene.
2. **Buffer de owners.** `Buffer<E>` exige elements Copy/no-drop. Una futura
   `LineSeries` que posea strings o buffers no puede ser element directo de
   `Buffer<LineSeries>`. Múltiples series requerirán arenas planas/spans o una
   capability general diseñada por separado.
3. **Interior borrows de fields class.** No se puede prestar el Buffer interior
   de Figure a una API externa. `scene` itera mediante métodos/read access
   internos de Figure y publica sólo valores Copy/Scene owner.
4. **Named/default user arguments.** No están disponibles como API nativa
   general. V1 usa `FigureOptions` explícito.

Estas limitaciones influyen en la forma elegida y no alteran la API objetivo.

### 20.2 Dependencia bloqueante de implementación

El preflight demostró que un field owning de tipo exacto `string` en una class
es rechazado por el frontend con `E0401`. `Figure2D` requiere tres de esos
fields para poseer su configuración sin retener borrows. La dependencia se
resolverá sólo mediante la capability general
`OOP-OWNING-STRING-FIELDS-V1`, con init, Alias/Transfer, replacement, drop,
herencia y unwind verificados. Hasta entonces no se implementan `plots` ni
`plots.svg`, y no se sustituyen los textos por globals, borrows retenidos,
Buffers de bytes, intrinsics o allowlists.

### 20.3 Limitaciones de API gráfica, no del lenguaje

- Graphics no mide text: layout y margins son fijos y no hay garantía de no
  overlap para strings arbitrarias.
- Graphics no ofrece dash: line styles discontinuos se difieren.
- SVG es un backend de documento: interactividad/windowing requiere otro
  backend futuro, no estado de sesión dentro de Plots.

`Buffer<DataPoint>` privado y `ref Figure2D` superaron el control positivo del
preflight. Los strings owning no están admitidos y constituyen el bloqueo ya
registrado; cualquier otro gap debe detener el vertical y abrir un milestone
general. No se autoriza un intrinsic, allowlist `plots` ni lowering especial.

## 21. Fuera de scope V1

Quedan expresamente fuera:

- más de una serie y legends;
- scatter y markers configurables;
- histogram, bar, area y error bars;
- sampling de funciones;
- implicit X indices y matrices multi-column;
- grid, minor ticks y nice tick locator;
- log/symlog/category/date axes;
- subplots, secondary axes y aspect constraints;
- pan, zoom, hit testing, events y ventanas;
- PNG/raster, PDF y display notebook;
- themes, arbitrary fonts, MathTeX y rich text;
- mutation incremental de Figure y Scene caching.

Son extensiones futuras, no placeholders que V1 deba implementar.

## 22. Secuencia propuesta

```text
PLOTS-ARCH-1                         este documento
PLOTS-2D-LINE-V1                     package, tests y consumer nativos
PLOTS-SVG-ADAPTER-V1                 puede cerrar en el mismo vertical
PLOTS-MULTI-SERIES-ARCH              sólo si existe una necesidad concreta
PLOTS-OTHER-CHARTS                   milestones independientes
```

La implementación V1 debe preservar las fronteras: Plots produce una Scene,
Graphics la representa y SVG la serializa.

**CLOSED.**
