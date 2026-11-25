//! SHAPE-CONTRACT-DIAGNOSTICS-V1 runtime, IR and corruption qualification.

use std::fs;
use std::path::{Path, PathBuf};
use std::process::Command;

use aether_driver::{
    ClangToolchain, CompilationSession, Emit, OptimizationLevel, compile_session_with_optimization,
    compile_source_with_optimization,
};
use aether_frontend::SourceFile;

const LINEAR_ALGEBRA: &str = include_str!("../../../../linearAlgebra/src/lib.ae");

struct Artifact(PathBuf);

impl Artifact {
    fn new(label: &str) -> Self {
        static NEXT: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
        Self(std::env::temp_dir().join(format!(
            "aether-shape-diagnostic-{label}-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, std::sync::atomic::Ordering::Relaxed)
        )))
    }
}

impl Drop for Artifact {
    fn drop(&mut self) {
        let _ = fs::remove_file(&self.0);
    }
}

struct PackageArtifact(PathBuf);

impl PackageArtifact {
    fn new(label: &str) -> Self {
        static NEXT: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
        let path = std::env::temp_dir().join(format!(
            "aether-shape-diagnostic-package-{label}-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, std::sync::atomic::Ordering::Relaxed)
        ));
        fs::create_dir(&path).unwrap();
        fs::write(path.join("linearAlgebra.ae"), LINEAR_ALGEBRA).unwrap();
        Self(path)
    }
}

impl Drop for PackageArtifact {
    fn drop(&mut self) {
        fs::remove_dir_all(&self.0).unwrap();
    }
}

fn compile_and_run(
    name: &str,
    source: &str,
    optimization: OptimizationLevel,
) -> (aether_driver::Compilation, std::process::Output) {
    let compilation = compile_source_with_optimization(
        &SourceFile::new(name, source),
        &[Emit::Hir, Emit::Mir, Emit::Ssa, Emit::Llvm],
        optimization,
    )
    .unwrap_or_else(|diagnostics| panic!("{diagnostics:#?}\n{source}"));
    let artifact = Artifact::new(name);
    ClangToolchain::default()
        .with_optimization(optimization)
        .link_executable(&compilation.llvm, Path::new(&artifact.0))
        .unwrap();
    let output = Command::new(&artifact.0).output().unwrap();
    (compilation, output)
}

fn compile_package_and_run(
    label: &str,
    source: &str,
    optimization: OptimizationLevel,
) -> std::process::Output {
    let directory = PackageArtifact::new(label);
    let entry = directory.0.join("main.ae");
    fs::write(&entry, source).unwrap();
    let compilation = compile_session_with_optimization(
        CompilationSession::discover(&entry).unwrap(),
        &[Emit::Hir, Emit::Mir, Emit::Ssa, Emit::Llvm],
        optimization,
    )
    .unwrap_or_else(|diagnostics| panic!("{diagnostics:#?}\n{source}"));
    let executable = directory.0.join("program");
    ClangToolchain::default()
        .with_optimization(optimization)
        .link_executable(&compilation.llvm, &executable)
        .unwrap();
    Command::new(executable).output().unwrap()
}

#[test]
#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
fn extent_observations_reuse_the_guard_values_in_o0_and_o2() {
    use std::os::unix::process::ExitStatusExt;

    let source = "int main(){\n  Matrix<int> value=matrixFilled<int>(2,3,0);\n  shapeGuard(rows(value)==columns(value));\n  return 0;\n}";
    let expected = b"Aether trap: ShapeMismatch at extent.ae:3:3 in main: rows(value)==columns(value) [rows(value)=2, columns(value)=3]\n";
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        let (compilation, output) = compile_and_run("extent.ae", source, optimization);
        assert_eq!(output.status.signal(), Some(4));
        assert!(output.stdout.is_empty());
        assert_eq!(output.stderr, expected);
        for phase in [Emit::Hir, Emit::Mir, Emit::Ssa] {
            let dump = &compilation.dumps[&phase];
            assert!(dump.contains("TrapDiagnosticSiteId"), "{phase:?}\n{dump}");
            assert!(dump.contains("rows(value)"), "{phase:?}\n{dump}");
        }
        assert!(compilation.llvm.contains("@aether_report_shape_mismatch"));
        assert!(
            compilation
                .llvm
                .contains("call void @aether_report_shape_mismatch")
        );
        assert!(!compilation.llvm.contains("__cxa_throw"));
    }
}

#[test]
#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
fn arbitrary_guards_use_static_fallback_and_keep_distinct_sites() {
    use std::os::unix::process::ExitStatusExt;

    let source = "int main(){\n  shapeGuard(true);\n  shapeGuard(1+1==3);\n  return 0;\n}";
    let expected = b"Aether trap: ShapeMismatch at fallback.ae:3:3 in main: 1+1==3\n";
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        let (compilation, output) = compile_and_run("fallback.ae", source, optimization);
        assert_eq!(output.status.signal(), Some(4));
        assert_eq!(output.stderr, expected);
        assert!(output.stdout.is_empty());
        assert!(compilation.llvm.contains("aether_shape_site_0_0_prefix"));
        assert!(compilation.llvm.contains("aether_shape_site_0_1_prefix"));
    }
}

#[test]
#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
fn native_matrix_product_reports_its_own_contract_and_extents() {
    use std::os::unix::process::ExitStatusExt;

    let source = "int main(){\n  Matrix<int> left=matrixFilled<int>(2,3,0);\n  Matrix<int> right=matrixFilled<int>(2,1,0);\n  Matrix<int> value=left*right;\n  return 0;\n}";
    let expected = b"Aether trap: ShapeMismatch at product.ae:4:21 in main: columns(left) == rows(right) [columns(left)=3, rows(right)=2]\n";
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        let (_, output) = compile_and_run("product.ae", source, optimization);
        assert_eq!(output.status.signal(), Some(4));
        assert!(output.stdout.is_empty());
        assert_eq!(output.stderr, expected);
    }
}

#[test]
#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
fn linear_algebra_contract_sites_are_exact_in_o0_and_o2() {
    use std::os::unix::process::ExitStatusExt;

    let cases: [(&str, &str, &[u8]); 3] = [
        (
            "solve-not-square",
            "package consumer;import linearAlgebra as la;int main(){Matrix<float64>a=[1.0,2.0];Vector<float64,Column>b=[1.0];Vector<float64,Column>x=la.solve(a,b);return 0;}",
            b"Aether trap: ShapeMismatch at linearAlgebra.ae:448:5 in linearAlgebra.solve: rows(*A) == columns(*A) [rows(*A)=1, columns(*A)=2]\n",
        ),
        (
            "solve-rhs",
            "package consumer;import linearAlgebra as la;int main(){Matrix<float64>a=[1.0,0.0;0.0,1.0];Vector<float64,Column>b=[1.0];Vector<float64,Column>x=la.solve(a,b);return 0;}",
            b"Aether trap: ShapeMismatch at linearAlgebra.ae:449:5 in linearAlgebra.solve: dimension(*b) == rows(*A) [dimension(*b)=1, rows(*A)=2]\n",
        ),
        (
            "dot",
            "package consumer;import linearAlgebra as la;int main(){Array<int>a={1,2};Array<int>b={3};int value=la.dot(a,b);return value;}",
            b"Aether trap: ShapeMismatch at linearAlgebra.ae:48:5 in linearAlgebra.dot: length(*a) == length(*b) [length(*a)=2, length(*b)=1]\n",
        ),
    ];
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        for (label, source, expected) in cases {
            let output = compile_package_and_run(label, source, optimization);
            assert_eq!(output.status.signal(), Some(4), "{label} {optimization:?}");
            assert!(output.stdout.is_empty(), "{label} {optimization:?}");
            assert_eq!(output.stderr, expected, "{label} {optimization:?}");
        }
    }
}
