# MATH-FORMAT-ARCH-1 — formatting de Vector y Matrix

Estado: **ARQUITECTURA CERRADA; NO IMPLEMENTADA**, 2026-09-28.

Este milestone extiende el perfil FORMAT de manera estática y composicional a
los owners matemáticos `Vector<T,Row>`, `Vector<T,Column>` y `Matrix<T>`. No
modifica todavía frontend, HIR, MIR, SSA, backend, runtime, Core, stdlib,
`linearAlgebra` ni tests ejecutables.

Son autoridad de base
[FORMAT-ARCH-1](FORMAT_ARCH_1.md)/[FORMAT-V1](FORMAT_V1_REPORT.md) para texto,
evaluación y construcción count/write, y
[FORMAT-BORROW-ARCH-1](FORMAT_BORROW_ARCH_1.md) para observación sin transferir
ownership. La representación y los extents matemáticos provienen de
[DYNAMIC-SHAPES-AND-SLICES-ARCH-1](DYNAMIC_SHAPES_AND_SLICES_ARCH_1.md) y
[MATRIX-DYNAMIC-DESCRIPTOR-V1](MATRIX_DYNAMIC_DESCRIPTOR_V1_REPORT.md).

No se agrega reflection, lookup de métodos, dispatch por `TypeId`, un protocolo
user-defined ni un caso especial en `println`, LU o la biblioteca algebraica.

## 1. Decisiones resumidas

- Si un `T` concreto pertenece al perfil FORMAT activo y ya es un elemento
  admitido de la familia matemática, `Vector<T,O>` y `Matrix<T>` son
  interpolables. Formatting no amplía por sí mismo la admisión de elementos.
- Row no vacío usa `[a, b, c]`; Column no vacío usa `[a; b; c]`. Los singletons
  de ambas orientaciones usan `[a]`.
- Los vectores vacíos distinguen orientación con `Row[]` y `Column[]`.
- Toda Matrix con ambos ejes positivos usa `[a, b; c, d]`, en una sola línea
  salvo que los bytes FORMAT de un elemento contengan un salto de línea.
- Toda Matrix con algún eje cero conserva ambos extents:
  `Matrix(0,0)[]`, `Matrix(0,n)[]` o `Matrix(m,0)[]`, sin espacios dentro de la
  pareja de extents.
- Cada elemento usa exactamente la conversión FORMAT canónica de `T`. Math
  formatting no cambia precisión, escaping, quoting, NaN, infinities ni signed
  zero y no crea strings owner por elemento.
- V1 admite sólo owners `Vector`/`Matrix`. `VectorView`, `VectorViewMut`,
  `MatrixView` y `MatrixViewMut` continúan produciendo E0340.
- HIR conserva una conversión agregada tipada. MIR/SSA conservan count/write y
  traversal lógico explícitos. El backend emite loops directos y sólo reutiliza
  primitives privados FORMAT; el runtime no selecciona tipos.
- FORMAT-BORROW es una dependencia independiente: MATH-FORMAT decide si el
  tipo y su texto están soportados; FORMAT-BORROW decide cómo observar owner,
  field, referencia o temporal sin Move/Clone.

## 2. Regla de interpolabilidad

Para un perfil FORMAT `P`, la regla conceptual es:

```text
math_interpolable_P(Vector<T,Row>)    iff
    admitted_vector_element(T) && interpolable_P(T)

math_interpolable_P(Vector<T,Column>) iff
    admitted_vector_element(T) && interpolable_P(T)

math_interpolable_P(Matrix<T>)        iff
    admitted_matrix_element(T) && interpolable_P(T)
```

La consulta es estructural sobre `TypeData`, pero cerrada y estática. No es una
implicación general para cualquier generic o colección. Tampoco hace
interpolables Array, List, Buffer, sparse matrices o tipos que sólo se parezcan
por layout.

`admitted_*_element` continúa siendo la autoridad de formación del tipo. Esta
feature no permite construir una Matrix que el lenguaje rechace ni suma
`Numeric`, `Copy` o `Relocatable` a la constraint base `Storable`. El requisito
adicional sólo aparece al usar el valor en un hole FORMAT: el `T` concreto debe
tener una conversión FORMAT conocida.

Un parámetro simbólico `T:Storable` no demuestra interpolabilidad. Como no
existe una capability pública `Format`, un cuerpo generic que intente
interpolar `Matrix<T>` o `Vector<T,O>` falla cerrado con E0340. Admitir una
constraint pública de formatting requiere otro milestone; no se difiere la
selección hasta runtime ni se acepta el cuerpo esperando monomorphization.

FORMAT-BORROW aplica antes de esta consulta sólo para normalizar referencias:

```text
formatted_type(ref T)     = formatted_type(T)
formatted_type(ref mut T) = formatted_type(T)
```

Así, cuando ambos verticales estén implementados, owner, proyección y
referencia a una Matrix soportada comparten la misma respuesta. Sin
FORMAT-BORROW implementado, MATH-FORMAT no autoriza mover o copiar el owner como
atajo.

## 3. Representación de Vector

### 3.1 Vectores no vacíos

El orden es siempre el índice lógico creciente `1..dimension`:

| Tipo y longitud | Resultado |
|---|---|
| `Vector<T,Row>`, 1 | `[e1]` |
| `Vector<T,Row>`, n > 1 | `[e1, e2, ..., en]` |
| `Vector<T,Column>`, 1 | `[e1]` |
| `Vector<T,Column>`, n > 1 | `[e1; e2; ...; en]` |

Hay exactamente un espacio ASCII después de `,` o `;`, ninguno tras `[` ni
antes de `]`, y nunca trailing separator. Esta forma coincide visualmente con
los literals matemáticos: coma separa entradas de una fila y punto y coma
separa filas.

La orientación es observable mediante el separator cuando existen al menos dos
elementos. Un singleton no contiene una frontera en la que expresar
orientación; agregarle un tag haría verboso el caso ordinario y rompería la
simetría literal-like. Por ello Row(1) y Column(1) tienen el mismo texto. FORMAT
es presentación humana contextual, no una codificación autosuficiente del
TypeId.

### 3.2 Vectores vacíos

La salida normativa es:

| Tipo | Resultado |
|---|---|
| `Vector<T,Row>` de longitud 0 | `Row[]` |
| `Vector<T,Column>` de longitud 0 | `Column[]` |

En el vacío no existe separator que pueda comunicar orientación. Usar `[]` para
ambos borraría la única propiedad matemática que distingue los dos TypeIds; el
prefijo corto reutiliza los nombres source `Row`/`Column` sin fingir que la
salida es un literal aceptado por el parser. Es estable aunque `T` no tenga
ningún valor materializado.

No se escribe `Vector<T,...>` porque el nombre o spelling de `T` no forma parte
de FORMAT y no existe reflection textual de tipos.

## 4. Representación de Matrix

### 4.1 Ambos ejes positivos

Una Matrix `m×n`, con `m > 0` y `n > 0`, se recorre en row-major lógico y usa:

```text
[e(1,1), e(1,2); e(2,1), e(2,2)]
```

Normativamente:

- `, ` separa columnas dentro de una fila;
- `; ` separa filas;
- sólo existe la pareja exterior `[`/`]`;
- no hay brackets por fila, trailing separators, padding ni alineación;
- 1×1 es `[e]`, 1×n usa sólo comas y m×1 usa sólo puntos y coma.

El formatter no consulta terminal width, locale ni longitud de las celdas. No
inserta indentación o nuevas líneas propias. La forma es determinista y
literal-like tanto para matrices rectangulares como cuadradas.

### 4.2 Shapes con un eje cero

Rows y columns son metadata semántica independiente aun con cero elementos y
backing nulo. Toda Matrix con `rows == 0 || columns == 0` usa:

```text
Matrix(<rows>,<columns>)[]
```

Por ejemplo:

| Shape | Resultado |
|---|---|
| 0×0 | `Matrix(0,0)[]` |
| 0×3 | `Matrix(0,3)[]` |
| 3×0 | `Matrix(3,0)[]` |

Los extents se escriben en decimal ASCII canónico de `usize`, sin signo,
leading zeros ni locale. No hay espacio tras la coma. La forma conserva la
shape completa y mantiene `[]` como señal visual de ausencia de elementos. Se
elige también para 0×0, aunque el literal Matrix `[]` ya denote esa shape, para
que las tres zero shapes compartan una regla y el texto no se confunda con un
Vector vacío.

El formatter no recorre el backing en ninguna zero shape. Los extents se leen
del descriptor ya validado; no se deducen desde pointer, capacity o stride.

## 5. Composición con el formatter de T

Cada `ei` se obtiene con exactamente la conversión que el perfil FORMAT activo
asigna a `T`. La capa matemática sólo agrega brackets, separators y, para
vacíos, metadata de orientación/shape. En particular:

- integers conservan decimal canónico;
- `float32` y `float64` conservan shortest-round-trip, `0`/`-0`, `NaN`, `Inf`
  y `-Inf` de FORMAT-V1;
- `bool` conserva `true`/`false`;
- `char` conserva exactamente su scalar UTF-8 sin quotes ni escaping;
- una futura categoría FORMAT conserva su propia semántica sin ser redefinida
  por Matrix/Vector.

No se llama `str` para producir un owner intermedio por elemento. Count invoca
la primitive de medición de T y write su primitive de emisión directamente
sobre el backing final de la interpolación.

### 5.1 `char` y `string`

`char` satisface hoy la admisión matemática basada en `Storable` y pertenece a
FORMAT-V1. Por tanto, `Vector<char,O>` y `Matrix<char>` son interpolables. Se
acepta conscientemente que un char `,`, `;`, `[`, `]` o whitespace pueda ser
visualmente ambiguo y que LF/CR pueda hacer físicamente multilínea la salida.
Agregar quotes o escapes cambiaría el formatter de T y violaría composición
exacta. La salida sigue siendo byte-determinista, pero no promete parseabilidad
ni una línea cuando los bytes del elemento contienen line breaks.

`string` pertenece a FORMAT-V1, pero la admisión actual rechaza expresamente
`Vector<string,O>` y `Matrix<string>`. MATH-FORMAT no levanta ese gate y por
tanto no crea hoy un caso de strings como elementos. Si otro milestone admite
ese storage, la regla composicional reutilizará bytes string sin quotes,
escaping ni normalización; cualquier política distinta deberá cambiar primero
el contrato general, no esconderse en este formatter.

## 6. Owners y views

El primer vertical incluye exclusivamente:

```text
Vector<T,Row>
Vector<T,Column>
Matrix<T>
```

Quedan fuera:

```text
VectorView<T,O>
VectorViewMut<T,O>
MatrixView<T>
MatrixViewMut<T>
```

Aunque el traversal lógico de una view sería equivalente y observacional, no
es gratis en el contrato: exige preservar provenance/keepalive durante ambas
pasadas, aceptar strides arbitrarios y negativos si llegan a existir, resolver
mutable-view effects y verificar que ningún descriptor borrowed escape. El
vertical owner ya cumple el dogfood LU y mantiene pequeño el nuevo set.

Una extensión posterior puede admitir las cuatro views aditivamente usando la
misma sintaxis y orden lógico, nunca mostrando strides/layout. Hasta entonces
un hole de view produce E0340; no se materializa un owner como fallback.

## 7. Traversal y layout

Vector recorre exactamente:

```text
for i in 1..=dimension(vector)
    format(vector[i])
```

Matrix recorre exactamente:

```text
for i in 1..=rows(matrix)
    for j in 1..=columns(matrix)
        format(matrix[i,j])
```

La notación expresa índices source; el lowering puede usar contadores internos
0-based después de probar los límites. El address de Matrix usa el stride
físico owner vigente (`columnCapacity` en el descriptor actual), pero los
límites y separators dependen sólo de `rows`/`columns`. Nunca se itera hasta
`rowCapacity * columnCapacity`, se inspecciona padding ni se asume
`rowStride == columns`.

Las dos pasadas repiten el mismo traversal de lectura. No materializan
transpose, slice, Vector por fila, Array/List auxiliar ni segunda Matrix. Cada
elemento lógico se mide una vez y se escribe una vez; padding se toca cero
veces. El owner permanece inmutable durante el plan por el shared borrow de
FORMAT-BORROW.

## 8. Evaluación, ownership y lifecycle

Se conserva el orden de FORMAT-V1:

1. evaluar cada hole exactamente una vez, de izquierda a derecha;
2. capturar su acceso tipado; para un owner matemático, shared observation según
   FORMAT-BORROW;
3. medir chunks y agregados en orden con suma checked;
4. reservar un único backing final exacto si el total no es vacío;
5. emitir fragments y publicar el owner string;
6. cerrar borrows y destruir roots temporales según el plan ordinario.

MATH-FORMAT no introduce Move, Clone, Alias, retain, COW ni partial-move de una
Matrix/Vector. `factor.L` se conserva como proyección de Place; `ref Matrix<T>`
observa el pointee; un rvalue se estabiliza en el root temporal definido por
FORMAT-BORROW. El borrow debe cubrir count y write y terminar antes de que
`Interpolation` entregue su resultado.

Esta arquitectura no implementa por sí sola esa adaptación. El vertical puede
agregar la nueva interpolabilidad independientemente, pero el dogfood non-Copy
queda gated hasta que FORMAT-BORROW esté implementado y calificado. No se
permite resolver el orden temporal copiando la Matrix.

## 9. Costos

Para `n = dimension(vector)` y una Matrix `m×n`:

| Operación | Tiempo | Storage adicional |
|---|---:|---|
| Vector count + write | O(n) + O(n) = O(n) | bookkeeping escalar + backing final |
| Matrix count + write | O(m·n) + O(m·n) = O(m·n) | bookkeeping escalar + backing final |
| zero shape | O(1) | backing final de la notación, si no está fusionado con una interpolación mayor |

El backing final es el único storage proporcional al texto producido. Los
buffers privados acotados ya permitidos para formatting scalar no son owners
string ni crecen con el número de elementos. No hay tabla de longitudes por
elemento, row owners, builder público o cadena de concatenaciones.

Los separators tienen longitud constante y se cuentan con aritmética checked.
Una implementación puede computar su cantidad de manera cerrada, pero no puede
usar esa optimización para saltar validación de extents o cambiar traversal.

## 10. Representación por fases

### 10.1 AST y resolución

AST no cambia: `${matrix}` sigue siendo un hole de una literal interpolada
ordinaria. La resolución centraliza `interpolable_type` y, tras normalizar el
acceso con FORMAT-BORROW, reconoce los tres `TypeData` owners y valida
recursivamente el formatter estático de su element TypeId.

No existe sintaxis especial, `matrixToString`, `printMatrix`, `show` ni overload
de `println`. `"${matrix}"`, `"A=${matrix}"` y `"${vector}"` producen un string
owned mediante `Interpolation` normal.

### 10.2 HIR

`InterpolationFragment::Hole` conserva una conversión nueva conceptual:

```text
MathematicalAggregateFormat {
    kind: Vector(Row) | Vector(Column) | Matrix,
    aggregate_type: TypeId,
    element_type: TypeId,
    element_conversion: InterpolationConversion,
    traversal: LogicalVector | LogicalMatrixRowMajor,
    empty_representation: OrientedVector | ShapedMatrix,
}
```

No contiene valores de extents duplicados ni una lista de elementos: éstos son
runtime data del operand capturado. El verifier reconstruye todos los campos
desde el TypeId, exige owner (no view), element admission e interpolabilidad y
rechaza recursion, conversion kind o traversal corruptos. Access/borrow y
conversion siguen siendo ejes distintos conforme a FORMAT-BORROW.

### 10.3 MIR

MIR conserva una región FORMAT matemática con descriptor borrowed, extents
lógicos, recipe estática del elemento y fases `Count`/`Write`. El lowering hace
explícitos:

- lectura única del descriptor estable;
- branching de zero shape antes de cualquier element address;
- loops lógicos y separators;
- checked add de cada longitud;
- `Borrow`/`EndBorrow` y cleanup, cuando FORMAT-BORROW aplique;
- resultado no publicado durante count o write parcial.

No se baja a una call opaca que reciba `Any`, TypeId o formatter callback. Los
verificadores MIR prueban type/shape recipe, dominios de loop, acceso al layout
correcto y ausencia de owner intermediario.

### 10.4 SSA

SSA retiene los loops count/write y metadata de consumer FORMAT. Su verifier
comprueba que count y write usan el mismo kind, element type, extents y orden;
que los GEPs están dominados por bounds/zero checks; que Matrix direcciona con
el stride físico verificado; que el resultado se publica una vez; y que el
borrow no escapa ni cruza su `EndBorrow`.

O0 y O2 pueden optimizar induction variables, separator counts o helpers, pero
deben preservar exactamente los mismos bytes, traps, reads lógicos y lifecycle.

### 10.5 Backend y runtime

El backend genera los loops desde SSA ya tipado. Reutiliza las primitives
privadas count/write de FORMAT-V1 para cada element category y la
allocation/publicación string existente. Puede especializar helpers por tipo
canónico en compile time, pero no emitir un switch de TypeId, witness table,
boxed value, virtual call o callback formatter.

No se agrega ningún símbolo específico de LU o `linearAlgebra`. Si se extraen
helpers generales, sus firmas quedan monomorfizadas/tipadas por el lowering y
reciben descriptor/extents ya verificados; no poseen policy de ownership ni
deciden interpolabilidad.

## 11. Overflow, fallos y atomicidad

Se reutilizan exactamente los traps y reglas FORMAT-V1:

- cada longitud de elemento y delimiter se suma con checked `usize`;
- la notación de extents vacíos también se mide con primitives canónicas y suma
  checked;
- overflow total produce `AllocationSizeOverflow` antes de allocation;
- allocation fallida produce `AllocationFailure`;
- ningún backing parcial se publica ni ningún string parcial es observable;
- no existe `MathFormatException` ni excepción algebraica nueva.

Los formatters del perfil actual no lanzan language exceptions. Si un perfil
futuro admite un formatter con failure, éste conserva su semántica general y
el plan debe limpiar temporales/borrows ordinarios; MATH-FORMAT no lo convierte
en zero, placeholder o debug fallback. Los traps abortivos conservan la política
de cleanup ya cerrada por FORMAT-V1.

Un descriptor corrupto es corrupción de IR/runtime y sigue los verificadores o
traps de Matrix/Vector existentes. Formatting no normaliza extents, capacity o
pointer inconsistentes.

## 12. Determinismo y round-trip

Para el mismo valor, TypeId y perfil FORMAT, el output es idéntico entre O0/O2
y no depende de locale, terminal, capacity, padding, dirección, target debug
mode ni heurísticas pretty-print. Sólo bytes propios de un elemento `char`
pueden incluir whitespace/newlines; no son decisiones adaptativas del agregado.

V1 no promete round-trip ni que el parser acepte `Row[]`, `Column[]` o
`Matrix(m,n)[]`. Incluso formas no vacías pueden ser ambiguas con `char`. El
parecido con literals es una decisión ergonómica de lectura humana, no una
serialización, un debug dump autocontenido o una reconstrucción de tipos.

## 13. Diagnostics

Se conserva E0340 como único diagnóstico de interpolabilidad:

- `Matrix<T>` o `Vector<T,O>` con `T` no interpolable: E0340 en el hole,
  nombrando el tipo agregado completo y aclarando que su element type no
  pertenece al perfil FORMAT;
- generic `Matrix<T>` sin prueba estática: E0340, sin esperar instantiation;
- cualquiera de las cuatro views: E0340 nombrando la view exacta y señalando
  que MATH-FORMAT-1 admite sólo owners;
- referencia a un agregado no soportado: E0340 sobre el tipo subyacente según
  FORMAT-BORROW, no sobre su dirección.

Ejemplos conceptuales:

```text
E0340: type Matrix<Unknown> is not interpolable: element type Unknown is not
       interpolable in the active FORMAT profile

E0340: type MatrixView<float64> is not interpolable in MATH-FORMAT-1;
       only owning Matrix<T> is supported
```

Un `T` que ni siquiera sea un elemento matemático válido falla antes bajo el
diagnóstico ordinario de formación/admisión del tipo; MATH-FORMAT no reemplaza
la causa por E0340. Conflictos de borrow, uso tras move y corrupción conservan
sus diagnósticos existentes. No se crean códigos exclusivos de álgebra lineal.

## 14. Casos normativos

Asumiendo el formatter scalar FORMAT-V1:

| Valor | Texto |
|---|---|
| Row vacío | `Row[]` |
| Column vacío | `Column[]` |
| Row `[1]` | `[1]` |
| Column `[1]` | `[1]` |
| Row `[1,2,3]` | `[1, 2, 3]` |
| Column `[1,2,3]` | `[1; 2; 3]` |
| Matrix 0×0 | `Matrix(0,0)[]` |
| Matrix 0×3 | `Matrix(0,3)[]` |
| Matrix 3×0 | `Matrix(3,0)[]` |
| Matrix 1×1 con 2 | `[2]` |
| Matrix 1×3 | `[1, 2, 3]` |
| Matrix 3×1 | `[1; 2; 3]` |
| Matrix 2×3 | `[1, 2, 3; 4, 5, 6]` |
| Matrix con `-0`, `NaN`, `Inf` | `[-0, NaN, Inf]` |

Que Row(3), Matrix(1×3), Column(3) y Matrix(3×1) puedan compartir texto es
intencional: FORMAT conserva estructura visual, no el TypeId completo. Vacíos
son distintos porque allí se perderían extents/orientación que no tienen ninguna
representación elemental.

## 15. Qualification del futuro vertical

La suite dedicada debe cubrir en O0 y O2:

1. bytes exactos para Row/Column de longitud 0, 1 y múltiples;
2. Matrix 0×0, 0×n, m×0, 1×1, 1×n, m×1, rectangular y square;
3. int, float32, float64, bool y char cuando sean elementos admitidos;
4. float signed zero, NaN e infinities sin cambio de policy;
5. char delimitador, U+0000, Unicode multibyte y newline byte-exact;
6. nested interpolation, labels y formatting repetido;
7. extents lógicos con capacity/padding mayor y cero reads de padding;
8. HIR/MIR/SSA dumps con aggregate conversion, count/write y loops correctos;
9. corrupciones independientes de kind, element TypeId, traversal, extents,
   conversion y publicación;
10. ausencia de transpose, slice, row Vector, segunda Matrix y owner string por
    elemento;
11. checked overflow/OOM y no publicación parcial;
12. `T` no interpolable y generic no probado producen E0340;
13. las cuatro views producen E0340 sin materialización;
14. salida idéntica O0/O2 y suites FORMAT/math/ownership previas verdes;
15. reachability: un programa sin math formatting no enlaza su machinery.

Con FORMAT-BORROW implementado, se agregan owner, field, nested field, ref,
ref mut y rvalue Matrix/Vector, con ausencia estructural de Move/Clone/Alias y
borrow terminado antes del statement siguiente.

Dogfood obligatorio conjunto:

```aether
var factor = linearAlgebra.lu(A);

println("L = ${factor.L}");
println("U = ${factor.U}");

solve(factor, b);
det(factor);
```

Los overloads vigentes sobre `ref LU<T>` permiten exactamente ese orden: ni
`solve(factor,b)` ni `det(factor)` consumen el factor. La prueba debe demostrar
que formatting no lo consume ni lo deja partial-moved y que ambos usos
posteriores siguen siendo legales sobre el mismo owner.

## 16. Orden de implementación

1. Centralizar la consulta de interpolabilidad recursiva sin ampliar el perfil
   scalar ni agregar capability pública.
2. Agregar la conversion HIR matemática y verifier de kind/element/traversal,
   inicialmente para owners concretos.
3. Incorporar count exacto de delimiters, empty Vector y zero-shape Matrix con
   checked-size y pruebas negativas.
4. Bajar traversal owner lógico a MIR, incluyendo layout padded Matrix, sin
   strings ni owners intermedios.
5. Preservar regions/loops y verificarlos independientemente en SSA.
6. Emitir count/write directo en backend reutilizando primitives FORMAT-V1 y
   calificar reachability.
7. Integrar FORMAT-BORROW para owners/projections/refs/temporales non-Copy y
   verificar lifecycle normal/unwind.
8. Completar output byte-exact, corruptions, O0/O2, padding, diagnostics y
   regresiones.
9. Ejecutar dogfood LU y qualification global; no modificar `linearAlgebra`.
10. Considerar views sólo en un milestone aditivo posterior.

## 17. Alternativas rechazadas

| Alternativa | Motivo |
|---|---|
| `[]` para ambos Vector vacíos | pierde orientación sin ningún elemento que la sugiera |
| `[]` para todas las Matrix vacías | colapsa 0×0, 0×n y m×0 |
| tags para todo Vector/Matrix | hace verboso el caso común y se aleja de literals |
| brackets por fila o pretty table | rompe la sintaxis visual elegida y agrega policy de layout |
| quoting especial de char/string | redefine FORMAT de T y crea dos representaciones contextuales |
| materializar `str(element)` | owner/allocation por elemento y trabajo evitable |
| convertir cada fila en Vector | allocation/owner y traversal no necesarios |
| helper `printMatrix`/caso `println` | no compone como string y acopla IO con tipos matemáticos |
| helper de LU/linearAlgebra | formatting pertenece al lenguaje y debe servir a todo owner |
| formatter callback o switch TypeId runtime | dispatch dinámico/reflection y verifier débil |
| incluir views por layout similar | amplía provenance, strides y lifetime del primer vertical |
| hacer Move/Clone para non-Copy | cambia ownership y costo; FORMAT-BORROW es la solución |

## 18. Fuera de alcance

- user-defined formatting protocol o constraint pública `Format`;
- format specifiers, precision configurable o scientific policy nueva;
- pretty tables, alineación, multiline adaptativo, terminal width o colors;
- parser/round-trip/serialization;
- views matemáticas en V1, sparse matrices, tensors o `Complex<T>`;
- cambios a element admission, capabilities numéricas o storage de string;
- cambios en `linearAlgebra`, LU, solve o det;
- partial moves, Clone/COW implícito o streaming directo a output;
- APIs explícitas `matrixToString`, `printMatrix` o `show`.

## 19. Criterio de cierre futuro

El vertical sólo estará implementado cuando tipos y output coincidan con estas
tablas, zero shapes preserven ambos extents, cada elemento use el formatter
vigente sin owner string intermedio, count/write recorra sólo storage lógico,
HIR/MIR/SSA prueben el plan de manera independiente y O0/O2 sean byte-idénticos.
El dogfood LU requiere además FORMAT-BORROW calificado y debe demostrar que el
factor sigue válido después de interpolar `L` y `U`.
