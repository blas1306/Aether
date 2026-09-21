# NULLABLE-V1 — implementation report

Estado: **IMPLEMENTADO Y CALIFICADO**, 2026-09-21.

Autoridad normativa:
[NULLABLE_ARCH_1.md](NULLABLE_ARCH_1.md) y
[NULLABLE_ARCH_1_REPORT.md](NULLABLE_ARCH_1_REPORT.md).

## Resultado

El compilador de `compiler-next` implementa el primer vertical cerrado de
nullable values. `T` continúa siendo non-null y `T?` es un `TypeId` canónico
distinto mediante `TypeData::Nullable(TypeId)`. El arena rechaza `void?` y
nullable nested, y propaga el constructor por substitution, generics,
propiedades, capabilities, signatures y composición nominal/collection.

El lexer y parser admiten `null`, `T?`, grouping de tipos, `&&`, `||` y `!`.
La precedencia conserva las identidades arquitectónicas:

- `ref T?` y `ref mut T?` referencian storage nullable;
- `(ref T)?` y `(ref mut T)?` son referencias nullable.

No se agregó safe navigation, coalescing, force unwrap, `take`, patterns ni
nullable nested.

## Tipado y refinamiento

`null` permanece contextual y no tiene un `TypeData` propio. Se materializa
como `NullableNull` sólo con expected `T?`; se rechazan `null` hacia `T`,
`var x = null` e inferencia genérica sustentada únicamente por null. La única
coerción nullable implícita es `T -> T?`, preservada como `NullableInject`.

Los tests contra null funcionan en ambos órdenes. `null == null` y
`null != null` son constantes cerradas. Igualdad general y ordering nullable
fallan cerrado.

El checker mantiene `Unknown | Null | NonNull` separado del tipo declarado para
locals y parámetros estables. Implementa then/else, joins por intersección,
recalculo tras assignment e invalidación por mutable borrow y calls que pueden
escribir mediante aliases. Los loops preinvalidan roots escritos o posiblemente
mutados y aplican el fact de la condición en el body, evitando proofs optimistas
en iteraciones posteriores o a la salida.

`&&`, `||` y `!` permanecen explícitos en HIR. MIR los convierte en CFG real;
el RHS recibe respectivamente los facts true/false requeridos y nunca se evalúa
eager.

Los payloads Copy se leen con `NullablePayload { access: Copy }`. Payloads
owning sólo se exponen como borrow call-scoped/observación; moverlos, retornarlos
o consumirlos como `T` se rechaza. Mover el container `T?` completo sigue el
protocolo ordinario.

## Lifecycle, layout y ABI

`NullableLayout` es la clasificación central. `string`, class handles,
`Function` y references usan niche null-pointer. Números, structs, enums,
interfaces, collections y el resto usan `{ tag, padding, payload }` con offsets
derivados del layout engine. El backend consulta esta clasificación y no vuelve
a decidir por spelling.

Para owning `T?`, inject transfiere el owner, move transfiere el container y
drop prueba presencia antes de ejecutar `Drop(T)`. Esto está integrado con
replacement, cleanup normal y unwind. Nullable class owners se transfieren al
container sin duplicar tokens en los ledgers MIR/SSA.

El mangling usa exactamente `N<decimal-byte-length>x<payload-mangle>`; por
ejemplo, `int?` produce `N6xiInt64` y `string?` produce `N3xstr`. Niche conserva
la forma ABI física del payload; tagged usa el aggregate físico calculado.

## IR y fail-closed

HIR, MIR y SSA conservan operaciones semánticas separadas para null, inject,
presence test y payload access hasta lowering LLVM. Los verificadores comprueban
tipos nullable/payload, modo Copy/Borrow, operands de `IsNull`, phis y ownership.
Las proof identities son únicas y canónicas por función; IDs ausentes,
duplicados o adulterados se rechazan en MIR y SSA. Los corruption tests cubren
null/inject/test/payload incoherentes además de las verificaciones generales de
dominance, phi, drop y ownership existentes.

## Calificación

La suite dedicada es
`compiler-next/crates/aether-driver/tests/nullable_v1.rs`. Cubre, entre otros:

- null/present, inyección, returns, defaults, const y generics;
- inferencia genérica positiva y rechazo de null-only inference;
- string, class, struct, List, Function y las cuatro formas de reference;
- comparación simétrica, then/else, joins, assignments, aliases y loops;
- short-circuit `&&`/`||`/`!`;
- payload Copy y rechazo de Move owning;
- layouts niche/tagged, ABI y mangling;
- cleanup normal/unwind y ejecución nativa O0/O2;
- corrupción nullable de MIR/SSA.

Comandos de cierre ejecutados:

```text
cargo test --workspace
cargo fmt --all -- --check
cargo clippy --workspace --all-targets -- -D warnings
git diff --check
bash compiler-next/tests/run-differential.sh
```

El differential conserva 21/21 resultados esperados del compilador legacy.
