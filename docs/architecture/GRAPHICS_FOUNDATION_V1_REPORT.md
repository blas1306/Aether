# GRAPHICS-FOUNDATION-V1 — reporte de implementación

Estado: **BLOCKED**, 2026-10-19.

Autoridad normativa:

- [GRAPHICS-FOUNDATION-ARCH-1](GRAPHICS_FOUNDATION_ARCH_1.md);
- [GRAPHICS-FOUNDATION-ARCH-1-REPORT](GRAPHICS_FOUNDATION_ARCH_1_REPORT.md);
- [AETHER-V1-SEMANTIC-CONTRACT](AETHER_V1_SEMANTIC_CONTRACT.md);
- [MODULE-STD-ARCH-1](MODULE_STD_ARCH_1.md);
- [PACKAGE-MANAGER-ARCH-1](PACKAGE_MANAGER_ARCH_1.md);
- [TEXT-BYTE-ACCESS-ARCH-1](TEXT_BYTE_ACCESS_ARCH_1.md).

## Resultado

La implementación se detuvo antes de crear la OAL `graphics`. La regla de
language gap de GRAPHICS-FOUNDATION-ARCH-1 exige detener el milestone si los
fields privados `Buffer<Command>`, `Buffer<PathVerb>` o
`Buffer<TextRecord>` no están admitidos realmente. El frontend vigente los
rechaza con `E0401`.

No se modificaron compiler, runtime, Core ni std. Tampoco se introdujo una
representación alternativa con `List`, arrays paralelos, nodos, aliases,
wrappers, fields públicos o una allowlist para `graphics`, porque cualquiera
de esos caminos cambiaría la arquitectura cerrada o el contrato de storage.

## Reproducción mínima

Los tipos cerrados sí son elementos válidos de `Buffer<T>` en storage local.
Este probe pasa `aether check`:

```aether
struct Point { float64 x; float64 y; }
enum PathVerb { MoveTo(Point), Close }
struct TextRecord { Point position; usize index; }
enum Command { DrawPoint(Point), DrawText(usize) }

int main() {
    Buffer<Command> commands =
        Buffer<Command>(0, Command.DrawPoint(Point(0.0, 0.0)));
    Buffer<Point> points = Buffer<Point>(0, Point(0.0, 0.0));
    Buffer<PathVerb> verbs = Buffer<PathVerb>(0, PathVerb.Close);
    Buffer<TextRecord> records =
        Buffer<TextRecord>(0, TextRecord(Point(0.0, 0.0), 0));
    Buffer<uint8> bytes = Buffer<uint8>(0, uint8(0));
    return 0;
}
```

El mismo storage como field privado de clase falla:

```aether
class Probe {
    Buffer<Command> commands;

    public init() {
        commands =
            Buffer<Command>(0, Command.DrawPoint(Point(0.0, 0.0)));
    }
}
```

Diagnóstico observado:

```text
error[E0401] (semantic): class field requires a scalar/Copy value,
private Buffer<int>, or a private non-self concrete class owner
```

La restricción está en la resolución de fields de clase de
`compiler-next/crates/aether-frontend/src/hir.rs`: la excepción estrecha
comprueba literalmente que el elemento de `Buffer` sea `int`. Por eso también
rechaza `Buffer<Point>`, `Buffer<PathVerb>`, `Buffer<TextRecord>`,
`Buffer<Command>` y `Buffer<uint8>` como fields, aunque sus instanciaciones
locales sean válidas.

## Capacidad faltante aislada

El milestone previo necesario es una capacidad general de lenguaje para
**fields privados `Buffer<T>` en classes cuando `T` satisface las reglas
ordinarias de storage/lifecycle**. Debe cerrar frontend, lowering, layout,
replacement, Drop y qualification O0/O2 sin una excepción por package o por
los nombres de los tipos gráficos.

Esa capacidad es necesaria dos veces por la arquitectura vigente:

- `SceneBuilder` debe poseer cinco arenas growable privadas;
- `Scene` debe poseer los cinco backings exactos privados e inmutables.

Permitir únicamente `Buffer<int>` no alcanza: cambiar los payloads a integers
o descomponerlos en arrays paralelos alteraría la representación nominal,
atomicidad, ownership y costes cerrados por el ARCH.

## Qualification no ejecutada

No corresponde ejecutar la qualification funcional, de allocations, IR ni
O0/O2 de graphics mientras el package normativo no puede expresarse. Las gates
globales solicitadas tampoco pueden convertir este estado en `CLOSED`.

Cuando el milestone de lenguaje anterior esté implementado y qualified,
GRAPHICS-FOUNDATION-V1 debe retomarse desde la superficie cerrada, sin reutilizar
este probe como producto y sin cambios gráficos en compiler/runtime.
