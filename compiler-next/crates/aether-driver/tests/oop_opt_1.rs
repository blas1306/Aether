//! OOP-OPT-1: logical ownership, physical emission and adversarial proofs.
use aether_backend_llvm::{TargetDescriptor, emit_llvm};
use aether_driver::{Emit, OptimizationLevel, compile_source_with_optimization};
use aether_frontend::{ClassId, ClassOp, SourceFile, analyze, parse_source};
use aether_middle::{
    SsaIr, SsaOp, SsaOperand, VerifiedSsa, build_ssa, lower_hir, optimize_oop, verify_mir,
    verify_ssa,
};
use std::{fmt::Write, fs, process::Command};

const C: &str = "interface I{int get();mut int inc();}class C:I{int n;public init(int n){this.n=n;}public int get(){return n;}public mut int inc(){n=n+1;return n;}}";
fn raw(source: &str) -> SsaIr {
    build_ssa(
        &verify_mir(lower_hir(
            analyze(parse_source(&SourceFile::new("opt.ae", source)).unwrap()).unwrap(),
        ))
        .unwrap(),
    )
}
fn optimized(source: &str) -> VerifiedSsa {
    optimize_oop(&verify_ssa(raw(source)).unwrap()).unwrap()
}
fn llvm(ssa: &VerifiedSsa) -> String {
    emit_llvm(ssa, &TargetDescriptor::linux_x86_64())
}
fn native(ir: &str, result: i64, counts: [u64; 7]) {
    static NEXT: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
    let dir = std::env::temp_dir().join(format!(
        "oop-opt-{}-{}",
        std::process::id(),
        NEXT.fetch_add(1, std::sync::atomic::Ordering::Relaxed)
    ));
    fs::create_dir(&dir).unwrap();
    let names = [
        "object_alloc",
        "object_retain",
        "object_release",
        "object_destroy",
        "object_buffer_drop",
        "heap_alloc",
        "heap_free",
    ];
    let mut guard = format!("  %ok0 = icmp eq i32 %process_status, {result}\n");
    for (i, (name, expected)) in names.iter().zip(counts).enumerate() {
        writeln!(guard, "  %count{i} = load i64, ptr @aether_{name}_count\n  %eq{i} = icmp eq i64 %count{i}, {expected}\n  %ok{} = and i1 %ok{i}, %eq{i}", i+1).unwrap();
    }
    guard.push_str("  %status = select i1 %ok7, i32 0, i32 99\n  ret i32 %status");
    fs::write(
        dir.join("test.ll"),
        ir.replace("  ret i32 %process_status", &guard),
    )
    .unwrap();
    for opt in ["-O0", "-O2"] {
        let output = Command::new("clang")
            .args(["-Wno-override-module", opt])
            .arg(dir.join("test.ll"))
            .arg("-o")
            .arg(dir.join("test"))
            .output()
            .unwrap();
        assert!(
            output.status.success(),
            "{}",
            String::from_utf8_lossy(&output.stderr)
        );
        assert_eq!(
            Command::new(dir.join("test")).status().unwrap().code(),
            Some(0),
            "{opt} expected result={result}, counts={counts:?}"
        );
    }
    fs::remove_dir_all(dir).unwrap();
}

#[test]
fn physical_arc_cases_preserve_native_results_and_final_cleanup() {
    let cases = [
        (
            "class read",
            "int main(){C c=C(7);return c.get();}",
            7,
            1,
            0,
        ),
        ("class mut", "int main(){C c=C(7);return c.inc();}", 8, 1, 0),
        (
            "interface read",
            "int main(){I i=C(7);return i.get();}",
            7,
            1,
            0,
        ),
        (
            "interface mut lvalue adaptation",
            "int main(){C c=C(7);I i=c;return i.inc();}",
            8,
            2,
            1,
        ),
        (
            "class alias",
            "int main(){C c=C(7);C a=c;a.inc();return c.get();}",
            8,
            3,
            1,
        ),
        (
            "interface alias",
            "int main(){I i=C(7);I a=i;a.inc();return i.get();}",
            8,
            3,
            1,
        ),
        ("fresh receiver", "int main(){return C(7).get();}", 7, 0, 0),
        (
            "class parameter",
            "int read(C c){return c.get();}int main(){C c=C(7);return read(c);}",
            7,
            2,
            1,
        ),
        (
            "class return",
            "C make(){C c=C(7);return c;}int main(){C c=make();return c.get();}",
            7,
            2,
            1,
        ),
        (
            "unknown interface parameter",
            "int read(I i){return i.get();}int main(){I i=C(7);return read(i);}",
            7,
            2,
            2,
        ),
        (
            "opaque interface return",
            "I make(){I i=C(7);return i;}int main(){I i=make();return i.get();}",
            7,
            2,
            2,
        ),
    ];
    for (name, body, result, before, after) in cases {
        let source = format!("{C}{body}");
        let semantic = verify_ssa(raw(&source)).unwrap();
        let opt = optimize_oop(&semantic).unwrap();
        let physical = llvm(&opt);
        assert_eq!(
            llvm(&semantic)
                .matches("call void @aether_object_retain(")
                .count() as u64,
            before,
            "{name}"
        );
        assert_eq!(
            physical.matches("call void @aether_object_retain(").count() as u64,
            after,
            "{name}"
        );
        native(&physical, result, [1, after, after + 1, 1, 0, 1, 1]);
        // The transformed SSA retains every semantic instruction and obligation.
        for (a, b) in semantic
            .as_ssa()
            .functions
            .iter()
            .zip(&opt.as_ssa().functions)
        {
            assert_eq!(a.blocks, b.blocks, "{name}");
        }
        assert_eq!(optimize_oop(&opt).unwrap(), opt, "idempotent {name}");
    }
    let source = "interface I{int get();}class C:I{Buffer<int> b;public init(Buffer<int> b){this.b=b;}public int get(){return 7;}}int main(){I i=C(Buffer<int>(2,7));return i.get();}";
    native(&llvm(&optimized(source)), 7, [1, 0, 1, 1, 1, 2, 2]);
}

#[test]
fn exact_adaptation_alias_phi_and_loop_provenance() {
    for body in [
        "int main(){I i=C(7);return i.get();}",
        "int main(){C c=C(7);I i=c;return i.inc();}",
        "int main(){I i=C(7);I a=i;I b=a;return b.get();}",
        "int main(){I i=C(7);if(true){i=C(8);}else{i=C(9);}return i.get();}",
        "int main(){I i=C(7);int n=0;while(n<2){i=C(n);n=n+1;}return i.get();}",
    ] {
        let opt = optimized(&format!("{C}{body}"));
        let ir = llvm(&opt);
        assert!(ir.contains("OOP-OPT-1 devirtualization"), "{body}");
        assert!(!ir.contains(" = load ptr, ptr %slot"), "{body}");
        assert!(!ir.contains(" %target"), "{body}");
        assert!(opt.dump().contains("requirement: RequirementId"));
    }
}

#[test]
fn mixed_and_unknown_provenance_cannot_authorize_direct_dispatch() {
    let d = "class D:I{public int get(){return 9;}public mut int inc(){return 10;}}";
    for body in [
        "int main(){I i=C(7);if(true){i=C(8);}else{i=D();}return i.get();}",
        "int read(I i){return i.get();}int main(){I i=C(7);return read(i);}",
        "I make(){return C(7);}int main(){I i=make();return i.get();}",
        "int read(I i,bool flag){if(flag){i=C(1);}return i.get();}int main(){I i=C(7);return read(i,false);}",
        "int main(){I i=C(7);int n=0;while(n<2){i=D();n=n+1;}return i.get();}",
    ] {
        let opt = optimized(&format!("{C}{d}{body}"));
        assert!(llvm(&opt).contains(" = load ptr, ptr %slot"), "{body}");
        let mut bad = opt.as_ssa().clone();
        let method = bad
            .signatures
            .iter()
            .find(|s| {
                bad.types
                    .class_method(s.function_id)
                    .is_some_and(|(c, m)| c == ClassId(0) && m.name == "get")
            })
            .unwrap()
            .id;
        let f = bad.functions.iter_mut().find(|f| f.blocks.iter().flat_map(|b| &b.instructions).any(|i| matches!(&i.op, SsaOp::Class(op) if matches!(op.as_ref(), ClassOp::InterfaceCall{..})))).unwrap();
        let i = f.blocks.iter().flat_map(|b| &b.instructions).find(|i| matches!(&i.op, SsaOp::Class(op) if matches!(op.as_ref(), ClassOp::InterfaceCall{..}))).unwrap();
        let SsaOp::Class(op) = &i.op else {
            unreachable!()
        };
        let ClassOp::InterfaceCall { requirement, .. } = op.as_ref() else {
            unreachable!()
        };
        f.oop_optimizations.direct.insert(
            i.result,
            aether_middle::Devirtualization {
                requirement: *requirement,
                class: ClassId(0),
                method,
            },
        );
        assert!(verify_ssa(bad).is_err(), "forged exact provenance: {body}");
    }
}

#[test]
fn corrupted_physical_decisions_and_logical_pairs_fail_closed() {
    let opt = optimized(&format!("{C}int main(){{I i=C(7);return i.get();}}"));
    for mutation in 0..8 {
        let mut bad = opt.as_ssa().clone();
        let f = &mut bad.functions[bad.entry.0 as usize];
        let (&acquire, pair) = f.oop_optimizations.arc.iter().next().unwrap();
        let release = pair.release;
        match mutation {
            0 => f.oop_optimizations.arc.get_mut(&acquire).unwrap().release = acquire,
            1 => f.oop_optimizations.arc.get_mut(&acquire).unwrap().owner = acquire,
            2 => {
                f.blocks
                    .iter_mut()
                    .flat_map(|b| &mut b.instructions)
                    .find(|i| i.result == release)
                    .unwrap()
                    .op = SsaOp::Use(SsaOperand::Bool(true));
            }
            3 => {
                let i = f
                    .blocks
                    .iter_mut()
                    .flat_map(|b| &mut b.instructions)
                    .find(|i| i.result == acquire)
                    .unwrap();
                let SsaOp::Class(op) = &mut i.op else {
                    unreachable!()
                };
                let ClassOp::ReceiverKeepalive { transfer, .. } = op.as_mut() else {
                    unreachable!()
                };
                *transfer = true;
            }
            4 => {
                f.oop_optimizations
                    .direct
                    .values_mut()
                    .next()
                    .unwrap()
                    .class = ClassId(99);
            }
            5 => {
                f.oop_optimizations
                    .direct
                    .values_mut()
                    .next()
                    .unwrap()
                    .method = bad.entry;
            }
            6 => {
                f.oop_optimizations
                    .direct
                    .values_mut()
                    .next()
                    .unwrap()
                    .requirement
                    .index = 1;
            }
            7 => {
                let target = bad
                    .signatures
                    .iter()
                    .find(|s| {
                        bad.types
                            .class_method(s.function_id)
                            .is_some_and(|(_, m)| m.mutable)
                    })
                    .unwrap()
                    .id;
                f.oop_optimizations
                    .direct
                    .values_mut()
                    .next()
                    .unwrap()
                    .method = target;
            }
            _ => unreachable!(),
        }
        assert!(verify_ssa(bad).is_err(), "mutation {mutation}");
    }
}

#[test]
fn recursion_preserves_checked_rc_and_non_oop_llvm_is_identical() {
    let opt = optimized(&format!(
        "{C}int recur(C c,int n){{if(n==0){{return c.get();}}return recur(c,n-1);}}int main(){{C c=C(7);return recur(c,2);}}"
    ));
    assert!(
        opt.as_ssa()
            .functions
            .iter()
            .all(|f| f.oop_optimizations.arc.is_empty())
    );
    for source in [
        "int main(){return 1+2;}",
        "struct P{int x;}int main(){P p=P(7);return p.x;}",
        "int main(){Buffer<int> b=Buffer<int>(2,7);return b[0];}",
        "T id<T>(T x){return x;}int main(){return id(7);}",
        "int main(){Matrix<int> a=[1,2;3,4];Matrix<int> b=a*a;return b[1,1];}",
        "int main(){/* untouched */}",
    ] {
        let source = SourceFile::new("same.ae", source);
        let a = compile_source_with_optimization(&source, &[], OptimizationLevel::O0).unwrap();
        let b =
            compile_source_with_optimization(&source, &[Emit::Ssa], OptimizationLevel::O2).unwrap();
        assert_eq!(a.llvm, b.llvm);
    }
}

#[test]
fn last_receiver_owner_and_stale_replacement_proofs_are_rejected() {
    // Replacement is moved into the receiver/argument interval in MIR because
    // source handle-slot references are intentionally unavailable. No opaque
    // call barrier can mask the need for the old object's keepalive here.
    let source = "interface I{int get(int x);}class C:I{Buffer<int> b;public init(Buffer<int> b){this.b=b;}public int get(int x){return x+2;}}class D:I{public int get(int x){return x+90;}}int main(){I i=C(Buffer<int>(2,7));int n=i.get(3);i=D();return n;}";
    let mut mir =
        lower_hir(analyze(parse_source(&SourceFile::new("replace.ae", source)).unwrap()).unwrap());
    let instructions = &mut mir.functions[mir.entry.0 as usize].blocks[0].instructions;
    let start = instructions.iter().enumerate().filter(|(_, i)| matches!(&i.value, aether_middle::Rvalue::Class(op) if matches!(op.as_ref(), ClassOp::ObjectAlloc{..}))).nth(1).unwrap().0;
    let end = start
        + instructions[start..]
            .iter()
            .position(|i| matches!(i.value, aether_middle::Rvalue::Drop { .. }))
            .unwrap()
        + 1;
    let replacement = instructions.drain(start..end).collect::<Vec<_>>();
    let insertion = instructions.iter().position(|i| matches!(&i.value, aether_middle::Rvalue::Class(op) if matches!(op.as_ref(), ClassOp::ReceiverKeepalive{..}))).unwrap()+1;
    instructions.splice(insertion..insertion, replacement);
    let valid = verify_ssa(build_ssa(&verify_mir(mir).unwrap())).unwrap();
    let opt = optimize_oop(&valid).unwrap();
    let f = &opt.as_ssa().functions[opt.as_ssa().entry.0 as usize];
    assert!(f.oop_optimizations.arc.is_empty());
    assert_eq!(
        f.oop_optimizations.direct.values().next().unwrap().class,
        ClassId(0)
    );
    native(&llvm(&opt), 5, [2, 1, 3, 2, 1, 3, 3]);
    let acquire = f.blocks[0].instructions.iter().find(|i| matches!(&i.op, SsaOp::Class(op) if matches!(op.as_ref(), ClassOp::ReceiverKeepalive{..}))).unwrap();
    let SsaOp::Class(op) = &acquire.op else {
        unreachable!()
    };
    let ClassOp::ReceiverKeepalive {
        source: SsaOperand::Value(owner),
        ..
    } = op.as_ref()
    else {
        unreachable!()
    };
    let release = f.blocks[0].instructions.iter().find(|i| matches!(&i.op, SsaOp::Drop{owner:p} if p.base == aether_middle::SsaPlaceBase::Value(SsaOperand::Value(acquire.result)))).unwrap().result;
    let mut bad = opt.as_ssa().clone();
    bad.functions[bad.entry.0 as usize]
        .oop_optimizations
        .arc
        .insert(
            acquire.result,
            aether_middle::ArcElision {
                release,
                owner: *owner,
            },
        );
    assert!(verify_ssa(bad).is_err(), "cannot elide final live owner");
    let mut bad = opt.as_ssa().clone();
    let target = bad
        .signatures
        .iter()
        .find(|s| {
            bad.types
                .class_method(s.function_id)
                .is_some_and(|(c, m)| c == ClassId(1) && m.name == "get")
        })
        .unwrap()
        .id;
    let decision = bad.functions[bad.entry.0 as usize]
        .oop_optimizations
        .direct
        .values_mut()
        .next()
        .unwrap();
    decision.class = ClassId(1);
    decision.method = target;
    assert!(
        verify_ssa(bad).is_err(),
        "new slot class is not captured receiver class"
    );
    // No concrete-release optimization exists: corrupting the interface owner
    // into another class's value cannot bypass exact typed owner verification.
    let mut bad = opt.as_ssa().clone();
    let wrong = bad
        .types
        .id_of(aether_frontend::TypeData::Class(ClassId(1)))
        .unwrap();
    bad.functions[bad.entry.0 as usize].blocks[0]
        .instructions
        .iter_mut()
        .find(|i| i.result == acquire.result)
        .unwrap()
        .ty = wrong;
    assert!(verify_ssa(bad).is_err());
}

#[test]
fn escaping_alias_and_cross_block_owner_intervals_keep_arc() {
    for body in [
        "C escape(C c){C a=c;return a;}int main(){C c=C(7);C a=escape(c);return a.get();}",
        "int opaque(C c){return 7;}int main(){C c=C(7);C a=c;return opaque(a);}",
        "int main(){C c=C(7);C a=c;if(true){c=C(9);}return a.get();}",
    ] {
        let source = format!("{C}{body}");
        let opt = optimized(&source);
        let raw = opt.as_ssa();
        let mut retained = 0;
        for f in &raw.functions {
            for i in f.blocks.iter().flat_map(|b| &b.instructions) {
                if matches!(&i.op, SsaOp::Class(op) if matches!(op.as_ref(),ClassOp::HandleAlias{..}))
                    && !f.oop_optimizations.arc.contains_key(&i.result)
                {
                    retained += 1;
                }
            }
        }
        // Returning/passing an lvalue creates another Alias: that escaping
        // obligation is retained even if a preceding local alias is removable.
        assert!(retained > 0, "{body}");
        let ir = llvm(&opt);
        let retains = ir.matches("call void @aether_object_retain(").count() as u64;
        let objects = if body.contains("c=C(9)") { 2 } else { 1 };
        native(
            &ir,
            7,
            [
                objects,
                retains,
                objects + retains,
                objects,
                0,
                objects,
                objects,
            ],
        );
    }
}

#[test]
fn final_buffer_destruction_stays_between_observable_checkpoints() {
    let source = "interface I{int get();}class C:I{Buffer<int> b;public init(Buffer<int> b){this.b=b;}public int get(){return 7;}}int checkpoint(int expected){return expected;}int main(){if(true){I i=C(Buffer<int>(2,7));i.get();checkpoint(0);}checkpoint(1);return 0;}";
    let semantic = verify_ssa(raw(source)).unwrap();
    for ssa in [semantic.clone(), optimize_oop(&semantic).unwrap()] {
        let ir = llvm(&ssa);
        let signature = ir
            .lines()
            .find(|line| line.starts_with("define i64 @") && line.contains("_f10_checkpoint("))
            .unwrap();
        let start = ir.find(signature).unwrap() + signature.len();
        let end = start + ir[start..].find("\n}").unwrap();
        let probe = "\nbb0:\n  %destroyed = load i64, ptr @aether_object_destroy_count\n  %buffers = load i64, ptr @aether_object_buffer_drop_count\n  %d = icmp eq i64 %destroyed, %v0\n  %b = icmp eq i64 %buffers, %v0\n  %ok = and i1 %d, %b\n  br i1 %ok, label %good, label %bad\ngood:\n  ret i64 %v0\nbad:\n  call void @llvm.trap()\n  unreachable";
        let instrumented = format!("{}{probe}{}", &ir[..start], &ir[end..]);
        let retains = ir.matches("call void @aether_object_retain(").count() as u64;
        native(&instrumented, 0, [1, retains, retains + 1, 1, 1, 2, 2]);
    }
}

#[test]
fn stale_direct_decision_after_valid_object_replacement_is_rejected() {
    let classes = "interface I{int get();}class C:I{public int get(){return 7;}}class D:I{public int get(){return 9;}}";
    let before = optimized(&format!("{classes}int main(){{I i=C();return i.get();}}"));
    let after = optimized(&format!("{classes}int main(){{I i=D();return i.get();}}"));
    let mut bad = after.as_ssa().clone();
    bad.functions[bad.entry.0 as usize].oop_optimizations.direct = before.as_ssa().functions
        [before.as_ssa().entry.0 as usize]
        .oop_optimizations
        .direct
        .clone();
    assert!(verify_ssa(bad).is_err());
    native(&llvm(&before), 7, [1, 0, 1, 1, 0, 1, 1]);
    native(&llvm(&after), 9, [1, 0, 1, 1, 0, 1, 1]);
}

#[test]
fn native_phi_dispatch_and_receiver_argument_order() {
    let d = "class D:I{public int get(){return 9;}public mut int inc(){return 10;}}";
    let source = format!(
        "{C}{d}int read(bool flag){{I i=C(1);if(flag){{i=C(7);}}else{{i=D();}}return i.get();}}int main(){{return read(true)+read(false);}}"
    );
    native(&llvm(&optimized(&source)), 16, [4, 2, 6, 4, 0, 4, 4]);
    let source = format!(
        "{C}int read(bool flag){{I i=C(1);if(flag){{i=C(7);}}else{{i=C(9);}}return i.get();}}int main(){{return read(true)+read(false);}}"
    );
    native(&llvm(&optimized(&source)), 16, [4, 0, 4, 4, 0, 4, 4]);
    let source = "interface I{mut int add(int x);}class C:I{int n;public init(){n=1;}public mut int add(int x){n=n+x;return n;}public mut int inc(){n=n+1;return n;}}int main(){C c=C();I i=c;return i.add(c.inc());}";
    // Receiver is captured first; argument increments the shared object from 1
    // to 2, then the interface call adds that result and observes 4.
    native(&llvm(&optimized(source)), 4, [1, 1, 2, 1, 0, 1, 1]);
}

#[test]
fn devirtualized_calls_preserve_reference_aggregate_and_owning_results() {
    let cases = [
        (
            "interface I{int read(ref mut int x);}class C:I{public int read(ref mut int x){*x=*x+1;return *x;}}int main(){I i=C();int n=6;return i.read(&mut n);}",
            0,
            1,
        ),
        (
            "struct P{int x;int y;}interface I{P echo(P p);}class C:I{public P echo(P p){return p;}}int main(){I i=C();P p=i.echo(P(3,4));return p.x+p.y;}",
            1,
            1,
        ),
        (
            "interface I{Buffer<int> echo(Buffer<int> b);}class C:I{public Buffer<int> echo(Buffer<int> b){return b;}}int main(){I i=C();Buffer<int> b=i.echo(Buffer<int>(2,7));return b[0];}",
            1,
            2,
        ),
        (
            "interface I{I echo(I i);int get();}class C:I{public I echo(I i){return i;}public int get(){return 7;}}int main(){I i=C();I j=i.echo(i);return j.get();}",
            3,
            1,
        ),
    ];
    for (source, retains, heaps) in cases {
        let ir = llvm(&optimized(source));
        assert!(ir.contains("OOP-OPT-1 devirtualization"));
        native(&ir, 7, [1, retains, retains + 1, 1, 0, heaps, heaps]);
    }
}

#[test]
fn optimized_interface_method_preserves_checked_overflow_trap() {
    let source = format!("{C}int main(){{I i=C(9223372036854775807);return i.inc();}}");
    let semantic = verify_ssa(raw(&source)).unwrap();
    let optimized = optimize_oop(&semantic).unwrap();
    let output = std::env::temp_dir().join(format!("oop-opt-trap-{}", std::process::id()));
    for ssa in [semantic, optimized] {
        for profile in [OptimizationLevel::O0, OptimizationLevel::O2] {
            aether_driver::ClangToolchain::default()
                .with_optimization(profile)
                .link_executable(&llvm(&ssa), &output)
                .unwrap();
            assert!(Command::new(&output).status().unwrap().code().is_none());
        }
    }
    fs::remove_file(output).unwrap();
}
