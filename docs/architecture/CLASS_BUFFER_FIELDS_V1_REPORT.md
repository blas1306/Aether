# CLASS-BUFFER-FIELDS-V1 — reporte de implementación

Estado: **CLOSED**, 2026-10-19. Qualification local completa en verde.

Autoridad normativa:
[CLASS-BUFFER-FIELDS-ARCH-1](CLASS_BUFFER_FIELDS_ARCH_1.md) y
[AETHER-V1-SEMANTIC-CONTRACT](AETHER_V1_SEMANTIC_CONTRACT.md).

## Resultado

Los fields privados de class admiten `Buffer<E>` mediante la misma autoridad
central `is_admitted_buffer_element(E)` que un Buffer ordinario. Se eliminaron
las dos excepciones productivas a `int` de resolución HIR y verificación de
metadata. No se agregó allowlist nominal, por package ni graphics.

La qualification cubre `int`, `uint8`, `float32`, `float64`, `bool`, `char`,
structs Copy simples/anidados, enums Copy con y sin payload e instancias
concretas de aggregates genéricos. Continúan rechazados public Buffer fields,
owners o needs-drop anidados, string, class handles, function-containing
storage, classes genéricas, extracción/move, borrows, View/ViewMut y acceso
privado externo.

## Storage place

HIR, MIR y SSA conservan una raíz cerrada `ClassField` con receiver, FieldId,
tipo exacto, mutabilidad y estado initialized. Las proyecciones ordinarias
`Index` y `Field` se aplican después. Los tres verificadores rechazan receiver,
FieldId, tipo, mutabilidad, initialization o proyección corruptos. Borrow nunca
acepta esta raíz.

LLVM calcula el slot mediante el offset verificado del field, carga el
descriptor `{ptr, usize}` sólo como dato para el bounds check y calcula la
dirección con el layout concreto de `E`. Read/write indexado no crea ni consume
token Buffer. Replacement y final release continúan usando el drop glue
concreto existente.

## Lifecycle y representación

- descriptor Buffer inline, 16 bytes/alignment 8 en Linux x86-64;
- sin boxing, vtable, reflection, tag o dispatch runtime por `E`;
- zero-length conserva una allocation/backing owner real;
- replacement evalúa RHS antes del commit, instala el nuevo descriptor y
  destruye el anterior exactamente una vez;
- constructor unwind usa la receta y el estado por FieldId existentes;
- herencia destruye derived antes de base mediante la receta vigente.

Los fixtures nativos O0/O2 verifican indexing, nested projection, zero-length,
aliases, múltiples replacements, herencia, unwind antes/después del field y RHS
de replacement que lanza dejando intacto el owner anterior. Los contadores
comprueban object alloc/free, backing alloc/free y final Buffer field drop.

## Qualification

Fixture dedicado:
`compiler-next/crates/aether-driver/tests/class_buffer_fields_v1.rs`.

Checks ejecutados al cierre:

- `cargo test -p aether-driver --test class_buffer_fields_v1`;
- `cargo test --workspace`;
- `cargo fmt --all --check`;
- `cargo clippy --workspace --all-targets -- -D warnings`;
- `bash compiler-next/tests/run-differential.sh`;
- `git diff --check`.

GRAPHICS-FOUNDATION-V1 no fue modificado productivamente.
