//! OOP-V3 native dispatch, ownership, construction and rejection qualification.
use aether_driver::{Emit, compile_source};
use aether_frontend::{
    ClassId, ClassOp, FunctionId, SourceFile, VirtualSlotId, analyze, parse_source,
};
use aether_middle::{Rvalue, SsaOp, build_ssa, lower_hir, verify_mir, verify_ssa};
use std::{fmt::Write, fs, path::PathBuf, process::Command};
struct Directory(PathBuf);
impl Directory {
    fn new() -> Self {
        static NEXT: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
        let path = std::env::temp_dir().join(format!(
            "aether-oop-v3-{}-{}",
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
fn compile(text: &str) -> aether_driver::Compilation {
    compile_source(
        &SourceFile::new("oop.ae", text),
        &[Emit::Hir, Emit::Mir, Emit::Ssa],
    )
    .unwrap_or_else(|e| panic!("{text}\n{e:?}"))
}
fn native_status(llvm: &str, opt: &str) -> Option<i32> {
    let dir = Directory::new();
    let ir = dir.0.join("program.ll");
    let exe = dir.0.join("program");
    fs::write(&ir, llvm).unwrap();
    let output = Command::new("clang")
        .args(["-Wno-override-module", opt, "-x", "ir"])
        .arg(&ir)
        .arg("-o")
        .arg(&exe)
        .output()
        .unwrap();
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    let status = Command::new(exe).status().unwrap();
    status.code()
}
fn execute(llvm: &str, opt: &str) {
    assert_eq!(
        native_status(llvm, opt),
        Some(0),
        "native {opt} qualification failed"
    );
}
/// Assert actual counters after the source main has completed all cleanup.
fn instrument(llvm: &str, result: i64, counts: [u64; 7]) -> String {
    let names = [
        "object_alloc",
        "object_retain",
        "object_release",
        "object_destroy",
        "object_buffer_drop",
        "heap_alloc",
        "heap_free",
    ];
    let mut guard = format!("  %oop_result_ok = icmp eq i32 %process_status, {result}\n");
    let mut last = "oop_result_ok".to_owned();
    for (i, (name, expected)) in names.iter().zip(counts).enumerate() {
        writeln!(guard,"  %oop_{i} = load i64, ptr @aether_{name}_count\n  %oop_ok_{i} = icmp eq i64 %oop_{i}, {expected}\n  %oop_all_{i} = and i1 %{last}, %oop_ok_{i}").unwrap();
        last = format!("oop_all_{i}");
    }
    writeln!(
        guard,
        "  %oop_status = select i1 %{last}, i32 0, i32 99\n  ret i32 %oop_status"
    )
    .unwrap();
    llvm.replace("  ret i32 %process_status", &guard)
}

#[test]
#[allow(clippy::too_many_lines)]
fn native_inheritance_o0_o2() {
    let cases = [
        (
            "empty",
            include_str!("../../../tests/programs/oop_v3_empty.ae"),
            0,
        ),
        (
            "fields",
            include_str!("../../../tests/programs/oop_v3_fields.ae"),
            9,
        ),
        (
            "base_init",
            include_str!("../../../tests/programs/oop_v3_base_init.ae"),
            4,
        ),
        (
            "implicit_base",
            include_str!("../../../tests/programs/oop_v3_implicit_base.ae"),
            1,
        ),
        (
            "root",
            include_str!("../../../tests/programs/oop_v3_root.ae"),
            7,
        ),
        (
            "fresh",
            include_str!("../../../tests/programs/oop_v3_fresh.ae"),
            0,
        ),
        (
            "alias",
            include_str!("../../../tests/programs/oop_v3_alias.ae"),
            0,
        ),
        (
            "transitive",
            include_str!("../../../tests/programs/oop_v3_transitive.ae"),
            0,
        ),
        (
            "nonvirtual_derived",
            include_str!("../../../tests/programs/oop_v3_nonvirtual_derived.ae"),
            3,
        ),
        (
            "nonvirtual_base",
            include_str!("../../../tests/programs/oop_v3_nonvirtual_base.ae"),
            3,
        ),
        (
            "open_no_override",
            include_str!("../../../tests/programs/oop_v3_open_no_override.ae"),
            1,
        ),
        (
            "override_derived",
            include_str!("../../../tests/programs/oop_v3_override_derived.ae"),
            7,
        ),
        (
            "override_base",
            include_str!("../../../tests/programs/oop_v3_override_base.ae"),
            7,
        ),
        (
            "override_chain",
            include_str!("../../../tests/programs/oop_v3_override_chain.ae"),
            9,
        ),
        (
            "three_levels",
            include_str!("../../../tests/programs/oop_v3_three_levels.ae"),
            7,
        ),
        (
            "identity",
            include_str!("../../../tests/programs/oop_v3_identity.ae"),
            1,
        ),
        (
            "type_alias",
            include_str!("../../../tests/programs/oop_v3_type_alias.ae"),
            7,
        ),
        (
            "mut_virtual",
            include_str!("../../../tests/programs/oop_v3_mut_virtual.ae"),
            6,
        ),
        (
            "read_virtual",
            include_str!("../../../tests/programs/oop_v3_read_virtual.ae"),
            7,
        ),
        (
            "keepalive",
            include_str!("../../../tests/programs/oop_v3_keepalive.ae"),
            12,
        ),
        (
            "base_buffer",
            include_str!("../../../tests/programs/oop_v3_base_buffer.ae"),
            0,
        ),
        (
            "derived_buffer",
            include_str!("../../../tests/programs/oop_v3_derived_buffer.ae"),
            0,
        ),
        (
            "buffer_order",
            include_str!("../../../tests/programs/oop_v3_buffer_order.ae"),
            0,
        ),
        (
            "inherited_interface",
            include_str!("../../../tests/programs/oop_v3_inherited_interface.ae"),
            1,
        ),
        (
            "interface_override",
            include_str!("../../../tests/programs/oop_v3_interface_override.ae"),
            7,
        ),
        (
            "base_interface",
            include_str!("../../../tests/programs/oop_v3_base_interface.ae"),
            7,
        ),
        (
            "interface_drop",
            include_str!("../../../tests/programs/oop_v3_interface_drop.ae"),
            7,
        ),
        (
            "second_interface",
            include_str!("../../../tests/programs/oop_v3_second_interface.ae"),
            10,
        ),
        (
            "unknown",
            include_str!("../../../tests/programs/oop_v3_unknown.ae"),
            7,
        ),
        (
            "mixed",
            include_str!("../../../tests/programs/oop_v3_mixed.ae"),
            16,
        ),
    ];
    for (name, source, result) in cases {
        let compilation = compile(source);
        for opt in ["-O0", "-O2"] {
            let llvm = match name {
                "fresh" => instrument(&compilation.llvm, result, [1,0,1,1,0,1,1]),
                "alias" => instrument(&compilation.llvm, result, [1,1,2,1,0,1,1]),
                "buffer_order" => instrument(&compilation.llvm, result, [1,0,1,1,2,3,3]),
                "interface_drop" => instrument(&compilation.llvm, result, [1,1,2,1,2,3,3]),
                "base_interface" => instrument(&compilation.llvm, result, [1,2,3,1,0,1,1]),
                _ => compilation.llvm.replace("  ret i32 %process_status", &format!("  %ok = icmp eq i32 %process_status, {result}\n  %exit = select i1 %ok, i32 0, i32 99\n  ret i32 %exit")),
            };
            execute(&llvm, opt);
        }
    }
}

#[test]
fn base_method_calls_are_direct_nonowning_and_capability_checked() {
    use aether_driver::{OptimizationLevel, compile_source_with_optimization};
    let cases = [
        (
            "open class A{public int value(){return 5;}}class B:A{public int baseValue(){return base.value();}}int main(){B b=B();return b.baseValue();}",
            5,
            [1, 1, 2, 1, 0, 1, 1],
        ),
        (
            include_str!("../../../tests/programs/oop_polish_1_base.ae"),
            7,
            [1, 1, 2, 1, 0, 1, 1],
        ),
        (
            include_str!("../../../tests/programs/oop_polish_1_multilevel.ae"),
            3,
            [1, 2, 3, 1, 0, 1, 1],
        ),
        (
            include_str!("../../../tests/programs/oop_polish_1_mut.ae"),
            10,
            [1, 2, 3, 1, 0, 1, 1],
        ),
    ];
    for (source, result, counts) in cases {
        let compilation = compile(source);
        assert!(
            compilation
                .dumps
                .iter()
                .any(|(_, dump)| dump.contains("BaseMethodCall"))
        );
        assert!(!compilation.llvm.contains("base method indirect"));
        // Only the main-to-method call acquires a keepalive. The nested base
        // invocation borrows that method receiver and adds no retain/release.
        let llvm = instrument(&compilation.llvm, result, counts);
        for opt in ["-O0", "-O2"] {
            execute(&llvm, opt);
        }
        let optimized = compile_source_with_optimization(
            &SourceFile::new("base-method.ae", source),
            &[],
            OptimizationLevel::O2,
        )
        .unwrap();
        let llvm = optimized.llvm.replace(
            "  ret i32 %process_status",
            &format!("  %ok = icmp eq i32 %process_status, {result}\n  %exit = select i1 %ok, i32 0, i32 99\n  ret i32 %exit"),
        );
        execute(&llvm, "-O2");
    }
}

#[test]
fn source_rejections() {
    let cases = [
        "class A{} class B:A{}",
        "open class A{} open class B{} class C:A,B{}",
        "open class A:A{}",
        "open class A:B{} open class B:A{}",
        "open class A:B{} open class B:C{} open class C:A{}",
        "class A:Unknown{}",
        "open class A{public init(int n){}} class B:A{}",
        "open class A{public init(int n){}} class B:A{public init():base(true){}}",
        "open class A{} class B:A{public init():base():base(){}}",
        "open class A{} class B:A{public init():A(){}}",
        "class A{public init():base(){}}",
        "open class A{} class B:A{public int f(){base();return 0;}}",
        "open class A{} class B:A{public init(){B b=this;}}",
        "open class A{public open int f(){return 1;}} class B:A{public int f(){return 2;}}",
        "open class A{} class B:A{public override int f(){return 2;}}",
        "open class A{public int f(){return 1;}} class B:A{public override int f(){return 2;}}",
        "open class A{public open int f(int n){return n;}} class B:A{public override int f(bool n){return 2;}}",
        "open class A{public open int f(){return 1;}} class B:A{public override bool f(){return true;}}",
        "open class A{public open int f(){return 1;}} class B:A{public override mut int f(){return 2;}}",
        "open class A{public open int f(){return 1;}} class B:A{private override int f(){return 2;}}",
        "open class A{private open int f(){return 1;}}",
        "open class A{public open init(){}}",
        "open class A{public open int n;public init(){n=1;}}",
        "class A{public open int f(){return 1;}}",
        "open class A{public int n;public init(){n=1;}} class B:A{int n;public init(){n=2;}}",
        "open class A{public int f(){return 1;}} class B:A{public int f(){return 2;}}",
        "open class A{} class B extends A{}",
        "interface I{} class B implements I{}",
        "open class A{} class B:A{} int bad(){A a=B();B b=a;return 0;}",
        "class A{} int bad(){A a=A();return a is A;}",
        "class A{} int bad(){A a=A();A b=a as A;return 0;}",
        "open class A{protected int f(){return 1;}}",
        "abstract class A{}",
        "sealed class A{}",
        "final class A{}",
        "class A{A a;public init(){a=A();}}",
        "open class A{int n;public init(){n=1;}} class B:A{public int f(){return n;}}",
        "open class A<T>{} class B:A<int>{}",
        "open class A{private init(){}} class B:A{}",
        "interface I{} open class A:I{} class B:A,I{}",
        "open class A{public int n;public init(){n=1;}} class B:A{public override int n(){return 2;}}",
        "open class A{public init(int n){}} class B:A{int n;public init():base(n){n=2;}}",
        "open class A{public init(int n){}} class B:A{public init():base(this.f()){}public int f(){return 1;}}",
        "int f(){return base.value();}",
        "open class A{public int f(){return 1;}}class B:A{public init(){base.f();}}",
        "class A{public int f(){return base.f();}}",
        "open class A{private int f(){return 1;}}class B:A{public int g(){return base.f();}}",
        "open class A{public mut int f(){return 1;}}class B:A{public int g(){return base.f();}}",
        "open class A{}class B:A{public int g(){A a=base;return 0;}}",
        "open class A{}class B:A{public int g(){return base;}}",
        "open class A{}int use(A a){return 0;}class B:A{public int g(){return use(base);}}",
    ];
    for (index, source) in cases.iter().enumerate() {
        let source = format!("{source} int main(){{return 0;}}");
        assert!(
            compile_source(&SourceFile::new("negative.ae", &source), &[]).is_err(),
            "accepted case {index}: {source}"
        );
    }
}

#[test]
fn imported_base_identity_and_visibility() {
    use aether_driver::{CompilationSession, compile_session};
    let dir = Directory::new();
    let entry = dir.0.join("main.ae");
    let base = "public open class A{public init(){}public open int f(){return 1;}}";
    fs::write(dir.0.join("first.ae"), base).unwrap();
    fs::write(dir.0.join("second.ae"), base).unwrap();
    fs::write(&entry, "import first;class B:first.A{public override int f(){return 7;}}int main(){first.A a=B();return a.f();}").unwrap();
    let c = compile_session(CompilationSession::discover(&entry).unwrap(), &[]).unwrap();
    for opt in ["-O0", "-O2"] {
        execute(&instrument(&c.llvm, 7, [1, 1, 2, 1, 0, 1, 1]), opt);
    }
    for source in [
        "import first;import second;class B:first.A{}int main(){second.A a=B();}",
        "import first;class B:first.A,first.A{}int main(){}",
    ] {
        fs::write(&entry, source).unwrap();
        assert!(compile_session(CompilationSession::discover(&entry).unwrap(), &[]).is_err());
    }
    fs::write(
        dir.0.join("first.ae"),
        base.replace("public open class", "open class"),
    )
    .unwrap();
    fs::write(&entry, "import first;class B:first.A{}int main(){}").unwrap();
    assert!(compile_session(CompilationSession::discover(&entry).unwrap(), &[]).is_err());
}

fn mir(source: &str) -> aether_middle::FlowMir {
    lower_hir(analyze(parse_source(&SourceFile::new("v3.ae", source)).unwrap()).unwrap())
}
#[test]
fn receiver_keepalive_survives_rebound_owner_in_mir_native_fixture() {
    let source = "open class A{public int value;public init(int n){value=n;}public open int with_arg(int n){return value+n;}}class B:A{public init(int n):base(n){}public override int with_arg(int n){return value+n;}}int effect(){return 3;}int main(){A a=B(2);int n=a.with_arg(effect());a=B(9);return n;}";
    let mut fixture = mir(source);
    let instructions = &mut fixture.functions[fixture.entry.0 as usize].blocks[0].instructions;
    let second_allocation=instructions.iter().enumerate().filter(|(_,i)|matches!(&i.value,Rvalue::Class(op) if matches!(op.as_ref(),ClassOp::ObjectAlloc{..}))).nth(1).unwrap().0;
    let end = second_allocation
        + instructions[second_allocation..]
            .iter()
            .position(|i| matches!(i.value, Rvalue::Drop { .. }))
            .unwrap()
        + 1;
    let replacement = instructions
        .drain(second_allocation..end)
        .collect::<Vec<_>>();
    let keepalive=instructions.iter().position(|i|matches!(&i.value,Rvalue::Class(op) if matches!(op.as_ref(),ClassOp::ReceiverKeepalive{..}))).unwrap();
    let insertion = keepalive + 1;
    instructions.splice(insertion..insertion, replacement);
    let valid = verify_mir(fixture).unwrap();
    let ssa = verify_ssa(build_ssa(&valid)).unwrap();
    let llvm = aether_backend_llvm::emit_llvm(
        &ssa,
        &aether_backend_llvm::TargetDescriptor::linux_x86_64(),
    );
    for opt in ["-O0", "-O2"] {
        execute(&instrument(&llvm, 5, [2, 1, 3, 2, 0, 2, 2]), opt);
    }
    let optimized = aether_middle::optimize_oop(&ssa).unwrap();
    assert!(
        optimized.as_ssa().functions[optimized.as_ssa().entry.0 as usize]
            .oop_optimizations
            .arc
            .is_empty()
    );
    let llvm = aether_backend_llvm::emit_llvm(
        &optimized,
        &aether_backend_llvm::TargetDescriptor::linux_x86_64(),
    );
    for opt in ["-O0", "-O2"] {
        execute(&instrument(&llvm, 5, [2, 1, 3, 2, 0, 2, 2]), opt);
    }
}

fn corrupt_op<O: Clone, F: Clone>(op: &mut ClassOp<O, F>, mutation: u32) -> bool {
    match (mutation, op) {
        (0, ClassOp::ObjectAlloc { class })
        | (6, ClassOp::VirtualCall { class, .. })
        | (8, ClassOp::BaseInit { class, .. }) => *class = ClassId(999),
        (1, ClassOp::BaseInit { base, .. }) => *base = ClassId(999),
        (2, ClassOp::ClassUpcast { path, .. }) => path.reverse(),
        (3, ClassOp::ClassUpcast { transfer, .. }) => *transfer = !*transfer,
        (4, ClassOp::VirtualCall { slot, .. }) => *slot = VirtualSlotId(FunctionId(999)),
        (5, op @ ClassOp::VirtualCall { .. }) => {
            let ClassOp::VirtualCall {
                method,
                receiver,
                args,
                ..
            } = op.clone()
            else {
                unreachable!()
            };
            *op = ClassOp::DirectMethodCall {
                method,
                receiver,
                args,
            };
        }
        (7, ClassOp::InterfaceAdapt { witness, .. }) => witness.0 = 999,
        _ => return false,
    }
    true
}
const CORRUPTION_SOURCE: &str = "interface I{int f();}open class A:I{Buffer<int> a;public init(Buffer<int> a){this.a=a;}public open int f(){return 1;}}class B:A{Buffer<int> b;public init(Buffer<int> a,Buffer<int> b):base(a){this.b=b;}public override int f(){return 7;}}int main(){B b=B(Buffer<int>(2,1),Buffer<int>(2,2));A a=b;I i=a;return a.f()+i.f();}";
#[test]
fn independent_mir_ssa_operation_corruptions() {
    let valid = mir(CORRUPTION_SOURCE);
    let ssa = build_ssa(&verify_mir(valid.clone()).unwrap());
    for mutation in 0..9 {
        let mut bad = valid.clone();
        assert!(
            bad.functions
                .iter_mut()
                .flat_map(|f| &mut f.blocks)
                .flat_map(|b| &mut b.instructions)
                .any(|i| if let Rvalue::Class(op) = &mut i.value {
                    corrupt_op(op, mutation)
                } else {
                    false
                })
        );
        assert!(verify_mir(bad).is_err(), "MIR mutation {mutation}");
        let mut bad = ssa.clone();
        assert!(
            bad.functions
                .iter_mut()
                .flat_map(|f| &mut f.blocks)
                .flat_map(|b| &mut b.instructions)
                .any(|i| if let SsaOp::Class(op) = &mut i.op {
                    corrupt_op(op, mutation)
                } else {
                    false
                })
        );
        assert!(verify_ssa(bad).is_err(), "SSA mutation {mutation}");
    }
    for duplicate in [false, true] {
        let mut bad = valid.clone();
        let block = bad.functions.iter_mut().flat_map(|f| &mut f.blocks).find(|b| b.instructions.iter().any(|i| matches!(&i.value, Rvalue::Class(op) if matches!(op.as_ref(), ClassOp::BaseInit { .. })))).unwrap();
        let index = block.instructions.iter().position(|i| matches!(&i.value, Rvalue::Class(op) if matches!(op.as_ref(), ClassOp::BaseInit { .. }))).unwrap();
        if duplicate {
            block
                .instructions
                .insert(index, block.instructions[index].clone());
        } else {
            block.instructions.remove(index);
        }
        assert!(verify_mir(bad).is_err());
        let mut bad = ssa.clone();
        let block = bad.functions.iter_mut().flat_map(|f| &mut f.blocks).find(|b| b.instructions.iter().any(|i| matches!(&i.op, SsaOp::Class(op) if matches!(op.as_ref(), ClassOp::BaseInit { .. })))).unwrap();
        let index = block.instructions.iter().position(|i| matches!(&i.op, SsaOp::Class(op) if matches!(op.as_ref(), ClassOp::BaseInit { .. }))).unwrap();
        if duplicate {
            block
                .instructions
                .insert(index, block.instructions[index].clone());
        } else {
            block.instructions.remove(index);
        }
        assert!(verify_ssa(bad).is_err());
    }
}

#[test]
fn base_method_target_is_independently_verified_in_mir_and_ssa() {
    let source = include_str!("../../../tests/programs/oop_polish_1_base.ae");
    let valid = mir(source);
    let ssa = build_ssa(&verify_mir(valid.clone()).unwrap());
    for mutation in 0..2 {
        let mut bad = valid.clone();
        assert!(
            bad.functions
                .iter_mut()
                .flat_map(|f| &mut f.blocks)
                .flat_map(|b| &mut b.instructions)
                .any(|i| {
                    let Rvalue::Class(op) = &mut i.value else {
                        return false;
                    };
                    let ClassOp::BaseMethodCall { base, method, .. } = op.as_mut() else {
                        return false;
                    };
                    if mutation == 0 {
                        *base = ClassId(999);
                    } else {
                        *method = aether_frontend::InstanceId(999);
                    }
                    true
                })
        );
        assert!(verify_mir(bad).is_err(), "MIR base mutation {mutation}");

        let mut bad = ssa.clone();
        assert!(
            bad.functions
                .iter_mut()
                .flat_map(|f| &mut f.blocks)
                .flat_map(|b| &mut b.instructions)
                .any(|i| {
                    let SsaOp::Class(op) = &mut i.op else {
                        return false;
                    };
                    let ClassOp::BaseMethodCall { base, method, .. } = op.as_mut() else {
                        return false;
                    };
                    if mutation == 0 {
                        *base = ClassId(999);
                    } else {
                        *method = aether_frontend::InstanceId(999);
                    }
                    true
                })
        );
        assert!(verify_ssa(bad).is_err(), "SSA base mutation {mutation}");
    }
}
#[test]
fn independent_inheritance_metadata_corruptions() {
    let valid = mir(CORRUPTION_SOURCE);
    let ssa = build_ssa(&verify_mir(valid.clone()).unwrap());
    for mutation in 0..10 {
        let mut definition = valid.types.classes()[1].clone();
        match mutation {
            0 => definition.base = Some(ClassId(1)),
            1 => definition.base = None,
            2 => definition.interfaces.clear(),
            3 => definition.methods[1].virtual_slot = Some(VirtualSlotId(FunctionId(999))),
            4 => definition.methods[1].override_target = None,
            5 => definition.methods[1].overriding = false,
            6 => definition.destruction = valid.types.classes()[0].destruction.clone(),
            7 => definition.destruction.reverse(),
            8 => definition.fields[0].offset = 8,
            9 => {
                definition = valid.types.classes()[0].clone();
                definition.open = false;
            }
            _ => unreachable!(),
        }
        let mut bad = valid.clone();
        std::sync::Arc::make_mut(&mut bad.types).register_class_definition(definition.clone());
        assert!(verify_mir(bad).is_err(), "MIR metadata {mutation}");
        let mut bad = ssa.clone();
        std::sync::Arc::make_mut(&mut bad.types).register_class_definition(definition);
        assert!(verify_ssa(bad).is_err(), "SSA metadata {mutation}");
    }
}

#[test]
fn derived_fields_drop_before_base_with_one_free_per_allocation() {
    let mut llvm = compile(include_str!(
        "../../../tests/programs/oop_v3_buffer_order.ae"
    ))
    .llvm;
    llvm.push_str("\n@v3_drop_trace = internal global i64 0\n");
    for field in 0..2 {
        let anchor = format!("  %field{field} = getelementptr");
        let probe = format!(
            "  %trace_old{field} = load i64, ptr @v3_drop_trace\n  %trace_shift{field} = mul i64 %trace_old{field}, 10\n  %trace_next{field} = add i64 %trace_shift{field}, {}\n  store i64 %trace_next{field}, ptr @v3_drop_trace\n{anchor}",
            field + 1
        );
        assert!(llvm.contains(&anchor));
        llvm = llvm.replace(&anchor, &probe);
    }
    llvm = instrument(&llvm, 0, [1, 0, 1, 1, 2, 3, 3]);
    llvm = llvm.replace("  ret i32 %oop_status", "  %trace = load i64, ptr @v3_drop_trace\n  %ordered = icmp eq i64 %trace, 21\n  %ordered_status = select i1 %ordered, i32 %oop_status, i32 98\n  ret i32 %ordered_status");
    for opt in ["-O0", "-O2"] {
        execute(&llvm, opt);
    }
}

#[test]
fn optimized_dynamic_provenance_and_dispatch() {
    use aether_driver::{OptimizationLevel, compile_source_with_optimization};
    let cases = [
        (
            include_str!("../../../tests/programs/oop_v3_base_interface.ae"),
            7,
            true,
        ),
        (
            include_str!("../../../tests/programs/oop_v3_mixed.ae"),
            16,
            false,
        ),
        (
            "interface I{int f();}open class A:I{public open int f(){return 1;}}class B:A{public override int f(){return 7;}}int call(A a){I i=a;return i.f();}int main(){return call(B());}",
            7,
            false,
        ),
        (
            "interface I{int f();}open class A:I{public open int f(){return 1;}}class B:A{public override int f(){return 7;}}class C:A{public override int f(){return 9;}}int call(bool b){A a=B();if(b){a=C();}I i=a;return i.f();}int main(){return call(true)+call(false);}",
            16,
            false,
        ),
        (
            "open class A{public open Buffer<int> f(Buffer<int> b){return b;}}class B:A{public override Buffer<int> f(Buffer<int> b){return b;}}int main(){A a=B();Buffer<int> b=a.f(Buffer<int>(2,7));return b[0];}",
            7,
            false,
        ),
    ];
    for (source, result, direct) in cases {
        let c = compile_source_with_optimization(
            &SourceFile::new("optimized.ae", source),
            &[],
            OptimizationLevel::O2,
        )
        .unwrap();
        assert_eq!(c.llvm.contains("; OOP-OPT-1 devirtualization:"), direct);
        let llvm = c.llvm.replace("  ret i32 %process_status", &format!("  %ok = icmp eq i32 %process_status, {result}\n  %exit = select i1 %ok, i32 0, i32 99\n  ret i32 %exit"));
        for opt in ["-O0", "-O2"] {
            execute(&llvm, opt);
        }
    }
}

#[test]
fn exact_class_virtual_calls_devirtualize_but_unknown_and_mixed_stay_indirect() {
    use aether_driver::{OptimizationLevel, compile_source_with_optimization};
    let exact = "open class A{public open int f(){return 1;}}class B:A{public override int f(){return 7;}}int main(){A a=B();return a.f();}";
    let same_phi = "open class A{public open int f(){return 1;}}class B:A{public override int f(){return 7;}}int call(bool b){A a=B();if(b){a=B();}return a.f();}int main(){return call(true);}";
    let unknown = "open class A{public open int f(){return 1;}}class B:A{public override int f(){return 7;}}int call(A a){return a.f();}int main(){return call(B());}";
    let mixed = "open class A{public open int f(){return 1;}}class B:A{public override int f(){return 7;}}class C:A{public override int f(){return 9;}}int call(bool b){A a=B();if(b){a=C();}return a.f();}int main(){return call(false);}";
    for (source, result, direct) in [
        (exact, 7, true),
        (same_phi, 7, true),
        (unknown, 7, false),
        (mixed, 7, false),
    ] {
        let o0 = compile_source_with_optimization(
            &SourceFile::new("class-devirt.ae", source),
            &[],
            OptimizationLevel::O0,
        )
        .unwrap();
        assert!(!o0.llvm.contains("OOP-POLISH-1 class devirtualization"));
        let o2 = compile_source_with_optimization(
            &SourceFile::new("class-devirt.ae", source),
            &[],
            OptimizationLevel::O2,
        )
        .unwrap();
        assert_eq!(
            o2.llvm.contains("OOP-POLISH-1 class devirtualization"),
            direct
        );
        let llvm = o2.llvm.replace(
            "  ret i32 %process_status",
            &format!("  %ok = icmp eq i32 %process_status, {result}\n  %exit = select i1 %ok, i32 0, i32 99\n  ret i32 %exit"),
        );
        for opt in ["-O0", "-O2"] {
            execute(&llvm, opt);
        }
    }
}

#[test]
fn class_devirtualization_rejects_wrong_override_slot_and_stale_provenance() {
    let dog = "open class A{public open int f(){return 1;}}class B:A{public override int f(){return 7;}}class C:A{public override int f(){return 9;}}int main(){A a=B();return a.f();}";
    let cat = dog.replace("A a=B()", "A a=C()");
    let dog_ssa = verify_ssa(build_ssa(&verify_mir(mir(dog)).unwrap())).unwrap();
    let optimized = aether_middle::optimize_oop(&dog_ssa).unwrap();
    let base_method = optimized
        .as_ssa()
        .signatures
        .iter()
        .find(|s| {
            optimized
                .as_ssa()
                .types
                .class_method(s.function_id)
                .is_some_and(|(class, method)| class == ClassId(0) && method.name == "f")
        })
        .unwrap()
        .id;

    let mut wrong_override = optimized.as_ssa().clone();
    assert!(wrong_override.functions.iter_mut().any(|function| {
        function
            .oop_optimizations
            .virtual_direct
            .values_mut()
            .next()
            .is_some_and(|decision| {
                decision.method = base_method;
                true
            })
    }));
    assert!(verify_ssa(wrong_override).is_err());

    let mut wrong_slot = optimized.as_ssa().clone();
    assert!(wrong_slot.functions.iter_mut().any(|function| {
        function
            .oop_optimizations
            .virtual_direct
            .values_mut()
            .next()
            .is_some_and(|decision| {
                decision.slot = VirtualSlotId(FunctionId(999));
                true
            })
    }));
    assert!(verify_ssa(wrong_slot).is_err());

    let cat_ssa = build_ssa(&verify_mir(mir(&cat)).unwrap());
    let mut stale = cat_ssa;
    for (target, old) in stale
        .functions
        .iter_mut()
        .zip(&optimized.as_ssa().functions)
    {
        target.oop_optimizations = old.oop_optimizations.clone();
    }
    assert!(verify_ssa(stale).is_err());
}

#[test]
fn corrupt_dynamic_destruction_and_witnesses_fail_native_qualification() {
    let llvm = instrument(&compile(CORRUPTION_SOURCE).llvm, 14, [1, 4, 5, 1, 2, 3, 3]);
    let base_witness = llvm
        .lines()
        .find(|l| l.starts_with("@aether_witness_0 ="))
        .unwrap();
    let derived_witness = llvm
        .lines()
        .find(|l| l.starts_with("@aether_witness_1 ="))
        .unwrap();
    let mut static_adaptation = llvm.clone();
    for line in llvm
        .lines()
        .filter(|l| l.trim_start().starts_with("%dynamic_witness"))
    {
        let lhs = line.split(" = ").next().unwrap();
        static_adaptation = static_adaptation.replace(
            line,
            &format!("{lhs} = getelementptr ptr, ptr @aether_witness_0, i64 0"),
        );
    }
    let corruptions = [
        llvm.replace(
            "ptr @aether_object_destroy_1",
            "ptr @aether_object_destroy_0",
        ),
        llvm.replace("ptr @aether_witness_1", "ptr @aether_witness_0"),
        llvm.replace(
            derived_witness,
            &base_witness.replacen("@aether_witness_0", "@aether_witness_1", 1),
        ),
        static_adaptation,
        llvm.replace(
            "call void %release(ptr %object)",
            "call void @aether_object_destroy_0(ptr %object)",
        ),
    ];
    for opt in ["-O0", "-O2"] {
        execute(&llvm, opt);
        for corrupted in &corruptions {
            assert_ne!(corrupted, &llvm);
            assert_ne!(native_status(corrupted, opt), Some(0));
        }
    }
}

#[test]
fn stale_or_base_only_devirtualization_rejects() {
    use aether_middle::{Devirtualization, optimize_oop};
    let valid = verify_ssa(build_ssa(&verify_mir(mir(CORRUPTION_SOURCE)).unwrap())).unwrap();
    let optimized = optimize_oop(&valid).unwrap();
    let mut bad = optimized.as_ssa().clone();
    let base_method = bad
        .signatures
        .iter()
        .find(|s| {
            bad.types
                .class_method(s.function_id)
                .is_some_and(|(c, m)| c == ClassId(0) && !m.initializing)
        })
        .unwrap()
        .id;
    let mut changed = false;
    for function in &mut bad.functions {
        for decision in function.oop_optimizations.direct.values_mut() {
            decision.method = base_method;
            changed = true;
        }
    }
    assert!(changed);
    assert!(verify_ssa(bad).is_err());
    for source in [
        "interface I{int f();}open class A:I{public open int f(){return 1;}}class B:A{public override int f(){return 7;}}int call(A a){I i=a;return i.f();}int main(){return call(B());}",
        "interface I{int f();}open class A:I{public open int f(){return 1;}}class B:A{public override int f(){return 7;}}class C:A{public override int f(){return 9;}}int call(bool b){A a=B();if(b){a=C();}I i=a;return i.f();}int main(){return call(true);}",
    ] {
        let mut bad = build_ssa(&verify_mir(mir(source)).unwrap());
        let method = bad
            .signatures
            .iter()
            .find(|s| {
                bad.types
                    .class_method(s.function_id)
                    .is_some_and(|(c, m)| c == ClassId(1) && !m.initializing)
            })
            .unwrap()
            .id;
        for function in &mut bad.functions {
            for i in function.blocks.iter().flat_map(|b| &b.instructions) {
                if let SsaOp::Class(op) = &i.op
                    && let ClassOp::InterfaceCall { requirement, .. } = op.as_ref()
                {
                    function.oop_optimizations.direct.insert(
                        i.result,
                        Devirtualization {
                            requirement: *requirement,
                            class: ClassId(1),
                            method,
                        },
                    );
                }
            }
        }
        assert!(verify_ssa(bad).is_err());
    }
}

#[test]
fn upcast_phi_cannot_duplicate_ownership() {
    let source = "open class A{}class B:A{}class C:A{}int main(){A a=B();A b=C();if(true){a=b;}else{b=a;}return 0;}";
    let mut bad = build_ssa(&verify_mir(mir(source)).unwrap());
    let block = bad.functions[bad.entry.0 as usize]
        .blocks
        .iter_mut()
        .find(|b| {
            b.phis
                .iter()
                .filter(|p| bad.types.class_id(p.ty).is_some())
                .count()
                >= 2
        })
        .unwrap();
    let mut phis = block
        .phis
        .iter_mut()
        .filter(|p| bad.types.class_id(p.ty).is_some());
    let first = phis.next().unwrap().incoming.clone();
    phis.next().unwrap().incoming = first;
    assert!(verify_ssa(bad).is_err());
}

#[test]
fn empty_base_initialization_and_final_release_are_required() {
    let source = "open class A{}class B:A{}int main(){A a=B();}";
    let valid = mir(source);
    let ssa = build_ssa(&verify_mir(valid.clone()).unwrap());
    let mut bad = valid;
    for block in bad.functions.iter_mut().flat_map(|f| &mut f.blocks) {
        block.instructions.retain(|i| !matches!(&i.value, Rvalue::Class(op) if matches!(op.as_ref(), ClassOp::BaseInit { .. })));
    }
    assert!(verify_mir(bad).is_err());
    let mut bad = ssa.clone();
    for block in bad.functions.iter_mut().flat_map(|f| &mut f.blocks) {
        block.instructions.retain(|i| !matches!(&i.op, SsaOp::Class(op) if matches!(op.as_ref(), ClassOp::BaseInit { .. })));
    }
    assert!(verify_ssa(bad).is_err());
    let mut bad = ssa;
    for block in &mut bad.functions[bad.entry.0 as usize].blocks {
        block
            .instructions
            .retain(|i| !matches!(i.op, SsaOp::Drop { .. }));
    }
    assert!(verify_ssa(bad).is_err());
}
