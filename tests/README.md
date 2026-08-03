# Suite de tests de Aether

## Proposito

La suite protege contratos reales del lenguaje Aether, el CLI, la REPL, el LSP
y las capas compartidas usadas por VS Code e IntelliJ. La prioridad no es
cobertura cosmetica: es mantener estable la superficie activa `.ae`.

## Como correrla

Suite enfocada de Aether v0:

```bash
.venv/bin/python -m pytest -q tests/aether tests/test_aether_cli.py tests/test_aether_lsp_server.py
```

Suite completa:

```bash
.venv/bin/python -m pytest -q
```

Los tests cargan `src/` automaticamente desde `tests/conftest.py`, asi que pueden correrse desde la raiz del repo sin exportar `PYTHONPATH`.

## Areas principales

- Aether v0: parser, typechecker, runtime, stdlib, matrices, algebra lineal, strings, imports rechazados y sesion persistente.
- Tooling oficial: CLI, diagnosticos, formatting, completions, simbolos y LSP.
- Integraciones: contratos compartidos que consumen VS Code e IntelliJ.

## Contratos importantes

- `.ae` es la superficie fuente activa.
- `array(...)` no es builtin publico de Aether v0; usa `Array<T>` para colecciones mutables de tamaño fijo.
- Las interpolaciones de strings `$expr$` se parsean, typecheckean y formatean como salida Aether normal.
- Los fallos de una corrida de `AetherSession` no destruyen variables o funciones ya comprometidas.
- El LSP no debe caerse por errores del analizador y debe publicar rangos diagnosticos validos dentro del documento.

## Principios para nuevos tests

- Priorizar contratos reales y regresiones de bugs por encima de cobertura cosmetica.
- Preferir tests pequenos, deterministas y con poco estado compartido.
- Agregar tests de integracion solo cuando validen limites entre modulos delicados.
- No introducir semantica duplicada en clientes: CLI, VS Code e IntelliJ deben
  reutilizar compiler, language service o LSP segun corresponda.
