# PACKAGE-ERGONOMICS-ARCH-1 — reporte

Estado: **ARQUITECTURA CERRADA; SIN IMPLEMENTACIÓN**, 2026-09-15.

Documento normativo:
[PACKAGE_ERGONOMICS_ARCH_1](PACKAGE_ERGONOMICS_ARCH_1.md).

## Resultado

Se cerró la semántica de `package` opcional para compiler-next sin admitir aún
la feature ni modificar código.

- Una unidad puede omitir `package`; el AST conserva `None` y semántica le
  asigna una identidad nominal `Anonymous`, no un `AstPackage` falso.
- `PackageKey` debe ser una suma `Named`/`Anonymous`. `PackagePath` permanece no
  vacío y exclusivo de named; no se usan `main`, `default`, `root`, `anonymous`
  ni el vector vacío como identidad encubierta.
- Anonymous no tiene spelling importable, no aparece en el namespace index, no
  tiene children y no colisiona con ningún package nombrado.
- Un entry anonymous puede importar proyecto y `std` normalmente. La mezcla es
  unidireccional: anonymous puede depender de named, pero named nunca puede
  importar ni descubrir anonymous.
- V1 admite una sola source unit anónima por grafo. Otros `.ae` sin package
  presentes bajo el root no se agregan por vecindad; un proveedor que intente
  agregar dos falla antes de collection.
- Packages nombrados parciales y multi-file conservan sus reglas completas.
- `main` se sigue buscando en el `ModuleId` entry y conserva wrapper/ABI. El
  mangling named no cambia; símbolos anonymous nuevos reciben un discriminante
  estructural imposible de confundir con un identifier source.
- El root parte del entry canónico y su logical key es relativo. Los spellings
  `main.ae`, `./main.ae` y absoluto son equivalentes cuando seleccionan el mismo
  archivo; jamás se infiere package del path.
- Package misplaced y duplicate reciben diagnostics parse específicos. La
  ausencia deja de producir la exigencia actual de `package <path>;`.

## Política multi-file elegida

Se descartó fusionar automáticamente todas las unidades sin package del source
root. El catálogo actual expresa composición mediante identities named e
imports, mientras que el anonymous package no tiene un target que pueda listar
contribuciones. Usar el directorio habría hecho que un archivo no alcanzado
alterase members, duplicados y output del programa.

La frontera V1 es por ello una unidad explícita: el entry. Una ampliación futura
puede aceptar varias unidades sólo si un manifest o lista de inputs las asigna
explícitamente al singleton anonymous; no podrá inferirlo por layout físico.

## Identidad y capas afectadas

```text
source `package A.B;` -> PackageKey::Named(Project, A::B)
source sin package    -> PackageKey::Anonymous(graph-local marker)

PackageKey -> PackageId -> SourceUnitKey / SymbolKey
                         -> ModuleInfo / HIR nominal identities
                         -> verified MIR/SSA -> collision-free mangling
```

Namespace prefixes, imports y `PackagePath::source/canonical` operan sólo sobre
`Named`. Collection package-wide puede seguir indexando por `PackageId`, también
para anonymous. Diagnostics y dumps muestran el discriminante y source
provenance por separado, nunca una etiqueta string con valor semántico.

## Evidencia del compiler actual

La inspección confirmó que compiler-next ya usa
`ParsedAst.package: Option<AstPackage>` y el parser ya puede construir `None`.
La obligación se reintroduce en discovery mediante el error E0230 y
`explicit_project_package`. A su vez, el helper in-memory `collect_signatures`
normaliza hoy la ausencia a `PackagePath(["main"])`.

El catálogo, `PackageKey`, prefix construction, representatives,
`ModuleInfo.name`, `SymbolKey` y maps de resolución presuponen un path named.
Ésa es la razón de exigir un refactor nominal, en vez de aceptar simplemente un
vector vacío. La collection global ya agrupa por `PackageId`, y la selección de
entry ya parte de `ParsedProgram.entry`; ambas piezas encajan limpiamente con la
variante anonymous.

Discovery toma hoy el directorio contenedor del spelling recibido antes de
canonicalizar por completo el entry. El vertical deberá invertir ese detalle
para que paths relativos equivalentes produzcan root y logical identity
idénticos.

## Primer vertical recomendado

**PACKAGE-ERGONOMICS-V1 — single-unit anonymous entry** debe:

- introducir identities discriminadas y verificadores fail-closed;
- preservar `None` de AST a catálogo/HIR;
- cargar el entry anonymous directamente y sólo packages named por imports;
- prohibir más de una unidad anonymous en el grafo;
- retirar el error de ausencia y diagnosticar misplaced/duplicate package;
- mantener anonymous fuera de namespaces/import targets;
- dar mangling no colisionante a symbols anonymous sin cambiar named ni `main`;
- cubrir los nueve casos normativos, paths equivalentes, dumps, corrupciones,
  O0/O2 y regresión completa de compiler-next.

No debe agregar composición anonymous multi-file, package inference, manifest
nuevo, script mode, imports nuevos, exports anonymous, cambios ABI named ni
cambios en legacy.

## Validación de este milestone

- Se crearon únicamente el documento normativo y este reporte.
- No se modificó parser, resolver, catálogo, HIR, MIR, SSA, backend, runtime,
  STD, tests, CLI ni compiler legacy.
- Se preservaron los cambios preexistentes del working tree.
- Sintaxis, anonymous semantics, source graph, multi-file, imports, entrypoint,
  canonical identity, AST/HIR, diagnostics, path behavior y primer vertical
  quedan cerrados.
- Las únicas decisiones abiertas corresponden a milestones posteriores y no
  permiten inferencia accidental desde el filesystem.
