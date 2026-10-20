//! TEXT-UTF8-BUILDER-V1 strict validation, publication, lowering and lifecycle qualification.

use std::fmt::Write as _;
use std::fs;
use std::path::{Path, PathBuf};
use std::process::{Command, Output};

use aether_driver::{ClangToolchain, Emit, OptimizationLevel, build_path};
use aether_frontend::{SourceFile, TypeId, analyze, parse_source};
use aether_middle::{Rvalue, build_ssa, lower_hir, verify_mir, verify_ssa};

struct Directory(PathBuf);

impl Directory {
    fn new(label: &str) -> Self {
        static NEXT: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
        let path = std::env::temp_dir().join(format!(
            "aether-text-utf8-builder-{label}-{}-{}",
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

fn run(executable: &Path) -> Output {
    Command::new(executable).output().unwrap()
}

fn execute_llvm(llvm: &str, optimization: OptimizationLevel) -> Output {
    let directory = Directory::new("instrumented");
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
    run(&executable)
}

fn require_string_counts(llvm: &str, allocations: u64, frees: u64) -> String {
    let replacement = format!(
        "  %utf8_allocs = load i64, ptr @aether_string_alloc_count\n  %utf8_frees = load i64, ptr @aether_string_free_count\n  %utf8_allocs_ok = icmp eq i64 %utf8_allocs, {allocations}\n  %utf8_frees_ok = icmp eq i64 %utf8_frees, {frees}\n  %utf8_counts_ok = and i1 %utf8_allocs_ok, %utf8_frees_ok\n  %utf8_program_ok = icmp eq i32 %process_status, 0\n  %utf8_ok = and i1 %utf8_counts_ok, %utf8_program_ok\n  %utf8_status = select i1 %utf8_ok, i32 0, i32 99\n  ret i32 %utf8_status"
    );
    llvm.replace("  ret i32 %process_status", &replacement)
}

fn rejected(directory: &Directory, source: &str) -> bool {
    let input = directory.0.join("rejected.ae");
    let executable = directory.0.join("rejected");
    fs::write(&input, source).unwrap();
    build_path(&input, &executable, &[], &ClangToolchain::default()).is_err()
}

fn byte_buffer(bytes: &[u8], length: usize, body: &str) -> String {
    let mut source = format!(
        "package main;import std.Text;int main(){{Buffer<uint8> bytes=Buffer<uint8>({},uint8(0));",
        bytes.len()
    );
    for (index, byte) in bytes.iter().enumerate() {
        write!(source, "bytes[{index}]=uint8({byte});").unwrap();
    }
    source.push_str(&body.replace("{length}", &length.to_string()));
    source.push('}');
    source
}

#[test]
fn positive_smoke_runs_at_o0_and_o2() {
    let source = include_str!("../../../tests/programs/text_utf8_builder_v1_smoke.ae");
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        let directory = Directory::new("positive");
        let (compilation, executable) = build(&directory, source, optimization);
        let output = run(&executable);
        assert_eq!(output.status.code(), Some(0), "{optimization:?}");
        assert!(output.stdout.is_empty());
        assert!(output.stderr.is_empty());
        assert!(compilation.llvm.contains("@aether_text_from_utf8_prefix"));
        assert!(compilation.llvm.contains("@aether_utf8_validate"));
        assert!(!compilation.llvm.contains("@aether_process_utf8"));
        assert!(!compilation.llvm.contains("@aether_io_utf8"));
        assert!(!compilation.llvm.contains("call ptr @aether_string_concat"));
    }
}

#[test]
fn strict_invalid_matrix_is_caught_and_buffer_remains_usable() {
    let mut invalid = vec![
        vec![0x80],
        vec![0xbf],
        vec![0xc0, 0x80],
        vec![0xc1, 0xbf],
        vec![0xc2],
        vec![0xe0],
        vec![0xe0, 0xa0],
        vec![0xf0],
        vec![0xf0, 0x90],
        vec![0xf0, 0x90, 0x80],
        vec![0xc2, 0x41],
        vec![0xe1, 0x80, 0x41],
        vec![0xf1, 0x80, 0x80, 0x41],
        vec![0xe0, 0x80, 0x80],
        vec![0xf0, 0x80, 0x80, 0x80],
        vec![0xed, 0xa0, 0x80],
        vec![0xed, 0xbf, 0xbf],
        vec![0xf4, 0x90, 0x80, 0x80],
    ];
    invalid.extend((0xf5..=0xff).map(|lead| vec![lead, 0x80, 0x80, 0x80]));
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        for bytes in &invalid {
            let directory = Directory::new("invalid");
            let first = bytes[0];
            let body = format!(
                "try{{string value=std.Text.fromUtf8(&bytes,{{length}});return int(byteLength(value))+40;}}catch(std.Text.InvalidUtf8Exception error){{if(bytes[0]!=uint8({first})){{return 2;}}return 0;}}"
            );
            let source = byte_buffer(bytes, bytes.len(), &body);
            let (_, executable) = build(&directory, &source, optimization);
            assert_eq!(
                run(&executable).status.code(),
                Some(0),
                "{optimization:?} {bytes:x?}"
            );
        }
    }
}

#[test]
fn prefix_boundary_and_bounds_precedence_are_exact() {
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        let directory = Directory::new("prefix");
        let valid_prefix = byte_buffer(
            &[b'A', 0xff, 0x80],
            1,
            "string value=std.Text.fromUtf8(&bytes,{length});if(value!=\"A\"){return 1;}return 0;",
        );
        let (_, executable) = build(&directory, &valid_prefix, optimization);
        assert_eq!(run(&executable).status.code(), Some(0));

        let cut = byte_buffer(
            &[0xe2, 0x82, 0xac],
            2,
            "try{string value=std.Text.fromUtf8(&bytes,{length});return 2;}catch(std.Text.InvalidUtf8Exception error){return 0;}",
        );
        let (_, executable) = build(&directory, &cut, optimization);
        assert_eq!(run(&executable).status.code(), Some(0));

        let bounds = byte_buffer(
            b"A",
            2,
            "try{string value=std.Text.fromUtf8(&bytes,{length});return 3;}catch(std.Text.InvalidUtf8Exception error){return 4;}",
        );
        let (_, executable) = build(&directory, &bounds, optimization);
        assert!(!run(&executable).status.success());
    }
}

#[test]
fn public_surface_is_typed_imported_and_not_spelling_privileged() {
    let directory = Directory::new("surface");
    let alias = "package main;import std.Text as text;int main(){Buffer<uint8>b=Buffer<uint8>(1,uint8(65));string s=text.fromUtf8(&b,1);if(s==\"A\"){return 0;}return 1;}";
    let (_, executable) = build(&directory, alias, OptimizationLevel::O0);
    assert_eq!(run(&executable).status.code(), Some(0));

    for invalid in [
        "package main;int main(){Buffer<uint8>b=Buffer<uint8>(0,uint8(0));string s=std.Text.fromUtf8(&b,0);return 0;}",
        "package main;import std.Text;int main(){Buffer<int>b=Buffer<int>(1,0);string s=std.Text.fromUtf8(&b,1);return 0;}",
        "package main;import std.Text;int main(){Buffer<uint8>b=Buffer<uint8>(1,uint8(0));string s=std.Text.fromUtf8(b,1);return 0;}",
        "package main;import std.Text;int main(){Buffer<uint8>b=Buffer<uint8>(1,uint8(0));string s=std.Text.fromUtf8(&b,-1);return 0;}",
        "package main;import std.Text;int main(){Buffer<uint8>b=Buffer<uint8>(1,uint8(0));int s=std.Text.fromUtf8(&b,1);return s;}",
        "package main;import std.Text;int main(){Buffer<uint8>b=Buffer<uint8>(0,uint8(0));string s=std.Text.fromUtf8Unchecked(&b,0);return int(byteLength(s));}",
        "package main;import std.Text;int main(){Buffer<uint8>b=Buffer<uint8>(0,uint8(0));string s=std.Text.aether_string_from_buffer(&b,0);return int(byteLength(s));}",
    ] {
        assert!(
            rejected(&directory, invalid),
            "accepted invalid API: {invalid}"
        );
    }

    let homonym_directory = Directory::new("homonym");
    let homonym = "package main;string fromUtf8(ref Buffer<uint8>b,usize n){return \"local\";}int main(){Buffer<uint8>b=Buffer<uint8>(0,uint8(0));string s=fromUtf8(&b,0);if(s==\"local\"){return 0;}return 1;}";
    let (compilation, executable) = build(&homonym_directory, homonym, OptimizationLevel::O0);
    assert_eq!(run(&executable).status.code(), Some(0));
    assert!(!compilation.llvm.contains("aether_text_from_utf8_prefix"));
}

#[test]
fn reachability_and_ordinary_call_ir_are_explicit() {
    let directory = Directory::new("reachability");
    let (unused, _) = build(
        &directory,
        "package main;import std.Text;class Later:Exception{public init(){}}int main(){try{throw Later();}catch(Later error){return 0;}}",
        OptimizationLevel::O0,
    );
    for forbidden in [
        "aether_text_from_utf8_prefix",
        "aether_utf8_validate",
        "InvalidUtf8Exception",
    ] {
        assert!(
            !unused.llvm.contains(forbidden),
            "unexpected {forbidden}: {}",
            unused
                .llvm
                .lines()
                .filter(|line| line.contains(forbidden))
                .collect::<Vec<_>>()
                .join(" | ")
        );
    }

    let source = "package main;import std.Text;class Later:Exception{public init(){}}int fail(){throw Later();}int main(){Buffer<uint8>b=Buffer<uint8>(1,uint8(65));try{string s=std.Text.fromUtf8(&b,1);fail();return int(byteLength(s));}catch(Later error){return 0;}}";
    let (used, executable) = build(&directory, source, OptimizationLevel::O0);
    assert_eq!(run(&executable).status.code(), Some(0));
    for phase in [Emit::Hir, Emit::Mir, Emit::Ssa] {
        let dump = &used.dumps[&phase];
        assert!(dump.contains("fromUtf8"), "{phase:?}");
        assert!(dump.contains("Call"), "{phase:?}");
        assert!(!dump.contains("FromUtf8"), "{phase:?}");
    }
    assert!(used.dumps[&Emit::Hir].contains("CallScopedSharedBorrow"));
    assert!(used.dumps[&Emit::Mir].contains("EndBorrow"));
    assert!(used.dumps[&Emit::Mir].contains("unwind"));
    assert!(used.dumps[&Emit::Ssa].contains("Drop"));
    for artifact in used.dumps.values().chain(std::iter::once(&used.llvm)) {
        assert!(!artifact.contains("graphics"));
        assert!(!artifact.contains("graphics.svg"));
    }
    assert_eq!(
        used.llvm
            .matches("define internal i1 @aether_utf8_validate")
            .count(),
        1
    );
}

#[test]
fn allocation_publication_and_final_free_counts_are_exact() {
    let cases = [
        (
            "package main;import std.Text;int main(){Buffer<uint8>b=Buffer<uint8>(3,uint8(255));string s=std.Text.fromUtf8(&b,0);return int(byteLength(s));}",
            0,
            0,
        ),
        (
            "package main;import std.Text;int main(){Buffer<uint8>b=Buffer<uint8>(4,uint8(120));string s=std.Text.fromUtf8(&b,4);if(s==\"xxxx\"){return 0;}return 1;}",
            1,
            1,
        ),
        (
            "package main;import std.Text;int main(){Buffer<uint8>b=Buffer<uint8>(2,uint8(128));try{string s=std.Text.fromUtf8(&b,2);return 1;}catch(std.Text.InvalidUtf8Exception error){return 0;}}",
            0,
            0,
        ),
    ];
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        for (source, allocations, frees) in cases {
            let directory = Directory::new("counts");
            let (compilation, _) = build(&directory, source, optimization);
            let instrumented = require_string_counts(&compilation.llvm, allocations, frees);
            assert_eq!(
                execute_llvm(&instrumented, optimization).status.code(),
                Some(0),
                "{optimization:?}: {source}"
            );
            let validator = compilation
                .llvm
                .split("define internal i1 @aether_utf8_validate")
                .nth(1)
                .unwrap()
                .split("\n}\n")
                .next()
                .unwrap();
            assert!(!validator.contains("@aether_alloc"));
            assert!(!validator.contains("@aether_string_"));

            let boundary = compilation
                .llvm
                .split("define internal { i1, ptr } @aether_text_from_utf8_prefix")
                .nth(1)
                .unwrap()
                .split("\n}\n")
                .next()
                .unwrap();
            let bounds = boundary
                .find("icmp ule i64 %length, %buffer_length")
                .unwrap();
            let validation = boundary.find("call i1 @aether_utf8_validate").unwrap();
            let publication = boundary
                .find("call ptr @aether_string_from_buffer")
                .unwrap();
            assert!(bounds < validation);
            assert!(validation < publication);
            assert_eq!(boundary.matches("@aether_utf8_validate").count(), 1);
            assert_eq!(boundary.matches("@aether_string_from_buffer").count(), 1);
            assert!(!boundary.contains("load i8"));
            assert!(!boundary.contains("@aether_string_allocate"));
            assert!(
                compilation
                    .llvm
                    .contains("@llvm.uadd.with.overflow.i64(i64 %length, i64 25)")
            );
        }
    }
}

#[test]
fn uncaught_error_is_nominal_and_shared_validator_is_singleton() {
    let uncaught = "package main;import std.Text;int main(){Buffer<uint8>b=Buffer<uint8>(1,uint8(255));string s=std.Text.fromUtf8(&b,1);return int(byteLength(s));}";
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        let directory = Directory::new("uncaught");
        let (_, executable) = build(&directory, uncaught, optimization);
        let output = run(&executable);
        assert_eq!(output.status.code(), Some(70));
        assert_eq!(output.stderr, b"Unhandled std.Text.InvalidUtf8Exception\n");
    }

    let combined = r"package main;import std.Text;import std.Process;import std.IO;
int main(){
 Array<string> args=std.Process.args();
 Buffer<uint8>b=Buffer<uint8>(1,uint8(65));string s=std.Text.fromUtf8(&b,1);
 match(std.IO.readLine()){std.IO.ReadLineResult.Line(line)=>{} std.IO.ReadLineResult.End=>{}}
 return int(length(args))+int(byteLength(s))-1;
}";
    let directory = Directory::new("shared");
    let (compilation, executable) = build(&directory, combined, OptimizationLevel::O0);
    assert_eq!(run(&executable).status.code(), Some(0));
    assert_eq!(
        compilation
            .llvm
            .matches("define internal i1 @aether_utf8_validate")
            .count(),
        1
    );
    assert!(!compilation.llvm.contains("aether_process_utf8"));
    assert!(!compilation.llvm.contains("aether_io_utf8"));
}

#[test]
#[allow(clippy::too_many_lines)]
fn ordinary_call_borrow_owner_drop_and_unwind_corruptions_fail_closed() {
    let source = r#"class Later:Exception{public init(){}}
string publish(ref Buffer<uint8> bytes,usize used){return "x";}
int fail(){throw Later();}
int main(){Buffer<uint8>b=Buffer<uint8>(1,uint8(65));try{string s=publish(&b,1);fail();return int(byteLength(s));}catch(Later error){return 0;}}"#;
    let hir =
        analyze(parse_source(&SourceFile::new("utf8-call-contract.ae", source)).unwrap()).unwrap();
    let mir = lower_hir(hir);
    verify_mir(mir.clone()).unwrap();
    let publish = mir
        .signatures
        .iter()
        .find(|signature| signature.name == "publish")
        .unwrap()
        .id;

    let mut wrong_return = mir.clone();
    wrong_return.signatures[publish.0 as usize].return_type = TypeId::INT64;
    assert!(verify_mir(wrong_return).is_err());

    let mut wrong_operand = mir.clone();
    let call = wrong_operand
        .functions
        .iter_mut()
        .flat_map(|function| &mut function.blocks)
        .flat_map(|block| &mut block.instructions)
        .find(|instruction| {
            matches!(instruction.value, Rvalue::Call { callee, .. } if callee == publish)
        })
        .unwrap();
    let Rvalue::Call { args, .. } = &mut call.value else {
        unreachable!()
    };
    args[1] = aether_middle::Operand::Bool(false);
    assert!(verify_mir(wrong_operand).is_err());

    let mut wrong_borrow = mir.clone();
    let borrow = wrong_borrow
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
    borrow.pointee_type = TypeId::STRING;
    assert!(verify_mir(wrong_borrow).is_err());

    let mut missing_drop = mir.clone();
    for block in &mut missing_drop.functions[missing_drop.entry.0 as usize].blocks {
        block
            .instructions
            .retain(|instruction| !matches!(instruction.value, Rvalue::Drop { .. }));
    }
    assert!(verify_mir(missing_drop).is_err());

    let mut missing_unwind = mir.clone();
    let call = missing_unwind
        .functions
        .iter_mut()
        .flat_map(|function| &mut function.blocks)
        .flat_map(|block| &mut block.instructions)
        .find(|instruction| {
            instruction.unwind.is_some()
                && matches!(instruction.value, Rvalue::Call { callee, .. } if callee == publish)
        })
        .unwrap();
    call.unwind = None;
    assert!(verify_mir(missing_unwind).is_err());

    let verified = verify_mir(mir).unwrap();
    let ssa = build_ssa(&verified);
    verify_ssa(ssa.clone()).unwrap();

    let mut wrong_ssa_return = ssa.clone();
    wrong_ssa_return.signatures[publish.0 as usize].return_type = TypeId::INT64;
    assert!(verify_ssa(wrong_ssa_return).is_err());

    let mut missing_ssa_unwind = ssa.clone();
    let call = missing_ssa_unwind
        .functions
        .iter_mut()
        .flat_map(|function| &mut function.blocks)
        .flat_map(|block| &mut block.instructions)
        .find(|instruction| {
            instruction.unwind.is_some()
                && matches!(instruction.op, aether_middle::SsaOp::Call { callee, .. } if callee == publish)
        })
        .unwrap();
    call.unwind = None;
    assert!(verify_ssa(missing_ssa_unwind).is_err());
}
