# Guia de uso de Aether v0

Esta guia resume la superficie activa de Aether Studio. El producto actual esta centrado en archivos `.ae`, ejecucion de scripts y una REPL persistente. Los flujos heredados de MathTeX, MTeX, `.mtx`, `.mtex`, `.mtn`, proyectos, notebooks y PDF pueden seguir existiendo en el repositorio mientras se limpia el codigo, pero no forman parte de la aplicacion activa.

## 1. Archivos y ejecucion

Usa `.ae` para scripts Aether:

```aether
x = 2;
y = 3;
println(x + y);
```

Desde la GUI puedes abrir o crear un archivo `.ae` y ejecutar el script completo o la seleccion. Desde consola:

```bash
python3 src/main.py --cli
```

La REPL usa el prompt `aether>` y conserva variables y funciones entre comandos hasta reiniciar la sesion.

```text
aether> x = 10;
aether> println(x);
10
```

Si un comando falla, la sesion vuelve al ultimo estado valido.

## 2. Sintaxis basica

Aether usa bloques con llaves y las sentencias simples terminan con `;`.

```aether
int abs_int(int x) {
    if x < 0 {
        return -x;
    }
    return x;
}
```

Las asignaciones no imprimen automaticamente. Usa `print(...)` o `println(...)` para salida visible.

```aether
n = 4;
println(n);
```

Los comentarios de linea pueden escribirse con `#` o `//`.

## 3. Tipos y valores

Aether v0 tiene tipos primitivos `int`, `float`, `double`, `string` y `boolean`. Puedes declarar tipos de forma explicita o dejar que Aether infiera el tipo inicial:

```aether
int count = 3;
ratio = 2.5;
ok = true;
```

Una variable conserva su tipo despues de creada. Las conversiones implicitas solo ensanchan numeros de forma segura (`int -> float`, `int -> double`, `float -> double`). Para conversiones explicitas usa llamadas como `int(expr)`, `double(expr)` o `string(expr)`.

## 4. Strings

Los strings usan comillas dobles:

```aether
println("hola");
```

Puedes interpolar expresiones Aether con `$expr$`. La expresion se analiza, se typecheckea y se formatea igual que `println`.

```aether
n = 4;
println("n = $n$");
println("n^2 = $n^2$");
println("Precio: \$10");
```

`$...$` dentro de strings no es modo matematico LaTeX. Es interpolacion Aether. Las interpolaciones vacias, sin cerrar, invalidas o con variables no definidas son errores.

## 5. Matrices y algebra lineal

Los corchetes crean valores matematicos `Matrix<T>`:

```aether
row = [1 2 3];
col = [1; 2; 3];
A = [1 2; 3 4];
```

Tambien podes concatenar bloques con corchetes al estilo Julia:

```aether
B = [5 6; 7 8];
println([A B]);  // [1 2 5 6; 3 4 7 8]
println([A; B]); // [1 2; 3 4; 5 6; 7 8]
```

En concatenacion, `Vector<T>` se usa como columna y `TransposeVector<T>` como fila. Las comas siguen reservadas para vectores escalares como `[1, 2, 3]`; `[A, B]` no concatena matrices en v0.

Las matrices imprimen en formato compacto:

```aether
println([1 2; 3 4]); // [1 2; 3 4]
```

`array(...)` no es un builtin publico de Aether v0. Los arrays solo permanecen como detalle interno/transicional; para dimensiones de matrices usa `rows(A)` y `cols(A)`.

Operaciones disponibles:

```aether
println(rows(A));
println(cols(A));
println(Math.LinearAlgebra.transpose(A));
println(Math.LinearAlgebra.matmul(A, [5; 6]));
```

`*` no es multiplicacion matricial en v0; usa `Math.LinearAlgebra.matmul(A, B)`.

## 6. Builtins utiles

- Salida: `print(...)`, `println(...)`
- Dimensiones: `rows(matrix)`, `cols(matrix)`, `length(array interno)`
- Numericos: `sin`, `cos`, `tan`, `exp`, `ln`, `log`, `sqrt`, `abs`
- Modulo de piso: `Math.mod(a, b)`
- Algebra lineal: `Math.LinearAlgebra.inner`, `norm`, `transpose`, `matmul`, `solve`, `eig`

Para la especificacion completa, consulta `docs/aether/AETHER_V0_SPEC.md`.
