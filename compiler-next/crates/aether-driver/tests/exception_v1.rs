//! EXCEPTION-V1 semantic, IR-corruption and Linux x86-64 native qualification.

use std::{fs, path::PathBuf, process::Command};

use aether_driver::{Emit, OptimizationLevel, compile_source_with_optimization};
use aether_frontend::{SourceFile, analyze, parse_source};
use aether_middle::{build_ssa, lower_hir, verify_mir, verify_ssa};

struct Directory(PathBuf);

impl Directory {
    fn new() -> Self {
        static NEXT: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
        let path = std::env::temp_dir().join(format!(
            "aether-exception-v1-{}-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, std::sync::atomic::Ordering::Relaxed),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos()
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

fn compile(text: &str, optimization: OptimizationLevel) -> aether_driver::Compilation {
    compile_source_with_optimization(
        &SourceFile::new("exception.ae", text),
        &[Emit::Hir, Emit::Mir, Emit::Ssa],
        optimization,
    )
    .unwrap_or_else(|errors| panic!("{text}\n{errors:#?}"))
}

fn native(text: &str, optimization: OptimizationLevel) -> std::process::Output {
    let compilation = compile(text, optimization);
    let directory = Directory::new();
    let llvm = directory.0.join("program.ll");
    let executable = directory.0.join("program");
    fs::write(&llvm, compilation.llvm).unwrap();
    let option = match optimization {
        OptimizationLevel::O0 => "-O0",
        OptimizationLevel::O2 => "-O2",
    };
    let linked = Command::new("clang")
        .args(["-Wno-override-module", option, "-x", "ir"])
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
    Command::new(executable).output().unwrap()
}

fn diagnostics(text: &str) -> Vec<String> {
    compile_source_with_optimization(
        &SourceFile::new("bad_exception.ae", text),
        &[],
        OptimizationLevel::O0,
    )
    .unwrap_err()
    .into_iter()
    .map(|diagnostic| format!("{} {}", diagnostic.code, diagnostic.message))
    .collect()
}

const PREFIX: &str = "open class Problem:Exception{public init(){}}";

#[test]
fn ordered_nominal_catches_and_explicit_exception_ir() {
    let text = format!(
        "{PREFIX} int fail(){{throw Problem();}}int bridge(){{return fail();}}int main(){{try{{bridge();}}catch(Problem p){{return 17;}}catch(Exception e){{return 18;}}return 19;}}"
    );
    let compilation = compile(&text, OptimizationLevel::O0);
    assert!(compilation.dumps[&Emit::Hir].contains("Throw"));
    assert!(compilation.dumps[&Emit::Hir].contains("transfer: true"));
    assert!(compilation.dumps[&Emit::Hir].contains("Try"));
    assert!(compilation.dumps[&Emit::Mir].contains("landing_pad"));
    assert!(compilation.dumps[&Emit::Mir].contains("ExceptionMatches"));
    assert!(compilation.dumps[&Emit::Ssa].contains("exception_events"));
    assert!(compilation.llvm.contains("landingpad { ptr, i32 }"));
    assert!(compilation.llvm.contains("invoke i64"));
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        assert_eq!(native(&text, optimization).status.code(), Some(17));
    }
}

#[test]
fn lvalue_alias_rethrow_nested_handlers_and_exceptional_cleanup() {
    let lvalue = format!(
        "{PREFIX} int main(){{Problem p=Problem();try{{throw p;}}catch(Problem e){{return 21;}}}}"
    );
    assert!(compile(&lvalue, OptimizationLevel::O0).dumps[&Emit::Hir].contains("transfer: false"));
    let rethrow = format!(
        "{PREFIX} int inner(){{try{{throw Problem();}}catch(Problem e){{throw;}}}}int main(){{try{{inner();}}catch(Exception e){{return 23;}}return 24;}}"
    );
    let cleanup = format!(
        "{PREFIX} class Holder{{public init(){{}}}}int fail(){{throw Problem();}}int main(){{try{{Buffer<int> b=Buffer<int>(4,7);Holder h=Holder();fail();}}catch(Problem e){{return 25;}}return 26;}}"
    );
    let direct_method = format!(
        "{PREFIX} class Worker{{public init(){{}}public int run(){{throw Problem();}}}}int main(){{Worker w=Worker();try{{w.run();}}catch(Problem e){{return 27;}}return 28;}}"
    );
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        assert_eq!(native(&lvalue, optimization).status.code(), Some(21));
        assert_eq!(native(&rethrow, optimization).status.code(), Some(23));
        assert_eq!(native(&cleanup, optimization).status.code(), Some(25));
        assert_eq!(native(&direct_method, optimization).status.code(), Some(27));
    }
    let rethrow_ir = compile(&rethrow, OptimizationLevel::O0);
    assert!(rethrow_ir.dumps[&Emit::Hir].contains("Rethrow"));
    assert!(rethrow_ir.dumps[&Emit::Mir].contains("Rethrow"));
    assert!(rethrow_ir.llvm.contains("@__cxa_rethrow"));
}

#[test]
fn exception_free_program_has_no_aether_eh_runtime() {
    let compilation = compile("int main(){return 0;}", OptimizationLevel::O2);
    assert!(!compilation.llvm.contains("@__cxa_"));
    assert!(!compilation.llvm.contains("personality ptr"));
    assert!(!compilation.llvm.contains("aether_exception"));
}

#[test]
fn root_is_deterministic_and_traps_are_not_aether_exceptions() {
    let unhandled = format!("{PREFIX} int main(){{throw Problem();}}");
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        let output = native(&unhandled, optimization);
        assert_eq!(output.status.code(), Some(70));
        assert_eq!(
            String::from_utf8_lossy(&output.stderr),
            "unhandled Aether exception\n"
        );
    }
    let trap = format!(
        "{PREFIX} int main(){{int z=0;try{{return 1/z;}}catch(Exception e){{return 31;}}}}"
    );
    assert_eq!(native(&trap, OptimizationLevel::O0).status.code(), None);
}

#[test]
fn semantic_frontier_is_rejected() {
    let cases = [
        ("class Plain{}int main(){throw Plain();}", "E0432"),
        ("int main(){throw;}", "E0434"),
        (
            "open class P:Exception{}class C:P{}int main(){try{}catch(P p){}catch(C c){}}",
            "E0435",
        ),
        (
            "class P:Exception{}int f(){throw P();}class C{public init(){f();}}int main(){}",
            "E0436",
        ),
        (
            "open class Exception{}int main(){throw Exception();}",
            "E0431",
        ),
    ];
    for (text, code) in cases {
        let diagnostics = diagnostics(text);
        assert!(
            diagnostics
                .iter()
                .any(|diagnostic| diagnostic.contains(code)),
            "{text}: {diagnostics:#?}"
        );
    }
}

#[test]
fn mir_and_ssa_exception_metadata_corruption_is_rejected() {
    let text =
        format!("{PREFIX} int main(){{try{{throw Problem();}}catch(Exception e){{return 0;}}}}");
    let hir = analyze(parse_source(&SourceFile::new("corrupt.ae", &text)).unwrap()).unwrap();
    let mut mir = lower_hir(hir);
    mir.functions
        .iter_mut()
        .find(|function| !function.exception_events.is_empty())
        .unwrap()
        .exception_events
        .clear();
    assert!(verify_mir(mir).is_err());

    let hir = analyze(parse_source(&SourceFile::new("corrupt.ae", &text)).unwrap()).unwrap();
    let verified = verify_mir(lower_hir(hir)).unwrap();
    let mut ssa = build_ssa(&verified);
    let function = ssa
        .functions
        .iter_mut()
        .find(|function| !function.exception_events.is_empty())
        .unwrap();
    function.exception_events.clear();
    assert!(verify_ssa(ssa).is_err());
}
