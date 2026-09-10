//! LANGUAGE-PARITY-1: entry normalization, trivia and cross-layer qualification.

use std::{fs, path::PathBuf};

use aether_driver::{
    ClangToolchain, CompilationSession, Emit, compile_session, compile_source, run_path,
};
use aether_frontend::{
    HirExprKind, HirStmtKind, Phase, SourceFile, Span, TypeId, analyze, lex, parse_source,
};

const EMITS: &[Emit] = &[Emit::Hir, Emit::Mir, Emit::Ssa];

struct TestDirectory(PathBuf);

impl TestDirectory {
    fn new() -> Self {
        static NEXT: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
        let id = NEXT.fetch_add(1, std::sync::atomic::Ordering::Relaxed);
        let path = std::env::temp_dir().join(format!(
            "aether-language-parity-{}-{id}",
            std::process::id()
        ));
        fs::create_dir(&path).unwrap();
        Self(path)
    }
}

impl Drop for TestDirectory {
    fn drop(&mut self) {
        fs::remove_dir_all(&self.0).unwrap();
    }
}

// Remove only physical source ranges from the deterministic pretty dumps.
// All types, identities, expressions, CFG, cleanup and generation markers remain.
fn without_spans(dump: &str) -> String {
    let mut in_span = false;
    dump.lines()
        .filter(|line| {
            if line.trim() == "span: Span {" {
                in_span = true;
                false
            } else if in_span {
                if line.trim() == "}," {
                    in_span = false;
                }
                false
            } else {
                true
            }
        })
        .collect::<Vec<_>>()
        .join("\n")
}

#[test]
fn entry_normalizes_before_ownership_and_backend() {
    for text in [
        "int main() {}",
        "int main() {} // trailing comment at EOF",
        "int main() { bool x=false; if(x){return 3;} }",
        "int main() { Buffer<int> b=Buffer<int>(2,7); }",
    ] {
        let source = SourceFile::new("entry.ae", text);
        let hir = analyze(parse_source(&source).unwrap()).unwrap();
        let function = &hir.functions()[hir.entry().0 as usize];
        let last = function.body.statements.last().unwrap();
        assert!(last.compiler_generated);
        let closing = text.rfind('}').unwrap();
        assert_eq!(last.span, Span::new(closing, closing + 1));
        let HirStmtKind::Return { value, drops } = &last.kind else {
            panic!("missing normalized return")
        };
        assert_eq!(value.kind, HirExprKind::Int(0));
        assert_eq!(value.ty, TypeId::INT64);
        assert_eq!(value.span, last.span);
        assert_eq!(drops.len(), usize::from(text.contains("Buffer")));
        let compiled = compile_source(&source, EMITS).unwrap();
        let repeated = compile_source(&source, EMITS).unwrap();
        assert_eq!(compiled.dumps, repeated.dumps);
        assert_eq!(compiled.llvm, repeated.llvm);
        assert!(compiled.dumps[&Emit::Hir].contains("compiler_generated: true"));
        for phase in [Emit::Mir, Emit::Ssa] {
            assert!(compiled.dumps[&phase].contains("Return("));
            assert!(!compiled.dumps[&phase].contains("compiler_generated"));
        }
        let explicit = SourceFile::new(
            "entry.ae",
            format!("{}return 0; {}", &text[..closing], &text[closing..]),
        );
        let explicit = compile_source(&explicit, EMITS).unwrap();
        assert_eq!(compiled.llvm, explicit.llvm);
        for phase in [Emit::Mir, Emit::Ssa] {
            assert_eq!(
                without_spans(&compiled.dumps[&phase]),
                without_spans(&explicit.dumps[&phase])
            );
        }
    }
}

#[test]
fn terminating_entry_paths_do_not_get_duplicate_returns() {
    for text in [
        "int main(){return 0;}",
        "int main(){return 7;}",
        "int main(){if(true){return 1;}else{return 2;}}",
        "enum E{A,B} int main(){E x=E.A;match(x){E.A=>{return 1;}E.B=>{return 2;}}}",
    ] {
        let compilation = compile_source(&SourceFile::new("entry.ae", text), EMITS).unwrap();
        assert!(!compilation.dumps[&Emit::Hir].contains("compiler_generated: true"));
    }
}

#[test]
fn ordinary_returns_entry_signatures_and_no_script_mode_remain_strict() {
    for (text, code) in [
        ("int f(){} int main(){}", "E0207"),
        ("int f(bool x){if(x){return 1;}} int main(){}", "E0207"),
        ("int f<T>(){} int main(){}", "E0207"),
        ("bool main(){return true;}", "E0201"),
        ("double main(){return 0.0;}", "E0201"),
        ("int32 main(){return 0;}", "E0201"),
        ("int main(int x){return x;}", "E0201"),
        ("int main<T>(){return 0;}", "E0201"),
        ("int main<T>(){}", "E0201"),
        ("int f(){return 0;}", "E0200"),
        ("// no synthetic entry", "E0101"),
        ("int main(){return 1;return 2;}", "E0208"),
    ] {
        let error = compile_source(&SourceFile::new("invalid.ae", text), &[]).unwrap_err();
        assert_eq!(error[0].code, code, "{text}");
    }
    for text in [
        "void main(){}",
        "main(){}",
        "println(1);",
        "println(1); int main(){}",
        "int x=1; int main(){}",
        "int main(){} int main(){}",
    ] {
        assert!(
            compile_source(&SourceFile::new("invalid.ae", text), &[]).is_err(),
            "{text}"
        );
    }
    // Canonical int aliases were already deliberately admitted.
    for text in ["int64 main(){}", "alias Exit=int; Exit main(){}"] {
        compile_source(&SourceFile::new("alias.ae", text), &[]).unwrap();
    }
}

#[test]
fn imported_main_is_never_given_entry_semantics() {
    let dir = TestDirectory::new();
    let entry = dir.0.join("main.ae");
    let helper = dir.0.join("helper.ae");
    fs::write(&entry, "import helper; int main(){}").unwrap();
    for text in ["int main(){}", "int main(bool x){if(x){return 1;}}"] {
        fs::write(&helper, text).unwrap();
        let session = CompilationSession::discover(&entry).unwrap();
        let error = compile_session(session, &[]).unwrap_err();
        assert_eq!(error[0].code, "E0207");
        assert_eq!(error[0].source_name.as_deref(), Some("helper.ae"));
    }
    fs::write(&helper, "// ordinary helper\nbool main(){return true;}").unwrap();
    compile_session(CompilationSession::discover(&entry).unwrap(), &[]).unwrap();
    fs::write(&entry, "import helper; int f(){return 0;}").unwrap();
    assert_eq!(
        compile_session(CompilationSession::discover(&entry).unwrap(), &[]).unwrap_err()[0].code,
        "E0200"
    );
}

#[test]
fn comments_preserve_tokens_and_all_semantic_phases() {
    for text in [
        "int main(){int x=6/2*3;if(x>=9){return x;}return 0;}",
        "T identity<T:Copy>(T x){return x;} int main(){int x=identity(1);}",
        "int main(){Vector<double,Row> v=[1,2]; Matrix<double> A=[1,2;3,4]; Matrix<double> B=A*A;}",
    ] {
        let plain = SourceFile::new("comments.ae", text);
        let tokens = lex(&plain).unwrap();
        let commented = SourceFile::new(
            "comments.ae",
            tokens
                .iter()
                .map(|t| t.lexeme.as_str())
                .collect::<Vec<_>>()
                .join(" /* λ\r\n // { + / } */ // line\r\n"),
        );
        let commented_tokens = lex(&commented).unwrap();
        assert_eq!(
            tokens
                .iter()
                .map(|t| (t.kind, &t.lexeme))
                .collect::<Vec<_>>(),
            commented_tokens
                .iter()
                .map(|t| (t.kind, &t.lexeme))
                .collect::<Vec<_>>()
        );
        let baseline = compile_source(&plain, EMITS).unwrap();
        let actual = compile_source(&commented, EMITS).unwrap();
        for phase in EMITS {
            assert_eq!(
                without_spans(&baseline.dumps[phase]),
                without_spans(&actual.dumps[phase]),
                "{phase:?}"
            );
        }
        assert_eq!(baseline.llvm, actual.llvm);
    }
}

#[test]
fn parser_diagnostic_after_closed_comment_has_exact_position() {
    for newline in ["\n", "\r\n"] {
        let source = SourceFile::new(
            "position.ae",
            format!("/*{newline}line 2{newline}line 3{newline}*/{newline}  ;"),
        );
        let error = &compile_source(&source, &[]).unwrap_err()[0];
        assert_eq!(error.phase, Phase::Parse);
        assert_eq!(
            error.span,
            Some(Span::new(source.text.len() - 1, source.text.len()))
        );
        assert_eq!(source.line_column(error.span.unwrap().start), (5, 3));
        assert!(
            error
                .render(Some(&source))
                .starts_with("position.ae:5:3: error[")
        );
    }
}

#[test]
#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
fn native_main_exit_codes_and_comment_integration() {
    let dir = TestDirectory::new();
    let entry = dir.0.join("main.ae");
    for (text, expected) in [
        ("int main(){}", 0),
        ("int main(){return 0;}", 0),
        ("int main(){return 7;}", 7),
        ("int main(){bool x=true;if(x){return 3;}}", 3),
        ("int main(){bool x=false;if(x){return 3;}}", 0),
        ("int main(){int x=8/2*3;while(x>0){x=x-1;}}", 0),
        ("int main(){if(true){if(true){int x=1;}}}", 0),
        ("int main(){Buffer<int> b=Buffer<int>(2,7);}", 0),
        (
            "int main(){/* explicit for formality */ return /* value */ 0;}",
            0,
        ),
        (
            include_str!("../../../tests/programs/language_parity_1.ae"),
            0,
        ),
    ] {
        fs::write(&entry, text).unwrap();
        let (_, status) = run_path(&entry, &[], &ClangToolchain::default()).unwrap();
        assert_eq!(status.code(), Some(expected), "{text}");
    }
    fs::write(dir.0.join("helper.ae"), "int main(){return 7;}").unwrap();
    fs::write(&entry, "import helper; int main(){return helper.main();}").unwrap();
    assert_eq!(
        run_path(&entry, &[], &ClangToolchain::default())
            .unwrap()
            .1
            .code(),
        Some(7)
    );
}
