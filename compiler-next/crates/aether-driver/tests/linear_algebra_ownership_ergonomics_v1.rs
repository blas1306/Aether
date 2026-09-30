//! LINEAR-ALGEBRA-OWNERSHIP-ERGONOMICS-V1 qualification.

use std::{fs, path::PathBuf, process::Command};

use aether_backend_llvm::{TargetDescriptor, emit_llvm};
use aether_driver::{
    ClangToolchain, CompilationSession, Emit, OptimizationLevel, compile_session,
    compile_session_with_optimization,
};
use aether_frontend::{SourceFile, analyze, parse_source};
use aether_middle::{SsaOp, build_ssa, lower_hir, verify_mir, verify_ssa};

const LIBRARY: &str = include_str!("../../../../linearAlgebra/src/lib.ae");

struct Directory(PathBuf);

impl Directory {
    fn new(label: &str) -> Self {
        static NEXT: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
        let path = std::env::temp_dir().join(format!(
            "aether-linear-algebra-ownership-{label}-{}-{}",
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
        .unwrap();
    Command::new(executable).status().unwrap()
}

fn allocation_guard(llvm: &str, expected: u64) -> String {
    llvm.replace(
        "  %process_status = trunc i64 %aether_result to i32",
        &format!(
            "  %allocs = load i64, ptr @aether_heap_alloc_count\n  %frees = load i64, ptr @aether_heap_free_count\n  %alloc_ok = icmp eq i64 %allocs, {expected}\n  %free_ok = icmp eq i64 %frees, {expected}\n  %heap_ok = and i1 %alloc_ok, %free_ok\n  %result_ok = icmp eq i64 %aether_result, 0\n  %all_ok = and i1 %heap_ok, %result_ok\n  %process_status = select i1 %all_ok, i32 0, i32 99"
        ),
    )
}

#[test]
fn public_surface_has_preserving_defaults_and_single_in_place_kernels() {
    for signature in [
        "LU<T> lu<T: IEEEFloat>(ref Matrix<T> A)",
        "LU<T> luInPlace<T: IEEEFloat>(Matrix<T> A)",
        "QR<T> qr<T: IEEEFloat>(ref Matrix<T> A)",
        "QR<T> qrInPlace<T: IEEEFloat>(Matrix<T> A)",
        "Cholesky<T> cholesky<T: IEEEFloat>(ref Matrix<T> A)",
        "Cholesky<T> choleskyInPlace<T: IEEEFloat>(Matrix<T> A)",
        "T det<T: IEEEFloat>(ref Matrix<T> A)",
        "T detInPlace<T: IEEEFloat>(Matrix<T> A)",
    ] {
        assert_eq!(LIBRARY.matches(signature).count(), 1, "{signature}");
    }
    assert_eq!(
        LIBRARY
            .matches("Vector<T,Column> solveInPlace<T: IEEEFloat>(")
            .count(),
        1
    );
    assert_eq!(
        LIBRARY
            .matches("Matrix<T> solveInPlace<T: IEEEFloat>(")
            .count(),
        1
    );
    assert!(!LIBRARY.contains("LU<T> lu<T: IEEEFloat>(Matrix<T> A)"));
    assert!(!LIBRARY.contains("QR<T> qr<T: IEEEFloat>(Matrix<T> A)"));
    assert!(!LIBRARY.contains("Cholesky<T> cholesky<T: IEEEFloat>(Matrix<T> A)"));
    assert!(LIBRARY.contains("return qrInPlace(A);"));

    let helper_start = LIBRARY
        .find("Matrix<T> copyMatrixForFactorization<T: IEEEFloat>")
        .unwrap();
    let helper_end = LIBRARY[helper_start..].find("\n}\n\nLU<T> lu").unwrap() + helper_start;
    let helper = &LIBRARY[helper_start..helper_end];
    assert_eq!(helper.matches("matrixFilled<T>(m, n, 0)").count(), 1);
    assert_eq!(helper.matches("result[i,j] = (*source)[i,j]").count(), 1);
    assert!(!helper.contains("memcpy"));
    assert!(!LIBRARY.contains("public Matrix<T> copyMatrixForFactorization"));
}

#[test]
fn preserving_calls_keep_sources_usable_and_match_in_place_results_o0_o2() {
    let source = r"package consumer;import linearAlgebra as la;
int main(){
  Matrix<float64>a=[0.0,2.0;3.0,4.0];
  la.LU<float64>lp=la.lu(a);la.QR<float64>qp=la.qr(&a);
  if(a[1,1]!=0.0||a[1,2]!=2.0||a[2,1]!=3.0||a[2,2]!=4.0){return 1;}
  Matrix<float64>al=[0.0,2.0;3.0,4.0];la.LU<float64>li=la.luInPlace(al);
  Matrix<float64>aq=[0.0,2.0;3.0,4.0];la.QR<float64>qi=la.qrInPlace(aq);
  if(lp.permutationSign!=li.permutationSign||lp.U[1,1]!=li.U[1,1]||lp.L[2,1]!=li.L[2,1]){return 2;}
  if(abs(qp.R[1,1]-qi.R[1,1])>1e-12||abs(qp.Q[2,1]-qi.Q[2,1])>1e-12){return 3;}
  Matrix<float64>c=[4.0,2.0;2.0,5.0];la.Cholesky<float64>cp=la.cholesky(c);
  Matrix<float64>ci=[4.0,2.0;2.0,5.0];la.Cholesky<float64>cx=la.choleskyInPlace(ci);
  if(c[1,1]!=4.0||c[1,2]!=2.0||cp.L[2,1]!=cx.L[2,1]){return 4;}
  Vector<float64,Column>b=[2.0,8.0];Vector<float64,Column>x=la.solve(a,b);
  Matrix<float64>B=[2.0,1.0;8.0,5.0];Matrix<float64>X=la.solve(a,B);
  float64 d=la.det(a);
  if(a[2,2]!=4.0||b[1]!=2.0||B[1,1]!=2.0){return 5;}
  if(abs(x[1]-1.3333333333333333)>1e-12||abs(X[1,1]-1.3333333333333333)>1e-12||abs(d+6.0)>1e-12){return 6;}
  return 0;
}";
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        let compilation = compile(source, optimization);
        assert_eq!(status(&compilation.llvm, optimization).code(), Some(0));
        assert!(compilation.dumps[&Emit::Hir].contains("CallScopedSharedBorrow"));
        assert!(compilation.dumps[&Emit::Mir].contains("EndBorrow"));
        assert!(compilation.dumps[&Emit::Ssa].contains("EndBorrow"));
    }
}

#[test]
fn every_in_place_matrix_entry_point_consumes_its_owner() {
    for call in [
        "var f=la.luInPlace(a);",
        "var f=la.qrInPlace(a);",
        "var f=la.choleskyInPlace(a);",
        "float64 f=la.detInPlace(a);",
        "Vector<float64,Column>f=la.solveInPlace(a,b);",
        "Matrix<float64>f=la.solveInPlace(a,B);",
    ] {
        let extras = if call.contains(",b") {
            "Vector<float64,Column>b=[1.0];"
        } else if call.contains(",B") {
            "Matrix<float64>B=[1.0];"
        } else {
            ""
        };
        let source = format!(
            "package consumer;import linearAlgebra as la;int main(){{Matrix<float64>a=[1.0];{extras}{call}return int(a[1,1]);}}"
        );
        let output = diagnostics(&source);
        assert!(
            output.contains("use after move of non-Copy local `a`"),
            "{call}: {output}"
        );
    }
}

#[test]
fn preserving_factorizations_add_exactly_one_nonempty_backing() {
    let cases = [
        ("var f=la.lu(a);return f.permutationSign-1;", 4_u64),
        ("var f=la.luInPlace(a);return f.permutationSign-1;", 3),
        ("var f=la.qr(a);return int(rows(f.Q)-2);", 3),
        ("var f=la.qrInPlace(a);return int(rows(f.Q)-2);", 2),
        ("var f=la.cholesky(a);return int(f.L[1,1]-2.0);", 2),
        ("var f=la.choleskyInPlace(a);return int(f.L[1,1]-2.0);", 1),
    ];
    for (body, expected) in cases {
        let matrix = if body.contains("cholesky") {
            "[4.0,2.0;2.0,5.0]"
        } else {
            "[2.0,0.0;0.0,3.0]"
        };
        let source = format!(
            "package consumer;import linearAlgebra as la;int main(){{Matrix<float64>a={matrix};{body}}}"
        );
        for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
            let compilation = compile(&source, optimization);
            let guarded = allocation_guard(&compilation.llvm, expected);
            assert_ne!(guarded, compilation.llvm);
            assert_eq!(
                status(&guarded, optimization).code(),
                Some(0),
                "{body} {optimization:?}"
            );
        }
    }
}

#[test]
fn logical_copy_uses_padded_stride_and_normalizes_destination_capacity() {
    let source = SourceFile::new(
        "ownership-padded.ae",
        r"Matrix<T> copyMatrixForFactorization<T:IEEEFloat>(ref Matrix<T>source){usize m=rows(*source);usize n=columns(*source);Matrix<T>result=matrixFilled<T>(m,n,0);usize i=1;while(i<=m){usize j=1;while(j<=n){result[i,j]=(*source)[i,j];j=j+1;}i=i+1;}return result;}int main(){Matrix<float64>a=[1.0,2.0;3.0,4.0];Matrix<float64>b=copyMatrixForFactorization(a);if(a[2,1]!=3.0||b[1,2]!=2.0||b[2,1]!=3.0||b[2,2]!=4.0){return 1;}return 0;}",
    );
    let hir = analyze(parse_source(&source).unwrap()).unwrap();
    let mir = verify_mir(lower_hir(hir)).unwrap();
    let mut ssa = build_ssa(&mir);
    let mut padded = 0;
    let mut exact_copy = 0;
    for instruction in ssa
        .functions
        .iter_mut()
        .flat_map(|function| &mut function.blocks)
        .flat_map(|block| &mut block.instructions)
    {
        match &mut instruction.op {
            SsaOp::MatrixInit {
                row_capacity,
                column_capacity,
                ..
            } => {
                *row_capacity = 3;
                *column_capacity = 5;
                padded += 1;
            }
            SsaOp::MatrixFilled {
                rows,
                columns,
                row_capacity,
                column_capacity,
                ..
            } => {
                assert_eq!(rows, row_capacity);
                assert_eq!(columns, column_capacity);
                exact_copy += 1;
            }
            _ => {}
        }
    }
    assert_eq!(padded, 1);
    assert_eq!(exact_copy, 1);
    let llvm = emit_llvm(&verify_ssa(ssa).unwrap(), &TargetDescriptor::linux_x86_64());
    assert!(llvm.contains("%row_offset = mul i64 %row0, %column_capacity"));
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        assert_eq!(
            status(&allocation_guard(&llvm, 2), optimization).code(),
            Some(0)
        );
    }

    let empty = SourceFile::new(
        "ownership-empty-padded.ae",
        r"Matrix<T> copyMatrixForFactorization<T:IEEEFloat>(ref Matrix<T>source){usize m=rows(*source);usize n=columns(*source);Matrix<T>result=matrixFilled<T>(m,n,0);usize i=1;while(i<=m){usize j=1;while(j<=n){result[i,j]=(*source)[i,j];j=j+1;}i=i+1;}return result;}int main(){Matrix<float64>a=[];Matrix<float64>b=copyMatrixForFactorization(a);if(rows(a)!=0||columns(a)!=0||rows(b)!=0||columns(b)!=0){return 1;}return 0;}",
    );
    let hir = analyze(parse_source(&empty).unwrap()).unwrap();
    let mir = verify_mir(lower_hir(hir)).unwrap();
    let mut ssa = build_ssa(&mir);
    for instruction in ssa
        .functions
        .iter_mut()
        .flat_map(|function| &mut function.blocks)
        .flat_map(|block| &mut block.instructions)
    {
        if let SsaOp::MatrixInit {
            row_capacity,
            column_capacity,
            ..
        } = &mut instruction.op
        {
            *row_capacity = 2;
            *column_capacity = 3;
        }
    }
    let llvm = emit_llvm(&verify_ssa(ssa).unwrap(), &TargetDescriptor::linux_x86_64());
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        // Only the deliberately reserved empty source owns storage; its exact
        // 0x0 copy has a null backing.
        assert_eq!(
            status(&allocation_guard(&llvm, 1), optimization).code(),
            Some(0)
        );
    }
}

#[test]
fn zero_extent_factorizations_preserve_both_extents_without_copy_backings() {
    let source = r"package consumer;import linearAlgebra as la;
int main(){
  Vector<float64,Column>three=[1.0,2.0,3.0];Vector<float64,Row>none=[];
  Matrix<float64>m0=three*none;var l=la.lu(m0);
  if(rows(m0)!=3||columns(m0)!=0||rows(l.L)!=3||columns(l.L)!=0||rows(l.U)!=0||columns(l.U)!=0){return 1;}
  Vector<float64,Column>zero=[];Vector<float64,Row>four=[1.0,2.0,3.0,4.0];
  Matrix<float64>z4=zero*four;var q=la.qr(z4);
  if(rows(z4)!=0||columns(z4)!=4||rows(q.Q)!=0||columns(q.Q)!=0||rows(q.R)!=0||columns(q.R)!=4){return 2;}
  Matrix<float64>z=la.zeros(0,0);var c=la.cholesky(z);
  if(rows(z)!=0||columns(z)!=0||rows(c.L)!=0||columns(c.L)!=0){return 3;}
  return 0;
}";
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        let compilation = compile(source, optimization);
        assert_eq!(status(&compilation.llvm, optimization).code(), Some(0));
    }
}
