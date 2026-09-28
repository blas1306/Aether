# MATH-FORMAT-V1 — implementation report

Estado: **IMPLEMENTADO**, 2026-09-28.

## Alcance y representación

El perfil FORMAT reconoce composicionalmente los owners `Vector<T,Row>`,
`Vector<T,Column>` y `Matrix<T>` cuando T está admitido por la familia y posee
conversión FORMAT escalar estática. Views, elementos no admitidos y genéricos
sin prueba estática continúan produciendo E0340; no se añadió capability pública
`Format`.

La salida es byte-exacta: Row usa `[a, b]`, Column `[a; b]`, Matrix
`[a, b; c, d]`; los vacíos son `Row[]`, `Column[]` y `Matrix(m,n)[]`. Cada
elemento usa los formatters canónicos existentes, incluidos float shortest
round-trip, `-0`, NaN/Inf, bool y char sin quotes adicionales.

## IR y backend

Cada hole conserva `MathematicalAggregateFormat`: kind, aggregate/element
`TypeId`, conversión del elemento, traversal lógico y política empty. La receta
permanece idéntica en HIR, MIR y SSA dentro del `Interpolate` verificado y va
acompañada de la región FORMAT-BORROW.

El backend expande esa receta tipada en fases count/write. Count suma tamaños
con overflow checked antes de la única allocation final. Write emite al backing
final, sin strings owner por elemento. Vector usa dimension lógica; Matrix usa
rows/columns lógicos y calcula cada dirección física con `columnCapacity`. La
rama zero-shape precede cualquier acceso al backing. No se materializan
transpose, slices, filas, segunda Matrix ni arrays proporcionales al agregado.

No existe dispatch por `TypeId`, reflection, witness/callback formatter ni
helper específico de Matrix, LU o `linearAlgebra`. La machinery sólo aparece
cuando una receta matemática resulta alcanzable.

## Qualification e integración

Las pruebas ejecutables O0/O2 cubren Row/Column/Matrix no vacíos, repetición sin
consumo, referencias, mutación posterior, temporales y shapes 0×0, 0×n y m×0.
Los tests existentes conservan E0340 para views y tipos no interpolables, y
FORMAT-V1 conserva sus spellings escalares y su publicación única.

El dogfood del consumidor de `linearAlgebra` imprime L/U desde fields del LU y
después valida `solve(factor,b)` y `det(factor)`. No hay MoveField, Clone, Alias
defensivo, copia owner ni código especial para LU.

