//! INTEGER-SLICE-BOUNDS-V1 end-to-end and verifier qualification.

use std::{fs, path::PathBuf, process::Command};

use aether_driver::{ClangToolchain, Emit, OptimizationLevel, compile_source_with_optimization};
use aether_frontend::{SourceFile, analyze, parse_source};
use aether_middle::{
    Operand, Rvalue, SliceSelector, SsaOp, SsaOperand, build_ssa, lower_hir, verify_mir, verify_ssa,
};

struct Output(PathBuf);

impl Output {
    fn new() -> Self {
        static NEXT: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
        Self(std::env::temp_dir().join(format!(
            "aether-integer-slice-bounds-v1-{}-{}",
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
        &SourceFile::new("integer_slice_bounds_v1.ae", source),
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

fn qualify(source: &str) {
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        assert_eq!(
            status(source, optimization).code(),
            Some(0),
            "{optimization:?}"
        );
    }
}

fn qualify_trap(source: &str) {
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        assert!(!status(source, optimization).success(), "{optimization:?}");
    }
}

#[test]
fn every_native_integer_and_int_alias_are_valid_closed_endpoints() {
    qualify(
        r"
int main(){
  Array<int>a={10,20,30,40};
  int8 i8=0;int16 i16=1;int32 i32=2;int64 i64=3;int ii=0;
  uint8 u8=1;uint16 u16=2;uint32 u32=3;uint64 u64=0;
  isize iz=1;usize uz=2;
  Array<int>b0=a[i8:i8];Array<int>b1=a[i16:i16];Array<int>b2=a[i32:i32];
  Array<int>b3=a[i64:i64];Array<int>b4=a[ii:ii];Array<int>b5=a[u8:u8];
  Array<int>b6=a[u16:u16];Array<int>b7=a[u32:u32];Array<int>b8=a[u64:u64];
  Array<int>b9=a[iz:iz];Array<int>b10=a[uz:uz];
  if(b0[0]!=10||b1[0]!=20||b2[0]!=30){return 1;}
  if(b3[0]!=40||b4[0]!=10||b5[0]!=20){return 2;}
  if(b6[0]!=30||b7[0]!=40||b8[0]!=10){return 3;}
  if(b9[0]!=20||b10[0]!=30){return 4;}
  return 0;
}
",
    );
}

#[test]
fn heterogeneous_read_assignment_views_and_mixed_scalars_preserve_contracts() {
    qualify(
        r"
int8 mark8(ref mut int p,int digit,int8 value){*p=*p*10+digit;return value;}
uint16 mark16(ref mut int p,int digit,uint16 value){*p=*p*10+digit;return value;}
int main(){
  int order=0;Array<int>a={1,2,3,4};
  Array<int>b=a[mark8(&mut order,1,1):mark16(&mut order,2,2)];
  if(order!=12||length(b)!=2||b[0]!=2||b[1]!=3){return 1;}
  int8 lo=1;uint64 hi=2;Array<int>rhs={8,9};a[lo:hi]=rhs;
  if(a[1]!=8||a[2]!=9){return 2;}
  Vector<int,Row>v=[4,5,6];VectorView<int,Row>vv=v[uint8(1):int16(2)];
  if(dimension(vv)!=2||vv[2]!=5){return 3;}
  Matrix<int>m=[1,2,3;4,5,6;7,8,9];
  int8 row=2;uint16 first=1;int64 last=2;
  VectorView<int,Row>r=m[row,first:last];
  VectorView<int,Column>c=m[uint8(1):uint16(2),uint32(3)];
  MatrixView<int>block=m[uint8(2):int16(3),int32(1):uint64(2)];
  if(r[1]!=4||r[2]!=5||c[2]!=6||block[2,2]!=8){return 4;}
  return 0;
}
",
    );
}

#[test]
fn mathematical_order_precedes_bounds_and_large_unsigned_never_wraps() {
    for source in [
        "int main(){Array<int>a={1,2};int8 x=1;int8 y=-1;Array<int>b=a[x:y];return 0;}",
        "int main(){Array<int>a={1,2};int8 x=-2;int8 y=-1;Array<int>b=a[x:y];return 0;}",
        "int main(){Array<int>a={1,2,3};uint8 x=3;uint8 y=2;Array<int>b=a[x:y];return 0;}",
        "int main(){Array<int>a={1};uint64 x=uint64(18446744073709551615);Array<int>b=a[x:x];return 0;}",
        "int main(){Matrix<int>a=[1];int8 x=-1;VectorView<int,Row>b=a[x,:];return 0;}",
    ] {
        qualify_trap(source);
    }
    qualify(
        "int main(){Array<int>a={7,8,9,10};uint8 x=3;int64 y=3;Array<int>b=a[x:y];return int(length(b))-1;}",
    );

    let llvm = compile(
        "int main(){Array<int>a={1,2};int8 x=0;uint64 y=1;Array<int>b=a[x:y];return 0;}",
        OptimizationLevel::O0,
    )
    .llvm;
    assert!(llvm.contains("sext i8"));
    assert!(llvm.contains("zext i64"));
    assert!(llvm.contains("icmp sle i65"));
    assert!(llvm.find("_ordered =").unwrap() < llvm.find("_first_lower =").unwrap());
}

#[test]
fn non_integer_endpoints_and_mixed_scalars_remain_rejected() {
    for source in [
        "int main(){Array<int>a={1};Array<int>b=a[float32(0.0):0];return 0;}",
        "int main(){Array<int>a={1};Array<int>b=a[false:true];return 0;}",
        "int main(){Array<int>a={1};Array<int>b=a['a':'b'];return 0;}",
        "int main(){Array<int>a={1};Array<int>b=a[\"a\":\"b\"];return 0;}",
        "int main(){Matrix<int>a=[1];float32 x=1.0;VectorView<int,Row>b=a[x,:];return 0;}",
        "int main(){Array<int>a={1,2,3,4};Array<int>b=a[3:2];return 0;}",
        "int main(){Array<int>a={1,2,3,4};Array<int>b=a[int8(3):uint16(2)];return 0;}",
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
fn hir_mir_and_ssa_reject_non_integer_selector_corruption() {
    let source = SourceFile::new(
        "integer_slice_corrupt.ae",
        "int main(){Array<int>a={1,2};int8 x=0;uint16 y=1;Array<int>b=a[x:y];return b[0]-1;}",
    );
    let hir = analyze(parse_source(&source).unwrap()).unwrap();
    let raw = lower_hir(hir);
    let mut bad_mir = raw.clone();
    let selector = bad_mir.functions[0]
        .blocks
        .iter_mut()
        .flat_map(|block| &mut block.instructions)
        .find_map(|instruction| match &mut instruction.value {
            Rvalue::CollectionSliceCopy { selector, .. } => Some(selector),
            _ => None,
        })
        .unwrap();
    if let SliceSelector::Closed { first, .. } = selector {
        *first = Operand::Bool(true);
    }
    assert!(verify_mir(bad_mir).is_err());

    let verified = verify_mir(raw).unwrap();
    let mut bad_ssa = build_ssa(&verified);
    let selector = bad_ssa.functions[0]
        .blocks
        .iter_mut()
        .flat_map(|block| &mut block.instructions)
        .find_map(|instruction| match &mut instruction.op {
            SsaOp::CollectionSliceCopy { selector, .. } => Some(selector),
            _ => None,
        })
        .unwrap();
    if let SliceSelector::Closed { last, .. } = selector {
        *last = SsaOperand::Bool(false);
    }
    assert!(verify_ssa(bad_ssa).is_err());
}
