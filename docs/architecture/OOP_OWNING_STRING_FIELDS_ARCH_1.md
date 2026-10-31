# OOP-OWNING-STRING-FIELDS-ARCH-1 — fields owning `string` en classes

Estado: **ARQUITECTURA CERRADA; IMPLEMENTADA POR OOP-OWNING-STRING-FIELDS-V1**, 2026-10-31.

Este documento define `OOP-OWNING-STRING-FIELDS-V1`, una extensión general del
lenguaje. No admite todavía programas nuevos ni modifica compiler, runtime,
Graphics, SVG o Plots. Su primer consumer conocido es `Figure2D`, pero ninguna
regla depende de ese tipo, package o caso de uso.

## 1. Autoridad inspeccionada y problema

Son autoridades de esta decisión:

- `GENERAL_ARCH_1_STRING.md`, `GENERAL_V1_STRING_REPORT.md` y
  `GENERAL_V2_STRING_COMPOSITION_REPORT.md` para representación, Alias,
  Transfer, Relocate, Drop y composición de `string`;
- `OOP_ARCH_1.md` y los cierres OOP para identidad, layout, ARC, init,
  herencia, receiver capabilities y final release;
- `CLASS_BUFFER_FIELDS_ARCH_1.md` y su cierre V1 para fields owning privados,
  estado de inicialización, replacement y cleanup de construcción;
- `CLASS_HANDLE_REFERENCES_ARCH_1.md` para anchors y prohibición de interior
  references no estabilizadas;
- `OWNING_STRUCT_FIELD_REPLACEMENT_ARCH_1.md` y su cierre V1 para el orden
  acquire/publish/drop, sin reutilizar su clase de Place;
- `EXCEPTION_ARCH_2.md` y sus cierres para cleanup, constructor unwind y
  exceptional CFG;
- las autoridades reales de `ClassFieldInfo`, `ClassDropStep`,
  `ConstructorUnwindPlan`, `ClassOp::FieldWrite`, los ledgers MIR/SSA, el drop
  glue y el backend LLVM de `compiler-next`.

El bloqueo vigente es intencional: la admisión de fields de class sólo acepta
Copy/scalars, un `Buffer<E>` privado admitido o un owner de class concreto
privado y acotado. Un field de tipo `string` cae en `E0401`, aunque `string`
tiene layout finito, es `Storable`, `Relocatable` y `needs_drop`.

La extensión no puede resolverse clasificando `string` como Copy ni como class
handle. Esas dos aproximaciones romperían contratos ya cerrados.

## 2. Diferencias normativas entre `string` y un handle de class

| Propiedad | `string` | handle de class |
|---|---|---|
| significado | valor textual por contenido | identidad mutable compartida |
| representación source | handle opaco no nulo de una palabra | object pointer no nulo de una palabra |
| backing | objeto string inmutable, estático o heap | allocation de objeto con header y payload |
| ARC | contador privado del backing string | contador del objeto class |
| alias observable | mismo contenido; identidad no observable | misma identidad; mutation visible |
| `Copy` | no | no |
| adquisición desde lvalue | `StringOp::Alias`, retain lógico | `HandleAlias`, retain lógico |
| Transfer/Relocate | mueve una obligación, cero ARC | mueve una obligación, cero ARC |
| Drop | string release; literal inmortal puede ser no-op | object release; último release destruye payload |
| grafo/ciclos | string no contiene owners | fields class pueden formar ciclos |
| lectura de field | puede producir Alias textual independiente | sigue las reglas de graph edge/capability |

Que ambos sean físicamente un pointer y usen ARC no autoriza compartir opcode,
contador, descriptor, drop symbol, verifier category ni optimización. El objeto
class posee exactamente una obligación string por field inicializado. Aliases
de la class no duplican esa obligación: sólo mantienen vivo el mismo objeto.
Leer el field como valor sí adquiere una obligación string adicional.

## 3. Superficie V1 admitida

### 3.1 Declaración

V1 admite un field cuyo tipo canónico es exactamente `string`:

```aether
class Label {
    string text;

    public init(string initial) {
        text = initial;
    }
}
```

La admisión se decide por tipo canónico, no por spelling, alias source, nombre
de clase o package. Se permiten uno o varios fields string, intercalados con
otros fields ya admitidos, en classes finales u `open`, base o derived. La
visibility privada o pública conserva la regla ordinaria de members; `public`
no cambia ownership.

V1 no generaliza el predicado a “todo tipo que contiene string”. Structs,
enums, collections o genéricos que contienen string siguen sujetos a su propio
milestone de class storage. Tampoco admite `string?`, referencias o views por
semejanza estructural.

### 3.2 Propiedades requeridas

La autoridad central debe reconocer para el tipo exacto:

```text
Copy = false
Storable = true
Relocatable = true
needs_drop = true
finite concrete layout = true
```

Admitir storage no fabrica Clone, deep copy, mutación de bytes ni default
initialization. Una class no vacía continúa requiriendo `init` y toda salida
normal debe inicializar el field.

## 4. Layout físico e identidad del field

El field ocupa inline en la allocation del objeto la representación canónica
de un owner `string`: un handle de una palabra con alignment de pointer en el
target bootstrap. No se boxea el slot, no se agrega flag por field y no se
altera el objeto string.

El offset se calcula con el mismo `layout_of(string)` usado fuera de classes.
`FieldId` conserva identidad nominal, declaring class, índice, offset y TypeId
exactos. Un alias de tipo source o dos fields con bytes iguales no comparten
identidad de slot. La identidad del backing string no es observable.

El object header y dynamic descriptor de la class siguen siendo distintos del
header privado del backing string:

```text
class allocation
  [class strong count | class descriptor]
  [base payload]
  [string field: one string handle] ---> static/heap StringObject
  [other fields]
```

No se estabiliza ABI pública, offset fijo entre targets, reflection ni acceso
raw a ninguno de los headers.

## 5. Inicialización y transferencia de ownership

### 5.1 Adquisición del RHS

La asignación inicial consume exactamente una obligación string:

- literal o resultado fresco: Transfer de la obligación existente;
- local/lvalue string vivo: Alias, con retain lógico y source todavía válido;
- parámetro owning: sigue la categoría real de la expresión, sin bitcopy;
- valor moved-from, reference o tipo distinto: rechazo.

La adquisición ocurre antes de escribir el slot. `ClassOp::FieldWrite` con
`initialize=true` consume el owner RHS y asocia la obligación al `FieldId`.
Los bytes reservados por `ObjectAlloc`, incluso si están zeroed, no son un
string válido ni cuentan como inicialización. `""` es un owner válido porque
designa el singleton inmortal no nulo; no es sentinel uninitialized.

### 5.2 Inicialización definida e herencia

Se conserva el análisis path-sensitive vigente:

- base init completa antes del body/fields derived;
- no hay read, Alias ni borrow antes de la primera escritura;
- cada salida normal inicializa todos los fields propios;
- joins deben concordar; un loop no prueba por sí solo ejecución;
- el objeto se publica sólo después de base y derived completos;
- `this` no escapa durante init.

Una segunda escritura a un field ya inicializado es replacement, incluso dentro
de `init`; no puede marcarse de nuevo como initialize para omitir el Drop viejo.

## 6. Lectura, Alias y borrowing

### 6.1 Lectura owning

Leer un field string inicializado como valor produce un **Alias string**, no
una extracción ni Move del slot:

```aether
public string title() {
    return title; // Alias; la class conserva su obligación
}
```

La operación adquiere primero un owner string independiente y sólo después
puede terminar el keepalive del receiver. Es válida desde receiver read o mut
y respeta visibility. El resultado sigue vivo aunque otro alias de la class
reemplace el field o se destruya el objeto.

HIR no debe representar esta lectura como `ClassOp::FieldRead` Copy ni como un
load de pointer sin retain. Debe conservar una operación explícita equivalente
a `StringFieldAlias { receiver, field }`, cuyo resultado exacto es `string` y
que crea una obligación en el ledger.

### 6.2 Borrow estabilizado para calls

V1 permite usar el contenido del field en un parámetro `ref string` sólo con
esta semántica:

```text
field read -> StringFieldAlias hidden owner -> ordinary borrow of hidden owner
           -> call -> EndBorrow -> Drop hidden owner
```

El retain lógico estabiliza el backing frente a replacement o destrucción del
objeto a través de otro alias durante la call. O0 puede materializar el owner;
O2 puede elidir retain/release únicamente si SSA prueba la obligación y la
misma vida observable.

No se admite crear un `ref string` cuyo anchor sea directamente el slot dentro
de la class, almacenar/retornar ese reference, ni formar `&object.field` como
interior reference source-visible. Un keepalive de la class sólo mantiene viva
la allocation del objeto; no impide que un alias mut reemplace el field y
libere su backing anterior. La estabilización mediante Alias es, por ello, un
contrato de seguridad y no sólo una optimización.

### 6.3 Aliasing y mutabilidad

El backing string es inmutable. Un Alias textual no permite mutar la class ni
el slot. Read receiver puede leer/Alias/prestar el owner estabilizado, pero no
reemplazar el field. Replacement requiere receiver mut o el acceso writable ya
admitido para un member público. `mut` no implica exclusividad ni `noalias`.

## 7. Replacement

Para un field string ya inicializado, `field = rhs` sigue exactamente:

```text
1. evaluar rhs completamente;
2. adquirir una obligación string independiente por Alias o Transfer;
3. capturar internamente el handle anterior;
4. publicar el handle nuevo en el slot;
5. consumir el owner RHS hacia el field;
6. ejecutar string Drop/release del handle anterior una vez.
```

Los pasos 3–6 forman un efecto semántico indivisible sin unwind. El store debe
preceder al release. Si RHS lanza, el slot y su owner viejo quedan intactos y
sólo se limpian temporaries del RHS. Si una excepción ocurre después del
commit, el cleanup final encuentra el owner nuevo.

`field = field` no es un Move parcial. La lectura RHS crea primero un Alias
independiente; por ello retain-new, publish-new, release-old es correcto aun si
ambos handles designan el mismo backing. No se agrega pointer comparison en
LLVM ni se permite bitcopy sin adquisición.

No hay estado source-visible empty/moved, `take`, `swap`, extracción owning ni
lectura field-to-field por Transfer. El objeto publicado permanece totalmente
inicializado.

## 8. Destrucción normal, excepcional y herencia

### 8.1 Final release normal

La receta `ClassDropStep` incluye todo field string porque `needs_drop=true`.
En el último release del objeto dinámico ejecuta:

1. fields propios derived que necesitan Drop, en orden inverso de declaración;
2. fields de cada base según su receta, derived antes que base;
3. un único free de la allocation most-derived.

Cada step string carga el handle del slot y llama al drop glue canónico de
`string`, que ejecuta string release o no-op para un literal inmortal. No llama
object release, no recorre bytes y no altera el ARC de la class.

### 8.2 Construcción parcial y unwind

`ConstructorUnwindPlan` conserva la receta canónica completa, mientras el
estado CFG selecciona sólo el prefijo realmente inicializado. Ante throw:

- un field cuyo RHS inicial lanzó no se toca;
- un field string ya instalado se libera una vez;
- los fields se limpian en orden inverso, y luego una base completada;
- un init de base que falla limpia su propio prefijo;
- no se publica `this`, no se ejecuta `deinit` y se libera una vez la
  allocation completa;
- no se requiere bitmap runtime ni valor string nulo.

Un release/drop durante cleanup es non-throwing. Corrupción de ARC conserva la
política trap/fail-fast; no crea una segunda exception recuperable.

## 9. Restricciones y diagnósticos

### 9.1 Cerrado en V1

Permanecen fuera:

- fields cuyo tipo sólo **contiene** string;
- `ref string`, `ref mut string`, `StringView` o cualquier interior reference
  almacenado directamente en la class;
- borrow source-visible anclado al slot de class;
- partial move/extraction, destructuring, `take` o `swap` del field;
- default implícito a `""`, field initializer expressions y null string;
- class genérica o tipo simbólico admitido sólo por `T: Storable`;
- `Buffer<string>` u otra collection por inferencia desde este milestone;
- deep copy/Clone estructural y mutación/COW/SSO de strings;
- atomic ARC, acceso cross-thread, FFI de layout y ABI pública;
- reglas especiales para Plots, Graphics o nombres de fields.

### 9.2 Diagnósticos mínimos

La implementación puede reservar IDs definitivos al integrar, pero debe
producir diagnósticos específicos y estables para:

| Condición | Diagnóstico requerido |
|---|---|
| field string exacto | admitido; no `E0401` |
| aggregate/container con string | storage owning compuesto no admitido en class V1 |
| read antes de init | field read before initialization |
| write desde receiver read | field mutation requires a declared mut receiver |
| interior `&field` | interior class string reference unavailable; use value Alias/call-scoped stabilized borrow |
| Move/extraction | owning class string field cannot be moved out |
| IR init/replacement adulterado | verifier error, nunca fallback a Store |

No se relaja `E0401` globalmente: se agrega una rama positiva exacta. Los casos
fuera del perfil siguen fallando cerrados.

## 10. Contratos HIR, MIR y SSA

### 10.1 Metadata y HIR

La autoridad central de class storage debe clasificar `string` exacto y ser
recalculada por resolución y `verify_class_metadata`. `ClassFieldInfo.ty`,
offset y `ClassDropStep::Field { field, ty }` deben coincidir con el TypeId y
layout canónicos.

HIR debe demostrar independientemente:

- declaración exacta, layout finito y visibility;
- estado inicializado por `FieldId` en cada path;
- `FieldWrite.initialize` correcto y consumo único del RHS;
- read owning sólo por `StringFieldAlias`, nunca `FieldRead` Copy;
- borrow de call sólo desde un owner Alias temporal con Begin/EndBorrow;
- receiver capability, member access y no-escape;
- cleanup lists iguales a ownership synthesis;
- constructor unwind plan igual a la receta canónica.

### 10.2 MIR

MIR conserva operaciones explícitas de:

- adquisición Alias/Transfer del RHS antes de `FieldWrite`;
- alias read del field que produce exactamente un owner;
- initialize frente a replacement;
- replacement publish-before-drop, sin exceptional edge interno;
- cleanup parcial `ConstructionCleanup` con fields canónicos;
- borrow temporal ordinario y su fin en retorno normal/unwind de la call.

El ledger de classes debe incluir `string` exacto además de los owners ya
seguidos. Rechaza owner RHS inexistente/duplicado, load owning sin Alias,
FieldWrite con tipo distinto, replacement de field no inicializado, omisión o
duplicación de cleanup y salida normal con fields faltantes.

### 10.3 SSA y optimización

SSA preserva FieldId, TypeId, initialize/replacement, receiver, owner de
resultado y efectos ARC. El verifier reconstruye:

- un token string por field inicializado y uno nuevo por cada Alias result;
- consumo del RHS exactamente una vez por FieldWrite;
- continuidad del owner de slot a través de joins/replacement;
- ausencia de owner extra por load, phi, Store o corrupción de metadata;
- orden publish-before-release y cleanup excepcional correcto;
- lifetime del owner temporal que estabiliza cada borrow.

ARC optimization puede eliminar pares retain/release sólo después de esta
verificación, sin cambiar el momento de último release a través de calls,
handlers, `finally` u otros efectos. O2 no puede tratar un read string como load
puro ni inferir `noalias` de receiver mut.

### 10.4 Enmienda de precisión: eventos, borrows y verificación independiente

Esta enmienda no cambia la semántica cerrada; fija tres distinciones que la
implementación debe poder comprobar:

1. Un evento lógico de ownership es la creación, transferencia o consumo de
   una obligación en HIR/MIR/SSA. Siempre existe aunque el backing sea un
   literal inmortal o el optimizador pruebe que el retain/release físico puede
   omitirse. Una operación ARC física es sólo la llamada runtime emitida en
   LLVM. O0 materializa los efectos físicos ordinarios; O2 puede elidirlos
   únicamente después de conservar el mismo token lógico y el mismo momento
   observable de último release.
2. El borrow estabilizado se admite exclusivamente al adaptar para un
   parámetro `ref string` una expresión value de field (`field`/`this.field`
   dentro del método, o `owner.field` con receiver estable ya admitido). Esa
   expresión produce primero `StringFieldAlias`; el borrow ordinario se forma
   sobre ese owner temporal y termina al volver o unwinding la call. La
   expresión source-visible `&owner.field`, incluso dentro de la clase, no es
   una abreviatura de este protocolo y permanece rechazada como referencia
   interior. Tampoco se puede retornar ni almacenar el borrow temporal.
3. HIR recalcula TypeId/FieldId/layout, estado de inicialización y exige el
   opcode owning; MIR vuelve a validar esos datos, el estado por CFG y el
   consumo único del owner sin confiar en el resultado HIR; SSA reconstruye
   sus tokens desde valores/phis/operaciones, prohíbe que un `Load` cree owner
   y cuenta de nuevo cada transferencia a `FieldWrite` o call. Sólo después de
   superar las tres autoridades LLVM puede materializar o elidir ARC. Los
   dumps y metadatos de una capa anterior no constituyen prueba para la
   siguiente.

## 11. LLVM O0/O2 y runtime

El backend recibe únicamente SSA verificada. Para Linux x86-64 usa el layout
pointer canónico del string y el offset verificado del field.

- init: store del owner adquirido, sin release previo;
- Alias read: load + string retain lógico/físico;
- replacement: load old, store new, string release old;
- final/partial cleanup: `aether_drop_string(handle)` una vez;
- literal inmortal: retain/release físico puede ser no-op por el runtime
  string ya vigente.

No se agrega runtime nuevo, header común con classes, tag por field, bitmap,
boxing, branch por package ni símbolo Plots. O0 conserva todos los efectos
lógicos. O2 puede aplicar las elisiones ARC ya verificadas y debe producir la
misma salida, excepciones, orden de destrucción y balances por identidad.

El contador de instrumentación de Buffer existente no puede usarse como
evidencia de Drop string: qualification necesita contadores string separados
de object ARC y Buffer backing.

## 12. Qualification obligatoria

Todos los casos ejecutables se califican nativamente en O0 y O2. La suite debe
registrar por separado object alloc/free/retain/release y string
alloc/free/retain/release/literal-noop.

### 12.1 Positivos

- un field string desde literal, heap result y lvalue;
- vacío inmortal y contenido UTF-8/no ASCII/U+0000 ya válido;
- dos y tres fields intercalados con Copy y Buffer admitido;
- private y public field; class final y open;
- lectura value desde receiver read y mut, retorno y parámetro by-value;
- borrow de call estabilizado y nested calls;
- replacement desde literal, fresh result, lvalue y mismo field;
- dos replacements consecutivos con identidad de allocation observada;
- alias de class antes/después del replacement;
- base string + derived string, base handle y dispatch dinámico;
- early return, branches y loops con estado definido;
- RHS throw antes de owner, después de temporaries y excepción posterior al
  commit;
- fallo durante base init y durante derived init después de uno o más fields;
- final release por handle concrete, base e interface si ya admitido;
- equivalencia observable y balance exacto O0/O2.

### 12.2 Negativos

- read/borrow antes de init y path normal sin init completa;
- write desde receiver read o member privado inaccesible;
- uso del RHS moved-from, tipo distinto y owner duplicado;
- extracción/Move, field-to-field Transfer y Drop proyectado source;
- `&object.field`, retorno/storage de interior ref y `ref mut string` interior;
- struct/enum/Array/List/Buffer que contiene string como field class;
- nullable/view/reference/function/generic symbolic por falsa semejanza;
- metadata de FieldId perteneciente a otra class o tipo/offset adulterado;
- `initialize=true` sobre field vivo y replacement antes de init;
- Store pointer ordinario que evita Alias/Transfer/Drop.

### 12.3 Corruption tests por capa

HIR, MIR y SSA deben rechazar independientemente:

- borrar o duplicar el owner de `StringFieldAlias`;
- convertir el alias read en `FieldRead` Copy;
- omitir el retain lógico de una lectura lvalue;
- marcar string como Copy o como class handle;
- consumir dos veces u omitir el RHS de FieldWrite;
- invertir release/store o agregar unwind entre ambos;
- omitir/duplicar/reordenar `ClassDropStep`;
- alterar constructor cleanup, base/derived order o initialized set;
- prestar directamente el slot sin owner temporal estabilizador;
- cambiar TypeId, FieldId, offset, visibility o receiver capability;
- eliminar un release bajo O2 sin prueba ARC válida.

### 12.4 Gates de regresión

La qualification de implementación exige:

- fixture dedicada y reproducers O0/O2;
- suites string GENERAL-V1/V2, OOP/inheritance/interfaces, Buffer/class fields,
  references/borrows, owning replacement, exceptions/finally y LLVM opt;
- reproducer negativo original de Plots convertido en positivo sólo por la
  regla general, sin tocar Plots productivo;
- `cargo test --workspace -j 1`, format, clippy y `git diff --check` cuando se
  implemente el vertical;
- inspección de LLVM O0/O2 para retain de read, store-before-release,
  destruction derived-before-base y ausencia de runtime/type branches nuevos.

## 13. Criterios de cierre y secuencia

`OOP-OWNING-STRING-FIELDS-V1` sólo podrá declararse implementado cuando:

1. admisión y metadata usan el TypeId exacto sin allowlists;
2. init, Alias read, stabilized borrow y replacement tienen owners explícitos;
3. HIR/MIR/SSA verifican de forma independiente;
4. partial construction y final destruction liberan cada string una vez;
5. herencia conserva derived-before-base y una sola object free;
6. los contadores separan ARC string de class y coinciden en O0/O2;
7. corruption tests y gates de regresión pasan;
8. el reproducer de Plots deja de emitir `E0401` sin excepción especial.

Hasta entonces `E0401` es el comportamiento correcto y
`PLOTS-2D-LINE-V1` permanece **BLOCKED**. Cerrar esta arquitectura no autoriza
implementar ni reanudar Plots.
