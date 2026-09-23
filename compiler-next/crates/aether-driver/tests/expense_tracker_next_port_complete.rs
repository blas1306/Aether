//! End-to-end qualification for the complete compiler-next Expense Tracker port.

use std::{
    fs,
    os::unix::fs::MetadataExt,
    path::{Path, PathBuf},
    process::{Command, Output},
};

use aether_driver::{
    ClangToolchain, Compilation, CompilationSession, Emit, OptimizationLevel,
    compile_session_with_optimization,
};

struct Directory(PathBuf);

impl Directory {
    fn new(label: &str) -> Self {
        static NEXT: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
        let path = std::env::temp_dir().join(format!(
            "aether-expense-port-{label}-{}-{}",
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

fn entry() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../../examples/expense_tracker/main.ae")
}

fn compile(optimization: OptimizationLevel) -> Compilation {
    compile_session_with_optimization(
        CompilationSession::discover(&entry()).unwrap(),
        &[Emit::Hir, Emit::Mir, Emit::Ssa, Emit::Llvm],
        optimization,
    )
    .unwrap_or_else(|errors| panic!("{optimization:?}: {errors:#?}"))
}

fn link(llvm: &str, path: &Path, optimization: OptimizationLevel) {
    ClangToolchain::default()
        .with_optimization(optimization)
        .link_executable(llvm, path)
        .unwrap();
}

fn run(executable: &Path, arguments: &[&str]) -> Output {
    Command::new(executable).args(arguments).output().unwrap()
}

fn assert_status(output: &Output, expected: i32) {
    assert_eq!(
        output.status.code(),
        Some(expected),
        "stdout={}\nstderr={}",
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr)
    );
}

#[allow(clippy::too_many_lines)]
fn exercise_cli(optimization: OptimizationLevel) {
    let directory = Directory::new(match optimization {
        OptimizationLevel::O0 => "o0",
        OptimizationLevel::O2 => "o2",
    });
    let compilation = compile(optimization);
    let executable = directory.0.join("expense");
    link(&compilation.llvm, &executable, optimization);
    let ledger = directory.0.join("ledger.alpt");
    let ledger_text = ledger.to_str().unwrap();

    let missing = run(&executable, &[ledger_text, "list"]);
    assert_status(&missing, 0);
    assert!(missing.stdout.is_empty());
    assert!(!ledger.exists());

    for arguments in [
        vec![ledger_text, "add"],
        vec![ledger_text, "summary", "extra"],
        vec![ledger_text, "unknown"],
        vec![ledger_text, "add", "expense", "x", "1", "c", "d", "date"],
        vec![
            ledger_text,
            "add",
            "expense",
            "999999999999999999999999999999",
            "1",
            "c",
            "d",
            "date",
        ],
        vec![ledger_text, "add", "expense", "1", "0", "c", "d", "date"],
        vec![ledger_text, "add", "expense", "1", "-1", "c", "d", "date"],
        vec![ledger_text, "add", "expense", "1", "nope", "c", "d", "date"],
        vec![
            ledger_text,
            "add",
            "expense",
            "1",
            "1e9999",
            "c",
            "d",
            "date",
        ],
        vec![
            ledger_text,
            "add",
            "expense",
            "1",
            "1e-9999",
            "c",
            "d",
            "date",
        ],
        vec![ledger_text, "add", "other", "1", "1", "c", "d", "date"],
    ] {
        let output = run(&executable, &arguments);
        assert_status(&output, 2);
        assert!(!ledger.exists());
    }

    let first = run(
        &executable,
        &[
            ledger_text,
            "add",
            "income",
            "1",
            "1500.25",
            "work",
            "Salary September",
            "2026-09-22",
        ],
    );
    assert_status(&first, 0);
    assert_eq!(first.stdout, b"transaction added: work: Salary September\n");
    let first_bytes = fs::read(&ledger).unwrap();
    let first_inode = fs::metadata(&ledger).unwrap().ino();
    assert!(first_bytes.starts_with(b"AETHER-PERSISTENCE\n"));

    let second = run(
        &executable,
        &[
            ledger_text,
            "add",
            "expense",
            "2",
            "19.95",
            "caf\u{e9}:\u{3bb}\u{1f642}",
            "Lunch: first line\nsecond line",
            "date with spaces",
        ],
    );
    assert_status(&second, 0);
    assert!(String::from_utf8_lossy(&second.stdout).contains("caf\u{e9}:\u{3bb}\u{1f642}"));
    let second_bytes = fs::read(&ledger).unwrap();
    assert_ne!(first_bytes, second_bytes);
    assert_ne!(first_inode, fs::metadata(&ledger).unwrap().ino());
    assert!(
        second_bytes
            .windows(b"record-count 2".len())
            .any(|bytes| bytes == b"record-count 2")
    );

    let listed = run(&executable, &[ledger_text, "list"]);
    assert_status(&listed, 0);
    let listed = String::from_utf8(listed.stdout).unwrap();
    assert!(listed.contains("#1 | Income | 2026-09-22 | work | Salary September | 1500.25"));
    assert!(listed.contains(
        "#2 | Expense | date with spaces | caf\u{e9}:\u{3bb}\u{1f642} | Lunch: first line\nsecond line | 19.95"
    ));

    let summary = run(&executable, &[ledger_text, "summary"]);
    assert_status(&summary, 0);
    assert_eq!(
        summary.stdout,
        b"income: 1500.25\nexpenses: 19.95\nbalance: 1480.3\n"
    );

    let before_failed_save = fs::read(&ledger).unwrap();
    let injected = compilation
        .llvm
        .replace("@renameat(", "@aether_test_renameat(")
        .replace(
            "declare i32 @aether_test_renameat(i32, ptr, i32, ptr)\n",
            "",
        );
    let injected = format!(
        "{injected}\ndefine i32 @aether_test_renameat(i32 %a, ptr %b, i32 %c, ptr %d) {{\n  %ep = call ptr @__errno_location()\n  store i32 5, ptr %ep\n  ret i32 -1\n}}\n"
    );
    let failing_executable = directory.0.join("expense-failing-save");
    link(&injected, &failing_executable, optimization);
    let failed_save = run(
        &failing_executable,
        &[
            ledger_text,
            "add",
            "expense",
            "3",
            "4.5",
            "test",
            "must not publish",
            "2026-09-24",
        ],
    );
    assert_status(&failed_save, 4);
    assert_eq!(fs::read(&ledger).unwrap(), before_failed_save);

    fs::write(&ledger, b"AETHER-PERSISTENCE\ncorrupt\n").unwrap();
    let corrupt_before = fs::read(&ledger).unwrap();
    let corrupt = run(&executable, &[ledger_text, "list"]);
    assert_status(&corrupt, 3);
    assert!(String::from_utf8_lossy(&corrupt.stdout).contains("ledger load failed"));
    let refused_add = run(
        &executable,
        &[
            ledger_text,
            "add",
            "expense",
            "3",
            "4.5",
            "test",
            "must not replace corrupt input",
            "2026-09-24",
        ],
    );
    assert_status(&refused_add, 3);
    assert_eq!(fs::read(&ledger).unwrap(), corrupt_before);
}

#[test]
fn complete_expense_tracker_runs_in_separate_processes_at_o0_and_o2() {
    exercise_cli(OptimizationLevel::O0);
    exercise_cli(OptimizationLevel::O2);
}

#[test]
fn source_uses_only_the_current_supported_surface() {
    let source = fs::read_to_string(entry()).unwrap();
    for required in [
        "std.Process.args",
        "std.Text.parseInt",
        "std.Text.parseDouble",
    ] {
        assert!(source.contains(required), "missing {required}");
    }
    for forbidden in ["System", "appendText", "persist-check", "split-check"] {
        assert!(!source.contains(forbidden), "unexpected {forbidden}");
    }
    let persistence = fs::read_to_string(entry().with_file_name("Persistence.ae")).unwrap();
    for required in [
        "std.Text.byteAt",
        "std.Text.byteSlice",
        "std.File.readText",
        "std.File.writeTextAtomic",
    ] {
        assert!(persistence.contains(required), "missing {required}");
    }
}

#[test]
fn aether_next_run_forwards_program_arguments_after_separator() {
    let directory = Directory::new("driver-cli");
    let ledger = directory.0.join("missing.alpt");
    let output = Command::new(env!("CARGO_BIN_EXE_aether-next"))
        .args([
            "run",
            entry().to_str().unwrap(),
            "--",
            ledger.to_str().unwrap(),
            "summary",
        ])
        .output()
        .unwrap();
    assert_status(&output, 0);
    assert_eq!(output.stdout, b"income: 0\nexpenses: 0\nbalance: 0\n");
    assert!(!ledger.exists());
}
