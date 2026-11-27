//! Cross-layer qualification for COMPOUND-ASSIGNMENT-V1.

use std::{fs, path::Path, process::Command};

use aether_driver::{ClangToolchain, Emit, compile_source, run_path};
use aether_frontend::SourceFile;

fn compile(
    source: &str,
    emits: &[Emit],
) -> Result<aether_driver::Compilation, Vec<aether_driver::Diagnostic>> {
    compile_source(&SourceFile::new("compound.ae", source), emits)
}

#[test]
fn all_five_operators_preserve_transaction_identity_through_ssa() {
    let source = r"
        int main() {
            int x = 20;
            x += 4;
            x -= 2;
            x *= 3;
            x /= 2;
            x %= 10;
            return x;
        }
    ";
    let compiled = compile(source, &[Emit::Hir, Emit::Mir, Emit::Ssa, Emit::Llvm]).unwrap();
    let hir = &compiled.dumps[&Emit::Hir];
    let mir = &compiled.dumps[&Emit::Mir];
    let ssa = &compiled.dumps[&Emit::Ssa];
    assert!(hir.matches("CompoundAssign").count() >= 5);
    assert!(mir.matches("CompoundLoad").count() >= 5);
    assert!(mir.matches("CompoundCommit").count() >= 5);
    assert!(ssa.matches("CompoundLoad").count() >= 5);
    assert!(ssa.matches("CompoundCommit").count() >= 5);
    assert!(compiled.llvm.matches("store i64").count() >= 6); // initializer + five commits
}

#[test]
fn compound_operators_are_statement_only_and_reject_non_numeric_or_float_remainder() {
    for source in [
        "int main(){ int x = 1; int y = (x += 1); return y; }",
        "int main(){ int x = 1; return x += 1; }",
        "int main(){ bool x = true; x += false; return 0; }",
        "int main(){ float64 x = 1.0; x %= 1.0; return 0; }",
    ] {
        assert!(
            compile(source, &[]).is_err(),
            "unexpected acceptance: {source}"
        );
    }
}

#[test]
fn maximal_munch_keeps_plain_binary_and_assignment_syntax_unchanged() {
    compile("int main(){ int x = 1; x = x + 2; return x; }", &[]).unwrap();
}

#[test]
fn admitted_scalar_places_cover_aggregate_collection_view_and_reference_shapes() {
    for source in [
        "struct S { int x; } int main(){ S s=S(1); s.x += 2; return s.x; }",
        "int main(){ Array<int> a={1}; a[0] += 2; return a[0]; }",
        "int main(){ Buffer<int> a=Buffer<int>(1,1); a[0] *= 3; return a[0]; }",
        "int main(){ List<int> a={1}; a[0] -= 1; return a[0]; }",
        "int main(){ Array<int> a={1}; ViewMut<int> v=view_mut(a); v[0] += 2; return a[0]; }",
        "int main(){ int x=1; ref mut int r=&mut x; *r += 2; return x; }",
        "int main(){ Vector<int,Row> v=[1,2]; v[2] += 3; return v[2]; }",
        "int main(){ Matrix<int> m=[1,2;3,4]; m[2,1] /= 3; return m[2,1]; }",
    ] {
        compile(source, &[]).unwrap_or_else(|errors| panic!("{source}: {errors:#?}"));
    }
}

#[test]
fn class_scalar_fields_use_the_nominal_transaction_path() {
    let source = r"
        open class Base {
            public int inherited;
            public init(int value) { inherited = value; }
        }
        class Counter : Base {
            public int value;
            public init(int inherited, int value) : base(inherited) { this.value = value; }
            public mut int update(int amount) {
                this.value += amount;
                inherited *= 2;
                return value + inherited;
            }
        }
        int main() {
            Counter counter = Counter(3, 4);
            counter.value -= 1;
            return counter.update(2);
        }
    ";
    let compiled = compile(source, &[Emit::Hir, Emit::Mir, Emit::Ssa, Emit::Llvm]).unwrap();
    for emit in [Emit::Hir, Emit::Mir, Emit::Ssa] {
        let dump = &compiled.dumps[&emit];
        assert!(
            dump.contains("ClassScalarField"),
            "missing nominal path in {emit:?}"
        );
    }
    assert!(compiled.llvm.contains("compound_field"));
}

#[test]
fn class_scalar_fields_preserve_access_mutability_and_initialization_rules() {
    for source in [
        "class C{int value;public init(){value+=1;}}int main(){return 0;}",
        "class C{int value;public init(int x){value=x;}public int bad(){value+=1;return value;}}int main(){return 0;}",
        "class C{int value;public init(int x){value=x;}}int main(){C c=C(1);c.value+=1;return 0;}",
        "class C{public int value;public init(){value=1;}}int main(){C c=C();ref C r=&c;(*r).value+=1;return 0;}",
        "class C{public int value;public init(){value=1;}}int replace(ref mut C slot){*slot=C();return 1;}int main(){C c=C();c.value+=replace(&mut c);return 0;}",
    ] {
        assert!(
            compile(source, &[]).is_err(),
            "unexpected acceptance: {source}"
        );
    }
}

#[test]
fn class_field_rhs_may_update_same_or_disjoint_scalar_field() {
    let source = "class C{public int a;public int b;public init(){a=5;b=1;}public mut int same(){a=20;return 3;}public mut int other(){b=9;return 2;}public mut int run(){a+=same();a+=other();return a*10+b;}}int main(){C c=C();return c.run();}";
    compile(source, &[Emit::Mir, Emit::Ssa, Emit::Llvm])
        .unwrap_or_else(|errors| panic!("{errors:#?}"));
}

#[test]
fn class_field_throw_and_arithmetic_traps_leave_commit_on_normal_path_only() {
    let throwing = "open class Problem:Exception{public init(){}}int fail(){throw Problem();}class C{public int value;public init(){value=4;}public mut int run(){try{value+=fail();}catch(Problem e){return value;}return 9;}}int main(){C c=C();return c.run();}";
    let compiled = compile(throwing, &[Emit::Mir, Emit::Ssa, Emit::Llvm]).unwrap();
    assert_eq!(
        compiled.dumps[&Emit::Mir].matches("CompoundCommit").count(),
        1
    );
    assert_eq!(
        compiled.dumps[&Emit::Ssa].matches("CompoundCommit").count(),
        1
    );
    for source in [
        "class C{public int value;public init(){value=1;}public mut int run(){value*=2;return value;}}int main(){return 0;}",
        "class C{public int value;public init(){value=1;}public mut int run(){value/=0;return value;}}int main(){return 0;}",
        "class C{public int value;public init(){value=1;}public mut int run(){value%=0;return value;}}int main(){return 0;}",
    ] {
        compile(source, &[Emit::Llvm]).unwrap();
    }
}

#[test]
fn read_only_and_temporary_destinations_are_rejected() {
    for source in [
        "int main(){ int x=1; ref int r=&x; *r += 2; return x; }",
        "int main(){ Array<int> a={1}; View<int> v=view(a); v[0] += 2; return a[0]; }",
        "int make(){return 1;} int main(){ make() += 2; return 0; }",
    ] {
        assert!(
            compile(source, &[]).is_err(),
            "unexpected acceptance: {source}"
        );
    }
}

#[test]
fn rhs_may_mutate_scalar_slots_without_invalidating_the_stabilized_place() {
    for source in [
        "int touch(ref mut int x){*x=7;return 2;}int main(){List<int>x={1,3};x[0]+=touch(&mut x[0]);return x[0];}",
        "int touch(ref mut int x){*x=7;return 2;}int main(){List<int>x={1,3};x[0]+=touch(&mut x[1]);return x[0];}",
    ] {
        compile(source, &[]).unwrap_or_else(|errors| panic!("{source}: {errors:#?}"));
    }
}

#[test]
fn rhs_rejects_structural_invalidation_of_the_protected_backing_or_slot() {
    for source in [
        "int main(){List<int>x={1,2};x[0]+=pop(x);return x[0];}",
        "int main(){List<int>x={1,2};x[0]+=remove(x,0);return x[0];}",
        "int main(){List<int>x={1,2};x[0]+=swap_remove(x,0);return x[0];}",
        "int grow(ref mut List<int>x){push(*x,2);return 1;}int main(){List<int>x={1};x[0]+=grow(&mut x);return x[0];}",
        "int grow(ref mut List<int>x){reserve(*x,8);return 1;}int main(){List<int>x={1};x[0]+=grow(&mut x);return x[0];}",
        "int shrink(ref mut List<int>x){return pop(*x);}int main(){List<int>x={1,2};x[0]+=shrink(&mut x);return x[0];}",
        "int replace(ref mut List<int>x){*x={3};return 1;}int main(){List<int>x={1};x[0]+=replace(&mut x);return x[0];}",
        "int grow(ref mut List<int>x){push(*x,2);return 1;}int main(){List<int>x={1};Function<(ref mut List<int>),int>f=grow;x[0]+=f(&mut x);return x[0];}",
        "int grow(ref mut Matrix<int>x){Vector<int,Row>r=[2];(*x).add(r);return 1;}int main(){Matrix<int>x=[1];x[1,1]+=grow(&mut x);return x[1,1];}",
    ] {
        let errors = compile(source, &[])
            .err()
            .unwrap_or_else(|| panic!("unexpected acceptance: {source}"));
        assert!(
            errors.iter().any(|error| {
                error.message.contains("compound assignment")
                    || error.message.contains("live element reference/view")
                    || error
                        .message
                        .contains("derived element reference/view remains live")
            }),
            "rejected for the wrong reason: {source}: {errors:#?}"
        );
    }
}

#[test]
fn exceptional_rhs_keeps_commit_only_on_the_normal_path() {
    let source = "open class Problem:Exception{public init(){}}int fail(){throw Problem();}int main(){int x=4;try{x+=fail();}catch(Problem e){return x-4;}return 9;}";
    let compiled = compile(source, &[Emit::Mir, Emit::Ssa, Emit::Llvm]).unwrap();
    assert!(compiled.dumps[&Emit::Mir].contains("unwind: Some"));
    assert_eq!(
        compiled.dumps[&Emit::Mir].matches("CompoundCommit").count(),
        1
    );
    assert_eq!(
        compiled.dumps[&Emit::Ssa].matches("CompoundCommit").count(),
        1
    );
}

#[test]
#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
fn all_five_operators_execute_natively() {
    let path = Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("../..")
        .join("tests/programs/compound_assignment_v1.ae");
    let (_, status) = run_path(&path, &[], &ClangToolchain::default()).unwrap();
    assert_eq!(status.code(), Some(3));
}

#[test]
#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
fn class_field_aliasing_and_keepalive_execute_natively() {
    let path = Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("../..")
        .join("tests/programs/compound_assignment_class_fields_v1.ae");
    let (_, status) = run_path(&path, &[], &ClangToolchain::default()).unwrap();
    assert_eq!(status.code(), Some(0));
    let source = fs::read_to_string(&path).unwrap();
    let compilation = compile(&source, &[Emit::Llvm]).unwrap();
    for optimization in ["-O0", "-O2"] {
        let stem = std::env::temp_dir().join(format!(
            "aether-compound-class-{}-{optimization}",
            std::process::id()
        ));
        let llvm = stem.with_extension("ll");
        let executable = stem.with_extension("out");
        fs::write(&llvm, &compilation.llvm).unwrap();
        let linked = Command::new("clang")
            .args([optimization, "-Wno-override-module"])
            .arg(&llvm)
            .arg("-o")
            .arg(&executable)
            .status()
            .unwrap();
        assert!(linked.success());
        assert_eq!(Command::new(&executable).status().unwrap().code(), Some(0));
        let _ = fs::remove_file(&llvm);
        let _ = fs::remove_file(&executable);
    }
}

#[test]
#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
fn indexed_compound_transaction_is_clean_under_asan_and_ubsan() {
    let source = "int main(){List<int>x={4,2};x[0]+=2;x[1]*=3;return x[0]-x[1];}";
    let compilation = compile(source, &[Emit::Llvm]).unwrap();
    let stem =
        std::env::temp_dir().join(format!("aether-compound-sanitized-{}", std::process::id()));
    let llvm = stem.with_extension("ll");
    let executable = stem.with_extension("out");
    fs::write(&llvm, compilation.llvm).unwrap();
    let linked = Command::new("clang")
        .args(["-O0", "-fsanitize=address,undefined"])
        .arg(&llvm)
        .arg("-o")
        .arg(&executable)
        .status()
        .unwrap();
    assert!(linked.success());
    let execution = Command::new(&executable)
        .env("ASAN_OPTIONS", "detect_leaks=0:halt_on_error=1")
        .env("UBSAN_OPTIONS", "halt_on_error=1:print_stacktrace=1")
        .output()
        .unwrap();
    let _ = fs::remove_file(&llvm);
    let _ = fs::remove_file(&executable);
    assert_eq!(
        execution.status.code(),
        Some(0),
        "{}",
        String::from_utf8_lossy(&execution.stderr)
    );
}

#[test]
#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
fn class_field_compound_transaction_is_clean_under_asan_and_ubsan() {
    let source = "class C{public int x;public init(){x=4;}public mut int run(){x+=2;x*=3;return x-18;}}int main(){C c=C();return c.run();}";
    let compilation = compile(source, &[Emit::Llvm]).unwrap();
    let stem = std::env::temp_dir().join(format!(
        "aether-compound-class-sanitized-{}",
        std::process::id()
    ));
    let llvm = stem.with_extension("ll");
    let executable = stem.with_extension("out");
    fs::write(&llvm, compilation.llvm).unwrap();
    let linked = Command::new("clang")
        .args(["-O0", "-fsanitize=address,undefined"])
        .arg(&llvm)
        .arg("-o")
        .arg(&executable)
        .status()
        .unwrap();
    assert!(linked.success());
    let execution = Command::new(&executable)
        .env("ASAN_OPTIONS", "detect_leaks=0:halt_on_error=1")
        .env("UBSAN_OPTIONS", "halt_on_error=1:print_stacktrace=1")
        .output()
        .unwrap();
    let _ = fs::remove_file(&llvm);
    let _ = fs::remove_file(&executable);
    assert_eq!(
        execution.status.code(),
        Some(0),
        "{}",
        String::from_utf8_lossy(&execution.stderr)
    );
}
