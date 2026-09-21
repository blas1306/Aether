# Expense tracker: auditoría de port a compiler-next

Estado: **port detenido por blockers estructurales**, 2026-09-21.

## Resultado

No se modificó el source de `examples/expense_tracker`. La auditoría encontró
que la superficie pública actual de `compiler-next` permite portar el dominio,
los reportes y una demostración puramente en memoria, pero no permite conservar
de forma natural la aplicación legacy descrita por su README: su CLI persistente
ALPT1 depende de argumentos de proceso, parsing numérico y acceso byte-based a
texto. Las tres capacidades están ausentes.

Crear sólo el demo sin argumentos habría hecho ejecutable el comando pedido,
pero habría eliminado `add|list|summary`, la carga fail-closed y la
compatibilidad con el formato persistente. Eso no constituye un port razonable
del ejemplo legacy completo. Conforme al alcance del milestone, no se agregó
ninguna feature al lenguaje, stdlib o runtime y no se sustituyó ALPT1 por otro
formato.

El comando objetivo sigue sin estar disponible:

```text
$ aether examples/expense_tracker/main.ae --compiler next
error[E0700] (driver): could not read entry source `examples/expense_tracker/main.ae`: No such file or directory (os error 2)
```

El entry legacy es `Main.ae`; tampoco compila sin migración y falla primero en
el import selectivo:

```text
$ aether examples/expense_tracker/Main.ae --compiler next
Main.ae:1:14: error[E0100] (parse): expected `(` after function name
```

## Auditoría legacy frente a compiler-next

| Superficie legacy | Clasificación | Superficie real / resolución posible |
| --- | --- | --- |
| `from X import Y` | 2. Feature soportada con spelling distinto | `import X;` y nombres calificados como `X.Transaction`. |
| `public` en funciones, structs y enums top-level | 2. Feature soportada con spelling distinto | Las declaraciones top-level importables se escriben sin `public`. |
| `int main()` | 1. Diferencia de sintaxis/API ya soportada | Se puede conservar directamente. |
| `println(a, b, ...)` | 2. Feature soportada con spelling distinto | `println` recibe un string; la interpolación cubre la composición escalar. |
| `.byteLength`, `.trim()` y `.split()` | 2. Feature soportada con spelling distinto | `byteLength(value)`, `std.Text.trim(value)` y `std.Text.split(value, separator)`. |
| `List.length`, `.push()` y `.copy()` | 2/3 | `length(list)` y `push(list, value)` existen; no existe `copy()` owning general. |
| `List` slicing, `contains` e `indexOf` | 3. Feature realmente ausente | No existe superficie equivalente actual. Son checks de dogfood del demo, no requisito del ledger básico. |
| Assignment con aliasing de `List` | 1. Diferencia semántica soportada | `compiler-next` usa ownership exclusivo y move; el source debe adaptarse, no intentar recrear aliasing legacy. |
| `List<Transaction>`, crecimiento y replacement por índice | 1. Diferencia de API ya soportada | Structs owning relocatable dentro de `List`, `push`, indexing y replacement están soportados. |
| Iteración owning `for (Transaction t in list)` | 2. Feature soportada con spelling distinto | Un elemento non-Copy se itera como `ref Transaction`; sus fields se leen mediante dereference explícito. |
| Igualdad de enums payload-free | 1. Diferencia ya soportada | `ENUM-EQUALITY-V1` permite `==`/`!=`; no requiere workaround con `match`. |
| Strings dentro de structs/collections y concatenación | 1. Diferencia ya soportada | Son owners con Drop estructural; `+` e interpolación producen strings owned. |
| `System.args()` / `Array<string>` de argumentos | 3. Feature realmente ausente | No existe package de proceso ni API pública de argv. |
| `parseInt` / `parseDouble` y sus resultados | 3. Feature realmente ausente | FORMAT-V1 implementa scalar→string, pero declara string→número fuera de alcance. |
| `text.byteAt` / `text.byteSlice` | 3. Feature realmente ausente | `std.Text` expone offsets por scalar; las primitives byte-based son privadas por contrato. |
| `text.formatInt` / `text.formatDouble` | 2. Feature soportada con spelling distinto | `str(value)` produce representación escalar canónica. |
| `text.concatFragments` | 5. Ergonomía incómoda pero posible | Se puede componer con `+`; para muchos fragments no hay builder público. |
| `io.readText` / `io.writeText` con status | 2. Feature soportada con API distinta | `std.File.readText` y `writeText` usan excepciones nominales. |
| `io.appendText` | 3. Feature realmente ausente | `std.File` no ofrece append. El `persist-check` auxiliar podría reescribirse, pero perdería su contrato de append. |
| `io.writeTextAtomic` | 3. Feature realmente ausente | `std.File.writeText` trunca/escribe y no promete atomicidad, rollback ni durabilidad. No es equivalente a la publicación ALPT1 legacy. |
| stdin y EOF | 1. Diferencia de API ya soportada | `std.IO.readLine()` devuelve `ReadLineResult.Line(string)` o `End`; errores de IO/UTF-8 son excepciones. |
| Repetición de lectura en loops | 1. Diferencia ya soportada | `readLine()` conserva estado, distingue línea vacía/EOF y admite llamadas repetidas. |

No se encontró durante la auditoría una feature necesaria que estuviera
documentada como soportada pero fallara por bug/regresión. Los fallos relevantes
son rechazos source-facing coherentes con la superficie publicada.

## Blocker estructural principal: codec ALPT1

ALPT1 enmarca cada field como longitud en **bytes UTF-8**, seguida por un
payload que puede contener cualquier texto válido, incluidos espacios y saltos
de línea. El decoder legacy necesita inspeccionar el byte terminador y extraer
exactamente `length` bytes. `std.Text.substring` trabaja con posiciones scalar,
no byte offsets, mientras `std.Text.lines` y `split` no pueden preservar el
framing cuando el payload contiene sus separadores.

### Source mínimo

```aether
import std.Text;

int main() {
    string payload = std.Text.byteSlice("éxito", 0, 2);
    return int(byteLength(payload));
}
```

### Comportamiento esperado

Una API pública equivalente debe extraer los primeros dos bytes sólo bajo un
contrato UTF-8 seguro, o el lenguaje debe ofrecer un tipo/lector de bytes que
permita implementar el framing ALPT1 y validar las fronteras antes de publicar
un string.

### Comportamiento actual

```text
expense_audit_bytes.ae:4:20: error[E0222] (semantic): unknown function `byteSlice` in module `Text`
```

### Fase donde falla

Resolución semántica del member importado, antes de HIR/MIR/SSA.

### Por qué no hay workaround natural

- `substring` usa offsets scalar; ALPT1 almacena longitudes y offsets en bytes.
- Sólo podría reconstruirse una frontera byte recorriendo scalars, creando
  substrings y acumulando `byteLength`; eso implementaría dentro del ejemplo
  un cursor indirecto, allocation-heavy y potencialmente cuadrático.
- `lines` no sirve porque un payload string puede contener LF/CRLF.
- `split` no sirve porque el separador también puede aparecer dentro del
  payload y el formato no aplica escaping.
- Cambiar a un formato line-based, prohibir saltos de línea o medir scalars
  rompería compatibilidad y la semántica fail-closed del ejemplo legacy.

## Blockers adicionales reproducidos

### Argumentos de proceso

Source mínimo:

```aether
import System;

int main() {
    Array<string> args = System.args();
    return int(length(args));
}
```

Resultado actual, en resolución de packages:

```text
error[E0221] (semantic): package path `System` does not exist
```

Sin argv no se puede conservar la interfaz documentada
`<ledger.alpt> <add|list|summary> ...`. Migrarla a stdin cambiaría la interfaz y
aun así quedaría bloqueada por parsing numérico.

### Parsing numérico

Source mínimo:

```aether
int main() {
    IntParseResult parsed = parseInt("42");
    return parsed.value;
}
```

Resultado actual, en resolución semántica de tipos:

```text
error[E0204] (semantic): unknown type `IntParseResult`
```

No hay scanner, acceso a chars/bytes ni parser string→número alternativo. Una
tabla manual basada en cadenas y `substring` sería desproporcionada, no cubre
de manera natural floats canónicos/exponentes y duplicaría una responsabilidad
de std/runtime dentro del ejemplo.

### Publicación atómica y append

Las llamadas mínimas `std.File.writeTextAtomic(path, content)` y
`std.File.appendText(path, content)` fallan durante resolución semántica con
`E0222 unknown function or struct`. `writeText` no es equivalente: el contrato
IO-V1 declara explícitamente que no ofrece atomicidad, rollback ni durabilidad.
Usarlo en `saveLedger` permitiría que un fallo parcial corrompiera el ledger,
rompiendo una garantía funcional destacada por el README legacy.

## Cambios de source

Ninguno. En particular, no se creó `examples/expense_tracker/main.ae` y no se
alteraron `Main.ae`, `Transaction.ae`, `Ledger.ae`, `Reports.ae`,
`Persistence.ae` ni el README legacy.

## Workarounds evaluados y descartados

- Un demo sólo en memoria: compilaría con adaptaciones naturales, pero elimina
  la mayor parte del programa documentado y oculta los blockers.
- Un menú por stdin: `std.IO.readLine` existe, pero cambia la CLI y no resuelve
  parsing numérico ni ALPT1.
- Un ledger line-based: pierde compatibilidad, acepta menos strings y cambia el
  diseño funcional.
- `std.File.writeText` como reemplazo de escritura atómica: degrada una
  garantía explícita de seguridad del archivo.
- Clones o aliases artificiales para reproducir los checks de collections del
  demo: contradicen el modelo de ownership actual y no son necesarios para el
  dominio.

## Fricciones de ergonomía no bloqueantes

La qualification de packages hace más verbosos tipos, variantes y funciones.
Los loops de elementos owning requieren bindings `ref` y dereference explícito.
Las operaciones de `List` son funciones libres. La composición de muchos
fragments sin builder público es posible con `+`, aunque potencialmente menos
eficiente. El mapeo de excepciones de `std.File` a `LedgerStatus` también exige
wrappers `try/catch`, pero es expresable.

## Features deliberadamente no implementadas

No se agregó argv, parsing numérico, byte indexing/slicing, builders, clone de
colecciones, slicing, `contains`, `indexOf`, append ni escritura atómica.
Tampoco se agregó import selectivo, output variádico o compatibilidad sintáctica
legacy. No se modificó el compilador, la stdlib ni el runtime.

## Validación funcional y O0/O2

No corresponde afirmar validación funcional del port: no existe un port
ejecutable mientras el blocker permanezca. Por la misma razón no hay resultados
O0/O2 del expense tracker. Los programas mínimos se compilaron directamente con
`aether-next build` para aislar la fase y evitar que el primer error legacy
ocultara los siguientes.

La auditoría sí contrastó las capacidades positivas con los contratos y tests
actuales de IO-V1, TEXT-V1, FORMAT-V1, ITERATION-V3, BORROW-ERGONOMICS-V1,
ENUM-EQUALITY-V1 y las verticales de collections owning.

La matriz general solicitada se ejecutó para comprobar que el blocker no era
una regresión incidental del workspace:

```text
cargo test --workspace                              pass
cargo fmt --all --check                             pass
cargo clippy --workspace --all-targets -- -D warnings  pass
git diff --check                                    pass
bash compiler-next/tests/run-differential.sh        checked=21 failures=0
```

## Próximo frente recomendado

El siguiente frente debería ser una superficie de parsing y framing de datos,
no una ampliación ad hoc para este ejemplo. El mínimo útil combina:

1. parsing canónico y checked de enteros/floats desde `ref string`, con
   resultados o excepciones explícitos;
2. una abstracción pública segura de bytes UTF-8 o un cursor de decoding que
   pueda validar y extraer rangos byte-framed sin exponer strings inválidos;
3. después, `std.Process.args()` para recuperar la interfaz CLI y una operación
   de reemplazo atómico en `std.File` para recuperar la garantía de guardado.

Ese orden desbloquea primero el codec ALPT1, que es la imposibilidad
estructural más profunda. argv por sí solo sólo haría alcanzable una ruta que
todavía no puede parsear ni cargar el ledger; `writeText` por sí solo conservaría
un riesgo de corrupción que el ejemplo legacy evita deliberadamente.
