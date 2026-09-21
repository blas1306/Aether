# TEXT-BYTE-ACCESS-ARCH-1 — report

Estado: **DISEÑO CERRADO; NO IMPLEMENTADO**, 2026-09-21. Documento normativo:
[TEXT_BYTE_ACCESS_ARCH_1](TEXT_BYTE_ACCESS_ARCH_1.md).

## Resultado

Se cerró una extensión pública mínima de `std.Text` para decodificar formatos
length-prefixed sin permitir strings UTF-8 inválidos:

```aether
uint8 byteAt(ref string value, usize offset);
bool isByteBoundary(ref string value, usize offset);
ByteSliceResult byteSlice(
    ref string value,
    usize start,
    usize endExclusive
);

enum ByteSliceResult {
    Slice(string),
    InvalidRange,
    OutOfBounds,
    InvalidBoundary
}
```

`byteAt` retorna el octeto unsigned exacto, incluidos `128...255`, sin
interpretación Unicode, allocation ni Alias. Acepta sólo `offset < byteLength`.
`isByteBoundary` acepta posiciones hasta el final inclusive y decide en O(1):
cero/final son fronteras y una posición interior lo es si su byte no tiene
prefijo de continuation `10`. Ambas consultas hacen trap
`TextByteOffsetOutOfBounds` si el caller viola bounds.

`byteSlice` está orientada al dato externo: clasifica de forma recuperable y
ordenada `InvalidRange`, `OutOfBounds` e `InvalidBoundary`. Sólo `Slice(string)`
publica un owner. Un rango vacío usa el singleton, el completo puede hacer Alias
y uno propio copia exactamente sus bytes una vez. Source válido más endpoints
en fronteras demuestra UTF-8 válido sin rescanning.

## Decisiones arquitectónicas

- Los offsets son `usize` y los rangos `[start,endExclusive)`. Componen
  directamente con `byteLength`; no se agrega `ByteOffset`.
- Se eligió end-exclusive frente a start+length para mantener rango invertido
  explícito y no introducir overflow oculto. El decoder prueba primero
  `n <= total - start`, por lo que `start + n` queda demostrado seguro.
- Se rechazó `TextByteCursor`: un `usize cursor` local ya da avance lineal y no
  abre storage borrowed, lifetimes, retain del source ni otro subsistema.
- No se agrega vista de bytes, `Bytes`, indexing/slicing sintáctico, buffer
  mutable ni capacidad de construir strings desde bytes arbitrarios.
- LF, CRLF, `:`, NUL y otros delimitadores dentro del payload no tienen trato
  especial: conocida la longitud, el decoder salta exactamente hasta el final.

## Runtime e IR

La implementación reutilizará las primitives privadas existentes
`textByteAt` y `copyUtf8ByteRange`. Boundary sólo requiere `byteLength`, fast
paths de extremos y un test del byte actual. La copia privada conserva checks
defensivos O(1), pero no revalida linealmente UTF-8.

No hay syntax ni operación ALPT1 en el compilador. En el bootstrap
declaration-only actual, tres variantes `TextOp` pueden servir de puente para
las identidades de `std.Text`; HIR/MIR/SSA preservan tipos, borrow, enum owner,
traps y Drop, y LLVM consume únicamente estados verificados. No se agrega un
`StringOp` público ni acceso sin `import std.Text`.

## Errores y complejidad

Las consultas primitivas tratan bounds como precondición de programación. El
slice trata orden, bounds y boundary como resultados esperables de framing
externo. No hay sentinel ni se captura/reinterpreta un trap privado.

`byteAt`, boundary y fallos de slice son O(1). Un slice propio cuesta O(R) y una
allocation; vacío/completo no copian. Un decoder con cursor monotónico es O(n)
y no usa substring scalar repetido, rescans desde cero ni concatenaciones.

## Qualification requerida

TEXT-BYTE-ACCESS-V1 deberá cubrir en O0/O2 ASCII, `éxito`, `λ`, emoji, todos
los bytes leading/continuation, inicio/final, slices vacíos/completos/propios,
rangos invertidos/out-of-bounds, ambos endpoints dentro de scalars y precedencia
de errores. También deberá ejecutar decoders length-prefixed y ALPT1-like con
múltiples fields, LF/CRLF/delimitadores dentro del payload, framing malformado,
avance lineal, lifecycle exacto y corrupción independiente de HIR/MIR/SSA.

Este milestone no implementó código ni cambió programas admitidos.
