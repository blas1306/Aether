# CLASS-HANDLE-REFERENCES-ARCH-1 — reporte de cierre

Estado: **CLOSED COMO ARQUITECTURA; SIN IMPLEMENTACIÓN**, 2026-10-20.

Documento normativo:
[CLASS-HANDLE-REFERENCES-ARCH-1](CLASS_HANDLE_REFERENCES_ARCH_1.md).

## Resultado

Se cerró `ref C` para class handles como shared borrow non-owning del valor
handle. El caller conserva su único owner; el borrow mantiene un `BorrowAnchor`
semántico sobre ese owner, impide mover/reemplazar/dropear el source durante la
región y no crea `Alias`, strong token, retain/release ni Drop propio. Para
`ref C?`, el anchor es el slot nullable inicializado más su owner condicional
sólo cuando está present; null no inventa una obligación de objeto.

La decisión es general y no contiene allowlists de `graphics`, `Scene` ni SVG.
No se modificó compiler, runtime, std, graphics ni qualification ejecutable.

## Distinción cerrada

`ref C` presta el handle que alcanza una identidad de objeto. No presta storage
interior del payload. Continúan rechazados:

```aether
&object.bufferField
&object.bufferField[i]
ref mut object.someOwner
```

Mantener vivo el objeto no mantendría vivo un backing reemplazado a través de
otro `Alias`; por eso no se agregó pinning ni backing refcount.

## Semántica y ARC

La representación semántica conserva el Place, `BorrowId`, región y owner
anchor. Para `ref C`, LLVM pasa el mismo object pointer de C como argumento
borrowed, no un `C**`, wrapper, fat pointer ni runtime borrow object. `ref C?`
conserva el pointer non-null al slot nullable: usar directamente su object
pointer posiblemente null confundiría pointee ausente con reference nullable
ausente. Ese slot es storage ordinario existente/temporal, no una allocation.

El costo normativo de `f(ref c)` es cero ARC adicional en O0 y O2. Una llamada
a método read mediante `(*r)` usa un `BorrowedReceiver` respaldado por el anchor
y los `DirectMethodCall`/`VirtualCall` existentes. No usa el
`ReceiverKeepalive` owning conservador, por lo que tampoco agrega el par
retain/release actual de una call ordinaria.

El callee puede llamar methods read, leer public Copy fields, forwardear el
reference y comparar identidad. No puede llamar métodos `mut`, convertir
`*r` en owner, moverlo, extraer fields owning, almacenarlo ni retornarlo. La
class no se vuelve profundamente immutable: otros aliases strong conservan sus
capacidades ordinarias.

## Nullability, inheritance e interfaces

- `ref C` presta un handle non-null.
- `ref C?` presta storage nullable sin probar presencia ni agregar auto-unwrap;
  null no tiene owner y present usa el owner condicional como anchor.
- `(ref C)?` conserva únicamente la composición general de NULLABLE-V1.
- `ref mut C` y todas sus variantes nullable quedan fuera.
- `ref Derived` puede llamar métodos base y convertirse a `ref Base` sólo por
  un path owning ya válido, mediante un upcast borrowed sin ARC. No se agrega
  variance general ni conversion+borrow desde un owning Derived.
- `ref Interface` queda fuera porque el carrier vigente es object+witness y
  necesita una qualification de layout/lifetime separada.

## IR y unwind

HIR/MIR/SSA conservarán BeginBorrow/Borrow, owner anchor, BorrowedHandleView,
BorrowedReceiver y EndBorrow. El ledger owning no gana ni pierde obligaciones;
el ledger de borrow inmoviliza el token source. SSA deberá rechazar owner
ausente/movido, pointer-anchor incoherente, ARC inventado, escape, mut access,
upcast corrupto y EndBorrow incompleto.

En unwind, el callee limpia sólo sus locals owning. El caller termina el borrow
en el exceptional edge, después destruye un temporary root si existía y
propaga el mismo `ExceptionEvent`. Un owner lvalue del caller no se dropea y
puede seguir usándose dentro/después del catch.

## Qualification futura

El vertical autorizado es **CLASS-HANDLE-REFERENCES-V1** y debe crear
`compiler-next/crates/aether-driver/tests/class_handle_references_v1.rs`.
Cubrirá O0/O2, explícito/implícito, method read, nested/two borrows, aliases,
inheritance, nullable, temporary, throw/catch y uso posterior del owner.

Los counters deben demostrar exactamente 0 retain/0 release atribuibles al
borrow y al receiver read. Negativos y corrupciones cubrirán move/replacement,
mut capability, escape/store/return, owner extraction, interior fields/elements,
interfaces, ref mut, owner anchor/metadata adulterados y cleanup normal/unwind.

Regresiones obligatorias: OOP V1/V2/V3/OPT/POLISH, class ARC/lifecycle, refs V9,
borrow ergonomics, nullable, exceptions/finally, class Buffer fields, graphics
foundation y workspace completo.

## Cambios realizados

Sólo se agregaron este reporte y el documento normativo. No se implementó
ningún cambio de lenguaje o runtime.

**CLOSED — siguiente milestone: CLASS-HANDLE-REFERENCES-V1.**
