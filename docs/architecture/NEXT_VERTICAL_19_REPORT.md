# NEXT-VERTICAL-19 — indexed owning extraction with List swap_remove

Implementado en `compiler-next`, Linux x86_64. Cierre: 2026-09-07.
`swap_remove(list, index)` extrae un propietario y reemplaza el hueco con el
antiguo tail cuando corresponde. No conserva el orden de List.

1. **Modelo inicial V18.** SlotPlace identifica root, índice y TypeId del
   almacenamiento interno. Take cambia Initialized → Uninitialized y produce
   un valor propietario ordinario. Pop verificaba una transacción contigua
   TailIndex/Take/ListSetLength precedida por lectura fresca y chequeo de vacío.
   Relocate ya describía la transferencia física de almacenamiento en V16.
   Longitud era y sigue siendo la autoridad del prefijo inicializado en runtime.

2. **Archivos cambiados.** Rutas relativas a la raíz:

   | Archivo | Responsabilidad |
   |---|---|
   | `compiler-next/crates/aether-frontend/src/hir.rs` | resolución, HIR, sustitución, procedencia, validación e inferencia contextual |
   | `compiler-next/crates/aether-frontend/src/lib.rs` | exportación de InvalidationShape |
   | `compiler-next/crates/aether-middle/src/mir.rs` | CFG indexado, Relocate entre slots y verificador |
   | `compiler-next/crates/aether-middle/src/ssa.rs` | preservación de operandos/slots y verificación independiente |
   | `compiler-next/crates/aether-backend-llvm/src/lib.rs` | Relocate tail → hole mediante glue existente y contador |
   | `compiler-next/crates/aether-driver/tests/vertical.rs` | nueve pruebas V19 |
   | `compiler-next/tests/programs/v19_swap_remove_{int,buffer,nested,reuse,dataset,enum,array,return,consume,conditional,tail}.ae` | once fixtures nativos |
   | `compiler-next/tests/modules/v19_swap_remove/{main,storage}.ae` | helper genérico entre módulos |
   | `compiler-next/tests/modules/v1-contract.tsv` | admisión del módulo |
   | `compiler-next/tests/measure-v19.py` | medición reproducible con baseline V18 opcional |
   | `compiler-next/tests/timings/v19-debug.json` | snapshot completo de tiempos |
   | `compiler-next/README.md` | sintaxis, implementación y calificación V19 |
   | `docs/architecture/AETHER_V1_LANGUAGE_CHARTER.md` | alcance de la operación |
   | `docs/architecture/AETHER_V1_SEMANTIC_CONTRACT.md` | contrato normativo 6.6 |
   | `docs/architecture/AETHER_COMPILER_ARCHITECTURE.md` | confirmación de implementación 36 |
   | `docs/architecture/NEXT_VERTICAL_19_REPORT.md` | este informe |

3. **Sintaxis fuente.** `T removed = swap_remove(list, index);`,
   `return swap_remove(*list, i);` y `consume(swap_remove(list, i))`.
   El primer argumento es un Place List escribible y el segundo es usize,
   zero-based. Se reutiliza la aplicación neutral del parser; no hay métodos,
   auto-deref ni nueva forma de descarte de resultados como sentencia.

4. **Orden.** Para `[10,20,30,40]`, índice 1 devuelve 20 y deja `[10,40,30]`.
   La operación no preserva orden. Complejidad temporal pretendida O(1), salvo
   el coste del glue de relocalización del elemento. No hay desplazamiento de
   sufijos; `remove(i)` con preservación del orden sigue siendo futuro.

5. **Bounds.** Se evalúa el índice una sola vez y se congela en un temporal
   antes de leer longitud fresca N. `index < N` es el chequeo normal unsigned.
   La arista falsa termina en IndexOutOfBounds sin Take, Relocate, commit ni
   cálculo de N−1. Incluye List vacío y usize máximo. Los errores de tipo de
   índice siguen las reglas ordinarias, sin conversión signed especial.

6. **Tail.** Si index == N−1, el camino completo es Take(tail), commit N−1.
   Cero relocalizaciones de elementos, sin traslado del tail tomado a sí mismo.
   El tail de una lista de un elemento produce un prefijo vacío correctamente.

7. **Transacción no-tail.** Bounds; tail = N−1; Take(index) → result; el slot
   removido pasa a Uninitialized; Relocate(tail → index) inicializa el hueco y
   termina la inicialización del antiguo tail; commit length = tail. El
   verificador comprueba estas identidades sobre los operandos y aristas reales.

8. **SlotPlace.** Se reutiliza sin modificar sus campos. Relocate indexado
   transporta dos SlotPlace, cada uno con root, índice y TypeId. El verificador
   exige mismo List y tipo, origen exactamente tail y destino exactamente el
   slot removido. No se utiliza una proyección Index fuente para autorizar raw
   storage ni se fabrican accesos fuera del prefijo tras un commit temprano.

9. **Take.** Sigue siendo la única extracción. Conserva TakeState
   Initialized → Uninitialized y non_trapping. Su resultado entra en el flujo
   ordinario de propietarios; no se introduce otro primitivo de extracción.

10. **Relocate.** Se reutiliza el contrato de estados V16 y su glue recursivo.
    Se añade RelocationRange::SingleSlot y el postestado explícito
    destination_after = Initialized. Source_before = Initialized,
    destination_before = Uninitialized y source_after = Uninitialized.
    Push/reserve siguen verificando ListInitializedPrefix y ahora también el
    postestado del destino. No hay source Drop, duplicación ni deep copy.

11. **Prefijo inicializado.** Ambos caminos llegan al commit con exactamente
    `[0,N−1)` Initialized y el antiguo tail Uninitialized. El hueco temporal
    sólo existe dentro de la transacción no atrapante y se rellena antes de
    hacer autoritativa la nueva longitud. También se aplica a elementos Copy.

12. **Orden de commit.** El CFG comparte Take antes de una comparación pura
    index == tail. La arista igual está vacía; la desigual contiene exactamente
    un Relocate; ambas saltan al mismo bloque cuyo primer efecto es ListSetLength.
    Compartir Take evita duplicar su resultado propietario o introducir un phi
    de extracción. Cada recorrido conserva el protocolo tail o no-tail exigido.
    No se permite otra entrada a estos caminos ni un efecto intermedio que
    pueda observar el hueco, atrapar o salir antes del commit.

13. **Efecto/invalidation.** StructuralMutation::SwapRemove devuelve
    StableStructuralMutation. InvalidationShape::IndexAndTail explicita el
    conjunto lógico afectado independientemente de la estabilidad del backing.
    Relocalizar un elemento no convierte la operación en realloc de List.
    No se amplía a un sistema general de efectos.

14. **Préstamo del removido.** Ref y ref mut vivos al índice removido bloquean
    swap_remove con E0321. Se comprueban también préstamos temporales de
    argumentos anteriores durante la evaluación de argumentos posteriores.

15. **Préstamo del tail.** Bloquea la operación también en el caso no-tail:
    aunque el valor sobreviva, su dirección cambia. En el caso tail sólo ese
    slot desaparece. Secuencias de extracciones vuelven a consultar el tail
    actualizado, sin conservar hechos obsoletos.

16. **Préstamos no afectados.** Una referencia directa de índice constante i
    sobre un root de longitud conocida N sobrevive si i < N−1 e i != removed.
    La prueba admite slots a ambos lados del hueco; el fixture int retiene
    referencias a 0 y 2 mientras elimina 1 de cuatro elementos. También se
    prueban un préstamo no-tail al eliminar tail y aliases escribibles del List.

17. **Índices desconocidos/dinámicos.** Se rechaza cuando no se puede probar
    separación de ambos slots. No se agregan razonamiento aritmético general ni
    comparaciones de punteros runtime. Se reutilizan hechos de literales y
    decrementos de longitud. Push, backedges List, llamadas escribibles y joins
    divergentes mantienen la política conservadora V18.

18. **View/ViewMut.** Una vista completa cubre la secuencia antigua y bloquea
    swap_remove mientras está viva. Fin de alcance permite la extracción.
    La relación de propietarios anidados sigue siendo conservadora incluso
    cuando la asignación interna de un Buffer podría sobrevivir físicamente.

19. **Genéricos.** Funciona `T takeAt<T: Storable + Relocatable>(ref mut
    List<T> list, usize i) { return swap_remove(*list,i); }`, comprobado
    paramétricamente antes de monomorfizar. Hay llamadas inferidas con elementos
    no-Copy y helpers entre módulos. Los parámetros concretos dan contexto a
    sus argumentos durante inferencia, por lo que un literal de índice recibe
    usize sin una conversión especial. No hay capacidades runtime.

20. **Copy.** List<int> transfiere bits y actualiza la misma vida lógica de
    slots. El antiguo tail deja de ser un elemento inicializado, aunque sus
    bits puedan permanecer físicamente y el resultado sea duplicable.

21. **Propietarios.** Buffer, Array y List transfieren descriptores. La
    extracción no libera los pointees ni el backing; el resultado extraído y
    los supervivientes conservan propietarios únicos y limpieza ordinaria.

22. **Anidados/agregados.** Cobertura nativa de List<Array<int>>,
    List<List<int>>, List<Dataset> con Buffer y enum con variantes propietarias
    y vacías. Se extrae de un campo List dentro de Owner y de un List interior.
    Se comprueban payloads del removido y del tail en su nueva ubicación.

23. **HIR.** ListSwapRemove contiene source Place, expresión index resuelta,
    element_type, effect e invalidation. Sustitución genérica y verificación
    retienen todos ellos. Ninguna identidad de función libre sin resolver
    sobrevive al HIR.

24. **MIR.** CFG explícito de bounds, trap, TailIndex, Take, decisión tail,
    Relocate opcional y commit. Las temporales del índice, longitud, condición,
    Take, Relocate y commit son definiciones únicas sin aliases. El análisis
    ordinario de ownership consume el resultado una vez. Pop conserva su
    transacción V18, sin reescritura a swap_remove.

25. **SSA.** Preserva SlotPlace, estados, Take y Relocate. Un verificador
    independiente inspecciona su propio CFG, sin confiar en VerifiedMir para
    aceptar una transacción corrupta. No admite phis dentro del diamante de
    slots; el resultado Take no-Copy debe transferirse una vez antes de un phi.
    La comprobación de unicidad de Take es común a pop y swap_remove en SSA.

26. **LLVM.** Take reutiliza la transferencia V18. Relocate materializa los
    dos GEP del backing estable y llama al glue tipado existente; incrementa
    una vez el contador de relocalización sólo en la arista no-tail. Commit
    escribe únicamente el campo length. No hay helper backend que esconda
    bounds, la decisión de tail o una mutación no representada en MIR/SSA.

27. **Frescura.** Los roots mutados cruzan la frontera de memoria selectiva
    existente. Se prueban ref mut aliases, consultas de longitud a través del
    alias y del owner, campos, List anidado, push y retorno/move del descriptor.
    Todos observan la nueva longitud; no se agregan supuestos noalias.

28. **Asignaciones/liberaciones.** Se ejecutan contadores exactos de heap y
    guard de balance en cada fixture. Probes antes de Take y después de cada
    commit comparan puntero, capacidad, asignaciones y frees: delta 0 en todos.

    | Fixture `v19_swap_remove_…` | Alloc | Free | Relocate total |
    |---|---:|---:|---:|
    | int | 1 | 1 | 1 |
    | buffer | 5 | 5 | 1 |
    | nested | 5 | 5 | 2 |
    | reuse | 5 | 5 | 4 |
    | dataset | 4 | 4 | 1 |
    | enum | 3 | 3 | 2 |
    | array | 4 | 4 | 1 |
    | return | 3 | 3 | 1 |
    | consume | 3 | 3 | 1 |
    | conditional | 10 | 10 | 4 |
    | tail | 3 | 3 | 0 |

29. **Relocalizaciones.** Los probes calculan el delta por operación y
    requieren exactamente 0 cuando index == nueva longitud y 1 en otro caso.
    En reuse, tres relocalizaciones corresponden al reserve de los tres
    Buffers y una a swap_remove. El push con capacidad disponible no agrega
    asignaciones ni relocalizaciones. Los contadores son instrumentación, no
    una API semántica pública.

30. **Preservación de datos.** Int comprueba 20 como resultado y `[10,40,30]`
    como secuencia final. Buffer comprueba cada payload. Nested/array validan
    contenidos de dos elementos y longitudes; Dataset valida Buffer y campo
    escalar; enum comprueba payload activo y variante vacía. También se verifica
    que una expresión de índice con efecto se evalúe una sola vez.

31. **Drop.** Contadores exactos y ejecución de propietarios retornados,
    consumidos, condicionalmente movidos y extraídos en bucle detectan fugas y
    doble limpieza. Un probe de free registra los payloads de los cuatro Buffers:
    primero 20 (resultado), luego 30,40,10 (reverse FINAL indices de List).
    El antiguo tail no recibe limpieza oculta en su ubicación original.

32. **Diagnósticos.** E0320 para target no-List/no escribible o aridad/type
    arguments inválidos; E0321 para préstamo/vista que puede cubrir removido o
    tail; errores ordinarios de índice/tipo y E0310 para garantías insuficientes.
    IndexOutOfBounds reutiliza el trap estructurado. Los errores internos usan
    E0300/Phase::Mir y E0400/Phase::Ssa, con mensajes de transacción/slot.

33. **Dumps.** Dos compilaciones producen dumps iguales. HIR muestra
    ListSwapRemove, StableStructuralMutation e IndexAndTail; MIR/SSA muestran
    TailIndex, Take, Relocate SingleSlot, estados, IndexOutOfBounds y commit.
    LLVM conserva la comparación, los GEP de origen/hueco y comentarios de
    transición. Los probes runtime complementan la inspección de dumps.

34. **Pruebas exactas.** `cargo test --workspace --no-fail-fast`:
    **142 pruebas, cero fallos** (7 backend, 20 frontend, 22 middle,
    93 integración). Las nueve nuevas pruebas son:

    | Prueba | Cobertura |
    |---|---|
    | vertical19_swap_remove_native_owners_and_exact_counts | once fixtures y helper entre módulos; resultados y contadores |
    | vertical19_swap_remove_diagnostics | target, shared, índices, slots removido/tail, unknown/dynamic, vistas, anidados, aliases, loops y genéricos |
    | vertical19_scopes_aliases_and_descriptor_freshness | fin de scopes, aliases, moves/returns, proyecciones, push y evaluación única del índice |
    | vertical19_bounds_trap_before_transaction | vacío Copy/propietario, length y usize máximo fuera de rango |
    | vertical19_deterministic_semantic_dumps | contratos HIR/MIR/SSA/LLVM y determinismo |
    | vertical19_each_swap_remove_preserves_storage_heap_and_relocation_counts | probes por operación en once fixtures |
    | vertical19_mir_rejects_corrupt_slot_transactions | 23 corrupciones MIR |
    | vertical19_ssa_rejects_corrupt_slot_transactions | las mismas 23 corrupciones SSA independientes |
    | vertical19_drop_order_uses_reverse_final_indices | secuencia exacta de destrucción de payloads |

    Las corrupciones cubren root/slot Take incorrectos, Take Uninitialized,
    Relocate antes de Take, source/destination erróneos, traslado en tail,
    Relocate ausente/doble, tail vivo, hueco sin inicializar, longitud errónea,
    commit temprano, length/index obsoletos, Drop de origen tras relocalización,
    Use duplicante de no-Copy, TypeId erróneo, transferencia atrapante,
    aristas invertidas, frescura interrumpida, salida antes de commit y Take que
    conserva inicialización. Clippy workspace/all-targets con `-D warnings`,
    fmt check y diff check pasan.

35. **Tiempos.** Se conserva la metodología V17/V18: debug, procesos nuevos,
    un warmup descartado y diez muestras por fixture. Core suma los ocho
    temporizadores parse → LLVM; excluye startup, discovery, I/O, dumps y
    clang/link. Detalles frontend siguen siendo inclusivos y no aditivos.
    Baseline V18 construido por separado desde
    `e47eb93705cb94d9d1287b3375b472f6474659b1` en `/tmp`. No hubo compilación
    concurrente de esta tarea durante la medición. Linux x86_64, rustc 1.97.1,
    clang 22.1.8.

    | Compilador / fixture | Core media ms | Core mediana ms |
    |---|---:|---:|
    | V18 original / v18_pop_buffer | 1.963 | 1.914 |
    | V19 / v18_pop_buffer | 1.444 | 1.400 |
    | V19 / swap_remove int | 1.591 | 1.563 |
    | V19 / swap_remove Buffer | 1.280 | 1.243 |
    | V19 / swap_remove nested | 1.943 | 1.819 |
    | V19 / swap_remove reuse | 1.427 | 1.353 |

    Son snapshots debug con variabilidad de host/caché y compiladores
    construidos por separado, sin atribución de mejora estadística ni trabajo
    de optimizador. [JSON completo](../../compiler-next/tests/timings/v19-debug.json)
    y [script](../../compiler-next/tests/measure-v19.py). Desde `compiler-next`:
    `python3 tests/measure-v19.py --runs 10`, opcionalmente con
    `--baseline-binary <v18> --baseline-revision <revision>`.

36. **Legacy.** `tests/run-differential.sh`: **21 casos, cero fallos**.
    No se modifican compiler-rs, compilador/runtime/CLI legacy ni archivos del
    usuario en scrap. La implementación está limitada a compiler-next, sus
    pruebas y documentación. No se creó commit ni se publicó nada.

37. **Deuda aceptada.** Procedencia léxica/anidada conservadora, sin último
    uso ni subrangos. La prueba de slots admite sólo las formas CFG acotadas
    pop e indexed diamond; futuros pases deben preservar o ampliar esa prueba.
    Los roots mutados permanecen en memoria selectiva y agregados Take pueden
    requerir el temporal de stack V18. Se mantienen la ABI bootstrap, límites
    genéricos y admisión estrecha de Buffer. No se añaden bitmap, rollback,
    lifetimes, métodos, Option, traits, Array extraction ni optimizador.

38. **OPEN DECISIONS.** El resultado fuera de rango queda resuelto como
    IndexOutOfBounds, y swap_remove no promete orden. Siguen abiertas la API
    opcional de biblioteca, precisión de procedencia/rangos, efectos de helpers
    interprocedurales, promoción de descriptores, ABI pública y construcción de
    propietarios sensibles a su dirección. No bloquean esta vertical.

39. **Problemas arquitectónicos.** MutationEffect por sí solo no describe
    qué objetos dejan de ocupar sus slots; se añade una forma pequeña de
    invalidación. Relocate de crecimiento sólo tenía autoridad de rango y
    destino inicial: SingleSlot más destination_after permite expresar y
    comprobar el relleno del hueco. La inferencia genérica prechequeaba todos
    los argumentos sin tipo esperado: un literal para un parámetro usize se
    convertía en int64 y fallaba incluso cuando el otro argumento determinaba T.
    Ahora sólo parámetros que contienen genéricos carecen de contexto inicial;
    los concretos reutilizan las reglas ordinarias. No se cambian capacidades
    ni se introduce una conversión de índices específica de swap_remove.

40. **Recomendación NEXT-VERTICAL-20.** Una única operación order-preserving
    `remove(list,i)` con contrato de invalidación del sufijo `[i,N)` y
    transacción Take + relocalización creciente del sufijo hacia el hueco.
    Antes de implementarla, definir autoridad del rango solapado, prueba de
    inicialización por iteración, commit y coste O(N−i). Reutilizar Take,
    Relocate y SlotPlace sin generalizar todavía a insert, drain o lifetimes.
    V19 no implementa remove ni insert.
