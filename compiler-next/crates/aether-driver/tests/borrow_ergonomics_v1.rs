//! BORROW-ERGONOMICS-V1 exact shared call-borrow qualification.

use std::{fmt::Write as _, fs, path::PathBuf, process::Command};

use aether_driver::{
    ClangToolchain, Emit, OptimizationLevel, build_path, compile_source,
    compile_source_with_optimization,
};
use aether_frontend::{CallSiteId, SourceFile, analyze, parse_source};
use aether_middle::{Rvalue, SsaOp, build_ssa, lower_hir, verify_mir, verify_ssa};

struct Output(PathBuf);

impl Output {
    fn new(label: &str) -> Self {
        static NEXT: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
        Self(std::env::temp_dir().join(format!(
            "aether-borrow-v1-{label}-{}-{}",
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
        &SourceFile::new("borrow_ergonomics_v1.ae", source),
        &[Emit::Hir, Emit::Mir, Emit::Ssa, Emit::Llvm],
        optimization,
    )
    .unwrap_or_else(|errors| panic!("{source}\n{errors:#?}"))
}

fn status(source: &str, optimization: OptimizationLevel) -> i32 {
    let compilation = compile(source, optimization);
    let output = Output::new("native");
    ClangToolchain::default()
        .with_optimization(optimization)
        .link_executable(&compilation.llvm, &output.0)
        .unwrap();
    Command::new(&output.0)
        .status()
        .unwrap()
        .code()
        .unwrap_or(-1)
}

fn std_compile_and_status(
    source: &str,
    optimization: OptimizationLevel,
) -> (aether_driver::Compilation, i32) {
    let directory = Output::new("project");
    fs::create_dir(&directory.0).unwrap();
    let input = directory.0.join("main.ae");
    let executable = directory.0.join("program");
    fs::write(&input, format!("package main;{source}")).unwrap();
    let compilation = build_path(
        &input,
        &executable,
        &[Emit::Hir, Emit::Mir, Emit::Ssa, Emit::Llvm],
        &ClangToolchain::default().with_optimization(optimization),
    )
    .unwrap_or_else(|errors| panic!("{source}\n{errors:#?}"));
    let status = Command::new(&executable)
        .status()
        .unwrap()
        .code()
        .unwrap_or(-1);
    fs::remove_dir_all(&directory.0).unwrap();
    (compilation, status)
}

fn instrument_string_counts(llvm: &str, counts: [u64; 7]) -> String {
    let names = [
        "alloc",
        "free",
        "retain",
        "release",
        "concat",
        "equal",
        "literal_arc_noop",
    ];
    let mut guard = "  %borrow_result_ok = icmp eq i32 %process_status, 0\n".to_owned();
    let mut last = "borrow_result_ok".to_owned();
    for (index, (name, expected)) in names.iter().zip(counts).enumerate() {
        writeln!(
            guard,
            "  %borrow_{index} = load i64, ptr @aether_string_{name}_count\n  %borrow_ok_{index} = icmp eq i64 %borrow_{index}, {expected}\n  %borrow_all_{index} = and i1 %{last}, %borrow_ok_{index}"
        )
        .unwrap();
        last = format!("borrow_all_{index}");
    }
    writeln!(
        guard,
        "  %borrow_status = select i1 %{last}, i32 0, i32 99\n  ret i32 %borrow_status"
    )
    .unwrap();
    llvm.replace("  ret i32 %process_status", &guard)
}

#[test]
fn exact_lvalue_copy_literal_temporary_and_explicit_forms_run_at_o0_o2() {
    let source = r#"
import std.Text;
int read(ref int value){return *value;}
string make(){return "Ae"+"ther";}
int main(){
  int value=7; string text="Aether";
  if(read(value)!=read(&value)){return 1;}
  if(std.Text.contains(text,"Aether")==false){return 2;}
  if(std.Text.contains("Aether","ether")==false){return 3;}
  if(std.Text.contains(make(),"Aether")==false){return 4;}
  return 0;
}"#;
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        let (compilation, status) = std_compile_and_status(source, optimization);
        assert_eq!(status, 0);
        for dump in [
            &compilation.dumps[&Emit::Hir],
            &compilation.dumps[&Emit::Mir],
            &compilation.dumps[&Emit::Ssa],
        ] {
            assert!(dump.contains("CallSiteId"));
            assert!(dump.contains("argument_index"));
        }
        assert!(compilation.dumps[&Emit::Mir].contains("EndBorrow"));
        assert!(compilation.dumps[&Emit::Ssa].contains("EndBorrow"));
        assert!(compilation.dumps[&Emit::Hir].contains("CallScopedSharedBorrow"));
        assert!(compilation.dumps[&Emit::Hir].contains("Temporary"));
        assert!(compilation.dumps[&Emit::Hir].contains("Explicit"));
        assert!(!compilation.llvm.contains("noalias"));
    }
}

#[test]
fn file_and_text_use_the_same_typed_adaptation() {
    let path = Output::new("input");
    fs::write(&path.0, "Aether\n").unwrap();
    let path = path.0.to_string_lossy().replace('\\', "\\\\");
    let source = format!(
        r#"import std.File;import std.Text;
int main(){{string path="{path}";string a=std.File.readText(path);string b=std.File.readText("{path}");if(std.Text.contains(a,"Aether")==false){{return 1;}}if(std.Text.contains(b,"Aether")==false){{return 2;}}return 0;}}"#
    );
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        let (compilation, status) = std_compile_and_status(&source, optimization);
        assert_eq!(status, 0);
        assert!(
            compilation.dumps[&Emit::Hir]
                .matches("CallScopedSharedBorrow")
                .count()
                >= 6
        );
        assert!(compilation.dumps[&Emit::Mir].contains("reference_type"));
        assert!(compilation.dumps[&Emit::Ssa].contains("EndBorrow"));
    }
}

#[test]
fn generics_are_determined_before_borrow_adaptation() {
    let source = r"
int explicitRead<T>(ref T value){return 3;}
int pair<T>(T tag,ref T value){return 4;}
int main(){int x=1;if(explicitRead<int>(x)!=3){return 1;}if(pair(x,x)!=4){return 2;}return 0;}
";
    assert_eq!(status(source, OptimizationLevel::O0), 0);
    let inferred_only = "int read<T>(ref T value){return 0;}int main(){int x=1;return read(x);}";
    let errors = compile_source(&SourceFile::new("infer.ae", inferred_only), &[]).unwrap_err();
    assert_eq!(errors[0].code, "E0263");
}

#[test]
fn mutable_conversion_escape_contexts_and_auto_deref_remain_closed() {
    let cases = [
        "int f(ref mut int x){return *x;}int main(){int x=1;return f(x);}",
        "int f(ref int64 x){return *x;}int main(){int32 x=1;return f(x);}",
        "int f(int x){return x;}int main(){int x=1;ref int r=&x;return f(r);}",
        "int main(){int x=1;ref int r=x;return 0;}",
        "ref int bad(int x){return x;}",
    ];
    for source in cases {
        assert!(
            compile_source(&SourceFile::new("closed.ae", source), &[]).is_err(),
            "unexpected admission: {source}"
        );
    }
}

#[test]
fn earlier_borrow_blocks_same_root_move_but_disjoint_root_is_legal() {
    let invalid = r"
int inspect(ref Buffer<int> first,Buffer<int> second){return (*first)[0];}
int main(){Buffer<int> value=Buffer<int>(1,7);return inspect(value,value);}
";
    assert!(compile_source(&SourceFile::new("invalid.ae", invalid), &[]).is_err());
    let valid = r"
int inspect(ref Buffer<int> first,Buffer<int> second){return (*first)[0]+second[0];}
int main(){Buffer<int> a=Buffer<int>(1,3);Buffer<int> b=Buffer<int>(1,4);return inspect(a,b)-7;}
";
    assert_eq!(status(valid, OptimizationLevel::O0), 0);
}

#[test]
fn mir_and_ssa_reject_call_region_corruption_independently() {
    let source = SourceFile::new(
        "corruption.ae",
        "int read(ref int x){return *x;}int main(){int x=7;return read(x)-7;}",
    );
    let hir = analyze(parse_source(&source).unwrap()).unwrap();
    let mir = lower_hir(hir);
    verify_mir(mir.clone()).unwrap();

    let mut bad_site = mir.clone();
    let metadata = bad_site
        .functions
        .iter_mut()
        .flat_map(|function| &mut function.blocks)
        .flat_map(|block| &mut block.instructions)
        .find_map(|instruction| match &mut instruction.value {
            Rvalue::Borrow {
                call: Some(metadata),
                ..
            } => Some(metadata),
            _ => None,
        })
        .unwrap();
    metadata.call_site = CallSiteId(metadata.call_site.0 + 100);
    assert!(verify_mir(bad_site).is_err());

    let mut missing_end = mir.clone();
    for function in &mut missing_end.functions {
        for block in &mut function.blocks {
            block
                .instructions
                .retain(|instruction| !matches!(instruction.value, Rvalue::EndBorrow { .. }));
        }
    }
    assert!(verify_mir(missing_end).is_err());

    let verified = verify_mir(mir).unwrap();
    let ssa = build_ssa(&verified);
    verify_ssa(ssa.clone()).unwrap();

    let mut bad_index = ssa.clone();
    let metadata = bad_index
        .functions
        .iter_mut()
        .flat_map(|function| &mut function.blocks)
        .flat_map(|block| &mut block.instructions)
        .find_map(|instruction| match &mut instruction.op {
            SsaOp::Borrow {
                call: Some(metadata),
                ..
            } => Some(metadata),
            _ => None,
        })
        .unwrap();
    metadata.argument_index = 9;
    assert!(verify_ssa(bad_index).is_err());

    let mut escaped = ssa;
    let (reference, reference_type) = escaped
        .functions
        .iter()
        .flat_map(|function| &function.blocks)
        .flat_map(|block| &block.instructions)
        .find_map(|instruction| match &instruction.op {
            SsaOp::Borrow { call: Some(_), .. } => Some((instruction.result, instruction.ty)),
            _ => None,
        })
        .unwrap();
    let end = escaped
        .functions
        .iter_mut()
        .flat_map(|function| &mut function.blocks)
        .flat_map(|block| &mut block.instructions)
        .find(|instruction| matches!(instruction.op, SsaOp::EndBorrow { .. }))
        .unwrap();
    end.op = SsaOp::Use(aether_middle::SsaOperand::Value(reference));
    end.ty = reference_type;
    assert!(verify_ssa(escaped).is_err());
}

#[test]
fn later_argument_and_callee_unwind_close_borrows_before_finally() {
    let source = r#"
open class Problem:Exception{public init(){}}
int fail(){throw Problem();}
int inspect(ref string first,int second){return int(byteLength(*first))+second;}
int main(){int state=0;try{string text="A"+"B";inspect(text,fail());}catch(Problem p){state=1;}finally{state=state+2;}
try{inspect("C"+"D",fail());}catch(Problem p){state=state+4;}return state-7;}
"#;
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        assert_eq!(status(source, optimization), 0);
        let compilation = compile(source, optimization);
        let mir = &compilation.dumps[&Emit::Mir];
        assert!(mir.contains("landing_pad"));
        assert!(mir.contains("EndBorrow"));
        assert!(mir.contains("Drop"));
        assert!(compilation.llvm.contains("invoke"));
    }
}

#[test]
fn implicit_and_explicit_forms_add_no_alias_or_arc_events() {
    let sources = [
        (
            r#"int inspect(ref string value){return int(byteLength(*value));}int main(){return inspect("A"+"B")-2;}"#,
            [1, 1, 0, 1, 1, 0, 2],
        ),
        (
            r#"int inspect(ref string value){return int(byteLength(*value));}int main(){string value="A"+"B";return inspect(&value)-2;}"#,
            [1, 1, 0, 1, 1, 0, 2],
        ),
        (
            r#"int inspect(ref string value){return int(byteLength(*value));}int main(){return inspect("A")-1;}"#,
            [0, 0, 0, 0, 0, 0, 1],
        ),
    ];
    for (source, counts) in sources {
        for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
            let compilation = compile(source, optimization);
            assert!(!compilation.dumps[&Emit::Hir].contains("Alias"));
            let output = Output::new("counters");
            let llvm = instrument_string_counts(&compilation.llvm, counts);
            ClangToolchain::default()
                .with_optimization(optimization)
                .link_executable(&llvm, &output.0)
                .unwrap();
            assert_eq!(Command::new(&output.0).status().unwrap().code(), Some(0));
        }
    }
}
