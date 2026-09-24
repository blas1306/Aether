//! OWNING-PARAM-EARLY-RETURN-V1 path-sensitive cleanup qualification.

use std::{fs, path::PathBuf, process::Command};

use aether_driver::{ClangToolchain, Emit, OptimizationLevel, compile_source_with_optimization};
use aether_frontend::SourceFile;

struct Output(PathBuf);

impl Output {
    fn new(label: &str) -> Self {
        static NEXT: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
        Self(std::env::temp_dir().join(format!(
            "aether-owning-param-{label}-{}-{}",
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
        &SourceFile::new("owning_param_early_return_v1.ae", source),
        &[Emit::Hir, Emit::Mir, Emit::Ssa, Emit::Llvm],
        optimization,
    )
    .unwrap_or_else(|errors| panic!("{source}\n{errors:#?}"))
}

fn balanced_status(source: &str, optimization: OptimizationLevel) -> i32 {
    let compilation = compile(source, optimization);
    let checks = "  %own_heap_allocs = load i64, ptr @aether_heap_alloc_count\n  %own_heap_frees = load i64, ptr @aether_heap_free_count\n  %own_heap_ok = icmp eq i64 %own_heap_allocs, %own_heap_frees\n  %own_string_allocs = load i64, ptr @aether_string_alloc_count\n  %own_string_frees = load i64, ptr @aether_string_free_count\n  %own_string_ok = icmp eq i64 %own_string_allocs, %own_string_frees\n  %own_lifecycle_ok = and i1 %own_heap_ok, %own_string_ok\n  %own_result_ok = icmp eq i32 %process_status, 0\n  %own_ok = and i1 %own_lifecycle_ok, %own_result_ok\n  %own_status = select i1 %own_ok, i32 0, i32 99\n  ret i32 %own_status";
    let llvm = compilation
        .llvm
        .replace("  ret i32 %process_status", checks);
    let output = Output::new(match optimization {
        OptimizationLevel::O0 => "o0",
        OptimizationLevel::O2 => "o2",
    });
    ClangToolchain::default()
        .with_optimization(optimization)
        .link_executable(&llvm, &output.0)
        .unwrap();
    Command::new(&output.0)
        .status()
        .unwrap()
        .code()
        .unwrap_or(-1)
}

#[test]
fn expense_tracker_shape_by_value_runs_balanced_at_o0_o2() {
    let source = include_str!("../../../tests/programs/owning_param_early_return_smoke.ae");
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        let compilation = compile(source, optimization);
        assert!(compilation.dumps[&Emit::Hir].contains("Unconditional"));
        assert!(compilation.dumps[&Emit::Mir].contains("Drop"));
        assert!(compilation.dumps[&Emit::Ssa].contains("Drop"));
        assert_eq!(balanced_status(source, optimization), 0);
    }
}

#[test]
fn returned_owner_siblings_nested_branches_and_loops_compile_at_o0_o2() {
    let source = r#"
string choose(string value, bool take) {
    if (take) { return value; }
    return "fallback";
}

int paths(string first, string second, bool early) {
    if (early) { return 1; }
    if (byteLength(first) == 0) { return 2; }
    int i = 0;
    while (i < 3) {
        if (i == 2) { return 3; }
        i = i + 1;
    }
    for (int j in 1:2) {
        if (j == 2) { return 4; }
    }
    Array<string> items = {"x"};
    for (ref string item in items) {
        if (byteLength(*item) == 1) { return 5; }
    }
    return 6;
}

int main() {
    string result = choose("moved", true);
    if (byteLength(result) != 5) { return 90; }
    return paths("a", "b", true) - 1;
}
"#;
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        assert_eq!(balanced_status(source, optimization), 0);
    }
}
