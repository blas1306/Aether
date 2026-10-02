# LINEAR-ALGEBRA-SVD-ASSEMBLY-V1 — reporte de implementación

Estado: **IMPLEMENTADO Y CALIFICADO**, 2026-10-01.

Autoridad normativa:
[LINEAR-ALGEBRA-SVD-ARCH-1](LINEAR_ALGEBRA_SVD_ARCH_1.md),
[LINEAR-ALGEBRA-SVD-BIDIAGONAL-ARCH-1](LINEAR_ALGEBRA_SVD_BIDIAGONAL_ARCH_1.md)
y
[LINEAR-ALGEBRA-SVD-BIDIAGONAL-QR-ARCH-1](LINEAR_ALGEBRA_SVD_BIDIAGONAL_QR_ARCH_1.md).

## API pública

`linearAlgebra/src/lib.ae` publica exactamente el aggregate thin
`SVD<T>` con fields owning `U`, `S: Vector<T,Column>` y `Vt`, la operación
preserving `svd<T: IEEEFloat>(ref Matrix<T>)`, y las excepciones nominales
`NonFiniteMatrixException` y `NumericalConvergenceException`. La última es la
misma declaración usada por QR-V1, ahora promovida a pública; no hay wrapper ni
traducción. No se agregó `svdInPlace`, full SVD, `Sigma`, rank, pseudoinverse,
condition number ni API low-rank.

Para `k=min(m,n)`, la salida tiene exactamente `U:m×k`, `S:k` column y
`Vt:k×n`. Los casos `m×0`, `0×n` y `0×0` conservan sus extents lógicos y no
crean backing para objetos vacíos.

## Preservación, finitud y pipeline

`svd` crea una sola copia lógica owning mediante el helper normalizado común a
las factorizaciones. La fuente sólo se lee, por sus filas y columnas lógicas,
y sigue utilizable tanto tras éxito como tras una excepción. La copia se
recorre row-major antes de la reducción y cada valor se acepta exactamente si
`(x-x)==0`; el primer NaN o infinito lanza `NonFiniteMatrixException`.

Después de ese gate, la única ruta numérica usa los kernels existentes:
`reduceTallBidiagonal`, materialización thin y
`convergeBidiagonalSVDState`. Wide conserva el descriptor O(1) transpuesto y
sale directamente con orientación pública; assembly no transpone owners ni
conoce otra representación bidiagonal.

Aether rechaza partial moves de fields owning. Por ello la ruta pública
mantiene `d/e/U/Vt` como owners locales separados desde su creación, en vez de
encerrarlos temporalmente en `BidiagonalSVDSeed` para luego copiarlos. Esta
adaptación de ownership no duplica reducción ni QR y permite mover el owner
`d` directamente al field público `S`.

## Signos, ordering y validación final

Tras convergencia, cada `d[i]<+0` se niega y se niega correlacionadamente toda
la fila `i` de `Vt`; `U` no cambia. Todo valor igual a cero se reescribe con el
`+0` del tipo, incluida la representación `-0`. No se usa tolerancia ni se
tratan valores pequeños como cero.

Los triplets se ordenan en orden descendente mediante bubble sort estable
in-place `O(k²)`. Sólo una comparación estricta intercambia vecinos; el mismo
swap mueve columnas de `U` y filas de `Vt`. Valores iguales preservan el orden
producido por QR. No existen índices, permutation arrays ni Matrix temporales.

Antes de construir `SVD<T>` se recorre `S`, luego `U` y luego `Vt`; cualquier
no finito lanza `NumericalConvergenceException`. El constructor final mueve
`U`, el owner `d` renombrado conceptualmente como `S`, y `Vt`, sin copias.

## Ownership y allocations

El máximo workspace sigue el modelo aprobado: una copia `m×n`, `U:m×k`,
`Vt:k×n`, `d/S:k`, `e:k-1`, `tauLeft:k` y `tauRight:k-1`. Assembly sólo usa
scalars y no agrega `Sigma`, owner adicional de `S`, matrices de factors,
transpose owners ni arrays de ordenamiento. Los owners temporales quedan bajo
cleanup estructurado y las excepciones no publican aggregates parciales.

## Qualification e IR

`linear_algebra_svd_assembly_v1.rs` cubre la superficie pública y su cierre,
float32/float64, O0/O2, preserving, shapes thin y vacías, square/tall/wide,
zero y rank deficiency, reconstrucción, ortogonalidad, no negatividad,
ordering, un oráculo analítico independiente, NaN e infinito. La qualification
white-box cubre `-0`, diagonales negativas, sort estable de repetidos,
permutación correlacionada y las identidades nominales de failure de entrada,
convergencia y validación final.

El consumer real importa `linearAlgebra as la`, llama `la.svd(A)`, imprime
`U/S/Vt` y reutiliza `A`; también cubre inferencia, llamada explícita float32 y
forwarding genérico.

La inspección MIR/SSA/LLVM confirma monomorfización float32/float64 y source
ordinario: no quedan generic parameters, witnesses, vtables, `TypeId`, LAPACK,
opcode SVD ni helper numérico de runtime.
