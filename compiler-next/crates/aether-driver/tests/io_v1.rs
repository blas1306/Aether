//! IO-V1 UTF-8 console and whole-text-file qualification.

use std::fs;
use std::io::Write;
use std::os::unix::fs::PermissionsExt;
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};

use aether_driver::{
    ClangToolchain, Emit, OptimizationLevel, build_path, compile_source_with_optimization,
};
use aether_frontend::SourceFile;

struct Directory(PathBuf);

impl Directory {
    fn new() -> Self {
        static NEXT: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
        let path = std::env::temp_dir().join(format!(
            "aether-io-v1-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, std::sync::atomic::Ordering::Relaxed)
        ));
        fs::create_dir(&path).unwrap();
        Self(path)
    }
}

impl Drop for Directory {
    fn drop(&mut self) {
        let _ = fs::set_permissions(&self.0, fs::Permissions::from_mode(0o700));
        fs::remove_dir_all(&self.0).unwrap();
    }
}

fn build(
    directory: &Directory,
    source: &str,
    optimization: OptimizationLevel,
) -> (aether_driver::Compilation, PathBuf) {
    let input = directory.0.join("main.ae");
    let executable = directory.0.join("program");
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

fn run(executable: &Path, stdin: &[u8]) -> std::process::Output {
    let mut child = Command::new(executable)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .unwrap();
    child.stdin.take().unwrap().write_all(stdin).unwrap();
    child.wait_with_output().unwrap()
}

fn execute_llvm(directory: &Directory, llvm: &str, stdin: &[u8]) -> std::process::Output {
    let input = directory.0.join("injected.ll");
    let executable = directory.0.join("injected");
    fs::write(&input, llvm).unwrap();
    let linked = Command::new("clang")
        .args(["-Wno-override-module", "-O0", "-x", "ir"])
        .arg(&input)
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
    run(&executable, stdin)
}

#[test]
fn read_line_distinguishes_end_empty_crlf_and_unterminated_final_line() {
    let source = r#"package main;
import std.IO;
void show(){
  std.IO.ReadLineResult result=std.IO.readLine();
  match(result){
    std.IO.ReadLineResult.Line(line)=>{print("[");print(line);println("]");}
    std.IO.ReadLineResult.End=>{println("END");}
  }
}

int main(){show();show();show();show();show();show();return 0;}"#;
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        let directory = Directory::new();
        let (_, executable) = build(&directory, source, optimization);
        let output = run(&executable, b"a\n\r\n\rx\n\nlast");
        assert_eq!(output.status.code(), Some(0));
        assert_eq!(output.stdout, b"[a]\n[]\n[\rx]\n[]\n[last]\nEND\n");
        assert!(output.stderr.is_empty());
    }
}

#[test]
fn general_void_dependency_is_nonstorable_and_supports_effect_calls() {
    let valid = "void first(){return;}void second(){}int main(){first();second();return 0;}";
    compile_source_with_optimization(
        &SourceFile::new("void.ae", valid),
        &[Emit::Hir, Emit::Mir, Emit::Ssa],
        OptimizationLevel::O0,
    )
    .unwrap();
    for invalid in [
        "void f(){}int main(){void value=f();return 0;}",
        "struct S{void value;}int main(){return 0;}",
        "enum E{Value(void)}int main(){return 0;}",
        "int f(void value){return 0;}int main(){return 0;}",
        "void f(){return 1;}int main(){return 0;}",
        "int f(){return;}int main(){return 0;}",
    ] {
        assert!(
            compile_source_with_optimization(
                &SourceFile::new("bad_void.ae", invalid),
                &[],
                OptimizationLevel::O0,
            )
            .is_err(),
            "accepted invalid void program: {invalid}"
        );
    }
}

#[test]
fn stderr_is_byte_exact_and_uses_exactly_one_requested_lf() {
    let source = r#"package main;import std.IO;
int main(){string a="A";string empty="";std.IO.eprint(&a);std.IO.eprintln(&empty);return 0;}"#;
    let directory = Directory::new();
    let (_, executable) = build(&directory, source, OptimizationLevel::O0);
    let output = run(&executable, b"");
    assert_eq!(output.status.code(), Some(0));
    assert!(output.stdout.is_empty());
    assert_eq!(output.stderr, b"A\n");
}

#[test]
fn read_line_accepts_utf8_one_through_four_bytes_and_nul() {
    let source = r"package main;import std.IO;
int main(){std.IO.ReadLineResult value=std.IO.readLine();match(value){std.IO.ReadLineResult.Line(line)=>{print(line);}std.IO.ReadLineResult.End=>{return 3;}}return 0;}";
    let directory = Directory::new();
    let (_, executable) = build(&directory, source, OptimizationLevel::O0);
    let content = b"A\0\xc2\xa2\xe2\x82\xac\xf0\x9f\x98\x80";
    let mut stdin = content.to_vec();
    stdin.push(b'\n');
    let output = run(&executable, &stdin);
    assert_eq!(output.status.code(), Some(0));
    assert_eq!(output.stdout, content);
}

#[test]
fn read_and_write_text_preserve_utf8_nul_bom_and_newlines_and_truncate() {
    let directory = Directory::new();
    let input = directory.0.join("input.txt");
    let output_path = directory.0.join("output.txt");
    let created_path = directory.0.join("created.txt");
    let bytes = b"\xef\xbb\xbfuno\0\r\ndos\n\xf0\x9f\x98\x80";
    fs::write(&input, bytes).unwrap();
    fs::write(&output_path, b"a much longer previous value").unwrap();
    let source = format!(
        "package main;import std.File;int main(){{string input=\"{}\";string output=\"{}\";string created=\"{}\";string value=std.File.readText(&input);std.File.writeText(&output,&value);std.File.writeText(&created,&value);return 0;}}",
        input.display(),
        output_path.display(),
        created_path.display()
    );
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        let (_, executable) = build(&directory, &source, optimization);
        let result = run(&executable, b"");
        assert_eq!(result.status.code(), Some(0), "{optimization:?}");
        assert_eq!(fs::read(&output_path).unwrap(), bytes);
        assert_eq!(fs::read(&created_path).unwrap(), bytes);
    }

    let empty_source = format!(
        "package main;import std.File;int main(){{string path=\"{}\";string value=\"\";std.File.writeText(&path,&value);string empty=std.File.readText(&path);return int(byteLength(empty));}}",
        output_path.display()
    );
    let (_, executable) = build(&directory, &empty_source, OptimizationLevel::O0);
    assert_eq!(run(&executable, b"").status.code(), Some(0));
    assert!(fs::read(&output_path).unwrap().is_empty());
}

#[test]
fn invalid_utf8_is_nominal_and_read_line_recovers_after_consumed_line() {
    let source = r#"package main;import std.IO;
int main(){
  try{std.IO.ReadLineResult bad=std.IO.readLine();}
  catch(std.IO.InvalidTextEncodingException error){string marker="bad";std.IO.eprintln(&marker);}
  std.IO.ReadLineResult next=std.IO.readLine();
  match(next){std.IO.ReadLineResult.Line(line)=>{std.IO.eprintln(&line);}std.IO.ReadLineResult.End=>{return 4;}}
  return 0;
}"#;
    let directory = Directory::new();
    let (_, executable) = build(&directory, source, OptimizationLevel::O0);
    let output = run(&executable, b"\xff\nnext\n");
    assert_eq!(output.status.code(), Some(0));
    assert_eq!(output.stderr, b"bad\nnext\n");
}

#[test]
fn file_errors_match_nominally_and_embedded_nul_never_reaches_open() {
    let directory = Directory::new();
    let missing = directory.0.join("missing.txt");
    let source = format!(
        "package main;import std.IO;import std.File;int main(){{string path=\"{}\";try{{string value=std.File.readText(&path);}}catch(std.File.FileNotFoundException error){{return 0;}}catch(std.IO.IOException error){{return 2;}}return 3;}}",
        missing.display()
    );
    let (_, executable) = build(&directory, &source, OptimizationLevel::O0);
    assert_eq!(run(&executable, b"").status.code(), Some(0));

    let nul_source = r#"package main;import std.IO;import std.File;
int main(){string path="bad\0path";try{string value=std.File.readText(&path);}catch(std.IO.IOException error){return 0;}return 3;}"#;
    let (_, executable) = build(&directory, nul_source, OptimizationLevel::O0);
    assert_eq!(run(&executable, b"").status.code(), Some(0));
}

#[test]
fn invalid_file_utf8_and_permission_are_distinct_nominal_failures() {
    let directory = Directory::new();
    let invalid = directory.0.join("invalid.txt");
    fs::write(&invalid, b"ok\xff").unwrap();
    let denied = directory.0.join("denied.txt");
    fs::write(&denied, b"secret").unwrap();
    fs::set_permissions(&denied, fs::Permissions::from_mode(0o000)).unwrap();
    let source = format!(
        "package main;import std.IO;import std.File;int main(){{string invalid=\"{}\";try{{string value=std.File.readText(&invalid);}}catch(std.IO.InvalidTextEncodingException error){{string denied=\"{}\";try{{string value=std.File.readText(&denied);}}catch(std.File.PermissionDeniedException permission){{return 0;}}catch(std.IO.IOException io){{return 2;}}}}return 3;}}",
        invalid.display(),
        denied.display()
    );
    let (_, executable) = build(&directory, &source, OptimizationLevel::O0);
    assert_eq!(run(&executable, b"").status.code(), Some(0));
    fs::set_permissions(&denied, fs::Permissions::from_mode(0o600)).unwrap();
}

#[test]
fn reachability_and_effects_remain_on_ordinary_calls() {
    let directory = Directory::new();
    let (unused, _) = build(
        &directory,
        "package main;import std.IO;import std.File;int main(){return 0;}",
        OptimizationLevel::O0,
    );
    assert!(!unused.llvm.contains("@aether_io_read_line"));
    assert!(!unused.llvm.contains("@aether_io_read_text"));
    assert!(!unused.llvm.contains("@aether_io_write_text"));
    assert!(!unused.llvm.contains("@aether_throw"));
    assert!(!unused.llvm.contains("@aether_descriptor_"));

    let read_source = format!(
        "package main;import std.File;int main(){{string path=\"{}\";string value=std.File.readText(&path);return 0;}}",
        directory.0.join("empty.txt").display()
    );
    fs::write(directory.0.join("empty.txt"), b"").unwrap();
    let (read_only, _) = build(&directory, &read_source, OptimizationLevel::O0);
    assert!(read_only.llvm.contains("@aether_io_read_text"));
    assert!(!read_only.llvm.contains("@aether_io_read_line"));
    for phase in [Emit::Hir, Emit::Mir, Emit::Ssa] {
        let dump = &read_only.dumps[&phase];
        assert!(dump.contains("readText"));
        assert!(!dump.contains("FileOp"));
        assert!(!dump.contains("IOOp"));
    }
}

#[test]
fn core_stdout_failure_uses_io_exception_without_source_import() {
    let directory = Directory::new();
    let source = "package main;int main(){println(\"x\");return 0;}";
    let (compilation, executable) = build(&directory, source, OptimizationLevel::O0);
    assert!(compilation.llvm.contains("@aether_io_stdout"));
    assert!(compilation.llvm.contains("call void @aether_throw"));
    let status = Command::new("sh")
        .arg("-c")
        .arg("exec 1>&-; exec \"$1\"")
        .arg("sh")
        .arg(executable)
        .status()
        .unwrap();
    assert_eq!(status.code(), Some(70));
}

#[test]
fn injected_eintr_short_zero_progress_and_prefix_failure_follow_contract() {
    let directory = Directory::new();
    let source = r#"package main;import std.IO;
int main(){string value="ABC";try{std.IO.eprintln(&value);}catch(std.IO.IOException error){return 7;}return 0;}"#;
    let (compilation, _) = build(&directory, source, OptimizationLevel::O0);

    let renamed = compilation
        .llvm
        .replace("@write(", "@aether_test_write(")
        .replace("declare i64 @aether_test_write(i32, ptr, i64)\n", "");
    let short_retry = format!(
        "{renamed}\ndeclare i64 @write(i32, ptr, i64)\n@aether_test_calls = internal global i64 0\ndefine i64 @aether_test_write(i32 %fd, ptr %data, i64 %length) {{\nentry:\n  %count = load i64, ptr @aether_test_calls\n  %next = add i64 %count, 1\n  store i64 %next, ptr @aether_test_calls\n  %first = icmp eq i64 %count, 0\n  br i1 %first, label %eintr, label %write\neintr:\n  %errno = call ptr @__errno_location()\n  store i32 4, ptr %errno\n  ret i64 -1\nwrite:\n  %long = icmp ugt i64 %length, 1\n  %amount = select i1 %long, i64 1, i64 %length\n  %result = call i64 @write(i32 %fd, ptr %data, i64 %amount)\n  ret i64 %result\n}}\n"
    );
    let output = execute_llvm(&directory, &short_retry, b"");
    assert_eq!(output.status.code(), Some(0));
    assert_eq!(output.stderr, b"ABC\n");

    let zero = format!(
        "{renamed}\ndefine i64 @aether_test_write(i32 %fd, ptr %data, i64 %length) {{ ret i64 0 }}\n"
    );
    assert_eq!(execute_llvm(&directory, &zero, b"").status.code(), Some(7));

    let prefix = format!(
        "{renamed}\ndeclare i64 @write(i32, ptr, i64)\n@aether_prefix_calls = internal global i64 0\ndefine i64 @aether_test_write(i32 %fd, ptr %data, i64 %length) {{\nentry:\n  %count = load i64, ptr @aether_prefix_calls\n  %first = icmp eq i64 %count, 0\n  store i64 1, ptr @aether_prefix_calls\n  br i1 %first, label %prefix, label %fail\nprefix:\n  %result = call i64 @write(i32 %fd, ptr %data, i64 1)\n  ret i64 %result\nfail:\n  %errno = call ptr @__errno_location()\n  store i32 5, ptr %errno\n  ret i64 -1\n}}\n"
    );
    let output = execute_llvm(&directory, &prefix, b"");
    assert_eq!(output.status.code(), Some(7));
    assert_eq!(output.stderr, b"A");
}

#[test]
fn injected_read_eintr_is_retried_without_publishing_partial_state() {
    let directory = Directory::new();
    let source = r"package main;import std.IO;
int main(){std.IO.ReadLineResult value=std.IO.readLine();match(value){std.IO.ReadLineResult.Line(line)=>{println(line);}std.IO.ReadLineResult.End=>{return 3;}}return 0;}";
    let (compilation, _) = build(&directory, source, OptimizationLevel::O0);
    let renamed = compilation
        .llvm
        .replace("@read(", "@aether_test_read(")
        .replace("declare i64 @aether_test_read(i32, ptr, i64)\n", "");
    let injected = format!(
        "{renamed}\ndeclare i64 @read(i32, ptr, i64)\n@aether_read_calls = internal global i64 0\ndefine i64 @aether_test_read(i32 %fd, ptr %data, i64 %length) {{\nentry:\n  %count = load i64, ptr @aether_read_calls\n  store i64 1, ptr @aether_read_calls\n  %first = icmp eq i64 %count, 0\n  br i1 %first, label %eintr, label %read\neintr:\n  %errno = call ptr @__errno_location()\n  store i32 4, ptr %errno\n  ret i64 -1\nread:\n  %result = call i64 @read(i32 %fd, ptr %data, i64 %length)\n  ret i64 %result\n}}\n"
    );
    let output = execute_llvm(&directory, &injected, b"retry\n");
    assert_eq!(output.status.code(), Some(0));
    assert_eq!(output.stdout, b"retry\n");
}
