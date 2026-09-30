//! Joint structural qualification for NUMERIC-GENERIC-MIGRATION-CLOSURE-1.

use std::{fs, path::PathBuf};

use aether_driver::{CompilationSession, Emit, compile_session};

const LIBRARY: &str = include_str!("../../../../linearAlgebra/src/lib.ae");

struct Directory(PathBuf);

impl Directory {
    fn new() -> Self {
        static NEXT: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
        let path = std::env::temp_dir().join(format!(
            "aether-numeric-generic-closure-{}-{}",
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

#[test]
fn public_source_is_one_generic_kernel_per_family() {
    let signatures = [
        ("Matrix<T> zeros<T: Storable + Copy + Zero>(", 2),
        ("Vector<T,Row> zeros<T: Storable + Copy + Zero>(", 1),
        ("Vector<T,Column> zeros<T: Storable + Copy + Zero>(", 1),
        ("Matrix<T> ones<T: Storable + Copy + One>(", 2),
        ("Vector<T,Row> ones<T: Storable + Copy + One>(", 1),
        ("Vector<T,Column> ones<T: Storable + Copy + One>(", 1),
        ("Matrix<T> identity<T: Storable + Copy + Zero + One>(", 1),
        ("LU<T> lu<T: IEEEFloat>(", 1),
        ("T det<T: IEEEFloat>(", 2),
        ("Vector<T,Column> solve<T: IEEEFloat>(", 2),
        ("Matrix<T> solve<T: IEEEFloat>(", 2),
        ("QR<T> qr<T: IEEEFloat>(", 1),
    ];
    for (signature, count) in signatures {
        assert_eq!(LIBRARY.matches(signature).count(), count, "{signature}");
    }

    assert_eq!(
        LIBRARY
            .matches("QR<float32> qrFloat32(Matrix<float32> A)")
            .count(),
        1
    );
    let wrapper = LIBRARY
        .split_once("QR<float32> qrFloat32(Matrix<float32> A)")
        .unwrap()
        .1;
    assert!(wrapper.contains("return qrInPlace(A);"));
    assert!(!wrapper.contains("while ("));

    for forbidden in [
        "Matrix<float64> zeros",
        "Matrix<float32> zeros",
        "LU<float64> lu",
        "LU<float32> lu",
        "float64 det(",
        "float32 det(",
        "Vector<float64,Column> solve",
        "Vector<float32,Column> solve",
        "Matrix<float64> solve",
        "Matrix<float32> solve",
        "QR<float64> qr",
        "TypeId",
        "witness",
        "vtable",
    ] {
        assert!(!LIBRARY.contains(forbidden), "source contains {forbidden}");
    }

    let precision_specific_functions = LIBRARY
        .lines()
        .filter(|line| {
            let line = line.trim();
            !line.starts_with("//")
                && line.ends_with('{')
                && line.contains('(')
                && (line.contains("float32") || line.contains("float64"))
        })
        .collect::<Vec<_>>();
    assert_eq!(
        precision_specific_functions,
        ["QR<float32> qrFloat32(Matrix<float32> A) {"]
    );
}

#[test]
fn capability_ir_is_parametric_only_and_both_precisions_are_monomorphized() {
    let directory = Directory::new();
    let entry = directory.entry(
        "package consumer;import linearAlgebra as la;\
         la.LU<T> glu<T:IEEEFloat>(Matrix<T>a){return la.lu(a);}\
         T gdet<T:IEEEFloat>(ref la.LU<T>f){return la.det(f);}\
         Vector<T,Column> gsolve<T:IEEEFloat>(ref la.LU<T>f,ref Vector<T,Column>b){return la.solve(f,b);}\
         la.QR<T> gqr<T:IEEEFloat>(Matrix<T>a){return la.qr(a);}\
         int main(){\
         Matrix<float64>a=[2.0];la.LU<float64>f=glu(a);Vector<float64,Column>b=[4.0];\
         Vector<float64,Column>x=gsolve(f,b);float64 d=gdet(f);Matrix<float64>q=[1.0];la.QR<float64>r=gqr(q);\
         Matrix<float32>c=[float32(3.0)];la.LU<float32>h=glu(c);Vector<float32,Column>e=[float32(6.0)];\
         Vector<float32,Column>y=gsolve(h,e);float32 z=gdet(h);Matrix<float32>s=[float32(1.0)];la.QR<float32>t=gqr(s);\
         return int(x[1]+float64(y[1])+d+float64(z)+r.R[1,1]+float64(t.R[1,1])-12.0);}",
    );
    let compilation = compile_session(
        CompilationSession::discover(&entry).unwrap(),
        &[Emit::Hir, Emit::Mir, Emit::Ssa, Emit::Llvm],
    )
    .unwrap();

    let hir = &compilation.dumps[&Emit::Hir];
    for node in [
        "AlgebraicValue",
        "CapabilityBinary",
        "CapabilityUnary",
        "CapabilityCompare",
        "CapabilityMath",
    ] {
        assert!(hir.contains(node), "parametric HIR misses {node}");
    }
    for concrete in [
        "AddFloat",
        "SubtractFloat",
        "MultiplyFloat",
        "DivideFloat",
        "NegateFloat",
    ] {
        assert!(hir.contains(concrete), "concrete HIR misses {concrete}");
    }

    for phase in [Emit::Mir, Emit::Ssa] {
        let dump = &compilation.dumps[&phase];
        for residue in [
            "AlgebraicValue",
            "CapabilityBinary",
            "CapabilityUnary",
            "CapabilityCompare",
            "CapabilityMath",
            "GenericParam(",
            "witness",
            "vtable",
        ] {
            assert!(!dump.contains(residue), "{phase:?} contains {residue}");
        }
    }

    for residue in ["Capability", "GenericParam", "TypeId", "witness", "vtable"] {
        assert!(
            !compilation.llvm.contains(residue),
            "LLVM contains {residue}"
        );
    }
    for symbol in [
        "linearAlgebra_f2_lu__gfFloat64",
        "linearAlgebra_f2_lu__gfFloat32",
        "__gfFloat64",
        "__gfFloat32",
        "call double @fabs(double",
        "call float @fabsf(float",
        "call double @sqrt(double",
        "call float @sqrtf(float",
    ] {
        assert!(compilation.llvm.contains(symbol), "LLVM misses {symbol}");
    }
}
