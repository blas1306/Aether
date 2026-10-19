# LINEAR-ALGEBRA-SYMMETRIC-EIGEN-ARCH-1 — reporte de cierre

Estado: **ARQUITECTURA CERRADA; NO IMPLEMENTADA**, 2026-10-19.

Documento normativo:
[LINEAR-ALGEBRA-SYMMETRIC-EIGEN-ARCH-1](LINEAR_ALGEBRA_SYMMETRIC_EIGEN_ARCH_1.md).

## Resultado

Quedó diseñada, pero no implementada, la eigendecomposition real simétrica de
`linearAlgebra`:

```aether
public struct SymmetricEigen<T: Storable> {
    Vector<T,Column> values;
    Matrix<T> vectors;
}

public SymmetricEigen<T> symmetricEigen<T: IEEEFloat>(
    ref Matrix<T> A);
```

Para `A:n×n`, `values` tiene dimensión `n`, `vectors` es `n×n`, cada columna
`vectors[:,j]` corresponde a `values[j]`, y los valores salen ascendentes. La
entrada se presta shared y se preserva; ambos fields del resultado son owners
independientes.

No se agregó una ruta eigenvalues-only, variante `InPlace`, tolerance de
simetría, opciones ni aliases. Esas superficies requieren beneficios y
qualification propios.

## Dominio y errores

La Matrix debe ser square, finita y exactamente simétrica. La precedencia es:

1. no square: `shapeGuard` y `ShapeMismatch`;
2. cualquier NaN/infinito: `NonFiniteMatrixException`;
3. cualquier pareja finita desigual: `NotSymmetricMatrixException`;
4. fallo de iteración o estado/resultado interno no finito:
   `NumericalConvergenceException`.

Se reutilizan las tres excepciones públicas existentes; no se introduce
`NonSymmetricMatrixException`. La igualdad es IEEE ordinaria, por lo que
`+0==-0`, pero no se acepta una Matrix sólo aproximadamente simétrica. El
caller controla explícitamente cualquier symmetrization según su escala y
modelo de error.

No se exige positive definiteness. Zero, singular, semidefinite, indefinite,
repeated y clustered spectra pertenecen al dominio.

## Algoritmo cerrado

La ruta general obtiene una escala máxima, trabaja sobre una copia normalizada
del triángulo inferior y ejecuta:

1. reducción Householder simétrica compacta a `d/e`;
2. conservación de colas de reflectors en el workspace y `tau` separado;
3. materialización directa de `Qh`, sin matrices Householder;
4. QR implícito con shift de Wilkinson escalado sobre la tridiagonal;
5. deflation local derivada de epsilon, splitting de bloques y bulge chasing;
6. acumulación inmediata de cada Givens en columnas de `vectors`;
7. rescale, canonicalización de zero y sort ascendente de eigenpairs.

Se eligió QR frente a QL para mantener un chase creciente natural con índices
one-based `usize`, selección trailing y reutilización conceptual de
`stableHypot`/Givens/rotación de columnas. QL es el algoritmo espejo sin una
ventaja general de estabilidad para V1. La dirección adaptativa queda como
optimización interna futura.

Jacobi, characteristic polynomial y QR dense repetido fueron rechazados como
kernels productivos. No se forma `T`, `diag(values)`, una Matrix de cada
reflector ni historial de rotaciones.

## Ordering y no unicidad

El orden público es ascendente, consistente con familias simétricas
`eigh`/LAPACK. El sort permuta values y columnas juntas. No promete estabilidad
dentro de valores iguales.

No se canonicalizan signos. Para multiplicidades, cualquier base ortonormal
del eigenspace es válida. Determinismo de una implementación concreta no
convierte signos ni bases en contrato.

## Convergencia, recursos y complejidad

Deflation usa:

```text
abs(e[i]) <= epsilon<T>() * (abs(d[i]) + abs(d[i+1]))
```

evaluado mediante escala local para evitar overflow de la suma. Cada bloque
activo recibe un Wilkinson shift normalizado; ni el shift dimensional ni
restas extremas se materializan sin escala.

El budget global es `64*n` sweeps completos. Un split no lo reinicia. Esto
acota la tridiagonal a `O(n²)` rotaciones y su acumulación a `O(n³)`, y evita
un loop ilimitado o un cap que habilite `O(n⁴)`. Un hook privado permitirá
calificar el failure path.

La ruta general tiene peak de dos matrices `n×n` —workspace y resultado— más
`O(n)` vectores: `d`, `e`, `tau` y scratch. El coste total es `O(n³)` y el
storage, incluido resultado, `2n²+O(n)`. Los casos `0×0`, `1×1`, diagonal y
zero tienen rutas directas.

## Qualification y próximos milestones

La qualification futura cubrirá float32/float64 y O0/O2; vacíos, diagonal,
dense symmetric, positive definite, indefinite, zero, singular, repeated,
clustered, split blocks y escalas extremas; errores, precedence, preservation,
allocations y budget.

Comprobará residual, ortogonalidad y reconstrucción:

```text
A*Q ≈ Q*diag(values)
Q^T*Q ≈ I
Q*diag(values)*Q^T ≈ A
```

Los values se contrastarán con `numpy.linalg.eigh/eigvalsh` sólo desde el host
de test. Eigenvectors no se compararán elemento a elemento: multiplicidades y
clusters se evaluarán mediante residuals y projectors/subspaces, nunca signos.

La secuencia posterior queda dividida en reducción tridiagonal, QR
tridiagonal, assembly público y qualification closure. Este milestone creó
únicamente el documento normativo y este reporte; no modificó source, tests,
consumer, compiler, runtime ni standard library.
