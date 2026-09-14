# MODULE-STD-ARCH-1 — reporte

Estado: **ARQUITECTURA CERRADA; SIN IMPLEMENTACIÓN**, 2026-09-13.

Documento normativo: [MODULE_STD_ARCH_1](MODULE_STD_ARCH_1.md).

## Resultado

Se cerró el modelo de packages, source units, imports, aliases y capas de
biblioteca sin cambiar compiler-next ni el lenguaje actualmente admitido.

- `package A.B;` define el namespace lógico del source. Varios archivos pueden
  contribuir al mismo package y los packages contienen members directamente.
- Source module/source unit continúa siendo la unidad de parsing, imports,
  provenance, implementación y dependencia. No es el namespace público.
- `PackageKey`, `SourceUnitKey` y `DeclKey` son claves lógicas; `PackageId`,
  `ModuleId` y `SymbolId` son internados densos de sesión. Paths absolutos y
  discovery order nunca son identidad.
- Los members de todas las contribuciones forman una tabla única. Duplicados y
  colisión member/child son errores; ningún archivo gana por orden.
- `import A.B` habilita `A.B.x`, no `x` ni `B.x`. También habilita descendientes
  como `A.B.C.x`, con lookup lazy.
- `import A.B as q` crea sólo el binding local `q`; HIR conserva la identidad
  canónica. Puede aliasarse un namespace completo.
- Imports exactos repetidos, aliases duplicados y conflicts alias/local son
  errores. Roots compatibles de imports sin alias pueden compartir spelling.
- El grafo separa grants de lookup, dependencies por symbols resueltos y
  reachability de link. Un import o subtree sin uso no fuerza codegen/link.
- `std` es raíz reservada de toolchain, no suplantable. `import std;` es inválido
  y no hay acortamiento automático de paths.
- `import Text` migra exclusivamente a `import std.Text`; un alias explícito es
  `import std.Text as text`. No se conservan ambos spellings.

## Fronteras de funcionalidad

| Capa | Decisión |
|---|---|
| Lenguaje | tipos/semántica que el compiler debe preservar: scalars, `string`, refs, aggregates/OOP/generics, exceptions, `Array`, Vector/Matrix, operators, conversions y package/import |
| Core/prelude | lista pequeña y versionada sin import: `print`/`println`, `byteLength`, matemática escalar básica y `List<T>` como dirección inicial |
| STD explícita | `std.Text`, IO/File, LinearAlgebra/Statistics, Collections, Random, Time y demás dominios/policies |
| Runtime privado | layout, allocation, ARC, UTF-8 backing, EH, libc/syscalls y primitives privilegiadas; no es importable ni vive bajo `std` |

Prelude no importa stdlib, no abre namespaces, no obliga a linkear código no
usado y no convierte cada API en intrinsic u opcode.

## Evidencia y compatibilidad

La decisión respeta el charter, contrato semántico y arquitectura por fases;
mantiene la separación `SourceId`/`ModuleId`, collection global antes de bodies,
nominal identity y resolución calificada ya probadas en compiler-next. Sustituye
su mapping temporal `import name -> <entry>/name.ae` y su módulo único por
archivo, que permanecen evidencia bootstrap.

El sistema legacy confirma utilidad de aliases locales e identities canónicas,
pero sus imports selectivos, búsqueda por path y `ModuleId` string no se elevan
a contrato. TEXT-V1 confirma la raíz estándar read-only y reachability de
helpers; su spelling provisional `Text` queda deliberadamente reemplazado.

## Siguiente vertical

Se recomienda **MODULE-STD-V1 — package and hierarchical import spine**:
parser mínimo, catálogo/source provider determinista, packages parciales,
identidades separadas, lookup jerárquico/aliases, grafos por uso, raíz `std` y
migración de TEXT-V1 a `std.Text` en la misma ruta nativa.

Quedan fuera de ese vertical stdlib/runtime nuevos, wildcard/selective imports,
re-exports, registry/dependency manager, manifest final, visibilidad compleja,
module initialization, separate compilation y ABI pública de packages.

## Validación de este milestone

- Se crearon únicamente los dos documentos solicitados.
- No se modificó parser, resolver, HIR/MIR/SSA, stdlib, runtime, tests ni CLI.
- Las decisiones abiertas posteriores están enumeradas y no se resolvieron por
  inferencia accidental del filesystem o del bootstrap existente.
