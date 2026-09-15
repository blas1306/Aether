//! UNCAUGHT-EXCEPTION-DIAGNOSTICS-V1 native and ABI qualification.

use std::fs;
use std::io::Write;
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};

use aether_driver::{ClangToolchain, Emit, OptimizationLevel, build_path};

struct Directory(PathBuf);

impl Directory {
    fn new(label: &str) -> Self {
        static NEXT: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
        let path = std::env::temp_dir().join(format!(
            "aether-uncaught-v1-{label}-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, std::sync::atomic::Ordering::Relaxed)
        ));
        fs::create_dir(&path).unwrap();
        Self(path)
    }

    fn write(&self, relative: &str, bytes: &[u8]) -> PathBuf {
        let path = self.0.join(relative);
        fs::create_dir_all(path.parent().unwrap()).unwrap();
        fs::write(&path, bytes).unwrap();
        path
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
    let input = directory.write("main.ae", source.as_bytes());
    let executable = directory.0.join("program");
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

fn execute_llvm(directory: &Directory, llvm: &str) -> std::process::Output {
    let input = directory.write("injected.ll", llvm.as_bytes());
    let executable = directory.0.join("injected");
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
        "{}\n{llvm}",
        String::from_utf8_lossy(&linked.stderr)
    );
    run(&executable, b"")
}

fn qualify(source: &str, status: i32, stdout: &[u8], stderr: &[u8]) {
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        let directory = Directory::new("native");
        let (_, executable) = build(&directory, source, optimization);
        let output = run(&executable, b"");
        assert_eq!(output.status.code(), Some(status));
        assert_eq!(output.stdout, stdout);
        assert_eq!(output.stderr, stderr);
    }
}

#[test]
fn named_anonymous_dynamic_caught_rethrow_finally_and_channels_are_exact() {
    qualify(
        "package MyApp;open class ParseException:Exception{public init(){}}int main(){throw ParseException();}",
        70,
        b"",
        b"Unhandled MyApp.ParseException\n",
    );
    qualify(
        "open class ParseException:Exception{public init(){}}int main(){throw ParseException();}",
        70,
        b"",
        b"Unhandled ParseException\n",
    );
    qualify(
        "package MyApp;open class BaseException:Exception{public init(){}}class ParseException:BaseException{public init():base(){}}int main(){BaseException value=ParseException();throw value;}",
        70,
        b"",
        b"Unhandled MyApp.ParseException\n",
    );
    qualify(
        "open class ParseException:Exception{public init(){}}int main(){try{throw ParseException();}catch(ParseException error){return 0;}}",
        0,
        b"",
        b"",
    );
    qualify(
        "open class ParseException:Exception{public init(){}}int main(){try{throw ParseException();}catch(ParseException error){throw;}}",
        70,
        b"",
        b"Unhandled ParseException\n",
    );
    qualify(
        "open class ParseException:Exception{public init(){}}int main(){println(\"kept\");try{throw ParseException();}finally{int completed=1;completed=completed+1;}}",
        70,
        b"kept\n",
        b"Unhandled ParseException\n",
    );
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        let directory = Directory::new("finally-order");
        let (_, executable) = build(
            &directory,
            "open class ParseException:Exception{public init(){}}int main(){try{throw ParseException();}finally{int zero=0;int impossible=1/zero;}}",
            optimization,
        );
        let output = run(&executable, b"");
        assert_eq!(output.status.code(), None);
        assert!(output.stdout.is_empty());
        assert!(output.stderr.is_empty());
    }
    qualify("int main(){return 70;}", 70, b"", b"");
}

#[test]
fn std_file_and_encoding_exceptions_use_source_nominal_names() {
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        let missing_directory = Directory::new("missing");
        let missing = missing_directory.0.join("does-not-exist.txt");
        let source = format!(
            "import std.File;int main(){{string path=\"{}\";string value=std.File.readText(&path);return 0;}}",
            missing.display()
        );
        let (_, executable) = build(&missing_directory, &source, optimization);
        let output = run(&executable, b"");
        assert_eq!(output.status.code(), Some(70));
        assert!(output.stdout.is_empty());
        assert_eq!(output.stderr, b"Unhandled std.File.FileNotFoundException\n");

        let invalid_directory = Directory::new("encoding");
        let invalid = invalid_directory.write("invalid.txt", b"\xff");
        let source = format!(
            "import std.File;int main(){{string path=\"{}\";string value=std.File.readText(&path);return 0;}}",
            invalid.display()
        );
        let (_, executable) = build(&invalid_directory, &source, optimization);
        let output = run(&executable, b"");
        assert_eq!(output.status.code(), Some(70));
        assert!(output.stdout.is_empty());
        assert_eq!(
            output.stderr,
            b"Unhandled std.IO.InvalidTextEncodingException\n"
        );
    }
}

#[test]
fn descriptor_metadata_is_static_object_header_is_unchanged_and_eh_is_elided() {
    let directory = Directory::new("abi");
    let source =
        "open class ParseException:Exception{public init(){}}int main(){throw ParseException();}";
    let (compilation, _) = build(&directory, source, OptimizationLevel::O0);
    let llvm = &compilation.llvm;
    assert!(llvm.contains("private constant { ptr, i64 }"));
    assert!(llvm.contains("c\"\\50\\61\\72\\73\\65\\45\\78\\63\\65\\70\\74\\69\\6F\\6E\""));
    assert!(llvm.contains("getelementptr i8, ptr %object, i64 8"));
    assert!(llvm.contains("@aether_alloc(i64 16, i64 8)"));
    assert!(llvm.contains("%diagnostic_slot = getelementptr ptr, ptr %dynamic_descriptor, i64 1"));
    let reporter = llvm
        .split_once("define internal void @aether_report_unhandled")
        .unwrap()
        .1
        .split_once("\n}\n")
        .unwrap()
        .0;
    assert!(!reporter.contains("aether_alloc"));
    assert!(!reporter.contains("aether_string"));
    assert!(!reporter.contains("aether_io"));
    assert!(!llvm.contains("unhandled Aether exception"));

    let no_eh_directory = Directory::new("no-eh");
    let (no_eh, _) = build(
        &no_eh_directory,
        "int main(){return 0;}",
        OptimizationLevel::O2,
    );
    assert!(!no_eh.llvm.contains("@__cxa_"));
    assert!(!no_eh.llvm.contains("aether_report_unhandled"));
    assert!(!no_eh.llvm.contains("aether_diagnostic_type_"));
}

#[test]
fn reporter_retries_eintr_and_short_writes_then_tolerates_terminal_error() {
    let directory = Directory::new("writer");
    let source =
        "open class ParseException:Exception{public init(){}}int main(){throw ParseException();}";
    let (compilation, _) = build(&directory, source, OptimizationLevel::O0);
    let renamed = compilation
        .llvm
        .replace("@write(", "@aether_test_write(")
        .replace("declare i64 @aether_test_write(i32, ptr, i64)\n", "");
    let short_retry = format!(
        "{renamed}\ndeclare i64 @write(i32, ptr, i64)\n@aether_test_calls = internal global i64 0\ndefine i64 @aether_test_write(i32 %fd, ptr %data, i64 %length) nounwind {{\nentry:\n  %count = load i64, ptr @aether_test_calls\n  %next = add i64 %count, 1\n  store i64 %next, ptr @aether_test_calls\n  %first = icmp eq i64 %count, 0\n  br i1 %first, label %eintr, label %write\neintr:\n  %errno = call ptr @__errno_location()\n  store i32 4, ptr %errno\n  ret i64 -1\nwrite:\n  %long = icmp ugt i64 %length, 1\n  %amount = select i1 %long, i64 1, i64 %length\n  %result = call i64 @write(i32 %fd, ptr %data, i64 %amount)\n  ret i64 %result\n}}\n"
    );
    let output = execute_llvm(&directory, &short_retry);
    assert_eq!(output.status.code(), Some(70));
    assert!(output.stdout.is_empty());
    assert_eq!(output.stderr, b"Unhandled ParseException\n");

    let terminal_base = renamed.replace(
        "  call void @__cxa_end_catch()\n  ret i32 70",
        "  call void @__cxa_end_catch()\n  %error_balance = call i64 @aether_allocation_balance()\n  %error_balanced = icmp eq i64 %error_balance, 0\n  %error_status = select i1 %error_balanced, i32 70, i32 99\n  ret i32 %error_status",
    );
    let terminal = format!(
        "{terminal_base}\ndeclare i64 @write(i32, ptr, i64)\n@aether_test_calls = internal global i64 0\ndefine i64 @aether_test_write(i32 %fd, ptr %data, i64 %length) nounwind {{\nentry:\n  %count = load i64, ptr @aether_test_calls\n  store i64 1, ptr @aether_test_calls\n  %first = icmp eq i64 %count, 0\n  br i1 %first, label %prefix, label %fail\nprefix:\n  %result = call i64 @write(i32 %fd, ptr %data, i64 1)\n  ret i64 %result\nfail:\n  %errno = call ptr @__errno_location()\n  store i32 5, ptr %errno\n  ret i64 -1\n}}\n"
    );
    let output = execute_llvm(&directory, &terminal);
    assert_eq!(output.status.code(), Some(70));
    assert!(output.stdout.is_empty());
    assert_eq!(output.stderr, b"U");
}

#[test]
fn root_finishes_event_once_and_corrupt_metadata_is_fail_fast() {
    let directory = Directory::new("lifecycle");
    let source =
        "open class ParseException:Exception{public init(){}}int main(){throw ParseException();}";
    let (compilation, _) = build(&directory, source, OptimizationLevel::O0);
    assert_eq!(
        compilation
            .llvm
            .matches("call void @__cxa_end_catch()")
            .count(),
        1
    );
    let probed = compilation.llvm.replace(
        "  call void @__cxa_end_catch()\n  ret i32 70",
        "  call void @__cxa_end_catch()\n  %root_balance = call i64 @aether_allocation_balance()\n  %root_release = load i64, ptr @aether_object_release_count\n  %root_destroy = load i64, ptr @aether_object_destroy_count\n  %root_balance_ok = icmp eq i64 %root_balance, 0\n  %root_release_ok = icmp eq i64 %root_release, 1\n  %root_destroy_ok = icmp eq i64 %root_destroy, 1\n  %root_counts_ok = and i1 %root_release_ok, %root_destroy_ok\n  %root_ok = and i1 %root_balance_ok, %root_counts_ok\n  %root_status = select i1 %root_ok, i32 70, i32 99\n  ret i32 %root_status",
    );
    let output = execute_llvm(&directory, &probed);
    assert_eq!(output.status.code(), Some(70));
    assert_eq!(output.stderr, b"Unhandled ParseException\n");

    let diagnostic_line = compilation
        .llvm
        .lines()
        .find(|line| {
            line.starts_with("@aether_diagnostic_name_")
                && line.contains("\\50\\61\\72\\73\\65\\45\\78")
        })
        .unwrap();
    let id = diagnostic_line
        .strip_prefix("@aether_diagnostic_name_")
        .unwrap()
        .split_once(' ')
        .unwrap()
        .0;
    let corrupted =
        compilation
            .llvm
            .replacen(&format!("ptr @aether_diagnostic_type_{id}"), "ptr null", 1);
    let output = execute_llvm(&directory, &corrupted);
    assert_eq!(output.status.code(), None);
    assert!(output.stdout.is_empty());
    assert!(output.stderr.is_empty());
}
