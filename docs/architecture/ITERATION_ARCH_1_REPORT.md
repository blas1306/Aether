# ITERATION-ARCH-1 — informe de diseño

Estado: **ARQUITECTURA CERRADA; SIN IMPLEMENTACIÓN**, 2026-09-14.

Documento normativo: [ITERATION_ARCH_1.md](ITERATION_ARCH_1.md).

## Resultado

Se diseñó la primera semántica de `for (binding in iterable)` para
`Range<T>`, `Array<T>` y `List<T>`, sin agregar parser, HIR, MIR, SSA, backend,
runtime ni una abstracción general `Iterator<T>`.

Los ranges son inclusivos y se escriben `start:end` o `start:step:end`. El step
default es siempre `+1`; un descendente necesita step negativo explícito. Una
dirección incompatible (`0:-1:10`, `10:1:0` o `10:0`) produce un range vacío.
Step cero es diagnosticable si es constante y trap si es dinámico. Todos los
operands son expresiones evaluadas exactamente una vez, izquierda→derecha.

Se admiten por diseño enteros signed/unsigned, `isize`/`usize`, `float32` y
`float64`, bajo contextual typing y widening ordinarios. No hay coerciones por
item ni reglas numéricas exclusivas de range. Descenso unsigned no se modela
con un step signed especial: requiere escoger un T signed.

## Float

Range float exige start, step y end finitos y step distinto de ambos ceros.
NaN/Inf de entrada y zero step fallan antes de iterar. El candidato cero es
start; cada candidato posterior se calcula estrictamente como
`start + convert_T(k) * step`, con rounding en T, multiplicación y suma
separadas, sin FMA, epsilon, snapping, acumulación recurrente ni fast math.

La comparación inclusiva es `<= end` ascendiendo y `>= end` descendiendo. End
aparece sólo si algún candidato coincide realmente. Un candidato dentro del
límite debe progresar estrictamente o produce `FloatRangeNoProgress`. Infinity
generado en la dirección de avance agota el range; NaN generado hace trap. El
contador tampoco puede wrappear. Estas reglas garantizan terminación sin
depender de locale o runtime.

## Representación y colecciones

`Range<T>` queda como tipo compiler-known del lenguaje, inline y conceptualmente
`{start, step, end}`. Para los T cerrados es Copy/Relocatable/Storable, no
necesita drop ni allocation y puede almacenarse en un local. No pertenece a
`std`; su API pública más allá del literal queda abierta.

Array/List se recorren por índice cero-based ascendente. El iterable y su length
se observan una vez; cada elemento se obtiene al llegar a su vuelta. List queda
bajo préstamo estructural durante el loop, por lo que push/reserve/pop/remove/
swap_remove, moves, replacement y calls potencialmente estructurales se
rechazan estáticamente. No hay version counter ni concurrent-modification
exception.

Un elemento Copy produce binding T por valor. Un elemento no-Copy produce
binding `ref T` read-only. La inferencia conserva ese tipo visible y una
anotación owning como `string x` se rechaza; `ref string x` es la forma exacta.
No hay moves destructivos, Alias, retain/release ni deep copy por item. El
préstamo impide reemplazar un slot posiblemente coincidente y termina al salir
del body de esa vuelta. Iteración no amplía la legalidad del elemento:
`List<ClassHandle>` seguirá esperando su milestone de storage OOP, pero al ser
admitido heredará esta misma semántica borrowed.

## Scope, control flow e IR

El binding tiene LocalId e instancia semántica nuevos por vuelta, scope sólo en
el body y shadowing sujeto a las reglas lexicales existentes. Esta decisión
fija futuras capturas por vuelta aunque el backend pueda reutilizar storage
cuando sea inobservable.

`continue` limpia el body y avanza una vez; `break` limpia y sale sin avanzar;
`return` y unwind limpian scopes y temporales owning en orden. `finally`
preserva su continuation pendiente. Los traps siguen siendo fail-fast sin
cleanup garantizado.

HIR conserva iterable/item/binding TypeIds, categoría Copy/Borrow, provenance,
extent, dirección y targets. MIR baja a preheader/header/body/latch/exit con
cleanups y guards explícitos. SSA conserva phis, memory roots, dominance,
normal/unwind edges y ownership lineal. Array/List no crean iterator heap
objects y Range no llama runtime.

## Primer vertical

Se recomienda **ITERATION-V1 — `int` range `for-in` nativo**: ambas formas de
range, operands expresivos, inclusividad, dirección vacía, zero-step, binding
fresh y composición completa con break/continue/return/excepciones/finally.
Debe llegar a LLVM Linux x86-64 O0/O2, incluir corrupciones HIR/MIR/SSA y probar
cero allocation. El resto falla cerrado hasta verticales de enteros completos,
float, collections Copy y collections owning prestadas.

## Fuera de scope y deuda

Quedan para decisiones posteriores iteración mutable o consuming, Alias/value
explícito de owners, View/Vector/Matrix/string/Text, custom iterables,
generators/yield, async/paralelo, pipelines, map/dictionary, destructuring,
enumerate/zip, slicing, comprehensions, ranges abiertos/infinitos, reverse y
custom strides. No se creó código ni se cambió la superficie soportada.
