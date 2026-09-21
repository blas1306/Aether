# GENERIC-LOCAL-INFERENCE-V1 — implementation report

Estado: **IMPLEMENTADO**, 2026-09-21.

Autoridad normativa:

- [GENERIC_LOCAL_INFERENCE_ARCH_1.md](GENERIC_LOCAL_INFERENCE_ARCH_1.md)
- [GENERIC_LOCAL_INFERENCE_ARCH_1_REPORT.md](GENERIC_LOCAL_INFERENCE_ARCH_1_REPORT.md)

## Resultado

El frontend admite la omisión total de los argumentos del constructor generic
root exclusivamente en locals source con initializer:

```aether
QR qr = la.qr(a);       // RHS QR<double>; local QR<double>
List values = make();   // RHS List<int>; local List<int>
Pair pair = pairOf();   // RHS Pair<int, string>; local idéntico
```

El tipo source se clasifica temporalmente como `Exact(TypeId)` o
`InferRoot(LocalTypePattern)`. El patrón conserva identidad nominal o
intrínseca, aridad, nullable y provenance source; no se interna en `TypeArena`
ni se publica en HIR.

Para `InferRoot`, el initializer se tipa con `expected = None`. Después se
exige la misma familia exacta, la misma forma nullable y una aplicación completa.
El binding adopta directamente el `TypeId` canónico del RHS. No se reconstruye
el tipo y no se ejecutan coercions, nullable injection, borrow adaptation,
upcasts ni selección de call por resultado.

## Cobertura cerrada

La implementación reconoce:

- structs y enums generic nominales, incluso con múltiples argumentos;
- `Buffer`, `Array`, `List`, `View`, `ViewMut`;
- `Matrix`, `MatrixView`, `MatrixViewMut`;
- `Vector`, `VectorView`, `VectorViewMut`, preservando orientación;
- locals `const`;
- aplicaciones simbólicas completas como `Box<T>` dentro de bodies generic;
- `Box? value = rhs` únicamente si el RHS ya es exactamente `Box<X>?`.

Continúan fuera de alcance `var`, argumentos parciales, `<>`, `_`, omissions
nested, references alrededor del constructor omitido, parámetros, returns,
fields, aliases y enum payloads. Esos contextos no crean raw generics.

## Diagnósticos

Se implementaron los diagnósticos reservados:

- `E0460`: familia nominal/intrínseca distinta;
- `E0461`: RHS escalar o no aplicación generic elegible;
- `E0462`: RHS sin tipo autónomo completo (`null` o resultado generic no
  determinado sin expected type);
- `E0463`: omission nested o debajo de reference/function type;
- `E0464`: shape nullable o aplicación canónica incompatible.

Lookup, imports, visibilidad, aridad explícita, constraints y admission del
elemento conservan sus diagnósticos preexistentes.

## Frontera IR e invariantes

HIR recibe sólo el tipo final adoptado y mantiene
`HirLocal.ty == initializer.ty`. Los verificadores HIR, MIR y SSA rechazan una
base nominal generic usada como tipo de valor y aplicaciones con aridad
incompleta. Los `GenericParam` legítimos sólo permanecen en HIR paramétrico;
MIR/SSA concretos conservan su rechazo existente de parámetros sin sustituir.

La qualification incluye corruption tests independientes en HIR, MIR y SSA.
La comparación explicit/inferred verifica la misma identidad semántica en los
dumps HIR/MIR/SSA (ignorando spans source) y LLVM idéntico en O0 y O2. El caso
usa un owner con `Buffer`, por lo que también atraviesa move, Drop y cleanup sin
una ruta especial para la inferencia.

## Qualification

La suite dedicada cubre:

- una y varias variables generic, struct y enum;
- todas las familias intrínsecas V1 y orientación de vector;
- local mutable y `const`;
- body generic que adopta `Box<T>`;
- nullable exacto y rechazo de nullable injection;
- familia errónea, RHS escalar, `null` y call result indeterminado;
- omissions nested, partial, references y contextos no locales;
- constraints/admission por la ruta ordinaria del RHS;
- ownership, Drop y equivalencia de IR explicit/inferred;
- verificadores fail-closed frente a tipos generic incompletos.

Validación ejecutada al cerrar el milestone:

```text
cargo test --workspace
cargo fmt --all --check
cargo clippy --workspace --all-targets -- -D warnings
git diff --check
bash compiler-next/tests/run-differential.sh
```

