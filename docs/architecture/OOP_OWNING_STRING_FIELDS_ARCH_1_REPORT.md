# OOP-OWNING-STRING-FIELDS-ARCH-1 — reporte de arquitectura

Estado: **ARQUITECTURA CERRADA; SUPERADO POR EL CIERRE DE IMPLEMENTACIÓN**, 2026-10-31.

El cierre vigente y su evidencia están en
[OOP-OWNING-STRING-FIELDS-V1](OOP_OWNING_STRING_FIELDS_V1_REPORT.md). Este
archivo conserva el resultado histórico del preflight de arquitectura.

Documento normativo:
[OOP-OWNING-STRING-FIELDS-ARCH-1](OOP_OWNING_STRING_FIELDS_ARCH_1.md).

## Resultado

Se diseñó una extensión general para admitir fields cuyo tipo canónico es
exactamente `string` dentro de classes. No se modificó código productivo,
runtime, Graphics, SVG, Plots ni ejemplos. El reproducer de preflight continúa
fallando correctamente con `E0401` hasta una futura implementación.

La decisión principal es mantener separados los dos ARC involucrados. El
handle de class posee la identidad y mantiene viva la allocation del objeto;
cada field string contiene una obligación del runtime string. Aliases de la
class no retienen nuevamente el string. Una lectura del field sí produce un
Alias textual independiente, y su Drop libera sólo esa obligación.

## Decisiones cerradas

- Se admite sólo `string` exacto; no cualquier aggregate que lo contenga.
- El field usa inline el handle string canónico de una palabra, sin boxing,
  tag, bitmap ni ABI nueva.
- Inicializar desde lvalue ejecuta Alias; desde resultado fresco ejecuta
  Transfer. Zeroed memory nunca es un string inicializado.
- Una lectura value es `StringFieldAlias`, no extracción, Move ni Copy load.
- Un borrow para una call se ancla en un owner Alias temporal. El préstamo
  directo del slot interior sigue cerrado porque otro alias de class puede
  reemplazarlo.
- Replacement evalúa/adquiere RHS, publica el handle nuevo y sólo entonces
  libera el anterior. El fallo del RHS conserva el valor viejo.
- Final destruction ejecuta drop string en orden inverso, derived antes que
  base, y una única object free.
- Partial construction reutiliza `ConstructorUnwindPlan` y estado CFG; no usa
  null, sentinel ni bitmap runtime.
- HIR/MIR/SSA conservan owners y operaciones explícitas; LLVM no infiere
  ownership desde pointers.

## Riesgos y mitigaciones

| Riesgo | Decisión/qualification |
|---|---|
| confundir string con class handle por layout/ARC | TypeId, opcodes, ledgers, counters y drop glue separados |
| read como load sin retain | `StringFieldAlias` explícito y corruption test por capa |
| dangling interior borrow tras replacement por alias | owner temporal estabilizador; `&field` directo cerrado |
| leak/double release en init parcial | initialized set + canonical constructor cleanup O0/O2 |
| release viejo antes de publicar nuevo | op indivisible y LLVM store-before-release inspeccionado |
| self replacement del mismo backing | Alias independiente antes del commit, sin pointer guard |
| orden incorrecto con inheritance | receta derived fields, luego base, una object free |
| optimización ARC cambia último release | SSA ownership audit y comparación de eventos O0/O2 |
| admisión accidental de aggregates/containers | predicado positivo de tipo exacto; negativos E0401 |
| instrumentación existente mezcla Buffer y string | contadores separados por subsistema y allocation identity |

## Límites V1

Quedan cerrados interior references source-visible, `ref mut string` de field,
partial moves, `take`/`swap`, default field values, class generics, fields cuyo
tipo contiene string, `Buffer<string>`, Clone estructural, COW/SSO, ARC atómico,
threads y ABI/FFI pública. Nada se infiere de `Storable` o de que el valor mida
un pointer.

La extensión no resuelve ownership de graphs de class ni weak references: un
string no contiene owners de clase y no introduce ciclos. Tampoco amplía el
perfil de class storage para otros tipos owning.

## Qualification plan

La matriz normativa exige casos positivos, negativos y corrupciones en HIR,
MIR y SSA. Los ejecutables corren en O0/O2 y observan separadamente:

- object ARC y object alloc/free;
- string alloc/free/retain/release/literal no-op;
- init, Alias read, borrow temporal y replacements consecutivos;
- base/derived, dispatch y final release por distintos handle types;
- RHS throw, post-commit throw y construcción parcial en base/derived;
- store-before-release y ausencia de paths especiales en LLVM.

Además se mantienen como gates GENERAL string/composition, OOP, inheritance,
interfaces, class Buffer fields, references, owning replacement, exceptions,
optimizer y workspace. El reproducer de Plots sólo puede pasar por la regla
general; no autoriza implementar Plots en el mismo cambio.

## Decisiones pendientes de implementación

- nombres Rust definitivos de `StringFieldAlias` y de la clasificación central;
- IDs definitivos de diagnósticos nuevos, preservando los mensajes normativos;
- punto exacto de materialización/elisión del owner temporal de borrow;
- fixture e instrumentación separada de eventos string/class;
- cambios concretos por fase, que deberán seguir esta arquitectura y superar
  la qualification antes de declarar el vertical implementado.

Estas decisiones no reabren semántica, layout, orden de ownership ni alcance.

**Estado final: ARCHITECTURE CLOSED; IMPLEMENTATION NOT STARTED. PLOTS REMAINS
BLOCKED.**
