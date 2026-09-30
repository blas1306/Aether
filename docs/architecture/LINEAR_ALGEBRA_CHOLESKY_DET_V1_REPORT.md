# LINEAR-ALGEBRA-CHOLESKY-DET-V1 — reporte de implementación

Estado: **IMPLEMENTADO Y CALIFICADO**, 2026-09-29.

Autoridad normativa:

- [LINEAR-ALGEBRA-CHOLESKY-DET-ARCH-1](LINEAR_ALGEBRA_CHOLESKY_DET_ARCH_1.md);
- [LINEAR-ALGEBRA-CHOLESKY-DET-ARCH-1-REPORT](LINEAR_ALGEBRA_CHOLESKY_DET_ARCH_1_REPORT.md);
- [LINEAR-ALGEBRA-CHOLESKY-ARCH-1](LINEAR_ALGEBRA_CHOLESKY_ARCH_1.md);
- [LINEAR-ALGEBRA-CHOLESKY-V1](LINEAR_ALGEBRA_CHOLESKY_V1_REPORT.md);
- [LINEAR-ALGEBRA-CHOLESKY-SOLVE-ARCH-1](LINEAR_ALGEBRA_CHOLESKY_SOLVE_ARCH_1.md);
- [LINEAR-ALGEBRA-CHOLESKY-SOLVE-V1](LINEAR_ALGEBRA_CHOLESKY_SOLVE_V1_REPORT.md);
- [LINEAR-ALGEBRA-GENERIC-DET-V1](LINEAR_ALGEBRA_GENERIC_DET_V1_REPORT.md).

## Resultado y API

`linearAlgebra/src/lib.ae` incorpora exactamente el overload público:

```aether
T det<T: IEEEFloat>(ref Cholesky<T> factor);
```

Coexiste por nominalidad con `det(ref LU<T>)` y `det(ref Matrix<T>)`; esas dos
rutas, `detInPlace` y sus algoritmos no fueron modificados. No se agregaron
wrappers por precisión, aliases, selector de algoritmo ni variante consuming.

## Guard y aggregate manual

La primera sentencia ejecutable es el único guard square. La sintaxis de
referencias de Aether requiere la desreferencia explícita equivalente:

```aether
shapeGuard(rows((*factor).L) == columns((*factor).L));
```

Inmediatamente después se fija `n = rows((*factor).L)`. El guard precede la
inicialización de `p`, cualquier aritmética sobre `T` y todo acceso elemental.
Su fallo conserva el trap `ShapeMismatch`, sin allocation ni lectura de celda.

No se revalidan positividad, no nulidad o finitud de la diagonal,
triangularidad, upper cero, procedencia ni SPD. Un `Cholesky<T>` manual square
entra directamente al kernel IEEE. No se construye ni lanza
`NotPositiveDefiniteException`, `SingularMatrixException` o
`InvalidCholeskyFactorException`.

## Algoritmo, lecturas y orden IEEE

La implementación es literalmente la forma A en orden ascendente:

```aether
T p = 1;
usize i = 1;
while (i <= n) {
    p = p * (*factor).L[i,i];
    i = i + 1;
}
return p * p;
```

Cada iteración hace una única lectura `L[i,i]`, una multiplicación y actualiza
`p` antes de la siguiente. El retorno hace la multiplicación adicional
`p * p`. No hay lectura lower/upper off-diagonal, forma B, reassociation,
fast-math contractual, FMA, reducción paralela, promoción, `abs`, log-domain,
scaling ni producto compensado.

Los aggregates manuales preservan el comportamiento IEEE de diagonales
negativas, `+0`, `-0`, NaN, `+Inf`, `-Inf`, subnormales, overflow y underflow.
La qualification incluye escalas mixtas que producen un resultado finito con
forma A donde el producto de cuadrados desbordaría y subdesbordaría antes de
combinarse. También cambia arbitrariamente ambas mitades off-diagonal a NaN e
infinito y obtiene el mismo resultado con diagonal idéntica.

## Zero shape, ownership y coste

Para `L 0×0` el guard pasa, el loop queda vacío y se ejecuta `one * one`, con
resultado exacto `+1`, cero lecturas y cero allocations. No existe branch
especial para `n == 0`.

`factor` es un préstamo shared. El kernel no mueve, clona, copia ni muta el
factor o `L`, no crea Matrix/Vector/view/transpose/workspace y sólo retorna el
scalar `T`. El consumer calcula `det(ch)`, imprime `ch.L` y el resultado y
reutiliza después el mismo factor en `solve`, tanto para `float32` como para
`float64`.

Para orden `n`, el coste queda fijado en `O(n)`, exactamente `n` lecturas
diagonales, exactamente `n + 1` multiplicaciones, `O(1)` storage escalar y
cero allocations propias para todo `n`. La instrumentación de qualification
confirma que llamar a `det` no incrementa los contadores de heap, incluido el
caso `0×0`.

## Capabilities y lowering

Sobre `T`, el body paramétrico usa sólo `One` y `Mul`. No usa `Zero`, `Add`,
`Sub`, `Div`, `Negate`, `Equal`, `Order`, `Sqrt` ni `Abs`; la frontera pública
permanece `T: IEEEFloat`.

La implementación es source ordinario del package. HIR conserva el shared
borrow, `ShapeGuard`, `One`, el loop/indexado diagonal y `Mul`. Las instancias
MIR/SSA y LLVM de qualification son concretas para `float32` y `float64`, sin
`GenericParam`, capability nodes, `TypeId`, witness, vtable, boxing o dispatch
indirecto. No se añadió opcode, intrinsic, helper runtime ni reconocimiento
especial del compilador.

## Qualification y regresión

La suite `linear_algebra_cholesky_det_v1.rs` cubre en O0 y O2:

- `0×0`, `1×1`, SPD dense y ambas precisiones;
- comparación tolerante con `det(A)` y `det(ref LU)`;
- factor producido por `cholesky` y reutilización posterior con `solve`;
- aggregates manuales con signos, ceros, NaN, infinitos, escalas extremas,
  overflow y underflow;
- invariancia frente a lower y upper off-diagonal no finitos;
- precedencia del único `shapeGuard` para un factor rectangular;
- cero allocations adicionales;
- forma source, capabilities y ausencia de residuo genérico tras
  monomorphization.

El consumer del package ejerce el flujo dogfood normativo en `float32` y
`float64`. Las suites previas preservan las rutas LU/Matrix determinant,
Cholesky, Cholesky solve, LU solve, QR y ergonomía de ownership.

Quedan fuera logdet/slogdet, selección automática de Cholesky desde Matrix,
Complex, API de validación de factores, scaling, producto compensado,
arbitrary precision y BLAS/LAPACK.
