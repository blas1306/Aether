# NEXT-VERTICAL-21 — mathematical Vector<T, Orientation> foundation

Implementado en `compiler-next`, Linux x86_64. Calificado el 2026-09-07.
Vector tiene identidad matemática propia, orientación canónica, literal `[]`,
dimensión fija, almacenamiento propietario contiguo e índices comprobados desde 1.

1. **Arquitectura inicial de índices/storage.** V20 usaba Place::Index tipado
   con elemento y trap, pero suponía base cero tanto en chequeos constantes
   como en el helper LLVM de descriptores fijos. Array compartía `{ptr,length}`
   y asignación exacta con Buffer; List tenía `{ptr,length,capacity}` y sus
   transacciones de extracción. V16/V17 ya aportaban admisión Storable para
   almacenamiento fijo, transferencia de operandos propietarios y drop recursivo.
   Vector reutiliza esos mecanismos físicos sin adquirir identidad Array ni
   operaciones de crecimiento/extracción List.

2. **Archivos cambiados.** Rutas relativas a la raíz:

   | Archivo | Responsabilidad |
   |---|---|
   | `compiler-next/crates/aether-frontend/src/types.rs` | Orientation, Vector TypeData, interning, IndexSemantics, propiedades y sustitución |
   | `compiler-next/crates/aether-frontend/src/ast.rs` | VectorLiteral separado |
   | `compiler-next/crates/aether-frontend/src/parser.rs` | brackets, vacío, trailing comma y reserva Matrix |
   | `compiler-next/crates/aether-frontend/src/hir.rs` | resolución, admisión, VectorInit/Dimension, índices, ownership y verificación |
   | `compiler-next/crates/aether-frontend/src/lib.rs` | exportaciones de Orientation/IndexSemantics |
   | `compiler-next/crates/aether-middle/src/mir.rs` | operaciones Vector, índices tipados y verificación |
   | `compiler-next/crates/aether-middle/src/ssa.rs` | preservación, operandos, promoción y verificación independiente |
   | `compiler-next/crates/aether-backend-llvm/src/lib.rs` | storage fijo, índices one-based, mangling, drop y consultas proyectadas |
   | `compiler-next/crates/aether-driver/tests/vertical.rs` | nueve tests V21 y adaptación explícita de cuatro índices corruptos anteriores a ZeroBased |
   | `compiler-next/tests/programs/v21_vector_*.ae` | diecisiete fixtures nativos, enumerados abajo |
   | `compiler-next/tests/modules/v21_vectors/{main,storage}.ae` | firmas y agregados genéricos Row/Column importados |
   | `compiler-next/tests/modules/v1-contract.tsv` | registro del módulo |
   | `compiler-next/tests/measure-v21.py` | snapshots reproducibles con baseline V20 opcional |
   | `compiler-next/tests/timings/v21-debug.json` | resultados completos por fase |
   | `compiler-next/README.md` | gramática y contrato V21 |
   | `docs/architecture/AETHER_V1_LANGUAGE_CHARTER.md` | alcance matemático implementado |
   | `docs/architecture/AETHER_V1_SEMANTIC_CONTRACT.md` | contrato normativo 6.3 y actualización 6.4 |
   | `docs/architecture/AETHER_COMPILER_ARCHITECTURE.md` | confirmación 38 |
   | `docs/architecture/NEXT_VERTICAL_21_REPORT.md` | este informe |

3. **Sintaxis Vector.** `Vector<double,Row> r=[1,2,3];`,
   `Vector<float64,Column> c=[1.0,2.0,3.0];`, `v[i]=value;`,
   `ref T x=&v[1];`, `ref mut T y=&mut v[1];`, `dimension(v)`.
   Se admiten alias transparentes, espacios, literales multilínea y coma final.
   No hay constructor fill, métodos ni conversiones Array/Vector.

4. **Orientación.** `Orientation::{Row,Column}` es un enum interno de Rust,
   resuelto desde el segundo argumento intrínseco. No se interna Row/Column
   como tipos ordinarios ni se añade una variable/booleano runtime. No hay
   orientación genérica O, const/value generics ni metadatos de stride.

5. **TypeData/TypeId.** `TypeData::Vector { element:TypeId,
   orientation:Orientation }` participa en interning, formato, propiedades,
   layout, detección de símbolos, sustitución y mangling. Repetir resolución
   con igual elemento/orientación devuelve el mismo ID. La dimensión pertenece
   al valor: no forma parte del TypeId ni es un argumento estático.

6. **Identidad Row/Column.** Son tipos distintos aun con idéntico layout.
   No hay asignación, paso de argumentos ni retorno implícito entre ambos.
   Holder<Vector<int,Row>> conserva esa diferencia frente a Holder de Column.
   El mangling estructural incluye QRow/QColumn; firmas importadas y referencias
   a ellas preservan los TypeIds exactos.

7. **AST matemático.** Los brackets crean AstExprKind::VectorLiteral; las
   llaves siguen creando CollectionLiteral. No hay Array intermedio ni nodo
   neutral que pierda esta distinción. Vector<Vector<…>,…> puede almacenar
   propietarios anidados como cualquier T: Storable, pero no representa Matrix.

8. **Expected type.** El literal requiere un Vector esperado para resolver
   orientación y elemento. Declaraciones, argumentos concretos, campos, payloads,
   retornos y cuerpos genéricos aportan contexto. Un argumento genérico sin
   contexto suficiente y `auto x=[…]` se rechazan; auto sigue sin implementarse.

9. **Vacío.** Row y Column admiten `[]`, dimensión cero, descriptor null/zero,
   cero asignaciones y cero liberaciones. No se llama al allocator para el
   vacío Vector. Toda indexación runtime de dimensión cero atrapa.

10. **Tipado/coerción de elementos.** Reutiliza las reglas normales: enteros
    literales contextuales pueden producir double, y float32 puede ensancharse
    a float64. No se inventan conversiones de escalares particulares para
    vectores. Bool, structs y elementos de tamaño cero también funcionan;
    legalidad de storage no equivale a capacidad numérica.

11. **Storage fijo.** Layout bootstrap de 16 bytes, alineación 8, descriptor
    LLVM `{ptr,i64 dimension}`. Ambos sentidos usan la misma representación.
    Cada construcción no vacía asigna espacio exacto y guarda los operandos
    en orden fuente. Su dimensión no cambia; reasignar el propietario completo
    puede instalar otro valor construido. No hay capacidad ni mutación dinámica.

12. **Admisión Storable.** La política fija requiere únicamente Storable.
    `CollectionKind::Vector` es una categoría interna de admisión de storage,
    no una equivalencia semántica con las colecciones. Copy y Relocatable no
    son requisitos del elemento. Referencias/views almacenadas se rechazan.

13. **Genéricos simbólicos.** `Vector<T,Row> pair<T:Storable>(T a,T b)
    {return [a,b];}` se comprueba paramétricamente y se monomorfiza normalmente,
    incluidos Buffer propietarios. La prueba de TypeArena usa un T con sólo
    Storable, comprueba que no garantiza Relocatable y aun así se admite.
    Sustitución e inferencia exacta conservan orientación; no hay dispatch runtime.

14. **Dimension.** `dimension(vector_place)` devuelve usize sin consumirlo
    y resuelve a VectorDimension. Funciona con locales, referencias explícitamente
    dereferenciadas, campos y descriptores indexados como `dimension(v[2])`.
    No es ArrayLength/ListLength ni un método. Aridad/tipo incorrectos se rechazan.

15. **Contrato one-based.** `TypeArena::index_semantics(TypeId)` devuelve
    OneBased para Vector y ZeroBased para Buffer/Array/List/View. Cada proyección
    Index transporta el resultado y cada verificador lo contrasta con el tipo
    del contenedor recorrido. Vector acepta exactamente `1 <= i <= dimension`.
    No existe base configurable global. El índice usa usize y no acepta índices
    signed, negativos ni bool.

16. **Offset físico.** El helper LLVM comprueba primero unsigned i>=1 y
    salta a un segundo bloque que comprueba i<=dimension. Ambos fallos llegan a
    IndexOutOfBounds. Sólo el bloque valid emite `%offset=sub i64 %index,1` y
    el GEP inbounds. No hay resta/GEP antes del guard. Lectura, escritura y
    ambos préstamos comparten esta autoridad. La prueba de contador comprueba
    una evaluación fuente del índice por cada una de esas cuatro operaciones.

17. **Regresión zero-based.** Array/List conservan llaves, `i<length`, índices
    primero 0/último n-1 y sus operaciones existentes. El fixture mixto comprueba
    ambos tipos junto a Row/Column en el mismo programa. Se ejercitan también
    Array<Vector>, List<Vector>, Vector<Array> y Vector<Vector> con tamaños
    interiores distintos del exterior. La suite V0..V20 sigue verde.

18. **Lecturas.** T Copy se lee por valor. T no-Copy no puede extraerse mediante
    indexación ordinaria: se conserva la prohibición de partial move. Un préstamo
    a Buffer dentro de Vector permite consultar su contenido sin extraerlo.

19. **Escrituras.** Reemplazo Copy y escritura de subcampos Copy funcionan.
    El reemplazo parcial no-Copy falla con E0297 porque el modelo de asignación
    actual no expresa de forma segura la destrucción/transferencia del slot.
    No se implementa clone ni drop oculto para sortear esa limitación independiente.

20. **Refs/ref-mut.** `&v[1]` y `&mut v[1]` usan el mismo bounds one-based.
    Los elementos permanecen en sus direcciones mientras vive el propietario.
    La prueba conserva ambas referencias durante una llamada que sólo modifica
    elementos a través de ref mut Vector; no adquiere invalidación List.
    Move/reemplazo del propietario con refs vivas se rechaza. View/ViewMut
    públicos y sus verificadores excluyen Vector; VectorView queda futuro.

21. **Elementos propietarios.** Vector<Buffer<int>,Row> admite temporales y
    Move de propietarios existentes, con transferencia única y sin copia profunda.
    Se prueban construcción genérica, literal directo, acceso anidado y préstamos.
    El contenedor se destruye con tres asignaciones/liberaciones en el fixture
    de dos Buffers. No se requiere Relocatable de T para moverlo a su slot final.

22. **Move/drop.** Vector es no-Copy y needs_drop. Sus descriptores se transfieren
    mediante el flujo existente de raíces en moves, parámetros y retornos.
    Flags de limpieza condicional siguen siendo los genéricos. Drop recorre
    slots n-1..0, equivalentes a índices lógicos n..1, y libera el backing una
    vez. El fixture conditional recorre ambas ramas de consumo/no consumo.

23. **Composición agregada.** Campos struct, payload enum, Holder genérico,
    agregados importados y nested owners conservan tipos, orientación y ownership.
    Copy de un agregado depende de sus miembros; contener Vector lo hace no-Copy.
    Drop usa el orden previo de campos/payloads y sólo la variante activa.

24. **HIR.** VectorInit, VectorDimension y Place::Index con OneBased son
    operaciones explícitas, con elemento TypeId y tipo del valor. Sustitución y
    verificación no borran identidad Vector. Los dumps muestran orientación,
    propiedades y requisitos/admisión Storable.

25. **MIR.** Conserva ambas operaciones Vector y los contratos de traps de
    asignación. El flujo de ownership consume una sola vez los operandos no-Copy.
    Bounds se mantiene como efecto comprobado de la proyección tipada, como en
    Array, sin exponer una resta fuente ni reutilizar una operación zero-based
    sin autoridad. Verifica dimensión, elementos, flags/traps y base semántica.

26. **SSA.** Conserva TypeId exacto, VectorInit/Dimension e IndexSemantics.
    La verificación independiente rechaza base cero en Vector, init/dimension
    reemplazados por operaciones Array y metadatos de tipo/trap corruptos.
    La promoción sigue siendo selectiva: los accesos al backing no convierten
    todos los valores en memoria. No se añade MemorySSA.

27. **LLVM.** Reutiliza fixed_new y drop de storage fijo, con helpers tipados
    y símbolos de propietario específicos de orientación. La orientación no
    tiene coste de campo runtime. Los operandos se evalúan mediante lowering
    ordinario y los slots se inicializan en orden fuente. Consultas proyectadas
    usan emit_place_value, incluyendo el backing de descriptores promovidos.

28. **Traps.** E0296 rechaza un índice constante directo cuando se conoce su
    dimensión y está fuera de rango. Los demás índices inválidos terminan en
    IndexOutOfBounds. Cuarenta ejecuciones distinguen Row/Column, 0, n+1,
    usize máximo, vacío con 0/1, y read/write/ref/ref-mut; todas producen SIGILL
    (llvm.trap en el target), no SIGSEGV. El test de LLVM verifica además las
    aristas que dominan offset/GEP. Se conservan AllocationSizeOverflow y
    AllocationFailure de la infraestructura fija.

29. **Instrumentación exacta.** Se ejecuta cada fixture para comprobar su
    resultado y dos variantes LLVM que leen alloc_count/free_count tras la
    limpieza. El guard de balance existente sigue activo. Ningún contador
    es una API pública nueva.

    | Fixture `v21_vector_…` | Alloc | Free |
    |---|---:|---:|
    | empty_row | 0 | 0 |
    | empty_column | 0 | 0 |
    | row | 1 | 1 |
    | column | 1 | 1 |
    | widening | 1 | 1 |
    | refs | 1 | 1 |
    | loop | 1 | 1 |
    | move | 1 | 1 |
    | return | 1 | 1 |
    | struct | 1 | 1 |
    | enum | 1 | 1 |
    | generic | 2 | 2 |
    | owning | 3 | 3 |
    | conditional | 4 | 4 |
    | nested | 10 | 10 |
    | non_numeric | 3 | 3 |
    | index_once | 1 | 1 |

    Una instrumentación adicional registra payloads antes de free en ambas
    orientaciones y exige 302010: destrucción exacta 30,20,10. Nested incluye
    un reserve del List exterior, cuya asignación extra explica su total.

30. **Diagnósticos de orientación.** E0324 requiere Row/Column intrínsecos
    sin referencia, calificador ni argumentos. La aridad usa E0262; E0325
    informa storage sin Storable; E0326 exige contexto Vector; E0327 valida
    dimension. Orientaciones incompatibles usan los errores ordinarios de tipo
    con nombres Vector completos. Hay cuatro rechazos adicionales entre módulos.

31. **Reserva Matrix.** `[1,2,3]` genera VectorLiteral y `[1,2;3,4]` se rechaza
    con diagnóstico que reserva los semicolons para future Matrix syntax.
    No se implementa Matrix ni se representan sus filas como vectores anidados.
    Se documentan `Matrix<double> A=[1.0,2.0;3.0,4.0]` y acceso futuro A[i,j].

32. **Pruebas exactas.** `cargo test --workspace --no-fail-fast`:
    **163 tests, cero fallos**: 7 backend, 21 frontend, 22 middle y
    113 integración. Diez son nuevos V21:

    | Test | Cobertura |
    |---|---|
    | vertical21_hir_rejects_erased_vector_contracts (frontend) | tres corrupciones HIR: init, dimension y base |
    | vertical21_orientation_identity_and_symbolic_storage | interning, Row/Column, propiedades y sustitución |
    | vertical21_deterministic_mathematical_ir | AST, HIR/MIR/SSA, determinismo y dominación LLVM de offset/GEP |
    | vertical21_diagnostics_and_matrix_reservation | 45 casos de rechazo, cuatro códigos exactos y reserva Matrix |
    | vertical21_native_values_and_exact_heap_counts | 17 fixtures, 51 ejecuciones con resultados/contadores y módulo |
    | vertical21_runtime_bounds_read_write_and_borrow | 40 ejecuciones de traps |
    | vertical21_collections_keep_zero_based_indices | programa mixto Array/List/Row/Column |
    | vertical21_verifiers_reject_erased_index_and_vector_contracts | seis corrupciones MIR y seis SSA independientes |
    | vertical21_drop_order_is_reverse_logical_index | dos trazas nativas exactas de destrucción |
    | vertical21_cross_module_orientation_rejection_and_mangling | mangling y cuatro programas importados incompatibles |

    Pasan también `cargo clippy --workspace --all-targets -- -D warnings`,
    `cargo fmt --all -- --check` y `git diff --check`.

33. **Snapshots de compilación.** Metodología V17..V20: binarios debug,
    un proceso nuevo por build, un warmup descartado y diez muestras por fixture.
    Core suma ocho fases parse-through-LLVM; excluye startup, discovery, I/O,
    dumps y clang/link. Detalles frontend inclusivos no se suman otra vez.
    No hubo builds/tests concurrentes de esta tarea durante la medición.
    Linux x86_64, rustc 1.97.1, clang 22.1.8. Baseline V20 reconstruido desde
    `a65a02af0a4132661dd5affe2599196537de14a9` en una copia separada bajo /tmp.

    | Compilador / fixture | Core media ms | Core mediana ms |
    |---|---:|---:|
    | V20 original / remove Buffer | 1.586 | 1.393 |
    | V21 / remove Buffer | 1.499 | 1.365 |
    | V21 / Row pequeño | 1.028 | 0.966 |
    | V21 / Column pequeño | 0.884 | 0.816 |
    | V21 / loop indexado | 1.196 | 1.070 |
    | V21 / elementos propietarios | 1.142 | 1.082 |

    Son snapshots descriptivos, no evidencia de mejora de rendimiento ni
    benchmarks runtime. El host/caché y diferencias de fixture impiden inferir
    ventajas Row/Column. [JSON completo](../../compiler-next/tests/timings/v21-debug.json)
    y [script reproducible](../../compiler-next/tests/measure-v21.py).

34. **Legacy.** `tests/run-differential.sh`: **21 comparaciones ejecutables,
    cero fallos**. No se cambian compiler-rs, runtime/CLI legacy ni scrap.
    FaCAether/FaCAetherO0 eran binarios untracked preexistentes y se preservan.
    No se hizo commit ni publicación.

35. **Deuda aceptada.** Lifetime/procedencia léxica y relaciones nested siguen
    conservadoras. No hay extracción parcial no-Copy ni reemplazo de propietarios
    en slots; existe la limitación independiente de Buffer fill. Dimensión es
    runtime, almacenamiento heap, ABI interna y ayudas LLVM tipadas. Traps abortan
    sin unwind. Bounds no tiene un pase nuevo de eliminación por pruebas de rango.
    Las capas tienen brazos explícitos para VectorInit/Dimension; compartir su
    implementación física no elimina sus contratos semánticos independientes.

36. **OPEN DECISIONS.** Quedan para otras verticales: VectorView con orientación,
    transpose explícito y sus variantes consuming/borrowed, dimensión estática
    opcional, errores de dimensión en operaciones binarias, tipo/AST de Matrix,
    capacidades numéricas por operación, ABI pública y precisión de lifetimes.
    Nada de ello bloquea esta base ni se resuelve implícitamente en V21.

37. **Problemas arquitectónicos descubiertos.** El campo checked/trap previo
    no expresaba base de índices: se incorpora IndexSemantics validado por tipo.
    El chequeo constante podía aplicar la longitud exterior a cualquier índice
    nested; ahora sólo usa esa información para la proyección directa y deja
    las demás a sus guards correctos. La consulta de descriptor fijo asumía
    Place sin proyecciones y podía panic; se elimina esa ruta y se usan cargas
    generales, con acceso por puntero para metadata de SSA indexado. El helper
    fijo histórico asigna aun con longitud cero: Vector vacío se construye como
    null/zero explícitamente para obtener 0/0 sin alterar Array/Buffer.

38. **Recomendación NEXT-VERTICAL-22.** Una conversión matemática explícita
    transpose que consuma un Vector y devuelva la orientación opuesta, conservando
    dimensión y backing, sería una extensión acotada. Debe conservar ownership,
    rechazar consumo con refs vivas y tener operaciones HIR/MIR/SSA propias.
    No necesita Numeric ni matrices. Variantes borrowed y aritmética por elementos
    requieren contratos separados; V21 no implementa ninguna de ellas.
