# MATRIX-ADD-V1 — reporte

Estado: **IMPLEMENTADO**, 2026-09-27.

Autoridad normativa:

- [DYNAMIC_SHAPES_AND_SLICES_ARCH_1](DYNAMIC_SHAPES_AND_SLICES_ARCH_1.md)
- [DYNAMIC_SHAPES_AND_SLICES_ARCH_1_REPORT](DYNAMIC_SHAPES_AND_SLICES_ARCH_1_REPORT.md)
- [MATRIX_DYNAMIC_DESCRIPTOR_V1_REPORT](MATRIX_DYNAMIC_DESCRIPTOR_V1_REPORT.md)
- [FILLED_INIT_V1_REPORT](FILLED_INIT_V1_REPORT.md)

## Superficie y semántica elegida

La única superficie nueva es el método intrínseco estructural:

```aether
A.add(rowVector);
A.add(columnVector);
```

`Row` agrega una fila y `Column` agrega una columna. El receiver debe ser un
`Matrix<T>` owner en un Place escribible. El argumento debe ser exactamente un
owner `Vector<T,O>` con el mismo `T`; Matrix, Array/List, VectorView y
conversiones de orientación no participan.

Se eligió **consumo uniforme** del Vector, incluso para `T:Copy`. La alternativa
copy-preserving reduciría la sorpresa en usos pequeños de escalares, pero
introduciría dos regímenes observables para la misma escritura: préstamo y copia
implícita para `T:Copy`, transferencia para `T` no-Copy. El modelo actual ya
trata `Vector` como owner move-only independientemente de su elemento. Mantener
ese modelo da un diagnostic único de use-after-move, una operación IR única y
un runtime que siempre transfiere cada slot una vez. El costo real tampoco
desaparece en la alternativa: el vector debe recorrerse y sus valores copiarse;
la elección sólo conservaría su backing y obligaría a una segunda vida lógica.

Por ello V1 conserva:

```aether
A.add(v);
// v está moved, también si T:Copy
```

No se agregó una segunda API pública. Para `T` no-Copy nunca aparece una copia
implícita.

## Shape, reserva y transacción

La comprobación de extent ocurre antes de aritmética de crecimiento,
allocation, relocation o escritura. `ShapeMismatch` deja ambos owners intactos
hasta el trap. En un `0x0`, el primer vector establece el extent complementario;
esto incluye `Row(0) -> 1x0` y `Column(0) -> 0x1`. Los shapes `mx0` y `0xn`
conservan ambos ejes y siguen las reglas ordinarias.

Cada eje conserva capacity independiente. Al agotarse, la capacity de ese eje
se duplica con mínimo uno y se eleva al required extent si el primer vector es
mayor. El crecimiento:

1. valida shape y todos los incrementos/productos;
2. asigna el nuevo rectángulo de capacity;
3. relocaliza sólo `[0,rows) x [0,columns)` usando el viejo y nuevo stride;
4. transfiere el Vector a la fila o columna nueva;
5. libera ambos backings fuente;
6. construye y retorna al Place el descriptor con metadata nueva.

Sin realloc sólo se transfiere el Vector y se actualiza metadata al final. No se
lee, copia ni destruye padding. Las pruebas fuerzan capacity física mayor que el
shape lógico en ambos ejes y luego vuelven a crecer e indexar el rectángulo.

La estructura LLVM muestra una única rama de crecimiento geométrico por eje,
un loop sobre las celdas lógicas sólo cuando cambia capacity y un loop sobre el
Vector en todo add. Esto da `O(columns)`/`O(rows)` sin realloc,
`O(rows*columns + vector.length)` con realloc y costo amortizado lineal en las
celdas finales.

## Bounds, ownership y provenance

`Matrix.add` exige `T: Storable + Relocatable`; construir, consultar e indexar
un `Matrix<T>` continúa requiriendo sólo `Storable`. La calificación genérica
rechaza un add cuando el bound sólo prueba `Storable`.

La operación lleva `PotentiallyRelocatingMutation` y
`InvalidationShape::WholeBacking`. El análisis de provenance rechaza el add si
permanece vivo un `MatrixView`, `VectorView` de eje o referencia a una celda del
owner. También se rechazan receivers const y dereferences compartidos. Campos y
`ref mut Matrix<T>` sí son Places válidos.

El Vector argumento se marca moved en HIR, se descarga en el ledger de
ownership MIR y se cuenta como consumo en SSA. Su backing se libera después de
transferir todos sus slots, sin ejecutar drop sobre slots ya movidos.

## IR verificable

HIR, MIR y SSA contienen una operación `MatrixAdd` explícita. Conserva:

- `element_type` y orientación estática;
- receiver Place y descriptor Vector, fuentes runtime de shape previa,
  capacities y length;
- `MatrixAddContract::V1`, que fija extracción de metadata, shape resultante por
  orientación, growth geométrico, precheck anterior a mutation y consumo;
- efecto `MatrixAdd` e invalidación `WholeBacking`;
- relocation exacta `MatrixLogicalRectangle`;
- traps `ShapeMismatch`, `AllocationSizeOverflow` y `AllocationFailure` en
  MIR/SSA.

Los tres verificadores fallan cerrados ante corrupción independiente de
orientación/contrato/traps/relocation/tipos. El backend sólo acepta SSA
verificado.

## Cobertura

La suite `matrix_add_v1` cubre Row, Column, primer vector, vectores vacíos,
`0x0`, `mx0`, `0xn`, crecimiento repetido y alternado, caminos con y sin
realloc, padding real, `int`, `float64`, `Buffer<int>` relocalizable no trivial,
campos, returns, O0/O2, mismatch y rechazos de tipo/ownership/provenance.

También cubre el consumo de un Vector con elementos Copy, el rechazo genérico
de un elemento sólo Storable, argumentos Matrix/VectorView/T distinto y
corrupción HIR/MIR/SSA.

## Fuera de alcance preservado

No se modificaron slices, slice assignment, overloads contextuales,
`linearAlgebra`, `zeros`/`ones` ni el workaround de QR. No se agregaron
`addRow` o `addColumn`, queries de capacity ni conversiones nuevas.

## Validación

Se ejecutaron:

```text
cargo test --workspace
cargo fmt --all --check
cargo clippy --workspace --all-targets -- -D warnings
git diff --check
bash compiler-next/tests/run-differential.sh
```
