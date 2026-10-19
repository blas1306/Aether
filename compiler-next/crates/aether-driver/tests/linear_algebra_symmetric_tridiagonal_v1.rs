//! LINEAR-ALGEBRA-SYMMETRIC-TRIDIAGONAL-V1 internal qualification.

use std::{fmt::Write, fs, path::PathBuf, process::Command};

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
            "aether-symmetric-tridiagonal-{label}-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, std::sync::atomic::Ordering::Relaxed)
        ));
        fs::create_dir(&path).unwrap();
        Self(path)
    }

    fn white_box(&self, source: &str) -> PathBuf {
        let path = self.0.join("linearAlgebra.ae");
        fs::write(&path, format!("{LIBRARY}\n{source}\n")).unwrap();
        path
    }

    fn imported(&self, source: &str) -> PathBuf {
        fs::write(self.0.join("linearAlgebra.ae"), LIBRARY).unwrap();
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

fn compile_and_run(source: &str, optimization: OptimizationLevel) -> String {
    let directory = Directory::new("native");
    let entry = directory.white_box(source);
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
fn aggregates_and_helpers_are_module_private() {
    for expression in [
        "int probe(la.CompactSymmetricTridiagonalReduction<float64> x){return 0;}",
        "int probe(la.SymmetricTridiagonalSeed<float64> x){return 0;}",
        "int probe(Matrix<float64> x){var y=la.compactSymmetricTridiagonalReduction(x);return 0;}",
        "int probe(Matrix<float64> x){var y=la.symmetricTridiagonalSeedInPlace(x);return 0;}",
    ] {
        let directory = Directory::new("visibility");
        let source = format!(
            "package consumer;import linearAlgebra as la;{expression}int main(){{return 0;}}"
        );
        let diagnostics = compile_session(
            CompilationSession::discover(&directory.imported(&source)).unwrap(),
            &[],
        )
        .unwrap_err();
        let text = diagnostics
            .iter()
            .map(|diagnostic| diagnostic.message.as_str())
            .collect::<Vec<_>>()
            .join("\n");
        assert!(
            text.contains("internal to its module") || text.contains("unknown"),
            "{text}"
        );
    }
}

#[test]
fn source_matches_the_closed_compact_algorithm() {
    for declaration in [
        "struct CompactSymmetricTridiagonalReduction<T: Storable>",
        "struct SymmetricTridiagonalSeed<T: Storable>",
        "int reduceSymmetricTridiagonal<T: IEEEFloat>(",
        "compactSymmetricTridiagonalReduction<T: IEEEFloat>(Matrix<T> workspace)",
        "Matrix<T> materializeSymmetricTridiagonalQ<T: IEEEFloat>(",
        "SymmetricTridiagonalSeed<T> symmetricTridiagonalSeedInPlace<T: IEEEFloat>(",
    ] {
        assert_eq!(LIBRARY.matches(declaration).count(), 1, "{declaration}");
    }
    for required in [
        "if (n > 0) { offDiagonal = n - 1; }",
        "if (n > 2) { reflectors = n - 2; }",
        "stableNormRange<T>(axis, p, n)",
        "T tail = (W[i,k] / beta) / denominatorRatio;",
        "T alpha = -(tauValue / two) * dot;",
        "T first = W[i,j] - vi * (*work)[j];",
        "T next = first - (*work)[i] * vj;",
        "Matrix<T> vectors = identity<T>(n);",
    ] {
        assert!(LIBRARY.contains(required), "{required}");
    }

    let reduction_start = LIBRARY
        .find("int reduceSymmetricTridiagonal<T: IEEEFloat>(")
        .unwrap();
    let reduction_end = LIBRARY[reduction_start..]
        .find("CompactSymmetricTridiagonalReduction<T>")
        .unwrap()
        + reduction_start;
    let reduction = &LIBRARY[reduction_start..reduction_end];
    for forbidden in [
        "matrixFilled",
        "vectorFilled",
        "identity",
        "epsilon<T>()",
        "Matrix<T> H",
        "Matrix<T> T",
        "qr<",
        "qrInPlace",
    ] {
        assert!(!reduction.contains(forbidden), "{forbidden}");
    }

    let materialize_start = LIBRARY
        .find("Matrix<T> materializeSymmetricTridiagonalQ<T: IEEEFloat>(")
        .unwrap();
    let materialize_end = LIBRARY[materialize_start..]
        .find("SymmetricTridiagonalSeed<T>")
        .unwrap()
        + materialize_start;
    let materialize = &LIBRARY[materialize_start..materialize_end];
    let loop_start = materialize.find("usize k = 1;").unwrap();
    for forbidden in ["matrixFilled", "vectorFilled", "identity<T>"] {
        assert!(
            !materialize[loop_start..].contains(forbidden),
            "{forbidden}"
        );
    }
    for forbidden in ["LAPACK", "BLAS", "transpose_view", "stableHypot"] {
        assert!(!reduction.contains(forbidden), "{forbidden}");
        assert!(!materialize.contains(forbidden), "{forbidden}");
    }
}

#[derive(Clone)]
struct Case {
    name: &'static str,
    n: usize,
    values: Vec<f64>,
}

fn case(name: &'static str, rows: &[&[f64]]) -> Case {
    let n = rows.len();
    assert!(rows.iter().all(|row| row.len() == n));
    Case {
        name,
        n,
        values: rows.iter().flat_map(|row| row.iter().copied()).collect(),
    }
}

#[allow(clippy::too_many_lines)] // The table keeps the normative numeric corpus together.
fn cases(float32: bool) -> Vec<Case> {
    let tiny = if float32 {
        f64::from(1.0e-30_f32)
    } else {
        1.0e-200
    };
    let small = if float32 {
        f64::from(1.0e-20_f32)
    } else {
        1.0e-150
    };
    let subnormal = if float32 {
        f64::from(f32::from_bits(1))
    } else {
        f64::from_bits(1)
    };
    vec![
        Case {
            name: "empty",
            n: 0,
            values: vec![],
        },
        case("scalar", &[&[7.0]]),
        case("two", &[&[2.0, -3.0], &[-3.0, 5.0]]),
        case(
            "diagonal",
            &[
                &[4.0, 0.0, 0.0, 0.0],
                &[0.0, -2.0, 0.0, 0.0],
                &[0.0, 0.0, 7.0, 0.0],
                &[0.0, 0.0, 0.0, 1.0],
            ],
        ),
        case(
            "identity",
            &[
                &[1.0, 0.0, 0.0, 0.0],
                &[0.0, 1.0, 0.0, 0.0],
                &[0.0, 0.0, 1.0, 0.0],
                &[0.0, 0.0, 0.0, 1.0],
            ],
        ),
        case(
            "signed_zero",
            &[
                &[0.0, -0.0, 0.0, -0.0],
                &[-0.0, 0.0, -0.0, 0.0],
                &[0.0, -0.0, 0.0, -0.0],
                &[-0.0, 0.0, -0.0, 0.0],
            ],
        ),
        case(
            "dense",
            &[
                &[4.0, 1.0, -2.0, 2.0],
                &[1.0, 2.0, 0.0, 1.0],
                &[-2.0, 0.0, 3.0, -2.0],
                &[2.0, 1.0, -2.0, -1.0],
            ],
        ),
        case(
            "positive_definite",
            &[&[4.0, 1.0, 1.0], &[1.0, 3.0, 0.5], &[1.0, 0.5, 2.0]],
        ),
        case(
            "indefinite",
            &[&[0.0, 2.0, 0.0], &[2.0, -3.0, 1.0], &[0.0, 1.0, 1.0]],
        ),
        case(
            "rank_deficient",
            &[
                &[1.0, 1.0, 1.0, 1.0],
                &[1.0, 1.0, 1.0, 1.0],
                &[1.0, 1.0, 1.0, 1.0],
                &[1.0, 1.0, 1.0, 1.0],
            ],
        ),
        case(
            "disconnected",
            &[
                &[2.0, -1.0, 0.0, 0.0],
                &[-1.0, 2.0, 0.0, 0.0],
                &[0.0, 0.0, -3.0, 2.0],
                &[0.0, 0.0, 2.0, 4.0],
            ],
        ),
        case(
            "zero_reflector",
            &[
                &[1.0, 0.0, 0.0, 0.0],
                &[0.0, 2.0, 3.0, 4.0],
                &[0.0, 3.0, 5.0, 6.0],
                &[0.0, 4.0, 6.0, 7.0],
            ],
        ),
        case(
            "tail_zero",
            &[&[1.0, 2.0, 0.0], &[2.0, 3.0, 1.0], &[0.0, 1.0, 4.0]],
        ),
        case(
            "pivot_positive_zero",
            &[&[1.0, 0.0, 2.0], &[0.0, 3.0, 1.0], &[2.0, 1.0, 4.0]],
        ),
        case(
            "pivot_negative_zero",
            &[&[1.0, -0.0, 2.0], &[-0.0, 3.0, 1.0], &[2.0, 1.0, 4.0]],
        ),
        case(
            "extreme_normalized",
            &[
                &[1.0, tiny, small],
                &[tiny, -1.0, subnormal],
                &[small, subnormal, 0.5],
            ],
        ),
    ]
}

fn matrix_literal(case: &Case, float32: bool) -> String {
    if case.n == 0 {
        return if float32 {
            "matrixFilled<float32>(0,0,float32(0.0))".into()
        } else {
            "matrixFilled<float64>(0,0,0.0)".into()
        };
    }
    let mut literal = String::from("[");
    for row in 0..case.n {
        if row != 0 {
            literal.push(';');
        }
        for column in 0..case.n {
            if column != 0 {
                literal.push(',');
            }
            let value = case.values[row * case.n + column];
            if float32 {
                write!(literal, "float32({value:.17e})").unwrap();
            } else {
                write!(literal, "{value:.17e}").unwrap();
            }
        }
    }
    literal.push(']');
    literal
}

fn emitter_source(cases: &[Case], float32: bool) -> String {
    let scalar = if float32 { "float32" } else { "float64" };
    let mut source = String::from("int main(){\n");
    for (index, case) in cases.iter().enumerate() {
        writeln!(
            source,
            "Matrix<{scalar}> a{index}={};var s{index}=symmetricTridiagonalSeedInPlace(a{index});",
            matrix_literal(case, float32)
        )
        .unwrap();
        writeln!(
            source,
            "if(dimension(s{index}.d)!={}||dimension(s{index}.e)!={}||rows(s{index}.vectors)!={}||columns(s{index}.vectors)!={}){{return {};}}",
            case.n,
            case.n.saturating_sub(1),
            case.n,
            case.n,
            index + 1
        )
        .unwrap();
        writeln!(source, "usize i{index}=1;while(i{index}<={}){{println(s{index}.d[i{index}]);i{index}=i{index}+1;}}", case.n).unwrap();
        writeln!(
            source,
            "i{index}=1;while(i{index}<={}){{println(s{index}.e[i{index}]);i{index}=i{index}+1;}}",
            case.n.saturating_sub(1)
        )
        .unwrap();
        writeln!(source, "i{index}=1;while(i{index}<={}){{usize j{index}=1;while(j{index}<={}){{println(s{index}.vectors[i{index},j{index}]);j{index}=j{index}+1;}}i{index}=i{index}+1;}}", case.n, case.n).unwrap();
    }
    source.push_str("return 0;}\n");
    source
}

fn frobenius(values: &[f64]) -> f64 {
    values.iter().map(|value| value * value).sum::<f64>().sqrt()
}

fn validate_host_oracle(cases: &[Case], output: &str, float32: bool) {
    let observed: Vec<f64> = output
        .split_whitespace()
        .map(|value| value.parse().unwrap())
        .collect();
    let mut cursor = 0;
    let epsilon = if float32 {
        f64::from(f32::EPSILON)
    } else {
        f64::EPSILON
    };

    for case in cases {
        let n = case.n;
        let d = &observed[cursor..cursor + n];
        cursor += n;
        let e = &observed[cursor..cursor + n.saturating_sub(1)];
        cursor += n.saturating_sub(1);
        let q = &observed[cursor..cursor + n * n];
        cursor += n * n;

        let input = case.values.clone();
        let mut aq = vec![0.0; n * n];
        for i in 0..n {
            for j in 0..n {
                for k in 0..n {
                    aq[i * n + j] += input[i * n + k] * q[k * n + j];
                }
            }
        }
        let mut transformed = vec![0.0; n * n];
        let mut orthogonality = vec![0.0; n * n];
        for i in 0..n {
            for j in 0..n {
                for k in 0..n {
                    transformed[i * n + j] += q[k * n + i] * aq[k * n + j];
                    orthogonality[i * n + j] += q[k * n + i] * q[k * n + j];
                }
                if i == j {
                    orthogonality[i * n + j] -= 1.0;
                }
            }
        }
        let mut residual = Vec::with_capacity(n * n);
        let mut off_band = 0.0_f64;
        for i in 0..n {
            for j in 0..n {
                let expected = if i == j {
                    d[i]
                } else if i + 1 == j {
                    e[i]
                } else if j + 1 == i {
                    e[j]
                } else {
                    0.0
                };
                let difference = transformed[i * n + j] - expected;
                residual.push(difference);
                if i.abs_diff(j) > 1 {
                    off_band = off_band.max(transformed[i * n + j].abs());
                }
            }
        }
        let scale = frobenius(&input).max(1.0);
        let order = f64::from(u32::try_from(n.max(1)).unwrap());
        let tri_bound = 512.0 * order * epsilon;
        let orth_bound = 256.0 * order * epsilon;
        let band_bound = 256.0 * order * epsilon * scale;
        assert!(
            frobenius(&residual) / scale <= tri_bound,
            "{} tridiagonal residual {} > {tri_bound}",
            case.name,
            frobenius(&residual) / scale
        );
        assert!(
            frobenius(&orthogonality) <= orth_bound,
            "{} orthogonality {} > {orth_bound}",
            case.name,
            frobenius(&orthogonality)
        );
        assert!(
            off_band <= band_bound,
            "{} off-band {off_band} > {band_bound}",
            case.name
        );
    }
    assert_eq!(cursor, observed.len());
}

#[test]
fn host_oracle_reconstructs_tridiagonal_and_orthogonal_factors_at_o0_and_o2() {
    for float32 in [false, true] {
        let cases = cases(float32);
        let source = emitter_source(&cases, float32);
        for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
            let output = compile_and_run(&source, optimization);
            validate_host_oracle(&cases, &output, float32);
        }
    }
}

#[test]
fn compact_storage_signed_zeros_and_inactive_tails_are_exact() {
    let source = r"
int main(){
 float64 z=0.0;
 Matrix<float64> empty=matrixFilled<float64>(0,0,z);var re=compactSymmetricTridiagonalReduction(empty);
 if(rows(re.workspace)!=0||columns(re.workspace)!=0||dimension(re.d)!=0||dimension(re.e)!=0||dimension(re.tau)!=0){return 1;}
 Matrix<float64> scalar=[3.0];var rs=compactSymmetricTridiagonalReduction(scalar);
 if(rs.d[1]!=3.0||dimension(rs.e)!=0||dimension(rs.tau)!=0){return 2;}
 Matrix<float64> two=[2.0,-1.0;-1.0,4.0];var r2=compactSymmetricTridiagonalReduction(two);
 if(r2.d[1]!=2.0||r2.d[2]!=4.0||r2.e[1]!=-1.0||dimension(r2.tau)!=0){return 3;}

 Matrix<float64> tailZero=[1.0,2.0,0.0;2.0,3.0,1.0;0.0,1.0,4.0];
 var rt=compactSymmetricTridiagonalReduction(tailZero);
 if(rt.workspace[2,1]!=-2.0||rt.e[1]!=-2.0||rt.tau[1]!=2.0||rt.workspace[3,1]!=z){return 4;}
 if(rt.workspace[1,1]!=rt.d[1]||rt.workspace[2,2]!=rt.d[2]||rt.workspace[3,3]!=rt.d[3]||rt.workspace[3,2]!=rt.e[2]){return 5;}

 Matrix<float64> plusPivot=[1.0,z,2.0;z,3.0,1.0;2.0,1.0,4.0];
 var rp=compactSymmetricTridiagonalReduction(plusPivot);
 if(rp.workspace[2,1]!=-2.0||rp.e[1]!=-2.0||rp.tau[1]!=1.0||rp.workspace[3,1]!=1.0){return 6;}
 Matrix<float64> minusPivot=[1.0,-z,2.0;-z,3.0,1.0;2.0,1.0,4.0];
 var rm=compactSymmetricTridiagonalReduction(minusPivot);
 if(rm.workspace[2,1]!=-2.0||rm.e[1]!=-2.0||rm.tau[1]!=1.0||rm.workspace[3,1]!=1.0){return 7;}

 Matrix<float64> zeros=[z,-z,z;-z,z,-z;z,-z,z];
 var rz=compactSymmetricTridiagonalReduction(zeros);
 if(rz.tau[1]!=z||rz.e[1]!=z||1.0/rz.e[1]!=1.0/z){return 8;}
 rz.workspace[3,1]=z/z;
 Matrix<float64> q=materializeSymmetricTridiagonalQ(&rz.workspace,&rz.tau);
 usize i=1;while(i<=3){usize j=1;while(j<=3){float64 wanted=z;if(i==j){wanted=1.0;}if(q[i,j]!=wanted){return 9;}j=j+1;}i=i+1;}

 Matrix<float64> dense=[4.0,1.0,-2.0,2.0;1.0,2.0,z,1.0;-2.0,z,3.0,-2.0;2.0,1.0,-2.0,-1.0];
 var rd=compactSymmetricTridiagonalReduction(dense);
 i=1;while(i<=4){if(rd.workspace[i,i]!=rd.d[i]){return 10;}if(i<4&&rd.workspace[i+1,i]!=rd.e[i]){return 11;}i=i+1;}

 Matrix<float32> f=[float32(1.0),float32(0.0),float32(2.0);float32(0.0),float32(3.0),float32(1.0);float32(2.0),float32(1.0),float32(4.0)];
 var rf=compactSymmetricTridiagonalReduction(f);
 if(rf.tau[1]!=float32(1.0)||rf.workspace[3,1]!=float32(1.0)){return 12;}

 Matrix<float64> lowerOnly=[1.0,z/z,z/z;z,3.0,z/z;2.0,1.0,4.0];
 var rl=compactSymmetricTridiagonalReduction(lowerOnly);
 if(rl.e[1]!=-2.0||rl.tau[1]!=1.0||rl.workspace[3,1]!=1.0){return 13;}
 return 0;
}
";
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        compile_and_run(source, optimization);
    }
}

#[test]
fn monomorphizes_and_observes_exactly_six_backings() {
    let directory = Directory::new("lowering");
    let entry = directory.white_box(
        "int main(){Matrix<float64>a=[1.0,2.0,3.0;2.0,4.0,5.0;3.0,5.0,6.0];var x=symmetricTridiagonalSeedInPlace(a);Matrix<float32>b=[float32(1.0),float32(2.0),float32(3.0);float32(2.0),float32(4.0),float32(5.0);float32(3.0),float32(5.0),float32(6.0)];var y=symmetricTridiagonalSeedInPlace(b);return int(dimension(x.d)+dimension(y.d)-6);}",
    );
    let compilation = compile_session(
        CompilationSession::discover(&entry).unwrap(),
        &[Emit::Mir, Emit::Ssa, Emit::Llvm],
    )
    .unwrap();
    for residue in ["GenericParam(", "witness", "vtable", "boxing"] {
        assert!(
            !compilation.dumps[&Emit::Mir].contains(residue),
            "{residue}"
        );
        assert!(
            !compilation.dumps[&Emit::Ssa].contains(residue),
            "{residue}"
        );
        assert!(!compilation.llvm.contains(residue), "{residue}");
    }
    assert!(!compilation.llvm.contains("TypeId"));
    assert!(
        compilation
            .llvm
            .contains("reduceSymmetricTridiagonal__gfFloat64")
    );
    assert!(
        compilation
            .llvm
            .contains("reduceSymmetricTridiagonal__gfFloat32")
    );

    for source in [
        "int main(){Matrix<float64>a=[1.0,2.0,3.0;2.0,4.0,5.0;3.0,5.0,6.0];var s=symmetricTridiagonalSeedInPlace(a);return int(rows(s.vectors)-3);}",
        "int main(){Matrix<float64>a=[1.0,2.0,3.0,4.0,5.0;2.0,6.0,7.0,8.0,9.0;3.0,7.0,10.0,11.0,12.0;4.0,8.0,11.0,13.0,14.0;5.0,9.0,12.0,14.0,15.0];var s=symmetricTridiagonalSeedInPlace(a);return int(rows(s.vectors)-5);}",
    ] {
        for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
            let directory = Directory::new("allocations");
            let entry = directory.white_box(source);
            let compilation = compile_session_with_optimization(
                CompilationSession::discover(&entry).unwrap(),
                &[Emit::Llvm],
                optimization,
            )
            .unwrap();
            let guarded = compilation.llvm.replace(
                "  %process_status = trunc i64 %aether_result to i32",
                "  %allocs = load i64, ptr @aether_heap_alloc_count\n  %frees = load i64, ptr @aether_heap_free_count\n  %alloc_ok = icmp eq i64 %allocs, 6\n  %free_ok = icmp eq i64 %frees, 6\n  %heap_ok = and i1 %alloc_ok, %free_ok\n  %result_ok = icmp eq i64 %aether_result, 0\n  %all_ok = and i1 %heap_ok, %result_ok\n  %process_status = select i1 %all_ok, i32 0, i32 99",
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
                "{optimization:?}"
            );
        }
    }
}
