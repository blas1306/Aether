# NEXT-VERTICAL-25 — VectorView/VectorViewMut with orientation, stride and zero-copy borrowed transpose

Implementado en `compiler-next`, Linux x86_64, 2026-09-08. Las vistas conservan
identidad matemática 1D, orientación estática, dimensión/stride runtime y
procedencia al propietario. No se implementan proyecciones Matrix row/column.

1. **Modelo Vector inicial.** V21 aporta `Vector<T,Row/Column>` propietario,
   contiguo fijo, no-Copy, Storable, con descriptor `{ptr,dimension}` e índices
   desde uno. V22 `transpose(Vector)` consume y transfiere esos mismos bits.
   V23 agrega Matrix y V24 vistas Matrix con cinco campos, recetas verificadas
   y préstamos léxicos. V25 conserva esos contratos y agrega el descriptor 1D
   prestado sin reutilizar la identidad de raw View.

2. **Archivos cambiados.** Rutas relativas a la raíz:

   | Archivo | Responsabilidad |
   |---|---|
   | `compiler-next/crates/aether-frontend/src/types.rs` | VectorView, interning, propiedades, orientación, sustitución, recetas y consulta común de efectos |
   | `compiler-next/crates/aether-frontend/src/hir.rs` | sintaxis contextual, intrínsecos, layout, genéricos, procedencia, dimensión y verificación HIR |
   | `compiler-next/crates/aether-frontend/src/lib.rs` | exportaciones del descriptor y selectores |
   | `compiler-next/crates/aether-middle/src/mir.rs` | operación propia, lowering, consultas, walkers y verificación |
   | `compiler-next/crates/aether-middle/src/ssa.rs` | preservación/renombrado, walkers y verificación independiente |
   | `compiler-next/crates/aether-backend-llvm/src/lib.rs` | mangling, descriptor de tres palabras, query tipada y GEP con stride |
   | `compiler-next/crates/aether-driver/tests/vertical.rs` | pruebas nativas, diagnósticos, corrupciones e instrumentación |
   | `compiler-next/tests/programs/v25_vector_view_*.ae` | catorce fixtures enumerados abajo |
   | `compiler-next/tests/modules/v25_vector_views/{main,helper}.ae` | helpers genéricos importados |
   | `compiler-next/tests/modules/v1-contract.tsv` | registro del módulo |
   | `compiler-next/tests/measure-v25.py` | mediciones reproducibles con baseline V24 |
   | `compiler-next/tests/timings/v25-debug.json` | snapshots por fase |
   | `compiler-next/README.md` | sintaxis y contrato actual |
   | `docs/architecture/AETHER_V1_LANGUAGE_CHARTER.md` | alcance implementado |
   | `docs/architecture/AETHER_V1_SEMANTIC_CONTRACT.md` | contrato normativo V25 |
   | `docs/architecture/AETHER_COMPILER_ARCHITECTURE.md` | confirmación 42 y hallazgos |
   | `docs/architecture/NEXT_VERTICAL_25_REPORT.md` | este informe |

3. **Sintaxis fuente.** `VectorView<int,Row> r=vector_view(v);`,
   `VectorViewMut<int,Column> c=transpose_view_mut(v);`, `r[i]`, `c[i]=x`,
   `dimension(r)`, `&r[i]` y `&mut c[i]`. Orientación obligatoria Row o Column;
   no auto-deref ni préstamo de temporales. El parser de tipos/aplicaciones
   existente basta; no se agrega sintaxis de rangos, métodos ni punteros.

4. **Identidad.** `TypeData::VectorView {element,orientation,mutable}` es
   canónico: los tres componentes participan en TypeId, sustitución, inferencia
   y mangling `QVRow/QVColumn` más capacidad/elemento. Row/Column no son tipos
   de uso general ni campos runtime. Dimensión y stride no entran en TypeId.
   No hay conversión implícita entre orientaciones, capacidades o raw View.

5. **Propiedades.** Ambas capacidades son Copy y Relocatable, no-Storable y
   sin drop, aun con T propietario. Write capability no significa unicidad;
   no se genera noalias. La vista no exige Copy/Relocatable/Storable adicional
   a T para existir; cada operación exige las propiedades que realmente usa.

6. **Descriptor.** `{ptr,dimension,stride}`; dimensión y stride son usize,
   stride en elementos. Layout derivado del target: tres palabras, tamaño 24
   y alineación 8 en Linux x86_64. Sin owner, procedencia, orientación, capacity,
   refcount ni drop flag runtime dentro de la vista.

7. **Vista normal compartida.** `vector_view(owner)` toma el Place existente,
   conserva elemento/orientación y selecciona ptr/dimension del dueño con
   stride=1. Sobre otra vista conserva también su stride. No mueve el owner,
   asigna almacenamiento ni carga/copia componentes.

8. **Vista normal mutable.** `vector_view_mut(owner)` usa la misma receta y
   exige un camino escribible. Column se conserva tanto como Row. Rechaza
   refs compartidas a Vector y vistas compartidas; un ref mut explícitamente
   dereferenciado sí permite crearla.

9. **Transposición prestada.** `transpose_view` y `transpose_view_mut` aceptan
   Vector o VectorView según capacidad. Row↔Column cambia sólo el tipo de
   resultado. Ptr, dimensión, stride y raíz prestada se preservan. No hay
   conjugación ni transformación numérica.

10. **Doble transposición.** Dos transpuestas restauran el TypeId original
    para la misma capacidad y exactamente los mismos tres campos. El fixture
    `double` prueba shared/mut, writes observables por aliases y consultas.
    La instrumentación verifica dimensión y stride en cada paso, no sólo valores.

11. **Dimensión.** `VectorDimension` acepta owner y ambas vistas, retorna
    usize y conserva el Place tipado. LLVM extrae campo 1 usando el tipo real
    del descriptor; no presupone las dos palabras del owner.

12. **Índices desde uno.** `TypeArena::index_semantics` selecciona OneBased.
    Se exige exactamente un índice usize. Hay guards de límite inferior y
    superior antes de calcular direcciones. Constantes con dimensión léxica
    conocida se diagnostican; el resto usa trap runtime. Copias/transpuestas
    directas conservan hechos conocidos de dimensión.

13. **Offset con stride.** Tras ambos guards, LLVM calcula
    `(i-1)*stride`, extrae ptr y emite GEP del elemento. No usa inbounds ni
    asume stride 1. La prueba interna ejecuta strides 2, 3 y 5, incluyendo
    lectura, escritura, ref/ref-mut y transposición doble en un helper fuente.

14. **Seguridad del offset.** La asignación Vector ya prueba bytes/dimensión
    válidos; stride 1 mapea cada índice lógico al backing original. Copiar y
    transponer preservan ese conjunto de offsets. Las recetas cerradas verifican
    esta inducción en cada capa. No se admite descriptor arbitrario en fuente.
    El harness LLVM de stride no unitario usa backing suficiente y descriptores
    de prueba válidos; no abre una operación fuente. En vacío se atrapa antes
    de la resta/multiplicación.

15. **Lectura/escritura.** T Copy se lee por valor desde ambas vistas y se
    reemplaza desde VectorViewMut. VectorView rechaza write y ref-mut incluso
    detrás de referencias/proyecciones. T no-Copy conserva la prohibición de
    extracción y reemplazo parcial: no se introduce clone ni drop oculto.

16. **Elementos propietarios.** `owning` usa `Vector<Buffer<int>,Row>`,
    vista compartida transpuesta y mutable normal. Presta Buffer y modifica
    su elemento Copy mediante referencia sin extraer ownership. Se exigen tres
    alloc/free finales: dos Buffer y el backing Vector.

17. **Procedencia.** Creación/transposición derivan el owner del source Place;
    copiar un local conserva su tabla de procedencia. Cargar un descriptor
    matemático por referencia conserva ahora también su raíz. Los parámetros
    de vista representan una raíz proxy del backing del caller. HIR/MIR/SSA
    conservan Place y cadenas de definición/uso; LLVM no guarda la procedencia.

18. **Liveness del dueño.** Move, consumo y reemplazo se rechazan con aliases
    prestados léxicamente vivos. Incluye vistas normales, transpuestas y copias
    shared/mut. Se revalida el dueño después de índices y durante argumentos
    de llamadas, evitando consumo del owner o contenedor mientras se prepara
    el préstamo. Tras salir del bloque de vistas, `consume(owner)` vuelve a ser
    legal y realiza la limpieza normal.

19. **Copy y aliases.** VectorViewMut sigue la política Copy de ViewMut/V24;
    copias escribibles pueden aliasar entre sí y con vistas compartidas. Todas
    conservan relación al root durante sus scopes. `copy` verifica observación
    compartida/mutable y `refs` incluye copia explícita por `*ref` y transposición
    del descriptor dereferenciado. No se agregan exclusividad ni refcounts.

20. **No escape/Storable.** Se rechaza retorno prestado, almacenamiento en
    struct/enum/Array/List/Matrix/Vector y rebind de locals prestados. No hay
    parámetros de lifetime ni excepción VectorView al modelo previo.

21. **Dueños proyectados/anidados.** `holder.v`, `array[0]`, `list[0]` y
    `*ref`/`*ref mut` funcionan, preservando la raíz contenedora. El fixture
    proyectado combina los tres tipos de contenedor. Se rechaza crecimiento
    List con una vista interior viva y consumo del contenedor desde su propio
    índice. No se usa estabilidad del backing interno para ignorar préstamos
    del descriptor que podría ser relocalizado.

22. **Genéricos.** Se admiten parámetros `VectorView<T,Row>` y
    `VectorViewMut<T,Column>` con T inferido/expreso, también entre módulos.
    Leer/reemplazar T exige T:Copy; consultar dimensión de una vista simbólica
    no requiere Copy. Crear desde `ref Vector<T,Row>` exige T:Storable por
    legalidad del owner. Se prueba T=Buffer<int>. Se conservan rechazo de
    `inspect<VectorView<int,Row>>` y ausencia de orientación genérica O,
    dispatch runtime y traits.

23. **Frontera de efectos mutables.** `has_untracked_mutable_view_effect`
    centraliza la regla para vistas Vector/Matrix. Desenvuelve referencias,
    reconoce capacidad mutable y consulta List transitivo en el elemento.
    Rechaza pasar esos descriptores a helpers, incluso por ref compartida que
    podría copiarlos. Las mutaciones locales con aliases mantienen comprobación
    conservadora. La auditoría añade regresión Matrix para copias mediante Load.

24. **Vacío.** Normal/transpuesto, shared/mut: `{null,0,1}`. Cambia sólo
    orientación cuando corresponde. Cero alloc/free/relocation y dimensión 0.
    Todas las rutas de índice atraparán antes de offset/GEP.

25. **HIR.** `HirExprKind::VectorView {source,mutable,transpose,descriptor}`
    representa explícitamente las cuatro operaciones; el TypeId fuente/resultado
    aporta orientaciones y elemento sin caches redundantes. Receta con selectores
    `Dimension`, `Stride`, `One`; el source Place conserva relación de préstamo.
    No se borra a View ni se construye propietario temporal.

26. **MIR.** Rvalue::VectorView preserva source Place y receta sin alloc/drop
    de vista. Lowering y walkers visitan las proyecciones e índices. Verifica
    tipo/capacidad, giro de orientación, selectores exactos y OneBased.

27. **SSA.** SsaOp::VectorView preserva tipo y metadatos; renombrado conserva
    dependencia de source. Verifica independientemente los mismos contratos,
    incluida mutabilidad desde fuente compartida aun con resultado/receta
    coherentes. La autoridad de lifetime sigue siendo el frontend léxico;
    no se añade análisis global de lifetimes en MIR/SSA.

28. **LLVM.** Transformación limitada a extractvalue/insertvalue del descriptor,
    luego de resolver/cargar el Place fuente. Tres palabras y cero orientación
    runtime. Index helper con ambos bounds, resta, producto stride y GEP.
    Firmas sólo-view no introducen malloc/free. Sin drop/refcount/noalias ni
    funciones runtime de transposición.

29. **Regresión transpose consumidor.** V22 mantiene `VectorTransposeMove`
    independiente y dos palabras del owner. Continúan rechazo de reusar el
    dueño consumido y asignar Row a Column implícitamente. Transpose de una
    vista mediante el intrínseco consumidor sigue siendo inválido.

30. **Regresión MatrixView.** Se conservan descriptor de cinco palabras,
    recetas 2D, swaps de shape/strides y todos los tests V24. Sólo se centraliza
    el chequeo de efectos y se cierra el hueco de procedencia en Load de vistas
    matemáticas. No se enruta MatrixView por VectorView.

31. **Diagnósticos.** E0338: target VectorView inválido o intento de constructor
    de descriptor; E0339: mutable desde vista compartida; E0336: aridad/target
    matemático incorrecto; E0272: writable por ref compartida; E0288: write por
    vista compartida; E0334: aridad de índices; E0296: bounds constantes;
    E0292: owner prestado; E0313: invalidación List/efectos anidados;
    E0276: argumento genérico prestado; E0277: rebind. Orientación usa mismatch
    tipado existente; storage/escape/índice no-usize conservan diagnósticos
    estructurados previos. Corrupciones IR indican contrato de stride/type/capability.

32. **Dumps.** HIR/MIR/SSA/LLVM son idénticos entre dos compilaciones. Se
    comprueban VectorView, dimensión/stride, transpose y OneBased. Identidad
    orientada y capacidad permanecen en el arena/TypeIds; el Place conserva
    ancestry. LLVM muestra tres campos y producto del stride. Marcadores
    VectorViewBegin/End delimitan exclusivamente la transformación para tests.

33. **Pruebas exactas.** `cargo test --workspace --no-fail-fast`: **197 tests, cero fallos**
    (7 backend, 25 frontend, 22 middle, 143 integración). Se conservan los
    186 tests V0..V24 y se añaden once. Pasan clippy con `-D warnings`,
    fmt y git diff --check.

    | Nuevo test | Cobertura |
    |---|---|
    | vertical25_hir_rejects_corrupt_vector_view_contracts | seis corrupciones HIR |
    | vertical25_native_mapping_borrows_and_heap_counts | catorce fixtures y módulo importado |
    | vertical25_identity_and_deterministic_ir | identidad, orientación, propiedades, layout, dumps, bounds/stride |
    | vertical25_each_view_has_zero_heap_relocation_and_pointer_delta | ptr/dimensión/stride y contadores por operación |
    | vertical25_mir_ssa_reject_corrupt_descriptor_contracts | siete corrupciones por capa |
    | vertical25_structured_diagnostics_and_owner_liveness | códigos, índices, move/rebind, storage/escape y propietarios |
    | vertical25_nested_provenance_and_call_effects | roots proyectados, evaluación, efectos List y Load de vistas |
    | vertical25_runtime_bounds_orientations_and_capabilities | 144 ejecuciones con SIGILL exacto |
    | vertical25_nonunit_stride_backend_contract | strides 2/3/5, refs y transposición en helper |
    | vertical25_cross_module_type_capability_rejections | cuatro firmas incompatibles |
    | vertical25_mir_ssa_reject_mutable_from_shared_with_matching_result | fuente shared con resultado mutable y receta coherentes |

    Las 144 ejecuciones son dos orientaciones × vacío/no vacío × tres índices
    inválidos × cuatro creadores, con lectura/ref para shared y lectura/write/
    ref/ref-mut para mutable. Índices: 0, upper+1 y usize::MAX. Con quince
    positivos, catorce instrumentados y tres strides internos son **176 ejecuciones
    nativas dedicadas V25**, además del módulo en el contrato general.

34. **Contadores coste cero.** Cada creación/transposición exige delta
    `(alloc,free,relocation)=(0,0,0)`, ptr idéntico y dimensión/stride conservados
    (stride fuente=1 para owners). Dentro de los marcadores sólo se admiten
    extractvalue/insertvalue: ninguna llamada, load/store de elementos ni drop.
    Conteos finales exactos y relocation total cero:

    | Fixture v25_vector_view_* | Alloc = Free |
    |---|---:|
    | normal, column, mutable, column_mut | 1 cada uno |
    | transpose | 2 |
    | transpose_mut, double | 1 cada uno |
    | empty | 0 |
    | owning | 3 |
    | projected | 5 |
    | refs, copy, scope, generic | 1 cada uno |
    | módulo v25_vector_views | 1 |

35. **Snapshots de compilación.** Metodología V17..V24: binario debug,
    proceso nuevo, un warmup descartado y diez muestras por fixture. Core suma
    ocho fases parse-through-LLVM; excluye startup, discovery, I/O, dumps,
    clang/link y detalles inclusivos duplicados. V24 se compiló antes de editar
    desde `17c23f979f490914f631844b238b96be00326546` y se conservó el binario en
    `/tmp/aether-v24-baseline-bin`. Mediciones sin builds/tests concurrentes.

    | Compilador / fixture | Core media ms | Core mediana ms |
    |---|---:|---:|
    | V24 original / normal MatrixView | 7.896 | 10.157 |
    | V25 / mismo normal MatrixView | 1.809 | 1.209 |
    | V25 / normal VectorView | 0.850 | 0.796 |
    | V25 / mutable VectorView | 1.998 | 0.976 |
    | V25 / transpose VectorView | 0.855 | 0.816 |
    | V25 / owner proyectado | 1.405 | 1.178 |

    Son snapshots descriptivos de compilación, con fixtures de trabajo distinto;
    no miden velocidad runtime ni demuestran una mejora/regresión estadística.
    Datos por fase y versiones en [v25-debug.json](../../compiler-next/tests/timings/v25-debug.json).
    Reproducible con [measure-v25.py](../../compiler-next/tests/measure-v25.py).

36. **Legacy.** `tests/run-differential.sh`: **21 comparaciones, cero fallos**. No se modifican compiler-rs, runtime/CLI
    legacy ni scrap. Los binarios no rastreados preexistentes FaCAether y
    FaCAetherO0 quedan fuera de los cambios de V25.

37. **Deuda aceptada.** Borrow léxico conservador, única inicialización de
    locals prestados, no extracción/reemplazo parcial propietario, ABI bootstrap
    Linux x86_64 y traps sin unwind. No se re-infiere lifetime global en MIR/SSA.
    Call effects de mutable views con List y procedencia anidada conservan
    rechazo; no se expone constructor de stride. Orientación es estática Row/
    Column, sin O paramétrico.

38. **OPEN DECISIONS.** Matrix row/column projection con prueba de offsets y
    procedencia; slices/rangos; strides negativos; lifetimes no léxicos o
    almacenados; ABI pública; layouts alternativos; dimensiones estáticas;
    transpose propietario Matrix; aritmética/BLAS y capacidades numéricas.
    Ninguna queda admitida implícitamente por tener un campo stride.

39. **Problemas arquitectónicos descubiertos.** VectorDimension LLVM usaba
    un descriptor físico fijo de dos palabras: ahora obtiene el tipo del Place.
    Copiar vistas a través de referencias (`Load`) podía perder la raíz usada
    para invalidación de List, a diferencia de Local y de creación explícita.
    La regresión reprodujo aceptación incorrecta; se centraliza conservación de
    raíz/storage borrow para las dos vistas matemáticas. El chequeo de llamadas
    mutable MatrixView era específico de Matrix; pasa a una consulta común.
    Recetas y tipos siguen separados por rango matemático, sin ensamblado libre
    de descriptores ni nuevos estados de ownership.

40. **Recomendación NEXT-VERTICAL-26.** Proyecciones explícitas y comprobadas
    de filas/columnas Matrix hacia VectorView orientada. Definir recetas cerradas
    de ptr/dimensión/stride y proof de bounds del eje fijo, incluyendo MatrixView
    transpuesta, capacidades y root contenedor. Reutilizar el offset con stride
    ya calificado y mantener arithmetic/slicing/lifetimes para verticales propias.
