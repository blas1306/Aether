//! OOP-OWNING-STRING-FIELDS-V1 qualification.

use aether_driver::{Emit, OptimizationLevel, compile_source_with_optimization};
use aether_frontend::{ClassOp, SourceFile, TypeId, analyze, parse_source};
use aether_middle::{Rvalue, SsaOp, build_ssa, lower_hir, verify_mir, verify_ssa};
use std::{fs, path::PathBuf, process::Command};

struct Directory(PathBuf);

impl Directory {
    fn new() -> Self {
        static NEXT: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
        let path = std::env::temp_dir().join(format!(
            "aether-owning-string-fields-v1-{}-{}",
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

fn source() -> &'static str {
    r#"
int size(ref string value) { return int(byteLength(*value)); }
string heap(string left, string right) { return left + right; }
open class Base {
    public string title;
    public init(string value) { title = value; }
    public string readBase() { return title; }
}
class Label : Base {
    int marker;
    public string text;
    public init(string first, string second) : base(first) { marker = 7; text = second; }
    public string read() { return text; }
    public int borrowed() { return size(text); }
    public mut int replace(string next) { text = next; return marker; }
}
int main() {
    string left = heap("h", "é");
    Label label = Label(left, "A\0B");
    string before = label.read();
    Label other = label;
    if (label.borrowed() != 3) { return 1; }
    if (label.replace(left) != 7) { return 2; }
    string after = other.read();
    string inherited = label.readBase();
    if (byteLength(before) != 3 || byteLength(after) != 3 || byteLength(inherited) != 3) { return 3; }
    label.replace(label.text);
    return 0;
}
"#
}

fn compile(optimization: OptimizationLevel) -> aether_driver::Compilation {
    compile_source_with_optimization(
        &SourceFile::new("owning_string_fields.ae", source()),
        &[Emit::Hir, Emit::Mir, Emit::Ssa],
        optimization,
    )
    .unwrap_or_else(|diagnostics| panic!("{diagnostics:#?}"))
}

fn execute(llvm: &str, optimization: OptimizationLevel) {
    let directory = Directory::new();
    let ir = directory.0.join("program.ll");
    let executable = directory.0.join("program");
    fs::write(&ir, llvm).unwrap();
    let opt = match optimization {
        OptimizationLevel::O0 => "-O0",
        OptimizationLevel::O2 => "-O2",
    };
    let output = Command::new("clang")
        .args(["-Wno-override-module", opt, "-x", "ir"])
        .arg(&ir)
        .arg("-o")
        .arg(&executable)
        .arg("-lstdc++")
        .output()
        .unwrap();
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    assert_eq!(Command::new(executable).status().unwrap().code(), Some(0));
}

#[test]
fn aliases_borrows_replacement_inheritance_utf8_and_nul_run_o0_o2() {
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        let compilation = compile(optimization);
        for phase in [Emit::Hir, Emit::Mir, Emit::Ssa] {
            assert!(compilation.dumps[&phase].contains("StringFieldAlias"));
        }
        let alias = compilation
            .llvm
            .find("call void @aether_string_retain")
            .unwrap();
        assert!(compilation.llvm[alias..].contains("call void @aether_drop_str"));
        let replacement = compilation.llvm.find("%old").unwrap();
        let replacement_ir = &compilation.llvm[replacement..];
        assert!(
            replacement_ir.find("store ptr").unwrap()
                < replacement_ir.find("call void @aether_drop_str").unwrap()
        );
        execute(&compilation.llvm, optimization);
    }
}

#[test]
fn partial_init_rhs_and_post_commit_unwind_and_interface_release_run_o0_o2() {
    let source = r#"
open class Problem : Exception { public init() {} }
void fail() { throw Problem(); }
string failString() { throw Problem(); }
interface Readable { string read(); }
class Record : Readable {
    string first;
    Buffer<int> data;
    string second;
    public string third;
    public init(int mode) {
        first = "";
        data = Buffer<int>(1, 7);
        if (mode == 1) { string impossible = failString(); }
        second = "A";
        third = "B";
        if (mode == 2) { fail(); }
    }
    public string read() { return first; }
    public string readSecond() { return second; }
    public mut int failBeforeCommit() { first = failString(); return 9; }
    public mut int commitThenFail(string next) { first = next; fail(); return 9; }
}
int main() {
    try { Record partial = Record(1); } catch (Problem error) {}
    try { Record complete = Record(2); } catch (Problem error) {}
    Record record = Record(0);
    try { record.failBeforeCommit(); } catch (Problem error) {
        if (byteLength(record.read()) != 0) { return 1; }
    }
    string next = "new" + " value";
    try { record.commitThenFail(next); } catch (Problem error) {
        if (record.read() != next) { return 2; }
    }
    Readable erased = record;
    string throughInterface = erased.read();
    if (throughInterface != next || record.readSecond() != "A" || record.third != "B") { return 3; }
    return 0;
}
"#;
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        let compilation = compile_source_with_optimization(
            &SourceFile::new("string_field_unwind.ae", source),
            &[Emit::Hir, Emit::Mir, Emit::Ssa],
            optimization,
        )
        .unwrap_or_else(|diagnostics| panic!("{diagnostics:#?}"));
        assert!(compilation.llvm.contains("aether_drop_str"));
        assert!(compilation.llvm.contains("aether_drop_B"));
        execute(&compilation.llvm, optimization);
    }
}

#[test]
fn closed_owning_storage_and_interior_reference_cases_stay_rejected() {
    let cases = [
        "struct S{string value;}class C{S value;public init(S v){value=v;}}int main(){return 0;}",
        "class C{string value;public init(){value=\"x\";}public int bad(){ref string r=&value;return 0;}}int main(){return 0;}",
        "class C{string value;public init(bool yes){if(yes){value=\"x\";}}}int main(){return 0;}",
        "class C{string value;public init(){string x=value;value=\"x\";}}int main(){return 0;}",
        "class C{Buffer<string> value;public init(){value=Buffer<string>(1,\"x\");}}int main(){return 0;}",
    ];
    for text in cases {
        assert!(
            compile_source_with_optimization(
                &SourceFile::new("negative.ae", text),
                &[],
                OptimizationLevel::O0,
            )
            .is_err(),
            "unexpected acceptance: {text}"
        );
    }
}

#[test]
fn mir_and_ssa_reject_copy_load_corruption_of_string_field_alias() {
    let file = SourceFile::new("corruption.ae", source());
    let hir = analyze(parse_source(&file).unwrap()).unwrap();
    let valid_mir = lower_hir(hir);
    let mut bad_mir = valid_mir.clone();
    let instruction = bad_mir
        .functions
        .iter_mut()
        .flat_map(|function| &mut function.blocks)
        .flat_map(|block| &mut block.instructions)
        .find(|instruction| matches!(&instruction.value, Rvalue::Class(op) if matches!(op.as_ref(), ClassOp::StringFieldAlias { .. })))
        .unwrap();
    if let Rvalue::Class(op) = &mut instruction.value {
        let ClassOp::StringFieldAlias { receiver, field } = op.as_ref() else {
            unreachable!()
        };
        **op = ClassOp::FieldRead {
            receiver: receiver.clone(),
            field: *field,
        };
    }
    assert!(verify_mir(bad_mir).is_err());

    let valid_mir = verify_mir(valid_mir).unwrap();
    let mut bad_ssa = build_ssa(&valid_mir);
    let instruction = bad_ssa
        .functions
        .iter_mut()
        .flat_map(|function| &mut function.blocks)
        .flat_map(|block| &mut block.instructions)
        .find(|instruction| matches!(&instruction.op, SsaOp::Class(op) if matches!(op.as_ref(), ClassOp::StringFieldAlias { .. })))
        .unwrap();
    if let SsaOp::Class(op) = &mut instruction.op {
        let ClassOp::StringFieldAlias { receiver, field } = op.as_ref() else {
            unreachable!()
        };
        **op = ClassOp::FieldRead {
            receiver: receiver.clone(),
            field: *field,
        };
        instruction.ty = TypeId::STRING;
    }
    assert!(verify_ssa(bad_ssa).is_err());
}
