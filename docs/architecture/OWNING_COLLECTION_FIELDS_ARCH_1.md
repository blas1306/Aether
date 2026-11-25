# Aether — OWNING-COLLECTION-FIELDS-ARCH-1

Estado: **ARCHITECTURE CLOSED; IMPLEMENTACIÓN NO INICIADA**, 2026-11-22.

Este documento cierra la investigación y el contrato de los hallazgos F1 y F2
de `APPLICATION-MATURITY-ASSESSMENT-V1`. No implementa cambios. En particular,
no modifica compiler, runtime, Core, STD, OAL ni APIs públicas.

## 1. Decisión ejecutiva

F1 y F2 son defectos **independientes**.

- **F1 es un defecto de representación/verificación SSA de una mutación ya
  admitida.** HIR y MIR conservan correctamente el `Place` proyectado y la
  operación tipada `ListPush`. SSA pierde la continuidad de la obligación en
  su forma promovida a valores y, en la forma materializada en memoria, aplica
  una prohibición genérica de `Store` antes de reconocer el
  `DescriptorCommit` válido. No hace falta replacement de field, partial move,
  sintaxis nueva ni cambio de `List`.
- **F2 no es una capacidad de borrow ausente.** `lines[0]` es un `Place` de
  tipo `string`, no un `ref string`; `*lines[0]` significa dereferenciar el
  valor indexado, no prestarlo. El source original debe seguir rechazado. El
  defecto es que se emite E0293 al intentar cargar prematuramente el elemento
  non-Copy, en lugar de E0271 por dereference de un tipo no-reference. Las
  formas correctas `trim(lines[0])` y `trim(&lines[0])` ya pasan HIR, MIR, SSA,
  LLVM y ejecución O0/O2.

Se recomiendan dos milestones separados:

1. `OWNING-COLLECTION-FIELDS-V1`: continuidad de descriptor/owner en SSA para
   mutaciones tipadas de owners locales y fields.
2. `INDEX-DEREFERENCE-DIAGNOSTIC-V1`: corregir la prioridad/causa diagnóstica
   de `*non_reference_place`, sin legalizar el programa.

No se debe fusionar frontend y SSA bajo una feature nueva de ownership.

## 2. Autoridades y baseline CLOSED

Se inspeccionaron como autoridad:

- `docs/reports/APPLICATION_MATURITY_ASSESSMENT_V1.md`;
- `docs/architecture/AETHER_V1_SEMANTIC_CONTRACT.md`, especialmente evaluación,
  references, ownership agregado, `Array`/`List`, extracción y relocation;
- `docs/architecture/BORROW_ERGONOMICS_ARCH_1.md` y
  `BORROW_ERGONOMICS_V1_REPORT.md`;
- `docs/architecture/ITERATION_ARCH_1.md` e `ITERATION_V3_REPORT.md`;
- `docs/architecture/OWNING_STRUCT_FIELD_REPLACEMENT_ARCH_1.md`, su amendment
  y `OWNING_STRUCT_FIELD_REPLACEMENT_V1_REPORT.md` CLOSED;
- `docs/architecture/SSA_STORE_PROVENANCE_ARCH_1.md` y
  `SSA_STORE_PROVENANCE_V1_REPORT.md` CLOSED;
- contratos de aggregate/drop/unwind del semantic contract y las suites de
  replacement, borrow ergonomics, iteration, exceptions y Store provenance.

La decisión conserva estos contratos CLOSED:

- los partial moves ordinarios de fields o elements non-Copy siguen
  prohibidos;
- `ReplaceOwned` sigue siendo la única transacción de replacement total de un
  slot owning ya inicializado;
- `ListPush`, `ListReserve` y `MatrixAdd` siguen siendo commits tipados de
  descriptor, no replacements;
- `ref`/`ref mut` no implican exclusividad ni LLVM `noalias`;
- el borrow implícito shared existe sólo en un argumento cuya firma concreta
  exige exactamente `ref T`;
- traps de bounds, overflow y allocation siguen siendo abortivos y no
  prometen unwind cleanup.

## 3. Reproducción y evidencia observable

Checkout: `3c5c451854cbddb2d5296ed1873ae837a5e03908`, CLI oficial
`compiler-next/target/debug/aether`, Linux x86-64.

### 3.1 F1 original

```aether
struct Item {
    string name;
}

enum Status {
    Ok,
    Bad
}

struct Result {
    List<Item> items;
    Status status;
}

int main() {
    Result result = Result({}, Status.Ok);
    push(result.items, Item("x"));
    return 0;
}
```

`check` y `build` fallan de igual modo en O0 y O2:

```text
error[E0400] (ssa): SSA owner ValueId(6) remains live at normal return
```

El perfil de optimización no es causal: el error aparece al verificar SSA antes
de la optimización opcional y de LLVM.

### 3.2 Variantes discriminantes de F1

| Variante | O0/O2 | Evidencia |
|---|---|---|
| `List<Item>` owning como local root, sin struct exterior | E0400 | el defecto no es exclusivo de fields |
| `reserve(List<string>, 8)` sobre local root | E0400 | afecta continuidad de descriptor, no sólo el valor de `push` |
| `Result { List<ItemCopy> }`, `ItemCopy` sólo contiene `int` | PASS y runtime 0 | la misma forma HIR/MIR/SSA no activa el ledger de owner string-containing |
| root `Result` previamente address-taken y luego `push(result.items, ...)` | E0400 `SSA memory store type/ownership contract invalid` | reproduce la segunda rama observada por el assessment |
| `push((*resultRef).items, ...)` con `ref mut Result` | PASS y runtime 0 | el `DescriptorCommit` por dereference ya está representado y verificado |

La variante Copy permite inspeccionar la forma SSA análoga sin que el driver
se detenga antes del dump:

```text
%updated_list = ListPush source=%old_result.items, value=%item
%new_result   = InsertField aggregate=%old_result,
                            projections=[items], value=%updated_list
Drop(%new_result)
```

En el reproducer owning, `ValueId(6)` corresponde al resultado `ListPush`; el
aggregate actualizado sí llega a su `Drop`, pero el ledger no registra que
`InsertField` consumió también el descriptor owning insertado.

### 3.3 F2 original

```aether
import std.Text;

int main() {
    List<string> lines = std.Text.lines("x");
    string value = std.Text.trim(*lines[0]);
    println(value);
    return 0;
}
```

`check` y `build`, O0/O2:

```text
error[E0293] (semantic): partial move of non-Copy field `string` is unsupported
```

Las formas con significado de borrow correcto ya pasan y ejecutan en ambos
perfiles:

```aether
string implicit = std.Text.trim(lines[0]);
string explicit = std.Text.trim(&lines[0]);
```

HIR de la primera contiene:

```text
CallScopedSharedBorrow {
    pointee_type: string,
    reference_type: ref string,
    source: Place(Local(lines), Index(0)),
    origin: Implicit,
}
```

MIR y SSA contienen un `Borrow` de `lines[0]`, la operación Text con el mismo
`CallSiteId` y `EndBorrow`. La ejecución O0/O2 imprime `x` y retorna 0.

También pasan O0/O2:

- string owning local a `ref string`;
- field string de struct a `ref string`;
- elemento string de `Array<string>`;
- elemento Copy de `List<int>` a `ref int`;
- `for (ref string item in list)` seguido de `trim(*item)`;
- borrow explícito `&list[0]`.

## 4. Causa raíz F1

### 4.1 HIR conserva el significado correcto

El binder resuelve `result.items` como:

```text
HirPlace {
    base: Local(result),
    projections: [Field(items)],
    ty: List<Item>,
}
```

`push` baja a `HirStmtKind::ListPush` con `StructuralMutation::Push`. El tipo de
elemento `Item` es `Storable + Relocatable`, non-Copy y drop-needing por su
field `string`. El análisis atribuye la provenance del target al root `result`,
comprueba writability/borrows y consume el owner `Item("x")` hacia el tail.

No existe un load owning del field, `Move` proyectado ni estado parcialmente
inicializado. HIR satisface sus invariantes.

### 4.2 MIR conserva la operación tipada

MIR representa una asignación semántica de mutador, con destination y source
idénticos:

```text
result.items = ListPush {
    source: result.items,
    value: item,
    initialization: tail(Item),
    relocation: initialized_prefix(Item),
    mutation: Push,
}
```

El verifier MIR exige owner root vivo, mismo `Place`, tipo exacto, relocation
canónica, traps de allocation canónicos y consumo único del item. El `Drop`
lexical permanece sobre `result` completo. MIR pasa: tampoco es la primera
etapa inválida.

### 4.3 Rama SSA promovida a valores

Un local no address-taken con proyecciones sólo `Field` se promueve. El builder
emite `ListPush` sobre `Value(old_root).Field(items)` y luego `InsertField` para
formar el nuevo valor root.

El ledger `verify_ownership_ledger` identifica como owners los valores
drop-needing que contienen string o closure. Sus consumos actuales tienen dos
omisiones relevantes:

1. `ListPush` cuenta el owner del elemento insertado, pero no la obligación del
   descriptor source cuando el source es el root SSA completo;
2. `InsertField` cuenta el aggregate anterior, pero no el `value` owning
   insertado.

Por eso:

- en `List<string>` local, la definición anterior del List queda viva;
- en `Result { List<Item> }`, el resultado `ListPush` queda vivo aunque el nuevo
  `Result` sea destruido.

La primera representación que viola un invariante es, por tanto, el **SSA raw
producido por `build_ssa` respecto del ledger lineal**. El algoritmo LLVM aún
no se ejecuta.

### 4.4 Rama SSA materializada en memoria

Si el root fue address-taken, el builder emite:

```text
%updated = ListPush source=MemoryLocal(result).items, value=%item
Store MemoryLocal(result).items, %updated,
      DescriptorCommit(ListPush)
```

`verify_store_provenance` ya sabe demostrar producer, source/destination
idénticos, adjacency, single use y clase de commit. Sin embargo, la verificación
genérica de `SsaOp::Store` rechaza antes todo Store drop-needing con base
`MemoryLocal`/`Value` y proyecciones exclusivamente `Field`, sin exceptuar un
`DescriptorCommit` validado. Ésta es la causa exacta del segundo mensaje
observado en el consumer mayor.

El caso por `ref mut` usa base `Dereference`; no cae en esa prohibición y pasa.
Eso explica por qué el workaround del assessment y `examples/expense_tracker`
es estable.

### 4.5 Clasificación

F1 no requiere una capacidad source nueva. El semantic contract ya admite:

- `List<T>` como field de struct owning;
- mutación estructural de un `List<T>` writable;
- relocation y drop de elementos owning;
- borrow provenance hacia el owner root;
- return y recursive Drop del aggregate completo.

El defecto es una discontinuidad entre dos representaciones SSA del mismo
`DescriptorCommit`.

## 5. Causa raíz F2

### 5.1 Interpretación real

El parser/binder interpreta:

```text
*lines[0]
```

como:

```text
Dereference(Index(Name(lines), 0))
```

No se interpreta como `Borrow(Index(...))`. En Aether:

- `&place` crea `ref T`;
- `&mut place` crea `ref mut T`;
- `*reference` accede al pointee de una referencia existente;
- `place[index]` conserva categoría de Place en contextos de assignment o
  borrow, y produce una lectura sólo en un contexto de valor.

`lines[0]` tiene tipo `string`. No tiene tipo `ref string` y la indexación no
inserta automáticamente una capa reference.

### 5.2 Por qué aparece E0293

Para resolver el outer dereference, `resolve_expr_place` evalúa primero su
operand mediante `expression(operand, None)`. El `Index` entra así a contexto
de valor y `load_place` intenta cargar el `string`. Como es non-Copy y el
lenguaje no admite extracción parcial por indexing, `load_place` emite E0293.
La comprobación posterior que habría emitido E0271 por dereference de un
non-reference nunca se alcanza.

Cuando el source de la call es simplemente `lines[0]`,
`adapt_call_argument` ve primero el `Place` exacto de tipo `string` para el
parámetro concreto `ref string`, crea `CallScopedSharedBorrow` y no llama a
`load_place`. No hay Move, Alias, Clone ni owner nuevo.

### 5.3 Clasificación

El source original es semánticamente inválido. E0293 describe una operación
intermedia que el usuario no pidió y oculta el error primario. F2 es un defecto
de **prioridad y precisión diagnóstica**, no de borrowing, indexing ni SSA.

## 6. Contrato semántico normativo

### 6.1 Observación shared de un elemento non-Copy

Para un owner vivo `collection : Array<T> | List<T>` y un índice válido, con
`T` non-Copy:

```aether
inspect(collection[i]);       // si inspect espera ref T
inspect(&collection[i]);      // forma explícita equivalente
```

son válidos cuando el `Place` es addressable, el tipo es exactamente T y la
región no escapa. La operación:

- evalúa base e índice una vez, de izquierda a derecha;
- ejecuta el bounds check normal;
- obtiene la dirección del slot inicializado;
- crea sólo un borrow shared `ref T`;
- no carga T por valor, no mueve el slot y no crea Alias/Clone/retain;
- conserva como provenance el owner collection root.

Una asignación owning por valor desde `collection[i]` continúa prohibida. Para
extraer ownership deben usarse únicamente protocolos ya cerrados como
`pop`, `remove` o `swap_remove`, que actualizan el prefijo inicializado.

### 6.2 Mutación de colección owning dentro de struct

Para un writable Place `p : List<T>`, incluso `root.field` o
`root.inner.field`:

```aether
push(p, value);
reserve(p, capacity);
```

son mutaciones estructurales tipadas del List. No son:

- lectura/move del field;
- replacement source de `root.field`;
- `ReplaceOwned`;
- partial move del aggregate;
- Clone o reconstrucción source-visible del aggregate.

El root permanece `Owned` e inicializado antes y después. El field conserva una
única obligación lógica List. SSA/LLVM pueden calcular un descriptor actualizado
y reinsertarlo/publicarlo, pero esa forma física representa continuidad del
mismo slot, no una obligación independiente que deba quedar sin consumir ni un
owner anterior que deba recibir `Drop<List<T>>`.

`push` transfiere exactamente una obligación `value` al nuevo tail. En growth,
los elementos existentes se relocalizan sin Drop de los slots viejos; se libera
sólo el backing reemplazado. El List final contiene exactamente `[0,length)`
inicializado.

### 6.3 Fields e índices

Toda proyección conserva:

- TypeId concreto en cada paso;
- `FieldId` nominal exacto o contrato de índice exacto;
- writability derivada del root/reference;
- owner/storage root para borrow e invalidación;
- orden de evaluación y bounds traps para índices.

Una cadena `Field*` puede seleccionar el descriptor List para una mutación
tipada. Una proyección `Index` selecciona un elemento. Ninguna de las dos
autoriza por sí sola a mover un valor non-Copy fuera de su owner.

La indexación no retorna implícitamente `ref T`. Puede participar como Place en
un borrow explícito/contextual. Dereference nunca crea borrow.

### 6.4 Lifetimes temporales

Un borrow implícito de argumento:

1. comienza después de resolver el Place y sus índices;
2. permanece vivo durante argumentos posteriores y la call;
3. termina, en éxito, después de capturar el resultado y antes de continuar;
4. termina en el exceptional edge antes de limpiar temporales y propagar el
   mismo evento.

`f(&place)` inline tiene la misma región call-scoped. Un local
`ref T r = &place` conserva lifetime léxico; no se acorta por último uso.

### 6.5 Growth, replacement y aliases

Mientras exista un borrow de un elemento, View o storage derivado de un List:

- `push` y `reserve` sobre el mismo root o un alias que pueda alcanzarlo se
  rechazan, incluso si capacity runtime sería suficiente;
- move, Drop o replacement del owner root se rechazan;
- una llamada por acceso writable potencialmente invalidante falla cerrada;
- roots demostrablemente distintos pueden mutarse.

`ref` no prueba inmutabilidad global y `ref mut` no prueba exclusividad. No se
emite `noalias`. La prohibición se basa en invalidación de provenance, no en
una regla global nueva de aliasing.

### 6.6 Return, exceptions, traps y Drop

- Si la evaluación del elemento de `push` lanza antes de la mutación, el List y
  el aggregate conservan su estado anterior; se limpian sólo temporales RHS
  completamente inicializados.
- `ListPush`/`ListReserve` usan traps abortivos para bounds/size/allocation
  según su contrato actual. Esos traps no prometen unwind cleanup.
- Después de un commit normal, un return o una exception posterior limpia el
  aggregate completo con su descriptor actual.
- Struct Drop recorre fields drop-needing en orden inverso. List Drop recorre
  `[0,length)` en orden inverso y libera el backing una vez.
- Un aggregate retornado transfiere su obligación completa al caller. El root
  del callee no se vuelve a destruir.
- El borrow call-scoped termina antes de cualquier Drop de su root en normal o
  unwind.

No se agrega rollback de allocation traps ni Drop source-visible.

## 7. Invariantes por capa

### 7.1 HIR

F1 debe conservar sin cambios sustantivos:

- `HirStmtKind::ListPush/ListReserve` con target `HirPlace` exacto;
- tipo List y element TypeId exactos;
- clasificación de mutación estructural;
- root/provenance, writability y ausencia de borrow incompatible;
- consumo único del valor de `push`.

F2 válido debe contener `CallScopedSharedBorrow` sobre el indexed Place. El
source original no debe contener ese nodo: debe fallar como dereference de
non-reference.

### 7.2 MIR

F1 conserva source == destination en `Rvalue::ListPush/ListReserve`, relocation,
initialization y traps canónicos. El item owning se consume una vez y el root
aggregate conserva un único cleanup.

F2 válido conserva `Borrow` + metadata de call, operación/call exacta y
`EndBorrow` en toda salida no abortiva. No aparece `Load string` como owner ni
`Move` desde el slot.

### 7.3 SSA

SSA debe reconocer tres formas equivalentes de continuidad de descriptor:

1. **root SSA directo**: el resultado del mutador consume/continúa el owner
   source root y se vuelve la nueva definición root;
2. **field SSA promovido**: el mutador produce el descriptor actualizado;
   `InsertField` consume tanto el aggregate anterior como ese descriptor y
   produce la nueva definición aggregate;
3. **place materializado/dereference**: el resultado del mutador tiene un
   único `Store DescriptorCommit` al mismo Place; el Store consume el resultado
   transitorio y el slot permanece initialized.

Para una inserción de field non-Copy por `InsertField`, SSA debe reconstruir
que el `value` proviene inmediatamente de `ListPush`, `ListReserve` o
`MatrixAdd`, que su `source` es exactamente `aggregate + projections`, que no
hay unwind/uso intermedio y que el resultado tiene un único uso. Cualquier otra
escritura owning de field debe seguir usando `ReplaceOwned`/`ReplaceString` o
ser rechazada.

Los consumos del ledger deben contar todos los operands owning relevantes:

- `ListPush`: item owning y, sólo para source root SSA directo, owner source;
- `ListReserve`: owner source root SSA directo;
- `MatrixAdd`: vector y owner source root SSA directo cuando corresponda;
- `InsertField`: aggregate anterior y value owning insertado;
- `Store DescriptorCommit`: resultado transitorio del producer.

No se consume el aggregate base desde el mutador proyectado: lo consume el
`InsertField` posterior. No se consume un memory/dereference root como ValueId:
su slot continúa inicializado.

### 7.4 LLVM

LLVM puede conservar la implementación vigente:

- extraer descriptor;
- llamar helper tipado de push/reserve;
- reinsertar o almacenar el descriptor actualizado;
- ejecutar el Drop final ordinario del root.

No debe emitir Drop del descriptor anterior por el commit, Clone, retain,
deep-copy, bitmap, heap box, `noalias` ni ABI nuevo. O0/O2 deben preservar el
mismo lifecycle lógico.

## 8. Arquitectura de implementación recomendada

### 8.1 Milestone F1 — cambio mínimo

Ámbito productivo esperado: `compiler-next/crates/aether-middle/src/ssa.rs`.
Backend/frontend/MIR sólo requieren tests de regresión salvo que la
implementación revele una inconsistencia no observada.

1. Factorizar una query cerrada de **descriptor ownership continuation** para
   `ListPush`, `ListReserve` y `MatrixAdd`.
2. Completar `owner_consumptions` para source root directo y para ambos
   operands de `InsertField`.
3. Verificar la región producer + owning `InsertField` descrita en §7.3.
4. Permitir un Store drop-needing sobre `MemoryLocal/Value + Field*` sólo si su
   provenance es `DescriptorCommit` y `verify_store_provenance` demuestra el
   producer/source/destination exacto. La etiqueta sola nunca autoriza.
5. Reejecutar el verifier tras optimización y añadir corrupciones que omitan o
   dupliquen cada transición.
6. Mantener el lowering LLVM actual y calificar lifecycle por identidad.

La regla debe derivarse de tipo, Place y clase de operación; no de nombres de
struct, field, package, `Item`, `Result`, Expense Tracker o strings.

### 8.2 Milestone F2 — cambio mínimo

Ámbito productivo esperado: resolución diagnóstica en
`compiler-next/crates/aether-frontend/src/hir.rs`.

Al resolver `Dereference(operand)`:

1. si el operand es un Place, inspeccionar su tipo sin materializar un load
   owning;
2. si no es reference, emitir E0271 directamente, indicando que `*` exige
   `ref T`/`ref mut T` y no crea un borrow;
3. si sí es reference, conservar el camino actual y sus capacidades;
4. no capturar o reetiquetar E0293 de partial moves reales fuera de este caso.

Mensaje recomendado para el reproducer:

```text
cannot dereference `lines[0]`: indexed place has type string, not ref string;
`*` observes through an existing reference and does not create a borrow
```

En un argumento que espera `ref string`, una nota puede sugerir
`trim(lines[0])` o `trim(&lines[0])`. La sugerencia es contextual; la regla de
lenguaje no cambia.

## 9. Alternativas consideradas

### 9.1 Marcar siempre el aggregate como address-taken

Evitaría la forma SSA promovida, pero introduce memoria/pesimismo en todos los
casos y no resuelve por sí solo el rechazo del Store projected. Se descarta.

### 9.2 Usar `ReplaceOwned` para `push(field, value)`

Es semánticamente incorrecto. Un descriptor commit continúa el slot List y
puede conservar o relocalizar su backing. Tratar el descriptor anterior como
un owner independiente a destruir puede liberar elementos/backing que el nuevo
descriptor todavía representa y producir double-drop/use-after-free. Se
descarta.

### 9.3 Mover el field fuera, mutarlo y reinsertarlo

Abriría exactamente el partial-move state que V1 prohíbe, complicaría unwind y
drop flags por field y contradice el aggregate siempre inicializado. Se
descarta.

### 9.4 Convertir mutadores SSA en operaciones void con destination embebido

Una operación monolítica sería válida y más fuerte, pero cambia IR, def-use,
backend, optimizers y dumps de todos los commits. No es necesaria para cerrar
el defecto verificable. Queda como evolución futura, no como F1 mínimo.

### 9.5 Hacer que indexing de non-Copy retorne implícitamente `ref T`

Cambiaría el tipo visible de `collection[i]`, assignment, overload resolution,
generics y semántica Copy. Además las formas de borrow correctas ya existen. Se
descarta.

### 9.6 Interpretar `*lines[0]` como borrow o auto-deref contextual

Contradice la sintaxis CLOSED: `*` dereferencia y `&` presta. También introduciría
auto-deref especial para List/Text. Se descarta.

### 9.7 Clone/Alias implícito del elemento

Crearía un owner y costos observables donde sólo se pidió observación. Está
prohibido por alcance y por el contrato de ownership. Se descarta.

## 10. Riesgos y compatibilidad

| Riesgo | Mitigación requerida |
|---|---|
| descargar dos veces aggregate/source | distinguir root directo, projected y memory; corruption tests por transición |
| no consumir el descriptor actualizado | `InsertField` y Store deben consumir su `value` exactamente una vez |
| usar `InsertField` como bypass de replacement | owning insert sólo con producer tipado/source/path exactos |
| aceptar Store owning por una etiqueta falsificada | provenance se reconstruye; tag no es autoridad |
| Drop del descriptor viejo en commit | inspección LLVM y lifecycle por identidad deben demostrar ausencia |
| perder owner del item de push | ledger separado para value/tail, incluido unwind previo y allocation trap |
| borrow dangling tras growth | conservar invalidación estructural y pruebas de aliases/views |
| cambiar E0293 legítimo | F2 sólo altera dereference de Place cuyo tipo probado no es reference |
| optimización rompe región producer/commit | re-verificación SSA O0/O2 y single-use/adjacency explícitos |

La compatibilidad source es estricta: F1 legaliza programas ya autorizados por
el contrato; F2 no legaliza ninguno y sólo mejora el diagnóstico. No cambian
layout, ABI, mangling, std.Text, List, OAL ni complejidad algorítmica.

## 11. Qualification propuesta — F1

`IR` indica inspección/corrupción HIR/MIR/SSA; `LLVM` indica build/ejecución e
instrumentación nativa. Todos los positivos se ejecutan en O0 y O2.

| Caso | Resultado requerido | IR | LLVM |
|---|---|:---:|:---:|
| reproducer original `Result.items` | check/build/run PASS | sí | sí |
| local root `List<Item{string}>` + push | PASS; source owner continúa | sí | sí |
| `reserve(List<string>)` root y field | PASS; cero element move/drop | sí | sí |
| `List<int>` / T Copy | permanece PASS | sí | sí |
| `List<T owning>` string, Buffer y aggregate nested | PASS; tail owner único | sí | sí |
| nested structs `outer.inner.items` | field path exacto | sí | sí |
| root address-taken + direct field mutation | Store DescriptorCommit válido | sí | sí |
| `ref mut List<T>` y `ref mut Struct` | permanece PASS | sí | sí |
| múltiples pushes sin y con growth | secuencia/length exactos | sí | sí |
| reserve suficiente seguido de push | sin reallocation innecesaria; lifecycle igual | sí | sí |
| return del aggregate mutado | transferencia root única | sí | sí |
| early return antes/después de push | cleanup del estado alcanzado | sí | sí |
| RHS que lanza antes del push | field viejo intacto; temporales limpios | sí | sí |
| throw/catch después del push | new List/element se limpian una vez | sí | sí |
| Drop de aggregate con siblings owning | orden inverso; siblings intactos | sí | sí |
| borrow element/view vivo + push/reserve | rechazo semántico | sí | no |
| alias writable potencialmente invalidante | rechazo fail-closed | sí | no |
| root disjunto mientras otro está prestado | PASS | sí | sí |
| move-out de field/element non-Copy | E0293/diagnóstico vigente | sí | no |
| field assignment owning ordinario por Store/InsertField | rechazo; exige ReplaceOwned | sí | no |
| implicit Clone/Alias probe | cero Clone/retain/owner extra | sí | sí |
| corrupción: omitir source consume root | E0400 | SSA | no |
| corrupción: omitir/duplicar inserted-value consume | E0400 | SSA | no |
| corrupción: wrong FieldId/path/value producer | E0400 | SSA | no |
| corrupción: wrong Store provenance/kind/source/destination | E0400 | SSA | no |
| corrupción: phi/uso intermedio/duplicate commit | E0400 | SSA | no |
| corrupción: missing/duplicate final Drop | detectado | MIR/SSA | sí |
| lifecycle growth | cada element owner y backing se destruye/libera una vez | sí | sí |
| no use-after-free/double-drop | ASan o ledger equivalente más ejecución | no | sí |

Los dumps deben demostrar explícitamente las tres formas de §7.3. La
instrumentación por identidad debe distinguir descriptor/backing y cada element
owner; contadores globales solos no bastan.

## 12. Qualification propuesta — F2

| Caso | Resultado requerido | HIR/MIR/SSA | LLVM O0/O2 |
|---|---|:---:|:---:|
| `trim(*lines[0])` original | rechazo E0271; no E0293 | HIR negativo | no |
| `trim(lines[0])` | PASS; implicit shared borrow | sí | sí |
| `trim(&lines[0])` | PASS; explicit shared borrow | sí | sí |
| owning string local | PASS | sí | sí |
| string field de struct | PASS sin partial move | sí | sí |
| `Array<string>[i]` | PASS por borrow | sí | sí |
| `List<int>[i]` a `ref int` | PASS Copy/no-string | sí | sí |
| iteración `ref string`, luego `trim(*item)` | PASS | sí | sí |
| `ref string r=&lines[0]; trim(*r)` | PASS; dereference real | sí | sí |
| `string x=lines[0]` | sigue rechazado como partial move | HIR negativo | no |
| `*numbers[0]` con elemento Copy no-reference | E0271 | HIR negativo | no |
| borrow indexado seguido de growth en argumento posterior | rechazo por región activa | sí | no |
| borrow termina y luego growth | PASS | sí | sí |
| return/store/capture del ref indexado | rechazo no-escape | sí | no |
| callee/argument posterior lanza | EndBorrow antes de cleanup/unwind | sí | sí |
| dumps válidos | Place Index, Borrow, EndBorrow; sin Move/Clone/Alias | sí | sí |
| LLVM | pointer ABI; sin `noalias`, retain, Clone ni heap auxiliar | no | sí |

## 13. Plan mínimo de implementación

### 13.1 F1

1. Agregar tests que congelen los dos mensajes actuales y las tres formas SSA.
2. Implementar y verificar la relación de continuidad en
   `aether-middle/src/ssa.rs`.
3. Agregar corruption tests de ledger, owning `InsertField` y projected Store.
4. Ejecutar suites focalizadas de ownership, collections, Store provenance,
   replacement y exceptions.
5. Ejecutar los casos nativos O0/O2 y lifecycle/LLVM de la matriz.
6. Sólo después declarar `OWNING-COLLECTION-FIELDS-V1` CLOSED.

### 13.2 F2

1. Congelar AST/source span y el E0293 actual.
2. Introducir el type probe de Place para dereference sin load owning.
3. Exigir E0271 al original y mantener E0293 en partial moves reales.
4. Ejecutar borrow ergonomics, indexing, iteration y Text O0/O2.
5. Cerrar el milestone como corrección diagnóstica, no como feature.

No deben compartir PR/milestone salvo por conveniencia administrativa; sus
gates y commits lógicos deben permanecer separables.

## 14. Bloqueos reales y estado de cierre

No queda una pregunta semántica abierta para ninguno de los dos hallazgos.

Bloqueos para implementación/cierre de qualification:

- F1 necesita cambios SSA y la matriz lifecycle/corruption aún no existe;
- F2 necesita el cambio diagnóstico y sus regresiones;
- la CLI pública no emite raw SSA cuando su verifier falla; la causa se aisló
  mediante la forma Copy análoga, las dos ramas de error, la forma `ref mut`
  positiva y la inspección directa del builder/verifier. Esto no bloquea la
  implementación, pero conviene que el test use `build_ssa` antes de
  `verify_ssa` para fijar la forma exacta.

Se declara **ARCHITECTURE CLOSED** porque:

1. ambas causas están localizadas y son reproducibles en O0/O2;
2. el significado válido/inválido está determinado sin contradecir contratos
   CLOSED;
3. ownership, borrow, alias, lifetime, growth, return, unwind y Drop tienen
   reglas verificables;
4. existe una corrección mínima por defecto y una matriz de qualification
   separada;
5. no se requiere nueva sintaxis, API, borrow checker, partial moves, Clone ni
   rediseño general de SSA.
