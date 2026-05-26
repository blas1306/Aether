# Aether IntelliJ Plugin

Primer corte del plugin Aether para IDEs IntelliJ.

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
