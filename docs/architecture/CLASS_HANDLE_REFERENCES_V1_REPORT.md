# CLASS-HANDLE-REFERENCES-V1 — reporte de implementación

Estado: **IMPLEMENTADO Y CALIFICADO**, 2026-10-20.

Autoridad normativa:

- [CLASS-HANDLE-REFERENCES-ARCH-1](CLASS_HANDLE_REFERENCES_ARCH_1.md)
- [CLASS-HANDLE-REFERENCES-ARCH-1 — reporte](CLASS_HANDLE_REFERENCES_ARCH_1_REPORT.md)
- [AETHER V1 semantic contract](AETHER_V1_SEMANTIC_CONTRACT.md)
- NEXT-VERTICAL-9, BORROW-ERGONOMICS-V1, OOP-V1/V2/V3, NULLABLE-V1,
  EXCEPTION-V1..V4 y CLASS-BUFFER-FIELDS-V1.

## Resultado

Las referencias shared a handles de class concretas están admitidas como
`ref C` y `ref C?`, incluidos aliases transparentes. Formar, forwardear,
observar y terminar esos borrows no crea ownership ni tráfico ARC.

La frontera permanece cerrada para `ref mut C`, interfaces, aggregates que
contienen classes, interior references a fields/elements, extracción owning y
escape de references. Tampoco se admite el ajuste combinado owning
`Derived -> ref Base`; el único upcast nuevo es `ref Derived -> ref Base`.

## Implementación

### Admisión y semántica HIR

`TypeArena::class_handle_reference_pointee` implementa el predicado positivo
cerrado para un handle directo `C` o un nullable directo `C?`. El gate E0406
continúa rechazando el resto de los tipos que sólo contienen una class de
manera transitiva y emite diagnósticos específicos para `ref mut` e
interfaces.

HIR conserva el `Borrow`/`CallScopedSharedBorrow` existente con su Place,
provenance, `CallSiteId`, índice y origen. La clasificación exacta del pointee
distingue el handle directo del storage interior. Se agregaron las operaciones
semánticas verificadas:

- `BorrowedHandleView`, para observar `*r` sin producir un owner;
- `BorrowedReceiver`, siempre read y sin `ReceiverKeepalive`; y
- `BorrowedClassUpcast`, que reconstruye y verifica el path nominal exacto.

Las operaciones OOP existentes siguen resolviendo visibility, field identity,
targets directos, `VirtualSlotId` y dispatch dinámico. Una vista borrowed sólo
puede alimentar métodos read, fields públicos Copy e identity equality.

### MIR y SSA

Los borrows call-scoped conservan `BeginBorrow`/`EndBorrow` en los successors
normal y excepcional. Los receivers borrowed no generan Drop. Para temporales,
el orden sigue siendo `Transfer -> Borrow -> call -> EndBorrow -> Drop`.

Los verificadores mantienen separado el ledger del borrow del ledger owning.
Además de las verificaciones generales de no-escape y cierre completo, MIR y
SSA conservan el Place anchor de cada class borrow y rechazan de forma
independiente `Move`, `Transfer`, `Drop`, store o replacement del anchor antes
de `EndBorrow`. Una corrupción dedicada mueve el cleanup válido antes del
cierre de región y ambos verificadores la rechazan por esta regla, no por un
Drop faltante o duplicado.

### LLVM y ABI

`ref C` baja al mismo object pointer one-word del handle. Si el Place todavía
reside en memoria se carga ese pointer una vez al comenzar el borrow; no se
pasa `C**`. `ref C?` conserva el ABI general pointer-to-slot non-null y el
pointee nullable puede contener null.

`BorrowedHandleView`, `BorrowedReceiver` y `BorrowedClassUpcast` son
passthroughs de pointer sin runtime de borrow, wrapper, boxing, fat pointer,
vtable adicional ni reflection. No se agrega `noalias`, retain, release o Drop
al borrow ni al receiver read.

## Qualification

Se agregó
`compiler-next/crates/aether-driver/tests/class_handle_references_v1.rs`, con
ejecución nativa O0/O2. Sus nueve tests cubren:

- borrow explícito, adaptación implícita, aliases transparentes, forwarding,
  dos shared borrows y owners alias distintos;
- método directo y virtual, field Copy, identity, inheritance y borrowed
  upcast;
- `ref C?` null/present, temporary owner y owner utilizable tras la región;
- throw/catch y forwarding throwing anidado;
- rechazos de mut receiver, field/element interior, owning extraction,
  by-value desde `*r`, escape, interfaces, `ref mut`, nullable misuse, base no
  relacionada y conversión+borrow owning;
- corrupción independiente de `ClassId` en MIR/SSA y cleanup del anchor antes
  de `EndBorrow`; y
- ausencia de runtime de borrow, `noalias` y wrappers en LLVM.

Los contadores nativos para borrow, método read, forwarding, upcast y temporary
son exactamente `[alloc=1, retain=0, release=1, destroy=1]`: el único release es
el Drop final del owner. En unwind, la fixture borrowed y una baseline sin
borrow producen ambas `[2, 1, 3, 2]`; el retain/release adicional pertenece al
protocolo del objeto excepción y el delta atribuible al borrow es exactamente
`retain=0, release=0` en O0 y O2.

La matriz dirigida también volvió a ejecutar OOP-V1/V2/V3/OPT, lifecycle y
dispatch dinámico, BORROW-ERGONOMICS-V1, generic ref inference, NULLABLE-V1,
EXCEPTION-V1..V4, CLASS-BUFFER-FIELDS-V1 y GRAPHICS-FOUNDATION-V1. Graphics no
recibió modificaciones productivas ni privilegios compiler-side.

## Validación

Ejecutado satisfactoriamente:

```text
cargo test --workspace
cargo fmt --all -- --check
cargo clippy --workspace --all-targets -- -D warnings
bash compiler-next/tests/run-differential.sh
git diff --check
```

La vertical nueva terminó 9/9, `vertical` 220/220, frontend 74/74, middle
29/29 y el differential 21/21 con cero fallos.

**Estado final: CLOSED.**
