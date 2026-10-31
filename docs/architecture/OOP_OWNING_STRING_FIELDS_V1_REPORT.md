# OOP-OWNING-STRING-FIELDS-V1 — implementación y qualification

Estado: **CLOSED**, 2026-10-31.

Documento normativo:
[OOP-OWNING-STRING-FIELDS-ARCH-1](OOP_OWNING_STRING_FIELDS_ARCH_1.md).

## Resultado

El compilador admite ahora fields cuyo TypeId canónico es exactamente
`string`, sin regla por nombre, package, Graphics o Plots. Los demás owners no
incluidos en el perfil V1 continúan fail-closed. `string` permanece no-Copy y
separado de los handles de class.

La operación `ClassOp::StringFieldAlias` conserva en HIR, MIR y SSA la lectura
owning del field. Produce un owner string independiente; no puede degradarse a
`FieldRead` ni a `Load`. `FieldWrite` consume una obligación adquirida y el
backend conserva para replacement el orden load-old, store-new,
`aether_drop_str(old)`. La receta `ClassDropStep` y
`ConstructorUnwindPlan` existentes incluyen los fields string por
`needs_drop`, en orden inverso y derived-before-base.

No se agregó runtime, representación, boxing, sentinel null, bitmap ni camino
especial de Plots. El slot usa inline el handle string canónico. También se
corrigió la instrumentación de destrucción de classes para que el contador de
fields Buffer no cuente fields string: los eventos string siguen en los
contadores `aether_string_*` y el ARC del objeto en `aether_object_*`.

## Precisión contractual aplicada

La enmienda §10.4 distingue obligaciones lógicas de llamadas ARC físicas,
delimita las expresiones value que pueden originar un borrow estabilizado y
describe la reconstrucción independiente en HIR/MIR/SSA. En particular,
`&object.field` sigue rechazado; una adaptación de call crea primero un owner
`StringFieldAlias`, hace el borrow ordinario y ejecuta EndBorrow/Drop tanto en
retorno normal como excepcional.

El ledger SSA general fue extendido para contabilizar otra vez, desde SSA, los
owners string consumidos por `FieldWrite`, init y calls de clase. No depende
del ledger de class handles ni del análisis MIR.

## Qualification implementada

La suite dedicada
`oop_owning_string_fields_v1.rs` cubre en O0/O2:

- literal, heap result, lvalue, UTF-8 y U+0000;
- fields públicos y privados, Copy intercalado, class open/base/derived;
- lectura value, retorno, parámetro, alias de class y borrow de call;
- replacement desde lvalue y self-replacement del mismo backing;
- fallo del RHS, excepción posterior al commit, construcción parcial antes y
  después de instalar varios fields, y preservación del valor antiguo;
- destrucción final concreta, inherited y por interface, más
  store-before-release inspeccionado en LLVM;
- negativos de aggregate con string, `Buffer<string>`, init incompleta, read
  antes de init y referencia interior explícita;
- corrupción de `StringFieldAlias` a `FieldRead` rechazada por HIR, MIR y SSA.

Las suites existentes de exceptions, class construction, inheritance,
interfaces y class Buffer fields ejercen además cleanup parcial, recipes de
drop, dispatch y final release compartidos por el nuevo TypeId admitido.

El reproducer original `reproducers/plots_preflight`, antes negativo por
`E0401`, pasa `check` y `run` en O0/O2 sin modificar Plots productivo. El
archivo personal `examples/pNR/probandoNR2.ae` no es ese reproducer y conserva
un error de sintaxis previo por funciones locales; no fue modificado.

## Gates

Resultados del cierre:

- suite dedicada O0/O2 y corrupciones: PASS;
- GENERAL string V1/V2: PASS;
- OOP V1/V2, class Buffer fields y class handle references: PASS;
- reproducer `plots_preflight` check/run O0/O2: PASS;
- `cargo fmt --all --check`: PASS;
- `CARGO_INCREMENTAL=0 TMPDIR=/home/blasm/tmp cargo test --workspace -j 1`:
  PASS completo, incluidos 220/220 tests verticales y doc-tests;
- `cargo clippy --workspace --all-targets`: PASS con warnings preexistentes de
  `assert_is_empty`, `needless_borrows_for_generic_args`, `match_same_arms` y
  `too_many_lines`; la variante `-D warnings` falla por esos warnings ajenos al
  milestone. El único warning inicialmente introducido en el test HIR nuevo se
  corrigió antes del cierre;
- `git diff --check`: PASS.

No se implementó `PLOTS-2D-LINE-V1`, ni se modificaron Graphics Foundation,
SVG Backend, Plots productivo, Plots legacy o ejemplos personales.

**Estado final: OOP-OWNING-STRING-FIELDS-V1 CLOSED.**
