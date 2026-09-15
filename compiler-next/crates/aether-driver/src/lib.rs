//! Development driver for the isolated compiler.

use std::collections::{BTreeMap, BTreeSet};
use std::fs;
use std::path::{Path, PathBuf};
use std::process::{Command, ExitStatus};
use std::time::{Instant, SystemTime, UNIX_EPOCH};

use aether_backend_llvm::{Backend, LlvmTextBackend, TargetDescriptor};
use aether_frontend::{
    Diagnostic, DiagnosticCategory, LogicalSourceKey, ModuleId, ModuleInfo, OriginKey, PackageId,
    PackageKey, PackagePath, ParsedAst, ParsedModule, ParsedProgram, Phase, ResolvedImport,
    SourceFile, SourceId, SourceUnitKey, Span, analyze_bodies_for_target,
    collect_program_signatures, collect_signatures, parse_source,
};
use aether_middle::{build_ssa, lower_hir, optimize_oop, verify_mir, verify_ssa};

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
        discover_catalog(entry_path)
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

#[derive(Debug)]
struct CatalogUnit {
    path: PathBuf,
    logical: String,
    source: SourceFile,
    ast: ParsedAst,
    package: PackageKey,
    toolchain: bool,
}

struct SourceCandidate {
    path: PathBuf,
    logical: String,
    text: String,
    package_path: Option<Vec<String>>,
}

#[allow(clippy::cast_possible_truncation, clippy::too_many_lines)]
fn discover_catalog(entry_path: &Path) -> Result<CompilationSession, Vec<Diagnostic>> {
    let discovery_started = Instant::now();
    let source_root = entry_path
        .parent()
        .unwrap_or_else(|| Path::new("."))
        .to_path_buf();
    let entry_absolute = entry_path.canonicalize().map_err(|error| {
        vec![io_diagnostic(format!(
            "could not read entry source `{}`: {error}",
            entry_path.display()
        ))]
    })?;
    let mut paths = Vec::new();
    collect_source_paths(&source_root, &source_root, &mut paths)?;
    paths.sort_by(|left, right| left.0.cmp(&right.0));
    let mut file_load_ns = 0_u128;
    let mut candidates = Vec::new();
    for (logical, path) in paths {
        let started = Instant::now();
        let text = fs::read_to_string(&path).map_err(|error| {
            vec![io_diagnostic(format!(
                "could not read source unit `{logical}`: {error}"
            ))]
        })?;
        file_load_ns += started.elapsed().as_nanos();
        let package_path = catalog_package_header(&text);
        if package_path
            .as_ref()
            .is_some_and(|path| path.first().is_some_and(|segment| segment == "std"))
        {
            return Err(vec![
                Diagnostic::new(
                    "E0231",
                    Phase::Semantic,
                    DiagnosticCategory::Name,
                    "project source cannot declare reserved package root `std`",
                    None,
                )
                .with_source_name(&logical),
            ]);
        }
        candidates.push(SourceCandidate {
            path,
            logical,
            text,
            package_path,
        });
    }
    let entry_candidate = candidates
        .iter()
        .position(|candidate| candidate.path.canonicalize().ok().as_ref() == Some(&entry_absolute))
        .ok_or_else(|| {
            vec![io_diagnostic(
                "entry source is outside its source root catalog",
            )]
        })?;
    let entry_path = candidates[entry_candidate]
        .package_path
        .clone()
        .ok_or_else(|| {
            vec![
                Diagnostic::new(
                    "E0230",
                    Phase::Parse,
                    DiagnosticCategory::Syntax,
                    "source unit requires `package <path>;` as its first item",
                    None,
                )
                .with_source_name(&candidates[entry_candidate].logical),
            ]
        })?;
    if entry_path.first().is_some_and(|segment| segment == "std") {
        return Err(vec![
            Diagnostic::new(
                "E0231",
                Phase::Semantic,
                DiagnosticCategory::Name,
                "project source cannot declare reserved package root `std`",
                None,
            )
            .with_source_name(&candidates[entry_candidate].logical),
        ]);
    }
    let mut parse_ns = 0_u128;
    let mut units = Vec::new();
    let entry_package = PackageKey {
        origin: OriginKey::Project,
        path: PackagePath(entry_path),
    };
    let mut pending = BTreeSet::from([entry_package.clone()]);
    let mut descendant_grants = BTreeSet::new();
    let mut visited = BTreeSet::new();
    let mut loaded_sources = BTreeSet::new();
    while let Some(package) = pending.pop_first() {
        if !visited.insert(package.clone()) || package.origin == OriginKey::Toolchain {
            continue;
        }
        let include_descendants = descendant_grants.contains(&package);
        let matching_candidates = candidates
            .iter()
            .filter(|candidate| {
                candidate.package_path.as_ref().is_some_and(|path| {
                    path == &package.path.0
                        || (include_descendants && path.starts_with(&package.path.0))
                }) && !loaded_sources.contains(&candidate.logical)
            })
            .collect::<Vec<_>>();
        for candidate in matching_candidates {
            loaded_sources.insert(candidate.logical.clone());
            let source_id = SourceId(units.len() as u32);
            let source =
                SourceFile::with_id(source_id, candidate.logical.clone(), candidate.text.clone());
            let started = Instant::now();
            let ast = parse_source(&source).map_err(|diagnostics| {
                diagnostics
                    .into_iter()
                    .map(|d| d.with_source_name(&candidate.logical))
                    .collect::<Vec<_>>()
            })?;
            parse_ns += started.elapsed().as_nanos();
            let verified = explicit_project_package(&ast, &candidate.logical)?;
            for import in ast.imports() {
                if import.path != ["Text"] && import.path != ["std"] {
                    let origin = if import.path.first().is_some_and(|segment| segment == "std") {
                        OriginKey::Toolchain
                    } else {
                        OriginKey::Project
                    };
                    let imported = PackageKey {
                        origin,
                        path: PackagePath(import.path.clone()),
                    };
                    if imported.origin == OriginKey::Project {
                        descendant_grants.insert(imported.clone());
                    }
                    pending.insert(imported);
                }
            }
            units.push(CatalogUnit {
                path: candidate.path.clone(),
                logical: candidate.logical.clone(),
                source,
                ast,
                package: verified,
                toolchain: false,
            });
        }
    }
    let mut std_grants = units
        .iter()
        .flat_map(|unit| unit.ast.imports())
        .filter(|import| import.path.first().is_some_and(|segment| segment == "std"))
        .map(|import| PackagePath(import.path.clone()))
        .collect::<BTreeSet<_>>();
    let file_granted = std_grants.contains(&PackagePath(vec!["std".into(), "File".into()]));
    if file_granted {
        std_grants.insert(PackagePath(vec!["std".into(), "IO".into()]));
    }
    let core_output_used = units.iter().filter(|unit| !unit.toolchain).any(|unit| {
        let declared = unit
            .ast
            .functions()
            .iter()
            .map(|function| function.name.as_str())
            .collect::<BTreeSet<_>>();
        aether_frontend::lex(&unit.source).is_ok_and(|tokens| {
            tokens.iter().enumerate().any(|(index, token)| {
                token.kind == aether_frontend::TokenKind::Identifier
                    && matches!(token.lexeme.as_str(), "print" | "println")
                    && !declared.contains(token.lexeme.as_str())
                    && tokens
                        .get(index + 1)
                        .is_some_and(|next| next.kind == aether_frontend::TokenKind::LeftParen)
                    && index.checked_sub(1).is_none_or(|previous| {
                        tokens[previous].kind != aether_frontend::TokenKind::Dot
                    })
            })
        })
    });
    let io_public = std_grants.contains(&PackagePath(vec!["std".into(), "IO".into()]));
    let toolchain_packages = [
        (vec!["std", "Math"], "package std.Math;"),
        (
            vec!["std", "Math", "LinearAlgebra"],
            "package std.Math.LinearAlgebra;",
        ),
        (
            vec!["std", "Text"],
            "package std.Text; struct ScalarOffset { usize value; } enum FindResult { Found(ScalarOffset), NotFound, }",
        ),
        (
            vec!["std", "IO"],
            if io_public {
                "package std.IO; public open class IOException:Exception{public init(){}} public class InvalidTextEncodingException:IOException{public init():base(){}} enum ReadLineResult{Line(string),End,} ReadLineResult readLine(){ReadLineResult result=ReadLineResult.End;return result;} void eprint(ref string value){return;} void eprintln(ref string value){return;}"
            } else {
                "package std.IO; public open class IOException:Exception{public init(){}}"
            },
        ),
        (
            vec!["std", "File"],
            "package std.File; import std.IO; public class FileNotFoundException:std.IO.IOException{public init():base(){}} public class PermissionDeniedException:std.IO.IOException{public init():base(){}} string readText(ref string path){return \"\";} void writeText(ref string path,ref string value){return;}",
        ),
    ];
    for (segments, text) in toolchain_packages {
        let path = PackagePath(segments.into_iter().map(str::to_owned).collect());
        let granted = std_grants.iter().any(|grant| path.starts_with(grant));
        let core_io = path == PackagePath(vec!["std".into(), "IO".into()]) && core_output_used;
        if !(granted || core_io) {
            continue;
        }
        let std_source_id = SourceId(units.len() as u32);
        let logical = format!("{}/package.ae", path.0.join("/"));
        let std_source = SourceFile::with_id(std_source_id, format!("<toolchain>/{logical}"), text);
        let started = Instant::now();
        let std_ast = parse_source(&std_source)?;
        parse_ns += started.elapsed().as_nanos();
        units.push(CatalogUnit {
            path: PathBuf::from(format!("<toolchain>/{logical}")),
            logical,
            source: std_source,
            ast: std_ast,
            package: PackageKey {
                origin: OriginKey::Toolchain,
                path,
            },
            toolchain: true,
        });
    }

    let mut package_ids = BTreeMap::new();
    let package_keys = units
        .iter()
        .flat_map(|unit| {
            (1..=unit.package.path.0.len()).map(|length| PackageKey {
                origin: unit.package.origin.clone(),
                path: PackagePath(unit.package.path.0[..length].to_vec()),
            })
        })
        .collect::<BTreeSet<_>>();
    for key in package_keys {
        let id = PackageId(package_ids.len() as u32);
        package_ids.insert(key, id);
    }
    let mut representatives = BTreeMap::new();
    for (index, unit) in units.iter().enumerate() {
        for length in 1..=unit.package.path.0.len() {
            let prefix = PackageKey {
                origin: unit.package.origin.clone(),
                path: PackagePath(unit.package.path.0[..length].to_vec()),
            };
            representatives
                .entry(prefix)
                .or_insert(ModuleId(index as u32));
        }
    }
    validate_package_members(&units)?;
    let mut modules = units
        .iter()
        .enumerate()
        .map(|(index, unit)| SessionModule {
            info: ModuleInfo {
                id: ModuleId(index as u32),
                key: SourceUnitKey {
                    package: unit.package.clone(),
                    logical_source: LogicalSourceKey(unit.logical.clone()),
                },
                package: package_ids[&unit.package],
                name: unit.package.path.source(),
                source: unit.source.id,
                source_name: if unit.toolchain {
                    format!("<toolchain>/{}", unit.logical)
                } else {
                    unit.logical.clone()
                },
                imports: Vec::new(),
                semantic_dependencies: BTreeSet::new(),
            },
            source: unit.source.clone(),
            ast: unit.ast.clone(),
        })
        .collect::<Vec<_>>();
    for (index, unit) in units.iter().enumerate() {
        modules[index].info.imports = resolve_imports(unit, &package_ids, &representatives)?;
    }
    let entry = units
        .iter()
        .position(|unit| {
            !unit.toolchain && unit.path.canonicalize().ok().as_ref() == Some(&entry_absolute)
        })
        .map(|index| ModuleId(index as u32))
        .ok_or_else(|| {
            vec![io_diagnostic(
                "entry source is outside its source root catalog",
            )]
        })?;
    Ok(CompilationSession {
        source_root,
        entry,
        modules,
        discovery_ns: discovery_started.elapsed().as_nanos(),
        file_load_ns,
        parse_ns,
    })
}

fn catalog_package_header(text: &str) -> Option<Vec<String>> {
    let source = SourceFile::new("<catalog>", text);
    let tokens = aether_frontend::lex(&source).ok()?;
    if tokens.first()?.kind != aether_frontend::TokenKind::KwPackage {
        return None;
    }
    let mut path = Vec::new();
    let mut index = 1;
    loop {
        let token = tokens.get(index)?;
        if token.kind != aether_frontend::TokenKind::Identifier {
            return None;
        }
        path.push(token.lexeme.clone());
        index += 1;
        match tokens.get(index)?.kind {
            aether_frontend::TokenKind::Dot => index += 1,
            aether_frontend::TokenKind::Semicolon => return Some(path),
            _ => return None,
        }
    }
}

fn collect_source_paths(
    root: &Path,
    directory: &Path,
    output: &mut Vec<(String, PathBuf)>,
) -> Result<(), Vec<Diagnostic>> {
    let entries = fs::read_dir(directory).map_err(|error| {
        vec![io_diagnostic(format!(
            "could not scan source root `{}`: {error}",
            root.display()
        ))]
    })?;
    for entry in entries {
        let entry = entry.map_err(|error| {
            vec![io_diagnostic(format!(
                "could not inspect source root entry: {error}"
            ))]
        })?;
        let kind = entry.file_type().map_err(|error| {
            vec![io_diagnostic(format!(
                "could not inspect `{}`: {error}",
                entry.path().display()
            ))]
        })?;
        if kind.is_symlink() {
            return Err(vec![io_diagnostic(format!(
                "symlink source-provider entry `{}` is ambiguous",
                entry.path().display()
            ))]);
        }
        if kind.is_dir() {
            collect_source_paths(root, &entry.path(), output)?;
        } else if kind.is_file()
            && entry.path().extension().and_then(|ext| ext.to_str()) == Some("ae")
        {
            let entry_path = entry.path();
            let relative = entry_path.strip_prefix(root).expect("walked below root");
            let logical = relative
                .components()
                .map(|component| component.as_os_str().to_string_lossy())
                .collect::<Vec<_>>()
                .join("/");
            output.push((logical, entry_path));
        }
    }
    Ok(())
}

fn explicit_project_package(
    ast: &ParsedAst,
    source_name: &str,
) -> Result<PackageKey, Vec<Diagnostic>> {
    let Some(package) = ast.package() else {
        return Err(vec![
            Diagnostic::new(
                "E0230",
                Phase::Parse,
                DiagnosticCategory::Syntax,
                "source unit requires `package <path>;` as its first item",
                None,
            )
            .with_source_name(source_name),
        ]);
    };
    if package.path.first().is_some_and(|segment| segment == "std") {
        return Err(vec![
            Diagnostic::new(
                "E0231",
                Phase::Semantic,
                DiagnosticCategory::Name,
                "project source cannot declare reserved package root `std`",
                Some(package.span),
            )
            .with_source_name(source_name),
        ]);
    }
    Ok(PackageKey {
        origin: OriginKey::Project,
        path: PackagePath(package.path.clone()),
    })
}

#[allow(clippy::too_many_lines)]
fn resolve_imports(
    unit: &CatalogUnit,
    packages: &BTreeMap<PackageKey, PackageId>,
    representatives: &BTreeMap<PackageKey, ModuleId>,
) -> Result<Vec<ResolvedImport>, Vec<Diagnostic>> {
    let mut seen_targets = BTreeSet::new();
    let mut bindings = BTreeMap::<String, Span>::new();
    let declarations = unit
        .ast
        .aliases()
        .iter()
        .map(|d| d.name.as_str())
        .chain(unit.ast.structs().iter().map(|d| d.name.as_str()))
        .chain(unit.ast.enums().iter().map(|d| d.name.as_str()))
        .chain(unit.ast.classes().iter().map(|d| d.name.as_str()))
        .chain(unit.ast.interfaces().iter().map(|d| d.name.as_str()))
        .chain(unit.ast.functions().iter().map(|d| d.name.as_str()))
        .collect::<BTreeSet<_>>();
    let mut resolved = Vec::new();
    for import in unit.ast.imports() {
        if import.path == ["Text"] {
            return Err(vec![
                Diagnostic::new(
                    "E0232",
                    Phase::Semantic,
                    DiagnosticCategory::Name,
                    "legacy `import Text` is invalid; replace it with `import std.Text`",
                    Some(import.span),
                )
                .with_fixit(import.span, "import std.Text;")
                .with_source_name(&unit.logical),
            ]);
        }
        if import.path == ["std"] {
            return Err(vec![
                Diagnostic::new(
                    "E0233",
                    Phase::Semantic,
                    DiagnosticCategory::Name,
                    "`import std;` is invalid; import a concrete `std.X` branch",
                    Some(import.span),
                )
                .with_source_name(&unit.logical),
            ]);
        }
        let origin = if import.path.first().is_some_and(|segment| segment == "std") {
            OriginKey::Toolchain
        } else {
            OriginKey::Project
        };
        let target = PackageKey {
            origin,
            path: PackagePath(import.path.clone()),
        };
        let Some(package) = packages.get(&target).copied() else {
            return Err(vec![
                Diagnostic::new(
                    "E0221",
                    Phase::Semantic,
                    DiagnosticCategory::Name,
                    format!("package path `{}` does not exist", target.path.source()),
                    Some(import.span),
                )
                .with_source_name(&unit.logical),
            ]);
        };
        if !seen_targets.insert(target.clone()) {
            return Err(vec![
                Diagnostic::new(
                    "E0220",
                    Phase::Semantic,
                    DiagnosticCategory::Name,
                    format!(
                        "duplicate import of canonical package `{}`",
                        target.path.canonical()
                    ),
                    Some(import.span),
                )
                .with_source_name(&unit.logical),
            ]);
        }
        let binding = import
            .alias
            .clone()
            .unwrap_or_else(|| import.path[0].clone());
        if binding == "std" && import.alias.is_some() {
            return Err(vec![
                Diagnostic::new(
                    "E0234",
                    Phase::Semantic,
                    DiagnosticCategory::Name,
                    "`std` is reserved and cannot be an import alias",
                    Some(import.span),
                )
                .with_source_name(&unit.logical),
            ]);
        }
        if let Some(previous) = bindings.insert(binding.clone(), import.span) {
            if import.alias.is_some() {
                return Err(vec![
                    Diagnostic::new(
                        "E0220",
                        Phase::Semantic,
                        DiagnosticCategory::Name,
                        format!(
                            "duplicate namespace binding `{binding}`; previous binding at {}..{}",
                            previous.start, previous.end
                        ),
                        Some(import.span),
                    )
                    .with_source_name(&unit.logical),
                ]);
            }
        }
        if declarations.contains(binding.as_str()) {
            return Err(vec![
                Diagnostic::new(
                    "E0235",
                    Phase::Semantic,
                    DiagnosticCategory::Name,
                    format!("namespace binding `{binding}` conflicts with a package member"),
                    Some(import.span),
                )
                .with_source_name(&unit.logical),
            ]);
        }
        resolved.push(ResolvedImport {
            name: import.alias.clone().unwrap_or_else(|| target.path.source()),
            module: representatives[&target],
            package,
            target,
            alias: import.alias.clone(),
            span: import.span,
        });
    }
    Ok(resolved)
}

fn validate_package_members(units: &[CatalogUnit]) -> Result<(), Vec<Diagnostic>> {
    let mut members = BTreeMap::<PackageKey, BTreeMap<String, (&str, Span, &str)>>::new();
    for unit in units {
        let table = members.entry(unit.package.clone()).or_default();
        for (kind, name, span) in unit
            .ast
            .aliases()
            .iter()
            .map(|d| ("alias", &d.name, d.span))
            .chain(
                unit.ast
                    .structs()
                    .iter()
                    .map(|d| ("struct", &d.name, d.span)),
            )
            .chain(unit.ast.enums().iter().map(|d| ("enum", &d.name, d.span)))
            .chain(
                unit.ast
                    .classes()
                    .iter()
                    .map(|d| ("class", &d.name, d.span)),
            )
            .chain(
                unit.ast
                    .interfaces()
                    .iter()
                    .map(|d| ("interface", &d.name, d.span)),
            )
            .chain(
                unit.ast
                    .functions()
                    .iter()
                    .map(|d| ("function", &d.name, d.span)),
            )
        {
            if let Some((previous_kind, previous_span, previous_source)) =
                table.insert(name.clone(), (kind, span, &unit.logical))
            {
                return Err(vec![Diagnostic::new("E0240", Phase::Semantic, DiagnosticCategory::Name, format!("duplicate package member `{}` across `{previous_source}` ({previous_kind} at {}..{}) and `{}` ({kind})", name, previous_span.start, previous_span.end, unit.logical), Some(span)).with_source_name(&unit.logical)]);
            }
        }
    }
    let keys = members.keys().cloned().collect::<Vec<_>>();
    for package in &keys {
        for child in keys.iter().filter(|candidate| {
            candidate.origin == package.origin
                && candidate.path.0.len() == package.path.0.len() + 1
                && candidate.path.0.starts_with(&package.path.0)
        }) {
            let child_name = child.path.0.last().unwrap();
            if let Some((kind, span, source)) = members[package].get(child_name) {
                return Err(vec![Diagnostic::new("E0236", Phase::Semantic, DiagnosticCategory::Name, format!("package member `{child_name}` ({kind}) collides with child package `{}`", child.path.canonical()), Some(*span)).with_source_name(*source)]);
            }
        }
    }
    Ok(())
}

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
