# GENERAL-ARCH-1 — modelo de `string` y frontera de texto

Estado: **DECISIÓN DE ARQUITECTURA; SIN ADMISIÓN NI IMPLEMENTACIÓN**, 2026-09-12.
Este milestone no modifica parser, HIR, MIR, SSA, LLVM ni runtime. La admisión
de cualquier parte requiere un vertical native-first independiente y su
promoción explícita al contrato semántico.

## 1. Decisión resumida

Aether debe tener un tipo fundamental `string` con estas propiedades:

- valor inmutable, no nulo y estáticamente tipado;
- secuencia de Unicode scalar values representada siempre como UTF-8 válido;
- semántica de valor e igualdad por contenido, sin identidad pública;
- handle opaco de una palabra a backing compartido;
- backing dinámico con strong ARC no atómico en el bootstrap;
- literales y vacío como objetos estáticos inmortales con la misma forma de
  handle;
- `Copy = false`, `Relocatable = true`, `Storable = true` y
  `needs_drop = true` en las consultas estructurales del compilador;
- duplicación ergonómica mediante la operación semántica `Alias`, distinta de
  `Copy`; resultados frescos usan `Transfer` y todo owner restante usa `Drop`;
- sin copy-on-write, sin mutación del payload, sin `class String`, sin dynamic
  typing y sin SSO en el bootstrap.

El significado requerido es:

```aether
string a = "hello"; // Transfer del owner inmortal del literal al slot a
string b = a;       // Alias: a sigue válido; b obtiene otra obligación owning
```

Para un objeto heap, `Alias` implica conceptualmente un retain. Para un objeto
inmortal el retain físico es un no-op. Esta diferencia no es observable como
identidad; sí debe ser inspeccionable como costo de ownership.

```aether
string c = a + " world";
```

Evalúa operandos de izquierda a derecha, los toma prestados durante la
operación, calcula y comprueba el tamaño, crea un resultado UTF-8 owned y lo
transfiere a `c`. Con dos operandos no vacíos, el bootstrap realiza una
allocation exacta y copia ambos rangos una vez: tiempo O(bytes(a)+bytes(b)) y
espacio O(bytes(result)). `a` permanece válido. No se modifica ningún backing
y no hay COW.

## 2. Autoridad y evidencia consultada

Esta decisión refina la sección 7 del
[contrato semántico](AETHER_V1_SEMANTIC_CONTRACT.md), que ya fija `string`
inmutable, no nulo y UTF-8 válido, y cierra su dirección provisional de ARC.
Respeta el [charter](AETHER_V1_LANGUAGE_CHARTER.md), la
[arquitectura por fases tipadas](AETHER_COMPILER_ARCHITECTURE.md) y las reglas
de evaluación, lifecycle, layout y C ABI vigentes.

El reporte [OOP-V1](OOP_V1_REPORT.md) aporta el vocabulario probado
`Alias`/`Transfer`/`Drop`, el retain antes
de reemplazar y la distinción entre semántica owning y RC físico. OOP-OPT-1
([reporte](OOP_OPT_1_REPORT.md)) confirma que una optimización puede quitar retain/release sólo después de SSA
verificada, sin borrar la obligación lógica. `string` reutiliza esos principios,
pero no adquiere identidad de clase, dispatch, descriptor de clase ni igualdad
por puntero.

[EXCEPTION-ARCH-2](EXCEPTION_ARCH_2.md) aporta la frontera de cleanup: los futuros unwinds ejecutan
`Drop` de strings ya inicializados; los traps de tamaño, allocation y corrupción
ARC siguen siendo fail-fast no capturable y no prometen unwind.

La implementación legacy y
[`STRING_RUNTIME_DESIGN`](../aether/STRING_RUNTIME_DESIGN.md) son evidencia
histórica valiosa: demostraron un handle de una palabra, objetos inmortales,
UTF-8 length-aware, ARC, concat, igualdad y transporte por aggregates. Sus
offsets de 24 bytes, nombres de helpers, `int` de 32 bits, convención borrowed
de parámetros y runtime LLVM embebido no son autoridad para la reconstrucción.

## 3. Naturaleza semántica del tipo

`string` es un **tipo fundamental owning con semántica de valor**. “Fundamental”
significa que el compilador conoce su identidad, literales, operaciones básicas,
propiedades de lifecycle y frontera runtime. No significa que sea un escalar
bitwise-copyable ni que todos sus algoritmos deban ser intrinsics.

No es:

- una `class String` ni un subtipo de una raíz de objetos;
- un alias de `Array<byte>`, `List<byte>`, `Buffer<byte>` o `ref byte`;
- una referencia prestada al source file;
- un C string terminado en cero;
- una colección indexable genérica;
- un valor dinámicamente despachado.

Dos valores pueden compartir backing, pero el lenguaje no expone dirección,
contador, inmortalidad ni identidad del backing. Toda operación observable se
define sobre el contenido.

## 4. Propiedades estructurales y ownership

### 4.1 Por qué `string` no es `Copy`

En Aether, `Copy` significa duplicación estructural sin crear una obligación de
ownership ni requerir cleanup. Duplicar un string heap crea un nuevo strong
owner y su futuro `Drop`; por ello `string` es `Copy = false` aunque la sintaxis
ordinaria de alias sea cómoda y O(1).

Marcarlo `Copy` mezclaría una copia trivial con un retain effectful, permitiría
`T: Copy` donde el costo y cleanup no son válidos y volvería inseguras las
copias bitwise de aggregates. La inmutabilidad no implica `Copy`.

`string` sí es `Relocatable`: mover físicamente el handle desde un slot vivo a
otro no duplica el owner y no toca el refcount. También es `Storable` y
`needs_drop`; esas propiedades se componen estructuralmente en structs, enums y
colecciones cuando cada vertical admita ese almacenamiento.

`Alias` es inicialmente una capacidad intrínseca del tipo `string`, no una
consecuencia estructural de `Copy`. Por ello `T: Copy` no acepta `string`. Un
aggregate que contiene string es no-Copy y, bajo el lifecycle general actual,
se mueve como un todo y se destruye recursivamente; no adquiere una copia
implícita field-by-field. Permitir duplicación genérica o estructural de owners
compartidos requiere una futura capability `Alias`/`Clone` diseñada para todos
los tipos, no una excepción silenciosa introducida por este milestone.

### 4.2 Operaciones owning

| Contexto | Operación semántica | Resultado |
|---|---|---|
| inicializar desde literal o resultado fresco | `Transfer` | el destino toma la obligación existente |
| inicializar desde lvalue | `Alias` | source y destino siguen válidos |
| pasar lvalue por valor | `Alias` | caller y callee tienen owners independientes |
| pasar resultado fresco por valor | `Transfer` | no se agrega un owner intermedio |
| retornar lvalue | `Alias` antes del cleanup local | caller recibe un owner válido |
| retornar resultado fresco | `Transfer` | caller recibe el owner producido |
| `ref string` | borrow explícito | no crea owner ni prolonga lifetime |
| reubicar storage | `Relocate` | transferencia física sin retain/release |
| fin de lifetime | `Drop` | release o no-op inmortal |

Esta convención sigue el modelo compartido de OOP-V1, no la convención borrowed
por defecto del legacy. Una ABI interna puede optimizar un parámetro probado
como borrow, pero esa decisión física no cambia el contrato por valor.

### 4.3 Asignación y self-assignment

`dst = src` evalúa primero el RHS. Para un lvalue adquiere su Alias antes de
publicar el reemplazo y sólo entonces hace Drop del valor anterior. Así la
autoasignación y dos handles al mismo backing son seguras. La implementación
puede reconocer self-assignment exacta como no-op.

Los joins conservan las mismas obligaciones `Owned`/`Moved`/`MaybeMoved` del
lifecycle general. Un string movido no es utilizable; no se inventa un null o
un vacío como estado source-visible posterior al move.

## 5. Representación bootstrap

### 5.1 Handle y backing

El valor native es un handle opaco, no nulo y de una palabra, que apunta al
inicio de un objeto string. El objeto contiene conceptualmente:

```text
StringObject {
    byte_length: usize
    strong_count: u64
    flags: private
    data: u8[byte_length]
    trailing_zero: u8
}
```

El objeto dinámico y su payload forman una allocation contigua en el
bootstrap. `data` no cambia tras publicación. `strong_count` es el único estado
mutable y no forma parte del valor textual.

El cero auxiliar facilita adaptadores C, pero no pertenece al contenido y
nunca es autoridad de longitud. U+0000 puede aparecer dentro de `data`; todas
las operaciones Aether usan `byte_length`.

El orden exacto de campos, offsets, padding, alineación, bits de flags y nombres
de símbolos son ABI privada derivada del target layout. GENERAL-ARCH-1 no
estabiliza el header legacy ni permite que código Aether o C lo inspeccione.

### 5.2 Reference counting

- Un objeto heap se publica con strong count uno.
- `Alias` adquiere una obligación; el lowering físico hace retain salvo
  elisión verificada.
- `Drop` libera una obligación; la transición uno a cero libera el
  objeto una vez.
- Retain sobre máximo, release de cero, null o descriptor inválido son traps de
  invariantes, nunca wrapping ni excepciones capturables.
- El count bootstrap es no atómico y no autoriza compartir strings dinámicos
  entre threads. Concurrencia requiere una decisión posterior sobre ARC
  atómico, transferencia estática o GC.
- El runtime no necesita weak references ni cycle collection: un string no
  contiene owners a otros objetos.

La optimización ARC usa el patrón de OOP-OPT-1: las operaciones lógicas
permanecen en SSA verificada y sólo se suprimen sitios físicos con prueba de un
owner independiente y de la posición de destrucción final.

### 5.3 Literales, vacío y heap

Todo literal se codifica y valida en compile time y se materializa como objeto
read-only estático con forma lógica compatible con el handle ordinario. Está
marcado `IMMORTAL`; retain y release físicos son no-op. Su lifetime cubre el
proceso y nunca se copia al heap sólo por asignarlo, pasarlo o retornarlo.

`""` usa un singleton estático no nulo. Literales de bytes idénticos pueden
deduplicarse dentro de un artefacto y el linker puede fusionarlos, pero esa
identidad no es observable ni constituye interning público.

Los strings producidos en runtime son heap-backed y usan ARC. Ambos casos
circulan con el mismo handle; no hay un tagged union source-visible ni dos ABI
de string. El programa no puede preguntar si un string es estático o dinámico.

GENERAL-ARCH-1 no decide inicialización implícita de locales. Si una futura
regla general requiere un default de `string`, el único candidato coherente es
el singleton vacío, pero eso no se admite aquí.

## 6. UTF-8 y política Unicode

Un `string` publicado contiene exactamente una secuencia UTF-8 bien formada:
sin overlong encodings, surrogate code points, unidades truncadas ni valores
mayores que U+10FFFF. Por ello cada secuencia de Unicode scalar values tiene
una representación byte única y la igualdad escalar puede implementarse con
igualdad de bytes.

- `char` representa un Unicode scalar value, no un byte ni un grapheme.
- No hay normalización implícita. NFC y NFD visualmente equivalentes pueden ser
  strings distintos.
- No hay case folding, collation o clasificación dependiente de locale en el
  core.
- U+0000 es contenido válido.
- Los source files y escapes deben producir scalars válidos; un error recibe
  diagnóstico Aether en la frontera fuente, no una excepción del host.
- Bytes externos se validan antes de publicar un string. No hay replacement
  silencioso; una API lossy futura debe decirlo en el nombre.

Grapheme clusters, normalización, case mapping y collation requieren tablas
Unicode versionadas y pertenecen a la futura biblioteca `Text`.

## 7. Longitud, indexing, slicing e iteración

### 7.1 Longitudes

La única longitud O(1) del objeto es `byte_length`. La operación core debe
nombrar su unidad, provisionalmente `byteLength(s) -> usize`. No se admite un
`length` ambiguo ni narrowing implícito a `int`.

Contar Unicode scalar values es O(bytes) y pertenece a `Text`, con un nombre
explícito como `Text.codePointCount(s)`. Contar grapheme clusters pertenece a
la capa Unicode futura y su resultado depende de una versión de datos Unicode.

### 7.2 Indexing

No se admite `s[i]`. Su apariencia O(1) no puede expresar si `i` cuenta bytes,
scalars o graphemes, ni qué tipo devuelve. Tampoco se sobrecarga según el tipo
del índice.

El acceso a bytes debe ocurrir sobre `Bytes` o un byte span explícito y devolver
`byte`; nunca crea por sí solo otro string. El acceso por posición de code point,
si se ofrece, será una función `Text` con complejidad O(bytes recorridos) y
resultado `char`, no bracket indexing.

### 7.3 Slicing y views

El bootstrap no admite `s[a:b]`, substring ni views. La primera operación de
substring recomendada es una API `Text` por límites de code points que devuelve
un `string` owned y copia el rango. Debe validar límites antes de allocation y
nunca publicar UTF-8 cortado.

Una futura view textual debe ser un tipo distinto, provisionalmente
`StringView`, con `{data, byte_length}` y provenance del owner. Será borrowed,
`Copy`, no owning, no `Storable` bajo el lifetime actual y no podrá sobrevivir
al backing. No se introduce antes de que el modelo general permita expresar su
lifetime. Esto evita que una substring pequeña retenga inadvertidamente un
backing enorme y evita convertir todo `string` en un descriptor ancho.

### 7.4 Iteración

La iteración textual canónica, cuando el protocolo de iteración la admita, es
por `char`/Unicode scalar value:

- toma prestado el string durante la iteración;
- mantiene un byte offset privado;
- decodifica el siguiente scalar en O(1) por paso (uno a cuatro bytes);
- cuesta O(byteLength) en total, no allocation y produce `char` Copy;
- no necesita una rama de UTF-8 inválido porque el invariante ya está probado.

Iterar bytes requiere una vista/conversión de bytes explícita. Iterar graphemes
es una operación de `Text.Unicode`, no el significado de `for` sobre string.

## 8. Operaciones core

### 8.1 Concatenación

`string + string -> string` es una operación fundamental estática, no dispatch
de método ni overload dinámico. Toma prestados ambos operandos y devuelve un
owner.

Para dos contenidos no vacíos, el bootstrap:

1. carga las longitudes;
2. comprueba suma, header, terminador y límite del allocator;
3. reserva una allocation exacta;
4. copia left y right en orden;
5. escribe el cero auxiliar y publica count uno.

Si un operando es vacío, puede devolver un Alias owned del otro; si ambos son
vacíos devuelve el singleton. Por tanto `+` es allocation-capable, no una
promesa de allocation incondicional. Las cadenas `a+b+c` conservan
asociatividad/evaluación source y pueden asignar temporales en el primer
vertical. Fusión, cálculo total y builders privados son optimizaciones futuras
que deben preservar traps, orden y ownership y volver a verificar SSA.

No hay COW: ningún resultado modifica o reutiliza como writable el backing de
un operando, aunque su count sea uno.

### 8.2 Igualdad

`==` y `!=` comparan contenido:

1. handles iguales permiten éxito inmediato;
2. longitudes distintas son desiguales;
3. longitud cero es igual;
4. se comparan exactamente `byte_length` bytes.

Es O(1) en fast paths y O(n) en el peor caso, no allocation y no observa locale
ni normalización. Los operadores relacionales no se admiten para `string`; un
orden bytewise interno o una collation humana futura no son lo mismo.

### 8.3 Hashing futuro

Un hash compatible debe consumir exactamente los mismos bytes que igualdad,
incluido U+0000. Los containers expuestos a input adversarial deben usar seed
por proceso; el valor no es persistente ni estable entre ejecuciones. Un hash
estable necesita API y algoritmo versionados separados.

No se reserva ni actualiza un cache de hash en el header bootstrap. Agregarlo
requiere medición y revisar concurrencia, pero no cambia la igualdad.

### 8.4 Costos observables e inspeccionables

| Operación | Costo semántico bootstrap |
|---|---|
| Alias de lvalue | O(1), puede ejecutar un retain |
| Transfer/Relocate | O(1), sin retain ni copia de payload |
| Drop | O(1), puede ejecutar release y free final |
| byte length | O(1) |
| igualdad | O(1) fast path; O(n) peor caso |
| concatenación no vacía | O(n+m), una allocation y n+m bytes copiados |
| contar/ubicar code points | O(bytes recorridos) |

El compilador debe poder reportar obligaciones lógicas y, por separado, sitios
físicos de retain/release/allocation eliminados o conservados. El usuario puede
usar un borrow explícito en APIs sensibles y una futura herramienta de costos;
la sintaxis cómoda no convierte Alias en Copy ni oculta concat como operación
pura.

## 9. Strings y bytes

No hay conversión implícita en ninguna dirección.

- `string -> Bytes` owned copia los bytes UTF-8 exactos.
- Una futura byte view puede ser zero-copy y borrowed, con lifetime explícito;
  no es un string mutable.
- `Bytes -> string` valida UTF-8 y copia a backing owned antes de publicar.
- El fallo de validación es un error esperado estructurado (`Result` o forma
  que se decida), no texto de reemplazo y no allocation failure.
- Una conversión lossy futura debe ser explícita y documentar U+FFFD.
- `unsafeFromUtf8` no forma parte de la API segura ni de este milestone. Sólo
  podría existir en la frontera low-level con el invariante como precondición.

`Bytes` y la forma exacta de `Result` aún no están admitidos; estas reglas fijan
la frontera para que sus futuros diseños no redefinan `string`.

## 10. Formatting, interpolación y salida

Formatting e interpolación se difieren. Cuando se diseñen:

- la selección de formato será estática; no habrá `toString` dinámico universal;
- las expresiones se evaluarán una vez y de izquierda a derecha;
- cada conversión tendrá reglas deterministas y locale explícito cuando
  corresponda;
- los fragments alimentarán un builder privado o una API de stdlib y producirán
  un único string owned cuando sea posible;
- el builder mutable no será un estado de `string` ni justificará COW.

`print` y `println` pertenecen a la superficie core/IO, no a métodos de
`string`. Reciben el valor como borrow durante la llamada y escriben exactamente
`data[0:byte_length]`; nunca usan `%s`, `strlen` ni el cero auxiliar. `println`
agrega su separador definido por la API de salida después del contenido. Aceptar
otros tipos requiere formatting separado y no cambia el modelo string.

## 11. Runtime y FFI

El runtime mínimo privado es responsable sólo de lo que conoce representación,
allocation, invariantes o lifecycle:

- singleton vacío y acceso a literal;
- allocate-from-valid-UTF-8 y validación de input externo;
- byte length/data borrowed accessors;
- retain/release;
- concatenación e igualdad length-aware;
- bridge length-aware usado por output;
- traps de tamaño, allocation y corrupción.

Los helpers forman parte de un runtime versionado detrás de C ABI generado, no
texto LLVM copiado por printers. Sus effects —borrow, allocation, trap, owner
result— deben estar declarados; LLVM no los infiere desde nombres.

La frontera C nunca expone el header:

- lectura síncrona: borrowed `{const uint8_t *data, size_t length}` con UTF-8
  válido y keepalive del owner durante la call;
- transferencia duradera: opaque handle más funciones versionadas explícitas
  de retain/release, con allocator ownership documentado;
- ingreso: `(data,length)` se valida y copia; memoria extranjera no se adopta
  como backing general;
- `const char *` sólo mediante adapter que trate el terminador y rechace ceros
  internos cuando la API C no pueda representarlos;
- ninguna excepción Aether o extranjera cruza `extern "C"`.

El layout privado puede cambiar al recompilar compiler y runtime juntos. No se
promete compatibilidad con el handle legacy aunque ambos se escriban `ptr`.

## 12. Fallos, exceptions y cleanup

Concatenación y construcción comprueban aritmética de tamaño antes de allocation
y no publican objetos parciales. `AllocationSizeOverflow`, `AllocationFailure`
y corrupción/overflow ARC son traps fail-fast no capturables. Conforme a
EXCEPTION-ARCH-2, no tienen exceptional successor y no prometen cleanup.

La validación UTF-8 de input ordinario es un error esperado y debe devolverse
estructuradamente cuando existan `Bytes`/`Result`. No debe confundirse con OOM
ni convertirse automáticamente en una language exception.

Cuando las excepciones estén admitidas, cada string completamente inicializado
en un scope que unwinde ejecuta su `Drop` exactamente una vez, en el orden de
cleanup general. Retain, release y destrucción de string son non-throwing. Si
formatting futuro llama código que puede lanzar, temporales y fragments ya
inicializados requieren cleanup excepcional explícito antes de SSA.

## 13. Core, runtime y futura biblioteca `Text`

| Capa | Responsabilidad |
|---|---|
| Lenguaje/core | `string`/`char`/`byte`, literales, UTF-8 válido, inmutabilidad, Alias/Transfer/Drop, `+`, `==`/`!=`, byte length explícito y futura iteración por `char` |
| Runtime privado | layout, static/heap backing, validation, allocation, ARC, byte accessors, concat/equality y transporte length-aware |
| Core/IO | `print`/`println` de string borrowed; no filesystem ni formatting general |
| STD `Text` | code-point count/access, owned substring, search, replace, split, trim, parsing y formatting deterministas |
| STD `Text.Unicode` | graphemes, normalización, case mapping y collation con datos/versionado explícitos |
| Futuro storage | `Bytes`, byte views y un builder mutable público si la evidencia lo justifica |

Que una operación use un helper runtime no la vuelve builtin pública. Que una
API esté en `Text` no impide al compilador reconocerla para optimizar, pero su
semántica no debe depender de un opcode o backend particular.

## 14. Alternativas evaluadas

| Alternativa | Ventajas | Costos | Decisión |
|---|---|---|---|
| Immutable ARC backing | Alias O(1), valor denso de una palabra, lifetime determinista, literales compatibles, concat simple | retain/release y una indirección; threading pendiente | **Elegida para bootstrap** |
| Deep-copy value string | identidad irrelevante y ownership local simple | cada asignación/call/field puede ser O(n); costo oculto y mala composición | Rechazada |
| Copy-on-write | copias baratas y posible mutación futura | branch de unicidad, semántica compleja, invalida views/hash y no aporta nada a un tipo inmutable | Rechazada inicialmente |
| Class-based `String` | reutiliza ARC/descriptors/métodos | identidad/null/dispatch/cycles impropios; confunde valor textual con objeto | Rechazada |
| Inline/SSO hybrid | evita heap en textos cortos y mejora localidad | handle más ancho o tagged, más estados en ABI/aggregates, copy/drop complejos | Diferida tras medición |

Immutable ARC es el mejor bootstrap porque separa valor e implementación,
mantiene Alias barato, hace determinista el cleanup, permite literales sin heap
y conserva un único carrier compacto. Sus costos importantes —allocation,
retain/release y scans UTF-8— son clasificables e inspeccionables. No condiciona
la superficie a COW ni a una jerarquía de objetos y deja SSO como optimización
posterior con recompilación.

## 15. Primer vertical acotado recomendado

**GENERAL-V1 — immutable UTF-8 string spine**, inicialmente Linux x86-64,
single-thread, runtime ABI privada y traps abortivos.

Debe admitir solamente:

- `string` canónico y literals ASCII/Unicode/vacío como objetos inmortales;
- locals, asignación, by-value direct parameters y returns con
  Alias/Transfer/Drop explícitos;
- `+`, `==`, `!=` y la consulta core de byte length;
- `print`/`println` de un string borrowed y length-aware;
- objetos heap de concat con una allocation, ARC no atómico y cleanup normal;
- branches/early returns suficientes para verificar cleanup condicional;
- HIR/MIR/SSA explícitos y verificación independiente cuando ese vertical se
  implemente;
- O0/O2, contadores de allocation/retain/release/final free, NUL embebido,
  UTF-8 multibyte, overflow, OOM inyectable y sanitizers.

Debe excluir en ese primer vertical:

- fields de struct/class y elementos de Array/List/Buffer/Vector/Matrix;
- generics, interfaces, virtual calls, FFI pública y threads;
- indexing, slicing, views, iteración, `Bytes` y decode público;
- interpolation, formatting, parsing, trim/split/search y builder público;
- hashing, interning público, COW, SSO, normalization y graphemes;
- recoverable exceptions y cualquier cambio a traps.

Esta frontera prueba primero el carrier y lifecycle. Un vertical posterior
puede admitir composición estructural en aggregates/collections usando las
mismas propiedades, sin agregar casos ad hoc para string.

## 16. Decisiones abiertas y gates

| Tema | Gate antes de admisión correspondiente |
|---|---|
| Spelling de `byteLength` y protocolo de miembros | Cerrar en GENERAL-V1 sin admitir `length` ambiguo |
| Grammar exacta de escapes y multiline literals | Decisión léxica con spans UTF-8 y diagnostics propios |
| Layout físico/header/flags | Derivarlo del target descriptor y ABI runtime versionada |
| Límite máximo de string | Política de target/runtime; siempre con aritmética checked |
| Strings globales no literales | Espera reglas generales de module initialization |
| Aggregate/container storage | Vertical posterior con hooks estructurales y corruptions |
| Iteration syntax/protocol | Mantener semántica por `char`; integrar con el protocolo general |
| `Bytes`, byte view y `Result` de decode | Diseño separado de storage/errores; sin conversión implícita |
| Owned substring y futura `StringView` | Primero cerrar lifetimes de views no léxicas |
| Formatting/interpolation protocol | Selección estática, orden, locale y cleanup excepcional |
| Hash/container seed y stable hash | Cerrar junto con Map/Set y persistencia, no en el header ahora |
| Concurrencia | Elegir ARC atómico, transferencia o GC antes de sharing cross-thread |
| Public runtime/FFI ABI | Schema generado, ownership y adapters; nunca exponer header privado |
| SSO/cache/interning dinámico | Sólo tras perfiles y sin cambio semántico accidental |

## 17. Consecuencias

La asignación de string es ergonómica y O(1), pero no finge ser una copia
trivial. La concatenación expresa una operación potencialmente costosa y
allocation-capable. Las unidades textuales nunca quedan implícitas: bytes,
scalars y graphemes tienen superficies distintas. El runtime se mantiene
pequeño y la futura `Text` puede crecer sin transformar `string` en class ni
congelar algoritmos Unicode dentro del compilador.
