# Operadores Elemento a Elemento

MathTeX soporta operadores tipo Octave para operaciones elemento a elemento:

- `.*` multiplicacion elemento a elemento.
- `./` division elemento a elemento.
- `.^` potencia elemento a elemento.
- `.+` y `.-` son alias de `+` y `-`.

Diferencia clave:

- `*`, `/`, `^` son operaciones matriciales (algebra lineal).
- `.*`, `./`, `.^` son operaciones elemento a elemento.

Ejemplos:

```
A = [1 2; 3 4];
B = [5 6; 7 8];

A * B   -> multiplicacion matricial
A .* B  -> producto elemento a elemento
A ^ 2   -> potencia matricial (solo exponente entero)
A .^ 2  -> potencia elemento a elemento
```

Para escalares, el punto no cambia el resultado:

```
2.*3 == 2*3
2.^3 == 2^3
```
