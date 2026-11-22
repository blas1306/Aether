//! PLOTS-MULTISERIES-V1 M0 flat-arena, ownership and compatibility qualification.

use std::{fs, path::PathBuf, process::Command};

use aether_driver::{
    ClangToolchain, Compilation, CompilationSession, Emit, OptimizationLevel,
    compile_session_with_optimization,
};

const GRAPHICS: &str = include_str!("../../../../graphics/src/lib.ae");
const GRAPHICS_SVG: &str = include_str!("../../../../graphics/src/svg.ae");
const LINEAR_ALGEBRA: &str = include_str!("../../../../linearAlgebra/src/lib.ae");
const PLOTS: &str = include_str!("../../../../plots/src/lib.ae");
const PLOTS_SVG: &str = include_str!("../../../../plots/src/svg.ae");
const SCIENTIFIC_CONSUMER: &str =
    include_str!("../../../../examples/scientific-curve-fitting/src/main.ae");
const MULTISERIES_GOLDEN: &str = include_str!("../../../../plots/tests/goldens/multiseries.svg");

const SCIENTIFIC_QUALIFICATION: &str = r"
package q;import linearAlgebra as la;
int main(){
 Matrix<float64> design=[1.0,0.0;1.0,1.0;1.0,2.0;1.0,3.0;1.0,4.0];
 Vector<float64,Column> observed=[0.0,4.0,5.0,8.0,8.0];
 usize row=1;while(row<=usize(5)){
  if(design[row,1]!=1.0||design[row,2]!=float64(row-1)){return 1;}
  row=row+1;
 }
 if(observed[1]!=0.0||observed[2]!=4.0||observed[3]!=5.0||
    observed[4]!=8.0||observed[5]!=8.0){return 2;}
 var coefficients=la.leastSquares(design,observed);
 var predicted=design*coefficients;
 var residuals=observed-predicted;
 float64 sse=la.dot(residuals,residuals);
 if(abs(coefficients[1]-1.0)>1.0e-10||
    abs(coefficients[2]-2.0)>1.0e-10){return 3;}
 if(abs(predicted[1]-1.0)>1.0e-10||abs(predicted[2]-3.0)>1.0e-10||
    abs(predicted[3]-5.0)>1.0e-10||abs(predicted[4]-7.0)>1.0e-10||
    abs(predicted[5]-9.0)>1.0e-10){return 4;}
 if(abs(residuals[1]-(-1.0))>1.0e-10||abs(residuals[2]-1.0)>1.0e-10||
    abs(residuals[3])>1.0e-10||abs(residuals[4]-1.0)>1.0e-10||
    abs(residuals[5]-(-1.0))>1.0e-10){return 5;}
 if(abs(sse-4.0)>1.0e-10){return 6;}
 return 0;
}
";

struct Project(PathBuf);

impl Project {
    fn new(label: &str, source: &str) -> Self {
        static NEXT: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
        let root = std::env::temp_dir().join(format!(
            "aether-plots-multiseries-{label}-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, std::sync::atomic::Ordering::Relaxed)
        ));
        fs::create_dir(&root).unwrap();
        fs::write(root.join("graphics.ae"), GRAPHICS).unwrap();
        fs::write(root.join("graphics_svg.ae"), GRAPHICS_SVG).unwrap();
        fs::write(root.join("linearAlgebra.ae"), LINEAR_ALGEBRA).unwrap();
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

fn compile_with_emits(
    source: &str,
    optimization: OptimizationLevel,
    emits: &[Emit],
) -> Compilation {
    let project = Project::new("compile", source);
    compile_session_with_optimization(
        CompilationSession::discover(&project.entry()).unwrap(),
        emits,
        optimization,
    )
    .unwrap_or_else(|diagnostics| panic!("{source}\n{diagnostics:#?}"))
}

fn compile(source: &str, optimization: OptimizationLevel) -> String {
    compile_with_emits(source, optimization, &[Emit::Llvm]).llvm
}

fn run(source: &str, optimization: OptimizationLevel) -> i32 {
    let llvm = compile(source, optimization);
    let project = Project::new("run", "package q;int main(){return 0;}");
    let executable = project.0.join("qualification");
    ClangToolchain::default()
        .with_optimization(optimization)
        .link_executable(&llvm, &executable)
        .unwrap();
    Command::new(executable)
        .status()
        .unwrap()
        .code()
        .unwrap_or(-1)
}

fn output(source: &str, optimization: OptimizationLevel) -> std::process::Output {
    let llvm = compile(source, optimization);
    let project = Project::new("output", "package q;int main(){return 0;}");
    let executable = project.0.join("qualification-output");
    ClangToolchain::default()
        .with_optimization(optimization)
        .link_executable(&llvm, &executable)
        .unwrap();
    Command::new(executable)
        .current_dir(&project.0)
        .output()
        .unwrap()
}

fn instrument_closure_counts(llvm: &str) -> String {
    let checks = r"  %m1_retains = load i64, ptr @aether_closure_retain_count
  %m1_releases = load i64, ptr @aether_closure_release_count
  %m1_destroys = load i64, ptr @aether_closure_destroy_count
  %m1_retain_ok = icmp eq i64 %m1_retains, 0
  %m1_release_ok = icmp eq i64 %m1_releases, 1
  %m1_destroy_ok = icmp eq i64 %m1_destroys, 1
  %m1_arc_ok = and i1 %m1_retain_ok, %m1_release_ok
  %m1_all_ok = and i1 %m1_arc_ok, %m1_destroy_ok
  %m1_status = select i1 %m1_all_ok, i32 %process_status, i32 99
  ret i32 %m1_status";
    let instrumented = llvm.replace("  ret i32 %process_status", checks);
    assert_ne!(instrumented, llvm);
    instrumented
}

fn run_llvm(llvm: &str, optimization: OptimizationLevel) -> i32 {
    let project = Project::new("instrumented", "package q;int main(){return 0;}");
    let executable = project.0.join("qualification-instrumented");
    ClangToolchain::default()
        .with_optimization(optimization)
        .link_executable(llvm, &executable)
        .unwrap();
    Command::new(executable)
        .current_dir(&project.0)
        .status()
        .unwrap()
        .code()
        .unwrap_or(-1)
}

fn render_to_file(source: &str, name: &str, optimization: OptimizationLevel) -> String {
    let llvm = compile(source, optimization);
    let project = Project::new("render", "package q;int main(){return 0;}");
    let executable = project.0.join("qualification-render");
    ClangToolchain::default()
        .with_optimization(optimization)
        .link_executable(&llvm, &executable)
        .unwrap();
    assert_eq!(
        Command::new(executable)
            .current_dir(&project.0)
            .status()
            .unwrap()
            .code(),
        Some(0)
    );
    fs::read_to_string(project.0.join(name)).unwrap()
}

fn run_with_balanced_heap(source: &str, optimization: OptimizationLevel) -> i32 {
    let llvm = compile(source, optimization);
    let guarded = llvm.replace(
        "  %process_status = trunc i64 %aether_result to i32",
        "  %arena_allocs = load i64, ptr @aether_heap_alloc_count\n  %arena_frees = load i64, ptr @aether_heap_free_count\n  %arena_heap_ok = icmp eq i64 %arena_allocs, %arena_frees\n  %arena_result_ok = icmp eq i64 %aether_result, 0\n  %arena_all_ok = and i1 %arena_heap_ok, %arena_result_ok\n  %process_status = select i1 %arena_all_ok, i32 0, i32 99",
    );
    assert_ne!(guarded, llvm);
    let project = Project::new("heap", "package q;int main(){return 0;}");
    let executable = project.0.join("heap-check");
    ClangToolchain::default()
        .with_optimization(optimization)
        .link_executable(&guarded, &executable)
        .unwrap();
    Command::new(executable)
        .current_dir(&project.0)
        .status()
        .unwrap()
        .code()
        .unwrap_or(-1)
}

const EMPTY_AND_VALIDATION: &str = r#"
package q;import plots as p;import plots.svg as svg;import graphics as g;
int main(){
 p.FigureOptions explicit=p.defaultOptions();
 explicit.xLimits=p.LimitMode.Explicit(p.Limits(-1.0,1.0));
 explicit.yLimits=p.LimitMode.Explicit(p.Limits(-2.0,2.0));
 explicit.title="Empty";explicit.xLabel="x";explicit.yLabel="y";
 explicit.line=p.LineStyle(g.Color(uint8(0),uint8(0),uint8(0),uint8(255)),0.0);
 p.Figure2D empty=p.figure(&explicit);g.Scene first=empty.scene();g.Scene second=empty.scene();
 if(first==second||first.commandCount()!=31||second.commandCount()!=31){return 1;}
 string a=svg.render(&empty);explicit.title="changed";explicit.xLabel="changed";explicit.yLabel="changed";explicit.xLimits=p.LimitMode.Auto;string b=svg.render(&empty);if(a!=b){return 2;}

 p.FigureOptions automatic=p.defaultOptions();p.Figure2D noData=p.figure(&automatic);
 try{g.Scene rejected=noData.scene();return 3;}catch(p.NoFiniteDataException error){}
 automatic.xLimits=p.LimitMode.Explicit(p.Limits(0.0,1.0));
 p.Figure2D halfExplicit=p.figure(&automatic);
 try{g.Scene rejected=halfExplicit.scene();return 4;}catch(p.NoFiniteDataException error){}

 p.FigureOptions invalid=p.defaultOptions();invalid.viewport=g.Viewport(96.0,480.0);
 try{p.Figure2D rejected=p.figure(&invalid);return 5;}catch(p.InvalidFigureException error){}
 invalid=p.defaultOptions();invalid.xLimits=p.LimitMode.Explicit(p.Limits(2.0,1.0));
 try{p.Figure2D rejected=p.figure(&invalid);return 6;}catch(p.InvalidLimitsException error){}
 return 0;
}
"#;

const ARENAS_AND_RENDERING: &str = r"
package q;import plots as p;import plots.svg as svg;import graphics as g;
bool lineAt(ref g.Scene scene,usize at,uint8 red,usize count,float64 firstX,float64 firstY,float64 lastX,float64 lastY){
 match((*scene).commandAt(at)){
  g.Command.DrawPolyline(span,stroke)=>{g.Point first=(*scene).pointAt(span,0);g.Point last=(*scene).pointAt(span,count-1);return span.length==count&&stroke.color.red==red&&first.x==firstX&&first.y==firstY&&last.x==lastX&&last.y==lastY;}
  g.Command.PushState=>{return false;}g.Command.PopState=>{return false;}g.Command.ConcatTransform(v)=>{return false;}g.Command.IntersectClipRect(v)=>{return false;}g.Command.DrawPoint(v,d,c)=>{return false;}g.Command.DrawLine(v,s)=>{return false;}g.Command.DrawRect(v,pa)=>{return false;}g.Command.DrawPath(v,pa)=>{return false;}g.Command.DrawText(v)=>{return false;}
 }
}
p.Figure2D fromTemporary(){p.FigureOptions o=p.defaultOptions();Array<p.DataPoint> local={p.DataPoint(0.0,0.0),p.DataPoint(1.0,1.0)};p.Figure2D f=p.figure(&o);f.addLine(&local,p.LineStyle(g.Color(uint8(9),uint8(0),uint8(0),uint8(255)),2.0));return f;}
int main(){
 p.FigureOptions o=p.defaultOptions();p.Figure2D f=p.figure(&o);p.Figure2D same=f;
 Array<p.DataPoint> low={p.DataPoint(0.0,0.0),p.DataPoint(1.0,1.0)};
 Array<p.DataPoint> high={p.DataPoint(10.0,-10.0),p.DataPoint(20.0,100.0)};
 f.addLine(&low,p.LineStyle(g.Color(uint8(10),uint8(0),uint8(0),uint8(255)),1.0));
 low[0]=p.DataPoint(99.0,99.0);
 same.addLine(&high,p.LineStyle(g.Color(uint8(20),uint8(0),uint8(0),uint8(255)),3.0));
 high[0]=p.DataPoint(-99.0,-99.0);
 g.Scene joined=f.scene();if(joined.commandCount()!=27){return 1;}
 if(!lineAt(&joined,3,uint8(10),2,72.0,382.54545454545456,99.2,379.2)){return 2;}
 if(!lineAt(&joined,4,uint8(20),2,344.0,416.0,616.0,48.0)){return 3;}
 string once=svg.render(&f);string twice=svg.render(&same);if(once!=twice){return 4;}

 Array<p.DataPoint> empty={};try{f.addLine(&empty,p.LineStyle(g.Color(uint8(1),uint8(2),uint8(3),uint8(255)),2.0));return 5;}catch(p.EmptySeriesException error){}
 Array<p.DataPoint> valid={p.DataPoint(2.0,2.0)};try{f.addLine(&valid,p.LineStyle(g.Color(uint8(1),uint8(2),uint8(3),uint8(255)),0.0));return 6;}catch(p.InvalidFigureException error){}
 float64 zero=0.0;float64 nan=zero/zero;Array<p.DataPoint> invalid={p.DataPoint(nan,0.0)};try{f.addLine(&invalid,p.LineStyle(g.Color(uint8(1),uint8(2),uint8(3),uint8(255)),2.0));return 7;}catch(p.NoFiniteDataException error){}
 g.Scene afterErrors=f.scene();if(afterErrors.commandCount()!=27){return 8;}
 if(svg.render(&f)!=once){return 10;}

 p.Figure2D temporary=fromTemporary();g.Scene retained=temporary.scene();if(retained.commandCount()!=26||!lineAt(&retained,3,uint8(9),2,72.0,416.0,616.0,48.0)){return 9;}
 return 0;
}
";

const REPEATED_GROWTH: &str = r"
package q;import plots as p;import graphics as g;
bool expectedLine(ref g.Scene scene,usize command,uint8 red){match((*scene).commandAt(command)){g.Command.DrawPolyline(span,stroke)=>{return span.length==3&&stroke.color.red==red;}g.Command.PushState=>{return false;}g.Command.PopState=>{return false;}g.Command.ConcatTransform(v)=>{return false;}g.Command.IntersectClipRect(v)=>{return false;}g.Command.DrawPoint(v,d,c)=>{return false;}g.Command.DrawLine(v,s)=>{return false;}g.Command.DrawRect(v,pa)=>{return false;}g.Command.DrawPath(v,pa)=>{return false;}g.Command.DrawText(v)=>{return false;}}}
int main(){p.FigureOptions o=p.defaultOptions();p.Figure2D f=p.figure(&o);usize i=0;while(i<usize(20)){float64 x=float64(i)*3.0;Array<p.DataPoint> values={p.DataPoint(x,x),p.DataPoint(x+1.0,x+1.0),p.DataPoint(x+2.0,x+2.0)};f.addLine(&values,p.LineStyle(g.Color(uint8(i),uint8(0),uint8(0),uint8(255)),2.0));values[0]=p.DataPoint(-1.0,-1.0);i=i+1;}g.Scene scene=f.scene();if(scene.commandCount()!=45){return 1;}i=0;while(i<usize(20)){if(!expectedLine(&scene,usize(3)+i,uint8(i))){return 2;}i=i+1;}g.Scene again=f.scene();if(again.commandCount()!=45){return 3;}return 0;}
";

const SCATTER_COMPOSITION: &str = r"
package q;import plots as p;import plots.svg as svg;import graphics as g;
bool pointAt(ref g.Scene scene,usize at,uint8 red,uint8 alpha,float64 diameter,float64 x,float64 y){
 match((*scene).commandAt(at)){
  g.Command.DrawPoint(point,size,color)=>{return color.red==red&&color.alpha==alpha&&size==diameter&&abs(point.x-x)<1.0e-12&&abs(point.y-y)<1.0e-12;}
  g.Command.PushState=>{return false;}g.Command.PopState=>{return false;}g.Command.ConcatTransform(v)=>{return false;}g.Command.IntersectClipRect(v)=>{return false;}g.Command.DrawLine(v,s)=>{return false;}g.Command.DrawRect(v,pa)=>{return false;}g.Command.DrawPolyline(v,s)=>{return false;}g.Command.DrawPath(v,pa)=>{return false;}g.Command.DrawText(v)=>{return false;}
 }
}
bool lineAt(ref g.Scene scene,usize at,uint8 red){
 match((*scene).commandAt(at)){
  g.Command.DrawPolyline(span,stroke)=>{return span.length==2&&stroke.color.red==red;}
  g.Command.PushState=>{return false;}g.Command.PopState=>{return false;}g.Command.ConcatTransform(v)=>{return false;}g.Command.IntersectClipRect(v)=>{return false;}g.Command.DrawPoint(v,d,c)=>{return false;}g.Command.DrawLine(v,s)=>{return false;}g.Command.DrawRect(v,pa)=>{return false;}g.Command.DrawPath(v,pa)=>{return false;}g.Command.DrawText(v)=>{return false;}
 }
}
bool clipAt(ref g.Scene scene,usize at){
 match((*scene).commandAt(at)){
  g.Command.IntersectClipRect(rectangle)=>{return rectangle.x==72.0&&rectangle.y==48.0&&rectangle.width==544.0&&rectangle.height==368.0;}
  g.Command.PushState=>{return false;}g.Command.PopState=>{return false;}g.Command.ConcatTransform(v)=>{return false;}g.Command.DrawPoint(v,d,c)=>{return false;}g.Command.DrawLine(v,s)=>{return false;}g.Command.DrawRect(v,pa)=>{return false;}g.Command.DrawPolyline(v,s)=>{return false;}g.Command.DrawPath(v,pa)=>{return false;}g.Command.DrawText(v)=>{return false;}
 }
}
int main(){
 p.FigureOptions o=p.defaultOptions();p.Figure2D f=p.figure(&o);p.Figure2D same=f;
 Array<p.DataPoint> line={p.DataPoint(0.0,0.0),p.DataPoint(4.0,8.0)};
 float64 z=0.0;float64 nan=z/z;
 Array<p.DataPoint> dots={p.DataPoint(0.0,1.0),p.DataPoint(nan,2.0),p.DataPoint(2.0,9.0),p.DataPoint(4.0,5.0)};
 f.addLine(&line,p.LineStyle(g.Color(uint8(10),uint8(11),uint8(12),uint8(255)),2.0));
 same.addScatter(&dots,p.ScatterStyle(g.Color(uint8(20),uint8(21),uint8(22),uint8(123)),7.0));
 line[0]=p.DataPoint(99.0,99.0);dots[0]=p.DataPoint(99.0,99.0);
 g.Scene joined=f.scene();if(joined.commandCount()!=29||!lineAt(&joined,3,uint8(10))){return 1;}
 if(!pointAt(&joined,4,uint8(20),uint8(123),7.0,72.0,375.1111111111111)){return 2;}
 if(!pointAt(&joined,5,uint8(20),uint8(123),7.0,344.0,48.0)){return 3;}
 if(!pointAt(&joined,6,uint8(20),uint8(123),7.0,616.0,211.55555555555554)){return 4;}
 string once=svg.render(&f);string twice=svg.render(&same);if(once!=twice){return 5;}

 p.Figure2D reverse=p.figure(&o);Array<p.DataPoint> twoDots={p.DataPoint(0.0,0.0),p.DataPoint(4.0,9.0)};
 Array<p.DataPoint> reverseLine={p.DataPoint(0.0,0.0),p.DataPoint(4.0,8.0)};
 reverse.addScatter(&twoDots,p.ScatterStyle(g.Color(uint8(30),uint8(0),uint8(0),uint8(255)),5.0));
 reverse.addLine(&reverseLine,p.LineStyle(g.Color(uint8(40),uint8(0),uint8(0),uint8(255)),3.0));
 g.Scene reversed=reverse.scene();if(!pointAt(&reversed,3,uint8(30),uint8(255),5.0,72.0,416.0)||!pointAt(&reversed,4,uint8(30),uint8(255),5.0,616.0,48.0)||!lineAt(&reversed,5,uint8(40))){return 6;}

 p.FigureOptions mixed=p.defaultOptions();mixed.xLimits=p.LimitMode.Explicit(p.Limits(0.0,4.0));p.Figure2D constant=p.figure(&mixed);
 Array<p.DataPoint> singleton={p.DataPoint(2.0,7.0)};constant.addScatter(&singleton,p.defaultScatterStyle());
 g.Scene centered=constant.scene();if(!pointAt(&centered,3,uint8(31),uint8(255),6.0,344.0,232.0)){return 7;}

 p.FigureOptions clippedOptions=p.defaultOptions();clippedOptions.xLimits=p.LimitMode.Explicit(p.Limits(0.0,1.0));clippedOptions.yLimits=p.LimitMode.Explicit(p.Limits(0.0,1.0));p.Figure2D clipped=p.figure(&clippedOptions);
 Array<p.DataPoint> outside={p.DataPoint(-1.0,0.5),p.DataPoint(0.5,0.5),p.DataPoint(2.0,0.5)};clipped.addScatter(&outside,p.ScatterStyle(g.Color(uint8(50),uint8(0),uint8(0),uint8(255)),4.0));g.Scene clippedScene=clipped.scene();if(clippedScene.commandCount()!=28||!clipAt(&clippedScene,2)||!pointAt(&clippedScene,3,uint8(50),uint8(255),4.0,-472.0,232.0)||!pointAt(&clippedScene,4,uint8(50),uint8(255),4.0,344.0,232.0)||!pointAt(&clippedScene,5,uint8(50),uint8(255),4.0,1160.0,232.0)){return 13;}

 Array<p.DataPoint> empty={};try{f.addScatter(&empty,p.defaultScatterStyle());return 8;}catch(p.EmptySeriesException error){}
 Array<p.DataPoint> one={p.DataPoint(1.0,1.0)};try{f.addScatter(&one,p.ScatterStyle(g.Color(uint8(1),uint8(2),uint8(3),uint8(4)),0.0));return 9;}catch(p.InvalidFigureException error){}
 try{f.addScatter(&one,p.ScatterStyle(g.Color(uint8(1),uint8(2),uint8(3),uint8(4)),nan));return 10;}catch(p.InvalidFigureException error){}
 Array<p.DataPoint> invalid={p.DataPoint(nan,1.0),p.DataPoint(1.0,nan)};try{f.addScatter(&invalid,p.defaultScatterStyle());return 11;}catch(p.NoFiniteDataException error){}
 if(svg.render(&f)!=once){return 12;}

 p.Figure2D scatterPair=p.figure(&o);
 Array<p.DataPoint> firstDots={p.DataPoint(0.0,0.0),p.DataPoint(1.0,1.0)};
 Array<p.DataPoint> secondDots={p.DataPoint(2.0,2.0),p.DataPoint(3.0,3.0)};
 scatterPair.addScatter(&firstDots,p.ScatterStyle(g.Color(uint8(60),uint8(1),uint8(2),uint8(200)),3.0));
 scatterPair.addScatter(&secondDots,p.ScatterStyle(g.Color(uint8(70),uint8(3),uint8(4),uint8(201)),9.0));
 g.Scene paired=scatterPair.scene();
 if(paired.commandCount()!=29||
    !pointAt(&paired,3,uint8(60),uint8(200),3.0,72.0,416.0)||
    !pointAt(&paired,6,uint8(70),uint8(201),9.0,616.0,48.0)){return 14;}
 return 0;
}
";

const MIXED_GROWTH: &str = r"
package q;import plots as p;import graphics as g;
int main(){p.FigureOptions o=p.defaultOptions();p.Figure2D f=p.figure(&o);usize i=0;while(i<usize(24)){float64 x=float64(i);Array<p.DataPoint> values={p.DataPoint(x,x),p.DataPoint(x+1.0,x+1.0),p.DataPoint(x+2.0,x+2.0)};if(i%usize(2)==usize(0)){f.addLine(&values,p.LineStyle(g.Color(uint8(i),uint8(0),uint8(0),uint8(255)),2.0));}else{f.addScatter(&values,p.ScatterStyle(g.Color(uint8(i),uint8(0),uint8(0),uint8(255)),4.0));}values[0]=p.DataPoint(-100.0,-100.0);i=i+1;}g.Scene scene=f.scene();if(scene.commandCount()!=73){return 1;}i=0;usize command=3;while(i<usize(24)){if(i%usize(2)==usize(0)){match(scene.commandAt(command)){g.Command.DrawPolyline(span,stroke)=>{if(span.length!=3||stroke.color.red!=uint8(i)){return 2;}}g.Command.PushState=>{return 3;}g.Command.PopState=>{return 3;}g.Command.ConcatTransform(v)=>{return 3;}g.Command.IntersectClipRect(v)=>{return 3;}g.Command.DrawPoint(v,d,c)=>{return 3;}g.Command.DrawLine(v,s)=>{return 3;}g.Command.DrawRect(v,pa)=>{return 3;}g.Command.DrawPath(v,pa)=>{return 3;}g.Command.DrawText(v)=>{return 3;}}command=command+1;}else{usize j=0;while(j<usize(3)){match(scene.commandAt(command)){g.Command.DrawPoint(v,d,c)=>{if(d!=4.0||c.red!=uint8(i)){return 4;}}g.Command.PushState=>{return 5;}g.Command.PopState=>{return 5;}g.Command.ConcatTransform(v)=>{return 5;}g.Command.IntersectClipRect(v)=>{return 5;}g.Command.DrawLine(v,s)=>{return 5;}g.Command.DrawRect(v,pa)=>{return 5;}g.Command.DrawPolyline(v,s)=>{return 5;}g.Command.DrawPath(v,pa)=>{return 5;}g.Command.DrawText(v)=>{return 5;}}command=command+1;j=j+1;}}i=i+1;}if(command!=usize(51)){return 6;}return 0;}
";

const ADD_FUNCTION: &str = r"
package q;import plots as p;import plots.svg as svg;import graphics as g;
open class Stop:Exception{public init(){}}
float64 observed(float64 x){println(x);return x*x;}
float64 fail(float64 x){println(x);if(x==0.0){throw Stop();}return x;}
int main(){
 p.FigureOptions o=p.defaultOptions();p.Figure2D f=p.figure(&o);p.Figure2D same=f;
 Function<(float64),float64> top=observed;
 p.addFunction(f,top,-2.0,2.0,usize(5),p.LineStyle(g.Color(uint8(11),uint8(0),uint8(0),uint8(255)),2.0));
 float64 scale=2.0;var closure=(float64 x) capture(copy scale)=>observed(x)*scale;
 p.addFunction(same,closure,0.0,2.0,usize(3),p.LineStyle(g.Color(uint8(22),uint8(0),uint8(0),uint8(255)),3.0));
 if(closure(3.0)!=18.0){return 1;}
 p.addFunction(f,(float64 x) capture(copy scale)=>x+scale,0.0,1.0,usize(2),p.LineStyle(g.Color(uint8(33),uint8(0),uint8(0),uint8(255)),4.0));
 p.addFunction(f,(float64 x)=>x,0.0,1.0,usize(2),p.LineStyle(g.Color(uint8(34),uint8(0),uint8(0),uint8(255)),5.0));
 g.Scene composed=f.scene();if(composed.commandCount()!=29){return 2;}
 string before=svg.render(&f);int caught=0;try{p.addFunction(same,fail,-1.0,1.0,usize(3),p.LineStyle(g.Color(uint8(44),uint8(0),uint8(0),uint8(255)),2.0));}catch(Stop error){caught=1;}
 if(caught!=1||svg.render(&f)!=before){return 3;}
 try{p.addFunction(f,top,0.0,1.0,usize(1),p.LineStyle(g.Color(uint8(1),uint8(0),uint8(0),uint8(255)),2.0));return 4;}catch(p.InvalidSampleCountException error){}
 try{p.addFunction(f,top,1.0,0.0,usize(2),p.LineStyle(g.Color(uint8(1),uint8(0),uint8(0),uint8(255)),2.0));return 5;}catch(p.InvalidSampleIntervalException error){}
 try{p.addFunction(f,top,0.0,1.0,usize(2),p.LineStyle(g.Color(uint8(1),uint8(0),uint8(0),uint8(255)),0.0));return 7;}catch(p.InvalidFigureException error){}
 if(svg.render(&f)!=before){return 6;}
 return 0;
}
";

const MULTISERIES_GOLDEN_SOURCE: &str = r#"
package q;import plots as p;import plots.svg as svg;import graphics as g;
float64 wave(float64 x){return sin(x);}
int main(){p.FigureOptions o=p.defaultOptions();o.title="Line and observations";o.xLabel="x";o.yLabel="y";p.Figure2D f=p.figure(&o);p.addFunction(f,wave,-3.141592653589793,3.141592653589793,usize(17),p.LineStyle(g.Color(uint8(40),uint8(90),uint8(180),uint8(255)),2.0));Array<p.DataPoint> observations={p.DataPoint(-3.141592653589793,0.0),p.DataPoint(-1.5707963267948966,-1.0),p.DataPoint(0.0,0.0),p.DataPoint(1.5707963267948966,1.0),p.DataPoint(3.141592653589793,0.0)};f.addScatter(&observations,p.ScatterStyle(g.Color(uint8(210),uint8(65),uint8(50),uint8(220)),8.0));string path="multiseries.svg";svg.save(&f,&path);return 0;}
"#;

#[test]
fn empty_figure_and_figure_validation_are_exact_o0_o2() {
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        assert_eq!(
            run(EMPTY_AND_VALIDATION, optimization),
            0,
            "{optimization:?}"
        );
    }
}

#[test]
fn add_line_joint_limits_aliases_order_and_validation_are_exact_o0_o2() {
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        assert_eq!(
            run(ARENAS_AND_RENDERING, optimization),
            0,
            "{optimization:?}"
        );
    }
}

#[test]
fn both_flat_arenas_survive_repeated_and_simultaneous_growth_o0_o2() {
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        assert_eq!(run(REPEATED_GROWTH, optimization), 0, "{optimization:?}");
        assert_eq!(
            run_with_balanced_heap(REPEATED_GROWTH, optimization),
            0,
            "{optimization:?}"
        );
    }
}

#[test]
fn hir_mir_and_ssa_expose_general_flat_buffer_replacement() {
    let source = r"
package q;import plots as p;import graphics as g;
int main(){p.FigureOptions o=p.defaultOptions();p.Figure2D f=p.figure(&o);Array<p.DataPoint> a={p.DataPoint(0.0,0.0),p.DataPoint(1.0,1.0)};f.addLine(&a,p.LineStyle(g.Color(uint8(1),uint8(2),uint8(3),uint8(255)),2.0));return 0;}
";
    let compilation = compile_with_emits(
        source,
        OptimizationLevel::O0,
        &[Emit::Hir, Emit::Mir, Emit::Ssa, Emit::Llvm],
    );
    for phase in [Emit::Hir, Emit::Mir, Emit::Ssa] {
        let dump = &compilation.dumps[&phase];
        assert!(dump.contains("SeriesRecord"), "{phase:?}");
        assert!(dump.contains("Buffer<"), "{phase:?}");
        assert!(dump.contains("ReplaceOwned"), "{phase:?}");
    }
    assert!(compilation.llvm.contains("addLine"));
    assert!(PLOTS.contains("Buffer<DataPoint> points;"));
    assert!(PLOTS.contains("Buffer<SeriesRecord> series;"));
    assert!(!PLOTS.contains("Buffer<Buffer<"));
}

#[test]
fn scatter_composes_with_lines_limits_styles_aliases_and_failures_o0_o2() {
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        assert_eq!(
            run(SCATTER_COMPOSITION, optimization),
            0,
            "{optimization:?}"
        );
    }
}

#[test]
fn line_and_scatter_share_both_growing_flat_arenas_o0_o2() {
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        assert_eq!(run(MIXED_GROWTH, optimization), 0, "{optimization:?}");
        assert_eq!(
            run_with_balanced_heap(MIXED_GROWTH, optimization),
            0,
            "{optimization:?}"
        );
    }
}

#[test]
fn add_function_is_borrowed_eager_atomic_and_identity_preserving_o0_o2() {
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        let actual = output(ADD_FUNCTION, optimization);
        assert_eq!(actual.status.code(), Some(0), "{optimization:?}");
        let stdout = String::from_utf8(actual.stdout).unwrap();
        assert_eq!(stdout.lines().count(), 13, "{optimization:?}: {stdout}");
        assert_eq!(
            stdout, "-2\n-1\n0\n1\n2\n0\n1\n2\n3\n-1\n0\n0\n1\n",
            "{optimization:?}"
        );
        assert_eq!(run_with_balanced_heap(ADD_FUNCTION, optimization), 0);
    }
}

#[test]
fn add_function_rejects_incompatible_callback_signatures() {
    let cases = [
        "int bad(int x){return x;}int main(){p.FigureOptions o=p.defaultOptions();p.Figure2D f=p.figure(&o);p.addFunction(f,bad,0.0,1.0,usize(2),o.line);return 0;}",
        "float64 bad(float64 x,float64 y){return x+y;}int main(){p.FigureOptions o=p.defaultOptions();p.Figure2D f=p.figure(&o);p.addFunction(f,bad,0.0,1.0,usize(2),o.line);return 0;}",
        "int main(){int n=1;var bad=(int x) capture(copy n)=>x+n;p.FigureOptions o=p.defaultOptions();p.Figure2D f=p.figure(&o);p.addFunction(f,bad,0.0,1.0,usize(2),o.line);return 0;}",
    ];
    for body in cases {
        let source = format!("package q;import plots as p;{body}");
        let project = Project::new("bad-signature", &source);
        let diagnostics = compile_session_with_optimization(
            CompilationSession::discover(&project.entry()).unwrap(),
            &[Emit::Hir],
            OptimizationLevel::O0,
        )
        .unwrap_err();
        let text = format!("{diagnostics:#?}");
        assert!(
            text.contains("E0205") || text.contains("Invocable"),
            "{text}"
        );
    }
}

#[test]
fn add_function_borrowed_closure_arc_and_temporaries_are_balanced_o0_o2() {
    let source = r"
package q;import plots as p;import graphics as g;
int main(){p.FigureOptions o=p.defaultOptions();p.Figure2D f=p.figure(&o);float64 scale=2.0;var closure=(float64 x) capture(copy scale)=>scale*x;p.addFunction(f,closure,0.0,2.0,usize(33),p.LineStyle(g.Color(uint8(1),uint8(2),uint8(3),uint8(255)),2.0));if(closure(3.0)!=6.0){return 1;}return 0;}
";
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        let llvm = compile(source, optimization);
        assert_eq!(
            run_llvm(&instrument_closure_counts(&llvm), optimization),
            0,
            "{optimization:?}"
        );
        assert_eq!(run_with_balanced_heap(source, optimization), 0);
    }
}

#[test]
fn m1_surface_and_lowering_do_not_store_borrowed_callbacks() {
    let source = r"
package q;import plots as p;import graphics as g;int main(){p.FigureOptions o=p.defaultOptions();p.Figure2D f=p.figure(&o);float64 scale=2.0;var closure=(float64 x) capture(copy scale)=>scale*x;p.addFunction(f,closure,0.0,2.0,usize(3),p.LineStyle(g.Color(uint8(1),uint8(2),uint8(3),uint8(255)),2.0));return 0;}
";
    let compilation = compile_with_emits(
        source,
        OptimizationLevel::O0,
        &[Emit::Hir, Emit::Mir, Emit::Ssa, Emit::Llvm],
    );
    assert!(PLOTS.contains("public struct ScatterStyle"));
    assert!(PLOTS.contains("public mut void addScatter"));
    assert!(PLOTS.contains("public void addFunction<C: Invocable<(float64), float64>>"));
    assert!(!PLOTS.contains("Buffer<Closure"));
    assert!(!PLOTS.contains("Buffer<Function"));
    assert!(compilation.dumps[&Emit::Mir].contains("EndClosureBorrow"));
    assert!(compilation.dumps[&Emit::Mir].contains("addLine"));
    assert!(!compilation.llvm.contains("invocable_adapter"));
}

#[test]
fn representative_multiseries_golden_is_xml_and_deterministic_o0_o2() {
    let o0 = render_to_file(
        MULTISERIES_GOLDEN_SOURCE,
        "multiseries.svg",
        OptimizationLevel::O0,
    );
    let o2 = render_to_file(
        MULTISERIES_GOLDEN_SOURCE,
        "multiseries.svg",
        OptimizationLevel::O2,
    );
    assert_eq!(o0, o2);
    assert_eq!(o0, MULTISERIES_GOLDEN);
    let document = roxmltree::Document::parse(&o0).unwrap();
    assert_eq!(
        document.root_element().tag_name().namespace(),
        Some("http://www.w3.org/2000/svg")
    );
    assert_eq!(
        document
            .descendants()
            .filter(|node| node.has_tag_name("polyline"))
            .count(),
        1
    );
    assert_eq!(
        document
            .descendants()
            .filter(|node| node.has_tag_name("circle"))
            .count(),
        5
    );
    assert!(o0.find("<polyline").unwrap() < o0.find("<circle").unwrap());
}

#[test]
fn scientific_curve_fitting_consumer_is_exact_and_deterministic_o0_o2() {
    let compact_source = SCIENTIFIC_CONSUMER.split_whitespace().collect::<String>();
    assert!(
        compact_source.contains("Matrix<float64>design=[1.0,0.0;1.0,1.0;1.0,2.0;1.0,3.0;1.0,4.0];")
    );
    assert!(compact_source.contains("Vector<float64,Column>observed=[0.0,4.0,5.0,8.0,8.0];"));
    assert!(compact_source.contains("la.leastSquares(design,observed)"));
    assert!(compact_source.contains("predicted=design*coefficients"));
    assert!(compact_source.contains("residuals=observed-predicted"));
    assert!(compact_source.contains("la.dot(residuals,residuals)"));
    assert!(compact_source.contains("capture(copyintercept,copyslope)=>intercept+slope*x"));
    assert!(compact_source.contains("options.xLimits=p.LimitMode.Explicit(p.Limits(0.0,4.0))"));
    assert!(compact_source.contains("options.yLimits=p.LimitMode.Explicit(p.Limits(0.0,9.0))"));

    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        assert_eq!(run(SCIENTIFIC_QUALIFICATION, optimization), 0);
    }

    let o0 = render_to_file(SCIENTIFIC_CONSUMER, "curve_fit.svg", OptimizationLevel::O0);
    let o2 = render_to_file(SCIENTIFIC_CONSUMER, "curve_fit.svg", OptimizationLevel::O2);
    assert_eq!(o0, o2);
    let document = roxmltree::Document::parse(&o0).unwrap();
    let polylines = document
        .descendants()
        .filter(|node| node.has_tag_name("polyline"))
        .collect::<Vec<_>>();
    let circles = document
        .descendants()
        .filter(|node| node.has_tag_name("circle"))
        .collect::<Vec<_>>();
    assert_eq!(polylines.len(), 1);
    assert_eq!(circles.len(), 5);
    assert_eq!(
        circles
            .iter()
            .map(|node| node.attribute("transform").unwrap())
            .collect::<Vec<_>>(),
        vec![
            "matrix(0.5 0 0 0.5 72 416)",
            "matrix(0.5 0 0 0.5 208 252.44444444444446)",
            "matrix(0.5 0 0 0.5 344 211.55555555555557)",
            "matrix(0.5 0 0 0.5 480 88.88888888888891)",
            "matrix(0.5 0 0 0.5 616 88.88888888888891)",
        ]
    );
    assert_eq!(
        polylines[0]
            .attribute("points")
            .unwrap()
            .split_ascii_whitespace()
            .count(),
        33
    );
    let line_points = polylines[0].attribute("points").unwrap();
    assert!(line_points.starts_with("72,375.1111111111111 "));
    assert!(line_points.ends_with("616,48.000000000000114"));
    assert!(o0.find("<polyline").unwrap() < o0.find("<circle").unwrap());

    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        let llvm = compile(SCIENTIFIC_CONSUMER, optimization);
        assert_eq!(
            run_llvm(&instrument_closure_counts(&llvm), optimization),
            0,
            "{optimization:?}"
        );
        assert_eq!(
            run_with_balanced_heap(SCIENTIFIC_CONSUMER, optimization),
            0,
            "{optimization:?}"
        );
    }
}
