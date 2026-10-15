# GENERIC-INFERENCE-REF-ARGUMENT-V1 — reporte

Implementado y calificado en `compiler-next`. Cierre: 2026-10-15.

## Resultado

La inferencia de una llamada genérica ahora obtiene el tipo concreto de un
argumento `Place` antes de adaptarlo a un parámetro `ref`. Por ejemplo,
`Vector<double,Column>` frente a `ref Vector<T,Column>` aporta la restricción
`T = double`; después, la adaptación ordinaria materializa el préstamo shared
del mismo `Place`.

La corrección es general. No reconoce Matrix, Vector, SVD, packages concretos
ni nombres de funciones, y no infiere desde el retorno para ocultar el fallo.
No se modificaron `linearAlgebra`, `SVD<T>`, las reglas de ownership/borrow ni
la sintaxis genérica.

## Reducción

Se comparó el siguiente consumer con owner local, field de struct no genérico,
field de struct genérico y un aggregate `Factor<T>` equivalente a `SVD<T>`:

```aether
int consume<T: Storable>(ref Vector<T,Column> value) {
    return int(dimension(*value));
}
```

Antes de la corrección, el owner local se admitía. Una proyección field
no-`Copy` fallaba durante la inferencia con `E0293 partial move`, tanto si el
aggregate era genérico como si no. Al envolver las firmas Row/Column en un
overload set, los errores internos descartaban todos los candidatos y se
presentaba `E0460 no matching overload`. Los mismos cuatro casos con
`<double>` explícito funcionaban.

La matriz demuestra que:

- la adaptación owner → `ref` participa en el defecto;
- la proyección field no-`Copy` es el disparador mínimo observable;
- la sustitución de un aggregate genérico no es necesaria para reproducirlo;
- `Column` se conserva correctamente y no es la causa;
- overload resolution y package qualification sólo hacen visible el fallo
  como ausencia de candidato; no son la causa;
- `SVD<T>` y std no tienen comportamiento especial relevante.

## Causa raíz y fase corregida

El pipeline ya tenía las piezas correctas por separado:

1. candidate discovery encontraba las declaraciones correctas;
2. `infer_generic_arguments` sabía retirar exactamente un `ref` shared del
   patrón y unificar recursivamente `Vector<T,Column>` con
   `Vector<double,Column>`;
3. `adapt_call_argument` sabía crear un `CallScopedSharedBorrow` desde un
   `HirPlace` con el pointee exacto;
4. la sustitución nominal de fields producía correctamente
   `Vector<double,Column>` para `Holder<double>.value` y `SVD<double>.S`.

La brecha estaba entre 2 y 3, dentro de la adquisición preliminar de argumentos
de `call_id`. Para inferir `T`, el frontend llamaba a `expression(field, None)`.
Eso bajaba la proyección como lectura por valor antes de conocer la adaptación
`ref`; en un field owner no-`Copy`, la lectura se rechazaba inmediatamente como
partial move. La fase posterior que primero intenta resolver un `Place` nunca
llegaba a ejecutarse. Las aplicaciones explícitas evitaban por completo esa
precomprobación de inferencia, por eso funcionaban.

La fase corregida es generic constraint collection / argument type
acquisition. Si el patrón es `ref` shared y el argumento es un owner `Place`,
se conserva un `PrecheckedCallArgument::SharedBorrowPlace` y se unifica usando
su `place.ty`. La adaptación consume luego ese mismo `HirPlace`, verifica
igualdad exacta con el pointee sustituido y emite el préstamo de llamada. Esto
evita tanto el move ficticio como volver a analizar índices o dereferences con
efectos.

## Seguridad y casos negativos

La ruta nueva sólo se activa para un parámetro `ref` shared y un argumento
resoluble como owner `Place`. No se aplica a `ref mut`, no elimina
orientaciones nominales, no ejecuta coerciones y exige que el tipo del Place
sea exactamente el pointee concreto después de sustituir los genéricos.

La qualification mantiene rechazo para:

- `Vector<_,Row>` cuando sólo existe el parámetro Column;
- elementos incompatibles, incluidos conflictos inferidos entre argumentos;
- `ref mut` desde una fuente shared;
- rvalues donde `ref mut` exige un Place explícito;
- parámetros genéricos sin ninguna restricción inferible;
- overloads realmente ambiguos por tipo de retorno ausente.

No se elige un candidato arbitrariamente y no se relajan moves, mutabilidad ni
conversiones.

## Regresión real

El test de integración carga el package real `linearAlgebra`, obtiene
`var factor = la.svd(A)` y compila sin argumentos de tipo explícitos:

```aether
Matrix<double> Sigma = mat.diagonalMatrix(factor.S);
Matrix<double> V = mat.transposeCopy(factor.Vt);
```

También se cubren overloads Row/Column mediante llamada local y llamada
package-qualified, además de la matriz A–E en fixtures independientes.

## Impacto sobre IR

No hay cambios de esquema ni nuevas operaciones HIR, MIR, SSA o LLVM. Una
llamada corregida usa el `CallScopedSharedBorrow` que ya representaba la forma
explícita/inferida válida, y conserva su `EndBorrow` normal en lowering. El
cambio ocurre únicamente antes de la selección final del candidato y reutiliza
la adaptación existente.

## Archivos

- `compiler-next/crates/aether-frontend/src/hir.rs`: adquisición de tipo desde
  Place, conservación del Place precomprobado y adaptación shared posterior.
- `compiler-next/crates/aether-driver/tests/generic_inference_ref_argument_v1.rs`:
  matriz mínima, overload/package qualification, negativos e integración SVD.
- `docs/architecture/GENERIC_INFERENCE_REF_ARGUMENT_V1_REPORT.md`: este informe.

No se creó documento de arquitectura previo: el cambio repara una capacidad
ya esperada del lenguaje.
