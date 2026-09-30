# IEEE-FLOAT-CONSTANTS-ARCH-1 — constantes del dominio IEEEFloat

Estado: **ARQUITECTURA CERRADA; NO IMPLEMENTADA**, 2026-09-30.

Este milestone es exclusivamente documental. No modifica compiler, Core,
runtime, standard library, `linearAlgebra`, tests ni manifests. El vertical de
implementación y qualification será `IEEE-FLOAT-CONSTANTS-V1` (§15).

Autoridad relacionada:

- [AETHER-V1-LANGUAGE-CHARTER](AETHER_V1_LANGUAGE_CHARTER.md);
- [AETHER-V1-SEMANTIC-CONTRACT](AETHER_V1_SEMANTIC_CONTRACT.md);
- [MODULE-STD-ARCH-1](MODULE_STD_ARCH_1.md);
- [NUMERIC-CAPABILITIES-V1](NUMERIC_CAPABILITIES_V1_REPORT.md);
- [LINEAR-ALGEBRA-SVD-ARCH-1](LINEAR_ALGEBRA_SVD_ARCH_1.md);
- [LINEAR-ALGEBRA-SVD-ARCH-1-REPORT](LINEAR_ALGEBRA_SVD_ARCH_1_REPORT.md).

## 1. Decisión resumida

Aether V1 agregará exactamente una operación pública:

```aether
T epsilon<T: IEEEFloat>();
```

Su uso normativo es explícito:

```aether
float32 e32 = epsilon<float32>();
float64 e64 = epsilon<float64>();

T threshold<T: IEEEFloat>() {
    T e = epsilon<T>();
    return e;
}
```

`epsilon` pertenece a **Core/prelude**. Está disponible desde source ordinario
de cualquier package, incluido `linearAlgebra`, sin import. Es una primitive
estándar compiler-known, pura y nullary cuya única selección es el type argument
explícito. No es una capability, associated member, global con storage, runtime
function ni operación especial de SVD.

No se agregan los aliases `machineEpsilon`, `eps` ni variantes por precisión.
La única grafía pública es `epsilon`.

## 2. Semántica exacta

Para un formato IEEE binario concreto `T`, `epsilon<T>()` es la distancia entre
`1` y el menor valor representable de `T` estrictamente mayor que `1`:

```text
epsilon(T) = nextUp_T(1_T) - 1_T
```

`nextUp` expresa aquí una definición matemática del formato. No implica una
call a `nextafter`, una operación libm ni una resta ejecutada en runtime.

El dominio y los resultados V1 quedan cerrados:

| `T` | valor matemático | payload IEEE del resultado |
|---|---:|---:|
| `float32` | `2^-23` | `0x34000000` |
| `float64` | `2^-52` | `0x3cb0000000000000` |

El resultado es exactamente normal, positivo y finito. La operación retorna
exactamente `T`; no promueve `float32` a `float64` ni depende del tipo por
defecto de los floating literals. Los aliases transparentes conservan su
identidad canónica: `epsilon<float>()` es el caso `float32` y
`epsilon<double>()` el caso `float64`.

Esta definición no es:

- el menor normal positivo (`2^-126` para binary32, `2^-1022` para binary64);
- el menor subnormal positivo (`2^-149` y `2^-1074` respectivamente);
- una tolerancia absoluta o relativa elegida por un algoritmo;
- el *unit roundoff*, que bajo round-to-nearest ties-to-even suele definirse
  como `epsilon/2`, es decir `2^-24` o `2^-53`.

Los algoritmos pueden usar epsilon para construir una tolerancia dependiente de
escala, pero Core no fija esa política.

## 3. Nombre y superficie descartada

Se elige `epsilon<T>()` porque es breve, convencional, consistente con la
notación ya adoptada por SVD y no atribuye al valor una policy algorítmica.
`machineEpsilon<T>()` es inequívoco pero innecesariamente largo; mantener ambos
crearía aliases sin diferencia semántica.

No se elige una propiedad o constante asociada a `IEEEFloat`. El sistema V1 de
capabilities no tiene associated values ni member lookup estático: sus
constraints prueban operaciones y el marker `IEEEFloat` es nominal, sellado y
sin witness. Introducir associated constants sólo para este valor abriría una
abstracción mucho mayor que la necesidad.

Tampoco se publican `float32Epsilon`/`float64Epsilon`, un argumento type-token,
una constante global genérica ni una forma `epsilon(T)`. Todas duplicarían la
selección que ya expresa el type argument y degradarían el source genérico.

## 4. Ubicación: Core/prelude

`epsilon` satisface la frontera de Core/prelude cerrada por
`MODULE-STD-ARCH-1`: es matemática escalar fundamental, pequeña, estable,
total y sin policy de dominio. Está conceptualmente junto a `abs` y `sqrt`, no
junto a una descomposición especializada.

Ubicarla bajo `std.Math` obligaría a importar una rama para una propiedad
básica del formato y haría que `linearAlgebra` dependiera de una API de std para
expresar el contrato de su propio binder. Ubicarla en `linearAlgebra` u OAL
invertiría la dependencia y permitiría copias divergentes. Por ello quedan
rechazadas esas tres ubicaciones.

Core/prelude es la autoridad pública, pero no se requiere un body source de
Core. La identidad estable se incorporará al manifest cerrado/versionado de
Core. Las reglas ordinarias de lookup, shadowing y profile siguen aplicando; no
se introduce reconocimiento textual fuera de la resolución de ese símbolo.

## 5. Typing e inferencia

La firma exige un único type argument que satisfaga `IEEEFloat` y no acepta
value arguments. El resultado tiene ese mismo `TypeId` canónico.

La forma requerida es:

```aether
T e = epsilon<T>();
```

La forma siguiente **no se admite en V1**:

```aether
T e = epsilon();
```

La inferencia genérica vigente unifica type parameters desde argumentos de la
call y no realiza return-context inference. Como `epsilon` no tiene argumentos,
no existe evidencia desde la que inferir `T`. No se crea una regla especial
basada en expected result, assignment, `return` o overload para epsilon. La call
sin type argument obtiene el diagnóstico general de type argument no inferible.

`epsilon<int32>()`, `epsilon<T>()` bajo un binder que sólo prueba `RealOps` y
cualquier otro tipo fuera del dominio se rechazan con los diagnostics generales
de constraint/marker sellado. Un caller `T: IEEEFloat` sí puede reenviar su
binder directamente.

## 6. No es una capability nueva

`NUMERIC-CAPABILITIES-V1` no se amplía. `Epsilon` no es una operación algebraica
que un tipo numérico arbitrario deba implementar y no habilita un operator. Es
un dato del formato dentro del dominio nominal ya probado por `IEEEFloat`.

Agregar una capability atómica produciría una promesa falsa de extensibilidad,
metadata de proof y posibles listas de constraints para un conjunto V1 que ya
está cerrado. La regla correcta es:

```text
la call epsilon<T>() es válida si y sólo si el contexto prueba T: IEEEFloat
```

Esta validación es análoga a otras firmas Core constrained, pero no agrega
`Epsilon` al lattice, aliases o tablas de satisfaction. No existen witnesses,
dictionaries, vtables, methods ni implementación por usuario.

## 7. Dominio sellado

En V1 `IEEEFloat` contiene exactamente los dos `TypeId` concretos de `float32`
y `float64`. Sólo una revisión explícita del lenguaje puede ampliar ese dominio
y deberá definir el epsilon exacto del formato nuevo antes de admitirlo.

El conjunto cerrado hace exhaustiva la sustitución compile-time. No se permite:

- branch runtime sobre `TypeId`;
- comparación de nombres de tipos o strings;
- tabla runtime indexada por tipo;
- witness, vtable o dictionary passing;
- fallback para tipos desconocidos;
- reconocimiento del nombre `svd` o del package consumidor.

## 8. HIR paramétrico y sustitución

La call resuelta en un body genérico se representa conceptualmente como un nodo
semántico tipado, por ejemplo:

```text
IEEEFloatConstant {
    kind: Epsilon,
    result_type: T,
    required_marker: IEEEFloat
}
```

El nombre es ilustrativo; el vertical puede integrarlo en la familia interna de
Core constants siempre que conserve esas tres facts y la verificación cerrada.
No debe modelarse como `AlgebraicValue`: `Zero` y `One` son identidades
algebraicas disponibles para dominios más amplios, mientras epsilon es una
propiedad específica del formato IEEE.

El verificador HIR paramétrico reconstruye desde `kind` el marker requerido,
comprueba que el binder lo garantice y que el result type sea exactamente ese
binder. No confía solamente en metadata creada por el analyzer.

Al instanciar, después de sustituir types y antes de publicar HIR concreto:

```text
epsilon<T>()
    T := float32  -> Float32(bits = 0x34000000)
    T := float64  -> Float64(bits = 0x3cb0000000000000)
```

La tabla de sustitución está centralizada junto a la semántica del símbolo Core,
no en callers. El verificador de HIR concreto rechaza cualquier
`IEEEFloatConstant` residual, type genérico o combinación de kind/type fuera de
la tabla.

## 9. Representación exacta

La representación normativa de implementación es un **constant node tipado con
payload de bits IEEE**. Se aprovecha el modelo existente que transporta
`Float32(u32 bits)` y `Float64(u64 bits)` desde HIR hacia lowering.

Los spellings hexadecimales matemáticos `0x1p-23` y `0x1p-52` describen bien el
valor, pero los hexadecimal floating literals no son source admitido hoy. No se
amplía el lexer ni el lenguaje literal para este milestone. Tampoco se calcula
el valor mediante divisiones, exponentiation, `nextafter(1,+inf)-1` ni parsing
de estas aproximaciones decimales:

```text
1.1920929e-7
2.220446049250313e-16
```

Una tabla compile-time de dos payloads no es la tabla runtime prohibida en §7.
Los bits son independientes del locale, parser decimal, precisión del host y
endianness de memoria. El backend recibe una constante float ya tipada; su
spelling textual LLVM puede variar sin cambiar el payload.

## 10. MIR, SSA, LLVM y constant folding

Después de monomorphization no queda una call:

```text
HIR concreto -> constante Float32/Float64
MIR          -> operand/rvalue constante existente
SSA          -> constante float existente
LLVM         -> constant float/double exacta
```

No se agrega opcode genérico a MIR/SSA ni intrinsic específico al backend. Sus
verificadores comprueban el tipo y payload como para cualquier otra constante.

Ésta no es una optimización de constant folding. La semántica de
monomorphization materializa directamente el valor; por ello O0 tampoco necesita
eliminar una call o plegar una expresión para satisfacer el contrato. Folding,
propagation o eliminación posterior son optimizaciones ordinarias y no cambian
el valor observable.

## 11. Runtime, efectos y ABI

`epsilon<T>()` es pura y total para todo `T` admitido. Su evaluación no:

- llama runtime, libm, FFI ni función de usuario;
- reserva, libera o consulta memoria;
- lee rounding mode, environment, locale o estado global;
- inicializa un global ni introduce orden de inicialización;
- lanza exception o produce trap;
- cambia ABI, calling convention o layout de ningún tipo.

Como no sobrevive una función concreta, no hay símbolo linkable de epsilon ni
dirección de función pública. Se mantiene la regla Core vigente de que estos
builtins no son first-class function values.

## 12. Floating point, rounding y O0/O2

La construcción directa por bits no ejecuta redondeo y produce el mismo valor
en todos los niveles normales de optimización. Qualification debe demostrar
payload idéntico en O0 y O2 para ambas precisiones. Ningún nivel habilita
fast-math, flush-to-zero o una constante aproximada.

La identidad:

```text
1 + epsilon > 1
```

se calificará para `float32` y `float64`. Tanto `1` como `epsilon` y su suma son
representables exactamente en esos casos.

No se usa como requisito normativo general:

```text
1 + epsilon/2 == 1
```

La suma está exactamente a mitad entre dos floats y la igualdad resulta cierta
bajo round-to-nearest ties-to-even, porque el significand de `1` es el vecino
par. Puede resultar falsa bajo rounding toward `+infinity`. El contrato vigente
mantiene abierta la observabilidad/control del ambient rounding mode, así que
este milestone no la cierra indirectamente. Un test de implementación puede
ejecutarla sólo si el harness fija y registra `FE_TONEAREST`; será evidencia del
entorno, no definición de epsilon ni requisito portable de source.

## 13. Diagnostics y corrupción

No se introducen diagnostics de SVD. La implementación reutilizará las
categorías generales:

| source/corrupción | resultado requerido |
|---|---|
| `epsilon()` | type argument no inferible |
| `epsilon<int32>()` | constraint `IEEEFloat` no satisfecha |
| `epsilon<T>()` con `T: RealOps` | caller no prueba el marker requerido |
| value arguments o más de un type argument | arity genérica/call inválida |
| nodo paramétrico sin guarantee | rechazo del verificador HIR paramétrico |
| nodo residual tras instantiation | rechazo del verificador HIR concreto |
| kind/type/payload incoherente | rechazo antes de MIR/backend |

Los mensajes pueden seguir el wording estructurado existente. No se agrega una
ruta especial que mencione `linearAlgebra`, tolerancias o deflation.

## 14. Qualification requerida

`IEEE-FLOAT-CONSTANTS-V1` deberá cubrir al menos:

1. resolución de la identidad Core/prelude única `epsilon` desde un package
   ordinario y desde el source de `linearAlgebra`;
2. calls explícitas `epsilon<float32>()`, `epsilon<float64>()` y forwarding
   `epsilon<T>()` dentro de `T: IEEEFloat`;
3. retorno exactamente `T`, incluidos los aliases transparentes `float` y
   `double`;
4. rechazo de inferencia nullary, tipos no IEEE y binders insuficientes;
5. HIR paramétrico con marker/result type auditables;
6. HIR concreto con payloads exactos `0x34000000` y
   `0x3cb0000000000000`, sin nodo simbólico residual;
7. MIR, SSA y LLVM sin generic types, call epsilon, runtime helper, TypeId
   branch, lookup table runtime, witness, vtable, boxing ni allocation;
8. inspección directa de bits en el harness/compiler y comparación contra los
   dos payloads normativos, sin usar decimal aproximado como oráculo;
9. ejecución nativa de `1 + epsilon > 1` para ambas precisiones en O0 y O2;
10. igualdad bitwise de los valores observados en O0/O2 y corruption tests para
    nodo residual, marker ausente y payload/type incoherente;
11. `cargo test --workspace`, formatting, clippy, differential suite y
    `git diff --check` según la qualification ordinaria del repositorio.

La inspección exacta puede hacerse en tests internos sobre `FloatValue`, dumps
HIR/MIR/SSA y constantes LLVM. No se agrega una API pública de bitcast sólo para
probar esta operación.

## 15. Secuencia de implementación

Un único vertical `IEEE-FLOAT-CONSTANTS-V1` implementará:

1. identidad y firma nullary genérica de `epsilon` en Core/prelude;
2. análisis de type arguments y constraint `IEEEFloat` sin inferencia nueva;
3. nodo HIR paramétrico y verificación independiente;
4. sustitución exhaustiva a los dos constant nodes tipados;
5. verificación concreta y lowering por infraestructura de constantes vigente;
6. qualification source, negativa, de IR, bits, O0/O2 y ausencia de runtime.

Ese vertical no modifica SVD. Una vez calificado, los milestones de SVD podrán
consumir `epsilon<T>()` como source ordinario sin reconocer su package ni
duplicar constantes.

## 16. Decisiones rechazadas y fuera de scope

| alternativa | decisión |
|---|---|
| `machineEpsilon<T>()` o alias adicional | rechazada; una sola grafía |
| associated constant de `IEEEFloat` | rechazada; no hay ese modelo en V1 |
| capability atómica `Epsilon` | rechazada; propiedad del dominio sellado |
| `std.Math.epsilon` | rechazada; matemática escalar básica de prelude |
| helper en `linearAlgebra`/OAL | rechazada; autoridad y dependencia erróneas |
| decimal aproximado | rechazado; no garantiza payload por construcción |
| cálculo runtime con `nextafter`/división | rechazado; trabajo y dependencia innecesarios |
| inferencia desde expected return | rechazada; no se agrega inferencia especial |
| branch/tabla runtime por tipo | rechazada; monomorphization es exhaustiva |

Quedan fuera de scope: `minNormal`, `minSubnormal`, máximos finitos, infinito,
NaN/payloads, radix, digits, exponent bounds, `nextafter`, `ulp(x)`, APIs de
rounding mode, traits implementables por usuario y formatos floating nuevos.
Cada incorporación futura deberá diseñar nombre, semántica y representación;
este milestone no reserva una familia pública completa bajo la palabra
“constants”.

