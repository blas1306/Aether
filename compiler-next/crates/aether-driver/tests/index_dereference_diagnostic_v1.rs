//! INDEX-DEREFERENCE-DIAGNOSTIC-V1 focused diagnostic qualification.

use std::{fs, path::PathBuf, process::Command};

use aether_driver::{ClangToolchain, Emit, OptimizationLevel, build_path, compile_source};
use aether_frontend::SourceFile;

struct Project {
    root: PathBuf,
    input: PathBuf,
    output: PathBuf,
}

impl Project {
    fn new(source: &str) -> Self {
        static NEXT: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
        let root = std::env::temp_dir().join(format!(
            "aether-index-dereference-diagnostic-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, std::sync::atomic::Ordering::Relaxed)
        ));
        fs::create_dir(&root).unwrap();
        let input = root.join("main.ae");
        let output = root.join("program");
        fs::write(&input, source).unwrap();
        Self {
            root,
            input,
            output,
        }
    }
}

impl Drop for Project {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.root);
    }
}

fn diagnostic(source: &str) -> aether_frontend::Diagnostic {
    compile_source(
        &SourceFile::new("index_dereference_diagnostic_v1.ae", source),
        &[],
    )
    .expect_err(source)
    .remove(0)
}

#[test]
fn indexed_string_dereference_reports_the_primary_type_error() {
    let source = r#"import std.Text;

int main() {
    List<string> lines = std.Text.lines("x");
    string result = std.Text.trim(*lines[0]);
    println(result);
    return 0;
}
"#;
    let project = Project::new(source);
    let diagnostics = build_path(
        &project.input,
        &project.output,
        &[],
        &ClangToolchain::default(),
    )
    .unwrap_err();
    assert_eq!(diagnostics[0].code, "E0271", "{diagnostics:#?}");
    assert_eq!(
        diagnostics[0]
            .span
            .map(|span| &source[span.start..span.end]),
        Some("*lines[0]")
    );
    assert!(
        diagnostics[0]
            .message
            .contains("expression of type `string`")
    );
    assert!(
        diagnostics[0]
            .message
            .contains("requires `ref T` or `ref mut T`")
    );
    assert!(diagnostics[0].message.contains("does not create a borrow"));
}

#[test]
fn non_reference_places_and_ordinary_values_both_report_e0271() {
    for (source, ty) in [
        (
            "int main(){List<int> numbers={1};return *numbers[0];}",
            "int64",
        ),
        (
            "int number(){return 1;}int main(){return *number();}",
            "int64",
        ),
    ] {
        let error = diagnostic(source);
        assert_eq!(error.code, "E0271", "{source}: {error:#?}");
        assert!(
            error
                .message
                .contains(&format!("expression of type `{ty}`")),
            "{source}: {}",
            error.message
        );
        assert!(error.span.is_some(), "{source}");
    }
}

#[test]
fn refined_nullable_references_dereference_in_then_else_and_local_storage_o0_o2() {
    let source = r"
int readThen((ref int)? value) {
    if (value != null) { return *value; }
    return 0;
}

int readElse((ref int)? value) {
    if (value == null) { return 0; }
    else { return *value; }
}

int main() {
    int number = 9;
    (ref int)? local = &number;
    if (local != null) {
        int observed = *local;
        if (observed != 9) { return 1; }
    } else { return 2; }
    if (readThen(local) != 9) { return 3; }
    if (readElse(local) != 9) { return 4; }
    return 0;
}
";
    let project = Project::new(source);
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        let compilation = build_path(
            &project.input,
            &project.output,
            &[Emit::Hir, Emit::Mir, Emit::Ssa, Emit::Llvm],
            &ClangToolchain::default().with_optimization(optimization),
        )
        .unwrap_or_else(|diagnostics| panic!("{optimization:?}: {diagnostics:#?}"));
        assert!(compilation.dumps[&Emit::Hir].contains("NullablePayload"));
        assert!(compilation.dumps[&Emit::Hir].contains("Dereference"));
        assert_eq!(
            Command::new(&project.output).status().unwrap().code(),
            Some(0)
        );
    }
}

#[test]
fn nullable_reference_without_live_non_null_proof_remains_rejected() {
    for source in [
        "int read((ref int)? value){return *value;}int main(){return 0;}",
        "int read((ref int)? value){if(value!=null){value=null;return *value;}return 0;}int main(){return 0;}",
    ] {
        let error = diagnostic(source);
        assert_eq!(error.code, "E0271", "{source}: {error:#?}");
        assert!(
            error.message.contains("(ref int64)?"),
            "{source}: {}",
            error.message
        );
        assert!(error.span.is_some(), "{source}");
    }
}

#[test]
fn real_partial_moves_and_closed_borrow_rules_keep_their_diagnostics() {
    for (source, code) in [
        (
            "int main(){List<string> lines={\"x\"};string value=lines[0];return 0;}",
            "E0293",
        ),
        (
            "ref string bad(ref List<string> lines){return &(*lines)[0];}int main(){return 0;}",
            "E0273",
        ),
        (
            "int main(){List<int> values={1};ref int item=&values[0];push(values,2);return *item;}",
            "E0313",
        ),
        (
            "int main(){List<string> values={\"x\"};List<string> moved=values;return int(length(values));}",
            "E0291",
        ),
    ] {
        let error = diagnostic(source);
        assert_eq!(error.code, code, "{source}: {error:#?}");
        assert!(error.span.is_some(), "{source}");
    }
}

#[test]
fn list_array_field_local_iteration_copy_and_real_dereference_run_at_o0_o2() {
    let source = r#"import std.Text;

struct Holder { string value; }

int readInt(ref int value) { return *value; }

int main() {
    List<string> lines = std.Text.lines(" x ");
    string contextual = std.Text.trim(lines[0]);
    string explicit = std.Text.trim(&lines[0]);

    Array<string> fixed = {" y "};
    string arrayValue = std.Text.trim(fixed[0]);

    Holder holder = Holder(" z ");
    string fieldValue = std.Text.trim(holder.value);

    string local = " q ";
    string localValue = std.Text.trim(&local);
    ref string actual = &local;
    string dereferenced = std.Text.trim(*actual);

    List<int> numbers = {7};
    if (readInt(numbers[0]) != 7) { return 1; }

    usize iterations = 0;
    for (ref string item in lines) {
        string value = std.Text.trim(*item);
        if (value != "x") { return 2; }
        iterations = iterations + 1;
    }
    if (iterations != 1) { return 3; }
    if (contextual != "x" || explicit != "x" || arrayValue != "y") { return 4; }
    if (fieldValue != "z" || localValue != "q" || dereferenced != "q") { return 5; }
    return 0;
}
"#;
    let project = Project::new(source);
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        let compilation = build_path(
            &project.input,
            &project.output,
            &[Emit::Hir, Emit::Mir, Emit::Ssa, Emit::Llvm],
            &ClangToolchain::default().with_optimization(optimization),
        )
        .unwrap_or_else(|diagnostics| panic!("{optimization:?}: {diagnostics:#?}"));
        for emit in [Emit::Hir, Emit::Mir, Emit::Ssa] {
            assert!(
                compilation.dumps[&emit].contains("Borrow"),
                "{optimization:?} {emit:?}"
            );
        }
        assert!(compilation.dumps[&Emit::Hir].contains("Dereference"));
        assert!(compilation.dumps[&Emit::Mir].contains("EndBorrow"));
        assert!(compilation.dumps[&Emit::Ssa].contains("EndBorrow"));
        assert!(!compilation.dumps[&Emit::Hir].contains("Clone"));
        let execution = Command::new(&project.output).output().unwrap();
        assert_eq!(
            execution.status.code(),
            Some(0),
            "{optimization:?}: {}",
            String::from_utf8_lossy(&execution.stderr)
        );
    }
}
