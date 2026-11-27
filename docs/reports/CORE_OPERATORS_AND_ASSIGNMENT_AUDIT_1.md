# Aether — CORE-OPERATORS-AND-ASSIGNMENT-AUDIT-1

Estado: **AUDIT COMPLETE**

Fecha de auditoría: 2026-11-27

Autoridad inspeccionada: `compiler-next` en `5e136069` (`main`)

Alcance: auditoría documental; no se modificó código productivo ni se implementó sintaxis.

## 1. Resumen ejecutivo

El compilador oficial implementa asignación simple y un modelo de `Place` reutilizable a través de HIR, MIR, SSA y LLVM. Los Places admiten raíces local, dereference mutable y field de class, con proyecciones anidadas `Field` e `Index`. La asignación simple alcanza variables, fields, índices escalares de Buffer/Array/List/Vector/Matrix/views mutables y `*ref mut`; slice assignment tiene una operación separada. Mutabilidad, const, bounds, tipos y ownership se verifican de forma explícita.

No están implementados `+=`, `-=`, `*=`, `/=`, `%=`, `++`, `--`, bitwise ni `**`. Tampoco existe hoy la función fuente `pow`. Los documentos históricos que describen `+=` o potencia con `^` no reflejan la superficie de `compiler-next` y, para este roadmap, deben tratarse como deuda de reconciliación documental, no como comportamiento vigente.

La infraestructura de Place es suficiente para una implementación incremental, pero el lowering actual de asignación simple evalúa primero el RHS y después los operandos dinámicos del Place. El reproducer `list[index()] = rhs()` imprimió `rhs` y luego `index`. Por tanto, para fijar el orden recomendado de compound assignment —destino/proyecciones, lectura anterior, RHS, operación, checks, escritura— no basta con construir textualmente `p = p + rhs` ni con reutilizar sin cambios el orden de `HirStmtKind::Assign`. Debe estabilizarse una sola instancia del Place antes del RHS.

## 2. Preflight y autoridad

### Hechos verificados

- Branch: `main`.
- HEAD: `5e136069 feat(compiler-next): admit native integer slice bounds`.
- `origin/main`: `18b94662`; la rama está `ahead 2`.
- Commits locales adicionales: `9ce07c86` y `5e136069`.
- La política vigente declara a `compiler-next` y a la CLI Rust `aether` como únicas autoridades oficiales (`docs/architecture/COMPILER_AUTHORITY.md:1-28`).
- La CLI oficial usada fue `compiler-next/target/debug/aether` con `check`, `run` y `build --emit`.
- Había cambios previos en `examples/ProbandoNR/`, reportes no versionados, un binario no versionado y numerosos artefactos ignorados, incluyendo `scrap/` y `compiler-next/target/`. Todos se preservaron.
- No se ejecutó `reset`, `clean`, `stash`, commit ni push. No se consultaron implementaciones legacy como autoridad.

### Cambios preexistentes preservados

`examples/ProbandoNR/probandoNR2.ae`, `probandoNR3`, `probandoNR4`, `probandoNR4.ae`, `probandoNR3C`, `docs/reports/CORE_LANGUAGE_CONSOLIDATION_AUDIT_1.md` y `docs/reports/INTEGER_SLICE_BOUNDS_PREFLIGHT.md` no fueron alterados por esta auditoría. `scrap/`, configuraciones locales, locks, binarios y targets ignorados tampoco fueron modificados deliberadamente.

## 3. Inventario real de operadores

### 3.1 Precedencia y asociatividad implementadas

De mayor a menor precedencia, el parser actual usa:

1. postfix: field, method call e index; asociatividad por encadenamiento a izquierda;
2. prefijos `!`, `-`, `*`, `&`, `&mut`; recursivos, por tanto a derecha;
3. `*`, `/`, `%`; izquierda;
4. `+`, `-`; izquierda;
5. `<`, `<=`, `>`, `>=`; izquierda;
6. `==`, `!=`; izquierda;
7. range `a:b` / `a:s:b`; no asociativo;
8. `&&`; izquierda y short-circuit;
9. `||`; izquierda y short-circuit.

La asignación `=` es sintaxis de statement, no expresión, y no tiene asociatividad expresiva. Evidencia: `parser.rs:991-1001,1261-1421`, `ast.rs:367-380,497-588`.

### 3.2 Matriz de operadores fuente

| Familia / sintaxis | Tipos admitidos y resultado | Conversiones | Fallos / evaluación | IR y estado |
|---|---|---|---|---|
| `+` | escalares enteros y floats homogéneos tras widening; genéricos con `Add`; String+String; Vector/Matrix homólogos | widening sólo dentro de signed, unsigned o float; literales contextuales; sin mixed int/float implícito | enteros checked; floats IEEE; operandos izquierda→derecha; matemáticos comprueban shape | HIR/MIR/SSA binary o capability/string/elementwise; LLVM checked intrinsic, `fadd` o runtime. Implementado |
| `-` | escalares numéricos; genéricos `Sub`; Vector/Matrix homólogos | como `+` | entero checked; float IEEE; shape para matemáticos | binary/capability/elementwise; implementado |
| `*` binario | escalares; genéricos `Mul`; scalar×Vector/Matrix y productos algebraicos admitidos | tipos exactos en matemática estructural; scalar común en escalares | entero checked, float IEEE; shape/allocation donde aplica | binary/capability/math; implementado |
| `/` | enteros signed/unsigned, floats; genéricos `Div` | tipo común permitido | cero: trap; signed MIN/-1: trap de overflow; float IEEE | op signed/unsigned checked o `fdiv`; implementado |
| `%` | sólo enteros | tipo entero común | cero: trap; signed MIN%-1 produce 0; float rechazado E0235 | remainder signed/unsigned; implementado |
| unary `-` | enteros signed, floats; genéricos con `Negate` | ninguna adicional | signed checked; unsigned rechazado; float IEEE | `NegateIntegerChecked` / `NegateFloat`; implementado |
| `< <= > >=` | escalares numéricos compatibles; genéricos con `Order` | mismo common-type que escalares | bool result; floats usan ordered comparisons (NaN hace falsas las ordenadas) | HIR/MIR/SSA comparison; `icmp` signed/unsigned o `fcmp o*`; implementado |
| `== !=` | bool, números compatibles, strings, payload-free enums nominales, genéricos `Equal`; null con nullable | widening permitido sólo por reglas comunes | bool; strings por contenido; enum con payload rechazado; refs no tienen identidad pública | comparison o operaciones dedicadas; implementado |
| `&& ||` | `bool × bool -> bool` | ninguna | izquierda primero y RHS condicional | HIR short-circuit; MIR CFG branch/join; implementado |
| `!` | `bool -> bool` | ninguna | evaluación única | HIR logical-not, lowering booleano; implementado |
| `&place`, `&mut place` | Place addressable a `ref T` / `ref mut T` | no es bitwise ni conversión | const/read-only impiden borrow mutable; class-field interior restringido | HIR Borrow con Place/provenance; MIR/SSA Borrow; implementado |
| unary `*ref` | `ref T -> T` en lectura Copy; en contexto Place forma dereference | ninguna | shared permite leer, no escribir; partial move owning rechazado | `HirPlaceBase::Dereference`; implementado |
| `=` | statement sobre Place tipado | RHS se resuelve con tipo esperado del destino | hoy RHS antes de operandos dinámicos del Place en MIR; bounds al materializar dirección | Assign / ReplaceString / ReplaceOwned / Class FieldWrite / SliceAssign; implementado |
| `a:b`, `a:s:b` | range inclusivo para iteración | operandos enteros del perfil | step cero trap; captura una vez | HIR/MIR específico; implementado |
| postfix `.`, `()`, `[]` | miembros/calls/subscript según tipo | contextual según operación | source order; index checked | calls y Place projections; implementado |
| `+= -= *= /= %=` | ninguno | n/a | `+=` falla en parse E0103 | ausente de tokens, AST, HIR, MIR, SSA y backend |
| statement `i++`, `i--` | ninguno | n/a | falla en parse E0103 | ausente |
| `& | ^ ~ << >>` bitwise | ninguno | n/a | `&` se tokeniza sólo como borrow; `|`, `^`, `~` ni siquiera tienen token; shifts se leen como dos comparadores | ausente |
| `**` | ninguno | n/a | se parsea como multiply seguido de dereference y llega a E0271 en el reproducer | ausente |
| `pow(a,b)` | ninguno en la superficie fuente inspeccionada | n/a | E0212 unknown function | ausente |

Detalles de tipos: `int8/16/32/64`, `uint8/16/32/64`, `isize/usize`, `float32/64` están centralizados en `types.rs:195-315`. El tipo común sólo amplía dentro de la misma familia de signed, unsigned o float (`hir.rs:19561-19571`). `int` es alias transparente de `int64`.

### 3.3 No confundir fuente con LLVM

LLVM contiene `and`, `or`, `xor`, shifts y otras operaciones internas para CFG, descriptors o runtime. Eso no constituye admisión fuente. La lista fuente cerrada está dada por `TokenKind`, `AstUnaryOp`, `AstBinaryOp`, `HirUnaryOp` y `HirBinaryOp` (`lexer.rs:5-130`, `ast.rs:619-662`, `hir.rs:2403-2426`).

## 4. Asignación y modelo de Places

### 4.1 Shapes admitidos

| Fuente | Estado real | Representación principal |
|---|---|---|
| `x = value` | admitido si binding mutable y no es ref/view single-init | base Local, sin proyección |
| `obj.field = value` | structs: admitido según Copy/ownership; class fields usan camino dedicado y receiver `mut` | Field projection o ClassField/FieldWrite |
| `list[i] = value` | admitido para scalar index y element compatible | Place Index, bounds checked |
| `matrix[i,j] = value` | admitido; Matrix usa contrato de índice 2D one-based | una proyección Index con row+column |
| `*r = value` | admitido sólo con `ref mut T`; owning sujeto a ReplaceOwned | base Dereference |
| nested fields/index | admitido mientras cada paso forme un Place y el tipo final satisfaga storage/ownership | cadena ordenada de proyecciones |
| slice target | implementado por `SliceAssign`, separado del Assign escalar | target Place + subscript + snapshot RHS-before-write |
| temporary/call como target | rechazado E0270: debe ser Place existente addressable | ninguno |

`HirPlace` contiene base, proyecciones y `TypeId` final (`hir.rs:1583-1587`). Sus bases son `Local`, `Dereference` y `ClassField`; las proyecciones son `Field` o `Index` con subscript tipado, element type y check (`hir.rs:1684-1709`). MIR conserva esa estructura y convierte expresiones de índice, reference o receiver en `Operand` una vez (`mir.rs:183-218,5653-5703`). SSA vuelve a conservar base y projections (`ssa.rs:116-151`). LLVM calcula el pointer final desde ese único Place.

### 4.2 Resolución, dirección y nested projections

`resolve_expr_place` camina recursivamente desde la raíz hacia afuera. Cada field actualiza el tipo del Place y agrega un `FieldId`; cada index verifica aridad/familia, tipa los selectores en source order, agrega metadata de base/axis y cambia el tipo final al element type (`hir.rs:13681-13912`). La dirección física no se calcula en HIR. MIR baja los operandos del Place; SSA los referencia por valores ya evaluados; LLVM emite GEP/index helpers y bounds checks al usar el Place.

Esto evita re-resolver nombres o field identities, pero no garantiza por sí solo el orden respecto del RHS: `lower_block` baja actualmente `value` antes de `lower_place` (`mir.rs:1686-1689`).

### 4.3 Mutabilidad, const y referencias

- Un root `const` bloquea tanto rebind como mutación proyectada: E0372 (`hir.rs:12316-12330`).
- `&mut` sobre const falla E0373; `&` sigue siendo read-only (`hir.rs:15343-15361`).
- `*ref T = ...` falla E0272; `ref mut T` aporta write capability, no exclusividad/noalias (`hir.rs:13780-13799`).
- Views read-only no permiten element write; se exige ViewMut (`hir.rs:13841-13874`).
- Locals de reference/view son bindings de inicialización única y no pueden rebindearse (E0277), aunque un pointee mutable sí puede escribirse (`hir.rs:12362-12379`).
- Fields de class requieren receiver declarado `mut`; storage interior de class no se presta libremente.

### 4.4 Copy, Move, Alias, Transfer y replacement owning

- Copy: assignment emite `Use`/store sin obligación owning.
- Root non-Copy: el RHS produce una obligación; MIR mueve el old a temporal, publica el nuevo, actualiza drop flag y destruye old. Esta secuencia sólo es válida para root.
- String proyectado: `ReplaceString` captura old, publica new y libera old.
- Owning struct field/pointee: HIR clasifica `ReplaceOwned` sólo si el tipo es concreto storable+relocatable+needs-drop, el Place es field-only o dereference admitido y no es class field. MIR/SSA preservan una operación indivisible; LLVM hace capture→publish→Drop (`hir.rs:12338-12360,12408-12415`; `mir.rs:1758-1777`; backend `lib.rs:2550-2585`).
- Un index owning sigue prohibido por E0297: no se admite ReplaceOwned sobre elementos owning. Los elementos Copy sí se asignan.
- Leer un Place non-Copy proyectado falla E0293; no se habilita partial move (`hir.rs:15475-15490`).
- Alias/Transfer no se infieren por el operador: dependen de cómo se produjo el RHS (owner fresco, move único, alias ARC ya adquirido). No se fabrica Clone, retain o deep copy.

El contrato CLOSED de owning replacement exige que un RHS throwing falle antes del commit; entonces old sigue intacto y los temporales RHS se limpian. Tras el commit, Drop del old no tiene exceptional successor. Los traps nativos, incluido bounds/overflow, son abortivos y no hacen unwind de frames Aether. Referencias: `OWNING_STRUCT_FIELD_REPLACEMENT_ARCH_1.md:25-109,122-218,254-348` y `AETHER_LANGUAGE_SPEC_V1.md:567-576`.

## 5. Evaluación única y orden de efectos

### Hecho actual

En simple assignment el frontend resuelve primero el Place para tipar/validar, luego el RHS. Sin embargo, esto no ejecuta las expresiones del Place. MIR baja el RHS antes de `lower_place`. El reproducer:

```aether
list[index()] = rhs();
```

imprimió:

```text
rhs
index
```

y el LLVM emitido mostró call a `rhs`, luego call a `index`, luego bounds helper y store. Cada call ocurrió una sola vez, pero el orden es RHS→LHS dinámico.

### Orden recomendado para compound assignment

Para `lista[obtenerIndice()] += 5` se recomienda fijar contractualmente:

1. evaluar base del destino y cada proyección de izquierda a derecha, capturando reference/receiver/índices una vez;
2. materializar la dirección y ejecutar checks de acceso/bounds; si fallan, no evaluar RHS;
3. leer el valor anterior exactamente una vez (sólo tipos Copy/numeric en V1);
4. evaluar el RHS de izquierda a derecha;
5. aplicar las mismas conversiones y el mismo operador checked/IEEE que una expresión ordinaria;
6. si operator/conversion trap, no escribir el destino;
7. escribir el resultado una vez.

Este orden hace que los efectos del destino precedan al RHS y evita que un RHS throwing o trapping cambie el slot. El old value es Copy en el primer milestone, por lo que no abre partial moves ni ReplaceOwned.

### Representación recomendada

No expandir AST a `p = p + rhs`: duplicaría calls/índices y podría cambiar borrow/ownership. Tampoco es necesario agregar una operación atómica LLVM para Copy. La opción mínima y verificable es:

- AST/HIR: statement explícito `CompoundAssign { place, op, value }` para conservar intención y diagnosticar;
- MIR: `lower_place` antes del RHS, con operandos capturados en temporales; `Load(stable_place)`, lowering del RHS, `Binary`, store al mismo `Place`;
- SSA: puede usar operaciones existentes, siempre que verifier compruebe que load/store comparten exactamente la identidad estabilizada y que los operandos de dirección aparecen una sola vez;
- opcionalmente mantener una op MIR/SSA `CompoundAssign` hasta después de verificación si probar identidad mediante secuencia resultara frágil. No hay evidencia que obligue a una op backend nueva.

Se debe agregar un contrato explícito de invalidación: durante RHS no puede permitirse una mutación estructural que relocalice el backing del Place estabilizado. La infraestructura de borrows/effects ya distingue element mutation de structural potentially-relocating mutation (`hir.rs:1429-1538`) y debe reutilizarse, no relajarse.

## 6. Postfix `++` y `--`

Decisión de diseño recibida: son statements sin valor. El parser debe admitir únicamente `place++;` / `place--;` en posición statement y rechazar prefix y cualquier uso en initializer, argumento, return o interpolación.

Semánticamente son `CompoundAssign(place, Add/Subtract, literal contextual 1)`, no una expansión textual. Deben reutilizar:

- Place estabilizado y evaluación única;
- write capability/const/view/ref checks;
- tipado del operador, incluidos enteros checked y floats IEEE sólo si el contrato decide admitir floats;
- restricción inicial a escalares que ya admiten `+ 1`/`- 1` y cuyo resultado es asignable al tipo exacto del Place.

Aplica de forma uniforme a locals, fields Copy, class scalar fields mutables, índices Copy, nested projections y `*ref mut`. No debe admitir owners, operaciones vector/matrix que creen owners, generic capabilities sin una decisión explícita ni tipos donde `1` no sea contextualizable. Overflow debe coincidir con `+= 1`/`-= 1`.

## 7. Bitwise

### Conflictos de sintaxis

- `&` ya se tokeniza como `Ampersand` y en posición prefija significa borrow; en posición infija puede distinguirse por la gramática sin conflicto léxico.
- `&&` debe conservar maximal munch antes que `&`.
- `|` sólo reconoce hoy `||`; single `|` da E0001. Si se usa también en tipos, el parser debe decidir por contexto, con un único token.
- `^` y `~` dan E0001 y requieren tokens nuevos.
- `<<`/`>>` actualmente son dos tokens `<`/`>`; maximal munch debe agregar shift antes de comparadores y respetar `<=`/`>=`.
- `^` histórico como potencia en documentación queda invalidado por la decisión actual: será XOR; potencia es `**`.

### Reglas recomendadas, derivadas del sistema numérico actual

1. Sólo enteros built-in; nunca bool, char, float, refs, owners o operaciones LLVM internas.
2. `& | ^`: usar el mismo mecanismo `common()` vigente. Se admite mismo tipo o widening value-preserving dentro de la misma familia signed o unsigned. No signed↔unsigned, no isize/usize↔fixed, no C promotions. Resultado: common type.
3. `~a`: conserva exactamente el tipo/ancho de `a`; inversión de todos los bits de su representación two's-complement para signed. No overflow.
4. `a << n`, `a >> n`: resultado tiene el tipo exacto del LHS. RHS debe ser entero; conviene exigir `usize` o un literal contextualizable a `usize`, evitando signed negativo por construcción. Si se admite cualquier entero, negative debe trap/diagnostic antes de conversión.
5. Shift count `>= bit_width` debe ser diagnóstico si constante y trap dedicado si dinámico; nunca masking, wrapping ni UB de LLVM.
6. `>>` signed es aritmético; unsigned es lógico. `<<` opera sobre bits, descarta bits salientes y no usa el overflow aritmético de `+/*`; si se desea checked numeric shift debe decidirse en contrato, no heredarse accidentalmente de LLVM.
7. Const folding debe usar ancho/signedness canónicos y replicar exactamente los traps dinámicos.

Precedencia propuesta convencional, pendiente de decisión CLOSED: `~` junto a unary; shifts entre additive y ordered comparison; `&`, luego `^`, luego `|`, todos izquierda y entre equality y `&&`. Esto preserva separación de `&&/||/!`, pero debe calificarse con tests de legibilidad y con la gramática de tipos para `|`.

## 8. Potenciación `**`

### Conflictos y parsing

El lexer debe reconocer `**` antes de `*`. El parser necesita un nivel `power` right-associative entre postfix y unary de signo. Para cumplir `-2 ** 2 == -(2 ** 2)`, unary `-` debe consumir una potencia, mientras el exponente debe poder consumir unary para permitir, si se decide, `2 ** -2`. Una forma típica es `unary := ('-'|'!'|'~'|...) unary | power` y `power := postfix ('**' unary)?`.

### Semántica recomendada y decisiones pendientes

`**` y `pow(a,b)` deben desugarizar a una misma operación semántica HIR/builtin, nunca duplicar tablas. La documentación histórica propone una tabla `int/int -> int` con exponente no negativo y floats por libm, pero esa tabla usaba `^` y pertenece a una superficie que `compiler-next` no implementa. Debe revalidarse contra los tipos actuales.

Baseline recomendado:

- base integer + exponent integer natural: resultado del tipo de la base; exponent debe ser non-negative y representable como count; exponentiation by squaring con multiply checked; `0 ** 0 = 1` por consistencia histórica, pero requiere decisión explícita;
- base float + exponent float: mismo float common type y semántica libm/IEEE `pow` sin fast-math;
- float base + integer exponent: decidir entre algoritmo `powi` que preserve exponent exacto o conversión explícita a float. No debe introducirse un widening entero→float implícito contrario al contrato actual;
- integer base + negative/fraccional exponent: no puede retornar integer. Rechazar salvo que el usuario convierta explícitamente la base a float es la opción coherente con las conversiones vigentes;
- base negativa con exponent float, NaN/infinities, signed zero y fractional exponent: delegar a una función libm seleccionada por formato, documentando IEEE/platform behavior;
- constant exponent: fold sólo con el mismo algoritmo/checks; optimizar multiplication chain/exponentiation by squaring sin debilitar overflow ni IEEE;
- genéricos, vectors y matrices quedan fuera de V1: no existe capability `Pow` ni una identidad `One` general admitida para esta operación.

Decisiones que deben cerrarse antes de implementar: `0**0`; tipos permitidos para exponent integer; resultado de combinaciones mixed; negative exponent; float32 entrypoint/rounding; domain behavior y reproducibilidad libm; si `pow` es builtin reservado/importado; precedence exacta respecto de borrow/deref; trap category para exponent inválido.

## 9. Composabilidad y límites legítimos

### Infraestructura reusable

- Place recursivo y tipado con identidad de FieldId, axis/base y element type.
- Operandos MIR/SSA para capturar índices/receivers/references una vez.
- `Load` y store existentes para valores Copy.
- Opcodes checked enteros, IEEE floats y CFG short-circuit.
- Verifiers independientes HIR/MIR/SSA.
- Mutability/const/ref/view y borrow provenance.
- Mutation effects para impedir relocalización mientras vive un Place interior.
- ReplaceString/ReplaceOwned para assignment simple owning; no deben involucrarse en compound numeric V1.

### Restricciones necesarias

- no partial read/move de owners;
- no replacement owning por Index;
- no mutación a través de shared ref/read-only view/const path;
- no implicit mixed signedness, int↔float o narrowing;
- no operator protocol público implícito;
- no extender storage, ownership, aliasing o lifetimes para hacer encajar un operador.

### Ergonomía actualmente artificial o incoherente

- la ausencia total de compound assignment obliga a repetir Places simples y hace imposible expresar de forma segura Places con efectos;
- el orden actual RHS→Place de simple assignment es poco convencional y no sirve como baseline accidental para compound assignment;
- `pow` está documentado históricamente pero ausente en `compiler-next`;
- el documento `AETHER_LANGUAGE_SPEC_V1.md:266-270,287-328` afirma `+=` y potencia `^`, en conflicto directo con autoridad/implementación actuales;
- generic arithmetic ya tiene capabilities Add/Sub/Mul/Div, pero compound assignment no debe admitirse automáticamente hasta definir resultado exacto, writeback y ownership de T.

## 10. Roadmap incremental

### COMPOUND-ASSIGNMENT-V1

Alcance: `+= -= *= /= %=` statements sobre Places Copy escalares; opcionalmente String `+=` sólo en milestone separado, porque implica owner replacement. Agregar tokens maximal-munch, AST/HIR específico, estabilización MIR, verificación de identidad Place, tests de order/once/trap/const/ref/view/bounds.

Criterios de aceptación:

- cada base/receiver/index se evalúa una vez y antes del RHS;
- old load ocurre antes del RHS; write sólo tras éxito;
- mismas tablas/conversiones/traps que el operador binario;
- exact destination type tras writeback; no narrowing implícito;
- RHS throw/trap deja el slot sin escribir; structural relocation incompatible se rechaza;
- HIR/MIR/SSA corruption tests fallan cerrados;
- todos los shapes Copy soportados por `=` funcionan o tienen rechazo explícito documentado.

### POSTFIX-UPDATE-V1

Depende de CompoundAssign estable. Parser sólo statement postfix; reutiliza `+= 1`/`-= 1`. Negativos obligatorios para prefix y value contexts. Qualification en local, field, index, dereference, nested Place, const/shared ref, overflow y evaluación única.

### BITWISE-OPERATORS-V1

Puede desarrollarse después de estabilizar lexer/precedence, independiente del writeback. Primero operadores de expresión y const folding; luego compound `&= |= ^=` y shifts sólo en una extensión posterior. Cerrar width/count/right-shift/left-shift semantics antes del backend.

### EXPONENTIATION-V1

Agregar `**` y builtin `pow` sobre una única semántica. Primero integers naturales checked y float homogéneo; mixed/negative sólo tras decisión. Verificar right associativity y `-2 ** 2`. Backend integer helper/op explícita y libm float con ABI probado.

### Extensiones de compound assignment

Después de cada operador de expresión: `&= |= ^=` y posiblemente `<<= >>= **=` requieren decisión separada. No asumir que todos son deseables. String, mathematical owners y generic T requieren contratos propios de allocation/ownership/result identity y quedan fuera del V1 scalar.

## 11. Evidencia de qualification

### Reproductores temporales con CLI oficial

| Caso | Resultado |
|---|---|
| aritmética/comparison/logical + local/field/List/Matrix/ref-mut assignment | `check` PASS; `run` exit 20 |
| `list[index()] = rhs()` | `check` PASS; salida `rhs` luego `index`; exit 9 |
| const assignment | E0372 semantic |
| write por shared ref | E0272 semantic |
| dynamic int64 overflow | `check` PASS; runtime SIGILL por `llvm.trap`; CLI exit 1 |
| `x += 2` | E0103 parse |
| `x++` | E0103 parse |
| `x & 1` | E0100 parse (token `&` existe sólo en prefix borrow grammar) |
| `x << 1` | E0103 parse |
| `x ** 2` | E0271 semantic por tokenización como `*` + dereference |
| `pow(3,2)` | E0212 semantic, unknown function |
| `|`, `^`, `~` | E0001 lex |

`build --emit hir --emit mir --emit ssa --emit llvm` confirmó el orden y que el index dinámico se representa una sola vez como operand del Place. Los reproductores se crearon fuera de examples personales y se eliminaron al terminar.

### Pruebas focales

Se ejecutaron únicamente suites del driver directamente relacionadas con core, const, indexing, slice assignment y owning replacement. No se repitió el workspace completo porque no hubo cambios productivos. Los resultados finales se registran en la sección de cierre de qualification debajo.

| Comando | Resultado |
|---|---|
| `cargo test -p aether-driver --test core_v1` | PASS: 7/7 |
| `cargo test -p aether-driver --test const_v1` | PASS: 8/8 |
| `cargo test -p aether-driver --test integer_indexing_v1` | PASS: 6/6 |
| `cargo test -p aether-driver --test slice_assignment_v1` | PASS: 5/5 |
| `cargo test -p aether-driver --test owning_struct_field_replacement_v1` | PASS: 16/16 |

## 12. Referencias primarias

- Autoridad: `docs/architecture/COMPILER_AUTHORITY.md:1-32`.
- Tipos/conversiones/overflow: `docs/architecture/AETHER_V1_SEMANTIC_CONTRACT.md:32-240`; `types.rs:195-315`; `hir.rs:19561-19609`.
- Lexer: `compiler-next/crates/aether-frontend/src/lexer.rs:5-130,343-415`.
- AST/operators: `compiler-next/crates/aether-frontend/src/ast.rs:355-415,474-483,497-662`.
- Parser/order: `compiler-next/crates/aether-frontend/src/parser.rs:991-1001,1261-1471,1590-1629`.
- HIR statements/Places: `compiler-next/crates/aether-frontend/src/hir.rs:1275-1318,1582-1709,12298-12416,13681-13912,2403-2426`.
- Semántica binaria: `compiler-next/crates/aether-frontend/src/hir.rs:18684-19215,19694-19787`.
- MIR Places/lowering: `compiler-next/crates/aether-middle/src/mir.rs:183-218,314-361,473-505,1657-1777,5653-5703`.
- SSA Places/ops: `compiler-next/crates/aether-middle/src/ssa.rs:116-151,176-320,562-581`.
- LLVM: `compiler-next/crates/aether-backend-llvm/src/lib.rs:2516-2585,4070-4263`.
- Replacement owning: `docs/architecture/OWNING_STRUCT_FIELD_REPLACEMENT_ARCH_1.md:25-109,122-218,254-348`.

## 13. Cierre

La auditoría queda **AUDIT COMPLETE** porque las conclusiones están respaldadas por código de `compiler-next`, contratos vigentes, IR emitido y reproductores ejecutados con la CLI oficial. No se inicia ningún milestone. Las reglas propuestas permanecen propuestas hasta un contrato arquitectónico CLOSED y qualification end-to-end.
