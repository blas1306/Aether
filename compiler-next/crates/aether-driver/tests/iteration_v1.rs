//! ITERATION-V1 native int range qualification.

use std::{fs, path::PathBuf, process::Command};

use aether_driver::{Emit, OptimizationLevel, compile_source_with_optimization};
use aether_frontend::{SourceFile, analyze, parse_source};
use aether_middle::{BinaryOp, Rvalue, SsaOp, build_ssa, lower_hir, verify_mir, verify_ssa};

struct Directory(PathBuf);

impl Directory {
    fn new() -> Self {
        static NEXT: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
        let path = std::env::temp_dir().join(format!(
            "aether-iteration-v1-{}-{}",
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
        &SourceFile::new("iteration_v1.ae", text),
        &[Emit::Hir, Emit::Mir, Emit::Ssa],
        optimization,
    )
    .unwrap_or_else(|errors| panic!("{text}\n{errors:#?}"))
}

fn run(text: &str, optimization: OptimizationLevel) -> std::process::ExitStatus {
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
        "{}",
        String::from_utf8_lossy(&linked.stderr)
    );
    Command::new(executable).status().unwrap()
}

fn qualify(text: &str, expected: i32) {
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        assert_eq!(run(text, optimization).code(), Some(expected), "{text}");
    }
}

#[test]
fn exact_sequences_boundaries_and_dynamic_direction_match_at_o0_o2() {
    qualify("int main(){int x=0;for(i in 0:3){x=x*10+i;}return x;}", 123);
    qualify("int main(){int x=0;for(i in 0:2:6){x=x+i;}return x;}", 12);
    qualify("int main(){int x=0;for(i in 6:-2:0){x=x+i;}return x;}", 12);
    qualify(
        "int main(){int x=7;for(i in 0:-1:10){x=1;}for(i in 10:1:0){x=2;}return x;}",
        7,
    );
    qualify("int main(){int x=0;for(i in 5:5){x=x+i;}return x;}", 5);
    qualify(
        "int main(){int x=0;for(i in 9223372036854775807:9223372036854775807){x=x+1;}return x-1;}",
        0,
    );
    qualify(
        "int main(){int x=0;for(i in -9223372036854775808:-1:-9223372036854775808){x=x+1;}return x-1;}",
        0,
    );
    qualify(
        "int main(){int s=-1;int x=4;for(i in 0:s:10){x=9;}return x;}",
        4,
    );
}

#[test]
fn operands_are_once_left_to_right_and_control_targets_are_exact() {
    qualify(
        "int mark(ref mut int trace,int digit,int value){*trace=*trace*10+digit;return value;}int main(){int trace=0;int sum=0;for(i in mark(&mut trace,1,0):mark(&mut trace,2,2):mark(&mut trace,3,4)){sum=sum+i;}if(trace==123){if(sum==6){return 0;}}return 1;}",
        0,
    );
    qualify(
        "int main(){int n=0;for(i in 0:10){n=n+1;break;}return n-1;}",
        0,
    );
    qualify(
        "int main(){int n=0;for(i in 0:3){if(i<3){continue;}n=n+1;}return n-1;}",
        0,
    );
    qualify(
        "int main(){int n=0;for(i in 0:2){for(j in 0:2){n=n+1;}}return n-9;}",
        0,
    );
}

#[test]
fn scope_return_exception_and_finally_compose() {
    qualify(
        "int main(){int i=7;for(i in 0:1){if(i==1){return i+8;}}return i;}",
        9,
    );
    qualify(
        "open class Problem:Exception{public init(){}} int main(){int x=0;try{for(i in 0:3){try{x=x+1;if(i==0){continue;}if(i==1){break;}}finally{x=x+1;}}}finally{x=x+1;}return x-5;}",
        0,
    );
    qualify(
        "open class Problem:Exception{public init(){}} int main(){int x=0;try{for(i in 0:2){Buffer<int> b=Buffer<int>(1,i);if(i==1){throw Problem();}x=x+1;}}catch(Problem e){return x-1;}return 9;}",
        0,
    );
}

#[test]
fn zero_step_and_unadmitted_iterables_fail_closed() {
    for text in [
        "int main(){for(i in 0:0:2){}return 0;}",
        "int main(){int x=0:2;return 0;}",
        "int main(){for(i in {1,2}){}return 0;}",
        "int main(){for(i in 0.0:1.0){}return 0;}",
        "int main(){for(double i in 0:1){}return 0;}",
        "int main(){for(i in 0:1){}return i;}",
    ] {
        assert!(
            compile_source_with_optimization(
                &SourceFile::new("bad.ae", text),
                &[],
                OptimizationLevel::O0
            )
            .is_err(),
            "{text}"
        );
    }
    let dynamic = "int main(){int step=0;for(i in 0:step:2){}return 0;}";
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        let compilation = compile(dynamic, optimization);
        assert!(compilation.dumps[&Emit::Mir].contains("ZeroRangeStep"));
        assert!(!run(dynamic, optimization).success());
    }
}

#[test]
fn mir_and_ssa_corruptions_are_rejected_and_no_iteration_helper_is_emitted() {
    let source = "int main(){int x=0;for(i in 0:2:6){x=x+i;}return x;}";
    let hir = analyze(parse_source(&SourceFile::new("corrupt.ae", source)).unwrap()).unwrap();
    let mir = lower_hir(hir);
    let mut bad_mir = mir.clone();
    let range = bad_mir.functions[0].range_loops[0].clone();
    let instruction = bad_mir.functions[0].blocks[range.positive_add.0 as usize]
        .instructions
        .iter_mut()
        .find(|instruction| {
            matches!(
                instruction.value,
                Rvalue::Binary {
                    op: BinaryOp::LessEqual,
                    ..
                }
            )
        })
        .unwrap();
    let Rvalue::Binary { op, .. } = &mut instruction.value else {
        unreachable!()
    };
    *op = BinaryOp::Less;
    assert!(verify_mir(bad_mir).is_err());

    let verified = verify_mir(mir).unwrap();
    let mut bad_ssa = build_ssa(&verified);
    let range = bad_ssa.functions[0].range_loops[0].clone();
    let instruction = bad_ssa.functions[0].blocks[range.negative_add.0 as usize]
        .instructions
        .iter_mut()
        .find(|instruction| {
            matches!(
                instruction.op,
                SsaOp::Binary {
                    op: BinaryOp::GreaterEqual,
                    ..
                }
            )
        })
        .unwrap();
    let SsaOp::Binary { op, .. } = &mut instruction.op else {
        unreachable!()
    };
    *op = BinaryOp::Greater;
    assert!(verify_ssa(bad_ssa).is_err());

    let llvm = compile(source, OptimizationLevel::O0).llvm;
    assert!(!llvm.contains("range_iterator"));
    assert!(!llvm.contains("range_alloc"));
    assert!(!llvm.contains("@malloc"));
    assert!(!llvm.contains("@free"));
}
