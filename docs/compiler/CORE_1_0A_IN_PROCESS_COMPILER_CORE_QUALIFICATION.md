# CORE-1.0A — In-process compiler core qualification

Fecha local: 2026-08-28

## Decisión pre-CI

`CORE_IN_PROCESS_BOUNDARY_QUALIFICATION_BLOCKED`

La calificación local completa pasa en Linux x86_64, pero la decisión permanece
bloqueada de forma fail-closed hasta que un único run CI sobre una revisión
limpia aporte Linux x86_64, Windows x86_64, macOS x86_64, macOS arm64 y la
matriz CPython 3.11–3.14. Esto no es una divergencia observada: son gates de
portabilidad todavía ausentes localmente.

La evidencia local base usa `c90b71e5f989c4ccf83b7cca66f0e27ad00d3d7d`
con cambios sin commit, por lo que no se presenta como evidencia de una revisión
exacta reproducible. El checker exige `worktree_clean=true`, un mismo SHA y un
run ID CI no local antes de emitir `CORE_IN_PROCESS_BOUNDARY_QUALIFIED`.

## Superficies productivas afectadas y gates elegidos

El refactor afecta la ruta ordinaria de `aether-ssa-shadow`: decode protocol-v1,
llamada a `CompilerCore::lower_verified_ssa`, lifecycle policy-v1, lowering SSA,
verificación owned SSA, conversión schema-v2 y propagación de fallos. También
afecta indirectamente la integración que consume ese resultado: imported SSA,
refinement, autoridad RUST-4.5, modo diferencial y rollbacks.

Se ejecutaron 51 pruebas enfocadas de RUST-4.5: protocolo/default, lifecycle,
verification/refinement, differential Python shadow y rollback. Pasaron 51/51.
No se repitieron gates de optimizer, LLVM o release assembly que no alcanzan
esta ruta. `rust-ssa-shadow.yml` no se reemplazó ni modificó.

El companion ordinario y PyO3 comparten la misma implementación:

```text
protocol-v1 companion ---\
                         CompilerCore -> lifecycle -> SSA -> owned SSA verifier
PyO3 binding ------------/
```

El modo companion de caracterización mantiene la instrumentación por fases
separada porque es diagnóstico de performance, no una autoridad semántica. Un
guard de tests exige que la ruta ordinaria y PyO3 sigan llamando a
`CompilerCore`, que el core no dependa de PyO3 y que el selector productivo no
importe el cliente in-process.

Protocol-v1 conserva por defecto exactamente `{"ok": false, "error": ...}`.
Un flag exclusivamente de qualification agrega los siete campos diagnósticos
para compararlos con PyO3; sin ese flag el campo se omite por serialización.

## Resultados locales

- Histórico: companion 116/116, in-process 116/116 y equivalencia 116/116.
- Deep CFG: 993, 1000, 5000 y 10000 pasan sin recursión, overflow ni corrupción
  de lifetime.
- Casos ordinarios y feature-heavy: SSA schema-v2 exacto, canonical SSA,
  source locations, imported SSA verification y refinement equivalentes.
- Campaña Initial IR/binding: 8/8, cubriendo JSON/documento malformado, schema,
  CFG, función duplicada, retorno/value flow y lifecycle.
- Campaña SSA/refinement RUST-4.x: 13/13, incluyendo phi inválido, retorno,
  tipos, branches, calls, instrucciones preservadas, promoted values y SSA wire
  malformado. No se ocultaron divergencias; se registran las cuatro clases y la
  evidencia local contiene cero divergencias.
- Companion productivo: handshake protocol-v1, tres requests en un solo proceso,
  resultado repetido y failure shape histórico pasan.
- Sesiones: create/use/reuse, dos sesiones interleaved, isolation, error seguido
  de reuse, ocho llamadas same-session, cuatro independent-session y ocho
  fallos concurrentes pasan.
- GIL: un thread Python progresó 4,701,307 iteraciones durante lowering Rust.
  No se usa esto para prometer speedup; prueba que `detach` permite progreso.
- `CompilerCore` y `CompilationSession` son `Send + Sync`, verificado en compile
  time. El binding usa `Mutex<CompilationSession>`: sesiones independientes
  pueden correr en paralelo y la misma sesión se serializa. No hay `unsafe`, IDs
  globales ni registry de handles; stale/double-free no son estados del API.
- Memoria: 500 create/lower/export/destroy, crecimiento RSS 0 bytes y crecimiento
  Python trazado 0 bytes en esta ejecución. LSan no se ejecutó; no se confunde
  esa ausencia con evidencia de leak ni con limitación ptrace observada.
- Packaging Linux CPython 3.14: wheel clean-install/import/ordinary/failure/reuse
  pasa con Cargo ausente del `PATH` de instalación. El wheel lleva el módulo
  nativo, por lo que el usuario final no necesita Rust. Companion permanece
  usable y separado.

## Performance local

Release, dos warmups, cinco muestras; medianas y MAD/min/max están en JSON. La
performance es caracterización, no gate de corrección.

| Workload | Companion persistente | In-process |
|---|---:|---:|
| ordinary | 0.222 ms | 0.109 ms |
| historical batch (116) | 297.248 ms | 273.814 ms |
| repository real (`particles.ae`) | 3.101 ms | 2.424 ms |
| deep CFG 5000 | 183.039 ms | 174.790 ms |

La evidencia separa decode/conversion, IPC residual, core Rust, result
conversion y total boundary. No existe umbral mínimo ni afirmación de mejora
universal.

## Python y packaging CI

El paquete raíz declara Python `>=3.11`; el binding PyO3 produce wheels por minor
de CPython y no usa `abi3`. CORE-1.0A prueba las cuatro plataformas requeridas en
CPython 3.13 y, en Linux x86_64, cada minor 3.11, 3.12, 3.13 y 3.14. Esta matriz
valida el rango actualmente relevante sin multiplicar plataforma × minor.

`.github/workflows/core-in-process.yml` contiene jobs separados para:

1. semantic/historical/failures/deep/performance;
2. preservación productiva RUST-4.5;
3. sesiones/concurrencia/GIL/memoria;
4. clean-install de cuatro plataformas;
5. compatibilidad Python;
6. decisión aggregate fail-closed.

## Alcance y trust

CORE-1.0A no implementa CORE-1.1, no cambia semántica, no elimina el companion,
no promueve PyO3 y no introduce fallback. `AETHER_SSA_AUTHORITY_MODE` y el
default RUST-4.5 permanecen intactos. El companion sigue siendo el transporte
productivo y rollback actual; in-process sigue siendo `QUALIFICATION_ONLY` y
requiere construcción explícita.

Sólo después de un aggregate CI calificado puede afirmarse: “The in-process
boundary is operationally qualified against the existing companion and
qualified corpus on the tested platforms.” Nunca se afirma corrección universal.

Artefactos y herramientas:

- `core_1_0a_in_process_compiler_core_qualification.json`: decisión local;
- `core_1_0a_local_evidence/`: lanes locales completas;
- `scripts/qualify_core_1_0a_in_process.py`: semántica/productivo/sesiones;
- `scripts/qualify_core_1_0a_packaging.py`: clean install;
- `scripts/check_core_1_0a_in_process.py`: checker aggregate fail-closed.
