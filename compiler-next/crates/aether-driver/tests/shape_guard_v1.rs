//! SHAPE-GUARD-V1 cross-layer, diagnostics, ordering and corruption qualification.

use std::{fs, path::PathBuf, process::Command};

use aether_driver::{
    ClangToolchain, CompilationSession, Emit, OptimizationLevel, compile_session_with_optimization,
    compile_source, compile_source_with_optimization,
};
use aether_frontend::{HirStmtKind, SourceFile, Span, TypeId, analyze, parse_source};
use aether_middle::{
    Operand, SsaOperand, SsaTerminator, Terminator, TrapKind, build_ssa, lower_hir, verify_mir,
    verify_ssa,
};

struct Output(PathBuf);

impl Output {
    fn new(label: &str) -> Self {
        static NEXT: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
        Self(std::env::temp_dir().join(format!(
            "aether-shape-guard-v1-{label}-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, std::sync::atomic::Ordering::Relaxed)
        )))
    }
}

impl Drop for Output {
    fn drop(&mut self) {
        let _ = fs::remove_file(&self.0);
        let _ = fs::remove_dir_all(&self.0);
    }
}

fn compile(source: &str, optimization: OptimizationLevel) -> aether_driver::Compilation {
    compile_source_with_optimization(
        &SourceFile::new("shape_guard_v1.ae", source),
        &[Emit::Hir, Emit::Mir, Emit::Ssa, Emit::Llvm],
        optimization,
    )
    .unwrap_or_else(|errors| panic!("{source}\n{errors:#?}"))
}

fn status_llvm(llvm: &str, optimization: OptimizationLevel) -> std::process::ExitStatus {
    let output = Output::new("native");
    ClangToolchain::default()
        .with_optimization(optimization)
        .link_executable(llvm, &output.0)
        .unwrap_or_else(|error| panic!("{error:#?}\n{llvm}"));
    Command::new(&output.0).status().unwrap()
}

fn status(source: &str, optimization: OptimizationLevel) -> std::process::ExitStatus {
    status_llvm(&compile(source, optimization).llvm, optimization)
}

#[test]
fn true_false_and_explicit_ir_survive_o0_o2() {
    let passing = "int main(){shapeGuard(true);return 0;}";
    let failing = "int main(){shapeGuard(false);return 0;}";
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        assert_eq!(status(passing, optimization).code(), Some(0));
        assert!(!status(failing, optimization).success());
        let compilation = compile(passing, optimization);
        for phase in [Emit::Hir, Emit::Mir, Emit::Ssa] {
            assert!(compilation.dumps[&phase].contains("ShapeGuard"));
            assert!(compilation.dumps[&phase].contains("ShapeMismatch"));
        }
        assert!(compilation.llvm.contains("trap_shape_mismatch:"));
        assert!(compilation.llvm.contains("call void @llvm.trap()"));
        assert!(!compilation.llvm.contains("aether_shape_guard"));
    }
}

#[test]
fn condition_is_evaluated_once_and_source_order_is_preserved() {
    let source = r"
bool tick(ref mut int trace){*trace=*trace*10+2;return true;}
int main(){int trace=1;shapeGuard(tick(&mut trace));trace=trace*10+3;return trace-123;}
";
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        assert_eq!(status(source, optimization).code(), Some(0));
    }

    let borrow = "bool square(ref Matrix<int>m){return rows(*m)==columns(*m);}int main(){Matrix<int>a=[1];shapeGuard(square(a));a[1,1]=2;return a[1,1]-2;}";
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        assert_eq!(status(borrow, optimization).code(), Some(0));
    }
}

#[test]
fn arbitrary_extent_relations_and_zero_extents_are_plain_bool_conditions() {
    let source = r"
int main(){
  Matrix<int>a=matrixFilled<int>(3,0,0);
  Matrix<int>b=matrixFilled<int>(0,3,0);
  Vector<int,Column>v=[];
  shapeGuard(rows(a)==columns(b));
  shapeGuard(columns(a)==dimension(v));
  shapeGuard(rows(b)==dimension(v));
  return 0;
}
";
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        assert_eq!(status(source, optimization).code(), Some(0));
    }
}

#[test]
fn a_condition_trap_is_not_converted_to_shape_mismatch() {
    let source = "bool condition(int x){int y=1/x;return y==0;}int main(){shapeGuard(condition(0));return 0;}";
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        let compilation = compile(source, optimization);
        let instrumented = compilation
            .llvm
            .replace(
                "trap_division_by_zero:\n  call void @llvm.trap()",
                "trap_division_by_zero:\n  call void @exit(i32 71)",
            )
            .replace(
                "trap_shape_mismatch:\n  ; structured Aether trap: ShapeMismatch\n  call void @llvm.trap()",
                "trap_shape_mismatch:\n  call void @exit(i32 72)",
            )
            + "\ndeclare void @exit(i32)\n";
        assert_eq!(status_llvm(&instrumented, optimization).code(), Some(71));
    }
}

#[test]
fn false_guard_precedes_later_allocation_index_division_and_call() {
    let cases = [
        "int main(){shapeGuard(false);Buffer<int>b=Buffer<int>(4,1);return b[0];}",
        "int main(){Array<int>a={1};usize i=8;shapeGuard(false);return a[i];}",
        "int main(){int z=0;shapeGuard(false);return 1/z;}",
        "int expensive(){return 9;}int main(){shapeGuard(false);return expensive();}",
    ];
    for source in cases {
        for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
            let compilation = compile(source, optimization);
            let instrumented = compilation.llvm.replace(
                "trap_shape_mismatch:\n  ; structured Aether trap: ShapeMismatch\n  call void @llvm.trap()",
                "trap_shape_mismatch:\n  call void @exit(i32 73)",
            ) + "\ndeclare void @exit(i32)\n";
            assert_eq!(status_llvm(&instrumented, optimization).code(), Some(73));
        }
    }
}

#[test]
fn diagnostics_close_every_noncanonical_surface() {
    let rejected = [
        "int main(){shapeGuard();return 0;}",
        "int main(){shapeGuard(true,false);return 0;}",
        "int main(){shapeGuard(1);return 0;}",
        "int main(){shapeGuard<bool>(true);return 0;}",
        "int main(){bool x=shapeGuard(true);return 0;}",
        "int main(){bool x=shapeGuard;return 0;}",
        "bool f(bool x){return shapeGuard(x);}int main(){return 0;}",
        "int main(){std.shapeGuard(true);return 0;}",
        "struct S{}int main(){S s=S();s.shapeGuard(true);return 0;}",
        "void shapeGuard(bool x){}int main(){shapeGuard(true);return 0;}",
        "int main(){bool shapeGuard=true;return 0;}",
        "int f(bool shapeGuard){return 0;}int main(){return 0;}",
    ];
    for source in rejected {
        let errors =
            compile_source(&SourceFile::new("bad_shape_guard.ae", source), &[]).unwrap_err();
        assert!(!errors.is_empty(), "unexpectedly accepted: {source}");
    }
}

#[test]
fn ordinary_package_guard_is_preserved_for_a_separate_consumer() {
    let directory = Output::new("package");
    fs::create_dir_all(&directory.0).unwrap();
    let library = directory.0.join("guardlib.ae");
    let entry = directory.0.join("main.ae");
    fs::write(
        &library,
        "package guardlib;bool admitted(int rows,int columns){shapeGuard(rows==columns);return true;}",
    )
    .unwrap();
    fs::write(
        &entry,
        "package consumer;import guardlib;int main(){if(guardlib.admitted(2,2)){return 0;}return 1;}",
    )
    .unwrap();
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        let compilation = compile_session_with_optimization(
            CompilationSession::discover(&entry).unwrap(),
            &[Emit::Hir, Emit::Mir, Emit::Ssa],
            optimization,
        )
        .unwrap();
        for phase in [Emit::Hir, Emit::Mir, Emit::Ssa] {
            assert!(compilation.dumps[&phase].contains("ShapeGuard"));
        }
        assert_eq!(status_llvm(&compilation.llvm, optimization).code(), Some(0));
    }
}

#[test]
#[allow(clippy::too_many_lines)]
fn malformed_mir_and_ssa_guards_fail_closed() {
    let source = SourceFile::new(
        "corrupt_shape_guard.ae",
        "int main(){shapeGuard(true);return 0;}",
    );
    let hir = analyze(parse_source(&source).unwrap()).unwrap();
    assert!(matches!(
        hir.functions()[hir.entry().0 as usize].body.statements[0].kind,
        HirStmtKind::ShapeGuard { .. }
    ));
    let raw = lower_hir(hir);
    let guard_block = raw.functions[0]
        .blocks
        .iter()
        .position(|block| matches!(block.terminator, Some(Terminator::ShapeGuard { .. })))
        .unwrap();

    for corrupt in 0..7 {
        let mut bad = raw.clone();
        let (success_id, failure_id) = match bad.functions[0].blocks[guard_block]
            .terminator
            .as_ref()
            .unwrap()
        {
            Terminator::ShapeGuard {
                success, failure, ..
            } => (*success, *failure),
            _ => unreachable!(),
        };
        match corrupt {
            0..=3 => {
                let Terminator::ShapeGuard {
                    condition,
                    failure,
                    trap,
                    span,
                    ..
                } = bad.functions[0].blocks[guard_block]
                    .terminator
                    .as_mut()
                    .unwrap()
                else {
                    unreachable!()
                };
                match corrupt {
                    0 => {
                        *condition = Operand::Int {
                            value: 1,
                            ty: TypeId::INT64,
                        }
                    }
                    1 => *trap = TrapKind::IndexOutOfBounds,
                    2 => *failure = success_id,
                    3 => *span = Span::default(),
                    _ => unreachable!(),
                }
            }
            4 => {
                bad.functions[0].blocks[failure_id.0 as usize].terminator =
                    Some(Terminator::Trap(TrapKind::DivisionByZero));
            }
            5 => bad.functions[0].blocks[failure_id.0 as usize].landing_pad_catches = true,
            6 => {
                let instruction = bad.functions[0].blocks[guard_block]
                    .instructions
                    .last()
                    .unwrap()
                    .clone();
                bad.functions[0].blocks[failure_id.0 as usize]
                    .instructions
                    .push(instruction);
            }
            _ => unreachable!(),
        }
        assert!(
            verify_mir(bad).is_err(),
            "MIR accepted corruption {corrupt}"
        );
    }

    let verified = verify_mir(raw).unwrap();
    let ssa = build_ssa(&verified);
    let guard_block = ssa.functions[0]
        .blocks
        .iter()
        .position(|block| matches!(block.terminator, SsaTerminator::ShapeGuard { .. }))
        .unwrap();
    for corrupt in 0..8 {
        let mut bad = ssa.clone();
        let (success_id, failure_id) = match &bad.functions[0].blocks[guard_block].terminator {
            SsaTerminator::ShapeGuard {
                success, failure, ..
            } => (*success, *failure),
            _ => unreachable!(),
        };
        match corrupt {
            0..=3 => {
                let SsaTerminator::ShapeGuard {
                    condition,
                    failure,
                    trap,
                    span,
                    ..
                } = &mut bad.functions[0].blocks[guard_block].terminator
                else {
                    unreachable!()
                };
                match corrupt {
                    0 => {
                        *condition = SsaOperand::Int {
                            value: 1,
                            ty: TypeId::INT64,
                        }
                    }
                    1 => *trap = TrapKind::IndexOutOfBounds,
                    2 => *failure = success_id,
                    3 => *span = Span::default(),
                    _ => unreachable!(),
                }
            }
            4 => {
                bad.functions[0].blocks[failure_id.0 as usize].terminator =
                    SsaTerminator::Trap(TrapKind::DivisionByZero);
            }
            5 => bad.functions[0].blocks[failure_id.0 as usize].landing_pad_catches = true,
            6 => bad.functions[0].blocks[failure_id.0 as usize]
                .phis
                .push(aether_middle::Phi {
                    result: aether_middle::ValueId(99),
                    ty: TypeId::BOOL,
                    local: aether_frontend::LocalId(0),
                    incoming: Vec::new(),
                }),
            7 => {
                let mut instruction = bad.functions[0].blocks[guard_block]
                    .instructions
                    .last()
                    .unwrap()
                    .clone();
                instruction.result = aether_middle::ValueId(
                    bad.functions[0]
                        .blocks
                        .iter()
                        .flat_map(|block| &block.instructions)
                        .map(|instruction| instruction.result.0)
                        .max()
                        .unwrap()
                        + 1,
                );
                bad.functions[0].blocks[failure_id.0 as usize]
                    .instructions
                    .push(instruction);
            }
            _ => unreachable!(),
        }
        assert!(
            verify_ssa(bad).is_err(),
            "SSA accepted corruption {corrupt}"
        );
    }
}
