# Aether — BORROWED-INVOCABLE-PARAM-ARCH-1

Estado: **ARCHITECTURE CLOSED; IMPLEMENTATION CLOSED**, 2026-11-15.

M0–M3 y la qualification final están cerrados; evidencia reproducible en
`BORROWED_INVOCABLE_PARAM_M3_REPORT.md`.

Este documento define la extensión acotada
`BORROWED-INVOCABLE-PARAM-V1` sobre `INVOCABLE-CAPABILITY-V1`, que permanece
**CLOSED** y no se reabre. La única superficie nueva permite invocar, dentro de
un body generic, un parámetro shared `ref C` cuando la capability pertenece al
tipo pointee `C`:

```aether
R apply<P, R, C: Invocable<(P), R>>(ref C f, P x) {
    return f(x);
}
```

No se implementa código productivo en este milestone de arquitectura.

## 1. Decisión

Se adopta la siguiente regla normativa:

> Si un parámetro tiene tipo exacto `ref C`, `C` es un binder generic de la
> declaración y ese binder posee evidencia
> `C: Invocable<(P...), R>`, el body puede invocar el pointee mediante
> `f(args)` en modo shared, read-only y repeatable.

La regla no declara invocable a `ref C`. La prueba sigue siendo exactamente la
evidencia de `C`. `ref C` sólo concede acceso borrowed al carrier durante la
invocación de la función que recibió el parámetro.

Consecuencias cerradas:

- `satisfies(ref Function<S>, Invocable<S>)` continúa siendo false;
- `satisfies(ref Closure<S>, Invocable<S>)` continúa siendo false;
- sólo `Function<S>` y `Closure<S>` satisfacen `Invocable<S>`;
- entrar a la función no copia `C`, no hace `Alias`, retain, Clone, Move ni
  Transfer del pointee;
- el parámetro reference no es un owner y no recibe Drop;
- invocation no consume ni reemplaza `C`;
- no se crea un adapter ni un callable erased;
- no cambian Function ABI, ClosureABI-v1, exception ABI ni runtime.

La extensión queda deliberadamente restringida a parámetros de función
declarados `ref C`. No introduce una regla general para invocar cualquier
expresión `ref T`, no admite `ref mut C` y no agrega references almacenables o
retornables.

## 2. Autoridades y compatibilidad

La decisión conserva las siguientes autoridades:

- `INVOCABLE_CAPABILITY_ARCH_1.md` y su cierre M4: requirement parametrizado,
  evidencia declaration-owned, firma exacta, body universal,
  `CapabilityInvoke`, especialización y dos únicos satisfiers;
- `BORROW_ERGONOMICS_ARCH_1.md` y `BORROW_ERGONOMICS_V1_REPORT.md`: borrow
  shared exacto en una frontera de call, Place/temporary, orden
  izquierda→derecha, no escape y cleanup normal/unwind;
- `GENERIC_INFERENCE_REF_ARGUMENT_V1_REPORT.md`: un patrón `ref U` puede
  obtener `U` del tipo exacto de un Place owner antes de materializar el borrow;
- `FUNCTION_VALUES_ARCH_1.md`: Function es un code pointer Copy/no-drop y una
  call de valor usa `IndirectCall` may-unwind;
- `FIRST_CLASS_CLOSURES_ARCH_1.md` y los reportes de ownership/runtime:
  Closure es un owner ARC, repeatable y read-only, y toda invocation usa
  borrow/call/end-borrow sin ARC por invocation;
- el contrato V9 de references: descriptor non-owning, shared, no-escape, sin
  retorno, storage, captura ni conversión a ownership;
- generic inference, sustitución y monomorfización vigentes;
- HIR/MIR/SSA verificados independientemente;
- `EXCEPTION-ARCH-2` y Exceptions V1–V4: evaluación izquierda→derecha,
  `CallSiteId`, un `ExceptionEventId` por evento, cleanup determinista y
  preservación del evento por catch/rethrow/finally.

La inspección del pipeline vigente encontró una ampliación necesaria pero no
un bloqueo:

| Capa | Estado vigente | Extensión requerida |
|---|---|---|
| source typing | `f: C` puede producir `CapabilityInvoke`; `f: ref C` no | reconocer exactamente el parámetro shared y usar evidencia de C |
| HIR generic | callee de `CapabilityInvoke` tiene tipo C owning | operación borrowed distinta, con carrier Place de tipo C bajo `ref C` |
| especialización Function | produce `IndirectCall` | cargar el code pointer Copy desde el Place prestado |
| especialización Closure | `ClosureCall` HIR presupone local owner | admitir carrier `BorrowedPlace`; MIR ya expresa carrier como Place |
| MIR/SSA Closure | protocolo tipado con carrier Place y token | reutilizarlo y verificar el Place dereferenciado/provenance |
| ABI/runtime | ambos call spines ya existen | ningún cambio |

No se puede modelar la feature cargando una Closure desde `*f` como si fuera un
valor. Eso fabricaría un owner sin Alias/Transfer. El carrier Closure debe
permanecer como Place borrowed hasta `ClosureBorrow`.

## 3. Superficie y formación

La forma admitida es:

```aether
R apply<P, R, C: Invocable<(P), R>>(ref C f, P x) {
    return f(x);
}
```

Son requisitos simultáneos:

1. `f` es un parámetro de la declaración actual;
2. su tipo declarado es exactamente shared `ref C`;
3. C es un `GenericParamId` visible de esa declaración;
4. C posee exactamente un requirement `Invocable<S>` bien formado;
5. argumentos y resultado coinciden exactamente con S bajo las reglas V1;
6. la invocation es read-only, repeatable y may-unwind.

No se admite por esta feature:

```aether
R bad(ref mut C f, P x) { return f(x); }
R bad(ref C f, P x) { return (*f)(x); } // no crea una lectura owning general
R bad(ref Function<(P), R> f, P x) { ... } // fuera del vertical generic acotado
```

La sintaxis `f(x)` es sugar de invocation borrowed validada; no es auto-deref
general. `*f` conserva las reglas ordinarias de dereference y no autoriza
cargar, mover o duplicar una Closure.

Forwarding a otra función cuyo parámetro sea `ref C` sigue siendo una copia del
descriptor reference y está permitido sólo bajo el no-escape vigente. No
convierte el pointee en owner.

## 4. Capability, satisfaction e inferencia

### 4.1 Autoridad de la capability

Para un parámetro `ref C`, el analyzer retira exactamente una capa shared para
buscar la evidencia. La relación normativa es:

```text
borrowed-invocable(ref C, S)
    iff binder(C) owns evidence C: Invocable<S>
```

No se agrega una regla a `satisfies_requirement`. El requirement y su
`ConstraintEvidenceId` continúan ligados a C, a su declaración y ordinal.

Una evidence de `ref C`, de otro binder o de otra declaración es corrupción.
Una constraint atómica, un `Invocable` de otra firma o una propiedad del tipo
concreto no sustituyen la evidence.

### 4.2 Inferencia en el call site

Para llamar `apply` con un owner `F`:

```aether
Function<(float64), float64> fn = square;
apply(fn, 2.0);

Closure<(float64), float64> closure =
    (float64 x) capture(copy scale) => scale * x;
apply(closure, 2.0);
```

la inferencia compara el patrón `ref C` con el Place owner exacto y obtiene
`C = Function<...>` o `C = Closure<...>`. Después valida
`C: Invocable<S>` y sólo entonces materializa el shared call borrow. No infiere
`C = ref Function<...>` ni `C = ref Closure<...>`.

Un argumento ya `ref T` coincide exactamente con `ref C` e infiere C=T. No se
forma `ref ref T`. Sólo se retira una capa shared; `ref mut`, nullable,
conversiones, widening y auto-deref no participan.

La firma de C continúa ayudando a inferir P y R mediante las reglas cerradas de
Invocable V1. Conflictos entre el pointee, otros argumentos y la firma producen
un error determinista. Imports generic usan los mismos `GenericParamId`,
substitution y evidence tables de la declaración importada.

## 5. Dos borrows distintos

La implementación y los dumps deben distinguir obligatoriamente:

1. **borrow de frontera**: lo crea el caller para satisfacer el parámetro
   `ref C`; protege el owner del caller durante toda la call a `apply`;
2. **borrow de invocation Closure**: lo crea el body especializado justo antes
   de evaluar los argumentos de `f(...)`; protege el carrier Closure durante
   esa invocation y termina en sus edges normal y excepcional.

Para Function sólo existe el borrow de frontera. El code pointer se carga como
Copy desde el Place protegido y se usa en `IndirectCall`.

Para Closure los intervalos están anidados:

```text
caller: Begin CallScopedSharedBorrow(owner, outer CallSiteId)
  callee apply(ref C):
    Begin ClosureBorrow(*f, inner CallSiteId)
      evaluate invocation arguments
      ClosureCall(*f, token, ...)
    EndClosureBorrow normal/unwind
caller: EndBorrow outer normal/unwind
```

El borrow interior no extiende la lifetime del owner y el exterior no sustituye
el token que exige `ClosureCall`. Ninguno hace retain/release.

`CallSiteId` exterior e interior son identidades distintas y no se fusionan.
Cada frame conserva el `ExceptionEventId` que le asigna el modelo vigente a su
landing pad/handler; cerrar cualquiera de los borrows no crea, sustituye ni
duplica un evento. Al cruzar el límite de frame, el caller observa el evento de
su outer invoke transportando el mismo record excepcional, no una excepción de
adaptación.

## 6. Contrato de lifetime y ownership

### 6.1 Function lvalue

Al pasar un lvalue `Function<S>`:

- el caller forma un shared borrow del Place existente;
- no copia el code pointer para adquirir el parámetro;
- no hay owner, Alias, ARC, allocation ni Drop en la frontera;
- dentro de la instancia, cada invocation carga el pointer Copy desde `*f` y
  ejecuta `IndirectCall`;
- invocaciones repetidas vuelven a leer el mismo Place protegido o reutilizan
  una copia SSA sólo si una optimización demuestra equivalencia.

### 6.2 Closure lvalue

Al pasar un lvalue `Closure<S>`:

- el caller presta el Place exacto y conserva su única obligación owning;
- no se ejecuta `ClosureAlias` ni retain al entrar;
- el parámetro transporta sólo un descriptor reference;
- cada invocation abre/cierra `ClosureBorrow` sobre el Place dereferenciado;
- no hay retain/release por invocation;
- el caller puede volver a usar, mover, reemplazar o destruir su Closure sólo
  después de terminar el borrow exterior.

### 6.3 Fresh temporaries

Se admiten Function y Closure fresh mediante la regla ya calificada de
call-scoped shared temporaries:

```aether
apply(square, 2.0);
apply((float64 x) capture(copy scale) => scale * x, 2.0);
```

El caller:

1. evalúa el argumento una vez;
2. inicializa un root temporary completo de tipo C por Transfer del fresh;
3. abre el borrow de frontera;
4. evalúa los argumentos posteriores;
5. invoca `apply`;
6. cierra el borrow;
7. destruye el temporary si C necesita Drop.

La materialización no duplica ownership. Para Closure hay una allocation
intrínseca a crear la closure y un release final intrínseco a destruir el
temporary, pero delta cero de allocation/ARC por la adaptación borrowed. Para
Function el storage addressable puede ser eliminado en O2; el Borrow debe
seguir siendo demostrable antes de optimización.

Un temporary incompleto o cuya creación lanza antes de publicarlo no tiene
borrow ni cleanup. Un descriptor borrowed cuya provenance no cubre toda la call
no obtiene una extensión artificial.

### 6.4 Evaluación de argumentos

La evaluación sigue siendo estrictamente izquierda→derecha:

- el callee/primer argumento que forma el borrow se evalúa una vez;
- el borrow exterior comienza al resolver o materializar su Place;
- permanece activo mientras se evalúan todos los argumentos posteriores de
  `apply` y durante toda esa call;
- un argumento posterior no puede mover, reemplazar, dropear o invalidar el
  mismo root;
- dentro de `apply`, el `ClosureBorrow` interior comienza antes de evaluar los
  argumentos de la invocation y permanece hasta obtener el resultado normal o
  tomar el edge excepcional;
- cleanups de temporaries ya inicializados siguen orden inverso.

Un efecto sobre un root demostrablemente distinto sigue siendo legal. Esta
feature no añade exclusividad/noalias ni un solver nuevo de aliases.

### 6.5 Repeated invocation y control flow

`f(args)` no cambia el estado owning del pointee. Por tanto se permiten cero,
una o varias invocaciones en branches y loops, siempre que el reference siga
vivo y cada invocation Closure cierre su token en todos los edges.

Early return desde `apply`:

- termina cualquier borrow interior activo antes de abandonar su expresión;
- no limpia ni transfiere C;
- no ejecuta Drop sobre el parámetro reference;
- devuelve sólo el resultado ordinario autorizado;
- deja que el caller cierre el borrow exterior y, si corresponde, destruya su
  temporary.

El generic HIR no crea `GenericOwnerObligation` para `f: ref C`. Las
obligaciones simbólicas de Invocable V1 continúan existiendo sólo para roots C
by-value.

### 6.6 Invalidación, Move y replacement

Mientras el borrow exterior está activo, se rechazan sobre su root:

- whole-root Move o Transfer;
- replacement o reinitialization;
- Drop/destrucción;
- partial move;
- mutación estructural que invalide el Place/provenance.

Dentro del body se rechazan `Move(*f)`, Drop de `*f`, assignment a `*f`, return
de `*f` como C y paso by-value que requeriría adquirir un owner. `ref C` no
autoriza ninguna de esas operaciones aunque una especialización concreta sea
Function Copy o Closure Alias-capable. La monomorfización no puede legalizar un
body generic inválido.

Copiar/forwardear el descriptor `ref C` a otra frontera reference es distinto:
no toca C, pero sigue sujeto a no-escape y no puede sobrevivir a la call.

### 6.7 Escape y storage

Se rechaza almacenar, retornar, capturar o convertir el parámetro/reference en:

- field, payload, Array/List/aggregate o global;
- resultado borrowed;
- Closure capture;
- generic type argument de storage;
- owner C, Alias, nullable callable o erased callable.

`Storable` adicional sobre C no cambia esta regla. Describe C, no concede
lifetime almacenables a `ref C`.

## 7. Excepciones y cleanup

Todas las invocaciones siguen siendo conservadoramente may-unwind.

### 7.1 Throw durante argumentos exteriores

Si un argumento posterior de `apply` lanza:

1. no se entra a `apply`;
2. se cierra el borrow exterior ya activo;
3. se destruye el temporary C si fue publicado y necesita Drop;
4. se ejecutan los demás cleanups en orden inverso;
5. se propaga el mismo `ExceptionEvent` del argumento que lanzó.

### 7.2 Throw durante argumentos de la invocation

Para Closure, si un argumento de `f(...)` lanza después de `ClosureBorrow`:

1. se cierran sus call borrows internos ya activos;
2. se ejecuta `EndClosureBorrow`;
3. no se libera C, porque `apply` no lo posee;
4. se propaga el mismo evento hacia el handler interno o fuera de `apply`.

Para Function no existe token Closure; los temporaries de argumentos se
limpian por el protocolo ordinario.

### 7.3 Throw durante invocation

Si `IndirectCall` o `ClosureCall` lanza:

- el resultado sólo existe en el edge normal;
- Closure ejecuta `EndClosureBorrow` antes de propagar;
- el frame de `apply` no ejecuta cleanup de C;
- al salir de `apply`, el caller termina el borrow exterior antes de destruir
  un temporary C;
- no se crea, sustituye, envuelve ni duplica el evento.

### 7.4 Catch, rethrow y finally

Un catch dentro de `apply` puede manejar el evento y volver a invocar f; el
borrow exterior sigue vigente porque la call exterior no terminó. Un rethrow
usa el mismo evento después de cerrar cualquier borrow interior activo.

Un catch del caller observa el mismo evento después del cleanup del frame y del
borrow exterior. `finally` conserva las restricciones vigentes: cleanup
compiler-generated sí cierra borrows; esta feature no habilita calls de usuario
en un `finally` que hoy las prohíba, ni permite que una excepción nueva sustituya
silenciosamente a la activa.

Destroy/release glue continúa `nounwind`; una violación es corrupción/fail-fast.
Traps permanecen abortivos y no prometen cleanup.

## 8. HIR generic

Se agrega una operación proof-carrying distinta para no cambiar el significado
cerrado de `CapabilityInvoke` by-value:

```text
BorrowedCapabilityInvoke {
    carrier: HirPlace,                    // tipo C; base Dereference(ref C)
    reference_type: TypeId,              // exactamente ref C shared
    carrier_type: TypeId,                // exactamente C GenericParam
    arguments: [HirExpr],
    result_type: TypeId,
    requirement: GenericRequirementId,
    evidence: ConstraintEvidenceId,
    required_signature: CallableSignatureId,
    satisfaction: SatisfactionEvidence,  // prueba sobre C
    mode: RepeatableRead,
    effect: MayUnwind,
    call_site: CallSiteId,
    provenance: SourceSpan,
}
```

`carrier` contiene la evaluación única del descriptor reference y su
provenance; no contiene un load owning de C. En V1 su root es exactamente un
parámetro de la función actual declarado `ref C`, sin proyecciones adicionales
después del dereference.

No se reutiliza `CallScopedSharedBorrow` dentro del body: ese nodo pertenece al
caller que construye la frontera. El body recibe una reference ya formada.

### 8.1 Verificador HIR generic

Un verificador independiente exige:

1. parámetro root existente, perteneciente a la declaración y declarado
   exactamente shared `ref C`;
2. `carrier` de tipo C formado por una única dereference de ese parámetro;
3. C es el binder exacto de `carrier_type`, no `ref C`;
4. evidence declaration-owned de C y requirement Invocable exacto;
5. `reference_type == ref carrier_type`, sin mutable/nullable;
6. firma, aridad, argumentos y resultado exactos;
7. `RepeatableRead`, `MayUnwind`, provenance válida y `CallSiteId` único;
8. reference viva y no escapada;
9. ausencia de load/move/alias/retain/transfer/drop/storage de C;
10. ninguna `GenericOwnerObligation` o cleanup de owner para el parámetro.

`BorrowedCapabilityInvoke` debe desaparecer durante especialización. MIR
rechaza categóricamente cualquier residuo.

## 9. Especialización

La especialización conserva el orden de Invocable V1: sustituir, volver a
validar satisfaction sobre C, comprobar evidence, seleccionar desde el
`TypeData` concreto, reescribir y verificar HIR concreto antes de MIR.

No se consulta el `TypeData::Reference` como satisfier. Primero se valida que
la reference tiene pointee concreto C; después el dispatch se selecciona
exclusivamente desde ese pointee.

### 9.1 `ref Function<S>`

```text
BorrowedCapabilityInvoke(carrier Place:Function<S>, args, S)
    -> IndirectCall {
         callee: LoadCopy(carrier),
         args,
         signature: Function<S>,
         call_site: original,
       }
```

`LoadCopy` lee un code pointer desde el Place; no adquiere ownership. El pointer
de código tiene lifetime de proceso. La call permanece indirecta y may-unwind,
salvo una optimización posterior ordinaria con prueba independiente.

### 9.2 `ref Closure<S>`

HIR concreto amplía el carrier de Closure sin alterar su protocolo:

```text
ClosureCarrier = OwnedLocal(LocalId) | BorrowedPlace(HirPlace)
```

La reescritura es:

```text
BorrowedCapabilityInvoke(carrier Place:Closure<S>, args, S)
    -> ClosureCall {
         carrier: BorrowedPlace(carrier),
         args,
         signature: Closure<S>,
         call_site: original,
       }
```

Lowering produce el protocolo existente:

```text
token = ClosureBorrow(call_site, carrier_place, Closure<S>)
args  = evaluate left-to-right
value = ClosureCall(call_site, carrier_place, token, args, Closure<S>)
EndClosureBorrow(call_site, carrier_place, token) // normal y unwind
```

MIR ya representa el carrier como Place; debe aceptar/verificar el Place
dereferenciado shared. No se materializa un local owner intermedio y no se
emite `ClosureAlias`, retain o release.

### 9.3 Rechazo residual y ABI

Antes de MIR no puede quedar:

- `BorrowedCapabilityInvoke`;
- evidence/requirement operativos;
- GenericParam en firmas, references, locals o Places;
- `ClosureCall` borrowed cuyo pointee no sea Closure de firma exacta.

MIR/SSA/LLVM conservan sólo `IndirectCall` o el protocolo Closure existente.
No cambian:

- Function ABI de un pointer;
- ClosureABI-v1, header, invoke/destroy thunks;
- helpers ARC;
- reference ABI de un pointer al storage del carrier;
- exception ABI o runtime helpers.

## 10. Verificación independiente MIR y SSA

### 10.1 MIR

Además de las reglas existentes, MIR reconstruye:

- que el parámetro de la instancia es `ref Function<S>` o `ref Closure<S>`;
- que el Place dereferenciado tiene exactamente el pointee y provenance del
  parámetro;
- Function: load Copy exacto antes de la call, callee/args/result y site;
- Closure: un token, una call y un end por cada edge no abortivo;
- ClosureBorrow comienza antes de argumentos y domina la ClosureCall;
- ningún Move/Replace/Drop/Store/owner load del carrier durante la región;
- ninguna Drop/ARC action para el parámetro reference;
- unwind edge y `ExceptionEventId` correctos.

### 10.2 SSA

SSA no confía en `VerifiedMir`. Reconstruye por CFG, types, definitions y
provenance:

- dominancia y evaluación única del reference/carrier;
- exactitud del pointee y firma;
- no escape del reference por phi, Store, Return, aggregate o otra call no
  autorizada;
- Function operand proveniente del load Copy correcto;
- Closure token no escapado, no duplicado y cerrado en todos los edges;
- carrier no invalidado y sin owner fabricado;
- resultado sólo normal y evento sólo excepcional;
- el `ExceptionEventId` vigente en cada frame se conserva por cleanup, catch,
  rethrow, finally y resume, sin fabricar uno para la adaptación.

LLVM recibe sólo SSA verificada. Puede eliminar storage o loads redundantes con
prueba, pero no inventar `noalias`, ARC, allocation, adapter o lifetime mayor.

## 11. Corruption matrix

Se requieren corrupciones construidas directamente en cada IR:

| Corrupción | Autoridad que rechaza |
|---|---|
| capability/evidence ligada a ref C en vez de C | generic HIR |
| evidence de otro binder/declaración/ordinal | generic HIR |
| reference mutable, nullable o con capa extra | generic HIR |
| carrier no es dereference del parámetro exacto | generic HIR |
| owner load, Move, Alias, Drop o obligation inventada | generic HIR/ownership |
| firma, aridad, argumento o resultado adulterado | generic y concrete HIR |
| RepeatableRead/MayUnwind/site/provenance alterado | generic HIR |
| Function reescrito como ClosureCall o viceversa | specialization/concrete HIR |
| Function load no-Copy o desde otro Place | concrete HIR/MIR/SSA |
| Closure owner temporary/retain inventado | concrete HIR/MIR/SSA/counters |
| missing/duplicate/premature ClosureBorrow/End | MIR/SSA |
| carrier moved/replaced/dropped/stored durante borrow | MIR/SSA |
| EndClosureBorrow sólo en success o sólo en unwind | MIR/SSA |
| Drop/ARC del parámetro reference | MIR/SSA |
| borrow de frontera termina antes de la outer call | call-borrow MIR/SSA |
| temporary cleanup antes de EndBorrow | MIR/SSA |
| event/site sustituido, duplicado o perdido | HIR/MIR/SSA exception verifiers |
| operación generic/evidence residual | frontera HIR→MIR y SSA |

## 12. Qualification obligatoria

Todo executable se corre en O0 y O2. Dumps HIR generic, HIR concreto, MIR, SSA
y LLVM se inspeccionan donde corresponda.

### 12.1 Positivos y lifecycle

- Function top-level lvalue y lambda sin capture;
- Closure lvalue con captures Copy, Alias y Move;
- Function y Closure fresh;
- invocation cero, una y repetida, incluidos branch y loop;
- cero, uno y varios parámetros, y retorno void;
- firma generic `Invocable<(T),T>`;
- dos parámetros borrowed callables F/G con evidence independiente;
- forwarding `ref D` con requirement idéntico;
- función generic importada y monomorfizada transitivamente;
- owner usable después de la call;
- early return antes y después de invocation;
- Place local y proyección legal si la frontera de borrow ya la admite.

### 12.2 Coste

Contadores comparan `apply(ref C, ...)` con calls borrowed directas equivalentes:

- delta cero de retain/release al entrar y salir para Closure lvalue;
- delta cero de ARC por cada invocation;
- cero allocation/free de adaptación;
- una allocation/free sólo cuando la creación intrínseca de una Closure fresh
  lo exige;
- ningún adapter thunk o helper runtime nuevo;
- Function lvalue sin copy owning ni Drop;
- LLVM sin `CapabilityInvoke`/`BorrowedCapabilityInvoke` residual.

No se promete eliminar el indirect dispatch, la allocation intrínseca de una
Closure ni el storage temporal conceptual en O0.

### 12.3 Temporaries y excepciones

- Closure fresh: cleanup normal, early return y unwind;
- throw antes de publicar el temporary;
- throw en argumento posterior de `apply`;
- throw en argumento de la invocation después de `ClosureBorrow`;
- throw desde Function y Closure;
- catch interno y segunda invocation;
- catch exterior, rethrow, finally y ResumeUnwind;
- orden `EndClosureBorrow` → salida de frame → `EndBorrow` exterior → Drop del
  temporary;
- mismo evento, sin resultado en exceptional edge;
- traps siguen sin cleanup prometido.

### 12.4 Negativos

- non-callable, firma/aridad/parámetro/resultado diferentes;
- `ref mut C`, nullable C y referencia con capa extra;
- satisfaction falsa de `ref Function`/`ref Closure`;
- return/storage/capture del parámetro;
- formar owner C desde `*f`;
- Move, Drop, replacement, assignment, Alias o retain del pointee;
- invalidar el root desde un argumento posterior;
- usar el borrow después de la outer call;
- body generic que sólo resulta legal para Function Copy;
- body generic que intenta explotar Alias intrínseco de Closure;
- toda corrupción de §11.

### 12.5 Consumer numérico

El consumer mínimo es integración por rectángulos, local al fixture:

```aether
float64 integrate<C: Invocable<(float64), float64>>(
    ref C f, float64 a, float64 b, usize n
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

Debe ejecutarse con Function y Closure capturante lvalue/fresh, comparar el
resultado con tolerancia explícita, contar exactamente n invocaciones por
carrier y demostrar el delta ARC/allocation de la adaptación. No migra Plots ni
otra biblioteca productiva.

## 13. Riesgos y tratamiento

| Riesgo | Tratamiento obligatorio |
|---|---|
| confundir capability de C con una de ref C | nodo/evidence sobre carrier_type C; satisfaction sin cambios |
| cargar Closure como owner desde dereference | carrier Place hasta MIR; corrupción si aparece owner load |
| borrar la diferencia entre los dos borrows | identidades/sites y verificadores separados |
| inferir C como ref Function/ref Closure | retirar exactamente una capa shared del patrón, luego validar C |
| lifetime de fresh demasiado corto | root temporal del caller hasta después de EndBorrow en ambos edges |
| retain defensivo oculto | counters y prohibición normativa de Alias/ARC en frontera |
| invalidación durante argumentos | call-borrow ledger desde la evaluación del primer argumento |
| perder event al desenrollar dos regiones | CallSiteId distintos; cada cleanup conserva el event de su frame y no crea otro |
| especialización legaliza operación owning | generic HIR se verifica antes de conocer Function/Closure |
| broaden de ClosureCall HIR afecta V1 owning | carrier discriminado; ruta OwnedLocal y sus tests permanecen intactos |
| falsa promesa zero-cost | prometer sólo delta cero de adaptación/ARC; medir costes intrínsecos aparte |

La incompatibilidad HIR actual es local y resoluble. MIR ya usa Place para el
carrier Closure y el ABI/runtime no requieren cambios. Por tanto no existe un
bloqueo arquitectónico real.

## 14. Milestones mínimos

### M0 — typing y HIR generic

- reconocer únicamente parámetro `ref C` con evidence de C;
- inference/satisfaction exactas sin nuevos satisfiers;
- `BorrowedCapabilityInvoke` y verifier independiente;
- rechazo de ownership, escape, storage, Move y Drop;
- corruption tests generic HIR.

### M1 — especialización y HIR concreto

- Function → load Copy + `IndirectCall`;
- Closure → `ClosureCarrier::BorrowedPlace`;
- preservación de call site, firma y may-unwind;
- rechazo residual pre-MIR;
- corruption tests de especialización/concrete HIR.

### M2 — MIR/SSA lifecycle y exceptions

- carrier Place dereferenciado en Closure protocol;
- verificadores independientes de provenance, token y no owner;
- nesting con CallScopedSharedBorrow exterior;
- temporaries, early return, arguments y unwind;
- event/catch/rethrow/finally corruption tests.

### M3 — qualification final

- matriz O0/O2 completa;
- contadores ARC/allocation/drop;
- imports/forwarding;
- consumer numérico;
- workspace, format, lint y reporte reproducible.

Un caso positivo aislado no cierra implementation. Todos los milestones y la
qualification deben quedar verdes antes de declarar
`BORROWED-INVOCABLE-PARAM-V1 CLOSED`.

## 15. Fronteras explícitas

No forman parte de esta arquitectura:

- callable owning o parámetro C by-value nuevo;
- `Callable`, `CallableRef` o type erasure;
- `ref mut C` invocation;
- invocation general de valores concretos `ref Function`/`ref Closure` fuera
  del parámetro generic acotado;
- nuevos satisfiers o cambios a Invocable V1;
- mutable/consuming/once closures;
- generic lambdas;
- traits/interfaces generales o satisfaction user-defined;
- storage heterogéneo o referencias almacenables;
- migración de Plots o libraries;
- Function ABI, ClosureABI, exception ABI o runtime helpers nuevos.

## 16. Cierre

Ownership, lifetime, temporaries, evaluación de argumentos, repeated
invocation, early return, invalidación, Move/replacement, escape, exceptions y
los dos niveles de borrow quedan definidos sin modificar las decisiones CLOSED
de Invocable V1.

La única brecha real del pipeline —HIR ClosureCall limitado a un local owner—
se resuelve conservando un `BorrowedPlace` hasta el protocolo Closure existente;
MIR/SSA y ABI ya pueden representar el carrier como Place. No exige owner
intermedio, retain, allocation, adapter ni runtime nuevo.

Clasificación: **ARCHITECTURE CLOSED; IMPLEMENTATION CLOSED;
BORROWED-INVOCABLE-PARAM-V1 CLOSED**.

