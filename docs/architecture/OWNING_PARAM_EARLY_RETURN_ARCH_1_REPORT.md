# OWNING-PARAM-EARLY-RETURN-ARCH-1 — reporte de diseño

Estado: **ARQUITECTURA CERRADA; SIN IMPLEMENTACIÓN**, 2026-09-23.

Documento normativo:
[OWNING-PARAM-EARLY-RETURN-ARCH-1](OWNING_PARAM_EARLY_RETURN_ARCH_1.md).

## Resultado

Se cerró el contrato de lifecycle para parámetros owning por valor con CFG
arbitrario. Un parámetro owning entra al callee como `Owned`; no tiene que ser
movido explícitamente. En cada path alcanzable su obligación termina exactamente
una vez mediante Transfer, Drop normal o cleanup de unwind.

Por tanto, este programa es válido:

```aether
int f(Owner x, bool early) {
    if (early) { return 1; }
    return 2;
}
```

Cada return evalúa su resultado, destruye `x` una vez y retorna. Si un path usa
`return x`, ese path mueve `x` al resultado y omite su Drop; un sibling que no lo
mueve todavía lo destruye.

## Diagnóstico del estado actual

La auditoría del repositorio encontró que el modelo principal ya contiene las
piezas necesarias:

- HIR inicia parámetros non-Copy en `Owned`, los agrega al scope activo, procesa
  la expresión de retorno y después sintetiza `HirDrop` según el estado;
- HIR ya excluye branches terminantes de joins continuantes y dispone de
  `MaybeMoved`/conditional cleanup;
- MIR inicia parámetros owning en `active_owners`, crea flags inicialmente
  armados para parameters cuando se necesitan y posee landing pads, pending
  actions para `finally`, `Move`, `Drop` y CFG explícito;
- el verifier MIR ya hace dataflow `Owned/Moved/MaybeMoved` y rechaza un return
  que conserve un owner vivo;
- SSA conserva parameters, memory locals, phis, drop flags, Move/Drop, unwind
  edges y terminadores.

La regresión está alineada con la auditoría de Expense Tracker: el verifier SSA
de ownership compuesto con string reúne todos los owners y exige que cada uno
tenga algún sitio global de Transfer o Drop. Esa prueba existencial no demuestra
balance por path y puede rechazar un parámetro correctamente limpiado mediante
los roots/memory places generados, especialmente con varios exits. También es
demasiado débil para ser la autoridad de exactamente-una-vez.

La arquitectura no prescribe un parche especial para Expense Tracker ni para
`string`. Prescribe sustituir esa condición de balance por un ledger general de
obligaciones path-sensitive, conservando chequeos especializados sólo como
validaciones complementarias.

## Decisiones de IR

No se agregan nodos HIR, MIR o SSA.

HIR conserva `HirStmtKind::Return { value, drops }`. La regla obligatoria es
analizar primero `value`, tomar después el snapshot path-local y generar Drop
incondicional, ninguno o conditional Drop para `Owned`, `Moved` y `MaybeMoved`.

MIR puede dejar ladders duplicadas o compartir sufijos equivalentes. Sólo puede
compartir cuando coinciden exit/continuation, profundidad de finally y secuencia
ordenada `(root, modo, flag)`. Temporales, locals y parámetros se destruyen en
orden inverso y el carrier de retorno se excluye.

SSA reconstruye el ledger desde parámetros, owner-producing instructions,
transfers, Drops, phis, memory roots y flags. En cada Return o propagación fuera
de función, el ledger del frame debe estar vacío después de contabilizar el
resultado/payload transportado. Calls con unwind producen estados por edge: los
argumentos owning ya transferidos faltan en ambos successors y el resultado
sólo existe en el normal.

Un Move a otro root del mismo frame termina la obligación del source pero
traslada el token al destino; no basta por sí solo para balancear la función.
Aggregate/container construction traslada del mismo modo sus componentes al
root compuesto. Sólo Drop o una transferencia fuera del frame retira finalmente
el token del ledger del callee.

## Return, exceptions y loops

El orden exacto cerrado es:

```text
evaluate return expression
materialize/move return value
run scope/finally cleanup for remaining owners
return
```

Esto evita dropear un parámetro retornado y asegura que un unwind durante la
expresión use el estado anterior correcto. Throw protege primero su payload y
después limpia; un callee que recibe argumentos owning responde por ellos aunque
propague; el caller no los vuelve a limpiar en su unwind pad.

Returns y unwind pendientes atraviesan `finally` con carrier/evento protegido.
Los roots interiores se limpian al cruzar su scope y los exteriores después del
finally. Una acción que el finally reemplace vuelve a someterse al mismo balance.
Si el finally puede mover un root exterior, la acción pendiente debe usar su
estado posterior o el drop flag correspondiente, nunca un Drop incondicional
stale calculado antes de entrar al finally.

En loops, return limpia el scope de función; break/continue no limpian el
parámetro que sigue en scope. Un move en un path que retorna no llega al
backedge. Un move que sale por break puede producir `MaybeMoved` después del
loop y sólo habilita conditional cleanup, nunca uso ordinario. Se conserva el
mismo lattice y análisis de punto fijo, sin estado específico para loops.

## Drop flags y corrupción

Un parámetro owning comienza con flag `true`; inicialización arma, Transfer/Drop
desarma y los joins crean el phi booleano correspondiente. Conditional Drop debe
consultar el flag del mismo root y dropear únicamente en el arm verdadero.

La qualification futura corromperá HIR/MIR/SSA para comprobar rechazo de owner
vivo al exit, double Drop, Drop-after-Move, flag incorrecto, early return o
unwind sin cleanup, argumento transferido dropeado por el caller, carrier de
retorno dropeado y phi que duplica ownership.

## Regression y qualification futura

Se fijó como regression real la forma original por valor del helper `runList`
de Expense Tracker: `Array<string>` y `LedgerDecodeResult` observados, un return
temprano por aridad y un return final. Ambos parámetros deben destruirse en cada
exit, en orden inverso. Se exige también una fixture del helper real o sus tipos
estructurales, no sólo un caso artificial de string.

La matriz agrega uno y varios early returns, un path que mueve el parámetro y
otro que lo retiene, nested branches, joins, loops con return/break/continue,
throw, call unwind y finally. Se ejecutará en O0/O2 con counters de allocation,
move, drop y free; deberá observar cero leaks, double drops y double frees, y se
comparará con un equivalente manual cuando sea posible.

## Validación de este milestone

- Se crearon únicamente el documento normativo y este reporte.
- No se modificó compiler, runtime, standard library, ejemplos ni tests.
- No se declara corregida ni calificada la regresión.
- Se preservó el workaround `ref`/`ref mut` del port existente y cualquier
  cambio preexistente del worktree.
- No quedan decisiones semánticas abiertas para iniciar el vertical de
  implementación.

Quedan fuera borrow inference, cloning implícito, copy constructors, GC, nuevos
destructores, sintaxis de ownership, partial moves y cleanup de traps abortivos.
