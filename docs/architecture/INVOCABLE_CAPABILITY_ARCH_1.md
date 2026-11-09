# Aether — INVOCABLE-CAPABILITY-ARCH-1

Estado: **ARCHITECTURE CLOSED; M0/M1/M2/M3/M4 CLOSED; V1 CLOSED**, 2026-11-09.

Este documento define la arquitectura normativa de `INVOCABLE-CAPABILITY-V1`.
La implementación quedó admitida tras cerrar los gates de la sección 18, sin
cambios de ABI, runtime o bibliotecas.

## 1. Decisión

Aether incorpora una capability estructural, sellada por el compilador y
parametrizada por una firma exacta:

```aether
Invocable<(P1, P2, ...), R>
```

`Invocable`:

- sólo puede aparecer como constraint de un parámetro generic;
- no es un tipo de valor, un trait, una interface ni un constructor genérico;
- autoriza invocación read-only, repetible y de firma exacta;
- tiene únicamente dos satisfiers en V1: `Function<(P...),R>` y
  `Closure<(P...),R>`;
- no convierte un carrier en el otro y no introduce adapter, allocation, thunk,
  witness, vtable, ABI o helper de runtime;
- no implica `Copy`, `Relocatable`, `Storable`, `Alias`, `Clone` ni una política
  uniforme de Drop.

El primer vertical recibe `C` por valor. Invocar a través de `ref C`,
`Callable`, `CallableRef`, storage erased y migración de APIs quedan fuera.

## 2. Autoridades comprobadas

Esta arquitectura cierra las decisiones abiertas de
`FIRST_CLASS_CALLABLES_EXPLORATION.md` y su report, y conserva los contratos de:

- `FUNCTION_VALUES_ARCH_1.md`, `FUNCTION_VALUES_V1_REPORT.md` y
  `ANONYMOUS_FUNCTIONS_V1_REPORT.md`;
- `FIRST_CLASS_CLOSURES_ARCH_1.md`, capture analysis, ownership IR,
  `OWNING_CLOSURES_READ_V1_REPORT.md` y `CLOSURE_LLVM_RUNTIME_V1_REPORT.md`;
- generic constraints, inferencia y monomorfización actuales;
- ownership de parámetros by-value, root moves y cleanup en early return;
- `EXCEPTION-ARCH-2` y EXCEPTION-V1..V4.

La inspección del código vigente confirmó:

| Contrato | Estado real relevante |
|---|---|
| constraints | `AstCapabilityConstraint` sólo guarda un nombre; `Capability` es un enum atómico `Copy`; `GenericParamInfo` usa `BTreeSet<Capability>` |
| tipos | `TypeData::Function` y `TypeData::Closure` son identidades canónicas distintas por firma |
| sustitución | sustituye recursivamente parámetros y resultado de Function/Closure |
| HIR generic | conserva operaciones proof-carrying para capabilities numéricas |
| monomorfización | valida arguments, sustituye y produce HIR concreto antes de MIR |
| MIR | rechaza tipos generic residuales |
| Function call | `FunctionRef` / `IndirectCall`, may-unwind |
| Closure call | `ClosureBorrow` / `ClosureCall` / `EndClosureBorrow`, may-unwind y sin ARC por invocation |
| exceptions | `CallSiteId` identifica la call en HIR; MIR crea y transporta `ExceptionEventId` |

Por ello `Invocable` necesita un requirement parametrizado separado. Añadirlo
como un valor de `Capability` sin firma o fingir un `TypeData` sería incorrecto.

## 3. Gramática normativa

La extensión exacta es:

```text
generic_parameters       := "<" generic_parameter
                            ("," generic_parameter)* ">"

generic_parameter        := identifier
                            (":" generic_constraint
                            ("+" generic_constraint)*)?

generic_constraint       := atomic_constraint
                          | invocable_constraint

atomic_constraint        := identifier

invocable_constraint     := "Invocable" "<"
                            callable_parameter_tuple "," type ">"

callable_parameter_tuple := "(" callable_parameter_types? ")"

callable_parameter_types := type ("," type)*
```

`callable_parameter_tuple` es la misma forma sintáctica usada por
`Function` y `Closure`: los paréntesis son obligatorios para cero, uno o varios
parámetros. No se admite `Invocable<P,R>`, `Invocable<P...>`, un retorno omitido
ni parámetros de valor dentro de la tupla.

Ejemplos:

```aether
R apply<P, R, C: Invocable<(P), R>>(C f, P x) {
    return f(x);
}

void fire<C: Invocable<(), void>>(C f) {
    f();
}

R fold2<A, B, R, C: Invocable<(A, B), R> + Storable>(
    C f, A a, B b
) {
    return f(a, b);
}
```

El ejemplo abreviado `R apply<C: Invocable<(P), R>>(...)` sólo es válido si
`P` y `R` ya están en un scope generic exterior. En una declaración top-level
deben declararse, como en el primer ejemplo. `Invocable` no introduce binders
implícitos.

### 3.1 Restricción de contexto

El parser reconoce esta forma únicamente después de `:` o `+` dentro de un
binder generic. En cualquier posición de tipo se diagnostica que `Invocable`
es una constraint y no un tipo. Se rechazan, entre otros:

```aether
Invocable<(int), int> value;
Array<Invocable<(int), int>> values;
Invocable<(int), int> make();
```

Aliases de tipos sí se permiten dentro de la firma. Un alias de constraint que
expanda a `Invocable` no se incorpora en V1; los aliases agregados existentes
(`RingOps`, `FieldOps`, `RealOps`) siguen siendo exclusivamente atómicos.

## 4. Modelo tipado de requirements

La arquitectura separa tres conceptos:

```text
AtomicCapability
    = el Capability cerrado vigente

CallableSignature {
    parameters: TypeArgsId,
    result: TypeId,
}

GenericRequirement {
    Atomic(AtomicCapability),
    Invocable(CallableSignatureId),
}
```

`CallableSignatureId` pertenece a una tabla canónica de firmas de constraint en
el frontend. Su clave es el vector ordenado de `TypeId` de parámetros más el
`TypeId` de resultado. Puede reutilizar el interning de listas de tipos de
`TypeArena`, pero **no** agrega `TypeData::Invocable`, no obtiene layout y no
puede llegar a una posición de valor.

Los `TypeId` de la firma pueden ser concretos o `GenericParam` del owner de la
declaración. Los aliases transparentes se resuelven antes de internar; spelling
y spans se conservan sólo como metadata diagnóstica. Por tanto:

```aether
alias Scalar = float64;
Invocable<(Scalar), Scalar>
Invocable<(float64), float64>
```

representan el mismo requirement canónico.

### 4.1 Metadata de un binder

`GenericParamInfo` deja de modelar todas sus obligaciones como un único
`BTreeSet<Capability>` y conserva:

```text
GenericParamInfo {
    id: GenericParamId,
    ...,
    declared_constraints: [GenericConstraintSpelling],
    atomic_capabilities: BTreeSet<AtomicCapability>,
    requirements: [GenericRequirementId],
}
```

Cada requirement resuelto recibe una evidencia declaration-owned:

```text
ConstraintEvidence {
    id: ConstraintEvidenceId,
    owner: FunctionId | nominal generic owner,
    parameter: GenericParamId,
    requirement: GenericRequirementId,
    declaration_ordinal: u32,
    span: Span,
}
```

La identidad de evidencia no se deriva del spelling ni de un `TypeId`. Impide
que una operación del body tome por accidente la constraint de otro binder o
de otra declaración con la misma firma.

### 4.2 Varias constraints

`+` conserva semántica conjuntiva. Son válidos:

```aether
C: Invocable<(int), int> + Storable
C: Relocatable + Invocable<(), void>
```

Un mismo requirement, incluso escrito mediante aliases de tipos, se rechaza
como duplicado. Dos requirements `Invocable` de firmas distintas sobre el mismo
binder también se rechazan: con los dos satisfiers estructurales de V1 la
intersección es vacía, porque cada `Function` o `Closure` tiene una sola firma.
No se introduce overloadability de un valor generic.

Constraints de parámetros callable independientes conservan evidencia
independiente:

```aether
R choose<A, R,
    F: Invocable<(A), R>,
    G: Invocable<(A), R>
>(F first, G second, A value) { ... }
```

## 5. Formación y firma exacta

Una firma de requirement está bien formada si:

1. cada tipo resuelve en el scope de la declaración;
2. ningún parámetro ni el resultado contiene un tipo incompleto;
3. `void` sólo aparece como resultado, nunca como parámetro;
4. las reglas ordinarias de referencias/views dentro de firmas siguen vigentes;
5. todos los `GenericParamId` pertenecen a un binder visible;
6. después de aliases, la lista y el resultado tienen identidades canónicas.

V1 es invariante. Igualdad de firma significa misma aridad y el mismo `TypeId`
en cada posición y resultado después de sustitución. No hay widening numérico,
subtyping, covariance, contravariance, defaults, overload adaptation ni
conversión de retorno.

Los parámetros cero, uno y varios son respectivamente:

```aether
Invocable<(), R>
Invocable<(P), R>
Invocable<(P, Q, S), R>
```

El resultado `void` es `TypeId::VOID`; una invocation se usa como statement y
produce el valor HIR unit/void ordinario, sin storage.

## 6. Sustitución

La sustitución de una instancia se aplica tanto a signatures de funciones como
a requirements:

```text
substitute(Invocable<(P...), R>, S)
    = Invocable<(substitute(P, S)...), substitute(R, S)>
```

El resultado se reinterna como `CallableSignatureId` canónico. No se muta la
evidencia de la declaración: la instancia conserva el par
`(ConstraintEvidenceId, substituted requirement)` para auditoría.

La sustitución debe fallar cerrada ante binder ausente, tipo inválido,
`void` en parámetro o requirement que todavía contenga un generic no resuelto
al cruzar hacia HIR concreto.

## 7. Satisfaction

### 7.1 Tipos concretos

Para una firma canónica `S = (P...) -> R`:

```text
satisfies(Function<S>, Invocable<S>) = true
satisfies(Closure<S>,  Invocable<S>) = true
```

Todo otro caso es false, incluida cualquier diferencia de firma. No se consulta
layout, `TypeProperties`, métodos llamados `call`, conformances nominales ni el
tipo dinámico de un objeto.

No satisfacen V1:

- classes, interfaces, structs o enums;
- `Callable`/`CallableRef` futuros;
- references a Function/Closure;
- nullable callable;
- closures mutable, consuming u once futuras;
- un Function o Closure de firma convertible pero no idéntica.

### 7.2 Tipos simbólicos

Un argumento generic simbólico `D` satisface el requirement de `C` sólo si el
binder de `D` ofrece un requirement `Invocable` canónicamente idéntico después
de sustituir los parámetros visibles. No basta `Storable`, `Copy` ni que alguna
instanciación conocida de `D` sea callable.

La implication lattice atómica no cambia. En particular:

```text
Invocable !-> Copy
Invocable !-> Relocatable
Invocable !-> Storable
Copy       !-> Invocable
Storable   !-> Invocable
```

### 7.3 Diagnósticos

Los errores deben identificar:

- parámetro generic y declaración que exigen la capability;
- firma requerida y firma real si el argumento es Function/Closure;
- primera posición incompatible, o aridad/resultado;
- si el argumento fue explícito o inferido;
- spelling source útil sin usarlo como autoridad.

Un no-callable reporta “no satisface `Invocable<...>`”; un callable de otra
firma reporta “signature mismatch”, no una ausencia genérica de capability.

## 8. Inferencia de llamadas generic

La inferencia continúa siendo local a la call y exacta. Se ejecuta en dos
etapas hasta un punto fijo finito:

1. la unificación ordinaria de parámetros y argumentos infiere el tipo completo
   de `C` y cualquier parámetro visible en posiciones ordinarias;
2. si `C` quedó ligado a Function/Closure, se descompone su firma y se unifica
   exactamente con la firma requerida sustituida, pudiendo inferir parámetros
   todavía libres que aparezcan en ella.

Ejemplo:

```aether
R apply<P, R, C: Invocable<(P), R>>(C f, P x) { return f(x); }
```

`f` infiere `C`; su firma y `x` infieren o confirman `P`; el resultado de la
firma infiere `R`. Dos fuentes incompatibles producen conflicto, no una
conversión. Un resultado contextual puede participar sólo según las reglas
contextuales generales ya admitidas; `Invocable` no inventa una inferencia
global o bidireccional nueva.

Después de inferir todos los type arguments se sustituye y valida satisfaction.
La selección de overload no puede aceptar provisionalmente una firma que
requiera widening. Errores internos de un candidato se conservan como rechazo
de ese candidato según el contrato actual, con diagnóstico final determinista.

## 9. Contrato del body generic

El body se valida una vez contra sus requirements, antes de conocer una
instanciación. La especialización no puede legalizar una operación que el body
generic no tenía autorizada.

Con sólo `C: Invocable<(P...),R>` se permite:

- recibir y conservar el parámetro by-value como una obligación root;
- invocarlo cero o más veces con argumentos de tipos exactos;
- transferir el root completo una vez a otra frontera by-value;
- retornarlo como `C` mediante transferencia;
- dejar que termine su scope, generando cleanup simbólico;
- usar operaciones otorgadas por constraints adicionales.

No se permite por `Invocable` solamente:

- copiar o duplicar `C`;
- crear Alias/retain/Clone;
- guardar `C` en Array/List/field/payload u otra posición que exija Storable;
- asumir Relocatable para una operación que lo exija;
- igualdad, orden, aritmética o conversión;
- invocación a través de `ref C`;
- mutar o consumir el carrier durante invocation.

### 9.1 Lectura e invocation

`f(args)` donde `f: C` no es una lectura by-value de `f`. Es una
`CapabilityInvoke` en modo `RepeatableRead` que abre la observación necesaria
del carrier y deja vivo el root. Por eso son válidas dos invocaciones seguidas
sin exigir `Copy` o `Alias`.

Una lectura ordinaria de `f` en un contexto de valor sigue las reglas de
ownership. `C other = f` no puede elegir entre copia de Function y Alias de
Closure mientras el body es simbólico, así que se rechaza sin `Copy` o una
operación de transferencia explícita ya admitida por el lenguaje.

### 9.2 Transfer, return y assignment

- Pasar o retornar el root `C` por valor puede transferir su única obligación;
  el source queda `Moved` y no se limpia allí.
- Un `return f;` es válido y transfiere el parámetro; no borra su kind concreto.
- Invocar antes del return es válido; invocar, leer o retornar después del move
  es use-after-move.
- Inicializar otro root mediante transferencia explícita es válido. Una simple
  lectura lvalue no se reinterpreta como transferencia implícita.
- Reemplazar un target ya inicializado sólo es válido si la forma source provee
  una adquisición autorizada del RHS y el ownership checker puede representar
  cleanup del valor anterior. `Invocable` por sí sola no autoriza adquirir un
  segundo owner desde un lvalue.
- `C: Copy + Invocable<...>` permite las copias ordinarias. En V1 eso deja como
  satisfier concreto posible a Function, pero la conclusión viene de `Copy`,
  no de `Invocable`.

La arquitectura no agrega un spelling nuevo de `Move`; usa el contrato de
whole-root transfer vigente. Cualquier cambio general de sintaxis de Move es
otro milestone.

### 9.3 Lvalues y fresh owners

Para invocar un lvalue se observa su root estable. Para invocar una expresión
fresh de tipo `C`, el frontend materializa un temporary owner, lo invoca y
termina su obligación después de la call en success o unwind. Esa
materialización no copia ni aliasa el valor.

En el primer vertical, el caso obligatorio es el parámetro by-value. Fresh
generic callees deben calificarse si la gramática de expresiones permite
producirlos; no pueden implementarse consumiendo directamente la expresión.

### 9.4 Cleanup simbólico

`C: Invocable` no tiene `TypeProperties` uniformes: Function no necesita Drop y
Closure sí. El generic HIR debe conservar una obligación de owner root
**condicional a la especialización**. Conceptualmente:

```text
GenericOwnerObligation {
    root: LocalId,
    type: TypeId(GenericParam),
    state: Owned | Moved | MaybeMoved,
    source: ParameterByValue | Temporary | Local,
}
```

Cada salida normal, early return y exceptional edge contiene el cleanup
simbólico correspondiente. Al especializar:

- Function elimina el drop porque su tipo concreto es Copy/no-drop;
- Closure produce exactamente un `ClosureDrop`/release si la obligación sigue
  viva;
- un root transferido no se limpia en el source.

No se permite que `TypeProperties::is_known == false` se interprete como
`needs_drop == false`. Este cambio es una dependencia del vertical y evita que
una Closure instanciada se filtre aunque el body generic no la invoque.

## 10. `CapabilityInvoke` en HIR generic

La operación normativa es:

```text
CapabilityInvoke {
    callee: HirExprOrPlace,
    callee_type: TypeId,                 // C, no la firma carrier inventada
    arguments: [HirExpr],
    result_type: TypeId,
    requirement: GenericRequirementId,
    evidence: ConstraintEvidenceId,
    required_signature: CallableSignatureId,
    satisfaction: SatisfactionEvidence,
    mode: RepeatableRead,
    effect: MayUnwind,
    call_site: CallSiteId,
    provenance: SourceSpan,
}
```

`SatisfactionEvidence` en HIR generic enlaza el binder, requirement y firma; no
afirma todavía Function o Closure. Después de sustitución añade el concrete
`TypeId` y el kind comprobado.

`call_site` es la identidad lógica del evento excepcional en HIR. La reescritura
no asigna otro site ni duplica la call. Al bajar a MIR se crea exactamente un
`ExceptionEventId` para ese site, como en las calls actuales, y el mismo event
fluye por landing pad, cleanup, catch/resume y `finally`. `MayUnwind` nunca se
rebaja por ser una capability.

### 10.1 Verificación de HIR generic

El verifier, independiente del analyzer, exige:

1. evidencia existente y perteneciente a la declaración actual;
2. `evidence.parameter` igual al generic param de `callee_type`;
3. requirement `Invocable`, no una capability atómica;
4. identidad exacta entre requirement y `required_signature`;
5. aridad, argumentos y resultado exactos;
6. modo exactamente `RepeatableRead` en V1;
7. `MayUnwind`, `CallSiteId` único y provenance válido;
8. callee vivo y no moved;
9. ninguna inferencia de Copy/Alias/Storage desde la operación.

## 11. Especialización y rewriting

Por cada instancia, el monomorphizer debe ejecutar en orden:

1. validar type arguments y todos sus requirements;
2. sustituir tipos del body y de la firma requerida;
3. volver a comprobar satisfaction exacta;
4. verificar la evidencia contra binder, requirement sustituido y callee;
5. reescribir `CapabilityInvoke` según el `TypeData` concreto;
6. resolver cleanup simbólico según lifecycle concreto;
7. verificar HIR concreto completo;
8. rechazar cualquier generic param, evidencia abierta o
   `CapabilityInvoke` residual antes de MIR.

### 11.1 Function

```text
CapabilityInvoke(callee Function<S>, args, S)
    -> IndirectCall {
         callee, args,
         signature: TypeId::Function<S>,
         call_site: original,
       }
```

El carrier sigue siendo un code pointer. No se transforma en direct call salvo
una optimización posterior con prueba ordinaria. La call conserva may-unwind.

### 11.2 Closure

```text
CapabilityInvoke(callee Closure<S>, args, S)
    -> ClosureBorrow(call_site, carrier, Closure<S>)
       ClosureCall(call_site, carrier, token, args, Closure<S>)
       EndClosureBorrow(call_site, carrier, token)
```

`EndClosureBorrow` ocurre en success y unwind conforme al spine vigente. La
invocation no hace retain/release. El token no escapa y el carrier no puede
moverse, reemplazarse o dropearse hasta cerrar el borrow.

## 12. Frontera by-value y ownership concreto

La adaptación del argumento ocurre en el call site después de inferir `C`:

| Argumento concreto | Entrada by-value | Durante invocation | Salida si sigue vivo |
|---|---|---|---|
| Function lvalue/fresh | copia de code pointer | `IndirectCall` | sin drop |
| Closure fresh | Transfer del owner | borrow + call + end borrow | release del parámetro |
| Closure lvalue | `ClosureAlias` + retain | borrow + call + end borrow | release del parámetro |
| explicit Move de Closure | Transfer e invalida source | borrow + call + end borrow | release del parámetro |

El root ownership verifier debe demostrar una adquisición y un cleanup o
transfer exactos por salida. Early return y exception limpian el parámetro
Closure si está vivo. Si el body retorna `C`, el owner pasa al caller y no hay
release en el callee. Function mantiene su semántica Copy.

Que Closure lvalue pueda formar un owner mediante su operación intrínseca no
convierte `Alias` en una garantía del body generic. Es adaptación de un call
site ya concreto.

## 13. Exceptions

Ambos dispatch spines son conservadoramente may-unwind. Las reglas son:

- argumentos se evalúan en el orden source ordinario;
- owners ya materializados se limpian si un argumento posterior o la call
  lanza;
- Closure mantiene su borrow hasta el cleanup excepcional de la invocation;
- `EndClosureBorrow` precede al release del parámetro/temporary;
- el `ExceptionEvent` original no se sustituye, envuelve ni descarta;
- cleanup y destroy thunks continúan nounwind; una violación es corrupción;
- traps abortivos no se convierten en exceptions.

La especialización no puede crear dos events, cambiar el `CallSiteId`, convertir
may-unwind en nounwind ni reconducir el edge a otro landing pad.

## 14. MIR, SSA, LLVM y ABI

MIR rechaza categóricamente:

- `CapabilityInvoke`;
- `ConstraintEvidenceId` o `GenericRequirementId` operativos;
- `GenericParam` residual en signatures, locals u operands;
- una call cuyo kind no corresponda al `TypeData` del carrier.

MIR y SSA reutilizan y verifican sólo `IndirectCall` o la familia Closure. LLVM
no recibe un opcode generic, un witness ni metadata que pueda decidir dispatch.
No se modifica:

- Function ABI de un pointer;
- `ClosureABI-v1` ni su header de tres words;
- helpers `aether_closure_retain_v1` / `release_v1`;
- prototypes de invoke/destroy thunk;
- ABI de exceptions o unwinding.

No hay allocation de adaptación ni adapter thunk. Esto no promete ausencia de
la allocation intrínseca de una Closure, ni de ARC al cruzar by-value con un
lvalue, ni de indirect dispatch.

## 15. Verificación y corruption tests

Se requieren pruebas negativas que muten independientemente:

| Corrupción | Verifier que debe rechazarla |
|---|---|
| evidence inexistente o de otra función | generic HIR |
| evidence de otro binder con igual firma | generic HIR |
| requirement atómico presentado como Invocable | generic HIR |
| firma requerida adulterada | generic HIR y specialization |
| callee type distinto del binder | generic HIR |
| aridad, argumento o resultado adulterado | generic HIR |
| mode distinto de RepeatableRead | generic HIR |
| may-unwind/event/site eliminado o cambiado | HIR/MIR/SSA exception verifiers |
| Function reescrito como ClosureCall | concrete HIR/MIR/SSA |
| Closure reescrito como IndirectCall | concrete HIR/MIR/SSA |
| missing/duplicate EndClosureBorrow | MIR/SSA borrow verifiers |
| carrier moved/dropped dentro del borrow | ownership + MIR/SSA |
| cleanup Closure omitido en success/return/unwind | ownership/MIR/SSA |
| drop Function inventado | concrete ownership verifier |
| CapabilityInvoke residual | HIR→MIR boundary |
| generic/evidence residual en MIR o SSA | phase verifier |

Las pruebas deben construir IR corrupto directamente; no basta comprobar que el
parser no lo emite.

## 16. Qualification normativa

Todos los ejecutables se califican en O0 y O2, con dumps HIR generic, HIR
concreto, MIR y SSA cuando corresponda.

| Área | Casos mínimos |
|---|---|
| Function | top-level; lambda sin captura; cero/uno/múltiples parámetros; void |
| Closure Copy | captura Copy e invocation repetida |
| Closure Alias | captura Alias, contadores ARC y cleanup |
| Closure Move | captura Move, transferencia y destrucción exacta |
| firma generic | `Invocable<(T),T>` y tipos distintos por instancia |
| varios callables | F/G independientes en combinaciones FF, FC, CF, CC |
| imports | función generic importada y monomorfizada desde fuentes transitivas |
| return C | Function y Closure; use-after-move negativo |
| body universal | rechazo Copy, Alias, arithmetic, equality, storage y lvalue assignment no autorizados |
| constraints extra | `Copy + Invocable`, `Storable + Invocable`, requirement forwarding simbólico |
| mismatch | kind no-callable, aridad, cada parámetro, resultado y void |
| aliases | aliases de tipos equivalentes y mismatch tras resolución |
| exceptions | success, throw, early return, catch/resume/finally y mismo event |
| fresh/lvalue | Closure fresh Transfer; lvalue retain/release; Function copy |
| IR | toda corrupción de sección 15 y ausencia residual |
| coste | cero allocation/thunk de adaptación; cero ARC por invocation |

### 16.1 Consumer numérico pequeño

El consumer de qualification recomendado es integración por rectángulos, local
al fixture y no productivo:

```aether
float64 integrate<C: Invocable<(float64), float64>>(
    C f, float64 a, float64 b, usize n
) {
    float64 h = (b - a) / float64(n);
    float64 sum = 0.0;
    usize i = usize(0);
    while (i < n) {
        sum = sum + f(a + (float64(i) + 0.5) * h);
        i = i + usize(1);
    }
    return sum * h;
}
```

Debe ejecutarse con Function y Closure capturante y comparar tolerancia, ARC y
número de invocaciones. No migra `plots` ni otra biblioteca.

## 17. Riesgos y dependencias reales

| Riesgo/dependencia | Tratamiento obligatorio |
|---|---|
| parser sólo admite nombres de constraint | AST discriminado y parser contextual de Invocable |
| `Capability` es Copy/atómico | requirement parametrizado separado; no meter TypeId dinámicos en ese enum |
| metadata usa `BTreeSet<Capability>` | preservar atomic set y agregar requirement/evidence tables |
| lifecycle generic desconocido | obligación root simbólica y resolución al especializar |
| inferencia desde firma | unificación exacta post-inferencia de C, con conflictos deterministas |
| evidencia falsificada | IDs declaration-owned y verificación independiente |
| dispatch incorrecto | seleccionar sólo desde `TypeData` concreto, nunca desde evidence declarativa sola |
| pérdida de event/cleanup | conservar CallSiteId y verificar success/unwind |
| explosión de instancias | medir combinaciones; límites actuales de monomorfización siguen vigentes |
| confusión source/binary ABI | sólo módulos fuente de una `CompilationSession`; no ABI independiente |
| falsa promesa zero-cost | prometer sólo ausencia de adaptación; medir costes intrínsecos |

No hay incompatibilidad técnica que obligue a reabrir Function ABI o
ClosureABI. Sí hay trabajo frontend y de ownership que no puede omitirse.

## 18. Gates de aceptación CLOSED

`INVOCABLE-CAPABILITY-V1` sólo puede declararse CLOSED cuando todos estos gates
estén verdes:

1. gramática contextual y diagnósticos de mal uso;
2. requirement/signature/evidence canónicos sin `TypeData::Invocable`;
3. aliases, cero/uno/múltiples parámetros y void;
4. sustitución y forwarding simbólico verificados;
5. inferencia exacta y satisfaction exclusiva Function/Closure;
6. body generic comprobado antes de especializar;
7. repeated invocation sin Copy/Alias implícitos;
8. ownership by-value Function/Closure y cleanup simbólico correcto;
9. return/early-return/unwind sin leak, double-drop ni use-after-move;
10. rewriting a los dos spines concretos existentes;
11. preservación de `CallSiteId`/`ExceptionEventId` y may-unwind;
12. corruption matrix independiente en HIR, specialization, MIR y SSA;
13. ausencia de `CapabilityInvoke`, evidencia y generics en MIR/SSA/LLVM;
14. matriz O0/O2 y consumer numérico ejecutable;
15. contadores prueban cero allocation/thunk de adaptación y cero ARC por call;
16. no cambios de runtime, Function ABI, ClosureABI ni libraries productivas;
17. documentación de feature/report actualizada con evidencia reproducible.

Un gate incompleto conserva estado de implementación PROPOSED, aunque los casos
positivos básicos compilen.

## 19. Milestones de implementación

### M0 — metadata y parser

- AST discriminado de constraints;
- firma canónica separada de `TypeData`;
- requirement/evidence tables;
- grammar, aliases y diagnostics.

### M1 — satisfaction e inferencia

- sustitución de requirements;
- satisfaction concreta/simbólica;
- inferencia exacta desde la firma del carrier;
- mismatch y forwarding tests.

### M2 — generic HIR

- `CapabilityInvoke` proof-carrying;
- validación universal del body;
- owner obligations simbólicas;
- verifier y corruption tests.

### M3 — especialización

- Function → `IndirectCall`;
- Closure → borrow/call/end-borrow;
- resolución de cleanup simbólico;
- rechazo residual pre-MIR.

### M4 — qualification end-to-end

- matriz O0/O2 completa;
- exceptions y ARC counters;
- import generic;
- consumer de integración;
- report de implementación.

### M5 — posteriores, no parte de V1

- invocation a través de `ref C`;
- posible migración de `plots`;
- medición de code size;
- sólo con evidencia, explorar `CallableRef` o `Callable` owning.

## 20. Fronteras explícitas

Quedan fuera de esta arquitectura V1:

- invocation a través de `ref C` o `ref mut C`;
- `Callable` owning erased y `CallableRef`;
- conversiones Function/Closure o adapters implícitos;
- generic lambdas;
- closures mutables, consuming u once;
- storage heterogéneo y retorno de kinds distintos bajo un solo tipo;
- traits/interfaces nominales generales o user-defined satisfaction;
- migración de `plots`, linearAlgebra u otras libraries;
- ABI generic entre artefactos compilados independientemente;
- cambios a ClosureABI-v1, Function ABI o runtime.

## 21. Cierre

Las decisiones son coherentes con el pipeline real y dejan cerradas grammar,
identidad, substitution, inference, satisfaction, semántica universal,
ownership, exceptions, rewriting y qualification. El punto que requería una
decisión adicional —cleanup de un parámetro cuya especialización puede o no
necesitar Drop— queda resuelto mediante obligación simbólica de owner en HIR
generic, nunca mediante una capability falsa.

Clasificación vigente: **ARCHITECTURE CLOSED; M0/M1/M2/M3/M4 CLOSED; V1
CLOSED**. La qualification final de los 17 gates, O0/O2, coste, corrupciones y
workspace completo se registra en `INVOCABLE_CAPABILITY_M4_REPORT.md`.
