//! MODULE-STD-V1 package catalog, namespace grants and canonical identity.

use std::fs;
use std::path::{Path, PathBuf};

use aether_driver::{CompilationSession, Emit, compile_session};

struct Directory(PathBuf);

impl Directory {
    fn new(label: &str) -> Self {
        static NEXT: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
        let path = std::env::temp_dir().join(format!(
            "aether-module-std-{label}-{}-{}",
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

fn diagnostics(entry: &Path) -> String {
    format!("{:#?}", CompilationSession::discover(entry).unwrap_err())
}

#[test]
fn multiple_units_contribute_before_body_analysis() {
    let directory = Directory::new("multi");
    let entry = directory.write(
        "main.ae",
        "package Project.Numerical; int main(){return later();}",
    );
    directory.write(
        "contribution.ae",
        "package Project.Numerical; int later(){return 7;}",
    );
    let session = CompilationSession::discover(&entry).unwrap();
    assert_eq!(session.modules().len(), 2);
    let compilation = compile_session(session, &[Emit::Hir]).unwrap();
    assert!(compilation.dumps[&Emit::Hir].contains("later"));
}

#[test]
fn duplicate_and_child_collisions_are_global() {
    let duplicate = Directory::new("duplicate");
    let entry = duplicate.write("main.ae", "package P; int main(){} int value(){return 1;}");
    duplicate.write("other.ae", "package P; int value(){return 2;}");
    assert!(diagnostics(&entry).contains("E0240"));

    let collision = Directory::new("collision");
    let entry = collision.write(
        "main.ae",
        "package App; import App.Models; int Models(){return 0;} int main(){}",
    );
    collision.write("model.ae", "package App.Models; int make(){return 1;}");
    assert!(diagnostics(&entry).contains("E0236"));
}

#[test]
fn hierarchical_grants_support_descendants_and_aliases() {
    let directory = Directory::new("hierarchy");
    let entry = directory.write(
        "main.ae",
        "package Main; import Library.Math as math; int main(){return math.base()+math.LinearAlgebra.leaf();}",
    );
    directory.write("math.ae", "package Library.Math; int base(){return 20;}");
    directory.write(
        "linear.ae",
        "package Library.Math.LinearAlgebra; int leaf(){return 22;}",
    );
    let compilation = compile_session(
        CompilationSession::discover(&entry).unwrap(),
        &[Emit::Hir, Emit::Llvm],
    )
    .unwrap();
    assert!(compilation.dumps[&Emit::Hir].contains("Library"));
    assert!(!compilation.dumps[&Emit::Hir].contains("alias: Some(\"math\")"));

    let leaf_alias = Directory::new("leaf-alias");
    let entry = leaf_alias.write(
        "main.ae",
        "package Main; import Library.Math.LinearAlgebra as la; int main(){return la.leaf();}",
    );
    leaf_alias.write(
        "linear.ae",
        "package Library.Math.LinearAlgebra; int leaf(){return 0;}",
    );
    compile_session(CompilationSession::discover(&entry).unwrap(), &[]).unwrap();
}

#[test]
fn imports_are_grants_not_open_namespaces_or_link_roots() {
    let directory = Directory::new("grants");
    let entry = directory.write(
        "main.ae",
        "package Main; import Dep.Branch; int main(){return 0;}",
    );
    directory.write(
        "dep.ae",
        "package Dep.Branch; int definitely_unused(){return 9;}",
    );
    let compilation = compile_session(
        CompilationSession::discover(&entry).unwrap(),
        &[Emit::Hir, Emit::Llvm],
    )
    .unwrap();
    assert!(!compilation.llvm.contains("definitely_unused"));
    assert!(compilation.dumps[&Emit::Hir].contains("semantic_dependencies: {}"));

    let open = Directory::new("not-open");
    let entry = open.write(
        "main.ae",
        "package Main; import Dep.Branch; int main(){return definitely_unused();}",
    );
    open.write(
        "dep.ae",
        "package Dep.Branch; int definitely_unused(){return 9;}",
    );
    let errors = compile_session(CompilationSession::discover(&entry).unwrap(), &[]).unwrap_err();
    assert!(format!("{errors:#?}").contains("unknown function"));
}

#[test]
fn namespace_binding_conflicts_and_missing_siblings_fail_closed() {
    let duplicate = Directory::new("duplicate-alias");
    let entry = duplicate.write(
        "main.ae",
        "package Main; import A.One as branch; import A.Two as branch; int main(){}",
    );
    duplicate.write("one.ae", "package A.One;");
    duplicate.write("two.ae", "package A.Two;");
    assert!(diagnostics(&entry).contains("duplicate namespace binding"));

    let local = Directory::new("local-alias");
    let entry = local.write(
        "main.ae",
        "package Main; import A.One as branch; int main(){int branch=0;return branch;}",
    );
    local.write("one.ae", "package A.One;");
    let errors = compile_session(CompilationSession::discover(&entry).unwrap(), &[]).unwrap_err();
    assert!(format!("{errors:#?}").contains("E0235"));

    let sibling = Directory::new("sibling");
    let entry = sibling.write(
        "main.ae",
        "package Main; import A.One; int main(){return A.Two.value();}",
    );
    sibling.write("one.ae", "package A.One;");
    sibling.write("two.ae", "package A.Two; int value(){return 1;}");
    assert!(
        format!(
            "{:#?}",
            compile_session(CompilationSession::discover(&entry).unwrap(), &[]).unwrap_err()
        )
        .contains("unknown package path")
    );
}

#[test]
fn std_is_reserved_and_text_has_one_canonical_identity() {
    let legacy = Directory::new("legacy-text");
    let entry = legacy.write("main.ae", "package Main; import Text; int main(){}");
    let errors = CompilationSession::discover(&entry).unwrap_err();
    assert_eq!(errors[0].code, "E0232");
    assert_eq!(errors[0].fixits[0].replacement, "import std.Text;");

    let root = Directory::new("std-root");
    let entry = root.write("main.ae", "package Main; import std; int main(){}");
    assert!(diagnostics(&entry).contains("E0233"));

    let forged = Directory::new("forged-std");
    let entry = forged.write("main.ae", "package std.Text; int main(){}");
    assert!(diagnostics(&entry).contains("E0231"));

    let canonical = Directory::new("canonical-text");
    let entry = canonical.write(
        "main.ae",
        "package Main; import std.Text as text; int main(){bool hit=text.contains(\"abc\",\"b\");if(hit){return 0;}return 1;}",
    );
    canonical.write("Text.ae", "package Text; int contains(){return 99;}");
    let compilation =
        compile_session(CompilationSession::discover(&entry).unwrap(), &[Emit::Hir]).unwrap();
    assert!(compilation.dumps[&Emit::Hir].contains("Toolchain"));
    assert!(compilation.dumps[&Emit::Hir].contains("Contains"));
}

#[test]
fn standard_math_namespace_nodes_exist_without_adding_an_api() {
    let directory = Directory::new("std-math");
    let entry = directory.write(
        "main.ae",
        "package Main; import std.Math; import std.Math.LinearAlgebra as la; int main(){}",
    );
    let session = CompilationSession::discover(&entry).unwrap();
    assert!(
        session
            .modules()
            .iter()
            .any(|module| module.info().name == "std.Math")
    );
    assert!(
        session
            .modules()
            .iter()
            .any(|module| module.info().name == "std.Math.LinearAlgebra")
    );
    compile_session(session, &[]).unwrap();
}

#[test]
fn logical_identity_is_independent_of_absolute_checkout_path() {
    fn compile_tree(label: &str) -> String {
        let directory = Directory::new(label);
        let entry = directory.write(
            "main.ae",
            "package Main; import Shared.Code; int main(){return Shared.Code.answer();}",
        );
        directory.write(
            "nested/answer.ae",
            "package Shared.Code; int answer(){return 42;}",
        );
        compile_session(
            CompilationSession::discover(&entry).unwrap(),
            &[Emit::Hir, Emit::Mir, Emit::Ssa],
        )
        .unwrap()
        .dumps
        .into_values()
        .collect::<Vec<_>>()
        .join("\n")
    }
    assert_eq!(compile_tree("absolute-a"), compile_tree("absolute-b"));
}

#[test]
fn namespace_alias_spelling_disappears_before_hir() {
    fn compile_with(alias: &str, label: &str) -> String {
        let directory = Directory::new(label);
        let entry = directory.write(
            "main.ae",
            &format!(
                "package Main; import std.Text as {alias}; int main(){{bool hit={alias}.contains(\"x\",\"x\");if(hit){{return 0;}}return 1;}}"
            ),
        );
        compile_session(CompilationSession::discover(&entry).unwrap(), &[Emit::Hir])
            .unwrap()
            .dumps[&Emit::Hir]
            .clone()
    }
    assert_eq!(
        compile_with("txt", "alias-a"),
        compile_with("str", "alias-b")
    );
}

#[test]
fn std_import_aliases_do_not_open_or_modify_the_core_prelude() {
    let directory = Directory::new("core-independent");
    let entry = directory.write(
        "main.ae",
        "package Main; import std.Text as text; int main(){double x=exp(0.0);bool hit=text.contains(\"x\",\"x\");if(x!=1.0){return 1;}if(hit){return 0;}return 2;}",
    );
    let compilation = compile_session(
        CompilationSession::discover(&entry).unwrap(),
        &[Emit::Hir, Emit::Llvm],
    )
    .unwrap();
    assert!(compilation.dumps[&Emit::Hir].contains("CoreSymbolKey"));
    assert!(compilation.dumps[&Emit::Hir].contains("Contains"));
    assert!(compilation.llvm.contains("Core libm dependency"));
}
