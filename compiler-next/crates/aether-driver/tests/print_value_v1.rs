//! PRINT-VALUE-V1 direct FORMAT output qualification.

use std::{fs, path::PathBuf, process::Command};

use aether_driver::{Emit, OptimizationLevel, compile_source_with_optimization};
use aether_frontend::SourceFile;

struct Directory(PathBuf);

impl Directory {
    fn new() -> Self {
        static NEXT: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
        let path = std::env::temp_dir().join(format!(
            "aether-print-value-v1-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, std::sync::atomic::Ordering::Relaxed)
        ));
        fs::create_dir(&path).unwrap();
        Self(path)
    }
}

impl Drop for Directory {
    fn drop(&mut self) {
        fs::remove_dir_all(&self.0).unwrap();
    }
}

fn compile(source: &str, optimization: OptimizationLevel) -> aether_driver::Compilation {
    compile_source_with_optimization(
        &SourceFile::new("print_value_v1.ae", source),
        &[Emit::Hir, Emit::Mir, Emit::Ssa],
        optimization,
    )
    .unwrap_or_else(|errors| panic!("{source}\n{errors:#?}"))
}

fn execute(llvm: &str, optimization: OptimizationLevel) -> std::process::Output {
    let directory = Directory::new();
    let ir = directory.0.join("program.ll");
    let executable = directory.0.join("program");
    fs::write(&ir, llvm).unwrap();
    let option = match optimization {
        OptimizationLevel::O0 => "-O0",
        OptimizationLevel::O2 => "-O2",
    };
    let linked = Command::new("clang")
        .args(["-Wno-override-module", option, "-x", "ir"])
        .arg(&ir)
        .arg("-o")
        .arg(&executable)
        .arg("-lstdc++")
        .output()
        .unwrap();
    assert!(
        linked.status.success(),
        "{}",
        String::from_utf8_lossy(&linked.stderr)
    );
    Command::new(executable).output().unwrap()
}

#[test]
fn direct_scalars_are_byte_exact_at_o0_o2() {
    let source = r#"int main(){
print(42);print('|');print(1.5);print('|');print(true);print('|');println('é');
int n=7;ref mut int p=&mut n;println(p);*p=9;
println("hola");println("x = ${42}");return n-9;}"#;
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        let compilation = compile(source, optimization);
        let output = execute(&compilation.llvm, optimization);
        assert!(output.status.success());
        assert_eq!(output.stdout, "42|1.5|true|é\n7\nhola\nx = 42\n".as_bytes());
        assert!(compilation.dumps[&Emit::Hir].contains("DirectFormat"));
        assert!(compilation.dumps[&Emit::Hir].contains("ExistingString"));
    }
}

#[test]
fn direct_math_owners_fields_refs_and_temporaries_are_observational() {
    let source = r"struct Holder{Matrix<int> value;}
Holder make(){Matrix<int> m=[5,6];return Holder(m);}
int main(){
Vector<int,Row> r=[1,2];Vector<int,Column> c=[3,4];Matrix<int> m=[1,2;3,4];Matrix<int> n=[1,2;3,4];
Holder h=Holder(n);ref Matrix<int> p=&h.value;
println(r);println(c);println(m);println(h.value);println(p);
println(matrixFilled<int>(1,2,7));println(make().value);
m[1,1]=9;return m[1,1]-9;}";
    let expected = b"[1, 2]\n[3; 4]\n[1, 2; 3, 4]\n[1, 2; 3, 4]\n[1, 2; 3, 4]\n[7, 7]\n[5, 6]\n";
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        let compilation = compile(source, optimization);
        let output = execute(&compilation.llvm, optimization);
        assert!(
            output.status.success(),
            "{}",
            String::from_utf8_lossy(&output.stderr)
        );
        assert_eq!(output.stdout, expected);
        assert!(compilation.dumps[&Emit::Mir].contains("FormatEndBorrow"));
        assert!(compilation.dumps[&Emit::Ssa].contains("FormatEndBorrow"));
    }
}

#[test]
fn string_fast_path_does_not_reach_format_runtime() {
    let compilation = compile(
        "struct S{string value;}S make(){return S(\"temporary\");}int main(){string x=\"plain\";println(x);println(\"literal\");println(make().value);return 0;}",
        OptimizationLevel::O0,
    );
    let output = execute(&compilation.llvm, OptimizationLevel::O0);
    assert!(output.status.success());
    assert_eq!(output.stdout, b"plain\nliteral\ntemporary\n");
    assert!(!compilation.llvm.contains("aether_format_i64"));
    assert!(!compilation.dumps[&Emit::Hir].contains("DirectFormat"));
}

#[test]
fn direct_output_keeps_closed_arity_and_format_admission() {
    for (source, code) in [
        ("int main(){println();return 0;}", "E0205"),
        ("int main(){println(1,2);return 0;}", "E0205"),
        (
            "int main(){Matrix<int> m=[1];MatrixView<int> v=matrix_view(m);println(v);return 0;}",
            "E0340",
        ),
    ] {
        let errors = compile_source_with_optimization(
            &SourceFile::new("bad_print_value.ae", source),
            &[],
            OptimizationLevel::O0,
        )
        .unwrap_err();
        assert!(errors.iter().any(|error| error.code == code), "{errors:#?}");
        if code == "E0340" {
            assert!(
                errors
                    .iter()
                    .any(|error| error.message.contains("argument of `println`")),
                "{errors:#?}"
            );
        }
    }
}
