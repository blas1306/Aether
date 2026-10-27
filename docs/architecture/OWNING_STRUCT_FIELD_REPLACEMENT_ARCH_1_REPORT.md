# OWNING-STRUCT-FIELD-REPLACEMENT-ARCH-1 — reporte de investigación

Estado: **INVESTIGACIÓN Y ARQUITECTURA COMPLETADAS; SIN IMPLEMENTACIÓN**,
2026-10-26.

Documento normativo:
[OWNING-STRUCT-FIELD-REPLACEMENT-ARCH-1](OWNING_STRUCT_FIELD_REPLACEMENT_ARCH_1.md).

No se modificó código productivo, runtime, Graphics ni tests. No se declara
GRAPHICS-SVG-BACKEND-V1 como cerrado.

## Resultado

Se seleccionó assignment con una operación IR indivisible `ReplaceOwned`.
Primero se materializa por completo el RHS; luego se publica el owner nuevo y
recién después se destruye el anterior. El field nunca queda desinicializado en
HIR, MIR o SSA. La operación consume una obligación RHS, descarga una obligación
anterior y conserva inicializado el mismo slot dentro del aggregate.

V1 se limita a fields directos/anidados mediante proyecciones `Field` de structs
locales, más esos slots o el pointee exacto alcanzados por `ref mut`. Excluye
índices, payloads enum, interior class storage, symbolic types no demostrados,
move-out, take, destructuring y swap. La regla se basa en propiedades concretas
(`Storable`, `Relocatable`, non-Copy y needs-drop), no en Buffer, Graphics ni
nombres nominales.

## Hallazgos de implementación

| Área | Hallazgo |
|---|---|
| diagnóstico | `hir.rs` emite E0297 para todo assignment non-Copy proyectado o con raíz Dereference |
| HIR verifier | repite la prohibición; quitar sólo el diagnóstico no atraviesa verificación |
| lowering MIR | el camino genérico contiene `Move(old)`, Store(new), Drop(old), pero sólo es válido para roots |
| MIR verifier | `Move` y `Drop` rechazan projections; el ledger exige un owner local completo |
| SSA verifier | repite que Move/Drop sean roots completos; un Store no expresa descarga del owner viejo |
| string | `ReplaceString` ya conserva publish-before-release y se verifica en MIR/SSA |
| classes | `ClassOp::FieldWrite` evalúa RHS, carga old, publica new y llama drop glue; además conserva receiver/constructor state |
| Drop | glue tipado recursivo ya cubre aggregates y collections y es non-throwing |
| init/cleanup | structs usan obligación/drop flag root-level; no existe ni se necesita bitmap de fields para replacement |
| exceptions | instrucciones potentially-throwing llevan unwind edge; el replacement no debe llevarlo, sólo su RHS |
| references | `ref mut` es write capability y explícitamente no promete uniqueness/noalias |

La consecuencia importante es que remover E0297 sería incorrecto. Activaría
un lowering que intenta representar un partial move y que los verificadores
posteriores, correctamente, rechazan. La capability necesita identidad propia
en HIR/MIR/SSA.

## Reproducer y alternativa sin lenguaje nuevo

El comando:

```text
cd compiler-next
cargo run -q -p aether-cli -- check \
  ../reproducers/graphics_svg_owning_buffer_growth.ae
```

sigue produciendo E0297 en `*output = next`.

Se comprobó además la reconstrucción del agregado completo. Con un struct que
contiene un solo Buffer y fields Copy, construir `One(next, old.length)` y
asignarlo al local root compila y ejecuta: reutiliza el replacement root vigente.
No resuelve el backend normativo. `SvgSerializer` contiene varios Buffer owning;
para reconstruirlo habría que leer/mover los siblings. La prueba equivalente
con dos Buffer falla al usar el segundo field con E0247/E0293: partial move de
un field non-Copy. Copiar todos los backings, boxearlos o cambiar a class altera
allocations, representación u ownership exigidos.

Por tanto existe un workaround sólo para el caso degenerado de un único owner,
no una solución actual para GRAPHICS-SVG-BACKEND-V1 ni para la capability general.

## Alternativas y decisión

| Alternativa | Resultado |
|---|---|
| assignment + `ReplaceOwned` | seleccionada: expresa intención existente, no expone old y preserva init |
| builtin `replace` | descartado: sintaxis nueva sin información semántica adicional |
| `swap`/`take` | descartado: expone o transfiere old y abre partial ownership |
| reutilizar ClassOp literalmente | descartado: structs no tienen receiver ARC, constructor FieldId state ni final release |
| reconstruir agregado completo | insuficiente con varios siblings owning |
| class/boxing/wrapper nullable | cambia aliasing, heap/layout o introduce estado parcial |
| copiar storage o usar otra collection | cambia costos, allocations y contrato público |

Se reutilizan de classes el orden RHS/publish/drop y el drop glue, y de string
el precedente de una operación IR atómica verificada. Se mantiene separado el
protocolo de class porque protege invariantes diferentes.

## Seguridad y riesgos

El riesgo principal es aliasing por references. `ref mut` no es exclusivo. La
decisión exige que HIR, MIR y SSA rechacen un replacement si existe cualquier
borrow/view vivo del root o de un place potencialmente solapado. Para raíces
reference de procedencia desconocida, referencias compatibles se consideran
`may_alias`; no se emite `noalias` ni se agrega un check runtime. Un borrow
call-scoped usado sólo para construir el RHS termina antes del commit.

Otros riesgos cerrados por el contrato:

- RHS que lanza: old permanece publicado y los temporales usan unwind normal;
- double-drop: old sólo existe dentro de ReplaceOwned y new pasa una vez al slot;
- leak: el verifier exige consumo RHS y descarga interna old;
- estado parcial: no hay Move/Drop proyectado ni drop flag por field;
- optimización: ReplaceOwned es un efecto read/write/consume/drop indivisible;
- tipos futuros: no se admite symbolic `T: Storable` ni se inventa Drop glue;
- scope creep: índices, enum payloads y class interior permanecen separados.

El diseño es conservador con borrows de siblings y aliases desconocidos. Esa
pérdida de expresividad es aceptada en V1 a cambio de no introducir inferencia
de regiones, exclusividad de `ref mut` ni MemorySSA.

## Qualification diseñada

La matriz futura incluye:

- Buffer directo, anidado, por `ref mut Buffer` y por `ref mut Struct`;
- múltiples replacements y aggregates con varios owners;
- owners concretos distintos de Buffer;
- borrow del RHS que termina antes del commit;
- RHS throw, exception posterior y early return;
- negativos de borrows vivos, aliases reference, shared refs, Index, enum,
  symbolic types, move-out, self/field-to-field y use-after-move;
- corruptions independientes HIR/MIR/SSA;
- native O0/O2 y gates completos de ownership, collections, classes y
  exceptions.

La instrumentación requerida registra allocations/frees por identidad,
retain/release, entradas de drop glue y commits de test. Para una secuencia
`v0 -> v1 -> v2`, debe demostrar Drops ordenados de `v0`, `v1` y `v2`; para RHS
throw, cero commit y supervivencia de `v0`. Terminar sin crash no cuenta como
prueba de lifecycle.

## Archivos creados

- `docs/architecture/OWNING_STRUCT_FIELD_REPLACEMENT_ARCH_1.md`
- `docs/architecture/OWNING_STRUCT_FIELD_REPLACEMENT_ARCH_1_REPORT.md`

No quedó el probe temporal usado para evaluar reconstrucción completa. No se
hizo commit ni push.
