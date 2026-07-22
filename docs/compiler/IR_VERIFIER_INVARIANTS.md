# Python IR verifier invariant inventory

This document is the Phase 0, Step 1 inventory of the semantic rules enforced
by `src/aether/ir/verifier.py`. It describes the verifier as it exists today; it
does not endorse every rule as a permanent IR contract and does not change
diagnostics or runtime behavior.

`IRV-NNN` identifiers are the canonical, stable names for these rules. Future
Python and Rust verifiers may share them, but the current Python verifier does
not emit them yet. An identifier must not be reused if a rule is removed. A
rule may be split only by allocating new identifiers and retaining the old one
as a documented umbrella or retired identifier.

The inventory uses one identifier per independently implementable contract.
Shared prerequisites such as definition-before-use are documented once and are
referenced by instruction contracts instead of being duplicated. A contract's
description lists every conjunct checked at its cited location.

## Definitions and types

| ID | Short title | Description | Verifier location | Category |
| --- | --- | --- | --- | --- |
| IRV-001 | Unique struct definitions | Nominal struct definition names are unique within a module. | `_verify_struct_definitions` (lines 187–189) | Definitions |
| IRV-002 | Non-empty struct names | Every nominal struct definition has a non-empty name. | `_verify_struct_definitions` (lines 191–193) | Definitions |
| IRV-003 | Unique struct fields | Field names are unique within each struct definition. | `_verify_struct_definitions` (lines 194–196) | Definitions |
| IRV-004 | Valid struct field types | Every struct field has a valid, complete IR type and is not `void`. | `_verify_struct_definitions` (lines 197–201) | Types |
| IRV-005 | Finite by-value struct layout | The graph of direct `StructType` fields is acyclic, so recursive by-value struct layouts cannot have infinite size. | `_verify_struct_definitions.visit` (lines 202–224) | Types |
| IRV-006 | Unique function names | Function names are unique within a module. | `_verify_module` (lines 175–185) | Definitions |
| IRV-007 | Unique parameter names | Parameter names are unique within a function. | `_verify_parameters` (lines 311–322) | Definitions |
| IRV-008 | Unique block names | Basic-block names are unique within a function. | `_collect_blocks` (lines 324–330) | Definitions |
| IRV-009 | Unique value names | Parameters and all instruction results share one function-wide namespace and each name has exactly one definition, including definitions in unreachable blocks. | `_collect_value_types`, `_define_value_type` (lines 374–398) | Definitions |
| IRV-010 | Stable slot types | Every occurrence of a storage name has the same IR type. | `_collect_slot_types` (lines 400–413) | Types |
| IRV-011 | Valid declared types | Parameter types, function return types, instruction-result types, and collected storage types must satisfy the verifier's type grammar. | `_verify_function`, `_verify_parameters`, `_collect_value_types`, `_collect_slot_types` (lines 226–240, 311–322, 374–413) | Types |
| IRV-012 | Well-formed enum types | An `EnumType` has a non-empty name, at least one variant, and no duplicate variant names. | `_is_valid_type` (lines 2513–2516) | Types |
| IRV-013 | Resolved struct types | A `StructType` has a non-empty name that resolves to a struct definition in the same module. | `_is_valid_type` (lines 2516–2517) | Types |
| IRV-014 | Valid composite member types | `NullableType.inner`, list/array/vector/matrix element types, and both method-result component types recursively satisfy the type grammar. | `_is_valid_type` (lines 2534–2539) | Types |
| IRV-015 | Admitted leaf types | Integer, float, double, bool, string, void, complex, class-reference, interface, and function types are admitted as leaf types. The current verifier does not recursively inspect a `FunctionType` signature. | `_is_valid_type` (lines 2518–2533) | Types |
| IRV-016 | Function has blocks | Every function contains at least one basic block. | `_verify_function` (lines 230–231) | CFG |
| IRV-017 | Function has entry | Every function contains a block named exactly `entry`. | `_verify_function` (lines 233–235) | CFG |

## Control flow, returns, and data flow

| ID | Short title | Description | Verifier location | Category |
| --- | --- | --- | --- | --- |
| IRV-018 | Block terminator required | Every block is non-empty and contains an `IRReturn`, `IRJump`, or `IRBranch` terminator. | `_verify_block_structure` (lines 332–352) | CFG |
| IRV-019 | Terminator is final | No instruction may follow the first terminator in a block. | `_verify_block_structure` (lines 343–348) | CFG |
| IRV-020 | CFG targets exist | Every jump target and both targets of every branch name blocks in the same function. | `_verify_terminator_targets` (lines 354–372) | CFG |
| IRV-021 | Boolean branch condition | A branch condition is defined and has `bool` type. | `_transfer_instruction` (lines 976–980) | CFG |
| IRV-022 | Unreachable blocks are locally valid | Reachability is not required, but every unreachable block still undergoes local instruction and type checking with all collected values and slots treated as available. Executable-path proof of initialization is not required there. | `_verify_reachable_values` (lines 482–496) | CFG |
| IRV-023 | Supported instruction set | Every instruction is one of the explicitly handled IR instruction variants; any other instruction class is rejected. | `_transfer_instruction` (lines 541–1017) | Instructions |
| IRV-024 | Non-void paths return values | Contract: from `entry`, every exiting path of a non-void function reaches a return carrying a value; non-entry labels do not affect semantics. Python implementation note: `_block_returns` is nominally sensitive and treats a revisited block as a non-exiting loop cycle only when its name starts with `cond` or `for.cond`, so isomorphic renamed cycles can produce different Python results. | `_verify_all_non_void_paths_return`, `_block_returns` (lines 2059–2108) | Returns |
| IRV-025 | Return value matches function | A valueless return is allowed only in a void function. A valued return operand is defined and its type exactly equals the function return type. | `_verify_return` (lines 2028–2057) | Returns |
| IRV-026 | Storage is not a return value | `IRStorage` cannot be returned directly as a value, even when live; it must be loaded or explicitly transferred as a value. | `_verify_return` (lines 2042–2051) | Returns |
| IRV-027 | Valid return transfer | `transferred_storage`, when present, is valid lifecycle storage, is live, accompanies a returned value, and has exactly the returned value's type. | `_transfer_instruction` (lines 985–1008) | Lifecycle |
| IRV-028 | Return cleans owning storage | At return, every live storage name classified as lifecycle storage is cleaned up, except the one explicitly named as transferred storage. | `_transfer_instruction`, `_is_lifecycle_storage` (lines 987–1014, 498–512) | Lifecycle |
| IRV-029 | Values defined before use | On executable paths, every value operand is available from a parameter or an earlier definition on every incoming path. | `_verify_reachable_values`, `_require_defined` (lines 435–480, 2322–2330) | Data Flow |
| IRV-030 | Value-use type identity | Each value use has exactly the type recorded for its function-wide definition. | `_require_defined` (lines 2331–2336) | Data Flow |
| IRV-031 | Slot references resolve | A referenced slot name exists in the collected slot table and the occurrence has its canonical slot type. | `_require_slot_exists` (lines 2338–2350) | Data Flow |
| IRV-032 | Load requires definite initialization | A load's slot is initialized on every executable incoming path. Loads after a tracked move or destroy are rejected distinctly. | `_transfer_instruction`, `_require_slot_stored` (lines 545–553, 2352–2360) | Data Flow |
| IRV-033 | Load result type | A load result has exactly the canonical type of its slot. | `_transfer_instruction` (lines 545–553) | Types |
| IRV-034 | Store contract | A stored value is defined, its slot resolves, and its type exactly equals the slot type; the store then marks the slot initialized and clears tracked moved/destroyed state for that name. | `_transfer_instruction` (lines 555–568) | Data Flow |
| IRV-035 | Definite state at CFG merges | Available values, initialized slots, moved slots, and destroyed slots are intersected across incoming executable paths; availability on only some paths is insufficient. | `_State.intersect`, `_verify_reachable_values` (lines 145–151, 449–480) | Data Flow |
| IRV-036 | Consistent lifecycle initialization at merges | Before intersection, a storage name used by any lifecycle instruction must have the same initialized/not-initialized state on every incoming path to a block. | `_verify_reachable_values`, `_is_lifecycle_storage` (lines 461–476, 498–512) | Lifecycle |

## Borrowing and lifecycle instructions

| ID | Short title | Description | Verifier location | Category |
| --- | --- | --- | --- | --- |
| IRV-037 | Borrow requires scope | A borrowed array/list get has a non-empty iteration scope. | `_verify_borrowed_elements` (lines 246–255) | Borrowing |
| IRV-038 | Borrow defined in its scope | A borrowed array/list get is defined in the block whose name equals its declared borrow scope. | `_verify_borrowed_elements` (lines 255–260) | Borrowing |
| IRV-039 | Owned get has no borrow scope | A non-borrowed array/list get does not carry a borrow scope. | `_verify_borrowed_elements` (lines 261–262) | Borrowing |
| IRV-040 | Borrowed owning store requires acquisition | A borrowed value whose type needs destruction cannot be stored as owned unless an `__aether_retain` call for that value occurred earlier in the same block. | `_verify_borrowed_elements` (lines 278–298) | Borrowing |
| IRV-041 | Borrowed value cannot return | A borrowed iteration value cannot be returned directly, regardless of an earlier retain call. | `_verify_borrowed_elements` (lines 299–303) | Borrowing |
| IRV-042 | No mutation through borrow | Borrowed iteration elements cannot be receivers of array/list mutation, sequence sort, or struct-set operations enumerated by the verifier. | `_verify_borrowed_elements` (lines 266–309) | Borrowing |
| IRV-043 | Lifecycle destination kind | A lifecycle destination/source passed through the common destination check is `IRStorage`, resolves as a slot with the same type, and is not void storage. | `_verify_lifecycle_destination` (lines 2362–2375) | Lifecycle |
| IRV-044 | Default initialization | `IRInitDefault` targets uninitialized lifecycle storage whose type's lifecycle traits support a default value, then makes it live. | `_transfer_instruction` (lines 570–579) | Lifecycle |
| IRV-045 | Copy initialization | `IRCopyInit` targets uninitialized lifecycle storage, reads a defined value or live storage source, requires exact source/destination type equality, then makes the destination live without consuming the source. | `_transfer_instruction`, `_require_lifecycle_source` (lines 581–590, 2401–2412) | Lifecycle |
| IRV-046 | Move initialization | `IRMoveInit` uses distinct valid source and destination storages, requires an uninitialized destination and live source of the same type, then makes the destination live and marks the source moved. | `_transfer_instruction` (lines 592–610) | Lifecycle |
| IRV-047 | Assignment | `IRAssign` requires a live lifecycle destination plus a defined value or live storage source of exactly the destination type. Self-assignment is accepted. | `_transfer_instruction` (lines 612–623) | Lifecycle |
| IRV-048 | Destruction | `IRDestroy` targets live lifecycle storage, then makes it non-live and marks it destroyed. | `_transfer_instruction` (lines 625–633) | Lifecycle |
| IRV-049 | Relocation | `IRRelocate` uses distinct valid storages, an exact built-in `int` count greater than zero, an uninitialized destination, a live same-typed source, and a source type marked trivially relocatable; it then makes the destination live and marks the source moved. | `_transfer_instruction` (lines 635–661) | Lifecycle |
| IRV-050 | Lifecycle liveness | Storage required to be live must be initialized and neither moved nor destroyed; storage required to be uninitialized must not currently be live. | `_require_uninitialized`, `_require_live_storage` (lines 2376–2399) | Lifecycle |

## Calls and builtins

| ID | Short title | Description | Verifier location | Category |
| --- | --- | --- | --- | --- |
| IRV-051 | Function reference contract | `IRFunctionRef` names a defined function and its result type exactly matches the function's parameter and return signature. | `_transfer_instruction` (lines 701–714) | Calls |
| IRV-052 | Direct call contract | A non-builtin direct call names a defined function, has the exact arity, uses defined arguments of the exact parameter types, produces no result for void callees, and produces a result of the exact return type for non-void callees. | `_verify_call` (lines 1190–1229) | Calls |
| IRV-053 | Indirect call contract | The callee is a defined value of `FunctionType`; arguments have the signature's exact arity and types; void signatures have no result and non-void signatures have a result of the exact return type. | `_verify_indirect_call` (lines 1231–1267) | Calls |
| IRV-054 | Defined builtin arguments | Every argument to every builtin call is defined and agrees with its recorded value type before builtin-specific validation. | `_verify_call` (lines 1025–1027) | Calls |
| IRV-055 | Process arguments builtin | The process-arguments builtin retains its canonical semantic/function name and has signature `() -> array<string>` with a result. | `_verify_call` (lines 1028–1037) | Builtins |
| IRV-056 | Range-step guard builtin | The range-step nonzero guard retains its canonical semantic/function name and has signature `(int) -> void`. | `_verify_call` (lines 1038–1047) | Builtins |
| IRV-057 | String byte-length builtin | `__aether_string_byte_length` retains its canonical semantic/function name and has signature `(string) -> int`. | `_verify_call` (lines 1048–1058) | Builtins |
| IRV-058 | String trim builtin | The string-trim builtin retains its canonical semantic/function name and has signature `(string) -> string` with a result. | `_verify_call` (lines 1059–1069) | Builtins |
| IRV-059 | String split builtin | The string-split builtin retains its canonical semantic/function name and has signature `(string, string) -> array<string>` with a result. | `_verify_call` (lines 1070–1080) | Builtins |
| IRV-060 | String parse builtin signature | Integer/double parsing builtins retain their canonical semantic/function names and have signature `(string) -> StructType(canonical parse-result name)`. | `_verify_call` (lines 1081–1099) | Builtins |
| IRV-061 | String parse result layout | The selected parse-result struct exists with exactly `value` and `status` fields; `value` is the matching int/double type and `status` is an enum type. | `_verify_call` (lines 1099–1109) | Builtins |
| IRV-062 | Text-file builtin common contract | Text-file builtins retain canonical names, take one string argument for read or two for write, and always produce a result. | `_verify_call` (lines 1110–1122) | Builtins |
| IRV-063 | Text read result layout | Text read returns the canonical `FileReadResult` struct, whose exact two-field layout is `content: string` followed by `status: EnumType(FileStatus)`. | `_verify_call` (lines 1123–1135) | Builtins |
| IRV-064 | Text write result | A text-file write returns an `EnumType` named `FileStatus`. | `_verify_call` (lines 1136–1141) | Builtins |
| IRV-065 | Text codec builtin | Each text-codec builtin retains its canonical semantic/function name, produces a result, and exactly matches its entry in the verifier's argument/result signature map. | `_verify_call` (lines 1142–1158) | Builtins |
| IRV-066 | Retain/release builtin | `__aether_retain` and `__aether_release` retain their canonical names, take exactly one string/struct/method-result/array/list argument, and produce no result. | `_verify_call` (lines 1159–1172) | Builtins |
| IRV-067 | Scalar math builtin | Any other builtin produces a result, has an argument signature accepted by `scalar_math_result_type`, retains its canonical semantic/function name, and uses the result type computed by that helper. | `_verify_call` (lines 1173–1189) | Builtins |

## Constants, scalar operations, and nominal aggregates

| ID | Short title | Description | Verifier location | Category |
| --- | --- | --- | --- | --- |
| IRV-068 | Enum constant identity | An enum constant result is `EnumType` of the same enum name; its member ID is in range, selects the declared member name, and equals its discriminant. | `_verify_const` (lines 2110–2135) | Constants |
| IRV-069 | Primitive constant contract | Bool, int, float, complex, and string Python values map respectively to bool, int, float-or-double, complex, and string IR types; int constants fit signed i32. `None` and unrecognized value classes receive no value/type validation beyond the result's general type validity. | `_verify_const` (lines 2137–2166) | Constants |
| IRV-070 | Numeric/string binary arithmetic | Binary `add/sub/mul/div/rem/mod/pow` accepts exact-equal numeric operand types, except string `add` also accepts two strings. `rem/mod` exclude complex. Integer division returns double; otherwise the result follows the verifier's numeric result rule, and the declared result matches it. | `_binary_result_type`, `_transfer_instruction` (lines 663–672, 2168–2206) | Operators |
| IRV-071 | Binary equality operators | Binary `eq/ne` requires exact-equal operand types and returns bool; this opcode path does not apply the separate `Eq` capability check. | `_binary_result_type` (lines 2208–2214) | Operators |
| IRV-072 | Binary ordered operators | Binary `lt/le/gt/ge` requires both operands to be real numeric types and returns bool; this opcode path does not require the two real types to be equal. | `_binary_result_type` (lines 2216–2225) | Operators |
| IRV-073 | Binary logical/operators allowlist | Binary `and/or` requires two bool operands and returns bool; any binary operator outside the explicitly supported sets is rejected. | `_binary_result_type` (lines 2227–2235) | Operators |
| IRV-074 | Unary operator contract | Unary `neg` accepts only float/double and preserves its operand type. Unary `not` accepts only bool and returns bool. All other unary operators are rejected through the `not` validation path. | `_verify_unary` (lines 2237–2257) | Operators |
| IRV-075 | Aggregate compare contract | Vector/matrix comparison uses only `eq/ne`, requires exact-equal aggregate types, a positive shape of rank one/two respectively, element type int/double/bool/string, and a bool result. | `_compare_result_type`, `_transfer_instruction` (lines 679–688, 2264–2275) | Operators |
| IRV-076 | Scalar compare contract | A scalar compare carries no aggregate shape. Ordered compare accepts exactly int/int or double/double. `eq/ne` requires exact-equal types with an available `Eq` capability. Supported comparisons return bool; other operators are rejected. | `_compare_result_type` (lines 2277–2304) | Operators |
| IRV-077 | Numeric cast allowlist | Casts allow identical int/float/double types, int to float/double, and conversions among float/double/int when source and target differ as expressed by the verifier; all other casts are rejected. | `_verify_cast` (lines 2306–2320) | Types |
| IRV-078 | Print contract | Print accepts int, bool, string, double, enum, array, list, vector, matrix, or struct. Vectors carry exactly one shape value, matrices exactly two, and every other printable type carries no aggregate shape. | `_transfer_instruction` (lines 722–751) | Instructions |
| IRV-079 | Struct construction | `IRStructNew` has a result naming a declared struct, supplies exactly all canonical fields in declaration order, and uses defined values of each exact field type. | `_transfer_instruction` (lines 753–760) | Structs |
| IRV-080 | Struct field read | `IRStructGet` uses a defined declared-struct operand, a canonical in-range field index, and a result of exactly that field's declared type. | `_transfer_instruction` (lines 762–768) | Structs |
| IRV-081 | Struct field update | `IRStructSet` uses defined struct/value operands, a canonical in-range field index, a value of the field's exact type, and a result of the exact input struct type. | `_transfer_instruction` (lines 770–778) | Structs |
| IRV-082 | Method-result construction | `IRMethodResultNew` uses a defined receiver and a `MethodResultType` result with matching receiver type; a void value component forbids a source value, while a non-void component requires a defined source of its exact type. | `_transfer_instruction` (lines 780–793) | Method Results |
| IRV-083 | Method receiver extraction | Receiver extraction uses a defined `MethodResultType` operand and returns exactly its receiver component type. | `_transfer_instruction` (lines 795–800) | Method Results |
| IRV-084 | Method value extraction | Value extraction uses a defined `MethodResultType` operand and returns exactly its value component type. | `_transfer_instruction` (lines 802–807) | Method Results |

## Collections

All operand values mentioned below are also subject to IRV-029 and IRV-030.

| ID | Short title | Description | Verifier location | Category |
| --- | --- | --- | --- | --- |
| IRV-085 | Array construction | `IRArrayNew` returns `ArrayType` and every element has exactly the array element type. | `_verify_array_new` (lines 1269–1283) | Collections |
| IRV-086 | List construction | `IRListNew` returns `ListType` and every element has exactly the list element type. | `_verify_list_new` (lines 1285–1299) | Collections |
| IRV-087 | Array element read | Array get uses an array operand and int index and returns exactly the array element type. | `_verify_array_get` (lines 1635–1651) | Collections |
| IRV-088 | Array element write | Array set uses an array operand, int index, and value of exactly the array element type. | `_verify_array_set` (lines 1733–1750) | Collections |
| IRV-089 | Array slice | Array slice uses an array plus int start/end values and returns exactly the input array type. | `_verify_array_slice` (lines 1653–1672) | Collections |
| IRV-090 | Array length | Array length uses an array operand and returns int. | `_verify_array_length` (lines 1814–1824) | Collections |
| IRV-091 | Array copy | Array copy uses an array operand, returns exactly its type, and requires lifecycle traits without an error reason for the element type. | `_verify_array_copy` (lines 1838–1848) | Collections |
| IRV-092 | List element read | List get uses a list operand and int index and returns exactly the list element type. | `_verify_list_get` (lines 1674–1690) | Collections |
| IRV-093 | List element write | List set uses a list operand, int index, and value of exactly the list element type. | `_verify_list_set` (lines 1771–1788) | Collections |
| IRV-094 | List slice | List slice uses a list plus int start/end values, returns exactly the input list type, and requires lifecycle traits without an error reason for the element type. | `_verify_list_slice` (lines 1862–1887) | Collections |
| IRV-095 | List length | List length uses a list operand and returns int. | `_verify_list_length` (lines 1826–1836) | Collections |
| IRV-096 | List emptiness | List `is_empty` uses a list operand and returns bool. | `_verify_list_is_empty` (lines 1976–1986) | Collections |
| IRV-097 | List copy | List copy uses a list operand, returns exactly its type, and requires lifecycle traits without an error reason for the element type. | `_verify_list_copy` (lines 1850–1860) | Collections |
| IRV-098 | List membership | List `contains` uses a list plus a value of exactly its element type, requires `Eq` capability for that type, and returns bool. | `_verify_list_contains` (lines 1889–1898) | Collections |
| IRV-099 | List index lookup | List `index_of` uses a list plus a value of exactly its element type, requires `Eq` capability for that type, and returns int. | `_verify_list_index_of` (lines 1900–1909) | Collections |
| IRV-100 | List clear | List clear uses a list operand. | `_verify_list_clear` (lines 1916–1919) | Collections |
| IRV-101 | List reverse | List reverse uses a list operand. | `_verify_list_reverse` (lines 1911–1914) | Collections |
| IRV-102 | List push | List push uses a list and a value of exactly its element type. | `_verify_list_push` (lines 1921–1930) | Collections |
| IRV-103 | List insert | List insert uses a list, an int index, and a value of exactly its element type. | `_verify_list_insert` (lines 1932–1944) | Collections |
| IRV-104 | List pop | List pop uses a list and returns exactly its element type. | `_verify_list_pop` (lines 1946–1954) | Collections |
| IRV-105 | List remove-at | List `remove_at` uses a list and int index and returns exactly its element type. | `_verify_list_remove_at` (lines 1956–1967) | Collections |
| IRV-106 | Sequence sort | Sequence sort uses an array or list whose element type is int, double, or string. | `_verify_sequence_sort` (lines 1969–1974) | Collections |

## Vectors and matrices

All operand values mentioned below are also subject to IRV-029 and IRV-030.
Where a contract invokes the shared numeric result rule, both element types must
be numeric and promotion selects complex, then double, then float, then int.

| ID | Short title | Description | Verifier location | Category |
| --- | --- | --- | --- | --- |
| IRV-107 | Vector construction | `IRVectorNew` returns `VectorType`; result and instruction orientations are each `row` or `column` and equal; every element has exactly the result element type. | `_verify_vector_new` (lines 1301–1324) | Linear Algebra |
| IRV-108 | Matrix construction | `IRMatrixNew` returns `MatrixType`, has positive row/column metadata, supplies exactly rows-times-columns elements, and every element has exactly the result element type. | `_verify_matrix_new` (lines 1326–1347) | Linear Algebra |
| IRV-109 | Vector add/subtract | Vector add/subtract has vector operands and result, positive length metadata, equal operand orientations and exact-equal operand/result vector types, and instruction orientation equal to result orientation. It does not separately restrict element types to numeric. | `_verify_vector_binary` (lines 1365–1393) | Linear Algebra |
| IRV-110 | Vector scale | Vector scale has vector operand/result, positive length metadata, instruction orientation equal to result orientation, exact-equal operand/result vector types, and a scalar exactly equal to the vector element type. It does not separately restrict that type to numeric. | `_verify_vector_scale` (lines 1395–1418) | Linear Algebra |
| IRV-111 | Vector dot product | Dot product uses a row vector followed by a column vector, has positive length metadata, and returns the shared numeric result type of the two element types. | `_verify_vector_dot` (lines 1420–1443) | Linear Algebra |
| IRV-112 | Outer product | Outer product uses a column vector followed by a row vector, returns a matrix, has positive row/column metadata, and its result element is the shared numeric result type of the operand elements. | `_verify_outer_product` (lines 1445–1471) | Linear Algebra |
| IRV-113 | Matrix add/subtract | Matrix add/subtract has matrix operands and result, positive row/column metadata, and exact-equal operand/result matrix types. It does not separately restrict element types to numeric. | `_verify_matrix_binary` (lines 1489–1513) | Linear Algebra |
| IRV-114 | Matrix scale | Matrix scale has matrix operand/result, positive row/column metadata, exact-equal operand/result matrix types, and a scalar exactly equal to the matrix element type. It does not separately restrict that type to numeric. | `_verify_matrix_scale` (lines 1515–1536) | Linear Algebra |
| IRV-115 | Matrix multiplication | Matrix multiplication has matrix operands/result; positive rows/inner/columns metadata; and a result element equal to the shared numeric result type of operand elements. | `_verify_matrix_matmul` (lines 1538–1565) | Linear Algebra |
| IRV-116 | Matrix-vector multiplication | Matrix-vector multiplication has matrix and column-vector operands, a column-vector result, positive rows/inner metadata, and a result element equal to the shared numeric result type of operand elements. | `_verify_matrix_vector_mul` (lines 1567–1599) | Linear Algebra |
| IRV-117 | Vector-matrix multiplication | Vector-matrix multiplication has row-vector and matrix operands, a row-vector result, positive rows/columns metadata, and a result element equal to the shared numeric result type of operand elements. | `_verify_vector_matrix_mul` (lines 1601–1633) | Linear Algebra |
| IRV-118 | Vector element read | Vector get uses a vector operand and int index and returns exactly the vector element type. | `_verify_vector_get` (lines 1692–1708) | Linear Algebra |
| IRV-119 | Vector element write | Vector set uses a vector operand, int index, and value of exactly the vector element type. | `_verify_vector_set` (lines 1752–1769) | Linear Algebra |
| IRV-120 | Matrix element read | Matrix get uses a matrix operand and int row/column indices, has positive column-count metadata, and returns exactly the matrix element type. | `_verify_matrix_get` (lines 1710–1731) | Linear Algebra |
| IRV-121 | Matrix element write | Matrix set uses a matrix operand, int row/column indices, positive column-count metadata, and a value of exactly the matrix element type. | `_verify_matrix_set` (lines 1790–1812) | Linear Algebra |
| IRV-122 | Vector length | Vector length uses a vector operand and returns int. | `_verify_vector_length` (lines 1988–1998) | Linear Algebra |
| IRV-123 | Matrix row count | Matrix rows uses a matrix operand, has positive row-count metadata, and returns int. | `_verify_matrix_rows` (lines 2000–2012) | Linear Algebra |
| IRV-124 | Matrix column count | Matrix columns uses a matrix operand, has positive column-count metadata, and returns int. | `_verify_matrix_columns` (lines 2014–2026) | Linear Algebra |

## Inventory boundaries

This inventory contains **124 invariants**. It intentionally records several
current-verifier boundaries that a second implementation must not silently
strengthen:

- block reachability is not required (IRV-022);
- phi completeness, SSA single-definition rules, and dominance are outside this
  verifier;
- function-type signatures are not recursively type-validated (IRV-015);
- `None` and otherwise unrecognized Python constant payloads are not checked
  against their result types (IRV-069);
- aggregate dimension metadata is checked only where stated above; vector and
  matrix types do not encode dimensions; and
- borrow checking is limited to IRV-037 through IRV-042; it is not a general
  cross-block borrow-use analysis.

The ID appears exactly once as a table-row identifier. Cross-references in prose
are descriptive references and do not redefine an invariant.
