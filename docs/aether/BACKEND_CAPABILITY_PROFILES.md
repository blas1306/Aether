# Perfiles de capacidades de backend

Los perfiles de capacidades son la fuente programática que usa Aether para
distinguir una feature válida del lenguaje de una feature ejecutable por un
backend concreto. El catálogo, los estados y los perfiles versionados viven en
`src/aether/capabilities.py`.

El perfil **no** redefine la gramática ni el sistema de tipos, no negocia
features dinámicamente y no sustituye los verificadores de IR o SSA. El parser
y el typechecker siguen decidiendo si un programa es Aether válido. Después del
typechecking, un detector recorre el AST chequeado (nunca el texto fuente) y
produce requisitos deduplicados con ubicación. La validación del perfil ocurre
antes del lowering específico de backend.

## Modelo

Cada `BackendCapabilityProfile` tiene:

- una identidad tipada (`ast` o `native`);
- una versión de schema/perfil;
- exactamente una entrada para cada miembro del enum `Capability`;
- un estado `COMPLETE`, `PARTIAL` o `UNSUPPORTED`;
- descripción y código diagnóstico estable en el catálogo canónico.

`COMPLETE` significa que el alcance completo de esa capacidad, tal como lo
define el catálogo, tiene evidencia end-to-end para ese backend. `PARTIAL`
significa que existe un subconjunto funcional y que los casos identificables
fuera de él deben producir un diagnóstico específico. `UNSUPPORTED` significa
que un uso válido del lenguaje no entra todavía en ese backend.

El catálogo agrupa features observables por el usuario. No replica las 81 filas
de `BACKEND_FEATURE_PARITY.md`: opcodes, helpers de runtime, verificadores y
detalles de ownership permanecen en la auditoría porque son evidencia o
arquitectura, no capacidades solicitadas directamente por un programa.

## Perfiles actuales

La versión actual del perfil es `2`; el cambio desde `1` promueve
`modules` e `imports` de `UNSUPPORTED` a `PARTIAL` en LLVM/native.

El perfil AST representa el intérprete de referencia. Incluye módulos,
imports, classes, interfaces, enums, input, errores y matemática escalar. Las
funciones como valores son parciales: solo están cubiertas las funciones de
expresión y el hook de referencias usado por `Plots`; Aether aún no posee un
tipo callable general.

El perfil LLVM/native representa el recorrido completo
AST→IR→SSA→LLVM→clang. Módulos e imports están en `PARTIAL`: compilan funciones,
funciones `void`, structs, constructores, métodos y firmas cross-module mediante
imports completos/selectivos y aliases, con transitividad, privacidad y ciclos
resueltos por el frontend. Globals/constantes y statements ejecutables en un
módulo importado se rechazan temprano porque el IR aún no modela storage ni
inicialización de módulo. Callables, classes, interfaces, enums, input, errores
y matemática escalar siguen no soportados. Strings, primitivos, arithmetic,
structs y colecciones quedan parciales porque sus subconjuntos compilables son
reales pero no cubren toda la superficie AST.
Archivos y argumentos del proceso están no soportados en ambos perfiles porque
todavía no son APIs válidas del lenguaje.

La CLI no añade por ahora un comando `capabilities`: ejecución AST valida el
perfil AST, y `--emit-llvm`, ejecución LLVM, `build` y los perfiles LLVM/native
de `bench` validan el perfil native. Los modos de inspección IR/SSA conservan
sus rechazos internos porque son backends de desarrollo con límites propios,
no perfiles de ejecución publicados.

## Política de actualización

Para añadir o cambiar una capacidad:

1. actualizar el enum y su única definición canónica;
2. actualizar ambos perfiles de forma explícita;
3. ampliar el detector solo con información del AST chequeado o del estado
   semántico existente;
4. conservar una validación interna si protege invariantes de IR/SSA/LLVM;
5. añadir tests de modelo, detección, ubicación, deduplicación, CLI y backend;
6. reconciliar el cambio con `BACKEND_FEATURE_PARITY.md` y el alcance v1.

> Una capacidad no puede marcarse `COMPLETE` en un perfil sin tests
> end-to-end registrados para ese backend.

`E2E_TESTED_CAPABILITIES` y su test de consistencia hacen ejecutable esta
política. El registro no reemplaza la revisión de la auditoría: antes de marcar
`COMPLETE` deben existir casos positivos, negativos y de límites, además de
paridad observable cuando ambos backends implementen la feature.
