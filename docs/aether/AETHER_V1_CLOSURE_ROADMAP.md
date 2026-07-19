# Roadmap de cierre de Aether 1.0

Cada bloque es pequeño, revisable y commiteable. Ninguno agrega features de
lenguaje.

## Bloqueadores de RC3

### R1 — Congelar el contrato normativo (P1, docs)

**Estado: CERRADO (2026-07-18).** La spec normativa ahora define únicamente
las 75 filas `SUPPORTED`; la superficie reconocida sólo por frontend/AST quedó
en un anexo experimental no normativo. El gate compara ambos bloques de IDs
contra la matriz de auditoría, busca las contradicciones conocidas, valida
links/clasificaciones y regenera el perfil native antes de aprobar.

- actualizar `AETHER_LANGUAGE_SPEC_V1.md` para que v1 estable sea el perfil
  native cerrado;
- mover la superficie AST-only a un anexo experimental;
- corregir la sintaxis de interpolación documentada y la afirmación de backend
  por defecto en `AETHER_IR_DESIGN.md`;
- enlazar audit, decision, native profile y manifest desde el README.

**Gate:** script de docs, búsqueda de contradicciones conocidas y
`git diff --check`.

**Evidencia de cierre:** `.venv/bin/python scripts/check_release_docs.py`,
`git diff --check` y `tests/test_release_contract.py`. Este cierre resuelve R1
y la parte documental de B12; no altera el estado de B13 ni sustituye R2.

### R2 — Cerrar el catálogo oficial de ejemplos (P1)

**Estado: CERRADO (2026-07-18).** Se conservaron los 78 `V1_NATIVE`, los dos
ejemplos reparables de álgebra pasaron a `AST_ONLY_EXPERIMENTAL`, el experimento
de asignación a slice pasó a fixture inválido estructurado y el duplicado
interactivo incompleto fue eliminado con decisión auditada. El catálogo público
queda en 101 rutas: 78 native, 23 AST-only y cero `BROKEN`.

**Gate:** `scripts/check_examples_catalog.py` y
`tests/aether/test_v1_profile_audit.py`: esquema y cobertura 1:1 de 101 rutas,
typecheck/capability de todos los experimentales, pipeline verificado de los 78
native, observación de los 68 entry points y ejecución AST observada para 14 de
los 23 experimentales (los demás son input, plotting o módulos). El wheel distribuye README,
manifiesto y ejemplos, sin fixtures; el sdist conserva el corpus de tests.

**Evidencia de cierre:** `AETHER_EXAMPLES_CATALOG_AUDIT.md` registra ruta,
historia, sintaxis, fase, referencias, valor y decisión de los cuatro casos.
R2/B13 queda cerrado sin promover ninguna feature experimental a Aether 1.0.

### R3 — Normalizar diagnostics de pipeline (P2 relevante)

**Estado: SIGUIENTE BLOQUEADOR DE RC3.**

- conservar `AE-BACKEND-*` para capability;
- mapear rechazo de verifier a categoría pública `verification` manteniendo
  `ir`/`ssa` como detalle;
- añadir una frontera `internal compiler error` para excepciones inesperadas,
  sin convertirlas en errores de usuario;
- probar stderr, exit code 1 y ausencia de traceback.

**Gate:** tests CLI/LSP de syntax, type, capability, verification, runtime e ICE.

### R4 — Validación RC3 limpia

- suite Python completa;
- corpus diferencial (14 programas × O0/O1/O2);
- los 101 casos del manifest;
- Gradle/IntelliJ tests;
- `scripts/ci.py`, build de wheel/sdist e instalación limpia;
- `git diff --check` y release manifest desde un commit limpio.

**Gate:** ningún skip nuevo; clang ausente debe fallar el release gate, no
degradarlo a warning.

## Entre RC3 y 1.0

### S1 — Sanitizers y stress externo

- ASan/UBSan obligatorios para corpus native y ejemplos de ownership;
- LSan donde el runner sea confiable;
- stress de strings, Array/List, structs anidados, exits tempranos y loops;
- documentar allocation failure y stack overflow como límite si no se cierran.

### S2 — Fuzzing básico y property tests

- lexer/parser con UTF-8 válido e inválido;
- IR/SSA verifiers con modelos mutados;
- codecs string/ALPT1 y slicing/bounds;
- propiedad AST/native para programas pequeños dentro del profile gate.

### S3 — Packaging e instalación limpia

- wheel y sdist en venv sin checkout;
- validar que `aether --version`, native smoke, imports y runtime data no usan
  paths del repositorio;
- documentar clang externo y Linux x86_64;
- no declarar Windows/macOS sin una matriz real.

### S4 — Dogfooding y documentación

- ejecutar numerical methods, expense tracker, FormulaNumerosPrimos y NR desde
  instalación limpia;
- revisar outputs/hashes y timeouts;
- tutorial pequeño que sólo use `SUPPORTED`;
- rotular todos los documentos v0/rc.1 como históricos.

### S5 — Trazabilidad de capabilities

- sustituir el set manual `E2E_TESTED_CAPABILITIES` por registro
  capability→test/corpus;
- generar la tabla del native profile y validar que ninguna fila concreta
  vuelva a depender de `PARTIAL` como conclusión.

## Después de 1.0

Reabrir sólo mediante RFC y pipeline completo, en bloques independientes:

- `long` y una política de overflow multiancho;
- do-while y match;
- lambdas, closures, captura y callable returns;
- classes, interfaces, vtables, ABI y ownership;
- float/complex con semántica y ABI definidos;
- rangos genéricos y rangos almacenables;
- Vector/Matrix avanzado y álgebra lineal native;
- IO/persistencia general, GC si alguna vez se decide;
- migración parcial a Rust/C/C++ sólo como proyecto de backend, nunca como
  condición implícita de una feature.

Estas tareas no pertenecen a RC3 ni a 1.0 y no deben colarse como “correcciones
pequeñas” de la auditoría.
