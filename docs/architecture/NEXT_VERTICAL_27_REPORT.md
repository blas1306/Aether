# NEXT-VERTICAL-27 — built-in elementwise Vector/Matrix addition and subtraction

Implementado en `compiler-next`, Linux x86_64, 2026-09-08. Primera aritmética
matemática: `+` y `-` entre propietarios/vistas compatibles, resultado propietario
nuevo, lectura lógica con strides y semántica escalar comprobada.

1. **Arquitectura inicial.** V21..V26 proveían Vector/Matrix propietarios fijos,
   vistas prestadas con strides, orientación Vector, índices desde uno,
   transposición y proyección de ejes. La aritmética binaria era escalar; no
   existía un contrato para producir almacenamiento matemático nuevo leyendo
   dos descriptores. V27 resuelve esta operación antes de la coerción escalar.

2. **Archivos cambiados.** Rutas relativas a la raíz:

   | Archivo | Responsabilidad |
   |---|---|
   | `compiler-next/crates/aether-frontend/src/types.rs` | admisión interna de aritmética |
   | `compiler-next/crates/aether-frontend/src/hir.rs` | operaciones, shape contract, resolución, sustitución, préstamos, diagnóstico y test HIR |
   | `compiler-next/crates/aether-frontend/src/lib.rs` | exportación de MathShapeCheck |
   | `compiler-next/crates/aether-middle/src/elementwise.rs` | lenguaje de iteración estructurada y verificación completa |
   | `compiler-next/crates/aether-middle/src/mir.rs` | descriptores legibles, temporales, operación, ShapeMismatch y validación |
   | `compiler-next/crates/aether-middle/src/ssa.rs` | operación, renombrado, dependencias y validación |
   | `compiler-next/crates/aether-middle/src/lib.rs` | exportación de instrucciones semánticas |
   | `compiler-next/crates/aether-backend-llvm/src/elementwise.rs` | traducción recursiva de instrucciones a CFG LLVM |
   | `compiler-next/crates/aether-backend-llvm/src/lib.rs` | integración, traps, continuaciones y etiqueta estructurada del overflow de tamaño Matrix |
   | `compiler-next/crates/aether-driver/tests/vertical.rs` | nueve tests integrales e instrumentación |
   | `compiler-next/tests/programs/v27_*.ae` | diez fixtures enumerados abajo |
   | `compiler-next/tests/measure-v27.py` | snapshots reproducibles |
   | `compiler-next/tests/timings/v27-debug.json` | mediciones por fase |
   | `compiler-next/README.md` | sintaxis, alcance y coste actuales |
   | `docs/architecture/AETHER_V1_LANGUAGE_CHARTER.md` | admisión V27 |
   | `docs/architecture/AETHER_V1_SEMANTIC_CONTRACT.md` | contrato normativo |
   | `docs/architecture/AETHER_COMPILER_ARCHITECTURE.md` | confirmación 44 |
   | `docs/architecture/NEXT_VERTICAL_27_REPORT.md` | este informe |

3. **Elementos admitidos.** int8, int16, int32, int64, uint8, uint16, uint32,
   uint64, isize, usize, float32 y float64. Los aliases canónicos existentes
   int/float/double conservan sus equivalencias. No hay bool, struct, enum,
   Buffer, Array, List, Vector, Matrix ni referencia como elemento aritmético.
   Admisión en almacenamiento no implica admisión en aritmética.

4. **Consulta interna.** `TypeArena::supports_builtin_add_sub(TypeId)` utiliza
   la clasificación escalar concreta central `is_numeric`. Sólo Integer/Float
   satisfacen la consulta. No consulta Copy, Relocatable ni Storable y no crea
   una capacidad o trait público. Ambos rangos matemáticos la reutilizan.

5. **Resolución fuente.** El parser no cambia. `a+b` y `a-b` conservan la
   precedencia aditiva. El checker reconoce Places matemáticos antes de que la
   resolución por valor inserte Move, los convierte en descriptores compartidos
   y selecciona la operación matemática según sus tipos. Los escalares siguen
   por la resolución/coerción escalar existente. Otros operadores matemáticos
   se rechazan; no existe superficie `add(...)` ni dispatch runtime.

6. **Operandos Vector.** Vector<T,O>, VectorView<T,O> y VectorViewMut<T,O>, en
   cualquier combinación: las nueve parejas se ejecutan con ambos operadores.
   Owners, campos, elementos de contenedores y dereferencias explícitas se
   capturan como lecturas de descriptor. También se admiten las proyecciones
   `row(...)` y `column(...)` directamente como expresiones.

7. **Operandos Matrix.** Matrix<T>, MatrixView<T> y MatrixViewMut<T>, las nueve
   parejas con ambos operadores. Vistas compartidas y mutables son entradas
   legibles; no se escribe en su backing dentro de la operación.

8. **Propiedad del resultado.** Siempre Vector<T,O> o Matrix<T>, nunca View.
   Un backing nuevo independiente en caso no vacío. Los operandos existentes
   permanecen utilizables. Expresiones explícitas encadenadas como `(a+b)+(a+b)`
   crean los resultados solicitados por cada operador; los temporales internos
   prestan su descriptor al operador exterior y se destruyen después. No se
   introduce una copia propietaria auxiliar para adaptar un operando.

9. **Elemento exacto.** Se exige igualdad del TypeId canónico de T antes de
   cualquier aritmética. float32+float64 y int+double se rechazan sin promoción,
   conversión de elementos ni asignación de un operando convertido.

10. **Orientación.** Row+Row y Column-Column mantienen su orientación. Row con
    Column se rechaza con E0344. No hay transposición automática ni broadcasting.

11. **Dimensión Vector.** Igualdad exacta de dimensión. El análisis léxico
    diagnostica mismatch conocido; de otro modo ShapeGuard(Dimension) lo
    comprueba al ejecutar. La dimensión validada define resultado y loop.

12. **Forma Matrix.** Igualdad de filas, después igualdad de columnas. 2x3 y
    3x2 se rechazan aunque tengan seis elementos. El resultado mantiene ambas
    dimensiones y los loops conservan las coordenadas lógicas 2D.

13. **ShapeMismatch.** Nuevo TrapKind estructurado, distinto de IntegerOverflow,
    IndexOutOfBounds y traps de asignación. LLVM tiene `trap_shape_mismatch`
    con llvm.trap/unreachable. Las constantes incompatibles producen E0345.

14. **Orden de compatibilidad y asignación.** Descriptores primero; todos los
    guards de forma; bypass vacío; asignación comprobada; loops; resultado.
    El producto Matrix y el tamaño en bytes se comprueban después de la forma.
    No hay lectura de elementos antes de los guards. Instrumentación del trap
    confirma cero asignaciones de resultado ante mismatch. Inyección de tamaño
    imposible y malloc fallido confirma AllocationSizeOverflow/AllocationFailure.

15. **Vacío.** Vector vacío compatible y Matrix 0x0 compatible producen
    descriptor propietario cero/null sin llamar al allocator. Los cuatro
    operadores del fixture empty tienen cero operaciones, escrituras,
    asignaciones y liberaciones. Vacío con no vacío sigue diagnosticando/trap.

16. **Lecturas Vector con stride.** El operando legible contiene ptr, dimension
    y stride. Owner materializa stride=1; vistas conservan stride explícito.
    El loop usa `i*stride` para cada entrada por separado y almacena en result[i].
    Columnas con stride=3 producen los valores esperados en todas sus posiciones.

17. **Lecturas Matrix con strides.** Descriptor ptr,R,C,RS,CS. Owner suministra
    RS=C, CS=1. Los loops anidados usan `r*RS+c*CS` para cada entrada; el resultado
    almacena en `r*C+c`. Nunca se recorren físicamente R*C elementos contiguos
    de una MatrixView suponiendo su layout original.

18. **Aritmética de proyecciones.** `row(a,3)+row(b,3)` devuelve Row [77,88,99].
    Dos columnas segundas 3x3 devuelven Column [22,55,88], leyendo stride 3.
    El indexado del resultado sigue siendo el ordinario Vector desde uno.

19. **MatrixView transpuesta.** Para A=[1,2;3,4], T+T da [2,6;4,8]. También se
    verifica una transpuesta rectangular 2x3 -> 3x2. `A+transpose_view(A)`
    comprueba aliases del mismo backing con distintos recorridos lógicos.

20. **Overflow entero.** Se selecciona AddIntegerChecked/SubtractIntegerChecked
    y el contrato escalar existente exige IntegerOverflow. LLVM utiliza los
    mismos intrínsecos signed/unsigned with.overflow que los escalares. Ninguna
    operación emplea wrap silencioso ni flags nsw/nuw. Diez casos comprueban
    overflow después de inicializar el primer elemento, en ambos rangos.
    El proceso aborta sin unwind/rollback ni limpieza de slots parciales.

21. **Floats.** fadd/fsub IEEE, sin fast-math ni reassociation. Se ejecutan
    float32/float64, aliases float/double, columnas y matrices rectangulares.
    El fixture ieee comprueba cero negativo, infinito y NaN. No hay una vía
    rápida que cambie el contrato escalar según la forma del contenedor.

22. **Aliasing y préstamos durante evaluación.** Descriptores capturados a
    izquierda y derecha permanecen legibles; no se promete exclusividad ni
    noalias. El análisis protege el root del izquierdo mientras verifica el
    derecho, incluyendo proyecciones de Matrix. Consumir ese root desde una
    llamada derecha se rechaza. `a[i]+rhs(&mut i)` conserva el descriptor
    elegido antes del cambio de i; se ejecuta con contadores exactos.

23. **Genéricos simbólicos.** Operar sobre Vector<T>/Matrix<T> con T:Storable o
    T:Copy+Storable produce E0346 durante la comprobación paramétrica, incluso
    en una función sin instancias. No se difiere la prueba a monomorfización.
    No se admiten protocolos Add/Sub ni restricciones conductuales nuevas.

24. **HIR Vector.** `VectorElementwiseBinary {shape_check,op,left,right,
    element_type,orientation}` tiene TypeId propietario. MathShapeCheck es
    VectorDimension. El verificador exige tipos/elemento/orientación exactos,
    op escalar correcto, shape contract y ausencia de lectura propietaria
    Local/Move/Load como adaptación implícita. Sustitución conserva la receta.

25. **HIR Matrix.** `MatrixElementwiseBinary {shape_check,op,left,right,
    element_type}` tiene TypeId Matrix<T>. MathShapeCheck es MatrixRowsThenColumns.
    Forma permanece metadato runtime. El verificador comprueba ambos operandos
    recursivamente y el resultado; no admite mezcla de familias ni tipo simbólico.

26. **Loop MIR Vector.** Rvalue::ElementwiseBinary lleva dos operandos Copy
    legibles y un ElementwiseKernel ejecutable: ShapeGuard(Dimension), Allocate,
    For(Dimension,start=0,step=1), dos StridedLoad, ScalarBinary, InitializeNext,
    YieldOwner. Es control estructurado dentro de MIR; no un helper opaco cuya
    semántica de iteración aparezca por primera vez en el backend.

27. **Iteración MIR Matrix.** ShapeGuard(Rows), ShapeGuard(Columns), Allocate
    con ambas extensiones, For(Rows) exterior y For(Columns) interior. Cada
    StridedLoad tiene los términos (Rows,RowStride) y (Columns,ColumnStride).
    Los contadores internos no se exponen como índices fuente.

28. **Prueba de inicialización.** El lenguaje cerrado sólo acepta la secuencia
    canónica completa. Guards dominan asignación; ésta domina loops. El contador
    de cada eje empieza en cero, termina en su extensión y avanza uno. El cuerpo
    ejecuta una operación y una inicialización; la anidación enumera cada slot
    row-major una sola vez. InitializeNext es un prefijo implícito; al terminar
    la iteración alcanza N/R*C y sólo entonces YieldOwner puede escapar. LLVM
    representa ese prefijo con i o r*C+c, sin bitmap ni estado fuente adicional.

29. **Verificador MIR.** Comprueba disponibilidad y tipos de ambos operandos,
    tipo propietario de destino y programa completo: orden/traps de guards,
    dimensiones de asignación, bounds/step de loops, selectores stride, op
    escalar, inicialización y yield. Integra el resultado en los estados de
    ownership existentes. ElementwiseKernel no contiene instrucciones capaces
    de mover, destruir o mutar entradas. Los offsets se apoyan en invariantes
    de los descriptores admitidos y bounds del loop; LLVM usa GEP sin inbounds.

30. **SSA.** SsaOp::ElementwiseBinary conserva el programa estructurado y
    renombra ambos descriptores. Walkers de liveness/dominancia incluyen ambas
    dependencias. For representa su phi de contador y control de forma
    estructurada; esos phis se hacen explícitos al traducir a LLVM. No MemorySSA.

31. **Verificador SSA.** Invoca el verificador completo del programa con sus
    propios operand/result TypeIds, sin asumir un flag de validez heredado de
    MIR. Una entrada propietaria sustituida por la vista falla. Corrupciones de
    guards, orden, asignación, strides, step, inicialización, op, trap y resultado
    se rechazan en ambas fronteras. La autoridad global de lifetime/provenance
    continúa siendo el frontend léxico, igual que V26; no se añade un análisis
    global de préstamos en MIR/SSA.

32. **LLVM.** El traductor recorre las instrucciones MathStep: extrae
    descriptores, genera branches, bypass vacío, helper existente de almacenamiento,
    phis de loops, GEP strided, scalar op y stores contiguos. No llama a un
    dispatcher de aritmética ni BLAS. El phi final une propietario completo o
    vacío. Las continuaciones se integran en los predecesores de phis exteriores.
    AllocationSizeOverflow del helper Matrix ahora lleva etiqueta/comentario
    estructurados; no se altera el allocator ni el runtime legacy.

33. **Diagnósticos.** E0342: operador fuera de alcance/mezcla de familias;
    E0343: T canónico distinto; E0344: Row/Column distinto; E0345: forma conocida
    incompatible; E0346: elemento no escalar concreto, incluido T simbólico.
    Mensajes de resolución nombran el símbolo y los tipos; mismatch conocido
    muestra dimensiones/formas. E0292 y los diagnósticos previos conservan los
    rechazos de consumo invalidante y las restricciones de almacenamiento.

34. **Dumps.** HIR conserva nombre de operación, tipo, orientación y
    MathShapeCheck. MIR/SSA muestran ShapeGuard, ShapeMismatch, Allocate, For,
    StridedLoad, ScalarBinary, InitializeNext y YieldOwner. LLVM muestra los
    loops y marcadores ElementwiseBegin/End. Dos compilaciones de cuatro
    fixtures producen dumps HIR/MIR/SSA/LLVM idénticos. Se comprueba además
    orden de shape/allocation/load y ausencia de flags UB/copies/relocation.

35. **Tests exactos.** Suite completa: **216 tests, cero fallos**: 7 backend,
    28 frontend, 22 middle, 159 integración. Se mantienen los 206 de V0..V26 y
    se agregan diez. El negativo histórico V21 de `v+v` se actualiza a `v*v`,
    conservando un rechazo válido bajo la admisión V27.

    | Test nuevo | Evidencia |
    |---|---|
    | vertical27_hir_rejects_corrupt_math_types_and_ops | 12 rechazos HIR, seis por rango |
    | vertical27_native_values_and_exact_operation_allocation_counts | diez fixtures, valores y contadores por operación/finales |
    | vertical27_all_readable_pairs_and_scalar_types | 36 parejas/rangos/ops y 12 tipos, 48 ejecutables |
    | vertical27_structured_rejections_and_evaluation_borrows | 17 errores tipados, tres genéricos y tres invalidaciones |
    | vertical27_runtime_shape_checks_precede_allocation_and_element_access | 14 casos, originales y instrumentados |
    | vertical27_integer_overflow_uses_scalar_checked_traps | diez casos originales y traps identificados |
    | vertical27_mir_ssa_independently_verify_executable_loop_and_types | 19 corrupciones por rango/capa: 76 rechazos |
    | vertical27_deterministic_dumps_and_logical_codegen | cuatro fixtures, determinismo, strides y orden |
    | vertical27_allocation_traps_after_shape_and_before_access | tamaño imposible y fallo allocator en ambos rangos |
    | vertical27_nested_elements_remain_storage_without_arithmetic | siete clases de elemento en ambos rangos, 14 rechazos |

    Fixtures `v27_`: vector_contiguous, vector_strided, matrix_contiguous,
    matrix_transposed, empty, floats, control_flow, projected, ieee, evaluation.
    Se ejercitan resultados retornados, encadenados, limpieza condicional,
    loops, campos/Array y refs explícitas. fmt y clippy con `-D warnings` forman
    parte de la calificación, además de git diff --check.

36. **Ejecuciones de traps.** 14 ejecuciones de ShapeMismatch y diez de overflow
    exigen SIGILL (señal 4). Sus 24 variantes instrumentadas distinguen el trap:
    salida 73 comprueba forma sin asignación nueva; salida 74 identifica
    IntegerOverflow. Cuatro probes adicionales usan salida 75/76 para comprobar
    AllocationSizeOverflow/AllocationFailure, con sólo dos asignaciones previas
    de operandos. Total dedicado: **110 ejecuciones nativas**, contando los
    diez fixtures instrumentados y 48 ejecutables de parejas/tipos. La inyección
    de extents imposibles se limita al LLVM de tests, no a una API fuente.

37. **Contadores exactos.** Cada operador exitoso comprueba delta alloc
    `1 si no vacío, 0 si vacío`, delta free=0, número de scalar ops y stores
    igual a N/R*C. El wrapper comprueba alloc/free finales iguales y valores
    fuente correctos. Operaciones y stores se cuentan dinámicamente en el cuerpo.

    | Fixture | Alloc = Free finales | Operaciones = stores elementwise |
    |---|---:|---:|
    | vector_contiguous | 4 | 6 |
    | vector_strided | 4 | 6 |
    | matrix_contiguous | 4 | 12 |
    | matrix_transposed | 4 | 10 |
    | empty | 0 | 0 |
    | floats | 8 | 10 |
    | control_flow | 18 | 26 |
    | projected | 9 | 14 |
    | ieee | 4 | 5 |
    | evaluation | 6 | 8 |

    Cada fixture generado de parejas usa alloc=free=3, cuatro operaciones/stores.
    Cada fixture de tipo escalar usa alloc=free=4, seis operaciones/stores.
    Coste por operación: Vector O(N), Matrix O(R*C), sin copia oculta de entrada.

38. **Snapshots de compilación.** Misma metodología V17..V26: driver debug,
    proceso nuevo, un warmup descartado, diez muestras. Core suma las ocho fases
    parse-through-LLVM; excluye startup/discovery/I/O/dumps/clang/link y fases
    inclusivas duplicadas. Se conservó el ejecutable V26 antes de editar en
    `/tmp/aether-v26-v27-baseline`, HEAD
    `6e089ff0891c183c08f8bd323e5f43f967a3c5b2`. Sin builds/tests concurrentes
    durante las muestras.

    | Compilador / fixture | Core media ms | Core mediana ms |
    |---|---:|---:|
    | V26 original / proyección column | 1.373 | 1.370 |
    | V27 / misma proyección column | 1.037 | 1.001 |
    | V27 / Vector contiguo | 1.593 | 1.551 |
    | V27 / Vector strided | 2.107 | 2.071 |
    | V27 / Matrix contigua | 2.120 | 1.906 |
    | V27 / MatrixView transpuesta | 1.958 | 1.957 |

    Son snapshots descriptivos de compilación, no benchmarks runtime ni prueba
    estadística de mejora. Cada fixture incluye sus comprobaciones y puede
    contener más de un operador. Datos en
    [v27-debug.json](../../compiler-next/tests/timings/v27-debug.json), script
    [measure-v27.py](../../compiler-next/tests/measure-v27.py).

39. **Legacy.** `bash compiler-next/tests/run-differential.sh`: 21 comparaciones,
    cero fallos. No se modifican compiler-rs, runtime ni CLI legacy, ni scrap.
    Los binarios no rastreados preexistentes FaCAether/FaCAetherO0 quedan fuera
    de la implementación. Los cambios del backend pertenecen sólo a compiler-next.

40. **Deuda aceptada.** Control de iteración estructurado dentro de MIR/SSA,
    no BasicBlocks/phis internos expandidos hasta LLVM. La verificación del
    lenguaje cerrado acepta la secuencia canónica completa; no es un solver
    general de invariantes ni permite optimizadores reordenar libremente la
    región. Lifetime/provenance global sigue siendo léxico/frontend. ABI
    bootstrap x86_64, traps abortivos, sin unwind ni cleanup parcial para T
    propietario. Nada de esto introduce una capacidad aritmética genérica.

41. **OPEN DECISIONS.** Promoción de elementos; capacidades conductuales;
    orientación/dimensiones genéricas o estáticas; operaciones in-place;
    multiplicación escalar/dot/outer/matmul; IEEE/overflow para futuros kernels;
    BLAS; ABI pública; slices/submatrices y strides negativos; lifetimes más
    precisos. Ninguna queda admitida por V27.

42. **Problemas arquitectónicos encontrados.** La resolución escalar por valor
    insertaba Move antes de conocer el operador; ahora los Places matemáticos
    se resuelven como lecturas antes de ese punto. Un operando proyectado debe
    capturarse antes de efectos del segundo, y su root protegido léxicamente.
    Una operación que asigna y puede atrapar necesita separar su backing privado
    parcialmente inicializado del propietario que escapa: la región estructurada
    establece esa frontera. La expansión de loops obliga a integrar correctamente
    las continuaciones en phis exteriores. La prueba negativa V21 dejó de ser
    válida por admisión explícita de `+`, sin regresión del rechazo de `*`.

43. **Recomendación NEXT-VERTICAL-28.** Introducir multiplicación escalar
    explícita para Vector/Matrix sobre los mismos elementos built-in, si se
    elige continuar computación matemática: fijar sintaxis/orden de operandos,
    tipos exactos, IEEE/overflow y reutilizar la región de inicialización
    verificada. Tratar dot/outer/matmul y capacidades públicas en decisiones
    separadas. Esta es una recomendación, no parte de la implementación V27.
