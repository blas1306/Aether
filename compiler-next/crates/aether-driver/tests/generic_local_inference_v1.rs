//! GENERIC-LOCAL-INFERENCE-V1 closed vertical qualification.

use std::{fs, path::PathBuf, process::Command};

use aether_driver::{
    ClangToolchain, CompilationSession, Emit, OptimizationLevel, compile_session, compile_source,
    compile_source_with_optimization,
};
use aether_frontend::{SourceFile, TypeData, analyze, parse_source, verify_hir};
use aether_middle::{build_ssa, lower_hir, verify_mir, verify_ssa};

fn analyze_source(source: &str) -> aether_frontend::TypedHir {
    analyze(parse_source(&SourceFile::new("generic_local_inference_v1.ae", source)).unwrap())
        .unwrap_or_else(|errors| panic!("{source}\n{errors:#?}"))
}

fn diagnostics(source: &str) -> String {
    compile_source(
        &SourceFile::new("bad_generic_local_inference_v1.ae", source),
        &[],
    )
    .unwrap_err()
    .into_iter()
    .map(|diagnostic| format!("{} {}", diagnostic.code, diagnostic.message))
    .collect::<Vec<_>>()
    .join("\n")
}

struct Temporary(PathBuf);

impl Temporary {
    fn directory(label: &str) -> Self {
        static NEXT: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
        let path = std::env::temp_dir().join(format!(
            "aether-generic-local-{label}-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, std::sync::atomic::Ordering::Relaxed)
        ));
        fs::create_dir_all(&path).unwrap();
        Self(path)
    }
}

impl Drop for Temporary {
    fn drop(&mut self) {
        let _ = if self.0.is_dir() {
            fs::remove_dir_all(&self.0)
        } else {
            fs::remove_file(&self.0)
        };
    }
}

#[test]
fn nominal_intrinsic_const_nullable_and_generic_body_adopt_exact_rhs_type_ids() {
    let source = r#"
struct Box<T>{T value;}
struct Pair<T,U>{T first;U second;}
enum Maybe<T>{None,Some(T)}
Box<T> forward<T>(Box<T> value){Box copy=value;return copy;}
Box<int>? maybeBox(){Box<int>? value=Box<int>(7);return value;}
List<int> makeList(){List<int> value={1,2};return value;}
Array<int> makeArray(){Array<int> value={3,4};return value;}
Matrix<int> makeMatrix(){Matrix<int> value=[1,2;3,4];return value;}
Vector<int,Row> makeRow(){Vector<int,Row> value=[5,6];return value;}
Vector<int,Column> makeColumn(){Vector<int,Column> value=[7,8];return value;}
int main(){
  Box box=Box<int>(1);
  const Pair pair=Pair<int,string>(2,"x");
  Maybe choice=Maybe<int>.Some(3);
  List list=makeList();
  Array array=makeArray();
  Matrix matrix=makeMatrix();
  Vector row=makeRow();
  Vector column=makeColumn();
  Box? nullable=maybeBox();
  Box generic=forward(Box<int>(9));
  if(nullable==null){return 1;}
  if(box.value+pair.first+list[0]+array[0]+matrix[1,1]+row[1]+column[1]+generic.value!=29){return 2;}
  return 0;
}
"#;
    let hir = analyze_source(source);
    verify_hir(&hir).unwrap();
    let main = hir
        .functions()
        .iter()
        .find(|function| hir.instances()[function.id.0 as usize].name == "main")
        .unwrap();
    for local in main
        .locals
        .iter()
        .filter(|local| local.source_binding && !local.parameter)
    {
        assert!(
            !matches!(
                hir.types().get(local.ty),
                Some(TypeData::Struct(id)) if !hir.structs()[id.0 as usize].generic_parameters.is_empty()
            ),
            "generic struct declaration escaped as local type: {}",
            local.name
        );
        assert!(
            !matches!(
                hir.types().get(local.ty),
                Some(TypeData::Enum(id)) if !hir.enums()[id.0 as usize].generic_parameters.is_empty()
            ),
            "generic enum declaration escaped as local type: {}",
            local.name
        );
    }
    let mir = lower_hir(hir);
    let mir = verify_mir(mir).unwrap();
    let ssa = build_ssa(&mir);
    verify_ssa(ssa).unwrap();
}

#[test]
fn mismatch_scalar_nullable_undetermined_nesting_and_references_fail_closed() {
    let cases = [
        (
            "struct Box<T>{T x;}struct Other<T>{T x;}int main(){Box x=Other<int>(1);return 0;}",
            "E0460",
        ),
        ("struct Box<T>{T x;}int main(){Box x=1;return 0;}", "E0461"),
        (
            "struct Box<T>{T x;}T make<T>(){return make<T>();}int main(){Box x=make();return 0;}",
            "E0462",
        ),
        (
            "struct Box<T>{T x;}int main(){Box x=null;return 0;}",
            "E0462",
        ),
        (
            "struct Box<T>{T x;}int main(){List<Box> x={};return 0;}",
            "E0463",
        ),
        (
            "struct Box<T>{T x;}int main(){ref Box x=&Box<int>(1);return 0;}",
            "E0463",
        ),
        (
            "struct Box<T>{T x;}int main(){Box? x=Box<int>(1);return 0;}",
            "E0464",
        ),
    ];
    for (source, expected) in cases {
        let actual = diagnostics(source);
        assert!(actual.contains(expected), "{source}\n{actual}");
    }
}

#[test]
fn every_intrinsic_family_and_view_mutability_is_matched_exactly() {
    analyze_source(
        r"
int main(){
  Buffer buffer=Buffer<int>(2,1);
  Buffer other=Buffer<int>(2,2);
  if(true){View shared=view(buffer);int x=shared[0];}
  if(true){ViewMut mutable=view_mut(other);mutable[0]=3;}
  Matrix<int> matrix=[1,2;3,4];
  if(true){MatrixView sharedMatrix=matrix_view(matrix);int x=sharedMatrix[1,1];}
  if(true){MatrixViewMut mutableMatrix=matrix_view_mut(matrix);mutableMatrix[1,1]=5;}
  Vector<int,Row> vector=[6,7];
  if(true){VectorView sharedVector=vector_view(vector);int x=sharedVector[1];}
  if(true){VectorViewMut mutableVector=vector_view_mut(vector);mutableVector[1]=8;}
  return 0;
}
",
    );
}

#[test]
fn partial_omission_and_non_local_contexts_keep_requiring_complete_types() {
    let cases = [
        "struct Pair<T,U>{T a;U b;}int main(){Pair<int> p=Pair<int,int>(1,2);return 0;}",
        "struct Box<T>{T x;}int consume(Box value){return 0;}int main(){return 0;}",
        "struct Box<T>{T x;}Box make(){return Box<int>(1);}int main(){return 0;}",
        "struct Box<T>{T x;}struct Holder{Box value;}int main(){return 0;}",
        "struct Box<T>{T x;}enum E{Some(Box)}int main(){return 0;}",
        "struct Box<T>{T x;}alias Alias=Box;int main(){return 0;}",
    ];
    for source in cases {
        let actual = diagnostics(source);
        assert!(actual.contains("E0261"), "{source}\n{actual}");
    }
    assert!(diagnostics("int main(){var value=1;return 0;}").contains("unknown type `var`"));
}

#[test]
fn aliases_normalize_and_rhs_constraints_and_admission_remain_authoritative() {
    analyze_source(
        "struct Box<T>{T value;}alias IntBox=Box<int>;IntBox make(){return Box<int>(1);}int main(){Box value=make();return value.value-1;}",
    );

    let constrained =
        diagnostics("struct Box<T:Add>{T value;}int main(){Box value=Box<bool>(true);return 0;}");
    assert!(
        constrained.contains("does not satisfy") && !constrained.contains("E0460"),
        "{constrained}"
    );

    let inadmissible = diagnostics("int main(){Buffer value=Buffer<string>(1,\"x\");return 0;}");
    assert!(inadmissible.contains("E0280"), "{inadmissible}");
}

#[test]
fn imported_nominal_identity_is_resolved_before_rhs_matching() {
    let directory = Temporary::directory("imports");
    fs::write(
        directory.0.join("storage.ae"),
        "package storage;struct Box<T>{T value;}Box<int> make(){return Box<int>(42);}",
    )
    .unwrap();
    let entry = directory.0.join("main.ae");
    fs::write(
        &entry,
        "package main;import storage;int main(){storage.Box value=storage.make();return value.value-42;}",
    )
    .unwrap();
    compile_session(CompilationSession::discover(&entry).unwrap(), &[Emit::Hir]).unwrap();

    fs::write(
        &entry,
        "package main;int main(){storage.Box value=1;return 0;}",
    )
    .unwrap();
    let errors = compile_session(CompilationSession::discover(&entry).unwrap(), &[]).unwrap_err();
    assert!(
        errors
            .iter()
            .any(|error| matches!(error.code, "E0221" | "E0223"))
    );
}

#[test]
#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
fn initializer_side_effect_executes_once_at_o0_and_o2() {
    let source = r"
open class Problem:Exception{public init(){}}
struct Box<T>{T value;}
Box<int> bump(ref mut int count){*count=*count+1;return Box<int>(*count);}
Box<int> fail(){throw Problem();}
int main(){
  int count=0;
  Box value=bump(&mut count);
  try{Box never=fail();return 1;}
  catch(Problem problem){return count+value.value-2;}
}
";
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        let compilation = compile_source_with_optimization(
            &SourceFile::new("side_effect.ae", source),
            &[Emit::Llvm],
            optimization,
        )
        .unwrap();
        let output = Temporary(std::env::temp_dir().join(format!(
            "aether-generic-local-side-effect-{}-{optimization:?}",
            std::process::id()
        )));
        ClangToolchain::default()
            .with_optimization(optimization)
            .link_executable(&compilation.llvm, &output.0)
            .unwrap();
        assert_eq!(Command::new(&output.0).status().unwrap().code(), Some(0));
    }
}

#[test]
fn inferred_and_explicit_spelling_have_identical_lower_ir() {
    let inferred = "struct Box<T>{T x;}Box<Buffer<int>> make(){return Box<Buffer<int>>(Buffer<int>(1,7));}int main(){Box x=make();return x.x[0]-7;}";
    let explicit = "struct Box<T>{T x;}Box<Buffer<int>> make(){return Box<Buffer<int>>(Buffer<int>(1,7));}int main(){Box<Buffer<int>> x=make();return x.x[0]-7;}";
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        let inferred = compile_source_with_optimization(
            &SourceFile::new("same.ae", inferred),
            &[Emit::Hir, Emit::Mir, Emit::Ssa, Emit::Llvm],
            optimization,
        )
        .unwrap();
        let explicit = compile_source_with_optimization(
            &SourceFile::new("same.ae", explicit),
            &[Emit::Hir, Emit::Mir, Emit::Ssa, Emit::Llvm],
            optimization,
        )
        .unwrap();
        for phase in [Emit::Hir, Emit::Mir, Emit::Ssa] {
            let inferred_dump = &inferred.dumps[&phase];
            let explicit_dump = &explicit.dumps[&phase];
            assert_eq!(
                inferred_dump.matches("Box<Buffer<int64>>").count(),
                explicit_dump.matches("Box<Buffer<int64>>").count()
            );
            assert_eq!(
                inferred_dump.matches("TypeId(18)").count(),
                explicit_dump.matches("TypeId(18)").count()
            );
        }
        assert_eq!(inferred.llvm, explicit.llvm);
    }
}
