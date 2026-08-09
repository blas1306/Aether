# O2.6 conservative loop-invariant code motion

O2 runs `LoopInvariantCodeMotion` after proven Array/List/Vector/Matrix BCE and
before final SSA DCE. O0 and O1 do not contain it. It uses the existing natural
loops, dominators, and canonical preheaders; no CFG canonicalization is added.

## Safety contract

An instruction moves only when effect metadata says it is pure, nonthrowing,
nontrapping, nonallocating, and memory-free; every operand is defined outside
the loop or by an already selected instruction; and its block dominates every
loop latch and exiting block. This rejects conditional and early-exit paths.
Zero-trip evaluation is harmless for this closed set because it has no effect
or failure mode. Stable inner-to-outer, block, and instruction order supplies
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
`SSAListGet`, `SSAVectorGet`, `SSAMatrixGet`, `SSAVectorLength`,
`SSAMatrixRows`, `SSAMatrixColumns`, `SSAArraySet`, `SSAListSet`,
`SSAVectorSet`, `SSAMatrixSet`, `SSAArrayLength`, `SSAListLength`,
`SSAListIsEmpty`, `SSAPackException`, `SSACatchEntry`, `SSAExceptionMatch`,
`SSAExceptionPayload`, `SSAExceptionDestroy`, `SSAPhi`, `SSABranch`, `SSAJump`,
`SSAThrow`, `SSARethrow`, `SSAPropagate`, and `SSAReturn`.

Thus all calls, allocations, aggregates, memory and metadata reads, writes,
ARC/lifecycle, ownership transfer, phis, terminators, and exception operations
are excluded. Array/List length and Vector/Matrix metadata are deferred, so
O2.6 does not need an alias/mod-ref query. O2.4 remains the basis for a future
memory-read LICM extension.

## Statistics and follow-up

Statistics cover loops, irreducible regions, absent preheaders, candidates,
hoists, each blocking reason (trap, throw, control, variant, memory/mod-ref,
ownership/effects, unsupported kind), and hoists per class.

LLVM may later perform the same scalar motion; O2.6 merely exposes simpler SSA
earlier. Memory-read LICM is recommended next. Calls, speculation, ARC
optimization, GVN/CSE, and loop canonicalization remain deferred.
