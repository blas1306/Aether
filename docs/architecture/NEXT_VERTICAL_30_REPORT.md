# NEXT-VERTICAL-30 — generic Vector/Matrix arithmetic kernels via Copy + Add/Sub/Mul

Implementado en `compiler-next`, Linux x86_64, 2026-09-09. Los kernels
matemáticos admiten elementos genéricos bajo garantías independientes y se
concretizan antes de MIR. **248 pruebas aprobadas, cero fallos**.

1. **Restricción inicial V27/V28.** El resolver exigía elementos built-in
   concretos mediante `supports_builtin_add_sub` / `supports_builtin_multiply`.
   T simbólico producía E0346 incluso con comportamiento declarado. HIR guardaba
   un HirBinaryOp concreto para +/− e infería la multiplicación desde el tipo.
   V29 ya proporcionaba garantías conductuales y una autoridad de concretización.

2. **Archivos cambiados.** Rutas relativas a la raíz:

   | Archivo | Cambio |
   |---|---|
   | `compiler-next/crates/aether-frontend/src/hir.rs` | MathElementOp, admisión, sustitución, verificación y corrupción HIR |
   | `compiler-next/crates/aether-frontend/src/lib.rs` | exportación de MathElementOp |
   | `compiler-next/crates/aether-middle/src/mir.rs` | extracción explícita del operador concretizado y frontera exhaustiva |
   | `compiler-next/crates/aether-driver/tests/vertical.rs` | nueve tests V30 y expectativa diagnóstica V29 actualizada |
   | `compiler-next/tests/programs/v30_vector_add.ae` | Row int y forwarding |
   | `compiler-next/tests/programs/v30_vector_scale.ae` | escala double |
   | `compiler-next/tests/programs/v30_vector_strided.ae` | suma de columnas int con stride 3 |
   | `compiler-next/tests/programs/v30_matrix_add.ae` | suma rectangular double |
   | `compiler-next/tests/programs/v30_matrix_transposed.ae` | suma y escala double de vista transpuesta |
   | `compiler-next/tests/programs/v30_empty.ae` | cuatro kernels vacíos y efectos escalares |
   | `compiler-next/tests/modules/v30_kernels/{main,helper}.ae` | Add/Sub/Mul y forwarding entre módulos |
   | `compiler-next/tests/modules/v1-contract.tsv` | registro del módulo |
   | `compiler-next/tests/measure-v30.py` | mediciones reproducibles |
   | `compiler-next/tests/timings/v30-debug.json` | snapshot de compilación |
   | `compiler-next/README.md` | contrato actual y ejemplos |
   | `docs/architecture/AETHER_V1_LANGUAGE_CHARTER.md` | admisión V30 |
   | `docs/architecture/AETHER_V1_SEMANTIC_CONTRACT.md` | requisitos normativos V30 |
   | `docs/architecture/AETHER_COMPILER_ARCHITECTURE.md` | confirmación 47 |
   | `docs/architecture/NEXT_VERTICAL_30_REPORT.md` | este informe |

3. **Regla del kernel.** `math_element_op` admite GenericParam exacto sólo
   cuando satisface Storable + Copy + la capacidad de la operación. Los
   built-ins concretos usan directamente la autoridad existente de V29.
   No se modifican TypeProperties, satisfacción conductual ni implicaciones.

4. **Por qué Copy.** Cada elemento se obtiene por valor desde almacenamiento
   prestado sin mover su slot; el escalar se reutiliza en cada iteración.
   Copy prueba ambas operaciones. Add/Sub/Mul por sí solos no las autorizan.
   No hay clones implícitos, Move por iteración ni consumo de elementos.

5. **Storable independiente.** Prueba almacenamiento del elemento en el
   resultado propietario. No implica Copy o comportamiento, ni éstos implican
   Storable. Un descriptor de vista sigue siendo no-Storable aunque T lo sea.
   El kernel vuelve a verificar la garantía del elemento.

6. **Add.** `T:Storable+Copy+Add` permite el kernel `T + T -> T`.
   Mul/Sub no sirven como prueba de Add. El operador fuente se conserva.

7. **Sub.** `T:Storable+Copy+Sub` permite `T - T -> T`.
   Incluso Add+Mul juntos son insuficientes. Se conserva underflow checked
   para unsigned, además de overflow signed.

8. **Mul.** `T:Storable+Copy+Mul` permite ambos órdenes de escala, con
   escalar T exactamente igual al elemento T. La identidad de Mul es implícita
   en el tipo de nodo de escala y se compara con su metadata explícita.

9. **Familias.** Vector, VectorView, VectorViewMut y, separadamente, Matrix,
   MatrixView, MatrixViewMut son entradas legibles. Se prueban las nueve
   combinaciones por pareja, más seis formas de escala por orientación/rango.
   Los refs usan dereferencia explícita: `return *a + *b;`, llamada `add(&a,&b)`.

10. **Orientación.** T es genérico; Row y Column son concretos. No se admite O
    genérico ni conversiones entre orientaciones. El lenguaje actual no tiene
    alias `uint`: la cobertura Column unsigned usa `uint64`.

11. **HIR simbólico.** Los cuatro nodos matemáticos llevan
    `MathElementOp::{Concrete(HirBinaryOp),Behavioral(BehavioralCapability)}`.
    +/− también retienen `source_op: AstBinaryOp` como evidencia independiente.
    Así, alterar Add por Sub/Mul se detecta aun cuando T garantice los tres.
    No se fabrica una expresión CapabilityBinary por elemento.

12. **Verificador HIR.** Comprueba identidad exacta de T, garantías, igualdad
    de elementos/resultados, familia, orientación, entrada legible y contrato de
    forma. Rechaza metadata concreta sobre T y comportamiento discordante con
    el operador fuente. La verificación paramétrica incluye cuerpos sin uso.
    Eliminar Copy o Storable coherentemente del binder y del arena no evita
    la comprobación independiente del kernel.

13. **Sustitución.** El mecanismo existente sustituye tipos de resultado,
    elemento, operandos y Places. `substitute_math_op` sustituye el elemento de
    una receta Behavioral y obtiene su operación concreta. Concrete se conserva.

14. **Concretización.** Reutiliza `concrete_behavior_op` de V29: Add/Sub/Mul
    se convierten a Add/Subtract/MultiplyIntegerChecked o sus variantes Float.
    Una concretización imposible produce E0348. No hay otra tabla de operadores.

15. **Copy después de sustituir.** El cuerpo ya tuvo que demostrar Copy antes
    de solicitar instancias. El éxito de `int` o `double` no rescata un cuerpo
    insuficiente. La sustitución normal de usos simbólicos Copy se conserva;
    no se agrega una autorización tardía basada únicamente en propiedades concretas.

16. **Frontera MIR.** HIR concreto rechaza cualquier MathElementOp::Behavioral
    residual con E0290, incluso sobre int. El lowering enumera esa variante como
    violación de la invariante de HIR verificado. MIR sólo puede representar
    BinaryOp concretos en el mismo ElementwiseKernel V27/V28; no se añadió un
    tag conductual inyectable en MIR. La prueba de frontera inyecta el residual
    en HIR y, separadamente, un TypeId simbólico en el kernel MIR.

17. **SSA.** Sin cambios de representación o implementación. Se renombran
    los mismos operandos y se verifica el mismo árbol ejecutable. Corrupciones
    de tipos simbólicos, operadores, entradas propietarias y schedule se rechazan
    independientemente de MIR.

18. **LLVM/runtime.** Sin cambios de backend ni runtime. No se emiten
    diccionarios, vtables, dispatch, metadata ni argumentos conductuales ocultos.
    La comparación de la función LLVM completa incluye la firma después de
    normalizar únicamente el símbolo de la función.

19. **Forma Vector.** Orientación y dimensión exactas. Los helpers genéricos
    ejecutan ShapeMismatch dinámico antes de asignar memoria o leer elementos.
    Los diagnósticos estáticos anteriores permanecen.

20. **Forma Matrix.** Igualdad de filas y después columnas, sin parámetros
    estáticos de shape. Se prueba específicamente 2x3 contra 3x2 y distinto
    número de columnas con igual número de filas.

21. **Forma de escala.** Un único descriptor define las extensiones del
    resultado. No hay ShapeGuard/ShapeMismatch en el kernel de escala.

22. **Strides.** Los descriptores preservan stride vectorial y ambos strides
    de matriz. La iteración usa coordenadas lógicas y escribe el resultado
    contiguo; no se asume entrada contigua ni se copia su backing.

23. **Row/Column genéricos.** La tabla nativa ejecuta ambos con int, uint64,
    float32 y double, Add/Sub y escala en ambos órdenes. El fixture de columna
    suma las columnas 2 y 3 de una Matrix<int> 2x3: produce [5,11] con stride 3.

24. **MatrixView transpuesta.** El fixture double transpone 2x3 a 3x2;
    verifica suma y escala mediante coordenadas que distinguen filas/columnas
    físicas. El módulo adicional prueba Sub y escala sobre transpuestas int.

25. **Propiedad de entradas.** Los operadores toman descriptores prestados y
    dejan el propietario utilizable. Las pruebas leen de nuevo el original.
    Pasar un owner por valor a una función sigue transfiriéndolo a esa función
    según las reglas ordinarias; el operador dentro de ella no lo consume.
    Vector/Matrix siguen siendo no-Copy y mantienen su destrucción habitual.

26. **Forwarding.** Hay forwarding Row local y Column entre módulos. Los
    callers deben probar requisitos del callee; ocho casos rechazan falta de
    Copy, Add, Sub o Mul en ambos rangos. Se conserva la validación central
    antes de InstanceId/cache, cubierta también por el test V29 existente.

27. **Cuerpos no usados.** Catorce casos negativos de garantías se comprueban
    sin llamadas. Las corrupciones paramétricas también usan helpers sin
    instancias, por lo que no dependen de una especialización exitosa.

28. **Enteros checked.** Doce programas V30 prueban Add/Sub/Mul sobre int8 y
    uint8 en Vector y Matrix, con un primer slot válido y un segundo que
    desborda. Cada uno se ejecuta con SIGILL y nuevamente con una sonda que
    identifica IntegerOverflow: 24 ejecuciones. Se comprueba el trap en MIR/SSA.
    La suite previa de todos los anchos permanece verde.

29. **IEEE.** Doce programas cubren float32/float64 × Vector/Matrix × Add/Sub/Mul.
    Verifican ceros con signo, infinitos y NaN, y la instrucción LLVM
    `fadd/fsub/fmul float|double` sin flags fast-math. La tabla de familias
    también ejecuta aritmética finita float32 y double.

30. **Inicialización.** Se reutiliza el árbol cerrado de Allocate, For,
    StridedLoad/InvariantScalar, ScalarBinary, InitializeNext y YieldOwner.
    Cada slot se inicializa una vez; sólo escapa un owner completo. No bitmap,
    cambios de layout ni maquinaria de cleanup conductual. Los traps son abortivos.

31. **Vacíos.** El fixture combina suma Vector, resta Matrix y escala de ambos.
    Comprueba dimensiones/formas vacías, cero operaciones y cero asignaciones.
    Los dos argumentos escalares con efectos incrementan su contador exactamente
    una vez cada uno. Las reglas previas de evaluación dentro del operador persisten.

32. **Diagnósticos.** E0346 nombra los requisitos y la lista independiente
    ausente, por ejemplo `requires Storable + Copy + Add; missing Copy`.
    E0325/E0331 conservan los errores de almacenamiento Vector/Matrix sin
    Storable. E0316/E0317 son requisitos de llamada explícita/inferida;
    E0348 identifica HIR paramétrico/concretización inválidos; E0290 identifica
    residuales en HIR concreto. E0342/E0343/E0344 preservan familia, identidad y
    orientación. El test V29 que antes esperaba «built-in» para Storable+Add
    ahora exige «missing Copy», manteniendo E0346.

33. **Dumps.** HIR muestra T, garantías estructurales/conductuales y
    `op: Behavioral(Add/Sub/Mul)`; las instancias muestran `op: Concrete(...)`.
    MIR/SSA no contienen Behavioral ni CapabilityBinary; su kernel es concreto.
    Se comparan dumps completos y LLVM de compilaciones repetidas.

34. **Tests exactos.** `cargo test --workspace`: 7 backend, 35 frontend,
    22 middle y 184 integración: **248**, incluidos los 237 anteriores.
    Los once tests añadidos son:

    | Test | Cobertura |
    |---|---|
    | vertical30_hir_independently_verifies_symbolic_kernel_contracts | 36 corrupciones HIR paramétricas |
    | vertical30_concrete_hir_rejects_residual_behavioral_kernel | seis residuales HIR concretos |
    | vertical30_native_strides_forwarding_empty_and_exact_counters | seis fixtures y sondas exactas |
    | vertical30_all_readable_families_orientations_and_behaviors | 12 ejecuciones, 288 kernels |
    | vertical30_missing_independent_guarantees_and_invalid_instances | 14 cuerpos, ocho forwarding y dos instancias inválidas |
    | vertical30_checked_integer_kernels_trap_after_first_slot | 24 ejecuciones de overflow |
    | vertical30_ieee_kernels_preserve_signed_zero_infinity_and_nan | 12 ejecuciones IEEE |
    | vertical30_mir_ssa_reject_symbolic_types_and_corrupt_kernel_schedules | 136 corrupciones entre ambas fronteras |
    | vertical30_codegen_equivalence_and_deterministic_dumps | dos comparaciones genérico/concreto y determinismo |
    | vertical30_shape_mismatch_precedes_result_allocation | diez ejecuciones con sonda de heap |
    | vertical30_cross_module_strided_kernels | una ejecución entre módulos |

    Total dedicado: **65 ejecuciones nativas**. También pasan
    `cargo fmt --all --check`, `cargo clippy --all-targets -- -D warnings`
    y `git diff --check` (comandos Cargo desde compiler-next).

35. **Corrupciones.** HIR cambia comportamiento por otro aun con garantía,
    borra Copy/Storable de ambas tablas, cambia resultado, elemento, familia,
    orientación y sustituye metadata simbólica por concreta. MIR/SSA corrompen
    guards, traps, allocation, loops, strides, operación, inicialización,
    scalar-side, elemento simbólico y owner consumible como entrada. Behavioral
    no es representable en MIR/SSA: su residual se rechaza en la frontera HIR.

36. **Equivalencia de código.** `add<int>` sobre Vector y `scale<double>`
    sobre Matrix comparan ElementwiseKernel completo de MIR y SSA con helpers
    concretos equivalentes. La firma y cuerpo LLVM completos coinciden tras
    normalizar sólo el nombre de función; no existen argumentos/calls extra.
    No se usa esta comparación para afirmar igualdad de tiempos de ejecución.

37. **Contadores.** Las sondas V27/V28 se reutilizan sin cambios. Cada kernel
    tiene delta de allocation 1 si no vacío, 0 si vacío; frees durante el
    operador 0; operaciones y stores iguales a N o R*C. Los fixtures comprueban
    además alloc/free totales y destrucción sin fugas:

    | Fixture | Alloc/free totales | Operaciones/stores matemáticos |
    |---|---:|---:|
    | vector_add | 2 | 3 |
    | vector_scale | 2 | 3 |
    | matrix_add | 2 | 6 |
    | matrix_transposed | 3 | 12 |
    | vector_strided | 2 | 2 |
    | empty | 0 | 0 |

38. **Snapshots de tiempos.** Driver debug, un proceso por muestra, un warmup
    descartado y diez muestras por fixture; sin builds/tests concurrentes.
    Core suma las ocho fases parse-through-LLVM, excluyendo startup, discovery,
    I/O, dumps, clang/link y temporizadores inclusivos duplicados. El baseline
    es el fixture escalar Add de V29 compilado por el mismo driver V30, no una
    comparación histórica entre revisiones del compilador.

    | Fixture | Core media ms | Core mediana ms |
    |---|---:|---:|
    | v29_add_int | 0.942 | 0.960 |
    | v30_matrix_add | 1.638 | 1.503 |
    | v30_matrix_transposed | 2.337 | 2.161 |
    | v30_vector_add | 1.406 | 1.359 |
    | v30_vector_scale | 1.508 | 1.398 |

    Datos completos, toolchains, plataforma y fases:
    [v30-debug.json](../../compiler-next/tests/timings/v30-debug.json).
    Reproducción: `python3 tests/measure-v30.py --runs 10` desde compiler-next.
    Son snapshots descriptivos de compilación, no benchmarks runtime ni una
    afirmación de mejora estadística. El código emitido no tiene dispatch de
    capacidades y la comparación estructural no encuentra overhead añadido.

39. **Legacy.** `bash compiler-next/tests/run-differential.sh`: **21 comparaciones,
    cero fallos**. No se modifican compiler-rs, CLI legacy, runtime ni scrap.
    Los binarios no rastreados preexistentes FaCAether/FaCAetherO0 no forman
    parte del cambio.

40. **Deuda aceptada.** Comportamientos cerrados, homogéneos y sólo built-in;
    sin implementaciones de usuario. La frontera de lowering presupone HIR
    verificado y usa una rama unreachable para un residual imposible mediante
    las APIs normales, como V29. La autoridad de lifetimes sigue siendo el
    análisis léxico frontend; no se añadió un análisis global MIR/SSA de
    préstamos. Permanece la restricción de vistas mutables con elementos que
    contienen List y los traps abortivos sin unwind.

41. **OPEN DECISIONS.** Contratos prestados para elementos no-Copy, user impl,
    associated types/resultados heterogéneos, orientación genérica, Zero/One,
    dot/outer/matmul, semántica de reducción/orden IEEE y acumulación checked.
    Ninguna se admite implícitamente por esta implementación.

42. **Problemas arquitectónicos encontrados.** El HIR anterior no distinguía
    receta simbólica de operación concreta; además, escala reconstruía la
    operación a partir del tipo sólo al bajar a MIR. Ambos caminos ahora llevan
    MathElementOp explícito y usan la misma autoridad de concretización. Para
    detectar corrupción de comportamiento cuando existen varias garantías,
    +/− necesitan evidencia fuente independiente; se retiene AstBinaryOp y el
    verificador limita ese campo a Add/Sub. No hizo falta cambiar los bucles,
    la derivación de propiedades o el modelo de ownership.

43. **Recomendación NEXT-VERTICAL-31.** Definir una primera reducción matemática
    acotada, por ejemplo dot, comenzando por su contrato explícito: orientación,
    resultado, identidad del caso vacío, garantías Copy/Storable/Add/Mul,
    orden de acumulación, overflow y IEEE. Resolver Zero o una semilla explícita
    antes de implementar la reducción. Mantener user impl, heterogeneidad y
    matmul como decisiones independientes.
