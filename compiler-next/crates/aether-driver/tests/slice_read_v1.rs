//! SLICE-READ-V1 end-to-end qualification.

use std::{fs, path::PathBuf, process::Command};

use aether_driver::{ClangToolchain, Emit, OptimizationLevel, compile_source_with_optimization};
use aether_frontend::{
    HirSubscriptAxis, HirSubscriptContainerKind, Orientation, SourceFile, VectorViewField, analyze,
    parse_source,
};
use aether_middle::{
    Rvalue, SliceSelector, SsaOp, TrapKind, build_ssa, lower_hir, verify_mir, verify_ssa,
};

struct Output(PathBuf);

impl Output {
    fn new(label: &str) -> Self {
        static NEXT: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
        Self(std::env::temp_dir().join(format!(
            "aether-slice-read-v1-{label}-{}-{}",
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
        &SourceFile::new("slice_read_v1.ae", source),
        &[Emit::Hir, Emit::Mir, Emit::Ssa, Emit::Llvm],
        optimization,
    )
    .unwrap_or_else(|errors| panic!("{source}\n{errors:#?}"))
}

fn status(source: &str, optimization: OptimizationLevel) -> std::process::ExitStatus {
    let compilation = compile(source, optimization);
    let output = Output::new("native");
    ClangToolchain::default()
        .with_optimization(optimization)
        .link_executable(&compilation.llvm, &output.0)
        .unwrap();
    Command::new(&output.0).status().unwrap()
}

const COLLECTIONS: &str = r"
int main(){
  Array<int> a={10,20,30,40};
  Array<int> b=a[1:2];
  Array<int> all=a[:];
  b[0]=99;
  if(length(b)!=2||b[1]!=30||a[1]!=20||length(all)!=4){return 1;}
  List<int> l={1,2,3,4};
  List<int> m=l[1:3];
  List<int> whole=l[:];
  m[0]=88;
  if(length(m)!=3||capacity(m)!=3||m[2]!=4||l[1]!=2){return 2;}
  if(length(whole)!=4||capacity(whole)!=4){return 3;}
  Array<int> empty={};Array<int> emptyCopy=empty[:];
  List<int> emptyList={};List<int> emptyListCopy=emptyList[:];
  if(length(emptyCopy)!=0||length(emptyListCopy)!=0||capacity(emptyListCopy)!=0){return 4;}
  return 0;
}
";

const MATHEMATICAL: &str = r"
int main(){
  Vector<int,Row> r=[10,20,30,40];
  VectorView<int,Row> rs=r[2:4];
  VectorView<int,Row> rf=r[:];
  if(dimension(rs)!=3||rs[1]!=20||rs[3]!=40||rf[4]!=40){return 1;}
  Vector<int,Column> c=[1,2,3];
  VectorView<int,Column> cs=c[1:1];
  if(dimension(cs)!=1||cs[1]!=1){return 2;}
  Vector<int,Row> mutableSource=[5,6,7];
  VectorViewMut<int,Row> mutableView=vector_view_mut(mutableSource);
  VectorView<int,Row> sharedFromMutable=mutableView[2:3];
  if(sharedFromMutable[1]!=6||sharedFromMutable[2]!=7){return 6;}

  Matrix<int> a=[1,2;3,4];
  Vector<int,Column> extra=[5,6];a.add(extra);
  VectorView<int,Row> rowSlice=a[2,:];
  VectorView<int,Column> columnSlice=a[:,3];
  MatrixView<int> oneRow=a[1:1,:];
  MatrixView<int> oneColumn=a[:,2:2];
  MatrixView<int> block=a[1:2,2:3];
  MatrixView<int> full=a[:,:];
  if(rowSlice[3]!=6||columnSlice[1]!=5||rows(oneRow)!=1||columns(oneRow)!=3){return 3;}
  if(rows(oneColumn)!=2||columns(oneColumn)!=1||block[2,2]!=6||full[2,3]!=6){return 4;}

  MatrixView<int> transposed=transpose_view(a);
  MatrixView<int> sub=transposed[2:3,1:2];
  MatrixView<int> chained=sub[:,:];
  VectorView<int,Column> strided=a[:,2];
  VectorView<int,Column> stridedSlice=strided[1:2];
  if(chained[1,2]!=4||chained[2,2]!=6||stridedSlice[2]!=4){return 5;}
  Matrix<int> writableMatrix=[8,9];
  MatrixViewMut<int> writableView=matrix_view_mut(writableMatrix);
  MatrixView<int> sharedMatrixSlice=writableView[:,:];
  if(sharedMatrixSlice[1,2]!=9){return 7;}
  return 0;
}
";

const ZERO_SHAPES: &str = r"
int main(){
  Vector<int,Row> z=[];VectorView<int,Row> zv=z[:];
  Matrix<int> z00=matrixFilled<int>(0,0,7);
  Matrix<int> zm0=matrixFilled<int>(3,0,7);
  Matrix<int> z0n=matrixFilled<int>(0,4,7);
  MatrixView<int> a=z00[:,:];MatrixView<int> b=zm0[:,:];MatrixView<int> c=z0n[:,:];
  VectorView<int,Row> emptyRow=zm0[2,:];
  VectorView<int,Column> emptyColumn=z0n[:,3];
  if(dimension(zv)!=0||rows(a)!=0||columns(a)!=0){return 1;}
  if(rows(b)!=3||columns(b)!=0||rows(c)!=0||columns(c)!=4){return 2;}
  if(dimension(emptyRow)!=0||dimension(emptyColumn)!=0){return 3;}
  return 0;
}
";

#[test]
fn owning_and_mathematical_slices_run_at_o0_and_o2() {
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        assert_eq!(status(COLLECTIONS, optimization).code(), Some(0));
        assert_eq!(status(MATHEMATICAL, optimization).code(), Some(0));
        assert_eq!(status(ZERO_SHAPES, optimization).code(), Some(0));
    }
}

#[test]
fn ir_keeps_explicit_slice_operations_and_structured_traps() {
    let compilation = compile(MATHEMATICAL, OptimizationLevel::O0);
    assert!(compilation.dumps[&Emit::Hir].contains("SliceRead"));
    for phase in [Emit::Mir, Emit::Ssa] {
        let dump = &compilation.dumps[&phase];
        assert!(dump.contains("VectorSliceView"));
        assert!(dump.contains("MatrixSliceView"));
        assert!(dump.contains("SliceOrderError"));
        assert!(dump.contains("SliceBoundsError"));
    }
    assert!(compilation.llvm.contains("VectorSliceViewBegin"));
    assert!(compilation.llvm.contains("MatrixSliceViewBegin"));
}

#[test]
fn order_bounds_evaluation_once_copy_and_assignment_boundaries_are_enforced() {
    let eval = r"
usize next(ref mut usize p){usize value=*p;*p=value+1;return value;}
int main(){usize i=0;Array<int>a={7,8,9};Array<int>b=a[next(&mut i):next(&mut i)];return int(i)+b[0]+b[1]-17;}
";
    assert_eq!(status(eval, OptimizationLevel::O0).code(), Some(0));

    for source in [
        "int main(){Array<Buffer<int>>a={Buffer<int>(1,1)};Array<Buffer<int>>b=a[:];return 0;}",
        "Array<T> bad<T:Storable>(Array<T>a){return a[:];}int main(){return 0;}",
        "int main(){Array<int>a={1,2};a[0:1]={3,4};return 0;}",
        "VectorView<int,Row> bad(){Vector<int,Row>a=[1,2];return a[:];}int main(){return 0;}",
        "int eat(Vector<int,Row>a){return 0;}int main(){Vector<int,Row>a=[1];VectorView<int,Row>v=a[:];return eat(a);}",
        "int main(){Matrix<int>a=[1];Vector<int,Row>r=[2];MatrixView<int>v=a[:,:];a.add(r);return 0;}",
    ] {
        assert!(
            compile_source_with_optimization(
                &SourceFile::new("rejected.ae", source),
                &[],
                OptimizationLevel::O0,
            )
            .is_err()
        );
    }

    for source in [
        "int main(){Array<int>a={1,2};usize x=1;usize y=0;Array<int>b=a[x:y];return 0;}",
        "int main(){List<int>a={1,2};usize x=0;usize y=2;List<int>b=a[x:y];return 0;}",
        "int main(){Vector<int,Row>a=[1,2];usize x=0;VectorView<int,Row>b=a[x:1];return 0;}",
        "int main(){Matrix<int>a=[1];usize x=2;VectorView<int,Row>b=a[x,:];return 0;}",
        "int main(){Matrix<int>a=[1];usize x=2;usize y=1;MatrixView<int>b=a[x:y,:];return 0;}",
        "int main(){Matrix<int>a=[1];usize x=1;usize y=2;MatrixView<int>b=a[x:y,:];return 0;}",
        "int main(){Matrix<int>a=matrixFilled<int>(0,3,1);usize x=1;VectorView<int,Row>b=a[x,:];return 0;}",
        "int main(){Matrix<int>a=matrixFilled<int>(3,0,1);usize x=1;VectorView<int,Column>b=a[:,x];return 0;}",
    ] {
        assert!(!status(source, OptimizationLevel::O0).success(), "{source}");
    }
}

#[test]
#[allow(clippy::too_many_lines)]
fn hir_mir_and_ssa_reject_corrupt_slice_contracts() {
    let source = SourceFile::new(
        "corrupt_slice.ae",
        "int main(){Vector<int,Row>a=[1,2,3];VectorView<int,Row>b=a[1:2];return b[1]-1;}",
    );
    let hir = analyze(parse_source(&source).unwrap()).unwrap();
    let raw = lower_hir(hir);
    for case in 0..6 {
        let mut bad = raw.clone();
        let (selector, family, orientation, descriptor, order_trap, bounds_trap) = bad.functions[0]
            .blocks
            .iter_mut()
            .flat_map(|block| &mut block.instructions)
            .find_map(|instruction| match &mut instruction.value {
                Rvalue::VectorSliceView {
                    selector,
                    family,
                    orientation,
                    descriptor,
                    order_trap,
                    bounds_trap,
                    ..
                } => Some((
                    selector,
                    family,
                    orientation,
                    descriptor,
                    order_trap,
                    bounds_trap,
                )),
                _ => None,
            })
            .unwrap();
        match case {
            0 => {
                if let SliceSelector::Closed { index_base, .. } = selector {
                    *index_base = 0;
                }
            }
            1 => *family = HirSubscriptContainerKind::List,
            2 => *orientation = Orientation::Column,
            3 => descriptor.stride = VectorViewField::Dimension,
            4 => *order_trap = TrapKind::IndexOutOfBounds,
            5 => *bounds_trap = TrapKind::IndexOutOfBounds,
            _ => unreachable!(),
        }
        assert!(verify_mir(bad).is_err(), "MIR accepted corruption {case}");
    }

    let mir = verify_mir(raw).unwrap();
    let ssa = build_ssa(&mir);
    for case in 0..6 {
        let mut bad = ssa.clone();
        let (selector, family, orientation, descriptor, order_trap, bounds_trap) = bad.functions[0]
            .blocks
            .iter_mut()
            .flat_map(|block| &mut block.instructions)
            .find_map(|instruction| match &mut instruction.op {
                SsaOp::VectorSliceView {
                    selector,
                    family,
                    orientation,
                    descriptor,
                    order_trap,
                    bounds_trap,
                    ..
                } => Some((
                    selector,
                    family,
                    orientation,
                    descriptor,
                    order_trap,
                    bounds_trap,
                )),
                _ => None,
            })
            .unwrap();
        match case {
            0 => {
                if let SliceSelector::Closed { axis, .. } = selector {
                    *axis = HirSubscriptAxis::Row;
                }
            }
            1 => *family = HirSubscriptContainerKind::Array,
            2 => *orientation = Orientation::Column,
            3 => descriptor.stride = VectorViewField::Dimension,
            4 => *order_trap = TrapKind::IndexOutOfBounds,
            5 => *bounds_trap = TrapKind::IndexOutOfBounds,
            _ => unreachable!(),
        }
        assert!(verify_ssa(bad).is_err(), "SSA accepted corruption {case}");
    }

    let matrix_source = SourceFile::new(
        "corrupt_matrix_slice.ae",
        "int main(){Matrix<int>a=[1,2;3,4];VectorView<int,Row>b=a[1,:];return b[1];}",
    );
    let matrix_hir = analyze(parse_source(&matrix_source).unwrap()).unwrap();
    let matrix_raw = lower_hir(matrix_hir);
    let mut bad_matrix_mir = matrix_raw.clone();
    let operation = bad_matrix_mir.functions[0]
        .blocks
        .iter_mut()
        .flat_map(|block| &mut block.instructions)
        .find_map(|instruction| match &mut instruction.value {
            Rvalue::MatrixSliceView { index_trap, .. } => Some(index_trap),
            _ => None,
        })
        .unwrap();
    *operation = TrapKind::SliceBoundsError;
    assert!(verify_mir(bad_matrix_mir).is_err());

    let verified_matrix_flow = verify_mir(matrix_raw).unwrap();
    let mut bad_matrix_ssa = build_ssa(&verified_matrix_flow);
    let operation = bad_matrix_ssa.functions[0]
        .blocks
        .iter_mut()
        .flat_map(|block| &mut block.instructions)
        .find_map(|instruction| match &mut instruction.op {
            SsaOp::MatrixSliceView { descriptor, .. } => Some(descriptor),
            _ => None,
        })
        .unwrap();
    operation.row_stride = aether_frontend::MatrixViewField::Rows;
    assert!(verify_ssa(bad_matrix_ssa).is_err());
}
