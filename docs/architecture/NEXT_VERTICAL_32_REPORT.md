# NEXT-VERTICAL-32 — native Matrix×Column and Row×Matrix algebraic multiplication

Implementado en `compiler-next`, Linux x86_64, 2026-09-09. Ambas direcciones
producen Vector propietario con orientación exacta, aceptan vistas strided y
mantienen separadas la extensión del resultado y la extensión de contracción.
Una contracción vacía **no** convierte un resultado no vacío en Vector(0).
**274 tests aprobados, cero fallos; 21 comparaciones legacy aprobadas.**

1. **Tabla algebraica inicial.** V31 admitía scalar×Vector, Vector×scalar,
   scalar×Matrix, Matrix×scalar, Row(n)×Column(n)->T y
   Column(n)×Row(p)->Matrix(n,p). V32 agrega exactamente las dos últimas filas
   de esta tabla vigente:

   | Operandos | Resultado |
   |---|---|
   | scalar × Vector / Vector × scalar | Vector propietario de igual orientación |
   | scalar × Matrix / Matrix × scalar | Matrix propietario |
   | Row(n) × Column(n) | T |
   | Column(n) × Row(p) | Matrix<T>(n,p) |
   | Matrix<T>(m,n) × Column<T>(n) | Vector<T,Column>(m) |
   | Row<T>(m) × Matrix<T>(m,n) | Vector<T,Row>(n) |

2. **Archivos cambiados.** Rutas relativas a la raíz:

   | Archivo | Cambio |
   |---|---|
   | `compiler-next/crates/aether-frontend/src/hir.rs` | variante MatrixVector, selectores, resolución, capacidades, sustitución, formas conocidas, verificador y corrupciones HIR |
   | `compiler-next/crates/aether-frontend/src/lib.rs` | exportación MatrixProductExtent |
   | `compiler-next/crates/aether-middle/src/algebraic.rs` | dos kernels, guard de ejes diferentes, selectores, bypass y verificación cerrada |
   | `compiler-next/crates/aether-middle/src/mir.rs` | lowering de las dos variantes y Zero concreto |
   | `compiler-next/crates/aether-backend-llvm/src/algebraic.rs` | descriptores de distinto rango, loops anidados, phi interior, strides y resultado Vector |
   | `compiler-next/crates/aether-backend-llvm/src/lib.rs` | trap ShapeMismatch para los nuevos kernels |
   | `compiler-next/crates/aether-driver/tests/vertical.rs` | registro V32 y diagnóstico V28 actualizado |
   | `compiler-next/crates/aether-driver/tests/vertical31/mod.rs` | negativos actualizados a orientaciones que siguen rechazadas |
   | `compiler-next/crates/aether-driver/tests/vertical32/mod.rs` | ejecución, costes, diagnósticos, corrupciones MIR/SSA, traps, IEEE y módulos |
   | `compiler-next/tests/programs/v32_matrix_column.ae` | propietario rectangular int |
   | `compiler-next/tests/programs/v32_row_matrix.ae` | propietario rectangular double |
   | `compiler-next/tests/programs/v32_matrix_column_strided.ae` | Matrix transpuesta y Column stride=2 |
   | `compiler-next/tests/programs/v32_row_matrix_strided.ae` | Matrix transpuesta y Row stride=2 |
   | `compiler-next/tests/programs/v32_generic_int.ae` | forwarding Matrix×Column int strided |
   | `compiler-next/tests/programs/v32_generic_double.ae` | forwarding Row×Matrix double strided |
   | `compiler-next/tests/programs/v32_zero_axes.ae` | cuatro formas vacías y sus transpuestas |
   | `compiler-next/tests/modules/v32_products/{helper,main}.ae` | forwarding de ambas direcciones entre módulos y alias strided |
   | `compiler-next/tests/modules/v1-contract.tsv` | contrato modular V32 |
   | `compiler-next/tests/measure-v32.py` | metodología de snapshots V17/V31 |
   | `compiler-next/tests/timings/v32-debug.json` | mediciones y entorno |
   | `compiler-next/README.md` | tabla completa y contrato actual |
   | `docs/architecture/AETHER_V1_LANGUAGE_CHARTER.md` | admisión V32 |
   | `docs/architecture/AETHER_V1_SEMANTIC_CONTRACT.md` | contrato normativo V32 |
   | `docs/architecture/AETHER_COMPILER_ARCHITECTURE.md` | confirmación 49 |
   | `docs/architecture/NEXT_VERTICAL_32_REPORT.md` | este informe |

   SSA reutiliza su integración VectorProduct existente: no requiere editar
   `ssa.rs`, porque renombra operandos y llama al verificador ampliado del kernel.

3. **Formas fuente admitidas.** Matrix/MatrixView/MatrixViewMut ×
   Vector/VectorView/VectorViewMut Column, y las tres formas Row × las tres
   formas Matrix. Las 18 combinaciones se ejecutan con los 15 nombres de tipos
   numéricos/aliases probados. Los owners se leen mediante préstamos.

4. **Contrato Matrix×Column.** Para A(m,n), x(n), `y[i]` es la reducción
   ordenada de A[i,j]*x[j] sobre j=1..n. Devuelve Column(m).

5. **Contrato Row×Matrix.** Para r(m), A(m,n), `y[j]` es la reducción
   ordenada de r[i]*A[i,j] sobre i=1..m. Devuelve Row(n). No se intercambia
   el orden de los factores para favorecer el layout.

6. **Pares rechazados.** Matrix×Row, Column×Matrix, Matrix×Matrix, Row×Row y
   Column×Column mantienen E0342, incluso con dimensiones uno. Sin dot Vector,
   dot Array/List, Hadamard, función matmul, One o impl de usuario.

7. **Elemento exacto.** Ambos elementos comparten el mismo TypeId canónico T;
   resultado T exacto. E0343 ante diferencia. Sin promoción, heterogeneidad ni
   acumulador ampliado. Aliases transparentes conservan identidad canónica.

8. **Orientación y tipo del resultado.** Siempre Vector propietario Column
   para Matrix izquierda, Row para Matrix derecha. Nunca View, escalar o Matrix.
   Descriptor normal V21 `{ptr,dimension}`; orientación sólo en TypeId/mangling.
   Asignar el resultado a una orientación/familia distinta falla por tipo.

9. **Requisitos genéricos.** Storable, Copy, Add, Mul y Zero se prueban de forma
   independiente. Storable justifica almacenar el resultado; Copy justifica
   lecturas por valor; Mul forma términos; Add reduce; Zero inicializa. No se
   agrega ninguna implicación entre garantías ni maquinaria runtime.

10. **Compatibilidad.** A.columns=x.dimension o r.dimension=A.rows. Ownership
    detecta incompatibilidades conocidas con E0345. ShapeGuardPair dinámico es
    el primer paso de la región, antes de asignación y accesos, incluso si el
    resultado tiene extensión cero. Cuatro casos dinámicos comprueban esta
    dominancia con trap real y con contadores en la rama de error.

11. **Extensión del resultado.** A.rows para Matrix×Column, A.columns para
    Row×Matrix. Controla el bypass, tamaño de backing y límite exterior.

12. **Extensión de contracción.** A.columns para Matrix×Column, A.rows para
    Row×Matrix. Controla únicamente el límite interior; puede ser cero aunque
    el resultado tenga slots que inicializar.

13. **Contracción cero Matrix×Column.** A(m,0)×Column(0) produce Column(m),
    con m ceros y una asignación cuando m>0. Cero Mul/Add, m stores.

14. **Resultado cero Matrix×Column.** A(0,n)×Column(n) produce Column(0)
    canónico, sin allocator, stores, Mul ni Add.

15. **Contracción cero Row×Matrix.** Row(0)×A(0,n) produce Row(n), con n
    ceros y una asignación cuando n>0. Cero Mul/Add, n stores.

16. **Resultado cero Row×Matrix.** Row(m)×A(m,0) produce Row(0) canónico,
    sin allocator ni trabajo de elementos. Todas las variantes se ejecutan
    con double e int, incluyendo formas creadas por productos V31.

17. **Orden de reducción.** Cada salida comienza con Zero y recorre el eje
    lógico creciente, start=0/step=1 interno. Cada iteración multiplica primero
    y suma después. Nunca se usa el primer producto como semilla.

18. **Conteos de operaciones.** Para m,n generales ambas direcciones hacen
    m*n Mul, m*n Add y 2*m*n cargas. Stores=m o n según la dirección. El número
    de productos no determina el número de stores en contracciones vacías.

19. **Strides Matrix.** Offset i*RowStride+j*ColumnStride, ambos campos del
    descriptor de lectura. Owner utiliza RS=columns/CS=1; las vistas conservan
    sus strides explícitos. No se aplana el backing físico.

20. **Stride Vector.** Offset k*Stride. Los fixtures emplean columnas V26
    stride=2 y su transpose_view Row, sin Vector propietario temporal.

21. **MatrixView transpuesta.** A=[1,2,3;4,5,6] transpuesta tiene forma 3×2
    y strides intercambiados. Multiplicada por Column [2,3] da [14,19,24].
    Row [2,3,4] por esa vista da [20,47]. Las transpuestas de 3×0 y 0×4
    conservan ejes exactos y satisfacen las cuatro reglas de vacío.

22. **Genéricos strided.** Helpers con parámetros MatrixView y VectorView
    reciben ambos descriptores strided y retornan owners. Fixtures int/double
    hacen forwarding anidado; el test de todas las familias instancia ambas
    direcciones para cada tipo numérico y mutabilidad.

23. **Overflow del producto.** MultiplyIntegerChecked usa smul/umul con el
    ancho de T. max*2 dispara IntegerOverflow para diez enteros y ambas
    direcciones: 20 ejecuciones separadas.

24. **Overflow acumulado.** Productos max*1 y 1*1 caben; la segunda suma
    desborda. AddIntegerChecked conserva el ancho y dispara otros 20 traps.
    Casos finitos signed y unsigned comprueban resultados sin widening.

25. **IEEE.** float32/float64 comprueban finitos, -0, +0 inicial, infinito,
    NaN y [2^p,1,-2^p] con p=24/53, para ambas direcciones y dos salidas.
    Se inspecciona fmul antes de fadd y ausencia de fast/reassoc/contract,
    FMA/fmuladd y BLAS. El cero de contracción vacía se comprueba también
    mediante el signo de su recíproco.

26. **Alias, evaluación y ownership.** lhs se evalúa y protege durante rhs.
    Un contador fuente distingue orden 12 de 21 en ambas direcciones. Se
    aceptan modificaciones de slots compatibles con préstamos existentes y
    se rechazan consumo/reemplazo del root izquierdo. Los temporales owner
    viven hasta completar el producto y reciben cleanup normal. Los inputs
    siguen utilizables y el resultado tiene backing independiente.

27. **Forwarding.** Llamadas inferidas, helpers genéricos con owners por ref,
    vistas compartidas/mutables y forwarding entre módulos. El fixture modular
    comparte el mismo Matrix como vista transpuesta y proyección strided,
    prueba ambos resultados y mantiene el backing fuente utilizable.

28. **Cuerpos sin instancias.** Se validan antes de monomorfizar. Faltantes
    de cada una de las cinco garantías se rechazan tanto en el producto directo
    como al reenviar a otro helper, aun cuando main no llama al cuerpo.

29. **HIR simbólico.** VectorAlgebraicProduct contiene el par fuente y Mul;
    VectorProduct::MatrixVector conserva matrix_side, shape_check,
    result_extent, contraction_extent, Add y Zero tipado. Capacidades siguen
    siendo evidencia del parámetro en TypeArena. La receta se reconstruye en
    verificación, incluyendo familia, orientación y resultado propietario.

30. **Monomorfización.** Sustitución reutiliza la autoridad V29/V31:
    Behavioral(Mul/Add) se concreta a operación checked/float y AlgebraicValue
    Zero se convierte en Int(0) o FloatValue con bits positivos cero de T.
    Ninguna capacidad cruza la frontera concreta. Orden de garantías no cambia
    LLVM ni ABI.

31. **MIR map-reduction.** MatrixColumnKernel/RowMatrixKernel contienen
    ShapeGuardPair, dos SelectSourceExtent, EmptyResultBypass(resultado),
    Allocate(resultado), For(resultado), AccumulatorInit, For(contracción),
    dos StridedLoad, ScalarBinary(Mul), Accumulate(Add), InitializeNext y
    YieldOwner. No se fabrica código fuente ni se llama row()/column().

32. **Inicialización.** Un único acumulador por salida y un único store al
    salir del loop interior, incluso si ejecutó cero veces. El owner sólo sale
    después del loop exterior. No bitmap, source Move/drop/write ni resultado
    parcialmente inicializado observable. Los traps continúan siendo abortivos.

33. **Verificador MIR.** Resuelve tipos de operandos y destino, exige
    descriptores de lectura y owner Vector exacto, y compara el árbol completo
    con el schedule cerrado. Rechaza ejes, strides, operaciones, cero, guard,
    orden de asignación, cadenas de acumulación e inicialización incorrectos.

34. **SSA.** La infraestructura existente renombra operandos externos y
    preserva la región cerrada concreta. El acumulador es un binding interno
    de la reducción; no se introduce MemorySSA ni metadata de capacidades.

35. **Verificador SSA.** Resuelve sus propios operandos/destino y vuelve a
    validar el árbol entero; no confía en que MIR haya pasado. Las corrupciones
    SSA se aplican después de construirlo desde MIR válido.

36. **LLVM.** Extrae cinco campos MatrixView y tres VectorView. Genera guard,
    bypass por resultado, llamada al helper fijo de asignación comprobada,
    loops anidados, un phi de acumulación en el loop interior, cargas strided,
    Mul/Add y store contiguo. El phi recibe Zero en cada entrada exterior. No
    helper matvec, BLAS, dispatch ni materialización de transpuestas.

37. **Contadores de asignación.** Instrumentación exclusiva de tests mide
    deltas reales entre AlgebraicBegin/End, después de evaluar inputs:

    | Región | Alloc | Mul | Add | Stores |
    |---|---:|---:|---:|---:|
    | Matrix(m,n)×Column(n) | 1 iff m>0 | m*n | m*n | m |
    | Row(m)×Matrix(m,n) | 1 iff n>0 | m*n | m*n | n |
    | Contracción cero, salida k>0 | 1 | 0 | 0 | k |
    | Salida cero | 0 | 0 | 0 | 0 |
    | ShapeMismatch | 0 | 0 | 0 | 0 |

    Free/relocation delta dentro de la región es cero. Cada fixture no vacío
    asigna/libera tres backings; zero_axes asigna/libera seis: dos vectores
    fuente y cuatro resultados no vacíos. El programa de 18 combinaciones
    asigna/libera 21 backings. No se deduce coste contando instrucciones LLVM.

38. **Diagnósticos.** E0342 pairing algebraico no admitido; E0343 elementos
    distintos; E0345 contracción conocida incompatible; E0346 capacidades
    algebraicas faltantes. Formación de Vector<T> mantiene su error Storable;
    forwarding conserva E0316/E0317. Tipo/orientación de destino incorrecto
    falla E0218. Metadata HIR genérica/concreta y schedules MIR/SSA se rechazan
    en sus respectivas fronteras estructuradas, sin usar lenguaje de dot.

39. **Dumps.** HIR genérico expone variante, forma, ambos selectores, Mul/Add
    simbólicos y Zero. Instanciado expone operaciones y cero concretos. MIR/SSA
    muestran la región y sus dependencias; LLVM muestra nested CFG. Dos
    compilaciones de cada fixture genérico comparan todos los dumps y LLVM;
    reordenar Storable+Copy+Add+Mul+Zero conserva LLVM byte a byte.

40. **Tests exactos.** Los 13 tests nuevos son:

    | Test | Ubicación/cobertura |
    |---|---|
    | `vertical32_hir_corruption_and_erased_guarantees` | frontend, metadata simbólica/concreta y cinco garantías |
    | `vertical32_native_fixtures_and_exact_costs` | siete fixtures y contadores |
    | `vertical32_all_readable_families_and_builtin_scalars` | 18 combinaciones × 15 nombres numéricos |
    | `vertical32_parametric_constraints_diagnostics_and_forwarding` | pares, elementos, formas y requisitos |
    | `vertical32_integer_product_and_accumulator_overflow` | 40 traps y signed finitos |
    | `vertical32_ieee_order_zero_infinity_nan` | dos precisiones y ambas direcciones |
    | `vertical32_mir_ssa_independent_corruption_rejection` | 120 corrupciones de frontera |
    | `vertical32_dynamic_mismatch_guard_dominates_even_empty_result` | cuatro incompatibilidades y contadores |
    | `vertical32_alias_evaluation_temporaries_and_nonconsuming_owners` | orden, efectos, temporales y reemplazo/consumo |
    | `vertical32_deterministic_dumps_and_constraint_order_abi` | dumps y ABI |
    | `vertical32_cross_module_strided_products` | ambas direcciones entre módulos |
    | `vertical32_allocation_traps_precede_element_access` | size overflow y fallo allocator, ambas direcciones |
    | `vertical32_integer_zero_axes_and_shared_projections` | ejes cero enteros y proyecciones row/column |

41. **Corrupciones.** HIR: 28 alteraciones de receta simbólica, 10 borrados
    coordinados de garantías en declaración/arena y 48 corrupciones concretas:
    **86**. Incluyen orientación, familia, tipo, selectores intercambiados,
    shape-check removido semánticamente, Mul/Add cambiados y Zero incorrecto.
    MIR/SSA: 30 casos × 2 direcciones × 2 fronteras = **120**, con asignación o
    bypass sobre contracción, loops ausentes/límites incorrectos, strides,
    fuentes, Zero, orden Mul/Add, inicialización faltante/duplicada, scalar yield
    y guard posterior a Allocate. Total: **206 corrupciones rechazadas**.

42. **Ejecuciones y traps.** El conjunto V32 ejecuta 97 binarios nativos:
    40 IntegerOverflow y cuatro ShapeMismatch con SIGILL; cuatro ejecuciones
    instrumentadas de esas incompatibilidades comprueban cero trabajo previo;
    cuatro inyecciones LLVM de asignación comprueban AllocationSizeOverflow o
    AllocationFailure y cero cargas/Mul/Add/stores previos; 45 éxitos restantes
    comprueban resultados, coste, ownership e IEEE. Las inyecciones de extents
    imposibles/fallo malloc existen sólo en tests, no en el compilador.

43. **Snapshots de compilación.** Metodología V17/V31: driver debug, proceso
    nuevo por muestra, un warmup descartado y diez muestras por fixture. Core
    suma parse, signatures, semantic bodies, MIR lowering/verification, SSA
    build/verification y LLVM; excluye startup, I/O/dumps, clang/link y timers
    inclusivos duplicados. Se ejecuta sin builds/tests concurrentes. Baseline
    V31 reconstruido con git archive de
    `a1a8f480044e0fcab9266b211613525e28c9bffc` en `/tmp`.

    | Compilador / fixture | Core media ms | Core mediana ms |
    |---|---:|---:|
    | V31 baseline / v31_inner_concrete | 1.438 | 1.406 |
    | V32 / v31_inner_concrete | 1.194 | 1.123 |
    | V32 / v32_generic_double | 1.726 | 1.653 |
    | V32 / v32_generic_int | 1.652 | 1.539 |
    | V32 / v32_matrix_column | 1.821 | 1.734 |
    | V32 / v32_matrix_column_strided | 1.597 | 1.541 |
    | V32 / v32_row_matrix | 1.753 | 1.651 |
    | V32 / v32_row_matrix_strided | 1.540 | 1.471 |
    | V32 / v32_zero_axes | 7.651 | 7.540 |

    Datos completos y entorno: [v32-debug.json](../../compiler-next/tests/timings/v32-debug.json).
    Son snapshots descriptivos de compilación, no benchmarks runtime ni prueba
    estadística de mejora. Los fixtures incluyen comprobaciones; zero_axes
    incluye varias operaciones y no es comparable a una expresión aislada.
    Reproducción desde la raíz:

    ```sh
    python3 compiler-next/tests/measure-v32.py --runs 10 \
      --baseline-binary /tmp/aether-v32-baseline-source/compiler-next/target/debug/aether-next \
      --baseline-revision a1a8f480044e0fcab9266b211613525e28c9bffc
    ```

44. **Regresión y legacy.** `cargo test --workspace` final: **274 aprobados,
    cero fallos** (7 backend, 206 integración, 39 frontend y 22 middle).
    V0..V31 conserva productos, scaling, +/−, transposición y
    proyecciones. V28 actualiza el error de Row×Matrix asignado a Matrix: ahora
    es E0218 por resultado incorrecto, pues el producto sí es válido. Dos
    negativos V31 usan las orientaciones que siguen prohibidas. Differential:
    **21 comparaciones, cero fallos**. `cargo fmt --all --check`,
    `cargo clippy --all-targets -- -D warnings` y `git diff --check` pasan.
    No se modifican compiler-rs, runtime/CLI legacy ni scrap. FaCAether y
    FaCAetherO0 son binarios no rastreados preexistentes ajenos al cambio.

45. **Deuda aceptada.** Se conserva la verificación por comparación de un
    schedule cerrado común a MIR/SSA. La región se convierte en CFG exterior
    recién en LLVM. Los nombres VectorAlgebraicProduct/VectorProductKernel
    son históricos y ahora contienen explícitamente variantes de rango mixto.
    Se reutiliza el helper estático de almacenamiento, sin helper algebraico.
    Bootstrap Linux x86_64, escalares built-in homogéneos y traps abortivos.

46. **OPEN DECISIONS.** Matrix×Matrix queda pendiente con su contrato propio;
    no se generaliza automáticamente esta implementación. One, impl de usuario,
    heterogeneidad, widening, Complex/Hermitian, orientación genérica y cambios
    de orden/BLAS/SIMD siguen abiertos. dot de secuencias no está implementado.
    No queda una decisión abierta necesaria para las dos formas V32.

47. **Problemas arquitectónicos encontrados.** La asignación por número total
    de términos de un producto no sirve para mapas de reducciones: m*n puede
    ser cero con m/n salidas no vacías. V32 expresa el bypass por resultado.
    Además, el emisor V31 creaba un phi en cada For cuando había Zero; en V32
    el acumulador debe ligarse sólo al For interior y reiniciarse por salida.
    StridedLoad V31 asumía un término de offset; ahora traduce la suma de los
    dos términos Matrix. Las formas cero V31 y los préstamos existentes no
    necesitaron cambios de semántica ni materialización de vistas.

48. **Recomendación NEXT-VERTICAL-33.** Considerar Matrix<T>(m,k)×Matrix<T>(k,n)
    como una vertical separada: resultado Matrix(m,n), guard de contracción,
    doble extensión de salida y reducción ordenada sobre k, con caso crítico
    k=0 y m,n>0, strides y verificadores/coste independientes. Mantener alcance
    homogéneo built-in sin FMA/BLAS ni widening. Descomposiciones avanzadas
    pertenecen a futura LinearAlgebra STD; V32 no las introduce.
