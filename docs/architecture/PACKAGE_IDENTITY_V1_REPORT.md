# PACKAGE-IDENTITY-V1 — reporte de implementación

Estado: **IMPLEMENTADO Y CALIFICADO**, 2026-09-26.

Autoridad normativa:
[PACKAGE-MANAGER-ARCH-1](PACKAGE_MANAGER_ARCH_1.md) y
[PACKAGE-MANAGER-ARCH-1 report](PACKAGE_MANAGER_ARCH_1_REPORT.md).

Este vertical implementa identidad nominal de instancias, grafo multi-root y
dependencias de path. No implementa lockfile, resolución de registry, red,
cache CAS ni comandos de administración de dependencias.

## Resultado

La compilación de proyecto ya no identifica todo package no-toolchain como
`OriginKey::Project`. Cada nodo resuelto posee una identidad estructural exacta,
sus propios sources y su tabla de dependencias directas. La misma raíz de import
puede seleccionar instancias distintas según el package que posee el source:

```text
App -> A -> math 1.5.0
    -> B -> math 2.1.0
```

Dentro de `A`, `import math` apunta a la primera instancia; dentro de `B`, al
segundo `math`. El source no escribe versiones. Los IDs densos siguen siendo
locales a la sesión, pero se internan desde claves que contienen la instancia
exacta y el path lógico, por lo que ambas versiones conservan tipos, símbolos y
mangling separados.

El modo standalone conserva la ruta anterior: `aether run file.ae` no lee ni
adopta manifests vecinos y continúa usando el catálogo standalone explícito.

## Identidad de instancia

La forma implementada es:

```text
PackageInstanceKey = Root {
    manifest,
    name,
    version,
}
                   | Path {
    manifest,
    name,
    version,
}
                   | Registry {
    registry,
    name,
    version,
    checksum,
}
```

`manifest` es el spelling UTF-8 del manifest canónico de la sesión. `name` y
`version` provienen de metadata validada; la versión pasa por `semver::Version`.
`Root` distingue el package raíz de una instancia obtenida mediante un edge de
path. `Path` usa el manifest canónico para deduplicación e identidad material de
sesión.

`Registry` deja preparada la identidad futura exigida por la arquitectura, pero
PACKAGE-IDENTITY-V1 no construye esa variante. Su presencia no implica solver,
descarga, checksum verification ni soporte de registry disponible.

`PackageId(u32)` permanece como entero denso de sesión. Las claves internadas
son `PackageKey`, cuya parte named ahora combina identidad de origen exacta y
`PackagePath`; por tanto no se interna sólo por spelling.

## `OriginKey` y `PackageKey`

`OriginKey` queda cerrado como:

```text
Project                         # catálogo standalone legacy
Toolchain                       # std
Package(PackageInstanceKey)     # proyecto resuelto multi-root
```

`PackageKey` conserva sus dos formas:

```text
Named { origin, path }
Anonymous
```

En una compilación de proyecto, un package named usa
`OriginKey::Package(instance)`; `PackagePath` conserva la ruta lógica declarada,
incluidos descendants. Así, dos claves con path lógico `math` son distintas si
sus `PackageInstanceKey` difieren. `Anonymous` sigue disponible únicamente para
el entry técnico permitido; no puede convertirse en target de import.

`std` continúa usando `Toolchain`, sin identidad de registry ni edge de
manifest. `Project` se conserva exclusivamente para no cambiar la semántica
standalone existente.

## Grafo resuelto y frontera del compiler

`ProjectPlan` se extendió con:

```text
root_instance: PackageInstanceKey
packages: Map<PackageInstanceKey, ResolvedPackage>
```

Cada `ResolvedPackage` contiene:

```text
instance
canonical root
canonical direct manifest
validated package metadata
selected source entry
application/library kind
dependency import name -> exact PackageInstanceKey
```

La tabla de edges pertenece al owner. `ProjectPlan::resolved` revalida que:

- exista el nodo raíz;
- la key del mapa coincida con la identidad del nodo;
- manifest canónico, name y version coincidan con la identidad;
- cada edge tenga target presente;
- la key del edge coincida con el `package.name` del target;
- el grafo sea acíclico.

La CLI resuelve TOML y paths y entrega esta forma tipada al driver. Frontend,
HIR, MIR, SSA y backend no leen TOML, locators de dependencias ni conceptos de
registry. Reciben identidad, owner, catálogo y edges ya resueltos.

## Source discovery multi-root

La ruta de proyecto usa `discover_catalog_with_plan` en lugar de derivar todo el
catálogo desde un único entry. Para cada `ResolvedPackage` obtiene su provider
root seleccionado, enumera sus `.ae` y adjunta a cada candidato el
`PackageInstanceKey` owner y el nombre esperado del package.

Durante parseo:

- cada source named recibe `OriginKey::Package(owner)`;
- su declaración `package` debe estar bajo el `package.name` del owner;
- un source de otra raíz no puede contribuir accidentalmente al namespace del
  owner;
- sólo el entry raíz puede permanecer anonymous;
- sources `std` de proyecto siguen prohibidos;
- los módulos toolchain requeridos se incorporan después con origen
  `Toolchain`.

El catálogo resultante puede contener varias contribuciones con el mismo
spelling visible siempre que pertenezcan a instancias distintas. Las tablas de
package y los `PackageId` se construyen desde las claves exactas.

La función pública de discovery standalone no recibe un plan y conserva el
escaneo y resolución previos. Un manifest vecino, válido o inválido, no afecta
un target archivo.

## Resolución contextual de imports

La resolución de un import no-`std` consulta primero el owner del source actual.
Para un import cuyo primer segmento es `math`:

```text
(owner instance, "math") -> exact target instance
```

El target completo se forma con esa instancia y el `PackagePath` escrito por el
source. Esto mantiene `import math.Dense` dentro de la misma instancia elegida
para `math`; no se vuelve a seleccionar globalmente por spelling.

Un package también puede importar su propio root sin un edge externo. Todo otro
root debe aparecer en la tabla de dependencias directas del owner. Si existe en
el grafo sólo por transitividad, se emite `E0242` indicando que el package no
declara esa dependencia directa.

Por ejemplo, con `App -> A -> hidden`, un `import hidden` en `App` falla aunque
el nodo `hidden` ya esté materializado para `A`. La presencia global de un nodo
no concede visibilidad.

`std` conserva su resolución especial a `Toolchain`, y las reglas existentes de
imports concretos, aliases, descendants y grants permanecen activas.

## Multiversión, nominalidad y mangling

La separación de instancia llega a la identidad usada por módulos, símbolos y
declaraciones. Structs, enums, classes, interfaces, funciones y sus instancias
genéricas continúan usando IDs densos internos, pero esos IDs se recolectan
desde módulos cuyos packages ya contienen el `PackageInstanceKey` exacto.

La regresión de multiversión compila dos libraries llamadas exactamente `math`,
con versiones y manifests distintos, y ambas declaran un nominal `Record` con
el mismo spelling y layout. `A` opera con `math@1`; `B`, con `math@2`. El grafo
positivo compila y ejecuta correctamente.

Una segunda regresión intenta entregar `math@1::Record` a una función que exige
`math@2::Record`. El frontend lo rechaza por mismatch nominal; no se agregó
coerción ni equivalencia estructural.

El mangling de funciones e instancias genéricas dejó de depender sólo de
`display_name`. Para packages resueltos incorpora la forma canónica de
`PackageInstanceKey` y el `PackagePath` lógico. El mangling recursivo de tipos
nominales concretos usa esa misma identidad de módulo, evitando colisiones aun
cuando name, source spelling y layout sean iguales. Standalone y toolchain
conservan sus spellings bootstrap previos.

## Dependencias de path

La forma existente del manifest está habilitada:

```toml
[dependencies]
localLibrary = { path = "../localLibrary" }
```

El resolver implementado aplica estas reglas:

- resuelve el locator respecto del directorio del manifest que declara el edge;
- canonicaliza el directorio y exige un `aether.toml` regular directo;
- parsea cada manifest transitivo con schema fail-closed;
- valida `package.name`, `package.version` SemVer y compatibilidad Aether;
- exige igualdad exacta entre dependency key y `package.name`;
- procesa recursivamente path dependencies del target;
- exige que una dependencia de path sea library con `src/lib.ae`;
- no busca manifests en ancestors ni descendants;
- no prueba registry como fallback;
- deduplica por manifest canónico;
- conserva un solo target exacto por import root y owner.

El root mantiene la clasificación application/library ya existente. No se crea
ni consulta `aether.lock`; cada invocación resuelve directamente los manifests
de path actuales.

## Cycles, canonicalización y symlinks

`PathResolver` mantiene un stack ordenado de manifests canónicos. Reencontrar
un manifest activo produce un diagnóstico determinista con la cadena de nombres,
por ejemplo:

```text
path dependency cycle: app -> a -> app
```

La comprobación ocurre después de canonicalizar, por lo que spellings como
`../app/./` no evitan el ciclo. `ProjectPlan::resolved` repite una validación de
DAG sobre los edges exactos como defensa de frontera para callers distintos de
la CLI.

El índice `by_manifest` comparte un nodo ya resuelto cuando dos edges alcanzan
el mismo manifest canónico. Esto cubre diamonds, segmentos redundantes y aliases
de filesystem. En plataformas Unix existe una regresión donde una rama usa el
directorio real y otra un symlink; ambas convergen en una sola instancia de
package.

## Registry rechazado temporalmente

La forma string continúa parseándose para mantener el schema normativo:

```toml
[dependencies]
foo = "1.2"
```

Un constraint vacío conserva su diagnóstico específico. Todo valor registry no
vacío falla explícitamente con:

```text
registry dependency `foo` cannot be resolved: registry resolution is not implemented
```

No se ignora el edge, no se consulta red y no se reinterpreta como path. La
variante `PackageInstanceKey::Registry` queda reservada hasta que exista una
resolución material verificada.

## Calificación

La suite de CLI agregó cobertura real para:

- root con dependencia de path y ejecución;
- path dependency transitiva;
- diamond dependency;
- mismo path exacto compartido;
- canonicalización con segmentos redundantes;
- identidad canónica mediante symlink;
- dos versiones del mismo `package.name` coexistiendo;
- tipo nominal con igual nombre/layout en ambas versiones;
- rechazo de mezcla nominal cross-version;
- mismatch entre dependency key y `package.name`;
- manifest directo ausente;
- cycle con spellings distintos del mismo manifest;
- rechazo de import transitivo no declarado;
- rechazo explícito de dependencia registry;
- preservación de standalone frente a manifests vecinos.

Se ejecutaron los gates:

```text
cargo test --workspace
cargo clippy --workspace --all-targets -- -D warnings
cargo fmt --all --check
git diff --check
bash compiler-next/tests/run-differential.sh
```

El workspace completo pasó. La suite de CLI quedó en 19 tests verdes. El
diferencial standalone comprobó 21 casos con cero fallos, preservando los casos
equivalentes, rechazos y cambios intencionales ya registrados.

## Deuda restante para PACKAGE-MANAGER-V1

Este vertical establece la identidad y topología que las capas futuras deben
reproducir, pero deja fuera deliberadamente:

1. `aether.lock`, su schema, lectura, escritura atómica, orden canónico y paths
   relativos portables. Los paths absolutos canónicos actuales son identidad de
   sesión y no un formato persistente.
2. Solver de requirements registry, selección SemVer edge-local, yanked state y
   snapshots deterministas de metadata.
3. Materialización de `PackageInstanceKey::Registry`, checksums SHA-256,
   downloads, extracción segura y cache CAS global.
4. Red, protocolo, credenciales, registry oficial y política offline.
5. Comandos `add`, `remove`, `sync`, `update`, `install`, `uninstall` y
   `publish`, incluidas mutaciones transaccionales manifest+lock.
6. Fingerprinting persistente de contents para path packages y artefactos. La
   identidad nominal ya está separada, pero este vertical no introduce una
   cache de compilación/package manager.
7. Producción del mismo `ProjectPlan` desde un lock futuro. Esa capa deberá
   conservar exactamente nodes, identities y edges por owner sin filtrar TOML,
   registry locators ni policy hacia el compiler.

La futura resolución de registry no puede volver a una selección global por
nombre ni debilitar los edges directos. Un lock o cache nuevos deben producir el
mismo grafo contextual y la misma separación nominal demostrada por este
vertical.
