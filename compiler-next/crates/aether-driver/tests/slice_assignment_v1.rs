//! SLICE-ASSIGNMENT-V1 end-to-end qualification.

use std::{fs, path::PathBuf, process::Command};

use aether_driver::{ClangToolchain, Emit, OptimizationLevel, compile_source_with_optimization};
use aether_frontend::{
    HirSubscriptAxis, HirSubscriptContainerKind, Orientation, SliceAssignmentSnapshot, SourceFile,
    analyze, parse_source,
};
use aether_middle::{
    Rvalue, SliceSelector, SsaOp, TrapKind, build_ssa, lower_hir, verify_mir, verify_ssa,
};

struct Output(PathBuf);

impl Output {
    fn new() -> Self {
        static NEXT: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
        Self(std::env::temp_dir().join(format!(
            "aether-slice-assignment-v1-{}-{}",
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
        &SourceFile::new("slice_assignment_v1.ae", source),
        &[Emit::Hir, Emit::Mir, Emit::Ssa, Emit::Llvm],
        optimization,
    )
    .unwrap_or_else(|errors| panic!("{source}\n{errors:#?}"))
}

fn status(source: &str, optimization: OptimizationLevel) -> std::process::ExitStatus {
    let compilation = compile(source, optimization);
    let output = Output::new();
    ClangToolchain::default()
        .with_optimization(optimization)
        .link_executable(&compilation.llvm, &output.0)
        .unwrap();
    Command::new(&output.0).status().unwrap()
}

const BASIC: &str = r"
int main(){
  Array<int>a={1,2,3,4};Array<int>b={8,9};a[1:2]=b;
  if(a[0]!=1||a[1]!=8||a[2]!=9||a[3]!=4||length(a)!=4){return 1;}
  List<int>l={1,2,3};List<int>m={7,8,9};l[:]=m;
  if(l[0]!=7||l[2]!=9||length(l)!=3||capacity(l)!=3){return 2;}
  Vector<int,Row>v=[1,2,3,4];v[1:3]=v[2:4];
  if(v[1]!=2||v[2]!=3||v[3]!=4||v[4]!=4){return 3;}
  Vector<int,Row>w=[5,6,7];v[2:4]=w;
  if(v[1]!=2||v[2]!=5||v[4]!=7){return 4;}
  Matrix<int>A=[1,2,3;4,5,6;7,8,9];
  Vector<int,Row>row=[10,11,12];A[2,:]=row;
  Vector<int,Column>column=[20,21,22];A[:,1]=column;
  Matrix<int>B=[30,31;32,33];A[1:2,2:3]=B;
  if(A[1,1]!=20||A[1,2]!=30||A[1,3]!=31||A[2,1]!=21||A[2,2]!=32||A[2,3]!=33||A[3,1]!=22){return 5;}
  MatrixView<int>source=A[2:3,:];A[1:2,:]=source;
  if(A[1,1]!=21||A[1,2]!=32||A[2,1]!=22||A[2,2]!=8){return 6;}
  return 0;
}
";

const STRIDED_AND_ZERO: &str = r"
int main(){
  Matrix<int>A=[1,2,3;4,5,6;7,8,9];
  MatrixViewMut<int>T=transpose_view_mut(A);
  Matrix<int>B=[10,11;12,13];T[1:2,2:3]=B;
  if(A[2,1]!=10||A[3,1]!=11||A[2,2]!=12||A[3,2]!=13){return 1;}
  VectorViewMut<int,Column>c=column_mut(A,2);Vector<int,Column>x=[40,41,42];c[:]=x;
  if(A[1,2]!=40||A[2,2]!=41||A[3,2]!=42){return 2;}
  Vector<int,Row>z=[];Vector<int,Row>zr=[];z[:]=zr;
  Matrix<int>z00=matrixFilled<int>(0,0,1);Matrix<int>r00=matrixFilled<int>(0,0,2);z00[:,:]=r00;
  Matrix<int>zm0=matrixFilled<int>(3,0,1);Matrix<int>rm0=matrixFilled<int>(3,0,2);zm0[:,:]=rm0;
  Matrix<int>z0n=matrixFilled<int>(0,3,1);Matrix<int>r0n=matrixFilled<int>(0,3,2);z0n[:,:]=r0n;
  if(rows(zm0)!=3||columns(zm0)!=0||rows(z0n)!=0||columns(z0n)!=3){return 3;}
  return 0;
}
";

const OVERLAP_FULL_AND_PADDED: &str = r"
int main(){
  Matrix<int>A=[1,2,3;4,5,6;7,8,9];A[:,1:2]=A[:,2:3];
  if(A[1,1]!=2||A[1,2]!=3||A[2,1]!=5||A[2,2]!=6||A[3,1]!=8||A[3,2]!=9){return 1;}
  Matrix<int>B=[9,8,7;6,5,4;3,2,1];A[:,:]=B;
  if(A[1,1]!=9||A[2,2]!=5||A[3,3]!=1){return 2;}
  Matrix<int>P=[1,2;3,4;5,6];Vector<int,Column>extra=[7,8,9];P.add(extra);
  Matrix<int>Q=[10,11,12;13,14,15;16,17,18];P[:,:]=Q;
  if(rows(P)!=3||columns(P)!=3||P[1,3]!=12||P[3,1]!=16){return 3;}
  VectorViewMut<int,Column>c=column_mut(P,2);c[1:2]=c[2:3];
  if(P[1,2]!=14||P[2,2]!=17){return 4;}
  return 0;
}
";

const EVALUATION_ONCE: &str = r"
usize mark(ref mut usize p,usize digit,usize value){*p=*p*10+digit;return value;}
Matrix<int> rhs(ref mut usize p){*p=*p*10+3;return [8,9;10,11];}
int main(){
  usize p=0;Matrix<int>A=[1,2,3;4,5,6;7,8,9];
  A[mark(&mut p,1,1):mark(&mut p,2,2),1:2]=rhs(&mut p);
  if(p!=123||A[1,1]!=8||A[1,2]!=9||A[2,1]!=10||A[2,2]!=11){return 1;}
  return 0;
}
";

#[test]
fn assignments_snapshot_and_preserve_shape_at_o0_and_o2() {
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        assert_eq!(status(BASIC, optimization).code(), Some(0));
        assert_eq!(status(STRIDED_AND_ZERO, optimization).code(), Some(0));
        assert_eq!(
            status(OVERLAP_FULL_AND_PADDED, optimization).code(),
            Some(0)
        );
        assert_eq!(status(EVALUATION_ONCE, optimization).code(), Some(0));
    }
}

#[test]
fn ir_exposes_the_verified_transaction() {
    let compilation = compile(BASIC, OptimizationLevel::O0);
    assert!(compilation.dumps[&Emit::Hir].contains("SliceAssign"));
    for phase in [Emit::Mir, Emit::Ssa] {
        let dump = &compilation.dumps[&phase];
        assert!(dump.contains("SliceAssign"));
        assert!(dump.contains("RhsBeforeWrite"));
        assert!(dump.contains("ShapeMismatch"));
        assert!(dump.contains("OrientationMismatch"));
    }
    assert!(compilation.llvm.contains("SliceAssignBegin"));
    assert!(compilation.llvm.contains("SnapshotRhsBeforeWrite"));
}

#[test]
fn invalid_static_contracts_are_rejected() {
    for source in [
        "int main(){Vector<int,Row>a=[1];Vector<int,Column>b=[2];a[:]=b;return 0;}",
        "int main(){Matrix<int>a=[1,2];Vector<int,Column>b=[3,4];a[1,:]=b;return 0;}",
        "int main(){Array<Buffer<int>>a={Buffer<int>(1,1)};Array<Buffer<int>>b={Buffer<int>(1,2)};a[:]=b;return 0;}",
        "int main(){Matrix<int>a=[1];MatrixView<int>v=matrix_view(a);v[:,:]=a;return 0;}",
        "int main(){const Vector<int,Row>a=[1];Vector<int,Row>b=[2];a[:]=b;return 0;}",
    ] {
        assert!(
            compile_source_with_optimization(
                &SourceFile::new("rejected.ae", source),
                &[],
                OptimizationLevel::O0,
            )
            .is_err(),
            "unexpectedly accepted: {source}"
        );
    }
}

#[test]
fn mismatch_traps_before_any_store() {
    let source = r"
int main(){Vector<int,Row>a=[1,2,3];Vector<int,Row>b=[8,9];a[:]=b;return a[1];}
";
    assert_ne!(status(source, OptimizationLevel::O0).code(), Some(0));
}

#[test]
#[allow(clippy::too_many_lines)]
fn mir_and_ssa_reject_corrupt_assignment_contracts() {
    let source = SourceFile::new(
        "corrupt_slice_assignment.ae",
        "int main(){Vector<int,Row>a=[1,2,3];Vector<int,Row>b=[4,5];a[1:2]=b;return 0;}",
    );
    let hir = analyze(parse_source(&source).unwrap()).unwrap();
    let raw = lower_hir(hir);
    for case in 0..8 {
        let mut bad = raw.clone();
        let operation = bad.functions[0]
            .blocks
            .iter_mut()
            .flat_map(|block| &mut block.instructions)
            .find_map(|instruction| match &mut instruction.value {
                Rvalue::SliceAssign {
                    selectors,
                    family,
                    result,
                    snapshot,
                    order_trap,
                    shape_trap,
                    orientation_trap,
                    ..
                } => Some((
                    selectors,
                    family,
                    result,
                    snapshot,
                    order_trap,
                    shape_trap,
                    orientation_trap,
                )),
                _ => None,
            })
            .unwrap();
        match case {
            0 => operation.0.clear(),
            1 => {
                if let SliceSelector::Closed { axis, .. } = &mut operation.0[0] {
                    *axis = HirSubscriptAxis::Row;
                }
            }
            2 => *operation.1 = HirSubscriptContainerKind::List,
            3 => {
                *operation.2 = aether_frontend::HirSubscriptResult::VectorView {
                    orientation: Orientation::Column,
                };
            }
            4 => *operation.3 = SliceAssignmentSnapshot::RhsBeforeWrite,
            5 => *operation.4 = TrapKind::IndexOutOfBounds,
            6 => *operation.5 = TrapKind::SliceBoundsError,
            7 => *operation.6 = TrapKind::ShapeMismatch,
            _ => unreachable!(),
        }
        if case == 4 {
            // The enum intentionally has one valid value; corrupt another required
            // field in this case to exercise the snapshot-adjacent result contract.
            *operation.2 = aether_frontend::HirSubscriptResult::MatrixView;
        }
        assert!(verify_mir(bad).is_err(), "MIR accepted corruption {case}");
    }

    let mir = verify_mir(raw).unwrap();
    let ssa = build_ssa(&mir);
    for case in 0..7 {
        let mut bad = ssa.clone();
        let operation = bad.functions[0]
            .blocks
            .iter_mut()
            .flat_map(|block| &mut block.instructions)
            .find_map(|instruction| match &mut instruction.op {
                SsaOp::SliceAssign {
                    selectors,
                    family,
                    result,
                    order_trap,
                    bounds_trap,
                    index_trap,
                    shape_trap,
                    ..
                } => Some((
                    selectors,
                    family,
                    result,
                    order_trap,
                    bounds_trap,
                    index_trap,
                    shape_trap,
                )),
                _ => None,
            })
            .unwrap();
        match case {
            0 => operation.0.clear(),
            1 => {
                if let SliceSelector::Closed { index_base, .. } = &mut operation.0[0] {
                    *index_base = 0;
                }
            }
            2 => *operation.1 = HirSubscriptContainerKind::Array,
            3 => *operation.2 = aether_frontend::HirSubscriptResult::MatrixView,
            4 => *operation.3 = TrapKind::IndexOutOfBounds,
            5 => *operation.4 = TrapKind::IndexOutOfBounds,
            6 => {
                *operation.5 = TrapKind::SliceBoundsError;
                *operation.6 = TrapKind::SliceBoundsError;
            }
            _ => unreachable!(),
        }
        assert!(verify_ssa(bad).is_err(), "SSA accepted corruption {case}");
    }
}
