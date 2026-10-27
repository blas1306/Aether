//! OWNING-STRUCT-FIELD-REPLACEMENT-V1 cross-layer qualification.

use std::{fs, path::PathBuf, process::Command};

use aether_driver::{ClangToolchain, Emit, OptimizationLevel, compile_source_with_optimization};
use aether_frontend::{SourceFile, TypeId, analyze, parse_source};
use aether_middle::{
    BlockId, Operand, Place, PlaceBase, Rvalue, SsaOp, SsaPlaceBase, build_ssa, lower_hir,
    verify_mir, verify_ssa,
};

struct Output(PathBuf);

impl Output {
    fn new(label: &str) -> Self {
        static NEXT: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
        Self(std::env::temp_dir().join(format!(
            "aether-owning-field-{label}-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, std::sync::atomic::Ordering::Relaxed)
        )))
    }
}

impl Drop for Output {
    fn drop(&mut self) {
        let _ = fs::remove_file(&self.0);
    }
}

fn compile(source: &str, optimization: OptimizationLevel) -> aether_driver::Compilation {
    compile_source_with_optimization(
        &SourceFile::new("owning_struct_field_replacement_v1.ae", source),
        &[Emit::Hir, Emit::Mir, Emit::Ssa, Emit::Llvm],
        optimization,
    )
    .unwrap_or_else(|errors| panic!("{source}\n{errors:#?}"))
}

fn balanced_status(source: &str, optimization: OptimizationLevel) -> i32 {
    let compilation = compile(source, optimization);
    let checks = "  %replace_allocs = load i64, ptr @aether_heap_alloc_count\n  %replace_frees = load i64, ptr @aether_heap_free_count\n  %replace_balanced = icmp eq i64 %replace_allocs, %replace_frees\n  %replace_result_ok = icmp eq i32 %process_status, 0\n  %replace_ok = and i1 %replace_balanced, %replace_result_ok\n  %replace_status = select i1 %replace_ok, i32 0, i32 99\n  ret i32 %replace_status";
    let llvm = compilation
        .llvm
        .replace("  ret i32 %process_status", checks);
    let output = Output::new(match optimization {
        OptimizationLevel::O0 => "o0",
        OptimizationLevel::O2 => "o2",
    });
    ClangToolchain::default()
        .with_optimization(optimization)
        .link_executable(&llvm, &output.0)
        .unwrap();
    Command::new(&output.0)
        .status()
        .unwrap()
        .code()
        .unwrap_or(-1)
}

fn exact_heap_status(source: &str, optimization: OptimizationLevel, expected: u64) -> i32 {
    let compilation = compile(source, optimization);
    let checks = format!(
        "  %replace_allocs = load i64, ptr @aether_heap_alloc_count\n  %replace_frees = load i64, ptr @aether_heap_free_count\n  %replace_allocs_ok = icmp eq i64 %replace_allocs, {expected}\n  %replace_frees_ok = icmp eq i64 %replace_frees, {expected}\n  %replace_counts_ok = and i1 %replace_allocs_ok, %replace_frees_ok\n  %replace_result_ok = icmp eq i32 %process_status, 0\n  %replace_ok = and i1 %replace_counts_ok, %replace_result_ok\n  %replace_status = select i1 %replace_ok, i32 0, i32 99\n  ret i32 %replace_status"
    );
    let llvm = compilation
        .llvm
        .replace("  ret i32 %process_status", &checks);
    let output = Output::new("exact");
    ClangToolchain::default()
        .with_optimization(optimization)
        .link_executable(&llvm, &output.0)
        .unwrap();
    Command::new(&output.0)
        .status()
        .unwrap()
        .code()
        .unwrap_or(-1)
}

const POSITIVE: &str = r#"
struct Inner { Buffer<uint8> bytes; }
struct Owners { Buffer<uint8> first; Inner nested; Buffer<uint8> sibling; }

void replaceBuffer(ref mut Buffer<uint8> slot, uint8 value) {
    Buffer<uint8> next = Buffer<uint8>(2, value);
    *slot = next;
}

void replaceOwner(ref mut Owners owner) {
    Buffer<uint8> next = Buffer<uint8>(3, uint8(9));
    (*owner).nested.bytes = next;
}

int main() {
    Owners value = Owners(
        Buffer<uint8>(1, uint8(1)),
        Inner(Buffer<uint8>(1, uint8(2))),
        Buffer<uint8>(1, uint8(3))
    );
    Buffer<uint8> direct = Buffer<uint8>(2, uint8(4));
    value.first = direct;
    Buffer<uint8> consecutive = Buffer<uint8>(2, uint8(5));
    value.first = consecutive;
    replaceBuffer(&mut value.first, uint8(6));
    replaceOwner(&mut value);
    return int(value.first[0]) + int(value.nested.bytes[0]) + int(value.sibling[0]) - 18;
}
"#;

#[test]
fn direct_nested_reference_and_sibling_replacements_are_balanced_at_o0_o2() {
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        let compilation = compile(POSITIVE, optimization);
        for phase in [Emit::Hir, Emit::Mir, Emit::Ssa] {
            assert!(
                compilation.dumps[&phase].contains("ReplaceOwned"),
                "{phase:?}"
            );
        }
        assert_eq!(
            balanced_status(POSITIVE, optimization),
            0,
            "{optimization:?}"
        );
        let replacement = compilation
            .llvm
            .find("owning slot replacement: capture, publish, drop")
            .unwrap();
        let replacement = &compilation.llvm[replacement..];
        assert!(
            replacement.find("store ").unwrap()
                < replacement.find("call void @aether_drop_").unwrap()
        );
    }
}

#[test]
fn consecutive_replacements_allocate_and_free_each_owner_exactly_once() {
    let source = "struct S{Buffer<int> value;}int main(){S s=S(Buffer<int>(1,0));Buffer<int> v1=Buffer<int>(1,1);s.value=v1;Buffer<int> v2=Buffer<int>(1,2);s.value=v2;return s.value[0]-2;}";
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        assert_eq!(exact_heap_status(source, optimization, 3), 0);
    }
}

#[test]
fn unsupported_partial_moves_indices_self_assignment_and_live_borrows_stay_rejected() {
    for source in [
        "struct S{Buffer<int> a;}int main(){S s=S(Buffer<int>(1,1));s.a=s.a;return 0;}",
        "struct S{Buffer<int> a;}int main(){S s=S(Buffer<int>(1,1));Buffer<int> x=s.a;return 0;}",
        "struct S{Buffer<int> a;}int main(){S s=S(Buffer<int>(1,1));ref int x=&s.a[0];Buffer<int> n=Buffer<int>(1,2);s.a=n;return *x;}",
        "struct S{Array<Buffer<int>> a;}int main(){S s=S({Buffer<int>(1,1)});Buffer<int> n=Buffer<int>(1,2);s.a[0]=n;return 0;}",
        "void replace(ref mut Buffer<int> a,ref Buffer<int> possibleAlias){Buffer<int> n=Buffer<int>(1,2);*a=n;}int main(){Buffer<int> x=Buffer<int>(1,1);replace(&mut x,&x);return 0;}",
    ] {
        assert!(
            compile_source_with_optimization(
                &SourceFile::new("rejected.ae", source),
                &[],
                OptimizationLevel::O0,
            )
            .is_err(),
            "accepted: {source}"
        );
    }
}

#[test]
fn malformed_mir_and_ssa_replacements_are_rejected_independently() {
    let source = SourceFile::new(
        "corrupt.ae",
        "struct S{Buffer<int> a;}int main(){S s=S(Buffer<int>(1,1));Buffer<int> n=Buffer<int>(1,2);s.a=n;return 0;}",
    );
    let hir = analyze(parse_source(&source).unwrap()).unwrap();
    let mir = lower_hir(hir);
    verify_mir(mir.clone()).unwrap();

    let mut wrong_mir_type = mir.clone();
    let replacement = wrong_mir_type
        .functions
        .iter_mut()
        .flat_map(|function| &mut function.blocks)
        .flat_map(|block| &mut block.instructions)
        .find(|instruction| matches!(instruction.value, Rvalue::ReplaceOwned { .. }))
        .unwrap();
    let Rvalue::ReplaceOwned { value_type, .. } = &mut replacement.value else {
        unreachable!()
    };
    *value_type = TypeId::BOOL;
    assert!(verify_mir(wrong_mir_type).is_err());

    let mut wrong_mir_rhs = mir.clone();
    let replacement = wrong_mir_rhs
        .functions
        .iter_mut()
        .flat_map(|function| &mut function.blocks)
        .flat_map(|block| &mut block.instructions)
        .find(|instruction| matches!(instruction.value, Rvalue::ReplaceOwned { .. }))
        .unwrap();
    let Rvalue::ReplaceOwned { value, .. } = &mut replacement.value else {
        unreachable!()
    };
    *value = Operand::Bool(true);
    assert!(verify_mir(wrong_mir_rhs).is_err());

    let verified = verify_mir(mir).unwrap();
    let ssa = build_ssa(&verified);
    verify_ssa(ssa.clone()).unwrap();
    let mut wrong_ssa = ssa;
    let replacement = wrong_ssa
        .functions
        .iter_mut()
        .flat_map(|function| &mut function.blocks)
        .flat_map(|block| &mut block.instructions)
        .find(|instruction| matches!(instruction.op, SsaOp::ReplaceOwned { .. }))
        .unwrap();
    replacement.ty = TypeId::INT64;
    assert!(verify_ssa(wrong_ssa).is_err());

    let verified = verify_mir(lower_hir(analyze(parse_source(&source).unwrap()).unwrap())).unwrap();
    let mut store_ssa = build_ssa(&verified);
    let replacement = store_ssa
        .functions
        .iter_mut()
        .flat_map(|function| &mut function.blocks)
        .flat_map(|block| &mut block.instructions)
        .find(|instruction| matches!(instruction.op, SsaOp::ReplaceOwned { .. }))
        .unwrap();
    let SsaOp::ReplaceOwned {
        destination, value, ..
    } = replacement.op.clone()
    else {
        unreachable!()
    };
    replacement.op = SsaOp::Store {
        place: destination,
        value,
    };
    assert!(verify_ssa(store_ssa).is_err());
}

#[test]
fn mir_rejects_an_owning_dereference_store_disguised_as_a_move() {
    let source = SourceFile::new(
        "corrupt_dereference_store.ae",
        "void replace(ref mut Buffer<int> slot){Buffer<int> n=Buffer<int>(1,2);*slot=n;}int main(){Buffer<int> x=Buffer<int>(1,1);replace(&mut x);return 0;}",
    );
    let mir = lower_hir(analyze(parse_source(&source).unwrap()).unwrap());
    verify_mir(mir.clone()).unwrap();

    let mut ordinary_move = mir.clone();
    let replacement = ordinary_move
        .functions
        .iter_mut()
        .flat_map(|function| &mut function.blocks)
        .flat_map(|block| &mut block.instructions)
        .find(|instruction| matches!(instruction.value, Rvalue::ReplaceOwned { .. }))
        .unwrap();
    let Rvalue::ReplaceOwned {
        destination, value, ..
    } = replacement.value.clone()
    else {
        unreachable!()
    };
    let Operand::Local(value) = value else {
        unreachable!()
    };
    assert!(matches!(destination.base, PlaceBase::Dereference { .. }));
    replacement.destination = destination;
    replacement.value = Rvalue::Move {
        source: Place {
            base: PlaceBase::Local(value),
            projections: vec![],
        },
    };
    assert!(verify_mir(ordinary_move).is_err());

    let mut shared_mir = mir.clone();
    let replacement = shared_mir
        .functions
        .iter_mut()
        .flat_map(|function| &mut function.blocks)
        .flat_map(|block| &mut block.instructions)
        .find(|instruction| matches!(instruction.value, Rvalue::ReplaceOwned { .. }))
        .unwrap();
    let Rvalue::ReplaceOwned { destination, .. } = &mut replacement.value else {
        unreachable!()
    };
    let PlaceBase::Dereference { mutable, .. } = &mut destination.base else {
        unreachable!()
    };
    *mutable = false;
    assert!(verify_mir(shared_mir).is_err());

    let mut unwind_mir = mir.clone();
    let replacement = unwind_mir
        .functions
        .iter_mut()
        .flat_map(|function| &mut function.blocks)
        .flat_map(|block| &mut block.instructions)
        .find(|instruction| matches!(instruction.value, Rvalue::ReplaceOwned { .. }))
        .unwrap();
    replacement.unwind = Some(BlockId(0));
    assert!(verify_mir(unwind_mir).is_err());

    let verified = verify_mir(mir).unwrap();
    let ssa = build_ssa(&verified);
    verify_ssa(ssa.clone()).unwrap();
    let mut shared_ssa = ssa.clone();
    let replacement = shared_ssa
        .functions
        .iter_mut()
        .flat_map(|function| &mut function.blocks)
        .flat_map(|block| &mut block.instructions)
        .find(|instruction| matches!(instruction.op, SsaOp::ReplaceOwned { .. }))
        .unwrap();
    let SsaOp::ReplaceOwned { destination, .. } = &mut replacement.op else {
        unreachable!()
    };
    let SsaPlaceBase::Dereference { mutable, .. } = &mut destination.base else {
        unreachable!()
    };
    *mutable = false;
    assert!(verify_ssa(shared_ssa).is_err());

    let mut unwind_ssa = ssa;
    let replacement = unwind_ssa
        .functions
        .iter_mut()
        .flat_map(|function| &mut function.blocks)
        .flat_map(|block| &mut block.instructions)
        .find(|instruction| matches!(instruction.op, SsaOp::ReplaceOwned { .. }))
        .unwrap();
    replacement.unwind = Some(BlockId(0));
    assert!(verify_ssa(unwind_ssa).is_err());
}

#[test]
fn rhs_throw_keeps_old_and_post_commit_throw_cleans_new() {
    let source = r#"
open class Problem:Exception { public init() {} }
struct Owner { Buffer<int> value; }
Buffer<int> make(bool fail) {
    Buffer<int> temporary = Buffer<int>(1, 7);
    if (fail) { throw Problem(); }
    return temporary;
}
int main() {
    Owner owner = Owner(Buffer<int>(1, 3));
    try { owner.value = make(true); }
    catch (Problem error) {
        if (owner.value[0] != 3) { return 11; }
    }
    try {
        owner.value = make(false);
        throw Problem();
    } catch (Problem error) {
        if (owner.value[0] != 7) { return 12; }
    }
    return 0;
}
"#;
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        assert_eq!(balanced_status(source, optimization), 0, "{optimization:?}");
        let compilation = compile(source, optimization);
        let replacement = compilation.dumps[&Emit::Mir].find("ReplaceOwned").unwrap();
        assert!(
            !compilation.dumps[&Emit::Mir][replacement..]
                .lines()
                .next()
                .unwrap()
                .contains("unwind: Some")
        );
    }
}

#[test]
fn concrete_list_owner_uses_the_general_operation() {
    let source = "struct S{List<int> values;}int main(){S s=S({1,2});List<int> n={4,5};s.values=n;return s.values[0]-4;}";
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        let compilation = compile(source, optimization);
        assert!(compilation.dumps[&Emit::Mir].contains("ReplaceOwned"));
        assert_eq!(balanced_status(source, optimization), 0);
    }
}

#[test]
fn concrete_owner_type_matrix_preserves_lifecycle_at_o0_o2() {
    let cases = [
        (
            "array",
            "struct S{Array<int> value;}int main(){S s=S({1,2});Array<int> n={4,5};s.value=n;return s.value[0]-4;}",
        ),
        (
            "vector",
            "struct S{Vector<int,Row> value;}int main(){S s=S([1,2]);Vector<int,Row> n=[4,5];s.value=n;return s.value[1]-4;}",
        ),
        (
            "matrix",
            "struct S{Matrix<int> value;}int main(){S s=S([1,2]);Matrix<int> n=[4,5];s.value=n;return s.value[1,1]-4;}",
        ),
        (
            "nested_aggregate",
            "struct Inner{Buffer<int> value;}struct S{Inner inner;Buffer<int> sibling;}int main(){S s=S(Inner(Buffer<int>(1,1)),Buffer<int>(1,9));Inner n=Inner(Buffer<int>(1,4));s.inner=n;return s.inner.value[0]+s.sibling[0]-13;}",
        ),
        (
            "concrete_generic",
            "struct Box<T:Storable>{T value;}struct S{Box<Buffer<int>> box;}int main(){S s=S(Box<Buffer<int>>(Buffer<int>(1,1)));Box<Buffer<int>> n=Box<Buffer<int>>(Buffer<int>(1,4));s.box=n;return s.box.value[0]-4;}",
        ),
    ];
    for (name, source) in cases {
        for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
            let compilation = compile(source, optimization);
            assert!(
                compilation.dumps[&Emit::Mir].contains("ReplaceOwned"),
                "{name} {optimization:?}"
            );
            assert_eq!(
                balanced_status(source, optimization),
                0,
                "{name} {optimization:?}"
            );
        }
    }
}

#[test]
fn string_field_preserves_the_existing_replace_string_protocol() {
    let source = "struct S{string value;}int main(){S s=S(\"a\"+\"b\");string n=\"c\"+\"d\";s.value=n;return int(byteLength(s.value))-2;}";
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        let compilation = compile(source, optimization);
        assert!(compilation.dumps[&Emit::Mir].contains("ReplaceString"));
        assert!(!compilation.dumps[&Emit::Mir].contains("ReplaceOwned"));
        assert_eq!(balanced_status(source, optimization), 0);
        let replacement = compilation.llvm.find("string replacement").unwrap();
        let replacement = &compilation.llvm[replacement..];
        assert!(
            replacement.find("store ").unwrap()
                < replacement.find("@aether_string_release").unwrap()
        );
    }
}

#[test]
fn class_and_interface_struct_fields_remain_blocked_by_the_global_contract() {
    for source in [
        "class C{}struct S{C value;}int main(){return 0;}",
        "interface I{}class C:I{}struct S{I value;}int main(){return 0;}",
    ] {
        let diagnostics = compile_source_with_optimization(
            &SourceFile::new("blocked_handle_field.ae", source),
            &[],
            OptimizationLevel::O0,
        )
        .unwrap_err();
        assert!(
            diagnostics
                .iter()
                .any(|diagnostic| diagnostic.code == "E0274")
        );
    }
}
