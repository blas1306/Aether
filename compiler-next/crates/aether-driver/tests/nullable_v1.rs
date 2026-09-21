//! NULLABLE-V1 end-to-end and fail-closed qualification.

use std::{fs, path::PathBuf, process::Command};

use aether_driver::{
    ClangToolchain, Emit, OptimizationLevel, compile_source, compile_source_with_optimization,
};
use aether_frontend::{
    AstTypeKind, NullableLayout, SourceFile, TargetProperties, TypeArena, TypeId, layout_of,
    nullable_layout_of, parse_source,
};

struct Output(PathBuf);
impl Output {
    fn new(name: &str) -> Self {
        static NEXT: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
        Self(std::env::temp_dir().join(format!(
            "aether-nullable-v1-{name}-{}-{}",
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
        &SourceFile::new("nullable_v1.ae", source),
        &[Emit::Ast, Emit::Hir, Emit::Mir, Emit::Ssa, Emit::Llvm],
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

fn diagnostics(source: &str) -> String {
    compile_source(&SourceFile::new("bad_nullable_v1.ae", source), &[])
        .unwrap_err()
        .into_iter()
        .map(|d| format!("{} {}", d.code, d.message))
        .collect::<Vec<_>>()
        .join("\n")
}

#[test]
fn niche_owner_null_inject_refinement_and_conditional_drop_work_o0_o2() {
    let source = r#"
int main() {
    string? name = null;
    if (name != null) { println(name); }
    string? value = "Aether";
    if (value == null) { return 1; } else { println(value); }
    return 0;
}
"#;
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        assert_eq!(status(source, optimization), 0);
    }
    let compilation = compile(source, OptimizationLevel::O0);
    assert!(compilation.dumps[&Emit::Hir].contains("NullableNull"));
    assert!(compilation.dumps[&Emit::Hir].contains("NullableInject"));
    assert!(compilation.dumps[&Emit::Hir].contains("NullablePayload"));
    assert!(compilation.llvm.contains("aether_drop_N3xstr"));
}

#[test]
fn tagged_defaults_returns_copy_payload_and_logical_not_work_o0_o2() {
    let source = r"
int? choose(int? value = null) { return value; }
bool positive(int value) { return value > 0; }
int main() {
    int? value = choose(7);
    if (!(value == null) && positive(value)) { return value - 7; }
    return 1;
}
";
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        assert_eq!(status(source, optimization), 0);
    }
    let llvm = compile(source, OptimizationLevel::O0).llvm;
    assert!(llvm.contains("{ i8, i64 }"));
    assert!(llvm.contains("N6xiInt64"));
}

#[test]
fn canonical_identity_properties_layout_and_reference_precedence_are_exact() {
    let mut types = TypeArena::new();
    let nullable_int = types.intern_nullable(TypeId::INT64).unwrap();
    let nullable_string = types.intern_nullable(TypeId::STRING).unwrap();
    assert_ne!(nullable_int, TypeId::INT64);
    assert_eq!(types.intern_nullable(TypeId::INT64).unwrap(), nullable_int);
    assert!(types.is_copy(nullable_int));
    assert!(types.needs_drop(nullable_string));
    assert!(types.intern_nullable(TypeId::VOID).is_err());
    assert!(types.intern_nullable(nullable_int).is_err());
    assert!(matches!(
        nullable_layout_of(
            &types,
            nullable_string,
            TargetProperties::LINUX_X86_64,
            &[],
            &[]
        ),
        Some(NullableLayout::Niche { .. })
    ));
    assert!(matches!(
        nullable_layout_of(
            &types,
            nullable_int,
            TargetProperties::LINUX_X86_64,
            &[],
            &[]
        ),
        Some(NullableLayout::Tagged {
            payload_offset: 8,
            ..
        })
    ));
    assert_eq!(
        layout_of(
            &types,
            nullable_int,
            TargetProperties::LINUX_X86_64,
            &[],
            &[]
        )
        .unwrap()
        .size,
        16
    );

    let ast = parse_source(&SourceFile::new(
        "types.ae",
        r"
void f(ref string? slot, (ref string)? maybe) {}
",
    ))
    .unwrap();
    let parameters = &ast.functions()[0].parameters;
    assert!(matches!(parameters[0].ty.kind, AstTypeKind::Reference(_)));
    assert!(matches!(
        parameters[1].ty.kind,
        AstTypeKind::Nullable { .. }
    ));
}

#[test]
fn invalid_nullability_and_owning_payload_moves_fail_closed() {
    let cases = [
        (
            "int main(){string x=null;return 0;}",
            "cannot use null where non-null string is required",
        ),
        (
            "int main(){int?? x=null;return 0;}",
            "nested nullable is not supported",
        ),
        (
            "int main(){int? x=null;return x;}",
            "cannot use int64? where non-null int64 is required",
        ),
        (
            "string take(string x){return x;} int main(){string? x=\"x\";if(x!=null){take(x);}return 0;}",
            "cannot move owning payload",
        ),
        ("int main(){if(null==null){return 0;}return 1;}", ""),
    ];
    for (source, expected) in &cases[..4] {
        assert!(
            diagnostics(source).contains(expected),
            "{}",
            diagnostics(source)
        );
    }
    assert_eq!(status(cases[4].0, OptimizationLevel::O0), 0);
}

#[test]
fn nullable_composes_with_generics_defaults_const_collections_and_aggregates() {
    let source = r#"
T? identityNullable<T>(T? value){return value;}
string? absent(string? value=null){return value;}
struct Number{int value;}
class Boxed{int value;public init(int value){this.value=value;}public int get(){return value;}}
int main(){
 const string? text=absent("ok");
 List<string?> elements={null,"x"};
 List<string>? optionalList={"owned"};
 Number? number=Number(7);
 Boxed? object=Boxed(8);
 string? inferred=identityNullable("generic");
 string? explicitNull=identityNullable<string>(null);
 if(text==null){return 1;}
 if(number==null){return 2;}
 if(object==null){return 3;}
 if(inferred==null){return 4;}
 if(explicitNull!=null){return 5;}
 if(optionalList==null){return 6;}
 return 0;
}
"#;
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        assert_eq!(status(source, optimization), 0);
    }
}

#[test]
fn nullable_functions_and_references_refine_without_conflating_storage() {
    let source = r"
int addOne(int value){return value+1;}
int read((ref int)? value){if(value!=null){return *value;}return 0;}
int inspect(ref int? slot){if(*slot==null){return 0;}return 1;}
int inspectMut(ref mut int? slot){if(*slot!=null){return 1;}return 0;}
int main(){
 Function<(int),int>? callback=addOne;
 int number=9;(ref int)? maybeRef=&number;
 int? storage=null;
 if(callback!=null){if(callback(9)!=10){return 1;}}
 if(read(maybeRef)!=9){return 2;}
 if(inspect(storage)!=0){return 3;}
 if(inspectMut(&mut storage)!=0){return 4;}
 return 0;
}
";
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        assert_eq!(status(source, optimization), 0);
    }
}

#[test]
fn refinement_handles_symmetric_tests_short_circuit_joins_and_invalidation() {
    let source = r"
bool positive(int value){return value>0;}
int main(){
 int? value=1;
 if(null!=value&&positive(value)){}else{return 1;}
 if(null==value||positive(value)){}else{return 2;}
 if(value==null){}else{int copy=value;if(copy!=1){return 3;}}
 if(true){value=2;}else{value=3;}
 int joined=value;
 value=null;
 if(value!=null){return value;}
 value=joined;
 if(!(value==null)){return value-2;}
 return 4;
}
";
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        assert_eq!(status(source, optimization), 0);
    }
}

#[test]
fn unsupported_nullable_operations_and_null_only_inference_fail_closed() {
    let cases = [
        (
            "T? choose<T>(T? value){return value;}int main(){int? x=choose(null);return 0;}",
            "cannot infer generic parameter",
        ),
        (
            "int main(){var value=null;return 0;}",
            "null cannot infer a payload type",
        ),
        (
            "int main(){int? a=1;int? b=2;if(a==b){return 1;}return 0;}",
            "nullable",
        ),
        (
            "void clear(ref mut int? slot){*slot=null;}int main(){int? value=1;ref mut int? link=&mut value;if(value!=null){clear(link);int x=value;}return 0;}",
            "non-null int64 is required",
        ),
        (
            "int main(){int? value=1;if(value!=null){value=null;int x=value;}return 0;}",
            "non-null int64 is required",
        ),
        (
            "int main(){int? value=1;int count=0;while(count<2){int copy=value;value=null;count=count+1;}return 0;}",
            "non-null int64 is required",
        ),
    ];
    for (source, expected) in cases {
        let actual = diagnostics(source);
        assert!(actual.contains(expected), "{source}\n{actual}");
    }
}

#[test]
fn loop_body_uses_condition_fact_but_cannot_export_an_optimistic_fact() {
    let source = r"
int main(){
 int? value=2;int sum=0;
 while(value!=null){sum=sum+value;value=null;}
 if(value!=null){return 1;}
 return sum-2;
}
";
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        assert_eq!(status(source, optimization), 0);
    }
}

#[test]
fn owning_nullable_cleanup_is_conditional_on_normal_and_unwind_paths() {
    let source = r#"
open class Problem:Exception{public init(){}}
void fail(){throw Problem();}
int main(){
 try{string? absent=null;string? present="owned";fail();}
 catch(Problem problem){return 0;}
 return 1;
}
"#;
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        let compilation = compile(source, optimization);
        let output = Output::new("nullable-unwind");
        ClangToolchain::default()
            .with_optimization(optimization)
            .link_executable(&compilation.llvm, &output.0)
            .unwrap();
        assert_eq!(Command::new(&output.0).status().unwrap().code(), Some(0));
        assert!(compilation.llvm.contains("aether_drop_N3xstr"));
    }
}
