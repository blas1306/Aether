# FIRST-CLASS-CLOSURES-ARCH-1 — reporte de cierre

Estado: **CLOSED; ARQUITECTURA ACEPTADA; IMPLEMENTACIÓN NO INICIADA**,
2026-11-01.

Documento normativo:
[FIRST-CLASS-CLOSURES-ARCH-1](FIRST_CLASS_CLOSURES_ARCH_1.md).
Enmienda normativa vigente:
[ABI Scope Amendment](FIRST_CLASS_CLOSURES_ARCH_1_ABI_SCOPE_AMENDMENT.md).

## Resultado

La arquitectura separa dos verticales independientes. Una arrow lambda sin
capturas baja a una función sintética y conserva exactamente `FunctionRef`,
`Function` e `IndirectCall`. Una lambda capturante produce
`Closure<(Args), Return>`, owner ARC no-Copy, Relocatable, Storable y
drop-needing que apunta a un box con environment read-only. Aunque ambos
carriers ocupen un pointer, uno apunta a código y el otro a un object; no son
ABI-intercambiables y no existe conversión implícita.

La sintaxis aceptada usa parámetros tipados y body de una expresión:

```aether
var square = (double x) => x * x;
var f = (double x) capture(copy a, alias label, move data) =>
    evaluate(x, a, label, data);
```

`capture(...)` es opcional y parcial. No se introducen `@(...)`, `fn`, `let` ni
declaraciones nuevas; `var` es la inferencia local elegida.

## Política y semántica cerradas

- Un free variable `Copy + Storable` se captura automáticamente por Copy como
  snapshot.
- Un owner con Alias intrínseco calificado se captura automáticamente por Alias
  como owner independiente que comparte identidad, no mediante deep copy.
- Un owner Move-only sin Alias exige `capture(move name)`; nunca hay Move
  implícito.
- No se infieren Clone/deep copy ni Alias desde `Storable`.
- `ref`, `ref mut`, views, captura mutable, partial moves y consumo de captures
  se rechazan en V1.
- Una entrada explícita prevalece para su nombre, pero debe ser una operación
  válida. Duplicados, símbolos inválidos y modes incompatibles son errores.
  Una entrada explícita válida no usada produce warning y conserva adquisición
  y cleanup.
- Free variables y shadowing se resuelven léxicamente. Captures explícitos se
  ordenan como fueron escritos; los implícitos siguen el primer uso source.
  Adquisición es izquierda-a-derecha y destrucción inversa.
- El box no se publica hasta completar la creación. Un fallo recuperable limpia
  el prefijo inicializado en orden inverso; roots ya movidos permanecen moved.
  Traps abortivos vigentes no prometen cleanup.
- No existe self-capture mágico: el binding de un initializer no está en scope
  dentro de él. Lambdas anidadas tienen environments propios y propagación
  transitiva de free variables; no pueden mover desde captures read-only.
- Invocation es repetible y no consume el box. El último release destruye cada
  capture exactamente una vez. Read-only se aplica a los slots, no promete
  deep immutability de objetos compartidos mediante Alias.

## ABI y ownership

`ClosureABI-v1` fija un header de tres words: `strong_count`, `invoke_thunk` y
`destroy_thunk`, en offsets `0`, `W` y `2W`. El payload privado comienza en
`align_up(3W, payload_alignment)`; allocation size/alignment se calculan con el
data layout del target y overflow checked. El count es non-atomic, empieza en
uno y no hay weak owners.

El invoke thunk usa Aether ABI v1 con `ptr box` como primer argumento oculto y
puede unwind. El destroy thunk es `void(ptr box)`, `nounwind`, destruye captures
en orden inverso y libera el allocation. Ownership entre módulos/packages
fuente usa los helpers
runtime versionados `aether_closure_retain_v1` y
`aether_closure_release_v1`.

La identidad de glue incluye package, module, `LambdaId`, generic instance y
versión ABI. En V1, todas las fuentes transitivas se compilan con un único
target/data layout y se emiten en un único módulo LLVM. No hay registry, RTTI,
TLS trampoline ni adaptación heurística.

Metadata persistida de target, data-layout fingerprint, Aether ABI y compiler
ABI epoch, así como rechazo de combinaciones incompatibles entre productor y
consumidor compilados independientemente, quedan en
`COMPILED-ARTIFACT-ABI`. V1 no promete bibliotecas Aether precompiladas.

## Verticales y qualification

### `ANONYMOUS-FUNCTIONS-V1`

Incluye arrow syntax, parámetros tipados, expression body, clasificación
`Function`, synthetic identity/reachability y el spine existente de
`FunctionRef`/`IndirectCall`. Debe calificarse por separado en O0/O2 y unwind,
incluidos negativos de free variables/shadowing y corrupción HIR/MIR/SSA que
intente convertirlo en Closure. No agrega runtime y conserva todos los gates de
storage/reference de Function.

### `OWNING-CLOSURES-READ-V1`

Incluye captura automática Copy/Alias, captura explícita Copy/Alias/Move,
mezclas parciales, análisis léxico, orden y rollback deterministas, nested
lambdas/callbacks, lifecycle ARC y repeated read invocation. Debe cubrir:

- duplicados, mode inválido, shadowing, capture no usada y Move-only sin
  `capture(move ...)`;
- snapshots Copy, owners Alias, invalidación Move y prohibiciones de references,
  mutation y partial move;
- assignment/replacement, arguments, return, closures nunca invocadas y
  callbacks escapables;
- cleanup normal, early return, conditional paths, throw/catch/finally y unwind;
- offsets/alignment, thunks, identidad entre módulos fuente y counters exactos
  alloc/free/retain/release/drop;
- corrupción independiente de capture set/order/mode/source en HIR, MIR y SSA,
  owner tokens, borrow/`EndBorrow`, recipes de destroy y event identity;
- paridad O0/O2 y ausencia de UAF, leaks, double free, TLS/global trampolines o
  conversiones `Closure`/`Function`.

Los dos verticales mantienen qualification y aceptación independientes. Abrir
storage en struct/class fields, enum payloads o `Array`/`List` queda para
milestones dedicados; class fields requieren además política explícita de
ciclos ARC. References/views y closures mutable/consuming/borrowed siguen fuera.

Los positivos entre módulos y packages califican interoperabilidad de fuentes
compiladas en una misma `CompilationSession`, no compatibilidad entre artefactos
binarios. V1 debe cubrir paso y retorno cross-function, cross-source-module y
cross-source-package, helpers y reachability en el módulo LLVM único. Tests
productor/consumidor de compilaciones independientes, metadata epoch/fingerprint
y rechazo pre-link son gates diferidos, no PASS.

## Riesgos y restricciones

Los riesgos aceptados son confusión entre carriers de un pointer, pérdida o
duplicación de owners, cleanup parcial/unwind incorrecto, cycles futuros,
inestabilidad ABI y optimizaciones que eliminen keepalive. Se contienen con
tipos y operaciones distintas, metadata de captures ya resuelta antes de HIR,
owner ledgers/verificadores por fase, ABI versionada, storage gates e inspección
O0/O2 con counters.

El environment read-only no hace inmutables en profundidad los objetos
compartidos por Alias. ARC non-atomic conserva el modelo runtime actual. La
arquitectura no promete zero-cost: O2 sólo puede eliminar box/ARC o devirtualizar
con pruebas completas de provenance y escape.

No se agregan mecanismos especiales para Plots, Newton, integración ni otros
métodos numéricos. APIs que aceptan `Function` reciben lambdas sin captura;
aceptar closures capturantes requerirá en el futuro overload o adapter explícito.

## Alcance de esta enmienda

La revisión ABI posterior confirmó que el bloqueo por compilación separada no
era una dependencia real del ABI interno. `CompilationSession` reúne fuentes
transitivas, el pipeline produce un único HIR/MIR/SSA y `LlvmTextBackend` emite
un único módulo para un target. Por ello header, thunks, helpers, ownership,
return y unwind pueden implementarse y calificarse íntegramente en el modelo
actual.

Se actualizaron sólo documentos de arquitectura y reportes. No se modificaron
compiler, runtime, libraries, tests, Plots, métodos numéricos ni ejemplos
personales. No se inició implementación. La arquitectura permanece **CLOSED**;
los verticales aún no están implementados ni qualified.
