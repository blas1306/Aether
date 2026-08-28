# CORE-1.0 — In-process compiler-core boundary

Fecha: 2026-08-28

Estado: **prototipo qualification-only calificado en Linux x86_64**. No es el
default productivo, no modifica `AETHER_SSA_AUTHORITY_MODE`, no tiene fallback
automático y no reemplaza ni elimina el companion.

La evidencia reproducible está en
[`core_1_0_in_process_compiler_core_boundary.json`](core_1_0_in_process_compiler_core_boundary.json)
y el harness en
[`qualify_core_1_0_in_process_boundary.py`](../../scripts/qualify_core_1_0_in_process_boundary.py).

## Decisión

CORE-1.0 adopta un límite híbrido y transicional:

```text
Python IRModule
  -> schema-v1 una vez
  -> adapter PyO3                  adapter protocol-v1
          \                         /
           CompilerCore.accept_initial_ir(IRModuleDTO)
                         |
              Rust-owned CompilationSession
                         |
                    lower_ssa()
                         |
                   OwnedSsaModule
                         |
          schema-v2 sólo para Python actual/debug
```

El API semántico vive en `aether-verifier::compiler_core`, no en PyO3. Se eligió
ese crate porque ya posee la verificación Rust compuesta y el companion que
orquesta lowering+verification; `aether-ir` sigue siendo deliberadamente el
modelo/importer sin autoridad semántica. Crear otro crate ahora habría añadido
un ciclo o un wrapper sin ownership propio. Si CORE-2.0 hace que optimización y
backend excedan claramente el concepto de verifier, deberá extraerse este
módulo conservando su API tipada.

El API implementado es:

```rust
CompilerCore::accept_initial_ir(IRModuleDTO) -> CompilationSession
CompilationSession::lower_ssa() -> Result<(), CompilerError>
CompilationSession::ssa() -> Option<&OwnedSsaModule>
CompilationSession::export_ssa_schema_v2() -> Result<SSAModuleV2DTO, CompilerError>
```

`aether-ssa-shadow` usa `CompilerCore::lower_verified_ssa` en su ruta ordinaria.
El modo instrumentado conserva llamadas separadas únicamente para medir fases;
no implementa semántica SSA alternativa.

## Auditoría exacta del límite actual

El objeto que llega al límite es un `aether.ir.model.IRModule` Python ya
verificado y, en el default RUST-4.5, normalizado por `expand_lifecycle`. La ruta
actual realiza:

1. `IRVerifier(module).verify()` en la aceptación shadow-independent;
2. snapshot schema-v1 con `ir_module_to_dto`;
3. `expand_lifecycle` Python y segundo snapshot schema-v1;
4. `json.dumps(..., separators=(",", ":"))` y UTF-8;
5. frame de 4 bytes big-endian seguido del JSON;
6. subprocess `aether-ssa-shadow --persistent`;
7. `serde_json` a `IRModuleDTO`, normalización Rust idempotente, lowering SSA y
   `verify_owned_ssa`;
8. materialización schema-v2, JSON y frame de respuesta;
9. `json.loads`, `ssa_module_from_dto`, `SSAVerifier` Python;
10. dos checks de integridad del input, `verify_ssa_refinement`, otro
    `SSAVerifier`, y verificaciones posteriores de pipeline/optimizer/backend.

La auditoría post-RUST-4.5 observó tres verificaciones Initial IR y cinco SSA en
O0. CORE-1.0 no elimina ninguna: hacerlo corresponde a una promoción posterior.

El handshake companion fija producto/versiones/protocolo, acepta frames de hasta
64 MiB y sirve múltiples requests. Python conserva un proceso global lazy y un
cache de companions de calificación. `PersistentRustSSALoweringClient` serializa
requests con un lock; el estado persistente es proceso, pipes, contadores y
configuración de timing. No hay estado semántico Rust entre requests.

### Transporte frente a semántica

Son transporte: descubrimiento/package manifest, subprocess, handshake, framing,
timeout, límite de tamaño, JSON encode/decode, locks de pipes y restart/close.

Son compiler core: aceptar Initial IR tipado, normalización lifecycle policy-v1,
construcción SSA, ownership de `OwnedSsaModule`, verificación Rust y clasificación
de errores por fase. Schema-v1/v2 siguen siendo contratos de adapter/escape, no
métodos entre futuras etapas.

## Auditoría de `aether-python`

Antes de CORE-1.0 el crate estaba en el workspace, no tenía dependencias, código,
PyO3, funciones exportadas, build ni packaging; no participaba en producción.
Era sólo un comentario que reservaba una frontera futura.

El prototipo lo convierte en un adapter fino:

- PyO3 0.29.2, `cdylib` + `rlib`, módulo `_aether_core`;
- `CompilerCore` Python crea `CompilationSession` Rust-owned;
- cada sesión contiene `Mutex<CompilationSession>`; no usa globals ni `unsafe`;
- copia los bytes de entrada una vez para desacoplar el lifetime Python y luego
  decodifica schema-v1 sin GIL;
- libera el GIL durante decode, lowering, verificación y export;
- retorna schema-v2 bytes como escape transicional; el adapter Python existente
  los importa al modelo SSA actual;
- publica `QUALIFICATION_ONLY=True` y no está conectado a selección productiva.

El crate es apto como binding permanente si permanece fino. No debe absorber
política de authority, semántica, canonicalización ni fallback. Su deuda actual
es que schema-v1/v2 todavía copia y serializa en los extremos y que el packaging
vive en un `pyproject.toml` de calificación separado del paquete release raíz.

## Alternativas de entrada/salida

| Alternativa | Copias/serialización | Ownership y estabilidad | Diagnóstico y futuro | Decisión |
|---|---|---|---|---|
| A. objetos Python → conversión PyO3 campo a campo | evita JSON, pero cruza el árbol completo y acopla nombres/clases Python | lifetimes complejos; dos modelos cambian juntos | buen debug Python; mala migración gradual | descartada ahora |
| B. schema-v2 bytes/string | copia y JSON en ambos extremos | contrato congelado y compatible con companion | simple y depurable; repetirlo entre etapas sería un callejón | sólo entrada/salida transicional |
| C. wrappers tipados sobre representaciones Rust | pocas conversiones tras construirlos | ownership claro, API Python grande | útil cuando el frontend produzca nodos Rust incrementalmente | candidata futura, prematura |
| D. handles opacos Rust | una conversión inicial; cero fronteras internas | lifetime/invalidation explícitos | excelente para absorber optimizer/backend; peor inspección directa | elegida internamente |
| E. híbrida | schema-v1 al entrar + handle Rust + schema-v2 al salir hoy | rollback compatible y etapas futuras Rust-owned | mantiene escape de debug sin volverlo API entre etapas | **elegida** |

No se eligió `lower_initial_ir_to_ssa(json) -> json` como API arquitectónica. El
binding puede reproducir ese efecto para calificar, pero lo hace creando una
sesión y llamando métodos del core.

## Representación Rust-owned

CORE-1.0 sí introduce un objeto persistente por compilación. Posee el
`IRModuleDTO` decodificado y, después de `lower_ssa`, el `OwnedSsaModule`.
`lower_ssa` es idempotente; no publica referencias mutables; `ssa()` presta una
referencia Rust y el binding serializa el acceso con `Mutex`. El GC Python
destruye el handle y todas sus representaciones juntas. No existen IDs globales,
registries ni handles reutilizables después de destrucción.

Mutabilidad futura debe ser por transiciones de estado verificadas dentro de la
sesión. Un error no deja publicar SSA parcial. Export schema-v2 es el escape de
debug/compatibilidad y no invalida el estado. Este diseño permite que CORE-1.1
añada verificación/refinement y CORE-2.0 optimización/backend sin serialización
intermedia.

## Errores

El core define `CompilerError` con `kind`, `category`, `phase`, `code`, `message`,
`function`, `block` y `source_location`. El binding traduce a:

- `AetherCompilerError`: rechazo determinista del programa/lowering;
- `AetherBindingError`: JSON/schema o uso incorrecto del límite;
- `AetherInternalCompilerError`: invariant/state/SSA Rust inesperado.

Todas heredan de `AetherCoreError` y conservan los campos legibles por máquina
como atributos, incluido contexto de función/bloque. No se aplana todo a
`RuntimeError`. La ubicación de fuente es
opcional porque los errores de lowering actuales no siempre exponen todavía una
ubicación tipada; el campo ya forma parte del contrato y debe poblarse al
propagar diagnósticos tipados en CORE-1.1. El companion conserva el texto de
protocolo v1 y su comportamiento fail-closed; el código estructurado no altera
su wire contract.

## Paridad diferencial

El run completo usó exactamente los mismos bytes schema-v1 normalizados para
ambos adapters. Resultados:

- programas ordinarios, strings, colecciones, multi-module y lifecycle-heavy:
  PASS;
- corpus histórico: **116/116 PASS**;
- mutaciones `malformed_json`, `unsupported_schema` y `missing_terminator`:
  misma aceptación/rechazo y mismo texto; el binding además conservó clase,
  categoría, fase, código y location;
- deep CFG **993, 1000, 5000 y 10000: PASS**;
- schema-v2 exacto, representación canónica, source locations e import+
  verificación Python: PASS en cada caso;
- 139 requests por ruta; companion inició una vez e in-process cero procesos.

La canonicalización existente fue sólo oracle de calificación. No hay una nueva
dependencia productiva en canonical comparison.

## Caracterización de performance

Workload: `examples/aggregate_collections/particles.ae`, release, dos warmups y
nueve muestras, mediana/MAD y min/max. El scope incluye transporte/core, import
schema-v2 y verificación Python posterior en ambas rutas.

| Ruta | Mediana | MAD | min–max |
|---|---:|---:|---:|
| companion persistente | 7.320 ms | 0.179 ms | 6.659–8.604 ms |
| in-process | 6.089 ms | 0.102 ms | 5.899–6.191 ms |

Ratio de medianas in-process/companion: 0.832. Fases directas in-process:
decode/copia schema-v1 0.327 ms, lifecycle+SSA+Rust verification 1.537 ms y
materialización schema-v2/bytes 0.052 ms. El resto incluye JSON/import y
verificación Python.

Esto demuestra una reducción medible de costo/variabilidad de frontera en este
caso y, sobre todo, elimina el IPC entre futuras etapas. No implica un speedup
whole-compiler: startup/import Python, verificaciones redundantes, refinement,
LLVM y clang quedan fuera o siguen dominando según workload.

## Packaging y plataformas

El prototipo usa maturin y produjo/instaló correctamente
`aether_core_qualification-0.1.0-cp314-cp314-manylinux_2_34_x86_64.whl`; import,
metadata y error estructurado pasaron en un venv limpio. El usuario final no
necesita Rust cuando instala un wheel.

La release deberá publicar wheels para Linux x86_64, Windows x86_64, macOS
x86_64 y macOS arm64. La extensión es `_aether_core` (`.so`/`.pyd`). El proyecto
declara Python >=3.11. El prototipo genera wheels CPython-minor-specific; `abi3`
podría reducir la matriz, pero debe decidirse junto con soporte de CPython
free-threaded y validarse antes de promoción. macOS necesita flags de extension
module que maturin configura; Windows necesita toolchain MSVC; Linux release
debe elegir baseline manylinux compatible con el paquete principal.

La matrix multiplataforma no se ejecutó en CORE-1.0. El root `pip install` sigue
empaquetando sólo Python+companion: integrar el wheel nativo allí es trabajo de
promoción, no de este prototipo.

## Threading, concurrencia y rollback

PyO3 libera el GIL para import, lowering, verificación y export Rust. Cada handle
tiene su propio mutex y estado, por lo que sesiones distintas pueden ejecutarse
en paralelo; llamadas simultáneas sobre la misma sesión se serializan. No hay
estado semántico global ni `unsafe`. El core y DTOs son `Send` bajo esta
implementación. Antes de paralelizar etapas internas habrá que decidir si una
sesión admite forks/snapshots o sólo transiciones exclusivas.

El companion actual sigue siendo el rollback. Durante CORE-1.x la selección
debe ser explícita entre `in_process` y `companion`; este prototipo sólo ofrece
`InProcessRustSSALoweringClient` por import/construcción directa. Si import o
ejecución in-process falla, se propaga/rechaza: nunca intenta el companion de
forma silenciosa.

## Validación

- `cargo check --workspace`: PASS;
- `cargo test --workspace --locked`: PASS;
- adapter Python: 2/2 PASS;
- build release companion y binding: PASS;
- wheel build/install/import/error smoke local: PASS;
- diferencial completo/historical/deep/failures: PASS;
- `cargo fmt --check`: requerido en cierre final;
- `git diff --check`: requerido en cierre final;
- matrix cross-platform: no ejecutada, deliberadamente.

## Decisión CORE-1.0 y CORE-1.1

La frontera queda **calificada como prototipo**, no promovida. Cumple separación
core/transporte, binding funcional, paridad, corpus, fallos, deep CFG, diseño de
packaging, mejora de frontera y rollback intacto sin cambios semánticos.

CORE-1.1 debe absorber exactamente la aceptación ya implementada en Rust:

1. conectar la autoridad Initial IR Rust al `IRBackend()` realmente usado;
2. aceptar Initial IR no normalizado en la sesión y hacer lifecycle Rust una
   sola vez;
3. portar/establecer el refinement verifier independiente en el core o definir
   evidencia equivalente antes de retirar su ejecución Python;
4. reducir las tres verificaciones Initial IR y cinco SSA a una ejecución
   intencional por familia en producción, conservando oracles Python en modos de
   calificación/rollback;
5. mantener el `OwnedSsaModule` en la sesión hasta que el consumidor Python
   actual necesite schema-v2.

No debe absorber todavía optimizer, backend LLVM ni nuevas semánticas. La
evidencia señala que verification/refinement/schema conversion son el siguiente
borde coherente; migrar una etapa no relacionada volvería a multiplicar
fronteras.

## Archivos y garantías

Cambios: módulo `compiler_core` en `aether-verifier`, binding `aether-python`,
adapter Python experimental, harness, pruebas y estos dos artefactos. El
companion permanece, schema-v1/v2 permanecen, ninguna verificación fue eliminada,
la política productiva no cambió, no se creó commit y no se ejecutó una nueva
qualification multiplataforma completa.
