# FORMAT-BORROW-V1 — implementation report

Estado: **IMPLEMENTADO**, 2026-09-28.

## Alcance

La interpolación distingue ahora `formatted_type`, `access` (`CopyValue` o
`SharedObservation`) y `conversion`. Los escalares Copy conservan captura por
valor. Owners non-Copy, fields, referencias shared/mutables y temporales se
observan mediante `FormatScopedSharedBorrow`; el peeling de referencias termina
en el primer pointee no-reference y nunca imprime una dirección.

Un field ordinario non-Copy fuera de interpolación continúa siguiendo E0293 y
un tipo subyacente no interpolable continúa siguiendo E0340.

## HIR, MIR y SSA

HIR conserva `FormatSiteId`, índice de fragmento, pointee/reference `TypeId`,
origen (`Owner`, `Ref`, `RefMut`) y source (`Place`, `Temporary` o
`ProjectedTemporary`). Los holes observacionales sólo admiten una referencia
shared exacta al `formatted_type`.

MIR baja el source una vez, estabiliza roots temporales, emite `Borrow` con
`FormatBorrowMetadata`, ejecuta `Interpolate`, emite `FormatEndBorrow` y sólo
después destruye el root temporal completo. Los cleanup de unwind cierran los
borrows FORMAT antes de los drops. SSA conserva la misma metadata y rechaza
escapes por usos ajenos, phi o ausencia de interpolación/EndBorrow compatible.

LLVM recibe únicamente la referencia ya tipada y verificada; no decide
ownership, no clona owners y trata `FormatEndBorrow` como marcador posterior a
verificación.

## Lifecycle y diagnóstico

Los holes se capturan exactamente una vez y de izquierda a derecha. El borrow
permanece activo durante count/write, termina antes de publicar el string y un
`ref mut T` conserva su capacidad mutable. El análisis de ownership mantiene
activos los borrows de holes anteriores al analizar los posteriores, de modo
que una mutación invalidante conserva el diagnóstico normal.

Las pruebas cubren owners repetidos, fields, referencias shared/mutables,
zero-shapes y roots temporales completos, incluidos fields proyectados de un
rvalue. Los verificadores HIR/MIR/SSA reconstruyen identidad, tipos,
provenance, uso único por interpolación y cierre de región.

## Interacción y dogfood LU

MATH-FORMAT-V1 aporta la conversión de `Matrix`/`Vector`; FORMAT-BORROW-V1
aporta exclusivamente el acceso observacional. El consumidor real de
`linearAlgebra` imprime `factor.L` y `factor.U` y reutiliza después el mismo
`factor` con `solve` y `det`, comprobando resultados y ausencia de partial move.

