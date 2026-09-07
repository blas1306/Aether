# NEXT-VERTICAL-17 — Storable capability and symbolic collection legality

Implementación en el compilador aislado `compiler-next`. Fecha de cierre:
2026-09-07. El contrato actual admite colecciones simbólicas con garantías
positivas de almacenamiento, conserva la propiedad exclusiva y no introduce
operaciones de capacidades en el programa generado.

1. **Admisión anterior.** V16 usaba `collection_element_admission(TypeId)`:
   pedía Relocatable para Array y List, excluía referencias/views por inspección
   estructural y rechazaba elementos simbólicos con `SymbolicStorageUnknown`.
   Relocatable por sí solo no podía probar la legalidad del almacenamiento.

2. **Archivos cambiados.** El cambio está limitado al compilador nuevo, sus
   pruebas y documentos de arquitectura:

   | Archivo, relativo a la raíz | Cambio |
   |---|---|
   | `compiler-next/crates/aether-frontend/src/types.rs` | Storable, propiedades, requisitos por colección, derivación estructural y mediciones |
   | `compiler-next/crates/aether-frontend/src/hir.rs` | resolución/validación, colecciones simbólicas, diagnósticos, inferencia y correcciones de instanciación |
   | `compiler-next/crates/aether-frontend/src/lib.rs` | exportación de CollectionKind |
   | `compiler-next/crates/aether-middle/src/mir.rs` | auditoría de tipos concretos, separada de metadatos genéricos |
   | `compiler-next/crates/aether-middle/src/ssa.rs` | la misma separación en SSA |
   | `compiler-next/crates/aether-driver/src/lib.rs` | captura del desglose de tiempos antes de dumps y lowering |
   | `compiler-next/crates/aether-driver/tests/vertical.rs` | nueve pruebas V17; conservación de las comprobaciones de temporizadores anteriores |
   | `compiler-next/tests/programs/v17_storable.ae` | integración nativa de propietarios, agregados y colecciones anidadas |
   | `compiler-next/tests/programs/v17_array_storage.ae` | caso pequeño de Array genérico propietario |
   | `compiler-next/tests/programs/v17_list_storage.ae` | caso pequeño de List genérico con crecimiento |
   | `compiler-next/tests/modules/v17_storable/{main,storage}.ae` | restricciones y colecciones entre módulos |
   | `compiler-next/tests/modules/v1-contract.tsv` | registro del nuevo caso entre módulos |
   | `compiler-next/tests/measure-v17.py` | medición reproducible, con alcance explícito |
   | `compiler-next/tests/timings/v17-debug.json` | snapshot completo de medias y medianas |
   | `compiler-next/README.md` | gramática, contrato actual, tabla de propiedades y metodología |
   | `docs/architecture/AETHER_V1_LANGUAGE_CHARTER.md` | confirmación del alcance V17 |
   | `docs/architecture/AETHER_V1_SEMANTIC_CONTRACT.md` | contrato normativo, sección 10.7 |
   | `docs/architecture/AETHER_COMPILER_ARCHITECTURE.md` | confirmación de implementación, sección 34 |
   | `docs/architecture/NEXT_VERTICAL_17_REPORT.md` | este informe |

3. **Definición de Storable.** Una instancia de T puede persistir como
   subobjeto o elemento de almacenamiento propietario sin introducir una
   dependencia de préstamo/lifetime que el modelo actual no pueda representar.
   No significa duplicable, sin destrucción, tamaño conocido ni borrado de
   lifetimes.

4. **Representación.** `Capability::{Copy, Relocatable, Storable}` sigue siendo
   un conjunto cerrado, derivado por el compilador. Las restricciones son
   garantías exigidas a los argumentos; no son implementaciones aportadas por
   el usuario. No se agregó sintaxis `impl`.

5. **Implicaciones.** La única implicación entre capacidades distintas sigue
   siendo `Copy => Relocatable`. Storable no implica Copy ni Relocatable; Copy
   y Relocatable tampoco implican Storable. Las pruebas de propiedades recorren
   todas las combinaciones de la matriz de implicaciones.

6. **TypeProperties concretas.** Se agrega `is_storable`, independiente de
   `is_known`, `is_copy`, `is_relocatable` y `needs_drop`. Los escalares son
   Copy/Relocatable/Storable sin drop. Buffer/Array/List de int son
   no-Copy/Relocatable/Storable y requieren drop. Referencias y views son
   Copy/Relocatable sin drop, pero no Storable. Los resultados concretos se
   almacenan en la caché existente; las consultas desconocidas fallan de forma
   conservadora.

7. **Structs.** Storable se deriva de todos los campos sustituidos.
   `Dataset { Buffer<int> values; int count; }` lo satisface. Los tests directos
   del arena también verifican que un struct con un campo prestado no lo
   satisface, independientemente del rechazo previo de esos campos en fuente.

8. **Enums.** Se requiere Storable en todos los payloads de todas las
   variantes, incluidas las inactivas. Un solo payload prestado impide derivar
   la capacidad para todo el enum. Los propietarios de Buffer mantienen drop
   recursivo únicamente para la variante activa.

9. **Garantías simbólicas.** `guarantees_storable` integra la consulta general
   `guarantees_capability`. `Holder<T>` y `Maybe<T>` derivan Storable con
   `T: Storable`, Relocatable con `T: Relocatable`, y ambas cuando ambas se
   garantizan. La sustitución de propiedades evalúa argumentos en el entorno
   exterior antes de asociarlos al parámetro del agregado; esto evita capturas
   en `Holder<Holder<T>>`.

10. **GenericParam.** Las capacidades permanecen en `GenericParamInfo`, con
    identidad `GenericParamId { owner, index }`, sin cambiar TypeId. Un parámetro
    Storable sigue teniendo propiedades concretas desconocidas, sin hechos
    globales de Copy/Relocatable/Storable y con potencial necesidad de drop.
    La capacidad declarada se consulta exclusivamente como garantía simbólica.

11. **Sintaxis y resolución.** Funcionan `T: Storable`,
    `T: Relocatable + Storable` y `T: Copy + Storable` mediante la gramática
    existente. Hay validación en llamadas explícitas, inferidas, forwarding,
    structs y enums restringidos, antes de solicitar InstanceId. La prohibición
    V9 de argumentos genéricos prestados se mantiene, pero se comprueba después
    de las capacidades para producir el diagnóstico más específico.

12. **Array.** Requiere únicamente `T: Storable` mediante
    `CollectionKind::Array.requirements()`. La construcción literal inicializa
    cada slot final una sola vez desde su valor tipado, sin relocalizar un
    elemento ya inicializado. La transferencia de propiedad de un valor fuente
    es Move, distinta de Relocate sobre objetos almacenados. No fue necesario
    alterar el lowering LLVM de Array. El futuro soporte de tipos sensibles a
    direcciones deberá definir construcción/ABI apropiados antes de admitirlos;
    V17 no implementa esos tipos.

13. **List.** Requiere `T: Storable + Relocatable`. La misma API central
    distingue `MissingStorable` de `MissingRelocatable`. La primera capacidad
    autoriza almacenamiento y la segunda el traslado de elementos inicializados
    durante crecimiento. Copy no forma parte de esta admisión.

14. **Array simbólico.** Funciona `Array<T> a = {value}` con `T: Storable`,
    incluso en firmas, tipos nominales restringidos y llamadas entre módulos.
    El programa nativo instancia este camino con Buffer y agregados propietarios.

15. **List simbólico.** Funcionan literal vacío/no vacío, push y reserve bajo
    ambas garantías. La comprobación semántica precede a la instanciación; el
    código concreto recibe el glue V16 habitual. Se eliminó el rechazo genérico
    `SymbolicStorageUnknown`.

16. **Literales genéricos.** Los operandos se evalúan en orden fuente. Sin
    garantía Copy, un local usado como elemento se consume y su uso posterior
    falla. Con Copy puede reutilizarse. Los temporales transfieren una única
    propiedad al slot, sin una segunda limpieza del origen.

17. **Push genérico.** Consume T salvo que esté garantizado Copy. El caso
    propietario y la reutilización con Copy se ejecutan nativamente. Los
    préstamos de elementos siguen bloqueando las mutaciones estructurales.
    El crecimiento relocaliza exactamente el prefijo inicializado.

18. **Fill y Copy.** `Array<T>(length, fill)` requiere Storable más Copy.
    `T: Storable` solo produce un error de duplicación. El chequeo anticipado
    de bytes ya no intenta obtener un layout simbólico; cuando depende de T,
    el helper concreto conserva la comprobación de overflow en ejecución.
    No se inventa un tamaño ni se elimina el chequeo de asignación.

19. **Referencias y views.** `ref`, `ref mut`, View y ViewMut son no-Storable.
    Se rechazan las ocho combinaciones con Array/List. Las restricciones
    explícitas e inferidas identifican capacidad, parámetro y tipo real.
    Continúan prohibidos los campos prestados, los retornos prestados y mover
    propietarios con préstamos vivos. No hay relajación de lifetimes.

20. **Anidamiento.** Se ejecutan `Array<Array<int>>`, `Array<List<int>>`,
    `List<Array<int>>`, `List<List<int>>`, `List<Dataset>` y agregados genéricos
    anidados, sin una lista especial de contenedores permitidos. La
    relocalización de un descriptor propietario no relocaliza sus elementos
    alojados en otra asignación.

21. **Buffer.** Se separan dos conceptos: el elemento puede ser Storable y,
    aun así, no ser duplicable por el constructor fill actual. V17 mantiene
    la admisión de fuente V10 concreta Copy/no-drop: Buffer no tiene literal
    propietario y su drop todavía no destruye elementos recursivamente. Es
    una restricción de implementación, no una ley semántica de almacenamiento.
    Opciones futuras: separar admisión de tipo y fill, añadir inicialización
    completa y drop de elementos, o conservar Buffer como sustrato restringido.
    No se amplió Buffer en este cambio.

22. **HIR.** Los dumps muestran parámetros con Storable, propiedades
    concretas, garantías simbólicas, `element_requirements`,
    `element_admission=Admitted` y operandos Move en init/push. El comprobador
    procesa cuerpos genéricos antes de monomorfizarlos. No hay valores de
    capacidades en ejecución.

23. **MIR.** Conserva ArrayInit/ArrayFill/ListInit/ListPush/ListReserve y los
    contratos existentes de Move, Drop y Relocate. La auditoría del arena omite
    metadatos genéricos no ejecutados; las firmas y los locales de ejecución
    siguen exigiendo tipos concretos. Una prueba de mutación introduce un
    Array simbólico en un local y confirma el rechazo.

24. **SSA.** La misma separación conserva la promoción, efectos de memoria y
    verificación de propiedad V16. Se rechaza una instrucción de ejecución con
    tipo de colección simbólica, incluso si sus garantías permitirían la
    colección dentro de una declaración genérica.

25. **LLVM.** No hubo cambios en el backend. No hay operación, helper,
    diccionario, vtable ni despacho Storable. El glue de relocalización y
    destrucción sigue siendo el de V16, generado únicamente para tipos
    concretos. Las capacidades agregan costo al compilador, no al programa.

26. **Diagnósticos.** Se conservan los códigos estructurados existentes:
    E0314 para nombre de capacidad desconocido y, por compatibilidad con V16,
    para fill sin Copy; E0315 para duplicados; E0316 para restricción explícita/
    reenviada/nominal incumplida; E0317 para inferencia exitosa con restricción
    incumplida; E0304/E0310 para admisión de Array/List. Los mensajes distinguen
    almacenamiento, relocalización y duplicación, conservan spans y muestran
    `T`/el tipo canónico en lugar de TypeId cuando se rechaza el elemento directo.
    E0291, E0292, E0313 y los errores V9 de escape siguen activos.

27. **Pruebas exactas.** `cargo test --workspace --no-fail-fast` pasa **125
    pruebas**, sin fallos: 7 de backend, 20 de frontend, 22 de middle y 76 de
    integración del driver. Incluye las 114 anteriores. Las once nuevas son:

    | Prueba | Evidencia principal |
    |---|---|
    | `storable_concrete_properties_are_independent_and_structural` | tabla concreta, propietarios con drop, campos/payloads prestados, fallo conservador |
    | `storable_symbolic_guarantees_do_not_cross_imply_or_become_concrete` | garantías independientes, Holder/Maybe/anidados, Array sin Relocatable, List con ambas |
    | `vertical17_storable_diagnostics_and_parametric_ownership` | 26 casos de error de restricciones, fill, movimiento y lifetimes |
    | `vertical17_hir_retains_guarantees_requirements_and_consumption` | requisitos y Move en HIR; Drop/Relocate en MIR/SSA; borrado en LLVM |
    | `vertical17_symbolic_collections_execute_natively_and_drop_owners` | fixture completo con resultado 0 y módulos con resultado 42 |
    | `vertical17_independent_instances_are_not_expanding_recursion` | aplicaciones independientes finitas; rechazo de expansión recursiva real |
    | `vertical17_all_borrowed_collection_elements_fail_storable` | ocho formas de elementos prestados y restricción inferida |
    | `vertical17_repeated_nominal_binders_derive_storage_without_capture` | Holder<Holder<Buffer<int>>> nativo |
    | `vertical17_exact_cleanup_and_relocation_counts` | 67 asignaciones, 67 liberaciones, 56 relocalizaciones |
    | `vertical17_semantic_detail_timers_have_explicit_scope` | cuatro detalles nuevos y ocho temporizadores core conservados |
    | `vertical17_verifiers_reject_symbolic_collection_runtime_types` | mutaciones inválidas de MIR y SSA |

    `cargo clippy --workspace --all-targets -- -D warnings` y `cargo fmt --all
    -- --check` pasan. La comparación ejecutable con el compilador legacy
    cubre 21 casos con cero diferencias inesperadas. El fixture V16 conserva
    sus contadores 43/43 y 12 relocalizaciones. Los tests incluyen ejecución
    nativa con clang; no se depende de un intérprete para la admisión.

28. **Tiempos.** Se conservan los temporizadores anteriores y se añaden cuatro
    detalles inclusivos: resolución de parámetros/restricciones, derivación
    simbólica, admisión de colecciones y segunda validación nominal. Los límites
    exactos están en el [README](../../compiler-next/README.md#vertical-17-timing-methodology).
    Los detalles se solapan entre sí y con las fases; no se suman al total.
    `constraint_resolution` mide la resolución de binders y nombres, no la
    validación de todas las aplicaciones. Los detalles se capturan después de
    semántica y antes de dumps, MIR, SSA y LLVM.

    El snapshot usa Linux x86_64, `rustc 1.97.1`, `clang 22.1.8`, driver debug
    sin optimización, un proceso nuevo por build, un calentamiento descartado
    por fixture y diez muestras secuenciales posteriores. Core suma únicamente
    lex/parse, declaraciones, cuerpos/monomorfización/layout/HIR verify,
    MIR lower/verify, SSA build/verify y LLVM. Excluye startup, descubrimiento,
    lectura/escritura de archivos, dumps y clang/link. No había otra compilación
    de esta tarea en curso durante la medición. Son snapshots de fixtures de
    distinto tamaño, no una comparación de rendimiento con V15/V16.

    | Fixture | Core media (ms) | Core mediana (ms) | Restricciones¹ | Simbólico¹ | Admisión¹ | Segunda pasada¹ |
    |---|---:|---:|---:|---:|---:|---:|
    | `v15_capabilities.ae` | 3.361 | 3.356 | 0.071 | 0.054 | 0.000 | 0.013 |
    | `v16_owned_collections.ae` | 2.784 | 2.593 | 0.013 | 0.000 | 0.042 | 0.009 |
    | `v17_array_storage.ae` | 0.825 | 0.785 | 0.016 | 0.015 | 0.016 | 0.003 |
    | `v17_list_storage.ae` | 0.941 | 0.924 | 0.021 | 0.022 | 0.022 | 0.003 |
    | `v17_storable.ae` | 7.293 | 7.275 | 0.082 | 0.121 | 0.128 | 0.019 |

    ¹ Medias en milisegundos de detalles inclusivos; se solapan y no se suman a core.

    Se puede reproducir desde `compiler-next` con `cargo build -p aether-driver
    --bin aether-next` y `python3 tests/measure-v17.py --runs 10`. El
    [JSON completo](../../compiler-next/tests/timings/v17-debug.json) conserva
    medias/medianas de todas las fases y la lista exacta que compone core.

29. **Legacy.** No se modificaron `src/aether`, `compiler-rs`, el runtime, la
    CLI de producción ni los archivos de trabajo del usuario en `scrap`.
    La comparación legacy se ejecuta como oráculo, sin integrarlo en el nuevo
    pipeline. No se creó commit ni se publicó nada.

30. **Deuda aceptada.** Continúan la restricción de Buffer/View simbólicos,
    procedencia léxica conservadora, prohibición de extracción de campos/slots
    propietarios, límites de instanciación y ABI bootstrap. La telemetría es
    inclusiva y añade overhead al compilador; no ofrece atribución exclusiva
    por consulta ni un benchmark estadístico. E0314 conserva el doble uso
    histórico mencionado arriba. No hay tipos concretos Storable y no-
    Relocatable en el lenguaje actual; la diferencia está comprobada mediante
    garantías simbólicas sin inventar sintaxis de tipos.

31. **OPEN DECISIONS.** Siguen abiertos el contrato de resultado vacío para
    extracción de List, la API futura de Buffer y el diseño de construcción/ABI
    de valores sensibles a direcciones. Lifetimes nombrados, almacenamiento de
    préstamos con parámetros y pinning requieren propuestas separadas. La
    admisión V17 de Array y List queda resuelta y no depende de esas decisiones.

32. **Problemas arquitectónicos encontrados y corregidos.** La prohibición
    simbólica ocultaba: búsqueda de layout concreto durante fill/reserve
    genéricos; ausencia de inferencia sobre patrones Array/List; detección de
    recursión expansiva basada en toda la cola, que rechazaba llamadas
    independientes; y captura de parámetros al derivar propiedades de
    aplicaciones nominales repetidas. Se corrigieron esos puntos dentro del
    alcance de las colecciones genéricas. La recursión ahora compara ancestros
    de instanciación y mantiene los límites de profundidad 32 y 256 instancias.
    No se alteró el algoritmo operacional de relocalización ni de drop.

33. **Recomendación para NEXT-VERTICAL-18.** Diseñar extracción propietaria de
    List: decidir primero el resultado vacío, representar el final que deja de
    estar inicializado y verificar transferencia exactamente una vez y drop del
    nuevo prefijo. Implementar una operación acotada solo cuando esos contratos
    estén definidos. Mantener lifetimes almacenados, pinning, traits y tipos
    matemáticos en verticales independientes. V17 no implementa pop/remove.
