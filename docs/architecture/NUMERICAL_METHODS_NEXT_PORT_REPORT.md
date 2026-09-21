# Numerical methods: port a compiler-next

Estado: port completado y validado, 2026-09-21.

## Resultado

El ejemplo multi-package de métodos numéricos compila y ejecuta con
`compiler-next` sin agregar features al lenguaje ni cambiar los algoritmos:

```bash
aether examples/numerical_methods/main.ae --compiler next
aether examples/numerical_methods/main.ae --compiler next -O2
```

Ambos niveles producen las mismas 18 validaciones exitosas. Se preservan
bisección, Newton-Raphson, secante, trapecios, Simpson, límites invertidos y
todos los resultados inválidos observables del programa legacy.

## Auditoría legacy frente a compiler-next

| Hallazgo | Clasificación | Resolución |
| --- | --- | --- |
| El entry legacy ejecutaba statements top-level | 1. Diferencia de sintaxis/API ya soportada | Se movió la ejecución a `int main()`. |
| `from X import Y` no pertenece al sistema actual | 2. Feature soportada con spelling distinto | Se usó `import X;` y acceso calificado `X.Y`. |
| `println` legacy aceptaba varios argumentos | 2. Feature soportada con spelling distinto | Se usó un string interpolado por línea. |
| Callables top-level capture-free | 1. Diferencia de API ya soportada | Se conservó `Function<(double), double>` mediante `ScalarCallable`. |
| Casts y matemática escalar | 1. Diferencia de API ya soportada | Se conservaron `double(value)` y `abs(value)`. |
| Structs, enums y constructores por valor | 1. Diferencia de sintaxis/API ya soportada | Se conservaron los cuatro tipos nominales y sus payloads. |
| `public` en declaraciones top-level legacy | 2. Spelling distinto | Se omitió; la superficie package actual importa las declaraciones top-level sin ese modificador. |
| `public Results.RootResult f(...)` | 5. Ergonomía incómoda pero posible | El parser deriva `public` al grammar de clases y falla en el tipo calificado; se usa la declaración top-level canónica sin `public`. |
| Igualdad `==` entre enums payload-free | 4. Bug/regresión de compiler-next | La semántica construye HIR pero el verificador falla con `E0348 HIR binary invalid`. Se observaron estados mediante `match` exhaustivo. |
| Feature realmente ausente y bloqueante | 3. Feature realmente ausente | Ninguna. |

El source legacy sin adaptar falla primero en su import inicial con:

```text
main.ae:1:18: error[E0100] (parse): expected `(` after function name
```

Esto confirma que el import selectivo antiguo no se debe forzar en el port.

## Cambios de source

- `main.ae` ahora importa `Problems`, `Roots`, `Integration` y `Results`, y
  contiene un `int main()`.
- Los símbolos entre packages se nombran de forma calificada.
- Las 18 impresiones usan interpolación y `println` de un argumento.
- `Functions.ae` conserva el alias estructural `ScalarCallable`.
- `Roots.ae` e `Integration.ae` conservan firmas basadas en ese alias, los
  mismos loops, tolerancias, límites de iteraciones y fórmulas.
- `Results.ae` conserva `RootStatus`, `RootResult`, `IntegrationStatus` e
  `IntegrationResult`. Añade predicados exhaustivos basados en `match` para
  validar estados sin depender de la regresión de igualdad de enums.
- Se mantuvieron los packages separados; no se agregaron wildcard imports.

## Blockers

No hubo blockers estructurales. Todas las capacidades necesarias existen en el
lenguaje actual y la regresión de igualdad de enums tiene una expresión natural
equivalente mediante pattern matching.

## Fricciones de ergonomía

La qualification de tipos, constructores y variantes importados es más verbosa
que el import selectivo legacy, pero deja explícita la procedencia nominal. La
ausencia de `public` en top-level difiere del source anterior. La regresión de
igualdad de enums obliga a predicados `match` repetitivos para checks que
conceptualmente son comparaciones simples.

## Bugs encontrados y corregidos

No se modificó el compilador. Se encontró una regresión reproducible en
`compiler-next`: una expresión como esta llega a HIR y falla en verificación:

```aether
enum Status { Ok, Error }

int main() {
    Status status = Status.Ok;
    if (status == Status.Ok) {
        return 0;
    }
    return 1;
}
```

El diagnóstico observado es `error[E0348] (semantic): HIR binary invalid`.
Para este port se corrigió el source consumidor usando `match`; reparar la
igualdad nominal queda deliberadamente fuera de alcance.

## Features deliberadamente no implementadas

No se agregó import selectivo, script mode, ejecución top-level, overload de
`println`, nueva visibilidad top-level, nueva representación de callables ni
igualdad de enums. Tampoco se incorporaron defaults, `const`, nullable o
inferencia genérica local porque no mejoraban naturalmente estos algoritmos.

## Salida final

```text
bisection converged: true
bisection accurate: true
newton converged: true
newton accurate: true
secant converged: true
secant accurate: true
invalid bracket rejected: true
zero derivative rejected: true
zero secant denominator rejected: true
trapezoid succeeded: true
trapezoid accurate: true
simpson succeeded: true
simpson accurate: true
invalid trapezoid count rejected: true
invalid Simpson count rejected: true
odd Simpson count rejected: true
reversed trapezoid preserves sign: true
reversed Simpson preserves sign: true
```

## Validación

Comandos del ejemplo y el differential ejecutados desde la raíz del repositorio:

```bash
.venv/bin/aether examples/numerical_methods/main.ae --compiler next
.venv/bin/aether examples/numerical_methods/main.ae --compiler next -O2
bash compiler-next/tests/run-differential.sh
```

Comandos ejecutados desde `compiler-next/`:

```bash
cargo test --workspace
cargo fmt --all --check
cargo clippy --workspace --all-targets -- -D warnings
```

Comando final desde la raíz:

```bash
git diff --check
```

El launcher local se invocó como `.venv/bin/aether` porque `aether` no estaba
en `PATH`; es el mismo entry point documentado. O0 y O2 devolvieron status 0 y
salida idéntica.

Resultados:

- `cargo test --workspace`: pass, 0 fallos;
- `cargo fmt --all --check`: pass;
- `cargo clippy --workspace --all-targets -- -D warnings`: pass;
- `git diff --check`: pass;
- differential: `checked=21 failures=0`.

## Próximo frente recomendado

Conviene atacar la coherencia de igualdad para enums payload-free: hoy la
resolución acepta la expresión pero el verificador HIR la rechaza tarde con un
diagnóstico interno. El trabajo siguiente debería decidir explícitamente si la
igualdad nominal pertenece al contrato; si pertenece, implementarla y
calificarla en todas las capas, y si no, rechazarla temprano con un diagnóstico
source-facing preciso. No hace falta rediseñar imports ni el modelo de status
para resolver este punto.
