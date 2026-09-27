# LINEAR-ALGEBRA-OAL-V1-QR — reporte de implementación

Estado: **IMPLEMENTADO Y CALIFICADO**, 2026-09-27.

## Resultado

`linearAlgebra/` es un package Aether V1 library-only ordinario y publicable:

```toml
[package]
name = "linearAlgebra"
version = "0.1.0"
aether = "1"
```

Su implementación completa vive en `linearAlgebra/src/lib.ae`. No se cambió el
parser, resolver, compiler, runtime ni standard library; el package usa sólo
`Matrix`, views, multiplicación de matrices, indexación, control de flujo y las
funciones públicas `rows`, `columns`, `sqrt` y `transpose_view`.

## API pública

```aether
struct QR<T: Storable> {
    Matrix<T> Q;
    Matrix<T> R;
}

QR<float64> qr(Matrix<float64> A);
QR<float32> qrFloat32(Matrix<float32> A);
```

El uso principal es:

```aether
import linearAlgebra as la;

la.QR<float64> factor = la.qr(A);
Matrix<float64> Q = factor.Q;
Matrix<float64> R = factor.R;
```

`qr` es deliberadamente el nombre principal y no se expone
`qrHouseholder`. Aether V1 no tiene overloads de funciones ni una capability
genérica `Float`/`Div`; además `sqrt(T)` sólo se resuelve para un tipo float
concreto. Por eso una falsa función genérica sobre `NumericScalar` sería
incorrecta. V1 ofrece `qr` para `float64` y la entrada explícita `qrFloat32`
para `float32`; no promete enteros ni complejos.

## Algoritmo

Para `A` de forma `m×n`, se toma `p = min(m,n)` y se construye un reflector
Householder por columna `k = 1..p` (los índices matemáticos públicos son
one-based).

Se calcula `norm = ||x||₂` sobre `x = R[k:m,k]` con una suma de cuadrados
escalada, evitando el overflow/underflow evitable de formar directamente
`sum(x[i]^2)`, y se escoge `alpha = -copysign(norm, x[1])`. El primer elemento
del reflector queda como `x[1] - alpha`, elección que evita la cancelación de
restar números de igual signo. La cola se normaliza por ese primer elemento;
así el reflector aplicado es `[1; tail]` y su denominador queda acotado. Si la
norma es exactamente cero no se forma reflector ni se divide; la columna ya es
cero. No se decide rank ni se usa tolerancia dentro de `qr`.

No se materializa `H`. Mientras se aplica, el primer elemento del reflector
está en una variable y su cola permanece temporalmente bajo la diagonal de la
columna activa de `R`. Se actualiza primero `Q <- Q H`, después las columnas de
`R` a la derecha, y sólo entonces se escribe `R[k,k] = alpha` y se anula la
cola. El resultado materializa `Q` de forma `m×m` y `R` de forma `m×n`.

La API pública actual no ofrece un constructor de Matrix con dimensiones
dinámicas. La implementación obtiene legalmente el workspace `m×m` mediante
`A * transpose_view(A)` y sobrescribe todas sus entradas con la identidad antes
de observarlas. Esto también conserva correctamente formas con dimensiones
cero y no introduce un constructor privilegiado.

## Semántica rectangular y degenerada

- Square: `Q` es `m×m` y `R` es triangular superior `m×m`.
- Tall (`m > n`): `Q` sigue siendo completa `m×m`; `R` es trapezoidal `m×n`.
- Wide (`m < n`): se construyen `m` reflectores y `R` es trapezoidal `m×n`.
- Rank-deficient: las columnas nulas exactas se omiten; no hay pivoting ni
  estimación de rank.
- Matriz cero: devuelve una `Q` identidad y `R` cero.
- Formas `0×0`, `m×0` y `0×n`: están cubiertas cuando se pueden construir con
  las operaciones públicas; los loops vacíos conservan formas y producen la
  identidad correspondiente.

Para entradas reales finitas se verifica `A ≈ Q R`, `QᵀQ ≈ I` y que las
entradas de `R` bajo la diagonal sean cero. NaN e infinito no tienen contrato
especial en V1.

## Calificación numérica

El consumer independiente versionado en `linearAlgebra/tests/consumer` cubre:

- 2×2 y el ejemplo clásico 3×3;
- rectangular tall y wide;
- rank-deficient;
- identidad, diagonal, cero y entradas negativas;
- `0×0`, `m×0` y `0×n`;
- `float64` y `float32`.

Cada caso calcula elemento a elemento el residual `A - QR`, la ortogonalidad
`QᵀQ - I` y la estructura trapezoidal. Las tolerancias son `1e-10` para los
casos generales `float64`, `1e-9` para el caso deficiente y `2e-5` para
`float32`; no se usa igualdad exacta para validar resultados flotantes. La
comparación conocida usa la matriz clásica
`[12,-51,4; 6,167,-68; -4,24,-41]` y verifica
`abs(diag(R)) = [14,175,35]` dentro de tolerancia.

Ejecución directa comprobada:

```text
aether check linearAlgebra
aether check linearAlgebra/tests/consumer
aether run linearAlgebra/tests/consumer -O0
aether run linearAlgebra/tests/consumer -O2
```

## Publicación y consumo por package manager

`aether publish linearAlgebra --dry-run` valida el package y el archive cerrado:

```text
package: linearAlgebra@0.1.0
files:
  aether.toml
  src/lib.ae
```

La prueba
`aether-registry/tests/registry.rs::linear_algebra_oal_publishes_and_runs_real_qr_consumer`
realiza sin Internet público el flujo completo sobre un registry de test
persistente:

1. construye y publica el archive `linearAlgebra@0.1.0`;
2. marca administrativamente esa versión como official;
3. crea un consumer independiente sin dependencies;
4. ejecuta el equivalente de `aether add linearAlgebra <consumer>`;
5. ejecuta `sync` y comprueba manifest y lock;
6. compila el `import linearAlgebra as la` desde el package materializado;
7. ejecuta toda la batería QR en O0 y O2.

Se ejecuta con:

```text
cargo test -p aether-registry --test registry \
  linear_algebra_oal_publishes_and_runs_real_qr_consumer
```

## Limitaciones V1

- La API materializa `Q` completa; no hay representación compacta.
- No hay QR pivoted ni rank-revealing.
- No hay `Complex<T>`.
- `float32` necesita el nombre secundario `qrFloat32` hasta que el lenguaje
  admita overloads o una restricción float con división y `sqrt`.
- No se agregan LU, Cholesky, SVD, eigenvalues, solve, sparse ni bindings
  BLAS/LAPACK.
