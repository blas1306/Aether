# OWNING-PARAM-EARLY-RETURN-ARCH-1 — lifecycle de parámetros owning en CFG arbitrario

Estado: **DECISIÓN DE ARQUITECTURA; NO IMPLEMENTADA**, 2026-09-23.

Este milestone cierra la semántica de parámetros owning por valor frente a
returns tempranos, branches, loops y salidas excepcionales. No modifica hoy el
compiler, runtime, standard library, fixtures ni tests. La implementación y su
qualification corresponden a un vertical posterior.

La decisión reutiliza sin ampliarlo el lattice `Owned`/`Moved`/`MaybeMoved`, los
drop flags root-level, el Drop tipado recursivo y el modelo de exceptions y
`finally` ya existentes. Corrige una regresión de verificación; no introduce
cloning implícito, inferencia de borrow, destructores nuevos ni otro sistema de
lifecycle.

## 1. Decisiones resumidas

- Un parámetro non-Copy con `needs_drop(T)` entra al callee como una obligación
  owning `Owned`. El caller la transfiere en la frontera de call.
- La obligación debe terminar exactamente una vez en cada salida alcanzable del
  callee: por Move/Transfer, Drop normal o cleanup de unwind.
- Llegar `Owned` a un `return` source es válido. Significa que el compilador
  inserta `Drop` antes del terminador; nunca exige un consume source artificial.
- El valor de retorno se evalúa y se mueve a un carrier protegido antes de
  limpiar los owners restantes. Si el valor retornado consume el parámetro, ese
  parámetro no aparece en el cleanup.
- `Owned` produce Drop incondicional, `Moved` no produce Drop y `MaybeMoved`
  reutiliza el drop flag y el conditional Drop actuales.
- Los cleanups siguen orden de adquisición: temporales vivos primero en orden
  inverso de construcción y después locals/parámetros en orden inverso de
  declaración, desde el scope interior al exterior. Los parámetros pertenecen
  al scope de función y preceden a sus locals.
- Returns pueden compartir cleanup ladders sólo cuando coinciden exit kind,
  continuación, estado de `finally`, conjunto ordenado de obligaciones y modo
  de cada cleanup. Compartir bloques es una optimización, no semántica.
- HIR no necesita nodos nuevos. MIR y SSA conservan sus `Move`, `Drop`, flags,
  CFG, unwind edges y terminadores actuales.
- El verifier SSA deja de preguntar si cada parámetro fue movido alguna vez y
  demuestra en cambio que cada obligación se descarga exactamente una vez por
  cada path alcanzable, incluido unwind.
- Traps abortivos siguen sin ejecutar cleanup. Sólo `throw`, `rethrow` y calls
  con edge recuperable/unwind participan en esta decisión.

## 2. Contrato semántico normativo

Para un parámetro owning por valor `x: T`, con `T` non-Copy y
`needs_drop(T) == true`, la entrada de función crea una obligación lógica:

```text
caller --Move(argument)--> callee entry: x = Owned
```

En cada path alcanzable, esa obligación tiene exactamente uno de estos finales:

1. **Move/Transfer**: `x` se transfiere a otro owner, a una call consumidora, a
   un aggregate o al resultado de la función. `x` pasa a `Moved` y no se limpia.
2. **Drop normal**: `x` continúa `Owned` al abandonar su scope de función y el
   cleanup ejecuta un Drop tipado exactamente una vez.
3. **Cleanup excepcional**: un edge de unwind abandona el scope y ejecuta el
   mismo Drop, o su forma condicional, exactamente una vez antes de propagar o
   entrar al handler correspondiente.

No existe una cuarta obligación de “consumir explícitamente” el parámetro. No
usar un owner es legal siempre que su cleanup automático descargue la
obligación. Los tipos Copy no crean obligación owning; un tipo non-Copy sin
Drop conserva las restricciones de transferencia existentes, pero no inventa
una acción física de destrucción para satisfacer este milestone.

“Terminar la obligación de `x` por Transfer” se refiere al root source. Si el
destino sigue dentro del mismo frame, el token lógico continúa bajo la identidad
del destino y éste también debe transferirse fuera o destruirse. Sólo una
transferencia al caller/callee u otro owner exterior saca ese token del ledger
del frame. Así, `Owner y = x; return 0;` no queda balanceado por el Move de `x`:
el cleanup debe destruir `y`.

El lattice no cambia:

| Estado al abandonar scope | Acción de cleanup |
| --- | --- |
| `Owned` | Drop tipado incondicional |
| `Moved` o `Dropped` | ninguna |
| `MaybeMoved` | consultar el drop flag exacto y ejecutar Drop sólo si está armado |
| `Uninitialized` | ninguna; no es un estado válido de entrada para un parámetro owning |

Después de Drop el root está `Dropped`. Después de Transfer está `Moved`. Ninguna
operación ordinaria puede leer, prestar, mover o destruir un root `Moved`,
`Dropped` o `MaybeMoved`.

### 2.1 Owner nunca movido

```aether
int f(Owner x, bool b) {
    if (b) { return 1; }
    return 2;
}
```

Ambos paths son válidos. En cada uno se evalúa el `int`, se ejecuta `Drop(x)` y
después se retorna. No se crea drop flag porque el estado de `x` es uniformemente
`Owned` en cada exit y no existe un join `Owned`/`Moved` relevante.

### 2.2 Owner movido en un path

```aether
Owner identity(Owner x, bool b) {
    if (b) { return x; }
    Owner y = makeOwner();
    return y;
}
```

En el path `b`, evaluar `return x` transfiere `x` al carrier de retorno; no hay
`Drop(x)`. En el otro path, `y` se transfiere al carrier y `x` permanece Owned,
por lo que se destruye antes del terminador. `y` no se destruye en el callee.
La divergencia termina en exits distintos: por sí sola no exige `MaybeMoved` ni
un flag.

### 2.3 Joins y branches anidados

Sólo los predecessors que continúan contribuyen al estado de un join. Un arm
que retorna, lanza o diverge no contamina el join posterior. Para predecessors
continuantes se aplican las reglas actuales: estados iguales permanecen
iguales; `Owned + Moved` produce `MaybeMoved`; cualquier merge con
`MaybeMoved` permanece `MaybeMoved`.

Branches anidados y varios early returns no cambian la regla. Cada exit recibe
el cleanup derivado de su estado propio, no el estado aproximado de otro exit.
Un `MaybeMoved` puede continuar únicamente hacia control y cleanup que no use el
valor; cualquier uso source ordinario sigue siendo error estático.

## 3. Orden normativo del return

Todo return se interpreta en este orden observable:

```text
1. evaluar completamente la expresión de retorno;
2. materializar/mover el resultado a un carrier de retorno owning, si aplica;
3. ejecutar finally pendientes conforme a su contrato;
4. limpiar las obligaciones restantes de los scopes abandonados;
5. ejecutar el terminador Return, que transfiere el carrier al caller.
```

Los pasos 3 y 4 pueden intercalarse por scopes: antes de entrar a un `finally`
se limpian los roots interiores que ese `finally` no puede observar; los roots
exteriores permanecen vivos hasta que el `finally` termina y luego se limpian.
La propiedad indispensable es que el carrier ya esté separado y protegido:
nunca forma parte del cleanup residual.

Consecuencias:

- `return x` mueve `x` antes de calcular el cleanup; `Drop(x)` queda omitido.
- `return make(x)` respeta los consumes que ocurran al evaluar la call.
- si evaluar la expresión hace unwind, todavía no existe un return normal: el
  unwind pad limpia exactamente los owners que sigan vivos en ese punto;
- un temporal de resultado ya comprometido al carrier no puede ser dropeado por
  el callee en el path normal;
- side effects de la expresión ocurren antes que cualquier Drop del return.

Para un return Copy el carrier puede ser un SSA value. Para un resultado owning
puede ser un local/slot compiler-generated o la representación ABI equivalente.
Esto no agrega sintaxis ni un nodo HIR público.

## 4. HIR

La forma HIR vigente es suficiente: parámetros tienen identidad `LocalId` y
tipo; `HirStmtKind::Return` conserva la expresión y una lista de `HirDrop`; los
exits de scope, throw/rethrow, loops y try/finally ya tienen cleanup explícito.

El contrato del synthesis HIR queda fijado así:

1. cada parámetro non-Copy entra en estado `Owned` y en el conjunto activo del
   scope de función;
2. el análisis procesa primero la expresión de return, incluidas todas sus
   transiciones `Owned -> Moved`;
3. después toma un snapshot path-local y sintetiza, en orden inverso, Drop
   incondicional para `Owned`, ninguno para `Moved` y conditional Drop para
   `MaybeMoved`;
4. marca sólo ese path como terminado. Su estado posterior no participa en un
   join continuante;
5. la caída normal de `main` ya normalizada a `return 0` usa exactamente el
   mismo camino, sin exención.

No se agrega `ConsumeParameter`, `ImplicitDropAtReturn` ni un estado nuevo.
La implementación futura debe auditar que `definitely_returns` no mezcle el
estado mutado por un early return con siblings o joins continuantes. HIR
corrupto debe rechazarse si omite, duplica, desordena o agrega un drop que no
corresponde al snapshot del exit.

## 5. MIR y cleanup ladders

MIR materializa explícitamente el plan HIR. Una forma conceptual para el primer
ejemplo es:

```text
bb_early:
    result = 1
    Drop(x)
    Return(result)

bb_tail:
    result = 2
    Drop(x)
    Return(result)
```

Puede canonicalizarse a:

```text
bb_early: result = 1; Goto(cleanup_x)
bb_tail:  result = 2; Goto(cleanup_x)
cleanup_x: Drop(x); Return(result_phi)
```

si el phi/carrier, el orden de Drop y toda metadata de exception/finally son
equivalentes. No debe forzarse una única epilogue universal: distintos exits
pueden tener conjuntos o estados de owners diferentes.

Una cleanup ladder es una secuencia de bloques, un root por peldaño cuando se
necesita branch condicional. Su clave semántica es:

```text
(exit kind, continuation/event, finally depth,
 ordered [(root, Unconditional|Conditional, flag)])
```

Dos exits sólo pueden compartir el sufijo para el cual esa clave coincide. El
orden es: temporales vivos en orden inverso de construcción; bindings del scope
interior en orden inverso de declaración; scopes hacia afuera; locals de función
en orden inverso y finalmente parámetros en orden inverso. Un owner movido se
omite, no se representa mediante un Drop no ejecutado.

### 5.1 Drop flags

Se conserva un booleano compiler-generated por root que alcance cleanup en
`MaybeMoved`, o que necesite la misma discriminación en unwind:

- parámetros owning: flag inicial `true`;
- local aún no inicializado: flag inicial `false`;
- publicación/inicialización completa: escribir `true`;
- Move/Transfer o Drop: escribir `false` en la misma transición lógica;
- merge: phi booleano con el valor de cada predecessor;
- conditional cleanup: branch sobre el flag del mismo root; el arm `true`
  ejecuta exactamente un Drop y desarma el flag, el arm `false` lo omite.

El flag no hace válido usar un `MaybeMoved`, no es source-addressable, no es por
field y no duplica el discriminante de nullable/enum. Un flag conservador puede
existir para unwind aunque un pad concreto sólo reciba `Owned`; debe seguir
siendo exacto y puede optimizarse después de verification.

### 5.2 Transferencia del resultado

El resultado owning se materializa en un root/carrier distinto o en una forma
SSA que represente la misma transferencia. La operación que lo crea consume el
source. La ladder excluye el carrier y el terminador lo transfiere al caller.
Está prohibido mover el valor al return y después destruir el source lógico o
el carrier como parte del frame saliente.

## 6. Exceptions, calls y finally

Las salidas recuperables obedecen la misma obligación, con estados específicos
del edge.

### 6.1 Throw y rethrow

Primero se evalúa y compromete el payload de `throw`. Si el payload consume un
owner, ese root ya está `Moved`. Luego se limpian temporales y scopes abandonados
antes de transferir el evento al handler o continuar el unwind. El payload
transportado queda protegido igual que un carrier de retorno.

Un handler local no limpia roots de scopes exteriores que continúan vivos. Una
propagación que abandona la función sí descarga todos los owners restantes de
esa función. `rethrow` no vuelve a adquirir ni vuelve a limpiar el payload del
evento capturado.

### 6.2 Calls que pueden unwind

Los argumentos owning by-value se transfieren al callee antes de la invocación
y quedan `Moved` en ambos successors del call. El caller no puede dropearlos en
su unwind pad; el callee es responsable de sus parámetros tanto si retorna como
si propaga. El resultado de la call sólo se inicializa en el successor normal.

El unwind edge se toma desde el estado exacto inmediatamente anterior a la
posible excepción, después de consumos de argumentos y antes de publicar el
resultado. Su landing pad limpia en reverse order todos y sólo los owners vivos
de los scopes abandonados, usando flags para estado condicional, y luego entra
al catch/finally o propaga.

### 6.3 Finally

Un return, break, continue o unwind pendiente se representa como una acción
pendiente mientras ejecuta los `finally` interiores a exteriores. El return
carrier o exception event permanece protegido. Cada owner se limpia al cruzar
el límite de su scope, una sola vez; no se repite en la continuación de la
acción pendiente.

Un plan pendiente no puede congelar un Drop incondicional calculado antes de un
`finally` si ese `finally` todavía puede mover o destruir el root exterior. La
acción posterior usa el estado resultante del `finally`; cuando confluyen
estados `Owned`/`Moved`, debe usar el mismo flag condicional existente. Un
`finally` que sólo observa el root conserva el Drop originalmente debido.

Si un `finally` completa normalmente, continúa la acción original. Si ejecuta
su propio return/throw, éste reemplaza la acción pendiente según la semántica
vigente y debe descargar las obligaciones todavía vivas exactamente una vez.
Drop glue continúa siendo no-throwing; un trap durante cleanup aborta y no
promete ejecutar el resto de la ladder.

## 7. Loops

Los parámetros de función permanecen activos alrededor de un loop. Por tanto:

- `return` desde el cuerpo abandona todos los scopes y limpia el parámetro si
  continúa Owned;
- `break` y `continue` sólo limpian bindings de los scopes que realmente
  abandonan; no limpian un parámetro del scope de función;
- un path que mueve el parámetro y retorna inmediatamente es válido y no aporta
  estado al backedge;
- un path que mueve el parámetro y hace `break` se combina con zero-iteration y
  otros exits del loop; el resultado puede ser `MaybeMoved` y sólo puede
  continuar sin uso ordinario hasta un conditional cleanup;
- un path que mueve el parámetro y alcanza `continue`/latch debe satisfacer el
  análisis de punto fijo. Si una iteración posterior podría usar el root, se
  rechaza. Los flags no convierten ese uso en dinámicamente válido.

La implementación puede conservar restricciones conservadoras sobre
backedges, pero no puede rechazar un move confinado a un path terminante ni un
parámetro uniformemente Owned alrededor del loop. El dataflow de CFG usa el
mismo lattice y calcula un punto fijo; no se agrega estado “loop-owned”.

## 8. Invariante y verifier SSA

La invariante incorrecta queda explícitamente eliminada:

```text
INCORRECTO: every owning parameter must be consumed by Move
INCORRECTO: every SSA owner value must have some consume site somewhere
```

La invariante normativa es:

```text
Para cada obligación owning y cada salida alcanzable de su región,
existe exactamente una descarga path-sensitive que domina esa salida:
Transfer, Drop incondicional, conditional Drop seleccionado por su flag,
o cleanup de unwind. No puede existir una segunda descarga en ese path.
```

El verifier debe implementar un ledger de obligaciones sensible a CFG, no una
búsqueda existencial global de usos. El ledger se deriva de IR existente:

- seeds `Owned` para parámetros owning;
- nuevas obligaciones para resultados/initializers owning publicados;
- `Move`, calls consumidoras, aggregates, enum construction, collection
  insertion y return transfieren una obligación fuera del source;
- `Drop` la descarga;
- phis de owners combinan alternativas mutuamente exclusivas, no duplican un
  token;
- Stores/Loads de memory locals usan su identidad de root y la metadata de
  promoción existente; no crean owners por copiar bits;
- drop flags prueban presencia de la obligación del root asociado.

Un Move a otro root del mismo frame cambia la identidad que porta el token; no
lo elimina del ledger. Una call by-value o Return lo elimina del frame y crea la
obligación correspondiente en el receptor externo. Construir un aggregate o
container local traslada los tokens de sus componentes al root compuesto, cuyo
Drop recursivo es la única descarga posterior; no cuenta como fuga ni como
descarga prematura de los recursos interiores.

El transfer function se ejecuta por bloque hasta punto fijo. Para instrucciones
con unwind produce estados edge-specific: argumentos consumidos no están vivos
en ninguno de los dos edges; el resultado sólo existe en el normal. En joins,
el estado lógico y el phi del flag deben coincidir predecessor por predecessor.

En un `Return`, SSA primero contabiliza la transferencia del operand de retorno
si éste es owning y después exige ledger vacío para todas las demás obligaciones
del frame. En `ResumeUnwind` o propagación fuera de función exige igualmente que
el ledger del frame esté vacío, exceptuando únicamente el payload/evento
transportado. Exits abortivos no se someten a cleanup recuperable.

La prueba debe ser general para todo `needs_drop(TypeId)`, incluidos string,
Buffer, Array/List, structs, enums, nullable, concrete generics y class owners
según sus contratos especializados. El chequeo actual específico de owners que
contienen string puede conservar validaciones estructurales complementarias,
pero no puede ser la autoridad de balance ni exigir un consume global de cada
parameter SSA value.

## 9. Responsabilidad por capa y corrupción

HIR comprueba reglas source, orden del return y plan de drops por estado. MIR
reconstruye independientemente el dataflow root-level, valida flags y exige que
cada terminador normal o excepcional salga balanceado. SSA vuelve a demostrar
el balance sobre el CFG promovido, phis, memory locals y unwind edges. LLVM no
infiere lifecycle: emite el CFG ya verificado y puede compartir/eliminar bloques
sólo preservando efectos.

Las pruebas de corrupción deben rechazar como mínimo:

| Corrupción | Motivo de rechazo |
| --- | --- |
| owner live alcanza `Return`/propagación | obligación no descargada |
| Drop duplicado en un path | double discharge |
| Drop después de Move/Transfer | uso de obligación ausente |
| Move/Transfer después de Drop | uso after drop |
| conditional Drop con flag de otro root | prueba de presencia desconectada |
| flag inicial/update/phi invertido u omitido | flag no equivale a ownership |
| early return sin su ladder | path alcanzable con fuga |
| unwind edge que saltea cleanup | salida excepcional con fuga |
| argumento ya transferido limpiado por caller unwind | double discharge entre frames |
| return source/carrier movido y después dropeado | resultado destruido antes de transferencia |
| phi que usa una obligación en dos outputs owning | duplicación de token |
| ladder compartida con orden/estado/finally distintos | cleanup no equivalente |

Los verificadores deben fallar cerrados aun cuando el backend pudiera generar
código que “parece funcionar” para el caso corrupto.

## 10. Regression fixtures y qualification futura

El vertical de implementación debe preservar como fixture el shape real que
apareció durante el port de Expense Tracker, antes del workaround con borrows:

```aether
int runList(
    Array<string> arguments,
    expense_tracker.persistence.LedgerDecodeResult loaded
) {
    if (length(arguments) != 2) {
        println("invalid arguments: <ledger.alpt> list");
        return 2;
    }
    expense_tracker.reports.printTransactions(loaded.ledger);
    return 0;
}
```

Ambos parámetros son observados, no movidos; cada return debe limpiar ambos en
orden inverso. La fixture puede aislar tipos equivalentes mínimos, pero debe
existir además una compilación del helper Expense Tracker por valor para evitar
que un mock exclusivamente basado en `string` o Buffer esconda la regresión
estructural.

La matriz positiva mínima incluye:

- un early return y fallthrough/return final;
- varios early returns siblings;
- un path que mueve el parámetro al return y otro que lo retiene y lo dropea;
- branches anidados, joins `Owned/Owned` y `Owned/Moved`;
- return desde `while`, `for range` y collection loop;
- break/continue con parámetro vivo y move sólo en path terminante;
- throw explícito antes y después de mover otro owner;
- call que retorna normalmente y la misma call haciendo unwind;
- try/catch/finally, incluidos return pendiente y override desde finally;
- varios parámetros/locals para demostrar reverse declaration order;
- aggregates owning estructurales, no sólo string directo.

Cada caso se ejecutará en O0 y O2. Los probes de lifecycle observarán al menos:

```text
allocation count
logical move/transfer count
drop count y orden
free count
live allocations al terminar
double-drop/double-free count
```

Para toda ejecución normal o excepción capturada: allocations y frees quedan
balanceados, cada obligación tiene exactamente un final, no hay leak ni double
drop. Cuando sea posible se compara stdout/status/counters con un equivalente
manual que expresa los mismos Drops/transfers sin depender de early-return
lowering. Los dumps HIR/MIR/SSA deben demostrar evaluación del resultado antes
del cleanup, flags sparse correctos, ladders normal/unwind y ausencia de Drop
del carrier retornado.

La qualification negativa mutará HIR, MIR y SSA de manera independiente para
cada fila de la tabla de corrupción. Debe incluir O0/O2 porque optimización no
puede reparar IR inválido ni ocultar una obligación rota.

## 11. Alcance y no objetivos

Este milestone no diseña ni admite:

- inferencia nueva de borrow o cambio de `ref`/`ref mut`;
- cloning implícito, copy constructors o aliasing owning;
- GC, ARC nuevo o destructores de usuario;
- sintaxis nueva de ownership;
- partial moves de fields ni flags por field;
- cleanup de traps abortivos;
- supresión/encadenamiento de exceptions lanzadas por Drop;
- relajación general de usos `MaybeMoved` o de borrows vivos;
- optimizaciones ABI o una epilogue única obligatoria.

La única ampliación semántica es hacer efectiva una regla que el lenguaje ya
declara: recibir ownership por valor obliga al callee a transferirlo o limpiarlo,
no a moverlo artificialmente.

## 12. Criterio de cierre del vertical de implementación

OWNING-PARAM-EARLY-RETURN-V1 podrá declararse cerrado sólo cuando:

1. el reproducer mínimo y el helper Expense Tracker por valor compilen y corran;
2. HIR, MIR y SSA acepten todos los CFG válidos de la matriz;
3. los tres niveles rechacen su corrupción correspondiente;
4. normal return, throw, call unwind y finally descarguen cada obligación una
   vez;
5. O0/O2 y counters demuestren cero leaks y cero double drops/frees;
6. no se hayan agregado nodos HIR/MIR/SSA ni un segundo lifecycle salvo que una
   evidencia de implementación posterior invalide expresamente esta decisión.
