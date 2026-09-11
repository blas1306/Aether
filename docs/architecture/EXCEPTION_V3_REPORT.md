# EXCEPTION-V3 — virtual and interface unwind

## Estado

EXCEPTION-V3 elimina `E0437` para llamadas virtuales de clase y llamadas de
interface cuando el programa declara una jerarquía de excepciones. Ambos tipos
de dispatch pueden lanzar, propagar a un `catch` exterior y ejecutar el cleanup
del caller antes de transferir el `ExceptionEvent`.

El milestone no incorpora `finally`, llamadas indirectas arbitrarias,
`try`/`catch` local dentro de `init`, destructores de usuario, async/threads,
FFI, excepciones genéricas, mensajes/stack traces ni conversión de traps.

## Virtual invoke unwind

`VirtualCall` conserva el `ClassId`, `VirtualSlotId` y método de referencia que
fueron verificados en HIR. MIR lo clasifica como operación potencialmente
lanzadora y le exige un successor `unwind` cuando existe una clase raíz de
excepción. El normal successor produce el resultado; el unwind successor entra
en el cleanup excepcional del caller y continúa hacia el handler exterior.

El dispatch indirecto continúa cargando el target desde el descriptor y el slot
virtual. Una instancia derivada observada mediante un tipo base conserva, por
tanto, el override dinámico también cuando ese override lanza.

## Interface invoke unwind

`InterfaceCall` conserva el `RequirementId` completo —incluido su
`InterfaceId`— y el slot de witness validado. MIR y SSA le asignan el mismo
contrato normal/unwind de una llamada virtual. El backend obtiene el target del
witness correspondiente y usa ese target para el invoke indirecto. Esto cubre
conformances heredadas y overrides de clases derivadas sin reconstruir ni
adivinar la identidad del requirement durante el lowering.

## Orden de evaluación, keepalive y ownership

El lowering de las llamadas de método materializa primero el receiver y luego
evalúa los argumentos de izquierda a derecha. El owner temporal del receiver se
registra antes de empezar los argumentos, de modo que permanece vivo si la
evaluación de un argumento lanza, durante la llamada y en ambos successors.

Al entrar en el invoke, los argumentos owning ya fueron transferidos al callee:
se consumen exactamente una vez tanto en retorno normal como en unwind y el
caller no vuelve a liberarlos. El receiver owning sigue siendo responsabilidad
del caller y se libera una vez en el camino normal o una vez en el pad de
cleanup excepcional. Los owners anteriores del caller se limpian antes de
propagar al handler.

El valor resultante se define únicamente en el normal edge. El
`ExceptionEvent` se materializa únicamente en el landing pad del unwind edge;
no existe una sustitución, phi o valor ficticio que mezcle ambos resultados.

## HIR, MIR y SSA

- HIR mantiene `VirtualCall`/`InterfaceCall` como operaciones de dispatch con
  sus identidades exactas. Sus verificadores existentes rechazan slots,
  métodos, requirements, witnesses y receivers incoherentes.
- MIR convierte las operaciones en invokes potencialmente lanzadores, adjunta
  un unwind edge explícito y construye el cleanup con el ledger de owners. El
  verificador rechaza edges ausentes o espurios, receivers no materializados,
  cleanup del receiver ausente/duplicado y drops espurios de argumentos ya
  consumidos.
- SSA preserva las identidades del dispatch y el unwind edge. Sus verificadores
  de CFG, dominancia, landing pads y ownership rechazan results/events en el
  edge incorrecto y cleanup incompleto.

Además se corrigió la actualización de drop flags durante el reemplazo atómico
de una referencia de clase: el destino queda desarmado al extraer el valor
anterior y vuelve a quedar armado inmediatamente después del move nuevo. Esto
mantiene consistente el ledger cuando la operación siguiente abre bloques de
unwind.

## LLVM EH y devirtualización

LLVM EH continúa siendo transporte físico. Un dispatch dinámico con unwind se
emite como `invoke` indirecto hacia el target leído del descriptor o witness;
su destino excepcional es el landing pad ya decidido por SSA.

En O2, OOP-OPT puede reemplazar físicamente el target por una función directa
solo cuando la proveniencia exacta lo autoriza. EXCEPTION-V3 conserva el
`invoke`, el normal successor y el unwind successor en esa transformación. Una
proveniencia unknown o mixed conserva el dispatch indirecto y la misma
propagación excepcional.

## Qualification y corrupciones

La suite `exception_v3` cubre en O0 y O2:

- virtual exacta que lanza y es capturada;
- llamada por base cuyo override dinámico derivado lanza;
- interface call y conformance heredada con override que lanza;
- receiver temporal, argumento owning y owners previos liberados exactamente
  una vez, incluso si un argumento posterior lanza antes del dispatch;
- resultado owning inexistente en unwind;
- virtual invoke dentro de `init` compuesto con el rollback de EXCEPTION-V2;
- devirtualización exacta que sigue propagando;
- proveniencia unknown/mixed de clase e interface que permanece indirecta;
- fixture diferencial `exception_v3_smoke.ae`.

Las corrupciones negativas eliminan el unwind de MIR/SSA, eliminan el cleanup
del receiver, alteran el `RequirementId` y quitan el landing pad que define el
evento. Todas deben ser rechazadas. Las corrupciones HIR de OOP-V2/V3 siguen
ejercitando independientemente `VirtualSlotId`, método, `RequirementId`, slot de
witness y receiver inválidos.

## Compatibilidad y deuda restante

EXCEPTION-V1/V2 mantienen su modelo de catch, propagación, cleanup y rollback de
constructores. Los milestones OOP-V1/V2/V3 y OOP-OPT conservan layout, dispatch,
ownership y reglas de proveniencia. `E0436` continúa rechazando `try`/`catch`
local dentro de `init`; `E0437` deja de usarse únicamente para los dos dispatch
implementados aquí.

Quedan fuera de scope los puntos enumerados al inicio, en particular `finally`
y cualquier forma de llamada indirecta que necesite una representación de
firma/ownership adicional. Tampoco se atribuye semántica de excepción a traps
del runtime.
