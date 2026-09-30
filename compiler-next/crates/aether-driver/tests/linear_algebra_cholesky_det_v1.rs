//! LINEAR-ALGEBRA-CHOLESKY-DET-V1 source, IEEE, ownership, lowering, and allocation qualification.

use std::{fs, path::PathBuf, process::Command};

use aether_driver::{
    ClangToolchain, CompilationSession, Emit, OptimizationLevel, compile_session,
    compile_session_with_optimization,
};

const LIBRARY: &str = include_str!("../../../../linearAlgebra/src/lib.ae");

struct Directory(PathBuf);

impl Directory {
    fn new(label: &str) -> Self {
        static NEXT: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
        let path = std::env::temp_dir().join(format!(
            "aether-linear-algebra-cholesky-det-{label}-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, std::sync::atomic::Ordering::Relaxed)
        ));
        fs::create_dir(&path).unwrap();
        fs::write(path.join("linearAlgebra.ae"), LIBRARY).unwrap();
        Self(path)
    }

    fn entry(&self, source: &str) -> PathBuf {
        let path = self.0.join("main.ae");
        fs::write(&path, source).unwrap();
        path
    }
}

impl Drop for Directory {
    fn drop(&mut self) {
        fs::remove_dir_all(&self.0).unwrap();
    }
}

fn compile(source: &str, optimization: OptimizationLevel) -> aether_driver::Compilation {
    let directory = Directory::new("compile");
    let entry = directory.entry(source);
    compile_session_with_optimization(
        CompilationSession::discover(&entry).unwrap(),
        &[Emit::Hir, Emit::Mir, Emit::Ssa, Emit::Llvm],
        optimization,
    )
    .unwrap_or_else(|errors| panic!("{source}\n{errors:#?}"))
}

fn diagnostics(source: &str) -> String {
    let directory = Directory::new("diagnostic");
    let entry = directory.entry(source);
    compile_session(CompilationSession::discover(&entry).unwrap(), &[])
        .unwrap_err()
        .into_iter()
        .map(|diagnostic| format!("{} {}", diagnostic.code, diagnostic.message))
        .collect::<Vec<_>>()
        .join("\n")
}

fn status(llvm: &str, optimization: OptimizationLevel) -> std::process::ExitStatus {
    let directory = Directory::new("native");
    let executable = directory.0.join("program");
    ClangToolchain::default()
        .with_optimization(optimization)
        .link_executable(llvm, &executable)
        .unwrap_or_else(|error| panic!("{error:#?}\n{llvm}"));
    Command::new(executable).status().unwrap()
}

fn run_both(source: &str) {
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        let compilation = compile(source, optimization);
        assert_eq!(
            status(&compilation.llvm, optimization).code(),
            Some(0),
            "{optimization:?}: {source}"
        );
    }
}

fn allocation_guard(llvm: &str, expected: i64) -> String {
    let guarded = llvm.replace(
        "  %process_status = trunc i64 %aether_result to i32",
        &format!(
            "  %allocs = load i64, ptr @aether_heap_alloc_count\n  %frees = load i64, ptr @aether_heap_free_count\n  %alloc_ok = icmp eq i64 %allocs, {expected}\n  %free_ok = icmp eq i64 %frees, {expected}\n  %heap_ok = and i1 %alloc_ok, %free_ok\n  %result_ok = icmp eq i64 %aether_result, 0\n  %all_ok = and i1 %heap_ok, %result_ok\n  %process_status = select i1 %all_ok, i32 0, i32 99"
        ),
    );
    assert_ne!(guarded, llvm);
    guarded
}

#[test]
fn public_surface_guard_and_form_a_are_exact() {
    let signature = "T det<T: IEEEFloat>(ref Cholesky<T> factor)";
    assert_eq!(LIBRARY.matches(signature).count(), 1);
    let start = LIBRARY.find(signature).unwrap();
    let end = LIBRARY[start..]
        .find("public class NotSymmetricMatrixException")
        .unwrap()
        + start;
    let kernel = &LIBRARY[start..end];

    assert!(kernel.starts_with(
        "T det<T: IEEEFloat>(ref Cholesky<T> factor) {\n    shapeGuard(rows((*factor).L) == columns((*factor).L));\n    usize n = rows((*factor).L);"
    ));
    assert_eq!(kernel.matches("shapeGuard(").count(), 1);
    assert_eq!(kernel.matches("(*factor).L[i,i]").count(), 1);
    assert!(kernel.contains("T p = 1;"));
    assert!(kernel.contains("p = p * (*factor).L[i,i];"));
    assert!(kernel.contains("return p * p;"));
    assert!(kernel.find("T p = 1;").unwrap() < kernel.find("usize i = 1;").unwrap());
    for forbidden in [
        "if (n == 0)",
        "abs(",
        "sqrt(",
        "throw ",
        "Matrix<T>",
        "Vector<",
        "transpose",
        "clone",
        "upper",
        "lower",
        "log(",
    ] {
        assert!(!kernel.contains(forbidden), "kernel contains {forbidden}");
    }
}

#[test]
fn legitimate_factors_match_matrix_and_lu_and_remain_reusable() {
    let source = "package consumer;import linearAlgebra as la;int main(){Matrix<float64>a=[4.0,2.0;2.0,5.0];la.Cholesky<float64>ch=la.cholesky(a);float64 dc=la.det(ch);float64 dm=la.det(a);la.LU<float64>lu=la.lu(a);float64 dl=la.det(lu);Vector<float64,Column>b=[8.0,12.0];Vector<float64,Column>x=la.solve(ch,b);if(abs(dc-16.0)>1e-12||abs(dc-dm)>1e-12||abs(dc-dl)>1e-12||ch.L[2,1]!=1.0||x[1]!=1.0||x[2]!=2.0){return 1;}Matrix<float64>e=la.zeros(0,0);la.Cholesky<float64>ce=la.Cholesky<float64>(e);float64 de=la.det(ce);if(de!=1.0){return 2;}Matrix<float32>f=[float32(4.0),float32(2.0);float32(2.0),float32(5.0)];la.Cholesky<float32>cf=la.cholesky(f);float32 df=la.det<float32>(cf);if(abs(df-float32(16.0))>float32(2e-5)||cf.L[2,1]!=float32(1.0)){return 3;}return 0;}";
    run_both(source);
}

#[test]
fn scalar_identity_and_diagonal_factors_work_in_both_precisions() {
    let source = "package consumer;import linearAlgebra as la;int main(){Matrix<float64>s=[9.0];la.Cholesky<float64>fs=la.cholesky(s);if(la.det(fs)!=9.0){return 1;}Matrix<float64>i=[1.0,0.0,0.0;0.0,1.0,0.0;0.0,0.0,1.0];la.Cholesky<float64>fi=la.cholesky(i);if(la.det(fi)!=1.0){return 2;}Matrix<float64>d=[4.0,0.0,0.0;0.0,9.0,0.0;0.0,0.0,16.0];la.Cholesky<float64>fd=la.cholesky(d);if(la.det(fd)!=576.0){return 3;}Matrix<float32>q=[float32(4.0),float32(0.0);float32(0.0),float32(9.0)];la.Cholesky<float32>fq=la.cholesky(q);la.LU<float32>lq=la.lu(q);float32 dc=la.det(fq);float32 dm=la.det(q);float32 dl=la.det(lq);if(dc!=float32(36.0)||abs(dc-dm)>float32(2e-5)||abs(dc-dl)>float32(2e-5)){return 4;}return 0;}";
    run_both(source);
}

#[test]
fn manual_factors_follow_ieee_form_a_and_ignore_every_off_diagonal() {
    let source = "package consumer;import linearAlgebra as la;int main(){float64 z=0.0;float64 inf=1.0/z;float64 nan=z/z;Matrix<float64>a=[2.0,nan;inf,-3.0];Matrix<float64>b=[2.0,-inf;nan,-3.0];la.Cholesky<float64>fa=la.Cholesky<float64>(a);la.Cholesky<float64>fb=la.Cholesky<float64>(b);float64 da=la.det(fa);float64 db=la.det(fb);if(da!=36.0||db!=da){return 1;}Matrix<float64>neg=[-2.0,9.0;7.0,3.0];la.Cholesky<float64>fn=la.Cholesky<float64>(neg);if(la.det(fn)!=36.0){return 2;}Matrix<float64>pz=[z];Matrix<float64>nz=[-z];la.Cholesky<float64>fpz=la.Cholesky<float64>(pz);la.Cholesky<float64>fnz=la.Cholesky<float64>(nz);float64 dpz=la.det(fpz);float64 dnz=la.det(fnz);if(dpz!=z||dnz!=z||1.0/dpz!=inf||1.0/dnz!=inf){return 3;}Matrix<float64>qn=[nan];la.Cholesky<float64>fqn=la.Cholesky<float64>(qn);if(la.det(fqn)==la.det(fqn)){return 4;}Matrix<float64>qi=[-inf];la.Cholesky<float64>fqi=la.Cholesky<float64>(qi);if(la.det(fqi)!=inf){return 5;}Matrix<float64>mix=[inf,5.0;7.0,z];la.Cholesky<float64>fmix=la.Cholesky<float64>(mix);if(la.det(fmix)==la.det(fmix)){return 6;}Matrix<float64>formA=[1e200,0.0;0.0,1e-200];la.Cholesky<float64>ffa=la.Cholesky<float64>(formA);float64 dfa=la.det(ffa);if(abs(dfa-1.0)>1e-12){return 7;}Matrix<float64>partial=[1e308,0.0,0.0;0.0,2.0,0.0;0.0,0.0,0.5];la.Cholesky<float64>fpartial=la.Cholesky<float64>(partial);if(la.det(fpartial)!=inf){return 8;}Matrix<float64>under=[1e-200];la.Cholesky<float64>funder=la.Cholesky<float64>(under);if(la.det(funder)!=z){return 9;}Matrix<float32>formA32=[float32(1e20),float32(0.0);float32(0.0),float32(1e-20)];la.Cholesky<float32>ffa32=la.Cholesky<float32>(formA32);float32 dfa32=la.det(ffa32);if(!(dfa32>float32(0.9))||!(dfa32<float32(1.1))){return 10;}return 0;}";
    run_both(source);
}

#[test]
fn float32_manual_factors_preserve_special_values_and_off_diagonal_invariance() {
    let source = "package consumer;import linearAlgebra as la;int main(){float32 z=float32(0.0);float32 inf=float32(1.0)/z;float32 nan=z/z;Matrix<float32>a=[float32(-2.0),nan;inf,float32(3.0)];Matrix<float32>b=[float32(-2.0),-inf;-nan,float32(3.0)];la.Cholesky<float32>fa=la.Cholesky<float32>(a);la.Cholesky<float32>fb=la.Cholesky<float32>(b);if(la.det(fa)!=float32(36.0)||la.det(fb)!=la.det(fa)){return 1;}Matrix<float32>nz=[-z];la.Cholesky<float32>fnz=la.Cholesky<float32>(nz);float32 dnz=la.det(fnz);if(dnz!=z||float32(1.0)/dnz!=inf){return 2;}Matrix<float32>qn=[nan];la.Cholesky<float32>fqn=la.Cholesky<float32>(qn);if(la.det(fqn)==la.det(fqn)){return 3;}Matrix<float32>qi=[-inf];la.Cholesky<float32>fqi=la.Cholesky<float32>(qi);if(la.det(fqi)!=inf){return 4;}Matrix<float32>under=[float32(1e-30)];la.Cholesky<float32>funder=la.Cholesky<float32>(under);if(la.det(funder)!=z){return 5;}return 0;}";
    run_both(source);
}

#[test]
fn rectangular_manual_factor_traps_at_the_only_shape_guard() {
    let source = "package consumer;import linearAlgebra as la;int main(){Matrix<float64>l=[1.0,2.0];la.Cholesky<float64>f=la.Cholesky<float64>(l);float64 d=la.det(f);return int(d);}";
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        let compilation = compile(source, optimization);
        let instrumented = compilation.llvm.replace(
            "trap_shape_mismatch:\n  ; structured Aether trap: ShapeMismatch\n  call void @llvm.trap()",
            "trap_shape_mismatch:\n  call void @exit(i32 73)",
        ) + "\ndeclare void @exit(i32)\n";
        assert_eq!(status(&instrumented, optimization).code(), Some(73));
    }
}

#[test]
fn determinant_adds_no_allocations_including_order_zero() {
    let cases = [
        (
            "package consumer;import linearAlgebra as la;int main(){Matrix<float64>l=[2.0,99.0;88.0,3.0];la.Cholesky<float64>f=la.Cholesky<float64>(l);float64 d=la.det(f);return int(d-36.0);}",
            1,
        ),
        (
            "package consumer;import linearAlgebra as la;int main(){Matrix<float64>l=la.zeros(0,0);la.Cholesky<float64>f=la.Cholesky<float64>(l);float64 d=la.det(f);return int(d-1.0);}",
            0,
        ),
    ];
    for (source, expected) in cases {
        for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
            let compilation = compile(source, optimization);
            assert_eq!(
                status(&allocation_guard(&compilation.llvm, expected), optimization).code(),
                Some(0)
            );
        }
    }
}

#[test]
fn lowering_is_generic_only_in_hir_and_concrete_after_monomorphization() {
    let source = "package consumer;import linearAlgebra as la;T forward<T:IEEEFloat>(ref la.Cholesky<T>f){return la.det(f);}int main(){Matrix<float64>a=[2.0];la.Cholesky<float64>x=la.Cholesky<float64>(a);float64 dx=forward(x);Matrix<float32>b=[float32(3.0)];la.Cholesky<float32>y=la.Cholesky<float32>(b);float32 dy=la.det(y);return int(dx+float64(dy)-13.0);}";
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        let compilation = compile(source, optimization);
        let hir = &compilation.dumps[&Emit::Hir];
        for operation in [
            "ShapeGuard",
            "MatrixRows",
            "MatrixColumns",
            "AlgebraicValue",
            "capability: One",
            "CapabilityBinary",
            "behavior: Mul",
            "MultiplyFloat",
        ] {
            assert!(hir.contains(operation), "HIR missing {operation}");
        }
        for phase in [Emit::Mir, Emit::Ssa] {
            let dump = &compilation.dumps[&phase];
            for residue in [
                "AlgebraicValue",
                "CapabilityBinary",
                "GenericParam(",
                "witness",
                "vtable",
            ] {
                assert!(!dump.contains(residue), "{phase:?} contains {residue}");
            }
        }
        assert!(compilation.llvm.contains("fmul double"));
        assert!(compilation.llvm.contains("fmul float"));
        for residue in ["TypeId", "witness", "vtable", "aether_cholesky_det"] {
            assert!(!compilation.llvm.contains(residue));
        }
        assert_eq!(status(&compilation.llvm, optimization).code(), Some(0));
    }

    let rejected = diagnostics(
        "package consumer;import linearAlgebra as la;int main(){Matrix<int>l=[1];la.Cholesky<int>f=la.Cholesky<int>(l);int d=la.det<int>(f);return d;}",
    );
    assert!(rejected.contains("E0460"), "{rejected}");
    assert!(rejected.contains("no matching overload"), "{rejected}");
}
