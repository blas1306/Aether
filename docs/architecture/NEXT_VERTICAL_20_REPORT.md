# NEXT-VERTICAL-20 — order-preserving indexed List removal

Implementado en `compiler-next`, Linux x86_64. Cierre: 2026-09-07.
`remove(list,index)` conserva el orden con una transacción explícita de hueco
móvil y relocalización creciente del sufijo. No se modifica la CLI legacy.

1. **Modelo inicial V19.** SlotPlace identificaba root, índice y TypeId; Take
   transfería el elemento de Initialized a Uninitialized. SingleSlot Relocate
   expresaba ambos slots y sus cuatro estados, con glue no atrapante. V19
   comprobaba un diamante de extracción del tail o sustitución desde tail,
   commit del prefijo y préstamos de IndexAndTail. Longitud sigue siendo la
   única autoridad runtime del prefijo inicializado.

2. **Archivos cambiados.** Rutas relativas a la raíz:

   | Archivo | Cambio |
   |---|---|
   | `compiler-next/crates/aether-frontend/src/hir.rs` | ListRemove, sustitución, resolución, validación, SuffixFrom y préstamos |
   | `compiler-next/crates/aether-middle/src/mir.rs` | bucle de hueco, HoleNext, resolución previa del descriptor y prueba inductiva |
   | `compiler-next/crates/aether-middle/src/ssa.rs` | preservación, phi de hueco y verificador independiente |
   | `compiler-next/crates/aether-backend-llvm/src/lib.rs` | sucesor acotado; Relocate existente admite el nuevo bucle |
   | `compiler-next/crates/aether-driver/tests/vertical.rs` | once pruebas V20 e instrumentación |
   | `compiler-next/tests/programs/v20_remove_{int,first,middle,last,single,buffer,array,nested,dataset,enum,reuse,return,consume,conditional,tail}.ae` | quince fixtures |
   | `compiler-next/tests/modules/v20_remove/{main,storage}.ae` | helper genérico importado |
   | `compiler-next/tests/modules/v1-contract.tsv` | admisión del módulo |
   | `compiler-next/tests/measure-v20.py` | snapshots reproducibles |
   | `compiler-next/tests/timings/v20-debug.json` | resultados completos |
   | `compiler-next/README.md` | contrato actual, ejemplo y calificación |
   | `docs/architecture/AETHER_V1_LANGUAGE_CHARTER.md` | alcance V20 |
   | `docs/architecture/AETHER_V1_SEMANTIC_CONTRACT.md` | contrato normativo 6.7 |
   | `docs/architecture/AETHER_COMPILER_ARCHITECTURE.md` | confirmación 37 |
   | `docs/architecture/NEXT_VERTICAL_20_REPORT.md` | este informe |

3. **Sintaxis fuente.** `T removed = remove(list,index);`,
   `return remove(*values,i);` y `consume(remove(values,i))`. El target debe ser
   un Place List escribible. Se reutiliza la aplicación neutral del parser,
   con índice usize zero-based. No hay métodos ni nuevo descarte de resultados
   como sentencia.

4. **Contrato de orden.** `{10,20,30,40}` eliminando 1 devuelve 20 y deja
   `{10,30,40}`. Swap_remove sigue dejando `{10,40,30}`. No se implementa
   remove componiendo swap_remove y un reordenamiento posterior.

5. **Complejidad.** Remove tiene coste pretendido O(N-i), exactamente N-i-1
   relocalizaciones de elementos, más el coste de Take y del glue de T.
   Swap_remove conserva O(1), con cero o una relocalización. El coste lineal
   del sufijo se documenta explícitamente y no se oculta en un helper LLVM.

6. **Bounds.** Se evalúa una vez el índice, se congela en un temporal y se
   lee longitud fresca. La rama unsigned i<N precede N-1, Take, Relocate y
   commit. Su rama falsa termina en IndexOutOfBounds, incluso para vacío o
   usize máximo, dejando el List sin cambios de la transacción. Los efectos
   ordinarios de evaluar el índice ocurren antes del chequeo.

7. **Tail.** Para i=N-1, Take deja el tail raw y la primera condición del
   bucle es falsa: no se ejecuta su cuerpo ni se llama Relocate. Se hace commit
   inmediato de N-1. Singleton sigue el mismo camino y termina en longitud 0,
   sin cambiar capacidad. Es coherente con la extracción de pop.

8. **Transacción general.** Bounds → TailIndex → Take(i) → hole=i → header
   hole<tail → HoleNext(hole) → Relocate(hole+1 → hole) → hole=next → header.
   La única salida del header llega a ListSetLength(tail). El resultado
   extraído se usa después, con las reglas ordinarias de ownership.

9. **Invariante del hueco.** Al entrar al header, `[0,h)` está Initialized
   con los valores finales; h está Uninitialized; `(h,N)` contiene los valores
   vivos pendientes de desplazamiento. Take establece el caso base h=i.
   Relocate(h+1→h) establece el siguiente hueco exactamente en h+1. El chequeo
   h<tail implica h+1<=tail, sin overflow. La única salida h>=tail, junto con
   el avance unitario y la cota, implica h==tail.

10. **Dirección.** Las únicas transferencias admitidas son i+1→i,
    i+2→i+1, …, tail→tail-1. Invertir source/destination, usar tail como
    origen fijo, omitir un paso o repetirlo es rechazado. Mover hacia atrás
    sobrescribiría un objeto todavía vivo y no satisface la prueba.

11. **Autoridad del solapamiento.** La prueba pertenece al CFG de MIR/SSA:
    cada SingleSlot Relocate requiere el hueco raw de la iteración actual.
    No se introduce una operación opaca memmove ni un contrato de byte-copy
    como autoridad de ownership. No hay bitmap ni MemorySSA.

12. **Take.** Se reutiliza sin cambiar TakeState ni crear otro primitivo.
    Produce un único resultado antes del bucle, transferido después una vez
    si T no es Copy. El loop no extrae ni duplica resultados propietarios.

13. **Relocate.** Se reutilizan SlotPlace, SingleSlot, los estados V19 y el
    glue derivado no atrapante. Source pasa Initialized→Uninitialized y
    destination Uninitialized→Initialized. No hay source Drop, deep copy ni
    nuevas capacidades. HoleNext sólo expresa aritmética interna acotada;
    no es una segunda extracción ni transferencia de ownership.

14. **Prueba del prefijo.** La inducción termina con `[0,tail)` Initialized
    y tail Uninitialized. Sólo entonces length=tail se vuelve autoritativo.
    La forma cerrada de bloques/entradas/aristas excluye efectos observables,
    operaciones atrapantes o salidas laterales mientras existe un hueco.

15. **Efecto e invalidación.** StructuralMutation::Remove corresponde a
    StableStructuralMutation. HIR lleva InvalidationShape::SuffixFrom, cuyo
    índice es el campo index de la operación. El conjunto invalidado es el
    sufijo antiguo `[i,N)`, independiente de la estabilidad del backing.

16. **Préstamos de prefijo.** Una referencia directa constante j sobre el
    mismo root sobrevive si j<i es demostrable con índices constantes. No se
    necesita conocer N para esa desigualdad; también funciona alrededor de
    un bucle de remove(x,1) que conserva &x[0]. No se invalida todo el List
    por mover objetos posteriores.

17. **Préstamos de sufijo.** Se rechazan ref/ref mut al removido y a cualquier
    slot desplazado j>i, incluido el antiguo tail. El valor puede sobrevivir
    pero su dirección cambia. Se comprueban también préstamos temporales de
    argumentos anteriores y operaciones a través de aliases escribibles.

18. **Índices dinámicos/desconocidos.** Si no se prueba borrowed_index <
    removal_index se rechaza conservadoramente. Se reutilizan literales y
    hechos de longitud existentes, sin teoremas aritméticos ni pruebas runtime.
    Las consultas/operaciones posteriores reciben longitud actualizada o
    desconocida según la política previa de aliases, joins y backedges.

19. **View/ViewMut.** Las vistas completas bloquean remove mientras están
    vivas; su fin de alcance restaura la legalidad. La cobertura incluye ambas
    vistas y su liberación léxica. No se añaden vistas por subrangos.

20. **Genéricos.** Funciona `T removeAt<T: Storable + Relocatable>(ref mut
    List<T> values, usize i) { return remove(*values,i); }`, con comprobación
    paramétrica previa a monomorfizar e inferencia de T propietario. Faltar
    cualquiera de las garantías sigue siendo un error. No hay diccionarios
    ni otra representación runtime de capacidades.

21. **Copy.** Int usa exactamente los mismos estados de vida de slots que
    los propietarios. Que el resultado sea duplicable no autoriza mantener
    semánticamente vivo el antiguo tail ni duplicar un elemento del sufijo.

22. **Elementos propietarios.** Buffer, Array y List transfieren sus
    descriptores sin copiar los datos. Resultado y supervivientes retienen
    propietarios únicos; los contadores de heap y la limpieza condicional
    comprueban ausencia de pérdidas y doble destrucción.

23. **Anidados y agregados.** Fixtures de List<Array<int>>, List<List<int>>,
    List<Dataset> con Buffer y List<enum propietario>. Se incluyen campos List,
    List interior a otro List, un Array de Owner con campo List, aliases,
    move/return del descriptor y uso de sus valores después de remove.
    La procedencia anidada ambigua conserva la sobre-restricción de V19.

24. **HIR.** ListRemove conserva source Place, index resuelto, element_type,
    effect e invalidation. Se sustituye genéricamente y se verifica tipo,
    escritura, índice, efecto y forma de invalidación. No queda una llamada
    ordinaria sin resolver debajo de HIR.

25. **MIR.** CFG explícito de bounds, trap, Take, inicialización del hueco,
    header, cuerpo creciente y commit. HoleNext produce el sucesor usize bajo
    la prueba del header. El hueco tiene sólo dos definiciones estáticas: la
    semilla y la actualización. Los otros temporales de transacción son
    definiciones únicas no aliasables.

26. **Verificador MIR.** Reconoce el CFG completo y prueba base, paso y
    salida. Comprueba roots, estados, operandos frescos, bound estricto,
    successor, update, precedencias exactas y commit. Rechaza HoleNext o
    Relocate fuera de una transacción verificada. Las 40 corrupciones cubren
    identidades, huecos, direcciones, pasos, trapping, Drop y aristas, sin
    reducir la validez a contar instrucciones.

27. **SSA.** Conserva las mismas operaciones y slots. El único phi del header
    fusiona usize de la semilla con el resultado de la actualización del
    backedge. El Take propietario es una definición externa al bucle y no
    necesita phi. Los roots mutados siguen en memoria selectiva.

28. **Verificador SSA.** Inspecciona independientemente su CFG y sus
    operandos, sin confiar en VerifiedMir para aceptar una corrupción. Exige
    un único phi de hueco con las dos entradas exactas y no permite phis en
    entrada, cuerpo o commit. La verificación de Take mantiene transferencia
    única no-Copy antes de phis. Se prueban 40 corrupciones de transacción
    más cinco de phi: entrada/backedge obsoletos, phi ausente/duplicado y
    propietario indebidamente fusionado en el commit.

29. **LLVM.** Emite comparación de bounds, TailIndex, Take, phi usize,
    comparación hole<tail, add probado seguro, GEP origen/destino, llamada al
    glue tipado y store final de longitud. El contador aumenta una vez por
    iteración. No se añaden allocator/free, source Drop ni memmove a remove.
    La prueba de proyecciones verifica también ausencia de helpers de índices,
    traps, alloc/free y Drop desde el sucesor hasta el commit.

30. **Frescura del descriptor.** Los roots address-taken se consultan desde
    memoria. Para un target proyectado se resuelve su dirección con Borrow
    antes del guard y se usa un dereference estable durante la transacción;
    MIR interna su TypeId ref mut canónico cuando hace falta. Los verificadores
    rechazan proyecciones pendientes en roots remove. Se prueban aliases,
    longitudes después de mutar, moves/returns, campos, listas anidadas y
    secuencias combinadas remove/pop/swap_remove/push/remove. Un índice que
    ejecuta pop en el mismo List demuestra que el bounds usa longitud fresca.

31. **Asignaciones/liberaciones.** Probes antes de Take y después de cada
    commit comparan puntero, capacidad, alloc y free; los cuatro permanecen
    iguales en los quince fixtures. Las cantidades completas de cada programa
    incluyen creación, reserve y limpieza ordinaria:

    | Fixture `v20_remove_…` | Alloc | Free | Relocate total |
    |---|---:|---:|---:|
    | int | 1 | 1 | 2 |
    | first | 1 | 1 | 3 |
    | middle | 1 | 1 | 2 |
    | last | 1 | 1 | 0 |
    | single | 1 | 1 | 0 |
    | buffer | 5 | 5 | 2 |
    | array | 4 | 4 | 1 |
    | nested | 5 | 5 | 4 |
    | dataset | 4 | 4 | 2 |
    | enum | 3 | 3 | 3 |
    | reuse | 5 | 5 | 4 |
    | return | 3 | 3 | 1 |
    | consume | 3 | 3 | 1 |
    | conditional | 10 | 10 | 5 |
    | tail | 3 | 3 | 0 |

32. **Relocalizaciones.** Cada probe exige delta = nueva_longitud − índice,
    equivalente a N-i-1. First/middle/last/single distinguen 3/2/0/0 para los
    casos requeridos. Nested y conditional incluyen extracciones repetidas y
    bucles. En reuse, tres relocalizaciones son del reserve y una de remove;
    el push posterior no requiere otra asignación ni relocalización.

33. **Preservación de datos.** Los fixtures comprueban resultado, longitud,
    capacidad y secuencia ordenada completa para int; payloads, tags activos
    y campos para propietarios. Buffer valida `{10,30,40}` tras devolver 20.
    Se verifica evaluación única del índice con un contador de llamadas.

34. **Drop order.** Instrumentar free registra payloads de los cuatro Buffers
    y exige 20403010: resultado 20, luego 40,30,10 en reverse FINAL indices.
    El tail raw no se limpia. Se cubren retorno, consumo directo, movimiento
    condicional y extracción completa en bucle, con guard de balance y
    cantidades exactas de asignación/liberación.

35. **Diagnósticos.** E0322 identifica target no-List/no escribible, aridad o
    type arguments inválidos; E0323 identifica ref/view al sufijo o relación
    desconocida. Índices siguen los errores ordinarios de tipo usize y las
    garantías genéricas usan E0310. El trap reutiliza IndexOutOfBounds. Los
    errores internos son E0300/Phase::Mir y E0400/Phase::Ssa con detalle de
    transacción, hueco, phi o estados.

36. **Dumps.** Compilaciones repetidas producen HIR/MIR/SSA/LLVM iguales.
    HIR muestra ListRemove, StableStructuralMutation y SuffixFrom. MIR/SSA
    muestran Take, HoleNext, SingleSlot Relocate, estados y ListSetLength;
    SSA expone el phi de control. LLVM retiene el loop creciente y comentarios
    del sucesor probado y de las transiciones. Los dumps no contienen
    metadatos de medición no deterministas.

37. **Pruebas exactas.** `cargo test --workspace --no-fail-fast` desde
    compiler-next: **153 pruebas, cero fallos** (7 backend, 20 frontend,
    22 middle, 104 integración). V0..V19 siguen verdes. Las once V20 son:

    | Prueba | Cobertura |
    |---|---|
    | vertical20_remove_native_owners_and_exact_counts | quince fixtures, módulo, valores y contadores |
    | vertical20_remove_diagnostics | targets, índices, garantías, sufijo, unknown/dynamic, aliases, vistas y nested |
    | vertical20_scopes_aliases_and_descriptor_freshness | scopes, prefijo, loops, índice con efecto y descriptores alias/proyectados |
    | vertical20_bounds_trap_before_transaction | vacío Copy/owner, length y usize máximo |
    | vertical20_deterministic_semantic_dumps | determinismo y contratos de las cuatro capas |
    | vertical20_each_remove_preserves_storage_heap_and_relocation_counts | probes por operación en quince fixtures |
    | vertical20_drop_order_uses_reverse_final_indices | secuencia exacta 20,40,30,10 |
    | vertical20_mir_rejects_corrupt_shift_transactions | 40 corrupciones MIR |
    | vertical20_ssa_rejects_corrupt_shift_transactions | las mismas 40 corrupciones SSA |
    | vertical20_ssa_rejects_hole_and_owner_phi_corruption | cinco corrupciones de phi |
    | vertical20_projected_descriptor_is_resolved_before_hole_exists | dirección resuelta antes de transacción; ningún índice/trap oculto |

    `cargo clippy --workspace --all-targets -- -D warnings`,
    `cargo fmt --all -- --check` y `git diff --check` pasan.

38. **Tiempos.** Metodología V17..V19: debug, un proceso por build, un warmup
    descartado y diez muestras por fixture. Core suma ocho timers desde parse
    hasta LLVM; excluye startup, discovery, I/O, dumps y clang/link. Los detalles
    frontend inclusivos no se suman otra vez. Sin compilaciones concurrentes
    de esta tarea durante la medición. Linux x86_64, rustc 1.97.1, clang 22.1.8.
    Baseline V19 reconstruido por separado desde
    `062fce6b47af75489ec128e263e721ec8d3903af` en `/tmp`.

    | Compilador / fixture | Core media ms | Core mediana ms |
    |---|---:|---:|
    | V19 original / swap_remove Buffer | 1.844 | 1.792 |
    | V20 / swap_remove Buffer | 1.508 | 1.367 |
    | V20 / remove int first | 1.381 | 1.364 |
    | V20 / remove int middle | 1.556 | 1.438 |
    | V20 / remove int tail | 1.517 | 1.407 |
    | V20 / remove Buffer | 1.460 | 1.349 |
    | V20 / remove nested | 1.975 | 1.926 |
    | V20 / remove Dataset | 1.561 | 1.516 |
    | V20 / remove enum | 2.019 | 1.957 |
    | V20 / remove+push reuse | 1.597 | 1.496 |

    Son snapshots de compilación con variación de host/caché y builds separados,
    no afirmaciones de mejora estadística ni benchmarks de tiempo runtime.
    Runtime se califica con cantidades exactas de transferencias y heap.
    [JSON completo](../../compiler-next/tests/timings/v20-debug.json) y
    [script](../../compiler-next/tests/measure-v20.py). Reproducir desde
    compiler-next con `python3 tests/measure-v20.py --runs 10`, opcionalmente
    `--baseline-binary <v19> --baseline-revision <revision>`.

39. **Legacy.** `tests/run-differential.sh`: **21 comparaciones ejecutables,
    cero fallos**. No se modifican compiler-rs, runtime/CLI legacy ni archivos
    de scrap. Los binarios FaCAether/FaCAetherO0 preexistentes permanecen ajenos
    al cambio. No se creó commit ni se publicó nada.

40. **Deuda aceptada.** Procedencia léxica/nested conservadora; no hay análisis
    de último uso, vistas por rangos ni pruebas dinámicas de desigualdad. Los
    helpers con referencias mutables conservan sus efectos interprocedurales
    conservadores. La prueba admite una forma CFG cerrada y futuros pases
    deberán preservarla o ampliarla. Roots selectivos en memoria, temporal
    de Take para agregados, ABI bootstrap y admisión estrecha de Buffer siguen
    vigentes. No se incorporan optimizaciones ni generalización de slots.

41. **OPEN DECISIONS.** El orden, bounds, invalidación, dirección y coste de
    remove quedan resueltos. Siguen abiertas una futura API opcional de
    biblioteca, precisión de procedencia/rangos, efectos de helpers, promoción
    de descriptores, ABI pública y propietarios sensibles a dirección. No
    bloquean este contrato ni introducen Option, lifetimes o métodos.

42. **Problemas arquitectónicos descubiertos.** El diamante V19 no podía
    justificar solapamiento repetido; V20 añade una prueba inductiva explícita
    y una única variable de control, sin generalizar ownership a phis. Un Add
    fuente implicaría un trap dentro del hueco; HoleNext tiene autoridad
    solamente bajo hole<tail. Las proyecciones generaban repetidos helpers
    de bounds al releer List: materializar la dirección antes del guard elimina
    ese efecto oculto. El predicado de préstamos V19 dependía del tail; para
    remove basta j<i y se conserva el prefijo incluso con longitud desconocida.

43. **Recomendación NEXT-VERTICAL-21.** Considerar una única inserción
    ordenada, con contrato index<=length, invalidación del sufijo y crecimiento
    previo a abrir huecos. Necesita una prueba independiente de desplazamiento
    hacia la derecha en orden decreciente, inicialización del nuevo slot y
    commit final, además de transferencia del argumento sin pérdidas si la
    preparación falla. No reutilizar la dirección creciente de remove como
    autoridad automática. Mantener drain, rangos y lifetimes separados. V20
    no implementa insert ni ninguna de esas extensiones.
