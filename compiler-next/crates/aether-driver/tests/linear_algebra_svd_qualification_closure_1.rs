//! LINEAR-ALGEBRA-SVD-QUALIFICATION-CLOSURE-1 independent qualification.

use std::{
    fmt::Write as _,
    fs,
    io::Write as _,
    path::PathBuf,
    process::{Command, Stdio},
    time::Instant,
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
            "aether-svd-closure-{label}-{}-{}",
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

    fn white_box(&self, source: &str) -> PathBuf {
        let entry = self.0.join("linearAlgebra.ae");
        fs::write(&entry, format!("{LIBRARY}\n{source}\n")).unwrap();
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
    rows: usize,
    columns: usize,
    values: Vec<f64>,
}

impl Case {
    fn new(name: &'static str, rows: usize, columns: usize, values: Vec<f64>) -> Self {
        assert_eq!(values.len(), rows * columns);
        Self {
            name,
            rows,
            columns,
            values,
        }
    }

    fn diagonal(name: &'static str, values: &[f64]) -> Self {
        let size = values.len();
        let mut matrix = vec![0.0; size * size];
        for (i, value) in values.iter().enumerate() {
            matrix[i * size + i] = *value;
        }
        Self::new(name, size, size, matrix)
    }
}

fn dense(name: &'static str, rows: usize, columns: usize, scale: f64) -> Case {
    let values = (0..rows * columns)
        .map(|p| {
            let row = p / columns + 1;
            let column = p % columns + 1;
            let integer =
                f64::from(u32::try_from((row * 37 + column * 19 + row * column * 7) % 43).unwrap())
                    - 21.0;
            let row_value = f64::from(u32::try_from(row).unwrap());
            let column_value = f64::from(u32::try_from(column).unwrap());
            scale * (integer / 11.0 + (row_value - column_value) / 97.0)
        })
        .collect();
    Case::new(name, rows, columns, values)
}

fn fixtures64() -> Vec<Case> {
    let mut cases = vec![
        dense("square_dense_8", 8, 8, 1.0),
        dense("tall_dense_12x5", 12, 5, 1.0),
        dense("wide_dense_5x12", 5, 12, 1.0),
        dense("strong_tall_24x3", 24, 3, 1.0),
        dense("strong_wide_3x24", 3, 24, 1.0),
        dense("moderate_dense_16x12", 16, 12, 0.25),
        Case::new("zero_6x4", 6, 4, vec![0.0; 24]),
        Case::diagonal("mixed_sign_diagonal", &[-9.0, 7.0, -3.0, 0.5]),
        Case::diagonal("repeated_singular_values", &[5.0, -5.0, 2.0, -2.0, 0.0]),
        Case::diagonal(
            "near_singular_values",
            &[1.0 + 2.0e-12, 1.0 + 1.0e-12, 1.0, 0.25],
        ),
        Case::diagonal(
            "separated_singular_values",
            &[1.0e120, 1.0e40, 1.0, 1.0e-80],
        ),
        Case::diagonal("ill_conditioned", &[1.0, 1.0e-6, 1.0e-12, 1.0e-15]),
        Case::diagonal("subnormal", &[1.0e-320, -4.0e-321, 5.0e-324]),
        dense("large_magnitude", 5, 4, 1.0e306),
        dense("small_magnitude", 5, 4, 1.0e-200),
    ];

    let hadamard = [
        0.5, 0.5, 0.5, 0.5, 0.5, -0.5, 0.5, -0.5, 0.5, 0.5, -0.5, -0.5, 0.5, -0.5, -0.5, 0.5,
    ];
    cases.push(Case::new("orthogonal", 4, 4, hadamard.to_vec()));

    let mut dependent = dense("dependent_rows_columns", 7, 6, 1.0);
    for column in 0..dependent.columns {
        dependent.values[5 * dependent.columns + column] =
            dependent.values[column] + 2.0 * dependent.values[dependent.columns + column];
    }
    for row in 0..dependent.rows {
        dependent.values[row * dependent.columns + 5] = dependent.values[row * dependent.columns]
            - dependent.values[row * dependent.columns + 1];
    }
    cases.push(dependent);
    cases
}

fn fixtures32() -> Vec<Case> {
    let mut cases = vec![
        dense("square_dense_7_f32", 7, 7, 1.0),
        dense("tall_14x4_f32", 14, 4, 1.0),
        dense("wide_4x14_f32", 4, 14, 1.0),
        Case::new("zero_f32", 5, 3, vec![0.0; 15]),
        Case::diagonal("mixed_repeated_f32", &[-8.0, 8.0, -2.0, 0.0]),
        Case::diagonal("near_f32", &[1.000_03, 1.000_02, 1.000_01, 1.0]),
        Case::diagonal("separated_f32", &[1.0e30, 1.0e10, 1.0, 1.0e-20]),
        Case::diagonal("subnormal_f32", &[1.0e-44, -5.0e-45, 1.401_298_464e-45]),
        dense("large_f32", 5, 3, 1.0e36),
        dense("small_f32", 5, 3, 1.0e-30),
    ];
    let mut dependent = dense("dependent_f32", 6, 5, 1.0);
    for column in 0..dependent.columns {
        dependent.values[4 * dependent.columns + column] =
            dependent.values[column] - dependent.values[dependent.columns + column];
    }
    cases.push(dependent);
    cases
}

/// NumPy/LAPACK is deliberately invoked by the host-side qualification only.
/// The product source, generated Aether consumer, and linked executable never
/// import or link the oracle.
fn numpy_singular_values(cases: &[Case], float32: bool) -> Vec<Vec<f64>> {
    let script = r#"
import sys
import numpy as np
dtype = np.float32 if sys.argv[1] == "32" else np.float64
lines = iter(sys.stdin.read().splitlines())
count = int(next(lines))
for _ in range(count):
    rows, columns = map(int, next(lines).split())
    values = np.fromstring(next(lines), sep=" ", dtype=dtype)
    matrix = values.reshape((rows, columns))
    singular = np.linalg.svd(matrix, compute_uv=False)
    print(" ".join(format(float(value), ".17e") for value in singular))
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
        writeln!(input, "{}", cases.len()).unwrap();
        for case in cases {
            writeln!(input, "{} {}", case.rows, case.columns).unwrap();
            for value in &case.values {
                write!(input, "{value:.17e} ").unwrap();
            }
            writeln!(input).unwrap();
        }
    }
    let output = child.wait_with_output().unwrap();
    assert!(
        output.status.success(),
        "NumPy oracle failed: {}",
        String::from_utf8_lossy(&output.stderr)
    );
    let rows: Vec<Vec<f64>> = String::from_utf8(output.stdout)
        .unwrap()
        .lines()
        .map(|line| {
            line.split_whitespace()
                .map(|value| value.parse().unwrap())
                .collect()
        })
        .collect();
    assert_eq!(rows.len(), cases.len());
    rows
}

fn matrix_literal(case: &Case, float32: bool) -> String {
    let mut result = String::from("[");
    for row in 0..case.rows {
        if row != 0 {
            result.push(';');
        }
        for column in 0..case.columns {
            if column != 0 {
                result.push(',');
            }
            let value = case.values[row * case.columns + column];
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

fn vector_literal(values: &[f64], float32: bool) -> String {
    let mut result = String::from("[");
    for (index, value) in values.iter().enumerate() {
        if index != 0 {
            result.push(',');
        }
        if float32 {
            write!(result, "float32({value:.17e})").unwrap();
        } else {
            write!(result, "{value:.17e}").unwrap();
        }
    }
    result.push(']');
    result
}

fn qualification_source(cases: &[Case], oracle: &[Vec<f64>], float32: bool) -> String {
    let scalar = if float32 { "float32" } else { "float64" };
    let tolerance = if float32 {
        "float32(3.0e-4)"
    } else {
        "2.0e-12"
    };
    let mut source = format!(
        r"package consumer;import linearAlgebra as la;
int validate(ref Matrix<{scalar}> a,ref Vector<{scalar},Column> expected,{scalar} tolerance){{
 usize m=rows(*a);usize n=columns(*a);usize k=m;if(n<k){{k=n;}}
 la.SVD<{scalar}> f=la.svd<{scalar}>(a);
 if(rows(f.U)!=m||columns(f.U)!=k||dimension(f.S)!=k||rows(f.Vt)!=k||columns(f.Vt)!=n){{return 1;}}
 {scalar} scale=0;usize i=1;while(i<=m){{usize j=1;while(j<=n){{{scalar} av=abs((*a)[i,j]);if(scale<av){{scale=av;}}j=j+1;}}i=i+1;}}
 i=1;while(i<=k){{
  if((f.S[i]-f.S[i])!=0||f.S[i]<0||(i>1&&f.S[i-1]<f.S[i])){{return 2;}}
  {scalar} sn=f.S[i];{scalar} en=(*expected)[i];if(scale!=0){{sn=sn/scale;en=en/scale;}}
  if(abs(sn-en)>tolerance*(1+abs(en))){{return 3;}}
  usize j=1;while(j<=k){{{scalar} uu=0;{scalar} vv=0;usize q=1;
   while(q<=m){{uu=uu+f.U[q,i]*f.U[q,j];q=q+1;}}q=1;while(q<=n){{vv=vv+f.Vt[i,q]*f.Vt[j,q];q=q+1;}}
   {scalar} wanted=0;if(i==j){{wanted=1;}}if(abs(uu-wanted)>tolerance||abs(vv-wanted)>tolerance){{return 4;}}j=j+1;}}
  i=i+1;
 }}
 i=1;while(i<=m){{usize j=1;while(j<=n){{{scalar} reconstructed=0;usize q=1;
  while(q<=k){{if(scale==0){{reconstructed=reconstructed+f.U[i,q]*f.S[q]*f.Vt[q,j];}}else{{reconstructed=reconstructed+f.U[i,q]*(f.S[q]/scale)*f.Vt[q,j];}}q=q+1;}}
  {scalar} wanted=(*a)[i,j];if(scale!=0){{wanted=wanted/scale;}}if((reconstructed-reconstructed)!=0||abs(reconstructed-wanted)>tolerance*(1+abs(wanted))){{return 5;}}j=j+1;}}i=i+1;}}
 return 0;
}}
int main(){{int result=0;
"
    );
    for (index, (case, expected)) in cases.iter().zip(oracle).enumerate() {
        assert_eq!(expected.len(), case.rows.min(case.columns));
        writeln!(
            source,
            "Matrix<{scalar}> a{index}={};Vector<{scalar},Column> s{index}={};result=validate(&a{index},&s{index},{tolerance});if(result!=0){{return {};}}",
            matrix_literal(case, float32),
            vector_literal(expected, float32),
            10 + index * 10
        )
        .unwrap();
        let _ = case.name;
    }
    source.push_str("return 0;}\n");
    source
}

fn run_public(source: &str, optimization: OptimizationLevel) {
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
    let started = Instant::now();
    let status = Command::new(executable).status().unwrap();
    eprintln!(
        "SVD qualification {optimization:?}: {} ms",
        started.elapsed().as_millis()
    );
    assert_eq!(status.code(), Some(0), "{optimization:?}");
}

#[test]
fn numpy_oracle_and_adversarial_invariants_pass_for_both_precisions_at_o0_o2() {
    let cases64 = fixtures64();
    let oracle64 = numpy_singular_values(&cases64, false);
    let source64 = qualification_source(&cases64, &oracle64, false);
    let cases32 = fixtures32();
    let oracle32 = numpy_singular_values(&cases32, true);
    let source32 = qualification_source(&cases32, &oracle32, true);
    let source64 = source64
        .replace("int validate(", "int validate64(")
        .replace("result=validate(", "result=validate64(")
        .replace("int main()", "int qualify64()");
    let source32 = source32
        .replace("package consumer;import linearAlgebra as la;\n", "")
        .replace("int validate(", "int validate32(")
        .replace("result=validate(", "result=validate32(");
    let source = format!("{source64}\n{source32}");
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        run_public(
            &source.replace(
                "int main(){int result=0;",
                "int main(){int first=qualify64();if(first!=0){return first;}int result=0;",
            ),
            optimization,
        );
    }
}

fn instrument_heap(llvm: &str, allocations: u64, frees: u64) -> String {
    let guarded = llvm.replace(
        "  %process_status = trunc i64 %aether_result to i32",
        &format!(
            "  %allocs = load i64, ptr @aether_heap_alloc_count\n  %frees = load i64, ptr @aether_heap_free_count\n  %alloc_ok = icmp eq i64 %allocs, {allocations}\n  %free_ok = icmp eq i64 %frees, {frees}\n  %heap_ok = and i1 %alloc_ok, %free_ok\n  %result_ok = icmp eq i64 %aether_result, 0\n  %all_ok = and i1 %heap_ok, %result_ok\n  %process_status = select i1 %all_ok, i32 0, i32 99"
        ),
    );
    assert_ne!(guarded, llvm);
    guarded
}

fn run_instrumented(source: &str, white_box: bool, allocations: u64, frees: u64) {
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        let directory = Directory::new("resources");
        let entry = if white_box {
            directory.white_box(source)
        } else {
            directory.imported(source)
        };
        let compilation = compile_session_with_optimization(
            CompilationSession::discover(&entry).unwrap(),
            &[Emit::Llvm],
            optimization,
        )
        .unwrap();
        let guarded = instrument_heap(&compilation.llvm, allocations, frees);
        let executable = directory.0.join("resource-check");
        ClangToolchain::default()
            .with_optimization(optimization)
            .link_executable(&guarded, &executable)
            .unwrap();
        let status = Command::new(executable).status().unwrap().code();
        if status != Some(0) {
            let counts: Vec<_> = ["heap_alloc", "heap_free"]
                .iter()
                .map(|name| {
                    let probed = compilation.llvm.replace(
                        "  ret i32 %process_status",
                        &format!("  %probe = load i64, ptr @aether_{name}_count\n  %probe32 = trunc i64 %probe to i32\n  ret i32 %probe32"),
                    );
                    let probe = directory.0.join(format!("probe-{name}"));
                    ClangToolchain::default()
                        .with_optimization(optimization)
                        .link_executable(&probed, &probe)
                        .unwrap();
                    Command::new(probe).status().unwrap().code()
                })
                .collect();
            eprintln!("observed heap allocation/free counts: {counts:?}");
        }
        assert_eq!(
            status,
            Some(0),
            "resource check failed: expected {allocations} allocations and {frees} frees"
        );
    }
}

#[test]
fn failures_preserve_input_and_cleanup_without_partial_results() {
    run_instrumented(
        "package consumer;import linearAlgebra as la;int main(){float64 z=0.0;Matrix<float64>a=[1.0,z/z;3.0,4.0];int caught=0;try{var result=la.svd(a);}catch(la.NonFiniteMatrixException error){caught=1;}if(caught!=1||a[1,1]!=1.0||a[2,2]!=4.0){return 1;}return 0;}",
        false,
        3,
        3,
    );
    run_instrumented(
        "int main(){Vector<float64,Column>d=[3.0,2.0];Vector<float64,Column>e=[1.0];Matrix<float64>u=identity<float64>(2);Matrix<float64>v=identity<float64>(2);int caught=0;try{var result=bidiagonalSVDQRWithMaxSteps<float64>(BidiagonalSVDSeed<float64>(d,e,u,v,BidiagonalOrientation(false)),0);}catch(NumericalConvergenceException error){caught=1;}if(caught!=1){return 1;}return 0;}",
        true,
        5,
        5,
    );
    run_instrumented(
        "int main(){float64 z=0.0;Vector<float64,Column>d=[1.0,z/z];Vector<float64,Column>e=[1.0];Matrix<float64>u=identity<float64>(2);Matrix<float64>v=identity<float64>(2);int caught=0;try{var result=bidiagonalSVDQRWithMaxSteps<float64>(BidiagonalSVDSeed<float64>(d,e,u,v,BidiagonalOrientation(false)),4);}catch(NumericalConvergenceException error){caught=1;}if(caught!=1){return 1;}return 0;}",
        true,
        5,
        5,
    );
}

#[test]
fn empty_extents_resources_budget_and_ir_remain_closed() {
    let source = "package consumer;import linearAlgebra as la;int main(){Matrix<float64>a=[1.0,2.0;3.0,4.0;5.0,6.0];var f=la.svd(a);return int(rows(f.U)+columns(f.Vt)-5);}";
    run_instrumented(source, false, 8, 8);

    let directory = Directory::new("ir");
    let entry = directory.imported("package consumer;import linearAlgebra as la;int main(){Matrix<float64>a=[1.0,2.0;3.0,4.0];var x=la.svd(a);Matrix<float32>b=[float32(2.0)];var y=la.svd(b);return int(dimension(x.S)+dimension(y.S)-3);}");
    let compilation = compile_session(
        CompilationSession::discover(&entry).unwrap(),
        &[Emit::Mir, Emit::Ssa, Emit::Llvm],
    )
    .unwrap();
    for residue in ["GenericParam(", "witness", "vtable"] {
        assert!(
            !compilation.dumps[&Emit::Mir].contains(residue),
            "MIR: {residue}"
        );
        assert!(
            !compilation.dumps[&Emit::Ssa].contains(residue),
            "SSA: {residue}"
        );
        assert!(!compilation.llvm.contains(residue), "LLVM: {residue}");
    }
    for residue in ["TypeId", "LAPACK", "lapack"] {
        assert!(!compilation.llvm.contains(residue), "LLVM: {residue}");
    }
    assert!(compilation.llvm.contains("assembleSVDWorkspace__gfFloat64"));
    assert!(compilation.llvm.contains("assembleSVDWorkspace__gfFloat32"));
    assert!(LIBRARY.contains("usize maxSteps = 64 * (k * k);"));
    assert!(!LIBRARY.contains("Matrix<T> Sigma"));
    assert!(!LIBRARY.contains("svdInPlace"));

    let empty = "package consumer;import linearAlgebra as la;int main(){Matrix<float64>a=matrixFilled<float64>(7,0,0.0);var x=la.svd(a);Matrix<float64>b=matrixFilled<float64>(0,9,0.0);var y=la.svd(b);if(rows(x.U)!=7||columns(x.U)!=0||columns(y.Vt)!=9||dimension(x.S)!=0||dimension(y.S)!=0){return 1;}return 0;}";
    run_instrumented(empty, false, 0, 0);
}
