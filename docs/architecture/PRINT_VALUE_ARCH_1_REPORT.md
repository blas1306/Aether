# PRINT-VALUE-ARCH-1 — architecture milestone report

Estado: **ARQUITECTURA CERRADA; NO IMPLEMENTADA**, 2026-09-29.

El diseño normativo está en
[PRINT_VALUE_ARCH_1.md](PRINT_VALUE_ARCH_1.md). Este milestone sólo agrega
documentación; no modifica compilador, runtime, stdlib, tests ni ejemplos.

## Resultado

Se cerró `print(value)`/`println(value)` como una familia Core de exactamente un
argumento cuya admisión procede de la autoridad FORMAT activa. La notación
conceptual `T: FormatAdmitted` no crea una capability pública. Strings,
scalars, referencias y owners matemáticos son aceptados exactamente donde un
hole `${value}` ya los acepta; views y cualquier tipo fuera del perfil siguen
rechazados.

La igualdad central es byte-exacta:

```text
print(value)   == print("${value}")
println(value) == println("${value}")
```

para la representación del valor. `println` agrega después exactamente un LF.
String continúa escribiéndose sin quotes ni escaping nuevo, y las literals
conservan su decodificación ordinaria de escapes.

## Decisiones de arquitectura

- Se extrae/reutiliza una única consulta de admisión que produce
  `StringBorrow`, `CanonicalScalarFormat` o la receta
  `MathematicalAggregateFormat`. `str` no se usa como sustituto incompleto de
  esa autoridad.
- `string` mantiene el output borrowed actual y no paga una allocation nueva.
- Un valor non-string se representa como un `StringOp::Interpolate` interno de
  un hole, se publica como un único owner exacto y luego usa el stdout Core
  existente. Streaming directo queda diferido.
- `FormatScopedSharedBorrow` conserva el acceso observacional. Owners y fields
  non-Copy no se mueven, clonan ni dejan partial move; referencias imprimen el
  pointee y no una address.
- Un rvalue directo se estabiliza una vez. Su borrow termina al publicar el
  string, pero el root permanece vivo hasta completar el write; éxito y
  `IOException` destruyen string y root exactamente una vez.
- No hacen falta nuevos opcodes MIR/SSA. HIR `StringOutput` sólo requiere
  metadata contextual `ExistingString | DirectFormat` para verificar el plan y
  su extensión de cleanup sin alterar una interpolación source ordinaria.
- El CoreCall/backend/runtime de output sigue recibiendo `string`. No se agrega
  ABI genérica, reflection, `Any`, TypeId dispatch, fallback ni formatter por
  tipo dentro de IO.

## IO, errores y costes

La frontera length-aware y el modelo IO-V1 permanecen intactos: `print` no
agrega bytes, `println` agrega `0x0A`, U+0000 es contenido, y un fallo de stdout
produce el mismo `std.IO.IOException`, incluidos write parcial y cleanup por
landing pad.

El coste aceptado para un valor non-string es el mismo owner intermedio que
produce `"${value}"`: medición checked, una allocation final exacta y emisión
con los primitives FORMAT existentes. No hay strings por elemento ni copia
owning del source. Literal/lvalue string conserva cero allocations adicionales.

## Diagnóstico y evolución

Un argumento no formateable falla en la misma frontera E0340 que un hole, con
span del argumento y wording adaptado a `print`/`println`. Aridad múltiple sigue
fuera de alcance; no hay debug repr, address output ni conversión implícita
general a string.

Un milestone posterior deberá diseñar por separado output multi-argument:
aridad, heterogeneidad, orden, stabilization, publicación, unwind y
allocations. Mantener `print`/`println` como identidades Core de familia permite
esa evolución sin cambiar el contrato de aridad uno.

## Qualification requerida para implementación

El vertical futuro deberá comparar bytes directos contra interpolación para
integers, floats, bool, char, string, Row/Column/Matrix y fields LU; comprobar
owner usable, ausencia de partial move, temporales y projected temporaries,
stdout failure, O0/O2, reachability y rechazos. Dumps y corruption tests deben
demostrar reutilización de FORMAT/FORMAT-BORROW y ausencia de Clone, Alias,
dispatch de tipo u opcodes especializados.

## Validación del milestone

- entregables de arquitectura creados;
- alcance explícitamente marcado como no implementado;
- ningún archivo de código modificado;
- validación mecánica: `git diff --check`.
