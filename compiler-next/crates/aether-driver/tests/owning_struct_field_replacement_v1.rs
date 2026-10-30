//! OWNING-STRUCT-FIELD-REPLACEMENT-V1 cross-layer qualification.

use std::{fmt::Write as _, fs, path::PathBuf, process::Command};

use aether_driver::{ClangToolchain, Emit, OptimizationLevel, compile_source_with_optimization};
use aether_frontend::{FieldId, SourceFile, TypeId, analyze, parse_source};
use aether_middle::{
    BlockId, Operand, Place, PlaceBase, PlaceProjection, Rvalue, SsaOp, SsaPlaceBase,
    SsaPlaceProjection, StoreProvenance, build_ssa, lower_hir, verify_mir, verify_ssa,
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

/// Test-only owner ledger. Allocations are deliberately not returned to the
/// host allocator so pointer identity cannot be reused during one probe. This
/// changes neither the compiler runtime nor its public ABI.
fn identity_ledger(llvm: &str, publication_allocations: &[usize], drop_stages: &[usize]) -> String {
    assert!(drop_stages.len() <= 16);
    let globals = "@replace_ids = internal global [16 x ptr] zeroinitializer\n@replace_drops = internal global [16 x i64] zeroinitializer\n@replace_drop_stages = internal global [16 x i64] zeroinitializer\n@replace_stage = internal global i64 0\n@replace_free_ok = internal global i1 true\n@replace_publication_ok = internal global i1 true\n";
    let mut instrumented = llvm.replacen(
        "@aether_heap_alloc_count = internal global i64 0\n",
        &format!("{globals}@aether_heap_alloc_count = internal global i64 0\n"),
        1,
    );
    instrumented = instrumented.replacen(
        "%alloc_next = add i64 %alloc_count, 1\nstore i64 %alloc_next, ptr @aether_heap_alloc_count",
        "  %replace_alloc_slot = getelementptr [16 x ptr], ptr @replace_ids, i64 0, i64 %alloc_count\n  store ptr %alloc_ptr, ptr %replace_alloc_slot\n  %alloc_next = add i64 %alloc_count, 1\n  store i64 %alloc_next, ptr @aether_heap_alloc_count",
        1,
    );
    assert!(instrumented.contains("%replace_alloc_slot ="));
    let mut identity_scan = String::new();
    for index in 0..16 {
        writeln!(
            identity_scan,
            "  %replace_id_slot_{index} = getelementptr [16 x ptr], ptr @replace_ids, i64 0, i64 {index}\n  %replace_id_{index} = load ptr, ptr %replace_id_slot_{index}\n  %replace_is_id_{index} = icmp eq ptr %ptr, %replace_id_{index}"
        )
        .unwrap();
        let previous = if index == 0 {
            "-1".to_string()
        } else {
            format!("%replace_identity_{}", index - 1)
        };
        writeln!(
            identity_scan,
            "  %replace_identity_{index} = select i1 %replace_is_id_{index}, i64 {index}, i64 {previous}"
        )
        .unwrap();
    }
    let free_probe = format!(
        "{identity_scan}  %replace_drop_slot = getelementptr [16 x i64], ptr @replace_drops, i64 0, i64 %replace_identity_15\n  %replace_drop_count = load i64, ptr %replace_drop_slot\n  %replace_first_drop = icmp eq i64 %replace_drop_count, 0\n  %replace_drop_next = add i64 %replace_drop_count, 1\n  store i64 %replace_drop_next, ptr %replace_drop_slot\n  %replace_drop_stage_slot = getelementptr [16 x i64], ptr @replace_drop_stages, i64 0, i64 %replace_identity_15\n  %replace_current_stage = load i64, ptr @replace_stage\n  store i64 %replace_current_stage, ptr %replace_drop_stage_slot\n  %replace_old_ok = load i1, ptr @replace_free_ok\n  %replace_free_event_ok = and i1 %replace_old_ok, %replace_first_drop\n  store i1 %replace_free_event_ok, ptr @replace_free_ok\n  ; test ledger deliberately retains the allocation"
    );
    instrumented = instrumented.replacen("call void @free(ptr %ptr)", &free_probe, 1);
    assert!(
        !instrumented.contains("call void @free(ptr %ptr)"),
        "{:?}",
        instrumented
            .lines()
            .filter(|line| line.contains("@free"))
            .collect::<Vec<_>>()
    );

    let mut publication = 0;
    let mut output = String::with_capacity(instrumented.len() + 4096);
    let mut after_replacement_marker = false;
    for line in instrumented.lines() {
        output.push_str(line);
        output.push('\n');
        if line.contains("owning slot replacement: capture, publish, drop") {
            after_replacement_marker = true;
            continue;
        }
        if !after_replacement_marker || !line.trim_start().starts_with("store { ptr, i64 }") {
            continue;
        }
        let expected = publication_allocations[publication];
        let value = line
            .trim_start()
            .strip_prefix("store { ptr, i64 } ")
            .and_then(|tail| tail.split(", ptr ").next())
            .expect("Buffer publication store value");
        writeln!(
            output,
            "  %replace_published_ptr_{publication} = extractvalue {{ ptr, i64 }} {value}, 0\n  %replace_expected_slot_{publication} = getelementptr [16 x ptr], ptr @replace_ids, i64 0, i64 {expected}\n  %replace_expected_ptr_{publication} = load ptr, ptr %replace_expected_slot_{publication}\n  %replace_publication_identity_ok_{publication} = icmp eq ptr %replace_published_ptr_{publication}, %replace_expected_ptr_{publication}\n  %replace_publication_stage_{publication} = load i64, ptr @replace_stage\n  %replace_publication_order_ok_{publication} = icmp eq i64 %replace_publication_stage_{publication}, {publication}\n  %replace_publication_event_ok_{publication} = and i1 %replace_publication_identity_ok_{publication}, %replace_publication_order_ok_{publication}\n  %replace_before_publication_ok_{publication} = load i1, ptr @replace_publication_ok\n  %replace_after_publication_ok_{publication} = and i1 %replace_before_publication_ok_{publication}, %replace_publication_event_ok_{publication}\n  store i1 %replace_after_publication_ok_{publication}, ptr @replace_publication_ok\n  store i64 {}, ptr @replace_stage",
            publication + 1
        )
        .unwrap();
        publication += 1;
        after_replacement_marker = false;
    }
    assert_eq!(publication, publication_allocations.len());

    let mut checks = String::new();
    for (index, stage) in drop_stages.iter().enumerate() {
        writeln!(
            checks,
            "  %replace_final_drop_slot_{index} = getelementptr [16 x i64], ptr @replace_drops, i64 0, i64 {index}\n  %replace_final_drop_{index} = load i64, ptr %replace_final_drop_slot_{index}\n  %replace_final_drop_once_{index} = icmp eq i64 %replace_final_drop_{index}, 1\n  %replace_final_stage_slot_{index} = getelementptr [16 x i64], ptr @replace_drop_stages, i64 0, i64 {index}\n  %replace_final_stage_{index} = load i64, ptr %replace_final_stage_slot_{index}\n  %replace_final_stage_ok_{index} = icmp eq i64 %replace_final_stage_{index}, {stage}\n  %replace_final_identity_ok_{index} = and i1 %replace_final_drop_once_{index}, %replace_final_stage_ok_{index}\n  %replace_final_old_ok_{index} = load i1, ptr @replace_free_ok\n  %replace_final_new_ok_{index} = and i1 %replace_final_old_ok_{index}, %replace_final_identity_ok_{index}\n  store i1 %replace_final_new_ok_{index}, ptr @replace_free_ok"
        )
        .unwrap();
    }
    write!(
        checks,
        "  %replace_final_allocs = load i64, ptr @aether_heap_alloc_count\n  %replace_final_frees = load i64, ptr @aether_heap_free_count\n  %replace_final_alloc_count_ok = icmp eq i64 %replace_final_allocs, {}\n  %replace_final_free_count_ok = icmp eq i64 %replace_final_frees, {}\n  %replace_final_counts_ok = and i1 %replace_final_alloc_count_ok, %replace_final_free_count_ok\n  %replace_final_free_ok = load i1, ptr @replace_free_ok\n  %replace_final_publication_ok = load i1, ptr @replace_publication_ok\n  %replace_final_result_ok = icmp eq i32 %process_status, 0\n  %replace_final_status_result = select i1 %replace_final_result_ok, i32 0, i32 94\n  %replace_final_status_publication = select i1 %replace_final_publication_ok, i32 %replace_final_status_result, i32 93\n  %replace_final_status_free = select i1 %replace_final_free_ok, i32 %replace_final_status_publication, i32 92\n  %replace_final_status = select i1 %replace_final_counts_ok, i32 %replace_final_status_free, i32 91\n  ret i32 %replace_final_status",
        drop_stages.len(),
        drop_stages.len()
    )
    .unwrap();
    output.replace("  ret i32 %process_status", &checks)
}

fn linked_status(llvm: &str, optimization: OptimizationLevel, label: &str) -> i32 {
    let output = Output::new(label);
    ClangToolchain::default()
        .with_optimization(optimization)
        .link_executable(llvm, &output.0)
        .unwrap();
    Command::new(&output.0)
        .status()
        .unwrap()
        .code()
        .unwrap_or(-1)
}

#[derive(Clone, Copy)]
enum DropMutation {
    Omit,
    Duplicate,
    BeforePublish,
}

fn mutate_first_replace_drop(llvm: &str, mutation: DropMutation) -> String {
    let mut lines: Vec<_> = llvm.lines().map(str::to_owned).collect();
    let marker = lines
        .iter()
        .position(|line| line.contains("owning slot replacement: capture, publish, drop"))
        .unwrap();
    let store = (marker + 1..lines.len())
        .find(|index| lines[*index].trim_start().starts_with("store "))
        .unwrap();
    let drop = (store + 1..lines.len())
        .find(|index| lines[*index].contains("call void @aether_drop_"))
        .unwrap();
    match mutation {
        DropMutation::Omit => {
            lines.remove(drop);
        }
        DropMutation::Duplicate => {
            let duplicate = lines[drop].clone();
            lines.insert(drop + 1, duplicate);
        }
        DropMutation::BeforePublish => {
            let drop = lines.remove(drop);
            lines.insert(store, drop);
        }
    }
    lines.join("\n") + "\n"
}

const POSITIVE: &str = r"
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
";

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
    let source = "struct S{Buffer<int> value;Buffer<int> left;Buffer<int> right;}int main(){S s=S(Buffer<int>(1,0),Buffer<int>(1,7),Buffer<int>(1,9));Buffer<int> v1=Buffer<int>(1,1);s.value=v1;Buffer<int> v2=Buffer<int>(1,2);s.value=v2;return s.value[0]+s.left[0]+s.right[0]-18;}";
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        let compilation = compile(source, optimization);
        let ledger = identity_ledger(&compilation.llvm, &[3, 4], &[1, 2, 2, 2, 2]);
        assert_eq!(linked_status(&ledger, optimization, "identity"), 0);

        for (label, mutation) in [
            ("omit", DropMutation::Omit),
            ("duplicate", DropMutation::Duplicate),
            ("reorder", DropMutation::BeforePublish),
        ] {
            let corrupted = mutate_first_replace_drop(&compilation.llvm, mutation);
            let corrupted = identity_ledger(&corrupted, &[3, 4], &[1, 2, 2, 2, 2]);
            assert_ne!(
                linked_status(&corrupted, optimization, label),
                0,
                "mutation {label} escaped at {optimization:?}"
            );
        }
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
        "void replace(ref mut Buffer<int> a,ref int element){Buffer<int> n=Buffer<int>(1,2);*a=n;int x=*element;}int main(){Buffer<int> x=Buffer<int>(1,1);replace(&mut x,&x[0]);return 0;}",
        "void replace(ref mut List<int> a,ref int element){List<int> n={2};*a=n;int x=*element;}int main(){List<int> x={1};replace(&mut x,&x[0]);return 0;}",
        "void replace(ref mut Array<int> a,View<int> view){Array<int> n={2};*a=n;int x=view[0];}int main(){Array<int> x={1};replace(&mut x,view(x));return 0;}",
        "void replace(ref mut Vector<int,Row> a,VectorView<int,Row> view){Vector<int,Row> n=[2];*a=n;int x=view[1];}int main(){Vector<int,Row> x=[1];replace(&mut x,vector_view(x));return 0;}",
        "void replace(ref mut Matrix<int> a,MatrixView<int> view){Matrix<int> n=[2];*a=n;int x=view[1,1];}int main(){Matrix<int> x=[1];replace(&mut x,matrix_view(x));return 0;}",
        "struct Nested{Buffer<int> value;}void replace(ref mut Nested a,ref int element){Nested n=Nested(Buffer<int>(1,2));*a=n;int x=*element;}int main(){Nested x=Nested(Buffer<int>(1,1));replace(&mut x,&x.value[0]);return 0;}",
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
fn independent_element_reference_remains_admitted() {
    let source = r"
struct Holder { Buffer<int> value; }
void replaceLocal(ref int independent) {
    Holder holder = Holder(Buffer<int>(1, 1));
    Buffer<int> next = Buffer<int>(1, 2);
    holder.value = next;
    int observed = *independent;
}

int main() {
    Buffer<int> other = Buffer<int>(1, 7);
    replaceLocal(&other[0]);
    return 0;
}
";
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        compile(source, optimization);
    }
}

#[test]
fn rhs_call_borrow_ends_before_commit_while_lexical_aliases_remain_live() {
    let positive = r"
struct Holder { Buffer<int> value; }
Buffer<int> next(ref int old) { return Buffer<int>(1, *old + 1); }
int main() {
    Holder holder = Holder(Buffer<int>(1, 4));
    holder.value = next(holder.value[0]);
    return holder.value[0] - 5;
}

";
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        let compilation = compile(positive, optimization);
        for phase in [Emit::Mir, Emit::Ssa] {
            let dump = &compilation.dumps[&phase];
            assert!(dump.find("EndBorrow").unwrap() < dump.find("ReplaceOwned").unwrap());
        }
        assert_eq!(balanced_status(positive, optimization), 0);
    }

    let rejected = [
        // Last use has occurred, but the ordinary lexical reference remains in scope.
        "struct S{Buffer<int> value;}int main(){S s=S(Buffer<int>(1,1));ref int r=&s.value[0];int seen=*r;Buffer<int> n=Buffer<int>(1,2);s.value=n;return seen-1;}",
        // A copied/reborrowed reference keeps the same owner provenance.
        "struct S{Buffer<int> value;}int main(){S s=S(Buffer<int>(1,1));ref int r=&s.value[0];ref int copy=r;int seen=*copy;Buffer<int> n=Buffer<int>(1,2);s.value=n;return seen-1;}",
        // View copies and derived views keep the replaced backing alive.
        "struct S{Matrix<int> value;}int main(){S s=S([1]);MatrixView<int> v=matrix_view(s.value);MatrixView<int> copy=v;int seen=copy[1,1];Matrix<int> n=[2];s.value=n;return seen-1;}",
        // The join cannot forget a borrow that is live on either predecessor.
        "struct S{Buffer<int> value;}int main(){S s=S(Buffer<int>(1,1));ref int r=&s.value[0];int seen=0;if(true){seen=*r;}Buffer<int> n=Buffer<int>(1,2);s.value=n;return seen-1;}",
        // A use after replacement is rejected rather than treated as an implicit End.
        "struct S{Buffer<int> value;}int main(){S s=S(Buffer<int>(1,1));ref int r=&s.value[0];Buffer<int> n=Buffer<int>(1,2);s.value=n;return *r;}",
    ];
    for source in rejected {
        assert!(
            compile_source_with_optimization(
                &SourceFile::new("live_replace_alias.ae", source),
                &[],
                OptimizationLevel::O0,
            )
            .is_err(),
            "accepted live alias: {source}"
        );
    }
}

#[test]
fn replace_owned_rhs_borrow_end_metadata_corruption_fails_closed() {
    let source = SourceFile::new(
        "replace_rhs_borrow_end.ae",
        "struct S{Buffer<int> value;}Buffer<int> next(ref int old){return Buffer<int>(1,*old+1);}int main(){S s=S(Buffer<int>(1,1));s.value=next(s.value[0]);return s.value[0]-2;}",
    );
    let hir = analyze(parse_source(&source).unwrap()).unwrap();
    let mir = lower_hir(hir);
    verify_mir(mir.clone()).unwrap();

    let mut bad_mir_end = mir.clone();
    let end = bad_mir_end
        .functions
        .iter_mut()
        .flat_map(|function| &mut function.blocks)
        .flat_map(|block| &mut block.instructions)
        .find(|instruction| matches!(instruction.value, Rvalue::EndBorrow { .. }))
        .unwrap();
    let Rvalue::EndBorrow { call, .. } = &mut end.value else {
        unreachable!()
    };
    call.argument_index += 1;
    assert!(verify_mir(bad_mir_end).is_err());

    let verified = verify_mir(mir).unwrap();
    let ssa = build_ssa(&verified);
    verify_ssa(ssa.clone()).unwrap();

    let mut bad_ssa_end = ssa.clone();
    let end = bad_ssa_end
        .functions
        .iter_mut()
        .flat_map(|function| &mut function.blocks)
        .flat_map(|block| &mut block.instructions)
        .find(|instruction| matches!(instruction.op, SsaOp::EndBorrow { .. }))
        .unwrap();
    let SsaOp::EndBorrow { call, .. } = &mut end.op else {
        unreachable!()
    };
    call.argument_index += 1;
    assert!(verify_ssa(bad_ssa_end).is_err());

    let mut use_after_end = ssa;
    let end = use_after_end
        .functions
        .iter_mut()
        .flat_map(|function| &mut function.blocks)
        .flat_map(|block| &mut block.instructions)
        .find(|instruction| matches!(instruction.op, SsaOp::EndBorrow { .. }))
        .unwrap();
    let SsaOp::EndBorrow { reference, .. } = end.op.clone() else {
        unreachable!()
    };
    end.op = SsaOp::Use(reference);
    assert!(verify_ssa(use_after_end).is_err());
}

#[test]
fn mir_and_ssa_reconstruct_element_alias_risk_from_parameter_types() {
    let source = SourceFile::new(
        "parameter_provenance.ae",
        "void observe(ref int x){}void replace(ref mut Buffer<int> slot,ref bool independent){Buffer<int> n=Buffer<int>(1,2);*slot=n;}int main(){Buffer<int> x=Buffer<int>(1,1);bool b=false;replace(&mut x,&b);return 0;}",
    );
    let hir = analyze(parse_source(&source).unwrap()).unwrap();
    let mir = lower_hir(hir);
    verify_mir(mir.clone()).unwrap();
    let reference_int = mir
        .types
        .entries()
        .find_map(|(ty, _)| {
            (mir.types.reference_info(ty) == Some((TypeId::INT64, false))).then_some(ty)
        })
        .unwrap();
    let target = mir
        .functions
        .iter()
        .position(|function| {
            function.blocks.iter().any(|block| {
                block
                    .instructions
                    .iter()
                    .any(|instruction| matches!(instruction.value, Rvalue::ReplaceOwned { .. }))
            })
        })
        .unwrap();

    let mut invalid_mir = mir.clone();
    let function = &mut invalid_mir.functions[target];
    let parameter_local = function.parameters[1].local;
    function.parameters[1].ty = reference_int;
    function.locals[parameter_local.0 as usize].ty = reference_int;
    invalid_mir.signatures[function.id.0 as usize].parameters[1].ty = reference_int;
    assert!(verify_mir(invalid_mir).is_err());

    let verified = verify_mir(mir).unwrap();
    let mut invalid_ssa = build_ssa(&verified);
    let function = &mut invalid_ssa.functions[target];
    let parameter_local = function.parameters[1].local;
    function.parameters[1].ty = reference_int;
    function.bindings[parameter_local.0 as usize].ty = reference_int;
    if let Some(memory) = function
        .memory_locals
        .iter_mut()
        .find(|memory| memory.local == parameter_local)
    {
        memory.ty = reference_int;
    }
    invalid_ssa.signatures[function.id.0 as usize].parameters[1].ty = reference_int;
    assert!(verify_ssa(invalid_ssa).is_err());
}

#[test]
#[allow(clippy::too_many_lines)]
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

    let mut wrong_mir_field = mir.clone();
    let replacement = wrong_mir_field
        .functions
        .iter_mut()
        .flat_map(|function| &mut function.blocks)
        .flat_map(|block| &mut block.instructions)
        .find(|instruction| matches!(instruction.value, Rvalue::ReplaceOwned { .. }))
        .unwrap();
    let Rvalue::ReplaceOwned { destination, .. } = &mut replacement.value else {
        unreachable!()
    };
    destination.projections[0] = PlaceProjection::Field(FieldId(u32::MAX));
    assert!(verify_mir(wrong_mir_field).is_err());

    let mut duplicate_mir_consume = mir.clone();
    let (block, index) = duplicate_mir_consume
        .functions
        .iter_mut()
        .flat_map(|function| &mut function.blocks)
        .find_map(|block| {
            block
                .instructions
                .iter()
                .position(|instruction| matches!(instruction.value, Rvalue::ReplaceOwned { .. }))
                .map(|index| (block, index))
        })
        .unwrap();
    let duplicate = block.instructions[index].clone();
    block.instructions.insert(index + 1, duplicate);
    assert!(verify_mir(duplicate_mir_consume).is_err());

    let verified = verify_mir(mir).unwrap();
    let ssa = build_ssa(&verified);
    verify_ssa(ssa.clone()).unwrap();
    let mut wrong_ssa = ssa.clone();
    let replacement = wrong_ssa
        .functions
        .iter_mut()
        .flat_map(|function| &mut function.blocks)
        .flat_map(|block| &mut block.instructions)
        .find(|instruction| matches!(instruction.op, SsaOp::ReplaceOwned { .. }))
        .unwrap();
    replacement.ty = TypeId::INT64;
    assert!(verify_ssa(wrong_ssa).is_err());

    let mut wrong_ssa_field = ssa.clone();
    let replacement = wrong_ssa_field
        .functions
        .iter_mut()
        .flat_map(|function| &mut function.blocks)
        .flat_map(|block| &mut block.instructions)
        .find(|instruction| matches!(instruction.op, SsaOp::ReplaceOwned { .. }))
        .unwrap();
    let SsaOp::ReplaceOwned { destination, .. } = &mut replacement.op else {
        unreachable!()
    };
    destination.projections[0] = SsaPlaceProjection::Field(FieldId(u32::MAX));
    assert!(verify_ssa(wrong_ssa_field).is_err());

    let mut duplicate_ssa_consume = ssa;
    let (block, index) = duplicate_ssa_consume
        .functions
        .iter_mut()
        .flat_map(|function| &mut function.blocks)
        .find_map(|block| {
            block
                .instructions
                .iter()
                .position(|instruction| matches!(instruction.op, SsaOp::ReplaceOwned { .. }))
                .map(|index| (block, index))
        })
        .unwrap();
    let duplicate = block.instructions[index].clone();
    block.instructions.insert(index + 1, duplicate);
    assert!(verify_ssa(duplicate_ssa_consume).is_err());

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
        provenance: StoreProvenance::Initialize,
    };
    assert!(verify_ssa(store_ssa).is_err());
}

#[test]
fn replacement_cannot_transition_its_root_drop_flag() {
    let source = SourceFile::new(
        "replace_root_flag.ae",
        "open class Problem:Exception{public init(){}}struct S{Buffer<int> value;}Buffer<int> make(){return Buffer<int>(1,2);}int main(){S s=S(Buffer<int>(1,1));s.value=make();return 0;}",
    );
    let mut mir = lower_hir(analyze(parse_source(&source).unwrap()).unwrap());
    verify_mir(mir.clone()).unwrap();
    let function = mir
        .functions
        .iter_mut()
        .find(|function| {
            function.blocks.iter().any(|block| {
                block
                    .instructions
                    .iter()
                    .any(|instruction| matches!(instruction.value, Rvalue::ReplaceOwned { .. }))
            })
        })
        .unwrap();
    let (block_index, instruction_index, root) =
        function
            .blocks
            .iter()
            .enumerate()
            .find_map(|(block_index, block)| {
                block.instructions.iter().enumerate().find_map(
                    |(instruction_index, instruction)| {
                        let Rvalue::ReplaceOwned { destination, .. } = &instruction.value else {
                            return None;
                        };
                        let PlaceBase::Local(root) = destination.base else {
                            return None;
                        };
                        Some((block_index, instruction_index, root))
                    },
                )
            })
            .unwrap();
    let flag = function
        .drop_flags
        .iter()
        .find(|entry| entry.owner == root)
        .expect("exception-enabled root drop flag")
        .flag;
    let mut forged_transition =
        function.blocks[block_index].instructions[instruction_index].clone();
    forged_transition.destination = Place {
        base: PlaceBase::Local(flag),
        projections: Vec::new(),
    };
    forged_transition.value = Rvalue::Use(Operand::Bool(false));
    forged_transition.unwind = None;
    function.blocks[block_index]
        .instructions
        .insert(instruction_index + 1, forged_transition);
    assert!(verify_mir(mir).is_err());
}

#[test]
fn rhs_owner_obligation_cannot_be_omitted_or_consumed_twice() {
    let source = SourceFile::new(
        "replace_rhs_consumption.ae",
        "struct S{Buffer<int> a;Buffer<int> b;}int main(){S s=S(Buffer<int>(1,0),Buffer<int>(1,0));Buffer<int> x=Buffer<int>(1,1);Buffer<int> y=Buffer<int>(1,2);s.a=x;s.b=y;return 0;}",
    );
    let mir = lower_hir(analyze(parse_source(&source).unwrap()).unwrap());
    verify_mir(mir.clone()).unwrap();

    let mut omitted_mir = mir.clone();
    let replacements: Vec<_> = omitted_mir
        .functions
        .iter()
        .flat_map(|function| &function.blocks)
        .flat_map(|block| &block.instructions)
        .filter_map(|instruction| match &instruction.value {
            Rvalue::ReplaceOwned { value, .. } => Some(value.clone()),
            _ => None,
        })
        .collect();
    let first = omitted_mir
        .functions
        .iter_mut()
        .flat_map(|function| &mut function.blocks)
        .flat_map(|block| &mut block.instructions)
        .find(|instruction| matches!(instruction.value, Rvalue::ReplaceOwned { .. }))
        .unwrap();
    let Rvalue::ReplaceOwned { value, .. } = &mut first.value else {
        unreachable!()
    };
    *value = replacements[1].clone();
    assert!(verify_mir(omitted_mir).is_err());

    let verified = verify_mir(mir).unwrap();
    let ssa = build_ssa(&verified);
    verify_ssa(ssa.clone()).unwrap();
    let mut omitted_ssa = ssa;
    let replacements: Vec<_> = omitted_ssa
        .functions
        .iter()
        .flat_map(|function| &function.blocks)
        .flat_map(|block| &block.instructions)
        .filter_map(|instruction| match &instruction.op {
            SsaOp::ReplaceOwned { value, .. } => Some(value.clone()),
            _ => None,
        })
        .collect();
    let first = omitted_ssa
        .functions
        .iter_mut()
        .flat_map(|function| &mut function.blocks)
        .flat_map(|block| &mut block.instructions)
        .find(|instruction| matches!(instruction.op, SsaOp::ReplaceOwned { .. }))
        .unwrap();
    let SsaOp::ReplaceOwned { value, .. } = &mut first.op else {
        unreachable!()
    };
    *value = replacements[1].clone();
    assert!(verify_ssa(omitted_ssa).is_err());
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
    let source = r"
open class Problem:Exception { public init() {} }
struct Owner { Buffer<int> value; }
Buffer<int> make(bool fail) {
    Buffer<int> temporary = Buffer<int>(1, 7);
    if (fail) { throw Problem(); }
    return temporary;
}
void replace(ref mut Owner owner, bool fail) {
    (*owner).value = make(fail);
}
int main() {
    Owner owner = Owner(Buffer<int>(1, 3));
    try { replace(&mut owner, true); }
    catch (Problem error) {
        if (owner.value[0] != 3) { return 11; }
    }
    try {
        replace(&mut owner, false);
        throw Problem();
    } catch (Problem error) {
        if (owner.value[0] != 7) { return 12; }
    }
    return 0;
}
";
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        assert_eq!(balanced_status(source, optimization), 0, "{optimization:?}");
        let compilation = compile(source, optimization);
        let ledger = identity_ledger(&compilation.llvm, &[3], &[1, 0, 0, 1, 1]);
        assert_eq!(linked_status(&ledger, optimization, "throw-identity"), 0);
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

    let symbolic = "struct Box<T:Storable>{T value;}void replace<T:Storable>(ref mut Box<T> slot,T next){(*slot).value=next;}int main(){return 0;}";
    assert!(
        compile_source_with_optimization(
            &SourceFile::new("symbolic_replace_owned.ae", symbolic),
            &[],
            OptimizationLevel::O0,
        )
        .is_err()
    );
}
