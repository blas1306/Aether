# LINEAR-ALGEBRA-CHOLESKY-DET-ARCH-1 — determinant reutilizable desde Cholesky

Estado: **ARQUITECTURA CERRADA; NO IMPLEMENTADA**, 2026-09-29.

Este milestone es exclusivamente documental. No modifica
`linearAlgebra/src/lib.ae`, consumer, tests, compiler, runtime ni standard
library. La implementación y qualification pertenecen a un milestone
posterior.

Autoridad relacionada:

- [LINEAR-ALGEBRA-CHOLESKY-ARCH-1](LINEAR_ALGEBRA_CHOLESKY_ARCH_1.md);
- [LINEAR-ALGEBRA-CHOLESKY-V1](LINEAR_ALGEBRA_CHOLESKY_V1_REPORT.md);
- [LINEAR-ALGEBRA-CHOLESKY-SOLVE-ARCH-1](LINEAR_ALGEBRA_CHOLESKY_SOLVE_ARCH_1.md);
- [LINEAR-ALGEBRA-CHOLESKY-SOLVE-V1](LINEAR_ALGEBRA_CHOLESKY_SOLVE_V1_REPORT.md);
- [LINEAR-ALGEBRA-GENERIC-DET-V1](LINEAR_ALGEBRA_GENERIC_DET_V1_REPORT.md).

## 1. Decisión resumida

Se agregará exactamente este overload público y genérico:

```aether
T det<T: IEEEFloat>(ref Cholesky<T> factor);
```

Para un factor legítimo con `A = L L^T`, calcula:

```text
p = product(diag(L))
det(A) = p * p
```

El producto diagonal se evalúa en orden ascendente y se cuadra una sola vez al
final. Ésta es la forma A de §7 y es normativa. El factor es un préstamo
shared, permanece intacto y puede reutilizarse después. Sólo se valida que
`factor.L` sea square; no se vuelve a validar la representación Cholesky.

La operación cuesta `O(n)`, usa `O(1)` storage escalar y realiza cero
allocations. Es package source ordinario y no introduce soporte especial del
compiler o runtime.

## 2. Superficie, overload e inferencia

El overload coexiste con las declaraciones actuales:

```aether
T det<T: IEEEFloat>(ref LU<T> factor);
T det<T: IEEEFloat>(ref Matrix<T> A);
```

El tipo nominal del argumento distingue `Cholesky<T>`, `LU<T>` y `Matrix<T>`.
No se selecciona algoritmo por shape runtime, flag, enum, `TypeId` ni tipo de
retorno. No se modifica ninguna declaración existente.

`ref` forma parte de la declaración y expresa un préstamo shared. Las reglas
vigentes de borrow ergonomics permiten llamar con un owner:

```aether
var ch = cholesky(A);
var d = det(ch);
```

La forma explícita equivalente es `det(&ch)`. `T` se infiere desde
`Cholesky<T>` antes de materializar el préstamo; `det<float32>(ch)` y
`det<float64>(ch)` siguen siendo formas válidas. No se agregan wrappers por
precisión, default float, alias `cholDet`, variante consuming ni overload desde
una Matrix que elija Cholesky automáticamente.

## 3. Semántica matemática

Para un factor legítimo producido conforme a CHOLESKY-V1:

```text
factor.L = L : n×n
A = L L^T
diag(L) finita y estrictamente positiva
```

se cumple en aritmética exacta:

```text
det(A) = det(L) det(L^T)
       = product(diag(L)) * product(diag(L))
       = product(diag(L))^2
```

El resultado concreto está sujeto al orden IEEE de §7. La operación no
reconstruye `A`, no calcula `L^T` y no consulta ninguna celda fuera de la
diagonal. Por tanto lower y upper off-diagonal no influyen en el resultado.

El contrato de un factor legítimo implica un determinante matemático positivo
para `n > 0`. La aritmética concreta puede producir `+0` por underflow o
`+Inf` por overflow. Esos resultados no se reinterpretan como error.

## 4. Guard único y precedencia

La primera sentencia ejecutable del overload es exactamente:

```aether
shapeGuard(rows(factor.L) == columns(factor.L));
```

El guard ocurre antes de fijar `n`, indexar una celda, inicializar el
acumulador o ejecutar aritmética escalar. Sólo sus consultas de metadata
`rows`/`columns` son necesarias para decidirlo. Si falla, produce el trap
abortivo `ShapeMismatch` conforme al contrato vigente de `shapeGuard`.

Después del guard se fija `n = rows(factor.L)`. No existe otro guard ni pase de
validación. En particular, no se comprueban:

- positividad ni no nulidad de la diagonal;
- finitud;
- triangularidad lower;
- upper materializado a cero;
- simetría o positive definiteness de una Matrix original;
- procedencia del factor desde `cholesky`.

No se construye ni lanza `NotPositiveDefiniteException`,
`SingularMatrixException` o `InvalidCholeskyFactorException`. Revalidar sólo la
diagonal sería una certificación incompleta; revalidar toda la representación
agregaría costo, capabilities y una segunda autoridad sobre el productor.

## 5. Factor legítimo y aggregate manual

`Cholesky<T>` conserva su constraint representacional:

```aether
struct Cholesky<T: Storable> {
    Matrix<T> L;
}
```

Ese aggregate permite almacenar y mover una Matrix; por sí solo no demuestra
que haya sido producido por `cholesky`. La legitimidad es una precondición del
caller para interpretar el resultado como el determinante de una Matrix SPD,
no una propiedad que este overload vuelva a certificar.

Un aggregate manual que pasa el guard square ejecuta exactamente el algoritmo
IEEE de §7:

- una diagonal negativa participa normalmente en el producto;
- `+0` y `-0` participan con su signo IEEE;
- NaN, `+Inf` y `-Inf` participan sin validación;
- subnormales participan en la precisión concreta;
- lower y upper off-diagonal se ignoran por completo.

No existe un resultado garantizado respecto de alguna Matrix original para un
factor no legítimo. Sí quedan garantizados el guard, las lecturas exclusivas de
la diagonal, el orden operacional, el ownership y la ausencia de allocations.

## 6. Invariancia respecto del upper y del lower off-diagonal

El único acceso elemental permitido tiene la forma:

```text
factor.L[i,i]
```

para `i = 1..n` ascendente. Dos aggregates square con la misma secuencia de
bits diagonales deben ejecutar la misma secuencia aritmética y devolver el
mismo resultado observable, aunque difieran arbitrariamente en:

- todas las celdas del upper físico;
- todas las celdas lower off-diagonal;
- si esos valores ignorados son finitos, cero, NaN o infinitos.

Esta propiedad es normativa tanto para factores legítimos como manuales. No se
autoriza una lectura especulativa observable de celdas off-diagonal.

## 7. Algoritmo y orden numérico normativos

Después del guard, el body ejecuta conceptualmente:

```text
T p = 1
for i = 1..n ascending:
    p = p * factor.L[i,i]
return p * p
```

La inicialización usa `One` del tipo concreto. Cada iteración carga exactamente
una diagonal y ejecuta un `Mul`; el store en `p` ocurre antes de la siguiente
iteración. Al terminar, se ejecuta exactamente un `Mul` adicional con los dos
operandos iguales al valor final de `p`.

No se permite:

- reassociation o cambio del orden ascendente;
- convertir `p * p` en otro cálculo contractual;
- fast-math;
- FMA contractual;
- reducción vectorial o paralela que cambie el agrupamiento;
- acumulador de precisión distinta de `T`;
- normalización de signed zero, NaN o infinito;
- log-domain, escalado o producto compensado.

El conteo escalar es `n + 1` multiplicaciones, incluso para `n == 0`, donde la
última operación es `one * one`. Una optimización backend sólo es válida si
preserva el resultado y la semántica observable de esta secuencia.

## 8. Elección explícita entre A y B

Se compararon estas formas:

```text
A: p = 1; p = p * L[i,i]; return p * p
B: d = 1; d = d * (L[i,i] * L[i,i]); return d
```

Se elige **A**. Las razones normativas son:

- corresponde literalmente a `product(diag(L))^2`;
- realiza `n + 1` multiplicaciones frente a `2n` en B para `n > 1`;
- redondea una vez por entrada y una vez al cuadrar, mientras B redondea cada
  cuadrado y vuelve a redondear al acumularlo;
- retrasa el cuadrado hasta después de combinar las escalas diagonales;
- evita overflow prematuro de `L[i,i] * L[i,i]` y underflow prematuro del mismo
  cuadrado cuando diagonales grandes y pequeñas pueden compensarse antes;
- reduce casos artificiales `Inf * 0 -> NaN` creados por haber desbordado un
  cuadrado y subdesbordado otro de manera independiente.

A no elimina todo overflow o underflow. El producto parcial puede desbordar
antes de encontrar una diagonal pequeña posterior, o subdesbordar antes de una
grande; el cuadrado final también puede hacerlo. Corregir esos casos requeriría
escalado, log-domain, reordenamiento o precisión adicional, todos fuera de V1.

Las dos formas son equivalentes sobre reales exactos, pero no bajo redondeo
IEEE. B queda rechazada para V1 y no es una transformación válida de A.

## 9. Semántica IEEE por caso

El overload usa las operaciones IEEE ordinarias de `float32` o `float64`:

- **diagonal positiva finita:** el producto sigue el redondeo de `T`; el
  cuadrado final es no negativo salvo NaN producido por una operación previa;
- **diagonal negativa finita:** cambia el signo del producto parcial como
  cualquier multiplicación. El cuadrado final elimina ese signo; no hay
  excepción ni valor absoluto explícito;
- **`+0` o `-0`:** el signo del producto parcial sigue IEEE y puede verse
  afectado por otras diagonales negativas. Si el producto llega finitamente a
  `+0` o `-0`, `p * p` devuelve `+0` porque ambos operandos tienen el mismo
  signo;
- **NaN:** al alcanzar esa diagonal el producto pasa a NaN y el resultado final
  es NaN. No se promete payload ni signo de NaN más allá del contrato IEEE y
  backend vigente;
- **`+Inf` o `-Inf`:** sin cero ni NaN en la secuencia relevante, el producto
  llega a infinito con signo IEEE y el cuadrado devuelve `+Inf`. Multiplicar
  cero por infinito en cualquier orden produce NaN, que llega al resultado;
- **subnormales:** participan sin flush-to-zero contractual. Pueden permanecer
  subnormales o redondear a cero según las operaciones de la precisión;
- **overflow:** cualquier multiplicación puede producir infinito. Una
  multiplicación posterior por cero produce NaN; no hay saturación ni error;
- **underflow:** cualquier producto parcial o el cuadrado final puede producir
  un subnormal o cero. Si el valor final es cero por un cuadrado de operandos
  iguales, su signo es positivo.

No se promete que el resultado permanezca finito para todo factor legítimo ni
que un determinante real no cero no subdesborde. La reproducibilidad se define
por esta secuencia fija en la misma precisión y bajo las reglas backend del
proyecto, no por igualdad entre `float32` y `float64` ni por igualdad bitwise
con kernels LU que tienen otro orden aritmético.

## 10. Caso `0×0`

Un `Cholesky<T> { L: Matrix<T> 0×0 }` pasa el guard. El loop diagonal es vacío,
`p` conserva `One` y la operación final `p * p` devuelve `+1` concreto:

```text
det(Cholesky{L: 0×0}) = +1
```

Ésta es la convención del producto vacío y coincide con determinant V1. No se
lee ninguna celda, no se crea backing y se realizan cero allocations. No hay
special case ni branch numérico específico para `n == 0`.

## 11. Ownership, alias y lifetime

`factor` es shared durante toda la call:

- no se mueve, consume, clona ni muta `factor`;
- no se mueve, consume, clona, copia ni muta `factor.L`;
- no se retiene ni escapa un préstamo en el resultado;
- no se materializan Matrix, Vector, view owning, transpose ni workspace;
- el resultado es un único scalar `T` retornado por valor.

Después del retorno normal, el mismo factor puede usarse en nuevas llamadas a
`det`, en `solve` Vector/Matrix y para observar o imprimir `ch.L`. No existe
alias de storage numérico en el resultado escalar.

## 12. Allocations y coste

Para `L : n×n`:

- tiempo: `O(n)`;
- lecturas elementales: exactamente `n`, todas diagonales;
- multiplicaciones escalares: exactamente `n + 1` según el algoritmo
  normativo;
- storage auxiliar: un acumulador `T` e índices, `O(1)`;
- Matrix/Vector/workspace/transpose: cero;
- allocations de backing u otro owner: exactamente cero para todo `n`, incluido
  `n == 0`.

El guard fallido ocurre antes de cualquier acceso elemental y también realiza
cero allocations. No existe objeto Exception nominal en ninguna ruta del
overload; `ShapeMismatch` conserva el modelo abortivo de `shapeGuard`.

## 13. Capabilities y frontera genérica

El body usa exactamente estas familias escalares sobre `T`:

| capability | uso |
|---|---|
| `One` | inicialización del producto vacío |
| `Mul` | producto diagonal y cuadrado final |

No necesita `Zero`, `Add`, `Sub`, `Div`, `Negate`, `Equal`, `Order`, `Sqrt` ni
`Abs`. El guard y la indexación no agregan una operación escalar sobre `T`.

La superficie pública permanece `T: IEEEFloat`; no expone una conjunción de
capabilities y no amplía el dominio. V1 continúa limitado a `float32` y
`float64` sellados por ese marker. No se agrega Complex.

## 14. Relación con `det(ref LU<T>)`

No se cambia la firma, guards, signo de permutación, orden diagonal,
capabilities, ownership ni semántica IEEE de:

```aether
T det<T: IEEEFloat>(ref LU<T> factor);
```

El overload LU continúa validando sus cuatro relaciones estructurales y
calculando el signo de permutación por `Negate` antes del producto de `U`.
El overload Cholesky tiene un único guard, no usa permutación ni `Negate`, y
cuadra el producto de `diag(L)`.

Ambos kernels permanecen bodies source separados. No se introduce un helper
común si ello agrega branches, flags, guards, capabilities o semántica distinta.
Una futura deduplicación sólo sería admisible si preservara literalmente cada
contrato; no es necesaria para el primer vertical.

La comparación numérica entre ambos overloads sobre factores de una misma SPD
es una prueba de qualification, no una promesa de igualdad bitwise: LU y
Cholesky factorizan y multiplican con órdenes diferentes.

## 15. HIR, MIR, SSA y backend

La implementación futura vive exclusivamente como source ordinario en
`linearAlgebra/src/lib.ae`. No se agregan:

- opcode o recipe HIR/MIR/SSA de determinant Cholesky;
- intrinsic, builtin o helper runtime especializado;
- reconocimiento de `Cholesky`, `det` o del package;
- `TypeId`, allowlist, witness, vtable, boxing o dispatch runtime;
- ABI nuevo ni ruta backend especial.

HIR debe mostrar el préstamo shared, el `shapeGuard`, el literal algebraico
`One`, el loop/indexing diagonal, las operaciones `Mul` y el retorno escalar.
No debe contener construcción de Matrix/Vector, transpose ni capabilities
fuera de §13.

La monomorphization sustituye `T` antes de MIR. Las instancias MIR/SSA contienen
sólo operaciones concretas `float32` o `float64`, branches e indexación; no
retienen parámetros genéricos, nodos capability, `TypeId`, witness, boxing ni
calls indirectas. O0 y O2 deben respetar el orden numérico de §7.

## 16. Qualification del milestone futuro

La qualification cubrirá `float32` y `float64`, en O0 y O2 cuando corresponda.

### Factores legítimos

- `0×0 -> +1` con bit de signo positivo;
- `1×1` y relación `det = L[1,1] * L[1,1]`;
- identity;
- SPD diagonal;
- SPD dense con factor conocido;
- SPD dense producida por `cholesky`;
- comparación con un oráculo de `det(A)` bajo tolerancia apropiada;
- comparación con `det(ref LU)` sobre la misma SPD bajo tolerancia apropiada;
- resultado no negativo para casos legítimos sin NaN;
- reutilización del factor después en observación, otro `det` y `solve`.

### Aggregate manual y casos IEEE

- diagonal negativa con paridad par e impar;
- `+0` y `-0`, verificando `+0` final cuando no se combina con infinito;
- NaN en cada posición diagonal relevante;
- `+Inf` y `-Inf`, con y sin cero en distintas posiciones;
- subnormales y casos que permanecen subnormales o subdesbordan;
- overflow en producto parcial y en cuadrado final;
- casos de escalas mezcladas que distinguen A de B;
- Matrix square con lower y upper off-diagonal arbitrarios, incluidos NaN e
  infinitos, verificando invariancia bitwise al conservar la diagonal;
- ausencia de `NotPositiveDefiniteException`, `SingularMatrixException` y
  `InvalidCholeskyFactorException`.

### Guards, ownership, coste e IR

- `factor.L` rectangular, incluido `0×n`/`m×0`, falla por `ShapeMismatch` antes
  de acceso elemental;
- el guard square es el único guard;
- exactamente `n` lecturas diagonales y ninguna off-diagonal en una
  instrumentación adecuada;
- factor intacto y utilizable después;
- cero move, clone, copia, workspace, transpose y allocations;
- costo `O(n)` y storage escalar `O(1)`;
- HIR genérico con sólo `One` y `Mul` sobre `T`;
- HIR concreto y MIR/SSA `float32`/`float64` sin residuo genérico ni dispatch;
- ausencia de cambios o regresiones en `det(ref LU)` y `det(ref Matrix)`.

Las comparaciones entre algoritmos usan tolerancias acordes a cada precisión;
no reemplazan los casos IEEE exactos y de signed zero, que verifican bits.

## 17. Consumer futuro

El consumer del milestone de implementación mostrará como mínimo:

```aether
var ch = cholesky(A);
var d = det(ch);

println(ch.L);
println(d);

var x = solve(ch, b);
println(x);
```

La lectura de `ch.L` y el solve posterior demuestran que `det(ch)` materializa
un préstamo shared y no consume el factor. El consumer cubrirá ambas
precisiones y comparará el resultado con las rutas Matrix/LU donde corresponda.

## 18. Alternativas rechazadas

| alternativa | motivo |
|---|---|
| forma B, producto de cuadrados | más multiplicaciones y redondeos; overflow/underflow prematuro; no preserva A |
| log-domain o escalado | cambia operaciones, semántica IEEE y capabilities; fuera de V1 |
| acumulador promovido | cambia resultados y lowering; `T` debe ser la precisión efectiva |
| reordenar diagonales por magnitud | requiere storage/branches y rompe el orden reproducible |
| validar diagonal | duplica parcialmente al productor y agrega capabilities sin certificar el factor |
| validar toda `L` | agrega `O(n²)` y una segunda autoridad representacional |
| lanzar por cero o no finitud | contradice la política de factors manuales y la aritmética IEEE elegida |
| consumir o clonar el factor | impide reutilización o asigna/copia sin necesidad |
| reconstruir `A` o `L^T` | costo `O(n²)`/`O(n³)` y storage innecesario |
| unificar a la fuerza con LU | introduce signo/guards/branches y contracts distintos |
| soporte especial del compiler | package source y capabilities ordinarias bastan |

## 19. Fuera de scope

Este milestone no implementa código. También quedan fuera:

- `logdet` y `slogdet`;
- determinant automático vía Cholesky desde Matrix;
- `Complex` y Cholesky Hermitian;
- API checked o validated para factors construidos manualmente;
- productos compensados, escalados o arbitrary precision;
- BLAS/LAPACK;
- cambios a `det(ref LU<T>)` o `det(ref Matrix<T>)`;
- nuevos opcodes, intrinsics o reconocimiento del compiler.

## 20. Criterio de cierre

La arquitectura queda cerrada cuando este documento y su reporte fijan la
firma, semántica matemática, guard único, política de aggregates manuales,
forma A, orden IEEE, `0×0`, ownership, allocations, capabilities, relación con
LU, lowering, qualification y consumer sin decisiones pendientes.

La implementación futura puede proceder sin reabrir arquitectura. Cualquier
cambio de guard, forma de producto, precisión, orden, validación, excepción o
presupuesto de allocations requiere una nueva autoridad explícita.
