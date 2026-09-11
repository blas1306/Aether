# OOP-V3 — single class inheritance and virtual dispatch

Status: **ADMITTED**, bounded native Linux x86-64 bootstrap, 2026-09-10.
OOP-V1 remains authoritative for class identity, non-atomic ARC, initialization,
direct methods, receiver capabilities, visibility and identity equality. OOP-V2
remains authoritative for interface carriers and requirement dispatch.
OOP-OPT-1 remains a verified physical optimization layer.

## Result

```aether
open class Animal {
    public init() {}
    public open int sound() { return 1; }
}
class Dog : Animal {
    public init() : base() {}
    public override int sound() { return 7; }
}
int main() {
    Animal animal = Dog();
    return animal.sound();
}
```

The required program builds natively and exits 7 at O0 and O2. `Animal` and
`Dog` handles identify one allocation with one strong count. The virtual call
uses the descriptor installed for `Dog`; final release through either static
type invokes `Dog` destruction.

## Implementation inventory

| Area | Files | Responsibility |
| --- | --- | --- |
| Frontend | `aether-frontend/src/{parser.rs,oop.rs,types.rs,hir.rs,hir/classes.rs,interfaces.rs}` | Syntax, base resolution, slots, overrides, fields, upcasts, inherited witnesses and HIR verification |
| Middle | `aether-middle/src/{mir.rs,mir/classes.rs,ssa/classes.rs,ssa/oop_opt.rs}` | Same-object base initialization, path state, owner verification and exact/unknown provenance |
| Backend | `aether-backend-llvm/src/{lib.rs,classes.rs}` | Descriptor/vtable emission, virtual calls, dynamic witnesses and dynamic final release |
| Qualification | `aether-driver/tests/oop_v3.rs`, frontend inheritance tests, `tests/programs/oop_v3_*.ae` | Native O0/O2 programs, source negatives, metadata/IR/runtime corruptions |
| Measurement | `tests/measure-oop-v3.py`, `tests/timings/oop-v3.json` | Physical sites/events, text size and process timing samples |
| Documentation | `compiler-next/README.md`, charter, semantic contract, architecture, this report | Admission and evidence |

Existing untracked root binaries `FaCAether` and `FaCAetherO0` were preserved.

## Required implementation account

The numbering follows the requested 60-point final report.

| # | Topic | Implemented contract and evidence |
| ---: | --- | --- |
| 1 | Admitted syntax | `open class`, `public open` method, `override`, one class plus interfaces in `:`, and initializer `: base(args)`; no `extends`/`implements`. |
| 2 | Files changed | Inventory above; runnable and cost fixtures are under `compiler-next/tests/programs`. |
| 3 | BaseClass relation | `ClassInfo.base: Option<ClassId>` is the sole stateful base authority. |
| 4 | Relation resolution | Canonical resolved `TypeId` determines class/interface kind; at most one class target, independent of list order. |
| 5 | Final/open class | Classes are final by default. Only an accessible `open` class may be a base. Public derivation cannot expose an internal base. |
| 6 | Open method | A public open method in an open class introduces a virtual slot; class openness alone does not affect methods. |
| 7 | Override | `override` is mandatory; target, visibility, parameters, result and read/mut capability must match exactly. |
| 8 | Slot identity | Kind-safe `VirtualSlotId(FunctionId)` names the originating declaration. Overrides reuse it and record `override_target`. |
| 9 | Graph verification | `class_chain` rejects self, indirect and longer cycles and missing base identities in every metadata verification. |
| 10 | Object layout | One complete allocation: `{strong_count, descriptor_ptr, base prefix, derived fields}` with target alignment. |
| 11 | Descriptor layout | One immutable descriptor per concrete class: destruction slot, deterministic virtual target cells and interface witness references. Physical indices are private. |
| 12 | Strong count | All views use the one non-atomic count at object offset zero. No base/interface count exists. |
| 13 | Base fields | Base fields retain declaring `ClassId`, `FieldId` and fixed offset. The complete base layout is a prefix. |
| 14 | Derived fields | Derived fields follow the aligned complete base layout and cannot hide inherited fields/methods. |
| 15 | Construction allocation | Construction arguments are lowered before exactly one most-derived `ObjectAlloc`; there is no base allocation. |
| 16 | Base init | `BaseInit` invokes the immediate base initializer on the same derived initialization token. Omission inserts a zero-arg call only when accessible. |
| 17 | Initialization order | Arguments, allocation/header, base arguments/init, derived body/fields, publication. Base init recursively applies the same rule. |
| 18 | Publication | Exactly one `PublishObject` follows completed base and derived initialization; base publication is absent. |
| 19 | `this` during init | Existing no-escape/no-alias/no-return/no-arbitrary-call rule remains; inherited state cannot be used before base completion. |
| 20 | Field access | Lookup follows the base chain but preserves declaration identity. Private base fields remain inaccessible. Reads before initialization fail. |
| 21 | Method inheritance | Accessible base methods are found through the nominal chain. Same-name non-override declarations fail instead of hiding/overloading. |
| 22 | Nonvirtual calls | Non-open inherited methods retain the declaring implementation and lower as `DirectMethodCall`. |
| 23 | Virtual calls | `VirtualCall` records static class, origin slot and exact static target contract; LLVM loads descriptor, slot and indirect target. |
| 24 | Receiver capability | Every override exactly preserves read/mut. Mut remains shared and never gains `noalias`. |
| 25 | Receiver keepalive | Capture precedes arguments; keepalive remains live through indirect invocation and is released afterward. Replacement corruption is qualified. |
| 26 | Class upcast | HIR/MIR/SSA carry `ClassUpcast {source_class,target_base,path,transfer}`. The pointer and identity are unchanged. |
| 27 | Alias upcast | Derived lvalue to base retains exactly once and creates one additional strong token. |
| 28 | Transfer upcast | Fresh derived owner to base transfers with zero upcast retains. |
| 29 | Transitive upcast | Exact full chain permits `C -> A`; corrupted and unrelated paths reject. |
| 30 | No slicing | Upcast emits pointer forwarding only: no allocation, payload copy, wrapper or base refcount. |
| 31 | Dynamic identity | Static class `TypeId` remains distinct from the descriptor's most-derived class. Compatible base/derived equality compares the shared pointer. |
| 32 | Dynamic destruction | Every class drop calls common dynamic release. At count zero, descriptor slot zero selects final concrete destruction. |
| 33 | Destruction order | Concrete recipe is reverse derived owning fields followed recursively by reverse base fields, then one free. |
| 34 | Buffer destruction | Native trace asserts derived Buffer then base Buffer, each once, with one object free and both backing frees. |
| 35 | Inherited interfaces | Effective conformance is inherited base conformances plus explicit derived conformances. Duplicate inherited redeclaration rejects. |
| 36 | Dynamic witness | Each concrete class has its own witness. Interface adaptation obtains it from the object's dynamic descriptor. |
| 37 | Interface override | A witness maps requirements to the concrete class's effective override; `Speaker s = Dog()` returns 7. |
| 38 | Final class/interface release | Both routes reach dynamic descriptor destruction and drop the entire derived object. Runtime base-only corruptions fail qualification. |
| 39 | HIR | Exact base relation, override target, slot, `BaseInit`, `ClassUpcast`, `VirtualCall`, inherited conformance and effective witness mapping survive. |
| 40 | HIR verifier | Rebuilds graph, access, overrides, layout/drop recipes, init state, upcast path, slots, receiver contract and witness targets. |
| 41 | MIR | Materializes one allocation, same-object base init, field writes, one publication, explicit upcast mode, virtual call and ordinary dynamic drop. |
| 42 | MIR verifier | Path state separates base completion from initialized fields; rejects missing/duplicate base init, premature access/publication and corrupted calls/owners. |
| 43 | SSA | Preserves all class operations, static types and owner tokens. Exact/Unknown provenance propagates through aliases, transfers and phis. |
| 44 | SSA verifier | Independently checks metadata, definitions, path init, upcast consumption, virtual target/capability, phi ownership and final cleanup. |
| 45 | LLVM object layout | On x86-64 header is 16 bytes; class handle remains one 8-byte pointer. Field offsets are verified target-layout bytes. |
| 46 | Descriptor/vtable emission | Constants are emitted deterministically for reachable object classes, without runtime name lookup or source-visible type numbers. |
| 47 | Virtual codegen | Unknown virtual receivers perform descriptor load, slot load and indirect call. Nonvirtual calls remain direct. |
| 48 | ARC counters | Fresh upcast: alloc 1, retain 0, release 1. Lvalue upcast: alloc 1, retain 1, release 2. One shared count and no wrapper allocation. |
| 49 | Destruction counters | Base+derived Buffer object: Buffer drops 2, object destroys 1, heap alloc/free 3/3; trace is derived then base. |
| 50 | Native results | 30 core positive fixtures run at O0/O2, including three-level inheritance, mut/read dispatch, interfaces, modules and unknown parameters. |
| 51 | Source negatives | 43 named cases cover bases, cycles, initialization, override mismatches, hiding, modifiers, casts, visibility and graph/generic exclusions. |
| 52 | Corruption tests | HIR mutates 5 operations and 9 metadata facts; MIR/SSA mutate operations, base-init cardinality, metadata, owner phis and final drop. Five runtime descriptor/witness/drop corruptions fail at O0/O2. |
| 53 | O0/O2 observations | Table below records actual sites, counters, text and timing samples; no zero-cost claim. |
| 54 | OOP-OPT interaction | Exact interface provenance through a derived descriptor devirtualizes. Unknown parameters and mixed B/C phis do not. Class virtual calls remain semantic/indirect. |
| 55 | Non-OOP regression | Six scalar/struct/Buffer/generic/Matrix/main-comment representatives emitted byte-identical LLVM against pre-V3 `HEAD`. |
| 56 | Exact test counts | `cargo test --workspace`: 353 passed, zero failed/ignored: 7 backend, 7 parity, 12 OOP-OPT, 15 OOP-V1, 10 OOP-V2, 12 OOP-V3, 219 vertical integration, 49 frontend, 22 middle. |
| 57 | Differential | `run-differential.sh`: checked 21, failures 0; intentional integer differences unchanged. |
| 58 | Accepted debt | `base.method` deferred; class-virtual exact devirtualization deferred; physical descriptor tables are sparse bootstrap constants; diagnostics share bounded E0420/E0421 families. |
| 59 | OPEN DECISIONS | Public object ABI, descriptor compaction/stable slot indexing, user destructors, graph/cycle policy, class generics, protected access, RTTI/downcasts and exception construction cleanup. |
| 60 | Recommendation | Next general-language milestone should admit explicit same-object `base.method` calls and exact class-virtual devirtualization before expanding stored object graphs. |

## Native counters and order

The key ownership cases after source-main cleanup are:

| Case | Alloc | Retain | Release | Destroy | Buffer drops | Heap alloc/free |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Fresh `Dog -> Animal` | 1 | 0 | 1 | 1 | 0 | 1/1 |
| Lvalue `Dog -> Animal` | 1 | 1 | 2 | 1 | 0 | 1/1 |
| Base-typed to interface on Dog | 1 | 2 | 3 | 1 | 0 | 1/1 |
| Derived and base Buffer fields | 1 | 0 | 1 | 1 | 2 | 3/3 |
| Final interface owner with both buffers | 1 | 1 | 2 | 1 | 2 | 3/3 |

The order probe encodes each actual owning-field drop into a decimal trace. The
derived field has marker 2 and the base field marker 1; final trace 21 proves the
required derived-before-base ordering. Corrupting descriptor destruction to the
base recipe, freezing the base witness, choosing the wrong override, adapting
with the static witness or performing base-only interface release fails native
qualification at both clang O0 and O2.

## Descriptive costs

Reproduce with:

```sh
python3 compiler-next/tests/measure-oop-v3.py --runs 7
```

Measurements used rustc 1.97.1 and clang 22.1.8. Times include process startup,
instrumentation and allocator work. `I` is indirect method calls in emitted
source bodies; dynamic release also adds an indirect destruction call in glue.

| Workload | Profile | Retain/release events | Descriptor/slot loads | I | ELF text bytes | Median ms |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| Direct nonvirtual | O0 | 10000/10001 | 0/0 | 0 | 4000 | 0.670 |
| Direct nonvirtual | O2 | 0/1 | 0/0 | 0 | 1676 | 0.575 |
| Exact class virtual | O0 | 10000/10001 | 1/1 | 1 | 4000 | 0.631 |
| Exact class virtual | O2 | 0/1 | 1/1 | 1 | 2210 | 0.595 |
| Unknown base parameter | O0 | 20000/20001 | 1/1 | 1 | 4080 | 0.438 |
| Unknown base parameter | O2 | 10000/10001 | 1/1 | 1 | 2266 | 0.393 |
| Lvalue upcast loop | O0 | 10000/10001 | 0/0 | 0 | 3904 | 0.485 |
| Lvalue upcast loop | O2 | 10000/10001 | 0/0 | 0 | 1727 | 0.388 |
| Fresh upcast loop | O0 | 0/10000 | 0/0 | 0 | 3872 | 0.536 |
| Fresh upcast loop | O2 | 0/10000 | 0/0 | 0 | 1717 | 0.339 |
| Dynamic final release | O0 | 0/10000 | 0/0 | 0 | 4348 | 1.185 |
| Dynamic final release | O2 | 0/10000 | 0/0 | 0 | 2006 | 0.465 |
| Inherited interface | O0 | 10001/10002 | 1/1 | 1 | 4388 | 0.699 |
| Inherited interface | O2 | 1/2 | 1/0 | 0 | 1692 | 0.353 |

The exact class virtual path remains indirect by design at this milestone.
Exact inherited interface provenance devirtualizes at O2, while unknown and
mixed provenance retains its indirect call. Fresh upcast performs no conversion
retain. Lvalue upcast currently retains its loop-local alias at both profiles.

## Regression and boundaries

The full workspace, formatting, all-target clippy with denied warnings,
`git diff --check` and the differential harness pass. Previous OOP-V1/V2/OPT
tests remain green after their private object layout moves from an 8-byte to a
16-byte header. Their source semantics and counter schedules are unchanged.
Non-class programs do not emit descriptors or class runtime symbols.

This admission does not implement multiple class inheritance,
abstract/sealed/protected, explicit `final`, class graph fields, generic
inheritance, downcasts/type tests, source RTTI, nullability, user destructors or
exceptions. Descriptor existence is solely private dispatch/lifecycle metadata.
