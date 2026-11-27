//! Cross-layer qualification for POSTFIX-UPDATE-V1.

use std::{fs, path::Path, process::Command};

use aether_driver::{ClangToolchain, Emit, compile_source, run_path};
use aether_frontend::SourceFile;

fn compile(
    source: &str,
    emits: &[Emit],
) -> Result<aether_driver::Compilation, Vec<aether_driver::Diagnostic>> {
    compile_source(&SourceFile::new("postfix-update.ae", source), emits)
}

#[test]
fn ast_retains_postfix_origin_then_hir_reuses_compound_transaction() {
    let compiled = compile(
        "int main(){int x=1;x++;x--;return x;}",
        &[Emit::Ast, Emit::Hir, Emit::Mir, Emit::Ssa, Emit::Llvm],
    )
    .unwrap();
    assert!(
        compiled.dumps[&Emit::Ast]
            .matches("origin: PostfixUpdate")
            .count()
            >= 2
    );
    assert!(compiled.dumps[&Emit::Hir].matches("CompoundAssign").count() >= 2);
    for phase in [Emit::Mir, Emit::Ssa] {
        assert!(compiled.dumps[&phase].matches("CompoundLoad").count() >= 2);
        assert!(compiled.dumps[&phase].matches("CompoundCommit").count() >= 2);
        assert!(compiled.dumps[&phase].contains("AddIntegerChecked"));
        assert!(compiled.dumps[&phase].contains("SubtractIntegerChecked"));
    }
    assert!(compiled.llvm.contains("with.overflow"));
}

#[test]
fn all_native_integer_types_and_transparent_aliases_are_admitted() {
    let source = r"
        alias Tiny = int8;
        int main() {
            int8 a=1; int16 b=1; int32 c=1; int64 d=1;
            uint8 e=2; uint16 f=2; uint32 g=2; uint64 h=2;
            isize i=1; usize j=2; int k=1; Tiny aliasValue=1;
            a++; b++; c++; d++; i++; k++; aliasValue++;
            e--; f--; g--; h--; j--;
            return 0;
        }
    ";
    compile(source, &[Emit::Hir, Emit::Mir, Emit::Ssa, Emit::Llvm]).unwrap();
}

#[test]
fn postfix_updates_cover_the_existing_mutable_scalar_destinations() {
    for source in [
        "struct S{int x;}int main(){S s=S(1);s.x++;return s.x;}",
        "int main(){Array<int>a={1};a[0]++;return a[0];}",
        "int main(){Buffer<int>a=Buffer<int>(1,2);a[0]--;return a[0];}",
        "int main(){List<int>a={1};a[0]++;return a[0];}",
        "int main(){Array<int>a={1};ViewMut<int>v=view_mut(a);v[0]++;return a[0];}",
        "int main(){int x=1;ref mut int r=&mut x;(*r)++;return x;}",
        "int main(){Vector<int,Row>v=[1,2];v[2]++;return v[2];}",
        "int main(){Matrix<int>m=[1,2;3,4];m[2,1]--;return m[2,1];}",
        "class C{public int x;public init(){x=1;}public mut int bump(){this.x++;x--;return x;}}int main(){C c=C();c.x++;return c.bump();}",
        "open class B{public int x;public init(){x=1;}}class C:B{public init():base(){}public mut int bump(){x++;return x;}}int main(){C c=C();return c.bump();}",
    ] {
        compile(source, &[]).unwrap_or_else(|errors| panic!("{source}: {errors:#?}"));
    }
}

#[test]
fn postfix_forms_are_statement_only_and_integer_only() {
    for source in [
        "int main(){int i=1;++i;return i;}",
        "int main(){int i=1;--i;return i;}",
        "int main(){int i=1;int x=i++;return x;}",
        "int main(){int i=1;return i++;}",
        "int main(){int i=1;println(i++);return i;}",
        "int main(){int i=1;i+++i;return i;}",
        "int main(){bool x=true;x++;return 0;}",
        "int main(){float32 x=1.0;x++;return 0;}",
        "int main(){float64 x=1.0;x--;return 0;}",
        "int main(){char x='a';x++;return 0;}",
        "int main(){string x=\"a\";x++;return 0;}",
        "int main(){int x=1;ref int r=&x;(*r)++;return x;}",
        "int main(){const int x=1;x++;return x;}",
    ] {
        assert!(
            compile(source, &[]).is_err(),
            "unexpected acceptance: {source}"
        );
    }
}

#[test]
fn forbidden_prefix_and_value_contexts_have_postfix_specific_diagnostics() {
    let prefix = compile("int main(){int i=1;++i;return i;}", &[]).unwrap_err();
    assert!(prefix[0].message.contains("prefix `++` and `--`"));

    let value = compile("int main(){int i=1;return i++;}", &[]).unwrap_err();
    assert!(value[0].message.contains("standalone statements"));
}

#[test]
fn maximal_munch_preserves_adjacent_existing_operators() {
    compile(
        "int main(){int a=1;int b=2;a+=b;a=a+b;a-=b;a=a-b;a /* gap */ ++;a-- /* gap */;return a;}",
        &[],
    )
    .unwrap();
}

#[test]
fn indexed_destination_is_evaluated_once_and_matches_compound_assignment() {
    let source = r"
        int next(ref mut int calls){*calls=*calls+1;return 0;}
        int main(){
            int calls=0;List<int>a={4};
            a[next(&mut calls)]++;
            if(calls!=1||a[0]!=5){return 1;}
            int left=9;int right=9;left--;right-=1;
            if(left!=right){return 2;}
            return 0;
        }
    ";
    let compiled = compile(source, &[Emit::Mir, Emit::Ssa]).unwrap();
    for phase in [Emit::Mir, Emit::Ssa] {
        assert!(compiled.dumps[&phase].contains("next"));
        assert!(compiled.dumps[&phase].matches("CompoundCommit").count() >= 3);
    }
}

#[test]
fn integer_overflow_and_underflow_keep_checked_traps() {
    for (source, intrinsic) in [
        (
            "int main(){int8 x=127;x++;return 0;}",
            "sadd.with.overflow.i8",
        ),
        (
            "int main(){uint8 x=0;x--;return 0;}",
            "usub.with.overflow.i8",
        ),
    ] {
        let compiled = compile(source, &[Emit::Mir, Emit::Ssa, Emit::Llvm]).unwrap();
        assert!(
            compiled.llvm.contains(intrinsic),
            "{intrinsic}: {}",
            compiled.llvm
        );
        for phase in [Emit::Mir, Emit::Ssa] {
            assert!(compiled.dumps[&phase].contains("IntegerOverflow"));
        }
    }
}

#[test]
#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
fn native_fixture_is_identical_at_o0_and_o2() {
    let path = Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("../..")
        .join("tests/programs/postfix_update_v1.ae");
    let (_, status) = run_path(&path, &[], &ClangToolchain::default()).unwrap();
    assert_eq!(status.code(), Some(0));
    let source = fs::read_to_string(path).unwrap();
    let compilation = compile(&source, &[Emit::Llvm]).unwrap();
    for optimization in ["-O0", "-O2"] {
        let stem = std::env::temp_dir().join(format!(
            "aether-postfix-update-{}-{optimization}",
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
        let _ = fs::remove_file(llvm);
        let _ = fs::remove_file(executable);
    }
}
