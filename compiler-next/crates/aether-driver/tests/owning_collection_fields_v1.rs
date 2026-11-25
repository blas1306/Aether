//! OWNING-COLLECTION-FIELDS-V1 SSA ownership-continuity qualification.

use std::{fs, path::PathBuf, process::Command};

use aether_driver::{ClangToolchain, Emit, OptimizationLevel, compile_source_with_optimization};
use aether_frontend::{FieldId, SourceFile, TypeId, analyze, parse_source};
use aether_middle::{
    DescriptorCommitKind, SsaInstruction, SsaIr, SsaOp, SsaOperand, SsaPlace, SsaPlaceBase,
    StoreProvenance, ValueId, build_ssa, lower_hir, verify_mir, verify_ssa,
};

fn raw(source: &str) -> SsaIr {
    let source = SourceFile::new("owning_collection_fields_v1.ae", source);
    let hir = analyze(parse_source(&source).unwrap()).unwrap();
    build_ssa(&verify_mir(lower_hir(hir)).unwrap())
}

fn failure(ssa: SsaIr) -> String {
    verify_ssa(ssa)
        .expect_err("corrupted SSA must be rejected")
        .into_iter()
        .map(|diagnostic| diagnostic.message)
        .collect::<Vec<_>>()
        .join("\n")
}

fn next_value(ssa: &SsaIr) -> ValueId {
    ValueId(
        ssa.functions
            .iter()
            .flat_map(|function| &function.blocks)
            .flat_map(|block| &block.instructions)
            .map(|instruction| instruction.result.0)
            .max()
            .unwrap()
            + 1,
    )
}

struct Output(PathBuf);

impl Output {
    fn new(label: &str) -> Self {
        static NEXT: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
        Self(std::env::temp_dir().join(format!(
            "aether-owning-collection-fields-{label}-{}-{}",
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

const ROOT: &str = r#"
struct Item { string name; }
int main() {
    List<Item> items = {};
    push(items, Item("root"));
    return 0;
}
"#;

const PROMOTED_FIELD: &str = r#"
struct Item { string name; }
enum Status { Ok, Bad }
struct Result { List<Item> items; Status status; }
int main() {
    Result result = Result({}, Status.Ok);
    push(result.items, Item("field"));
    return 0;
}
"#;

const RESERVE_ROOT: &str = r#"
int main() {
    List<string> values = {"value"};
    reserve(values, 8);
    return 0;
}
"#;

const MEMORY_FIELD: &str = r#"
struct Item { string name; }
struct Result { List<Item> items; int state; }
void observe(ref Result result) { return; }
int main() {
    Result result = Result({}, 7);
    observe(&result);
    push(result.items, Item("memory"));
    return 0;
}
"#;

const REF_MUT_FIELD: &str = r#"
struct Item { string name; }
struct Result { List<Item> items; int state; }
void append(ref mut Result result) {
    push((*result).items, Item("reference"));
    return;
}
int main() {
    Result result = Result({}, 9);
    append(&mut result);
    return 0;
}
"#;

const MATRIX_FIELD: &str = r#"
struct MatrixBox { Matrix<int> value; }
int main() {
    MatrixBox boxed = MatrixBox([]);
    Vector<int,Row> row = [11, 13];
    boxed.value.add(row);
    if (boxed.value[1,2] != 13) { return 1; }
    return 0;
}
"#;

#[test]
fn raw_ssa_freezes_the_three_descriptor_continuity_shapes() {
    let root = raw(ROOT);
    assert!(root.dump().contains("ListPush"));
    assert!(!root.dump().contains("InsertField"));
    verify_ssa(root).unwrap();

    let promoted = raw(PROMOTED_FIELD);
    assert!(promoted.dump().contains("ListPush"));
    assert!(promoted.dump().contains("InsertField"));
    verify_ssa(promoted).unwrap();

    let reserve = raw(RESERVE_ROOT);
    assert!(reserve.dump().contains("ListReserve"));
    verify_ssa(reserve).unwrap();

    let memory = raw(MEMORY_FIELD);
    assert!(memory.functions.iter().flat_map(|function| &function.blocks).flat_map(|block| &block.instructions).any(|instruction| matches!(&instruction.op, SsaOp::Store { place, .. } if matches!(place.base, SsaPlaceBase::MemoryLocal(_)) && !place.projections.is_empty())));
    verify_ssa(memory).unwrap();

    let by_reference = raw(REF_MUT_FIELD);
    assert!(verify_ssa(by_reference).is_ok());

    let matrix_field = raw(MATRIX_FIELD);
    assert!(matrix_field.dump().contains("MatrixAdd"));
    assert!(matrix_field.dump().contains("InsertField"));
    verify_ssa(matrix_field).unwrap();
}

#[test]
#[allow(clippy::too_many_lines)]
fn promoted_field_requires_exact_typed_adjacent_single_use_continuation() {
    let mut wrong_field = raw(PROMOTED_FIELD);
    let insertion = wrong_field
        .functions
        .iter_mut()
        .flat_map(|function| &mut function.blocks)
        .flat_map(|block| &mut block.instructions)
        .find(|instruction| matches!(instruction.op, SsaOp::InsertField { .. }))
        .unwrap();
    let SsaOp::InsertField { projections, .. } = &mut insertion.op else {
        unreachable!()
    };
    projections[0] = FieldId(u32::MAX);
    let message = failure(wrong_field);
    assert!(message.contains("field"), "{message}");

    let mut wrong_producer = raw(PROMOTED_FIELD);
    let insertion = wrong_producer
        .functions
        .iter()
        .flat_map(|function| &function.blocks)
        .flat_map(|block| &block.instructions)
        .find_map(|instruction| match &instruction.op {
            SsaOp::InsertField { aggregate, .. } => Some(aggregate.clone()),
            _ => None,
        })
        .unwrap();
    let producer = wrong_producer
        .functions
        .iter_mut()
        .flat_map(|function| &mut function.blocks)
        .flat_map(|block| &mut block.instructions)
        .find(|instruction| matches!(instruction.op, SsaOp::ListPush { .. }))
        .unwrap();
    producer.op = SsaOp::Use(insertion);
    assert!(failure(wrong_producer).contains("copy type mismatch"));

    let mut split = raw(PROMOTED_FIELD);
    let fresh = next_value(&split);
    let block = split
        .functions
        .iter_mut()
        .flat_map(|function| &mut function.blocks)
        .find(|block| {
            block
                .instructions
                .iter()
                .any(|instruction| matches!(instruction.op, SsaOp::InsertField { .. }))
        })
        .unwrap();
    let index = block
        .instructions
        .iter()
        .position(|instruction| matches!(instruction.op, SsaOp::InsertField { .. }))
        .unwrap();
    let span = block.instructions[index].span;
    block.instructions.insert(
        index,
        SsaInstruction {
            result: fresh,
            ty: TypeId::BOOL,
            op: SsaOp::Use(SsaOperand::Bool(true)),
            span,
            unwind: None,
            binding: None,
        },
    );
    assert!(failure(split).contains("continuation is invalid"));

    let mut multiply_used = raw(PROMOTED_FIELD);
    let fresh = next_value(&multiply_used);
    let block = multiply_used
        .functions
        .iter_mut()
        .flat_map(|function| &mut function.blocks)
        .find(|block| {
            block
                .instructions
                .iter()
                .any(|instruction| matches!(instruction.op, SsaOp::InsertField { .. }))
        })
        .unwrap();
    let insertion = block
        .instructions
        .iter()
        .position(|instruction| matches!(instruction.op, SsaOp::InsertField { .. }))
        .unwrap();
    let producer = block.instructions[insertion - 1].result;
    let producer_ty = block.instructions[insertion - 1].ty;
    let span = block.instructions[insertion].span;
    block.instructions.insert(
        insertion + 1,
        SsaInstruction {
            result: fresh,
            ty: TypeId::BOOL,
            op: SsaOp::Drop {
                owner: SsaPlace {
                    base: SsaPlaceBase::Value(SsaOperand::Value(producer)),
                    projections: Vec::new(),
                },
            },
            span,
            unwind: None,
            binding: None,
        },
    );
    assert_ne!(producer_ty, TypeId::BOOL);
    assert!(failure(multiply_used).contains("continuation is invalid"));
}

#[test]
#[allow(clippy::too_many_lines)]
fn promoted_field_ledger_rejects_omitted_and_duplicate_consumptions_and_drops() {
    let mut root_source_double_consume = raw(ROOT);
    let fresh = next_value(&root_source_double_consume);
    let block = root_source_double_consume
        .functions
        .iter_mut()
        .flat_map(|function| &mut function.blocks)
        .find(|block| {
            block
                .instructions
                .iter()
                .any(|instruction| matches!(instruction.op, SsaOp::ListPush { .. }))
        })
        .unwrap();
    let push = block
        .instructions
        .iter()
        .position(|instruction| matches!(instruction.op, SsaOp::ListPush { .. }))
        .unwrap();
    let SsaOp::ListPush { source, .. } = &block.instructions[push].op else {
        unreachable!()
    };
    let SsaPlaceBase::Value(SsaOperand::Value(source_owner)) = source.base else {
        unreachable!()
    };
    assert!(source.projections.is_empty());
    let span = block.instructions[push].span;
    block.instructions.insert(
        push + 1,
        SsaInstruction {
            result: fresh,
            ty: TypeId::BOOL,
            op: SsaOp::Drop {
                owner: SsaPlace {
                    base: SsaPlaceBase::Value(SsaOperand::Value(source_owner)),
                    projections: Vec::new(),
                },
            },
            span,
            unwind: None,
            binding: None,
        },
    );
    assert!(failure(root_source_double_consume).contains("more than once"));

    let mut omitted_commit = raw(PROMOTED_FIELD);
    let block = omitted_commit
        .functions
        .iter_mut()
        .flat_map(|function| &mut function.blocks)
        .find(|block| {
            block
                .instructions
                .iter()
                .any(|instruction| matches!(instruction.op, SsaOp::InsertField { .. }))
        })
        .unwrap();
    let ordinary_owner = block
        .instructions
        .iter()
        .find(|instruction| matches!(instruction.op, SsaOp::ListInit { .. }))
        .map(|instruction| instruction.result)
        .unwrap();
    let insertion = block
        .instructions
        .iter_mut()
        .find(|instruction| matches!(instruction.op, SsaOp::InsertField { .. }))
        .unwrap();
    let SsaOp::InsertField { value, .. } = &mut insertion.op else {
        unreachable!()
    };
    *value = SsaOperand::Value(ordinary_owner);
    let message = failure(omitted_commit);
    assert!(message.contains("typed descriptor producer"), "{message}");

    let mut duplicate_source_consume = raw(PROMOTED_FIELD);
    let fresh = next_value(&duplicate_source_consume);
    let block = duplicate_source_consume
        .functions
        .iter_mut()
        .flat_map(|function| &mut function.blocks)
        .find(|block| {
            block
                .instructions
                .iter()
                .any(|instruction| matches!(instruction.op, SsaOp::InsertField { .. }))
        })
        .unwrap();
    let insertion = block
        .instructions
        .iter()
        .position(|instruction| matches!(instruction.op, SsaOp::InsertField { .. }))
        .unwrap();
    let SsaOp::InsertField { aggregate, .. } = block.instructions[insertion].op.clone() else {
        unreachable!()
    };
    let span = block.instructions[insertion].span;
    block.instructions.insert(
        insertion - 1,
        SsaInstruction {
            result: fresh,
            ty: TypeId::BOOL,
            op: SsaOp::Drop {
                owner: SsaPlace {
                    base: SsaPlaceBase::Value(aggregate),
                    projections: Vec::new(),
                },
            },
            span,
            unwind: None,
            binding: None,
        },
    );
    assert!(failure(duplicate_source_consume).contains("more than once"));

    let mut missing_drop = raw(PROMOTED_FIELD);
    let drop = missing_drop
        .functions
        .iter_mut()
        .flat_map(|function| &mut function.blocks)
        .flat_map(|block| &mut block.instructions)
        .rev()
        .find(|instruction| matches!(instruction.op, SsaOp::Drop { .. }))
        .unwrap();
    drop.op = SsaOp::Use(SsaOperand::Bool(true));
    assert!(failure(missing_drop).contains("remains live"));

    let mut duplicate_drop = raw(PROMOTED_FIELD);
    let fresh = next_value(&duplicate_drop);
    let block = duplicate_drop
        .functions
        .iter_mut()
        .flat_map(|function| &mut function.blocks)
        .find(|block| {
            block
                .instructions
                .iter()
                .any(|instruction| matches!(instruction.op, SsaOp::InsertField { .. }))
        })
        .unwrap();
    let drop = block
        .instructions
        .iter()
        .rev()
        .find(|instruction| matches!(instruction.op, SsaOp::Drop { .. }))
        .unwrap()
        .clone();
    block.instructions.push(SsaInstruction {
        result: fresh,
        ..drop
    });
    assert!(failure(duplicate_drop).contains("more than once"));
}

#[test]
fn materialized_field_requires_real_descriptor_commit_provenance() {
    let mut forged = raw(MEMORY_FIELD);
    let store = forged
        .functions
        .iter_mut()
        .flat_map(|function| &mut function.blocks)
        .flat_map(|block| &mut block.instructions)
        .find(|instruction| {
            matches!(
                instruction.op,
                SsaOp::Store {
                    provenance: StoreProvenance::DescriptorCommit(_),
                    ..
                }
            )
        })
        .unwrap();
    let SsaOp::Store { provenance, .. } = &mut store.op else {
        unreachable!()
    };
    *provenance = StoreProvenance::DescriptorCommit(DescriptorCommitKind::ListReserve);
    assert!(failure(forged).contains("kind/producer mismatch"));

    let mut wrong_destination = raw(MEMORY_FIELD);
    let store = wrong_destination
        .functions
        .iter_mut()
        .flat_map(|function| &mut function.blocks)
        .flat_map(|block| &mut block.instructions)
        .find(|instruction| {
            matches!(
                instruction.op,
                SsaOp::Store {
                    provenance: StoreProvenance::DescriptorCommit(_),
                    ..
                }
            )
        })
        .unwrap();
    let SsaOp::Store { place, .. } = &mut store.op else {
        unreachable!()
    };
    let Some(aether_middle::SsaPlaceProjection::Field(field)) = place.projections.last_mut() else {
        unreachable!()
    };
    *field = FieldId(u32::MAX);
    assert!(failure(wrong_destination).contains("field"));

    let mut duplicate = raw(MEMORY_FIELD);
    let fresh = next_value(&duplicate);
    let block = duplicate
        .functions
        .iter_mut()
        .flat_map(|function| &mut function.blocks)
        .find(|block| {
            block.instructions.iter().any(|instruction| {
                matches!(
                    instruction.op,
                    SsaOp::Store {
                        provenance: StoreProvenance::DescriptorCommit(_),
                        ..
                    }
                )
            })
        })
        .unwrap();
    let store = block
        .instructions
        .iter()
        .find(|instruction| {
            matches!(
                instruction.op,
                SsaOp::Store {
                    provenance: StoreProvenance::DescriptorCommit(_),
                    ..
                }
            )
        })
        .unwrap()
        .clone();
    block.instructions.push(SsaInstruction {
        result: fresh,
        ..store
    });
    assert!(failure(duplicate).contains("use region is invalid"));
}

const NATIVE_QUALIFICATION: &str = r#"
struct Item { string name; }
struct Inner { List<Item> items; }
struct Result { Inner inner; List<string> words; string sibling; int state; }

void observe(ref Result result) { return; }

void mutate(ref mut Result result) {
    push((*result).inner.items, Item("reference"));
    reserve((*result).words, 24);
    push((*result).words, "through-ref");
    return;
}

Result build() {
    Result result = Result(Inner({}), {}, "sibling", 7);
    reserve(result.inner.items, 8);
    push(result.inner.items, Item("one"));
    push(result.inner.items, Item("two"));
    reserve(result.words, 8);
    push(result.words, "word");
    return result;
}

int early(bool before) {
    Result result = Result(Inner({}), {}, "early", 1);
    if (before) { return 0; }
    push(result.inner.items, Item("after"));
    return 0;
}

int main() {
    List<Item> root = {};
    push(root, Item("root-1"));
    push(root, Item("root-2"));
    reserve(root, 16);

    List<int> copy = {1};
    push(copy, 2);

    Result result = build();
    observe(&result);
    push(result.inner.items, Item("memory-field"));
    reserve(result.words, 16);
    mutate(&mut result);

    if (length(root) != 2) { return 1; }
    if (length(copy) != 2) { return 2; }
    if (length(result.inner.items) != 4) { return 3; }
    if (length(result.words) != 2) { return 4; }
    if (result.state != 7) { return 5; }
    if (early(true) != 0) { return 6; }
    if (early(false) != 0) { return 7; }
    return 0;
}
"#;

const EXCEPTION_QUALIFICATION: &str = r#"
open class Problem : Exception { public init() {} }
struct Item { string name; }
struct Result { List<Item> items; string sibling; }

void fail() { throw Problem(); }

int beforeCommit() {
    Result result = Result({}, "before");
    try {
        fail();
        push(result.items, Item("unreachable"));
    } catch (Problem error) {
        if (length(result.items) == 0) { return 0; }
    }
    return 1;
}

int afterCommit() {
    try {
        Result result = Result({}, "after");
        push(result.items, Item("committed"));
        fail();
    } catch (Problem error) {
        return 0;
    }
    return 1;
}

int main() {
    if (beforeCommit() != 0) { return 1; }
    if (afterCommit() != 0) { return 2; }
    return 0;
}
"#;

const EXPENSE_LOAD_FIXTURE: &str = include_str!(concat!(
    env!("CARGO_MANIFEST_DIR"),
    "/../../tests/programs/owning_collection_fields_expense_load.ae"
));

fn lifecycle_checked_llvm(llvm: &str) -> String {
    let checks = "  %ocf_heap_allocs = load i64, ptr @aether_heap_alloc_count\n  %ocf_heap_frees = load i64, ptr @aether_heap_free_count\n  %ocf_heap_ok = icmp eq i64 %ocf_heap_allocs, %ocf_heap_frees\n  %ocf_string_allocs = load i64, ptr @aether_string_alloc_count\n  %ocf_string_frees = load i64, ptr @aether_string_free_count\n  %ocf_string_ok = icmp eq i64 %ocf_string_allocs, %ocf_string_frees\n  %ocf_lifecycle_ok = and i1 %ocf_heap_ok, %ocf_string_ok\n  %ocf_result_ok = icmp eq i32 %process_status, 0\n  %ocf_ok = and i1 %ocf_lifecycle_ok, %ocf_result_ok\n  %ocf_status = select i1 %ocf_ok, i32 0, i32 99\n  ret i32 %ocf_status";
    let instrumented = llvm.replace("  ret i32 %process_status", checks);
    assert_ne!(instrumented, llvm);
    instrumented
}

#[test]
fn native_o0_o2_cover_growth_reserve_return_address_taken_ref_mut_and_unwind() {
    for (label, source) in [
        ("main", NATIVE_QUALIFICATION),
        ("exceptions", EXCEPTION_QUALIFICATION),
        ("expense-load", EXPENSE_LOAD_FIXTURE),
    ] {
        for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
            let compilation = compile_source_with_optimization(
                &SourceFile::new("owning_collection_fields_v1.ae", source),
                &[Emit::Hir, Emit::Mir, Emit::Ssa, Emit::Llvm],
                optimization,
            )
            .unwrap_or_else(|diagnostics| panic!("{source}\n{diagnostics:#?}"));
            assert!(compilation.dumps[&Emit::Hir].contains("ListPush"));
            assert!(compilation.dumps[&Emit::Mir].contains("ListPush"));
            assert!(compilation.dumps[&Emit::Ssa].contains("ListPush"));
            assert!(compilation.llvm.contains("@aether_list_push_"));
            assert!(!compilation.dumps[&Emit::Ssa].contains("Clone"));
            assert!(!compilation.llvm.contains("owning slot replacement"));
            let output = Output::new(&format!("{label}-{optimization:?}"));
            ClangToolchain::default()
                .with_optimization(optimization)
                .link_executable(&lifecycle_checked_llvm(&compilation.llvm), &output.0)
                .unwrap();
            let execution = Command::new(&output.0).output().unwrap();
            assert_eq!(
                execution.status.code(),
                Some(0),
                "{label} {optimization:?}: {}",
                String::from_utf8_lossy(&execution.stderr)
            );
        }
    }
}

#[test]
#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
fn representative_growth_is_clean_under_address_sanitizer() {
    let compilation = compile_source_with_optimization(
        &SourceFile::new("owning_collection_fields_asan.ae", NATIVE_QUALIFICATION),
        &[Emit::Llvm],
        OptimizationLevel::O0,
    )
    .unwrap();
    let output = Output::new("asan");
    let llvm = output.0.with_extension("ll");
    fs::write(&llvm, lifecycle_checked_llvm(&compilation.llvm)).unwrap();
    let linked = Command::new("clang")
        .args(["-O0", "-fsanitize=address"])
        .arg(&llvm)
        .arg("-o")
        .arg(&output.0)
        .status()
        .unwrap();
    assert!(linked.success());
    let execution = Command::new(&output.0)
        .env("ASAN_OPTIONS", "detect_leaks=0:halt_on_error=1")
        .output()
        .unwrap();
    let _ = fs::remove_file(llvm);
    assert_eq!(
        execution.status.code(),
        Some(0),
        "{}",
        String::from_utf8_lossy(&execution.stderr)
    );
}
