//! OOP-V2 independent native lifecycle and witness qualification.
use aether_driver::{Emit, compile_source};
use aether_frontend::{
    ClassId, ClassOp, InterfaceId, RequirementId, SourceFile, TypeData, TypeId, WitnessId, analyze,
    parse_source,
};
use aether_middle::{
    Operand, Rvalue, SsaOp, SsaOperand, build_ssa, lower_hir, verify_mir, verify_ssa,
};
use std::{fmt::Write, fs, path::PathBuf, process::Command};
const COUNTER: &str = "interface I { int get(); mut int inc(); } interface J { int get(); } class C : I, J { int n; public init(int n){this.n=n;} public int get(){return n;} public mut int inc(){n=n+1;return n;} }";
const OWNER: &str = "interface I { int get(); } class C : I { Buffer<int> b; public init(Buffer<int> b){this.b=b;} public int get(){return 7;} }";
struct Directory(PathBuf);
impl Directory {
    fn new() -> Self {
        static NEXT: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
        let path = std::env::temp_dir().join(format!(
            "aether-oop-v2-{}-{}",
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
fn mir(text: &str) -> aether_middle::FlowMir {
    lower_hir(analyze(parse_source(&SourceFile::new("oop.ae", text)).unwrap()).unwrap())
}
fn execute(llvm: &str, opt: &str) {
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
    assert_eq!(
        status.code(),
        Some(0),
        "native {opt} execution failed: {status}"
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
fn native_adaptation_dispatch_ownership_o0_o2() {
    let cases = [
        ("lvalue",format!("{COUNTER} int main(){{C c=C(0);I i=c;}}"),0,[1,1,2,1,0,1,1]),
        ("fresh",format!("{COUNTER} int main(){{I i=C(0);}}"),0,[1,0,1,1,0,1,1]),
        ("alias",format!("{COUNTER} int main(){{I i=C(0);I j=i;}}"),0,[1,1,2,1,0,1,1]),
        ("shared",format!("{COUNTER} int main(){{C c=C(0);I i=c;i.inc();return c.get();}}"),1,[1,3,4,1,0,1,1]),
        ("multiple",format!("{COUNTER} int main(){{C c=C(0);I i=c;J j=c;i.inc();return j.get()+c.get();}}"),2,[1,5,6,1,0,1,1]),
        ("read",format!("{COUNTER} int main(){{I i=C(4);return i.get();}}"),4,[1,1,2,1,0,1,1]),
        ("mut",format!("{COUNTER} int main(){{I i=C(4);return i.inc();}}"),5,[1,1,2,1,0,1,1]),
        ("empty","interface I{} class C:I{} int main(){I i=C();}".into(),0,[1,0,1,1,0,1,1]),
        ("return_fresh",format!("{COUNTER} I make(){{return C(3);}} int main(){{I i=make();return i.get();}}"),3,[1,1,2,1,0,1,1]),
        ("return_local",format!("{COUNTER} I make(){{I i=C(3);return i;}} int main(){{I i=make();return i.get();}}"),3,[1,2,3,1,0,1,1]),
        ("return_class",format!("{COUNTER} I make(){{C c=C(3);return c;}} int main(){{I i=make();return i.get();}}"),3,[1,2,3,1,0,1,1]),
        ("parameter",format!("{COUNTER} int use(I i){{return i.inc();}} int main(){{I i=C(0);int n=use(i);return i.get();}}"),1,[1,3,4,1,0,1,1]),
        ("class_parameter",format!("{COUNTER} int use(I i){{return i.inc();}} int main(){{C c=C(0);int n=use(c);return c.get();}}"),1,[1,3,4,1,0,1,1]),
        ("fresh_parameter",format!("{COUNTER} int use(I i){{return i.inc();}} int main(){{return use(C(0));}}"),1,[1,1,2,1,0,1,1]),
        ("fresh_interface_parameter",format!("{COUNTER} I make(){{return C(0);}} int use(I i){{return i.inc();}} int main(){{return use(make());}}"),1,[1,1,2,1,0,1,1]),
        ("temporary_read",format!("{COUNTER} I make(){{return C(3);}} int main(){{return make().get();}}"),3,[1,0,1,1,0,1,1]),
        ("buffer_final",format!("{OWNER} int main(){{I i=C(Buffer<int>(4,1));return i.get();}}"),7,[1,1,2,1,1,2,2]),
        ("buffer_local_return",format!("{OWNER} I make(){{C c=C(Buffer<int>(4,1));I i=c;return i;}} int main(){{I i=make();return i.get();}}"),7,[1,3,4,1,1,2,2]),
        ("conditional",format!("{COUNTER} int f(bool b){{I i=C(2);if(b){{I j=i;return j.get();}}return i.get();}} int main(){{return f(true)+f(false);}}"),4,[2,3,5,2,0,2,2]),
        ("replace",format!("{COUNTER} int main(){{I i=C(2);I j=i;i=C(5);return j.get()+i.get();}}"),7,[2,3,5,2,0,2,2]),
        ("self",format!("{COUNTER} int main(){{I i=C(2);i=i;return i.get();}}"),2,[1,1,2,1,0,1,1]),
        ("loop",format!("{COUNTER} int main(){{I i=C(0);int n=0;while(n<3){{I j=i;j.inc();n=n+1;}}return i.get();}}"),3,[1,7,8,1,0,1,1]),
        ("alias_type", "interface I{int get();} alias A=I; class C:A{public int get(){return 8;}} int main(){A a=C();return a.get();}".into(),8,[1,1,2,1,0,1,1]),
    ];
    for (name, source, result, counts) in cases {
        eprintln!("OOP-V2 {name}: {counts:?}; wrapper allocations=0");
        let c = compile(&source);
        for opt in ["-O0", "-O2"] {
            execute(&instrument(&c.llvm, result, counts), opt);
        }
    }
}

#[test]
#[allow(clippy::too_many_lines)]
fn source_rejections() {
    let cases = [
        (
            "structural",
            "interface I{int get();} class C{public int get(){return 1;}} int main(){I i=C();}",
        ),
        (
            "missing",
            "interface I{int get();} class C:I{} int main(){}",
        ),
        (
            "private",
            "interface I{int get();} class C:I{int get(){return 1;}} int main(){}",
        ),
        (
            "parameter",
            "interface I{int get(int x);} class C:I{public int get(bool x){return 1;}} int main(){}",
        ),
        (
            "result",
            "interface I{int get();} class C:I{public bool get(){return true;}} int main(){}",
        ),
        (
            "arity",
            "interface I{int get(int x);} class C:I{public int get(){return 1;}} int main(){}",
        ),
        (
            "mode",
            "interface I{int get(ref int x);} class C:I{public int get(ref mut int x){return 1;}} int main(){}",
        ),
        (
            "read_mut",
            "interface I{int get();} class C:I{public mut int get(){return 1;}} int main(){}",
        ),
        (
            "mut_read",
            "interface I{mut int get();} class C:I{public int get(){return 1;}} int main(){}",
        ),
        ("duplicate", "interface I{} class C:I,I{} int main(){}"),
        (
            "alias_duplicate",
            "interface I{} alias A=I; class C:I,A{} int main(){}",
        ),
        ("class_base", "class B{} class C:B{} int main(){}"),
        (
            "interface_base",
            "interface I{} interface J:I{} int main(){}",
        ),
        ("body", "interface I{int get(){return 1;}} int main(){}"),
        ("field", "interface I{int n;} int main(){}"),
        ("init", "interface I{init();} int main(){}"),
        ("generic", "interface I<T>{} int main(){}"),
        ("generic_method", "interface I{int get<T>();} int main(){}"),
        ("struct", "interface I{} struct S:I{} int main(){}"),
        (
            "unrelated",
            "interface I{} class C:I{} class D{} int main(){I i=D();}",
        ),
        (
            "nominal",
            "interface I{} interface J{} class C:I{} int main(){I i=C();J j=i;}",
        ),
        ("aggregate", "interface I{} struct S{I i;} int main(){}"),
        (
            "container",
            "interface I{} class C:I{} int main(){Array<I> a={C()};}",
        ),
        (
            "class_field",
            "interface I{} class C{I i;public init(I i){this.i=i;}} int main(){}",
        ),
        ("enum", "interface I{} enum E{V(I)} int main(){}"),
        (
            "equal",
            "interface I{} class C:I{} int main(){I i=C();bool b=i==i;}",
        ),
        (
            "not_equal",
            "interface I{} class C:I{} int main(){I i=C();bool b=i!=i;}",
        ),
        ("null", "interface I{} int main(){I i=null;}"),
        (
            "reference",
            "interface I{} class C:I{} int main(){I i=C();ref I r=&i;}",
        ),
        (
            "view",
            "interface I{} class C:I{} int main(){I i=C();View<int> v=view(i);}",
        ),
        (
            "implements",
            "interface I{} class C implements I{} int main(){}",
        ),
        ("extends", "class B{} class C extends B{} int main(){}"),
        (
            "override",
            "interface I{int get();} class C:I{public override int get(){return 1;}} int main(){}",
        ),
        (
            "private_requirement",
            "interface I{private int get();} int main(){}",
        ),
        ("static", "interface I{static int get();} int main(){}"),
        (
            "duplicate_requirement",
            "interface I{int get();int get();} int main(){}",
        ),
        (
            "conflict",
            "interface I{int get();} interface J{bool get();} class C:I,J{public int get(){return 1;}} int main(){}",
        ),
        (
            "copy",
            "interface I{} class C:I{} int f<T:Copy>(T x){return 0;} int main(){I i=C();return f(i);}",
        ),
        (
            "temporary_mut",
            "interface I{mut int inc();} class C:I{public mut int inc(){return 1;}} I make(){return C();} int main(){return make().inc();}",
        ),
    ];
    for (name, source) in cases {
        let errors = compile_source(&SourceFile::new("bad.ae", source), &[]).unwrap_err();
        assert!(
            errors.iter().all(|d| d.span.is_some()),
            "{name}: {errors:?}"
        );
    }
}

#[test]
fn typed_carriers_and_codegen() {
    let source = format!("{COUNTER} int main(){{C c=C(0);I i=c;I j=i;j.inc();return c.get();}}");
    let h = analyze(parse_source(&SourceFile::new("oop.ae", &source)).unwrap()).unwrap();
    let t = h
        .types()
        .id_of(TypeData::Interface(InterfaceId(0)))
        .unwrap();
    assert!(!h.types().is_copy(t));
    assert!(h.types().is_relocatable(t));
    assert!(h.types().needs_drop(t));
    assert!(!h.types().is_admitted_list_element(t));
    let c = compile(&source);
    for phase in [Emit::Hir, Emit::Mir, Emit::Ssa] {
        for op in [
            "InterfaceAdapt",
            "InterfaceCall",
            "ReceiverKeepalive",
            "HandleAlias",
            "DirectMethodCall",
        ] {
            assert!(c.dumps[&phase].contains(op), "{phase:?} {op}");
        }
    }
    assert!(c.llvm.contains("internal constant [3 x ptr]"));
    assert!(c.llvm.contains("call i64 %target"));
    assert!(c.llvm.contains("%release = load ptr, ptr %witness"));
    assert!(!c.llvm.contains("atomic"));
    assert!(!c.llvm.contains("noalias"));
    let direct = compile(&format!("{COUNTER} int main(){{C c=C(0);return c.get();}}"));
    assert!(!direct.llvm.contains("@aether_witness_"));
    assert!(!direct.llvm.contains("call i64 %target"));
    assert!(!direct.llvm.contains("%witness"));
    assert!(!direct.llvm.contains("aether_drop_iface"));
    let unused = compile("interface I{} int unused(I i){I j=i;return 1;}int main(){}");
    assert!(!unused.llvm.contains("aether_object_retain"));
    for opt in ["-O0", "-O2"] {
        execute(&unused.llvm, opt);
    }
    // An uninhabited recursive return still needs well-formed cleanup code.
    let recursive = compile("interface I{} I make(){return make();} int main(){I i=make();}");
    assert!(
        recursive
            .llvm
            .contains("define internal void @aether_drop_iface")
    );
}

#[test]
#[allow(clippy::too_many_lines)]
fn mir_interface_corruptions_fail_independently() {
    let valid = mir(&format!(
        "{COUNTER} int main(){{C c=C(0);I i=c;I j=i;return j.inc();}}"
    ));
    verify_mir(valid.clone()).unwrap();
    for mutation in 0..14 {
        let mut bad = valid.clone();
        let instructions = &mut bad.functions[bad.entry.0 as usize].blocks[0].instructions;
        match mutation {
            0..=4 => {
                let i=instructions.iter_mut().find(|i|matches!(&i.value,Rvalue::Class(op) if matches!(op.as_ref(),ClassOp::InterfaceAdapt{..}))).unwrap();
                let Rvalue::Class(op) = &mut i.value else {
                    unreachable!()
                };
                let ClassOp::InterfaceAdapt {
                    class,
                    interface,
                    witness,
                    source,
                    transfer,
                } = op.as_mut()
                else {
                    unreachable!()
                };
                match mutation {
                    0 => *class = ClassId(999),
                    1 => *interface = InterfaceId(1),
                    2 => *witness = WitnessId(1),
                    3 => *transfer = true,
                    4 => *source = Operand::Bool(true),
                    _ => unreachable!(),
                }
            }
            5..=8 => {
                let i=instructions.iter_mut().find(|i|matches!(&i.value,Rvalue::Class(op) if matches!(op.as_ref(),ClassOp::InterfaceCall{..}))).unwrap();
                let Rvalue::Class(op) = &mut i.value else {
                    unreachable!()
                };
                let ClassOp::InterfaceCall {
                    requirement,
                    slot,
                    receiver,
                    args,
                } = op.as_mut()
                else {
                    unreachable!()
                };
                match mutation {
                    5 => *slot = 0,
                    6 => {
                        *requirement = RequirementId {
                            interface: InterfaceId(1),
                            index: 0,
                        }
                    }
                    7 => *receiver = Operand::Bool(true),
                    8 => args.push(Operand::Bool(true)),
                    _ => unreachable!(),
                }
            }
            9 => {
                let index=instructions.iter().position(|i|matches!(&i.value,Rvalue::Class(op) if matches!(op.as_ref(),ClassOp::InterfaceCall{..}))).unwrap();
                instructions.swap(index, index + 1);
            }
            10 => {
                let i = instructions
                    .iter()
                    .rfind(|i| matches!(i.value, Rvalue::Drop { .. }))
                    .unwrap()
                    .clone();
                instructions.push(i);
            }
            11 => {
                let index = instructions
                    .iter()
                    .rposition(|i| matches!(i.value, Rvalue::Drop { .. }))
                    .unwrap();
                instructions.remove(index);
            }
            12 => {
                let i=instructions.iter_mut().find(|i|matches!(&i.value,Rvalue::Class(op) if matches!(op.as_ref(),ClassOp::HandleAlias{..}))).unwrap();
                let Rvalue::Class(op) = &i.value else {
                    unreachable!()
                };
                let ClassOp::HandleAlias { source } = op.as_ref() else {
                    unreachable!()
                };
                i.value = Rvalue::Use(source.clone());
            }
            13 => {
                let i=instructions.iter_mut().find(|i|matches!(&i.value,Rvalue::Class(op) if matches!(op.as_ref(),ClassOp::ReceiverKeepalive{..}))).unwrap();
                let Rvalue::Class(op) = &mut i.value else {
                    unreachable!()
                };
                let ClassOp::ReceiverKeepalive { mutable, .. } = op.as_mut() else {
                    unreachable!()
                };
                *mutable = false;
            }
            _ => unreachable!(),
        }
        assert!(
            verify_mir(bad).is_err(),
            "MIR interface mutation {mutation}"
        );
    }
}

#[test]
#[allow(clippy::too_many_lines)]
fn ssa_interface_corruptions_fail_independently() {
    let valid = build_ssa(
        &verify_mir(mir(&format!(
            "{COUNTER} int main(){{C c=C(0);I i=c;I j=i;return j.inc();}}"
        )))
        .unwrap(),
    );
    verify_ssa(valid.clone()).unwrap();
    for mutation in 0..13 {
        let mut bad = valid.clone();
        let instructions = &mut bad.functions[bad.entry.0 as usize].blocks[0].instructions;
        match mutation {
            0..=3 => {
                let i=instructions.iter_mut().find(|i|matches!(&i.op,SsaOp::Class(op) if matches!(op.as_ref(),ClassOp::InterfaceAdapt{..}))).unwrap();
                let SsaOp::Class(op) = &mut i.op else {
                    unreachable!()
                };
                let ClassOp::InterfaceAdapt {
                    class,
                    interface,
                    witness,
                    transfer,
                    ..
                } = op.as_mut()
                else {
                    unreachable!()
                };
                match mutation {
                    0 => *class = ClassId(999),
                    1 => *interface = InterfaceId(1),
                    2 => *witness = WitnessId(1),
                    3 => *transfer = true,
                    _ => unreachable!(),
                }
            }
            4..=7 => {
                let i=instructions.iter_mut().find(|i|matches!(&i.op,SsaOp::Class(op) if matches!(op.as_ref(),ClassOp::InterfaceCall{..}))).unwrap();
                let SsaOp::Class(op) = &mut i.op else {
                    unreachable!()
                };
                let ClassOp::InterfaceCall {
                    requirement,
                    slot,
                    receiver,
                    ..
                } = op.as_mut()
                else {
                    unreachable!()
                };
                match mutation {
                    4 => *slot = 0,
                    5 => {
                        *requirement = RequirementId {
                            interface: InterfaceId(1),
                            index: 0,
                        }
                    }
                    6 => *receiver = SsaOperand::Bool(true),
                    7 => i.ty = TypeId::BOOL,
                    _ => unreachable!(),
                }
            }
            8 => {
                let index=instructions.iter().position(|i|matches!(&i.op,SsaOp::Class(op) if matches!(op.as_ref(),ClassOp::InterfaceCall{..}))).unwrap();
                instructions.swap(index, index + 1);
            }
            9 => {
                let op = instructions
                    .iter()
                    .find(|i| matches!(i.op, SsaOp::Drop { .. }))
                    .unwrap()
                    .op
                    .clone();
                instructions
                    .iter_mut()
                    .rfind(|i| matches!(i.op, SsaOp::Drop { .. }))
                    .unwrap()
                    .op = op;
            }
            10 => {
                instructions
                    .iter_mut()
                    .rfind(|i| matches!(i.op, SsaOp::Drop { .. }))
                    .unwrap()
                    .op = SsaOp::Use(SsaOperand::Bool(true));
            }
            11 => {
                let i=instructions.iter_mut().find(|i|matches!(&i.op,SsaOp::Class(op) if matches!(op.as_ref(),ClassOp::HandleAlias{..}))).unwrap();
                let SsaOp::Class(op) = &i.op else {
                    unreachable!()
                };
                let ClassOp::HandleAlias { source } = op.as_ref() else {
                    unreachable!()
                };
                i.op = SsaOp::Use(source.clone());
            }
            12 => {
                let i=instructions.iter_mut().find(|i|matches!(&i.op,SsaOp::Class(op) if matches!(op.as_ref(),ClassOp::ReceiverKeepalive{..}))).unwrap();
                let SsaOp::Class(op) = &mut i.op else {
                    unreachable!()
                };
                let ClassOp::ReceiverKeepalive { mutable, .. } = op.as_mut() else {
                    unreachable!()
                };
                *mutable = false;
            }
            _ => unreachable!(),
        }
        assert!(
            verify_ssa(bad).is_err(),
            "SSA interface mutation {mutation}"
        );
    }
}

#[test]
fn modules_keep_interfaces_nominal() {
    use aether_driver::{CompilationSession, compile_session};
    let dir = Directory::new();
    let entry = dir.0.join("main.ae");
    let public = COUNTER
        .replace("interface ", "public interface ")
        .replace("class C", "public class C");
    fs::write(dir.0.join("first.ae"), &public).unwrap();
    fs::write(dir.0.join("second.ae"), &public).unwrap();
    fs::write(&entry,"import first;import second;int main(){first.I a=first.C(2);second.I b=second.C(3);return a.get()+b.get();}").unwrap();
    let c = compile_session(CompilationSession::discover(&entry).unwrap(), &[]).unwrap();
    for opt in ["-O0", "-O2"] {
        execute(&instrument(&c.llvm, 5, [2, 2, 4, 2, 0, 2, 2]), opt);
    }
    for body in [
        "first.C c=first.C(0);second.I i=c;",
        "first.I a=first.C(0);second.I b=a;",
    ] {
        fs::write(
            &entry,
            format!("import first;import second;int main(){{{body}}}"),
        )
        .unwrap();
        assert!(compile_session(CompilationSession::discover(&entry).unwrap(), &[]).is_err());
    }
    fs::write(dir.0.join("first.ae"), COUNTER).unwrap();
    fs::write(&entry, "import first;int main(){first.I i=first.C(0);}").unwrap();
    assert!(compile_session(CompilationSession::discover(&entry).unwrap(), &[]).is_err());
}

#[test]
fn interface_keepalive_survives_rebound_original_owner() {
    let source = "interface I{int get(int x);}class C:I{int n;public init(int n){this.n=n;}public int get(int x){return n+x;}}int effect(){return 3;}int main(){I i=C(2);int n=i.get(effect());i=C(9);return n;}";
    let mut fixture = mir(source);
    let instructions = &mut fixture.functions[fixture.entry.0 as usize].blocks[0].instructions;
    let start=instructions.iter().enumerate().filter(|(_,i)|matches!(&i.value,Rvalue::Class(op) if matches!(op.as_ref(),ClassOp::ObjectAlloc{..}))).nth(1).unwrap().0;
    let end = start
        + instructions[start..]
            .iter()
            .position(|i| matches!(i.value, Rvalue::Drop { .. }))
            .unwrap()
        + 1;
    let replacement = instructions.drain(start..end).collect::<Vec<_>>();
    let insertion=instructions.iter().position(|i|matches!(&i.value,Rvalue::Class(op) if matches!(op.as_ref(),ClassOp::ReceiverKeepalive{..}))).unwrap()+1;
    instructions.splice(insertion..insertion, replacement);
    let ssa = verify_ssa(build_ssa(&verify_mir(fixture).unwrap())).unwrap();
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

#[test]
fn metadata_corruption_is_rejected_again_in_mir_and_ssa() {
    fn corrupt(types: &mut aether_frontend::TypeArena, mutation: u32) {
        let mut witness = types.witnesses()[0].clone();
        let mut class = types.classes()[0].clone();
        match mutation {
            0 => witness.class = ClassId(999),
            1 => witness.interface = InterfaceId(1),
            2 => {
                witness.slots.pop();
            }
            3 => witness.slots[1] = witness.slots[0].clone(),
            4 => witness.slots[0].requirement.interface = InterfaceId(1),
            5 => witness.slots[0].method = aether_frontend::FunctionId(999),
            6 => {
                class
                    .methods
                    .iter_mut()
                    .find(|m| m.name == "get")
                    .unwrap()
                    .public = false;
            }
            7 => {
                class
                    .methods
                    .iter_mut()
                    .find(|m| m.name == "get")
                    .unwrap()
                    .mutable = true;
            }
            8 => class
                .methods
                .iter_mut()
                .find(|m| m.name == "get")
                .unwrap()
                .parameters
                .push(TypeId::BOOL),
            9 => {
                class
                    .methods
                    .iter_mut()
                    .find(|m| m.name == "get")
                    .unwrap()
                    .result = TypeId::BOOL;
            }
            10 => witness.slots.reverse(),
            11 => class.interfaces.clear(),
            12 => class.destruction.clear(),
            _ => unreachable!(),
        }
        types.register_witness(witness);
        types.register_class_definition(class);
    }
    let valid = mir(&format!("{COUNTER} int main(){{I i=C(0);return i.get();}}"));
    let ssa = build_ssa(&verify_mir(valid.clone()).unwrap());
    for mutation in 0..13 {
        let mut bad = valid.clone();
        corrupt(std::sync::Arc::make_mut(&mut bad.types), mutation);
        assert!(verify_mir(bad).is_err(), "MIR metadata {mutation}");
        let mut bad = ssa.clone();
        corrupt(std::sync::Arc::make_mut(&mut bad.types), mutation);
        assert!(verify_ssa(bad).is_err(), "SSA metadata {mutation}");
    }
}

#[test]
fn interface_phi_cannot_duplicate_an_owner() {
    let source = format!(
        "{COUNTER} int main(){{I a=C(1);I b=C(2);if(true){{a=b;}}else{{b=a;}}return a.get()+b.get();}}"
    );
    let valid = build_ssa(&verify_mir(mir(&source)).unwrap());
    verify_ssa(valid.clone()).unwrap();
    let mut bad = valid;
    let block = bad.functions[bad.entry.0 as usize]
        .blocks
        .iter_mut()
        .find(|b| {
            b.phis
                .iter()
                .filter(|p| bad.types.interface_id(p.ty).is_some())
                .count()
                >= 2
        })
        .unwrap();
    let mut phis = block
        .phis
        .iter_mut()
        .filter(|p| bad.types.interface_id(p.ty).is_some());
    let first = phis.next().unwrap().incoming.clone();
    phis.next().unwrap().incoming = first;
    assert!(verify_ssa(bad).is_err());
    // Interface results require the owner ledger even without adaptation/call ClassOps.
    let mut bad = build_ssa(
        &verify_mir(mir(
            "interface I{} I make(){return make();} int main(){I i=make();}",
        ))
        .unwrap(),
    );
    bad.functions[bad.entry.0 as usize].blocks[0]
        .instructions
        .iter_mut()
        .find(|i| matches!(i.op, SsaOp::Drop { .. }))
        .unwrap()
        .op = SsaOp::Use(SsaOperand::Bool(true));
    assert!(
        verify_ssa(bad).is_err(),
        "interface result without local adaptation still owns a token"
    );
}

#[test]
fn exact_indirect_scalar_reference_aggregate_and_owner_contracts() {
    let cases = [
        (
            "interface I{int add(int x,bool yes);}class C:I{public int add(int x,bool yes){if(yes){return x+1;}return x;}}int main(){I i=C();return i.add(6,true);}",
            7,
            [1, 1, 2, 1, 0, 1, 1],
        ),
        (
            "interface I{int read(ref int x);}class C:I{public int read(ref int x){return *x;}}int main(){I i=C();int n=7;return i.read(&n);}",
            7,
            [1, 1, 2, 1, 0, 1, 1],
        ),
        (
            "struct P{int x;int y;}interface I{P echo(P p);}class C:I{public P echo(P p){return p;}}int main(){I i=C();P p=i.echo(P(3,4));return p.x+p.y;}",
            7,
            [1, 1, 2, 1, 0, 1, 1],
        ),
        (
            "interface I{Buffer<int> echo(Buffer<int> b);}class C:I{public Buffer<int> echo(Buffer<int> b){return b;}}int main(){I i=C();Buffer<int> b=i.echo(Buffer<int>(2,7));return b[0];}",
            7,
            [1, 1, 2, 1, 0, 2, 2],
        ),
        (
            "interface I{I echo(I i);int get();}class C:I{public I echo(I i){return i;}public int get(){return 7;}}int main(){I i=C();I j=i.echo(i);return j.get();}",
            7,
            [1, 4, 5, 1, 0, 1, 1],
        ),
    ];
    for (source, result, counts) in cases {
        for opt in ["-O0", "-O2"] {
            execute(&instrument(&compile(source).llvm, result, counts), opt);
        }
    }
}
