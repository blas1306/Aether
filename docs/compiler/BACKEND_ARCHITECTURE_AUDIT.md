# Auditoría de arquitectura del backend

> Estado: auditoría de consolidación, 18 de julio de 2026. Este documento
> describe el repositorio inspeccionado; no congela IR, ABI ni símbolos de
> runtime y no autoriza una migración general.

## 1. Resumen ejecutivo

Aether ya tiene un pipeline reconocible y defensas poco habituales para su
etapa de desarrollo: frontend tipado, intérpretes AST e IR independientes,
verificadores IR/SSA, dominancia, optimizadores con efectos, capability gate
native, LLVM textual verificable por Clang y un corpus diferencial AST/native.
No es necesario reemplazar esa arquitectura.

La frontera conceptual más prometedora es:

```text
frontend Python
    -> TypedProgram / CheckedProgram
    -> IR verificado + lifecycle explícito
    -> SSA verificado
    -> backend native
```

Sin embargo, todavía no es una frontera portable. `IRModule`, `IRType`, las 68
clases de instrucción IR, `SSAModule` y las 61 clases de instrucción SSA son
dataclasses Python. No existe esquema, versión, parser ni serialización
canónica. El backend LLVM recibe esos objetos directamente y reconstruye
layouts, lifecycle, nombres de helpers y runtime mediante strings LLVM.

La auditoría registra **18 hallazgos: 1 P0 resuelto, 7 P1, 8 P2 y 2 P3**. Los
hallazgos principales son:

1. ~~literales `int` fuera de i32 dependían del entero arbitrario de Python y
   divergían en native~~ — **resuelto el 18 de julio de 2026** por validación
   frontend y defensas IR/SSA/LLVM;
2. el runtime se genera y enlaza dentro de cada módulo LLVM, sin artefacto ni
   ABI C separada;
3. IR/SSA no tienen contrato versionado independiente de Python;
4. layouts y lifecycle se conocen en varias capas y algunos índices/offsets
   están hardcodeados;
5. `LLVMPrinter` mezcla emisión, validación tardía, especialización, ownership
   y generación del runtime;
6. no existe target matrix, `target datalayout`/`target triple` explícito ni
   baseline automatizada de sanitizers.

Recomendación: mantener lexer, parser, typechecker, servicios de lenguaje,
diagnósticos y tooling en Python. Consolidar primero el contrato i32, el
modelo de tipos/layout, el IR exportable y el runtime. El primer candidato
nativo debe ser un **verificador IR independiente** que consuma una vista
versionada, no el LLVM backend completo. La primera pieza de producción a
separar después debe ser el runtime con una ABI C interna versionada,
implementado principalmente en Rust `extern "C"` y con C sólo donde la API del
sistema lo justifique.

## 2. Alcance y método

Se inspeccionaron `src/aether`, los runtimes textuales LLVM, los verificadores,
los optimizadores, el capability profile 22, CLI/build/run, tests, corpus
diferencial, benchmarks, scripts de CI/release y la documentación de lenguaje,
ownership, strings, colecciones, SSA y LLVM. La suite contiene 3.096 tests
recolectados en este checkout.

La evidencia se obtuvo mediante lectura estática, emisión LLVM, ejecución de
tests dirigidos y una reproducción separada del límite i32. No se modificó
sintaxis, semántica, ABI ni implementación del backend.

Escala de estabilidad usada:

- **alta**: contrato explícito, gate y tests negativos/positivos;
- **media**: invariantes verificadas, pero representación interna no congelada;
- **baja**: representación accidental, incompleta o ligada a Python/LLVM.

## 3. Arquitectura real

```text
source UTF-8
  -> lexer.py / tokens.py
  -> parser.py -> ast.py
  -> typechecker.py + symbols.py + modules.py + stdlib registry
  -> TypedProgram(program normalizado, TypeChecker, CheckedProgram)
       |-> ASTBackend -> interpreter.py -> objetos runtime Python
       |-> IRLowerer -> IRModule
              -> IRVerifier
              |-> IRInterpreter
              |-> expand_lifecycle + optimizadores IR
              -> GeneralSSABuilder -> SSAModule
                     -> SSAVerifier + dominancia
                     -> optimizadores SSA, verificación por pass
                     -> LLVMPrinter
                            -> LLVM textual + runtime textual privado
                            -> clang/linker
                            -> ejecutable + libc/libm/POSIX
```

`prepare_typed_program()` es hoy la frontera frontend. Normaliza el entry point
y conserva `TypeChecker` completo dentro de `TypedProgram`; IR lowering consume
`CheckedProgram`, pero también vuelve a consultar estructuras semánticas y AST.
`LLVMBuilder.emit_llvm()` aplica el capability gate, baja a SSA verificado,
optimiza verificando cada pass y sólo entonces emite LLVM.

### 3.1 Inventario por capa

| Capa | Archivos principales | Entrada -> salida | Invariantes y errores | Dependencias / conocimiento | Tests y estabilidad |
| --- | --- | --- | --- | --- | --- |
| Source/lexer | `lexer.py`, `tokens.py` | `str` Python -> `list[Token]` | posiciones, escapes y token EOF; `AetherSyntaxError` | Unicode/code points y conversión numérica Python | tests de lenguaje; **media-alta**, falta diagnóstico propio de UTF-8 y rango i32 |
| Parser/AST | `parser.py`, `ast.py` | tokens -> `ast.Program` | precedencia, formas de declaración/control y recuperación; syntax errors | importa tipos fuente concretos de `types.py`; AST contiene payloads Python | cobertura amplia; **alta para la gramática implementada**, AST no versionado |
| Análisis semántico | `typechecker.py`, `scope.py`, `symbols.py`, `modules.py`, `capabilities.py` | AST -> AST anotado indirectamente + tablas/`CheckedProgram` | tipos, imports, visibilidad, Eq(T), const, shapes, capability profile | filesystem, parser recursivo de módulos, stdlib, tipos runtime y detalles native de exclusión | amplia + gate negativo; **media-alta**, monolítico |
| Frontera tipada | `pipeline.py`, `modules.py`, `entry_point.py` | source -> `TypedProgram` | programa chequeado, módulos identificados, entry normalizado | mantiene referencia al `TypeChecker` y AST Python | `test_pipeline`, módulos; **media**, frontera sólo in-process |
| Intérprete AST | `interpreter.py`, `types.py`, `collection_value.py`, `string_value.py`, `stdlib/` | AST tipado -> `Environment`/observables | typecheck previo, boolean estricto, RC simulado de string/Array/List | objetos, excepciones, listas, paths, IO, floats y recursión Python | suite funcional y diferencial; **media como oráculo**, no ABI |
| Lowering IR | `ir/lowering.py`, `ir/module_lowering.py`, `ir/model.py`, `ir/types.py` | `CheckedProgram` -> `IRModule` | CFG con terminadores, tipos explícitos, storage/lifecycle, mangling estable | AST y tipos fuente Python; conoce builtins, módulos, ownership y shapes | lowering/verifier/lifecycle; **media** |
| Verificador IR | `ir/verifier.py`, `ir/lifecycle.py`, `instruction_effects.py`, `ir/equality.py` | `IRModule` -> mismo módulo aceptado | definiciones, tipos, CFG, terminadores, lifecycle y cleanup | duplica reglas de opcodes/builtins con lowering y SSA | tests negativos extensos; **alta como implementación, baja como formato estable** |
| Intérprete IR | `ir/interpreter.py` | IR verificado -> valores/observables Python | dispatch tipado, bounds/panic, calls y lifecycle expandido | reutiliza helpers Python y representa agregados con listas/tuplas/objetos host | paridad AST/IR; **media**, oráculo útil independiente |
| SSA | `ssa/model.py`, `general_builder.py`, `renaming.py`, `phi_placement.py` | IR verificado -> `SSAModule` | definiciones únicas, phi por predecesor, entry explícito | reutiliza `IRType`; replica casi todo el modelo de instrucciones | stress, comparación de builders; **media** |
| Verificador SSA | `ssa/verifier.py`, `analysis/*` | SSA -> mismo módulo aceptado | tipos, CFG, dominancia, usos dominados, phi completos | repite reglas de cada operación/builtin del IR verifier | tests negativos/dominancia; **alta como implementación** |
| Optimización | `ir/optimizer/*`, `ssa/optimizer/*` | IR/SSA -> IR/SSA | preservación según `InstructionEffects`; SSA puede verificar por pass | dos familias de passes y folds parcialmente duplicados | tests por pass/SCCP; **media-alta** |
| LLVM | `backend/llvm/printer.py`, `types.py`, `layout.py` | SSA verificado -> `str` LLVM | capability gate previo; varios chequeos tardíos; LLVM debe ser aceptado por Clang | conoce layouts, ABI, lifecycle, builtins, libc, runtime, símbolos y strings LLVM | integración/goldens parciales; **media funcional, baja como frontera** |
| Runtime native | `*_runtime.py`, `runtime.py`, partes de `printer.py` | flags/tipos Python -> definiciones LLVM privadas | allocation checked, panic, ARC, UTF-8, colecciones, IO/POSIX | LLVM textual, libc/libm y Linux/POSIX para files | E2E, corpus diferencial y RC tests; **media semántica, baja ABI** |
| Build/run | `build.py`, `run.py`, `cli.py` | LLVM textual -> clang -> proceso | entry `int main()`, clang disponible, límites de plataforma | subprocess, archivos temporales, PATH, plataforma host | CLI/integración; **media** |

### 3.2 Dependencias directas e inversas relevantes

| Productor | Consumidores directos | Dependencia inversa problemática |
| --- | --- | --- |
| `types.py` | parser, checker, AST interpreter, modules, stdlib | contiene tipos fuente y también valores/runtime/coerciones; cambios semánticos afectan tooling y ejecución |
| `CheckedProgram` | module lowering / IR lowering | contiene AST y `TypeChecker`; no puede consumirse fuera de Python |
| `IRType` | IR, SSA, optimizadores, LLVM layout/printer | LLVM y SSA dependen directamente de clases Python concretas |
| `IRInstruction` | verifier, interpreter, builders, printers, passes | agregar opcode exige editar varios switches independientes |
| `InstructionEffects` | IR y SSA optimizers | `IRCall.effects` y `SSACall.effects` replican dispatch de builtins |
| `LLVMTypeLayouts` | printer y helpers generados | runtimes aún usan índices de fields y strings de layout propios |
| capability profile | CLI, builder, documentación generada | conoce combinaciones de tipos/backend y compensa ausencia de una representación de support declarativa común |

## 4. Responsabilidades mezcladas

| Evidencia | Mezcla | Severidad | Frontera propuesta | Costo | ¿Bloquea? |
| --- | --- | --- | --- | --- | --- |
| `typechecker.py` (4.467 líneas), `_load_module`, `_expression_type`, `_can_assign`, `_validate_struct_layouts` | tipos, import resolver, diagnósticos, layout semántico, capability inputs | P2 | `SemanticContext`, `TypeRelations`, `ModuleResolver`, diagnósticos puros | alto | no al runtime; sí a migrar frontend |
| `interpreter.py` (3.428 líneas) | semántica, módulos, IO, builtins, ownership y representación host | P2 | visitor ejecutivo + `RuntimeServices` + value operations | alto | no; debe seguir como oráculo |
| `ir/lowering.py` (3.439 líneas) | lowering, CFG/cleanup, resolución de builtins, coerciones y shapes | P2 | builder tipado de IR, tabla declarativa de builtin signatures/effects, cleanup planner | medio-alto | parcialmente |
| `IRCall.effects` y `SSACall.effects` | modelo y semántica de efectos duplicada | P1 | registro único `BuiltinContract` compartido/generado | medio | sí para una frontera Rust fiable |
| `ir/verifier.py` / `ssa/verifier.py` | verificación estructural y reglas semánticas por opcode | P1 | esquema de opcodes con operandos/resultados/efectos generado; verificadores independientes conservan CFG/lifecycle/dominancia | medio-alto | sí |
| `LLVMPrinter.print_module()` y clase `LLVMPrinter` (4.116 líneas) | emisión, validación, layouts, helper discovery, ARC, impresión, mangling y runtime | P1 | `LLVMModuleEmitter` + typed builder + `RuntimeRequirements` + llamadas ABI | alto e incremental | sí para migrar LLVM |
| `backend/llvm/*_runtime.py` | contratos runtime y cuerpos LLVM textuales | P1 | cabecera ABI/versionada + runtime compilable separado | alto | sí para runtime Rust/C |
| `layout.py`, `types.py`, runtime GEPs y `printer.py` | representación, size y field offsets | P1 | descriptor de layout canónico; compiler sólo usa handles/opacidades salvo structs by-value | medio-alto | sí |
| `build.py` | pipeline semántico, plataforma y toolchain | P2 | `CompilationPlan`/`Toolchain` inyectables | medio | no |

## 5. Duplicación semántica

La independencia AST/IR/native es valiosa como detector de divergencias. No se
debe reemplazar por una sola implementación ejecutiva. Sí conviene compartir
contratos, constantes, tablas de tipos/efectos y tests diferenciales.

| Regla | AST | IR | SSA | LLVM | Runtime | Fuente canónica actual | Riesgo / decisión |
| --- | --- | --- | --- | --- | --- | --- | --- |
| int i32 y overflow | `integer_arithmetic.py` | mismo helper | efecto `may_trap` | intrinsics/helpers i32 | `integer_runtime.py` textual | spec + helper Python | **alto/cerrado para literales**: límites compartidos, diagnóstico frontend y test diferencial |
| división/módulo cero | helper/interpreter | helper/interpreter | preserva efecto | checks explícitos | helpers integer/math | spec/tests | mantener implementaciones independientes + corpus |
| rango inclusivo/paso cero | `AetherRange` | lowering/interpreter | CFG | helper guard | panic textual | `range_safety.py` + spec | duplicación aceptable; generar contrato del builtin |
| igualdad | `equality.py` | `ir/equality.py` | verifier | helpers por tipo | string/aggregate helpers | Eq(T) de spec + typechecker | compartir capability/layout; ejecutar diferencial |
| strings | `StringValue` | objetos Python | handle nominal | `ptr` | `%AetherStringObject` + ARC | spec/string design | layout sólo runtime; no exponer header al IR |
| Array/List | `CollectionObject` | host objects | opcodes | handles `ptr` | headers/ARC/helpers | collection RFC | conservar dos runtimes temporales; ABI explícita |
| Vector/Matrix | listas/shapes Python | listas planas + metadata | metadata parcial | `%AetherArray`-like ptr | helpers de índice/print | diseños + lowering | riesgo alto por shape/layout implícito |
| structs | `StructInstance` + `field_order` | tuplas + definitions | definitions como `object` | by-value `%struct.*` | helpers generados | declaración fuente/IR definition | centralizar layout y nominal IDs |
| classes/interfaces | objetos Python | tipos nominales parciales | nominal parcial | no soportado | ninguno | frontend/spec | mantener Python; diseñar antes de migrar |
| enums | `EnumIdentity/Value` | `IREnumConstant` | mismo constant Python | `i32` | selección de texto generada | orden de declaración | metadata Python cruza hasta LLVM; serializar IDs/discriminante |
| conversions | `types.py`/interpreter | lowering/interpreter | verifier | casts LLVM | math helpers | typechecker | tabla de conversiones declarativa; tests de edge cases |
| calls/callables | objetos `Function` | `IRCall/Indirect` | SSA | default LLVM CC, `ptr` | sin closure runtime | firmas checker/IR | ABI callable provisional |
| ownership | `copy_value`, Collection/String RC | lifecycle opcodes/registry | lifecycle expandido | `_emit_arc_value` | ARC textual | lifecycle design + IR | contrato fuerte, representación todavía dispersa |
| cleanup | scopes interpreter | lowering + verifier | ya expandido | calls release | exit sin unwind | IR lifecycle | mantener en IR; definir panic/no-unwind explícito |
| printing | `formatting.py` | IR interpreter | `SSAPrint` | printer dispatch | IO/string/aggregate helpers | spec de formato | diferencial; no compartir implementación ejecutiva |
| panic/exit | excepciones Aether | `IRExecutionError` | efecto | `puts`/`exit` | varios helpers | spec observable | normalizar catálogo/stream/code; ABI interna separada |
| parsing texto | `string_parsing.py` | llama helper Python | call tipada | call runtime | parser LLVM + libc locale | gramática byte-level | compartir fixtures/generadores, no algoritmo único |
| file IO | `text_file_io.py` | helper Python | call tipada | call runtime | POSIX textual | spec + status enums | separar provider de plataforma; diferencial de archivos |

## 6. Dependencias accidentales de Python

| Dependencia | Dónde | Tooling o semántica | Riesgo | Desacoplamiento / caracterización |
| --- | --- | --- | --- | --- |
| enteros arbitrarios | `lexer._number()` conserva magnitud con `int(text)` hasta análisis semántico | semántica | **P0 resuelto**: frontend rechaza fuera de rango; `-2147483648` usa regla estructural; IR/SSA/LLVM tienen defensas | mantener corpus de bordes AST/IR/native; el entero Python no define semántica |
| floats/conversión Python | lexer, `types._coerce_python_value`, IR interpreter | semántica | diferencias de parsing/format/narrowing | mantener gramática byte-level y fixtures C/Python; contrato IEEE explícito |
| `str`/Unicode Python | source, lexer/parser, interpolación; `StringValue` mitiga runtime | ambas | code points y errores host pueden filtrarse | boundary UTF-8 bytes; diagnóstico de decode; strings runtime siempre `StringValue` |
| `list` mutable | AST y parte del IR interpreter; `CollectionObject` hereda `list` | semántica/oráculo | métodos/slices/índices negativos host podrían filtrarse | todas las operaciones públicas pasan por helpers checked; property tests contra contrato |
| identidad `id()` | enum declarations importadas en `interpreter.py`; ciclos defensivos de igualdad/snapshot | semántica interna | identidad de declaración no portable | usar sólo `EnumIdentity`/`SymbolId` nominal a partir del checked program |
| orden de dict | tablas de módulos, fields y helper discovery | determinismo | mitigado con `field_order`, dependency sort y `sorted()` en emission | test cross-`PYTHONHASHSEED`; no usar insertion order como ABI |
| hashing Python | sets/dicts de tipos/helpers | determinismo | bajo hoy por sorting; hash no estable entre procesos | serialización ordenada y golden por hash seeds |
| excepciones Python | checker/interpreters/build wrappers | diagnostics/control | jerarquía host es parte accidental del flujo | resultado tipado `Expected/Error` en fronteras exportables; adaptador Python conserva API |
| `None` | void, nullable, ausencia interna | semántica | tres significados se solapan | tags explícitos en esquema IR; no serializar `None` ambiguo |
| truthiness | short-circuit usa payload tras comprobar `boolean`; `StringValue.__bool__` existe | semántica | bajo actualmente; riesgo futuro | verifier/runtime APIs requieren bool nominal, nunca `bool(value)` genérico |
| recursion/stack Python | parser, checker, interpreter, type/layout walkers | tooling y semántica de ejecución | programas profundos fallan por host | tests de profundidad y límites documentados; walkers iterativos donde importe |
| filesystem/paths | module resolver, CLI, files AST | ambas | cwd, case sensitivity, symlinks y Windows | IDs de módulo path-independent ya existen; provider FS y matriz de plataforma |
| formatting float | `format(..., ".15g")` vs `snprintf` C locale | semántica observable | cubierto parcialmente por differential | mantener locale controlado y fixtures NaN/Inf/-0/subnormales |

Ningún objeto Python debe cruzar la futura frontera. Hoy sí cruzan:
`TypedProgram`, AST, `TypeChecker`, dataclasses `IRType`/`IRInstruction`, valores
de constantes (`str`, `int`, `float`, `IREnumConstant`), `IRStructDefinition` y
todo `SSAModule`.

## 7. Modelo de tipos y transformaciones

No existe una clase `SourceType` separada: el parser instancia directamente
los tipos de `aether/types.py`, que también contiene `AetherValue`, coerciones y
representaciones del intérprete. SSA reutiliza `IRType`; LLVM reconstruye su
tipo con `llvm_type()` y su storage con `LLVMTypeLayouts`.

| Source/Semantic | IR | LLVM | Runtime/layout | Estado |
| --- | --- | --- | --- | --- |
| `int` | `IntType` | `i32` | valor signed checked | total; literal fuera de rango rechazado antes de IR |
| `boolean` | `BoolType` | `i1` | valor | total |
| `double` | `DoubleType` | `double` | IEEE binary64 | total en subset |
| `float` | `FloatType` | `float` en mapper | profile lo rechaza por ABI no estable | parcial/contradictorio deliberadamente gated |
| `complex` | `ComplexType` | no soportado | Python `complex` AST | AST/IR-only |
| `string` | `StringType` | `ptr` | `%AetherStringObject {length,strong,flags,reserved,data}` | total en subset; header privado |
| `Array<T>` | `ArrayType(T)` | `ptr` | `{i64 length, ptr data, i64 strong}` | total para T layout-compatible |
| `List<T>` | `ListType(T)` | `ptr` | `{i64 length,i64 capacity,ptr data,i64 strong}` | total para T layout-compatible |
| `Vector<T>` | `VectorType(T,orientation)` | `ptr` | reutiliza layout tipo Array; length runtime, shape parcial | parcial |
| `Matrix<T>` | `MatrixType(T)` | `ptr` | buffer plano; rows/cols suelen viajar en instrucciones | parcial, layout implícito |
| struct | `StructType(name)` + `IRStructDefinition` | `%struct.name` by-value | layout/padding de target LLVM | total para campos representables/acíclicos |
| class | `ClassRefType` existe pero lowering fuente no lo completa | no mapper | objeto Python | AST-only |
| interface | `InterfaceType` parcial | no mapper | objeto Python | AST-only |
| enum | `EnumType` + `IREnumConstant` | `i32` | discriminante por orden | total sin payload, ABI interna |
| callable top-level | `FunctionType` | `ptr` | function pointer sin captures | parcial; signature sólo en IR |
| tuple | `TupleType` fuente | no lowering general | ninguno | AST-only; method result usa agregado interno distinto |
| nullable | `NullableType` IR nominal | sin LLVM layout | `None` AST | AST-only |
| range | `RangeType` fuente | se desazucara a control/ints | sin objeto native | lowering parcial por construcción |
| resultados parse/file | enums/structs nominales sintetizados | structs by-value | `{value,status}` | ABI interna implícita |
| method result | no source type | `MethodResultType` | `{receiver[,value]}` | ABI interna provisional |

Hardcodes relevantes: `i32` para int/enum, offsets 8/16/24 del string,
`HEADER_SIZE = 24`, field indices Array/List en varios generadores, strong count
i64 máximo `2^63-1`, flags string y firmas POSIX/libc. Los structs delegan
padding/alineación al DataLayout de LLVM mediante tipos nominales y
`getelementptr`; eso es correcto, pero el target no se fija ni registra.

## 8. IR y SSA como frontera de migración

### Dictamen

**No es posible hoy producir IR en Python y consumirlo en Rust sin importar o
traducir objetos Python.** El modelo es suficientemente expresivo para ser la
base, pero no suficientemente estable para ser el protocolo.

Fortalezas: tipos nominales, CFG explícito, terminadores, storage separado de
values, lifecycle verificable, efectos, source location parcial, definiciones
de structs, símbolos mangleados path-independent y verifiers obligatorios en
el pipeline native.

Faltantes mínimos: versión de esquema; IDs numéricos/strings estables de
opcodes y builtins; tipos cerrados; módulo/símbolo/layout metadata; ubicación
fuente completa con file table; ownership de operandos/resultados; orden
canónico; política de extensiones; reader/writer; fixtures golden y rechazo de
versiones/campos desconocidos. No hace falta diseñar todavía bytecode binario.

| Alternativa | Performance | Debug/versionado | Complejidad | Recomendación |
| --- | --- | --- | --- | --- |
| bindings directos | alta | ABI del binding frágil | media | no como contrato; útil sólo prototipo |
| JSON versionado | suficiente para compilación inicial | excelente, diffable | baja | **primera frontera recomendada** |
| textual propio + parser | buena ergonomía humana | excelente si se especifica | media-alta | posible después de estabilizar el printer actual |
| binario | alta | peor inspección/evolución | alta | no justificado |
| C ABI builders | alta/in-process | ABI estable posible | alta y verbosa para 68 opcodes | fase posterior, no formato primario |
| PyO3 | alta/in-process | acopla lifetime/GIL/Python ABI | media | adaptador opcional, no frontera canónica |

SSA no debe ser la primera frontera serializada. Es más voluminosa, replica el
modelo IR y su correcto significado depende de invariantes de dominancia. Un
backend Rust puede comenzar consumiendo IR verificado y construir/verificar su
propia SSA, comparándola con la Python.

## 9. LLVM y runtime

El backend imprime LLVM textual. No usa bindings ni LLVM C API. No emite debug
metadata, `target triple` ni `target datalayout`. La verificación real se
produce al invocar Clang; `--emit-llvm` no llama un verifier LLVM separado.
Los nombres son deterministas por construcción en los casos inspeccionados,
pero no había gate cross-process/cross-hash-seed.

Todo el runtime es LLVM textual generado bajo demanda:

- common: allocation checked, panic, memcpy/memmove y sort;
- integer/scalar math: overflow, div/rem, floor-mod y conversions;
- string: descriptor UTF-8, ARC, concat, trim, split, parse, codec y print;
- Array/List: headers, allocation, slicing, bounds, growth, search y RC;
- Vector/Matrix: index, equality y print;
- process arguments y entry wrapper;
- text files POSIX/Linux, status/errno y atomic write;
- IO/formatting mediante libc/libm.

Todos los helpers Aether se emiten `private`; por tanto hoy no existe un
conjunto de símbolos runtime exportados. El único símbolo de proceso público
del artefacto es `main` y las funciones fuente no privadas del módulo LLVM
pueden quedar con external linkage accidental. Esto es ABI de objeto interno,
no FFI.

### Caminos futuros

| Camino | Evaluación para Aether |
| --- | --- |
| LLVM textual Python | mantener durante consolidación; es debuggable y ya probado, pero no seguir ampliando el runtime inline |
| LLVM en Rust con bindings | candidato sólo tras esquema IR/layout/runtime estable; beneficio probable en builders tipados y mantenimiento, no asumido en performance |
| C intermedio | útil como backend diagnóstico/portabilidad, pero pierde control preciso de overflow, layout y ownership y agrega otro compilador semántico; no recomendado como backend principal |
| LLVM C API | ABI más estable que C++ API, pero demasiado bajo nivel; usar desde Rust vía bindings si se elige LLVM |
| Cranelift | interesante para JIT/compilación rápida futura; no cubre por sí solo packaging/runtime/ABI y sería otro backend que mantener |

## 10. Requisitos previos a migrar

| Requisito | Estado | Prioridad | Evidencia / cierre necesario |
| --- | --- | --- | --- |
| verifier IR obligatorio | cumplido en pipeline | bloqueante cumplido | `IRBackend.lower_verified`; evitar rutas como `_emit_cfg` que usan lower sin verify para ejecución |
| verifier SSA obligatorio | cumplido en native | bloqueante cumplido | `SSAPipeline` y optimizer native con `verify_after_each=True` |
| capability gate sound | fuerte/parcial | bloqueante | profile 22 + diferencial; agregar matriz capability->test generada |
| ABI documentada | parcial con el documento hermano | bloqueante | no congelar; versionar runtime cuando se separe |
| runtime desacoplado | no cumplido | bloqueante | artefacto separado + calls ABI |
| layouts centralizados | parcial | bloqueante | eliminar offsets/índices fuera del descriptor |
| golden tests | parciales | recomendable | layouts/mangling sí; IR/LLVM completos deliberadamente pocos |
| differential tests | cumplido para corpus 12 | bloqueante cumplido/parcial | ampliar límites, ownership y medium/dogfoods |
| sanitizers | no cumplido | bloqueante runtime | ASan/UBSan/LSan CI y corpus native |
| benchmarks | parcial | recomendable | faltan memoria, startup, wheel/exe y fases separadas parse/typecheck/clang |
| corpus | parcial | recomendable | parity + examples + dogfoods; manifest versionado pendiente |
| determinismo | parcial | bloqueante para cache/object format | gate por hash seed, paths y runs |
| diagnostics estables | parcial | recomendable | IDs capability existen; errores internos siguen strings/excepciones |
| ownership verificable | parcial fuerte en string/Array/List | bloqueante | falta Vector/Matrix/classes/panic-unwind y sanitizer |
| cero objetos Python en frontera | no cumplido | bloqueante | esquema IR versionado |
| versión IR/API | no cumplido | bloqueante | `aether-ir` schema v0 experimental |

## 11. Catálogo de hallazgos

Cada fila contiene la clasificación pedida; las rutas/funciones son evidencia
reproducible y no una promesa de número de línea estable.

| ID | Componente | Sev. | Tipo | Descripción | Evidencia | Riesgo | Bloquea migración | Recomendación | Fase |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| BA-001 | lexer/tipos/native | **P0 CERRADO** | Python coupling / semántica | literal int fuera de signed i32 se rechaza semánticamente; sólo la magnitud `2147483648` bajo `-` produce `INT_MIN` | spans en `ast.Literal`; typechecker; defensas AST/lowering/IR/SSA/LLVM; corpus focalizado | sin divergencia conocida; IR inválido falla cerrado | no | mantener límites y corpus AST/IR/native | cerrado en fase 0 |
| BA-002 | runtime native | **P1** | runtime / ABI | runtime LLVM textual se inserta en cada módulo y todos sus helpers son privados | `LLVMPrinter.print_module`, `*_runtime.py` | no se puede sustituir/ensanchar/versionar independientemente | sí, runtime | manifest ABI + runtime artefacto separado | 0-1 |
| BA-003 | IR/SSA | **P1** | arquitectura | frontera son dataclasses Python sin schema/version/parser | `ir/model.py`, `ssa/model.py`, `CheckedProgram` | Rust requeriría importar Python o reimplementar ad hoc | sí | JSON canónico experimental + golden/reader | 0-2 |
| BA-004 | tipos/layout | **P1** | ABI | layout se reconstruye y fields/offsets se hardcodean en printer/runtimes | `layout.py`, `types.py`, Array/List/String runtime, `_emit_arc_value` | drift, corrupción al cambiar headers | sí | descriptor único generado y tests de layout | 0 |
| BA-005 | LLVM printer | **P1** | arquitectura | 4.116 líneas mezclan emission, validación, runtime, ARC y especialización | `backend/llvm/printer.py` | alto costo y riesgo al migrar/extender | sí, LLVM | extraer requirements/calls ABI/builders en pasos mecánicos | 0-3 |
| BA-006 | plataforma ABI | **P1** | ABI / tooling | sin triple/datalayout ni target matrix; IO usa firmas/errno POSIX/Linux | `build.py`, `text_file_runtime.py`; profile rechaza plataformas | objetos no portables, layout accidental | sí, ABI/objetos | target descriptor y providers por plataforma | 0-1 |
| BA-007 | ownership | **P1** | ownership / testing | lifecycle fuerte para string/Array/List, pero sin sanitizer gate, unwind ni modelo native de todas las referencias | lifecycle registry, ARC textual, release readiness | leak/UAF/double-free no detectado sistemáticamente | sí, runtime | ASan/UBSan/LSan + property lifecycle; panic no-unwind explícito | 0-2 |
| BA-008 | opcodes/builtins | **P1** | semántica | reglas de instrucciones, effects y builtins se replican IR/SSA/verifiers/printer | `IRCall.effects`, `SSACall.effects`, ambos verifiers | drift silencioso entre capas/lenguajes | sí, IR Rust | schema declarativo generado; conservar verificadores independientes | 0-2 |
| BA-009 | typechecker | **P2** | arquitectura | checker combina imports, tipos, layout checks, diagnostics y metadata backend | `typechecker.py` | mantenimiento lento; frontend difícil de aislar | no | extraer servicios sólo si una métrica lo justifica | 0/5 |
| BA-010 | AST interpreter | **P2** | arquitectura | ejecución, módulos, IO, stdlib, objects y ownership en una clase | `interpreter.py` | oráculo difícil de razonar y fuzzear | no | runtime services inyectables; conservar intérprete | 0/5 |
| BA-011 | identidad host | **P2** | Python coupling | enum mapping usa `id(declaration)`; snapshots/cycle guards usan identidad Python | `interpreter.py`, `collection_value.py`, equality | identidad no serializable y comportamiento host | sí para frontera, no native actual | usar `SymbolId`/`EnumIdentity`; limitar `id` a tooling snapshot | 0 |
| BA-012 | source locations | **P2** | diagnostics | location sólo existe en algunos opcodes, sin path, se pierde en muchos SSA ops y LLVM no emite debug info | `_source_location`, modelos IR/SSA, printer | diagnósticos peores tras migración | no, pero criterio de calidad | file table + span en toda instrucción que trapa/call | 0-3 |
| BA-013 | conversiones/tipos | **P2** | semántica | source, semantic y runtime comparten `types.py`; LLVM mapper acepta tipos que profile rechaza | `types.py`, `_lower_type`, `llvm_type`, capabilities | correspondencias parciales y cambios no locales | parcialmente | capas `SourceType/SemanticType/IRType/Layout` explícitas | 0-2 |
| BA-014 | benchmarks | **P2** | performance | benchmark mezcla parse+typecheck y native build completo; no mide memoria/artefactos/startup | `benchmark.py` | no se puede probar beneficio de Rust | no | harness JSON con fases y RSS/tamaños | 0 |
| BA-015 | diagnostics | **P2** | tooling | excepciones y strings son protocolo interno entre capas | pipeline/build/verifiers | API Rust puede cambiar mensajes/categorías | no | diagnostic ID + span + payload; renderer Python | 0-2 |
| BA-016 | build/packaging | **P2** | packaging | clang, LLVM y runtime no son artefactos versionados separados | `build.py`, `pyproject.toml`, release checks | wheel/startup/distribución difíciles de comparar | no | inventario de artefactos y runtime library versionada | 0-1 |
| BA-017 | SSA legacy | **P3** | arquitectura | builder pattern convive con General default | `pipeline.SSAPipeline`, `ssa/builder.py` | doble mantenimiento | no | mantener sólo como oráculo hasta retirar con evidencia | 4 |
| BA-018 | C++ | **P3** | tooling | no hay necesidad concreta que justifique C++ | todo el backend usa Python/LLVM textual | complejidad innecesaria si se introduce | no | Rust principal, C ABI, C mínimo, sin C++ | todas |

## 12. Riesgos y bloqueantes ordenados

1. **BA-001 está cerrado antes de medir o serializar IR.** Ninguna constante
   source fuera de signed i32 alcanza IR y las fronteras internas fallan
   cerrado ante módulos construidos manualmente.
2. Definir qué parte del runtime ABI se exportará sin declarar estable el
   header interno de string/colecciones.
3. Crear un descriptor canónico de tipos/layout/lifecycle antes de duplicarlo
   en Rust.
4. Versionar una vista IR mínima y mantener el IR Python actual detrás de un
   adaptador.
5. Establecer sanitizer y determinism gates antes del dual runtime.
6. Sólo después evaluar la migración del emisor LLVM.

## 13. Conclusión

El IR tiene **estabilidad semántica media** y **estabilidad de intercambio
baja**. SSA tiene un verifier fuerte, pero no debe congelarse antes del IR. La
ABI tiene **estabilidad pública nula**, **runtime baja** e **interna media para
el subset probado**. Estos estados no desmerecen el backend actual: indican
exactamente qué contratos faltan para poder sustituir piezas sin reescritura.

La consolidación recomendada preserva Python donde aporta velocidad de
iteración, mantiene AST e IR interpreters como oráculos, usa Rust para nuevos
componentes nativos con ownership explícito, expone una C ABI estrecha y evita
C++ salvo una dependencia futura que lo exija.
