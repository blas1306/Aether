# FORMAT-BORROW-ARCH-1 — architecture milestone report

Estado: **COMPLETADO COMO ARQUITECTURA; SIN IMPLEMENTACIÓN**, 2026-09-28.

Documento normativo:
[FORMAT_BORROW_ARCH_1.md](FORMAT_BORROW_ARCH_1.md).

## Resultado

Se cerró una semántica general de formatting observacional. Interpolar un valor
que el perfil FORMAT activo ya reconoce no transfiere ownership. Los scalars
Copy pueden conservar su captura by-value; un owner non-Copy y cualquier
proyección prestable usan shared borrow contextual; `ref T` observa T; `ref mut
T` hace un reborrow shared temporal sin perder su capacidad mutable posterior.

El cambio se limita a `Interpolation`. Una lectura owning ordinaria como:

```aether
Matrix<float64> L = factor.L;
```

puede continuar fallando con E0293. No se diseñaron partial moves, Clone
implícito ni una excepción específica para Matrix o LU.

## Decisiones cerradas

| Área | Decisión |
|---|---|
| owner non-Copy | shared borrow; nunca Move, Clone, Alias o retain defensivo |
| field/nested field | borrow del Place completo antes de aplicar reglas ordinarias de consumo |
| `ref T` | formatting del pointee T; nunca pointer/address |
| `ref mut T` | reborrow shared limitado a FORMAT; mutabilidad disponible tras `EndBorrow` |
| nested refs | peeling contextual hasta el tipo no-reference, con evaluación única y provenance |
| rvalue owner | root temporal estabilizado, borrow, EndBorrow y Drop exactamente una vez |
| field de rvalue | se conserva el owner base completo; no se extrae/mueve el field |
| lifetime | desde evaluación del hole hasta su último read de medición/emisión; nunca cruza la expresión `Interpolation` |
| orden | holes exactamente una vez y de izquierda a derecha, igual que FORMAT-V1 |
| conflictos | checker ordinario de Places/provenance; FORMAT no salta aliasing |
| output | sin caso especial: `print`/`println` siguen recibiendo string |
| costos | cero copia/clone/allocation de owner atribuible a formar el borrow |

## Representación elegida

HIR hará explícito `FormatScopedSharedBorrow` con `FormatSiteId`, fragment index,
TypeIds, source/projections, origin y provenance. Cada hole separará:

- `formatted_type`: tipo subyacente que debe ser interpolable;
- `access`: `CopyValue` o `SharedObservation`;
- `conversion`: estrategia existente para producir bytes.

No se reutiliza literalmente `CallScopedSharedBorrow`, porque una interpolación
no tiene argument slot y la región puede abarcar holes posteriores y las dos
pasadas count/write. Sí se reutiliza su protocolo probado en capas inferiores:
MIR y SSA contienen `Borrow`/`EndBorrow`, roots temporales y cleanup normal o de
unwind, con metadata de consumer FORMAT y verificadores independientes.

LLVM sólo recibe el acceso prestado ya verificado. No decide ownership y no se
agrega helper runtime para Matrix/LU.

## Temporales, cleanup y orden

`makeT()` se materializa una sola vez en un root owning. Para
`makeStruct().field`, el root es el struct completo y el borrow selecciona el
field. El root vive hasta terminar el último read del fragmento y se destruye
después de `EndBorrow`.

Ante una language exception en un hole posterior, se terminan los borrows y se
destruyen roots inicializados en orden inverso. Un initializer fallido no
publica root. Los traps abortivos de size/OOM conservan la política FORMAT-V1 y
no adquieren una promesa nueva de cleanup.

La estrategia de dos pasadas de FORMAT-V1 obliga a mantener un borrow mientras
el operand todavía pueda ser leído para count o write. Todos los borrows cierran
antes de que `Interpolation` entregue el owner string, de modo que el statement
siguiente nunca hereda un borrow contextual.

## Interpolabilidad y diagnóstico

La regla es sobre el tipo subyacente: `T`, `ref T` y `ref mut T` comparten la
misma respuesta de interpolabilidad. Una referencia a `Unknown` no vuelve
formateable a `Unknown`; sigue produciendo E0340. E0293 se conserva para moves
ordinarios de fields non-Copy, y los conflictos reales conservan el diagnóstico
normal del borrow checker.

La auditoría confirmó que el FORMAT-V1 actualmente calificado sólo incluye
`string` y scalars. Matrix y otros tipos matemáticos están explícitamente fuera
de ese perfil. Por ello este milestone no puede, por sí solo, hacer ejecutable
el ejemplo LU: elimina el move/copy accidental cuando `Matrix<T>` ya sea
interpolable, pero no diseña su representación textual. Esta separación evita
ampliar silenciosamente FORMAT bajo un milestone de ownership.

## Qualification futura

El vertical de implementación deberá cubrir owner repetido, fields simples y
anidados, dos fields del mismo agregado, refs shared/anidadas, ref mut con uso
mutable posterior, owners y fields temporales, orden/side effects, unwind,
conflictos reales, E0340, E0293, dumps/corruptions HIR-MIR-SSA, lifecycle sin
clone/retain y O0/O2.

Cuando `Matrix<float64>` esté en el perfil FORMAT activo, será obligatorio el
dogfood:

```aether
var factor = linearAlgebra.lu(A);
println("${factor.L}");
println("${factor.U}");
solve(factor, b);
```

y `det(factor)` donde sus firmas y el orden de consumos lo permitan. Los dumps
deberán demostrar borrow/observation y ausencia de `MoveField`, Clone y estado
partial-move.

## Orden de implementación acordado

1. separar consulta de interpolabilidad, tipo formateado, modo de acceso y
   conversión;
2. resolver contextualmente Places, refs y temporales en HIR;
3. verificar `FormatScopedSharedBorrow` sin escapes;
4. materializar regiones y cleanup en MIR;
5. preservar y verificar metadata en SSA;
6. adaptar codegen sólo después del contrato de capas altas;
7. calificar negativos, lifecycle, orden, O0/O2 y regresiones;
8. habilitar dogfood LU sólo con Matrix formatting ya disponible.

No se modificó código, runtime, tests ni `linearAlgebra` en este milestone.

