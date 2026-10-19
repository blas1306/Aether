# CLASS-BUFFER-FIELDS-ARCH-1 — reporte de cierre

Estado: **COMPLETADO COMO ARQUITECTURA; SIN IMPLEMENTACIÓN**, 2026-10-19.

Documento normativo:
[CLASS-BUFFER-FIELDS-ARCH-1](CLASS_BUFFER_FIELDS_ARCH_1.md).

## Resultado

Se cerró la generalización de fields privados `Buffer<E>` sin allowlist. La
admisión debe reutilizar el predicado ordinario vigente de Buffer y las
restricciones ortogonales de class storage. `int` deja de tener privilegio
semántico, pero el milestone no amplía qué elements puede almacenar Buffer.

La regla actual no es `E: Storable`. Buffer todavía exige element concreto,
Copy, no-drop y sin subestructura borrowed/owning. Por eso entran scalars,
structs Copy, enums Copy con o sin payload, nested Copy structs e instancias
nominales concretas; quedan fuera owners, class handles, string, refs/views,
tipos con Drop y parameters simbólicos.

## Hallazgos de auditoría

- La excepción literal a `int` existe tanto en resolución HIR como en
  `verify_class_metadata`; ambas deben usar una autoridad central.
- Layout, HIR FieldWrite, MIR, SSA y LLVM ya preservan el `TypeId` concreto y
  son genéricos para init, replacement y drop.
- El descriptor de todo `Buffer<E>` es pointer + length, inline en el objeto;
  sólo el backing es otra allocation.
- El drop vigente de Buffer libera el backing y no destruye elements. Esta es
  la razón técnica para no sustituir la regla por Storable.
- El Place vigente no representa class fields. Quitar los dos checks a `int`
  permitiría almacenar nuevos Buffers, pero no acceder correctamente a sus
  elements.

## Decisiones cerradas

| Área | Decisión |
|---|---|
| visibility | sólo private; public sigue rechazado; protected/internal member no existen |
| init | definite initialization por FieldId; zero-length es owner inicializado |
| transfer | local/fresh Buffer se mueve una vez al field |
| replacement | evaluar RHS, instalar nuevo owner, destruir anterior una vez |
| self/alias | no guard runtime; owning field read y `field = field` siguen fuera |
| final drop | reverse field order, derived antes de base, backing una vez, object free una vez |
| partial unwind | cleanup de subsecuencia inicializada mediante ConstructorUnwindPlan |
| layout | mismo `{ptr,usize}` que un local; sin boxing ni allocation por descriptor |
| generics | class genérica fuera; concrete aggregate instantiation dentro si satisface Buffer |
| indexed access | class-field storage place efímero, projections/bounds ordinarios, sin owner copy |
| borrows | `ref/ref mut` del field o element y View/ViewMut siguen fuera por aliases mutables |
| move-out | extracción, return, field-to-field y partial moves siguen fuera |
| backend | concrete post-monomorphization; sin runtime por T ni símbolos graphics |

El acceso indexado inmediato permite a un método leer o escribir elements Copy
y copiar prefijos para growth. No crea una referencia source-visible. Esto
cierra el uso necesario de arenas sin abrir el problema general de interior
borrows de objects ARC: un keepalive de objeto no mantendría vivo un backing
reemplazado por otro alias.

## Qualification futura

Se diseñó `class_buffer_fields_v1.rs` como fixture dedicado con:

- todos los element kinds positivos requeridos;
- negativos de visibility, storage, Drop, symbolic generics, borrows y moves;
- definite init, zero length, replacement y múltiples replacements;
- exception antes/después de init y durante RHS de replacement;
- class alias + final release e inheritance drop order;
- corruption tests HIR/MIR/SSA;
- inspección de descriptor/drop glue LLVM;
- conteos exactos de allocations/frees/drops en O0 y O2;
- gates de Buffer, aggregates, storage, collections, álgebra, OOP y exceptions.

GRAPHICS-FOUNDATION-V1 permanece bloqueado hasta que exista una implementación
qualified de esta arquitectura. Point, Command, PathVerb y TextRecord serán
dogfood nominal; no aparecerán en el compiler ni runtime.

## Cambios realizados

Sólo se agregaron este reporte y el documento de arquitectura. No se modificó
frontend, HIR, MIR, SSA, LLVM, runtime, tests ni packages source.
