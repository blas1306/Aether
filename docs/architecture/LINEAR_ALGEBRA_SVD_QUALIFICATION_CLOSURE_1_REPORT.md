# LINEAR-ALGEBRA-SVD-QUALIFICATION-CLOSURE-1 — reporte de cierre

Estado: **CLOSED**, 2026-10-02.

Autoridad normativa:

- [LINEAR-ALGEBRA-SVD-ARCH-1](LINEAR_ALGEBRA_SVD_ARCH_1.md);
- [LINEAR-ALGEBRA-SVD-BIDIAGONAL-ARCH-1](LINEAR_ALGEBRA_SVD_BIDIAGONAL_ARCH_1.md);
- [LINEAR-ALGEBRA-SVD-BIDIAGONAL-QR-ARCH-1](LINEAR_ALGEBRA_SVD_BIDIAGONAL_QR_ARCH_1.md);
- [LINEAR-ALGEBRA-SVD-ASSEMBLY-V1](LINEAR_ALGEBRA_SVD_ASSEMBLY_V1_REPORT.md);
- reportes V1 de stable norm, bidiagonalización y QR bidiagonal.

## Resultado

La SVD thin pública queda calificada y cerrada para `float32` y `float64`, en
O0 y O2. No apareció un defecto numérico ni una brecha contractual. Este
milestone no modifica `linearAlgebra/src/lib.ae`, no agrega API y no cambia el
algoritmo, sus tolerancias productivas ni sus contratos.

La qualification nueva reside exclusivamente en
`compiler-next/crates/aether-driver/tests/linear_algebra_svd_qualification_closure_1.rs`.
Compila consumers públicos reales contra el paquete, ejecuta las instancias
concretas y usa el acceso white-box sólo para inyectar los failures y medir los
recursos privados que la API no puede solicitar.

## Oráculo independiente

El host de qualification entrega los mismos fixtures a NumPy y a Aether. El
oráculo ejecuta `numpy.linalg.svd(matrix, compute_uv=False)` con el dtype
concreto. NumPy/LAPACK sólo se invoca desde el proceso Rust de test: no se
importa en source Aether, no se enlaza al ejecutable calificado y no existe
como dependencia productiva. No se forma `A^T A` y ninguna implementación
Aether actúa como referencia.

Sólo se comparan los singular values descendentes. `U` y `Vt` se validan por
sus invariantes, nunca elemento a elemento contra el oráculo.

## Batería y criterios

La batería reproducible incluye matrices dense deterministas hasta `16x12`,
square, tall, wide, `24x3` y `3x24`, cero, extents `7x0`, `0x9` y los vacíos ya
cerrados por assembly, dependencia exacta simultánea de filas y columnas,
rank deficiency numérica, valores repetidos y cercanos, espectros separados,
mal condicionamiento, una Hadamard ortogonal, diagonales de signo mixto,
subnormales y escalas desde subnormal hasta aproximadamente `1e306` en
float64 y `1e36` en float32. Los fixtures densos no dependen de random state.

Para una Matrix no cero se usa `scale=max(abs(A[i,j]))`. La reconstrucción se
acumula como `U[i,q]*(S[q]/scale)*Vt[q,j]`, no formando primero un residual
dimensional que pudiera overflowear o underflowear. El caso `scale==0` tiene
ruta explícita y nunca divide por cero.

Los límites por entrada son:

```text
float64: 2e-12
float32: 3e-4

|S/scale-Sref/scale| <= tol*(1+|Sref/scale|)
|Ahat/scale-A/scale| <= tol*(1+|A/scale|)
|U^T U-I|, |Vt Vt^T-I| <= tol
```

Son límites fijos de backward error para esta batería moderada, más estrictos
que los fixtures públicos anteriores; no se ajustan por caso ni por resultado.
El piso absoluto está expresado en unidades de la escala de entrada. Por ello
los valores por debajo del error backward esperable no se reinterpretan como
rango numérico, de acuerdo con el contrato V1. Además se comprueban shapes
thin, `S>=+0`, ordering, y finitud completa de `S`, `U`, `Vt` y reconstrucción.

La batería cubre las rutas de norma estable, cambio de escala global,
deflation, Wilkinson shift y zero chase. Las qualifications V1 privadas
mantienen además los fixtures dirigidos de igualdad exacta con el umbral,
shift analítico/escalado, diagonal cero interior, cero trailing y subnormal.
Todas convergen dentro del budget productivo.

## Fallos y ownership

La qualification conjunta comprueba:

- NaN y `+/-Inf` públicos producen `NonFiniteMatrixException` antes de la
  reducción;
- cap cero sobre un bloque activo produce
  `NumericalConvergenceException`;
- estado QR interno no finito produce la misma excepción;
- el owner fuente público conserva shape y valores tras captura;
- el resultado owning sólo existe en la arista normal;
- unwind libera exactamente una vez todos los backings y el objeto excepción.

Los contadores observados son `3 allocations/3 frees` para input no finito
(fuente, workspace y excepción) y `5/5` para los failures QR inyectados
(`d/e/U/Vt` y excepción). No se publica un aggregate parcial.

## Recursos, complejidad e IR

Una llamada pública no vacía observa exactamente ocho allocations y ocho
frees contando la Matrix fixture: una entrada del consumer y los siete owners
del pipeline (`workspace`, `U`, `Vt`, `d/S`, `e`, `tauLeft`, `tauRight`). Los
extents vacíos observan cero backings. La qualification de QR confirma que el
número no depende de los steps y que un step agrega cero allocations.

La inspección source e IR conserva:

- un workspace `m*n` y factors thin `m*k`, `k`, `k*n`;
- cero matrices Householder, cero `Sigma`, cero transpose owning;
- budget finito checked `64*k*k`;
- monomorfización concreta float32/float64 sin generic residue, witnesses,
  vtables ni `TypeId` en LLVM;
- source ordinario, sin opcode SVD, LAPACK productivo o runtime numérico
  especial.

No se observa cambio semántico en otros kernels: la regresión completa del
workspace pasa sin modificar source productivo ni goldens.

## Tiempos representativos

En la máquina de cierre, el ejecutable que contiene toda la batería
independiente tarda aproximadamente 2 ms en O0 y 1 ms en O2; el test completo,
incluyendo dos consultas NumPy, cuatro compilaciones/enlaces y checks de
recursos, tarda aproximadamente 6 s. El consumer monolítico de todo
`linearAlgebra` tarda aproximadamente 3 min 20 s en O0 y 5 min en O2,
dominados por compilación/enlace. No se impone ninguno de estos tiempos como
límite contractual.

## Validación ejecutada

```text
cargo test -p aether-driver --test linear_algebra_svd_qualification_closure_1
aether run linearAlgebra/tests/consumer -O0
aether run linearAlgebra/tests/consumer -O2
cargo test --workspace
cargo fmt --all --check
cargo clippy --workspace --all-targets -- -D warnings
bash compiler-next/tests/run-differential.sh
git diff --check
```

Todos los comandos terminan correctamente. El differential informa 21 casos,
cero fallos. El cierre no implementa pseudoinverse, rank, condition number,
PCA, mínimos cuadrados ni otra operación derivada.
