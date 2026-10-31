# PLOTS-FUNCTION-SAMPLING-ARCH-1 — muestreo uniforme de funciones

Estado: **ARQUITECTURA CERRADA; IMPLEMENTACIÓN NO INICIADA**, 2026-10-31.

Este documento diseña una extensión ordinaria del package nativo `plots` para
construir una `Figure2D` desde una función escalar Aether. No implementa la
extensión ni modifica compiler, runtime, Graphics, SVG, `plots.line()` o
ejemplos personales.

Autoridades inspeccionadas:

- `plots/src/lib.ae`, `plots/src/svg.ae` y la qualification
  `plots_2d_line_v1.rs`;
- [PLOTS-ARCH-1](PLOTS_ARCH_1.md) y
  [PLOTS-2D-LINE-V1](PLOTS_2D_LINE_V1_REPORT.md);
- la implementación y qualification actuales de function values, incluido
  `function_values_v1.rs`;
- el dogfood multi-package de `examples/numerical_methods`;
- los contratos vigentes de `Array<T>`, `Buffer<T>`, generics, exceptions,
  traps de allocation y aritmética IEEE-754.

## 1. Decisión resumida

La extensión será una función libre de `plots` que materializa un
`Array<DataPoint>` temporal, evalúa la función una vez por muestra en orden
ascendente y delega sin excepciones en `plots.line()`:

```text
Function<(float64), float64> + [a,b] + N
                    |
                    v
          Array<DataPoint> temporal
                    |
                    v
              plots.line()
                    |
                    v
               Figure2D ordinaria --plots.svg--> SVG
```

No se agrega una ruta geométrica, un tipo de figura, estado global, serializer,
intrinsic ni regla del compilador. La política de finite runs, límites,
clipping, layout, ownership de la figura y exportación sigue teniendo una sola
autoridad: `line()` y el adapter `plots.svg` existentes.

## 2. Capacidades reales inspeccionadas

### 2.1 Function values

La forma fuente implementada es estructural y exacta:

```aether
Function<(P1, P2, ...), R>
```

Para esta API el tipo concreto es `Function<(float64), float64>`. Un function
value vigente:

- referencia una función Aether top-level, no genérica y visible;
- ocupa un word, es `Copy`, `Relocatable` y `Storable`, y no necesita drop;
- no contiene environment, ARC, allocation ni estado capturado;
- se pasa por valor y se llama indirectamente con la firma exacta;
- puede lanzar una exception unchecked; la call indirecta conserva unwind y
  cleanup;
- puede proceder de otro package mediante los imports ordinarios.

No se admiten como valores lambdas, closures, funciones anidadas capturantes,
métodos enlazados, constructors, intrinsics ni builtins. Por ejemplo, `sin` no
puede pasarse directamente, pero un wrapper top-level sí:

```aether
float64 sine(float64 x) {
    return sin(x);
}
```

No se diseña una sintaxis callable nueva y no se presupone captura de
coeficientes. Una familia parametrizada por datos necesita por ahora funciones
top-level distintas o una futura capability general de closures; Plots no la
simula con globals o registries.

### 2.2 Generics

`Function<(T), T>` puede aparecer dentro de una función genérica y se concreta
antes de MIR. Eso no hace referenciable una declaración genérica abierta: una
función `identity<T>` no puede convertirse implícitamente en
`Function<(float64), float64>`. Tampoco existe partial application.

La extensión de Plots no necesita ser genérica. Aceptar únicamente `float64`
coincide con `DataPoint`, evita conversion thunks y mantiene exacta la firma
indirecta. Funciones de otro dominio deben usar un wrapper top-level con la
conversión explícita que corresponda.

### 2.3 Arrays, Plots y ownership

`Array<DataPoint>(n, initial)` crea un owner de longitud fija y permite llenar
sus elementos por índice. `DataPoint` es Copy/no-drop. `line(ref Array<...>,
ref FigureOptions)` presta ambos argumentos, copia los puntos a un
`Buffer<DataPoint>` exacto propiedad de `Figure2D` y copia la configuración que
debe sobrevivir a la call.

La implementación real de `line()`:

- rechaza input vacío, options inválidas y ausencia total de pares finitos;
- calcula extrema sólo sobre pares `(x,y)` ambos finitos;
- trata cualquier punto con X o Y no finito como separador de finite runs;
- nunca reenvía NaN o infinity a Graphics;
- valida spans y transformaciones representables;
- publica una figura independiente del Array y de las options del caller.

El adapter `plots.svg` sólo construye `figure.scene()` y delega en
`graphics.svg.render/save`. La nueva función retorna exactamente esa misma
`Figure2D`; por tanto no requiere cambios del adapter.

### 2.4 Exceptions, traps e IEEE-754

Las exceptions Aether son unchecked y no forman parte de la identidad de
`Function`. Una exception de la función muestreada puede atravesar la call
indirecta conservando los cleanups de owners vivos.

NaN, `+Inf`, `-Inf`, signed zero, overflow y underflow siguen la semántica
IEEE-754 existente. La comprobación de finitud usada por Plots es equivalente a
`(value - value) == 0.0`. Allocation-size overflow y allocation failure son
traps fail-fast generales, no exceptions capturables ni errores nuevos de
Plots.

## 3. API pública normativa

Se agregan al package `plots` exactamente estas declaraciones:

```aether
public class InvalidSampleCountException : PlotException {
    public init() : base() {}
}

public class InvalidSampleIntervalException : PlotException {
    public init() : base() {}
}

public Figure2D plotFunction(
    Function<(float64), float64> target,
    float64 a,
    float64 b,
    usize sampleCount,
    ref FigureOptions options);
```

`target` se pasa por valor porque Function es Copy y no posee environment.
`FigureOptions` conserva el borrow y el spelling de `line()`. No se agrega un
overload sin options: el caller usa `defaultOptions()` explícitamente. Tampoco
se expone el Array temporal ni un tipo `FunctionFigure`.

Ejemplo de consumo objetivo:

```aether
package functionPlotExample;

import plots as p;
import plots.svg as svg;

float64 wave(float64 x) {
    return sin(x);
}

int main() {
    p.FigureOptions options = p.defaultOptions();
    options.title = "sin(x)";
    p.Figure2D figure = p.plotFunction(wave, -3.141592653589793,
        3.141592653589793, usize(257), &options);
    string path = "wave.svg";
    svg.save(&figure, &path);
    return 0;
}
```

La declaración `wave` es top-level y no captura estado.

## 4. Precondiciones y clasificación de errores

Las validaciones propias de `plotFunction` ocurren en este orden, antes de
allocation o evaluación de `target`:

1. `sampleCount >= 2`; en caso contrario,
   `InvalidSampleCountException`;
2. `a` y `b` finitos y `a < b`; en caso contrario,
   `InvalidSampleIntervalException`;
3. `span = b - a` finito y positivo; si los endpoints finitos producen un
   span no representable, `PlotRangeException`.

Se exige un intervalo no degenerado y orientado ascendentemente. Esta API
representa una función sobre `[a,b]`, no una serie arbitraria; permitir `a==b`
duplicaría N veces el mismo punto y permitir `a>b` ocultaría el orden de
evaluación. Una función constante se admite normalmente: la restricción es
sobre X, no sobre Y.

Después del muestreo, `line()` conserva sus errores actuales. En particular:

| Condición | Resultado |
|---|---|
| `sampleCount < 2` | `InvalidSampleCountException`, cero calls a `target` |
| endpoint NaN/Inf o `a >= b` | `InvalidSampleIntervalException`, cero calls |
| `b-a` no finito | `PlotRangeException`, cero calls |
| fallo de allocation del Array | trap general, cero calls |
| coordenada generada no finita | `PlotRangeException`, calls del prefijo previo |
| `target(x)` lanza | misma exception, sin reclasificar |
| todos los Y son no finitos | `NoFiniteDataException`, después de N calls |
| options inválidas | error vigente de `line()`, después de N calls |
| SVG no representable o I/O | error vigente de Graphics/SVG, al exportar |

No se duplican en `plotFunction` las validaciones privadas de `line()`. Por
ello una viewport, line width o explicit limits inválidos se observan al
delegar, después de evaluar N veces. Este orden es parte del contrato y evita
que dos entry points compitan como autoridad sobre `FigureOptions`.

## 5. Grid uniforme y orden exacto

Sea `N = sampleCount`, `d = N - 1` y `span = b - a`, calculado una vez después
de las precondiciones. Para índices `i` crecientes de `0` a `N-1`:

```text
i == 0       : x_i = a
i == N - 1   : x_i = b
otro caso    : t_i = float64(i) / float64(d)
               x_i = a + span * t_i
```

El orden de operaciones escrito es normativo. No se permite reassociation,
recurrence acumulativa `x += step`, FMA implícito que cambie el resultado ni
fast-math. Los extremos se asignan explícitamente, no dependen del redondeo de
la fórmula interior.

“Uniforme” significa el grid real ideal `a + (b-a)i/(N-1)` representado por la
secuencia IEEE anterior. No promete que todos los `float64` resultantes sean
distintos ni que las diferencias consecutivas sean bitwise iguales. Para N o
magnitudes grandes, dos índices pueden redondear al mismo X; siguen siendo dos
muestras y `target` se evalúa para ambas. No se impone un cap arbitrario a N;
los límites reales de tamaño permanecen en los traps generales de Array.

Cada `x_i` se comprueba como finito antes de llamar a `target`. Aunque las
precondiciones hacen que el resultado matemático esté entre endpoints finitos,
el check cierra explícitamente cualquier overflow de la secuencia IEEE. Si
falla en `i`, se lanza `PlotRangeException`: ya ocurrieron exactamente `i`
calls y no ocurren calls posteriores.

Para cada índice válido el orden es:

1. calcular y validar `x_i`;
2. ejecutar exactamente una vez `y_i = target(x_i)`;
3. almacenar exactamente `DataPoint(x_i, y_i)`;
4. avanzar al índice siguiente.

No se reintenta, preevalúa, vectoriza, paraleliza, ordena ni elimina una call,
aun si X se repite o el resultado no se usa después. Finalizado el loop,
`line()` no vuelve a invocar `target`.

## 6. NaN, infinities y discontinuidades

El sampler conserva literalmente el `float64` retornado por `target`.

- Y finito produce un par finito y participa en extrema/runs.
- Y NaN, `+Inf` o `-Inf` produce un punto no finito que `line()` usa como gap.
- Un único valor no finito separa los runs finitos anterior y posterior.
- Si no hay ningún Y finito, `line()` lanza `NoFiniteDataException` después de
  completar todas las evaluaciones.

Como todos los X generados son finitos, la finitud del par depende únicamente
de Y. Con limits X automáticos, un sample cuyo Y es no finito tampoco participa
en los extrema de X, conforme al contrato ya cerrado de `line()`.

NaN/Inf sólo detecta una discontinuidad cuando la evaluación en un punto
muestreado retorna efectivamente un valor no finito. No existe análisis
simbólico ni prueba de continuidad. En particular:

- un polo situado exactamente en un sample puede producir Inf y abrir un gap;
- el mismo polo entre dos samples puede unir visualmente dos valores finitos;
- un salto con valores finitos en ambos lados se conecta como cualquier otro
  segmento;
- overflow de la función puede abrir un gap, pero no demuestra la ubicación ni
  naturaleza matemática de una discontinuidad.

Por tanto ni `plotFunction`, ni `line()`, ni un SVG resultante garantizan
continuidad matemática. Un caller que conozca un dominio excluido puede hacer
que su función top-level retorne NaN en samples de ese dominio, pero el
sampler V1 no inventa umbrales ni puntos adicionales. Adaptive sampling y
segmentos declarativos quedan fuera de scope.

## 7. Exceptions y efectos observables

Una call indirecta se considera capaz de unwind. Si `target(x_i)` lanza:

- la exception exacta se propaga sin envolverla en `PlotException`;
- las calls `0..i-1` y sus efectos ya ocurrieron en orden;
- no se almacena un resultado para `i` y no se evalúan índices posteriores;
- el Array temporal y cualquier owner vivo se limpian por las rutas generales;
- no se construye ni publica una `Figure2D`.

Una función con salida u otro efecto observable debe mostrar exactamente N
efectos en el caso normal y el prefijo exacto antes de un throw. O2 no puede
eliminar, duplicar, fusionar ni reordenar llamadas indirectas.

Traps de bounds, overflow de tamaño, allocation failure o corrupción son
fail-fast y no recorren el mecanismo de exceptions. El diseño no intenta
convertirlos en errores recuperables de Plots.

## 8. Arquitectura y ownership

La implementación conceptual completa es una función ordinaria:

```aether
// Esquema normativo; no es implementación de este milestone.
public Figure2D plotFunction(
    Function<(float64), float64> target,
    float64 a,
    float64 b,
    usize sampleCount,
    ref FigureOptions options) {
    // precondiciones de la sección 4
    Array<DataPoint> points = Array<DataPoint>(
        sampleCount, DataPoint(0.0, 0.0));
    // loop exacto de la sección 5
    return line(&points, options);
}
```

Lifecycle normal:

1. `plotFunction` posee el Array temporal;
2. `line()` lo presta y copia N `DataPoint` al Buffer de la figura;
3. la `Figure2D` retornada posee ese Buffer y sus copies de options/texto;
4. al salir `plotFunction`, se destruye el Array temporal;
5. la figura no retiene el descriptor, backing ni referencias del Array.

Lifecycle excepcional:

- un throw durante sampling destruye el Array parcial;
- un throw durante `line()` destruye tanto el Array como los temporales
  parciales de `line()`;
- no se publica una figura parcialmente construida;
- Function no agrega cleanup porque es Copy/no-drop.

No hay estado global, caché, callback retenido ni lifetime que sobreviva a la
call. La `Figure2D` sólo conserva los valores ya evaluados; volver a llamar a
`scene()`, `plots.svg.render()` o `save()` no vuelve a ejecutar la función.

## 9. Coste y optimizaciones diferidas

Sea `C_f` el coste de una evaluación:

| Fase | Tiempo | Storage/allocations relevantes |
|---|---:|---|
| validación sampler | O(1) | ninguna |
| Array temporal y fill | O(N * C_f + N) | un backing de N `DataPoint` |
| `line()` | O(N) | Buffer exacto de N `DataPoint`; copia N elementos |
| salida de `plotFunction` | O(N) total adicional a `f` | Array liberado; Figure retiene sólo Buffer |
| `scene()`/SVG | contrato vigente de Plots | sin cambio |

En el pico durante `line()` coexisten dos payloads de N puntos: Array temporal
y Buffer definitivo. El constructor filled inicializa N slots, el loop
sobrescribe cada slot una vez con su sample y `line()` copia N puntos al
Buffer. Esta duplicación y el fill inicial son el coste deliberado de reutilizar
la API y el ownership cerrados de `line()`.

Una optimización futura podría extraer un helper privado común o una ruta
privada que transfiera un Buffer ya validado. Sólo se justifica con medición y
debe preservar exactamente validación, errores, ownership y geometry de
`line()`. No se agrega ahora un overload público de Buffer, borrowing retenido,
lazy evaluation, streaming a Scene ni callback guardado en Figure.

## 10. Determinismo O0/O2

Para los mismos function target, inputs y estado externo observable, O0 y O2
deben conservar:

- los mismos N, X y orden de llamadas;
- los mismos bits de cada X bajo la secuencia IEEE normativa;
- exactamente un resultado Y capturado por call;
- el mismo prefijo de efectos y la misma exception si hay throw;
- los mismos `DataPoint`, errores de `line()`, Commands y SVG byte-for-byte.

La igualdad final presupone que `target` mismo es determinista. Si lee I/O,
tiempo o estado externo cambiante, Plots garantiza orden y cardinalidad, no
convierte una función impura en pura.

## 11. Qualification propuesta

La implementación futura debe agregar un gate dedicado en
`compiler-next/crates/aether-driver/tests/plots_function_sampling_v1.rs` y un
consumer real del package. Toda fila funcional se ejecuta en O0 y O2.

| Área | Casos mínimos | Evidencia/criterio |
|---|---|---|
| API real | función top-level local e importada | check/build/run; `FunctionRef` e `IndirectCall` |
| polinómica | `x*x-2*x+1`, dominio negativo/positivo | N puntos y extrema esperados |
| trigonométrica | wrapper `sin(x)` | anchors y valores con tolerancia definida |
| trascendental | wrappers `exp`, `log` | finite values y non-finite domain de `log` |
| intervalo | todo negativo y cruzando cero | X exactos, extremos incluidos |
| N mínimo | N=2 | calls exactas en `a`, luego `b` |
| N inválido | N=0 y N=1 | excepción nominal, cero calls/allocation útil |
| N grande | por ejemplo 100001 | cardinalidad, orden, cleanup y coste lineal |
| constante | `f(x)=c` | Y degenerado expandido por `line()` |
| redondeo | magnitudes donde X consecutivos coinciden | no deduplicación; una call por índice |
| NaN/Inf | inicial, interior, final, todos | runs exactos; all non-finite rechaza tras N calls |
| span overflow | `[-maxFloat,+maxFloat]` | `PlotRangeException`, cero calls |
| coordenadas extremas | span finito cerca de límites | endpoints exactos y ningún valor no finito |
| efectos | target imprime cada X | output en orden, una línea por sample |
| throw | target lanza en un X interior | prefijo exacto, propagación nominal, no Figure |
| options inválidas | viewport/width/limits | N calls y luego error vigente de `line()` |
| discontinuidad muestreada | `1/x`, N impar incluyendo cero | gap sólo si retorna Inf/NaN en X=0 |
| discontinuidad no muestreada | `1/x`, grid sin cero; salto finito | puede haber conexión; ninguna garantía falsa |
| ownership | heap counters normal y throws | Array/Buffer/strings balanceados; sin ref escapada |
| Figure | mutar options tras retorno | resultado independiente, igual a `line()` manual |
| SVG | consumer + golden de función | XML válido, golden completo idéntico O0/O2 |
| pureza arquitectónica | inspección source/IR | sin ruta Graphics nueva, Python, FFI, registry o intrinsic |

Además debe construirse manualmente el mismo `Array<DataPoint>` con el grid
normativo y probar equivalencia de Figure/Commands/SVG con `plotFunction`. Esa
es la prueba central de que el entry point sólo compone sampling y `line()`.

Los tests de efectos pueden observar stdout; no requieren globals ni closures.
El caso throwing puede elegir un X conocido del grid y lanzar por comparación,
por lo que tampoco necesita captura de contador.

## 12. Riesgos y mitigaciones

| Riesgo | Consecuencia | Decisión/mitigación |
|---|---|---|
| asumir closures inexistentes | API de ejemplos imposible | sólo funciones top-level capture-free |
| pasar builtins directamente | diagnóstico de function value | wrappers top-level explícitos |
| confundir Inf con detección universal | falsas garantías visuales | contrato limita gaps a samples no finitos |
| invalid options con función impura | efectos antes del error | orden documentado; `line()` sigue autoridad única |
| span extremo | overflow antes de sampling | `PlotRangeException`, cero calls |
| redondeo para N/magnitud grandes | X repetidos/no equidistancia bitwise | grid IEEE explícito; no deduplicar |
| throw durante fill/copia | leak o figura parcial | cleanup general y qualification de heap balance |
| doble payload de puntos | pico de memoria 2N | coste explícito; optimización privada futura medida |
| divergencia O0/O2 | samples/SVG distintos | orden de operaciones y calls normativo, gates dobles |
| duplicar renderer | drift respecto de `line()` | delegación obligatoria y equivalencia manual |

## 13. Decisiones diferidas, no bloqueantes

- overload que construya sus propias default options;
- reversed intervals o un parámetro explícito de traversal;
- sampling adaptativo, tolerancias y límites de recursión;
- domains excluidos declarativos y múltiples segmentos;
- parametric closures/callable objects cuando exista una capability general;
- múltiples series, legends y combinación de funciones;
- sampling float32 o generic numérico;
- streaming o transferencia privada de Buffer para evitar la copia;
- evaluación paralela o vectorizada;
- estrategias de error/recovery ante allocation failure.

Ninguna de estas decisiones es necesaria para implementar el vertical aquí
definido y ninguna autoriza reglas especiales de compiler o runtime para
Plots.

## 14. Fuera de scope

- lambdas, closures, captura, métodos enlazados y builtins como valores;
- adaptive sampling o detección simbólica/heurística de discontinuidades;
- más de una serie o cambios a `PLOTS-2D-LINE-V1`;
- cambios en Graphics Foundation, SVG, compiler o runtime;
- lazy figures que retengan el callback;
- una ruta de renderizado distinta de `line()`;
- modificación de ejemplos personales.

## 15. Criterio de cierre

La API propuesta es implementable con capacidades actuales: function values
top-level, calls indirectas con unwind, Array owner, `DataPoint`, `line()`,
`Figure2D` y `plots.svg` están implementados y calificados. Los gates existentes
revalidados para este diseño pasan 8/8 en `function_values_v1` y 5/5 en
`plots_2d_line_v1`.

No se necesitó un reproducer nuevo: la capability callable multi-package, el
unwind indirecto, el ownership de Array/Buffer y el consumer de Plots ya tienen
reproducers automatizados mínimos en esas suites y en
`examples/numerical_methods`. La implementación futura deberá agregar sólo la
qualification combinada descrita en la sección 11.

No queda una dependencia bloqueante ni una decisión abierta para el primer
vertical.

**PLOTS-FUNCTION-SAMPLING-ARCH-1: CLOSED.**
