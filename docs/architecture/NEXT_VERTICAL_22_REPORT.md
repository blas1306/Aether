# NEXT-VERTICAL-22 — explicit consuming Vector transpose

Implementado y calificado en `compiler-next`, Linux x86_64, 2026-09-07.
`transpose(v)` consume el propietario, cambia Row ↔ Column y transfiere el
mismo descriptor sin tocar almacenamiento ni elementos.

1. **Representación inicial.** V21 internaba `Vector<T,Row>` y
   `Vector<T,Column>` como TypeIds distintos. Ambos tenían descriptor bootstrap
   `{ptr, i64 dimension}`, tamaño 16 y alineación 8, almacenamiento contiguo fijo,
   admisión Storable, índices desde 1 y destrucción inversa. Vector era propietario
   no-Copy independientemente de T. No existía operación de transpose.

2. **Archivos cambiados.** Rutas relativas a la raíz:

   | Archivo | Cambio |
   |---|---|
   | `compiler-next/crates/aether-frontend/src/types.rs` | `Orientation::transposed` |
   | `compiler-next/crates/aether-frontend/src/hir.rs` | resolución, VectorTranspose, sustitución, ownership, dimensión conocida, verificación, llamadas descartadas Copy y pruebas HIR |
   | `compiler-next/crates/aether-middle/src/mir.rs` | VectorTransposeMove, lowering, consumo, flags y verificación |
   | `compiler-next/crates/aether-middle/src/ssa.rs` | operación tipada, promoción/operandos y auditoría independiente de consumo |
   | `compiler-next/crates/aether-backend-llvm/src/lib.rs` | transferencia de los mismos bits del descriptor |
   | `compiler-next/crates/aether-driver/tests/vertical.rs` | seis pruebas de integración V22, instrumentación y corrupciones |
   | `compiler-next/tests/programs/v22_transpose_*.ae` | once fixtures enumerados en el punto 22 |
   | `compiler-next/tests/modules/v22_transpose/{main,storage}.ae` | genéricos, llamadas importadas, ambas orientaciones y propietarios |
   | `compiler-next/tests/modules/v1-contract.tsv` | admisión del nuevo módulo |
   | `compiler-next/tests/measure-v22.py` | snapshots con metodología existente y baseline opcional |
   | `compiler-next/tests/timings/v22-debug.json` | mediciones completas por fase |
   | `compiler-next/README.md` | contrato y ejemplos actuales V22 |
   | `docs/architecture/AETHER_V1_LANGUAGE_CHARTER.md` | alcance implementado |
   | `docs/architecture/AETHER_V1_SEMANTIC_CONTRACT.md` | contrato normativo V22 dentro de 6.3 |
   | `docs/architecture/AETHER_COMPILER_ARCHITECTURE.md` | confirmación 39 y hallazgo sobre sentencias |
   | `docs/architecture/NEXT_VERTICAL_22_REPORT.md` | este informe |

3. **Sintaxis fuente.** Se admiten `Vector<int,Column> c=transpose(r);`,
   `return transpose(v);`, `consume(transpose(v));` y
   `transpose(transpose(r))`. El parser conserva su aplicación neutral existente.
   Una sentencia de llamada declarada, local o importada, puede descartar un
   resultado Copy (por ejemplo int); el resultado propietario exige binding
   explícito. Esto cubre la forma requerida sin introducir void. No hay métodos,
   apóstrofo, argumentos explícitos de tipo de transpose ni expresión general
   de descarte de propietarios.

4. **Contrato matemático.** Se conservan dimensión, componentes, orden y valores.
   `[10,20,30]` representa los mismos componentes con orientación opuesta.
   No se invierte el orden, conjuga, transforma numéricamente ni invoca funciones
   de elementos. Transpose no es conjugate transpose ni adjoint.

5. **Mapeo de orientación.** `Row -> Column`, `Column -> Row` mediante el enum
   cerrado `Orientation`. `Orientation::transposed` es total e involutivo.
   Los TypeIds de ambos lados son distintos y la asignación implícita continúa
   siendo inválida, también dentro de agregados y firmas importadas.

6. **Derivación del resultado.** Se analiza el operando sin expected type de
   destino. Su TypeData debe ser Vector; se interna el mismo elemento con
   orientación opuesta y después se verifica el contexto de uso. El TypeId exacto
   de T no cambia. `transpose([])` sin un operando con tipo no puede decidir
   orientación y conserva el rechazo de literal sin contexto de V21.

7. **Consumo del propietario.** HIR contiene el Move normal del operando.
   Ownership visita ese Move y el origen pasa a Moved; lecturas, consultas de
   dimensión y nuevos consumos posteriores fallan. Esto también se aplica a
   Vector<int>. MIR consume el temporal fuente e inicializa el destino mediante
   las mismas funciones de flujo de propietarios existentes. Owned/Moved/
   MaybeMoved y flags condicionales no incorporan estados específicos de Vector.

8. **Transferencia del descriptor.** Sólo se transfiere `{ptr, dimension}`.
   La operación conserva identidad semántica de ambos tipos y cambia únicamente
   la orientación canónica. No es ExplicitCast, alias, conversión escalar ni
   reinterpret cast general. Los Vector canónicos definen el mismo layout;
   no se introduce un cache de layout mutable que pueda contradecirlo.

9. **Contrato físico de coste cero.** Transpose es O(1), con exactamente cero
   alloc, free, copia, reconstrucción, relocación o drop de elementos. No hay
   nueva reserva ni acceso al backing. El descriptor puede recibir otro nombre
   SSA sin duplicar su propietario semántico. Este contrato es obligatorio,
   no una optimización dependiente de LLVM.

10. **Vector vacío.** Row y Column vacíos, incluidos elementos Buffer, conservan
    null/zero y dimensión cero. El fixture pasa por ambas orientaciones y exige
    cero asignaciones y liberaciones totales.

11. **Elementos propietarios.** Vector<Buffer<int>> funciona en ambos sentidos,
    también mediante genéricos. Las tres cargas de payload conservan 10,20,30.
    El backing exterior y los Buffer almacenados permanecen en sus direcciones;
    transpose no carga/copia los descriptores Buffer ni toca sus pointees.
    Structs propietarios y bool confirman que no se exige una capacidad numérica.

12. **Genéricos.** `toColumn<T:Storable>(Vector<T,Row> v)` y la inversa se
    comprueban paramétricamente antes de monomorfización. Un cuerpo no utilizado
    también se comprueba; orientación incorrecta en su retorno se rechaza.
    Sólo Storable es suficiente; Copy, Relocatable y Numeric no se añaden.
    Sustitución conserva el operando, source_type y tipo del resultado.

13. **Préstamos.** `ref` y `ref mut` vivos a elementos impiden el consumo con
    E0292. Se mantiene la protección de un primer argumento prestado mientras
    se evalúa un segundo argumento con transpose. Al finalizar el scope de un
    préstamo anterior, el propietario puede transponerse. El destino admite
    préstamos, índices primero/último y escritura Copy normalmente. Array/List
    mantienen su base cero en el fixture mixto.

14. **Doble transpose.** La forma anidada restaura Row y mantiene puntero,
    dimensión y valores. También se prueban dos pasos mediante locales con
    elementos propietarios y seis transposes dinámicos dentro de un loop de
    tres iteraciones. Cada operación se instrumenta individualmente.

15. **Agregados y módulos.** Struct y enum se construyen con resultados de
    transpose. Un payload enum extraído mediante el match consumidor existente
    puede transponerse como propietario local. Extraer un campo/slot no-Copy
    ordinario o mover a través de referencia sigue prohibido; no se añade partial
    move. El módulo importa ambas funciones genéricas e identity, consume desde
    una llamada importada y conserva los tipos exactos. Tres casos importados
    de orientación incorrecta fallan.

16. **HIR.** `VectorTranspose { operand, source_type }` usa el TypeId del HirExpr
    como resultado. Estos dos TypeIds canónicos expresan orientación, elemento
    y representación sin metadatos redundantes. El nodo es intrínsecamente
    consumidor y el verificador rechaza Local/Load como sustitutos del Move.
    Verifica recursivamente el operando, source_type, mismo T y orientación
    exactamente opuesta. Las dimensiones conocidas se propagan sin recalcularlas.

17. **MIR.** `VectorTransposeMove { operand, source_type }` conserva el tipo de
    destino en el Place/local. Lowering materializa el operando, emite la operación
    y actualiza el flag de consumo si existe. El verificador de tipos comprueba
    independientemente los Vector y su relación. El flujo normal de ownership
    consume exactamente una vez e inicializa el nuevo propietario; una segunda
    operación que reutilice el temporal fuente falla.

18. **SSA.** Conserva la misma operación y el tipo de cada definición. No se
    convierte en Use. La auditoría independiente recoge temporales de entrada y
    salida de transpose y exige una transferencia por temporal, sin escape directo
    a phi. Las asignaciones de raíces siguen usando Move antes de las phis
    ordinarias. La auditoría cuenta usos en un recorrido de la función, con mapas
    deterministas, y omite ese recorrido adicional si no hay transpose.
    Rechaza orientación igual, T distinto, no-Vector, source_type corrupto,
    reemplazo por Use y duplicación de propietario con ValueId nuevo.

19. **LLVM.** Emite `select i1 true, {ptr,i64} source, {ptr,i64} source`: los
    mismos bits bajo el nombre del resultado. No hay símbolo runtime transpose,
    campo de orientación, llamada, loop, rama, GEP de elemento, memcpy, helper
    de relocación ni drop dentro de la operación. La prueba de un helper genérico
    de retorno directo verifica también la ausencia de alloca y de extracción/
    reconstrucción del descriptor en todo el cuerpo.

20. **Mangling.** Continúa usando QRow/QColumn dentro de argumentos estructurales
    de instancias. El módulo ejecutable genera ambas especializaciones de identity
    con Vector<Buffer<int>>. No cambia ABI pública ni se añade símbolo runtime.

21. **Puntero y dimensión.** La instrumentación de prueba extrae ambos campos
    inmediatamente antes y después de cada select de transpose y exige igualdad
    exacta. Exige además que haya ocurrido al menos un transpose y preserva la
    comprobación del resultado fuente. Cubre vacíos, propietarios, genéricos,
    llamadas, ramas, loop y doble operación. No existe API fuente para consultar
    direcciones ni se calcula dimensión desde bytes.

22. **Contadores y destrucción.** Cada transpose exige deltas alloc/free/
    relocation = 0/0/0. Al salir se exigen los siguientes totales y cero
    relocaciones, además del guard de balance normal:

    | Fixture `v22_transpose_…` | Alloc | Free |
    |---|---:|---:|
    | row | 1 | 1 |
    | column | 1 | 1 |
    | empty | 0 | 0 |
    | owning | 4 | 4 |
    | double | 1 | 1 |
    | refs | 3 | 3 |
    | generic | 4 | 4 |
    | conditional | 6 | 6 |
    | aggregate | 3 | 3 |
    | non_numeric | 3 | 3 |
    | loop | 6 | 6 |
    | módulo v22_transpose | 2 | 2 |

    Dos ejecuciones adicionales, una por dirección, registran los payloads antes
    de cada free y exigen la traza exacta 302010, es decir 30,20,10. El destino
    destruye una vez en orden inverso; el origen movido no destruye elementos.
    Los contadores/observadores existen sólo en LLVM de calificación.

23. **Diagnósticos.** E0328 identifica Vector transpose con tipo inválido,
    aridad incorrecta o argumentos explícitos de tipo. E0291 indica uso tras
    Move, E0292 préstamo vivo, E0293 partial move y E0303 MaybeMoved. Se reutilizan
    los errores ordinarios para orientación/elemento incompatible. E0311 exige
    binding si una llamada descartada devuelve un propietario. Ninguno de los
    errores intrínsecos de transpose usa diagnóstico de cast escalar.

24. **Dumps.** AST conserva Call, HIR muestra VectorTranspose y MIR/SSA muestran
    VectorTransposeMove con source_type y tipos de destino. Las tablas canónicas
    contienen Row/Column. LLVM muestra transferencia de descriptor. Dos
    compilaciones completas generan dumps idénticos en las cinco capas.

25. **Pruebas exactas.** `cargo test --workspace --no-fail-fast` pasa **170 tests**,
    cero fallos: 7 backend, 22 frontend, 22 middle y 119 integración. Los 163
    tests de V0..V21 permanecen verdes. Los siete nuevos son:

    | Test | Evidencia |
    |---|---|
    | `vertical22_hir_rejects_corrupt_transpose_contracts` | cinco corrupciones HIR de orientación, metadatos, elemento, no-Vector y consumo |
    | `vertical22_deterministic_consuming_ir` | dumps deterministas y cuerpo LLVM sin storage/calls/loops |
    | `vertical22_structured_diagnostics_and_parametric_checking` | 28 ejecuciones negativas, códigos exactos y genéricos simbólicos no utilizados |
    | `vertical22_native_data_ownership_and_per_transpose_zero_cost` | once fixtures normales e instrumentados, más módulo instrumentado |
    | `vertical22_mir_ssa_reject_corrupt_type_and_owner_transfers` | seis corrupciones MIR y seis SSA, incluyendo duplicación con identidad nueva |
    | `vertical22_final_drop_is_once_in_reverse_order` | dos ejecuciones con traza exacta y contadores |
    | `vertical22_cross_module_orientation_and_layout` | TypeIds distintos, layout igual, no-Copy y tres rechazos importados |

    V22 suma **25 ejecuciones nativas dedicadas**: 22 de fixtures, una de módulo
    y dos de drop. También pasan `cargo clippy --workspace --all-targets -- -D warnings`,
    `cargo fmt --all -- --check` y `git diff --check`.

26. **Snapshots de compilación.** Metodología V17..V21: debug, un proceso por
    compilación, un warmup descartado y diez muestras. Core suma ocho fases
    parse-through-LLVM, excluyendo startup, discovery, I/O, dumps y clang/link;
    los detalles frontend inclusivos no se suman dos veces. Sin builds/tests
    concurrentes de esta tarea durante las muestras. rustc 1.97.1, clang 22.1.8,
    Linux x86_64. V21 reconstruido bajo /tmp desde
    `b1ad8fc00b5433daca17921b4d45c7c6a21a26cc`.

    | Compilador / fixture | Core media ms | Core mediana ms |
    |---|---:|---:|
    | V21 original / Vector Row V21 | 1.307 | 1.263 |
    | V22 / mismo Vector Row V21 | 1.120 | 0.991 |
    | V22 / Row -> Column | 1.054 | 0.982 |
    | V22 / Column -> Row | 1.053 | 1.022 |
    | V22 / elementos propietarios | 1.375 | 1.283 |
    | V22 / transpose dos veces | 0.960 | 0.905 |

    Son snapshots descriptivos de fixtures pequeños, no una afirmación de mejora
    ni benchmarks runtime. La instrumentación runtime verifica por separado el
    coste cero. [JSON](../../compiler-next/tests/timings/v22-debug.json) y
    [script](../../compiler-next/tests/measure-v22.py).

27. **Legacy.** `tests/run-differential.sh`: **21 comparaciones ejecutables,
    cero fallos**. No se modifica compiler-rs, runtime/CLI legacy ni scrap.
    FaCAether y FaCAetherO0 eran binarios untracked preexistentes y se preservan.
    No se hace commit ni publicación.

28. **Deuda aceptada.** Se conservan préstamos léxicos/procedencia conservadora,
    prohibición de partial move, ausencia de VectorView, ABI interna y traps sin
    unwind. El protocolo SSA exige materializar transferencias antes de phis;
    no es un nuevo análisis general de memoria. El descarte de llamadas sólo
    admite resultado Copy y no introduce void ni destrucción implícita de un
    resultado propietario. La asignación a la misma raíz desde un RHS que la
    consume, por ejemplo `r=transpose(transpose(r))`, sigue rechazada por el orden
    de comprobación de la asignación existente; el contrato requerido de doble
    transpose mediante un destino nuevo funciona. Resolver reasignación después
    de consumir su antiguo valor requiere una mejora general de asignaciones.

29. **OPEN DECISIONS.** Borrowed transpose/VectorView orientado, forma y lifetime
    de vistas, Matrix y su transpose, adjoint/conjugación, dimensiones estáticas,
    capacidades numéricas por operación, ABI pública, void/descarte propietario
    y mejora general de reasignación consumidora quedan separados. Ninguna
    decisión altera implícitamente esta transferencia consumidora cerrada.

30. **Problemas arquitectónicos descubiertos.** El filtro de sentencias V14
    impedía la forma exacta `consume(transpose(v));`; se resuelve admitiendo
    llamadas declaradas con sink Copy, conservando semántica normal de argumentos.
    El chequeo SSA de tipos por sí solo no prueba consumo tras un cambio de
    TypeId: se añade auditoría independiente de temporales de transpose,
    análoga al protocolo Take pero con un único recorrido de usos. La prueba
    adicional de reasignación consumidora a la misma raíz expuso una limitación
    previa del chequeo de Assign, que se documenta sin inventar una excepción
    específica de Vector. No fue necesario tocar storage, indexación, layout,
    mangling ni drop para transponer.

31. **Recomendación NEXT-VERTICAL-23.** Diseñar un VectorView con orientación y
    préstamos explícitos sería el siguiente paso matemático acotado. Antes de
    implementarlo deben cerrarse identidad de tipo, procedencia/lifetime, mutabilidad,
    indexación desde 1 y la distinción entre construir una vista transpuesta y
    consumir un propietario. El transpose consumidor V22 debe seguir independiente.
    Matrix, arithmetic y adjoint deberían tener verticales propias. La mejora
    general de asignación tras consumo puede tratarse como cierre de ownership
    separado, sin convertir transpose en una excepción.
