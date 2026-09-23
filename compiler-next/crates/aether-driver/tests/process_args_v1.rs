//! PROCESS-ARGS-V1 public surface, POSIX boundary, ownership and reachability qualification.

use std::ffi::{OsStr, OsString};
use std::fs;
use std::os::unix::ffi::OsStringExt;
use std::path::{Path, PathBuf};
use std::process::{Command, Output};

use aether_driver::{ClangToolchain, Emit, OptimizationLevel, build_path};
use aether_frontend::{SourceFile, TypeData, TypeId, analyze, parse_source};
use aether_middle::{Rvalue, SsaOp, build_ssa, lower_hir, verify_mir, verify_ssa};

struct Directory(PathBuf);

impl Directory {
    fn new(label: &str) -> Self {
        static NEXT: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
        let path = std::env::temp_dir().join(format!(
            "aether-process-args-{label}-{}-{}",
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

fn build(
    directory: &Directory,
    source: &str,
    optimization: OptimizationLevel,
) -> (aether_driver::Compilation, PathBuf) {
    let input = directory.0.join("main.ae");
    let executable = directory.0.join(format!("program-{optimization:?}"));
    fs::write(&input, source).unwrap();
    let compilation = build_path(
        &input,
        &executable,
        &[Emit::Hir, Emit::Mir, Emit::Ssa, Emit::Llvm],
        &ClangToolchain::default().with_optimization(optimization),
    )
    .unwrap_or_else(|errors| panic!("{source}\n{errors:#?}"));
    (compilation, executable)
}

fn run<I, S>(executable: &Path, args: I) -> Output
where
    I: IntoIterator<Item = S>,
    S: AsRef<OsStr>,
{
    Command::new(executable).args(args).output().unwrap()
}

fn rejected(directory: &Directory, source: &str) -> bool {
    let input = directory.0.join("rejected.ae");
    let executable = directory.0.join("rejected");
    fs::write(&input, source).unwrap();
    build_path(&input, &executable, &[], &ClangToolchain::default()).is_err()
}

#[allow(clippy::unicode_not_nfc)]
const SEQUENCE_SOURCE: &str = r#"package main;
import std.Process;
int main(){
  Array<string> values=std.Process.args();
  if(length(values)!=9){return 1;}
  if(values[0]!=""){return 2;}
  if(values[1]!="two words"){return 3;}
  if(values[2]!=":"){return 4;}
  if(values[3]!="tab\tline\n"){return 5;}
  if(values[4]!="áéí"){return 6;}
  if(values[5]!="é"){return 7;}
  if(values[6]!="😀"){return 8;}
  if(values[7]!="*.ae"){return 9;}
  if(byteLength(values[8])!=8192){return 10;}
  return 0;
}"#;

#[test]
fn posix_sequence_is_exact_at_o0_and_o2() {
    let arguments = [
        String::new(),
        "two words".to_owned(),
        ":".to_owned(),
        "tab\tline\n".to_owned(),
        "áéí".to_owned(),
        "e\u{301}".to_owned(),
        "😀".to_owned(),
        "*.ae".to_owned(),
        "x".repeat(8192),
    ];
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        let directory = Directory::new("sequence");
        let (_, executable) = build(&directory, SEQUENCE_SOURCE, optimization);
        let output = run(&executable, &arguments);
        assert_eq!(output.status.code(), Some(0), "{optimization:?}");
        assert!(output.stdout.is_empty());
        assert!(output.stderr.is_empty());
    }
}

#[test]
fn zero_one_and_multiple_calls_have_independent_owning_arrays() {
    let source = r#"package main;import std.Process;
Array<string> take(){Array<string> value=std.Process.args();return value;}
int main(){
  Array<string> first=std.Process.args();
  Array<string> second=take();
  if(length(first)!=length(second)){return 1;}
  if(length(first)==0){return 0;}
  if(first[0]!="original"||second[0]!="original"){return 2;}
  first[0]="changed";
  if(second[0]!="original"){return 3;}
  Array<string> third=std.Process.args();
  if(third[0]!="original"){return 4;}
  for(ref string item in third){if(*item=="impossible"){return 5;}}
  return int(length(third))-1;
}"#;
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        let directory = Directory::new("ownership");
        let (_, executable) = build(&directory, source, optimization);
        assert_eq!(
            run(&executable, std::iter::empty::<&str>()).status.code(),
            Some(0)
        );
        assert_eq!(run(&executable, ["original"]).status.code(), Some(0));
    }
}

#[test]
fn invalid_posix_bytes_throw_nominally_and_cleanup_partial_results() {
    let source = r"package main;import std.Process;
int main(){
  try{Array<string> values=std.Process.args();return int(length(values))+20;}
  catch(std.Process.InvalidArgumentEncodingException error){return 0;}
}";
    let invalid = [
        vec![0x80],
        vec![0xc0, 0x80],
        vec![0xe2, 0x82],
        vec![0xed, 0xa0, 0x80],
        vec![0xf4, 0x90, 0x80, 0x80],
    ];
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        let directory = Directory::new("invalid");
        let (_, executable) = build(&directory, source, optimization);
        for bytes in &invalid {
            let output = run(
                &executable,
                [
                    OsString::from("valid-prefix"),
                    OsString::from_vec(bytes.clone()),
                ],
            );
            assert_eq!(output.status.code(), Some(0), "{optimization:?} {bytes:x?}");
            assert!(output.stderr.is_empty());
        }
    }
}

#[test]
fn successful_result_is_dropped_during_later_unwind_and_snapshot_is_disposed() {
    let caught = r"package main;import std.Process;
class Later:Exception{public init(){}}
int fail(){throw Later();}
int main(){try{Array<string> values=std.Process.args();fail();return int(length(values));}catch(Later error){return 0;}}";
    let uncaught = r"package main;import std.Process;
class Later:Exception{public init(){}}
int main(){Array<string> values=std.Process.args();throw Later();}";
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        let directory = Directory::new("unwind");
        let (_, caught_executable) = build(&directory, caught, optimization);
        assert_eq!(run(&caught_executable, ["owned"]).status.code(), Some(0));
        let (_, uncaught_executable) = build(&directory, uncaught, optimization);
        let output = run(&uncaught_executable, ["owned"]);
        assert_eq!(output.status.code(), Some(70));
        assert_eq!(output.stderr, b"Unhandled main.Later\n", "{optimization:?}");
    }
}

#[test]
fn import_without_call_has_no_process_boundary_or_runtime() {
    let directory = Directory::new("reachability");
    let (unused, _) = build(
        &directory,
        "package main;import std.Process;int main(){return 0;}",
        OptimizationLevel::O0,
    );
    for forbidden in [
        "aether_process_snapshot",
        "aether_process_args",
        "aether_process_utf8",
        "InvalidArgumentEncodingException",
    ] {
        assert!(!unused.llvm.contains(forbidden), "unexpected {forbidden}");
    }
    assert!(unused.llvm.contains("define i32 @main()"));

    let (used, _) = build(
        &directory,
        "package main;import std.Process;int main(){Array<string> x=std.Process.args();return int(length(x));}",
        OptimizationLevel::O0,
    );
    assert!(used.llvm.contains("define i32 @main(i32 %argc, ptr %argv)"));
    assert!(used.llvm.contains("@aether_process_snapshot_init"));
    assert!(used.llvm.contains("@aether_process_snapshot_dispose"));
    assert!(used.dumps[&Emit::Hir].contains("std.Process"));
    assert!(used.dumps[&Emit::Mir].contains("Call"));
    assert!(used.dumps[&Emit::Ssa].contains("Call"));
    for phase in [Emit::Hir, Emit::Mir, Emit::Ssa] {
        let dump = &used.dumps[&phase];
        assert!(!dump.contains("ProcessOp"));
        assert!(!dump.contains("snapshot"));
        assert!(!dump.contains("argv"));
    }
}

#[test]
fn public_surface_is_canonical_typed_and_explicitly_imported() {
    let directory = Directory::new("surface");
    let alias = "package main;import std.Process as process;int main(){Array<string> x=process.args();return int(length(x));}";
    let (_, executable) = build(&directory, alias, OptimizationLevel::O0);
    assert_eq!(
        run(&executable, std::iter::empty::<&str>()).status.code(),
        Some(0)
    );

    for invalid in [
        "package main;int main(){Array<string> x=std.Process.args();return 0;}",
        "package main;import std.Process;int main(){std.Process.args(1);return 0;}",
        "package main;import std.Process;int main(){Array<int> x=std.Process.args();return 0;}",
        "package main;import System;int main(){return 0;}",
        "package main;import std.Process;int main(int argc){return argc;}",
    ] {
        assert!(
            rejected(&directory, invalid),
            "accepted invalid API: {invalid}"
        );
    }
}

#[test]
fn expense_tracker_fixture_dispatches_and_reuses_numeric_parsing() {
    let source = include_str!("../../../tests/modules/expense_tracker_process_args_v1/main.ae");
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        let directory = Directory::new("expense");
        let (compilation, executable) = build(&directory, source, optimization);
        for arguments in [
            vec!["ledger.alpt", "add", "42", "12.5", "food"],
            vec!["ledger.alpt", "list"],
            vec!["ledger.alpt", "summary"],
        ] {
            assert_eq!(
                run(&executable, arguments).status.code(),
                Some(0),
                "{optimization:?}"
            );
        }
        assert!(compilation.llvm.contains("aether_text_parse_int"));
        assert!(compilation.llvm.contains("aether_text_parse_double"));
        assert!(!compilation.llvm.contains("writeTextAtomic"));
        assert!(!compilation.llvm.contains("appendText"));
    }
}

#[test]
fn host_adapter_accepts_argc_zero_without_reading_argv() {
    let directory = Directory::new("argc-zero");
    let (compilation, _) = build(
        &directory,
        "package main;import std.Process;int main(){Array<string> x=std.Process.args();return int(length(x));}",
        OptimizationLevel::O0,
    );
    let injected = compilation.llvm.replace(
        "define i32 @main(i32 %argc, ptr %argv)",
        "define internal i32 @aether_host_main(i32 %argc, ptr %argv)",
    ) + "\ndefine i32 @main() {\nentry:\n  %status = call i32 @aether_host_main(i32 0, ptr null)\n  ret i32 %status\n}\n";
    let llvm = directory.0.join("argc-zero.ll");
    let executable = directory.0.join("argc-zero");
    fs::write(&llvm, injected).unwrap();
    let linked = Command::new("clang")
        .args(["-Wno-override-module", "-O0", "-x", "ir"])
        .arg(&llvm)
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
    assert_eq!(
        run(&executable, std::iter::empty::<&str>()).status.code(),
        Some(0)
    );
}

#[test]
#[allow(clippy::too_many_lines)]
fn ordinary_call_type_ownership_drop_and_unwind_corruptions_fail_verification() {
    let source = r#"class Later:Exception{public init(){}}
Array<string> capture(){return {"owned"};}
int fail(){throw Later();}
int main(){try{Array<string> values=capture();fail();return int(length(values));}catch(Later error){return 0;}}"#;
    let hir =
        analyze(parse_source(&SourceFile::new("process-contract.ae", source)).unwrap()).unwrap();
    let array_string = hir
        .types()
        .entries()
        .find_map(|(ty, data)| {
            matches!(data, TypeData::Array { element } if *element == TypeId::STRING).then_some(ty)
        })
        .unwrap();
    let properties = hir.types().properties(array_string).unwrap();
    assert!(!properties.is_copy);
    assert!(properties.is_relocatable);
    assert!(properties.is_storable);
    assert!(properties.needs_drop);

    let mir = lower_hir(hir);
    verify_mir(mir.clone()).unwrap();

    let capture = mir
        .signatures
        .iter()
        .find(|signature| signature.name == "capture")
        .unwrap()
        .id;
    let mut wrong_return = mir.clone();
    wrong_return.signatures[capture.0 as usize].return_type = TypeId::INT64;
    assert!(verify_mir(wrong_return).is_err());

    let mut wrong_owner = mir.clone();
    let function = wrong_owner
        .functions
        .iter_mut()
        .find(|function| {
            function.blocks.iter().any(|block| {
                block.instructions.iter().any(
                    |instruction| matches!(instruction.value, Rvalue::Call { callee, .. } if callee == capture),
                )
            })
        })
        .unwrap();
    let local = function
        .blocks
        .iter()
        .flat_map(|block| &block.instructions)
        .find_map(|instruction| {
            matches!(instruction.value, Rvalue::Call { callee, .. } if callee == capture).then(
                || match instruction.destination.base {
                    aether_middle::PlaceBase::Local(local) => local,
                    aether_middle::PlaceBase::Dereference { .. } => {
                        panic!("call result is a local")
                    }
                },
            )
        })
        .unwrap();
    function.locals[local.0 as usize].ty = TypeId::INT64;
    assert!(verify_mir(wrong_owner).is_err());

    let mut missing_drop = mir.clone();
    for block in &mut missing_drop.functions[missing_drop.entry.0 as usize].blocks {
        block
            .instructions
            .retain(|instruction| !matches!(instruction.value, Rvalue::Drop { .. }));
    }
    assert!(verify_mir(missing_drop).is_err());

    let mut double_drop = mir.clone();
    let entry_index = double_drop.entry.0 as usize;
    let duplicate = double_drop.functions[entry_index]
        .blocks
        .iter()
        .flat_map(|block| &block.instructions)
        .find(|instruction| matches!(instruction.value, Rvalue::Drop { .. }))
        .unwrap()
        .clone();
    double_drop.functions[entry_index].blocks[0]
        .instructions
        .push(duplicate);
    assert!(verify_mir(double_drop).is_err());

    let mut bad_edge = mir.clone();
    let throwing_call = bad_edge
        .functions
        .iter_mut()
        .flat_map(|function| &mut function.blocks)
        .flat_map(|block| &mut block.instructions)
        .find(|instruction| {
            instruction.unwind.is_some() && matches!(instruction.value, Rvalue::Call { .. })
        })
        .unwrap();
    throwing_call.unwind = None;
    assert!(verify_mir(bad_edge).is_err());

    let verified = verify_mir(mir).unwrap();
    let ssa = build_ssa(&verified);
    verify_ssa(ssa.clone()).unwrap();

    let mut wrong_ssa_return = ssa.clone();
    wrong_ssa_return.signatures[capture.0 as usize].return_type = TypeId::INT64;
    assert!(verify_ssa(wrong_ssa_return).is_err());

    let mut wrong_ssa_owner = ssa.clone();
    let call = wrong_ssa_owner
        .functions
        .iter_mut()
        .flat_map(|function| &mut function.blocks)
        .flat_map(|block| &mut block.instructions)
        .find(
            |instruction| matches!(instruction.op, SsaOp::Call { callee, .. } if callee == capture),
        )
        .unwrap();
    call.ty = TypeId::INT64;
    assert!(verify_ssa(wrong_ssa_owner).is_err());

    let mut missing_ssa_drop = ssa.clone();
    for block in &mut missing_ssa_drop.functions[missing_ssa_drop.entry.0 as usize].blocks {
        block
            .instructions
            .retain(|instruction| !matches!(instruction.op, SsaOp::Drop { .. }));
    }
    assert!(verify_ssa(missing_ssa_drop).is_err());

    let mut double_ssa_drop = ssa.clone();
    let entry_index = double_ssa_drop.entry.0 as usize;
    let duplicate = double_ssa_drop.functions[entry_index]
        .blocks
        .iter()
        .flat_map(|block| &block.instructions)
        .find(|instruction| matches!(instruction.op, SsaOp::Drop { .. }))
        .unwrap()
        .clone();
    double_ssa_drop.functions[entry_index].blocks[0]
        .instructions
        .push(duplicate);
    assert!(verify_ssa(double_ssa_drop).is_err());

    let mut bad_ssa_edge = ssa;
    let throwing_call = bad_ssa_edge
        .functions
        .iter_mut()
        .flat_map(|function| &mut function.blocks)
        .flat_map(|block| &mut block.instructions)
        .find(|instruction| {
            instruction.unwind.is_some() && matches!(instruction.op, SsaOp::Call { .. })
        })
        .unwrap();
    throwing_call.unwind = None;
    assert!(verify_ssa(bad_ssa_edge).is_err());
}
