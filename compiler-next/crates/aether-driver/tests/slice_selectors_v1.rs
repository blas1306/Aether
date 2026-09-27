//! SLICE-SELECTORS-V1 parser, AST and typed-selector qualification.

use aether_driver::{OptimizationLevel, compile_source_with_optimization};
use aether_frontend::{
    AstExprKind, AstStmtKind, AstSubscriptSelector, SourceFile, analyze, parse_source,
};

fn parse(source: &str) -> aether_frontend::ParsedAst {
    parse_source(&SourceFile::new("slice_selectors_v1.ae", source))
        .unwrap_or_else(|errors| panic!("{source}\n{errors:#?}"))
}

fn first_error(source: &str) -> aether_frontend::Diagnostic {
    compile_source_with_optimization(
        &SourceFile::new("slice_selectors_v1.ae", source),
        &[],
        OptimizationLevel::O0,
    )
    .expect_err(source)
    .remove(0)
}

#[test]
fn parser_builds_scalar_closed_full_and_matrix_combinations() {
    for expression in [
        "a[i]",
        "a[1:3]",
        "a[:]",
        "A[i,j]",
        "A[i,:]",
        "A[:,j]",
        "A[1:3,2:5]",
        "A[:,:]",
        "A[1:3,:]",
        "A[:,2:5]",
        "a[(1+f(2)):(g(3)*4)]",
    ] {
        let source = format!("int main(){{int x={expression};return x;}}");
        parse(&source);
    }

    let ast = parse("int main(){int x=a[1:3];int y=a[:];return 0;}");
    let statements = &ast.functions()[0].body.statements;
    let AstStmtKind::Local { initializer, .. } = &statements[0].kind else {
        panic!("expected local");
    };
    let AstExprKind::Index { selectors, .. } = &initializer.kind else {
        panic!("expected subscript");
    };
    assert!(matches!(
        selectors.as_slice(),
        [AstSubscriptSelector::Closed { .. }]
    ));
    assert!(!format!("{initializer:#?}").contains("Range"));

    let AstStmtKind::Local { initializer, .. } = &statements[1].kind else {
        panic!("expected local");
    };
    let AstExprKind::Index { selectors, .. } = &initializer.kind else {
        panic!("expected subscript");
    };
    assert_eq!(selectors, &[AstSubscriptSelector::Full]);
}

#[test]
fn endpoint_calls_are_stored_once_and_in_source_order() {
    let ast = parse(
        "usize first(){return 1;}usize last(){return 2;}int main(){Array<int>a={1,2};int x=a[first():last()];return x;}",
    );
    let main = ast.functions().last().unwrap();
    let AstStmtKind::Local { initializer, .. } = &main.body.statements[1].kind else {
        panic!("expected indexed local");
    };
    let AstExprKind::Index { selectors, .. } = &initializer.kind else {
        panic!("expected subscript");
    };
    let [AstSubscriptSelector::Closed { first, last }] = selectors.as_slice() else {
        panic!("expected one closed selector");
    };
    assert!(matches!(&first.kind, AstExprKind::Call { callee, .. } if callee == "first"));
    assert!(matches!(&last.kind, AstExprKind::Call { callee, .. } if callee == "last"));
}

#[test]
fn partial_stride_multiple_colon_and_malformed_forms_are_specific() {
    for (selector, code, detail) in [
        ("1:", "E0452", "partial slice"),
        (":3", "E0452", "partial slice"),
        ("1:2:3", "E0453", "stride"),
        ("::", "E0453", "stride"),
        ("::-1", "E0453", "stride"),
        ("1::2", "E0453", "stride"),
        ("1:2:3:4", "E0454", "multiple colons"),
        ("1,", "E0455", "malformed matrix selector"),
        (",1", "E0455", "malformed subscript"),
        ("1;2", "E0455", "malformed matrix selector"),
    ] {
        let source = format!("int main(){{Array<int>a={{1}};return a[{selector}];}}");
        let error = parse_source(&SourceFile::new("bad.ae", source))
            .expect_err(selector)
            .remove(0);
        assert_eq!(error.code, code, "{selector}: {error:?}");
        assert!(error.message.contains(detail), "{selector}: {error:?}");
    }
}

#[test]
fn selector_count_is_checked_by_container_rank() {
    for (body, expected, found) in [
        ("Array<int>a={1};return a[0,0];", 1, 2),
        ("List<int>a={1};return a[0,0];", 1, 2),
        ("Vector<int,Row>a=[1];return a[1,1];", 1, 2),
        ("Matrix<int>a=[1];return a[1];", 2, 1),
        ("Matrix<int>a=[1];return a[1,1,1];", 2, 3),
    ] {
        let error = first_error(&format!("int main(){{{body}}}"));
        assert_eq!(error.code, "E0334", "{body}: {error:?}");
        assert!(
            error
                .message
                .contains(&format!("expects {expected} selectors"))
        );
        assert!(error.message.contains(&format!("found {found}")));
    }
}

#[test]
fn typed_slice_metadata_resolves_base_axis_container_and_future_rank() {
    for (body, fragments) in [
        (
            "Array<int>a={1};Array<int>b=a[:];",
            &["CollectionOwner", "Array", "axes [Linear]", "base 0"][..],
        ),
        (
            "List<int>a={1};List<int>b=a[0:0];",
            &["CollectionOwner", "List", "axes [Linear]", "base 0"],
        ),
        (
            "Vector<int,Row>a=[1];VectorView<int,Row>b=a[:];",
            &[
                "VectorView { orientation: Row }",
                "Vector { orientation: Row }",
                "base 1",
            ],
        ),
        (
            "Matrix<int>a=[];MatrixView<int>b=a[:,:];",
            &["MatrixView", "Matrix", "axes [Row, Column]", "base 1"],
        ),
        (
            "Matrix<int>a=[1];VectorView<int,Row>b=a[1,:];",
            &[
                "VectorView { orientation: Row }",
                "axes [Row, Column]",
                "base 1",
            ],
        ),
        (
            "Matrix<int>a=[1];VectorView<int,Column>b=a[:,1];",
            &[
                "VectorView { orientation: Column }",
                "axes [Row, Column]",
                "base 1",
            ],
        ),
    ] {
        let error = first_error(&format!("int main(){{{body}return 0;}}"));
        assert_eq!(error.code, "E0456", "{body}: {error:?}");
        for fragment in fragments {
            assert!(
                error.message.contains(fragment),
                "{body}: {fragment}: {error:?}"
            );
        }
    }
}

#[test]
fn scalar_indexing_keeps_working_at_o0_and_o2_with_typed_metadata() {
    let source = "int main(){Array<int>a={7};List<int>b={8};Vector<int,Row>v=[9];Matrix<int>m=[10];return a[0]+b[0]+v[1]+m[1,1]-34;}";
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        compile_source_with_optimization(&SourceFile::new("scalar.ae", source), &[], optimization)
            .unwrap_or_else(|errors| panic!("{optimization:?}: {errors:#?}"));
    }

    let hir = analyze(parse(source)).unwrap();
    let dump = hir.dump();
    for fragment in [
        "container_kind: Array",
        "container_kind: List",
        "container_kind: Vector",
        "container_kind: Matrix",
        "axis: Linear",
        "axis: Row",
        "axis: Column",
        "index_base: 0",
        "index_base: 1",
        "result: Scalar",
    ] {
        assert!(dump.contains(fragment), "missing {fragment}\n{dump}");
    }
}
