# NEXT-VERTICAL-29 — behavioral generic capability foundation for Add, Sub and Mul

Implementado en `compiler-next`, Linux x86_64, cierre 2026-09-09.
Los genéricos escalares pueden probar operadores mediante garantías explícitas;
la monomorfización selecciona las operaciones checked/IEEE existentes.

1. **Arquitectura inicial.** V15/V17 representaban Copy/Relocatable/Storable en
   un enum cerrado y BTreeSets asociados a GenericParamId. Las propiedades
   concretas estaban separadas de las garantías simbólicas, con derivación
   recursiva de campos/payloads. Las llamadas explícitas, inferidas y nominales
   comprobaban restricciones antes de solicitar InstanceId. V27/V28 consultaban
   predicados concretos de aritmética; el resolver rechazaba cualquier operador
   escalar sobre T. HIR conservaba cuerpos genéricos, pero su verificador
   independiente recorría únicamente los cuerpos monomorfizados.

2. **Archivos cambiados.** Rutas relativas a la raíz:

   | Archivo | Cambio |
   |---|---|
   | `compiler-next/crates/aether-frontend/src/types.rs` | familia BehavioralCapability; satisfacción concreta y garantías separadas |
   | `compiler-next/crates/aether-frontend/src/hir.rs` | restricciones, CapabilityBinary, ownership, sustitución, verificación paramétrica/concreta, dumps y cuatro tests |
   | `compiler-next/crates/aether-frontend/src/lib.rs` | exporta BehavioralCapability |
   | `compiler-next/crates/aether-middle/src/mir.rs` | frontera exhaustiva que impide bajar CapabilityBinary residual |
   | `compiler-next/crates/aether-driver/tests/vertical.rs` | siete tests integrales V29 |
   | `compiler-next/tests/programs/v29_behavior.ae` | operaciones, aliases, nominales, forwarding, garantías combinadas y cuerpo sin instancias |
   | `compiler-next/tests/programs/v29_add_int.ae` | fixture pequeño Add entero |
   | `compiler-next/tests/programs/v29_affine_int.ae` | fixture Add+Mul entero |
   | `compiler-next/tests/programs/v29_affine_float.ae` | fixture Add+Mul double |
   | `compiler-next/tests/modules/v29_behavior/{main,helper}.ae` | forwarding y operaciones entre módulos |
   | `compiler-next/tests/modules/v1-contract.tsv` | registro del fixture entre módulos |
   | `compiler-next/tests/measure-v29.py` | snapshots reproducibles con baseline opcional |
   | `compiler-next/tests/timings/v29-debug.json` | datos por fase, entorno, medias y medianas |
   | `compiler-next/README.md` | contrato vigente, sintaxis, semántica y límites |
   | `docs/architecture/AETHER_V1_LANGUAGE_CHARTER.md` | admisión V29 |
   | `docs/architecture/AETHER_V1_SEMANTIC_CONTRACT.md` | sección normativa 10.8 |
   | `docs/architecture/AETHER_COMPILER_ARCHITECTURE.md` | confirmación 46 |
   | `docs/architecture/NEXT_VERTICAL_29_REPORT.md` | este informe |

3. **Modelo estructural/conductual.** Se conserva el vocabulario estructural
   `Capability::{Copy,Relocatable,Storable}` y se añade la variante etiquetada
   `Capability::Behavioral(BehavioralCapability::{Add,Sub,Mul})`. La clasificación
   explícita evita mezclar las reglas sin duplicar conjuntos que deban
   sincronizarse. `guarantees_capability` despacha comportamiento antes de entrar
   en propiedades concretas o derivación estructural. La única implicación no
   reflexiva sigue siendo Copy => Relocatable; se prueban las 36 parejas.

4. **Sintaxis fuente.** Se reutiliza el parser existente:
   `T:Add`, `T:Sub`, `T:Mul`, `T:Add+Mul`, `T:Copy+Storable+Add`.
   Funciones, structs y enums comparten colección de parámetros y validación.
   No se agrega where, impl, métodos ni sintaxis runtime.

5. **Contrato Add.** T + T -> T, mismos TypeIds canónicos para ambos operandos
   y resultado. Add no prueba Sub, Mul ni Copy. Un literal no representa un
   valor arbitrario de T; no se introduce identidad aditiva.

6. **Contrato Sub.** T - T -> T, independiente de Add. Su instanciación entera
   preserva overflow/underflow checked, incluyendo resta unsigned.

7. **Contrato Mul.** T * T -> T, independiente de Add y Sub. No se introducen
   productos entre contenedores, identidad multiplicativa ni reducciones.

8. **Satisfacción built-in.** `satisfies_behavior(TypeId, behavior)` acepta
   int8/int16/int32/int64, uint8/uint16/uint32/uint64, isize/usize y
   float32/float64. Cada comportamiento se consulta individualmente. Los
   predicados internos V27/V28 delegan en esta autoridad, manteniendo su
   admisión exclusivamente concreta. No existe Numeric como restricción.

9. **Ausencia de derivación estructural.** bool, referencias, vistas, structs,
   enums, Buffer/Array/List/Vector/Matrix no satisfacen estas capacidades
   escalares. Point con dos double sigue sin Add. Holder<int> y E<int> tampoco
   adquieren comportamiento por campos, payloads o restricciones del binder.
   Los tests recorren el arena y comprueban la separación.

10. **Representación de garantías.** GenericParamInfo mantiene su BTreeSet
    de Capability con variantes conductuales etiquetadas, ligado al
    GenericParamId exacto; TypeArena conserva la misma metadata. El verificador
    exige coincidencia de identidad, nombre y conjunto. `guarantees_behavior`
    consulta únicamente el parámetro simbólico exacto o satisfacción concreta.
    Un T:Add no es numérico y sus TypeProperties permanecen idénticas a las
    anteriores: is_copy/is_relocatable/is_storable/needs_drop no se modifican.

11. **Resolución simbólica.** Sólo +, - y * cuentan con estos contratos.
    Si existe la garantía y ambos operandos son el mismo T, se crea
    CapabilityBinary. Las expresiones escalares concretas conservan el resolver
    anterior. Los operandos siguen las reglas ordinarias de propiedad; sin
    Copy, cada argumento T se consume. `a+a` requiere Copy adicional y se
    rechaza aun cuando Add está garantizado.

12. **Diagnóstico de garantía ausente.** E0268 se conserva por compatibilidad
    con V8 y ahora explica, por ejemplo:
    `operator '+' on generic parameter T requires capability Add`.
    El error ocurre durante checking paramétrico, incluso sin instancias;
    no se difiere al worklist de monomorfización.

13. **Forwarding.** `outer<T:Add>` puede llamar `inner<T:Add>` explícitamente
    o mediante inferencia. El caller debe demostrar cada requisito del callee;
    T:Storable no demuestra Add, y T:Add no demuestra Add+Mul. El verificador
    independiente también sustituye firmas y revalida los requisitos de las
    llamadas declarativas. Un test corrompe consistentemente las garantías del
    callee en declaración y arena y detecta el forwarding ahora inválido.

14. **Garantías múltiples.** Affine<T:Add+Mul> produce un CapabilityBinary(Mul)
    anidado en CapabilityBinary(Add); cada nodo tiene su garantía independiente.
    Los fixtures ejecutan int y double, además de forwarding anidado mediante
    multiply y add. Un cuerpo sin instancias combina Add/Sub/Mul y se verifica.

15. **Nominales genéricos.** Se soportan uniformemente structs y enums.
    Holder<T:Add> y Maybe<T:Add> aceptan int; Holder<bool> y E<bool> restringido
    por Mul fallan en su aplicación. Esto restringe el argumento, no implementa
    operadores del agregado. Se construyen y usan ambos nominales en ejecución.

16. **Aliases.** La identidad canónica existente proporciona satisfacción
    transparente: int=int64, float=float32, double=float64, y alias Real=double.
    No existe una tabla de implementación por alias ni cambios de mangling.

17. **HIR CapabilityBinary.** Contiene behavior y operandos left/right; el
    HirExpr envolvente contiene tipo y span. El único tag de operador es
    BehavioralCapability, por lo que no hay un cache op/behavior contradictorio.
    El verificador recorre operandos, exige T op T -> T y prueba la garantía
    simbólica o satisfacción concreta. Rechaza borrado de la metadata mediante
    reemplazo por un Binary entero sobre T. También audita cuerpos no usados.

18. **Sustitución.** El worklist sustituye el tipo del resultado y ambos
    operandos con el Substitution existente. Los Move simbólicos se convierten
    a Local cuando el tipo sustituido es Copy, como antes. No se fabrica layout
    ni se cambia la clasificación de T durante el checking inicial.

19. **Concretización.** `concrete_behavior_op` sólo acepta un built-in probado
    por `satisfies_behavior`. CapabilityBinary se transforma a Binary concreto
    durante `substitute_expr`. Una resolución imposible produce E0348. La
    verificación de HIR concreto rechaza incluso un CapabilityBinary residual
    cuyos operandos ya son enteros válidos; la conversión no es opcional.

20. **Mapeo entero.** Add -> AddIntegerChecked;
    Sub -> SubtractIntegerChecked; Mul -> MultiplyIntegerChecked.
    La información signed/unsigned y el ancho siguen siendo del TypeId. MIR
    conserva IntegerOverflow y LLVM selecciona sadd/uadd, ssub/usub,
    smul/umul.with.overflow. No wrapping, nsw/nuw ni semántica debilitada.

21. **Mapeo float.** Add -> AddFloat; Sub -> SubtractFloat;
    Mul -> MultiplyFloat. LLVM emite fadd/fsub/fmul de float o double según el
    tipo sustituido. No se selecciona una operación float antes de sustitución.

22. **MIR.** No se agrega un Rvalue conductual. El lowering enumera
    CapabilityBinary como violación interna de la frontera HIR ya verificada;
    los TypedHir públicos tienen campos privados y se producen mediante análisis
    verificado. La prueba HIR comprueba el rechazo antes de ese lowering.
    El verificador MIR existente rechaza locales/firma con T sin resolver.

23. **SSA.** No cambia su representación ni implementación. Los operadores
    escalares y los contratos de trap existentes son la autoridad. Tests
    independientes corrompen tipos runtime en MIR y el resultado aritmético en
    SSA para Add/Sub/Mul: ambas fronteras rechazan los seis estados simbólicos.

24. **LLVM y runtime.** No se modifica backend ni runtime. Las instancias usan
    las firmas y llamadas estáticas existentes; la aritmética se emite directa.
    No hay diccionarios, witness tables, vtables, objetos de capacidades,
    parámetros ocultos ni llamadas indirectas de operador. Los dumps MIR/SSA
    no contienen CapabilityBinary y LLVM no contiene metadata de capacidades.

25. **Orden de instanciación.** El análisis de todas las funciones y su
    verificación paramétrica preceden a `monomorphize`. Las llamadas validan
    requisitos antes de solicitar instancias; `Monomorphizer::request` repite
    la validación antes de insertar en ids/queue/parents. El contexto prestado
    del verificador no crea InstanceIds artificiales ni clona cuerpos HIR.

26. **Overflow preservado.** Se ejecutan Add/Sub/Mul genéricos sobre los diez
    tipos enteros. Add(max,1), Sub(min,1), Mul(max,2) deben terminar con SIGILL
    (señal 4): treinta ejecuciones, incluyendo los cuatro casos mínimos signed/
    unsigned Add/Mul. MIR y SSA retienen IntegerOverflow, y LLVM contiene el
    intrínseco de overflow de la operación/signo correspondiente.

27. **IEEE preservado.** Doce ejecuciones: tres operadores por float32,
    float64, float y double. Cada programa comprueba -0 y +0 mediante el signo
    del infinito de su recíproco, +infinito, -infinito y NaN. Se exige la
    instrucción LLVM exacta `fadd/fsub/fmul float|double`, sin flags fast-math.

28. **Diagnósticos.** E0314: nombre desconocido; E0315: restricción duplicada;
    E0268: operador simbólico sin garantía; E0347: operandos heterogéneos del
    contrato; E0316/E0317: requisito incumplido explícito/inferido, incluido
    forwarding; E0348: metadata/cuerpo paramétrico inválido o concretización
    imposible. E0290 rechaza operaciones residuales en HIR concreto. Se
    conservan E0291 para uso tras Move y E0346 para aritmética matemática sobre
    elementos simbólicos, aun con Add declarado. No se presentan como errores
    de almacenamiento las fallas conductuales.

29. **Dumps, determinismo e identidad.** La tabla de tipos muestra
    `structural guarantees=[...]` y `behavioral guarantees=[Add, Mul]`;
    generic HIR muestra CapabilityBinary y behavior. Los cuerpos instanciados
    muestran Binary con su operación escalar concreta. Los conjuntos se ordenan
    Copy, Relocatable, Storable, Behavioral(Add), Behavioral(Sub), Behavioral(Mul).
    TypeId y símbolos siguen dependiendo de declaración y argumentos concretos,
    no del conjunto ni orden de restricciones. Se comparan los cuatro dumps de
    dos compilaciones y LLVM completo al permutar/agregar garantías satisfechas.

30. **Tests exactos.** `cargo test --workspace`: **237 aprobados, cero fallos**:
    7 backend, 33 frontend, 22 middle y 175 integración. Once tests nuevos;
    permanecen verdes los 226 anteriores de V0..V28.

    | Test nuevo | Cobertura |
    |---|---|
    | vertical29_behavior_is_separate_from_structural_properties | satisfacción del arena, propiedades simbólicas y matriz de implicaciones |
    | vertical29_hir_rejects_corrupt_parametric_and_concrete_operations | ocho corrupciones paramétricas; residual concreto y bool falsificado |
    | vertical29_invalid_requirements_never_allocate_or_cache_instance_ids | rechazo previo a IDs, caché, cola y parents para las tres capacidades |
    | vertical29_forwarding_metadata_is_independently_verified | requisito del callee alterado coherentemente detectado en el caller |
    | vertical29_native_behavior_and_cross_module_forwarding | cuatro fixtures escalares y un programa entre módulos |
    | vertical29_all_builtin_scalars_reify_each_independent_behavior | quince nombres escalares/aliases, tres operadores, quince ejecuciones |
    | vertical29_structured_rejections_even_without_instances | 22 casos negativos: garantías, argumentos, forwarding, nominales, nombres, heterogeneidad y propiedad |
    | vertical29_integer_overflow_and_underflow_remain_checked | diez enteros por tres operadores; treinta traps nativos |
    | vertical29_ieee_zero_infinity_nan_and_no_fast_math | doce ejecuciones IEEE y forma exacta de instrucciones LLVM |
    | vertical29_deterministic_dumps_and_unchanged_instance_abi | cuatro dumps repetidos y LLVM idéntico con orden/garantías cambiados |
    | vertical29_mir_ssa_reject_unresolved_behavioral_scalar_types | seis corrupciones independientes MIR/SSA |

    Total dedicado V29: **62 ejecuciones nativas**. También pasan
    `cargo fmt --all --check`, `cargo clippy --all-targets -- -D warnings` y
    `git diff --check`. Comandos Cargo desde `compiler-next`.

31. **Instancias inválidas.** Por cada Add/Sub/Mul se solicita bool, Buffer<int>
    y bool repetido, comprobando vacío de ids, queue, parents, instances y
    functions tras cada rechazo. Después int obtiene exactamente InstanceId(0),
    la repetición reutiliza ese ID y otro Buffer inválido no modifica la caché.
    Doce solicitudes rechazadas en total y seis solicitudes válidas/deduplicadas.

32. **Snapshots de compilación.** Driver debug; mismo entorno; un proceso
    nuevo por muestra, un warmup descartado y diez muestras por fixture. Core
    suma ocho fases parse-through-LLVM, excluyendo startup, discovery, I/O,
    dumps, clang/link y temporizadores inclusivos duplicados. Se reconstruyó
    V28 desde `git archive 8efe403dd2f63529bc863740c136dc9dd3264976 compiler-next`
    en `/tmp/aether-v29-baseline-source`; las mediciones se ejecutaron sin builds
    ni tests concurrentes. rustc 1.97.1; clang 22.1.8.

    | Compilador / fixture | Core media ms | Core mediana ms |
    |---|---:|---:|
    | V28 baseline / v28_vector_contiguous | 1.951 | 1.906 |
    | V29 / v28_vector_contiguous | 1.748 | 1.687 |
    | V29 / Add int | 0.828 | 0.840 |
    | V29 / Add+Mul int | 0.893 | 0.805 |
    | V29 / Add+Mul double | 0.897 | 0.906 |
    | V29 / comportamiento entre módulos | 1.601 | 1.604 |

    Son snapshots descriptivos, no una afirmación estadística de mejora ni
    benchmarks de ejecución. Cada fixture incluye comprobaciones propias.
    El coste de verificación paramétrica entra en frontend.semantic_bodies;
    el coste runtime de dispatch es inexistente por construcción del código.
    Datos: [v29-debug.json](../../compiler-next/tests/timings/v29-debug.json).
    Reproducción desde compiler-next:

    ```sh
    python3 tests/measure-v29.py --runs 10 \
      --baseline-binary /tmp/aether-v29-baseline-source/compiler-next/target/debug/aether-next \
      --baseline-revision 8efe403dd2f63529bc863740c136dc9dd3264976
    ```

33. **Legacy.** No se modificaron compiler-rs, runtime, CLI legacy ni scrap.
    `bash compiler-next/tests/run-differential.sh`: **21 comparaciones,
    cero fallos**. Los binarios no rastreados preexistentes FaCAether y
    FaCAetherO0 permanecen ajenos al cambio.

34. **Deuda aceptada.** Contratos cerrados, homogéneos y built-in solamente.
    Copy permanece independiente; un algoritmo que reusa parámetros necesita
    declararlo. Buffer, préstamos, escape y los límites del worklist conservan
    sus reglas previas. HIR mantiene el verificador central existente y un
    contexto de firmas paramétrico/concreto; no se introduce un nuevo framework
    de traits. El lowering presupone HIR verificado, y MIR/SSA no pueden
    representar CapabilityBinary. La sustitución de firmas en el verificador
    usa los tipos ya internados durante resolución. Traps abortivos sin unwind,
    target bootstrap Linux x86_64 y política IEEE previa sin cambios.

35. **OPEN DECISIONS.** Implementaciones de operadores por el usuario;
    contratos de parámetros prestados frente a consumidos para tipos no-Copy;
    operandos/resultados heterogéneos y associated types; identidades Zero/One;
    aritmética genérica de contenedores; separación y semántica de dot, outer y
    matmul; orden de reducción, overflow acumulado y IEEE de futuros productos.
    Ninguna de estas decisiones queda admitida implícitamente por V29.

36. **Problemas arquitectónicos encontrados.** El verificador independiente
    no auditaba los cuerpos paramétricos conservados: se añadió validación
    anterior a instancias, reusando el verificador de expresiones/bloques/Places
    con tablas de firmas diferenciadas. Se evita crear un HirFunction artificial
    con InstanceId o copiar árboles durante esa auditoría. La metadata de
    restricciones se duplicaba legítimamente entre declaración y arena sin
    comprobar correspondencia; ahora se verifica. E0268 era una expectativa
    pública de regresión V8, por lo que se amplió su mensaje sin cambiar código.
    La identidad de Add/Sub/Mul se mantiene separada de propiedades concretas
    y de las consultas matemáticas V27/V28; el backend no necesitó cambios.

37. **Recomendación NEXT-VERTICAL-30.** Extender de forma acotada los kernels
    matemáticos existentes a elementos genéricos con garantías conductuales,
    definiendo primero qué pruebas independientes de Copy/Storable necesita la
    lectura prestada y la inicialización de resultados. Mantener checked/IEEE,
    formas, strides y concretización verificables; posponer implementaciones
    de usuario, productos/reducciones y resultados heterogéneos a contratos
    independientes. V29 no habilita esa extensión anticipadamente.
