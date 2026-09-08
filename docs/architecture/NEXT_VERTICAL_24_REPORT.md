# NEXT-VERTICAL-24 — MatrixView/MatrixViewMut with explicit strides

Implementado y calificado en `compiler-next`, Linux x86_64, 2026-09-08.
Las vistas normales y transpuestas son préstamos matemáticos con descriptor
propio; la transposición no consume ni modifica el layout del Matrix propietario.

1. **Modelo inicial.** V23 usa Matrix<T> propietario, no-Copy, con almacenamiento
   fijo contiguo row-major y descriptor `{ptr,rows,columns}` de 24 bytes. La
   construcción comprueba producto de forma y tamaño de asignación. El drop
   destruye elementos en orden inverso por filas y libera una vez. V24 conserva
   ese modelo sin agregar strides al propietario.

2. **Archivos cambiados.** Rutas relativas a la raíz:

   | Archivos | Cambio |
   |---|---|
   | `compiler-next/crates/aether-frontend/src/types.rs` | identidad, propiedades, consultas, sustitución y receta de descriptor |
   | `compiler-next/crates/aether-frontend/src/hir.rs` | resolución, operaciones, procedencia, capacidad proyectada y verificación HIR |
   | `compiler-next/crates/aether-frontend/src/lib.rs` | exportaciones de metadata interna |
   | `compiler-next/crates/aether-middle/src/mir.rs` | operación, lugares 2D y verificación independiente |
   | `compiler-next/crates/aether-middle/src/ssa.rs` | preservación de tipos/recetas, operandos y capacidad |
   | `compiler-next/crates/aether-backend-llvm/src/lib.rs` | descriptor, swaps, offset por strides y mangling |
   | `compiler-next/crates/aether-driver/tests/vertical.rs` | siete pruebas integrales V24 |
   | `compiler-next/tests/programs/v24_matrix_view_*.ae` | doce fixtures nativos detallados abajo |
   | `compiler-next/tests/modules/v24_matrix_views/{main,storage}.ae` | helpers compartidos y mutables importados |
   | `compiler-next/tests/modules/v1-contract.tsv` | registro del módulo |
   | `compiler-next/tests/measure-v24.py`, `compiler-next/tests/timings/v24-debug.json` | metodología y snapshots |
   | `compiler-next/README.md` | contrato y ejemplos actuales |
   | `docs/architecture/AETHER_V1_LANGUAGE_CHARTER.md` | alcance V24 |
   | `docs/architecture/AETHER_V1_SEMANTIC_CONTRACT.md` | contrato normativo |
   | `docs/architecture/AETHER_COMPILER_ARCHITECTURE.md` | confirmación 41 |
   | `docs/architecture/NEXT_VERTICAL_24_REPORT.md` | este informe |

3. **Sintaxis.** `MatrixView<int> v=matrix_view(A);` y
   `MatrixViewMut<int> w=matrix_view_mut(A);`. Las variantes transpuestas son
   `transpose_view(A)` y `transpose_view_mut(A)`. Las cuatro aceptan exactamente
   un Place Matrix o matrix-view, sin argumentos de tipo. No hay métodos,
   constructor de strides ni extensión de temporales. La transposición de una
   vista existente requiere un binding/Place, no anidación de llamadas temporales.

4. **Identidad y propiedades.** `TypeData::MatrixView { element, mutable }` es
   la representación canónica equivalente de ambos tipos fuente. Sólo T y la
   capacidad participan en TypeId. Es distinta de Matrix y View/ViewMut; forma
   y strides son metadata del valor. Interning, sustitución, inferencia de T,
   detección de tipos simbólicos, layout y mangling preservan esa identidad.

   | Tipo | Copy | Relocatable | Storable | needs_drop |
   |---|---|---|---|---|
   | Matrix<T> | no | sí | según Storable de T | sí |
   | MatrixView<T> | sí | sí | no | no |
   | MatrixViewMut<T> | sí | sí | no | no |
   | View/ViewMut existentes | sí | sí | no | no |

   Las propiedades del descriptor prestado son independientes de Copy/drop de T.
   Mutabilidad es capacidad de escritura, sin exclusividad ni promesa noalias.

5. **Descriptor runtime.** `{ptr,rows,columns,row_stride,column_stride}`:
   cinco palabras, 40 bytes y alineación 8 en x86_64. Los strides se miden en
   elementos. No existe tag de ownership, procedencia runtime ni refcount.

6. **Vista normal.** Para propietario R×C, metadata `(R,C,C,1)` y el mismo
   puntero inicial. Sobre una vista existente se conserva su metadata actual,
   que puede ser no contigua en el orden lógico. Crear una vista no mueve al dueño.

7. **Vista mutable.** Usa el mismo mapeo físico, con TypeId writable distinto.
   Las escrituras Copy y las referencias mutables actualizan el backing del
   propietario. Una fuente compartida, incluso por `ref Matrix`, se rechaza.

8. **Transpose-view.** Sobre Matrix R×C produce `(C,R,1,C)`; sobre una vista
   intercambia rows/columns y row_stride/column_stride. No cambia el puntero,
   orden físico, elementos o ownership. El fixture rectangular verifica los
   seis valores de `[1,2,3;4,5,6]` en la transpuesta 3×2. El fixture mutable
   verifica `T[2,1]=99` seguido de `A[1,2]==99`.

9. **Doble transposición.** El fixture `double` comprueba ambos sentidos y
   capacidades, recupera forma 2×3 y verifica accesos/escritura en el owner y
   aliases originales. Las recetas verificadas intercambian dos veces ambos
   pares; recuperan exactamente `(R,C,C,1)`, sin reconstrucción del almacenamiento.

10. **Queries.** MatrixRows/MatrixColumns aceptan los tres tipos y devuelven
    usize de los campos lógicos actuales. HIR conserva el Place y su tipo;
    MIR/SSA resuelven el mismo tipo desde el lugar. LLVM extrae campos 1/2 del
    descriptor de tres o cinco palabras correspondiente.

11. **Índices.** `v[i,j]` lleva OneBased2D y exactamente dos operandos usize.
    Lectura, escritura y referencias comparten cuatro guards ordenados:
    `i>=1`, `i<=rows`, `j>=1`, `j<=columns`. Cero, upper+1, valores enormes y
    vacío se rechazan antes de cualquier dirección. Las formas directas conocidas
    se siguen a través de copias/transpuestas para diagnosticar constantes;
    joins y llamadas mutables descartan conocimiento de forma conservadoramente.

12. **Offset.** Después de los cuatro guards, LLVM calcula
    `(i-1)*row_stride+(j-1)*column_stride`. Extrae ambos strides del descriptor,
    usa mul/add sin nsw/nuw y GEP sin inbounds. No presupone row-major en vistas.

13. **Prueba de seguridad.** El propietario prueba N=R*C representable y bytes
    de backing válidos. En una vista normal el offset máximo es
    `(R-1)*C+(C-1)=N-1`. Transponer sólo intercambia pares coordenada/stride y
    preserva el conjunto de offsets; copiar preserva el descriptor. La inducción
    cubre todos los orígenes admitidos, incluidas firmas de funciones internas.
    No existe construcción fuente con puntero/strides arbitrarios. En vacío
    nunca se alcanza el bloque de dirección. Cada verificador exige la receta
    cerrada exacta para tipo de fuente y operación, no sólo igualdad del producto.

14. **Lectura/escritura.** T Copy puede leerse por valor y reemplazarse mediante
    MatrixViewMut. MatrixView rechaza escritura y `&mut`, también a través de
    referencias y proyecciones. Los verificadores recorren el tipo de cada tramo
    del lugar. La extracción/reemplazo parcial no-Copy conserva rechazo previo;
    no se introduce Clone ni drop implícito para sustituir ranuras.

15. **Elementos propietarios.** El fixture `owning` usa Matrix<Buffer<int>>,
    vista transpuesta compartida y vista normal mutable. Presta Buffer por
    referencia y modifica su subelemento Copy sin extraer ni sustituir el dueño.
    Exige exactamente cinco asignaciones/liberaciones: cuatro Buffer y el Matrix.

16. **Procedencia.** En análisis léxico, MatrixView deriva el owner del Place;
    copiar el local y transformar otra vista consultan la misma tabla de
    procedencia. Los índices/referencias derivados conservan la raíz. En IR la
    operación mantiene el Place fuente como relación de préstamo y las copias
    conservan sus cadenas de uso/definición. No se agrega una raíz de lifetime
    independiente para cada vista ni metadata de procedencia al descriptor LLVM.
    Los parámetros matrix-view usan una raíz proxy local del backing del caller,
    conservada por sus copias y referencias derivadas.

17. **Liveness del dueño.** Move, consumo y reemplazo con vista/copia viva
    producen E0292. Los argumentos prestados permanecen vivos durante la
    evaluación de argumentos posteriores. Tras evaluar índices se vuelve a
    comprobar el dueño, también cuando un índice de Array intenta consumir el
    contenedor del Matrix proyectado. El fixture `scope` permite consumir el
    propietario después de salir del bloque léxico que contiene las vistas.

18. **Copy/alias.** Ambas vistas siguen la política Copy de ViewMut existente.
    El fixture `copy` comprueba escritura por copia mutable observable desde
    los aliases compartidos y mutables. La copia conserva el préstamo al root
    hasta terminar los ámbitos pertinentes. No se promete unicidad/noalias.

19. **No escape/Storable.** Retornar vistas, almacenarlas en structs/enums o
    Array/List/Matrix y rebind de un local prestado siguen rechazados. No hay
    lifetimes almacenados. También se conserva E0276 para argumentos genéricos
    directos como `inspect<MatrixView<int>>`; los parámetros `MatrixView<T>` y
    `MatrixViewMut<T>` con T explícito o inferido sí funcionan. Los tests cubren
    un helper paramétrico sobre `ref Matrix<T>` y T propietario.

20. **Dueños proyectados/anidados.** Se soportan `matrix_view(holder.m)`,
    `transpose_view(array[0])`, vistas mutables de `list[0]` y fuentes `*ref` /
    `*ref mut` explícitas. La procedencia identifica el root del agregado o
    contenedor. La invalidación de List permanece conservadora: una vista de un
    Matrix interior bloquea crecimiento/extracción externa potencialmente
    invalidante aunque su backing interior pudiera conservar dirección física.
    Se rechaza pasar MatrixViewMut con elementos que contienen List a funciones,
    incluyendo referencias al descriptor:
    los efectos de realocación oculta entre parámetros potencialmente alias no
    tienen aún representación segura. Vistas compartidas y mutables de escalares
    o Buffer conservan sus helpers. Tres negativos verifican esta frontera y la
    invalidación de referencias derivadas de un parámetro/copias dentro del helper.

21. **Vacío.** Normal `{null,0,0,0,1}`; transpuesto `{null,0,0,1,0}`. No hay
    asignación, free ni relocation. Se prueban shared/mut y transpose de vista;
    cualquier índice runtime falla por bounds antes de restar o multiplicar.

22. **HIR.** Operación explícita MatrixView con source, mutable, transpose y
    MatrixViewDescriptor; equivale a las cuatro operaciones fuente sin borrar
    tipo/capacidad. La receta contiene selectores de shape/strides, no enteros
    fuente arbitrarios. La verificación HIR rechaza seis corrupciones específicas.

23. **MIR.** Conserva la misma receta y Place prestado; no genera asignación de
    backing ni drop para el valor vista. OneBased2D y ambos operandos sobreviven.
    Verifica contrato de descriptor, tipo de query, índices y capacidad de
    escritura a través de los tipos de cada proyección.

24. **SSA.** Renombra source/copies preservando TypeIds y dependencia del
    descriptor. Walkers visitan fuente y ambos índices para dominancia/promoción.
    Verifica independientemente siete corrupciones, igual que MIR. La autoridad
    del lifetime léxico sigue en frontend, como para referencias/View previos;
    no se agrega un análisis general de lifetimes en MIR/SSA. Los contratos
    independientes de esta vertical son de descriptor/strides, tipos y capacidad.

25. **LLVM.** Transformación compuesta exclusivamente de extractvalue e
    insertvalue después de leer el descriptor fuente. El helper de índices
    matemáticos usa strides. Una firma que sólo recibe MatrixView<int> necesita
    ese helper y no introduce malloc/free. No hay funciones de drop para vistas,
    runtime de procedencia, refcounts o noalias. Mangling estructural usa MV con
    capacidad y tipo de elemento, distinto de M/V/Q de tipos existentes.

26. **Transpose propietario.** `transpose(Matrix)` continúa produciendo E0328.
    No se cambian forma/layout del dueño para simular transposición. Los tests
    V22 de transferencia consumidora Vector y los V23 de Matrix permanecen verdes.

27. **Diagnósticos.** E0336: target/aridad de creación incorrectos; E0337:
    convertir MatrixView compartida a mutable; E0272: escritura a través de ref
    compartida; E0288: escritura por vista compartida; E0334: aridad de índices;
    E0296: bounds constantes; E0292: owner vivo prestado; E0277: rebind prestado;
    E0276: argumentos genéricos prestados; diagnósticos de storage/escape y tipos
    existentes cubren el resto. No existe constructor MatrixView: aplicarlo como
    función produce E0212. Corrupción IR informa stride/type/capability contract.

28. **Dumps.** Dos compilaciones producen HIR/MIR/SSA/LLVM idénticos. Los dumps
    contienen MatrixView, capacidad, transpose, filas/columnas, row_stride,
    column_stride, source Place y OneBased2D. LLVM muestra construcción de cinco
    campos y los dos productos del offset. Los comentarios MatrixViewBegin/End
    delimitan únicamente transformaciones para instrumentación de calificación.

29. **Pruebas exactas.** `cargo test --workspace --no-fail-fast`: **186 tests,
    cero fallos** (7 backend, 24 frontend, 22 middle, 133 integración). Se
    conservan los 178 tests V0..V23. Ocho nuevos tests:

    | Test | Cobertura |
    |---|---|
    | vertical24_hir_rejects_corrupt_matrix_view_contracts | seis corrupciones HIR |
    | vertical24_native_mapping_borrows_and_heap_counts | doce fixtures y módulo importado |
    | vertical24_identity_and_deterministic_ir | identidad, propiedades, layout, dumps, strides y guards |
    | vertical24_structured_diagnostics_and_owner_liveness | códigos exactos, move, storage, escape y elementos propietarios |
    | vertical24_each_view_has_zero_heap_relocation_and_pointer_delta | contadores por operación y puntero idéntico |
    | vertical24_runtime_bounds_all_axes_and_capabilities | 144 ejecuciones con SIGILL exacto |
    | vertical24_mir_ssa_reject_corrupt_descriptor_contracts | siete corrupciones por capa |
    | vertical24_projected_provenance_and_cross_module_rejections | consumo durante índices/argumentos, cuatro firmas incompatibles y helper sin owner runtime |

    Las 144 ejecuciones son dos formas × cuatro creadores × seis índices
    inválidos, con lectura/ref para shared y lectura/escritura/ref/ref-mut para
    mutable. Los índices incluyen 0, upper+1 y usize::MAX en ambos ejes. Las
    corrupciones incluyen shape swap sin stride swap, selector de stride inválido,
    mutabilidad, transpose flag, sustitución raw View y base cero. Junto con
    trece positivos y doce instrumentados son **169 ejecuciones nativas V24**.
    También pasan clippy con `-D warnings`, fmt y git diff --check.

30. **Contadores coste cero.** Para cada transformación ejecutada se miden
    alloc/free/relocation antes/después y se exige delta `(0,0,0)`. Se compara
    puntero fuente/destino. Además el test exige que entre marcadores haya sólo
    extractvalue/insertvalue: ningún load/store de elementos, call o drop. La
    salida verifica resultado fuente, conteos finales exactos y relocation total 0.

    | Fixture v24_matrix_view_* | Alloc = Free |
    |---|---:|
    | normal, mutable, transpose, transpose_mut, double | 1 cada uno |
    | empty | 0 |
    | owning | 5 |
    | projected | 5 |
    | refs, copy, scope, generic | 1 cada uno |
    | módulo v24_matrix_views | 1 |

31. **Snapshots de compilación.** Se mantiene la metodología V17..V23: binario
    debug, proceso nuevo por compilación, un warmup descartado y diez muestras.
    Core suma las ocho fases parse-through-LLVM; excluye startup, discovery,
    I/O, dumps, clang/link y no vuelve a sumar detalles inclusivos de frontend.
    V23 se reconstruyó desde HEAD inicial
    `73be0e2846b242f29c1fc0a6a94e69ff1399684a` bajo `/tmp/aether-v23-baseline`.
    No se ejecutaron builds/tests concurrentes durante las muestras.

    | Compilador / fixture | Core media ms | Core mediana ms |
    |---|---:|---:|
    | V23 original / rectangular V23 | 0.858 | 0.821 |
    | V24 / mismo rectangular V23 | 0.938 | 0.958 |
    | V24 / normal view | 1.161 | 1.117 |
    | V24 / transpose view | 1.517 | 1.423 |
    | V24 / mutable transpose view | 0.937 | 0.882 |
    | V24 / proyectado/anidado | 1.295 | 1.210 |

    Son snapshots descriptivos, no comparaciones equivalentes de coste runtime
    ni evidencia estadística de mejora/regresión: los fixtures realizan trabajo
    distinto. JSON con herramientas y fases completas en
    [v24-debug.json](../../compiler-next/tests/timings/v24-debug.json), reproducible
    con [measure-v24.py](../../compiler-next/tests/measure-v24.py).

32. **Legacy.** `tests/run-differential.sh`: **21 comparaciones ejecutables,
    cero fallos**. No se modifican compiler-rs, runtime/CLI legacy ni scrap. Los
    binarios preexistentes FaCAether y FaCAetherO0 permanecen sin incluir en cambios.

33. **Deuda aceptada.** Borrow léxico conservador, bindings prestados de única
    inicialización, no extracción/reemplazo parcial propietario, ABI bootstrap
    y traps sin unwind. Lifetime no se vuelve a inferir globalmente en MIR/SSA;
    se conserva su autoridad semántica previa. Procedencia nested bloquea List
    conservadoramente. No se expone stride ni se admite préstamo de temporales.
    Se conserva la restricción de argumentos genéricos prestados directos y de
    llamadas con vistas mutables cuyos elementos contienen List.

34. **OPEN DECISIONS.** Transpose propietario (movimiento físico o layout de
    owner distinto), slices/submatrices con intervalos, VectorView con orientación,
    lifetime no léxico/almacenado, ABI pública, strides negativos, layouts
    alternativos, dimensiones estáticas, arithmetic/BLAS y capacidades numéricas.
    V24 no decide ninguna de esas extensiones mediante su descriptor bootstrap.

35. **Problemas arquitectónicos descubiertos.** Los chequeos writable antiguos
    inspeccionaban principalmente la raíz; ahora los verificadores siguen los
    tipos proyectados para detectar vistas compartidas detrás de referencias.
    La revalidación de owner después de índices sólo protegía la proyección 2D;
    se generaliza para evitar consumir el Array que contiene un Matrix al crear
    su vista. La infraestructura genérica prohíbe valores prestados como argumentos
    de tipo directos: se conserva, mientras se habilitan las rutas de T dentro de
    MatrixView<T>. Las nuevas vistas pueden prestar elementos propietarios List,
    a diferencia de raw View: se cierra la frontera de llamadas mutables con
    List anidado para evitar realocaciones ocultas ante aliases vivos.
    Las recetas cerradas evitan abrir un IR de ensamblado de
    descriptores sin pruebas, manteniendo cada eje/stride visible y verificable.

36. **Recomendación NEXT-VERTICAL-25.** Diseñar VectorView/VectorViewMut con
    orientación explícita y procedencia, como extensión acotada antes de admitir
    extracción de filas/columnas o slices. Sus reglas de índice, capacidad,
    strides y transposición prestada deben preservar la identidad Vector y el
    transpose consumidor V22. Matrix transpose propietario y aritmética merecen
    verticales independientes.
