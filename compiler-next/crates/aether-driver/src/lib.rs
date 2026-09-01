//! Development driver for the isolated compiler.

use std::collections::{BTreeMap, BTreeSet, VecDeque};
use std::fs;
use std::path::{Path, PathBuf};
use std::process::{Command, ExitStatus};
use std::time::{Instant, SystemTime, UNIX_EPOCH};

use aether_backend_llvm::{Backend, LlvmTextBackend, TargetDescriptor};
use aether_frontend::{
    Diagnostic, DiagnosticCategory, ModuleId, ModuleInfo, ParsedAst, ParsedModule, ParsedProgram,
    Phase, ResolvedImport, SourceFile, SourceId, analyze_bodies, collect_program_signatures,
    collect_signatures, parse_source,
};
use aether_middle::{build_ssa, lower_hir, verify_mir, verify_ssa};

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

/// One source parsed exactly once during module discovery.
#[derive(Clone, Debug)]
pub struct SessionModule {
    info: ModuleInfo,
    source: SourceFile,
    ast: ParsedAst,
}

impl SessionModule {
    /// Resolved module graph node.
    #[must_use]
    pub const fn info(&self) -> &ModuleInfo {
        &self.info
    }

    /// Owned source record.
    #[must_use]
    pub const fn source(&self) -> &SourceFile {
        &self.source
    }
}

/// Per-compilation owner of source files, the module graph and discovery measurements.
#[derive(Clone, Debug)]
pub struct CompilationSession {
    source_root: PathBuf,
    entry: ModuleId,
    modules: Vec<SessionModule>,
    discovery_ns: u128,
    file_load_ns: u128,
    parse_ns: u128,
}

impl CompilationSession {
    /// Discovers, reads and parses the entry module and all imports transitively.
    pub fn discover(entry_path: &Path) -> Result<Self, Vec<Diagnostic>> {
        let discovery_started = Instant::now();
        let source_root = entry_path
            .parent()
            .unwrap_or_else(|| Path::new("."))
            .to_path_buf();
        let entry_name = logical_name(entry_path)?;
        let mut file_load_ns = 0;
        let mut parse_ns = 0;
        let entry_module = load_module(
            ModuleId(0),
            SourceId(0),
            entry_name.clone(),
            entry_path,
            entry_path
                .file_name()
                .and_then(|name| name.to_str())
                .unwrap_or("<entry>"),
            &mut file_load_ns,
            &mut parse_ns,
            None,
        )?;
        let mut modules = vec![entry_module];
        let mut by_name = BTreeMap::from([(entry_name, ModuleId(0))]);
        let mut pending = VecDeque::from([ModuleId(0)]);
        while let Some(module_id) = pending.pop_front() {
            let index = module_id.0 as usize;
            let imports = modules[index].ast.imports().to_vec();
            let mut seen = BTreeSet::new();
            let mut resolved = Vec::with_capacity(imports.len());
            for import in imports {
                if !seen.insert(import.module.clone()) {
                    return Err(vec![
                        Diagnostic::new(
                            "E0220",
                            Phase::Semantic,
                            DiagnosticCategory::Name,
                            format!("duplicate import `{}`", import.module),
                            Some(import.span),
                        )
                        .with_source_name(&modules[index].info.source_name),
                    ]);
                }
                let target = if let Some(id) = by_name.get(&import.module).copied() {
                    id
                } else {
                    let path = source_root.join(format!("{}.ae", import.module));
                    let id = ModuleId(u32::try_from(modules.len()).expect("module count fits u32"));
                    let source_id =
                        SourceId(u32::try_from(modules.len()).expect("source count fits u32"));
                    let loaded = load_module(
                        id,
                        source_id,
                        import.module.clone(),
                        &path,
                        &format!("{}.ae", import.module),
                        &mut file_load_ns,
                        &mut parse_ns,
                        Some((&modules[index].info.source_name, import.span)),
                    )?;
                    by_name.insert(import.module.clone(), id);
                    modules.push(loaded);
                    pending.push_back(id);
                    id
                };
                resolved.push(ResolvedImport {
                    name: import.module,
                    module: target,
                    span: import.span,
                });
            }
            modules[index].info.imports = resolved;
        }
        Ok(Self {
            source_root,
            entry: ModuleId(0),
            modules,
            discovery_ns: discovery_started.elapsed().as_nanos(),
            file_load_ns,
            parse_ns,
        })
    }

    /// Explicit bootstrap source root: the entry file's containing directory.
    #[must_use]
    pub fn source_root(&self) -> &Path {
        &self.source_root
    }

    /// Entry module identity.
    #[must_use]
    pub const fn entry(&self) -> ModuleId {
        self.entry
    }

    /// Canonical module table. Its length is also the read/parse count.
    #[must_use]
    pub fn modules(&self) -> &[SessionModule] {
        &self.modules
    }

    fn into_parsed_program(self) -> ParsedProgram {
        ParsedProgram {
            modules: self
                .modules
                .into_iter()
                .map(|module| ParsedModule {
                    info: module.info,
                    ast: module.ast,
                })
                .collect(),
            entry: self.entry,
        }
    }

    fn ast_dump(&self) -> String {
        self.modules
            .iter()
            .map(|module| format!("module: {:#?}\nast: {}", module.info, module.ast.dump()))
            .collect::<Vec<_>>()
            .join("\n")
    }
}

/// Compiles one owned source through verified SSA and LLVM.
pub fn compile_source(source: &SourceFile, emits: &[Emit]) -> Result<Compilation, Vec<Diagnostic>> {
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
    let hir = analyze_bodies(declared)?;
    timings_ns.insert("frontend.semantic_bodies", started.elapsed().as_nanos());
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
    if emits.contains(&Emit::Ssa) {
        dumps.insert(Emit::Ssa, ssa.dump());
    }

    let started = Instant::now();
    let llvm = LlvmTextBackend.emit(&ssa, &TargetDescriptor::linux_x86_64());
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
    let mut timings_ns = BTreeMap::from([
        ("module.discovery", session.discovery_ns),
        ("module.file_load", session.file_load_ns),
        ("frontend.parse", session.parse_ns),
    ]);
    let mut dumps = BTreeMap::new();
    if emits.contains(&Emit::Ast) {
        dumps.insert(Emit::Ast, session.ast_dump());
    }

    let started = Instant::now();
    let declared = collect_program_signatures(session.into_parsed_program())?;
    timings_ns.insert(
        "frontend.signature_collection",
        started.elapsed().as_nanos(),
    );
    let started = Instant::now();
    let hir = analyze_bodies(declared)?;
    timings_ns.insert("frontend.semantic_bodies", started.elapsed().as_nanos());
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
    if emits.contains(&Emit::Ssa) {
        dumps.insert(Emit::Ssa, ssa.dump());
    }

    let started = Instant::now();
    let llvm = LlvmTextBackend.emit(&ssa, &TargetDescriptor::linux_x86_64());
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

/// Bootstrap native toolchain concern, deliberately outside source semantics.
#[derive(Clone, Debug)]
pub struct ClangToolchain {
    executable: String,
}

impl Default for ClangToolchain {
    fn default() -> Self {
        Self {
            executable: "clang".to_owned(),
        }
    }
}

impl ClangToolchain {
    /// Overrides clang discovery, primarily for qualification.
    #[must_use]
    pub fn new(executable: impl Into<String>) -> Self {
        Self {
            executable: executable.into(),
        }
    }

    /// Converts LLVM text into a retained native executable.
    pub fn link_executable(&self, llvm: &str, output: &Path) -> Result<(), Vec<Diagnostic>> {
        let llvm_path = temporary_path("ll");
        fs::write(&llvm_path, llvm).map_err(|error| {
            vec![io_diagnostic(format!(
                "could not write temporary LLVM: {error}"
            ))]
        })?;
        let result = Command::new(&self.executable)
            .arg("-x")
            .arg("ir")
            .arg(&llvm_path)
            .arg("-o")
            .arg(output)
            .output();
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

/// Reads and compiles a path into a retained executable using the canonical pipeline.
pub fn build_path(
    source_path: &Path,
    output: &Path,
    emits: &[Emit],
    toolchain: &ClangToolchain,
) -> Result<Compilation, Vec<Diagnostic>> {
    let session = CompilationSession::discover(source_path)?;
    let compilation = compile_session(session, emits)?;
    toolchain.link_executable(&compilation.llvm, output)?;
    Ok(compilation)
}

/// Implements run literally as build-to-temporary-artifact followed by execution.
pub fn run_path(
    source_path: &Path,
    emits: &[Emit],
    toolchain: &ClangToolchain,
) -> Result<(Compilation, ExitStatus), Vec<Diagnostic>> {
    let executable = temporary_path("out");
    let compilation = build_path(source_path, &executable, emits, toolchain)?;
    let status = Command::new(&executable).status().map_err(|error| {
        vec![io_diagnostic(format!(
            "could not execute native artifact: {error}"
        ))]
    })?;
    let _ = fs::remove_file(&executable);
    Ok((compilation, status))
}

/// Default retained artifact path for `build foo.ae`.
#[must_use]
pub fn default_output(source: &Path) -> PathBuf {
    source.with_extension("")
}

fn temporary_path(extension: &str) -> PathBuf {
    let nonce = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_nanos();
    std::env::temp_dir().join(format!(
        "aether-next-{}-{nonce}.{extension}",
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

fn logical_name(path: &Path) -> Result<String, Vec<Diagnostic>> {
    let Some(name) = path.file_stem().and_then(|name| name.to_str()) else {
        return Err(vec![io_diagnostic(format!(
            "entry source `{}` has no UTF-8 module name",
            path.display()
        ))]);
    };
    let valid = name.bytes().enumerate().all(|(index, byte)| {
        byte == b'_' || byte.is_ascii_alphanumeric() && (index > 0 || !byte.is_ascii_digit())
    });
    if !valid {
        return Err(vec![io_diagnostic(format!(
            "entry source stem `{name}` is not a valid bootstrap module identifier"
        ))]);
    }
    Ok(name.to_owned())
}

#[allow(clippy::too_many_arguments)]
fn load_module(
    id: ModuleId,
    source_id: SourceId,
    logical_name: String,
    path: &Path,
    display_name: &str,
    file_load_ns: &mut u128,
    parse_ns: &mut u128,
    imported_from: Option<(&str, aether_frontend::Span)>,
) -> Result<SessionModule, Vec<Diagnostic>> {
    let started = Instant::now();
    let text = fs::read_to_string(path).map_err(|error| {
        let (message, span, source_name) = imported_from.map_or_else(
            || {
                (
                    format!("could not read entry module `{}`: {error}", path.display()),
                    None,
                    None,
                )
            },
            |(source_name, span)| {
                (
                    format!(
                        "imported module `{logical_name}` was not found at `{}`: {error}",
                        path.display()
                    ),
                    Some(span),
                    Some(source_name),
                )
            },
        );
        let diagnostic = Diagnostic::new(
            "E0701",
            Phase::Driver,
            DiagnosticCategory::Io,
            message,
            span,
        );
        vec![source_name.map_or(diagnostic.clone(), |name| diagnostic.with_source_name(name))]
    })?;
    *file_load_ns += started.elapsed().as_nanos();
    let source = SourceFile::with_id(source_id, display_name, text);
    let started = Instant::now();
    let ast = parse_source(&source).map_err(|diagnostics| {
        diagnostics
            .into_iter()
            .map(|diagnostic| diagnostic.with_source_name(display_name))
            .collect::<Vec<_>>()
    })?;
    *parse_ns += started.elapsed().as_nanos();
    Ok(SessionModule {
        info: ModuleInfo {
            id,
            name: logical_name,
            source: source_id,
            source_name: display_name.to_owned(),
            imports: Vec::new(),
        },
        source,
        ast,
    })
}
