# LINEAR-ALGEBRA-GENERIC-CONSTRUCTORS-V1 — reporte de implementación

Estado: **IMPLEMENTADO Y CALIFICADO**, 2026-09-28.

Autoridad normativa:

- [NUMERIC_CAPABILITIES_ARCH_1](NUMERIC_CAPABILITIES_ARCH_1.md)
- [NUMERIC_CAPABILITIES_ARCH_1_REPORT](NUMERIC_CAPABILITIES_ARCH_1_REPORT.md)
- [NUMERIC_CAPABILITIES_V1_REPORT](NUMERIC_CAPABILITIES_V1_REPORT.md)
- [LINEAR_ALGEBRA_CONSTRUCTORS_V1_REPORT](LINEAR_ALGEBRA_CONSTRUCTORS_V1_REPORT.md)

## Resultado

Los overloads concretos `float32`/`float64` de `zeros`, `ones` e `identity`
fueron reemplazados por nueve declaraciones genéricas: cuatro overloads de
`zeros`, cuatro de `ones` y uno de `identity`. Los constraints son exactamente
los mínimos normativos:

```aether
T: Storable + Copy + Zero
T: Storable + Copy + One
T: Storable + Copy + Zero + One
```

Cada overload delega directamente en `matrixFilled<T>` o
`vectorFilled<T,O>` con el literal algebraico `0` o `1`. `identity<T>` crea una
única matriz mediante `zeros<T>(size,size)` y escribe `1` directamente sobre la
diagonal. No hay casts desde integer, helpers de identidad algebraica, dispatch
runtime ni ramas especiales por precisión.

## Inferencia y dominio

El expected result type continúa seleccionando `T`, Matrix frente a Vector y,
para Vector, Row frente a Column. Las formas explícitas ordinarias
`zeros<float32>(...)` y `ones<float64>(...)` funcionan cuando el contexto
determina el overload. La llamada de un argumento sin expected type permanece
ambigua (`E0461`); la forma Matrix rectangular sin expected type informa el
diagnóstico general de parámetro sólo inferible por resultado (`E0462`).

El dominio se amplía intencionalmente a los integers que satisfacen los
constraints. La calificación ejecuta `zeros`, `ones` e `identity` con `int`,
incluidos ambos tipos de Vector. `bool`, `Buffer<int>` y elementos referencia
son rechazados por las rutas generales de overload/constraints/storage. No se
modificó la admisión base de Matrix o Vector.

## IR, ownership y coste

HIR conserva los `GenericParamId` y `AlgebraicValue` de los cuerpos
paramétricos. Las instancias concretas reifican esos valores antes de MIR; MIR
y SSA no contienen tipos genéricos ni valores algebraicos y siguen usando
`MatrixFilled`/`VectorFilled`. LLVM no contiene witnesses ni dispatch por
`TypeId`.

Se conserva una allocation de backing para cada resultado no vacío y cero para
productos de extents cero. `identity` conserva un solo owner Matrix. Los shapes
`0×0`, `m×0`, `0×n` y Vector length cero mantienen su metadata sin colapsarse.

La auditoría source prueba que existe exactamente una implementación por
shape/orientación y que ya no quedan declaraciones constructoras concretas
`float32`/`float64`. LU, solve, det y QR no fueron generalizados; sus suites
siguen compilando y ejecutando contra los nuevos constructors.

## Validación

Se ejecutó correctamente:

```text
cargo test -p aether-driver \
  --test linear_algebra_constructors_v1 \
  --test linear_algebra_lu_v1 \
  --test linear_algebra_solve_v1 \
  --test linear_algebra_solve_matrix_v1 \
  --test linear_algebra_det_v1
aether check linearAlgebra
aether run linearAlgebra/tests/consumer -O0
aether run linearAlgebra/tests/consumer -O2
cargo fmt --all --check
git diff --check
```

La prueba dedicada ejecuta instancias `float32`, `float64` e `int` en O0/O2,
formas inferidas y explícitas, Matrix/Row/Column, shapes vacíos, diagnostics,
IR y conteo exacto de allocations.
