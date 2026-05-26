# Suite de tests de Aether Studio

## Proposito

La suite protege contratos reales del lenguaje Aether v0, la REPL, el LSP basico y la superficie activa del editor. La prioridad no es cobertura cosmetica: es mantener estable la superficie activa `.ae` mientras el codigo legacy queda aislado.

## Como correrla

Suite enfocada de Aether v0:

```bash
.venv/bin/python -m pytest -q tests/aether tests/test_aether_lsp_server.py tests/test_repl_controller.py
```

Suite completa:

```bash
.venv/bin/python -m pytest -q
```

Los tests cargan `src/` automaticamente desde `tests/conftest.py`, asi que pueden correrse desde la raiz del repo sin exportar `PYTHONPATH`.

## Areas principales

- Aether v0: parser, typechecker, runtime, stdlib, matrices, algebra lineal, strings, imports rechazados y sesion persistente.
- Editor/LSP: diagnosticos, completions, REPL controller, resaltado y acciones no visuales.
- Legacy aislado: las pruebas del runtime historico, documentos antiguos, proyectos, notebooks y PDF viven fuera de la suite activa.

## Contratos importantes

- `.ae` es la superficie activa; `.mtx`, `.mtex`, `.mtn`, notebooks y PDF son rutas heredadas fuera del producto activo.
- `array(...)` no es builtin publico de Aether v0; los arrays solo quedan como detalle interno/transicional.
- Las interpolaciones de strings `$expr$` se parsean, typecheckean y formatean como salida Aether normal.
- Los fallos de una corrida de `AetherSession` no destruyen variables o funciones ya comprometidas.
- El LSP no debe caerse por errores del analizador y debe publicar rangos diagnosticos validos dentro del documento.

## Principios para nuevos tests

- Priorizar contratos reales y regresiones de bugs por encima de cobertura cosmetica.
- Preferir tests pequenos, deterministas y con poco estado compartido.
- Agregar tests de integracion solo cuando validen limites entre modulos delicados.
- Mantener separados los tests de Aether v0 activo y los tests de compatibilidad legacy.
