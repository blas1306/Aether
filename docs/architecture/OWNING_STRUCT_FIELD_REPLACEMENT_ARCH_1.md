# OWNING-STRUCT-FIELD-REPLACEMENT-ARCH-1 — reemplazo total de slots owning

Estado: **DECISIÓN DE ARQUITECTURA; NO IMPLEMENTADA**, 2026-10-26.

Esta arquitectura define la extensión mínima para reemplazar un field owning
de un struct sin admitir extracción owning, partial moves ni agregados
parcialmente desinicializados. No modifica hoy compiler, runtime, Graphics,
standard library ni tests. En particular, no cierra
GRAPHICS-SVG-BACKEND-V1.

Autoridades y evidencia:

- [AETHER-V1-SEMANTIC-CONTRACT](AETHER_V1_SEMANTIC_CONTRACT.md), especialmente
  referencias, Buffer, ownership estructural, Drop y exceptions;
- [AETHER-COMPILER-ARCHITECTURE](AETHER_COMPILER_ARCHITECTURE.md);
- [GENERAL-V2](GENERAL_V2_STRING_COMPOSITION_REPORT.md), por su operación
  verificada `ReplaceString`;
- [CLASS-BUFFER-FIELDS-ARCH-1](CLASS_BUFFER_FIELDS_ARCH_1.md) y su
  [qualification](CLASS_BUFFER_FIELDS_V1_REPORT.md), por el protocolo vigente
  de field replacement en classes;
- [GRAPHICS-SVG-BACKEND-V1-REPORT](GRAPHICS_SVG_BACKEND_V1_REPORT.md) y
  `reproducers/graphics_svg_owning_buffer_growth.ae`, sólo como reproducer del
  gap, nunca como autoridad para privilegiar Graphics o `Buffer<uint8>`.

## 1. Decisión normativa

El assignment existente expresa la operación. Para un place `p: T` admitido:

```aether
p = rhs;
```

es un **reemplazo total del slot `p`**, no un move parcial desde el agregado
que contiene `p`. El agregado raíz permanece completamente inicializado antes
y después de la operación. El valor anterior no queda disponible al programa.

V1 admite el reemplazo cuando se cumplen todas estas condiciones:

1. `T` es concreto, source-storable, `Copy=false`, `needs_drop=true` y
   `Relocatable=true` según la autoridad central de propiedades;
2. el destination es un slot ya inicializado y escribible;
3. el place es un field directo o anidado, sólo mediante proyecciones `Field`,
   de un struct local owning completamente inicializado; o es ese mismo slot
   alcanzado mediante una raíz `ref mut`;
4. para soportar helpers como el reproducer, también se admite el reemplazo del
   pointee completo `*r` cuando `r: ref mut T` y `T` satisface la regla anterior;
5. no existe un borrow/view incompatible vivo del owner raíz ni de storage que
   pueda aliasar el destination;
6. el RHS produce una obligación owning independiente de tipo exactamente `T`.

`Buffer<E>` no recibe una excepción. Entra porque los Buffer concretos
admitidos son owners relocatable, storable y needs-drop. La misma regla cubre
string, Array/List, Vector/Matrix, handles de class/interface y aggregates
concretos que los contengan, siempre que su expresión RHS ya produzca una
obligación owning válida. Los protocolos particulares de adquisición del RHS
(Move único, ARC Alias, resultado fresco) no cambian.

Una instancia genérica concreta puede entrar después de sustitución. Un tipo
simbólico no entra sólo por `T: Storable`: V1 necesita probar también
`Relocatable`, `needs_drop` y el tipo exacto del drop glue. El sistema vigente
no tiene una capability positiva `Drop`, por lo que esos casos paramétricos se
aplazan en vez de inferir propiedades.

Los assignments Copy, el reemplazo de un local raíz, `ReplaceString` vigente y
`ClassOp::FieldWrite` conservan su semántica. La implementación puede
normalizar `ReplaceString` a la nueva operación general, pero no puede mantener
dos contratos de orden distintos.

## 2. Lo que esta capability no admite

El reemplazo no autoriza ninguna de estas operaciones:

- leer o mover el owner anterior fuera del field;
- destructuring owning parcial;
- dejar el field uninitialized, ni siquiera temporalmente en el IR semántico;
- escribir un field owning por medio de un `Store` ordinario que omita Drop;
- reemplazar un payload de enum sin un protocolo que preserve tag/actividad;
- reemplazar un elemento owning por una proyección `Index`;
- reemplazar storage interior de class por el nuevo camino de structs;
- escribir mediante `ref T`, View o ViewMut sin capacidad apropiada;
- fabricar Clone, deep copy, retain o Alias para un tipo que no lo tenga;
- `swap`, `take`, un sentinel vacío o una operación de desinicialización
  source-visible;
- tipos simbólicos cuyas propiedades requeridas no estén demostradas.

Los fields Copy continúan usando assignment ordinario. Los fields non-Copy que
no necesitan Drop quedan fuera de V1: no motivan el lifecycle de esta decisión
y admitirlos requeriría fijar por separado su semántica de transferencia.

## 3. Orden de evaluación, commit y destrucción

La semántica observable es estrictamente:

```text
1. evaluar completamente rhs;
2. materializar rhs como una obligación owning nueva y protegida;
3. comprobar estáticamente que el destination sigue siendo escribible y no
   tiene borrows incompatibles (no hay check runtime);
4. ejecutar un commit semántico indivisible:
      old := contenido owning anterior de p
      p   := Move(rhs)
5. marcar consumida exactamente una vez la obligación rhs;
6. ejecutar Drop<T>(old) exactamente una vez;
7. continuar con p inicializado por el valor nuevo.
```

En los places V1, calcular la dirección no ejecuta source calls ni índices:
la raíz es un local o un reference local y las proyecciones son sólo `Field`.
Por eso no hay una evaluación lateral del LHS que pueda competir con el RHS.

El paso 4 es atómico en HIR/MIR/SSA: no existe un estado semántico en el que el
field esté uninitialized. LLVM puede implementarlo como load del valor viejo y
store del nuevo, pero entre ambos no puede insertar call, unwind edge, trap,
safepoint ni código source. La publicación del nuevo valor domina el Drop del
anterior.

El drop glue es el mismo `aether_drop_T` usado para un local raíz y es
non-throwing. Si el runtime detecta corrupción y atrapa durante cleanup, aplica
la política abortiva global: no se promete continuar otros cleanups. Esto no
crea un unwind recuperable desde el reemplazo.

### 3.1 Fallo del RHS

Toda call o construcción potentially-throwing pertenece a los pasos 1–2. Su
unwind edge se toma antes del commit. En ese edge:

- `p` conserva el owner anterior, intacto e inicializado;
- los temporales del RHS ya inicializados se limpian con el plan normal;
- no se ejecuta Drop sobre el valor anterior por causa del assignment;
- no existe todavía una obligación nueva publicada en `p`.

Después del commit no hay operación que lance una language exception. Una
excepción posterior encuentra el agregado completo y su cleanup recursivo
destruye el valor nuevo exactamente una vez.

Returns, `break`, `continue`, `throw` y `finally` no pueden intercalarse dentro
del commit. Antes de la operación ven el owner anterior; después ven el nuevo.

## 4. Inicialización y Drop del agregado

La capability no agrega flags por field. Un local struct publicado conserva un
único estado root `Owned` y, cuando corresponde, su drop flag root-level. El
replacement:

- exige que el root y toda la cadena de fields estén inicializados;
- no desarma ni rearma el drop flag del root;
- no cambia la receta recursiva de Drop del tipo;
- no cambia el orden inverso de fields al salir del scope;
- descarga internamente la obligación vieja y transfiere la nueva al mismo
  slot lógico.

Para un struct con varios owners, sólo cambia la obligación del destination.
Los siblings no se leen, mueven, retienen ni destruyen. El Drop final sigue
visitando todos los fields una vez en el orden canónico y encontrará el owner
nuevo en el field reemplazado.

Dos o más replacements consecutivos repiten la misma transacción. Con owners
`v0`, `v1`, `v2`, el primero publica `v1` y destruye `v0`; el segundo publica
`v2` y destruye `v1`; el Drop del agregado destruye `v2`. Ninguno recibe dos
Drops y ninguno queda sin descargar.

## 5. Move, self-assignment y aliasing del RHS

La lectura owning de un field o de un pointee non-Copy continúa fallando. Por
eso expresiones como éstas no se vuelven válidas:

```aether
owner.storage = owner.storage;
other.storage = owner.storage;
*left = *right;
```

Para un owner único como Buffer, el RHS admisible debe ser un local root movido
una vez o un resultado fresco. No puede compartir el backing anterior porque
el lenguaje no puede fabricar esa segunda obligación. Para un handle ARC o
string, un RHS Alias puede designar el mismo objeto sólo si su operación de
adquisición ya creó una obligación independiente; publicar una obligación y
descargar la anterior sigue siendo correcto, incluso para identidad runtime.

No se agrega comparación de direcciones ni guard de self-assignment en LLVM.
Ese guard ocultaría IR corrupto para owners únicos y no demostraría que existe
una obligación RHS separada.

El RHS puede observar el destination mediante Copy reads o borrows acotados a
una call, por ejemplo para calcular el tamaño o copiar elements al owner nuevo.
Esos borrows deben terminar antes del commit. Esto permite el patrón de growth
sin permitir que una referencia al backing viejo sobreviva a su Drop.

## 6. Borrowing y `ref mut`

`ref mut` sigue significando capacidad de escritura, no exclusividad ni
`noalias`. La capability no cambia esa regla y LLVM no recibe un atributo
`noalias` nuevo.

### 6.1 Raíz local conocida

Para `local.field = rhs`, la procedencia vigente se eleva al owner root. V1
rechaza conservadoramente el replacement si cualquier referencia o view
derivada del root sigue viva, incluso si apunta a un sibling que un análisis
futuro pudiera demostrar disjunto. Un borrow creado sólo para evaluar el RHS
termina antes del commit y es compatible.

### 6.2 Raíz alcanzada por referencia

Para `*destination = rhs` o `(*owner).field = rhs`, el verifier no puede asumir
que dos parámetros reference distintos sean disjuntos. V1 usa una relación
`may_alias` conservadora:

- referencias con la misma procedencia conocida se solapan;
- parámetros o referencias de procedencia desconocida cuyo pointee pueda
  contener el tipo reemplazado se consideran potencialmente solapados;
- una proyección field conocida puede refinarse sólo cuando ambas procedencias
  y cadenas completas son conocidas; ante duda se asume overlap.

Un replacement mediante dereference se rechaza mientras esté viva cualquier
referencia/view derivada de un place potencialmente solapado. Esto incluye un
element ref o View al backing de un Buffer alcanzado mediante otro parámetro.
Los call-scoped borrows del RHS finalizan explícitamente antes de
`ReplaceOwned`.

En el caller, crear/pasar el `ref mut` también debe respetar los borrows vivos
del owner local. Como references no pueden retornarse ni almacenarse, no existe
un alias oculto persistente fuera de las procedencias conservadas por la call.

Este chequeo se repite en HIR, MIR y SSA. No alcanza con confiar en que el
frontend emitió una secuencia segura.

## 7. Superficie V1 admitida y aplazada

| Caso | V1 | Razón |
|---|:---:|---|
| `local.buffer = fresh` | sí | field directo, root conocido |
| `local.inner.buffer = fresh` | sí | cadena Field estática |
| `replace(&mut local.buffer)` / `*destination = fresh` | sí | caso motivador; regla may-alias conservadora |
| `replaceOwner(&mut local)` / `(*r).buffer = fresh` | sí | field-only sobre `ref mut` |
| varios replacements del mismo field | sí | slot siempre inicializado |
| aggregate con varios siblings owning | sí | los siblings no cambian |
| tipo owning concreto distinto de Buffer | sí | regla por propiedades, no allowlist |
| field Copy | ya existente | Store ordinario, fuera de ReplaceOwned |
| local root completo | ya existente | protocolo root move/store/drop vigente |
| class field | ya existente | `ClassOp::FieldWrite`, no este place |
| `array[i].owner`, `list[i].owner`, `vector[i]` | no | proyección Index y protocolos de slot distintos |
| payload de enum | no | requiere preservar tag/variant activa |
| class-field storage anidado | no | aliases ARC/interior borrow tienen otra arquitectura |
| symbolic `T: Storable` | no | no prueba Relocatable/Drop concreto |
| move-out, take o destructuring parcial | no | dejaría estado parcial |
| swap explícito | no | no requerido para replacement |

Excluir índices es deliberado. Array/List/Vector/Matrix tienen contratos de
bounds, inicialización de slots, relocalización y borrows de storage propios.
Generalizarlos junto con fields haría V1 menos verificable y no es necesario
para el reproducer.

## 8. Representación HIR

No se agrega sintaxis. Durante resolución, un assignment non-Copy se clasifica
como `HirStmtKind::ReplaceOwned { destination, value }` (nombre normativo; el
spelling Rust final puede variar). No debe quedar como `Assign` genérico con una
exención a E0297, porque se perdería la diferencia entre Store y transacción
owning.

HIR valida independientemente:

- tipo exacto del RHS y destination;
- propiedades concrete/storable/relocatable/non-Copy/needs-drop;
- raíz Local o Dereference mutable y shape de proyecciones sólo Field;
- pertenencia y especialización exacta de cada FieldId;
- root/field completamente inicializado y owner root vivo;
- ausencia de const/shared capability;
- ausencia de borrow/view incompatible, incluida `may_alias` para dereferences;
- que el RHS no sea una lectura owning parcial del destination;
- que la operación no sea init; V1 sólo reemplaza un slot ya inicializado.

E0297 se mantiene para todos los casos fuera del perfil, con un diagnóstico más
específico cuando la causa sea Index, tipo sin propiedades demostradas o
borrow incompatible. E0293 continúa rechazando partial reads/moves.

La verificación de HIR reconstruye estas condiciones desde tipos, locals,
FieldIds y places. HIR corrupto no puede convertir `Assign` en replacement
omitiendo el contrato.

## 9. Lowering MIR

MIR incorpora una operación indivisible:

```text
ReplaceOwned {
    destination: Place,
    value: Operand,
    value_type: TypeId
} -> bool
```

El `bool` es sólo token interno de secuenciación, igual que `ReplaceString`.
Antes de emitirla, lowering materializa por completo el RHS en un owner
temporal. La instrucción no tiene exceptional successor. El unwind de las
operaciones del RHS precede a `ReplaceOwned`.

No se baja a:

```text
old = Move(destination)
Store(destination, Move(value))
Drop(old)
```

porque `Move(destination)` sería precisamente un partial move y expondría en
el CFG un estado desinicializado. La secuencia existente en el lowering
genérico sólo es válida para roots y no debe reutilizarse para projections.

El verifier MIR recalcula, sin confiar en HIR:

1. shape admitido y writability del Place;
2. tipo exacto, propiedades y drop glue disponible;
3. destination inicializado en todos los predecessors;
4. operand RHS materializado, Owned y consumido una vez por la operación;
5. root drop flag sin transición y root todavía Owned;
6. borrow/view liveness y overlap conservador;
7. ausencia de unwind en `ReplaceOwned`;
8. prohibición de `Move`/`Drop` proyectado y de Store owning que evada la op.

En el ledger, `ReplaceOwned` consume la obligación RHS, descarga internamente
la obligación anterior del slot y vuelve a asociar la obligación nueva al
mismo slot. No crea un owner local para el valor viejo.

## 10. SSA y optimización

SSA preserva `SsaOp::ReplaceOwned` con Place, operand y TypeId exactos. No lo
convierte en un Store ordinario antes de verificar ownership. Los operandos que
forman la dirección y el RHS aparecen una sola vez.

El verifier SSA reconstruye independientemente:

- tipo/writability/shape del place desde metadata canónica;
- owner token único del RHS y su consumo por path;
- continuidad de la obligación del slot y del root en joins;
- borrows vivos y `may_alias` en el CFG SSA;
- que no haya `Load`/`Move` owning del field, Store owning alternativo, Drop
  proyectado, segundo consume del RHS ni segundo Drop del valor anterior;
- que la op no tenga unwind y produzca sólo el token `bool` interno.

Los optimizadores tratan `ReplaceOwned` como efecto de memoria que lee y
escribe el destination, consume `value` y ejecuta Drop. No puede eliminarse,
duplicarse, especularse, separarse, adelantarse sobre el último uso/borrow del
valor viejo ni retrasar el Drop a través de una observación posible. Dead-store
elimination sólo puede combinar replacements consecutivos si demuestra y
preserva todos los Drops observables y sus contadores; V1 no necesita esa
optimización.

## 11. LLVM

Después de verificación, el backend emite conceptualmente:

```llvm
%slot = <dirección estática verificada>
%old  = load T, ptr %slot
store T %new, ptr %slot
call void @aether_drop_T(T %old)
```

El load/store usa layout y alignment canónicos del `TypeId` concreto. El drop
glue existente maneja recursivamente structs, enum activo y colecciones. No se
agrega boxing, bitmap, tag, vtable, reflexión, allocation por replacement,
branch por tipo, comparación de pointers ni símbolo Graphics.

El store debe preceder a la call de Drop en O0 y O2. La call no puede llevar un
unwind edge. El backend no decide admisión, borrow safety ni ownership; sólo
baja un contrato ya verificado.

`ClassOp::FieldWrite` conserva su lowering propio porque receiver, FieldId,
estado de constructor y final release de objetos pertenecen al modelo class.
Sí comparte el mismo orden materialize/publish/drop y el mismo drop glue.

## 12. Interacción con exceptions y cleanup

La tabla de estados es:

| Punto | Slot | Obligación vieja | Obligación nueva |
|---|---|---|---|
| antes de evaluar RHS | old inicializado | en slot | inexistente |
| RHS parcial que lanza | old inicializado | en slot | temporales limpiados por unwind |
| RHS completo | old inicializado | en slot | temporal Owned |
| commit semántico | new inicializado | capturada internamente | consumida hacia slot |
| después de Drop old | new inicializado | descargada | en slot |
| unwind posterior | new inicializado | inexistente | cleanup recursivo una vez |

No hay bitmap runtime ni estado `MaybeInitialized` por field. Los drop flags de
roots siguen resolviendo sólo control flow root-level. Los landing pads no
contienen cleanup especial por un replacement a medio commit, porque no existe
un punto de unwind allí.

## 13. Alternativas consideradas

### 13.1 Assignment con `ReplaceOwned` — seleccionada

Es la semántica que el spelling ya sugiere, funciona con locals y `ref mut`, no
expone el valor viejo y puede verificarse como una transacción. Reutiliza
propiedades, Place, drop glue, cleanup y el precedente de ReplaceString/class.

### 13.2 Builtin explícito `replace` o `swap`

Un `replace(place, value)` no agrega información que el assignment no tenga.
Si retornara el valor viejo, abriría partial move y trasladaría su obligación al
caller. `swap` exige dos slots inicializados, cambia orden/observabilidad de
Drop y no resuelve directamente publicar un owner fresco. Ambos se aplazan
hasta existir una necesidad semántica distinta.

### 13.3 Extender `ClassOp::FieldWrite`

Se reutilizan su orden y drop glue, no su representación. Un struct no tiene
receiver ARC, ClassId, FieldId global de objeto, estado de constructor ni final
release. Forzar structs por ClassOp mezclaría dos modelos y debilitaría los
verificadores de acceso class.

### 13.4 Cambiar representación

- convertir el serializer en class o boxear cada field agrega aliasing/heap y
  contradice el ownership local requerido;
- envolver cada field en nullable/Option o usar descriptor vacío introduce
  estado parcial/sentinel y complejiza todo Drop;
- copiar/reconstruir storage evita mover el slot pero agrega allocations y
  trabajo proporcional al contenido;
- reconstruir el struct completo funciona hoy sólo cuando todos los demás
  fields necesarios son Copy o pueden recrearse. Con varios siblings owning no
  puede preservar sus owners sin partial move, Clone o copia de contenido;
- sustituir Buffer por List u otra colección cambia API, layout, allocations y
  no constituye una capability general de fields.

Por eso una operación semántica de slot es menor y más general que alterar la
representación.

## 14. Qualification obligatoria

La implementación futura debe agregar un fixture dedicado, por ejemplo
`compiler-next/crates/aether-driver/tests/owning_struct_field_replacement_arch_1.rs`,
y programas fuente separados para native O0/O2.

### 14.1 Positivos

- Buffer en field directo de struct local;
- el reproducer original mediante `ref mut Buffer<uint8>`;
- reemplazo directo y mediante `ref mut Struct`;
- dos y tres replacements consecutivos;
- proyección anidada sólo Field;
- struct con dos o más siblings owning, verificando que no cambian;
- string, class handle y al menos dos collections/aggregates owning concretos;
- RHS que lee Copy metadata y copia elements desde el owner anterior mediante
  borrow acotado;
- RHS que lanza antes de producir owner y después de crear temporales;
- early return y exception posterior al commit;
- ejecución nativa equivalente en O0 y O2;
- reproducer SVG y gates de Graphics, sin declarar su milestone cerrado hasta
  completar su propia implementation/qualification.

### 14.2 Negativos

- shared `ref`, const storage y destination uninitialized;
- borrow/view vivo del field, de un element/backing y del root;
- alias potencial mediante dos reference parameters;
- lectura/move del field viejo, field-to-field move y self-assignment owning;
- index projection, enum payload y class interior por el camino nuevo;
- tipo non-Relocatable, non-storable, symbolic o metadata desconocida;
- partial move que deje un field sin inicializar;
- use-after-move del local transferido como RHS;
- RHS de tipo distinto y replacement desde receiver no mutable.

### 14.3 Instrumentación lifecycle

No basta con que el proceso termine. La qualification registra, por allocation
identity cuando sea posible:

- allocations/frees de backing y object;
- retain/release para string y class handles;
- entradas al drop glue tipado para aggregate/collection;
- commits `ReplaceOwned` sólo en builds de test;
- double-free, release bajo cero y owner vivo al terminar.

Para `v0 -> v1 -> v2`, los asserts deben identificar Drop(`v0`) tras el primer
publish, Drop(`v1`) tras el segundo y Drop(`v2`) en cleanup final. En RHS throw
deben mostrar Drop de temporales nuevos, cero commit y supervivencia de `v0`.
Los eventos deben coincidir en O0/O2. La inspección LLVM confirma
store-before-drop y ausencia de runtime/type branches nuevos.

### 14.4 Corruption tests

HIR, MIR y SSA requieren tests independientes que alteren:

- TypeId de value/destination o FieldId/projection;
- mutable a shared, initialized a false o Field a Index;
- propiedad Relocatable/needs-drop esperada;
- `ReplaceOwned` por Store, Move proyectado o Drop proyectado;
- consumo RHS omitido/duplicado;
- root drop flag modificado;
- unwind edge agregado a la operación;
- borrow region/alias incompatible omitido;
- Drop viejo omitido, duplicado o movido antes del publish en una forma backend
  instrumentada.

Cada verifier debe rechazar su corrupción aunque la capa anterior no vuelva a
ejecutarse.

### 14.5 Gates de regresión

Deben pasar suites de structs/enums/generics, Buffer, string GENERAL-V2,
Array/List/Vector/Matrix, references/views, iteration, classes/interfaces,
exceptions/finally, optimization y differential; además de `cargo fmt`, clippy
y `git diff --check`. Se comparan explícitamente replacements root, string y
class antes/después para asegurar que no cambiaron sus conteos.

## 15. Criterios de cierre

OWNING-STRUCT-FIELD-REPLACEMENT sólo puede declararse implementado cuando:

1. HIR distingue replacement owning de assignment Copy;
2. MIR y SSA preservan una operación indivisible y la verifican de manera
   independiente;
3. ningún IR válido contiene un estado parcialmente desinicializado;
4. borrow/alias checks cubren locals y dereferences sin asumir `ref mut`
   exclusivo;
5. RHS throw conserva el valor viejo y post-commit cleanup destruye el nuevo;
6. los contadores prueban transferencia y Drop exactamente una vez en O0/O2;
7. las corruptions y todos los gates de regresión están verdes;
8. el reproducer original compila y ejecuta sin cambiar Graphics;
9. contrato global, compiler architecture y reporte de implementación se
   actualizan con evidencia reproducible.

Hasta entonces E0297 continúa siendo el comportamiento correcto y
GRAPHICS-SVG-BACKEND-V1 permanece **BLOCKED**.
