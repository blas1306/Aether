# SLICE-SELECTORS-V1 — reporte

Estado: **IMPLEMENTADO**, 2026-09-27.

Autoridad normativa:

- [DYNAMIC_SHAPES_AND_SLICES_ARCH_1](DYNAMIC_SHAPES_AND_SLICES_ARCH_1.md)
- [DYNAMIC_SHAPES_AND_SLICES_ARCH_1_REPORT](DYNAMIC_SHAPES_AND_SLICES_ARCH_1_REPORT.md)

## Superficie y gramática

El subscript conserva ahora una lista no vacía y ordenada de selectors AST:

```text
Scalar(expression)
Closed { first, last }
Full
```

`Closed` representa exclusivamente `a:b`, con ambos extremos presentes. `Full`
representa `:` como nodo real, sin fabricar cero, extent ni otro endpoint; por
eso también representa correctamente un eje cuyo extent futuro sea cero. El
parser contextual de brackets no reutiliza `AstExprKind::Range`.

Se admiten selectors escalares, closed y full, tanto unidimensionales como en
las combinaciones de dos ejes de Matrix. Los endpoints pueden contener
expresiones anidadas ordinarias. Base, selectors y endpoints permanecen una
sola vez y en orden source; el tipado los recorre base primero y luego cada
selector de izquierda a derecha, con `first` antes de `last`.

## Representación tipada

HIR introduce `HirSubscript` y `HirSubscriptSelector`. Cada selector conserva:

- la expresión escalar o los dos endpoints closed, o un `Full` sin endpoints;
- el eje `Linear`, `Row` o `Column`;
- `IndexSemantics` y la base resuelta 0/1.

El subscript completo conserva el `TypeId` del container, su familia exacta
(`Array`, `List`, `Vector`, `VectorView`, `Matrix`, `MatrixView`, además de las
familias escalares existentes) y el resultado futuro determinado por rank:
escalar, owner de colección, vector orientado o matriz. Estas variantes de
resultado son metadata; este vertical no construye un `VectorView` o
`MatrixView` de slice.

El caso escalar usa la misma proyección Place y el mismo MIR/SSA/backend
existentes. MIR exige un subscript HIR verificado y completamente escalar. El
verificador HIR valida cantidad, eje, base, semántica, container, tipos `usize`,
resultado escalar y flag checked, y falla cerrado ante corrupción independiente
de esos campos.

## Aridad y compatibilidad

La aridad se resuelve después de conocer el tipo:

- Buffer/Array/List/View/Vector/VectorView: exactamente un selector;
- Matrix/MatrixView: exactamente dos selectors.

Array/List conservan metadata 0-based. Vector/Matrix y sus views conservan
metadata 1-based. La indexación completamente escalar continúa bajando a los
IR existentes sin cambios de semántica, bounds trap ni ABI.

## Diagnostics

Se fijaron diagnostics estructurados y no se reinterpretan spellings legacy:

- `E0452`: slice parcial `a:` o `:b`;
- `E0453`: stride/reverse (`a:s:b`, `::`, `::-1`, `a::s`);
- `E0454`: más de los colons de un selector con stride;
- `E0455`: selector/matriz mal formado (selector ausente, coma final o
  separador inválido);
- `E0334`: cantidad de selectors incompatible con el rank del container;
- `E0457`: slice sobre Buffer/View, que no forma parte de los containers slice
  de la arquitectura;
- `E0456`: el selector slice quedó parseado y tipado, pero su lectura o
  asignación pertenece al siguiente vertical.

`E0456` informa resultado futuro, clase de container, ejes y base resueltos;
esto evita aceptar silenciosamente slices antes de que existan materialización,
views y sus invariantes runtime.

## Cobertura

La suite `slice_selectors_v1` cubre Scalar/Closed/Full, todas las combinaciones
Matrix pedidas, endpoints anidados, unicidad y orden de expresiones, forms
parciales, stride/reverse, múltiples colons, sintaxis Matrix mal formada,
errores de aridad, metadata 0-based/1-based, orientación/rank futuro y `Full`
sobre Matrix de shape cero. También conserva indexación escalar Array, List,
Vector y Matrix en O0/O2. Una prueba unitaria del frontend corrompe eje, base,
resultado, container y clase de selector HIR y exige rechazo del verificador.

## Fuera de alcance preservado

No se implementaron lectura/materialización de slices, copias owning de
Array/List, creación de views Vector/Matrix, bounds/order runtime de slices,
slice assignment, snapshots de overlap, overloads contextuales, `zeros`/`ones`
ni migración del compilador legacy. En particular todavía no se calcula
`last-first+1` ni se trata `first>last` como operación runtime: ambos contratos
quedan expresables por `Closed` para el siguiente vertical.

## Validación

Se ejecutaron:

```text
cargo test --workspace
cargo fmt --all --check
cargo clippy --workspace --all-targets -- -D warnings
git diff --check
bash compiler-next/tests/run-differential.sh
```
