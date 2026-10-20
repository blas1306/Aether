//! CLASS-BUFFER-FIELDS-V1 admission, storage-place, lifecycle and IR gates.
use aether_driver::{Emit, compile_source};
use aether_frontend::{FieldId, SourceFile, TypeId, analyze, parse_source};
use aether_middle::{
    Operand, PlaceBase, Rvalue, SsaOp, SsaOperand, SsaPlaceBase, build_ssa, lower_hir, verify_mir,
    verify_ssa,
};
use std::{fmt::Write, fs, path::PathBuf, process::Command};

struct Directory(PathBuf);

impl Directory {
    fn new() -> Self {
        static NEXT: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
        let path = std::env::temp_dir().join(format!(
            "aether-class-buffer-fields-v1-{}-{}",
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
        &SourceFile::new("class_buffer_fields.ae", text),
        &[Emit::Hir, Emit::Mir, Emit::Ssa],
    )
    .unwrap_or_else(|diagnostics| panic!("{text}\n{diagnostics:?}"))
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
        .arg("-lstdc++")
        .output()
        .unwrap();
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    assert_eq!(Command::new(exe).status().unwrap().code(), Some(0));
}

fn instrument(llvm: &str, counts: [u64; 7]) -> String {
    let names = [
        "object_alloc",
        "object_retain",
        "object_release",
        "object_destroy",
        "object_buffer_drop",
        "heap_alloc",
        "heap_free",
    ];
    let mut guard = "  %cbf_result_ok = icmp eq i32 %process_status, 0\n".to_owned();
    let mut last = "cbf_result_ok".to_owned();
    for (index, (name, expected)) in names.iter().zip(counts).enumerate() {
        writeln!(guard,"  %cbf_{index} = load i64, ptr @aether_{name}_count\n  %cbf_ok_{index} = icmp eq i64 %cbf_{index}, {expected}\n  %cbf_all_{index} = and i1 %{last}, %cbf_ok_{index}").unwrap();
        last = format!("cbf_all_{index}");
    }
    writeln!(
        guard,
        "  %cbf_status = select i1 %{last}, i32 0, i32 99\n  ret i32 %cbf_status"
    )
    .unwrap();
    llvm.replace("  ret i32 %process_status", &guard)
}

fn mir(text: &str) -> aether_middle::FlowMir {
    lower_hir(analyze(parse_source(&SourceFile::new("place.ae", text)).unwrap()).unwrap())
}

#[test]
fn admitted_element_kinds_and_inline_layout() {
    let cases = [
        "class C{Buffer<int> v;public init(){v=Buffer<int>(0,0);}}int main(){C c=C();return 0;}",
        "class C{Buffer<uint8> v;public init(){v=Buffer<uint8>(1,uint8(7));}}int main(){C c=C();return 0;}",
        "class C{Buffer<float32> v;public init(){v=Buffer<float32>(1,float32(1.0));}}int main(){C c=C();return 0;}",
        "class C{Buffer<float64> v;public init(){v=Buffer<float64>(1,1.0);}}int main(){C c=C();return 0;}",
        "class C{Buffer<bool> v;public init(){v=Buffer<bool>(1,true);}}int main(){C c=C();return 0;}",
        "class C{Buffer<char> v;public init(){v=Buffer<char>(1,'A');}}int main(){C c=C();return 0;}",
        "struct P{int x;int y;}class C{Buffer<P> v;public init(){v=Buffer<P>(1,P(1,2));}}int main(){C c=C();return 0;}",
        "struct P{int x;}struct N{P p;bool ok;}class C{Buffer<N> v;public init(){v=Buffer<N>(1,N(P(1),true));}}int main(){C c=C();return 0;}",
        "enum E{A,B}class C{Buffer<E> v;public init(){v=Buffer<E>(1,E.A);}}int main(){C c=C();return 0;}",
        "enum E{A,Value(int)}class C{Buffer<E> v;public init(){v=Buffer<E>(1,E.Value(3));}}int main(){C c=C();return 0;}",
        "struct Box<T>{T value;}class C{Buffer<Box<int>> v;public init(){v=Buffer<Box<int>>(1,Box<int>(3));}}int main(){C c=C();return 0;}",
    ];
    for source in cases {
        let compilation = compile(source);
        assert!(!compilation.llvm.contains("vtable"));
    }
}

#[test]
fn indexed_read_write_nested_projection_and_replacement_o0_o2() {
    let source = r"
struct Point { int x; int y; }
class Store {
    Buffer<Point> values;
    public init(Buffer<Point> initial) { values = initial; }
    public int read(usize i) { return values[i].x + values[i].y; }
    public mut int write(usize i, int x) { values[i].x = x; return values[i].x; }
    public mut int writePoint(usize i, Point point) { values[i] = point; return values[i].y; }
    public mut int replace(Buffer<Point> next) { values = next; return values[0].x; }
}
int main() {
    Store store = Store(Buffer<Point>(2, Point(3, 4)));
    if (store.read(1) != 7) { return 1; }
    if (store.write(0, 8) != 8) { return 2; }
    if (store.writePoint(1, Point(9, 10)) != 10) { return 4; }
    if (store.replace(Buffer<Point>(1, Point(5, 6))) != 5) { return 3; }
    return store.read(0) - 11;
}
";
    let compilation = compile(source);
    for phase in [Emit::Hir, Emit::Mir, Emit::Ssa] {
        assert!(compilation.dumps[&phase].contains("ClassField"));
        assert!(compilation.dumps[&phase].contains("Index"));
    }
    for forbidden in ["vtable", "reflection", "graphics", "boxed"] {
        assert!(!compilation.llvm.contains(forbidden), "{forbidden}");
    }
    assert!(compilation.llvm.contains("getelementptr i8"));
    assert!(compilation.llvm.contains("aether_drop_B"));
    for opt in ["-O0", "-O2"] {
        execute(&compilation.llvm, opt);
    }
}

#[test]
fn zero_length_alias_and_multiple_replacements_have_exact_lifecycle() {
    let zero = compile(
        "class C{Buffer<int> v;public init(){v=Buffer<int>(0,0);}}int main(){C c=C();return 0;}",
    );
    let replacements = compile(
        "class C{Buffer<float64> v;public init(Buffer<float64> v){this.v=v;}public mut int replace(Buffer<float64> v){this.v=v;return 0;}}int main(){C a=C(Buffer<float64>(1,1.0));C b=a;a.replace(Buffer<float64>(2,2.0));a.replace(Buffer<float64>(0,0.0));return 0;}",
    );
    for opt in ["-O0", "-O2"] {
        execute(&instrument(&zero.llvm, [1, 0, 1, 1, 1, 2, 2]), opt);
        execute(&instrument(&replacements.llvm, [1, 3, 4, 1, 1, 4, 4]), opt);
    }
}

#[test]
fn inheritance_constructor_unwind_and_failing_replacement_o0_o2() {
    let inheritance = compile(
        "struct P{int x;}open class Base{Buffer<float64> base;public init(){base=Buffer<float64>(1,2.0);}public float64 baseValue(){return base[0];}}class Child:Base{Buffer<P> own;public init():base(){own=Buffer<P>(1,P(5));}public int ownValue(){return own[0].x;}}int main(){Child c=Child();if(c.baseValue()!=2.0){return 1;}return c.ownValue()-5;}",
    );
    let unwind = compile(
        "open class Problem:Exception{public init(){}}int fail(){throw Problem();}Buffer<float64> failBuffer(){throw Problem();}class C{Buffer<float64> v;public init(int mode){if(mode==0){fail();}v=Buffer<float64>(1,7.0);if(mode==1){fail();}}public float64 read(){return v[0];}public mut int replace(){v=failBuffer();return 1;}}int main(){try{C before=C(0);}catch(Problem e){}try{C after=C(1);}catch(Problem e){}C c=C(2);try{c.replace();}catch(Problem e){if(c.read()==7.0){return 0;}return 2;}return 3;}",
    );
    for opt in ["-O0", "-O2"] {
        execute(&inheritance.llvm, opt);
        execute(&unwind.llvm, opt);
    }
}

#[test]
fn rejected_storage_visibility_moves_and_borrows() {
    let cases = [
        "class C{public Buffer<float64> v;public init(){v=Buffer<float64>(1,0.0);}}int main(){}",
        "class C{Buffer<string> v;public init(){v=Buffer<string>(1,\"x\");}}int main(){}",
        "class D{}class C{Buffer<D> v;public init(){v=Buffer<D>(1,D());}}int main(){}",
        "struct O{Buffer<int> b;}class C{Buffer<O> v;public init(Buffer<O> v){this.v=v;}}int main(){}",
        "struct O{Matrix<int> m;}class C{Buffer<O> v;public init(Buffer<O> v){this.v=v;}}int main(){}",
        "struct F{Function<(),int> f;}class C{Buffer<F> v;public init(Buffer<F> v){this.v=v;}}int main(){}",
        "class C<T>{Buffer<T> v;}int main(){}",
        "class C{Buffer<int> v;public init(){v=Buffer<int>(1,0);}public Buffer<int> take(){return v;}}int main(){}",
        "class C{Buffer<int> v;public init(){v=Buffer<int>(1,0);}public int bad(){ref Buffer<int> r=&v;return 0;}}int main(){}",
        "class C{Buffer<int> v;public init(){v=Buffer<int>(1,0);}public int bad(){ref int r=&v[0];return 0;}}int main(){}",
        "class C{Buffer<int> v;public init(){v=Buffer<int>(1,0);}public int bad(){View<int> x=view(v);return 0;}}int main(){}",
        "class C{Buffer<int> v;public init(){v=Buffer<int>(1,0);}public int bad(){ViewMut<int> x=view_mut(v);return 0;}}int main(){}",
        "class C{Buffer<int> a;Buffer<int> b;public init(){a=Buffer<int>(1,0);b=a;}}int main(){}",
        "class C{Buffer<int> v;public init(){v=Buffer<int>(1,0);}public int bad(){v[0]=1;return 0;}}int main(){}",
        "class C{Buffer<int> v;public init(){int x=v[0];v=Buffer<int>(1,0);}}int main(){}",
        "class C{Buffer<int> v;public init(){v=Buffer<int>(1,0);}}int main(){C c=C();return c.v[0];}",
    ];
    for source in cases {
        assert!(
            compile_source(&SourceFile::new("negative.ae", source), &[]).is_err(),
            "unexpected acceptance: {source}"
        );
    }
}

#[test]
fn place_contract_survives_all_verifiers() {
    let source = SourceFile::new(
        "verify.ae",
        "class C{Buffer<float64> v;public init(){v=Buffer<float64>(1,2.0);}public float64 get(){return v[0];}}int main(){C c=C();if(c.get()==2.0){return 0;}return 1;}",
    );
    let hir = analyze(parse_source(&source).unwrap()).unwrap();
    let mir = verify_mir(lower_hir(hir)).unwrap();
    verify_ssa(build_ssa(&mir)).unwrap();
}

#[test]
fn mir_and_ssa_reject_corrupted_class_field_storage_places() {
    let source = "class C{Buffer<float64> v;public init(){v=Buffer<float64>(1,2.0);}public float64 get(){return v[0];}}int main(){C c=C();if(c.get()==2.0){return 0;}return 1;}";
    let valid_mir = mir(source);
    for mutation in 0..5 {
        let mut bad = valid_mir.clone();
        let place = bad
            .functions
            .iter_mut()
            .flat_map(|function| &mut function.blocks)
            .flat_map(|block| &mut block.instructions)
            .find_map(|instruction| match &mut instruction.value {
                Rvalue::Load(place) if matches!(place.base, PlaceBase::ClassField { .. }) => {
                    Some(place)
                }
                _ => None,
            })
            .unwrap();
        match mutation {
            0 => {
                let PlaceBase::ClassField { receiver, .. } = &mut place.base else {
                    unreachable!()
                };
                *receiver = Operand::Bool(true);
            }
            1 => {
                let PlaceBase::ClassField { field, .. } = &mut place.base else {
                    unreachable!()
                };
                *field = FieldId(u32::MAX);
            }
            2 => {
                let PlaceBase::ClassField { field_type, .. } = &mut place.base else {
                    unreachable!()
                };
                *field_type = TypeId::BOOL;
            }
            3 => {
                let PlaceBase::ClassField { initialized, .. } = &mut place.base else {
                    unreachable!()
                };
                *initialized = false;
            }
            4 => place.projections.clear(),
            _ => unreachable!(),
        }
        assert!(verify_mir(bad).is_err(), "MIR mutation {mutation}");
    }

    let valid_mir = verify_mir(valid_mir).unwrap();
    let valid_ssa = build_ssa(&valid_mir);
    for mutation in 0..5 {
        let mut bad = valid_ssa.clone();
        let place = bad
            .functions
            .iter_mut()
            .flat_map(|function| &mut function.blocks)
            .flat_map(|block| &mut block.instructions)
            .find_map(|instruction| match &mut instruction.op {
                SsaOp::Load { place } if matches!(place.base, SsaPlaceBase::ClassField { .. }) => {
                    Some(place)
                }
                _ => None,
            })
            .unwrap();
        match mutation {
            0 => {
                let SsaPlaceBase::ClassField { receiver, .. } = &mut place.base else {
                    unreachable!()
                };
                *receiver = SsaOperand::Bool(true);
            }
            1 => {
                let SsaPlaceBase::ClassField { field, .. } = &mut place.base else {
                    unreachable!()
                };
                *field = FieldId(u32::MAX);
            }
            2 => {
                let SsaPlaceBase::ClassField { field_type, .. } = &mut place.base else {
                    unreachable!()
                };
                *field_type = TypeId::BOOL;
            }
            3 => {
                let SsaPlaceBase::ClassField { initialized, .. } = &mut place.base else {
                    unreachable!()
                };
                *initialized = false;
            }
            4 => place.projections.clear(),
            _ => unreachable!(),
        }
        assert!(verify_ssa(bad).is_err(), "SSA mutation {mutation}");
    }
}
