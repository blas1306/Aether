//! GRAPHICS-FOUNDATION-V1 structural, runtime, allocation and boundary qualification.

use std::{fs, path::PathBuf, process::Command};

use aether_driver::{
    ClangToolchain, CompilationSession, Emit, OptimizationLevel, compile_session,
    compile_session_with_optimization,
};

const LIBRARY: &str = include_str!("../../../../graphics/src/lib.ae");
const CONSUMER: &str = include_str!("../../../../graphics/tests/consumer/src/main.ae");

struct Directory(PathBuf);

impl Directory {
    fn new(label: &str) -> Self {
        static NEXT: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
        let path = std::env::temp_dir().join(format!(
            "aether-graphics-foundation-{label}-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, std::sync::atomic::Ordering::Relaxed)
        ));
        fs::create_dir(&path).unwrap();
        fs::write(path.join("graphics.ae"), LIBRARY).unwrap();
        Self(path)
    }

    fn entry(&self, source: &str) -> PathBuf {
        let path = self.0.join("main.ae");
        fs::write(&path, source).unwrap();
        path
    }
}

impl Drop for Directory {
    fn drop(&mut self) {
        fs::remove_dir_all(&self.0).unwrap();
    }
}

fn compile(source: &str, optimization: OptimizationLevel) -> aether_driver::Compilation {
    let directory = Directory::new("compile");
    let entry = directory.entry(source);
    compile_session_with_optimization(
        CompilationSession::discover(&entry).unwrap(),
        &[Emit::Hir, Emit::Mir, Emit::Ssa, Emit::Llvm],
        optimization,
    )
    .unwrap_or_else(|diagnostics| panic!("{source}\n{diagnostics:#?}"))
}

fn run(source: &str, optimization: OptimizationLevel) {
    let directory = Directory::new("run");
    let entry = directory.entry(source);
    let compilation = compile_session_with_optimization(
        CompilationSession::discover(&entry).unwrap(),
        &[Emit::Llvm],
        optimization,
    )
    .unwrap_or_else(|diagnostics| panic!("{source}\n{diagnostics:#?}"));
    let executable = directory.0.join("qualification");
    ClangToolchain::default()
        .with_optimization(optimization)
        .link_executable(&compilation.llvm, &executable)
        .unwrap();
    assert_eq!(
        Command::new(executable).status().unwrap().code(),
        Some(0),
        "{optimization:?}"
    );
}

fn diagnostics(source: &str) -> String {
    let directory = Directory::new("diagnostics");
    let entry = directory.entry(source);
    compile_session(CompilationSession::discover(&entry).unwrap(), &[])
        .unwrap_err()
        .into_iter()
        .map(|diagnostic| format!("{} {}", diagnostic.code, diagnostic.message))
        .collect::<Vec<_>>()
        .join("\n")
}

fn instrument(llvm: &str, counts: [u64; 7]) -> String {
    use std::fmt::Write;

    let names = [
        "object_alloc",
        "object_retain",
        "object_release",
        "object_destroy",
        "object_buffer_drop",
        "heap_alloc",
        "heap_free",
    ];
    let mut guard = "  %graphics_result_ok = icmp eq i64 %aether_result, 0\n".to_owned();
    let mut last = "graphics_result_ok".to_owned();
    for (index, (name, expected)) in names.iter().zip(counts).enumerate() {
        writeln!(
            guard,
            "  %graphics_count_{index} = load i64, ptr @aether_{name}_count\n  %graphics_ok_{index} = icmp eq i64 %graphics_count_{index}, {expected}\n  %graphics_all_{index} = and i1 %{last}, %graphics_ok_{index}"
        )
        .unwrap();
        last = format!("graphics_all_{index}");
    }
    writeln!(
        guard,
        "  %process_status = select i1 %{last}, i32 0, i32 99"
    )
    .unwrap();
    let result = llvm.replace(
        "  %process_status = trunc i64 %aether_result to i32",
        &guard,
    );
    assert_ne!(result, llvm);
    result
}

fn execute_llvm(llvm: &str, optimization: OptimizationLevel) -> i32 {
    let directory = Directory::new("llvm");
    let ir = directory.0.join("program.ll");
    let executable = directory.0.join("program");
    fs::write(&ir, llvm).unwrap();
    ClangToolchain::default()
        .with_optimization(optimization)
        .link_executable(llvm, &executable)
        .unwrap();
    Command::new(executable).status().unwrap().code().unwrap()
}

fn observe_counter(llvm: &str, name: &str) -> u64 {
    let replacement = format!(
        "  %graphics_observed = load i64, ptr @aether_{name}_count\n  %process_status = trunc i64 %graphics_observed to i32"
    );
    let observed = llvm.replace(
        "  %process_status = trunc i64 %aether_result to i32",
        &replacement,
    );
    assert_ne!(observed, llvm);
    u64::try_from(execute_llvm(&observed, OptimizationLevel::O0)).unwrap()
}

#[test]
fn public_consumer_runs_at_o0_and_o2() {
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        run(CONSUMER, optimization);
    }
}

#[test]
fn source_compiles_for_ir_inspection() {
    let compilation = compile(
        "package consumer;import graphics as g;int main(){g.SceneBuilder b=g.SceneBuilder(g.Viewport(1.0,1.0));string t=\"x\";string n=\"n\";g.TextStyle y=g.TextStyle(1.0,g.Color(uint8(0),uint8(0),uint8(0),uint8(255)),g.FontRequest(g.FontFamily.Named(n),g.FontWeight.Normal,g.FontSlant.Normal),g.TextAlign.Left,g.TextBaseline.Alphabetic);b.drawText(&t,g.Point(0.0,0.0),&y);g.Scene s=b.finish();return int(s.commandCount()-1);}",
        OptimizationLevel::O0,
    );
    assert!(compilation.dumps[&Emit::Hir].contains("Buffer<"));
}

#[test]
fn scene_constructor_is_not_available_to_consumers() {
    let output = diagnostics(
        "package consumer;import graphics as g;int main(){var token=g.SceneConstruction(0);return 0;}",
    );
    assert!(
        output.contains("E0222") && output.contains("SceneConstruction"),
        "{output}"
    );
}

#[test]
fn geometry_style_state_and_incremental_failures_are_transactional() {
    let source = r#"
package consumer;import graphics as g;
g.Color c(){return g.Color(uint8(0),uint8(0),uint8(0),uint8(255));}
g.Stroke s(float64 width,float64 miter){return g.Stroke(c(),width,g.LineCap.Butt,g.LineJoin.Miter,miter);}
int badViewport(float64 width,float64 height){int caught=0;try{g.SceneBuilder b=g.SceneBuilder(g.Viewport(width,height));}catch(g.InvalidGeometryException e){caught=1;}return caught-1;}
int badPoint(float64 value){g.SceneBuilder b=g.SceneBuilder(g.Viewport(1.0,1.0));int caught=0;try{b.drawPoint(g.Point(value,0.0),1.0,c());}catch(g.InvalidGeometryException e){caught=1;}g.Scene x=b.finish();if(caught==1&&x.commandCount()==0){return 0;}return 1;}
int badDiameter(float64 value){g.SceneBuilder b=g.SceneBuilder(g.Viewport(1.0,1.0));int caught=0;try{b.drawPoint(g.Point(0.0,0.0),value,c());}catch(g.InvalidGeometryException e){caught=1;}g.Scene x=b.finish();if(caught==1&&x.commandCount()==0){return 0;}return 1;}
int badRect(g.Rect value){g.SceneBuilder b=g.SceneBuilder(g.Viewport(1.0,1.0));int caught=0;try{b.drawRect(value,g.Paint.FillOnly(g.Fill(c(),g.FillRule.NonZero)));}catch(g.InvalidGeometryException e){caught=1;}g.Scene x=b.finish();if(caught==1&&x.commandCount()==0){return 0;}return 1;}
int badStroke(float64 width,float64 miter){g.SceneBuilder b=g.SceneBuilder(g.Viewport(1.0,1.0));int caught=0;try{b.drawLine(g.Line(g.Point(0.0,0.0),g.Point(0.0,0.0)),s(width,miter));}catch(g.InvalidGeometryException e){caught=1;}g.Scene x=b.finish();if(caught==1&&x.commandCount()==0){return 0;}return 1;}
int badText(float64 size){g.SceneBuilder b=g.SceneBuilder(g.Viewport(1.0,1.0));string t="x";g.TextStyle y=g.TextStyle(size,c(),g.FontRequest(g.FontFamily.BackendDefault,g.FontWeight.Normal,g.FontSlant.Normal),g.TextAlign.Left,g.TextBaseline.Alphabetic);int caught=0;try{b.drawText(&t,g.Point(0.0,0.0),&y);}catch(g.InvalidGeometryException e){caught=1;}g.Scene x=b.finish();if(caught==1&&x.commandCount()==0){return 0;}return 1;}
int badTransform(float64 value){g.SceneBuilder b=g.SceneBuilder(g.Viewport(1.0,1.0));int caught=0;try{b.concatTransform(g.Transform2D(value,0.0,0.0,1.0,0.0,0.0));}catch(g.InvalidGeometryException e){caught=1;}g.Scene x=b.finish();if(caught==1&&x.commandCount()==0){return 0;}return 1;}
int badPolyline(){g.SceneBuilder b=g.SceneBuilder(g.Viewport(1.0,1.0));Array<g.Point> empty={};Array<g.Point> one={g.Point(0.0,0.0)};int caught=0;try{b.drawPolyline(&empty,s(1.0,1.0));}catch(g.InvalidGeometryException e){caught=caught+1;}try{b.drawPolyline(&one,s(1.0,1.0));}catch(g.InvalidGeometryException e){caught=caught+1;}g.Scene x=b.finish();if(caught==2&&x.commandCount()==0){return 0;}return 1;}
int stateErrors(){g.SceneBuilder b=g.SceneBuilder(g.Viewport(1.0,1.0));int caught=0;try{b.popState();}catch(g.InvalidSceneStateException e){caught=caught+1;}b.pushState();try{g.Scene x=b.finish();}catch(g.InvalidSceneStateException e){caught=caught+1;}b.popState();g.Scene x=b.finish();if(caught==2&&x.commandCount()==2){return 0;}return 1;}
int openPolyline(){g.SceneBuilder b=g.SceneBuilder(g.Viewport(1.0,1.0));b.beginPolyline();b.addPolylinePoint(g.Point(0.0,0.0));int caught=0;try{b.endPolyline(s(1.0,1.0));}catch(g.InvalidGeometryException e){caught=caught+1;}try{g.Scene x=b.finish();}catch(g.InvalidSceneStateException e){caught=caught+1;}b.addPolylinePoint(g.Point(1.0,1.0));b.endPolyline(s(1.0,1.0));g.Scene x=b.finish();if(caught==2&&x.commandCount()==1){return 0;}return 1;}
int pathErrors(){g.SceneBuilder b=g.SceneBuilder(g.Viewport(1.0,1.0));int caught=0;try{b.lineTo(g.Point(0.0,0.0));}catch(g.InvalidSceneStateException e){caught=caught+1;}b.beginPath();try{b.closePath();}catch(g.InvalidSceneStateException e){caught=caught+1;}try{g.Scene x=b.finish();}catch(g.InvalidSceneStateException e){caught=caught+1;}b.moveTo(g.Point(0.0,0.0));b.closePath();b.endPath(g.Paint.FillOnly(g.Fill(c(),g.FillRule.NonZero)));g.Scene x=b.finish();if(caught==3&&x.commandCount()==1){return 0;}return 1;}
int everyPathStateError(){int caught=0;g.Paint p=g.Paint.FillOnly(g.Fill(c(),g.FillRule.NonZero));
 g.SceneBuilder outside=g.SceneBuilder(g.Viewport(1.0,1.0));try{outside.cubicTo(g.Point(0.0,0.0),g.Point(0.0,0.0),g.Point(0.0,0.0));}catch(g.InvalidSceneStateException e){caught=caught+1;}try{outside.closePath();}catch(g.InvalidSceneStateException e){caught=caught+1;}try{outside.endPath(p);}catch(g.InvalidSceneStateException e){caught=caught+1;}g.Scene a=outside.finish();
 g.SceneBuilder beforeMove=g.SceneBuilder(g.Viewport(1.0,1.0));beforeMove.beginPath();try{beforeMove.lineTo(g.Point(0.0,0.0));}catch(g.InvalidSceneStateException e){caught=caught+1;}try{beforeMove.cubicTo(g.Point(0.0,0.0),g.Point(0.0,0.0),g.Point(0.0,0.0));}catch(g.InvalidSceneStateException e){caught=caught+1;}try{beforeMove.closePath();}catch(g.InvalidSceneStateException e){caught=caught+1;}try{beforeMove.endPath(p);}catch(g.InvalidSceneStateException e){caught=caught+1;}beforeMove.moveTo(g.Point(0.0,0.0));beforeMove.endPath(p);g.Scene b=beforeMove.finish();
 g.SceneBuilder nested=g.SceneBuilder(g.Viewport(1.0,1.0));nested.beginPath();try{nested.beginPath();}catch(g.InvalidSceneStateException e){caught=caught+1;}nested.moveTo(g.Point(0.0,0.0));nested.endPath(p);g.Scene d=nested.finish();if(caught==8&&a.commandCount()==0&&b.commandCount()==1&&d.commandCount()==1){return 0;}return 1;}
int secondFinish(){g.SceneBuilder b=g.SceneBuilder(g.Viewport(1.0,1.0));g.Scene first=b.finish();int caught=0;try{g.Scene second=b.finish();}catch(g.InvalidSceneStateException e){caught=1;}if(caught==1&&first.commandCount()==0){return 0;}return 1;}
int sealedAlias(){g.SceneBuilder b=g.SceneBuilder(g.Viewport(1.0,1.0));g.SceneBuilder a=b;g.Scene first=b.finish();int caught=0;try{a.drawPoint(g.Point(0.0,0.0),1.0,c());}catch(g.InvalidSceneStateException e){caught=caught+1;}try{g.Scene second=a.finish();}catch(g.InvalidSceneStateException e){caught=caught+1;}if(caught==2&&first.commandCount()==0){return 0;}return 1;}
int transformOrder(float64 maximum){g.SceneBuilder b=g.SceneBuilder(g.Viewport(1.0,1.0));b.concatTransform(g.Transform2D(2.0,0.0,0.0,1.0,0.0,0.0));int caught=0;try{b.concatTransform(g.Transform2D(1.0,0.0,0.0,1.0,maximum,0.0));}catch(g.InvalidGeometryException e){caught=1;}g.Scene x=b.finish();if(caught==1&&x.commandCount()==1){return 0;}return 1;}
int main(){float64 z=0.0;float64 nan=z/z;float64 inf=1.0/z;float64 ninf=-1.0/z;float64 maximum=1.7976931348623157e308;
 int result=0;result=result+badViewport(-1.0,1.0)+badViewport(inf,1.0)+badViewport(1.0,nan);
 result=result+badPoint(nan)+badPoint(inf)+badPoint(ninf)+badDiameter(0.0)+badDiameter(-1.0)+badDiameter(nan)+badDiameter(inf)+badDiameter(ninf);
 result=result+badRect(g.Rect(0.0,0.0,-1.0,1.0))+badRect(g.Rect(maximum,0.0,maximum,1.0))+badRect(g.Rect(nan,0.0,1.0,1.0))+badRect(g.Rect(inf,0.0,1.0,1.0))+badRect(g.Rect(ninf,0.0,1.0,1.0));
 result=result+badTransform(nan)+badTransform(inf)+badTransform(ninf)+badStroke(0.0,1.0)+badStroke(nan,1.0)+badStroke(inf,1.0)+badStroke(ninf,1.0)+badStroke(1.0,0.5)+badStroke(1.0,nan)+badStroke(1.0,inf)+badStroke(1.0,ninf)+badText(0.0)+badText(nan)+badText(inf)+badText(ninf);
 result=result+badPolyline()+stateErrors()+openPolyline()+pathErrors()+everyPathStateError()+secondFinish()+sealedAlias()+transformOrder(maximum);return result;}
"#;
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        run(source, optimization);
    }
}

#[test]
fn extreme_finite_zero_viewports_singular_transform_and_source_lifetimes_are_preserved() {
    let source = r#"
package consumer;import graphics as g;
g.Color c(){return g.Color(uint8(4),uint8(5),uint8(6),uint8(7));}
g.Scene makeText(){g.SceneBuilder b=g.SceneBuilder(g.Viewport(0.0,5.0));string text="é";string name="名字";g.TextStyle style=g.TextStyle(2.0,c(),g.FontRequest(g.FontFamily.Named(name),g.FontWeight.Bold,g.FontSlant.Italic),g.TextAlign.Right,g.TextBaseline.Bottom);b.drawText(&text,g.Point(0.0,0.0),&style);return b.finish();}
int main(){float64 maximum=1.7976931348623157e308;g.SceneBuilder b=g.SceneBuilder(g.Viewport(maximum,0.0));b.concatTransform(g.Transform2D(0.0,0.0,0.0,0.0,maximum,-maximum));b.intersectClipRect(g.Rect(maximum,-maximum,0.0,0.0));b.drawPoint(g.Point(maximum,-maximum),1.0,c());g.Scene finite=b.finish();if(finite.commandCount()!=3){return 1;}match(finite.commandAt(2)){g.Command.DrawPoint(p,d,color)=>{if(p.x!=maximum||p.y!=-maximum){return 2;}}g.Command.PushState=>{return 2;}g.Command.PopState=>{return 2;}g.Command.ConcatTransform(t)=>{return 2;}g.Command.IntersectClipRect(r)=>{return 2;}g.Command.DrawLine(l,s)=>{return 2;}g.Command.DrawPolyline(p,s)=>{return 2;}g.Command.DrawRect(r,p)=>{return 2;}g.Command.DrawPath(p,v)=>{return 2;}g.Command.DrawText(i)=>{return 2;}}
 g.Scene textScene=makeText();match(textScene.commandAt(0)){g.Command.DrawText(i)=>{g.TextRecord r=textScene.textRecordAt(i);if(r.content.length!=2||textScene.utf8ByteAt(r.content,0)!=uint8(195)||textScene.utf8ByteAt(r.content,1)!=uint8(169)){return 3;}match(r.font.family){g.StoredFontFamily.Named(span)=>{if(span.length!=6){return 4;}}g.StoredFontFamily.BackendDefault=>{return 4;}g.StoredFontFamily.Serif=>{return 4;}g.StoredFontFamily.SansSerif=>{return 4;}g.StoredFontFamily.Monospace=>{return 4;}}}g.Command.PushState=>{return 3;}g.Command.PopState=>{return 3;}g.Command.ConcatTransform(t)=>{return 3;}g.Command.IntersectClipRect(r)=>{return 3;}g.Command.DrawPoint(p,d,color)=>{return 3;}g.Command.DrawLine(l,s)=>{return 3;}g.Command.DrawPolyline(p,s)=>{return 3;}g.Command.DrawRect(r,p)=>{return 3;}g.Command.DrawPath(p,v)=>{return 3;}}
 g.SceneBuilder w=g.SceneBuilder(g.Viewport(5.0,0.0));g.Scene empty=w.finish();if(empty.commandCount()!=0){return 5;}return 0;}
"#;
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        run(source, optimization);
    }
}

#[test]
fn every_style_text_variant_and_all_arena_growth_paths_survive_o0_o2() {
    let source = r#"
package consumer;import graphics as g;
g.Color color(uint8 alpha){return g.Color(uint8(1),uint8(2),uint8(3),alpha);}
g.Stroke stroke(g.LineCap cap,g.LineJoin join){return g.Stroke(color(uint8(255)),1.0,cap,join,1.0);}
void text(g.SceneBuilder b,ref string value,g.FontFamily family,g.FontWeight weight,g.FontSlant slant,g.TextAlign align,g.TextBaseline baseline){g.TextStyle style=g.TextStyle(1.0,color(uint8(0)),g.FontRequest(family,weight,slant),align,baseline);b.drawText(value,g.Point(0.0,0.0),&style);}
int familyCode(g.StoredFontFamily family){match(family){g.StoredFontFamily.BackendDefault=>{return 0;}g.StoredFontFamily.Serif=>{return 1;}g.StoredFontFamily.SansSerif=>{return 2;}g.StoredFontFamily.Monospace=>{return 3;}g.StoredFontFamily.Named(span)=>{if(span.length==5){return 4;}return 9;}}}
int main(){g.SceneBuilder b=g.SceneBuilder(g.Viewport(0.0,0.0));
 b.pushState();b.pushState();b.pushState();b.pushState();b.pushState();b.popState();b.popState();b.popState();b.popState();b.popState();
 b.drawRect(g.Rect(-2.0,-3.0,0.0,0.0),g.Paint.FillOnly(g.Fill(color(uint8(0)),g.FillRule.NonZero)));
 b.drawRect(g.Rect(0.0,0.0,1.0,1.0),g.Paint.StrokeOnly(stroke(g.LineCap.Butt,g.LineJoin.Miter)));
 b.drawRect(g.Rect(0.0,0.0,1.0,1.0),g.Paint.StrokeOnly(stroke(g.LineCap.Square,g.LineJoin.Round)));
 b.drawRect(g.Rect(0.0,0.0,1.0,1.0),g.Paint.FillAndStroke(g.Fill(color(uint8(255)),g.FillRule.EvenOdd),stroke(g.LineCap.Round,g.LineJoin.Bevel)));
 Array<g.Point> p={g.Point(0.0,0.0),g.Point(1.0,1.0),g.Point(2.0,2.0),g.Point(3.0,3.0),g.Point(4.0,4.0)};b.drawPolyline(&p,stroke(g.LineCap.Butt,g.LineJoin.Miter));
 b.beginPath();b.moveTo(g.Point(0.0,0.0));b.lineTo(g.Point(1.0,1.0));b.lineTo(g.Point(2.0,2.0));b.lineTo(g.Point(3.0,3.0));b.lineTo(g.Point(4.0,4.0));b.endPath(g.Paint.FillOnly(g.Fill(color(uint8(255)),g.FillRule.NonZero)));
 string a="a";string n="named";text(b,&a,g.FontFamily.BackendDefault,g.FontWeight.Normal,g.FontSlant.Normal,g.TextAlign.Left,g.TextBaseline.Alphabetic);text(b,&a,g.FontFamily.Serif,g.FontWeight.Bold,g.FontSlant.Normal,g.TextAlign.Center,g.TextBaseline.Top);text(b,&a,g.FontFamily.SansSerif,g.FontWeight.Normal,g.FontSlant.Italic,g.TextAlign.Right,g.TextBaseline.Middle);text(b,&a,g.FontFamily.Monospace,g.FontWeight.Bold,g.FontSlant.Italic,g.TextAlign.Left,g.TextBaseline.Bottom);text(b,&a,g.FontFamily.Named(n),g.FontWeight.Bold,g.FontSlant.Italic,g.TextAlign.Center,g.TextBaseline.Alphabetic);
 g.Scene scene=b.finish();if(scene.commandCount()!=21){return 1;}
 match(scene.commandAt(10)){g.Command.DrawRect(r,p)=>{match(p){g.Paint.FillOnly(f)=>{if(f.rule!=g.FillRule.NonZero||f.color.alpha!=uint8(0)){return 2;}}g.Paint.StrokeOnly(s)=>{return 2;}g.Paint.FillAndStroke(f,s)=>{return 2;}}}g.Command.PushState=>{return 2;}g.Command.PopState=>{return 2;}g.Command.ConcatTransform(t)=>{return 2;}g.Command.IntersectClipRect(r)=>{return 2;}g.Command.DrawPoint(p,d,c)=>{return 2;}g.Command.DrawLine(l,s)=>{return 2;}g.Command.DrawPolyline(p,s)=>{return 2;}g.Command.DrawPath(p,v)=>{return 2;}g.Command.DrawText(i)=>{return 2;}}
 match(scene.commandAt(11)){g.Command.DrawRect(r,p)=>{match(p){g.Paint.StrokeOnly(s)=>{if(s.cap!=g.LineCap.Butt||s.join!=g.LineJoin.Miter||s.miterLimit!=1.0){return 3;}}g.Paint.FillOnly(f)=>{return 3;}g.Paint.FillAndStroke(f,s)=>{return 3;}}}g.Command.PushState=>{return 3;}g.Command.PopState=>{return 3;}g.Command.ConcatTransform(t)=>{return 3;}g.Command.IntersectClipRect(r)=>{return 3;}g.Command.DrawPoint(p,d,c)=>{return 3;}g.Command.DrawLine(l,s)=>{return 3;}g.Command.DrawPolyline(p,s)=>{return 3;}g.Command.DrawPath(p,v)=>{return 3;}g.Command.DrawText(i)=>{return 3;}}
 match(scene.commandAt(12)){g.Command.DrawRect(r,p)=>{match(p){g.Paint.StrokeOnly(s)=>{if(s.cap!=g.LineCap.Square||s.join!=g.LineJoin.Round){return 4;}}g.Paint.FillOnly(f)=>{return 4;}g.Paint.FillAndStroke(f,s)=>{return 4;}}}g.Command.PushState=>{return 4;}g.Command.PopState=>{return 4;}g.Command.ConcatTransform(t)=>{return 4;}g.Command.IntersectClipRect(r)=>{return 4;}g.Command.DrawPoint(p,d,c)=>{return 4;}g.Command.DrawLine(l,s)=>{return 4;}g.Command.DrawPolyline(p,s)=>{return 4;}g.Command.DrawPath(p,v)=>{return 4;}g.Command.DrawText(i)=>{return 4;}}
 match(scene.commandAt(13)){g.Command.DrawRect(r,p)=>{match(p){g.Paint.FillAndStroke(f,s)=>{if(f.rule!=g.FillRule.EvenOdd||f.color.alpha!=uint8(255)||s.cap!=g.LineCap.Round||s.join!=g.LineJoin.Bevel){return 5;}}g.Paint.FillOnly(f)=>{return 5;}g.Paint.StrokeOnly(s)=>{return 5;}}}g.Command.PushState=>{return 5;}g.Command.PopState=>{return 5;}g.Command.ConcatTransform(t)=>{return 5;}g.Command.IntersectClipRect(r)=>{return 5;}g.Command.DrawPoint(p,d,c)=>{return 5;}g.Command.DrawLine(l,s)=>{return 5;}g.Command.DrawPolyline(p,s)=>{return 5;}g.Command.DrawPath(p,v)=>{return 5;}g.Command.DrawText(i)=>{return 5;}}
 g.TextRecord r0=scene.textRecordAt(0);g.TextRecord r1=scene.textRecordAt(1);g.TextRecord r2=scene.textRecordAt(2);g.TextRecord r3=scene.textRecordAt(3);g.TextRecord r4=scene.textRecordAt(4);
 if(familyCode(r0.font.family)!=0||r0.align!=g.TextAlign.Left||r0.baseline!=g.TextBaseline.Alphabetic||r0.font.weight!=g.FontWeight.Normal||r0.font.slant!=g.FontSlant.Normal){return 6;}
 if(familyCode(r1.font.family)!=1||r1.align!=g.TextAlign.Center||r1.baseline!=g.TextBaseline.Top||r1.font.weight!=g.FontWeight.Bold||r1.font.slant!=g.FontSlant.Normal){return 6;}
 if(familyCode(r2.font.family)!=2||r2.align!=g.TextAlign.Right||r2.baseline!=g.TextBaseline.Middle||r2.font.weight!=g.FontWeight.Normal||r2.font.slant!=g.FontSlant.Italic){return 6;}
 if(familyCode(r3.font.family)!=3||r3.align!=g.TextAlign.Left||r3.baseline!=g.TextBaseline.Bottom||r3.font.weight!=g.FontWeight.Bold||r3.font.slant!=g.FontSlant.Italic){return 6;}
 if(familyCode(r4.font.family)!=4||r4.align!=g.TextAlign.Center||r4.baseline!=g.TextBaseline.Alphabetic||r4.font.weight!=g.FontWeight.Bold||r4.font.slant!=g.FontSlant.Italic){return 6;}
 return 0;}
"#;
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        run(source, optimization);
    }
}

#[test]
fn representation_backend_boundary_and_static_ir_are_closed() {
    for required in [
        "Buffer<Command> commands;",
        "Buffer<Point> polylinePoints;",
        "Buffer<PathVerb> pathVerbs;",
        "Buffer<TextRecord> textRecords;",
        "Buffer<uint8> utf8Bytes;",
        "class SceneBuilder",
        "public class Scene",
        "float64 m11;",
        "uint8 alpha;",
        "std.Text.byteAt",
    ] {
        assert!(LIBRARY.contains(required), "missing {required}");
    }
    let scene = LIBRARY.split("public class Scene {").nth(1).unwrap();
    let scene = scene.split("public class SceneBuilder {").next().unwrap();
    for field in [
        "Buffer<Command> commands;",
        "Buffer<Point> polylinePoints;",
        "Buffer<PathVerb> pathVerbs;",
        "Buffer<TextRecord> textRecords;",
        "Buffer<uint8> utf8Bytes;",
    ] {
        assert_eq!(scene.matches(field).count(), 1, "{field}");
    }
    assert!(!scene.contains("public mut"));
    assert!(!LIBRARY.contains("interface "));
    let lower = LIBRARY.to_ascii_lowercase();
    for forbidden in [
        "svg",
        "<xml",
        "png",
        "raster",
        "window",
        "toolkit",
        "gpu",
        "renderer",
        "callback",
        "reflection",
    ] {
        assert!(!lower.contains(forbidden), "source leaked {forbidden}");
    }

    let compilation = compile(
        "package consumer;import graphics as g;int main(){g.SceneBuilder b=g.SceneBuilder(g.Viewport(1.0,1.0));b.drawPoint(g.Point(0.0,0.0),1.0,g.Color(uint8(0),uint8(0),uint8(0),uint8(255)));g.Scene s=b.finish();g.Command c=s.commandAt(0);return 0;}",
        OptimizationLevel::O0,
    );
    for phase in [Emit::Hir, Emit::Mir, Emit::Ssa] {
        let dump = &compilation.dumps[&phase];
        assert!(dump.contains("ClassField"), "{phase:?}");
        assert!(!dump.contains("InterfaceCall"), "{phase:?}");
    }
    for forbidden in ["vtable", "reflection", "svg", "png", "gpu"] {
        assert!(!compilation.llvm.to_ascii_lowercase().contains(forbidden));
    }
    assert!(compilation.llvm.contains("aether_drop_B"));
}

#[test]
fn one_and_four_primitives_have_the_same_allocation_count_and_all_resources_drop() {
    fn source(count: usize) -> String {
        let mut body = String::from(
            "package consumer;import graphics as g;int main(){g.SceneBuilder b=g.SceneBuilder(g.Viewport(1.0,1.0));",
        );
        for index in 0..count {
            use std::fmt::Write;
            write!(body,"b.drawPoint(g.Point({index}.0,0.0),1.0,g.Color(uint8(0),uint8(0),uint8(0),uint8(255)));").unwrap();
        }
        body.push_str("g.Scene s=b.finish();return int(s.commandCount()-");
        body.push_str(&count.to_string());
        body.push_str(");}");
        body
    }

    let one = compile(&source(1), OptimizationLevel::O0);
    let four = compile(&source(4), OptimizationLevel::O0);
    // The exact totals establish two objects, five final Scene backings, six
    // transient builder backings, one command growth, sealing replacement and
    // balanced destruction. Four primitives still fit the first arena block.
    let expected = [2, 8, 10, 2, 11, 20, 20];
    let names = [
        "object_alloc",
        "object_retain",
        "object_release",
        "object_destroy",
        "object_buffer_drop",
        "heap_alloc",
        "heap_free",
    ];
    let observed = names.map(|name| observe_counter(&one.llvm, name));
    assert_eq!(observed, expected);
    let four_observed = names.map(|name| observe_counter(&four.llvm, name));
    assert_eq!(four_observed[0], 2);
    assert_eq!(four_observed[3..], [2, 11, 20, 20]);
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        assert_eq!(
            execute_llvm(&instrument(&one.llvm, expected), optimization),
            0,
            "one primitive at {optimization:?}"
        );
        let four_expected = [2, four_observed[1], four_observed[2], 2, 11, 20, 20];
        assert_eq!(
            execute_llvm(&instrument(&four.llvm, four_expected), optimization),
            0,
            "four primitives at {optimization:?}"
        );
    }

    // Exercise a Scene where all five final arenas are non-empty. The last
    // release must destroy both classes and every Buffer owner exactly once.
    let full = compile(
        r#"package consumer;import graphics as g;int main(){g.SceneBuilder b=g.SceneBuilder(g.Viewport(1.0,1.0));g.Color c=g.Color(uint8(0),uint8(0),uint8(0),uint8(255));g.Stroke st=g.Stroke(c,1.0,g.LineCap.Butt,g.LineJoin.Miter,1.0);Array<g.Point> p={g.Point(0.0,0.0),g.Point(1.0,1.0)};b.drawPolyline(&p,st);b.beginPath();b.moveTo(g.Point(0.0,0.0));b.lineTo(g.Point(1.0,1.0));b.endPath(g.Paint.FillOnly(g.Fill(c,g.FillRule.NonZero)));string t="x";g.TextStyle ts=g.TextStyle(1.0,c,g.FontRequest(g.FontFamily.BackendDefault,g.FontWeight.Normal,g.FontSlant.Normal),g.TextAlign.Left,g.TextBaseline.Alphabetic);b.drawText(&t,g.Point(0.0,0.0),&ts);g.Scene s=b.finish();return int(s.commandCount()-3);}"#,
        OptimizationLevel::O0,
    );
    let full_observed = names.map(|name| observe_counter(&full.llvm, name));
    assert_eq!(full_observed[0], 2);
    assert_eq!(full_observed[3], 2);
    assert_eq!(full_observed[4], 11);
    assert_eq!(full_observed[5], full_observed[6]);
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        assert_eq!(
            execute_llvm(&instrument(&full.llvm, full_observed), optimization),
            0,
            "five non-empty arenas at {optimization:?}"
        );
    }
}
