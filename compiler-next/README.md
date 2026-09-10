# Aether native compiler — OOP-V1


## Concrete class identity and lifecycle (OOP-V1)

The native Linux x86-64 bootstrap admits concrete non-generic classes with
non-null owning handles, shared identity, non-atomic strong ARC and direct
instance methods. Class handles are **not Copy**: an owning lvalue aliases
(retains once), while a fresh result transfers its ownership. Structs retain
their existing inline value semantics.

```aether
class Counter {
    int value;
    public init(int value) { this.value = value; }
    public mut int increment() { value = value + 1; return value; }
    public int get() { return value; }
}
int main() {
    Counter a = Counter(0);
    Counter b = a;
    b.increment();
    return a.get(); // 1: both handles identify the same object
}
```

Members default to private; classes default to module-internal. `public class`
permits imported use. Read receivers are the default; receiver-derived writes
require a declared `mut` method. Every method call acquires a receiver keepalive
before evaluating arguments; fresh read receivers transfer their existing token.
`==` and `!=` compare object identity for the same concrete class.

A nonempty class requires one `init` that initializes every field before
publication. Empty classes may omit `init`. Fields admit supported primitive
scalars, aliases, finite concrete Copy/no-drop value types with available layout,
and a private `Buffer<int>`. The last release destroys owning fields in reverse
declaration order and frees the object. Initializers have no source result or
value return; `this` is a nonescaping borrowed receiver.

Inheritance, interfaces, generic classes, class graph fields, class-containing
aggregates/containers/generic applications, interior refs/views, class-slot refs,
nullable handles and user destructors remain outside this admission. Mut methods
require an addressable writable receiver. Temporary field access is rejected;
`Counter(0).get()` is supported. Initializer loops cannot establish new field
initialization, and owning-field initialization must agree at branch joins.

HIR/MIR/SSA expose and independently verify class identity, Alias/Transfer,
publication, receiver capability, keepalive and cleanup. LLVM uses a private
one-pointer handle and an eight-byte strong-count header; no public class ABI
is promised. Programs without class use acquire no ARC runtime.

See [the OOP-V1 report](../docs/architecture/OOP_V1_REPORT.md) for exact counter,
corruption, regression and O0/O2 evidence. [OOP-ARCH-1](../docs/architecture/OOP_ARCH_1.md)
remains the broader design. Run `cargo test -p aether-driver --test oop_v1` for
the qualification and `python3 tests/measure-oop-v1.py --runs 7` for descriptive
native cost samples. Executable examples are in `tests/programs/oop_v1_*.ae`.

## Program entry and source comments

The entry module selects exactly one non-generic `int main()` with zero
parameters. `int` is canonical int64; existing transparent spellings such as
`int64` and user aliases remain equivalent. Only that resolved entry function
gets an implicit `return 0;` when normal control flow reaches its closing brace.
Explicit returns remain valid and preserve their exit codes. Ordinary functions,
including imported functions named `main`, still require explicit returns on
every reachable path. There is no script mode, top-level execution or global
executable initialization.

```aether
// program entry
int main() {
    /* No explicit return is required here. */
}
```

`//` skips through the line ending or EOF; `/* ... */` skips through the first
closing delimiter and does not nest. Comments are whitespace between tokens,
never semantic nodes. An unterminated block comment produces lexer error E0002
at its opening `/*`. Spans retain original UTF-8 byte offsets and source IDs;
diagnostic lines and character columns come from the unchanged source. LF and
CRLF remain supported. Division/multiplication and contiguous multi-character
operators retain their tokenization. Strings remain outside the admitted slice.

HIR shows an ordinary zero return marked `compiler_generated: true`, located
at the closing brace and inserted before ownership cleanup. MIR/SSA/LLVM reuse
ordinary returns; no runtime helper or backend fallthrough rule is added.
See [LANGUAGE_PARITY_1_REPORT.md](../docs/architecture/LANGUAGE_PARITY_1_REPORT.md)
for native exit-code, equivalence, diagnostic and regression evidence.

## Mathematical architecture consolidation

MATH-ARCH-1 consolidates the mathematical architecture through V33 without
adding source features. Native multiplication resolves through
`Analyzer::resolve_native_multiplication` in `hir/mathematical.rs`; HIR uses
`AlgebraicProduct` / `AlgebraicProductKind`, and MIR/SSA use
`AlgebraicProductKernel`. Elementwise and algebraic kernels retain separate
closed recipes and independent verification at both boundaries. Shared
mathematical modules own kernel vocabulary, stride reads and Matrix shape
construction. Checked integers, strict IEEE reductions, borrowed inputs, fresh
results and zero-axis allocation behavior remain the reference semantics.

See [the consolidation report](../docs/architecture/MATH_ARCH_1_REPORT.md) for
the authority inventory, qualification, LLVM equivalence, and native-core versus
future `LinearAlgebra` STD boundary. Numbered sections below remain historical
feature-admission records; their internal names describe the original milestone.

This directory is the isolated Rust implementation of the first reconstruction
slice. The current mathematical foundation includes Matrix<T> owners and borrowed strided MatrixView/MatrixViewMut and oriented VectorView/VectorViewMut with zero-copy transpose; the numbered
Vertical-9..17 sections below retain historical qualification context.
It does not replace the production `aether` CLI or import any legacy
Python object, JSON schema, Initial IR, or SSA representation.

## Native Matrix×Matrix multiplication (V33)

```aether
Matrix<T> multiply<T:Storable+Copy+Add+Mul+Zero>(
    MatrixView<T> a, MatrixView<T> b) {
    return a * b;
}
```

The complete native `*` table through V33 is:

| Operands | Result | Compatibility |
|---|---|---|
| scalar × Vector, Vector × scalar | owning Vector, same orientation | exact scalar/element T |
| scalar × Matrix, Matrix × scalar | owning Matrix | exact scalar/element T |
| Row(n) × Column(n) | T | equal dimensions |
| Column(n) × Row(p) | owning Matrix(n,p) | independent dimensions |
| Matrix(m,k) × Column(k) | owning Column(m) | matrix columns = vector dimension |
| Row(k) × Matrix(k,n) | owning Row(n) | vector dimension = matrix rows |
| Matrix(m,k) × Matrix(k,n) | owning Matrix(m,n) | left columns = right rows |

Both Matrix operands independently accept Matrix, MatrixView and MatrixViewMut,
with exact same canonical element T and no promotion. Owners are borrowed;
mutable views are read only for this operation. Inputs may share backing, remain
usable afterwards, and evaluate left to right with the left owner protected
while evaluating the right. Temporary owners receive normal cleanup.

Output rows = lhs.rows, output columns = rhs.columns, contraction = lhs.columns.
Each output starts at exact Zero<T>, iterates contraction indices in increasing
logical order, then stores once. Output traversal is rows, then columns, then
contraction. Integers use checked multiplication and checked addition without
widening. Floats use canonical +0 and separate strict fmul/fadd: no FMA,
reassociation, fast-math, BLAS or SIMD. Generic T independently requires
Storable+Copy+Add+Mul+Zero, including unused bodies and generic forwarding.
Operations and Zero become concrete before MIR; no capability dispatch exists.

Shape mismatch is diagnosed statically when known or traps before the empty
bypass, allocation, loads and arithmetic. For m×0 times 0×n, the result still
contains m*n zeros: one allocation if m,n>0, m*n stores, no loads/Mul/Add. Zero
output rows or columns allocate nothing and preserve exact 0×n/m×0 shape with
a null pointer. Matrix(1,k)×Matrix(k,1) is Matrix(1,1), never the scalar returned
by Row×Column. Allocation checks only m*n and its byte size, before source reads.

Logical addressing uses i*lhs.row_stride+l*lhs.column_stride and
l*rhs.row_stride+j*rhs.column_stride independently, including either or both
transposed views. Result stores use i*n+j. No row()/column() adaptation or
transpose materialization occurs. General exact costs: m*k*n Mul, m*k*n Add,
2*m*k*n loads, m*n stores, one allocation iff m,n>0. Free/relocation deltas
inside the successful product are zero; normal cleanup balances allocations.

HIR retains explicit MatrixAlgebraicProduct metadata. MIR and SSA each validate
the concrete MatrixMatrixKernel three-axis schedule before LLVM emits loops.
Matrix×Row, Column×Matrix, Row×Row and Column×Column remain rejected. No dot,
Hadamard, matmul function, user impl or lifetime extension is introduced.
Advanced decompositions remain future STD LinearAlgebra work.

See [the V33 report](../docs/architecture/NEXT_VERTICAL_33_REPORT.md) and
[the normative contract](../docs/architecture/AETHER_V1_SEMANTIC_CONTRACT.md#next-vertical-33--native-matrixmatrix).
Compilation snapshots: `python3 tests/measure-v33.py --runs 10`.
The numbered sections below describe admission at their original boundaries.

## Native Matrix×Column and Row×Matrix multiplication (V32)

```aether
Vector<T,Column> apply<T:Storable+Copy+Add+Mul+Zero>(
    MatrixView<T> a, VectorView<T,Column> x) {
    return a * x;
}
Vector<T,Row> apply_row<T:Storable+Copy+Add+Mul+Zero>(
    VectorView<T,Row> r, MatrixView<T> a) {
    return r * a;
}
```

The complete native mathematical `*` table through V32 is:

| Operands | Result | Compatibility |
|---|---|---|
| scalar × Vector, Vector × scalar | owning Vector, same orientation | exact scalar/element T |
| scalar × Matrix, Matrix × scalar | owning Matrix | exact scalar/element T |
| Row(n) × Column(n) | T | equal dimensions |
| Column(n) × Row(p) | owning Matrix(n,p) | independent dimensions |
| Matrix(m,n) × Column(n) | owning Column(m) | matrix columns = vector dimension |
| Row(m) × Matrix(m,n) | owning Row(n) | vector dimension = matrix rows |

Both new products accept every readable owner, view and mutable-view combination,
require exact canonical same T, and borrow inputs without consuming or copying
backing. Matrix offsets use logical `i*row_stride+j*column_stride`; vectors use
`k*stride`. Transposed MatrixView and strided VectorView work simultaneously.
Orientation comes from types, never strides or a runtime dimension-one shortcut.

Each output starts from Zero<T> (integer zero or floating +0), visits contraction
indices in increasing logical order, and performs one multiplication followed by
one addition per term. Integer operations are checked without widening; floating
operations are separate strict fmul/fadd without FMA, reassociation or fast-math.
Generic T independently requires Storable+Copy+Add+Mul+Zero. Unused bodies and
forwarding are checked before operations and Zero concretize for MIR.

Shape mismatch is diagnosed statically when known, otherwise traps before result
allocation or element access. The result extent alone controls allocation:
Matrix(m,0)×Column(0) yields m zeros; Row(0)×Matrix(0,n) yields n zeros. These
nonempty results allocate once and perform zero Mul/Add. Matrix(0,n)×Column(n)
and Row(m)×Matrix(m,0) yield canonical null/zero Vector descriptors without
allocation. Each nonempty output is stored exactly once. In general both
products execute m*n Mul and m*n Add, with m stores for Matrix×Column and n for
Row×Matrix, and exactly one allocation iff the result extent is nonzero.

MIR/SSA retain independently verified MatrixColumnKernel/RowMatrixKernel closed
maps of reductions with explicit result/contraction selectors. LLVM translates
them to nested loops and the normal `{ptr,dimension}` Vector owner layout.
At the V32 boundary Matrix×Matrix was still deferred; V33 admits it above.
Matrix×Row, Column×Matrix, Row×Row, Column×Column, dot, Hadamard,
matmul function, BLAS and user impl remain unimplemented. Advanced decompositions remain
future LinearAlgebra STD work.

See [the V32 report](../docs/architecture/NEXT_VERTICAL_32_REPORT.md) and
[the normative contract](../docs/architecture/AETHER_V1_SEMANTIC_CONTRACT.md#next-vertical-32--native-matrixcolumn-and-rowmatrix).
Compilation snapshots: `python3 tests/measure-v32.py --runs 10`.
The numbered sections below describe admission at their original boundaries.

## Native algebraic Vector multiplication (V31)

```aether
T inner<T:Copy+Add+Mul+Zero>(VectorView<T,Row> r, VectorView<T,Column> c) {
    return r * c;
}
Matrix<T> product<T:Storable+Copy+Mul>(VectorView<T,Column> c, VectorView<T,Row> r) {
    return c * r;
}
```

Row(n) represents 1×n, including Row(0)=1×0; Column(n) represents n×1,
including Column(0)=0×1. Native Row×Column returns exactly T after checking
matching dimensions. It starts from canonical Zero<T> and executes n ordered
multiplications and n additions, with no allocation. Column(n)×Row(m) returns
an owning Matrix<T> of exactly n×m, including 0×m and n×0. It performs n*m
multiplications/stores, with one nonempty backing allocation and none for empty
results. Row×Row and Column×Column remain invalid.

Zero is a separate algebraic value guarantee, satisfied only by built-in
integers/floats and their transparent aliases. It implies no binary behavior or
storage property. All readable owner/view/mutable-view combinations preserve
orientation, independent strides and input usability. Inner views require
Copy+Add+Mul+Zero without Storable; outer needs Storable+Copy+Mul without Add or
Zero. Unused generic bodies and forwarding are checked before instantiation.

HIR represents symbolic behaviors and Zero explicitly, then concretizes them
before MIR. MIR and SSA independently verify closed ReductionKernel and
OuterProductKernel schedules. LLVM emits checked integers or strict separate
fmul/fadd, with no FMA, reassociation, fast-math or runtime capability dispatch.
The initial positive-zero addition is observable and is never omitted.

No dot(Vector,Vector), outer()/matmul() function, Hadamard, Matrix products,
One, user implementations, widened accumulator or generic orientation is added.
`dot` remains a possible future Array/List sequence operation. Existing consuming
transpose is unchanged; transpose_view changes orientation without consuming.
See [the V31 report](../docs/architecture/NEXT_VERTICAL_31_REPORT.md) and the
[normative contract](../docs/architecture/AETHER_V1_SEMANTIC_CONTRACT.md#next-vertical-31--algebraic-zero-and-native-vector-multiplication).
Compilation snapshots: `python3 tests/measure-v31.py --runs 10`.
Historical version sections below describe admission at their original boundary.

## Generic mathematical arithmetic kernels (V30)

```aether
Vector<T,Row> addRows<T:Storable+Copy+Add>(
    ref Vector<T,Row> a, ref Vector<T,Row> b) { return *a + *b; }
Vector<T,Column> subtractColumns<T:Storable+Copy+Sub>(
    VectorView<T,Column> a, VectorView<T,Column> b) { return a - b; }
Matrix<T> scale<T:Storable+Copy+Mul>(T scalar, MatrixView<T> m) {
    return scalar * m;
}
```

V30 extends V27/V28 arithmetic to symbolic element T. Addition requires
`Storable + Copy + Add`, subtraction `Storable + Copy + Sub`, and scaling
`Storable + Copy + Mul`. These are independent obligations: Storable permits
owning result storage; Copy permits non-destructive reads from borrowed elements
and repeated scalar use; the behavior proves exactly `T op T -> T`. No behavior
implies Copy or Storable. Missing guarantees are diagnosed during parametric
checking, including unused bodies and forwarding callers, before instantiation.

All existing readable owner/view/mutable-view families work, with exact Row or
Column orientation. Orientation itself cannot be generic. Owners remain
non-Copy and arithmetic leaves them usable. Explicit refs require `*a` in the
body and `&a` at the call; no auto-borrow/deref is introduced. Borrowed views
remain non-Storable even when their element T guarantees Storable.

HIR kernel metadata is `MathElementOp::Behavioral(Add/Sub/Mul)` for symbolic T,
`Concrete(HirBinaryOp)` for built-in scalars. Verification checks independent
capabilities, source operator, family, result, orientation and read-only inputs.
V29's concretization authority resolves the metadata during substitution;
concrete HIR rejects residual behavior. MIR/SSA retain the exact existing
concrete ElementwiseKernel, and LLVM retains checked integer intrinsics and
IEEE fadd/fsub/fmul without fast-math, dictionaries or hidden operator arguments.

Shape guards, logical strides, contiguous result initialization and allocation
rules remain V27/V28's. Generic column projections and transposed MatrixView
kernels honor descriptor strides. Empty kernels allocate nothing; scaling still
evaluates its scalar. User nominal operators, heterogeneous contracts, generic
orientation, dot/outer/matmul, identities, in-place operations and lifetimes are
outside this vertical. The sections below describe their historical versions.
See [the V30 report](../docs/architecture/NEXT_VERTICAL_30_REPORT.md).
Compilation snapshots: `python3 tests/measure-v30.py --runs 10`.

## Behavioral scalar generic capabilities (V29)

```aether
T add<T:Add>(T a, T b) { return a + b; }
T subtract<T:Sub>(T a, T b) { return a - b; }
T multiply<T:Mul>(T a, T b) { return a * b; }
T affine<T:Add + Mul>(T a, T b, T c) { return a * b + c; }
T forward<T:Add>(T a, T b) { return add(a, b); }
struct Holder<T:Add> { T value; }
```

`Add`, `Sub` and `Mul` are independent behavioral guarantees with homogeneous
bootstrap contracts `T + T -> T`, `T - T -> T` and `T * T -> T`. All built-in
signed/unsigned integers (including isize/usize), float32 and float64 satisfy
each contract. Transparent aliases use the same canonical TypeId: `int` is
int64, `float` is float32 and `double` is float64. Explicit and inferred calls,
nested forwarding and imported helpers use the same constraint checking.
Struct and enum binders accept these constraints too; `Holder<int>` is valid,
`Holder<bool>` is rejected, and `Holder<int>` itself does not satisfy Add.

Structural `Copy`, `Relocatable` and `Storable` describe representation and
ownership; they may derive through fields/payloads. Behavioral guarantees never
derive through fields, payloads, elements or nominal constraints. bool,
references, views, structs, enums and containers have no scalar behavioral
satisfaction. The only cross-capability implication remains Copy => Relocatable.
`T:Add` does not imply Copy, Storable, numeric classification or known layout.
Operands follow ordinary ownership: `a+b` consumes each unknown non-Copy T;
`a+a` requires an additional Copy guarantee. A generic literal identity is not
provided by these constraints.

The existing `T: Copy + Storable + Add` syntax composes both families. Every
body is checked before instantiation, including unused functions. Missing
operator guarantees identify the required capability. Forwarding must prove
all callee requirements; invalid concrete arguments fail before InstanceId
allocation/caching. HIR retains `CapabilityBinary { behavior: Add/Sub/Mul }`
and prints structural and behavioral guarantees separately. Its verifier checks
parametric bodies and call guarantees independently before monomorphization.

Substitution reifies each capability expression to the existing concrete scalar
operation: checked integer Add/Subtract/Multiply with IntegerOverflow, or IEEE
fadd/fsub/fmul without fast-math. Concrete HIR rejects residual CapabilityBinary;
MIR/SSA have no capability operation, and reject unresolved symbolic runtime
types. LLVM has ordinary static instances and direct scalar instructions, with
no dictionaries, hidden capability parameters, indirect dispatch or runtime
capability metadata. Constraint ordering does not change the existing instance
ABI or mangling, which depends only on declaration and concrete type arguments.

V27/V28 concrete container arithmetic stays available. V29 does not admit
arithmetic on generic Vector<T>/Matrix<T>, user operator implementations,
traits/interfaces, associated types, heterogeneous operands/results, Numeric,
Zero/One, dot/outer/matmul or runtime dispatch.
See [the V29 report](../docs/architecture/NEXT_VERTICAL_29_REPORT.md).
Compilation snapshots: `python3 tests/measure-v29.py --runs 10`.

## Built-in scalar multiplication (V28)

```aether
Matrix<int> a = [1,2;3,4];
Matrix<int> b = 2 * transpose_view(a); // [2,6;4,8]
Matrix<int> c = transpose_view(a) * 2;
Vector<int,Column> d = 3 * column(a,2); // [6,12], stride=2
Vector<int,Row> e = row(a,1) * 3;
Vector<double,Row> v = [1.5,2.5];
Vector<double,Row> w = 2 * v; // literal 2 is contextualized as double
```

Both orders accept one scalar and one Vector/VectorView/VectorViewMut or
Matrix/MatrixView/MatrixViewMut. The mathematical input is read through a
borrowed descriptor and stays usable. The result is a fresh owning Vector
with the same orientation, or Matrix with the same logical rows/columns.
Reads honor vector strides and both matrix strides, including projections
and transposed views; result storage is contiguous (row-major for Matrix).

Supported element/scalar types are int8/16/32/64, uint8/16/32/64, isize, usize,
float32/float64 and canonical aliases int/float/double. Scalar and element
canonical TypeIds must be equal. A typed `int s` cannot scale a double Vector.
Existing integer/float literal contexts (including directly negated literals)
use the mathematical element type; this does not convert typed variables or
arbitrary expressions. `supports_builtin_multiply` is an internal concrete-type
query. Storage/Copy constraints do not prove multiplication for symbolic T.

Operands evaluate in source order, and both are captured before allocation.
The mathematical root stays protected during a following scalar expression.
Even an empty input evaluates the scalar. Empty results allocate nothing;
nonempty operations allocate exactly one backing, perform N / R*C scalar
multiplications and stores in O(N) / O(R*C), and make no input backing copy.
Integer overflow traps as IntegerOverflow, including after partial result
initialization; floats use IEEE fmul without fast-math. AllocationSizeOverflow
and AllocationFailure remain checked. There is no shape compatibility guard.

HIR uses VectorScalarMultiply/MatrixScalarMultiply with source-side metadata.
The V27 structured MIR/SSA region now accepts an InvariantScalar and one
StridedLoad per logical element. Both verifiers check types, side, iteration,
strides, Multiply and complete initialization independently before LLVM emission.

Pairwise mathematical `*` remains rejected: no dot, outer, matmul, Hadamard,
scalar division, promotion, broadcasting, public Mul/Numeric trait or BLAS.
No slicing, methods or lifetime changes. Versioned sections below retain their
historical scope; V28 adds only scalar multiplication to V27 arithmetic.
See [the V28 report](../docs/architecture/NEXT_VERTICAL_28_REPORT.md).
Compilation snapshots: `python3 tests/measure-v28.py --runs 10`.

## Built-in elementwise addition and subtraction (V27)

```aether
Matrix<int> a = [1,2;3,4];
Matrix<int> b = transpose_view(a) + transpose_view(a); // [2,6;4,8]
Vector<int,Column> c = column(a,2) + column(a,2);     // [4,8], strided reads
Matrix<int> d = b - a;                              // independent owning result
```

`+` and `-` accept any pair of Vector/VectorView/VectorViewMut, or any pair of
Matrix/MatrixView/MatrixViewMut. They borrow readable inputs and produce one
fresh contiguous owner. Vector orientation and canonical element TypeId must
match exactly. Supported elements are int8/16/32/64, uint8/16/32/64, isize, usize,
float32 and float64 (including canonical aliases int/float/double). Neither
Copy nor Storable nor Relocatable proves arithmetic for symbolic T.

Vector dimensions must match; Matrix rows are compared first, then columns.
Known mismatches produce E0345; dynamic mismatches trap with ShapeMismatch
before allocation or element reads. Nonempty results allocate exactly one
backing and perform N (or R*C) scalar operations and stores, with O(N) / O(R*C)
time. Compatible empty inputs produce a null empty owner without allocation.
Explicit view strides, including transposes and column projections, govern
reads. Inputs may alias and remain usable. Integers retain checked overflow;
floats retain IEEE add/sub without fast-math. A trap aborts without unwinding,
including overflow after partial result initialization.

HIR retains distinct VectorElementwiseBinary/MatrixElementwiseBinary nodes and
ordered shape contracts. MIR/SSA contain executable structured loops with
shape guards, allocation, strided reads, scalar operations and complete-prefix
initialization. Both verifiers validate the complete region before LLVM emits
its nested CFG; only the fully initialized owner escapes.

V27 itself admitted no multiplication, scalar multiplication, dot/outer/matmul, division,
broadcasting, promotion, operator traits, user overloading or BLAS.
The following versioned sections preserve historical scope; V27 supersedes
their deferral of built-in addition/subtraction only.
See [the V27 report](../docs/architecture/NEXT_VERTICAL_27_REPORT.md).
Compilation snapshots: `python3 tests/measure-v27.py --runs 10`.

## Matrix rows and columns as oriented vector views (V26)

```aether
Matrix<int> A = [1,2,3;4,5,6];
VectorView<int,Row> r = row(A,2);          // [4,5,6], dimension 3, stride 1
VectorView<int,Column> c = column(A,2);    // [2,5], dimension 2, stride 3
VectorViewMut<int,Row> w = row_mut(A,2);
w[2] = 99;                              // A[2,2] = 99
MatrixView<int> T = transpose_view(A);
VectorView<int,Row> tr = row(T,2);        // [2,99], dimension 2, stride 3
VectorView<int,Column> tc = column(T,2);  // [4,99,6], dimension 3, stride 1
VectorView<int,Column> rt = transpose_view(r);
```

`row` / `column` accept Matrix, MatrixView and MatrixViewMut Places.
`row_mut` / `column_mut` require writable Matrix or MatrixViewMut capability
through the current path. References require explicit dereference; shared
references cannot regain write capability. All operations take a source and
one usize index, without type arguments or methods. Row/Column is mathematical
orientation, independent of physical layout; element T is preserved exactly.
The result is always the existing V25 VectorView/VectorViewMut, never an owning
Vector or raw View.

For source logical metadata `(ptr,R,C,RS,CS)`, row i gives
`{ptr+(i-1)*RS,C,CS}` and column j gives `{ptr+(j-1)*CS,R,RS}`.
Owners supply RS=C, CS=1; matrix views supply their actual strides, including
transposes. Fixed-axis lower and upper bounds precede subtraction and pointer
math. Empty 0x0 matrices have no valid row or column. Indexing the result uses
ordinary V25 one-based strided bounds; `dimension` works unchanged.

Every successful projection has zero allocation/free/relocation delta and
performs no element copy/load/store/drop. Its provenance follows the source
through views, copies and transposes to the same underlying owner or containing
struct/Array/List root. Live derived aliases block owner move/replacement and
potential List invalidation. Scope exit releases the borrow. Owning elements
can be borrowed; Copy subelements may be written through mutable projections.
No partial owning-element extraction/replacement is added.

Element-generic MatrixView<T>/MatrixViewMut<T> helpers support inferred T and
cross-module calls. The V25 centralized mutable-view call restriction for
List-containing elements remains in force. Projections cannot return, enter
owning storage or extend temporary lifetimes: bind a projection before applying
`transpose_view` to it. Slices/ranges, submatrices, owning row copies, Matrix
owning transpose, arithmetic and lifetimes remain future work.
See [the V26 report](../docs/architecture/NEXT_VERTICAL_26_REPORT.md).

## Oriented borrowed vector views (V25)

```aether
Vector<int,Row> v = [10,20,30];
VectorView<int,Row> row = vector_view(v);
VectorView<int,Column> column = transpose_view(row);
VectorViewMut<int,Column> writable = transpose_view_mut(v);
writable[2] = 42; // v[2] is now 42
ref int first = &column[1];
usize n = dimension(column);
```

`VectorView<T,Row/Column>` and `VectorViewMut<T,Row/Column>` are distinct
mathematical borrowed types. Element, orientation and write capability enter
canonical TypeId; runtime orientation does not exist. Their target-sized
three-word descriptor is `{ptr,dimension,stride}`, with stride in elements.
`vector_view` / `vector_view_mut` borrow a Vector Place with stride 1;
`transpose_view` / `transpose_view_mut` accept Vector owners or vector views
and flip Row/Column while preserving pointer, dimension and stride. Normal
creation from existing views also preserves their metadata. Empty owner views
use `{null,0,1}`. Every creation/transpose has zero alloc/free/relocation delta.

`view[i]` requires one usize index, checks `1 <= i <= dimension`, then computes
`(i-1)*stride`. Shared views allow Copy reads and shared references; mutable
views additionally allow Copy replacement and mutable references. Owning
Buffer elements/subelements can be borrowed without extracting ownership.
Both descriptors are Copy/Relocatable, non-Storable and have no drop; writable
does not imply uniqueness or noalias. Copies, explicit dereference loads and
transposes preserve the underlying lexical owner root. Live views block owner
move/replacement; scope exit releases their borrow. Struct fields, indexed
Array/List owners and explicitly dereferenced owner references are supported.

Views cannot return, enter owning storage, be rebound or serve as bare generic
type arguments. Element-generic `VectorView<T,Row>` / `VectorViewMut<T,Column>`
helpers support explicit/inferred T and cross-module calls; there is no generic
orientation O. Copy operations need T:Copy, and symbolic owning Vector sources
need T:Storable. Mutable mathematical views with List-containing elements cannot
cross call boundaries until nested alias effects can be proven; this common
rule covers MatrixView too.

V22 `transpose(Vector)` still consumes the owner and transfers its two-word
descriptor. Borrowed transpose leaves that owner live. V24 MatrixView keeps
its separate 2D descriptor and recipes. V25 itself adds no Matrix row/column extraction (V26 connects them above),
slicing/ranges, arithmetic, conjugation, traits, methods, raw descriptors or
lifetime parameters. See [the V25 report](../docs/architecture/NEXT_VERTICAL_25_REPORT.md)
for qualification, exact instrumentation, supported forms and compile snapshots.

## Borrowed strided matrix views (V24)

```aether
Matrix<int> A = [1,2,3;4,5,6];
MatrixView<int> v = matrix_view(A);
MatrixViewMut<int> T = transpose_view_mut(A);
T[2,1] = 99; // A[1,2] is now 99
MatrixView<int> back = transpose_view(T); // shape 2x3 again
usize m = rows(T);    // 3
usize n = columns(T); // 2
ref int x = &v[1,2];
```

The four intrinsics are `matrix_view`, `matrix_view_mut`, `transpose_view` and
`transpose_view_mut`. Each takes one existing Matrix or matrix-view Place, with
explicit dereference for references. The `_mut` operations require writable
source capability. These are borrowed operations; Vector's consuming
`transpose` remains separate, and `transpose(Matrix)` remains rejected.

Canonical `TypeData::MatrixView { element, mutable }` distinguishes both source
types from Matrix and zero-based raw View/ViewMut. Only T and write capability
participate in identity. Both view descriptors are Copy and Relocatable,
non-Storable and have no drop. Mutable capability implies no uniqueness and
LLVM receives no noalias promise. Copy aliases and transposed views retain the
original owner provenance under the existing lexical borrow model.

The five-word bootstrap descriptor is `{ptr,rows,columns,row_stride,column_stride}`
(40 bytes on x86_64), with strides in elements. Matrix owners still use their
three-word contiguous row-major descriptor. Normal owner views have `(R,C,C,1)`;
transposed owner views have `(C,R,1,C)`. Transposing a view swaps both shape and
strides, preserving its pointer. No transformation allocates, frees, relocates,
loads/stores elements or drops backing storage. Empty normal metadata is
`(0,0,0,1)`; transposed empty metadata is `(0,0,1,0)`.

Indexing remains `v[i,j]`, with two usize axes and all four one-based bounds
checks before `(i-1)*row_stride+(j-1)*column_stride`. Closed, independently
verified descriptor recipes preserve the original allocation's valid offset
range; no source pointer/stride constructor exists. Copy reads/writes and
shared/mutable element references use this same path. Owning elements can be
borrowed; partial owner extraction/replacement remains rejected.

An owner cannot move or be replaced while any derived view/copy is lexically
live. After the view scope ends, ordinary owner transfer and cleanup resume.
Struct fields, indexed owning containers and explicit owner references work;
nested List invalidation remains conservative. Passing mutable views whose
elements contain List across calls is rejected until nested alias effects can
be represented safely. Views cannot return, be stored
in owning aggregates/containers, be rebound, or be supplied as bare generic
type arguments under the existing borrowed-value restrictions. Helpers with
`MatrixView<T>`/`MatrixViewMut<T>` parameters support element generics and modules.
V24 added no stored lifetimes, methods, slicing, arithmetic or BLAS; V25 adds VectorView above.
See [the V24 report](../docs/architecture/NEXT_VERTICAL_24_REPORT.md).

## Current mathematical foundation (V23)

```aether
Matrix<double> A = [1, 2, 3; 4, 5, 6];
usize m = rows(A);
usize n = columns(A);
double last = A[m,n];
A[1,2] = 20;
ref double x = &A[1,1];
ref mut double y = &mut A[2,3];
```

`Matrix<T>` is a distinct mathematical owner, never an alias for nested
collections or vectors. Only T participates in canonical TypeId and structural
mangling; shape is immutable runtime value metadata. Storable is required,
including for symbolic `T:Storable`; Copy, Relocatable and Numeric are not
required of the element. Matrix itself is non-Copy and needs drop.

Brackets parse as `MathematicalLiteral { rows }`. Expected Vector context
requires at most one nonempty row and resolves to VectorInit, preserving Row /
Column identity and V22 consuming transpose. Expected Matrix context resolves
to MatrixInit after rectangular-shape validation. Commas separate entries and
semicolons separate rows. `[]` gives a 0x0 Matrix or dimension-zero Vector;
`[1,2,3]` gives a 1x3 Matrix, `[1;2;3]` a 3x1 Matrix. Every row is nonempty and
has the same width. A single trailing comma is accepted only before the final
`]`, including `[1,2;3,4,]`; commas before semicolons and trailing row semicolons
are rejected. Brackets without mathematical expected context are rejected.
Array/List retain `{...}` and zero-based indexing.

`A[i,j]` carries both usize indices in one place projection. Four ordered
checks enforce `1 <= i <= rows(A)` and `1 <= j <= columns(A)` before subtraction,
linearization or GEP. Copy reads/replacement and element references use the
same checked path. Indexed extraction or replacement of non-Copy elements
remains rejected. Constant bounds are diagnosed for direct lexical shape facts;
control-flow joins, writable calls and indirect shapes use runtime checks.

The bootstrap descriptor is `{ptr, i64 rows, i64 columns}` (24 bytes on x86_64),
with exact fixed contiguous storage, no capacity or stride field. Physical
storage is row-major: `(i-1)*columns+(j-1)`. Construction checks the shape product
and allocation byte size. Those immutable invariants plus all four bounds
prove the offset is representable and inside storage. Source operands are
evaluated and captured in row-major order; owning values transfer once. Cleanup
destroys slots in reverse row-major order and frees storage once. Empty matrices
allocate nothing. Generic calls, returns, structs, enums and nesting reuse
ordinary ownership and cleanup.

Matrix semantics are layout-independent. Row-major is a bootstrap layout
choice, not type identity. There is no Matrix arithmetic, multiplication,
transpose, slicing, row/column view, layout parameter or MatrixView in V23 (borrowed views are added by V24 above).
`transpose(Matrix)` is rejected by the Vector intrinsic. Raw View/ViewMut also
reject Matrix because they erase shape and use zero-based indexing. V24 above defines borrowed MatrixView/transpose; owning transpose remains future work.

See [the V23 report](../docs/architecture/NEXT_VERTICAL_23_REPORT.md) for
qualification, verifier corruption tests, allocation/drop instrumentation,
compilation snapshots and remaining decisions.

## Pipeline and crates

```text
entry SourceFile
  -> transitive discovery -> CompilationSession(module graph + source table)
  -> lexer/parser once per source -> ParsedProgram
  -> global declaration collection -> parametric resolver/type analysis
  -> type-directed ownership/provenance + transitive cleanup synthesis
  -> deduplicated concrete-instance worklist -> monomorphized TypedHir
  -> CFG/lifecycle lowering -> FlowMir -> VerifiedMir
  -> selective local promotion + explicit memory/ownership effects -> SsaIr -> VerifiedSsa
  -> LLVM backend -> textual LLVM
  -> clang toolchain -> Linux x86_64 executable
```

- `aether-frontend`: `SourceId`-qualified spans, structured diagnostics,
  lexer/parser, resolved module graph, global declaration collection, name
  resolution and typed HIR.
- `aether-middle`: explicit CFG MIR, MIR verifier, pruned dominance-frontier SSA
  construction, dominance analysis and SSA verifier.
- `aether-backend-llvm`: the backend interface and textual LLVM implementation.
- `aether-driver`: the in-process session pipeline, phase timings, clang
  toolchain boundary and the internal `aether-next` command.

The workspace has no third-party Rust dependencies. This is intentional: the
closed grammar and compact IR do not justify a parser framework, serialization,
LLVM binding, or general CLI dependency yet.

## Current bootstrap grammar (through V29)

```text
program    := import* (alias | struct | enum | function)+ EOF
import     := "import" IDENT ";"
alias      := "alias" IDENT "=" type ";"
struct     := "struct" IDENT generic-params? "{" field* "}"
field      := type IDENT ";"
enum       := "enum" IDENT generic-params? "{" variant ("," variant)* ","? "}"
variant    := IDENT | IDENT "(" type ("," type)* ")"
function   := type IDENT generic-params? "(" parameters? ")" block
generic-params := "<" generic-param ("," generic-param)* ">"
generic-param  := IDENT (":" capability ("+" capability)*)?
capability     := "Copy" | "Relocatable" | "Storable" | "Add" | "Sub" | "Mul"
parameters := parameter ("," parameter)*
parameter  := type IDENT
type       := "ref" "mut"? type
            | (IDENT ".")? ("bool" | integer-type | float-type | IDENT)
              ("<" type ("," type)* ">")?
block      := "{" statement* "}"
statement  := type IDENT "=" expression ";"
            | place "=" expression ";"
            | apply ";"
            | "if" "(" expression ")" block ("else" block)?
            | "while" "(" expression ")" block
            | "match" "(" match-mode? expression ")" "{" match-arm+ "}"
            | "return" expression ";"
match-arm  := variant-path ("(" IDENT ("," IDENT)* ")")? "=>" block
match-mode := "ref" "mut"?
expression := integer | float | "true" | "false" | IDENT | apply
            | "{" (expression ("," expression)* ","?)? "}"
            | mathematical-literal
            | expression "." IDENT | expression "[" expression ("," expression)* "]"
            | "(" expression ")" | "-" expression
            | "&" expression | "&" "mut" expression | "*" expression
            | expression ("*" | "/" | "%" | "+" | "-" | "<" | "<=" | ">" | ">="
                         | "==" | "!=") expression
apply      := path ("<" type ("," type)* ">")? "(" arguments? ")"
            | type "." IDENT ("(" arguments? ")")?
variant-path := type "." IDENT
arguments  := expression ("," expression)*
mathematical-literal := "[" (math-row (";" math-row)* ","?)? "]"
math-row   := expression ("," expression)*
place      := IDENT (("." IDENT) | ("[" expression ("," expression)* "]"))*
            | "*" expression | "(" "*" expression ")" (("." IDENT) | ("[" expression ("," expression)* "]"))*
```

Braces in expression position form a neutral `CollectionLiteral`; braces
required by a statement/declaration remain blocks. Semantic analysis resolves
the literal from its expected type. Vertical-14 admits `Array<T>` and `List<T>`
as expected collection kinds, including the canonical empty literal `{}`.
Effect statements admit `push(...)`, `reserve(...)`, and (since V22) declared
calls with a Copy result, which is discarded. Owning results require an explicit
binding; this is not a general void-expression or method system.

The semantic restriction is narrower than the expression-shaped grammar:
`&` and `&mut` accept only an existing resolved `Place`. No temporary lifetime
extension exists, so arithmetic, calls and aggregate constructors cannot be
borrowed.

Application syntax remains neutral in the AST. Semantic analysis resolves its
source application/path to exactly one of a declaration call plus explicit
type arguments, scalar conversion, `StructInit` or `EnumInit`; no ambiguity
survives HIR. The
canonical aggregate construction is positional, for example
`Point(3.0, 4.0)`. Arguments map to `FieldId`s in declaration order and every
field is required. This is structural construction, not a function call or a
user-defined constructor. Named initializers and named arguments are not part
of Vertical-5.

Generic functions, structs and enums use declaration binders with optional
compiler-known capability constraints.
`GenericParamId { owner, index }` supplies binder identity independently of
source spelling. `Pair<int,float64>` and `Option<Pair<int,float64>>` are
canonical applied `TypeId`s; repeated applications reuse one ID. Explicit call
arguments (`identity<int>(42)`) are the baseline. Calls without them use only
exact local parameter/argument matching; an uninferable parameter is rejected.
Generic bodies are checked parametrically, so arithmetic, comparison and field
access on an unconstrained `T` are invalid. Declared aggregate fields and enum
variants remain usable after substitution.

Vertical-15 capabilities are not general traits. `Copy` permits implicit
duplication; `Relocatable` permits an ownership-preserving physical move after
the old location ceases to be live. `Copy` centrally implies `Relocatable`, but
the reverse does not hold. Capabilities are derived by the compiler only:
there are no user implementations, methods, associated types, operator
constraints, dictionaries, vtables or runtime dispatch.

`GenericParamInfo` owns the resolved capability set for its exact
`GenericParamId`; `TypeData::GenericParam` identity does not include it.
Concrete `TypeProperties` remain actual facts, while a separate symbolic query
uses declaration guarantees and, for structural capabilities only, recursively
substituted struct fields or enum payloads. Calls and nominal applications validate inferred, explicit and
forwarded arguments before an `InstanceId` is requested. Constraints disappear
before MIR/SSA/LLVM.

`FunctionId` continues to identify one declaration. A canonical `InstanceId`
identifies each `(FunctionId, concrete type arguments)` and a deterministic
worklist lowers only concrete HIR into MIR/SSA. Same-instance runtime recursion
is permitted. Structurally expanding recursion is rejected early, with depth
and instance-count limits as a fallback. LLVM sees no unresolved generic
parameters, and instance symbols mangle logical module/declaration names plus
structural type arguments rather than session-local IDs.

Structs are nominal, module-owned value types. Same-layout declarations have
different `StructId`s, including declarations with the same spelling in two
modules. Imported struct types and construction require direct qualification,
for example `geometry.Point`; imports never inject unqualified type names.
Transparent aliases to structs preserve the underlying nominal identity.
Functions, structs, enums and aliases share one fail-closed top-level namespace
per module, so an application spelling always has one interpretation.

Enums are nominal, module-owned value types. `EnumId` identifies a declaration
and `VariantId { enum_id, index }` identifies a declaration-order variant in
O(1); source spellings are metadata below HIR. Variants are never injected into
local scope. Construction
is qualified (`Number.Integer(42)`, payloadless `State.Idle`, and imported
`types.Number.Integer(42)`). Positional payloads use ordinary contextual literal
and widening rules. Transparent aliases preserve the original `EnumId` and may
qualify construction.

Vertical-6 `match` is a statement with block arms, positional payload bindings,
and no wildcard, guard, nested pattern or result value. Every variant must
occur exactly once. HIR resolves the scrutinee `EnumId`, every arm `VariantId`
and every binding `LocalId`, rejecting duplicates and missing variants before
MIR.

The canonical scalar set is `bool`, `int8`/`16`/`32`/`64`,
`uint8`/`16`/`32`/`64`, `isize`, `usize`, `float32` and `float64`. Transparent
built-ins are `int = int64`, `byte = uint8`, `float = float32`, and
`double = float64`. User `alias` declarations are module-local transparent
aliases; chains are canonicalized once and cycles are rejected.

Integer and floating literals remain source spellings until contextual typing;
unconstrained defaults are `int64` and `float64`. Non-literal implicit
conversions are limited to widening within the signed family, widening within
the unsigned family, and `float32 -> float64`. HIR records each widening as a
`SignExtend`, `ZeroExtend`, or `FloatExtend`; MIR and SSA verify it explicitly.
Signed/unsigned, integer/float, narrowing, and bool/numeric conversions remain
invalid implicitly. Explicit numeric conversions are represented by a fully
typed `CastKind`. Integer conversions trap rather than wrap when the value is
not representable; float-to-integer truncates toward zero and traps for NaN,
infinity or an unrepresentable result. Integer-to-float and float narrowing may
round according to IEEE semantics. Bool has no numeric conversions.

Canonical semantic types use the compact, copyable, session-local identity
`TypeId(u32)`. A session-owned `TypeArena` provides the only authoritative
`TypeId -> TypeData` mapping and interns the reverse `TypeData -> TypeId`
mapping. Its current data variants are `Bool`, `Integer`, `Float`, nominal and
applied aggregate forms, generic parameters, and
`Reference { pointee: TypeId, mutable: bool }`, `Buffer { element: TypeId }`,
`Array { element: TypeId }`, `List { element: TypeId }`,
`Vector { element: TypeId, orientation: Orientation }`,
`Matrix { element: TypeId }`,
`MatrixView { element: TypeId, mutable: bool }`,
`VectorView { element: TypeId, orientation: Orientation, mutable: bool }`, and
`View { element: TypeId, mutable: bool }`. Repeated `ref T` resolution
reuses one ID, while `ref T` and `ref mut T` remain distinct. HIR is the first canonical boundary;
HIR, MIR, SSA, signatures, fields and enum payloads transport IDs rather than
copies of `TypeData`. MIR and SSA share the immutable arena through ordinary
Rust `Arc` ownership. IDs are never addresses, persistent fingerprints, ABI
identities or meaningful outside their owning compilation.

`StructId`, `EnumId`, `VariantId` and `FieldId` remain declaration/component
identities. Interning `Struct(StructId)` or `Enum(EnumId)` preserves nominality,
so equal layouts never imply equal `TypeId`s. Transparent built-in and user
aliases resolve directly to the underlying ID and do not receive a `TypeData`
variant. In particular `int == int64`, `float == float32`, `double == float64`
and `byte == uint8`, while `isize != int64` and `usize != uint64` even on
x86_64.

Struct and enum declarations are collected in all discovered modules before
aliases, payload/field types and function signatures are resolved. A
target-aware DFS rejects self and mutual by-value recursion across both
aggregate kinds, calculates nested size/alignment/padding,
and preserves source field order as physical bootstrap order. `layout_of`
forms the shared `(TypeId, TargetProperties) -> TypeLayout` boundary; aggregate
results are cached in declaration metadata once per single-target session.
Reordering fields
is therefore a source API change. The layout and aggregate calling convention
are internal bootstrap contracts, not public ABI.

All integer `+`, `-`, `*`, and signed negation are checked at their exact
width. LLVM uses signed or unsigned overflow intrinsics without `nsw`/`nuw`.
Integer `/` returns the same promoted integer type and truncates toward zero
when signed. Integer `%` is the corresponding remainder, so `-5 % 2 == -1`.
Zero divisors trap; signed `MIN / -1` traps separately, while `MIN % -1` is
lowered safely to zero. Floats use ordinary strict-baseline
`fadd`/`fsub`/`fmul`/`fdiv` without fast-math; floating division by zero follows
IEEE and floating `%` remains rejected.
Floating `==`, `<`, `<=`, `>`, `>=` are ordered (false with NaN); `!=` is
unordered (true with NaN).

The driver treats the entry file's directory as the explicit bootstrap source
root. `import math;` resolves only `<source-root>/math.ae`; there is no PATH,
environment, standard-library, registry or manifest search. Discovery is a
linear work queue keyed by logical module name, so every reachable file is
read and parsed once even with shared dependencies or cycles.

`SourceId` qualifies every span and indexes source provenance. `ModuleId` is a
separate, session-local logical identity; source paths never become semantic
identity. The resolved module graph uses `ModuleId` edges. The bootstrap
visibility policy makes every top-level function, struct and enum in a
discovered module available through a direct qualifier, but imported declarations never
enter unqualified scope. This policy is deliberately not the final v1
visibility design.

The frontend collects every struct/enum identity and signature in every
discovered module before checking any body. `FunctionId` is global and dense within the compilation
session, while names and module spellings remain metadata after resolution.
Local/qualified calls both become a concrete `FunctionId`, admitting forward
calls, recursion, import cycles and cross-module mutual recursion without
textual or filesystem order exceptions. Parameters retain ordinary
function-local `LocalId` identities and value semantics.

HIR carries the canonical type arena, `StructInfo`/`FieldInfo` and
`EnumInfo`/`VariantInfo` tables plus
fully resolved `StructInit`, `EnumInit`, matches and field places. MIR extends
the reusable `Place` model with a dereference base and represents borrow
creation semantically. Non-address-taken locals and aggregates retain ordinary
SSA (`Aggregate`, `ExtractField`, `InsertField`). A local whose address is taken
crosses a selective memory boundary: SSA retains it as `MemoryLocal` and uses
explicit aliasable `Load`, `Store` and `Borrow` operations. LLVM lowers only
those roots to `alloca` plus typed GEP/load/store; ordinary programs remain
allocation-free aggregate SSA.

MIR lowers enum matching to mode-carrying `EnumDiscriminant`/`EnumPayload`
operations and a reusable multi-way `Switch`. Consuming matches finish with an
explicit `ConsumeEnum`; reference matches form payload addresses only after the
tag selected the active arm. SSA retains these verified distinctions. LLVM uses
a fixed bootstrap `i32` tag and a typed envelope
`{ tag, variant-0-tuple, variant-1-tuple, ... }`, initialized from zero. This is
larger than a byte union but avoids type-punning, stack storage and MemorySSA.
Tags follow declaration order from zero. Tags, layout and aggregate calling
convention remain internal bootstrap details; niche/union compaction is
deferred.

## Development CLI

```bash
cargo run -p aether-driver --bin aether-next -- build input.ae -o output
cargo run -p aether-driver --bin aether-next -- run input.ae
cargo run -p aether-driver --bin aether-next -- build input.ae \
  --emit ast --emit hir --emit mir --emit ssa --emit llvm --timings
```

`run` calls the same build function with a temporary artifact and executes that
artifact. There is no interpreter or fallback.

## Qualification

Run all layer and native tests with:

```bash
cargo test --workspace
cargo clippy --workspace --all-targets -- -D warnings
tests/run-differential.sh
```

`tests/differential.tsv` remains the versioned admission manifest. It distinguishes
legacy-equivalent cases, deliberate `int64` changes, v1-contract cases,
open-decision rejection and fail-closed rejection. The integration suite checks
all new-compiler admission expectations and executes multiple native artifacts.
Legacy-equivalent native cases are separately compared with the legacy CLI in
qualification environments that contain its Python dependencies.
`tests/modules/v1-contract.tsv` records the Vertical-2 multi-file contract;
these cases are not forced through legacy differential semantics.

The Vertical-13 qualification run completed with 99 Rust unit/integration
tests passing, zero failures; clippy passed for the whole workspace/all targets
with warnings denied; and the executable legacy differential subset completed
21 comparisons with zero failures. Buffer-native tests additionally compile
through clang and exercise the generated allocation/free balance guard.

The Vertical-14 qualification run completes 106 Rust unit/integration tests
with zero failures, passes workspace/all-target clippy with warnings denied,
and keeps the 21-case executable legacy differential subset green. List-native
tests compile through clang, verify bounds/overflow traps, exact allocation and
free counts, aggregate/cross-module ownership and storage-borrow invalidation.

The Vertical-15 qualification run completes 110 Rust unit/integration tests
with zero failures, passes workspace/all-target clippy with warnings denied,
and keeps the executable legacy differential comparisons green. Capability
fixtures cover syntax/resolution, concrete and symbolic properties,
implication, explicit and inferred calls, forwarding, constrained
structs/enums, cross-module use, diagnostics and native erasure.

The Vertical-16 qualification run completes 114 Rust unit/integration tests
with zero failures and keeps workspace/all-target clippy warning-free. Native
coverage includes owned and nested Array/List literals, consuming push,
multiple List growths, returned and conditionally moved containers, structural
and active-variant cleanup, 43/43 allocation balance, and 12 observed element
relocations in the combined fixture.

### Vertical-7 timing baseline

A warm debug-build comparison against the pre-migration `HEAD`, using 30 full
compilations of `tests/programs/v6_enums.ae`, measured means in the low
microseconds: frontend signature+body analysis 195.1 -> 278.6 us, MIR verify
107.8 -> 112.0 us, and SSA verify 142.8 -> 157.0 us. The frontend phase boundary
also moved target layout from signature collection into semantic analysis.
These tiny-input figures are noisy, but they show a real current cost from
arena construction/property lookup and the new invalid-ID integrity scans.
`TypeId` itself is 32-bit and comparisons avoid copying/matching `TypeData`;
MIR/SSA share the arena with `Arc` instead of cloning it. Optimizing the scans or
property-query hot paths is accepted follow-up debt; no unsafe/global cache or
weaker verification was introduced to improve this microbenchmark.

### Vertical-8 timing snapshot

The same warm debug binary and 30-compilation `v6_enums.ae` workload measured
281.4 us for signature/body semantics, 111.8 us for MIR verification and 130.8
us for SSA verification. Against the recorded Vertical-7 means (278.6, 112.0
and 157.0 us), generic-capable type resolution and the concrete-instance table
add no material regression on this non-generic microbenchmark; the SSA change
is within the expected noise for such a small input. The cross-module generic
fixture is intentionally not compared as if it were the same workload.

### Vertical-9 timing snapshot

A warm debug binary was run for 30 full compilations of three versioned
fixtures. Mean core phase totals (parse, signatures, bodies, MIR lower/verify,
SSA build/verify and LLVM text emission; excluding file discovery and clang)
were approximately 941.3 us for the existing generic `v8_smoke.ae`, 462.7 us
for `v9_scalar_ref.ae`, and 515.3 us for `v9_aggregate_ref.ae`. The fixtures
have intentionally different sizes, so these are workload snapshots rather
than a before/after speedup claim. Inspection confirms that the V8 fixture has
no `alloca`; the two V9 fixtures spill only address-taken roots.

### Vertical-10 timing snapshot

A representative warm debug build on Linux x86_64 measured the core compiler
phases (parse, signatures, bodies, MIR lower/verify, SSA build/verify and LLVM
text emission; excluding discovery, file load and clang) at approximately
564.0 us for unchanged `v9_scalar_ref.ae`, 626.9 us for direct
`v10_element_ref.ae`, 630.7 us for `v10_view.ae`, and 2930.4 us for the much
larger all-features `v10_buffers.ae`. These are fixture snapshots rather than
same-workload speed comparisons. The element-reference fixture keeps the
Buffer descriptor in SSA while taking the stable heap element address; the
view fixture adds no allocation beyond its owner.

## Vertical-9 non-owning reference contract

`ref T` is a readable, non-null, non-owning view. `ref mut T` additionally
permits writes through that view. `mut` is a capability, not uniqueness:
mutable aliases and shared/mutable overlap are allowed, and codegen emits no
`noalias` or whole-object immutability promise from either reference kind.
Calls borrow explicitly (`read(&x)`, `write(&mut x)`), dereference is explicit
(`*r`, `(*r).field`), and reference parameters use the bootstrap pointer ABI
without copying an aggregate pointee.

V9 deliberately uses conservative non-escape rules instead of a general
lifetime or ownership system. References may be parameters, temporary call
arguments and single-initialization locals; reference locals cannot be rebound.
Functions cannot return references, aggregates cannot store them, and generic
type arguments cannot themselves be references. These restrictions make a
dangling lexical reference inexpressible with the current initialized-local
grammar. There are no null references, raw pointers, pointer arithmetic,
address comparisons/casts, heap ownership, ARC, moves or destructors in this
vertical.

## Vertical-10 fixed owning buffer contract

`Buffer<T>` is the first move-only owning value in the reconstruction. It owns
one fixed-length contiguous allocation, is constructed only as
`Buffer<T>(length, fill)`, and provides zero-based checked indexing through the
ordinary Place machinery. The length and every index have type `usize`; a
constant provably outside a known length is diagnosed, while dynamic failures
trap as `IndexOutOfBounds`. Allocation byte-size overflow and allocation
failure are distinct structured aborting traps. A zero-length buffer is valid
and still follows the same exactly-once allocation/free accounting.

Buffer assignment, by-value argument passing and return transfer ownership.
There is no implicit deep copy and no ARC. HIR records consuming uses as
`Move`, synthesizes lexical/return cleanup, and rejects use after move,
inconsistent ownership at continuing control-flow joins, loop-carried moves,
or moving/replacing an owner while a local derived reference or view remains
live. MIR makes `BufferAlloc`, `Move` and `Drop` explicit and independently
verifies ownership dataflow; SSA retains those transitions and keeps indexed
contents in memory rather than pretending they are aggregate SSA values.

`View<T>` and `ViewMut<T>` are non-owning contiguous descriptors created by
`view(buffer-place)` and `view_mut(buffer-place)`. Both carry pointer plus
length and reuse checked indexing; only `ViewMut<T>` permits stores. Like V9
references, view locals are single-initialization and cannot escape through a
return, aggregate field/payload or generic argument. `&buffer[i]` and
`&mut buffer[i]` borrow the checked element Place and remain valid because V10
buffers never resize.

V10 bounds ownership deliberately. `T` must be a concrete `Copy` type that
does not need drop or contain borrowed/owning substructure. Consequently
nested owning buffers, borrowed descriptor elements, symbolic `Buffer<T>`
inside generic bodies and borrowed descriptor elements are rejected. Buffers
themselves may be locals, aggregate fields/payloads, owned parameters, returned
values and reference pointees, including across modules. `Buffer` element
destruction remains deliberately deferred even though ownership may now
compose outward through aggregates.

LLVM represents Buffer/View values internally as `{ ptr, i64 }`, allocates
through a small runtime boundary backed by `malloc`, fills contiguously, and
frees through the matching boundary. Element size/alignment come from the
canonical target layout; current admitted element alignment fits the platform
`malloc` guarantee. Generated buffer programs count allocations and frees and
the platform wrapper traps if their normal-path balance is nonzero. Traps abort
without cleanup in V10; unwinding and exceptional cleanup remain deferred.

`Buffer<T>` is lower-level storage for future collections. It is not the final
`Array<T>` abstraction and adds no resizing, capacity, append/insert/remove,
slicing syntax, allocator API, shared ownership, raw pointer surface or general
ownership system.

## Vertical-11 transitive aggregate ownership contract

`is_copy(TypeId)`, `is_relocatable(TypeId)` and `needs_drop(TypeId)` are
independent, centralized,
memoized lifecycle queries. Scalars, references and views are Copy/no-drop;
`Buffer<T>` is non-Copy/needs-drop. A concrete struct is Copy only when every
substituted field is Copy and needs drop when any substituted field does. An
enum applies the same rules across every payload of every variant. Thus
`Holder<int>` remains Copy while `Holder<Buffer<int>>` moves and drops.
Unresolved generic parameters produce `is_known: false` and are conservatively
non-Copy/non-relocatable/potentially drop-requiring as concrete properties.
Their separately declared guarantees drive parametric checking;
monomorphization substitutes the concrete property and re-synthesizes
ownership cleanup.

Struct and enum construction consume non-Copy arguments from left to right,
including temporaries, without hidden clone, ARC or a second cleanup. A
whole-value move invalidates the source root, including access to its Copy
fields. Directly moving a non-Copy field is rejected as unsupported partial
move. Whole-local reassignment is supported: the right-hand side is evaluated
first, the old destination receives recursive drop glue, then ownership is
transferred. By-value parameters consume and returns transfer; references
borrow without moving.

One general MIR/SSA `Drop` carries the typed owner place. LLVM expands it as
compiler-generated glue: struct fields are destroyed in reverse declaration
order, nested aggregates recurse, and enums switch on the active discriminant
and destroy only that variant's payloads in reverse order. Physical LLVM
aggregate copies used to transfer bits do not imply source Copy semantics.
Normal-path allocation/free balance remains instrumented; traps abort and do
not unwind.

Non-Copy enum payload bindings in `match` remain rejected. Variant-only arms
(including payload-bearing variants with no requested binding) and Copy
payload bindings inspect a live local enum without consuming it.
References/views are still forbidden transitively in stored aggregates, and
the V10 `Buffer` element restriction is unchanged. V11 adds no partial moves,
destructor traits, clone, ARC, resizing or lifetime annotations.

### Vertical-11 timing snapshot

A warm debug build on Linux x86_64 measured one complete core compilation
(parse through LLVM, excluding discovery/file load and clang) at 3.313 ms for
the existing `v10_buffers.ae` fixture and 3.359 ms for the larger
`v11_aggregates.ae` fixture. The latter exercises concrete generic property
queries, nested struct glue and discriminant-based enum glue; these are
workload snapshots, not a same-input regression comparison.

## Vertical-12 ownership-aware match and conditional drop contract

Enum matching has one explicit match-level mode. `match (value)` is the default:
it copies a Copy enum, but consumes a non-Copy enum root as one whole-value
destructure. Each bound payload receives its declared `T`; non-Copy payloads
transfer ownership in declaration order and arm cleanup destroys remaining
bindings in reverse order. An omitted owning payload is extracted into internal
storage and destroyed, while the consumed wrapper is marked by `ConsumeEnum`
and is never recursively dropped again. This is a special whole-root operation,
not general partial-move support.

`match (ref value)` and `match (ref mut value)` require an addressable enum
Place. Their bindings have exact types `ref T` and `ref mut T`, respectively,
even when `T` is Copy. The owner remains alive; mutable payload references write
the active payload in place. As in V9, mutability is capability rather than
uniqueness and LLVM emits no `noalias`. Pattern references are restricted to the
arm by the existing no-return/no-storage/single-initialization reference rules.
Arbitrary temporaries cannot be matched by reference.

Ownership analysis adds `MaybeMoved` at continuing `Owned`/`Moved` joins.
Ordinary read, borrow, move, match or replacement still requires statically
`Owned`, so `MaybeMoved` produces a compile-time diagnostic and never a dynamic
use check. Normal cleanup alone may inspect this state. HIR records a
`Conditional` cleanup, and MIR allocates one compiler-only boolean flag for that
root, initializes it explicitly, updates it after every transfer, and lowers
cleanup to an ordinary branch around `Drop`. MIR verifies root/flag identity,
initial values and paired transitions; SSA retains the flag and verifies that
its phi reaches the cleanup branch. Uniform ownership paths receive no flag.

Flags remain root-level and apply through the existing concrete `needs_drop`
query to Buffer, structs, enums and generic aggregates. No per-field flags or
general conditionally initialized locals exist. Early-return path sensitivity
avoids a flag when only one ownership state reaches subsequent code. Loop
backedges that change ownership remain rejected with E0295; flags do not permit
repeated maybe-moved use. Traps remain aborting and non-unwinding.

### Vertical-12 qualification and timing snapshot

The local qualification completed with 93 Rust unit/integration tests passing
and zero failures; whole-workspace/all-target clippy passed with warnings
denied, and the executable legacy differential subset completed 21 comparisons
with zero failures. Native V12 fixtures execute value/ref/ref-mut matches,
multi-payload transfer, generic and cross-module matches, and conditional
Buffer/struct/enum/generic cleanup under the allocation/free balance guard.

A warm debug binary was run for 20 full compilations per representative
workload. Mean core time excluding discovery, file I/O and clang was
approximately 1.347 ms for the unchanged `v11_control_flow.ae`, 0.832 ms for a
minimal owning value match, 0.919 ms for its ref-match counterpart, and 2.238 ms
for the larger `v12_conditional_drop.ae` fixture. These are workload snapshots,
not a same-input optimization claim. MIR inspection reports zero flags for the
uniform `v12_match_ownership.ae` fixture and four root-level flags across the
four conditional-cleanup functions in `v12_conditional_drop.ae`.

## Vertical-13 fixed Array contract

`Array<T>` is the normal fixed-size owning collection. Its length is fixed at
construction, its initialized elements are contiguous, and indexing is checked
and zero-based. It has no capacity distinct from length and no `push`, `pop`,
`reserve`, `resize` or reallocation operation. `Buffer<T>` remains the distinct
lower-level storage primitive; the two types have different canonical
`TypeData`/`TypeId` identities and no implicit conversion, even though LLVM
uses the same internal `{ ptr, i64 }` descriptor and allocation boundary.

Collection literals are source AST `CollectionLiteral` nodes:

```aether
Array<int> values = {10, 20, 30};
Array<int> empty = {};
```

They require an expected `Array<T>` in this vertical. HIR resolves them to
`ArrayInit { element_type, elements }`; no unresolved braces reach MIR.
Elements use ordinary contextual scalar literal typing and coercion. Integer
spellings may directly select a floating contextual literal type, so
`Array<float64> values = {1, 2, 3};` has no runtime integer-to-float casts.
The temporary V13 element restriction requires concrete Copy/no-drop values
without borrowed or owning substructure. `Array<Buffer<int>>`, nested Array,
owning aggregate elements and symbolic `Array<T>` are therefore rejected until
an exact internal no-drop/storage-admission proof and element drop loops exist.
Public Copy/Relocatable constraints alone are intentionally insufficient. Array may itself be a
struct field, enum payload or concrete generic argument.

Fill construction is independent of literals:

```aether
Array<int> values = Array<int>(count, 0);
```

The bootstrap length surface is `length(array_place)`. This is intentionally
not a general method/property system: it resolves to `ArrayLength` in HIR, MIR
and SSA. Literal construction, fill and length remain explicit as `ArrayInit`,
`ArrayFill` and `ArrayLength`; checked element access continues through the
shared Place index projection and `IndexOutOfBounds` trap. `&a[i]`,
`&mut a[i]`, `view(a)` and `view_mut(a)` reuse existing provenance rules.
Stable element addresses need only owner-liveness checks because Array never
relocates.

Array is non-Copy and needs drop. Whole-value assignment, calls and returns
move it through the general V11/V12 ownership lattice, including `MaybeMoved`
conditional cleanup. General recursive aggregate drop glue frees its allocation
exactly once; V13 elements themselves require no destructor loop. Allocation
checks `length * sizeof(T)`, literal stores execute in source order, and the
normal-path allocation/free counters cover empty, literal, fill, moved,
returned, consumed, aggregate, conditional and borrowed/viewed arrays.

The collection/scientific split is intentional. `List<T>` is the distinct
dynamic, zero-based computational collection using the same `{...}` literal
syntax and owns growth/capacity operations. Future `Vector<T, Orientation>` and
`Matrix<T>` are mathematical objects, use bracket literals and one-based
indexing. Matrix literal syntax is structurally two-dimensional with semicolon
row separators; Matrix is not a nested Array/List/Vector representation.

`int main()` continues to return the process exit status. Nonzero results such
as 42 in bootstrap fixtures are a test harness technique for observing native
computation, not idiomatic successful application termination; canonical
success returns 0.

### Vertical-13 timing snapshot

A warm debug driver was sampled on the unchanged V12 fixture and on the V13
empty, literal, fill and indexed-reference-loop fixtures. These are small
workload snapshots, not benchmark-quality comparisons; discovery, file I/O and
clang/link time are excluded. Over 20 complete compilations per fixture, mean
core time was approximately 2.648 ms for unchanged
`v12_conditional_drop.ae`, 0.536 ms for `v13_empty_array.ae`, 0.600 ms for
`v13_literal_array.ae`, 0.619 ms for `v13_fill_array.ae`, and 0.803 ms for
`v13_index_ref_loop.ae`.

## Vertical-14 dynamic List contract

`List<T>` is a move-owned, dynamic contiguous collection distinct from both
fixed `Array<T>` and lower-level `Buffer<T>`. Its bootstrap representation is
`{ data pointer, length: usize, capacity: usize }`, with the invariant
`0 <= length <= capacity`. Only `[0, length)` is initialized and source-visible;
indexing is checked and zero-based against `length`, never `capacity`.

The existing neutral AST `CollectionLiteral` is reused. Expected `Array<T>`
produces `ArrayInit`, while expected `List<T>` produces `ListInit`. An empty
List has length and capacity zero and performs no allocation. A nonempty
literal allocates exactly once with initial length and capacity equal to the
literal element count, then initializes elements in source order without
lowering through repeated pushes. As in V13, `T` is temporarily restricted to
concrete Copy/no-drop values without borrowed or owning substructure.

The bootstrap semantic operations are:

```aether
length(list)
capacity(list)
push(list, value);
reserve(list, requested_capacity);
```

They resolve before HIR to `ListLength`, `ListCapacity`, `ListPush` and
`ListReserve`; the last two carry explicit `StructuralMutation` classification
through HIR, MIR and SSA. `push` checks `length + 1`, grows when needed, writes
the new element and only then exposes the incremented length. `reserve` keeps
length unchanged and guarantees at least the requested capacity. Growth uses
a checked internal geometric policy, but its exact factor and resulting spare
capacity are implementation details, not language semantics.

Reallocation allocates new storage, copies exactly the initialized prefix,
frees the replaced allocation and updates the descriptor. Capacity-byte and
growth arithmetic trap as `AllocationSizeOverflow`; allocation failure follows
the existing bootstrap policy. Drop frees the current allocation once and has
no per-element loop under the V14 element restriction. Moves, returns,
conditional ownership and recursive struct/enum/generic cleanup use the
existing V11/V12 machinery unchanged.

References and views into List element storage record their owning root. A
lexically live `&list[i]`, `&mut list[i]`, `view(list)` or `view_mut(list)`
prevents every `push` or `reserve`, even when runtime capacity would make the
specific operation allocation-free. Element assignment is not structural and
does not change pointer, length or capacity. Passing the owner to an arbitrary
call as `ref mut List<T>` is conservatively treated as potentially
storage-invalidating; shared List references are not. Explicit dereference is
still required when mutating through `ref mut List<T>`.

Array remains fixed and gains none of these operations. There is no implicit
Array/List/Buffer conversion. `pop`, resize, insert, erase, non-Copy elements,
general methods are deliberately deferred. Likely
future forms such as `list.length` and `list.push(x)` remain ergonomic surface
work over the explicit semantic operations.

### Vertical-14 timing and allocation snapshot

A warm debug driver was sampled over ten complete compilations per fixture,
excluding discovery, file I/O and clang/link time. Mean core times were about
0.741 ms for the unchanged V13 literal Array, 0.605 ms for empty List,
0.880 ms for literal List, 0.794 ms for sixteen repeated pushes, 0.910 ms for
reserve plus sixteen pushes, and 0.750 ms for the List view/index fixture.
These are small-fixture snapshots, not benchmark-quality comparisons.

Under the current internal policy, sixteen pushes from an empty List visit
capacities 1, 2, 4, 8 and 16: five allocations, four replacement frees and one
final free. Reserving 16 first performs one allocation and the sixteen pushes
perform no intermediate allocation, followed by one final free. Exact counts
demonstrate this implementation and its balance instrumentation; the capacity
sequence and growth factor are not language guarantees.
The combined move/return/struct/enum/generic/conditional fixture observes nine
allocations and nine frees, covering recursive and transferred ownership.

## Vertical-15 generic capability contract

Inline constraints support `T: Copy`, `T: Relocatable` and conjunction with
`+`, including multiple independently identified parameters. Unknown and
duplicate capability names are structured semantic errors. Generic bodies are
checked once using only declared guarantees; forwarding requires the caller's
symbolic argument to imply every callee constraint. Local inference still uses
exact type matching, then reports constraint failure separately from inference
failure.

The concrete table is: scalar integers/floats/bool, references, `View` and
`ViewMut` are Copy and Relocatable; `Buffer`, `Array` and `List` are non-Copy,
Relocatable owners requiring drop; structs are Copy/Relocatable iff all fields
are, and enums iff all payloads are. Reference/view escape and borrow rules are
independent and are never bypassed by capabilities.

V15 intentionally keeps symbolic `Buffer<T>`, `Array<T>` and `List<T>`
rejected. Their current admission contract additionally requires concrete,
no-drop elements without borrowed or owning substructure, and those internal
facts are not exposed as public constraints. List growth still copies elements
and does not run element drop glue. Relocatable therefore prepares a future
generalization without admitting `Array<Buffer<int>>` or `List<Buffer<int>>`.

### Vertical-15 timing snapshot

A warm debug driver was sampled over 30 complete compilations per versioned
fixture. Mean signature-collection plus semantic-body time was approximately
602.0 us for the V14 all-List baseline, 1060.9 us for the larger constrained
definition/use fixture, and 389.6 us for the compact symbolic aggregate
fixture. Corresponding mean core phase totals were 3203.6, 2314.7 and 658.6 us.
These fixtures intentionally differ in size and generated runtime helpers, so
the figures are snapshots rather than a same-workload regression claim. The
constraints add no runtime representation or dispatch.

## Vertical-16 owned collection element contract

`Array<T>` and `List<T>` now use the single
`collection_element_admission(TypeId)` query. A concrete element is admitted
when it is `Relocatable` and contains no stored reference or view under the
current lifetime rules. `Copy` and `needs_drop` are independent: the important
non-Copy + Relocatable + needs-drop combination is accepted. `Buffer<T>` keeps
its V10 fill-based Copy/no-drop element policy; broadening that lower-level
storage primitive is not necessary for owned Array/List composition.

Symbolic `T: Relocatable` proves physical transfer but not storage legality,
because references and views are themselves Relocatable. With no public
negative `NoBorrow` capability, symbolic Array/List element use remains
conservatively rejected. Concrete generic aggregates such as
`Holder<Buffer<int>>` and `Holder<List<int>>` are admitted after substitution.

Collection literals initialize one owner per slot in source order. A non-Copy
local used as an Array/List literal element or push argument is consumed by the
ordinary ownership analysis; a temporary transfers directly and receives no
second cleanup. `Array<T>(length, fill)` remains distinct and requires `T:
Copy`, since it duplicates one value into every element.

MIR and SSA attach a verified `Relocate` contract to List growth. It names the
element `TypeId`, exact initialized prefix `[0,length)`, initialized source,
uninitialized destination, uninitialized/dead source after transfer,
increasing order and a non-trapping guarantee. This internal storage operation
is not source `Move`: Move transfers a source-language value between owners,
while Relocate changes the physical location of one existing logical owner.

LLVM emits centralized typed relocation glue. Scalars use typed load/store;
Buffer, Array and List transfer descriptors without copying pointees; structs
relocate fields in declaration order; enums copy the discriminant and relocate
only the active payload in declaration order. The glue performs no allocation,
checked arithmetic, drop or trap. List reserve completes checked size
calculation and allocation before invoking it for elements `0..length`, then
frees only the old backing allocation and installs the new descriptor. A debug
counter records one relocation per moved List element.

Central generated drop glue recursively destroys Array/List elements from
`length-1` down to zero, then frees backing storage. List never reads reserved
slots `[length,capacity)`. Struct fields and active enum payloads retain reverse
declaration order. Nested indexing lowers through each descriptor layer;
borrow provenance remains conservative and continues to block structural List
mutation when a derived element path is live.

There is still no pop/remove, partial move, Clone, user Drop/Relocate, stored
borrow lifetime system, unwind cleanup, ARC/GC, raw pointer surface or
Vector/Matrix implementation. Nested Array/List values remain nested owners;
they are not Matrix semantics.

### Vertical-16 timing snapshot

A five-run warm debug-driver sample measured mean core compiler time (parse
through LLVM, excluding discovery, file I/O and clang) of approximately 37.5 ms
for the larger V15 capability fixture, 6.8 ms for `Array<Buffer<int>>`, 7.8 ms
for growing `List<Buffer<int>>`, 7.3 ms for nested `List<List<int>>`, and 9.2 ms
for `List<Dataset>` owning Buffer. These small-fixture wall-clock samples are
not benchmark-quality comparisons. In a separate five-run attribution sample,
V15 capability signature collection averaged 2.75 ms and semantic bodies
10.46 ms; the current phase timers do not split constraint resolution,
symbolic derivation and nominal second-pass validation further, which remains
measurement debt rather than a reason to speculate about their individual
costs.

## Vertical-17 Storable and symbolic collection legality

`Storable` is a positive compiler-derived capability: a value may persist as
an owning field/payload/element without introducing a lifetime dependency the
current ownership model cannot represent. It is independent of `Copy`,
`Relocatable`, size, and `needs_drop`. The only cross-capability implication is
still `Copy => Relocatable`. Source code cannot implement or assert a capability.

| Concrete type | Copy | Relocatable | Storable | Needs drop |
|---|:---:|:---:|:---:|:---:|
| `int` and other admitted scalars | yes | yes | yes | no |
| `Buffer<int>` | no | yes | yes | yes |
| `Array<int>` / `List<int>` | no | yes | yes | yes |
| `ref int` / `ref mut int` | yes | yes | no | no |
| `View<int>` / `ViewMut<int>` | yes | yes | no | no |

Structs derive Storable iff every substituted field does; enums require every
payload of every variant. Owning descriptors derive storage legality from their
element without requiring that element to be Copy or no-drop. Descriptor
relocatability is independent of element relocatability. Concrete properties
are memoized actual facts; `guarantees_storable` and `guarantees_capability`
resolve symbolic declaration guarantees structurally. A generic parameter's
`TypeProperties` remains unknown and potentially drop-requiring even under
`T: Storable`. Nested applications evaluate arguments in their outer binder
context before deriving members, including `Holder<Holder<T>>`.

One `collection_element_admission(CollectionKind, TypeId)` query applies
positive requirements to both concrete and symbolic types:

- `Array<T>` requires `T: Storable`.
- `List<T>` requires `T: Storable + Relocatable` because growth relocates live elements.
- Array fill additionally requires `T: Copy` because it duplicates a value.

```aether
Array<T> singleton<T: Storable>(T value) {
    Array<T> result = {value};
    return result;
}
List<T> append<T: Storable + Relocatable>(T value) {
    List<T> result = {};
    push(result, value);
    return result;
}
Array<T> repeated<T: Storable + Copy>(T value) {
    return Array<T>(3, value);
}
```

Literal elements and push arguments consume a non-guaranteed-Copy root; adding
Copy permits reuse. Storable alone does not remove cleanup obligations. Explicit,
inferred, forwarded and constrained nominal applications validate before
`InstanceId` allocation. Exact local inference also matches Array/List element
patterns. Array literal lowering initializes each final slot once from a typed
value: it performs no post-initialization element relocation. Source Move is an
ownership transfer, distinct from V16's physical Relocate. Future address-sensitive
types will need their own initialization/ABI rules; they are not implemented.

HIR dumps expose generic capability sets, concrete properties, symbolic
guarantees, each collection's element requirements/admission, and Move operands
in init/push. Monomorphization supplies ordinary concrete MIR/SSA operations and
re-synthesizes cleanup. MIR/SSA audit concrete type entries and reject symbolic
runtime locals/results; the shared arena may retain generic declaration metadata.
LLVM has no Storable operation, dispatch, dictionary, vtable or runtime overhead.
List relocation/drop glue and allocation semantics remain V16's.

Stored references/views remain forbidden. Storable does not introduce named
lifetimes, borrowed returns, lifetime-parameterized storage, self-references,
pinning, pop/remove, partial moves, traits or mathematical types. Array/List
remain zero-based collections; future Vector/Matrix remain one-based mathematics.

**Buffer distinction:** semantic persistent storage requires a Storable element;
repeating one fill additionally needs Copy. V17 derives Buffer storage properties
independently, but retains the source-level V10 concrete Copy/no-drop admission
as an implementation restriction: the only initializer is fill and Buffer drop
glue does not recursively destroy elements. It is not a universal type-level
law that owning storage needs Copy. A future Buffer extension can split type
admission from fill, add recursive element cleanup and a fully initialized
literal/builder API, or retain Buffer as the restricted substrate. V17 does not
choose or implement that extension. Symbolic Buffer/View construction remains deferred.

Qualification adds 11 Rust tests to the 114-test baseline, including native
symbolic owner/aggregate/nested collections, parameter consumption, borrowed
rejection, inference, cross-module constraints and concrete verifier mutations.
The full V17 fixture observes 67 allocations, 67 frees and 56 root-element List
relocations. V16 still observes 43/43 and 12. See the complete
[V17 implementation report](../docs/architecture/NEXT_VERTICAL_17_REPORT.md).

### Vertical-17 timing methodology

The existing timers retain their scope:

| Timer | Inclusive measured work |
|---|---|
| `module.discovery` | source-root setup, transitive discovery, file reads, parsing and module graph assembly |
| `module.file_load` | sum of file reads inside discovery |
| `frontend.parse` | lex/parse; summed per module for a session |
| `frontend.signature_collection` | global declarations, aliases, generic binders, fields/payloads, nominal second pass, signatures |
| `frontend.semantic_bodies` | target layouts, parametric body checking/ownership, monomorphization, concrete layouts and HIR verification |
| `middle.mir_lower` / `middle.mir_verify` | HIR-to-MIR lowering / MIR verification |
| `middle.ssa_build` / `middle.ssa_verify` | SSA construction / SSA verification |
| `backend.llvm` | LLVM text and runtime-helper emission |

Four additional `frontend.detail.*` counters are snapshotted immediately after
semantic bodies, before HIR dump generation and middle/backend processing:

| Detail suffix | Inclusive measured work |
|---|---|
| `constraint_resolution` | declaration binder collection, constraint-name lookup/deduplication, registration/interning; excludes application constraint checking |
| `symbolic_property_derivation` | each top-level guarantee query whose type contains a generic parameter, including recursive argument/member derivation; excludes concrete property queries |
| `collection_admission` | each Array/List element admission query, including its capability queries |
| `nominal_second_pass` | post-registration validation of fields, enum payloads, aliases, container entries and stored-borrow restrictions; excludes function signatures/bodies |

These are nested inclusive measurements, not disjoint costs. Never add detail
timers to phase totals, nor discovery to its file-read/parse components. Timer
bookkeeping has compiler-side overhead and is excluded from semantic identity and
deterministic dumps. The measurement script's `core` is exactly the original
eight parse-through-LLVM timers; it excludes discovery, file I/O, dumps, process
startup, output writing and clang/linking. Layout-dependent generic allocation
size checks remain in concrete runtime helpers when symbolic layout is unknown.

Reproduce a snapshot after building the debug driver, with no concurrent builds:

```bash
cargo build -p aether-driver --bin aether-next
python3 tests/measure-v17.py --runs 10
```

The script launches a fresh process for each build, discards one warmup per
fixture, then reports mean/median milliseconds across ten warm-cache builds.
Clang runs for each build but is outside core timings. Fixture contents and
compiler build/profile matter; earlier V13..16 numbers are historical snapshots,
not comparable before/after measurements. Raw results and summarized values are
linked from the V17 report.

## Vertical-18 initialized slots and owning List pop

`T last = pop(list);` extracts a whole final element from a writable `List<T>`
place. Through a reference, use `pop(*list)` with `ref mut List<T>`. The same
operation works parametrically under `T: Storable + Relocatable`; Copy is not
required. Its result can initialize a local or aggregate, be consumed by a call,
or be returned directly.

```aether
T popLast<T: Storable + Relocatable>(ref mut List<T> values) {
    return pop(*values);
}
```

The initialized prefix changes from `[0,N)` to `[0,N-1)`. The tail's lifetime
ends in storage and ownership passes to the ordinary result, including when T
is Copy. Capacity and backing pointer stay unchanged; pop performs no heap
allocation, reallocation, free or surviving-element relocation. Subsequent push
can initialize that raw tail slot again without growing when capacity suffices.
List cleanup reads the new length and destroys only the remaining prefix.

An empty List takes a structured `ListEmpty` trap before subtraction or storage
access. There is no unwind, Option magic or `try_pop`. A future library optional
API can be designed separately. The result is currently required in an expression;
`pop(list);` is not a new discard/effect statement form.

`SlotPlace<Place, Operand>` (and its SSA specialization) is a compiler-internal
typed storage address with owning root, element index and TypeId. Ordinary
`PlaceProjection::Index` always checks logical length. Take uses SlotPlace,
which has its own initialization authority; push's raw slot at old length is
represented by `PushInit`, never by unchecked source indexing.

| Operation | Ownership/initialization transition |
|---|---|
| Move | source-language root Owned → Moved; ordinary destination owns the value |
| Relocate | initialized storage A → raw storage B; A becomes Uninitialized |
| Take | initialized storage slot → ordinary owned result; slot becomes Uninitialized |
| PushInit | raw tail at old length → Initialized; incremented prefix includes it |

HIR carries `ListPop`, the element type and `StableStructuralMutation`. The
small effect API distinguishes element assignment, stable structural mutation
(pop), and potentially relocating mutation (push/reserve). MIR and SSA carry a
real nonempty-check branch, `TailIndex`, `Take` with explicit before/after states,
and `ListSetLength`. Both verifiers require a fresh checked length and exactly
one contiguous extraction/commit transaction; they reject missing commits,
double Take, wrong state/index/root, misplaced operations and trapping transfers.
An extracted non-Copy SSA temporary must transfer exactly once before a phi.
No per-element runtime bitmap or drop flag is added: length is the prefix boundary.

Pop descriptor roots use the existing selective memory boundary so aliases,
subsequent queries, whole-root moves and cleanup see the committed length.
Unrelated locals remain promoted. Scalars and owning handles transfer by load;
aggregates reuse recursive relocation glue into one entry-block stack temporary.
No pointee is copied or freed. This bootstrap choice deliberately defers promotion
of pop-mutated descriptors and generalized storage dataflow/MemorySSA.

A direct constant-index element reference survives pop when the compiler knows
`index < old_length-1`. A definite tail, unknown index, unknown length or live
whole-list View/ViewMut fails closed with E0319. Scope exit ends the restriction.
Proofs track direct literal lengths and successful pops; push, differing branch lengths,
List loops and arbitrary writable calls invalidate constant length knowledge.
Nested provenance remains conservative, even for an inner Buffer whose allocation
might survive. Calls with writable access to List-containing types remain potentially
invalidating; calls that only mutate scalar/Copy elements preserve the prefix. Borrowed
arguments also remain live during evaluation of subsequent arguments.

E0318 reports invalid/read-only pop targets or intrinsic arguments. Symbolic
collection capability errors retain V17's diagnostics. Array extraction, Buffer
broadening, arbitrary partial moves, remove/insert/drain, ranged slices, methods,
Option, named lifetimes and mathematical containers are outside V18.

Qualification, exact counts, accepted debt and all 37 report items are in
[NEXT_VERTICAL_18_REPORT.md](../docs/architecture/NEXT_VERTICAL_18_REPORT.md).
`tests/measure-v18.py --runs 10` uses the unchanged V17 eight-phase core timing
methodology, with an optional `--baseline-binary` built from V17. The checked-in
`tests/timings/v18-debug.json` records both versions and all phase statistics.

## Vertical-19 indexed owning extraction with swap_remove

```aether
T takeAt<T: Storable + Relocatable>(ref mut List<T> list, usize i) {
    return swap_remove(*list, i);
}
int main() {
    List<int> values = {10,20,30,40};
    ref int first = &values[0];
    int removed = swap_remove(values, 1);
    // removed == 20; values == {10,40,30}; *first == 10
    return 0;
}
```

`swap_remove` accepts a writable List Place and one ordinary zero-based usize
index. It returns the removed T, supporting Copy values, owning handles, nested
collections, structs and enums. Order is **not preserved**: the previous tail
replaces the removed slot. Intended complexity is O(1), modulo element relocation
glue cost. Out-of-bounds (including an empty List) traps with IndexOutOfBounds
before subtraction or mutation. The index is evaluated exactly once.

The verified CFG reads fresh length, checks bounds, computes tail, Takes the
requested slot and branches on index == tail. The tail edge performs no relocation;
the non-tail edge invokes one element Relocate into the hole. The common commit
updates length only after both paths establish `[0,N-1)` Initialized and the old
tail Uninitialized. Sharing the non-trapping Take before the tail decision avoids
duplicating extracted ownership or merging it through a phi. MIR and SSA verify
this bounded diamond independently in addition to the unchanged V18 pop shape.
Relocate reuses V16 state metadata and recursive glue, adding SingleSlot range
and an explicit destination Initialized post-state. No runtime bitmap is used.

HIR records ListSwapRemove, StableStructuralMutation and IndexAndTail invalidation.
Backing pointer and capacity never change; the operation allocates/frees nothing.
Aliases, projected descriptors, subsequent indexing/push/length, owner returns
and cleanup read the committed descriptor. Drop visits reverse final indices,
including the former tail at its new slot. A reserved swap_remove + push transfers
slot → result, tail → hole, result → new tail without additional allocations.

A live ref/ref mut to the removed slot or old tail blocks extraction. Direct
constant references outside `{index,tail}` survive when length is known; tail
removal affects only the tail. Unknown/dynamic indices and nested relationships
remain conservative. Whole-list View/ViewMut blocks mutation while in scope.
E0320 diagnoses invalid/read-only targets or intrinsic arguments; E0321 diagnoses
maybe affected live borrows/views. Index type errors use ordinary numeric/type
diagnostics. Generic helpers check parametrically, and concrete parameters such
as usize provide context to literals even during generic argument inference.

The native suite checks eleven fixtures with exact cleanup and relocation counts,
per-operation pointer/capacity/heap probes, reverse final drop order, aliases,
scopes, generic cross-module helpers and structured bounds traps. MIR and SSA
each reject 23 transaction corruptions. See
[NEXT_VERTICAL_19_REPORT.md](../docs/architecture/NEXT_VERTICAL_19_REPORT.md).
Timing uses the unchanged eight V17/V18 core phase boundaries, excluding clang:

```bash
cargo build -p aether-driver --bin aether-next
python3 tests/measure-v19.py --runs 10
# Optional: --baseline-binary <separately-built-v18-driver> --baseline-revision <rev>
```

`tests/timings/v19-debug.json` records mean/median for a V18 pop baseline and
swap_remove int, Buffer, nested owning and reuse fixtures. These are debug
snapshots, not optimizer claims. V19 leaves order-preserving remove to V20 below. Insert, drain, methods,
Option, Array extraction, Buffer broadening and lifetimes remain outside V19.

## Bootstrap ABI and deliberate limits

One entry module plus transitively imported source modules and exactly one
selected `int main()` in the entry module are admitted. An imported module may
spell a function `main`, but it is never selected as process entry. Function
parameter and result lowering (scalars and LLVM aggregates) is an
**internal bootstrap ABI**, not a stable Aether ABI and not `extern C`.
Bootstrap LLVM symbols use deterministic length-delimited logical module and
function names plus structural generic substitutions. They do not depend on
session-local `TypeId`/`InstanceId` numbers and cannot collide
for the admitted identifiers. The scheme is intentionally temporary, is not a
public ABI, and still leaves packages and overload signatures for later milestones.

A generated platform `main` calls the internal Aether entry, truncates its
semantic `int64` result to the host `i32` process status, and returns that to
the toolchain. POSIX generally exposes only its low status byte. This mapping
is a platform/toolchain observable, not the final meaning of returning an
Aether `int`.

Modules are declaration-only: there are no globals, top-level statements,
module initializers or initialization order. This is precisely why import
cycles have no execution-order meaning in this slice. There are also no
packages, nested/selective/wildcard/aliased imports, reexports, visibility
keywords, overloads, behavioral traits, generic aliases, function values, closures, extern functions,
heap values beyond `Buffer`/`Array`/`List`, strings, named initializers, methods, general
ownership, optimization pipeline, public ABI/runtime API, or LLVM library binding. Unsupported forms fail
closed before lowering.


## Vertical-20 order-preserving List removal

```aether
T removeAt<T: Storable + Relocatable>(ref mut List<T> values, usize i) {
    return remove(*values, i);
}
int main() {
    List<int> values = {10,20,30,40};
    ref int first = &values[0];
    int removed = remove(values, 1);
    // removed == 20; values == {10,30,40}; *first == 10
    return 0;
}
```

| Operation | Final sequence after removing 1 | Intended time | Relocations |
|---|---|---|---|
| `swap_remove` | `{10,40,30}` | O(1) | 0 at tail, otherwise 1 |
| `remove` | `{10,30,40}` | O(N-i), modulo element glue | N-i-1 |

`remove` requires a writable List Place and one zero-based usize index. It
returns T with ordinary owning or Copy behavior; no Copy constraint is added.
A fresh length check traps with IndexOutOfBounds before N-1, Take or mutation,
including empty Lists. The index expression is evaluated once. Pointer and
capacity remain unchanged, and remove itself performs zero allocation/free.

The explicit MIR/SSA CFG uses the existing Take at i, then a pretested forward
loop. Its sole hole starts at i: Relocate(h+1 -> h) initializes h and ends
h+1 liveness; HoleNext supplies the bounded, non-trapping successor. After
h reaches N-1, the loop exits and commits length=N-1. Tail and singleton
removals execute no loop body and no relocation. The extracted owner is never
merged by a phi; SSA promotes only the usize hole in this loop.

Both layers independently verify roots, operands, initialization states, exact
successor, actual loop edges, unique entry, bound and complete prefix at commit.
Projected descriptor addresses are resolved before the transaction through the
existing internal Borrow/dereference representation, avoiding repeated checked
outer indexing while a hole exists. LLVM emits the verified loop, typed GEPs,
existing non-trapping relocation glue and the final length store. It does not
use memmove as ownership authority or introduce runtime slot flags.

HIR marks ListRemove as StableStructuralMutation with SuffixFrom, whose index
is the operation's resolved index field. Live refs/ref muts to any old slot
>= i are rejected, including shifted values that survive at another address.
A direct constant borrowed index < constant removal index survives even if
length is unknown. Dynamic/unknown relations, whole View/ViewMut and ambiguous
nested provenance remain conservative. Scope exit releases the restriction;
writable descriptor aliases retain root identity. Diagnostics are E0322 for
invalid targets/arity and E0323 for affected or unprovable borrows, plus ordinary
usize/type diagnostics.

Buffer, Array, nested List, Dataset, owning enum and generic/cross-module tests
exercise unique transfer, consuming calls/returns, projected and alias freshness,
remove+push reuse, conditional cleanup and reverse FINAL index destruction.
Per-operation probes assert pointer/capacity stability, zero alloc/free and
N-i-1 relocations. A Buffer example records extracted 20 followed by List
cleanup 40,30,10. Existing pop, swap_remove and growth retain their contracts.

Qualification: 153 workspace tests pass, including eleven V20 tests, 40 MIR
and 45 SSA corruptions. See [the V20 report](../docs/architecture/NEXT_VERTICAL_20_REPORT.md)
for exact coverage and compile snapshots. Reproduce timings with
`python3 tests/measure-v20.py --runs 10`; optional `--baseline-binary` and
`--baseline-revision` select a separately built V19 compiler. Insert, range erase,
drain, methods, Option, lifetimes, traits, Array removal and Buffer changes remain
outside this vertical.


## Vertical-21 mathematical Vector foundation

```aether
Vector<T, Row> pair<T: Storable>(T a, T b) { return [a, b]; }
int main() {
    Vector<double, Row> r = [1, 2, 3];
    Vector<double, Column> c = [];
    r[1] = 4.0;
    ref double first = &r[1];
    ref mut double last = &mut r[3];
    *last = 5.0;
    return int(dimension(r)) + int(dimension(c)) - 3;
}
```

| Type | Literal | Extent | Source indices | Query |
|---|---|---|---|---|
| Array<T> | `{...}` | Fixed length | `0 <= i < length` | `length(a)` |
| List<T> | `{...}` | Dynamic length/capacity | `0 <= i < length` | `length(l)`, `capacity(l)` |
| Vector<T, Row/Column> | `[...]` | Fixed dimension | `1 <= i <= dimension` | `dimension(v)` |

Vector is an intrinsic mathematical type, not an Array alias. Canonical
`TypeData::Vector { element, orientation: Orientation::{Row,Column} }` makes
orientations distinct TypeIds, including inside generic aggregates and imported
signatures. Markers are intrinsic compile-time arguments; no value generics,
orientation fields or strides are introduced. `Vector` takes exactly two
arguments. Dimension is descriptor data, not a type argument.

`AstExprKind::VectorLiteral` is separate from `CollectionLiteral`. Expected
Vector context supplies both element type and orientation, including for `[]`
(dimension zero). Ordinary contextual literals and widening apply; unconstrained
`auto`/untyped mathematical literals remain rejected. No implicit Array/Vector
or Row/Column conversion exists. Matrix remains future: `[a,b; c,d]` is reserved
for a structurally 2D literal with `A[i,j]`, never nested Vector/Array semantics.
The parser reports that reservation when a semicolon occurs in a bracket literal.

Vector admits `T: Storable` without Copy, Relocatable or a numerical capability
requirement. Symbolic bodies, exact inference and monomorphization preserve
orientation. Bool, structs, enums and owning elements are legal storage types.
`Vector<Buffer<int>,Row>` transfers each literal operand once; there is no
intermediate Array, deep copy or implicit extraction. Ordinary non-Copy indexed
reads and non-Copy partial replacement remain rejected by existing ownership
rules. Copy reads/writes and element `ref`/`ref mut` work, including projections.

HIR, MIR and SSA retain VectorInit and VectorDimension. Their shared Place
index model carries IndexSemantics, checked independently against canonical
container TypeId in every verifier. Vector selects OneBased; Array/List/Buffer/
View select ZeroBased. Index operands remain usize. Known invalid direct indices
are diagnosed; other invalid indices trap with IndexOutOfBounds. LLVM checks
`i >= 1`, then `i <= dimension`, and only in the successful block computes
`offset = i - 1` and its GEP. Nested descriptor access selects each level's base.

The physical descriptor is `{ ptr, i64 dimension }` on Linux x86_64. Nonempty
construction uses shared exact fixed allocation, then stores source-order
operands. Empty Vector uses null/zero without allocation. It has no capacity,
growth or extraction operations. Vector is non-Copy and needs_drop; normal root
move, call, return, aggregate and conditional cleanup transfer its ownership.
Drop destroys owning elements in reverse logical order n..1 (slots n-1..0), then
frees the backing allocation. No Vector-specific ownership flags are introduced.

Backing addresses remain stable while the owner lives. Live element references
block owner moves/replacement under existing lexical rules. Vector has no List
structural invalidation; element-only mutation through a Vector reference does
not acquire a List growth effect. A nested List retains its own effects.
Public `view`/`view_mut` reject Vector: raw zero-based View would erase orientation
and mathematical semantics. Future VectorView is separate work.

Qualification and exact heap counts are in
[the V21 report](../docs/architecture/NEXT_VERTICAL_21_REPORT.md). Reproduce compile
snapshots using `python3 tests/measure-v21.py --runs 10`, optionally with
`--baseline-binary <separate-v20-driver> --baseline-revision <revision>`.
No arithmetic, dot/outer/norm/transpose, Matrix, methods, traits, Numeric/Scalar,
Vector views, or new List operations are implemented by V21.


## Vertical-22 explicit consuming Vector transpose

```aether
Vector<T,Column> toColumn<T:Storable>(Vector<T,Row> v) {
    return transpose(v);
}
int main() {
    Vector<int,Row> r = [10,20,30];
    Vector<int,Column> c = transpose(r);
    Vector<int,Row> r2 = transpose(c);
    return r2[1] + r2[2] + r2[3] - 60;
}
```

`transpose(vector)` consumes its operand and derives its result type without
expected-type inference: `Vector<T,Row> -> Vector<T,Column>` and conversely.
The exact element TypeId is preserved. The source owner is moved, including
when T is Copy; subsequent use is an ordinary use-after-move error. Direct
Row/Column assignment remains invalid. Return, consuming arguments, generic
bodies with only T: Storable, struct fields at construction, enum payloads and
imported signatures compose with existing whole-owner transfer rules.
`consume(transpose(v));` is supported when consume returns Copy (for example int):
a compiler-only sink discards the result using ordinary call lowering. Owning
results must be bound explicitly; no unit/void type is introduced.
Non-Copy partial field/index extraction and moving through a reference remain
rejected. A live shared or mutable element borrow blocks consumption; ordinary
one-based indexing and borrowing work on the result.

This is a strong O(1) physical contract: the exact backing pointer and dimension
are transferred unchanged. Transpose performs zero allocations, frees, element
copies, relocations or drops, including for Vector<Buffer<int>,Row>. Empty
null/zero descriptors remain empty. Components keep their order and values;
there is no reversal, conjugation or invocation of element functions. This is
not conjugate transpose. The final destination performs the ordinary reverse
index element drop and one backing free. Double transpose restores the original
orientation with the same allocation.

AST retains ordinary application syntax. HIR VectorTranspose and MIR/SSA
VectorTransposeMove are explicit consuming operations. The operand source_type
and enclosing result TypeId are the sole orientation/element authorities;
independent verifiers require equal elements and opposite orientations. Their
canonical Vector representation defines the same two-field descriptor layout,
without a mutable layout/orientation cache. MIR uses existing owner states and
cleanup flags. SSA independently checks each materialized source and result
transfers exactly once before a phi. LLVM passes the identical aggregate bits
using a constant select, with no orientation runtime field, branch, helper,
backing access or element loop. Existing QRow/QColumn mangling is unchanged.

E0328 reports invalid operand kind, arity or explicit type arguments. Ordinary
ownership/type diagnostics cover moved owners, live borrows and partial moves.
The operation accepts one owning Vector expression and no explicit type
arguments; a bare `transpose([])` lacks operand orientation context and fails
with the existing mathematical literal diagnostic.

Qualification instruments every emitted transpose to compare pointer, dimension
and allocation/free/relocation counters before and after, plus final exact heap
counts and reverse drop traces. See [the V22 report](../docs/architecture/NEXT_VERTICAL_22_REPORT.md).
Compilation-only snapshots: `python3 tests/measure-v22.py --runs 10`, optionally
with `--baseline-binary <separate-v21-driver> --baseline-revision <revision>`.
Borrowed transpose/VectorView, Matrix transpose, arithmetic, numeric traits,
methods, operator syntax and conjugate transpose remain separate future work.
