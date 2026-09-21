# NUMERIC-PARSING-ARCH-1 — report

Estado: **DISEÑO CERRADO; NO IMPLEMENTADO**, 2026-09-21. Documento normativo:
[NUMERIC_PARSING_ARCH_1](NUMERIC_PARSING_ARCH_1.md).

## Resultado

Se cerró una superficie pública checked y nominal en `std.Text`:

```aether
enum IntParseResult {
    Value(int),
    Invalid,
    Overflow
}

enum DoubleParseResult {
    Value(double),
    Invalid,
    Overflow,
    Underflow
}

IntParseResult parseInt(ref string value);
DoubleParseResult parseDouble(ref string value);
```

`int` es el `int64` canónico y `double` es IEEE-754 binary64. Los resultados son
enums Copy sin allocation ni Drop. El string sólo se presta; no se retiene ni se
materializan substrings. No se agregó un `Result<T,E>` universal, parser generic,
exception, sentinel ni estado global.

## Gramáticas cerradas

`parseInt` acepta exactamente `[+-]?[0-9]+`, con consumo total. Leading zeros,
`+` y `-0` son válidos. Empty, signo aislado, whitespace, suffix, underscore,
radix, punto, byte NUL y caracteres no ASCII son `Invalid`. Ambos límites int64
son válidos y sus vecinos externos son `Overflow`.

`parseDouble` acepta un signo opcional, un significando decimal con al menos un
dígito total, punto opcional, y un exponente `e`/`E` opcional con signo y al
menos un dígito. Por ello admite `0`, `1.0`, `.5`, `5.`, `-1.25`, `+1.25`,
`1e3`, `1E3`, `1.2e-3` y `-0.0`. No admite whitespace, comma decimal, Unicode,
underscore, hexadecimal, `NaN`, `Inf` ni `Infinity`.

La syntax se valida completa antes de clasificar rango. Por eso una magnitud que
ya parece overflowing pero termina en `x` es `Invalid`, no `Overflow`.

## Semántica numérica

El entero se acumula checked contra un límite de magnitud distinto por signo;
el algoritmo nunca niega `int64.min`, desborda durante el parse ni depende de
wrapping/undefined behavior.

El decimal se convierte directamente a binary64 con nearest, ties-to-even, sin
depender del rounding mode ambiental. Un resultado normal o subnormal no cero es
`Value`. Un decimal que redondea a infinity es `Overflow`; uno matemáticamente
no nulo que redondea a signed zero es `Underflow`. Cero decimal exacto conserva
su signo y es `Value`, aun con un exponente extremo. Así, `1e9999` y `1e-9999`
se distinguen, y un subnormal representable no se considera fallo.

El motor futuro debe ser length-aware, locale-independent, O(N) y de workspace
bounded. Puede usar un algoritmo conocido con fallback exacto, pero no `strtod`,
`errno`, libc ambiental ni una conversión host con grammar diferente.

## Round-trip y especiales

Para todo `int`, `parseInt(str(x))` produce `Value(x)`. Para todo `double`
finito, incluidos signed zero y subnormales, `parseDouble(str(x))` recupera el
mismo patrón binary64 gracias al contrato shortest-round-trip de FORMAT-V1.

La excepción deliberada son NaN e infinities: FORMAT-V1 escribe `NaN`, `Inf` y
`-Inf`, pero NUMERIC-PARSING-V1 los clasifica `Invalid`. V1 es parsing decimal
checked, no una grammar de todos los estados IEEE ni de NaN payloads.

## Módulo y lowering futuro

Se eligió `std.Text`, no Core ni `std.Math`, porque la operación interpreta
bytes, grammar y policy textual. Exige import explícito y conserva identidades
nominales distintas para ambos resultados.

El bootstrap declaration-only puede agregar `ParseInt` y `ParseDouble` a
`TextOp` como puente interno. HIR/MIR/SSA deben verificar borrow, operand y enum
de retorno exactos; LLVM usa helpers privados length-aware que retornan status y
payload sólo en éxito. No se agrega syntax, member mágico de string ni ABI
público. Reachability debe mantener separados los motores int y double.

## Qualification requerida

NUMERIC-PARSING-V1 deberá cubrir O0/O2, límites y vecinos de int64, precedencia
de Invalid, todas las producciones/rechazos de ambas gramáticas, U+0000 y
no-ASCII. Para double deberá verificar bit de signed zero, normales,
subnormales, halfway ties, fronteras finito/infinity y subnormal/zero, exponentes
enormes, casos difíciles contra un oracle exacto y round-trip bit a bit de
`str(double)` finito.

También deberá cubrir import/alias/arity/tipos, match exhaustivo y Copy, borrow
de literal/lvalue/temporary, corrupción independiente de HIR/MIR/SSA,
reachability de helpers, locale/rounding ambiental, avance O(N), workspace
bounded y todas las suites de regresión de `compiler-next`.

Este milestone agregó solamente los dos documentos de arquitectura. No
implementó código, no agregó tests ejecutables y no cambió programas admitidos.
