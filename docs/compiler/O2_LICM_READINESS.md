# O2.5.5 LICM readiness audit

This milestone only observes O1 SSA (the pre-BCE inventory). It does not move,
delete, or synthesize instructions or preheaders.

## Measured loop and opportunity inventory

Across the 16 representative workloads, loop analysis found 15 natural loops,
all 15 with canonical preheaders, no irreducible regions, and no multi-latch
loops. Header, latches, body, exits, parent/children, depth, induction facts,
and dominance are available. Multi-latch representation is a set and is
therefore structurally adequate, but repository evidence does not exercise it.
Exceptional CFG is supported by the CFG, but the sample supplies no
exceptional loop. Loop canonicalization is therefore **not required before the
first LICM**, while a later canonicalization milestone is appropriate when
real missing-preheader opportunities appear.

The conservative syntactic census found 142 possible value-producing sites:
42 immediately hoistable, 51 loop-variant, 32 may-trap, and 17 calls excluded
as may-throw/opaque. The instruction matrix is:

| Class | Ready | Variant | Trap | Throw/call | Alias |
|---|---:|---:|---:|---:|---:|
| Scalar arithmetic/constants/copies | 42 | 21 | 29 | 0 | 0 |
| Comparisons | 0 | 30 | 0 | 0 | 0 |
| Array/List length | 0 | 0 | 3 | 0 | 0 |
| Calls | 0 | 0 | 0 | 17 | 0 |

The 42 include trivial constants, so they overstate valuable work. This corpus
contained no in-loop pure-math, shape metadata, field read, or collection-read
candidate accepted by the conservative classifier. Scientific workloads
(Newton-Raphson/ProbandoNR, numerical methods, Matrix/Vector/Array loops) expose
mostly scalar candidates which clang already hoists well. The distinctive
Aether opportunity is a proven-unmodified high-level length/shape read, but
current length instructions are trapping and consequently excluded initially.

## Exact initial policy

The first pass should be non-speculative and process inner loops before outer
loops. A candidate may move to the nearest loop preheader only when:

1. every operand definition dominates the insertion point or has already been
   proven invariant for that loop;
2. a canonical preheader exists and the loop is natural/reducible;
3. it has no side effect, allocation, write, throw, trap, panic, ownership, or
   lifecycle behavior;
4. moving it cannot make a conditionally executed operation execute on a new
   path (initially require safe speculation or guaranteed execution);
5. any read location has no loop writer under alias/mod-ref; `MAY_ALIAS +
   MAY_MODIFY` fails closed.

Thus `SAFE_CANDIDATE` initially means nontrapping scalar constants, copies,
unary operations, arithmetic and comparisons with invariant operands.
`CONDITIONAL` includes pure math whose declared effects are safe, List/Array
length, Vector/Matrix metadata, field/collection reads, and direct calls.
`NEVER_HOIST` initially includes phis/induction variables, mutations, bounds
checks, division/modulo and checked arithmetic, allocations, all invokes and
interface/indirect calls, exception pack/destroy/catch/rethrow operations,
retain/release/destroy/move, and interface boxing.

O2.4 can answer whether a loop modifies a semantic whole-object/List/Array
location and can retain facts across precise nonmodifying direct calls. It is
sufficient for a later read LICM slice but field insensitivity, unknown globals,
parameter aliasing, indirect targets, and open interface dispatch cause safe
misses. Calls should not be hoisted in v1 even when their summary is read-only.
Length reads presently carry may-trap semantics, so alias proof alone is not
authorization. Moving any value-producing operation must also be checked for
implicit owned results; allocations, boxes, ARC, and transfers stay fixed.

For nested loops, invariance is evaluated relative to each loop: a value may be
outer-variant but inner-invariant and must then target only the inner
preheader. Header phis and loop-carried definitions remain variant. Multiple
latches are handled as a set; every incoming/update path must agree. Break,
continue, early return, zero-trip loops and conditional bodies require the
non-speculation rule. Irreducible regions are explicitly reported and skipped.

## LLVM overlap and recommended scope

clang `-O2` already handles ordinary scalar LICM in the sampled emitted LLVM.
Aether should initially implement only semantic, nontrapping scalar LICM and
use it to establish the transformation/verifier contract. A follow-up may add
proven-nontrapping immutable shape/length and field reads where O2.4 proves no
interfering write. Do not start with calls, general loads, ARC or allocation.

## Verification and future tests

After every transform run SSA structural/type verification, dominance,
ownership/lifecycle, exceptional-CFG, and effect consistency checks. Each moved
definition must dominate every use, remain outside its source loop, preserve
operand dominance, target exactly one preheader, and never move a phi,
terminator, may-trap/may-throw, side-effecting, allocating, or ownership
instruction.

Positive tests: scalar invariant, proven-safe length/shape read in the later
slice, nested inner-only and outer+inner invariants, and a NO_ALIAS read.
Negative tests: checked arithmetic/division, may-throw call, same-location and
MAY_ALIAS writers, conditional-only execution, missing preheader, irreducible
and multi-latch edge cases, ownership/allocation, and induction dependence.
Semantic tests must pin panic and exception ordering, zero-trip behavior, side
effects, lifecycle counts, output and O0/O1 parity.

## Recommendation

**PROCEED_TO_LICM**

Start with non-speculative, nontrapping, nonthrowing scalar pure instructions
with invariant operands and existing canonical preheaders. Preheader
canonicalization is not required first. No production behavior changed and no
commit was created by this audit.

## O2.6 implementation status

The recommended scalar-only slice is implemented. `O2_LICM.md` is the current
contract for eligibility, control safety, ordering, statistics, and deferrals.
