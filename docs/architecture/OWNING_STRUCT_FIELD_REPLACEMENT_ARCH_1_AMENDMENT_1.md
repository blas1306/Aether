# OWNING-STRUCT-FIELD-REPLACEMENT-ARCH-1 — Amendment 1

Estado: **ENMIENDA NORMATIVA PROPUESTA PARA QUALIFICATION; MILESTONE NO
CERRADO**, 2026-10-28.

Esta enmienda modifica de forma acotada
[OWNING-STRUCT-FIELD-REPLACEMENT-ARCH-1](OWNING_STRUCT_FIELD_REPLACEMENT_ARCH_1.md).
Todo requisito original no sustituido aquí permanece vigente. La solución
**CLOSED** de
[SSA-STORE-PROVENANCE-V1](SSA_STORE_PROVENANCE_V1_REPORT.md) forma parte del
baseline y no es un trabajo pendiente de este milestone.

Autoridades adicionales:

- [AETHER-V1-SEMANTIC-CONTRACT](AETHER_V1_SEMANTIC_CONTRACT.md), en especial
  referencias no owning, ownership estructural, `Storable`, `Relocatable`,
  Drop y `OWNING-STRUCT-FIELD-REPLACEMENT-V1`;
- [SSA-STORE-PROVENANCE-ARCH-1](SSA_STORE_PROVENANCE_ARCH_1.md) y su reporte
  CLOSED;
- [OWNING-STRUCT-FIELD-REPLACEMENT-V1-REPORT](OWNING_STRUCT_FIELD_REPLACEMENT_V1_REPORT.md),
  como evidencia de implementación, no como autoridad para relajar este
  contrato.

## 1. Cambios normativos precisos

| Requisito original | Sustitución de esta enmienda |
|---|---|
| §1, párrafo que incluía handles de class/interface en la regla general | V1 sólo cubre tipos concretos que ya sean legalmente almacenables en el place conforme al contrato global. E0274 sigue prohibiendo handles de class/interface dentro de structs; ReplaceOwned no amplía esa superficie. |
| §6.1–6.2, §8, §9, §10 y §15.4, reconstrucción de borrow/view liveness | Se exige demostrar ausencia de borrow/view incompatible con las regiones léxicas, regiones explícitamente delimitadas y análisis conservador descritos en §2. No se exige inferencia general de non-lexical lifetimes ni reconstruir una muerte arbitraria que el lenguaje no utiliza para admitir el programa. |
| §14.1, positivo de class handle | Se elimina de la matriz positiva. Se reemplaza por un negativo E0274 que prueba que esta capability no altera storage global. Interface handles reciben el mismo tratamiento. |
| §14.1, “string” entre los owners generales | `string` se conserva como regresión del protocolo existente `ReplaceString`; no cuenta como cobertura de `ReplaceOwned`. |
| §14.3, toda la instrumentación enumerada como igualmente obligatoria | Se sustituye por la separación de instrumentación indispensable y observabilidad adicional de §5. |
| §14.4, corrupción | Se sustituye por la matriz por capa de §6. La corrupción SSA Store ya cubierta por el baseline CLOSED no se reabre, aunque su suite debe seguir pasando. |
| §14.5 y §15.7, “todos los gates verdes” sin clasificación | Se sustituyen por la taxonomía y regla de cierre de §7. Un gate que falla nunca se registra como PASS; un fallo preexistente o ambiental tampoco se presenta como regresión del milestone. |
| §15.6, contadores como prueba suficiente de Drop | Los contadores agregados siguen siendo necesarios pero no suficientes. La secuencia multi-replacement requiere evidencia por identidad según §5. |
| §15.9, actualización de autoridades | Para CLOSED deben actualizarse el contrato global y el reporte final con esta enmienda y evidencia reproducible. No es necesario reescribir la decisión histórica original. |

## 2. Borrow/view liveness definitivo para V1

### 2.1 Modelo suficiente

V1 es seguro sin lifetime inference general si HIR, MIR y SSA verifican
independientemente estas reglas:

1. Un borrow/view local ordinario conserva su owner root o storage provenance
   durante toda la región léxica que el modelo vigente le asigna. Mientras esa
   región esté viva se rechaza el replacement del root, de cualquier field
   protegido o de storage que pueda invalidarlo.
2. Una región que el IR ya representa explícitamente —incluidos borrows de
   call y formatting, y los scopes cerrados de iteration— puede terminar en su
   `End` verificado. Después del cierre, ese borrow concreto deja de proteger
   el owner. El verifier debe comprobar Begin/uso/End, dominance, correspondencia
   y que no haya uso posterior.
3. Un borrow temporal creado exclusivamente durante evaluación del RHS puede
   ser admitido sólo si su cierre léxico o explícito domina `ReplaceOwned`. El
   RHS completo y todos sus usos del owner viejo preceden al commit.
4. Para una raíz local conocida, owner provenance prevalece sobre una mera
   comparación de tipos. Un borrow de otro owner local demostrado distinto no
   bloquea; cualquier borrow derivado del mismo root sí bloquea. V1 puede
   rechazar también siblings disjuntos si no demuestra la separación completa.
5. Para replacement por dereference, `ref mut` no prueba exclusividad. Toda
   referencia/view parámetro o procedencia no demostrada que pueda alcanzar el
   owner, un member suyo o storage expuesto por él se considera `may_alias`.
   La relación se calcula con `may_borrow_storage_of`, incluyendo members de
   aggregates, payload nullable y elementos de Buffer, Array, List, Vector y
   Matrix. Topología desconocida, recursiva mal formada o incompatibilidad no
   demostrable falla cerrada.
6. HIR, MIR y SSA reconstruyen la decisión desde sus tablas canónicas de
   locals/parámetros, tipos, places, regiones y CFG. Copiar una conclusión de
   la capa anterior no constituye verificación independiente.

No se admite “último uso” implícito para acortar una referencia local. Si el
frontend conserva esa referencia hasta fin de scope, el replacement se
rechaza aunque un análisis NLL futuro pudiera aceptarlo. Esa pérdida de
expresividad es parte del perfil V1, no un defecto de seguridad.

### 2.2 Patrones admitidos

- replacement de un field de root local sin borrow derivado vivo;
- replacement cuando sólo existe un borrow de un owner local distinto y la
  procedencia distinta está demostrada;
- observación Copy o borrow del owner viejo durante el RHS, si la región
  léxica termina allí o su End explícito está verificado antes del commit;
- call-scoped y format-scoped borrows cerrados antes de `ReplaceOwned`;
- replacement a través de `ref mut` cuando no hay otro parámetro ni alias vivo
  cuyo tipo/topología pueda designar el slot o su backing.

### 2.3 Rechazos conservadores obligatorios

- referencia/view local derivada del destination root y todavía en scope;
- referencia a element/backing o view de Buffer, Array, List, Vector o Matrix
  invalidable por el replacement;
- borrow de un sibling cuando el análisis no demuestra disjointness completa;
- dos parámetros donde uno permite replacement y el otro puede alcanzar por
  tipo el owner, un member o su storage, aunque un caller observado use roots
  distintos;
- procedencia perdida, parámetro indirecto, aggregate topology desconocida o
  join de CFG con estados de región incompatibles;
- reborrow/copia de referencia cuyo origen no pueda reconstruirse en la capa
  que verifica;
- pretendido fin por último uso cuando no existe End explícito ni fin léxico;
- cualquier uso de la referencia/view después de su End explícito.

Una ruta concreta que permita ejecutar `ReplaceOwned`, destruir el backing
viejo y luego usar una referencia/view derivada sigue siendo un **bloqueo de
seguridad**. Debe corregirse o rechazarse antes de CLOSED. La ausencia de NLL
general, por sí sola, deja de ser un bloqueo si todos los programas admitidos
cumplen las reglas anteriores.

## 3. Matriz de tipos definitiva

La admisión se decide por el `TypeId` concreto ya sustituido y por todas estas
propiedades independientes: storage source válido, `Storable=true`,
`Relocatable=true`, `Copy=false`, `needs_drop=true`, layout y drop glue
concretos. `T: Storable` no implica ninguna de las demás.

| Familia | Estado V1 | Qualification mínima |
|---|---|---|
| `Buffer<E>` admitido globalmente | admitida | directo, nested y por `ref mut`; lifecycle por identidad |
| `Array<E>`, `List<E>`, `Vector<E,O>`, `Matrix<E>` concretos admitidos globalmente | admitida | al menos un positivo por familia y negativos de element/view alias donde exista esa superficie |
| struct concreto con owner(s), incluido aggregate anidado | admitida si deriva todas las propiedades | replacement de aggregate y preservación de al menos dos siblings owning |
| instancia genérica concreta sustituida | admitida si el `TypeId` concreto satisface todo | un positivo y corrupción de metadata/property |
| `string` | protocolo existente | regresión `ReplaceString` publish-before-release; no cuenta como `ReplaceOwned` |
| handle class/interface dentro de struct | prohibida por E0274 | negativos que demuestren que ReplaceOwned no ensancha storage |
| tipo simbólico sólo `T: Storable` | no admitido | negativo paramétrico; no se inventa capability `Drop` |
| Copy o non-Copy/no-drop | fuera de ReplaceOwned | conserva el protocolo global correspondiente |
| referencia, view, Index, enum payload o class interior | fuera de este place profile | negativos de superficie y capability |

Esta matriz no crea Clone, Alias, Drop genérico, storage nuevo ni una excepción
nominal para Graphics.

## 4. Garantías normativas finales de ownership

Para cada `ReplaceOwned` válido se mantienen sin modificación:

1. el RHS se evalúa y materializa por completo antes del commit;
2. un unwind previo al commit preserva intacto el owner anterior y limpia sólo
   temporales efectivamente inicializados del RHS;
3. el commit captura internamente old, publica new y sólo entonces ejecuta el
   Drop tipado de old;
4. el RHS aporta una obligación owning independiente y se consume exactamente
   una vez;
5. old recibe exactamente un Drop y new queda como única obligación del slot;
6. root permanece initialized/Owned, su drop flag no transiciona y los siblings
   no se mueven, leen, retienen ni destruyen;
7. HIR, MIR y SSA preservan `ReplaceOwned` y verifican independientemente tipo,
   place, writability, initialization, ownership, borrow/alias y ausencia de
   unwind;
8. ningún Store owning ordinario, projected Move/Drop o provenance label puede
   suplantar la operación. Se conserva íntegro el baseline CLOSED de SSA Store
   provenance;
9. O0 y O2 preservan operación, consumos, efectos y orden publish-before-drop.

## 5. Evidencia lifecycle requerida

### 5.1 Indispensable

La qualification debe observar por identidad lógica, no sólo por totales:

- para `v0 -> v1 -> v2`, publicación de `v1` antes del único Drop de `v0`,
  publicación de `v2` antes del único Drop de `v1` y único Drop final de `v2`;
- identidad del owner viejo y nuevo en cada commit, sin reutilizar el mismo
  token como dos obligaciones;
- supervivencia e identidad inalterada de siblings owning;
- en RHS throw, cero commit/Drop de old por el assignment, supervivencia de
  old y cleanup único de cada temporal RHS inicializado;
- igualdad de esos eventos en O0 y O2.

Puede implementarse con hooks sólo de test, un ledger del harness o identidad
de allocations/owners. No se exige instrumentación productiva ni ABI público.
Los contadores globales de alloc/free y la inspección estática LLVM son
evidencia complementaria, no sustitutos de esta prueba.

### 5.2 Observabilidad adicional, no requisito de cierre

No son obligatorios para V1: un evento para cada entrada de todo drop glue del
lenguaje, retain/release por identidad para handles excluidos por E0274,
telemetría productiva, nombres source en runtime, un contador público de
commits o instrumentar tipos/protocolos no ejercitados por ReplaceOwned.

## 6. Qualification mínima y suficiente para CLOSED

### 6.1 Funcional y semántica

- Buffer directo/nested, `ref mut Buffer`, `ref mut Struct` y proyección Field
  anidada;
- dos o más replacements consecutivos y aggregate con al menos dos siblings;
- cada familia concreta de la matriz de §3, aggregate owning y generic instance
  concreta;
- RHS con borrow cerrado antes del commit, RHS throw, throw posterior, early
  return y cleanup normal/excepcional;
- positivos y rechazos de §2.2–2.3, incluidas cadenas de reborrow/copia,
  branches/joins y alias de element/view para cada storage family aplicable;
- negativos de shared ref, const, uninitialized, Index, enum payload, class
  interior, tipo simbólico, propiedad desconocida, partial move,
  self/field-to-field owning assignment y use-after-move;
- lifecycle por identidad de §5.1 y equivalencia nativa O0/O2.

### 6.2 Corrupción independiente

- HIR: kind Assign/ReplaceOwned, TypeId, FieldId/cadena de proyección,
  writability, initialized, propiedad requerida y alias/región;
- MIR: TypeId/RHS, mutable/shared, Index, owner/root state, root drop flag,
  consumo RHS omitido o duplicado, unwind y sustitución por Move/Store/Drop;
- SSA: TypeId/place/value, owner token/consumo, borrow/end metadata, unwind y
  sustitución por Store/Move/Drop;
- backend qualification: omitir/duplicar old Drop y reordenarlo antes de
  publish debe ser detectado por el harness por identidad; la inspección LLVM
  debe confirmar store-before-drop en O0/O2.

Las corruption suites CLOSED de SSA Store provenance se ejecutan como
regresión. No se duplican como requisito nuevo salvo que ReplaceOwned cambie su
frontera con Store.

## 7. Gates y regla de estado

Cada gate se registra como `PASS`, `FAIL`, `NOT RUN` o `BLOCKED`, con comando,
entorno y evidencia. Nunca se escribe PASS si el comando falla.

| Clase | Regla para cierre |
|---|---|
| requisitos semánticos | todos demostrados; cualquier bypass de safety es bloqueo |
| qualification funcional | toda §6.1 PASS en O0/O2 |
| corrupción de IR/backend | toda §6.2 PASS |
| regresiones introducidas | suites afectadas, vertical, workspace y diff checks PASS; un fallo causado por el cambio bloquea |
| problema preexistente de tooling | resultado `FAIL`, causa `PREEXISTING`, con evidencia de no atribución; no se llama PASS ni se arregla código ajeno para este cierre |
| gate ambiental | se registra BLOCKED o NOT RUN y causa exacta; no prueba corrección. Un gate esencial debe repetirse en entorno apto antes de CLOSED |

Un gate global de tooling preexistente no es por sí solo una propiedad
semántica de ReplaceOwned. Puede no bloquear el milestone únicamente si se
demuestra que precede al cambio, no toca archivos del milestone y el gate
equivalente sobre el alcance modificado pasa. Esa excepción debe quedar
explícita; no convierte el gate global en verde.

No se modifican Graphics, SVG, Plots, ejemplos personales ni código no
relacionado para fabricar resultados verdes.

## 8. Bloqueos normativos restantes

Tras esta enmienda, los bloqueos reales para CLOSED son:

1. completar la evidencia de liveness/alias de §6.1, especialmente reborrows,
   copias de referencia y joins, y corregir cualquier bypass concreto;
2. completar las corruptions FieldId, root drop flag, duplicate consume y
   metadata de borrow/End descritas en §6.2;
3. aportar lifecycle per-identity indispensable y detección de
   omit/duplicate/reordered Drop en O0/O2;
4. ejecutar y clasificar nuevamente todos los gates de §7 sobre el árbol final.

No son bloqueos de este milestone la falta de NLL general ni la prohibición
E0274, siempre que el perfil conservador y los negativos normativos aquí
definidos se cumplan. Esta enmienda no declara el milestone CLOSED.
