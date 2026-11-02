//! OWNING-CLOSURES-READ-V1 foundation and fail-closed qualification.

use aether_driver::{Emit, OptimizationLevel, compile_source_with_optimization};
use aether_frontend::{
    AstCaptureMode, AstExprKind, AstStmtKind, AstTypeKind, SourceFile, TargetProperties, TypeArena,
    TypeData, TypeId, layout_of, lex, parse,
};

#[test]
fn closure_type_is_distinct_owning_one_pointer_carrier() {
    let mut types = TypeArena::new();
    let closure = types
        .intern_closure(vec![TypeId::FLOAT64], TypeId::FLOAT64)
        .unwrap();
    let function = types
        .intern_function(vec![TypeId::FLOAT64], TypeId::FLOAT64)
        .unwrap();

    assert_ne!(closure, function);
    assert!(matches!(types.get(closure), Some(TypeData::Closure { .. })));
    let properties = types.properties(closure).unwrap();
    assert!(properties.is_known && properties.is_relocatable && properties.is_storable);
    assert!(!properties.is_copy && properties.needs_drop);
    assert_eq!(
        layout_of(&types, closure, TargetProperties::LINUX_X86_64, &[], &[])
            .map(|layout| (layout.size, layout.align)),
        Some((8, 8))
    );
}

#[test]
fn closure_type_and_partial_capture_clause_parse_without_function_coercion() {
    let source = SourceFile::new(
        "owning_closures_read_v1.ae",
        r#"
Closure<(double),double> accept(Closure<(double),double> f){return f;}
int main(){
  double a=2.0;
  string label="x";
  var f=(double x) capture(copy a, alias label)=>a*x;
  return 0;
}"#,
    );
    let ast = parse(&source, lex(&source).unwrap()).unwrap();
    assert!(matches!(
        ast.functions()[0].return_type.kind,
        AstTypeKind::Closure { .. }
    ));
    let main = ast
        .functions()
        .iter()
        .find(|function| function.name == "main")
        .unwrap();
    let lambda = main
        .body
        .statements
        .iter()
        .find_map(|statement| match &statement.kind {
            AstStmtKind::Local { initializer, .. } => match &initializer.kind {
                AstExprKind::Lambda { captures, .. } => Some(captures),
                _ => None,
            },
            _ => None,
        })
        .unwrap();
    assert_eq!(lambda.len(), 2);
    assert_eq!(lambda[0].mode, AstCaptureMode::Copy);
    assert_eq!(lambda[0].name, "a");
    assert_eq!(lambda[1].mode, AstCaptureMode::Alias);
    assert_eq!(lambda[1].name, "label");
}

#[test]
fn malformed_capture_modes_and_trailing_entries_fail_closed() {
    for (source, expected) in [
        (
            "int main(){int a=1;var f=() capture(clone a)=>a;}",
            "capture mode must",
        ),
        (
            "int main(){int a=1;var f=() capture(copy a,)=>a;}",
            "expected capture after",
        ),
        (
            "int main(){int a=1;var f=() capture(copy a, copy a)=>a;}",
            "duplicate explicit capture",
        ),
    ] {
        let source = SourceFile::new("bad_closure.ae", source);
        let diagnostics = parse(&source, lex(&source).unwrap()).unwrap_err();
        assert!(
            diagnostics
                .iter()
                .any(|diagnostic| diagnostic.code == "E0368"
                    && diagnostic.message.contains(expected))
        );
    }
}

#[test]
fn versioned_arc_helpers_use_the_v1_header_destroy_offset() {
    let source = SourceFile::new(
        "closure_abi_v1.ae",
        "void sink(Closure<(double),double> f){} int main(){return 0;}",
    );
    let compilation =
        compile_source_with_optimization(&source, &[Emit::Llvm], OptimizationLevel::O0).unwrap();
    assert!(
        compilation
            .llvm
            .contains("define ptr @aether_closure_retain_v1")
    );
    assert!(
        compilation
            .llvm
            .contains("define void @aether_closure_release_v1")
    );
    assert!(
        compilation
            .llvm
            .contains("getelementptr i8, ptr %box, i64 16")
    );
    assert!(
        compilation
            .llvm
            .contains("call void %destroy_thunk(ptr %box)")
    );
}
