# EXCEPTION-V2 — constructor unwind

Estado: **implementado y calificado** para el bootstrap Linux x86-64 en O0/O2.

## Resultado

EXCEPTION-V2 elimina E0436 para `throw`, llamadas directas, llamadas directas de
método y construcción de clases durante `init`. La construcción sigue sin
publicar un handle hasta que terminan base y fields. Si una operación propaga,
el compilador destruye solamente los subobjetos owning que se inicializaron por
completo, en orden inverso, libera una vez la allocation most-derived y reanuda
el mismo evento excepcional.

`try`/`catch` dentro de `init` conserva temporalmente E0436. Los invokes
virtuales y de interface conservan E0437. No se añadió ninguna otra superficie
de excepciones.

## Estados de construcción parcial

El protocolo distingue:

1. evaluación de argumentos, todavía sin allocation;
2. `ObjectAlloc`, que produce solamente un token `Unpublished`;
3. estado del initializer `{ base_completed, initialized_fields }`;
4. `PublishObject`, única transición a un handle fuente owning;
5. rollback excepcional de subobjetos, seguido por el free raw exterior.

`ConstructorUnwindPlan` conserva en HIR la clase, el `LocalId` exacto de `this`
y el orden canónico de fields owning derivado de la receta de destrucción. El
prefijo efectivamente vivo no se almacena en una bitmap: se reconstruye de
`BaseInit` y `FieldWrite { initialize: true }` sobre cada path. Los joins de
fields owning ya deben concordar; por eso EXCEPTION-V2 no introduce flags de
construcción. Los flags ordinarios siguen limitados a owners raíz realmente
condicionales.

## Rollback de base y derived

Cada frame initializer responde por sus propios fields y por las bases que ya
terminaron. Un `BaseInit` que propaga no marca la base como completa: el
initializer base ya limpió su propio prefijo. Si la base retornó normalmente,
los fields derived ya inicializados se limpian primero y luego los fields de la
base completa. Esto se aplica recursivamente a herencia de cualquier profundidad
admitida.

El `InitCall` del constructor exterior tiene una obligación diferente: después
del rollback ejecutado dentro del initializer, su landing pad libera la
allocation `Unpublished` most-derived. No invoca `aether_object_release`, no
selecciona el destructor dinámico y no incrementa el contador de destrucciones
completas. La publicación consume el token y hace imposible ese free raw en el
path normal.

## Orden y ownership

`ClassOp::ConstructionCleanup` materializa una lista ordenada de `FieldId` y un
bit semántico `free_allocation`. En un frame initializer, la lista debe ser
exactamente la subsecuencia viva de la receta canónica: fields derived en orden
inverso, después fields de cada base en orden inverso. En el caller del
`InitCall`, la lista debe estar vacía y `free_allocation` libera solamente el
storage completo.

Cada field usa el drop glue tipado existente. Esto cubre `Buffer<int>` y handles
de clase con ARC; los escalares solo participan en definite initialization y no
generan drop. Para satisfacer el caso requerido de class owners, los fields
privados de tipo clase concreta se admiten con el lifecycle ya existente; no se
admitieron interfaces almacenadas, extracción owning, borrows interiores ni una
nueva política de ciclos.

Los argumentos se evalúan antes de allocation. Owners temporales ya evaluados
se registran hasta entrar al `InitCall`; si un argumento posterior propaga, se
destruyen en orden inverso. Cuando empieza el initializer, esos argumentos ya
fueron transferidos y el pad del caller no los vuelve a destruir.

## HIR, MIR y SSA

- HIR conserva y verifica `ConstructorUnwindPlan`. Un initializer sin plan, un
  plan en una función ordinaria, un receiver/clase incorrectos o un orden que no
  coincide con metadata nominal se rechazan.
- MIR pone `unwind` explícito en `InitCall` y `BaseInit`, además de calls y
  métodos directos. Cada landing pad contiene drops concretos y
  `ConstructionCleanup`; el verificador reconstruye base/fields y exige cleanup
  exacto antes de `ResumeUnwind`.
- SSA conserva el plan, los edges y la operación. Su ledger separa el estado
  normal del excepcional de un invoke: los argumentos están consumidos en
  ambos, pero base completion, resultado y publicación existen solo en el edge
  normal. La verificación rechaza owners/eventos duplicados y cleanup omitido,
  duplicado, desordenado o aplicado fuera de `init`.

No se usa estado global/TLS ni bitmap runtime de fields.

## LLVM EH

El backend continúa usando Itanium EH solamente como transporte físico.
`InitCall` y `BaseInit` bajan a `invoke` cuando exceptions están habilitadas.
Los landing pads ejecutan los drops decididos en MIR/SSA y después usan el
`resume` existente. El free de una allocation parcial llama directamente al
boundary de allocation con el layout most-derived verificado. El payload y el
record originales no se reemplazan.

Traps aritméticos, bounds, allocation y ARC siguen siendo abortivos, sin edge
excepcional ni promesa de rollback.

## Qualification y corrupciones

`crates/aether-driver/tests/exception_v2.rs` y
`tests/programs/exception_v2_smoke.ae` cubren:

- excepción antes de cualquier field;
- excepción durante argumentos, incluido un owner temporal previo;
- base init que falla después de inicializar un field;
- base completa con el primer field derived pendiente;
- varios fields owning con uno pendiente;
- cleanup exacto de Buffer y class owner;
- tres niveles, con orden derived → middle → root;
- throw directo, call directo y método directo que propaga;
- una sola liberación de la allocation parcial y ausencia de destructor completo;
- llegada del evento original al catch exterior;
- O0/O2 con contadores ARC/object/drop/heap;
- corrupción independiente del plan HIR y del cleanup MIR/SSA;
- permanencia de E0436 para `try` en init y de E0437 para invoke virtual.

La suite EXCEPTION-V1 permanece verde. Los gates de release son
`cargo test --workspace`, rustfmt, clippy con warnings denegados,
`git diff --check` y el differential harness.

## Deuda restante

Quedan fuera de EXCEPTION-V2: `finally`, catch local dentro de `init`, invokes
virtual/interface/indirectos, user `deinit`, generics de clases/excepciones,
async/threads, FFI, stack traces/messages y conversión de traps. E0437 no cambió.
Los class-owner fields permanecen privados, no-self y bajo ARC no atómico; weak
owners y una política general de ciclos siguen siendo trabajo OOP separado.
