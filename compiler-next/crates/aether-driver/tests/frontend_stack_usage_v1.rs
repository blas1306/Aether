//! FRONTEND-STACK-USAGE-V1 depth and semantic qualification.

use std::{fmt::Write as _, fs, path::PathBuf, process::Command};

use aether_driver::{
    ClangToolchain, Emit, OptimizationLevel, compile_source, compile_source_with_optimization,
};
use aether_frontend::SourceFile;

struct Output(PathBuf);

impl Output {
    fn new() -> Self {
        static NEXT: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
        Self(std::env::temp_dir().join(format!(
            "aether-frontend-stack-{}-{}",
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
        &SourceFile::new("frontend_stack_usage_v1.ae", source),
        &[Emit::Hir, Emit::Mir, Emit::Ssa, Emit::Llvm],
        optimization,
    )
    .unwrap_or_else(|diagnostics| panic!("{source}\n{diagnostics:#?}"))
}

fn status(source: &str, optimization: OptimizationLevel) -> i32 {
    let compilation = compile(source, optimization);
    let output = Output::new();
    ClangToolchain::default()
        .with_optimization(optimization)
        .link_executable(&compilation.llvm, &output.0)
        .unwrap();
    Command::new(&output.0)
        .status()
        .unwrap()
        .code()
        .unwrap_or(-1)
}

fn comparison_chain(operator: &str, operators: usize) -> String {
    let comparison = if operator == "&&" { "0<1" } else { "1<0" };
    std::iter::repeat_n(comparison, operators + 1)
        .collect::<Vec<_>>()
        .join(operator)
}

fn depth_source() -> String {
    let mut source = String::new();
    let depths = [1, 8, 19, 64, 128];
    for operators in depths {
        write!(
            &mut source,
            "bool and{operators}(){{return {};}}",
            comparison_chain("&&", operators)
        )
        .unwrap();
        write!(
            &mut source,
            "bool or{operators}(){{return {};}}",
            comparison_chain("||", operators)
        )
        .unwrap();
    }
    source.push_str("int main(){");
    for (index, operators) in depths.into_iter().enumerate() {
        write!(
            &mut source,
            "if(!and{operators}()){{return {};}}if(or{operators}()){{return {};}}",
            index * 2 + 1,
            index * 2 + 2
        )
        .unwrap();
    }
    source.push_str("return 0;}");
    source
}

#[test]
fn logical_depths_from_one_through_128_operators_compile_and_execute_o0_o2() {
    let source = depth_source();
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        assert_eq!(status(&source, optimization), 0);
    }
    let hir = &compile(&source, OptimizationLevel::O0).dumps[&Emit::Hir];
    // HIR dumps both the generic declaration and its concrete instance.
    let expected_per_operator = 2 * (1 + 8 + 19 + 64 + 128);
    assert_eq!(
        hir.matches("ShortCircuitAnd").count(),
        expected_per_operator
    );
    assert_eq!(hir.matches("ShortCircuitOr").count(), expected_per_operator);
}

#[test]
fn logical_semantics_preserve_order_short_circuit_parentheses_and_nullable_refinement() {
    let source = r"
bool mark(ref mut int trace,int digit,bool value){*trace=*trace*10+digit;return value;}
bool positive(int value){return value>0;}
int main(){
 int trace=0;
 if(mark(&mut trace,1,true)&&mark(&mut trace,2,true)){}else{return 1;}
 if(trace!=12){return 2;}
 trace=0;
 if(mark(&mut trace,1,false)&&mark(&mut trace,2,true)){return 3;}
 if(trace!=1){return 4;}
 trace=0;
 if(mark(&mut trace,3,true)||mark(&mut trace,4,false)){}else{return 5;}
 if(trace!=3){return 6;}
 if(!((1<2&&2<3)||(3<2&&4<5))){return 7;}
 int? value=7;
 if((value!=null&&positive(value))||(false&&mark(&mut trace,9,true))){}else{return 8;}
 if(trace!=3){return 9;}
 return 0;
}
";
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        assert_eq!(status(source, optimization), 0);
    }
}

#[test]
fn invalid_deep_logical_condition_reports_a_type_diagnostic_without_overflowing() {
    let mut operands = vec!["true"; 128];
    operands.push("1");
    let source = format!(
        "int main(){{if({}){{return 0;}}return 1;}}",
        operands.join("&&")
    );
    let diagnostics = compile_source(
        &SourceFile::new("bad_frontend_stack_usage_v1.ae", &source),
        &[],
    )
    .unwrap_err();
    assert!(diagnostics.iter().any(|diagnostic| {
        diagnostic.code.starts_with('E') && diagnostic.message.contains("bool")
    }));
}
