//! EXCEPTION-V2 constructor-unwind qualification for Linux x86-64.

use std::{fmt::Write as _, fs, path::PathBuf, process::Command};

use aether_driver::{Emit, OptimizationLevel, compile_source_with_optimization};
use aether_frontend::{ClassOp, SourceFile, analyze, parse_source};
use aether_middle::{Rvalue, SsaOp, build_ssa, lower_hir, verify_mir, verify_ssa};

struct Directory(PathBuf);

impl Directory {
    fn new() -> Self {
        static NEXT: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
        let path = std::env::temp_dir().join(format!(
            "aether-exception-v2-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, std::sync::atomic::Ordering::Relaxed)
        ));
        fs::create_dir(&path).unwrap();
        Self(path)
    }
}

impl Drop for Directory {
    fn drop(&mut self) {
        fs::remove_dir_all(&self.0).unwrap();
    }
}

fn compile(text: &str, optimization: OptimizationLevel) -> aether_driver::Compilation {
    compile_source_with_optimization(
        &SourceFile::new("exception_v2.ae", text),
        &[Emit::Hir, Emit::Mir, Emit::Ssa],
        optimization,
    )
    .unwrap_or_else(|errors| panic!("{text}\n{errors:#?}"))
}

fn instrument(llvm: &str, result: i64, counts: [u64; 7]) -> String {
    let names = [
        "object_alloc",
        "object_retain",
        "object_release",
        "object_destroy",
        "object_buffer_drop",
        "heap_alloc",
        "heap_free",
    ];
    let mut guard = format!("  %v2_result_ok = icmp eq i32 %process_status, {result}\n");
    let mut last = "v2_result_ok".to_owned();
    for (index, (name, expected)) in names.iter().zip(counts).enumerate() {
        writeln!(guard,"  %v2_{index} = load i64, ptr @aether_{name}_count\n  %v2_ok_{index} = icmp eq i64 %v2_{index}, {expected}\n  %v2_all_{index} = and i1 %{last}, %v2_ok_{index}").unwrap();
        last = format!("v2_all_{index}");
    }
    writeln!(
        guard,
        "  %v2_status = select i1 %{last}, i32 0, i32 99\n  ret i32 %v2_status"
    )
    .unwrap();
    llvm.replace("  ret i32 %process_status", &guard)
}

fn execute(llvm: &str, optimization: OptimizationLevel) {
    let directory = Directory::new();
    let ir = directory.0.join("program.ll");
    let executable = directory.0.join("program");
    fs::write(&ir, llvm).unwrap();
    let option = match optimization {
        OptimizationLevel::O0 => "-O0",
        OptimizationLevel::O2 => "-O2",
    };
    let linked = Command::new("clang")
        .args(["-Wno-override-module", option, "-x", "ir"])
        .arg(&ir)
        .arg("-o")
        .arg(&executable)
        .arg("-lstdc++")
        .output()
        .unwrap();
    assert!(
        linked.status.success(),
        "{}",
        String::from_utf8_lossy(&linked.stderr)
    );
    assert_eq!(Command::new(executable).status().unwrap().code(), Some(0));
}

const PREFIX: &str = "open class Problem:Exception{public init(){}}int fail(){throw Problem();}";

fn qualify(text: &str, result: i64, counts: [u64; 7]) {
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        let compilation = compile(text, optimization);
        execute(&instrument(&compilation.llvm, result, counts), optimization);
    }
}

#[test]
fn smoke_program_qualifies_at_o0_and_o2() {
    qualify(
        include_str!("../../../tests/programs/exception_v2_smoke.ae"),
        0,
        [2, 1, 2, 1, 2, 4, 4],
    );
}

fn diagnostic_codes(text: &str) -> Vec<&'static str> {
    compile_source_with_optimization(
        &SourceFile::new("exception_v2_negative.ae", text),
        &[],
        OptimizationLevel::O0,
    )
    .unwrap_err()
    .into_iter()
    .map(|diagnostic| diagnostic.code)
    .collect()
}

#[test]
fn throw_before_fields_and_during_constructor_arguments() {
    let before = format!(
        "{PREFIX} class Pending{{Buffer<int> value;public init(){{fail();this.value=Buffer<int>(2,1);}}}}int main(){{try{{Pending p=Pending();}}catch(Problem e){{return 11;}}return 12;}}"
    );
    qualify(&before, 11, [2, 1, 2, 1, 0, 2, 2]);

    let arguments = format!(
        "{PREFIX} usize failArg(){{throw Problem();}}class Target{{Buffer<int> value;public init(usize n){{this.value=Buffer<int>(n,1);}}}}int main(){{try{{Target t=Target(failArg());}}catch(Problem e){{return 13;}}return 14;}}"
    );
    qualify(&arguments, 13, [1, 1, 2, 1, 0, 1, 1]);

    let owning_argument = format!(
        "{PREFIX} usize failArg(){{throw Problem();}}class Child{{public init(){{}}}}class Target{{Child child;public init(Child child,usize n){{this.child=child;fail();}}}}int main(){{try{{Target t=Target(Child(),failArg());}}catch(Problem e){{return 14;}}return 99;}}"
    );
    qualify(&owning_argument, 14, [2, 1, 3, 2, 0, 2, 2]);

    let direct_throw = format!(
        "{PREFIX} class Direct{{Buffer<int> value;public init(){{this.value=Buffer<int>(1,1);throw Problem();}}}}int main(){{try{{Direct value=Direct();}}catch(Problem e){{return 15;}}return 16;}}"
    );
    qualify(&direct_throw, 15, [2, 1, 2, 1, 1, 3, 3]);
}

#[test]
fn buffer_and_class_fields_roll_back_exactly_once() {
    let text = format!(
        "{PREFIX} class Child{{public init(){{}}}}class Owner{{Buffer<int> first;Child child;Buffer<int> pending;public init(){{this.first=Buffer<int>(2,1);this.child=Child();fail();this.pending=Buffer<int>(3,2);}}}}int main(){{try{{Owner owner=Owner();}}catch(Problem e){{return 21;}}return 22;}}"
    );
    let compilation = compile(&text, OptimizationLevel::O0);
    assert!(compilation.dumps[&Emit::Hir].contains("ConstructorUnwindPlan"));
    assert!(compilation.dumps[&Emit::Mir].contains("ConstructionCleanup"));
    assert!(compilation.dumps[&Emit::Ssa].contains("free_allocation: true"));
    qualify(&text, 21, [3, 1, 3, 2, 2, 4, 4]);
}

#[test]
fn direct_method_propagation_rolls_back_constructor_state() {
    let text = format!(
        "{PREFIX} class Worker{{public init(){{}}public int explode(){{throw Problem();}}}}class Owner{{Buffer<int> value;public init(){{this.value=Buffer<int>(1,1);Worker worker=Worker();worker.explode();}}}}int main(){{try{{Owner owner=Owner();}}catch(Problem e){{return 25;}}return 26;}}"
    );
    qualify(&text, 25, [3, 2, 4, 2, 1, 4, 4]);
}

#[test]
fn three_level_base_and_derived_cleanup_use_reverse_canonical_order() {
    let text = format!(
        "{PREFIX} open class Root{{Buffer<int> root;public init(){{this.root=Buffer<int>(1,1);}}}}open class Mid:Root{{Buffer<int> middle;public init():base(){{this.middle=Buffer<int>(1,2);}}}}class Leaf:Mid{{Buffer<int> leaf;public init():base(){{this.leaf=Buffer<int>(1,3);fail();}}}}int main(){{try{{Leaf value=Leaf();}}catch(Problem e){{return 31;}}return 32;}}"
    );
    let compilation = compile(&text, OptimizationLevel::O0);
    let mir = &compilation.dumps[&Emit::Mir];
    let cleanup = mir.find("fields: [\n                                    FieldId(\n                                        2,").expect("derived field begins rollback");
    let middle = mir[cleanup..]
        .find("FieldId(\n                                        1,")
        .expect("middle field follows derived");
    let root = mir[cleanup..]
        .find("FieldId(\n                                        0,")
        .expect("root field follows middle");
    assert!(middle < root);
    qualify(&text, 31, [2, 1, 2, 1, 3, 5, 5]);
}

#[test]
fn base_init_failure_and_post_base_failure_keep_distinct_prefixes() {
    let during_base = format!(
        "{PREFIX} open class Root{{Buffer<int> root;public init(){{this.root=Buffer<int>(1,1);fail();}}}}class Derived:Root{{Buffer<int> pending;public init():base(){{this.pending=Buffer<int>(1,2);}}}}int main(){{try{{Derived value=Derived();}}catch(Problem e){{return 41;}}return 42;}}"
    );
    qualify(&during_base, 41, [2, 1, 2, 1, 1, 3, 3]);

    let after_base = format!(
        "{PREFIX} open class Root{{Buffer<int> root;public init(){{this.root=Buffer<int>(1,1);}}}}class Derived:Root{{Buffer<int> pending;public init():base(){{fail();this.pending=Buffer<int>(1,2);}}}}int main(){{try{{Derived value=Derived();}}catch(Problem e){{return 43;}}return 44;}}"
    );
    qualify(&after_base, 43, [2, 1, 2, 1, 1, 3, 3]);
}

#[test]
fn malformed_hir_mir_and_ssa_constructor_cleanup_is_rejected() {
    let text = format!(
        "{PREFIX} class Owner{{Buffer<int> value;public init(){{this.value=Buffer<int>(1,1);fail();}}}}int main(){{try{{Owner owner=Owner();}}catch(Problem e){{return 0;}}}}"
    );
    let hir = analyze(parse_source(&SourceFile::new("corrupt_v2.ae", &text)).unwrap()).unwrap();
    let mir = lower_hir(hir);
    let mut bad_mir = mir.clone();
    let cleanup = bad_mir
        .functions
        .iter_mut()
        .flat_map(|function| &mut function.blocks)
        .flat_map(|block| &mut block.instructions)
        .find_map(|instruction| match &mut instruction.value {
            Rvalue::Class(op)
                if matches!(op.as_ref(), ClassOp::ConstructionCleanup { free_allocation: false, fields, .. } if !fields.is_empty()) => Some(op),
            _ => None,
        })
        .unwrap();
    let ClassOp::ConstructionCleanup { fields, .. } = cleanup.as_mut() else {
        unreachable!()
    };
    fields.clear();
    assert!(verify_mir(bad_mir).is_err());

    let ssa = build_ssa(&verify_mir(mir).unwrap());
    let mut bad_ssa = ssa.clone();
    let cleanup = bad_ssa
        .functions
        .iter_mut()
        .flat_map(|function| &mut function.blocks)
        .flat_map(|block| &mut block.instructions)
        .find_map(|instruction| match &mut instruction.op {
            SsaOp::Class(op)
                if matches!(op.as_ref(), ClassOp::ConstructionCleanup { free_allocation: false, fields, .. } if !fields.is_empty()) => Some(op),
            _ => None,
        })
        .unwrap();
    let ClassOp::ConstructionCleanup { fields, .. } = cleanup.as_mut() else {
        unreachable!()
    };
    fields.clear();
    assert!(verify_ssa(bad_ssa).is_err());
}

#[test]
fn deferred_exception_surface_remains_rejected() {
    let try_in_init = format!(
        "{PREFIX} class Owner{{public init(){{try{{fail();}}catch(Problem e){{}}}}}}int main(){{return 0;}}"
    );
    assert!(diagnostic_codes(&try_in_init).contains(&"E0436"));

    let virtual_invoke = format!(
        "{PREFIX} open class Worker{{public init(){{}}public open int run(){{return 0;}}}}class Owner{{public init(){{Worker worker=Worker();worker.run();}}}}int main(){{return 0;}}"
    );
    assert!(diagnostic_codes(&virtual_invoke).contains(&"E0437"));
}
