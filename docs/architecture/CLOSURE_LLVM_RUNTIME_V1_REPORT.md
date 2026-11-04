# Aether — CLOSURE-LLVM-RUNTIME-V1 — Implementation & Qualification

Estado: **CLOSED — IMPLEMENTACIÓN PRODUCTIVA, QUALIFICATION FOCAL Y WORKSPACE
COMPLETOS**, 3 de noviembre de 2026.

## Qualification de cierre tras la auditoría completa de `dot`

La causa restante del gate global era una tercera expectativa matemática
incorrecta en `testDotConsumer()`, no un defecto de `dot` ni una regresión de
Closure. Se corrigió únicamente `32.0 -> 14.0` para
`dot(Array{1,2,3}, List{1,2,3})`, porque
`1*1 + 2*2 + 3*3 = 14`. Se conservaron las dos correcciones previas
`54.0 -> 122.0` y `74.0 -> 122.0`. No se modificaron `linearAlgebra/src/lib.ae`,
las APIs públicas, los overloads, la indexación, QR ni otros tests.

### Auditoría matemática de `testDotConsumer()`

Los diez casos tienen longitud o dimensión 3. Array y List se recorren desde
0; Vector Row y Column, desde 1. Los overloads mixtos adaptan el índice del
Vector mediante `i + 1`. Todos los overloads validan primero igualdad de
longitudes/dimensiones con `shapeGuard`. La función auditada no contiene casos
que esperen errores o excepciones y ninguno de sus operandos es incompatible;
por ello los diez guards deben aceptar las entradas. Los 16 overloads cubren
Array/List, las cuatro orientaciones Vector/Vector y las ocho combinaciones
Array/List con Vector en ambos órdenes.

| Retorno | Llamada y operandos | Expectativa encontrada | Correcta | Cálculo independiente |
|---:|---|---:|---:|---|
| 1 | `arrayA{1,2,3} . arrayB{4,5,6}` | 32 | 32 | `1*4 + 2*5 + 3*6` |
| 2 | `listA{7,8,9} . listB{1,2,3}` | 50 | 50 | `7*1 + 8*2 + 9*3` |
| 3 | `arrayA{1,2,3} . listB{1,2,3}` | 32 | 14 | `1*1 + 2*2 + 3*3` |
| 4 | `listA{7,8,9} . arrayB{4,5,6}` | 122 | 122 | `7*4 + 8*5 + 9*6` |
| 5 | `rowA{1,2,3} . columnB{4,5,6}` | 32 | 32 | `1*4 + 2*5 + 3*6` |
| 6 | `columnB{4,5,6} . rowA{1,2,3}` | 32 | 32 | `4*1 + 5*2 + 6*3` |
| 7 | `arrayA{1,2,3} . rowA{1,2,3}` | 14 | 14 | `1*1 + 2*2 + 3*3` |
| 8 | `rowA{1,2,3} . arrayB{4,5,6}` | 32 | 32 | `1*4 + 2*5 + 3*6` |
| 9 | `listA{7,8,9} . columnB{4,5,6}` | 122 | 122 | `7*4 + 8*5 + 9*6` |
| 10 | `columnB{4,5,6} . listB{1,2,3}` | 32 | 32 | `4*1 + 5*2 + 6*3` |

La columna «expectativa encontrada» refleja el estado al iniciar esta
qualification: los casos 4 y 9 ya contenían las correcciones previas a 122;
el caso 3 era la única constante restante que debía cambiar.

### Qualification progresiva y global

El primer intento de O0 con `TMPDIR=$HOME/tmp` terminó con código 1 antes de
ejecutar el consumer: el sandbox expuso ese directorio como read-only y el
driver informó `E0700: could not write temporary LLVM`. Se repitieron todos los
gates con `TMPDIR=/tmp/aether-linear-algebra-qualification`, directorio
escribible dedicado. Este incidente de infraestructura no se contabiliza como
fallo del consumer.

Resultados finales, todos con `CARGO_INCREMENTAL=0`:

```text
cargo run -q -p aether-cli -- run ../linearAlgebra/tests/consumer -O0  # exit 0
cargo run -q -p aether-cli -- run ../linearAlgebra/tests/consumer -O2  # exit 0
cargo test -p aether-registry --test registry \
  linear_algebra_oal_publishes_and_runs_real_qr_consumer -j 1 \
  -- --exact --nocapture                                                # exit 0; 1/1; 1083.20 s
cargo test --workspace -j 1                                            # exit 0
cargo fmt --all --check                                                 # exit 0
cargo clippy --workspace --all-targets -j 1                             # exit 0
git diff --check                                                        # exit 0
```

O0 y O2 imprimieron las factorizaciones `Q`/`R` del consumer real y toda la
salida posterior de Cholesky, SVD y eigen, demostrando que no hubo retorno
anticipado después de `testDotConsumer()`. El registry aislado publicó el
package y ejecutó ambas optimizaciones. Dentro del workspace, registry terminó
5/5 en 1094,48 s, `vertical` 220/220, frontend 78/78 y middle 29/29; Cargo
alcanzó y completó los doc-tests de las siete crates.

La qualification focal de Closure, distinguible del gate global, también
quedó verde dentro de esa ejecución:

- `owning_closures_read_v1`: 25/25, con O0/O2, corrupción HIR/MIR/SSA,
  cross-source-module, lifecycle, contadores ARC/alloc/free y ASan;
- `anonymous_functions_v1`: 5/5;
- `function_values_v1`: 8/8;
- Exceptions V1–V4: 6/6, 8/8, 8/8 y 7/7.

Clippy conservó warnings preexistentes y terminó con código 0. No se cambiaron
contratos de Closure, Function ni ABI. Con qualification focal y gate global
verdes, **CLOSURE-LLVM-RUNTIME-V1 queda CLOSED**. Las secciones PARTIAL que
siguen se conservan como historial de los fallos y aislamientos anteriores.

Archivos modificados para el cierre:

- `linearAlgebra/tests/consumer/src/main.ae`;
- `docs/architecture/CLOSURE_LLVM_RUNTIME_V1_REPORT.md`;
- `docs/architecture/OWNING_CLOSURES_READ_V1_REPORT.md`.

El reproducer `linear_algebra_dot_exit_88` se conserva sin cambios como
evidencia histórica del primer defecto de expectativas.

## Qualification final tras corregir las dos expectativas documentadas

Se aplicó la corrección mínima solicitada en
`linearAlgebra/tests/consumer/src/main.ae`: las expectativas `54.0` y `74.0`
de `dot(listA,arrayB)` y `dot(listA,columnB)` pasaron a `122.0`. Ambos casos
usan, en el mismo orden, los valores `{7,8,9}` y `{4,5,6}`; el segundo sólo
adapta el operando derecho de `Array` 0-based a `Vector<Column>` 1-based. No se
modificaron `dot`, sus overloads, la indexación ni ningún otro test.

El consumer real todavía termina 88 y no produce stdout, tanto en O0 como en
O2:

```text
TMPDIR=$HOME/tmp CARGO_INCREMENTAL=0 \
  cargo run -q -p aether-cli -- run ../linearAlgebra/tests/consumer -O0  # exit 88
TMPDIR=$HOME/tmp CARGO_INCREMENTAL=0 \
  cargo run -q -p aether-cli -- run ../linearAlgebra/tests/consumer -O2  # exit 88
```

El preflight ampliado encontró una tercera expectativa matemáticamente
incompatible, anterior a las dos corregidas:

```aether
Array<double> arrayA = {1.0,2.0,3.0};
List<double> listB = {1.0,2.0,3.0};
if (la.dot(arrayA,listB) != 32.0) { return 3; }
```

Ese producto es `1*1 + 2*2 + 3*3 = 14`, no `32`. El overload
`dot(ref Array<T>, ref List<T>)` itera ambos containers 0-based y, por tanto,
la condición rechaza el resultado matemáticamente correcto. No se cambió esta
tercera aserción porque la autorización de esta qualification fue explícita:
corregir exclusivamente `54.0` y `74.0` y no modificar otros tests para
hacerlos pasar. El exit 88 histórico se conserva como diagnóstico de un fallo
del consumer y no se atribuye a Closure Runtime; las dos correcciones pedidas
resolvieron sus dos defectos documentados, pero no este gate adicional.

El test de registry aislado confirmó el mismo resultado en su consumer
publicado: código global `101`, 0/1, O0 `Some(88)`, 398,47 s. Por diseño abortó
antes de O2; la ejecución directa anterior sí cubrió O2.

La qualification focal de Closure se reejecutó completa y terminó con código
0: `owning_closures_read_v1` 25/25 (O0/O2, corrupción HIR/MIR/SSA,
cross-source-module, lifecycle, ARC/alloc/free y ASan),
`anonymous_functions_v1` 5/5, `function_values_v1` 8/8 y Exceptions V1–V4
6/6, 8/8, 8/8 y 7/7. Se mantuvieron el ABI interno aprobado y las fronteras
de `Function`/`Closure`; no se añadieron Callable, adapters ni capacidades.

El workspace serial completo avanzó con todos los grupos anteriores en verde,
incluidos `vertical` 220/220, frontend 78/78 y middle 29/29, pero terminó con
código `101` en registry 4/5: el consumer volvió a salir O0 `Some(88)` después
de 408,34 s. Cargo no alcanzó los doc-tests, por lo que no se declaran PASS.
Los otros gates terminaron así:

```text
cargo fmt --all --check                         # exit 0
cargo clippy --workspace --all-targets -j 1    # exit 0, warnings preexistentes
git diff --check                                # exit 0
```

Veredicto de esta qualification: **CLOSURE-LLVM-RUNTIME-V1 PARTIAL** y
**OWNING-CLOSURES-READ-V1 PARTIAL**. El runtime y sus pruebas focales están
completos, pero el gate normativo exige workspace, registry y doc-tests
completos con código 0. No se inició otro milestone.

## Aislamiento final de la regresión de registry

### Snapshot y preservación

El preflight partió de `b7a2c4df64f04531a1bb5afa0382b3485b170fac`
(`feat(compiler): implement owning closure LLVM runtime`) con `git status`
limpio. Se inspeccionaron los reportes de Closure, el consumer de registry, el
historial de los tres archivos afectados y los overloads nuevos de `dot`. No se
modificaron `linearAlgebra/src/lib.ae`, su consumer, Plots, Graphics, las
bibliotecas numéricas ni los ejemplos personales.

El test de registry publica `linearAlgebra/src/lib.ae`, copia literalmente
`linearAlgebra/tests/consumer/src/main.ae` y ejecuta O0 antes de O2. Los hashes
del snapshot investigado son:

```text
76756aeaae6c89dc21c2c4f91fc8f8630be839c94b532885399985d9d7e7ccf5  linearAlgebra/src/lib.ae
244ff06e913e5d3d59a9a2f954334d14eae62796b95224d4303eb31c5c8d7a4a  linearAlgebra/tests/consumer/src/main.ae
c16ebdd2055103a83099d0d92f419ac8787847794965d9a7e685408bd1f97ff8  linearAlgebra/aether.toml
e701376fc796da20dd598a9daf203bc5688803c51af25d9bb69c838e74a1705c  linearAlgebra/tests/consumer/aether.toml
```

### Causa exacta de 88

`main` llama primero a `testDotConsumer()` y retorna `600` si el helper
retorna cualquier valor distinto de cero. POSIX expone sólo los ocho bits bajos
del status: `600 mod 256 = 88`.

La primera aserción incorrecta del helper es:

```aether
List<double> listA = {7.0,8.0,9.0};
Array<double> arrayB = {4.0,5.0,6.0};
if (la.dot(listA,arrayB) != 54.0) { return 4; }
```

El overload `dot(ref List<T>, ref Array<T>)` valida longitudes iguales,
inicializa un acumulador `T` en cero e itera ambos containers 0-based en
`0..<length`. Produce correctamente `7*4 + 8*5 + 9*6 = 122`, no `54`. El
reproducer mínimo imprime `122` y conserva la comparación y el retorno `600`;
termina 88 en O0 y O2. La aserción posterior
`dot(listA,columnB) != 74.0` también tiene expectativa incorrecta: el adaptador
List 0-based / Vector 1-based es correcto y el resultado vuelve a ser `122`.

No se observó error numérico, dimensional, de tipos, ownership ni backend. Los
argumentos son préstamos `ref`, las dimensiones son tres, el acumulador es
`double` y el fallo es independiente de la optimización. La corrección
propuesta al owner del consumer es cambiar esas dos expectativas a `122.0`;
no se aplicó para preservar los archivos concurrentes.

Reproducer entregado:
`reproducers/owning_closures_read_v1/linear_algebra_dot_exit_88`.

### Comparación con fuentes idénticas

Se extrajo `93a437e2` (`feat(compiler): implement verified closure ownership
IR`), padre inmediato anterior al runtime LLVM productivo, en
`/tmp/aether-owning-closures-baseline-93a437e2`. Se copiaron allí los cuatro
archivos del snapshot actual y se volvieron a verificar los hashes anteriores.
El worktree principal no se cambió.

Target observado: `x86_64-pc-linux-gnu`. Comandos, ejecutados desde el
`compiler-next` de cada snapshot:

```text
cargo run -q -p aether-cli -- run ../linearAlgebra/tests/consumer -O0
cargo run -q -p aether-cli -- run ../linearAlgebra/tests/consumer -O2
```

| Compilador | O0 | O2 | stdout del consumer |
|---|---:|---:|---|
| `b7a2c4df64f04531a1bb5afa0382b3485b170fac` | 88 | 88 | vacío |
| `93a437e2` + fuentes actuales verificadas | 88 | 88 | vacío |

El reproducer sobre el compilador actual observó `stdout = 122` y exit 88 en
ambos modos. No fue necesaria una comparación de LLVM IR: el valor producido
es matemáticamente correcto, el consumer rechaza ese mismo valor por una
constante source incorrecta y ambos compiladores reproducen el mismo status.
Esta evidencia demuestra preexistencia del fallo observado respecto de Closure
Runtime; no afirma descartar toda interacción posible no cubierta.

### Qualification final y workspace

La ejecución focal, sin cambios productivos adicionales, terminó:

- `owning_closures_read_v1`: 25/25 PASS O0/O2, incluidos corrupción
  HIR/MIR/SSA, cross-source-module, lifecycle, contadores ARC/alloc/free y ASan;
- `anonymous_functions_v1`: 5/5 PASS;
- `function_values_v1`: 8/8 PASS;
- Exceptions V1–V4: 6/6, 8/8, 8/8 y 7/7 PASS.

Comando focal:

```text
CARGO_INCREMENTAL=0 cargo test -p aether-driver -j 1 \
  --test owning_closures_read_v1 --test anonymous_functions_v1 \
  --test function_values_v1 --test exception_v1 --test exception_v2 \
  --test exception_v3 --test exception_v4
```

El workspace actual se ejecutó completo con TMPDIR aislado y terminó con código
`101`. Todos los grupos anteriores pasaron, incluidos `vertical` 220/220,
frontend 78/78, middle 29/29 y registry 4/5. El último test falló después de
418,93 s con `linearAlgebra consumer failed at O0: Some(88)`; por diseño se
detuvo antes de O2. La ejecución directa separada sí confirmó O2=88.

```text
TMPDIR=/tmp/aether-owning-closures-read-v1 CARGO_INCREMENTAL=0 \
  cargo test --workspace -j 1                         # exit 101
cargo fmt --all --check                              # exit 0
cargo clippy --workspace --all-targets -j 1          # exit 0, warnings preexistentes
git diff --check                                     # exit 0
```

Veredicto: **CLOSURE-LLVM-RUNTIME-V1 PARTIAL** y
**OWNING-CLOSURES-READ-V1 PARTIAL**. La implementación, los gates focales y el
aislamiento de regresión están completos, pero el criterio normativo exige un
workspace verde para CLOSED. El snapshot actual no lo cumple; corresponde una
aceptación condicionada a que el owner de `linearAlgebra` corrija y califique
las expectativas del consumer.

Archivos modificados o añadidos por este aislamiento:

- `docs/architecture/CLOSURE_LLVM_RUNTIME_V1_REPORT.md`;
- `docs/architecture/OWNING_CLOSURES_READ_V1_REPORT.md`;
- `reproducers/owning_closures_read_v1/linear_algebra_dot_exit_88/README.md`;
- `reproducers/owning_closures_read_v1/linear_algebra_dot_exit_88/aether.toml`;
- `reproducers/owning_closures_read_v1/linear_algebra_dot_exit_88/aether.lock`;
- `reproducers/owning_closures_read_v1/linear_algebra_dot_exit_88/.aether-package.lock`;
- `reproducers/owning_closures_read_v1/linear_algebra_dot_exit_88/src/main.ae`.

## Resultado

El backend LLVM productivo de closures owning read-only quedó implementado a
partir de `VerifiedSsa`. Se retiró la frontera `E0376`; no se modificó el ABI de
`Function`, no se añadió un Callable general y no se reconstruyen capturas por
nombres source.

`ClosureABI-v1` usa un carrier `ptr` owning al byte cero de:

```text
0   usize strong_count
8   ptr   invoke_thunk
16  ptr   destroy_thunk
24+ payload, alineado según sus fields
```

El backend acepta el bootstrap x86-64 vigente, calcula offsets, tamaño y
alignment mediante `layout_of` y aritmética checked, y aborta fail-closed si se
intenta emitir Closure con un target de word/pointer distinto de 64 bits.

## Implementación

- `ClosureCreate` asigna el box, escribe header, adquiere captures en orden
  canónico y publica el carrier sólo después del último store.
- `Copy` materializa un snapshot; `Alias` usa el retain intrínseco de string,
  class/interface o Closure; `Move` transfiere los bits del root ya invalidado
  por el ownership IR.
- Las adquisiciones V1 son nounwind o traps abortivos. Por ello no existe hoy
  un unwind recuperable entre captures; el contrato de prefijo queda preservado
  sin inventar una ruta de rollback inobservable.
- Cada environment genera un invoke thunk `R(ptr box, P...)` con prototype
  derivado de la firma verificada. Sólo el thunk proyecta el payload y entrega
  los `capture_slots` read-only al body sintético.
- Cada environment genera un destroy thunk `void(ptr) nounwind`, destruye en
  orden inverso y libera con el size/alignment exactos.
- Los drops aparentes de `capture_slots` en el body no emiten destrucción LLVM:
  esos slots son vistas privadas read-only y su única destrucción corresponde
  al destroy thunk.
- `ClosureAlias`, `ClosureBorrow`, `ClosureCall` y `EndClosureBorrow` poseen
  lowering propio. La call carga exclusivamente offset 8, pasa el box oculto,
  conserva el borrow en normal/unwind y no hace ARC por invocación.
- `aether_closure_retain_v1` y `aether_closure_release_v1` son versionados,
  nounwind y fail-closed para zero/overflow/underflow. El último release fija
  count cero antes de llamar al destroy thunk.
- Invoke/destroy/body y todas sus dependencias permanecen emitidos aunque el
  único root visible sea un pointer almacenado en el header. El mangling parte
  de la identidad única del target sintético, que incluye package/source,
  lambda/instancia y firma del programa conjunto.

No se añadieron TLS, trampolines globales, GC, weak ownership ni conversiones
`Function`/`Closure`.

## Qualification productiva

`aether-driver/tests/owning_closures_read_v1.rs` ejecuta binarios reales O0/O2
y cubre:

- Copy automático y snapshot frente a mutación exterior;
- Alias de string, class, interface y otra Closure;
- Move explícito de aggregate owning;
- captures mixtas/parciales, varios parámetros e invocación repetida;
- closure nunca invocada, paths condicionales y destrucción al salir;
- paso/retorno, supervivencia al creator, alias de argumento, replacement y
  self-assignment;
- lambdas anidadas y captura transitiva;
- excepción desde el body, catch, normal/unwind borrow cleanup y owner vivo;
- fuentes/packages declarados distintos dentro de una `CompilationSession`;
- offsets 0/8/16/24, reachability, prototype oculto y destroy `nounwind`;
- contadores exactos: retain 1, release 2, destroy 1, alloc 1, free 1 para un
  paso owning por alias;
- AddressSanitizer para captures mixtas (UAF/double-free). LeakSanitizer no es
  utilizable bajo la política ptrace del entorno; la instrumentación
  alloc/free y el gate de balance del runtime verifican leaks en los consumers.

Resultado focal final: **25/25 PASS**. Los corruption tests HIR/MIR/SSA y los
tests de capture/ownership IR permanecen en el mismo target.

Regresiones focales adicionales ejecutadas:

- `anonymous_functions_v1`: 5/5 PASS;
- `function_values_v1`: 8/8 PASS;
- `exception_v1`: 6/6 PASS;
- `exception_v2`: 8/8 PASS;
- `exception_v3`: 8/8 PASS;
- `exception_v4`: 7/7 PASS.

`cargo fmt --all --check`, Clippy del workspace y `git diff --check`
finalizaron con código 0. Clippy conserva warnings preexistentes; los dos
warnings nuevos del backend fueron corregidos.

`CARGO_INCREMENTAL=0 cargo test --workspace -j 1` ejecutó todo el workspace y
todos los grupos anteriores al último terminaron PASS, incluidos `vertical`
220/220, frontend 78/78, middle 29/29 y registry 4/5. El último test,
`linear_algebra_oal_publishes_and_runs_real_qr_consumer`, terminó **FAIL** porque
el consumer salió 88 en O0. Durante este trabajo aparecieron cambios ajenos en
`linearAlgebra/src/lib.ae` y su consumer que añaden `dot` y hacen retornar 600
si esa nueva prueba falla; esos cambios se preservaron y no pertenecen a este
subvertical. Por tanto el workspace completo no se declara PASS.

## Alcance ABI

Se calificó interoperabilidad entre funciones, módulos fuente y packages
fuente compilados conjuntamente. Artefactos Aether producidos por
compilaciones independientes, metadata ABI persistida y bibliotecas
precompiladas continúan **OUT OF SCOPE** según
`FIRST_CLASS_CLOSURES_ARCH_1_ABI_SCOPE_AMENDMENT.md`.

## Archivos del subvertical

- `compiler-next/crates/aether-backend-llvm/src/lib.rs`;
- `compiler-next/crates/aether-driver/src/lib.rs`;
- `compiler-next/crates/aether-driver/tests/owning_closures_read_v1.rs`;
- `compiler-next/crates/aether-driver/tests/anonymous_functions_v1.rs`;
- `compiler-next/tests/modules/owning_closures_read_v1/main.ae`;
- `compiler-next/tests/modules/owning_closures_read_v1/provider.ae`;
- `docs/architecture/CLOSURE_LLVM_RUNTIME_V1_REPORT.md`;
- `docs/architecture/OWNING_CLOSURES_READ_V1_REPORT.md`.

Clasificación conservadora: **CLOSURE-LLVM-RUNTIME-V1 PARTIAL** únicamente por
el gate global de workspace no verde; backend y qualification específica están
completos. `OWNING-CLOSURES-READ-V1` permanece **PARTIAL** hasta rerun verde del
workspace después de integrar o corregir los cambios concurrentes de
`linearAlgebra`.
