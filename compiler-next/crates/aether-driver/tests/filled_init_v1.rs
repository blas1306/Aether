//! FILLED-INIT-V1 cross-layer, native and package qualification.

use std::{fs, path::PathBuf, process::Command};

use aether_driver::{
    ClangToolchain, Emit, OptimizationLevel, build_path, compile_source,
    compile_source_with_optimization,
};
use aether_frontend::{SourceFile, analyze, parse_source};
use aether_middle::{Rvalue, SsaOp, build_ssa, lower_hir, verify_mir, verify_ssa};

struct Output(PathBuf);

impl Output {
    fn new(label: &str) -> Self {
        static NEXT: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
        Self(std::env::temp_dir().join(format!(
            "aether-filled-init-v1-{label}-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, std::sync::atomic::Ordering::Relaxed)
        )))
    }
}

impl Drop for Output {
    fn drop(&mut self) {
        let _ = fs::remove_file(&self.0);
    }
}

fn compile(source: &str, optimization: OptimizationLevel) -> aether_driver::Compilation {
    compile_source_with_optimization(
        &SourceFile::new("filled_init_v1.ae", source),
        &[Emit::Hir, Emit::Mir, Emit::Ssa, Emit::Llvm],
        optimization,
    )
    .unwrap_or_else(|errors| panic!("{source}\n{errors:#?}"))
}

fn status(source: &str, optimization: OptimizationLevel) -> i32 {
    let compilation = compile(source, optimization);
    let output = Output::new("native");
    ClangToolchain::default()
        .with_optimization(optimization)
        .link_executable(&compilation.llvm, &output.0)
        .unwrap();
    Command::new(&output.0)
        .status()
        .unwrap()
        .code()
        .unwrap_or(-1)
}

fn process_status(source: &str, optimization: OptimizationLevel) -> std::process::ExitStatus {
    let compilation = compile(source, optimization);
    let output = Output::new("trap");
    ClangToolchain::default()
        .with_optimization(optimization)
        .link_executable(&compilation.llvm, &output.0)
        .unwrap();
    Command::new(&output.0).status().unwrap()
}

const SOURCE: &str = r"
struct Pair{int x;int y;}
struct Owners{Matrix<int> matrix;Vector<int,Row> row;}
Owners make(usize m,usize n){return Owners(matrixFilled<int>(m,n,7),vectorFilled<int,Row>(n,9));}
int main(){
  Owners x=make(2,3);
  Vector<int,Column> c=vectorFilled<int,Column>(2,11);
  Matrix<Pair> p=matrixFilled<Pair>(3,1,Pair(4,5));
  Matrix<int> wide=matrixFilled<int>(1,4,6);
  Matrix<int> z00=matrixFilled<int>(0,0,1);
  Matrix<int> zm0=matrixFilled<int>(3,0,1);
  Matrix<int> z0n=matrixFilled<int>(0,4,1);
  MatrixView<int> v=matrix_view(x.matrix);
  if(rows(x.matrix)!=2||columns(x.matrix)!=3||x.matrix[2,3]!=7){return 1;}
  if(x.row[3]!=9||c[2]!=11||p[3,1].y!=5||wide[1,4]!=6){return 2;}
  if(v[1,2]!=7){return 3;}
  if(rows(z00)!=0||columns(z00)!=0){return 4;}
  if(rows(zm0)!=3||columns(zm0)!=0){return 5;}
  if(rows(z0n)!=0||columns(z0n)!=4){return 6;}
  return 0;
}
";

#[test]
fn runtime_shapes_values_views_moves_fields_and_zero_axes_work_at_o0_o2() {
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        assert_eq!(status(SOURCE, optimization), 0);
    }
    let compilation = compile(SOURCE, OptimizationLevel::O0);
    for phase in [Emit::Hir, Emit::Mir, Emit::Ssa] {
        assert!(compilation.dumps[&phase].contains("VectorFilled"));
        assert!(compilation.dumps[&phase].contains("MatrixFilled"));
    }
    assert!(compilation.llvm.contains("@aether_matrix_fill_"));
    assert!(compilation.llvm.contains("%column_capacity"));
}

#[test]
fn scalar_types_and_ordinary_package_are_supported() {
    for ty in ["int", "float32", "float64"] {
        let source = format!(
            "int main(){{Matrix<{ty}> a=matrixFilled<{ty}>(2,3,4);Vector<{ty},Row> r=vectorFilled<{ty},Row>(3,5);Vector<{ty},Column> c=vectorFilled<{ty},Column>(2,6);if(a[2,3]!=4||r[3]!=5||c[2]!=6){{return 1;}}return 0;}}"
        );
        assert_eq!(status(&source, OptimizationLevel::O0), 0, "{ty}");
    }
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../..");
    let output = Output::new("package");
    let compilation = build_path(
        &root.join("tests/modules/filled_init_v1/main.ae"),
        &output.0,
        &[Emit::Hir, Emit::Mir, Emit::Ssa],
        &ClangToolchain::default(),
    )
    .unwrap();
    assert_eq!(Command::new(&output.0).status().unwrap().code(), Some(0));
    assert!(compilation.dumps[&Emit::Hir].contains("MatrixFilled"));
}

#[test]
fn non_copy_and_static_overflow_are_rejected() {
    for source in [
        "int main(){Matrix<Buffer<int>> a=matrixFilled<Buffer<int>>(1,1,Buffer<int>(1,0));return 0;}",
        "int main(){Vector<Buffer<int>,Row> a=vectorFilled<Buffer<int>,Row>(1,Buffer<int>(1,0));return 0;}",
    ] {
        let errors = compile_source(&SourceFile::new("bad.ae", source), &[]).unwrap_err();
        assert!(
            errors
                .iter()
                .any(|error| error.message.contains("Storable + Copy"))
        );
    }
    let errors = compile_source(
        &SourceFile::new(
            "overflow.ae",
            "int main(){Matrix<int> a=matrixFilled<int>(18446744073709551615,2,0);return 0;}",
        ),
        &[],
    )
    .unwrap_err();
    assert!(
        errors
            .iter()
            .any(|error| error.message.contains("AllocationSizeOverflow"))
    );

    let dynamic = "usize huge(){return 18446744073709551615;}int main(){Matrix<int> a=matrixFilled<int>(huge(),2,0);return 0;}";
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        assert!(!process_status(dynamic, optimization).success());
    }
}

#[test]
fn malformed_hir_mir_and_ssa_are_rejected() {
    let source = SourceFile::new(
        "corrupt.ae",
        "int main(){Matrix<int> a=matrixFilled<int>(2,3,7);return a[2,3]-7;}",
    );
    let hir = analyze(parse_source(&source).unwrap()).unwrap();
    let raw = lower_hir(hir);
    let mut bad_mir = raw.clone();
    let operation = bad_mir.functions[0]
        .blocks
        .iter_mut()
        .flat_map(|block| &mut block.instructions)
        .find_map(|instruction| match &mut instruction.value {
            Rvalue::MatrixFilled { row_capacity, .. } => Some(row_capacity),
            _ => None,
        })
        .unwrap();
    *operation = aether_middle::Operand::Bool(false);
    assert!(verify_mir(bad_mir).is_err());

    let mir = verify_mir(raw).unwrap();
    let mut ssa = build_ssa(&mir);
    let operation = ssa.functions[0]
        .blocks
        .iter_mut()
        .flat_map(|block| &mut block.instructions)
        .find_map(|instruction| match &mut instruction.op {
            SsaOp::MatrixFilled {
                column_capacity, ..
            } => Some(column_capacity),
            _ => None,
        })
        .unwrap();
    *operation = aether_middle::SsaOperand::Bool(false);
    assert!(verify_ssa(ssa).is_err());
}
