//! INTEGER-INDEXING-V1 scalar-only qualification.

use std::{fs, path::PathBuf, process::Command};

use aether_driver::{Emit, OptimizationLevel, compile_source_with_optimization};
use aether_frontend::{SourceFile, analyze, parse_source};
use aether_middle::{
    Operand, PlaceProjection, Rvalue, SsaOp, SsaOperand, SsaPlaceProjection, build_ssa, lower_hir,
    verify_mir, verify_ssa,
};

struct Directory(PathBuf);

impl Directory {
    fn new() -> Self {
        static NEXT: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
        let path = std::env::temp_dir().join(format!(
            "aether-integer-indexing-v1-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, std::sync::atomic::Ordering::Relaxed)
        ));
        fs::create_dir(&path).unwrap();
        Self(path)
    }
}

impl Drop for Directory {
    fn drop(&mut self) {
        fs::remove_dir_all(&self.0).unwrap();
    }
}

fn compile(text: &str, optimization: OptimizationLevel) -> aether_driver::Compilation {
    compile_source_with_optimization(
        &SourceFile::new("integer_indexing_v1.ae", text),
        &[Emit::Hir, Emit::Mir, Emit::Ssa],
        optimization,
    )
    .unwrap_or_else(|errors| panic!("{text}\n{errors:#?}"))
}

fn run(text: &str, optimization: OptimizationLevel) -> std::process::ExitStatus {
    let compilation = compile(text, optimization);
    let directory = Directory::new();
    let ir = directory.0.join("program.ll");
    let executable = directory.0.join("program");
    fs::write(&ir, &compilation.llvm).unwrap();
    let option = match optimization {
        OptimizationLevel::O0 => "-O0",
        OptimizationLevel::O2 => "-O2",
    };
    let linked = Command::new("clang")
        .args(["-Wno-override-module", option, "-x", "ir"])
        .arg(&ir)
        .arg("-o")
        .arg(&executable)
        .arg("-lstdc++")
        .output()
        .unwrap();
    assert!(
        linked.status.success(),
        "{}",
        String::from_utf8_lossy(&linked.stderr)
    );
    Command::new(executable).status().unwrap()
}

fn qualify(text: &str) {
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        assert_eq!(run(text, optimization).code(), Some(0), "{optimization:?}");
    }
}

fn qualify_trap(text: &str) {
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        assert!(
            !run(text, optimization).success(),
            "{optimization:?}: {text}"
        );
    }
}

#[test]
fn every_native_integer_reads_and_writes_without_general_conversion() {
    let source = r"
int main(){
  Array<int>a={0,0,0};
  int8 i8=0;int16 i16=1;int32 i32=2;int64 i64=0;
  uint8 u8=1;uint16 u16=2;uint32 u32=0;uint64 u64=1;
  isize iz=2;usize uz=0;
  a[i8]=11;if(a[i8]!=11){return 1;}
  a[i16]=12;if(a[i16]!=12){return 2;}
  a[i32]=13;if(a[i32]!=13){return 3;}
  a[i64]=14;if(a[i64]!=14){return 4;}
  a[u8]=15;if(a[u8]!=15){return 5;}
  a[u16]=16;if(a[u16]!=16){return 6;}
  a[u32]=17;if(a[u32]!=17){return 7;}
  a[u64]=18;if(a[u64]!=18){return 8;}
  a[iz]=19;if(a[iz]!=19){return 9;}
  a[uz]=20;if(a[uz]!=20){return 10;}
  return 0;
}";
    qualify(source);
    let compilation = compile(source, OptimizationLevel::O0);
    assert!(compilation.llvm.contains("sext i8"));
    assert!(compilation.llvm.contains("zext i16"));
}

#[test]
fn collection_families_views_multidimensional_and_nested_owners_keep_their_domains() {
    qualify(
        r"
int ordered(ref mut int state,int digit,int result){*state=*state*10+digit;return result;}
int main(){
  Array<int>a={1,2,3};List<int>l={4,5,6};Buffer<int>b=Buffer<int>(3,7);
  Vector<int,Row>v=[8,9,10];Matrix<int>m=[11,12;13,14];
  int32 z=0;uint16 one=1;int64 two=2;
  a[z]=21;l[one]=22;b[two]=23;v[one]=24;m[two,one]=25;
  if(a[z]!=21||l[one]!=22||b[two]!=23||v[one]!=24||m[two,one]!=25){return 1;}
  ViewMut<int>av=view_mut(a);av[uint8(2)]=26;
  VectorViewMut<int,Row>vv=vector_view_mut(v);vv[int8(3)]=27;
  MatrixViewMut<int>mv=matrix_view_mut(m);mv[uint32(1),isize(2)]=28;
  if(av[2]!=26||vv[3]!=27||mv[1,2]!=28){return 2;}
  Matrix<Buffer<int>>owners=[Buffer<int>(1,30)];
  owners[int16(1),uint64(1)][int8(0)]=31;
  if(owners[1,1][0]!=31){return 3;}
  int state=0;m[ordered(&mut state,1,1),ordered(&mut state,2,2)]=32;
  if(state!=12||m[1,2]!=32||a[int32(1)+int32(1)]!=26){return 4;}
  return 0;
}",
    );
}

#[test]
fn range_int_binding_indexes_list_directly_and_once() {
    qualify(
        "int main(){List<int> lista={10,20,30};int sum=0;for(int i in 0:2){println(lista[i]);sum=sum+lista[i];}return sum-60;}",
    );
}

#[test]
fn signed_negative_empty_extreme_unsigned_and_arithmetic_overflow_trap() {
    for ty in ["int8", "int16", "int32", "int64", "isize"] {
        qualify_trap(&format!(
            "int main(){{Array<int>a={{1}};{ty} i={ty}(-1);return a[i];}}"
        ));
    }
    for (ty, value) in [
        ("uint8", "255"),
        ("uint16", "65535"),
        ("uint32", "4294967295"),
        ("uint64", "18446744073709551615"),
        ("usize", "18446744073709551615"),
    ] {
        qualify_trap(&format!(
            "int main(){{Array<int>a={{1}};{ty} i={ty}({value});return a[i];}}"
        ));
    }
    qualify_trap("int main(){Array<int>a={};int i=0;return a[i];}");
    qualify_trap(
        "uint8 next(uint8 x){return x+uint8(1);}int main(){Array<int>a={1};uint8 i=next(uint8(255));return a[i];}",
    );
}

#[test]
fn non_integer_scalar_indices_fail_and_slice_rules_do_not_expand() {
    for source in [
        "int main(){Array<int>a={1};bool i=true;return a[i];}",
        "int main(){Array<int>a={1};float64 i=0.0;return a[i];}",
        "int main(){Array<int>a={1};string i=\"0\";return a[i];}",
        "int main(){Array<int>a={1};char i='0';return a[i];}",
    ] {
        let errors = compile_source_with_optimization(
            &SourceFile::new("bad_index.ae", source),
            &[],
            OptimizationLevel::O0,
        )
        .expect_err(source);
        assert_eq!(errors[0].code, "E0480", "{errors:#?}");
    }
    for source in [
        "int main(){Array<int>a={1,2};int i=0;Array<int>b=a[i:1];return 0;}",
        "int main(){Matrix<int>m=[1];int i=1;VectorView<int,Row>v=m[i,:];return 0;}",
    ] {
        assert!(
            compile_source_with_optimization(
                &SourceFile::new("slice_unchanged.ae", source),
                &[],
                OptimizationLevel::O0,
            )
            .is_err(),
            "{source}"
        );
    }
}

#[test]
fn mir_and_ssa_verifiers_reject_non_integer_index_corruption() {
    let source = SourceFile::new(
        "integer_index_corrupt.ae",
        "int main(){Array<int>a={1};int8 i=0;return a[i];}",
    );
    let hir = analyze(parse_source(&source).unwrap()).unwrap();
    let mir = lower_hir(hir);
    let mut bad_mir = mir.clone();
    let mut changed = false;
    for instruction in bad_mir.functions[0]
        .blocks
        .iter_mut()
        .flat_map(|block| &mut block.instructions)
    {
        if let Rvalue::Load(place) = &mut instruction.value {
            for projection in &mut place.projections {
                if let PlaceProjection::Index { index, .. } = projection {
                    *index = Operand::Bool(true);
                    changed = true;
                }
            }
        }
    }
    assert!(changed);
    assert!(verify_mir(bad_mir).is_err());

    let verified_mir = verify_mir(mir).unwrap();
    let ssa = build_ssa(&verified_mir);
    let mut bad_ssa = ssa.clone();
    let mut changed = false;
    for instruction in bad_ssa.functions[0]
        .blocks
        .iter_mut()
        .flat_map(|block| &mut block.instructions)
    {
        if let SsaOp::Load { place } = &mut instruction.op {
            for projection in &mut place.projections {
                if let SsaPlaceProjection::Index { index, .. } = projection {
                    *index = SsaOperand::Bool(true);
                    changed = true;
                }
            }
        }
    }
    assert!(changed);
    assert!(verify_ssa(bad_ssa).is_err());
}
