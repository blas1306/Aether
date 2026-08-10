# O2.4 alias and mod/ref analysis

Status: implemented as an opt-in, read-only SSA analysis. It is not a pass and
does not alter O0/O1/O2 membership or generated code.

## Semantic model

Scalars and enums copy values. Structs, method-result tuples, Vector and Matrix
are aggregate values: copies do not alias aggregate storage, although contained
reference fields retain their identities. Strings and classes are reference
identities; nullable values retain their payload semantics.

Array and List copies are explicit allocating `array_copy`/`list_copy`
operations with independent collection storage. Reference elements can still
share identities. Slices allocate independent storage. Borrowed collection
elements alias an element only for their verifier-enforced lexical scope; SSA
parameters have no general noalias contract.

An interface is `{carrier,witness}`. Class-backed construction retains carrier
identity; struct-backed construction owns a fresh box. Witness identity is not
object identity. Interface calls use conservative union semantics and do not
devirtualize. Function values and uncontracted native calls remain opaque.

## Lattice, provenance, and locations

`AliasRelation` is `MUST_ALIAS`, `NO_ALIAS`, or `MAY_ALIAS`. A value must-aliases
itself. Distinct intrafunction fresh roots do not alias. Parameters, unknown
returns, and non-identical phi root sets may alias. Phi joins union roots and
fail closed. Roots distinguish fresh objects/storage, parameters, values,
interface carriers, and unknowns.

O2.7 adds nominal, one-level field locations alongside whole class objects,
Array/List storage and length, Vector/Matrix values, interface carriers/boxes,
and unknown global state. Class fields on a proven common base are disjoint;
struct updates reconstruct values. Whole-object effects still overlap every
field. See `O2_FIELD_SENSITIVE_MODREF.md`.

## Mod/ref and summaries

`ModRefEffect` is `NO_ACCESS`, `READ`, `MODIFY`, `READ_MODIFY`, or `UNKNOWN`.
The API supplies `effects`, `may_read`, `may_modify`, memory/length/shape fact
preservation, and loop modification queries over the existing generic
`InstructionEffects` model.

Direct summaries record read/modified parameters, returned parameter aliases,
fresh returns, allocation, global access, traps, throws, and unknown reasons. A
deterministic monotone fixed point handles recursion and mutual recursion. A
mutation remains visible on exceptional propagation. Indirect/interface and
unknown external calls remain conservative. Lifecycle metadata is distinct
from logical length/shape; no ARC operation is removed.

Unknown reasons cover external calls, indirect targets, interface
implementations, phi merges, parameter aliasing, global state, field
insensitivity, unsupported instructions, and other. Debug output is sorted and
verification checks alias reflexivity/symmetry and fixed-point convergence.

## Coverage, complexity, and limitations

The API preserves List length across arithmetic/reads, mutation of a distinct
fresh object, and a summarized nonmodifying call. It invalidates on
`MAY_ALIAS + MAY_MODIFY` and opaque calls. Two O2.1.5 List records were dominated
by call invalidation and form the immediate future re-audit pool; O2.4 neither
reclassifies nor removes them.

Alias queries are linear in small root sets (normally constant). Provenance is
a bounded monotone SSA scan. Summary convergence height is proportional to
parameter-effect bits and scans instructions per iteration. Loop queries are
linear in loop instructions.

Limitations: no deep field paths, no global-location inventory, no
escape analysis, no exact indirect target sets, no closed interface world, and
no caller provenance for summarized return aliases. The recommended next
consumer is List BCE after integrating and measuring fact transfer. LICM, ARC,
and escape transformations remain later work.

## O2.6 consumer status

Initial LICM intentionally excludes every memory-derived instruction, so it
does not yet query mod/ref. These APIs remain the required authority for the
recommended follow-up memory-read LICM; no logic was duplicated in O2.6.
