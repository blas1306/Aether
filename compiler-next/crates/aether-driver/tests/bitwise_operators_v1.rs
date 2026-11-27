//! Cross-layer qualification for BITWISE-OPERATORS-V1.

use std::{fs, path::PathBuf, process::Command};

use aether_driver::{ClangToolchain, Emit, OptimizationLevel, compile_source_with_optimization};
use aether_frontend::{SourceFile, analyze, parse_source};
use aether_middle::{
    BinaryOp, Rvalue, SsaOp, TrapKind, build_ssa, lower_hir, verify_mir, verify_ssa,
};

fn compile(source: &str) -> aether_driver::Compilation {
    compile_source_with_optimization(
        &SourceFile::new("bitwise_operators_v1.ae", source),
        &[Emit::Ast, Emit::Hir, Emit::Mir, Emit::Ssa, Emit::Llvm],
        OptimizationLevel::O0,
    )
    .unwrap_or_else(|errors| panic!("{source}\n{errors:#?}"))
}

struct Output(PathBuf);

impl Output {
    fn new() -> Self {
        static NEXT: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
        Self(std::env::temp_dir().join(format!(
            "aether-bitwise-v1-{}-{}",
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
        &SourceFile::new("bitwise_native.ae", source),
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
fn six_operators_reach_explicit_hir_mir_ssa_and_llvm_opcodes() {
    let compilation = compile(
        r"int main(){
          int32 a=12; int32 b=10; uint8 count=1;
          int32 x=(a&b)|(a^b); int32 n=~x;
          int32 l=a<<count; int32 r=n>>count;
          return int((l^r)&255);
        }",
    );
    for dump in [Emit::Hir, Emit::Mir, Emit::Ssa] {
        let text = &compilation.dumps[&dump];
        for opcode in [
            "BitwiseAnd",
            "BitwiseOr",
            "BitwiseXor",
            "BitwiseNot",
            "ShiftLeftChecked",
            "ShiftRightArithmetic",
        ] {
            assert!(text.contains(opcode), "{dump:?} lacks {opcode}\n{text}");
        }
    }
    let llvm = &compilation.llvm;
    for opcode in [" and ", " or ", " xor ", " shl ", " ashr "] {
        assert!(llvm.contains(opcode), "LLVM lacks {opcode}\n{llvm}");
    }
    assert!(llvm.contains("trap_shift_count_out_of_range"));
    assert!(llvm.contains("trap_integer_overflow"));
    assert_eq!(llvm.matches(" shl ").count(), 1, "{llvm}");
    let count_guard = llvm.find("br i1 %shift_invalid").unwrap();
    let overflow_guard = llvm.find("br i1 %shift_overflow").unwrap();
    let source_shift = llvm.find(" = shl ").unwrap();
    assert!(count_guard < overflow_guard && overflow_guard < source_shift);
    assert!(!llvm.contains(" shl nsw "));
    assert!(!llvm.contains(" shl nuw "));
}

#[test]
fn all_native_integer_types_aliases_and_heterogeneous_counts_are_admitted() {
    compile(
        r"alias Tiny=int8;int main(){
          int8 a=1;int16 b=1;int32 c=1;int64 d=1;uint8 e=1;uint16 f=1;
          uint32 g=1;uint64 h=1;isize i=1;usize j=1;Tiny t=1;
          uint64 count=1;
          a=a<<count;b=b>>count;c=~c;d=d^1;e=e|1;f=f&1;
          g=g<<count;h=h>>count;i=i<<count;j=j>>count;t=~t;
          return 0;
        }",
    );
}

#[test]
fn precedence_and_generic_closers_are_contextual() {
    let ast = parse_source(&SourceFile::new(
        "generic_shift.ae",
        "int main(){Matrix<Buffer<int>> owners=[Buffer<int>(1,1)];int x=8;return x>>1;}",
    ))
    .unwrap();
    let debug = format!("{ast:#?}");
    assert!(debug.contains("ShiftRight"));

    let ast = parse_source(&SourceFile::new(
        "precedence.ae",
        "int main(){int a=1;int b=2;int c=3;return a+b<<1&b^c|a==3||false;}",
    ))
    .unwrap();
    let debug = format!("{ast:#?}");
    assert!(debug.contains("BitwiseAnd"));
    assert!(debug.contains("BitwiseXor"));
    assert!(debug.contains("BitwiseOr"));
}

#[test]
fn invalid_types_mixes_and_counts_fail_closed() {
    for source in [
        "int main(){bool x=true;return int(x&x);}",
        "int main(){int32 x=1;uint32 y=1;return int(x|y);}",
        "int main(){int64 x=1;isize y=1;return int(x^y);}",
        "int main(){int x=1;return x<<-1;}",
        "int main(){int8 x=1;return int(x<<8);}",
        "int main(){return int(int8(127)<<1);}",
    ] {
        assert!(
            compile_source_with_optimization(
                &SourceFile::new("bad_bitwise.ae", source),
                &[],
                OptimizationLevel::O0,
            )
            .is_err(),
            "unexpectedly accepted {source}"
        );
    }
}

#[test]
fn constant_folding_preserves_signed_and_unsigned_bit_patterns() {
    let compilation = compile(
        "int main(){int8 a=~int8(0);uint8 b=~uint8(0);int8 c=int8(-3)>>1;return int(a)+int(b)+int(c)-252;}",
    );
    let hir = &compilation.dumps[&Emit::Hir];
    assert!(hir.contains("BitwiseNot"));
    assert!(hir.contains("ShiftRightArithmetic"));
}

#[test]
fn native_o0_o2_agree_and_dynamic_guards_trap_before_shifting() {
    let valid = r"int main(){
      int8 negative=-3;uint8 high=128;int8 left=-2;uint8 mask=240;
      if(negative>>1!=-2){return 1;}
      if(high>>1!=64){return 2;}
      if(left<<5!=-64){return 3;}
      if((mask&15)!=0||(mask|15)!=255||(mask^255)!=15||~mask!=15){return 4;}
      return 0;
    }";
    let bad_count = "int shift(int8 x,int8 c){return int(x<<c);}int main(){return shift(1,8);}";
    let overflow = "int shift(int8 x,uint8 c){return int(x<<c);}int main(){return shift(64,1);}";
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        assert_eq!(native_status(valid, optimization).code(), Some(0));
        assert!(!native_status(bad_count, optimization).success());
        assert!(!native_status(overflow, optimization).success());
    }
}

#[test]
fn mir_and_ssa_shift_contract_corruption_fails_closed() {
    let hir = analyze(
        parse_source(&SourceFile::new(
            "bitwise_corrupt.ae",
            "int main(){int x=8;uint8 c=1;return x<<c;}",
        ))
        .unwrap(),
    )
    .unwrap();
    let raw = lower_hir(hir);
    let verified = verify_mir(raw.clone()).unwrap();

    let mut bad_mir = raw;
    let shift = bad_mir
        .functions
        .iter_mut()
        .flat_map(|function| &mut function.blocks)
        .flat_map(|block| &mut block.instructions)
        .find_map(|instruction| match &mut instruction.value {
            Rvalue::Binary {
                op: BinaryOp::ShiftLeftChecked,
                trap,
                ..
            } => Some(trap),
            _ => None,
        })
        .unwrap();
    *shift = Some(TrapKind::IntegerOverflow);
    assert!(verify_mir(bad_mir).is_err());

    let mut bad_ssa = build_ssa(&verified);
    let shift = bad_ssa
        .functions
        .iter_mut()
        .flat_map(|function| &mut function.blocks)
        .flat_map(|block| &mut block.instructions)
        .find_map(|instruction| match &mut instruction.op {
            SsaOp::Binary {
                op: BinaryOp::ShiftLeftChecked,
                secondary_trap,
                ..
            } => Some(secondary_trap),
            _ => None,
        })
        .unwrap();
    *shift = Some(TrapKind::ShiftCountOutOfRange);
    assert!(verify_ssa(bad_ssa).is_err());
}
