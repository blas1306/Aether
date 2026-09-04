//! Internal command-line entry point through NEXT-VERTICAL-13.

use std::env;
use std::path::PathBuf;
use std::process;

use aether_driver::{ClangToolchain, Compilation, Emit, build_path, default_output, run_path};
use aether_frontend::SourceFile;

fn main() {
    let args: Vec<_> = env::args().skip(1).collect();
    let code = match run_cli(&args) {
        Ok(code) => code,
        Err(message) => {
            eprintln!("{message}");
            2
        }
    };
    process::exit(code);
}

fn run_cli(args: &[String]) -> Result<i32, String> {
    let Some(command) = args.first().map(String::as_str) else {
        return Err(usage());
    };
    if command != "build" && command != "run" {
        return Err(usage());
    }
    let Some(source_arg) = args.get(1) else {
        return Err(usage());
    };
    let source_path = PathBuf::from(source_arg);
    let mut output = None;
    let mut emits = Vec::new();
    let mut timings = false;
    let mut cursor = 2;
    while cursor < args.len() {
        match args[cursor].as_str() {
            "-o" if command == "build" => {
                cursor += 1;
                output = Some(PathBuf::from(args.get(cursor).ok_or_else(usage)?));
            }
            "--emit" => {
                cursor += 1;
                let value = args.get(cursor).ok_or_else(usage)?;
                emits.push(
                    Emit::parse(value).ok_or_else(|| format!("unknown emit phase `{value}`"))?,
                );
            }
            "--timings" => timings = true,
            value => return Err(format!("unknown argument `{value}`\n{}", usage())),
        }
        cursor += 1;
    }
    emits.sort();
    emits.dedup();
    let toolchain = ClangToolchain::default();
    let result = if command == "build" {
        let output = output.unwrap_or_else(|| default_output(&source_path));
        build_path(&source_path, &output, &emits, &toolchain).map(|compilation| {
            render_outputs(&compilation, timings);
            println!("built {}", output.display());
            0
        })
    } else {
        run_path(&source_path, &emits, &toolchain).map(|(compilation, status)| {
            render_outputs(&compilation, timings);
            status.code().unwrap_or(1)
        })
    };
    result.map_err(|diagnostics| {
        diagnostics
            .iter()
            .map(|diagnostic| {
                let diagnostic_path = diagnostic.source_name.as_ref().map_or_else(
                    || source_path.clone(),
                    |name| {
                        source_path
                            .parent()
                            .unwrap_or_else(|| std::path::Path::new("."))
                            .join(name)
                    },
                );
                let source = std::fs::read_to_string(&diagnostic_path).ok().map(|text| {
                    let source_id = diagnostic
                        .span
                        .map_or_else(Default::default, |span| span.source);
                    let display_name = diagnostic
                        .source_name
                        .clone()
                        .unwrap_or_else(|| source_path.display().to_string());
                    SourceFile::with_id(source_id, display_name, text)
                });
                diagnostic.render(source.as_ref())
            })
            .collect::<Vec<_>>()
            .join("\n")
    })
}

fn render_outputs(compilation: &Compilation, timings: bool) {
    for (phase, dump) in &compilation.dumps {
        println!(
            "== {} ==\n{dump}",
            format!("{phase:?}").to_ascii_lowercase()
        );
    }
    if timings {
        for (phase, nanoseconds) in &compilation.timings_ns {
            eprintln!("timing {phase}: {nanoseconds} ns");
        }
    }
}

fn usage() -> String {
    "usage: aether-next build <source.ae> [-o artifact] [--emit ast|hir|mir|ssa|llvm] [--timings]\n       aether-next run <source.ae> [--emit ast|hir|mir|ssa|llvm] [--timings]".to_owned()
}
