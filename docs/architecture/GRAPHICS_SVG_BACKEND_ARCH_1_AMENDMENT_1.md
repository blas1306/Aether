# GRAPHICS-SVG-BACKEND-ARCH-1-AMENDMENT-1 — serializer local owning

Estado: **CLOSED**, 2026-10-20.

Esta enmienda es exclusivamente documental. Corrige una única decisión de
representación privada de
[GRAPHICS-SVG-BACKEND-ARCH-1](GRAPHICS_SVG_BACKEND_ARCH_1.md); no implementa
el backend ni modifica source productivo, compiler, runtime, Core, std,
graphics foundation o tests ejecutables.

## 1. Autoridad y alcance

Son autoridad para esta enmienda:

- [GRAPHICS-SVG-BACKEND-ARCH-1](GRAPHICS_SVG_BACKEND_ARCH_1.md);
- [GRAPHICS-SVG-BACKEND-ARCH-1 — reporte](GRAPHICS_SVG_BACKEND_ARCH_1_REPORT.md);
- [CLASS-HANDLE-REFERENCES-V1 — reporte](CLASS_HANDLE_REFERENCES_V1_REPORT.md);
- [TEXT-UTF8-BUILDER-V1 — reporte](TEXT_UTF8_BUILDER_V1_REPORT.md).

El ARCH original permanece normativo salvo en la elección puntual que esta
enmienda sustituye: el serializer privado ya no es una class. Toda otra
decisión del ARCH y de su reporte se hereda sin modificación.

## 2. Incompatibilidad corregida

El diseño original especificó en su sección 21 una class privada con un
`Buffer<uint8>` de output como field. TEXT-UTF8-BUILDER-V1 cerró la
materialización general mediante esta API exacta:

```aether
public string fromUtf8(ref Buffer<uint8> bytes, usize length);
```

Publicar el resultado del serializer class exigiría formar conceptualmente:

```aether
std.Text.fromUtf8(&serializer.output, serializer.outputLength)
```

En ese modelo, `serializer.output` es storage interior del payload de una
class. CLASS-HANDLE-REFERENCES-V1 admite `ref C` y `ref C?` sobre slots que
contienen handles directos, pero mantiene fuera del lenguaje los interior
borrows de fields o elements de class. La expresión requerida no es por tanto
un borrow del handle `serializer`: es un borrow prohibido de su field
interior.

No se corrige esa incompatibilidad ampliando references, agregando un getter
que escape storage interior, copiando el Buffer ni privilegiando al backend.
Tampoco se cambia la firma ya implementada de `std.Text.fromUtf8`.

## 3. Decisión normativa única

El serializer privado del backend SVG es un **struct local owning**, no una
class. Su forma conceptual es:

```aether
struct SvgSerializer {
    Buffer<uint8> output;
    Buffer<SerializerState> states;
    Buffer<Rect> clips;
    usize outputLength;
    // current state, traversal counters and clip IDs
}
```

`render` crea una instancia local owning de `SvgSerializer`. Esa instancia:

- posee sus tres Buffers y el resto de su estado temporal;
- vive únicamente durante la invocación de `render`;
- no escapa, no se retorna, no se guarda en `Scene` ni se entrega a callbacks;
- no necesita identidad de objeto, Alias, ARC ni lifecycle compartido; y
- se limpia por el lifecycle ordinario de sus fields en salida normal o
  excepcional.

Las proyecciones de un struct local permiten formar el borrow call-scoped
ordinario que exige la API general:

```aether
std.Text.fromUtf8(&serializer.output, serializer.outputLength)
```

`fromUtf8` valida y copia el prefijo exacto a un nuevo owner `string`; no
consume ni adopta el backing del Buffer. Por ello el string retornado no
depende de la vida del serializer y los Buffers pueden destruirse al terminar
`render`.

La declaración exacta de helpers, constructors y métodos privados queda para
la implementación, pero no puede cambiar esta categoría de ownership ni
introducir una class wrapper equivalente.

## 4. `Scene` y frontera de references

`graphics.Scene` sigue siendo una class inmutable y la API pública permanece:

```aether
public string render(ref graphics.Scene scene);
public void save(ref graphics.Scene scene, ref string path);
```

`ref Scene` es el borrow compartido del handle directo que
CLASS-HANDLE-REFERENCES-V1 admite. El serializer recorre la Scene mediante sus
accessors read-only, no la retiene, copia ni muta y no forma references a sus
fields interiores.

Esta enmienda no habilita interior borrows de class, no relaja sus gates y no
crea un precedente para ellos. Usa solamente ownership local y
proyecciones/borrows ordinarios de struct ya admitidos.

## 5. Efecto sobre allocations y complejidad

Se elimina únicamente la allocation de la instancia class que el ARCH había
previsto para el serializer. Permanecen el crecimiento geométrico del output,
las allocations de los Buffers de state y clips cuando correspondan, los
temporales escalares `str(float64)` documentados y la materialización final
del string.

La política y las cotas continúan siendo:

```text
tiempo: O(commands + payload visitado + output bytes)
peak:   O(output bytes + nesting depth + clip count)
```

No aparecen copias de arenas Scene, listas intermedias de geometry,
concatenación incremental ni adoption del backing del Buffer.

## 6. Contratos no modificados

La enmienda no cambia:

- la API pública `render`/`save` ni su modelo de ownership;
- el perfil y formato SVG/XML, los bytes canónicos o el painter order;
- la state machine, los dos traversals, la numeración de clip IDs o clipping;
- numeric formatting, colors, escaping XML/CSS, texto o mappings de fonts;
- el modelo de errores, incluyendo `GraphicsTextException` y
  `GraphicsIoException`;
- determinism O0/O2, goldens, validación estructural o qualification;
- complejidad asintótica; ni
- la política de allocations, salvo eliminar la allocation class del
  serializer.

En particular, no se modifica graphics foundation, `Scene`, `Command`, std,
compiler o runtime. No se requiere otro milestone de lenguaje.

## 7. Relación con el bloqueo y secuencia

TEXT-UTF8-BUILDER-V1 ya cerró la capability general que motivaba el estado
BLOCKED del ARCH original. Esta enmienda adapta el estado privado del backend a
la frontera real de esa capability sin abrir el lenguaje.

La secuencia habilitada continúa directamente con:

```text
GRAPHICS-SVG-BACKEND-V1
```

Ese milestone deberá implementar y calificar el contrato original con esta
única sustitución de representación. Esta enmienda no declara implementado el
backend; declara coherente y cerrada la corrección arquitectónica.

**Estado final: CLOSED.**
