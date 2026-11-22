# Aether — Scientific & Plots Ergonomics Audit V1

Fecha: 2026-11-20.

Estado: **auditoría terminada; no se inició implementación**.

## 1. Alcance y preflight

La auditoría se realizó sobre `main` en `a0c2a9de` (`feat(plots): support
multiple line and scatter series`). El worktree estaba limpio al comenzar. No
se modificaron Plots, Graphics, álgebra lineal, ejemplos ni tests; tampoco se
ejecutó el workspace completo. Se inspeccionaron únicamente fuentes, tests,
goldens y reportes existentes.

La evidencia principal fue:

- `plots/src/lib.ae` y `plots/src/svg.ae`;
- `graphics/src/svg.ae`;
- `examples/scientific-curve-fitting/src/main.ae`, su README y su reporte;
- las entradas públicas `leastSquares` y `dot` de `linearAlgebra/src/lib.ae`;
- los consumers y goldens de `plots/tests/`;
- las suites `plots_2d_line_v1`, `plots_function_sampling_v1`,
  `plots_invocable_integration_v1` y `plots_multiseries_v1`;
- los contratos `FORMAT-V1`, Graphics SVG y los reportes de Plots.

`PLOTS-MULTISERIES-V1` está CLOSED. Esta auditoría no reabre ese alcance: evalúa
la experiencia de uso que queda encima de la implementación cerrada.

## 2. Evaluación del ejemplo científico

Conviene separar el flujo científico/render del código que convierte al ejemplo
en una prueba ejecutable. Las comprobaciones exhaustivas de observaciones,
residuos, coeficientes y SSE son evidencia valiosa, pero no son boilerplate que
un usuario de las APIs deba escribir normalmente.

### 2.1 Matriz y vector de observaciones

El literal de matriz es compacto y expresa bien la columna de intercepto. El
tipo `Vector<float64,Column>` hace explícita la orientación del RHS, lo que
evita ambigüedad científica. El coste visible es el índice base uno de Vector,
distinto del índice base cero de Array; esto reaparece cuando se trasladan datos
a `Array<DataPoint>` y aumenta el riesgo de off-by-one.

No hay conversión automática entre una matriz de diseño, un Vector y puntos de
Plots. Esa separación evita acoplar Plots a `linearAlgebra`, pero obliga al
ejemplo a repetir después las cinco observaciones. Es un problema ergonómico,
no un bug ni una deficiencia de la sintaxis de literales.

### 2.2 Mínimos cuadrados

El ejemplo usa:

```aether
la.SVD<float64> factor = la.svd(design);
Vector<float64,Column> coefficients = la.leastSquares(factor, observed);
```

Es correcto y hace visible la factorización. Sin embargo, el factor no se
reutiliza. La API pública ya ofrece
`la.leastSquares(design, observed)`, que hace la misma factorización SVD
internamente. Para un caso introductorio, una sola call elimina del código de
usuario un owner/binding y una decisión incidental sin perder estabilidad
numérica. Mantener la forma actual sólo aporta valor si el objetivo documental
es enseñar/reutilizar `SVD` o consultar rango/valores singulares.

### 2.3 Coeficientes, predicción y SSE

Extraer `coefficients[1]` y `[2]` es directo, aunque depende de conocer la base
uno. `design * coefficients` y `observed - predicted` son expresivos y no
requieren conversiones.

El loop manual del SSE es repetición evitable. La API pública ya admite dos
`Vector<T,Column>` en `la.dot`, de modo que el cálculo de usuario puede ser:

```aether
float64 sse = la.dot(residuals, residuals);
```

No hace falta una nueva API de norma para este caso. Los loops que verifican
cada residual pertenecen a la qualification del ejemplo, no al flujo normal.

### 2.4 Closure capturante

La captura explícita:

```aether
var fittedLine = (float64 x) capture(copy intercept, copy slope) =>
    intercept + slope * x;
```

es más verbosa que una captura implícita, pero hace visible ownership y no debe
considerarse un defecto por diferir de otros lenguajes. Es una Closure owner
prestada a `addFunction`; el callback se evalúa eagerly, no se guarda, no se
consume y sigue siendo invocable después. Para dos escalares Copy, el coste y
el riesgo son bajos.

### 2.5 Figura, series y estilos

La secuencia `defaultOptions` → mutación de campos → `figure(&options)` es
predecible. Los límites explícitos `[0,4]` y `[0,9]` evitan que pequeñas
desviaciones del ajuste SVD controlen el encuadre, pero también evidencian que
Auto usa extremos binarios exactos, no límites de presentación “nice”.

Agregar la curva y el scatter produce dos fricciones distintas:

- `addFunction` recibe seis argumentos y un `LineStyle` completo;
- las observaciones se vuelven a escribir como cinco `DataPoint`, aunque ya
  existen en `design`/`observed`.

La repetición de datos es real, pero una entrada Plots específica para Vector
introduciría dependencia de `linearAlgebra`. Una alternativa genérica X/Y
también tendría que resolver longitudes, índices, vistas y ownership. No es una
mejora de bajo coste para este milestone.

Los colores requieren construir `graphics.Color` con cuatro conversiones
`uint8`. Es explícito y seguro, pero ruidoso. Además existe
`defaultScatterStyle()` y no existe `defaultLineStyle()`; el default de línea
está incrustado en `defaultOptions().line`. Esta asimetría es verificable y
fácil de corregir, aunque su impacto es menor que el de las etiquetas.

### 2.6 Render y exportación

`svg.save(&figure, &outputPath)` es corto y separa con claridad el backend. La
referencia compartida al path sigue el contrato de `graphics.svg.save` y no
sugiere que Plots consuma ni modifique el texto.

La figura copia las series y los textos de opciones. El usuario puede mutar los
Arrays y `FigureOptions` originales sin alterar la figura. A cambio,
`plotFunction`/`addFunction` materializan un Array temporal y luego copian los
`DataPoint` al Buffer propiedad de la figura. Es un coste O(N) y un owner
temporal comprobado por las suites; para 33 muestras es despreciable y no es un
problema ergonómico visible.

## 3. Auditoría de la API pública de Plots

| API | Observación |
| --- | --- |
| `figure` | Constructor top-level coherente; permite figura vacía sólo si al renderizar cada eje puede resolverse. |
| `line` | Atajo legacy de construcción + primera línea. Usa `FigureOptions.line`. |
| `plotFunction` | Atajo de sampling + construcción. Comparte opciones y comportamiento con `line`. |
| `Figure2D.addLine` | Mutador natural para datos ya materializados; copia el Array. |
| `Figure2D.addScatter` | Simétrico a `addLine`, con estilo independiente. |
| `plots.addFunction` | Top-level porque requiere `C: Invocable`; Aether no admite generic methods. No es evidencia suficiente para pedir un cambio de compiler. |
| `FigureOptions` | Mezcla configuración de figura/ejes con el estilo de la línea legacy. Ese `line` no actúa como default de las series agregadas a `figure`. |
| `LineStyle` / `ScatterStyle` | Pequeños y claros; defaults públicos asimétricos. |
| `plots.svg.render/save` | Adapter mínimo y consistente sobre el único pipeline Graphics/SVG. |

La diferencia método/función tiene una explicación concreta:

- `figure`, `line` y `plotFunction` construyen y por eso son top-level;
- `addLine` y `addScatter` mutan una figura y son métodos;
- `addFunction` también muta, pero su binder genérico no puede declararse como
  método con las capacidades actuales.

Hay una consecuencia ergonómica: `figure.addScatter(...)` muestra la mutación,
mientras `p.addFunction(figure, ...)` pasa un class handle por valor. En Aether
eso crea un alias ARC y muta la misma identidad; no consume la figura, pero el
call site no lo hace obvio. Cambiarlo a `ref mut Figure2D` haría la mutación más
visible, pero rompería source compatibility y no elimina la limitación de
generic methods. No se recomienda como tarea inmediata.

También es confuso que `FigureOptions.line` configure `line` y `plotFunction`,
pero sea ignorado por `figure` + `addLine`/`addFunction`, donde el estilo vuelve
a ser obligatorio. La mejora compatible mínima es publicar
`defaultLineStyle()` y hacer que `defaultOptions()` lo reutilice. No conviene
agregar overloads de métodos: el lenguaje tampoco admite method overloads ni
default parameters en métodos.

## 4. Auditoría del formato numérico

### 4.1 Origen y selección de ticks

Cada eje usa exactamente cinco ticks, incluidos los endpoints. No existe un
locator de ticks “nice”. Para índice `i` entre 0 y 4:

```aether
minimum + (maximum - minimum) * float64(i) / 4.0
```

La posición gráfica se calcula por separado con la fracción `i / 4`. En modo
Auto, `minimum` y `maximum` son los extremos finitos exactos de todas las
series. En modo Explicit son los valores provistos, salvo la expansión de un
rango degenerado.

Representaciones como `1.0000000000000002`, `4.999999999999999` o
`6.999999999999998` nacen de operar en binary64 con extremos ya redondeados o
con una resta/multiplicación no representable exactamente. No indican pérdida
adicional de datos en SVG.

`tickValue` ya canonicaliza cualquier resultado que compare igual a cero a
`+0.0`, evitando `-0` en etiquetas.

### 4.2 Conversión a texto

`Figure2D.scene()` llama directamente a `str(tickValue(...))`. `FORMAT-V1`
define `str(float64)` como decimal shortest que round-trips al mismo binary64,
con fixed para exponente ajustado `[-6,21)` y scientific fuera, además de
`0`/`-0`, `Inf`, `-Inf` y `NaN`. Su implementación usa un motor shortest
locale-independent y es determinista O0/O2. Por tanto, `str` no está fallando:
publica precisamente el valor binario que recibe.

No existe hoy una API implementada de fixed/significant formatting. La
arquitectura de FORMAT ya reservó para un vertical posterior
`std.Format.fixed` y `std.Format.scientific`, pero FORMAT-V1 las excluye
explícitamente.

### 4.3 Rutas que comparten —y no comparten— formato

- **Etiquetas de ticks:** Plots crea un string con `str` y lo guarda como texto
  en la Scene.
- **Título y nombres de ejes:** son strings del usuario; no pasan por conversión
  numérica.
- **Coordenadas, transforms y tamaños SVG:** `graphics.svg` serializa cada
  `float64` mediante su propio `appendNumber`, que también usa `str` y
  canonicaliza cero.
- **Datos científicos:** permanecen como `float64`; Plots transforma sus
  coordenadas y Graphics conserva floats en la Scene. Sólo el serializer SVG
  los convierte al final.

Comparten el conversor canónico, pero no la misma call ni el mismo propósito.
Aplicar formato únicamente antes de `builder.drawText` cambia sólo el payload
de diez `DrawText`; las posiciones de ticks, transformaciones, polylines,
markers y atributos SVG pueden conservar toda su precisión actual.

### 4.4 Casos límite que debe cerrar cualquier solución

- enteros deben omitir `.0` y cero debe ser `0`, nunca `-0`;
- negativos deben redondear simétricamente;
- cinco labels deben permanecer distintos y ordenados cuando los ticks lo son;
- magnitudes muy grandes/pequeñas necesitan scientific para evitar strings
  inmanejables;
- límites cercanos no pueden colapsar a labels duplicados;
- los ejes nunca producen ticks no finitos válidos: límites no finitos y spans
  no finitos ya lanzan. Un helper interno debe igualmente fallar cerrado o
  conservar los spellings canónicos si recibe `NaN`/`Inf`;
- el resultado y sus bytes deben ser idénticos en O0/O2;
- los goldens cambiarán sólo donde cambie texto y deben revisarse como cambios
  intencionales, no regenerarse a ciegas.

## 5. Alternativas de formato

### A. Decimal fijo configurable

**Ventaja:** comportamiento sencillo y control útil en dominios con unidades
conocidas. **Problemas:** un único número de decimales no funciona bien para
todos los ejes; puede producir duplicados o ceros inútiles. La API robusta de
rounding ties-to-even todavía no está implementada. Es adecuada como opción
explícita futura, no como default automático.

### B. Significativo/adaptativo

**Ventaja:** cubre mejor rangos de magnitudes y notación científica.
**Problemas:** una cantidad fija de dígitos significativos sigue siendo una
policy arbitraria y puede ocultar diferencias entre ticks próximos. Requiere
definir rounding, trimming, transición a scientific y unicidad.

### C. Automático basado en el espaciado de ticks — recomendado

Plots conoce simultáneamente límites, cinco valores y spacing. Puede elegir la
representación decimal menos ruidosa que preserve valores distintos, orden y
una precisión coherente con el spacing, aumentando precisión si dos labels
colisionan y usando scientific cuando fixed deja de ser legible.

La policy no debe ser “redondear siempre a N decimales”. Debe especificar el
criterio de selección, validar el conjunto completo de cinco labels y conservar
el string canónico si no existe una simplificación segura. Puede implementarse
privadamente en Plots a partir del decimal canónico de `str`, inspección de
bytes con `std.Text` y construcción con `std.Text.fromUtf8`, sin alterar floats
ni agregar sintaxis al lenguaje. Esto tiene más código que llamar a una futura
`std.Format`, pero mantiene acotada la primera corrección.

### D. Formatter provisto por el usuario

Una Closure `(float64) -> string` sería flexible, pero Auto sólo conoce los
límites finales después de agregar series. La figura tendría que almacenar el
callback hasta `scene()`, con ownership y tipo genérico no representables como
un field simple de `Figure2D`; además los generic methods no existen. Un enum de
policies (`Auto`, `Fixed(n)`, `Scientific(n)`) sí es viable más adelante, pero
no es un formatter arbitrario. No se recomienda D en V1 ni justifica cambiar el
compiler.

## 6. Hallazgos clasificados

| Hallazgo | Clase | Evidencia / impacto | Alternativa | Complejidad | Riesgo | Dependencia / compiler |
| --- | --- | --- | --- | --- | --- | --- |
| Ruido binary64 en tick labels | Bug de presentación/ergonomía de Plots; no bug de `str` | `scene()` aplica `str` directamente al tick interpolado | Auto por spacing, sólo en labels | Media | Medio: rounding, duplicados, goldens | Plots-only posible; sin cambio de compiler |
| Cinco ticks equidistantes, no “nice” | Limitación funcional V1 | Contrato y loop fijo `i/4` | Locator futuro separado | Alta | Alto: layout/compatibilidad | Plots-only; fuera del arreglo mínimo |
| `FigureOptions.line` no es default multiseries | Problema de ergonomía y naming | `figure()` no conserva estilo; cada add exige uno | `defaultLineStyle()` y documentación | Baja | Bajo | Sólo Plots |
| `defaultScatterStyle` sin equivalente de línea | Inconsistencia verificable | Default de línea está embebido en `defaultOptions` | Publicar helper simétrico | Baja | Bajo | Sólo Plots |
| `addFunction` top-level frente a métodos add | Limitación de lenguaje con coste ergonómico | Generic methods no admitidos | Mantener y documentar | Ninguna | Ninguno | No pedir compiler |
| Handle por valor en `addFunction` oculta mutación y crea alias ARC | Ergonomía/ownership | M2 califica el alias temporal balanceado | `ref mut` sólo en una revisión incompatible | Baja técnica, alta migración | Medio | No compiler; rompe source |
| Observaciones duplicadas como `DataPoint` | Ergonomía/interoperabilidad | Vector científico y Array de Plots no comparten carrier | Helper X/Y futuro o loop local | Media/alta | Medio por shapes/coupling | Evitar dependencia Plots→LA |
| SVD explícita no reutilizada | Repetición del ejemplo, no bug de API | Existe overload matrix+vector | Usar `leastSquares(design, observed)` | Baja | Bajo | Ya disponible |
| SSE manual | Repetición del ejemplo, no bug de API | Existe `dot(Vector,Vector)` | `la.dot(residuals,residuals)` | Baja | Bajo | Ya disponible |
| RGBA y estilos verbosos | Preferencia estética con efecto real menor | Constructores completos en cada serie | Helpers de defaults/colores por separado | Baja/media | Bajo | Plots/Graphics, no compiler |

## 7. Priorización

Se limitan las prioridades a tres:

| Mejora | Impacto | Esfuerzo | Riesgo | Prioridad |
| --- | --- | --- | --- | --- |
| Formato automático contextual de tick labels | Alto: corrige output visible de toda figura científica | Medio | Medio | **P0** |
| Simplificar el ejemplo con overload directo de `leastSquares` y `dot` | Medio: reduce boilerplate científico sin API nueva | Bajo | Bajo | **P1** |
| Agregar `defaultLineStyle()` y aclarar `FigureOptions.line` | Medio-bajo: simetría y descubribilidad | Bajo | Bajo | **P2** |

No se priorizan nice ticks, integración directa Vector→Plots, formatter Closure
ni cambios de compiler. Todos expanden el problema más que la evidencia actual.

## 8. Siguiente tarea recomendada

Se recomienda una sola tarea: **PLOTS-TICK-LABEL-FORMAT-V1**.

### Objetivo exacto

Eliminar artefactos de representación binary64 en etiquetas de ejes mediante
formato automático dependiente del spacing, sin cambiar límites, posiciones,
datos, precisión geométrica ni serialización numérica general de SVG.

### Alcance mínimo

- tocar sólo la generación de `xText`/`yText` en Plots y tests focales;
- conservar cinco ticks y el `tickValue` actual;
- no agregar nice tick locator, grid, locale, unidades ni formatter callback;
- no cambiar Graphics, SVG, Core, compiler ni el formato canónico `str`;
- no agregar todavía opciones públicas si una policy interna estable resuelve
  el caso observado.

### Comportamiento deseado

Para cada eje, el formatter recibe los cinco valores y su spacing. Debe:

1. canonicalizar cero positivo;
2. elegir fixed o scientific según la escala del conjunto;
3. usar la menor precisión aceptada por una regla documentada ligada al
   spacing, no una constante estética sin justificación;
4. comprobar los cinco resultados como conjunto y aumentar precisión ante una
   colisión;
5. preservar orden y signo;
6. volver al spelling canónico si no puede simplificar con seguridad.

Casos como los del problema deben verse como `1`, `5` y `7`. Los labels ya
razonables de enteros, cuartos, medios y endpoints como π no deben degradarse.
Los floats usados en transforms y atributos SVG deben seguir usando `str`.

### Compatibilidad

La API pública permanece igual. Cambia intencionalmente el texto SVG de algunos
ticks y, por tanto, los goldens/hashes afectados. La geometría, cardinalidad y
orden de Commands deben permanecer iguales. O0 y O2 deben seguir generando
bytes idénticos.

### Tests necesarios

- reproducción exacta de `1.0000000000000002`, `4.999999999999999` y
  `6.999999999999998` como inputs/resultados de tick;
- enteros, negativos, cero y `-0`;
- cuartos/medios y un intervalo con endpoints no enteros;
- límites muy pequeños, subnormales representables y magnitudes grandes;
- límites muy cercanos que fuerzan más precisión y verifican no duplicación;
- transición fixed/scientific;
- rechazo previo de límites no finitos y fallback interno defensivo;
- Scene: sólo cambia contenido de `DrawText`, no posiciones ni Commands;
- SVG/goldens focales y equivalencia byte a byte O0/O2.

### Riesgos técnicos

El riesgo central es inventar un formatter decimal incompleto o esconder
diferencias reales. Debe cerrarse primero la regla matemática de selección y
después el código. Si la implementación Plots-only termina duplicando una
cantidad desproporcionada del rounding ya diseñado para `std.Format`, se debe
detener y reevaluar usar el vertical FORMAT-V2 como dependencia; no improvisar
rounding por casts y `+0.5`.

### Criterios de cierre

- los tres artefactos motivadores desaparecen bajo una policy escrita y
  reproducible;
- ningún eje finito produce labels duplicados;
- cero se presenta sin signo negativo;
- los casos grandes/pequeños tienen notación acotada y determinista;
- no cambian floats internos, transforms ni datos SVG;
- tests focales pasan en O0/O2 y goldens cambiados tienen revisión explícita;
- no hay cambios de compiler ni expansión a nice ticks;
- el reporte de cierre documenta qué labels cambiaron y por qué.

## 9. Conclusión

El flujo científico principal ya es sólido: literales matemáticos expresivos,
SVD/least-squares estable, operaciones vectorizadas, Closure borrowed y una
figura multiseries con ownership calificado. La fricción de mayor impacto no
está en el solver ni en SVG, sino en presentar como labels de usuario el
decimal shortest de un tick binary64 calculado. Resolver ese borde sólo en
Plots ofrece la mejor relación impacto/coste. Las demás mejoras prioritarias
ya pueden hacerse con APIs existentes o con un helper pequeño y no justifican
nuevas capacidades del lenguaje.
