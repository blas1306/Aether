# GRAPHICS-FOUNDATION-V1 — reporte de implementación

Estado: **CLOSED**, 2026-10-19.

Autoridad normativa:

- [GRAPHICS-FOUNDATION-ARCH-1](GRAPHICS_FOUNDATION_ARCH_1.md);
- [GRAPHICS-FOUNDATION-ARCH-1-REPORT](GRAPHICS_FOUNDATION_ARCH_1_REPORT.md);
- [CLASS-BUFFER-FIELDS-V1-REPORT](CLASS_BUFFER_FIELDS_V1_REPORT.md);
- [AETHER-V1-SEMANTIC-CONTRACT](AETHER_V1_SEMANTIC_CONTRACT.md);
- [MODULE-STD-ARCH-1](MODULE_STD_ARCH_1.md);
- [PACKAGE-MANAGER-ARCH-1](PACKAGE_MANAGER_ARCH_1.md);
- [TEXT-BYTE-ACCESS-ARCH-1](TEXT_BYTE_ACCESS_ARCH_1.md).

## Resultado

Se implementó la OAL pública `graphics` en `graphics/src/lib.ae` sin cambios en
compiler, runtime, Core ni std. `CLASS-BUFFER-FIELDS-V1` permite expresar
directamente la representación cerrada: `SceneBuilder` mutable y one-shot,
`Scene` inmutable y las cinco arenas contiguas exactas:

- `Buffer<Command>`;
- `Buffer<Point>`;
- `Buffer<PathVerb>`;
- `Buffer<TextRecord>`;
- `Buffer<uint8>`.

No hay `List`, arrays paralelos, nodos por primitiva, aliases mutables ni un
wrapper alternativo de storage. La pila de estado del builder es un
`Buffer<StateSnapshot>` privado separado y no forma parte de `Scene`.

La superficie conserva `float64` como escalar gráfico, color RGBA por bytes con
alpha straight, `Transform2D` especializado, painter order, paths
`MoveTo`/`LineTo`/`CubicTo`/`Close`, texto UTF-8 y una frontera de backend
estática. No se implementaron SVG, Plots, raster, window/UI/GPU,
MathTeX ni notebooks.

## Semántica implementada

### Validación y atomicidad

Los constructores y operaciones validan geometría y estilo antes de mutar las
arenas: finitud de coordenadas y transforms, dimensiones no negativas,
diámetro y ancho de stroke estrictamente positivos, miter limit al menos uno,
tamaño de fuente positivo y spans estructuralmente válidos. También se calificaron NaN,
infinidades, valores finitos extremos, viewports degenerados y transforms
singulares.

Los errores de estado cubren underflow de `popState`, primitivas incrementales
solapadas o incompletas, paths sin subpath abierto, `finish()` con estado no
balanceado y todo uso posterior al sellado. Los rechazos probados son
transaccionales: no dejan comandos ni payloads parciales.

### Estado, clipping y transform

`pushState` y `popState` guardan y restauran transform y clip explícitos. La
composición es `current * local`; el clipping se registra como estado explícito
y se intersecta con el clip vigente. Las operaciones correspondientes producen
comandos en painter order y no dependen de callbacks ni dispatch dinámico.

### Primitivas y arenas

Se implementaron puntos, líneas y rectángulos; polyline tanto por copia desde
`Array<Point>` como incremental; y path incremental con múltiples subpaths.
Todas las arenas crecen geométricamente y preservan sus spans al realojarse.
La qualification fuerza crecimiento en comandos, puntos, verbos, registros de
texto, bytes y pila de estado.

Las arenas arrancan con longitud/capacidad lógica cero y adquieren capacidad al
primer append. Conforme a la semántica ya calificada por
`CLASS-BUFFER-FIELDS-V1`, un `Buffer(0, fill)` sigue siendo un owner real de un
backing de longitud cero; el gate de recursos contabiliza también esos
backings, sin reinterpretarlos como una representación distinta.

### Texto y ownership

`drawText` copia exactamente los bytes UTF-8 del contenido, incluidos espacios,
NUL y saltos de línea, y copia también los bytes de `FontFamily.Named`. El
`TextRecord` conserva spans sobre la arena `uint8`, no referencias a los
`string` de origen. Se probaron lifetimes en los que texto y font salen de
scope antes de consumir la escena.

`finish()` copia cada arena a un `Buffer<E>` de longitud exacta, construye una
escena que posee los cinco backings, invalida el builder y libera su storage de
trabajo. Los accessors de `Scene` son exclusivamente read-only; no exponen los
buffers ni referencias mutables.

El lenguaje hace que un initializer privado sea accesible sólo desde la misma
class. Para mantener construcción interna sin abrirla a consumidores,
`Scene.init` exige el capability nominal interno `SceneConstruction`. Ese tipo
no es resoluble fuera del package (`E0222` en el gate negativo), es `Copy`, no
asigna y no participa en la representación almacenada de `Scene`.

## Qualification

Se añadió `compiler-next/crates/aether-driver/tests/graphics_foundation_v1.rs`
con ocho gates dedicados:

1. consumidor público real en O0 y O2;
2. compilación separada para inspección de IR;
3. constructor de `Scene` inaccesible desde consumidores;
4. rechazos geométricos, de estilo, estado e incrementalidad transaccionales;
5. extremos finitos, viewports cero, transform singular y lifetimes de texto;
6. todas las variantes de estilo/texto y crecimiento de todas las arenas en
   O0/O2;
7. representación, frontera de backend y dispatch estático en source/HIR/MIR/
   SSA;
8. allocations, ARC y liberación exacta de recursos en O0/O2.

El gate de representación comprueba exactamente cinco fields `Buffer` en
`Scene`, ausencia de mutación pública, presencia de los class fields en IR y
ausencia de `InterfaceCall`, callbacks, vtables o leakage de SVG/raster/window/
GPU/backend. El gate de recursos observa el mismo número de allocations de heap
para una y cuatro primitivas (`20` en ambos casos), dos objetos y once drops de
backings: no existe allocation por primitiva y todos los owners se liberan. Un
caso adicional hace no vacías las cinco arenas finales y verifica en O0/O2 que
allocations/frees y creación/destrucción queden exactamente balanceados.

El consumidor independiente `graphics/tests/consumer` cubre painter order,
estado, transform, clip, punto/línea/rectángulo, ambas formas de polyline, path
multi-subpath, copia UTF-8 exacta, font nombrada, sellado y accessors read-only.

## Gates ejecutados

Todos finalizaron en verde:

```text
cargo run -q -p aether-cli -- check ../graphics
cargo run -q -p aether-cli -- build ../graphics
cargo run -q -p aether-cli -- check ../graphics/tests/consumer
cargo run -q -p aether-cli -- run ../graphics/tests/consumer -O0
cargo run -q -p aether-cli -- run ../graphics/tests/consumer -O2
cargo test --workspace
cargo fmt --all --check
cargo clippy --workspace --all-targets -- -D warnings
bash compiler-next/tests/run-differential.sh
git diff --check
```

Los comandos Cargo se ejecutaron desde `compiler-next`; los del package usaron
el CLI de ese workspace. El diferencial cerró `checked=21 failures=0`.

## Cierre

`GRAPHICS-FOUNDATION-V1` queda **CLOSED**. El package foundation queda listo
para backends posteriores a través de la frontera estática definida, sin haber
adelantado ninguno de ellos ni rediseñado graphics.
