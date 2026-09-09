# NEXT-VERTICAL-33 — native Matrix×Matrix algebraic multiplication

Implementado en `compiler-next`, Linux x86_64, 2026-09-09. Native `*` completa
la tabla básica con Matrix(m,k)×Matrix(k,n)->Matrix(m,n), incluidas las nueve
combinaciones de propietarios/vistas y la contracción cero con salida no vacía.
**287 tests aprobados, cero fallos; 21 comparaciones legacy aprobadas.**

1. **Tabla inicial y tabla completa.** V32 admitía todas las filas siguientes
   salvo la última, que agrega V33:

   | Operandos | Resultado |
   |---|---|
   | scalar × Vector / Vector × scalar | Vector propietario de igual orientación |
   | scalar × Matrix / Matrix × scalar | Matrix propietaria |
   | Row(n) × Column(n) | T |
   | Column(n) × Row(p) | Matrix<T>(n,p) |
   | Matrix<T>(m,k) × Column<T>(k) | Vector<T,Column>(m) |
   | Row<T>(k) × Matrix<T>(k,n) | Vector<T,Row>(n) |
   | Matrix<T>(m,k) × Matrix<T>(k,n) | Matrix<T>(m,n) |

   Row×Row, Column×Column, Matrix×Row y Column×Matrix siguen rechazados,
   incluyendo dimensión uno. No hay nuevas familias de operadores.

2. **Archivos cambiados.** Rutas relativas a la raíz:

   | Archivo | Cambio |
   |---|---|
   | `compiler-next/crates/aether-frontend/src/hir.rs` | variante MatrixAlgebraicProduct, selección nativa, tres extensiones, formas conocidas, sustitución, verificación y corrupciones HIR |
   | `compiler-next/crates/aether-middle/src/algebraic.rs` | MatrixMatrixKernel, bypass 2D, schedule, verificación y eje explícito del acumulador |
   | `compiler-next/crates/aether-middle/src/elementwise.rs` | MathAxis::Contraction |
   | `compiler-next/crates/aether-middle/src/mir.rs` | lowering del nuevo kernel y reutilización de Zero concreto |
   | `compiler-next/crates/aether-backend-llvm/src/algebraic.rs` | dos descriptores Matrix, tres loops, phi de reducción y owner vacío con forma exacta |
   | `compiler-next/crates/aether-driver/tests/vertical.rs` | registro V33 y negativos históricos de tipo de resultado |
   | `compiler-next/crates/aether-driver/tests/vertical31/mod.rs` | negativo Matrix×Matrix actualizado a destino Vector incorrecto |
   | `compiler-next/crates/aether-driver/tests/vertical32/mod.rs` | mismo ajuste del negativo histórico |
   | `compiler-next/crates/aether-driver/tests/vertical33/mod.rs` | valores, capacidades, costes, traps, corrupción MIR/SSA, módulos, ownership e IEEE |
   | `compiler-next/tests/programs/v33_rectangular.ae` | signed 2×3 por 3×4 con ocho valores verificados |
   | `compiler-next/tests/programs/v33_one_cell.ae` | resultado Matrix(1,1) |
   | `compiler-next/tests/programs/v33_strided.ae` | MatrixView×MatrixView, izquierda transpuesta |
   | `compiler-next/tests/programs/v33_left_transposed.ae` | vista izquierda transpuesta por owner |
   | `compiler-next/tests/programs/v33_right_transposed.ae` | owner por vista derecha transpuesta |
   | `compiler-next/tests/programs/v33_both_transposed.ae` | ambos descriptores transpuestos no contiguos |
   | `compiler-next/tests/programs/v33_generic_int.ae` | forwarding local int con dos transpuestas |
   | `compiler-next/tests/programs/v33_generic_double.ae` | forwarding local double con dos transpuestas |
   | `compiler-next/tests/programs/v33_zero_contraction.ae` | 2×0 por 0×3, seis ceros |
   | `compiler-next/tests/programs/v33_zero_axes.ae` | 0×4, 4×0, 2×0 y 0×0, incluidas vistas |
   | `compiler-next/tests/modules/v33_products/helper.ae` | helper genérico Matrix×Matrix |
   | `compiler-next/tests/modules/v33_products/main.ae` | forwarding modular con alias y transposición |
   | `compiler-next/tests/modules/v1-contract.tsv` | registro del caso modular |
   | `compiler-next/tests/measure-v33.py` | snapshots con metodología V17/V32 |
   | `compiler-next/tests/timings/v33-debug.json` | mediciones y entorno |
   | `compiler-next/README.md` | tabla completa, contrato y ejemplos |
   | `docs/architecture/AETHER_V1_LANGUAGE_CHARTER.md` | admisión V33 |
   | `docs/architecture/AETHER_V1_SEMANTIC_CONTRACT.md` | contrato normativo V33 |
   | `docs/architecture/AETHER_COMPILER_ARCHITECTURE.md` | confirmación 50 |
   | `docs/architecture/NEXT_VERTICAL_33_REPORT.md` | este informe |

   SSA reutiliza su integración existente de VectorProduct: renombra operandos
   y llama al verificador ampliado. No necesita cambios en `ssa.rs`.

3. **Formas fuente admitidas.** Ambos lados aceptan independientemente
   Matrix<T>, MatrixView<T> y MatrixViewMut<T>: las nueve combinaciones se
   instancian y ejecutan para 15 nombres numéricos/aliases. Los owners se leen
   mediante préstamos; las vistas mutables son fuentes de lectura.

4. **Contrato algebraico.** A(m,k)×B(k,n) produce C(m,n), con
   C[i,j]=Σ A[i,l]*B[l,j], l creciente. Es el operador nativo `*`, sin función
   matmul, expansión row()/column() ni Vector propietario intermedio.

5. **Elemento.** TypeId canónico T idéntico en ambos lados y resultado.
   Sin promoción int/float, mezcla de anchos, heterogeneidad ni acumulador
   ampliado. Un struct con campos numéricos no deriva Add/Mul/Zero.

6. **Familia y tipo del resultado.** Siempre Matrix<T> propietaria y fresca.
   Nunca View, Vector o escalar. El backing es independiente de las fuentes.

7. **Compatibilidad.** lhs.columns==rhs.rows. E0345 estático cuando se conoce;
   ShapeMismatch dinámico antes del bypass, asignación y accesos/operaciones.
   Se prueba 0×3 por 4×0: debe fallar aunque la salida tendría cero elementos.

8. **Filas de salida.** Selector HIR (Left,Rows); MIR selecciona lhs.Rows
   explícitamente. Controla el bucle exterior y el primer campo de forma.

9. **Columnas de salida.** Selector HIR (Right,Columns); MIR selecciona
   rhs.Columns. Controla el segundo bucle, forma y paso row-major del resultado.

10. **Contracción.** Selector HIR (Left,Columns), comprobado contra rhs.Rows;
    MIR usa MathAxis::Contraction independiente. Controla sólo el tercer bucle.
    No se sustituye por el número de elementos ni por el número de términos.

11. **Garantías genéricas.** Storable justifica almacenamiento propietario;
    Copy la lectura por valor; Mul el término; Add la acumulación; Zero la
    semilla. Se exigen las cinco independientemente, sin implicaciones nuevas.

12. **Zero.** Reutiliza AlgebraicCapability::Zero de V31. HIR genérico conserva
    AlgebraicValue(Zero) tipado; tras sustitución hay Int(0), Float32 con bits
    cero o Float64 con bits cero. Sin representación runtime de capacidades.

13. **Contracción cero.** 2×0 por 0×3 produce Matrix(2,3), una asignación,
    seis stores de Zero, cero cargas de elementos, cero Mul y cero Add. Se
    ejecuta con int, float32 y double y se comprueban las seis celdas.

14. **Cero filas.** 0×3 por 3×4 produce {null,0,4}. No allocator, stores,
    cargas, Mul/Add; la igualdad de contracción ya se validó.

15. **Cero columnas.** 2×3 por 3×0 produce {null,2,0}. También se prueba
    4×3 por 3×0 mediante transpuestas. 0×0 por 0×0 y 0×3 por 3×0 conservan
    0×0. Nunca se borra el eje no nulo de una forma vacía.

16. **Distinción 1×1.** Matrix(1,3) por Matrix(3,1) produce Matrix(1,1)
    con valor 32. Asignarlo a int o Vector falla por tipo. La composición
    compara además Row×Column escalar contra Matrix(1,1) sin confundir tipos.

17. **Orden de reducción.** Cada celda comienza en Zero y ejecuta k pasos
    l=0..k-1 crecientes, con Mul antes de Add. Se conserva la primera suma al
    cero; no se inicializa desde el primer producto.

18. **Orden de salida.** Filas crecientes, dentro columnas crecientes, dentro
    contracción creciente. No hay intercambio de bucles ni reducción en árbol.

19. **Conteos de operaciones.** m*k*n Mul, m*k*n Add, 2*m*k*n cargas y m*n
    stores. El caso k=0 mantiene los stores; m=0 o n=0 elimina todo el trabajo
    de elementos. Los tests comprueban contadores ejecutados, no estimaciones
    a partir del texto LLVM.

20. **Overflow del producto.** Diez tipos enteros comprueban max*2 con trap
    IntegerOverflow real. MultiplyIntegerChecked conserva signedness y ancho.

21. **Overflow acumulado.** Los mismos diez tipos comprueban max*1+1*1:
    ambos productos caben y la suma desborda. AddIntegerChecked tiene su
    propio control de overflow, sin widening, wrapping, nsw/nuw nuevos.

22. **IEEE.** float32/float64 ejecutan rectangulares, -0, infinito, NaN y
    [2^p,1,-2^p] con p=24/53 en cuatro salidas. El resultado ordenado es cero.
    Se comprueba el signo positivo de la semilla mediante recíproco y el cero
    de contracción vacía. LLVM tiene fmul seguido por fadd y un phi interior;
    sin fast, reassoc, contract, fma/fmuladd, BLAS o noalias en la región.

23. **Strides izquierdos.** Dirección i*lhs.RowStride+l*lhs.ColumnStride.
    Owner se adapta al descriptor RS=columns, CS=1; vistas mantienen campos.

24. **Strides derechos.** Dirección l*rhs.RowStride+j*rhs.ColumnStride,
    independiente de la izquierda. No se aplana ninguna fuente.

25. **Izquierda transpuesta.** El fixture 3×2 transpuesto a 2×3 por owner
    3×2 produce [22,28;49,64]. También se ejecuta en ambas precisiones float.

26. **Derecha transpuesta.** Owner 2×3 por vista de 2×3 transpuesta a 3×2
    produce los mismos resultados. No se materializa una Matrix transpuesta.

27. **Ambas transpuestas.** Los dos descriptores tienen stride de columna
    distinto de uno y acceso lógico no contiguo; se verifican las cuatro
    salidas [22,28;49,64]. Cobertura int, float32/float64 y genéricos int/double.

28. **Alias, evaluación y ownership.** Un contador fuente distingue orden 12
    de 21 con dos owners temporales. Se prueban vistas mutables compartiendo
    backing, producto a*a y escritura al resultado sin cambiar a. Se rechazan
    consumo y reemplazo del owner izquierdo durante rhs, también vía vista.
    El lowering existente captura el descriptor izquierdo, evalúa rhs y limpia
    temporales después de completar la región. No se cambian lifetimes.

29. **Forwarding genérico.** Helpers locales y entre módulos reciben dos
    MatrixView<T>. El caso modular multiplica vistas transpuesta y normal del
    mismo owner y mantiene la fuente utilizable. Las nueve combinaciones usan
    también helpers genéricos con propietarios por ref y vistas mutables.

30. **Cuerpos sin uso.** Cada garantía omitida se rechaza en un helper nunca
    instanciado, tanto en multiplicación directa como al reenviar a otro helper.
    No hay comprobación de plantilla diferida a la instanciación.

31. **HIR simbólico.** VectorAlgebraicProduct es la familia histórica;
    VectorProduct::MatrixAlgebraicProduct expresa la nueva forma con shape_check,
    output_rows, output_columns, contraction_extent, Add y Zero. Mul y T están
    en el nodo exterior. Los selectores son evidencia cerrada reconstruida por
    verificación, no instrucciones arbitrarias del frontend.

32. **Monomorfización.** Reutiliza substitute_math_op y zero_value V29/V31.
    Behavioral(Mul/Add) se convierte en operación checked o float y Zero en
    constante exacta. El verificador rechaza comportamiento o valor algebraico
    simbólico en HIR concreto; MIR/SSA no contienen esas capacidades.

33. **MIR 2D.** MatrixMatrixKernel contiene ShapeGuardPair, tres
    SelectSourceExtent, EmptyMatrixResultBypass(Rows,Columns), Allocate de dos
    ejes, For(Rows)->For(Columns)->For(Contraction), cargas strided, Mul/Add,
    InitializeNext y YieldOwner. La arquitectura es una extensión directa de
    mapas de reducciones V32, sin fabricar operaciones row()/column().

34. **Ámbito del acumulador.** AccumulatorInit es el primer paso de cada celda,
    fuera del loop de contracción. reduction_axis() identifica explícitamente
    el loop que liga su phi; reinicia Zero para cada par (i,j), incluso con k=0.

35. **Inicialización.** InitializeNext aparece exactamente una vez después de
    la contracción. Su semántica existente de prefijo ordenado determina el
    store i*output_columns+j. YieldOwner sigue a la terminación del loop de
    filas. No bitmap ni owner parcialmente inicializado observable.

36. **Verificador MIR.** Resuelve tipos reales de dos descriptores Matrix,
    elemento built-in concreto y Matrix propietaria exacta. Reconstruye y compara
    el árbol completo: guard, tres selectores, bypass, asignación, loops, strides,
    cero, operaciones y única inicialización. Rechaza corrupción fail-closed.

37. **SSA.** La integración existente renombra los dos operandos externos y
    preserva el kernel concreto. Los índices/acumulador son bindings internos
    de la región. No MemorySSA ni operación genérica runtime.

38. **Verificador SSA.** Resuelve sus propios operandos y resultado, y vuelve
    a verificar el mismo contrato cerrado. Las corrupciones SSA parten de SSA
    construido desde MIR válido, independientemente de las corrupciones MIR.

39. **LLVM.** Extrae dos descriptores de cinco campos, emite guard y bypass,
    usa el helper fijo existente de almacenamiento Matrix y produce tres loops
    con un phi acumulador interior. Dos offsets independientes preceden cargas,
    Mul, Add y store row-major. No helper algebraico, BLAS ni descriptor temporal
    de fila/columna; el schedule tiene autoridad antes del backend.

40. **Descriptor vacío.** La rama vacía construye dos insertvalue de forma
    sobre el puntero nulo y une {null,lhs.rows,rhs.columns} con el owner asignado
    de la rama no vacía. No usa un zeroinitializer que borre ambos ejes.

41. **Traps de asignación.** Inyecciones LLVM exclusivas de test fuerzan
    overflow de bytes por filas, por columnas y overflow de rows*columns. Otras
    tres ejecuciones inyectan fallo malloc. Salidas distinguidas 75/76 prueban
    el trap esperado y cero cargas/Mul/Add/stores previos. La asignación mide
    únicamente salida, nunca m*n*k; no cambia el allocator de producción.

42. **Diagnósticos.** E0342 para pares no admitidos, E0343 para elemento
    canónico distinto, E0345 para contracción conocida incompatible, E0346
    para capacidades faltantes. Storable al formar Matrix<T> y restricciones
    de forwarding conservan sus diagnósticos existentes. E0218 rechaza destino
    escalar/Vector/View. El mensaje de capacidades compartido dice ahora
    «algebraic multiplication», pues también corresponde a matrices.

43. **Dumps.** HIR muestra variante MatrixAlgebraicProduct, tres selectores,
    Mul/Add simbólicos y AlgebraicValue Zero; instancias muestran operaciones
    y constantes concretas. MIR/SSA muestran MatrixMatrixKernel y la región 2D;
    LLVM muestra loops explícitos. Dos compilaciones de cada fixture genérico
    comparan todos los dumps y LLVM; reordenar garantías conserva LLVM idéntico.

44. **Tests exactos.** 13 tests nuevos:

    | Test | Cobertura |
    |---|---|
    | `vertical33_hir_corruption_and_erased_guarantees` | frontend: receta simbólica/concreta y cinco garantías |
    | `vertical33_native_fixtures_and_exact_costs` | diez fixtures, variantes int/float32 de ejes cero, contadores |
    | `vertical33_all_readable_families_and_builtin_scalars` | nueve combinaciones × 15 nombres numéricos |
    | `vertical33_parametric_constraints_diagnostics_and_forwarding` | cinco garantías, cuerpos sin uso, tipos, formas y pares |
    | `vertical33_integer_product_and_accumulator_overflow` | 20 traps separados de producto/acumulación |
    | `vertical33_ieee_order_zero_infinity_nan_and_transposes` | ambas precisiones, orden, especiales y strides |
    | `vertical33_alias_evaluation_temporaries_and_nonconsuming_owners` | alias, orden, backing independiente y rechazo de invalidación |
    | `vertical33_deterministic_dumps_and_constraint_order_abi` | dumps repetidos y orden de garantías |
    | `vertical33_cross_module_strided_products` | forwarding entre módulos con alias |
    | `vertical33_composition_preserves_result_families` | comparación V31/V32 conservando Matrix/Vector/escalar |
    | `vertical33_mir_ssa_independent_corruption_rejection` | árbol y tipos, aplicados a cada frontera |
    | `vertical33_allocation_traps_precede_element_access` | tres overflows de tamaño y tres fallos allocator |
    | `vertical33_dynamic_mismatch_guard_dominates_empty_result` | cuatro formas dinámicas y guard instrumentado |

    `cargo test --workspace`: 7 backend, 218 integración, 40 frontend y 22 middle,
    total 287. Tras ampliar dos corrupciones de tipo y ajustar un fixture strided,
    se volvió a ejecutar V33 completo; tras mejorar el mensaje compartido se
    repitieron los tests paramétricos de V31/V32/V33. Todos pasan.
    `cargo fmt --all --check`, `cargo clippy --workspace --all-targets -- -D warnings`
    y `git diff --check` pasan.

45. **Corrupciones.** HIR: 17 simbólicas + cinco borrados coordinados de
    garantías en firma/arena + ocho concretas × cuatro tipos = **54**.
    Incluyen tres selectores y sus lados, shape-check, familia/elemento,
    Mul/Add, Zero incorrecto/negativo/simbólico y Move de cada owner.
    MIR/SSA: 46 alteraciones × int/double × dos fronteras = **184**. Incluyen
    guard tardío, par incorrecto, tres selectores, bypass por contracción,
    asignación por términos, loops ausentes/invertidos/límites incorrectos,
    strides/coordenadas/fuentes, operaciones, cero, acumulador compartido,
    store faltante/duplicado/dentro de contracción, yield escalar/prematuro,
    operandos sin descriptor y tipos de resultado Vector/Matrix de otro elemento.
    Total **238 corrupciones rechazadas**. Fuente Move/drop/write no tiene
    instrucción representable en el vocabulario cerrado de la región.

46. **Ejecuciones y traps.** Los tests V33 ejecutan 83 binarios: 20
    IntegerOverflow y cuatro ShapeMismatch con SIGILL; cuatro variantes
    instrumentadas de los mismatches comprueban cero trabajo previo; seis
    inyecciones de asignación distinguen el trap y comprueban precedencia;
    49 ejecuciones exitosas restantes comprueban valores, costes, ownership,
    composición e IEEE. No se cuentan compilaciones de diagnósticos/dumps como
    ejecuciones runtime.

47. **Contadores runtime.** Se instrumenta sólo entre AlgebraicBegin/End,
    después de evaluar inputs; extracción del descriptor no es carga de elemento.

    | Región | Alloc | Mul | Add | Loads | Stores |
    |---|---:|---:|---:|---:|---:|
    | m,k,n positivos | 1 | m*k*n | m*k*n | 2*m*k*n | m*n |
    | k=0, m,n positivos | 1 | 0 | 0 | 0 | m*n |
    | m=0 o n=0, compatible | 0 | 0 | 0 | 0 | 0 |
    | ShapeMismatch | 0 | 0 | 0 | 0 | 0 |

    En producto exitoso free=0 y relocation=0. Final alloc/free balanceado:
    tres backings en fixtures normales, tres en cada fixture de ceros, once
    en el programa de nueve combinaciones, dos en el caso modular. Las vistas
    y adaptación de owners no asignan backings extra.

48. **Snapshots de compilación.** Driver debug, un proceso nuevo por muestra,
    un warmup descartado y diez muestras por fixture. Core suma parse,
    signatures, semantic bodies, MIR lowering/verification, SSA build/verification
    y LLVM. Excluye startup, I/O/dumps, clang/link y timers inclusivos duplicados.
    Medido sin tests/builds concurrentes. V32 baseline se reconstruye con
    `git archive` de `8f4f21f84ef389e49c7b95c2ee9e2ae65f3e98f4` en `/tmp`.

    | Compilador / fixture | Core media ms | Core mediana ms |
    |---|---:|---:|
    | V32 baseline / v32_matrix_column | 1.888 | 1.822 |
    | V33 / v32_matrix_column | 1.750 | 1.651 |
    | V33 / v33_both_transposed | 1.615 | 1.507 |
    | V33 / v33_generic_double | 1.801 | 1.781 |
    | V33 / v33_generic_int | 1.792 | 1.672 |
    | V33 / v33_rectangular | 3.029 | 2.946 |
    | V33 / v33_strided | 1.310 | 1.269 |
    | V33 / v33_zero_contraction | 3.008 | 2.862 |

    Datos y entorno: [v33-debug.json](../../compiler-next/tests/timings/v33-debug.json).
    Son snapshots descriptivos de compilación: no demuestran mejora runtime ni
    significancia estadística. Los fixtures contienen distinta cantidad de
    comprobaciones; no son expresiones aisladas comparables entre sí.

    ```sh
    python3 compiler-next/tests/measure-v33.py --runs 10 \
      --baseline-binary /tmp/aether-v33-baseline-source/compiler-next/target/debug/aether-next \
      --baseline-revision 8f4f21f84ef389e49c7b95c2ee9e2ae65f3e98f4 \
      > compiler-next/tests/timings/v33-debug.json
    ```

49. **Legacy y regresión.** No se modifica compiler-rs, runtime Python, CLI
    legacy ni scrap. Las 21 comparaciones de `tests/run-differential.sh` pasan.
    V0..V32 mantiene productos, +/−, scaling, ceros y transpuestas. Los negativos
    históricos Matrix×Matrix pasan a comprobar resultado Vector incorrecto,
    pues la operación se admite ahora. FaCAether/FaCAetherO0 son binarios no
    rastreados preexistentes ajenos al cambio.

50. **Deuda aceptada.** Se retienen nombres históricos VectorAlgebraicProduct
    y VectorProductKernel, con variantes de rango explícito. MIR/SSA comparten
    el constructor del contrato cerrado como autoridad de verificación; el CFG
    interno se genera en LLVM. InitializeNext conserva su semántica de prefijo
    en lugar de un offset arbitrario. Bootstrap Linux x86_64, built-ins
    homogéneos y traps abortivos. Ningún requisito V33 queda pospuesto.

51. **OPEN DECISIONS.** Ninguna necesaria para Matrix×Matrix. Quedan fuera de
    esta vertical One, impl de usuario, tipos heterogéneos, widening,
    Complex/Hermitian, orientación genérica, SIMD/BLAS, reasociación, dot de
    secuencias y descomposiciones. No se añade nueva familia Vector ni Hadamard.

52. **Problemas arquitectónicos encontrados.** La ausencia de una única
    matrix_input() ya no implica reducción Vector: ahora puede haber dos
    matrices. Se explicita reduction_axis() para ligar un solo phi al loop
    correcto. Además, el bypass Matrix anterior de producto exterior sucedía
    después del helper que construía el descriptor; V33 necesita bypass antes
    de asignar y por eso construye su descriptor vacío propio, conservando
    ambos ejes. Un tercer MathAxis evita reutilizar un eje de salida como
    contracción. No fue necesario cambiar préstamos, lifetimes ni allocator.

53. **Recomendación tras completar la tabla básica.** Mantener este contrato
    estricto como base verificable de la futura STD LinearAlgebra. Diseñar
    descomposiciones y operaciones avanzadas con contratos propios; cualquier
    propuesta BLAS/SIMD/FMA o cambio del orden numérico necesita una decisión
    explícita independiente. No ampliar el `*` nativo por analogía de formas.
