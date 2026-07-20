# Aether 1.0.0-rc.3 — Release notes

## Qué es RC3

Aether 1.0.0-rc.3 es una release candidate para validar el perfil Aether 1.0
antes de la versión final. No es la versión estable ni declara una ABI pública
estable. La identidad de paquete Python es `1.0.0rc3` y el tag previsto es
`v1.0.0-rc.3`.

## Cambios destacados desde RC2

- La especificación normativa v1 y el perfil native v1 cierran la frontera
  exacta del lenguaje 1.0.
- El catálogo schema 2 clasifica 78 ejemplos como `V1_NATIVE`, 23 como
  `AST_ONLY_EXPERIMENTAL` y ninguno como `BROKEN`.
- Los diagnósticos públicos son estructurados y documentan categorías, códigos
  y exit codes. Los ICE no muestran traceback por defecto; `--debug` conserva
  la información interna para investigación y `--check` valida frontend y
  capacidades native sin generar código.
- Mejoró la paridad AST/native y el backend numérico, incluidas las reglas de
  promoción, operaciones mixtas, potencia y límites checked.
- Los gates de release cubren documentación, ejemplos, diagnósticos, paridad,
  compilación native, instalación aislada y contenido de wheel/sdist.

## Backends

- **Native/LLVM** es el backend oficial del perfil Aether 1.0.
- **AST** es un intérprete auxiliar, el backend del REPL y una referencia para
  comparación diferencial dentro del perfil admitido.
- **IR interpreter** es infraestructura interna y no una API pública.

No hay fallback silencioso entre backends. La aceptación del frontend o la
ejecución AST de un experimento no amplía el perfil estable.

## Fuera de v1

Permanecen fuera del perfil 1.0 `float`, `complex`, classes, interfaces,
lambdas, closures y rangos almacenables. También permanecen fuera las APIs
avanzadas cuya estabilidad todavía no se ha definido. Algunas de estas
superficies pueden existir como experimentos AST-only.

## Instalación

Desde el directorio raíz, usando el wheel de la RC:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install dist/aether_language-1.0.0rc3-py3-none-any.whl
.venv/bin/aether --version
```

La salida de versión debe comenzar con `Aether 1.0.0-rc.3`. El backend native
requiere Linux x86_64 y `clang` disponible en `PATH`.

## Checksums y verificación

Los checksums SHA-256 del wheel, el sdist y el manifest de release están en
`dist/aether-1.0.0-rc.3-SHA256SUMS`. El archivo no se incluye a sí mismo en la
lista. Verifíquelos desde `dist/`:

```bash
cd dist
sha256sum -c aether-1.0.0-rc.3-SHA256SUMS
```

El manifest `aether-1.0.0-rc.3-manifest.json` registra nombre, tamaño y SHA-256
de cada artefacto, además de versiones, commit, plataforma y timestamp de
construcción.

## Feedback esperado

Al reportar problemas, incluya plataforma y comandos mínimos para reproducir.
Interesan especialmente reportes sobre instalación, compilación native,
paridad AST/native, diagnósticos, ejemplos públicos y detección/configuración
del toolchain.
