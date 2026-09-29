# LINEAR-ALGEBRA-CHOLESKY-ARCH-1 — reporte de cierre

Estado: **ARQUITECTURA CERRADA; NO IMPLEMENTADA**, 2026-09-28.

Autoridad normativa:

- [LINEAR-ALGEBRA-CHOLESKY-ARCH-1](LINEAR_ALGEBRA_CHOLESKY_ARCH_1.md);
- [NUMERIC-CAPABILITIES-ARCH-1](NUMERIC_CAPABILITIES_ARCH_1.md);
- [NUMERIC-CAPABILITIES-V1](NUMERIC_CAPABILITIES_V1_REPORT.md);
- [NUMERIC-GENERIC-MIGRATION-CLOSURE-1](NUMERIC_GENERIC_MIGRATION_CLOSURE_1_REPORT.md).

## Resultado

Quedó diseñada, pero no implementada, la factorización Cholesky real V1 de
`linearAlgebra`. Será package code ordinario, tendrá una sola implementación
source para los tipos sellados por `IEEEFloat` y no requerirá compiler magic,
runtime dispatch ni cambios de HIR/MIR/SSA.

La API cerrada es:

```aether
struct Cholesky<T: Storable> {
    Matrix<T> L;
}

public class NotSymmetricMatrixException : Exception {
    public init() {}
}

public class NotPositiveDefiniteException : Exception {
    public init() {}
}

Cholesky<T> cholesky<T: IEEEFloat>(Matrix<T> A);
```

`T` se infiere desde el argumento. No habrá overloads `float32`/`float64`,
default float, wrapper por precisión ni mega-lista de capabilities en la
firma.

## Factor y orientación

V1 publica un factor object con una sola Matrix `L` y relación canónica:

```text
A = L L^T
```

`L` es square, lower, materializada y con diagonal positiva. El upper contiene
ceros observables. El aggregate conserva constraint representacional
`T: Storable`, igual que `LU<T>`/`QR<T>`; el kernel productor declara el dominio
`IEEEFloat`.

Lower simplifica el kernel row-oriented, permite reciclar directamente la
entrada y basta para futuros forward/back substitutions. No se materializa
`L^T`, no hay selector upper/lower y no se expone storage packed ambiguo.

## Dominio, simetría y errores

El dominio es Matrix square, finita, exactamente simétrica y positive definite.
La precedencia de checks es normativa:

1. shape square con `shapeGuard`, cuyo fallo es `ShapeMismatch`;
2. finitud y simetría exacta de toda la entrada antes de mutarla;
3. positividad/finitud de cada pivot calculado antes de `sqrt`.

La simetría compara `A[i,j] == A[j,i]` mediante igualdad IEEE exacta. No usa
epsilon ni igualdad bitwise: `+0 == -0` pasa; diferencias finitas, incluso de
un ULP, fallan. Cada valor se considera finito si `(x - x) == 0`, prueba que
rechaza NaN e infinitos sin ampliar capabilities.

Una desigualdad finita lanza `NotSymmetricMatrixException`. Un no finito de
entrada o un pivot calculado no finito/no estrictamente positivo lanza
`NotPositiveDefiniteException`. No se reutiliza `SingularMatrixException`:
singularidad no cubre toda indefinitud. Las excepciones hacen unwind y liberan
la entrada consumida; shape mismatch sigue siendo un trap abortivo.

Para cada diagonal calculada `d` se exige:

```text
(d - d) == 0 && d > 0
```

antes de `sqrt(d)`. Por ello `+0`, `-0`, negativos, NaN e infinitos fallan;
un subnormal positivo puede pasar. No se usa `sqrt` como detector accidental.

## Algoritmo y semántica IEEE

Se eligió Cholesky clásico lower, unblocked, row-oriented, dot-product. Cada
entrada comienza en `A[i,j]` y resta en orden creciente `k` los productos
`L[i,k]*L[j,k]`. La diagonal usa `sqrt`; las entradas inferiores dividen por
la diagonal ya calculada. Al final se pone el upper a `+0`.

No se permite fast-math, reassociation, acumulador promovido ni tolerancia
oculta. NaN/Inf de entrada se rechazan antes de mutar; no finitos intermedios
se rechazan al validar el pivot. Overflow, underflow, signed zero, subnormales
y redondeo conservan la semántica concreta de `float32`/`float64`. Una matriz
SPD sobre reales exactos puede rechazarse si el cálculo concreto pierde un
pivot positivo; no se promete estabilidad perfecta.

Las capabilities efectivamente usadas son `Zero`, `Sub`, `Mul`, `Div`,
`Equal`, `Order` y `Sqrt`, pero la frontera pública permanece
`T: IEEEFloat`.

## Ownership, zero shape y coste

`cholesky(Matrix<T> A)` consume `A`, valida antes de mutar y reutiliza su
backing para `L`. No crea Matrix/Vector auxiliar, transpose ni copia simétrica.
La ruta de éxito realiza exactamente cero allocations propias de Matrix,
Vector, backing u owner auxiliar y usa `O(1)` storage escalar adicional. Su
tiempo es `O(n³)`, más pases `O(n²)` de validación y limpieza. Un fallo nominal
construye sólo el owner ordinario sin payload de la Exception correspondiente;
no crea storage numérico.

`0×0` es válido y devuelve `Cholesky<T> { L: 0×0 }` moviendo el mismo owner
vacío, sin backing ni allocation. `0×n` y `m×0` no square fallan por shape.

En éxito, el backing de entrada queda en `L`. En excepción, unwind lo libera
exactamente una vez y no expone un factor parcial. El trap de shape conserva la
política general sin cleanup por unwind.

## Evolución reservada

El factor `L` basta para futuros overloads `solve(ref Cholesky<T>, ref RHS)`:
forward substitution con `L` y backward substitution leyendo `L^T`, sin
materializar transpose. También basta para un determinant especializado con
`det(A) = product(diag(L))^2`. Ninguna de esas operaciones se implementa ahora.

Una futura variante compleja deberá diseñar `A = L L^H`, conjugación, simetría
Hermitian, diagonal real positiva y la relación entre `Complex<R>` y su real
asociado. Este milestone no modifica `IEEEFloat`/`RealOps`, no inventa `Order`
para Complex y no fija todavía esa firma.

## Lowering y qualification futura

HIR paramétrico usará operaciones capability ordinarias; monomorphization
producirá instancias concretas y MIR/SSA no retendrán genericidad ni nodos
capability. La qualification deberá demostrar calls directas a `sqrtf`/`sqrt`,
ausencia de dispatch, cero allocations del kernel y reutilización del backing.

La matriz de pruebas queda cerrada con `0×0`, `1×1`, identidad, diagonal, SPD
dense, SPD razonablemente ill-conditioned, `float32`/`float64`; y con inputs
rectangulares, semidefinite, indefinite, negativos, singular PSD,
nonsymmetric, NaN, Inf y signed zero. Se verificará `A ≈ L*L^T`, upper
exactamente cero, diagonal positiva, ownership, cleanup, O0/O2, HIR genérico y
MIR/SSA concreto.

## Alcance del cierre

No se modificó código. Quedan fuera Complex, pivoted/incomplete Cholesky,
`LDL^T`, sparse, blocked BLAS/LAPACK, solve, determinant, inverse, rank-one
update/downdate y variantes tolerantes/trusted. La implementación futura puede
proceder sin decisiones arquitectónicas pendientes.
