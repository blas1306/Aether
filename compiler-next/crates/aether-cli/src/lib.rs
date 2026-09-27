//! Official frontend for standalone files and explicit Aether projects.

use std::ffi::OsString;
use std::fs;
use std::path::{Path, PathBuf};
use std::sync::Arc;

use aether_driver::{
    BuildRequest, CheckRequest, Compilation, CompilationOptions, DriverRequest, DriverResponse,
    Emit, OptimizationLevel, ProjectBuildRequest, ProjectCheckRequest, ProjectKind, ProjectPlan,
    ProjectRunRequest, RunRequest, StandaloneFile, default_output, execute, render_diagnostics,
};
use aether_package::{
    CacheLimits, HttpsRegistryClient, PackageName, RegistryCache, RegistryPolicy,
    RegistrySnapshotProvider, add, add_path, remove, sync, update,
};

const USAGE: &str = "usage: aether run <file.ae|directory> [options] [-- args...]\n       aether build <file.ae|directory> [-o artifact] [options]\n       aether check <file.ae|directory> [options]\n       aether init [--lib] <packageName>\n       aether sync <project> [registry-options]\n       aether update <project> [registry-options]\n       aether add <package> <project> [--path <path>] [registry-options]\n       aether remove <package> <project> [registry-options]\n       aether <file.ae> [options] [-- args...]\noptions: -O0 | -O2, --emit ast|hir|mir|ssa|llvm, --timings\nregistry-options: --registry <https-url>, --cache-dir <path>, --offline\n         (`check` does not accept `--emit llvm`)";

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
    /// Create a new application or library package.
    Init {
        /// Create `src/lib.ae` instead of `src/main.ae`.
        library: bool,
    },
    /// Materialize the exact locked project graph, creating a lock if absent.
    Sync,
    /// Resolve the complete project graph anew.
    Update,
    /// Add one direct registry or path dependency.
    Add {
        /// Exact package/import name.
        package: String,
        /// Optional local path locator.
        path: Option<PathBuf>,
    },
    /// Remove one direct dependency.
    Remove {
        /// Exact package/import name.
        package: String,
    },
}

/// Registry/cache settings supplied explicitly by the CLI.
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct RegistryOptions {
    /// Physical HTTPS endpoint; it never participates in package identity.
    pub endpoint: Option<String>,
    /// Global cache root override.
    pub cache_dir: Option<PathBuf>,
    /// Disable all network access.
    pub offline: bool,
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
    /// Explicit package transport settings.
    pub registry: RegistryOptions,
}

/// Parses the V1 standalone grammar without invoking the compiler.
#[allow(clippy::too_many_lines)]
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
    if first_text == "init" {
        return parse_init(&arguments);
    }
    if matches!(first_text.as_ref(), "sync" | "update" | "add" | "remove") {
        return parse_package_command(&arguments);
    }
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
    let mut registry = RegistryOptions::default();
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
            "--offline" => registry.offline = true,
            "--registry" => {
                cursor += 1;
                registry.endpoint = Some(option_text(&arguments, cursor, "--registry")?);
            }
            "--cache-dir" => {
                cursor += 1;
                registry.cache_dir =
                    Some(PathBuf::from(arguments.get(cursor).ok_or_else(|| {
                        format!("missing value for `--cache-dir`\n{}", usage())
                    })?));
            }
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
        registry,
    })
}

fn parse_init(arguments: &[OsString]) -> Result<CliInvocation, String> {
    let mut library = false;
    let mut name = None;
    for argument in &arguments[1..] {
        match argument.to_string_lossy().as_ref() {
            "--lib" if !library && name.is_none() => library = true,
            value if value.starts_with('-') => {
                return Err(format!("unknown init option `{value}`\n{}", usage()));
            }
            _ if name.is_none() => name = Some(PathBuf::from(argument)),
            value => {
                return Err(format!(
                    "init requires exactly one package name; unexpected argument `{value}`\n{}",
                    usage()
                ));
            }
        }
    }
    let target = name.ok_or_else(|| format!("missing package name\n{}", usage()))?;
    Ok(CliInvocation {
        operation: CliOperation::Init { library },
        target,
        compilation: CompilationOptions::default(),
        timings: false,
        registry: RegistryOptions::default(),
    })
}

fn parse_package_command(arguments: &[OsString]) -> Result<CliInvocation, String> {
    let command = arguments[0].to_string_lossy();
    let mut positional = Vec::new();
    let mut registry = RegistryOptions::default();
    let mut dependency_path = None;
    let mut cursor = 1;
    while cursor < arguments.len() {
        match arguments[cursor].to_string_lossy().as_ref() {
            "--offline" => registry.offline = true,
            "--registry" => {
                cursor += 1;
                registry.endpoint = Some(option_text(arguments, cursor, "--registry")?);
            }
            "--cache-dir" => {
                cursor += 1;
                registry.cache_dir =
                    Some(PathBuf::from(arguments.get(cursor).ok_or_else(|| {
                        format!("missing value for `--cache-dir`\n{}", usage())
                    })?));
            }
            "--path" if command == "add" => {
                cursor += 1;
                dependency_path =
                    Some(PathBuf::from(arguments.get(cursor).ok_or_else(|| {
                        format!("missing value for `--path`\n{}", usage())
                    })?));
            }
            value if value.starts_with('-') => {
                return Err(format!("unknown {command} option `{value}`\n{}", usage()));
            }
            _ => positional.push(arguments[cursor].clone()),
        }
        cursor += 1;
    }
    let (operation, target) = match command.as_ref() {
        "sync" | "update" if positional.len() == 1 => (
            if command == "sync" {
                CliOperation::Sync
            } else {
                CliOperation::Update
            },
            PathBuf::from(&positional[0]),
        ),
        "add" if positional.len() == 2 => (
            CliOperation::Add {
                package: positional[0].to_string_lossy().into_owned(),
                path: dependency_path,
            },
            PathBuf::from(&positional[1]),
        ),
        "remove" if positional.len() == 2 => (
            CliOperation::Remove {
                package: positional[0].to_string_lossy().into_owned(),
            },
            PathBuf::from(&positional[1]),
        ),
        "sync" | "update" => {
            return Err(format!(
                "{command} requires exactly one project target\n{}",
                usage()
            ));
        }
        _ => {
            return Err(format!(
                "{command} requires a package and exactly one project target\n{}",
                usage()
            ));
        }
    };
    Ok(CliInvocation {
        operation,
        target,
        compilation: CompilationOptions::default(),
        timings: false,
        registry,
    })
}

fn option_text(arguments: &[OsString], cursor: usize, option: &str) -> Result<String, String> {
    arguments
        .get(cursor)
        .ok_or_else(|| format!("missing value for `{option}`\n{}", usage()))?
        .to_str()
        .map(ToOwned::to_owned)
        .ok_or_else(|| format!("value for `{option}` must be valid UTF-8"))
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum CommandKind {
    Run,
    Build,
    Check,
}

/// Runs the CLI and returns the architecture-defined process exit code.
#[allow(clippy::too_many_lines)]
pub fn run<I, S>(arguments: I) -> i32
where
    I: IntoIterator<Item = S>,
    S: Into<OsString>,
{
    let invocation = match parse(arguments) {
        Ok(invocation) => invocation,
        Err(message) => {
            eprintln!("aether: error: {message}");
            return 2;
        }
    };
    if let CliOperation::Init { library } = invocation.operation {
        return match init_project(&invocation.target, library) {
            Ok(()) => 0,
            Err(message) => {
                eprintln!("aether: error: {message}");
                2
            }
        };
    }
    if matches!(
        invocation.operation,
        CliOperation::Sync
            | CliOperation::Update
            | CliOperation::Add { .. }
            | CliOperation::Remove { .. }
    ) {
        return match run_package_command(&invocation) {
            Ok(()) => 0,
            Err(message) => {
                eprintln!("aether: error: {message}");
                2
            }
        };
    }
    let target = match resolve_target(&invocation.target, &invocation.registry) {
        Ok(target) => target,
        Err(message) => {
            eprintln!("aether: error: {message}");
            return 2;
        }
    };
    let source_path = target.source_path().to_path_buf();
    let request = match invocation.operation {
        CliOperation::Check => match target {
            ResolvedTarget::File(input) => DriverRequest::Check(CheckRequest {
                input,
                compilation: invocation.compilation,
            }),
            ResolvedTarget::Project(input) => DriverRequest::CheckProject(ProjectCheckRequest {
                input: *input,
                compilation: invocation.compilation,
            }),
        },
        CliOperation::Build { output } => match target {
            ResolvedTarget::File(input) => DriverRequest::Build(BuildRequest {
                input,
                compilation: invocation.compilation,
                output: output.unwrap_or_else(|| default_output(&source_path)),
            }),
            ResolvedTarget::Project(input) => {
                if output.is_some() {
                    eprintln!(
                        "aether: error: project build output is fixed under `.aether/build`; `-o` is standalone-only"
                    );
                    return 2;
                }
                DriverRequest::BuildProject(ProjectBuildRequest {
                    input: *input,
                    compilation: invocation.compilation,
                })
            }
        },
        CliOperation::Run { program_args } => match target {
            ResolvedTarget::File(input) => DriverRequest::Run(RunRequest {
                input,
                compilation: invocation.compilation,
                program_args,
            }),
            ResolvedTarget::Project(input) => {
                if input.kind() == ProjectKind::Library {
                    eprintln!("aether: error: library projects cannot be run");
                    return 2;
                }
                DriverRequest::RunProject(ProjectRunRequest {
                    input: *input,
                    compilation: invocation.compilation,
                    program_args,
                })
            }
        },
        CliOperation::Init { .. } => unreachable!("init handled before target resolution"),
        CliOperation::Sync
        | CliOperation::Update
        | CliOperation::Add { .. }
        | CliOperation::Remove { .. } => {
            unreachable!("package commands handled before target resolution")
        }
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
                eprintln!("aether: error: program terminated without a representable exit status");
                1
            }
        }
        Err(diagnostics) => {
            eprintln!("{}", render_diagnostics(&source_path, &diagnostics));
            1
        }
    }
}

enum ResolvedTarget {
    File(StandaloneFile),
    Project(Box<ProjectPlan>),
}

impl ResolvedTarget {
    fn source_path(&self) -> &Path {
        match self {
            Self::File(file) => file.path(),
            Self::Project(project) => project.source(),
        }
    }
}

fn resolve_target(spelling: &Path, registry: &RegistryOptions) -> Result<ResolvedTarget, String> {
    let canonical = fs::canonicalize(spelling).map_err(|error| {
        format!(
            "target `{}` does not exist or cannot be resolved: {error}",
            spelling.display()
        )
    })?;
    let metadata = fs::metadata(&canonical)
        .map_err(|error| format!("cannot inspect target `{}`: {error}", spelling.display()))?;
    if metadata.is_dir() {
        return resolve_project(&canonical, registry)
            .map(|project| ResolvedTarget::Project(Box::new(project)));
    }
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
    StandaloneFile::new(canonical)
        .map(ResolvedTarget::File)
        .map_err(|diagnostics| {
            diagnostics
                .iter()
                .map(|diagnostic| diagnostic.message.as_str())
                .collect::<Vec<_>>()
                .join("\n")
        })
}

fn resolve_project(root: &Path, options: &RegistryOptions) -> Result<ProjectPlan, String> {
    let provider = registry_provider(options)?;
    let graph = sync(
        root,
        provider
            .as_ref()
            .map(|value| value as &dyn aether_package::RegistryProvider),
    )?;
    ProjectPlan::resolved(graph.root, &graph.packages).map_err(driver_messages)
}

fn registry_provider(
    options: &RegistryOptions,
) -> Result<Option<RegistrySnapshotProvider>, String> {
    let offline = if options.offline {
        true
    } else {
        environment_flag("AETHER_OFFLINE")?
    };
    let endpoint = options
        .endpoint
        .clone()
        .or_else(|| std::env::var("AETHER_REGISTRY_URL").ok());
    let provider = if offline {
        Some(RegistrySnapshotProvider::offline(registry_cache(options)?))
    } else if let Some(endpoint) = endpoint {
        let client = HttpsRegistryClient::new(&endpoint)?;
        Some(RegistrySnapshotProvider::new(
            Arc::new(client),
            registry_cache(options)?,
            RegistryPolicy::Online,
        ))
    } else {
        None
    };
    Ok(provider)
}

fn registry_cache(options: &RegistryOptions) -> Result<RegistryCache, String> {
    if let Some(path) = &options.cache_dir {
        RegistryCache::new(path.clone(), CacheLimits::default())
    } else if let Some(path) = std::env::var_os("AETHER_CACHE_DIR") {
        RegistryCache::new(PathBuf::from(path), CacheLimits::default())
    } else {
        RegistryCache::from_os(CacheLimits::default())
    }
}

fn run_package_command(invocation: &CliInvocation) -> Result<(), String> {
    let root = fs::canonicalize(&invocation.target).map_err(|error| {
        format!(
            "project target `{}` does not exist or cannot be resolved: {error}",
            invocation.target.display()
        )
    })?;
    if !root.is_dir() {
        return Err(format!(
            "project target `{}` is not a directory",
            invocation.target.display()
        ));
    }
    if !root.join("aether.toml").is_file() {
        return Err(format!(
            "project target `{}` is missing direct `aether.toml`",
            invocation.target.display()
        ));
    }
    if let CliOperation::Add {
        package,
        path: Some(path),
    } = &invocation.operation
    {
        return add_path(&root, package, path).map(|_| ());
    }
    let provider = registry_provider(&invocation.registry)?;
    let registry = provider
        .as_ref()
        .map(|value| value as &dyn aether_package::RegistryProvider);
    match &invocation.operation {
        CliOperation::Sync => sync(&root, registry).map(|_| ()),
        CliOperation::Update => update(&root, registry).map(|_| ()),
        CliOperation::Add { path: Some(_), .. } => {
            unreachable!("path add handled without registry")
        }
        CliOperation::Add {
            package,
            path: None,
        } => add(
            &root,
            package,
            registry.ok_or_else(|| {
                "registry transport is not configured; pass `--registry <https-url>` or `--offline`"
                    .to_owned()
            })?,
        )
        .map(|_| ()),
        CliOperation::Remove { package } => remove(&root, package, registry).map(|_| ()),
        _ => unreachable!("not a package command"),
    }
}

fn environment_flag(name: &str) -> Result<bool, String> {
    let Some(value) = std::env::var_os(name) else {
        return Ok(false);
    };
    match value.to_string_lossy().to_ascii_lowercase().as_str() {
        "1" | "true" | "yes" => Ok(true),
        "0" | "false" | "no" | "" => Ok(false),
        _ => Err(format!(
            "{name} must be one of 1, true, yes, 0, false, or no"
        )),
    }
}

fn driver_messages(diagnostics: Vec<aether_driver::Diagnostic>) -> String {
    diagnostics
        .into_iter()
        .map(|diagnostic| diagnostic.message)
        .collect::<Vec<_>>()
        .join("\n")
}

fn init_project(name_path: &Path, library: bool) -> Result<(), String> {
    let name = name_path
        .to_str()
        .ok_or_else(|| "package name must be valid UTF-8".to_owned())?;
    if name_path.components().count() != 1 {
        return Err("package name must be one identifier, not a path".to_owned());
    }
    PackageName::new(name.to_owned())?;
    if path_entry_exists(name_path)? {
        return Err(format!("refusing to overwrite existing path `{name}`"));
    }
    let parent = Path::new(".");
    let temporary = parent.join(format!(".{name}.aether-init-{}", std::process::id()));
    if path_entry_exists(&temporary)? {
        return Err(format!(
            "temporary init path `{}` already exists",
            temporary.display()
        ));
    }
    let result = (|| {
        fs::create_dir(&temporary)
            .map_err(|error| format!("cannot create temporary project: {error}"))?;
        fs::create_dir(temporary.join("src"))
            .map_err(|error| format!("cannot create project source directory: {error}"))?;
        fs::write(
            temporary.join("aether.toml"),
            format!("[package]\nname = {name:?}\nversion = \"0.1.0\"\n"),
        )
        .map_err(|error| format!("cannot write project manifest: {error}"))?;
        let (file, source) = if library {
            ("lib.ae", "// Aether library package\n")
        } else {
            ("main.ae", "int main() {\n    return 0;\n}\n")
        };
        fs::write(temporary.join("src").join(file), source)
            .map_err(|error| format!("cannot write initial source: {error}"))?;
        fs::rename(&temporary, name_path)
            .map_err(|error| format!("cannot publish initialized project: {error}"))
    })();
    if result.is_err() && path_entry_exists(&temporary).unwrap_or(false) {
        let _ = fs::remove_dir_all(&temporary);
    }
    result
}

fn path_entry_exists(path: &Path) -> Result<bool, String> {
    match fs::symlink_metadata(path) {
        Ok(_) => Ok(true),
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(false),
        Err(error) => Err(format!("cannot inspect path `{}`: {error}", path.display())),
    }
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

    #[test]
    fn parses_package_commands_and_registry_options() {
        let sync = parse([
            "sync",
            ".",
            "--registry",
            "https://registry.example",
            "--cache-dir",
            "cache",
            "--offline",
        ])
        .unwrap();
        assert!(matches!(sync.operation, CliOperation::Sync));
        assert_eq!(sync.target, PathBuf::from("."));
        assert_eq!(
            sync.registry.endpoint.as_deref(),
            Some("https://registry.example")
        );
        assert_eq!(sync.registry.cache_dir, Some(PathBuf::from("cache")));
        assert!(sync.registry.offline);

        let add = parse(["add", "linearAlgebra", ".", "--path", "../linear"]).unwrap();
        assert_eq!(
            add.operation,
            CliOperation::Add {
                package: "linearAlgebra".to_owned(),
                path: Some(PathBuf::from("../linear")),
            }
        );
        assert!(parse(["remove", "only-name"]).is_err());
        assert!(parse(["update"]).is_err());
    }
}
