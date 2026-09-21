//! TEXT-BYTE-ACCESS-V1 exact byte-indexed Text qualification.

use std::{fs, path::PathBuf, process::Command};

use aether_driver::{ClangToolchain, Emit, OptimizationLevel, build_path};

struct Directory(PathBuf);

impl Directory {
    fn new() -> Self {
        static NEXT: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
        let path = std::env::temp_dir().join(format!(
            "aether-text-byte-access-v1-{}-{}",
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

fn compile_and_run(
    source: &str,
    optimization: OptimizationLevel,
) -> (aether_driver::Compilation, std::process::Output) {
    let directory = Directory::new();
    let input = directory.0.join("main.ae");
    let executable = directory.0.join("program");
    fs::write(&input, source).unwrap();
    let compilation = build_path(
        &input,
        &executable,
        &[Emit::Hir, Emit::Mir, Emit::Ssa, Emit::Llvm],
        &ClangToolchain::default().with_optimization(optimization),
    )
    .unwrap_or_else(|errors| panic!("{source}\n{errors:#?}"));
    let output = Command::new(executable).output().unwrap();
    (compilation, output)
}

fn execute_llvm(llvm: &str, optimization: OptimizationLevel) -> std::process::Output {
    let directory = Directory::new();
    let input = directory.0.join("program.ll");
    let executable = directory.0.join("program");
    fs::write(&input, llvm).unwrap();
    let option = if optimization == OptimizationLevel::O0 {
        "-O0"
    } else {
        "-O2"
    };
    let linked = Command::new("clang")
        .args(["-Wno-override-module", option, "-x", "ir"])
        .arg(input)
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

fn rejects(source: &str) -> bool {
    let directory = Directory::new();
    let input = directory.0.join("main.ae");
    let executable = directory.0.join("program");
    fs::write(&input, source).unwrap();
    build_path(&input, &executable, &[], &ClangToolchain::default()).is_err()
}

#[test]
fn values_boundaries_slices_and_precedence_run_at_o0_o2() {
    let source = include_str!("../../../tests/programs/text_byte_access_v1_smoke.ae");
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        let (compilation, output) = compile_and_run(source, optimization);
        assert_eq!(output.status.code(), Some(0), "{optimization:?}");
        for phase in [Emit::Hir, Emit::Mir, Emit::Ssa] {
            let dump = &compilation.dumps[&phase];
            for operation in ["ByteAt", "IsByteBoundary", "ByteSlice"] {
                assert!(dump.contains(operation), "{phase:?} lacks {operation}");
            }
        }
        assert!(compilation.dumps[&Emit::Hir].contains("CallScopedSharedBorrow"));
        assert!(compilation.dumps[&Emit::Mir].contains("EndBorrow"));
        assert!(compilation.dumps[&Emit::Ssa].contains("Drop"));
        assert!(compilation.llvm.contains("@aether_text_byte_at"));
        assert!(compilation.llvm.contains("@aether_text_is_byte_boundary"));
        assert!(compilation.llvm.contains("@aether_text_byte_slice"));
    }
}

#[test]
fn byte_queries_trap_at_the_exact_upper_bounds() {
    let cases = [
        "package main;import std.Text;int main(){return int(std.Text.byteAt(\"x\",1));}",
        "package main;import std.Text;int main(){return int(std.Text.byteAt(\"x\",2));}",
        "package main;import std.Text;int main(){if(std.Text.isByteBoundary(\"x\",2)){return 1;}return 0;}",
    ];
    for source in cases {
        for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
            let (_, output) = compile_and_run(source, optimization);
            assert!(
                !output.status.success(),
                "did not trap at {optimization:?}: {source}"
            );
        }
    }
}

#[test]
fn valid_final_boundary_does_not_trap() {
    let source = "package main;import std.Text;int main(){if(std.Text.isByteBoundary(\"é\",2)){return 0;}return 1;}";
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        let (_, output) = compile_and_run(source, optimization);
        assert_eq!(output.status.code(), Some(0));
    }
}

#[test]
fn length_prefixed_decoder_handles_payload_bytes_and_malformed_framing() {
    let source = r#"package main;
import std.Text;
int decode(ref string framed,ref string expected){
 usize total=byteLength(*framed);usize cursor=0;usize length=0;usize digits=0;
 while(cursor<total){
  uint8 current=std.Text.byteAt(*framed,cursor);
  if(current==58){break;}
  if(current<48||current>57){return 1;}
  if(digits==6){return 2;}
  length=length*10+usize(current-48);digits=digits+1;cursor=cursor+1;
 }
 if(digits==0||cursor==total){return 3;}
 cursor=cursor+1;
 if(length>total-cursor){return 4;}
 usize end=cursor+length;
 match(std.Text.byteSlice(*framed,cursor,end)){
  std.Text.ByteSliceResult.Slice(payload)=>{if(payload!=*expected){return 5;}}
  std.Text.ByteSliceResult.InvalidBoundary=>{return 6;}
  std.Text.ByteSliceResult.InvalidRange=>{return 7;}
  std.Text.ByteSliceResult.OutOfBounds=>{return 8;}
 }
 if(end!=total){return 9;}
 return 0;
}
int decodeTwo(ref string framed,ref string first,ref string second){
 usize total=byteLength(*framed);usize cursor=0;usize field=0;
 while(cursor<total&&field<2){
  usize length=0;usize digits=0;
  while(cursor<total){
   uint8 current=std.Text.byteAt(*framed,cursor);
   if(current==58){break;}
   if(current<48||current>57||digits==6){return 1;}
   length=length*10+usize(current-48);digits=digits+1;cursor=cursor+1;
  }
  if(digits==0||cursor==total){return 2;}
  cursor=cursor+1;if(length>total-cursor){return 3;}
  usize end=cursor+length;
  match(std.Text.byteSlice(*framed,cursor,end)){
   std.Text.ByteSliceResult.Slice(payload)=>{
    if(field==0&&payload!=*first){return 4;}
    if(field==1&&payload!=*second){return 5;}
   }
   std.Text.ByteSliceResult.InvalidBoundary=>{return 6;}
   std.Text.ByteSliceResult.InvalidRange=>{return 7;}
   std.Text.ByteSliceResult.OutOfBounds=>{return 8;}
  }
  cursor=end;field=field+1;
 }
 if(field!=2||cursor!=total){return 9;}return 0;
}
int main(){
 if(decode("6:Aether","Aether")!=0){return 1;}
 if(decode("6:éxito","éxito")!=0){return 2;}
 if(decode("4:🙂","🙂")!=0){return 3;}
 if(decode("0:","")!=0){return 4;}
 if(decode("3:a:b","a:b")!=0){return 5;}
 if(decode("10:\0\n\r\n:012::","\0\n\r\n:012::")!=0){return 6;}
 if(decode("1:é","x")!=6){return 7;}
 if(decode("3:é","x")!=4){return 8;}
 if(decode("x:a","x")!=1){return 9;}
 if(decode("12","x")!=3){return 10;}
 if(decode("1234567:a","x")!=2){return 11;}
 if(decode("1:ab","a")!=9){return 12;}
 if(decodeTwo("3:a:b2:é","a:b","é")!=0){return 13;}
 if(decodeTwo("0:4:🙂","","🙂")!=0){return 14;}
 return 0;
}"#;
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        let (_, output) = compile_and_run(source, optimization);
        assert_eq!(output.status.code(), Some(0), "{optimization:?}");
    }
}

#[test]
fn slice_owner_survives_match_move_and_early_return_with_balanced_drop() {
    let source = r#"package main;
import std.Text;
string sliceOrEmpty(ref string input,usize start,usize end){
 match(std.Text.byteSlice(*input,start,end)){
  std.Text.ByteSliceResult.Slice(value)=>{return value;}
  std.Text.ByteSliceResult.InvalidRange=>{return "";}
  std.Text.ByteSliceResult.OutOfBounds=>{return "";}
  std.Text.ByteSliceResult.InvalidBoundary=>{return "";}
 }
}
int main(){
 string source="ab"+"é🙂cd";
 string whole=sliceOrEmpty(source,0,byteLength(source));
 string fresh=sliceOrEmpty(source,2,8);
 string empty=sliceOrEmpty(source,2,2);
 if(whole!=source||fresh!="é🙂"||empty!=""){return 1;}
 return 0;
}"#;
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        let (compilation, output) = compile_and_run(source, optimization);
        assert_eq!(output.status.code(), Some(0), "{optimization:?}");
        let check = "  %byte_heap_allocs = load i64, ptr @aether_heap_alloc_count\n  %byte_heap_allocs_ok = icmp eq i64 %byte_heap_allocs, 2\n  %byte_heap_frees = load i64, ptr @aether_heap_free_count\n  %byte_heap_frees_ok = icmp eq i64 %byte_heap_frees, 2\n  %byte_string_allocs = load i64, ptr @aether_string_alloc_count\n  %byte_string_allocs_ok = icmp eq i64 %byte_string_allocs, 2\n  %byte_string_frees = load i64, ptr @aether_string_free_count\n  %byte_string_frees_ok = icmp eq i64 %byte_string_frees, 2\n  %byte_retains = load i64, ptr @aether_string_retain_count\n  %byte_retains_ok = icmp eq i64 %byte_retains, 3\n  %byte_releases = load i64, ptr @aether_string_release_count\n  %byte_releases_ok = icmp eq i64 %byte_releases, 5\n  %byte_literal_noops = load i64, ptr @aether_string_literal_arc_noop_count\n  %byte_literal_noops_ok = icmp eq i64 %byte_literal_noops, 8\n  %byte_result_ok = icmp eq i32 %process_status, 0\n  %byte_status_0 = select i1 %byte_result_ok, i32 0, i32 90\n  %byte_status_1 = select i1 %byte_heap_allocs_ok, i32 %byte_status_0, i32 91\n  %byte_status_2 = select i1 %byte_heap_frees_ok, i32 %byte_status_1, i32 92\n  %byte_status_3 = select i1 %byte_string_allocs_ok, i32 %byte_status_2, i32 93\n  %byte_status_4 = select i1 %byte_string_frees_ok, i32 %byte_status_3, i32 94\n  %byte_status_5 = select i1 %byte_retains_ok, i32 %byte_status_4, i32 95\n  %byte_status_6 = select i1 %byte_releases_ok, i32 %byte_status_5, i32 96\n  %byte_status_7 = select i1 %byte_literal_noops_ok, i32 %byte_status_6, i32 97\n  ret i32 %byte_status_7";
        let instrumented = compilation.llvm.replace("  ret i32 %process_status", check);
        assert_ne!(instrumented, compilation.llvm);
        assert_eq!(
            execute_llvm(&instrumented, optimization).status.code(),
            Some(0),
            "unbalanced lifecycle at {optimization:?}"
        );
    }
}

#[test]
fn surface_requires_text_import_and_keeps_exact_types_and_arity() {
    let alias = r#"package main;import std.Text as text;
int main(){uint8 byte=text.byteAt("x",0);bool edge=text.isByteBoundary("x",1);
match(text.byteSlice("x",0,1)){text.ByteSliceResult.Slice(value)=>{if(value=="x"&&byte==120&&edge){return 0;}return 1;} text.ByteSliceResult.InvalidRange=>{return 2;} text.ByteSliceResult.OutOfBounds=>{return 3;} text.ByteSliceResult.InvalidBoundary=>{return 4;}}}"#;
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        let (_, output) = compile_and_run(alias, optimization);
        assert_eq!(output.status.code(), Some(0));
    }

    for source in [
        "package main;int main(){return int(std.Text.byteAt(\"x\",0));}",
        "package main;import std.Text;int main(){uint8 x=std.Text.byteAt(\"x\");return int(x);}",
        "package main;import std.Text;int main(){int offset=0;uint8 x=std.Text.byteAt(\"x\",offset);return int(x);}",
        "package main;import std.Text;int main(){int x=std.Text.byteAt(\"x\",0);return x;}",
        "package main;import std.Text;int main(){return int(std.Text.textByteAt(\"x\",0));}",
        "package main;import std.Text;int main(){string x=std.Text.byteSlice(\"x\",0,1);return 0;}",
    ] {
        assert!(
            rejects(source),
            "accepted closed-surface violation: {source}"
        );
    }
}
