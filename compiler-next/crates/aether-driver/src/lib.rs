//! Development driver for the isolated compiler.

use std::collections::BTreeMap;
use std::ffi::OsString;
use std::fs;
use std::path::{Path, PathBuf};
use std::process::{Command, ExitStatus};
use std::time::{Instant, SystemTime, UNIX_EPOCH};

use aether_backend_llvm::{Backend, LlvmTextBackend, TargetDescriptor};
pub use aether_frontend::Diagnostic;
use aether_frontend::{
    DiagnosticCategory, Phase, SourceFile, analyze_bodies_for_target,
    collect_library_program_signatures, collect_program_signatures, collect_signatures,
    parse_source,
};
use aether_middle::{VerifiedSsa, build_ssa, lower_hir, optimize_oop, verify_mir, verify_ssa};
pub use aether_package::{
    PackageInstanceKey, PackageMetadata, PackageName, PackageVersion, ProjectKind, ResolvedPackage,
};

/// Native compilation profile; semantics and verification are identical.
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub enum OptimizationLevel {
    /// Inspectable semantic lowering, without physical OOP elision.
    #[default]
    O0,
    /// Verified OOP optimization followed by clang O2.
    O2,
}

/// Inspectable compiler phase.
#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord)]
pub enum Emit {
    /// Parsed source AST.
    Ast,
    /// Typed/resolved HIR.
    Hir,
    /// Verified flow MIR.
    Mir,
    /// Verified SSA.
    Ssa,
    /// LLVM module.
    Llvm,
}

impl Emit {
    /// Parses a CLI phase name.
    #[must_use]
    pub fn parse(value: &str) -> Option<Self> {
        match value {
            "ast" => Some(Self::Ast),
            "hir" => Some(Self::Hir),
            "mir" => Some(Self::Mir),
            "ssa" => Some(Self::Ssa),
            "llvm" => Some(Self::Llvm),
            _ => None,
        }
    }
}

/// Output of the in-process source-to-LLVM core.
#[derive(Clone, Debug)]
pub struct Compilation {
    /// Complete textual LLVM module.
    pub llvm: String,
    /// Requested deterministic phase dumps.
    pub dumps: BTreeMap<Emit, String>,
    /// Wall-clock nanoseconds by phase.
    pub timings_ns: BTreeMap<&'static str, u128>,
}

/// Result of semantic checking through verified SSA, before backend code generation.
#[derive(Clone, Debug)]
pub struct CheckedCompilation {
    /// Requested deterministic phase dumps. LLVM can never be present here.
    pub dumps: BTreeMap<Emit, String>,
    /// Wall-clock nanoseconds by phase.
    pub timings_ns: BTreeMap<&'static str, u128>,
}

struct AnalyzedSession {
    checked: CheckedCompilation,
    ssa: VerifiedSsa,
}

use aether_analysis::discover_catalog_with_plan;
pub use aether_analysis::{CompilationSession, ProjectPlan, SessionModule, StandaloneFile};

/// Compiles one owned source through verified SSA and LLVM.
pub fn compile_source(source: &SourceFile, emits: &[Emit]) -> Result<Compilation, Vec<Diagnostic>> {
    compile_source_with_optimization(source, emits, OptimizationLevel::O0)
}

/// Compiles a source with an explicit physical optimization profile.
pub fn compile_source_with_optimization(
    source: &SourceFile,
    emits: &[Emit],
    optimization: OptimizationLevel,
) -> Result<Compilation, Vec<Diagnostic>> {
    let mut timings_ns = BTreeMap::new();
    let mut dumps = BTreeMap::new();

    let started = Instant::now();
    let ast = parse_source(source)?;
    timings_ns.insert("frontend.parse", started.elapsed().as_nanos());
    if emits.contains(&Emit::Ast) {
        dumps.insert(Emit::Ast, ast.dump());
    }

    let started = Instant::now();
    let declared = collect_signatures(ast)?;
    timings_ns.insert(
        "frontend.signature_collection",
        started.elapsed().as_nanos(),
    );
    let started = Instant::now();
    let target = TargetDescriptor::linux_x86_64();
    let hir = analyze_bodies_for_target(declared, target.properties)?;
    timings_ns.insert("frontend.semantic_bodies", started.elapsed().as_nanos());
    timings_ns.extend(hir.types().semantic_timings_ns());
    if emits.contains(&Emit::Hir) {
        dumps.insert(Emit::Hir, hir.dump());
    }

    let started = Instant::now();
    let mir = lower_hir(hir);
    timings_ns.insert("middle.mir_lower", started.elapsed().as_nanos());
    let started = Instant::now();
    let mir = verify_mir(mir)?;
    timings_ns.insert("middle.mir_verify", started.elapsed().as_nanos());
    if emits.contains(&Emit::Mir) {
        dumps.insert(Emit::Mir, mir.dump());
    }

    let started = Instant::now();
    let ssa = build_ssa(&mir);
    timings_ns.insert("middle.ssa_build", started.elapsed().as_nanos());
    let started = Instant::now();
    let ssa = verify_ssa(ssa)?;
    timings_ns.insert("middle.ssa_verify", started.elapsed().as_nanos());
    let ssa = if optimization == OptimizationLevel::O2 {
        let started = Instant::now();
        let optimized = optimize_oop(&ssa)?;
        timings_ns.insert("middle.oop_opt_verify", started.elapsed().as_nanos());
        optimized
    } else {
        ssa
    };
    if emits.contains(&Emit::Ssa) {
        dumps.insert(Emit::Ssa, ssa.dump());
    }

    let started = Instant::now();
    let llvm = LlvmTextBackend.emit(&ssa, &target);
    timings_ns.insert("backend.llvm", started.elapsed().as_nanos());
    if emits.contains(&Emit::Llvm) {
        dumps.insert(Emit::Llvm, llvm.clone());
    }

    Ok(Compilation {
        llvm,
        dumps,
        timings_ns,
    })
}

/// Compiles one fully discovered multi-module session through the canonical pipeline.
pub fn compile_session(
    session: CompilationSession,
    emits: &[Emit],
) -> Result<Compilation, Vec<Diagnostic>> {
    compile_session_with_optimization(session, emits, OptimizationLevel::O0)
}

/// Compiles a complete module session with an explicit optimization profile.
pub fn compile_session_with_optimization(
    session: CompilationSession,
    emits: &[Emit],
    optimization: OptimizationLevel,
) -> Result<Compilation, Vec<Diagnostic>> {
    let analyzed = analyze_session_with_optimization(session, emits, optimization)?;
    let AnalyzedSession { mut checked, ssa } = analyzed;
    let started = Instant::now();
    let target = TargetDescriptor::linux_x86_64();
    let llvm = LlvmTextBackend.emit(&ssa, &target);
    checked
        .timings_ns
        .insert("backend.llvm", started.elapsed().as_nanos());
    if emits.contains(&Emit::Llvm) {
        checked.dumps.insert(Emit::Llvm, llvm.clone());
    }
    Ok(Compilation {
        llvm,
        dumps: checked.dumps,
        timings_ns: checked.timings_ns,
    })
}

fn analyze_session_with_optimization(
    session: CompilationSession,
    emits: &[Emit],
    optimization: OptimizationLevel,
) -> Result<AnalyzedSession, Vec<Diagnostic>> {
    analyze_session_for_kind(session, emits, optimization, false)
}

fn analyze_library_session_with_optimization(
    session: CompilationSession,
    emits: &[Emit],
    optimization: OptimizationLevel,
) -> Result<AnalyzedSession, Vec<Diagnostic>> {
    analyze_session_for_kind(session, emits, optimization, true)
}

fn analyze_session_for_kind(
    session: CompilationSession,
    emits: &[Emit],
    optimization: OptimizationLevel,
    library: bool,
) -> Result<AnalyzedSession, Vec<Diagnostic>> {
    let (discovery_ns, file_load_ns, parse_ns) = session.timings_ns();
    let mut timings_ns = BTreeMap::from([
        ("module.discovery", discovery_ns),
        ("module.file_load", file_load_ns),
        ("frontend.parse", parse_ns),
    ]);
    let mut dumps = BTreeMap::new();
    if emits.contains(&Emit::Ast) {
        dumps.insert(Emit::Ast, session.ast_dump());
    }

    let started = Instant::now();
    let program = session.into_parsed_program();
    let declared = if library {
        collect_library_program_signatures(program)?
    } else {
        collect_program_signatures(program)?
    };
    timings_ns.insert(
        "frontend.signature_collection",
        started.elapsed().as_nanos(),
    );
    let started = Instant::now();
    let target = TargetDescriptor::linux_x86_64();
    let hir = analyze_bodies_for_target(declared, target.properties)?;
    timings_ns.insert("frontend.semantic_bodies", started.elapsed().as_nanos());
    timings_ns.extend(hir.types().semantic_timings_ns());
    if emits.contains(&Emit::Hir) {
        dumps.insert(Emit::Hir, hir.dump());
    }

    let started = Instant::now();
    let mir = lower_hir(hir);
    timings_ns.insert("middle.mir_lower", started.elapsed().as_nanos());
    let started = Instant::now();
    let mir = verify_mir(mir)?;
    timings_ns.insert("middle.mir_verify", started.elapsed().as_nanos());
    if emits.contains(&Emit::Mir) {
        dumps.insert(Emit::Mir, mir.dump());
    }

    let started = Instant::now();
    let ssa = build_ssa(&mir);
    timings_ns.insert("middle.ssa_build", started.elapsed().as_nanos());
    let started = Instant::now();
    let ssa = verify_ssa(ssa)?;
    timings_ns.insert("middle.ssa_verify", started.elapsed().as_nanos());
    let ssa = if optimization == OptimizationLevel::O2 {
        let started = Instant::now();
        let optimized = optimize_oop(&ssa)?;
        timings_ns.insert("middle.oop_opt_verify", started.elapsed().as_nanos());
        optimized
    } else {
        ssa
    };
    if emits.contains(&Emit::Ssa) {
        dumps.insert(Emit::Ssa, ssa.dump());
    }

    Ok(AnalyzedSession {
        checked: CheckedCompilation { dumps, timings_ns },
        ssa,
    })
}

/// Bootstrap native toolchain concern, deliberately outside source semantics.
#[derive(Clone, Debug)]
pub struct ClangToolchain {
    executable: String,
    optimization: OptimizationLevel,
}

impl Default for ClangToolchain {
    fn default() -> Self {
        Self {
            executable: "clang".to_owned(),
            optimization: OptimizationLevel::O0,
        }
    }
}

impl ClangToolchain {
    /// Overrides clang discovery, primarily for qualification.
    #[must_use]
    pub fn new(executable: impl Into<String>) -> Self {
        Self {
            executable: executable.into(),
            optimization: OptimizationLevel::O0,
        }
    }

    /// Selects the same profile for middle-end optimization and native linking.
    #[must_use]
    pub const fn with_optimization(mut self, optimization: OptimizationLevel) -> Self {
        self.optimization = optimization;
        self
    }

    /// Converts LLVM text into a retained native executable.
    pub fn link_executable(&self, llvm: &str, output: &Path) -> Result<(), Vec<Diagnostic>> {
        let llvm_path = temporary_path("ll");
        fs::write(&llvm_path, llvm).map_err(|error| {
            vec![io_diagnostic(format!(
                "could not write temporary LLVM: {error}"
            ))]
        })?;
        let mut command = Command::new(&self.executable);
        command
            .arg(match self.optimization {
                OptimizationLevel::O0 => "-O0",
                OptimizationLevel::O2 => "-O2",
            })
            .arg("-x")
            .arg("ir")
            .arg(&llvm_path)
            .arg("-o")
            .arg(output);
        if llvm.contains("@__gxx_personality_v0")
            || llvm.contains("; FORMAT C++ to_chars dependency")
        {
            command.arg("-lstdc++");
        }
        if llvm.contains("; Core libm dependency") {
            command.arg("-lm");
        }
        let result = command.output();
        let _ = fs::remove_file(&llvm_path);
        let output_result = result.map_err(|error| {
            vec![Diagnostic::new(
                "E0600",
                Phase::Toolchain,
                DiagnosticCategory::Toolchain,
                format!("could not execute `{}`: {error}", self.executable),
                None,
            )]
        })?;
        if output_result.status.success() {
            Ok(())
        } else {
            Err(vec![Diagnostic::new(
                "E0601",
                Phase::Toolchain,
                DiagnosticCategory::Toolchain,
                format!(
                    "clang rejected generated LLVM: {}",
                    String::from_utf8_lossy(&output_result.stderr).trim()
                ),
                None,
            )])
        }
    }
}

/// Compiler settings shared by typed driver operations.
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct CompilationOptions {
    /// Physical optimization profile.
    pub optimization: OptimizationLevel,
    /// Deterministic compiler phase dumps requested by an embedding frontend.
    pub emits: Vec<Emit>,
}

/// A semantic-only request. Its type has no program arguments or output path.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct CheckRequest {
    /// The only standalone input.
    pub input: StandaloneFile,
    /// Compiler settings.
    pub compilation: CompilationOptions,
}

/// A retained native build request. Its type has no program arguments.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct BuildRequest {
    /// The only standalone input.
    pub input: StandaloneFile,
    /// Compiler settings.
    pub compilation: CompilationOptions,
    /// Exact retained artifact path.
    pub output: PathBuf,
}

/// A temporary native build-and-execute request.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct RunRequest {
    /// The only standalone input.
    pub input: StandaloneFile,
    /// Compiler settings.
    pub compilation: CompilationOptions,
    /// Arguments forwarded verbatim after argv[0].
    pub program_args: Vec<OsString>,
}

/// Semantic-only project request.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ProjectCheckRequest {
    /// Fully resolved project.
    pub input: ProjectPlan,
    /// Compiler settings.
    pub compilation: CompilationOptions,
}

/// Retained project build request. Its output is derived from the project plan.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ProjectBuildRequest {
    /// Fully resolved project.
    pub input: ProjectPlan,
    /// Compiler settings.
    pub compilation: CompilationOptions,
}

/// Retained application build at an explicit managed artifact path.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ManagedToolBuildRequest {
    /// Fully resolved application package graph.
    pub input: ProjectPlan,
    /// Compiler settings.
    pub compilation: CompilationOptions,
    /// Exact environment-owned output path.
    pub output: PathBuf,
}

/// Runnable application-project request.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ProjectRunRequest {
    /// Fully resolved application project.
    pub input: ProjectPlan,
    /// Compiler settings.
    pub compilation: CompilationOptions,
    /// Arguments forwarded verbatim after argv[0].
    pub program_args: Vec<OsString>,
}

/// Typed in-process CLI-to-driver boundary.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum DriverRequest {
    /// Analyze through verified SSA without backend or toolchain work.
    Check(CheckRequest),
    /// Build and retain a native artifact.
    Build(BuildRequest),
    /// Build temporarily and execute the native artifact.
    Run(RunRequest),
    /// Analyze an application or library project.
    CheckProject(ProjectCheckRequest),
    /// Build an application or library project into `.aether/build`.
    BuildProject(ProjectBuildRequest),
    /// Build an environment tool into a caller-owned managed path.
    BuildManagedTool(ManagedToolBuildRequest),
    /// Temporarily build and execute an application project.
    RunProject(ProjectRunRequest),
}

/// Typed result matching a [`DriverRequest`] operation.
#[derive(Debug)]
pub enum DriverResponse {
    /// Semantic analysis completed.
    Checked(CheckedCompilation),
    /// Native artifact was retained at the requested path.
    Built {
        /// Full compilation, including LLVM.
        compilation: Compilation,
        /// Retained artifact path.
        artifact: PathBuf,
    },
    /// The temporary native artifact ran to completion.
    Ran {
        /// Full compilation used for the run.
        compilation: Compilation,
        /// Native program status.
        status: ExitStatus,
    },
}

/// Executes a typed request using the default native toolchain.
pub fn execute(request: DriverRequest) -> Result<DriverResponse, Vec<Diagnostic>> {
    execute_with_toolchain(request, ClangToolchain::default())
}

/// Executes a typed request with an explicit toolchain, primarily for embedding and tests.
pub fn execute_with_toolchain(
    request: DriverRequest,
    toolchain: ClangToolchain,
) -> Result<DriverResponse, Vec<Diagnostic>> {
    match request {
        DriverRequest::Check(request) => {
            let checked = check_path(
                request.input.path(),
                &request.compilation.emits,
                request.compilation.optimization,
            )?;
            Ok(DriverResponse::Checked(checked))
        }
        DriverRequest::Build(request) => {
            let toolchain = toolchain.with_optimization(request.compilation.optimization);
            let compilation = build_path(
                request.input.path(),
                &request.output,
                &request.compilation.emits,
                &toolchain,
            )?;
            Ok(DriverResponse::Built {
                compilation,
                artifact: request.output,
            })
        }
        DriverRequest::Run(request) => {
            let toolchain = toolchain.with_optimization(request.compilation.optimization);
            let (compilation, status) = run_path_with_os_arguments(
                request.input.path(),
                &request.compilation.emits,
                &toolchain,
                &request.program_args,
            )?;
            Ok(DriverResponse::Ran {
                compilation,
                status,
            })
        }
        DriverRequest::CheckProject(request) => {
            let checked = check_project(&request.input, &request.compilation)?;
            Ok(DriverResponse::Checked(checked))
        }
        DriverRequest::BuildProject(request) => {
            build_project(&request.input, &request.compilation, &toolchain)
        }
        DriverRequest::BuildManagedTool(request) => {
            if request.input.kind() != ProjectKind::Application {
                return Err(vec![io_diagnostic(
                    "only application packages can be built as managed tools",
                )]);
            }
            let parent = request.output.parent().ok_or_else(|| {
                vec![io_diagnostic("managed tool output has no parent directory")]
            })?;
            fs::create_dir_all(parent).map_err(|error| {
                vec![io_diagnostic(format!(
                    "could not create managed tool directory `{}`: {error}",
                    parent.display()
                ))]
            })?;
            let toolchain = toolchain.with_optimization(request.compilation.optimization);
            let session = discover_catalog_with_plan(request.input.source(), Some(&request.input))?;
            let compilation = compile_session_with_optimization(
                session,
                &request.compilation.emits,
                request.compilation.optimization,
            )?;
            toolchain.link_executable(&compilation.llvm, &request.output)?;
            Ok(DriverResponse::Built {
                compilation,
                artifact: request.output,
            })
        }
        DriverRequest::RunProject(request) => {
            if request.input.kind() != ProjectKind::Application {
                return Err(vec![io_diagnostic("library projects cannot be run")]);
            }
            let toolchain = toolchain.with_optimization(request.compilation.optimization);
            let executable = temporary_path("out");
            let _cleanup = TemporaryArtifact(executable.clone());
            let session = discover_catalog_with_plan(request.input.source(), Some(&request.input))?;
            let compilation = compile_session_with_optimization(
                session,
                &request.compilation.emits,
                request.compilation.optimization,
            )?;
            toolchain.link_executable(&compilation.llvm, &executable)?;
            let status = Command::new(&executable)
                .args(&request.program_args)
                .status()
                .map_err(|error| {
                    vec![io_diagnostic(format!(
                        "could not execute native artifact: {error}"
                    ))]
                })?;
            Ok(DriverResponse::Ran {
                compilation,
                status,
            })
        }
    }
}

fn check_project(
    plan: &ProjectPlan,
    options: &CompilationOptions,
) -> Result<CheckedCompilation, Vec<Diagnostic>> {
    if options.emits.contains(&Emit::Llvm) {
        return Err(vec![io_diagnostic(
            "check cannot emit LLVM because it stops before the backend",
        )]);
    }
    let session = discover_catalog_with_plan(plan.source(), Some(plan))?;
    if plan.kind() == ProjectKind::Library {
        analyze_library_session_with_optimization(session, &options.emits, options.optimization)
            .map(|analysis| analysis.checked)
    } else {
        analyze_session_with_optimization(session, &options.emits, options.optimization)
            .map(|analysis| analysis.checked)
    }
}

fn build_project(
    plan: &ProjectPlan,
    options: &CompilationOptions,
    toolchain: &ClangToolchain,
) -> Result<DriverResponse, Vec<Diagnostic>> {
    let build_directory = plan.build_directory();
    fs::create_dir_all(&build_directory).map_err(|error| {
        vec![io_diagnostic(format!(
            "could not create project build directory `{}`: {error}",
            build_directory.display()
        ))]
    })?;
    let canonical_build = build_directory.canonicalize().map_err(|error| {
        vec![io_diagnostic(format!(
            "could not resolve project build directory `{}`: {error}",
            build_directory.display()
        ))]
    })?;
    if !canonical_build.starts_with(plan.root()) {
        return Err(vec![io_diagnostic(
            "project build directory escapes the project root through a symlink",
        )]);
    }
    let artifact = plan.artifact_path();
    match fs::symlink_metadata(&artifact) {
        Ok(metadata) if metadata.file_type().is_symlink() || !metadata.is_file() => {
            return Err(vec![io_diagnostic(format!(
                "project artifact path `{}` is not a safe regular file",
                artifact.display()
            ))]);
        }
        Ok(_) => {}
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => {}
        Err(error) => {
            return Err(vec![io_diagnostic(format!(
                "could not inspect project artifact path `{}`: {error}",
                artifact.display()
            ))]);
        }
    }
    if plan.kind() == ProjectKind::Application {
        let toolchain = toolchain.clone().with_optimization(options.optimization);
        let session = discover_catalog_with_plan(plan.source(), Some(plan))?;
        let compilation =
            compile_session_with_optimization(session, &options.emits, options.optimization)?;
        toolchain.link_executable(&compilation.llvm, &artifact)?;
        return Ok(DriverResponse::Built {
            compilation,
            artifact,
        });
    }

    let checked = check_project(plan, options)?;
    let metadata = format!(
        "aether-library-bootstrap = 1\nname = {:?}\nversion = {:?}\nsource = \"{}\"\n",
        plan.package().name.as_str(),
        plan.package().version.as_str(),
        plan.source()
            .strip_prefix(plan.root())
            .unwrap_or(plan.source())
            .display()
    );
    fs::write(&artifact, metadata).map_err(|error| {
        vec![io_diagnostic(format!(
            "could not write library bootstrap artifact `{}`: {error}",
            artifact.display()
        ))]
    })?;
    Ok(DriverResponse::Built {
        compilation: Compilation {
            llvm: String::new(),
            dumps: checked.dumps,
            timings_ns: checked.timings_ns,
        },
        artifact,
    })
}

/// Checks a standalone path through optimized, verified SSA and stops before LLVM.
pub fn check_path(
    source_path: &Path,
    emits: &[Emit],
    optimization: OptimizationLevel,
) -> Result<CheckedCompilation, Vec<Diagnostic>> {
    if emits.contains(&Emit::Llvm) {
        return Err(vec![io_diagnostic(
            "check cannot emit LLVM because it stops before the backend",
        )]);
    }
    let session = CompilationSession::discover(source_path)?;
    analyze_session_with_optimization(session, emits, optimization).map(|analysis| analysis.checked)
}

/// Reads and compiles a path into a retained executable using the canonical pipeline.
pub fn build_path(
    source_path: &Path,
    output: &Path,
    emits: &[Emit],
    toolchain: &ClangToolchain,
) -> Result<Compilation, Vec<Diagnostic>> {
    let session = CompilationSession::discover(source_path)?;
    let compilation = compile_session_with_optimization(session, emits, toolchain.optimization)?;
    toolchain.link_executable(&compilation.llvm, output)?;
    Ok(compilation)
}

/// Implements run literally as build-to-temporary-artifact followed by execution.
pub fn run_path(
    source_path: &Path,
    emits: &[Emit],
    toolchain: &ClangToolchain,
) -> Result<(Compilation, ExitStatus), Vec<Diagnostic>> {
    run_path_with_arguments(source_path, emits, toolchain, &[])
}

/// Compiles and runs one source path, forwarding arguments to the native program.
pub fn run_path_with_arguments(
    source_path: &Path,
    emits: &[Emit],
    toolchain: &ClangToolchain,
    arguments: &[String],
) -> Result<(Compilation, ExitStatus), Vec<Diagnostic>> {
    let arguments = arguments.iter().map(OsString::from).collect::<Vec<_>>();
    run_path_with_os_arguments(source_path, emits, toolchain, &arguments)
}

/// Compiles and runs one source path, preserving native program argument bytes.
pub fn run_path_with_os_arguments(
    source_path: &Path,
    emits: &[Emit],
    toolchain: &ClangToolchain,
    arguments: &[OsString],
) -> Result<(Compilation, ExitStatus), Vec<Diagnostic>> {
    let executable = temporary_path("out");
    let _cleanup = TemporaryArtifact(executable.clone());
    let compilation = build_path(source_path, &executable, emits, toolchain)?;
    let status = Command::new(&executable)
        .args(arguments)
        .status()
        .map_err(|error| {
            vec![io_diagnostic(format!(
                "could not execute native artifact: {error}"
            ))]
        })?;
    Ok((compilation, status))
}

struct TemporaryArtifact(PathBuf);

impl Drop for TemporaryArtifact {
    fn drop(&mut self) {
        let _ = fs::remove_file(&self.0);
    }
}

/// Default retained artifact path for `build foo.ae`.
#[must_use]
pub fn default_output(source: &Path) -> PathBuf {
    source.with_extension("")
}

fn temporary_path(extension: &str) -> PathBuf {
    static NEXT_TEMPORARY: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
    let sequence = NEXT_TEMPORARY.fetch_add(1, std::sync::atomic::Ordering::Relaxed);
    let nonce = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_nanos();
    std::env::temp_dir().join(format!(
        "aether-next-{}-{nonce}-{sequence}.{extension}",
        std::process::id()
    ))
}

fn io_diagnostic(message: impl Into<String>) -> Diagnostic {
    Diagnostic::new(
        "E0700",
        Phase::Driver,
        DiagnosticCategory::Io,
        message,
        None,
    )
}

/// Renders driver diagnostics against files in the standalone source root.
#[must_use]
pub fn render_diagnostics(source_path: &Path, diagnostics: &[Diagnostic]) -> String {
    diagnostics
        .iter()
        .map(|diagnostic| {
            let diagnostic_path = diagnostic.source_name.as_ref().map_or_else(
                || source_path.to_path_buf(),
                |name| {
                    source_path
                        .parent()
                        .unwrap_or_else(|| Path::new("."))
                        .join(name)
                },
            );
            let source = fs::read_to_string(&diagnostic_path).ok().map(|text| {
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
}

#[cfg(test)]
mod tests {
    use aether_analysis::source_root_for_entry;
    use std::path::{Path, PathBuf};

    #[test]
    fn entry_without_explicit_parent_uses_current_directory_as_source_root() {
        assert_eq!(
            source_root_for_entry(Path::new("main.ae")),
            PathBuf::from(".")
        );
        assert_eq!(
            source_root_for_entry(Path::new("./main.ae")),
            PathBuf::from(".")
        );

        let absolute = std::env::temp_dir()
            .join("aether-source-root")
            .join("main.ae");
        assert_eq!(source_root_for_entry(&absolute), absolute.parent().unwrap());
    }
}
