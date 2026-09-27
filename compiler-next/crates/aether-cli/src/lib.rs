//! Bootstrap frontend for standalone files and explicit Aether projects.

use std::collections::BTreeMap;
use std::ffi::OsString;
use std::fs;
use std::path::{Path, PathBuf};

use aether_driver::{
    BuildRequest, CheckRequest, Compilation, CompilationOptions, DriverRequest, DriverResponse,
    Emit, OptimizationLevel, PackageMetadata, PackageName, PackageVersion, ProjectBuildRequest,
    ProjectCheckRequest, ProjectKind, ProjectPlan, ProjectRunRequest, RunRequest, StandaloneFile,
    default_output, execute, render_diagnostics,
};
use serde::Deserialize;

const USAGE: &str = "usage: aether-cli-next run <file.ae|directory> [options] [-- args...]\n       aether-cli-next build <file.ae|directory> [-o artifact] [options]\n       aether-cli-next check <file.ae|directory> [options]\n       aether-cli-next init [--lib] <packageName>\n       aether-cli-next <file.ae> [options] [-- args...]\noptions: -O0 | -O2, --emit ast|hir|mir|ssa|llvm, --timings\n         (`check` does not accept `--emit llvm`)";

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
    if first_text == "init" {
        return parse_init(&arguments);
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
    })
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
            eprintln!("aether-cli-next: error: {message}");
            return 2;
        }
    };
    if let CliOperation::Init { library } = invocation.operation {
        return match init_project(&invocation.target, library) {
            Ok(()) => 0,
            Err(message) => {
                eprintln!("aether-cli-next: error: {message}");
                2
            }
        };
    }
    let target = match resolve_target(&invocation.target) {
        Ok(target) => target,
        Err(message) => {
            eprintln!("aether-cli-next: error: {message}");
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
                input,
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
                        "aether-cli-next: error: project build output is fixed under `.aether/build`; `-o` is standalone-only"
                    );
                    return 2;
                }
                DriverRequest::BuildProject(ProjectBuildRequest {
                    input,
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
                    eprintln!("aether-cli-next: error: library projects cannot be run");
                    return 2;
                }
                DriverRequest::RunProject(ProjectRunRequest {
                    input,
                    compilation: invocation.compilation,
                    program_args,
                })
            }
        },
        CliOperation::Init { .. } => unreachable!("init handled before target resolution"),
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

enum ResolvedTarget {
    File(StandaloneFile),
    Project(ProjectPlan),
}

impl ResolvedTarget {
    fn source_path(&self) -> &Path {
        match self {
            Self::File(file) => file.path(),
            Self::Project(project) => project.source(),
        }
    }
}

fn resolve_target(spelling: &Path) -> Result<ResolvedTarget, String> {
    let canonical = fs::canonicalize(spelling).map_err(|error| {
        format!(
            "target `{}` does not exist or cannot be resolved: {error}",
            spelling.display()
        )
    })?;
    let metadata = fs::metadata(&canonical)
        .map_err(|error| format!("cannot inspect target `{}`: {error}", spelling.display()))?;
    if metadata.is_dir() {
        return resolve_project(&canonical).map(ResolvedTarget::Project);
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

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct Manifest {
    package: ManifestPackage,
    application: Option<ManifestApplication>,
    #[serde(default)]
    dependencies: BTreeMap<String, DependencySpec>,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct ManifestPackage {
    name: String,
    version: String,
    aether: Option<String>,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct ManifestApplication {
    entry: Option<PathBuf>,
}

#[derive(Deserialize)]
#[serde(untagged)]
enum DependencySpec {
    Registry(String),
    Path(DependencyPath),
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct DependencyPath {
    path: PathBuf,
}

fn resolve_project(root: &Path) -> Result<ProjectPlan, String> {
    let direct_manifest = root.join("aether.toml");
    let metadata = fs::metadata(&direct_manifest).map_err(|error| {
        format!(
            "project root `{}` requires direct manifest `{}`: {error}",
            root.display(),
            direct_manifest.display()
        )
    })?;
    if !metadata.is_file() {
        return Err(format!(
            "direct project manifest `{}` is not a regular file",
            direct_manifest.display()
        ));
    }
    let manifest_path = fs::canonicalize(&direct_manifest).map_err(|error| {
        format!(
            "cannot resolve manifest `{}`: {error}",
            direct_manifest.display()
        )
    })?;
    let text = fs::read_to_string(&manifest_path).map_err(|error| {
        format!(
            "cannot read UTF-8 manifest `{}`: {error}",
            direct_manifest.display()
        )
    })?;
    let manifest: Manifest = toml::from_str(&text)
        .map_err(|error| format!("invalid manifest `{}`: {error}", direct_manifest.display()))?;
    let name = PackageName::new(manifest.package.name).map_err(driver_messages)?;
    let version = PackageVersion::new(manifest.package.version).map_err(driver_messages)?;
    if manifest
        .package
        .aether
        .as_deref()
        .is_some_and(|value| value != "1")
    {
        return Err("package.aether currently accepts only the compatibility line `1`".to_owned());
    }
    for (dependency_name, dependency) in &manifest.dependencies {
        PackageName::new(dependency_name.clone()).map_err(driver_messages)?;
        match dependency {
            DependencySpec::Registry(requirement) if requirement.trim().is_empty() => {
                return Err(format!(
                    "dependency `{dependency_name}` has an empty version constraint"
                ));
            }
            DependencySpec::Path(path) if path.path.as_os_str().is_empty() => {
                return Err(format!("dependency `{dependency_name}` has an empty path"));
            }
            _ => {}
        }
    }
    if !manifest.dependencies.is_empty() {
        return Err("dependencies are valid manifest entries but resolution is not supported by CLI-V1-PROJECT".to_owned());
    }

    let application = if let Some(entry) = manifest.application.and_then(|table| table.entry) {
        Some(resolve_entry(root, &entry)?)
    } else {
        conventional_source(root, "src/main.ae")?
    };
    let library = conventional_source(root, "src/lib.ae")?;
    let (source, kind) = match (application, library) {
        (Some(_), Some(_)) => {
            return Err("project has both application and library targets; multiple targets are not supported".to_owned());
        }
        (Some(source), None) => (source, ProjectKind::Application),
        (None, Some(source)) => (source, ProjectKind::Library),
        (None, None) => {
            return Err("package has no source root (`src/main.ae` or `src/lib.ae`)".to_owned());
        }
    };
    ProjectPlan::new(
        root,
        manifest_path,
        PackageMetadata {
            name,
            version,
            aether: manifest.package.aether,
        },
        source,
        kind,
    )
    .map_err(driver_messages)
}

fn resolve_entry(root: &Path, entry: &Path) -> Result<PathBuf, String> {
    if entry.is_absolute() || entry.extension().and_then(|value| value.to_str()) != Some("ae") {
        return Err("application.entry must be a relative path ending in `.ae`".to_owned());
    }
    let spelling = root.join(entry);
    let resolved = fs::canonicalize(&spelling).map_err(|error| {
        format!(
            "configured application entry `{}` is invalid: {error}",
            entry.display()
        )
    })?;
    if !resolved.starts_with(root) || !resolved.is_file() {
        return Err(format!(
            "configured application entry `{}` must resolve to a regular file inside the project root",
            entry.display()
        ));
    }
    Ok(resolved)
}

fn conventional_source(root: &Path, relative: &str) -> Result<Option<PathBuf>, String> {
    let spelling = root.join(relative);
    match fs::symlink_metadata(&spelling) {
        Ok(_) => {
            let resolved = fs::canonicalize(&spelling)
                .map_err(|error| format!("invalid conventional source `{relative}`: {error}"))?;
            if !resolved.starts_with(root) || !resolved.is_file() {
                return Err(format!(
                    "conventional source `{relative}` must resolve to a regular file inside the project root"
                ));
            }
            Ok(Some(resolved))
        }
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(None),
        Err(error) => Err(format!(
            "cannot inspect conventional source `{relative}`: {error}"
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
    PackageName::new(name.to_owned()).map_err(driver_messages)?;
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
}
