# NEXT-VERTICAL-26 — Matrix/MatrixView row and column projections to oriented VectorView

Implementado y calificado en `compiler-next`, Linux x86_64, 2026-09-08.
Las cuatro operaciones conectan las abstracciones matemáticas 2D y 1D con
préstamos completos de un eje, sin copias de elementos ni asignación de backing.

1. **Modelo inicial.** V21 Vector<T,Row/Column> es un propietario 1D fijo con
   índice desde uno; V22 transpose consume su descriptor. V23 Matrix<T> es
   propietario 2D fijo row-major, con `{ptr,rows,columns}`. V24 MatrixView y
   MatrixViewMut tienen `{ptr,rows,columns,row_stride,column_stride}` y transpose
   prestado. V25 VectorView y VectorViewMut usan `{ptr,dimension,stride}`,
   orientación estática, préstamos léxicos y transpose de descriptor. V26
   conecta estas representaciones sin cambiar sus identidades ni layouts.

2. **Archivos cambiados.** Rutas relativas a la raíz:

   | Archivo | Responsabilidad |
   |---|---|
   | `compiler-next/crates/aether-frontend/src/types.rs` | receta cerrada MatrixAxisVectorViewDescriptor |
   | `compiler-next/crates/aether-frontend/src/lib.rs` | exportación de la receta |
   | `compiler-next/crates/aether-frontend/src/hir.rs` | intrínsecos, operación, sustitución, procedencia, bounds constantes, verificador y dos tests HIR |
   | `compiler-next/crates/aether-middle/src/mir.rs` | operación, captura del Place, índice, trap, verificación y diagnóstico de root inexistente |
   | `compiler-next/crates/aether-middle/src/ssa.rs` | operación, renombrado, dependencias y verificación independiente |
   | `compiler-next/crates/aether-backend-llvm/src/lib.rs` | extracción lógica, guards, GEP, descriptor y continuaciones LLVM |
   | `compiler-next/crates/aether-driver/tests/vertical.rs` | siete tests integrales V26 |
   | `compiler-next/tests/programs/v26_matrix_axis_*.ae` | dieciséis fixtures enumerados en el punto 33 |
   | `compiler-next/tests/modules/v26_matrix_axes/{main,helper}.ae` | helpers genéricos importados |
   | `compiler-next/tests/modules/v1-contract.tsv` | registro ejecutable del módulo |
   | `compiler-next/tests/measure-v26.py` | snapshots reproducibles |
   | `compiler-next/tests/timings/v26-debug.json` | resultados por fase |
   | `compiler-next/README.md` | operaciones y modelo actual |
   | `docs/architecture/AETHER_V1_LANGUAGE_CHARTER.md` | admisión V26 |
   | `docs/architecture/AETHER_V1_SEMANTIC_CONTRACT.md` | contrato normativo V26 |
   | `docs/architecture/AETHER_COMPILER_ARCHITECTURE.md` | confirmación 43 |
   | `docs/architecture/NEXT_VERTICAL_26_REPORT.md` | este informe |

3. **Operaciones fuente.** `row(A,i)`, `column(A,j)`, `row_mut(A,i)` y
   `column_mut(A,j)`. Dos argumentos, índice usize y ningún argumento de tipo.
   Son aplicaciones intrínsecas, sin métodos ni sintaxis nueva del parser.

4. **Fuentes aceptadas.** Shared admite Matrix<T>, MatrixView<T> y
   MatrixViewMut<T>. Mutable admite Matrix<T> escribible o MatrixViewMut<T>
   escribible por el Place actual. Funcionan locals, campos, dueños indexados
   y referencias explícitamente dereferenciadas. No hay auto-deref ni préstamo
   de temporales. MatrixView compartida no puede generar una proyección mutable.

5. **Resultado e identidad.** Row produce VectorView<T,Row> y Column produce
   VectorView<T,Column>; `_mut` selecciona VectorViewMut con la misma orientación.
   Se reutiliza TypeData::VectorView y se conserva T exactamente. Row/Column es
   orientación matemática estática, independiente de contigüidad/stride. No
   existen RowView, ColumnView, raw View ni Vector propietario intermedio.

6. **Receta Row.** Del descriptor lógico `(ptr,R,C,RS,CS)`: bound fijo R,
   base `(i-1)*RS`, dimensión C, stride CS, orientación Row. Selectores exactos
   Rows / RowStride / Columns / ColumnStride.

7. **Receta Column.** Bound fijo C, base `(j-1)*CS`, dimensión R, stride RS,
   orientación Column. Selectores exactos Columns / ColumnStride / Rows /
   RowStride. Capacidad proviene de la operación, no de los selectores.

8. **Matrix propietario.** LLVM materializa RS=C, CS=1 para el mismo modelo
   lógico. Row queda `{ptr+(i-1)*C,C,1}`; Column `{ptr+(j-1),R,C}`. La receta
   semántica no tiene una variante que evite la prueba genérica de descriptor.

9. **MatrixView normal.** Se extraen R, C, RS y CS de los campos existentes.
   Las filas y columnas de una vista normal conservan los mismos valores que
   las del propietario; shared desde MatrixViewMut observa escrituras de aliases.

10. **MatrixView transpuesta.** Para `[1,2,3;4,5,6]`, T tiene `(R,C,RS,CS)`
    igual a `(3,2,1,3)`. `row(T,2)` da Row `[2,5]`, dimensión 2, stride 3;
    `column(T,2)` da Column `[4,5,6]`, dimensión 3, stride 1. Se verifican todos
    los valores y, por instrumentación, el puntero y ambos campos del resultado.

11. **Bounds del eje fijo.** Row comprueba `i>=1`, después `i<=rows`; Column
    usa columns. Sólo después se resta uno y calcula el offset. Constantes con
    forma léxica conocida producen E0296; otras usan IndexOutOfBounds/llvm.trap.
    Creación no consulta el índice del segundo eje. Usar el resultado dispara
    los bounds 1D ordinarios de V25.

12. **Seguridad del offset.** V24 garantiza coordenadas válidas dentro del
    backing. Un índice k de Row mapea a `i0*RS+k0*CS`, exactamente coordenada
    fuente (i,k); Column mapea a `k0*RS+j0*CS`, coordenada (k,j). La invariante
    del descriptor y los bounds prueban representabilidad e inclusión en la
    asignación. LLVM usa sub/mul sin nsw/nuw y GEP sin inbounds. No hay stride
    arbitrario suministrado por el usuario ni resta antes del límite inferior.

13. **Contrato zero-copy.** Cada proyección exitosa tiene deltas de
    alloc/free/relocation `(0,0,0)`. Sólo extrae descriptor, comprueba bounds,
    calcula dirección y construye tres palabras. Ningún load/store/copy/drop
    de elementos ocurre dentro de los marcadores de proyección. Resolver o
    cargar el descriptor fuente es parte de evaluar su Place.

14. **Capacidad compartida.** El resultado permite Copy reads y referencias
    compartidas; rechaza asignación y préstamos mutables. Puede originarse en
    un descriptor mutable sin transferir su capacidad writable al resultado.

15. **Capacidad mutable.** Los análisis fuente y los tres verificadores
    recorren el camino tipado. Rechazan MatrixView shared, ref Matrix shared y
    ref MatrixViewMut shared como fuentes mutables. No recuperan capacidad del
    owner subyacente. Writable no significa exclusividad ni noalias.

16. **Write-back.** `row_mut(A,2)[2]=99` mediante un binding actualiza A[2,2];
    `column_mut(A,2)[1]=77` actualiza A[1,2]. Desde T transpuesta,
    `row_mut(T,2)[1]=88` actualiza A[1,2] y `column_mut(T,2)[3]=99` A[2,3].
    También se ejecutan ref-mut de elementos y transpose mutable del resultado.

17. **Indexado reutilizado.** El resultado usa exactamente la proyección
    OneBased de VectorView V25 y su helper `(k-1)*stride`. No hay un helper
    MatrixRow especial, ni cambio al indexado VectorView existente.

18. **Dimensión.** `dimension` no necesita cambios. Row hereda columns y
    Column rows de la fuente lógica actual. Los hechos léxicos de dimensión
    también se conservan cuando hay forma conocida, incluidas transpuestas.

19. **Elementos propietarios.** `owning` proyecta Matrix<Buffer<int>> por
    fila transpuesta y columna del owner. Presta Buffer y subelementos; una
    columna mutable actualiza un int de Buffer. Se verifican cinco alloc/free
    finales. Extracción de Buffer por valor y sustitución parcial propietaria
    siguen rechazadas; no se introduce Clone ni drop oculto.

20. **Procedencia.** La nueva expresión deriva su owner del Place fuente,
    usando la misma tabla de V24/V25. Matrix -> transpose_view -> row/column
    -> copia/transpose/load VectorView conserva el dueño original. Parámetros
    prestados usan las raíces proxy existentes del caller. El descriptor
    MatrixView local no se convierte en propietario ni raíz independiente.

21. **Liveness del propietario.** Move, consumo y reemplazo del root con
    proyección/alias vivo producen E0292. El préstamo también se instala durante
    la evaluación del índice fijo para impedir consumo o invalidación desde
    ese argumento. Al salir del ámbito de todas las vistas vuelve a admitirse
    el consumo del dueño y su limpieza ordinaria.

22. **Copias y aliases.** VectorView y VectorViewMut continúan Copy,
    Relocatable, no-Storable y sin drop. Copias, cargas por referencias y
    transpuestas conservan raíz y observan el mismo backing. Se permiten
    múltiples aliases mutables conforme a la política previa; no hay refcounts.

23. **Genéricos.** Helpers MatrixView<T>/MatrixViewMut<T> pueden proyectar
    ambos ejes localmente. Inferencia y sustitución conservan T; Copy reads y
    writes requieren T:Copy. Consultar dimensión funciona con T simbólico sin
    Copy, incluido Buffer<int>. Fuentes `ref Matrix<T>` necesitan T:Storable.
    Se ejecutan helpers locales/importados y parámetros VectorView derivados.
    No hay O genérico, traits ni dispatch runtime.

24. **Fuentes proyectadas/anidadas.** `row(holder.m,2)`, `column(array[0],2)`
    y `row_mut(list[0],1)` funcionan, conservando el root contenedor. MIR captura
    la dirección del descriptor proyectado antes del índice fijo: en
    `row(array[i],advance(&mut i))` se conserva el elemento elegido originalmente.
    Referencias explícitas al owner y a MatrixViewMut también funcionan.
    Nested List growth/extraction permanece conservador, aunque el backing del
    Matrix interior pudiera ser estable. No se almacenan MatrixView anidadas.

25. **Frontera de efectos mutables.** Se reutiliza sin cambios
    `has_untracked_mutable_view_effect`: una proyección VectorViewMut cuyos
    elementos contienen List no cruza llamadas, tampoco mediante referencias
    al descriptor. Negativos cubren copias por Load, aliases dentro de helpers
    y mutación invalidante del List contenedor durante el índice fijo.

26. **Vacío.** Matrix literal vacío es 0x0. Ni row(empty,1) ni column(empty,1)
    tiene eje válido. Las constantes se diagnostican; índices runtime atrapan,
    incluyendo fuentes normales/transpuestas shared/mut. No se fabrica una
    VectorView vacía ni se calcula un offset sobre null.

27. **HIR.** `MatrixAxisVectorView {source,fixed_index,axis,mutable,descriptor}`
    conserva la operación matemática explícita. El TypeId de la expresión aporta
    T, orientación y capacidad del resultado; la receta contiene fixed_extent,
    base_stride, dimension y stride. Monomorfización sustituye fuente e índice.
    Verificación comprueba rango/tipos, usize, capacidad y selectores exactos.

28. **MIR.** Rvalue homónimo mantiene Place, operando fijo, eje, capacidad,
    receta y bounds_trap=IndexOutOfBounds. El resultado es un local VectorView
    normal, sin asignación de backing ni drop. Para fuentes proyectadas/ref,
    un Borrow interno congela la dirección antes de evaluar el índice. El
    verificador audita contrato y disponibilidad del source por separado.

29. **SSA.** Operación homónima y TypeId de resultado sobreviven a renombrado.
    Walkers de liveness/dominancia visitan Place e índice fijo. La verificación
    independiente rechaza orientación, dimensiones, strides, tipo/rango,
    capacidad, índice y trap incorrectos. La autoridad global del préstamo
    sigue siendo el frontend léxico, como en V24/V25.

30. **LLVM.** Extracción del descriptor fuente, materialización lógica de
    strides de owner cuando corresponde, lower/upper guards, sub/mul, GEP y
    tres insertvalue. No hay helper runtime de proyección, allocator, free ni
    drop de vista. Las continuaciones de las nuevas instrucciones con guards
    participan en el cálculo de predecesores LLVM de phis; se prueba en loops
    y ramas con más de una proyección.

31. **Diagnósticos.** E0340: target/aridad/type arguments de row/column;
    E0341: proyección mutable desde MatrixView shared; E0272: ref compartida;
    E0296: IndexOutOfBounds constante; E0288: escritura por resultado shared;
    E0292: owner prestado; E0277: rebind; E0313: invalidación/efectos List.
    Índices no-usize, mismatch de orientación/capacidad, storage/escape y
    reemplazo propietario usan sus diagnósticos tipados previos. Los nuevos
    diagnósticos de proyección nombran Matrix/MatrixView/VectorView, sin borrar
    la operación a raw View. Corrupciones IR reportan contrato
    bounds/recipe/orientation/capability o source rank/type.

32. **Dumps.** Dos compilaciones producen HIR/MIR/SSA/LLVM idénticos.
    Se comprueban nombre MatrixAxisVectorView, fixed_index, ambos ejes,
    capacidad, todos los selectores y resultado VectorView. El Place y las
    cadenas de creación/copia conservan la procedencia inspeccionable, sin
    campo de owner runtime. MIR/SSA muestran IndexOutOfBounds. LLVM contiene
    MatrixAxisVectorViewBegin/End, extracción, guards, base GEP y tres palabras.

33. **Pruebas exactas.** `cargo test --workspace --no-fail-fast` pasa con
    **206 tests, cero fallos**: 7 backend, 27 frontend, 22 middle y 150 integración.
    Se conservan los 197 de V0..V25 y se agregan nueve:

    | Test | Evidencia |
    |---|---|
    | vertical26_hir_rejects_corrupt_projection_recipes | nueve corrupciones por eje: 18 rechazos HIR |
    | vertical26_hir_rejects_shared_projection_source | dos fuentes shared con resultado mutable coherente |
    | vertical26_native_mapping_borrows_and_heap_counts | 16 fixtures y módulo importado |
    | vertical26_structured_diagnostics_and_provenance | 23 códigos exactos y 20 rechazos adicionales |
    | vertical26_mir_ssa_reject_corrupt_recipes | diez corrupciones por eje y capa: 40 rechazos |
    | vertical26_runtime_fixed_axis_and_result_bounds | 336 ejecuciones SIGILL |
    | vertical26_deterministic_ir_and_ordered_bounds | dumps, orden de guards y helper sólo-view sin malloc/free |
    | vertical26_each_projection_zero_cost_and_exact_pointer_metadata | 17 ejecutables instrumentados, metadatos y contadores exactos |
    | vertical26_mir_ssa_reject_shared_source_with_matching_mutable_result | dos ejes por capa con fuente shared y resultado mutable coherente |

    Fixtures `v26_matrix_axis_`: `row`, `column`, `row_mut`, `column_mut`,
    `normal`, `transpose_row`, `transpose_column`, `transpose_mut`, `owning`,
    `projected`, `refs`, `copy`, `scope`, `generic`, `control_flow`, `evaluation`.
    Módulo `v26_matrix_axes/{main,helper}.ae`, también registrado en el contrato
    general de módulos. Clippy con `-D warnings`, fmt y git diff --check pasan.

34. **Ejecuciones bounds.** Cuatro formas (0x0, 1x3, 3x1, 2x3), cinco fuentes
    (owner, vista normal/transpuesta shared/mut), dos ejes y capacidades legales.
    Índices 0, upper+1, usize::MAX: **192 fallos de creación**. Para las tres
    formas no vacías se crea una proyección válida y se indexa el resultado con
    esos tres valores: **144 fallos V25**, lecturas shared/escrituras mutables.
    Todos exigen señal 4 (SIGILL/llvm.trap), no sólo status no exitoso. Las 17
    ejecuciones positivas más 17 instrumentadas dan **370 ejecuciones nativas
    dedicadas V26**, además del módulo en el contrato general.

35. **Contadores zero-cost.** Cada proyección ejecutada compara alloc/free/
    relocation antes/después: delta `(0,0,0)`. El harness calcula por separado
    el puntero esperado desde el descriptor fuente y compara pointer, dimensión
    y stride. Se prohíben cargas/escrituras/calls de elementos en los marcadores.
    Relocation final es cero y alloc/free finales exactos:

    | Fixture | Alloc = Free |
    |---|---:|
    | row, column, row_mut, column_mut | 1 cada uno |
    | normal, transpose_row, transpose_column, transpose_mut | 1 cada uno |
    | owning, projected | 5 cada uno |
    | refs, copy, scope, control_flow | 1 cada uno |
    | generic, evaluation | 3 cada uno |
    | módulo v26_matrix_axes | 1 |

36. **Snapshots de compilación.** Metodología V17..V25: driver debug, proceso
    nuevo, un warmup descartado y diez muestras por fixture. Core suma ocho
    fases parse-through-LLVM; excluye startup/discovery/I/O/dumps/clang/link y
    fases inclusivas duplicadas. Antes de editar se compiló HEAD V25
    `71aeb540b195f3732c454055051e9f15bdc5f685` y se conservó el ejecutable en
    `/tmp/aether-v25-v26-baseline`. No hubo builds/tests concurrentes durante
    las muestras.

    | Compilador / fixture | Core media ms | Core mediana ms |
    |---|---:|---:|
    | V25 original / VectorView normal | 1.147 | 1.102 |
    | V26 / mismo VectorView normal | 0.940 | 0.936 |
    | V26 / row propietario | 1.100 | 1.030 |
    | V26 / column propietario | 1.060 | 1.015 |
    | V26 / row de vista transpuesta | 1.233 | 1.177 |
    | V26 / propietario proyectado mutable | 1.556 | 1.503 |

    Son snapshots descriptivos de compilación, con trabajo distinto por fixture;
    no prueban mejora/regresión estadística ni velocidad runtime. Datos completos
    en [v26-debug.json](../../compiler-next/tests/timings/v26-debug.json), script
    [measure-v26.py](../../compiler-next/tests/measure-v26.py).

37. **Legacy.** `bash compiler-next/tests/run-differential.sh`: **21 comparaciones,
    cero fallos**. No se modifican compiler-rs, runtime/CLI legacy ni scrap.
    Los binarios no rastreados preexistentes FaCAether y FaCAetherO0 permanecen
    fuera de los cambios de V26.

38. **Deuda aceptada.** Borrow léxico conservador, no lifetimes almacenados,
    no escape ni rebind de locals prestados, no reemplazo/extracción parcial
    propietaria. Para `transpose_view(row(A,i))` se exige binding intermedio:
    `VectorView<int,Row> r=row(A,i); VectorView<int,Column> t=transpose_view(r);`.
    No se introduce extensión de lifetime temporal. Se conservan la frontera
    mutable con List, ABI bootstrap x86_64, traps sin unwind y autoridad léxica
    frontend para lifetime; MIR/SSA verifican contratos, no lifetimes globales.

39. **OPEN DECISIONS.** Slices/rangos y submatrices; strides negativos; lifetimes
    no léxicos/almacenados; ABI pública; layouts alternativos; dimensiones
    estáticas; orientación genérica O; owning Matrix transpose; copias
    propietarias explícitas de ejes; aritmética/BLAS/capacidades numéricas.
    Ninguna extensión queda implícitamente admitida por esta proyección.

40. **Problemas arquitectónicos descubiertos.** Un segundo argumento con
    efectos obliga a proteger el root durante la evaluación y congelar el
    Place proyectado antes de que cambie su índice externo. La implementación
    usa borrows y operandos existentes, sin MemorySSA ni estado de ownership
    nuevo. Los guards inline requieren integrar la operación en continuaciones
    LLVM para phis correctas. Un LocalId fuente corrupto exponía indexación
    Rust sin comprobación en `require_place_owner`; ahora produce diagnóstico
    estructurado. Las recetas permanecen lógicas y comunes a Matrix/MatrixView;
    no se introduce una excepción row-major para vistas.

41. **Recomendación NEXT-VERTICAL-27.** Diseñar slices prestados 1D de
    Vector/VectorView con contrato explícito de intervalo, vacío, bounds,
    dimensión/stride y procedencia. Mantener recetas cerradas y pruebas sobre
    columnas no contiguas obtenidas en V26; abordar submatrices 2D en una
    vertical posterior. Aritmética, BLAS y lifetimes merecen decisiones propias.
