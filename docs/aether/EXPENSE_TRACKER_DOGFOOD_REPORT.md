# Informe de dogfooding generalista: expense tracker

Revisión: 15 de julio de 2026. Programa observado:
[`examples/expense_tracker/`](../../examples/expense_tracker/README.md).

## Resultado ejecutivo

El tracker completo funciona en el intérprete AST como programa modular en
memoria. Usa un enum nominal dentro de `Transaction`, seis campos de dominio,
`List<Transaction>`, alta con estado nominal, validación de monto positivo,
listado, resumen, filtro por tipo, lista vacía y múltiples transacciones.

No es todavía una aplicación CLI persistente. Aether no ofrece archivos ni
argumentos del proceso y carece de las operaciones de string necesarias para
interpretar CSV o comandos. LLVM ejecuta un subconjunto representativo con
structs, enums, campos string y agregación, pero el programa completo falla al
materializar `List<Transaction>` porque el backend no conoce el tamaño de un
elemento struct.

No se implementaron features de lenguaje para maquillar estos límites. El
ejemplo separa `Main.ae` (AST completo) de `NativeSubset.ae` (paridad real) y
las pruebas fijan ambas fronteras.

## Qué se implementó

| Capacidad | Evidencia | Estado |
| --- | --- | --- |
| Modelo | `TransactionType`, `Transaction` con enum/string/double/int | AST; modelo aislado también native |
| Alta | `addTransaction` agrega a la lista y retorna `AddTransactionStatus` | AST |
| Validación | monto `<= 0.0` retorna `NonPositiveAmount` sin mutar | AST |
| Listado | recorre y muestra todos los campos con `println` variádico | AST |
| Resumen | ingresos, gastos y balance en `Summary` | AST; algoritmo sin lista en `NativeSubset.ae` |
| Filtro | construye otra lista por `TransactionType` | AST |
| Casos límite | lista vacía, dos elementos y monto cero | AST automatizado |
| Módulos | imports selectivos entre modelo, ledger y reportes | AST; imports del modelo también native |

La fecha es deliberadamente `string`. No existe infraestructura temporal casi
completa que justifique añadir `Date` en esta tarea.

## Estado por nivel

### Nivel 1: AST

`Main.ae` ejecuta todas las operaciones en memoria. La salida contiene nueve
validaciones `true` y dos transacciones legibles. El diseño usa
`List<Transaction>` directamente, sin arrays paralelos ni campos codificados
como enteros.

### Nivel 2: native

`NativeSubset.ae` tiene paridad AST/LLVM y comprueba:

- enum nominal almacenado en struct;
- campos string almacenados, pasados e impresos;
- structs como parámetros y retornos;
- control de flujo y agregación `double`.

`Main.ae` no llega a clang. El emisor LLVM lanza:

```text
LLVM backend does not know the size of struct ...Transaction
```

El frontend, lowering, IR y SSA habían aceptado `List<Transaction>`; el fallo
ocurre al emitir `push`. Es una **feature parcial native** y también un **bug de
diagnóstico**: una combinación fuera del perfil debe rechazarse antes del
backend con código, ubicación y alternativa AST, no filtrar un tipo interno
mangleado. Un probe equivalente muestra el mismo límite para
`Array<Item>` con elemento struct.

### Nivel 3: persistencia y CLI

No puede implementarse de forma real con la superficie actual:

- no hay acceso a argumentos del proceso ni separación `--`;
- `main` no recibe parámetros por diseño actual;
- no hay API de archivos;
- no hay parsing string→`int`/`double`, `split` ni `trim`;
- input tipado es AST-only y no sustituye las otras dos capacidades.

La demostración invoca operaciones desde top-level. No hay `Storage.ae` porque
una API que solo devuelva estados sin tocar un archivo sería ficticia.

## Auditoría de strings

| Operación | AST | Native | Clasificación |
| --- | --- | --- | --- |
| Literal, variable y campo de struct | Sí | Sí para literales/ptr transportado | Parcial runtime |
| Parámetro y retorno | Sí | Sí para ptr transportado | Parcial runtime |
| Igualdad general | Sí | Rechazo temprano | Inconsistencia AST/native delimitada |
| Concatenación `+` | Sí | Rechazo temprano | Inconsistencia AST/native delimitada |
| Interpolación | Sí | Rechazo temprano | Inconsistencia AST/native delimitada |
| `int`/`double` desde string | No | No | Feature ausente / stdlib |
| `split` | No | No | Feature ausente / stdlib |
| `trim` | No | No | Feature ausente / stdlib |
| número→string | Sí en AST mediante cast | No dentro del perfil string completo | Parcial |
| Impresión | Sí | Sí para strings transportados | Parcial pero útil |
| Encoding | depende de `str` Python | literal C/UTF-8 de hecho, sin contrato | Problema runtime/documentación |
| Ownership/lifetime | gestionado por Python | ptr sin ownership de strings dinámicos | Bloqueador runtime |

Ejemplos mínimos observados:

```aether
// AST sí; native lo rechaza por soporte string parcial.
println("food" == "food");
println("foo" + "bar");
println("amount = $250.0$");
```

```aether
// Typechecker: Cannot explicitly convert 'string' to 'int'/'double'.
int id = int("42");
double amount = double("250.0");
```

```aether
// Typechecker: string has no native method 'split'/'trim'.
println("a,b".split(","));
println(" food ".trim());
```

El transporte de literales como `ptr` no equivale a un runtime string. Leer un
archivo, concatenar o producir substrings requiere representación, longitud,
encoding, allocation y liberación definidos.

## Auditoría de colecciones

- `List<Transaction>`: literal vacío target-typed, `push`, iteración, acceso,
  filtrado y agregación funcionan en AST.
- Búsqueda por campo se expresa con loop; no se necesita `Map`.
- Eliminación existe mediante `removeAt`, aunque el tracker no la necesita para
  validar el objetivo actual.
- `Array<Transaction>` también funciona en AST, pero es tamaño fijo y el mismo
  probe de elemento struct falla al calcular tamaño en LLVM.
- Métodos funcionales (`filter`, `map`, iteradores/closures) no existen. Los
  loops explícitos son suficientes y solo plantean un problema de ergonomía.
- `Map` sería útil para agrupar totales por categoría, pero no bloquea alta,
  listado, resumen o filtro. No hay evidencia para convertirlo en prioridad.

La copia de listas es por referencia y los structs son por valor; para listas
de structs con campos string, el backend debe definir copia de bytes y
ownership transitivo antes de declarar soporte completo.

## Auditoría separada de IO

### Entrada estándar

`input` tiene asignación tipada para string y números en AST y reporta errores
de conversión. No tiene lowering native. Puede servir para una demo interactiva
AST, pero no reemplaza argumentos ni persistencia y no se usó para ocultar esos
bloqueos.

### Archivos

No hay tipos ni funciones para abrir, leer, escribir, append, cerrar, encoding
o errores de OS. La carga de módulos fuente por el compilador no es IO
disponible para programas. CSV requiere primero strings dinámicos e IO textual;
un parser CSV simple podría vivir después en stdlib.

### Argumentos del proceso

No hay AST, builtin o stdlib para `argv`; `main` con parámetros se rechaza. El
CLI consume sus propios argumentos y no publica un separador para el programa.
Esto bloquea `add`, `list` y `summary` como comandos reales incluso si hubiera
persistencia.

## Manejo de errores recomendado

- Alta inválida y parsing de registros: resultado nominal estructurado; son
  fallos esperables del dominio.
- IO (`FileNotFound`, datos inválidos, write fallido): resultado estructurado
  en la API mínima; no depender de excepciones native para comenzar.
- Bounds, overflow, OOM e invariantes imposibles: panic del runtime, como las
  colecciones actuales.
- Feature válida pero no compilable (`List<Struct>` hoy): diagnóstico de
  compilación temprano con sugerencia de AST.
- Excepciones futuras: útiles para propagación de fallos inesperados, pero no
  son requisito previo para este tracker ni sustituto de estados esperables.

## Fricciones ordenadas por severidad

| Severidad | Fricción | Clase | Bloquea v1 |
| --- | --- | --- | --- |
| Crítica | Sin modelo native de string dinámico/ownership | Runtime + feature parcial | Sí |
| Crítica | Sin archivos | Feature ausente + stdlib/runtime | Sí según alcance v1 |
| Alta | `List/Array<Struct>` falla tarde en LLVM | Feature parcial native + bug diagnóstico | Sí para datos generales |
| Alta | Sin argumentos del proceso | Feature ausente | Sí según alcance v1 |
| Alta | Sin parse/split/trim | Stdlib ausente | Sí para CLI/CSV práctico |
| Alta | Igualdad/concat/interpolación solo AST | Inconsistencia AST/native conocida | Sí para perfil string v1 |
| Media | `input` solo AST | Inconsistencia AST/native | Sí si se conserva como API v1 |
| Media | Sin fecha/tiempo | Feature ausente | No; string documentado basta |
| Baja | Sin combinadores de colección | Ergonomía | No |
| Baja | Sin `Map` | Feature ausente | No para este caso |
| Baja | Contrato de encoding poco explícito | Documentación/runtime | Sí antes de estabilizar strings |

## Builtin, stdlib y runtime

- **Runtime/compiler:** representación y ownership de string, layout/copia de
  structs dentro de colecciones, igualdad/concat nativas, acceso a OS y
  diagnósticos de backend.
- **Stdlib:** `trim`, `split`, parsing numérico con resultado, API de archivos,
  CSV pequeño y eventualmente `Date`. No deben convertirse todos en builtins.
- **Builtin/sintaxis existente:** operadores string y `print` pueden conservar
  su forma; necesitan lowering/runtime, no sintaxis nueva.
- **Módulo `system` o equivalente:** argumentos y código de salida, respaldados
  por el runtime. `main` puede seguir sin parámetros.

## Dependencias y próximas tareas

```text
contrato string (encoding + ownership)
├── concat/igualdad/interpolación native
├── strings dinámicos desde archivos
│   └── split/trim/parsing
│       └── CSV real
└── argv estable
    └── CLI del tracker

layout/copia de Struct en Array/List
└── tracker completo en memoria sobre native
```

Orden recomendado por impacto y dependencia:

1. Definir e implementar el contrato mínimo de string native (longitud,
   encoding, borrowed/owned y liberación), con igualdad y construcción
   dinámica básicas. Es fundamento compartido por archivos, argv y parsing.
2. Añadir un rechazo temprano específico para elementos struct en colecciones
   mientras no estén soportados; es pequeño y evita errores internos.
3. Completar layout/copia/ownership de `Array/List<Struct>` con casos POD y con
   campos de referencia claramente delimitados.
4. Crear IO textual mínimo con resultados estructurados; después `trim`,
   `split` y parsing numérico en stdlib.
5. Exponer argumentos mediante un módulo `system` y separación `--` del CLI.
6. Implementar CSV específico en stdlib o en código Aether; no JSON general.
7. Evaluar fecha/tiempo y `Map` solo con nuevos programas que los justifiquen.

La próxima tarea de feature recomendada es el contrato mínimo de string native.
Aunque archivos y argumentos son los bloqueos visibles, ambos producirán o
transportarán texto cuya vida útil hoy no tiene semántica estable. Implementar
primero APIs de IO sobre `ptr` literales consolidaría deuda y no desbloquearía
parsing seguro.
