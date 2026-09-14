# MODULE-STD-ARCH-1 — packages, imports, Core y standard library

Estado: **DECISIÓN DE ARQUITECTURA; NO IMPLEMENTADA**, 2026-09-13.

Este milestone fija la organización lógica del código y las bibliotecas de
Aether. No modifica todavía parser, resolver, HIR, MIR, SSA, backend, standard
library ni runtime. La gramática, resolución y distribución descritas aquí son
contrato para verticales posteriores, no superficie actualmente admitida.

Esta decisión refina la sección 9.1 de
[AETHER_V1_SEMANTIC_CONTRACT](AETHER_V1_SEMANTIC_CONTRACT.md), reemplaza el
modelo bootstrap de un archivo por módulo descrito en
[AETHER_COMPILER_ARCHITECTURE](AETHER_COMPILER_ARCHITECTURE.md) y migra el
spelling provisional `Text` de [TEXT-ARCH-1](TEXT_ARCH_1.md) a `std.Text`.
No altera las semánticas de string ni Text ya calificadas; cambia la identidad
y forma pública que deberá usar su siguiente vertical de migración.

## 1. Decisiones resumidas

- `package` declara la identidad namespace de un source; no se infiere del
  path físico.
- Un package puede contener símbolos y packages hijos directamente. Varios
  source files pueden contribuir al mismo package.
- Un source module o **source unit** es un archivo de implementación, imports,
  provenance y dependencias; no es el namespace público.
- La identidad pública de un member se deriva del package y la declaración,
  no del archivo que la contiene ni de su path absoluto.
- `import A.B` habilita la ruta calificada `A.B`; no inyecta sus members en el
  scope sin calificación.
- Importar una rama habilita referencias calificadas a descendientes, pero sólo
  los source units que poseen símbolos usados forman dependencias de código.
- `import A.B as x` crea solamente el binding local `x`; la identidad canónica
  continúa siendo `A::B`.
- `std` es la única raíz pública reservada de la standard library.
  `import std;` es inválido: debe nombrarse al menos una rama concreta.
- Lenguaje, Core/prelude, standard library explícita y runtime privado son
  capas distintas. Prelude no significa `import std.*`.
- No se diseñan wildcard imports, apertura de namespaces, imports selectivos,
  re-exports, registro de terceros, dependency manager ni inicialización de
  módulos.

## 2. Vocabulario normativo

### 2.1 Package

Un **package** es un namespace lógico jerárquico y una frontera de identidad.
Puede contener directamente funciones, constantes, aliases, structs, enums,
classes, interfaces y otros members que el lenguaje admita, además de packages
hijos. No es un objeto runtime, no ejecuta código y no exige un archivo
homónimo.

Un path de package es una secuencia no vacía de identificadores:

```text
MyProject.Numerical
std.Math.LinearAlgebra
```

La representación canónica usa segmentos, nunca un string que deba volver a
separarse. La notación de diagnostics y dumps es `MyProject::Numerical`.

### 2.2 Source module o source unit

Un **source module** es una unidad de implementación y dependencia. En el
primer vertical será un archivo source, aunque la abstracción no depende de que
el proveedor sea siempre un archivo local. Cada source unit contiene:

- exactamente una declaración de package;
- imports cuyo scope es sólo esa unidad;
- declaraciones que contribuyen al package;
- bodies, spans y provenance propios;
- edges a las unidades que poseen símbolos realmente usados.

`module` y `source unit` son sinónimos en esta arquitectura. No se introduce
una declaración source `module`; `package` no cambia el límite incremental,
de parsing o de imports de cada archivo.

### 2.3 Namespace

Un namespace es un nodo del árbol de packages visible durante resolución. Un
namespace puede existir sólo como prefijo y puede contener a la vez members y
children:

```text
std.Math.sin
std.Math.LinearAlgebra
```

Aquí `std.Math` contiene el member `sin` y el child `LinearAlgebra`. No hay
conflicto entre esos dos nombres distintos. Un member y un child con el mismo
nombre dentro del mismo package sí colisionan, porque `P.X` no tendría una
interpretación única.

## 3. Declaración de package

La forma decidida es:

```aether
package MyProject.Numerical;
```

La declaración es obligatoria en sources de proyecto y de stdlib, aparece una
sola vez y debe ser el primer item no trivia. Precede imports y declaraciones.
Un archivo vacío o generado todavía necesita una identidad suministrada por
una forma explícita del proveedor; el primer vertical no admite package
implícito.

Cada segmento sigue las reglas de identificadores del lenguaje. Los siguientes
casos son errores antes de declaración/resolución de bodies:

- package ausente, repetido o situado después de otro item;
- segmento inválido o path vacío;
- path cuya primera componente es `std` en source de proyecto;
- desacuerdo entre la declaración y el package asignado por el catálogo del
  proyecto;
- dos orígenes lógicos que reclaman la misma unidad o package sin que el
  proyecto los haya declarado como contribuciones del mismo package.

### 3.1 Varios archivos por package

Varios source units pueden declarar el mismo package. Sus declaraciones se
reúnen como una sola tabla de members antes de analizar bodies, en un orden
determinista definido por sus claves lógicas de source y no por `readdir`, hora
de modificación, path absoluto ni orden de importación.

Un package parcial no crea precedencia entre archivos. Todos los top-level
members del package ocupan una tabla unificada. Dos declaraciones con el mismo
nombre son error incluso si están en archivos distintos, salvo que un futuro
milestone admita overloads y defina una clave inequívoca para ellos. Un member
y un package child del mismo nombre también son error.

El orden textual sólo conserva significado dentro de una declaración cuando
otro contrato lo requiere —por ejemplo field order o enum variant order—. No
decide qué archivo “gana”. Forward references entre contribuciones se resuelven
después de completar la colección global del package.

### 3.2 Package y visibilidad

Este milestone no diseña una jerarquía de visibilidad compleja. Fija sólo que
la visibilidad futura se aplicará a la identidad package/member y no al path
físico. Un source unit no constituye por sí solo una frontera pública distinta.
La política bootstrap que exporta todo no se eleva a contrato final.

## 4. Identidades canónicas

La arquitectura separa claves lógicas estables de IDs densos de sesión:

```text
PackageKey  = (OriginKey, PackagePath)
PackageId   = intern(PackageKey)                  // session-local

SourceUnitKey = (PackageKey, LogicalSourceKey)
ModuleId      = intern(SourceUnitKey)             // session-local

DeclKey      = (PackageKey, MemberName, DeclDisambiguator)
SymbolId     = intern(DeclKey)                    // session-local
```

`OriginKey` distingue el proyecto actual, la toolchain estándar y, en el
futuro, dependencias declaradas. Para la superficie pública estándar, el path
canónico continúa mostrándose simplemente como `std::...`; el origin de
toolchain impide que un proyecto suplante esa identidad.

`LogicalSourceKey` lo asigna el proyecto/source provider y es estable bajo un
cambio del checkout absoluto. Para un proveedor filesystem puede ser un path
normalizado relativo a un source root declarado. No participa en la identidad
pública de un member. Mover una declaración entre dos source units del mismo
package no cambia su path público; sí cambia provenance, fingerprint del body y
la unidad que posee su implementación.

Mientras no existan overloads, `DeclDisambiguator` es la clase de declaración
sólo para validar/dumps y no permite dos members con el mismo nombre. Un futuro
sistema de overloads deberá definir su disambiguador semántico; no podrá usar
posición, discovery order ni `ModuleId` numérico.

Ejemplo:

```text
source spelling:    la.solve
namespace identity: std::Math::LinearAlgebra
symbol identity:    std::Math::LinearAlgebra::solve
owning ModuleId:    unit lógica que contiene el body de solve
```

`PackageId`, `ModuleId` y `SymbolId` densos no son ABI, mangling persistente ni
cache key cross-session. Artifacts, incremental caches y mangling usan las
claves/fingerprints estructurales correspondientes. Los spans siguen usando
`SourceId`; `SourceId` no reemplaza a `ModuleId`.

## 5. Catálogo de packages y relación con filesystem

La declaración source es autoridad de identidad, pero no puede descubrir por
sí sola todos los sources. Un `PackageIndex` determinista, construido desde la
configuración del proyecto/toolchain, relaciona:

```text
PackageKey -> children, contributed SourceUnitKeys, public member index
SourceUnitKey -> SourceProvider locator + content fingerprint
```

El locator puede ser un path, una entrada de archive o una unidad generada. No
entra en resolución semántica después de obtener la clave lógica.

Para el primer vertical de implementación se permite un manifest mínimo con
uno o más source roots y paths relativos normalizados. Si temporalmente se
escanea un root, el resultado debe ordenarse, rechazar duplicados/symlink
ambiguity y validar cada `package` contra el mapping declarado. El filesystem
ayuda a localizar; nunca decide por casualidad que `a/b.ae` significa package
`a` ni que el primer archivo encontrado gana.

No se define aquí formato final de manifest, registry, version solver ni
download de dependencias. Sí queda fijada la interfaz semántica que esas capas
deberán alimentar.

## 6. Imports jerárquicos

### 6.1 Forma y significado

Las formas admitidas por esta arquitectura son:

```aether
import std.Math;
import std.Math.LinearAlgebra;
import MyProject.Models;
import std.Math.LinearAlgebra as la;
```

Un import sin alias concede a esa source unit acceso calificado a la ruta
canónica completa:

```aether
import std.Math;

std.Math.sin(x);  // válido
sin(x);           // el import no lo introduce
Math.sin(x);      // tampoco se acorta automáticamente
```

No es wildcard, no copia declarations al scope local y no abre el namespace.
El import se resuelve a un `PackageId`/namespace identity antes de resolver los
members usados.

### 6.2 Descendientes

Importar un namespace habilita referencias calificadas a cualquier descendiente
existente bajo esa rama:

```aether
import std.Math;

std.Math.LinearAlgebra.solve(A, b); // permitido por el import de std.Math
```

Esto es una capacidad de lookup, no una dependencia eager sobre el subtree.
Cada siguiente segmento debe existir en el catálogo y cada member final debe
ser accesible. Importar `std.Math.LinearAlgebra` sigue siendo recomendable
cuando ésa es la única rama usada, porque expresa intención y reduce la
superficie consultada por tooling, aunque ambas formas producen la misma
identidad de `solve`.

Una rama hermana no queda habilitada. `import std.Math` no autoriza
`std.Text.trim` ni `Other.Math`.

### 6.3 Alias

Un alias puede nombrar un namespace completo:

```aether
import std.Math as math;

math.sin(x);
math.LinearAlgebra.solve(A, b);
```

También puede nombrar una rama hoja:

```aether
import std.Math.LinearAlgebra as la;
la.solve(A, b);
```

El alias es un `ImportBinding { local_name, target: PackageId }` local al
source unit. No crea package, re-export, symbol wrapper, ABI identity ni nombre
alternativo en HIR. Después de resolución, HIR conserva sólo la identidad
canónica y provenance del import para diagnostics.

No se admiten aliases sobre members individuales en este milestone. Eso sería
import selectivo y requiere otra decisión.

### 6.4 Duplicados y colisiones

- Repetir exactamente el mismo import en una source unit es error de import
  redundante. Se conserva la disciplina fail-closed del bootstrap actual.
- Dos aliases con el mismo binding son error, aunque apunten al mismo target.
- Un alias que coincide con otro import binding, una declaración visible del
  package o un nombre reservado de lenguaje es error en el import.
- Un parámetro, local o binding de pattern no puede declarar el mismo nombre
  que un alias o root importado visible en su scope. Se diagnostica la
  colisión; no se permite reinterpretar `la.x` por shadowing incidental.
- Imports sin alias que comparten el mismo root y apuntan a ramas compatibles
  se fusionan como permisos de lookup: `import std.Math; import std.Text;` es
  válido. Un mismo root spelling que resolviera a origins distintos es ambiguo
  y se rechaza.
- Dos rutas distintas que llegan a la misma identidad no son ambiguas una vez
  canonicalizadas, pero escribir ambas explícitamente sigue siendo import
  redundante y se diagnostica.

Los diagnostics deben señalar el import original y el conflictivo, mostrar el
target canónico y distinguir “binding duplicado”, “ruta inexistente”, “member
inaccesible” y “nombre local en conflicto”. Nunca se elige por orden textual o
filesystem.

## 7. Grafo de dependencias y reachability

La arquitectura distingue tres relaciones:

1. **lookup grant**: un import autoriza consultar una rama;
2. **semantic dependency**: una referencia resuelta usa un package/member y la
   source unit que lo declara;
3. **code/link reachability**: un body o dato emitido es transitivamente
   alcanzable desde entry/export roots.

Por tanto:

```text
imports declarados
  -> grants de namespace (baratos, pueden quedar sin uso)
  -> resolución lazy de qualified paths
  -> edges ModuleId -> owning ModuleId por symbols realmente usados
  -> reachability de declarations/instances/runtime helpers
```

El `PackageIndex` puede cargar headers/indexes de declarations para lookup sin
parsear o compilar todos los bodies descendientes. Sólo las source units que
contribuyen declaraciones consultadas necesitan análisis semántico; sólo los
bodies/instancias alcanzables necesitan lowering y emisión. La exactitud del
diagnóstico de una declaración encontrada puede exigir cargar su unidad, pero
nunca todo el subtree por definición.

Un import sin usos no crea por sí solo una dependencia de código o link. Una
firma pública usada puede crear dependencia de tipo aunque su body no sea
alcanzable. Generics y constants deberán agregar edges a sus instancias/datos
según sus contratos futuros.

Los cycles se analizan por clase de edge. Los cycles de namespace y
declaraciones sin inicialización son permitidos si declaration collection los
puede resolver. Layout, aliases, generics u ownership pueden tener sus propios
cycle errors. Como module initialization sigue fuera de scope, no se deriva
orden de ejecución de este grafo.

## 8. Raíz estándar `std`

`std` es una raíz canónica reservada y case-sensitive. Sólo el origin de la
toolchain puede suministrarla. Sources de proyecto no pueden:

- declarar `package std` ni `package std.X`;
- registrar un source root que capture `std`;
- crear un import alias llamado `std`;
- sustituir un package std mediante un archivo vecino o precedencia de search.

La organización inicial prevista es extensible:

```text
std
├── Text
├── IO
├── File
├── Math
│   └── LinearAlgebra
├── Collections
├── Random
└── Time
```

El árbol expresa ownership de nombres, no compromiso de implementar cada rama.
La existencia de un nodo se obtiene del manifest/catalog de la stdlib que
acompaña a la toolchain.

`import std;` es inválido. `std` es un contenedor reservado, no una unidad
importable; el import debe contener al menos dos segmentos, por ejemplo
`import std.Text` o `import std.Math`. Esto evita una puerta equivalente en la
práctica a toda la stdlib y mantiene legible la dependencia declarada.

No hay acortamiento implícito:

```aether
import std.Text;
std.Text.trim(s);          // válido
Text.trim(s);              // inválido

import std.Text as text;
text.trim(s);              // válido
```

## 9. Resolución de nombres

### 9.1 Tablas separadas

El resolver mantiene separadas:

- tablas lexicales de values/types;
- members del package actual;
- bindings de namespace importados en la source unit;
- catálogo de namespace children;
- bindings cerrados del prelude.

No intenta una lista de concatenaciones de strings ni busca archivos mientras
resuelve cada expresión.

### 9.2 Nombres no calificados

Para un nombre de value/type no calificado la precedencia es:

1. binding lexical más interno —parámetro, local o pattern—;
2. member del package actual;
3. binding del prelude.

Los imports no agregan una cuarta fuente de members sin calificación. Un member
del package puede shadowear un nombre del prelude de forma explícita y estable;
el compiler debería ofrecer warning de legibilidad, pero no ambigüedad. Los
aliases/import roots no participan en esta precedencia porque sus colisiones se
rechazan al declarar el binding.

### 9.3 Nombres calificados

El head de un path calificado se clasifica una sola vez:

- alias de import;
- root habilitado por uno o más imports sin alias;
- package actual/child accesible cuando la gramática permita su path completo;
- value/type lexical para operaciones de member definidas por otros contratos.

Una vez clasificado como namespace, cada segmento intermedio debe ser un child
namespace y el último puede ser child o member según el contexto. Nunca se
cambia a otro origin a mitad del path ni se interpreta un fallo como permiso
para probar el filesystem.

`std` no es un fallback global. Sólo puede iniciar resolución en una unidad que
importe una rama `std.X` que cubra el path usado. El prelude tampoco habilita
la raíz `std` ni ningún descendiente.

Si un spelling podría ser simultáneamente namespace y value/member, la
declaración que creó esa colisión ya es inválida. Si el contexto de uso aún no
selecciona una categoría única, se emite ambigüedad con candidates canónicos;
no hay heurística “preferir llamada”, “preferir type” o “preferir archivo”.

## 10. Las cuatro capas

### 10.1 A — Lenguaje

Algo pertenece al lenguaje cuando un programa no puede conservar su significado
portable sin que frontend, IR/verificadores o backend conozcan una regla
semántica especial: sintaxis, type identity, layout abstracto, ownership,
evaluación, operators, traps o invariantes optimizables.

Pertenecen aquí inicialmente:

- primitives escalares, `char`, `string` y sus literals/operadores
  fundamentales;
- refs y reglas de ownership;
- structs, enums, classes, interfaces y generics;
- exceptions y operators admitidos;
- `Array<T>` como colección computacional fundamental;
- `Vector<T, Orientation>`, `Matrix<T>` y sus views/operaciones estructurales
  nativas ya cerradas por los contratos matemáticos;
- sintaxis y semántica de `package`/`import`;
- conversiones numéricas escritas como `TargetType(expression)`, porque su
  chequeo/trap es semántica del lenguaje, no una función de biblioteca.

“Lenguaje” no implica scalar, opcode único ni implementación inline. `string`,
Array, Vector y Matrix son compiler-known core types aunque necesiten runtime o
algoritmos de biblioteca para partes de su implementación.

### 10.2 B — Core y prelude

**Core** es una biblioteca pequeña distribuida con la toolchain, estable y
compatible con el perfil de lenguaje. Puede implementar APIs normales usando
features del lenguaje y helpers privados. No tiene una raíz source importable.
Sus identidades internas se registran por el manifest de Core, no se falsifican
como members de cada package.

**Prelude** es la lista cerrada/versionada de símbolos de Core expuestos sin
import. Es una política de name resolution, no un wildcard ni un namespace.
La lista inicial de candidatos aprobada para concretar por vertical es:

```text
print, println
byteLength
abs, min, max, clamp
sqrt, exp, ln, sin, cos, tan
List<T>
```

La pertenencia final de una firma/overload exige su propio contrato, pero la
dirección queda cerrada: output elemental y matemática escalar fundamental no
requieren imports; `List<T>` es Core/prelude, no fundamental, aunque el
bootstrap pueda seguir siendo compiler-aware hasta existir una implementación
de biblioteca suficiente.

Una API entra al prelude sólo si es extremadamente común, pequeña, estable,
sin policy o dominio significativo y esperable como vocabulario básico de
Aether. Que sea tradicional en otro lenguaje no basta. Que use libm/runtime no
la vuelve intrinsic.

### 10.3 C — Standard library explícita

La standard library contiene políticas, algoritmos y dominios que no deben
ocupar el vocabulario universal. Se accede sólo por imports `std.X`:

```text
std.Text
std.IO
std.File
std.Math.LinearAlgebra
std.Math.Statistics
std.Collections
std.Random
std.Time
```

Ejemplos de frontera:

```aether
double y = exp(x) - 2*x*x;          // prelude

import std.Math.LinearAlgebra as la;
Vector<double, Column> x = la.solve(A, b); // STD explícita

usize n = byteLength(s);            // prelude
import std.Text;
List<string> parts = std.Text.split(s, ",");
```

Factorizaciones, solvers, decompositions, estadísticas, Unicode avanzado,
filesystem, random y time contienen algoritmos, datos o policy y pertenecen a
STD. Una función STD puede ser inlined o reconocida por identidad estable sin
convertirse por ello en lenguaje.

### 10.4 D — Runtime privado

El runtime conoce representación y límites de plataforma: allocation/free,
ARC, backing UTF-8, traps, transporte EH, syscalls/libc, layout helpers y
primitives de acceso que una biblioteca segura necesita.

No está debajo de `std`, no tiene package source importable y no participa de
lookup de usuario. Sus identidades pertenecen a un manifest ABI privado, por
ejemplo un `RuntimeSymbolKey`, y sólo lowering/backend o módulos privilegiados
de la toolchain pueden referenciarlas. En particular, el provisional
`std::private::TextCore` de TEXT-ARCH-1 se reclasifica como soporte privado no
representable desde source; no se reserva un escape `std.private`.

Que `println`, `sqrt` o `std.Text.substring` terminen llamando un helper runtime
no mueve su API pública a esta capa.

## 11. Clasificación inicial

| Elemento | Clasificación | Razón |
|---|---|---|
| `string` | lenguaje, fundamental owning | identidad, literals, UTF-8, lifecycle y operadores requieren contrato compiler/runtime |
| `Array<T>` | lenguaje, fundamental collection | identidad fija, storage, indexing y ownership son semántica central |
| `Vector<T,O>` | lenguaje, compiler-known mathematical core type | orientación, indexing y álgebra afectan tipos y optimización |
| `Matrix<T>` | lenguaje, compiler-known mathematical core type | shape/operadores/layout abstracto deben sobrevivir hasta optimización |
| `List<T>` | Core/prelude | colección de uso general; crecimiento es API, no construcción esencial del lenguaje |
| `print`, `println` | Core/prelude | output elemental siempre disponible; formatting/IO complejo queda fuera |
| `byteLength` | Core/prelude sobre operación fundamental | unidad explícita y O(1); no abre `std.Text` |
| `abs`, `min`, `max`, `clamp` | Core/prelude | vocabulario escalar pequeño; firmas exactas quedan para su vertical |
| `sqrt`, `exp`, `ln`, `sin`, `cos`, `tan` | Core/prelude | matemática escalar fundamental para la identidad científica de Aether |
| conversiones numéricas básicas | lenguaje | `T(expr)` selecciona conversión checked/IEEE con semántica propia |
| factorización, `solve`, SVD/eigen | `std.Math.LinearAlgebra` | algoritmos especializados y policy numérica |
| split/trim/search/Unicode | `std.Text` y descendientes | algoritmos de texto, policy y eventualmente datos Unicode |
| filesystem/random/time | STD explícita | efectos, plataforma o policy de dominio |
| allocate/ARC/syscall/UTF-8 backing/EH | runtime privado | conoce layout o frontera nativa y no es API de usuario |

Esta tabla clasifica ownership conceptual, no admite nuevas APIs ni obliga a
que `List` deje de ser compiler-known en un solo salto. La migración física se
hará sólo cuando cada representación tenga una ruta nativa verificada.

## 12. Prelude no es standard library implícita

El prelude:

- es pequeño, enumerado y versionado con el language profile;
- introduce símbolos individuales, no namespaces;
- no contiene `std`, `std.Math`, `std.Text` ni un patrón equivalente;
- no hace import, parse, compile o link de toda la stdlib;
- puede apuntar a bodies normales de Core y usar monomorphization/reachability;
- no implica opcode, intrinsic LLVM ni helper runtime por cada función;
- sólo agrega dependencia cuando un símbolo resuelto es efectivamente usado.

Así, esto no requiere imports:

```aether
double y = exp(x) - 2*x*x;
println("done");
```

pero esto sí:

```aether
import std.Math.LinearAlgebra as la;
la.svd(A);
```

El manifest de perfil fija exactamente qué `SymbolKey` corresponde a cada
nombre prelude. Una dependencia no puede modificar esa lista por precedencia.

## 13. Migración de Text

La forma provisional admitida actualmente:

```aether
import Text;
Text.contains(value, needle);
```

se reemplaza por:

```aether
import std.Text;
std.Text.contains(value, needle);
```

o por alias explícito:

```aether
import std.Text as text;
text.contains(value, needle);
```

No se conserva `import Text` como spelling alternativo ni como búsqueda
preferencial de la toolchain. Mantener ambos produciría dos reglas de root,
haría ambiguo un package de proyecto `Text` y perpetuaría identidad dependiente
del resolver bootstrap.

La nueva identidad canónica es `std::Text`; `text`, o cualquier otro alias, es
sólo binding local. Los nominales se convierten en
`std::Text::ScalarOffset` y `std::Text::FindResult`. Sus significados,
representaciones y operaciones de TEXT-V1 no cambian por el rename.

La migración debe ser atómica en el perfil que la admita:

- actualizar fixtures, examples y docs activos;
- diagnosticar `import Text` con un fix-it a `import std.Text`, sin aceptarlo;
- resolver el manifest de toolchain antes de cualquier source provider de
  proyecto para la raíz reservada;
- demostrar que un package/archivo vecino no puede suplantar `std::Text`;
- mantener el mismo `SymbolKey` canónico bajo alias distintos y la misma
  reachability pay-for-what-you-use.

Artifacts del perfil bootstrap anterior no obtienen compatibilidad source o
ABI automática; la versión de language/stdlib manifest declara la frontera.

## 14. Primer vertical de implementación

El primer vertical posterior recomendado es **MODULE-STD-V1 — package and
hierarchical import spine**. Debe implementar como una sola ruta nativa:

1. parsing de `package` y paths import jerárquicos con alias de namespace;
2. `PackageKey`/`SourceUnitKey` estables e IDs densos separados;
3. un manifest/source-provider mínimo y catálogo determinista;
4. contribución de dos o más source units al mismo package y colección global
   de declarations antes de bodies;
5. lookup calificado, descendientes, alias y la precedencia de esta decisión;
6. grafo separado de grants, dependencies semánticas y link reachability;
7. raíz reservada `std`, rechazo de `import std` y de shadowing;
8. migración exclusiva de TEXT-V1 a `std.Text`, sin implementar una API Text
   nueva;
9. dumps deterministas y corrupciones/verificación de identity ownership;
10. pruebas de paths absolutos distintos produciendo las mismas claves/dumps
    semánticos normalizados.

La qualification debe cubrir packages parciales, collisions cross-file,
member/child collision, imports sin uso, shared dependencies, declaration
cycles, missing/inaccessible path, imports redundantes, aliases duplicados,
alias/local collision, siblings no habilitados, descendientes lazy, `std`
reservado y ausencia de helpers/código para ramas no usadas.

Ese vertical no debe implementar wildcard/selective imports, re-exports,
manifest final, registry, third-party resolution, module initialization,
object-per-module, stdlib nueva ni runtime separado. HIR recibe identities ya
resueltas; MIR/SSA no vuelven a interpretar source paths o aliases.

## 15. Decisiones posteriores abiertas

No bloquean la arquitectura actual:

- formato final de project/workspace manifest y mapping de source roots;
- identidad/versionado de proyectos y dependencias de terceros;
- source packages relativos o reglas para packages anidados en workspaces;
- visibilidad pública/package/private completa y friend/test access;
- overload sets y su `DeclDisambiguator` estable;
- imports selectivos, si alguna vez justifican su costo;
- re-exports y API forwarding;
- aliases de package declarados en manifest;
- globals, constants con storage y module initialization/order;
- separate compilation, object-per-module, metadata binaria y ownership de
  instancias genéricas cross-package;
- estabilidad ABI/source de stdlib precompilada y distribución multi-target;
- política de warnings por imports sin uso y shadowing de prelude;
- namespace relativo dentro del package actual;
- versionado y override controlado de Core/prelude por language profiles.

Wildcard imports, `using namespace` y fallback filesystem heurístico no quedan
reservados como dirección; admitirlos requeriría una decisión que demuestre
resolución determinista, diagnostics y costos aceptables.

## 16. Consecuencias

La identidad pública deja de depender del archivo sin perder source units como
frontera incremental y de dependencias. Los packages parciales permiten
organizar proyectos grandes, con collisions globales y orden determinista. Un
import hace visible sólo una rama calificada; aliases abrevían localmente sin
contaminar HIR ni ABI. Descendientes son navegables sin compilar árboles
enteros, y el linker conserva reachability por símbolo.

`std` obtiene una raíz imposible de suplantar, mientras Core/prelude permanece
pequeño y distinto de la standard library explícita. El runtime queda fuera del
namespace de usuario. Esta separación permite que ergonomía matemática básica
sea inmediata y que algoritmos, policy y plataforma crezcan en bibliotecas sin
convertirse accidentalmente en sintaxis o intrinsics del compilador.
