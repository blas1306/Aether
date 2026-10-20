# TEXT-UTF8-BUILDER-ARCH-1 — reporte de diseño

Estado: **CLOSED**, 2026-10-19.

Documento normativo:
[TEXT-UTF8-BUILDER-ARCH-1](TEXT_UTF8_BUILDER_ARCH_1.md).

## Resultado

Se cerró la primitive pública mínima de `std.Text` para materializar un string
desde bytes dinámicos:

```aether
public class InvalidUtf8Exception : Exception {
    public init() {}
}

public string fromUtf8(ref Buffer<uint8> bytes, usize length);
```

`length` selecciona exactamente `[0,length)`. La función comprueba primero que
el prefijo cabe, no consume ni modifica el Buffer, ignora cualquier byte
posterior y retorna un owner string independiente. Mutar o destruir el Buffer
después no afecta el resultado.

`length == 0` usa el singleton canónico sin allocation. Un éxito no vacío hace
exactamente una allocation string y una copia. No se promete zero-copy.

## UTF-8 y errores

La validación es estricta y preserva bytes. Acepta Unicode scalar values UTF-8
canónicos, incluidos multibyte, combining marks, emoji, controles válidos y
U+0000. Rechaza continuation aislada, truncados, overlongs, surrogates y valores
mayores que U+10FFFF. No normaliza ni sustituye con U+FFFD.

Los fallos quedan separados:

- `length > buffer length`: trap `IndexOutOfBounds`;
- prefijo UTF-8 inválido: `std.Text.InvalidUtf8Exception` capturable;
- overflow de tamaño, OOM o corrupción: traps globales vigentes.

La exception existente de IO no se reutiliza porque deriva de `IOException` y
clasifica una operación IO; Process posee otra exception igualmente específica
de su frontera. `std.Text` no adquiere dependencia hacia esos packages ni hacia
graphics.

## Complejidad, atomicidad y allocations

La implementación valida todo el prefijo antes de reservar el resultado. Puede
hacer dos pasadas O(n): validación y copy/publication. Usa O(1) auxiliar y un
backing final O(n). Bounds, UTF-8 inválido y allocation failure nunca publican
un string parcial.

En el bootstrap auditado, el backing no vacío ocupa exactamente
`length + 25` bytes (header privado de 24, payload y cero auxiliar), alineado a
8. Es un gate de la implementación actual, no ABI pública. La ruta vacía asigna
cero; la válida no vacía, una; la inválida, cero strings y la class exception
ordinaria necesaria para el throw.

Se prohíben concatenación incremental, strings por byte, listas de fragments
con concat repetida, allocations por byte y cualquier recorrido O(n²).

## Builder evaluado

No entra `TextBuilder`. Aunque centralizaría growth geométrico, exige decidir
constructors, capacidad, estado post-finish, append después de sellado y si sus
bytes deben ser UTF-8 válido incrementalmente. La primitive elegida es necesaria
de todos modos y ya permite a serializers con Buffer propio terminar en O(n).

Un builder posterior puede mantener `Buffer<uint8>` y logical length privados,
hacer append amortized O(total) y llamar conceptualmente `fromUtf8` en un
`finish()` one-shot O(total). No se reservó hoy esa API.

## Frontera de implementación

La auditoría encontró infraestructura general ya existente:

- `aether_string_allocate`/`aether_string_from_buffer` crean un owner exacto,
  escriben el terminador privado y manejan el singleton vacío;
- el runtime Process contiene un validador UTF-8 estricto correcto, pero bajo
  un nombre accidentalmente específico.

TEXT-UTF8-BUILDER-V1 debe extraer un helper runtime general que reciba data,
buffer length y prefix length, haga bounds + validación y retorne status o un
owner. El adapter STD traduce sólo el status inválido a la exception. No se
expone raw pointer ni constructor unchecked y no hay FFI, allowlist o helper
SVG.

`fromUtf8` baja como call directa ordinaria a la identidad canónica toolchain,
no como `TextOp`: puede lanzar y debe conservar el exceptional successor,
borrows y cleanup ordinarios en HIR/MIR/SSA. El backend selecciona el adapter
por identidad, no por spelling. Reachability evita emitir helper y descriptor
si la función no se usa.

## Qualification requerida

El vertical propuesto `TEXT-UTF8-BUILDER-V1` debe agregar
`text_utf8_builder_v1.rs` y ejecutar O0/O2. Debe cubrir vacío, ASCII,
2/3/4-byte, extremos, emoji, combining marks, NUL, controles, trailing garbage,
payload grande e independencia tras mutar/drop del Buffer.

Los negativos incluyen bounds, continuations aisladas, truncados en cada
boundary, overlongs, surrogates, valores mayores que U+10FFFF y prefijos que
cortan una secuencia. Debe probar catch nominal, Buffer reusable, lifecycle,
balance de allocations y ausencia de string parcial.

El gate de recursos usa counters/IR además de payload scaling: bytes procesados
lineales, una allocation string, cero concat y cero allocations por byte. Los
gates source/IR excluyen graphics, consumer allowlists, FFI, raw constructors y
`TextOp::FromUtf8`. La qualification final incluye regresiones de Text, strings,
format/interpolation, Buffer, ownership/drop, exceptions, Process/IO y workspace,
más `fmt`, `clippy`, differential y `git diff --check`.

## Secuencia

La arquitectura no está bloqueada. Queda autorizada esta secuencia:

```text
TEXT-UTF8-BUILDER-V1
GRAPHICS-SVG-BACKEND-V1
```

No se modificó source productivo.

CLOSED
