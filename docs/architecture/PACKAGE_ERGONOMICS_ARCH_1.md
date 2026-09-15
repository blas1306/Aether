# PACKAGE-ERGONOMICS-ARCH-1 — optional package declarations

Estado: **DECISIÓN DE ARQUITECTURA; NO IMPLEMENTADA**, 2026-09-15.

Este milestone hace opcional la declaración `package` en `compiler-next` para
que un programa pequeño pueda comenzar directamente por imports o
declaraciones. Sólo fija el contrato de arquitectura: no modifica parser,
catálogo, resolver, HIR, MIR, SSA, backend, runtime, CLI, tests ni compiler
legacy, y ningún source nuevo queda admitido hasta un vertical posterior.

Esta decisión refina la obligación de package explícito de
[MODULE-STD-ARCH-1](MODULE_STD_ARCH_1.md). Se conservan sin cambios sus packages
nombrados, imports jerárquicos, origins, packages parciales y separación entre
source unit y namespace público. La única excepción es una identidad de package
anónima, deliberadamente no importable y limitada a una unidad en V1.

## 1. Decisiones resumidas

- `package A.B;` es opcional, pero si aparece sigue siendo el primer item no
  trivia y sólo puede aparecer una vez.
- Una unidad sin esa declaración pertenece al **anonymous package** del grafo.
  `default package` es sólo una descripción informal, no un nombre source.
- El anonymous package posee una variante nominal interna; no se representa con
  `"main"`, `"default"`, `"root"`, `"anonymous"` ni un `PackagePath` vacío.
- No existe spelling para importarlo, no participa en el árbol de namespaces y
  sólo sus propias declaraciones pueden resolver sus members sin calificación.
- Un entry anónimo puede importar packages nombrados de proyecto o `std` con la
  sintaxis existente.
- V1 admite exactamente una source unit anónima por source graph. No agrega por
  proximidad otros archivos sin package, aunque estén bajo el mismo source root.
- Un grafo mixto es válido únicamente cuando la unidad anónima es el entry y sus
  edges alcanzan unidades nombradas. Una unidad nombrada nunca alcanza la
  anónima mediante import.
- `main` se selecciona en el entry como hoy, independientemente de que su package
  sea named o anonymous. No se introduce script mode.
- El path físico localiza una unidad pero nunca infiere su package. Las formas
  `main.ae`, `./main.ae` y el path absoluto de ese mismo archivo producen la
  misma identidad semántica.
- Packages nombrados multi-file, imports, `std`, entrypoint ABI y compiler legacy
  permanecen sin cambios.

## 2. Sintaxis

La gramática conceptual de una unidad pasa a ser:

```text
SourceUnit   := PackageDecl? ImportDecl* TopLevelDecl+
PackageDecl  := "package" PackagePath ";"
PackagePath  := Identifier ("." Identifier)*
```

Por tanto son válidos:

```aether
int main() {
    return 0;
}
```

```aether
import std.File;
import std.Text;

int main() {
    return 0;
}
```

y continúa siendo válido:

```aether
package Examples.WordStats;

int main() {
    return 0;
}
```

Comentarios, whitespace y demás trivia no cuentan como items. Si existe,
`package` debe preceder imports y declaraciones. La opcionalidad no relaja la
forma de `PackagePath`, la reserva de la raíz `std`, la posición de imports ni
la exigencia vigente de al menos una declaración top-level. Un archivo que sólo
contiene imports sigue siendo inválido por esa última regla, no por carecer de
package.

El parser debe reconocer específicamente `KwPackage` en cualquier posición
top-level posterior. Si ya consumió un package inicial, el caso es package
duplicado; si no lo consumió, es package fuera de posición. No debe dejar que
estos casos caigan accidentalmente en el diagnóstico genérico de una función o
clase mal formada.

## 3. Semántica del anonymous package

Cada source graph puede poseer cero o una identidad `AnonymousPackage`. Es un
scope package-local para las declaraciones de su única unidad, no un namespace
público, un segmento vacío ni el package padre de los packages nombrados.

Sus propiedades normativas son:

- no tiene nombre source, ruta canónica pública ni binding de namespace;
- no puede aparecer como target de un `import` o como prefijo de un path
  calificado;
- no tiene children y ningún package nombrado es child suyo;
- no colisiona con ningún `Named(origin, path)`, incluso si el usuario declara
  `package anonymous;`, `package default;`, `package root;` o `package main;`;
- reúne sus members para lookup sin calificación igual que un package nombrado;
- participa normalmente en chequeo de duplicados dentro de su unidad;
- puede usar prelude/Core y grants de imports igual que una unidad nombrada;
- no crea export público, re-export ni unidad descubrible por consumidores.

`anonymous`, `default` y expresiones como `<anonymous package>` sólo pueden
usarse como etiquetas explicativas en diagnostics o dumps. No son
identificadores reservados ni claves que el resolver vuelva a parsear.

La ausencia se conserva hasta semántica. No se sintetiza un `AstPackage` y no
se reescribe el source como `package main;`.

## 4. Source graph y política multi-file V1

### 4.1 Entry nombrado

El catálogo comienza por el package declarado por el entry y descubre las
contribuciones e imports nombrados según MODULE-STD-V1. Archivos sin package que
estén físicamente en el source root son candidatos no alcanzables: no entran en
el grafo, no contribuyen al package del entry y no se fusionan entre sí.

### 4.2 Entry anónimo

El proveedor agrega explícitamente el archivo entry como la única unidad del
anonymous package, sin intentar encontrarlo mediante un package header. Sus
imports se resuelven exclusivamente a packages nombrados y el descubrimiento
continúa desde esos targets con las reglas existentes.

```text
anonymous entry
  ├── import Project.Tools -> Named(Project, Project::Tools)
  └── import std.Text      -> Named(Toolchain, std::Text)
```

Los otros archivos sin package encontrados durante el scan no son dependencias
implícitas. Su presencia física aislada no es un conflicto y no obliga a
compilarlos. Esto mantiene la propiedad de que estar dentro de un directorio no
crea semántica.

### 4.3 Restricción de composición

V1 permite **una sola SourceUnitKey anónima en un ParsedProgram/source graph**.
Si una API multi-input, manifest, proveedor generado o futura forma de
discovery intenta agregar una segunda unidad sin package al mismo grafo, la
construcción del catálogo falla antes de collection de declarations. No se
elige una por orden, no se infiere que comparten package y no se usa el
directorio para decidirlo.

Esta restricción es preferible a fusionar archivos anónimos en el primer
vertical porque el modelo actual descubre composición por identidades named e
imports. El anonymous package no ofrece un target que pueda expresar qué
archivos contribuyen; fusionarlos por source root convertiría ubicación física
en membership semántico y haría que archivos no alcanzados alterasen el build.

Una ampliación multi-file futura requerirá una lista explícita de inputs o un
manifest que asigne contribuciones al singleton anónimo. No podrá inferirse sólo
por vecindad.

### 4.4 Grafos mixtos

Es válido que el grafo contenga la unidad anónima entry y cualquier número de
unidades de packages nombrados alcanzadas por sus imports. No es válido crear
un edge hacia la unidad anónima:

- la sintaxis `import` siempre denota un `PackagePath` named no vacío;
- el catálogo de namespaces no registra la identidad anónima;
- un entry nombrado no descubre archivos anónimos;
- una API interna que intente construir un `ResolvedImport` hacia
  `AnonymousPackage` debe fallar cerrada como grafo inválido.

Los cycles posibles siguen siendo sólo entre packages nombrados. El anonymous
entry puede iniciar esos edges pero no recibir uno de vuelta.

## 5. Imports y resolución de nombres

En una unidad anónima, imports como estos conservan exactamente su significado:

```aether
import std.Text;
import Project.Models as models;
```

No abren namespaces ni introducen members sin calificación. Los targets se
resuelven a `Named(Toolchain, std::Text)` y
`Named(Project, Project::Models)`. Aliases, duplicados, grants de descendientes,
colisiones, semantic dependencies y link reachability mantienen el contrato de
MODULE-STD-ARCH-1.

Un `AstImport` nunca puede denotar el anonymous package: su path contiene uno o
más identificadores y se consulta sólo en el índice named. Por ello no existe
un spelling especial cuya importación haya que reservar. Por ejemplo,
`import anonymous;` significa un intento ordinario de importar el package named
`anonymous`; funciona si ese package nombrado existe y en caso contrario emite
el diagnóstico normal de ruta inexistente. Nunca selecciona la identidad
anónima.

Dentro de la unidad anónima, un nombre no calificado sigue la precedencia:

1. binding lexical;
2. member del anonymous package;
3. prelude/Core.

La resolución calificada sólo considera aliases y roots named concedidos por
imports. El anonymous package no se prueba como fallback.

## 6. Entrypoint

La regla de entrypoint no depende de `PackageKey`. El compiler busca el member
`main` en el `ModuleId` marcado como entry y aplica el contrato vigente:
`int main()` sin parámetros. Un `main` perteneciente a una unidad importada no
reemplaza al entry ni se vuelve candidato adicional.

Así, ambos programas se ejecutan por la misma ruta:

```aether
int main() { return 0; }
```

```aether
package App;
int main() { return 0; }
```

El wrapper nativo `main`, conversión de status, manejo de excepción no capturada
y roots de reachability permanecen idénticos. La feature no admite statements
top-level ni un modo de script alternativo.

## 7. Identidad canónica

`PackagePath` continúa siendo una secuencia **no vacía** reservada a packages
nombrados. La identidad debe expresar la suma, no sobrecargar el vector:

```text
PackageKey =
    Named { origin: OriginKey, path: NonEmptyPackagePath }
  | Anonymous(AnonymousPackageKey)

AnonymousPackageKey = marcador nominal graph-local del proyecto actual

PackageId = intern(PackageKey)                    // session-local
SourceUnitKey = (PackageKey, LogicalSourceKey)
SymbolKey = (PackageKey, MemberName, Disambiguator)
```

La variante anónima no porta un string elegible por el usuario. Es única dentro
del grafo y sólo admite `OriginKey::Project`; toolchain, Core y dependencias
publicables deben usar identities named. Dos sesiones pueden internarla con el
mismo tag de clase porque sus IDs y grafos no se comparan directamente. Una
cache persistente de su unidad usa `LogicalSourceKey`, content/config
fingerprints y el tag estructural, no un nombre inventado ni el path absoluto.

`PackageId` puede identificar ambos casos. `ModuleId` continúa identificando la
unidad y `SourceId` sus spans. En V1 la cardinalidad anónima garantiza un único
`SourceUnitKey` bajo ese `PackageId`; no obstante los verificadores deben validar
la cardinalidad y no asumirla por el orden de IDs.

El árbol de namespaces, prefix packages, maps de roots importables y
`PackagePath::source/canonical` aceptan sólo la variante named. Código común que
necesite mostrar una identidad debe hacer pattern matching explícito; nunca debe
llamar operaciones de path sobre anonymous.

### 7.1 Symbols y mangling

Un member anónimo conserva identidad nominal estructural:

```text
SymbolKey(Anonymous, "helper", declaration disambiguator)
```

No equivale a `Named(Project, main)::helper` ni a ningún otro package. Como el
anonymous package no es importable ni publicable, esa identity es graph-local y
no constituye ABI pública cross-package.

El mangler recibe el discriminante estructural. Para símbolos no-entry usa un
tag reservado del esquema de mangling que no pueda obtenerse escapando un
identifier Aether, seguido del member/disambiguator habitual. El spelling
exacto del tag es detalle del vertical, pero las invariantes no lo son:

- salida determinista para el mismo grafo;
- ninguna colisión con un package named ni con helpers de runtime;
- nunca incorporar CWD o path absoluto;
- mangling de todos los packages nombrados byte-for-byte sin cambios;
- el wrapper ABI del proceso continúa siendo `main` y llama al símbolo Aether
  resuelto del entry como hoy.

Esto no cambia una ABI existente: los símbolos anonymous son superficie nueva y
no exportable. Visibilidad/linkage física de helpers continúa bajo la política
actual hasta un milestone separado; esta decisión no inventa exports.

## 8. Parser, AST, catálogo y HIR

### 8.1 Parser y AST

La forma correcta es la que el AST de compiler-next ya anticipa:

```text
ParsedAst.package: Option<AstPackage>
```

`None` significa ausencia source y se conserva. `Some` contiene path no vacío y
span completo. No hay `FakePackageDecl`, span sintético ni fixup `None -> main`.
El AST dump muestra la variante/ausencia real.

### 8.2 Catálogo y source provider

La inspección ligera de headers debe distinguir al menos:

```text
ValidNamedHeader(path)
AbsentHeader
MalformedOrMisplacedPackage
```

`Option<Vec<String>>` no basta como resultado definitivo porque confunde
ausencia válida con cabecera mal formada. El entry siempre se parsea y se agrega
por locator. Si resulta anonymous, se asigna la variante interna y luego se
procesan sus imports named. Los demás candidatos sólo se cargan como
contribuciones de packages named alcanzados.

El catálogo valida como invariante global `anonymous_source_units <= 1`. No
registra anonymous en `PackageIndex` por path ni crea representatives de
prefixes para él.

### 8.3 Resolver y HIR

`PackageKey`, `SourceUnitKey`, `SymbolKey`, `ModuleInfo` y todo metadata nominal
deben portar la variante discriminada. En particular:

- `collect_signatures` in-memory deja de normalizar `None` a `PackagePath([main])`;
- collection de declarations indexa por `PackageId` y por ello funciona para
  anonymous sin abrir un namespace;
- maps `package path -> representative ModuleId` excluyen anonymous;
- resolución de imports sólo construye targets `Named`;
- tipos nominales declarados en anonymous conservan `ModuleId`/`PackageId` y no
  se vuelven estructurales;
- HIR y los IR posteriores retienen las identities resueltas existentes; no
  necesitan volver a consultar un spelling source;
- verificadores rechazan un import target anonymous, más de una unidad bajo la
  identity V1 o un package path vacío.

Campos bootstrap como `ModuleInfo.name: String` no deben alojar una etiqueta
falsa con significado semántico. Deben sustituirse por identity discriminada o
por metadata de display separada. Diagnostics de provenance siguen usando
`source_name`/`LogicalSourceKey`.

## 9. Source root, paths y CWD

Para el CLI V1 el source root continúa siendo el directorio contenedor del
entry, pero se obtiene del **entry canónico ya resuelto**, no de su spelling
crudo. El orden conceptual es:

```text
CLI locator
  -> resolver/canonicalizar el archivo entry
  -> source root = parent canónico del entry
  -> LogicalSourceKey = path normalizado relativo a ese root
  -> parsear identidad declarada o Anonymous
```

Si `main.ae`, `./main.ae` y `/abs/path/main.ae` seleccionan el mismo archivo,
producen el mismo root, logical key, package identity y source graph. Un path
relativo necesita naturalmente el CWD para seleccionar un archivo, pero una
vez seleccionado el CWD no entra en identidad, resolución, mangling ni
diagnostics canónicos.

No se deduce ningún package de `examples/word_stats/main.ae`, del nombre
`main.ae` ni de la estructura de directorios. Cambiar entre named y anonymous
sólo depende del contenido del source. Las reglas existentes del provider para
orden determinista, paths relativos, duplicados y symlinks ambiguos se
conservan.

## 10. Diagnostics

La ausencia válida deja de emitir:

```text
source unit requires `package <path>;` as its first item
```

El código bootstrap asociado a esa obligación queda retirado para este uso; no
debe reciclarse silenciosamente si ya existe en otra categoría histórica. Los
diagnostics normativos son:

| Situación | Fase/categoría | Mensaje requerido |
|---|---|---|
| `package` después de import o declaración, sin package inicial | parse/syntax | ``package declaration must be the first non-trivia item`` |
| segundo `package` tras uno inicial | parse/syntax | ``source unit contains more than one package declaration`` |
| proveedor agrega dos units anonymous | catalog/semantic graph | ``V1 permits only one source unit without a package declaration per source graph``; mostrar ambos source names |
| import escrito sin target named existente | semantic/name | ruta de package inexistente existente |
| import interno dirigido a Anonymous | catalog/internal graph validation | target no importable; nunca convertirlo a un path |
| package de proyecto bajo `std` | semantic/name | diagnóstico reservado existente |

El span principal de package misplaced/duplicate cubre el keyword o la segunda
declaración completa cuando esté disponible. El diagnóstico de cardinalidad
incluye el source actual y la primera unidad anónima; no propone inventar
`package main;` automáticamente. Tooling puede sugerir declarar packages named
distintos para composición multi-file.

No hay diagnóstico especial para `import default;` o `import anonymous;`: son
paths named ordinarios. Tampoco se diagnostican archivos anónimos meramente
presentes pero no alcanzados bajo el source root, igual que otros candidates no
incluidos en el grafo.

## 11. Casos cerrados

| Caso | Decisión |
|---|---|
| 1. `int main() { return 0; }` | válido; entry en anonymous package |
| 2. anonymous con `import std.Text` | válido; import named normal |
| 3. `package Examples.WordStats;` | válido y sin cambio semántico |
| 4. varios archivos del mismo named package | válido; tabla package-wide existente |
| 5. varios archivos sin package | no admitidos en un mismo grafo V1; sólo el entry explícito entra por proximidad |
| 6. mezcla anonymous/named | válida con anonymous entry e imports salientes named; nunca edge entrante |
| 7. importar anonymous | imposible por sintaxis/índice; todo spelling intenta un named package |
| 8. package no inicial | error parse específico |
| 9. package duplicado | error parse específico |

## 12. Primer vertical de implementación

Se recomienda **PACKAGE-ERGONOMICS-V1 — single-unit anonymous entry** con este
orden y frontera:

1. introducir `PackageKey::Named`/`Anonymous` y hacer que `PackagePath` sea
   exclusivamente named; adaptar dumps y verificadores antes de aceptar syntax;
2. eliminar la normalización in-memory `None -> package main` y separar metadata
   semántica de strings de display;
3. hacer que discovery agregue el entry anonymous directamente, conserve la
   discovery named de sus imports y valide cardinalidad uno;
4. retirar el error de package ausente y agregar diagnostics explícitos para
   misplaced/duplicate package;
5. excluir anonymous de namespace/prefix/import maps, manteniendo collection de
   members por `PackageId`;
6. agregar el discriminante anonymous al mangler sin alterar símbolos named ni
   el wrapper `main`;
7. probar parser, AST/HIR/LLVM dumps, ejecución O0/O2, imports de proyecto y
   `std`, entrypoint, invalid graphs y las tres formas equivalentes del path;
8. ejecutar toda la suite compiler-next y pruebas de no cambio byte-for-byte de
   identities/mangling named; no tocar legacy.

El vertical debe incluir al menos los nueve casos de la sección 11, un archivo
`package anonymous;` que pruebe ausencia de colisión, un named entry junto a un
archivo anonymous no alcanzado, dos anonymous units inyectadas mediante un
fixture de catálogo y corrupciones que intenten un `ResolvedImport` anonymous o
un `PackagePath` vacío.

## 13. Decisiones abiertas y fuera de scope

No quedan abiertas reglas source necesarias para este milestone. Permanecen
deliberadamente para otros milestones:

- si un manifest o lista explícita permitirá varias contribuciones al anonymous
  package y cuál será su unidad incremental;
- si el anonymous package podrá producir alguna vez artifacts exportables o
  separate compilation; V1 dice no;
- formato final de manifest/source roots y cache keys cross-session;
- visibilidad/linkage final de helpers no-entry;
- números exactos de los nuevos diagnostics, que deben auditar primero el
  registro actual y no reutilizar códigos ocupados;
- wildcard, relative/selective imports, re-exports y package inference;
- statements top-level, otro contrato de entrypoint o script mode;
- cualquier cambio de ABI named, std reservation, runtime o compiler legacy.

Estas aperturas no permiten a una implementación V1 fusionar unidades por
directorio, publicar anonymous, inventar un nombre o relajar packages named.
