//! TEXT-V1 exact scalar-indexed Text qualification.

use std::{fs, path::PathBuf, process::Command};

use aether_driver::{ClangToolchain, Emit, OptimizationLevel, build_path};

struct Directory(PathBuf);

impl Directory {
    fn new() -> Self {
        static NEXT: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
        let path = std::env::temp_dir().join(format!(
            "aether-text-v1-{}-{}",
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

fn compile_and_run(
    source: &str,
    optimization: OptimizationLevel,
) -> (aether_driver::Compilation, std::process::Output) {
    let directory = Directory::new();
    let input = directory.0.join("main.ae");
    let executable = directory.0.join("program");
    fs::write(&input, source).unwrap();
    let toolchain = ClangToolchain::default().with_optimization(optimization);
    let compilation = build_path(
        &input,
        &executable,
        &[Emit::Hir, Emit::Mir, Emit::Ssa, Emit::Llvm],
        &toolchain,
    )
    .unwrap_or_else(|errors| panic!("{source}\n{errors:#?}"));
    let output = Command::new(executable).output().unwrap();
    (compilation, output)
}

fn execute_llvm(llvm: &str, optimization: OptimizationLevel) -> std::process::Output {
    let directory = Directory::new();
    let input = directory.0.join("program.ll");
    let executable = directory.0.join("program");
    fs::write(&input, llvm).unwrap();
    let option = if optimization == OptimizationLevel::O0 {
        "-O0"
    } else {
        "-O2"
    };
    let linked = Command::new("clang")
        .args(["-Wno-override-module", option, "-x", "ir"])
        .arg(input)
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
    Command::new(executable).output().unwrap()
}

#[test]
fn complete_surface_runs_at_o0_and_o2() {
    let source = include_str!("../../../tests/programs/text_v1_smoke.ae");
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        let (compilation, output) = compile_and_run(source, optimization);
        assert_eq!(output.status.code(), Some(0), "{optimization:?}");
        for phase in [Emit::Hir, Emit::Mir, Emit::Ssa] {
            let dump = &compilation.dumps[&phase];
            for operation in [
                "CodePointCount",
                "Contains",
                "StartsWith",
                "EndsWith",
                "Find",
                "Substring",
                "Trim",
                "Split",
            ] {
                assert!(dump.contains(operation), "{phase:?} lacks {operation}");
            }
        }
        assert!(compilation.llvm.contains("aether_text_byte_at"));
        assert!(compilation.llvm.contains("aether_text_copy_range"));
        assert!(!compilation.llvm.contains("TextOp"));
    }
}

#[test]
fn empty_edges_split_and_adversarial_search_are_exact() {
    let repeated = "a".repeat(20_000);
    let source = format!(
        r#"import Text;
int main(){{
 if(Text.contains("","")==false){{return 1;}}
 if(Text.startsWith("abc","")==false){{return 2;}}
 if(Text.endsWith("abc","")==false){{return 3;}}
 match(Text.find("abc","x")){{Text.FindResult.Found(at)=>{{return 4;}} Text.FindResult.NotFound=>{{}}}}
 match(Text.findFrom("abc","",Text.scalarOffset(3))){{Text.FindResult.Found(at)=>{{if(at.value!=3){{return 5;}}}} Text.FindResult.NotFound=>{{return 6;}}}}
 string empty=Text.substring("abc",Text.scalarOffset(1),Text.scalarOffset(1));
 string whole=Text.substring("abc",Text.scalarOffset(0),Text.scalarOffset(3));
 if(empty!=""){{return 7;}} if(whole!="abc"){{return 7;}}
 List<string> a=Text.split(",a,,",",");
 if(length(a)!=4){{return 8;}}
 string x0=remove(a,0);string x1=remove(a,0);string x2=remove(a,0);string x3=remove(a,0);
 if(x0!=""){{return 9;}} if(x1!="a"){{return 9;}} if(x2!=""){{return 9;}} if(x3!=""){{return 9;}}
 List<string> one=Text.split("abc","x");string only=remove(one,0);
 if(length(one)!=0){{return 10;}} if(only!="abc"){{return 10;}}
 if(Text.contains("{repeated}b","{repeated}b")==false){{return 11;}}
 return 0;
}}"#
    );
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        let (_, output) = compile_and_run(&source, optimization);
        assert_eq!(output.status.code(), Some(0), "{optimization:?}");
    }
}

#[test]
fn contract_failures_trap_before_results() {
    let cases = [
        "import Text;int main(){Text.FindResult r=Text.findFrom(\"x\",\"\",Text.scalarOffset(2));match(r){Text.FindResult.Found(at)=>{} Text.FindResult.NotFound=>{}}return 0;}",
        "import Text;int main(){string x=Text.substring(\"x\",Text.scalarOffset(1),Text.scalarOffset(0));return 0;}",
        "import Text;int main(){string x=Text.substring(\"x\",Text.scalarOffset(0),Text.scalarOffset(2));return 0;}",
        "import Text;int main(){List<string> x=Text.split(\"x\",\"\");return 0;}",
    ];
    for source in cases {
        let (_, output) = compile_and_run(source, OptimizationLevel::O0);
        assert!(!output.status.success(), "did not trap: {source}");
    }
}

#[test]
fn owned_results_cleanup_on_early_return_and_unwind() {
    let early = r#"import Text;
string choose(){
 string part=Text.substring("abcd",Text.scalarOffset(1),Text.scalarOffset(3));
 return part;
}
int main(){
 string selected=choose();if(selected!="bc"){return 1;}
 return 0;
}"#;
    let unwind = r#"import Text;
open class Problem:Exception{public init(){}}
int fail(){throw Problem();}
int main(){
 try{List<string> pieces=Text.split("a,b",",");fail();}
 catch(Problem error){return 0;}
 return 2;
}"#;
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        let (compilation, output) = compile_and_run(early, optimization);
        assert_eq!(output.status.code(), Some(0), "{optimization:?}");
        assert!(compilation.dumps[&Emit::Ssa].contains("Drop"));
        let (compilation, output) = compile_and_run(unwind, optimization);
        assert_eq!(output.status.code(), Some(0), "{optimization:?}");
        assert!(compilation.dumps[&Emit::Mir].contains("unwind"));
    }
}

#[test]
fn canonical_module_cannot_be_shadowed_and_helpers_are_reachable_only() {
    let directory = Directory::new();
    let input = directory.0.join("main.ae");
    let executable = directory.0.join("program");
    fs::write(
        &input,
        "import Text;int main(){return int(Text.codePointCount(\"é\"));}",
    )
    .unwrap();
    fs::write(
        directory.0.join("Text.ae"),
        "int codePointCount(string value){return 99;}",
    )
    .unwrap();
    let compilation = build_path(
        &input,
        &executable,
        &[Emit::Llvm],
        &ClangToolchain::default(),
    )
    .unwrap();
    assert_eq!(Command::new(executable).status().unwrap().code(), Some(1));
    assert!(compilation.llvm.contains("aether_text_code_point_count"));

    let plain = directory.0.join("plain.ae");
    let plain_exe = directory.0.join("plain");
    fs::write(&plain, "int main(){return 0;}").unwrap();
    let compilation = build_path(
        &plain,
        &plain_exe,
        &[Emit::Llvm],
        &ClangToolchain::default(),
    )
    .unwrap();
    assert!(!compilation.llvm.contains("aether_text_"));
}

#[test]
fn queries_allocate_and_retain_nothing() {
    let source = r#"import Text;
int main(){
 string value="aaaaaaaaaaaaaaaaab";
 usize count=Text.codePointCount(value);bool contains=Text.contains(value,"aaac");
 bool starts=Text.startsWith(value,"a");bool ends=Text.endsWith(value,"b");
 if(count!=18){return 2;}if(contains){return 2;}if(starts==false){return 2;}if(ends==false){return 2;}
 match(Text.find(value,"b")){Text.FindResult.Found(at)=>{} Text.FindResult.NotFound=>{return 1;}}
 return 0;
}"#;
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        let (compilation, _) = compile_and_run(source, optimization);
        let check = "  %text_allocs = load i64, ptr @aether_string_alloc_count\n  %text_no_alloc = icmp eq i64 %text_allocs, 0\n  %text_retains = load i64, ptr @aether_string_retain_count\n  %text_no_retain = icmp eq i64 %text_retains, 0\n  %text_clean = and i1 %text_no_alloc, %text_no_retain\n  %text_status = select i1 %text_clean, i32 %process_status, i32 99\n  ret i32 %text_status";
        let instrumented = compilation.llvm.replace("  ret i32 %process_status", check);
        assert_ne!(instrumented, compilation.llvm);
        assert_eq!(
            execute_llvm(&instrumented, optimization).status.code(),
            Some(0)
        );
    }
}
