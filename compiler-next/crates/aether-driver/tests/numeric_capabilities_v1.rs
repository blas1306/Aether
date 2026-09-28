//! NUMERIC-CAPABILITIES-V1 language, reification and zero-overhead qualification.

use std::process::Command;

use aether_driver::{ClangToolchain, Emit, OptimizationLevel, compile_source_with_optimization};
use aether_frontend::SourceFile;

fn compile(source: &str, optimization: OptimizationLevel) -> aether_driver::Compilation {
    compile_source_with_optimization(
        &SourceFile::new("numeric_capabilities_v1.ae", source),
        &[Emit::Hir, Emit::Mir, Emit::Ssa, Emit::Llvm],
        optimization,
    )
    .unwrap_or_else(|diagnostics| panic!("{source}\n{diagnostics:#?}"))
}

fn execute(llvm: &str, optimization: OptimizationLevel) -> std::process::ExitStatus {
    static NEXT: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
    let path = std::env::temp_dir().join(format!(
        "aether-numeric-capabilities-{}-{}",
        std::process::id(),
        NEXT.fetch_add(1, std::sync::atomic::Ordering::Relaxed)
    ));
    ClangToolchain::default()
        .with_optimization(optimization)
        .link_executable(llvm, &path)
        .unwrap();
    let status = Command::new(&path).status().unwrap();
    std::fs::remove_file(path).unwrap();
    status
}

fn diagnostics(source: &str) -> String {
    compile_source_with_optimization(
        &SourceFile::new("bad_numeric_capabilities_v1.ae", source),
        &[],
        OptimizationLevel::O0,
    )
    .unwrap_err()
    .into_iter()
    .map(|diagnostic| format!("{} {}", diagnostic.code, diagnostic.message))
    .collect::<Vec<_>>()
    .join("\n")
}

#[test]
fn every_numeric_capability_and_alias_reifies_before_mir() {
    let source = r"
T zero<T:Zero>(){T value=0;return value;}
T one<T:One>(){T value=1;return value;}
T add<T:Add>(T a,T b){return a+b;}
T sub<T:Sub>(T a,T b){return a-b;}
T mul<T:Mul>(T a,T b){return a*b;}
T div<T:Div>(T a,T b){return a/b;}
T neg<T:Negate>(T value){return -value;}
bool equal<T:Equal>(T a,T b){return a==b;}
bool unequal<T:Equal>(T a,T b){return a!=b;}
bool ordered<T:Order>(T a,T b){return a<b;}
T absolute<T:Abs>(T value){return abs(value);}
T root<T:Sqrt>(T value){return sqrt(value);}
T ring<T:RingOps>(T value){T o=1;return -(value+o);}
T field<T:FieldOps>(T a,T b){return a/b;}
T real<T:RealOps>(T a,T b){return sqrt(abs(a/b));}
T realForward<T:RealOps>(T a,T b){return field<T>(a,b);}
T ieeeForward<T:IEEEFloat>(T value){return real<T>(value,value);}
int main(){
  float32 f=float32(4.0);float64 d=4.0;int i=4;
  float32 fz=zero<float32>();float64 do_=one<float64>();int iz=zero<int>();
  float32 fa=add(f,f);float64 da=add(d,d);float64 ds=sub(d,d);int im=mul(i,i);
  float32 fd=div(f,float32(2.0));float64 dn=neg(d);int in_=neg(i);
  bool e=equal(f,f)&&unequal(d,float64(5.0))&&ordered(i,5);
  float32 aa=absolute(neg(f));float64 rr=root(d);
  float32 rf=ring(f);int ri=ring(i);float64 ff=field(d,d);float32 re=real(f,f);
  float64 fw=realForward(d,d);float32 iw=ieeeForward(f);
  if(e&&fz==float32(0.0)&&do_==1.0&&iz==0&&fa==float32(8.0)&&da==8.0&&ds==0.0&&im==16&&fd==float32(2.0)&&dn==-4.0&&in_==-4&&aa==f&&rr==2.0&&rf==-5.0&&ri==-5&&ff==1.0&&re==1.0&&fw==1.0&&iw==1.0){return 0;}
  return 1;
}
";
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        let compilation = compile(source, optimization);
        let hir = &compilation.dumps[&Emit::Hir];
        for symbolic in [
            "AlgebraicValue",
            "CapabilityBinary",
            "CapabilityUnary",
            "CapabilityCompare",
            "CapabilityMath",
        ] {
            assert!(hir.contains(symbolic), "missing parametric {symbolic}");
            for phase in [Emit::Mir, Emit::Ssa] {
                assert!(!compilation.dumps[&phase].contains(symbolic));
            }
            assert!(!compilation.llvm.contains(symbolic));
        }
        assert!(hir.contains("DivideFloat"));
        assert!(hir.contains("NegateIntegerChecked"));
        assert!(hir.contains("CoreCall") || hir.contains("Core("));
        assert!(compilation.llvm.contains("fFloat32"));
        assert!(compilation.llvm.contains("fFloat64"));
        assert!(!compilation.llvm.contains("vtable"));
        assert!(!compilation.llvm.contains("witness"));
        assert_eq!(execute(&compilation.llvm, optimization).code(), Some(0));
    }
}

#[test]
fn missing_capabilities_and_closed_satisfaction_are_rejected() {
    let cases = [
        (
            "T bad<T:Add>(T a,T b){return a/b;}int main(){return 0;}",
            "Div",
        ),
        (
            "T bad<T:Add>(T a){return -a;}int main(){return 0;}",
            "Negate",
        ),
        (
            "bool bad<T:Add>(T a,T b){return a==b;}int main(){return 0;}",
            "Equal",
        ),
        (
            "bool bad<T:Equal>(T a,T b){return a<b;}int main(){return 0;}",
            "Order",
        ),
        (
            "T bad<T:Sqrt>(T a){return abs(a);}int main(){return 0;}",
            "Abs",
        ),
        (
            "T bad<T:Abs>(T a){return sqrt(a);}int main(){return 0;}",
            "Sqrt",
        ),
        (
            "T bad<T:One>(){T a=0;return a;}int main(){return 0;}",
            "Zero",
        ),
        (
            "T bad<T:Zero>(){T a=1;return a;}int main(){return 0;}",
            "One",
        ),
    ];
    for (source, capability) in cases {
        let output = diagnostics(source);
        assert!(output.contains("E0268"), "{output}");
        assert!(output.contains(capability), "{output}");
    }

    for (source, detail) in [
        (
            "T f<T:Div>(T a,T b){return a/b;}int main(){int x=f(4,2);return x;}",
            "Div",
        ),
        (
            "T f<T:Div>(T a,T b){return a/b;}int main(){int x=f<int>(4,2);return x;}",
            "Div",
        ),
        (
            "T f<T:Negate>(T a){return -a;}int main(){uint32 x=f(uint32(1));return int(x);}",
            "Negate",
        ),
        (
            "T f<T:IEEEFloat>(T a){return a;}int main(){int x=f(1);return x;}",
            "IEEEFloat",
        ),
        (
            "T f<T:RingOps>(T a){return a;}int main(){uint32 x=f(uint32(1));return int(x);}",
            "Negate",
        ),
        (
            "struct Scalar{float64 value;}T f<T:Abs>(T a){return abs(a);}int main(){Scalar x=f(Scalar(1.0));return 0;}",
            "Abs",
        ),
        (
            "T ieee<T:IEEEFloat>(T a){return a;}T bad<T:RealOps>(T a){return ieee<T>(a);}int main(){return 0;}",
            "IEEEFloat",
        ),
        (
            "T bad<T:RingOps+Add>(T a){return a;}int main(){return 0;}",
            "duplicate `Add`",
        ),
        (
            "T bad<T:Numeric>(T a){return a;}int main(){return 0;}",
            "unknown generic capability",
        ),
    ] {
        let output = diagnostics(source);
        assert!(output.contains(detail), "{output}");
    }
}

#[test]
fn generic_literals_remain_exactly_zero_and_one() {
    for literal in ["2", "-1", "0.0", "1.0", "1e0"] {
        let output = diagnostics(&format!(
            "T bad<T:Zero+One>(){{T value={literal};return value;}}int main(){{return 0;}}"
        ));
        assert!(output.starts_with('E'), "{literal}: {output}");
    }
}
