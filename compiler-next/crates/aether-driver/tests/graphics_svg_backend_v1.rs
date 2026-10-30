//! GRAPHICS-SVG-BACKEND-V1 functional, structural and determinism qualification.

use std::{fs, path::PathBuf, process::Command};

use aether_driver::{
    ClangToolchain, Compilation, CompilationSession, Emit, OptimizationLevel,
    compile_session_with_optimization,
};

const FOUNDATION: &str = include_str!("../../../../graphics/src/lib.ae");
const SVG_BACKEND: &str = include_str!("../../../../graphics/src/svg.ae");
const REPRESENTATIVE_GOLDEN: &str =
    include_str!("../../../../graphics/tests/goldens/representative.svg");
const EMPTY_GOLDEN: &str = include_str!("../../../../graphics/tests/goldens/empty.svg");

struct Project {
    root: PathBuf,
    consumer: PathBuf,
}

impl Project {
    fn new(label: &str, source: &str) -> Self {
        static NEXT: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
        let root = std::env::temp_dir().join(format!(
            "aether-graphics-svg-{label}-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, std::sync::atomic::Ordering::Relaxed)
        ));
        fs::create_dir_all(&root).unwrap();
        fs::write(root.join("graphics.ae"), FOUNDATION).unwrap();
        fs::write(root.join("svg.ae"), SVG_BACKEND).unwrap();
        let entry = root.join("main.ae");
        fs::write(&entry, source).unwrap();
        Self {
            root,
            consumer: entry,
        }
    }

    fn output(&self, name: &str) -> PathBuf {
        self.root.join(name)
    }
}

impl Drop for Project {
    fn drop(&mut self) {
        fs::remove_dir_all(&self.root).unwrap();
    }
}

fn aether_string(path: &std::path::Path) -> String {
    path.to_string_lossy()
        .replace('\\', "\\\\")
        .replace('"', "\\\"")
}

fn run_source(source: &str, optimization: OptimizationLevel) -> (Project, i32) {
    let project = Project::new("run", source);
    let session = CompilationSession::discover(&project.consumer).unwrap();
    let compilation = compile_session_with_optimization(session, &[Emit::Llvm], optimization)
        .unwrap_or_else(|diagnostics| panic!("{source}\n{diagnostics:#?}"));
    let executable = project.output("qualification");
    ClangToolchain::default()
        .with_optimization(optimization)
        .link_executable(&compilation.llvm, &executable)
        .unwrap();
    let status = Command::new(executable).status().unwrap().code().unwrap();
    (project, status)
}

fn compile(source: &str, optimization: OptimizationLevel) -> Compilation {
    let project = Project::new("compile", source);
    compile_session_with_optimization(
        CompilationSession::discover(&project.consumer).unwrap(),
        &[Emit::Hir, Emit::Mir, Emit::Ssa, Emit::Llvm],
        optimization,
    )
    .unwrap_or_else(|diagnostics| panic!("{source}\n{diagnostics:#?}"))
}

fn execute_llvm(llvm: &str, optimization: OptimizationLevel) -> i32 {
    let project = Project::new("llvm", "package svgQualification;int main(){return 0;}");
    let executable = project.output("instrumented");
    ClangToolchain::default()
        .with_optimization(optimization)
        .link_executable(llvm, &executable)
        .unwrap();
    Command::new(executable).status().unwrap().code().unwrap()
}

fn render_source(body: &str, output: &std::path::Path) -> String {
    format!(
        "package svgQualification;import graphics as g;import graphics.svg as svg;{}string outputPath=\"{}\";svg.save(&scene,&outputPath);if(byteLength(document)==0){{return 1;}}return 0;}}",
        body,
        aether_string(output)
    )
}

const EMPTY_BODY: &str = "int main(){g.SceneBuilder builder=g.SceneBuilder(g.Viewport(0.0,0.0));g.Scene scene=builder.finish();string document=svg.render(&scene);";

const REPRESENTATIVE_BODY: &str = r#"
g.Color color(uint8 red,uint8 green,uint8 blue,uint8 alpha){return g.Color(red,green,blue,alpha);}
g.Stroke stroke(){return g.Stroke(color(uint8(1),uint8(2),uint8(255),uint8(128)),2.5,g.LineCap.Round,g.LineJoin.Bevel,4.0);}
int main(){g.SceneBuilder builder=g.SceneBuilder(g.Viewport(100.0,50.0));
 builder.pushState();builder.concatTransform(g.Transform2D(2.0,0.5,-0.25,3.0,4.0,5.0));builder.intersectClipRect(g.Rect(10.0,5.0,80.0,40.0));
 builder.drawPoint(g.Point(1.0,2.0),3.0,color(uint8(255),uint8(0),uint8(16),uint8(1)));
 builder.drawLine(g.Line(g.Point(0.0,-0.0),g.Point(5.0,6.0)),stroke());
 Array<g.Point> points={g.Point(0.0,1.0),g.Point(2.0,3.0),g.Point(4.0,5.0)};builder.drawPolyline(&points,stroke());
 builder.drawRect(g.Rect(7.0,8.0,9.0,0.0),g.Paint.FillAndStroke(g.Fill(color(uint8(10),uint8(11),uint8(12),uint8(255)),g.FillRule.EvenOdd),stroke()));
 builder.beginPath();builder.moveTo(g.Point(0.0,0.0));builder.lineTo(g.Point(1.0,1.0));builder.cubicTo(g.Point(2.0,3.0),g.Point(4.0,5.0),g.Point(6.0,7.0));builder.closePath();builder.moveTo(g.Point(8.0,9.0));builder.endPath(g.Paint.FillOnly(g.Fill(color(uint8(0),uint8(0),uint8(0),uint8(0)),g.FillRule.NonZero)));
 string text="  A<&>\"'\t\n\r hé́😀 ";string family="serif, A\"B\\C<&>'";g.TextStyle style=g.TextStyle(12.5,color(uint8(20),uint8(30),uint8(40),uint8(254)),g.FontRequest(g.FontFamily.Named(family),g.FontWeight.Bold,g.FontSlant.Italic),g.TextAlign.Center,g.TextBaseline.Bottom);builder.drawText(&text,g.Point(11.0,12.0),&style);
 builder.pushState();builder.intersectClipRect(g.Rect(200.0,200.0,0.0,0.0));builder.popState();builder.popState();
 g.Scene scene=builder.finish();string document=svg.render(&scene);
"#;

const STYLE_BODY: &str = r#"
g.Color c(uint8 alpha){return g.Color(uint8(0),uint8(127),uint8(255),alpha);}
g.Stroke s(g.LineCap cap,g.LineJoin join,uint8 alpha){return g.Stroke(c(alpha),1.0,cap,join,1.0);}
void addText(g.SceneBuilder builder,ref string text,g.FontFamily family,g.FontWeight weight,g.FontSlant slant,g.TextAlign align,g.TextBaseline baseline){g.TextStyle style=g.TextStyle(3.0,c(uint8(255)),g.FontRequest(family,weight,slant),align,baseline);builder.drawText(text,g.Point(1.0,2.0),&style);}
int main(){g.SceneBuilder builder=g.SceneBuilder(g.Viewport(20.0,20.0));
 builder.drawRect(g.Rect(0.0,0.0,1.0,1.0),g.Paint.FillOnly(g.Fill(c(uint8(0)),g.FillRule.NonZero)));
 builder.drawRect(g.Rect(1.0,0.0,1.0,1.0),g.Paint.StrokeOnly(s(g.LineCap.Butt,g.LineJoin.Miter,uint8(255))));
 builder.drawRect(g.Rect(2.0,0.0,1.0,1.0),g.Paint.StrokeOnly(s(g.LineCap.Square,g.LineJoin.Round,uint8(254))));
 builder.drawRect(g.Rect(3.0,0.0,1.0,1.0),g.Paint.FillAndStroke(g.Fill(c(uint8(1)),g.FillRule.EvenOdd),s(g.LineCap.Round,g.LineJoin.Bevel,uint8(1))));
 string text="x";string named="Missing Font";
 addText(builder,&text,g.FontFamily.BackendDefault,g.FontWeight.Normal,g.FontSlant.Normal,g.TextAlign.Left,g.TextBaseline.Alphabetic);
 addText(builder,&text,g.FontFamily.Serif,g.FontWeight.Bold,g.FontSlant.Normal,g.TextAlign.Center,g.TextBaseline.Top);
 addText(builder,&text,g.FontFamily.SansSerif,g.FontWeight.Normal,g.FontSlant.Italic,g.TextAlign.Right,g.TextBaseline.Middle);
 addText(builder,&text,g.FontFamily.Monospace,g.FontWeight.Bold,g.FontSlant.Italic,g.TextAlign.Left,g.TextBaseline.Bottom);
 addText(builder,&text,g.FontFamily.Named(named),g.FontWeight.Normal,g.FontSlant.Normal,g.TextAlign.Center,g.TextBaseline.Alphabetic);
 g.Scene scene=builder.finish();string document=svg.render(&scene);
"#;

const EXTREME_BODY: &str = r"
int main(){float64 minimum=5e-324;float64 maximum=1.7976931348623157e308;g.SceneBuilder builder=g.SceneBuilder(g.Viewport(maximum,minimum));builder.drawPoint(g.Point(maximum,-maximum),minimum,g.Color(uint8(255),uint8(255),uint8(255),uint8(255)));builder.drawPoint(g.Point(0.0,0.0),maximum,g.Color(uint8(255),uint8(255),uint8(255),uint8(255)));builder.drawLine(g.Line(g.Point(-0.0,0.0),g.Point(minimum,-minimum)),g.Stroke(g.Color(uint8(0),uint8(0),uint8(0),uint8(255)),minimum,g.LineCap.Butt,g.LineJoin.Miter,maximum));g.Scene scene=builder.finish();string document=svg.render(&scene);
";

const STATE_BODY: &str = r"
g.Paint p(){return g.Paint.FillOnly(g.Fill(g.Color(uint8(0),uint8(0),uint8(0),uint8(255)),g.FillRule.NonZero));}
int main(){g.SceneBuilder builder=g.SceneBuilder(g.Viewport(10.0,10.0));builder.drawRect(g.Rect(0.0,0.0,1.0,1.0),p());builder.pushState();builder.concatTransform(g.Transform2D(1.0,0.0,0.0,1.0,2.0,3.0));builder.intersectClipRect(g.Rect(1.0,1.0,8.0,8.0));builder.drawRect(g.Rect(1.0,1.0,1.0,1.0),p());builder.pushState();builder.concatTransform(g.Transform2D(2.0,0.0,0.0,2.0,0.0,0.0));builder.concatTransform(g.Transform2D(1.0,1.0,0.0,1.0,0.0,0.0));builder.intersectClipRect(g.Rect(2.0,2.0,2.0,2.0));builder.drawRect(g.Rect(2.0,2.0,1.0,1.0),p());builder.popState();builder.drawRect(g.Rect(3.0,3.0,1.0,1.0),p());builder.popState();builder.drawRect(g.Rect(4.0,4.0,1.0,1.0),p());builder.intersectClipRect(g.Rect(0.0,0.0,5.0,5.0));builder.drawRect(g.Rect(5.0,5.0,1.0,1.0),p());g.Scene scene=builder.finish();string document=svg.render(&scene);
";

fn render(body: &str, optimization: OptimizationLevel) -> String {
    let project = Project::new("render", "package svgQualification;int main(){return 0;}");
    let output = project.output("result.svg");
    let source = render_source(body, &output);
    fs::write(&project.consumer, &source).unwrap();
    let compilation = compile_session_with_optimization(
        CompilationSession::discover(&project.consumer).unwrap(),
        &[Emit::Llvm],
        optimization,
    )
    .unwrap_or_else(|diagnostics| panic!("{source}\n{diagnostics:#?}"));
    let executable = project.output("qualification");
    ClangToolchain::default()
        .with_optimization(optimization)
        .link_executable(&compilation.llvm, &executable)
        .unwrap();
    assert_eq!(Command::new(executable).status().unwrap().code(), Some(0));
    fs::read_to_string(output).unwrap()
}

#[test]
fn empty_and_representative_goldens_match_at_o0_and_o2() {
    for (body, golden) in [
        (EMPTY_BODY, EMPTY_GOLDEN),
        (REPRESENTATIVE_BODY, REPRESENTATIVE_GOLDEN),
    ] {
        let o0 = render(body, OptimizationLevel::O0);
        let o2 = render(body, OptimizationLevel::O2);
        assert_eq!(o0, o2);
        assert_eq!(o0, golden);
    }
}

#[test]
fn representative_svg_is_well_formed_and_structurally_exact() {
    let svg = render(REPRESENTATIVE_BODY, OptimizationLevel::O0);
    let document = roxmltree::Document::parse(&svg).unwrap();
    let root = document.root_element();
    assert_eq!(
        root.tag_name().namespace(),
        Some("http://www.w3.org/2000/svg")
    );
    assert_eq!(
        (root.attribute("width"), root.attribute("height")),
        (Some("100"), Some("50"))
    );
    assert_eq!(root.attribute("viewBox"), Some("0 0 100 50"));

    let clips: Vec<_> = root
        .descendants()
        .filter(|node| node.has_tag_name("clipPath"))
        .collect();
    assert_eq!(clips.len(), 3);
    for (index, clip) in clips.iter().enumerate() {
        assert_eq!(
            clip.attribute("id"),
            Some(format!("graphics-clip-{index}").as_str())
        );
        assert_eq!(clip.attribute("clipPathUnits"), Some("userSpaceOnUse"));
    }
    let draws: Vec<_> = root
        .children()
        .filter(|node| node.has_tag_name("g"))
        .map(|outer| {
            outer
                .first_element_child()
                .unwrap()
                .first_element_child()
                .unwrap()
                .tag_name()
                .name()
        })
        .collect();
    assert_eq!(
        draws,
        ["circle", "line", "polyline", "rect", "path", "text"]
    );
    let text = root
        .descendants()
        .find(|node| node.has_tag_name("text"))
        .unwrap();
    assert_eq!(text.text(), Some("  A<&>\"'\t\n\r hé́😀 "));
    assert_eq!(
        text.attribute("font-family"),
        Some("\"serif, A\\22 B\\5C C<&>'\"")
    );
    assert_eq!(text.attribute("direction"), Some("ltr"));
    assert_eq!(text.attribute("writing-mode"), Some("horizontal-tb"));
    assert!(
        root.descendants()
            .filter(|node| node.has_tag_name("g"))
            .all(|node| {
                node.attribute("clip-path").is_some() || node.attribute("transform").is_some()
            })
    );
}

#[test]
fn invalid_xml_text_is_atomic_and_io_errors_are_translated() {
    let source = r#"
package svgQualification;import graphics as g;import graphics.svg as svg;
g.Color c(){return g.Color(uint8(0),uint8(0),uint8(0),uint8(255));}
int main(){g.SceneBuilder b=g.SceneBuilder(g.Viewport(1.0,1.0));string text="bad\0";g.TextStyle style=g.TextStyle(1.0,c(),g.FontRequest(g.FontFamily.BackendDefault,g.FontWeight.Normal,g.FontSlant.Normal),g.TextAlign.Left,g.TextBaseline.Alphabetic);b.drawText(&text,g.Point(0.0,0.0),&style);g.Scene scene=b.finish();int caught=0;try{string impossible=svg.render(&scene);}catch(g.GraphicsTextException error){caught=caught+1;}string missing="/this/aether/path/does/not/exist/result.svg";g.SceneBuilder okBuilder=g.SceneBuilder(g.Viewport(1.0,1.0));g.Scene ok=okBuilder.finish();try{svg.save(&ok,&missing);}catch(g.GraphicsIoException error){caught=caught+1;}return caught-2;}
"#;
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        let (_project, status) = run_source(source, optimization);
        assert_eq!(status, 0, "{optimization:?}");
    }
}

#[test]
fn every_paint_stroke_font_alignment_and_baseline_variant_is_serialized() {
    let o0 = render(STYLE_BODY, OptimizationLevel::O0);
    let o2 = render(STYLE_BODY, OptimizationLevel::O2);
    assert_eq!(o0, o2);
    let document = roxmltree::Document::parse(&o0).unwrap();
    let rectangles: Vec<_> = document
        .descendants()
        .filter(|node| node.has_tag_name("rect"))
        .skip(1)
        .collect();
    assert_eq!(rectangles.len(), 4);
    assert_eq!(rectangles[0].attribute("fill-opacity"), Some("0"));
    assert_eq!(rectangles[0].attribute("stroke"), Some("none"));
    assert_eq!(rectangles[1].attribute("fill"), Some("none"));
    assert_eq!(rectangles[1].attribute("stroke-linecap"), Some("butt"));
    assert_eq!(rectangles[1].attribute("stroke-linejoin"), Some("miter"));
    assert_eq!(rectangles[2].attribute("stroke-linecap"), Some("square"));
    assert_eq!(rectangles[2].attribute("stroke-linejoin"), Some("round"));
    assert_eq!(rectangles[3].attribute("fill-rule"), Some("evenodd"));
    assert_eq!(rectangles[3].attribute("stroke-linecap"), Some("round"));
    assert_eq!(rectangles[3].attribute("stroke-linejoin"), Some("bevel"));

    let texts: Vec<_> = document
        .descendants()
        .filter(|node| node.has_tag_name("text"))
        .collect();
    assert_eq!(texts.len(), 5);
    assert_eq!(texts[0].attribute("font-family"), None);
    assert_eq!(texts[1].attribute("font-family"), Some("serif"));
    assert_eq!(texts[2].attribute("font-family"), Some("sans-serif"));
    assert_eq!(texts[3].attribute("font-family"), Some("monospace"));
    assert_eq!(texts[4].attribute("font-family"), Some("\"Missing Font\""));
    assert_eq!(
        texts
            .iter()
            .map(|node| node.attribute("text-anchor").unwrap())
            .collect::<Vec<_>>(),
        ["start", "middle", "end", "start", "middle"]
    );
    assert_eq!(
        texts
            .iter()
            .map(|node| node.attribute("dominant-baseline").unwrap())
            .collect::<Vec<_>>(),
        [
            "alphabetic",
            "text-before-edge",
            "central",
            "text-after-edge",
            "alphabetic"
        ]
    );
}

#[test]
fn finite_extremes_subnormals_and_signed_zero_use_canonical_numbers() {
    let o0 = render(EXTREME_BODY, OptimizationLevel::O0);
    let o2 = render(EXTREME_BODY, OptimizationLevel::O2);
    assert_eq!(o0, o2);
    assert!(o0.contains("width=\"1.7976931348623157e+308\" height=\"5e-324\""));
    assert!(o0.contains("r=\"5e-324\""));
    assert!(o0.contains("r=\"1.7976931348623157e+308\""));
    assert!(o0.contains("x1=\"0\" y1=\"0\" x2=\"5e-324\" y2=\"-5e-324\""));
    assert!(o0.contains("stroke-miterlimit=\"1.7976931348623157e+308\""));
    roxmltree::Document::parse(&o0).unwrap();
}

#[test]
fn state_stack_restores_transform_and_clip_ids_without_reordering_draws() {
    let svg = render(STATE_BODY, OptimizationLevel::O0);
    assert_eq!(svg, render(STATE_BODY, OptimizationLevel::O2));
    let document = roxmltree::Document::parse(&svg).unwrap();
    let outer: Vec<_> = document
        .root_element()
        .children()
        .filter(|node| node.has_tag_name("g"))
        .collect();
    assert_eq!(outer.len(), 6);
    assert_eq!(
        outer
            .iter()
            .map(|node| node.attribute("clip-path").unwrap())
            .collect::<Vec<_>>(),
        [
            "url(#graphics-clip-0)",
            "url(#graphics-clip-1)",
            "url(#graphics-clip-2)",
            "url(#graphics-clip-1)",
            "url(#graphics-clip-0)",
            "url(#graphics-clip-3)"
        ]
    );
    assert_eq!(
        outer
            .iter()
            .map(|node| node
                .first_element_child()
                .unwrap()
                .attribute("transform")
                .unwrap())
            .collect::<Vec<_>>(),
        [
            "matrix(1 0 0 1 0 0)",
            "matrix(1 0 0 1 2 3)",
            "matrix(2 2 0 2 2 3)",
            "matrix(1 0 0 1 2 3)",
            "matrix(1 0 0 1 0 0)",
            "matrix(1 0 0 1 0 0)"
        ]
    );
    assert_eq!(
        outer
            .iter()
            .map(|node| node
                .descendants()
                .find(|child| child.has_tag_name("rect"))
                .unwrap()
                .attribute("x")
                .unwrap())
            .collect::<Vec<_>>(),
        ["0", "1", "2", "3", "4", "5"]
    );
}

#[test]
fn zero_axis_viewports_degenerate_lines_large_polyline_and_singular_transform_work() {
    let body = r"
g.Color c(){return g.Color(uint8(0),uint8(0),uint8(0),uint8(255));}
g.Stroke s(g.LineCap cap){return g.Stroke(c(),1.0,cap,g.LineJoin.Miter,1.0);}
int main(){g.SceneBuilder builder=g.SceneBuilder(g.Viewport(0.0,5.0));builder.intersectClipRect(g.Rect(0.0,0.0,0.0,5.0));builder.intersectClipRect(g.Rect(0.0,0.0,0.0,5.0));builder.concatTransform(g.Transform2D(0.0,0.0,0.0,0.0,0.0,0.0));builder.drawLine(g.Line(g.Point(1.0,1.0),g.Point(1.0,1.0)),s(g.LineCap.Butt));builder.drawLine(g.Line(g.Point(2.0,2.0),g.Point(2.0,2.0)),s(g.LineCap.Round));builder.drawLine(g.Line(g.Point(3.0,3.0),g.Point(3.0,3.0)),s(g.LineCap.Square));builder.beginPolyline();usize i=0;while(i<64){builder.addPolylinePoint(g.Point(float64(i),float64(i)));i=i+1;}builder.endPolyline(s(g.LineCap.Butt));g.Scene scene=builder.finish();string document=svg.render(&scene);
";
    let o0 = render(body, OptimizationLevel::O0);
    let o2 = render(body, OptimizationLevel::O2);
    assert_eq!(o0, o2);
    let document = roxmltree::Document::parse(&o0).unwrap();
    let root = document.root_element();
    assert_eq!(
        (root.attribute("width"), root.attribute("height")),
        (Some("0"), Some("5"))
    );
    assert_eq!(
        root.descendants()
            .filter(|node| node.has_tag_name("clipPath"))
            .count(),
        3
    );
    let lines: Vec<_> = root
        .descendants()
        .filter(|node| node.has_tag_name("line"))
        .collect();
    assert_eq!(
        lines
            .iter()
            .map(|node| node.attribute("stroke-linecap").unwrap())
            .collect::<Vec<_>>(),
        ["butt", "round", "square"]
    );
    assert!(
        lines
            .iter()
            .all(|node| node.attribute("x1") == node.attribute("x2")
                && node.attribute("y1") == node.attribute("y2"))
    );
    let polyline = root
        .descendants()
        .find(|node| node.has_tag_name("polyline"))
        .unwrap();
    assert_eq!(polyline.attribute("points").unwrap().split(' ').count(), 64);
    assert!(
        root.descendants()
            .filter(|node| node.has_tag_name("g"))
            .filter_map(|node| node.attribute("transform"))
            .all(|value| value == "matrix(0 0 0 0 0 0)")
    );

    let width_only = "int main(){g.SceneBuilder builder=g.SceneBuilder(g.Viewport(5.0,0.0));g.Scene scene=builder.finish();string document=svg.render(&scene);";
    let second = render(width_only, OptimizationLevel::O0);
    let second_document = roxmltree::Document::parse(&second).unwrap();
    assert_eq!(
        (
            second_document.root_element().attribute("width"),
            second_document.root_element().attribute("height")
        ),
        (Some("5"), Some("0"))
    );
}

#[test]
fn all_xml_invalid_scalar_classes_and_empty_named_family_are_rejected() {
    let source = r#"
package svgQualification;import graphics as g;import graphics.svg as svg;import std.Text;
g.Color c(){return g.Color(uint8(0),uint8(0),uint8(0),uint8(255));}
int reject(ref Buffer<uint8> bytes,usize count,bool named){string value=std.Text.fromUtf8(bytes,count);g.SceneBuilder b=g.SceneBuilder(g.Viewport(1.0,1.0));g.FontFamily family=g.FontFamily.BackendDefault;if(named){family=g.FontFamily.Named(value);}g.TextStyle style=g.TextStyle(1.0,c(),g.FontRequest(family,g.FontWeight.Normal,g.FontSlant.Normal),g.TextAlign.Left,g.TextBaseline.Alphabetic);b.drawText(&value,g.Point(0.0,0.0),&style);g.Scene scene=b.finish();try{string impossible=svg.render(&scene);}catch(g.GraphicsTextException error){return 0;}return 1;}
int main(){int result=0;Buffer<uint8> nul=Buffer<uint8>(1,uint8(0));result=result+reject(&nul,1,false);Buffer<uint8> low=Buffer<uint8>(1,uint8(1));result=result+reject(&low,1,false);Buffer<uint8> eight=Buffer<uint8>(1,uint8(8));result=result+reject(&eight,1,false);Buffer<uint8> eleven=Buffer<uint8>(1,uint8(11));result=result+reject(&eleven,1,false);Buffer<uint8> fourteen=Buffer<uint8>(1,uint8(14));result=result+reject(&fourteen,1,false);Buffer<uint8> thirtyOne=Buffer<uint8>(1,uint8(31));result=result+reject(&thirtyOne,1,false);Buffer<uint8> fffe=Buffer<uint8>(3,uint8(0));fffe[0]=uint8(239);fffe[1]=uint8(191);fffe[2]=uint8(190);result=result+reject(&fffe,3,false);Buffer<uint8> ffff=Buffer<uint8>(3,uint8(0));ffff[0]=uint8(239);ffff[1]=uint8(191);ffff[2]=uint8(191);result=result+reject(&ffff,3,true);Buffer<uint8> empty=Buffer<uint8>(0,uint8(0));result=result+reject(&empty,0,true);Buffer<uint8> formFeed=Buffer<uint8>(1,uint8(12));string family=std.Text.fromUtf8(&formFeed,1);g.SceneBuilder b=g.SceneBuilder(g.Viewport(1.0,1.0));string text="x";g.TextStyle style=g.TextStyle(1.0,c(),g.FontRequest(g.FontFamily.Named(family),g.FontWeight.Normal,g.FontSlant.Normal),g.TextAlign.Left,g.TextBaseline.Alphabetic);b.drawText(&text,g.Point(0.0,0.0),&style);g.Scene scene=b.finish();string valid=svg.render(&scene);if(byteLength(valid)==0){result=result+1;}return result;}
"#;
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        let (_project, status) = run_source(source, optimization);
        assert_eq!(status, 0, "{optimization:?}");
    }
}

#[test]
fn rendering_failure_does_not_open_or_truncate_the_save_target() {
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        let project = Project::new("atomic", "package svgQualification;int main(){return 0;}");
        let target = project.output("existing.svg");
        fs::write(&target, "sentinel").unwrap();
        let source = format!(
            r#"package svgQualification;import graphics as g;import graphics.svg as svg;g.Color c(){{return g.Color(uint8(0),uint8(0),uint8(0),uint8(255));}}int main(){{g.SceneBuilder b=g.SceneBuilder(g.Viewport(1.0,1.0));string text="bad\0";g.TextStyle style=g.TextStyle(1.0,c(),g.FontRequest(g.FontFamily.BackendDefault,g.FontWeight.Normal,g.FontSlant.Normal),g.TextAlign.Left,g.TextBaseline.Alphabetic);b.drawText(&text,g.Point(0.0,0.0),&style);g.Scene scene=b.finish();string path="{}";try{{svg.save(&scene,&path);}}catch(g.GraphicsTextException error){{return 0;}}return 1;}}"#,
            aether_string(&target)
        );
        fs::write(&project.consumer, &source).unwrap();
        let compilation = compile_session_with_optimization(
            CompilationSession::discover(&project.consumer).unwrap(),
            &[Emit::Llvm],
            optimization,
        )
        .unwrap();
        let executable = project.output("atomic-check");
        ClangToolchain::default()
            .with_optimization(optimization)
            .link_executable(&compilation.llvm, &executable)
            .unwrap();
        assert_eq!(Command::new(executable).status().unwrap().code(), Some(0));
        assert_eq!(fs::read_to_string(target).unwrap(), "sentinel");
    }
}

#[test]
fn geometric_growth_paths_cleanup_all_heap_allocations_at_o0_and_o2() {
    let source = r"
package svgQualification;import graphics as g;import graphics.svg as svg;
g.Color c(){return g.Color(uint8(1),uint8(2),uint8(3),uint8(255));}
int main(){g.SceneBuilder b=g.SceneBuilder(g.Viewport(100.0,100.0));usize i=0;while(i<40){b.pushState();b.intersectClipRect(g.Rect(0.0,0.0,100.0,100.0));i=i+1;}i=0;while(i<200){b.drawPoint(g.Point(float64(i),float64(i)),1.0,c());i=i+1;}i=0;while(i<40){b.popState();i=i+1;}g.Scene scene=b.finish();string document=svg.render(&scene);if(byteLength(document)<10000){return 1;}return 0;}
";
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        let compilation = compile(source, optimization);
        let guard = "  %svg_allocs = load i64, ptr @aether_heap_alloc_count\n  %svg_frees = load i64, ptr @aether_heap_free_count\n  %svg_balanced = icmp eq i64 %svg_allocs, %svg_frees\n  %svg_result_ok = icmp eq i64 %aether_result, 0\n  %svg_ok = and i1 %svg_balanced, %svg_result_ok\n  %process_status = select i1 %svg_ok, i32 0, i32 99";
        let instrumented = compilation
            .llvm
            .replace("  %process_status = trunc i64 %aether_result to i32", guard);
        assert_ne!(instrumented, compilation.llvm);
        assert_eq!(
            execute_llvm(&instrumented, optimization),
            0,
            "{optimization:?}"
        );
    }
}

#[test]
fn source_and_ir_keep_the_approved_backend_boundary() {
    assert!(SVG_BACKEND.contains("struct SvgSerializer"));
    assert!(SVG_BACKEND.contains("Buffer<uint8> output"));
    assert!(SVG_BACKEND.contains("Buffer<SerializerState> states"));
    assert!(SVG_BACKEND.contains("Buffer<graphics.Rect> clips"));
    assert!(SVG_BACKEND.contains("std.Text.fromUtf8(&serializer.output"));
    assert!(SVG_BACKEND.contains("std.File.writeText(path, &document)"));
    for forbidden in [
        "InterfaceCall",
        "Plots",
        "Matplotlib",
        "extern ",
        "intrinsic",
    ] {
        assert!(!SVG_BACKEND.contains(forbidden), "{forbidden}");
    }
    let source = render_source(
        REPRESENTATIVE_BODY,
        std::path::Path::new("/tmp/aether-svg-ir.svg"),
    );
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        let compilation = compile(&source, optimization);
        assert!(
            compilation.dumps[&Emit::Hir].contains("render"),
            "{}",
            compilation.dumps[&Emit::Hir]
        );
        assert!(compilation.dumps[&Emit::Mir].contains("ReplaceOwned"));
        assert!(compilation.dumps[&Emit::Ssa].contains("ReplaceOwned"));
        assert!(!compilation.dumps[&Emit::Ssa].contains("InterfaceCall"));
        assert!(compilation.llvm.contains("aether_text_from_utf8_prefix"));
        assert!(compilation.llvm.contains("aether_io_write_text"));
    }
}
