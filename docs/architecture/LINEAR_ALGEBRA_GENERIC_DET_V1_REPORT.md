# LINEAR-ALGEBRA-GENERIC-DET-V1 — reporte de bloqueo

Estado: **BLOQUEADO SIN CAMBIOS PRODUCTIVOS**, 2026-09-28.

Autoridad normativa:

- [NUMERIC_CAPABILITIES_ARCH_1](NUMERIC_CAPABILITIES_ARCH_1.md)
- [NUMERIC_CAPABILITIES_V1_REPORT](NUMERIC_CAPABILITIES_V1_REPORT.md)
- [LINEAR_ALGEBRA_DET_V1_REPORT](LINEAR_ALGEBRA_DET_V1_REPORT.md)
- [LINEAR_ALGEBRA_GENERIC_CONSTRUCTORS_V1_REPORT](LINEAR_ALGEBRA_GENERIC_CONSTRUCTORS_V1_REPORT.md)

## Resultado de la auditoría obligatoria

La ruta de factor puede expresarse con el kernel requerido:

```aether
T det<T: IEEEFloat>(ref LU<T> factor) {
    // los cuatro shape guards DET-V1, en su orden actual
    T result = 1;
    if ((*factor).permutationSign < 0) {
        result = -result;
    }
    // producto diagonal en orden ascendente
}
```

`IEEEFloat` aporta `One`, `Negate` y `Mul`, por lo que esta ruta no necesita un
cast integer-to-`T`, un helper de signo ni una rama por precisión.

La ruta owning requerida no es tipable mientras `lu` conserve únicamente sus
dos overloads concretos. Se probó el body normativo exacto:

```aether
T det<T: IEEEFloat>(Matrix<T> A) {
    shapeGuard(rows(A) == columns(A));
    LU<T> factor = lu(A);
    return det(factor);
}
```

con los overloads vigentes:

```aether
LU<float64> lu(Matrix<float64> A);
LU<float32> lu(Matrix<float32> A);
```

`compiler-next/target/debug/aether check linearAlgebra` falla durante el análisis
paramétrico, antes de crear instancias, con:

```text
error[E0460] (semantic): no matching overload for `lu`; candidates:
  - lu(Matrix<float64>) -> LU<float64>
  - lu(Matrix<float32>) -> LU<float32>
```

El resolver actual exige elegir una identidad de declaración al construir el
HIR paramétrico. No representa un call a un overload set pendiente que pueda
resolverse después de sustituir `T`; la monomorfización sólo sustituye tipos y
reifica las operaciones capability de calls ya resueltos.

## Decisión de alcance

No se dejó una migración parcial: el milestone exige exactamente dos `det`
públicos y ambas rutas deben ser genéricas. Conservar wrappers concretos para
la ruta Matrix, duplicar el body por precisión, consultar `TypeId`, agregar
witnesses/vtables o reconocer `linearAlgebra.lu` en el compilador violaría la
superficie y las restricciones estructurales del milestone.

Tampoco se migró LU anticipadamente. Esa sería la salida arquitectónica
natural ya prevista por `NUMERIC_CAPABILITIES_ARCH_1`, pero ensancha de forma
material el scope solicitado y altera un kernel numérico que este milestone
ordena mantener intacto.

En consecuencia, `linearAlgebra/src/lib.ae`, sus tests y el comportamiento
DET-V1 permanecen sin cambios. No corresponde afirmar qualification de
`LINEAR-ALGEBRA-GENERIC-DET-V1` ni ejecutar la matriz final como si la
implementación existiera.

## Condición de desbloqueo

El milestone puede reabrirse cuando ocurra una de estas dos decisiones
arquitectónicas explícitas:

1. migrar primero `lu` a `LU<T> lu<T: IEEEFloat>(Matrix<T> A)`, conforme al
   plan de arquitectura; o
2. especificar e implementar en el lenguaje una representación general de
   overload resolution diferida para cuerpos paramétricos, con reglas de
   exhaustividad, ambigüedad, ownership e identidad de símbolo y qualification
   independiente de `linearAlgebra`.

La primera alternativa es acotada al roadmap numérico. La segunda no es un
arreglo local para `det`: sería una nueva capacidad general del frontend, HIR,
verificación y monomorfización.

## Validación efectuada

Se restauró completamente el intento sobre `linearAlgebra/src/lib.ae`. El
único cambio del milestone es este reporte de bloqueo. Se validó el diff con:

```text
git diff --check
```

