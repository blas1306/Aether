# Aether — FIRST-CLASS-CALLABLES — Architecture Exploration

Estado: **EXPLORATION COMPLETE; PROPOSED; NO NORMATIVO**, 2026-11-04.

Este documento investiga cómo una API puede aceptar valores invocables de una
firma exacta sin borrar las diferencias entre `Function<(Args), Return>` y
`Closure<(Args), Return>`. No autoriza implementación, no cambia ningún ABI y
no declara `CLOSED` ninguna decisión.

## 1. Resultado ejecutivo

La recomendación es una solución híbrida en dos niveles, introducida de forma
incremental:

1. modelar **invocabilidad repetible y read-only** como una capability
   compiler-known, estructural y parametrizada por firma, provisionalmente
   escrita `Invocable<(P...), R>`;
2. no introducir todavía un tipo owning `Callable`; reservarlo para erasure
   explícito, almacenamiento heterogéneo y retornos cuyo tipo concreto de
   callable no pueda permanecer en la firma;
3. estudiar después un `CallableRef<(P...), R>` no owning y no escapable para
   fronteras invoke-only que necesiten un ABI no genérico sin pagar allocation
   o ARC de adaptación.

La capability no es una interface nominal y no convierte carriers. Selecciona
estáticamente, al monomorfizar, uno de los protocolos ya existentes:

```text
C = Function<(P...), R>  -> FunctionRef / IndirectCall / code pointer
C = Closure<(P...), R>   -> ClosureBorrow / ClosureCall / EndClosureBorrow
```

“Estáticamente” significa que el compiler conoce cuál protocolo usar. No
significa que conozca el target final: una call a `Function` sigue siendo
indirecta y una call a `Closure` sigue cargando su `invoke_thunk`.

Un eventual `Callable` owning debe ser un tercer tipo, con representación y
lifecycle propios, y sólo debe construirse mediante adapters explícitos. No
debe alterar el ABI de `Function` ni `ClosureABI-v1`.

## 2. Alcance y no objetivos

La exploración cubre:

- APIs que invocan durante una llamada;
- APIs que invocan varias veces;
- callbacks almacenados o retornados;
- genéricos, inferencia y monomorfización;
- ownership por valor y borrowed invocation;
- exceptions, ARC, Drop y ABI;
- efectos en HIR, MIR, SSA y sus verificadores;
- compatibilidad entre módulos fuente de una `CompilationSession`.

Quedan fuera de una primera implementación:

- closures mutables o consuming/once;
- capturas borrowed escapables;
- interfaces nominales callable;
- generic lambdas;
- ABI entre artefactos Aether compilados independientemente;
- almacenamiento de callable en aggregates antes de abrir y calificar los gates
  de storage correspondientes;
- trampolines globales, TLS, registries o adaptación mediante estado global.

## 3. Preflight: contratos reales observados

### 3.1 Tipos y properties

`TypeArena` contiene variantes canónicas distintas:

```text
TypeData::Function { parameters, result }
TypeData::Closure  { parameters, result }
```

Las dos identidades son estructurales e invariantes por firma, pero sus
properties son uniformemente diferentes:

| Tipo | Copy | Relocatable | Storable | needs_drop | Alias |
|---|:---:|:---:|:---:|:---:|---|
| `Function<(P...),R>` | sí | sí | sí | no | innecesario; copiar duplica el pointer |
| `Closure<(P...),R>` | no | sí | sí | sí | intrínseco, ARC, no generic |

`TypeProperties` contiene hechos concretos de lifecycle. No es un trait system.
`Storable` no implica `Copy`, `Alias`, invocabilidad ni ausencia de Drop.
`Alias` no pertenece al vocabulario público actual de constraints.

El vocabulario cerrado vigente contiene capabilities estructurales y numéricas
como `Copy`, `Relocatable`, `Storable`, `Add`, `Mul` e `IEEEFloat`. Las
constraints actuales son nombres sin parámetros; una capability de llamada
por firma requiere una extensión explícita del modelo, parser y metadata, no
puede fingirse como una interface existente.

### 3.2 Function

`Function<(P...),R>` es exactamente un code pointer y no posee environment.
Una referencia produce `FunctionRef`; invocarla produce `IndirectCall` en HIR,
MIR y SSA. Cada fase verifica target/firma, aridad, argumentos y resultado. LLVM
deriva el prototype de la firma canónica y llama al pointer sin `bitcast` ni
`ptrtoint` como autoridad de tipos.

Una `IndirectCall` es conservadoramente may-unwind. Reachability conserva un
target usado sólo mediante `FunctionRef`.

Las lambdas sin captura siguen esta misma ruta. No crean box, ARC ni ABI
paralelo.

### 3.3 Closure

`Closure<(P...),R>` es un owner de un pointer a box. `ClosureABI-v1` fija:

| Offset | Campo |
|---:|---|
| `0` | `usize strong_count` |
| `W` | `ptr invoke_thunk` |
| `2W` | `ptr destroy_thunk` |
| `align_up(3W, payload_alignment)` | payload privado |

El thunk de invocación tiene prototype lógico `R(ptr box, P...)`. El de
destrucción es `void(ptr box) nounwind`. Los helpers ARC versionados son
`aether_closure_retain_v1` y `aether_closure_release_v1`.

La invocación abre un borrow sobre el carrier, evalúa argumentos, ejecuta
`ClosureCall` y cierra mediante `EndClosureBorrow` en success y unwind. No hay
retain/release por invocación. El último release destruye las capturas en orden
inverso y libera el box.

### 3.4 Ownership de parámetros y argumentos

Las reglas relevantes son:

- un valor Copy se duplica;
- un owner fresh se transfiere al parámetro by-value;
- un lvalue `Closure` usado by-value adquiere un owner independiente mediante
  `ClosureAlias`, con retain;
- un Move whole-root transfiere e invalida el source; no hay partial moves
  generales;
- un parámetro owning by-value entra al callee como obligación `Owned` y se
  transfiere o limpia exactamente una vez en cada salida;
- un parámetro `ref T` puede recibir un implicit shared call borrow exacto. El
  borrow no crea owner, Alias, retain, Clone ni Move y termina en todas las
  salidas no abortivas de la call.

La sintaxis general de Move source sigue siendo una decisión más amplia del
lenguaje. Esta propuesta no inventa una conversión implícita para ocultarla. Un
adapter owning futuro que quiera consumir un lvalue debe exponer un contrato
source explícito y calificado.

### 3.5 Generics y monomorfización

Las funciones generic se validan contra capabilities cerradas, se sustituyen y
quedan concretas antes de MIR. `Function<(T),T>` y `Closure<(T),T>` ya participan
en sustitución estructural.

Una capability de invocación puede aprovechar esa frontera: el HIR generic debe
conservar una operación de capability con firma exacta; la especialización debe
resolverla a `IndirectCall` o `ClosureCall`; MIR nunca debe recibir un callee
generic residual.

Una propiedad importante del modelo actual es que todas las funciones de una
misma firma comparten el mismo `TypeId Function`, y todas las closures de esa
firma comparten el mismo `TypeId Closure`. Especializar por el tipo `C` produce,
como máximo para V1, una instancia Function y una instancia Closure por
combinación de parámetros generic, no una instancia por lambda o target.

### 3.6 APIs reales

La API productiva más clara es:

```aether
public Figure2D plotFunction(
    Function<(float64), float64> target,
    float64 a,
    float64 b,
    usize sampleCount,
    ref FigureOptions options)
```

El repositorio también contiene consumidores `Function` reales para:

- Newton-Raphson y bisección;
- derivación numérica de orden N;
- modelos/bases de mínimos cuadrados;
- ejemplos de métodos numéricos con alias `ScalarCallable`.

`plots.plotFunction` llama el target N veces, puede propagar exceptions y sólo
lo necesita durante la llamada. Newton y derivación comparten esas propiedades.
Un registry de callbacks o una función que elija entre callable kinds plantea
un problema diferente: necesita storage o erasure, no sólo invocación.

### 3.7 Frontera entre módulos

Function y Closure funcionan entre módulos/packages fuente compilados en la
misma `CompilationSession`. No existe todavía una promesa de ABI para artefactos
Aether independientes. Una solución generic puede monomorfizar consumidores
desde fuentes transitivas. Un erased `Callable` necesitará además un ABI interno
versionado propio; eso no prueba compatibilidad binaria independiente.

### 3.8 Mapa de implementación inspeccionado

| Contrato | Autoridad actual |
|---|---|
| TypeData, TypeProperties, capabilities, substitution | `compiler-next/crates/aether-frontend/src/types.rs` |
| generic constraints, inference, call adaptation, HIR callable ops | `compiler-next/crates/aether-frontend/src/hir.rs` |
| grammar de types/constraints/lambdas | `compiler-next/crates/aether-frontend/src/parser.rs` |
| `FunctionRef`, `IndirectCall`, Closure ownership y EndBorrow MIR | `compiler-next/crates/aether-middle/src/mir.rs` |
| mismas operaciones y verificación SSA | `compiler-next/crates/aether-middle/src/ssa.rs` |
| Function/Closure LLVM lowering y runtime helpers | `compiler-next/crates/aether-backend-llvm/src/lib.rs` |
| Plots real | `plots/src/lib.ae` |
| consumidores numéricos | `examples/newton`, `examples/numerical_methods`, `examples/n-esimaDerivada.ae`, `examples/minimos_cuadrados` |

No hay hoy una abstracción intermedia que pueda reutilizarse sin ampliar al
menos el frontend generic o introducir un nuevo carrier erased.

## 4. Invariantes de esta exploración

Todas las alternativas deben preservar:

1. `FunctionABI-v1`: un code pointer, Copy, no Drop.
2. `ClosureABI-v1`: owner de box, header de tres words, ARC y Drop.
3. Ninguna conversión implícita `Function <-> Closure`.
4. Invocación Closure borrowed y `EndClosureBorrow` en normal/unwind.
5. Ninguna captura borrowed escapable.
6. Ningún Alias inferido desde `Storable`.
7. Ninguna conversión implícita que asigne, retenga o borre ownership sin un
   contrato aprobado.
8. Distinción entre lvalue, fresh owner y transferencia explícita.
9. Repeatable-read: invocar no consume el callable ni sus capturas.
10. Firma exacta e invariante; no hay adaptación por layout, widening o
    subtyping.
11. No hay interface nominal ficticia, registry ni trampoline global/TLS.
12. Las calls indirectas y de closure siguen siendo may-unwind.

## 5. Alternativa A — overloads explícitos

### 5.1 Superficie pública

```aether
public Figure2D plotFunction(
    Function<(float64), float64> target,
    float64 a, float64 b, usize n, ref FigureOptions options) {
    // implementación Function
}

public Figure2D plotFunction(
    Closure<(float64), float64> target,
    float64 a, float64 b, usize n, ref FigureOptions options) {
    // implementación Closure
}
```

Aceptaría exactamente:

```aether
var square = (float64 x) => x * x;          // Function
float64 scale = 2.0;
var scaled = (float64 x) => scale * x;      // Closure

plotFunction(square, -1.0, 1.0, usize(101), options);
plotFunction(scaled, -1.0, 1.0, usize(101), options);
```

No existe conversión: overload resolution selecciona una firma exacta después
de clasificar la lambda.

### 5.2 Semántica y ownership

- El overload Function copia un pointer y no crea Drop.
- Un `Closure` lvalue pasado by-value ejecuta un retain al entrar y un release
  al terminar el parámetro; una closure fresh se transfiere.
- Cada invocation de Closure usa borrow, no ARC.
- Ambos overloads preservan las reglas de ownership de los argumentos `P...`.
- Ambos pueden almacenar o retornar su tipo concreto sólo donde sus gates de
  storage/return ya estén abiertos.

### 5.3 Dispatch, ABI y coste

La selección del overload es estática. Dentro del body, Function usa
`IndirectCall` y Closure usa `ClosureCall`; ninguno garantiza target directo.
No hay adapter ni allocation adicional. La closure capturante ya pagó su box al
crearse.

La desventaja es duplicación source y de código. Para Newton con target y
derivada se necesitan cuatro combinaciones si se pretende aceptar cada
parámetro independientemente:

```text
Function / Function
Function / Closure
Closure  / Function
Closure  / Closure
```

Con N callables independientes, la familia puede crecer como `2^N`. Un helper
común que elimine esa duplicación termina necesitando precisamente una
capability o erasure.

### 5.4 IR y qualification

No necesita nuevas operaciones IR. Sí necesita overload resolution robusta y
qualification duplicada de success/unwind para ambos spines. No introduce una
nueva fuente de corrupción de carrier, porque cada body conserva tipos exactos.

### 5.5 Evaluación por casos

| Caso | Resultado A |
|---|---|
| `plots.plotFunction` | viable; dos overloads, loop duplicado o helper todavía inexistente |
| Newton con dos callables | viable; cuatro overloads para combinación completa |
| integración/derivación | viable; dos overloads por API |
| mínimos cuadrados, una función base-vector | viable; dos overloads |
| múltiples bases heterogéneas | no unifica storage Function/Closure |
| callback almacenado/retornado | conserva tipo concreto; no permite branch heterogéneo |
| invoke-once/multiple | correcto; repeatable-read |
| exceptions | ambos spines may-unwind; cleanup específico de cada tipo |

### 5.6 Veredicto

Es la opción de menor riesgo para una o dos APIs aisladas y puede ser un puente.
No escala como arquitectura común y hace muy difícil evitar duplicación en
Newton, optimización y familias numéricas amplias.

## 6. Alternativa B — `Callable<(P...),R>` owning erased

### 6.1 Tipo y superficie pública

Esta alternativa introduce un tercer tipo estructural:

```aether
Callable<(float64), float64>
```

No es supertype nominal de Function/Closure. Es un owner erased repeatable-read.
La API queda única:

```aether
public Figure2D plotFunction(
    Callable<(float64), float64> target,
    float64 a, float64 b, usize n, ref FigureOptions options);
```

Los adapters deben ser explícitos. Los nombres siguientes son sintaxis de
exploración, no una decisión normativa:

```aether
Callable<(float64), float64> a = eraseCallable(square);
Callable<(float64), float64> b = eraseCallable(scaled);       // lvalue: Alias
Callable<(float64), float64> c = moveIntoCallable(scaled);    // consume source

plotFunction(eraseCallable(square), -1.0, 1.0, usize(101), options);
plotFunction(eraseCallable(scaled), -1.0, 1.0, usize(101), options);
```

`moveIntoCallable` sólo puede existir después de fijar y calificar su contrato
source. No debe simularse como una optimización invisible de
`eraseCallable(lvalue)`.

### 6.2 Representación conservadora

La representación base más fácil de verificar es un pointer owning a un
`CallableBox` propio:

```text
CallableBox {
    strong_count;
    invoke_thunk;
    destroy_thunk;
    erased payload;
}
```

El header puede parecerse a `ClosureABI-v1`, pero debe tener identidad ABI
propia, helpers/versionado propios o una decisión normativa explícita de header
compartido. Igual layout accidental no autoriza reinterpretación.

- Adaptar Function guarda el code pointer en payload y requiere allocation.
- Adaptar Closure fresh transfiere el owner al payload; con box distinto,
  requiere una allocation wrapper.
- Adaptar Closure lvalue requiere además Alias/retain del closure contenido.
- Invocar llama al thunk erased, que luego llama al Function o Closure real.
- Alias de Callable retiene su box; Drop lo libera dinámicamente.

Una subvariante futura podría adoptar directamente un box Closure porque su
header ya ofrece invoke/destroy. Eso evitaría el wrapper de Closure, pero acopla
formalmente `CallableABI` a `ClosureABI-v1`, requiere demostrar que retain,
release, firma y reachability son idénticos y no puede inferirse sólo porque
ambos carriers sean un pointer. No se presupone en el baseline.

### 6.3 Properties y storage

La opción conservadora tendría:

| Propiedad | `Callable` owning |
|---|---|
| Copy | no |
| Relocatable | sí |
| Storable | sí, sujeto a gates de storage |
| needs_drop | sí |
| Alias | intrínseco ARC, no derivado de Storable |
| invocation | borrowed y repeatable |

Permite retornar una única familia erased y, cuando se abran los gates, guardar
Function y Closure mezclados en `Array<Callable<...>>`, fields o payloads.

### 6.4 IR y ABI

Requiere operaciones semánticas nuevas hasta `VerifiedSsa`, por ejemplo:

```text
CallableCreateFunction
CallableCreateClosure
CallableAlias
CallableBorrow
CallableCall
EndCallableBorrow
CallableDrop
```

Los verificadores deben impedir carrier confusion, adapter de firma distinta,
payload/destroy recipe adulterado, owner duplicado, borrow sin final y unwind
que pierda el box o la excepción activa.

El ABI de Function y Closure permanece intacto. El coste aparece en el adapter
y en el dispatch adicional del nuevo tipo, no en esos ABIs.

### 6.5 Inferencia y ergonomía

No debe haber conversión contextual automática desde Function o Closure: para
Function escondería una allocation; para Closure puede esconder allocation,
retain y otro nivel de dispatch. Expected type puede validar el resultado del
adapter, pero no insertarlo.

Una vez erased, la inferencia ordinaria ve sólo `Callable<sig>` y pierde el
kind original. No puede recuperar Function/Closure ni devirtualizar sin
provenance exacta del adapter.

### 6.6 Evaluación por casos

| Caso | Resultado B |
|---|---|
| `plots.plotFunction` | una firma, pero cada caller debe adaptar y puede asignar |
| Newton/integración/derivación | una implementación; adapters en cada boundary |
| mínimos cuadrados | permite callback modelo erased; arrays mixtos tras storage gate |
| callback almacenado/retornado | caso fuerte: tipo uniforme y dispatch dinámico |
| invoke multiple | correcto; borrow por call, sin consumir Callable |
| invoke-only | funcional pero paga erasure/posible allocation innecesaria |
| exceptions | thunk y underlying call may-unwind; mismo event debe sobrevivir |

### 6.7 Veredicto

Resuelve composición dinámica y storage, pero es demasiado costoso como
mecanismo único para algoritmos numéricos invoke-only. Debe ser explícito y no
es el primer milestone recomendado.

## 7. Alternativa C — capability genérica con especialización estática

### 7.1 Capability propuesta

Sintaxis provisional:

```aether
public Figure2D plotFunction<C: Invocable<(float64), float64>>(
    C target,
    float64 a, float64 b, usize n, ref FigureOptions options) {
    // ...
    float64 y = target(x);
    // ...
}
```

Satisfacción V1 cerrada:

```text
Function<(P...),R> satisfies Invocable<(P...),R>
Closure<(P...),R>  satisfies Invocable<(P...),R>
```

No satisfacen la capability por V1:

- structs/classes que casualmente tengan un método `call`;
- interfaces nominales;
- `Storable` generic;
- firmas con conversions en parámetros o retorno;
- closures mutable o consuming futuras.

La capability expresa tres garantías: firma exacta, invocation repeatable y
receiver observado/borrowed durante cada call. No implica `Copy`, `Storable`,
`Alias` ni layout.

### 7.2 Ejemplos aceptados

```aether
var square = (float64 x) => x * x;
float64 scale = 2.0;
var scaled = (float64 x) => scale * x;

plotFunction(square, -1.0, 1.0, usize(101), options); // C = Function<...>
plotFunction(scaled, -1.0, 1.0, usize(101), options); // C = Closure<...>
```

Newton usa una sola implementación y conserva kinds independientes:

```aether
public float64 newton<
    F: Invocable<(float64), float64>,
    D: Invocable<(float64), float64>
>(F target, D derivative, float64 x, float64 tolerance, int maxIterations) {
    // target(x) y derivative(x) usan evidencia distinta
}
```

Las cuatro combinaciones Function/Closure generan las especializaciones
necesarias, pero no cuatro cuerpos source.

### 7.3 Ownership by-value

Después de inferencia y sustitución, cada call site conoce el tipo concreto del
parámetro:

- Function se copia;
- Closure fresh se transfiere;
- Closure lvalue crea `ClosureAlias` y el parámetro se libera al salir;
- un callable Move-only futuro no puede ser duplicado sólo por satisfacer
  `Invocable`.

El body generic puede invocar `target`, moverlo una vez o retornarlo si su firma
lo permite. No puede duplicarlo, almacenarlo en una posición que exija
`Storable` ni fabricar Alias sólo por la capability.

Para una API que invoca N veces dentro de una llamada, el coste de un Closure
lvalue by-value es un retain/release por entrada de API, no por invocation. La
creación original del closure sigue requiriendo su box.

### 7.4 Variante borrowed

Una forma posterior evita incluso ese retain/release:

```aether
public float64 integrate<C: Invocable<(float64), float64>>(
    ref C target, float64 a, float64 b, usize n) {
    // `target(x)` significa invoke a través del shared ref, no Move de C.
}

integrate(square, 0.0, 1.0, usize(1000));
integrate(scaled, 0.0, 1.0, usize(1000));
```

El implicit shared argument borrow exacto y su inferencia ya tienen precedente,
pero invocar `ref C` requiere una regla nueva y explícita de capability. El
borrow debe abarcar evaluación de argumentos, call y unwind; no puede escapar,
guardarse ni retornarse.

No debe confundirse con capturar una referencia. El callable owner permanece
en el caller y el callee sólo observa su carrier durante la call externa.

### 7.5 HIR, MIR y SSA

El HIR generic necesita una operación proof-carrying, por ejemplo:

```text
CapabilityInvoke {
    callee,
    args,
    parameter: C,
    required_signature: (P...) -> R,
    mode: RepeatableRead
}
```

La monomorfización debe:

1. verificar que el type argument satisface la firma exacta;
2. sustituir todos los tipos;
3. reescribir a `IndirectCall` para Function o a la secuencia
   `ClosureBorrow/ClosureCall/EndClosureBorrow` para Closure;
4. volver a ejecutar los verificadores concretos;
5. rechazar cualquier `CapabilityInvoke` residual antes de MIR.

No se recomienda introducir un opcode LLVM “generic callable”. El backend debe
recibir sólo las operaciones concretas existentes.

Corruption tests deben alterar de forma independiente capability evidence,
firma, kind especializado, argumentos, resultado, borrow token y unwind edge.
Una evidencia `Invocable<sig A>` no autoriza `sig B`.

### 7.6 Dispatch, code size y rendimiento

La selección Function/Closure es estática. El target sigue dinámico dentro de
su carrier. Garantías defendibles:

- no allocation ni box nuevos por usar la capability;
- no adapter thunk nuevo;
- Function conserva su única indirect call;
- Closure conserva su header load e indirect invoke sin ARC por invocation;
- by-value Closure lvalue conserva un retain/release en la frontera de API;
- la forma `ref C` puede evitar ese ARC, con borrow tracking;
- O2 puede inlinear/devirtualizar sólo con provenance suficiente; no es una
  garantía source.

Code size: en el universo V1 hay hasta dos instancias por firma y combinación
generic, no una por lambda. Newton con `F,D` puede producir cuatro combinaciones.
Eso es menor duplicación source, no necesariamente menor código máquina que A.

### 7.7 Storage y retorno

Una función generic puede devolver `C` y preservar el tipo concreto:

```aether
public C relay<C: Invocable<(int), int>>(C callback) {
    return callback;
}
```

No puede devolver “Function o Closure según un branch” bajo un único `C`; el
type argument es único por instancia. Tampoco crea una colección heterogénea.
Esas necesidades exigen erasure.

### 7.8 Evaluación por casos

| Caso | Resultado C |
|---|---|
| `plots.plotFunction` | caso ideal; una fuente, hasta dos especializaciones |
| Newton | una fuente; F y D independientes; hasta cuatro combinaciones |
| integración/derivación | caso ideal, especialmente con `ref C` |
| mínimos cuadrados | modelo generic homogéneo; múltiples bases pueden usar parámetros C distintos |
| callback almacenado/retornado | preserva C concreto; no mezcla kinds dinámicamente |
| invoke multiple | capability repeatable-read lo expresa explícitamente |
| invoke-only | by-value funciona; `ref C` minimiza ARC de boundary |
| exceptions | operación capability y especialización deben conservar may-unwind/event |

### 7.9 Veredicto

Es el mejor primer mecanismo: evita adapters y duplicación source, mantiene
costes visibles por kind y reutiliza los spines verificados. Su coste real es
complejidad en constraints parametrizadas, HIR generic, monomorfización y code
size por combinaciones.

## 8. Alternativa D — híbrida: capability + erasure explícito

### 8.1 División de responsabilidades

Usar capability cuando el tipo concreto puede permanecer generic:

```aether
public float64 derivative<C: Invocable<(float64), float64>>(
    ref C target, float64 x, float64 h);
```

Usar `Callable` sólo al borrar el kind de manera intencional:

```aether
public Callable<(float64), float64> chooseModel(bool scaled) {
    if (scaled) {
        float64 factor = 2.0;
        return eraseCallable((float64 x) => factor * x);
    }
    return eraseCallable((float64 x) => x * x);
}
```

El ejemplo de retorno presupone que ambos adapters y el return/storage gate de
`Callable` han sido implementados. La diferencia de coste es visible en
`eraseCallable`.

### 8.2 APIs numéricas

Plots, Newton, integración, derivación y el callback modelo de mínimos cuadrados
deben preferir `Invocable`: el caller ya conoce el valor y el algoritmo sólo lo
observa durante su ejecución.

Un registry, event loop, graph de callbacks, branch que elige kinds diferentes
o `Array` que mezcla Function/Closure debe usar `Callable` explícito.

### 8.3 Compatibilidad y migración

La capability permite conservar calls source como `plotFunction(square, ...)`
y `plotFunction(scaled, ...)`. La migración de una API existente puede hacerse
en un milestone separado porque cambiar una declaración no generic por una
generic afecta mangling, address-taking de la API y resolución de overloads,
aunque no cambie los ABIs de los valores Function/Closure.

Durante transición puede conservarse el overload Function existente y añadir
un entry generic con nombre provisional o un wrapper pequeño. No debe duplicarse
el loop numérico: una vez disponible la capability, ambos entry points deben
delegar en una única implementación generic.

### 8.4 Coste

En el hot path generic el coste es el de C, sin erasure. El coste dinámico sólo
aparece donde source solicita `eraseCallable`. Esto evita hacer pagar
allocation/dispatch erased a toda API sólo porque algunos consumidores necesitan
storage heterogéneo.

### 8.5 Veredicto

Es la arquitectura objetivo recomendada, pero no exige implementar ambas
mitades a la vez. Capability entrega utilidad independiente; `Callable` puede
esperar a un caso de storage y a sus gates.

### 8.6 Evaluación por casos

| Caso | Resultado D |
|---|---|
| `plots.plotFunction` | capability; sin erasure en la ruta ordinaria |
| Newton | capabilities F/D independientes; sin cuatro cuerpos source |
| integración/derivación | capability borrowed cuando sólo observan el target |
| mínimos cuadrados | capability para modelo homogéneo; Callable sólo para bases heterogéneas almacenadas |
| callback almacenado/retornado | tipo concreto si es posible; Callable explícito si el kind varía |
| invoke multiple | capability repeatable-read o Callable borrowed internamente |
| invoke-only | capability/`ref C`; no pagar owner erased |
| exceptions | spine concreto en ruta generic; thunk erased sólo donde se solicitó erasure |

## 9. Alternativa E — `CallableRef` erased, borrowed y no escapable

### 9.1 Motivación

Existe un punto intermedio entre monomorfización y owner erased: una view
temporal uniforme para APIs que sólo invocan durante la llamada.

Sintaxis provisional con adapter explícito:

```aether
public Figure2D plotFunction(
    CallableRef<(float64), float64> target,
    float64 a, float64 b, usize n, ref FigureOptions options);

plotFunction(borrowCallable(square), -1.0, 1.0, usize(101), options);
plotFunction(borrowCallable(scaled), -1.0, 1.0, usize(101), options);
```

### 9.2 Representación

Un descriptor posible tiene dos words:

```text
CallableRef {
    ptr context_or_code;
    ptr invoke_adapter;
}
```

- Para Function, `context_or_code` lleva el code pointer y el adapter lo invoca
  con el prototype exacto.
- Para Closure, lleva el box borrowed y el adapter carga/llama el invoke thunk.
- El descriptor no es owner, no retiene y no se destruye.
- La región mantiene vivo el Function/Closure root hasta success o unwind.

No hay trampoline global: el adapter es código normal y todo estado viaja en el
descriptor.

### 9.3 Properties y restricciones

`CallableRef` sería Copy como descriptor, Relocatable, no Storable y no Drop.
Sus copias no pueden escapar de la región. No puede retornarse, guardarse,
capturarse, entrar en aggregates ni sobrevivir a la call que formó el adapter.

Adaptar un temporary Closure exige materializar su owner, prestar el box y
destruirlo después de la API, también en unwind.

### 9.4 Coste real

No necesita heap allocation ni ARC por adaptación, pero no es zero-cost:

- copia dos words;
- agrega al menos un adapter thunk indirecto;
- Function suele sufrir una capa de dispatch adicional;
- Closure puede sufrir adapter + carga de invoke thunk;
- requiere borrow/provenance y cleanup de temporales;
- O2 sólo puede colapsarlo con provenance completa.

Frente a capability reduce monomorfizaciones y ofrece un ABI uniforme. Frente a
Callable owning evita allocation/ARC, a cambio de prohibir storage/return.

### 9.5 IR y casos

Necesita operaciones distintas, por ejemplo `CallableRefCreate`,
`CallableRefCall` y `EndCallableRefBorrow`. El verifier debe impedir escape,
context mismatch, adapter de firma incorrecta, invalidación del root y missing
EndBorrow.

| Caso | Resultado E |
|---|---|
| Plots/Newton/integración/derivación | viable; ABI único, adapters explícitos |
| mínimos cuadrados invoke-only | viable |
| callback almacenado/retornado | imposible por diseño |
| invoke multiple | válido dentro de la región |
| exceptions | borrow y temporales se cierran/limpian en unwind |

### 9.6 Veredicto

Es una alternativa valiosa cuando code size o ABI generic sean problemas
medidos. No sustituye al owner erased y no debe preceder a la capability salvo
que exista evidencia de que monomorfización es inaceptable.

## 10. Matriz comparativa

### 10.1 Semántica y ergonomía

| Criterio | A Overloads | B Callable owning | C Capability | D Híbrida | E CallableRef |
|---|---|---|---|---|---|
| una implementación source | no, salvo helper nuevo | sí | sí | sí | sí |
| calls aceptan Function y Closure sin adapter | sí | no | sí | sí en ruta generic | no |
| storage heterogéneo | no | sí, tras gates | no | sí vía Callable | no |
| retorno heterogéneo | no | sí | no | sí vía Callable | no |
| preserva tipo concreto | sí | no | sí | según ruta | no |
| inferencia | overload exacto | expected Callable + adapter | infer C desde argumento | ambas | expected CallableRef + adapter |
| ownership visible | por firma | en adapter | por C concreto | explícito al borrar | borrow explícito |
| escala a N parámetros callable | `2^N` overloads | una firma | combinaciones monomorfizadas | generic hasta erasure | una firma |

### 10.2 Representación, dispatch y coste

| Criterio | A | B | C | D | E |
|---|---|---|---|---|---|
| cambia ABI Function/Closure | no | no | no | no | no |
| ABI propio | no | sí, owning | no | sólo Callable | sí, borrowed |
| allocation de adaptación Function | no | sí baseline | no | sólo erase | no |
| allocation de adaptación Closure | no | sí baseline | no | sólo erase | no |
| ARC por Closure lvalue boundary | una vez | retain inner + wrapper lifecycle | una vez by-value; cero con ref | según ruta | cero; borrow |
| dispatch Function | indirecto | erased + indirecto | indirecto | según ruta | adapter + indirecto |
| dispatch Closure | thunk | erased + thunk | thunk | según ruta | adapter + thunk |
| code size | bodies duplicados | uno | monomorfización | controlado por uso | uno + adapters |
| promesa zero-cost | no | no | no allocation de adapter; no direct-call guarantee | no | no |

### 10.3 IR y riesgo de corrupción

| Alternativa | HIR/MIR/SSA | Riesgo principal |
|---|---|---|
| A | operaciones existentes | divergencia entre overloads y coverage duplicada |
| B | nueva familia owning erased | carrier/payload confusion, leak/double drop, thunk incorrecto |
| C | `CapabilityInvoke` sólo en HIR generic; ops existentes tras specialization | evidencia/firma falsa o residual generic |
| D | suma de C y B, introducida por milestones | ampliar demasiado el primer vertical |
| E | nueva familia borrowed erased | escape/UAF, adapter equivocado, missing EndBorrow |

## 11. Casos de uso completos

### 11.1 Plots

Recomendación:

```aether
public Figure2D plotFunction<C: Invocable<(float64), float64>>(
    C target,
    float64 a,
    float64 b,
    usize sampleCount,
    ref FigureOptions options)
```

La forma by-value conserva el comportamiento natural de Function y Closure.
Una revisión posterior puede usar `ref C` para evitar el retain/release del
Closure lvalue. `Callable` owning no aporta valor mientras Plots no almacene el
callback.

### 11.2 Newton-Raphson

```aether
public float64 newton<
    F: Invocable<(float64), float64>,
    D: Invocable<(float64), float64>
>(ref F target, ref D derivative, float64 x0, float64 tolerance, int maxIterations)
```

Permite Function/Closure independientemente y evita cuatro overloads source.
El body puede invocar ambos múltiples veces. Cada call puede unwind.

### 11.3 Integración numérica

```aether
public float64 integrate<C: Invocable<(float64), float64>>(
    ref C target, float64 a, float64 b, usize panels)
```

Es el caso ideal para borrowed generic invocation: el callback no escapa, se
invoca N veces y no necesita owner adicional.

### 11.4 Derivación numérica

```aether
public float64 nthDerivative<C: Invocable<(float64), float64>>(
    ref C target, float64 x, int order, float64 h)
```

Reemplaza el `Function` rígido del ejemplo actual y acepta parámetros capturados
como `h`, escalas o datos auxiliares sin erasure.

### 11.5 Mínimos cuadrados con funciones base

Un modelo que devuelve todas las bases en una evaluación puede ser generic:

```aether
public Vector<float64,Column> fit<M: Invocable<(float64), Array<float64>>>(
    ref M model,
    ref Vector<float64,Column> samples,
    ref Vector<float64,Column> observations)
```

Si la API recibe varias bases como parámetros independientes, puede usar
`B0`, `B1`, ... pero eso no escala a aridad dinámica. Una colección dinámica
que mezcle functions y closures necesita `Array<Callable<(float64),float64>>`
y, antes, el vertical dedicado de storage.

### 11.6 Callbacks almacenados y retornados

- Retorno homogéneo conocido: devolver `Closure<sig>` o `C` conserva el tipo y
  evita erasure.
- Retorno que alterna Function/Closure: requiere `Callable<sig>` y adapters
  explícitos.
- Storage homogéneo: puede usar el tipo concreto cuando su storage gate esté
  abierto.
- Storage heterogéneo: requiere Callable owning; `CallableRef` es inválido.

### 11.7 Invoke-once frente a invoke-many

La capability recomendada no expresa cantidad exacta; expresa que cualquier
número de invocaciones read-only es válido. Por eso acepta invoke-once e
invoke-many sin conflarlo con una futura closure consuming.

Una futura capability `InvokeOnce` no debe satisfacer automáticamente
`Invocable`. Sus reglas de Move de captures, return y unwind son otro diseño.

### 11.8 Exceptions

Todos los mecanismos deben considerar cada invocation conservadoramente
may-unwind:

- Function conserva `IndirectCall` y su exceptional edge;
- Closure conserva carrier borrow y `EndClosureBorrow` en ambos edges;
- Capability conserva el efecto hasta especializar;
- Callable owning conserva borrow del erased box y cleanup de wrapper;
- CallableRef termina el borrow y destruye temporales adaptados antes de
  propagar el mismo `ExceptionEvent`.

Ningún thunk puede reemplazar, capturar dos veces ni perder la excepción activa.

## 12. Decisiones propuestas

### 12.1 ¿Debe existir un tipo público `Callable`?

**No en el primer milestone. Sí probablemente como mecanismo posterior y
explícito de erasure owning.** Su caso de uso es storage/return heterogéneo, no
la mera invocación de Function y Closure.

El nombre `Callable` debería reservarse hasta cerrar:

- representación baseline frente a adopción de header Closure;
- adapters y contrato de lvalue/fresh/Move;
- Alias y helpers ARC;
- storage gates y cycle policy para class fields;
- ABI/mangling dentro de una sesión.

### 12.2 ¿Debe invocabilidad ser capability genérica?

**Sí.** Debe ser compiler-known, estructural, exacta por firma y repeatable-read.
No debe ser una interface nominal ni implicar lifecycle properties.

### 12.3 ¿Se necesitan ambos mecanismos?

**Sí, para problemas diferentes.** Capability evita duplicación y erasure en
algoritmos estáticos. Callable owning habilita heterogeneidad runtime. La
existencia futura del segundo no debe hacer pagar sus costes al primero.

### 12.4 Adapters explícitos

Propuestos, con spelling todavía abierto:

- Function -> Callable: explícito; allocation visible en contrato.
- Closure fresh -> Callable: explícito; transfer; allocation wrapper en el
  baseline.
- Closure lvalue -> Callable: explícito; Alias/retain más wrapper baseline.
- Closure lvalue consumido -> Callable: sólo mediante una operación source de
  Move explícita y calificada.
- Callable -> Function o Closure: no.
- Function/Closure -> capability: no hay adapter; hay satisfacción estática.
- Function/Closure -> CallableRef: adapter borrowed explícito inicialmente.

### 12.5 Evitar duplicación de APIs

- No crear parejas Function/Closure como política general.
- Implementar el algoritmo una vez bajo `Invocable`.
- Si compatibilidad transicional exige un entry Function exacto, hacerlo
  wrapper y calificar overload resolution; no copiar el loop.
- Usar erasure sólo en boundaries que realmente guardan o mezclan callbacks.

## 13. Riesgos y mitigaciones

| Riesgo | Impacto | Mitigación propuesta |
|---|---|---|
| capability tratada como trait nominal | semántica ficticia | vocabulario compiler-known cerrado y satisfaction por TypeData exacto |
| `Invocable` implica Alias/Storable | ownership inválido | capabilities ortogonales; verifier rechaza uso no probado |
| generic call llega a MIR | backend sin contrato | gate fail-closed: ninguna `CapabilityInvoke` residual |
| especialización elige spine incorrecto | ABI corruption | reconstruir firma/kind en HIR especializado, MIR y SSA |
| code-size combinatorio | binarios grandes | medir; C tiene dos kinds por firma V1; usar CallableRef/erasure donde convenga |
| “zero-cost” no demostrado | expectativas falsas | guarantees limitadas; medir indirect calls, ARC y allocations O0/O2 |
| Callable oculta allocation | sorpresa de rendimiento | adapters explícitos; counters y dumps |
| confusión de pointers Function/Closure/Callable | memory corruption | TypeIds y ops distintos; no casts por layout |
| Callable wrapper de Closure duplica ARC | overhead | baseline explícito; estudiar adopción de header sólo normativamente |
| CallableRef escapa | UAF | non-Storable, región, EndBorrow y verifier de escape |
| exception pierde cleanup/event | leak o excepción incorrecta | edges explícitos y corruption tests por mecanismo |
| API generic rompe address-taking/mangling | source compatibility | milestone de migración separado y wrappers transitorios |
| artefactos separados incompatibles | ABI break | fuera de scope hasta `COMPILED-ARTIFACT-ABI` |

## 14. Dependencias reales

### Para `INVOCABLE-CAPABILITY-V1`

1. sintaxis de constraint parametrizada por lista de argumentos y retorno;
2. representación canónica de capability signature, separada de TypeProperties;
3. satisfaction exacta para Function y Closure;
4. inferencia de C y validation de constraints;
5. `CapabilityInvoke` en generic HIR con firma/effect/mode;
6. specialization a los spines existentes antes de MIR;
7. verificación de ownership de parámetros generic sin asumir Alias;
8. dumps, diagnostics y corruption tests;
9. qualification O0/O2, exceptions y cross-source-module.

No requiere runtime ni ABI nuevo.

### Para `CALLABLE-ERASURE-V1`

1. cerrar representación y `CallableABI-v1`;
2. cerrar adapters y spelling de Move;
3. TypeData/TypeProperties uniformes;
4. ownership IR, Alias, borrow, Drop y unwind;
5. thunks, helpers, reachability y counters;
6. qualification de lvalue/fresh/Move y firmas corruptas;
7. abrir sólo los gates de return/storage comprometidos por el milestone.

### Para `CALLABLE-REF-V1`

1. descriptor ABI y adapters por kind;
2. regiones no escapables y temporales;
3. call/EndBorrow normal y unwind;
4. verifier de context/adapter signature y escape;
5. medición frente a monomorfización generic.

## 15. Plan incremental

### Milestone 0 — revisión de diseño

- aprobar o rechazar la separación capability/erasure;
- elegir spelling (`Invocable`, `Invoke` u otro);
- decidir si el primer parámetro es by-value o se incluye también `ref C`;
- fijar diagnostics y límites de satisfaction V1.

Entrega utilidad: decisión implementable sin comprometer un ABI erased.

### Milestone 1 — `INVOCABLE-CAPABILITY-V1`

- capability exacta y repeatable-read;
- Function y Closure como únicos satisfiers;
- parámetros by-value;
- `CapabilityInvoke` sólo en generic HIR;
- specialization a `IndirectCall`/`ClosureCall` antes de MIR;
- ninguna API productiva migrada todavía;
- qualification focal con apply/integrate/exception y corrupción.

Entrega utilidad: autores pueden escribir una función generic que acepte ambos
kinds sin runtime nuevo.

### Milestone 2 — `BORROWED-INVOCABLE-PARAM-V1`

- invocation a través de `ref C`;
- inferencia exacta con implicit shared argument borrow;
- EndBorrow y temporales en normal/unwind;
- pruebas de cero retain/release adicional en Closure lvalue.

Entrega utilidad: algoritmos invoke-only y invoke-many con mínimo lifecycle de
boundary.

### Milestone 3 — migración de una API real

- migrar o extender `plots.plotFunction` sin duplicar el loop;
- calificar top-level Function, lambda no capturante y Closure capturante;
- preservar diagnostics, exceptions, output SVG y O0/O2;
- auditar source compatibility, overloads, mangling y address-taking.

Después, aplicar el patrón a Newton, integración, derivación y modelos de
mínimos cuadrados.

### Milestone 4 — medir necesidad de erasure

- medir code size de combinaciones generic;
- concretar un consumer de callback almacenado/retornado heterogéneo;
- comparar Callable owning frente a CallableRef;
- no implementar ambos por anticipación.

### Milestone 5A — `CALLABLE-REF-V1`, si domina invoke-only ABI

- descriptor borrowed explícito;
- sin storage/return;
- no allocation/ARC de adapter;
- qualification de dispatch y escape.

### Milestone 5B — `CALLABLE-ERASURE-V1`, si domina storage

- owner erased y adapters explícitos;
- locals, argumentos y return primero;
- storage en struct/enum/Array/List sólo en vertical dedicado;
- class fields sólo tras política de ciclos ARC.

Los milestones 5A y 5B son independientes; el orden debe decidirse con un caso
de uso y medidas, no por simetría.

## 16. Garantías que sí se pueden ofrecer

Para capability generic by-value:

- cero allocation de adaptación;
- cero thunk de adaptación;
- Function conserva Copy/no-drop y su indirect call;
- Closure conserva box/ARC/Drop; un lvalue paga un retain/release por frontera,
  un fresh owner se transfiere;
- ninguna ARC por invocation;
- exceptions y cleanup equivalentes a cada spine concreto;
- como máximo dos kinds de callable por firma en V1, aunque otros parámetros
  generic todavía pueden multiplicar instancias.

Para `ref C`, si se aprueba:

- cero owner/retain/release de boundary;
- borrow y EndBorrow obligatorios;
- no storage/escape del ref.

No se garantiza:

- direct call o inline;
- eliminación del closure box creado por una lambda capturante;
- devirtualización del invoke thunk;
- mismo code size que una implementación manual;
- compatibilidad ABI entre artefactos independientes;
- zero-cost para Callable owning o CallableRef.

## 17. Preguntas abiertas

1. ¿El spelling debe ser `Invocable<(P...),R>`, `Invoke<(P...),R>` u otro?
2. ¿La grammar de constraints admite directamente una capability parametrizada
   o referencia un alias de firma compiler-known?
3. ¿Milestone 1 incluye `ref C` o conviene aislarlo para qualification?
4. ¿Una API existente se migra in-place a generic o conserva temporalmente un
   overload Function exacto?
5. ¿Cómo se expresa en source un Move whole-root explícito para un adapter
   owning sin crear una regla sólo para Callable?
6. ¿Callable owning usa box siempre distinto o adopta directamente carriers
   ClosureABI-compatible mediante un contrato ABI compartido?
7. ¿Qué consumer real justifica storage heterogéneo antes de abrir gates de
   aggregates/containers?
8. ¿Cuándo code size medido justifica CallableRef frente a specialization?
9. ¿Las future mutable/once closures usan capabilities distintas y
   deliberadamente no satisfacen `Invocable`?
10. ¿Qué parte de esta superficie debe permanecer source-only hasta
    `COMPILED-ARTIFACT-ABI`?

## 18. Recomendación final

Proponer `Invocable<(P...),R>` como capability generic compiler-known,
repeatable-read y exacta, con Function y Closure como únicos satisfiers V1.
Implementarla primero by-value y bajar toda invocation a los spines concretos
antes de MIR. Añadir luego `ref C` para APIs invoke-only si la qualification de
borrow demuestra el contrato.

No crear todavía `Callable`. Reservarlo para un vertical owning erased motivado
por callbacks heterogéneos almacenados o retornados, con adapters explícitos y
costes medibles. Mantener `CallableRef` como alternativa separada para ABI
uniforme no escapable si code size o monomorfización lo justifican.

Esta recomendación preserva los ABIs existentes, evita duplicación source,
mantiene ownership visible y entrega valor antes de diseñar todo el sistema de
erasure y storage.
