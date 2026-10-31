# PLOTS-FUNCTION-SAMPLING-ARCH-1 — reporte de diseño

Estado: **ARQUITECTURA CERRADA; IMPLEMENTACIÓN NO INICIADA**, 2026-10-31.

Documento normativo:
[PLOTS_FUNCTION_SAMPLING_ARCH_1](PLOTS_FUNCTION_SAMPLING_ARCH_1.md).

## Resultado

Se cerró el diseño de una extensión mínima del package `plots` para graficar
funciones Aether sin construir manualmente `Array<DataPoint>`. La superficie
agrega una función libre:

```aether
public Figure2D plotFunction(
    Function<(float64), float64> target,
    float64 a,
    float64 b,
    usize sampleCount,
    ref FigureOptions options);
```

y dos categorías nominales para sus precondiciones:
`InvalidSampleCountException` e `InvalidSampleIntervalException`. La función
retorna una `Figure2D` ordinaria, reutiliza `FigureOptions` y se exporta sin
cambios mediante `plots.svg.render/save`.

No se modificó código productivo, compiler, runtime, Graphics, SVG,
`plots.line()`, sus contratos ni ejemplos personales. No se hizo commit ni
push.

## Capabilities confirmadas

La implementación vigente admite function values estructurales
`Function<(float64), float64>` para funciones Aether top-level no genéricas y
sin captura. Son valores Copy de un word, sin allocation o drop propio, y sus
calls indirectas preservan unwind y cleanup en O0/O2. Funciones importadas
también pueden pasarse como valores.

No se asumieron lambdas o closures. Tampoco pueden pasarse directamente
builtins, métodos enlazados o templates genéricos abiertos; se requiere un
wrapper top-level concreto. El diseño no necesita genéricos ni nuevas reglas
del compilador.

Los gates existentes se revalidaron sin cambios:

| Gate | Resultado |
|---|---|
| `function_values_v1` | PASS — 8/8 |
| `plots_2d_line_v1` | PASS — 5/5 |

Esas suites ya cubren callable imports, `FunctionRef`/`IndirectCall`, unwind,
cleanup, O0/O2, consumer real de Plots, ownership, finite runs, geometría y
goldens SVG. No apareció un bloqueo real y no fue necesario agregar un
reproducer redundante.

## Muestreo cerrado

El contrato exige `N >= 2`, endpoints finitos, `a < b` y span finito. Los
extremos se incluyen exactamente. Los interiores usan, en orden normativo:

```text
t_i = float64(i) / float64(N - 1)
x_i = a + (b - a) * t_i
```

con asignación explícita de `x_0=a` y `x_(N-1)=b`. `target` se evalúa
exactamente una vez por índice, de izquierda a derecha. X repetidos por redondeo
siguen siendo muestras distintas. Un overflow de span o coordenada produce
`PlotRangeException`; allocation-size overflow y OOM conservan los traps
generales.

NaN e infinities devueltos por la función se preservan en el Array temporal y
`line()` los interpreta con su política vigente de finite runs. Sólo abren un
gap cuando ocurren en un sample. El diseño declara expresamente que un muestreo
uniforme finito no detecta todas las discontinuidades: un polo entre samples o
un salto con valores finitos puede quedar conectado visualmente. No se agregó
adaptive sampling.

## Arquitectura y ownership

La implementación futura será una composición ordinaria:

1. validar count e intervalo;
2. asignar un `Array<DataPoint>` exacto;
3. calcular X, llamar una vez a la función y guardar Y por sample;
4. llamar `plots.line(&points, options)`;
5. liberar el Array al retornar o hacer unwind.

`line()` copia los puntos a su Buffer owning. El constructor filled inicializa
el Array antes de que el loop sobrescriba cada slot. La figura no retiene el
callback, el Array, references ni estado del caller. Un throw de la función se
propaga sin reclasificar y limpia el Array parcial; no se publica una figura.
Options inválidas se detectan al delegar, después de N evaluaciones, para no duplicar
la validación privada de `line()`.

La estrategia cuesta O(N) adicional a las N evaluaciones y mantiene dos
payloads de N puntos durante la copia de `line()`. Esa duplicación se acepta en
V1 para conservar contratos y una sola ruta geométrica. Un helper privado con
transferencia de Buffer queda como optimización futura condicionada a medición,
sin cambio de API.

## Qualification diseñada

La matriz normativa cubre polinomios, wrappers trigonométricos y
trascendentales, intervalos negativos y cruzando cero, N mínimo/inválido/grande,
función constante, redondeo con X repetidos, NaN/Inf, all-nonfinite, overflow,
efectos observables, throw intermedio, options inválidas, cleanup, equivalencia
con un Array manual, O0/O2, consumer real y golden SVG.

Dos casos separados prueban el límite de discontinuidades: un polo exactamente
muestreado puede abrir un gap, mientras un polo no muestreado o un salto finito
no recibe garantía de separación visual.

## Riesgos y decisiones diferidas

Los riesgos principales son redondeo de coordenadas, efectos anteriores a un
error tardío de options, cleanup durante unwind, pico de memoria 2N y falsas
inferencias de continuidad. Todos tienen contrato y qualification explícitos.

Quedan diferidos sin bloquear: closures, reversed intervals, domains excluidos,
adaptive/parallel sampling, múltiples series, float32/generics y eliminación
privada de la copia temporal.

La API propuesta es implementable enteramente con las capabilities actuales y
sus dependencias están cerradas.

**Estado final: PLOTS-FUNCTION-SAMPLING-ARCH-1 CLOSED.**
