//! PACKAGE-ERGONOMICS-V1 single-unit anonymous entry qualification.

use std::collections::BTreeSet;
use std::fs;
use std::path::{Path, PathBuf};
use std::process::Command;

use aether_backend_llvm::bootstrap_symbol_for;
use aether_driver::{
    ClangToolchain, CompilationSession, Emit, OptimizationLevel, compile_session,
    compile_session_with_optimization, run_path,
};
use aether_frontend::{
    LogicalSourceKey, ModuleId, ModuleInfo, OriginKey, PackageId, PackageKey, PackagePath,
    ParsedModule, ParsedProgram, ResolvedImport, SourceFile, SourceId, SourceUnitKey, Span,
    collect_program_signatures, parse_source,
};

struct Directory(PathBuf);

impl Directory {
    fn new(label: &str) -> Self {
        static NEXT: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
        let path = std::env::temp_dir().join(format!(
            "aether-package-ergonomics-{label}-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, std::sync::atomic::Ordering::Relaxed)
        ));
        fs::create_dir(&path).unwrap();
        Self(path)
    }

    fn write(&self, relative: &str, source: &str) -> PathBuf {
        let path = self.0.join(relative);
        fs::create_dir_all(path.parent().unwrap()).unwrap();
        fs::write(&path, source).unwrap();
        path
    }
}

impl Drop for Directory {
    fn drop(&mut self) {
        fs::remove_dir_all(&self.0).unwrap();
    }
}

fn injected_module(
    id: u32,
    package_id: u32,
    package: &PackageKey,
    logical: &str,
    source_text: &str,
) -> ParsedModule {
    let source_id = SourceId(id);
    let source = SourceFile::with_id(source_id, logical, source_text);
    let ast = parse_source(&source).unwrap();
    ParsedModule {
        info: ModuleInfo {
            id: ModuleId(id),
            key: SourceUnitKey {
                package: package.clone(),
                logical_source: LogicalSourceKey(logical.into()),
            },
            package: PackageId(package_id),
            display_name: package.display(),
            source: source_id,
            source_name: logical.into(),
            imports: Vec::new(),
            semantic_dependencies: BTreeSet::new(),
        },
        ast,
    }
}

#[test]
fn anonymous_ast_hir_llvm_and_native_o0_o2_are_closed() {
    let directory = Directory::new("basic");
    let entry = directory.write(
        "main.ae",
        "int helper(){return 0;} int main(){return helper();}",
    );
    directory.write("nearby.ae", "int main(){return 99;}");
    let session = CompilationSession::discover(&entry).unwrap();
    assert_eq!(session.modules().len(), 1);
    assert_eq!(
        session.modules()[0].info().key.package,
        PackageKey::Anonymous
    );

    let compilation = compile_session(
        session,
        &[Emit::Ast, Emit::Hir, Emit::Mir, Emit::Ssa, Emit::Llvm],
    )
    .unwrap();
    assert!(compilation.dumps[&Emit::Ast].contains("package: None"));
    assert!(compilation.dumps[&Emit::Hir].contains("package: Anonymous"));
    assert!(compilation.dumps[&Emit::Llvm].contains("__aether_v2_a0_f6_helper"));
    assert!(compilation.dumps[&Emit::Llvm].contains("define i32 @main()"));

    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        let (_, status) = run_path(
            &entry,
            &[],
            &ClangToolchain::default().with_optimization(optimization),
        )
        .unwrap();
        assert_eq!(status.code(), Some(0));
    }
}

#[test]
fn anonymous_imports_std_and_named_project_packages() {
    let directory = Directory::new("imports");
    let entry = directory.write(
        "main.ae",
        "import std.File; import std.Text; import Project.Tools; int main(){return Project.Tools.answer();}",
    );
    directory.write("tools.ae", "package Project.Tools; int answer(){return 0;}");
    let session = CompilationSession::discover(&entry).unwrap();
    assert_eq!(
        session.modules()[0].info().key.package,
        PackageKey::Anonymous
    );
    assert!(session.modules().iter().any(|module| {
        module.info().key.package
            == PackageKey::named(
                OriginKey::Project,
                PackagePath(vec!["Project".into(), "Tools".into()]),
            )
    }));
    compile_session_with_optimization(session, &[Emit::Hir], OptimizationLevel::O2).unwrap();
}

#[test]
fn named_packages_multi_file_and_named_mangling_remain_unchanged() {
    let directory = Directory::new("named");
    let entry = directory.write(
        "main.ae",
        "package Stable.App; int main(){return helper();}",
    );
    directory.write("helper.ae", "package Stable.App; int helper(){return 0;}");
    directory.write("unreached.ae", "int main(){return 99;}");
    let session = CompilationSession::discover(&entry).unwrap();
    assert_eq!(session.modules().len(), 2);
    assert!(
        session
            .modules()
            .iter()
            .all(|module| matches!(module.info().key.package, PackageKey::Named { .. }))
    );
    let llvm = compile_session(session, &[Emit::Llvm]).unwrap().llvm;
    assert_eq!(
        bootstrap_symbol_for("Stable.App", "helper"),
        "__aether_v2_m10_Stable_2eApp_f6_helper"
    );
    assert_eq!(
        bootstrap_symbol_for("Stable.App", "main"),
        "__aether_v2_m10_Stable_2eApp_f4_main"
    );
    assert!(llvm.contains("__aether_v2_m10_Stable_2eApp_f6_helper"));
    assert!(llvm.contains("__aether_v2_m10_Stable_2eApp_f4_main"));
    assert!(!llvm.contains("__aether_v2_a0_"));
}

#[test]
fn named_anonymous_does_not_collide_and_cannot_select_entry_main() {
    let directory = Directory::new("named-anonymous");
    let entry = directory.write(
        "main.ae",
        "import anonymous; int main(){return anonymous.answer();}",
    );
    directory.write(
        "named.ae",
        "package anonymous; int answer(){return 0;} int main(){return 17;}",
    );
    let session = CompilationSession::discover(&entry).unwrap();
    assert!(session.modules().iter().any(|module| {
        module.info().key.package
            == PackageKey::named(OriginKey::Project, PackagePath(vec!["anonymous".into()]))
    }));
    let (_, status) = run_path(&entry, &[], &ClangToolchain::default()).unwrap();
    assert_eq!(status.code(), Some(0));
}

#[test]
fn parser_preserves_none_and_diagnoses_misplaced_and_duplicate_package() {
    let ast = parse_source(&SourceFile::new("anonymous.ae", "int main(){return 0;}")).unwrap();
    assert!(ast.package().is_none());

    for source in [
        "import std.Text; package Later; int main(){}",
        "int helper(){return 0;} package Later; int main(){}",
    ] {
        let errors = parse_source(&SourceFile::new("misplaced.ae", source)).unwrap_err();
        assert_eq!(
            errors[0].message,
            "package declaration must be the first non-trivia item"
        );
    }
    let errors = parse_source(&SourceFile::new(
        "duplicate.ae",
        "package First; package Second; int main(){}",
    ))
    .unwrap_err();
    assert_eq!(
        errors[0].message,
        "source unit contains more than one package declaration"
    );
}

#[test]
fn invalid_anonymous_graphs_and_empty_named_paths_fail_closed() {
    let first = injected_module(0, 0, &PackageKey::Anonymous, "first.ae", "int main(){}");
    let second = injected_module(1, 0, &PackageKey::Anonymous, "second.ae", "int helper(){}");
    let errors = collect_program_signatures(ParsedProgram {
        modules: vec![first, second],
        entry: ModuleId(0),
    })
    .unwrap_err();
    assert_eq!(errors[0].code, "E0241");
    assert!(errors[0].message.contains("first.ae"));
    assert!(errors[0].message.contains("second.ae"));

    let mut imported = injected_module(0, 0, &PackageKey::Anonymous, "entry.ae", "int main(){}");
    imported.info.imports.push(ResolvedImport {
        name: "forged".into(),
        module: ModuleId(0),
        package: PackageId(0),
        target: PackageKey::Anonymous,
        alias: None,
        span: Span::default(),
    });
    let errors = collect_program_signatures(ParsedProgram {
        modules: vec![imported],
        entry: ModuleId(0),
    })
    .unwrap_err();
    assert!(
        errors[0]
            .message
            .contains("anonymous package is not importable")
    );

    let corrupt = injected_module(
        0,
        0,
        &PackageKey::named(OriginKey::Project, PackagePath(Vec::new())),
        "corrupt.ae",
        "package P; int main(){}",
    );
    let errors = collect_program_signatures(ParsedProgram {
        modules: vec![corrupt],
        entry: ModuleId(0),
    })
    .unwrap_err();
    assert!(errors[0].message.contains("empty PackagePath"));
}

#[test]
#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
fn relative_dot_and_absolute_entry_spellings_have_identical_graphs_and_output() {
    let directory = Directory::new("spellings");
    let entry = directory.write("main.ae", "int main(){return 0;}");
    let output = directory.0.join("program");
    let executable = env!("CARGO_BIN_EXE_aether-next");
    let invoke = |spelling: &Path| {
        let result = Command::new(executable)
            .current_dir(&directory.0)
            .arg("build")
            .arg(spelling)
            .arg("-o")
            .arg(&output)
            .arg("--emit")
            .arg("ast")
            .arg("--emit")
            .arg("hir")
            .arg("--emit")
            .arg("llvm")
            .output()
            .unwrap();
        assert!(
            result.status.success(),
            "{}",
            String::from_utf8_lossy(&result.stderr)
        );
        result.stdout
    };
    assert_eq!(invoke(Path::new("main.ae")), invoke(Path::new("./main.ae")));
    assert_eq!(invoke(Path::new("main.ae")), invoke(&entry));
}
