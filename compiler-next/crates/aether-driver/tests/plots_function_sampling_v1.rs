//! PLOTS-FUNCTION-SAMPLING-V1 functional, ownership, SVG and IR qualification.

use std::{fs, path::PathBuf, process::Command};

use aether_driver::{
    ClangToolchain, Compilation, CompilationSession, Emit, OptimizationLevel,
    compile_session_with_optimization,
};

const GRAPHICS: &str = include_str!("../../../../graphics/src/lib.ae");
const GRAPHICS_SVG: &str = include_str!("../../../../graphics/src/svg.ae");
const PLOTS: &str = include_str!("../../../../plots/src/lib.ae");
const PLOTS_SVG: &str = include_str!("../../../../plots/src/svg.ae");
const CONSUMER: &str = include_str!("../../../../plots/tests/function_consumer/src/main.ae");
const CONSUMER_FUNCTIONS: &str =
    include_str!("../../../../plots/tests/function_consumer/src/functions.ae");
const FUNCTION_GOLDEN: &str = include_str!("../../../../plots/tests/goldens/function_sine.svg");

struct Project(PathBuf);

impl Project {
    fn new(label: &str, source: &str) -> Self {
        static NEXT: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
        let root = std::env::temp_dir().join(format!(
            "aether-plots-function-{label}-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, std::sync::atomic::Ordering::Relaxed)
        ));
        fs::create_dir(&root).unwrap();
        fs::write(root.join("graphics.ae"), GRAPHICS).unwrap();
        fs::write(root.join("graphics_svg.ae"), GRAPHICS_SVG).unwrap();
        fs::write(root.join("plots.ae"), PLOTS).unwrap();
        fs::write(root.join("plots_svg.ae"), PLOTS_SVG).unwrap();
        fs::write(root.join("functions.ae"), CONSUMER_FUNCTIONS).unwrap();
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

fn compile(source: &str, optimization: OptimizationLevel) -> Compilation {
    let project = Project::new("compile", source);
    compile_session_with_optimization(
        CompilationSession::discover(&project.entry()).unwrap(),
        &[Emit::Hir, Emit::Mir, Emit::Ssa, Emit::Llvm],
        optimization,
    )
    .unwrap_or_else(|diagnostics| panic!("{source}\n{diagnostics:#?}"))
}

fn output(source: &str, optimization: OptimizationLevel) -> std::process::Output {
    let project = Project::new("run", source);
    let compilation = compile_session_with_optimization(
        CompilationSession::discover(&project.entry()).unwrap(),
        &[Emit::Llvm],
        optimization,
    )
    .unwrap_or_else(|diagnostics| panic!("{source}\n{diagnostics:#?}"));
    let executable = project.0.join("qualification");
    ClangToolchain::default()
        .with_optimization(optimization)
        .link_executable(&compilation.llvm, &executable)
        .unwrap();
    Command::new(executable).output().unwrap()
}

fn run(source: &str, optimization: OptimizationLevel) -> i32 {
    output(source, optimization).status.code().unwrap_or(-1)
}

fn run_with_balanced_heap(source: &str, optimization: OptimizationLevel) -> i32 {
    let compilation = compile(source, optimization);
    let guarded = compilation.llvm.replace(
        "  %process_status = trunc i64 %aether_result to i32",
        "  %sample_allocs = load i64, ptr @aether_heap_alloc_count\n  %sample_frees = load i64, ptr @aether_heap_free_count\n  %sample_heap_ok = icmp eq i64 %sample_allocs, %sample_frees\n  %sample_result_ok = icmp eq i64 %aether_result, 0\n  %sample_all_ok = and i1 %sample_heap_ok, %sample_result_ok\n  %process_status = select i1 %sample_all_ok, i32 0, i32 99",
    );
    assert_ne!(guarded, compilation.llvm);
    let project = Project::new("heap", "package q;int main(){return 0;}");
    let executable = project.0.join("heap-check");
    ClangToolchain::default()
        .with_optimization(optimization)
        .link_executable(&guarded, &executable)
        .unwrap();
    Command::new(executable)
        .status()
        .unwrap()
        .code()
        .unwrap_or(-1)
}

fn aether_string(path: &std::path::Path) -> String {
    path.to_string_lossy()
        .replace('\\', "\\\\")
        .replace('"', "\\\"")
}

fn render(body: &str, optimization: OptimizationLevel) -> String {
    let project = Project::new("render", "package q;int main(){return 0;}");
    let path = project.0.join("result.svg");
    let source = format!(
        "package q;import plots as p;import plots.svg as svg;import graphics;float64 wave(float64 x){{return sin(x);}}int main(){{{body}string path=\"{}\";svg.save(&figure,&path);return 0;}}",
        aether_string(&path)
    );
    fs::write(project.entry(), &source).unwrap();
    let compilation = compile_session_with_optimization(
        CompilationSession::discover(&project.entry()).unwrap(),
        &[Emit::Llvm],
        optimization,
    )
    .unwrap_or_else(|diagnostics| panic!("{source}\n{diagnostics:#?}"));
    let executable = project.0.join("render");
    ClangToolchain::default()
        .with_optimization(optimization)
        .link_executable(&compilation.llvm, &executable)
        .unwrap();
    assert_eq!(Command::new(executable).status().unwrap().code(), Some(0));
    fs::read_to_string(path).unwrap()
}

const FUNCTION_BODY: &str = r#"
p.FigureOptions options=p.defaultOptions();options.title="sin(x) sampled";options.xLabel="x";options.yLabel="sin(x)";p.Figure2D figure=p.plotFunction(wave,-3.141592653589793,3.141592653589793,usize(17),&options);
"#;

#[test]
fn local_and_imported_consumers_run_at_o0_o2() {
    let local = r"
package q;import plots as p;float64 square(float64 x){return x*x;}int main(){p.FigureOptions o=p.defaultOptions();p.Figure2D f=p.plotFunction(square,-2.0,2.0,usize(5),&o);return 0;}
";
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        assert_eq!(run(local, optimization), 0, "{optimization:?}");
        assert_eq!(run(CONSUMER, optimization), 0, "{optimization:?}");
    }
}

#[test]
fn anonymous_function_consumer_runs_without_plots_changes_at_o0_o2() {
    let source = r"
package q;import plots as p;
int main(){
  p.FigureOptions options=p.defaultOptions();
  p.Figure2D figure=p.plotFunction((float64 x)=>x*x,-2.0,2.0,usize(5),&options);
  return 0;
}";
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        assert_eq!(run(source, optimization), 0, "{optimization:?}");
    }
    let compilation = compile(source, OptimizationLevel::O0);
    for phase in [Emit::Hir, Emit::Mir, Emit::Ssa] {
        let dump = &compilation.dumps[&phase];
        assert!(dump.contains("$lambda$"));
        assert!(dump.contains("FunctionRef"));
        assert!(dump.contains("IndirectCall"));
        assert!(!dump.contains("Closure"));
    }
}

#[test]
fn validation_order_cardinality_throw_and_late_options_errors_are_exact() {
    let source = r"
package q;import plots as p;import graphics;
open class TargetException:Exception{public init(){}}
float64 observed(float64 x){println(x);return x;}
float64 failAtZero(float64 x){println(x);if(x==0.0){throw TargetException();}return x;}
float64 nonfinite(float64 x){println(x);float64 z=0.0;return z/z;}
int main(){int caught=0;p.FigureOptions o=p.defaultOptions();
try{p.Figure2D f=p.plotFunction(observed,0.0,1.0,usize(0),&o);}catch(p.InvalidSampleCountException e){caught=caught+1;}
try{p.Figure2D f=p.plotFunction(observed,0.0,1.0,usize(1),&o);}catch(p.InvalidSampleCountException e){caught=caught+1;}
float64 z=0.0;float64 nan=z/z;float64 inf=1.0/z;
try{p.Figure2D f=p.plotFunction(observed,nan,1.0,usize(2),&o);}catch(p.InvalidSampleIntervalException e){caught=caught+1;}
try{p.Figure2D f=p.plotFunction(observed,1.0,1.0,usize(2),&o);}catch(p.InvalidSampleIntervalException e){caught=caught+1;}
try{p.Figure2D f=p.plotFunction(observed,2.0,1.0,usize(2),&o);}catch(p.InvalidSampleIntervalException e){caught=caught+1;}
try{p.Figure2D f=p.plotFunction(observed,-1.7976931348623157e308,1.7976931348623157e308,usize(2),&o);}catch(p.PlotRangeException e){caught=caught+1;}
try{p.Figure2D f=p.plotFunction(failAtZero,-1.0,1.0,usize(3),&o);}catch(TargetException e){caught=caught+1;}
try{p.Figure2D f=p.plotFunction(nonfinite,-1.0,1.0,usize(3),&o);}catch(p.NoFiniteDataException e){caught=caught+1;}
o=p.defaultOptions();o.viewport=graphics.Viewport(96.0,480.0);
try{p.Figure2D f=p.plotFunction(observed,0.0,1.0,usize(2),&o);}catch(p.InvalidFigureException e){caught=caught+1;}
return caught-9;}
";
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        let actual = output(source, optimization);
        assert_eq!(actual.status.code(), Some(0), "{optimization:?}");
        let lines = String::from_utf8(actual.stdout).unwrap();
        assert_eq!(lines.lines().count(), 7, "{optimization:?}: {lines}");
        assert_eq!(lines, "-1\n0\n-1\n0\n1\n0\n1\n");
    }
}

#[test]
fn grid_edge_cases_math_families_large_count_and_discontinuities_run() {
    let source = r"
package q;import plots as p;
float64 polynomial(float64 x){return x*x-2.0*x+1.0;}
float64 trigonometric(float64 x){return sin(x);}
float64 exponential(float64 x){return exp(x);}
float64 logarithm(float64 x){return ln(x);}
float64 constant(float64 x){return 7.0;}
float64 identity(float64 x){return x;}
float64 pole(float64 x){return 1.0/x;}
float64 jump(float64 x){if(x<0.0){return -1.0;}return 1.0;}
int main(){p.FigureOptions o=p.defaultOptions();
p.Figure2D a=p.plotFunction(polynomial,-3.0,2.0,usize(9),&o);
p.Figure2D b=p.plotFunction(trigonometric,-3.141592653589793,3.141592653589793,usize(9),&o);
p.Figure2D c=p.plotFunction(exponential,-2.0,2.0,usize(9),&o);
p.Figure2D d=p.plotFunction(logarithm,-1.0,2.0,usize(7),&o);
p.Figure2D e=p.plotFunction(constant,-4.0,-2.0,usize(2),&o);
p.Figure2D f=p.plotFunction(identity,9007199254740992.0,9007199254740994.0,usize(4),&o);
p.Figure2D g=p.plotFunction(identity,-1.0,1.0,usize(100001),&o);
// The odd grid's middle coordinate must be exactly zero before qualifying a sampled pole.
float64 middle=-1.0+(1.0-(-1.0))*(float64(2)/float64(4));if(middle!=0.0){return 1;}
p.Figure2D h=p.plotFunction(pole,-1.0,1.0,usize(5),&o);
p.Figure2D i=p.plotFunction(pole,-1.0,1.0,usize(4),&o);
p.Figure2D j=p.plotFunction(jump,-1.0,1.0,usize(4),&o);
return 0;}
";
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        assert_eq!(run(source, optimization), 0, "{optimization:?}");
    }
}

#[test]
fn temporary_array_and_line_resources_are_balanced_on_return_and_unwind() {
    let normal = r"
package q;import plots as p;float64 f(float64 x){return x*x;}int main(){p.FigureOptions o=p.defaultOptions();p.Figure2D figure=p.plotFunction(f,-1.0,1.0,usize(33),&o);return 0;}
";
    let throwing = r"
package q;import plots as p;open class Stop:Exception{public init(){}}float64 f(float64 x){if(x==0.0){throw Stop();}return x;}int main(){p.FigureOptions o=p.defaultOptions();try{p.Figure2D figure=p.plotFunction(f,-1.0,1.0,usize(3),&o);}catch(Stop error){return 0;}return 1;}
";
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        assert_eq!(run_with_balanced_heap(normal, optimization), 0);
        assert_eq!(run_with_balanced_heap(throwing, optimization), 0);
    }
}

#[test]
fn plot_function_is_byte_equivalent_to_the_normative_manual_array() {
    let sampled = render(FUNCTION_BODY, OptimizationLevel::O0);
    let manual = render(
        r#"
Array<p.DataPoint> points=Array<p.DataPoint>(usize(17),p.DataPoint(0.0,0.0));float64 a=-3.141592653589793;float64 b=3.141592653589793;float64 span=b-a;usize n=17;usize d=n-1;usize i=0;while(i<n){float64 x=a;if(i==d){x=b;}else{if(i!=0){float64 t=float64(i)/float64(d);x=a+span*t;}}points[i]=p.DataPoint(x,wave(x));i=i+1;}p.FigureOptions options=p.defaultOptions();options.title="sin(x) sampled";options.xLabel="x";options.yLabel="sin(x)";p.Figure2D figure=p.line(&points,&options);
"#,
        OptimizationLevel::O0,
    );
    assert_eq!(sampled, manual);
}

#[test]
fn svg_golden_is_xml_and_byte_identical_at_o0_o2() {
    let o0 = render(FUNCTION_BODY, OptimizationLevel::O0);
    let o2 = render(FUNCTION_BODY, OptimizationLevel::O2);
    assert_eq!(o0, o2);
    assert_eq!(o0, FUNCTION_GOLDEN);
    let document = roxmltree::Document::parse(&o0).unwrap();
    assert_eq!(
        document.root_element().tag_name().namespace(),
        Some("http://www.w3.org/2000/svg")
    );
}

#[test]
fn lowering_uses_function_values_indirect_calls_and_existing_line_path() {
    let source = r"
package q;import plots as p;float64 f(float64 x){return x*x;}int main(){p.FigureOptions o=p.defaultOptions();p.Figure2D figure=p.plotFunction(f,-1.0,1.0,usize(3),&o);return 0;}
";
    let compilation = compile(source, OptimizationLevel::O0);
    for phase in [Emit::Hir, Emit::Mir, Emit::Ssa] {
        let dump = &compilation.dumps[&phase];
        assert!(dump.contains("FunctionRef"));
        assert!(dump.contains("IndirectCall"));
        assert!(dump.contains("Array<"));
    }
    assert!(compilation.llvm.contains("invoke double %"));
    assert!(PLOTS.contains("return line(&points, options);"));
    for forbidden in ["matplotlib", "numpy", "registry", "intrinsiccall"] {
        assert!(!PLOTS.to_ascii_lowercase().contains(forbidden));
    }
    assert!(PLOTS_SVG.contains("graphics.svg.render"));
}
