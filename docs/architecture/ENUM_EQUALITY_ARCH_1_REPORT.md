# ENUM-EQUALITY-ARCH-1 — reporte de diseño

Estado: **ARQUITECTURA CERRADA; SIN IMPLEMENTACIÓN**, 2026-09-21.

Documento normativo:
[ENUM_EQUALITY_ARCH_1](ENUM_EQUALITY_ARCH_1.md).

## Resultado

Se cerró igualdad nominal `==`/`!=` para enums payload-free sin modificar
código, tests ni superficie source. Dos operands son comparables sólo si tienen
el mismo tipo enum canónico, la misma declaración nominal y ninguna variante
de esa declaración tiene payload. La relación compara únicamente la variante
activa; `!=` es su negación.

No existe comparación por layout, nombre, discriminante entre declaraciones o
representación integer. No se agregan casts ni coercions. Dos enums con
`EnumId` diferentes fallan aunque sean físicamente idénticos.

## Generics y payloads

Para enums generic se adoptó la frontera estricta solicitada: además del mismo
`EnumId`, ambos operands deben tener exactamente el mismo `TypeId` de instancia.
`Box<int>` puede compararse con `Box<int>` si la declaración completa es
payload-free; `Box<int>` y `Box<double>` no. Que el parámetro generic no afecte
al layout no relaja identidad.

La propiedad payload-free se consulta en `EnumInfo` y exige que todas las
listas de payload estén vacías. No se deduce de Copy, tamaño, alignment o
instancia. Todo enum con al menos un payload sigue fuera de V1. Un futuro
vertical requerirá comparación de variante, igualdad recursiva de payloads,
una capability/constraint de equality y reglas explícitas de ownership,
borrows, short-circuit y cleanup.

## Frontera IR y backend

HIR conserva `Binary { Equal | NotEqual }`; no se necesita un nodo nuevo porque
cada operand ya porta su `TypeId` canónico. HIR verification amplía su contrato
de equality para admitir la familia enum payload-free, además de bool y
numéricos.

HIR → MIR y MIR → SSA conservan la operación y el tipo enum exacto de ambos
operands. Los verificadores MIR y SSA deben consultar también `EnumInfo` y
rechazar diferencias de declaración/instancia, payloads, resultado no bool o
traps. No se añade un `EnumId` redundante: `TypeData::Enum`/
`EnumInstance` es la única provenance nominal.

Sólo tras SSA verificado LLVM extrae o carga el tag canónico de cada operand y
emite `icmp eq`/`icmp ne`. No se compara el aggregate completo ni padding, no se
usa `memcmp` y no se expone una conversión enum → int. Layout, ABI, mangling,
drop glue y calling convention permanecen intactos.

## Nullable y diagnostics

`Status? == Status?` continúa fuera de NULLABLE-V1. Las formas contra `null`
siguen bajando por `NullableIsNull` y no pasan por enum equality.

Se reserva la familia source-facing:

- `E0470`: enums nominalmente distintos;
- `E0471`: igualdad de enum payload-bearing todavía no soportada;
- `E0472`: operands incompatibles, incluida distinta instancia generic.

Los errors source deben ocurrir antes de publicar HIR. `E0348`, `E0300` y
`E0400` quedan exclusivamente como defensas de corrupción HIR, MIR y SSA. El
caso válido que motivó el milestone ya no podrá terminar en
`HIR binary invalid` cuando se implemente V1.

## Qualification cerrada

La matriz obliga a cubrir misma/diferente variante, `!=`, locals, parámetros,
returns y conditions; enum generic payload-free; nominal mismatch; rechazo de
payload enums; interacción nullable; aliases/imports; corrupción independiente
de HIR/MIR/SSA; y ejecución O0/O2.

También se exige la fixture exacta mínima de `Status.Ok` encontrada en el port
y un escenario con `Results.RootStatus`/`Results.IntegrationStatus` de
`examples/numerical_methods`, para cubrir qualification entre packages. Este
milestone no reemplaza todavía sus helpers basados en `match`.

## Validación del milestone

- Se crearon únicamente el documento normativo y este reporte.
- No se modificó lexer, parser, AST, checker, HIR, MIR, SSA, backend, runtime,
  examples ni tests.
- Se preservaron los cambios preexistentes del worktree.
- Se cerraron semántica, identidad generic, payload gate, representación IR,
  verificación, lowering, ABI, diagnostics y qualification.
- No quedan decisiones abiertas para implementar **ENUM-EQUALITY-V1**.
