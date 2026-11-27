# EXPONENTIATION-V1 — informe de implementación y qualification

Estado: **CLOSED**

Fecha: 2026-11-27

Base: `1d4ead847f629cb8ede4ac9aad6e77800cc3716e`

Autoridad normativa: [EXPONENTIATION-ARCH-1](EXPONENTIATION_ARCH_1.md), cerrada
antes de iniciar esta implementación.

## Resultado

`compiler-next` admite `base ** exponent` y el `pow(base, exponent)` oficial de
Core mediante una única autoridad semántica. La implementación cubre las tres
familias aprobadas (`IntegerChecked`, `FloatInteger`, `FloatLibm`), conserva un
`PowerSpec` explícito y verificado en HIR/MIR/SSA, y baja a helpers LLVM internos
o a `powf`/`pow` según el modo.

`**=` no fue implementado. Tampoco se agregaron potencia genérica, overloads de
usuario, potencia de aggregates/complex, fast-math ni nuevos targets.

## Superficie y resolución

- El lexer aplica maximal munch a `**`; `*`, `*=`, dereference, bitwise,
  referencias y genéricos conservan sus tokens vigentes. `**=` se rechaza.
- El parser implementa `power := postfix ('**' unary)?`: asociatividad derecha,
  precedencia superior a prefijos por la izquierda y unary completo por la
  derecha.
- `resolve_power` tipa primero la base con el contexto de resultado y después
  el exponente con el contexto específico de la familia. No usa `common()` para
  exponentes integer ni los convierte al tipo de la base.
- Core incorpora `CoreSymbol::Pow`. Una llamada que llega al prelude se
  canonicaliza a `HirExprKind::Power`; su `CoreSymbolKey` queda autenticado en
  HIR. El lookup lexical/package sigue precediendo al prelude, por lo que una
  función local `pow` conserva shadowing normal.

## Contrato de tipos y traps

`IntegerChecked` conserva el `TypeId` exacto de la base y acepta cualquiera de
los diez enteros como exponente. Un negativo constante produce diagnóstico
`E0500`; un negativo dinámico conserva `NegativeIntegerExponent`; cada producto
usa el intrinsic checked signed/unsigned de la base y conserva
`IntegerOverflow`.

`FloatInteger` conserva la precisión de la base y procesa directamente el
patrón del exponente. Los negativos usan resta modular sin flags de overflow
para obtener la magnitud unsigned, incluido signed MIN, y aplican el recíproco
antes del loop.

`FloatLibm` homogeneiza sólo mediante el widening ordinario
`float32 -> float64` y selecciona `powf` o `pow`. Sus resultados excepcionales
son valores IEEE/libm y no traps Aether.

`Integer ** Float`, bool/char/string, aggregates, user-defined types y
parámetros genéricos se rechazan. Aliases transparentes conservan el tipo
canónico. Una expected type contextualiza la base/result; un exponente integer
literal continúa defaulting a `int64`.

## Algoritmos, folding y backend

Los modos integer y float-integer usan exponenciación binaria O(log e). El modo
integer valida dominio antes de multiplicar, resuelve `0`, `1` y `-1` en tiempo
constante, preserva `0 ** 0 = 1` y omite el cuadrado final. El modo
float-integer usa `fmul`/`fdiv` sin fast-math, no llama `llvm.powi` y conserva
paridad de exponentes hasta `uint64.max`.

El folding integer usa el mismo esquema binario y los límites exactos del tipo
base. Un resultado constante no representable produce `E0210`. No se pliegan
potencias floating no triviales con la libm del host.

LLVM genera un helper `internal` por `(modo, tipo base, tipo exponente)`
alcanzable. Los helpers integer usan `llvm.[su]mul.with.overflow.iN`; los
float-integer mantienen el orden de redondeos. `FloatLibm` emite llamadas
directas y marca la dependencia `-lm` sólo si una potencia alcanzable lo exige.
No se emiten `nsw`, `nuw`, reassociation ni fast-math sobre estas rutas.

## Verificación y pruebas

HIR, MIR y SSA reconstruyen de forma independiente modo, tipos de operandos,
resultado y política de traps. HIR verifica además provenance Core. Las pruebas
de corrupción alteran modo, trap y `CoreSymbolKey` y confirman rechazo en la
capa correspondiente.

La suite
`compiler-next/crates/aether-driver/tests/exponentiation_v1.rs` cubre:

- los diez enteros, aliases y exponentes heterogéneos;
- precedencia, asociatividad, maximal munch y regresiones de `*`, `*=`, borrow y
  dereference;
- `0/1/-1`, `0 ** 0`, signed MIN, unsigned MAX, overflow exacto, negativo
  constante/dinámico y complejidad logarítmica visible en IR;
- float32/float64, exponentes integer mínimos/máximos, NaN, infinito, signed
  zero, base negativa y separación `FloatInteger`/`FloatLibm`;
- equivalencia operator/Core, shadowing, contexto de literals, folding,
  evaluación única izquierda-derecha, reachability y corrupción MIR/SSA;
- ejecución nativa O0/O2.

Se agregó corrupción HIR focal a los tests internos de `aether-frontend`. Los
fixtures previos que escribían multiplicación seguida inmediatamente de
dereference (`a**b` como `a * *b`) se hicieron explícitos con espacios o
paréntesis; esto es necesario por el maximal munch normativo de `**` y no cambia
su semántica.

## Qualification

Ejecutado desde `compiler-next`:

| Gate | Resultado |
|---|---|
| `tests/qualify.sh core` | **PASS** — 15/15; resultado final `20261127T225224Z` |
| `tests/qualify.sh conformance` | **PASS** — 79/79; resultado final `20261127T225317Z` |
| `cargo test -p aether-driver --test exponentiation_v1` | **PASS** — 9/9 |
| harness y diferencial oficial | **PASS** — gates 78/79 y 79/79 dentro de Conformance |
| `cargo check --workspace` | **PASS** |
| `cargo fmt --all --check` | **PASS** |
| `cargo clippy --workspace --all-targets -j 1` | **PASS**, con warnings preexistentes no denegados |
| OAL Integration | **NOT RUN** — no se modificaron rutas de álgebra lineal productivas |
| Full Ecosystem | **NOT RUN** — no era obligatorio para este milestone |

Una primera corrida Conformance detectó expectativas antiguas: bitwise aún
rechazaba `2**3`, y varios fixtures de álgebra dependían de que `*` seguido de
dereference pudiera escribirse sin separación. Se actualizaron esas pruebas
para la nueva gramática normativa y la repetición completa fue 79/79 PASS. No
se presenta la corrida inicial como gate aprobado.

## Archivos modificados

- Frontend: `lexer.rs`, `parser.rs`, `ast.rs`, `core.rs`, `hir.rs`,
  `hir/classes.rs`, `lib.rs`.
- Middle end: `mir.rs`, `ssa.rs`.
- Backend: `lib.rs` y el nuevo `power.rs`.
- Qualification: `exponentiation_v1.rs`, `qualification.toml` y fixtures de
  regresión bitwise/vertical afectados por maximal munch.
- Contrato y reporte: `AETHER_V1_SEMANTIC_CONTRACT.md` y este documento.

Los cambios personales preexistentes bajo `examples/`, `docs/reports/` y los
dos documentos cerrados EXPONENTIATION-ARCH-1 se preservaron sin modificación.

## Excepciones y riesgos residuales

- La qualification nativa corresponde al perfil Linux x86-64 y su libm. No se
  promete cota ULP, payload NaN idéntico ni reproducibilidad entre plataformas.
- El folding floating no trivial permanece deliberadamente deshabilitado.
- OAL y Full Ecosystem quedan explícitamente `NOT RUN`; no hay evidencia para
  declararlos PASS.

No quedó una obligación normativa conocida incumplida. Por ello
`EXPONENTIATION-V1: CLOSED`.

Commit sugerido: `feat(compiler-next): implement exponentiation v1`.
