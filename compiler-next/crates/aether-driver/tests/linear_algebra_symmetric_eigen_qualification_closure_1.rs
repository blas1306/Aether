//! LINEAR-ALGEBRA-SYMMETRIC-EIGEN-QUALIFICATION-CLOSURE-1 joint qualification.

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
            "aether-symmetric-eigen-closure-{label}-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, std::sync::atomic::Ordering::Relaxed)
        ));
        fs::create_dir(&path).unwrap();
        Self(path)
    }

    fn imported(&self, source: &str) -> PathBuf {
        fs::write(self.0.join("linearAlgebra.ae"), LIBRARY).unwrap();
        let entry = self.0.join("main.ae");
        fs::write(&entry, source).unwrap();
        entry
    }
}

impl Drop for Directory {
    fn drop(&mut self) {
        fs::remove_dir_all(&self.0).unwrap();
    }
}

#[derive(Clone)]
struct Case {
    name: &'static str,
    n: usize,
    a: Vec<f64>,
    projector: Option<(usize, usize)>,
}

impl Case {
    fn new(name: &'static str, n: usize, a: Vec<f64>) -> Self {
        assert_eq!(a.len(), n * n);
        Self {
            name,
            n,
            a,
            projector: None,
        }
    }

    fn with_projector(mut self, first: usize, end: usize) -> Self {
        self.projector = Some((first, end));
        self
    }
}

fn orthogonal_spectrum(name: &'static str, spectrum: &[f64]) -> Case {
    assert_eq!(spectrum.len(), 4);
    let h = [
        0.5, 0.5, 0.5, 0.5, 0.5, -0.5, 0.5, -0.5, 0.5, 0.5, -0.5, -0.5, 0.5, -0.5, -0.5, 0.5,
    ];
    let mut a = vec![0.0; 16];
    for i in 0..4 {
        for j in 0..=i {
            let value = (0..4)
                .map(|k| h[i * 4 + k] * spectrum[k] * h[j * 4 + k])
                .sum();
            a[i * 4 + j] = value;
            a[j * 4 + i] = value;
        }
    }
    Case::new(name, 4, a)
}

fn fixtures(float32: bool) -> Vec<Case> {
    let cluster = if float32 { 3.0e-5 } else { 3.0e-11 };
    let large = if float32 { 1.0e30 } else { 1.0e200 };
    let small = if float32 { 1.0e-30 } else { 1.0e-200 };
    let subnormal = if float32 { 1.0e-39 } else { 1.0e-310 };
    vec![
        Case::new("empty", 0, vec![]),
        Case::new("scalar", 1, vec![-7.0]),
        Case::new(
            "diagonal",
            4,
            vec![
                4.0, 0.0, 0.0, 0.0, 0.0, -3.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 2.0,
            ],
        ),
        Case::new("zero", 4, vec![0.0; 16]),
        Case::new(
            "dense-simple",
            6,
            vec![
                7.0, 2.0, -1.0, 0.5, 1.0, -0.25, 2.0, 6.0, 1.5, -1.0, 0.25, 0.75, -1.0, 1.5, 5.0,
                2.0, -0.5, 1.25, 0.5, -1.0, 2.0, 4.0, 1.0, -1.5, 1.0, 0.25, -0.5, 1.0, 3.0, 0.8,
                -0.25, 0.75, 1.25, -1.5, 0.8, 2.0,
            ],
        ),
        orthogonal_spectrum("repeated", &[-2.0, 1.0, 1.0, 5.0]).with_projector(1, 3),
        orthogonal_spectrum("clustered", &[1.0, 1.0 + cluster, 3.0, 6.0]).with_projector(0, 2),
        orthogonal_spectrum("positive-definite", &[0.5, 2.0, 4.0, 9.0]),
        orthogonal_spectrum("semidefinite-singular", &[0.0, 0.0, 2.0, 7.0]),
        orthogonal_spectrum("singular-indefinite", &[-5.0, 0.0, 0.0, 4.0]),
        orthogonal_spectrum("indefinite", &[-8.0, -1.0, 2.0, 9.0]),
        Case::new(
            "split-blocks",
            6,
            vec![
                2.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 4.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, -3.0, 0.5,
                0.0, 0.0, 0.0, 0.0, 0.5, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 6.0, -2.0, 0.0, 0.0,
                0.0, 0.0, -2.0, 5.0,
            ],
        ),
        Case::new(
            "uniform-large",
            3,
            vec![
                3.0 * large,
                large,
                0.5 * large,
                large,
                2.0 * large,
                -0.25 * large,
                0.5 * large,
                -0.25 * large,
                4.0 * large,
            ],
        ),
        Case::new(
            "uniform-small",
            3,
            vec![
                3.0 * small,
                small,
                0.5 * small,
                small,
                2.0 * small,
                -0.25 * small,
                0.5 * small,
                -0.25 * small,
                4.0 * small,
            ],
        ),
        Case::new(
            "uniform-subnormal",
            2,
            vec![2.0 * subnormal, subnormal, subnormal, 3.0 * subnormal],
        ),
    ]
}

fn cast_cases(cases: &mut [Case], float32: bool) {
    if float32 {
        for case in cases {
            for value in &mut case.a {
                #[allow(clippy::cast_possible_truncation)]
                let rounded = *value as f32;
                *value = f64::from(rounded);
            }
        }
    }
}

fn literal(case: &Case, float32: bool) -> String {
    if case.n == 0 {
        let scalar = if float32 { "float32" } else { "float64" };
        return format!("matrixFilled<{scalar}>(0,0,{scalar}(0.0))");
    }
    let mut result = String::from("[");
    for i in 0..case.n {
        if i != 0 {
            result.push(';');
        }
        for j in 0..case.n {
            if j != 0 {
                result.push(',');
            }
            let value = case.a[i * case.n + j];
            if float32 {
                write!(result, "float32({value:.17e})").unwrap();
            } else {
                write!(result, "{value:.17e}").unwrap();
            }
        }
    }
    result.push(']');
    result
}

fn emitter(cases: &[Case], float32: bool) -> String {
    let scalar = if float32 { "float32" } else { "float64" };
    let mut source = String::from("package consumer;import linearAlgebra as la;int main(){");
    for (index, case) in cases.iter().enumerate() {
        write!(source, "Matrix<{scalar}>a{index}={};la.SymmetricEigen<{scalar}>x{index}=la.symmetricEigen(a{index});usize i{index}=1;while(i{index}<=dimension(x{index}.values)){{println(x{index}.values[i{index}]);i{index}=i{index}+1;}}i{index}=1;while(i{index}<=rows(x{index}.vectors)){{usize j{index}=1;while(j{index}<=columns(x{index}.vectors)){{println(x{index}.vectors[i{index},j{index}]);j{index}=j{index}+1;}}i{index}=i{index}+1;}}", literal(case, float32)).unwrap();
    }
    source.push_str("return 0;}");
    source
}

struct Oracle {
    values: Vec<f64>,
    vectors: Vec<f64>,
}

fn numpy(cases: &[Case], float32: bool) -> Vec<Oracle> {
    let script = r#"
import sys
import numpy as np
dtype=np.float32 if sys.argv[1] == "32" else np.float64
tokens=iter(sys.stdin.read().split())
count=int(next(tokens))
for _ in range(count):
 n=int(next(tokens))
 a=np.array([float(next(tokens)) for _ in range(n*n)],dtype=dtype).reshape((n,n))
 values=np.linalg.eigvalsh(a)
 values2,vectors=np.linalg.eigh(a)
 scale=float(np.max(np.abs(a))) if n else 0.0
 if scale:
  np.testing.assert_allclose(values/scale,values2/scale,rtol=32*np.finfo(dtype).eps,atol=32*np.finfo(dtype).eps)
 else:
  assert np.array_equal(values,values2)
 print(*[format(float(x),'.17e') for x in values])
 print(*[format(float(x),'.17e') for x in vectors.ravel()])
"#;
    let mut child = Command::new("python3")
        .args(["-c", script, if float32 { "32" } else { "64" }])
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .expect("qualification requires python3 with NumPy");
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
    assert!(
        output.status.success(),
        "NumPy oracle failed: {}",
        String::from_utf8_lossy(&output.stderr)
    );
    let mut tokens = String::from_utf8(output.stdout)
        .unwrap()
        .split_whitespace()
        .map(|value| value.parse::<f64>().unwrap())
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

fn frobenius(values: &[f64]) -> f64 {
    values.iter().map(|value| value * value).sum::<f64>().sqrt()
}

fn validate(cases: &[Case], oracle: &[Oracle], stdout: &str, float32: bool) {
    let observed: Vec<f64> = stdout
        .split_whitespace()
        .map(|value| value.parse().unwrap())
        .collect();
    let epsilon = if float32 {
        f64::from(f32::EPSILON)
    } else {
        f64::EPSILON
    };
    let least = if float32 {
        f64::from(f32::from_bits(1))
    } else {
        f64::from_bits(1)
    };
    let mut cursor = 0;
    for (case, expected) in cases.iter().zip(oracle) {
        let n = case.n;
        let values = &observed[cursor..cursor + n];
        cursor += n;
        let vectors = &observed[cursor..cursor + n * n];
        cursor += n * n;
        assert!(
            values.windows(2).all(|pair| pair[0] <= pair[1]),
            "{} ordering",
            case.name
        );
        if n == 0 {
            continue;
        }
        let scale = case.a.iter().fold(0.0_f64, |x, y| x.max(y.abs()));
        if scale == 0.0 {
            assert!(
                values
                    .iter()
                    .all(|value| *value == 0.0 && value.is_sign_positive())
            );
        }
        let order = f64::from(u32::try_from(n).unwrap());
        let quantization = if scale == 0.0 { 0.0 } else { least / scale };
        let bound = 8192.0 * order * epsilon + 16.0 * quantization;
        let divisor = if scale == 0.0 { 1.0 } else { scale };
        for (actual, wanted) in values.iter().zip(&expected.values) {
            assert!(
                (actual / divisor - wanted / divisor).abs() <= bound,
                "{} eigenvalue {actual} != {wanted}, bound={bound}",
                case.name
            );
        }
        let normalized_a: Vec<f64> = case.a.iter().map(|value| value / divisor).collect();
        let normalized_values: Vec<f64> = values.iter().map(|value| value / divisor).collect();
        let mut residual = vec![0.0; n * n];
        let mut orthogonal = vec![0.0; n * n];
        let mut reconstruction = vec![0.0; n * n];
        for i in 0..n {
            for j in 0..n {
                let mut aq = 0.0;
                let mut qtq = 0.0;
                let mut recon = 0.0;
                for k in 0..n {
                    aq += normalized_a[i * n + k] * vectors[k * n + j];
                    qtq += vectors[k * n + i] * vectors[k * n + j];
                    recon += vectors[i * n + k] * normalized_values[k] * vectors[j * n + k];
                }
                residual[i * n + j] = aq - vectors[i * n + j] * normalized_values[j];
                orthogonal[i * n + j] = qtq - if i == j { 1.0 } else { 0.0 };
                reconstruction[i * n + j] = recon - normalized_a[i * n + j];
            }
        }
        assert!(frobenius(&residual) <= bound, "{} residual", case.name);
        assert!(
            frobenius(&orthogonal) <= bound,
            "{} orthogonality",
            case.name
        );
        assert!(
            frobenius(&reconstruction) <= bound,
            "{} reconstruction",
            case.name
        );
        if let Some((first, end)) = case.projector {
            let mut difference = vec![0.0; n * n];
            for i in 0..n {
                for j in 0..n {
                    for k in first..end {
                        difference[i * n + j] += vectors[i * n + k] * vectors[j * n + k]
                            - expected.vectors[i * n + k] * expected.vectors[j * n + k];
                    }
                }
            }
            assert!(
                frobenius(&difference) <= 4.0 * bound,
                "{} invariant-subspace projector",
                case.name
            );
        }
    }
    assert_eq!(cursor, observed.len());
}

fn compile_and_run(source: &str, optimization: OptimizationLevel) -> String {
    let directory = Directory::new("numeric");
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
        "{optimization:?}: {}",
        String::from_utf8_lossy(&output.stderr)
    );
    String::from_utf8(output.stdout).unwrap()
}

#[test]
fn end_to_end_oracle_invariants_subspaces_and_scaling_close_at_o0_o2() {
    for float32 in [false, true] {
        let mut cases = fixtures(float32);
        cast_cases(&mut cases, float32);
        let oracle = numpy(&cases, float32);
        let source = emitter(&cases, float32);
        for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
            validate(
                &cases,
                &oracle,
                &compile_and_run(&source, optimization),
                float32,
            );
        }
    }
}

#[test]
fn input_and_two_result_owners_are_independent() {
    let source = r"
package consumer;import linearAlgebra as la;
int main(){
 Matrix<float64>a=[4.0,1.0,-2.0;1.0,3.0,0.5;-2.0,0.5,5.0];
 la.SymmetricEigen<float64>x=la.symmetricEigen(a);la.SymmetricEigen<float64>y=la.symmetricEigen(a);
 float64 yv=y.values[1];float64 yq=y.vectors[1,1];x.values[1]=99.0;x.vectors[1,1]=88.0;
 if(y.values[1]!=yv||y.vectors[1,1]!=yq){return 1;}
 if(a[1,1]!=4.0||a[1,2]!=1.0||a[1,3]!=-2.0||a[2,1]!=1.0||a[2,2]!=3.0||a[2,3]!=0.5||a[3,1]!=-2.0||a[3,2]!=0.5||a[3,3]!=5.0){return 2;}
 Matrix<float32>b=[float32(2.0),float32(1.0);float32(1.0),float32(2.0)];la.SymmetricEigen<float32>z=la.symmetricEigen(b);z.values[1]=float32(7.0);if(b[1,2]!=float32(1.0)){return 3;}
 return 0;
}";
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        compile_and_run(source, optimization);
    }
}

#[test]
fn public_errors_source_and_ir_remain_closed() {
    let errors = r"
package consumer;import linearAlgebra as la;
int main(){float64 z=0.0;int caught=0;
 Matrix<float64>a=[1.0,z/z;2.0,3.0];try{var x=la.symmetricEigen(a);}catch(la.NonFiniteMatrixException e){caught=caught+1;}catch(la.NotSymmetricMatrixException e){return 1;}
 Matrix<float64>b=[1.0,1.0000000000000002;1.0,2.0];try{var x=la.symmetricEigen(b);}catch(la.NotSymmetricMatrixException e){caught=caught+1;}
 Matrix<float64>c=[1.0,1.0/z;2.0,3.0];try{var x=la.symmetricEigen(c);}catch(la.NonFiniteMatrixException e){caught=caught+1;}
 if(caught!=3||a[1,1]!=1.0||b[2,2]!=2.0||c[1,1]!=1.0){return 2;}return 0;}";
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        compile_and_run(errors, optimization);
    }

    let directory = Directory::new("lowering");
    let entry = directory.imported("package consumer;import linearAlgebra as la;int main(){Matrix<float64>a=[2.0,1.0;1.0,3.0];var x=la.symmetricEigen(a);Matrix<float32>b=[float32(2.0),float32(1.0);float32(1.0),float32(3.0)];var y=la.symmetricEigen(b);return int(dimension(x.values)+dimension(y.values)-4);}");
    let compilation = compile_session(
        CompilationSession::discover(&entry).unwrap(),
        &[Emit::Mir, Emit::Ssa, Emit::Llvm],
    )
    .unwrap();
    for residue in ["GenericParam(", "witness", "vtable"] {
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
    for residue in ["TypeId", "LAPACK", "BLAS", "llvm.matrix", "eigen_opcode"] {
        assert!(!compilation.llvm.contains(residue), "LLVM {residue}");
    }
    for symbol in [
        "symmetricEigen__gfFloat64",
        "symmetricEigen__gfFloat32",
        "reduceSymmetricTridiagonal__gfFloat64",
        "convergeSymmetricTridiagonalState__gfFloat64",
    ] {
        assert!(compilation.llvm.contains(symbol), "{symbol}");
    }

    let public_body = LIBRARY
        .split("public SymmetricEigen<T> symmetricEigen<T: IEEEFloat>(ref Matrix<T> A) {")
        .nth(1)
        .unwrap()
        .split("BidiagonalShift<T> bidiagonalWilkinsonShift")
        .next()
        .unwrap();
    for forbidden in [
        "characteristic",
        "svd<",
        "qr<",
        "Matrix<T> tridiagonal",
        "Matrix<T> diagonal",
        "LAPACK",
        "BLAS",
    ] {
        assert!(!public_body.contains(forbidden), "{forbidden}");
    }
    assert_eq!(LIBRARY.matches("public struct SymmetricEigen").count(), 1);
    assert_eq!(
        LIBRARY
            .matches("public SymmetricEigen<T> symmetricEigen<T: IEEEFloat>(")
            .count(),
        1
    );
}
