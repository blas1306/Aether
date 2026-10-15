# MATRIX-REPRESENTATION-ARCH-1 — representación y construcción matricial general

Estado: **ARQUITECTURA CERRADA; NO IMPLEMENTADA**, 2026-10-03.

Este milestone diseña tres operaciones generales y separa de forma explícita
sus costes:

```aether
transpose_view(A)       // MatrixView<T>, O(1), cero allocation
la.transposeCopy(A)     // Matrix<T> nueva, O(m*n), una allocation si m*n > 0
la.diagonalMatrix(v)    // Matrix<T> k×k dense, O(k²), una allocation si k > 0
```

No cambia `SVD<T>`, no agrega algoritmos derivados y no implementa código.

## 1. Decisión resumida

1. La vista transpuesta **ya existe** en la capa de lenguaje. Los nombres
   públicos normativos continúan siendo `transpose_view` y
   `transpose_view_mut`. No se agregan `transposeView`, otro descriptor ni un
   wrapper de package.
2. La transposición owning de Matrix no existe. Se agrega conceptualmente como
   `std.Math.LinearAlgebra.transposeCopy`, implementable en source ordinario.
   El sufijo `Copy` hace visible que hay materialización y allocation.
3. La construcción diagonal dense no existe. Se agrega conceptualmente como
   `std.Math.LinearAlgebra.diagonalMatrix`, con overloads para Vector Column y
   Row. El nombre no se reutiliza para extracción de diagonales.
4. La implementación inicial usa `matrixFilled` y por ello ambas operaciones
   owning requieren `Storable + Copy + Zero`. No requieren `IEEEFloat`. `Zero`
   es una exigencia de inicialización segura del builder disponible, no una
   propiedad matemática de la transposición.
5. No se crea `DiagonalMatrix`, no se amplía el compilador y no se concede
   ningún privilegio a std u OAL.

En los ejemplos siguientes `la` denota:

```aether
import std.Math.LinearAlgebra as la;
```

La ubicación canónica es std porque son transformaciones matriciales generales
sin semántica nueva de tipos, ownership o borrowing. El package OAL existente
`linearAlgebra` contiene hoy constructores y algoritmos, pero no debe recibir
aliases duplicados para estas dos APIs nuevas. Su migración o compatibilidad de
namespace es un asunto de distribución separado; no cambia las firmas de este
documento.

## 2. Auditoría de la superficie existente

### 2.1 Owners

`Matrix<T>` es un owner matemático move-only, no una colección anidada. Su
shape runtime es inmutable y `T: Storable` basta para almacenar elementos,
incluidos elementos no-Copy y con drop. El descriptor actual es:

```text
{ ptr, rows, columns, rowCapacity, columnCapacity }
```

El offset físico de una celda lógica zero-based es
`row * columnCapacity + column`. El rectángulo lógico puede ser menor que la
reserva; padding y capacity no son observables desde source. Drop recorre sólo
las celdas lógicas y libera según el producto de capacities.

`Vector<T,O>` es también owning y move-only, con `O` nominalmente `Row` o
`Column`. La orientación es parte del tipo estático, no metadata runtime.
`transpose(Vector)` ya existe, consume el owner y transfiere su descriptor en
O(1); esta operación no es una transposición owning de Matrix.

Matrix y Vector usan indexación matemática 1-based. Los owners distinguen
`0×0`, `m×0` y `0×n`; un producto de capacities cero usa backing null sin
colapsar los extents lógicos.

### 2.2 Views matemáticas

Ya existen:

```text
MatrixView<T>
MatrixViewMut<T>
VectorView<T,Row/Column>
VectorViewMut<T,Row/Column>
```

`MatrixView` y `MatrixViewMut` comparten el descriptor de cinco palabras:

```text
{ ptr, rows, columns, rowStride, columnStride }
```

Son descriptores Copy/Relocatable, no-Storable, sin drop y prestados. No pueden
retornarse, almacenarse en aggregates/collections owning, rebindearse ni usarse
como generic argument desnudo. Las copias de descriptor retienen la provenance
del mismo owner raíz. Mientras una view derivada está viva, el owner no puede
moverse ni reemplazarse.

Los slices matemáticos ya producen estas mismas views. `A[i,:]` y `A[:,j]`
producen VectorView orientada; dos selectores slice producen MatrixView. Las
subviews conservan strides y provenance, también cuando la fuente ya es
transpuesta o strided. No existe un sistema paralelo que este diseño deba
crear.

### 2.3 Transpose views existentes

Las cuatro operaciones estructurales públicas ya cerradas son:

```aether
matrix_view(A)
matrix_view_mut(A)
transpose_view(A)
transpose_view_mut(A)
```

`transpose_view` acepta un Matrix owner o Matrix view Place legible y produce
`MatrixView<T>`. `transpose_view_mut` acepta un owner o view con capacidad de
escritura y produce `MatrixViewMut<T>`. Sobre el descriptor:

```text
(ptr, r, c, rs, cs) -> (ptr, c, r, cs, rs)
```

La construcción es O(1), no asigna, no carga/copia elementos y no cambia el
backing. Una view directa de owner padded usa
`(ptr, rows, columns, columnCapacity, 1)`; nunca reconstruye el row stride a
partir de `columns`.

La doble transposición intercambia dos veces shape y strides y por ello recupera
la orientación lógica original, aunque el resultado siga siendo una view. La
indexación continúa siendo 1-based y calcula el offset sólo después de validar
ambos límites. Los shapes vacíos conservan el otro extent y sus strides; no se
impone una combinación canónica única de strides vacíos.

### 2.4 Mutabilidad y aliasing existentes

Una fuente shared sólo puede producir `MatrixView<T>`. No hay conversión desde
shared a mutable. Una fuente writable puede producir una view mutable y las
escrituras se observan en el backing original.

El contrato vigente de Aether no convierte `ref mut`, `MatrixViewMut` ni
`VectorViewMut` en exclusividad Rust-like y no emite `noalias`: aliases shared
y mutables pueden solaparse cuando las reglas de provenance permiten crearlos.
La garantía es de **capacidad de escritura**, lifetime léxico, no-escape y
bloqueo conservador de moves/replacements del owner. Este milestone respeta ese
contrato y no promete exclusividad nueva.

### 2.5 Construcción, asignación y funciones generales

Ya existen literals Matrix/Vector, `matrixFilled<T>`/`vectorFilled<T,O>`,
indexación, asignación escalar, slices y slice assignment. `matrixFilled`
requiere `T: Storable + Copy`, recibe un valor T inicializado, valida overflow,
reserva una sola vez y publica el owner sólo después de inicializar todas sus
celdas. Para cualquier eje cero conserva shape y no asigna backing.

El package `linearAlgebra` actual ya ofrece genéricamente `zeros`, `ones` e
`identity` sobre `matrixFilled`; también LU, QR, Cholesky, solve, det y SVD.
Hay un helper privado `copyMatrixForFactorization<T: IEEEFloat>` que copia sólo
el rectángulo lógico a capacidad exacta. No es una copia pública general y no
es transposición.

La auditoría no encontró:

- transposición owning pública de `Matrix<T>`;
- constructor público de matriz diagonal desde Vector;
- extracción general de diagonal;
- tipo `DiagonalMatrix`.

## 3. Frontera de capas

| Operación | Capa | Decisión |
|---|---|---|
| `transpose_view` | lenguaje/core matemático nativo existente | El compilador debe conservar descriptor, provenance, lifetime y capacidad de escritura. Sólo se expone/reutiliza lo ya implementado. |
| `transpose_view_mut` | lenguaje/core matemático nativo existente | Misma razón; no se cambia aliasing ni mutabilidad. |
| `transposeCopy` | `std.Math.LinearAlgebra`, source ordinario | Es un algoritmo de recorrido y construcción sobre APIs seguras existentes; no necesita tipo/opcode/intrinsic nuevo. |
| `diagonalMatrix` | `std.Math.LinearAlgebra`, source ordinario | Es construcción algebraica general con cero; no altera identidad de Matrix. |

No se agrega un wrapper std alrededor de `transpose_view`: además de duplicar
la superficie, una función source no puede mejorar sus reglas de provenance.
Tampoco se colocan las operaciones owning en prelude: asignan storage, tienen
coste no constante y pertenecen a una dependencia matemática explícita.

OAL no tiene permisos especiales. `matrixFilled`, indexación y capabilities
deben estar disponibles bajo las mismas reglas para cualquier package. El
estado official de un package sólo expresa distribución/ownership.

## 4. Superficie pública cerrada

### 4.1 Vista transpuesta shared

No se declara nada nuevo. La superficie existente es equivalente a:

```aether
MatrixView<T> transpose_view<T: Storable>(ref Matrix<T> source);
MatrixView<T> transpose_view<T>(MatrixView<T> source);
MatrixView<T> transpose_view<T>(MatrixViewMut<T> source);
```

Estas firmas son contractuales, no una instrucción para reimplementar los
intrinsics como funciones source. En llamadas normales opera la adaptación de
borrow vigente y los argumentos deben ser Places; no hay lifetime extension de
rvalues.

### 4.2 Vista transpuesta mutable

Tampoco se declara nada nuevo:

```aether
MatrixViewMut<T> transpose_view_mut<T: Storable>(ref mut Matrix<T> source);
MatrixViewMut<T> transpose_view_mut<T>(MatrixViewMut<T> source);
```

`transpose_view_mut(MatrixView<T>)` y cualquier intento de obtener escritura
desde `ref Matrix<T>` deben continuar rechazándose. Transponer una
`MatrixViewMut` dos veces conserva capacidad de escritura y la provenance raíz.

### 4.3 Transposición owning

La nueva firma normativa es:

```aether
public Matrix<T> transposeCopy<T: Storable + Copy + Zero>(
    ref Matrix<T> source);
```

Semántica para `source:m×n`:

- retorna un owner nuevo `n×m`, independiente y sin borrows;
- deja `source` intacta, viva y reusable;
- para todo `1 <= i <= m`, `1 <= j <= n`,
  `result[j,i] == source[i,j]`;
- recorre exclusivamente las celdas lógicas mediante indexación/stride del
  owner; nunca lee ni copia padding;
- crea capacidad exacta para el resultado inicial;
- realiza una allocation de backing si `m*n > 0`, y cero si el producto es
  cero;
- no crea una Matrix transpuesta auxiliar ni materializa primero una view
  owning;
- conserva exactamente `n×m` para `0×n`, `m×0` y `0×0`.

La implementación source prevista crea una sola salida zero-filled mediante
`matrixFilled<T>(n,m,0)` y luego escribe cada celda lógica una vez desde la
fuente. Esto garantiza inicialización completa y cleanup ordinario si una
operación previa falla. Cuesta O(m*n), usa O(m*n) storage de resultado y O(1)
storage auxiliar. El zero-fill agrega stores de inicialización, pero no otra
allocation ni un buffer auxiliar.

No se usa el nombre `transpose`: ya designa la transferencia O(1) de owners
Vector y ocultaría una diferencia de coste importante para Matrix. Tampoco se
usa `materializeTranspose`, que describe mecanismo antes que resultado. El
camelCase `transposeCopy` sigue la convención de packages y hace explícita la
copia.

V1 acepta sólo Matrix owner borrowed. Un overload futuro sobre `MatrixView<T>`
puede usar el mismo nombre y contrato cuando exista demanda, pero no se reserva
ni implementa aquí; la vista sin copia ya cubre composición de views.

### 4.4 Construcción diagonal dense

Las firmas normativas son:

```aether
public Matrix<T> diagonalMatrix<T: Storable + Copy + Zero>(
    ref Vector<T,Column> values);

public Matrix<T> diagonalMatrix<T: Storable + Copy + Zero>(
    ref Vector<T,Row> values);
```

Para `k = dimension(values)`:

- retorna un owner Matrix `k×k` independiente;
- preserva el Vector y su orientación;
- inicializa toda celda off-diagonal con el `Zero` canónico de T;
- escribe `result[i,i] = values[i]` para `i=1..k`;
- usa una única allocation para `k>0`, ninguna para `k==0`;
- no crea Vector/Array/buffer auxiliar;
- cuesta O(k²) tiempo y O(k²) storage de resultado, con O(1) auxiliar;
- `k==0` retorna `0×0`.

Row y Column producen el mismo resultado; la orientación no se borra mediante
un parámetro runtime. Son dos overloads nominales, igual que los constructores
Vector existentes. V1 no agrega overloads para VectorView: pueden calificarse
después sin alterar estas firmas si aparece un consumer real.

`diagonalMatrix` se elige sobre `diag` porque declara que **construye una
Matrix** y deja disponible un nombre distinto, por ejemplo `diagonal`, para una
eventual extracción. No existe overload de extracción en este milestone.

## 5. Capabilities

`Storable` autoriza el elemento del owner resultado. `Copy` es necesaria porque
ambas operaciones preservan la fuente mientras duplican valores en un owner
nuevo. Sin Clone explícito, una entrada no-Copy no puede conservarse y a la vez
producir elementos independientes.

`Zero` es matemáticamente necesaria para `diagonalMatrix`. Para
`transposeCopy` no lo sería con un constructor por generador o una API segura
de inicialización slot-by-slot, pero la única primitive general disponible es
filled initialization y exige un valor incluso para expresar de forma uniforme
los zero shapes. Usar `Zero` evita memoria sin inicializar, raw pointers y un
cambio de compilador. Si una futura primitive source ordinaria por generador
permite inicializar exactamente una vez, un milestone separado podrá relajar
la firma de `transposeCopy` a `Storable + Copy` tras estudiar compatibilidad.

No se exige `Relocatable`, aritmética, `One`, `Numeric` ni `IEEEFloat`.
Inicialmente quedan admitidos float32, float64 e integers que satisfacen las
tres capabilities, además de cualquier futuro T válido. Views, refs y tipos no
Storable siguen rechazados por las reglas generales.

## 6. Borrowing, lifetime y composición

Una transpose view nunca posee ni prolonga la vida del backing. Su lifetime
queda limitado por la raíz y las reglas léxicas actuales. No se puede devolver
la view desde una función, guardarla dentro de `Matrix`, struct, enum, Array o
List, ni usarla después de mover/destruir el owner. El borrow bloquea ese move o
destrucción mientras esté vivo.

Views de views y slices componen intercambiando/preservando metadata, no
aplanando a un supuesto layout contiguous. Por ejemplo:

```aether
MatrixView<T> a = source[2:4,1:3];
MatrixView<T> at = transpose_view(a);
MatrixView<T> back = transpose_view(at);
```

`back` tiene el shape y los strides de `a` y comparte exactamente el mismo
backing. Los índices continúan siendo 1-based respecto de cada view lógica.

Las operaciones owning no retornan borrow y no comparten backing con la
fuente. Una vez termina la call, el resultado puede sobrevivir a la fuente. El
préstamo shared impide que la función escriba `source`; cualquier mutación por
otro alias conserva la semántica general vigente y no recibe promesa `noalias`.

## 7. Integración con algoritmos

El diseño habilita consumo general sin APIs especiales de factores:

```aether
SVD<float64> factor = la.svd(A);
Matrix<float64> V = la.transposeCopy(factor.Vt);
Matrix<float64> Sigma = la.diagonalMatrix(factor.S);

MatrixView<float64> Vview = transpose_view(factor.Vt); // sin copia
Matrix<float64> reconstructed =
    matrix_view(factor.U) * matrix_view(Sigma) * matrix_view(factor.Vt);
```

Un consumer que sólo necesita leer `V` usa `transpose_view(Vt)`; materializa
únicamente al pedir `transposeCopy`. QR puede leer `transpose_view(Q)` sin
copia y materializar una Matrix sólo cuando una API owning lo requiera. Lo
mismo aplica a LU, Cholesky y futuros factors.

`SVD<T>` conserva exactamente los fields `U`, `S`, `Vt`. No se agrega `V`,
`Sigma`, getters, cache ni lazy materialization. Tampoco se cambia la
implementación SVD, que ya usa transpose views internas para el branch wide.

## 8. Errores, evaluación y cleanup

No hay errores de shape propios: toda Matrix rectangular y todo Vector válido
están en el dominio. Bounds internos son demostrables por los loops. Overflow
de shape/capacity/bytes y fallo de allocation conservan las rutas generales de
`matrixFilled`.

La fuente se evalúa una vez. La salida no se publica hasta que
`matrixFilled` terminó su inicialización. Después, cada asignación reemplaza un
T Copy ya inicializado. Si el modelo de exceptions permite unwinding durante
una operación futura, el owner local completamente inicializado sigue cleanup
ordinario; no existe prefijo raw parcialmente construido en source.

`transposeCopy` y `diagonalMatrix` no consumen la entrada. Resultado y fuente
se destruyen independientemente una sola vez. Padding de la fuente nunca se
lee; padding futuro del resultado nunca se inicializa como celda lógica ni se
expone.

## 9. Costes observables

| Operación | Tiempo | Allocation | Storage nuevo | Copia de elementos |
|---|---:|---:|---:|---:|
| `transpose_view` | O(1) | 0 | descriptor 5 palabras | 0 |
| `transpose_view_mut` | O(1) | 0 | descriptor 5 palabras | 0 |
| `transposeCopy(m×n)` | O(m*n) | 1 si `m*n>0`, si no 0 | `n*m` celdas | `m*n` lógicas |
| `diagonalMatrix(k)` | O(k²) | 1 si `k>0`, si no 0 | `k²` celdas | `k` desde input |

El conteo de `transposeCopy` permite el fill seguro y la sobrescritura lógica;
la tabla cuenta copias desde la fuente, no stores totales. No hay conversiones
implícitas de views a owners, caches, temporaries Matrix ocultos ni buffers
auxiliares.

## 10. Qualification

### 10.1 Vista shared y mutable

Reusar y ampliar las pruebas existentes para cubrir:

- square, tall y wide;
- `0×0`, `m×0` y `0×n`, conservando el extent no cero;
- owner padded y subviews strided;
- view de view, slice de transpose y transpose de slice;
- doble transposición de shared y mutable;
- lectura 1-based y bounds en ambos ejes;
- escritura válida mediante `transpose_view_mut` observada en el owner;
- rechazo de `transpose_view_mut` desde `ref Matrix`/`MatrixView` shared;
- rechazo de move, replacement, return, storage y uso fuera de lifetime;
- aliases permitidos sin inferir exclusividad/noalias;
- cero allocation/free/element copy/drop por creación de views.

### 10.2 Transposición owning

Cubrir:

- Matrix square, tall y wide con valores no simétricos;
- `0×0`, `m×0`, `0×n` y shape invertido exacto;
- fuente padded con canarios en padding y resultado exact-capacity;
- fuente intacta y reusable; resultado sin alias y válido tras destruir fuente;
- float32, float64, int y otro T que satisfaga las capabilities;
- rechazo paramétrico por ausencia independiente de Storable, Copy o Zero;
- exactamente una allocation/free para resultado no vacío y cero para vacío;
- ningún owner/view/buffer auxiliar y ningún acceso a padding;
- cleanup exactamente una vez y ausencia de leaks en failure de allocation;
- igualdad O0/O2 y ausencia de fast-path layout que cambie semántica.

### 10.3 Matriz diagonal

Cubrir:

- Column y Row con k=0, 1 y varios elementos;
- diagonal exacta y Zero exacto en todas las `k²-k` celdas restantes;
- preservación y reutilización del Vector;
- float32, float64, signed/unsigned integers y otro T válido;
- una allocation para k>0, cero para k=0, sin buffers auxiliares;
- coste/store profile O(k²), owner independiente y cleanup;
- rechazo de tipo sin Zero, Copy o Storable;
- diferenciación source/diagnostic respecto de futura extracción diagonal.

### 10.4 IR y consumers

En HIR deben permanecer generic params/capabilities y los borrows shared. Tras
monomorfización, MIR/SSA deben contener tipos concretos, un solo
`MatrixFilled`, loops ordinarios, indexación 1-based y stores; no witnesses,
dispatch por TypeId ni opcodes nuevos. Verificar en O0/O2.

El consumer de integración debe demostrar:

- `V = transposeCopy(svd(A).Vt)` sin cambiar `SVD<T>`;
- `Sigma = diagonalMatrix(svd(A).S)` y reconstrucción compatible;
- QR usando tanto view como materialización explícita;
- ningún getter/función especializada de SVD;
- package/import canónico std y ausencia de duplicado OAL.

## 11. Secuencia mínima

Se recomiendan tres verticales, combinables en dos si la qualification comparte
harness:

1. **MATRIX-TRANSPOSE-VIEW-PUBLIC-1**: auditoría de exposición, documentación y
   qualification de los intrinsics existentes, sin cambio semántico. Si toda
   la matriz de pruebas ya está cubierta, este vertical se cierra sólo con
   evidencia y no modifica código.
2. **MATRIX-MATERIALIZATION-V1**: `transposeCopy` y `diagonalMatrix` juntos como
   funciones std source ordinarias, con capabilities, zero shapes, padding,
   allocations e IR.
3. **MATRIX-REPRESENTATION-QUALIFICATION-1**: consumer SVD/QR, negative compile
   tests, O0/O2, ownership/cleanup y cierre de distribución std.

Separar transposición owning y diagonalización en dos verticales sólo se
justifica si una falla de infraestructura independiente bloquea una de ellas.
No se programa una secuencia larga para tres recorridos simples.

## 12. Evolución compatible y fuera de scope

Un futuro `DiagonalMatrix<T>` puede ser un tipo sparse/structured separado y
tener conversiones explícitas. `diagonalMatrix(v)` seguirá significando el
owner `Matrix<T>` dense prometido aquí; no cambia silenciosamente de
representación ni retorna lazy storage.

Un futuro overload `transposeCopy(MatrixView<T>)` debe copiar sus celdas
lógicas mediante ambos strides y conservar el mismo coste explícito. No se
admite conversión automática view-to-owner.

Quedan fuera:

- SVD nueva/full o cambios a `SVD<T>`;
- pseudoinversa, least-squares, eigen u otros algoritmos derivados;
- extracción de diagonal;
- `DiagonalMatrix` como tipo;
- expression templates, cache o lazy transpose;
- BLAS/LAPACK y kernels nuevos;
- nuevas capabilities, raw/uninitialized allocation o cambios de ownership;
- cambios de compilador salvo que una implementación posterior demuestre un
  bloqueo estructural y lo reabra antes de escribir código.
