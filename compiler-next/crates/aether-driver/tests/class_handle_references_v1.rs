//! CLASS-HANDLE-REFERENCES-V1 shared class-handle borrow qualification.

use std::fmt::Write as _;
use std::{fs, path::PathBuf, process::Command};

use aether_driver::{ClangToolchain, Emit, OptimizationLevel, compile_source_with_optimization};
use aether_frontend::{ClassId, ClassOp, SourceFile, analyze, parse_source};
use aether_middle::{
    PlaceBase, Rvalue, SsaOp, SsaOperand, SsaPlaceBase, build_ssa, lower_hir, verify_mir,
    verify_ssa,
};

struct Output(PathBuf);

impl Output {
    fn new(label: &str) -> Self {
        static NEXT: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
        Self(std::env::temp_dir().join(format!(
            "aether-class-ref-v1-{label}-{}-{}",
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

fn compile(source: &str, optimization: OptimizationLevel) -> aether_driver::Compilation {
    compile_source_with_optimization(
        &SourceFile::new("class_handle_references_v1.ae", source),
        &[Emit::Hir, Emit::Mir, Emit::Ssa, Emit::Llvm],
        optimization,
    )
    .unwrap_or_else(|errors| panic!("{source}\n{errors:#?}"))
}

fn status(source: &str, optimization: OptimizationLevel) -> (aether_driver::Compilation, i32) {
    let compilation = compile(source, optimization);
    let output = Output::new("native");
    ClangToolchain::default()
        .with_optimization(optimization)
        .link_executable(&compilation.llvm, &output.0)
        .unwrap();
    let code = Command::new(&output.0)
        .status()
        .unwrap()
        .code()
        .unwrap_or(-1);
    (compilation, code)
}

fn instrument_object_counts(llvm: &str, result: i64, expected: [u64; 4]) -> String {
    let names = [
        "object_alloc",
        "object_retain",
        "object_release",
        "object_destroy",
    ];
    let mut guard = format!(
        "  %class_ref_result_ok = icmp eq i32 %process_status, {result}\n  %class_ref_status_0 = select i1 %class_ref_result_ok, i32 0, i32 90\n"
    );
    let mut last = "class_ref_status_0".to_owned();
    for (index, (name, count)) in names.iter().zip(expected).enumerate() {
        let failure = 91 + index;
        writeln!(
            guard,
            "  %class_ref_count_{index} = load i64, ptr @aether_{name}_count\n  %class_ref_ok_{index} = icmp eq i64 %class_ref_count_{index}, {count}\n  %class_ref_prior_ok_{index} = icmp eq i32 %{last}, 0\n  %class_ref_count_status_{index} = select i1 %class_ref_ok_{index}, i32 0, i32 {failure}\n  %class_ref_status_{failure} = select i1 %class_ref_prior_ok_{index}, i32 %class_ref_count_status_{index}, i32 %{last}"
        )
        .unwrap();
        last = format!("class_ref_status_{failure}");
    }
    writeln!(guard, "  ret i32 %{last}").unwrap();
    llvm.replace("  ret i32 %process_status", &guard)
}

fn llvm_status(llvm: &str, optimization: OptimizationLevel) -> i32 {
    let output = Output::new("instrumented");
    ClangToolchain::default()
        .with_optimization(optimization)
        .link_executable(llvm, &output.0)
        .unwrap();
    Command::new(&output.0)
        .status()
        .unwrap()
        .code()
        .unwrap_or(-1)
}

fn rejected(source: &str) -> String {
    compile_source_with_optimization(
        &SourceFile::new("class_handle_references_v1_negative.ae", source),
        &[Emit::Hir],
        OptimizationLevel::O0,
    )
    .expect_err(source)
    .into_iter()
    .map(|diagnostic| format!("{} {}", diagnostic.code, diagnostic.message))
    .collect::<Vec<_>>()
    .join("\n")
}

const COUNTER: &str = r"
class Counter {
    public int value;
    public init(int value) { this.value = value; }
    public int get() { return value; }
    public mut int increment() { value = value + 1; return value; }
}
";

#[test]
fn explicit_implicit_method_field_identity_and_forwarding_run_at_o0_o2() {
    let source = format!(
        r"{COUNTER}
int read(ref Counter value) {{ return (*value).get() + (*value).value; }}
int forward(ref Counter value) {{ return read(value); }}
bool same(ref Counter left, ref Counter right) {{ return *left == *right; }}
alias Counted = Counter;
int main() {{
    Counter owner = Counter(7);
    ref Counter first = &owner;
    ref Counter second = &owner;
    ref Counted through_alias = &owner;
    if (!same(first, second)) {{ return 1; }}
    if (read(&owner) != 14) {{ return 2; }}
    if (read(owner) != 14) {{ return 3; }}
    if (forward(first) != 14) {{ return 4; }}
    if (forward(through_alias) != 14) {{ return 5; }}
    return 0;
}}"
    );
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        let (compilation, code) = status(&source, optimization);
        assert_eq!(code, 0);
        let hir = &compilation.dumps[&Emit::Hir];
        assert!(hir.contains("BorrowedHandleView"));
        assert!(hir.contains("BorrowedReceiver"));
        assert!(hir.contains("CallScopedSharedBorrow"));
        assert!(compilation.dumps[&Emit::Mir].contains("EndBorrow"));
        assert!(compilation.dumps[&Emit::Ssa].contains("EndBorrow"));
        assert!(compilation.llvm.contains("shared class handle, zero ARC"));
        assert!(!compilation.llvm.contains("noalias"));
    }
}

#[test]
fn mutable_interface_owning_extraction_and_interior_borrows_stay_closed() {
    let cases = [
        format!("{COUNTER} int bad(ref mut Counter c){{return 0;}}int main(){{}}"),
        format!("{COUNTER} int bad(ref mut Counter? c){{return 0;}}int main(){{}}"),
        format!("{COUNTER} Counter bad(ref Counter c){{return *c;}}int main(){{}}"),
        format!("{COUNTER} int take(Counter c){{return 0;}}int bad(ref Counter c){{return take(*c);}}int main(){{}}"),
        format!("{COUNTER} int bad(ref Counter c){{(*c).value=2;return 0;}}int main(){{}}"),
        "interface I{int get();} int bad(ref I value){return 0;} int main(){}".into(),
        "interface I{int get();} int bad(ref I? value){return 0;} int main(){}".into(),
        "class C{Buffer<int> data;public init(Buffer<int> data){this.data=data;}}int bad(ref C c){ref Buffer<int> x=&(*c).data;return 0;}int main(){}".into(),
        "class C{Buffer<int> data;public init(Buffer<int> data){this.data=data;}}int main(){C c=C(Buffer<int>(1,0));ref Buffer<int> x=&c.data;return 0;}".into(),
        "class C{Buffer<int> data;public init(Buffer<int> data){this.data=data;}}int main(){C c=C(Buffer<int>(1,0));ref int x=&c.data[0];return 0;}".into(),
        "class C{Buffer<int> data;public init(Buffer<int> data){this.data=data;}}int bad(ref C c){ref int x=&(*c).data[0];return 0;}int main(){}".into(),
    ];
    for source in cases {
        assert!(
            !rejected(&source).is_empty(),
            "unexpectedly accepted: {source}"
        );
    }
}

#[test]
fn inheritance_nullable_temporary_aliases_and_unwind_run_at_o0_o2() {
    let inheritance = r"
open class Animal { public init(){} public open int sound(){return 1;} public int age(){return 3;} }
class Dog:Animal { public init():base(){} public override int sound(){return 7;} }
int derived(ref Dog dog){return (*dog).sound()+(*dog).age();}
int base(ref Animal animal){return (*animal).sound();}
int main(){Dog owner=Dog();ref Dog borrowed=&owner;if(derived(borrowed)!=10){return 1;}if(base(borrowed)!=7){return 2;}return 0;}
";
    let nullable = r"
class C { public init(){} }
bool absent(ref C? value){return *value==null;}
int main(){C? none=null;C? some=C();if(!absent(none)){return 1;}if(absent(&some)){return 2;}return 0;}
";
    let temporary_and_aliases = format!(
        r"{COUNTER}
int read(ref Counter value){{return (*value).get();}}
int main(){{Counter owner=Counter(5);Counter twin=owner;ref Counter a=&owner;ref Counter b=&twin;if(read(a)+read(b)!=10){{return 1;}}if(read(Counter(9))!=9){{return 2;}}return 0;}}"
    );
    let unwind = format!(
        r"open class Problem:Exception{{public init(){{}}}}{COUNTER}
int fail(ref Counter value){{int seen=(*value).get();throw Problem();}}
int read(ref Counter value){{return (*value).get();}}
int main(){{Counter owner=Counter(8);try{{fail(owner);}}catch(Problem error){{return read(owner)-8;}}return 3;}}"
    );

    for source in [inheritance, nullable, &temporary_and_aliases, &unwind] {
        for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
            let (compilation, code) = status(source, optimization);
            assert_eq!(code, 0, "{source}");
            assert!(!compilation.llvm.contains("noalias"));
            if source == inheritance {
                assert!(compilation.dumps[&Emit::Hir].contains("BorrowedClassUpcast"));
            }
            if source == nullable {
                assert!(compilation.llvm.contains("getelementptr inbounds i8"));
            }
            if source == unwind {
                assert!(compilation.dumps[&Emit::Mir].contains("EndBorrow"));
                assert!(compilation.dumps[&Emit::Ssa].contains("EndBorrow"));
            }
        }
    }
}

#[test]
fn combined_owning_upcast_borrow_and_mutating_borrowed_receiver_are_rejected() {
    let hierarchy = r"
open class Base{public init(){}public int get(){return 1;}}
class Derived:Base{public init():base(){}}
int base(ref Base value){return (*value).get();}
int main(){Derived value=Derived();return base(value);}
";
    assert!(rejected(hierarchy).contains("implicit shared argument borrow requires exact"));

    let mutation = format!(
        "{COUNTER} int bad(ref Counter value){{return (*value).increment();}}int main(){{}}"
    );
    assert!(rejected(&mutation).contains("mut method requires"));

    let unrelated = r"
class Left{public init(){}}
class Right{public init(){}}
int read(ref Left value){return 0;}
int bad(ref Right value){return read(value);}
int main(){}
";
    assert!(!rejected(unrelated).is_empty());

    let nullable_misuse = r"
class C{public init(){}public int get(){return 1;}}
int bad(ref C? value){return (*value).get();}
int main(){}
";
    assert!(!rejected(nullable_misuse).is_empty());
}

#[test]
fn borrow_receiver_forwarding_upcast_and_temporary_add_zero_arc() {
    let cases = [
        (
            format!(
            "{COUNTER} int read(ref Counter value){{return (*value).get();}}int main(){{Counter owner=Counter(6);return read(owner);}}"
        ),
            6,
            [1, 0, 1, 1],
        ),
        (
            format!(
            "{COUNTER} int read(ref Counter value){{return (*value).get();}}int forward(ref Counter value){{return read(value);}}int main(){{Counter owner=Counter(6);return forward(&owner);}}"
        ),
            6,
            [1, 0, 1, 1],
        ),
        (
            "open class Base{public init(){}public open int get(){return 1;}}class Derived:Base{public init():base(){}public override int get(){return 6;}}int read(ref Base value){return (*value).get();}int main(){Derived owner=Derived();ref Derived value=&owner;return read(value);}".into(),
            6,
            [1, 0, 1, 1],
        ),
        (
            format!(
            "{COUNTER} int read(ref Counter value){{return (*value).get();}}int main(){{return read(Counter(6));}}"
        ),
            6,
            [1, 0, 1, 1],
        ),
        (
            format!(
                "open class Problem:Exception{{public init(){{}}}}{COUNTER}int fail(ref Counter value){{int seen=(*value).get();throw Problem();}}int outer(ref Counter value){{return fail(value);}}int read(ref Counter value){{return (*value).get();}}int main(){{Counter owner=Counter(6);try{{outer(owner);}}catch(Problem error){{return read(owner)-6;}}return 4;}}"
            ),
            0,
            [2, 1, 3, 2],
        ),
        (
            format!(
                "open class Problem:Exception{{public init(){{}}}}{COUNTER}int fail(){{throw Problem();}}int main(){{Counter owner=Counter(6);try{{fail();}}catch(Problem error){{return 0;}}return 4;}}"
            ),
            0,
            [2, 1, 3, 2],
        ),
    ];
    for (source, result, expected) in cases {
        for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
            let compilation = compile(&source, optimization);
            let llvm = instrument_object_counts(&compilation.llvm, result, expected);
            assert_eq!(llvm_status(&llvm, optimization), 0, "{source}");
            assert!(!compilation.llvm.contains("aether_borrow_"));
        }
    }
}

#[test]
fn active_anchor_rebind_and_reference_escape_are_rejected() {
    let rebind = format!(
        "{COUNTER} int read(ref Counter value){{return (*value).get();}}int main(){{Counter owner=Counter(1);ref Counter borrowed=&owner;owner=Counter(2);return read(borrowed);}}"
    );
    assert!(rejected(&rebind).contains("cannot replace"));

    let escaping_return =
        format!("{COUNTER} ref Counter bad(ref Counter value){{return value;}}int main(){{}}");
    assert!(!rejected(&escaping_return).is_empty());
}

#[test]
fn borrowed_class_metadata_is_verified_again_in_mir_and_ssa() {
    let source = format!(
        "{COUNTER} int read(ref Counter value){{return (*value).get();}}int main(){{Counter owner=Counter(1);return read(owner)-1;}}"
    );
    let hir = analyze(parse_source(&SourceFile::new("class_ref_corruption.ae", &source)).unwrap())
        .unwrap();
    let raw_mir = lower_hir(hir);
    let valid_mir = verify_mir(raw_mir.clone()).unwrap();

    let mut bad_mir = raw_mir;
    let operation = bad_mir
        .functions
        .iter_mut()
        .flat_map(|function| &mut function.blocks)
        .flat_map(|block| &mut block.instructions)
        .find_map(|instruction| match &mut instruction.value {
            Rvalue::Class(operation)
                if matches!(operation.as_ref(), ClassOp::BorrowedHandleView { .. }) =>
            {
                Some(operation)
            }
            _ => None,
        })
        .unwrap();
    let ClassOp::BorrowedHandleView { class, .. } = operation.as_mut() else {
        unreachable!()
    };
    *class = ClassId(999);
    assert!(verify_mir(bad_mir).is_err());

    let raw_ssa = build_ssa(&valid_mir);
    verify_ssa(raw_ssa.clone()).unwrap();
    let mut bad_ssa = raw_ssa;
    let operation = bad_ssa
        .functions
        .iter_mut()
        .flat_map(|function| &mut function.blocks)
        .flat_map(|block| &mut block.instructions)
        .find_map(|instruction| match &mut instruction.op {
            SsaOp::Class(operation)
                if matches!(operation.as_ref(), ClassOp::BorrowedReceiver { .. }) =>
            {
                Some(operation)
            }
            _ => None,
        })
        .unwrap();
    let ClassOp::BorrowedReceiver { class, .. } = operation.as_mut() else {
        unreachable!()
    };
    *class = ClassId(999);
    assert!(verify_ssa(bad_ssa).is_err());
}

#[test]
fn mir_rejects_class_anchor_cleanup_before_end_borrow() {
    let source = format!(
        "{COUNTER} int read(ref Counter value){{return (*value).get();}}int main(){{Counter owner=Counter(1);return read(owner)-1;}}"
    );
    let hir =
        analyze(parse_source(&SourceFile::new("class_ref_anchor.ae", &source)).unwrap()).unwrap();
    let raw_mir = lower_hir(hir);
    verify_mir(raw_mir.clone()).unwrap();

    let mut bad_mir = raw_mir;
    let (reference, anchor) = bad_mir
        .functions
        .iter()
        .flat_map(|function| &function.blocks)
        .flat_map(|block| &block.instructions)
        .find_map(
            |instruction| match (&instruction.destination.base, &instruction.value) {
                (
                    PlaceBase::Local(reference),
                    Rvalue::Borrow {
                        place,
                        call: Some(_),
                        ..
                    },
                ) => match place.base {
                    PlaceBase::Local(anchor) => Some((*reference, anchor)),
                    _ => None,
                },
                _ => None,
            },
        )
        .unwrap();
    let mut cleanup = None;
    for function in &mut bad_mir.functions {
        for block in &mut function.blocks {
            if let Some(index) = block.instructions.iter().position(|instruction| {
                matches!(&instruction.value, Rvalue::Drop { owner }
                    if matches!(owner.base, PlaceBase::Local(local) if local == anchor))
            }) {
                cleanup = Some(block.instructions.remove(index));
                break;
            }
        }
        if cleanup.is_some() {
            break;
        }
    }
    let cleanup = cleanup.unwrap();
    let end_block = bad_mir
        .functions
        .iter_mut()
        .flat_map(|function| &mut function.blocks)
        .find(|block| {
            block.instructions.iter().any(|instruction| {
                matches!(&instruction.value, Rvalue::EndBorrow { reference: aether_middle::Operand::Local(local), .. } if *local == reference)
            })
        })
        .unwrap();
    let end = end_block
        .instructions
        .iter()
        .position(|instruction| {
            matches!(&instruction.value, Rvalue::EndBorrow { reference: aether_middle::Operand::Local(local), .. } if *local == reference)
        })
        .unwrap();
    end_block.instructions.insert(end, cleanup);
    let errors = verify_mir(bad_mir).unwrap_err();
    assert!(format!("{errors:?}").contains("class-handle borrow anchor"));
}

#[test]
fn ssa_rejects_class_anchor_cleanup_before_end_borrow() {
    let source = format!(
        "{COUNTER} int read(ref Counter value){{return (*value).get();}}int main(){{Counter owner=Counter(1);return read(owner)-1;}}"
    );
    let hir =
        analyze(parse_source(&SourceFile::new("class_ref_anchor.ae", &source)).unwrap()).unwrap();
    let valid_mir = verify_mir(lower_hir(hir)).unwrap();
    let raw_ssa = build_ssa(&valid_mir);
    verify_ssa(raw_ssa.clone()).unwrap();
    let mut bad_ssa = raw_ssa;
    let (reference, anchor) = bad_ssa
        .functions
        .iter()
        .flat_map(|function| &function.blocks)
        .flat_map(|block| &block.instructions)
        .find_map(|instruction| match &instruction.op {
            SsaOp::Borrow {
                place,
                call: Some(_),
                ..
            } => Some((instruction.result, place.clone())),
            _ => None,
        })
        .unwrap();
    assert!(matches!(
        anchor.base,
        SsaPlaceBase::Value(SsaOperand::Value(_)) | SsaPlaceBase::MemoryLocal(_)
    ));
    let mut cleanup = None;
    for function in &mut bad_ssa.functions {
        for block in &mut function.blocks {
            if let Some(index) = block.instructions.iter().position(|instruction| {
                matches!(&instruction.op, SsaOp::Drop { owner }
                    if owner.base == anchor.base && owner.projections == anchor.projections)
            }) {
                cleanup = Some(block.instructions.remove(index));
                break;
            }
        }
        if cleanup.is_some() {
            break;
        }
    }
    let cleanup = cleanup.unwrap();
    let end_block = bad_ssa
        .functions
        .iter_mut()
        .flat_map(|function| &mut function.blocks)
        .find(|block| {
            block.instructions.iter().any(|instruction| {
                matches!(&instruction.op, SsaOp::EndBorrow { reference: SsaOperand::Value(value), .. } if *value == reference)
            })
        })
        .unwrap();
    let end = end_block
        .instructions
        .iter()
        .position(|instruction| {
            matches!(&instruction.op, SsaOp::EndBorrow { reference: SsaOperand::Value(value), .. } if *value == reference)
        })
        .unwrap();
    end_block.instructions.insert(end, cleanup);
    let errors = verify_ssa(bad_ssa).unwrap_err();
    assert!(format!("{errors:?}").contains("class-handle borrow anchor"));
}
