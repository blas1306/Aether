# PACKAGE-ERGONOMICS-V1 — single-unit anonymous entry

Estado: **IMPLEMENTADO Y CALIFICADO**, 2026-09-15, para `compiler-next`, bajo
el contrato de
[PACKAGE-ERGONOMICS-ARCH-1](PACKAGE_ERGONOMICS_ARCH_1.md).

## Resultado

Una source unit de entrada puede omitir `package` y conserva
`ParsedAst.package = None`. Semántica le asigna `PackageKey::Anonymous`; no se
sintetiza un `AstPackage`, no se normaliza a `main` y no se construye un
`PackagePath` vacío. `package A.B;` continúa usando
`PackageKey::Named { origin, path }` y mantiene packages parciales, imports,
identidades y ABI existentes.

El anonymous package es una identidad nominal estructural, graph-local y sin
spelling source. El label `<anonymous package>` existe únicamente como metadata
de display en dumps. Los índices por path, representatives de prefixes y maps
de imports contienen sólo variants `Named`; un `ResolvedImport` interno cuyo
target sea `Anonymous` falla cerrado.

## Parser y diagnostics

El parser acepta imports o declaraciones como primer item cuando no existe
`package`. La ausencia ya no produce E0230. Si aparece `package` después de
haber consumido otro item, se emite E0107 con uno de los mensajes normativos:

- `package declaration must be the first non-trivia item` cuando no hubo una
  declaración inicial;
- `source unit contains more than one package declaration` cuando ya hubo una.

La declaración inicial named conserva su parsing, span y reglas. El catálogo
mantiene la reserva de `std`; los diagnostics de imports y packages named no
cambian.

## Identidad, catálogo y source graph

`PackageKey` es ahora una suma `Named`/`Anonymous`. `PackagePath` permanece
exclusivo de `Named` y su validador rechaza el vector vacío como corrupción. La
collection package-wide continúa indexada por `PackageId`, por lo que una única
unidad anonymous obtiene lookup no calificado de sus propios members sin abrir
un namespace público.

Discovery canonicaliza primero el locator del entry. A partir de ese archivo
canónico calcula el source root y el `LogicalSourceKey` relativo. Por ello
`main.ae`, `./main.ae` y el path absoluto del mismo archivo producen el mismo
grafo, dumps y LLVM. El CWD sólo participa en localizar un spelling relativo;
no entra en identidad ni mangling.

Si el entry es anonymous, el provider lo carga explícitamente como la única
unidad de esa identidad y continúa discovery únicamente desde sus imports
named. Otros archivos sin `package` bajo el mismo root no se agregan. Un entry
named conserva el algoritmo previo de contribuciones multi-file y tampoco
descubre archivos anonymous vecinos.

El validador de `ParsedProgram` impone la cardinalidad V1 antes de collection de
declarations. Dos unidades anonymous producen E0241 y el mensaje
`V1 permits only one source unit without a package declaration per source graph`,
incluyendo ambos nombres de source. También comprueba coherencia entre la
variant nominal y el AST, rechaza `PackagePath` named vacío e imports dirigidos
a Anonymous.

## Imports y entrypoint

Una unidad anonymous usa sin cambios imports jerárquicos de proyecto y de
toolchain, incluidos `std.File` y `std.Text`. Todos los targets se construyen
como `PackageKey::Named`; `import anonymous;` denota el package named ordinario
`anonymous`, nunca la variant interna.

La selección de `main` continúa partiendo de `ParsedProgram.entry`. Un `main`
en un package importado es una función ordinaria y no reemplaza al entry. El
wrapper nativo sigue siendo `i32 @main()` y conserva la conversión existente del
resultado Aether.

## Mangling y compatibilidad named

Los símbolos anonymous usan el discriminante reservado
`__aether_v2_a0_...`, independiente del filename, path absoluto y CWD. Los
nominales anonymous usan el mismo discriminante estructural en argumentos de
tipo. Ese dominio no puede colisionar con el prefijo named
`__aether_v2_m<length>_...` ni con helpers privados de runtime.

La ruta named del mangler no cambió. La qualification fija byte por byte, entre
otros, estos resultados previos:

```text
Stable.App::helper -> __aether_v2_m10_Stable_2eApp_f6_helper
Stable.App::main   -> __aether_v2_m10_Stable_2eApp_f4_main
```

También conserva el comportamiento histórico del provider sintético
in-memory, cuyo label físico de módulo named sigue siendo `main`; su identidad
nominal reside separadamente en `SourceUnitKey.package`. `ModuleInfo` denomina
ahora ese campo `display_name` para impedir que un string de presentación sea
interpretado como identidad.

## Qualification

La suite nueva
`compiler-next/crates/aether-driver/tests/package_ergonomics_v1.rs` cubre:

- AST `None`, HIR/MIR/SSA/LLVM y wrapper para un entry anonymous;
- ejecución nativa O0/O2;
- imports anonymous hacia `std.File`, `std.Text` y un package named de proyecto;
- named entry y package named multi-file sin regresión;
- `package anonymous;` coexistiendo con `PackageKey::Anonymous`;
- selección de `main` sólo desde el entry;
- archivos anonymous vecinos no alcanzados tanto con entry named como anonymous;
- dos unidades anonymous inyectadas;
- `ResolvedImport` forjado hacia Anonymous;
- `PackagePath` named vacío;
- package misplaced y duplicate con mensajes exactos;
- equivalencia byte por byte de `main.ae`, `./main.ae` y path absoluto;
- mangling named fijado a bytes conocidos y mangling anonymous separado.

Resultados finales:

- `cargo test --workspace`: **486 passed, 0 failed**;
- `cargo fmt --all --check`: **pass**;
- `cargo clippy --workspace --all-targets -- -D warnings`: **pass**;
- `git diff --check`: **pass**;
- `bash compiler-next/tests/run-differential.sh`: **checked=21, failures=0**.

## Scope preservado

No se agregó anonymous multi-file, manifest, inferencia de package desde el
filesystem, script mode, nueva forma de import, export anonymous ni cambio de
ABI named. No se modificó el compiler legacy. La composición anonymous futura
sigue requiriendo una fuente explícita de membership distinta de proximidad
física.
