# BORROW-ERGONOMICS-V1 — exact shared call borrows

Estado: **IMPLEMENTADO** en `compiler-next`, perfil nativo Linux x86-64,
2026-09-15.

Documentos normativos:
[BORROW_ERGONOMICS_ARCH_1.md](BORROW_ERGONOMICS_ARCH_1.md) y
[BORROW_ERGONOMICS_ARCH_1_REPORT.md](BORROW_ERGONOMICS_ARCH_1_REPORT.md).

## Superficie implementada

El frontend admite una única adaptación nueva, exclusivamente en posiciones de
argumento: después de resolver una firma concreta que espera `ref T` shared, un
argumento cuyo TypeId es exactamente T puede prestarse durante esa call. Esto
cubre calls directas, funciones de toolchain como `std.File.readText` y toda la
familia `std.Text` mediante el mismo adaptador tipado.

```aether
string path = "input.txt";

std.File.readText(path);
std.File.readText("input.txt");
std.Text.contains(text, "Aether");
```

No es una conversión general `T -> ref T`. La adaptación no se aplica a
assignments, returns, fields ni captures; no encadena conversiones, no hace
auto-deref y nunca sintetiza `ref mut`. Tampoco crea Alias, Clone, Move, owner o
ARC adicional. La forma explícita `f(&value)` conserva el mismo protocolo de
call y queda marcada como origen explícito.

## Resolución, tipos y generics

La firma y su instancia genérica se determinan primero. Sólo entonces
`adapt_call_argument` compara el parámetro concreto `ref T` con el TypeId exacto
T del argumento. Una conversión ordinaria seguida de borrow se rechaza.

La inferencia general no observa la adaptación: comparar `ref U` con U owning
no infiere U. `f<int>(value)` sí es legal, y también una call donde otro
parámetro infiere U antes de adaptar el argumento `ref U`. No cambian
InstanceId, mangling, constraints ni selección de candidatos.

## HIR y ownership

Cada call obtiene un `CallSiteId`. `CallScopedSharedBorrow` conserva:

- CallSiteId e índice exacto del argumento;
- pointee TypeId T y reference TypeId `ref T`;
- origen implícito o explícito;
- source `Place` o `Temporary` y su provenance.

Un lvalue presta su Place existente y queda address-taken. Un rvalue se evalúa
una vez en un root temporal oculto, que conserva la única obligación owning. El
análisis mantiene activo cada borrow desde que se evalúa su argumento hasta que
termina la call; por ello un argumento posterior no puede mover, reemplazar,
destruir ni invalidar el mismo root. Roots demostrablemente disjuntos siguen
siendo legales. La evaluación permanece estrictamente izquierda a derecha.

El verificador HIR exige que cada borrow aparezca directamente en el slot de
argumento indicado de su CallSite, reconstruye los TypeIds y el Place, y rechaza
cualquier uso o escape fuera de esa posición. `std.Text` ya no borra el `ref
string` canónico mediante una excepción string-specific: sus operands HIR son
references reales y pasan por el adaptador común.

## MIR, SSA y cleanup

MIR materializa `Borrow` con metadata de call, la call o Text op con el mismo
CallSiteId y un `EndBorrow` explícito. Para temporales owning, el Drop ocurre
después de `EndBorrow`; los argumentos múltiples cierran borrows y destruyen
roots en orden inverso.

Si la evaluación de un argumento posterior o el callee hace unwind, el landing
pad termina todos los borrows ya activos, destruye exactamente los roots
inicializados y propaga el mismo evento hacia catch/finally. Un initializer que
no completó no publica root ni Drop. Los traps siguen siendo abortivos y no
adquieren cleanup garantizado.

SSA preserva CallSiteId, argument index, tipos, source/provenance y
`Borrow`/`EndBorrow`. Sus verificadores, independientes de HIR y MIR, recorren
el CFG normal y excepcional, exigen estados idénticos en joins y rechazan:

- CallSite o índice que no correspondan al uso exacto;
- pointee/reference TypeIds incompatibles;
- Drop de un temporary antes de `EndBorrow`;
- regiones vivas en return o unwind no abortivo;
- usos por phi, Store, Return, terminator u otra operación que permitan escape.

LLVM conserva el pointer ABI existente. `std.Text` carga el handle string desde
el `ref string` antes de invocar sus helpers privados. `EndBorrow` se mantiene
como marcador inerte en LLVM; no genera retain/release, `noalias` ni extensión
de lifetime.

## Costos y strings inmortales

La instrumentación de lifecycle compara adaptación implícita y `&` explícito
en O0/O2. Para un temporary concatenado, ambas formas observan exactamente su
construcción y destrucción preexistentes y cero retain extra. Para un literal
prestado se observan cero alloc/free/retain/release físicos; el único evento es
el no-op lógico de cleanup del literal inmortal. Ninguna ruta emite
`StringOp::Alias` por esta adaptación.

## Qualification

La suite `crates/aether-driver/tests/borrow_ergonomics_v1.rs` y el test HIR local
cubren:

- lvalue string, literal string y temporary string;
- T Copy no-string y equivalencia con `&value`;
- calls directas, `std.File` y `std.Text`, incluidos múltiples argumentos;
- evaluación izquierda a derecha, préstamo anterior activo durante argumentos
  posteriores, invalidación del mismo root y roots disjuntos;
- generic explícito, inferido por otro argumento y rechazo de inferencia basada
  sólo en `ref U` contra U;
- rechazo de `ref mut`, conversion+borrow, auto-deref y contextos de escape;
- success, unwind durante argumento posterior, unwind del callee y finally;
- corrupciones independientes de CallSite, índice, región y escape en
  HIR/MIR/SSA;
- cleanup normal/excepcional, cero Alias/retain/release adicionales y ejecución
  equivalente en O0/O2.

La qualification de cierre ejecutó sin fallos `cargo test --workspace`, `cargo
fmt --all --check`, `cargo clippy --workspace --all-targets -- -D warnings`,
`git diff --check` y `bash compiler-next/tests/run-differential.sh`. El
diferencial comparó 21 casos legacy y reportó cero fallos.

## Scope conservado

Permanecen fuera borrows implícitos en assignments/returns/fields/captures,
stored o escaping borrows, conversion+borrow, auto-deref, `ref mut` automático,
receivers, overloads generales, closures, smart pointers y cualquier Alias,
Clone, Move o ARC nuevo. No cambia el runtime público, la representación de
string ni el compilador legacy.
