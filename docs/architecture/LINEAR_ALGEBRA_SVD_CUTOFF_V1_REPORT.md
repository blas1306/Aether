# LINEAR-ALGEBRA-SVD-CUTOFF-V1 — reporte de implementación

Estado: **IMPLEMENTADO Y CALIFICADO**, 2026-10-03.

Autoridad normativa:

- [LINEAR-ALGEBRA-SVD-DERIVED-ARCH-1](LINEAR_ALGEBRA_SVD_DERIVED_ARCH_1.md);
- [LINEAR-ALGEBRA-SVD-DERIVED-ARCH-1-REPORT](LINEAR_ALGEBRA_SVD_DERIVED_ARCH_1_REPORT.md);
- [LINEAR-ALGEBRA-SVD-ARCH-1](LINEAR_ALGEBRA_SVD_ARCH_1.md);
- [LINEAR-ALGEBRA-SVD-ASSEMBLY-V1](LINEAR_ALGEBRA_SVD_ASSEMBLY_V1_REPORT.md);
- [IEEE-FLOAT-CONSTANTS-V1](IEEE_FLOAT_CONSTANTS_V1_REPORT.md);
- [NUMERIC-CAPABILITIES-V1](NUMERIC_CAPABILITIES_V1_REPORT.md).

## Resultado

`linearAlgebra/src/lib.ae` incorpora la infraestructura privada compartida de
clasificación de singular values y publica únicamente
`InvalidSingularValueCutoffException` y
`nonzeroSingularValueCount(ref SVD<T>)`. No se incorporaron pseudoinversa,
least-squares, `numericalRank`, `condition2`, objetos de policy ni overloads
sobre `Matrix`.

Los factores ejecutan los dos guards estructurales normativos, sin exigir
`p==min(m,n)` ni certificar ordering, ortogonalidad o finitud de aggregates
manuales. El conteo público recorre `S` literalmente y cuenta `value != 0`;
por ello ambos ceros con signo se descartan y no intervienen epsilon ni cutoff.

## Cutoff y clasificación común

La validación explícita tiene una sola autoridad privada y acepta exactamente
los valores que satisfacen `(cutoff-cutoff)==0 && cutoff>=0`. Negativos, NaN y
ambos infinitos lanzan `InvalidSingularValueCutoffException`, incluso si el
espectro está vacío. `+0` y `-0` son válidos.

Dos overloads privados de `retainedSingularValueCount` constituyen la frontera
compartida para los futuros consumers. Como `S` es descendente y no negativa,
devuelven el largo del prefijo retenido. La ruta explícita usa estrictamente
`sigma>cutoff`. La ruta default retorna cero para espectro vacío o
`sigmaMax==0`; en otro caso compara estrictamente
`sigma/sigmaMax > dimensionAsT(max(m,n))*epsilon<T>()`. Nunca materializa el
producto del threshold por `sigmaMax`.

`dimensionAsT` descompone el `usize` en binario y acumula potencias obtenidas
por doubling. Sólo usa capabilities existentes, tarda `O(log(value))`, ocupa
`O(1)` y no depende de casts genéricos ni cambios de compiler.

## Recursos y qualification

Los helpers reciben shared borrows, sólo mantienen escalares, no copian
`U/S/Vt`, no crean `Vector`/`Matrix` y agregan cero allocations. La
clasificación y el conteo son `O(p)` como máximo.

`linear_algebra_svd_cutoff_v1.rs` califica en O0 y O2:

- conversión de cero, uno, potencias/fronteras de precisión y `usize::MAX` a
  float32/float64;
- clasificación default normal, vacía, `sigmaMax==0`, igualdad y vecinos del
  threshold, subnormales y magnitudes extremas;
- cutoff explícito cero, `-0`, negativo, NaN y ambos infinitos;
- conteo representacional manual, todos cero, todos no cero, vacío y shapes
  inválidas;
- privacidad de helpers, cierre de superficie, monomorfización y ausencia de
  owners/allocations atribuibles a los helpers.

La qualification usa la razón normalizada como oráculo operacional y un caso
subnormal donde formar primero el threshold absoluto cambiaría el resultado
por rounding prematuro.
