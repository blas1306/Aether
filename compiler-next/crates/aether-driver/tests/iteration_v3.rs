//! ITERATION-V3 borrowed non-Copy Array/List element qualification.

use std::{fs, path::PathBuf, process::Command};

use aether_driver::{
    ClangToolchain, Emit, OptimizationLevel, build_path, compile_source_with_optimization,
};
use aether_frontend::{IterationBindingCategory, SourceFile, TextOp, analyze, parse_source};
use aether_middle::{Operand, Rvalue, SsaOp, build_ssa, lower_hir, verify_mir, verify_ssa};

struct Directory(PathBuf);

impl Directory {
    fn new() -> Self {
        static NEXT: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
        let path = std::env::temp_dir().join(format!(
            "aether-iteration-v3-{}-{}",
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
        &SourceFile::new("iteration_v3.ae", text),
        &[Emit::Hir, Emit::Mir, Emit::Ssa],
        optimization,
    )
    .unwrap_or_else(|errors| panic!("{text}\n{errors:#?}"))
}

fn execute(text: &str, optimization: OptimizationLevel) -> std::process::Output {
    let compilation = compile(text, optimization);
    let directory = Directory::new();
    let ir = directory.0.join("program.ll");
    let executable = directory.0.join("program");
    fs::write(&ir, &compilation.llvm).unwrap();
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
    Command::new(executable).output().unwrap()
}

fn compile_and_run_text(
    text: &str,
    optimization: OptimizationLevel,
) -> (aether_driver::Compilation, std::process::Output) {
    let directory = Directory::new();
    let input = directory.0.join("main.ae");
    let executable = directory.0.join("program");
    fs::write(&input, text).unwrap();
    let compilation = build_path(
        &input,
        &executable,
        &[Emit::Hir, Emit::Mir, Emit::Ssa, Emit::Llvm],
        &ClangToolchain::default().with_optimization(optimization),
    )
    .unwrap_or_else(|errors| panic!("{text}\n{errors:#?}"));
    let output = Command::new(executable).output().unwrap();
    (compilation, output)
}

fn qualify(text: &str, expected: i32) {
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        assert_eq!(
            execute(text, optimization).status.code(),
            Some(expected),
            "{text}"
        );
    }
}

fn reject(text: &str) {
    assert!(
        compile_source_with_optimization(
            &SourceFile::new("bad_iteration_v3.ae", text),
            &[],
            OptimizationLevel::O0,
        )
        .is_err(),
        "{text}"
    );
}

#[test]
fn inferred_and_explicit_shared_string_borrows_read_exact_bytes() {
    let source = "int main(){Array<string> a={\"A\\0B\",\"hé\"};List<string> b={\"x\",\"yz\"};usize n=0;for(word in a){println(*word);n=n+byteLength(*word);}for(ref string word in b){n=n+byteLength(*word);}if(n==9){return 0;}return 1;}";
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        let output = execute(source, optimization);
        assert_eq!(output.status.code(), Some(0));
        assert_eq!(output.stdout, b"A\0B\nh\xc3\xa9\n");
        let compilation = compile(source, optimization);
        for dump in [Emit::Hir, Emit::Mir, Emit::Ssa] {
            assert!(compilation.dumps[&dump].contains("SharedElementBorrow"));
        }
        assert!(compilation.dumps[&Emit::Hir].contains("ref string"));
    }

    reject("int main(){Array<string> a={\"x\"};for(string x in a){}return 0;}");
    reject("int main(){List<string> a={\"x\"};for(ref mut string x in a){}return 0;}");
}

#[test]
fn borrowed_string_loads_feed_text_ops_in_array_list_and_nested_loops() {
    let source = r#"package iteration_v3_text;
import std.Text;
int main(){
 Array<string> lines={" alpha beta "," gamma "};List<string> more={" delta "," epsilon zeta "};
 string separator=" ";usize bytes=0;
 for(line in lines){
  List<string> words=std.Text.split(*line,separator);
  for(word in words){string trimmed=std.Text.trim(*word);bytes=bytes+byteLength(trimmed);}
 }
 for(line in more){
  List<string> words=std.Text.split(*line,separator);
  for(word in words){string trimmed=std.Text.trim(*word);bytes=bytes+byteLength(trimmed);}
 }
 if(bytes==30){return 0;}return 1;
}"#;
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        let (compilation, output) = compile_and_run_text(source, optimization);
        assert_eq!(output.status.code(), Some(0), "{optimization:?}");
        assert!(compilation.dumps[&Emit::Mir].contains("Trim"));
        assert!(compilation.dumps[&Emit::Mir].contains("Split"));
        assert!(compilation.dumps[&Emit::Mir].contains("SharedElementBorrow"));
        assert!(!compilation.dumps[&Emit::Mir].contains("Alias"));
    }
}

#[test]
fn text_op_still_rejects_a_genuinely_dropped_string_owner() {
    let source =
        "int main(){string value=\"abc\";usize count=byteLength(value);return int(count)-3;}";
    let hir =
        analyze(parse_source(&SourceFile::new("corrupt_text_owner.ae", source)).unwrap()).unwrap();
    let mut mir = lower_hir(hir);
    let function = &mut mir.functions[0];

    let (block_index, instruction_index, owner) =
        function
            .blocks
            .iter()
            .enumerate()
            .find_map(|(block_index, block)| {
                block.instructions.iter().enumerate().find_map(
                    |(instruction_index, instruction)| match &instruction.value {
                        Rvalue::Core(call)
                            if call.function.symbol == aether_frontend::CoreSymbol::ByteLength =>
                        {
                            match call.arguments.as_slice() {
                                [Operand::Local(owner)] => {
                                    Some((block_index, instruction_index, *owner))
                                }
                                _ => None,
                            }
                        }
                        _ => None,
                    },
                )
            })
            .unwrap();
    function.blocks[block_index].instructions[instruction_index].value = Rvalue::Text {
        call_site: aether_frontend::CallSiteId(999),
        op: Box::new(TextOp::CodePointCount {
            value: Operand::Local(owner),
        }),
    };
    let owner_drop = function
        .blocks
        .iter()
        .flat_map(|block| &block.instructions)
        .find(|instruction| {
            matches!(
                &instruction.value,
                Rvalue::Drop { owner: place }
                    if place.base == aether_middle::PlaceBase::Local(owner)
                        && place.projections.is_empty()
            )
        })
        .unwrap()
        .clone();
    function.blocks[block_index]
        .instructions
        .insert(instruction_index, owner_drop);

    let errors = verify_mir(mir).unwrap_err();
    assert_eq!(
        errors[0].message,
        "Text operation uses a moved/dropped owner"
    );
}

#[test]
fn non_copy_aggregate_control_flow_nesting_and_temporaries_compose() {
    qualify(
        "struct Word{string text;int weight;}Array<Word> make(){return {Word(\"a\",2),Word(\"b\",3)};}int main(){int n=0;usize bytes=0;for(word in make()){n=n+(*word).weight;if((*word).weight==2){continue;}}List<string> xs={\"z\"};for(x in xs){for(y in xs){bytes=bytes+byteLength(*y);break;}}if(n==5){if(bytes==1){return 0;}}return 1;}",
        0,
    );
    qualify(
        "List<string> make(){return {\"a\",\"bb\"};}int first(){for(x in make()){if(byteLength(*x)==1){return 0;}return 8;}return 9;}int main(){return first();}",
        0,
    );
    qualify(
        "open class Problem:Exception{public init(){}}List<string> make(){return {\"a\",\"bb\"};}int main(){int n=0;try{for(x in make()){n=n+1;if(byteLength(*x)==2){throw Problem();}}}catch(Problem e){return n-2;}return 9;}",
        0,
    );
    qualify(
        "int main(){List<string> xs={\"a\",\"bb\"};int n=0;for(x in xs){try{if(byteLength(*x)==1){n=n+1;continue;}n=n+2;}finally{n=n+1;}}return n-5;}",
        0,
    );
    qualify(
        "usize count<T:Storable>(ref Array<T> values){usize n=0;for(value in *values){n=n+1;}return n;}int main(){Array<string> xs={\"a\",\"b\"};if(count<string>(&xs)==2){return 0;}return 1;}",
        0,
    );
}

#[test]
fn invalidation_fails_closed_and_disjoint_roots_remain_usable() {
    for bad in [
        "int main(){List<string> a={\"x\"};for(x in a){push(a,\"y\");}return 0;}",
        "int main(){List<string> a={\"x\"};for(x in a){reserve(a,8);}return 0;}",
        "int main(){List<string> a={\"x\"};for(x in a){string y=pop(a);}return 0;}",
        "int main(){List<string> a={\"x\",\"y\"};for(x in a){string y=remove(a,0);}return 0;}",
        "int main(){List<string> a={\"x\",\"y\"};for(x in a){string y=swap_remove(a,1);}return 0;}",
        "int main(){Array<string> a={\"x\"};for(x in a){a[0]=\"y\";}return 0;}",
        "int main(){List<string> a={\"x\"};for(x in a){a[0]=\"y\";}return 0;}",
        "int main(){Array<string> a={\"x\"};for(x in a){a={\"y\"};}return 0;}",
        "int replace(ref mut string value){*value=\"y\";return 0;}int main(){Array<string> a={\"x\"};for(x in a){int n=replace(&mut a[0]);}return 0;}",
        "int replace(ref mut Array<string> value){*value={\"y\"};return 0;}int main(){Array<string> a={\"x\"};for(x in a){int n=replace(&mut a);}return 0;}",
    ] {
        reject(bad);
    }
    qualify(
        "int main(){Array<string> a={\"x\"};Array<string> b={\"y\"};for(x in a){b[0]=\"z\";}if(byteLength(b[0])==1){return 0;}return 1;}",
        0,
    );
}

#[test]
fn mir_ssa_provenance_corruptions_and_item_arc_absence_are_verified() {
    let source = "int main(){Array<string> a={\"x\",\"y\"};usize n=0;for(x in a){n=n+byteLength(*x);}if(n==2){return 0;}return 1;}";
    let hir = analyze(parse_source(&SourceFile::new("corrupt_v3.ae", source)).unwrap()).unwrap();
    let mir = lower_hir(hir);
    let mut bad_mir = mir.clone();
    let collection = bad_mir.functions[0].collection_loops[0].clone();
    let instruction = bad_mir.functions[0].blocks[collection.item.0 as usize]
        .instructions
        .iter_mut()
        .find(|instruction| matches!(instruction.value, Rvalue::CollectionBinding { .. }))
        .unwrap();
    let Rvalue::CollectionBinding { category, .. } = &mut instruction.value else {
        unreachable!()
    };
    *category = IterationBindingCategory::CopyValue;
    assert!(verify_mir(bad_mir).is_err());

    let verified = verify_mir(mir).unwrap();
    let mut bad_ssa = build_ssa(&verified);
    let collection = bad_ssa.functions[0].collection_loops[0].clone();
    let instruction = bad_ssa.functions[0].blocks[collection.item.0 as usize]
        .instructions
        .iter_mut()
        .find(|instruction| matches!(instruction.op, SsaOp::CollectionBinding { .. }))
        .unwrap();
    let SsaOp::CollectionBinding { item_type, .. } = &mut instruction.op else {
        unreachable!()
    };
    *item_type = aether_frontend::TypeId::INT64;
    assert!(verify_ssa(bad_ssa).is_err());

    let mut escaped_ssa = build_ssa(&verified);
    let collection = escaped_ssa.functions[0].collection_loops[0].clone();
    let binding = escaped_ssa.functions[0].blocks[collection.item.0 as usize]
        .instructions
        .iter()
        .find(|instruction| matches!(instruction.op, SsaOp::CollectionBinding { .. }))
        .unwrap()
        .result;
    let instruction = escaped_ssa.functions[0].blocks[collection.latch.0 as usize]
        .instructions
        .iter_mut()
        .find(|instruction| matches!(instruction.op, SsaOp::Binary { .. }))
        .unwrap();
    let SsaOp::Binary { right, .. } = &mut instruction.op else {
        unreachable!()
    };
    *right = aether_middle::SsaOperand::Value(binding);
    assert!(verify_ssa(escaped_ssa).is_err());

    let invalidation_source = "int main(){Array<string> a={\"x\"};Array<string> b={\"y\"};for(x in a){b[0]=\"z\";println(*x);}return 0;}";
    let hir = analyze(
        parse_source(&SourceFile::new(
            "corrupt_invalidation.ae",
            invalidation_source,
        ))
        .unwrap(),
    )
    .unwrap();
    let verified = verify_mir(lower_hir(hir)).unwrap();
    let mut invalidating_ssa = build_ssa(&verified);
    let collection = invalidating_ssa.functions[0].collection_loops[0].clone();
    let borrowed_base = invalidating_ssa.functions[0].blocks[collection.item.0 as usize]
        .instructions
        .iter()
        .find_map(|instruction| match &instruction.op {
            SsaOp::CollectionBinding { source, .. } => Some(source.base.clone()),
            _ => None,
        })
        .unwrap();
    let replacement = invalidating_ssa.functions[0]
        .blocks
        .iter_mut()
        .flat_map(|block| &mut block.instructions)
        .find_map(|instruction| match &mut instruction.op {
            SsaOp::ReplaceString { destination, .. } => Some(destination),
            _ => None,
        })
        .unwrap();
    replacement.base = borrowed_base;
    assert!(verify_ssa(invalidating_ssa).is_err());

    let compilation = compile(source, OptimizationLevel::O0);
    let item = &compilation.llvm[compilation.llvm.find("%collection").unwrap()..];
    let item = &item[..item.find("br label").unwrap_or(item.len())];
    assert!(!item.contains("aether_string_retain"));
    assert!(!item.contains("aether_string_release"));
    assert!(!item.contains("aether_relocate"));
    assert!(!compilation.llvm.contains("iterator"));
    assert!(!compilation.llvm.contains("collection_next"));
}
