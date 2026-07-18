
# Aether v0 Language Specification

> Classification: **Historical**. This document records prototype behavior and
> is deprecated as a current contract. For Aether `1.0.0-rc.2`, use
> [Aether Language Specification v1](AETHER_LANGUAGE_SPEC_V1.md).

## Status

Aether v0 is the initial language specification and executable prototype for Aether Studio. It is implemented in Python as a clean, isolated language core while the final architecture is prepared for a future Rust core.

This document describes the current v0 behavior. It is intentionally small and conservative: the goal is to stabilize syntax, typing, scoping, semantic checks, and execution before adding larger scientific features.

## Files

| Extension | Purpose |
|---|---|
| `.ae` | Aether scripts and programs |
| `.aen` | Future Aether notebooks |
| `.aed` | Future Aether computational documents |

Only `.ae` scripts are recognized at a basic level in v0. Notebooks and computational documents are reserved for later stages.

## Base Syntax

Aether uses braces for blocks:

```aether
if (x > 0) {
    println(x);
}
```

Simple statements must end with `;`.

The semicolon is only a statement terminator. It does not silence output. Assignments do not print automatically. In script mode, only `print(...)` and `println(...)` produce output.

```aether
x = 5;
println(x);
```

## Primitive Types

Aether v0 has six primitive types:

- `int`
- `float`
- `double`
- `complex`
- `string`
- `boolean`

Aether v0 also has a minimal builtin nominal runtime type:

- `Exception`

`Exception` values are used by the language exception feature. They currently expose `message` and `kind` fields.

## Type Inference

Aether supports inference for assignments without explicit type annotations.

| Literal | Inferred type |
|---|---|
| `5` | `int` |
| `5.2` | `double` |
| `im`, `2im`, `1 + 2im` | `complex` |
| `"hello"` | `string` |
| `true` / `false` | `boolean` |

`float` values must be requested explicitly:

```aether
float x = 5.2;
```

`null` has no inferred variable type. A declaration or assignment like `x = null;` is an error because Aether cannot infer the intended nullable base type.

## Declarations and Assignments

Explicit declarations:

```aether
int x = 5;
x = 6;
```

Inferred variables:

```aether
y = 2.5;
```

A variable has a fixed type after it is created. This is true for both explicitly declared variables and inferred variables. Changing a variable to an incompatible type is not allowed.

```aether
x = 5;
x = "hola"; // error
```

## Null and Nullable Types

`null` is a special literal that belongs only to explicitly nullable types. It is not a member of every reference-like type.

A nullable type is written by adding `?` to the base type:

```aether
string? name = null;
int? maybeN = null;
double? maybeX = null;
Vector<double>? maybeV = null;
Matrix<double>? maybeA = null;
```

Rules:

- `null` can be assigned to `T?`.
- A value of type `T` can be assigned to `T?`.
- `null` cannot be assigned to non-nullable `T`.
- `x = null;` without an explicit type is an error.
- A variable inferred as non-nullable remains non-nullable.
- `T?` is not automatically treated as `T`.

```aether
string? name = "Aether";
name = null;
name = "Aether";

string title = null; // error
x = null;            // error
```

Comparisons with `null` are supported:

```aether
string? name = null;

if (name == null) {
    println("empty");
}
```

`print(...)` and `println(...)` render null values as `null`.

Current limitation: v0 does not perform smart casts or null narrowing yet. Inside `if name != null { ... }`, `name` still has type `string?`.

## Constants

`const` declares a variable whose name cannot be reassigned after initialization:

```aether
const int maxIter = 100;
const double tol = 1e-8;
const name = "Aether";
```

`const` can be used with an explicit type or with local inference. Inferred constants use the same rules as inferred variables:

```aether
const n = 10; // n is int
```

In Aether v0, `const` prevents direct reassignment of the identifier:

```aether
const int n = 3;
n = 4; // error: Cannot assign to constant 'n'
n += 1; // error: Cannot assign to constant 'n'
```

`const` also rejects mutations performed through that variable as the root of the assignment or mutating builtin call:

```aether
List<int> ys = {1, 2, 3};
const List<int> zs = ys;

zs[0] = 9;        // error: Cannot mutate constant 'zs'
push(zs, 4);      // error: Cannot mutate constant 'zs'
clear(zs);        // error: Cannot mutate constant 'zs'

ys[0] = 9;        // ok
push(ys, 4);      // ok
```

This is not deep immutability. `const` blocks mutation through the constant variable, but it does not freeze a shared object globally. A mutable alias to the same value can still mutate that value.

For Array/List, the restriction follows chained access through value types and
nested collections. Thus `const List<List<int>> outer; outer[0].push(1);` and
`const List<Item> items; items[0].field = value;` are errors. Assigning
`outer[0]` to a normal `List<int>` local performs the normal owning handle copy;
mutating that local is allowed and is observed by `outer`. A class instance
reached as a collection element is a separate reference object: the const path
cannot replace its slot, but does not freeze that instance transitively.

## Type Aliases

`alias` declares a type synonym:

```aether
alias Real = double;
alias Index = int;

Real x = 2.5;
double y = x; // valid: Real is not a nominal type
```

Aliases are compile-time type information and do not exist as runtime values. An alias must resolve to an existing type:

```aether
alias Real = double;
alias Scalar = Real;
alias RealVector = Vector<double>;
```

Alias chains are resolved transitively. Cycles are errors:

```aether
alias A = B;
alias B = A; // error: Cyclic type alias involving 'A'

alias Self = Self; // error
```

`Matrix<T>` and `Vector<T>` aliases work for the existing primitive element types supported by Aether v0. Full generic type parameters are still reserved for a future version.

Invalid targets, duplicate alias names, and collisions with values/functions in the same scope are errors:

```aether
alias Foo = DoesNotExist; // error
alias Real = double;
alias Real = int;         // error
int Real = 3;             // error
```

### Alias Limitations

Aliases of generic container types work when fully instantiated:

```aether
alias RealVector = Vector<double>;     // valid
RealVector v = [1.0, 2.0];             // valid
```

However, using an alias of a primitive type as a type parameter does not yet work:

```aether
alias Real = double;
Vector<Real> v = [1.0, 2.0];            // NOT YET supported; use Vector<double> instead
```

This limitation will be addressed when full generic type parameters are implemented.

## Structs

Aether v0 supports a nominal `struct` form with an explicit list of typed fields, optional instance methods, an automatic positional constructor or one explicit constructor, and field/method access with `.`.

```aether
public struct Point {
    double x;
    double y;
}

Point p = Point(1.0, 2.0);
println(p.x);
println(p.y);
```

Struct declarations are top-level only in this version. They may use `public` or `private` in the same way as other top-level declarations:

```aether
private struct InternalData {
    int n;
}
```

Fields must have explicit types and unique names:

```aether
struct Point {
    double x;
    double y;
}
```

Field-level `public`, `private`, and `const` are not supported yet. Nested declarations, constructor overloads, static methods, generic methods, and inheritance are also not supported inside structs.

### Struct Methods

Structs may declare instance methods after or between fields. Methods use the same typed parameter and return syntax as top-level functions, but they do not declare an explicit `self` parameter:

```aether
public struct Point {
    double x;
    double y;

    double squaredNorm() {
        return x*x + y*y;
    }

    double norm() {
        return sqrt(squaredNorm());
    }

    Point scale(double k) {
        return Point(x*k, y*k);
    }
}

Point p = Point(3, 4);
println(p.norm()); // 5.0
Point q = p.scale(2);
```

The receiver is available implicitly inside the method. Field names resolve after local variables and parameters, so parameters can shadow fields:

```aether
struct S {
    int x;

    int f(int x) {
        return x; // parameter, not field
    }
}
```

The explicit receiver name `this` is also available for field reads and writes:

```aether
double sum() {
    return this.x + this.y;
}
```

Methods are looked up on the nominal struct type. Calling an unknown method, calling a method with the wrong arity, reading a method without `(...)`, or calling a field as a method is a type error. Fields and methods cannot share a name, and a struct cannot declare two methods with the same name. Methods may return any supported Aether type, including primitives, structs, enums, `List<T>`, `Vector<T>`, and `Matrix<T>`.

Struct methods may be mutating. A method is mutating when it assigns to a field of its receiver, either through an implicit field name or through `this.field`. A method that calls another mutating method on the same receiver is also mutating:

```aether
struct Counter {
    int value;

    void increment() {
        value = value + 1;
    }

    void add(int n) {
        this.value = this.value + n;
    }
}

Counter c = Counter(0);
c.increment();
c.add(4);
println(c.value); // 5
```

Field assignment inside a method is still typechecked against the declared field type. Local variables and parameters shadow fields; use `this.field` to select the receiver field when a local has the same name:

```aether
struct Counter {
    int value;

    void f(int value) {
        value = value + 1;           // parameter
        this.value = this.value + 1; // field
    }
}
```

Mutating methods cannot be called through a `const` receiver:

```aether
const Counter c = Counter(0);
c.increment(); // error: Cannot mutate constant 'c'
```

Mutating methods also cannot be called on temporary values, because the mutation would have no stable storage target:

```aether
Counter(0).increment(); // error: Cannot call mutating method on temporary value.
```

If a struct does not declare an explicit constructor, it has an automatic positional constructor. Its parameters follow field declaration order and use the declared field types:

```aether
Point p = Point(1.0, 2.0); // valid
Point q = Point(1.0);      // error: wrong argument count
Point r = Point("x", 2.0); // error: incompatible field type
```

Alternatively, a struct may declare one explicit constructor. It uses `constructor(...) { ... }`, has no return type, and all parameters must be typed:

```aether
struct Point {
    double x;
    double y;

    constructor(double x, double y) {
        this.x = x;
        this.y = y;
    }
}

Point p = Point(1.0, 2.0);
```

An explicit constructor completely replaces the automatic field-based signature. Calls must match the explicit parameter count and types; the positional field constructor is not also available.

The runtime creates a struct value with default field values, executes the constructor body on that value, and returns the initialized value. The constructor may read and write fields through implicit field names or `this`, use parameters, run ordinary control flow, and call methods of the same struct. Field assignments and method calls are typechecked using the same rules as struct methods.

Only one explicit constructor is allowed per struct. A constructor cannot be `private` or `static`, cannot declare a return type, and cannot return a value. `return;` without a value may end it early. Constructors cannot be declared outside a class or struct and do not participate in interface conformance.

Local inference works with struct constructor calls:

```aether
p = Point(1.0, 2.0);
println(p.x);
```

### Structs are value types

Struct values have value semantics. Assigning a struct to another variable copies the value, passing a struct as a function argument copies the value, and returning a struct returns an independent value. There is no observable aliasing between variables of struct type.

```aether
Point p = Point(1, 2);
Point q = p;

q = Point(10, 20);
println(p); // Point(x=1, y=2)
println(q); // Point(x=10, y=20)
```

This also applies when structs contain other structs:

```aether
struct Segment {
    Point a;
    Point b;
}

Point p = Point(1, 2);
Segment s1 = Segment(p, p);
Segment s2 = s1;

s2.a.x = 10;
println(s1.a.x); // 1
println(s2.a.x); // 10
```

In this respect Aether structs behave more like C# `struct` values, Julia immutable-style data values, or simple Rust structs than like Java objects. They are not reference objects, and assignment does not make two struct variables point at the same underlying instance. This value semantics is separate from field assignment: a non-`const` struct variable may update its own fields, but that update does not mutate another struct variable that was copied from it.

Mutating methods follow the same value semantics:

```aether
Counter a = Counter(0);
Counter b = a;
b.increment();
println(a.value); // 0
println(b.value); // 1
```

Struct aliases are type aliases. An alias can be used both as the annotated type and as the constructor name:

```aether
struct Point {
    double x;
    double y;
}

alias P = Point;
P p = P(1.0, 2.0);
```

Struct fields may use existing aliases:

```aether
alias Real = double;

struct Point {
    Real x;
    Real y;
}
```

Structs may contain fields whose type is another visible struct:

```aether
struct Point {
    double x;
    double y;
}

struct Segment {
    Point a;
    Point b;
}

Segment s = Segment(Point(0.0, 0.0), Point(1.0, 1.0));
println(s.a.x);
println(s.b.y);
```

Struct values can be passed to and returned from functions:

```aether
Point origin() {
    return Point(0.0, 0.0);
}

Point shift(Point p, double dx, double dy) {
    return Point(p.x + dx, p.y + dy);
}
```

Field reads are typechecked. Accessing a missing field or using field access on a non-struct value is an error:

```aether
println(p.z); // error

int x = 3;
println(x.y); // error
```

Field assignment is supported for this shallow data model:

```aether
Point p = Point(1.0, 2.0);
p.x = 3.0;
println(p.x); // 3.0
```

The assignment target must start from a variable or another field rooted in a variable. Assignment to a field on a temporary value is not supported:

```aether
Point(1.0, 2.0).x = 5.0; // error
```

This follows the current shallow `const` rule. A `const` binding prevents rebinding the variable name, but it does not deep-freeze the fields of the struct value yet.

Structs support nominal structural equality with `==` and `!=`. Both operands must have exactly the same nominal struct type; two different structs are not comparable even when they declare identical fields. Values of the same struct type are compared field by field in declaration order, and nested structs are compared recursively:

```aether
println(Point(1.0, 2.0) == Point(1.0, 2.0)); // true
println(Point(1.0, 2.0) != Point(1.0, 3.0)); // true
```

Every field must support equality. Comparable fields include numeric types, `string`, `boolean`, enums, nullable comparable types, recursively comparable structs, and collection or mathematical container types that already support equality such as `List<T>`, `Vector<T>`, and `Matrix<T>` when their element types are comparable.

Classes, interfaces, `void`, and any other type without `==` support are not comparable fields. If any field is not comparable, applying `==` or `!=` to that struct is a type error. `!=` is exactly the negation of `==`.

`print(...)` and `println(...)` render structs with field names:

```aether
println(Point(1.0, 2.0)); // Point(x=1.0, y=2.0)
```

Packaged files export only public structs:

```aether
package Geometry;

public struct Point {
    double x;
    double y;
}

private struct Hidden {
    int value;
}
```

```aether
import Geometry;

Point p = Point(1.0, 2.0); // valid
Hidden h = Hidden(3);      // error: Hidden is private
```

A public struct cannot expose a private local type in one of its fields:

```aether
package Geometry;

private struct Internal {
    int x;
}

public struct Wrapper {
    Internal value; // error
}
```

Current struct limitations:

- No constructor overloads or constructor chaining.
- No private or static constructors.
- No field visibility.
- No static methods or generic methods.
- No new generic struct parameters.
- No named constructor arguments.
- No user-defined properties or destructors.
- No inheritance, traits, or protocols.
- No destructuring or pattern matching for structs.
- No operator overloading for structs.
- No user-defined or configurable equality for structs.
- No deep `const`.
- Struct lowering to IR/JIT is not implemented.

## Classes

Aether v0 supports a minimal nominal `class` form. Classes look similar to structs, but they are reference types and their members are private by default:

```aether
public class Counter {
    int value; // private by default

    public void increment() {
        value = value + 1;
    }

    public int getValue() {
        return value;
    }

    public void setValue(int value) {
        this.value = value;
    }
}
```

Class declarations are top-level only. A class without an explicit constructor uses an automatic positional constructor whose arguments follow field declaration order. Automatic constructor initialization is allowed for every declared field, including private fields; member visibility controls later access, not construction:

```aether
class Counter {
    int value; // private
    public int getValue() { return value; }
}

Counter c = Counter(4); // valid: initializes the private field
println(c.getValue());  // 4
```

Alternatively, a class may declare one explicit constructor using `constructor(...) { ... }` or `public constructor(...) { ... }`. Constructors have no return type:

```aether
class Counter {
    int value;

    public constructor(int initial) {
        this.value = initial;
    }

    public void increment() {
        value = value + 1;
    }
}

Counter c = Counter(5);
```

When an explicit constructor is present, it completely replaces the automatic positional constructor. Calls to the class must match the explicit constructor parameter count and types exactly; the old field-based signature is no longer available. Constructor parameters must be typed.

The runtime creates the class instance first, then executes the constructor body with that instance as `this`, and finally returns the initialized instance. A constructor is an instance context: it may read and write fields, access private members of its own class, use its parameters, and call methods of the same class. `return;` may end a constructor early, but `return` with a value is invalid.

Only one explicit constructor is allowed per class. Constructors cannot be declared outside a class or struct, cannot be `private` or `static`, and cannot declare a return type. Constructors do not participate in interface conformance.

Fields and methods may be marked `public` or `private`. Unmarked class fields and methods are private; unmarked struct fields and methods remain public. Private members are accessible inside the declaring class through either implicit field names or `this.field`, but not through outside references:

```aether
Counter c = Counter(0);
c.getValue(); // valid
c.value;      // error: field is private
```

`public` fields can be read and updated through a mutable external reference. Aether v0 does not synthesize properties, getters, or setters: methods such as `getValue()` and `setValue(...)` must be declared explicitly.

Classes have reference semantics. Assigning, passing, or returning a class value copies the reference, not the object:

```aether
Counter a = Counter(0);
Counter b = a;

b.increment();
println(a.getValue()); // 1
println(b.getValue()); // 1
```

`const` on a class variable prevents rebinding that variable and prevents mutation through that variable, but it does not freeze the object globally if a mutable alias exists:

```aether
Counter a = Counter(0);
const Counter b = a;

a.increment();         // valid
b.increment();         // error: Cannot mutate constant 'b'
println(b.getValue()); // 1
```

Class methods use the same mutability detection as struct methods. Assigning to an implicit field or `this.field` makes the method mutating, and calling a mutating receiver method transitively makes the caller mutating. Mutating methods cannot be called on temporaries:

```aether
Counter(0).increment(); // error
Counter(0).getValue();  // valid
```

Classes may implement interfaces. Methods used to satisfy an interface must be public. Dispatch through an interface preserves class reference semantics:

```aether
interface Resettable {
    void reset();
}

class Counter implements Resettable {
    int value;

    public void reset() {
        value = 0;
    }
}

Counter c = Counter(1);
Resettable r = c;
r.reset(); // mutates the same object referenced by c
```

Packaged files export only `public` classes. Private classes remain usable inside their own module and are not visible to importers.

Class equality is not implemented yet. Comparing class values with `==` or `!=` is an error; no identity or structural equality rule is part of v0.

Current class limitations:

- No inheritance or `extends`.
- No `super`.
- No constructor overloads.
- No constructor chaining or calls to `constructor(...)` from a constructor.
- No private or static constructors.
- No method overloads.
- No static methods.
- No destructors.
- No generic classes.
- No automatic properties, getters, or setters.
- No operator overloading.
- No class equality.

## Planned Properties (Not Implemented)

> **Status: planned design only. Properties are not implemented in Aether v0.**

Properties v1 are planned only for classes. They are not fields, but they use field-like access syntax and may provide controlled read and write access to internally stored values.

The planned automatic property syntax is:

```aether
public int age { get; set; }
public int id { get; }
public string name { get; private set; }
```

An automatic property generates a private internal backing field. That storage is created by the compiler, is hidden from source code, and cannot be named or accessed directly by the user. For example:

```aether
public int age { get; set; }
```

behaves as if private storage existed internally, while exposing access only through the property's declared getter and setter.

Fields and properties share the same member namespace. A class cannot declare a field and a property with the same name:

```aether
class Person {
    private int age;
    public int age { get; set; } // error: duplicate member name
}
```

Property access uses ordinary member syntax. Reading a property invokes its getter, and assigning to it invokes its setter:

```aether
obj.age;       // calls the getter
obj.age = 10;  // calls the setter
```

Assigning to a property without a setter is an error:

```aether
obj.id = 5; // error: property has no setter
```

Inside a setter, `value` is an implicit parameter containing the value being assigned.

Custom accessors are reserved for a future design beyond automatic Properties v1. The intended direction is:

```aether
class Person {
    private int storedAge;

    public int age {
        get {
            return storedAge;
        }

        set {
            if (value < 0) {
                throw Exception("age cannot be negative");
            }

            storedAge = value;
        }
    }
}
```

Property setters are mutations through their receiver. Therefore, a property may be read through a `const` class reference, but it cannot be assigned through that reference:

```aether
const Person p = Person("Ana");
p.name;        // valid
p.name = "Lu"; // error: the setter mutates through p
```

A constructor of the declaring class may assign a property when the setter is accessible from that constructor. Whether a get-only property may receive special constructor-only assignment remains open for later design.

Properties v1 will not add properties to interfaces. Interface conformance continues to involve methods only until a later design explicitly extends it.

Example of the planned automatic property model:

```aether
class Person {
    public string name { get; set; }
    public int age { get; private set; }

    public constructor(string name, int age) {
        this.name = name;
        this.age = age;
    }

    public void birthday() {
        this.age = this.age + 1;
    }
}
```

The following features are explicitly outside Properties v1 and are not implemented:

- Properties in structs.
- Properties in interfaces.
- Computed properties with custom accessors instead of an automatic backing field.
- Init-only properties.
- Delegated properties.
- Getter or setter overrides.
- Static properties.
- Property overloading.
- Related operator overloading.

## Interfaces

Aether v0 supports minimal nominal interfaces. An interface declares method signatures only:

```aether
public interface Shape {
    double area();
}

private interface Printable {
    string toString();
}
```

Interfaces are top-level declarations. They may be `public` or `private` like other top-level declarations. Interfaces cannot declare fields, method bodies, default methods, generic parameters, or inheritance from other interfaces in this version.

Structs and classes can implement interfaces:

```aether
public struct Circle implements Shape, Printable {
    double r;

    double area() {
        return r * r;
    }

    string toString() {
        return "Circle";
    }
}
```

The typechecker verifies that every implemented interface method is present on the concrete type. Signatures must match exactly: same name, same parameter count, same parameter types, and same return type. Missing methods and signature mismatches are type errors. Class methods that implement interfaces must be `public`.

An interface defines a nominal type. A struct or class value is assignable to an interface type when its concrete declaration implements the interface:

```aether
Shape s = Circle(2);
println(s.area());

void printArea(Shape s) {
    println(s.area());
}

printArea(Circle(2));

Shape makeShape() {
    return Circle(3);
}
```

Calling a declared interface method dispatches to the concrete method stored in the value. Structs remain value types when assigned or passed through interface-typed variables and parameters; classes remain reference types. If the dispatched method is mutating, the interface-typed receiver must be mutable; calling it through a `const` interface variable is rejected.

Member access uses the static type. A variable whose static type is an interface exposes only the interface methods:

```aether
s.area(); // valid
s.foo();  // error: Shape has no method foo
s.r;      // error: Shape does not expose Circle.r
```

Packaged files export only public interfaces. Private interfaces remain visible inside their own module but are not imported by other modules. A public struct or class in a package cannot implement a private interface, because that would expose the private interface in its public API.

Current interface limitations:

- Method signatures only.
- No fields.
- No method bodies or default methods.
- No inheritance between interfaces.
- No generic interfaces.
- Structs and classes can implement interfaces.

## Enums

Aether v0 supports simple nominal enums with payload-free variants:

```aether
public enum SolverStatus {
    Converged,
    MaxIterations,
    SingularMatrix
}

private enum Color {
    Red,
    Green,
    Blue
}
```

An enum declaration is top-level only. It may use the same `public`/`private` visibility modifiers as other top-level declarations. In a packaged file, an enum without an explicit visibility modifier follows the package default and is private.

Variants are part of the enum declaration and do not have their own visibility. A public enum exposes all of its variants. Variant names must be unique within the enum.

Enum values are written with qualified variant access:

```aether
SolverStatus s = SolverStatus.Converged;

if (s == SolverStatus.Converged) {
    println("ok");
}
```

`SolverStatus.Converged` has type `SolverStatus`. Enums are nominal types: two enums with the same variant names are still distinct types.

```aether
enum SolverStatus { Converged }
enum OtherStatus { Converged }

SolverStatus s = SolverStatus.Converged; // valid
SolverStatus t = OtherStatus.Converged;  // error
```

`==` and `!=` are supported only between values of the same enum type. Comparing different enum types, or comparing an enum with `int`, `string`, `boolean`, or any other non-matching type, is a type error.

Enum values are not booleans:

```aether
if (SolverStatus.Converged) { // error
    println("ok");
}
```

Enums do not have constructors. Calling an enum type as a function is an error:

```aether
SolverStatus(); // error
```

Enums can be used in variable declarations, function return types, parameters, and struct fields:

```aether
SolverStatus solve() {
    return SolverStatus.Converged;
}

void report(SolverStatus status) {
    println(status);
}

struct Result {
    SolverStatus status;
}
```

`print(...)` and `println(...)` render enum values as `EnumName.VariantName`:

```aether
println(SolverStatus.Converged); // SolverStatus.Converged
```

The runtime value retains the enum declaration identity, variant identity, and
its zero-based source-order discriminant. AST, IR, and SSA keep the nominal
type; LLVM/native lowers the ABI value to `i32`. That integer representation is
internal and does not introduce an implicit conversion to or from `int`, nor a
stable external C enum ABI. Imports and aliases preserve the owning
module/declaration identity, so homonymous enums from different modules remain
incompatible.

Packaged files export only public enums:

```aether
package Solver;

public enum SolverStatus {
    Converged,
    MaxIterations
}

private enum InternalStatus {
    Hidden
}
```

```aether
import Solver;

println(SolverStatus.Converged); // valid
println(InternalStatus.Hidden);  // error: InternalStatus is private
```

Current enum limitations:

- No payload variants.
- No methods inside enums.
- No custom constructors.
- No `match` or `switch` yet.
- No per-variant visibility.
- No explicit numeric discriminants or implicit integer casts.
- No flags/bitwise enum semantics or reflection.

## Visibility Modifiers

Top-level declarations may be prefixed with `public` or `private`:

```aether
public int inc(int x) {
    return x + 1;
}

private const int internalLimit = 100;
public alias Real = double;
```

The accepted order in v0 is:

- `public` or `private`
- optional `const` for variable declarations
- the declaration itself

`public private` and repeated visibility modifiers are errors.

Visibility is recorded in the AST and symbol metadata. Inside a single file, `public` and `private` do not restrict access between declarations. Across file imports, packaged files export only `public` declarations.

In files with a `package` declaration, top-level declarations without a visibility modifier are private by default. In scripts without `package`, unmodified top-level declarations are exportable through explicit module membership or selective imports.

## Packages and File Imports

Aether v0 supports a first incremental multi-file module model without requiring declarations to live inside a class.

```aether
package Math.LinearAlgebra;

public double norm(Vector<double> v) {
    return 0.0;
}

private double helper(Vector<double> v) {
    return 1.0;
}
```

`package` is a top-level declaration. If present, it must be the first non-comment declaration in the file, before imports and normal declarations. A file may declare at most one package. The package name is stored as a dotted logical path such as `Math.LinearAlgebra`.

Another file can import the package:

```aether
import Math.LinearAlgebra;
println(Math.LinearAlgebra.norm([1; 2; 3]));
```

Imports create explicit bindings; importing a module never copies all of its
exports into the local scope. The four supported forms are:

```aether
import Math.LinearAlgebra;                         // Math.LinearAlgebra
import Math.LinearAlgebra as LA;                   // LA
from Math.LinearAlgebra import solve;              // solve
from Math.LinearAlgebra import solve as linearSolve; // linearSolve
```

The module's canonical identity is independent of its local binding. For
example, `LA` above still identifies `Math.LinearAlgebra`. A selective import
may bind a function, constant, type, or exported submodule; `from Math import
LinearAlgebra as LA` therefore binds the same canonical submodule as the module
alias example. Aliases collide with variables, functions, types, and other
imports in the same scope regardless of declaration order. Duplicate bindings
are errors, while a canonical binding and a differently named alias may
coexist.

`import`, `from`, and `as` are reserved keywords and cannot be declaration,
parameter, alias, or local module names. Import paths and aliases retain their
source locations in distinct AST nodes (`ImportStatement` and
`FromImportStatement`), while semantic bindings retain both their visible name
and canonical module origin.

The initial file mapping is intentionally simple:

```text
Math.LinearAlgebra -> Math/LinearAlgebra.ae
Config             -> Config.ae
```

Resolution is relative to the active source root. When running a saved file from the editor/runtime, the source root is the file's containing directory. Direct `run_aether(...)` calls can pass an explicit `source_root`; otherwise the current working directory is used to preserve existing script-import behavior.

For packaged files, only `public` top-level variables/constants, aliases, structs, classes, interfaces, enums, and functions are exported to importers:

```aether
package Math.Types;

public alias Real = double;
public const int DEFAULT_ITER = 100;
```

```aether
from Math.Types import Real;
from Math.Types import DEFAULT_ITER;

Real x = 2.5;
println(DEFAULT_ITER);
```

`private` declarations and declarations without a modifier remain usable inside their own file but are not visible through selective imports. Attempting to import a private name is a type error. File imports also reject missing modules, missing exports, import cycles, and binding collisions.

Builtin namespaces remain separate from file modules. A builtin import such as `import Math.LinearAlgebra` creates only the qualified module binding; use `from Math.LinearAlgebra import solve` for an unqualified local function. If a builtin namespace and a file module have the same name, the builtin namespace is preferred in this version.

Current package/import limitations:

- A package maps to one `.ae` file; multi-file packages are not implemented yet.
- Import lists, wildcard imports, relative imports, and reexports are not implemented.
- Cyclic imports are rejected.
- `private` is enforced across imports only; declarations in the same file can still use each other.
- Advanced exceptions and multi-file package visibility are outside this version.

## Implicit Conversions

Only safe widening conversions are implicit:

- `int -> float`
- `int -> double`
- `int -> complex`
- `float -> double`
- `float -> complex`
- `double -> complex`

Lossy or cross-domain conversions are not implicit:

- `complex -> double`
- `complex -> float`
- `complex -> int`
- `double -> float`
- `double -> int`
- `float -> int`
- `string` to any non-string type
- `boolean` to any non-boolean type
- numeric types to `boolean`
- numeric types to `string`

```aether
double x = 5;   // valid
int y = 2.5;    // error
```

## Explicit Casts

Aether v0 supports casts as function calls:

- `int(expr)`
- `float(expr)`
- `double(expr)`
- `complex(expr)`
- `string(expr)`
- `boolean(expr)`

Numeric casts to `int` truncate toward zero:

```aether
int x = int(3.9); // x = 3
```

An explicit cast to the value's existing scalar type, such as `int(i)` or
`double(d)`, is a valid identity operation and may be optimized away.

`string(value)` converts a value to its textual representation.

`complex(value)` converts a numeric value to complex, and `complex(real, imag)` constructs `real + imag*im`.

`boolean(number)` and `boolean(string)` are not implemented in v0 and must fail.

## Operators

Arithmetic operators:

- `+`
- `-`
- `*`
- `/`
- `%`
- `^`

`/` is always real division. Integer division is not implemented with `/`.

```aether
int a = 5;
int b = 2;
double c = a / b; // c = 2.5
```

`%` computes a truncating remainder, matching Java/C#/C/C++ sign behavior. It is defined as:

```text
a % b = a - trunc(a / b) * b
```

The divisor must not be zero:

```aether
println(5 % 3);    // 2
println(-5 % 3);   // -2
println(5 % -3);   // 2
println(-5 % -3);  // -2
```

Use `Math.mod(a, b)` for floor/Python-like modulo:

```aether
println(Math.mod(5, 3));    // 2
println(Math.mod(-5, 3));   // 1
println(Math.mod(5, -3));   // -1
println(Math.mod(-5, -3));  // -2
```

Promotion rules follow the wider numeric type. Important cases:

- `int + int -> int`
- `int / int -> double`
- `int + float -> float`
- `int + double -> double`
- `float + double -> double`
- `float + float -> float`
- `double + double -> double`
- `double + complex -> complex`
- `complex + complex -> complex`

The same numeric promotion model applies to `-`, `*`, and `/`, except that `/` is real division.

`^` is right-associative. `int ^ int` returns `int`, requires a non-negative
exponent, uses exponentiation by squaring and checks every signed-i32
multiplication. Thus `0 ^ 0 == 1`, `2 ^ 30` is valid, `2 ^ 31` overflows, and
`(-2) ^ 31 == -2147483648`. A statically visible negative integer exponent is
rejected; a dynamic negative integer exponent panics. If either operand is
`double`, both operands are promoted to `double` and IEEE/libm power semantics
apply, including NaN, infinity and signed-zero pole cases.

Complex values use `im` as the imaginary unit:

```aether
z = 1 + 2im;
w = complex(3, -4);
println(z * w);
```

The alias `i` is not reserved; use `im` for imaginary literals. Ordered comparisons and `%` require real numeric operands and reject `complex`.

Strings:

```aether
string s = "hola" + " mundo"; // valid
```

`string + numeric` and `numeric + string` are not allowed.
Concatenation is immutable, may allocate, preserves embedded NUL bytes, and
returns an owned string. No implicit formatting or conversion is performed.

`s.byteLength` returns the number of UTF-8 bytes as `int` in O(1). It is not a
character, code-point, or grapheme count: `"é".byteLength == 2` and
`"🙂".byteLength == 4`.

`s.trim()` returns an owned immutable string after removing only ASCII space,
tab, line feed, carriage return, form feed, and vertical tab from both ends.
It preserves internal whitespace, embedded NUL, valid UTF-8, and every
non-ASCII whitespace code point. It is locale-independent and does not modify
the receiver. An all-whitespace result is the canonical empty string.

`s.split(separator)` takes exactly one `string` and returns a new owned
`Array<string>`. It compares exact UTF-8 bytes from left to right and consumes
non-overlapping matches (`"ababa".split("aba")` is `{"", "ba"}`). Leading,
trailing, and repeated separators preserve empty fields. An empty separator is
invalid and panics with `Aether panic: string split separator cannot be empty`.
Embedded NUL and multibyte separators are ordinary length-aware bytes. Every
fragment is owned; this is not regex, CSV, normalization/segmentation,
split-by-whitespace, or split-with-limit. The initial search is O(n * m), with
O(n) total fragment bytes copied.

Numeric parsing is explicit and structured:

```aether
IntParseResult identifier = parseInt("+42");
DoubleParseResult amount = parseDouble("-2.5e-3");
if (amount.status == ParseStatus.Success) {
    println(amount.value);
}
```

`parseInt` accepts exactly `sign? digit+` in decimal ASCII and checks the i32
range. `parseDouble` accepts decimal mantissas with an optional point and
optional signed `e`/`E` exponent as specified in
[`STRING_PARSING_DESIGN.md`](STRING_PARSING_DESIGN.md). Both reject whitespace,
non-ASCII, embedded NUL and trailing text without throwing. Empty,
invalid-format and out-of-range inputs are distinguished by `ParseStatus`.
NaN/infinity spellings are not accepted; double underflow follows IEEE-754.
Parsing remains strict: callers that want boundary whitespace removed must
write it explicitly, for example `parseInt(" 42 ".trim())`.

String literals support interpolation with `$expr$`. The expression is parsed as Aether, typechecked in the current scope, evaluated at runtime, and formatted with the same display rules used by `print(...)` and `println(...)`.

```aether
n = 4;
println("n = $n$");       // n = 4
println("n^2 = $n^2$");   // n^2 = 16
println("Precio: \$10");  // Precio: $10
```

Empty interpolation (`$$` or `$   $`), unclosed interpolation, invalid embedded expressions, and undefined names inside interpolation are errors.

Booleans do not participate in arithmetic:

```aether
true + 1; // error
```

Logical negation uses the prefix `!` operator. Its only valid signature is:

```text
!boolean -> boolean
```

It binds more tightly than comparisons, equality, `&&`, and `||`, and may be
repeated:

```aether
boolean ready = false;
println(!ready);        // true
println(!!ready);       // false
println(!(1 == 2));     // true
```

Aether does not apply truthy/falsy conversions: `!1`, `!0.0`, `!"text"`, and
negation of collections are type errors. `!` has no postfix form and does not
mean factorial. Factorial remains available as `factorial(value)` or
`Math.factorial(value)`. The two-character `!=` token remains the inequality
operator.

## Comparisons

Numeric comparisons return `boolean`:

```aether
x = 3 < 4; // boolean
```

Supported:

- numeric comparisons such as `int < double`
- `string == string`
- `boolean == boolean`
- nominal structural equality between comparable values of the same struct type
- ordered structural equality between `Array<T>`/`List<T>` values when `T`
  supports equality
- `!=` for comparable values

Not supported in v0:

- `string < string`
- `boolean < boolean`

## Lists

Aether separates general programming collections from mathematical vectors and matrices:

- `List<T>` is the public dynamic collection type.
- List literals use braces: `{1, 2, 3}`.
- Without an expected type, a brace literal infers `List<T>`.
- With an expected `List<T>` target type, a brace literal produces `List<T>`.
- List indexing is 0-based: `xs[0]`.
- `[ ... ]` is reserved for mathematical `Vector<T, Orientation>` and
  `Matrix<T>` literals.

`Array<T>` is the fixed-size collection type. Its relationship to `List<T>` and
brace literals is documented in
[`AETHER_COLLECTIONS_DESIGN.md`](AETHER_COLLECTIONS_DESIGN.md).

Arrays and lists support 0-based, half-open slicing with two explicit `int` bounds:

```aether
Array<int> values = {1, 2, 3, 4, 5};
Array<int> middle = values[1:4];       // {2, 3, 4}
Array<int> whole = values[0:values.length];
Array<int> empty = values[2:2];
```

`collection[start:end]` returns a newly allocated collection of the same type containing the elements
in `[start, end)`. The new array does not share its container or element buffer
with the source, so indexed assignment in one does not change the other. Bounds
must satisfy `0 <= start <= end <= collection.length`; otherwise execution panics with
`Aether panic: Array slice out of bounds` or `Aether panic: List slice out of bounds`.
Only the explicit two-bound form is supported: `collection[:]`, `collection[start:]`, `collection[:end]`, step slices,
and slice assignment are not supported.

The LLVM capacity, growth, allocation, and shrinking policy for
length-changing `List<T>` operations is documented in
[`AETHER_LIST_GROWTH_DESIGN.md`](AETHER_LIST_GROWTH_DESIGN.md). That document
marks `clear`, `push`, and `pop` as implemented in the backend. `clear` sets the shared
header's length to zero in O(1), preserves capacity and data, and performs no
deallocation or recursive destruction. `push` appends in amortized O(1), grows
capacity geometrically when required, may replace the owned data buffer, and
preserves the shared header so aliases observe the new length and element.
`pop` removes and returns the last element in O(1), panics on an empty list,
and preserves header, capacity, and data; its now-out-of-range slot is logically
dead and is not cleared. `insert` and `removeAt` remain frontend-only.

The detailed future contract shared by `List<T>.sort()` and
`Array<T>.sort()` is documented in
[`AETHER_SEQUENCE_SORT_DESIGN.md`](AETHER_SEQUENCE_SORT_DESIGN.md). It defines
stable ordering, strings, NaN, mutation, and rejected element types. The array
API and compiler/backend work described there are design-only.

The first-class mathematical design for oriented vectors and matrices is
documented separately in
[`AETHER_VECTOR_MATRIX_DESIGN.md`](AETHER_VECTOR_MATRIX_DESIGN.md).

Examples:

```aether
inferred = {1, 2, 3};     // List<int>
List<int> xs = {1, 2, 3};
List<double> ys = {1.0, 2.0, 3.0};
List<string> names = {"Ana", "Luis"};

println(xs[0]); // 1
println(names); // {"Ana", "Luis"}
```

List elements must be homogeneous or numerically promotable. Lists use commas only; `{1 2 3}` is a syntax error.
The expected target type can come from an explicit variable declaration, assignment to an existing variable, function parameter, return type, or struct field. Numeric widening follows the same implicit-conversion rules as assignments: for example, `List<double> xs = {1, 2.5};` is valid, while `List<int> xs = {1, 2.5};` is not. `array(...)`, `int[]`, and other `T[]` spellings are not public Aether v0 syntax.

Lists use the same copying, half-open rule as arrays:

```aether
List<int> xs = {10, 20, 30, 40, 50};

List<int> a = xs[1:4];          // {20, 30, 40}
List<int> empty = xs[0:0];      // {}
List<int> whole = xs[0:length(xs)];
```

Only `xs[start:end]` is supported and both bounds must be `int`. The result has
type `List<T>`, owns a new object and buffer, and has `size == capacity ==
end-start`. Elements are copied logically in order; nested collection handles
remain shared. Negative bounds, `start > end`, and bounds greater than length
panic without clamping. Steps, open bounds, views and slice assignment are not
supported.

The original `List<T>` API remains exposed as global builtins:

```aether
List<int> xs = {1, 2};

println(length(xs));      // 2
println(is_empty(xs));    // false
List<int> ys = copy(xs);  // ys is a new List<int> with the same elements
push(xs, 3);              // {1, 2, 3}
println(pop(xs));         // 3, xs is {1, 2}
insert(xs, 1, 99);        // {1, 99, 2}
println(remove_at(xs, 1)); // 99, xs is {1, 2}
println(contains(xs, 2)); // true
reverse(xs);              // {2, 1}
sort(xs);                 // {1, 2}
clear(xs);                // {}
```

All list operations use 0-based indices. `insert(xs, index, value)` accepts `0 <= index <= length(xs)`; `remove_at(xs, index)` accepts `0 <= index < length(xs)`. `copy(xs)` returns a new `List<T>` container with the same elements as `xs`; it is a shallow copy, does not mutate `xs`, and is allowed for `const List<T>`. `push`, `insert`, `pop`, `remove_at`, `clear`, `reverse`, and `sort` mutate the list and reject a first argument whose expression is rooted in a `const` variable. `sort(xs)` and the method form sort `List<int>`, `List<double>`, `List<string>`, `Array<int>`, `Array<double>`, and `Array<string>` in place. Their stable cross-container ordering contract, including NaN handling, is defined in [`AETHER_SEQUENCE_SORT_DESIGN.md`](AETHER_SEQUENCE_SORT_DESIGN.md). `pop` and `remove_at` return the removed element. `length` returns `int`; `is_empty` and `contains` return `boolean`; `push`, `insert`, `clear`, `reverse`, and `sort` return `void`.

`Vector<T>` and `Matrix<T>` are not lists. They do not accept list mutation builtins such as `push`, `pop`, `insert`, `remove_at`, `clear`, `reverse`, or `sort`.

## Native Builtin Properties And Methods

Aether v0 supports a small set of native instance properties and methods on existing builtin container and mathematical types. These members are compiler-provided on builtin types; user-defined `struct` and `class` methods are documented separately, and this feature does not change interfaces.

These compiler-provided builtin members are distinct from the user-defined class properties described in **Planned Properties (Not Implemented)**. Native builtin properties such as `List<T>.length` are implemented; user-defined properties remain planned only.

Native properties use field syntax and cannot be called:

```aether
List<int> xs = {1, 2, 3};
Vector<double> v = [3 4];
Matrix<double> A = [1 2; 3 4];

println(xs.length); // 3
println(v.length);  // 2
println(A.rows);    // 2
println(A.columns); // 2

xs.length(); // error: length is a property, not a method.
```

Native methods use call syntax and are desugared to the existing builtins by passing the receiver as the first argument:

```aether
List<int> ys = xs.copy(); // copy(xs)
xs.push(4);               // push(xs, 4)
int last = xs.pop();      // pop(xs)
xs.insert(1, 9);          // insert(xs, 1, 9)
int removed = xs.removeAt(0); // remove_at(xs, 0)
boolean found = xs.contains(9); // contains(xs, 9)
xs.clear();               // clear(xs)
int count = xs.size();    // length(xs)
xs.reverse();             // reverse(xs), mutates xs in place
xs.sort();                // sort(xs), mutates xs in place

Matrix<double> B = A.transpose(); // Math.LinearAlgebra.transpose(A)
double n = v.norm();           // Math.LinearAlgebra.norm(v)

xs.copy(xs); // error: copy(...) expects exactly one argument.
xs.copy;     // error: copy is a method and must be called.
```

Supported native properties:

- `List<T>.length -> int`
- `Vector<T>.length -> int`
- `Matrix<T>.rows -> int`
- `Matrix<T>.columns -> int`

Supported native methods:

- `List<T>.push(value: T) -> void`, appends `value`
- `List<T>.pop() -> T`, removes and returns the last element
- `List<T>.insert(index: int, value: T) -> void`
- `List<T>.removeAt(index: int) -> T`
- `List<T>.contains(value: T) -> boolean`
- `List<T>.indexOf(value: T) -> int`, returns the zero-based index of the first
  equal element, or `-1` when no element matches
- `List<T>.clear() -> void`
- `List<T>.size() -> int`
- `List<T>.copy() -> List<T>`
- `Array<T>.copy() -> Array<T>`
- `List<T>.reverse() -> void`, mutates the list in place
- `List<T>.sort() -> void`, mutates the list in place
- `Matrix<T>.transpose() -> Matrix<T>`
- `Vector<T>.norm() -> double`

List method indices are zero-based. `indexOf(value)` returns the first matching
index and returns `-1` for an empty list or when the value is absent. It uses
the same internal `Eq(T)` contract as `contains`, `==`, `!=`, structs and
nested Array/List values. It compares collection content recursively, never
reference identity. Classes, interfaces and callables do not define Eq, so
search over those element types is a static error. `insert(index, value)` accepts `0 <= index <= size()`, while
`removeAt(index)` accepts `0 <= index < size()`. `pop()` on an empty list and
out-of-range indices raise an `AetherRuntimeError`. Method arguments are checked
statically when their types are known: values passed to `push`, `insert`,
`contains`, and `indexOf` must be assignable to `T`, and indices must be `int`.

The functional builtins remain valid and keep the same signatures: `length(xs)`, `push(xs, value)`, `pop(xs)`, `insert(xs, index, value)`, `remove_at(xs, index)`, `contains(xs, value)`, `clear(xs)`, `copy(xs)`, `reverse(xs)`, `sort(xs)`, `rows(A)`, `columns(A)`, and `Math.LinearAlgebra.transpose(A)`/an explicit `from Math.LinearAlgebra import transpose` binding still work. The global `size(value)` builtin retains its existing shape-vector semantics; `List<T>.size()` specifically returns the list length as an `int`.

`const` follows the same mutation rules as the functional builtins. Read-only properties and non-mutating copy methods are valid on constants, while mutating methods are rejected when the receiver is rooted in a constant variable:

```aether
const List<int> xs = {1, 2};

println(xs.length); // ok
println(xs.contains(2)); // ok
println(xs.size()); // ok
List<int> ys = xs.copy(); // ok
xs.push(3);    // error: Cannot mutate constant 'xs'.
xs.pop();      // error: Cannot mutate constant 'xs'.
xs.insert(0, 3); // error: Cannot mutate constant 'xs'.
xs.removeAt(0); // error: Cannot mutate constant 'xs'.
xs.clear();    // error: Cannot mutate constant 'xs'.
xs.reverse(); // error: Cannot mutate constant 'xs'.
xs.sort();    // error: Cannot mutate constant 'xs'.
```

## Vectors And Matrices

Aether supports mathematical vector and matrix literals with MATLAB/Julia-like bracket syntax:

```aether
[1, 2, 3]      // Vector<int, Row>, length 3
[1; 2; 3]      // Vector<int, Column>, length 3
[1, 2; 3, 4]   // Matrix<int>, shape 2x2
[1, 2; 3.0, 4] // Matrix<double>, shape 2x2
```

Commas separate row-vector elements or matrix columns. Semicolons separate
column-vector entries or matrix rows. All matrix rows must have the same number
of columns. Elements must be homogeneous or numerically promotable:

- `int -> float`
- `int -> double`
- `float -> double`

Mixed incompatible elements are type errors:

```aether
[1 "x"]; // error
[1, 2; 3]; // error, ragged rows
```

### Planned Static Orientation

The full design for first-class `Vector<T, Row>`, `Vector<T, Column>`, and
`Matrix<T>` semantics is maintained in
[`AETHER_VECTOR_MATRIX_DESIGN.md`](AETHER_VECTOR_MATRIX_DESIGN.md). This
section records the v0 behavior and the planned static-orientation direction.

The future formal static model makes vector orientation part of the type:

```aether
Vector<int, Row> r = [1, 2, 3];
Vector<int, Column> c = [1; 2; 3];
```

`Vector<T, Row>` and `Vector<T, Column>` are different static types. The
orientation is not merely runtime metadata.

Bracket literals are target-typed. If a compatible expected type exists, the
literal is constructed as that type:

```aether
Vector<int, Row> r = [1, 2, 3];
Vector<int, Column> c = [1, 2, 3];

Matrix<int> A = [1, 2, 3]; // Matrix 1x3
Matrix<int> B = [1; 2; 3]; // Matrix 3x1
```

If there is no expected type, the literal form determines the type:

- `{...}` infers `List<T>`.
- `[a, b, c]` infers `Vector<T, Row>`.
- `[a; b; c]` infers `Vector<T, Column>`.
- `[a, b; c, d]` infers `Matrix<T>`.

Precedence rule: a compatible expected type wins. Without one, the syntactic
form determines the mathematical container.

Bracket literals also support Julia-style block concatenation for existing scalar, vector, transposed-vector, and matrix values:

```aether
A = [1 2; 3 4];
B = [5 6; 7 8];
[A B]        // [1 2 5 6; 3 4 7 8]
[A; B]       // [1 2; 3 4; 5 6; 7 8]
[A [9; 10]]  // [1 2 9; 3 4 10]
```

For block concatenation, vector orientation is respected: row vectors contribute `1xN` blocks and column vectors contribute `Nx1` blocks. Comma-separated matrix or vector blocks are intentionally not supported in v0:

```aether
[A];    // error
[A, B]; // error
```

Explicit mathematical types are:

```aether
Matrix<int> A = [1, 2; 3, 4];
Matrix<double> B = [1, 2; 3.0, 4];
Vector<int, Row> row = [1, 2, 3];
Vector<int, Column> col = [1; 2; 3];
Vector<double, Row> v = [1, 2.5, 3];
```

`Matrix<T>` accepts 2D matrix literals. In the planned static model, `Vector`
accepts an orientation parameter: `Vector<T, Row>` for row vectors and
`Vector<T, Column>` for column vectors.

`Matrix<int>` and `Vector<int, Orientation>` reject `double` values because
narrowing is not implicit. `Matrix<double>` and `Vector<double, Orientation>`
accept `int` and `double` values. `Matrix<string>` does not accept numeric
matrix literals.

Vectors and matrices are indexed with 1-based mathematical indexing. Lists are the 0-based collection type.

```aether
A = [1 2; 3 4];
println(A[1, 2]); // 2
A[2, 1] = 99;
println(A);       // [1 2; 99 4]

v = [10 20];
println(v[1]);    // 10
```

`rows(matrix)` and `cols(matrix)` return matrix dimensions as `int` values for 2D matrices:

```aether
println(rows([1 2; 3 4]));   // 2
println(cols([1 2; 3 4]));   // 2
```

`length(vector)` returns vector length. `rows(list)` and `cols(list)` are type errors.

`print(...)` and `println(...)` render `Matrix<T>` and `Vector<T>` values with a compact mathematical display format:

```aether
println([1 2 3]);        // [1 2 3]
println([1; 2; 3]);      // [1; 2; 3]
println([1 2; 3 4]);     // [1 2; 3 4]
println([1.0 2.5; 3 4]); // [1.0 2.5; 3.0 4.0]
println(["a" "b";
         "c" "d"]);      // ["a" "b"; "c" "d"]
println([true false;
         false true]);   // [true false; false true]
```

Runtime categories remain distinct: `List<T>` for general collections,
`Vector<T, Orientation>` for oriented mathematical vectors in the planned
static model, and `Matrix<T>` for 2D mathematical matrices. There is no
implicit conversion between `List<T>` and mathematical vectors.

Matrix and vector equality compares compatible mathematical values by
shape/length, orientation where applicable, and content. Incompatible element
types are type errors. Comparing `Matrix<T>` or a vector with a `List<T>` is an
`AetherTypeError`.

## Math.LinearAlgebra

Aether v0 introduces a first explicit mathematical namespace:

```aether
Math.LinearAlgebra.inner(u, v)
Math.LinearAlgebra.norm(v)
Math.LinearAlgebra.transpose(A)
Math.LinearAlgebra.matmul(A, B)
Math.LinearAlgebra.solve(A, b)
Math.LinearAlgebra.eig(A)
Math.LinearAlgebra.SVD(A)
Math.LinearAlgebra.LU(A)
Math.LinearAlgebra.LDU(A)
Math.LinearAlgebra.N(A)
Math.LinearAlgebra.R(A)
Math.LinearAlgebra.rank(A)
```

This namespace is a simulated builtin namespace for now, implemented through the Aether stdlib registry. Its full names are available only through a matching module binding.

Importing the module preserves qualified access; selective imports provide unqualified names:

```aether
import Math.LinearAlgebra;
S, D = Math.LinearAlgebra.eig(A);

from Math.LinearAlgebra import eig;
S2, D2 = eig(A);
```

`Math.LinearAlgebra.inner(u, v)` computes the usual Euclidean inner product:

```text
sum(u_i * v_i)
```

Both arguments must be mathematical vectors represented as `Matrix<T>` or `Vector<T>` values with shape `1xN` or `Nx1`. Row-row, column-column, row-column, and column-row combinations are valid when the effective lengths match. General matrices with both dimensions greater than one are errors.

Vector elements must be numeric: `int`, `float`, or `double`. `boolean` and `string` vector elements are errors. The result uses the existing numeric promotion rules:

```aether
println(Math.LinearAlgebra.inner([1 2 3], [4 5 6]));  // 32
println(Math.LinearAlgebra.inner([1; 2; 3], [4; 5; 6])); // 32
println(Math.LinearAlgebra.inner([1 2 3], [4; 5; 6])); // 32
```

These are errors:

```aether
Math.LinearAlgebra.inner([1 2; 3 4], [1 2; 3 4]);
Math.LinearAlgebra.inner([1 2 3], [1 2]);
```

`Math.LinearAlgebra.norm(v)` computes the induced Euclidean norm:

```text
sqrt(inner(v, v))
```

The argument rules are the same: `v` must be a numeric mathematical row or column vector, not a general matrix. The result is a `double` in the current implementation:

```aether
println(Math.LinearAlgebra.norm([3 4]));     // 5.0
println(Math.LinearAlgebra.norm([1 2 2]));   // 3.0
```

Basic real numeric builtins such as `sin(x)`, `cos(x)`, `exp(x)`, `ln(x)`, and `log(x)` are available globally and accept real numeric scalar arguments. Complex-aware scalar builtins are:

- `complex(x)` and `complex(real, imag)`
- `real(z)`
- `imag(z)`
- `conj(z)`
- `abs(z)`
- `angle(z)`
- `sqrt(z)`

`sqrt(real_non_negative)` returns `double`; `sqrt(negative_real)` and `sqrt(complex)` return `complex`.

`Math.LinearAlgebra.transpose(A)` returns a new transposed matrix:

```aether
println(Math.LinearAlgebra.transpose([1 2 3]));    // [1; 2; 3]
println(Math.LinearAlgebra.transpose([1; 2; 3]));  // [1 2 3]
println(Math.LinearAlgebra.transpose([1 2; 3 4])); // [1 3; 2 4]
```

The argument must be a mathematical `Matrix<T>` or `Vector<T>` with numeric elements. Scalar values and matrices with `boolean` or `string` elements are errors for this linear algebra builtin. `transpose` does not mutate the original value. Shape rules are:

- `1xN -> Nx1`
- `Nx1 -> 1xN`
- `MxN -> NxM`

`Math.LinearAlgebra.matmul(A, B)` computes standard matrix multiplication explicitly:

```text
if A is m x n and B is n x p, matmul(A, B) is m x p
```

Both arguments must be mathematical `Matrix<T>` or `Vector<T>` values with numeric elements. Scalar values and matrices with `boolean` or `string` elements are errors. The inner dimensions must match. Row and column vectors follow their matrix shapes:

```aether
println(Math.LinearAlgebra.matmul([1 2; 3 4], [5 6; 7 8])); // [19 22; 43 50]
println(Math.LinearAlgebra.matmul([1 2 3], [4; 5; 6]));     // 32
println(Math.LinearAlgebra.matmul([1; 2; 3], [4 5 6]));     // [4 5 6; 8 10 12; 12 15 18]
println(Math.LinearAlgebra.matmul([1 2; 3 4], [5; 6]));     // [17; 39]
println(Math.LinearAlgebra.matmul([1 2], [3 4; 5 6]));      // [13 16]
```

`matmul` returns a new matrix and does not mutate either operand. It uses existing numeric promotion rules: `int` with `int` remains `int`, combinations involving `float` or `double` widen as usual, and combinations involving `complex` produce `complex`.

The `*` operator is still not matrix multiplication in Aether v0. Matrix multiplication is available only through the explicit `Math.LinearAlgebra.matmul(A, B)` builtin.

Future `*` semantics for mathematical vectors must preserve static
orientation:

```aether
[1, 2, 3] * [4; 5; 6]
// Vector<T, Row> * Vector<T, Column> -> T

[1; 2; 3] * [4, 5, 6]
// Vector<T, Column> * Vector<T, Row> -> Matrix<T>
```

These expressions are not equivalent. Row-by-column multiplication is an inner
product, while column-by-row multiplication is an outer product.

`Math.LinearAlgebra.solve(A, b)` solves linear systems with Julia-like left-division semantics. The expression `A \ b` lowers to the same central solve builtin, so both forms share type rules, dimension validation, algorithm selection, and errors.

The `\` operator is syntactically part of the language but is semantically
available only after the executable module successfully imports the canonical
provider `Math.LinearAlgebra`. A module alias, importing any exported symbol
from that module, or importing the `LinearAlgebra` submodule from `Math` all
load the same provider identity and enable the operator. Without such an import,
the frontend reports an import diagnostic before execution.

The coefficient argument `A` must be a numeric mathematical matrix. The right-hand side `b` must be a numeric mathematical vector or matrix with `rows(b) == rows(A)`. Row-vector right-hand sides with matching length are treated as column vectors. The result is a `Matrix<double>`/`Vector<double>` for real systems, or `Matrix<complex>`/`Vector<complex>` when either `A` or `b` is complex:

```aether
A = [2 1; 1 3];
b = [1; 2];
import Math.LinearAlgebra;
println(A \ b); // [0.2; 0.6]

B = [2 4; 8 12];
println(Math.LinearAlgebra.solve([2 0; 0 4], B)); // [1.0 2.0; 2.0 3.0]
```

Square full-rank systems use a direct solve. Rectangular or rank-deficient systems use a least-squares/minimum-norm solution. No implicit narrowing to `int` is performed.

`Math.LinearAlgebra.eig(A)` computes a diagonalization of a square numeric matrix over the real or complex numbers. It returns a tuple `(S, D)` where the columns of `S` are eigenvectors and `D` is diagonal, so `A * S == S * D` up to floating-point tolerance:

```aether
import Math.LinearAlgebra
A = [1 1; 0 2];
S, D = eig(A);
```

The result uses `Matrix<double>` values when the factors are real and `Matrix<complex>` values when the input or the computed eigenstructure is complex. Matrices that are not square or are not diagonalizable are errors in Aether v0.

`Math.LinearAlgebra.SVD(A)` computes a full singular value decomposition of a real or complex numeric matrix. It returns a tuple `(U, S, V)` where `U` is `rows(A)xrows(A)`, `S` is `rows(A)xcols(A)`, and `V` is `cols(A)xcols(A)`, so `A == U * S * V'` up to floating-point tolerance:

```aether
import Math.LinearAlgebra
A = [3 2; 1 0; 0 0];
U, S, V = SVD(A);
println(U * S * V');
```

For complex inputs, `U` and `V` use `Matrix<complex>` and `S` remains `Matrix<double>` because singular values are real. Empty matrices are errors in Aether v0.

`Math.LinearAlgebra.LU(A)` computes an LU factorization of a square real or complex numeric matrix with row pivoting. It returns a tuple `(P, L, U)` where `P` is a real permutation matrix, `L` is unit lower-triangular, and `U` is upper-triangular, so `P * A == L * U` up to floating-point tolerance:

```aether
import Math.LinearAlgebra
A = [2 1; 4 5];
P, L, U = LU(A);
```

`Math.LinearAlgebra.LDU(A)` computes the corresponding LDU factorization. It returns `(P, L, D, U)` where `P` is a real permutation matrix, `L` is unit lower-triangular, `D` is diagonal, and `U` is unit upper-triangular, so `P * A == L * D * U` up to floating-point tolerance:

```aether
import Math.LinearAlgebra
A = [4 8; 2 6];
P, L, D, U = LDU(A);
```

For complex inputs, `P` remains `Matrix<double>` and the other factors use `Matrix<complex>`. Matrices that are not square are errors in Aether v0. `LDU` also requires nonzero diagonal pivots after the LU factorization, because the upper factor is normalized through the diagonal factor.

`Math.LinearAlgebra.N(A)` returns an orthonormal basis for the null space as columns. `Math.LinearAlgebra.R(A)` returns an orthonormal basis for the column space as columns. `Math.LinearAlgebra.rank(A)` returns the numeric matrix rank as an `int`:

```aether
import Math.LinearAlgebra
A = [1 im; 0 0];
K = N(A);
B = R(A);
r = rank(A);
```

For complex inputs, `N` and `R` return `Matrix<complex>`. For real inputs, they return `Matrix<double>`.

## Matrix Arithmetic

Aether supports `+` and `-` for numeric matrices with the same shape. Row vectors and column vectors are matrices, so shape still matters:

```aether
println([1 2 3] + [4 5 6]); // [5 7 9]
[1 2 3] + [1; 2; 3];        // error, 1x3 vs 3x1
```

General-purpose collections do not participate in matrix/vector arithmetic, and comparisons between lists and matrix/vector values are type errors.

Supported scalar operations are:

- `matrix * scalar`
- `scalar * matrix`
- `matrix / scalar`

The scalar must be numeric. Division is real division over each element.

The following remain intentionally unsupported:

- matrix-matrix `*` and `/`
- vector-vector `*` and `/`
- unqualified `dot(...)`
- matrix multiplication through operator `*`
- determinant
- inverse
- broadcasting
- slicing
- ranges
- operator overloading for matrix multiplication

## Scopes

Aether is block-scoped.

The following constructs create scopes:

- `if` blocks
- `else` blocks
- `while` blocks
- `for` blocks
- `try` blocks
- `catch` blocks
- functions

Variables created inside a block do not escape that block. Variables from outer scopes are visible and may be updated from an inner block. Shadowing is not allowed in v0.

```aether
x = 1;

if (true) {
    x = 2;
    y = 3;
}

println(x); // valid, prints 2
println(y); // error
```

Redeclaring a visible variable in an inner scope is an error:

```aether
int x = 1;

if (true) {
    double x = 2.5; // error: shadowing is not allowed
}
```

Function parameters and local variables live only inside the function call.

Functions and module-level type declarations are visible throughout their
module regardless of textual order. The frontend first registers enum,
interface, struct, class, and alias names; then resolves fields, constructors,
method signatures, and global function signatures; and only then checks
function, method, and constructor bodies. This permits forward calls, mutual
recursion, methods that call later methods, and signatures that mention types
declared later. Cyclic aliases and recursive by-value `struct` layouts are
rejected; references between `class` types do not form a value-layout cycle.

Local variables are different: they become visible only after their
declaration. Aether does not hoist locals, loop variables, or block variables.
Module-level variable and constant initializers also retain their existing
sequential evaluation rules; only their already-declared bindings are visible.

## Control Flow

`if`:

```aether
if (condition) {
    println("yes");
}
```

`if` / `else`:

```aether
if (condition) {
    println("yes");
} else {
    println("no");
}
```

`while`:

```aether
while (x < 10) {
    x = x + 1;
}
```

`break` and `continue` are supported inside `for` and `while` loops:

```aether
for (i in 1:10) {
    if (i == 5) {
        break;
    }
    println(i);
}

while (true) {
    continue;
}
```

`break` exits only the innermost loop. `continue` advances only the innermost loop. Using either statement outside a loop is an `AetherTypeError`:

```aether
break;    // error: break used outside of a loop.
continue; // error: continue used outside of a loop.
```

Labeled breaks and labeled loops are not part of v0.

For Array/List collection loops, the iteration name is a read-only borrow of
the current element:

```aether
for (Transaction transaction in transactions) {
    println(transaction.amount);
}
```

Starting a loop iteration does not logically copy or retain the element. The
name cannot be reassigned, used to mutate a value-type element, or used to
mutate a nested collection through that path. A normal declaration such as
`Transaction saved = transaction` copies the struct; for Array/List/class/string
elements it copies the handle with its normal lifecycle. Returns and owning
stores likewise acquire ownership before the per-iteration borrow ends.
Structurally modifying or setting the iterated collection is rejected for the
direct receiver and simple local aliases known by the typechecker. There is no
public borrow syntax, mutable iterator object, or general alias analysis.

Conditions must be `boolean`. Numeric and string values are not accepted as conditions.

```aether
if (1) {
    println("bad");
} // error
```

`throw` raises an Aether language exception and stops normal execution of the current statement path:

```aether
throw Exception("algo salio mal");
throw "algo salio mal"; // shorthand; wrapped as Exception(message)
```

The thrown expression must be `string` or `Exception`. Throwing a string creates an `Exception` value whose `message` field is that string. Throwing any other type is an `AetherTypeError`.

`try` / `catch` handles one exception value:

```aether
try {
    risky();
} catch (e) {
    println(e.message);
}
```

The catch variable is local to the `catch` block and has type `Exception`. If the `try` block completes normally, the `catch` block is skipped. If the `try` block throws, the rest of that block is skipped and the `catch` block runs. A `throw` inside the `catch` propagates outward. `return`, `break`, and `continue` keep their usual behavior inside `try` and `catch`.

An uncaught language exception reaches the runner as an `AetherRuntimeError` whose message is the exception message. Aether v0 does not implement `finally`, multiple catches, exception hierarchies, stack traces, or generic exception types.

## Functions

Block functions are typed and have typed parameters. They are intended for complex logic.

```aether
int add(int a, int b) {
    return a + b;
}
```

Rules:

- The return type is required for block-bodied functions. A single-expression
  declaration may infer it as described below.
- Parameters must be typed.
- The official declaration form is `<return_type> <name>(params) { ... }`.
- The old `function <return_type> ...` form is legacy/deprecated and kept only for temporary compatibility.
- Non-`void` functions require a return value on all evident paths.
- `void` functions may end without a `return` and may use `return;` for early exit.
- `void` is only valid as a block function return type. It is not a variable, parameter, tuple, collection, matrix, or vector element type.
- Calls to `void` functions are valid only as statements; they cannot be assigned, passed as arguments, returned from non-`void` functions, or used inside expressions.
- Return values must match the declared return type, allowing safe widening.
- Function call arity is checked.
- Function argument types are checked, allowing safe widening.
- A module-level function may be called before its textual declaration.
- Direct and mutual recursion are supported for typed block functions.
- Duplicate parameter names are not allowed.
- Duplicate global function names are not allowed in v0.

### Typed top-level callables

A capture-free block function may be used as a value when its exact structural
signature is known. Callable types use the return-type-first spelling already
used by declarations:

```aether
double square(double x) { return x * x; }

double apply(double(double) operation, double value) {
    return operation(value);
}

int main() {
    double(double) saved = square;
    return int(apply(saved, 4.0));
}
```

The textual form is `ReturnType(ParameterType, ...)`; therefore `void()` is a
zero-argument procedure, `double(double)` maps one `double` to `double`, and
`boolean(int, double)` takes two ordered parameters. Type aliases may name a
callable. Compatibility is exact: parameter count, each parameter type in
order, and return type must all match. Callable signatures do not apply the
ordinary numeric widening rules.

Callable values may flow through local variables, parameters and control-flow
merges. They may refer to a visible user-defined top-level block function in
the same module or through a full/selective import and alias. A local variable
shadows a function name. Duplicate function names are already rejected, so v0
has no overload set or ambiguous-overload selection rule.

This first representation contains only the resolved function identity and
signature; it has no captured environment. LLVM/native represents it as a
typed function pointer and performs an indirect call with the existing
parameter/return ABI, including `void` and supported structs by value.

The following remain unsupported: callable return types, closures, lambdas,
anonymous or nested function values, capture, bound instance methods,
builtin functions as values, partial
application, variadic callables, and unspecialized generic functions. A
top-level typed wrapper may be used when a builtin needs to be passed.

Functions with a single expression may abbreviate their body with `=`:

```aether
double f(double x) = x^2 + 1.0;
g(double x, double y) = x^2 + y^2;
```

Parameters always require explicit types. The return type may be written before
the name or omitted and inferred from the expression. Before type checking, the
parser desugars the declaration to a normal `FunctionDeclaration` with one
`return`; AST consumers, IR, SSA, and LLVM require no separate representation.
The expression may call builtins and read globals under the same scope rules as
a block function:

```aether
int a = 2;
f(double x) = sin(x)^2 + cos(x)^2;
g(int x) = a*x + 1;

println(f(0.0)); // 1.0
println(g(3));   // 7
```

The `=` form admits exactly one expression followed by `;`. It is declaration
sugar, not a lambda, closure, anonymous function, or new function-value form.
Abbreviated and block functions share the same global function namespace;
redefining a function name is an `AetherTypeError`.

Valid widening:

```aether
double f() {
    return 2;
}
```

Invalid return:

```aether
int f() {
    return 2.5;
}
```

Invalid missing return:

```aether
int f(int x) {
    if (x > 0) {
        return x;
    }
} // error: may not return on all paths
```

Valid `void` procedure:

```aether
void emit(int x) {
    if (x < 0) {
        return;
    }
    println(x);
}

emit(3);
```

Valid evident return:

```aether
int f(int x) {
    if (x > 0) {
        return x;
    } else {
        return 0;
    }
}
```

## Builtins

Aether v0 recognizes these builtins:

- `print(...)`
- `println(...)`
- `length(list_or_vector)`
- `is_empty(list)`
- `copy(list)`
- `push(list, value)`
- `pop(list)`
- `insert(list, index, value)`
- `remove_at(list, index)`
- `contains(list, value)`
- `clear(list)`
- `reverse(list)`
- `sort(list)`
- `rows(matrix)`
- `cols(matrix)`
- `sin(x)`
- `cos(x)`
- `tan(x)`
- `exp(x)`
- `ln(x)`
- `log(x)`
- `sqrt(x)`
- `abs(x)`
- `Math.mod(a, b)`
- `Math.LinearAlgebra.inner(u, v)`
- `Math.LinearAlgebra.norm(v)`
- `Math.LinearAlgebra.transpose(A)`
- `Math.LinearAlgebra.matmul(A, B)`
- `Math.LinearAlgebra.solve(A, b)`
- `Math.LinearAlgebra.eig(A)`
- `Math.LinearAlgebra.SVD(A)`
- `Math.LinearAlgebra.LU(A)`
- `Math.LinearAlgebra.LDU(A)`
- `Math.LinearAlgebra.N(A)`
- `Math.LinearAlgebra.R(A)`
- `Math.LinearAlgebra.rank(A)`
- `System.args()` (requiere `import System;`)
- `io.readText(path)`, `io.writeText(path, content)`,
  `io.writeTextAtomic(path, content)` e
  `io.appendText(path, content)` (requieren `import io;`)

Side-effect builtins such as `print(...)`, `println(...)`, and plotting commands return `void`, except `savefig(...)`, which returns the output path as a `string`.
- `int(...)`
- `float(...)`
- `double(...)`
- `string(...)`
- `boolean(...)`

`print` and `println` accept one or more arguments. `print` does not add a newline. `println` adds one newline.

```aether
print("x = ");
println(x);
```

`array(...)` is not a recognized builtin in Aether v0.

`length(...)` accepts `List<T>` and `Vector<T>` values and returns an `int`.

`copy(...)`, `is_empty(...)`, `push(...)`, `pop(...)`, `insert(...)`, `remove_at(...)`, `contains(...)`, `clear(...)`, `reverse(...)`, and `sort(...)` accept `List<T>` values. `copy(...)` returns a shallow copy of the list container. `push`, `insert`, and `contains` require a value assignable to `T`. `insert` and `remove_at` require an `int` index and use 0-based indexing. `push`, `pop`, `insert`, `remove_at`, `clear`, `reverse`, and `sort` reject mutation through a `const` list variable. `sort` orders ascending and currently supports only `List<int>`, `List<double>`, and `List<string>`.

`rows(matrix)` and `cols(matrix)` accept one `Matrix<T>` argument and return `int` dimensions.

`sin(x)`, `cos(x)`, `tan(x)`, `exp(x)`, `ln(x)`, and `log(x)` accept one real numeric scalar and return `double`. `sqrt(x)` returns `double` for non-negative real inputs and `complex` for negative or complex inputs. `abs(x)` preserves real input type, uses checked i32 overflow for `int`, and returns `double` for `complex`. `real(x)`, `imag(x)`, `conj(x)`, and `angle(x)` are experimental complex-aware builtins. `Math.mod(a, b)` accepts two real numeric scalars and returns floor/Python-like modulo. `Math.floor(x)` and `Math.ceil(x)` return `int` and reject non-finite or out-of-range results. `Math.factorial(x)` accepts a non-negative `int` and is checked for i32 overflow.

Real scalar math follows IEEE-754 without consulting `errno` where the public contract remains real: invalid logarithm domains produce NaN, logarithm of zero produces negative infinity, and exponential overflow produces positive infinity. Negative real `sqrt` retains the legacy complex result. Operations whose public result is `int` retain checked panics because NaN, infinity, and out-of-range values have no representable result.

The only current mathematical constant is `Math.pi`, with exact language type `double`; aliases and selective imports preserve that identity. It lowers as an immediate constant and requires neither a runtime global nor module initialization. There is no global `PI` and no `E` constant in Aether v0.

`Math.LinearAlgebra.inner(u, v)`, `Math.LinearAlgebra.norm(v)`, `Math.LinearAlgebra.transpose(A)`, `Math.LinearAlgebra.matmul(A, B)`, `Math.LinearAlgebra.solve(A, b)`, `Math.LinearAlgebra.eig(A)`, `Math.LinearAlgebra.SVD(A)`, `Math.LinearAlgebra.LU(A)`, `Math.LinearAlgebra.LDU(A)`, `Math.LinearAlgebra.N(A)`, `Math.LinearAlgebra.R(A)`, and `Math.LinearAlgebra.rank(A)` are explicit simulated-namespace builtins for numeric mathematical vectors and matrices. See `Math.LinearAlgebra` above.

## Errors

Aether has its own error hierarchy:

- `AetherSyntaxError`: invalid syntax or malformed source.
- `AetherTypeError`: static semantic errors and type errors.
- `AetherRuntimeError`: runtime failures that are not caught statically.

The typechecker is expected to catch semantic errors before execution whenever possible, including undefined variables, undefined functions, invalid argument counts, invalid argument types, invalid conditions, and invalid returns.

## Pipeline

Aether v0 runs through this pipeline:

```text
Lexer -> Parser -> TypeChecker -> EntryPointNormalizer -> AST/IR/SSA/LLVM
```

Entry-point normalization runs after semantic checks so diagnostics keep their
original user source locations. The synthetic nodes are therefore absent from
user-visible symbols, completion, formatting, and documentation. The AST
interpreter and compiled backends consume the same normalized executable
program.

## Executable Entry Point

An executable `.ae` entry file uses exactly one of two equivalent forms. In
script mode, executable top-level statements are wrapped in an internal,
synthetic entry function:

```aether
println("Hola");
```

Alternatively, the file may declare one explicit entry function. Its only
valid signature is `int main()`; parameters, `void main()`, other return types,
and duplicate/overloaded `main` declarations are errors:

```aether
int main() {
    println("Hola");
}
```

Reaching the end of `main` returns `0`. This exception applies only to `main`;
every ordinary non-void function must still return on all paths. An explicit
return becomes the process/backend exit code, while a panic remains a distinct
failure with exit code `1`.

An explicit `main` cannot be combined with executable top-level statements.
Top-level declarations such as helper functions and constants remain valid;
constant initialization is normalized into the entry function for compiled
execution. A top-level `return` is invalid and is never interpreted as a return
from the synthetic entry point.

This guarantee applies to the executable entry file. Native compilation accepts
the declaration-only subset of file modules (supported functions and structs,
including aliases and selective imports) by combining checked modules into one
IR module. Globals/constants and executable top-level statements in imported
modules remain AST-only and receive an early capability diagnostic; native does
not invent module initialization semantics for them.

Process arguments do not change this signature. After `import System;`,
`System.args()` accepts zero arguments and returns a fresh owned
`Array<string>` snapshot in process order. Each call creates an independent
mutable Array and independently owned string objects, in `O(argc)` time.
Arguments are UTF-8 and never include the executable name. Process transports
cannot represent embedded NUL; this is an operating-system boundary, not a
restriction on ordinary Aether strings.

Text files use the explicit UTF-8-only `io` API. `readText` returns
`FileReadResult { string content; FileStatus status; }`; failures carry empty
content and callers must inspect status. `writeText` creates/truncates and
`appendText` creates/appends exact `byteLength` bytes without adding newlines.
`writeTextAtomic` writes the same exact bytes to a secure same-directory
temporary, fsyncs it, atomically renames it, and fsyncs the parent directory.
An error after rename can leave the new file visible with unconfirmed metadata
durability; no rollback is attempted.
Empty paths and paths containing NUL return `InvalidPath`. No operation expands
or normalizes paths, and this surface does not include binary files, streams or
directories. Native support is currently limited to Linux/POSIX; Windows paths
require a future explicit UTF-16 conversion.

## Script and Session Execution

`run_aether(source)` executes in a fresh Aether session each time, so globals do not persist across calls.

`AetherSession` provides REPL/session execution with persistent global variables and function definitions across `run(source)` calls. Each call still uses the same pipeline (`Lexer -> Parser -> TypeChecker -> Interpreter`). Failed runs roll back the session to its previous committed state, so errors do not destroy earlier variables or functions.

The `.ae` editor now selects an `Aether REPL` panel backed by a persistent `AetherSession`. The `Restart REPL` control creates a fresh session. Aether does not auto-print expression statements yet; use `print(...)` or `println(...)` for visible output.

## Command-Line Interface

The official command-line entrypoint treats a source file as the default
operation:

```bash
aether hello.ae
```

The explicit run spelling and program-argument separator are:

```bash
aether run hello.ae -- one "two words" --flag
```

Only the values after the first `--` reach `System.args()`. Aether does not
reparse shell quoting or interpret those values as compiler flags. Without
`--`, the program receives zero arguments.

This executes the same canonical pipeline used by `AetherSession`. A persistent
interactive session is available with:

```bash
aether --repl
```

The following inspection modes expose intermediate language structures for
compiler/runtime development without executing the program:

```bash
aether --tokens hello.ae
aether --ast hello.ae
```

`aether --version` reports the current language version and `aether --help`
lists the active interface. Future commands such as `test`, `fmt`, and
`package`, and an `--ir` inspection mode, are reserved for later work and are
not implemented in v0.

## Editor Integration

`.ae` files are the active Aether script format in the editor and use the persistent Aether REPL for interactive input. Legacy `.mtx`, `.mtex`, and `.mtn` workflows are outside the active Aether Studio surface. A basic Aether LSP server exists for diagnostics and completions; a full IDE protocol feature set is not part of v0.

## Not Implemented Yet

The following are intentionally not implemented in Aether v0:

### Tensors and Matrices

- Full ND tensors (only 1D vectors and 2D matrices are supported)
- Multidimensional slicing (only 1D vector slicing with `:` is supported; matrix slicing is not available)
- Broadcasting semantics (implicit dimension expansion for operations)
- Slice assignment (reading slices works; assignment to slices does not)

### Language Features

- Comprehensions (list, generator, etc.)
- Generics (aliases of generic types like `Vector<double>` work; generic type parameters for custom structs do not)
- Advanced exceptions (`finally`, multiple catches, hierarchies, stack traces)
- JIT compilation
- Multi-file packages (each package maps to one `.ae` file)
- Import aliases and specific imports (`import X as Y`, `from X import Y`)

### Ecosystem

- Rust core (currently Python-based)
- Full LSP feature set
- Formatter
- Notebooks `.aen`
- Documents `.aed`
- Package manager
- Integer division `//`

## Design Philosophy

Aether combines a Java/C-like surface syntax with `{}` blocks and explicit type syntax, plus comfortable inference inspired by Julia.

The language is intended for scientific and computational work. Numeric behavior favors predictable real arithmetic, explicit casts for lossy conversions, and early semantic errors whenever possible.

The current Python implementation is a prototype and executable specification. It is deliberately structured around clear lexer, parser, AST, typechecker, scope, and interpreter stages so the core can later be ported to Rust without depending on PyQt or legacy document/runtime pipelines.
