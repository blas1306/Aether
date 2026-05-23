# Guia de uso de MathTeX

Esta guia resume el flujo de trabajo diario del proyecto y la diferencia entre los dos tipos de archivos que maneja MathTeX.

## 1. Tipos de archivo

### `.mtx`

Se usa para scripts de calculo e importacion de funciones. Es el formato adecuado para:

- probar expresiones rapidamente
- definir funciones
- hacer algebra lineal
- generar graficos
- reutilizar codigo con `from modulo import nombre`

Ejemplo:

```text
function [x, iter, res] = Nr(f, x0, tol)
    g(x) = \diff(f, x);
    x = x0;
    iter = 0;
    res = \abs(f(x));

    while res > tol
        x = x - f(x) / g(x);
        res = \abs(f(x));
        iter = iter + 1;
    end
end
```

### `.mtex`

Se usa para documentos LaTeX con bloques ejecutables. Es el formato adecuado para:

- informes
- practicos o apuntes con calculos incrustados
- tablas y figuras generadas desde codigo
- exportar a PDF

Ejemplo:

```latex
\documentclass{article}
\usepackage{graphicx}

\begin{document}

\begin{code}
t = [-1; 0; 1; 2];
y = t.^2 + 1;
\plot(t, y, "o-", name = "curva");
\end{code}

Valores: $\var{y}$.

\plot[width=0.8\linewidth]{curva}

\end{document}
```

## 2. Como ejecutar la aplicacion

Comando normal:

```powershell
python src/main.py
```

Modos disponibles:

- `python src/main.py --cli`

Comportamiento actual:

- `python src/main.py` intenta abrir la GUI PySide6
- `python src/main.py --cli` abre la consola
- si la GUI no puede iniciarse, la aplicacion cae al modo consola

## 3. Flujo recomendado para `.mtx`

1. Abre o crea un script en el editor interactivo.
2. Ejecuta todo el archivo o solo la seleccion.
3. Observa la salida en consola y el estado del workspace.
4. Si el script define funciones, puedes importarlas desde otros `.mtx`.

Ejemplo de import:

```text
from NewtonMultiVariable import NewtonMultiVariable
```

### Capacidades comunes en scripts

- definicion de funciones: `function ... end`
- condicionales: `if`, `elif`, `else`
- bucles: `for`, `while`, `repeat`, `until`
- tuplas: `(a, b)` y `(a,)`; `(a)` solo agrupa una expresion
- vectores y matrices: `[a, b, c]` es vector 1D, `[a b; c d]` es matriz
- solucion de sistemas lineales: `x = A | b`
- derivadas simbolicas: `\diff(f, x)`
- solucion simbolica: `\solve(...)`
- minimos y maximos: `\min(...)`, `\max(...)`
- factorizaciones: `\LU(A)`, `\SVD(A)`
- Newton-Raphson: `\NR(f, x0, tol)`
- raices n-esimas: `\nthroot(x, n)`
- muestreo: `\linspace(a, b, n)`
- limpieza del workspace: `\clear x`

### Salida y separacion de sentencias

- Una sentencia puede ocupar varias lineas si hay corchetes o parentesis abiertos.
- El `;` sirve para silenciar salida cuando corresponde.
- Los comentarios con `#` y `%` son soportados.

### Literales matematicos

La sintaxis recomendada separa tuplas, vectores y matrices:

```text
t = (1, "hola", true)  # tupla inmutable y heterogenea
v = [1, 2, 3]          # vector 1D
r = [1 2 3]            # matriz fila 1x3
c = [1; 2; 3]          # matriz columna 3x1
A = [1 2; 3 4]         # matriz 2x2
```

La coma dentro de `[]` indica vector 1D. Los espacios separan columnas de una matriz y `;` separa filas. La forma anidada `[[1, 2], [3, 4]]` sigue aceptada por compatibilidad, pero para matrices nuevas se recomienda `[1 2; 3 4]`.

## 4. Flujo recomendado para `.mtex`

1. Crea un documento LaTeX normal.
2. Inserta bloques MathTeX con `\begin{code} ... \end{code}`.
3. Dentro del bloque, escribe calculos, tablas o graficos.
4. Usa placeholders en el texto para insertar resultados.
5. Compila el documento desde la app.

### Placeholders soportados

#### Variables

Inserta el valor de una variable o un elemento especifico:

```latex
$x = \var{x}$
$a_{2,1} = \var{A[2,1]}$
```

Los indices en `\var{...}` son base 1.

#### Graficos

Si un grafico se genera con nombre, luego puede insertarse en el documento:

```text
\plot(f, -1, 3, name = "mi_plot");
```

```latex
\plot[width=0.9\linewidth]{mi_plot}
```

Si no indicas opciones, MathTeX usa por defecto `width=0.6\linewidth`.

#### Tablas

Puedes construir una tabla LaTeX desde codigo:

```text
T = table(
  [[1, 2], [3, 4]],
  name = "tabla_demo",
  headers = ["A", "B"],
  caption = "Ejemplo"
);
```

Y luego insertarla con:

```latex
\table{tabla_demo}
```

## 5. Directorios de salida

Cuando trabajas con un proyecto, la salida se concentra en `build/`.

Archivos tipicos:

- `build/main.tex`
- `build/main.pdf`
- `build/compile.log`

Tambien se puede generar una metadata `.mtexproj` con el nombre del proyecto y el archivo principal.

## 6. Ejemplo completo de documento

```latex
\documentclass{article}
\usepackage{graphicx}
\title{Demo MathTeX}
\date{\today}

\begin{document}
\maketitle

\begin{code}
f(x) = x.^2 - 2;
xr = \NR(f, 1, 1e-8);
\plot(f, -1, 3, name = "nr_plot");

T = table(
  [[xr, \abs(f(xr))]],
  name = "resumen",
  headers = ["Raiz", "Residual"],
  caption = "Resultado de Newton-Raphson"
);
\end{code}

La raiz aproximada es $\var{xr}$.

\plot{nr_plot}

\section*{Resumen}
\table{resumen}

\end{document}
```

## 7. Operadores utiles

MathTeX distingue entre operaciones matriciales y elemento a elemento.

- matriciales: `*`, `/`, `^`
- elemento a elemento: `.*`, `./`, `.^`

Consulta `docs/operadores_elemento_a_elemento.md` para ejemplos concretos.

## 8. Problemas comunes

### No se genera el PDF

Revisa:

- que `pdflatex` este instalado
- que el documento LaTeX compile sin errores
- el archivo `build/compile.log`

### No aparece la vista previa

Revisa:

- que el PDF se haya generado
- que la instalacion de PySide6 incluya `QtPdf`

### Un placeholder no se reemplaza

Verifica:

- que la variable exista en el bloque ejecutado
- que el nombre del plot o de la tabla coincida exactamente
- que el indice usado en `\var{...}` empiece en 1
