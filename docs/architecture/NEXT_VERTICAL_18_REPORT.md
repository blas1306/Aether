# NEXT-VERTICAL-18 — initialized storage slots, owning extraction, and List pop

Implementado en el compilador aislado `compiler-next`, Linux x86_64.
Cierre: 2026-09-07. `pop(list)` llega a ejecución nativa para elementos Copy y
propietarios, con extracción explícita y prefijo inicializado verificable.

1. **Modelo inicial.** V17 representaba el prefijo inicializado mediante
   longitud, `PlaceProjection::Index` comprobaba índices lógicos y `Relocate`
   describía estados de almacenamiento durante crecimiento. No existía una
   operación para extraer un elemento hacia un resultado ordinario. Se conservan
   esas distinciones y se agrega autoridad explícita para el slot final.

2. **Archivos cambiados.** Rutas relativas a la raíz:

   | Archivo | Responsabilidad |
   |---|---|
   | `compiler-next/crates/aether-frontend/src/hir.rs` | ListPop, efectos, resolución, sustitución, procedencia y validación |
   | `compiler-next/crates/aether-frontend/src/types.rs` | consulta conservadora de List dentro de agregados para efectos de llamadas |
   | `compiler-next/crates/aether-frontend/src/lib.rs` | exportación de MutationEffect |
   | `compiler-next/crates/aether-middle/src/mir.rs` | SlotPlace, TakeState, PushInit, CFG, propiedad y verificación |
   | `compiler-next/crates/aether-middle/src/ssa.rs` | preservación de operaciones, operandos y verificación independiente |
   | `compiler-next/crates/aether-middle/src/lib.rs` | exportación del modelo de slots |
   | `compiler-next/crates/aether-backend-llvm/src/lib.rs` | extracción, commit de longitud, temporales y nombres de cargas proyectadas |
   | `compiler-next/crates/aether-driver/tests/vertical.rs` | ocho pruebas V18 y expectativa específica para rechazo de pop(Array) |
   | `compiler-next/tests/programs/v18_pop_{int,buffer,nested,reuse,owners,conditional}.ae` | seis fixtures nativos |
   | `compiler-next/tests/modules/v18_pop/{main,storage}.ae` | helper genérico entre módulos |
   | `compiler-next/tests/modules/v1-contract.tsv` | registro del nuevo módulo |
   | `compiler-next/tests/measure-v18.py` | medición reproducible con baseline opcional |
   | `compiler-next/tests/timings/v18-debug.json` | resultados completos por fase |
   | `compiler-next/README.md` | sintaxis, invariantes, límites y metodología |
   | `docs/architecture/AETHER_V1_LANGUAGE_CHARTER.md` | alcance V18 |
   | `docs/architecture/AETHER_V1_SEMANTIC_CONTRACT.md` | contrato normativo, sección 6.5 |
   | `docs/architecture/AETHER_COMPILER_ARCHITECTURE.md` | implementación, sección 35 |
   | `docs/architecture/NEXT_VERTICAL_18_REPORT.md` | este informe |

3. **Sintaxis.** `T last = pop(values);`, `return pop(*values);`,
   `consume(pop(values))` y construcción como `Dataset(pop(values), 1)`.
   El argumento es un Place List escribible. No hay auto-deref ni métodos.
   Se conserva la restricción de sentencias de efecto: un resultado de pop se
   usa en una expresión; `pop(values);` aislado no agrega descarte implícito.

4. **Vacío.** `ListEmpty` es un trap estructurado no recuperable, sin unwind.
   Un List vacío sigue llegando al chequeo dinámico, incluso cuando su literal
   es `{}`. No hay Option mágico ni try_pop. Una API opcional de biblioteca
   puede diseñarse independientemente.

5. **Representación del slot.** `SlotPlace<P,O>` contiene `root`, `index` y
   `type_id`. MIR lo especializa con Place/Operand y SSA con SsaPlace/SsaOperand.
   El root identifica el Place del descriptor propietario. El slot no es un
   valor fuente ni un `PlaceProjection::Index` ordinario. Push mantiene su
   operación semántica y explicita `PushInit` sobre el slot raw de la longitud
   anterior; no usa indexación fuente para acceder a capacidad reservada.

6. **Estados.** `ElementInitialization::{Initialized, Uninitialized}` describe
   el estado semántico; `TakeState` exige Initialized → Uninitialized y
   transferencia no atrapante. `PushInit` exige la transición inversa. Longitud
   representa exactamente el prefijo vivo en ejecución, sin bitmap ni flag de
   drop por slot. Los bits antiguos pueden permanecer físicamente en memoria;
   no representan una segunda instancia viva.

7. **Take.** `Rvalue::Take`/`SsaOp::Take` produce T y termina la inicialización
   del slot. Los verificadores exigen que sea la única extracción dentro de una
   transacción comprobada. Un origen raw, segunda extracción, estado final vivo,
   índice/root incorrecto, transferencia atrapante o commit ausente se rechaza.

8. **Take frente a Move.** Move sigue transfiriendo un root del lenguaje a otro
   propietario y marca su origen Moved. Take produce un resultado propietario
   desde almacenamiento interno; el antiguo tail deja de ser elemento de List.
   Los movimientos posteriores del resultado usan el Move normal.

9. **Take frente a Relocate.** Relocate transfiere entre ubicaciones de
   almacenamiento. Take entrega un resultado ordinario. El glue físico de
   agregados puede reutilizar Relocate sin borrar esta diferencia en MIR/SSA.
   Pop no incrementa el contador de elementos relocalizados por crecimiento.

10. **Orden del chequeo.** El bloque previo termina con lectura fresca de
    ListLength, comparación con cero y Branch. La arista vacía termina en
    ListEmpty y no contiene instrucciones. La arista positiva entra en
    TailIndex, Take y ListSetLength contiguos. TailIndex resta uno sin underflow
    porque su autoridad es esa arista. Los verificadores comprueban la
    correspondencia real de operandos y CFG, además de los metadatos.

11. **Longitud y capacidad.** ListSetLength escribe exclusivamente N−1 en el
    campo longitud. No cambia capacidad/puntero, no encoge, no libera y no mueve
    supervivientes. El commit debe usar exactamente el índice extraído.

12. **Clasificación de efectos.** `MutationEffect` distingue ElementMutation,
    StableStructuralMutation y PotentiallyRelocatingMutation. Asignación de elementos
    expone la primera mediante `HirStmtKind::mutation_effect`; pop lleva la
    segunda en HIR; `StructuralMutation::Push/Reserve.effect()` devuelve la
    tercera. No se implementó un sistema general de efectos.

13. **Referencias al prefijo.** Un préstamo directo de índice constante i
    sobre un List de longitud conocida N sobrevive si i < N−1. Funciona con
    referencias compartidas y con aliases conocidos del descriptor. Los hechos
    de longitud provienen del literal y se actualizan tras pop; reserve conserva
    la longitud. Push, longitudes divergentes entre ramas, backedges de List y
    llamadas escribibles hacen conservadora la prueba. Los bucles conservan
    los hechos de longitud fija de Array/Buffer.

14. **Referencia al tail.** Tanto `ref` como `ref mut` al elemento removido
    bloquean pop mientras permanezcan vivos léxicamente. Una secuencia de pops
    vuelve a comprobar el límite: una referencia que sobrevivió al primero
    puede bloquear el segundo.

15. **Índice desconocido.** Si el índice o la longitud no permiten demostrar
    exclusión del tail, se rechaza E0319. No se hace una prueba aritmética
    general ni se confunde estabilidad del puntero con existencia del objeto.

16. **View/ViewMut.** Una vista completa captura el antiguo prefijo y bloquea
    pop. Terminado el bloque que contiene la vista, vuelve a permitirse.
    Los tests usan bloques de `if`, ya admitidos por la gramática, para comprobar
    fin de alcance. No se agregaron slices o vistas de subrangos.

17. **Genéricos.** Funciona
    `T popLast<T: Storable + Relocatable>(ref mut List<T> values)` con
    `return pop(*values);`. Se verifica antes de monomorfizar y el glue aparece
    para cada tipo concreto. Las restricciones faltantes se diagnostican al
    validar List<T>; no hay dispatch de capacidades en ejecución.

18. **Copy.** Pop de int devuelve el valor y reduce el prefijo de la misma
    forma que un elemento propietario. El tail se vuelve Uninitialized aunque
    la copia de int sea permitida en usos posteriores del resultado.

19. **No-Copy.** Buffer/Array/List transfieren únicamente su descriptor. Su
    pointee sigue perteneciendo al valor extraído y no se copia ni libera.
    El List conserva la propiedad de los elementos restantes.

20. **Anidados y agregados.** Ejecución nativa de List<Buffer<int>>,
    List<Array<int>>, List<List<int>>, List<Dataset> y enum con Buffer,
    incluidas variantes sin payload. Hay extracción desde un campo List y
    desde un List anidado sin préstamos. La procedencia anidada con préstamos
    se mantiene conservadora.

21. **HIR.** ListPop contiene Place, TypeId de elemento y efecto estable. La
    aplicación deja de ser una llamada sin resolver. Sustitución genérica y
    síntesis de propiedad conservan el resultado en binding/return/argumento/
    agregado. Se exige capacidad de escritura.

22. **MIR.** Hay CFG explícito de vacío, TailIndex, Take y commit. Los
    temporales de la transacción tienen definiciones únicas y no son aliases.
    La propiedad del resultado entra en el análisis normal de owners. La
    verificación acotada exige una transacción contigua sobre un prefijo válido;
    no pretende probar secuencias arbitrarias de inicialización parcial.

23. **SSA.** Conserva SlotPlace y Take, sin convertir una extracción propietaria
    en Use duplicante. Verifica independientemente la forma del CFG, los
    estados, root, índice y commit. El temporal extraído no-Copy debe transferirse
    una vez antes de llegar a un phi. Los errores por Drop proyectado de un slot
    y las transiciones corruptas de PushInit siguen fallando antes de LLVM.

24. **LLVM.** Emite chequeo cero, resta, GEP del tail y carga de escalares/
    descriptores. Structs y enums reutilizan glue recursivo de relocalización;
    el resultado usa un temporal de stack en entry, sin asignación de heap
    ni alloca repetido por iteración. Luego se escribe sólo longitud. No hay
    llamada a asignador, free o drop del origen dentro de la extracción.

25. **Frescura del descriptor.** Los roots afectados por pop usan la frontera
    de memoria selectiva existente; los otros locales continúan promovidos.
    Las referencias, consultas posteriores, movimientos/retornos de List y drop
    leen la longitud actual. Este diseño evita versiones SSA obsoletas sin
    introducir MemorySSA; promover nuevamente esos descriptores queda diferido.

26. **Limpieza una vez.** El tail sale del intervalo recorrido por drop y el
    resultado recibe su limpieza ordinaria si no se consume. Hay pruebas de
    retorno directo, consumo como argumento, agregados, owners restantes,
    transferencia condicional por ambas ramas y extracción repetida en bucle.
    Los flags condicionales existentes siguen siendo de roots, nunca del tail.

27. **Asignaciones/liberaciones exactas.** Instrumentación nativa de los
    contadores existentes; cada fixture retorna cero con el guard de balance:

    | Fixture | Asignaciones | Liberaciones | Relocalizaciones por crecimiento |
    |---|---:|---:|---:|
    | v18_pop_int | 1 | 1 | 0 |
    | v18_pop_buffer | 4 | 4 | 0 |
    | v18_pop_nested | 3 | 3 | 0 |
    | v18_pop_reuse | 4 | 4 | 2 |
    | v18_pop_owners | 14 | 14 | 0 |
    | v18_pop_conditional | 8 | 8 | 0 |

    Se inyectan además probes exclusivamente de test antes del Take y después
    del commit: comparan puntero, capacidad, asignaciones y liberaciones.
    Cada pop conserva los cuatro. El fixture condicional ejecuta ambas ramas
    y un bucle propietario; no depende sólo de una inspección textual.
    V17 conserva 67/67 y 56 relocalizaciones; V16 conserva 43/43 y 12.

28. **Pop + push.** Reserve a capacidad 8, pop de Buffer y push del mismo owner
    reutilizan el slot raw. Las cuatro asignaciones totales son dos Buffers,
    el List inicial y el reserve. Las dos relocalizaciones pertenecen al reserve;
    el pop y el push posterior no agregan backing allocations.

29. **Diagnósticos.** E0318: argumento/target inválido o de sólo lectura;
    E0319: referencia/vista viva que puede cubrir el tail; E0313: llamada
    escribible potencialmente invalidante. Se conservan E0310 para requisitos
    de List<T>, E0300/Phase::Mir y E0400/Phase::Ssa para verificación interna.
    El test V13 de `pop(Array)` sigue rechazado y actualiza E0212 (nombre antes
    inexistente) a E0318 (operación conocida, tipo no permitido).

30. **Dumps.** Se comprueba igualdad entre compilaciones repetidas. HIR muestra
    ListPop y StableStructuralMutation; MIR/SSA muestran TailIndex, SlotPlace,
    TakeState Initialized → Uninitialized, ListEmpty y ListSetLength.
    Push muestra PushInit. LLVM conserva comentarios de transición y commit
    además de las operaciones físicas y el trap estructurado.

31. **Pruebas exactas.** `cargo test --workspace --no-fail-fast`: **133 pruebas,
    cero fallos** (7 backend, 20 frontend, 22 middle, 84 integración).
    Las ocho nuevas pruebas de integración son:

    | Prueba | Cobertura |
    |---|---|
    | vertical18_pop_native_owners_and_exact_counts | seis fixtures, resultados, asignaciones/frees/relocaciones y módulo |
    | vertical18_pop_borrow_and_capability_diagnostics | shared, tail, mutable tail, unknown, vistas, anidados, pops repetidos, loops, capacidades, argumentos y aliases de llamadas |
    | vertical18_pop_scopes_aliases_loops_and_conditional_cleanup | fin de préstamos/vistas, prefijo, aliases, bucles, retorno de descriptor y extracción proyectada |
    | vertical18_empty_pop_traps_before_extraction | vacío dinámico int y propietario, MIR/SSA y trap nativo |
    | vertical18_dumps_retain_slot_ownership_and_stable_effect | determinismo y contratos de las cuatro capas |
    | vertical18_verifiers_reject_corrupt_extraction_transactions | diez corrupciones MIR y diez SSA: estado raw/vivo, doble Take, commit ausente/incorrecto, índice obsoleto, orden, chequeo/Use inválido, trapping y Drop del slot |
    | vertical18_each_pop_preserves_pointer_capacity_and_heap_counters | probes ejecutables por pop en seis fixtures |
    | vertical18_push_reinitialization_and_effect_contracts | categorías de efectos y corrupción de PushInit en MIR/SSA |

    `cargo clippy --workspace --all-targets -- -D warnings`,
    `cargo fmt --all -- --check` y `git diff --check` pasan.

32. **Tiempos.** Se conserva exactamente la metodología V17: driver debug,
    proceso nuevo por build, un calentamiento descartado y diez muestras por
    fixture. Core suma parse, declaraciones, semántica, MIR lower/verify,
    SSA build/verify y LLVM. Excluye startup, descubrimiento, I/O, dumps y
    clang/link. Los detalles frontend siguen siendo inclusivos, no aditivos.
    Linux x86_64, rustc 1.97.1 y clang 22.1.8; no había otra compilación de esta
    tarea durante la medición. V17 se reconstruyó por separado desde
    `1f8077d767e3d9310f09a84759aca300c8f2daf3` en `/tmp`.

    | Compilador / fixture | Core media (ms) | Core mediana (ms) |
    |---|---:|---:|
    | V17 original / v17_storable | 8.959 | 8.078 |
    | V18 / v17_storable | 7.310 | 7.171 |
    | V18 / v18_pop_buffer | 1.409 | 1.319 |
    | V18 / v18_pop_int | 1.216 | 1.141 |
    | V18 / v18_pop_nested | 1.188 | 1.147 |
    | V18 / v18_pop_reuse | 1.216 | 1.056 |

    Son snapshots debug y builds separados, con variabilidad de host/caché;
    no se atribuye una optimización ni una mejora estadística a las diferencias.
    [JSON completo](../../compiler-next/tests/timings/v18-debug.json) y
    [script reproducible](../../compiler-next/tests/measure-v18.py).
    Ejecución desde `compiler-next` tras `cargo build -p aether-driver --bin
    aether-next`: `python3 tests/measure-v18.py --runs 10`, opcionalmente con
    `--baseline-binary <binario-v17> --baseline-revision <revision>`.

33. **Legacy.** Comparación ejecutable: **21 casos, cero fallos** mediante
    `tests/run-differential.sh`. No se modificaron el compilador legacy,
    `compiler-rs`, runtime, CLI de producción ni los archivos del usuario en
    `scrap`. No se creó commit ni se publicó nada. Esto califica compiler-next;
    no promueve automáticamente la nueva implementación a la CLI de producción.

34. **Deuda aceptada.** Procedencia léxica y anidada conservadora; no hay
    precisión de subrangos, último uso ni efecto interprocedural específico de
    pop. Push y llamadas arbitrarias mantienen restricciones conservadoras.
    La verificación de slots admite una forma CFG acotada y contigua; futuros
    pases que la transformen deberán conservarla o extender la prueba. Los
    roots mutados por pop usan memoria y los agregados requieren un temporal
    de stack para el glue. Permanecen ABI bootstrap, límites genéricos y la
    admisión estrecha de Buffer. No se agregan bitmap, optimizador ni MemorySSA.

35. **OPEN DECISIONS.** El resultado vacío de este pop queda resuelto: ListEmpty.
    Siguen abiertos la futura API opcional de biblioteca, rangos/préstamos más
    precisos, promoción de descriptores mutados, construcción de tipos sensibles
    a direcciones, Buffer y ABI público. No condicionan el contrato V18 ni
    introducen silenciosamente Option, lifetimes, métodos o capacidades nuevas.

36. **Problemas arquitectónicos encontrados.** La carga de un descriptor
    proyectado podía colisionar con el nombre LLVM de la carga de su prefijo;
    se incorpora profundidad de proyección al nombre final. Los préstamos
    temporales de argumentos no permanecían vivos al evaluar argumentos
    posteriores y una referencia escribible anterior podía coincidir con un
    préstamo posterior: ahora se mantiene alcance temporal y se comprueba la
    frontera completa de la llamada. `may_contain_list` conserva la distinción
    entre una llamada que puede cambiar List y una que sólo modifica un escalar
    o agregado Copy sin List; estas últimas no invalidan el prefijo. Se descartan hechos de longitud obsoletos
    tras llamadas escribibles y backedges de List. Ninguna corrección supone
    exclusividad `noalias` ni una prueba general de procedencia por capas.

37. **Recomendación NEXT-VERTICAL-19.** Diseñar una única extracción indexada
    acotada, preferentemente swap_remove, definiendo primero la invalidación de
    los dos elementos involucrados y el protocolo de traslado del tail al hueco.
    Reutilizar SlotPlace, Take y Relocate; ampliar la verificación sólo para esa
    transición antes de considerar remove/insert con desplazamiento de sufijos.
    La implementación actual no incluye ninguna de esas operaciones.
