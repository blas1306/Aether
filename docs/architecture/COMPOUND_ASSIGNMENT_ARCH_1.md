# Aether — COMPOUND-ASSIGNMENT-ARCH-1

Estado: **CLOSED**

Fecha: 2026-11-27

Autoridad: `compiler-next` en `5e1360694c65`

Alcance: contrato semántico y arquitectura. Este documento no habilita sintaxis ni
autoriza una implementación productiva.

## 1. Decisiones normativas

V1 reserva cinco statements de asignación compuesta:

```aether
place += rhs;
place -= rhs;
place *= rhs;
place /= rhs;
place %= rhs;
```

Una asignación compuesta no es una expresión, no produce valor y no puede aparecer
en un initializer, argumento, `return`, interpolación ni dentro de otra expresión.
No existen asignaciones encadenadas. El parser debe reconocer `+=`, `-=`, `*=`,
`/=` y `%=` por maximal munch y construir un statement propio; no puede convertir
texto fuente a `place = place op rhs`.

El contrato queda cerrado con estas propiedades:

1. el destino se evalúa y estabiliza antes del RHS;
2. el valor anterior se lee una vez y el RHS se evalúa una vez;
3. sólo escalares numéricos built-in, incluidos sus aliases transparentes, son
   destinos V1;
4. la operación usa exactamente el plan tipado, los checks y los traps del operador
   binario correspondiente;
5. sólo el camino normal que completa la operación escribe, exactamente una vez;
6. durante el RHS se protege la validez de la ubicación, no la exclusividad general
   de acceso al valor;
7. HIR conserva la intención; MIR y SSA conservan una identidad de transacción
   verificable; LLVM reutiliza load, aritmética checked/float y store existentes.

## 2. Base inspeccionada

La autoridad implementada que condiciona este diseño es:

- `HirPlace`: base `Local`, `Dereference` o `ClassField`, seguida por projections
  `Field` e `Index` (`aether-frontend/src/hir.rs`);
- MIR `Place`: conserva la misma ruta y materializa receiver, reference e índices
  como `Operand` (`aether-middle/src/mir.rs`);
- `SsaPlace`: conserva base, projections y operandos SSA
  (`aether-middle/src/ssa.rs`);
- los fields escalares de class no usan ese Place genérico para la lectura/escritura
  directa: conservan el camino dedicado `ClassOp::FieldRead/FieldWrite`; la base
  `ClassField` de Place cubre storage interior indexable bajo restricciones propias;
- asignación simple: valida un Place en HIR, pero MIR baja hoy el RHS antes de
  `lower_place`;
- loads/stores Copy, `ReplaceString`, `ReplaceOwned`, Move, drop flags y las reglas
  de prohibición de partial move;
- `MutationEffect::{ElementMutation, StableStructuralMutation,
  PotentiallyRelocatingMutation}`, `InvalidationShape`, regiones de borrow y
  provenance de owners;
- operadores enteros checked, división/remainder signed/unsigned y floats IEEE;
- verificadores propios de HIR, MIR y SSA.

Son también normativos para este diseño
`docs/reports/CORE_OPERATORS_AND_ASSIGNMENT_AUDIT_1.md` y
`docs/architecture/AETHER_V1_SEMANTIC_CONTRACT.md`. Documentos o implementaciones
legacy no son autoridad.

## 3. Semántica fuente y tipado

### 3.1 Resolución

Para `P op= R`, el frontend debe:

1. resolver `P` una sola vez como `HirPlace` escribible;
2. exigir que el tipo canónico de `P` sea un escalar numérico built-in;
3. resolver el operador binario `old(P) op R` mediante el resolver oficial, con el
   tipo del destino disponible como contexto para literales;
4. exigir que el resultado canónico de ese plan sea exactamente el tipo canónico
   de `P`;
5. rechazar cualquier conversión implícita de resultado que reduzca rango o
   precisión.

"Exactamente" compara tipos tras transparentar aliases. El statement conserva el
tipo fuente del alias para diagnósticos, pero no crea aritmética nominal distinta.
Las conversiones value-preserving ya admitidas para operandos siguen admitidas.
No se agrega conversión implícita signed/unsigned, integer/float,
`isize`/`usize`/fixed-width ni narrowing.

Por ejemplo, si la expresión binaria oficial produce `int16`, un destino `int8`
no puede aceptar el resultado de `+=`, aunque una conversión explícita separada
pudiera comprobar el rango. Un literal exacto sí puede adoptar contextualmente el
tipo permitido por las reglas existentes.

### 3.2 Tabla V1

| Statement | Destino | Operación reutilizada | Fallos propios |
|---|---|---|---|
| `+=` | integer o float escalar | suma binaria | overflow entero |
| `-=` | integer o float escalar | resta binaria | overflow entero |
| `*=` | integer o float escalar | multiplicación binaria | overflow entero |
| `/=` | integer o float escalar | división binaria | cero y `MIN / -1` en integer; IEEE en float |
| `%=` | sólo integer escalar | remainder binario | divisor cero; `MIN % -1 == 0` signed |

Los enteros conservan `IntegerOverflow`, `DivisionByZero` y
`DivisionOverflow` exactamente donde los produce el plan vigente. Los floats
conservan IEEE, ausencia de fast-math implícito y la semántica vigente de división
por cero. Un fallo conocido en compile time conserva la categoría diagnóstica del
operador ordinario.

### 3.3 Exclusiones cerradas

V1 no despacha capacidades genéricas `Add/Sub/Mul/Div`, overloads ni métodos. No
admite como destino completo String, Buffer, Array, List, Vector, Matrix, views,
structs, classes, enums, nullable, referencias ni ningún owner o tipo con lifecycle.
Esto no impide que un **elemento escalar numérico** dentro de uno de esos containers
sea destino.

No se infieren Clone, Alias, Transfer, retain, deep copy ni `ReplaceOwned`. Tanto el
old value como el resultado son Copy y no abren una obligación de Drop. Esta
restricción es intencional y hace que compound assignment V1 quede fuera de los
caminos de Move y replacement owning.

## 4. Destinos admitidos

Un destino sólo se admite si la asignación simple ya admite exactamente ese Place,
es escribible y su valor final cumple la sección 3.

| Forma de Place | V1 | Condición |
|---|---:|---|
| local mutable | sí | escalar numérico; no `const` ni binding single-init |
| field de struct | sí | field final escalar, root mutable y lectura Copy válida |
| field escalar de class | sí | camino dedicado FieldRead/FieldWrite, receiver `mut`, inicializado y acceso vigente |
| `Array/List/Buffer[i]` | sí | selector escalar, container escribible y bounds válidos |
| `Vector[i]`, `Matrix[i,j]` | sí | elemento escalar; aridad/base vigentes |
| `ViewMut`/views matemáticas mutables | sí | elemento escalar y provenance escribible |
| view read-only | no | no aporta write capability |
| `*ref mut T` | sí | pointee final escalar o proyección escalar válida |
| `*ref T` | no | referencia compartida |
| projections anidadas | sí | cada paso forma el mismo Place válido que en `=` |
| slice | no | `SliceAssign` tiene contrato distinto |
| temporary/call result | no | no es Place addressable admitido |
| índice owning | no | además de no ser escalar, no existe replacement indexado |

No se amplía accidentalmente la cobertura de asignación simple. En particular,
const bloquea rebind y mutación proyectada; class-field storage no adquiere borrow
público; un local de tipo reference/view sigue siendo single-init aunque su pointee
o backing mutable pueda modificarse.

## 5. Orden de evaluación

El orden normativo para `P op= R` es:

1. evaluar la base dinámica de `P` una vez;
2. evaluar cada projection de `P`, de adentro hacia afuera y sus operandos de
   izquierda a derecha, una vez;
3. estabilizar la identidad y lifetime de `P`;
4. ejecutar checks de acceso, null/provenance y bounds necesarios para leer y
   escribir `P`;
5. leer el old value una vez;
6. evaluar `R` una vez, con su orden ordinario;
7. aplicar conversiones de operandos ya resueltas y el operador binario;
8. si la operación completa normalmente, escribir el resultado una vez al mismo
   Place estabilizado;
9. terminar la región de protección.

Si un check de los pasos 1–4 falla, el RHS no se evalúa. Si el RHS lanza o el
operador/conversión hace trap, el store del paso 8 no ocurre. No hay store
especulativo ni restore compensatorio.

En `matrix[row(), column()] += rhs()`, el orden observable es `row`, `column`,
checks, load, `rhs`, operación y store. Receiver, reference, índices y cualquier
endpoint se capturan; nunca se reejecutan para el store.

## 6. Place stabilization

### 6.1 Identidad estabilizada

Un `StableCompoundDestination` conceptual contiene:

- base resuelta y su provenance;
- receiver/reference evaluado y una garantía de lifetime hasta el final;
- sequence exacta de FieldId y projections Index;
- todos los índices ya evaluados en operandos temporales/SSA;
- tipo final, write capability, semántica de índice y traps de bounds;
- owner/backing protegido y la clase de invalidación prohibida;
- `CompoundAssignId` único.

Su identidad de storage es una de dos formas cerradas:

1. `Place(HirPlace/MIR Place/SsaPlace)` para locals, dereference y projections;
2. `ClassScalarField { receiver, field, field_type, mutable, initialized }` para el
   camino dedicado que hoy implementan `ClassOp::FieldRead/FieldWrite`.

La segunda forma no se falsifica como `HirPlaceBase::ClassField`: esa base tiene un
contrato distinto para storage interior indexable. Ambas formas satisfacen la misma
semántica fuente de Place y comparten id, orden, protection y verificación de
transacción.

No es obligatorio convertirlo tempranamente en un raw pointer. El lowering puede
conservar la receta y rematerializar una dirección desde operandos capturados sólo
si el root/backing permanece protegido. Si conserva un pointer, debe probar además
su lifetime. Para class fields, el receiver capturado debe mantener vivo el object
durante toda la región; para dereference, la región de la reference debe cubrir la
transacción.

Los checks se ejecutan antes del RHS aunque la dirección física se rematerialice al
commit. No se repiten calls, índices ni checks observables. Una optimización puede
eliminar un check repetido únicamente mediante prueba y sin cambiar traps.

### 6.2 Región de protección

La región comienza antes del load estabilizado y termina después del único commit
normal. Su propiedad es:

> La ruta capturada debe seguir designando almacenamiento vivo, del mismo tipo y
> con el mismo slot lógico hasta el commit.

Esto es una protección de ubicación. No convierte `ref mut` en una referencia
exclusiva/noalias y no prohíbe toda escritura aliased. Reutiliza provenance,
regiones y efectos existentes, con un consumidor nuevo: la transacción compuesta.

Para un índice, se prohíbe tanto relocalizar el backing como cambiar el rango de
slots de forma que el índice o su identidad lógica puedan invalidarse. Por ello
`StableStructuralMutation` no es automáticamente segura: `pop`, `remove` o
`swapRemove` pueden invalidar o cambiar un slot aun sin realloc.

Cuando un efecto puede alcanzar la misma provenance y el compilador no puede
demostrar que preserva ubicación, debe rechazar de forma conservadora. No se puede
solucionar guardando un dangling pointer ni aplazando silenciosamente bounds.

## 7. RHS, mutation effects e invalidation

Los efectos previos del RHS son observables y no son transaccionales. Sólo el store
propio de `op=` tiene semántica de commit.

| Efecto del RHS sobre provenance compartida | Decisión |
|---|---|
| modifica exactamente el mismo slot escalar | permitido si no invalida ubicación; el resultado usa el old capturado y el commit final sobrescribe ese valor |
| modifica otro field del mismo owner | permitido si es disjunto y no reemplaza/mueve/destruye el root |
| modifica otro elemento de la misma colección | permitido si es `ElementMutation` y preserva descriptor, backing, rango e identidad del slot capturado |
| modifica el mismo elemento por un alias | permitido bajo la misma regla; el commit final gana |
| `push`, `reserve`, crecimiento de Matrix o posible realloc | rechazado si puede alcanzar el backing protegido |
| `pop`, `remove`, `swapRemove` u otra mutación de rango/orden | rechazado si puede alcanzar el slot protegido |
| reemplaza, mueve o destruye el root | rechazado durante la región |
| reemplaza un descriptor/owner que contiene la ruta | rechazado durante la región |
| efecto desconocido con acceso posible al root/backing | rechazado conservadoramente |
| mutación sobre provenance demostrablemente distinta | permitido |

Ejemplo conceptual: si `f(&mut x)` cambia `x`, `x += f(&mut x)` —cuando exista una
forma fuente tipable equivalente— calcula con el valor leído antes de `f` y el
store final gana. Esta regla no promete que toda forma de alias sea expresable; sólo
fija el resultado cuando el programa supera ownership y typing existentes.

Para `list[i] += rhs`, un RHS que sólo escribe `list[j]` puede ser seguro, incluso si
`i == j`, porque el slot sigue vivo. Un RHS que hace `list.push`, `reserve` o reduce
la longitud no es seguro y debe fallar antes de generar código si comparte
provenance. Si la igualdad de roots no puede decidirse, se falla cerrado.

## 8. Excepciones, traps y atomicidad limitada

- excepción durante RHS: no hay compound store; el mecanismo ordinario limpia
  temporales del RHS y propaga/captura la excepción;
- trap durante bounds previo: RHS no evaluado y ningún compound store;
- trap durante conversión u operador: ningún compound store;
- éxito: un store;
- integer trap sigue siendo abortivo y no adquiere unwind Aether;
- float conserva sus resultados IEEE, incluidos infinity/NaN donde correspondan.

"No hay compound store" no significa rollback. Si el RHS imprimió, mutó otro valor
o incluso escribió el mismo slot de forma permitida antes de lanzar, esos efectos
permanecen según el modelo ordinario. El compilador no restaura el old value.

El statement ofrece atomicidad sólo respecto de su publicación final: no publica
un resultado parcial. No es una primitiva atómica de concurrencia ni de memoria.

## 9. Representación IR

### 9.1 AST/HIR

AST debe tener `CompoundAssign { place, op, value }`. HIR debe conservar:

```text
HirStmtKind::CompoundAssign {
    id: CompoundAssignId,
    destination: HirCompoundDestination,
    op: CompoundAssignOp,
    rhs: HirExpr,
    plan: HirScalarBinaryPlan,
    destination_type: TypeId,
    protection: CompoundPlaceProtection,
}
```

`HirCompoundDestination` es la suma cerrada `Place(HirPlace) |
ClassScalarField(HirClassFieldDestination)`. `CompoundAssignOp` queda diseñado como
familia extensible, pero V1 sólo permite
Add, Subtract, Multiply, Divide y Remainder. El `plan` contiene la operación
concreta ya seleccionada, conversiones, signedness y traps; MIR no vuelve a inferir.
La metadata de protection es una afirmación a verificar, nunca autoridad por sí
sola.

### 9.2 MIR

MIR debe bajar el Place **antes** del RHS y capturar sus operandos. Para conservar la
relación aun cuando el RHS produzca CFG, se definen dos operaciones middle-end
específicas, no operaciones LLVM:

```text
old = CompoundLoad  { id, stable_destination, protection }
... lowering ordinario del RHS ...
result = Binary     { plan, converted_old, converted_rhs }
_ = CompoundCommit { id, stable_destination, result }
```

`CompoundLoad` realiza/materializa los checks de acceso y bounds. `CompoundCommit`
es un store Copy con provenance de compound transaction. Para el caso general,
ambos contienen el mismo Place estructural (mismos operandos capturados), no dos
resoluciones equivalentes. Para un field escalar de class contienen el mismo
receiver capturado, `FieldId`, tipo y capability y se bajan respectivamente mediante
los contratos existentes de FieldRead y FieldWrite. El `id` no vuelve válidos
destinos diferentes.

No se usa `ReplaceString`, `ReplaceOwned`, Move ni Drop. Un camino throwing/trapping
sale sin commit. Un camino normal del statement contiene exactamente uno.

### 9.3 SSA

SSA conserva `SsaCompoundLoad { id, destination, protection }` y
`SsaCompoundCommit { id, destination, value }` hasta la última verificación
semántica. `SsaCompoundDestination` conserva la misma alternativa cerrada entre
`SsaPlace` y field escalar de class dedicado.
Los valores de base e índices dominan el load; el load domina el RHS normal y la
operación; la operación domina el commit. El commit usa directamente el resultado
del plan, salvo identidades demostrables, y comparte la misma identidad de Place.

Los optimizadores deben tratar la región como memory-effecting y respetar alias,
traps, exceptions e invalidation. No pueden fusionar transacciones, adelantar el
store, releer old después del RHS ni mover checks a través de efectos observables.
Tras la última verificación, codegen traduce load/commit a mecanismos existentes.

### 9.4 LLVM

No se agrega opcode, intrinsic ni runtime helper de compound assignment. Se
reutilizan:

- address/index helpers y bounds checks existentes;
- un load del escalar;
- widening/conversiones ya aprobadas por el plan;
- `llvm.*with.overflow`/checks enteros, guards de division/remainder y operaciones
  floating existentes;
- un store normal en el único camino de éxito.

La intención semántica puede desaparecer sólo después de superar HIR, MIR y SSA
verification.

## 10. Verificación independiente

Cada capa reconstruye el contrato desde sus propios datos:

### HIR verifier

- statement-only y operador V1;
- Place escribible admitido por asignación simple;
- destino escalar built-in/alias y old Copy;
- plan binario oficial, tipos/conversiones/traps correctos;
- resultado canónico idéntico al destino;
- protection derivada de la ruta/provenance, no confiada ciegamente.

### MIR verifier

- un `CompoundAssignId` único tiene un load y como máximo un commit por path;
- operandos del Place se producen una vez, en source order, antes del load;
- load/commit tienen Place, tipo, provenance y protection idénticos;
- load y checks dominan evaluación RHS; resultado binario domina commit;
- sólo exits excepcionales/trap pueden abandonar sin commit;
- ninguna operación intermedia invalida el root/backing/rango protegido;
- el commit es Copy y no usa replacement/lifecycle.

### SSA verifier

- dominance, reachability y unicidad por CFG, incluidos joins y loops;
- def-use exacto de old, RHS convertido, binary result y commit;
- equivalencia estructural del `SsaCompoundDestination` —Place completo o tuple
  receiver/field/type/capability de class—, no sólo igualdad del id;
- alias/mod-ref y effect scan de toda la región;
- traps/exceptional successors no alcanzan commit;
- el normal successor no puede eludirlo ni ejecutarlo dos veces;
- optimizaciones no cambiaron orden observable ni trap categories.

Metadata corrupta nunca autoriza la operación: si el grafo no permite reconstruir
la prueba, el verifier rechaza.

### Tests de corrupción obligatorios

Como mínimo se mutan aisladamente: operador, tipo destino, conversion plan, trap,
id, Place del commit, índice, base/provenance, mutabilidad, orden load/RHS, segundo
load, commit faltante, doble commit, store anticipado, resultado ajeno, bypass CFG,
invalidación estable, invalidación por realloc, Move/Drop/root replacement y
exception edge que alcanza el commit. Cada corrupción debe ser rechazada por la
capa que la recibe.

## 11. Diferencia con asignación simple

La asignación simple vigente ejecuta el RHS antes de los operandos dinámicos del
destino en MIR. Compound assignment ejecuta y comprueba el destino antes del RHS.
Este milestone no cambia `=`.

Consecuencias documentadas:

- `a[index()] = rhs()` observa hoy `rhs` antes de `index`;
- `a[index()] += rhs()` debe observar `index`, bounds y load antes de `rhs`;
- un bounds trap en `=` puede ocurrir después de efectos del RHS; en `op=` ocurre
  antes del RHS;
- extraer un helper común de lowering sin parametrizar el orden sería incorrecto.

La diferencia es deuda de coherencia de lenguaje y requiere un milestone separado.
No bloquea este contrato porque ambas formas tienen orden definido y testeable.

## 12. Compatibilidad futura

`CompoundAssignOp`, stabilization, protection, transaction identity y verificación
son reutilizables por `i++`, `i--`, `&=`, `|=`, `^=`, `<<=`, `>>=` y `**=`. Esta
extensibilidad no habilita ninguna de esas sintaxis ni fija todavía sus tablas de
tipos/traps. `++/--` podrán mapear a una transacción con literal contextual `1`, no
a una expansión textual.

## 13. Riesgos y límites

1. **Alias/provenance insuficiente.** Un root compartido no probado obliga a
   rechazo conservador; relajar esto exige mejor análisis, no asumir noalias.
2. **Efectos de calls.** La implementación necesita resumir qué provenance puede
   invalidar una llamada o fallar cerrado cuando puede alcanzar el root protegido.
3. **Class lifetime.** Un receiver no owning no puede cruzar el RHS sin keepalive o
   prueba de lifetime.
4. **Optimización.** Load/store comunes perderían demasiado pronto la identidad;
   por eso las ops middle-end se conservan hasta verificación SSA.
5. **Stable structural mutation.** Backing estable no implica slot estable; debe
   consultarse también `InvalidationShape` y rango.
6. **Diagnósticos.** El usuario debe distinguir destino no escribible, binary op
   inválida, narrowing de resultado e invalidación potencial durante RHS.
7. **Concurrencia.** No se promete atomicidad thread-safe.

No queda una ambigüedad semántica esencial abierta. La estrategia exacta de
codificación de los records/ops middle-end puede ajustarse durante implementación
si conserva todos los invariantes y verificaciones aquí definidos.

## 14. Plan incremental de implementación

1. lexer/parser/AST statement-only y negativos de expresión/chaining;
2. HIR `CompoundAssign`, resolver escalar cerrado y verifier/corruption tests;
3. análisis de `CompoundPlaceProtection` sobre provenance/effects;
4. MIR capture-before-RHS, compound load/commit y verifier adversarial;
5. SSA preservation, CFG/effect verifier y corrupción post-optimization;
6. codegen con operaciones existentes y auditoría LLVM;
7. tests fuente de todos los Place shapes, aliases, conversiones y diagnósticos;
8. tests runtime de orden, evaluación única, exceptions, traps e invalidation;
9. differential `-O0`…`-O3`, targets admitidos y qualification final;
10. sólo entonces considerar cerrado un milestone futuro
   `COMPOUND-ASSIGNMENT-V1`.

## 15. Criterios de qualification

La implementación futura sólo califica si:

- los cinco tokens y sólo ellos se aceptan como statement;
- todo uso expresivo/chained es diagnóstico;
- cada forma admitida/rechazada de la tabla de destinos tiene tests positivos y
  negativos;
- cada tipo/ancho signed, unsigned, `isize/usize`, float y alias transparente cubre
  éxito, conversiones y límites relevantes;
- `%=` rechaza floats y tipos no integer;
- instrumentation prueba una evaluación de base, cada índice, old y RHS;
- el orden observado coincide con la sección 5, incluidos bounds-before-RHS;
- overflow/division/remainder conservan categorías y no escriben al fallar;
- throw del RHS omite commit y ejecuta cleanup ordinario;
- mutations estables admitidas conservan slot; cada invalidation prohibida falla
  en compile time, no en forma de dangling access runtime;
- HIR, MIR y SSA verifiers rechazan todo el corpus de corrupción;
- LLVM no contiene un store en paths de trap/exception ni operaciones unchecked;
- resultados y efectos coinciden entre `-O0`, `-O1`, `-O2` y `-O3`;
- no se modifica el orden de `=` ni se habilitan String, owners, whole
  Vector/Matrix, genéricos o futuros operadores;
- el repositorio mantiene todas sus suites oficiales verdes.
