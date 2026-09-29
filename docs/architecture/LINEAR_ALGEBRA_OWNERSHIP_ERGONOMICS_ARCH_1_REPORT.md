# LINEAR-ALGEBRA-OWNERSHIP-ERGONOMICS-ARCH-1 — reporte

Estado: **ARQUITECTURA CERRADA; SIN IMPLEMENTACIÓN**, 2026-09-29.

Documento normativo:
[LINEAR_ALGEBRA_OWNERSHIP_ERGONOMICS_ARCH_1](LINEAR_ALGEBRA_OWNERSHIP_ERGONOMICS_ARCH_1.md).

## Resultado

Se cerró una superficie dual para `linearAlgebra`: los nombres cotidianos
preservan la Matrix mediante `ref` shared y los nombres `InPlace` consumen el
owner y reutilizan su backing.

```aether
lu(A)        / luInPlace(A)
qr(A)        / qrInPlace(A)
cholesky(A)  / choleskyInPlace(A)
det(A)       / detInPlace(A)
solve(A,rhs) / solveInPlace(A,rhs)
```

En source de call se escribe normalmente `lu(A)`: la firma declarada sí es
`lu(ref Matrix<T> A)`, y BORROW-ERGONOMICS-V1 crea el préstamo shared después
de resolverla. Los dos comportamientos tienen spellings distintos; no hay
overload por ownership ni inferencia contextual.

Las seis variantes de factorización son públicas. `InPlace` se eligió sobre
`Owned`, `Consume`, `Move` e `inPlaceLu` porque expresa consistentemente la
intención de performance y deja primero el nombre del algoritmo.

## Ownership y copia

Una call preserving no mueve ni escribe ningún byte de `A`, deja el owner
usable y garantiza que el factor no comparte backing con la fuente. Cada
wrapper crea exactamente una copia lógica y delega en el único kernel
`InPlace`. Este último conserva el comportamiento actual: LU recicla el backing
como `U` para `m <= n` o como `L` para `m > n`; QR como `R`; Cholesky como `L`.

La auditoría confirmó que no existe hoy una copia general de Matrix. Se diseñó
el mínimo necesario: un helper source privado de `linearAlgebra`, restringido a
`IEEEFloat`, que crea capacidad exacta `m×n` y copia por indexación los `m*n`
elementos lógicos. No lee padding ni usa `memcpy`. Una fuente padded produce un
owner exact-capacity; `0×0`, `m×0` y `0×n` conservan shape sin backing.

No se publica `clone/copy`, no cambia assignment y no se agrega intrinsic,
COW, ARC, GC ni reconocimiento compiler de los algoritmos.

## Costos y errores

Cada factorización preserving agrega `O(mn)` de tiempo, `mn` elementos de
storage y exactamente una allocation de backing cuando `m*n > 0`. Luego corre
el mismo kernel. En square, la copia no cambia `O(n³)` pero aumenta memoria
pico y bandwidth en `O(n²)`. Las variantes `InPlace` conservan sus presupuestos
actuales; Cholesky continúa con cero allocations internas del kernel.

Cholesky preserving copia primero y delega toda validación a
`choleskyInPlace`. Por ello allocation/copy puede preceder shape o domain
failure, pero después conserva la precedencia vigente shape → no finito →
asimetría → pivot no positivo. Se descartó prevalidar porque duplicaría lógica
o exigiría un segundo entry point trusted. Cholesky `InPlace` conserva su
validación antes de la primera escritura.

Los guards propios de `det/solve` sobre square shape y RHS compatible sí se
mantienen antes de copiar, en su orden actual.

## `det`, `solve` y compatibilidad

Los overloads desde Matrix adoptan también preserving-by-default y obtienen
variantes públicas `InPlace`. Dejar esas operaciones consuming habría hecho
inconsistente la UX; mantener su parámetro owning mientras llaman al nuevo
`lu(A)` preserving habría consumido una Matrix sólo para copiarla y destruirla.

No cambian `det(ref LU<T>)`, `solve(ref LU<T>, ref Vector)` ni
`solve(ref LU<T>, ref Matrix)`. Los futuros overloads desde `ref Cholesky<T>`
serán igualmente borrowed y reutilizables.

El cambio es semántico pero aceptable antes de estabilización pública. La
mayoría del source sigue compilando, ahora conserva `A` y paga una copia. Los
callers de último uso deben migrar a `InPlace`; function values/forwarders y
tests de moves o allocations deben actualizar sus firmas y expectativas. No se
conserva un overload legacy que difiera sólo por ownership. El alias deprecated
`qrFloat32(Matrix<float32>)` sigue consuming y delegará a `qrInPlace`.

## Qualification cerrada

El vertical recomendado debe comprobar para LU, QR y Cholesky, en O0/O2:

- fuente intacta y usable para preserving, sin alias de backing;
- use-after-move compile-time para `InPlace`;
- equivalencia entre preserving y `InPlace` sobre una copia explícita;
- reutilización exacta del backing y conteos de allocations/frees;
- matrices padded, canarios, capacidades exactas y todos los zero shapes;
- clases/orden de errores y cleanup de Cholesky;
- defaults y variantes `InPlace` de `det/solve`;
- un solo kernel por algoritmo y Borrow/Move correctos en HIR/MIR/SSA;
- ausencia de opcode, intrinsic, allowlist, clone oculto o alias mágico.

## Validación de este milestone

- Se crearon únicamente el documento normativo y este reporte.
- No se modificó `linearAlgebra`, compiler, runtime, tests ni consumer.
- Se preservaron los cambios preexistentes del working tree.
- Firmas, nombres, visibilidad, ownership, copia, padding, costos, rutas
  `det/solve`, orden Cholesky, compatibilidad y primer vertical quedaron
  cerrados.
- `git diff --check` no reporta errores.
