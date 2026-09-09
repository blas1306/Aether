# NEXT-VERTICAL-31 — algebraic Zero capability and native Vector algebraic multiplication

Implementado y calificado en `compiler-next`, Linux x86_64, 2026-09-09.
`Row * Column` devuelve T; `Column * Row` devuelve Matrix<T>. Ambas operaciones
son multiplicaciones algebraicas nativas de `*`, con vistas strided, comprobación
paramétrica y regiones MIR/SSA verificadas. **261 tests aprobados, cero fallos**.

1. **Arquitectura inicial.** V21/V22 ya hacían Row/Column parte de TypeId y
   mantenían transpose propietario consumidor. V25/V26 aportaban descriptores
   VectorView de tres palabras y proyecciones Matrix con strides independientes.
   V29 separaba garantías estructurales y Add/Sub/Mul; V30 concretizaba recetas
   genéricas para kernels propietarios de +/−/escalado. `*` rechazaba cualquier
   par matemático y no existían identidad algebraica ni acumulador de reducción.

2. **Archivos cambiados.** Rutas relativas a la raíz:

   | Archivo | Responsabilidad |
   |---|---|
   | `compiler-next/crates/aether-frontend/src/types.rs` | AlgebraicCapability::Zero y satisfacción independiente |
   | `compiler-next/crates/aether-frontend/src/hir.rs` | restricciones, identidad, productos, ownership, sustitución, verificadores, dumps y tests |
   | `compiler-next/crates/aether-frontend/src/lib.rs` | exportaciones de capacidades y metadata de productos |
   | `compiler-next/crates/aether-middle/src/algebraic.rs` | representación cerrada y verificador de schedules |
   | `compiler-next/crates/aether-middle/src/{lib,mir,ssa}.rs` | lowering, Rvalue/SSA, operandos, ownership y fronteras verificadas |
   | `compiler-next/crates/aether-backend-llvm/src/algebraic.rs` | traducción de schedules a CFG y acumulador phi |
   | `compiler-next/crates/aether-backend-llvm/src/lib.rs` | integración y bypass Matrix vacío con ambos ejes |
   | `compiler-next/crates/aether-backend-llvm/src/elementwise.rs` | preservación de ejes vacíos en +/−/escalado |
   | `compiler-next/crates/aether-driver/tests/vertical.rs` | registro del módulo de pruebas |
   | `compiler-next/crates/aether-driver/tests/vertical31/mod.rs` | diez tests integrales, instrumentación y corrupciones |
   | `compiler-next/tests/programs/v31_inner_{concrete,int,double,strided}.ae` | cuatro fixtures de reducción |
   | `compiler-next/tests/programs/v31_outer_{concrete,generic,empty}.ae` | tres fixtures propietarios, incluyendo ejes cero |
   | `compiler-next/tests/modules/v31_products/{main,helper}.ae` | forwarding y productos strided entre módulos |
   | `compiler-next/tests/modules/v1-contract.tsv` | registro del contrato modular |
   | `compiler-next/tests/measure-v31.py` | snapshots con metodología V17/V30 y baseline opcional |
   | `compiler-next/tests/timings/v31-debug.json` | mediciones por fase y entorno |
   | `compiler-next/README.md` | contrato vigente y ejemplos |
   | `docs/architecture/AETHER_V1_LANGUAGE_CHARTER.md` | admisión acotada |
   | `docs/architecture/AETHER_V1_SEMANTIC_CONTRACT.md` | contrato normativo V31 |
   | `docs/architecture/AETHER_COMPILER_ARCHITECTURE.md` | confirmación 48 y auditoría de vacíos |
   | `docs/architecture/NEXT_VERTICAL_31_REPORT.md` | este informe |

3. **Orientación como forma.** Row(n) ≡ 1×n; Column(n) ≡ n×1. La orientación
   es identidad semántica canónica, no layout ni un campo runtime. Dimensión y
   stride son propiedades del descriptor. No se introduce orientación genérica O.

4. **Vectores vacíos.** Row(0) ≡ 1×0 y Column(0) ≡ 0×1. Sus descriptores
   propietarios siguen siendo null/dimensión cero; las vistas conservan dimensión
   y stride. La orientación vacía no se borra.

5. **Taxonomía Zero.** `Capability::Algebraic(AlgebraicCapability::Zero)` es
   una tercera familia junto a estructurales y comportamientos binarios. Su
   satisfacción se consulta antes de derivación estructural. No implica Add,
   Mul, Copy, Relocatable o Storable, ni éstos implican Zero. La única implicación
   no reflexiva sigue siendo Copy => Relocatable.

6. **Satisfacción y valor.** Los diez enteros built-in satisfacen Zero con
   entero 0 de su tipo exacto; float32/float64 con bits positivos cero. Los
   aliases transparentes comparten TypeId. Bool, structs, enums, Buffer, Array,
   List, Vector, Matrix y refs/views no obtienen Zero, aunque sus componentes lo
   tengan. Un parámetro restringido por Zero conserva propiedades simbólicas.

7. **Representación paramétrica.** `HirExprKind::AlgebraicValue { capability:
   Zero }` es una expresión tipada T. El nodo Inner conserva esta expresión
   explícita en su receta, sin fabricar un literal entero de T. No se añade
   una función fuente `zero()`; el ejemplo conceptual expresa la garantía.

8. **Concretización Zero.** La sustitución transforma la expresión a
   `Int(0)` con TypeId entero exacto o `Float(Float32(0)/Float64(0))`. El
   verificador concreto rechaza AlgebraicValue residual, incluso sobre tipos
   numéricos. MIR recibe un Operand escalar ordinario; SSA/LLVM no tienen
   una operación de capacidad algebraica.

9. **Resolución de `*`.** Se reconoce el par de familias Vector con elementos
   canónicos iguales y orientaciones opuestas. Row izquierda selecciona Inner;
   Column izquierda selecciona Outer. Los casos existentes de un escalar y un
   objeto matemático mantienen su resolver V28/V30. Matrix no adquiere productos
   entre contenedores. Errores hablan de multiplicación algebraica, nunca dot.

10. **Contrato Row×Column.** Dimensiones iguales, lecturas por valor Copy y
    resultado escalar T. `acc=Zero<T>`; para cada índice lógico creciente,
    `product=left[i]*right[i]`, seguido por `acc=acc+product`. No conjugación,
    asignación de resultado propietario, broadcasting o extracción de slots.

11. **Contrato Column×Row.** Dimensiones independientes n y m, resultado
    Matrix<T>(n,m), coordenada `[i,j]=column[i]*row[j]`. No compatibilidad entre
    dimensiones ni reducción; sólo multiplicación e inicialización del resultado.

12. **Rechazos Row×Row/Column×Column.** Ambos producen E0342. No se interpreta
    el producto como Hadamard, dot ni transposición automática. Los tests V27/V28
    que rechazaban pares de igual orientación permanecen verdes.

13. **Tipos de resultado.** Inner devuelve el TypeId del elemento exactamente;
    nunca un wrapper Matrix 1×1. Outer interna el Matrix<T> propietario normal.
    La verificación HIR/MIR/SSA comprueba la familia y elemento de resultado.

14. **Requisitos genéricos Inner.** Copy, Add, Mul y Zero se comprueban de forma
    independiente. Una vista de T no necesita probar representación almacenable
    para efectuar la reducción. Los helpers paramétricos sin instancias se
    auditan y no pueden apoyarse en una futura instanciación numérica exitosa.

15. **Requisitos genéricos Outer.** Storable, Copy y Mul. No se exige Add ni
    Zero; los fixtures genéricos propietarios se declaran sin esas capacidades.
    Copy prueba lecturas repetidas; Mul produce cada T; Storable admite Matrix<T>.

16. **Distinción Storable.** La formación de un Vector<T,O> propietario en una
    firma exige Storable independientemente del algoritmo. Las firmas únicamente
    VectorView de Inner funcionan sin él. Views siguen siendo no-Storable;
    eso no altera la garantía independiente de almacenamiento de su elemento.

17. **Dimensiones Inner.** Ownership aprovecha dimensiones conocidas y emite
    E0345 antes de lowering. Para dimensiones dinámicas, ShapeGuard(Dimension,
    ShapeMismatch) precede las cargas, operaciones y acumulador del schedule.
    Una ejecución instrumentada confirma cero cargas/Mul/Add y ninguna asignación
    o liberación adicional al disparar el guard.

18. **Resultado Inner vacío.** El header compara índice cero con dimensión
    cero y sale devolviendo el valor inicial del phi. No hay cargas, Mul, Add,
    backing allocation, free o relocation. Los tests float distinguen +0 mediante
    comparación con cero y signo del infinito de su recíproco.

19. **Orden de reducción.** For(start=0,step=1) sobre dimensión, un producto y
    una actualización por iteración. N multiplicaciones y N adiciones. Nunca se
    usa el primer producto como semilla. Los casos `[2^24,1,-2^24]` float32 y
    `[2^53,1,-2^53]` float64 multiplicados por unos comprueban orden observable.

20. **Overflow del producto entero.** MultiplyIntegerChecked emplea
    llvm.smul/umul.with.overflow con el ancho original. `max*2` atrapa en los diez
    enteros. Se ejecuta independientemente en Inner y Outer; ningún acumulador
    ampliado ni wrapping oculta el overflow.

21. **Overflow acumulado.** Los productos de `[max,1] * [1,1]` caben por
    separado, pero AddIntegerChecked atrapa al incorporar el segundo. Hay una
    ejecución por cada tipo entero, incluyendo unsigned. La rama de overflow
    del producto precede la rama de overflow del acumulador.

22. **IEEE Inner.** float32/float64 usan fmul y luego fadd separados, sin flags
    fast/reassoc/contract, FMA o BLAS. `+0 + (-0)` conserva la adición inicial y
    resulta +0 bajo el entorno IEEE normal del target. Se prueban finitos, vacío,
    signed zero, infinito, NaN y orden sensible; no hay semántica hermítica.

23. **Forma runtime Outer.** ProductStep::SelectExtent(Rows,Left) y
    SelectExtent(Columns,Right) leen dimensiones independientes. El helper
    verifica su producto y tamaño de backing antes de acceder a elementos.
    La inicialización es contigua row-major, manteniendo ambos ejes.

24. **Ejes cero Outer.** Admitidos 0×0, 0×3 y 2×0 en el fixture, con queries
    exactas y almacenamiento null. Row de una Matrix 2×0 y column de una Matrix
    0×3 son vistas vacías válidas sobre un eje fijo existente. Su producto Inner
    es cero. Transpose_view produce la forma intercambiada y permite queries y
    proyecciones vacías. No se cambia la sintaxis literal []=0×0.

25. **Almacenamiento Outer.** Se reutilizan Matrix TypeData, layout `{ptr,
    rows,columns}`, helper de asignación, consultas, índices y drop. El helper
    ahora evita el allocator cuando el número de elementos es cero. No se altera
    la política del allocator para solicitudes de cero bytes de otros tipos.

26. **Operaciones Outer.** Exactamente n*m MultiplyIntegerChecked o
    MultiplyFloat e igual número de stores. Ninguna suma de T, identidad ni
    widening. Los tests verifican unsigned, todos los anchos, signed zero,
    infinito y NaN; las regiones float Outer sólo tienen fmul como operación de T.

27. **Fuentes Inner strided.** `inner_strided` usa dos matrices: una columna
    stride=3 transpuesta a Row y otra columna stride=2. El resultado es 59.
    Otra reducción usa row de tres elementos y column stride=2, resultado 28.
    Ambos acceden a los descriptores originales sin Vector propietario temporal.

28. **Fuentes Outer strided.** `outer_generic` combina Column stride=3 con Row
    obtenido transponiendo Column stride=2. Produce Matrix 2×3 y verifica su
    última coordenada 55. El programa entre módulos comparte backing en ambos
    lados, verifica las cuatro coordenadas de Matrix 2×2 y preserva strides.

29. **Aliasing, evaluación y ownership.** Se captura lhs y protege su raíz
    durante rhs usando las pilas de préstamos/rangos V27/V30. Los inputs pueden
    aliasar; las vistas mutables sólo se leen. El lowering materializa descriptores
    y mantiene los temporales propietarios hasta terminar el kernel. Se prueban
    llamadas que crean temporales, efectos permitidos en rhs y rechazo de
    `r*consume(r)`. Transpose consumidor no cambia; transpose_view conserva dueño.

30. **Forwarding.** Inner y Outer forwards prueban cada garantía requerida.
    Se comprueban requisitos faltantes en callers no usados, llamadas inferidas,
    firmas de propietarios por ref, vistas compartidas y mutables, y forwarding
    entre módulos con ambos operandos strided.

31. **Cuerpos genéricos sin uso.** La validación paramétrica precede la
    monomorfización. Se rechazan faltantes de Copy/Add/Mul/Zero en Inner y
    Storable/Copy/Mul en Outer aun cuando main no los llama. La prueba de caché
    V29 se amplió con Zero: bool y Buffer son rechazados sin ids/queue/parents;
    int obtiene InstanceId(0) y se deduplica. Los tests de llamadas aceptan int y
    double y rechazan bool/Buffer bajo T:Zero.

32. **HIR Inner.** VectorAlgebraicProduct + VectorProduct::Inner contiene
    operandos, element_type, product_op, shape_check, accumulate_op y zero tipado.
    Las orientaciones permanecen en los TypeIds de operands; el discriminante
    Inner exige Row izquierda y Column derecha. El resultado debe ser T.

33. **HIR Outer.** El mismo nodo exterior con VectorProduct::Outer conserva
    selectores rows=Left y columns=Right y exige Column izquierda, Row derecha y
    Matrix<T>. No existe metadata de Add/Zero en esta variante. Recetas corruptas
    se rechazan reconstruyendo el contrato, sin usar flags como nueva autoridad.

34. **Monomorfización.** Operaciones usan el concretizador central V29:
    Mul/Add -> Multiply/AddIntegerChecked o Multiply/AddFloat. Zero se sustituye
    como expresión tipada. Instancias estáticas conservan ABI/mangling ordinario;
    reordenar Copy+Add+Mul+Zero produce LLVM idéntico. No hay argumentos ocultos.

35. **MIR reducción.** Rvalue::VectorProduct porta VectorProductKernel con
    ProductKind::ReductionKernel. Programa cerrado: ShapeGuard, SelectExtent,
    AccumulatorInit, For, dos StridedLoad, ScalarBinary(Mul), Accumulate(Add),
    YieldScalar. No Allocate, InitializeNext o YieldOwner. El programa es
    verificable antes de emitir LLVM.

36. **MIR Outer.** ProductKind::OuterProductKernel selecciona Rows/Columns,
    Allocate comprobado con bypass vacío, For Rows/Columns, dos StridedLoad,
    ScalarBinary(Mul), InitializeNext y YieldOwner. Ningún ShapeMismatch o
    acumulador forma parte del contrato.

37. **Inicialización.** Inner tiene un acumulador inicializado una vez y
    actualizado una vez por producto, con temporales escalares ordinarios.
    Outer inicializa cada slot una vez en orden row-major. Mul concreto sólo
    admite escalares built-in sin needs_drop; el verificador explicita este
    límite cerrado. No hay bitmap ni generalización de comportamientos de usuario.

38. **Verificador MIR.** Resuelve independientemente operandos/destino y
    comprueba orientación, elementos concretos y familia de resultado. Compara
    la totalidad del árbol ejecutable con el schedule canónico, incluyendo
    guards, selectores, strides, orden, traps, cero, pasos y yields. No acepta
    owners o refs donde requiere descriptores de lectura.

39. **SSA.** El renombrado transforma únicamente los operandos externos a
    SsaOperand; conserva la región cerrada concreta. El acumulador es una
    variable ligada por la región, no un valor arbitrariamente duplicable por
    instrucciones externas. LLVM lo materializa como un phi transportado por el
    único loop de reducción, sin alloca ni estado de capacidades.

40. **Verificador SSA.** Vuelve a resolver tipos de operandos SSA y resultado
    y a verificar el programa completo. Comparte la definición semántica del
    schedule con MIR, pero no confía en un sello de aprobación del MIR anterior.
    Los tests corrompen SSA después de construirlo desde MIR válido.

41. **LLVM.** El nuevo emisor recorre ProductStep y genera CFG, phi, direcciones
    strided, operaciones checked/IEEE y stores. ShapeMismatch domina las cargas
    Inner; comprobaciones de asignación dominan las cargas Outer. No metadata de
    capacidades, dispatcher, noalias, flags de overflow UB o código de BLAS.

42. **Diagnósticos.** E0342 para pares matemáticos no admitidos; E0343 para
    tipos de elemento distintos; E0345 para dimensión conocida incompatible;
    E0346 identifica las capacidades algebraicas que faltan. E0316/E0317 mantienen
    validación explícita/inferida de restricciones; formación de almacenamiento
    retiene sus diagnósticos Storable. Metadata paramétrica corrupta falla E0348;
    HIR concreto corrupto falla en la frontera E0290. MIR/SSA usan sus errores de
    verificación estructurados. No se denomina dot a un producto Vector válido.

43. **Dumps.** Tabla de tipos agrega `algebraic guarantees=[Zero]`. HIR genérico
    muestra VectorAlgebraicProduct, Inner/Outer, orientaciones de los descriptores,
    Behavioral y AlgebraicValue. Instanciado muestra operaciones concretas y
    cero concreto. MIR/SSA muestran ReductionKernel u OuterProductKernel y sus
    instrucciones. Dos compilaciones comparan todos los dumps y LLVM idénticos.

44. **Tests exactos.** `cargo test --workspace`: **261 aprobados**, distribuidos
    en 7 backend, 194 integración, 38 frontend y 22 middle. Permanecen verdes los
    248 anteriores. Los 13 tests nuevos son:

    | Test | Cobertura |
    |---|---|
    | `vertical31_zero_taxonomy_satisfaction_and_no_implications` | satisfacción del arena, propiedades simbólicas e independencia |
    | `vertical31_hir_product_corruption_and_erased_guarantees` | 20 corrupciones de productos y 7 borrados coordinados de garantías |
    | `vertical31_concrete_hir_zero_and_operation_corruption` | 24 corrupciones de cero y operaciones concretas |
    | `vertical31_native_fixtures_and_exact_costs` | siete fixtures, resultados y contadores por operación |
    | `vertical31_all_readable_families_and_builtin_scalars` | 15 nombres escalares/aliases y nueve pares por producto |
    | `vertical31_parametric_constraints_diagnostics_and_forwarding` | faltantes, forwarding, argumentos Zero y pares rechazados |
    | `vertical31_integer_product_and_accumulator_overflow` | 30 traps: diez tipos por tres causas |
    | `vertical31_ieee_strict_order_zero_infinity_nan` | dos precisiones, orden, +0 inicial, fmul/fadd e IEEE |
    | `vertical31_mir_ssa_independent_corruption_rejection` | 84 corrupciones independientes de frontera |
    | `vertical31_dynamic_mismatch_guards_before_loads_ops_or_allocation` | trap nativo y contadores anteriores al trap |
    | `vertical31_aliases_evaluation_temporaries_and_zero_axis_queries` | préstamos, temporales, efectos y proyecciones vacías |
    | `vertical31_deterministic_dumps_and_constraint_order_abi` | determinismo y ABI sin dependencia del orden de capacidades |
    | `vertical31_cross_module_strided_products` | alias strided y ambos resultados entre módulos |

45. **Corrupciones.** HIR: 51 casos nuevos, incluyendo orientación invertida,
    familia/resultados cambiados, Mul->Add, Add->Mul, cero borrado/tipo/signo,
    shape-check erróneo, selectores Outer y capacidades borradas en declaración y
    arena. MIR/SSA: 21 casos por producto y frontera, 84 en total. Incluyen guard
    ausente/reordenado, stride incorrecto, op equivocada, cero cambiado, acumulador
    duplicado, Allocate/ShapeMismatch indebidos, inicialización duplicada/faltante,
    yield incorrecto, límites/paso, selectores y input no descriptor. **135
    corrupciones nuevas rechazadas**, además de la caché Zero ampliada.

46. **Ejecuciones de traps.** Diez tipos enteros por overflow de producto Inner,
    acumulación Inner y producto Outer: 30 SIGILL. Un ShapeMismatch dinámico
    adicional produce SIGILL. Su variante instrumentada termina correctamente
    sólo si cargas, Mul/Add y asignaciones adicionales son cero. El conjunto
    dedicado V31 efectúa **59 ejecuciones nativas**, incluyendo éxitos y traps.
    Las pruebas V0..V30 siguen cubriendo allocation failure/size overflow e índices.

47. **Contadores de ejecución.** Instrumentación exclusiva de tests mide
    diferencias reales entre AlgebraicBegin/End, después de evaluar operandos.
    Los resultados finales exigen allocs=frees; no se infiere coste contando IR.

    | Operación | Alloc delta | Free / relocation delta | Mul | Add | Cargas | Stores |
    |---|---:|---:|---:|---:|---:|---:|
    | Inner dimensión n | 0 | 0 / 0 | n | n | 2n | 0 |
    | Inner vacío | 0 | 0 / 0 | 0 | 0 | 0 | 0 |
    | Outer n×m no vacío | 1 | 0 / 0 | n*m | 0 | 2*n*m | n*m |
    | Outer con cualquier eje cero | 0 | 0 / 0 | 0 | 0 | 0 | 0 |
    | Inner mismatch | 0 | 0 / 0 | 0 | 0 | 0 | 0 |

    Totales de asignaciones/frees de los fixtures: inner_concrete=2, inner_int=2,
    inner_double=2, inner_strided=3, outer_concrete=3, outer_generic=3 y
    outer_empty=2. Los últimos dos son únicamente los vectores fuente no vacíos;
    los tres resultados Matrix vacíos no asignan memoria. Por nombre escalar, el
    programa de nueve familias por producto asigna/libera 11 backings: dos inputs
    y nueve resultados Outer. La instrumentación no forma parte del compilador.

48. **Snapshots de compilación.** Driver debug, un proceso nuevo por muestra,
    un warmup descartado y diez muestras por fixture, sin tests/builds simultáneos.
    Core suma las ocho fases parse-through-LLVM V17/V30, excluyendo startup,
    discovery/I/O/dumps, clang/link y temporizadores inclusivos duplicados. Baseline
    V30 se reconstruyó con git archive de
    `e1df1391840ac3d2a7433fb61a4cc70b5e75d44b` en `/tmp`.

    | Compilador / fixture | Core media ms | Core mediana ms |
    |---|---:|---:|
    | V30 baseline / v30_vector_add | 2.069 | 2.025 |
    | V30 baseline / v30_vector_scale | 1.414 | 1.415 |
    | V31 / v30_vector_add | 1.426 | 1.413 |
    | V31 / v30_vector_scale | 1.508 | 1.411 |
    | V31 / v31_inner_concrete | 1.189 | 1.112 |
    | V31 / v31_inner_double | 1.278 | 1.264 |
    | V31 / v31_inner_int | 1.259 | 1.171 |
    | V31 / v31_inner_strided | 1.719 | 1.631 |
    | V31 / v31_outer_concrete | 1.392 | 1.340 |
    | V31 / v31_outer_empty | 3.262 | 3.193 |
    | V31 / v31_outer_generic | 1.914 | 1.848 |

    Son snapshots descriptivos, no evidencia estadística de mejora ni benchmarks
    runtime. Los fixtures incluyen comprobaciones de resultados; el fixture vacío
    prueba tres formas y operaciones posteriores, por lo que su coste de
    compilación no es comparable con una única expresión. Datos y entorno:
    [v31-debug.json](../../compiler-next/tests/timings/v31-debug.json).
    Reproducción desde la raíz:

    ```sh
    python3 compiler-next/tests/measure-v31.py --runs 10 \
      --baseline-binary /tmp/aether-v31-baseline-source/compiler-next/target/debug/aether-next \
      --baseline-revision e1df1391840ac3d2a7433fb61a4cc70b5e75d44b
    ```

49. **Legacy y checks.** `bash compiler-next/tests/run-differential.sh`:
    **21 comparaciones, cero fallos**. `cargo fmt --all --check`,
    `cargo clippy --all-targets -- -D warnings` y `git diff --check` pasan.
    Los comandos Cargo se ejecutan con el manifest compiler-next. No se modifican
    compiler-rs, runtime/CLI legacy ni scrap. FaCAether y FaCAetherO0 son binarios
    no rastreados preexistentes y permanecen fuera del cambio.

50. **Deuda aceptada.** Schedule cerrado comparado íntegramente, como V27/V30,
    con representación común para verificación MIR y SSA y emisor dedicado.
    La región liga internamente su acumulador; no se convierte en bloques
    ordinarios del IR exterior hasta LLVM. Se conserva bootstrap Linux x86_64,
    traps abortivos y aritmética built-in homogénea. Hay llamadas a helpers
    estáticos Matrix/fixed storage; el caso vacío puede llamar al helper Matrix,
    pero nunca al allocator ni crear backing. No se implementa una API fuente Zero.

51. **OPEN DECISIONS.** Matrix×Vector, Vector×Matrix y Matrix×Matrix requieren
    sus propias reglas de forma/reducción; dot podría ser una operación futura
    de secuencias Array/List, nunca este producto Vector. One, impl de usuario,
    contratos heterogéneos, acumuladores ampliados, Complex/Hermitian, orientación
    genérica, BLAS/SIMD y semánticas alternativas de reducción siguen abiertos.
    Descomposiciones avanzadas pertenecen a futura STD LinearAlgebra. Ninguna
    extensión queda admitida por V31.

52. **Problemas arquitectónicos encontrados.** Matrix ya representaba filas y
    columnas separadas, y sus queries/drop/índices no requerían que ambos fueran
    cero simultáneamente. Sin embargo, el helper Matrix llamaba fixed_new para
    cero elementos, y el allocator reserva al menos un byte incluso para cero
    bytes: se añadió bypass por count==0 preservando ambos ejes. Además, las rutas
    vacías elementwise comprobaban sólo Rows y devolvían zeroinitializer; eso
    colapsaría 0×m a 0×0. Ahora comprueban cualquiera de los ejes y construyen el
    descriptor vacío con ambos valores. Es soporte mínimo para formas nuevas;
    no cambia el allocator general ni la sintaxis literal.

53. **Recomendación NEXT-VERTICAL-32.** Extender de manera acotada a
    Matrix<T>×Vector<T,Column> -> Vector<T,Column>, con contrato explícito para
    filas/columnas cero, una reducción ordenada por fila, las mismas garantías
    independientes y pruebas MIR/SSA/coste. Mantener Matrix×Matrix, Vector×Matrix,
    dot de secuencias, heterogeneidad, user impl y optimizaciones algebraicas como
    decisiones posteriores, sin asumir conmutatividad ni reasociación.
