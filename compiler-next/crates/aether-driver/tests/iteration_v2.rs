//! ITERATION-V2 native Array/List Copy for-in qualification.

use std::{fs, path::PathBuf, process::Command};

use aether_driver::{Emit, OptimizationLevel, compile_source_with_optimization};
use aether_frontend::{SourceFile, analyze, parse_source};
use aether_middle::{BinaryOp, Rvalue, SsaOp, build_ssa, lower_hir, verify_mir, verify_ssa};

struct Directory(PathBuf);

impl Directory {
    fn new() -> Self {
        static NEXT: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
        let path = std::env::temp_dir().join(format!(
            "aether-iteration-v2-{}-{}",
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
        &SourceFile::new("iteration_v2.ae", text),
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
fn empty_singleton_multiple_exact_bindings_and_copy_sizes() {
    qualify(
        "int main(){Array<int> e={};Array<int> a={7};List<int> le={};List<int> ls={8};List<int> lm={1,2,3};int s=0;for(x in e){s=99;}for(x in le){s=99;}for(int x in a){s=s+x;}for(x in ls){s=s+x;}for(x in lm){s=s+x;}return s-21;}",
        0,
    );
    qualify(
        "struct Pair{int8 a;int32 b;}int main(){Array<int8> a={1,2};List<int32> b={3,4};Array<Pair> p={Pair(5,6)};int s=0;for(int8 x in a){s=s+x;}for(int32 x in b){s=s+x;}for(Pair x in p){s=s+x.a+x.b;}return s-21;}",
        0,
    );
    qualify(
        "int sum_array(ref Array<int> a){int s=0;for(x in *a){s=s+x;}return s;}int sum_list(ref List<int> a){int s=0;for(x in *a){s=s+x;}return s;}int main(){Array<int> a={1,2};List<int> b={3,4};return sum_array(&a)+sum_list(&b)-10;}",
        0,
    );
    for bad in [
        "int main(){Array<int32> a={1};for(int x in a){}return 0;}",
        "int main(){List<int> a={1};for(int32 x in a){}return 0;}",
    ] {
        assert!(
            compile_source_with_optimization(
                &SourceFile::new("bad.ae", bad),
                &[],
                OptimizationLevel::O0,
            )
            .is_err(),
            "{bad}"
        );
    }
}

#[test]
fn capture_once_future_slot_mutation_and_control_flow() {
    qualify(
        "Array<int> make(ref mut int calls){*calls=*calls+1;return {1,2,3};}int main(){int calls=0;int sum=0;for(x in make(&mut calls)){sum=sum+x;}return calls*10+sum-16;}",
        0,
    );
    qualify(
        "int main(){List<int> a={1,2,3};int s=0;for(x in a){s=s+x;if(x==1){a[1]=9;}}return s-13;}",
        0,
    );
    qualify(
        "int main(){Array<int> a={1,2,3};List<int> b={4,5,6};int s=0;for(x in a){if(x==2){continue;}for(y in b){s=s+y;break;}}return s-8;}",
        0,
    );
    let compilation = compile(
        "int main(){Array<int> a={1,2};int s=0;for(x in a){s=s+x;}for(i in 0:1){s=s+i;}return s-4;}",
        OptimizationLevel::O0,
    );
    assert_eq!(
        compilation.dumps[&Emit::Mir].matches("ArrayLength").count(),
        1
    );
    assert!(compilation.dumps[&Emit::Mir].contains("captured_length"));
}

#[test]
fn structural_mutation_move_and_unknown_writable_calls_fail_closed() {
    for bad in [
        "int main(){List<int> a={1};for(x in a){push(a,2);}return 0;}",
        "int main(){List<int> a={1};for(x in a){reserve(a,9);}return 0;}",
        "int main(){List<int> a={1};for(x in a){int y=pop(a);}return 0;}",
        "int main(){List<int> a={1,2};for(x in a){int y=swap_remove(a,0);}return 0;}",
        "int main(){List<int> a={1,2};for(x in a){int y=remove(a,0);}return 0;}",
        "int main(){List<int> a={1};for(x in a){List<int> b=a;}return 0;}",
        "int main(){List<int> a={1};for(x in a){a={2};}return 0;}",
        "int mutate(ref mut List<int> a){push(*a,2);return 0;}int main(){List<int> a={1};for(x in a){int y=mutate(&mut a);}return 0;}",
        "int main(){Array<int> a={1};for(x in a){Array<int> b=a;}return 0;}",
        "int main(){Array<int> a={1};for(x in a){a={2};}return 0;}",
    ] {
        assert!(
            compile_source_with_optimization(
                &SourceFile::new("bad.ae", bad),
                &[],
                OptimizationLevel::O0,
            )
            .is_err(),
            "{bad}"
        );
    }
}

#[test]
fn temporary_cleanup_return_throw_and_finally_compose() {
    qualify(
        "Array<int> make(){return {2,3};}int main(){for(x in make()){if(x==3){return x-3;}}return 9;}",
        0,
    );
    qualify(
        "open class Problem:Exception{public init(){}}List<int> make(){return {1,2};}int main(){int n=0;try{for(x in make()){n=n+1;if(x==2){throw Problem();}}}catch(Problem e){return n-2;}return 9;}",
        0,
    );
    qualify(
        "int main(){List<int> values={1,2};int n=0;for(x in values){try{n=n+1;if(x==1){continue;}}finally{n=n+2;}}return n-6;}",
        0,
    );
    let compilation = compile(
        "Array<int> make(){return {1};}int main(){for(x in make()){break;}return 0;}",
        OptimizationLevel::O0,
    );
    for dump in [Emit::Hir, Emit::Mir, Emit::Ssa] {
        assert!(compilation.dumps[&dump].contains("Collection"));
    }
    assert!(compilation.dumps[&Emit::Mir].contains("temporary_owner: Some"));
}

#[test]
fn mir_ssa_corruptions_and_zero_iterator_overhead() {
    let source = "int main(){Array<int> a={1,2,3};int s=0;for(x in a){s=s+x;}return s-6;}";
    let hir = analyze(parse_source(&SourceFile::new("corrupt.ae", source)).unwrap()).unwrap();
    let mir = lower_hir(hir);
    let mut bad_mir = mir.clone();
    let collection = bad_mir.functions[0].collection_loops[0].clone();
    let instruction = bad_mir.functions[0].blocks[collection.latch.0 as usize]
        .instructions
        .iter_mut()
        .find(|instruction| matches!(instruction.value, Rvalue::Binary { .. }))
        .unwrap();
    let Rvalue::Binary { op, .. } = &mut instruction.value else {
        unreachable!()
    };
    *op = BinaryOp::SubtractIntegerChecked;
    assert!(verify_mir(bad_mir).is_err());

    let verified = verify_mir(mir).unwrap();
    let mut bad_ssa = build_ssa(&verified);
    let collection = bad_ssa.functions[0].collection_loops[0].clone();
    let instruction = bad_ssa.functions[0].blocks[collection.item.0 as usize]
        .instructions
        .iter_mut()
        .find(|instruction| matches!(instruction.op, SsaOp::CollectionBinding { .. }))
        .unwrap();
    let SsaOp::CollectionBinding { item_type, .. } = &mut instruction.op else {
        unreachable!()
    };
    *item_type = aether_frontend::TypeId::INT32;
    assert!(verify_ssa(bad_ssa).is_err());

    let llvm = compile(source, OptimizationLevel::O0).llvm;
    assert!(!llvm.contains("iterator"));
    assert!(!llvm.contains("collection_alloc"));
    assert!(!llvm.contains("collection_next"));
    assert!(!llvm.contains("@aether_array_index"));
    let list_llvm = compile(
        "int main(){List<int> a={1,2};int s=0;for(x in a){s=s+x;}return s-3;}",
        OptimizationLevel::O0,
    )
    .llvm;
    assert!(!list_llvm.contains("call ptr @aether_list_index"));
}
