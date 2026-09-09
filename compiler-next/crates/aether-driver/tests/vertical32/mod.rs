//! V32 native, diagnostic, schedule-corruption and cost qualification.
use super::*;
use aether_middle::{
    BinaryOp, MathAxis, MathInput, MathStep, MathStride, Operand, ProductStep, VectorProductKernel,
};
use std::os::unix::process::ExitStatusExt;

fn compile(text: impl Into<String>) -> aether_driver::Compilation {
    compile_source(
        &SourceFile::new("v32.ae", text),
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
        ("m", "v32_mul"),
        ("p", "v32_add"),
        ("s", "v32_store"),
        ("l", "v32_load"),
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
            for (short, global) in counters {
                writeln!(out, "  %q{id}_{short}0 = load i64, ptr @{global}").unwrap();
            }
            region = Some((id, inner, matrix, row));
        }
        let Some((id, inner, matrix, row)) = &region else {
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
            writeln!(out, "  %q{id}_{short}n = load i64, ptr @v32_{global}\n  %q{id}_{short}next = add i64 %q{id}_{short}n, 1\n  store i64 %q{id}_{short}next, ptr @v32_{global}").unwrap();
        }
        if line.trim().starts_with("; AlgebraicEnd ") {
            if *matrix || *row {
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
            let extent = if *matrix || *row { "result" } else { "count" };
            writeln!(out, "  %q{id}_loads = mul i64 %q{id}_count, 2\n  %q{id}_nonempty = icmp ne i64 %q{id}_{extent}, 0\n  %q{id}_allocation = zext i1 %q{id}_nonempty to i64").unwrap();
            for (short, global) in counters {
                let expected = match short {
                    "m" => format!("%q{id}_count"),
                    "p" if *inner || *matrix || *row => format!("%q{id}_count"),
                    "l" => format!("%q{id}_loads"),
                    "a" if !inner => format!("%q{id}_allocation"),
                    "s" if !inner => format!("%q{id}_{extent}"),
                    _ => "0".into(),
                };
                writeln!(out, "  %q{id}_{short}1 = load i64, ptr @{global}\n  %q{id}_{short}delta = sub i64 %q{id}_{short}1, %q{id}_{short}0\n  %q{id}_{short}ok = icmp eq i64 %q{id}_{short}delta, {expected}\n  %q{id}_{short}old = load i1, ptr @v32_ok\n  %q{id}_{short}all = and i1 %q{id}_{short}old, %q{id}_{short}ok\n  store i1 %q{id}_{short}all, ptr @v32_ok").unwrap();
            }
            region = None;
        }
    }
    for global in ["mul", "add", "store", "load"] {
        writeln!(out, "@v32_{global} = internal global i64 0").unwrap();
    }
    out.push_str("@v32_ok = internal global i1 true\n");
    v23_heap_guard(&out, heap).replace("  %all_ok = and i1 %heap_ok, %result_ok", "  %v32_pass = load i1, ptr @v32_ok\n  %v32_both = and i1 %heap_ok, %v32_pass\n  %all_ok = and i1 %v32_both, %result_ok")
}

#[test]
fn vertical32_native_fixtures_and_exact_costs() {
    for (name, heap) in [
        ("matrix_column", 3),
        ("row_matrix", 3),
        ("matrix_column_strided", 3),
        ("row_matrix_strided", 3),
        ("generic_int", 3),
        ("generic_double", 3),
        ("zero_axes", 6),
    ] {
        let c = compile(fs::read_to_string(program(&format!("v32_{name}.ae"))).unwrap());
        for phase in [Emit::Mir, Emit::Ssa] {
            assert!(!c.dumps[&phase].contains("Behavioral("));
            assert!(!c.dumps[&phase].contains("AlgebraicValue"));
        }
        assert_eq!(
            v23_execute(&instrument(&c.llvm, heap)).code(),
            Some(0),
            "{name}"
        );
    }
}

#[test]
fn vertical32_all_readable_families_and_builtin_scalars() {
    for scalar in [
        "int8", "int16", "int32", "int64", "uint8", "uint16", "uint32", "uint64", "isize", "usize",
        "float32", "float64", "int", "float", "double",
    ] {
        let mut helpers = String::new();
        let mut body = format!(
            "int main(){{Matrix<{scalar}>a=[1,2;3,4];Vector<{scalar},Column>c=[2,3];Vector<{scalar},Row>r=[2,3];"
        );
        let matrices = [
            ("ref Matrix", "*", "&"),
            ("MatrixView", "", "matrix_view"),
            ("MatrixViewMut", "", "matrix_view_mut"),
        ];
        let vectors = [
            ("ref Vector", "*", "&"),
            ("VectorView", "", "vector_view"),
            ("VectorViewMut", "", "vector_view_mut"),
        ];
        for (i, (mf, me, ma)) in matrices.iter().enumerate() {
            for (j, (vf, ve, va)) in vectors.iter().enumerate() {
                let arg = |a: &str, n: &str| {
                    if a == "&" {
                        format!("&{n}")
                    } else {
                        format!("{a}({n})")
                    }
                };
                write!(helpers,"Vector<T,Column> mc{i}{j}<T:Storable+Copy+Add+Mul+Zero>({mf}<T>a,{vf}<T,Column>x){{return {me}a*{ve}x;}}Vector<T,Row> rm{i}{j}<T:Storable+Copy+Add+Mul+Zero>({vf}<T,Row>x,{mf}<T>a){{return {ve}x*{me}a;}}").unwrap();
                write!(body,"if(true){{Vector<{scalar},Column>y=mc{i}{j}({},{});if(y[1]!=8){{return 1;}}if(y[2]!=18){{return 2;}}}}if(true){{Vector<{scalar},Row>y=rm{i}{j}({},{});if(y[1]!=11){{return 3;}}if(y[2]!=16){{return 4;}}}}",arg(ma,"a"),arg(va,"c"),arg(va,"r"),arg(ma,"a")).unwrap();
            }
        }
        body.push_str(
            "if(a[2,2]!=4){return 5;}if(c[2]!=3){return 6;}if(r[2]!=3){return 7;}return 0;}",
        );
        let c = compile(helpers + &body);
        assert_eq!(
            v23_execute(&instrument(&c.llvm, 21)).code(),
            Some(0),
            "{scalar}"
        );
    }
}

#[test]
fn vertical32_parametric_constraints_diagnostics_and_forwarding() {
    for column in [true, false] {
        let (o, params, expr, args) = if column {
            (
                "Column",
                "MatrixView<T>a,VectorView<T,Column>x",
                "a*x",
                "a,x",
            )
        } else {
            ("Row", "VectorView<T,Row>x,MatrixView<T>a", "x*a", "x,a")
        };
        for missing in ["Storable", "Copy", "Add", "Mul", "Zero"] {
            let caps = ["Storable", "Copy", "Add", "Mul", "Zero"]
                .into_iter()
                .filter(|c| *c != missing)
                .collect::<Vec<_>>()
                .join("+");
            for forward in [false, true] {
                let body = if forward {
                    format!("good({args})")
                } else {
                    expr.into()
                };
                let source = format!(
                    "Vector<T,{o}> good<T:Storable+Copy+Add+Mul+Zero>({params}){{return {expr};}}Vector<T,{o}> bad<T:{caps}>({params}){{return {body};}}int main(){{return 0;}}"
                );
                let e = compile_source(&SourceFile::new("missing.ae", source), &[]).unwrap_err();
                assert!(
                    e.iter().any(|e| e.message.contains(missing)),
                    "{column} {forward} {missing}: {e:?}"
                );
            }
        }
    }
    for (body, code) in [
        (
            "Matrix<int>a=[1];Vector<int,Row>x=[1];Vector<int,Row>y=a*x;",
            "E0342",
        ),
        (
            "Matrix<int>a=[1];Vector<int,Column>x=[1];Vector<int,Column>y=x*a;",
            "E0342",
        ),
        ("Matrix<int>a=[1];Matrix<int>b=a*a;", "E0342"),
        ("Vector<int,Row>x=[1];Vector<int,Row>y=x*x;", "E0342"),
        ("Vector<int,Column>x=[1];Vector<int,Column>y=x*x;", "E0342"),
        (
            "Matrix<int>a=[1];Vector<double,Column>x=[1];Vector<double,Column>y=a*x;",
            "E0343",
        ),
        (
            "Matrix<int>a=[1];Vector<double,Row>x=[1];Vector<double,Row>y=x*a;",
            "E0343",
        ),
        (
            "Matrix<int>a=[1,2];Vector<int,Column>x=[1];Vector<int,Column>y=a*x;",
            "E0345",
        ),
        (
            "Matrix<int>a=[1;2];Vector<int,Row>x=[1];Vector<int,Row>y=x*a;",
            "E0345",
        ),
        // Empty result must not suppress a known incompatible contraction.
        (
            "Vector<int,Column>c=[];Vector<int,Row>r=[1,2];Matrix<int>a=c*r;Vector<int,Column>x=[1];Vector<int,Column>y=a*x;",
            "E0345",
        ),
        (
            "Vector<int,Column>c=[1,2];Vector<int,Row>r=[];Matrix<int>a=c*r;Vector<int,Row>x=[1];Vector<int,Row>y=x*a;",
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
}

#[test]
fn vertical32_integer_product_and_accumulator_overflow() {
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
        for column in [true, false] {
            for sum in [false, true] {
                let (o, expr, m, v) = if column {
                    (
                        "Column",
                        "a*x",
                        if sum {
                            format!("[{max},1]")
                        } else {
                            format!("[{max}]")
                        },
                        if sum { "[1,1]" } else { "[2]" },
                    )
                } else {
                    (
                        "Row",
                        "x*a",
                        if sum {
                            format!("[{max};1]")
                        } else {
                            format!("[{max}]")
                        },
                        if sum { "[1,1]" } else { "[2]" },
                    )
                };
                let c = compile(format!(
                    "int main(){{Matrix<{ty}>a={m};Vector<{ty},{o}>x={v};Vector<{ty},{o}>y={expr};return 0;}}"
                ));
                assert_eq!(
                    v23_execute(&c.llvm).signal(),
                    Some(4),
                    "{ty} {column} {sum}"
                );
                assert!(c.llvm.contains("mul.with.overflow"));
                assert!(c.llvm.contains("add.with.overflow"));
            }
        }
    }
    for ty in ["int8", "int64"] {
        let c = compile(format!(
            "int main(){{Matrix<{ty}>a=[-2,3;4,-5];Vector<{ty},Column>c=[-1,2];Vector<{ty},Row>r=[-1,2];Vector<{ty},Column>x=a*c;Vector<{ty},Row>y=r*a;if(x[1]!=8){{return 1;}}if(x[2]!=-14){{return 2;}}if(y[1]!=10){{return 3;}}if(y[2]!=-13){{return 4;}}return 0;}}"
        ));
        assert_eq!(v23_execute(&instrument(&c.llvm, 5)).code(), Some(0));
    }
}

#[test]
fn vertical32_ieee_order_zero_infinity_nan() {
    for (ty, large, llvm_ty) in [
        ("float32", "16777216", "float"),
        ("float64", "9007199254740992", "double"),
    ] {
        for column in [true, false] {
            let o = if column { "Column" } else { "Row" };
            let expr = if column { "a*x" } else { "x*a" };
            let order = if column {
                format!("[{large},1,-{large};{large},1,-{large}]")
            } else {
                format!("[{large},{large};1,1;-{large},-{large}]")
            };
            let c = compile(format!(
                "int main(){{Matrix<{ty}>a={order};Vector<{ty},{o}>x=[1,1,1];Vector<{ty},{o}>y={expr};if(y[1]!=0){{return 1;}}if(y[2]!=0){{return 2;}}return 0;}}"
            ));
            assert_eq!(v23_execute(&instrument(&c.llvm, 3)).code(), Some(0));
            for (value, check) in [
                ("-0.0", "if(y[1]!=0){return 1;}if(1/y[1]<0){return 2;}"),
                ("1.0/0.0", "if(y[1]!=v){return 3;}"),
                ("0.0/0.0", "if(y[1]==y[1]){return 4;}"),
            ] {
                let c = compile(format!(
                    "int main(){{{ty} v={value};Matrix<{ty}>a=[v];Vector<{ty},{o}>x=[1];Vector<{ty},{o}>y={expr};{check}return 0;}}"
                ));
                assert_eq!(
                    v23_execute(&instrument(&c.llvm, 3)).code(),
                    Some(0),
                    "{ty} {column} {value}"
                );
                let region = c
                    .llvm
                    .split("; AlgebraicBegin ")
                    .nth(1)
                    .unwrap()
                    .split("; AlgebraicEnd ")
                    .next()
                    .unwrap();
                let mul = region.find(&format!(" = fmul {llvm_ty}")).unwrap();
                let add = region.find(&format!(" = fadd {llvm_ty}")).unwrap();
                assert!(mul < add);
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
            }
        }
    }
}

fn outer(kernel: &mut VectorProductKernel) -> &mut Vec<ProductStep> {
    let ProductStep::For { body, .. } = &mut kernel.program[5] else {
        panic!()
    };
    body
}
fn inner(kernel: &mut VectorProductKernel) -> &mut Vec<ProductStep> {
    let ProductStep::For { body, .. } = &mut outer(kernel)[1] else {
        panic!()
    };
    body
}
#[allow(clippy::too_many_lines)]
fn corrupt(kernel: &mut VectorProductKernel, case: usize) {
    let result = if kernel.matrix_input() == Some(MathInput::Left) {
        MathAxis::Rows
    } else {
        MathAxis::Columns
    };
    let contraction = if result == MathAxis::Rows {
        MathAxis::Columns
    } else {
        MathAxis::Rows
    };
    match case {
        0 => {
            kernel.program.remove(0);
        }
        1 => kernel.program.swap(0, 4),
        2 => {
            if let ProductStep::SelectSourceExtent { source_axis, .. } = &mut kernel.program[1] {
                *source_axis = contraction;
            }
        }
        3 => {
            if let ProductStep::SelectSourceExtent { source_axis, .. } = &mut kernel.program[2] {
                *source_axis = result;
            }
        }
        4 => kernel.program[3] = ProductStep::EmptyResultBypass { axis: contraction },
        5 => {
            if let ProductStep::Math(MathStep::Allocate { extents, .. }) = &mut kernel.program[4] {
                *extents = vec![contraction];
            }
        }
        6 => {
            kernel.program.remove(5);
        }
        7 => {
            if let ProductStep::For { axis, .. } = &mut kernel.program[5] {
                *axis = contraction;
            }
        }
        8 => {
            if let ProductStep::For { axis, .. } = &mut outer(kernel)[1] {
                *axis = result;
            }
        }
        9 => {
            if let ProductStep::For { step, .. } = &mut kernel.program[5] {
                *step = 2;
            }
        }
        10 => {
            if let ProductStep::For { step, .. } = &mut outer(kernel)[1] {
                *step = 2;
            }
        }
        11 | 12 => {
            let matrix = usize::from(kernel.matrix_input() == Some(MathInput::Right));
            let index = if case == 11 { matrix } else { 1 - matrix };
            if let ProductStep::Math(MathStep::StridedLoad { offset, .. }) =
                &mut inner(kernel)[index]
            {
                offset[0].1 = if case == 11 {
                    MathStride::ColumnStride
                } else {
                    MathStride::RowStride
                };
            }
        }
        13 => {
            if let ProductStep::Math(MathStep::ScalarBinary { op, .. }) = &mut inner(kernel)[2] {
                *op = BinaryOp::AddIntegerChecked;
            }
        }
        14 => {
            if let ProductStep::Accumulate { op, .. } = &mut inner(kernel)[3] {
                *op = BinaryOp::MultiplyIntegerChecked;
            }
        }
        15 => {
            let ty = kernel.element_type;
            outer(kernel)[0] = ProductStep::AccumulatorInit {
                value: Operand::Int { value: 1, ty },
            };
        }
        16 => {
            outer(kernel).pop();
        }
        17 => outer(kernel).push(ProductStep::Math(MathStep::InitializeNext)),
        18 => kernel.program[6] = ProductStep::YieldScalar,
        19 => {
            outer(kernel).remove(0);
        }
        20 => {
            let body = inner(kernel);
            body.push(body[3].clone());
        }
        21 => kernel.zero = None,
        22 => kernel.product_op = BinaryOp::AddIntegerChecked,
        23 => kernel.accumulate_op = Some(BinaryOp::MultiplyIntegerChecked),
        24 => {
            if let ProductStep::ShapeGuardPair { left_axis, .. } = &mut kernel.program[0] {
                *left_axis = MathAxis::Rows;
            }
        }
        25 => {
            if let ProductStep::Math(MathStep::Allocate { size_trap, .. }) = &mut kernel.program[4]
            {
                *size_trap = aether_middle::TrapKind::ShapeMismatch;
            }
        }
        26 => {
            inner(kernel).swap(0, 1);
        }
        27 => {
            if let ProductStep::SelectSourceExtent { input, .. } = &mut kernel.program[1] {
                *input = if *input == MathInput::Left {
                    MathInput::Right
                } else {
                    MathInput::Left
                };
            }
        }
        _ => unreachable!(),
    }
}

#[test]
fn vertical32_mir_ssa_independent_corruption_rejection() {
    use aether_middle::{Rvalue, SsaOp, build_ssa, lower_hir, verify_mir, verify_ssa};
    for column in [true, false] {
        let (o, expr) = if column {
            ("Column", "a*x")
        } else {
            ("Row", "x*a")
        };
        let source = format!(
            "Vector<int,{o}> product(MatrixView<int>a,VectorView<int,{o}>x){{return {expr};}}int main(){{Matrix<int>a=[1];Vector<int,{o}>x=[2];Vector<int,{o}>y=product(matrix_view(a),vector_view(x));return 0;}}"
        );
        let raw = lower_hir(
            analyze(parse_source(&SourceFile::new("corrupt.ae", source)).unwrap()).unwrap(),
        );
        let ssa = build_ssa(&verify_mir(raw.clone()).unwrap());
        for case in 0..30 {
            let mut m = raw.clone();
            let f = m
                .functions
                .iter_mut()
                .find(|f| {
                    f.blocks
                        .iter()
                        .flat_map(|b| &b.instructions)
                        .any(|i| matches!(i.value, Rvalue::VectorProduct { .. }))
                })
                .unwrap();
            let wrong = f.parameters[usize::from(column)].local;
            let inst = f
                .blocks
                .iter_mut()
                .flat_map(|b| &mut b.instructions)
                .find(|i| matches!(i.value, Rvalue::VectorProduct { .. }))
                .unwrap();
            let Rvalue::VectorProduct { left, kernel, .. } = &mut inst.value else {
                panic!()
            };
            if case == 28 {
                *left = Operand::Local(wrong);
            } else if case == 29 {
                kernel.element_type = aether_frontend::TypeId::BOOL;
            } else {
                corrupt(kernel, case);
            }
            assert!(verify_mir(m).is_err(), "MIR {column} {case}");
            let mut s = ssa.clone();
            let f = s
                .functions
                .iter_mut()
                .find(|f| {
                    f.blocks
                        .iter()
                        .flat_map(|b| &b.instructions)
                        .any(|i| matches!(i.op, SsaOp::VectorProduct { .. }))
                })
                .unwrap();
            let wrong = f.parameters[usize::from(column)].value;
            let inst = f
                .blocks
                .iter_mut()
                .flat_map(|b| &mut b.instructions)
                .find(|i| matches!(i.op, SsaOp::VectorProduct { .. }))
                .unwrap();
            let SsaOp::VectorProduct { left, kernel, .. } = &mut inst.op else {
                panic!()
            };
            if case == 28 {
                *left = aether_middle::SsaOperand::Value(wrong);
            } else if case == 29 {
                kernel.element_type = aether_frontend::TypeId::BOOL;
            } else {
                corrupt(kernel, case);
            }
            assert!(verify_ssa(s).is_err(), "SSA {column} {case}");
        }
    }
}

#[test]
fn vertical32_dynamic_mismatch_guard_dominates_even_empty_result() {
    for column in [true, false] {
        for empty in [false, true] {
            let (o, expr) = if column {
                ("Column", "a*x")
            } else {
                ("Row", "x*a")
            };
            let init = if empty {
                if column {
                    "Vector<int,Column>c=[];Vector<int,Row>r=[1,2];Matrix<int>a=c*r;"
                } else {
                    "Vector<int,Column>c=[1,2];Vector<int,Row>r=[];Matrix<int>a=c*r;"
                }
            } else if column {
                "Matrix<int>a=[1,2];"
            } else {
                "Matrix<int>a=[1;2];"
            };
            let c = compile(format!(
                "Vector<int,{o}> product(MatrixView<int>a,VectorView<int,{o}>x){{return {expr};}}int main(){{{init}Vector<int,{o}>x=[1];Vector<int,{o}>y=product(matrix_view(a),vector_view(x));return 0;}}"
            ));
            assert_eq!(v23_execute(&c.llvm).signal(), Some(4));
            let instrumented = instrument(&c.llvm, 2);
            let instrumented=instrumented.replace("trap_shape_mismatch:\n", "trap_shape_mismatch:\n  %mload = load i64, ptr @v32_load\n  %mmul = load i64, ptr @v32_mul\n  %madd = load i64, ptr @v32_add\n  %mstore = load i64, ptr @v32_store\n  %mheap = load i64, ptr @aether_heap_alloc_count\n  %mfree = load i64, ptr @aether_heap_free_count\n  %msum0 = or i64 %mload, %mmul\n  %msum1 = or i64 %msum0, %madd\n  %msum = or i64 %msum1, %mstore\n  %mzero = icmp eq i64 %msum, 0\n  %mheq = icmp eq i64 %mheap, 2\n  %mfeq = icmp eq i64 %mfree, 0\n  %mhf = and i1 %mheq, %mfeq\n  %mok = and i1 %mzero, %mhf\n  %mstatus = select i1 %mok, i32 0, i32 97\n  call void @exit(i32 %mstatus)\n")+"\ndeclare void @exit(i32)\n";
            assert_eq!(
                v23_execute(&instrumented).code(),
                Some(0),
                "{column} {empty}"
            );
        }
    }
}

#[test]
fn vertical32_alias_evaluation_temporaries_and_nonconsuming_owners() {
    let c = compile(
        "Matrix<int> make_matrix(){Matrix<int>a=[2,3;4,5];return a;}Vector<int,Column> make_column(){Vector<int,Column>x=[2,3];return x;}Vector<int,Row> make_row(){Vector<int,Row>x=[2,3];return x;}int change(ref mut Matrix<int>a){(*a)[1,1]=7;return 1;}int change_row(ref mut Vector<int,Row>r){(*r)[1]=7;return 1;}int main(){Matrix<int>a=[2,3;4,5];Vector<int,Column>x=[2,3];Vector<int,Row>r=[2,3];Vector<int,Column>p=make_matrix()*make_column();Vector<int,Row>q=make_row()*make_matrix();if(p[1]!=13){return 1;}if(q[1]!=16){return 2;}Vector<int,Column>s=a*(change(&mut a)*x);if(s[1]!=23){return 3;}Vector<int,Row>t=r*(change_row(&mut r)*a);if(t[1]!=61){return 4;}if(a[1,1]!=7){return 5;}if(r[1]!=7){return 6;}return 0;}",
    );
    assert_eq!(v23_execute(&c.llvm).code(), Some(0));
    // Side effects record evaluation order independently of arithmetic results.
    let c = compile(
        "Matrix<int> lhs(ref mut int s){*s=*s*10+1;Matrix<int>a=[2];return a;}Vector<int,Column> rhs(ref mut int s){*s=*s*10+2;Vector<int,Column>x=[3];return x;}Vector<int,Row> left_row(ref mut int s){*s=*s*10+1;Vector<int,Row>x=[3];return x;}Matrix<int> right_matrix(ref mut int s){*s=*s*10+2;Matrix<int>a=[2];return a;}int main(){int s=0;Vector<int,Column>c=lhs(&mut s)*rhs(&mut s);if(s!=12){return 1;}s=0;Vector<int,Row>r=left_row(&mut s)*right_matrix(&mut s);if(s!=12){return 2;}return 0;}",
    );
    assert_eq!(v23_execute(&c.llvm).code(), Some(0));
    for source in [
        "Vector<int,Column> consume(Matrix<int>a){Vector<int,Column>x=[1];return x;}int main(){Matrix<int>a=[1];Vector<int,Column>x=a*consume(a);return 0;}",
        "Matrix<int> consume(Vector<int,Row>x){Matrix<int>a=[1];return a;}int main(){Vector<int,Row>x=[1];Vector<int,Row>y=x*consume(x);return 0;}",
        "Vector<int,Column> replace(ref mut Matrix<int>a){*a=[2];Vector<int,Column>x=[1];return x;}int main(){Matrix<int>a=[1];Vector<int,Column>x=a*replace(&mut a);return 0;}",
        "Matrix<int> replace(ref mut Vector<int,Row>x){*x=[2];Matrix<int>a=[1];return a;}int main(){Vector<int,Row>x=[1];Vector<int,Row>y=x*replace(&mut x);return 0;}",
    ] {
        assert!(
            compile_source(&SourceFile::new("invalidated.ae", source), &[]).is_err(),
            "{source}"
        );
    }
}

#[test]
fn vertical32_deterministic_dumps_and_constraint_order_abi() {
    for name in ["generic_int", "generic_double"] {
        let source = fs::read_to_string(program(&format!("v32_{name}.ae"))).unwrap();
        let a = compile(&source);
        let b = compile(&source);
        assert_eq!(a.dumps, b.dumps);
        assert_eq!(a.llvm, b.llvm);
        let reordered =
            compile(source.replace("Storable+Copy+Add+Mul+Zero", "Zero+Mul+Storable+Add+Copy"));
        assert_eq!(a.llvm, reordered.llvm);
        for text in [
            "VectorAlgebraicProduct",
            "MatrixVector",
            "shape_check",
            "result_extent",
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
                "ShapeGuardPair",
                "SelectSourceExtent",
                "EmptyResultBypass",
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
fn vertical32_cross_module_strided_products() {
    let c = compile_session(
        CompilationSession::discover(&module_program("v32_products")).unwrap(),
        &[],
    )
    .unwrap();
    assert_eq!(v23_execute(&instrument(&c.llvm, 3)).code(), Some(0));
}

#[test]
fn vertical32_allocation_traps_precede_element_access() {
    for column in [true, false] {
        let (o, expr, result_field) = if column {
            ("Column", "a*x", "_Left_Rows =")
        } else {
            ("Row", "x*a", "_Right_Columns =")
        };
        let c = compile(format!(
            "int main(){{Matrix<int>a=[2];Vector<int,{o}>x=[3];Vector<int,{o}>y={expr};return 0;}}"
        ));
        let instrumented = instrument(&c.llvm, 3);
        let check = |status| {
            format!(
                "  %allocs = load i64, ptr @aether_heap_alloc_count\n  %loads = load i64, ptr @v32_load\n  %mul = load i64, ptr @v32_mul\n  %add = load i64, ptr @v32_add\n  %stores = load i64, ptr @v32_store\n  %n0 = or i64 %loads, %mul\n  %n1 = or i64 %n0, %add\n  %n2 = or i64 %n1, %stores\n  %no_ops = icmp eq i64 %n2, 0\n  %heap_ok = icmp eq i64 %allocs, 2\n  %ok = and i1 %heap_ok, %no_ops\n  %status = select i1 %ok, i32 {status}, i32 99\n  call void @exit(i32 %status)"
            )
        };
        let mut oversized = String::new();
        for line in instrumented.lines() {
            if line.contains("%vp")
                && line.contains(" = extractvalue")
                && line.contains(result_field)
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
                failure.push_str("  store i1 true, ptr @v32_fail_malloc\n");
            }
        }
        failure = failure.replace(
            "%alloc_ptr = call ptr @malloc(i64 %alloc_actual)",
            "%alloc_ptr = call ptr @v32_malloc(i64 %alloc_actual)",
        );
        let old = "; structured Aether trap: AllocationFailure\ncall void @llvm.trap()";
        assert!(failure.contains(old));
        failure = failure.replace(old, &check(76));
        failure.push_str("\n@v32_fail_malloc = internal global i1 false\ndeclare void @exit(i32) noreturn\ndefine ptr @v32_malloc(i64 %size) {\nentry:\n  %fail = load i1, ptr @v32_fail_malloc\n  br i1 %fail, label %failed, label %allocate\nfailed:\n  ret ptr null\nallocate:\n  %ptr = call ptr @malloc(i64 %size)\n  ret ptr %ptr\n}\n");
        assert_eq!(v23_execute(&failure).code(), Some(76));
    }
}

#[test]
fn vertical32_integer_zero_axes_and_shared_projections() {
    let source = fs::read_to_string(program("v32_zero_axes.ae"))
        .unwrap()
        .replace("double", "int")
        .replace("if(1/ac[1]<0){return 5;}", "")
        .replace("if(1/rb[2]<0){return 9;}", "");
    let c = compile(source);
    assert_eq!(v23_execute(&instrument(&c.llvm, 6)).code(), Some(0));
    let c = compile(
        "int main(){Matrix<int>a=[1,2;3,4];Vector<int,Row>r=row(a,1)*a;Vector<int,Column>c=a*column(a,2);if(r[1]!=7){return 1;}if(r[2]!=10){return 2;}if(c[1]!=10){return 3;}if(c[2]!=22){return 4;}return 0;}",
    );
    assert_eq!(v23_execute(&instrument(&c.llvm, 3)).code(), Some(0));
}
