# FORMAT-V2 — explicit fixed/scientific float formatting

Estado: **CLOSED**, 2026-11-21, para el target bootstrap Linux x86-64 de
`compiler-next`.

## Resultado

`std.Format` publica las cuatro operaciones reservadas por FORMAT-ARCH-1:

```aether
string std.Format.fixed(float32 value, usize fractionalDigits);
string std.Format.fixed(float64 value, usize fractionalDigits);
string std.Format.scientific(float32 value, usize fractionalDigits);
string std.Format.scientific(float64 value, usize fractionalDigits);
```

Las operaciones se importan explícitamente con `import std.Format`, funcionan
desde la unidad de entrada y desde módulos importados, retornan un `string`
owning fresh y no modifican `str(float32)` ni `str(float64)`. No se integró esta
capacidad en Plots, Graphics, SVG ni interpolación.

El catálogo OAL materializa `std.Format` sólo cuando existe el grant de import.
El backend identifica sus firmas por identidad canónica de package toolchain,
nombre y tipos, y sustituye los cuerpos bootstrap por wrappers privados. Los
helpers y la dependencia decimal de precisión se emiten sólo si una de las
cuatro funciones es reachable.

## Semántica

`fixed(value, n)` emite exactamente `n` cifras después del punto y omite el
punto para `n == 0`. `scientific(value, n)` emite una mantisa normalizada con
un dígito antes del punto, exactamente `n` cifras posteriores y un exponente
`e`, signo obligatorio y sin ceros iniciales. Ambos formatos redondean el valor
IEEE binario exacto con nearest, ties-to-even. El carry puede ampliar la parte
entera fixed o renormalizar la mantisa y el exponente scientific.

El signo se conserva para todo valor finito negativo, incluido un valor que
redondea a cero. `+0` y `-0` producen respectivamente `0`/`-0`, con el punto,
ceros y exponente pedidos por cada estilo. Los valores especiales usan siempre
`NaN`, `Inf` y `-Inf`; no agregan punto, cifras ni exponente y no dependen de
`fractionalDigits`.

La conversión es independiente del locale y del rounding mode ambiental. La
qualification cambia el proceso a `FE_UPWARD` antes de ejecutar los mismos
casos ties/carry y obtiene bytes idénticos.

## Motor decimal y rounding

FORMAT-V1 ya usa el motor decimal correctamente redondeado de
`std::to_chars` provisto por libstdc++ del toolchain calificado. FORMAT-V2
extiende esa misma frontera al overload con `chars_format` y `precision`; no
agrega un segundo algoritmo decimal.

El valor `float32` se ensancha exactamente a binary64 antes de esa frontera.
Ese ensanchamiento no cambia su valor matemático, por lo que el resultado de
rounding a cualquier quantum decimal es el mismo que para el binary32 original.
`float64` cruza la frontera sin transformación. No se usa una representación
shortest intermedia, casts truncantes, `+0.5`, `snprintf`, streams ni
operaciones floating que alteren el valor.

libstdc++ emite al menos dos cifras en exponentes scientific pequeños. El
runtime Aether retira exclusivamente esos ceros iniciales después de que el
motor termina el rounding; mantisa, carry y exponente numérico no se
recalculan. Así se conserva la convención normativa `e+0`, `e-2`, `e+308`.

La qualification incluye casos que diferencian explícitamente el rounding del
binary float exacto del rounding de su spelling shortest: binary64 `2.675`
produce `2.67` con dos cifras, y binary32 `2.65` produce `2.7` con una cifra.

## Overloads

La superficie reveló que el resolvedor admitía a la vez una coincidencia
`float32` exacta y su coerción widening a `float64`. Se agregó ranking por
cantidad de coerciones de argumentos/resultado entre candidatos ya viables.
Una coincidencia exacta gana frente a una que inserta widening; empates reales
continúan diagnosticándose como `E0461`. Las suites de contextual overloads y
el workspace completo califican la corrección.

## Tamaño, allocation y ownership

Antes de asignar se comprueba que la precisión cabe en el parámetro `int` del
ABI `to_chars` calificado. El límite de recursos del target es por tanto
`i32::MAX` cifras fraccionarias. Una precisión mayor termina por el trap
estructurado `AllocationSizeOverflow`, antes de truncar, asignar o tocar el
valor. Los valores especiales se clasifican primero porque su salida no crece
con la precisión.

Las cotas de buffer incluyen signo, máximo de 309 cifras enteras binary64,
punto, precisión y exponente de hasta tres cifras. Todas las sumas variables
usan `llvm.uadd.with.overflow`. El buffer temporal usa el allocator calificado
y se libera en éxito y ante un error de conversión. El resultado se publica con
longitud exacta y contratos ordinarios de `string`; sus drops normales y de
unwind siguen el pipeline existente. Allocation failure conserva el trap
`AllocationFailure`. No se modifica el argumento.

## Qualification numérica e integración

`crates/aether-driver/tests/format_v2.rs` agrega vectores byte-exact congelados
desde una referencia independiente basada en la reconstrucción IEEE exacta y
el formatter correctamente redondeado de Python; el runtime bajo prueba nunca
actúa como su propio oráculo. Cubre:

- ties-to-even positivos y negativos, precision cero, carry y ceros finales;
- signo, `+0`, `-0`, `NaN`, `Inf` y `-Inf`;
- binary32 y binary64, incluida selección exacta del overload binary32;
- mínimos subnormales, mínimos normales, máximos finitos y exponentes
  `-324`, `-308`, `+38` y `+308`;
- precisión válida alta y precisión extrema rechazada antes de allocation;
- casos binary-exact distintos del rounding de un spelling shortest;
- `FE_UPWARD`, imports directos, alias de package implícito, otro módulo,
  reachability y ownership;
- outputs idénticos en O0 y O2;
- separación de `str(float*)` y ausencia de regresión de FORMAT-V1 y
  `std.Text.parseDouble`.

Las suites focales ejecutadas fueron FORMAT-V1, FORMAT-V2, numeric parsing,
contextual overloads y module std: 35 tests, 0 fallos. Las cuatro suites de
Plots también pasaron como parte del workspace sin cambios de fuentes ni
goldens.

## Gates

Ejecutados desde `compiler-next` con `TMPDIR=/tmp`:

| Gate | Resultado |
| --- | --- |
| `cargo check --workspace` | PASS |
| `cargo test --workspace -j 1` | PASS, 0 fallos; el test largo de registry terminó en 749.84 s |
| `cargo fmt --all --check` | PASS |
| `cargo clippy --workspace --all-targets -j 1` | PASS; 10 warnings preexistentes, ninguno en FORMAT-V2 |
| `git diff --check` | PASS |

## Archivos modificados

- `compiler-next/crates/aether-driver/src/lib.rs`: publicación toolchain de
  `std.Format`.
- `compiler-next/crates/aether-frontend/src/hir.rs`: preferencia del overload
  viable con menos coerciones.
- `compiler-next/crates/aether-backend-llvm/src/lib.rs`: reachability,
  materialización y emisión condicional del runtime FORMAT-V2.
- `compiler-next/crates/aether-backend-llvm/src/format.rs`: wrappers,
  conversión decimal, tamaño checked, normalización científica y publicación
  owning.
- `compiler-next/crates/aether-driver/tests/format_v2.rs`: qualification
  numérica, O0/O2, módulos, rounding mode y límites.
- `docs/architecture/FORMAT_V2_REPORT.md`: este reporte.

Se preservaron sin cambios los reportes no versionados preexistentes bajo
`docs/reports/`.

## Limitaciones

El target bootstrap continúa dependiendo del ABI libstdc++ calificado, igual
que FORMAT-V1. Portar el compilador requiere volver a calificar o reemplazar
esa frontera decimal. La precisión pública es `usize`, pero el target rechaza
valores superiores a `i32::MAX` por el límite del overload `to_chars` usado;
nunca los trunca silenciosamente.

No se implementan width, padding, grouping, otras bases, formato de enteros,
specifier syntax dentro de interpolación ni policy contextual de ticks. Esas
capacidades permanecen fuera de FORMAT-V2.
