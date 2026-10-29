# Aether — SSA Store Provenance Architecture

Status: **PROPOSED**. Documento de arquitectura; no implementa cambios ni
declara `OWNING-STRUCT-FIELD-REPLACEMENT-V1` CLOSED.

Fecha: 2026-10-27.

## 1. Alcance y decisión

Esta arquitectura distingue las publicaciones ordinarias en memoria de los
commits internos que hoy convergen en `SsaOp::Store`. La decisión es agregar
provenance cerrada a `SsaOp::Store` y verificarla en SSA contra evidencia que
SSA reconstruye por sí mismo.

```text
SsaOp::Store {
    place: SsaPlace,
    value: SsaOperand,
    provenance: StoreProvenance,
}

StoreProvenance =
    Copy
  | Initialize
  | RootTransfer
  | DescriptorCommit(DescriptorCommitKind)

DescriptorCommitKind = ListPush | ListReserve | MatrixAdd
```

Los nombres son normativos sólo a nivel conceptual. El enum es interno al
compilador, no es una capability del lenguaje ni una excepción para packages o
funciones particulares.

La etiqueta no autoriza la operación. Es una afirmación redundante que el
verificador contrasta con tipo, place, estado de inicialización, definición y
usos del `value`, CFG y contrato de la operación productora. Una etiqueta
incorrecta, aunque haya sido emitida por MIR lowering, se rechaza.

No se modifica `ReplaceOwned`. `ReplaceString`, `ReplaceOwned`, `Take`,
`Relocate` y las operaciones tipadas de collections conservan sus contratos.
No cambia borrowing, ninguna API pública ni los protocolos de collections,
File, strings o classes.

## 2. Causa raíz

MIR no posee un `Store` explícito. Cada `MirInstruction` tiene un destination y
un `Rvalue`. Durante construcción SSA, `rename_block` clasifica como
`memory_destination`:

- un local `address_taken`;
- cualquier local con proyección `Index`;
- cualquier `PlaceBase::Dereference`;
- cualquier `PlaceBase::ClassField`.

Para todos ellos genera primero el `SsaOp` correspondiente al `Rvalue` y luego
un `SsaOp::Store { place, value }`. Por lo tanto existe un único productor
sintáctico de `Store`, pero reúne productores semánticos diferentes.

La forma actual sólo conserva destino y valor. Un overwrite owning ilegítimo
sobre `*ref mut T` y la publicación del descriptor devuelto por una transacción
interna pueden tener el mismo tipo, el mismo place writable y un `Store` sin
unwind. Rechazar todo Store drop-needing sobre dereference rompe operaciones
existentes; admitirlo permite disfrazar un replacement que debía permanecer
como `ReplaceOwned`.

La procedencia no puede deducirse de nombres de funciones, módulos, spans o
del hecho de que MIR haya producido la secuencia. Tampoco basta con el tipo:
el descriptor anterior puede seguir siendo la misma obligación lógica durante
un commit, mientras que un valor owning independiente reemplaza una obligación
que debe descargarse.

## 3. Inventario completo de Stores SSA

### 3.1 Productor mecánico

El único punto que construye `SsaOp::Store` es el camino
`memory_destination` de `rename_block` en `aether-middle/src/ssa.rs`. Ningún
otro lowering ni optimizador crea Stores actualmente. El backend LLVM sólo los
consume.

### 3.2 Destinos físicos

| Destino SSA | Por qué queda en memoria | Estado inicial conocido |
|---|---|---|
| `MemoryLocal(root)` | local address-taken o temporal materializado | parámetro: inicializado; local: no inicializado hasta su definición |
| `MemoryLocal + Field*` | aggregate address-taken | depende del root; el field ya existe cuando el root está inicializado |
| `MemoryLocal/Value + Index` | slot de storage dinámico | lo determina el protocolo tipado del container, no un Store owning genérico |
| `Dereference` | storage del caller | inicializado para los places admitidos; no puede usarse como init genérico |
| `ClassField` | storage interior especial de class | el metadata existente exige `initialized`; no admite init genérico |

### 3.3 Categorías semánticas

| Categoría | Productores de valor | Place admitido | Efecto ownership |
|---|---|---|---|
| escritura Copy | cualquier `SsaOp` verificado cuyo resultado es Copy | root, Field, Index, dereference mutable o class storage writable | ninguno; puede sobrescribir |
| inicialización fresca | constructores, calls, `Move` y demás operaciones verificadas | sólo root `MemoryLocal` no parámetro demostrado `Uninitialized` | si no es Copy, publica y consume exactamente un owner nuevo |
| transferencia/reasignación de root | `Move` materializado por el protocolo root existente | sólo root `MemoryLocal` inicializado | captura el owner anterior, publica el nuevo y descarga el anterior una vez |
| commit de descriptor | resultado exacto de `ListPush`, `ListReserve` o `MatrixAdd` | el mismo place memory-resident que figura como `source`, incluido dereference mutable | continúa la obligación del descriptor; no crea un segundo owner ni omite Drop |

Cuando el target de esas operaciones es un local SSA ordinario, el resultado
redefine directamente el local y no existe Store. Un field de aggregate no
materializado usa `InsertField`. `DescriptorCommit` sólo clasifica el Store que
aparece cuando el mismo target está realmente materializado en memoria.

No pertenecen a `Store`:

- replacement de `string`: `ReplaceString`;
- replacement owning de field/dereference: `ReplaceOwned`;
- actualización de length sin reemplazar descriptor: `ListSetLength`;
- transición de slot: `Take` y `Relocate`;
- field de class general: `ClassOp::FieldWrite`;
- aggregate SSA no materializado: `InsertField`;
- elementos que el backend escribe dentro de una operación tipada: son parte
  del contrato de esa operación, no `SsaOp::Store` adicionales.

### 3.4 File no es una excepción

`std.File.readText` llega como una call ordinaria que produce `string`. Si el
destination es address-taken, su resultado se publica mediante Store en el
camino normal posterior a la call. Es `Initialize` cuando el local está
uninitialized, o participa en el protocolo root/string ya existente; no se
califica por `std.File`, `readText` ni por identidad de módulo. La misma regla
se aplica a cualquier call con igual contrato de tipos y ownership.

`writeText` y `writeTextAtomic` no generan un Store de resultado owning. Sus
efectos externos y unwind permanecen en la call.

## 4. Metadatos necesarios

SSA ya conserva casi toda la evidencia:

- tipo de resultado de cada ValueId y tipo reconstruible del place;
- definición única, dominance y usos del ValueId;
- `memory_locals`, parámetros, bindings y drop flags;
- writability y capability del place;
- source y contrato completo de `ListPush`, `ListReserve` y `MatrixAdd`;
- CFG, unwind y contratos de consumo de owners.

Faltan dos piezas explícitas:

1. la categoría que el Store afirma implementar (`StoreProvenance`);
2. un ledger SSA de estado del slot que derive `Uninitialized`, `Initialized`
   o `Unavailable` en cada punto del CFG.

El ledger es análisis verificador, no metadata confiada desde MIR. Para roots
`MemoryLocal`, parte de parámetros inicializados y locales no parámetros no
inicializados, aplica definiciones, Moves, Drops, Stores, drop flags y phis, y
exige igualdad de estado en joins salvo la bifurcación canónica gobernada por
un drop flag. Dereferences y ClassField comienzan como `InitializedExternal`.
Los Index se delegan exclusivamente a contratos de slot tipados; un Store
owning genérico nunca cambia su estado.

No se necesita un nombre de función productora, un module id, un span, un bit
`trusted` ni un token generado por MIR.

## 5. Alternativas consideradas

### 5.1 Rechazar todo Store owning sobre dereference

Es simple y cierra el bypass, pero también rechaza los commits legítimos de
descriptors cuando el target de `ListPush`, `ListReserve` o `MatrixAdd` se
alcanza por referencia. No es compatible.

### 5.2 Allowlist por función, módulo o spelling del productor

Viola el requisito de no depender de nombres y no prueba nada sobre el CFG, el
place ni el consumo. También sería frágil ante monomorfización y refactors. Se
descarta.

### 5.3 Inferir todo sin cambiar la representación

La definición del ValueId permite reconocer muchos pares productor/Store, y el
ledger puede reconocer init y root transfer. Sin embargo, la representación
seguiría sin declarar qué contrato debe sobrevivir a transforms. Un optimizer
podría insertar una copia, phi o reordenamiento y convertir una inferencia
accidental en autoridad. También faltaría una dimensión directa de corrupción:
dos Stores de igual forma no expresarían contratos diferentes.

Esta alternativa es útil como mecanismo de verificación, pero insuficiente
como contrato estable de IR.

### 5.4 Operaciones completamente tipadas con destination

`ListPush`, `ListReserve` y `MatrixAdd` podrían incorporar el destination y
realizar internamente el commit, eliminando su Store posterior. Es la
representación más fuerte: la transacción sería una única operación SSA.

Su costo es mayor: cambia forma, resultados y def-use de tres protocolos,
backend, dumps, tests y optimizaciones; además no resuelve por sí sola las
inicializaciones y transferencias de roots address-taken. Es una evolución
válida si esas operaciones se rediseñan, pero no el cambio mínimo para este
bloqueo.

### 5.5 Provenance explícita validada independientemente — seleccionada

Añade un enum cerrado al Store sin cambiar protocolos públicos ni el lowering
LLVM. La etiqueta hace estable la intención, y la evidencia existente más el
ledger impide confiar ciegamente en ella. Es localizada y permite corruption
tests directos para etiqueta y testigo.

## 6. Invariantes verificables en SSA

Se verifican después de estructura, definiciones, dominance y tipos, pero antes
de entregar `VerifiedSsa`.

### 6.1 Invariantes comunes

Todo Store debe:

1. tener place y value del mismo tipo;
2. tener destination writable y capability exacta;
3. carecer de unwind;
4. usar un value cuya definición domina el Store;
5. respetar const, views read-only y borrow regions existentes;
6. satisfacer exactamente una variante de provenance;
7. concordar con el ledger del slot antes y después;
8. no duplicar consumo ni dejar un owner vivo sin descarga.

### 6.2 `Copy`

- `types.is_copy(place_type)` debe ser verdadero;
- no autoriza un tipo sólo `guarantees_copy` si todavía tiene obligación de
  Drop;
- admite root, Field, Index y dereference writable;
- el producer puede ser cualquier operación cuyo contrato individual sea
  válido: la seguridad proviene del tipo Copy, no de su identidad.

### 6.3 `Initialize`

- destination exactamente `MemoryLocal(root)` sin proyecciones;
- local no parámetro y estado previo `Uninitialized` en todos los predecessors;
- estado posterior `Initialized`;
- si el tipo no es Copy, value definido una vez y consumido exactamente por
  este Store;
- no admite Dereference, ClassField, Field ni Index;
- una segunda inicialización, un join ambiguo o una etiqueta `Initialize`
  sobre storage externo se rechaza.

Así se admiten resultados de calls/File y constructores sin una excepción por
origen.

### 6.4 `RootTransfer`

- destination exactamente un root `MemoryLocal`, nunca dereference,
  ClassField, Field o Index;
- el estado previo debe ser `Initialized`;
- el nuevo value owning debe consumirse una vez;
- debe existir una captura `Move` única del mismo root que domina el Store y
  que no escapa;
- el owner capturado debe tener un único `Drop` dominado por el Store en todos
  los exits normales de la transacción, o el protocolo de drop flag equivalente
  ya verificado;
- entre captura y publicación no puede existir unwind ni observación del slot
  desinicializado;
- la publicación restablece `Initialized`.

Este contrato preserva la reasignación root existente, pero no puede usarse
para imitar un field/dereference replacement.

### 6.5 `DescriptorCommit(kind)`

El value debe ser un ValueId definido por la operación exacta indicada:

| kind | definición requerida | relaciones adicionales |
|---|---|---|
| `ListPush` | `SsaOp::ListPush` | `producer.source == store.place`; mutation, init, relocation y traps canónicos; value push consumido según tipo |
| `ListReserve` | `SsaOp::ListReserve` | `producer.source == store.place`; requested capacity, relocation, mutation y traps canónicos |
| `MatrixAdd` | `SsaOp::MatrixAdd` | `producer.source == store.place`; element/orientation, mutation, invalidation, relocation y traps canónicos |

Además:

- source y destination se comparan estructuralmente, incluidos base,
  projections, indices y capabilities; no sólo por tipo;
- el resultado del producer tiene un único uso de commit y no puede pasar por
  phi, `Use`, aggregate, call o return;
- producer y Store forman una región indivisible sin unwind ni operación que
  observe o invalide el mismo place entre ambos;
- el place estaba `Initialized` y sigue `Initialized`;
- para Dereference debe ser mutable y se repite el chequeo de aliases/borrows
  aplicable al producer;
- cambiar kind, producer, source, place, value o contrato de relocation hace
  fallar la verificación.

No existe `DescriptorCommit(Other)`. Agregar otra operación interna en el
futuro requiere ampliar el enum y escribir su verificación estructural; no se
obtiene autoridad por retornar un descriptor.

### 6.6 Regla decisiva para dereferences

Un Store sobre `SsaPlaceBase::Dereference` sólo puede ser:

- `Copy`, con tipo Copy; o
- `DescriptorCommit` con testigo tipado exacto.

`Initialize`, `RootTransfer` y cualquier Store drop-needing sin ese testigo se
rechazan. El único replacement owning ordinario admitido continúa siendo
`ReplaceOwned` (o `ReplaceString` para string).

## 7. Reparto de autoridad MIR/SSA

### 7.1 MIR

MIR conserva sus operaciones actuales y no recibe una etiqueta `trusted`.
Debe verificar:

- que un assignment owning de Field/dereference se represente como
  `ReplaceOwned`/`ReplaceString`;
- que `Move` owning ordinario sólo escriba un root local;
- que ListPush/ListReserve/MatrixAdd usen destination y source idénticos y sus
  contratos tipados completos;
- inicialización, drop flags, consumos y unwind a nivel MIR.

El builder SSA calcula `StoreProvenance` desde el Rvalue, el destination y el
estado local ya verificado; no copia un tag MIR.

### 7.2 SSA

SSA no acepta la conclusión MIR. Reconstruye:

- tipos y writability desde su arena y places;
- estado del slot desde su CFG, memory locals y drop flags;
- categoría desde el tipo, shape y operación que define el value;
- igualdad source/destination y contrato del producer;
- uniqueness de definición, uso y consumo;
- borrow/alias protection desde metadata SSA.

Finalmente exige que la categoría reconstruida sea igual a
`StoreProvenance`. Tanto una operación inválida con etiqueta correcta como una
operación válida con etiqueta corrupta fallan.

## 8. Cambios requeridos por capa

### 8.1 MIR

- ningún nuevo Rvalue público ni cambio a `ReplaceOwned`;
- factorizar una clasificación interna usada sólo por lowering SSA, sin
  convertirla en autoridad del verifier;
- completar tests MIR que aseguren que Move owning a dereference/Field/Index no
  llega a SSA y que los tres commits mantienen source == destination;
- no cambiar protocols, borrowing ni surface syntax.

### 8.2 SSA

- agregar `StoreProvenance` y `DescriptorCommitKind` cerrados;
- emitir la provenance en `rename_block`;
- construir índice ValueId → definición para validar producers (ya existe en
  el verifier; debe exponerse al chequeo de Stores);
- agregar el ledger de slots roots y el verificador de pares
  producer/descriptor commit;
- incorporar provenance en dumps, equality, operand walking y corruption
  tests;
- hacer que toda transformación que preserve o cree Store mantenga/recalcule
  provenance y volver a ejecutar `verify_ssa`.

### 8.3 LLVM

No cambia el ABI ni la secuencia física. Tras `VerifiedSsa`, las cuatro
variantes bajan al mismo `store` LLVM cuando corresponde. Provenance se borra
en lowering.

El backend conserva las operaciones tipadas antes del Store de commit. Puede
emitir comentarios diferenciados para pruebas, pero esos comentarios no son
autoridad. `ReplaceOwned` continúa bajando como load old, publish new y typed
Drop old; no pasa por el camino de Store genérico.

Se recomienda una assertion interna de exhaustividad sobre provenance y tests
LLVM que comprueben que:

- no se agrega Drop al descriptor continuado de un commit;
- no se elimina el Drop de `RootTransfer`/`ReplaceOwned`;
- publish precede Drop donde el protocolo lo requiere;
- el metadata no produce attrs `noalias` ni cambia ordering visible.

## 9. Optimización

`StoreProvenance` forma parte de la semántica SSA hasta codegen:

- `Copy`: efecto write ordinario; DSE sólo con las reglas de alias existentes;
- `Initialize`: publicación de una definición; no puede moverse antes del
  producer ni duplicar un owner;
- `RootTransfer`: barrera de transacción ownership; no se separan capture,
  publish y Drop;
- `DescriptorCommit`: inseparable del producer tipado y con efecto read/write
  sobre el mismo place, además de sus consumos, allocation/traps e
  invalidación.

La optimización OOP actual no gana permiso para reordenar Stores. Si una
optimización futura introduce phis/copies entre producer y commit, debe o bien
preservar un testigo explícito más rico, o materializar de nuevo la forma
canónica y re-verificar. V1 selecciona la forma canónica directa.

No se permite combinar dos descriptor commits, convertir `ReplaceOwned` en
Store, ni eliminar un Store owning por parecer muerto: Drops, traps,
allocations y contadores pueden ser observables.

## 10. Matriz de qualification

### 10.1 Positiva

| Caso | Resultado requerido | Evidencia a comprobar |
|---|---|---|
| asignación `int` a local address-taken | PASS | `Copy`, tipo Copy |
| escritura Copy por `ref mut int` | PASS | `Copy`, dereference mutable |
| escritura Copy a Field/Index writable | PASS | tipo/place exactos |
| init de Buffer/List/string en local address-taken | PASS | `Initialize`, slot Uninitialized, consume único |
| `std.File.readText` a local address-taken | PASS | call ordinaria + `Initialize`, sin chequeo de nombre |
| reasignación owning de root address-taken | PASS | `RootTransfer`, capture/publish/Drop completos |
| ListPush sobre target memory-resident o `ref mut List<T>` | PASS | `DescriptorCommit(ListPush)` y source == place |
| ListReserve sobre target memory-resident o dereference | PASS | `DescriptorCommit(ListReserve)` |
| MatrixAdd sobre target memory-resident o dereference | PASS | `DescriptorCommit(MatrixAdd)` |
| ListPush/ListReserve/MatrixAdd sobre local SSA ordinario | PASS | redefinición directa, sin Store ni provenance |
| ReplaceOwned local Field y por dereference | PASS | permanece `SsaOp::ReplaceOwned`, no Store |
| ReplaceString por dereference/field | PASS | permanece `SsaOp::ReplaceString` |
| O0 y O2 | PASS | verifier ejecutado antes y después de transforms |

### 10.2 Negativa

| Caso | Resultado requerido |
|---|---|
| Store owning ordinario sobre dereference | REJECT |
| Store owning ordinario sobre Field o ClassField inicializado | REJECT |
| `Initialize` sobre parámetro, dereference, field, index o slot ya inicializado | REJECT |
| `RootTransfer` sobre algo que no sea root MemoryLocal | REJECT |
| Store non-Copy a Index fuera de Take/Relocate/protocolo tipado | REJECT |
| descriptor result almacenado en place distinto del source | REJECT |
| descriptor result retornado, pasado a call, duplicado o unido por phi antes del commit | REJECT |
| Store a través de shared ref/View read-only | REJECT |
| producer/Store separados por unwind u observación del mismo place | REJECT |
| excepción por `std.File`, nombre de función o package | ABSENT |

### 10.3 Corrupción

| Mutación del IR | Resultado requerido |
|---|---|
| `ReplaceOwned -> Store(Copy)` | REJECT: tipo no Copy |
| `ReplaceOwned -> Store(Initialize)` | REJECT: destination externo/inicializado |
| `ReplaceOwned -> Store(RootTransfer)` | REJECT: no root MemoryLocal ni capture/drop |
| `ReplaceOwned -> Store(DescriptorCommit(ListPush))` | REJECT: value no definido por ListPush |
| cambiar sólo provenance de un Store válido | REJECT: categoría reconstruida no coincide |
| cambiar kind ListPush por ListReserve/MatrixAdd | REJECT |
| cambiar producer, value o ValueId del commit | REJECT |
| cambiar source del producer o place del Store | REJECT |
| insertar `Use`, phi, call o segundo Store del result de descriptor | REJECT |
| duplicar/eliminar commit Store | REJECT |
| eliminar capture o Drop de RootTransfer | REJECT |
| mover Drop antes de publish | REJECT |
| marcar parámetro/dereference como Initialize | REJECT |
| cambiar mutable dereference a shared | REJECT |
| agregar unwind al Store o entre producer y commit | REJECT |
| corromper relocation/init/mutation/invalidation/traps del producer | REJECT por contrato tipado existente |
| optimizer pierde o inventa provenance | REJECT en re-verificación O2 |

## 11. Riesgos de compatibilidad

1. **Falsos negativos por inventario incompleto.** Si existe otro Rvalue que
   retorna un descriptor para commit, el enum cerrado lo rechazará. La respuesta
   correcta es documentar y verificar una nueva variante, no usar `Other`.
2. **Ledger y excepciones.** Calls que inicializan memory locals pueden tener
   unwind. El Store sólo existe en el camino normal; el ledger debe propagar
   Uninitialized al edge excepcional y respetar drop flags.
3. **Joins condicionales.** La implementación debe reconocer únicamente joins
   canónicos gobernados por drop flags. Ante estados incompatibles, falla
   cerrado.
4. **Dumps y tests estructurales.** Agregar provenance cambia dumps Debug y
   tests que comparan texto, aunque no cambia programas Aether ni ABI.
5. **Optimización futura.** Una transformación que rompa el par directo
   producer/commit deberá preservar un witness más rico. No debe relajar el
   verifier para acomodarla.
6. **Class storage.** `ClassField` ya declara `initialized`; sólo Copy o un
   commit tipado exacto puede usar Store. Las escrituras generales siguen en
   `ClassOp::FieldWrite` y no se amplía la superficie de classes.
7. **Tipos con Drop parcial.** La clasificación usa `is_copy`, `needs_drop` y
   el contrato ownership, no tamaño ni layout LLVM. Tipos ambiguos o metadata
   incompleta se rechazan.
8. **No soluciona borrow liveness general.** Esta arquitectura cierra la
   procedencia de Stores, pero no agrega regiones no léxicas ni resuelve el
   bloqueo independiente de liveness general registrado en el reporte V1.

## 12. Criterio de implementación y estado de ReplaceOwned

El cambio mínimo necesario es el enum de provenance en SSA más verificación
independiente por ledger y testigo de producer. No se justifica modificar
`ReplaceOwned`, los protocolos tipados ni LLVM.

La arquitectura se considera implementada sólo cuando pasan las matrices
positiva, negativa y de corrupción en MIR, SSA, O0 y O2, y cuando los verticals
existentes de collections y File permanecen verdes. Hasta entonces —y aun
después, mientras sigan abiertos los otros bloqueos del reporte de
qualification— `OWNING-STRUCT-FIELD-REPLACEMENT-V1` permanece **PARTIAL** y no
debe declararse CLOSED.
