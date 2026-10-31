//! PLOTS-2D-LINE-V1 functional, ownership, SVG and IR qualification.

use std::{fs, path::PathBuf, process::Command};

use aether_driver::{
    ClangToolchain, Compilation, CompilationSession, Emit, OptimizationLevel,
    compile_session_with_optimization,
};

const GRAPHICS: &str = include_str!("../../../../graphics/src/lib.ae");
const GRAPHICS_SVG: &str = include_str!("../../../../graphics/src/svg.ae");
const PLOTS: &str = include_str!("../../../../plots/src/lib.ae");
const PLOTS_SVG: &str = include_str!("../../../../plots/src/svg.ae");
const CONSUMER: &str = include_str!("../../../../plots/tests/consumer/src/main.ae");
const PARABOLA_GOLDEN: &str = include_str!("../../../../plots/tests/goldens/parabola.svg");
const GAPS_GOLDEN: &str = include_str!("../../../../plots/tests/goldens/gaps.svg");
const SINGLETON_GOLDEN: &str = include_str!("../../../../plots/tests/goldens/singleton.svg");

struct Project(PathBuf);

impl Project {
    fn new(label: &str, source: &str) -> Self {
        static NEXT: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
        let root = std::env::temp_dir().join(format!(
            "aether-plots-{label}-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, std::sync::atomic::Ordering::Relaxed)
        ));
        fs::create_dir(&root).unwrap();
        fs::write(root.join("graphics.ae"), GRAPHICS).unwrap();
        fs::write(root.join("graphics_svg.ae"), GRAPHICS_SVG).unwrap();
        fs::write(root.join("plots.ae"), PLOTS).unwrap();
        fs::write(root.join("plots_svg.ae"), PLOTS_SVG).unwrap();
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

fn run(source: &str, optimization: OptimizationLevel) -> i32 {
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
    Command::new(executable).status().unwrap().code().unwrap()
}

fn aether_string(path: &std::path::Path) -> String {
    path.to_string_lossy()
        .replace('\\', "\\\\")
        .replace('"', "\\\"")
}

fn render(body: &str, optimization: OptimizationLevel) -> String {
    let project = Project::new("render", "package plotsQualification;int main(){return 0;}");
    let output = project.0.join("result.svg");
    let source = format!(
        "package plotsQualification;import plots as p;import plots.svg as svg;import graphics;int main(){{{body}string path=\"{}\";svg.save(&figure,&path);return 0;}}",
        aether_string(&output)
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
    fs::read_to_string(output).unwrap()
}

const PARABOLA: &str = r#"
Array<p.DataPoint> points={p.DataPoint(-2.0,4.0),p.DataPoint(-1.0,1.0),p.DataPoint(0.0,0.0),p.DataPoint(1.0,1.0),p.DataPoint(2.0,4.0)};
p.FigureOptions options=p.defaultOptions();options.title="Parabola: y = x*x";options.xLabel="x";options.yLabel="y";options.line=p.LineStyle(graphics.Color(uint8(180),uint8(40),uint8(40),uint8(255)),3.0);p.Figure2D figure=p.line(&points,&options);
"#;

const GAPS: &str = r#"
float64 zero=0.0;float64 nan=zero/zero;Array<p.DataPoint> points={p.DataPoint(-1.0,-1.0),p.DataPoint(0.0,0.0),p.DataPoint(nan,nan),p.DataPoint(0.5,1.0),p.DataPoint(nan,0.0),p.DataPoint(1.0,-1.0),p.DataPoint(2.0,0.0)};p.FigureOptions options=p.defaultOptions();options.title="Finite gaps";p.Figure2D figure=p.line(&points,&options);
"#;

const SINGLETON: &str = r#"
Array<p.DataPoint> points={p.DataPoint(5.0,-3.0)};p.FigureOptions options=p.defaultOptions();options.title="Single point";options.xLabel="constant x";options.yLabel="constant y";p.Figure2D figure=p.line(&points,&options);
"#;

#[test]
fn public_consumer_check_build_run_equivalent_o0_o2() {
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        assert_eq!(run(CONSUMER, optimization), 0, "{optimization:?}");
    }
}

#[test]
fn nominal_errors_and_backend_errors_are_exact_o0_o2() {
    let source = r#"
package plotsQualification;import plots as p;import plots.svg as svg;import graphics;
float64 nan(){float64 zero=0.0;return zero/zero;}float64 inf(){float64 zero=0.0;return 1.0/zero;}
int main(){int caught=0;p.FigureOptions o=p.defaultOptions();Array<p.DataPoint> empty={};try{p.Figure2D f=p.line(&empty,&o);}catch(p.EmptySeriesException e){caught=caught+1;}
 Array<p.DataPoint> bad={p.DataPoint(nan(),0.0),p.DataPoint(0.0,inf())};try{p.Figure2D f=p.line(&bad,&o);}catch(p.NoFiniteDataException e){caught=caught+1;}
 Array<p.DataPoint> one={p.DataPoint(0.0,0.0)};o.viewport=graphics.Viewport(96.0,480.0);try{p.Figure2D f=p.line(&one,&o);}catch(p.InvalidFigureException e){caught=caught+1;}
 o=p.defaultOptions();o.line=p.LineStyle(graphics.Color(uint8(0),uint8(0),uint8(0),uint8(255)),0.0);try{p.Figure2D f=p.line(&one,&o);}catch(p.InvalidFigureException e){caught=caught+1;}
 o=p.defaultOptions();o.xLimits=p.LimitMode.Explicit(p.Limits(2.0,1.0));try{p.Figure2D f=p.line(&one,&o);}catch(p.InvalidLimitsException e){caught=caught+1;}
 o=p.defaultOptions();o.xLimits=p.LimitMode.Explicit(p.Limits(nan(),1.0));try{p.Figure2D f=p.line(&one,&o);}catch(p.InvalidLimitsException e){caught=caught+1;}
 o=p.defaultOptions();o.xLimits=p.LimitMode.Explicit(p.Limits(-1.7976931348623157e308,1.7976931348623157e308));try{p.Figure2D f=p.line(&one,&o);}catch(p.PlotRangeException e){caught=caught+1;}
 o=p.defaultOptions();o.xLimits=p.LimitMode.Explicit(p.Limits(0.0,1.0));Array<p.DataPoint> far={p.DataPoint(1.7976931348623157e308,0.0)};try{p.Figure2D f=p.line(&far,&o);graphics.Scene s=f.scene();}catch(p.PlotRangeException e){caught=caught+1;}
 o=p.defaultOptions();o.title="bad\0text";p.Figure2D text=p.line(&one,&o);try{string document=svg.render(&text);}catch(graphics.GraphicsTextException e){caught=caught+1;}
 return caught-9;}
"#;
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        assert_eq!(run(source, optimization), 0, "{optimization:?}");
    }
}

#[test]
fn runs_clipping_transform_ticks_and_painter_order_are_exact_o0_o2() {
    let source = r"
package plotsQualification;import plots as p;import graphics as g;
bool kind(ref g.Scene s,usize i,int wanted){int actual=-1;match((*s).commandAt(i)){g.Command.PushState=>{actual=0;}g.Command.PopState=>{actual=1;}g.Command.ConcatTransform(v)=>{actual=2;}g.Command.IntersectClipRect(v)=>{actual=3;}g.Command.DrawPoint(v,d,c)=>{actual=4;}g.Command.DrawLine(v,st)=>{actual=5;}g.Command.DrawPolyline(v,st)=>{actual=6;}g.Command.DrawRect(v,pa)=>{actual=7;}g.Command.DrawPath(v,pa)=>{actual=8;}g.Command.DrawText(v)=>{actual=9;}}return actual==wanted;}
int main(){float64 z=0.0;float64 nan=z/z;float64 inf=1.0/z;Array<p.DataPoint> a={p.DataPoint(-2.0,0.0),p.DataPoint(0.0,0.0),p.DataPoint(2.0,0.0),p.DataPoint(nan,nan),p.DataPoint(0.0,1.0),p.DataPoint(inf,0.0),p.DataPoint(0.0,-1.0),p.DataPoint(1.0,1.0)};p.FigureOptions o=p.defaultOptions();o.viewport=g.Viewport(196.0,212.0);o.xLimits=p.LimitMode.Explicit(p.Limits(-1.0,1.0));o.yLimits=p.LimitMode.Explicit(p.Limits(-1.0,1.0));p.Figure2D f=p.line(&a,&o);g.Scene s=f.scene();if(s.commandCount()!=28){return 1;}Array<int> expected={7,0,3,6,4,6,1,7,5,5,5,5,5,5,5,5,5,5,9,9,9,9,9,9,9,9,9,9};usize i=0;while(i<length(expected)){if(!kind(&s,i,expected[i])){return 2;}i=i+1;}
 match(s.commandAt(3)){g.Command.DrawPolyline(span,st)=>{g.Point a0=s.pointAt(span,0);g.Point a2=s.pointAt(span,2);if(span.length!=3||a0.x!=22.0||a0.y!=98.0||a2.x!=222.0||a2.y!=98.0){return 3;}}g.Command.PushState=>{return 3;}g.Command.PopState=>{return 3;}g.Command.ConcatTransform(v)=>{return 3;}g.Command.IntersectClipRect(v)=>{return 3;}g.Command.DrawPoint(v,d,c)=>{return 3;}g.Command.DrawLine(v,st)=>{return 3;}g.Command.DrawRect(v,pa)=>{return 3;}g.Command.DrawPath(v,pa)=>{return 3;}g.Command.DrawText(v)=>{return 3;}}
 match(s.commandAt(4)){g.Command.DrawPoint(point,d,c)=>{if(point.x!=122.0||point.y!=48.0||d!=2.0){return 4;}}g.Command.PushState=>{return 4;}g.Command.PopState=>{return 4;}g.Command.ConcatTransform(v)=>{return 4;}g.Command.IntersectClipRect(v)=>{return 4;}g.Command.DrawLine(v,st)=>{return 4;}g.Command.DrawPolyline(v,st)=>{return 4;}g.Command.DrawRect(v,pa)=>{return 4;}g.Command.DrawPath(v,pa)=>{return 4;}g.Command.DrawText(v)=>{return 4;}}
 match(s.commandAt(5)){g.Command.DrawPolyline(span,st)=>{g.Point a0=s.pointAt(span,0);g.Point a1=s.pointAt(span,1);if(span.length!=2||a0.x!=122.0||a0.y!=148.0||a1.x!=172.0||a1.y!=48.0){return 5;}}g.Command.PushState=>{return 5;}g.Command.PopState=>{return 5;}g.Command.ConcatTransform(v)=>{return 5;}g.Command.IntersectClipRect(v)=>{return 5;}g.Command.DrawPoint(v,d,c)=>{return 5;}g.Command.DrawLine(v,st)=>{return 5;}g.Command.DrawRect(v,pa)=>{return 5;}g.Command.DrawPath(v,pa)=>{return 5;}g.Command.DrawText(v)=>{return 5;}}
 return 0;}
";
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        assert_eq!(run(source, optimization), 0, "{optimization:?}");
    }
}

#[test]
fn full_svg_goldens_are_xml_and_byte_identical_o0_o2() {
    for (body, golden) in [
        (PARABOLA, PARABOLA_GOLDEN),
        (GAPS, GAPS_GOLDEN),
        (SINGLETON, SINGLETON_GOLDEN),
    ] {
        let o0 = render(body, OptimizationLevel::O0);
        let o2 = render(body, OptimizationLevel::O2);
        assert_eq!(o0, o2);
        assert_eq!(o0, golden);
        let document = roxmltree::Document::parse(&o0).unwrap();
        assert_eq!(
            document.root_element().tag_name().namespace(),
            Some("http://www.w3.org/2000/svg")
        );
    }
}

#[test]
fn hir_mir_ssa_llvm_use_general_ownership_and_direct_graphics_calls() {
    let compilation = compile(CONSUMER, OptimizationLevel::O0);
    for phase in [Emit::Hir, Emit::Mir, Emit::Ssa] {
        let dump = &compilation.dumps[&phase];
        assert!(dump.contains("StringFieldAlias"));
        assert!(dump.contains("Buffer<"));
    }
    assert!(compilation.llvm.contains("aether_drop_str"));
    assert!(compilation.llvm.contains("SceneBuilder"));
    for forbidden in [
        "matplotlib",
        "numpy",
        "PlotBackend",
        "registry",
        "IntrinsicCall",
    ] {
        assert!(
            !PLOTS
                .to_ascii_lowercase()
                .contains(&forbidden.to_ascii_lowercase())
        );
        assert!(
            !PLOTS_SVG
                .to_ascii_lowercase()
                .contains(&forbidden.to_ascii_lowercase())
        );
    }
    assert!(PLOTS.contains("beginPolyline"));
    assert!(PLOTS.contains("addPolylinePoint"));
    assert!(PLOTS.contains("endPolyline"));
    assert!(PLOTS_SVG.contains("graphics.svg.render"));
    assert!(PLOTS_SVG.contains("graphics.svg.save"));
}
