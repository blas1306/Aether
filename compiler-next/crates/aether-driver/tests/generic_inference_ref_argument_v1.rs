//! GENERIC-INFERENCE-REF-ARGUMENT-V1 regression qualification.

use std::{fs, path::PathBuf};

use aether_driver::{CompilationSession, Emit, compile_session, compile_source};
use aether_frontend::SourceFile;

const LINEAR_ALGEBRA: &str = include_str!("../../../../linearAlgebra/src/lib.ae");

fn compile(source: &str) {
    compile_source(
        &SourceFile::new("generic_inference_ref_argument_v1.ae", source),
        &[],
    )
    .unwrap_or_else(|errors| panic!("{source}\n{errors:#?}"));
}

fn diagnostics(source: &str) -> String {
    compile_source(
        &SourceFile::new("bad_generic_inference_ref_argument_v1.ae", source),
        &[],
    )
    .unwrap_err()
    .into_iter()
    .map(|diagnostic| format!("{} {}", diagnostic.code, diagnostic.message))
    .collect::<Vec<_>>()
    .join("\n")
}

struct Directory(PathBuf);

impl Directory {
    fn new(label: &str) -> Self {
        static NEXT: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
        let path = std::env::temp_dir().join(format!(
            "aether-generic-ref-argument-{label}-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, std::sync::atomic::Ordering::Relaxed)
        ));
        fs::create_dir(&path).unwrap();
        Self(path)
    }

    fn write(&self, name: &str, source: &str) -> PathBuf {
        let path = self.0.join(name);
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
fn exact_owner_and_field_places_infer_through_shared_ref_parameters() {
    let cases = [
        "int main(){Vector<double,Column>v=[1.0];return consume(v)-1;}",
        "struct Holder{Vector<double,Column>value;}int main(){Vector<double,Column>v=[1.0];Holder h=Holder(v);return consume(h.value)-1;}",
        "struct Holder<T: Storable>{Vector<T,Column>value;}int main(){Vector<double,Column>v=[1.0];Holder<double>h=Holder<double>(v);return consume(h.value)-1;}",
        "struct Factor<T: Storable>{Matrix<T>U;Vector<T,Column>S;Matrix<T>Vt;}int main(){Matrix<double>u=[1.0];Vector<double,Column>s=[1.0];Matrix<double>v=[1.0];Factor<double>f=Factor<double>(u,s,v);return consume(f.S)-1;}",
    ];
    for body in cases {
        let source = format!(
            "int consume<T: Storable>(ref Vector<T,Column>value){{return int(dimension(*value));}}{body}"
        );
        compile(&source);
    }
}

#[test]
fn explicit_arguments_cover_the_same_owner_and_projection_matrix() {
    let cases = [
        "int main(){Vector<double,Column>v=[1.0];return consume<double>(v);}",
        "struct Holder{Vector<double,Column>value;}int main(){Vector<double,Column>v=[1.0];Holder h=Holder(v);return consume<double>(h.value);}",
        "struct Holder<T: Storable>{Vector<T,Column>value;}int main(){Vector<double,Column>v=[1.0];Holder<double>h=Holder<double>(v);return consume<double>(h.value);}",
        "struct Factor<T: Storable>{Vector<T,Column>S;}int main(){Vector<double,Column>v=[1.0];Factor<double>f=Factor<double>(v);return consume<double>(f.S);}",
    ];
    for body in cases {
        compile(&format!(
            "int consume<T: Storable>(ref Vector<T,Column>value){{return 0;}}{body}"
        ));
    }
}

#[test]
fn overloads_and_package_qualification_preserve_nominal_orientation() {
    compile(
        "struct Box<T: Storable>{Vector<T,Column>value;}int consume<T: Storable>(ref Vector<T,Column>value){return 1;}int consume<T: Storable>(ref Vector<T,Row>value){return 2;}int main(){Vector<double,Column>v=[1.0];Box<double>b=Box<double>(v);return consume(b.value)-1;}",
    );

    let directory = Directory::new("qualified");
    directory.write(
        "consumer.ae",
        "package helper;public int consume<T: Storable>(ref Vector<T,Column> value){return 1;}public int consume<T: Storable>(ref Vector<T,Row> value){return 2;}",
    );
    let entry = directory.write(
        "main.ae",
        "package main;import helper as h;struct Box<T: Storable>{Vector<T,Column> value;}int main(){Vector<double,Column>v=[1.0];Box<double>b=Box<double>(v);return h.consume(b.value)-1;}",
    );
    compile_session(CompilationSession::discover(&entry).unwrap(), &[Emit::Hir]).unwrap();
}

#[test]
fn incompatible_borrows_shapes_and_unconstrained_parameters_remain_rejected() {
    let cases = [
        (
            "int consume<T: Storable>(ref Vector<T,Column> value){return 0;}int main(){Vector<double,Row>v=[1.0];return consume(v);}",
            "argument does not match generic parameter pattern",
        ),
        (
            "int consume<T: Storable>(ref Vector<T,Column> value){return 0;}int main(){Vector<int,Column>v=[1];return consume<double>(v);}",
            "invalid implicit conversion",
        ),
        (
            "int consume<T: Storable>(ref mut Vector<T,Column> value){return 0;}int main(){Vector<double,Column>v=[1.0];ref Vector<double,Column>s=&v;return consume(s);}",
            "argument does not match generic parameter pattern",
        ),
        (
            "Vector<double,Column> make(){Vector<double,Column>v=[1.0];return v;}int consume<T: Storable>(ref mut Vector<T,Column> value){return 0;}int main(){return consume<double>(make());}",
            "implicit mutable argument borrows are not supported",
        ),
        (
            "int consume<T: Storable>(T tag,ref Vector<T,Column> value){return 0;}int main(){Vector<double,Column>v=[1.0];return consume(1,v);}",
            "conflicting inferred generic arguments",
        ),
        (
            "int consume<T: Storable>(int value){return value;}int main(){return consume(1);}",
            "E0263 cannot infer generic parameter",
        ),
    ];
    for (source, expected) in cases {
        let errors = diagnostics(source);
        assert!(errors.contains(expected), "{source}\n{errors}");
    }

    let ambiguous = diagnostics(
        "int choose<T: Storable>(ref Vector<T,Column> value){return 1;}double choose<T: Storable>(ref Vector<T,Column> value){return 2.0;}int main(){Vector<double,Column>v=[1.0];var x=choose(v);return 0;}",
    );
    assert!(
        ambiguous.contains("E0461 ambiguous overload"),
        "{ambiguous}"
    );
}

#[test]
fn real_svd_fields_feed_standard_linear_algebra_without_explicit_type_arguments() {
    let directory = Directory::new("svd-integration");
    directory.write("linearAlgebra.ae", LINEAR_ALGEBRA);
    let entry = directory.write(
        "main.ae",
        "package main;import linearAlgebra as la;import std.Math.LinearAlgebra as mat;int main(){Matrix<double>A=[1.0,2.0;3.0,4.0];var factor=la.svd(A);Matrix<double>Sigma=mat.diagonalMatrix(factor.S);Matrix<double>V=mat.transposeCopy(factor.Vt);return int(rows(Sigma)+rows(V)-4);}",
    );
    compile_session(
        CompilationSession::discover(&entry).unwrap(),
        &[Emit::Hir, Emit::Mir, Emit::Ssa],
    )
    .unwrap();
}
