# LINEAR-ALGEBRA-CONSTRUCTORS-V1 — reporte de implementación

Estado: **IMPLEMENTADO Y CALIFICADO**, 2026-09-28.

Autoridad:

- [DYNAMIC_SHAPES_AND_SLICES_ARCH_1](DYNAMIC_SHAPES_AND_SLICES_ARCH_1.md)
- [DYNAMIC_SHAPES_AND_SLICES_ARCH_1_REPORT](DYNAMIC_SHAPES_AND_SLICES_ARCH_1_REPORT.md)
- [FILLED_INIT_V1_REPORT](FILLED_INIT_V1_REPORT.md)
- [CONTEXTUAL_OVERLOADS_V1_REPORT](CONTEXTUAL_OVERLOADS_V1_REPORT.md)
- [LINEAR_ALGEBRA_OAL_V1_QR_REPORT](LINEAR_ALGEBRA_OAL_V1_QR_REPORT.md)

## Resultado

El package ordinario `linearAlgebra` expone `zeros`, `ones` e `identity` sin
ninguna modificación de parser, frontend, middle-end, backend o runtime. La
implementación usa únicamente overloads source ordinarios, expected result type
y las primitivas generales `matrixFilled`/`vectorFilled`.

La superficie soportada queda cerrada honestamente a `float32` y `float64`:

```aether
Matrix<float64> a = linearAlgebra.zeros(3, 2);
Matrix<float32> b = linearAlgebra.ones(4);
Vector<float64,Column> c = linearAlgebra.zeros(3);
Vector<float32,Row> d = linearAlgebra.ones(3);
Matrix<float64> i = linearAlgebra.identity(4);
```

No se declara un genérico ficticio: Aether aún no posee capabilities source
que expresen de forma correcta `Zero` y `One` para un `T` arbitrario. Tampoco
se agregaron nombres por shape u orientación como `zerosMatrix`, `zerosRow` o
`zerosColumn`.

## Overloads y contexto

Para cada tipo flotante existen overloads Matrix de una y dos dimensiones y
overloads Vector Row/Column de una dimensión. El expected type selecciona tipo
escalar, clase Matrix/Vector y orientación. No existe prioridad entre Matrix,
Row y Column.

`var value = linearAlgebra.zeros(3)` produce `E0461` por ambigüedad. Con dos
argumentos sólo quedan candidatos Matrix; sin expected type, los candidatos
`float32` y `float64` siguen siendo ambiguos. Un argumento incompatible o un
resultado no soportado produce `E0460`. Al ser overloads concretos y no
genéricos, V1 no ofrece type arguments explícitos para estos constructores.

## Construcción y costos

- Matrix `zeros(n)`/`ones(n)` delega una vez en `matrixFilled(n,n,value)`.
- Matrix `zeros(m,n)`/`ones(m,n)` delega una vez en
  `matrixFilled(m,n,value)`.
- Vector delega una vez en `vectorFilled(length,value)` con su orientación
  nominal concreta.
- `identity(n)` construye `zeros(n,n)` y escribe solamente sus `n` posiciones
  diagonales.

Por el contrato ya calificado de FILLED-INIT-V1, un shape no vacío realiza una
sola allocation y exactamente `m*n` o `length` stores de inicialización; un
shape con extent cero conserva su metadata y no asigna backing. `identity`
cuesta O(n²) por el zero-fill más O(n) stores. No se usa `Matrix.add`, memoria
sin inicializar, raw pointers, multiplicación de matrices ni una ruta de
allocation privilegiada.

La prueba de integración inspecciona HIR, MIR y SSA del package real y confirma
que contienen `MatrixFilled` y `VectorFilled`; LLVM llama los helpers generales
de filled-init. Una prueba nativa instrumenta los contadores del allocator en
O0/O2 y confirma una allocation por constructor no vacío, una allocation para
`identity` y cero allocations para Matrix/Vector con shape vacío.

## Limpieza de QR

Las implementaciones `qr` y `qrFloat32` construyen ahora `Q` mediante
`identity(m)`. Se eliminó tanto `A * transpose_view(A)` usado para fabricar el
shape `m×m` como el doble loop que sobrescribía ese producto con la identidad.
El algoritmo Householder y su orden de actualización no cambiaron.

La calificación numérica previa permanece verde para matrices square, tall,
wide, rank-deficient, identidad, diagonal, cero, entradas negativas, `0×0`,
`m×0`, `0×n`, `float32` y `float64`, en O0 y O2.

## Cobertura

El consumer independiente cubre:

- Matrix square, tall y wide para `zeros` y `ones`;
- overloads de una y dos dimensiones;
- todos los valores de cada matriz no vacía;
- `identity`, incluida cada celda diagonal y off-diagonal;
- `0×0`, `m×0`, `0×n` e `identity(0)`;
- Vector Row y Column para `zeros`/`ones`, incluido length cero;
- constructores `float32` y `float64`;
- toda la batería numérica QR anterior.

La suite Rust dedicada cubre la selección contextual sobre el package real,
los diagnostics de ambigüedad/no-match/result mismatch, los IR de filled-init,
la ausencia de variantes públicas artificiales y la eliminación del workaround
de QR. La prueba de registry publica el archive, marca la versión official,
crea un consumer independiente, ejecuta add/sync y corre el consumer en O0/O2.

## Validación

Se ejecutó correctamente:

```text
aether check linearAlgebra
aether check linearAlgebra/tests/consumer
aether run linearAlgebra/tests/consumer -O0
aether run linearAlgebra/tests/consumer -O2
cargo test -p aether-driver --test linear_algebra_constructors_v1
cargo test -p aether-registry --test registry \
  linear_algebra_oal_publishes_and_runs_real_qr_consumer
cargo test --workspace
cargo fmt --all --check
cargo clippy --workspace --all-targets -- -D warnings
git diff --check
bash compiler-next/tests/run-differential.sh
```

La prueba diferencial completó 21 casos sin fallos.
