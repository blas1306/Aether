//! MATRIX-ADD-V1 cross-layer and native qualification.

use std::{fs, path::PathBuf, process::Command};

use aether_driver::{
    ClangToolchain, Emit, OptimizationLevel, compile_source, compile_source_with_optimization,
};
use aether_frontend::{SourceFile, analyze, parse_source};
use aether_middle::{Rvalue, SsaOp, build_ssa, lower_hir, verify_mir, verify_ssa};

struct Output(PathBuf);

impl Output {
    fn new(label: &str) -> Self {
        static NEXT: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
        Self(std::env::temp_dir().join(format!(
            "aether-matrix-add-v1-{label}-{}-{}",
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
        &SourceFile::new("matrix_add_v1.ae", source),
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
        .unwrap_or_else(|error| panic!("{error:#?}\n{}", compilation.llvm));
    Command::new(&output.0)
        .status()
        .unwrap()
        .code()
        .unwrap_or(-1)
}

fn process_status(source: &str) -> std::process::ExitStatus {
    let compilation = compile(source, OptimizationLevel::O0);
    let output = Output::new("trap");
    ClangToolchain::default()
        .link_executable(&compilation.llvm, &output.0)
        .unwrap();
    Command::new(&output.0).status().unwrap()
}

const GROWTH: &str = r"
int main(){
  Matrix<int> a=[];
  Vector<int,Row> r0=[1,2,3];
  a.add(r0);
  Vector<int,Row> r1=[4,5,6];
  a.add(r1);
  Vector<int,Column> c0=[7,8];
  a.add(c0);
  Vector<int,Column> c1=[9,10];
  a.add(c1);
  Vector<int,Row> r2=[11,12,13,14,15];
  a.add(r2);
  if(rows(a)!=3||columns(a)!=5){return 1;}
  if(a[1,1]!=1){return 11;}if(a[1,4]!=7){return 12;}if(a[1,5]!=9){return 13;}
  if(a[2,4]!=8){return 14;}if(a[2,5]!=10){return 15;}if(a[3,1]!=11){return 16;}if(a[3,5]!=15){return 17;}
  return 0;
}
";

#[test]
fn row_column_alternation_and_geometric_growth_work_at_o0_o2() {
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        assert_eq!(status(GROWTH, optimization), 0);
    }
    let compilation = compile(GROWTH, OptimizationLevel::O0);
    for phase in [Emit::Hir, Emit::Mir, Emit::Ssa] {
        assert!(compilation.dumps[&phase].contains("MatrixAdd"));
    }
    assert!(compilation.llvm.contains("@aether_matrix_add_row_"));
    assert!(compilation.llvm.contains("@aether_matrix_add_column_"));
    assert!(compilation.llvm.contains("MatrixAdd consumes Vector"));
    assert!(compilation.llvm.contains("%row_doubled"));
    assert!(compilation.llvm.contains("%column_doubled"));
}

#[test]
fn all_zero_axis_cases_keep_both_extents() {
    let source = r"
int main(){
  Matrix<int> rowFirst=[];Vector<int,Row> rn=[1,2];rowFirst.add(rn);
  Matrix<int> columnFirst=[];Vector<int,Column> cm=[3,4,5];columnFirst.add(cm);
  Matrix<int> rowEmpty=[];Vector<int,Row> re=[];rowEmpty.add(re);
  Matrix<int> columnEmpty=[];Vector<int,Column> ce=[];columnEmpty.add(ce);
  Matrix<int> m0=matrixFilled<int>(2,0,0);Vector<int,Row> mre=[];m0.add(mre);Vector<int,Column> mc=[6,7,8];m0.add(mc);
  Matrix<int> n0=matrixFilled<int>(0,2,0);Vector<int,Column> nce=[];n0.add(nce);Vector<int,Row> nr=[9,10,11];n0.add(nr);
  if(rows(rowFirst)!=1||columns(rowFirst)!=2||rowFirst[1,2]!=2){return 1;}
  if(rows(columnFirst)!=3||columns(columnFirst)!=1||columnFirst[3,1]!=5){return 2;}
  if(rows(rowEmpty)!=1||columns(rowEmpty)!=0){return 3;}
  if(rows(columnEmpty)!=0||columns(columnEmpty)!=1){return 4;}
  if(rows(m0)!=3||columns(m0)!=1||m0[3,1]!=8){return 5;}
  if(rows(n0)!=1||columns(n0)!=3||n0[1,3]!=11){return 6;}
  return 0;
}";
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        assert_eq!(status(source, optimization), 0);
    }
}

#[test]
fn float_fields_returns_and_nontrivial_relocatable_elements_work() {
    let floats = "struct Box{Matrix<float64> value;}Vector<float64,Row>makeRow(){Vector<float64,Row>r=[1.5,2.5];return r;}int extend(ref mut Matrix<float64>a){Vector<float64,Column>c=[3.5];(*a).add(c);return 0;}Box make(){Matrix<float64>a=[];a.add(makeRow());return Box(a);}int main(){Box b=make();int ignored=extend(&mut b.value);if(b.value[1,3]!=3.5){return 1;}return 0;}";
    let owners = "int main(){Matrix<Buffer<int>>a=[];Vector<Buffer<int>,Row>r=[Buffer<int>(1,7)];a.add(r);Vector<Buffer<int>,Row>s=[Buffer<int>(1,9)];a.add(s);if(a[1,1][0]!=7||a[2,1][0]!=9){return 1;}return 0;}";
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        assert_eq!(status(floats, optimization), 0);
        assert_eq!(status(owners, optimization), 0);
    }
}

#[test]
fn exact_owner_type_relocatable_bound_consumption_and_live_borrows_are_enforced() {
    let rejected = [
        "int main(){Matrix<int>a=[];Vector<int,Row>r=[1];a.add(r);return r[1];}",
        "int main(){Matrix<int>a=[1];Vector<int,Row>r=[2];MatrixView<int>v=matrix_view(a);a.add(r);return v[1,1];}",
        "int main(){Matrix<int>a=[1];Vector<int,Row>r=[2];ref int x=&a[1,1];a.add(r);return *x;}",
        "int main(){Matrix<int>a=[];Matrix<int>b=[];a.add(b);return 0;}",
        "int main(){Matrix<int>a=[];Vector<int,Row>r=[];VectorView<int,Row>v=vector_view(r);a.add(v);return 0;}",
        "int main(){Matrix<int>a=[];Vector<float64,Row>r=[];a.add(r);return 0;}",
        "int main(){const Matrix<int>a=[];Vector<int,Row>r=[];a.add(r);return 0;}",
        "int f<T:Storable>(Matrix<T>a,Vector<T,Row>r){a.add(r);return 0;}int main(){return 0;}",
    ];
    for source in rejected {
        assert!(
            compile_source(&SourceFile::new("bad_matrix_add.ae", source), &[]).is_err(),
            "unexpectedly accepted: {source}"
        );
    }
}

#[test]
fn shape_mismatch_traps_before_any_matrix_add_allocation() {
    let source = "int main(){Matrix<int>a=[1,2];Vector<int,Row>r=[3];a.add(r);return 0;}";
    assert!(!process_status(source).success());
    let llvm = compile(source, OptimizationLevel::O0).llvm;
    let shape = llvm.find("trap_shape_mismatch:").unwrap();
    let allocation = llvm.find("%fresh = call").unwrap();
    assert!(shape < allocation);
}

#[test]
fn malformed_mir_and_ssa_matrix_add_are_rejected() {
    let source = SourceFile::new(
        "corrupt_matrix_add.ae",
        "int main(){Matrix<int>a=[];Vector<int,Row>r=[1];a.add(r);return a[1,1]-1;}",
    );
    let hir = analyze(parse_source(&source).unwrap()).unwrap();
    let raw = lower_hir(hir);
    let mut bad_mir = raw.clone();
    let operation = bad_mir.functions[0]
        .blocks
        .iter_mut()
        .flat_map(|block| &mut block.instructions)
        .find_map(|instruction| match &mut instruction.value {
            Rvalue::MatrixAdd { shape_trap, .. } => Some(shape_trap),
            _ => None,
        })
        .unwrap();
    *operation = aether_middle::TrapKind::IndexOutOfBounds;
    assert!(verify_mir(bad_mir).is_err());

    let mir = verify_mir(raw).unwrap();
    let mut ssa = build_ssa(&mir);
    let operation = ssa.functions[0]
        .blocks
        .iter_mut()
        .flat_map(|block| &mut block.instructions)
        .find_map(|instruction| match &mut instruction.op {
            SsaOp::MatrixAdd { orientation, .. } => Some(orientation),
            _ => None,
        })
        .unwrap();
    *operation = aether_frontend::Orientation::Column;
    assert!(verify_ssa(ssa).is_err());
}
