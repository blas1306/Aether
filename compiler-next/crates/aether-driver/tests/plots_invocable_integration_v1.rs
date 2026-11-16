//! PLOTS-INVOCABLE-INTEGRATION-V1 productive API qualification.

use std::{fs, path::PathBuf, process::Command};

use aether_driver::{
    ClangToolchain, Compilation, CompilationSession, Emit, OptimizationLevel,
    compile_session_with_optimization,
};

const GRAPHICS: &str = include_str!("../../../../graphics/src/lib.ae");
const GRAPHICS_SVG: &str = include_str!("../../../../graphics/src/svg.ae");
const PLOTS: &str = include_str!("../../../../plots/src/lib.ae");
const PLOTS_SVG: &str = include_str!("../../../../plots/src/svg.ae");

struct Project(PathBuf);

impl Project {
    fn productive(label: &str, source: &str, with_svg: bool) -> Self {
        static NEXT: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
        let root = std::env::temp_dir().join(format!(
            "aether-plots-invocable-{label}-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, std::sync::atomic::Ordering::Relaxed)
        ));
        fs::create_dir(&root).unwrap();
        fs::write(root.join("graphics.ae"), GRAPHICS).unwrap();
        fs::write(root.join("plots.ae"), productive_plots()).unwrap();
        if with_svg {
            fs::write(root.join("graphics_svg.ae"), GRAPHICS_SVG).unwrap();
            fs::write(root.join("plots_svg.ae"), PLOTS_SVG).unwrap();
        }
        fs::write(root.join("main.ae"), source).unwrap();
        Self(root)
    }

    fn standalone(label: &str, source: &str) -> Self {
        static NEXT: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
        let root = std::env::temp_dir().join(format!(
            "aether-plots-overload-{label}-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, std::sync::atomic::Ordering::Relaxed)
        ));
        fs::create_dir(&root).unwrap();
        fs::write(root.join("main.ae"), source).unwrap();
        Self(root)
    }

    fn entry(&self) -> PathBuf {
        self.0.join("main.ae")
    }
}

impl Drop for Project {
    fn drop(&mut self) {
        fs::remove_dir_all(&self.0).unwrap();
    }
}

fn productive_plots() -> String {
    let signature =
        "public Figure2D plotFunction<C: Invocable<(float64), float64>>(\n    ref C target,";
    assert_eq!(PLOTS.matches(signature).count(), 1);
    PLOTS.to_owned()
}

fn compile_productive(
    source: &str,
    with_svg: bool,
    optimization: OptimizationLevel,
) -> Result<Compilation, Vec<aether_frontend::Diagnostic>> {
    let project = Project::productive("compile", source, with_svg);
    compile_session_with_optimization(
        CompilationSession::discover(&project.entry()).unwrap(),
        &[Emit::Hir, Emit::Mir, Emit::Ssa, Emit::Llvm],
        optimization,
    )
}

fn execute(llvm: &str, label: &str, optimization: OptimizationLevel) -> i32 {
    static NEXT: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
    let executable = std::env::temp_dir().join(format!(
        "aether-plots-invocable-{label}-{}-{}-{optimization:?}",
        std::process::id(),
        NEXT.fetch_add(1, std::sync::atomic::Ordering::Relaxed)
    ));
    ClangToolchain::default()
        .with_optimization(optimization)
        .link_executable(llvm, &executable)
        .unwrap();
    let status = Command::new(&executable)
        .status()
        .unwrap()
        .code()
        .unwrap_or(-1);
    let _ = fs::remove_file(executable);
    status
}

fn link(llvm: &str, label: &str, optimization: OptimizationLevel) {
    static NEXT: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
    let executable = std::env::temp_dir().join(format!(
        "aether-runtime-dependencies-{label}-{}-{}-{optimization:?}",
        std::process::id(),
        NEXT.fetch_add(1, std::sync::atomic::Ordering::Relaxed)
    ));
    ClangToolchain::default()
        .with_optimization(optimization)
        .link_executable(llvm, &executable)
        .unwrap();
    let _ = fs::remove_file(executable);
}

fn instrument_closure_counts(llvm: &str) -> String {
    let checks = r"  %plots_retains = load i64, ptr @aether_closure_retain_count
  %plots_releases = load i64, ptr @aether_closure_release_count
  %plots_destroys = load i64, ptr @aether_closure_destroy_count
  %plots_retain_ok = icmp eq i64 %plots_retains, 0
  %plots_release_ok = icmp eq i64 %plots_releases, 1
  %plots_destroy_ok = icmp eq i64 %plots_destroys, 1
  %plots_arc_ok = and i1 %plots_retain_ok, %plots_release_ok
  %plots_all_ok = and i1 %plots_arc_ok, %plots_destroy_ok
  %plots_status = select i1 %plots_all_ok, i32 %process_status, i32 99
  ret i32 %plots_status";
    let instrumented = llvm.replace("  ret i32 %process_status", checks);
    assert_ne!(instrumented, llvm, "runtime counter hook was not found");
    instrumented
}

const CORE_CONSUMER: &str = r"
package q;import plots as p;
float64 square(float64 x){return x*x;}
int main(){
  p.FigureOptions o=p.defaultOptions();
  Function<(float64),float64> top=square;
  p.Figure2D a=p.plotFunction(top,-2.0,2.0,usize(5),&o);
  float64 scale=2.0;
  var closure=(float64 x) capture(copy scale)=>scale*x;
  p.Figure2D b=p.plotFunction(closure,0.0,2.0,usize(3),&o);
  if(closure(3.0)!=6.0){return 1;}
  return 0;
}";

#[test]
fn productive_api_accepts_function_and_closure_borrowed_o0_o2() {
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        let compilation = compile_productive(CORE_CONSUMER, false, optimization)
            .unwrap_or_else(|diagnostics| panic!("{diagnostics:#?}"));
        assert_eq!(execute(&compilation.llvm, "core", optimization), 0);
        assert_eq!(
            execute(
                &instrument_closure_counts(&compilation.llvm),
                "counts",
                optimization
            ),
            0
        );
        assert!(compilation.dumps[&Emit::Mir].contains("ClosureCall"));
        assert!(compilation.dumps[&Emit::Mir].contains("EndClosureBorrow"));
        for forbidden in [
            "BorrowedCapabilityInvoke",
            "CapabilityInvoke",
            "invocable_adapter",
        ] {
            assert!(!compilation.llvm.contains(forbidden));
        }
    }
}

#[test]
fn productive_api_renders_equivalent_deterministic_svg_o0_o2() {
    let source = r#"
package q;import plots as p;import plots.svg as svg;
float64 square(float64 x){return x*x;}
int main(){
  Function<(float64),float64> top=square;
  float64 factor=1.0;
  var closure=(float64 x) capture(copy factor)=>factor*x*x;
  p.FigureOptions o=p.defaultOptions();
  o.title="Invocable SVG";
  o.xLabel="input";
  o.yLabel="square";
  p.Figure2D functionFigure=p.plotFunction(top,0.0,2.0,usize(3),&o);
  p.Figure2D closureFigure=p.plotFunction(closure,0.0,2.0,usize(3),&o);
  string functionDocument=svg.render(&functionFigure);
  string closureDocument=svg.render(&closureFigure);
  string repeatedDocument=svg.render(&closureFigure);
  if(byteLength(functionDocument)==0||functionDocument!=closureDocument||
     closureDocument!=repeatedDocument||closure(3.0)!=9.0){return 1;}
  return 0;
}"#;
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        let compilation = compile_productive(source, true, optimization).unwrap();
        assert!(!compilation.llvm.contains("@aether_io_read_line"));
        assert!(!compilation.llvm.contains("@aether_io_read_text"));
        assert!(!compilation.llvm.contains("@aether_io_write_text"));
        assert_eq!(execute(&compilation.llvm, "svg", optimization), 0);
    }
}

#[test]
fn reachable_io_from_program_with_closure_emits_each_required_helper_once_o0_o2() {
    let source = r"
package q;import std.IO;
int main(){
  int offset=1;
  var closure=(int value) capture(copy offset)=>value+offset;
  std.IO.ReadLineResult input=std.IO.readLine();
  return closure(1)-2;
}";
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        let project = Project::standalone("reachable-io", source);
        let compilation = compile_session_with_optimization(
            CompilationSession::discover(&project.entry()).unwrap(),
            &[Emit::Llvm],
            optimization,
        )
        .unwrap();
        assert_eq!(
            compilation
                .llvm
                .matches("define internal { i32, ptr } @aether_io_read_line()")
                .count(),
            1
        );
        assert_eq!(
            compilation
                .llvm
                .matches("call { i32, ptr } @aether_io_read_line()")
                .count(),
            1
        );
        link(&compilation.llvm, "reachable-io", optimization);
    }
}

#[test]
fn concrete_and_generic_same_name_are_ambiguous_for_function_lvalues() {
    let source = r"
int apply(Function<(int),int> f,int x){return f(x);}
int apply<C:Invocable<(int),int>>(ref C f,int x){return f(x);}
int inc(int x){return x+1;}
int main(){Function<(int),int> f=inc;return apply(f,1)-2;}
";
    let project = Project::standalone("ambiguous", source);
    let diagnostics = compile_session_with_optimization(
        CompilationSession::discover(&project.entry()).unwrap(),
        &[Emit::Hir],
        OptimizationLevel::O0,
    )
    .unwrap_err();
    let text = format!("{diagnostics:#?}");
    assert!(text.contains("E0461"), "{text}");
    assert!(text.contains("ambiguous overload"), "{text}");
}

#[test]
fn productive_api_rejects_incompatible_callback_signatures() {
    let cases = [
        "int bad(int x){return x;}int main(){p.FigureOptions o=p.defaultOptions();p.Figure2D f=p.plotFunction(bad,0.0,1.0,usize(2),&o);return 0;}",
        "float64 bad(float64 x,float64 y){return x+y;}int main(){p.FigureOptions o=p.defaultOptions();p.Figure2D f=p.plotFunction(bad,0.0,1.0,usize(2),&o);return 0;}",
        "int main(){int n=1;var bad=(int x) capture(copy n)=>x+n;p.FigureOptions o=p.defaultOptions();p.Figure2D f=p.plotFunction(bad,0.0,1.0,usize(2),&o);return 0;}",
    ];
    for body in cases {
        let source = format!("package q;import plots as p;{body}");
        let diagnostics = compile_productive(&source, false, OptimizationLevel::O0).unwrap_err();
        let text = format!("{diagnostics:#?}");
        assert!(
            text.contains("E0205") || text.contains("Invocable"),
            "{text}"
        );
    }
}

#[test]
fn productive_api_closure_unwind_cleans_up_and_owner_remains_reusable_o0_o2() {
    let source = r"
package q;import plots as p;
open class Stop:Exception{public init(){}}
float64 failAtZero(float64 x){if(x==0.0){throw Stop();}return x;}
int main(){
  float64 marker=1.0;
  var closure=(float64 x) capture(copy marker)=>failAtZero(x)+marker;
  p.FigureOptions o=p.defaultOptions();
  int caught=0;
  try{p.Figure2D figure=p.plotFunction(closure,-1.0,1.0,usize(3),&o);}
  catch(Stop error){caught=1;}
  if(caught!=1||closure(1.0)!=2.0){return 1;}
  return 0;
}";
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        let compilation = compile_productive(source, false, optimization)
            .unwrap_or_else(|diagnostics| panic!("{diagnostics:#?}"));
        assert_eq!(execute(&compilation.llvm, "unwind", optimization), 0);
        assert_eq!(
            execute(
                &instrument_closure_counts(&compilation.llvm),
                "unwind-counts",
                optimization
            ),
            0
        );
    }
}
