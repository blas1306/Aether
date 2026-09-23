# PROCESS-ARGS-ARCH-1 — argumentos de proceso como valores Aether

Estado: **DECISIÓN DE ARQUITECTURA; NO IMPLEMENTADA**, 2026-09-22.

Este milestone define la primera superficie pública de argumentos de proceso
para `compiler-next`. No modifica parser, resolver, HIR, MIR, SSA, backend,
driver, standard library, runtime, fixtures ni programas admitidos. La
implementación y qualification corresponden a un vertical posterior.

La decisión compone la separación lenguaje/Core/STD/runtime de
[MODULE-STD-ARCH-1](MODULE_STD_ARCH_1.md), el `string` UTF-8 owning de
[GENERAL-ARCH-1](GENERAL_ARCH_1_STRING.md), `Array<string>` ya admitido por
[GENERAL-V2](GENERAL_V2_STRING_COMPOSITION_REPORT.md), las exceptions unchecked
de [EXCEPTION-ARCH-2](EXCEPTION_ARCH_2.md) y el entry source `int main()` de
[LANGUAGE-PARITY-1](LANGUAGE_PARITY_1_REPORT.md).

## 1. Decisiones resumidas

- La API pública inicial es `Array<string> std.Process.args()` y exige
  `import std.Process;`.
- El resultado contiene sólo argumentos de usuario. Excluye el nombre o path
  del ejecutable entregado como `argv[0]`.
- El `Array<string>` retornado es un owner Aether ordinario, de longitud fija,
  con backing independiente en cada call. Cada elemento es un owner `string`
  ordinario y conserva el orden del host.
- Ningún pointer, slice o borrow del `argv` host cruza la frontera pública. El
  wrapper copia primero el input a un snapshot runtime privado; `args()` copia
  desde ese snapshot a owners Aether.
- POSIX se valida como UTF-8 estricto. Un argumento inválido lanza
  `std.Process.InvalidArgumentEncodingException`; jamás se reemplazan bytes por
  U+FFFD ni se publica un prefijo.
- Windows recibe argumentos mediante la entrada wide del proceso y convierte
  UTF-16 bien formado a UTF-8. Un surrogate inválido produce la misma
  exception nominal.
- OOM, overflow de tamaños y corrupción de la frontera host/runtime son traps
  fail-fast, no `InvalidArgumentEncodingException`.
- El snapshot es estable. Cambiar elementos del Array retornado no cambia el
  estado global ni resultados posteriores.
- `int main()` source permanece sin parámetros. Un wrapper host generado
  recibe `argc`/`argv`, inicializa el snapshot privado, llama al entry Aether y
  lo destruye al salir.
- `std.Process.args` es una función STD ordinaria. No hay syntax, tipo de
  función, `ProcessOp` ni opcode público nuevos.

## 2. Superficie pública normativa

Las declaraciones conceptuales del package canónico son:

```aether
package std.Process;

class InvalidArgumentEncodingException : Exception {
}

Array<string> args();
```

El uso normal es:

```aether
import std.Process;

int main() {
    Array<string> arguments = std.Process.args();
    return int(length(arguments));
}
```

`InvalidArgumentEncodingException` es final en V1 y no necesita fields,
message, índice del argumento ni bytes ofensivos. Es una exception unchecked
ordinaria: el caller puede capturarla, pero la firma no se transforma en un
`Result` ni en una declaración checked. Una futura API de argumentos crudos
podrá diseñar su propio tipo sin cambiar el significado de `args()`.

El package `std.Process` pertenece exclusivamente al origin de la toolchain.
No se agrega al prelude, a Core ni a la raíz `std`; `import std;` continúa
inválido. No se crea `System`, alias legacy ni forwarding wrapper.

## 3. Semántica exacta de la secuencia

### 3.1 Exclusión de `argv[0]`

`args()` retorna sólo los argumentos que el usuario o launcher colocó después
del identificador del programa. Por ejemplo:

```text
./program ledger.alpt list
```

produce conceptualmente:

```aether
{"ledger.alpt", "list"}
```

La longitud es dos y el primer elemento es el path del ledger, no
`"./program"`.

Esta elección separa input de aplicación de metadata de lanzamiento. El valor
de `argv[0]` no es portable: puede ser relativo, absoluto, vacío, inventado por
un launcher, distinto del ejecutable real o no existir cuando el ABI admite
`argc == 0`. Incluirlo induciría a usarlo como path o identidad fiable sin poder
ofrecer esa garantía. Si en el futuro se necesita información del ejecutable,
debe existir una operación explícita con contrato de plataforma propio.

La adaptación usa esta regla total:

```text
host argc == 0       -> []
host argc >= 1       -> host arguments [1, argc), en el mismo orden
```

Un `argc` negativo, un vector ausente con count positivo o un pointer de
elemento nulo constituye corrupción de la frontera y hace trap. No se lee
`argv[argc]`, aunque el ABI host ofrezca allí un sentinel nulo.

### 3.2 Casos vacíos y contenido

Un proceso sin argumentos de usuario obtiene un `Array<string>` vacío válido.
No retorna `null`, un sentinel, una exception ni un Array con el ejecutable.

Un argumento de longitud cero es un elemento ordinario `""` y no se omite. Se
preservan exactamente cantidad, orden y contenido Unicode. Espacios, `:`, LF y
shell quoting no reciben interpretación dentro de la API. Los ABI de creación
de procesos POSIX y Windows no pueden transportar U+0000 dentro de un
argumento: `args()` no inventa ni promete un caso que el host no puede
entregar.

El shell, launcher o API de spawn ya decidió cómo separar la línea de comandos.
`args()` observa la secuencia recibida por el entry host; no vuelve a ejecutar
shell parsing, globbing, expansión de variables, quote removal ni normalización
de paths.

## 4. Tipo, mutabilidad y ownership

### 4.1 Por qué `Array<string>`

El count se conoce al entrar al proceso y no cambia. `Array<string>` expresa
esa forma exacta, contiguous y de longitud fija sin capacity, crecimiento,
`push`, `reserve` ni reallocations. `List<string>` introduciría una política de
colección dinámica que el dato no necesita y permitiría confundir mutación del
resultado con mutación de argv global.

La identidad nominal exacta es el `TypeData::Array { element: string }`
fundamental ya existente, no un alias, `ProcessArgs`, view o array host. Sus
propiedades estructurales siguen siendo las actuales:

```text
Copy = false
Relocatable = true
Storable = true
needs_drop = true
```

La longitud no puede cambiar. El Array vigente permite reemplazar un elemento;
esa mutación afecta sólo el valor retornado. “Snapshot” e “inmutable
estructuralmente” significan que la cantidad/estructura fija representa el
estado de entrada, no que se introduzca un nuevo Array read-only.

### 4.2 Resultado owning

Una call exitosa entrega un owner completo:

- el descriptor y backing de Array pertenecen al caller;
- cada slot inicializado contiene exactamente una obligación owning `string`;
- retornar, mover, almacenar, iterar y destruir usan las reglas existentes;
- Drop destruye elementos en orden inverso y después libera el backing una vez;
- un unwind posterior limpia el Array si ya fue publicado a un local vivo.

V1 construye un backing nuevo por call y copia cada argumento válido a un
string Aether owner. No adopta memoria del host, no publica strings que apunten
al snapshot privado y no conserva un borrow de startup. Para un argumento
vacío puede usar el singleton string vacío: sigue existiendo una obligación
owning lógica aunque retain/release físicos sean no-op.

Los strings son inmutables y no exponen identidad. Por ello una implementación
futura puede cachear owners canónicos y crear Alias exactos al llenar Arrays
nuevos, siempre que mantenga las mismas obligaciones, excepciones, contenido y
costos públicos no garantizados. El primer vertical recomendado debe usar la
estrategia conservadora de copia para calificar claramente la frontera.

### 4.3 Construcción transaccional

`args()` obtiene el count, hace aritmética checked para el backing exacto y
materializa los elementos de izquierda a derecha. El Array no se publica hasta
que todos sus slots estén inicializados.

Si la conversión del elemento `i` falla, se destruyen exactamente los owners
en `[0, i)`, se libera el backing parcial y recién entonces se lanza
`InvalidArgumentEncodingException`. No se entrega Array parcial, no se fuga el
argumento válido anterior y no se intenta convertir elementos posteriores.

OOM u overflow pueden ocurrir antes o durante esta construcción. Siguen las
reglas globales de traps abortivos y no prometen unwind; no se traducen a una
exception de encoding.

## 5. Encoding portable

### 5.1 POSIX

POSIX entrega cada argumento como una secuencia de bytes terminada en NUL, pero
no garantiza que esos bytes sean UTF-8. El terminador pertenece al ABI y no al
contenido. Un U+0000 embebido no es representable mediante `exec` y no se
confunde con un string Aether válido que sí podría contenerlo desde otro origen.

El adapter deriva una longitud checked una sola vez por argumento a partir del
terminador garantizado por el ABI, copia exactamente los bytes anteriores y no
usa `argv[argc]` como count. Antes de construir un `string`, valida UTF-8
estrictamente: rechaza overlong encodings, continuation bytes aislados,
secuencias truncadas, surrogates codificados y scalars mayores que U+10FFFF.
No normaliza Unicode, locale, case ni paths.

Un byte sequence inválido produce
`std.Process.InvalidArgumentEncodingException`. No se aplica locale, no se usa
la codificación ambiental y no se insertan replacement characters. Esta policy
evita presentar como texto válido un nombre que el caller ya no podría comparar
o reabrir byte-exactamente.

### 5.2 Windows

El port Windows debe usar el entry wide nativo (`wmain` o la frontera wide
equivalente declarada por el target/toolchain), nunca el `argv` narrow de una
code page ambiental. El snapshot copia las unidades UTF-16 de los argumentos
`[1, argc)` y conserva sus longitudes antes de entrar al código Aether.

La conversión reconoce BMP scalars no surrogate y pares high+low surrogate, y
emite UTF-8 canónico. Un high surrogate sin low, un low aislado o cualquier
secuencia UTF-16 mal formada lanza `InvalidArgumentEncodingException`. No usa
best-fit mapping, `?`, U+FFFD ni la code page activa.

La separación en argumentos sigue la que entrega la frontera wide elegida por
la toolchain. Aether no promete que reglas de quoting de Windows sean idénticas
a las de un shell POSIX; sí promete que, una vez recibida la secuencia, preserva
count, orden y valores Unicode.

### 5.3 Mecanismos descartados

| Alternativa | Decisión |
|---|---|
| trap por encoding inválido | rechazada: es input externo recuperable y la jerarquía unchecked ya permite cleanup/catch |
| `Result<Array<string>, E>` | rechazada: introduciría un `Result` transversal sólo para esta frontera y haría más pesada la ruta normal |
| variante checked propia | rechazada: obliga a transportar/matchear el Array completo aunque casi todos los entornos entregan texto válido |
| replacement U+FFFD | rechazada: pierde bytes silenciosamente y puede cambiar identidad de paths, comandos o valores |
| interpretar POSIX según locale | rechazada: no es estable ni satisface el invariante universal UTF-8 de `string` |
| exponer bytes o pointers host | rechazada: rompe tipo, lifetime, seguridad y portabilidad; una API raw requerirá otro milestone |

## 6. Snapshot y llamadas múltiples

La secuencia observada es la del entry del proceso y permanece estable durante
toda la ejecución Aether. Una llamada no relee `/proc`, el command line, una
variable global mutable del usuario ni una API susceptible de haber cambiado.

Cada llamada exitosa devuelve un Array backing distinto. Por tanto:

```aether
Array<string> first = std.Process.args();
Array<string> second = std.Process.args();
first[0] = "changed";
```

no modifica `second`, el snapshot privado ni una tercera llamada. Los strings
son owners ordinarios; compartir backing inmutable mediante Alias sería
semánticamente invisible, pero V1 copia desde el snapshot para mantener una
frontera simple.

El runtime puede memoizar validación o strings en un futuro sin cambiar:

- count, orden ni contenido;
- excepción ante input no representable;
- independencia de los backings Array;
- ownership y Drop de cada elemento retornado;
- imposibilidad de mutar el snapshot mediante el resultado.

Si el snapshot contiene una secuencia no representable, toda call que alcance
ese elemento vuelve a lanzar la misma clase de exception; capturarla no corrige,
omite ni reemplaza el argumento global.

No se promete igualdad de direcciones, counts ARC, cantidad exacta de
allocations a través de versiones ni que dos calls repitan físicamente la
conversión.

## 7. Entrada host y lifecycle del runtime

### 7.1 Wrapper elegido

El entry source continúa siendo exactamente un `int main()` no generic y sin
parámetros. La función Aether conserva su firma interna `() -> int`. El usuario
no puede declarar `main(int argc, ...)`, `ref argv`, variadics ni un overload.

El backend ya separa la función Aether seleccionada del `main` host generado.
Cuando `std.Process.args` es alcanzable, ese wrapper se vuelve target-specific:

```text
POSIX host main(argc, argv)
  -> process_snapshot_init(argc, argv)
  -> Aether main()                         // firma source intacta
  -> process_snapshot_dispose()
  -> chequeos finales de lifecycle
  -> process status
```

En Windows la primera función es la entrada wide equivalente. Esta solución se
elige frente a agregar parámetros ocultos a todas las funciones o cambiar la
firma Aether. Sólo el wrapper conoce el ABI host.

### 7.2 Snapshot runtime privado

`process_snapshot_init` copia las entradas de usuario a storage runtime privado
y length-aware. En POSIX guarda bytes; en Windows guarda code units UTF-16. No
crea aún strings Aether ni valida encoding, porque el fallo recuperable debe
ocurrir dentro de `args()` y poder ser capturado por source Aether.

El estado queda read-only después de publicación y no es importable. Contiene
count, longitudes y storage owned; nunca pointers al vector o stack de startup.
La inicialización checked rechaza counts, productos, sumas o pointers
inconsistentes con un trap de frontera. El estado se destruye exactamente una
vez después de terminar el entry Aether, tanto en retorno normal como en la
ruta de exception no capturada.

El storage privado no es un owner Aether ni puede falsear el contador de
allocations vivas usado para calificar Array/string. El vertical debe o bien
destruirlo antes del audit final, o contabilizarlo en un dominio runtime
separado igualmente balanceado. No puede dejar un cache process-global vivo al
momento del chequeo de leaks.

### 7.3 Reachability

Un programa que no referencia `std.Process.args` no necesita snapshot, helper
de encoding, exception ni firma host con argumentos por causa de esta feature.
Importar `std.Process` sin usar `args` concede lookup pero no crea code/link
reachability.

Una call alcanzable agrega edges a:

- el wrapper/init/dispose del snapshot para el target;
- el body/adaptador de `std.Process.args`;
- construcción y Drop de `Array<string>`;
- validación/conversión POSIX o Windows correspondiente;
- `InvalidArgumentEncodingException` y transporte EH;
- runtime string/Array ya seleccionado por los tipos owning.

No arrastra environment, filesystem, IO, cwd, spawning ni APIs de proceso
adicionales.

## 8. HIR, MIR, SSA y backend

### 8.1 Resolución y HIR

El catálogo de la toolchain registra `std.Process`, `args` y la class nominal.
El import sigue las reglas jerárquicas vigentes. Resolución exige aridad cero y
retorno exacto `Array<string>`; alias de package funciona de forma ordinaria:

```aether
import std.Process as process;
Array<string> values = process.args();
```

HIR representa una direct call a la identidad canónica
`std::Process::args`. El resultado es un value owning fresco/Transfer y la call
es `reads_external`, `may_allocate` y `may_unwind`; no es pure, constant-foldable
ni hoistable. No se agrega un `ProcessOp`, AST node o regla de sintaxis.

### 8.2 MIR y SSA

MIR baja la call ordinaria con su return place `Array<string>`, successor normal
y exceptional successor cuando el contexto necesita cleanup. En éxito se
publica exactamente un owner. En unwind no existe resultado inicializado que el
caller deba destruir; el callee/adaptador limpia toda construcción parcial.

SSA conserva la identidad de call, type exacto, orden effectful, ownership del
resultado y `may_unwind`. Sus verificadores deben rechazar:

- retorno que no sea `Array<string>`;
- resultado marcado Copy o sin obligación Drop;
- call sin exceptional edge cuando hay cleanup vivo;
- duplicación, Drop faltante o Drop doble del resultado;
- intento de tratar el snapshot o un pointer host como operand source-visible.

`Function`/`TypeData::Function`, function values e indirect-call ABI no cambian.
Tomar `args` como function value, cuando la visibilidad vigente lo permita,
conserva el tipo completo `Function<(), Array<string>>`; no transporta argc ni
un parámetro implícito.

### 8.3 Backend y frontera privada

El backend puede reconocer la identidad exacta de la declaración STD para
emitir su adaptador, como bootstrap de una función normal respaldada por
runtime privado. El helper recibe sólo el snapshot runtime ya inicializado y un
return channel compatible con el ABI owning actual. Status/pointers internos
no son ABI público Aether y ninguna exception cruza una frontera C sin el
wrapper Aether correspondiente.

La validación y copia nunca se modelan como concatenaciones. Un pass no puede
eliminar, duplicar, reordenar ni memoizar la call sin demostrar equivalencia de
allocations observables permitidas, exceptions, ownership y effects. O0 y O2
deben preservar la misma secuencia y cleanup.

## 9. Complejidad y allocations

Para `n` argumentos de usuario y `B` bytes UTF-8 resultantes:

- inicializar el snapshot cuesta O(n + bytes/code-units host) una vez;
- una call V1 cuesta O(n + B);
- el backing no vacío del Array requiere una allocation exacta;
- cada argumento no vacío requiere como máximo una allocation string propia;
- el vacío puede reutilizar el singleton;
- Drop cuesta O(n) más los releases/frees de sus strings.

No hay rescans desde cero, crecimiento geométrico, `List`, concat incremental
ni comportamiento O(B²). Cada input unit se mide/copia/valida un número
constante de veces. La suma de longitudes, el tamaño del backing, los offsets y
la expansión UTF-16→UTF-8 usan aritmética checked antes de allocation o GEP.

El contrato semántico no congela la cantidad física exacta de allocations:
empty singletons, allocation fusion, cache y ARC elision verificada pueden
optimizarla. Sí congela ownership, contenido, complejidad lineal e independencia
observable.

## 10. Invariantes de seguridad

La implementación debe mantener conjuntamente:

- `argc` se valida antes de convertirlo a `usize` o restar uno;
- sólo se consultan slots `[1, argc)` y nunca fuera del count;
- todo pointer requerido por un count positivo se valida según la frontera;
- la longitud se obtiene una vez y no incluye el terminador host;
- NUL embebido no se simula ni se trata como contenido transportable;
- toda suma, multiplicación, expansión y allocation size es checked;
- UTF-8/UTF-16 se valida completamente antes de publicar cada string;
- no se publica un owner parcial ni un string inválido;
- ningún pointer host o snapshot pointer aparece en HIR/MIR/SSA source-facing;
- ningún resultado presta storage del wrapper, stack, CRT o runtime startup;
- init/dispose es balanceado en return y exception no capturada;
- mutar o destruir un resultado no cambia el snapshot ni otro resultado.

Los ABI host válidos garantizan terminación de cada argumento. Defenderse de
un proceso que invoca `main` manualmente con pointers arbitrarios fuera del
contrato de plataforma no es una capacidad de memoria segura que C/LLVM pueda
proveer sin longitudes; tal estado se clasifica como corrupción host, no input
de aplicación. Aether no debilita el contrato fingiendo longitudes ausentes.

## 11. Qualification requerida para PROCESS-ARGS-V1

El primer vertical debe calificar al menos:

### 11.1 Superficie y semántica

- import canónico, alias de import, ausencia de import y rechazo de `System`;
- aridad y tipo de retorno exactos;
- cero, uno y varios argumentos;
- argumento `""`, espacios, `:`, tabs/newlines transportables por la API host;
- ASCII, UTF-8 multibyte, combining scalars y emoji;
- argumento largo cerca de límites prácticos del test host;
- orden preservado y exclusión inequívoca de `argv[0]`;
- `argc == 0` mediante adapter inyectable, aunque el runner normal no lo cree;
- quoting/globbing no reinterpretado dentro de Aether.

### 11.2 Ownership y lifecycle

- Array vacío válido y no nulo semánticamente;
- backings Array distintos en calls múltiples mediante mutación de uno;
- strings owners utilizables después de descartar el snapshot adapter de test;
- Transfer por retorno, moves, early return, iteration y Drop exacto;
- cleanup del prefijo ante encoding inválido en una posición intermedia;
- cleanup por exception posterior a una call exitosa;
- cero leaks/double drops y balance runtime separado;
- O0/O2 con el mismo resultado y contadores de lifecycle contractuales.

### 11.3 Encoding y plataforma

En POSIX, los tests deben lanzar un child con `OsString`/API byte-preserving
para entregar un argumento no UTF-8 y comprobar la exception nominal sin
replacement. Deben cubrir secuencias truncadas, overlong/continuation inválida
y bytes válidos de 2, 3 y 4 unidades.

El adapter Windows debe tener tests target-independent de UTF-16 para BMP,
pares surrogate, argumentos vacíos y surrogates aislados/mal emparejados. Una
CI Windows futura debe además ejecutar el binario mediante el entry wide y
comprobar Unicode/emoji reales. Si el CI inicial sólo es Linux x86-64, el
vertical puede admitir exclusivamente POSIX pero no declarar Windows
calificado; los tests puros de conversión y la estrategia wide quedan como gate
obligatorio del port.

### 11.4 Pipeline y reachability

- HIR/MIR/SSA muestran una call ordinaria con `Array<string>` owning y
  `may_unwind`, no `ProcessOp`;
- corrupciones independientes de tipo, ownership, Drop y exceptional edge son
  rechazadas por cada verifier correspondiente;
- helper/init/dispose/exception aparecen sólo con una call alcanzable;
- import sin uso y programa sin import no arrastran runtime Process;
- firma del entry source continúa `int main()` sin parámetros;
- wrapper POSIX usa count/vector host y el futuro wrapper Windows usa wide;
- regresión completa de packages, strings, collections, exceptions, IO y
  expense tracker codec.

## 12. Fixture Expense Tracker posterior

PROCESS-ARGS-V1 debe agregar una fixture ejecutable separada del codec ya
calificado, reutilizando su dominio/parsing, que acepte al menos:

```text
program ledger.alpt add 42 12.5 food
program ledger.alpt list
program ledger.alpt summary
```

Las secuencias observadas por Aether son respectivamente:

```text
["ledger.alpt", "add", "42", "12.5", "food"]
["ledger.alpt", "list"]
["ledger.alpt", "summary"]
```

La fixture debe demostrar dispatch, count/orden, parsing mediante
`std.Text.parseInt`/`parseDouble`, strings con espacios/Unicode y diagnostics de
uso por argumentos faltantes o sobrantes. Puede operar sobre un ledger en
memoria o sobre contenido fixture controlado; no debe afirmar persistencia
atómica ni introducir `writeTextAtomic`/`appendText` como workaround.

Este milestone arquitectónico no agrega esa fixture. Sólo fija su obligación
para el vertical de implementación.

## 13. Fuera de scope

No se diseñan ni admiten:

- environment variables, cwd o búsqueda del executable;
- process spawning, wait, pid, signals o una API nueva de exit;
- stdin/stdout, shell parsing, named options o framework CLI;
- bytes/raw argv, paths no-Unicode o una API lossy;
- mutación global de argv o setter de argumentos;
- `main` con parámetros source, variadics o overloads de entry;
- threading/reentrant runtime initialization;
- append, durable write o publicación atómica del Expense Tracker;
- estabilización de ABI pública de Array, string, exception o runtime.

## 14. Cierre

PROCESS-ARGS-ARCH-1 queda cerrado porque fija superficie, exclusión de
`argv[0]`, tipo nominal, ownership, snapshot, encoding, error, wrapper host,
reachability, IR, complejidad, invariantes y qualification. El vertical puede
implementar Linux x86-64/POSIX primero sin rediseñar source ni IR; Windows queda
normativamente definido y debe calificarse antes de declararse soportado.
