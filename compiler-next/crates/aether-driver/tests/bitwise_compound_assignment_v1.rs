//! Cross-layer qualification for BITWISE-COMPOUND-ASSIGNMENT-V1.

use std::{fs, path::PathBuf, process::Command};

use aether_driver::{ClangToolchain, Emit, OptimizationLevel, compile_source_with_optimization};
use aether_frontend::{SourceFile, analyze, parse_source};
use aether_middle::{
    BinaryOp, Rvalue, SsaOp, TrapKind, build_ssa, lower_hir, verify_mir, verify_ssa,
};

fn compile(source: &str, emits: &[Emit]) -> aether_driver::Compilation {
    compile_source_with_optimization(
        &SourceFile::new("bitwise_compound_assignment_v1.ae", source),
        emits,
        OptimizationLevel::O0,
    )
    .unwrap_or_else(|errors| panic!("{source}\n{errors:#?}"))
}

fn rejected(source: &str) {
    assert!(
        compile_source_with_optimization(
            &SourceFile::new("bad_bitwise_compound.ae", source),
            &[],
            OptimizationLevel::O0,
        )
        .is_err(),
        "unexpected acceptance: {source}"
    );
}

struct Output(PathBuf);

impl Output {
    fn new() -> Self {
        static NEXT: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
        Self(std::env::temp_dir().join(format!(
            "aether-bitwise-compound-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, std::sync::atomic::Ordering::Relaxed)
        )))
    }
}

impl Drop for Output {
    fn drop(&mut self) {
        let _ = fs::remove_file(&self.0);
    }
}

fn native_status(source: &str, optimization: OptimizationLevel) -> std::process::ExitStatus {
    let compilation = compile_source_with_optimization(
        &SourceFile::new("bitwise_compound_native.ae", source),
        &[Emit::Llvm],
        optimization,
    )
    .unwrap_or_else(|errors| panic!("{source}\n{errors:#?}"));
    let output = Output::new();
    ClangToolchain::default()
        .with_optimization(optimization)
        .link_executable(&compilation.llvm, &output.0)
        .unwrap();
    Command::new(&output.0).status().unwrap()
}

#[test]
fn five_operators_reuse_the_transaction_and_bitwise_pipeline() {
    let compiled = compile(
        "int main(){int32 x=12;int32 mask=10;uint8 count=1;x&=mask;x|=mask;x^=mask;x<<=count;x>>=count;return int(x);}",
        &[Emit::Ast, Emit::Hir, Emit::Mir, Emit::Ssa, Emit::Llvm],
    );
    let hir = &compiled.dumps[&Emit::Hir];
    for op in [
        "BitwiseAnd",
        "BitwiseOr",
        "BitwiseXor",
        "ShiftLeftChecked",
        "ShiftRightArithmetic",
    ] {
        assert!(hir.contains(op), "HIR lacks {op}\n{hir}");
    }
    for phase in [Emit::Mir, Emit::Ssa] {
        let dump = &compiled.dumps[&phase];
        assert_eq!(dump.matches("CompoundLoad").count(), 5, "{dump}");
        assert_eq!(dump.matches("CompoundCommit").count(), 5, "{dump}");
    }
    for opcode in [" and ", " or ", " xor ", " shl ", " ashr "] {
        assert!(compiled.llvm.contains(opcode), "LLVM lacks {opcode}");
    }
    assert!(compiled.llvm.contains("trap_shift_count_out_of_range"));
    assert!(compiled.llvm.contains("trap_integer_overflow"));
}

#[test]
fn all_integer_destinations_aliases_and_heterogeneous_counts_are_admitted() {
    compile(
        r"alias Tiny=int8;int main(){
          int8 a=1;int16 b=1;int32 c=1;int64 d=1;uint8 e=1;uint16 f=1;
          uint32 g=1;uint64 h=1;isize i=1;usize j=1;Tiny t=1;uint64 wide=1;
          a<<=wide;b>>=uint8(1);c&=int32(1);d|=int64(1);e^=uint8(1);
          f<<=int8(1);g>>=int16(1);h<<=int32(1);i>>=usize(1);j<<=isize(1);t^=Tiny(1);
          return 0;
        }",
        &[],
    );
}

#[test]
fn exact_rhs_and_statement_only_surface_fail_closed() {
    for source in [
        "int main(){int32 x=1;uint32 y=1;x&=y;return 0;}",
        "int main(){int32 x=1;uint32 y=1;x|=y;return 0;}",
        "int main(){int32 x=1;uint32 y=1;x^=y;return 0;}",
        "int main(){float64 x=1.0;x&=1;return 0;}",
        "int main(){int x=1;int y=(x&=1);return y;}",
        "int main(){int x=1;return x<<=1;}",
        "int main(){int x=1;int y=2;x&=y&=1;return x;}",
    ] {
        rejected(source);
    }
}

#[test]
fn mir_and_ssa_corruption_of_the_bitwise_transaction_fails_closed() {
    let hir = analyze(
        parse_source(&SourceFile::new(
            "bitwise_compound_corrupt.ae",
            "int main(){int8 x=1;uint16 c=1;x<<=c;return x;}",
        ))
        .unwrap(),
    )
    .unwrap();

    let mir = lower_hir(hir);
    let verified = verify_mir(mir.clone()).unwrap();
    let mut bad_mir = mir;
    let secondary_trap = bad_mir
        .functions
        .iter_mut()
        .flat_map(|function| &mut function.blocks)
        .flat_map(|block| &mut block.instructions)
        .find_map(|instruction| match &mut instruction.value {
            Rvalue::Binary {
                op: BinaryOp::ShiftLeftChecked,
                secondary_trap,
                ..
            } => Some(secondary_trap),
            _ => None,
        })
        .unwrap();
    *secondary_trap = None;
    assert!(verify_mir(bad_mir).is_err());

    let mut bad_ssa = build_ssa(&verified);
    let primary_trap = bad_ssa
        .functions
        .iter_mut()
        .flat_map(|function| &mut function.blocks)
        .flat_map(|block| &mut block.instructions)
        .find_map(|instruction| match &mut instruction.op {
            SsaOp::Binary {
                op: BinaryOp::ShiftLeftChecked,
                trap,
                ..
            } => Some(trap),
            _ => None,
        })
        .unwrap();
    *primary_trap = Some(TrapKind::IntegerOverflow);
    assert!(verify_ssa(bad_ssa).is_err());
}

#[test]
fn compound_places_share_existing_writability_and_stabilization_rules() {
    for source in [
        "struct S{int x;}int main(){S s=S(7);s.x&=3;return s.x;}",
        "int main(){Array<int>a={8};a[0]>>=uint8(1);return a[0];}",
        "int main(){List<int>a={1};a[0]<<=uint8(2);return a[0];}",
        "int main(){Buffer<int>a=Buffer<int>(1,3);a[0]^=1;return a[0];}",
        "int main(){Array<int>a={1};ViewMut<int>v=view_mut(a);v[0]|=2;return a[0];}",
        "int main(){int x=3;ref mut int r=&mut x;*r&=1;return x;}",
        "int main(){Vector<int,Row>v=[1,2];v[2]|=4;return v[2];}",
        "int main(){Matrix<int>m=[8];m[1,1]>>=1;return m[1,1];}",
        "class C{public int x;public init(){x=7;}public mut int f(){x&=3;return x;}}int main(){C c=C();c.x|=8;return c.f();}",
    ] {
        compile(source, &[]);
    }
    for source in [
        "int main(){int x=1;ref int r=&x;*r&=1;return x;}",
        "int main(){Array<int>a={1};View<int>v=view(a);v[0]|=2;return a[0];}",
    ] {
        rejected(source);
    }
}

#[test]
fn rhs_aliasing_uses_the_captured_old_value_and_invalidation_is_rejected() {
    let same_slot = "int touch(ref mut int x){*x=7;return 2;}int main(){int x=12;x^=touch(&mut x);return x==14?0:1;}";
    // Conditional expressions are intentionally outside the language surface;
    // use a statement conditional to observe that RHS mutation did not replace old.
    let same_slot = same_slot.replace("return x==14?0:1;", "if(x==14){return 0;}return 1;");
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        assert_eq!(native_status(&same_slot, optimization).code(), Some(0));
    }
    rejected(
        "int grow(ref mut List<int>x){push(*x,2);return 1;}int main(){List<int>x={1};x[0]|=grow(&mut x);return x[0];}",
    );
}

#[test]
fn native_o0_o2_preserve_values_and_shift_traps() {
    let valid = "int main(){int8 x=12;uint8 y=240;uint16 c=1;x&=int8(10);x|=int8(1);x^=int8(3);x<<=c;x>>=int8(1);y>>=c;if(x==10&&y==120){return 0;}return 1;}";
    let bad_count = "int main(){int8 x=1;x<<=uint8(8);return x;}";
    let negative_count = "int main(){int8 x=1;x>>=int8(-1);return x;}";
    let overflow = "int main(){int8 x=64;x<<=uint8(1);return x;}";
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        assert_eq!(native_status(valid, optimization).code(), Some(0));
        assert!(!native_status(bad_count, optimization).success());
        assert!(!native_status(negative_count, optimization).success());
        assert!(!native_status(overflow, optimization).success());
    }
}
