# O2.6.1 alias-proven immutable read LICM

O2 runs `LoopInvariantCodeMotion` after proven Array/List/Vector/Matrix BCE and
before final SSA DCE. O0 and O1 do not contain it. It uses the existing natural
loops, dominators, and canonical preheaders; no CFG canonicalization is added.

## Safety contract

Scalar instructions move only when effect metadata says they are pure,
nonthrowing, nontrapping, nonallocating, and memory-free. The separate
`READ_ELIGIBLE_IF_MODREF_PROVES_INVARIANT` class contains only
`SSAArrayLength`, `SSAListLength`, `SSAVectorLength`, `SSAMatrixRows`, and
`SSAMatrixColumns`. Every operand must be defined outside
the loop or by an already selected instruction; and its block dominates every
loop latch and exiting block. This rejects conditional and early-exit paths.
Length reads are nonfailing for valid, live typed collection values: allocation
limits keep their conversion within Aether `Int`. The lifetime/SSA verifier
excludes invalid references. The same control criterion is nevertheless used,
so conditional reads and zero-trip speculation remain rejected. Stable
inner-to-outer, block, and instruction order supplies
fixed-point dependency order. Movement is immediately before the preheader
terminator. Source metadata stays on the unchanged instruction object.

Pipeline verification after the pass covers SSA structure, dominance, types,
ownership/lifecycle, and exceptional CFG invariants.

## Complete instruction audit

`InstructionEffects` is primary, followed by the closed scalar allowlist.

`ALWAYS_ELIGIBLE_IF_OPERANDS_INVARIANT` (also subject to control and scalar
type checks): `SSAConst`, `SSAUnaryOp`, scalar `SSACompareOp`.

`CONDITIONALLY_ELIGIBLE`: `SSABinaryOp` and `SSACast` only when their dynamic
effects report no trap. Checked integer overflow, integer division/modulo,
string concatenation, and checked double-to-int conversion are excluded.
Floating operations preserve IEEE operation order: there is no reassociation,
FMA contraction, reduction reordering, or fast-math.

`NEVER_HOIST_INITIAL_LICM`: `SSACall`, `SSAInvoke`, `SSAFunctionRef`,
`SSACallIndirect`, `SSAInvokeIndirect`, `SSAPrint`, `SSAStructNew`,
`SSAClassNew`, `SSAClassGet`, `SSAClassSet`, `SSAInterfaceConstruct`,
`SSAInterfaceCall`, `SSAInvokeInterface`, `SSAStructGet`, `SSAStructSet`,
`SSAMethodResultNew`, `SSAMethodResultReceiver`, `SSAMethodResultValue`,
`SSAArrayNew`, `SSAListNew`, `SSAArrayCopy`, `SSAListCopy`, `SSAListContains`,
`SSAListIndexOf`, `SSAListClear`, `SSAListPush`, `SSAListInsert`,
`SSAListRemoveAt`, `SSAListPop`, `SSAListReverse`, `SSASequenceSort`,
`SSAVectorNew`, `SSAMatrixNew`, `SSAVectorAdd`, `SSAVectorSub`,
`SSAVectorScale`, `SSAVectorDot`, `SSAOuterProduct`, `SSAMatrixAdd`,
`SSAMatrixSub`, `SSAMatrixScale`, `SSAMatrixMatMul`, `SSAMatrixVectorMul`,
`SSAVectorMatrixMul`, `SSAArrayGet`, `SSAArraySlice`, `SSAListSlice`,
`SSAListGet`, `SSAVectorGet`, `SSAMatrixGet`, `SSAArraySet`, `SSAListSet`,
`SSAVectorSet`, `SSAMatrixSet`,
`SSAListIsEmpty`, `SSAPackException`, `SSACatchEntry`, `SSAExceptionMatch`,
`SSAExceptionPayload`, `SSAExceptionDestroy`, `SSAPhi`, `SSABranch`, `SSAJump`,
`SSAThrow`, `SSARethrow`, `SSAPropagate`, and `SSAReturn`.

Thus all calls, allocations, arbitrary element/field reads, writes,
ARC/lifecycle, ownership transfer, phis, terminators, and exception operations
are excluded. Array length is immutable for an Array identity. List length is
hoisted only when O2.4 proves that every loop instruction preserves that exact
semantic length fact; aliasing mutations and unknown indirect/interface calls
therefore block it, while mutations of proven-disjoint fresh Lists and known
read-only direct calls do not. Vector/Matrix shape uses the existing shape
preservation query; no field-sensitive heap analysis is added.

Vector length is an explicit SSA read. Matrix rows and columns are explicit SSA
metadata instructions whose dimensions are carried as compile-time integers;
O2.6.1 does not invent any additional runtime read.

## Statistics and follow-up

Statistics additionally report read candidates/hoists, per-collection hoists,
and conservative blockers for modification, unknown calls, base variation,
control/speculation, alias, and exceptional uncertainty.

The fixed O2 order remains BCE -> LICM -> DCE. LICM constructs fresh mod/ref
queries after BCE rather than reusing analysis state from before transformation.
LLVM may duplicate some length-load motion; Aether's semantic List summaries
can prove preservation across operations whose native aliasing is less clear.
Calls themselves, speculation, ARC optimization, GVN/CSE, and loop
canonicalization remain deferred.
