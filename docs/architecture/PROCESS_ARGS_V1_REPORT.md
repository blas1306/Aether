# PROCESS-ARGS-V1 — reporte de implementación y qualification

Estado: **IMPLEMENTADO Y CALIFICADO EN LINUX/POSIX**, 2026-09-22.

Autoridad normativa:
[PROCESS_ARGS_ARCH_1](PROCESS_ARGS_ARCH_1.md) y
[PROCESS_ARGS_ARCH_1_REPORT](PROCESS_ARGS_ARCH_1_REPORT.md).

## Resultado

Se implementó la superficie pública cerrada:

```aether
package std.Process;

class InvalidArgumentEncodingException : Exception {
}

Array<string> args();
```

El package es de origin Toolchain, requiere `import std.Process`, admite alias
de import ordinario y no agrega nombres a Core/prelude. No se agregó `System`,
una firma `main(argc, argv)`, `ProcessOp`, argumentos raw ni ninguna otra API de
proceso.

`std.Process.args()` excluye siempre `argv[0]`. `argc == 0` y `argc == 1`
producen un `Array<string>` vacío. El count, orden y bytes UTF-8 de los
argumentos restantes se preservan sin interpretar quoting, globbing, variables
o paths.

## Frontera POSIX y lifecycle

La identidad canónica `std::Process::args` sigue bajando como una call directa
ordinaria. Sólo cuando esa función es alcanzable, el backend emite un wrapper
host `main(i32 argc, ptr argv)` y el runtime privado Process. Un import no usado
conserva `main()` y no emite símbolos `aether_process_*`, conversor ni descriptor
de la exception.

El wrapper alcanzable ejecuta:

```text
aether_process_snapshot_init(argc, argv)
Aether main()
aether_process_snapshot_dispose()
audit de owners Aether
return status
```

La ruta root de exception no capturada reporta la exception y también destruye
el snapshot antes de retornar el status reservado. Init valida count/vector,
usa exclusivamente slots `[1, argc)`, mide cada C string una vez y copia bytes y
longitud a entries privadas. El snapshot usa allocations host separadas de los
contadores de owners Aether y queda sin mutaciones hasta dispose.

Counts negativos, vector ausente con count positivo, elementos requeridos nulos,
overflow y OOM terminan en trap. No se consulta `argv[argc]`.

## Conversión y ownership

Cada call a `args()` crea un backing `Array<string>` nuevo mediante el glue
normal de collections. Después recorre el snapshot de izquierda a derecha:

1. valida el argumento completo como UTF-8 estricto;
2. crea un `string` Aether owning copiando los bytes;
3. publica el owner únicamente en su slot inicializado.

El validador acepta UTF-8 canónico de una a cuatro unidades y rechaza
continuations aisladas, overlongs, truncados, encodings de surrogate y scalars
mayores que U+10FFFF. No consulta locale ni produce U+FFFD.

Si falla el elemento `i`, el helper libera en orden inverso los strings de
`[0, i)`, libera el backing no publicado y retorna un status privado. El adapter
Aether crea y lanza entonces `std.Process.InvalidArgumentEncodingException`.
OOM y overflow permanecen traps.

El resultado exitoso es el `Array<string>` fundamental, non-Copy, relocatable,
storable y needs-drop. Moves, retornos, iteración, reemplazo de elemento, early
return y unwind usan los protocolos existentes. Una mutación afecta sólo ese
backing; una llamada anterior, el snapshot y llamadas posteriores permanecen
independientes.

## IR y verificación

No se agregó ninguna operación HIR/MIR/SSA. Los tres niveles conservan una call
directa con retorno exacto `Array<string>` y obligación owning. Las calls
ordinarias son conservadoramente potencialmente unwinding; cuando hay cleanup
vivo, MIR y SSA requieren el successor excepcional existente. La identidad
Toolchain se materializa recién en backend como frontera que lee estado externo
y puede asignar y lanzar.

La qualification corrompe independientemente en MIR y SSA:

- tipo de retorno del callee;
- tipo/ownership del resultado;
- Drop faltante y Drop duplicado;
- arista unwind ausente.

Los verificadores rechazan todos esos casos. Los dumps HIR/MIR/SSA comprueban
además que no aparecen `ProcessOp`, `argv`, snapshot ni pointer host. La única
representación source-facing continúa siendo `Array<string>`.

## Qualification nativa

La suite `process_args_v1` ejecuta en O0 y O2:

- cero, uno y varios argumentos;
- argumento vacío, espacios, `:`, tab y LF;
- UTF-8 multibyte, scalar combining sin normalización y emoji;
- argumento de 8192 bytes, orden y exclusión de `argv[0]`;
- texto parecido a glob sin reinterpretación;
- calls múltiples y mutación independiente;
- retorno/move, iteración, early return y Drop final;
- cleanup por exception posterior a una call exitosa;
- cleanup parcial con un argumento inválido intermedio;
- bytes POSIX reales inválidos mediante `OsStringExt`;
- continuation aislada, overlong, truncado, surrogate y > U+10FFFF;
- adapter inyectado con `argc == 0` y `argv == null`;
- exception nominal capturada y diagnóstico nominal no capturado;
- ausencia completa del runtime Process por import no usado.

El audit existente de allocations al salir hace trap ante leaks o double drops;
por ello las ejecuciones exitosas también califican balance exacto de owners.

## Expense Tracker

Se agregó `tests/modules/expense_tracker_process_args_v1/main.ae`. La fixture
comprueba y despacha exactamente:

```text
ledger.alpt add 42 12.5 food
ledger.alpt list
ledger.alpt summary
```

La rama `add` reutiliza `std.Text.parseInt` y `std.Text.parseDouble`. El estado es
in-memory y controlado por la fixture; no se implementa ni simula persistencia,
`writeTextAtomic` o `appendText`.

## Windows

Este vertical declara qualification únicamente para el target vigente
`x86_64-unknown-linux-gnu`. La API y la frontera privada dejan aislada la captura
host del materializador Aether, de modo que el port Windows puede reemplazar el
snapshot POSIX por entrada wide y conversión UTF-16 validada sin cambiar source,
HIR, MIR, SSA ni ABI de funciones Aether. No se agregó ni se usa narrow Windows
argv/code page. La conversión UTF-16 y ejecución wide quedan como gate del port,
no como soporte declarado por este reporte.

## Validación

Ejecutado en el workspace `compiler-next`:

```text
cargo test --workspace
  PASS (incluye 9 tests PROCESS-ARGS-V1 y fixtures nativas O0/O2)

cargo fmt --all --check
  PASS

cargo clippy --workspace --all-targets -- -D warnings
  PASS

git diff --check
  PASS

bash compiler-next/tests/run-differential.sh
  PASS: checked=21 failures=0
```

No se implementaron environment, cwd, spawn, signals, raw args, framework CLI,
`writeTextAtomic` ni `appendText`.
