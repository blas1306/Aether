//! EXCEPTION-V4 finally qualification for Linux x86-64.

use std::{fs, path::PathBuf, process::Command};

use aether_driver::{Emit, OptimizationLevel, compile_source_with_optimization};
use aether_frontend::{SourceFile, analyze, parse_source};
use aether_middle::{Rvalue, SsaTerminator, build_ssa, lower_hir, verify_mir, verify_ssa};

struct Directory(PathBuf);

impl Directory {
    fn new() -> Self {
        static NEXT: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
        let path = std::env::temp_dir().join(format!(
            "aether-exception-v4-{}-{}",
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
        &SourceFile::new("exception_v4.ae", text),
        &[Emit::Hir, Emit::Mir, Emit::Ssa],
        optimization,
    )
    .unwrap_or_else(|errors| panic!("{text}\n{errors:#?}"))
}

fn run(text: &str, optimization: OptimizationLevel) -> i32 {
    let compilation = compile(text, optimization);
    let directory = Directory::new();
    let ir = directory.0.join("program.ll");
    let executable = directory.0.join("program");
    fs::write(&ir, &compilation.llvm).unwrap();
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
        "{}\n{}",
        String::from_utf8_lossy(&linked.stderr),
        compilation.llvm
    );
    Command::new(executable).status().unwrap().code().unwrap()
}

fn run_status(llvm: &str, optimization: OptimizationLevel) -> std::process::ExitStatus {
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
    assert!(linked.status.success());
    Command::new(executable).status().unwrap()
}

fn probe_counts(llvm: &str, optimization: OptimizationLevel) -> [i32; 7] {
    let names = [
        "object_alloc",
        "object_retain",
        "object_release",
        "object_destroy",
        "object_buffer_drop",
        "heap_alloc",
        "heap_free",
    ];
    names.map(|name| {
        let probed = llvm.replace(
            "  ret i32 %process_status",
            &format!("  %probe = load i64, ptr @aether_{name}_count\n  %probe32 = trunc i64 %probe to i32\n  ret i32 %probe32"),
        );
        run_status(&probed, optimization).code().unwrap()
    })
}

const PREFIX: &str = "open class Problem:Exception{public init(){}}";

fn qualify(text: &str, expected: i32) {
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        assert_eq!(run(text, optimization), expected);
    }
}

#[test]
fn repository_smoke_program_runs_at_o0_and_o2() {
    qualify(
        include_str!("../../../tests/programs/exception_v4_smoke.ae"),
        0,
    );
}

#[test]
fn normal_handled_unmatched_and_return_paths_execute_finally_once() {
    qualify("int main(){int x=1;try{x=x+2;}finally{x=x*3;}return x;}", 9);
    qualify(
        &format!(
            "{PREFIX} int main(){{int x=1;try{{throw Problem();}}catch(Problem e){{x=4;}}finally{{x=x+3;}}return x;}}"
        ),
        7,
    );
    qualify(
        &format!(
            "{PREFIX} int main(){{int x=1;try{{try{{throw Problem();}}finally{{x=x+2;}}}}catch(Problem e){{return x+4;}}}}"
        ),
        7,
    );
    qualify("int main(){try{return 8;}finally{int x=1;}}", 8);
    qualify(
        &format!(
            "{PREFIX} int main(){{try{{throw Problem();}}catch(Problem e){{return 12;}}finally{{int x=1;}}}}"
        ),
        12,
    );
}

#[test]
fn loop_transfers_and_nested_finally_preserve_pending_control() {
    qualify(
        "int main(){int x=0;while(x<4){try{x=x+1;if(x<3){continue;}if(x==3){break;}}finally{x=x+1;}}return x;}",
        4,
    );
    qualify(
        "int main(){int x=1;try{try{return 9;}finally{x=x+1;}}finally{x=x+1;}}",
        9,
    );
}

#[test]
fn finally_is_kept_non_throwing_and_without_outgoing_control() {
    for (text, fragment) in [
        ("int main(){try{return 1;}finally{return 2;}}", "E0438"),
        (
            "int main(){while(true){try{break;}finally{continue;}}return 0;}",
            "E0438",
        ),
        (
            "int f(){return 1;}int main(){try{return 0;}finally{f();}}",
            "E0438",
        ),
        (
            &format!("{PREFIX} int main(){{try{{return 0;}}finally{{throw Problem();}}}}"),
            "E0438",
        ),
        (
            &format!(
                "{PREFIX} int main(){{try{{throw Problem();}}catch(Problem e){{}}finally{{throw;}}return 0;}}"
            ),
            "E0438",
        ),
    ] {
        let errors = compile_source_with_optimization(
            &SourceFile::new("bad_v4.ae", text),
            &[],
            OptimizationLevel::O0,
        )
        .unwrap_err();
        assert!(errors.iter().any(|error| error.code == fragment));
    }
}

#[test]
fn owners_are_cleaned_once_and_exception_payload_is_not_repacked() {
    let text = format!(
        "{PREFIX} int fail(){{throw Problem();}}class Holder{{Buffer<int> value;public init(){{this.value=Buffer<int>(2,7);}}}}int main(){{try{{try{{Holder h=Holder();Buffer<int> b=Buffer<int>(3,8);fail();}}finally{{int marker=1;}}}}catch(Problem e){{return 23;}}return 24;}}"
    );
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        let compilation = compile(&text, optimization);
        assert_eq!(run_status(&compilation.llvm, optimization).code(), Some(23));
        assert_eq!(
            probe_counts(&compilation.llvm, optimization),
            [2, 1, 3, 2, 1, 4, 4]
        );
        let mir = &compilation.dumps[&Emit::Mir];
        assert!(mir.contains("EnterFinally"));
        assert!(mir.contains("ForwardUnwind"));
        assert!(compilation.llvm.contains("resume { ptr, i32 }"));
    }
}

#[test]
fn traps_remain_fail_fast_without_a_finally_guarantee() {
    let text = "int main(){int zero=0;try{return 1/zero;}finally{int marker=1;}}";
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        let compilation = compile(text, optimization);
        assert!(compilation.dumps[&Emit::Mir].contains("DivisionByZero"));
        assert!(!run_status(&compilation.llvm, optimization).success());
    }
}

#[test]
fn malformed_mir_and_ssa_finally_regions_are_rejected() {
    let source = "int main(){int x=0;try{if(x==0){return 1;}x=2;}finally{x=x+1;}return x;}";
    let hir = analyze(parse_source(&SourceFile::new("corrupt_v4.ae", source)).unwrap()).unwrap();
    let mir = lower_hir(hir);
    let mut omitted = mir.clone();
    let instruction = omitted
        .functions
        .iter_mut()
        .flat_map(|function| &mut function.blocks)
        .flat_map(|block| &mut block.instructions)
        .find(|instruction| matches!(instruction.value, Rvalue::ExitFinally { .. }))
        .unwrap();
    instruction.value = Rvalue::Use(aether_middle::Operand::Bool(true));
    assert!(verify_mir(omitted).is_err());

    let mut ssa = build_ssa(&verify_mir(mir).unwrap());
    let function = ssa
        .functions
        .iter_mut()
        .find(|function| !function.finally_regions.is_empty())
        .unwrap();
    let dispatch = function.finally_regions[0].dispatch;
    let SsaTerminator::Switch { cases, .. } = &mut function.blocks[dispatch.0 as usize].terminator
    else {
        panic!("expected finally dispatch");
    };
    assert!(cases.len() > 1);
    cases.swap(0, 1);
    assert!(verify_ssa(ssa).is_err());
}
