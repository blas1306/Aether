# Aether IntelliJ Plugin

Control-flow syntax follows the rc.2 language grammar: `if (condition)`,
`while (condition)`, and `for (binding in iterable)`. Diagnostics, completion
snippets, and document formatting are supplied by the bundled Aether LSP.

Primer corte del plugin Aether para IDEs IntelliJ.

Compatibilidad declarada: lenguaje Aether `1.0.0-rc.2`. La versión del plugin
se deriva de la fuente canónica de versión del lenguaje al construir con
Gradle. El plugin es un artefacto separado y no se incluye en el wheel Python.
Esta metadata no afirma validación de Gradle/IDE para la RC si esos tests no se
ejecutaron en el entorno de release.

Incluye:

- tipo de archivo `.ae`;
- accion `New > Aether File` para crear scripts `.ae` con un template ejecutable;
- resaltado sintactico basico;
- icono de ejecucion en el gutter para archivos `.ae`;
- language server Python por stdio;
- accion `Run Aether File`;
- run configuration para ejecutar el archivo `.ae` actual desde el boton verde de IntelliJ;
- ejecucion en la consola estandar de Run de IntelliJ;
- setting `Aether > Python interpreter` para sobreescribir el Python usado.
- estructura/outline del archivo via LSP;
- hover contextual para funciones, variables, imports y builtins Aether.

Por defecto el plugin busca `.venv/bin/python` en el proyecto abierto y cae a `python3`.

Comandos utiles desde la raiz del repo:

```bash
./gradlew :tools:intellij-aether:test
./gradlew :tools:intellij-aether:runIde
```
