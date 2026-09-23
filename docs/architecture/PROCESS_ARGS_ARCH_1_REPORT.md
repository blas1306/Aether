# PROCESS-ARGS-ARCH-1 — reporte de diseño

Estado: **ARQUITECTURA CERRADA; SIN IMPLEMENTACIÓN**, 2026-09-22.

Documento normativo:
[PROCESS-ARGS-ARCH-1](PROCESS_ARGS_ARCH_1.md).

## Resultado

Se diseñó la primera superficie pública de argumentos de proceso:

```aether
import std.Process;

Array<string> arguments = std.Process.args();
```

`args()` excluye `argv[0]`. Para
`./program ledger.alpt list` retorna conceptualmente
`{"ledger.alpt", "list"}`. Esto mantiene los argumentos de usuario separados
del nombre/path no portable del ejecutable, que puede ser relativo, inventado,
vacío o ausente. Sin argumentos de usuario retorna un Array vacío válido.

No se recupera el package legacy `System`, no se agrega nada a Core/prelude y
el import explícito sigue las reglas de MODULE-STD-V1.

## Tipo y ownership

Se eligió `Array<string>` en lugar de `List<string>` porque el tamaño es fijo y
conocido al entry. Es el Array fundamental existente: non-Copy, relocatable,
storable y needs-drop. Su longitud no cambia, aunque el caller puede reemplazar
un elemento de su copia sin afectar estado global.

Cada call exitosa crea un backing Array independiente y strings owners Aether.
No escapan pointers o borrows del host. Drop destruye los elementos y backing
mediante el lifecycle normal; unwind posterior hace el mismo cleanup. La
construcción es transaccional: un fallo en el elemento `i` destruye el prefijo
`[0,i)` antes de lanzar y nunca publica un Array parcial.

V1 copiará conservadoramente cada argumento. Una implementación futura puede
cachear strings inmutables y entregar Alias owners sólo si conserva el mismo
contenido, excepción, independencia de Array y Drop observable permitido.

## Encoding y fallos

POSIX entrega bytes sin promesa UTF-8. `args()` los valida estrictamente y
lanza `std.Process.InvalidArgumentEncodingException` ante cualquier secuencia
inválida. No usa locale ni replacement U+FFFD. El terminador NUL host no forma
parte del argumento y un NUL embebido no es transportable por ese ABI.

Windows debe usar una entrada wide y convertir UTF-16 bien formado a UTF-8. Un
surrogate aislado o mal emparejado produce la misma exception. No se permite el
argv narrow dependiente de code page ni best-fit mapping.

La exception es final, unchecked y sin payload obligatorio. Se prefirió frente
a un trap porque el encoding es input externo recuperable; frente a un
`Result` universal o resultado nominal porque la ruta normal tiene una única
salida útil; y frente a replacement porque perder bytes silenciosamente puede
cambiar comandos o paths. OOM, overflow y corrupción del ABI siguen siendo
traps fail-fast.

## Snapshot y entry

La firma source continúa siendo `int main()`. El wrapper host generado recibe
`argc`/`argv`, copia `[1, argc)` a un snapshot runtime privado y read-only,
invoca el `main()` Aether y destruye el snapshot al salir. En POSIX copia bytes;
en Windows copia code units UTF-16. La validación se difiere hasta `args()` para
que la exception pueda capturarse dentro del programa.

El snapshot posee count, longitudes y storage. No retiene pointers al vector,
stack o CRT de startup. Cambiar o destruir un Array retornado no cambia el
snapshot ni llamadas posteriores. Init/dispose debe quedar balanceado tanto en
retorno normal como ante una exception no capturada y no puede falsear el audit
de allocations Aether.

Esta opción evita cambiar el tipo de la función Aether, propagar un context
oculto por cada call o permitir `main(int argc, ...)` en source.

## IR y reachability

`std.Process.args` es una direct call ordinaria a la identidad canónica
`std::Process::args`. HIR, MIR y SSA conservan retorno `Array<string>` owning,
orden effectful, `reads_external`, `may_allocate` y `may_unwind`. No se agrega
syntax, `ProcessOp`, tipo nuevo de Function ni parámetro ABI visible.

El backend puede materializar un adaptador privilegiado para esa identidad,
igual que otras funciones STD respaldadas por runtime. Sólo una call alcanzable
selecciona wrapper con captura de argumentos, init/dispose, conversor del
target, exception y glue Array/string. Un import sin uso no arrastra código.

## Complejidad e invariantes

El snapshot se construye una vez en O(total input). Cada call V1 cuesta
O(n + bytes UTF-8), usa como máximo una allocation de backing no vacío y una
allocation por string no vacío, y nunca concatena o crece incrementalmente.
Empty puede reutilizar los singletons existentes.

La implementación futura deberá validar `argc`, no leer fuera de `[1, argc)`,
hacer checked toda suma/producto/expansión, validar encoding antes de publicar,
limpiar prefijos parciales y evitar por completo pointers host en el IR público.

## Qualification futura

PROCESS-ARGS-V1 deberá cubrir O0/O2, cero/uno/varios argumentos, empty, espacios,
`:`, Unicode multibyte, emoji, argumentos largos, orden, exclusión de argv[0],
calls múltiples, mutación independiente, lifecycle y unwind exactos.

En POSIX debe inyectar argumentos no UTF-8 reales mediante una API
byte-preserving. Para Windows se requieren tests puros de conversión UTF-16,
incluidos pares y surrogates inválidos, más ejecución native wide cuando exista
CI Windows. Hasta entonces sólo Linux x86-64/POSIX podrá declararse calificado.

Los dumps/verificadores deben demostrar call ordinaria, retorno owning y edge
excepcional; pruebas de reachability deben demostrar que programas sin uso no
incluyen el runtime Process.

## Expense Tracker

El vertical de implementación deberá agregar una fixture que observe:

```text
program ledger.alpt add 42 12.5 food
program ledger.alpt list
program ledger.alpt summary
```

como arrays que comienzan en `"ledger.alpt"`, haga dispatch y reutilice el
parsing ya admitido. La fixture no implementará ni fingirá persistencia atómica;
`writeTextAtomic` y `appendText` permanecen fuera de alcance.

## Validación de este milestone

- Se crearon únicamente el documento normativo y este reporte.
- No se modificó compiler, driver, runtime, standard library, fixture ni test.
- No cambió ningún programa admitido y no se afirma qualification ejecutable.
- Se preservaron los cambios preexistentes del worktree.
- No quedan decisiones abiertas que bloqueen PROCESS-ARGS-V1 en POSIX. El
  adapter wide y su matriz de qualification cierran la estrategia Windows sin
  declarar ese target implementado.

Permanecen en milestones separados environment, cwd, spawning, exit, signals,
raw args, APIs lossy, parser CLI, opciones nombradas, shell parsing y
persistencia atómica.
