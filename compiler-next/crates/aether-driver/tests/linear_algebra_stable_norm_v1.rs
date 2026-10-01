//! LINEAR-ALGEBRA-STABLE-NORM-V1 visibility, numerics, lowering, and cost qualification.

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
            "aether-linear-algebra-stable-norm-{label}-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, std::sync::atomic::Ordering::Relaxed)
        ));
        fs::create_dir(&path).unwrap();
        Self(path)
    }

    fn imported_entry(&self, source: &str) -> PathBuf {
        fs::write(self.0.join("linearAlgebra.ae"), LIBRARY).unwrap();
        let path = self.0.join("main.ae");
        fs::write(&path, source).unwrap();
        path
    }

    fn white_box_entry(&self, qualification: &str) -> PathBuf {
        let path = self.0.join("linearAlgebra.ae");
        fs::write(&path, format!("{LIBRARY}\n{qualification}\n")).unwrap();
        path
    }
}

impl Drop for Directory {
    fn drop(&mut self) {
        fs::remove_dir_all(&self.0).unwrap();
    }
}

fn diagnostics(source: &str) -> String {
    let directory = Directory::new("visibility");
    let entry = directory.imported_entry(source);
    compile_session(CompilationSession::discover(&entry).unwrap(), &[])
        .unwrap_err()
        .into_iter()
        .map(|diagnostic| format!("{} {}", diagnostic.code, diagnostic.message))
        .collect::<Vec<_>>()
        .join("\n")
}

fn run_white_box(source: &str, optimization: OptimizationLevel) {
    let directory = Directory::new("native");
    let entry = directory.white_box_entry(source);
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
    assert_eq!(
        Command::new(executable).status().unwrap().code(),
        Some(0),
        "{optimization:?}"
    );
}

fn frozen_qr_kernel() -> String {
    let start = LIBRARY
        .find("public QR<T> qrInPlace<T: IEEEFloat>(Matrix<T> A)")
        .unwrap();
    let end = LIBRARY
        .find("// Deprecated compatibility entry point.")
        .unwrap();
    let extracted = r"        StableScaledSquares<T> state =
            stableScaledSquaresRange<T>(column(R,k), k, m);

        if (state.scale != zero) {
            T norm = finishStableNormNonzero<T>(state);";
    let frozen = r"        // Frozen pre-extraction Householder norm loop.
        T normScale = zero;
        T scaledSquares = one;
        i = k;
        while (i <= m) {
            T magnitude = abs(R[i,k]);
            if (magnitude != zero) {
                if (normScale < magnitude) {
                    T ratio = normScale / magnitude;
                    scaledSquares = one + scaledSquares * ratio * ratio;
                    normScale = magnitude;
                }
                else {
                    T ratio = magnitude / normScale;
                    scaledSquares = scaledSquares + ratio * ratio;
                }
            }
            i = i + 1;
        }

        if (normScale != zero) {
            T norm = normScale * sqrt(scaledSquares);";
    LIBRARY[start..end]
        .replace(
            "public QR<T> qrInPlace<T: IEEEFloat>(Matrix<T> A)",
            "QR<T> qrFrozen<T: IEEEFloat>(Matrix<T> A)",
        )
        .replace(extracted, frozen)
}

#[test]
fn helpers_and_state_are_module_private() {
    for (name, expression) in [
        (
            "StableScaledSquares",
            "int probe(la.StableScaledSquares<float64> x){return 0;}",
        ),
        (
            "stableScaledSquaresRange",
            "int probe(Vector<float64,Column> x){var y=la.stableScaledSquaresRange(vector_view(x),1,1);return 0;}",
        ),
        (
            "finishStableNormNonzero",
            "int probe(){return int(la.finishStableNormNonzero<float64>(0.0));}",
        ),
        (
            "stableNormRange",
            "int probe(Vector<float64,Column> x){return int(la.stableNormRange(vector_view(x),1,1));}",
        ),
        (
            "stableHypot",
            "int probe(){return int(la.stableHypot(3.0,4.0));}",
        ),
    ] {
        let source = format!(
            "package consumer;import linearAlgebra as la;{expression}int main(){{return 0;}}"
        );
        let output = diagnostics(&source);
        assert!(
            output.contains("internal to its module") || output.contains("unknown function"),
            "{name}: {output}"
        );
    }
}

#[test]
fn source_has_one_exact_recurrence_and_qr_uses_the_column_view() {
    assert_eq!(LIBRARY.matches("struct StableScaledSquares<").count(), 1);
    assert_eq!(
        LIBRARY
            .matches("stableScaledSquaresRange<T: IEEEFloat>(")
            .count(),
        1
    );
    assert_eq!(
        LIBRARY
            .matches("scaledSquares = one + scaledSquares * ratio * ratio;")
            .count(),
        1
    );
    assert_eq!(
        LIBRARY
            .matches("scaledSquares = scaledSquares + ratio * ratio;")
            .count(),
        1
    );
    assert!(LIBRARY.contains("stableScaledSquaresRange<T>(column(R,k), k, m)"));
    assert!(LIBRARY.contains("if (state.scale != zero)"));
    assert!(LIBRARY.contains("T norm = finishStableNormNonzero<T>(state);"));
    for forbidden in ["epsilon<T>()", "sqrt(a * a + b * b)", "sqrt(a*a+b*b)"] {
        assert!(!LIBRARY.contains(forbidden), "{forbidden}");
    }
}

#[test]
fn stable_norm_and_hypot_cover_ieee_and_stability_paths_at_o0_and_o2() {
    let source = r"
int check64() {
    float64 zero = 0.0;
    float64 inf = 1.0 / zero;
    float64 nan = zero / zero;
    Matrix<float64> empty = matrixFilled<float64>(0, 1, zero);
    float64 value = stableNormRange<float64>(column(empty,1), 1, 0);
    if (value != zero || 1.0 / value != inf) { return 1; }
    Matrix<float64> one = [-7.0];
    if (stableNormRange<float64>(column(one,1), 1, 1) != 7.0) { return 2; }
    Matrix<float64> classic = [3.0;4.0];
    if (stableNormRange<float64>(column(classic,1), 1, 2) != 5.0) { return 3; }
    Matrix<float64> signedZeros = [-zero;zero;-zero];
    value = stableNormRange<float64>(column(signedZeros,1), 1, 3);
    if (value != zero || 1.0 / value != inf) { return 4; }
    Matrix<float64> huge = [1.0e308;1.0e308];
    value = stableNormRange<float64>(column(huge,1), 1, 2);
    if (!((value - value) == zero) || !(value > 1.0e308)) { return 5; }
    Matrix<float64> tiny = [1.0e-200;1.0e-200];
    value = stableNormRange<float64>(column(tiny,1), 1, 2);
    if (!(value > 1.0e-200)) { return 6; }
    Matrix<float64> subnormal = [5.0e-324];
    if (!(stableNormRange<float64>(column(subnormal,1), 1, 1) > zero)) { return 7; }
    Matrix<float64> nanOnly = [nan;-zero];
    value = stableNormRange<float64>(column(nanOnly,1), 1, 2);
    if (value != zero || 1.0 / value != inf) { return 8; }
    Matrix<float64> nanFinite = [nan;2.0];
    value = stableNormRange<float64>(column(nanFinite,1), 1, 2);
    if (value == value) { return 9; }
    Matrix<float64> oneInf = [inf];
    if (stableNormRange<float64>(column(oneInf,1), 1, 1) != inf) { return 10; }
    Matrix<float64> twoInf = [inf;inf];
    value = stableNormRange<float64>(column(twoInf,1), 1, 2);
    if (value == value) { return 11; }
    if (stableHypot<float64>(3.0,4.0) != 5.0 || stableHypot<float64>(4.0,3.0) != 5.0) { return 12; }
    if (stableHypot<float64>(-3.0,-4.0) != 5.0) { return 13; }
    value = stableHypot<float64>(-zero,zero);
    if (value != zero || 1.0 / value != inf) { return 14; }
    value = stableHypot<float64>(nan,2.0);
    if (value == value) { return 15; }
    if (stableHypot<float64>(inf,2.0) != inf) { return 16; }
    value = stableHypot<float64>(inf,inf);
    if (value == value) { return 17; }
    value = stableHypot<float64>(1.0e308,1.0e-200);
    if (value != 1.0e308) { return 18; }
    return 0;
}

int check32() {
    float32 zero = float32(0.0);
    float32 inf = float32(1.0) / zero;
    float32 nan = zero / zero;
    Matrix<float32> classic = [float32(3.0);float32(4.0)];
    if (stableNormRange<float32>(column(classic,1), 1, 2) != float32(5.0)) { return 21; }
    Matrix<float32> signedZeros = [-zero;zero];
    float32 value = stableNormRange<float32>(column(signedZeros,1), 1, 2);
    if (value != zero || float32(1.0) / value != inf) { return 22; }
    Matrix<float32> huge = [float32(2.0e38);float32(2.0e38)];
    value = stableNormRange<float32>(column(huge,1), 1, 2);
    if (!((value - value) == zero) || !(value > float32(2.0e38))) { return 23; }
    Matrix<float32> tiny = [float32(1.0e-30);float32(1.0e-30)];
    if (!(stableNormRange<float32>(column(tiny,1), 1, 2) > float32(1.0e-30))) { return 24; }
    Matrix<float32> nanOnly = [nan];
    value = stableNormRange<float32>(column(nanOnly,1), 1, 1);
    if (value != zero) { return 25; }
    Matrix<float32> nanFinite = [nan;float32(2.0)];
    value = stableNormRange<float32>(column(nanFinite,1), 1, 2);
    if (value == value) { return 26; }
    Matrix<float32> oneInf = [inf];
    if (stableNormRange<float32>(column(oneInf,1), 1, 1) != inf) { return 27; }
    Matrix<float32> twoInf = [inf;inf];
    value = stableNormRange<float32>(column(twoInf,1), 1, 2);
    if (value == value) { return 28; }
    if (stableHypot<float32>(float32(3.0),float32(4.0)) != float32(5.0)) { return 29; }
    value = stableHypot<float32>(nan,float32(2.0));
    if (value == value) { return 30; }
    if (stableHypot<float32>(inf,float32(2.0)) != inf) { return 31; }
    value = stableHypot<float32>(inf,inf);
    if (value == value) { return 32; }
    return 0;
}

int main() {
    int a = check64();
    if (a != 0) { return a; }
    return check32();
}
";
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        run_white_box(source, optimization);
    }
}

#[test]
fn extracted_qr_matches_the_frozen_pre_extraction_loop_at_o0_and_o2() {
    let qualification = format!(
        r"{}
int same64(QR<float64> left, QR<float64> right) {{
    usize i = 1;
    while (i <= rows(left.Q)) {{
        usize j = 1;
        while (j <= columns(left.Q)) {{
            float64 a = left.Q[i,j]; float64 b = right.Q[i,j];
            if (a != b && (a == a || b == b)) {{ return 1; }}
            j = j + 1;
        }}
        i = i + 1;
    }}
    i = 1;
    while (i <= rows(left.R)) {{
        usize j = 1;
        while (j <= columns(left.R)) {{
            float64 a = left.R[i,j]; float64 b = right.R[i,j];
            if (a != b && (a == a || b == b)) {{ return 2; }}
            j = j + 1;
        }}
        i = i + 1;
    }}
    return 0;
}}
int same32(QR<float32> left, QR<float32> right) {{
    usize i = 1;
    while (i <= rows(left.Q)) {{
        usize j = 1;
        while (j <= columns(left.Q)) {{
            float32 a = left.Q[i,j]; float32 b = right.Q[i,j];
            if (a != b && (a == a || b == b)) {{ return 3; }}
            j = j + 1;
        }}
        i = i + 1;
    }}
    i = 1;
    while (i <= rows(left.R)) {{
        usize j = 1;
        while (j <= columns(left.R)) {{
            float32 a = left.R[i,j]; float32 b = right.R[i,j];
            if (a != b && (a == a || b == b)) {{ return 4; }}
            j = j + 1;
        }}
        i = i + 1;
    }}
    return 0;
}}
int main() {{
    float64 z = 0.0; float64 inf = 1.0 / z; float64 nan = z / z;
    Matrix<float64> a = [12.0,-51.0,4.0;6.0,167.0,-68.0;-4.0,24.0,-41.0];
    if (same64(qr(a), qrFrozen(copyMatrixForFactorization<float64>(a))) != 0) {{ return 11; }}
    Matrix<float64> zeros = [-z,z;z,-z];
    if (same64(qr(zeros), qrFrozen(copyMatrixForFactorization<float64>(zeros))) != 0) {{ return 12; }}
    Matrix<float64> mixed = [1.0e308,1.0e-200;1.0e-200,-1.0e308];
    if (same64(qr(mixed), qrFrozen(copyMatrixForFactorization<float64>(mixed))) != 0) {{ return 13; }}
    Matrix<float64> special = [inf,nan;2.0,3.0];
    if (same64(qr(special), qrFrozen(copyMatrixForFactorization<float64>(special))) != 0) {{ return 14; }}
    Matrix<float32> b = [float32(3.0),float32(4.0);float32(-0.0),float32(1.0e-30)];
    if (same32(qr(b), qrFrozen(copyMatrixForFactorization<float32>(b))) != 0) {{ return 15; }}
    return 0;
}}
",
        frozen_qr_kernel()
    );
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        run_white_box(&qualification, optimization);
    }
}

#[test]
fn helpers_monomorphize_without_generic_or_dispatch_residue() {
    let directory = Directory::new("lowering");
    let entry = directory.white_box_entry(
        "int main(){Matrix<float64>a=[3.0;4.0];float64 x=stableNormRange<float64>(column(a,1),1,2);float32 y=stableHypot<float32>(float32(3.0),float32(4.0));return int(x+float64(y)-10.0);}",
    );
    let compilation = compile_session(
        CompilationSession::discover(&entry).unwrap(),
        &[Emit::Hir, Emit::Mir, Emit::Ssa, Emit::Llvm],
    )
    .unwrap();
    for phase in [Emit::Mir, Emit::Ssa] {
        let dump = &compilation.dumps[&phase];
        for residue in [
            "GenericParam(",
            "CapabilityBinary",
            "CapabilityCompare",
            "CapabilityMath",
            "witness",
            "vtable",
        ] {
            assert!(!dump.contains(residue), "{phase:?}: {residue}");
        }
    }
    for residue in ["TypeId", "callable", "stable_norm", "hypot("] {
        assert!(!compilation.llvm.contains(residue), "{residue}");
    }
    assert!(compilation.llvm.contains("call double @sqrt(double"));
    assert!(compilation.llvm.contains("call float @sqrtf(float"));
}

#[test]
fn helper_calls_add_no_heap_allocations() {
    let source = "int main(){Matrix<float64>a=[3.0;4.0];float64 x=stableNormRange<float64>(column(a,1),1,2);float64 y=stableHypot<float64>(x,12.0);return int(y-13.0);}";
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        let directory = Directory::new("allocations");
        let entry = directory.white_box_entry(source);
        let compilation = compile_session_with_optimization(
            CompilationSession::discover(&entry).unwrap(),
            &[Emit::Llvm],
            optimization,
        )
        .unwrap();
        let guarded = compilation.llvm.replace(
            "  %process_status = trunc i64 %aether_result to i32",
            "  %allocs = load i64, ptr @aether_heap_alloc_count\n  %frees = load i64, ptr @aether_heap_free_count\n  %alloc_ok = icmp eq i64 %allocs, 1\n  %free_ok = icmp eq i64 %frees, 1\n  %heap_ok = and i1 %alloc_ok, %free_ok\n  %result_ok = icmp eq i64 %aether_result, 0\n  %all_ok = and i1 %heap_ok, %result_ok\n  %process_status = select i1 %all_ok, i32 0, i32 99",
        );
        assert_ne!(guarded, compilation.llvm);
        let executable = directory.0.join("allocation-check");
        ClangToolchain::default()
            .with_optimization(optimization)
            .link_executable(&guarded, &executable)
            .unwrap();
        assert_eq!(Command::new(executable).status().unwrap().code(), Some(0));
    }
}
