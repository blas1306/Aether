# Aether — BITWISE-OPERATORS-ARCH-1 report

Estado: **CLOSED; ARQUITECTURA APROBADA; IMPLEMENTACIÓN NO INICIADA**

Fecha: 2026-11-27

Base: `a3e5f124df6bea1e8e7e4073a55f33306d107bbf`

Documento normativo aprobado:
[BITWISE_OPERATORS_ARCH_1](BITWISE_OPERATORS_ARCH_1.md).

## Resultado

Se diseñó una superficie bitwise exclusivamente entera para los diez tipos
nativos y sus aliases transparentes. `^` queda dedicado exclusivamente a XOR;
`**` y `pow` se incorporarán en `EXPONENTIATION-V1`. BITWISE-OPERATORS-V1 no
agrega el token `**` ni asigna semántica de potencia a su tokenización actual.
Borrow `&`/`&mut`, lógica
`&&`/`||`/`!` y la gramática de tipos permanecen separadas.

AND, OR, XOR y NOT se definen sobre patrones de ancho fijo. Signed usa
complemento a dos normativo; el ancho y la interpretación del tipo resultado se
preservan; no hay overflow, trap ni conversión a bool. Las variantes binarias
usan las conversiones ordinarias vigentes y después exigen operandos homogéneos.
No se introducen conversiones signed/unsigned, sized/fixed, integer/float ni
narrowing.

## Decisión de shifts aprobada

El operando izquierdo admite cualquiera de los diez enteros y fija tipo, ancho y
signedness del resultado. El count admite independientemente cualquiera de los
diez enteros. Un count signed negativo o cualquier count `>= width(left)` hace
`ShiftCountOutOfRange` antes de ejecutar un opcode LLVM.

`>>` es `ashr` para signed y `lshr` para unsigned. `<<` es checked: calcula
conceptualmente `left * 2^count` y hace `IntegerOverflow` si el resultado no cabe,
tanto en signed como en unsigned. Esta política se adopta frente al descarte
silencioso porque compone con la aritmética checked vigente. APIs wrapping o
checked explícitas pueden diseñarse después; no pertenecen a V1.

LLVM sólo recibe counts ya probados y normalizados exactamente. Se emiten `and`,
`or`, `xor`, `shl`, `ashr` y `lshr` sin `nsw`, `nuw` ni `exact`. No se usan masked
counts, módulo, freeze ni comportamiento poison como semántica del lenguaje.

## Precedencia

La tabla aprobada, de mayor a menor, es:

```text
postfix/primary
! ~ unary- * & &mut
* / %
+ -
<< >>
&
^
|
< <= > >=
== !=
range :
&&
||
```

Todos los binarios nuevos son asociativos a izquierda; unary es a derecha y range
conserva íntegramente su precedencia y asociatividad no asociativa vigentes.
BITWISE-OPERATORS-V1 no modifica su contrato; cualquier revisión general de
range queda como trabajo futuro independiente. Bitwise queda por encima de
comparación/equality para que
`flags & MASK == 0` signifique `(flags & MASK) == 0`, evitando la lectura
sorprendente de estilo C. `>>` requiere partición contextual como dos cierres `>`
sólo dentro del parser de tipos para preservar nested generics. En la base auditada
no existe todavía union type con `|`; agregar el token no autoriza esa gramática.

## Modelo de compilador

AST y HIR reciben variantes explícitas. AND/OR/XOR pueden reutilizar el contrato
binario homogéneo de MIR/SSA; NOT reutiliza la categoría unary. Los shifts exigen
una extensión mínima del verificador para validar por separado tipo izquierdo,
tipo count y tipo resultado. No justifican una infraestructura genérica nueva.

HIR hace const folding con el ancho exacto. HIR, MIR y SSA reconstruyen tipos,
signedness, resultado y traps independientemente. La guard del count precede a la
guard de overflow y a cualquier shift backend. Las cotas de representabilidad se
calculan sólo después de validar el count y mediante operaciones que no puedan
causar overflow, poison ni UB. El orden de evaluación de ambos operandos se
conserva.

Las asignaciones futuras `&=`, `|=`, `^=`, `<<=` y `>>=` pueden reutilizar
`CompoundLoad`/`CompoundCommit`. Los shifts añaden count heterogéneo, guard de
rango y, para `<<=`, overflow antes del único commit. No se implementan aquí y
`**=` no se admite.

## Qualification diseñada

El plan cubre los diez tipos, aliases, signed/unsigned, anchos distintos,
negativos, sign bit, cero, signed `MIN`/`MAX`, unsigned `MAX`, literals
contextuales, counts límite, prioridad de traps, folding,
precedencia y conflictos léxicos. Incluye corrupción independiente de HIR/MIR/SSA,
ejecución nativa O0/O2, differential oficial y comparación contra el contrato,
no sólo contra LLVM.

La qualification global deberá distinguir la excepción preexistente del registry:
el caso `linear_algebra_oal_publishes_and_runs_real_qr_consumer` puede quedar
colgado. Un timeout no se registra como PASS ni como regresión bitwise sin una
comparación de baseline.

## Preflight y cambios

HEAD coincidió con la base esperada. Se preservaron cambios personales previos en
`examples/ProbandoNR/` y reports no trackeados ajenos. No se ejecutaron commit,
push, reset, clean ni stash.

Este milestone creó únicamente:

- `docs/architecture/BITWISE_OPERATORS_ARCH_1.md`;
- `docs/architecture/BITWISE_OPERATORS_ARCH_1_REPORT.md`.

No se modificaron lexer, parser, AST, HIR, MIR, SSA, LLVM, tests ni programas.

## Cierre

Quedaron aprobados: counts de cualquiera de los diez enteros, trap
`ShiftCountOutOfRange` para count negativo o fuera de ancho, `<<` checked en
signed/unsigned, `>>` aritmético en signed y lógico en unsigned, bitwise por
encima de comparación/igualdad, asociatividad izquierda, conversiones enteras
ordinarias con resultado homogéneo, complemento a dos, partición contextual de
`>>` en tipos y reutilización de la infraestructura IR existente.

La matriz de tests, la corrupción independiente HIR/MIR/SSA, el differential y
la verificación O0/O2 se conservan íntegros, incluida la excepción global
preexistente del registry. BITWISE-OPERATORS-ARCH-1 queda `CLOSED` sin iniciar
BITWISE-OPERATORS-V1 ni modificar código productivo.
