# LINEAR-ALGEBRA-SOLVE-MATRIX-ARCH-1 — múltiples RHS sobre LU

Estado: **ARQUITECTURA CERRADA; NO IMPLEMENTADA**, 2026-09-28.

Este milestone define la extensión de `linearAlgebra.solve` para resolver
sistemas cuadrados con un RHS matricial. Es exclusivamente documental: no
modifica `linearAlgebra/src/lib.ae`, el compilador, el runtime ni los tests.

Autoridad relacionada:

- [LINEAR-ALGEBRA-SOLVE-ARCH-1](LINEAR_ALGEBRA_SOLVE_ARCH_1.md);
- [LINEAR-ALGEBRA-SOLVE-ARCH-1-REPORT](LINEAR_ALGEBRA_SOLVE_ARCH_1_REPORT.md);
- [LINEAR-ALGEBRA-SOLVE-V1](LINEAR_ALGEBRA_SOLVE_V1_REPORT.md);
- [LINEAR-ALGEBRA-LU-V1](LINEAR_ALGEBRA_LU_V1_REPORT.md);
- [SHAPE-GUARD-V1](SHAPE_GUARD_V1_REPORT.md).

## 1. Decisión resumida

La extensión resuelve:

```text
A X = B
A : n×n
B : n×q
X : n×q
T : float32 o float64
```

mediante la LU con pivoting parcial existente. La superficie pública nueva
queda cerrada en cuatro overloads concretos:

```aether
Matrix<float64> solve(
    Matrix<float64> A,
    ref Matrix<float64> B);

Matrix<float32> solve(
    Matrix<float32> A,
    ref Matrix<float32> B);

Matrix<float64> solve(
    ref LU<float64> factor,
    ref Matrix<float64> B);

Matrix<float32> solve(
    ref LU<float32> factor,
    ref Matrix<float32> B);
```

Los overloads conservan el nombre `solve`. No se agregan `solveMatrix`,
`solveMultiple`, un parámetro `method`, un genérico cuya implementación sólo
admita de hecho dos tipos ni conversiones entre precisiones.

`solve(A,B)` valida, factoriza `A` exactamente una vez y delega en el overload
de LU de su precisión. `solve(factor,B)` aplica la permutación por gather y
realiza ambas sustituciones en un único resultado/workspace `Matrix<T>`.

## 2. Coexistencia y resolución de overloads

Los overloads existentes de RHS vectorial permanecen sin cambios:

```text
solve(Matrix<float64>, ref Vector<float64,Column>)
solve(Matrix<float32>, ref Vector<float32,Column>)
solve(ref LU<float64>, ref Vector<float64,Column>)
solve(ref LU<float32>, ref Vector<float32,Column>)
```

La extensión agrega las cuatro variantes cuyo segundo argumento es
`Matrix<T>`. `Matrix<T>` y `Vector<T,Column>` son tipos canónicos distintos;
por ello el segundo argumento selecciona naturalmente RHS matricial o
vectorial. El primer argumento distingue ruta owning de matriz y ruta prestada
de factor, y la precisión concreta completa la selección. No existe una pareja
de candidatos igualmente aplicables ni se depende de la shape runtime para
resolver un overload.

El ajuste de borrow exacto ya admitido permite escribir `solve(factor, B)` sin
consumir ninguno de esos dos owners. Las formas explícitas `solve(&factor,&B)`
son equivalentes. No se agregan defaults ni conversiones que alteren esta
resolución.

Un RHS vectorial de longitud `n` y una matriz `n×1` representan problemas
numéricos equivalentes, pero siguen rutas tipadas diferentes y devuelven tipos
distintos. Ningún overload convierte uno en otro ni delega mediante una copia.

## 3. Ownership y préstamos

### 3.1 Ruta desde Matrix

`A` es un parámetro owning y se consume. Esto permite que `lu(A)` recicle el
backing recibido tal como en SOLVE-V1 y LU-V1; `solve` no hace una copia
defensiva de `A`. Quien necesite conservar sus valores debe proporcionar otro
owner explícitamente.

`B` se recibe como `ref Matrix<T>` shared. No se consume, no se modifica y no
se retiene más allá de la call. El resultado `X` es un owner nuevo e
independiente, incluso para identidad o `q=1`.

Después de validar las shapes, el overload llama una vez a `lu(A)` y delega en
`solve(ref LU<T>,ref Matrix<T>)`. El factor temporal se destruye al retornar o
durante unwind; no hay un segundo kernel numérico en esta ruta.

### 3.2 Ruta desde LU

`factor` es un `ref LU<T>` shared. Las proyecciones de `L`, `U` y
`permutation` son lecturas a través del préstamo: no mueven, clonan, retienen
ni copian esos owners. `B` también es shared y sólo se lee.

El resultado es un único owner `Matrix<T>` de shape `n×q`, usado sucesivamente
como `P B`, `Y` y `X`. Fuera de ese resultado sólo se necesitan índices, un
coeficiente del factor y acumulación escalar; no hay owners auxiliares.

Esto permite, sobre una misma factorización:

```aether
LU<float64> factor = linearAlgebra.lu(A);
Matrix<float64> X1 = linearAlgebra.solve(factor, B1);
Matrix<float64> X2 = linearAlgebra.solve(factor, B2);
Vector<float64,Column> x = linearAlgebra.solve(factor, b);
float64 determinant = linearAlgebra.det(factor);
```

sin refactorizar, copiar el factor, modificar los RHS ni materializar `P`.

### 3.3 Por qué `ref Matrix<T>` es suficiente

El kernel sólo necesita consultar `rows`, `columns` y elementos de `B` durante
el gather inicial. Un préstamo shared del owner expresa exactamente ese uso y
evita consumo o copia. No se necesita mutabilidad del RHS, slicing ni lifetime
almacenado en el resultado.

Aceptar `MatrixView<T>` sería técnicamente posible porque el gather podría leer
sus strides, pero duplicaría la superficie y obligaría a cerrar una política de
owners/views que no es necesaria para el primer vertical matricial. Queda como
extensión aditiva futura. V1 no acepta `MatrixView` ni `MatrixViewMut` como RHS.

## 4. Contrato de shapes

Para la ruta desde Matrix se exige, en este orden:

```text
rows(A) = columns(A) = n
rows(B) = n
q = columns(B)
```

Para la ruta desde LU se exige, en este orden:

```text
rows(L) = columns(L)
rows(U) = columns(U)
rows(L) = rows(U) = n
dimension(permutation) = n
rows(B) = n
q = columns(B)
```

Cada relación exigida se expresa con `shapeGuard` antes de la allocation del
resultado y antes de cualquier acceso elemental. El primer guard falso según
el orden anterior produce el trap estructurado `ShapeMismatch`.

No se recorre el factor para volver a probar triangularidad, diagonal unitaria
de `L` o biyección/rango de `permutation`: son invariantes publicadas por
LU-V1. Una instancia de `LU` fabricada manualmente que viola esas invariantes
semánticas está fuera del contrato; un índice de permutación inválido conserva
el bounds trap ordinario. En cambio, las inconsistencias de extents enumeradas
arriba sí se rechazan siempre antes de allocation o acceso.

`q` no necesita ser positivo. Tampoco existe una relación entre `q` y `n` más
allá de que ambos sean extents representables de `Matrix`.

## 5. Shapes vacías

El contrato distingue el orden del sistema `n` de la cantidad de RHS `q`:

| factor/sistema | RHS | resultado o fallo |
|---|---|---|
| `0×0` | `0×0` | éxito, `0×0` |
| `0×0` | `0×q` | éxito, `0×q` para cualquier `q` |
| `0×0` | filas distintas de cero | `ShapeMismatch` |
| `n×n`, `n>0`, no singular | `n×0` | éxito, `n×0` |
| `n×n`, `n>0`, singular | `n×0` | `SingularMatrixException` |
| `n×n` | filas distintas de `n` | `ShapeMismatch` |

Una matriz con cero elementos conserva ambos extents. Por tanto `0×q` y
`n×0` no se colapsan conceptualmente a `0×0`, aunque ninguno tenga backing de
elementos.

Para `n=0` no existen pivots que puedan ser cero: toda `B : 0×q` produce la
única `X : 0×q`. Para `n>0,q=0`, en cambio, el sistema tiene una matriz de
coeficientes real y su singularidad no desaparece porque el conjunto de RHS
esté vacío.

## 6. Decisión normativa para `q=0`

`solve(ref LU<T>, B : n×0)` inspecciona cada `U[i,i]` en el mismo orden
descendente que el solve vectorial:

- si todos los pivots son distintos de cero, devuelve `X : n×0`;
- si algún pivot es exactamente cero, lanza `SingularMatrixException`.

Ésta no es una interpretación de éxito vacuo. `solve` promete resolver usando
un factor que representa un sistema square no singular; la ausencia de
columnas RHS elimina el trabajo sobre datos, no la precondición matemática del
operador. Mantener la comprobación también hace que singularidad dependa sólo
de `A`/LU y no de cuántas columnas tenga el RHS, coincide con la semántica ya
anticipada por SOLVE-ARCH-1 y evita que agregar una columna vacía cambie qué
factores acepta la API.

La comprobación de diagonal debe estar fuera del loop de columnas RHS. Así no
se omite cuando `q=0` y sólo se ejecuta una vez por fila cuando `q>0`.

## 7. Algoritmo normativo

Sea una LU square válida que satisface:

```text
P A = L U
```

Todos los índices siguientes son 1-based. `W` es el único resultado/workspace,
de shape `n×q`.

### 7.1 Gather de filas

No se construye la matriz `P`. Se inicializa directamente:

```text
para i = 1..n:
    para c = 1..q:
        W[i,c] = B[permutation[i],c]
```

Al terminar, `W=P B`. Como `permutation` es una biyección legítima, leer de
`B` y escribir en un owner distinto no requiere snapshot ni protección contra
alias destructivo.

### 7.2 Forward substitution en sitio

Para resolver `L Y=P B`, se aplican actualizaciones de fila:

```text
para i = 1..n:
    para j = 1..i-1:
        coefficient = L[i,j]
        para c = 1..q:
            W[i,c] = W[i,c] - coefficient * W[j,c]
```

Después de procesar `i`, la fila `W[i,:]` es `Y[i,:]`. No se lee ni divide
por `L[i,i]`, cuya unidad es invariante de LU.

### 7.3 Backward substitution en sitio

Para resolver `U X=Y`:

```text
para i = n..1:
    diagonal = U[i,i]
    si diagonal == 0:
        throw SingularMatrixException()
    para j = i+1..n:
        coefficient = U[i,j]
        para c = 1..q:
            W[i,c] = W[i,c] - coefficient * W[j,c]
    para c = 1..q:
        W[i,c] = W[i,c] / diagonal
```

La lectura y comprobación de `diagonal` precede los loops dependientes de `q`.
El descenso termina después de `i=1` sin calcular el siguiente índice y, por
tanto, sin underflow de `usize`. `W` se devuelve directamente como `X`.

Para cada columna, las restas recorren `j` en el mismo orden ascendente que el
kernel vectorial. Agrupar las columnas no cambia el orden aritmético dentro de
un RHS, aunque no se exige igualdad bit a bit entre optimizaciones distintas.

## 8. Orden de loops y layout

El owner `Matrix` actual es contiguo row-major. Por eso se elige:

```text
i (fila objetivo) exterior
j (fila ya resuelta/dependencia) intermedio
c (columna RHS) interior
```

El gather usa igualmente `i` exterior y `c` interior. En cada actualización,
`W[i,1..q]` y `W[j,1..q]` se recorren de forma contigua, mientras un único
`L[i,j]` o `U[i,j]` se reutiliza para todos los RHS. Esto aprovecha el layout
existente sin cambiarlo, crear vistas de columna ni introducir transposes.

Resolver una columna completa antes de pasar a la siguiente sería correcto,
pero caminaría `W[1..n,c]` con stride `q` y releería las regiones triangulares
del factor para cada RHS. El orden por actualizaciones de fila ofrece la
localidad natural del storage actual y sigue respetando las dependencias de
sustitución. No se introduce blocking, SIMD, paralelismo ni una promesa de
vectorización en este milestone.

## 9. Singularidad y valores IEEE

La regla es idéntica a SOLVE-V1:

```text
U[i,i] == 0 exacto  ->  SingularMatrixException
```

Incluye `+0.0` y `-0.0`. No hay epsilon, tolerancia relativa, estimación de
rank o condición ni resultado `Option`/`Result`. La excepción es nominal y
capturable; no se convierte en `ShapeMismatch`.

La comprobación se realiza una vez por fila, antes de dividir cualquiera de
sus RHS, y también cuando `q=0`. Un pivot subnormal o muy pequeño distinto de
cero se divide normalmente. NaN no compara igual a cero; NaN e infinito se
propagan según la aritmética IEEE ordinaria.

No se distingue un sistema singular compatible de uno incompatible. Si se
lanza, no hay resultado parcial observable; el workspace se limpia durante
unwind y tanto el factor como `B` permanecen intactos y reutilizables.

## 10. Costos y allocations

Desde una matriz `A : n×n`:

```text
tiempo = O(n³ + n²q)
```

La LU conserva sus allocations normales y puede reciclar el backing de `A`.
El solve agrega un solo owner `Matrix<T>` `n×q`; no copia `B`, `L` o `U`.

Desde una LU:

```text
gather                    O(nq)
forward + backward        O(n²q)
comprobación de diagonal  O(n)
total general             O(n + n²q)
total para q>=1           O(n²q)
```

El término O(n) se explicita porque es observable y deliberado para `q=0`.
En ese caso el costo es O(n), no O(0), precisamente para preservar el contrato
de singularidad.

Las allocations desde LU quedan cerradas así:

- si `n*q > 0`, exactamente una allocation de backing para la Matrix resultado;
- si `n=0` o `q=0`, el descriptor resultado conserva shape y no asigna backing;
- workspace escalar adicional O(1);
- ninguna matriz separada para `P B`, `Y` o `X`;
- ninguna allocation asociada a los préstamos de factor o RHS.

El filled-init ordinario de Matrix es la única construcción requerida. No se
agrega un intrinsic `aether_solve_matrix`, helper runtime, buffer packed ni
cambio al layout de Matrix.

## 11. Diagnósticos y precedencia de fallos

Los fallos dinámicos de shape usan exclusivamente `shapeGuard` y
`ShapeMismatch`. En particular:

- `A` rectangular falla antes de `lu(A)`;
- `rows(B) != n` falla antes de factorización en la ruta desde Matrix;
- `L`/`U` rectangular, órdenes inconsistentes, permutación de longitud
  incompatible o filas incompatibles de `B` fallan antes de allocation y
  accesos en la ruta desde LU.

Shape tiene precedencia sobre singularidad. Un factor singular con RHS de
filas incompatibles produce `ShapeMismatch`; sólo después de pasar todos los
guards puede alcanzarse `SingularMatrixException`.

Las siguientes incompatibilidades son estáticas y usan el diagnóstico
ordinario de no matching overload, actualmente `E0460`:

- mezcla de `float32` y `float64` entre factor/matriz y RHS;
- `Matrix<int>` u otro tipo no soportado;
- `MatrixView` en lugar de `Matrix`;
- resultado esperado con precisión o clase Matrix/Vector incompatible.

No se agregan diagnostics propios de `linearAlgebra`, análisis especial del
nombre `solve` ni compiler magic. Las shapes continúan siendo runtime y no
participan en `TypeId`.

## 12. Casos límite cerrados

| caso | contrato |
|---|---|
| identidad con varios RHS | `X` reproduce numéricamente `B` en owner nuevo |
| diagonal | cada fila se divide por su diagonal para todas las columnas |
| triangular | misma ruta general, sin fast path público |
| permutaciones | `W[i,c]=B[permutation[i],c]` |
| `1×1`, `q>1`, pivot no cero | divide la fila completa por el pivot |
| `1×1`, `q=0`, pivot no cero | devuelve `1×0` sin backing |
| `1×1`, pivot `±0`, cualquier `q` | `SingularMatrixException` |
| `0×0` y `B:0×q` | devuelve `0×q` sin backing |
| `n×n` no singular y `B:n×0` | devuelve `n×0` sin backing |
| `n×n` singular y `B:n×0` | `SingularMatrixException` |
| filas de `B` incompatibles | `ShapeMismatch` antes de efectos del kernel |
| LU rectangular/inconsistente | `ShapeMismatch` antes de allocation/acceso |
| float32/float64 | kernels concretos, sin promoción |

No se promete un fast path para identidad, diagonal, triangular, `q=1` o
shapes vacías. Los loops ordinarios producen esos resultados y preservan una
única semántica.

## 13. Reutilización y convivencia con operaciones existentes

Una LU válida puede alternarse libremente entre:

- cualquier cantidad de solves matriciales;
- solves vectoriales existentes;
- `det(ref LU<T>)`.

Ninguna operación mueve o modifica los campos del factor. Dos resultados de
solves distintos son owners independientes entre sí y de sus RHS. Capturar
`SingularMatrixException` tampoco invalida el factor o el RHS prestado.

Para `q=1`, el solve matricial debe concordar numéricamente con el solve
vectorial aplicado a la única columna, sujeto a las tolerancias de prueba de
cada precisión. Esta equivalencia de valores no fusiona las APIs ni autoriza
una Matrix temporal en la ruta vectorial o un Vector temporal en la matricial.

## 14. Relación futura con `inverse`

Una futura operación:

```aether
Matrix<T> inverse(Matrix<T> A)
```

podría definirse conceptualmente como `solve(A, identity(n))`, aprovechando el
kernel de múltiples RHS. Esto documenta una dirección de reutilización, no
incorpora `inverse` a este milestone, no fija su firma definitiva y no autoriza
una implementación, alias ni overload nuevo ahora.

## 15. Calificación del futuro vertical

La implementación deberá cubrir para `float64` y `float32`, en O0 y O2:

- identidad con varios RHS;
- diagonal y triangulares superior e inferior;
- un swap y múltiples swaps, verificando dirección de `permutation`;
- una `B` aleatoria construida como `A*XKnown` y comparación con `XKnown`;
- residual `A*X-B` con tolerancia justificada por precisión y magnitud;
- `q=1` y concordancia con solve vectorial;
- `q>1`;
- `q=0` con factor no singular y singular;
- `n=0` con `B:0×0` y `B:0×q`;
- `1×1` con cero, una y varias columnas;
- singularidad con RHS no vacío;
- reutilización de una LU con al menos dos matrices RHS;
- convivencia secuencial con `solve(factor,bVector)` y `det(factor)`;
- `ShapeMismatch` para A rectangular, filas de B incompatibles y LU
  rectangular/inconsistente;
- rechazos estáticos por precisión, tipo y Matrix/Vector incorrectos.

La calificación estructural deberá demostrar:

- exactamente los cuatro overloads nuevos y ningún nombre alternativo;
- una sola llamada a `lu(A)` en cada ruta directa;
- una sola allocation Matrix desde LU cuando `n*q>0` y cero backing cuando el
  producto es cero;
- ausencia de matrices separadas `P B`, `Y` y `X`;
- ausencia de materialización de `P`, copias de `L/U` e intrinsic
  `aether_solve_matrix`;
- guards anteriores a allocation/accesos;
- diagonal revisada aun para `q=0`;
- préstamos de LU/B preservados y cleanup correcto en unwind;
- loops row-major y orden de dependencias visibles en HIR/MIR/SSA/LLVM;
- ninguna regresión de los cuatro overloads vectoriales existentes.

## 16. Orden recomendado de implementación

1. Agregar los dos overloads concretos desde `ref LU<T>` sin modificar los
   overloads vectoriales.
2. Implementar los cinco guards de shape por precisión antes de allocation y
   accesos.
3. Crear la única Matrix `W`, implementar el gather por filas y las
   sustituciones mediante actualizaciones row-major.
4. Colocar el check exacto de diagonal fuera del loop RHS para cubrir `q=0` y
   verificar cleanup excepcional.
5. Agregar los dos overloads owning `Matrix<T>` que guardan shapes, llaman una
   vez a `lu(A)` y delegan.
6. Ampliar el consumer con los casos numéricos, vacíos, de reutilización y
   convivencia para ambas precisiones en O0/O2.
7. Agregar calificación de diagnostics, IR, allocations, ausencia de copias e
   intrinsics y no regresión vectorial.
8. Ejecutar la suite completa y publicar un reporte de implementación
   separado.

## 17. Fuera de scope

No forman parte de este milestone:

- `inverse`;
- RHS `MatrixView` o `MatrixViewMut`;
- variantes in-place o sobrescritura de `B`;
- least squares y sistemas underdetermined;
- QR solve, Cholesky, sparse solve y métodos iterativos;
- rank, condición, refinement o clasificación de sistemas singulares;
- tolerancias de singularidad;
- `Complex<T>`;
- BLAS/LAPACK, SIMD, blocking, paralelismo o GPU;
- cambios al layout de Matrix, a LU, al compilador o al runtime.

No quedan decisiones de overload, ownership, shapes vacías, singularidad,
algoritmo, layout, costos o reutilización abiertas dentro de este dominio.
