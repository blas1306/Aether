# NEXT-VERTICAL-23 — mathematical Matrix<T> foundation

Implementado en `compiler-next`, Linux x86_64, 2026-09-08. Matrix conserva
identidad matemática propia desde HIR hasta LLVM, con forma en el valor,
almacenamiento fijo y acceso bidimensional comprobado desde uno.

1. **Arquitectura inicial.** V21/V22 tenían `AstExprKind::VectorLiteral`,
   proyecciones `Index` con un único operando e `IndexSemantics::{ZeroBased,
   OneBased}`. Vector internaba orientación, usaba `{ptr,dimension}`, exigía
   Storable y reutilizaba almacenamiento fijo, ownership de raíces y drop
   recursivo. Transpose consumía el descriptor sin modificar elementos.

2. **Archivos cambiados.** Rutas relativas a la raíz:

   | Archivo | Responsabilidad |
   |---|---|
   | `compiler-next/crates/aether-frontend/src/ast.rs` | literal matemático con filas e índices fuente múltiples |
   | `compiler-next/crates/aether-frontend/src/parser.rs` | semicolons, gramática y rechazo de fila final vacía |
   | `compiler-next/crates/aether-frontend/src/types.rs` | Matrix, interning, Storable, propiedades, sustitución y rango/base |
   | `compiler-next/crates/aether-frontend/src/hir.rs` | contexto, forma, índices, consultas, ownership, monomorfización y verificación |
   | `compiler-next/crates/aether-middle/src/mir.rs` | MatrixInit, consultas, ambos índices, captura de operandos y verificador |
   | `compiler-next/crates/aether-middle/src/ssa.rs` | operaciones, operandos, rango/base, verificador y consumo de temporales |
   | `compiler-next/crates/aether-backend-llvm/src/lib.rs` | descriptor, forma, guardas, almacenamiento, drop y mangling |
   | `compiler-next/crates/aether-driver/src/lib.rs` | nombres temporales únicos entre compilaciones concurrentes |
   | `compiler-next/crates/aether-driver/tests/vertical.rs` | pruebas V23, instrumentación y actualización del contrato AST de V21 |
   | `compiler-next/tests/programs/v23_matrix_*.ae` | dieciocho fixtures nativos |
   | `compiler-next/tests/modules/v23_matrix/{main,storage}.ae` | firmas y propietarios entre módulos |
   | `compiler-next/tests/modules/v1-contract.tsv` | admisión del módulo V23 |
   | `compiler-next/tests/measure-v23.py` | mediciones con metodología V17..V22 |
   | `compiler-next/tests/timings/v23-debug.json` | snapshots por fase y baseline V22 |
   | `compiler-next/README.md` | sintaxis y contrato actual |
   | `docs/architecture/AETHER_V1_LANGUAGE_CHARTER.md` | alcance implementado |
   | `docs/architecture/AETHER_V1_SEMANTIC_CONTRACT.md` | contrato Matrix normativo |
   | `docs/architecture/AETHER_COMPILER_ARCHITECTURE.md` | confirmación 40 y hallazgos |
   | `docs/architecture/NEXT_VERTICAL_23_REPORT.md` | este informe |

3. **Sintaxis Matrix.** `Matrix<int> A=[1,2,3;4,5,6];`, `A[i,j]`, `rows(A)`
   y `columns(A)`. Admite int, double, tipos nominales y T simbólico. Matrix
   exige exactamente un argumento de tipo; los argumentos extra se diagnostican
   antes de intentar resolver sus nombres. No hay parámetros de forma/layout.

4. **TypeData/TypeId.** `TypeData::Matrix { element: TypeId }` se interna de
   forma canónica. Resolver repetidamente Matrix<int> reutiliza su ID, distinto
   de Array<int>, List<int> y Vector<int,Row/Column>. La prueba de identidad
   verifica estas diferencias, no-Copy, needs_drop y layout de 24 bytes.

5. **Generalización AST.** `MathematicalLiteral { rows: Vec<Vec<AstExpr>> }`
   conserva los límites de filas hasta validar la forma. No se construyen
   VectorLiteral anidados. El mismo nodo representa brackets de Vector y Matrix.
   El AST de índices conserva una lista de expresiones sin decidir el tipo.

6. **Regresión contextual Vector.** Una fila sigue resolviendo VectorInit
   bajo contexto Vector, incluida orientación Column. `[]` conserva dimensión
   cero. Varias filas producen E0332. Los tests V21 que esperaban VectorLiteral
   y reserva sintáctica de semicolons se actualizan al nuevo contrato; sus
   verificaciones de datos, orientación, ownership, índices y transpose siguen
   pasando. Las matrices no pasan por VectorInit.

7. **Resolución contextual Matrix.** El tipo esperado aporta exclusivamente
   T. Una vez validada la rectangularidad se generan los operandos tipados y
   MatrixInit, conservando rows, columns y los finales de fila `row_ends` como
   evidencia verificable. Sin contexto matemático se emite E0326.

8. **Filas y separadores.** Gramática admitida:
   `"[" (row (";" row)* ","?)? "]"`, con
   `row := expression ("," expression)*`. Una coma final sólo se admite
   inmediatamente antes de `]`: `[1,2,]` y `[1,2;3,4,]` son válidos.
   `[1,2,;3,4]`, `[;]`, `[1;;2]` y `[1;]` se rechazan. Un semicolon final
   produce E0330, sin inventar una fila vacía ni statements anidados.

9. **Rectangularidad.** Se comprueba cada fila contra el ancho de la primera
   antes de aplanar. E0333 identifica fila, columnas esperadas y encontradas,
   con span del primer elemento de la fila incorrecta. HIR/MIR/SSA vuelven a
   comprobar el producto, la cantidad de operandos y todos los límites de fila.
   `row_ends` permite detectar intercambios de metadatos rows/columns en 2x3,
   que un chequeo del producto por sí solo no detectaría.

10. **Matrix vacía.** `[]` bajo Matrix<T> genera exclusivamente 0x0, cero
    operandos y límites de fila vacíos. LLVM usa descriptor cero sin llamar
    al constructor de almacenamiento. Los fixtures empty y empty_owning exigen
    exactamente cero alloc y free. No se admite 0xN ni Nx0 no canónico.

11. **Una fila/columna.** `[10,20,30]` es 1x3; `[10;20;30]` es 3x1.
    Ambos tienen descriptor Matrix, consultas distintas y una asignación/liberación.
    Se prueban también 2x2 y 2x3, con acceso a los extremos correctos.

12. **Tipado/evaluación de elementos.** Cada entrada usa las reglas ordinarias
    contra T; Matrix<double> admite enteros literales y ensanchamiento float32.
    No se agregan conversiones escalares propias. La evaluación y captura es
    por filas, de izquierda a derecha. MIR materializa operandos Copy antes de
    evaluar los siguientes, evitando que una llamada posterior cambie un local
    ya leído. El fixture evaluation observa ese orden y el de ambos índices.
    Los operandos no-Copy usan sus movimientos ordinarios, una sola vez.

13. **Admisión de almacenamiento.** `CollectionKind::Matrix` exige únicamente
    Storable, reutilizando la consulta central de capacidades. E0331 rechaza
    elementos no almacenables, incluidos préstamos persistentes. Ni Copy ni
    Relocatable ni Numeric son requisitos de T. El descriptor propietario es
    relocatable por sus propias propiedades, sin cambiar las obligaciones de T.

14. **Genéricos simbólicos.** `Matrix<T> pair<T:Storable>(T a,T b){return [a,b];}`
    se comprueba paramétricamente, incluso sin instanciarlo. T sin constraint
    y T:Copy son insuficientes para probar Storable. Sustitución, inferencia y
    monomorfización conservan Matrix; se ejecutan instancias con bool y Buffer.

15. **Descriptor físico.** `{ptr,i64 rows,i64 columns}`, tamaño 24 y alineación
    8 en el target bootstrap. No hay capacidad, orientación, tag de layout ni
    stride runtime. Los límites de fila del IR nunca forman parte del descriptor.

16. **Layout row-major.** Las ranuras físicas siguen el orden fuente por filas.
    Se usa `(row-1)*columns+(column-1)`. Esto es una elección del backend y no
    identidad matemática ni equivalencia con contenedores anidados. El stride
    de fila se deriva de columns; no se almacena metadata futura de vistas.

17. **rows.** MatrixRows permanece explícito en HIR/MIR/SSA y LLVM extrae
    el campo 1 del descriptor actual. Retorna usize y admite lugares proyectados,
    referencias a Matrix, campos y matrices guardadas en otros contenedores.

18. **columns.** MatrixColumns tiene el mismo contrato de lugar y retorna
    usize desde el campo 2. No se transforma semánticamente en length/dimension.
    Los fixtures comprueban formas rectangulares y consultas anidadas.

19. **Índices 2D.** `A[i,j]` produce una única proyección Index con primer
    índice y `column: Some(...)`. `A[i]` y `A[i,j,k]` producen E0334. Los
    contenedores 1D requieren exactamente un índice; no se codifica Matrix como
    dos proyecciones consecutivas. Los índices de valores realmente anidados,
    como `outer[0][1,2]`, mantienen sus tipos y bases propios.

20. **Bounds desde uno.** Se emiten cuatro ramas lógicas ordenadas: row>=1,
    row<=rows, column>=1, column<=columns. Cualquier fallo conduce al trap
    IndexOutOfBounds/llvm.trap. Cero, upper+1 y usize::MAX se prueban en cada eje,
    incluidos vacío, 1xN, Nx1 y rectangular.

21. **Prueba de seguridad del offset.** Construcción verifica `R*C` con
    `llvm.umul.with.overflow.i64`; el helper fijo verifica además bytes por
    elemento y fallo de asignación. La forma del descriptor no se modifica.
    Tras las guardas, `0<=r0<R`, `0<=c0<C`, por tanto
    `r0*C+c0 <= (R-1)*C+(C-1) = R*C-1`.
    El producto de forma representable prueba que multiplicación y suma del
    offset tampoco desbordan usize. Para una forma vacía nunca se llega al
    bloque de dirección. Las instrucciones sub/mul/add sin nsw/nuw y el GEP
    aparecen sólo en ese bloque posterior a las cuatro guardas. El drop usa
    el mismo producto de forma ya probado, sin ampliar el rango inicializado.

22. **Evolución IndexSemantics.** Se preservan ZeroBased y OneBased para 1D y
    se agrega OneBased2D. El TypeId canónico decide base y rango; tres
    verificadores exigen columna exactamente para Matrix, dos operandos usize
    y metadata coherente. Walkers de operandos, sustitución, ownership,
    renombrado y dominancia visitan ambos ejes. No se diseña un sistema tensorial.

23. **Lecturas.** Copy T se carga de la ranura comprobada. Los elementos
    propietarios sólo se consultan mediante proyecciones/referencias permitidas;
    intentar extraer Buffer de un índice Matrix mantiene el rechazo de partial
    move. No se introduce Take desde índices fuente.

24. **Escrituras.** La sustitución Copy usa el lugar 2D comprobado. Reemplazar
    una ranura no-Copy sigue rechazado por el modelo general de asignaciones,
    que aún no representa destruir/reinicializar esa ranura con seguridad.

25. **Referencias.** `&A[i,j]` y `&mut A[i,j]` usan las mismas guardas y una
    dirección estable durante la vida del propietario. Los préstamos vivos
    impiden mover el Matrix. También se rechaza consumir el propietario dentro
    de una expresión de índice antes de efectuar el acceso. Se mantiene la
    procedencia léxica conservadora; no hay View/ViewMut público de Matrix.

26. **Elementos propietarios.** Matrix<Buffer<int>> consume cuatro Buffer
    exactamente una vez y preserva sus payloads. Construcción no crea Vector,
    Array ni List temporales, ni clones. Las transferencias de descriptores usan
    las reglas y el almacenamiento fijo existentes.

27. **Move/drop.** Raíces, parámetros por valor, retornos, structs, enums y
    ramas reutilizan estados y flags existentes. El drop recorre las ranuras
    en orden inverso, llama al glue recursivo de T cuando corresponde y libera
    el backing una vez. No existen nuevos estados de ownership para Matrix.

28. **Composición anidada.** Se ejecutan Matrix<Vector<int,Row>>,
    Matrix<Matrix<int>>, Array<Matrix<int>> y List<Matrix<int>>, incluido push
    que provoca crecimiento externo. Consultas y accesos preservan forma y
    mezcla de bases. No hay whitelist de tipos ni interpretación como tensor.

29. **HIR.** MatrixInit, MatrixRows, MatrixColumns y la proyección bidimensional
    conservan identidad. El verificador comprueba forma y elementos, admisión,
    tipo de consultas y todos los operandos del lugar. Las consultas no mueven
    el propietario; los literales sí consumen entradas no-Copy.

30. **MIR.** Las mismas operaciones llevan traps explícitos de tamaño,
    asignación y bounds. El flujo normal consume entradas e inicializa el owner.
    La captura del primer índice ocurre antes de evaluar la columna. Los
    verificadores de lugar y operandos comprueban ambos ejes de forma independiente.

31. **SSA.** Mantiene los TypeIds exactos y las operaciones Matrix. Además
    del contrato de tipos y dominancia, una auditoría de temporales exige una
    transferencia de cada resultado MatrixInit y de sus entradas propietarias,
    sin escape directo a phi. Las raíces siguen moviéndose antes de las phis
    normales. Esto detecta duplicación de elementos propietarios sin MemorySSA.

32. **LLVM.** Helper interno Matrix crea el descriptor después de comprobar
    forma; la asignación física reutiliza `aether_fixed_new_T`. MatrixInit
    almacena operandos capturados en orden fuente. Queries extraen campos;
    índices llaman al helper de cuatro guardas. DropShape::Matrix es sólo una
    decisión del generador Rust que adapta el recorrido fijo a rows*columns.

33. **Mangling y módulos.** Matrix usa prefijo estructural M, distinto de
    A/L/QRow/QColumn y sin dimensiones. El módulo ejecutable instancia identity
    con Matrix<int> y Matrix<Buffer<int>>, conservando firmas exactas. Cuatro
    pruebas rechazan retornos/argumentos importados con Vector, Array o T distinto.

34. **Rechazo Matrix transpose.** E0328 informa expresamente que Matrix
    transpose no está implementado y que el intrínseco admite Vector. No se
    intercambian campos de forma. El transpose consumidor Vector continúa
    transfiriendo exactamente su descriptor de dos campos, con sus tests V22.

35. **Diagnósticos.** E0261 aridad Matrix; E0330 semicolon final; E0331
    Storable; E0332 varias filas bajo Vector; E0333 fila desigual; E0334 cantidad
    de índices; E0335 consultas de forma; E0326 falta de contexto matemático;
    E0328 transpose Matrix; E0296 bounds constantes; E0289 vistas planas.
    Los errores escalares ordinarios indican índices de tipo inválido con su
    span. E0291/E0292 y restricciones previas cubren moves/préstamos. Hay
    23 comprobaciones de código exacto, nueve rechazos adicionales y cuatro
    rechazos entre módulos, además de las regresiones V0..V22.

36. **Dumps.** Dos compilaciones completas producen los mismos dumps de
    AST/HIR/MIR/SSA/LLVM. Se observan filas AST, MatrixInit, rows/columns,
    row_ends, tipo Matrix y OneBased2D; en el mismo programa permanecen
    VectorInit, orientación, dimension y transpose. Metadata de admisión
    muestra el requisito Storable. Las filas no se convierten en contenedores.

37. **Pruebas exactas.** `cargo test --workspace --no-fail-fast` pasa **178
    tests**, cero fallos: 7 backend, 23 frontend, 22 middle y 126 integración.
    Los 170 de V0..V22 se conservan con la evolución intencional del AST V21.
    También pasan `cargo clippy --workspace --all-targets -- -D warnings`,
    `cargo fmt --all -- --check` y `git diff --check`. Los ocho nuevos tests son:

    | Test | Evidencia |
    |---|---|
    | vertical23_hir_rejects_corrupt_matrix_contracts | ocho corrupciones HIR |
    | vertical23_identity_context_and_deterministic_ir | identidad, layout, contexto, dumps y orden de guardas |
    | vertical23_native_shapes_ownership_and_exact_heap_counts | dieciocho fixtures y módulo con resultado y conteos exactos |
    | vertical23_structured_diagnostics | tipos, forma, índices, Storable, propietarios y rechazo transpose/vistas |
    | vertical23_runtime_bounds_all_axes_and_access_modes | 96 ejecuciones con SIGILL del trap |
    | vertical23_independent_hir_mir_ssa_contract_verifiers | once corrupciones MIR y once SSA, más duplicación propietaria en ambos |
    | vertical23_owning_payload_drop_order | traza 40,30,20,10 y 5/5 |
    | vertical23_cross_module_signature_rejections | cuatro firmas importadas incompatibles |

    Las corrupciones abarcan intercambio de forma, límites de fila incorrectos,
    elemento inválido, sustitución por VectorInit, query incorrecta, columna
    ausente, base/rango equivocado, traps alterados y producto desbordado.

38. **Ejecuciones de bounds/trap.** Cuatro formas × seis pares de índices
    inválidos × cuatro modos (lectura, escritura, ref, ref-mut) = **96**.
    Cada una exige señal 4 (SIGILL de llvm.trap), en lugar de aceptar cualquier
    terminación anormal. Los fixtures positivos ejercitan también ambos extremos,
    escritura, referencias, loops y queries proyectadas. Los tests V23 dedicados
    ejecutan **116 artefactos nativos** incluyendo datos, módulo y drop.

39. **Instrumentación alloc/free/drop.** El guard exige simultáneamente
    resultado fuente cero y ambos contadores exactos; el guard de balance
    existente sigue activo. No hay hooks públicos nuevos.

    | Fixture v23_matrix_* | Alloc | Free |
    |---|---:|---:|
    | empty | 0 | 0 |
    | empty_owning | 0 | 0 |
    | row | 1 | 1 |
    | column | 1 | 1 |
    | square | 1 | 1 |
    | rectangular | 1 | 1 |
    | widening | 2 | 2 |
    | refs | 1 | 1 |
    | move | 1 | 1 |
    | return | 1 | 1 |
    | struct | 1 | 1 |
    | enum | 1 | 1 |
    | generic | 4 | 4 |
    | owning | 5 | 5 |
    | conditional | 2 | 2 |
    | nested | 11 | 11 |
    | loop | 1 | 1 |
    | evaluation | 1 | 1 |
    | módulo v23_matrix | 4 | 4 |

    El caso nested incluye una reasignación de backing del List externo por
    crecimiento, además de sus valores Matrix. La prueba separada de drop
    registra payloads antes de liberar Buffer y exige exactamente 40302010,
    junto con cinco asignaciones y cinco liberaciones.

40. **Snapshots de compilación.** Metodología V17..V22: debug, un proceso
    nuevo por compilación, un warmup descartado y diez muestras. Core suma las
    ocho fases parse-through-LLVM, excluyendo startup, discovery, I/O, dumps y
    clang/link. Los detalles frontend inclusivos no se suman otra vez.
    V22 se reconstruyó bajo /tmp desde
    `be569d54d0ac3bc88199291c02e89c90eca6e1e8`; el baseline fuente es el fixture
    Vector `v22_transpose_row.ae`. No se ejecutaron builds/tests concurrentes de
    esta tarea durante las muestras. Herramientas y valores completos están en
    [v23-debug.json](../../compiler-next/tests/timings/v23-debug.json), reproducibles
    con [measure-v23.py](../../compiler-next/tests/measure-v23.py).

    | Compilador / fixture | Core media ms | Core mediana ms |
    |---|---:|---:|
    | V22 original / Vector V22 | 1.410 | 1.403 |
    | V23 / mismo Vector V22 | 1.025 | 1.001 |
    | V23 / Matrix 1x3 | 0.814 | 0.747 |
    | V23 / Matrix 2x2 | 0.899 | 0.817 |
    | V23 / Matrix 2x3 | 0.870 | 0.828 |
    | V23 / loop indexado | 1.136 | 1.085 |
    | V23 / elementos propietarios | 0.801 | 0.747 |

    Herramientas: rustc 1.97.1 (8bab26f4f 2026-07-14); clang version 22.1.8.

    Son snapshots descriptivos de compilación, sin afirmaciones de rendimiento
    runtime ni de mejoras estadísticamente demostradas.

41. **Legacy.** `compiler-next/tests/run-differential.sh` completa **21
    comparaciones ejecutables, cero fallos**. Esta implementación no modifica
    compiler-rs, runtime/CLI legacy ni scrap. Se preservan los binarios
    preexistentes FaCAether y FaCAetherO0. No se hizo commit ni publicación.

42. **Deuda aceptada.** Se conservan préstamos léxicos/procedencia conservadora,
    ausencia de partial moves y de reemplazo seguro de slots propietarios,
    traps sin unwind y ABI interna. Las formas constantes sólo se siguen para
    raíces léxicas directas y moves conocidos; se descartan conservadoramente
    ante control de flujo o llamadas con referencias mutables. Casos restantes
    siempre tienen bounds runtime. row_ends añade evidencia estática al IR, sin
    coste en el descriptor. No se introduce un análisis general de memoria o
    de inicialización parcial. La reasignación consumidora de la misma raíz
    conserva las restricciones del modelo anterior.

43. **OPEN DECISIONS.** MatrixView y lifetimes, strides, layouts alternativos,
    transpose con movimiento físico frente a vista prestada, row/column views,
    slicing, dimensiones estáticas, capacidades numéricas por operación,
    arithmetic/BLAS, ABI pública y cleanup con unwind requieren diseños propios.
    Ninguna opción se fija implícitamente mediante el layout bootstrap.

44. **Problemas arquitectónicos descubiertos.** La identidad antigua del
    literal ligaba innecesariamente brackets a Vector; ahora la decisión es
    contextual. El producto de forma no bastaba para verificar intercambio de
    ejes; se retienen límites fuente. Los walkers de índices eran de un solo
    operando y ahora incluyen columna en todas las capas. Reutilizar sin filtro
    owning_contiguous_element habría admitido vistas que pierden forma; HIR/MIR/
    SSA excluyen Matrix explícitamente. La captura diferida de valores Copy
    podía alterar el orden observable; Matrix materializa valores y primer
    índice. Ownership revalida la raíz tras evaluar índices consumidores.
    Finalmente, una ejecución paralela expuso dos compilaciones NEXT escribiendo
    el mismo temporal LLVM porque compartían timestamp. El driver y el helper
    de pruebas añaden un contador atómico por proceso al nombre; después de
    corregirlo la suite completa y clippy pasan. No fue un error de LLVM Matrix
    ni requirió tocar el driver legacy.

45. **Recomendación NEXT-VERTICAL-24.** Diseñar primero MatrixView con identidad
    matemática propia, forma/strides explícitos, préstamos y ambos ejes desde
    uno. Cerrar ese contrato permite definir una vista transpuesta sin fingir
    que intercambiar rows/columns en el propietario row-major transpone datos.
    Transpose propietario, arithmetic y capacidades numéricas deben conservar
    alcances separados. Mantener las guardas y los contratos Vector existentes.
