# Aether compiler authority

Estado: **POLÍTICA NORMATIVA VIGENTE**

Fecha: 2026-11-25

Esta es la fuente única de política sobre autoridad entre las implementaciones
del compilador de Aether. No redefine la semántica del lenguaje.

1. `compiler-next` es el único compilador oficial de Aether.
2. La CLI Rust `aether`, implementada sobre `compiler-next`, es la interfaz
   pública vigente de compilación, verificación, build y ejecución.
3. Los contratos `CLOSED` actuales tienen prioridad normativa. Ante un
   conflicto, gobierna el contrato vigente aplicable, no el comportamiento de
   una implementación histórica.
4. `compiler-rs` es una implementación histórica no normativa. Su presencia en
   el repositorio no le confiere autoridad sobre el lenguaje actual.
5. El compilador Python y su CLI `aether-legacy` son históricos y no normativos.
6. `compiler-next` no tiene obligación de compatibilidad ni paridad con
   `compiler-rs` o con el compilador Python.
7. No se pueden agregar dependencias de implementaciones legacy al pipeline,
   la CLI, el build, los tests de admisión ni los gates oficiales de
   `compiler-next`.
8. El código, los tests y los resultados históricos pueden usarse sólo como
   referencia técnica, corpus o evidencia explícitamente no normativa.
9. Los gates oficiales dependen exclusivamente de contratos y resultados de
   `compiler-next`. La ausencia, el fallo o la divergencia de una
   implementación legacy no puede cambiar su resultado.

El modo histórico opt-in descrito en `compiler-next/tests/` no es un gate de
producto. Esta política tampoco autoriza el retiro físico de `compiler-rs`, del
compilador Python ni de ninguna otra superficie histórica.
