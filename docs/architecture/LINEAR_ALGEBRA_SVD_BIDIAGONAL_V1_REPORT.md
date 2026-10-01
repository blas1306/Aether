# LINEAR-ALGEBRA-SVD-BIDIAGONAL-V1 — reporte de implementación

Estado: **IMPLEMENTADO**, 2026-10-01.

Autoridad normativa:

- [LINEAR-ALGEBRA-SVD-BIDIAGONAL-ARCH-1](LINEAR_ALGEBRA_SVD_BIDIAGONAL_ARCH_1.md);
- [LINEAR-ALGEBRA-SVD-ARCH-1](LINEAR_ALGEBRA_SVD_ARCH_1.md);
- [LINEAR-ALGEBRA-STABLE-NORM-ARCH-1](LINEAR_ALGEBRA_STABLE_NORM_ARCH_1.md).

## Resultado

`linearAlgebra/src/lib.ae` contiene ahora el vertical privado que reduce un
workspace owning a bidiagonal upper compacta y materializa el seed thin para
la futura iteración QR. No se agregó API pública ni `svd`.

Un único kernel `reduceTallBidiagonal<T: IEEEFloat>` recibe siempre una vista
`M×N`, `M>=N`. Tall/square usa `matrix_view_mut`; wide usa exclusivamente
`transpose_view_mut`, sin transpose owning. `d`, `e`, `tauLeft` y `tauRight`
se crean una vez con dimensiones `N`, `max(N-1,0)`, `N` y `max(N-1,0)`.
El workspace conserva los pivots y tails implícitos y `d/e` se escriben durante
la reducción, sin pase de extracción.

La formación Householder conserva el orden normativo basado en
`pivotRatio=x1/beta` y `denominatorRatio=pivotRatio-1`; no forma `x1-beta`.
Las normas de columna y fila delegan exclusivamente en `stableNormRange`, con
la fila observada mediante `transpose_view`. `tau==+0` omite por completo cada
aplicación.

## Materialización y ownership

Los cuatro caminos materializan directamente las shapes thin:

- Upper: `U=QL[:,1..k]`, seguido de `Vt=QR^T`;
- TransposedUpper: `U=QR`, seguido de `Vt=QL[:,1..k]^T`.

No se crean `B`, `H`, `G`, factors full, transposes owning, owners por
reflector ni allocations dentro de inner loops. El entry preserving copia la
entrada una vez; el entry owning reutiliza su Matrix como workspace. En el
caso no vacío owning se observaron exactamente siete allocations/frees:
workspace, `U`, `Vt` y los cuatro vectores. Extents cero no crean backing.

Los aggregates, el tag de orientación y todos los helpers son module-private.
La representación privada de orientación es un tag de un bit: `false` equivale
a `Upper` y `true` a `TransposedUpper`. Esto evita ampliar la superficie de
enums del lenguaje y conserva exactamente la frontera matemática requerida.

## Gap mínimo del frontend

El branch wide expuso una falsa alarma de alias effects: `may_contain_list`
trataba todo parámetro genérico como potencial contenedor de `List`, incluso
cuando `T: IEEEFloat` garantiza `Copy`. Se refinó únicamente esa consulta:
un tipo garantizado `Copy` no puede contener un owner `List`. Una prueba
unitaria cubre la implicación y el kernel genérico transpuesto la ejercita de
extremo a extremo. No se agregó sintaxis, lowering ni ABI.

## Qualification

La prueba white-box
`linear_algebra_svd_bidiagonal_v1.rs` cubre float32/float64 y O0/O2 para
square, tall, wide, `m×1`, `1×n`, cero, rank deficiency, filas repetidas,
signed zeros, huge/tiny y los tres zero extents. Comprueba shapes,
orientación, pivots/taus/layout, reconstrucción `U*B*Vt` o `U*B^T*Vt`,
`U^T U`, `Vt Vt^T`, privacidad, monomorfización y allocations.

Validación ejecutada:

```text
cargo test -p aether-frontend
cargo test -p aether-driver --test linear_algebra_stable_norm_v1
cargo test -p aether-driver --test linear_algebra_qr_v1
cargo test -p aether-driver --test linear_algebra_svd_bidiagonal_v1
cargo fmt --all
```

Permanecen fuera de scope la iteración QR bidiagonal, deflation, shifts,
Givens, normalización de signos, ordering, singular values y la API `svd`.
