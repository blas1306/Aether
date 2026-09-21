# GENERIC-LOCAL-INFERENCE-ARCH-1 — design report

Estado: **ARQUITECTURA CERRADA; NO IMPLEMENTADA**, 2026-09-21.

Documento normativo:
[GENERIC_LOCAL_INFERENCE_ARCH_1.md](GENERIC_LOCAL_INFERENCE_ARCH_1.md).

Sólo se agregaron documentos. No se modificó lexer, parser, AST, HIR, MIR, SSA,
backend, runtime, tests ni la superficie source admitida.

## Resultado

Se aprobó la omisión total de argumentos del constructor generic root de una
declaración local con initializer:

```aether
QR qr = la.qr(a);       // RHS QR<double>; binding QR<double>
Pair p = makePair();    // RHS Pair<int, string>; binding igual
List xs = makeList();   // RHS List<int>; binding igual
```

El nombre escrito fija la familia. El initializer se tipa primero sin expected
type aportado por la declaración; luego se exige identidad exacta de constructor
y se adopta el mismo `TypeId` completo del RHS. No se inspecciona la sintaxis de
la expresión, no se busca otra familia, no se resuelven overloads por resultado
y no se implementa `var`.

## Representación y frontera IR

El AST conserva el named type normal con cero argumentos. El resolver local lo
clasificará temporalmente como `Exact(TypeId)` o `InferRoot(LocalTypePattern)`.
El patrón contiene la identidad de `StructId`, `EnumId` o constructor
intrínseco, pero nunca se interna en `TypeArena`.

No existirán `Box`, `Box<?>`, raw generics ni holes en HIR/MIR/SSA. Antes de
publicar el binding, frontend adopta la aplicación canónica del RHS y mantiene
la invariante `HirLocal.ty == initializer.ty`. Los niveles posteriores no
conocen la inferencia; layout, mangling, ABI, monomorfización, ownership y
codegen son idénticos al spelling explícito.

## Scope cerrado

V1 cubre structs/enums generic y los constructores intrínsecos source como
`List`, `Array`, `Matrix` y `Vector`. Un tipo no generic y una aplicación con
argumentos explícitos siguen la ruta actual.

Se admite `Box? b = rhs` sólo cuando RHS ya es exactamente `Box<X>?`. No se usa
la inyección `Box<X> -> Box<X>?` para fabricar evidencia. `ref Box`,
`ref mut Box` y `(ref Box)?` quedan fuera hasta cerrar provenance/lifetimes.

No hay inferencia recursiva: `List<Box>`, `Map<string, List>` y
`Pair<int, Box>` fallan. Fields, parameters, returns, aliases, signatures,
payloads, locals sin initializer, patterns y otros bindings siguen requiriendo
argumentos completos.

## Exactitud y conversiones

`Box` sólo hace match con la misma declaración nominal `Box`; `OtherBox<int>`,
un subtipo, una interface o un tipo de igual layout fallan. Las familias
intrínsecas también son distintas entre sí. La ruta inferida no aplica numeric
widening, upcast, interface adaptation, nullable injection ni borrow adaptation:
tras un match correcto, cualquier conversión sería identidad porque el binding
adopta exactamente el tipo RHS.

Un `GenericParam` legítimo dentro de `Box<T>` sí es un tipo completo en un body
generic y puede adoptarse. Una variable de inferencia sin resolver no puede
llegar a HIR. `Box b = null` y calls cuyo resultado sólo se determinaría desde
el expected type fallan sin inventar `Any`, dynamic o defaults.

## Diagnósticos y qualification

Se propuso `E0460..E0464` para familia distinta, RHS no aplicable, RHS
indeterminado, contexto de omisión no soportado y shape nullable/canónica
incorrecta. Name lookup, imports, visibility, constraints, element admission y
errores internos del RHS conservan sus diagnósticos existentes.

El primer vertical debe cubrir familias de uno y varios argumentos, nominales e
intrínsecas, const, bodies generic, nullable, ownership/Drop/unwind, negativos
de mismatch/null/nesting/references/contexto, imports y constraints. La prueba
central compara spelling omitido contra explícito y exige paridad semántica e
identidad MIR/SSA/LLVM salvo provenance source.

## Validación del milestone

- Se crearon únicamente el documento normativo y este reporte.
- Se preservaron todos los cambios preexistentes del working tree.
- Se cerraron sintaxis, lookup, familias elegibles, representación temporal,
  orden de typing, exactitud nominal, conversions, nullable, references,
  nesting, generics abiertos bien formados, ownership, IR, diagnósticos,
  qualification y criterios de aceptación.
- No queda una decisión abierta dentro del alcance V1.
- No se declara implementada ninguna conducta source nueva.

