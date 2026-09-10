//! OOP-V1 native ARC counters, source boundaries and independent IR corruption.
use aether_driver::{Emit, compile_source};
use aether_frontend::{ClassId, ClassOp, SourceFile, TypeData, TypeId, analyze, parse_source};
use aether_middle::{
    Operand, Rvalue, SsaOp, SsaOperand, build_ssa, lower_hir, verify_mir, verify_ssa,
};
use std::{fmt::Write, fs, path::PathBuf, process::Command};

const COUNTER: &str = r"
class Counter {
    int value;
    public init(int value) { this.value = value; }
    public mut int increment() { value = value + 1; return value; }
    public int get() { return value; }
    public int read_again() { return this.get(); }
    public mut int increment_again() { return increment(); }
    public int with_arg(int n) { return value + n; }
}
";
const OWNER: &str = r"
class Owner {
    Buffer<int> data;
    public init(Buffer<int> data) { this.data = data; }
    public int marker() { return 1; }
    public mut int replace(Buffer<int> data) { this.data = data; return 1; }
}
";
struct Directory(PathBuf);
impl Directory {
    fn new() -> Self {
        static NEXT: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
        let path = std::env::temp_dir().join(format!(
            "aether-oop-v1-{}-{}",
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
fn native_identity_alias_transfer_lifecycle_o0_o2() {
    let cases = [
        ("empty", "class Empty {} int main(){Empty a=Empty();return 0;}".into(),0,[1,0,1,1,0,1,1]),
        ("scalar",format!("{COUNTER} int main(){{Counter a=Counter(3);return a.get();}}"),3,[1,1,2,1,0,1,1]),
        ("mutation",format!("{COUNTER} int main(){{Counter a=Counter(0);a.increment();return a.get();}}"),1,[1,2,3,1,0,1,1]),
        ("alias",format!("{COUNTER} int main(){{Counter a=Counter(0);Counter b=a;b.increment();return a.get();}}"),1,[1,3,4,1,0,1,1]),
        ("independent",format!("{COUNTER} int main(){{Counter a=Counter(1);Counter b=Counter(1);if(a==b){{return 99;}}return 0;}}"),0,[2,0,2,2,0,2,2]),
        ("identity",format!("{COUNTER} int main(){{Counter a=Counter(1);Counter b=a;if(a!=b){{return 99;}}if(a==b){{return 0;}}return 99;}}"),0,[1,1,2,1,0,1,1]),
        ("self",format!("{COUNTER} int main(){{Counter a=Counter(3);a=a;return a.get();}}"),3,[1,1,2,1,0,1,1]),
        ("replace",format!("{COUNTER} int main(){{Counter a=Counter(3);Counter b=a;a=Counter(7);return b.get()+a.get();}}"),10,[2,3,5,2,0,2,2]),
        ("lvalue_arg",format!("{COUNTER} int use(Counter c){{c.increment();return c.get();}} int main(){{Counter a=Counter(0);int n=use(a);return a.get();}}"),1,[1,4,5,1,0,1,1]),
        ("fresh_arg",format!("{COUNTER} int use(Counter c){{c.increment();return c.get();}} int main(){{return use(Counter(0));}}"),1,[1,2,3,1,0,1,1]),
        ("fresh_return",format!("{COUNTER} Counter make(){{return Counter(4);}} int main(){{Counter a=make();return a.get();}}"),4,[1,1,2,1,0,1,1]),
        ("lvalue_return",format!("{COUNTER} Counter same(Counter c){{return c;}} int main(){{Counter a=Counter(0);Counter b=same(a);b.increment();return a.get();}}"),1,[1,4,5,1,0,1,1]),
        ("read_call",format!("{COUNTER} int main(){{Counter a=Counter(2);return a.read_again();}}"),2,[1,2,3,1,0,1,1]),
        ("mut_call",format!("{COUNTER} int main(){{Counter a=Counter(2);return a.increment_again();}}"),3,[1,2,3,1,0,1,1]),
        ("buffer",format!("{OWNER} int main(){{Buffer<int> b=Buffer<int>(4,8);Owner x=Owner(b);Owner y=x;return y.marker();}}"),1,[1,2,3,1,1,2,2]),
        ("early_return",format!("{COUNTER} int f(bool q){{Counter a=Counter(5);Counter b=a;if(q){{return b.get();}}return a.get();}} int main(){{return f(true);}}"),5,[1,2,3,1,0,1,1]),
        ("branch",format!("{COUNTER} int main(){{Counter a=Counter(0);if(true){{Counter b=a;b.increment();}}else{{Counter b=a;b.increment();}}return a.get();}}"),1,[1,3,4,1,0,1,1]),
        ("temporary",format!("{COUNTER} int main(){{return Counter(5).get();}}"),5,[1,0,1,1,0,1,1]),
        ("init_branch", "class C{int n; public init(bool q){if(q){n=1;}else{n=2;}} public int get(){return n;}} int main(){C a=C(false);return a.get();}".into(),2,[1,1,2,1,0,1,1]),
        ("public_field", "class C{public int n;public init(){n=1;}} int main(){C a=C();a.n=4;return a.n;}".into(),4,[1,0,1,1,0,1,1]),
    ];
    for (name, text, result, counts) in cases {
        let c = compile(&text);
        eprintln!(
            "OOP-V1 {name}: alloc/retain/release/destroy/Buffer-drop/heap-alloc/heap-free={counts:?}"
        );
        for opt in ["-O0", "-O2"] {
            execute(&instrument(&c.llvm, result, counts), opt);
        }
    }
}
#[test]
fn nominal_properties_and_explicit_operations() {
    let source = SourceFile::new(
        "oop.ae",
        format!("{COUNTER} int main(){{Counter a=Counter(0);Counter b=a;return b.get();}}"),
    );
    let h = analyze(parse_source(&source).unwrap()).unwrap();
    let ty = h.types().id_of(TypeData::Class(ClassId(0))).unwrap();
    assert!(!h.types().guarantees_copy(ty));
    assert!(h.types().is_relocatable(ty));
    assert!(h.types().needs_drop(ty));
    assert!(!h.types().is_admitted_list_element(ty));
    assert_eq!(
        h.types().classes()[0].layout,
        aether_frontend::TypeLayout { size: 16, align: 8 }
    );
    let c = compile(&source.text);
    for phase in [Emit::Hir, Emit::Mir, Emit::Ssa] {
        for operation in [
            "HandleAlias",
            "HandleTransfer",
            "ReceiverKeepalive",
            "DirectMethodCall",
        ] {
            assert!(
                c.dumps[&phase].contains(operation),
                "{phase:?}: {operation}"
            );
        }
    }
    for phase in [Emit::Mir, Emit::Ssa] {
        for op in ["ObjectAlloc", "InitCall", "PublishObject"] {
            assert!(c.dumps[&phase].contains(op));
        }
    }
    assert!(!c.llvm.contains("atomic"));
    assert!(!c.llvm.contains("noalias"));
}

#[test]
#[allow(clippy::too_many_lines)]
fn negative_source_boundaries() {
    let cases = [
        (
            "read_write",
            "class C{int n;public init(){n=0;}public int bad(){n=1;return n;}} int main(){}",
        ),
        (
            "read_buffer_write",
            "class C{Buffer<int> b;public init(Buffer<int> x){b=x;}public int bad(Buffer<int> x){b=x;return 0;}} int main(){}",
        ),
        (
            "read_mut_call",
            "class C{public mut int m(){return 0;}public int bad(){return this.m();}} int main(){}",
        ),
        (
            "read_implicit_mut_call",
            "class C{public mut int m(){return 0;}public int bad(){return m();}} int main(){}",
        ),
        (
            "this_alias",
            "class C{public init(){} public int bad(){C a=this;return 0;}} int main(){}",
        ),
        (
            "this_return",
            "class C{public init(){} public C bad(){return this;}} int main(){}",
        ),
        (
            "this_pass",
            "int f(C c){return 0;} class C{public init(){}public int bad(){return f(this);}} int main(){}",
        ),
        (
            "init_this_escape",
            "int f(C c){return 0;} class C{public init(){f(this);}} int main(){}",
        ),
        (
            "init_call",
            "class C{public init(){this.get();}public int get(){return 0;}}int main(){}",
        ),
        (
            "init_implicit_call",
            "class C{public init(){get();}public int get(){return 0;}}int main(){}",
        ),
        ("missing_init", "class C{int n;} int main(){}"),
        (
            "incomplete_init",
            "class C{int n;public init(){}} int main(){}",
        ),
        (
            "read_before_init",
            "class C{int n;public init(){n=n+1;}} int main(){}",
        ),
        (
            "conditional_init",
            "class C{int n;public init(bool b){if(b){n=1;}}} int main(){}",
        ),
        (
            "loop_init",
            "class C{int n;public init(bool b){while(b){n=1;}}} int main(){}",
        ),
        (
            "init_return",
            "class C{public init(){return 0;}} int main(){}",
        ),
        (
            "duplicate_init",
            "class C{public init(){}public init(int n){}} int main(){}",
        ),
        (
            "private_field",
            "class C{int n;public init(){n=0;}}int main(){C c=C();return c.n;}",
        ),
        (
            "private_method",
            "class C{public init(){}int get(){return 0;}}int main(){C c=C();return c.get();}",
        ),
        (
            "private_init",
            "class C{private init(){}}int main(){C c=C();}",
        ),
        (
            "default_private_init",
            "class C{init(){}}int main(){C c=C();}",
        ),
        (
            "class_graph",
            "class C{C next;public init(C n){next=n;}}int main(){}",
        ),
        ("struct_class_edge", "class C{}struct S{C c;}int main(){}"),
        ("enum_class_edge", "class C{}enum E{V(C)}int main(){}"),
        (
            "reference_field",
            "class C{ref int n;public init(ref int x){n=x;}}int main(){}",
        ),
        (
            "view_field",
            "class C{View<int> n;public init(View<int> x){n=x;}}int main(){}",
        ),
        (
            "list_field",
            "class C{List<int> n;public init(List<int> x){n=x;}}int main(){}",
        ),
        (
            "array_field",
            "class C{Array<int> n;public init(Array<int> x){n=x;}}int main(){}",
        ),
        (
            "public_buffer",
            "class C{public Buffer<int> n;public init(Buffer<int> x){n=x;}}int main(){}",
        ),
        (
            "wrong_buffer",
            "class C{Buffer<double> n;public init(Buffer<double> x){n=x;}}int main(){}",
        ),
        (
            "buffer_extract",
            "class C{Buffer<int> n;public init(Buffer<int> x){n=x;}public int bad(){Buffer<int> b=n;return 0;}}int main(){}",
        ),
        (
            "interior_reference",
            "class C{public int n;public init(){n=0;}}int main(){C c=C();ref int r=&c.n;}",
        ),
        (
            "interior_mut_reference",
            "class C{public int n;public init(){n=0;}}int main(){C c=C();ref mut int r=&mut c.n;}",
        ),
        (
            "interior_this_reference",
            "class C{int n;public init(){n=0;}public int bad(){ref int r=&this.n;return *r;}}int main(){}",
        ),
        ("generic_class", "class C<T>{}int main(){}"),
        (
            "generic_method",
            "class C{public int f<T>(T x){return 0;}}int main(){}",
        ),
        (
            "copy_bound",
            "class C{}int f<T:Copy>(T x){return 0;}int main(){C c=C();return f<C>(c);}",
        ),
        ("generic_container", "class C{}int main(){List<C> c={C()};}"),
        ("inheritance", "class A{}class B:A{}int main(){}"),
        (
            "generic_interface",
            "interface I<T>{int get();}int main(){}",
        ),
        ("open", "open class C{}int main(){}"),
        (
            "override",
            "class C{public override int get(){return 0;}}int main(){}",
        ),
        ("destructor", "class C{deinit{}}int main(){}"),
        ("null", "class C{}int main(){C c=null;}"),
        (
            "order",
            "class C{}int main(){C a=C();C b=C();if(a<b){return 1;}return 0;}",
        ),
        (
            "cross_identity",
            "class A{}class B{}int main(){A a=A();B b=B();if(a==b){return 1;}return 0;}",
        ),
        (
            "temporary_mut",
            "class C{public mut int m(){return 0;}}int main(){return C().m();}",
        ),
        (
            "shadow_this",
            "class C{public int m(){int this=0;return this;}}int main(){}",
        ),
        (
            "init_this_assignment",
            "class C{public init(){this=this;}}int main(){}",
        ),
        (
            "moved_buffer",
            "class C{Buffer<int> b;public init(Buffer<int> x){b=x;}}int main(){Buffer<int> b=Buffer<int>(1,0);C c=C(b);Buffer<int> x=b;}",
        ),
    ];
    for (name, text) in cases {
        let error = compile_source(&SourceFile::new("negative.ae", text), &[]).expect_err(name);
        assert!(!error.is_empty(), "{name}");
        assert!(
            error[0].span.is_some(),
            "{name}: expected a source diagnostic, got {error:?}"
        );
    }
}

#[test]
#[allow(clippy::too_many_lines)]
fn mir_corruptions_fail_independently() {
    let source =
        format!("{COUNTER} int main(){{Counter a=Counter(2);Counter b=a;return b.get();}}");
    let valid = mir(&source);
    verify_mir(valid.clone()).unwrap();
    for mutation in 0..12 {
        let mut bad = valid.clone();
        let f = &mut bad.functions[bad.entry.0 as usize];
        let instructions = &mut f.blocks[0].instructions;
        match mutation {
            0 => {
                // release without acquisition
                let i=instructions.iter_mut().find(|i| matches!(&i.value,Rvalue::Class(op) if matches!(op.as_ref(),ClassOp::HandleAlias{..}))).unwrap();
                let Rvalue::Class(op) = &i.value else {
                    unreachable!()
                };
                let ClassOp::HandleAlias { source } = op.as_ref() else {
                    unreachable!()
                };
                i.value = Rvalue::Use(source.clone());
            }
            1 => {
                let i = instructions
                    .iter()
                    .find(|i| matches!(i.value, Rvalue::Drop { .. }))
                    .unwrap()
                    .clone();
                instructions.push(i);
            }
            2 => {
                let index = instructions
                    .iter()
                    .rposition(|i| matches!(i.value, Rvalue::Drop { .. }))
                    .unwrap();
                instructions.remove(index);
            }
            3 => {
                // consume source in place of alias; future source cleanup invalid
                let i=instructions.iter_mut().find(|i|matches!(&i.value,Rvalue::Class(op) if matches!(op.as_ref(),ClassOp::HandleAlias{..}))).unwrap();
                if let Rvalue::Class(op) = &mut i.value {
                    let ClassOp::HandleAlias { source } = op.as_ref() else {
                        unreachable!()
                    };
                    **op = ClassOp::HandleTransfer {
                        source: source.clone(),
                    };
                }
            }
            4 => {
                let index=instructions.iter().position(|i|matches!(&i.value,Rvalue::Class(op) if matches!(op.as_ref(),ClassOp::InitCall{..}))).unwrap();
                instructions.remove(index);
            }
            5 => {
                let index=instructions.iter().position(|i|matches!(&i.value,Rvalue::Class(op) if matches!(op.as_ref(),ClassOp::PublishObject{..}))).unwrap();
                instructions.swap(index, index - 1);
            }
            6 => {
                let index=instructions.iter().position(|i|matches!(&i.value,Rvalue::Class(op) if matches!(op.as_ref(),ClassOp::DirectMethodCall{..}))).unwrap();
                let drop = instructions.remove(index + 1);
                instructions.insert(index, drop);
            }
            7 => {
                for i in instructions {
                    if let Rvalue::Class(op) = &mut i.value
                        && let ClassOp::DirectMethodCall { method, .. } = op.as_mut()
                    {
                        *method = bad.entry;
                    }
                }
            }
            8 => {
                for i in instructions {
                    if let Rvalue::Class(op) = &mut i.value
                        && let ClassOp::ObjectAlloc { class } = op.as_mut()
                    {
                        *class = ClassId(999);
                    }
                }
            }
            9 => {
                let init = bad
                    .signatures
                    .iter()
                    .find(|s| s.name.rsplit('.').next() == Some("init"))
                    .unwrap()
                    .id;
                let f = &mut bad.functions[init.0 as usize];
                for i in &mut f.blocks[0].instructions {
                    if matches!(&i.value,Rvalue::Class(op) if matches!(op.as_ref(),ClassOp::FieldWrite{..}))
                    {
                        i.value = Rvalue::Use(Operand::Bool(true));
                    }
                }
            }
            10 => {
                let init = bad
                    .signatures
                    .iter()
                    .find(|s| s.name.rsplit('.').next() == Some("init"))
                    .unwrap()
                    .id;
                let f = &mut bad.functions[init.0 as usize];
                for i in &mut f.blocks[0].instructions {
                    if let Rvalue::Class(op) = &mut i.value
                        && let ClassOp::FieldWrite { field, .. } = op.as_mut()
                    {
                        *field = aether_frontend::FieldId(999);
                    }
                }
            }
            11 => {
                let index = instructions
                    .iter()
                    .rposition(|i| matches!(i.value, Rvalue::Drop { .. }))
                    .unwrap();
                let alias=instructions.iter().find(|i|matches!(&i.value,Rvalue::Class(op) if matches!(op.as_ref(),ClassOp::HandleAlias{..}))).unwrap().clone();
                instructions.insert(index + 1, alias);
            }
            _ => unreachable!(),
        }
        assert!(verify_mir(bad).is_err(), "MIR mutation {mutation}");
    }
}

#[test]
fn ssa_corruptions_fail_independently() {
    let source =
        format!("{COUNTER} int main(){{Counter a=Counter(2);Counter b=a;return b.get();}}");
    let valid = build_ssa(&verify_mir(mir(&source)).unwrap());
    verify_ssa(valid.clone()).unwrap();
    for mutation in 0..10 {
        let mut bad = valid.clone();
        let instructions = &mut bad.functions[bad.entry.0 as usize].blocks[0].instructions;
        match mutation {
            0 => {
                let i = instructions
                    .iter_mut()
                    .rfind(|i| matches!(i.op, SsaOp::Drop { .. }))
                    .unwrap();
                i.op = SsaOp::Use(SsaOperand::Bool(true));
            }
            1 => {
                let drop = instructions
                    .iter()
                    .find(|i| matches!(i.op, SsaOp::Drop { .. }))
                    .unwrap()
                    .op
                    .clone();
                let i = instructions
                    .iter_mut()
                    .rfind(|i| matches!(i.op, SsaOp::Drop { .. }))
                    .unwrap();
                i.op = drop;
            }
            2 => {
                for i in instructions {
                    if let SsaOp::Class(op) = &mut i.op
                        && let ClassOp::DirectMethodCall { method, .. } = op.as_mut()
                    {
                        *method = bad.entry;
                    }
                }
            }
            3 => {
                for i in instructions {
                    if let SsaOp::Class(op) = &mut i.op
                        && let ClassOp::ReceiverKeepalive { mutable, .. } = op.as_mut()
                    {
                        *mutable = !*mutable;
                    }
                }
            }
            4 => {
                let i=instructions.iter_mut().find(|i|matches!(&i.op,SsaOp::Class(op) if matches!(op.as_ref(),ClassOp::InitCall{..}))).unwrap();
                i.op = SsaOp::Use(SsaOperand::Bool(true));
            }
            5 => {
                let index=instructions.iter().position(|i|matches!(&i.op,SsaOp::Class(op) if matches!(op.as_ref(),ClassOp::PublishObject{..}))).unwrap();
                instructions.swap(index, index - 1);
            }
            6 => {
                let index=instructions.iter().position(|i|matches!(&i.op,SsaOp::Class(op) if matches!(op.as_ref(),ClassOp::DirectMethodCall{..}))).unwrap();
                instructions.swap(index, index + 1);
            }
            7 => {
                let init = bad
                    .signatures
                    .iter()
                    .find(|s| s.name.rsplit('.').next() == Some("init"))
                    .unwrap()
                    .id;
                for i in &mut bad.functions[init.0 as usize].blocks[0].instructions {
                    if let SsaOp::Class(op) = &mut i.op
                        && let ClassOp::FieldWrite { initialize, .. } = op.as_mut()
                    {
                        *initialize = false;
                    }
                }
            }
            8 => {
                let i=instructions.iter_mut().find(|i|matches!(&i.op,SsaOp::Class(op) if matches!(op.as_ref(),ClassOp::HandleAlias{..}))).unwrap();
                if let SsaOp::Class(op) = &i.op {
                    let ClassOp::HandleAlias { source } = op.as_ref() else {
                        unreachable!()
                    };
                    i.op = SsaOp::Use(source.clone());
                }
            }
            9 => {
                for i in instructions {
                    if let SsaOp::Class(op) = &mut i.op
                        && let ClassOp::ObjectAlloc { class } = op.as_mut()
                    {
                        *class = ClassId(888);
                    }
                }
            }
            _ => unreachable!(),
        }
        assert!(verify_ssa(bad).is_err(), "SSA mutation {mutation}");
    }
}

#[test]
fn receiver_keepalive_survives_rebound_owner_in_mir_native_fixture() {
    let source = format!(
        "{COUNTER} int effect(){{return 3;}} int main(){{Counter a=Counter(2);int n=a.with_arg(effect());a=Counter(9);return n;}}"
    );
    let mut fixture = mir(&source);
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
}

#[test]
fn modules_keep_classes_nominal_and_members_visible() {
    use aether_driver::{CompilationSession, compile_session};
    let dir = Directory::new();
    let entry = dir.0.join("main.ae");
    let public = COUNTER.replacen("class Counter", "public class Counter", 1);
    fs::write(dir.0.join("first.ae"), &public).unwrap();
    fs::write(dir.0.join("second.ae"), &public).unwrap();
    fs::write(&entry,"import first;import second;int main(){first.Counter a=first.Counter(5);second.Counter b=second.Counter(7);return a.get()+b.get();}").unwrap();
    let c = compile_session(CompilationSession::discover(&entry).unwrap(), &[Emit::Hir]).unwrap();
    for opt in ["-O0", "-O2"] {
        execute(&instrument(&c.llvm, 12, [2, 2, 4, 2, 0, 2, 2]), opt);
    }
    for body in [
        "first.Counter a=first.Counter(0);second.Counter b=a;",
        "first.Counter a=first.Counter(0);second.Counter b=second.Counter(0);if(a==b){return 1;}",
        "first.Counter a=first.Counter(0);return a.value;",
    ] {
        fs::write(
            &entry,
            format!("import first;import second;int main(){{{body}}}"),
        )
        .unwrap();
        assert!(
            compile_session(CompilationSession::discover(&entry).unwrap(), &[]).is_err(),
            "{body}"
        );
    }
    fs::write(dir.0.join("first.ae"), COUNTER).unwrap();
    fs::write(
        &entry,
        "import first;int main(){first.Counter a=first.Counter(0);}",
    )
    .unwrap();
    assert!(compile_session(CompilationSession::discover(&entry).unwrap(), &[]).is_err());
}

#[test]
fn owning_buffer_replacement_aliases_loops_and_value_fields() {
    let source = format!(
        "{OWNER} int main(){{Owner x=Owner(Buffer<int>(3,7));Owner y=x;x.replace(Buffer<int>(4,9));return y.marker();}}"
    );
    for opt in ["-O0", "-O2"] {
        execute(
            &instrument(&compile(&source).llvm, 1, [1, 3, 4, 1, 1, 3, 3]),
            opt,
        );
    }
    let source = format!(
        "{COUNTER} int main(){{Counter a=Counter(0);int i=0;while(i<3){{Counter b=a;b.increment();i=i+1;}}return a.get();}}"
    );
    for opt in ["-O0", "-O2"] {
        execute(
            &instrument(&compile(&source).llvm, 3, [1, 7, 8, 1, 0, 1, 1]),
            opt,
        );
    }
    let source = "struct Pair{int x;int y;}alias P=Pair;class C{P p;public init(P p){this.p=p;}public P get(){return p;}}int main(){C c=C(P(2,5));P p=c.get();return p.x+p.y;}";
    for opt in ["-O0", "-O2"] {
        execute(
            &instrument(&compile(source).llvm, 7, [1, 1, 2, 1, 0, 1, 1]),
            opt,
        );
    }
    let source = format!(
        "{COUNTER} int main(){{Counter a=Counter(0);Counter b=Counter(2);if(true){{a=b;}}else{{b=a;}}return a.get()+b.get();}}"
    );
    for opt in ["-O0", "-O2"] {
        execute(
            &instrument(&compile(&source).llvm, 4, [2, 3, 5, 2, 0, 2, 2]),
            opt,
        );
    }
}

#[test]
fn ssa_phi_and_equality_corruptions() {
    let source = format!(
        "{COUNTER} int main(){{Counter a=Counter(1);Counter b=Counter(2);if(true){{a=b;}}else{{b=a;}}return a.get()+b.get();}}"
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
    let second = phis.next().unwrap();
    second.incoming = first;
    assert!(
        verify_ssa(bad).is_err(),
        "two owning phis must not duplicate the same input token"
    );
    let source = "class A{}class B{}int main(){A a=A();B b=B();if(a==a){return 0;}return 1;}";
    let valid = mir(source);
    let mut bad = valid.clone();
    let f = &mut bad.functions[bad.entry.0 as usize];
    let b = f
        .locals
        .iter()
        .find(|l| l.name.as_deref() == Some("b"))
        .unwrap()
        .id;
    for i in f.blocks.iter_mut().flat_map(|b| &mut b.instructions) {
        if let Rvalue::Class(op) = &mut i.value
            && let ClassOp::IdentityEq { right, .. } = op.as_mut()
        {
            *right = Operand::Local(b);
        }
    }
    assert!(verify_mir(bad).is_err());
    let mut bad = build_ssa(&verify_mir(valid).unwrap());
    let b = bad.functions[bad.entry.0 as usize]
        .blocks
        .iter()
        .flat_map(|b| &b.instructions)
        .find(|i| {
            bad.types.class_id(i.ty) == Some(ClassId(1)) && matches!(i.op, SsaOp::Move { .. })
        })
        .unwrap()
        .result;
    for i in bad.functions[bad.entry.0 as usize]
        .blocks
        .iter_mut()
        .flat_map(|b| &mut b.instructions)
    {
        if let SsaOp::Class(op) = &mut i.op
            && let ClassOp::IdentityEq { right, .. } = op.as_mut()
        {
            *right = SsaOperand::Value(b);
        }
    }
    assert!(verify_ssa(bad).is_err());
}

#[test]
fn constructor_read_mut_contract_corruption_and_owning_fields() {
    let valid = mir(&format!(
        "{COUNTER} int main(){{Counter a=Counter(1);return a.get();}}"
    ));
    let mut bad = valid.clone();
    let read = bad
        .signatures
        .iter()
        .find(|s| s.name.rsplit('.').next() == Some("get"))
        .unwrap()
        .id;
    let instructions = &mut bad.functions[read.0 as usize].blocks[0].instructions;
    let i=instructions.iter_mut().find(|i|matches!(&i.value,Rvalue::Class(op) if matches!(op.as_ref(),ClassOp::FieldRead{..}))).unwrap();
    if let Rvalue::Class(op) = &mut i.value {
        let ClassOp::FieldRead { receiver, field } = op.as_ref() else {
            unreachable!()
        };
        **op = ClassOp::FieldWrite {
            receiver: receiver.clone(),
            field: *field,
            value: Operand::Int {
                value: 2,
                ty: TypeId::INT64,
            },
            initialize: false,
        };
    }
    assert!(verify_mir(bad).is_err());
    let mut bad = build_ssa(&verify_mir(valid).unwrap());
    let i = bad.functions[read.0 as usize].blocks[0]
        .instructions
        .iter_mut()
        .find(|i| matches!(&i.op,SsaOp::Class(op) if matches!(op.as_ref(),ClassOp::FieldRead{..})))
        .unwrap();
    if let SsaOp::Class(op) = &mut i.op {
        let ClassOp::FieldRead { receiver, field } = op.as_ref() else {
            unreachable!()
        };
        **op = ClassOp::FieldWrite {
            receiver: receiver.clone(),
            field: *field,
            value: SsaOperand::Int {
                value: 2,
                ty: TypeId::INT64,
            },
            initialize: false,
        };
    }
    assert!(verify_ssa(bad).is_err());
    let valid = mir(&format!(
        "{OWNER}int main(){{Owner x=Owner(Buffer<int>(3,0));}}"
    ));
    let init = valid
        .signatures
        .iter()
        .find(|s| s.name.rsplit('.').next() == Some("init"))
        .unwrap()
        .id;
    for duplicate in [false, true] {
        let mut bad = valid.clone();
        let instructions = &mut bad.functions[init.0 as usize].blocks[0].instructions;
        let index=instructions.iter().position(|i|matches!(&i.value,Rvalue::Class(op)if matches!(op.as_ref(),ClassOp::FieldWrite{..}))).unwrap();
        if duplicate {
            instructions.insert(index, instructions[index].clone());
        } else {
            instructions.remove(index);
        }
        assert!(verify_mir(bad).is_err());
        let mut bad = build_ssa(&verify_mir(valid.clone()).unwrap());
        let instructions = &mut bad.functions[init.0 as usize].blocks[0].instructions;
        let index=instructions.iter().position(|i|matches!(&i.op,SsaOp::Class(op)if matches!(op.as_ref(),ClassOp::FieldWrite{..}))).unwrap();
        if duplicate {
            let write = instructions[index].op.clone();
            let i = instructions
                .iter_mut()
                .rfind(|i| matches!(i.op, SsaOp::Use(_)))
                .unwrap();
            i.ty = TypeId::BOOL;
            i.op = write;
        } else {
            instructions[index].op = SsaOp::Use(SsaOperand::Bool(true));
        }
        assert!(verify_ssa(bad).is_err());
    }
}

#[test]
fn no_class_programs_emit_no_arc() {
    for text in [
        "int main(){return 3;}",
        "struct S{int n;}int main(){S s=S(1);return s.n;}",
        "int main(){Buffer<int> b=Buffer<int>(1,2);return b[0];}",
        "T id<T>(T x){return x;}int main(){return id<int>(3);}",
        "int main(){Matrix<int> a=[1,2;3,4];Matrix<int> b=a*a;return b[1,1];}",
        "int main(){// line\n /* ordinary block comment */ }",
    ] {
        let c = compile(text);
        assert!(!c.llvm.contains("aether_object_"));
        assert!(!c.dumps[&Emit::Mir].contains("ReceiverKeepalive"));
    }
    for declaration in ["class Unused {}", COUNTER] {
        let c = compile(&format!("{declaration} int main(){{return 3;}}"));
        assert!(!c.llvm.contains("aether_object_"));
        assert!(!c.llvm.contains("call i64 @aether_allocation_balance()"));
        for opt in ["-O0", "-O2"] {
            let checked = c.llvm.replace("%process_status = trunc i64 %aether_result to i32", "%checked = sub i64 %aether_result, 3\n  %process_status = trunc i64 %checked to i32");
            execute(&checked, opt);
        }
    }
}

#[test]
fn class_locals_preserve_existing_container_and_mathematical_programs() {
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../tests/programs");
    for name in [
        "v10_buffers.ae",
        "v16_list_buffer_growth.ae",
        "v16_array_buffer.ae",
        "v18_pop_buffer.ae",
        "v19_swap_remove_buffer.ae",
        "v20_remove_buffer.ae",
        "v20_remove_nested.ae",
        "v33_rectangular.ae",
        "v33_generic_int.ae",
        "language_parity_1.ae",
    ] {
        let source = fs::read_to_string(root.join(name)).unwrap();
        let main = source.find("int main()").unwrap();
        let brace = main + source[main..].find('{').unwrap() + 1;
        let mixed = format!(
            "class OopMarker{{}}\n{}OopMarker oop_marker=OopMarker();{}",
            &source[..brace],
            &source[brace..]
        );
        compile_source(&SourceFile::new(name, mixed), &[])
            .unwrap_or_else(|e| panic!("mixed {name}: {e:?}"));
    }
}

#[test]
fn arc_overflow_and_underflow_abort_without_wrapping() {
    use std::os::unix::process::ExitStatusExt;
    for (count, body) in [
        ("0", "Counter a=Counter(0);"),
        ("-1", "Counter a=Counter(0);Counter b=a;"),
    ] {
        let c = compile(&format!("{COUNTER}int main(){{{body}return 0;}}"));
        let allocation = c
            .llvm
            .lines()
            .find(|line| line.contains(" = call ptr @aether_object_alloc_0()"))
            .unwrap();
        let name = allocation.split('=').next().unwrap().trim();
        let injected = c.llvm.replace(
            allocation,
            &format!("{allocation}\n  store i64 {count}, ptr {name}"),
        );
        let dir = Directory::new();
        let ir = dir.0.join("bad-count.ll");
        fs::write(&ir, injected).unwrap();
        for opt in ["-O0", "-O2"] {
            let exe = dir.0.join("bad-count");
            let output = Command::new("clang")
                .args(["-Wno-override-module", opt])
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
            assert!(
                status.signal().is_some(),
                "invalid ARC counter {count} must trap"
            );
        }
    }
}

#[test]
fn simple_aliases_local_returns_and_initialized_replacement() {
    let cases=[
        (format!("{COUNTER}int main(){{Counter a=Counter(0);Counter b=a;return 0;}}"),0,[1,1,2,1,0,1,1]),
        (format!("{COUNTER}Counter make(){{Counter c=Counter(7);return c;}}int main(){{Counter a=make();return a.get();}}"),7,[1,2,3,1,0,1,1]),
        ("class C{int n;public init(bool b){if(b){n=1;}n=2;}public int get(){return n;}}int main(){C c=C(true);return c.get();}".into(),2,[1,1,2,1,0,1,1]),
        ("alias Handle=C;class C{public init(){}public Handle alias_arg(Handle a){return a;}}int main(){Handle a=Handle();Handle b=a.alias_arg(a);if(a==b){return 0;}return 1;}".into(),0,[1,3,4,1,0,1,1]),
    ];
    for (source, result, counts) in cases {
        let c = compile(&source);
        for opt in ["-O0", "-O2"] {
            execute(&instrument(&c.llvm, result, counts), opt);
        }
    }
    let error=compile_source(&SourceFile::new("bad-api.ae","class Hidden{}public class Exposed{public Hidden expose(Hidden h){return h;}}int main(){}"),&[]).unwrap_err();
    assert_eq!(error[0].code, "E0402");
    assert!(error[0].span.is_some());
}

#[test]
fn mir_ssa_corrupted_nested_drop_recipes_and_offsets_fail_closed() {
    let source = format!("{OWNER}int main(){{Owner x=Owner(Buffer<int>(3,0));}} ");
    let valid = mir(&source);
    let valid_ssa = build_ssa(&verify_mir(valid.clone()).unwrap());
    for mutation in 0..5 {
        let mut definition = valid.types.classes()[0].clone();
        match mutation {
            0 => {
                definition.destruction.remove(0);
            }
            1 => definition
                .destruction
                .insert(0, definition.destruction[0].clone()),
            2 => definition.destruction.reverse(),
            3 => definition.fields[0].offset += 8,
            4 => definition.fields[0].id = aether_frontend::FieldId(999),
            _ => unreachable!(),
        }
        let mut bad = valid.clone();
        std::sync::Arc::make_mut(&mut bad.types).register_class_definition(definition.clone());
        assert!(verify_mir(bad).is_err(), "MIR metadata mutation {mutation}");
        let mut bad = valid_ssa.clone();
        std::sync::Arc::make_mut(&mut bad.types).register_class_definition(definition);
        assert!(verify_ssa(bad).is_err(), "SSA metadata mutation {mutation}");
    }
}
