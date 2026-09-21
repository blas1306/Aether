# NULLABLE-ARCH-1 — nullable values and flow refinement

Estado: **ARQUITECTURA CERRADA; NO IMPLEMENTADA**, 2026-09-21.

Este milestone define nullability explícita para `compiler-next`. No modifica
lexer, parser, AST, HIR, MIR, SSA, backend, runtime, tests ni la superficie
source actualmente admitida. La implementación pertenece a **NULLABLE-V1**.

`T` continúa significando un valor válido y nunca nulo. `T?` es un `TypeId`
distinto que contiene ausencia o exactamente un `T`. La semántica no depende de
si el layout usa un niche o un tag y nunca existe una conversión implícita
`T? -> T`.

La decisión se integra con el `TypeArena` canónico, Places, ownership explícito,
cleanups y el pipeline verificado AST → HIR → MIR → SSA → LLVM descritos en el
[contrato semántico](AETHER_V1_SEMANTIC_CONTRACT.md) y la
[arquitectura del compilador](AETHER_COMPILER_ARCHITECTURE.md).

## 1. Decisiones resumidas

- `?` es un constructor postfix de tipo. `ref T?` significa `ref (T?)`; una
  referencia nullable se escribe `(ref T)?`, y análogamente para `ref mut`.
- `TypeData::Nullable(TypeId)` da identidad canónica a `T?`. `void?` y `T??`
  se rechazan.
- `null` es un literal contextual sin `TypeId` source autónomo. Debe recibir un
  expected type nullable concreto; `var x = null` falla.
- Existe una única coerción nullable implícita: `T -> T?`, representada en HIR.
  Conserva Copy o transfiere ownership según T; nunca inserta Clone ni ARC.
- NULLABLE-V1 admite `== null` y `!= null` en ambos órdenes. La igualdad general
  entre payloads nullable queda reservada.
- Sólo roots estables de locals y parámetros se refinan. Fields, indexes,
  dereferences, calls y demás projections no producen facts persistentes.
- El tipo declarado nunca cambia. Un entorno de facts por path permite un
  acceso explícito al payload bajo prueba; asignaciones y posibles escrituras
  por alias invalidan esa prueba.
- `&&`, `||` y `!` se incorporan a NULLABLE-V1 con evaluación short-circuit y
  propagación de facts a su RHS.
- Un payload owning refinado sólo puede observarse o borrowed; no puede moverse
  fuera del nullable. El `T?` completo sí puede moverse.
- El layout central elige `Niche(NullPointer)` sólo para tipos con contrato
  non-null auditado: `string`, class handles, `Function` y references. Los demás
  tipos usan `Tagged`, incluso si una optimización futura pudiera hallar niche.
- Null no ejecuta Drop. Un payload presente ejecuta el Drop de T exactamente
  una vez. Nullable no introduce boxing general.

## 2. Sintaxis, gramática y precedencia

La gramática normativa de tipos pasa a ser:

```ebnf
type              = reference-type | postfix-type ;
reference-type    = "ref", [ "mut" ], type ;
postfix-type      = primary-type, [ "?" ] ;
primary-type      = named-type
                  | function-type
                  | "(", type, ")" ;
```

El paréntesis de `primary-type` es grouping de tipos, no introduce tuple. Sólo
se necesita para aplicar `?` al resultado de un constructor prefix como `ref`.
El AST elimina el grouping y conserva el span exterior.

Consecuencias inequívocas:

```aether
string?                         // Nullable<string>
Matrix<double>?                 // Nullable<Matrix<double>>
Function<(int), int>?           // Nullable<Function<(int), int>>
ref T?                          // ref (T?)
ref mut T?                      // ref mut (T?)
(ref T)?                        // (ref T)?
(ref mut T)?                    // (ref mut T)?
List<string?>                   // List<Nullable<string>>
List<string>?                   // Nullable<List<string>>
```

`?` puede aparecer como máximo una vez en cada `postfix-type`. Aunque el parser
puede recuperar `T??` como dos tokens para dar un buen mensaje, resolución lo
rechaza como “nested nullable is not supported in NULLABLE-V1”; no lo
canonicaliza a `T?`. `?T`, `T ? ?`, `ref? T` y un `?` aplicado a una expresión
son inválidos. `?.`, `??` y postfix expression `!` no pertenecen a este diseño.

El AST incorpora conceptualmente:

```text
AstTypeKind::Nullable { payload: Box<AstType>, question_span: Span }
AstExprKind::Null
```

La precedencia de expresiones queda, de menor a mayor, `||`, `&&`, range,
equality, comparison, additive, multiplicative y unary. `!` es unary lógico;
no se confunde con `!=`. Así, `x != null && ready` se agrupa como
`(x != null) && ready` y evalúa `ready` sólo cuando la izquierda es verdadera.

## 3. Tipo canónico e identidad

`TypeData` incorpora:

```text
TypeData::Nullable(TypeId) // payload exacto
```

`TypeArena::intern_nullable(payload)` exige que:

1. `payload` exista en el mismo arena;
2. no sea `void` ni un tipo interno no almacenable;
3. no sea ya `TypeData::Nullable`;
4. retorne el único `TypeId` canónico para ese payload.

Un generic parameter sí es payload válido. Por tanto `T?` existe en HIR
paramétrico y se vuelve `Nullable(concrete_T)` durante substitution. Los ciclos
de aggregates por valor consideran `Nullable` una arista inline: `struct S {
S? next; }` no evade la prohibición de tamaño recursivo.

Nullable participa recursivamente en igualdad de tipos, aliases transparentes,
signatures, fields, enum payloads, generic arguments, collections, dumps,
substitution, depth/cycle checks, capability derivation, layout, ABI y mangling.
Un alias de `T?` conserva el mismo `TypeId`; `T` y `T?` nunca coinciden.

Las propiedades estructurales se derivan del payload:

| Propiedad de `T?` | Regla |
| --- | --- |
| `is_known` | igual que T |
| `Copy` | si y sólo si T es Copy |
| `Relocatable` | si y sólo si T es Relocatable |
| `Storable` | si y sólo si T es Storable |
| `needs_drop` | si y sólo si T necesita Drop |

Nullable no concede capabilities de comportamiento (`Add`, `Sub`, `Mul`,
`Zero`) aunque T las tenga. Null no es el cero algebraico de T.

## 4. El literal `null` y expected typing

`null` es una forma AST contextual. No se interna `TypeData::Null`, no puede
nombrarse en source, no satisface constraints y no participa como evidencia de
inferencia genérica. Antes de terminar type checking debe resolverse a un
`Nullable<U>` concreto y convertirse en `HirExprKind::NullableNull` con ese
`TypeId`.

Son válidos:

```aether
string? name = null;
Person? person = null;
Function<(int), int>? callback = null;
void f(string? value = null) { }
return null; // si el resultado declarado es U?
```

Son errores:

```aether
string name = null; // expected string no nullable
var x = null;       // no hay payload concreto
f(null);            // si ningún parámetro concreto determina U?
```

En una call, resolución e inferencia usan primero evidencia no-null y type args
explícitos. Sólo después contextualizan cada `null`. Así, para
`void f<T>(T? x)`, `f(null)` no infiere T, `f<string>(null)` sí, y una función
con otro argumento que determine T también puede aceptar null.

Las comparaciones contra null son un contexto especial: el operando no-null
determina el nullable concreto antes de resolver el literal. `null == null` y
`null != null`, al no necesitar observar un payload ni inferir T, se aceptan
como formas constantes `true` y `false` respectivamente y bajan directamente a
un bool; no crean un tipo universal para null. Fuera de este caso cerrado, dos
null sin contexto siguen sin tipo.

## 5. Construcción y coerción `T -> T?`

Cuando el expected type es `U?`, el checker aplica primero las conversiones
ordinarias permitidas de la expresión a U y luego una sola inyección nullable.
HIR conserva esa decisión como:

```text
HirExprKind::NullableInject { payload: HirExpr, nullable_type: TypeId }
```

La inyección es total y no puede fallar:

- si U es Copy, realiza la lectura/copia ordinaria;
- si U es owning non-Copy, transfiere exactamente el owner al container;
- si U es borrowed, conserva provenance y lifetime;
- nunca genera Clone, Alias/retain, allocation, boxing ni runtime cast.

Una expresión ya `U?` se usa con identidad, no se envuelve otra vez. No hay
coerción inversa, ni aun cuando el backend use el mismo word para U y U?. Una
conversión numérica y la inyección son nodos separados y verificables.

## 6. Equality y test de presencia

NULLABLE-V1 admite solamente estas operaciones de igualdad nullable:

```aether
x == null
x != null
null == x
null != x
```

donde x tiene exactamente tipo `T?`. La operación lee el discriminante lógico,
no consume, copia, retiene ni libera el payload. Produce `bool` y se representa
como `NullableIsNull { operand }`, más negación lógica cuando corresponda. Una
comparación entre un T non-null y null es error incluso si T tiene un niche
físico. Ordering con nullable siempre es error.

La igualdad `T? == T?` y `T? == T` queda fuera de NULLABLE-V1. Se reserva la
semántica futura: ausencia/ausencia true, ausencia/valor false y
presencia/presencia usa igualdad ordinaria de T sólo si T la soporta; `T` se
trataría como una inyección presente. No se expone hoy parcialmente ni se usa
igualdad de bits/punteros como sustituto.

## 7. Flow-sensitive refinement

### 7.1 Facts, no cambio de tipo

Cada binding conserva siempre su `declared_type: T?`. El análisis estructurado
mantiene separadamente, por root y path, un estado:

```text
NullState := Unknown | Null | NonNull
RefinementKey := LocalId // sólo local o parámetro root estable
```

`NonNull` permite tratar un uso compatible del root como payload T. `Null` sólo
mejora análisis/joins; no crea un valor T. El checker no reescribe la tabla de
locals ni reemplaza el TypeId declarado.

El análisis de una condición produce dos entornos, `when_true` y `when_false`:

| Condición | true | false |
| --- | --- | --- |
| `x != null` | x = NonNull | x = Null |
| `x == null` | x = Null | x = NonNull |
| `null != x` | x = NonNull | x = Null |
| `null == x` | x = Null | x = NonNull |

Esto cubre el `then` y el `else`:

```aether
if (name != null) { println(name); }
if (name == null) { } else { println(name); }
```

Sólo se generan facts para locals y parámetros directos. `obj.field`, `a[i]`,
`*slot`, resultados de calls y cualquier otra projection pueden compararse con
null, pero no quedan refinados. El usuario puede snapshotear una lectura una
sola vez en un local nullable y probar ese local. Nunca se duplica una call para
obtener una prueba.

### 7.2 Uso refinado y proof explícita

Un uso de x bajo `NonNull` no es un cast. HIR emite un acceso de payload ligado
a una prueba y a la versión vigente del binding:

```text
HirExprKind::NullablePayload {
    source: HirPlace, proof: NonNullProofId,
    access: Copy | Borrow
}
```

`Copy` sólo existe cuando T es Copy. `Borrow` crea una observación/borrow del
payload presente con lifetime contenido por el storage de `x`; sirve para
receiver access, member operations, `println` y argumentos que ya admiten
borrow call-scoped. Sólo puede aparecer anidado en esa operación consumidora de
borrow y no es un valor T general que pueda almacenarse o escapar. No fabrica
un owner T por valor ni agrega una sintaxis source para proyectar el payload.

En particular, si T es owning non-Copy, quedan rechazados aun bajo refinement:

```aether
T y = x;       // requeriría extraer/mover payload
consume(x);    // si consume T por valor
return x;      // si retorna T por ownership
```

Sí se permiten una operación observadora, un método cuyo receiver se borrowea,
un argumento adaptado por las reglas call-scoped existentes y, naturalmente,
mover o consumir el `T?` completo cuando el contexto espera `T?`. `&x` continúa
significando `ref T?`, aun bajo refinement; no cambia silenciosamente de
dirección al payload. Una futura operación `take` podrá reemplazar atómicamente
el container por null y retornar T, pero no forma parte de V1.

### 7.3 Invalidation, asignación y joins

Toda escritura al root invalida la proof anterior antes de analizar usos
posteriores. Después de una asignación válida el fact se recalcula:

- `x = null` produce `Null`;
- `x = value_of_T` (inyección conocida) produce `NonNull`;
- `x = nullable_expression` produce su fact demostrado si es un root estable
  vigente; en otro caso, `Unknown`.

También invalidan x un mutable borrow de su storage, un Store por un alias
conocido y una call que pueda escribir a través de ese alias. Si el análisis no
puede probar que x queda intacto, falla cerrado a `Unknown`. Un borrow vivo del
payload bloquea simultáneamente reemplazar x mediante las reglas de borrow ya
existentes.

En un merge, un fact se conserva sólo si es idéntico en todos los predecesores
alcanzables. `NonNull + Null`, `NonNull + Unknown` o la ausencia de un fact dan
`Unknown`. Esto permite conservar NonNull si todas las ramas lo prueban o
asignan, sin requerir un optimizador dataflow general.

Los loops se analizan con un header conservador hasta punto fijo sobre este
retículo finito. El body recibe los facts verdaderos de la condición. El estado
posterior combina la ruta de cero iteraciones con todos los backedges y aplica
los facts falsos de la última condición; ninguna asignación del body puede
producir una prueba optimista fuera del loop.

### 7.4 Short-circuit

`&&`, `||` y `!` son control flow, no operaciones eager:

- el RHS de `A && B` se analiza y ejecuta con `when_true(A)`;
- el RHS de `A || B` se analiza y ejecuta con `when_false(A)`;
- `!A` intercambia los entornos true/false.

Los facts de salida consideran todas las rutas short-circuit mediante el mismo
join por intersección. Por ello son válidos:

```aether
x != null && useBool(x)
x == null || useBool(x)
```

HIR conserva `ShortCircuitAnd`, `ShortCircuitOr` y `LogicalNot`; MIR los baja a
branches y bloques, nunca a evaluación eager. No se intenta razonamiento SAT,
De Morgan arbitrario ni correlación entre aliases.

## 8. Ownership, Move, Drop y assignment

Un `T?` owning contiene cero owners cuando está null y exactamente el owner T
cuando está presente. Sus reglas son:

- construir null crea cero obligaciones de Drop;
- inyectar un owner T transfiere una obligación al nullable;
- mover el `T?` completo transfiere tag/niche y payload como una unidad y marca
  el source moved; no es necesario escribir null físicamente en el source;
- copiar `T?` sólo es legal si T es Copy;
- Drop consulta presencia y llama Drop(T) exactamente una vez sólo si presente;
- replacement evalúa primero el RHS con las garantías normales, termina el
  valor anterior condicionalmente y publica el nuevo estado sin doble Drop;
- unwind limpia únicamente containers ya publicados y presentes.

Los drop flags de ownership siguen distinguiendo si el container completo está
Owned/Moved. La presencia interior no se representa mediante otro source drop
flag: es parte del valor nullable y `NullableDrop`/el helper estructural consulta
su discriminante. Para layout niche, null pointer omite release; para tagged,
`has_value == false` prohíbe leer o dropear los bytes de payload.

Mover el payload owning desde un refinement queda prohibido como se definió en
7.2. Esto evita dejar un container vivo con payload extraído, inventar una
escritura implícita a null o confundir Move del payload con Move del root.

## 9. References y borrowing

Las formas tienen significados distintos:

| Tipo | Significado |
| --- | --- |
| `T?` | storage nullable owning/Copy según T |
| `ref T?` | referencia non-null shared a storage nullable |
| `ref mut T?` | referencia non-null writable a storage nullable |
| `(ref T)?` | referencia shared nullable |
| `(ref mut T)?` | referencia writable nullable |

`&x` sobre `x: T?` produce `ref T?`; no prueba presencia. Un `(ref T)?` local
probado non-null se refina a `ref T`, que es Copy, conserva provenance y puede
dereferenciarse. Fuera de la prueba, dereference/member access falla.

En `ref Node? slot`, la referencia `slot` ya es non-null y su pointee es
nullable. `*slot == null` lee ese pointee; no refina la nullness de `slot` ni,
en V1, crea un fact persistente para `*slot`, porque es una projection
potencialmente mutable/aliased. `ref mut T?` puede reemplazar el container
completo con null o con una inyección bajo las reglas normales de borrow. No se
relajan provenance, exclusión de escritura, no-escape ni lifetimes.

## 10. Function, classes, string, collections y aggregates

`Function<(P...), R>` permanece non-null. Su nullable es un tipo distinto:

```aether
Function<(int), int>? callback = null;
if (callback != null) { callback(10); }
```

El function pointer non-null actual ofrece niche; `Function?` ocupa un word y
cero significa ausencia. Una call fuera de refinement falla porque Nullable no
es callable. FUNCTION-VALUES-V1, firma, ABI de la función apuntada y unwind de
la indirect call no cambian.

Los class handles y `string` continúan non-null por defecto. Sus contratos
actuales garantizan un único pointer non-null para todo valor válido, incluido
el string vacío; por ello `Class?` y `string?` reutilizan pointer cero. Null no
retiene/libera. Un valor presente conserva el ARC/lifecycle normal y su Drop
condicional ocurre exactamente una vez. `Person p = null` y `string s = null`
son errores.

Nullable compone sin deep nullability:

```aether
List<string?> values; // List non-null; cada elemento es nullable
List<string>? values; // el valor List completo es nullable
MyStruct? value;      // ausencia o struct completo
```

Los descriptores de Buffer/Array/List/Matrix/Vector/views pueden usar pointer
cero en valores válidos vacíos o tienen invariantes multiword aún no expresados
como niche central. NULLABLE-V1 los representa Tagged. Structs, enums,
interfaces y demás aggregates también son Tagged, aunque algún layout futuro
pueda exponer un niche probado. Cada elemento/field usa su layout nullable real;
no hay propagación a sus subvalores.

## 11. Representación y layout central

El layout engine incorpora una única consulta, consumida por lifecycle, ABI y
backend:

```text
NullableLayout :=
    Niche {
        layout: TypeLayout,
        niche: NullPointer { field_offset: 0 },
        zero_is_null: true,
    }
  | Tagged {
        layout: TypeLayout,
        tag_offset: 0,
        payload_offset: u64,
        payload: TypeLayout,
        zero_is_null: true,
    }
```

La elegibilidad no pregunta por el nombre source ni se dispersa en backends.
Una propiedad interna `NullNiche` sólo se devuelve cuando **todo** valor válido
de T excluye formalmente el patrón y lifecycle/backend preservan ese contrato.
La lista inicial cerrada es:

- `TypeData::String`;
- `TypeData::Class`;
- `TypeData::Reference` shared o mutable;
- `TypeData::Function`.

No se hereda niche automáticamente a aliases nominales, interfaces,
collections o aggregates. Ampliar la lista exige contrato semántico, tests de
layout/lifecycle y verifier; nunca un `if type == string` en lowering.

Para Niche, size y alignment son exactamente los de T y el null lógico es
pointer cero. Para Tagged se usa un tag byte canónico `0 = null`, `1 = present`;
`payload_offset = align_up(1, payload.align)`, alignment es
`max(1, payload.align)` y size se redondea a ese alignment después del payload.
El layout devuelve offsets explícitos; ningún consumidor recalcula padding.
Los bytes de payload de null están no inicializados/no observables. Un backend
puede ponerlos a cero, pero sólo el tag autoriza lectura y Drop.

No existe default initialization source de `T?`. La construcción explícita de
null puede usar zero-init sólo cuando `zero_is_null` está certificado por el
layout; en otro caso debe materializar el discriminante. La semántica nunca
observa padding ni compara toda la representación.

## 12. Generics, defaults, const y returns

Substitution recorre `Nullable(payload)` como cualquier constructor. Es válido
declarar `T?`, `List<T?>` y `Function<(T?), T?>`. Tras monomorphization no puede
quedar GenericParam en layout, ABI o backend. Nullable no agrega constraints:
un uso que requiere storage/drop/copy exige a T las capabilities ordinarias.

Los defaults se resuelven con el expected parameter type concreto y conservan
la receta caller-side:

```aether
void f(string? name = null) { }
```

Cada omission materializa null en el caller con el ABI normal de `string?`; no
hay sentinel adicional ni cambio al orden/evaluación única de defaults.

`const string? name = getName();` es un binding const cuyo TypeId es `string?`.
`const` no entra en Nullable y Nullable no cambia la regla shallow de const. Un
const puede refinarse pero no asignarse; Move completo continúa sujeto a las
reglas de CONST-V1 y Move de payload refinado sigue prohibido.

Un resultado declarado `T?` contextualiza `return null` e inyecta un T. Retornar
un `T?` a una función T falla. Retornar como T un payload Copy refinado es
posible; retornar un payload owning refinado por ownership se rechaza.

## 13. HIR

HIR debe hacer explícitas todas las decisiones nullable:

```text
NullableNull   { nullable_type }
NullableInject { payload, nullable_type }
NullableIsNull { operand }
NullablePayload { source, proof, access: Copy | Borrow }
ShortCircuitAnd { left, right }
ShortCircuitOr  { left, right }
LogicalNot      { operand }
```

Cada expresión conserva su TypeId exacto. La tabla de proofs identifica root,
versión del binding, branch polarity y región estructurada donde vale. El
verifier comprueba payload/nullable concordantes, ausencia de Nullable nested,
que IsNull recibe nullable, que cada payload access está dominado por su proof,
que no cruza una invalidación y que Borrow/Copy concuerda con propiedades.

El checker debe decidir access mode desde el contexto source; MIR no reconstruye
si un uso iba a observar o consumir. Un HIR que mueve payload owning, usa una
proof de otro local/versión o presenta un cast T?→T se considera corrupto.

## 14. MIR, SSA y verificadores

MIR incorpora operaciones semánticas independientes de representación:

```text
NullableNull(nullable_type)
NullableInject(payload, nullable_type)
NullableIsNull(value)
NullablePayloadCopy(place/value, proof)
NullablePayloadBorrow(place, proof)
NullableDrop(place)
```

Short-circuit ya se expresa como CFG. Los edges que prueban presencia crean una
autoridad `NonNullProofId`; NullablePayload sólo puede aparecer en un bloque
dominado por el edge correcto y antes de cualquier Store/Move/call invalidante
del root versionado. Phi de nullable tiene el mismo TypeId en todas sus entradas
y transporta el valor completo, no una proof. Los joins de facts se vuelven
proofs nuevas sólo cuando todos los incoming values están demostrados presentes.

SSA conserva `NullableNull`, `NullableInject`, `NullableIsNull` y
`NullablePayload`; no los degrada prematuramente a casts, pointer comparisons o
extractvalue. Una inyección o un edge de `IsNull` puede demostrar que un
`ValueId` SSA es presente. Para memory locals, Load/Store y alias invalidation
siguen siendo explícitos. Dominance, operand types y proof provenance se
reverifican después de toda optimización.

Lowering físico consulta `NullableLayout`: Niche materializa/testea el niche y
Tagged materializa/testea tag y proyecta el offset. Sólo entonces un payload
access probado puede ser no-op/extract. Drop emite branch de presencia antes del
Drop(T). Un backend nunca puede inferir presencia porque el puntero “parece” no
nulo ni reemplazar una proof por `assume` no verificado.

Corruption tests deben rechazar, como mínimo: null con tipo non-null, Inject con
payload incorrecto, IsNull non-null, payload access sin dominance, proof de otra
versión/root, acceso después de Store/Move, payload owning Move, phi de TypeIds
distintos, layout/tag inválido, Drop(T) sobre una ruta null y mangling que
colisione T con T?.

## 15. ABI y mangling

Nullable cambia layout y por tanto puede cambiar ABI. El clasificador ABI recibe
el `NullableLayout` completo:

- Niche nullable se pasa/retorna con la misma forma física que T, aunque su
  TypeId y semántica sean distintos;
- Tagged nullable se clasifica como su aggregate `{tag, padding, payload}` real;
- fields, elements, parámetros y retornos usan size/alignment/offsets centrales;
- no hay boxing, hidden pointer ni universal nullable descriptor.

Mangling codifica Nullable recursivamente como
`N<decimal-byte-length>x<payload-mangle>`, donde el length cuenta los bytes ASCII
de `payload-mangle`. Por ejemplo, si T mangles como `str`, T? mangles como
`N3xstr`. Esta forma exacta, recursiva y delimitada queda cubierta por goldens.
Así `f(T)` y `f(T?)`, `List<T?>` y `List<T>?`, y function signatures nested nunca
comparten símbolo aunque dos layouts físicos coincidan.

## 16. Diagnósticos mínimos

NULLABLE-V1 reserva diagnósticos específicos y anclados:

- “`null` requires a concrete nullable expected type”;
- “cannot use `null` where non-null `T` is required”;
- “cannot use `T?` where non-null `T` is required; prove `value != null` on
  this path”;
- “cannot infer T from `null` alone”;
- “nested nullable `T??` is not supported”;
- “member access/call/dereference requires a non-null value”;
- “null comparison requires a nullable operand, found T”;
- “ordering/equality between nullable values is not supported in
  NULLABLE-V1”;
- “cannot move owning payload from refined `T?`; move the nullable value or use
  a future explicit take operation”;
- “this projection is not stable enough for flow refinement; store it in a
  local and test the local”.

No diagnóstico sugiere `!`, `unwrap`, `?.` o `??`, porque esas operaciones no
existen. Los mensajes imprimen el tipo canónico y distinguen `(ref T)?` de
`ref T?` con paréntesis cuando sean necesarios.

## 17. Alcance de NULLABLE-V1

El primer vertical debe recorrer lexer → parser → AST → TypeArena → HIR → MIR →
SSA → layout/ABI → LLVM y calificar:

- `null`, `T?`, rechazo de `T??` y precedencia de references;
- inyección T→T? para Copy, owners y retornos;
- locals/parámetros, then/else, invalidación, joins, `&&`, `||` y `!`;
- null tests simétricos y rechazo contra non-null;
- defaults caller-side, const y generics con/sin evidencia suficiente;
- `Function?`, class?, string?, `(ref T)?`, `ref T?` y `ref mut T?`;
- List<T?> frente a List<T>?, nullable structs y fields;
- niche para los cuatro contratos aprobados y Tagged para int/double/struct/
  collections/interfaces;
- Drop cero/uno, Move completo y rechazo de Move de payload owning;
- O0/O2, paths normales/excepcionales y corrupción HIR/MIR/SSA.

Puede dividirse internamente en commits, pero la feature debe permanecer gated
y fail-closed hasta que representation, lifecycle, ABI y todos los verificadores
estén completos. No se admite una fase donde el frontend acepte nullable y un
backend lo trate como T.

Quedan fuera: `?.`, `??`, force unwrap/postfix `!`, Elvis, pattern matching
nullable, default initialization, FFI annotations, nested nullable, deep
nullability, fields/projections refinados, inferencia desde null solo, igualdad
general nullable, ordering, boxing universal y cambios de excepciones.

## 18. Decisiones abiertas posteriores a V1

No queda una decisión abierta necesaria para implementar NULLABLE-V1. Son
extensiones separadas:

- operación explícita `take` y/o unwrap con política de failure definida;
- safe navigation, coalescing y patterns;
- igualdad general cuando exista una capability de igualdad uniforme;
- refinamiento estable de fields/dereferences con análisis de alias más fuerte;
- niches estructurales en interfaces, enums, aggregates y descriptors;
- FFI nullability y representación estable cross-platform;
- decidir si alguna versión futura admite niveles distintos de `T??`.

Cada extensión debe conservar la regla base: T y T? son tipos distintos, ningún
payload se accede sin una prueba verificable y la representación física nunca
dicta por sí sola la semántica source.
