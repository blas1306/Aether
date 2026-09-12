//! GENERAL-V2 structural composition qualification for the string owner.

use std::{fmt::Write, fs, path::PathBuf, process::Command};

use aether_driver::{Emit, OptimizationLevel, compile_source_with_optimization};
use aether_frontend::{Capability, SourceFile, TypeData, TypeId, analyze, parse_source};
use aether_middle::{Operand, Rvalue, SsaOp, build_ssa, lower_hir, verify_mir, verify_ssa};

struct Directory(PathBuf);

impl Directory {
    fn new() -> Self {
        static NEXT: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
        let path = std::env::temp_dir().join(format!(
            "aether-general-v2-{}-{}",
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
        &SourceFile::new("general_v2.ae", text),
        &[Emit::Hir, Emit::Mir, Emit::Ssa],
        optimization,
    )
    .unwrap_or_else(|errors| panic!("{text}\n{errors:#?}"))
}

fn execute(llvm: &str, optimization: OptimizationLevel) -> std::process::Output {
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
        "{}\n{llvm}",
        String::from_utf8_lossy(&linked.stderr)
    );
    Command::new(executable).output().unwrap()
}

fn instrument(llvm: &str, result: i32, counts: [u64; 7], relocations: u64) -> String {
    let names = [
        "alloc",
        "free",
        "retain",
        "release",
        "concat",
        "equal",
        "literal_arc_noop",
    ];
    let mut guard = format!("  %v2_result_ok = icmp eq i32 %process_status, {result}\n");
    let mut last = "v2_result_ok".to_owned();
    for (index, (name, expected)) in names.iter().zip(counts).enumerate() {
        writeln!(
            guard,
            "  %v2_{index} = load i64, ptr @aether_string_{name}_count\n  %v2_ok_{index} = icmp eq i64 %v2_{index}, {expected}\n  %v2_all_{index} = and i1 %{last}, %v2_ok_{index}"
        )
        .unwrap();
        last = format!("v2_all_{index}");
    }
    writeln!(
        guard,
        "  %v2_relocations = load i64, ptr @aether_relocation_count\n  %v2_relocations_ok = icmp eq i64 %v2_relocations, {relocations}\n  %v2_all_relocations = and i1 %{last}, %v2_relocations_ok\n  %v2_status = select i1 %v2_all_relocations, i32 0, i32 99\n  ret i32 %v2_status"
    )
    .unwrap();
    llvm.replace("  ret i32 %process_status", &guard)
}

#[test]
fn structs_enums_arrays_and_lists_run_with_exact_recursive_lifecycle() {
    let source = include_str!("../../../tests/programs/general_v2_string_composition.ae");
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        let compilation = compile(source, optimization);
        let output = execute(
            &instrument(&compilation.llvm, 0, [2, 2, 8, 10, 2, 0, 5], 2),
            optimization,
        );
        assert_eq!(output.status.code(), Some(0), "{optimization:?}");
        assert!(compilation.dumps[&Emit::Hir].contains("Assign"));
        for phase in [Emit::Mir, Emit::Ssa] {
            let dump = &compilation.dumps[&phase];
            assert!(dump.contains("ArrayInit"));
            assert!(dump.contains("ListInit"));
            assert!(dump.contains("ReplaceString"));
            assert!(dump.contains("Relocate"));
            assert!(dump.contains("Drop"));
        }
        let replacement = compilation
            .llvm
            .find("string replacement: publish new owner")
            .unwrap();
        let replacement = &compilation.llvm[replacement..];
        assert!(
            replacement.find("store ptr").unwrap()
                < replacement.find("@aether_string_release").unwrap()
        );
    }
}

#[test]
fn empty_string_collections_select_runtime_without_text_operations() {
    let source = "int main(){Array<string> fixed={};List<string> dynamic={};return 0;}";
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        let compilation = compile(source, optimization);
        assert!(compilation.llvm.contains("@aether_string_release"));
        let output = execute(
            &instrument(&compilation.llvm, 0, [0, 0, 0, 0, 0, 0, 0], 0),
            optimization,
        );
        assert_eq!(output.status.code(), Some(0), "{optimization:?}");
    }
}

#[test]
fn structural_properties_moves_and_copy_constraints_are_enforced() {
    let hir = analyze(
        parse_source(&SourceFile::new(
            "properties.ae",
            "struct S{string value;}enum E{V(string),N}int main(){S s=S(\"x\");Array<string> a={\"y\"};List<string> l={\"z\"};return 0;}",
        ))
        .unwrap(),
    )
    .unwrap();
    let string_struct = hir
        .types()
        .entries()
        .find_map(|(ty, data)| matches!(data, TypeData::Struct(_)).then_some(ty))
        .unwrap();
    let properties = hir.types().properties(string_struct).unwrap();
    assert!(!properties.is_copy);
    assert!(properties.is_relocatable);
    assert!(properties.is_storable);
    assert!(properties.needs_drop);
    assert!(
        !hir.types()
            .guarantees_capability(string_struct, Capability::Copy)
    );

    for rejected in [
        "struct S{string value;}int main(){S a=S(\"x\");S b=a;S c=a;return 0;}",
        "struct S{string value;}int main(){S a=S(\"x\");string x=a.value;return 0;}",
        "T duplicate<T:Copy>(T value){T copy=value;return copy;}struct S{string value;}int main(){S x=duplicate<S>(S(\"x\"));return 0;}",
        "T duplicate<T:Copy>(T value){T copy=value;return copy;}int main(){string x=duplicate<string>(\"x\");return 0;}",
    ] {
        assert!(
            compile_source_with_optimization(
                &SourceFile::new("rejected.ae", rejected),
                &[],
                OptimizationLevel::O0,
            )
            .is_err(),
            "accepted: {rejected}"
        );
    }
}

#[test]
fn branch_early_return_and_root_replacement_drop_exactly_once() {
    let source = r#"
struct Owner{string value;}
int consume(Owner value){return 7;}
int choose(bool take){
    Owner value=Owner("a"+"b");
    if(take){return consume(value);}
    return 9;
}
int main(){
    Owner old=Owner("c"+"d");
    Owner replacement=Owner("e"+"f");
    old=replacement;
    return choose(true)+choose(false)-16;
}
"#;
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        let compilation = compile(source, optimization);
        let output = execute(
            &instrument(&compilation.llvm, 0, [4, 4, 0, 4, 4, 0, 8], 0),
            optimization,
        );
        assert_eq!(output.status.code(), Some(0), "{optimization:?}");
    }
}

#[test]
fn aggregate_strings_are_cleaned_once_during_exception_unwind() {
    let source = r#"
open class Problem:Exception{public init(){}}
struct Owner{string first;string second;}
int fail(){throw Problem();}
int main(){
    try{Owner value=Owner("a"+"b","c"+"d");fail();}
    catch(Problem error){return 23;}
    return 24;
}
"#;
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        let compilation = compile(source, optimization);
        let output = execute(
            &instrument(&compilation.llvm, 23, [2, 2, 0, 2, 2, 0, 4], 0),
            optimization,
        );
        assert_eq!(output.status.code(), Some(0), "{optimization:?}");
        assert!(compilation.dumps[&Emit::Mir].contains("unwind"));
        assert!(compilation.llvm.contains("@aether_drop_s0"));
    }
}

#[test]
fn malformed_hir_mir_and_ssa_composed_lifecycle_are_rejected() {
    let source = SourceFile::new(
        "corrupt.ae",
        "struct S{string value;}int main(){S s=S(\"a\"+\"b\");string x=\"c\"+\"d\";s.value=x;return 0;}",
    );
    let hir = analyze(parse_source(&source).unwrap()).unwrap();
    let mir = lower_hir(hir);
    verify_mir(mir.clone()).unwrap();
    let mut bad_mir = mir.clone();
    let replacement = bad_mir
        .functions
        .iter_mut()
        .flat_map(|function| &mut function.blocks)
        .flat_map(|block| &mut block.instructions)
        .find(|instruction| matches!(instruction.value, Rvalue::ReplaceString { .. }))
        .unwrap();
    let Rvalue::ReplaceString { value, .. } = &mut replacement.value else {
        unreachable!()
    };
    *value = Operand::Bool(true);
    assert!(verify_mir(bad_mir).is_err());

    let verified = verify_mir(mir).unwrap();
    let ssa = build_ssa(&verified);
    verify_ssa(ssa.clone()).unwrap();
    let mut bad_replacement = ssa.clone();
    let replacement = bad_replacement
        .functions
        .iter_mut()
        .flat_map(|function| &mut function.blocks)
        .flat_map(|block| &mut block.instructions)
        .find(|instruction| matches!(instruction.op, SsaOp::ReplaceString { .. }))
        .unwrap();
    replacement.ty = TypeId::STRING;
    assert!(verify_ssa(bad_replacement).is_err());

    let mut missing_recursive_drop = ssa;
    for block in &mut missing_recursive_drop.functions[0].blocks {
        block
            .instructions
            .retain(|instruction| !matches!(instruction.op, SsaOp::Drop { .. }));
    }
    assert!(verify_ssa(missing_recursive_drop).is_err());
}
