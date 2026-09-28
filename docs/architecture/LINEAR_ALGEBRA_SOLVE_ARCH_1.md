# LINEAR-ALGEBRA-SOLVE-ARCH-1 — resolución LU de sistemas cuadrados

Estado: **ARQUITECTURA CERRADA; NO IMPLEMENTADA**, 2026-09-28.

Este milestone define `solve` para el package ordinario `linearAlgebra`. No
modifica `linearAlgebra/src/lib.ae`, el compilador, el runtime ni los tests. La
implementación, incluida la pequeña capacidad general de guard de shape que se
identifica abajo, pertenece a milestones posteriores.

Autoridad relacionada:

- [LINEAR-ALGEBRA-LU-ARCH-1](LINEAR_ALGEBRA_LU_ARCH_1.md);
- [LINEAR-ALGEBRA-LU-ARCH-1-REPORT](LINEAR_ALGEBRA_LU_ARCH_1_REPORT.md);
- [LINEAR-ALGEBRA-LU-V1](LINEAR_ALGEBRA_LU_V1_REPORT.md);
- [LINEAR-ALGEBRA-OAL-V1-QR](LINEAR_ALGEBRA_OAL_V1_QR_REPORT.md);
- [LINEAR-ALGEBRA-CONSTRUCTORS-V1](LINEAR_ALGEBRA_CONSTRUCTORS_V1_REPORT.md);
- [BORROW-ERGONOMICS-V1](BORROW_ERGONOMICS_V1_REPORT.md);
- [EXCEPTION-V1](EXCEPTION_V1_REPORT.md).

## 1. Decisión resumida

`solve` V1 resuelve exclusivamente:

```text
A x = b
A : n×n real y no singular
b : Vector<T,Column> de longitud n
T : float32 o float64
```

Usa LU con pivoting parcial ya implementada. No mezcla este contrato con
least squares, sistemas underdetermined ni selección de método. Tampoco incluye
RHS matricial en V1.

La superficie pública cerrada es:

```aether
class SingularMatrixException : Exception {
    public init() {}
}

Vector<float64,Column> solve(
    Matrix<float64> A,
    ref Vector<float64,Column> b);

Vector<float32,Column> solve(
    Matrix<float32> A,
    ref Vector<float32,Column> b);

Vector<float64,Column> solve(
    ref LU<float64> factor,
    ref Vector<float64,Column> b);

Vector<float32,Column> solve(
    ref LU<float32> factor,
    ref Vector<float32,Column> b);
```

`solve(A,b)` factoriza internamente mediante `lu(A)` y delega en la misma ruta
de sustitución que `solve(factor,b)`. Los cuatro overloads se llaman `solve`;
no se agregan `solveFloat32`, `solveLU`, parámetros `method` ni un genérico
falso basado sólo en `Storable`.

La sintaxis usual sigue siendo:

```aether
Vector<float64,Column> x = linearAlgebra.solve(A, b);
LU<float64> factor = linearAlgebra.lu(A2);
Vector<float64,Column> x1 = linearAlgebra.solve(factor, b1);
Vector<float64,Column> x2 = linearAlgebra.solve(factor, b2);
```

BORROW-ERGONOMICS-V1 inserta el préstamo compartido exacto de `factor`, `b`,
`b1` y `b2` en posición de argumento. `&factor` y `&b` siguen siendo formas
explícitas equivalentes. El préstamo no crea Alias, Clone, owner ni allocation.

## 2. Dominio V1

V1 acepta toda matriz square runtime `n×n`, incluidos `0×0` y `1×1`, siempre
que el RHS Column tenga longitud `n`. Para `n>0`, la matriz debe ser no singular
según el criterio exacto de la sección 7.

La comparación de alternativas queda cerrada así:

| alternativa | decisión | razón |
|---|---|---|
| square `A x=b` | V1 | contrato único, respaldado directamente por LU |
| square `A X=B` | V2 | útil, pero duplica la superficie y agrega semántica de `q=0` sin ser necesaria para cerrar el primer vertical |
| tall least squares | fuera de V1 | exige un contrato QR distinto y decisiones de rank |
| wide/underdetermined | fuera de V1 | exige elegir solución, rank y posiblemente pivoting/pseudoinversa |
| LU rectangular como entrada | rechazada por `solve` | la factorización existe, pero no representa el dominio square de esta operación |

Que `lu` acepte matrices rectangulares no amplía `solve`. La precondición
square pertenece a `solve`, tal como anticipó la arquitectura LU.

No se aceptan enteros, `Complex<T>`, tipos definidos por usuarios ni un `T`
arbitrario `Storable`. Cada precisión ejecuta sustitución, comparación con cero
y división en su tipo concreto; no se promociona `float32` a `float64`.

## 3. Ownership y préstamos

### 3.1 `solve(A,b)`

`A` es un parámetro owning y se consume. Esto permite que `lu(A)` reutilice su
backing sin copiar la matriz completa. Después de la call el binding movido no
queda disponible. Quien necesite preservar los valores de `A` debe construir y
entregar explícitamente otro owner; `solve` no hace una copia defensiva oculta.

`b` se recibe como `ref Vector<T,Column>` compartido. No se consume ni modifica
y vuelve a estar disponible al terminar normalmente o al capturar una
`SingularMatrixException`. El resultado es siempre un `Vector<T,Column>` owner
nuevo, independiente de `b`.

El resultado nuevo no es una copia accidental: hace falta un workspace de
longitud `n` para formar `P b` sin sobrescribir valores de `b` que una entrada
posterior de la permutación todavía pueda necesitar. Ese mismo owner se reutiliza
en sitio primero como `P b`, luego como `y` y finalmente como `x`.

### 3.2 `solve(factor,b)`

`factor` se recibe como `ref LU<T>` shared. El cuerpo accede a sus campos con
proyecciones del préstamo, por ejemplo `(*factor).U`; no mueve, clona ni crea
Alias de `permutation`, `L` o `U`. La factorización permanece intacta y puede
usarse con cualquier cantidad de RHS secuenciales.

El préstamo es de la `LU` completa durante la call. V1 no rediseña `LU<T>`, no
guarda refs/views en ella y no necesita un factor packed nuevo.

Al igual que en el overload directo, `b` es shared y el resultado es un owner
nuevo usado como único workspace vectorial.

### 3.3 Views deliberadamente diferidas

V1 no ofrece `VectorView<T,Column>` ni `VectorViewMut<T,Column>` como RHS. Un
view shared sería viable y no requeriría materializar el input: el gather puede
leer strides y escribir el resultado owning. Sin embargo, añadirlo duplicaría
otra vez los overloads públicos y obligaría a fijar desde el primer vertical la
política de owners/views/mutable views.

El préstamo exacto de un owner cubre el uso principal sin consumir `b` ni
esconder una copia. Agregar overloads de view en V2 es aditivo. No habrá
conversión implícita de Row a Column.

## 4. Contrato de las factorizaciones recibidas

El overload de `LU<T>` espera un valor bien formado según LINEAR-ALGEBRA-LU-V1
y verifica antes de leer elementos que representa un problema square:

```text
rows(L) = columns(L) = rows(U) = columns(U) = n
dimension(permutation) = n
dimension(b) = n
```

Una LU rectangular producida legalmente por `lu` falla esta precondición. Los
checks preceden la allocation del resultado, el gather y cualquier división.

La invariante semántica restante es la publicada por `LU<T>`:
`permutation` es una biyección 1-based, `diag(L)=1`, `L` es lower, `U` es upper
y `P A=L U`. V1 no recorre O(n²) sólo para revalidar estructura y ceros de un
struct fabricado manualmente. Un `LU` forjado que viole esas invariantes está
fuera del contrato; un índice de permutación inválido conserva el bounds trap
normal. Esto no reduce la validación exigida para factores producidos por
`linearAlgebra.lu`.

## 5. Algoritmo normativo

Sea `factor` una LU square de orden `n` que satisface `P A=L U`, sea `w` el
owner de salida/workspace y sean todos los índices 1-based.

### 5.1 Aplicar la permutación

No se materializa `P`. Se hace un gather desde el RHS prestado:

```text
para i = 1..n:
    w[i] = b[permutation[i]]
```

Al terminar, `w=P b`.

### 5.2 Forward substitution

Resolver `L y=P b` en el mismo `w`. Como `L[i,i]=1`, no se lee ni divide por
la diagonal:

```text
para i = 1..n:
    y[i] = w[i] - sum(j=1..i-1, L[i,j] * y[j])
    w[i] = y[i]
```

El orden ascendente hace que cada `y[j]` requerido ya viva en `w[j]`.

### 5.3 Backward substitution

Resolver `U x=y` recorriendo en orden descendente:

```text
para i = n..1:
    si U[i,i] == 0:
        throw SingularMatrixException()
    x[i] = (w[i] - sum(j=i+1..n, U[i,j] * x[j])) / U[i,i]
    w[i] = x[i]
```

El decremento se expresará sin underflow de `usize`: el loop termina después
de procesar `i=1` y no calcula `1-1` como próximo índice. El owner `w` se
devuelve directamente; no se crea otro vector para `y` o `x`.

`solve(A,b)` primero valida shapes, evalúa `lu(A)` una sola vez y aplica este
algoritmo al factor temporal. No repite factorización ni implementa una segunda
ruta numérica.

## 6. Orden de validación y fallos de shape

Para `solve(A,b)`, antes de llamar a `lu`:

1. comprobar `rows(A) == columns(A)`;
2. comprobar `dimension(b) == rows(A)`.

Para `solve(factor,b)`, antes de allocation o accesos:

1. comprobar que `L` y `U` tienen las shapes square coherentes de la sección 4;
2. comprobar la longitud de `permutation`;
3. comprobar la longitud de `b`.

Una violación dinámica produce el trap estructurado `ShapeMismatch`, no
`SingularMatrixException`. Es un error de contrato de shape y no un resultado
matemático del sistema. El primer check fallido en el orden anterior gana.

Las dimensiones de `Matrix<T>` y `Vector<T,O>` son runtime y no participan en
su `TypeId`. Además, una función source ordinaria no recibe hoy análisis
interprocedural de shapes ni puede emitir directamente `ShapeMismatch`. Por eso:

- V1 no promete un diagnóstico estático para una matriz literal no square o
  una longitud conocida incompatible en una call a `solve`;
- inventar una multiplicación dummy para obtener un trap agregaría allocation
  y O(n²), y queda prohibido;
- el vertical de implementación queda precedido por una capacidad general y
  mínima para expresar un guard de shape desde una library, preservado como
  `ShapeMismatch` en HIR/MIR/SSA y sin intrinsic específico de `solve`;
- una mejora futura puede producir `E0345` cuando un contrato de precondición y
  shapes conocidas llegue a calls ordinarias, sin cambiar la API de `solve`.

Este requisito es un bloqueo real de expresabilidad, no una autorización para
agregar compiler magic de álgebra lineal.

La orientación y el tipo sí son estáticos:

- un RHS `Vector<T,Row>` no coincide con ningún overload y produce el
  diagnóstico ordinario `E0460` de no matching overload;
- combinaciones `float32`/`float64` mezcladas y tipos no soportados producen
  `E0460`;
- no hay cast, widening ni transpose implícito;
- pasar una LU por valor owning es aceptado por el ajuste `T -> ref T` sólo
  durante la call y no la consume.

## 7. Singularidad exacta

Después del pivoting parcial, `U[i,i] == 0` bajo igualdad IEEE exacta, incluido
`-0.0`, produce `SingularMatrixException`. No se usa epsilon absoluto o
relativo, norma, threshold ni estimación de condición.

La excepción es un fallo matemático recuperable y nominal. No es:

- un trap de shape o bounds;
- un `Option`/`Result` obligatorio en cada call;
- un status mezclado con el vector;
- una señal de matriz meramente mal condicionada.

El mismo contrato se aplica a `solve(A,b)` y `solve(factor,b)`. En el overload
directo, `lu` puede producir legalmente el factor singular y la excepción nace
al encontrar el primer pivot diagonal cero durante backward substitution.

V1 no distingue entre un sistema singular compatible con infinitas soluciones
y uno incompatible. Ambos lanzan la misma excepción, no devuelven una solución
particular y no intentan comprobar consistencia. El workspace parcial se limpia
por unwind; no existe resultado observable. Una LU prestada y el RHS prestado
permanecen intactos y reutilizables después del catch.

Una diagonal subnormal o muy pequeña pero distinta de cero se divide
normalmente. El resultado puede tener error grande o valores no finitos: eso es
condicionamiento, no singularidad exacta. NaN e infinito no reciben un contrato
especial; en particular, NaN no compara igual a cero y se propaga mediante la
aritmética IEEE ordinaria.

## 8. Casos límite

| caso | contrato V1 |
|---|---|
| `0×0` y Column length 0 | éxito; devuelve Column owner vacío, sin pivots, excepción ni backing allocation |
| `0×0` y RHS no vacío | `ShapeMismatch` |
| `1×1`, valor no cero | `x[1]=b[1]/A[1,1]` |
| `1×1`, `+0.0` o `-0.0` | `SingularMatrixException` |
| identidad | devuelve numéricamente `b` en un owner independiente |
| triangular | usa el mismo LU y las mismas sustituciones; no hay fast path público |
| permutación no trivial | aplica exactamente `b[permutation[i]]` |
| RHS cero y A no singular | solución cero |
| A singular y RHS cero | `SingularMatrixException`; no se elige una de infinitas soluciones |
| A rectangular | `ShapeMismatch` antes de factorizar |
| LU rectangular | `ShapeMismatch` antes de allocation/acceso |
| longitud incompatible | `ShapeMismatch` antes de allocation/acceso |
| Row RHS | rechazo estático `E0460` |
| `float32`/`float64` | overload y aritmética concretos, sin promoción |

El vacío es el único orden que no necesita un pivot no cero: el sistema vacío
tiene la solución Column vacía única para este contrato.

## 9. Costos

### 9.1 Desde matriz

Para `A : n×n`:

```text
solve(A,b):
    tiempo = O(n³) factorización + O(n²) sustituciones
    allocation = LU.permutation + segundo factor LU + vector resultado
    backing de A = reciclado como el otro factor LU
    backing de b = sólo lectura, no copiado como owner
```

El factor temporal se destruye al terminar o durante unwind. No se materializa
`P`, no se copian `L`/`U` y no existe un vector separado para cada una de
`P b`, `y` y `x`.

### 9.2 Desde LU

```text
solve(factor,b):
    tiempo = O(n²)
    allocation = exactamente un Vector<T,Column> resultado para n>0
    workspace escalar adicional = O(1)
    lecturas = permutation O(n), L/U O(n²), b O(n)
```

El factor prestado no realiza retain/release, clone ni allocation por el
contrato de call borrow. Para `n=0`, filled-init conserva la longitud cero y no
asigna backing.

Resolver `k` RHS con la misma LU mediante `k` calls cuesta O(k n²) después de
una única factorización O(n³), con un vector resultado por call. Esta es la
reutilización que V1 garantiza.

## 10. RHS matricial diferido

V1 no publica:

```aether
Matrix<T> solve(Matrix<T> A, ref Matrix<T> B);
Matrix<T> solve(ref LU<T> factor, ref Matrix<T> B);
```

La extensión V2 natural aceptará `B : n×q`, devolverá un owner `X : n×q`,
aplicará el gather y las sustituciones por columna y reutilizará una sola LU.
Su costo desde factor será O(n²q), con una allocation `n×q` y sin materializar
`P`. Deberá cerrar expresamente `q=0`; la recomendación es devolver `n×0` para
factor no singular y mantener la validación de singularidad independiente de
que existan columnas RHS.

Diferir esta superficie no impide implementarla: los overloads se distinguen
por el segundo parámetro Vector frente a Matrix y la representación LU no
cambia.

## 11. Extensibilidad futura

`solve` permanece como nombre de alto nivel seleccionado por los tipos de sus
argumentos, no por un parámetro abierto `method=...`:

- estos overloads significan LU para matriz square general;
- Cholesky futuro debe exponer primero su propio factor y podrá agregar
  `solve(ref Cholesky<T>, ...)` sin alterar `solve(ref LU<T>, ...)`;
- QR podrá agregar solve/least-squares sobre un factor QR con un contrato de
  shapes y rank explícito;
- métodos iterativos necesitarán criterios, estado y resultados distintos, y
  no deben forzarse dentro de esta firma;
- una API que permita elegir método desde `A` puede diseñarse después mediante
  otro tipo/configuración, sin convertir V1 en una mega API.

No se promete que un futuro overload `solve(A,b)` cambie silenciosamente de LU
a Cholesky o QR. El contrato V1 de ese overload es LU con pivoting parcial.

## 12. Calificación del futuro vertical

La implementación debe probar, para `float64` y `float32`:

- identidad, diagonal y triangular superior/inferior;
- un swap y múltiples swaps, verificando la dirección exacta de permutation;
- sistemas aleatorios pequeños construidos desde `b=A*xKnown`;
- RHS cero;
- `0×0`, `1×1` no singular y `1×1` singular;
- singular compatible y singular incompatible, ambos capturables como
  `SingularMatrixException`;
- matriz casi singular con diagonal exacta no cero, que no lanza;
- reutilización de una sola LU con al menos dos RHS y evidencia de que el
  factor no fue movido ni modificado;
- A rectangular, LU rectangular y longitud incompatible;
- rechazo estático de Row, tipos mezclados y tipos no soportados;
- ejecución equivalente en O0 y O2.

Para soluciones conocidas se compara `x` con `xKnown`. En todos los casos no
singulares se comprueba además:

```text
||A x - b||
```

con tolerancias justificadas por tipo y escaladas respecto de las magnitudes
del fixture; la API no usa esas tolerancias para decidir singularidad. Las
propiedades discretas —shape, orientación, excepción, no consumo y
permutación— se verifican exactamente.

La calificación estructural debe demostrar:

- sólo los cuatro overloads cerrados y la excepción pública acordada;
- `solve(A,b)` invoca `lu` una vez;
- `solve(ref LU,b)` no copia ni consume campos del factor;
- una sola allocation vectorial desde LU no vacío y cero para el vacío;
- ausencia de `P`, multiplicación dummy, copias de `L/U` e intrinsics
  `aether_solve`;
- guards de shape antes de allocation/accesos y singularidad como throw, no
  como `ShapeMismatch`;
- cleanup correcto del workspace y factores temporales durante unwind;
- HIR/MIR/SSA/LLVM conservan borrow, loops, guards y exceptional edge.

## 13. Orden recomendado de implementación

1. Admitir y calificar, en un milestone general separado, el guard source de
   shape que baja al `ShapeMismatch` estructurado existente; no agregar una
   primitiva específica de álgebra lineal.
2. Declarar `SingularMatrixException` y los dos overloads desde `ref LU<T>`.
3. Implementar checks de shape y el workspace resultado único.
4. Implementar gather, forward substitution y backward substitution concretos
   para `float64` y `float32`, incluido throw por diagonal cero exacta.
5. Agregar los dos overloads owning Matrix que validan, llaman una vez a `lu`
   y delegan en la ruta desde factor.
6. Ampliar el consumer sin retirar la batería constructors/QR/LU existente y
   cubrir los casos numéricos y excepcionales anteriores en O0/O2.
7. Calificar diagnósticos, IR, allocations, cleanup, reutilización y ausencia
   de copias/intrinsics.
8. Ejecutar la suite completa y publicar un reporte de implementación separado.

## 14. Fuera de scope

No forman parte de SOLVE V1:

- determinant, inverse, rank, condición o pseudo-inverse;
- RHS Matrix y `q=0` matricial;
- Vector Row o conversión implícita de orientación;
- VectorView/VectorViewMut como RHS;
- least squares, sistemas underdetermined o QR solve;
- Cholesky, sparse solve y métodos iterativos;
- selección `method`, factores packed o variantes públicas in-place;
- solución particular de sistemas singulares o clasificación
  compatible/incompatible;
- tolerancias de singularidad, refinement o estimación de error;
- `Complex<T>`, BLAS/LAPACK, SIMD, paralelismo o GPU.

No quedan decisiones de API, ownership, singularidad, algoritmo, shapes vacíos
o costos abiertas dentro de este dominio. El único prerequisito explícito es el
guard general de shape requerido para expresar honestamente el contrato desde
una library ordinaria.
