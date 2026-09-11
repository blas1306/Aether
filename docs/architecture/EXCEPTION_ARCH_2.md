# EXCEPTION-ARCH-2 — excepciones unchecked y unwinding determinista

Estado: **recomendación de arquitectura; no admisión de lenguaje**. Diseñado
2026-09-10 sobre el contrato vigente de `compiler-next` y OOP-V1/V2/V3/
OOP-POLISH-1. Este milestone no implementa parser, HIR, MIR, SSA, LLVM ni
runtime. Toda sintaxis y todo nombre de operación de IR de este documento son
provisionales hasta un vertical de implementación calificado.

## 1. Decisión resumida

Aether debe ofrecer excepciones **unchecked**, nominales y basadas en clases:

```aether
throw SomeException(...);

try {
    work();
}
catch (SomeException e) {
    recover(e);
}
```

No hay `throws`, `errors E` ni otro efecto obligatorio en firmas. Una función,
un método virtual o un requirement de interface puede propagar una excepción
sin que esa posibilidad forme parte de su tipo fuente. `Result<T, E>` puede
existir como abstracción ordinaria para fallos esperados, pero no es el
transporte obligatorio de las excepciones.

Solo puede lanzarse un handle de clase cuyo tipo estático sea `Exception` o un
subtipo nominal. `Exception` es una clase raíz conocida por el core, abierta y
sin significado de `Object` universal. Las excepciones usan la herencia simple
normal de OOP-V3, conservan identidad de objeto y usan el ARC normal. Los
`catch` se prueban en orden fuente y seleccionan el primero cuyo tipo sea un
supertipo del tipo dinámico lanzado. `catch (Exception e)` es el catch-all
tipado; no se recomienda un `catch` sin tipo para el primer modelo.

HIR, MIR y SSA deben representar el flujo excepcional y su ownership de forma
explícita. El backend recomendado es un **híbrido por capas**: CFG excepcional
y cleanup explícitos como autoridad semántica, y unwinding nativo de LLVM como
transporte físico en cada target admitido. LLVM no descubre propietarios ni
inventa cleanup. Un target sin una implementación de unwinding calificada no
admite excepciones; no cambia silenciosamente a otro ABI.

Los traps de aritmética, conversión, división, bounds, allocation, invariantes
ARC y fallos internos siguen siendo terminación no capturable. No se convierten
automáticamente en objetos `Exception`, no entran a `catch` y no adquieren una
promesa de cleanup.

## 2. Autoridad y relación con diseños anteriores

Este diseño parte de:

- [OOP-ARCH-1](OOP_ARCH_1.md), para identidad, Alias/Transfer, ARC, construcción
  no publicada y destrucción dinámica;
- [OOP-V1](OOP_V1_REPORT.md), [OOP-V2](OOP_V2_REPORT.md),
  [OOP-V3](OOP_V3_REPORT.md) y [OOP-POLISH-1](OOP_POLISH_1_REPORT.md), para el
  comportamiento efectivamente admitido de clases, interfaces, herencia,
  descriptores, dispatch y cleanup;
- el [contrato semántico v1](AETHER_V1_SEMANTIC_CONTRACT.md), especialmente
  evaluación izquierda-a-derecha, lifecycle y traps;
- la [arquitectura del compilador](AETHER_COMPILER_ARCHITECTURE.md), para las
  fronteras tipadas HIR → MIR → SSA → LLVM y la autoridad de verificación.

El diseño anterior basado en errores checked, `errors E`, `fail` y `handle` no
es autoridad para esta decisión. Sus experimentos de CFG, ownership lineal y
cleanup son evidencia histórica útil, pero no preservan su superficie, sus
obligaciones de call site ni su efecto en tipos de función.

Este documento cierra la dirección semántica, no reemplaza todavía la sección
8.3 del contrato v1 ni admite una nueva fila de producto. Esa promoción exige
un vertical end-to-end separado.

## 3. Objetivos y no objetivos

El modelo debe:

- permitir propagación implícita a través de cualquier cantidad de frames;
- preservar tipos estáticos y matching nominal, sin dynamic typing;
- preservar orden de evaluación y cleanup determinista de todo lo ya
  inicializado;
- funcionar sin GC y reutilizar el ownership/ARC de clases;
- separar excepciones recuperables de traps y fallos de runtime;
- hacer verificable el flujo excepcional antes del backend;
- no imponer un wrapper o branch de estado en la superficie de cada llamada;
- contener toda excepción en fronteras C/FFI.

No son objetivos de este milestone:

- implementar la característica;
- hacer capturables overflow, bounds, allocation failure o panics;
- diseñar `Result`, nullability, async/cancellation o stack traces completos;
- admitir valores arbitrarios, structs, enums o interfaces como payload
  lanzable;
- prometer ABI público de objetos, descriptores o records de unwinding;
- permitir destructores que lancen.

## 4. Comparación útil con C#, C++ y Java

| Tema | C# | C++ | Java | Recomendación Aether |
| --- | --- | --- | --- | --- |
| Declaración en firmas | Unchecked en la práctica | No checked; specs dinámicas históricas removidas | Checked para parte de la jerarquía | Ninguna declaración |
| Payload | Objetos derivados de `System.Exception` | Cualquier tipo puede lanzarse | Objetos `Throwable` | Solo clases bajo `Exception` |
| Matching | Tipo/subtipo, orden fuente | Tipo compatible, orden de handlers | Tipo/subtipo, orden fuente | Tipo/subtipo nominal, primer match |
| Catch-all | `catch` o `Exception` | `catch (...)` | `Throwable` | `catch (Exception e)` |
| Rethrow | `throw;` preserva excepción activa | `throw;` | `throw e` | `throw;` explícito y sin repack |
| Cleanup | `finally` y `using` | RAII | `finally`/try-with-resources | cleanup de ownership siempre; `finally` posterior |
| Fallo en destructor | No finalización determinista equivalente | doble excepción termina | finalizers no equivalentes | `deinit` no puede lanzar |

Aether toma de C#/Java la raíz común y el catch por subtipo, y de C++ la
propagación unchecked con cleanup determinista. No adopta el payload arbitrario
de C++, las checked exceptions de Java ni la dependencia de un GC de C#/Java.

## 5. `Exception` y elegibilidad para `throw`

### 5.1 Categoría de `Exception`

`Exception` debe ser una **clase nominal del core**, no una interface, un trait,
un enum ni una categoría estructural. Conceptualmente:

```aether
// Declaración conceptual del core; no es sintaxis admitida por este milestone.
public open class Exception {
    public init() {}
}
```

Su `ClassId` es estable dentro del universo nominal de la compilación y no puede
ser recreado por spelling o layout. No introduce un `Object` universal. Una
clase que no desciende de `Exception` conserva exactamente el modelo OOP actual
y no puede lanzarse.

Una interface `Exception` evitaría prescribir estado, pero obligaría al record
de unwinding a preservar carrier y witness, y convertiría el catch por herencia
en una combinación especial de conformance y RTTI. Una clase raíz reutiliza la
identidad, el upcast, la destrucción dinámica y el ARC ya admitidos. Tampoco se
recomiendan payloads value: exigirían boxing o una segunda familia de carriers,
copias/moves y matching.

La primera versión puede permitir construir `Exception()` directamente, como
excepción genérica. No necesita `abstract`, string ni message para existir. Una
API futura podrá añadir message, cause o metadata sin cambiar la elegibilidad.

### 5.2 Regla estática

La expresión de `throw expression;` debe tener un tipo estático de clase `C`
tal que `C <: Exception`. Se aplican aliases transparentes antes de comprobar
la relación. El tipo dinámico puede ser cualquier subtipo de `C`.

No son elegibles:

- primitives, structs, enums, tuples o owners científicos;
- interfaces, incluso si el objeto subyacente es una excepción;
- clases sin una relación nominal con `Exception`;
- referencias prestadas o `this`;
- valores movidos, no inicializados, parcialmente construidos o null;
- un parámetro genérico sin una futura constraint nominal suficiente.

No existe conversión implícita desde strings, códigos, traps o valores que solo
tengan el mismo shape. Crear una excepción es construcción ordinaria de clase;
lanzarla es una operación posterior sobre un owner válido.

### 5.3 Clases de excepción

Las clases de excepción usan todas las reglas normales de OOP-V3:

- herencia simple y nominal;
- base `open`, derivadas final por defecto;
- un solo objeto, header, descriptor, strong count e identidad;
- base initialization antes de campos derivados y publicación única;
- métodos no virtuales por defecto y `open`/`override` normales;
- destrucción dinámica más-derived → base;
- visibilidad y módulos normales.

No hay tabla de tipos paralela basada en nombres. El descriptor de una clase
de excepción incorpora o referencia su padre nominal para matching. Esa
metadata privada no admite reflection, casts o `is`; sirve únicamente para
dispatch, destrucción y catches verificados.

## 6. Superficie de lenguaje recomendada

### 6.1 Throw, try y catch

```aether
class ParseException : Exception {
    int position;
    public init(int position) : base() { this.position = position; }
}

int parse(int code) {
    if (code < 48) {
        throw ParseException(0);
    }
    return code - 48;
}

int main() {
    try {
        return parse(40);
    }
    catch (ParseException e) {
        return e.position;
    }
    catch (Exception e) {
        return 1;
    }
}
```

`throw` es un statement abrupto y no produce un valor. `try` protege su bloque
completo. Cada `catch` requiere inicialmente un tipo de clase y un binding.
No se proponen filters, union catches, destructuring, patterns ni catch de una
expresión individual.

Un `try` debe tener al menos un `catch` o, cuando se admita, un `finally`. En el
primer vertical solo se acepta uno o más `catch`.

### 6.2 Matching y orden

Para una excepción con clase dinámica `D`, `catch (C e)` matchea exactamente si
`D == C` o `D` deriva transitivamente de `C`. Se consideran catches en orden de
aparición y se ejecuta solo el primero que matchea.

El compilador rechaza como inalcanzable un catch cuyo tipo es igual o subtipo
de un tipo anterior. Por ejemplo, `Exception` antes de `ParseException` hace
inalcanzable al segundo. Catches hermanos pueden aparecer en cualquier orden.
El orden sigue siendo observable aun si hoy no existen filtros.

`catch (Exception e)` cubre todos los valores que Aether permite lanzar y es el
catch-all recomendado. No se admite inicialmente `catch { ... }` ni
`catch (...)`: omitir el tipo sugeriría que traps o excepciones extranjeras
también son capturables. Un alias de `Exception` es equivalente tras
canonicalización.

El binding `e` tiene el tipo estático declarado por el catch, es un handle de
clase owning normal y vive solo en el bloque del handler. El objeto y su
identidad dinámica no se copian ni se cortan. Puede usarse, aliasarse o
retornarse bajo las reglas ordinarias de clases.

### 6.3 Propagación unchecked

Si ningún catch del `try` actual matchea, el mismo evento continúa hacia el
handler dinámicamente exterior después del cleanup correspondiente. Si no hay
handler en el frame, abandona el frame después de su cleanup excepcional. No
hay sintaxis de propagación, anotación en firma ni diagnóstico por llamada no
manejada.

La posibilidad de unwind no forma parte de:

- la identidad o compatibilidad de function types;
- una firma de función o método;
- un override;
- un requirement de interface o witness;
- monomorphization o mangling fuente.

El compilador puede inferir internamente `nounwind` para optimizar, pero es una
propiedad revocable de cuerpo/instancia, no una promesa fuente ni autoridad de
type checking. Una llamada indirecta o virtual desconocida se considera capaz
de unwind salvo prueba válida del target completo.

### 6.4 Rethrow

```aether
try {
    work();
}
catch (ParseException e) {
    log(e);
    throw;
}
```

`throw;` solo es legal dentro del cuerpo léxico de un catch y relanza el evento
actual. No construye otro objeto, no crea otro record, no cambia el tipo
dinámico ni reinicia su provenance/origen. Consume la disposición del handler:
después de limpiar los locals del catch, el mismo owner de propagación sigue al
handler exterior.

En catches anidados, `throw;` refiere al catch léxico más interno. No es válido
en una función llamada desde un catch ni dentro de un `finally` por el mero
hecho de existir una excepción activa en otro frame.

`throw e;` sigue siendo un throw ordinario. Evalúa `e`, adquiere o transfiere un
owner según las reglas normales y crea una nueva acción de lanzamiento. El
runtime puede registrar un nuevo sitio de origen. Para preservar la excepción
activa sin repack, se usa `throw;`.

## 7. Ownership del payload y del evento

Hay dos identidades que no deben confundirse:

1. el objeto Aether `Exception`, que es una clase ARC normal;
2. el record privado de unwinding, que transporta una obligación strong sobre
   ese objeto mientras la excepción está en vuelo.

El record no es un valor fuente, no participa en equality y no es GC. Contiene,
como mínimo, estado del unwinder y un owner de `Exception`; puede conservar
provenance diagnóstica. El tipo dinámico se obtiene del descriptor nominal del
objeto, no de un string del record.

`throw freshException()` transfiere el owner fresco al record sin retain.
`throw localException;` aplica Alias antes de abandonar el scope: el record
adquiere una obligación y el local conserva la suya hasta su cleanup. Una
optimización puede transferir un local muerto solo si prueba que preserva el
orden y toda observación.

Durante propagación existe exactamente un owner del record. Los edges de CFG,
landing pads y rethrow lo transfieren; nunca lo copian. Al entrar a un catch,
el runtime conserva el record por si ocurre `throw;` y el binding fuente recibe
un Alias ARC tipado al objeto. En salida manejada se limpian primero los locals
del catch, incluido el binding, y después `EndCatch` libera el owner del record.
En rethrow se limpian los locals pero el record se transfiere en vez de liberarse.
Esta retención en la entrada al catch es un costo deliberado para que `e` sea
un handle owning normal y pueda escapar de forma segura.

Una implementación futura puede eliminar un retain/release balanceado si
demuestra que el record ya no puede relanzarse y transfiere su owner al binding.
La optimización no cambia la semántica lineal ni la identidad.

## 8. Orden de evaluación, scopes y cleanup

Las reglas actuales de evaluación izquierda-a-derecha siguen vigentes. Si una
subexpresión lanza:

- las subexpresiones a su izquierda ya evaluadas conservan sus efectos;
- las subexpresiones a su derecha no se evalúan;
- se limpian en orden inverso solo temporaries/locals completamente
  inicializados;
- una asignación que aún no publicó el RHS deja el destino anterior intacto;
- un owner ya transferido no vuelve a destruirse.

Cada scope léxico tiene una receta normal y una receta excepcional derivadas de
la misma autoridad de ownership. Un edge que sale por excepción atraviesa los
cleanup scopes interiores en orden, hasta la entrada del handler que protege el
scope correspondiente. El catch no ve locals del bloque protegido.

`return`, `break` y `continue` conservan sus cleanups normales. Un throw dentro
de un catch primero limpia scopes internos y el propio binding antes de
propagar su nuevo evento. Los loops no crean una excepción especial: cada edge
mantiene el estado de inicialización/ownership de su iteración.

Los releases ARC ejecutados durante unwind son los mismos efectos semánticos
que en salida normal. Un último release puede destruir sincrónicamente un grafo
acíclico de owners y su orden es observable. Un optimizador no puede moverlo a
través de efectos, handlers o `finally` solo por liveness.

## 9. Fallo de constructores

La construcción sigue sin publicar un handle normal hasta completar base y
derived initialization. Si una evaluación o llamada lanza durante construcción:

- el token de objeto no publicado pasa a un cleanup de construcción, nunca a
  un catch como valor `this`;
- se destruyen exactamente los campos owning definitivamente inicializados, en
  orden inverso dentro de cada subobjeto;
- si una base terminó, sus campos se limpian después de los campos derivados ya
  inicializados; si la base falló, limpia solo su propio prefijo inicializado;
- no se ejecuta `deinit` del objeto cuya construcción no completó;
- se libera una sola vez la allocation completa most-derived;
- arguments y temporaries del call site siguen sus propios estados de
  transferencia e inicialización.

La receta no depende de una bitmap fuente ni de memoria zeroed: MIR conoce el
estado por path y materializa los cleanup edges necesarios. Los joins de
inicialización deben concordar o seleccionar flags explícitos ya admitidos por
el lifecycle general.

`throw SomeException(args)` primero construye y publica completamente el objeto
de excepción y luego lo lanza. Si su propia construcción lanza, se limpia el
objeto de excepción parcial y se propaga la excepción interior; nunca existe un
evento exterior incompleto.

Allocation failure, corrupción del header o fallo interno al crear el record
de unwinding siguen la ruta trap/fail-fast. No intentan lanzar una segunda
excepción y no prometen completar cleanup.

## 10. `finally`

`finally` **sí pertenece al modelo recomendado**, pero no al primer vertical.
Debe admitirse en un milestone posterior a throw/catch/rethrow y construcción
parcial, porque multiplica las salidas abruptas que el CFG y el verificador
deben demostrar.

Superficie prevista:

```aether
try {
    use(resource);
}
catch (RecoverableException e) {
    recover(e);
}
finally {
    observe();
}
```

El bloque `finally` se ejecuta exactamente una vez al abandonar el `try`/
`catch` por fallthrough, return, break, continue o excepción capturable. No se
ejecuta como promesa frente a abort, trap, process termination o corrupción de
runtime.

Para su primer milestone se recomienda que un `finally` no pueda transferir
control hacia afuera con `return`, `break` o `continue`. Puede completar
normalmente. Permitir que lance requiere cerrar antes una política de excepción
durante excepción activa; la opción segura inicial es rechazarlo estáticamente
cuando el compilador conoce un `throw` y terminar si una llamada produce un
segundo unwind. No se recomienda que un `finally` silenciosamente reemplace una
excepción o un return al estilo de algunos casos Java.

El cleanup implícito de ownership no espera a `finally` para existir. `finally`
es código fuente observable adicional; no es el mecanismo básico que hace
seguro ARC.

## 11. Traps, panic y excepciones

| Evento | Capturable | Unwind/cleanup garantizado | Uso |
| --- | --- | --- | --- |
| `throw` de `Exception` | Sí | Sí | Fallo excepcional recuperable por política de la aplicación |
| Excepción no manejada | No en el root | Sí hasta el root; luego report/terminate | Error de aplicación no recuperado |
| Overflow/división/conversión | No | No | Violación aritmética checked |
| Bounds/shape/size trap | No | No | Seguridad de acceso o contrato de storage |
| Allocation failure | No | No | Fail-fast del runtime |
| ARC under/overflow/corrupción | No | No | Invariante rota |
| ICE/runtime corruption | No | No | Fallo de implementación |

En particular, arithmetic y bounds traps **siguen siendo no-catchable**. Un
usuario que quiera una API recuperable debe comprobar condiciones y lanzar una
excepción explícita, o usar una API value como `Result`; el compilador no cambia
la categoría automáticamente.

Esta separación permite que los helpers de trap permanezcan `noreturn` y
`nounwind`. Un catch-all de `Exception` no intercepta señales, access violations,
foreign exceptions ni panics.

## 12. Representación HIR

HIR conserva estructura y decisiones nominales sin convertir todavía todo en
CFG. El vocabulario conceptual incluye:

| HIR fact/operation | Responsabilidad |
| --- | --- |
| `Throw` | Expresión evaluada una vez, ClassId estático elegible y modo Alias/Transfer |
| `Rethrow` | Identidad léxica del catch activo; no payload nuevo |
| `Try` | Bloque protegido, catches ordenados y `finally` opcional futuro |
| `CatchClause` | ClassId canónico, binding local owning, span y orden |
| Call unwind effect | Resumen interno conservador, no parte de firma/tipo fuente |
| Construction region | Token no publicado y receta de rollback por campos/base |
| Cleanup plan | Obligaciones normales y excepcionales calculadas por la autoridad central |

HIR resuelve todos los nombres y tipos de catch, prueba `C <: Exception`,
rechaza catches inalcanzables y vincula `throw;` con su catch. El tipo dinámico
nunca se decide por spelling. Los calls siguen nombrando FunctionId,
VirtualSlotId o RequirementId exactos.

La síntesis de ownership se amplía para producir obligaciones por salida normal
y excepcional. No debe ejecutarse una segunda síntesis independiente en MIR o
LLVM. Los verificadores posteriores reconstruyen y validan esas obligaciones,
pero no inventan otra política.

## 13. Representación Flow MIR

MIR es la autoridad ejecutable del flujo excepcional. Recomendación conceptual:

```text
Call {
  callee, arguments,
  normal -> bb_success(result),
  unwind -> bb_cleanup(exception_event)
}

Throw { owner, unwind -> bb_handler(exception_event) }
ResumeUnwind { exception_event }
Trap { kind, span }                 // sin successor excepcional
```

Todo call capaz de lanzar dentro de una región que necesita cleanup o handling
tiene successors normal y excepcional explícitos. Calls probados `nounwind`
pueden conservar un successor normal único. `Throw` empaqueta/transfiere el
owner y salta al cleanup/handler; `ResumeUnwind` abandona el frame con el mismo
evento.

El dispatcher de un try puede conservar catches ordenados como metadata
verificada o bajar a tests nominales explícitos:

```text
ExceptionMatches(event, CatchClassId) -> bool
CatchBindAlias(event, CatchClassId) -> owned class handle
```

Un test exitoso domina el binding estrechado. Un fallo pasa el mismo owner al
siguiente test. Si ninguno matchea, el evento se reanuda. Ningún branch duplica
el owner.

Cleanup blocks contienen Drops/Releases concretos en orden y después transfieren
el evento. Los estados `Uninitialized`, `Initialized`, `Moved` y condicionales
se computan sobre el CFG completo. Construcción parcial tiene un cleanup pad por
estado necesario o recetas parametrizadas verificables; nunca usa el destructor
completo sobre memoria parcial.

El verificador MIR debe rechazar:

- calls con unwind posible que omiten un edge requerido;
- traps con handler edge;
- eventos duplicados, perdidos, usados tras resume o destruidos dos veces;
- catch binding sin test de subtipo dominante;
- rethrow fuera del catch correcto;
- cleanup omitido, duplicado o desordenado;
- publicación o deinit de una construcción parcial;
- uso del result normal sobre el edge excepcional.

## 14. Representación SSA

SSA conserva los dos resultados mutuamente exclusivos de una invocación:

- el valor ordinario existe solo en el edge normal;
- un `ExceptionEvent` owned existe solo en el edge excepcional.

Se recomiendan block arguments o valores definidos por edge, según la convención
general que use SSA al implementar el vertical. No se recomienda TLS/global
`current_exception`: rompería reentrancia, ownership lineal y análisis local.

Los exceptional edges participan en reachability, predecessors, dominance,
frontiers, loops, phi placement y critical-edge splitting. Un join de eventos
selecciona exactamente un owner del predecessor ejecutado; no retiene, copia ni
fusiona objetos. El narrowing de un catch produce un handle tipado solo después
de `ExceptionMatches`; físicamente sigue apuntando al mismo objeto.

Operaciones conceptuales:

- `InvokeDirect`, `InvokeVirtual`, `InvokeInterface`;
- `ExceptionPack`, `ExceptionMatches`, `CatchBindAlias`;
- `ExceptionEndCatch`, `ResumeUnwind`, `UnhandledException`;
- ordinary ordered `Drop`/`Release` en cleanup blocks;
- `Trap`, sin exceptional successor.

Los optimizadores tratan invokes, matching, ARC y cleanup como efectos ordenados.
Pueden convertir invoke a call solo con una prueba vigente de `nounwind`, quitar
un handler inalcanzable por identidad nominal o coalescer cleanup blocks
equivalentes. Toda transformación vuelve a `verify_ssa`; ninguna decisión física
borra el ClassId, el edge kind o la disposición del owner.

Además de los invariantes MIR, SSA verifica dominance por edge, argumentos
exactos de successors, phis owning, disponibilidad exclusiva del result/evento
y una disposición terminal única del record en cada path.

## 15. LLVM y estrategia de unwinding

### 15.1 Alternativas

| Estrategia | Ventajas | Costos/riesgos |
| --- | --- | --- |
| Status/out-slot + CFG | Portable a targets sin unwinder; transporte visible | Cambia ABI de calls, agrega test en paths normales, complica function pointers/separate compilation y hace que un detalle inferido afecte firmas físicas |
| LLVM native EH puro | ABI de retorno/call normal intacto; propagación natural | Personalities, landing pads/funclets y tablas específicas por plataforma; fácil delegar demasiado cleanup al backend |
| CFG semántico + native EH físico | Verificación independiente y ABI normal sin status | Mantiene el costo de portar EH, pero confina esa complejidad al backend |

### 15.2 Recomendación

Usar el tercer modelo: **híbrido por capas**.

MIR/SSA contienen todo el CFG excepcional, los owners y los cleanups. En un
target admitido, LLVM baja invokes a `invoke`/landing pads o al modelo funclet
equivalente, y resume con el mecanismo nativo. El runtime/personality solo:

- reconoce un record de excepción Aether;
- transporta su owner;
- compara metadata nominal solicitada por tablas de catch;
- inicia/finaliza catch y reporta la excepción no manejada.

No escanea objetos Aether, no decide orden de destructores y no busca tipos por
string. Los landing pads ejecutan los blocks de cleanup que ya existen en SSA.
Si un backend necesita duplicar físicamente pads, debe preservar la receta
verificada y su provenance.

La primera implementación debe apuntar a Linux x86-64 con el ABI de unwinding
ya seleccionado y documentado. Windows/SEH, Darwin/ARM64 y WASI son admissions
independientes. Un target sin unwinding no transforma excepciones en abort de
forma silenciosa ni usa `setjmp` como fallback. Un backend event-out futuro es
posible si baja el mismo SSA y define un ABI uniforme para **todos** los
callables afectados; no es la recomendación inicial.

### 15.3 Metadata de matching

Cada descriptor de clase de excepción expone privadamente una identidad nominal
y un enlace al descriptor de su base exception. Matching inicial puede caminar
la cadena y cuesta O(profundidad de herencia). Los type tables de LLVM contienen
referencias a descriptors/identidades canónicas, nunca nombres.

Una optimización futura puede asignar intervalos link-time o caches, pero debe
seguir siendo collision-free bajo módulos y separate compilation. Hashes o
strings solos están prohibidos. Los nombres pueden existir como metadata
diagnóstica para un unhandled report, no como autoridad de matching.

## 16. Costos y predictibilidad

### Camino sin excepción

- construcción de una clase de excepción no ocurre si no se ejecuta;
- no hay `Result` ni status fuente y la firma normal no cambia;
- funciones con handlers/cleanup pueden generar `invoke`, landing pads y tablas
  de unwind, aumentando code size;
- calls probados `nounwind` conservan lowering directo;
- no se promete costo cero ni una tabla idéntica entre targets.

El unwinding nativo suele evitar un branch de status después de cada call, pero
no es literalmente gratuito: metadata, presión de optimización y cold blocks
son costos reales que deberán medirse en O0/O2.

### Camino excepcional

- construir la excepción cuesta la allocation/initialization ordinaria de clase;
- crear el record puede requerir otra allocation privada;
- propagar cuesta al menos O(frames atravesados + cleanup ejecutado);
- cada catch probado cuesta matching nominal, inicialmente O(profundidad);
- entrar a un catch owning puede agregar un retain/release;
- releases finales pueden producir cascadas de destrucción.

Por ello exceptions son adecuadas para paths excepcionales, no para control flow
de alta frecuencia o requisitos hard real-time. `Result`/status explícitos
siguen disponibles como diseño de library cuando costo y locality sean parte
del contrato.

La qualification debe separar code size, sitios `invoke`, tablas EH, eventos
ARC, allocations, cleanup ejecutado y tiempo normal/excepcional. Un único
benchmark de latencia no justifica afirmaciones de zero-cost.

## 17. Root y excepción no manejada

El entry Aether instala una frontera root. Una excepción que llega allí ya ha
ejecutado los cleanups de todos los frames Aether. El root toma ownership del
record, produce un diagnóstico determinista mínimo con el nombre nominal solo
para presentación, destruye record/payload y termina con status no exitoso.

El reporter es fail-fast y no puede lanzar. Un fallo al formatear/escribir no
crea una segunda excepción ni recurre al mismo mecanismo. Stack trace, message,
cause y exit code exactos quedan abiertos; el primer vertical puede imprimir
solo tipo y sitio original.

## 18. FFI

Ninguna excepción Aether cruza una frontera C, ni una excepción C++/host entra
por ella. `extern "C"` permanece un ABI no-unwind desde la perspectiva Aether.

- imports C comunican fallos mediante su contrato C explícito: status, errno,
  tagged result u opaque error handle;
- una excepción extranjera que atraviesa un shim declarado C viola la frontera;
  el shim debe capturarla y traducirla o terminar antes de entrar a Aether;
- exports/callbacks Aether tienen un catch-all root generado que contiene y
  termina, salvo que un adapter explícito traduzca `Exception` a un error ABI;
- un adapter recuperable captura `Exception` dentro de Aether y devuelve el
  status/handle documentado; no expone el record del unwinder;
- hasta diseñar esos adapters, exports/callbacks potencialmente excepcionales
  se rechazan o se limitan a la política root de terminación, nunca best-effort.

Los objetos de excepción que se exponen como opaque handles siguen el contrato
ARC/retain/release de clases, no el lifetime del record de unwinding. No se
exportan descriptors, ClassIds de sesión ni tablas EH como ABI público.

## 19. Interacción futura con `deinit`

Los user destructors deben ser **estáticamente non-throwing**. No admiten
`throw`, rethrow ni calls que no satisfagan una futura garantía fuerte de
non-throwing. Como las excepciones son unchecked en firmas ordinarias, esa
garantía requerirá una categoría restringida propia del destructor o una
verificación conservadora del call graph; no se infiere optimistamente.

Durante unwinding, el último release de un objeto completamente construido sí
ejecuta su `deinit` futuro y luego sus fields/base en el orden OOP definido. Un
objeto parcial nunca ejecuta `deinit`. Resurrección, publicación de `this` y
virtual dispatch desde destrucción siguen prohibidos según el diseño OOP.

Si código extranjero o corrupción produce un segundo unwind desde cleanup/
`deinit`, el runtime termina inmediatamente después de aplicar la política de
contención posible; no intenta elegir entre dos excepciones ni construir una
lista de suppressed exceptions. Esto conserva una disposición única del evento
y evita cleanup recursivo no determinista.

## 20. Primer vertical acotado recomendado

Nombre sugerido: **EXCEPTION-V1 — unchecked class exception spine**.

Target único: Linux x86-64, un solo thread, private ABI, native LLVM unwinding.
Debe admitir:

- la clase core `Exception` y clases finales no genéricas derivadas;
- `throw expression;`, bloques `try`, catches tipados ordenados y `throw;`;
- throw fresh y desde lvalue, matching exact/subtipo y catch-all `Exception`;
- propagación a través de calls directos y root unhandled;
- nested lexical scopes y cleanup de scalar, Buffer y class owners;
- fallo durante construcción base/derived con rollback parcial exacto;
- una excepción con payload scalar y otra con `Buffer<int>` para validar drop;
- HIR/MIR/SSA explícitos, verificadores independientes y LLVM EH nativo;
- O0/O2, contadores ARC/allocation/drop y sanitizer qualification.

Debe excluir:

- `finally`;
- virtual/interface/indirect invokes como superficie del vertical;
- generics, async, threads, exception filters y multi-catch;
- user destructors, public FFI adapters y stable ABI;
- strings/message/cause/stack trace como requisito;
- conversión de cualquier trap en exception.

Qualification mínima:

1. un subtype catch gana sobre su base cuando aparece primero;
2. un base catch captura un derived dinámico y conserva su identidad;
3. un catch posterior inalcanzable se rechaza con span;
4. bare rethrow llega al handler exterior sin repack ni fuga;
5. un helper sin declaración propaga a través de dos frames;
6. locals/temporaries se destruyen una vez, en orden inverso, antes del catch;
7. construcción parcial limpia solo campos/base inicializados y libera una vez;
8. throw/catch de owner lvalue/fresh produce balances ARC exactos;
9. overflow, bounds, allocation/ARC traps no entran a `catch (Exception e)`;
10. eventos/resultados edge-only, catch narrowing y cleanup corruptos fallan
    independientemente en HIR, MIR y SSA;
11. unhandled root destruye el payload y termina de forma determinista;
12. programas sin excepciones preservan comportamiento y no enlazan runtime EH
    Aether innecesario, salvo metadata mínima exigida por el target.

Virtual, interface e indirect invokes forman un vertical siguiente antes de
`finally`, porque deben validar function-pointer ABI, witnesses, keepalive y
result ownership en ambos successors.

## 21. Decisiones abiertas y gates

| Tema | Estado/gate |
| --- | --- |
| API exacta de `Exception` | Abierto: message/cause/stack trace no bloquean V1 |
| Spelling/prelude de la clase core | Cerrar al admitir parser/core modules |
| Grammar exacta y recovery | Cerrar en EXCEPTION-V1, preservando la superficie recomendada |
| ABI/personality Linux | Seleccionar y documentar antes del backend V1 |
| Windows, Darwin, ARM64, WASI | Qualification independiente por target; sin fallback silencioso |
| Separate compilation/dynamic libraries | Definir canonical descriptor identity/coalescing antes de exponer ABI |
| Finalmente que lanza | Resolver antes de admitir `finally`; recomendación inicial restrictiva |
| API FFI recuperable | Adapter/status/opaque handle en milestone FFI separado |
| User `deinit` | Requiere garantía non-throwing verificable antes de admisión |
| Generic exception constraints | Espera constraints nominales y class generics |
| Async/coroutines/cancellation | Requiere definir captura del frame y task boundary |
| Threads | Record, ARC atómico/isolation y unhandled thread policy separados |
| Stack trace/provenance | Elegir costo, optimización y symbolization por profile |
| OOM durante throw/report | Sigue fail-fast; emergency allocation/reporting queda abierto |
| Optimización `nounwind` | Análisis interno verificado, nunca cambio de función fuente |

## 22. Consecuencias

La recomendación da a Aether una experiencia reconocible de C#/C++ sin checked
signatures, GC, dynamic typing ni conversión implícita de traps. Limitar payloads
a una jerarquía nominal de clases reduce superficie y reutiliza la arquitectura
OOP ya calificada. El costo principal es portar y verificar unwinding nativo,
además de tablas/cold code incluso en paths normales.

La decisión más importante para la seguridad no es el mecanismo del unwinder:
es que ownership, construcción parcial y cleanup ya estén completos en MIR/SSA
y sean verificados antes de LLVM. El backend transporta un evento; no define la
semántica de vida de los objetos.
