# FIRST-CLASS-CLOSURES-ARCH-1 — ABI Scope Amendment

Estado: **ENMIENDA NORMATIVA ACEPTADA; ARQUITECTURA CLOSED; IMPLEMENTACIÓN NO
INICIADA**, 2026-11-01.

Esta enmienda modifica de forma acotada
[FIRST-CLASS-CLOSURES-ARCH-1](FIRST_CLASS_CLOSURES_ARCH_1.md). Todo requisito
original no sustituido aquí permanece vigente. Son también autoridades su
[reporte de cierre](FIRST_CLASS_CLOSURES_ARCH_1_REPORT.md) y el reporte de
[OWNING-CLOSURES-READ-V1](OWNING_CLOSURES_READ_V1_REPORT.md).

La revisión inspeccionó además `aether-driver::CompilationSession`, el pipeline
HIR/MIR/SSA, `LlvmTextBackend`, `aether-package::PackageMetadata` y la
resolución vigente de packages fuente.

## 1. Decisión

`OWNING-CLOSURES-READ-V1` se califica en el modelo que Aether implementa hoy:
una `CompilationSession` descubre todas las fuentes transitivas, incluidas las
de packages fuente, y una invocación del pipeline produce un único programa
verificado y un único módulo LLVM para un target.

La compatibilidad entre artefactos Aether producidos por compilaciones
independientes no es una precondición técnica para la corrección de closures
dentro de ese modelo. Se separa en el milestone futuro
`COMPILED-ARTIFACT-ABI`.

Esta separación no declara implementado ni qualified
`OWNING-CLOSURES-READ-V1`. Elimina únicamente el prerrequisito incorrecto de
compilación separada.

## 2. Tres contratos distintos

### 2.1 A — ABI interno de Closure en compilación conjunta

Es el alcance normativo de `OWNING-CLOSURES-READ-V1`:

- módulos y packages fuente alcanzables pertenecen a una misma
  `CompilationSession`;
- un único compilador construye identidades, tipos, layouts, thunks y
  operaciones de ownership;
- un único `TargetDescriptor` y data layout gobiernan todas las instancias;
- un único `VerifiedSsa` cruza al backend;
- el backend emite un único módulo LLVM con productores y consumidores;
- los helpers ARC versionados están disponibles coherentemente para ese
  módulo y su runtime;
- invoke/destroy thunks permanecen alcanzables mientras un box pueda usarlos.

En este dominio, un consumidor conoce sólo el header común y la firma
`Closure<(P...), R>`. El payload privado se proyecta exclusivamente dentro de
los thunks del productor. No existe una segunda compilación capaz de elegir
otro header, calling convention, target o epoch.

### 2.2 B — compatibilidad entre compilaciones independientes

Es la capacidad de enlazar o cargar un productor y un consumidor Aether
compilados por separado. Requiere una frontera binaria que hoy no existe:
interfaces/objetos importables, metadata ABI persistida, reglas públicas de
linkage y una etapa que compare productor y consumidor antes del link/load.

B no se demuestra mediante dos módulos fuente ni mediante dos packages fuente
de una misma sesión. Tampoco es necesaria para A: ninguna ruta de ejecución de
la compilación conjunta consume un box producido por otro artefacto Aether.

### 2.3 C — distribución y versionado de bibliotecas precompiladas

Es el contrato de publicación, selección, evolución y reutilización de
artefactos binarios. Además de B, comprende compatibilidad declarada entre
versiones, política de compiler ABI epoch, invalidación de caches y soporte de
tooling/package registry. Queda igualmente fuera de
`OWNING-CLOSURES-READ-V1`.

## 3. Sustituciones normativas

| Requisito original | Sustitución de esta enmienda |
|---|---|
| §5: return hace bloqueante el “ABI cross-module” | Return hace bloqueante la corrección ownership y ABI entre funciones y módulos **fuente** de la misma sesión. No hace bloqueante la compilación separada. |
| §9.2: “cross-module” sin distinguir fronteras | En V1 significa módulos/packages fuente compilados conjuntamente. La frontera de artefactos se difiere. |
| §9.3: metadata y rechazo de incompatibilidad | El header e identidad se aplican ahora. Metadata persistida y rechazo entre artefactos pertenecen a `COMPILED-ARTIFACT-ABI`. |
| §14: package ABI qualification como dependencia | V1 exige ABI interno, helpers y reachability en la sesión conjunta. Package binary ABI queda fuera. |
| §§15–16: metadata/identidad cross-module y “exact cross-module ABI” | V1 prueba paso/return entre módulos y packages fuente dentro de una sesión; no afirma compatibilidad binaria independiente. |
| §17: metadata rejection como mitigación inmediata | Un único compiler/target y los verificadores impiden mezclar representaciones en V1. Artefactos independientes deben fallar cerrados en el milestone futuro. |
| §18.5: metadata incompatible se rechaza como decisión V1 | Header, thunks y helpers siguen fijados. El rechazo de artefactos incompatibles no es gate de V1. |

## 4. Invariantes implementables y calificables ahora

### 4.1 Header y layout

`ClosureABI-v1` permanece sin cambios:

- `strong_count`, `invoke_thunk` y `destroy_thunk` en offsets `0`, `W` y
  `2W`;
- carrier como pointer owning al byte cero del header;
- payload desde `align_up(3W, payload_alignment)`;
- size/alignment calculados con el target de la sesión y overflow checked;
- requisito de igualdad de word, data pointer y code pointer para el target;
- payload privado, nunca inspeccionado por consumidores.

Como todas las fuentes se analizan y emiten con un único target descriptor, no
hay dos cálculos de layout que reconciliar. Esto no permite cambiar el layout
por módulo ni interpretarlo heurísticamente.

### 4.2 Identidad, mangling y reachability

Cada expresión conserva identidad compiler-internal basada en package,
módulo, `LambdaId`, instancia generic y versión ABI. La construcción debe ser
determinista y libre de colisiones dentro del programa emitido. El mangling
incluye la firma y recipe de captures exigidas por la arquitectura.

El invoke thunk, destroy thunk y body sintético son roots de reachability
cuando su dirección se almacena en un box alcanzable. Deben emitirse una vez
por instancia generada. Deduplicación o COMDAT pueden usarse, pero no son
necesarios para demostrar interoperabilidad entre artefactos en V1.

### 4.3 Acceso consumidor y llamadas indirectas

Un consumidor en otra función, módulo fuente o package fuente:

1. trata el carrier exclusivamente como `Closure<(P...), R>`;
2. carga `invoke_thunk` desde el offset normativo;
3. reconstruye el prototype desde la firma verificada;
4. pasa el box como primer argumento oculto;
5. nunca proyecta ni necesita conocer el payload.

HIR, MIR y SSA verifican de forma independiente carrier, aridad, parámetros,
resultado, borrow/keepalive y unwind edge. LLVM opaque pointers no son
autoridad para convertir `Function` y `Closure` ni para ocultar una firma
incompatible.

### 4.4 ARC, paso y retorno

`aether_closure_retain_v1` y `aether_closure_release_v1` conservan nombre y
contrato versionados. En V1 deben ser accesibles para todo el código del módulo
emitido y enlazarse con una única implementación coherente. Alias, Transfer,
Move, replacement, return y Drop conservan las obligaciones originales entre
funciones y módulos fuente.

Return no depende de metadata de artefactos: el carrier continúa apuntando al
box y a thunks presentes en el mismo módulo LLVM final. Sí depende de que
reachability preserve esos thunks y de que cada salida normal/unwind transfiera
o libere exactamente la obligación correspondiente.

## 5. Garantías diferidas a `COMPILED-ARTIFACT-ABI`

El milestone futuro debe cubrir:

1. formato compiler-owned de interface/object Aether importable;
2. emisión y consumo mediante invocaciones de compilador independientes;
3. metadata persistida de Aether ABI, Closure ABI y compiler ABI epoch;
4. target triple y fingerprint canónico del data layout;
5. compatibilidad de mangling, calling conventions, symbols y visibility;
6. linkage/reachability de helpers, bodies y thunks exportados;
7. validación fail-closed antes del link/load, sin adaptación heurística;
8. pruebas reales productor/consumidor independientes y matrices de versiones;
9. política de distribución, cache, registry y evolución de bibliotecas.

Hasta cerrar ese milestone, Aether no promete reutilizar una closure a través
de artefactos precompilados. Tampoco puede presentar tests entre módulos fuente
como prueba de esa capacidad.

## 6. Qualification revisada

### 6.1 `OWNING-CLOSURES-READ-V1` — obligatoria

| Área | Evidencia requerida |
|---|---|
| local y cross-function | crear, alias/move, pasar, retornar e invocar repetidamente |
| cross-source-module | productor y consumidor en módulos fuente distintos de una sesión |
| cross-source-package | import de package fuente, paso y retorno en ambos sentidos dentro de la sesión |
| ABI interno | header/offsets/alignment exactos y payload sólo accedido por thunks |
| identidad | `LambdaId`/instancia/mangling deterministas y sin colisiones |
| reachability | invoke/destroy/body presentes aunque sólo sean referidos desde boxes |
| ARC | helpers versionados accesibles y contadores exactos de retain/release/alloc/free/drop |
| calls | prototype con environment oculto, sin conversión `Function`/`Closure` |
| ownership | Alias/Transfer/Move/replacement/return y conditional Drop exactos |
| exceptions | mismo `ExceptionEvent`, cleanup normal/unwind y destroy `nounwind` |
| verificación | corrupción independiente HIR/MIR/SSA de tipo, identity, recipe, owner y CFG |
| optimización | igual resultado/lifecycle en O0/O2, sin UAF, leak ni double free |

Estos tests prueban interoperabilidad de módulos fuente y packages fuente
compilados conjuntamente. El reporte debe nombrarla así.

### 6.2 `COMPILED-ARTIFACT-ABI` — no atribuible a V1

| Área | Estado durante V1 |
|---|---|
| productor/consumidor compilados independientemente | diferida |
| importación de object/library Aether | diferida |
| metadata target/data-layout/epoch | diferida |
| rechazo de mezcla ABI incompatible | diferida |
| estabilidad binaria entre versiones de compiler | diferida |
| bibliotecas precompiladas distribuibles | diferida |

Estos gates son `OUT OF SCOPE`, no `PASS`, para
`OWNING-CLOSURES-READ-V1`.

## 7. Bloqueos técnicos reales restantes

La revisión confirma trabajo sustantivo dentro del vertical, pero no otro
prerrequisito arquitectónico general:

- la gramática aún no acepta `capture(...)`;
- el frontend capture-free no conserva el scope exterior necesario para
  análisis de variables libres capturantes;
- todavía no existen `TypeData::Closure`, operaciones HIR/MIR/SSA, ledgers de
  ownership, helpers ARC ni lowering LLVM de boxes/thunks;
- deben implementarse reachability, unwind/cleanup y toda la qualification de
  §6.1.

Son componentes y gates propios de `OWNING-CLOSURES-READ-V1`. Su ausencia
significa **IMPLEMENTACIÓN NO INICIADA / NOT QUALIFIED**, no dependencia de
compilación separada.
