# PRINT-VALUE-ARCH-1 — output de un valor mediante FORMAT

Estado: **ARQUITECTURA CERRADA; IMPLEMENTADA EN PRINT-VALUE-V1**, 2026-09-29.

Este milestone amplía la superficie Core de `print` y `println` para aceptar un
único valor perteneciente al perfil FORMAT activo. La representación, la
admisión de tipos y el acceso observacional proceden de FORMAT; output sólo
elige stdout y si agrega LF.

Documentos y verticales de base:

- [FORMAT_ARCH_1.md](FORMAT_ARCH_1.md) y
  [FORMAT_V1_REPORT.md](FORMAT_V1_REPORT.md);
- [FORMAT_BORROW_ARCH_1.md](FORMAT_BORROW_ARCH_1.md) y
  [FORMAT_BORROW_V1_REPORT.md](FORMAT_BORROW_V1_REPORT.md);
- [MATH_FORMAT_ARCH_1.md](MATH_FORMAT_ARCH_1.md) y
  [MATH_FORMAT_V1_REPORT.md](MATH_FORMAT_V1_REPORT.md);
- [CORE_V1_REPORT.md](CORE_V1_REPORT.md) e
  [IO_V1_REPORT.md](IO_V1_REPORT.md).

## 1. Resultado normativo

La superficie fuente queda conceptualmente cerrada como:

```aether
void print<T: FormatAdmitted>(T value);
void println<T: FormatAdmitted>(T value);
```

`FormatAdmitted` es notación de este documento, no una capability, trait o
tipo público nuevo. El compilador consulta la misma autoridad cerrada que
construye un `InterpolationFragment::Hole`. Para un argumento `E`:

```text
T = format_type(type(E))                 // peeling FORMAT de ref/ref mut
admit print(E) iff format_admission(T) existe
bytes(print(E)) = bytes del único hole ${E}
```

Esto admite, bajo el perfil implementado al cerrar esta arquitectura:

- `string`, todos los integers, `float32`, `float64`, `bool` y `char`;
- `Vector<T,Row>`, `Vector<T,Column>` y `Matrix<T>` exactamente cuando
  MATH-FORMAT admite el owner y su elemento;
- places, proyecciones, referencias y temporales de esos tipos mediante las
  reglas de FORMAT-BORROW.

No admite views matemáticas, tipos nominales arbitrarios, collections fuera
del perfil, genéricos sin prueba estática ni ningún tipo que FORMAT rechace.
No existe fallback de runtime.

La aridad V1 es exactamente uno. Siguen siendo inválidos:

```aether
println();
println("x = ", x);
println(a, b, c);
```

No se agregan type arguments source para estas funciones.

## 2. Auditoría del estado actual

La implementación canónica afectada es `compiler-next`.

- `CoreSymbol::Print` y `CoreSymbol::Println` son identidades únicas del
  manifest Core. `CoreFunction` conserva hoy `parameter_type = string`; su
  resultado `bool` es un token interno de efecto, no un valor source.
- El resolver reconoce un statement Core output antes del camino general de
  calls, exige un argumento y lo fuerza mediante `string_borrow_operand`.
- HIR usa `HirStmtKind::StringOutput`; MIR lo baja a un `CoreCall` de output y
  SSA conserva ese call. El backend llama a la frontera stdout length-aware.
- El fallo de stdout mantiene el `may_unwind` existente y se traduce a
  `std.IO.IOException`. `println` agrega un LF y `print` no lo agrega.
- La autoridad FORMAT está en la construcción y verificación del hole:
  `scalar_interpolation_conversion` para string/scalars y
  `mathematical_format` para los owners matemáticos. La conversión resuelta se
  conserva en `InterpolationConversion` hasta backend.
- `FormatScopedSharedBorrow` separa acceso (`CopyValue` o
  `SharedObservation`) de conversión. MIR/SSA conservan región, metadata,
  provenance y cleanup.
- `StringOp::Interpolate` ya implementa medición checked, una publicación
  exacta y escritura mediante los formatters canónicos. No concatena strings
  ni despacha por `TypeId` en runtime.

La extensión no debe tomar `str` como autoridad suficiente: `str` cubre la
familia escalar pública, mientras el perfil de holes también contiene `string`
y las recetas MATH-FORMAT. La autoridad compartida correcta es la consulta que
produce `InterpolationConversion` para el `formatted_type`.

## 3. Una sola autoridad FORMAT

La implementación debe extraer o reutilizar una consulta semántica única,
conceptualmente:

```text
format_admission(types, formatted_type)
    -> StringBorrow
     | CanonicalScalarFormat
     | MathematicalAggregateFormat(recipe)
     | none
```

La usan tanto un hole escrito `${expression}` como el argumento directo de
output. El verificador reconstruye la respuesta desde `TypeArena`; no confía
en una etiqueta producida por frontend.

La consulta sólo decide representación. Antes de invocarla, la resolución
contextual de FORMAT decide cómo observar la expresión:

```text
Copy scalar              -> CopyValue
non-Copy Place           -> FormatScopedSharedBorrow(Place)
ref T / ref mut T        -> shared observation del pointee final
owning rvalue             -> stabilized root + shared observation
projection sobre rvalue  -> stabilized root completo + projected borrow
```

Estas son exactamente las dos dimensiones ya separadas por FORMAT-BORROW:
`formatted_type/access` y `conversion`. Output no agrega una tercera tabla de
tipos, no busca nombres de tipos y no selecciona formatter en runtime.

## 4. Strings y escapes

`string` conserva una ruta de identidad, sin construir una interpolación
sintética:

- un lvalue se presta a la call de output;
- un temporary string se mantiene como owner hasta que el write termina y se
  destruye mediante el cleanup actual;
- una literal ordinaria conserva su representación inmortal;
- los bytes `data[0:byteLength]`, incluido U+0000, se escriben sin quotes,
  escaping adicional ni normalización.

Por tanto:

```aether
print("hola");
println("hola");
```

escribe `hola` y `hola\n`. Los escapes se decodifican en lexer/parser como
siempre:

```aether
println("a\nb");
println("\tx");
```

Output no interpreta nuevamente `\n`, `\t`, backslashes ni `${...}`. Una
literal con holes continúa siendo una expresión `StringOp::Interpolate` normal
y llega a la ruta string una vez construido su owner.

Mantener esta ruta especializada no crea overload ambiguity: no hay dos
candidatos públicos. Existe una sola familia Core source; tras resolver el
argumento, `string` usa identidad y cualquier otro tipo admitido usa el plan
FORMAT de valor descrito abajo.

## 5. Scalars y owners matemáticos

Para un argumento no-string admitido, el frontend construye un plan FORMAT
interno equivalente a una interpolación de un hole y cero chunks de texto:

```text
Interpolate {
    fragments: [Hole(value, formatted_type, access, conversion)],
    ownership: Fresh,
    size_plan: CheckedExact,
}
```

Por construcción:

```text
formatted_bytes(value) == bytes("${value}")
```

Esto preserva byte por byte:

- decimal y signedness de integers;
- formato shortest, umbrales fixed/scientific, `-0`, `NaN`, `Inf` y `-Inf`;
- `true`/`false`;
- UTF-8 de `char`, incluido U+0000;
- `[a, b]`, `[a; b]`, `[a, b; c, d]` y las formas empty de MATH-FORMAT.

No se agregan quotes a `char` ni `string`. Tampoco hay formatter particular de
Matrix, Vector, LU, `factor.L`, `factor.U`, `solve` o `det` dentro de output.
Las views siguen excluidas mientras MATH-FORMAT las excluya.

## 6. Elección de publicación y allocation

PRINT-VALUE-V1 elige **formatear primero a un owner `string` y después usar el
stdout Core existente**.

La alternativa de publicar fragments directamente a stdout se difiere porque
crearía una segunda estrategia de count/write, complicaría el comportamiento
ante write parcial y mezclaría representación FORMAT con IO. No es necesaria
para cumplir el contrato V1.

El coste normativo es:

| Argumento | Allocation adicional de PRINT-VALUE-V1 |
|---|---|
| literal o lvalue `string` | ninguna; output borrowed existente |
| temporary `string` | ninguna aparte de producir ese temporary |
| scalar directo | el único owner exacto que produciría `"${value}"` |
| Vector/Matrix directo | el único owner exacto que produciría `"${value}"` |
| literal interpolada | sin cambio: su única publicación FORMAT actual |

El plan de un hole mide con aritmética checked, realiza una sola allocation
exacta si el resultado no es vacío y escribe con los primitives FORMAT ya
existentes. No crea string por elemento, concat chain, clone del owner fuente
ni buffer proporcional adicional. Buffers escalares privados acotados siguen
sin ser owners Aether.

Una optimización futura puede fusionar FORMAT con stdout si preserva API,
bytes, orden, traps, exceptions y ownership. Esa optimización no forma parte de
este milestone y no puede convertirse en otra autoridad de representación.

## 7. Ownership, borrows y temporales

Formatting directo es observacional. Para un owner o field non-Copy:

```aether
println(matrix);
use(matrix);

println(factor.L);
use(factor);
```

el argumento se resuelve contextualmente como FORMAT antes de generar un
`Load`/`Move`. Se presta el Place completo o su proyección; no hay `MoveField`,
partial move, Clone, Alias, retain, COW ni reconstrucción del agregado.

Referencias shared y mutables siguen el peeling de FORMAT-BORROW. Se imprime
el pointee, nunca la dirección. Un `ref mut T` recupera su capacidad mutable al
terminar el borrow FORMAT. Los conflictos reales se someten al checker
ordinario de Places/provenance.

### 7.1 Rvalue directo

`println(makeMatrix())` se ejecuta en este orden:

1. evaluar `makeMatrix()` exactamente una vez;
2. estabilizar el owner completo en un root temporal;
3. abrir el shared borrow FORMAT;
4. medir, reservar, emitir y publicar el string exacto;
5. cerrar el borrow FORMAT;
6. escribir el string a stdout y, para `println`, escribir un LF;
7. destruir el string formateado y luego el root temporal, exactamente una vez.

Aunque el último read del valor ocurre en el paso 4, el root temporal directo
permanece inicializado hasta que termina la operación completa `format +
write`. El borrow sí termina antes del write: el string publicado no contiene
referencias al source. Esta extensión de storage no habilita un uso, move o
mutación intermedio y satisface el límite de lifetime de la operación source.

En una proyección de rvalue se estabiliza y conserva el root completo, no sólo
el field. En el camino normal, el orden de destrucción es el inverso al de
publicación de owners: string FORMAT y luego root fuente.

### 7.2 Fallos y cleanup

- Si evaluar el argumento lanza antes de publicar el root, no hay Drop del root.
- Si una evaluación ya inicializó un root y una operación recuperable posterior
  lanza, el landing pad cierra borrows activos antes de destruir owners.
- El formatter cerrado actual no produce `FormatException`. Una vez publicado
  el string y cerrado el borrow, un fallo de stdout lanza el mismo
  `std.IO.IOException` actual; el landing pad destruye el string y después el
  root estabilizado exactamente una vez.
- Overflow de tamaño, OOM, corrupción y `char` runtime inválido conservan los
  traps abortivos de FORMAT. PRINT-VALUE no promete unwind donde el runtime
  global no lo tiene.
- Un write parcial antes de `IOException` conserva el modelo IO existente: los
  bytes externos ya escritos no se revierten.

La vida extendida del root aplica sólo al argumento directo de valor. No cambia
el momento de cleanup de una interpolación construida como expresión string
independiente. Hace falta, por ello, conservar en HIR que el plan fue creado
por direct-value output; no se debe inferirlo sólo viendo que el argumento
resultante es `StringOp::Interpolate`.

## 8. Efectos e IO

Después de obtener el string:

```text
print(value)   = stdout.write_all(formatted bytes)
println(value) = stdout.write_all(formatted bytes); stdout.write_all([LF])
```

Se escribe exactamente un byte `0x0A` adicional para `println`; `print` no
agrega bytes. No se agrega flush, buffering contractual, stderr fallback ni
newline dependiente de plataforma.

La frontera sigue siendo length-aware y conserva U+0000. Los loops de write,
EINTR, write parcial, progreso cero, SIGPIPE/EPIPE y traducción a
`std.IO.IOException` permanecen bajo IO-V1. Formatting termina antes del primer
efecto externo de output, de modo que una falla de medición/allocation no
publica un prefijo en stdout.

## 9. Resolución y API Core

`print` y `println` permanecen símbolos únicos de Core/prelude; no se agregan
funciones homónimas en `std.IO`. El manifest, `CoreSymbolKey` y reglas de
shadowing no cambian.

El resolver trata cada símbolo como una familia intrínseca cerrada de una
arity, similar a las familias Core numéricas, pero su admisión se obtiene sólo
de FORMAT. La secuencia es:

1. comprobar cero type arguments y exactamente un argumento;
2. resolver el argumento una vez bajo contexto FORMAT, conservando Place,
   references y rvalue root;
3. obtener `formatted_type`, `access` y `format_admission`;
4. para `string`, construir output string existente;
5. para otro tipo admitido, construir el plan interno de un hole;
6. bajar ambos al mismo Core output `(string) -> efecto` ya existente.

La firma de backend/runtime no se vuelve genérica. `CoreCall` de output sigue
recibiendo `string`; la genericidad existe sólo en la superficie y se resuelve
estáticamente antes de MIR output. Esto evita ABI nueva, boxing y dispatch.

Un callable lexical o member del package actual conserva el shadowing vigente.
No se reinterpretan calls ya resueltas por comparar el spelling `print`.

## 10. HIR, MIR, SSA y backend

### 10.1 AST

AST no cambia: sigue siendo una call source de un argumento. La sintaxis de
interpolación y su parser no se modifican.

### 10.2 HIR

No se agrega un opcode de formatting nuevo. Se reutilizan:

- `FormatScopedSharedBorrow` para acceso observacional;
- `InterpolationFragment::Hole` y `InterpolationConversion` para FORMAT;
- `StringOp::Interpolate` para producir el owner;
- `HirStmtKind::StringOutput` para publicación.

`StringOutput` necesita metadata contextual mínima, conceptualmente:

```text
OutputArgumentKind = ExistingString | DirectFormat { format_site }
```

`DirectFormat` exige exactamente un `Interpolate` sintético de un hole y cero
text chunks. La metadata es necesaria para extender los roots estabilizados
hasta el final del write sin cambiar el lifetime de interpolaciones source
ordinarias. No define representación ni admite tipos.

El `FormatSiteId` identifica el plan directo y el hole usa índice cero. Su span
primario es el argumento source. El verifier HIR reconstruye:

- símbolo Core, aridad, newline y argumento final string;
- correspondencia entre `DirectFormat`, site, hole y borrows;
- `formatted_type`, access y conversión con la autoridad FORMAT;
- ausencia de Move/Clone/Alias y escape de referencias FORMAT;
- que `ExistingString` no se haga pasar por un direct plan.

### 10.3 MIR

MIR expresa la operación con machinery existente:

```text
Evaluate/Stabilize
Borrow(format metadata), si corresponde
Interpolate(one hole) -> owned string
EndFormatBorrow
CoreCall Print/Println(owned string) [unwind -> cleanup]
Drop formatted string
Drop stabilized direct root, si corresponde
```

No aparece `PrintValue`, `FormatToStdout` ni un opcode por tipo. El lowering de
`DirectFormat` difiere cleanup de sus roots hasta después del CoreCall. Los
landing pads conservan una pila explícita de owners inicializados y nunca hacen
Drop antes de `EndBorrow`.

### 10.4 SSA

SSA conserva el plan `Interpolate`, los `Borrow`/`EndBorrow`, el `CoreCall` y su
unwind edge. Sus verificadores deben exigir en todo path no abortivo:

- evaluación única del argumento;
- uso del borrow sólo por el plan FORMAT asociado;
- `EndBorrow` después del último count/write y antes de output;
- root directo vivo a través del CoreCall;
- Drop único del string y del root, normal o excepcional;
- identidad Core y flag newline consistentes;
- ningún phi, Store, Return o call arbitraria con la referencia FORMAT.

Dumps y corruption tests deben poder distinguir `ExistingString` de
`DirectFormat` y fallar cerrados ante conversiones, sites, types, lifetime o
cleanup falsificados.

### 10.5 Backend y reachability

El backend recibe un `StringOp::Interpolate` verificado y después el mismo call
stdout que hoy. Reutiliza count/write de FORMAT, recetas matemáticas y
`aether_io_stdout`/la frontera Core existente. No inspecciona el TypeId para
elegir representación.

Reachability permanece composicional:

- `println("literal")` no debe enlazar FORMAT sólo por usar output;
- `println(42)` enlaza únicamente los helpers FORMAT requeridos por integer y
  stdout;
- Matrix/Vector enlazan su receta y element primitives alcanzables;
- cuerpos no alcanzables no materializan FORMAT ni IO.

## 11. Diagnostics

Las fallas de admisión usan la misma frontera E0340 de un hole, con el span del
argumento y contexto de call. Forma recomendada:

```text
E0340: type MatrixView<float64> is not formattable by the active FORMAT profile
       as the argument of println
```

La palabra puede ser `interpolable` si se conserva el wording actual, pero el
código, la causa y la consulta deben ser los mismos. Después de peeling, el
diagnóstico nombra el pointee no admitido, no `ref T` ni una dirección.

Se conservan por causa:

- diagnóstico de aridad/type arguments para llamadas que no tienen exactamente
  un valor;
- diagnósticos ordinarios de nombres/tipos al resolver la expresión;
- E0340 para tipo FORMAT no admitido, incluidos views y elementos matemáticos
  no soportados;
- diagnósticos de borrow/provenance para conflictos reales;
- uso-after-move si el owner ya estaba movido;
- addressability/stabilization si el tipo es admitido pero el source no puede
  prestarse de forma segura.

Nunca se imprime una address, debug representation o nombre de tipo. No hay
fallback, warning con ejecución, `Any`, reflection, TypeId dispatch ni llamada
a `toString`.

## 12. Interpolación permanece intacta

Estas formas conservan parser, evaluación, semántica y representación:

```aether
println("x = ${x}");
println("${nombre} pesa ${peso} kg");
string s = "${matrix}";
```

El hecho de que output directo reutilice internamente un plan de un hole no
reemplaza interpolación ni la desazucara a una API multi-argument. Texto y holes
siguen componiéndose en un único `StringOp::Interpolate` source.

## 13. Qualification futura

La suite de implementación debe cubrir byte-exact output en O0 y O2 para:

```aether
println(42);
println(1.5);
println(true);
println('a');
println("hola");

println(rowVector);
println(columnVector);
println(matrix);

println(factor.L);
println(factor.U);

print(x);
println(x);
```

Cada caso admitido se compara contra `print("${value}")` o
`println("${value}")` según corresponda. La matriz de prueba incluye:

1. todos los anchos/signedness integers y aliases transparentes;
2. float32/float64 con umbrales, vecinos ULP, subnormals, `-0`, NaN e Inf;
3. bool exacto, char UTF-8 de uno a cuatro bytes y U+0000;
4. string vacío, multibyte, escapes ya decodificados y U+0000;
5. Row/Column/Matrix no vacíos y zero-shapes de MATH-FORMAT;
6. owner repetido y reutilizado tras output;
7. field/nested field sin `MoveField` ni partial move;
8. `ref T`, nested refs y `ref mut T` con mutación posterior;
9. rvalue owner y projected rvalue con evaluación once y Drop once;
10. stdout success, write parcial/failure e `IOException` recuperada con cleanup
    exacto;
11. argumento que lanza antes de inicializar o después de roots previos cuando
    resulte aplicable a la expresión;
12. tipos, views y element types no soportados rechazados con E0340;
13. aridad cero/múltiple y type arguments rechazados;
14. dumps/corruptions HIR, MIR y SSA para access, conversion, site, Core
    identity, newline, unwind y Drop;
15. ausencia de Clone/Alias/retain/COW, strings por elemento y dispatch de tipo;
16. reachability FORMAT/IO y equivalencia nativa O0/O2;
17. regresión completa de interpolation, FORMAT-BORROW, MATH-FORMAT, Core, IO y
    ownership.

Las pruebas de temporales deben instrumentar destrucción y verificar que el
root directo sigue vivo durante el write, y que en un stdout failure el string
y el root se destruyen una sola vez por el landing pad.

## 14. Compatibilidad con multi-argument futuro

Un milestone posterior podrá estudiar:

```aether
println("x = ", x);
println("L = ", L, ", U = ", U);
```

Deberá definir aridad, heterogeneidad, evaluación izquierda-derecha,
stabilization y conflictos entre argumentos, publicación, write parcial,
unwind y allocations. PRINT-VALUE-V1 no decide esos puntos.

La decisión actual no lo bloquea: `print`/`println` conservan una identidad
Core de familia y el resolver puede incorporar una rama de aridad posterior.
La aridad uno permanece semánticamente un valor FORMAT; no debe reexplicarse
como un caso variádico de longitud uno ni cambiar sus costes retroactivamente.

## 15. Alternativas rechazadas

| Alternativa | Motivo de rechazo |
|---|---|
| overload por cada scalar y agregado | duplica admisión, escala mal y permite divergence respecto de holes |
| conversión implícita general `T -> string` | amplía el lenguaje fuera de FORMAT y oculta allocation |
| llamar `str(value)` para todo | no cubre string/MATH-FORMAT y convertiría una API escalar en autoridad incorrecta |
| formatter propio dentro de print | crea dos spellings y dos runtimes |
| streaming directo V1 | mezcla FORMAT/IO y complica partial write/unwind sin necesidad funcional |
| dispatch runtime por TypeId/Any/reflection | pierde selección estática y requiere fallback/boxing |
| imprimir debug repr/address | viola el contrato de bytes canónicos y ownership |
| mover o clonar owner/field | consume estado o introduce costes ocultos |
| mantener overload público string más generic | el resolver actual no necesita dos candidatos y aparecería ambigüedad artificial |
| reemplazar interpolation por argumentos múltiples | pierde composición como string y deja sin diseñar orden/unwind multi-arg |

## 16. Fuera de alcance

- output de cero o múltiples argumentos;
- `printf`, format strings dinámicos, specifiers, width, padding o named args;
- logging y selección de stderr;
- split `Debug`/`Display`;
- formatting definido por usuario o capability pública;
- conversión implícita general a string;
- views matemáticas u otros tipos no admitidos por FORMAT;
- streaming/fusión FORMAT→stdout;
- cambios al modelo de errores stdout/stderr;
- nueva garantía de cleanup para traps abortivos.

## 17. Orden de implementación futuro

1. Centralizar `format_admission(formatted_type)` y hacer que los holes actuales
   la usen sin cambiar resultados.
2. Extraer el resolver contextual de un operand FORMAT para compartir Place,
   ref, temporary, `access` y conversion.
3. Ampliar la familia source Core de aridad uno y conservar el fast path string.
4. Construir el plan `DirectFormat` de un hole para non-string.
5. Agregar la metadata contextual mínima a `StringOutput` y su verificador.
6. Bajar el plan con cleanup de root extendido a través del CoreCall y reforzar
   MIR/SSA, incluidos unwind/corruptions.
7. Reutilizar backend FORMAT y stdout sin agregar selección de tipo.
8. Incorporar qualification positiva, negativa, lifecycle, reachability y
   equivalencia O0/O2.
9. Ejecutar workspace tests, fmt, clippy, differential y `git diff --check`.

No se habilita parcialmente un subconjunto distinto del perfil FORMAT activo.

## 18. Criterio de cierre futuro

PRINT-VALUE-V1 sólo podrá declararse implementado cuando `print(value)` y
`println(value)` acepten exactamente la admisión vigente de holes, produzcan
bytes iguales a la interpolación equivalente, observen owners sin consumirlos,
mantengan temporales directos hasta completar output, limpien exactamente una
vez en éxito y `IOException`, y no incorporen otra tabla de formatting ni
dispatch runtime.
