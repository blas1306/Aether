# LINEAR-ALGEBRA-SVD-DERIVED-ARCH-1 — reporte de arquitectura

Estado: **DISEÑADO; NO IMPLEMENTADO**, 2026-10-03.

Autoridad normativa:

- [LINEAR-ALGEBRA-SVD-DERIVED-ARCH-1](LINEAR_ALGEBRA_SVD_DERIVED_ARCH_1.md);
- [LINEAR-ALGEBRA-SVD-ARCH-1](LINEAR_ALGEBRA_SVD_ARCH_1.md);
- [LINEAR-ALGEBRA-SVD-ASSEMBLY-V1](LINEAR_ALGEBRA_SVD_ASSEMBLY_V1_REPORT.md);
- [LINEAR-ALGEBRA-SVD-QUALIFICATION-CLOSURE-1](LINEAR_ALGEBRA_SVD_QUALIFICATION_CLOSURE_1_REPORT.md);
- [IEEE-FLOAT-CONSTANTS-V1](IEEE_FLOAT_CONSTANTS_V1_REPORT.md);
- [NUMERIC-CAPABILITIES-V1](NUMERIC_CAPABILITIES_V1_REPORT.md).

## Resultado

Queda cerrada la arquitectura de las cinco familias derivadas de la SVD thin:
pseudoinversa Moore–Penrose numérica, least-squares de norma mínima, rango
numérico, condición 2 y Eckart–Young para rank dado. Este milestone sólo crea
los dos documentos de diseño; no modifica source, tests, consumer, API pública,
compiler ni capabilities.

Cada familia ofrece una ruta preserving desde `Matrix<T>` y, salvo el contador
representacional estrecho, una ruta desde `SVD<T>` precomputada. Los factors y
RHS son shared borrows, los resultados dense son owners nuevos y las rutas
Matrix llaman exactamente una vez a la SVD pública.

## Política de cutoff cerrada

Pseudoinversa, least-squares y `numericalRank` comparten una sola autoridad. El
default convencional

```text
max(m,n) * epsilon<T>() * sigmaMax
```

no se materializa. Para `sigmaMax>0`, se retiene `sigma` exactamente si
`sigma>0` y
`sigma/sigmaMax > dimensionAsT(max(m,n))*epsilon<T>()`. La comparación
normalizada evita overflow/underflow prematuro por escala de `sigmaMax`. La
conversión privada de dimensión se diseñó por descomposición binaria en
`O(log dimension)`, sin cast genérico, nueva capability o compiler magic.

El cutoff explícito es absoluto, finito y no negativo. Se retiene sólo
`sigma>cutoff`; igualdad se descarta. Negativo, NaN o infinito lanza la nueva y
justificada `InvalidSingularValueCutoffException`. Cero explícito significa
“todos los singular values almacenados no cero”, no rango matemático exacto.

No se publica `pseudoInverseExact`: sobre una SVD floating point ese nombre
confundiría ceros representacionales con exactitud algebraica. La API default
declara semántica numérica truncada. `nonzeroSingularValueCount(ref SVD)` queda
como la consulta explícita y honestamente representacional.

## Semánticas independientes

`condition2` no consulta cutoff: usa todo el espectro thin, retorna infinito
ante `sigmaMin==0`, overflow del cociente o espectro vacío, y admite matrices
rectangulares full rank con valor finito.

`lowRankApproximation(factor,rank)` usa exactamente el primer prefijo de
triplets y admite `rank` entre cero y la dimensión de `S`. No usa rango
numérico. Sus errores spectral y Frobenius leen sólo `S`; el segundo reutiliza
acumulación escalada. Ninguna consulta de error materializa aproximación o
residual.

No se introduce aggregate de factor truncado porque rompería la shape canónica
de `SVD<T>` o agregaría un tipo sin consumers. Tampoco se diseña todavía la
selección automática del mínimo rank por tolerancia: queda separada del
problema de mejor aproximación para rank dado.

## Recursos, errores y compatibilidad

Sobre factores, cada operación dense asignará sólo su resultado; rank,
condición y errores no asignarán backings. Least-squares proyectará y acumulará
directamente sin construir pseudoinversa. No se forman `Sigma`, transpose,
normal equations, copias de factores ni listas de índices.

Los overloads de factor validarán las dos relaciones de shapes necesarias con
`shapeGuard`, sin intentar certificar un aggregate manual. Las rutas Matrix
heredan `NonFiniteMatrixException` y `NumericalConvergenceException` de SVD.
Rank deficiency es input normal. Los overloads `solve` LU/Cholesky/QR no
cambian en nombre, dominio, exact-zero policy ni excepciones.

La frontera sigue siendo `T: IEEEFloat` para float32/float64, con source
ordinario monomorfizado. Quedan prohibidos LAPACK/NumPy productivo, runtime
dispatch, opcodes nuevos y cambios al compilador.

## Secuencia acordada

La implementación futura se divide en seis verticales:

1. infraestructura común de cutoff;
2. pseudoinversa;
3. mínimos cuadrados;
4. rango y condición;
5. low-rank y errores, manteniendo selección automática reservada;
6. qualification de cierre con oráculos independientes, O0/O2, ambas
   precisiones, ownership, allocations, monomorfización e IR.

Cutoff se comparte sólo donde define semántica. Condición y Eckart–Young no se
acoplan artificialmente a esa infraestructura.

## Alcance del cambio

Archivos agregados:

- `docs/architecture/LINEAR_ALGEBRA_SVD_DERIVED_ARCH_1.md`;
- `docs/architecture/LINEAR_ALGEBRA_SVD_DERIVED_ARCH_1_REPORT.md`.

No se implementó ninguna operación ni se modificó una API pública.

## Validación

```text
git diff --check
```

El comando termina correctamente. No se ejecutaron suites de código porque el
milestone es exclusivamente de arquitectura y no altera source ni tests.
