//! PLOTS-TICK-LABEL-FORMAT-V1 contextual numeric-label qualification.

use std::{collections::BTreeMap, fmt::Write, fs, path::PathBuf, process::Command};

use aether_driver::{
    ClangToolchain, CompilationSession, Emit, OptimizationLevel, compile_session_with_optimization,
};

const GRAPHICS: &str = include_str!("../../../../graphics/src/lib.ae");
const GRAPHICS_SVG: &str = include_str!("../../../../graphics/src/svg.ae");
const PLOTS: &str = include_str!("../../../../plots/src/lib.ae");
const PLOTS_SVG: &str = include_str!("../../../../plots/src/svg.ae");

const CASES: &[(&str, &str, &str)] = &[
    ("noise_one", "1.0000000000000002", "5.000000000000001"),
    ("noise_five", "4.999999999999999", "9.0"),
    ("noise_seven", "6.999999999999998", "11.0"),
    ("signed", "-1.0", "1.0"),
    ("quarters", "0.0", "1.0"),
    ("near_zero", "0.0", "4e-7"),
    ("fixed_edge", "1e-6", "5e-6"),
    ("narrow", "1.0", "1.0000000000000009"),
    ("subnormal", "5e-324", "2.5e-323"),
    ("large", "1e100", "5e100"),
    ("carry", "9.9996", "10.0004"),
    ("repeated", "1e20", "1.0000000000000002e20"),
];

struct Project(PathBuf);

impl Project {
    fn new(source: &str) -> Self {
        static NEXT: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
        let root = std::env::temp_dir().join(format!(
            "aether-plots-tick-labels-{}-{}",
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
}

impl Drop for Project {
    fn drop(&mut self) {
        fs::remove_dir_all(&self.0).unwrap();
    }
}

fn source() -> String {
    let mut calls = String::new();
    for (name, minimum, maximum) in CASES {
        write!(
            calls,
            "string {name}=\"{name}.svg\";saveCase({minimum},{maximum},&{name});"
        )
        .unwrap();
    }
    format!(
        r"package qualification;
import plots as p;import plots.svg as svg;import graphics as g;
void saveCase(float64 minimum,float64 maximum,ref string path){{
 p.FigureOptions options=p.defaultOptions();
 options.xLimits=p.LimitMode.Explicit(p.Limits(minimum,maximum));
 options.yLimits=p.LimitMode.Explicit(p.Limits(-1.0,1.0));
 p.Figure2D figure=p.figure(&options);svg.save(&figure,path);
}}
int main(){{{calls}return 0;}}"
    )
}

fn render(optimization: OptimizationLevel) -> BTreeMap<&'static str, String> {
    let source = source();
    let project = Project::new(&source);
    let compilation = compile_session_with_optimization(
        CompilationSession::discover(&project.0.join("main.ae")).unwrap(),
        &[Emit::Llvm],
        optimization,
    )
    .unwrap_or_else(|diagnostics| panic!("{source}\n{diagnostics:#?}"));
    let executable = project.0.join("qualification");
    ClangToolchain::default()
        .with_optimization(optimization)
        .link_executable(&compilation.llvm, &executable)
        .unwrap();
    assert_eq!(
        Command::new(executable)
            .current_dir(&project.0)
            .status()
            .unwrap()
            .code(),
        Some(0)
    );
    CASES
        .iter()
        .map(|(name, _, _)| {
            (
                *name,
                fs::read_to_string(project.0.join(format!("{name}.svg"))).unwrap(),
            )
        })
        .collect()
}

fn x_labels(svg: &str) -> Vec<String> {
    roxmltree::Document::parse(svg)
        .unwrap()
        .descendants()
        .filter(|node| node.has_tag_name("text"))
        .take(10)
        .step_by(2)
        .map(|node| node.text().unwrap().to_owned())
        .collect()
}

fn assert_strict_when_distinct(labels: &[String]) {
    for pair in labels.windows(2) {
        let left: f64 = pair[0].parse().unwrap();
        let right: f64 = pair[1].parse().unwrap();
        assert!(left <= right, "{labels:?}");
        if pair[0] != pair[1] {
            assert!(left < right, "{labels:?}");
        }
    }
}

#[test]
fn contextual_labels_cover_rounding_extremes_and_are_identical_o0_o2() {
    let o0 = render(OptimizationLevel::O0);
    let o2 = render(OptimizationLevel::O2);
    assert_eq!(o0, o2);

    assert_eq!(x_labels(&o0["noise_one"])[0], "1");
    assert_eq!(x_labels(&o0["noise_five"])[0], "5");
    assert_eq!(x_labels(&o0["noise_seven"])[0], "7");
    assert_eq!(x_labels(&o0["signed"]), ["-1", "-0.5", "0", "0.5", "1"]);
    assert_eq!(x_labels(&o0["quarters"]), ["0", "0.25", "0.5", "0.75", "1"]);
    assert_eq!(
        x_labels(&o0["near_zero"]),
        ["0", "1e-7", "2e-7", "3e-7", "4e-7"]
    );
    assert_eq!(
        x_labels(&o0["fixed_edge"]),
        ["0.000001", "0.000002", "0.000003", "0.000004", "0.000005"]
    );
    assert_eq!(
        x_labels(&o0["large"]),
        ["1e+100", "2e+100", "3e+100", "4e+100", "5e+100"]
    );
    assert_eq!(
        x_labels(&o0["carry"]),
        ["9.9996", "9.9998", "10", "10.0002", "10.0004"]
    );

    for name in ["narrow", "subnormal", "repeated"] {
        let labels = x_labels(&o0[name]);
        assert_eq!(labels.len(), 5);
        assert_strict_when_distinct(&labels);
    }
    assert!(
        x_labels(&o0["subnormal"])
            .iter()
            .all(|label| label.contains('e'))
    );
    assert_ne!(x_labels(&o0["repeated"])[0], x_labels(&o0["repeated"])[4]);
}

#[test]
fn implementation_is_local_and_retains_canonical_fallback() {
    assert!(PLOTS.contains("std.Format.fixed"));
    assert!(PLOTS.contains("std.Format.scientific"));
    assert!(PLOTS.contains("TickFormat(true, false, 0)"));
    assert!(PLOTS.contains("tickValue(resolvedX, tick)"));
    assert!(PLOTS.contains("tickValue(resolvedY, tick)"));
}
