//! V33 native, diagnostic, schedule-corruption and cost qualification.
use super::*;
use aether_middle::{
    AlgebraicProductKernel, BinaryOp, MathAxis, MathInput, MathStep, MathStride, Operand,
    ProductStep,
};
use std::os::unix::process::ExitStatusExt;

fn compile(text: impl Into<String>) -> aether_driver::Compilation {
    compile_source(
        &SourceFile::new("v33.ae", text),
        &[Emit::Hir, Emit::Mir, Emit::Ssa],
    )
    .unwrap()
}

// Instrument only instructions executed within the product region. In particular,
// descriptor extraction is not an element load and operand construction is excluded.
fn instrument(llvm: &str, heap: u64) -> String {
    let counters = [
        ("a", "aether_heap_alloc_count"),
        ("f", "aether_heap_free_count"),
        ("r", "aether_relocation_count"),
        ("m", "v33_mul"),
        ("p", "v33_add"),
        ("s", "v33_store"),
        ("l", "v33_load"),
    ];
    let mut out = String::new();
    let mut region = None;
    for line in llvm.lines() {
        writeln!(out, "{line}").unwrap();
        if let Some(rest) = line.trim().strip_prefix("; AlgebraicBegin ") {
            let id = rest.split_whitespace().next().unwrap().to_owned();
            let inner = rest.contains("ReductionKernel");
            let matrix = rest.contains("MatrixColumnKernel");
            let row = rest.contains("RowMatrixKernel");
            let mm = rest.contains("MatrixMatrixKernel");
            for (short, global) in counters {
                writeln!(out, "  %q{id}_{short}0 = load i64, ptr @{global}").unwrap();
            }
            region = Some((id, inner, matrix, row, mm));
        }
        let Some((id, inner, matrix, row, mm)) = &region else {
            continue;
        };
        let tag = if line.contains("_product_checked = call") || line.contains("_product = fmul") {
            Some(("mul", "m"))
        } else if line.contains("_accumulate_checked = call") || line.contains("_accumulate = fadd")
        {
            Some(("add", "p"))
        } else if line.contains("; InitializeNext") {
            Some(("store", "s"))
        } else if line.contains("_Left_value = load") {
            Some(("load", "ll"))
        } else if line.contains("_Right_value = load") {
            Some(("load", "lr"))
        } else {
            None
        };
        if let Some((global, short)) = tag {
            writeln!(out, "  %q{id}_{short}n = load i64, ptr @v33_{global}\n  %q{id}_{short}next = add i64 %q{id}_{short}n, 1\n  store i64 %q{id}_{short}next, ptr @v33_{global}").unwrap();
        }
        if line.trim().starts_with("; AlgebraicEnd ") {
            if *mm {
                writeln!(out, "  %q{id}_result = mul i64 %vp{id}_Left_Rows, %vp{id}_Right_Columns\n  %q{id}_count = mul i64 %q{id}_result, %vp{id}_Left_Columns").unwrap();
            } else if *matrix || *row {
                let side = if *matrix { "Left" } else { "Right" };
                let result = if *matrix { "Rows" } else { "Columns" };
                writeln!(out, "  %q{id}_count = mul i64 %vp{id}_{side}_Rows, %vp{id}_{side}_Columns\n  %q{id}_result = add i64 %vp{id}_{side}_{result}, 0").unwrap();
            } else if *inner {
                writeln!(out, "  %q{id}_count = add i64 %vp{id}_Left_Dimension, 0").unwrap();
            } else {
                writeln!(
                    out,
                    "  %q{id}_count = mul i64 %vp{id}_Left_Dimension, %vp{id}_Right_Dimension"
                )
                .unwrap();
            }
            let extent = if *matrix || *row || *mm {
                "result"
            } else {
                "count"
            };
            writeln!(out, "  %q{id}_loads = mul i64 %q{id}_count, 2\n  %q{id}_nonempty = icmp ne i64 %q{id}_{extent}, 0\n  %q{id}_allocation = zext i1 %q{id}_nonempty to i64").unwrap();
            for (short, global) in counters {
                let expected = match short {
                    "m" => format!("%q{id}_count"),
                    "p" if *inner || *matrix || *row || *mm => format!("%q{id}_count"),
                    "l" => format!("%q{id}_loads"),
                    "a" if !inner => format!("%q{id}_allocation"),
                    "s" if !inner => format!("%q{id}_{extent}"),
                    _ => "0".into(),
                };
                writeln!(out, "  %q{id}_{short}1 = load i64, ptr @{global}\n  %q{id}_{short}delta = sub i64 %q{id}_{short}1, %q{id}_{short}0\n  %q{id}_{short}ok = icmp eq i64 %q{id}_{short}delta, {expected}\n  %q{id}_{short}old = load i1, ptr @v33_ok\n  %q{id}_{short}all = and i1 %q{id}_{short}old, %q{id}_{short}ok\n  store i1 %q{id}_{short}all, ptr @v33_ok").unwrap();
            }
            region = None;
        }
    }
    for global in ["mul", "add", "store", "load"] {
        writeln!(out, "@v33_{global} = internal global i64 0").unwrap();
    }
    out.push_str("@v33_ok = internal global i1 true\n");
    v23_heap_guard(&out, heap).replace("  %all_ok = and i1 %heap_ok, %result_ok", "  %v33_pass = load i1, ptr @v33_ok\n  %v33_both = and i1 %heap_ok, %v33_pass\n  %all_ok = and i1 %v33_both, %result_ok")
}

#[test]
fn vertical33_native_fixtures_and_exact_costs() {
    for (name, heap) in [
        ("rectangular", 3),
        ("one_cell", 3),
        ("strided", 3),
        ("left_transposed", 3),
        ("right_transposed", 3),
        ("both_transposed", 3),
        ("generic_int", 3),
        ("generic_double", 3),
        ("zero_contraction", 3),
        ("zero_axes", 3),
    ] {
        let c = compile(fs::read_to_string(program(&format!("v33_{name}.ae"))).unwrap());
        for phase in [Emit::Mir, Emit::Ssa] {
            assert!(!c.dumps[&phase].contains("Behavioral("));
            assert!(!c.dumps[&phase].contains("AlgebraicValue"));
            assert!(c.dumps[&phase].contains("MatrixMatrixKernel"));
        }
        assert_eq!(
            v23_execute(&instrument(&c.llvm, heap)).code(),
            Some(0),
            "{name}"
        );
    }
    for ty in ["int", "float32"] {
        for (name, heap) in [("zero_contraction", 3), ("zero_axes", 3)] {
            let source = fs::read_to_string(program(&format!("v33_{name}.ae")))
                .unwrap()
                .replace("double", ty)
                .replace(
                    "if(1/z[1,1]<0){return 9;}",
                    if ty == "int" {
                        ""
                    } else {
                        "if(1/z[1,1]<0){return 9;}"
                    },
                );
            let c = compile(source);
            assert_eq!(v23_execute(&instrument(&c.llvm, heap)).code(), Some(0));
        }
    }
}

#[test]
fn vertical33_all_readable_families_and_builtin_scalars() {
    for scalar in [
        "int8", "int16", "int32", "int64", "uint8", "uint16", "uint32", "uint64", "isize", "usize",
        "float32", "float64", "int", "float", "double",
    ] {
        let families = [
            ("ref Matrix", "*", "&"),
            ("MatrixView", "", "matrix_view"),
            ("MatrixViewMut", "", "matrix_view_mut"),
        ];
        let mut helpers = String::new();
        let mut body =
            format!("int main(){{Matrix<{scalar}>a=[1,2,3;4,5,6];Matrix<{scalar}>b=[1,2;3,4;5,6];");
        for (i, (lf, le, la)) in families.iter().enumerate() {
            for (j, (rf, re, ra)) in families.iter().enumerate() {
                let arg = |a: &str, n: &str| {
                    if a == "&" {
                        format!("&{n}")
                    } else {
                        format!("{a}({n})")
                    }
                };
                write!(helpers,"Matrix<T> mm{i}{j}<T:Storable+Copy+Add+Mul+Zero>({lf}<T>a,{rf}<T>b){{return {le}a*{re}b;}}").unwrap();
                write!(body,"if(true){{Matrix<{scalar}>c=mm{i}{j}({},{});if(rows(c)!=2){{return 1;}}if(columns(c)!=2){{return 2;}}if(c[1,1]!=22){{return 3;}}if(c[1,2]!=28){{return 4;}}if(c[2,1]!=49){{return 5;}}if(c[2,2]!=64){{return 6;}}}}",arg(la,"a"),arg(ra,"b")).unwrap();
            }
        }
        body.push_str("if(a[2,3]!=6){return 7;}if(b[3,2]!=6){return 8;}return 0;}");
        let c = compile(helpers + &body);
        assert_eq!(
            v23_execute(&instrument(&c.llvm, 11)).code(),
            Some(0),
            "{scalar}"
        );
    }
}

#[test]
fn vertical33_parametric_constraints_diagnostics_and_forwarding() {
    for missing in ["Storable", "Copy", "Add", "Mul", "Zero"] {
        let caps = ["Storable", "Copy", "Add", "Mul", "Zero"]
            .into_iter()
            .filter(|c| *c != missing)
            .collect::<Vec<_>>()
            .join("+");
        for forward in [false, true] {
            let body = if forward { "good(a,b)" } else { "a*b" };
            let source = format!(
                "Matrix<T> good<T:Storable+Copy+Add+Mul+Zero>(MatrixView<T>a,MatrixView<T>b){{return a*b;}}Matrix<T> bad<T:{caps}>(MatrixView<T>a,MatrixView<T>b){{return {body};}}int main(){{return 0;}}"
            );
            let e = compile_source(&SourceFile::new("missing.ae", source), &[]).unwrap_err();
            assert!(
                e.iter().any(|e| e.message.contains(missing)),
                "{forward} {missing}: {e:?}"
            );
        }
    }
    for (body, code) in [
        (
            "Matrix<int>a=[1];Matrix<double>b=[1];Matrix<int>c=a*b;",
            "E0343",
        ),
        (
            "Matrix<float32>a=[1];Matrix<float64>b=[1];Matrix<float32>c=a*b;",
            "E0343",
        ),
        (
            "Matrix<int>a=[1,2];Matrix<int>b=[1];Matrix<int>c=a*b;",
            "E0345",
        ),
        ("Matrix<int>a=[1,2];Matrix<int>b=[1;2];int c=a*b;", "E0218"),
        ("Matrix<int>a=[1];MatrixView<int>c=a*a;", "E0218"),
        ("Matrix<int>a=[1];Vector<int,Row>c=a*a;", "E0218"),
        (
            "Matrix<int>a=[1];Vector<int,Row>r=[1];Matrix<int>c=a*r;",
            "E0342",
        ),
        (
            "Matrix<int>a=[1];Vector<int,Column>r=[1];Matrix<int>c=r*a;",
            "E0342",
        ),
        ("Vector<int,Row>r=[1];Vector<int,Row>c=r*r;", "E0342"),
        ("Vector<int,Column>r=[1];Vector<int,Column>c=r*r;", "E0342"),
        (
            "Vector<int,Column>e=[];Vector<int,Row>r=[1,2,3];Vector<int,Column>c=[1,2,3,4];Vector<int,Row>f=[];Matrix<int>a=e*r;Matrix<int>b=c*f;Matrix<int>z=a*b;",
            "E0345",
        ),
    ] {
        let e = compile_source(
            &SourceFile::new("bad.ae", format!("int main(){{{body}return 0;}}")),
            &[],
        )
        .unwrap_err();
        assert!(e.iter().any(|e| e.code == code), "{body}: {e:?}");
    }
    let e=compile_source(&SourceFile::new("struct.ae","struct S{int x;}Matrix<S> bad(MatrixView<S>a,MatrixView<S>b){return a*b;}int main(){return 0;}"),&[]).unwrap_err();
    assert!(e.iter().any(|e| e.code == "E0346"), "{e:?}");
}

#[test]
fn vertical33_integer_product_and_accumulator_overflow() {
    for (ty, max) in [
        ("int8", "127"),
        ("int16", "32767"),
        ("int32", "2147483647"),
        ("int64", "9223372036854775807"),
        ("isize", "9223372036854775807"),
        ("uint8", "255"),
        ("uint16", "65535"),
        ("uint32", "4294967295"),
        ("uint64", "18446744073709551615"),
        ("usize", "18446744073709551615"),
    ] {
        for sum in [false, true] {
            let (a, b) = if sum {
                (format!("[{max},1]"), "[1;1]")
            } else {
                (format!("[{max}]"), "[2]")
            };
            let c = compile(format!(
                "int main(){{Matrix<{ty}>a={a};Matrix<{ty}>b={b};Matrix<{ty}>c=a*b;return 0;}}"
            ));
            assert_eq!(v23_execute(&c.llvm).signal(), Some(4), "{ty} {sum}");
            assert!(c.llvm.contains("mul.with.overflow"));
            assert!(c.llvm.contains("add.with.overflow"));
        }
    }
}

#[test]
fn vertical33_ieee_order_zero_infinity_nan_and_transposes() {
    for (ty, large, llvm_ty) in [
        ("float32", "16777216", "float"),
        ("float64", "9007199254740992", "double"),
    ] {
        let c = compile(format!(
            "int main(){{Matrix<{ty}>a=[{large},1,-{large};{large},1,-{large}];Matrix<{ty}>b=[1,1;1,1;1,1];Matrix<{ty}>c=a*b;if(c[1,1]!=0){{return 1;}}if(c[1,2]!=0){{return 2;}}if(c[2,1]!=0){{return 3;}}if(c[2,2]!=0){{return 4;}}return 0;}}"
        ));
        assert_eq!(v23_execute(&instrument(&c.llvm, 3)).code(), Some(0));
        for (value, check) in [
            ("-0.0", "if(c[1,1]!=0){return 1;}if(1/c[1,1]<0){return 2;}"),
            ("1.0/0.0", "if(c[1,1]!=v){return 3;}"),
            ("0.0/0.0", "if(c[1,1]==c[1,1]){return 4;}"),
        ] {
            let c = compile(format!(
                "int main(){{{ty} v={value};Matrix<{ty}>a=[v];Matrix<{ty}>b=[1];Matrix<{ty}>c=a*b;{check}return 0;}}"
            ));
            assert_eq!(
                v23_execute(&instrument(&c.llvm, 3)).code(),
                Some(0),
                "{ty} {value}"
            );
            let region = c
                .llvm
                .split("; AlgebraicBegin ")
                .nth(1)
                .unwrap()
                .split("; AlgebraicEnd ")
                .next()
                .unwrap();
            assert!(
                region.find(&format!(" = fmul {llvm_ty}")).unwrap()
                    < region.find(&format!(" = fadd {llvm_ty}")).unwrap()
            );
            for bad in [
                " fast ",
                " reassoc ",
                " contract ",
                "llvm.fma",
                "llvm.fmuladd",
                "noalias",
                "blas",
            ] {
                assert!(!region.contains(bad));
            }
            assert_eq!(region.matches("_accumulator = phi").count(), 1);
        }
        for name in [
            "strided",
            "left_transposed",
            "right_transposed",
            "both_transposed",
        ] {
            let source = fs::read_to_string(program(&format!("v33_{name}.ae")))
                .unwrap()
                .replace("Matrix<int>", &format!("Matrix<{ty}>"))
                .replace("MatrixView<int>", &format!("MatrixView<{ty}>"));
            let c = compile(source);
            assert_eq!(
                v23_execute(&instrument(&c.llvm, 3)).code(),
                Some(0),
                "{ty} {name}"
            );
        }
    }
}

#[test]
fn vertical33_alias_evaluation_temporaries_and_nonconsuming_owners() {
    let c = compile(
        "Matrix<int> lhs(ref mut int s){*s=*s*10+1;Matrix<int>a=[2];return a;}Matrix<int> rhs(ref mut int s){*s=*s*10+2;Matrix<int>a=[3];return a;}int main(){int s=0;Matrix<int>c=lhs(&mut s)*rhs(&mut s);if(s!=12){return 1;}if(c[1,1]!=6){return 2;}return 0;}",
    );
    assert_eq!(v23_execute(&instrument(&c.llvm, 3)).code(), Some(0));
    let c = compile(
        "int main(){Matrix<int>a=[1,2;3,4];MatrixViewMut<int>x=matrix_view_mut(a);MatrixViewMut<int>y=transpose_view_mut(a);Matrix<int>c=x*y;if(c[1,1]!=5){return 1;}if(c[2,2]!=25){return 2;}c[1,1]=99;if(a[1,1]!=1){return 3;}Matrix<int>d=a*a;if(d[2,2]!=22){return 4;}return 0;}",
    );
    assert_eq!(v23_execute(&instrument(&c.llvm, 3)).code(), Some(0));
    for source in [
        "Matrix<int> consume(Matrix<int>a){return a;}int main(){Matrix<int>a=[1];Matrix<int>c=a*consume(a);return 0;}",
        "Matrix<int> replace(ref mut Matrix<int>a){*a=[2];Matrix<int>b=[1];return b;}int main(){Matrix<int>a=[1];Matrix<int>c=a*replace(&mut a);return 0;}",
        "Matrix<int> consume(Matrix<int>a){return a;}int main(){Matrix<int>a=[1];MatrixView<int>v=matrix_view(a);Matrix<int>c=v*consume(a);return 0;}",
    ] {
        assert!(
            compile_source(&SourceFile::new("invalid.ae", source), &[]).is_err(),
            "{source}"
        );
    }
}

#[test]
fn vertical33_deterministic_dumps_and_constraint_order_abi() {
    for name in ["generic_int", "generic_double"] {
        let source = fs::read_to_string(program(&format!("v33_{name}.ae"))).unwrap();
        let a = compile(&source);
        let b = compile(&source);
        assert_eq!(a.dumps, b.dumps);
        assert_eq!(a.llvm, b.llvm);
        assert_eq!(
            a.llvm,
            compile(source.replace("Storable+Copy+Add+Mul+Zero", "Zero+Mul+Storable+Add+Copy"))
                .llvm
        );
        for text in [
            "MatrixMatrix",
            "output_rows",
            "output_columns",
            "contraction_extent",
            "Behavioral(",
            "AlgebraicValue",
            "Zero",
            "Concrete(",
        ] {
            assert!(a.dumps[&Emit::Hir].contains(text), "{text}");
        }
        for phase in [Emit::Mir, Emit::Ssa] {
            for text in [
                "MatrixMatrixKernel",
                "ShapeGuardPair",
                "SelectSourceExtent",
                "Contraction",
                "EmptyMatrixResultBypass",
                "AccumulatorInit",
                "InitializeNext",
                "YieldOwner",
            ] {
                assert!(a.dumps[&phase].contains(text), "{text}");
            }
        }
    }
}

#[test]
fn vertical33_cross_module_strided_products() {
    let c = compile_session(
        CompilationSession::discover(&module_program("v33_products")).unwrap(),
        &[],
    )
    .unwrap();
    assert_eq!(v23_execute(&instrument(&c.llvm, 2)).code(), Some(0));
}

#[test]
fn vertical33_composition_preserves_result_families() {
    let c = compile(
        "int main(){Matrix<int>a=[1,2;3,4];Matrix<int>b=[2;3];Matrix<int>c=a*b;Vector<int,Column>v=a*column(b,1);if(c[1,1]!=v[1]){return 1;}if(c[2,1]!=v[2]){return 2;}MatrixView<int>bt=transpose_view(b);Matrix<int>d=bt*a;Vector<int,Row>r=row(bt,1)*a;if(d[1,1]!=r[1]){return 3;}if(d[1,2]!=r[2]){return 4;}VectorView<int,Row>br=row(bt,1);VectorView<int,Column>bc=column(b,1);int s=br*bc;Matrix<int>e=bt*b;if(e[1,1]!=s){return 5;}Matrix<int>f=bc*br;if(rows(f)!=2){return 6;}return 0;}",
    );
    assert_eq!(v23_execute(&instrument(&c.llvm, 8)).code(), Some(0));
}

fn rows_body(k: &mut AlgebraicProductKernel) -> &mut Vec<ProductStep> {
    let ProductStep::For { body, .. } = &mut k.program[6] else {
        panic!()
    };
    body
}
fn cells(k: &mut AlgebraicProductKernel) -> &mut Vec<ProductStep> {
    let ProductStep::For { body, .. } = &mut rows_body(k)[0] else {
        panic!()
    };
    body
}
fn terms(k: &mut AlgebraicProductKernel) -> &mut Vec<ProductStep> {
    let ProductStep::For { body, .. } = &mut cells(k)[1] else {
        panic!()
    };
    body
}
#[allow(clippy::too_many_lines)]
fn corrupt(k: &mut AlgebraicProductKernel, case: usize) {
    use MathAxis::{Columns, Contraction, Rows};
    match case {
        0 => {
            k.program.remove(0);
        }
        1 => k.program.swap(0, 4),
        2 => k.program.swap(0, 5),
        3 => {
            if let ProductStep::ShapeGuardPair { right_axis, .. } = &mut k.program[0] {
                *right_axis = Columns;
            }
        }
        4..=6 => {
            if let ProductStep::SelectSourceExtent { source_axis, .. } = &mut k.program[case - 3] {
                *source_axis = if *source_axis == Rows { Columns } else { Rows };
            }
        }
        7 => {
            k.program[4] = ProductStep::EmptyMatrixResultBypass {
                rows: Rows,
                columns: Contraction,
            }
        }
        8 => {
            if let ProductStep::Math(MathStep::Allocate { extents, .. }) = &mut k.program[5] {
                extents.push(Contraction);
            }
        }
        9 => {
            k.program.remove(6);
        }
        10 => {
            rows_body(k).clear();
        }
        11 => {
            if let ProductStep::For { axis, .. } = &mut k.program[6] {
                *axis = Columns;
            }
        }
        12 => {
            if let ProductStep::For { axis, .. } = &mut rows_body(k)[0] {
                *axis = Rows;
            }
        }
        13 => {
            if let ProductStep::For { axis, .. } = &mut cells(k)[1] {
                *axis = Columns;
            }
        }
        14 | 15 => {
            if let ProductStep::Math(MathStep::StridedLoad { offset, .. }) =
                &mut terms(k)[case - 14]
            {
                offset[0].1 = MathStride::ColumnStride;
            }
        }
        16 | 17 => {
            if let ProductStep::Math(MathStep::StridedLoad { offset, .. }) =
                &mut terms(k)[case - 16]
            {
                offset.swap(0, 1);
                offset[0].0 = Rows;
            }
        }
        18 => {
            if let ProductStep::Math(MathStep::ScalarBinary { op, .. }) = &mut terms(k)[2] {
                *op = BinaryOp::AddIntegerChecked;
            }
        }
        19 => {
            if let ProductStep::Accumulate { op, .. } = &mut terms(k)[3] {
                *op = BinaryOp::MultiplyIntegerChecked;
            }
        }
        20 => {
            let ty = k.element_type;
            cells(k)[0] = ProductStep::AccumulatorInit {
                value: Operand::Int { value: 1, ty },
            };
        }
        21 => {
            let init = cells(k).remove(0);
            rows_body(k).insert(0, init);
        }
        22 => {
            cells(k).pop();
        }
        23 => cells(k).push(ProductStep::Math(MathStep::InitializeNext)),
        24 => {
            let store = cells(k).pop().unwrap();
            terms(k).push(store);
        }
        25 => k.program[7] = ProductStep::YieldScalar,
        26 => terms(k).swap(2, 3),
        27 => {
            let add = terms(k)[3].clone();
            terms(k).push(add);
        }
        28 => k.zero = None,
        29 => k.product_op = BinaryOp::AddIntegerChecked,
        30 => k.accumulate_op = Some(BinaryOp::MultiplyIntegerChecked),
        31 => {
            if let ProductStep::For { step, .. } = &mut rows_body(k)[0] {
                *step = 2;
            }
        }
        32 => {
            if let ProductStep::For { start, .. } = &mut cells(k)[1] {
                *start = 1;
            }
        }
        33 => {
            if let ProductStep::SelectSourceExtent { input, .. } = &mut k.program[1] {
                *input = MathInput::Right;
            }
        }
        34 => {
            if let ProductStep::SelectSourceExtent { input, .. } = &mut k.program[2] {
                *input = MathInput::Left;
            }
        }
        35 => {
            if let ProductStep::SelectSourceExtent { input, .. } = &mut k.program[3] {
                *input = MathInput::Right;
            }
        }
        36 => k.program.swap(6, 7),
        37 => {
            if let ProductStep::Math(MathStep::Allocate { size_trap, .. }) = &mut k.program[5] {
                *size_trap = aether_middle::TrapKind::ShapeMismatch;
            }
        }
        38 => {
            if let ProductStep::Math(MathStep::StridedLoad { input, .. }) = &mut terms(k)[0] {
                *input = MathInput::Right;
            }
        }
        39 => {
            if let ProductStep::Math(MathStep::StridedLoad { input, .. }) = &mut terms(k)[1] {
                *input = MathInput::Left;
            }
        }
        40 => {
            let ty = k.element_type;
            let z = Operand::Float {
                value: aether_frontend::FloatValue::Float64(1_u64 << 63),
                ty,
            };
            k.zero = Some(z.clone());
            cells(k)[0] = ProductStep::AccumulatorInit { value: z };
        }
        _ => unreachable!(),
    }
}

#[test]
#[allow(clippy::too_many_lines)]
fn vertical33_mir_ssa_independent_corruption_rejection() {
    use aether_middle::{Rvalue, SsaOp, build_ssa, lower_hir, verify_mir, verify_ssa};
    for scalar in ["int", "double"] {
        let source = format!(
            "Matrix<{scalar}> product(MatrixView<{scalar}>a,MatrixView<{scalar}>b,ref Matrix<{scalar}>owner){{return a*b;}}int main(){{Matrix<{scalar}>a=[1];Matrix<{scalar}>b=product(matrix_view(a),matrix_view(a),&a);return 0;}}"
        );
        let raw = lower_hir(
            analyze(parse_source(&SourceFile::new("corrupt.ae", source)).unwrap()).unwrap(),
        );
        let ssa = build_ssa(&verify_mir(raw.clone()).unwrap());
        for case in 0..46 {
            let mut m = raw.clone();
            let wrong_result = if case == 44 {
                std::sync::Arc::make_mut(&mut m.types).intern_vector(
                    aether_frontend::TypeId::INT64,
                    aether_frontend::Orientation::Row,
                )
            } else {
                std::sync::Arc::make_mut(&mut m.types).intern_matrix(aether_frontend::TypeId::BOOL)
            };
            let f = m
                .functions
                .iter_mut()
                .find(|f| {
                    f.blocks
                        .iter()
                        .flat_map(|b| &b.instructions)
                        .any(|i| matches!(i.value, Rvalue::AlgebraicProduct { .. }))
                })
                .unwrap();
            let wrong = f.parameters[2].local;
            let inst = f
                .blocks
                .iter_mut()
                .flat_map(|b| &mut b.instructions)
                .find(|i| matches!(i.value, Rvalue::AlgebraicProduct { .. }))
                .unwrap();
            let Rvalue::AlgebraicProduct {
                left,
                right,
                kernel,
            } = &mut inst.value
            else {
                panic!()
            };
            match case {
                41 => *left = Operand::Local(wrong),
                42 => *right = Operand::Local(wrong),
                43 => kernel.element_type = aether_frontend::TypeId::BOOL,
                44 | 45 => {
                    let aether_middle::PlaceBase::Local(local) = inst.destination.base else {
                        panic!()
                    };
                    f.locals[local.0 as usize].ty = wrong_result;
                }
                _ => corrupt(kernel, case),
            }
            assert!(verify_mir(m).is_err(), "MIR {scalar} {case}");
            let mut s = ssa.clone();
            let wrong_result = if case == 44 {
                std::sync::Arc::make_mut(&mut s.types).intern_vector(
                    aether_frontend::TypeId::INT64,
                    aether_frontend::Orientation::Row,
                )
            } else {
                std::sync::Arc::make_mut(&mut s.types).intern_matrix(aether_frontend::TypeId::BOOL)
            };
            let f = s
                .functions
                .iter_mut()
                .find(|f| {
                    f.blocks
                        .iter()
                        .flat_map(|b| &b.instructions)
                        .any(|i| matches!(i.op, SsaOp::AlgebraicProduct { .. }))
                })
                .unwrap();
            let wrong = f.parameters[2].value;
            let inst = f
                .blocks
                .iter_mut()
                .flat_map(|b| &mut b.instructions)
                .find(|i| matches!(i.op, SsaOp::AlgebraicProduct { .. }))
                .unwrap();
            let SsaOp::AlgebraicProduct {
                left,
                right,
                kernel,
            } = &mut inst.op
            else {
                panic!()
            };
            match case {
                41 => *left = aether_middle::SsaOperand::Value(wrong),
                42 => *right = aether_middle::SsaOperand::Value(wrong),
                43 => kernel.element_type = aether_frontend::TypeId::BOOL,
                44 | 45 => inst.ty = wrong_result,
                _ => corrupt(kernel, case),
            }
            assert!(verify_ssa(s).is_err(), "SSA {scalar} {case}");
        }
    }
}

#[test]
fn vertical33_allocation_traps_precede_element_access() {
    // Row-count, column-count byte overflow, and rows*columns count overflow.
    for fields in [
        vec!["_Left_Rows ="],
        vec!["_Right_Columns ="],
        vec!["_Left_Rows =", "_Right_Columns ="],
    ] {
        let c = compile("int main(){Matrix<int>a=[2];Matrix<int>b=[3];Matrix<int>c=a*b;return 0;}");
        let instrumented = instrument(&c.llvm, 3);
        let check = |status| {
            format!(
                "  %allocs = load i64, ptr @aether_heap_alloc_count\n  %loads = load i64, ptr @v33_load\n  %mul = load i64, ptr @v33_mul\n  %add = load i64, ptr @v33_add\n  %stores = load i64, ptr @v33_store\n  %n0 = or i64 %loads, %mul\n  %n1 = or i64 %n0, %add\n  %n2 = or i64 %n1, %stores\n  %no_ops = icmp eq i64 %n2, 0\n  %heap_ok = icmp eq i64 %allocs, 2\n  %ok = and i1 %heap_ok, %no_ops\n  %status = select i1 %ok, i32 {status}, i32 99\n  call void @exit(i32 %status)"
            )
        };
        let mut oversized = String::new();
        for line in instrumented.lines() {
            if line.contains("%vp")
                && line.contains(" = extractvalue")
                && fields.iter().any(|field| line.contains(field))
            {
                writeln!(
                    oversized,
                    "{} = add i64 -1, 0",
                    line.split(" = ").next().unwrap()
                )
                .unwrap();
            } else {
                writeln!(oversized, "{line}").unwrap();
            }
        }
        let old = "trap_allocation_size_overflow:\n  ; structured Aether trap: AllocationSizeOverflow\n  call void @llvm.trap()";
        assert!(oversized.contains(old));
        oversized = oversized.replace(
            old,
            &format!("trap_allocation_size_overflow:\n{}", check(75)),
        );
        oversized.push_str("\ndeclare void @exit(i32) noreturn\n");
        assert_eq!(v23_execute(&oversized).code(), Some(75));
        let mut failure = String::new();
        for line in instrumented.lines() {
            writeln!(failure, "{line}").unwrap();
            if line.trim().starts_with("; AlgebraicBegin ") {
                failure.push_str("  store i1 true, ptr @v33_fail_malloc\n");
            }
        }
        failure = failure.replace(
            "%alloc_ptr = call ptr @malloc(i64 %alloc_actual)",
            "%alloc_ptr = call ptr @v33_malloc(i64 %alloc_actual)",
        );
        let old = "; structured Aether trap: AllocationFailure\ncall void @llvm.trap()";
        assert!(failure.contains(old));
        failure = failure.replace(old, &check(76));
        failure.push_str("\n@v33_fail_malloc = internal global i1 false\ndeclare void @exit(i32) noreturn\ndefine ptr @v33_malloc(i64 %size) {\nentry:\n  %fail = load i1, ptr @v33_fail_malloc\n  br i1 %fail, label %failed, label %allocate\nfailed:\n  ret ptr null\nallocate:\n  %ptr = call ptr @malloc(i64 %size)\n  ret ptr %ptr\n}\n");
        assert_eq!(v23_execute(&failure).code(), Some(76));
    }
}

#[test]
fn vertical33_dynamic_mismatch_guard_dominates_empty_result() {
    for init in [
        "Matrix<int>a=[1,2,3];Matrix<int>b=[1;2;3;4];",
        "Vector<int,Column>ec=[];Vector<int,Row>r=[1,2,3];Matrix<int>a=ec*r;Matrix<int>b=[1;2;3;4];",
        "Matrix<int>a=[1,2,3];Vector<int,Column>c=[1,2,3,4];Vector<int,Row>er=[];Matrix<int>b=c*er;",
        "Vector<int,Column>ec=[];Vector<int,Row>r=[1,2,3];Vector<int,Column>c=[1,2,3,4];Vector<int,Row>er=[];Matrix<int>a=ec*r;Matrix<int>b=c*er;",
    ] {
        let c = compile(format!(
            "Matrix<int> product(MatrixView<int>a,MatrixView<int>b){{return a*b;}}int main(){{{init}Matrix<int>z=product(matrix_view(a),matrix_view(b));return 0;}}"
        ));
        assert_eq!(v23_execute(&c.llvm).signal(), Some(4));
        let checked=instrument(&c.llvm,2).replace("trap_shape_mismatch:\n", "trap_shape_mismatch:\n  %ml = load i64, ptr @v33_load\n  %mm = load i64, ptr @v33_mul\n  %ma = load i64, ptr @v33_add\n  %ms = load i64, ptr @v33_store\n  %mh = load i64, ptr @aether_heap_alloc_count\n  %mf = load i64, ptr @aether_heap_free_count\n  %mt0 = or i64 %ml, %mm\n  %mt1 = or i64 %mt0, %ma\n  %mt2 = or i64 %mt1, %ms\n  %mt3 = or i64 %mt2, %mf\n  %mz = icmp eq i64 %mt3, 0\n  %mhe = icmp eq i64 %mh, 2\n  %mok = and i1 %mz, %mhe\n  %mstatus = select i1 %mok, i32 0, i32 97\n  call void @exit(i32 %mstatus)\n")+"\ndeclare void @exit(i32)\n";
        assert_eq!(v23_execute(&checked).code(), Some(0), "{init}");
    }
}
