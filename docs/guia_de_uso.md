# Guia de uso de Aether v0

Esta guia resume la superficie activa de Aether. El producto actual esta
centrado en archivos `.ae`, el CLI, una REPL persistente, el LSP y sus clientes
oficiales para VS Code e IntelliJ. El antiguo IDE Qt y los flujos MathTeX/MTeX
no forman parte del producto activo.

## 1. Archivos y ejecucion

Usa `.ae` para scripts Aether:

```aether
x = 2;
y = 3;
println(x + y);
```

Ejecuta un archivo desde consola con el CLI oficial:

```bash
aether programa.ae
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
    if (x < 0) {
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

## 5. Listas, matrices y algebra lineal

Las listas de programacion usan `List<T>` y literales con llaves. Son 0-based:

```aether
List<int> xs = {10, 20, 30};
println(xs[0]); // 10
```

La API basica de listas usa funciones globales por ahora:

```aether
println(length(xs));
println(is_empty(xs));
push(xs, 40);
println(pop(xs));
insert(xs, 1, 15);
println(remove_at(xs, 1));
println(contains(xs, 20));
clear(xs);
```

`insert` acepta indices `0 <= index <= length(xs)` y `remove_at` acepta `0 <= index < length(xs)`. Los vectores matematicos y `Matrix<T>` no son listas y no aceptan `push`, `pop`, `insert`, `remove_at` ni `clear`.

Los corchetes crean valores matematicos. En la semantica formal futura,
`Vector` lleva la orientacion en el tipo estatico: `Vector<T, Row>` o
`Vector<T, Column>`. Los vectores y matrices son 1-based:

```aether
row = [1, 2, 3];      // Vector<int, Row>
alsoRow = [1, 2, 3];
col = [1; 2; 3];      // Vector<int, Column>
A = [1, 2; 3, 4];     // Matrix<int>

println(row[1]);  // 1
println(A[1, 1]); // 1
```

Si hay un tipo esperado compatible, ese tipo guia la interpretacion del
literal:

```aether
Vector<int, Row> r = [1, 2, 3];
Vector<int, Column> c = [1, 2, 3];

Matrix<int> A = [1, 2, 3]; // Matrix 1x3
Matrix<int> B = [1; 2; 3]; // Matrix 3x1
```

Sin tipo esperado, la forma decide: `{...}` produce `List<T>`,
`[a, b, c]` produce `Vector<T, Row>`, `[a; b; c]` produce
`Vector<T, Column>` y `[a, b; c, d]` produce `Matrix<T>`.

Tambien podes concatenar bloques con corchetes al estilo Julia:

```aether
B = [5 6; 7 8];
println([A B]);  // [1 2 5 6; 3 4 7 8]
println([A; B]); // [1 2; 3 4; 5 6; 7 8]
```

En concatenacion, la orientacion del vector se respeta: un vector fila aporta un bloque `1xN`, y un vector columna aporta `Nx1`. Las comas siguen reservadas para vectores escalares como `[1, 2, 3]`; `[A, B]` no concatena matrices en v0.

Las matrices imprimen en formato compacto:

```aether
println([1 2; 3 4]); // [1 2; 3 4]
```

`Array<T>` esta reservado para una coleccion futura de tamaño fijo. Cuando se implemente, se inicializara con llaves si hay tipo esperado:

```aether
Array<int> xs = {1, 2, 3};
xs[0] = 9;
println(length(xs));
```

`array(...)` y `T[]` no son sintaxis publica de Aether v0. Usa `List<T>` cuando necesites cambiar la longitud con `push`, `pop`, `insert`, `remove_at` o `clear`; para dimensiones de matrices usa `rows(A)` y `cols(A)`.

Operaciones disponibles:

```aether
println(rows(A));
println(cols(A));
println(Math.LinearAlgebra.transpose(A));
println(Math.LinearAlgebra.matmul(A, [5; 6]));
```

`*` no es multiplicacion matricial en v0; usa `Math.LinearAlgebra.matmul(A, B)`.
La intencion futura para `*` distingue la orientacion estatica:
`[1, 2, 3] * [4; 5; 6]` produce un escalar, mientras que
`[1; 2; 3] * [4, 5, 6]` produce una matriz. No son equivalentes.

## 6. Builtins utiles

- Salida: `print(...)`, `println(...)`
- Dimensiones y listas: `rows(matrix)`, `cols(matrix)`, `length(list_or_vector)`, `is_empty(list)`, `push(list, value)`, `pop(list)`, `insert(list, index, value)`, `remove_at(list, index)`, `contains(list, value)`, `clear(list)`
- Numericos: `sin`, `cos`, `tan`, `exp`, `ln`, `log`, `sqrt`, `abs`
- Modulo de piso: `Math.mod(a, b)`
- Algebra lineal: `Math.LinearAlgebra.inner`, `norm`, `transpose`, `matmul`, `solve`, `eig`, `SVD`, `LU`, `LDU`, `N`, `R`, `rank`

Para la especificacion completa, consulta `docs/aether/AETHER_V0_SPEC.md`.
