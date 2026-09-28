# NUMERIC-CAPABILITIES-ARCH-1 — reporte de arquitectura

Estado: **ARQUITECTURA CERRADA; NO IMPLEMENTADA**, 2026-09-28.

Autoridad normativa:
[NUMERIC_CAPABILITIES_ARCH_1](NUMERIC_CAPABILITIES_ARCH_1.md).

Este reporte cierra el milestone documental. No se modificaron compiler-next,
`linearAlgebra`, runtime ni tests.

## Resultado

Se auditó la implementación real y se decidió extender su sistema cerrado de
capabilities. Compiler-next ya posee binders con identidad semántica,
constraints, `Copy`/`Relocatable`/`Storable`, `Add`/`Sub`/`Mul`, `Zero`, HIR
paramétrico verificado, monomorfización por type arguments y reificación a
operaciones concretas. No hace falta un sistema paralelo de traits.

La carencia que bloquea los kernels numéricos queda acotada a:

```text
One, Div, Negate, Equal, Order, Abs, Sqrt
```

más literales `0`/`1` sobre un parámetro genérico y una garantía nominal de
semántica IEEE.

## Jerarquía cerrada

Las primitives finales son:

```text
Zero  One
Add   Sub   Mul   Div   Negate
Equal Order
Abs   Sqrt
```

Las composiciones legibles son aliases compile-time:

```text
RingOps  = Zero + One + Add + Sub + Mul + Negate + Equal
FieldOps = RingOps + Div
RealOps  = FieldOps + Order + Abs + Sqrt
```

`*Ops` prueba disponibilidad y semántica de operaciones, no leyes formales. Así
no se afirma que floats con redondeo/NaN formen un campo exacto ni que sus
comparaciones sean un orden total.

`IEEEFloat` es un marker nominal sellado, satisfecho inicialmente exactamente
por `float32` y `float64`. Implica `RealOps + Copy + Relocatable + Storable`,
pero reunir esas capabilities no implica `IEEEFloat`. Ésta es la frontera que
preserva los contratos actuales de `+/-0`, NaN, Inf, subnormals, comparaciones y
operaciones IEEE sin admitir accidentalmente Decimal, Rational, BigFloat o
tipos de usuario.

## Valores, operadores y Core

Con expected type `T`, los tokens exactos `0` y `1` producirán
`AlgebraicValue::{Zero,One}` y exigirán su capability. No se hará cast desde
`int`, no se agregarán `zero<T>()`/`one<T>()`, y `2`, `0.0`, `1.0` u otros
literales continuarán inválidos sobre T. QR construirá `two = one + one` una vez.

HIR paramétrico retendrá prueba explícita:

| operación | HIR simbólico |
|---|---|
| `0`, `1` | `AlgebraicValue` |
| `+`, `-`, `*`, `/` | `CapabilityBinary` |
| unary `-` | `CapabilityUnary` |
| igualdad/orden | `CapabilityCompare` |
| `abs`, `sqrt` | `CapabilityMath` |

`abs` y `sqrt` siguen siendo Core/prelude; no se convierten en helpers de
`linearAlgebra`. Tras sustitución, los nodes se reifican a literals, opcodes o
Core calls concretas existentes. HIR concreto los prohíbe y MIR/SSA nunca ven
un generic operation.

## Requisitos reales y API

La revisión de `linearAlgebra/src/lib.ae` determinó:

- `zeros`: `Storable + Copy + Zero`;
- `ones`: `Storable + Copy + One`;
- `identity`: `Storable + Copy + Zero + One`;
- LU: zero/one, abs, orden, igualdad, división, resta y multiplicación;
- solve Vector/Matrix: zero, igualdad, resta, multiplicación y división;
- det desde LU: one, negación y multiplicación, sin cast integer-to-T;
- QR: todo `RealOps`, incluido abs/sqrt y el valor two derivado de one.

Aunque solve/det usan subconjuntos, LU, solve, det y QR expondrán
`T: IEEEFloat` para conservar el dominio y contrato exactos. Los constructores
sí usarán constraints mínimas y podrán servir otros built-ins admitidos.

La superficie objetivo conserva nombres y overloads Matrix/Vector:

```aether
Matrix<T> zeros<T: Storable + Copy + Zero>(usize rows, usize columns);
Vector<T,Column> ones<T: Storable + Copy + One>(usize length);
Matrix<T> identity<T: Storable + Copy + Zero + One>(usize size);
LU<T> lu<T: IEEEFloat>(Matrix<T> A);
QR<T> qr<T: IEEEFloat>(Matrix<T> A);
T det<T: IEEEFloat>(ref LU<T> factor);
Vector<T,Column> solve<T: IEEEFloat>(ref LU<T> factor,
                                     ref Vector<T,Column> b);
Matrix<T> solve<T: IEEEFloat>(ref LU<T> factor, ref Matrix<T> B);
```

Los demás overloads de aridad/entrada quedan detallados en el documento
normativo. La orientación no es generic parameter, por lo que Row/Column siguen
siendo overloads seleccionados por expected result.

La inferencia existente ya permite:

```aether
Matrix<float64> A = linearAlgebra.zeros(3, 2);
Vector<float32,Column> v = linearAlgebra.ones(5);
```

`var x = zeros(3)` permanece ambiguo y usa diagnostics generales. `qr` será el
nombre final para ambas precisiones; `qrFloat32` se conserva temporalmente como
wrapper deprecated sin duplicar el kernel.

## Monomorfización, ABI y overhead

Una implementación source genera instancias y símbolos distintos para
`float32` y `float64`. Las capabilities se eliminan antes de MIR:

- no vtables ni witness tables;
- no boxing, `Any` o wrapper scalar;
- no allocation causada por constraints;
- no lookup/reflection/switch por TypeId;
- no cambio de ABI concreto.

El mangler existente ya incorpora overload disambiguators y type arguments. La
migración reemplazará cada familia concreta atómicamente; no coexistirá con una
genérica igualmente viable. Consumidores se recompilan porque los símbolos
genéricos cambian aunque la mayoría de calls source no cambie.

## Extensibilidad

V1 mantiene todas las capabilities compiler-known. Las algebraicas podrán
evolucionar a implementations estáticas de user types sin cambiar el HIR ni
agregar dispatch runtime; `IEEEFloat` seguirá sellada salvo revisión explícita.

Complex no se fuerza dentro de `Order`, `RealOps` o `IEEEFloat`. Una extensión
futura usará `Conjugate` y una relación estática `Magnitude<R>` o
`NormSquared<R>`. LU comparará magnitudes reales, QR usará inner products
conjugados y Cholesky será Hermitian. `CapabilityMath` conserva result type
separado precisamente para no cerrar esa evolución, pero associated outputs y
Complex quedan fuera de este milestone.

## Diagnostics y verificadores

Cada operación faltante señalará la capability exacta en el cuerpo genérico.
Las instancias inválidas reutilizarán `E0316`/`E0317`; la inferencia ambigua o
ausente conservará `E0263`/`E0461`/`E0462`/`E0464`. No habrá diagnostics de
`linearAlgebra`.

El verificador HIR fallará cerrado si la operación, capability o tipos no
coinciden, si el marker requerido fue borrado o si un node simbólico alcanza HIR
concreto. MIR/SSA seguirán rechazando generic types y contratos concretos
incoherentes. LLVM nunca completa semántica omitida por el frontend.

## Migración posterior

El orden cerrado es:

1. vocabulary, aliases y `IEEEFloat`;
2. `Zero`/`One` y literales contextuales;
3. Div/Negate/Equal/Order;
4. Abs/Sqrt en Core genérico;
5. qualification completa del lenguaje;
6. constructors;
7. det;
8. solve Vector/Matrix;
9. LU;
10. QR y wrapper `qrFloat32`;
11. eliminación de kernels redundantes y regresión completa;
12. recién entonces, milestone Cholesky.

Los tests actuales de constructors, LU, solve, det y QR serán oracles. La
qualification exigirá equivalencia float32/float64, operación/order y valores
IEEE especiales, HIR genérico constrained, MIR/SSA concretos, símbolos
separados, ausencia de dispatch, mismas allocations/ownership y ejecución O0/O2.

## Alcance verificado

Este milestone crea sólo:

- `docs/architecture/NUMERIC_CAPABILITIES_ARCH_1.md`;
- `docs/architecture/NUMERIC_CAPABILITIES_ARCH_1_REPORT.md`.

No implementa capabilities ni migra kernels; tampoco agrega
Cholesky/Complex, cambia storage o altera contratos numéricos. No quedan
decisiones arquitectónicas abiertas que bloqueen el primer vertical posterior.
