//! GENERAL-V1 immutable UTF-8 string qualification.

use std::{fmt::Write, fs, path::PathBuf, process::Command};

use aether_driver::{Emit, OptimizationLevel, compile_source_with_optimization};
use aether_frontend::{SourceFile, StringOp, TypeData, TypeId, analyze, parse_source};
use aether_middle::{Rvalue, SsaOp, build_ssa, lower_hir, verify_mir, verify_ssa};

struct Directory(PathBuf);

impl Directory {
    fn new() -> Self {
        static NEXT: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
        let path = std::env::temp_dir().join(format!(
            "aether-general-v1-{}-{}",
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
        &SourceFile::new("general_v1.ae", text),
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

fn instrument(llvm: &str, result: i32, counts: [u64; 7]) -> String {
    let names = [
        "alloc",
        "free",
        "retain",
        "release",
        "concat",
        "equal",
        "literal_arc_noop",
    ];
    let mut guard = format!("  %string_result_ok = icmp eq i32 %process_status, {result}\n");
    let mut last = "string_result_ok".to_owned();
    for (index, (name, expected)) in names.iter().zip(counts).enumerate() {
        writeln!(
            guard,
            "  %string_{index} = load i64, ptr @aether_string_{name}_count\n  %string_ok_{index} = icmp eq i64 %string_{index}, {expected}\n  %string_all_{index} = and i1 %{last}, %string_ok_{index}"
        )
        .unwrap();
        last = format!("string_all_{index}");
    }
    writeln!(
        guard,
        "  %string_status = select i1 %{last}, i32 0, i32 99\n  ret i32 %string_status"
    )
    .unwrap();
    llvm.replace("  ret i32 %process_status", &guard)
}

#[test]
fn literals_utf8_nul_output_and_value_boundaries_run_at_o0_o2() {
    let source = include_str!("../../../tests/programs/general_v1_string_smoke.ae");
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        let compilation = compile(source, optimization);
        let output = execute(&compilation.llvm, optimization);
        assert_eq!(output.status.code(), Some(0));
        assert_eq!(output.stdout, b"A\0Bh\xc3\xa9\n");
        for phase in [Emit::Hir, Emit::Mir, Emit::Ssa] {
            let dump = &compilation.dumps[&phase];
            for operation in ["Literal", "Alias", "Concat", "Equal", "ByteLength"] {
                assert!(dump.contains(operation), "{phase:?} lacks {operation}");
            }
        }
        assert!(compilation.llvm.contains("@aether_string_write"));
        assert!(!compilation.llvm.contains("strlen"));
        assert!(!compilation.llvm.contains("@printf"));
    }
}

#[test]
fn arc_transfer_alias_empty_fast_paths_and_final_free_are_exact() {
    let cases = [
        (
            "literal_assignment",
            "int main(){string value=\"x\";return int(byteLength(value));}",
            1,
            [0, 0, 0, 0, 0, 0, 1],
        ),
        (
            "literal_parameter",
            "int use(string value){return int(byteLength(value));}int main(){return use(\"x\");}",
            1,
            [0, 0, 0, 0, 0, 0, 1],
        ),
        (
            "literal_return",
            "string make(){return \"x\";}int main(){string value=make();return int(byteLength(value));}",
            1,
            [0, 0, 0, 0, 0, 0, 1],
        ),
        (
            "fresh_concat",
            "int main(){string value=\"a\"+\"b\";return int(byteLength(value));}",
            2,
            [1, 1, 0, 1, 1, 0, 2],
        ),
        (
            "fresh_return_operands",
            "string atom(){return \"x\";}int main(){string value=atom()+atom();return int(byteLength(value));}",
            2,
            [1, 1, 0, 1, 1, 0, 2],
        ),
        (
            "heap_alias",
            "int main(){string value=\"a\"+\"b\";string copy=value;return int(byteLength(copy));}",
            2,
            [1, 1, 1, 2, 1, 0, 2],
        ),
        (
            "heap_self_assignment",
            "int main(){string value=\"a\"+\"b\";value=value;return int(byteLength(value));}",
            2,
            [1, 1, 0, 1, 1, 0, 2],
        ),
        (
            "fresh_parameter",
            "int use(string value){return int(byteLength(value));}int main(){return use(\"a\"+\"b\");}",
            2,
            [1, 1, 0, 1, 1, 0, 2],
        ),
        (
            "lvalue_parameter_and_return",
            "string same(string value){return value;}int main(){string a=\"a\"+\"b\";string b=same(a);return int(byteLength(b));}",
            2,
            [1, 1, 2, 3, 1, 0, 2],
        ),
        (
            "early_return",
            "int choose(bool yes){string value=\"a\"+\"b\";if(yes){return int(byteLength(value));}return 9;}int main(){return choose(true);}",
            2,
            [1, 1, 0, 1, 1, 0, 2],
        ),
        (
            "branch_cleanup",
            "int choose(bool yes){string value=\"a\"+\"b\";if(yes){return 9;}return int(byteLength(value));}int main(){return choose(false);}",
            2,
            [1, 1, 0, 1, 1, 0, 2],
        ),
        (
            "empty_left",
            "int main(){string value=\"\"+\"x\";return int(byteLength(value));}",
            1,
            [0, 0, 0, 0, 1, 0, 4],
        ),
        (
            "empty_right",
            "int main(){string value=\"x\"+\"\";return int(byteLength(value));}",
            1,
            [0, 0, 0, 0, 1, 0, 4],
        ),
        (
            "literal_equality",
            "int main(){if(\"x\"==\"x\"){return 1;}return 0;}",
            1,
            [0, 0, 0, 0, 0, 1, 2],
        ),
        (
            "heap_inequality",
            "int main(){string value=\"a\"+\"b\";if(value!=\"ac\"){return 1;}return 0;}",
            1,
            [1, 1, 0, 1, 1, 1, 3],
        ),
    ];
    for (name, source, result, counts) in cases {
        for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
            let compilation = compile(source, optimization);
            let output = execute(&instrument(&compilation.llvm, result, counts), optimization);
            assert_eq!(output.status.code(), Some(0), "{name} {optimization:?}");
        }
    }
}

#[test]
fn initialized_string_is_dropped_once_during_exception_unwind() {
    let source = r#"
open class Problem:Exception{public init(){}}
int fail(){throw Problem();}
int main(){
    try{string value="a"+"b";fail();}
    catch(Problem error){return 23;}
    return 24;
}
"#;
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        let compilation = compile(source, optimization);
        let output = execute(
            &instrument(&compilation.llvm, 23, [1, 1, 0, 1, 1, 0, 2]),
            optimization,
        );
        assert_eq!(output.status.code(), Some(0));
        assert!(compilation.dumps[&Emit::Mir].contains("unwind"));
    }
}

#[test]
fn concat_size_overflow_and_oom_are_fail_fast_traps() {
    let compilation = compile(
        "int main(){string value=\"a\"+\"b\";return int(byteLength(value));}",
        OptimizationLevel::O0,
    );
    assert!(compilation.llvm.contains("AllocationSizeOverflow"));
    assert!(compilation.llvm.contains("AllocationFailure"));

    let overflow = compilation.llvm.replacen(
        "@aether_string_literal_61 = private constant { i64, i64, i64, [2 x i8] } { i64 1,",
        "@aether_string_literal_61 = private constant { i64, i64, i64, [2 x i8] } { i64 -1,",
        1,
    );
    assert_ne!(overflow, compilation.llvm);
    assert!(!execute(&overflow, OptimizationLevel::O0).status.success());

    let oom = compilation.llvm.replacen(
        "declare ptr @malloc(i64)",
        "define ptr @malloc(i64 %ignored) { ret ptr null }",
        1,
    );
    assert_ne!(oom, compilation.llvm);
    assert!(!execute(&oom, OptimizationLevel::O0).status.success());
}

#[test]
fn canonical_properties_private_runtime_and_non_string_elision() {
    let hir = analyze(
        parse_source(&SourceFile::new(
            "type.ae",
            "int main(){string s=\"x\";return 0;}",
        ))
        .unwrap(),
    )
    .unwrap();
    assert_eq!(hir.types().get(TypeId::STRING), Some(&TypeData::String));
    let properties = hir.types().properties(TypeId::STRING).unwrap();
    assert!(properties.is_known);
    assert!(!properties.is_copy);
    assert!(properties.is_relocatable);
    assert!(properties.is_storable);
    assert!(properties.needs_drop);

    let with_string = compile(
        "int main(){string s=\"x\";return 0;}",
        OptimizationLevel::O0,
    );
    assert!(
        with_string
            .llvm
            .contains("private constant { i64, i64, i64")
    );
    assert!(with_string.llvm.contains("i64 1"));
    assert!(!with_string.llvm.contains("atomic"));
    let plain = compile("int main(){return 0;}", OptimizationLevel::O0);
    assert!(!plain.llvm.contains("aether_string_"));
}

#[test]
fn out_of_scope_text_surfaces_are_rejected() {
    let cases = [
        "class C{string value;public init(string x){value=x;}}int main(){}",
        "int main(){Buffer<string> x=Buffer<string>(1,\"a\");}",
        "int main(){Matrix<string> x={{\"a\"}};}",
        "int main(){Vector<string,Row> x={\"a\"};}",
        "int main(){string s=\"a\";ref string r=&s;}",
        "int main(){print(1);}",
        "int main(){println(true);}",
    ];
    for source in cases {
        assert!(
            compile_source_with_optimization(
                &SourceFile::new("negative.ae", source),
                &[],
                OptimizationLevel::O0,
            )
            .is_err(),
            "accepted: {source}"
        );
    }
}

#[test]
fn malformed_mir_and_ssa_string_metadata_and_ownership_are_rejected() {
    let source = SourceFile::new(
        "corrupt.ae",
        "int main(){string a=\"a\"+\"b\";string b=a;return int(byteLength(b));}",
    );
    let hir = analyze(parse_source(&source).unwrap()).unwrap();
    let mir = lower_hir(hir);
    verify_mir(mir.clone()).unwrap();

    let mut wrong_mir_type = mir.clone();
    let instruction = wrong_mir_type
        .functions
        .iter_mut()
        .flat_map(|function| &mut function.blocks)
        .flat_map(|block| &mut block.instructions)
        .find(|instruction| matches!(&instruction.value, Rvalue::String(op) if matches!(op.as_ref(), StringOp::Concat { .. })))
        .unwrap();
    let Rvalue::String(op) = &instruction.value else {
        unreachable!()
    };
    let StringOp::Concat { left, .. } = op.as_ref() else {
        unreachable!()
    };
    instruction.value = Rvalue::String(Box::new(StringOp::ByteLength {
        source: left.clone(),
    }));
    assert!(verify_mir(wrong_mir_type).is_err());

    let mut invalid_utf8 = mir.clone();
    let instruction = invalid_utf8
        .functions
        .iter_mut()
        .flat_map(|function| &mut function.blocks)
        .flat_map(|block| &mut block.instructions)
        .find(|instruction| matches!(&instruction.value, Rvalue::String(op) if matches!(op.as_ref(), StringOp::Literal { .. })))
        .unwrap();
    instruction.value = Rvalue::String(Box::new(StringOp::Literal { bytes: vec![0xff] }));
    assert!(verify_mir(invalid_utf8).is_err());

    let verified = verify_mir(mir).unwrap();
    let ssa = build_ssa(&verified);
    verify_ssa(ssa.clone()).unwrap();
    let mut wrong_ssa_type = ssa.clone();
    let instruction = wrong_ssa_type
        .functions
        .iter_mut()
        .flat_map(|function| &mut function.blocks)
        .flat_map(|block| &mut block.instructions)
        .find(|instruction| matches!(&instruction.op, SsaOp::String(op) if matches!(op.as_ref(), StringOp::Concat { .. })))
        .unwrap();
    instruction.ty = TypeId::BOOL;
    assert!(verify_ssa(wrong_ssa_type).is_err());

    let mut duplicate_drop = ssa.clone();
    let instructions =
        &mut duplicate_drop.functions[duplicate_drop.entry.0 as usize].blocks[0].instructions;
    let index = instructions
        .iter()
        .rposition(|instruction| matches!(instruction.op, SsaOp::Drop { .. }))
        .unwrap();
    let duplicate = instructions[index].clone();
    instructions.insert(index + 1, duplicate);
    assert!(verify_ssa(duplicate_drop).is_err());

    let mut missing_drop = ssa;
    let instructions =
        &mut missing_drop.functions[missing_drop.entry.0 as usize].blocks[0].instructions;
    let index = instructions
        .iter()
        .rposition(|instruction| matches!(instruction.op, SsaOp::Drop { .. }))
        .unwrap();
    instructions.remove(index);
    assert!(verify_ssa(missing_drop).is_err());
}
