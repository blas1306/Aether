# EXCEPTION-V4 — `finally`

## Estado y sintaxis

EXCEPTION-V4 agrega un bloque `finally` opcional al `try` existente. Se admiten
ambas formas:

```aether
try {
    work();
}
catch (SomeException error) {
    recover(error);
}
finally {
    cleanup();
}
```

```aether
try {
    work();
}
finally {
    cleanup();
}
```

Un `try` sin `catch` ni `finally` sigue rechazándose con `E0430`. El parser no
permite más de un `finally` ni cláusulas `catch` después de él.

Este primer vertical mantiene `finally` no-throwing. Dentro del bloque se
rechazan con `E0438` `return`, `break`, `continue`, `throw expression`,
`throw;`, llamadas y construcción de clases. Las operaciones fail-fast que
pueden terminar en trap conservan la semántica de trap y no se convierten en
excepciones.

## Salidas normales y abruptas

Cada salida dinámica de un `try`/`catch` con `finally` registra una acción
pendiente y entra en una única región compartida. Esto cubre:

- fallthrough del `try`;
- finalización normal de un handler;
- `return` desde `try` o `catch`;
- `break` y `continue` desde un `try` dentro de un loop;
- excepción no capturada localmente;
- propagación desde un handler.

Al terminar el bloque, un dispatch exhaustivo recupera la acción pendiente. No
se clona el cuerpo de `finally` por salida: una ejecución que abandona la
construcción entra una vez en la región y sale una vez por el continuation que
le corresponde. Los `finally` anidados encadenan la acción hacia afuera en
orden léxico interior-exterior.

## Representación del control pendiente

MIR usa estado exclusivamente local a la función:

- un selector `uint32` local identifica el continuation;
- un slot local conserva el payload de `return`;
- la acción pendiente conserva el target de `break`/`continue`, los drops aún
  no ejecutados o el `ExceptionEvent` activo;
- `SetPendingFinally`, `EnterFinally` y `ExitFinally` hacen explícito el
  protocolo en MIR y SSA;
- `FinallyRegion` registra identidad, entrada, dispatch, bloques del cuerpo y
  exits autorizados.

No se usa TLS ni estado global. Los tags se asignan en orden estable y el
dispatch enumera exactamente un caso por acción registrada.

En este vertical el slot de retorno se admite para payloads escalares. Una
función de retorno owning o agregado que contiene `finally` se rechaza con
`E0438`; extender el slot a payloads move-only sin inventar un owner en las
rutas no-return queda como deuda explícita.

## Propagación excepcional

Una excepción que no encuentra handler local ejecuta primero el cleanup
implícito correspondiente al scope protegido, conserva su `ExceptionEvent`,
registra `Resume` y atraviesa `finally`. Después del dispatch se emite
`ResumeUnwind` para ese mismo evento.

Si existe un handler exterior, la acción `Forward` conserva el evento físico y
su destino exterior mientras corre `finally`; luego ejecuta
`ForwardUnwind`. No se vuelve a construir el objeto, no se llama nuevamente a
`aether_throw` y no se crea una excepción sustituta. El backend transporta el
mismo puntero EH capturado por el landing pad. No existen suppressed
exceptions ni reemplazo silencioso de una excepción activa.

Una excepción capturada cuyo handler termina normalmente ejecuta `EndCatch`,
entra una vez en `finally` y continúa al join normal. Un `return` desde el
handler conserva primero su valor, cierra el catch y solo entonces ejecuta la
región.

## `return`, `break` y `continue`

El lowering separa el payload/destino pendiente de los cleanups por frontera
de `finally`. Para un `return`, el valor escalar se materializa antes de entrar
en la región y se devuelve después del dispatch. Para `break` y `continue`, el
target del loop y la profundidad de finalizers quedan fijados antes de la
entrada; al salir se continúa hacia el exit o header original.

Los drops se dividen por el límite de owners capturado al abrir cada
`finally`. Así, cada owner se limpia en su frontera correcta y una acción que
atraviesa varios finalizers no duplica el cleanup.

## HIR, MIR y SSA

HIR conserva `HirFinally { id, body, span }` dentro de `HirStmtKind::Try`.
También representa `Break` y `Continue` con sus drops sintetizados. El
verificador exige identidades `FinallyId` canónicas, un `try` no vacío de
cláusulas y un cuerpo de `finally` sin throw/call/control saliente.

MIR construye una sola copia del cuerpo y expone el protocolo mediante
`FinallyRegion`. Su verificador comprueba:

- identidades y metadata canónicas;
- selector `uint32` y dispatch exhaustivo en orden de tag;
- exactamente un `EnterFinally` y un `ExitFinally`;
- una asignación pendiente por exit, seguida directamente por la entrada;
- exits cuyo único predecessor es el dispatch;
- ausencia de invokes, unwind y terminadores salientes dentro de la región.

SSA preserva la metadata y los tres operadores. Verifica nuevamente, sin
confiar en MIR, el phi/direct value del selector, cada incoming, tags y cases,
predecessors, marcadores únicos y la ausencia de bypasses o control saliente.
Las reglas ordinarias de dominancia, definición única y ownership siguen
aplicándose.

## Ownership

El cleanup implícito continúa siendo independiente de `finally`: el lenguaje
no interpreta el bloque como destructor ni permite reemplazar el ledger de
owners con código de usuario. Los owners del scope abandonado se liberan según
los `HirDrop` existentes y los temporales de unwind; luego se ejecuta
`finally`. Drop flags y estados MIR/SSA verifican que cada `Buffer` y cada
objeto de clase se consuma o destruya exactamente una vez.

La qualification mide alloc/free, retain/release, destroy y buffer-drop para
una propagación a través de `finally`; los contadores quedan balanceados en O0
y O2.

## LLVM EH

LLVM EH sigue siendo transporte físico. Las llamadas y throws del `try` usan
los `invoke`/landing pads de EXCEPTION-V1/V2/V3. El landing pad ejecuta el
cleanup implícito y salta a la entrada ordinaria de `finally`; después del
dispatch se reanuda o reenvía el evento con `resume`/la transferencia ya
verificada.

El cuerpo compartido de `finally` no es un cleanup pad LLVM y, por la frontera
no-throwing, no necesita modelar double-unwind. Los traps siguen ramificando a
sus bloques fail-fast y no adquieren garantía de pasar por `finally`.

## Qualification y corrupciones

La suite `exception_v4` y el fixture `exception_v4_smoke.ae` cubren en O0 y O2:

- fallthrough y handler completado normalmente;
- excepción unmatched que atraviesa `finally` y llega a un catch exterior;
- `return` desde `try` y desde `catch`;
- `break` y `continue` desde un `try` dentro de un loop;
- finalizers anidados y orden interior-exterior;
- ejecución exactamente una vez mediante efectos escalares observables;
- cleanup exacto de owners `Buffer`/clase con contadores runtime;
- preservación del evento sin reconstrucción del payload;
- traps fail-fast sin garantía de `finally`;
- rechazo de control saliente, throw bare/expreso y llamadas en `finally`.

Las corrupciones independientes duplican un `FinallyId` en HIR, omiten un
marcador de salida en MIR y reordenan los cases de dispatch en SSA. Cada
verificador rechaza su corrupción antes de que alcance la fase siguiente.

La suite completa mantiene verdes EXCEPTION-V1, V2 y V3, además del resto del
workspace. La salida nativa y los contadores se califican tanto con O0 como con
O2.

## Deuda y límites restantes

Además del slot de retorno owning/agregado pendiente, permanecen fuera de
scope: `try`/`catch` local dentro de `init` mientras aplique `E0436`, llamadas
indirectas arbitrarias, destructores de usuario, async/threads, FFI, filtros de
excepción, mensajes/stack traces, suppressed exceptions y conversión de traps
en excepciones. Permitir código potencialmente throwing dentro de `finally`
requiere diseñar double-unwind explícito y no forma parte de EXCEPTION-V4.
