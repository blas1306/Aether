# ENUM-EQUALITY-V1 — reporte de implementación

Estado: **IMPLEMENTADO Y QUALIFIED**, 2026-09-21.

Autoridad normativa:

- [ENUM_EQUALITY_ARCH_1](ENUM_EQUALITY_ARCH_1.md)
- [ENUM_EQUALITY_ARCH_1_REPORT](ENUM_EQUALITY_ARCH_1_REPORT.md)

## Resultado

`compiler-next` admite `==` y `!=` entre dos valores del mismo tipo enum
canónico cuando todas las variantes de la declaración son payload-free. La
identidad es nominal y exacta: se comprueban tanto `EnumId` como `TypeId`, por
lo que `Box<int>` se compara con `Box<int>` pero no con `Box<double>`.

No se añadieron casts, coercions, conversión enum a integer, igualdad de
payloads, igualdad estructural, igualdad nullable general, capability `Eq` ni
operadores definidos por el usuario. Layout, ABI y mangling no cambiaron.

## Contrato compartido

El frontend expone `classify_enum_equality`, una clasificación cerrada que
distingue:

- admisión con `EnumId` y `TypeId` exactos;
- operands que no son ambos enum;
- declaraciones nominales distintas;
- instancias generic distintas;
- declaración con algún payload;
- metadata inválida o incompleta.

La propiedad payload-free se obtiene exclusivamente de
`EnumInfo::variants[*].payloads`. Source typing, HIR, MIR y SSA reutilizan esta
misma frontera; no se deriva comparabilidad desde Copy, tamaño o layout.

## Source y diagnostics

La ruta de binarios intercepta cualquier operand enum después de las reglas
especiales existentes para nullables y strings, pero antes de buscar un tipo
numérico común. Sólo publica `HirExprKind::Binary` con `Equal` o `NotEqual`
cuando la clasificación es admitida y produce `bool`.

Se implementaron:

- `E0470` para declaraciones enum nominalmente distintas;
- `E0471` para una declaración con cualquier variante con payload;
- `E0472` para distinta instancia generic, enum/no-enum y operadores distintos
  de `==`/`!=`.

Los rechazos source ya no alcanzan `E0348`. Las comparaciones con `null`
continúan usando `NullableIsNull`; `Status? == Status?` conserva el rechazo de
NULLABLE-V1.

## HIR, MIR y SSA

HIR mantiene `Binary { Equal | NotEqual }`. La sustitución generic conserva el
opcode y sustituye ambos operands al mismo `TypeId` canónico.

HIR verification admite enum equality sólo tras la clasificación compartida.
MIR y SSA conservan los tipos exactos de los operands y vuelven a exigir:

- mismo tipo de operand;
- enum nominal y aplicación exactos;
- declaración payload-free;
- resultado `bool`;
- `trap` y `secondary_trap` ausentes.

Las pruebas de corrupción cubren cambio de tipo nominal o instancia, payload,
opcode, resultado y traps. Fallan en HIR/MIR/SSA con sus diagnostics internos y
no llegan al backend.

## Backend LLVM

Después de SSA verificado, LLVM extrae el field `0` (`i32`) de cada aggregate
enum con `extractvalue` y emite `icmp eq` o `icmp ne` sobre esos tags. No emite
comparación del aggregate, `memcmp`, lectura de padding ni reconstrucción de
nominalidad desde el tipo LLVM.

## Qualification

La suite `enum_equality_v1` cubre:

- misma variante, variante distinta y `!=`;
- literals/constructors, aliases, locals, parámetros, retorno `bool` e `if`;
- `Box<T>` payload-free en body generic y `Box<int>` concreto;
- mismatch nominal, mismatch de instancia generic y enum frente a
  integer/bool/struct;
- ordering, aritmética y payload enums;
- interacción nullable;
- imports, packages y variantes qualified;
- conservación del `TypeId` en dumps HIR/MIR/SSA;
- lowering LLVM por tag sin `memcmp`;
- ejecución nativa O0 y O2;
- reproducer mínimo exacto de `Status`.

`examples/numerical_methods/Results.ae` ya usa comparaciones directas para
`RootStatus` e `IntegrationStatus`; se eliminaron los seis `match` usados como
workaround. La qualification compila y ejecuta el programa multi-package
completo en O0/O2 y exige exactamente 18 líneas, todas terminadas en `true`.

## Validación final

Pasaron sin errores:

```text
cargo test --workspace
cargo fmt --all --check
cargo clippy --workspace --all-targets -- -D warnings
git diff --check
bash compiler-next/tests/run-differential.sh
```

El diferencial conserva todos los casos equivalentes y los cambios/rechazos
intencionales previamente registrados.
