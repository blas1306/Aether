# MATH-ARCH-1 — native mathematical architecture consolidation

## 1. Scope and non-goals

Consolidation of the native mathematical subsystem in `compiler-next`, qualified
on Linux x86_64. V21..V33 source semantics are authoritative. No new syntax,
operators, capabilities, algorithms, source acceptance, lifetime rules, ownership,
runtime representation, ABI, mangling, trap behavior or optimization is introduced.
This is MATH-ARCH-1, not a feature vertical or a performance milestone.

## 2. Initial inventory (completed before renaming)

Baseline: `ec520fff2711e0bf1f091e40438e4991ec0962d5`, V33. The two
pre-existing untracked binaries FaCAether/FaCAetherO0 are unrelated.

| Responsibility | Initial authority / finding |
|---|---|
| Source resolution | `aether-frontend/src/hir.rs`: `binary`, `readable_math_operand`, `literal_binary_context`; multiplication family table embedded in successive checker branches |
| HIR families | Init/query/view/transpose/projection, separate Vector/Matrix elementwise and scaling nodes; historical `VectorAlgebraicProduct` wraps `VectorProduct` even for Matrix×Matrix |
| Semantic metadata | `MathShapeCheck`, `MatrixProductExtent`, `ScalarSide`, `MathElementOp`; Inner, Outer, MatrixVector, MatrixAlgebraicProduct recipes |
| Capabilities | `types.rs`: guarantees/satisfaction separate structural, behavioral and algebraic families; only Copy implies Relocatable |
| Concretization | `hir.rs`: `substitute_math_op` and scalar CapabilityBinary use `concrete_behavior_op`; AlgebraicValue uses `zero_value`; already centralized |
| Known shapes | Frontend ownership pass: `known_length`, `known_matrix_shape`, E0345; follows logical views and result selectors conservatively |
| MIR | `mir.rs`: borrowed descriptor lowering, temporary cleanup; ElementwiseBinary and historically named VectorProduct regions |
| Kernel recipes | `elementwise.rs`: ElementwiseKernel and common MathAxis/Input/Stride/Step; `algebraic.rs`: historical VectorProductKernel, five closed ProductKind schedules |
| MIR verification | Resolves actual local/place operand and destination types; kernel.verify reconstructs and compares the whole canonical tree |
| SSA | `ssa.rs`: renames external operands; resolves SSA operand/result types and independently invokes full kernel verification |
| LLVM | Separate elementwise/algebraic translators; same strided-load formula duplicated; checked scalar operations and ordered loops |
| Allocation/empty | `lib.rs`: checked matrix/fixed helpers; Matrix helper preserves shape on null-pointer path; elementwise and MatrixMatrix bypasses duplicate two shape insertions; Vector empty and literal Matrix 0×0 use zero constants |
| Strides/views | `types.rs` closed descriptor recipes; backend checked source indexing and projections remain distinct from already-bounded kernel reads |
| Diagnostics | E0342 family, E0343 exact element, E0344 additive orientation, E0345 shape, E0346 capability; no change of codes required |
| Dumps | Derived deterministic Debug trees expose historical names; explicit kind/selectors/operations/Zero already visible |
| Tests | V21..V33 native values, views/strides, zero axes, generics, counters, strict arithmetic, ownership, modules, dumps and independent HIR/MIR/SSA corruptions; V33 baseline reports 287 tests |

Shared concepts already sound: descriptor recipes, TypeArena capability queries,
concretization, MathStep reuse, complete recipe equality, borrowed input lowering,
fixed storage and temporary cleanup. The shared vocabulary belongs outside the
elementwise module. Actual duplication to remove: frontend family dispatch,
kernel strided-load emission and shape-field construction.

Intentionally separate: source checked indexing versus bounded internal loops;
scalar operations versus owning maps; scalar reduction versus outer product;
output extents versus contraction; consuming transpose versus borrowed views;
structural admission versus behavior/Zero. Existing Vec trees are closed recipes,
not arbitrary schedules: accepting anything beyond canonical equality would
weaken verification. No verifier uses a V31/V32/V33 success flag; historical
names, rather than milestone-dependent validation, are the issue.

## 3. Historical naming found

`VectorAlgebraicProduct`, frontend `VectorProduct`, MIR/SSA `VectorProduct`
and `VectorProductKernel` described all five algebraic pairings, including two
Matrix inputs. These names have been removed from current code. The overly
verbose frontend variant `MatrixAlgebraicProduct` becomes `MatrixMatrix` inside
the explicitly algebraic family. Milestone reports and numbered historical
documentation retain original names as dated evidence.

The LLVM register prefix `vp` is retained deliberately: it is an incidental
private identifier used by existing counter probes, not a family classification.
Keeping it permits byte-identical LLVM and preserves instrumentation. The
`vector_product_recipe` helper still constructs only Inner/Outer oriented-vector
metadata; Matrix recipes reuse its canonical scalar reduction requirements.
Its vector-specific name is accurate at that narrower boundary.

## 4. Files changed

Paths in the first three groups are relative to `compiler-next/crates/`.

| Files | Responsibility |
|---|---|
| `aether-frontend/src/{hir,lib}.rs` | semantic naming, metadata documentation, imports/exports, resolver delegation and existing corruption tests |
| `aether-frontend/src/hir/mathematical.rs` (new) | extracted complete multiplication authority, capability recipes and scalar concretization |
| `aether-middle/src/{algebraic,elementwise,mir,ssa,lib}.rs` | algebraic naming and shared-vocabulary imports; unchanged canonical validation |
| `aether-middle/src/mathematical.rs` (new) | shared closed MathAxis/Input/Stride/Step definitions and axis-role documentation |
| `aether-backend-llvm/src/{algebraic,elementwise,lib}.rs` | use renamed regions, shared strided loads and Matrix shape construction |
| `aether-backend-llvm/src/mathematical.rs` (new) | physical helper authority without changing emitted instructions |
| `aether-driver/tests/vertical{31,32,33}/mod.rs` | rename imports, pattern matches and dump expectations; retain all corruption cases |
| `aether-driver/tests/vertical.rs` | one additional double-transposition native regression |
| `compiler-next/tests/programs/math_arch_1_double_transpose.ae` (new) | repeated transpose views, rectangular product, shape/value/source-ownership checks |
| `compiler-next/tests/compare-math-codegen.py` (new) | reproducible full-module before/after comparison |
| `compiler-next/tests/codegen/math-arch-1.json` (new) | fixture-level equivalence evidence with both SHA-256 hashes |
| `compiler-next/README.md` | current architecture entry point, retaining historical admission sections |
| `docs/architecture/AETHER_COMPILER_ARCHITECTURE.md` | current authority map and core/STD/optimization boundaries |
| `docs/architecture/MATH_ARCH_1_REPORT.md` | this inventory and qualification report |

## 5. Final naming model

| Layer | Name / meaning |
|---|---|
| HIR expression | `HirExprKind::AlgebraicProduct` |
| HIR semantic kind | `AlgebraicProductKind::{Inner,Outer,MatrixVector,MatrixMatrix}` |
| MIR and SSA expression | `Rvalue::AlgebraicProduct`, `SsaOp::AlgebraicProduct` |
| Concrete kernel | `AlgebraicProductKernel` |
| Computational form | `ProductKind::{ReductionKernel,OuterProductKernel,MatrixColumnKernel,RowMatrixKernel,MatrixMatrixKernel}` |
| Executable closed recipe | `ProductStep`, reusing common `MathStep` operations |

The two MatrixVector directions retain `matrix_side` and distinct exact
orientation/result contracts. ProductKind describes computation; the HIR kind
describes semantics. The common names no longer imply Vector-only operands.

## 6. Multiplication resolution authority

`Analyzer::resolve_native_multiplication` in `hir/mathematical.rs` is the single
source decision for mathematical `*`. Its arguments are already typed readable
operands; it returns a closed typed HIR expression. Using those existing variants
as the classification avoids another enum that could disagree with the HIR.

| Pair | Resolved classification and result |
|---|---|
| scalar × Vector / Vector × scalar | VectorScalarMultiply, exact scalar_side, owning Vector<T,O> |
| scalar × Matrix / Matrix × scalar | MatrixScalarMultiply, exact scalar_side, owning Matrix<T> |
| Row × Column | AlgebraicProduct(Inner), scalar T |
| Column × Row | AlgebraicProduct(Outer), owning Matrix<T> |
| Matrix × Column | AlgebraicProduct(MatrixVector, Left), owning Column<T> |
| Row × Matrix | AlgebraicProduct(MatrixVector, Right), owning Row<T> |
| Matrix × Matrix | AlgebraicProduct(MatrixMatrix), owning Matrix<T> |

`binary` retains literal context, borrowed operand resolution and selection of
this entry point when a mathematical family is present. Scalar-only operators
keep ordinary coercion. Resolver ordering, canonical TypeId checks, interning
order, orientation rejection and capability-error precedence are preserved.
Known mismatch remains a frontend check in OwnershipAnalysis, where the required
shape/provenance facts live; it is not duplicated in a type-only dispatch table.
There is no runtime decision, dimension-one exception or hidden dispatch data.

## 7. Mathematical operation taxonomy

Elementwise maps (+/− and scaling), scalar reductions, outer maps, rank-1 maps
of reductions and rank-2 maps of reductions remain closed computational classes.
Result family comes from semantic operand types, independently of runtime shape.
In particular Matrix(1,k)×Matrix(k,1) remains Matrix(1,1), while Row×Column is T.
Buffer/Array/List stay computational containers with zero-based indexing.

## 8. Elementwise kernel architecture

ElementwiseKernel owns pairwise +/− and scaling. Pairwise maps guard dimension
or rows then columns; scaling has no pairwise guard and one invariant scalar.
Allocate is followed by increasing logical For loops, descriptor loads and one
ScalarBinary/InitializeNext per output, ending in YieldOwner. The entire
canonical program, result family, orientation and scalar side are verified.
An empty output still evaluates both source operands, including the scalar.

## 9. Scalar reduction architecture

Inner lowers to ReductionKernel: dimension guard, selected extent, canonical
Zero, one increasing dimension loop, two independent strided loads, Mul then
Add, and YieldScalar. No allocation/store is introduced. The initial addition
to Zero is retained, even for the first term; dimension zero returns Zero.

## 10. Outer/map architecture

Outer lowers to OuterProductKernel: left dimension supplies rows, right dimension
supplies columns, followed by checked Matrix creation, rows/columns loops, two
loads, Mul and one InitializeNext per output. No shape equality, Add or Zero is
required. The existing Matrix helper builds a null descriptor for a zero count
without entering fixed allocation; the later outer-loop bypass stays in place.

## 11. Rank-1 map-reduction architecture

MatrixColumnKernel and RowMatrixKernel have one output axis and a separate
contraction axis. The guard compares Matrix columns with Column dimension or
Row dimension with Matrix rows. Bypass/allocation uses only the output extent.
An outer loop resets Zero, the inner loop executes ordered Mul/Add, and the
post-reduction InitializeNext writes once even when the inner loop has no terms.
The exact result is an owning Column or Row, respectively.

## 12. Rank-2 map-reduction architecture

MatrixMatrixKernel retains left rows, right columns and left columns as three
explicit selectors. ShapeGuardPair checks left columns against right rows before
EmptyMatrixResultBypass(Rows,Columns) and allocation. The loop order remains
Rows → Columns → Contraction, with one Zero and one final store per cell.
Output size checks exclude contraction, so m×0 times 0×n initializes m*n zeros.

## 13. Shared kernel concepts

MathAxis, MathInput, MathStride and MathStep moved from `elementwise.rs` into
middle `mathematical.rs`. Existing shared guards, allocation/traps, bounded
loops, strided loads, scalar operations, initialization and owner yield are
unchanged. ProductStep retains unlike-axis guards, source extent selection,
output bypass and accumulator/scalar-yield metadata. The backend shares the
literal read formula and immutable Matrix shape-field construction.

## 14. Concepts intentionally not generalized

No tensor iteration IR, dynamic rank, configurable loop nests, arbitrary
instruction legality analysis or global pattern-matching verifier was added.
The Vec trees remain inspectable closed recipes whose entire value must equal
the canonical reconstruction. Output stores retain InitializeNext rather than
an arbitrary store-offset language. Source indexing/projection guards, scalar
coercion, owner allocation policy, structural capabilities and borrowing remain
separate responsibilities. Scalar reduction and owning maps have different
escape/allocation contracts and are not collapsed.

## 15. Shape/extent authority

TypeArena fixes family, element and orientation. Frontend recipes fix
MathShapeCheck and exact logical extent selectors; lexical known_length and
known_matrix_shape supply static facts. MIR/SSA reconstruct the concrete
selectors, bypass conditions and loops. Backend fields only implement them.

MathAxis names refer to logical descriptor/loop coordinates, not physical layout.
In Matrix×Column, Rows is output and Columns contraction; Row×Matrix reverses
those roles. In Matrix×Matrix, Rows and Columns both bind output, so Contraction
is distinct. `reduction_axis()` identifies only the loop binding the accumulator;
it cannot authorize allocation or determine result emptiness. Existing names
at those exact narrower boundaries are retained and explicitly documented.

## 16. Zero-axis authority

Row(0) is mathematically 1×0; Column(0) is 0×1. Matrix may carry 0×n, m×0 or
0×0 while `[]` still produces only 0×0 in Matrix context. Nonzero axes survive
queries, views, transpose views, arithmetic and products. Positive output with
zero contraction remains distinct from empty output:

| Operation | Result / allocation and element work |
|---|---|
| Matrix(m,0) × Column(0), m>0 | Column(m), one allocation, m Zero stores, no loads/Mul/Add |
| Row(0) × Matrix(0,n), n>0 | Row(n), one allocation, n Zero stores, no loads/Mul/Add |
| Matrix(m,0) × Matrix(0,n), m,n>0 | Matrix(m,n), one allocation, m*n Zero stores, no loads/Mul/Add |
| Compatible product with empty output extent | null owner, exact extents, no allocator or element work |

The V31..V33 value, IEEE and runtime-counter tests retain these distinctions.
ShapeMismatch guards still precede empty-result bypasses.

## 17. Empty descriptor construction

`emit_matrix_shape` writes rows and columns on a descriptor base. Elementwise
and MatrixMatrix empty paths pass a null-pointer zeroinitializer and both
logical extents; the Matrix helper passes its null/allocated-pointer phi base.
All dynamic Matrix owner creation paths therefore share the same shape-field
authority and preserve nonzero axes without allocating for empty output.

Vector dimension-zero descriptors and literal Matrix 0×0 already have all-zero
fields, so their existing constant construction remains correct and unchanged.
The ordinary fixed allocator deliberately supports zero-byte storage for other
containers/zero-sized elements: it is not changed to force mathematical policy
onto computational containers. No runtime helper, call signature or ABI changed.

## 18. Stride-address authority

Backend `emit_strided_load` now emits both mathematical kernel families' reads:
`ptr + i*stride` or `ptr + r*row_stride + c*column_stride`, independently for
Left and Right. It receives the canonical verified coordinate/stride selectors.
MatrixMatrix uses output/contraction coordinates in the appropriate order.
No row-major source assumption, flattening, inbounds claim, extra load or copy
is introduced. Result owners keep their bootstrap contiguous layout.

Checked one-based source indexing and row/column projection stay in their
existing helpers: they must establish bounds before subtraction/addressing,
whereas kernel coordinates are already bounded by the verified loops. Sharing
those whole control-flow paths would obscure their different proof obligations.

## 19. Generic capability concretization authority

Frontend `concrete_behavior_op` is the sole Behavioral(Add/Sub/Mul) mapping to
checked integer or IEEE HIR operations. Scalar CapabilityBinary substitution,
substitute_math_op and all mathematical recipes use it. `zero_value` is the
single symbolic/concrete Zero constructor, yielding AlgebraicValue for a proven
symbolic T or exact Int(0)/positive Float32/Float64 zero after substitution.
Both functions were already shared and have moved intact into the mathematical
module; no feature-specific mapping table was added.

TypeArena still separates structural Copy/Relocatable/Storable, behavioral
Add/Sub/Mul and algebraic Zero. Requirements are checked parametrically before
instances, including unused bodies and forwarding. Concrete HIR rejects residual
capability metadata. MIR/SSA use their existing concrete scalar dialect and
independently validate operations/types/constants; that is not another generic
capability dispatch. There are no runtime dictionaries or hidden arguments.

## 20. HIR organization

Shared semantic metadata remains next to HirExprKind and public exports in
`hir.rs`. The new child module owns multiplication resolution and mathematical
recipes/concretization. Borrowing, substitution traversal, known-shape analysis
and recursive verification remain in their existing passes. Explicit Init,
view, query, transpose and projection nodes retain their exact contracts.

## 21. MIR organization

AlgebraicProduct lowering still evaluates left then right, borrows descriptors,
selects one canonical concrete kernel, materializes the result and cleans up
temporary owners afterwards. No source owner is consumed by the kernel.
ElementwiseBinary lowering and ordinary ownership states are unchanged.
The change at integration points is the operation/kernel naming and imports.

## 22. SSA organization

SSA renames the same two external dependencies and preserves the concrete closed
region. Loop coordinates and accumulator remain internal bindings until LLVM
CFG emission. Operand enumeration, dominance and ownership handling retain
their existing exhaustive paths under the renamed operation. No MemorySSA,
symbolic behavior, verifier stamp or new SSA operation family is introduced.

## 23. LLVM organization

Elementwise and algebraic translators remain separate. Shared physical helpers
remove duplicated formula/shape-field emission, while each translator retains
its own guard, bypass, loop, accumulator, checked scalar operation and yield
control. Matrix allocation still joins null/allocated pointers before shape
construction. LLVM symbol names, instruction order and runtime helpers remain
byte-identical for all compared modules.

## 24. Verifier architecture

For each of the five product forms and both elementwise ranks, verification
resolves source/result types and reconstructs the canonical recipe. Full equality
checks shape guards/selectors, source sides, allocation extent/traps, output-only
bypass, loop nesting/start/step/order, strides, Zero type/value/sign, Mul/Add or
Add/Sub, initialization count/placement and scalar/owning yield. Input descriptors
must have the exact family/orientation/element; results must have exact owning
or scalar family. No schedule instruction can consume, drop or mutate a source.

No acceptance predicate or corruption case was removed. The moved MathStep
definitions are unchanged; algebraic constructor/verifier algorithms are
unchanged. Canonical constructors remain shared semantic authority, rather than
a general legality solver. Lexical lifetime/provenance authority remains in
frontend, as before; this report does not claim a new global borrow verifier.

## 25. MIR/SSA independence

MIR calls kernel.verify with operand_type from its own operands and the actual
destination. SSA separately calls kernel.verify with its operand_ty and actual
instruction result. Neither accepts an already-verified boolean. Existing tests
corrupt MIR and separately corrupt SSA built from valid MIR, preserving independent
rejection even though both share the canonical recipe definition.

## 26. Diagnostics terminology

The extracted authority preserves E0342 (pairing), E0343 (canonical type), E0344
(elementwise orientation), E0345 (shape), E0346 (capability) and existing
generic/ownership/verification codes. Diagnostic ordering and wording remain
unchanged. The remaining phrase “algebraic Vector multiplication” is used only
for an actual pair of same-oriented Vectors, where it is precise. Products of
matrices use “algebraic multiplication”; no accepted Row×Column is called dot.

## 27. Dump terminology

HIR/MIR/SSA now show AlgebraicProduct rather than Vector-only product names.
HIR retains Inner/Outer/MatrixVector/MatrixMatrix, exact typed result, orientation,
shape_check, source selectors and symbolic/concrete operations/Zero. MIR/SSA
retain the five computational kind names and all output/contraction selectors,
strides, loop bindings and concrete instructions. Derived ordered formatting
remains deterministic. Existing repeated-dump tests now expect current names;
their structural and ABI checks remain intact.

## 28. File/module organization

Three small modules establish ownership where it was previously unclear:
frontend `hir/mathematical.rs` owns resolution and scalar recipes; middle
`mathematical.rs` owns shared recipe vocabulary; backend `mathematical.rs` owns
common physical emission. Elementwise/algebraic files remain coherent semantic
boundaries. No bulk directory move, compiler framework, new crate/dependency or
reorganization of unrelated passes was needed.

## 29. Native-core mathematical boundary

The core owns Vector/Matrix types, exact Row/Column orientation, mathematical
one-based indexing, runtime dimensions/shapes, readable/mutable borrowed views,
transpose views, row/column projections, elementwise +/−, scalar scaling and
the complete native algebraic `*` table. Existing consuming Vector transpose
retains its independent ownership semantics. Core means intrinsic behavior of
these types; it does not imply behavior for Buffer/Array/List.

## 30. Future LinearAlgebra STD boundary

LU, QR, Cholesky, SVD, Schur, Hessenberg, eigendecomposition, solve, least squares,
rank, condition number, iterative solvers and advanced decompositions belong
outside native operator semantics, in future LinearAlgebra STD work. None is
implemented here, and this report does not finalize an API, error model, precision
policy or decomposition representation. Core operators provide the strict
semantic base on which those independent algorithm contracts can be specified.

## 31. Strict numeric semantics

Integers retain checked operations and IntegerOverflow without widening or
wrapping. Floats retain IEEE operations without fast-math, reassociation or
implicit contraction. Every reduction starts at canonical Zero, visits logical
contraction indices in increasing order and executes multiply then add, with
one Add per term including the first. Empty contraction performs no arithmetic
but still initializes every existing output. These are the semantic reference,
not performance claims.

## 32. Future performance OPEN DECISIONS

Fast-math modes, BLAS lowering, SIMD, loop tiling/blocking, parallel reductions,
FMA and reproducibility modes each require explicit future semantic decisions.
In particular, changed reduction order, first-product seeding, silent library
substitution, ownership consumption or allocation elimination cannot be smuggled
in as cleanup. This milestone designs and enables none of those modes.

## 33. Tests preserved/updated

All 287 existing workspace tests remain. V31/V32/V33 imports, operation pattern
matches and dump strings follow the semantic names; no loops generating cases
or assertions about behavior were removed. The same independent corruption
matrices remain, including 84 MIR/SSA cases in V31, 120 in V32 and 184 in V33,
and the existing symbolic/concrete HIR corruptions. V27/V28/V30 elementwise
corruption coverage and V21..V26 view/index/lifetime qualification are unchanged.

One new test, `math_arch_1_double_transpose_preserves_product_and_owners`, executes
a rectangular Matrix product after transposing each input twice, checks all four
values and shape, and writes the result while confirming the sources remain
unchanged and usable. Together with existing both-transposed fixtures it covers
both meanings of double transposition in the equivalence target.

## 34. Exact final test counts

`cargo test --workspace`: **288 passed, 0 failed, 0 ignored**. All 287 baseline
tests are preserved and one native double-transpose regression is added.

| Suite | Passed |
|---|---:|
| Backend LLVM | 7 |
| Driver integration | 219 |
| Frontend | 40 |
| Middle | 22 |
| Total | **288** |

Driver library/binary unit suites and the four doc-test suites contain zero
tests and all complete successfully. Final qualification commands:

```sh
# From compiler-next
cargo test --workspace
cargo fmt --all --check
cargo clippy --workspace --all-targets -- -D warnings
# From repository root
git diff --check
bash compiler-next/tests/run-differential.sh
```

All pass. The first implementation run caught an incorrectly placed extracted
Matrix-shape helper; that placement was corrected before the successful full
run and byte-equivalence comparison. The new fixture was also corrected to use
the existing conditional syntax. Neither correction changes the compiler's
accepted language or weakens any test. Logs from this qualification are local
to `/tmp/aether-math-arch-1/`; the durable codegen evidence is checked in below.

## 35. Differential result

`bash compiler-next/tests/run-differential.sh`: **21 checked, 0 failures**.
Legacy-equivalent cases, intentional scalar-width differences and rejection
comparisons all retain their prior results. The harness itself is unchanged.

## 36. LLVM equivalence findings

Before edits, the V33 baseline driver was built and copied to
`/tmp/aether-math-arch-1/baseline`; 53 original V27..V33 fixture modules were
captured. The checked-in comparison script invokes that preserved binary and the
final driver on exactly the same paths and compares complete LLVM without
normalizing symbols, helpers, register names, whitespace or instruction order.
Only CLI framing/status text is excluded. Both versions also link each module
through clang. The additional double-transpose fixture compiles with the original
baseline as well; it does not require any new source feature.

| Required comparison | Fixture |
|---|---|
| Vector add | `v27_vector_contiguous.ae` |
| Matrix scale | `v28_matrix_contiguous.ae` |
| Row×Column | `v31_inner_concrete.ae` |
| Column×Row | `v31_outer_concrete.ae` |
| Matrix×Column | `v32_matrix_column.ae` |
| Row×Matrix | `v32_row_matrix.ae` |
| Matrix×Matrix | `v33_rectangular.ae` |
| Both input matrices transposed | `v33_both_transposed.ae` |
| Each input matrix transposed twice | `math_arch_1_double_transpose.ae` |
| Zero-contraction Matrix×Matrix | `v33_zero_contraction.ae` |

**54 complete LLVM modules compared, 54 byte-identical, 0 differences.**
Exact fixture-level findings and both hashes are in
[`math-arch-1.json`](../../compiler-next/tests/codegen/math-arch-1.json).
The original 53 fixtures also cover generic operations, IEEE, control flow,
evaluation order, projections and zero axes. No material LLVM change is accepted.
Reproduce from compiler-next after building separate baseline/final drivers:

```sh
python3 tests/compare-math-codegen.py \
  --baseline-binary /tmp/aether-math-arch-1/baseline \
  --baseline-revision ec520fff2711e0bf1f091e40438e4991ec0962d5
```

The temporary baseline path is session-local; future reproduction must build
that revision separately. The script never checks out or edits the working tree.

## 37. Compile snapshot findings

Not measured. Compilation timing is optional for this architecture milestone.
No runtime or compilation performance improvement is claimed from refactoring.

## 38. Legacy status

No changes to `compiler-rs`, legacy runtime/CLI, or `scrap`. No dependencies,
runtime ABI, layout, mangling or public source capability changes. The
pre-existing untracked FaCAether/FaCAetherO0 files remain untouched. No commit,
merge, publication or deployment was performed.

## 39. Accepted debt

Canonical recipes remain inspectable Vec trees validated by exact equality;
internal control flow expands only in LLVM. HIR and middle retain different
semantic/computational tags deliberately. The broad HIR traversal and ownership
passes remain in the existing large file. Borrowing is lexical/conservative,
the target and ABI are bootstrap Linux x86_64, traps are abortive, and operator
satisfaction is built-in/homogeneous. Fixed allocation policy for other storage
families remains separate from mathematical emptiness. None of this is new debt
introduced by a relaxed verifier or changed source semantics.

## 40. Other OPEN DECISIONS

User operator implementations, heterogeneous results, widening, Complex/Hermitian
semantics, generic orientation, stored/nonlexical lifetimes, slices/submatrices,
negative strides, public ABI and future STD API contracts remain outside scope.
Changes to those areas would require their own admission and qualification.
No deferred decision is necessary to use the consolidated existing operations.

## 41. Architectural risks still present

Shared constructors mean a bug in a canonical recipe can affect lowering and
both verifiers together; independent runtime values/order/counters and corruption
tests remain essential. Verification success tokens are not a replacement for
SSA revalidation. Closed recipe extension must explicitly specify output and
contraction roles, particularly empty contraction with positive output. A new
dynamic Matrix result path must preserve both axes through emit_matrix_shape;
literal 0×0 zero construction must not be copied into such a path. The backend
still trusts verified descriptor provenance and bounded coordinates, while global
lifetime authority remains frontend. These limits are documented rather than
silently widened by a generic-kernel abstraction.

## 42. Recommended next major workstream

Move to explicit design/admission of the general-purpose foundations needed by
future native STD code, especially function result/error and module/library
boundaries, before implementing advanced LinearAlgebra algorithms. Preserve this
strict native arithmetic as the reference. Decomposition/solver APIs and any
performance modes should be independently specified and qualified; another
operator extension is not implied by mathematical shape similarity.
