# Aether Sequence Sort Design

## Status And Scope

This document defines the implemented common sorting contract for `List<T>`
and `Array<T>`. The frontend, interpreter, common `IRSequenceSort` /
`SSASequenceSort` instruction, optimizers, and LLVM helpers implement this
contract.

The contract applies to both method calls:

```aether
xs.sort(); // List<T>
a.sort();  // Array<T>
```

The existing `sort(xs)` builtin remains a compatibility surface. Every
spelling that reaches sequence sorting has the semantics in this document.

## Normative V0 Contract

`sort()`:

- sorts the elements in ascending order;
- mutates the receiver in place and returns `void`;
- does not construct or return a new collection;
- preserves the identity of the collection, so all aliases observe the new
  order;
- preserves `length`;
- preserves the fixed size of an `Array<T>`; and
- preserves the capacity of a `List<T>`.

An implementation may allocate temporary working memory. That memory is not a
new public collection and must not replace the receiver, its public identity,
or its capacity.

```aether
List<int> a = {3, 1, 2};
List<int> b = a;

b.sort();

// a and b refer to the same list and both observe {1, 2, 3}.
```

The same aliasing rule applies to arrays. A call through a receiver rooted in
a `const` variable is a compile-time mutation error, consistently with other
in-place collection operations.

## Orderable Element Types

The v0 allowlist is deliberately closed:

| Element type | `sort()` | Order |
| --- | --- | --- |
| `int` | allowed | ascending signed numeric order |
| `double` | allowed | total order defined below |
| `string` | allowed | deterministic lexicographic order defined below |
| `boolean` | rejected | no v0 ordering |
| reference type | rejected | no address or deep ordering |
| nested `List`, `Array`, `Vector`, or `Matrix` | rejected | no aggregate ordering |
| any other type | rejected | no ordering unless a later design opts it in |

`boolean` is rejected even though an implementation could choose
`false < true`. Aether v0 does not otherwise define relational ordering for
booleans, so `sort()` must not introduce one implicitly.

Classes, structs, interfaces, enums, nullable values, and other reference or
structured values are not ordered by this contract. In particular, an
implementation must not compare addresses, object identities, fields, or
elements recursively. Future user-defined ordering requires a separate design.

The typechecker must reject unsupported element types when the receiver type is
known. It must not defer such failures to runtime:

```aether
List<boolean> flags = {true, false};
flags.sort(); // compile-time error: boolean has no v0 sequence order

Array<List<int>> rows = {{2}, {1}};
rows.sort(); // compile-time error: nested collections are not orderable
```

The rule is identical for `List<T>` and `Array<T>` and for all supported call
spellings.

## String Order

Strings use lexicographic comparison of their UTF-8 encoding, treating each
byte as unsigned. At the first differing byte, the string with the smaller byte
sorts first; if one encoding is a prefix of the other, the shorter string sorts
first.

This order is:

- deterministic;
- case-sensitive;
- independent of the process locale; and
- compatible with an initial runtime implementation that compares UTF-8 bytes.

It does not perform Unicode normalization, case folding, locale-sensitive
collation, or language-specific ordering. Consequently, canonically equivalent
Unicode spellings need not compare as equal. This is a storage-level,
deterministic order rather than linguistic collation.

## `double` Total Order

Sorting `double` must not use the IEEE partial comparison as the whole sorting
predicate, because unordered NaN comparisons do not define a valid sort order.
The sequence order is instead:

1. All non-NaN values sort by numeric value.
2. Negative infinity sorts before every finite value; positive infinity sorts
   after every finite value.
3. `-0.0` and `+0.0` are equivalent for ordering.
4. Every NaN sorts after every non-NaN value.
5. All NaNs are equivalent for ordering, regardless of sign, payload, or bit
   representation.

Because the sort is stable, the input order is retained within the
order-equivalent groups of signed zeroes and NaNs. Sorting never rejects a
sequence merely because it contains NaN.

## Stability

The public `sort()` contract is stable. If two elements are equivalent under
the order above, their relative input order is preserved in the result.

Stability makes behavior deterministic for signed zeroes, NaNs, duplicates,
and future key- or comparator-based APIs. It is a semantic requirement, not an
accidental property of the initial algorithm; implementations may change only
if they continue to preserve it.

## Shared `List` And `Array` Semantics

`List<T>` and `Array<T>` share exactly one definition of:

- the orderable-type allowlist;
- ascending comparison;
- string ordering;
- `double`/NaN ordering; and
- stability.

Their representation is the only relevant difference. `Array<T>` has fixed
size. `List<T>` has dynamic length and capacity, although sorting changes
neither. A backend must not let representation details create observable
differences in ordering.

A future `Sequence<T>` interface or similar hierarchy could expose common
operations. `sort`, `reverse`, `contains`, `indexOf`, `length`, and `isEmpty`
are candidates, but this document neither chooses the hierarchy nor implements
it. Existing naming differences such as `is_empty` also remain outside this
design.

## Backend Strategy

Three broad implementation approaches are possible:

| Approach | Advantages | Costs and risks |
| --- | --- | --- |
| Emit the algorithm directly in IR/LLVM | no runtime call boundary; optimizer can see the loop | large lowering and SSA surface; duplicated control flow; string and NaN comparison remain specialized |
| Runtime helper specialized by element type | simple lowering; comparison policy is centralized; reusable by arrays and lists | several helpers and a runtime ABI; temporary allocation and string representation must be handled |
| Generic helper plus comparator function | one sorting core; extensible to future comparators | indirect-call ABI and optimizer complexity; premature for the closed v0 type set |

The recommended initial backend is a family of storage-oriented runtime helpers
shared by both containers, for example:

```text
aether_sort_i32(data, length)
aether_sort_f64(data, length)
aether_sort_string(data, length)
```

Names and exact ABI are not normative. The important property is that `Array`
and `List` pass their data and current length to the same type-specialized
semantics rather than growing independent sorting implementations. The `f64`
helper owns the NaN policy and the string helper owns unsigned UTF-8 byte
comparison. This keeps those rules consistent across the AST interpreter and
compiled backend as well.

## Algorithm Guidance

The algorithm is not part of the public contract, except that it must be
stable. Relevant initial choices are:

- Insertion sort is stable and very small, and performs well on short or nearly
  sorted ranges, but is quadratic for general input.
- Merge sort is stable with predictable `O(n log n)` time and is straightforward
  to share across both container representations, but normally needs `O(n)`
  auxiliary storage.
- Conventional in-place quicksort is compact and often fast, but is not stable
  and has a quadratic worst case without additional safeguards.
- Timsort is stable and strong on partially ordered data, but is substantially
  more complex for an initial runtime.

Use stable merge sort as the initial general algorithm, optionally with stable
insertion sort for small merge runs. The auxiliary buffer does not alter the
receiver's identity, length, array size, or list capacity. A later stable
algorithm may replace it without changing language semantics.

## Compile-Time Errors

Static checking must diagnose `sort()` on:

- `List<boolean>` or `Array<boolean>`;
- reference types, including classes and interfaces;
- structs, enums, and nullable types unless a future ordering design admits
  them explicitly;
- nested lists or arrays;
- vectors and matrices, whether direct or nested; and
- every other element type outside the v0 allowlist.

The diagnostic should identify both the receiver element type and the closed
set of supported types. Runtime type dispatch is not a substitute when `T` is
known statically.

## Required Future Tests

When the contract is implemented, minimum coverage for both `List` and `Array`
is:

- empty and one-element sequences;
- already sorted and reverse-ordered input;
- duplicates and explicit stability checks;
- ascending `int` values;
- finite `double` values, both infinities, signed zeroes, and multiple NaNs;
- empty, prefix-related, mixed-case, ASCII, and non-ASCII strings;
- aliases observing the in-place mutation;
- unchanged identity, length, array size, and list capacity;
- compile-time rejection of every unsupported type category; and
- behavioral parity between the AST interpreter and LLVM backend.

Tests should include different NaN payloads and preserve their relative input
order without requiring NaN bit patterns to compare as language-level values.

## Deferred Extensions And Open Questions

The following are explicitly not part of v0 `sort()`:

- `sortDescending`;
- comparator or comparison-function arguments;
- key functions;
- overloads; and
- a `reverse` parameter.

Open integration questions, none of which changes the semantic contract above:

- the final runtime helper names and string ABI;
- how helper allocation failure is reported;
- whether and when `sort(Array<T>)` is added as a global builtin in addition to
  `Array<T>.sort()`; and
- whether a future common collection hierarchy is named `Sequence<T>` and
  which naming convention it uses for `isEmpty`/`is_empty`.
