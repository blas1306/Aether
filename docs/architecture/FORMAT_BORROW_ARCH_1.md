# FORMAT-BORROW-ARCH-1 — observational interpolation borrows

Estado: **ARQUITECTURA CERRADA; NO IMPLEMENTADA**, 2026-09-28.

Este documento define una extensión acotada de FORMAT-V1: todo operand que ya
sea interpolable se observa sin transferir ownership. El cambio corrige la
diferencia accidental entre un owner completo, una proyección de field y una
referencia. No agrega tipos interpolables, partial moves, `Clone`, formatting
definido por usuario ni APIs especiales para álgebra lineal.

Documentos de base:

- [FORMAT_ARCH_1.md](FORMAT_ARCH_1.md) y
  [FORMAT_V1_REPORT.md](FORMAT_V1_REPORT.md);
- [BORROW_ERGONOMICS_ARCH_1.md](BORROW_ERGONOMICS_ARCH_1.md) y
  [BORROW_ERGONOMICS_V1_REPORT.md](BORROW_ERGONOMICS_V1_REPORT.md);
- [AETHER_V1_SEMANTIC_CONTRACT.md](AETHER_V1_SEMANTIC_CONTRACT.md).

## 1. Problema y resultado requerido

La interpolación actual puede resolver una proyección non-Copy como un uso
ordinario antes de decidir si el hole sólo necesita observarla. Eso intenta
mover el field y produce E0293. Una referencia, por otra parte, conserva su
TypeId `ref T` y falla E0340 aunque el pointee `T` sea interpolable. Son dos
manifestaciones del mismo defecto: el contexto FORMAT se decide demasiado
tarde y pierde la categoría de acceso necesaria.

La regla normativa nueva es:

> Construir un fragmento de formatting nunca transfiere ownership del valor
> formateado. Un valor non-Copy se lee mediante un shared borrow contextual; una
> referencia se observa a través de su pointee; un rvalue owning se estabiliza
> en un root temporal y se presta. El borrow no escapa del plan de
> interpolación.

Por tanto, para todo `T` que el perfil FORMAT activo reconozca:

```aether
println("${owner}");
println("${aggregate.field}");
println("${aggregate.a.b.c}");

ref T shared = &owner;
println("${shared}");

ref mut T writable = &mut owner;
println("${writable}");
```

observa el mismo valor `T`; no imprime una dirección, no crea otro owner y no
invalida ninguno de esos bindings. Tras finalizar la interpolación vuelven a
ser aplicables los usos que ya fueran legales:

```aether
println("${factor.L}");
println("${factor.U}");
solve(factor, b);
```

La última línea puede consumir `factor` conforme a su firma porque las dos
interpolaciones ya cerraron sus borrows.

## 2. Límite con interpolabilidad

FORMAT-BORROW-ARCH-1 no amplía el conjunto de tipos formateables. Primero se
normaliza el tipo observado y después se aplica exactamente la tabla de
interpolabilidad del perfil FORMAT activo:

```text
format_type(T)           = T
format_type(ref T)       = format_type(T)
format_type(ref mut T)   = format_type(T)

interpolable(E) iff interpolable_type(format_type(type(E)))
```

El peeling recursivo de referencias sólo determina qué valor se observa. No es
una regla general de auto-deref y no permite formatting por el mero hecho de
tener un pointer.

En el FORMAT-V1 actualmente calificado, el conjunto cerrado sigue siendo
`string`, integers, `float32`, `float64`, `bool` y `char`. Su reporte excluye
collections y tipos matemáticos. En consecuencia, esta arquitectura por sí
sola no promete que `Matrix<T>` pase E0340. El caso LU es un dogfood obligatorio
cuando el perfil que se implemente ya declare `Matrix<T>` interpolable mediante
una decisión separada. En ese perfil, FORMAT-BORROW sí garantiza que
`factor.L`, `factor.U`, `ref Matrix<T>` y `ref mut Matrix<T>` no se muevan ni se
copien.

Un tipo subyacente no soportado conserva E0340 en el span del hole:

```aether
Unknown value = ...;
ref Unknown r = &value;
println("${r}"); // E0340: Unknown no es interpolable
```

El diagnóstico debe nombrar `Unknown`, no presentar `ref Unknown` como una
capability de formatting. Este cambio tampoco agrega dispatch, reflection,
lookup de métodos ni formatter protocol.

## 3. Clasificación de operands

Cada hole se clasifica después de resolver su expresión una sola vez y antes de
aplicar las reglas ordinarias de consumo:

| Expresión fuente | Captura FORMAT | Ownership |
|---|---|---|
| valor Copy `T` | `CopyValue` | conserva el mecanismo by-value actual |
| Place owning non-Copy `T` | `SharedPlace` | shared borrow del Place |
| `ref T` | `SharedReborrow` | observa el pointee |
| `ref mut T` | `SharedReborrow` | reborrow shared temporal del pointee |
| rvalue owning `T` | `OwnedTemporary` + shared borrow | root temporal único |
| proyección sobre rvalue | root del rvalue + `SharedPlace` proyectado | el root vive hasta el último uso FORMAT |

### 3.1 Copy

FORMAT puede conservar la captura by-value de un scalar Copy. Esta libertad es
una equivalencia de implementación, no una excepción de ownership: el source
no queda movido y la expresión se evalúa exactamente una vez. Una referencia a
un scalar no se formatea como pointer; se hace reborrow shared del pointee y la
lectura Copy necesaria ocurre dentro del formatter.

### 3.2 Places owning y proyecciones

Para un lvalue non-Copy, el frontend intenta primero resolución contextual como
Place. Un local, field, field anidado, elemento o dereference que ya sea un
Place prestable llega completo a HIR. No se construye antes un `Load` o `Move`
del valor non-Copy.

Así, `"${factor.L}"` contiene un borrow de la proyección `factor.L`; nunca
contiene `MoveField`, un `Load` owning ni un cambio de estado partial-move para
`factor`. Lo mismo vale para `obj.a.b.c`. La resolución conserva el root y toda
la cadena de projections para que provenance y disjointness usen las reglas
ordinarias.

Esto no cambia una expresión fuera de FORMAT:

```aether
Matrix<float64> L = factor.L; // puede continuar produciendo E0293
```

No se agregan partial moves, destructuring parcial ni reads implícitos de
fields non-Copy.

### 3.3 Referencias compartidas y mutables

Un hole cuyo tipo sea `ref T` observa `T`. Si el pointee vuelve a ser una
referencia, se repite la operación hasta llegar al primer tipo no-reference.
Cada descriptor de referencia se evalúa una vez y se conserva su provenance;
ninguna capa imprime su representación física.

`ref mut T` no se consume ni se degrada permanentemente. FORMAT crea un
reborrow shared de `T`, lo termina al último uso del fragmento y después el
binding original conserva su capacidad de escritura. Esta regla no implica
`noalias`, exclusividad nueva ni una conversión general `ref mut T -> ref T`.
Es una adaptación exclusiva del consumer FORMAT.

Las referencias nullable no se desenvuelven implícitamente: `(ref T)?` sigue
siendo un nullable y requiere el control de null explícito que ya exija el
lenguaje. En cambio, `ref T?` observa un valor subyacente `T?`, que sólo será
aceptado si ese tipo exacto pertenece al perfil FORMAT activo.

### 3.4 Rvalues y proyecciones de temporales

Un owner rvalue se evalúa una vez en un root temporal oculto:

```aether
println("${makeMatrix()}");
println("${makeStruct().matrix}");
```

En el segundo caso se estabiliza el resultado completo de `makeStruct()` y el
borrow apunta a su field `matrix`. No se mueve el field fuera del temporal. El
root owning permanece inicializado hasta que finalice el último read del hole,
y se destruye exactamente una vez después de `EndFormatBorrow`.

Si el initializer lanza, no existe root publicado ni Drop. Si un hole posterior
lanza, los borrows activos se terminan y los roots temporales ya inicializados
se destruyen en orden inverso mediante el unwind ordinario. Los traps abortivos
conservan la política actual: FORMAT-BORROW no introduce cleanup donde el
modelo global no lo promete.

No se permite prestar un rvalue cuyo storage no pueda estabilizarse. El
frontend debe materializarlo primero; nunca puede bajar un pointer a storage
efímero del backend.

## 4. Evaluación y región de lifetime

Se conserva el contrato FORMAT-V1:

1. los holes se evalúan exactamente una vez, de izquierda a derecha;
2. sus captures quedan disponibles para las pasadas de medición y emisión;
3. se calcula el tamaño checked y se reserva el backing final;
4. los fragments se emiten en orden;
5. el owner `string` se publica y se limpian captures/temporales.

Crear un borrow no autoriza reevaluar la expresión ni separar su base de sus
projections. En `"${f()} ${g()}"`, todos los efectos de `f` preceden a los de
`g`, igual que en FORMAT-V1.

La región mínima de un operand prestado empieza al evaluar ese hole y termina
inmediatamente después de su último read por el plan FORMAT. En el builder
exacto actual, medición y emisión pueden leer el mismo operand; por ello la
región puede abarcar la evaluación de holes posteriores y ambas pasadas. No se
promete cerrar el borrow después de la primera medición si la emisión todavía
lo necesita.

Los borrows pueden cerrarse por fragmento tras su última emisión. Todos deben
estar cerrados antes de que la expresión `Interpolation` produzca su `string` y,
por tanto, antes de entrar al statement siguiente:

```aether
println("${factor.L}");
mutate(factor); // no existe borrow FORMAT vivo
```

No pueden guardarse dentro del `string`, retornarse, pasar por phi como
referencias, almacenarse en fields/globals, capturarse ni escapar a un formatter
callback. FORMAT recibe sólo acceso de lectura durante una región estructurada.

## 5. Borrow checking y conflictos

Los borrows FORMAT entran en el mismo análisis de Places, roots, provenance,
invalidación y conflictos que cualquier shared borrow. La interpolación no
tiene un permiso privilegiado por aparecer dentro de `println`.

```aether
ref mut Matrix<float64> x = &mut matrix;
println("${matrix}");
```

se acepta o rechaza según la regla ordinaria vigente para un shared borrow de
`matrix` mientras ese `ref mut` está vivo. FORMAT-BORROW no redefine si `ref
mut` es exclusivo ni omite el conflicto. El diagnóstico debe ser el mismo
diagnóstico de borrow/provenance que produciría un shared borrow explícito
equivalente.

En cambio:

```aether
println("${x}");
mutateThrough(x);
```

forma un reborrow shared a través de `x`, lo cierra al terminar la
interpolación y preserva la mutabilidad posterior. Un intento de mutar o mover
el mismo root desde un hole posterior mientras el reborrow siga necesario se
somete al checker normal. Shared borrows de fields demostrablemente disjuntos
pueden coexistir si el análisis ordinario ya demuestra esa disjointness.

La regla vive en `Interpolation`, no en `print` o `println`. Construir
`string s = "${value}"` crea y cierra los mismos borrows antes de asignar `s`.
`print` y `println` continúan recibiendo sólo un `string` y no obtienen un caso
especial.

## 6. Representación por fases

### 6.1 AST

AST no cambia. Un hole conserva su expresión y span source. La semántica
contextual se decide después de resolución de nombres y tipos.

### 6.2 HIR

HIR debe hacer visible la observación. Se agrega una forma conceptual distinta
de `CallScopedSharedBorrow`:

```text
FormatScopedSharedBorrow {
    format_site: FormatSiteId,
    fragment_index: u32,
    pointee_type: TypeId,
    reference_type: TypeId,       // ref pointee_type
    source: FormatBorrowSource,   // Place | Reference | ProjectedTemporary
    origin: Owner | Ref | RefMut,
}
```

Cada `InterpolationFragment::Hole` conserva además dos identidades separadas:

```text
Hole {
    operand,
    formatted_type: TypeId,       // T tras peeling de refs
    access: CopyValue | SharedObservation,
    conversion,
    span,
}
```

`conversion` sigue describiendo cómo T se convierte a bytes; `access` describe
cómo FORMAT obtiene T. Mezclar ambos conceptos volvería a introducir la
confusión actual. `StringBorrow` puede evolucionar a una conversión de string
independiente de si su acceso provino de owner, ref o temporal.

Se elige una forma HIR específica de FORMAT y no se reutiliza sin cambios
`CallScopedSharedBorrow`: una interpolación no es una call, no tiene argument
slot y su borrow puede sobrevivir evaluación de holes posteriores, medición y
emisión. Ambas formas sí deben compartir tipos auxiliares de Place/provenance y
el lowering común de regiones. Una refactorización futura a un
`ScopedSharedBorrow` parametrizado por consumer es válida sólo si los
verificadores conservan `CallSiteId`/argument index para calls y
`FormatSiteId`/fragment index para FORMAT.

El verificador HIR reconstruye:

- que `FormatSiteId` identifica la `Interpolation` contenedora;
- que el índice apunta al hole exacto y el borrow aparece sólo como su operand;
- que source/projections producen `pointee_type` y el reference TypeId es
  `ref pointee_type` shared;
- que `formatted_type` es el pointee final tras refs y coincide con la
  conversión estática;
- que `CopyValue` sólo se usa donde una captura by-value no consume;
- que `SharedObservation` no contiene `Move`, `MoveField`, `Alias`, Clone ni
  escape;
- que el tipo subyacente pertenece al set interpolable activo.

### 6.3 MIR

MIR materializa cada observación como región estructurada:

```text
EvaluateOrStabilizeSource
Borrow(shared, format metadata) -> ref T
... evaluate remaining holes ...
... measure/read fragment ...
... emit/read fragment ...
EndBorrow(format metadata)
Drop temporary root, if any
```

La metadata contiene `FormatSiteId`, fragment index, TypeIds, origin,
source-kind y provenance. El plan mantiene una pila de borrows FORMAT activos y
una pila de roots owning inicializados. Los unwind edges de expresiones
capturables ejecutan `EndBorrow` y luego Drop en orden inverso. Size overflow y
OOM conservan sus terminators abortivos sin sucesor excepcional.

MIR nunca representa el source de un hole non-Copy como operand owning
consumido. Una proyección temporal conserva por separado el root owning y el
Place prestado. El resultado final continúa siendo un único owner `string`
fresh.

### 6.4 SSA

SSA conserva `Borrow`/`EndBorrow` con metadata FORMAT; `EndBorrow` no es sólo un
comentario descartable antes de verificación. Los verificadores recorren CFG
normal y excepcional y exigen:

- definición única del source y evaluación ordenada de holes;
- región activa desde `Borrow` hasta el último read del fragmento;
- ningún Move/Drop/Store invalidante del root durante la región;
- `EndBorrow` exactamente una vez por path no abortivo;
- Drop del root temporal sólo después del `EndBorrow` correspondiente;
- estados de borrows/owners compatibles en joins;
- ninguna referencia FORMAT en Return, Store, phi, call arbitraria o resultado;
- ningún owner duplicado ni estado partial-move.

Los dumps deben permitir una prueba estructural de que
`println("${factor.L}")` contiene `FormatScopedSharedBorrow` en HIR y
`Borrow`/`EndBorrow` en MIR/SSA, y no `MoveField`, Clone, Alias de owner ni
partial-move state.

### 6.5 Backend y runtime

LLVM recibe un pointer prestado porque HIR/MIR/SSA ya probaron el acceso; el
pointer no es la fuente de la semántica. `EndBorrow` puede bajar a marcador
inerte después de verificación y no implica retain/release, `noalias` ni copia.

Los formatters existentes deben aceptar lectura borrowed del valor que ya
soportan. No se agrega helper para Matrix/LU ni helper de clone defensivo. Una
extensión independiente que haga interpolable un agregado debe definir sus
propios helpers/protocolo, pero FORMAT-BORROW sólo entrega `ref T` shared a esa
conversión.

## 7. Costos y ownership

Queda normativamente prohibido implementar esta feature mediante:

- `Copy`, `Clone`, `Alias`, retain o COW implícitos para owners non-Copy;
- materialización de un segundo Matrix, String, Array, List, Vector o struct;
- moving del field a un temporary y reconstrucción posterior del agregado;
- dispatch runtime sobre el TypeId de una referencia;
- dependencia accidental de que un helper LLVM reciba un pointer.

El único storage adicional permitido por la semántica es el root necesario
para estabilizar un rvalue que ya debía existir, más los temporales internos del
formatter preexistente. Formar o terminar el borrow no asigna heap. Copiar bytes
al backing final de la string es el trabajo ordinario de formatting, no una
copia owning del source.

La instrumentación de calificación debe demostrar deltas cero de
clone/owner-allocation/retain/release atribuibles al borrow, tanto O0 como O2.

## 8. Diagnostics

Se conservan las identidades existentes siempre que representen la causa:

- E0340 para un `formatted_type` no interpolable, incluido detrás de una o más
  referencias;
- E0293 para un move ordinario de field non-Copy fuera de FORMAT;
- los diagnósticos ordinarios de borrow/provenance para conflictos reales;
- el diagnóstico ordinario de uso tras move si el owner ya estaba movido antes
  de entrar al hole.

No deben emitirse E0293 ni E0340 para owner, field o referencia cuyo tipo
subyacente sí sea interpolable y cuyo shared borrow sea legal. Un Place no
prestable o un temporary que no pueda estabilizarse recibe un diagnóstico de
borrow/addressability, no E0340: su tipo puede ser perfectamente interpolable y
la falla es de acceso.

Los spans primarios permanecen en el hole. Cuando el error sea un conflicto, el
diagnóstico secundario debe señalar el borrow previo o la invalidación igual
que el checker ordinario.

## 9. Casos normativos

Suponiendo `T` interpolable:

| Caso | Resultado requerido |
|---|---|
| `"${owner}"` dos veces | dos observaciones; owner válido después |
| `"${s.field}"` | borrow del field; sin partial move |
| `"${s.a.b.c}"` | borrow de la proyección completa |
| `"${shared}"`, `shared: ref T` | valor pointee, no dirección |
| `"${writable}"`, `writable: ref mut T` | reborrow shared; mutabilidad utilizable después |
| `"${makeT()}"` | root temporal, borrow, EndBorrow, Drop once |
| `"${makeS().field}"` | root de S; no extracción owning del field |
| `"${s.left} ${s.right}"` | evaluación izquierda-derecha; shared borrows compatibles según checker |
| `"${unknown}"` | E0340 si el tipo subyacente no está soportado |
| `T x = s.field` non-Copy | E0293 puede mantenerse |

`print`, `println`, asignación, retorno y composición posterior de la string no
cambian esta tabla: el límite semántico es construir `Interpolation`.

## 10. Cobertura exigida al vertical de implementación

La suite dedicada debe cubrir en O0 y O2:

1. owner non-Copy interpolado dos veces y reutilizado después;
2. field non-Copy y nested field sin estado partial-move;
3. dos fields non-Copy del mismo agregado;
4. `ref T`, referencias shared anidadas y valor pointee exacto;
5. `ref mut T`, reborrow shared y mutación posterior;
6. owner temporal y field de temporal, Drop once normal;
7. unwind desde un hole posterior, EndBorrow y Drop inversos;
8. evaluación exactly-once y side effects izquierda-derecha;
9. conflicto de borrow real todavía rechazado;
10. tipo subyacente no interpolable todavía E0340;
11. move ordinario de field todavía E0293;
12. dumps y corruptions independientes de HIR, MIR y SSA;
13. cero Clone/Alias/retain/release/allocation de owner atribuible al borrow;
14. interpolación construida fuera de output, para probar que no está
    hardcodeada en `println`;
15. equivalencia native O0/O2 y suites FORMAT/ownership previas verdes.

Cuando `Matrix<float64>` sea interpolable, se agrega el dogfood real:

```aether
var factor = linearAlgebra.lu(A);
println("${factor.L}");
println("${factor.U}");
solve(factor, b);
```

Si existe una API `det` que no consume de forma incompatible el mismo valor, se
cubre también `det(factor)` en el orden admitido por sus firmas. La prueba debe
separar un fallo de interpolabilidad de Matrix de un fallo de borrow: este
milestone sólo corrige el segundo.

## 11. Orden de implementación

1. Extraer una consulta única `interpolable_type(T)` y separar
   `formatted_type`, access y conversion sin ampliar el set actual.
2. Asignar `FormatSiteId` y resolver holes contextualmente como Copy, Place,
   reference/reborrow o stabilized temporary antes de generar Move/Load.
3. Agregar `FormatScopedSharedBorrow` y reforzar el verifier HIR, incluidos
   nested refs, projections y ausencia de escape.
4. Bajar a regiones MIR `Borrow`/`EndBorrow`, reutilizando machinery de
   provenance, active borrows, temporary roots y unwind de calls donde sea
   semánticamente común.
5. Preservar metadata y verificar regiones/owners independientemente en SSA.
6. Adaptar backend/formatters sólo para consumir el operand borrowed ya
   verificado; no agregar decisiones de ownership en LLVM.
7. Incorporar tests negativos/corruptions, lifecycle, orden y O0/O2 con un tipo
   non-Copy ya interpolable.
8. Activar el dogfood LU únicamente cuando Matrix pertenezca al perfil FORMAT
   activo; no modificar `linearAlgebra` desde este vertical.
9. Ejecutar qualification completa: workspace tests, fmt, clippy, differential
   legacy y `git diff --check`.

Este orden evita que un backend que “funciona por pointer” preceda al contrato
verificable de lenguaje y permite revisar por separado interpolabilidad,
ownership y codegen.

## 12. Alternativas rechazadas

| Alternativa | Motivo de rechazo |
|---|---|
| clonar/copiar el operand non-Copy | costo oculto y ownership distinto |
| mover el field a un temporary | exige partial moves y consume el agregado |
| tratar `ref T` como interpolable por sí mismo | imprimiría/aceptaría referencias a tipos no soportados |
| desreferenciar sólo en LLVM | la semántica no sería visible ni verificable en HIR/MIR/SSA |
| reutilizar literalmente `CallScopedSharedBorrow` | FORMAT no tiene call slot y su región cubre count/write |
| hardcodear `println` | falla para una interpolación asignada o retornada como string |
| cerrar todos los borrows al final del statement | extiende lifetimes más allá de la expresión productora |
| cerrar al terminar de evaluar el hole | puede dejar dangling antes de medir/emitir |
| agregar excepción Matrix/LU | viola generalidad y duplica policy de tipos |

## 13. Fuera de alcance

- partial moves y reconstrucción de agregados;
- destructuring de owners;
- Copy/Clone/Alias/COW implícitos;
- ampliar el set FORMAT-V1, Matrix formatting o cambios en `linearAlgebra`;
- traits/protocols de formatting, user-defined formatting o reflection;
- format specifiers, output variádico o streaming directo a `println`;
- auto-deref general fuera de holes FORMAT;
- una nueva semántica de exclusividad para `ref mut`;
- garantías de cleanup para traps abortivos que hoy no las poseen.

## 14. Criterio de cierre futuro

El vertical sólo podrá declararse implementado cuando sea posible probar, por
estructura y por ejecución, que todo valor non-Copy soportado se observa sin
Move/Clone, que cada referencia formatea su pointee, que temporales viven y se
destruyen exactamente una vez, que los borrows terminan antes del siguiente
statement y que E0340/E0293 continúan protegiendo respectivamente tipos no
soportados y moves ordinarios.

