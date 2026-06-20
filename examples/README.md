# Aether Examples

After installing the local CLI with `python3 -m pip install -e .`, run the
smallest example with:

```bash
aether examples/hello.ae
```

The same file can be inspected with `aether --tokens examples/hello.ae` or
`aether --ast examples/hello.ae`.

This directory contains example Aether programs organized by topic.

## Non-Interactive Examples

Examples that run to completion without user input are suitable for automated testing.

### Structs

- **Geometry.ae** - Define struct `Point` with fields `x` and `y`
- **main.ae** - Create and access a `Point` instance using alias `P`
- **custom_constructor_and_equality.ae** - Use an explicit struct constructor and compare struct values with structural equality

Run both together as a module to demonstrate struct usage:
```bash
python3 src/main.py --cli < /dev/null
# import Geometry;
# P p = P(1.0, 2.0);
# println(p.x);
```

### Classes

- **counter_basic.ae** - Basic private state with public instance methods
- **custom_constructor.ae** - Initialize private class state with an explicit constructor
- **private_field_public_methods.ae** - Encapsulation with explicit getter and mutating method
- **reference_aliasing.ae** - Assignment preserves a shared class reference
- **const_with_mutable_alias.ae** - A `const` reference cannot mutate, while a mutable alias can
- **implements_interface.ae** - Interface dispatch over a class preserves reference semantics
- **invalid_cases.ae** - Invalid class operations kept as commented examples

### Lists

- **list_api.ae** - Native `List<T>` methods, const behavior, and common invalid operations

### Linear Algebra

- **basic_operations.ae** - Basic matrix/vector operations: creation, transposition, matrix multiplication, and iteration
- **primes_check.ae** - Check if a number is prime using simple primality test
- **primes_advanced.ae** - Check if a number is prime using optimized primality test with modular arithmetic

### Non-Linear Systems

- **newton_system.ae** - Solve a 2x2 non-linear system using Newton's method

## Interactive Examples

Examples that require user input are marked as **interactive** and should not be included in automated smoke tests.

### Interactive

- **sum_calculator.ae** - Interactive calculator that reads two numbers and prints their sum
- **primes_interactive.ae** - Interactive primality checker
- **fibonacci.ae** - Interactive Fibonacci sequence generator

### Minimos Cuadrados (Least Squares)

- **MinimosCuadrados.ae** - Least-squares polynomial fitting helpers
- **interactive.ae** - Interactive least-squares polynomial fitting with plot visualization

## Additional Examples

- **Sorts/** - Sorting algorithms and their supporting exception/module example
- **FormulaNumerosPrimos.ae** - Prime-number formula experiment
- **Miller-Rabbin.ae** - Miller-Rabin primality experiment
- **probando.ae**, **probandoNR.ae** - General language experiments
- **pruebaException.ae** - Exception handling experiment
- **pruebaListas.ae** - List operations experiment

## Current Status

- `structs/`: ✅ Non-interactive, tested
- `classes/`: ✅ Non-interactive, tested
- `lists/`: ✅ Non-interactive, tested
- `linear_algebra/`: ✅ Non-interactive, tested  
- `nonlinear_systems/`: ⚠️ Experimental (incomplete implementation)
- `interactive/`: 👤 Interactive examples (not for automation)
- `minimos_cuadrados/`: 👤 Interactive example with plotting

## Notes

### Experimental Examples

The following examples are experimental or incomplete:

- **nonlinear_systems/newton_system.ae** - Solver implementation may need verification
- **minimos_cuadrados/interactive.ae** - Depends on plot support which may have limitations

### Testing

Run non-interactive examples with smoke tests:
```bash
python3 -m pytest tests/test_example_smoke.py -v
```
