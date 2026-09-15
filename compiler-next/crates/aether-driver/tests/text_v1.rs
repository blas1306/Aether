//! TEXT-V1 exact scalar-indexed Text qualification.

use std::{fmt::Write as _, fs, path::PathBuf, process::Command};

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
    let source = if source.trim_start().starts_with("package ") {
        source.to_owned()
    } else {
        format!("package main;\n{source}")
    };
    fs::write(&input, &source).unwrap();
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
                "Lines",
            ] {
                assert!(dump.contains(operation), "{phase:?} lacks {operation}");
            }
        }
        assert!(compilation.llvm.contains("aether_text_byte_at"));
        assert!(compilation.llvm.contains("aether_text_copy_range"));
        assert!(!compilation.llvm.contains("TextOp"));
    }
}

fn instrument_balanced_lifecycle(llvm: &str) -> String {
    let mut guard = String::new();
    writeln!(
        guard,
        "  %lines_heap_allocs = load i64, ptr @aether_heap_alloc_count\n  %lines_heap_frees = load i64, ptr @aether_heap_free_count\n  %lines_heap_ok = icmp eq i64 %lines_heap_allocs, %lines_heap_frees\n  %lines_string_allocs = load i64, ptr @aether_string_alloc_count\n  %lines_string_frees = load i64, ptr @aether_string_free_count\n  %lines_string_ok = icmp eq i64 %lines_string_allocs, %lines_string_frees\n  %lines_balanced = and i1 %lines_heap_ok, %lines_string_ok\n  %lines_result_ok = icmp eq i32 %process_status, 0\n  %lines_ok = and i1 %lines_balanced, %lines_result_ok\n  %lines_status = select i1 %lines_ok, i32 0, i32 99\n  ret i32 %lines_status"
    )
    .unwrap();
    llvm.replace("  ret i32 %process_status", &guard)
}

#[test]
fn lines_v1_exact_semantics_borrow_and_lifecycle_at_o0_o2() {
    let source = r#"import std.Text;
int zero(ref string input){List<string> lines=std.Text.lines(input);if(length(lines)!=0){return 1;}return 0;}
int one(ref string input,ref string expected){List<string> lines=std.Text.lines(input);if(length(lines)!=1){return 1;}string a=remove(lines,0);if(a!=*expected){return 2;}return 0;}
int two(ref string input,ref string first,ref string second){List<string> lines=std.Text.lines(input);if(length(lines)!=2){return 1;}string a=remove(lines,0);string b=remove(lines,0);if(a!=*first){return 2;}if(b!=*second){return 3;}return 0;}
int three(ref string input,ref string first,ref string second,ref string third){List<string> lines=std.Text.lines(input);if(length(lines)!=3){return 1;}string a=remove(lines,0);string b=remove(lines,0);string c=remove(lines,0);if(a!=*first){return 2;}if(b!=*second){return 3;}if(c!=*third){return 4;}return 0;}
int main(){
 string text="a\nb";
 if(zero("")!=0){return 1;}
 if(one("a","a")!=0){return 2;}
 if(two(text,"a","b")!=0){return 3;}
 if(two("a\nb\n","a","b")!=0){return 4;}
 if(one("\n","")!=0){return 5;}
 if(two("\n\n","","")!=0){return 6;}
 if(three("a\n\nb","a","","b")!=0){return 7;}
 if(two("a\r\nb\r\n","a","b")!=0){return 8;}
 if(one("a\rb","a\rb")!=0){return 9;}
 if(three("é\0😀\r\n\n中\rtext\n","é\0😀","","中\rtext")!=0){return 10;}
 if(one("a b","a b")!=0){return 11;}
 List<string> split=std.Text.split("a\n","\n");if(length(split)!=2){return 12;}
 string split0=remove(split,0);string split1=remove(split,0);if(split0!="a"){return 13;}if(split1!=""){return 14;}
 return 0;
}"#;
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        let (compilation, output) = compile_and_run(source, optimization);
        assert_eq!(output.status.code(), Some(0), "{optimization:?}");
        assert!(compilation.dumps[&Emit::Hir].contains("Lines"));
        assert!(compilation.dumps[&Emit::Hir].contains("CallScopedSharedBorrow"));
        assert!(compilation.dumps[&Emit::Mir].contains("EndBorrow"));
        assert!(compilation.dumps[&Emit::Ssa].contains("Drop"));
        assert!(compilation.llvm.contains("@aether_text_lines"));
        assert_eq!(
            execute_llvm(
                &instrument_balanced_lifecycle(&compilation.llvm),
                optimization
            )
            .status
            .code(),
            Some(0),
            "unbalanced lifecycle at {optimization:?}"
        );
    }
}

#[test]
fn lines_v1_list_is_cleaned_during_unwind() {
    let source = r#"import std.Text;
open class Problem:Exception{public init(){}}
int fail(){throw Problem();}
int main(){try{List<string> lines=std.Text.lines("a\r\n\nb\n");fail();}catch(Problem error){return 0;}return 1;}"#;
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        let (compilation, output) = compile_and_run(source, optimization);
        assert_eq!(output.status.code(), Some(0), "{optimization:?}");
        assert!(compilation.dumps[&Emit::Mir].contains("unwind"));
        assert_eq!(
            execute_llvm(
                &instrument_balanced_lifecycle(&compilation.llvm),
                optimization
            )
            .status
            .code(),
            Some(0),
            "unbalanced unwind lifecycle at {optimization:?}"
        );
    }
}

#[test]
fn empty_edges_split_and_adversarial_search_are_exact() {
    let repeated = "a".repeat(20_000);
    let source = format!(
        r#"import std.Text;
int main(){{
 if(std.Text.contains("","")==false){{return 1;}}
 if(std.Text.startsWith("abc","")==false){{return 2;}}
 if(std.Text.endsWith("abc","")==false){{return 3;}}
 match(std.Text.find("abc","x")){{std.Text.FindResult.Found(at)=>{{return 4;}} std.Text.FindResult.NotFound=>{{}}}}
 match(std.Text.findFrom("abc","",std.Text.scalarOffset(3))){{std.Text.FindResult.Found(at)=>{{if(at.value!=3){{return 5;}}}} std.Text.FindResult.NotFound=>{{return 6;}}}}
 string empty=std.Text.substring("abc",std.Text.scalarOffset(1),std.Text.scalarOffset(1));
 string whole=std.Text.substring("abc",std.Text.scalarOffset(0),std.Text.scalarOffset(3));
 if(empty!=""){{return 7;}} if(whole!="abc"){{return 7;}}
 List<string> a=std.Text.split(",a,,",",");
 if(length(a)!=4){{return 8;}}
 string x0=remove(a,0);string x1=remove(a,0);string x2=remove(a,0);string x3=remove(a,0);
 if(x0!=""){{return 9;}} if(x1!="a"){{return 9;}} if(x2!=""){{return 9;}} if(x3!=""){{return 9;}}
 List<string> one=std.Text.split("abc","x");string only=remove(one,0);
 if(length(one)!=0){{return 10;}} if(only!="abc"){{return 10;}}
 if(std.Text.contains("{repeated}b","{repeated}b")==false){{return 11;}}
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
        "import std.Text;int main(){std.Text.FindResult r=std.Text.findFrom(\"x\",\"\",std.Text.scalarOffset(2));match(r){std.Text.FindResult.Found(at)=>{} std.Text.FindResult.NotFound=>{}}return 0;}",
        "import std.Text;int main(){string x=std.Text.substring(\"x\",std.Text.scalarOffset(1),std.Text.scalarOffset(0));return 0;}",
        "import std.Text;int main(){string x=std.Text.substring(\"x\",std.Text.scalarOffset(0),std.Text.scalarOffset(2));return 0;}",
        "import std.Text;int main(){List<string> x=std.Text.split(\"x\",\"\");return 0;}",
    ];
    for source in cases {
        let (_, output) = compile_and_run(source, OptimizationLevel::O0);
        assert!(!output.status.success(), "did not trap: {source}");
    }
}

#[test]
fn owned_results_cleanup_on_early_return_and_unwind() {
    let early = r#"import std.Text;
string choose(){
 string part=std.Text.substring("abcd",std.Text.scalarOffset(1),std.Text.scalarOffset(3));
 return part;
}
int main(){
 string selected=choose();if(selected!="bc"){return 1;}
 return 0;
}"#;
    let unwind = r#"import std.Text;
open class Problem:Exception{public init(){}}
int fail(){throw Problem();}
int main(){
 try{List<string> pieces=std.Text.split("a,b",",");fail();}
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
        "package main; import std.Text;int main(){return int(std.Text.codePointCount(\"é\"));}",
    )
    .unwrap();
    fs::write(
        directory.0.join("Text.ae"),
        "package Text; int codePointCount(string value){return 99;}",
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
    fs::write(&plain, "package plain; int main(){return 0;}").unwrap();
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
    let source = r#"import std.Text;
int main(){
 string value="aaaaaaaaaaaaaaaaab";
 usize count=std.Text.codePointCount(value);bool contains=std.Text.contains(value,"aaac");
 bool starts=std.Text.startsWith(value,"a");bool ends=std.Text.endsWith(value,"b");
 if(count!=18){return 2;}if(contains){return 2;}if(starts==false){return 2;}if(ends==false){return 2;}
 match(std.Text.find(value,"b")){std.Text.FindResult.Found(at)=>{} std.Text.FindResult.NotFound=>{return 1;}}
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
