# GENERIC-LOCAL-INFERENCE-ARCH-1 — omitted root generic arguments in locals

Estado: **ARQUITECTURA CERRADA; NO IMPLEMENTADA**, 2026-09-21.

Este milestone define cómo omitir todos los argumentos de un constructor
generic en el tipo de una declaración local cuando el tipo final del
initializer determina una única aplicación exacta. No modifica lexer, parser,
AST, HIR, MIR, SSA, backend, runtime, tests ni la superficie source actualmente
admitida. La implementación pertenece a **GENERIC-LOCAL-INFERENCE-V1**.

```aether
Matrix<double> a = makeMatrix();
QR qr = la.qr(a);              // qr: QR<double>
List values = makeValues();    // values: List<int>
Pair pair = makePair();        // pair: Pair<int, string>
```

La declaración escrita fija el constructor. Sólo se recupera su lista completa
de argumentos desde el `TypeId` ya resuelto del RHS. Esto no es `var`, no crea
raw generics y no agrega inferencia desde la sintaxis interna de una expresión.

## 1. Decisiones resumidas

- La única nueva forma admitida es un constructor generic sin argumentos en el
  tipo root de un local que tiene initializer obligatorio.
- Se omiten **todos** los argumentos del constructor elegible. No existe `_`,
  `<>`, omisión parcial ni búsqueda de argumentos individuales.
- El AST conserva el spelling ordinario `AstTypeKind::Named { arguments: [] }`.
  La declaración y el contexto deciden si significa un tipo no generic completo
  o un patrón local. No se agrega sintaxis ni un tipo semántico raw.
- Resolución produce un `LocalTypePattern` efímero, separado de `TypeArena`.
  Nunca se interna un hole ni una aplicación generic incompleta.
- El initializer se tipa primero sin expected type proveniente del patrón. Su
  `TypeId` final debe estar completamente formado.
- El constructor escrito y el del RHS deben tener la misma identidad exacta.
  Para structs/enums esto significa el mismo `StructId`/`EnumId`; para
  constructores intrínsecos, el mismo discriminante y parámetros no generic.
- El tipo del binding es exactamente el `TypeId` del RHS que hizo match. La
  ruta de inferencia no ejecuta conversiones, upcasts, nullable injection,
  borrow adaptation ni selección de overloads.
- `T?` puede envolver el único constructor root omitido: `Box? b = rhs` requiere
  que `rhs` ya tenga exactamente `Box<X>?`. References quedan fuera de V1.
- No se permite omisión dentro de argumentos: `List<Box>`,
  `Map<string, List>` y `Pair<int, Box>` continúan siendo errores de aridad.
- Parámetros, returns, fields, aliases, signatures, enum payloads y todo local
  sin initializer continúan exigiendo argumentos explícitos.
- HIR recibe sólo el `TypeId` final. MIR, SSA, mangling, layout, ABI, ownership y
  monomorfización no conocen la inferencia ni cambian su representación.

## 2. Superficie y gramática

No se cambia la gramática de tipos. La forma canónica es:

```aether
QR qr = expression;
List xs = expression;
Pair p = expression;
```

No se admite `QR<>`. `QR<T>` continúa siendo la forma explícita y `QR` fuera
del contexto local cerrado continúa produciendo el error de aridad existente.
El parser ya representa `QR` como un named type con cero argumentos; no debe
decidir si la declaración es válida ni consultar símbolos.

Conceptualmente, sólo este contexto semántico habilita el patrón:

```ebnf
inferable-local = binding-modifier?, local-type-pattern,
                  identifier, "=", expression ;
```

`const QR qr = expression;` usa la misma regla: const afecta al binding, no a
la inferencia. El initializer obligatorio existente hace que no haya estado
declarado pero todavía indeterminado.

No se introduce `var`. En `QR q = rhs`, `QR` es evidencia y restringe el
resultado; una futura `var q = rhs` inferiría el tipo completo sin esa
restricción y requiere un milestone independiente.

## 3. Constructores elegibles

V1 admite:

1. structs generic declarados, identificados por `StructId`;
2. enums generic declarados, identificados por `EnumId`;
3. constructores generic intrínsecos que ya tienen spelling source, incluido
   `List`, y los demás constructores de colección/matemáticos admitidos por el
   frontend (`Array`, `Buffer`, `View`, `ViewMut`, `Matrix`, `MatrixView`,
   `MatrixViewMut`, `Vector`, `VectorView` y `VectorViewMut`).

La tercera categoría se incluye porque estos tipos son aplicaciones canónicas
en el lenguaje aunque `TypeData` use variantes estructurales dedicadas. Cada
una tiene una `GenericFamilyKey` cerrada; no se equiparan entre sí. En `Vector`
se infieren tanto element type como orientation, pero el RHS todavía debe ser
exactamente `Vector<E, O>`, no un view ni una matriz.

Un constructor no generic con cero argumentos se resuelve normalmente y no
activa inferencia. Un nombre generic con argumentos explícitos también sigue la
ruta ordinaria. Interfaces y classes actuales no son generic; si una versión
posterior los admite, no entran automáticamente: el conjunto elegible debe
ampliarse deliberadamente junto con sus reglas de ownership y aplicación.

Aliases no son familias inferibles. Un alias transparente sin parámetros se
resuelve normalmente al tipo completo que ya nombra. V1 no introduce aliases
generic ni permite usar un alias para ocultar un constructor incompleto.

Name lookup, imports, visibilidad y shadowing ocurren antes de clasificar el
nombre como patrón. No se buscan todas las declaraciones llamadas `QR`, no se
prueban familias alternativas y no se usa el RHS para reparar un nombre
desconocido o ambiguo.

## 4. Representación temporal del patrón

`TypeId` significa siempre un tipo semántico completo. Por tanto no se agregan
`TypeData::RawGeneric`, `Unknown`, `InferenceVar` ni argumentos sentinel al
`TypeArena`. El resolver local usa una representación privada conceptual:

```text
LocalTypeExpectation =
    Exact(TypeId)
  | InferRoot(LocalTypePattern)

LocalTypePattern {
    family: GenericFamilyKey,
    nullable: bool,
    source_span: Span,
    name_span: Span,
    expected_arity: usize,
}

GenericFamilyKey =
    Struct(StructId)
  | Enum(EnumId)
  | Intrinsic(IntrinsicGenericConstructor, fixed_parameters)
```

`fixed_parameters` conserva únicamente identidad que no sea un argumento
omitible del spelling. En los constructores actuales normalmente está vacío;
la orientación de `Vector` sí es un argumento y se obtiene del RHS.

El patrón no implementa igualdad general de tipos, no puede almacenarse en una
signature y no cruza la llamada que baja el statement local. Su existencia se
limita al intervalo entre resolver el tipo source y publicar `HirLocal`.

Invariantes:

- `TypeArena` contiene únicamente aplicaciones completas y canónicas;
- un `LocalTypePattern` siempre denota una familia ya resuelta, visible y con
  aridad mayor que cero;
- como máximo hay un constructor omitido y éste está en la posición aprobada;
- todo `HirLocal.ty` coincide exactamente con `initializer.ty` al terminar el
  lowering del statement.

## 5. Clasificación contextual del tipo source

La resolución general `resolve_type_in_module` debe conservar su contrato:
todo named generic con aridad incorrecta falla. V1 agrega una entrada específica
para tipos de locals, conceptualmente `resolve_local_type_expectation`, que:

1. inspecciona la forma exterior permitida;
2. ejecuta name lookup normal y determina la declaración/familia;
3. si hay argumentos, llama al resolver ordinario y devuelve `Exact`;
4. si no hay argumentos y la aridad es cero, resuelve normalmente a `Exact`;
5. si no hay argumentos, la aridad es mayor que cero y el constructor ocupa la
   posición aprobada, devuelve `InferRoot`;
6. en cualquier otra posición deja actuar al error de aridad ordinario.

Esto evita añadir un booleano permisivo al resolver recursivo. Un modo global
como `allow_missing_generics` aceptaría accidentalmente holes en fields,
signatures o argumentos nested.

### 5.1 Nullable

V1 admite una sola envoltura nullable sobre el constructor omitido:

```aether
Box? value = makeNullableBox(); // RHS: Box<int>?
List? values = maybeValues();   // RHS: List<string>?
```

La forma temporal es `nullable: true` más `family: Box/List`; no se intenta
internar `Nullable(Box<?>)`. Deben mantenerse las restricciones nullable
ordinarias (`void?`, nullable nested, admisión del payload). El RHS debe ser ya
nullable. `Box? value = makeBox()` no usa la coerción `Box<int> -> Box<int>?`
para descubrir argumentos y falla por shape externo distinto. El usuario puede
escribir `Box<int>?` cuando quiera esa conversión ordinaria.

Esta decisión conserva la regla de inferir desde el tipo resultante real del
RHS y evita que una conversión dependiente del expected type fabrique la
evidencia que pretende justificar ese mismo expected type.

### 5.2 References

`ref Box b`, `ref mut Box b`, `(ref Box)? b` y cualquier omisión debajo de una
reference se rechazan en V1 con diagnóstico de contexto no soportado. Aunque el
RHS pudiera tener `ref Box<int>`, admitirlo exige cerrar por separado
provenance, lifetime, mutable capability, materialización y la interacción con
borrow ergonomics. No se reinterpretan como root nominal locals.

Los tipos reference completamente explícitos no cambian:

```aether
ref Box<int> b = expression;
(ref Box<int>)? maybe = expression;
```

### 5.3 Omission nested

El walker sólo reconoce `Named(generic, [])` directamente o como payload
directo de un único `Nullable`. No desciende por argumentos de tipos:

```aether
List<Box> xs = expression;         // error
Map<string, List> map = expression; // error
Pair<int, Box> pair = expression;   // error
Function<(Box), int> f = expression;// error
```

Tampoco mezcla argumentos escritos y omitidos. `Pair<int>`, `Pair<, string>`,
`Pair<int, _>` y `Pair<>` no son spellings alternativos.

## 6. Algoritmo de typing y matching

Para `P name = initializer`, donde P clasifica como `InferRoot`, el orden es
normativo:

1. Resolver P a una identidad de familia, nunca a un `TypeId` incompleto.
2. Tipar `initializer` con `expected = None`. Calls completan su resolución e
   inferencia generic usando únicamente su callee, type arguments explícitos y
   argumentos; P no selecciona callable ni completa generics de la call.
3. Obtener el `TypeId R` final de la expresión después de las reglas internas
   que no dependen de P. R debe ser un tipo formado y almacenable.
4. Descomponer R en `outer shape`, `GenericFamilyKey` y lista completa de
   argumentos. Si P es nullable, primero exigir `R = Nullable(Q)` y descomponer
   Q. Si P no es nullable, descomponer R directamente.
5. Exigir igualdad exacta de `GenericFamilyKey` y aridad declarada.
6. Validar que la aplicación de R es canónica, que cada argumento está formado
   y que satisface todas las reglas de admisión/constraints que se aplicarían a
   un spelling explícito equivalente.
7. Adoptar `R` sin reconstrucción ni conversión como tipo del local; bajar el
   initializer ya tipado y publicar simultáneamente `HirLocal { ty: R }` y
   `HirStmtKind::Local`.

Ejemplo:

```text
type(la.qr(a), expected=None) -> QR<double>
pattern                       -> family Struct(QR), nullable=false, arity=1
decompose RHS                 -> family Struct(QR), args=[double]
binding                       -> existing canonical TypeId QR<double>
```

No hay unification recursiva general: como se omiten todos los argumentos root,
la lista se copia de una aplicación RHS de la misma familia. “Unify” describe
el match de constructor, no un solver de variables o constraints.

## 7. Qué significa completo

“Completo” significa que no hay holes de inferencia ni aplicaciones de aridad
incorrecta. En el body paramétrico de una función generic, un argumento puede
ser un `TypeData::GenericParam` legítimo:

```aether
T first<T>(Box<T> input) {
    Box copy = forward(input); // copy: Box<T>
    ...
}
```

`Box<T>` es un tipo HIR bien formado, no un raw `Box`. La sustitución y
monomorfización existentes lo convierten después en cada instancia concreta.
Si el RHS conserva una variable de inferencia privada sin resolver, typing debe
fallar antes de construir HIR; esa variable nunca se convierte en argumento del
binding.

Los literals contextuales que carecen de tipo autónomo no reciben ayuda del
patrón. En particular, `Box b = null` falla: `null` no produce `Box<X>` ni
determina X. Lo mismo aplica a una call generic cuyo resultado sólo podría
inferirse desde expected return type.

## 8. Exactitud nominal y conversiones

El match compara identidad semántica, no spelling, layout ni convertibilidad:

```aether
Box x = makeOtherBox();       // OtherBox<int>: error
BaseBox x = makeDerivedBox(); // error aunque exista upcast
List x = makeArray();         // error aunque elementos coincidan
Matrix x = makeView();        // error
```

Aliases transparentes del RHS ya están normalizados a su `TypeId`; pueden hacer
match con la familia canónica escrita. Dos declaraciones nominales con fields y
layout iguales no coinciden.

La ruta inferida no aplica conversiones después del match porque el binding
adopta exactamente R. Esto cierra el punto sin introducir casos inútiles: una
conversión que cambia la familia sería no nominal; una que conserva exactamente
familia y argumentos es identidad. Numeric widening, class/interface
adaptation, nullable injection y borrow adaptation siguen disponibles sólo
cuando el tipo esperado completo fue escrito explícitamente y las reglas
ordinarias las permiten.

## 9. Calls, overloads y evaluación

El patrón no fluye como expected result hacia el initializer. Por ello:

- no elige entre overloads por return type;
- no infiere parámetros generic presentes sólo en el resultado;
- no especializa una regla para `la.qr(A)` ni inspecciona que A sea Matrix;
- no cambia prioridad de candidatos ni diagnósticos de ambigüedad;
- no cambia orden, cantidad de evaluaciones, side effects, traps o unwind.

El initializer se evalúa exactamente una vez y el binding sólo se publica si
termina normalmente, igual que un local explícito actual. Si una call no puede
resolverse sin expected return type, la declaración falla aunque una familia
escrita parezca compatible. Una versión futura puede diseñar inferencia
bidireccional por separado sin alterar este contrato V1.

## 10. Ownership, lifecycle y mutabilidad

La feature sólo elige un `TypeId`; no crea una operación de valor. Una vez
elegido R se aplican sin cambios sus propiedades:

- Copy se copia y owners non-Copy se transfieren según el initializer real;
- const/mutable continúa siendo metadata del binding;
- Drop, unwind, definite initialization y moved-state usan R;
- no se inserta Clone, Alias/retain, allocation, boxing ni temporary adicional;
- references o views que el RHS ya contiene como argumentos generic conservan
  sus reglas ordinarias; sólo la envoltura `ref Box` omitida está fuera.

Inferir `List<int>` debe generar exactamente los mismos eventos de lifecycle y
el mismo HIR de valor que escribir `List<int>` explícitamente.

## 11. HIR, MIR, SSA, ABI y dumps

No se agrega un nodo HIR de inferencia. Al salir del frontend:

```text
HirLocal.ty == HirStmtKind::Local.initializer.ty == inferred TypeId
```

El verificador HIR ya exige igualdad entre local e initializer y debe añadir o
mantener un rechazo explícito para cualquier aplicación malformed, unknown o
no canonical. Los generic parameters de un body generic son válidos; los holes
del resolver no lo son porque carecen de `TypeData`.

MIR y SSA copian el `TypeId` concreto exactamente como para el spelling
explícito. Sus verificadores no necesitan saber si el source omitió argumentos,
pero deben seguir comprobando igualdad de locals/operands, tipos conocidos,
substitution completa y lifecycle. Un corruption test que intente introducir
un tipo base generic sin argumentos debe ser irrepresentable o rechazado en la
frontera HIR.

Layout, ABI, mangling, `InstanceId`, monomorfización y codegen dependen sólo del
tipo final. Dos programas que difieren únicamente entre `Box b = rhs` y
`Box<int> b = rhs`, con RHS `Box<int>`, deben producir HIR semánticamente
equivalente y MIR/SSA/LLVM idénticos salvo spans o spelling de dump puramente
source.

Los dumps tipados muestran el tipo final (`Box<int>`), nunca `Box`, `Box<?>` ni
una variable de inferencia. Si se conserva provenance para tooling, debe ser
metadata frontend no normativa y no participar en identidad o codegen.

## 12. Diagnósticos

Se reserva la familia `E0460..E0464` para este vertical, sujeta al registro
central al implementar:

| Código | Condición | Mensaje base | Span principal |
| --- | --- | --- | --- |
| `E0460 generic_local_family_mismatch` | familia RHS distinta | ``local type pattern `Box` requires `Box<...>`, but initializer has `Other<int>` `` | tipo local; nota en initializer |
| `E0461 generic_local_rhs_not_application` | RHS no es aplicación generic elegible | ``local type pattern `Box` cannot be inferred from initializer type `int` `` | initializer |
| `E0462 generic_local_rhs_undetermined` | RHS no obtiene tipo completo sin expected | ``initializer does not determine all arguments of `Box` `` | initializer; nota en tipo local |
| `E0463 generic_local_omission_context` | reference, nested u otro contexto fuera de V1 | ``generic arguments may be omitted only for the root local constructor (optionally nullable)`` | constructor omitido |
| `E0464 generic_local_shape_mismatch` | nullable exterior distinto u aridad/canonicalidad corrupta | ``initializer type does not have the required local type shape `Box?<...>` `` | initializer |

Un nombre desconocido, import ausente, visibilidad, argumentos explícitos con
aridad incorrecta, constraint/admission violation y error interno del RHS
conservan sus diagnósticos existentes. `Box b = null` debe priorizar el error de
typing contextual de `null`/RHS indeterminado, con una nota que el patrón local
no proporciona argumentos.

Los mensajes imprimen el nombre source resuelto y el tipo RHS concreto. No
imprimen `<?>` como sintaxis válida ni sugieren `Box<>`.

## 13. Contextos expresamente fuera de V1

Continúan requiriendo argumentos completos:

```aether
QR q;                    // además, local sin initializer no admitido
QR make();               // return
void consume(QR q);      // parameter
struct Holder { QR q; }  // field
enum E { Item(QR) }      // payload
type Alias = QR;         // alias target
List<Box> xs = rhs;      // nested omission
ref Box b = rhs;         // reference wrapper
```

También quedan fuera `var`, `_` type placeholders, partial/turbofish omission,
default generic arguments, inference from assignments posteriores, inference
from destructuring, iteration/catch/pattern bindings, expected-return typing,
generic aliases, overload search by result and conversion-driven family match.

## 14. Plan del primer vertical

**GENERIC-LOCAL-INFERENCE-V1 — exact root constructor adoption** debe
implementarse fail-closed en este orden:

1. introducir la clasificación frontend `Exact | InferRoot`, privada al local;
2. resolver familias nominales e intrínsecas con lookup/visibilidad ordinarios;
3. tipar el RHS sin expected type y extraer la aplicación exacta;
4. adoptar su `TypeId`, validar admission/constraints y construir HIR normal;
5. admitir la única envoltura nullable y rechazar references/nesting;
6. agregar diagnósticos estables y dumps con tipo final;
7. reforzar verificadores para que ningún tipo incompleto cruce HIR;
8. demostrar equivalencia explícito/inferido hasta LLVM en O0 y O2.

La qualification mínima incluye:

- struct y enum de uno y varios argumentos, local mutable y const;
- `List`, `Array`, `Matrix` y `Vector` con orientación;
- funciones generic donde el RHS produce `Box<T>` bien formado;
- nullable exacto `Box<X>?` y rechazo de inyección `Box<X> -> Box<X>?`;
- familia distinta, RHS escalar, `null`, call result indeterminado;
- omissions nested, partial, references y todos los contextos no locales;
- imports/visibilidad/aliases, constraints y element admission;
- Copy, owning, Drop, move, unwind y initializer con side effects;
- paridad de HIR typing y equivalencia MIR/SSA/LLVM frente al spelling explícito;
- corruption tests de HIR/MIR/SSA y no regresión del error de aridad general.

## 15. Criterios de aceptación

El vertical queda completo sólo si:

1. `QR q = rhs` acepta exactamente cuando RHS determina `QR<A...>` de la misma
   familia y el binding obtiene ese mismo `TypeId`;
2. no existe raw generic ni hole en `TypeArena`, HIR, MIR o SSA;
3. el patrón no influye en resolución del RHS ni habilita conversiones;
4. nullable sigue la forma exacta definida y references fallan cerradamente;
5. toda omisión nested o fuera de local conserva/reemplaza por un diagnóstico
   específico sin ser aceptada accidentalmente;
6. explicit e inferred spellings tienen comportamiento, lifecycle, ABI y
   codegen equivalentes;
7. la suite completa previa permanece verde en O0/O2.

## 16. Trabajo posterior separado

Requieren nuevos diseños: inferencia dentro de references, generic classes e
interfaces, omissions nested/partial, generic aliases, default type arguments,
`var`, expected-return inference, destructuring/pattern bindings y extensión a
fields/parameters/returns. Ninguno queda implícitamente autorizado por V1.

