//! EXCEPTION-V3 virtual/interface unwind qualification for Linux x86-64.

use std::{fs, path::PathBuf, process::Command};

use aether_driver::{Emit, OptimizationLevel, compile_source_with_optimization};
use aether_frontend::{ClassOp, RequirementId, SourceFile, analyze, parse_source};
use aether_middle::{Rvalue, SsaOp, build_ssa, lower_hir, verify_mir, verify_ssa};

struct Directory(PathBuf);

impl Directory {
    fn new() -> Self {
        static NEXT: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
        let path = std::env::temp_dir().join(format!(
            "aether-exception-v3-{}-{}",
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

fn compile(text: &str, optimization: OptimizationLevel) -> aether_driver::Compilation {
    compile_source_with_optimization(
        &SourceFile::new("exception_v3.ae", text),
        &[Emit::Hir, Emit::Mir, Emit::Ssa],
        optimization,
    )
    .unwrap_or_else(|errors| panic!("{text}\n{errors:#?}"))
}

fn run_status(llvm: &str, optimization: OptimizationLevel) -> i32 {
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
    Command::new(executable).status().unwrap().code().unwrap()
}

fn probe_counts(llvm: &str, optimization: OptimizationLevel) -> [i32; 7] {
    let names = [
        "object_alloc",
        "object_retain",
        "object_release",
        "object_destroy",
        "object_buffer_drop",
        "heap_alloc",
        "heap_free",
    ];
    names.map(|name| {
        let probed = llvm.replace(
            "  ret i32 %process_status",
            &format!("  %probe = load i64, ptr @aether_{name}_count\n  %probe32 = trunc i64 %probe to i32\n  ret i32 %probe32"),
        );
        run_status(&probed, optimization)
    })
}

fn qualify(text: &str, result: i32, counts: [i32; 7]) {
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        let compilation = compile(text, optimization);
        assert_eq!(run_status(&compilation.llvm, optimization), result);
        assert_eq!(probe_counts(&compilation.llvm, optimization), counts);
    }
}

const PREFIX: &str = "open class Problem:Exception{public init(){}}";

#[test]
fn virtual_exact_and_dynamic_override_unwind_at_o0_and_o2() {
    let exact = format!(
        "{PREFIX} open class Worker{{public init(){{}}public open int run(){{throw Problem();}}}}int main(){{Worker worker=Worker();try{{return worker.run();}}catch(Problem problem){{return 11;}}}}"
    );
    qualify(&exact, 11, [2, 2, 4, 2, 0, 2, 2]);

    let dynamic = format!(
        "{PREFIX} open class Base{{public init(){{}}public open int run(){{return 1;}}}}class Derived:Base{{public init():base(){{}}public override int run(){{throw Problem();}}}}int main(){{Base value=Derived();try{{return value.run();}}catch(Problem problem){{return 12;}}}}"
    );
    qualify(&dynamic, 12, [2, 2, 4, 2, 0, 2, 2]);

    let o0 = compile(&dynamic, OptimizationLevel::O0);
    assert!(o0.llvm.contains("invoke i64 %target"));
    let o2 = compile(&dynamic, OptimizationLevel::O2);
    assert!(o2.llvm.contains("OOP-POLISH-1 class devirtualization"));
    assert!(o2.llvm.contains("invoke i64 @"));
}

#[test]
fn interface_and_inherited_override_unwind_at_o0_and_o2() {
    let direct = format!(
        "{PREFIX} interface Fallible{{int run();}}class Worker:Fallible{{public init(){{}}public int run(){{throw Problem();}}}}int main(){{Fallible value=Worker();try{{return value.run();}}catch(Problem problem){{return 21;}}}}"
    );
    qualify(&direct, 21, [2, 2, 4, 2, 0, 2, 2]);

    let inherited = format!(
        "{PREFIX} interface Fallible{{int run();}}open class Base:Fallible{{public init(){{}}public open int run(){{return 1;}}}}class Derived:Base{{public init():base(){{}}public override int run(){{throw Problem();}}}}int main(){{Fallible value=Derived();try{{return value.run();}}catch(Problem problem){{return 22;}}}}"
    );
    qualify(&inherited, 22, [2, 2, 4, 2, 0, 2, 2]);

    let o0 = compile(&inherited, OptimizationLevel::O0);
    assert!(o0.llvm.contains("invoke i64 %target"));
    let o2 = compile(&inherited, OptimizationLevel::O2);
    assert!(o2.llvm.contains("OOP-OPT-1 devirtualization"));
    assert!(o2.llvm.contains("invoke i64 @"));
}

#[test]
fn receiver_keepalive_and_owning_argument_are_cleaned_once_on_unwind() {
    let text = format!(
        "{PREFIX} class Argument{{public init(){{}}}}open class Worker{{Buffer<int> value;public init(){{this.value=Buffer<int>(2,7);}}public open int run(Argument argument){{throw Problem();}}}}int main(){{Worker worker=Worker();try{{return worker.run(Argument());}}catch(Problem problem){{return 31;}}}}"
    );
    let compilation = compile(&text, OptimizationLevel::O0);
    let mir = &compilation.dumps[&Emit::Mir];
    assert!(mir.contains("VirtualCall"));
    assert!(mir.contains("unwind: Some"));
    assert!(mir.contains("Drop"));
    qualify(&text, 31, [3, 2, 5, 3, 1, 4, 4]);

    let fresh = format!(
        "{PREFIX} open class Worker{{Buffer<int> value;public init(){{this.value=Buffer<int>(1,7);}}public open int run(){{throw Problem();}}}}int main(){{try{{return Worker().run();}}catch(Problem problem){{return 32;}}}}"
    );
    qualify(&fresh, 32, [2, 1, 3, 2, 1, 3, 3]);

    let argument_unwind = format!(
        "{PREFIX} int failArg(){{throw Problem();}}class Argument{{public init(){{}}}}open class Worker{{public open int run(Argument argument,int value){{if(value<0){{throw Problem();}}return value;}}}}int main(){{Worker worker=Worker();try{{return worker.run(Argument(),failArg());}}catch(Problem problem){{return 33;}}}}"
    );
    qualify(&argument_unwind, 33, [3, 2, 5, 3, 0, 3, 3]);
}

#[test]
fn owning_result_is_created_only_on_the_normal_edge() {
    let text = format!(
        "{PREFIX} class Product{{public init(){{}}}}open class Factory{{public open Product make(){{throw Problem();}}}}int main(){{Factory factory=Factory();try{{Product product=factory.make();return 1;}}catch(Problem problem){{return 34;}}}}"
    );
    qualify(&text, 34, [2, 2, 4, 2, 0, 2, 2]);
}

#[test]
fn virtual_unwind_inside_initializer_composes_with_constructor_rollback() {
    let text = format!(
        "{PREFIX} open class Worker{{public open int run(){{throw Problem();}}}}class Owner{{Buffer<int> value;public init(){{this.value=Buffer<int>(1,7);Worker worker=Worker();worker.run();}}}}int main(){{try{{Owner owner=Owner();}}catch(Problem problem){{return 35;}}return 36;}}"
    );
    qualify(&text, 35, [3, 2, 4, 2, 1, 4, 4]);
}

#[test]
fn exact_devirtualizes_but_unknown_and_mixed_provenance_remain_indirect() {
    let unknown = format!(
        "{PREFIX} open class Base{{public open int run(){{return 1;}}}}class Thrower:Base{{public override int run(){{throw Problem();}}}}int call(Base value){{return value.run();}}int main(){{try{{return call(Thrower());}}catch(Problem problem){{return 41;}}}}"
    );
    let mixed = format!(
        "{PREFIX} open class Base{{public open int run(){{return 1;}}}}class Thrower:Base{{public override int run(){{throw Problem();}}}}class Other:Base{{public override int run(){{return 2;}}}}int call(bool choose){{Base value=Thrower();if(choose){{value=Other();}}return value.run();}}int main(){{try{{return call(false);}}catch(Problem problem){{return 42;}}}}"
    );
    for (text, result) in [(&unknown, 41), (&mixed, 42)] {
        let compilation = compile(text, OptimizationLevel::O2);
        assert!(
            !compilation
                .llvm
                .contains("OOP-POLISH-1 class devirtualization")
        );
        assert!(compilation.llvm.contains("invoke i64 %target"));
        assert_eq!(run_status(&compilation.llvm, OptimizationLevel::O2), result);
        let expected = [2, 2, 4, 2, 0, 2, 2];
        assert_eq!(
            probe_counts(&compilation.llvm, OptimizationLevel::O2),
            expected
        );
    }

    let interface_unknown = format!(
        "{PREFIX} interface Fallible{{int run();}}class Thrower:Fallible{{public int run(){{throw Problem();}}}}int call(Fallible value){{return value.run();}}int main(){{try{{return call(Thrower());}}catch(Problem problem){{return 43;}}}}"
    );
    let compilation = compile(&interface_unknown, OptimizationLevel::O2);
    assert!(!compilation.llvm.contains("OOP-OPT-1 devirtualization"));
    assert!(compilation.llvm.contains("invoke i64 %target"));
    assert_eq!(run_status(&compilation.llvm, OptimizationLevel::O2), 43);
    assert_eq!(
        probe_counts(&compilation.llvm, OptimizationLevel::O2),
        [2, 2, 4, 2, 0, 2, 2]
    );
}

#[test]
#[allow(clippy::too_many_lines)]
fn malformed_dispatch_and_unwind_are_rejected_in_mir_and_ssa() {
    let source = format!(
        "{PREFIX} interface Fallible{{int run();}}class Worker:Fallible{{public int run(){{throw Problem();}}}}int main(){{Fallible value=Worker();try{{return value.run();}}catch(Problem problem){{return 0;}}}}"
    );
    let hir = analyze(parse_source(&SourceFile::new("bad_v3.ae", &source)).unwrap()).unwrap();
    let mir = lower_hir(hir);

    let mut missing_unwind = mir.clone();
    let instruction = missing_unwind
        .functions
        .iter_mut()
        .flat_map(|function| &mut function.blocks)
        .flat_map(|block| &mut block.instructions)
        .find(|instruction| matches!(&instruction.value, Rvalue::Class(op) if matches!(op.as_ref(), ClassOp::InterfaceCall { .. })))
        .unwrap();
    instruction.unwind = None;
    assert!(verify_mir(missing_unwind).is_err());

    let mut missing_cleanup = mir.clone();
    let (function_index, unwind) = missing_cleanup
        .functions
        .iter()
        .enumerate()
        .find_map(|(function_index, function)| {
            function
                .blocks
                .iter()
                .flat_map(|block| &block.instructions)
                .find_map(|instruction| match &instruction.value {
                    Rvalue::Class(op) if matches!(op.as_ref(), ClassOp::InterfaceCall { .. }) => {
                        instruction.unwind.map(|unwind| (function_index, unwind))
                    }
                    _ => None,
                })
        })
        .unwrap();
    let function = &mut missing_cleanup.functions[function_index];
    let cleanup = &mut function.blocks[unwind.0 as usize].instructions;
    let drop = cleanup
        .iter()
        .position(|instruction| matches!(instruction.value, Rvalue::Drop { .. }))
        .unwrap();
    cleanup.remove(drop);
    assert!(verify_mir(missing_cleanup).is_err());

    let mut wrong_requirement = mir.clone();
    let op = wrong_requirement
        .functions
        .iter_mut()
        .flat_map(|function| &mut function.blocks)
        .flat_map(|block| &mut block.instructions)
        .find_map(|instruction| match &mut instruction.value {
            Rvalue::Class(op) if matches!(op.as_ref(), ClassOp::InterfaceCall { .. }) => Some(op),
            _ => None,
        })
        .unwrap();
    let ClassOp::InterfaceCall { requirement, .. } = op.as_mut() else {
        unreachable!()
    };
    *requirement = RequirementId {
        interface: requirement.interface,
        index: 999,
    };
    assert!(verify_mir(wrong_requirement).is_err());

    let ssa = build_ssa(&verify_mir(mir).unwrap());
    let mut missing_ssa_unwind = ssa.clone();
    let instruction = missing_ssa_unwind
        .functions
        .iter_mut()
        .flat_map(|function| &mut function.blocks)
        .flat_map(|block| &mut block.instructions)
        .find(|instruction| matches!(&instruction.op, SsaOp::Class(op) if matches!(op.as_ref(), ClassOp::InterfaceCall { .. })))
        .unwrap();
    instruction.unwind = None;
    assert!(verify_ssa(missing_ssa_unwind).is_err());

    let mut missing_ssa_cleanup = ssa.clone();
    let (function_index, unwind) = missing_ssa_cleanup
        .functions
        .iter()
        .enumerate()
        .find_map(|(function_index, function)| {
            function
                .blocks
                .iter()
                .flat_map(|block| &block.instructions)
                .find_map(|instruction| match &instruction.op {
                    SsaOp::Class(op) if matches!(op.as_ref(), ClassOp::InterfaceCall { .. }) => {
                        instruction.unwind.map(|unwind| (function_index, unwind))
                    }
                    _ => None,
                })
        })
        .unwrap();
    let cleanup =
        &mut missing_ssa_cleanup.functions[function_index].blocks[unwind.0 as usize].instructions;
    let drop = cleanup
        .iter()
        .position(|instruction| matches!(instruction.op, SsaOp::Drop { .. }))
        .unwrap();
    cleanup.remove(drop);
    assert!(verify_ssa(missing_ssa_cleanup).is_err());

    let mut wrong_event_edge = ssa;
    let function = wrong_event_edge
        .functions
        .iter_mut()
        .find(|function| {
            function.blocks.iter().any(|block| {
                block.instructions.iter().any(|instruction| {
                    matches!(&instruction.op, SsaOp::Class(op) if matches!(op.as_ref(), ClassOp::InterfaceCall { .. }))
                })
            })
        })
        .unwrap();
    let target = function
        .blocks
        .iter()
        .flat_map(|block| &block.instructions)
        .find_map(|instruction| instruction.unwind)
        .unwrap();
    function.blocks[target.0 as usize].landing_pad = None;
    assert!(verify_ssa(wrong_event_edge).is_err());
}

#[test]
fn smoke_fixture_qualifies() {
    qualify(
        include_str!("../../../tests/programs/exception_v3_smoke.ae"),
        0,
        [2, 2, 4, 2, 0, 2, 2],
    );
}
