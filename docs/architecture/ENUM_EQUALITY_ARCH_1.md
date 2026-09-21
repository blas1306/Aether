# ENUM-EQUALITY-ARCH-1 — igualdad nominal de enums payload-free

Estado: **ARQUITECTURA CERRADA; NO IMPLEMENTADA**, 2026-09-21.

Este milestone define `==` y `!=` para valores de un mismo enum nominal sin
payloads en `compiler-next`. No modifica lexer, parser, AST, HIR, MIR, SSA,
backend, runtime, tests ni la superficie actualmente admitida. La
implementación pertenece a **ENUM-EQUALITY-V1**.

La motivación inmediata es una regresión encontrada al portar
`examples/numerical_methods`: el checker construye hoy un `HirExprKind::Binary`
para dos valores `Status`, pero el verificador sólo reconoce igualdad de
`bool` y numéricos y falla tarde con `E0348 HIR binary invalid`. Este diseño
cierra el contrato completo para que una expresión source válida no dependa de
un error interno y una inválida se rechace antes de publicar HIR.

## 1. Decisiones resumidas

- V1 admite exclusivamente `e1 == e2` y `e1 != e2` cuando ambos operandos
  tienen el mismo tipo enum canónico y la declaración no tiene payload en
  ninguna variante.
- La identidad es nominal. Dos `EnumId` distintos nunca son comparables aunque
  sus nombres, variantes, discriminantes, layout o representación física sean
  iguales.
- Para un enum generic aplicado se exige además identidad exacta de `TypeId`.
  `Box<int>` se compara con `Box<int>`; no con `Box<double>`.
- Igualdad significa igualdad de `VariantId`/discriminante dentro de esa única
  declaración nominal. `!=` es exactamente la negación de esa relación.
- No se introducen conversiones entre enums, coerción numérica, comparación por
  layout, igualdad estructural ni una conversión source enum → integer.
- Enums con cualquier payload continúan rechazados, aun si el payload es Copy,
  cero-sized, nunca se usa en una instancia concreta o ambas expresiones
  construyen la misma variante.
- `Status? == Status?` continúa fuera de NULLABLE-V1. `Status? == null` y el
  orden simétrico conservan las reglas nullable existentes.
- HIR conserva `Binary { Equal | NotEqual }`. MIR y SSA conservan la misma
  operación y los `TypeId` exactos de sus operands; sus verificadores vuelven a
  validar nominalidad y ausencia de payload.
- LLVM puede comparar los tags físicos sólo después de recibir SSA verificado.
  No cambia layout, ABI, mangling ni calling convention.

## 2. Superficie source y semántica

No se agrega sintaxis. La gramática y precedencia existentes de equality se
mantienen:

```aether
enum Status {
    Ok,
    Error
}

Status left = Status.Ok;
Status right = Status.Error;

left == Status.Ok;       // true
left == right;           // false
left != right;           // true
```

Sea `E` una declaración enum y `V(E)` su conjunto de variantes. Si todas las
variantes de `E` tienen una lista de payload vacía, cada valor válido de `E`
denota exactamente una variante. Para operands `x` e `y` del mismo tipo enum
canónico:

```text
x == y  := variant(x) = variant(y)
x != y  := not (x == y)
```

La comparación sólo observa la variante. No consume los operands, no los
mueve, no crea borrows, no ejecuta Drop y no puede lanzar. Un enum payload-free
es Copy bajo las reglas agregadas actuales, incluidas sus instancias generic,
pero la admisibilidad de equality se decide directamente por su forma enum y
no se infiere de la capability Copy.

Las evaluaciones de `x` e `y` mantienen el orden ordinario de expresiones
binarias: izquierda y después derecha, exactamente una vez cada una. La
operación no altera esos efectos ni permite omitir la evaluación porque dos
variantes escritas sean evidentemente iguales. Un constant fold posterior sólo
es válido tras verificar tipos y preservar efectos.

Ordering y aritmética no se amplían:

```aether
Status.Ok < Status.Error    // error
Status.Ok + Status.Error    // error
```

El orden de declaración o el valor físico de un discriminante no define un
orden source.

## 3. Identidad nominal y tipos canónicos

La regla normativa de admisión para una operación `==` o `!=` es:

1. tipar completamente ambos operands con las reglas ordinarias, sin expected
   type inventado por equality;
2. resolver ambos `TypeId` a `TypeData::Enum` o `TypeData::EnumInstance`;
3. exigir el mismo `EnumId`;
4. exigir `left.ty == right.ty`;
5. comprobar en el `EnumInfo` de ese `EnumId` que toda variante tiene cero
   payloads;
6. producir `bool` sin insertar coercions.

Los pasos 3 y 4 son intencionalmente separados. Para enums no generic, el
`TypeArena` canónico hace que el mismo `EnumId` implique el mismo `TypeId`. En
una aplicación generic, el `EnumId` identifica la declaración y el `TypeId`
identifica también su lista canónica de argumentos:

```aether
enum Box<T> {
    Empty,
    Full
}

Box<int> a = Box<int>.Empty;
Box<int> b = Box<int>.Full;
Box<double> c = Box<double>.Empty;

a == b; // válido: mismo TypeId Box<int>
a == c; // error: mismo EnumId, distinta instancia/TypeId
```

Aunque `T` no contribuya al layout de este enum, `Box<int>` y `Box<double>` son
tipos aplicados distintos. El backend no puede usar que sus bits coincidan para
relajar esta regla. Transparent aliases, que ya se resuelven al tipo canónico
subyacente, comparan como ese mismo tipo y no crean una identidad nueva.

Tampoco se busca un tipo común. En particular quedan prohibidos:

- widening o reencoding numérico de un enum;
- cast implícito entre dos enums;
- adaptación por compartir interface, capability o layout;
- comparación de un enum con su tag integer;
- comparación de dos aplicaciones distintas aunque sus argumentos tengan el
  mismo layout o aliases no canónicos en source.

Un error al tipar cualquiera de los operands se reporta con su diagnostic
primario y detiene esta clasificación para evitar cascadas de equality.

## 4. Definición de payload-free

Una declaración es payload-free si y sólo si:

```text
enum_info.variants.all(|variant| variant.payloads.is_empty())
```

Es una propiedad de la declaración, no del layout ni de una optimización. Debe
consultarse en la metadata semántica autoritativa `EnumInfo`; no se deduce del
tamaño, alignment, `needs_drop`, `is_copy`, cantidad de variantes o contenido
del storage LLVM.

Por tanto todos estos enums están fuera de V1:

```aether
enum Result {
    Ok(int),
    Error(string)
}

enum Maybe<T> {
    None,
    Some(T)
}
```

`Result.Ok(1) == Result.Ok(1)` sigue siendo error. También lo es una instancia
`Maybe<UnitLike>` aunque su payload eventualmente ocupe cero bytes. Que una
comparación concreta sólo alcance variantes payload-free de una declaración
mixta no cambia la regla: basta un payload en cualquier variante para excluir
la declaración completa.

Las reglas existentes deciden si una declaración con cero variantes es válida.
Si lo fuera, satisface formalmente la propiedad pero no tiene valores
construibles; ENUM-EQUALITY-V1 no cambia esa política.

## 5. Frontera compartida de contrato

La implementación debe centralizar una consulta semántica equivalente a:

```text
classify_enum_equality(left: TypeId, right: TypeId, enums, types)
    -> Admitted { enum_id, enum_type }
     | NotBothEnums
     | DifferentDeclarations { left: EnumId, right: EnumId }
     | DifferentInstances { enum_id, left: TypeId, right: TypeId }
     | PayloadBearing { enum_id }
     | InvalidMetadata
```

El nombre y la forma Rust exactos no son normativos. Sí lo son una única
definición de `payload-free`, la identidad exacta de instancia y su reutilización
por resolución, HIR verification, MIR verification y SSA verification. Los
checkers source traducen la clasificación a diagnostics precisos; los
verificadores de IR la traducen a errores internos de su fase.

La consulta no concede una capability de igualdad general. Es una regla
cerrada built-in para enum payload-free. Esto evita afirmar accidentalmente que
un `T` generic arbitrario es comparable o que todos los aggregates Copy lo son.

En HIR paramétrico, `Box<T>` puede compararse con el mismo `Box<T>` si ambos
operands tienen el mismo `TypeId` aplicado bien formado y la declaración es
payload-free. La sustitución debe producir un único `Box<int>` canónico. HIR
concreto, MIR y SSA continúan prohibiendo generic parameters sin resolver como
ya lo hacen; no existe raw `Box`, wildcard de argumentos ni comparación
dependiente del layout instanciado.

## 6. Resolución y typing source

La ruta de binary typing debe interceptar cualquier operación con un operand
enum antes de buscar `common(...)` o aplicar reglas numéricas. Para `==` y
`!=`, usa la clasificación anterior. Para cualquier otro operador, emite un
error de operands incompatibles.

Una comparación admitida construye:

```text
HirExpr {
    kind: Binary {
        op: Equal | NotEqual,
        left: HirExpr<E>,
        right: HirExpr<E>,
    },
    ty: bool,
}
```

donde `left.ty == right.ty == E`. No se agrega `EnumEqual`, `EnumToInt`, cast,
coercion ni nodo de layout. Conservar `Binary` mantiene la representación
existente y basta porque cada expresión ya porta su `TypeId` canónico.

El branch debe ocurrir después de las rutas especiales que ya poseen semántica
propia y que no se amplían aquí: nullable/null, strings, identidad de clases e
interfaces. En particular un `Nullable<Status>` no se desempaqueta ni se
clasifica como enum por mirar recursivamente su payload.

## 7. Contrato y verificación HIR

Para `HirBinaryOp::Equal | HirBinaryOp::NotEqual`, el verificador acepta
exactamente tres familias built-in:

- `bool` con `bool`;
- el mismo tipo numérico canónico con el mismo tipo;
- el mismo tipo enum canónico payload-free con el mismo tipo.

En los tres casos el resultado debe ser `bool`. Para la tercera familia debe
resolver el `EnumId`, validar existencia/canonicalidad de metadata, identidad
exacta de operands y ausencia de payload. El simple hecho de que
`left.ty == right.ty` no alcanza: un tipo struct, nullable, payload enum o tipo
interno corrupto debe fallar.

La verificación debe rechazar como `E0348` de categoría Verification, al menos:

- operand types distintos;
- `EnumId` o aplicación inexistente/incompleta;
- enum payload-bearing;
- resultado distinto de `bool`;
- ordered/arithmetic opcode aplicado a enum.

Esos errores sólo son defensa contra HIR corrupto. Source válido no debe
alcanzarlos; source inválido usa los diagnostics de la sección 12.

La sustitución/monomorfización de una expresión de enum equality conserva el
opcode y sustituye ambos operand types. Después vuelve a verificarse el
contrato con la instancia concreta. No se transporta un `EnumId` redundante
que pueda divergir del `TypeId`.

## 8. Lowering y contrato MIR

HIR → MIR baja la expresión admitida a la forma existente:

```text
destination: bool = Rvalue::Binary {
    op: Equal | NotEqual,
    left: Operand<E>,
    right: Operand<E>,
    trap: None,
    secondary_trap: None,
}
```

Los operands se materializan con las reglas ordinarias y conservan `E` en sus
locals/places. No se baja todavía a integer ni se pierde provenance nominal.
La operación no tiene unwind edge ni cleanup propio.

El contrato compartido de `BinaryOp::Equal/NotEqual` debe recibir acceso tanto
al `TypeArena` como a `EnumInfo`. Para enum equality exige:

```text
left_type == right_type == exact enum TypeId
destination_type == bool
payload_free(enum_id)
trap == None
secondary_trap == None
```

El verificador MIR vuelve a resolver ese `TypeId`; no confía sólo en que HIR
fue verificado. Debe rechazar mutaciones que cambien un operand a otro enum, a
otra instancia del mismo enum, a un payload enum, cambien el destino o añadan
traps. Los errores permanecen internos `E0300`/Phase::Mir.

No se necesita un campo adicional de provenance en `Rvalue::Binary`: `Operand`
→ local/place → `TypeId`, más `TypeData::Enum[Instance]`, ya preserva la
declaración y los argumentos. Añadir un `EnumId` duplicado crearía dos fuentes
de verdad y no está autorizado por este diseño.

## 9. SSA y optimizaciones

MIR → SSA conserva:

```text
result: bool = SsaOp::Binary {
    op: Equal | NotEqual,
    left: SsaOperand<E>,
    right: SsaOperand<E>,
    trap: None,
    secondary_trap: None,
}
```

Los values SSA y operands permiten recuperar el `TypeId` exacto. El
verificador SSA aplica el mismo contrato nominal con `TypeArena` y `EnumInfo` y
reporta corrupción como `E0400`/Phase::Ssa. Debe detectar las mismas mutaciones
que MIR, incluidas aplicaciones generic diferentes con el mismo `EnumId`.

Una optimización puede:

- propagar o plegar tags conocidos;
- reemplazar `x == x` por `true` sólo cuando la evaluación/ownership ya permite
  esa transformación y se preservan efectos;
- expresar `NotEqual` como negación de `Equal` o como comparación `ne` del tag.

No puede introducir igualdad entre tipos distintos, comparar bytes/padding del
aggregate, convertir el enum a un integer source-observable ni borrar la
validación nominal antes de SSA verificado. Cualquier IR reescrito debe volver
a satisfacer el verifier.

## 10. Backend, layout y ABI

La representación LLVM actual de un enum comienza con su discriminante/tag
canónico. Para un `SsaOp::Binary` enum ya verificado, el backend:

1. obtiene el tipo exacto de ambos operands;
2. extrae o carga el field de tag definido por el layout central;
3. emite `icmp eq` para `==` o `icmp ne` para `!=` sobre esos tags;
4. produce `i1`.

Si los operands están en valores aggregate SSA, se usa `extractvalue`; si la
ruta de lowering los mantiene en storage, se usa el acceso de field tipado
equivalente. La elección física no cambia la semántica.

Queda prohibido emitir `icmp` sobre el aggregate completo, usar `memcmp`,
comparar padding, asumir que el valor source es intercambiable con `i32` o
reconstruir nominalidad desde el layout LLVM. El `EnumInfo` verificado garantiza
que sólo el tag es observable para este caso.

ENUM-EQUALITY-V1 no cambia:

- `TypeLayout`, ancho o asignación de discriminantes;
- representación de enum payload-free o payload-bearing;
- parámetros/retornos y aggregate calling convention;
- mangling de declaraciones o instancias generic;
- drop/relocation glue;
- metadata importada ni formato de símbolos.

O0 y O2 deben compartir el mismo resultado observable. O2 puede simplificar la
comparación física después de que el contrato SSA haya sido verificado.

## 11. Nullable, ownership e interacción con otras igualdades

### Nullable

Este milestone no amplía igualdad nullable:

```aether
Status? a;
Status? b;

a == b;       // sigue fuera de NULLABLE-V1
a != b;       // sigue fuera de NULLABLE-V1
a == null;    // conserva NullableIsNull existente
null != a;    // conserva NullableIsNull + LogicalNot existente
```

No se inyecta `Status -> Status?` para hacer comparables operands y no se usa
enum equality para comparar payloads presentes. El diagnostic existente de
igualdad nullable general tiene precedencia porque el tipo exterior es
`Nullable`, no `Enum`.

### Ownership

Un enum payload-free no contiene owners y deriva Copy conforme al contrato
actual. Compararlo sólo lee sus valores. ENUM-EQUALITY-V1 no añade Clone,
retain/release, move, borrow ni cleanup. Una expresión que falle antes de
producir el operand conserva su comportamiento normal; la comparación misma no
trapea ni lanza.

### Otras familias

La igualdad numérica, de bool, strings y la identidad de objetos conservan sus
nodos y reglas actuales. No se generaliza un trait/capability `Eq` y no se
habilita igualdad de structs, references, functions, buffers, collections o
interfaces por analogía.

## 12. Diagnostics source-facing

El primer vertical reserva `E0470..E0472`; si el catálogo central reasigna los
números antes de implementar, los nombres y contenidos siguen siendo
normativos.

| Código | Situación y mensaje mínimo | Span primario / notas |
| --- | --- | --- |
| `E0470 enum_equality_nominal_mismatch` | ``cannot compare distinct enum types `A` and `B`; enum equality is nominal`` | operador/expresión; notas en ambos operand types o declaraciones |
| `E0471 payload_enum_equality_unsupported` | ``equality for payload-bearing enum `Result` is not supported in ENUM-EQUALITY-V1`` | operador/expresión; nota en la primera variante con payload |
| `E0472 enum_equality_operand_mismatch` | ``enum equality requires two values of the same enum type; found `Box<int>` and `Box<double>` `` | operador/expresión; spans de operands; o mensaje equivalente para enum/no-enum y operador no admitido |

La selección es determinista:

1. si un operand no puede tiparse, conservar su diagnostic y no emitir otro;
2. si la operación no es `==`/`!=` o uno de los tipos no es enum, `E0472`;
3. si ambos son enums con `EnumId` diferentes, `E0470`;
4. si comparten `EnumId` pero sus `TypeId` aplicados difieren, `E0472`;
5. si el tipo exacto es payload-bearing, `E0471`;
6. de lo contrario, admitir.

Esto garantiza que `A.X == B.X` explique nominalidad, que
`Box<int> == Box<double>` explique instancia exacta y que `Result == Result`
explique el límite deliberado de payloads. Ninguno debe degradar a
`E0348 HIR binary invalid`. Errores HIR/MIR/SSA siguen usando sus families de
Verification porque indican corrupción del compilador, no un error source.

## 13. Igualdad futura de enums con payload

Habilitar payload enums exige otro diseño y no puede implementarse comparando
sólo tags. La semántica futura mínima tendría que definir:

1. comparar primero la variante;
2. si difiere, producir `false` sin leer payloads incompatibles;
3. si coincide, proyectar los payloads activos en orden;
4. exigir igualdad recursiva para cada tipo de payload;
5. combinar resultados con short-circuit;
6. hacer de `!=` la negación de la relación completa.

Antes de ese vertical debe existir una capability/constraint de igualdad que
pueda expresarse para tipos concretos y generic parameters, con reglas de
derivación recursiva y diagnóstico de cuál payload no la satisface. También se
deben cerrar ownership y borrow semantics: observar payloads activos sin mover
owners, lifetimes de projections, valores non-Copy, temporales, aliasing,
short-circuit, cleanup y potenciales equalities que puedan lanzar.

El futuro diseño debe decidir además coherencia con structs, nullable
presente/presente y user-defined equality. Nada de ello se anticipa mediante
una capability ficticia en V1. La clasificación `PayloadBearing` permanece un
failure gate explícito.

## 14. Primer vertical — ENUM-EQUALITY-V1

La implementación posterior debe incluir:

1. clasificación central exacta de enum equality;
2. branch source-facing antes de numeric common/coercion;
3. aceptación HIR de `Equal/NotEqual` enum payload-free;
4. sustitución y monomorfización de instancias generic exactas;
5. contrato MIR con acceso a metadata enum;
6. contrato SSA equivalente;
7. lowering LLVM por extracción del tag verificado;
8. diagnostics `E0470..E0472`;
9. dumps que demuestren conservación de `TypeId` hasta SSA;
10. qualification funcional, negativa y de corrupción en O0/O2.

No requiere cambios de parser/AST ni un nodo source nuevo. Si al implementar se
descubre que una capa ha borrado el `TypeId` nominal antes de verificar, la
solución debe restaurar esa provenance; no se permite inferirla del LLVM type o
del tamaño.

## 15. Matriz de qualification

### Casos positivos

- `Status.Ok == Status.Ok` produce `true`;
- `Status.Ok == Status.Error` produce `false`;
- `Status.Ok != Status.Error` produce `true` y `Status.Ok != Status.Ok`,
  `false`;
- operands en literals/constructors, locals y parámetros;
- resultado usado en `if`, asignado/retornado como `bool` y compuesto con
  lógica short-circuit;
- función `bool same(Status a, Status b) { return a == b; }`;
- enum importado y alias transparente al mismo enum;
- `Box<int>` payload-free comparado con la misma instancia;
- comparación de `Box<T>` con `Box<T>` dentro de body generic y sus instancias
  concretas, si el frontend ya admite esa declaración/aplicación;
- múltiples variantes y discriminantes no asumidos contiguos por el test;
- mismo resultado y estructura válida en O0/O2.

### Casos negativos source

- `A.X == B.X` y `A.X != B.X` con layout/variant spelling idénticos: `E0470`;
- `Box<int>` frente a `Box<double>`: `E0472`;
- enum frente a integer, bool, struct u otro valor: `E0472`;
- ordering y aritmética de enums: `E0472` o el diagnostic específico de
  operador incompatible sin construir HIR inválido;
- cualquier declaración con al menos un payload: `E0471`, incluidas variantes
  payload-free dentro de un enum mixto;
- `Status? == Status?` conserva el rechazo de igualdad nullable general;
- `Status? == null`, `null == Status?`, `!= null` continúan aceptados por
  NULLABLE-V1 y no producen diagnostics de enum equality;
- operands con error previo no generan cascada `E047x`.

### Corrupción HIR/MIR/SSA

Partiendo de una comparación válida, cada verifier debe rechazar mutaciones
independientes de:

- tipo del operand derecho a otro `EnumId`;
- tipo derecho a otra instancia del mismo `EnumId`;
- metadata/tipo a un enum payload-bearing;
- resultado de `bool` a enum u otro tipo;
- opcode a ordering/arithmetic conservando operands enum;
- trap o secondary trap agregado en MIR/SSA;
- `TypeId`, `EnumId`, type arguments o tabla de variantes inexistentes/no
  canónicos.

HIR debe fallar con `E0348`, MIR con `E0300` y SSA con `E0400`. Ninguna prueba
de corrupción debe llegar al backend.

### Regresión de numerical_methods

Debe existir una fixture exacta del caso encontrado:

```aether
enum Status {
    Ok,
    Error
}

int main() {
    Status status = Status.Ok;
    if (status == Status.Ok) {
        return 0;
    }
    return 1;
}
```

Además, la qualification debe usar los enums reales `Results.RootStatus` e
`Results.IntegrationStatus` del ejemplo, comparar un parámetro/local con una
variante qualified y comprobar la salida completa en O0/O2. Esto prueba el
camino package/import, no sólo una declaración local. Sustituir helpers `match`
del port por equality es una decisión del milestone de implementación; no se
modifica el ejemplo durante esta arquitectura.

## 16. Criterios de aceptación arquitectónica

ENUM-EQUALITY-ARCH-1 queda cerrado porque fija:

- la relación semántica y su dominio exacto;
- nominalidad, generic instances y ausencia de conversions;
- definición autoritativa de payload-free;
- representación y contratos HIR/MIR/SSA;
- lowering físico sin exposición source del discriminante;
- interacción con nullable, ownership y otras equalities;
- diagnostics y precedence;
- frontera explícita para payload enums futuros;
- matriz de qualification, corrupción, O0/O2 y regresión original.

No quedan decisiones abiertas que bloqueen ENUM-EQUALITY-V1. Igualdad de
payload enums, igualdad nullable general, una capability `Eq`, igualdad de
structs y user-defined operators son milestones posteriores.
