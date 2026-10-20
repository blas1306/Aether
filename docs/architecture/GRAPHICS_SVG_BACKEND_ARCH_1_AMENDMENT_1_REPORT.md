# GRAPHICS-SVG-BACKEND-ARCH-1-AMENDMENT-1 — reporte

Estado: **CLOSED**, 2026-10-20.

Autoridad:

- [GRAPHICS-SVG-BACKEND-ARCH-1](GRAPHICS_SVG_BACKEND_ARCH_1.md);
- [GRAPHICS-SVG-BACKEND-ARCH-1 — reporte](GRAPHICS_SVG_BACKEND_ARCH_1_REPORT.md);
- [CLASS-HANDLE-REFERENCES-V1 — reporte](CLASS_HANDLE_REFERENCES_V1_REPORT.md);
- [TEXT-UTF8-BUILDER-V1 — reporte](TEXT_UTF8_BUILDER_V1_REPORT.md).

Documento de enmienda:
[GRAPHICS-SVG-BACKEND-ARCH-1-AMENDMENT-1](GRAPHICS_SVG_BACKEND_ARCH_1_AMENDMENT_1.md).

## Resultado

Se corrigió exclusivamente la representación privada del serializer SVG. El
serializer deja de ser una class y pasa a ser un struct owning creado como
local dentro de `render`. Posee los Buffers de output, stack de state y clips,
además de logical length, estado corriente y counters.

La instancia no escapa y no requiere identidad, Alias, ARC ni lifecycle
compartido. Sus fields se limpian mediante lifecycle ordinario en las salidas
normal y excepcional.

## Coherencia de references

La API implementada por TEXT-UTF8-BUILDER-V1 exige:

```aether
std.Text.fromUtf8(ref Buffer<uint8>, usize)
```

Un `Buffer<uint8>` guardado en el payload de una class no puede prestarse como
field interior: CLASS-HANDLE-REFERENCES-V1 conserva deliberadamente fuera del
lenguaje esos interior borrows. Con el serializer como struct local owning,
la llamada final usa una proyección ordinaria admitida:

```aether
std.Text.fromUtf8(&serializer.output, serializer.outputLength)
```

La publicación copia el prefijo validado a un string owner independiente. El
serializer y sus Buffers pueden destruirse después de la llamada sin crear un
borrow escapado ni transferir el backing.

`Scene` permanece una class inmutable recibida como `ref Scene`. Ese borrow es
del handle directo y no implica un borrow de fields interiores. No se amplió
el lenguaje, no se habilitaron interior borrows de class y no se requiere otro
milestone de lenguaje.

## Contrato preservado

Permanecen sin cambios API pública, formato SVG, output canónico, painter
order, state machine, clip IDs, escaping, mappings de text/fonts, errores,
determinism, qualification, complejidad asintótica y política de allocations.
El único delta de allocation es que ya no existe la allocation class del
serializer; las allocations de Buffers, temporales numéricos y string final
siguen bajo el contrato original.

No se modificó graphics foundation ni source productivo.

## Archivos y cierre

Se agregaron solamente:

```text
docs/architecture/GRAPHICS_SVG_BACKEND_ARCH_1_AMENDMENT_1.md
docs/architecture/GRAPHICS_SVG_BACKEND_ARCH_1_AMENDMENT_1_REPORT.md
```

La decisión es compatible con las cuatro autoridades y elimina la
incompatibilidad sin reabrir ninguna frontera. El siguiente milestone puede
ser `GRAPHICS-SVG-BACKEND-V1`.

CLOSED
