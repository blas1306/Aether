# NEXT-VERTICAL-28 — built-in scalar multiplication for Vector/Matrix owners and views

Implementado exclusivamente en `compiler-next`, Linux x86_64, 2026-09-08.
Se admite multiplicación por un escalar built-in en ambos órdenes, leyendo
owners/vistas con strides y produciendo un propietario independiente.

1. **Arquitectura inicial.** `*` escalar ya seleccionaba
   MultiplyIntegerChecked/MultiplyFloat. V27 incorporó HIR específico para
   suma/resta matemática, captura prestada de Places y ElementwiseKernel:
   instrucciones estructuradas verificadas en MIR y SSA, traducidas por un
   único emisor LLVM. No existía un contrato de un escalar y un descriptor.

2. **Archivos cambiados.**

   | Ruta | Cambio |
   |---|---|
   | `compiler-next/crates/aether-frontend/src/types.rs` | consulta de multiplicación |
   | `compiler-next/crates/aether-frontend/src/hir.rs` | resolución, HIR, sustitución, préstamos, formas conocidas, verificación y test |
   | `compiler-next/crates/aether-frontend/src/lib.rs` | exporta ScalarSide |
   | `compiler-next/crates/aether-middle/src/elementwise.rs` | scalar_side, InvariantScalar, constructor y verificación completos |
   | `compiler-next/crates/aether-middle/src/mir.rs` | captura fuente y lowering/cleanup compartidos |
   | `compiler-next/crates/aether-backend-llvm/src/elementwise.rs` | extensión del mismo traductor estructurado |
   | `compiler-next/crates/aether-driver/tests/vertical.rs` | nueve tests V28; probes de contadores/asignación compartidos con V27 |
   | `compiler-next/tests/programs/v28_*.ae` | nueve fixtures: vector_contiguous, vector_strided, matrix_contiguous, matrix_transposed, empty, floats, evaluation, control_flow, projected |
   | `compiler-next/tests/measure-v28.py` | medición reproducible |
   | `compiler-next/tests/timings/v28-debug.json` | snapshots de compilación |
   | `compiler-next/README.md` | sintaxis, tipos, coste y alcance |
   | `docs/architecture/AETHER_V1_LANGUAGE_CHARTER.md` | admisión V28 |
   | `docs/architecture/AETHER_V1_SEMANTIC_CONTRACT.md` | contrato normativo |
   | `docs/architecture/AETHER_COMPILER_ARCHITECTURE.md` | confirmación 45 |
   | `docs/architecture/NEXT_VERTICAL_28_REPORT.md` | este informe |

3. **Tipos elemento/escalar.** int8/int16/int32/int64,
   uint8/uint16/uint32/uint64, isize/usize y float32/float64. Los aliases
   canónicos int/float/double conservan su identidad. bool, structs, enums,
   Buffer, Array/List, elementos matemáticos anidados y referencias no
   adquieren aritmética por ser almacenables.

4. **Consulta de soporte.** `TypeArena::supports_builtin_multiply(TypeId)`
   consulta la clasificación concreta Integer/Float existente. Es independiente
   de `supports_builtin_add_sub` y de las capacidades de almacenamiento.
   No se introduce un concepto Numeric nuevo ni una capacidad pública Mul.

5. **Operadores fuente.** `s*v`, `v*s`, `s*m`, `m*s`, con la precedencia
   multiplicativa existente. Resolución matemática antes de coerciones y
   adaptación implícita por Move. La multiplicación escalar ordinaria no cambia.

6. **Contexto de literales.** Se reutilizan las reglas existentes para literales
   numéricos y literales numéricos directamente negados. Su contexto es el tipo
   de elemento built-in: `2 * Vector<double,Row>` y el orden inverso funcionan.
   Un literal izquierdo permite descubrir primero el tipo derecho durante
   checking, porque el literal no tiene efectos; HIR conserva su posición
   izquierda y MIR ejecuta los operandos en orden fuente. Expresiones escalares
   arbitrarias, llamadas, casts y variables no reciben esta contextualización.
   Los elementos no admitidos no se usan como contexto numérico.

7. **Tipo exacto.** El TypeId canónico del escalar debe ser igual al del elemento.
   `int s` con Vector<double>, int con Matrix<int8>, float64 con Matrix<float32>
   y referencias a escalares se rechazan antes de cualquier promoción.

8. **Entradas Vector.** Vector<T,O>, VectorView<T,O>, VectorViewMut<T,O>, Row y
   Column. Se prueban owners, vistas ligadas y llamadas directas vector_view y
   vector_view_mut, en ambos órdenes. Vistas mutables sólo se leen en el kernel.

9. **Entradas Matrix.** Matrix<T>, MatrixView<T>, MatrixViewMut<T>, incluyendo
   vistas ligadas y llamadas directas matrix_view/matrix_view_mut. Campos y
   elementos de Array pueden ser el Place fuente sin copiar su almacenamiento.

10. **Parejas matemáticas rechazadas.** Vector*Vector, VectorView*Vector,
    Matrix*Matrix, MatrixView*Matrix, Vector*Matrix y Matrix*Vector producen
    E0342. El mensaje identifica la pareja no admitida y exige un escalar y
    un operando vector-like/matrix-like; no anuncia una multiplicación escalar
    resuelta para esas parejas.

11. **Propiedad del resultado.** Vector<T,O> o Matrix<T> nuevos. El owner
    existente sigue disponible. Las expresiones que explícitamente producen
    un owner temporal lo prestan al kernel y reciben cleanup posterior, igual
    que V27. No hay asignación/copia de backing para adaptar una entrada.

12. **Orden de evaluación.** Las expresiones HIR left/right se conservan.
    MIR evalúa izquierda y después derecha, escogiendo lower_expr para el
    escalar y lower_math_read para el descriptor. Ambos se capturan antes de
    Allocate. Tests distinguen estados 12 y 21 para funciones escalares y
    productoras de Vector/Matrix; también comprueban captura del escalar antes
    de una llamada que modifica su variable original.

13. **Préstamos temporales.** El root de una entrada izquierda queda protegido
    contra consumo/reemplazo e invalidación estructural mientras se evalúa
    la derecha. `a*take(a)` y `column(a,1)*take(a)` se rechazan; invertirlos
    detecta uso después de Move. Se reutilizan las protecciones léxicas V27.
    La política previa permite aliases y escrituras de elementos que no
    invalidan el descriptor: `a*mutate(&mut a[1])` lee el elemento actualizado
    después de evaluar el escalar. Se prueba en ambos rangos; el kernel mismo
    sólo lee la entrada. No se añade exclusividad de préstamos ni lifetimes.

14. **Vacíos.** Descriptor propietario canónico null/cero; cero asignaciones,
    multiplicaciones y stores. Se ejecutan ambos órdenes en Vector y Matrix
    0x0, tanto con Place como con funciones que retornan owners vacíos y
    registran efectos. La evaluación escalar no se elimina por el vacío.

15. **Stride Vector.** Lectura lógica `ptr[i*stride]`; owner aporta stride=1.
    La dimensión del único descriptor delimita el loop unitario desde cero.
    Resultado contiguo con una escritura en result[i] por iteración.

16. **Strides Matrix.** Lectura `ptr[r*row_stride+c*column_stride]`, loops
    Rows/Columns anidados, resultado row-major `r*C+c`. Owner aporta RS=C, CS=1;
    la vista conserva ambos strides. Sin recorrido físico plano de la fuente.

17. **Proyecciones row/column.** Columna segunda de [1,2,3;4,5,6;7,8,9] tiene
    stride=3: `3*c` y `c*3` dan [6,15,24]. También se ejecutan
    `column(a,2)*3` y `2*row(a,3)`. El indexado fuente permanece desde uno.

18. **Vista Matrix transpuesta.** A=[1,2;3,4], T=transpose_view(A): `2*T`
    y `T*2` dan [2,6;4,8]. `2*transpose_view(rect)` sobre 2x3 produce 3x2
    lógicamente correcto, con d[2,2]=10 y d[3,2]=12.

19. **Overflow entero.** MultiplyIntegerChecked e IntegerOverflow exactos;
    LLVM usa smul/umul.with.overflow. Se prueban los diez tipos enteros en
    Vector y Matrix: primer elemento 1*2 se inicializa y el segundo desborda.
    Sin wrapping ni flags nsw/nuw; trap abortivo, sin unwind/rollback.

20. **Floats.** MultiplyFloat se emite como IEEE fmul, sin fast-math ni
    reassociation. float32, float64, float y double se prueban separadamente,
    ambos rangos y órdenes: +0, -0, +infinito, -infinito y NaN.

21. **Genéricos.** Vector<T,Row>/Matrix<T> con T:Storable y T:Copy+Storable
    se rechazan paramétricamente con E0346 en funciones sin instancias.
    No se difiere una prueba conductual a monomorfización.

22. **HIR Vector.** VectorScalarMultiply contiene left/right, scalar_side,
    element_type y orientation. El TypeId de HirExpr es Vector propietario.
    Sustitución conserva campos y operandos. El verificador exige coherencia
    de lado, elemento, familia/orientación y lectura no consumidora.

23. **HIR Matrix.** MatrixScalarMultiply conserva left/right, scalar_side y
    element_type; TypeId Matrix<T>. La forma conocida se propaga desde el
    único operando matemático. No incorpora MathShapeCheck.

24. **Kernel MIR.** Se reutiliza Rvalue::ElementwiseBinary y ElementwiseKernel.
    scalar_side=Some(Left/Right) identifica scaling; None conserva V27.
    Programa: Allocate, For(s), InvariantScalar/StridedLoad según orden,
    ScalarBinary(Multiply), InitializeNext, YieldOwner. No ShapeGuard.
    El escalar capturado es invariante; InvariantScalar no carga memoria.

25. **Prueba de inicialización.** La comparación con el programa canónico
    completo exige loops desde cero, paso uno, dimensiones del descriptor y
    un store por coordenada. El prefijo de inicialización alcanza N/R*C
    antes de YieldOwner. No bitmap ni propietario parcial escapable. Elementos
    built-in triviales, sin destructores por slot ni cleanup tras trap.

26. **Verificador MIR.** Comprueba disponibilidad de operandos, un escalar y
    un descriptor, igualdad de TypeIds, soporte Multiply y resultado propietario
    correcto. Valida todo el árbol, allocation/traps, strides, loops, lado,
    operador e inicialización. Una entrada owner en lugar del descriptor, un
    guard de forma o un store extra invalidan el programa.

27. **SSA.** SsaOp::ElementwiseBinary transporta ambos operandos renombrados,
    el kernel y el TypeId de resultado. Los walkers existentes ya incluyen las
    dos dependencias; no fue necesario cambiar ssa.rs. La información de lado
    no se borra y For conserva los contadores estructurados hasta LLVM.

28. **Verificador SSA.** Reejecuta kernel.verify con sus propios operand/result
    TypeIds. No confía en MIR ni en un flag previo. Pruebas separadas rechazan
    fuentes propietarias, elemento/escalar distinto, lado incorrecto, Add,
    selectores stride erróneos, orientación/familia incorrecta, ShapeMismatch
    y escrituras duplicadas. No MemorySSA ni análisis global nuevo de lifetime.

29. **LLVM.** El mismo traductor recursivo V27 extrae un descriptor, toma sus
    extents, deriva vacío, asigna almacenamiento comprobado e itera. Combina
    una carga strided y el escalar con checked multiply/fmul, almacena contiguo
    y une owner completo/vacío por phi. Sin dispatcher, BLAS ni noalias.
    La región de scaling no contiene dependencia de ShapeMismatch; pueden
    existir etiquetas genéricas de trap no usadas fuera de ella, como antes.

30. **Diagnósticos.** E0342 para pareja matemática/operador fuera de alcance;
    E0343 para escalar/elemento canónico distinto; E0346 para elemento no
    built-in o T simbólico; E0218 para asignación a familia/orientación
    incompatible; diagnósticos existentes de consumo/préstamos para evaluación
    invalidante. Los tests también ejercitan escalar prestado y bool.

31. **Dumps.** HIR nombra ScalarMultiply, scalar_side, tipo y orientación.
    MIR/SSA muestran scalar_side, InvariantScalar, Allocate, For, StridedLoad,
    Multiply, InitializeNext y YieldOwner, sin ShapeMismatch. Ocho fixtures
    compilados dos veces tienen dumps HIR/MIR/SSA/LLVM idénticos. Inspección
    LLVM exige una sola carga de elemento y una llamada de asignación por
    región, asignación antes de carga, strides y ausencia de flags prohibidos.

32. **Tests exactos.** **226 tests, cero fallos**: 7 backend, 29 frontend,
    22 middle y 168 integración. Diez tests nuevos; se mantienen los 216 de V0..V27.

    | Test | Cobertura |
    |---|---|
    | vertical28_hir_rejects_scalar_side_type_and_consumption | 24 corrupciones HIR, dos rangos y órdenes |
    | vertical28_native_values_and_exact_allocation_operation_counts | nueve fixtures, valores, contadores por región y totales |
    | vertical28_all_readable_inputs_types_and_orders | 30 variantes de entrada/orientación/orden; 30 ejecutables de tipos y aliases |
    | vertical28_structured_rejections_and_temporary_borrows | 18 errores tipados, cuatro genéricos, seis consumos invalidantes y 14 elementos no admitidos |
    | vertical28_checked_overflow_after_initialized_slot | diez tipos enteros por dos rangos, original e instrumentado |
    | vertical28_ieee_floats_both_ranks_and_orders | 16 ejecuciones IEEE |
    | vertical28_mir_ssa_independently_reject_corruption | 68 corrupciones MIR y 68 SSA |
    | vertical28_deterministic_dumps_and_single_descriptor_codegen | ocho fixtures/dos compilaciones/cuatro dumps |
    | vertical28_allocation_traps_before_element_access | tamaño imposible y malloc fallido, dos rangos |
    | vertical28_noninvalidating_scalar_effects_follow_existing_alias_policy | dos ejecuciones con escritura de elemento desde el escalar |

    Comandos: `cargo test --workspace`, `cargo fmt --all --check`,
    `cargo clippy --all-targets -- -D warnings` desde compiler-next;
    `git diff --check` desde la raíz.

33. **Traps ejecutados.** 20 ejecutables enteros terminan por SIGILL (señal 4).
    Sus 20 variantes salen con 74 sólo después de comprobar un store previo
    y alcanzar IntegerOverflow. Cuatro probes salen con 75/76 en
    AllocationSizeOverflow/AllocationFailure y confirman sólo la asignación
    previa de la entrada. Extents imposibles y fallo malloc se inyectan sólo
    en LLVM de tests. Total dedicado V28: **131 ejecuciones nativas**.

34. **Contadores alloc/free.** Para cada región no vacía: delta alloc=1,
    delta free=0. Vacíos: delta alloc=0. El wrapper verifica equilibrio final
    alloc=free y valor de retorno. Temporales explícitos se liberan después
    de la región, sin asignación auxiliar para adaptar el descriptor.

35. **Multiplicaciones/stores.** Contadores dinámicos dentro del loop exigen
    N/R*C operaciones y stores por región. Fixtures además exigen total global.

    | Fixture | Alloc = Free finales | Multiply = stores |
    |---|---:|---:|
    | vector_contiguous | 6 | 10 |
    | vector_strided | 5 | 12 |
    | matrix_contiguous | 3 | 12 |
    | matrix_transposed | 5 | 14 |
    | empty | 0 | 0 |
    | evaluation | 15 | 18 |
    | control_flow | 16 | 20 |
    | projected | 10 | 12 |
    | floats | 6 | 8 |

36. **Snapshots de compilación.** Metodología V17..V27: driver debug, proceso
    nuevo, un warmup descartado y diez muestras por fixture, sin builds/tests
    concurrentes. Core suma ocho fases parse-through-LLVM; excluye
    startup/discovery/I/O/dumps/clang/link y fases inclusivas duplicadas.
    Se preservó el binario previo en `/tmp/aether-v27-v28-baseline`; HEAD
    inicial `1e2d3e700ba9e928e3cde5db7b5dbd84aeba326d`.

    | Compilador / fixture | Core media ms | Core mediana ms |
    |---|---:|---:|
    | V27 previo / Vector V27 +/− | 2.345 | 2.328 |
    | V28 / mismo fixture V27 +/− | 1.567 | 1.510 |
    | V28 / Vector contiguo | 1.673 | 1.608 |
    | V28 / Vector strided | 2.712 | 2.573 |
    | V28 / Matrix contigua | 1.562 | 1.554 |
    | V28 / MatrixView transpuesta | 2.602 | 2.600 |

    Son snapshots descriptivos de compilación, no benchmarks de ejecución ni
    una afirmación estadística de mejora. Cada fixture contiene sus propias
    comprobaciones y puede ejecutar varios operadores. Datos y reproducción:
    [v28-debug.json](../../compiler-next/tests/timings/v28-debug.json),
    [measure-v28.py](../../compiler-next/tests/measure-v28.py).

37. **Legacy.** No se modifican compiler-rs, runtime, CLI legacy ni scrap.
    `bash compiler-next/tests/run-differential.sh`: **21 comparaciones, cero
    fallos**. Los binarios no rastreados preexistentes FaCAether/FaCAetherO0
    quedan fuera del cambio.

38. **Deuda aceptada.** Región cerrada canónica en MIR/SSA; control interno y
    phis se expanden en LLVM. La verificación no es un solver general para
    reordenar kernels. Provenance/lifetime global sigue siendo léxico; aliases
    y efectos no invalidantes siguen la política anterior. ABI bootstrap
    x86_64, traps abortivos, sin unwind ni cleanup parcial. Literales admitidos
    por contexto sintáctico, no inferencia bidireccional general.

39. **OPEN DECISIONS.** Contratos separados para dot, outer y matmul;
    capacidades conductuales; promoción; operaciones in-place; dimensiones
    estáticas/genéricas; políticas de overflow/IEEE para reducciones; ABI
    pública, BLAS, slices/submatrices y strides negativos; precisión futura
    de préstamos. No quedan admitidos por V28.

40. **Problemas arquitectónicos encontrados.** El kernel V27 asumía Left como
    descriptor de forma y dos cargas. Se generalizó explícitamente la selección
    de descriptor mediante scalar_side y se sustituyó una carga por selección
    del escalar invariante, sin duplicar loops. La captura de valores/proyecciones
    debe preceder efectos posteriores: el test cambia un índice y distingue
    qué Matrix se eligió, y otro cambia una variable escalar tras capturarla.
    La protección léxica preserva validez del backing, sin introducir
    exclusividad nueva de aliases; el resultado observa efectos escalares antes
    de su primera carga. El esquema existente de SSA ya preservaba todos los
    campos y dependencias necesarios para verificar esta extensión.

41. **Recomendación NEXT-VERTICAL-29.** Fijar un contrato explícito para dot
    sobre vectores antes de implementarlo: orientación, dimensiones, orden de
    reducción, overflow de productos/sumas e IEEE, identidad del vacío y
    verificación de acumuladores. Mantener outer/matmul, traits y BLAS como
    decisiones independientes. V28 no implementa ninguno.
