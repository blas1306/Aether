//! Bootstrap frontend for standalone-file compiler operations.

use std::ffi::OsString;
use std::fs;
use std::path::{Path, PathBuf};

use aether_driver::{
    BuildRequest, CheckRequest, Compilation, CompilationOptions, DriverRequest, DriverResponse,
    Emit, OptimizationLevel, RunRequest, StandaloneFile, default_output, execute,
    render_diagnostics,
};

const USAGE: &str = "usage: aether-cli-next run <file.ae> [options] [-- args...]\n       aether-cli-next build <file.ae> [-o artifact] [options]\n       aether-cli-next check <file.ae> [options]\n       aether-cli-next <file.ae> [options] [-- args...]\noptions: -O0 | -O2, --emit ast|hir|mir|ssa|llvm, --timings\n         (`check` does not accept `--emit llvm`)";

/// CLI operation after shorthand normalization and argument validation.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum CliOperation {
    /// Execute with an exact program argument tail.
    Run {
        /// Tokens following the first irreversible `--` separator.
        program_args: Vec<OsString>,
    },
    /// Retain an executable, optionally at an explicit path.
    Build {
        /// Explicit `-o` path, or `None` for the bootstrap default.
        output: Option<PathBuf>,
    },
    /// Analyze without backend or linker work.
    Check,
}

/// Parsed CLI intent; filesystem resolution is deliberately a separate step.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct CliInvocation {
    /// Normalized operation.
    pub operation: CliOperation,
    /// Exactly one target spelling.
    pub target: PathBuf,
    /// Compiler settings.
    pub compilation: CompilationOptions,
    /// Whether phase timings should be presented on stderr.
    pub timings: bool,
}

/// Parses the V1 standalone grammar without invoking the compiler.
pub fn parse<I, S>(arguments: I) -> Result<CliInvocation, String>
where
    I: IntoIterator<Item = S>,
    S: Into<OsString>,
{
    let arguments = arguments
        .into_iter()
        .map(Into::into)
        .collect::<Vec<OsString>>();
    let first = arguments.first().ok_or_else(usage)?;
    let first_text = first.to_string_lossy();
    let (kind, target_index) = match first_text.as_ref() {
        "run" => (CommandKind::Run, 1),
        "build" => (CommandKind::Build, 1),
        "check" => (CommandKind::Check, 1),
        value
            if !value.starts_with('-')
                && Path::new(first).extension().is_some_and(|x| x == "ae") =>
        {
            (CommandKind::Run, 0)
        }
        value if value.starts_with('-') => {
            return Err(format!("unknown option `{value}`\n{}", usage()));
        }
        value => return Err(format!("unknown subcommand `{value}`\n{}", usage())),
    };
    let target = arguments
        .get(target_index)
        .ok_or_else(|| format!("missing target\n{}", usage()))?;
    if target == "--" || target.to_string_lossy().starts_with('-') {
        return Err(format!("missing target\n{}", usage()));
    }

    let mut optimization = OptimizationLevel::O0;
    let mut emits = Vec::new();
    let mut timings = false;
    let mut output = None;
    let mut program_args = Vec::new();
    let mut cursor = target_index + 1;
    while cursor < arguments.len() {
        let token = arguments[cursor].to_string_lossy();
        match token.as_ref() {
            "--" if kind == CommandKind::Run => {
                program_args = arguments[cursor + 1..].to_vec();
                break;
            }
            "--" => {
                return Err(format!(
                    "`--` and program arguments are only valid for run\n{}",
                    usage()
                ));
            }
            "-O0" => optimization = OptimizationLevel::O0,
            "-O2" => optimization = OptimizationLevel::O2,
            "--timings" => timings = true,
            "--emit" => {
                cursor += 1;
                let value = arguments
                    .get(cursor)
                    .ok_or_else(|| format!("missing value for `--emit`\n{}", usage()))?
                    .to_string_lossy();
                let emit = Emit::parse(&value)
                    .ok_or_else(|| format!("unknown emit phase `{value}`\n{}", usage()))?;
                if kind == CommandKind::Check && emit == Emit::Llvm {
                    return Err("check stops before LLVM and cannot use `--emit llvm`".to_owned());
                }
                emits.push(emit);
            }
            "-o" if kind == CommandKind::Build => {
                cursor += 1;
                output =
                    Some(PathBuf::from(arguments.get(cursor).ok_or_else(|| {
                        format!("missing value for `-o`\n{}", usage())
                    })?));
            }
            value if value.starts_with('-') => {
                return Err(format!("unknown option `{value}`\n{}", usage()));
            }
            value => {
                return Err(format!(
                    "expected exactly one target; unexpected argument `{value}`\n{}",
                    usage()
                ));
            }
        }
        cursor += 1;
    }
    emits.sort();
    emits.dedup();
    let operation = match kind {
        CommandKind::Run => CliOperation::Run { program_args },
        CommandKind::Build => CliOperation::Build { output },
        CommandKind::Check => CliOperation::Check,
    };
    Ok(CliInvocation {
        operation,
        target: PathBuf::from(target),
        compilation: CompilationOptions {
            optimization,
            emits,
        },
        timings,
    })
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum CommandKind {
    Run,
    Build,
    Check,
}

/// Runs the CLI and returns the architecture-defined process exit code.
pub fn run<I, S>(arguments: I) -> i32
where
    I: IntoIterator<Item = S>,
    S: Into<OsString>,
{
    let invocation = match parse(arguments) {
        Ok(invocation) => invocation,
        Err(message) => {
            eprintln!("aether-cli-next: error: {message}");
            return 2;
        }
    };
    let target = match resolve_target(&invocation.target) {
        Ok(target) => target,
        Err(message) => {
            eprintln!("aether-cli-next: error: {message}");
            return 2;
        }
    };
    let source_path = target.path().to_path_buf();
    let request = match invocation.operation {
        CliOperation::Check => DriverRequest::Check(CheckRequest {
            input: target,
            compilation: invocation.compilation,
        }),
        CliOperation::Build { output } => {
            let output = output.unwrap_or_else(|| default_output(&source_path));
            DriverRequest::Build(BuildRequest {
                input: target,
                compilation: invocation.compilation,
                output,
            })
        }
        CliOperation::Run { program_args } => DriverRequest::Run(RunRequest {
            input: target,
            compilation: invocation.compilation,
            program_args,
        }),
    };
    match execute(request) {
        Ok(DriverResponse::Checked(checked)) => {
            render_outputs(&checked.dumps, &checked.timings_ns, invocation.timings);
            0
        }
        Ok(DriverResponse::Built {
            compilation,
            artifact,
        }) => {
            render_compilation(&compilation, invocation.timings);
            println!("{}", artifact.display());
            0
        }
        Ok(DriverResponse::Ran {
            compilation,
            status,
        }) => {
            render_compilation(&compilation, invocation.timings);
            if let Some(code) = status.code() {
                code
            } else {
                eprintln!(
                    "aether-cli-next: error: program terminated without a representable exit status"
                );
                1
            }
        }
        Err(diagnostics) => {
            eprintln!("{}", render_diagnostics(&source_path, &diagnostics));
            1
        }
    }
}

fn resolve_target(spelling: &Path) -> Result<StandaloneFile, String> {
    let canonical = fs::canonicalize(spelling).map_err(|error| {
        format!(
            "target `{}` does not exist or cannot be resolved: {error}",
            spelling.display()
        )
    })?;
    let metadata = fs::metadata(&canonical)
        .map_err(|error| format!("cannot inspect target `{}`: {error}", spelling.display()))?;
    if !metadata.is_file() {
        return Err(format!(
            "target `{}` is not a regular file",
            spelling.display()
        ));
    }
    if canonical
        .extension()
        .and_then(|extension| extension.to_str())
        != Some("ae")
    {
        return Err(format!(
            "target `{}` must have extension `.ae`",
            spelling.display()
        ));
    }
    StandaloneFile::new(canonical).map_err(|diagnostics| {
        diagnostics
            .iter()
            .map(|diagnostic| diagnostic.message.as_str())
            .collect::<Vec<_>>()
            .join("\n")
    })
}

fn render_compilation(compilation: &Compilation, timings: bool) {
    render_outputs(&compilation.dumps, &compilation.timings_ns, timings);
}

fn render_outputs(
    dumps: &std::collections::BTreeMap<Emit, String>,
    timings_ns: &std::collections::BTreeMap<&'static str, u128>,
    timings: bool,
) {
    for (phase, dump) in dumps {
        println!(
            "== {} ==\n{dump}",
            format!("{phase:?}").to_ascii_lowercase()
        );
    }
    if timings {
        for (phase, nanoseconds) in timings_ns {
            eprintln!("timing {phase}: {nanoseconds} ns");
        }
    }
}

fn usage() -> String {
    USAGE.to_owned()
}

#[cfg(test)]
mod tests {
    use super::{CliOperation, parse};
    use std::path::PathBuf;

    #[test]
    fn parses_commands_and_requires_one_target() {
        assert!(parse(["run"]).unwrap_err().contains("missing target"));
        assert!(parse(["build"]).unwrap_err().contains("missing target"));
        assert!(parse(["check"]).unwrap_err().contains("missing target"));
        assert!(
            parse(["run", "one.ae", "two.ae"])
                .unwrap_err()
                .contains("exactly one target")
        );
        assert!(matches!(
            parse(["check", "one.ae"]).unwrap().operation,
            CliOperation::Check
        ));
    }

    #[test]
    fn shorthand_is_exactly_run_and_subcommands_win() {
        let explicit = parse(["run", "space name.ae", "-O2", "--", "a", "-x", "--", "b"]).unwrap();
        let shorthand = parse(["space name.ae", "-O2", "--", "a", "-x", "--", "b"]).unwrap();
        assert_eq!(explicit, shorthand);
        assert_eq!(explicit.target, PathBuf::from("space name.ae"));
        assert_eq!(
            explicit.operation,
            CliOperation::Run {
                program_args: vec!["a".into(), "-x".into(), "--".into(), "b".into()]
            }
        );
        assert!(parse(["run.ae"]).is_ok());
        assert!(parse(["run"]).is_err());
    }

    #[test]
    fn non_run_operations_reject_program_separator_and_tail() {
        for command in ["build", "check"] {
            assert!(parse([command, "main.ae", "--"]).is_err());
            assert!(parse([command, "main.ae", "--", "arg"]).is_err());
            assert!(parse([command, "main.ae", "arg"]).is_err());
        }
    }

    #[test]
    #[cfg(unix)]
    fn program_tail_preserves_non_utf8_bytes() {
        use std::ffi::OsString;
        use std::os::unix::ffi::OsStringExt;

        let raw = OsString::from_vec(vec![0xff, b'x']);
        let parsed = parse([
            OsString::from("run"),
            OsString::from("main.ae"),
            OsString::from("--"),
            raw.clone(),
        ])
        .unwrap();
        assert_eq!(
            parsed.operation,
            CliOperation::Run {
                program_args: vec![raw]
            }
        );
    }
}
