# PLOTS-ARCH-1 — reporte de diseño

Estado: **COMPLETADO COMO DISEÑO; NO IMPLEMENTADO**, 2026-10-30.

Documento normativo: [PLOTS-ARCH-1](PLOTS_ARCH_1.md).

## Resultado

Se diseñó el primer vertical nativo `PLOTS-2D-LINE-V1` como una OAL ordinaria
sin estado global. La API recibe un `Array<DataPoint>` prestado, publica una
`Figure2D` explícita e inmutable y construye una `graphics.Scene` nueva al
solicitarla. El adapter `plots.svg` delega `render` y `save` al backend ya
cerrado `graphics.svg`.

No se modificó código productivo, compiler, runtime, Core, std, Graphics, SVG,
tests, examples ni archivos del usuario. No se hizo commit ni push.

## Autoridades verificadas

La propuesta fue contrastada con las APIs reales:

- `SceneBuilder` acepta viewport finito, clip rectangular en scene
  coordinates, text, lines, points y polylines de al menos dos points;
- la construcción incremental disponible es
  `beginPolyline/addPolylinePoint/endPolyline`;
- `finish` publica una Scene inmutable y sella el builder;
- Graphics rechaza toda geometry no finita, por lo que Plots segmenta finite
  runs antes de invocarlo;
- `graphics.svg` expone únicamente `render(ref Scene)` y
  `save(ref Scene, ref string)`, preservando painter order y clips;
- shared `ref` de class handles, fields privados `Buffer<Copy aggregate>`,
  strings owning, exceptions y packages OAL son capabilities vigentes.

El builtin legacy y `PlotBackend` Python se inspeccionaron para identificar la
superficie histórica. No se copiaron su current figure, `hold`, registry,
Matplotlib/NumPy, coerciones dinámicas, sampling ni export PNG.

## Decisiones principales

- `DataPoint(x,y)` es la representación única de la primera serie; evita dos
  owners paralelos y distingue data coordinates de `graphics.Point`.
- Figure copia los samples a `Buffer<DataPoint>` y no retiene borrows.
- Cero samples es error; un singleton se muestra con `DrawPoint`; múltiples
  points forman finite runs incrementales y gaps no finitos no se conectan.
- Auto limits usan sólo pares finitos. Explicit limits permiten clipping. Todo
  intervalo degenerado se expande con una regla determinista del 5%/1 unit.
- La transformación se materializa point por point para mantener line width en
  scene units; Y se invierte explícitamente.
- El plot area usa margins fijos. Hay cinco ticks por eje, formatting mediante
  `str`, frame, tick labels, title y axis labels mínimos.
- Los datos se dibujan dentro de un push/clip/pop; frame y texto se dibujan
  después, preservando painter order.
- SVG se obtiene exclusivamente mediante `graphics.svg`; Plots no contiene
  serializer, XML ni clip IDs.

## Ownership y errores

`Figure2D` es un class handle normal, lógicamente inmutable. Sus aliases
comparten identidad ARC. Inputs y options se prestan sólo durante `line`; la
Scene y el string SVG son owners independientes. Cada export reconstruye la
Scene y la libera después del traversal.

Se separan errores de input vacío, ausencia de datos finitos, figura inválida,
limits inválidos y rango no representable. Exceptions de Graphics/SVG se
propagan con su tipo original; no se convierten en un error Plots genérico.

## Qualification cerrada para el V1

La matriz exige check/build/run nativo O0/O2, inspección geométrica de Commands,
goldens SVG completos parseados como XML, equivalencia byte-for-byte, pruebas
de clipping/runs/degeneración/non-finite, mutation-after-call, aliases y heap
balance. Los gates de source e IR deben demostrar ausencia de Python,
Matplotlib, NumPy, FFI, builtin Plots, registries e intrinsics.

## Limitaciones registradas

No hay bloqueo de compiler para una figura de una serie. Sí quedan limitaciones
concretas para extensiones:

- Figure no puede almacenar/cachear un class handle `graphics.Scene` dentro
  de un retained class graph con el perfil actual;
- `Buffer<T>` no puede contener una futura `LineSeries` owning con buffers o
  strings;
- no hay interior borrow público de un Buffer guardado en una class;
- user functions no ofrecen named/default arguments generales, por lo que la
  API usa `FigureOptions`;
- Graphics no mide text, de modo que V1 usa layout fijo y no promete resolver
  overlap de labels arbitrarias.

Ninguna se resuelve introduciendo una capability automáticamente. Multi-series,
retained caching o layout medido deberán justificar un diseño posterior.

## Alcance preservado

Scatter, histogram, bar, legends, sampling de funciones, grids, nice ticks,
log axes, subplots, interactividad, raster/PNG, themes y mutation incremental
quedan fuera. El siguiente paso autorizado por este diseño es implementar y
calificar únicamente `PLOTS-2D-LINE-V1` y su adapter SVG delgado.

**Estado final: READY FOR IMPLEMENTATION.**
