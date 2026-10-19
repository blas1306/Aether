//! LINEAR-ALGEBRA-SYMMETRIC-EIGEN-ASSEMBLY-V1 public qualification.

use std::{
    fmt::Write as _,
    fs,
    io::Write as _,
    path::PathBuf,
    process::{Command, Stdio},
};

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
            "aether-symmetric-eigen-{label}-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, std::sync::atomic::Ordering::Relaxed)
        ));
        fs::create_dir(&path).unwrap();
        Self(path)
    }

    fn imported(&self, source: &str) -> PathBuf {
        fs::write(self.0.join("linearAlgebra.ae"), LIBRARY).unwrap();
        let path = self.0.join("main.ae");
        fs::write(&path, source).unwrap();
        path
    }

    fn white_box(&self, source: &str) -> PathBuf {
        let path = self.0.join("linearAlgebra.ae");
        fs::write(&path, format!("{LIBRARY}\n{source}\n")).unwrap();
        path
    }
}

impl Drop for Directory {
    fn drop(&mut self) {
        fs::remove_dir_all(&self.0).unwrap();
    }
}

fn compile_and_run(source: &str, optimization: OptimizationLevel) -> String {
    let directory = Directory::new("native");
    let entry = directory.imported(source);
    let compilation = compile_session_with_optimization(
        CompilationSession::discover(&entry).unwrap(),
        &[Emit::Llvm],
        optimization,
    )
    .unwrap();
    let executable = directory.0.join("qualification");
    ClangToolchain::default()
        .with_optimization(optimization)
        .link_executable(&compilation.llvm, &executable)
        .unwrap();
    let output = Command::new(executable).output().unwrap();
    assert!(
        output.status.success(),
        "{optimization:?}: exit={:?}\nstdout={}\nstderr={}",
        output.status.code(),
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr)
    );
    String::from_utf8(output.stdout).unwrap()
}

#[derive(Clone)]
struct Case {
    name: &'static str,
    n: usize,
    a: Vec<f64>,
}

fn cases(float32: bool) -> Vec<Case> {
    let cluster = if float32 { 2.0e-5 } else { 2.0e-10 };
    let large = if float32 { 1.0e30 } else { 1.0e200 };
    let small = if float32 { 1.0e-30 } else { 1.0e-200 };
    vec![
        Case {
            name: "empty",
            n: 0,
            a: vec![],
        },
        Case {
            name: "scalar",
            n: 1,
            a: vec![-3.0],
        },
        Case {
            name: "diagonal-unordered",
            n: 3,
            a: vec![3.0, 0.0, -0.0, 0.0, -2.0, 0.0, -0.0, 0.0, 1.0],
        },
        Case {
            name: "identity",
            n: 3,
            a: vec![1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0],
        },
        Case {
            name: "zero",
            n: 3,
            a: vec![0.0; 9],
        },
        Case {
            name: "dense",
            n: 4,
            a: vec![
                4.0, 1.0, -2.0, 2.0, 1.0, 2.0, 0.0, 1.0, -2.0, 0.0, 3.0, -2.0, 2.0, 1.0, -2.0, -1.0,
            ],
        },
        Case {
            name: "positive-definite",
            n: 3,
            a: vec![4.0, 1.0, 1.0, 1.0, 3.0, 0.0, 1.0, 0.0, 2.0],
        },
        Case {
            name: "semidefinite",
            n: 2,
            a: vec![1.0, 1.0, 1.0, 1.0],
        },
        Case {
            name: "singular-indefinite",
            n: 3,
            a: vec![0.0, 1.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0],
        },
        Case {
            name: "indefinite",
            n: 3,
            a: vec![2.0, -3.0, 1.0, -3.0, -1.0, 2.0, 1.0, 2.0, 0.5],
        },
        Case {
            name: "repeated",
            n: 3,
            a: vec![2.0, 1.0, 0.0, 1.0, 2.0, 0.0, 0.0, 0.0, 3.0],
        },
        Case {
            name: "clustered",
            n: 3,
            a: vec![1.0, cluster, 0.0, cluster, 1.0, 0.0, 0.0, 0.0, 3.0],
        },
        Case {
            name: "split-blocks",
            n: 4,
            a: vec![
                2.0, 1.0, 0.0, 0.0, 1.0, 4.0, 0.0, 0.0, 0.0, 0.0, -1.0, 0.5, 0.0, 0.0, 0.5, 3.0,
            ],
        },
        Case {
            name: "large-scale",
            n: 2,
            a: vec![2.0 * large, large, large, 3.0 * large],
        },
        Case {
            name: "small-scale",
            n: 2,
            a: vec![2.0 * small, small, small, 3.0 * small],
        },
    ]
}

fn literal(case: &Case, float32: bool) -> String {
    if case.n == 0 {
        let scalar = if float32 { "float32" } else { "float64" };
        return format!("matrixFilled<{scalar}>(0,0,{scalar}(0.0))");
    }
    let mut result = String::from("[");
    for i in 0..case.n {
        for j in 0..case.n {
            if j > 0 {
                result.push(',');
            }
            let value = case.a[i * case.n + j];
            if float32 {
                write!(result, "float32({value:.17e})").unwrap();
            } else {
                write!(result, "{value:.17e}").unwrap();
            }
        }
        if i + 1 < case.n {
            result.push(';');
        }
    }
    result.push(']');
    result
}

fn emitter_source(cases: &[Case], float32: bool) -> String {
    let scalar = if float32 { "float32" } else { "float64" };
    let mut body = String::from("package consumer;import linearAlgebra as la;int main(){");
    for (index, case) in cases.iter().enumerate() {
        let matrix = literal(case, float32);
        write!(body,
            "Matrix<{scalar}>a{index}={matrix};la.SymmetricEigen<{scalar}>f{index}=la.symmetricEigen(a{index});usize i{index}=1;while(i{index}<=dimension(f{index}.values)){{println(f{index}.values[i{index}]);i{index}=i{index}+1;}}i{index}=1;while(i{index}<=rows(f{index}.vectors)){{usize j{index}=1;while(j{index}<=columns(f{index}.vectors)){{println(f{index}.vectors[i{index},j{index}]);j{index}=j{index}+1;}}i{index}=i{index}+1;}}"
        ).unwrap();
    }
    body.push_str("return 0;}");
    body
}

fn frobenius(values: &[f64]) -> f64 {
    let scale = values.iter().fold(0.0_f64, |x, y| x.max(y.abs()));
    if scale == 0.0 {
        return 0.0;
    }
    scale
        * values
            .iter()
            .map(|x| (x / scale) * (x / scale))
            .sum::<f64>()
            .sqrt()
}

struct Oracle {
    values: Vec<f64>,
    vectors: Vec<f64>,
}

fn numpy_oracle(cases: &[Case]) -> Vec<Oracle> {
    let script = r"
import sys, numpy as np
tokens=iter(sys.stdin.read().split())
count=int(next(tokens))
for _ in range(count):
 n=int(next(tokens)); a=np.array([float(next(tokens)) for _ in range(n*n)]).reshape((n,n))
 x=np.linalg.eigvalsh(a); y,v=np.linalg.eigh(a)
 assert np.allclose(x,y,rtol=1e-14,atol=1e-300)
 print(*x)
 print(*v.ravel())
";
    let mut child = Command::new("python3")
        .args(["-c", script])
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .spawn()
        .unwrap();
    {
        let input = child.stdin.as_mut().unwrap();
        write!(input, "{} ", cases.len()).unwrap();
        for case in cases {
            write!(input, "{} ", case.n).unwrap();
            for value in &case.a {
                write!(input, "{value:.17e} ").unwrap();
            }
        }
    }
    let output = child.wait_with_output().unwrap();
    assert!(output.status.success(), "numpy oracle unavailable");
    let mut tokens = String::from_utf8(output.stdout)
        .unwrap()
        .split_whitespace()
        .map(|x| x.parse::<f64>().unwrap())
        .collect::<Vec<_>>()
        .into_iter();
    cases
        .iter()
        .map(|case| Oracle {
            values: (0..case.n).map(|_| tokens.next().unwrap()).collect(),
            vectors: (0..case.n * case.n)
                .map(|_| tokens.next().unwrap())
                .collect(),
        })
        .collect()
}

fn validate_output(cases: &[Case], output: &str, float32: bool) {
    let oracle = numpy_oracle(cases);
    let observed = output
        .split_whitespace()
        .map(|x| x.parse::<f64>().unwrap())
        .collect::<Vec<_>>();
    let mut cursor = 0;
    let eps = if float32 {
        f64::from(f32::EPSILON)
    } else {
        f64::EPSILON
    };
    for (case, expected) in cases.iter().zip(oracle) {
        let n = case.n;
        let values = &observed[cursor..cursor + n];
        cursor += n;
        let q = &observed[cursor..cursor + n * n];
        cursor += n * n;
        for pair in values.windows(2) {
            assert!(pair[0] <= pair[1], "{} ordering", case.name);
        }
        let scale = case.a.iter().fold(0.0_f64, |x, y| x.max(y.abs()));
        let order = f64::from(u32::try_from(n.max(1)).unwrap());
        let value_bound = 512.0 * order * eps * scale.max(f64::MIN_POSITIVE);
        for (actual, wanted) in values.iter().zip(expected.values) {
            assert!(
                (actual - wanted).abs() <= value_bound.max(scale * 2.0e-14),
                "{} eigenvalue {actual} != {wanted}",
                case.name
            );
        }
        if n == 0 {
            continue;
        }
        let mut residual = vec![0.0; n * n];
        let mut orthogonal = vec![0.0; n * n];
        let mut reconstruction = vec![0.0; n * n];
        for i in 0..n {
            for j in 0..n {
                let mut aq = 0.0;
                let mut qq = 0.0;
                let mut recon = 0.0;
                for k in 0..n {
                    aq += case.a[i * n + k] * q[k * n + j];
                    qq += q[k * n + i] * q[k * n + j];
                    recon += q[i * n + k] * values[k] * q[j * n + k];
                }
                residual[i * n + j] = aq - q[i * n + j] * values[j];
                orthogonal[i * n + j] = qq - if i == j { 1.0 } else { 0.0 };
                reconstruction[i * n + j] = recon - case.a[i * n + j];
            }
        }
        let divisor = scale.max(f64::MIN_POSITIVE);
        let numerical_bound = 2048.0 * order * eps;
        assert!(
            frobenius(&residual) / divisor <= numerical_bound,
            "{} residual",
            case.name
        );
        assert!(
            frobenius(&orthogonal) <= numerical_bound,
            "{} orthogonality",
            case.name
        );
        assert!(
            frobenius(&reconstruction) / divisor <= numerical_bound,
            "{} reconstruction",
            case.name
        );
        if case.name == "repeated" || case.name == "clustered" {
            let (first, last) = if case.name == "repeated" {
                (1, 3)
            } else {
                (0, 2)
            };
            let mut projector_difference = vec![0.0; n * n];
            for i in 0..n {
                for j in 0..n {
                    let mut actual = 0.0;
                    let mut wanted = 0.0;
                    for k in first..last {
                        actual += q[i * n + k] * q[j * n + k];
                        wanted += expected.vectors[i * n + k] * expected.vectors[j * n + k];
                    }
                    projector_difference[i * n + j] = actual - wanted;
                }
            }
            assert!(
                frobenius(&projector_difference) <= numerical_bound,
                "{} invariant-subspace projector",
                case.name
            );
        }
    }
    assert_eq!(cursor, observed.len());
}

#[test]
fn public_decomposition_matches_numpy_and_invariants_for_both_types_o0_o2() {
    for float32 in [false, true] {
        let cases = cases(float32);
        let source = emitter_source(&cases, float32);
        for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
            validate_output(&cases, &compile_and_run(&source, optimization), float32);
        }
    }
}

#[test]
fn fast_paths_sort_precedence_signed_zero_and_preservation_are_exact() {
    let source = r"
package consumer;import linearAlgebra as la;
int main(){
 Matrix<float64>d=[3.0,0.0,-0.0;0.0,-0.0,0.0;-0.0,0.0,-2.0];var x=la.symmetricEigen(d);
 if(x.values[1]!=-2.0||x.values[2]!=0.0||x.values[3]!=3.0||1.0/x.values[2]!=1.0/0.0){return 1;}
 if(x.vectors[3,1]!=1.0||x.vectors[2,2]!=1.0||x.vectors[1,3]!=1.0){return 2;}
 if(d[1,1]!=3.0||d[2,2]!=-0.0||d[3,3]!=-2.0){return 3;}
 Matrix<float64>s=[7.0];var y=la.symmetricEigen(s);if(y.values[1]!=7.0||y.vectors[1,1]!=1.0||s[1,1]!=7.0){return 4;}
 Matrix<float64>e=matrixFilled<float64>(0,0,0.0);var z=la.symmetricEigen(e);if(dimension(z.values)!=0||rows(z.vectors)!=0||columns(z.vectors)!=0){return 5;}
 float64 q=0.0;Matrix<float64>nanAsymmetric=[1.0,q/q;2.0,3.0];int caught=0;
 try{var ignored=la.symmetricEigen(nanAsymmetric);}catch(la.NonFiniteMatrixException error){caught=1;}catch(la.NotSymmetricMatrixException error){return 6;}if(caught!=1){return 7;}
 Matrix<float64>infAsymmetric=[1.0,1.0/q;2.0,3.0];caught=0;try{var ignored=la.symmetricEigen(infAsymmetric);}catch(la.NonFiniteMatrixException error){caught=1;}if(caught!=1){return 8;}
 Matrix<float64>almost=[1.0,1.0000000000000002;1.0,2.0];caught=0;try{var ignored=la.symmetricEigen(almost);}catch(la.NotSymmetricMatrixException error){caught=1;}if(caught!=1){return 9;}
 Matrix<float32>f=[float32(2.0),float32(1.0);float32(1.0),float32(3.0)];var g=la.symmetricEigen<float32>(f);if(g.values[1]>g.values[2]||f[1,2]!=float32(1.0)){return 10;}
 return 0;
}
";
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        compile_and_run(source, optimization);
    }
}

#[test]
fn rescale_failure_and_non_square_shape_guard_are_observable() {
    let failure = r"package consumer;import linearAlgebra as la;int main(){float64 m=1.7976931348623157e308;Matrix<float64>a=[m,m;m,m];try{var x=la.symmetricEigen(a);}catch(la.NumericalConvergenceException e){return 0;}return 1;}";
    compile_and_run(failure, OptimizationLevel::O0);

    let directory = Directory::new("shape");
    let entry = directory.imported("package consumer;import linearAlgebra as la;int main(){Matrix<float64>a=[1.0,2.0];var x=la.symmetricEigen(a);return 0;}");
    let compilation =
        compile_session(CompilationSession::discover(&entry).unwrap(), &[Emit::Llvm]).unwrap();
    let executable = directory.0.join("shape-guard");
    ClangToolchain::default()
        .link_executable(&compilation.llvm, &executable)
        .unwrap();
    assert!(!Command::new(executable).status().unwrap().success());
}

#[test]
fn surface_resources_and_lowering_are_closed() {
    assert_eq!(
        LIBRARY
            .matches("public struct SymmetricEigen<T: Storable>")
            .count(),
        1
    );
    assert_eq!(
        LIBRARY
            .matches("public SymmetricEigen<T> symmetricEigen<T: IEEEFloat>(")
            .count(),
        1
    );
    for forbidden in [
        "symmetricEigenvalues",
        "symmetricEigenInPlace",
        "eigen opcode",
        "characteristic polynomial",
    ] {
        assert!(!LIBRARY.contains(forbidden), "{forbidden}");
    }
    let start = LIBRARY
        .find("public SymmetricEigen<T> symmetricEigen<T: IEEEFloat>(")
        .unwrap();
    let end = LIBRARY[start..]
        .find("BidiagonalShift<T> bidiagonalWilkinsonShift")
        .unwrap()
        + start;
    let body = &LIBRARY[start..end];
    for forbidden in [
        "copyMatrixForFactorization",
        "qr<",
        "svd<",
        "LAPACK",
        "BLAS",
        "Matrix<T> diagonal",
    ] {
        assert!(!body.contains(forbidden), "{forbidden}");
    }

    let directory = Directory::new("lowering");
    let entry = directory.imported("package consumer;import linearAlgebra as la;int main(){Matrix<float64>a=[2.0,1.0;1.0,3.0];var x=la.symmetricEigen(a);Matrix<float32>b=[float32(2.0),float32(1.0);float32(1.0),float32(3.0)];var y=la.symmetricEigen(b);return int(dimension(x.values)+dimension(y.values)-4);}");
    let compilation = compile_session(
        CompilationSession::discover(&entry).unwrap(),
        &[Emit::Mir, Emit::Ssa, Emit::Llvm],
    )
    .unwrap();
    for residue in [
        "GenericParam(",
        "witness",
        "vtable",
        "boxing",
        "LAPACK",
        "BLAS",
        "llvm.matrix",
    ] {
        assert!(
            !compilation.dumps[&Emit::Mir].contains(residue),
            "MIR {residue}"
        );
        assert!(
            !compilation.dumps[&Emit::Ssa].contains(residue),
            "SSA {residue}"
        );
        assert!(!compilation.llvm.contains(residue), "LLVM {residue}");
    }
    assert!(!compilation.llvm.contains("TypeId"));
    for symbol in [
        "symmetricEigen__gfFloat64",
        "symmetricEigen__gfFloat32",
        "reduceSymmetricTridiagonal__gfFloat64",
        "convergeSymmetricTridiagonalState__gfFloat64",
    ] {
        assert!(compilation.llvm.contains(symbol), "{symbol}");
    }
}

#[test]
fn general_diagonal_and_empty_paths_use_the_exact_backing_budgets() {
    for (label, source, allocations) in [
        (
            "general",
            "int main(){Matrix<float64>a=[2.0,1.0,0.5;1.0,3.0,-1.0;0.5,-1.0,4.0];var x=symmetricEigen(a);return int(dimension(x.values)-3);}",
            7,
        ),
        (
            "diagonal",
            "int main(){Matrix<float64>a=[3.0,0.0;0.0,1.0];var x=symmetricEigen(a);return int(dimension(x.values)-2);}",
            3,
        ),
        (
            "empty",
            "int main(){Matrix<float64>a=matrixFilled<float64>(0,0,0.0);var x=symmetricEigen(a);return int(dimension(x.values));}",
            0,
        ),
    ] {
        for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
            let directory = Directory::new(label);
            let entry = directory.white_box(source);
            let compilation = compile_session_with_optimization(
                CompilationSession::discover(&entry).unwrap(),
                &[Emit::Llvm],
                optimization,
            )
            .unwrap();
            let guarded = compilation.llvm.replace(
                "  %process_status = trunc i64 %aether_result to i32",
                &format!("  %allocs = load i64, ptr @aether_heap_alloc_count\n  %frees = load i64, ptr @aether_heap_free_count\n  %alloc_ok = icmp eq i64 %allocs, {allocations}\n  %free_ok = icmp eq i64 %frees, {allocations}\n  %heap_ok = and i1 %alloc_ok, %free_ok\n  %result_ok = icmp eq i64 %aether_result, 0\n  %all_ok = and i1 %heap_ok, %result_ok\n  %process_status = select i1 %all_ok, i32 0, i32 99"),
            );
            assert_ne!(guarded, compilation.llvm);
            let executable = directory.0.join("allocation-check");
            ClangToolchain::default()
                .with_optimization(optimization)
                .link_executable(&guarded, &executable)
                .unwrap();
            assert_eq!(
                Command::new(executable).status().unwrap().code(),
                Some(0),
                "{label} {optimization:?}"
            );
        }
    }
}
