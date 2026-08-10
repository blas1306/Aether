# O2.7 field-sensitive mod/ref foundation

Status: implemented as read-only analysis infrastructure. No optimization pass
consumes field locations and no generated code changes.

## Semantic model and locations

`FieldIdentity(owner, name, index)` is nominal: `A.x` and `B.x` are unrelated
even when their spelling and index match. The bounded location vocabulary is
`ObjectLocation`, `FieldLocation`, `StructFieldLocation`,
`CollectionStorageLocation`, and `CollectionLengthLocation`. Locations refer to
Aether semantic cells, never byte offsets.

Classes preserve reference identity. A class get reads one field cell and a
class set modifies one field cell; initialization uses the same conservative
effect. Must-alias bases and equal fields must-alias. Distinct nominal fields on
aliasing bases do not alias. No-alias bases imply no-alias fields, while
may-alias bases retain may-alias for compatible fields. A whole-object access
overlaps all its fields.

Structs are SSA values. `struct_set` reconstructs a new aggregate and does not
modify the input value. `struct_get` denotes a field of that value. Copying a
struct copies its cells, but a reference-like value held in a copied cell still
denotes the same referenced object. The field cell and that object's storage are
therefore distinct locations.

Arrays and Lists have reference storage; their storage location includes their
logical length for conservative writes. Strings are reference-like but have no
mutable public storage. Vector and Matrix remain value aggregates. Nullable
values retain their payload model. A field rebinding modifies only its cell and
does not itself mutate either the old or new referenced object.

## Calls, exceptions, and ownership

Direct-call summaries add read/modified nominal fields relative to a receiver
or parameter. These sets participate in the same deterministic monotone union
fixed point as coarse parameter effects, including recursion. Constructor field
sets are ordinary class field modifications. Effects executed before throwing
remain in the summary because all CFG blocks, including exceptional paths, are
scanned.

Indirect and unknown external calls remain coarse. Interface calls report
`INTERFACE_FIELD_LAYOUT_UNKNOWN`: witness dispatch does not imply common field
layout and is not devirtualized. ARC retain/release accesses ownership metadata,
not the semantic field cell, and remains `NO_ACCESS` in this model.

Consumers use `effects`, `preserves_memory_fact`, `preserves_field_fact`, and
`field_effects`; they need not inspect summary maps. Debug rendering sorts
fields and unknown reasons deterministically.

## Complexity and limitations

One-level sensitivity bounds location growth by the number of accessed nominal
fields. A location alias query performs one existing base query plus constant
field comparison. Summary height and storage grow by the number of
parameter-field effect bits; fixed-point behavior remains monotone. Arbitrary
nested paths are deliberately unsupported. A load of a reference-like field can
be modeled as a field cell and later collection/object identity, but this
milestone does not perform flow-sensitive rebinding or general loaded-reference
provenance. Interface layout, globals, indirect targets, external mutation,
escape analysis, and public purity/noalias contracts remain conservative.

The added precision proves a read of `obj.a` preserved across `obj.b = value`,
including a known direct call that writes only `b`. It does not enable field-load
LICM, BCE, ARC removal, escape analysis, inlining, or devirtualization. The next
recommended milestone is ownership/escape analysis: the measured general-read
LICM set still lacks a complete nontrapping loaded-reference provenance story.

## O2.8 integration

`obj.a = value` now records a field escape of `value` without conflating a
write to `obj.b`. Arbitrary nested loaded-reference paths remain conservative.
