# MATRIX-REPRESENTATION-ARCH-1 — reporte

Estado: **ARQUITECTURA CERRADA; SIN IMPLEMENTACIÓN**, 2026-10-03.

Documento normativo:
[MATRIX_REPRESENTATION_ARCH_1](MATRIX_REPRESENTATION_ARCH_1.md).

## Resultado

La auditoría determinó que Aether ya posee el sistema completo de transpose
views. `transpose_view` y `transpose_view_mut` son operaciones públicas del
lenguaje sobre Matrix owners y Matrix views; comparten backing, intercambian
shape/strides en O(1), conservan provenance y lifetime, admiten doble
transposición y no asignan. No se diseñó un segundo sistema ni el alias
camelCase `transposeView`.

Lo que falta realmente son dos operaciones owning generales. Quedaron cerradas
en `std.Math.LinearAlgebra` como source ordinario:

```aether
Matrix<T> transposeCopy<T: Storable + Copy + Zero>(ref Matrix<T> source);
Matrix<T> diagonalMatrix<T: Storable + Copy + Zero>(
    ref Vector<T,Column> values);
Matrix<T> diagonalMatrix<T: Storable + Copy + Zero>(
    ref Vector<T,Row> values);
```

`transposeCopy` produce un owner independiente `n×m`, preserva la fuente y
copia sólo sus `m*n` celdas lógicas. `diagonalMatrix` produce una Matrix dense
`k×k`, preserva el Vector, coloca sus valores en la diagonal y Zero fuera de
ella. Ambos usan una allocation para resultado no vacío, cero para empty,
inicialización completa y ningún buffer auxiliar.

## Capabilities y construcción

No se restringe a `IEEEFloat`: Storable autoriza el owner, Copy permite
duplicar valores sin consumir la entrada y Zero alimenta la inicialización
segura. Para diagonal, Zero es parte del significado. Para transpose es una
limitación explícita del builder `matrixFilled` disponible; evita inventar
memoria sin inicializar o ampliar el compilador. Una futura primitive por
generador podría justificar relajar sólo esa firma a Storable+Copy.

La materialización transpuesta cuesta O(m*n). La diagonal dense cuesta O(k²).
`0×n`, `m×0`, `0×0` y `k=0` conservan sus shapes sin backing. Las fuentes
padded se recorren por indexación lógica/stride y nunca se copia padding.

## Capas y mutabilidad

Las views permanecen infraestructura nativa porque compiler e IR deben conocer
provenance, no-escape y capacidad de escritura. Las dos construcciones owning
pertenecen a std explícita porque son algoritmos generales expresables sobre
`matrixFilled` e indexación. No hay opcode, intrinsic nuevo ni privilegio OAL.
El package OAL `linearAlgebra` existente no debe publicar aliases duplicados.

Una fuente shared nunca produce una view mutable. La mutabilidad continúa
expuesta únicamente por `transpose_view_mut` desde un Place writable. El
contrato actual no promete exclusividad/noalias para `ref mut` o
`MatrixViewMut`; este diseño conserva capacidad de escritura, lifetime léxico,
provenance y bloqueo de move/replacement sin ampliar ownership.

## Integración

El diseño permite obtener `V` desde `SVD.Vt` y construir Sigma desde `S` sin
agregar getters ni cambiar `SVD<T>`:

```aether
Matrix<float64> V = la.transposeCopy(factor.Vt);
Matrix<float64> Sigma = la.diagonalMatrix(factor.S);
MatrixView<float64> Vread = transpose_view(factor.Vt);
```

Los consumers QR y de otros factors pueden elegir de forma visible entre view
sin copia y owner materializado. No hay conversión implícita view-to-owner,
cache, lazy transpose, pseudoinversa ni algoritmo derivado.

## Qualification y secuencia

La qualification cerrada cubre square/tall/wide, todos los zero extents,
owners padded, subviews y views de views, doble transposición, lectura y
escritura mutable, rechazos shared/mutable, lifetime/no-escape, aliasing vigente,
float32/float64/int, O0/O2, cleanup, conteos de allocations, IR monomorfizado y
consumers SVD/QR.

La secuencia mínima es:

1. cerrar con evidencia la exposición/qualification de transpose views ya
   existentes;
2. implementar juntas `transposeCopy` y `diagonalMatrix` en std;
3. ejecutar qualification de cierre e integración SVD/QR.

Los pasos 2 y 3 pueden combinarse. No se modificó source, compiler, runtime,
tests, consumer ni `SVD<T>` durante este milestone.
