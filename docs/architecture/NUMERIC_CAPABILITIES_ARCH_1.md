# NUMERIC-CAPABILITIES-ARCH-1 — capabilities numéricas estáticas

Estado: **ARQUITECTURA CERRADA; NO IMPLEMENTADA**, 2026-09-28.

Este milestone define cómo completar las capabilities numéricas de
`compiler-next` y cómo usarlas posteriormente para deduplicar
`linearAlgebra`. No modifica el compilador, `linearAlgebra`, el runtime ni los
tests. Este documento normativo y su
[reporte de cierre](NUMERIC_CAPABILITIES_ARCH_1_REPORT.md) son los únicos
entregables de `NUMERIC-CAPABILITIES-ARCH-1`.

Autoridad relacionada:

- [MATH-ARCH-1](MATH_ARCH_1_REPORT.md);
- [CONTEXTUAL-OVERLOADS-V1](CONTEXTUAL_OVERLOADS_V1_REPORT.md);
- [LINEAR-ALGEBRA-CONSTRUCTORS-V1](LINEAR_ALGEBRA_CONSTRUCTORS_V1_REPORT.md);
- [LINEAR-ALGEBRA-LU-V1](LINEAR_ALGEBRA_LU_V1_REPORT.md);
- [LINEAR-ALGEBRA-SOLVE-V1](LINEAR_ALGEBRA_SOLVE_V1_REPORT.md);
- [LINEAR-ALGEBRA-SOLVE-MATRIX-V1](LINEAR_ALGEBRA_SOLVE_MATRIX_V1_REPORT.md);
- [LINEAR-ALGEBRA-DET-V1](LINEAR_ALGEBRA_DET_V1_REPORT.md);
- [LINEAR-ALGEBRA-OAL-V1-QR](LINEAR_ALGEBRA_OAL_V1_QR_REPORT.md).

## 1. Decisión resumida

La solución extiende la infraestructura cerrada de capabilities que ya existe.
No introduce traits, interfaces, diccionarios, witnesses ni operator lookup en
runtime.

Las capabilities primitivas numéricas V1 serán:

```text
Zero  One
Add   Sub   Mul   Div   Negate
Equal Order
Abs   Sqrt
```

`Add`, `Sub`, `Mul` y `Zero` ya existen. Los demás nombres completan la misma
representación, resolución y reificación.

Tres nombres compuestos, puramente compile-time, mantienen legibles las firmas:

```text
RingOps  = Zero + One + Add + Sub + Mul + Negate + Equal
FieldOps = RingOps + Div
RealOps  = FieldOps + Order + Abs + Sqrt
```

Los sufijos `Ops` son deliberados: prueban disponibilidad y semántica de
operaciones, no axiomas formales como asociatividad, distributividad o
reflexividad. Esto evita afirmar que IEEE 754, con redondeo y NaN, sea un campo
matemático exacto.

`IEEEFloat` es una capability nominal, sellada y compiler-known que inicialmente
satisfacen exactamente `float32` y `float64`. Implica:

```text
RealOps + Copy + Relocatable + Storable
```

pero la implicación inversa no existe: reunir las operaciones de `RealOps` no
prueba semántica IEEE. Los kernels actuales de LU, solve, det y QR se migrarán
con `T: IEEEFloat`, aunque alguno use menos operaciones, porque sus contratos
observables son específicamente IEEE.

Las capabilities sólo prueban el HIR paramétrico. Cada aplicación concreta se
monomorfiza y reifica a los mismos opcodes y Core calls que hoy usan los cuerpos
`float32`/`float64`. MIR, SSA, LLVM y ABI no llevan capabilities ni witnesses.

## 2. Auditoría del sistema actual

### 2.1 Parsing, identidad y metadata

El parser ya acepta listas de identifiers en un binder como:

```aether
T f<T: Storable + Copy + Add>(T x);
```

`AstGenericParam` conserva nombre, constraints y spans. El frontend asigna a
cada binder un `GenericParamId { owner, index }`; el spelling no es identidad.
`TypeData::GenericParam` participa en tipos de parámetros, retorno, aggregates,
collections y tipos matemáticos.

La lista aceptada no es abierta. `collect_generic_parameters` traduce spellings
a `Capability`; hoy reconoce:

```text
Copy, Relocatable, Storable, Add, Sub, Mul, Zero
```

Un nombre desconocido produce `E0314`, un duplicado `E0315`. La arena conserva
por binder el conjunto de guarantees y el nombre para diagnostics.

### 2.2 Capabilities estructurales

`Copy`, `Relocatable` y `Storable` describen representación/ownership, no
aritmética. La única implicación general actual es:

```text
Copy -> Relocatable
```

`Storable` admite el tipo como elemento persistente de `Matrix<T>` y
`Vector<T,O>`; `Copy` permite leer un elemento escalar sin moverlo; y
`Relocatable` controla traslados de storage. Ninguna de ellas autoriza `+`, `/`
o una función matemática. Esa separación se preserva.

### 2.3 Capabilities numéricas que ya existen

El compilador distingue:

- `BehavioralCapability::{Add, Sub, Mul}` para contratos homogéneos
  `T op T -> T`;
- `AlgebraicCapability::Zero` para el valor canónico de `T`;
- propiedades estructurales, en un namespace semántico distinto.

Los tipos enteros y floats concretos satisfacen actualmente `Add`, `Sub`, `Mul`
y `Zero`. Los aggregates no heredan comportamiento numérico de sus fields.
Los tipos definidos por el usuario no pueden declarar implementations: la
vocabulary y la tabla de satisfacción son cerradas.

En un cuerpo genérico, `a + b`, `a - b` y `a * b` sólo son legales cuando ambos
operandos son el mismo parámetro `T` y su binder garantiza la capability
correspondiente. El HIR retiene un `CapabilityBinary { behavior, ... }`. El
verificador paramétrico vuelve a probar homogeneidad y guarantee.

`Zero` ya tiene una representación HIR independiente:
`AlgebraicValue { Zero }`. Se utiliza internamente en productos
Matrix/Vector. Durante sustitución se vuelve `Int(0)` o el `FloatValue(0)` de la
precisión concreta.

### 2.4 Lo que todavía no puede expresarse

Hoy no existen constraints para:

- `/`;
- unary `-`;
- `==`/`!=` sobre `T`;
- `<`, `<=`, `>` o `>=` sobre `T`;
- el valor uno;
- `abs(T)` o `sqrt(T)`.

En consecuencia, el analizador rechaza esas operaciones sobre
`TypeData::GenericParam`, aunque una futura instanciación fuese `float32` o
`float64`.

Los literales contextuales actuales se seleccionan directamente como un tipo
concreto integer/float; no son casts runtime. Sin embargo, si el expected type
es un parámetro `T`, `integer()` y `float()` no encuentran una clasificación
concreta y rechazan el literal. `Zero` sólo se materializa hoy dentro de recetas
algebraicas internas; aún no habilita `T x = 0` en source. `One` no existe.

`abs` y `sqrt` son Core/prelude functions cerradas. `abs` admite enteros signed
y floats concretos; `sqrt`, sólo `float32`/`float64`. `core_call` clasifica un
`TypeId` concreto y no acepta un parámetro genérico aun si tuviera otras
capabilities.

### 2.5 Resolución, inferencia y monomorfización existentes

La resolución de llamadas genéricas ya:

1. unifica primero el retorno con el expected result type, si existe;
2. infiere después desde argumentos de izquierda a derecha;
3. valida constraints antes de asignar/cachear una instancia;
4. conserva la declaración como HIR paramétrico verificado;
5. crea una `InstanceId` por `(FunctionId, type arguments)`;
6. sustituye cada tipo y operación simbólica por una operación concreta.

`CapabilityBinary` está prohibido en HIR concreto. MIR rechaza tipos genéricos
sin resolver y sólo contiene `AddFloat`, `SubtractFloat`, `MultiplyFloat`, los
opcodes checked integer u operaciones concretas equivalentes. SSA vuelve a
verificar contratos tipados y el backend sólo recibe scalar types concretos.

Los símbolos LLVM incorporan el disambiguador de overload y, para una instancia
genérica, el mangling de todos sus type arguments. Por tanto `foo<float32>` y
`foo<float64>` ya tienen identidad, cuerpo y símbolo distintos.

### 2.6 Conclusión de la auditoría

La ruta correcta es ampliar `Capability`, sus tablas de satisfacción, el HIR
simbólico y la reificación existente. Un sistema paralelo de traits o una API
especial de `linearAlgebra` duplicaría mecanismos y rompería el límite entre
package ordinario y compilador.

## 3. Semántica de las capabilities primitivas

| capability | garantía source | resultado | built-ins iniciales | extensible por user types en V1 |
|---|---|---|---|---|
| `Zero` | valor canónico `0` | `T` | todos los integers y floats | no |
| `One` | valor canónico `1` | `T` | todos los integers y floats | no |
| `Add` | `T + T` | `T` | todos los integers y floats | no |
| `Sub` | `T - T` | `T` | todos los integers y floats | no |
| `Mul` | `T * T` | `T` | todos los integers y floats | no |
| `Div` | `T / T` con división fraccional | `T` | `float32`, `float64` | no |
| `Negate` | `-T` | `T` | signed integers y floats | no |
| `Equal` | `T == T`, `T != T` | `bool` | todos los integers y floats | no |
| `Order` | `<`, `<=`, `>`, `>=` | `bool` | todos los integers y floats | no |
| `Abs` | `abs(T)` | `T` en V1 | signed integers y floats | no |
| `Sqrt` | `sqrt(T)` | `T` en V1 | `float32`, `float64` | no |

`Div` genérico excluye inicialmente integers. La `/` concreta integer sigue
existiendo con su contrato checked actual, pero no se presenta como división
fraccional paramétrica. Esto impide que `FieldOps` admita accidentalmente
truncamiento.

`Equal` sólo promete los operadores y la semántica propia del tipo. No promete
una relación de equivalencia: sobre floats, NaN conserva la comparación IEEE no
reflexiva. `Order` tampoco promete orden total; sobre floats conserva unordered
NaN. El nombre evita `Ord`, que sugeriría total order y bloquearía la semántica
actual.

`Abs` y `Sqrt` son independientes. Un algoritmo que sólo necesita magnitud no
adquiere raíz cuadrada, y uno que sólo necesita raíz no adquiere funciones
trascendentales. `sin`, `cos`, `tan`, `exp` y `ln` no forman parte de este
milestone ni son implicadas por `RealOps` o `IEEEFloat`.

### 3.1 Operaciones, no leyes demostradas

El compilador prueba que existe una operación con semántica definida y lowering
concreto. No prueba leyes algebraicas. En particular:

- `Add` no prueba asociatividad;
- `FieldOps` no prueba inversos para todo valor ni aritmética exacta;
- `Equal` no prueba reflexividad;
- `Order` no prueba totalidad;
- ningún alias autoriza reassociation, fast-math o eliminación de checks.

Los nombres compuestos terminan en `Ops` para hacer explícito este límite.

## 4. Composiciones y `IEEEFloat`

### 4.1 Aliases compile-time

`RingOps`, `FieldOps` y `RealOps` son aliases del lenguaje para conjuntos de
capabilities, no traits nominales, tipos ni witnesses. En source:

```aether
T polynomial<T: RingOps>(T x) { ... }
T ratio<T: FieldOps>(T a, T b) { ... }
T normStep<T: RealOps>(T x) { ... }
```

equivale, para verificación, a escribir sus primitivas. La metadata semántica
debe conservar el spelling declarado para diagnostics y almacenar también su
cierre normalizado. Duplicaciones directas o vía alias se diagnostican; por
ejemplo `T: RingOps + Add` repite `Add`.

No se agregan aliases para cada combinación posible. Los tres niveles cubren
constructores/polinomios, división y algoritmos reales. Firmas que necesitan
menos expresan las primitivas exactas.

| composición | built-ins que satisfacen el conjunto inicialmente | forma/estatus | user types |
|---|---|---|---|
| `RingOps` | signed integers, `float32`, `float64` | alias abierto de atoms | no en V1; extensible cuando existan implementations estáticas |
| `FieldOps` | `float32`, `float64` | alias abierto de `RingOps + Div` | no en V1; Rational/Complex futuros podrían satisfacerlo |
| `RealOps` | `float32`, `float64` | alias abierto de `FieldOps + Order + Abs + Sqrt` | no en V1; un real futuro podría satisfacerlo sin volverse IEEE |
| `IEEEFloat` | exactamente `float32`, `float64` | marker nominal sealed/compiler-known | no; sólo una revisión del lenguaje amplía el conjunto |

Los unsigned integers pueden satisfacer atoms como `Zero`, `One`, `Add`,
`Sub`, `Mul`, `Equal` y `Order`, pero no `RingOps` porque no satisfacen
`Negate`. La tabla concreta de cada primitive está en la sección anterior.

### 4.2 Capability nominal sellada

`IEEEFloat` no es un alias. Es un marker nominal que sólo el compilador puede
satisfacer y que implica el cierre de `RealOps`, `Copy`, `Relocatable` y
`Storable`.

Inicialmente:

| tipo | `RealOps` | `IEEEFloat` |
|---|---:|---:|
| `float32` | sí | sí |
| `float64` | sí | sí |
| integers | no | no |
| tipos definidos por usuarios | no | no |
| futuro `Decimal`/`Rational`/`BigFloat` | según sus operaciones futuras | no por defecto |
| futuro `Complex<T>` | no, porque no tiene `Order` ni `Sqrt: T -> T` con el contrato real | no |

`T: RealOps` jamás satisface una callee que exige `T: IEEEFloat`. Sólo el marker
nominal prueba:

- formatos binarios `float32`/`float64` del lenguaje;
- `+0.0` y `-0.0`, NaN, infinities y subnormals conforme a los contratos
  concretos vigentes;
- comparaciones, división, `abs` y `sqrt` exactamente por las rutas Core/LLVM
  existentes;
- ausencia de traps integer y de coerciones numéricas escondidas.

No se fija en esta arquitectura un modo fast-math nuevo. La monomorfización
hereda los mismos flags y opcodes concretos que el código escrito directamente.

### 4.3 Representación recomendada

`Capability` sigue siendo la vocabulary cerrada. Se agregan los atoms y el
marker `IEEEFloat`. Un helper único calcula el cierre de implicaciones:

```text
IEEEFloat -> RealOps -> FieldOps -> RingOps
```

Los aliases `*Ops` se expanden al recolectar constraints y no necesitan una
entidad runtime. `GenericParamInfo` debe distinguir:

- spellings declarados, con spans, para diagnostics y dumps;
- guarantees atómicas normalizadas;
- markers nominales sellados, al menos `IEEEFloat`.

`guarantees_capability` consulta el cierre; `satisfies_capability` consulta la
tabla concreta. Ninguna propiedad numérica deriva estructuralmente a través de
fields, collections o aggregates.

## 5. Zero, One y literales genéricos

### 5.1 Sintaxis elegida

La sintaxis source natural queda admitida:

```aether
T z = 0;  // requiere Zero
T o = 1;  // requiere One
```

También funciona al fluir un expected `T` hacia un argumento:

```aether
return matrixFilled<T>(rows, columns, 0);
```

No se agregan `zero<T>()` ni `one<T>()` públicos. Podrían modelar el mismo HIR,
pero son más ruidosos, compiten con inferencia y parecen calls runtime. El HIR
sí conserva valores algebraicos explícitos.

### 5.2 Regla precisa

Sólo los tokens enteros sin signo exactamente `0` y `1` obtienen esta regla
cuando el expected type es un único parámetro genérico:

- `0` requiere `Zero` y produce `AlgebraicValue::Zero` de tipo `T`;
- `1` requiere `One` y produce `AlgebraicValue::One` de tipo `T`.

No hay conversión intermedia desde `int`, cast, allocation ni instrucción
runtime. Tras monomorfización se materializan directamente el cero positivo o
el uno del tipo concreto.

La regla no admite `2`, `-1`, `0.0`, `1.0`, exponentes ni cualquier literal
arbitrario sobre `T`. Los literales concretos conservan las reglas existentes.
Así `Zero`/`One` no se convierten en una puerta de coerción numérica general.

Cuando un algoritmo genérico necesita dos, lo construye explícitamente:

```aether
T one = 1;
T two = one + one;
```

La suma se reifica y constant-folding puede producir la constante concreta. QR
debe calcular `two` una vez fuera de los loops relevantes; no debe insertar una
operación extra por elemento.

### 5.3 HIR y verificación

`AlgebraicCapability` se amplía con `One`. `AlgebraicValue` continúa llevando
capability y tipo. El verificador paramétrico exige un `GenericParam` y la
garantía exacta. El verificador concreto prohíbe cualquier `AlgebraicValue`; la
sustitución debe haberlo reificado a literal concreto antes de MIR.

Para `float32` el cero reificado tiene bits de `+0.0f`; para `float64`,
`+0.0`. `-0.0` sólo se obtiene por negación u otra operación IEEE y no es el
valor canónico de `Zero`.

## 6. Operadores genéricos

### 6.1 Binarios homogéneos

`BehavioralCapability` se amplía con `Div`; `Add`, `Sub`, `Mul` y `Div` prueban
`T × T -> T`. El analyzer conserva el patrón actual:

```text
source T op T
  -> comprobar guarantee sobre T
  -> HIR CapabilityBinary(op, T, T) : T
  -> sustituir T concreto
  -> reificar opcode concreto
```

Para `float32`/`float64`, `Div` se vuelve el mismo `DivideFloat` existente. Un
marker o alias nunca selecciona un opcode por sí solo; lo seleccionan el tipo
concreto y la operación ya probada.

### 6.2 Negación

Unary `-x` sobre `T` requiere `Negate` y produce
`CapabilityUnary { Negate, operand } : T`. Tras monomorfización:

- floats usan `NegateFloat`;
- signed integers admitidos por `Negate` usan `NegateIntegerChecked` y conservan
  `IntegerOverflow`;
- ningún opcode simbólico cruza a MIR.

`Negate` no se infiere de `Sub`: disponer de resta binaria no prueba
necesariamente una negación con el mismo contrato.

### 6.3 Igualdad y orden

`==` y `!=` requieren `Equal`; producen `bool`. Las cuatro comparaciones de
orden requieren `Order`; también producen `bool`. HIR usa una operación
simbólica tipada distinta de `CapabilityBinary`, porque el resultado no es `T`:

```text
CapabilityCompare { Equal|NotEqual|Less|LessEqual|Greater|GreaterEqual,
                    left: T, right: T } : bool
```

La reificación selecciona los opcodes concretos actuales. Para IEEE conserva
exactamente el comportamiento unordered de NaN y `+0.0 == -0.0`. `Equal` no
implica `Order`, ni `Order` implica `Equal` salvo mediante un alias compuesto
que enumere ambos.

## 7. `abs` y `sqrt`

### 7.1 Participación en Core

`abs(x)` y `sqrt(x)` siguen siendo los mismos nombres Core/prelude. No se crean
métodos ni funciones de `linearAlgebra`. Al resolver una Core call cuyo
argumento es `T`:

- `abs(T)` exige `Abs`;
- `sqrt(T)` exige `Sqrt`;
- HIR emite `CapabilityMath { Abs|Sqrt, operand, result_type }`;
- el HIR concreto reifica a `CoreCall` con `CoreFunction` y tipo concretos;
- backend usa `fabsf`/`fabs` y `sqrtf`/`sqrt` como hoy.

El verificador comprueba operación, capability, tipo de operando y resultado.
En V1 ambos resultados son `T`; el field `result_type` no debe inferirse de la
ausencia de metadata, porque será el punto de extensión para magnitudes.

### 7.2 Sin bundle trascendental

`IEEEFloat` no habilita genéricamente `sin`, `cos`, `tan`, `exp` o `ln` en este
milestone. Si se necesitan más adelante, cada familia deberá justificar una
capability o composición propia. No se amplía `RealOps` por conveniencia.

## 8. Requisitos auditados por algoritmo

La siguiente tabla deriva de `linearAlgebra/src/lib.ae` vigente. “Operaciones
escalares T” excluye loops/shapes sobre `usize` y el signo/permutación integer.
“Constraint público V1” prioriza conservar el contrato observable, no sólo la
lista mínima de tokens del cuerpo.

| API/kernel | operaciones reales sobre `T` | storage/lectura | constraint público futuro |
|---|---|---|---|
| `zeros` Matrix/Vector | `Zero` como fill | `Storable + Copy` requerido por filled-init | `Storable + Copy + Zero` |
| `ones` Matrix/Vector | `One` como fill | `Storable + Copy` | `Storable + Copy + One` |
| `identity` | `Zero` fill, `One` diagonal | `Storable + Copy` | `Storable + Copy + Zero + One` |
| LU partial pivoting | `Zero`, `One`, `Abs`, `Order` (`>`), `Equal` (`!= 0`), `Div`, `Sub`, `Mul` | Matrix storage y reads `Copy` | `IEEEFloat` |
| solve Vector desde LU | `Zero`, `Equal` (`== 0`), `Sub`, `Mul`, `Div` | output filled, reads de L/U/b | `IEEEFloat` |
| solve Matrix desde LU | `Zero`, `Equal`, `Sub`, `Mul`, `Div` | output filled, reads de L/U/B | `IEEEFloat` |
| det desde LU | `One`, `Negate`, `Mul` | reads de diagonal | `IEEEFloat` |
| det desde Matrix | lo anterior más todo LU | owner Matrix | `IEEEFloat` |
| QR Householder | `Zero`, `One`, `Add`, `Sub`, `Mul`, `Div`, `Negate`, `Equal`, `Order` (`<`, `>=`), `Abs`, `Sqrt`; `two = one + one` | Q/R Matrix, `Copy` | `IEEEFloat` |

Detalles que la tabla hace explícitos:

- LU no usa unary `-` sobre `T`; el signo de permutación sigue siendo `int`.
- `det` no necesita convertir `permutationSign` a `T`: inicia en `one`, lo
  niega si el signo es negativo y luego multiplica la diagonal. Esto elimina un
  cast genérico desde integer.
- solve no necesita `One`, `Abs`, `Order` ni `Sqrt` en su cuerpo, pero
  `IEEEFloat` impide construir una generalización contractual falsa.
- QR usa el literal concreto `2.0` hoy; la migración usa `two = one + one` para
  no crear conversión genérica arbitraria.

### 8.1 Cholesky futuro

No existe un kernel Cholesky actual que pueda auditarse línea por línea. Para la
variante real no bloqueada por este diseño se anticipan:

```text
Zero, One, Add/Sub, Mul, Div, Equal/Order, Sqrt, Storable, Copy
```

y el contrato público inicial debe ser `T: IEEEFloat`. La decisión exacta de
positividad, singularidad y shapes pertenece a su propio milestone.

Una variante compleja futura no debe reutilizar ese cuerpo fingiendo `Order`
sobre `Complex<T>`; véase la sección 11.

## 9. API futura de `linearAlgebra`

La sintaxis siguiente es normativa como objetivo, salvo detalles puramente de
formato. La orientación continúa siendo cerrada, no un type parameter genérico;
por ello Row y Column siguen siendo overloads.

```aether
Matrix<T> zeros<T: Storable + Copy + Zero>(usize size);
Matrix<T> zeros<T: Storable + Copy + Zero>(usize rows, usize columns);
Vector<T,Row> zeros<T: Storable + Copy + Zero>(usize length);
Vector<T,Column> zeros<T: Storable + Copy + Zero>(usize length);

Matrix<T> ones<T: Storable + Copy + One>(usize size);
Matrix<T> ones<T: Storable + Copy + One>(usize rows, usize columns);
Vector<T,Row> ones<T: Storable + Copy + One>(usize length);
Vector<T,Column> ones<T: Storable + Copy + One>(usize length);

Matrix<T> identity<T: Storable + Copy + Zero + One>(usize size);

LU<T> lu<T: IEEEFloat>(Matrix<T> A);
QR<T> qr<T: IEEEFloat>(Matrix<T> A);

T det<T: IEEEFloat>(ref LU<T> factor);
T det<T: IEEEFloat>(Matrix<T> A);

Vector<T,Column> solve<T: IEEEFloat>(
    ref LU<T> factor,
    ref Vector<T,Column> b);
Vector<T,Column> solve<T: IEEEFloat>(
    Matrix<T> A,
    ref Vector<T,Column> b);

Matrix<T> solve<T: IEEEFloat>(ref LU<T> factor, ref Matrix<T> B);
Matrix<T> solve<T: IEEEFloat>(Matrix<T> A, ref Matrix<T> B);
```

`LU<T: Storable>` y `QR<T: Storable>` pueden conservar su constraint
representacional actual. Restringir el aggregate mismo a `IEEEFloat` impediría
usarlo como mero contenedor en evolución futura y no es necesario: son las
operaciones constructoras/consumidoras las que garantizan su dominio.

### 9.1 Inferencia y overload resolution

La inferencia existente basta:

```aether
Matrix<float64> A = linearAlgebra.zeros(3, 2);
Vector<float32,Column> v = linearAlgebra.ones(5);
LU<float64> f = linearAlgebra.lu(A);
```

En los constructores, `T` aparece sólo en el retorno; el expected type se
unifica antes de arguments y selecciona tanto el overload Matrix/Vector como la
orientación exacta. En `lu`, `qr`, `solve` y `det`, los argumentos suelen
inferir `T`; el expected result sólo agrega una comprobación consistente.

Estas expresiones permanecen deliberadamente sin información suficiente:

```aether
var a = linearAlgebra.zeros(3);
var b = linearAlgebra.ones(5);
```

Deben usar los diagnostics generales `E0461`/`E0462`; no se elige `float64` ni
una orientación por default. Son válidas las formas explícitas cuando el
overload queda determinado por contexto, por ejemplo
`Matrix<float32> A = zeros<float32>(3)`.

No se agrega lógica compiler-known para nombres `zeros`, `lu` o package
`linearAlgebra`.

### 9.2 Compatibilidad de nombres

`lu`, `solve`, `det`, `zeros`, `ones` e `identity` conservan nombres y calls
source. Los overloads concretos se reemplazan por las declaraciones genéricas
familia por familia; no deben coexistir con una genérica igualmente viable,
porque introducirían ambigüedad y dos kernels.

El nombre final de QR es `qr` para ambas precisiones. Para preservar consumidores
actuales, `qrFloat32` queda temporalmente como wrapper deprecated:

```aether
QR<float32> qrFloat32(Matrix<float32> A) {
    return qr(A);
}
```

El wrapper no duplica el kernel. Su eliminación requiere una ventana de
deprecation o un cambio de versión source incompatible explícito.

## 10. HIR, monomorfización, MIR y SSA

### 10.1 HIR paramétrico

HIR debe registrar la prueba estática junto a cada operación:

| source | HIR paramétrico |
|---|---|
| `0`, `1` | `AlgebraicValue { Zero|One }` |
| `+ - * /` binarios | `CapabilityBinary { behavior }` |
| unary `-` | `CapabilityUnary { Negate }` |
| `== != < <= > >=` | `CapabilityCompare { operation }` |
| `abs`, `sqrt` | `CapabilityMath { operation, result_type }` |

Cada nodo conserva operand types, result type y span. El verificador paramétrico
recalcula el requirement desde la operación y exige que el binder lo pruebe.
No confía en que el analyzer haya construido un nodo correcto.

Las calls genéricas también siguen verificando que un caller simbólico provea
todo el cierre exigido por el callee. Un `T: RealOps` puede llamar a
`f<U: FieldOps>`, pero no a `f<U: IEEEFloat>`.

### 10.2 Frontera de reificación

Al crear una instancia, antes de publicar su `InstanceId` ejecutable:

1. se validan constraints concretas;
2. se sustituye `T` en locals, parámetros, retornos y expressions;
3. cada operation capability se resuelve mediante `(tipo concreto, operación)`;
4. algebraic values se vuelven literales concretos;
5. `abs`/`sqrt` se vuelven Core calls concretas;
6. se verifica el HIR concreto.

Si una tabla está incompleta o corrupta, la instanciación falla con un diagnostic
de verificación; nunca difiere a LLVM.

### 10.3 MIR/SSA/backend

MIR no incorpora nuevos opcodes genéricos. Recibe únicamente los ya concretos:

- arithmetic integer checked o float;
- comparisons concretas;
- `CoreCall` concreta para `abs`/`sqrt`;
- constantes del scalar concreto.

Los verificadores MIR y SSA deben rechazar cualquier `TypeData::GenericParam`,
capability op o Core signature incoherente. Los contratos existentes de traps
integer y ausencia de trap float siguen vigentes.

LLVM no consulta capabilities. `float32` baja a `float`, `float64` a `double`, y
los símbolos de las instancias retienen sus type arguments. No hay helper de
dispatch numérico ni branch por `TypeId`.

## 11. Extensibilidad a tipos numéricos futuros

### 11.1 Límite V1

Todas las capabilities numéricas permanecen compiler-known en el primer
vertical. No se añade sintaxis para que un user type implemente operaciones, ni
operator overloading general, associated types o coherence. Éste es un límite
de implementación, no una clausura conceptual:

- los atoms algebraicos y sus HIR nodes no codifican `float32`/`float64`;
- las tablas concretas pueden evolucionar a implementations estáticas;
- los aliases `*Ops` son composiciones, no listas hard-coded en algoritmos;
- `IEEEFloat` sí permanece sellada salvo revisión explícita de su contrato.

Una fase futura puede permitir implementations estáticas para `Zero`, `One`,
operadores y funciones matemáticas. Debe monomorfizar calls directas, aplicar
coherence y conservar cero runtime witnesses. Esa machinery no es requisito
para deduplicar los kernels actuales.

### 11.2 Complex sin orden falso

`Complex<float32>` y `Complex<float64>` no satisfarán `Order`, `RealOps` ni
`IEEEFloat`. Sí podrían satisfacer en el futuro capacidades como:

```text
Zero, One, Add, Sub, Mul, Div, Negate, Equal
Conjugate
Magnitude<R> o NormSquared<R>
```

donde `R` es el scalar real asociado. Este diseño reserva esa evolución de dos
formas:

- `CapabilityMath` conserva un `result_type` separado del operand type;
- `Abs` V1 no se usa como prueba implícita de `Order` ni se embebe dentro de
  `FieldOps`.

La primera implementación de Complex deberá introducir una relación estática
de output, por ejemplo `Magnitude<R>`, en vez de cambiar silenciosamente
`Abs: T -> T`. Para LU complejo, partial pivoting calcula una magnitud `R` y
compara `R`; nunca compara dos `Complex`. Para QR complejo, inner products y
Householder requieren conjugación y magnitud/norma real. Para Cholesky complejo,
la factorización es Hermitian: usa conjugación, diagonal real positiva y
conjugate transpose, no la transposición simple.

No se implementa nada de ello ahora. La separación actual evita tener que
deshacer `IEEEFloat` o una falsa super-capability de orden cuando llegue ese
milestone.

## 12. Diagnostics

Se reutilizan los caminos generales y se reservan códigos concretos sólo durante
el milestone de implementación. Los mensajes normativos son:

| caso | forma del diagnostic |
|---|---|
| `/` sin prueba | `operator '/' on generic parameter T requires capability Div` |
| unary `-` sin prueba | `unary operator '-' on generic parameter T requires capability Negate` |
| `==`/`!=` sin prueba | `operator '==' on generic parameter T requires capability Equal` |
| `>` u otro orden sin prueba | `operator '>' on generic parameter T requires capability Order` |
| `abs(T)` sin prueba | `Core function 'abs' on generic parameter T requires capability Abs` |
| `sqrt(T)` sin prueba | `Core function 'sqrt' on generic parameter T requires capability Sqrt` |
| `0`/`1` sin prueba | `literal '0' for generic parameter T requires capability Zero` |
| instancia inválida explícita | `type X does not satisfy 'Capability'; required by ...` (`E0316`) |
| instancia inferida inválida | `inference succeeded, but inferred type X does not satisfy ...` (`E0317`) |
| inferencia ausente/ambigua | infrastructure `E0263`, `E0461`, `E0462`, `E0464` existente |
| alias duplicado | identificar atom repetido y ambos spans |
| marker imposible | `type X does not satisfy sealed capability IEEEFloat` |

Un cuerpo genérico se rechaza al analizar su declaración, aunque nunca se
instancie. Una call inválida se rechaza antes de reservar/cachear `InstanceId`.
No existen errores específicos de `linearAlgebra`.

La verificación de IR corrupto usa `E0348` y falla cerrado si:

- el node simbólico no coincide con la capability;
- operands/result types son incoherentes;
- un marker fue eliminado de metadata;
- una operation capability llega a HIR concreto;
- un generic type u operation llega a MIR/SSA.

## 13. Cero overhead y ABI

Normativamente, la implementación no puede introducir:

- vtables o interface dispatch;
- runtime witness tables o dictionaries;
- boxing, `Any` o wrappers de scalar;
- heap allocation causada por una capability;
- lookup por nombre, reflection o switch por `TypeId`;
- un ABI scalar distinto del concreto actual.

Una implementación source produce instancias separadas. Para un ejemplo:

```text
lu<float32> -> símbolo ...lu__gf32..., operaciones float/fabsf
lu<float64> -> símbolo ...lu__gf64..., operaciones double/fabs
```

El spelling exacto depende del mangler existente; la propiedad normativa es que
incluya la identidad de declaración, disambiguador de overload si corresponde y
type arguments canónicos, sin colisiones.

El objetivo de performance es el mismo IR optimizable que el kernel concreto
manual. O0 puede conservar estructura distinta por bindings genéricos, pero no
dispatch ni allocations adicionales; O2 debe eliminar abstracción y producir
operaciones equivalentes.

Durante la migración, una declaración concreta y su reemplazo genérico tienen
símbolos distintos. No se publican simultáneamente bajo la misma resolución
source. Los consumidores del package se recompilan; si existiera distribución
de artefactos binarios precompilados, el cambio exige versionado ABI o shims
explícitos, no alias accidental de símbolos.

## 14. Preservación de contratos numéricos

La migración futura sólo cambia la expresión source del tipo. Debe conservar:

- orden exacto de loops y operaciones;
- pivoting parcial, desempate estricto y swaps completos de LU;
- chequeo de singularidad por igualdad exacta, no epsilon;
- comportamiento de `+0.0`, `-0.0`, NaN, infinities y subnormals;
- algoritmo scaled sum-of-squares y Householder de QR;
- orden de updates de QR y storage temporal del reflector;
- shape guards y exception types;
- ownership de inputs, outputs y refs;
- layouts de `LU<T>`, `QR<T>`, `Matrix<T>` y `Vector<T,O>`;
- cantidad/clase de allocations y reutilización del backing;
- resultados de solve y determinant, incluido signo de permutación.

No se activa fast-math, reassociation, tolerancia, finite check ni promoción.
Una diferencia numérica respecto del kernel oracle es un bug de migración, no
una libertad de la abstracción.

## 15. Plan de implementación y migración

El orden posterior queda cerrado así:

1. **Vocabulary y closure.** Agregar atoms, aliases y marker `IEEEFloat`; ampliar
   parser/collection, metadata, satisfaction/guarantee y diagnostics sin nuevas
   operaciones source.
2. **Zero/One contextuales.** Generalizar `AlgebraicValue`, typing exacto de
   tokens `0`/`1`, sustitución y verificación negativa.
3. **Operadores faltantes.** Implementar `Div`, `Negate`, `Equal` y `Order` en
   HIR paramétrico y su reificación concreta; mantener MIR sin símbolos.
4. **Core genérico.** Implementar `Abs`/`Sqrt` vía `CapabilityMath` y reificar a
   Core calls actuales.
5. **Qualification del lenguaje.** Tests positivos/negativos, forwarding de
   aliases/markers, HIR corrupto, instancias y símbolos O0/O2. No tocar aún
   `linearAlgebra`.
6. **Constructores.** Migrar `zeros`, `ones`, `identity`; preservar overloads de
   Matrix/Row/Column e inferencia expected-result.
7. **det desde LU.** Migrar usando `one` y `Negate` en vez de cast desde
   `permutationSign`; calificar resultados bitwise/IEEE.
8. **solve Vector y Matrix.** Migrar ambos pares factor/matrix conservando shape
   guards, allocations y exception behavior.
9. **LU.** Migrar el kernel completo y comparar con los overloads oracles antes
   de retirarlos.
10. **QR.** Migrar Householder, agregar `qr<float32>`, convertir `qrFloat32` en
    wrapper y preservar operación/order exactos.
11. **Limpieza y regresión.** Eliminar sólo kernels concretos redundantes,
    actualizar docs y correr qualification completa.
12. **Cholesky.** Recién después, abrir su milestone de arquitectura/algoritmo.

Cada familia se cambia atómicamente. Mientras se compara contra el oracle, el
kernel histórico puede vivir bajo un nombre test-only/interno no visible al
resolver overloads; nunca debe crear ambigüedad pública.

## 16. Qualification futura

### 16.1 Capability system

La suite deberá probar:

- parse y closure de cada primitive, alias y `IEEEFloat`;
- implicaciones positivas y ausencia de implicaciones inversas;
- duplicate/unknown constraints y forwarding entre genéricos;
- cada operador/function permitido con su capability exacta;
- cada operador/function rechazado al retirar sólo esa capability;
- `0`/`1` sobre T y rechazo de `2`, `0.0`, `1.0` genéricos;
- satisfacción concreta de built-ins y rechazo de aggregates/user types;
- `IEEEFloat` exactamente para `float32`/`float64`;
- HIR paramétrico con nodes simbólicos y HIR concreto sin ellos;
- corrupción independiente de metadata/node/op/result;
- MIR/SSA sin tipos ni operaciones genéricas;
- símbolos separados y ausencia de runtime witnesses.

### 16.2 `linearAlgebra`

Los tests actuales de constructors, LU, solve Vector, solve Matrix, det y QR son
oracles. Se agregará:

- una búsqueda/source assertion de un solo cuerpo de kernel por algoritmo;
- comparación de resultados float32/float64 con los kernels previos, incluida
  clasificación/bit pattern donde el contrato lo exija;
- matrices square/tall/wide, vacías, singulares y casos especiales existentes;
- `+0.0`, `-0.0`, NaN, infinities y subnormals;
- inference desde expected Matrix/Vector Row/Column;
- ambiguity de `var x = zeros(...)`/`ones(...)` sin expected type;
- inferencia desde argumentos para `lu`, `solve`, `det`, `qr`;
- `qrFloat32` wrapper y `qr` genérico equivalentes;
- HIR con una instancia por type arguments y mangling no colisionante;
- MIR/SSA con opcodes float concretos;
- inspección de LLVM O0/O2 sin indirect calls, vtables ni TypeId dispatch;
- mismos owners, borrows, drops, shape guards, exceptions y allocations;
- suite completa del workspace y consumer publicado.

Comandos mínimos de cierre de cada vertical:

```text
cargo test --workspace
cargo fmt --all --check
cargo clippy --workspace --all-targets -- -D warnings
bash compiler-next/tests/run-differential.sh
git diff --check
```

Las pruebas de IR/allocations existentes se amplían; no se acepta sólo igualdad
aproximada de outputs como evidencia de cero overhead o preservación contractual.

## 17. Alternativas rechazadas

### 17.1 Un único `Float` gigante

Mezclar aritmética, orden, abs, sqrt y trascendentales haría imprecisas firmas
simples y convertiría cualquier extensión en un cambio global. `IEEEFloat` es
deliberadamente un dominio sellado para migrar contratos IEEE, mientras los
atoms/aliases permiten expresar algoritmos generales sin adquirir funciones no
usadas.

### 17.2 Sólo listas largas de primitives

Son precisas pero vuelven ilegibles LU/QR/Cholesky y propensas a omisiones. Los
tres aliases `*Ops` cubren familias matemáticas sin crear una biblioteca de
typeclasses. Los constructores, que necesitan combinaciones pequeñas, siguen
usando primitives.

### 17.3 `Field`/`Real` como axiomas

El compilador no demuestra leyes y IEEE no las cumple literalmente. Nombrar
aliases `RingOps`/`FieldOps`/`RealOps` documenta su naturaleza operacional.

### 17.4 Cast implícito desde `int`

Convertir `0`/`1` pasando por `int` introduce semántica y potencial lowering no
necesarios, y generalizarlo habilitaría coerciones peligrosas. Los valores
algebraicos contextuales se reifican directamente.

### 17.5 `zero<T>()`/`one<T>()`

Es viable internamente pero peor como source, parece dispatchable y no aprovecha
el expected typing existente. Se conserva `AlgebraicValue` como representación,
no como call pública.

### 17.6 Core genérico sin capability

Aceptar `abs(T)` o `sqrt(T)` porque alguna instancia futura podría ser float
dejaría cuerpos sin prueba paramétrica y errores dependientes de instanciación.
Cada call exige capability al verificar la declaración.

### 17.7 Traits/witnesses desde el primer vertical

La necesidad inmediata cubre dos built-ins y ya existe reificación cerrada.
Agregar coherence, associated types y dispatch sería un sistema mucho mayor y
contrario al objetivo cero overhead verificable. La evolución a implementations
estáticas permanece posible sin introducir witnesses runtime.

## 18. Fuera de scope

No forman parte de `NUMERIC-CAPABILITIES-ARCH-1`:

- implementar cualquier capability o cambiar código/tests;
- migrar `linearAlgebra` o eliminar overloads;
- Cholesky, Complex, Decimal, Rational, BigFloat o arbitrary precision;
- operator overloading general y declarations de capability por usuarios;
- associated types o la forma final de `Magnitude<R>`;
- sin/cos/tan/exp/ln genéricos;
- SIMD, BLAS/LAPACK, sparse kernels o fast-math;
- dynamic numeric protocols, reflection o runtime dispatch;
- cambios a storage/layout de Matrix, Vector, LU o QR.

No quedan decisiones abiertas que bloqueen el primer vertical de
implementación: vocabulary, jerarquía, literales, HIR, reificación, dominio
IEEE, API objetivo, inferencia, ABI, diagnostics y orden de migración quedan
cerrados aquí.
