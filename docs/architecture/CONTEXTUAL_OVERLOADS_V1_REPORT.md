# CONTEXTUAL-OVERLOADS-V1 — reporte

Estado: **IMPLEMENTADO**, 2026-09-28.

Autoridad de origen:

- [DYNAMIC_SHAPES_AND_SLICES_ARCH_1](DYNAMIC_SHAPES_AND_SLICES_ARCH_1.md)
- [DYNAMIC_SHAPES_AND_SLICES_ARCH_1_REPORT](DYNAMIC_SHAPES_AND_SLICES_ARCH_1_REPORT.md)

## Resultado

Compiler-next admite overload sets source generales. Un nombre de función se
indexa a todas sus declaraciones visibles dentro del package y la llamada se
resuelve por aridad, argumentos, constraints y expected result type. No existe
prioridad por orden de declaración.

La resolución prueba cada candidato sobre un estado semántico transaccional:
los candidatos descartados no consumen owners, no publican borrows, no alteran
refinamientos null, no asignan locals/call sites y no dejan TypeIds internados.
Después de exigir un único candidato viable, se analiza una vez la llamada
seleccionada y HIR conserva exclusivamente su `FunctionId` concreto y sus type
arguments. MIR y SSA nunca reciben un overload set.

Las funciones no-overloaded conservan el camino y los diagnostics anteriores.
Las firmas alpha-equivalentes, incluidos sus constraints, se rechazan como
duplicados; mutabilidad de binding y defaults no crean identidades de overload.
`main` continúa siendo exactamente una declaración `int main()` y no puede
formar un overload set.

## Contexto e inferencia

El expected type ya recorrido por el analizador se usa ahora al resolver
llamadas desde:

- declaraciones locales tipadas;
- assignments;
- returns;
- argumentos con parámetro conocido, incluidas llamadas anidadas;
- fields de inicializadores de aggregates;
- referencias a funciones overloaded con Function type esperado.

La inferencia genérica unifica primero el retorno con el expected type y luego
los argumentos de izquierda a derecha. Por eso puede determinar parámetros que
aparecen sólo en el retorno y usar parámetros ya inferidos para contextualizar
argumentos posteriores. La adaptación `T -> ref T` permanece posterior a la
inferencia y no se debilitó BORROW-ERGONOMICS-V1.

`var name = expression;` adopta el tipo completo del initializer. No aporta un
expected type; por lo tanto una llamada contextual con varios resultados
posibles permanece ambigua. `var name = null` conserva su rechazo específico.

## Orientación

No se agregó borrado de orientación ni metadata runtime. Los overloads pueden
devolver `Vector<T,Row>` y `Vector<T,Column>` y el expected result selecciona la
identidad nominal exacta. Esto permite expresar la superficie requerida para
`zeros`/`ones` mediante overloads ordinarios con retornos Matrix, Vector Row y
Vector Column, sin reconocer esos nombres ni packages en el compilador.

## Identidad y backend

Las declaraciones de un overload set reciben un disambiguador explícito. HIR
verifica que sólo exista cuando el nombre está overloaded y que cada instancia
monomorfizada conserve el de su declaración. El backend lo incorpora al símbolo
LLVM para evitar colisiones entre overloads no genéricos. Los símbolos de
funciones no-overloaded permanecen byte-for-byte iguales.

## Diagnostics

Se agregaron diagnostics compactos con las firmas source relevantes:

- `E0460`: no matching overload, incluido result type mismatch;
- `E0461`: ambiguous overload y orientation ambiguity;
- `E0462`: type parameter inferable sólo desde contexto ausente;
- `E0464`: mismatch entre retorno genérico y expected result durante evaluación
  de candidato;
- `E0211`: firma de overload duplicada/indistinguible.

## Cobertura

`contextual_overloads_v1.rs` cubre overload por aridad, argumento y resultado;
inferencia de T sólo desde retorno; Matrix frente a Vector; Row frente a Column;
`var` ambiguo; contextos return, assignment, argumento anidado y aggregate;
no-match, ambiguity, result mismatch, contexto faltante, constraints, packages e
import aliases; HIR/MIR/SSA resueltos; ejecución nativa O0/O2 y símbolos LLVM
sin colisión.

También se actualizaron las expectativas históricas que declaraban fuera de
alcance `var` o la inferencia genérica desde retorno. No se implementaron
`zeros`, `ones`, `identity`, defaults nuevos, conversiones implícitas ni dynamic
dispatch.

## Validación

Comandos de cierre:

```text
cargo test --workspace
cargo fmt --all --check
cargo clippy --workspace --all-targets -- -D warnings
git diff --check
bash compiler-next/tests/run-differential.sh
```

Todos finalizaron correctamente. La prueba diferencial comprobó 21 casos con
0 fallos; la suite completa de workspace, incluidos los tests nativos O0/O2 de
esta feature, quedó verde.
