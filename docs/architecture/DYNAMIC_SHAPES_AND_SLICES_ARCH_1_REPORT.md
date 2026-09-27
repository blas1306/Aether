# DYNAMIC-SHAPES-AND-SLICES-ARCH-1 — reporte

Estado: **ARQUITECTURA CERRADA; SIN IMPLEMENTACIÓN**, 2026-09-27.

Documento normativo:
[DYNAMIC_SHAPES_AND_SLICES_ARCH_1](DYNAMIC_SHAPES_AND_SLICES_ARCH_1.md).

## Resultado

Se cerró un único modelo para shapes runtime, crecimiento rectangular, slices
y asignación, sin modificar código.

- Vector conserva descriptor `{ptr,length}`, longitud runtime inmutable y
  orientación estática nominal. Row/Column y Vector/Matrix no se convierten.
- Matrix conserva siempre `rows` y `columns`, incluso con backing nulo. Esto
  distingue `0×0`, `m×0` y `0×n`; `[]` sigue significando sólo `0×0`.
- Para evitar repeated full copies, Matrix adopta capacities geométricas por
  ambos ejes. Su owner pasa a cinco palabras y su row stride físico es
  `columnCapacity`. Sólo el rectángulo lógico está inicializado.
- `A.add(v)` consume exactamente un Vector del mismo T. Row agrega fila,
  Column agrega columna; los extents complementarios deben coincidir. Los casos
  con primer vector y longitud/ejes cero quedaron definidos exhaustivamente.
- El consumo incluso para `T:Copy` queda como decisión consciente a calificar
  durante implementación: es uniforme y evita copias implícitas, pero puede ser
  ergonómicamente sorprendente. Se comparará con una variante copy-preserving
  para `T:Copy` que tome por préstamo y deje el Vector utilizable; no se cambia
  aún la semántica de `add`.
- Add requiere `T:Storable+Relocatable`, invalida direcciones y se rechaza con
  aliases vivos. Sin realloc cuesta O(longitud del vector); con realloc cuesta
  O(celdas existentes + vector), amortizado lineal bajo growth geométrico.
- Array/List permanecen 0-based y sus slices son owners independientes del
  mismo tipo. Vector/Matrix permanecen 1-based y sus slices son los views
  orientados/strided ya existentes.
- La única gramática slice es closed `a:b` o full `:`. Closed incluye ambos
  extremos y no puede ser vacío; `[:]` funciona directamente con extent cero.
- Scalar/scalar Matrix produce T; scalar/slice produce VectorView Row/Column;
  slice/slice produce MatrixView. Un closed slice de longitud uno no colapsa
  rank.
- Slice assignment no cambia length/shape. Requiere T:Copy, mutabilidad,
  extent/shape y orientación exactos. No hay broadcasting, padding o resize.
- Overlap tiene semántica de snapshot RHS. Temporales, memmove y dirección de
  traversal son optimizaciones siempre que preserven ese resultado.
- Una capacidad fundamental, general y segura de filled-init asigna e
  inicializa completamente owners runtime. Cualquier package puede usarla bajo
  los mismos constraints; no hay autorización especial para std/OAL.
- `linearAlgebra.zeros/ones/identity` son implementaciones ordinarias sobre esa
  capacidad, igual que podrían serlo abstracciones comunitarias. Matrix acepta
  uno o dos extents; Vector uno y toma orientación del expected type.
  `zeros(n)` Matrix es `n×n`.

## Tabla de tipos resultantes

| Forma | Resultado |
|---|---|
| `array[a:b]`, `array[:]` | owner `Array<T>` nuevo |
| `list[a:b]`, `list[:]` | owner `List<T>` nuevo |
| `vector[a:b]`, `vector[:]` | `VectorView<T,O>` |
| `A[i,j]` | T/Place escalar |
| `A[i,:]` | `VectorView<T,Row>` |
| `A[:,j]` | `VectorView<T,Column>` |
| cualquier slice en ambos ejes Matrix | `MatrixView<T>` |

Los slices matemáticos cuestan O(1) y heredan lifetime/procedencia. Las copias
de colecciones y materializaciones cuestan O(cantidad de elementos).

## Frontera fundamental/packages

```text
runtime/compiler
  checked allocation + full initialization before owner publication
                         |
                         v
general safe core/low-level surface (same constraints for every package)
                         |
              +----------+----------+
              |                     |
              v                     v
linearAlgebra zeros/ones/identity   community package abstractions
```

La superficie exige `T:Storable+Copy` y un valor T inicializado obligatorio;
comprueba shapes, productos y bytes, inicializa cada celda lógica antes de
publicar el owner y no lee/destruye padding. Los zero shapes conservan metadata
sin backing. No expone raw pointers, uninitialized memory, `assume_init` ni
capacity. Que `linearAlgebra` sea OAL sólo expresa metadata/ownership según
PACKAGE-MANAGER-ARCH-1 y no le concede acceso técnico especial.

## Capacidad de lenguaje faltante

La API exacta de `zeros/ones` no se puede declarar hoy en compiler-next. Faltan
overload sets, selección por expected result type, inferencia de T sólo desde el
retorno y parametrización/selección contextual de Row/Column. La solución
recomendada es una capacidad general de contextual overload resolution; se
rechazan hacks por nombre `zeros` y variantes públicas por orientación.

`A.add(v)` puede implementarse antes como intrinsic method porque receiver y
argumento determinan unívocamente T/orientación. También faltan en el pipeline
selectors Scalar/Closed/Full, slice places, snapshot assignment y operaciones
IR verificables para todos ellos.

## Auditoría de implementación existente

Compiler-next ya aporta las identidades nominales correctas, bases separadas,
rectangularidad de literales, owners, queries, MatrixView/VectorView con
strides, axis views, transpose, procedencia y borrow invalidation. Esas piezas
se reutilizan.

Requieren cambio el descriptor Matrix `{ptr,rows,columns}`, toda su aritmética
que asume `rowStride==columns`, la canonicalización de vacío a `0×0`, el AST
Index de expresiones sin selectors y los IR sin slice/add/filled-init.

El compilador legacy ya posee slices Array/List owning, pero su intervalo es
semiabierto y `[:]` no existe. Debe migrar a closed bounds y Full selector; no
puede permanecer como semántica alternativa. Sus reglas de proofs, optimizers,
runtime helpers y fixtures también usan hoy `start<=end<=length`.

La auditoría de `linearAlgebra/src/lib.ae` confirmó el problema original: QR
crea su workspace `m×m` mediante `A * transpose_view(A)` y luego sobrescribe
todas las entradas. `zeros/identity` reemplazarán esa operación matemática
artificial sin un hack especial en QR.

## Orden recomendado

1. descriptor/capacity/zero shapes Matrix;
2. filled-init general seguro y accesible uniformemente por packages;
3. `Matrix.add` con ambos ejes y growth amortizado;
4. AST/parser de Scalar/Closed/Full;
5. slices read-only matemáticos y de colecciones;
6. slice assignment y overlap snapshot;
7. overload resolution contextual;
8. `linearAlgebra.zeros/ones/identity` y retiro del workaround QR;
9. migración/parity del compiler legacy.

## Validación de este milestone

- Se crearon sólo el documento normativo y este reporte.
- No se modificó parser, HIR, MIR, SSA, backend, runtime, std, OAL ni tests.
- Se preservaron los cambios preexistentes de `README.md` y `CHANGELOG.md`.
- Quedaron cerrados invariantes, zero shapes, add, bases, gramática, tipos de
  resultado, assignment, overlap, frontera de allocation, costos, capacidades
  faltantes, compatibilidad y orden de implementación.
