//! Development driver for the isolated compiler.

use std::collections::{BTreeMap, BTreeSet};
use std::ffi::OsString;
use std::fs;
use std::path::{Path, PathBuf};
use std::process::{Command, ExitStatus};
use std::time::{Instant, SystemTime, UNIX_EPOCH};

use aether_backend_llvm::{Backend, LlvmTextBackend, TargetDescriptor};
pub use aether_frontend::Diagnostic;
use aether_frontend::{
    DiagnosticCategory, LogicalSourceKey, ModuleId, ModuleInfo, OriginKey, PackageId, PackageKey,
    PackagePath, ParsedAst, ParsedModule, ParsedProgram, Phase, ResolvedImport, SourceFile,
    SourceId, SourceUnitKey, Span, analyze_bodies_for_target, collect_library_program_signatures,
    collect_program_signatures, collect_signatures, parse_source,
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
    owner: Option<PackageInstanceKey>,
}

struct SourceCandidate {
    path: PathBuf,
    logical: String,
    text: String,
    package_path: Option<Vec<String>>,
    owner: Option<PackageInstanceKey>,
    owner_name: Option<String>,
}

#[allow(clippy::cast_possible_truncation, clippy::too_many_lines)]
fn discover_catalog(entry_path: &Path) -> Result<CompilationSession, Vec<Diagnostic>> {
    discover_catalog_with_plan(entry_path, None)
}

#[allow(clippy::cast_possible_truncation, clippy::too_many_lines)]
fn discover_catalog_with_plan(
    entry_path: &Path,
    project: Option<&ProjectPlan>,
) -> Result<CompilationSession, Vec<Diagnostic>> {
    let discovery_started = Instant::now();
    let entry_absolute = entry_path.canonicalize().map_err(|error| {
        vec![io_diagnostic(format!(
            "could not read entry source `{}`: {error}",
            entry_path.display()
        ))]
    })?;
    let source_root = source_root_for_entry(&entry_absolute);
    let mut paths = Vec::new();
    if let Some(plan) = project {
        for (instance, package) in plan.packages() {
            let root = package
                .source()
                .parent()
                .ok_or_else(|| vec![io_diagnostic("package source has no provider root")])?;
            let mut provider_paths = Vec::new();
            collect_source_paths(root, root, &mut provider_paths)?;
            for (logical, path) in provider_paths {
                paths.push((
                    format!("{}::{logical}", instance.canonical()),
                    path,
                    Some(instance.clone()),
                    Some(package.package().name.as_str().to_owned()),
                ));
            }
        }
    } else {
        let mut standalone_paths = Vec::new();
        collect_source_paths(&source_root, &source_root, &mut standalone_paths)?;
        paths.extend(
            standalone_paths
                .into_iter()
                .map(|(logical, path)| (logical, path, None, None)),
        );
    }
    paths.sort_by(|left, right| left.0.cmp(&right.0));
    let mut file_load_ns = 0_u128;
    let mut candidates = Vec::new();
    for (logical, path, owner, owner_name) in paths {
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
            owner,
            owner_name,
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
    let mut parse_ns = 0_u128;
    let mut units = Vec::new();
    let entry_package = candidates[entry_candidate]
        .package_path
        .clone()
        .map(|path| PackageKey::named(OriginKey::Project, PackagePath(path)));
    let mut pending = BTreeSet::new();
    let mut descendant_grants = BTreeSet::new();
    let mut visited = BTreeSet::new();
    let mut loaded_sources = BTreeSet::new();
    if project.is_some() {
        for candidate in &candidates {
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
            let is_entry = candidate.path.canonicalize().ok().as_ref() == Some(&entry_absolute);
            let package = match ast.package() {
                Some(declaration) => {
                    let owner_name = candidate
                        .owner_name
                        .as_deref()
                        .expect("project candidate owner");
                    if declaration.path.first().map(String::as_str) != Some(owner_name) {
                        return Err(vec![Diagnostic::new("E0241", Phase::Semantic, DiagnosticCategory::Name, format!("source package `{}` is outside owning package root `{owner_name}`", declaration.path.join(".")), Some(declaration.span)).with_source_name(&candidate.logical)]);
                    }
                    PackageKey::named(
                        OriginKey::Package(
                            candidate.owner.clone().expect("project candidate owner"),
                        ),
                        PackagePath(declaration.path.clone()),
                    )
                }
                None if is_entry
                    && project.is_some_and(|plan| {
                        plan.root_instance() == candidate.owner.as_ref().expect("owner")
                    }) =>
                {
                    PackageKey::Anonymous
                }
                None => {
                    return Err(vec![
                        Diagnostic::new(
                            "E0220",
                            Phase::Semantic,
                            DiagnosticCategory::Name,
                            "non-entry package source must declare its owning package",
                            None,
                        )
                        .with_source_name(&candidate.logical),
                    ]);
                }
            };
            units.push(CatalogUnit {
                path: candidate.path.clone(),
                logical: candidate.logical.clone(),
                source,
                ast,
                package,
                toolchain: false,
                owner: candidate.owner.clone(),
            });
        }
    } else if let Some(package) = entry_package {
        pending.insert(package);
    } else {
        let candidate = &candidates[entry_candidate];
        let source = SourceFile::with_id(
            SourceId(0),
            candidate.logical.clone(),
            candidate.text.clone(),
        );
        let started = Instant::now();
        let ast = parse_source(&source).map_err(|diagnostics| {
            diagnostics
                .into_iter()
                .map(|d| d.with_source_name(&candidate.logical))
                .collect::<Vec<_>>()
        })?;
        parse_ns += started.elapsed().as_nanos();
        for import in ast.imports() {
            if import.path != ["Text"] && import.path != ["std"] {
                let origin = if import.path.first().is_some_and(|segment| segment == "std") {
                    OriginKey::Toolchain
                } else {
                    OriginKey::Project
                };
                let imported = PackageKey::named(origin.clone(), PackagePath(import.path.clone()));
                if origin == OriginKey::Project {
                    descendant_grants.insert(imported.clone());
                }
                pending.insert(imported);
            }
        }
        loaded_sources.insert(candidate.logical.clone());
        units.push(CatalogUnit {
            path: candidate.path.clone(),
            logical: candidate.logical.clone(),
            source,
            ast,
            package: PackageKey::Anonymous,
            toolchain: false,
            owner: None,
        });
    }
    while let Some(package) = pending.pop_first() {
        let PackageKey::Named { origin, path } = &package else {
            return Err(vec![io_diagnostic(
                "anonymous package cannot be a discovery or import target",
            )]);
        };
        if !visited.insert(package.clone()) || *origin == OriginKey::Toolchain {
            continue;
        }
        let include_descendants = descendant_grants.contains(&package);
        let matching_candidates = candidates
            .iter()
            .filter(|candidate| {
                candidate
                    .package_path
                    .as_ref()
                    .is_some_and(|candidate_path| {
                        candidate_path == &path.0
                            || (include_descendants && candidate_path.starts_with(&path.0))
                    })
                    && !loaded_sources.contains(&candidate.logical)
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
                    let imported =
                        PackageKey::named(origin.clone(), PackagePath(import.path.clone()));
                    if origin == OriginKey::Project {
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
                owner: None,
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
            "package std.Text; public struct ScalarOffset { usize value; } enum FindResult { Found(ScalarOffset), NotFound, } enum ByteSliceResult { Slice(string), InvalidRange, OutOfBounds, InvalidBoundary, } enum IntParseResult { Value(int), Invalid, Overflow, } enum DoubleParseResult { Value(double), Invalid, Overflow, Underflow, }",
        ),
        (
            vec!["std", "IO"],
            if io_public {
                "package std.IO; public open class IOException:Exception{public init(){}} public class InvalidTextEncodingException:IOException{public init():base(){}} enum ReadLineResult{Line(string),End,} public ReadLineResult readLine(){ReadLineResult result=ReadLineResult.End;return result;} public void eprint(ref string value){return;} public void eprintln(ref string value){return;}"
            } else {
                "package std.IO; public open class IOException:Exception{public init(){}}"
            },
        ),
        (
            vec!["std", "File"],
            "package std.File; import std.IO; public class FileNotFoundException:std.IO.IOException{public init():base(){}} public class PermissionDeniedException:std.IO.IOException{public init():base(){}} public string readText(ref string path){return \"\";} public void writeText(ref string path,ref string value){return;} public void writeTextAtomic(ref string path,ref string value){return;}",
        ),
        (
            vec!["std", "Process"],
            "package std.Process; public class InvalidArgumentEncodingException:Exception{public init(){}} public Array<string> args(){Array<string> values={};return values;}",
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
            package: PackageKey::named(OriginKey::Toolchain, path),
            toolchain: true,
            owner: None,
        });
    }

    let mut package_ids = BTreeMap::new();
    let package_keys = units
        .iter()
        .flat_map(|unit| match unit.package.named_parts() {
            Some((origin, path)) => (1..=path.0.len())
                .map(|length| {
                    PackageKey::named(origin.clone(), PackagePath(path.0[..length].to_vec()))
                })
                .collect::<Vec<_>>(),
            None => vec![PackageKey::Anonymous],
        })
        .collect::<BTreeSet<_>>();
    for key in package_keys {
        let id = PackageId(package_ids.len() as u32);
        package_ids.insert(key, id);
    }
    let mut representatives = BTreeMap::new();
    for (index, unit) in units.iter().enumerate() {
        if let Some((origin, path)) = unit.package.named_parts() {
            for length in 1..=path.0.len() {
                let prefix =
                    PackageKey::named(origin.clone(), PackagePath(path.0[..length].to_vec()));
                representatives
                    .entry(prefix)
                    .or_insert(ModuleId(index as u32));
            }
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
                display_name: unit.package.display(),
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
        modules[index].info.imports =
            resolve_imports(unit, &package_ids, &representatives, project)?;
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

fn source_root_for_entry(entry_path: &Path) -> PathBuf {
    entry_path
        .parent()
        .filter(|parent| !parent.as_os_str().is_empty())
        .unwrap_or_else(|| Path::new("."))
        .to_path_buf()
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
                "E0220",
                Phase::Semantic,
                DiagnosticCategory::Name,
                "catalog classified an anonymous source unit as a named package contribution",
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
    Ok(PackageKey::named(
        OriginKey::Project,
        PackagePath(package.path.clone()),
    ))
}

#[allow(clippy::too_many_lines)]
fn resolve_imports(
    unit: &CatalogUnit,
    packages: &BTreeMap<PackageKey, PackageId>,
    representatives: &BTreeMap<PackageKey, ModuleId>,
    project: Option<&ProjectPlan>,
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
        } else if let Some(plan) = project {
            let owner = unit.owner.as_ref().ok_or_else(|| {
                vec![io_diagnostic(
                    "non-toolchain project source has no owning package instance",
                )]
            })?;
            let owner_node = plan.packages().get(owner).expect("validated owner node");
            let import_root = &import.path[0];
            let target_instance = if import_root == owner_node.package().name.as_str() {
                owner.clone()
            } else if let Some(target) = owner_node.dependencies().get(import_root) {
                target.clone()
            } else {
                return Err(vec![
                    Diagnostic::new(
                        "E0242",
                        Phase::Semantic,
                        DiagnosticCategory::Name,
                        format!(
                            "package `{}` does not declare direct dependency `{import_root}`",
                            owner_node.package().name.as_str()
                        ),
                        Some(import.span),
                    )
                    .with_source_name(&unit.logical),
                ]);
            };
            OriginKey::Package(target_instance)
        } else {
            OriginKey::Project
        };
        let target = PackageKey::named(origin, PackagePath(import.path.clone()));
        let Some(package) = packages.get(&target).copied() else {
            return Err(vec![
                Diagnostic::new(
                    "E0221",
                    Phase::Semantic,
                    DiagnosticCategory::Name,
                    format!("package path `{}` does not exist", import.path.join(".")),
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
                        target
                            .named_parts()
                            .expect("source import target is named")
                            .1
                            .canonical()
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
            name: import
                .alias
                .clone()
                .unwrap_or_else(|| import.path.join(".")),
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
                if kind == "function" && previous_kind == "function" {
                    continue;
                }
                return Err(vec![Diagnostic::new("E0240", Phase::Semantic, DiagnosticCategory::Name, format!("duplicate package member `{}` across `{previous_source}` ({previous_kind} at {}..{}) and `{}` ({kind})", name, previous_span.start, previous_span.end, unit.logical), Some(span)).with_source_name(&unit.logical)]);
            }
        }
    }
    let keys = members.keys().cloned().collect::<Vec<_>>();
    for package in &keys {
        let Some((origin, path)) = package.named_parts() else {
            continue;
        };
        for child in keys.iter().filter(|candidate| {
            candidate
                .named_parts()
                .is_some_and(|(candidate_origin, candidate_path)| {
                    candidate_origin == origin
                        && candidate_path.0.len() == path.0.len() + 1
                        && candidate_path.0.starts_with(&path.0)
                })
        }) {
            let child_path = child.named_parts().expect("filtered named child").1;
            let child_name = child_path.0.last().unwrap();
            if let Some((kind, span, source)) = members[package].get(child_name) {
                return Err(vec![Diagnostic::new("E0236", Phase::Semantic, DiagnosticCategory::Name, format!("package member `{child_name}` ({kind}) collides with child package `{}`", child_path.canonical()), Some(*span)).with_source_name(*source)]);
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

/// A canonical standalone Aether source selected by an embedding frontend.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct StandaloneFile {
    path: PathBuf,
}

/// Fully resolved and validated project boundary supplied by a frontend.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ProjectPlan {
    root: PathBuf,
    manifest: PathBuf,
    package: PackageMetadata,
    source: PathBuf,
    kind: ProjectKind,
    root_instance: PackageInstanceKey,
    packages: BTreeMap<PackageInstanceKey, ResolvedPackage>,
}

impl ProjectPlan {
    /// Revalidates canonical paths and critical V1 project invariants.
    pub fn new(
        root: impl AsRef<Path>,
        manifest: impl AsRef<Path>,
        package: PackageMetadata,
        source: impl AsRef<Path>,
        kind: ProjectKind,
    ) -> Result<Self, Vec<Diagnostic>> {
        let root = root.as_ref().canonicalize().map_err(|error| {
            vec![io_diagnostic(format!(
                "could not resolve project root: {error}"
            ))]
        })?;
        if !root.is_dir() {
            return Err(vec![io_diagnostic("project root is not a directory")]);
        }
        if package.aether.as_deref().is_some_and(|value| value != "1") {
            return Err(vec![io_diagnostic(
                "package Aether compatibility currently accepts only `1`",
            )]);
        }
        let expected_manifest = root.join("aether.toml").canonicalize().map_err(|error| {
            vec![io_diagnostic(format!(
                "could not resolve direct project manifest: {error}"
            ))]
        })?;
        let manifest = manifest.as_ref().canonicalize().map_err(|error| {
            vec![io_diagnostic(format!(
                "could not resolve project manifest: {error}"
            ))]
        })?;
        if manifest != expected_manifest || !manifest.is_file() {
            return Err(vec![io_diagnostic(
                "project manifest must be the regular file `<root>/aether.toml`",
            )]);
        }
        let source = source.as_ref().canonicalize().map_err(|error| {
            vec![io_diagnostic(format!(
                "could not resolve project source: {error}"
            ))]
        })?;
        if !source.starts_with(&root)
            || !source.is_file()
            || source.extension().and_then(|value| value.to_str()) != Some("ae")
        {
            return Err(vec![io_diagnostic(
                "project source must be a regular `.ae` file confined to the project root",
            )]);
        }
        if kind == ProjectKind::Library {
            let expected_library = root.join("src/lib.ae").canonicalize().map_err(|error| {
                vec![io_diagnostic(format!(
                    "could not resolve V1 library source: {error}"
                ))]
            })?;
            if source != expected_library {
                return Err(vec![io_diagnostic(
                    "V1 library source must be `<root>/src/lib.ae`",
                )]);
            }
        }
        let root_instance = PackageInstanceKey::Root {
            manifest: manifest.to_string_lossy().into_owned(),
            name: package.name.as_str().to_owned(),
            version: package.version.as_str().to_owned(),
        };
        let root_package = ResolvedPackage::new(
            root_instance.clone(),
            root.clone(),
            manifest.clone(),
            package.clone(),
            source.clone(),
            kind,
            BTreeMap::new(),
        );
        Ok(Self {
            root,
            manifest,
            package,
            source,
            kind,
            root_instance: root_instance.clone(),
            packages: BTreeMap::from([(root_instance, root_package)]),
        })
    }

    /// Builds a resolved multi-root graph. The compiler receives only canonical package nodes
    /// and exact dependency edges; it never reads manifests or dependency locators.
    pub fn resolved(
        root_instance: PackageInstanceKey,
        packages: &BTreeMap<PackageInstanceKey, ResolvedPackage>,
    ) -> Result<Self, Vec<Diagnostic>> {
        if !matches!(root_instance, PackageInstanceKey::Root { .. }) {
            return Err(vec![io_diagnostic(
                "resolved package graph root does not have root identity",
            )]);
        }
        if !packages.contains_key(&root_instance) {
            return Err(vec![io_diagnostic(
                "resolved package graph has no root node",
            )]);
        }
        let mut validated = BTreeMap::new();
        for (key, node) in packages {
            if key != &root_instance
                && (matches!(key, PackageInstanceKey::Root { .. })
                    || node.kind() != ProjectKind::Library)
            {
                return Err(vec![io_diagnostic(
                    "resolved dependency nodes must be non-root library packages",
                )]);
            }
            if key != node.instance() {
                return Err(vec![io_diagnostic(
                    "resolved package graph key does not match its node identity",
                )]);
            }
            let rebuilt = Self::new(
                node.root(),
                node.manifest(),
                node.package.clone(),
                node.source(),
                node.kind,
            )?;
            let expected = match key {
                PackageInstanceKey::Root {
                    manifest,
                    name,
                    version,
                }
                | PackageInstanceKey::Path {
                    manifest,
                    name,
                    version,
                } => {
                    manifest == &node.manifest.to_string_lossy()
                        && name == node.package.name.as_str()
                        && version == node.package.version.as_str()
                }
                PackageInstanceKey::Registry {
                    name,
                    version,
                    checksum,
                    ..
                } => {
                    name == node.package.name.as_str()
                        && version == node.package.version.as_str()
                        && !checksum.is_empty()
                }
            };
            if !expected {
                return Err(vec![io_diagnostic(
                    "package instance identity does not match canonical manifest metadata",
                )]);
            }
            for (name, target) in &node.dependencies {
                let Some(target_node) = packages.get(target) else {
                    return Err(vec![io_diagnostic(format!(
                        "dependency edge `{name}` has no resolved target"
                    ))]);
                };
                if name != target_node.package.name.as_str() {
                    return Err(vec![io_diagnostic(format!(
                        "dependency edge `{name}` does not match target package `{}`",
                        target_node.package.name.as_str()
                    ))]);
                }
            }
            let mut canonical = rebuilt.packages.into_values().next().expect("root package");
            canonical.instance = key.clone();
            canonical.dependencies.clone_from(&node.dependencies);
            validated.insert(key.clone(), canonical);
        }
        validate_resolved_acyclic(&validated)?;
        let root_package = validated.get(&root_instance).expect("validated root");
        Ok(Self {
            root: root_package.root.clone(),
            manifest: root_package.manifest.clone(),
            package: root_package.package.clone(),
            source: root_package.source.clone(),
            kind: root_package.kind,
            root_instance,
            packages: validated,
        })
    }

    /// Canonical project root.
    #[must_use]
    pub fn root(&self) -> &Path {
        &self.root
    }
    /// Canonical direct manifest.
    #[must_use]
    pub fn manifest(&self) -> &Path {
        &self.manifest
    }
    /// Validated package metadata.
    #[must_use]
    pub const fn package(&self) -> &PackageMetadata {
        &self.package
    }
    /// Canonical selected source root file.
    #[must_use]
    pub fn source(&self) -> &Path {
        &self.source
    }
    /// Selected package class.
    #[must_use]
    pub const fn kind(&self) -> ProjectKind {
        self.kind
    }
    /// Exact root instance identity.
    #[must_use]
    pub const fn root_instance(&self) -> &PackageInstanceKey {
        &self.root_instance
    }
    /// All resolved nodes indexed by exact identity.
    #[must_use]
    pub const fn packages(&self) -> &BTreeMap<PackageInstanceKey, ResolvedPackage> {
        &self.packages
    }
    /// Canonical bootstrap build directory.
    #[must_use]
    pub fn build_directory(&self) -> PathBuf {
        self.root.join(".aether/build")
    }
    /// Canonical retained artifact path for this package.
    #[must_use]
    pub fn artifact_path(&self) -> PathBuf {
        let name = self.package.name.as_str();
        match self.kind {
            ProjectKind::Application => self.build_directory().join(name),
            ProjectKind::Library => self.build_directory().join(format!("{name}.aetherlib")),
        }
    }
}

fn instance_display_name(instance: &PackageInstanceKey) -> String {
    match instance {
        PackageInstanceKey::Root { name, .. }
        | PackageInstanceKey::Path { name, .. }
        | PackageInstanceKey::Registry { name, .. } => name.clone(),
    }
}

fn validate_resolved_acyclic(
    packages: &BTreeMap<PackageInstanceKey, ResolvedPackage>,
) -> Result<(), Vec<Diagnostic>> {
    fn visit(
        key: &PackageInstanceKey,
        packages: &BTreeMap<PackageInstanceKey, ResolvedPackage>,
        states: &mut BTreeMap<PackageInstanceKey, u8>,
        stack: &mut Vec<PackageInstanceKey>,
    ) -> Result<(), Vec<Diagnostic>> {
        match states.get(key).copied() {
            Some(2) => return Ok(()),
            Some(1) => {
                let position = stack.iter().position(|item| item == key).unwrap_or(0);
                let mut names = stack[position..]
                    .iter()
                    .map(instance_display_name)
                    .collect::<Vec<_>>();
                names.push(instance_display_name(key));
                return Err(vec![io_diagnostic(format!(
                    "resolved package cycle: {}",
                    names.join(" -> ")
                ))]);
            }
            _ => {}
        }
        states.insert(key.clone(), 1);
        stack.push(key.clone());
        for target in packages[key].dependencies.values() {
            visit(target, packages, states, stack)?;
        }
        stack.pop();
        states.insert(key.clone(), 2);
        Ok(())
    }

    let mut states = BTreeMap::new();
    let mut stack = Vec::new();
    for key in packages.keys() {
        visit(key, packages, &mut states, &mut stack)?;
    }
    Ok(())
}

impl StandaloneFile {
    /// Validates and canonicalizes one regular `.ae` file.
    pub fn new(path: impl AsRef<Path>) -> Result<Self, Vec<Diagnostic>> {
        let spelling = path.as_ref();
        let path = spelling.canonicalize().map_err(|error| {
            vec![io_diagnostic(format!(
                "could not resolve standalone source `{}`: {error}",
                spelling.display()
            ))]
        })?;
        let metadata = path.metadata().map_err(|error| {
            vec![io_diagnostic(format!(
                "could not inspect standalone source `{}`: {error}",
                path.display()
            ))]
        })?;
        if !metadata.is_file() {
            return Err(vec![io_diagnostic(format!(
                "standalone source is not a regular file: `{}`",
                path.display()
            ))]);
        }
        if path.extension().and_then(|extension| extension.to_str()) != Some("ae") {
            return Err(vec![io_diagnostic(format!(
                "standalone source must have extension `.ae`: `{}`",
                path.display()
            ))]);
        }
        Ok(Self { path })
    }

    /// Canonical source path.
    #[must_use]
    pub fn path(&self) -> &Path {
        &self.path
    }

    /// Explicit source root used for the existing standalone import graph.
    #[must_use]
    pub fn source_root(&self) -> &Path {
        self.path.parent().unwrap_or_else(|| Path::new("."))
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
    use super::source_root_for_entry;
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
