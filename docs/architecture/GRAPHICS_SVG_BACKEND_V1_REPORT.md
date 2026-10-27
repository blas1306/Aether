# GRAPHICS-SVG-BACKEND-V1 — reporte de implementación

Estado: **BLOCKED**, 2026-10-26.

## Autoridad revisada

Antes de modificar source se revisaron íntegramente
`GRAPHICS_SVG_BACKEND_ARCH_1`, su reporte, la enmienda owning y su reporte,
`GRAPHICS_FOUNDATION_ARCH_1`/reportes, `TEXT_UTF8_BUILDER_ARCH_1`/reportes y el
contrato FORMAT-V1 aplicable.

La capability `std.Text.fromUtf8` está implementada y no es el bloqueo. La
Foundation también expone todos los accessors read-only requeridos.

## Bloqueo reproducible

La enmienda exige que `SvgSerializer` sea un `struct` local owning y posea
directamente tres `Buffer`: output, states y clips. Los tres deben crecer
geométricamente durante la serialización. En el lenguaje vigente, un
`Buffer<T>` local puede reemplazarse y un field `Buffer<T>` de una class puede
reemplazarse, pero un field owning de un struct no puede reemplazarse. Tampoco
se habilita la operación prestando el field completo como `ref mut Buffer<T>`.

El reproducer mínimo está en
`reproducers/graphics_svg_owning_buffer_growth.ae`. Ejecutado con:

```text
cd compiler-next
cargo run -q -p aether-cli -- check \
  ../reproducers/graphics_svg_owning_buffer_growth.ae
```

produce:

```text
error[E0297] (semantic): partial replacement of a non-Copy aggregate is unsupported
```

El fallo corresponde a `*output = next`; reemplazar directamente
`serializer.output` produce la misma clasificación. Sin esa operación no se
puede publicar crecimiento geométrico de ninguno de los tres buffers owned por
el struct.

## Alternativas descartadas

- Volver el serializer una class permitiría reemplazar fields, pero contradice
  expresamente `GRAPHICS_SVG_BACKEND_ARCH_1_AMENDMENT_1` y vuelve a introducir
  el borrow interior que la enmienda elimina.
- Guardar los buffers en wrappers class o fuera del serializer viola el
  ownership local normativo.
- Precontar y reservar buffers exactos, o imponer una capacidad máxima, cambia
  la política normativa de crecimiento y sus gates de allocations.
- Copiar el output a un Buffer local al final agrega la copia innecesaria que
  la enmienda prohíbe.
- Modificar el compilador para admitir partial owning replacement está fuera
  del alcance y de la autorización de este milestone.

No se dejó un backend parcial ni se modificaron Foundation, std, compiler,
runtime u otras OAL.

## Gates

| Gate | Resultado |
|---|---|
| Lectura de autoridades normativas | PASS |
| Prerrequisito `std.Text.fromUtf8` | PASS |
| Accessors read-only de Foundation | PASS |
| `cargo test -p aether-driver --test graphics_foundation_v1` | PASS — 8/8 |
| `cargo test -p aether-driver --test text_utf8_builder_v1` | PASS — 8/8 |
| `cargo run -q -p aether-cli -- check ../graphics` | PASS |
| `cargo run -q -p aether-cli -- build ../graphics` | PASS |
| Serializer local owning con buffers growable | FAIL — E0297 |
| Backend SVG productivo | BLOCKED |
| Qualification funcional secciones 26–28 | NOT RUN — backend no construible conforme |
| Ausencia de cambios en Foundation/compiler/std | PASS |
| `git diff --check` | PASS |

El milestone no puede declararse `CLOSED`. Hace falta una decisión separada de
lenguaje que permita reemplazo seguro de un field owning en un struct local, o
una nueva enmienda normativa que autorice otra representación sin violar los
contratos de ownership y allocations.

**Estado final: BLOCKED.**
