//! V31 native, diagnostic, schedule-corruption and cost qualification.
use super::*;
use aether_middle::{
    BinaryOp, MathAxis, MathInput, MathStep, MathStride, Operand, ProductStep, VectorProductKernel,
};
use std::os::unix::process::ExitStatusExt;

fn compile(text: impl Into<String>) -> aether_driver::Compilation {
    compile_source(
        &SourceFile::new("v31.ae", text),
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
        ("m", "v31_mul"),
        ("p", "v31_add"),
        ("s", "v31_store"),
        ("l", "v31_load"),
    ];
    let mut out = String::new();
    let mut region = None;
    for line in llvm.lines() {
        writeln!(out, "{line}").unwrap();
        if let Some(rest) = line.trim().strip_prefix("; AlgebraicBegin ") {
            let id = rest.split_whitespace().next().unwrap().to_owned();
            let inner = rest.contains("ReductionKernel");
            for (short, global) in counters {
                writeln!(out, "  %q{id}_{short}0 = load i64, ptr @{global}").unwrap();
            }
            region = Some((id, inner));
        }
        let Some((id, inner)) = &region else {
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
            writeln!(out, "  %q{id}_{short}n = load i64, ptr @v31_{global}\n  %q{id}_{short}next = add i64 %q{id}_{short}n, 1\n  store i64 %q{id}_{short}next, ptr @v31_{global}").unwrap();
        }
        if line.trim().starts_with("; AlgebraicEnd ") {
            if *inner {
                writeln!(out, "  %q{id}_count = add i64 %vp{id}_Left_Dimension, 0").unwrap();
            } else {
                writeln!(
                    out,
                    "  %q{id}_count = mul i64 %vp{id}_Left_Dimension, %vp{id}_Right_Dimension"
                )
                .unwrap();
            }
            writeln!(out, "  %q{id}_loads = mul i64 %q{id}_count, 2\n  %q{id}_nonempty = icmp ne i64 %q{id}_count, 0\n  %q{id}_allocation = zext i1 %q{id}_nonempty to i64").unwrap();
            for (short, global) in counters {
                let expected = match short {
                    "m" => format!("%q{id}_count"),
                    "p" if *inner => format!("%q{id}_count"),
                    "l" => format!("%q{id}_loads"),
                    "a" if !inner => format!("%q{id}_allocation"),
                    "s" if !inner => format!("%q{id}_count"),
                    _ => "0".into(),
                };
                writeln!(out, "  %q{id}_{short}1 = load i64, ptr @{global}\n  %q{id}_{short}delta = sub i64 %q{id}_{short}1, %q{id}_{short}0\n  %q{id}_{short}ok = icmp eq i64 %q{id}_{short}delta, {expected}\n  %q{id}_{short}old = load i1, ptr @v31_ok\n  %q{id}_{short}all = and i1 %q{id}_{short}old, %q{id}_{short}ok\n  store i1 %q{id}_{short}all, ptr @v31_ok").unwrap();
            }
            region = None;
        }
    }
    for global in ["mul", "add", "store", "load"] {
        writeln!(out, "@v31_{global} = internal global i64 0").unwrap();
    }
    out.push_str("@v31_ok = internal global i1 true\n");
    v23_heap_guard(&out, heap).replace("  %all_ok = and i1 %heap_ok, %result_ok", "  %v31_pass = load i1, ptr @v31_ok\n  %v31_both = and i1 %heap_ok, %v31_pass\n  %all_ok = and i1 %v31_both, %result_ok")
}

#[test]
fn vertical31_native_fixtures_and_exact_costs() {
    for (name, heap) in [
        ("inner_concrete", 2),
        ("inner_int", 2),
        ("inner_double", 2),
        ("inner_strided", 3),
        ("outer_concrete", 3),
        ("outer_generic", 3),
        ("outer_empty", 2),
    ] {
        let c = compile(fs::read_to_string(program(&format!("v31_{name}.ae"))).unwrap());
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
fn vertical31_all_readable_families_and_builtin_scalars() {
    for scalar in [
        "int8", "int16", "int32", "int64", "uint8", "uint16", "uint32", "uint64", "isize", "usize",
        "float32", "float64", "int", "float", "double",
    ] {
        let mut helpers = String::new();
        let mut body =
            format!("int main(){{Vector<{scalar},Row>r=[2,3];Vector<{scalar},Column>c=[4,5];");
        let forms = [
            ("ref Vector", "*", "&"),
            ("VectorView", "", "vector_view"),
            ("VectorViewMut", "", "vector_view_mut"),
        ];
        for (i, (lf, le, la)) in forms.iter().enumerate() {
            for (j, (rf, re, ra)) in forms.iter().enumerate() {
                let arg = |a: &str, name: &str| {
                    if a == "&" {
                        format!("&{name}")
                    } else {
                        format!("{a}({name})")
                    }
                };
                // Owning signatures independently require Storable; view-only inner does not.
                let storage = if i == 0 || j == 0 { "Storable+" } else { "" };
                write!(helpers,"T inner{i}{j}<T:{storage}Copy+Add+Mul+Zero>({lf}<T,Row>a,{rf}<T,Column>b){{return {le}a*{re}b;}}Matrix<T> product{i}{j}<T:Storable+Copy+Mul>({lf}<T,Column>a,{rf}<T,Row>b){{return {le}a*{re}b;}}").unwrap();
                write!(body,"if(inner{i}{j}({}, {})!=23){{return 1;}}if(true){{Matrix<{scalar}>m=product{i}{j}({},{});if(m[2,2]!=15){{return 2;}}}}",arg(la,"r"),arg(ra,"c"),arg(la,"c"),arg(ra,"r")).unwrap();
            }
        }
        body.push_str("return 0;}");
        let c = compile(helpers + &body);
        assert_eq!(
            v23_execute(&instrument(&c.llvm, 11)).code(),
            Some(0),
            "{scalar}"
        );
    }
}

#[test]
fn vertical31_parametric_constraints_diagnostics_and_forwarding() {
    for missing in ["Copy", "Add", "Mul", "Zero"] {
        let caps = ["Copy", "Add", "Mul", "Zero"]
            .into_iter()
            .filter(|c| *c != missing)
            .collect::<Vec<_>>()
            .join("+");
        for forward in [false, true] {
            let callee = "T good<T:Copy+Add+Mul+Zero>(VectorView<T,Row>a,VectorView<T,Column>b){return a*b;}";
            let body = if forward { "good(a,b)" } else { "a*b" };
            let source = format!(
                "{callee}T bad<T:{caps}>(VectorView<T,Row>a,VectorView<T,Column>b){{return {body};}}int main(){{return 0;}}"
            );
            let e = compile_source(&SourceFile::new("missing.ae", source), &[]).unwrap_err();
            assert!(e.iter().any(|e| e.message.contains(missing)), "{e:?}");
        }
    }
    for missing in ["Storable", "Copy", "Mul"] {
        let caps = ["Storable", "Copy", "Mul"]
            .into_iter()
            .filter(|c| *c != missing)
            .collect::<Vec<_>>()
            .join("+");
        for body in ["a*b", "good(a,b)"] {
            let source = format!(
                "Matrix<T> good<T:Storable+Copy+Mul>(VectorView<T,Column>a,VectorView<T,Row>b){{return a*b;}}Matrix<T> bad<T:{caps}>(VectorView<T,Column>a,VectorView<T,Row>b){{return {body};}}int main(){{return 0;}}"
            );
            let e = compile_source(&SourceFile::new("missing.ae", source), &[]).unwrap_err();
            assert!(e.iter().any(|e| e.message.contains(missing)), "{e:?}");
        }
    }
    for (ty, value, valid) in [
        ("int", "1", true),
        ("double", "1.5", true),
        ("bool", "true", false),
        ("Buffer<int>", "Buffer<int>(1,2)", false),
    ] {
        let source = format!(
            "T keep<T:Zero>(T a){{return a;}}int main(){{{ty} a={value};{ty} b=keep(a);return 0;}}"
        );
        assert_eq!(
            compile_source(&SourceFile::new("zero.ae", source), &[]).is_ok(),
            valid
        );
    }
    for (body, code) in [
        ("Vector<int,Row>a=[1];int x=a*a;", "E0342"),
        ("Vector<int,Column>a=[1];int x=a*a;", "E0342"),
        (
            "Vector<int,Row>a=[1];Vector<double,Column>b=[1];double x=a*b;",
            "E0343",
        ),
        (
            "Vector<int,Row>a=[1];Vector<int,Column>b=[1,2];int x=a*b;",
            "E0345",
        ),
        (
            "Vector<bool,Row>a=[true];Vector<bool,Column>b=[true];bool x=a*b;",
            "E0346",
        ),
        (
            "Vector<int,Row>a=[1];Matrix<int>b=[1];Matrix<int>x=a*b;",
            "E0342",
        ),
        (
            "Matrix<int>a=[1];Vector<int,Column>b=[1];Matrix<int>x=a*b;",
            "E0342",
        ),
        ("Matrix<int>a=[1];Matrix<int>x=a*a;", "E0342"),
    ] {
        let e = compile_source(
            &SourceFile::new("bad.ae", format!("int main(){{{body}return 0;}}")),
            &[],
        )
        .unwrap_err();
        assert!(e.iter().any(|e| e.code == code), "{e:?}");
    }
}

#[test]
fn vertical31_integer_product_and_accumulator_overflow() {
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
        for case in 0..3 {
            let (r, c, result, expr) = match case {
                0 => (format!("[{max}]"), "[2]", ty.to_owned(), "r*c"),
                1 => (format!("[{max},1]"), "[1,1]", ty.to_owned(), "r*c"),
                _ => (format!("[{max}]"), "[2]", format!("Matrix<{ty}>"), "c*r"),
            };
            let source = format!(
                "int main(){{Vector<{ty},Row>r={r};Vector<{ty},Column>c={c};{result} x={expr};return 0;}}"
            );
            let compiled = compile(source);
            assert_eq!(v23_execute(&compiled.llvm).signal(), Some(4), "{ty} {case}");
            assert!(compiled.llvm.contains("mul.with.overflow"));
            if case == 1 {
                assert!(compiled.llvm.contains("add.with.overflow"));
            }
        }
    }
}

#[test]
fn vertical31_ieee_strict_order_zero_infinity_nan() {
    for (ty, large, llvm_ty) in [
        ("float32", "16777216", "float"),
        ("float64", "9007199254740992", "double"),
    ] {
        let source = format!(
            r"T inner<T:Copy+Add+Mul+Zero>(VectorView<T,Row>a,VectorView<T,Column>b){{return a*b;}}
int main(){{Vector<{ty},Row>e=[];Vector<{ty},Column>ec=[];{ty} z=inner(vector_view(e),vector_view(ec));if(1.0/z<0.0){{return 1;}}if(z!=0.0){{return 2;}}
Vector<{ty},Row>r=[-0.0];Vector<{ty},Column>c=[1.0];{ty} v=r*c;if(1.0/v<0.0){{return 3;}}Matrix<{ty}>o=c*r;if(1.0/o[1,1]>0.0){{return 4;}}
Vector<{ty},Row>a=[{large},1.0,-{large}];Vector<{ty},Column>b=[1.0,1.0,1.0];if(a*b!=0.0){{return 5;}}
{ty} inf=1.0/0.0;Vector<{ty},Row>ir=[inf];{ty} iv=ir*c;if(iv!=inf){{return 6;}}Matrix<{ty}>io=c*ir;if(io[1,1]!=inf){{return 7;}}
{ty} nan=0.0/0.0;Vector<{ty},Row>nr=[nan];{ty} nv=nr*c;if(nv==nv){{return 8;}}Matrix<{ty}>no=c*nr;if(no[1,1]==no[1,1]){{return 9;}}return 0;}}"
        );
        let c = compile(source);
        assert_eq!(v23_execute(&instrument(&c.llvm, 9)).code(), Some(0), "{ty}");
        for region in c.llvm.split("; AlgebraicBegin ").skip(1) {
            let region = region.split("; AlgebraicEnd ").next().unwrap();
            assert!(region.contains(&format!(" = fmul {llvm_ty}")));
            if region.contains("ReductionKernel") {
                assert!(region.contains(&format!(" = fadd {llvm_ty}")));
            } else {
                assert!(!region.contains(" = fadd "));
            }
            for forbidden in [
                " fast ",
                " reassoc ",
                " contract ",
                "llvm.fma",
                "llvm.fmuladd",
                "noalias",
            ] {
                assert!(!region.contains(forbidden));
            }
        }
    }
}

#[allow(clippy::too_many_lines)]
fn corrupt(kernel: &mut VectorProductKernel, case: usize) {
    fn leaf(program: &mut [ProductStep]) -> &mut Vec<ProductStep> {
        let body = program
            .iter_mut()
            .find_map(|s| {
                if let ProductStep::For { body, .. } = s {
                    Some(body)
                } else {
                    None
                }
            })
            .unwrap();
        if body.iter().any(|s| matches!(s, ProductStep::For { .. })) {
            leaf(body)
        } else {
            body
        }
    }
    match case {
        0 => {
            kernel.program.remove(0);
        }
        1 => kernel.program.swap(0, 2),
        2 => kernel.product_op = BinaryOp::AddIntegerChecked,
        3 => kernel.accumulate_op = Some(BinaryOp::MultiplyIntegerChecked),
        4 => {
            kernel.zero = Some(Operand::Int {
                value: 1,
                ty: kernel.element_type,
            });
        }
        5 => {
            let body = leaf(&mut kernel.program);
            if let ProductStep::Math(MathStep::StridedLoad { offset, .. }) = &mut body[0] {
                offset[0].1 = MathStride::RowStride;
            }
        }
        6 => {
            let body = leaf(&mut kernel.program);
            if let ProductStep::Math(MathStep::StridedLoad { input, .. }) = &mut body[1] {
                *input = MathInput::Left;
            }
        }
        7 => {
            let body = leaf(&mut kernel.program);
            body[2] = ProductStep::Math(MathStep::ScalarBinary {
                op: BinaryOp::AddIntegerChecked,
                element_type: kernel.element_type,
                trap: Some(aether_middle::TrapKind::IntegerOverflow),
            });
        }
        8 => {
            let body = leaf(&mut kernel.program);
            body.push(body.last().unwrap().clone());
        }
        9 => {
            leaf(&mut kernel.program).pop();
        }
        10 => {
            kernel.program.push(ProductStep::Math(MathStep::YieldOwner));
        }
        11 => {
            kernel.program.push(ProductStep::YieldScalar);
        }
        12 => {
            let f = kernel
                .program
                .iter_mut()
                .find(|s| matches!(s, ProductStep::For { .. }))
                .unwrap();
            if let ProductStep::For { axis, .. } = f {
                *axis = MathAxis::Columns;
            }
        }
        13 => {
            let f = kernel
                .program
                .iter_mut()
                .find(|s| matches!(s, ProductStep::For { .. }))
                .unwrap();
            if let ProductStep::For { step, .. } = f {
                *step = 2;
            }
        }
        14 => kernel.program.insert(
            0,
            ProductStep::Math(MathStep::Allocate {
                extents: vec![MathAxis::Dimension],
                size_trap: aether_middle::TrapKind::AllocationSizeOverflow,
                failure_trap: aether_middle::TrapKind::AllocationFailure,
            }),
        ),
        15 => kernel.program.insert(
            0,
            ProductStep::Math(MathStep::ShapeGuard {
                axis: MathAxis::Dimension,
                trap: aether_middle::TrapKind::ShapeMismatch,
            }),
        ),
        16 => {
            let s = kernel
                .program
                .iter_mut()
                .find(|s| matches!(s, ProductStep::SelectExtent { .. }))
                .unwrap();
            if let ProductStep::SelectExtent { input, .. } = s {
                *input = MathInput::Right;
            }
        }
        17 => {
            let body = leaf(&mut kernel.program);
            body[3] = ProductStep::Accumulate {
                op: BinaryOp::MultiplyIntegerChecked,
                element_type: kernel.element_type,
                trap: Some(aether_middle::TrapKind::IntegerOverflow),
            };
        }
        18 => {
            if let Some(ProductStep::AccumulatorInit { value }) = kernel
                .program
                .iter_mut()
                .find(|s| matches!(s, ProductStep::AccumulatorInit { .. }))
            {
                *value = Operand::Int {
                    value: 1,
                    ty: kernel.element_type,
                };
            } else {
                kernel.program.push(ProductStep::AccumulatorInit {
                    value: Operand::Int {
                        value: 0,
                        ty: kernel.element_type,
                    },
                });
            }
        }
        _ => unreachable!(),
    }
}

#[test]
fn vertical31_mir_ssa_independent_corruption_rejection() {
    use aether_middle::{Rvalue, SsaOp, build_ssa, lower_hir, verify_mir, verify_ssa};
    for inner in [true, false] {
        let (result, expr) = if inner {
            ("int", "r*c")
        } else {
            ("Matrix<int>", "c*r")
        };
        let source = format!(
            "{result} product(ref Vector<int,Row>r,ref Vector<int,Column>c){{return {};}}int main(){{Vector<int,Row>r=[1];Vector<int,Column>c=[2];{result} x=product(&r,&c);return 0;}}",
            expr.replace('r', "*r").replace('c', "*c")
        );
        let raw = lower_hir(
            analyze(parse_source(&SourceFile::new("corrupt.ae", source)).unwrap()).unwrap(),
        );
        let ssa = build_ssa(&verify_mir(raw.clone()).unwrap());
        for case in 0..21 {
            let mut m = raw.clone();
            let fi = m
                .functions
                .iter()
                .position(|f| {
                    f.blocks
                        .iter()
                        .flat_map(|b| &b.instructions)
                        .any(|i| matches!(i.value, Rvalue::VectorProduct { .. }))
                })
                .unwrap();
            let input = m.functions[fi].parameters[0].local;
            let inst = m.functions[fi]
                .blocks
                .iter_mut()
                .flat_map(|b| &mut b.instructions)
                .find(|i| matches!(i.value, Rvalue::VectorProduct { .. }))
                .unwrap();
            let Rvalue::VectorProduct { left, kernel, .. } = &mut inst.value else {
                panic!()
            };
            if case == 19 {
                *left = Operand::Local(input);
            } else if case == 20 {
                kernel.element_type = aether_frontend::TypeId::BOOL;
            } else {
                corrupt(kernel, case);
            }
            assert!(verify_mir(m).is_err(), "MIR {inner} {case}");
            let mut s = ssa.clone();
            let input = s.functions[fi].parameters[0].value;
            let inst = s.functions[fi]
                .blocks
                .iter_mut()
                .flat_map(|b| &mut b.instructions)
                .find(|i| matches!(i.op, SsaOp::VectorProduct { .. }))
                .unwrap();
            let SsaOp::VectorProduct { left, kernel, .. } = &mut inst.op else {
                panic!()
            };
            if case == 19 {
                *left = aether_middle::SsaOperand::Value(input);
            } else if case == 20 {
                kernel.element_type = aether_frontend::TypeId::BOOL;
            } else {
                corrupt(kernel, case);
            }
            assert!(verify_ssa(s).is_err(), "SSA {inner} {case}");
        }
    }
}

#[test]
fn vertical31_dynamic_mismatch_guards_before_loads_ops_or_allocation() {
    let c = compile(
        "int inner(VectorView<int,Row>r,VectorView<int,Column>c){return r*c;}int main(){Vector<int,Row>r=[1,2];Vector<int,Column>c=[3];return inner(vector_view(r),vector_view(c));}",
    );
    assert_eq!(v23_execute(&c.llvm).signal(), Some(4));
    let instrumented = instrument(&c.llvm, 2);
    let instrumented=instrumented.replace("trap_shape_mismatch:\n", "trap_shape_mismatch:\n  %mload = load i64, ptr @v31_load\n  %mmul = load i64, ptr @v31_mul\n  %madd = load i64, ptr @v31_add\n  %mheap = load i64, ptr @aether_heap_alloc_count\n  %mfree = load i64, ptr @aether_heap_free_count\n  %msum0 = or i64 %mload, %mmul\n  %msum = or i64 %msum0, %madd\n  %mzero = icmp eq i64 %msum, 0\n  %mheq = icmp eq i64 %mheap, 2\n  %mfeq = icmp eq i64 %mfree, 0\n  %mhf = and i1 %mheq, %mfeq\n  %mok = and i1 %mzero, %mhf\n  %mstatus = select i1 %mok, i32 0, i32 97\n  call void @exit(i32 %mstatus)\n")+"\ndeclare void @exit(i32)\n";
    assert_eq!(v23_execute(&instrumented).code(), Some(0));
}

#[test]
fn vertical31_aliases_evaluation_temporaries_and_zero_axis_queries() {
    let c = compile(
        "Vector<int,Row> make(){Vector<int,Row>x=[2,3];return x;}int change(ref mut Vector<int,Row>r){(*r)[1]=4;return 1;}int main(){Vector<int,Row>r=[2,3];VectorView<int,Column>c=transpose_view(r);if(r*c!=13){return 1;}if(make()*c!=13){return 2;}if(r*(change(&mut r)*c)!=25){return 3;}Matrix<int>m=c*r;if(m[1,1]!=16){return 4;}return 0;}",
    );
    assert_eq!(v23_execute(&c.llvm).code(), Some(0));
    let bad = "Vector<int,Column> consume(Vector<int,Row>r){return transpose(r);}int main(){Vector<int,Row>r=[1,2];int x=r*consume(r);return x;}";
    assert!(compile_source(&SourceFile::new("consume.ae", bad), &[]).is_err());
    // Both zero axes survive transpose_view, copying descriptors, queries and
    // arithmetic. A row/column along a present axis is a valid empty view.
    let c = compile(
        "int main(){Vector<int,Column>c=[];Vector<int,Row>r=[1,2,3];Matrix<int>m=c*r;MatrixView<int>t=transpose_view(m);if(rows(t)!=3){return 1;}if(columns(t)!=0){return 2;}VectorView<int,Row>v=row(t,3);if(dimension(v)!=0){return 3;}return 0;}",
    );
    assert_eq!(v23_execute(&instrument(&c.llvm, 1)).code(), Some(0));
}

#[test]
fn vertical31_deterministic_dumps_and_constraint_order_abi() {
    let source = fs::read_to_string(program("v31_inner_int.ae")).unwrap();
    let a = compile(&source);
    let b = compile(&source);
    assert_eq!(a.dumps, b.dumps);
    assert_eq!(a.llvm, b.llvm);
    let reordered = compile(source.replace("Copy+Add+Mul+Zero", "Zero+Mul+Copy+Add"));
    assert_eq!(a.llvm, reordered.llvm);
    let h = &a.dumps[&Emit::Hir];
    for text in [
        "VectorAlgebraicProduct",
        "Behavioral(",
        "AlgebraicValue",
        "Zero",
        "Concrete(",
        "Inner",
    ] {
        assert!(h.contains(text), "{text}");
    }
    for phase in [Emit::Mir, Emit::Ssa] {
        assert!(a.dumps[&phase].contains("ReductionKernel"));
    }
}

#[test]
fn vertical31_cross_module_strided_products() {
    let c = compile_session(
        CompilationSession::discover(&module_program("v31_products")).unwrap(),
        &[],
    )
    .unwrap();
    assert_eq!(v23_execute(&instrument(&c.llvm, 2)).code(), Some(0));
}
