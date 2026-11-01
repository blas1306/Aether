# FIRST-CLASS-CLOSURES-ARCH-1 — anonymous functions and owning closures

Estado: **CLOSED; ARQUITECTURA ACEPTADA; IMPLEMENTACIÓN NO INICIADA**,
2026-11-01.

Este documento investiga funciones anónimas y closures de primera clase para
Aether. No implementa sintaxis, compiler, runtime o libraries, y no cambia los
contratos vigentes de `Function<(Args), Return>`. La propuesta separa de forma
deliberada una función anónima sin captura de una closure que posee un
environment.

Esta revisión incorpora las decisiones de sintaxis, captura, ownership y ABI
de §18. Es una especificación arquitectónica; no autoriza cambios implícitos en
compiler, runtime, libraries, tests ni APIs existentes. Los dos verticales de
§16 conservan qualification y aceptación de implementación independientes.

## 1. Autoridades y preflight

Se inspeccionaron como autoridad vigente:

- `FUNCTION_VALUES_V1_REPORT.md`, `function_values_v1.rs` y los gates
  `E0350..E0357`;
- `TypeArena`, `TypeData::Function`, `TypeProperties`, sustitución generic y
  layouts en `aether-frontend/src/types.rs` y `hir.rs`;
- `HirExprKind::{FunctionRef,IndirectCall}`, sus verificadores y lowering;
- `Rvalue::{FunctionRef,IndirectCall}`, `SsaOp::{FunctionRef,IndirectCall}` y
  sus verificadores independientes;
- lowering LLVM de function values, direct/indirect `call`/`invoke` y
  reachability;
- ownership estructural, `Move`, `Drop`, conditional cleanup, string/class/
  interface `Alias` y owner ledgers;
- referencias V9, borrow ergonomics, class-handle references, regiones
  `Borrow`/`EndBorrow` y sus rutas normal/unwind;
- structs, enums, classes, interfaces, generics, `Storable`, `Relocatable` y
  límites actuales de storage;
- EXCEPTION-V1..V4, landing pads, `ExceptionEvent`, catch/finally y cleanup;
- OOP-OPT-1 y el tratamiento actual de calls indirectas en O0/O2;
- `plots.plotFunction`, Newton, numerical methods y least-squares consumers.

### 1.1 Restricciones comprobadas de `Function`

`Function<(P1, ...), R>` es una identidad estructural e invariante. Sus
propiedades vigentes son:

| Propiedad | Contrato actual |
|---|---|
| carrier | exactamente un pointer |
| semántica | dirección de función Aether top-level, visible y no generic abierta |
| `Copy` | sí |
| `Relocatable` / `Storable` | sí / sí |
| `needs_drop` | no |
| environment | ninguno |
| invocation ABI | `R code(P1, ...)` |
| exceptions | indirect call conservadoramente may-unwind |
| backend | `ptr`; prototype derivado de la firma canónica |

`FunctionRef` conserva el `InstanceId` target y la firma exacta. `IndirectCall`
conserva callee, argumentos, resultado, `CallSiteId` y firma en HIR, MIR y SSA.
Cada verificador reconstruye aridad y tipos; LLVM emite `call` o `invoke`
directamente contra el pointer. Reachability sigue `FunctionRef`.

Aunque `Function` es `Storable`, FUNCTION-VALUES-V1 mantiene gates explícitos:
no se retorna, no aparece en fields/payloads ni en `Array`/`List`. Esos gates
son deuda de qualification, no evidencia de que una closure tenga que copiar
su representación.

### 1.2 Locals, ownership y `Alias`

- Scalars y aggregates `Copy` se duplican sin lifecycle.
- Un owner no-Copy ordinario se mueve como root completo; el source pasa a
  `Moved`. No existen partial moves generales.
- `Drop` es tipado y estructural. Estados `Owned`, `Moved` y `MaybeMoved`
  determinan cleanup normal, early return y unwind.
- `Alias` no es `Copy`. Hoy es una capacidad intrínseca y cerrada de strings,
  class handles e interface carriers. Un lvalue crea otra obligación owning;
  un fresh result transfiere.
- No existe todavía una constraint generic pública `Alias` ni un mecanismo
  universal de clone.

Una closure no puede heredar propiedades distintas según sus captures si todas
las instancias comparten sólo `Closure<(Args), R>` como `TypeId`: las
`TypeProperties` se consultan por tipo canónico, no por valor. Por tanto una
representación V1 debe elegir propiedades uniformes para todo `Closure` o
introducir tipos anónimos concretos distintos. La recomendación elige
propiedades uniformes.

### 1.3 References y regiones

`ref T` y `ref mut T` son non-owning, no-storable y conservadoramente
no-escaping. Pueden vivir como parámetros, argumentos y locals de una sola
inicialización, pero no se retornan, almacenan, capturan ni usan como generic
arguments. Las regiones call-scoped conservan Place/provenance, bloquean
invalidaciones incompatibles y terminan mediante `EndBorrow` en rutas normal y
unwind.

`ref mut` concede escritura pero no unicidad, exclusividad ni `noalias`.
Aether no tiene hoy lifetime parameters ni regiones heap. En consecuencia, una
closure retornable o almacenable no puede capturar una referencia sin romper el
contrato vigente o añadir un sistema de lifetimes que este milestone no diseña.

### 1.4 Structs, classes, generics e interfaces

- Structs/enums son values nominales inline; sus propiedades se derivan de
  fields/payloads concretos. Ownership es whole-root.
- Classes son objects heap con handles ARC de un pointer. Alias y receiver
  keepalive son operaciones semánticas, no `Copy`.
- Interfaces son carriers owning `{object, witness}` con dispatch y release
  dinámicos. No son interfaces estructurales ni generic.
- Generic functions se monomorfizan antes de MIR. Las capabilities públicas
  cerradas son `Copy`, `Relocatable` y `Storable`; `Alias` no está entre ellas.
- `Storable` expresa persistencia sin lifetime borrowed, no `Copy`, no-drop o
  aliasabilidad.

Modelar cada closure como una class sintética reutilizaría parte del ARC, pero
haría depender una firma estructural de classes nominales ocultas, no resuelve
un carrier común entre environments diferentes y no convierte interfaces en
generic callables. Es una técnica de implementación posible, no el modelo
semántico adoptado.

### 1.5 Exceptions y optimización

Toda `Call`/`IndirectCall` dentro de una función con exceptions posee exactamente
el unwind edge requerido. El landing pad limpia owners vivos y transporta el
mismo `ExceptionEvent`; `finally` no sustituye esa excepción. Traps, incluidos
allocation failure y ARC overflow, continúan abortivos y no prometen cleanup.

El pipeline no posee una devirtualización semántica general de `FunctionRef` +
`IndirectCall`. LLVM puede propagar un target constante, inlinear o eliminar
una call en O2. OOP sí tiene pruebas específicas de devirtualización, pero no
deben extrapolarse automáticamente a closures.

## 2. Dos capacidades distintas

### 2.1 A — función anónima sin captura

Una expresión como:

```aether
(double x) => x * x
```

que no usa locals, parámetros ni `this` de un scope exterior puede bajar a una
función sintética module-owned y materializar su dirección mediante el
`FunctionRef` existente. Su tipo es exactamente
`Function<(double), double>`, conserva un pointer, `Copy`, ausencia de Drop y
el ABI actual. No necesita descriptor, environment, allocation, ARC ni una
operación de call nueva.

El target sintético recibe un `LambdaId` estable, participa en reachability y
tiene un `InstanceId` ordinario después de monomorfización. No es visible por
name lookup ni exportable por su nombre generado. HIR/MIR/SSA siguen mostrando
`FunctionRef` e `IndirectCall`; sólo AST/HIR source provenance identifica la
expresión anónima.

Esta equivalencia vale por semántica, no por una optimización. Si la expresión
contiene una capture, no puede tomar esta ruta aunque O2 pudiera constant-fold
el valor capturado.

### 2.2 B — closure con capture

Una expresión como:

```aether
(double x) capture(copy a, copy b) => a * x + b
```

necesita preservar `a` y `b` después de abandonar el scope creador. La firma
visible no describe layout ni Drop de ese environment. El target real necesita
un ABI interno como:

```text
R invoke(ptr environment, P1, ...)
```

Por ello no es un `Function<(P1,...),R>`. La recomendación introduce un tipo
estructural distinto:

```aether
Closure<(P1, ...), R>
```

`Closure` representa un callable owning, repeatable y de environment read-only.
No significa “cualquier cosa invocable”, no implementa una interface source y
no es convertible implícitamente a `Function`.

## 3. Tipo y capabilities de `Closure`

Para todo `Closure<(P...), R>` V1 se fijan propiedades uniformes:

| Propiedad | Valor V1 |
|---|---|
| identidad | estructural e invariante por parámetros/resultado |
| carrier source/ABI | un pointer owning a un closure box |
| `Copy` | no |
| `Relocatable` | sí |
| `Storable` | sí, sujeto a gates de V1 |
| `needs_drop` | sí |
| `Alias` | capability intrínseca de Closure, no generic |
| null | no; nullable sólo mediante `Closure<...>?` futuro/calificado |
| invocation | repeatable; no consume el closure ni sus captures |

Que el carrier sea un pointer no lo hace compatible con `Function`: el pointer
apunta a un object con header y payload, no a código con prototype `R(P...)`.

### 3.1 Assignment, arguments y return

Se recomienda la misma clasificación que string/class handles:

- fresh closure a local/argument/return: Transfer del owner existente;
- closure lvalue a local/argument/return: `ClosureAlias`, con un retain;
- explicit whole-root Move: transfiere e invalida el source;
- replacement: adquirir/materializar RHS, publicar, release del owner viejo;
- scope exit/unwind: un `ClosureDrop`/release por obligación viva.

`Closure` no satisface `T: Copy`. Un generic que sólo conoce `T: Storable` no
puede inventar `Alias`; por-value puede transferir según las reglas generic
existentes. Generalizar `Alias` como constraint es un milestone separado.

### 3.2 Invocación repetida

`closure(args)` observa captures sin consumirlas. El callee abre un borrow
interno sobre el carrier owner antes de evaluar argumentos, lo mantiene hasta
retorno o unwind y luego lo cierra. Así el box no puede destruirse ni
reemplazarse durante la call y no se exige un retain/release por invocación.

Una closure fresh invocada inmediatamente se materializa en un temporary owner,
se presta durante la call y se destruye después. Cualquier excepción del body
atraviesa la call; si un handler conserva el owner exterior, la misma closure
puede invocarse otra vez.

## 4. Capture semantics

La sintaxis normativa V1 es una arrow lambda con parámetros explícitamente
tipados, body de una expresión y una cláusula `capture(...)` opcional:

```aether
var square = (double x) => x * x;
var affine = (double x) capture(copy a, alias label, move data) =>
    evaluate(x, a, label, data);
```

La forma gramatical es:

```text
LambdaExpr    := "(" [TypedParameter {"," TypedParameter}] ")"
                 [CaptureClause] "=>" Expression
CaptureClause := "capture" "(" CaptureItem {"," CaptureItem} ")"
CaptureItem   := ("copy" | "alias" | "move") Identifier
```

La cláusula completa es opcional pero, si aparece, contiene al menos un item.
`capture()` vacío y nombres sin modo son errores de sintaxis.

No se introducen `@(...)`, `fn`, `let` ni una nueva declaración. `var` es la
inferencia local existente elegida para Aether. La cláusula es una lista
**parcial**: sólo reemplaza el modo automático de los nombres que contiene.
Toda otra variable libre capturable se adquiere implícitamente por su categoría:

| Categoría del tipo concreto | Captura automática V1 |
|---|---|
| `Copy` y `Storable` | `copy` |
| owning con `Alias` intrínseco calificado | `alias` |
| owning Move-only sin `Alias` | error; exige `capture(move name)` |
| `ref`, `ref mut`, view o non-`Storable` transitivo | error |

Nunca se infiere `move`, deep copy, `Clone` ni `Alias` a partir de `Storable`.
Una entrada explícita tiene prioridad para ese nombre, pero debe ser válida para
su tipo. En particular, `copy` no fuerza copia de un owner, `alias` no fabrica
una capability y `move` nunca admite un valor borrowed.

### 4.1 Variables libres, resolución y shadowing

Name lookup del body se realiza léxicamente antes de clasificar captures. Un
uso es libre para una lambda si resuelve a un local o parámetro nombrado de un
scope exterior; un parámetro de la propia lambda o una declaración más interna
lo sombrea y no se captura. Functions top-level, types, constants de compile
time y otras declarations sin storage local se resuelven normalmente y no
forman parte del environment.

Cada entrada de `capture(...)` se resuelve en el scope inmediatamente exterior
a la lambda, con las reglas ordinarias de lookup, y debe nombrar exactamente un
local o parámetro exterior capturable. Es error repetir un nombre, nombrar un
símbolo inexistente o sombreado por un parámetro de la lambda, capturar una
declaration no capturable, usar un modo inválido o intentar capturar el mismo
root por dos spellings. Un capture explícito válido que no corresponde a ningún
uso libre del body ni de una lambda anidada produce un warning obligatorio,
source-spanned en la entrada y en la declaration; el capture sí se adquiere y
conserva su lifecycle, de modo que el warning no cambia semántica.

`this`, bound-method temporaries y default-argument context no son capturables
en V1. Un local ordinario que contenga el valor explícitamente materializado sí
sigue las reglas generales.

### 4.2 Orden, adquisición, fallo y publicación

El orden canónico del environment es:

1. captures explícitos, en el orden escrito en `capture(...)`;
2. captures implícitos, por la posición del primer uso léxico del binding en el
   body completo, incluyendo bodies de lambdas anidadas; los spans desambiguados
   constituyen el desempate estable.

Ese orden gobierna layout, adquisición y dumps. El box se asigna primero y se
mantiene sin publicar; luego cada capture se adquiere de izquierda a derecha.
`copy` copia el snapshot, `alias` adquiere un owner independiente y `move`
transfiere el root e invalida inmediatamente el binding source. Sólo después de
inicializar header y todos los fields se publica el carrier `Closure`.

Ante un fallo recuperable durante creación se destruye exactamente el prefijo
inicializado, en orden inverso, y se libera el box; un source ya movido permanece
`Moved`, como en cualquier evaluación parcial izquierda-a-derecha. Los captures
no iniciados no se tocan. Los traps abortivos vigentes, incluidos allocation
failure y ARC overflow, no prometen unwind ni cleanup. Ninguna operación de
captura V1 ejecuta user code; si una futura adquisición puede lanzar, debe
implementar este mismo rollback antes de abrirla.

La destrucción final de una closure publicada destruye todos los fields en
orden inverso al canónico. El orden no depende de hash maps, optimización ni
orden de recorrido del AST.

### 4.3 Copy capture

`copy x` exige `x: Copy + Storable`. Copia el valor al crear la closure y
captura un snapshot. Una modificación posterior del binding exterior no cambia
el capture. Se rechazan references/views aunque sean `Copy`, porque no son
`Storable` y su lifetime no puede borrarse.

### 4.4 Owning capture mediante Alias

`alias x` exige que el tipo concreto posea una operación `Alias` ya calificada.
En el sistema actual eso puede cubrir string, class handle, interface carrier y,
recursivamente, otra `Closure`. Adquiere una obligación owning para el
environment y deja válido el source.

No se deriva `Alias` estructuralmente para un aggregate que contiene un string
o class. Sin una capability general, ese aggregate se captura mediante `move`.
Un class handle capturado conserva identidad compartida: el slot del
environment es read-only, pero otros handles pueden mutar el object conforme a
las reglas normales de Aether.

### 4.5 Owning capture mediante Move

`move x` exige un root owning `Storable`; transfiere la obligación completa al
environment e invalida el source al adquirir su field, antes de publicar la
closure. No admite field move, index move ni partial move. Si el environment se
destruye sin ser invocado, el valor capturado se destruye igualmente una vez.

Move en la creación no implica “invoke once”. El body V1 no puede mover el
capture hacia afuera, reemplazarlo ni consumirlo; puede observarlo mediante
operaciones read/borrow que no alteren la obligación. Una futura closure
consumidora necesita otra capability de invocación.

### 4.6 Capture por referencia

`ref` y `ref mut` captures se reservan y se rechazan en V1, incluso si el uso
parece inmediato. Admitir sólo casos “que no escapan” crearía un segundo tipo
borrowed cuya región tendría que sobrevivir assignment, phi, indirect calls y
generic forwarding. Las regiones actuales no justifican ese escape.

Un milestone posterior puede diseñar `BorrowedClosure` con region identity y
gates que prohíban return/storage. No debe reutilizar `Closure`, porque
`Closure` es `Storable` y retornable.

### 4.7 Capture mutable

V1 prohíbe asignar a un capture, obtener `ref mut` de él, reemplazarlo o
consumirlo. También prohíbe que la invocación requiera mutabilidad del carrier.
Esto evita decidir prematuramente si varias aliases de una closure comparten
estado mutable, si la llamada requiere un binding writable o si se necesita una
categoría callable separada.

No se copian automáticamente `Fn`/`FnMut`/`FnOnce`. Un milestone posterior debe
partir de las capabilities Aether: repeatable-read, repeatable-write-shared y
consuming, y decidir su relación con `Alias` y `ref mut`, que hoy no significa
unicidad.

### 4.8 Self-capture y lambdas anidadas

El binding declarado por un initializer no está en scope dentro de su propio
initializer. Por tanto `var f = (...) => f(...)` no crea recursión ni un ciclo
mágico: resuelve un `f` exterior si existe y, si no, es un nombre no resuelto.
No existe `self` implícito de closure en V1. Al reemplazar un local preexistente,
una captura `alias f` observa/adquiere el valor anterior antes de publicar y
reemplazar el nuevo; no se reescribe para apuntar a sí misma.

Cada lambda anidada tiene análisis y environment propios. Un nombre exterior
usado sólo dentro de la lambda interna cuenta como libre transitivo para las
lambdas intermedias necesarias para construirla. La lambda exterior lo captura
según esta sección; durante una invocation, la interna puede `copy` o `alias`
desde el slot read-only exterior. No puede `move` desde ese slot, porque
consumiría un capture y rompería repeatability. Si el valor original es
Move-only sin Alias y debe llegar a una lambda interna escapable, V1 lo rechaza:
no hay move transitivo ni consumo del environment exterior implícitos.

Una lambda interna sin captures propios sigue clasificándose como `Function`.
Una que capture parámetros de la lambda exterior, slots de su environment u
otros locals visibles se clasifica como `Closure`; su lifetime es independiente
y sus owners mantienen vivos los objetos aliasados después del retorno exterior.

## 5. Lifetime, escape y storage

El box posee todos los captures; por ello una closure V1 puede sobrevivir al
scope de declaración y retornarse sin referencia colgante. El environment no
contiene `ref`, view ni otro tipo non-Storable, ni directa ni transitivamente.

El **primer vertical mínimo** admite:

- initializer de local explícito o `var`;
- assignment/replacement de locals;
- paso y retorno por valor;
- invocación repetida;
- captures `copy`, `alias` y whole-root `move`;
- normal cleanup, early return, conditional cleanup y exception unwind.

Conserva gates para Closure dentro de struct/class fields, enum payloads y
`Array`/`List`. Aunque la representación adoptada es `Storable`, abrir cada
posición exige qualification independiente, igual que los gates históricos de
`Function`. El siguiente storage milestone debe abrir primero struct/enum y
Array/List; class fields se separan por riesgo de ciclos ARC
`closure -> class -> closure`.

Las closures retornadas sí pertenecen al V1 mínimo: sin return no se califica el
escape owning central de la feature. El ABI cross-module del box es por eso una
decisión bloqueante, no una optimización opcional.

## 6. Representación adoptada

### 6.1 Closure box heap

Cada expresión capturante posee un layout de payload privado y glue estático:

```text
ClosureBox<LambdaId> {
    usize strong_count;
    ptr invoke_thunk;
    ptr destroy_thunk;
    capture_0;
    ...
    capture_n;
}

Closure<(P...), R> carrier = ptr ClosureBoxHeader
```

El header y sus offsets forman ABI compiler/runtime; el payload no. El
`invoke_thunk` tiene prototype lógico `R(ptr box, P...)`, proyecta captures por
layout verificado y ejecuta el body sintético. `destroy_thunk` destruye los
captures inicializados en orden inverso y libera el box. Retain/release son
non-atomic, coherentes con el ARC bootstrap actual.

§9 fija normativamente offsets, alignment, calling conventions, helpers,
identidad y compatibilidad cross-module. El pseudolayout anterior no deja esos
puntos a elección del backend.

Una representación equivalente que reutilice un header class es aceptable en
backend si preserva estas invariantes. No debe exponer una class nominal, una
vtable source, RTTI o reflection.

### 6.2 Por qué heap-only en V1

Un `Closure<(P),R>` puede contener environments de tamaños distintos. Inline
storage exige uno de:

1. tamaño máximo fijo y desperdicio/limitación;
2. tipo anónimo concreto por lambda y posterior erasure;
3. small-object optimization con estado discriminante, move/drop más complejos;
4. generic environment visible en el tipo público.

Todos agregan otra frontera semántica antes de demostrar la básica. Heap-only
da carrier uniforme, address estable, return/storage sencillos y Drop dinámico.
O2 puede eliminar una allocation sólo después de pruebas de escape; no cambia
la semántica.

### 6.3 Alternativas descartadas para V1

| Alternativa | Ventaja | Motivo de no elección V1 |
|---|---|---|
| cambiar `Function` a `{code,env}` | una sola superficie | rompe layout, Copy/Drop, ABI y consumers existentes |
| trampoline + global/TLS | conserva un pointer de código | no reentrante, no thread-safe, lifetime oculto, incorrecto con recursion |
| stack environment | cero heap | inválido al retornar/almacenar; requeriría escape split observable |
| inline existential | locality | tamaño/Drop heterogéneos; necesita concrete closure types |
| class sintética expuesta | reutiliza ARC | nominalidad falsa y carrier común no resuelto |
| interface callable | dispatch existente | interfaces no generic/estructurales; signature family y ownership sin resolver |
| environment deep-copy | closures independientes | Aether no posee Clone general; costos y fallos ocultos |
| move-only box sin Alias | implementación menor | assignment/pass ergonómico deja de preservar source y limita callbacks reutilizables |
| GC | cycles sencillos | introduce runtime y ownership ajenos al lenguaje actual |

## 7. Typing e inferencia local

La sintaxis V1 normativa tiene parámetros tipados explícitamente y body de
una expresión:

```aether
(double x) => x * x
(double x) capture(copy a, copy b) => a * x + b
```

No hay parámetros sin tipo, destructuring, defaults, variadics ni generic
lambdas. El resultado se obtiene del body ya tipado. Si existe expected type,
la firma final debe coincidir exactamente con el `Function` o `Closure`
esperado después de las conversiones contextuales ordinarias dentro del body.

Sin expected type, `var` infiere:

- capture set vacío: `Function<(P...), R>`;
- capture set no vacío: `Closure<(P...), R>`.

Una declaración explícita fija la clasificación:

```aether
Function<(double), double> square = (double x) => x * x;
Closure<(double), double> affine =
    (double x) capture(copy a, copy b) => a * x + b;
```

V1 no convierte una closure sin capture almacenada como `Closure` a
`Function`, ni un `Function` a `Closure`. Para evitar allocation accidental, una
expresión sin capture esperada como `Closure` se rechaza en el primer vertical;
un adapter/static singleton puede calificarse después.

## 8. Contratos HIR, MIR y SSA

### 8.1 AST/HIR

AST conserva `LambdaId`, parámetros, body, cláusula parcial de captures y spans.
Free-name analysis resuelve el binding de cada uso exterior, agrega captures
automáticos, valida las entradas explícitas y emite el warning obligatorio para
entradas explícitas no usadas.

HIR agrega metadata y operaciones semánticas distintas:

```text
ClosureEnvironmentInfo {
    lambda, signature, captures[(mode, source_type, field_type)],
    invoke_instance, layout, destroy_recipe
}

ClosureCreate { environment, captures, signature }
ClosureAlias  { source, signature }
ClosureCall   { call_site, callee, args, signature }
```

Una lambda sin capture no usa estas operaciones: crea una función sintética y
el `FunctionRef` existente. HIR verifica capture modes, exact source, storage,
body access, firma, absence de references/mutation y una recipe de Drop total.
El análisis conserva para cada capture si fue explícito o implícito, declaration
span, first-use span y orden canónico. Resuelve free variables y shadowing antes
de crear HIR; ninguna fase posterior vuelve a inferir el set desde nombres.

### 8.2 MIR

MIR materializa capturas en el orden canónico de §4.2 y emite `ClosureCreate`
como adquisición de un owner. Copy duplica; Alias adquiere antes de publicar;
Move transfiere e invalida al adquirir su field. El box no se considera
publicado hasta que todas las captures y el header están inicializados. Estado
de inicialización por prefijo hace explícito el cleanup inverso ante cualquier
unwind recuperable.

Allocation/ARC traps siguen siendo abortivos. Si en el futuro la allocation
puede lanzar, `ClosureCreate` deberá exponer un unwind protocol para destruir el
prefijo adquirido; V1 no puede asumir silenciosamente rollback.

`ClosureCall` conserva signature y unwind edge. El borrow del carrier y sus
`EndBorrow` normal/excepcional son explícitos. `ClosureAlias`, `Move` y `Drop`
alimentan el mismo ledger path-sensitive que otros owners.

### 8.3 SSA

SSA conserva las operaciones anteriores, owner tokens, borrow region,
provenance de capture y unwind. No degrada el box a raw pointers antes de
`VerifiedSsa`. Phis transfieren una obligación de Closure por edge; no pueden
duplicarla. El verificador rechaza:

- `ClosureCreate` con capture faltante/reordenada/tipo o mode adulterado;
- environment con reference/view o field no-Storable;
- Alias sin adquisición, Move duplicado, use-after-move y Drop ausente/doble;
- call con carrier/signature/arity/result incompatibles;
- mutation/consumption de capture en un body read-only;
- borrow de carrier vivo que cruza Store/Return/Drop o carece de EndBorrow;
- unwind que pierde captures/closure owners o fabrica un `ExceptionEvent`.

## 9. LLVM y ABI normativo V1

Backend recibe sólo `VerifiedSsa`. Para create:

1. calcula el layout privado exacto con overflow checked;
2. asigna un box;
3. inicializa count y glue pointers;
4. inicializa captures en orden;
5. publica el carrier.

Para call carga `invoke_thunk`, forma el prototype desde el `Closure` signature
y emite:

```llvm
%result = invoke R %invoke(ptr %box, P1 %a1, ...)
          to label %normal unwind label %cleanup
```

No hay `bitcast`/`ptrtoint` como autoridad de tipos. LLVM opaque pointers no
reemplazan la firma semántica verificada. Release final llama el destroy thunk
una vez; captures owning generan su glue normal. El box no es el pointer de
código que espera `Function`.

### 9.1 Header, layout y alignment

`ClosureABI-v1` usa tres words del target, sin padding intermedio:

| Offset | Field | Tipo ABI |
|---:|---|---|
| `0` | `strong_count` | `usize`, non-atomic, inicialmente `1` |
| `W` | `invoke_thunk` | code pointer de un word |
| `2W` | `destroy_thunk` | code pointer de un word |

`W = sizeof(usize) = sizeof(data pointer) = sizeof(code pointer)` es requisito
del target para soportar este ABI. Si un target no lo cumple, Closure V1 no está
disponible hasta definir otro ABI versionado; no se altera silenciosamente el
layout. El header tiene size `3W` y alignment `W`. El payload comienza en
`align_up(3W, payload_alignment)` y sus fields siguen el orden canónico de
§4.2 con el data layout ordinario del target. El alignment y size de allocation
son respectivamente `max(W, payload_alignment)` y el size total redondeado a
ese alignment, ambos calculados con overflow checked. El allocator recibe size
y alignment explícitos.

Un carrier apunta al byte cero del header. `strong_count` nunca es cero en un
owner vivo; overflow es trap abortivo. Al pasar de uno a cero, release adquiere
el `destroy_thunk` antes de escribir cero y lo invoca exactamente una vez. El
destroy thunk recibe el box todavía asignado, destruye payload inversamente y
lo libera con el mismo size/alignment. No hay weak owners en V1.

### 9.2 Thunks y ownership cross-module

El invoke thunk usa `Aether ABI v1`, la misma lowering/calling convention que
una función Aether de firma `R(P...)`, precedida por un primer parámetro
no-null `ptr box`. Su tipo completo se deriva del `Closure<(P...),R>` verificado.
Puede unwind exactamente como el body. El destroy thunk tiene firma
`void(ptr box)`, es `nounwind` y usa la misma ABI; fallar durante Drop conserva
el comportamiento abortivo vigente.

Retain y release cross-module se realizan mediante los símbolos runtime
versionados `aether_closure_retain_v1(ptr) -> ptr` y
`aether_closure_release_v1(ptr) -> void`. Tienen linkage público de runtime,
`nounwind`, semántica non-atomic y no ejecutan user code salvo el destroy thunk
final de release. El compiler puede inlinearlos sólo si preserva exactamente
este contrato observable y los counters de qualification. Un módulo consumidor
no necesita conocer el payload.

Invoke/destroy glue se emite una vez en el módulo propietario de la expresión,
con linkage deduplicable/visibility compatible con el formato de objeto del
target. Sus direcciones se almacenan en cada box; no se buscan en un registry,
RTTI, TLS ni por nombre durante invocation o destruction. El módulo/package que
exporta closures debe mantener ese código link-reachable mientras puedan
existir valores retornados, como cualquier función referenciada.

### 9.3 Identidad y compatibilidad

La identidad compiler-internal de una expresión es la tupla estable
`(PackageId, ModuleId, source LambdaId, GenericInstanceId, ClosureABI-v1)`.
`LambdaId` proviene de identidad source estable del módulo, no del orden de un
hash map; el mangling incluye un hash ABI de parámetros, resultado y tipos/modos
de captures. Esa identidad gobierna symbols, COMDAT/deduplication, reachability
y diagnósticos cross-module. No define igualdad source entre valores Closure:
V1 no ofrece comparación de identidad de closures.

Metadata de package registra `ClosureABI-v1`, Aether ABI version, target triple,
data-layout fingerprint y compiler ABI epoch. El linker/package loader rechaza
una mezcla incompatible antes de ejecutar; no adapta headers ni thunks por
heurística. Compilers distintos son compatibles sólo si producen metadata
idéntica para esos campos y respetan este contrato. El payload sigue privado al
módulo propietario y nunca forma parte de la firma pública.

## 10. Exceptions y unwind

Una invocation es conservadoramente may-unwind, igual que `IndirectCall`.
Throws no forman parte de la identidad del callable.

- El carrier borrow termina en ambos edges.
- Una closure lvalue propiedad del caller no se destruye por el hecho de que su
  body lance.
- Una closure transferida a un callee se limpia allí si el callee abandona por
  unwind sin retornarla.
- Captures se destruyen sólo cuando cae el último owner del box, no al final de
  cada invocation.
- Si el último release ocurre durante unwind, el destroy thunk no puede lanzar;
  sigue el contrato actual de Drop/glue.
- Catch/finally recibe el mismo `ExceptionEvent`; closure cleanup no sustituye
  la excepción activa.

Una closure puede usarse durante cleanup compiler-generated sólo donde hoy se
permite una call. EXCEPTION-V4 mantiene `finally` no-throwing y prohíbe calls de
usuario dentro de `finally`; closures no abren una excepción a esa regla.

## 11. Calls indirectas y optimización

O0 debe conservar allocation, header, ARC lógico y indirect invoke. O2 puede:

- propagar `LambdaId` exacto y direct-call el invoke thunk;
- inlinear el body;
- scalar-replace un environment que no escapa;
- eliminar retain/release balanceados;
- stack-promote o eliminar el box con escape proof completa.

Estas transformaciones no son requisito funcional V1 y deben conservar
operations semánticas hasta la frontera de optimización verificada. Un phi de
closures diferentes, parámetro público, return o storage desconocido conserva
dispatch indirecto. No se promete zero-cost abstraction.

La prueba de target no puede basarse sólo en igualdad de signature. Debe seguir
provenance exacta de `ClosureCreate`/Alias/Move/phi, como OOP-OPT hace con sus
carriers, y abandonar la devirtualización ante mezcla o escape desconocido.

## 12. Relación con APIs existentes

Las APIs actuales continúan exactas:

```aether
Function<(double), double>
```

Por tanto:

| Valor | `plots.plotFunction` / Newton actuales |
|---|---|
| función top-level compatible | aceptado, sin cambio |
| lambda anónima sin capture | aceptado como `Function` |
| variable `Function` | aceptado |
| closure con capture | rechazado: `Closure` no es `Function` |
| variable `Closure` aunque no capture | no conversión implícita V1 |

Esto aplica también a integración, Newton-Raphson, least squares y callbacks
que hoy declaren `Function`. Permitir una closure capturante sin cambiar esa
firma requeriría cambiar el ABI de `Function`, usar estado global/trampoline o
especializar toda call de manera no composable. Ninguna opción preserva el
contrato actual.

Milestones posteriores razonables:

1. overloads explícitos que acepten `Closure<...>`;
2. un compiler-known `Callable<(P...),R>` erased que pueda adaptar Function y
   Closure con un carrier/ownership uniforme;
3. generic callables por capability, después de diseñar constraints de call y
   Alias.

No se recomienda convertir `Function` en supertype ni interface. Una futura
abstracción general debe mantener adapters explícitos y costos inspeccionables.
Este trabajo no modifica ninguna API.

## 13. Jerarquía de invocación V1

V1 no crea una jerarquía nominal. Conserva dos tipos hermanos:

| Tipo | Environment | Ownership | Invocation |
|---|---|---|---|
| `Function<(P),R>` | no | Copy/no-drop | repeatable |
| `Closure<(P),R>` | owning read-only | ARC Alias/Drop | repeatable |

Capacidades futuras, sin nombres normativos:

- repeatable read: V1 Closure;
- repeatable write/shared state: necesita receiver/capture mutation rules;
- consuming invocation: puede mover captures y deja el callable consumed.

No se presume subtyping entre ellas. En particular una consuming closure no
puede satisfacer automáticamente una API que invoca N veces, y una mutable no
debe esconder su requirement detrás del mismo tipo read-only.

## 14. Dependencias y bloqueos reales

Antes de implementation hacen falta:

1. agregar `TypeData::Closure` con propiedades/layout uniformes y sustitución;
2. implementar el ABI cross-module y helpers ARC fijados en §9;
3. free-variable/capture analysis con diagnostics source-spanned;
4. synthetic function/environment identities estables y reachability;
5. operaciones/verificadores HIR, MIR y SSA descritos en §8;
6. lifecycle de `ClosureAlias`, Transfer, replacement, Drop y conditional Drop;
7. borrow de invocation con cleanup normal/unwind;
8. backend create/invoke/destroy y counters de heap/ARC;
9. dumps, diagnostics, LSP grammar/highlighting y package ABI qualification;
10. levantar sólo los gates de return necesarios para Closure V1;
11. mantener cerrados los gates de aggregate/container/class storage hasta sus
    verticales dedicados.

No bloquean el mínimo: mutable captures, borrow captures, general `Callable`,
inline environments, closure specialization, generic `Alias` y devirtualization
propia. Son milestones posteriores, no atajos permitidos en V1.

## 15. Qualification requerida

### 15.1 Matriz funcional y lifecycle

| Caso | V1 mínimo | Resultado/evidencia |
|---|:---:|---|
| lambda 0/1/N args sin capture | sí | `FunctionRef` existente; no heap/ARC |
| lambda void result | sí | firma exacta y call repetida |
| Copy scalar/struct automático | sí | snapshot; source sigue válido |
| Alias string/class/interface automático | sí | owner independiente; source válido |
| Copy/Alias explícito | sí | override válido y mismo lifecycle de categoría |
| Move explícito | sí | root source invalidado al adquirir |
| mezcla explícita/implícita | sí | orden §4.2 y modes exactos |
| free Move-only omitido de `capture` | sí, negativo | exige `capture(move name)` con spans |
| capture duplicado/inexistente/sombreado | sí, negativo | rechazo source-spanned |
| capture explícito no usado | sí | warning obligatorio; adquisición preservada |
| capture de reference/view con `copy` | sí, negativo | non-Storable/lifetime rejection |
| Alias de otra Closure | sí | box compartido; final destroy una vez |
| whole-root Move Buffer/aggregate | sí | source moved; capture drop una vez |
| partial Move field/index | sí, negativo | partial move rejection |
| shadowing de parámetro/local | sí | captura sólo el binding resuelto |
| self-capture en initializer | sí, negativo | outer binding o unresolved; nunca self mágico |
| nested lambda/callback escapable | sí | captura transitiva, owners y clasificación exactos |
| mutation/ref-mut/consume capture | sí, negativo | read-only environment diagnostic |
| closure local assignment | sí | Alias before old release; self-assignment safe |
| pass lvalue/fresh | sí | Alias/Transfer respectivamente |
| return closure | sí | survives scope; exact cross-module ABI |
| repeated calls | sí | same captures, no per-call consumption |
| invocation throws then caller catches | sí | owner remains callable if still live |
| closure owner unwinds out | sí | captures/box cleaned once |
| conditional move/return | sí | conditional Drop flags exact |
| struct/enum/Array/List storage | posterior | dedicated storage qualification |
| class field storage/cycle | posterior | explicit ARC cycle decision |
| ref/ref-mut capture | posterior, negative in V1 | no dangling references |
| mutable/once closure | posterior, negative in V1 | capability not conflated |
| generic lambda | posterior | no implicit monomorphization model |

### 15.2 IR corruption

Cada fase debe mutarse independientemente, sin confiar en rechazo previo:

- lambda target/signature/LambdaId incorrectos;
- explicit/implicit bit, capture mode, order, count, type, source, binding
  identity, use span or field recipe adulterados;
- hidden reference/view inserted into environment;
- missing/duplicate Alias acquisition;
- Move changed to Copy, stale source use, duplicate Transfer;
- missing/duplicate/premature Drop or release;
- result bound on unwind edge;
- call arity/argument/result/signature mismatch;
- invoke thunk or destroy recipe from another environment;
- phi duplicating one owner on two continuing paths;
- borrow carrier without matching call/EndBorrow or crossing invalidation;
- cleanup block that leaks a capture, drops twice or changes event identity.

### 15.3 LLVM/runtime evidence

Qualification must inspect, for O0 and O2:

- Function lambda remains one code pointer and emits no closure allocation;
- Closure carrier is one box pointer but invoke prototype includes env first;
- exact header offsets/alignment and payload field layout;
- stable thunk prototypes, ABI metadata, mangling and cross-module identity;
- no `bitcast`, `ptrtoint`, global registry or TLS trampoline authority;
- call vs invoke and correct landing pads;
- exact alloc/free, retain/release, capture-drop and destroy counters;
- zero leaks/double frees in normal return, early return, throw/catch/finally,
  conditional owner paths and never-invoked closures;
- target body/address reachability when referenced only from a closure header;
- output parity O0/O2 and sanitizer/heap instrumentation where available.

### 15.4 Regression gates

Mandatory regressions include function values, default parameters, borrow
ergonomics, class/interface ownership, OOP optimization, generic capabilities,
owning replacement, exception V1..V4, Plots function sampling, Newton consumers,
workspace, formatter, clippy and differential suite.

## 16. Milestones

### 16.1 `ANONYMOUS-FUNCTIONS-V1`

- arrow expression-body syntax with typed parameters;
- no captures;
- contextual/inferred `Function`;
- synthetic target and existing FunctionRef/IndirectCall path;
- current Function storage gates unchanged;
- free-variable/shadowing negatives, O0/O2 and unwind qualification;
- HIR/MIR/SSA corruption must not reclassify it as Closure.

Este vertical no agrega runtime y puede implementarse/calificarse primero.

### 16.2 `OWNING-CLOSURES-READ-V1`

- `Closure<(P...),R>`;
- optional partial `capture(copy/alias/move ...)` plus automatic Copy/Alias;
- explicit Move required for Move-only values and no implicit Move/Clone/Alias;
- heap box, intrinsic Closure Alias, Transfer and Drop;
- locals, assignment, arguments, returns and repeatable read invocation;
- free-variable/shadowing, deterministic acquisition, partial cleanup,
  self/nested-lambda and unused-explicit-capture rules from §4;
- exact cross-module `ClosureABI-v1` from §9;
- no borrowed/mutable/consuming captures;
- aggregate/container/class storage todavía gated;
- independent O0/O2, ownership/unwind and HIR/MIR/SSA corruption qualification.

### 16.3 Posteriores

1. Closure storage in struct/enum/Array/List plus Function storage debt.
2. Class fields and explicit ARC-cycle policy.
3. Function/Closure adapters or general Callable.
4. Mutable closure capability.
5. Consuming closure capability.
6. Borrowed non-escaping closures with regions.
7. Generic lambda inference and generic `Alias` capability.
8. Inline/SBO environment and provenance-based devirtualization.

## 17. Riesgos

| Riesgo | Impacto | Mitigación propuesta |
|---|---|---|
| confundir one-pointer carriers | ABI corruption | tipos/ops distintos; verifier impide Function/Closure interchange |
| dangling borrowed capture | memory unsafety | no ref/view captures; transitive Storable check |
| owner perdido/duplicado | leak/double free | explicit Alias/Move/Drop ledgers and corruption tests |
| exception durante invocation | leak/event replacement | explicit unwind edge and same-event cleanup |
| hidden allocation cost | performance surprise | distinct `Closure` type/dumps; no implicit Function conversion |
| ARC cycle through class field | permanent leak | class storage gated until cycle policy |
| mutable shared environment | semantic races/alias surprise | immutable captures V1 |
| generic erasure loses Alias | surprising consumption | Alias is concrete-only; no generic claim |
| incompatible public layout | package ABI break | fixed/versioned §9 header and metadata rejection |
| optimizer removes needed keepalive | UAF | carrier borrow remains semantic through VerifiedSsa |
| anonymous symbol collisions | wrong target/reachability | stable module + LambdaId + instance mangling |
| implementation copies Rust/C#/C++ model | mismatch with Aether | use Aether Copy/Alias/Move/ref contracts and qualification |

## 18. Registro de decisiones aceptadas

Las decisiones antes pendientes quedan resueltas normativamente:

1. **Sintaxis:** arrow lambda `(T x) => expression`, parámetros tipados y body
   de una expresión. `capture(...)` es opcional y parcial. No se agregan
   `@(...)`, `fn`, `let` ni declaraciones nuevas; `var` infiere locals.
2. **Captura automática:** `Copy` captura snapshot por Copy; owner con Alias
   intrínseco captura por Alias; Move-only exige `capture(move name)`. Nunca hay
   Move, Clone/deep-copy o Alias-from-Storable implícitos.
3. **Captura explícita:** `copy`, `alias` y `move` tienen prioridad sólo cuando
   la operación es válida. Duplicados/entradas inválidas son errores y entradas
   no usadas generan warning sin eliminar su lifecycle.
4. **Semántica:** resolución léxica, shadowing, orden canónico, evaluación
   parcial, rollback, self-capture, nesting, read-only environment, repeated
   invocation y owner lifecycle quedan fijados en §§3–4 y §10.
5. **Carrier/ABI:** `ClosureABI-v1` es el header heap de tres words, payload
   alineado, thunks y helpers versionados de §9. Metadata incompatible se
   rechaza; no hay adaptación implícita cross-module.
6. **Alias:** `Closure` posee Alias intrínseco ARC aunque Alias no sea una
   capability generic pública. Captures Alias son owners independientes, no
   deep copies.
7. **Frontera V1:** se admiten locals, replacement, arguments y returns; siguen
   gated aggregate/container/class storage y todas las referencias/views.
8. **Tipos separados:** `Function` conserva un code pointer Copy/no-drop;
   `Closure` conserva un box pointer owning. No existe conversión implícita en
   ninguna dirección.
9. **Verticales:** `ANONYMOUS-FUNCTIONS-V1` y `OWNING-CLOSURES-READ-V1` se
   implementan y califican independientemente según §§15–16. Ninguno añade
   reglas especiales para Plots o métodos numéricos.

Un cambio futuro en cualquiera de estas decisiones requiere una nueva revisión
arquitectónica conjunta de TypeProperties, ABI, ownership, IR y qualification;
no puede introducirse como detalle de implementación.

## 19. Decisión final

Adoptar la separación:

```text
anonymous, no captures
    -> synthetic top-level target
    -> existing Function / FunctionRef / IndirectCall

capturing, read-only, owning
    -> Closure<(Args), Return>
    -> ARC heap environment + invoke/destroy glue
    -> ClosureCall (env hidden argument)
```

Es la alternativa examinada que preserva literalmente el ABI y las
propiedades de `Function`, permite return seguro sin regiones heap, expresa
Copy/Alias/Move con el vocabulario de Aether y deja mutable/once/borrowed
closures para decisiones separadas.

Con las decisiones de §18 y el ABI de §9 resueltos coherentemente, la
arquitectura se declara **CLOSED**. Esto no declara implementado ni qualified
ninguno de los verticales y no elimina sus gates de aceptación independientes.
