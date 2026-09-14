# MODULE-STD-V1 — package and hierarchical import spine

Estado: **IMPLEMENTADO Y CALIFICADO**, 2026-09-14, para `compiler-next`, bajo
el contrato de [MODULE-STD-ARCH-1](MODULE_STD_ARCH_1.md).

## Modelo de package y source unit

Cada source unit de proyecto que participa en una compilación declara primero
`package A.B;`. La declaración fija su namespace lógico; el path físico sólo
conserva provenance. El source provider toma como root mínimo el directorio de
la entrada, recorre `.ae` de forma ordenada y construye nombres lógicos relativos
con separador `/`. Symlinks se rechazan por ambiguos.

`PackageKey { origin, path }` es la identidad estable del package:
`OriginKey::Project` separa código de usuario de `OriginKey::Toolchain`.
`SourceUnitKey { package, logical_source }` identifica una contribución física
sin convertirla en namespace. `SymbolKey { package, member }` identifica una
declaración independientemente del alias con que se alcanzó. `PackageId`,
`ModuleId`, `SourceId` y los IDs nominales continúan siendo índices densos de la
sesión y nunca sustituyen a las claves lógicas.

## Contribución multiarchivo

Todos los source units con el mismo `PackageKey` contribuyen a una única tabla
de miembros. El frontend crea nominales y colecta firmas de todo el package
antes de analizar bodies, de modo que las referencias forward entre archivos y
los ciclos declarativos admitidos no dependen del orden de discovery.

Un nombre repetido entre contribuciones produce `E0240` con provenance de ambos
archivos. También se rechaza `P.X` cuando `P` ya contiene un miembro `X`
(`E0236`). Las tablas de aliases, structs, enums y funciones se comparten entre
todas las unidades del package, pero imports, spans y dependencias siguen siendo
propiedad del source unit.

## Catálogo, lookup e imports

El catálogo se arma determinísticamente con `BTreeMap`/`BTreeSet`, paths lógicos
y claves ordenadas. Incluye nodos prefijo aunque no tengan declaraciones; por
eso importar una rama habilita sus descendientes existentes. El source provider
carga una rama de proyecto una sola vez aunque varios imports compartan el mismo
destino.

`import A.B;` es un grant de lookup, no un `using`: habilita `A.B.member` y los
paths calificados de sus descendientes, pero nunca publica `member` sin
calificación ni autoriza siblings. `import A.B as branch;` crea solamente el
binding local `branch`; tanto aliases de rama como de hoja terminan en el mismo
`ModuleId`/`SymbolKey` canónico. Imports repetidos, destinos canónicos repetidos,
bindings duplicados y colisiones alias/member/parameter/local fallan antes de
bajar IR.

Tras resolver bodies, HIR elimina los spellings y aliases de sus `ModuleInfo`.
HIR, MIR, SSA y backend conservan únicamente identidades canónicas densas más
las claves lógicas de metadata; ninguna fase reinterpreta source paths.

## Raíz estándar

`std` es una raíz reservada con origen `Toolchain`. Cualquier archivo de
proyecto que declare `package std;` o `package std.X;` se rechaza con `E0231`,
incluso si existe un archivo de usuario llamado `Text.ae`. `import std;` se
rechaza con `E0233`; sólo se importan ramas concretas.

El catálogo bootstrap materializa los nodos sin API `std.Math` y
`std.Math.LinearAlgebra` requeridos por el spine, además del package existente
`std.Text` cuando la rama correspondiente es alcanzable. Esto no agrega
funciones, tipos públicos, runtime ni prelude.

## Grants, dependencias y reachability

Hay tres relaciones separadas:

1. los imports del source unit conceden lookup durante resolución;
2. las referencias efectivamente resueltas forman
   `ModuleInfo.semantic_dependencies`;
3. el cierre de llamadas desde `main` forma la reachability de link/codegen.

Por lo tanto un import no usado puede descubrir y verificar una rama, pero no
emite sus funciones ni la convierte en dependencia semántica. Una dependencia
compartida conserva un único source/catalog node. Los helpers privados de Text
siguen seleccionándose exclusivamente por `TextOp` alcanzables.

## Migración de Text

TEXT-V1 se usa únicamente como:

```aether
import std.Text;
std.Text.contains(value, needle);
```

o con alias local:

```aether
import std.Text as text;
text.contains(value, needle);
```

`import Text;` ya no se acepta: produce `E0232` y un fix-it estructurado que
reemplaza la declaración por `import std.Text;`. Los nominales, operaciones HIR
y helpers LLVM de TEXT-V1 son los anteriores; sólo cambió su package canónico a
`Toolchain::std::Text`. Aliases distintos y la forma completa producen el mismo
target canónico.

## Diagnósticos

Además de los diagnósticos anteriores del lenguaje, este vertical fija:

- `E0220`: import, target o binding duplicado/inválido;
- `E0221`: path de package inexistente o namespace desconocido;
- `E0223`: package conocido pero no importado;
- `E0230`: source unit de entrada sin declaración package;
- `E0231`: declaración de proyecto bajo la raíz reservada `std`;
- `E0232`: spelling legado `import Text`, con fix-it;
- `E0233`: import inválido de la raíz desnuda `std`;
- `E0234`: uso de `std` como alias;
- `E0235`: colisión entre binding de namespace y nombre local/declarado;
- `E0236`: colisión member/package-child;
- `E0240`: miembro duplicado entre contribuciones de package.

Todos retienen `SourceId`, span y nombre lógico de source cuando corresponde.

## Determinismo, qualification y corrupciones

La suite `module_std_v1.rs` cubre contribución de dos archivos, forward
cross-file, duplicados y child collisions, lookup descendiente, imports
calificados, aliases de rama/hoja, namespaces no abiertos, sibling no importado,
bindings duplicados, colisiones locales, imports sin reachability, raíz `std`,
shadowing por `Text.ae`, fix-it legado, nodos Math sin API y equivalencia de dumps
HIR/MIR/SSA entre roots absolutos distintos. También demuestra que dos spellings
de alias de `std.Text` desaparecen antes de HIR.

Las suites existentes califican ciclos declarativos, dependencia compartida,
provenance multiarchivo, reachability de helpers Text y corrupciones HIR/MIR/SSA.
`validate_program` falla cerrado ante IDs no densos, `SourceUnitKey` duplicadas,
`SourceId` duplicados e imports cuyo representative no pertenece al subtree
canónico concedido. La qualification completa incluye workspace tests, fmt,
clippy con warnings como errores, whitespace diff y differential nativo.

## Deuda restante

El source root bootstrap sigue siendo explícitamente mínimo: el directorio de la
entrada; todavía no existe manifest ni configuración multi-root. El catálogo
toolchain de este vertical sólo conoce `std.Text` y los nodos organizativos
vacíos Math solicitados. `compile_source` conserva su provider sintético
in-memory para tests unitarios; builds de filesystem exigen package explícito.

Continúan fuera de scope wildcard/selective imports, `using`/open namespace,
re-exports, visibility compleja, inicialización de módulos, registry/dependency
manager, resolución de versiones, separate compilation y ABI pública de
packages. No se agregó ninguna API stdlib, cambio de Core/prelude ni superficie
runtime.
