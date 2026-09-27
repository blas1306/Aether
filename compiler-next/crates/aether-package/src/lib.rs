//! Reusable Aether manifest, package-resolution, and lockfile layer.
//!
//! This crate deliberately contains no networking, CLI presentation, or compiler policy.

use std::collections::{BTreeMap, BTreeSet};
use std::fmt;
use std::fs::{self, OpenOptions};
use std::io::Write;
use std::path::{Component, Path, PathBuf};

use semver::Version;
use serde::{Deserialize, Serialize};

/// Logical registry identity used by package-manager V1.
pub const OFFICIAL_REGISTRY: &str = "official";
/// Lockfile name at a project root.
pub const LOCK_FILE: &str = "aether.lock";

/// Stable identity of one resolved package instance.
#[derive(Clone, Debug, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum PackageInstanceKey {
    /// The package owning the lockfile.
    Root {
        /// Canonical manifest spelling for this session.
        manifest: String,
        /// Exact package name.
        name: String,
        /// Exact package version.
        version: String,
    },
    /// A local path package.
    Path {
        /// Canonical manifest spelling for this session.
        manifest: String,
        /// Exact package name.
        name: String,
        /// Exact package version.
        version: String,
    },
    /// An immutable registry package.
    Registry {
        /// Logical registry identifier, never a URL.
        registry: String,
        /// Exact package name.
        name: String,
        /// Exact package version.
        version: String,
        /// Expected artifact checksum.
        checksum: String,
    },
}

impl PackageInstanceKey {
    /// Canonical in-session identity used by nominal compiler keys and mangling.
    #[must_use]
    pub fn canonical(&self) -> String {
        match self {
            Self::Root {
                manifest,
                name,
                version,
            } => format!("root:{manifest}#{name}@{version}"),
            Self::Path {
                manifest,
                name,
                version,
            } => format!("path:{manifest}#{name}@{version}"),
            Self::Registry {
                registry,
                name,
                version,
                checksum,
            } => {
                format!("registry:{registry}:{name}@{version}#{checksum}")
            }
        }
    }

    /// Exact package name carried by the identity.
    #[must_use]
    pub fn name(&self) -> &str {
        match self {
            Self::Root { name, .. } | Self::Path { name, .. } | Self::Registry { name, .. } => name,
        }
    }
}

/// Validated package/import name.
#[derive(Clone, Debug, PartialEq, Eq, PartialOrd, Ord)]
pub struct PackageName(String);

impl PackageName {
    /// Validates one exact, non-keyword Aether identifier.
    pub fn new(value: impl Into<String>) -> Result<Self, String> {
        const KEYWORDS: &[&str] = &[
            "alias", "as", "bool", "break", "catch", "const", "continue", "else", "enum", "false",
            "finally", "for", "if", "import", "in", "int", "match", "mut", "null", "package",
            "ref", "return", "struct", "throw", "true", "try", "while",
        ];
        let value = value.into();
        let mut bytes = value.bytes();
        let valid_start = bytes
            .next()
            .is_some_and(|byte| byte.is_ascii_alphabetic() || byte == b'_');
        let valid_tail = bytes.all(|byte| byte.is_ascii_alphanumeric() || byte == b'_');
        if !valid_start || !valid_tail || KEYWORDS.contains(&value.as_str()) {
            return Err(format!(
                "package name `{value}` is not a valid Aether namespace identifier"
            ));
        }
        Ok(Self(value))
    }

    /// Exact untranslated spelling.
    #[must_use]
    pub fn as_str(&self) -> &str {
        &self.0
    }
}

/// Validated exact `SemVer` package version.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct PackageVersion(String);

impl PackageVersion {
    /// Validates exact `SemVer` while retaining its original spelling.
    pub fn new(value: impl Into<String>) -> Result<Self, String> {
        let value = value.into();
        Version::parse(&value)
            .map_err(|error| format!("package version `{value}` is not valid SemVer: {error}"))?;
        Ok(Self(value))
    }

    /// Original exact spelling.
    #[must_use]
    pub fn as_str(&self) -> &str {
        &self.0
    }
}

/// Package metadata passed across the compiler boundary after resolution.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct PackageMetadata {
    /// Package/import identity.
    pub name: PackageName,
    /// Exact package version.
    pub version: PackageVersion,
    /// Optional language compatibility line.
    pub aether: Option<String>,
}

/// The single source target selected for a V1 package.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ProjectKind {
    /// Runnable root application.
    Application,
    /// Importable library package.
    Library,
}

/// One resolved node with owner-local exact dependency edges.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ResolvedPackage {
    /// Exact structural identity.
    pub instance: PackageInstanceKey,
    /// Canonical source root/materialization directory.
    pub root: PathBuf,
    /// Canonical direct manifest.
    pub manifest: PathBuf,
    /// Validated metadata.
    pub package: PackageMetadata,
    /// Canonical selected `.ae` entry.
    pub source: PathBuf,
    /// Package target class.
    pub kind: ProjectKind,
    /// Direct edges keyed by import root.
    pub dependencies: BTreeMap<String, PackageInstanceKey>,
}

impl ResolvedPackage {
    /// Constructs a resolved node. The compiler boundary revalidates graph invariants.
    #[must_use]
    pub fn new(
        instance: PackageInstanceKey,
        root: PathBuf,
        manifest: PathBuf,
        package: PackageMetadata,
        source: PathBuf,
        kind: ProjectKind,
        dependencies: BTreeMap<String, PackageInstanceKey>,
    ) -> Self {
        Self {
            instance,
            root,
            manifest,
            package,
            source,
            kind,
            dependencies,
        }
    }
    /// Exact structural identity.
    #[must_use]
    pub const fn instance(&self) -> &PackageInstanceKey {
        &self.instance
    }
    /// Canonical package root.
    #[must_use]
    pub fn root(&self) -> &Path {
        &self.root
    }
    /// Canonical direct manifest.
    #[must_use]
    pub fn manifest(&self) -> &Path {
        &self.manifest
    }
    /// Validated manifest metadata.
    #[must_use]
    pub const fn package(&self) -> &PackageMetadata {
        &self.package
    }
    /// Canonical selected source entry.
    #[must_use]
    pub fn source(&self) -> &Path {
        &self.source
    }
    /// Package target class.
    #[must_use]
    pub const fn kind(&self) -> ProjectKind {
        self.kind
    }
    /// Direct import-root edges owned by this package.
    #[must_use]
    pub const fn dependencies(&self) -> &BTreeMap<String, PackageInstanceKey> {
        &self.dependencies
    }
}

/// Complete deterministic multi-root resolved graph.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ResolvedGraph {
    /// Root package identity.
    pub root: PackageInstanceKey,
    /// All reachable nodes, shared only by exact identity.
    pub packages: BTreeMap<PackageInstanceKey, ResolvedPackage>,
}

/// Strict manifest schema used by path and fake/materialized registry packages.
#[derive(Clone, Debug, Deserialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct Manifest {
    /// Required package table.
    pub package: ManifestPackage,
    /// Optional application table.
    pub application: Option<ManifestApplication>,
    /// Direct dependencies.
    #[serde(default)]
    pub dependencies: BTreeMap<String, DependencySpec>,
}

/// Package table in `aether.toml`.
#[derive(Clone, Debug, Deserialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct ManifestPackage {
    /// Exact package/import name.
    pub name: String,
    /// Exact package `SemVer`.
    pub version: String,
    /// Optional Aether language compatibility line.
    pub aether: Option<String>,
}

/// Application table in `aether.toml`.
#[derive(Clone, Debug, Deserialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct ManifestApplication {
    /// Optional relative application entry.
    pub entry: Option<PathBuf>,
}

/// One dependency with exactly one source class.
#[derive(Clone, Debug, Deserialize, PartialEq, Eq)]
#[serde(untagged)]
pub enum DependencySpec {
    /// Official-registry version requirement.
    Registry(String),
    /// Local path relative to the declaring manifest.
    Path(DependencyPath),
}

/// Strict path dependency table.
#[derive(Clone, Debug, Deserialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct DependencyPath {
    /// Locator relative to the declaring manifest.
    pub path: PathBuf,
}

/// V1 version requirement.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct VersionRequirement {
    original: String,
    kind: RequirementKind,
}

#[derive(Clone, Debug, PartialEq, Eq)]
enum RequirementKind {
    Exact(Version),
    Compatible { minimum: Version, maximum: Version },
}

impl VersionRequirement {
    /// Parses only `Compatible`, `^Compatible`, or `=FullSemVer`.
    pub fn parse(text: &str) -> Result<Self, String> {
        if text.is_empty() {
            return Err("version requirement is empty".to_owned());
        }
        let kind = if let Some(exact) = text.strip_prefix('=') {
            if exact.is_empty() {
                return Err(format!("invalid V1 version requirement `{text}`"));
            }
            RequirementKind::Exact(Version::parse(exact).map_err(|_| {
                format!(
                    "invalid V1 version requirement `{text}`; exact requirements need full SemVer"
                )
            })?)
        } else {
            let compatible = text.strip_prefix('^').unwrap_or(text);
            let parts = compatible.split('.').collect::<Vec<_>>();
            if !(1..=3).contains(&parts.len())
                || parts.iter().any(|part| !valid_numeric_component(part))
            {
                return Err(format!("invalid V1 version requirement `{text}`"));
            }
            let major = parts[0]
                .parse::<u64>()
                .map_err(|_| format!("invalid V1 version requirement `{text}`"))?;
            let minor = parts
                .get(1)
                .unwrap_or(&"0")
                .parse::<u64>()
                .map_err(|_| format!("invalid V1 version requirement `{text}`"))?;
            let patch = parts
                .get(2)
                .unwrap_or(&"0")
                .parse::<u64>()
                .map_err(|_| format!("invalid V1 version requirement `{text}`"))?;
            let minimum = Version::new(major, minor, patch);
            let maximum = if major > 0 {
                Version::new(
                    major.checked_add(1).ok_or_else(|| {
                        format!("invalid V1 version requirement `{text}`: upper bound overflows")
                    })?,
                    0,
                    0,
                )
            } else if minor > 0 {
                Version::new(
                    0,
                    minor.checked_add(1).ok_or_else(|| {
                        format!("invalid V1 version requirement `{text}`: upper bound overflows")
                    })?,
                    0,
                )
            } else {
                Version::new(
                    0,
                    0,
                    patch.checked_add(1).ok_or_else(|| {
                        format!("invalid V1 version requirement `{text}`: upper bound overflows")
                    })?,
                )
            };
            RequirementKind::Compatible { minimum, maximum }
        };
        Ok(Self {
            original: text.to_owned(),
            kind,
        })
    }

    /// Whether an exact `SemVer` satisfies the requirement.
    #[must_use]
    pub fn matches(&self, version: &Version) -> bool {
        match &self.kind {
            RequirementKind::Exact(exact) => exact == version,
            RequirementKind::Compatible { minimum, maximum } => {
                version.pre.is_empty() && version >= minimum && version < maximum
            }
        }
    }

    /// Original requirement spelling.
    #[must_use]
    pub fn as_str(&self) -> &str {
        &self.original
    }
}

fn valid_numeric_component(value: &str) -> bool {
    !value.is_empty()
        && value.bytes().all(|byte| byte.is_ascii_digit())
        && (value == "0" || !value.starts_with('0'))
}

/// Version summary returned while enumerating registry candidates.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct RegistryVersion {
    /// Exact `SemVer` spelling.
    pub version: String,
    /// Yanked versions are excluded from new resolution.
    pub yanked: bool,
}

/// Exact immutable metadata plus a conceptually materialized source root.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct RegistryPackageMetadata {
    /// Exact package name.
    pub name: String,
    /// Exact version spelling.
    pub version: String,
    /// Expected immutable artifact checksum.
    pub checksum: String,
    /// Exact direct dependency metadata.
    pub dependencies: BTreeMap<String, DependencySpec>,
    /// Fake/provider materialization root used to build the compiler graph. No cache semantics
    /// are implied by this field.
    pub root: PathBuf,
}

/// Network-free registry resolution boundary.
pub trait RegistryProvider {
    /// Enumerates all visible versions; caller imposes deterministic ordering.
    fn versions(&self, name: &PackageName) -> Result<Vec<RegistryVersion>, String>;
    /// Returns exact metadata even when that version is yanked, enabling lock reuse.
    fn metadata(
        &self,
        name: &PackageName,
        version: &Version,
    ) -> Result<RegistryPackageMetadata, String>;
}

/// Resolves from current manifests without consulting a lock.
pub fn resolve(
    root: &Path,
    registry: Option<&dyn RegistryProvider>,
) -> Result<ResolvedGraph, String> {
    Resolver::new(registry).resolve_root(root)
}

/// Reuses and validates an existing lock, or creates one atomically when absent.
pub fn sync(root: &Path, registry: Option<&dyn RegistryProvider>) -> Result<ResolvedGraph, String> {
    let root = canonical_directory(root, "project root")?;
    let lock_path = root.join(LOCK_FILE);
    if lock_path.exists() {
        let lock = read_lock(&lock_path)?;
        return validate_locked(&root, &lock, registry)
            .map_err(|error| format!("{error}; run `aether update` to create a new resolution"));
    }
    let graph = resolve(&root, registry)?;
    let text = serialize_lock(&root, &graph)?;
    write_atomic(&lock_path, text.as_bytes())?;
    Ok(graph)
}

/// Resolves every edge anew and atomically replaces the lock on success.
pub fn update(
    root: &Path,
    registry: Option<&dyn RegistryProvider>,
) -> Result<ResolvedGraph, String> {
    let root = canonical_directory(root, "project root")?;
    let graph = resolve(&root, registry)?;
    let text = serialize_lock(&root, &graph)?;
    write_atomic(&root.join(LOCK_FILE), text.as_bytes())?;
    Ok(graph)
}

struct Resolver<'a> {
    registry: Option<&'a dyn RegistryProvider>,
    packages: BTreeMap<PackageInstanceKey, ResolvedPackage>,
    by_manifest: BTreeMap<PathBuf, PackageInstanceKey>,
    stack: Vec<(PackageInstanceKey, String)>,
}

impl<'a> Resolver<'a> {
    fn new(registry: Option<&'a dyn RegistryProvider>) -> Self {
        Self {
            registry,
            packages: BTreeMap::new(),
            by_manifest: BTreeMap::new(),
            stack: Vec::new(),
        }
    }

    fn resolve_root(mut self, root: &Path) -> Result<ResolvedGraph, String> {
        let root = self.resolve_path(root, None, true)?;
        Ok(ResolvedGraph {
            root,
            packages: self.packages,
        })
    }

    #[allow(clippy::too_many_lines)]
    fn resolve_path(
        &mut self,
        root: &Path,
        expected_name: Option<&str>,
        is_root: bool,
    ) -> Result<PackageInstanceKey, String> {
        let root = canonical_directory(root, "path dependency directory")?;
        let manifest_path = direct_manifest(&root)?;
        if let Some(existing) = self.by_manifest.get(&manifest_path) {
            if self.stack.iter().any(|(active, _)| active == existing) {
                return Err(self.cycle(existing));
            }
            if let Some(expected) = expected_name {
                if existing.name() != expected {
                    return Err(name_mismatch(expected, existing.name()));
                }
            }
            return Ok(existing.clone());
        }
        let manifest = read_manifest(&manifest_path)?;
        let package = validate_manifest_package(&manifest)?;
        if let Some(expected) = expected_name {
            if package.name.as_str() != expected {
                return Err(name_mismatch(expected, package.name.as_str()));
            }
        }
        let instance = if is_root {
            PackageInstanceKey::Root {
                manifest: path_utf8(&manifest_path)?.to_owned(),
                name: package.name.as_str().to_owned(),
                version: package.version.as_str().to_owned(),
            }
        } else {
            PackageInstanceKey::Path {
                manifest: path_utf8(&manifest_path)?.to_owned(),
                name: package.name.as_str().to_owned(),
                version: package.version.as_str().to_owned(),
            }
        };
        self.by_manifest
            .insert(manifest_path.clone(), instance.clone());
        self.push(&instance, package.name.as_str())?;
        let dependencies = self.resolve_dependencies(&root, &manifest.dependencies, false)?;
        self.stack.pop();
        let (source, kind) = select_source(&root, manifest.application.as_ref(), is_root)?;
        self.packages.insert(
            instance.clone(),
            ResolvedPackage {
                instance: instance.clone(),
                root,
                manifest: manifest_path,
                package,
                source,
                kind,
                dependencies,
            },
        );
        Ok(instance)
    }

    fn resolve_dependencies(
        &mut self,
        owner_root: &Path,
        dependencies: &BTreeMap<String, DependencySpec>,
        registry_owner: bool,
    ) -> Result<BTreeMap<String, PackageInstanceKey>, String> {
        let mut resolved = BTreeMap::new();
        for (name, dependency) in dependencies {
            let package_name = PackageName::new(name.clone())?;
            let target = match dependency {
                DependencySpec::Path(path) => {
                    if registry_owner {
                        return Err(format!(
                            "registry package `{}` declares forbidden path dependency `{name}`",
                            self.stack.last().map_or("<unknown>", |(_, value)| value)
                        ));
                    }
                    if path.path.as_os_str().is_empty() {
                        return Err(format!("dependency `{name}` has an empty path"));
                    }
                    self.resolve_path(&owner_root.join(&path.path), Some(name), false)?
                }
                DependencySpec::Registry(requirement) => {
                    let requirement = VersionRequirement::parse(requirement)
                        .map_err(|error| format!("dependency `{name}`: {error}"))?;
                    self.resolve_registry(&package_name, &requirement)?
                }
            };
            resolved.insert(name.clone(), target);
        }
        Ok(resolved)
    }

    fn resolve_registry(
        &mut self,
        name: &PackageName,
        requirement: &VersionRequirement,
    ) -> Result<PackageInstanceKey, String> {
        let provider = self.registry.ok_or_else(|| {
            format!(
                "registry dependency `{}` cannot be resolved: registry transport is not available",
                name.as_str()
            )
        })?;
        let mut candidates = Vec::new();
        for candidate in provider.versions(name)? {
            let parsed = Version::parse(&candidate.version).map_err(|error| {
                format!(
                    "registry returned invalid version `{}` for `{}`: {error}",
                    candidate.version,
                    name.as_str()
                )
            })?;
            if !candidate.yanked && requirement.matches(&parsed) {
                candidates.push((parsed, candidate.version));
            }
        }
        candidates.sort_by(|left, right| left.0.cmp(&right.0).then_with(|| left.1.cmp(&right.1)));
        let (version, spelling) = candidates.pop().ok_or_else(|| {
            format!(
                "registry has no non-yanked version of `{}` satisfying `{}`",
                name.as_str(),
                requirement.as_str()
            )
        })?;
        let metadata = provider.metadata(name, &version)?;
        if metadata.name != name.as_str() {
            return Err(name_mismatch(name.as_str(), &metadata.name));
        }
        if metadata.version != spelling {
            return Err(format!(
                "registry metadata for `{}` returned version `{}` instead of selected `{spelling}`",
                name.as_str(),
                metadata.version
            ));
        }
        if metadata.checksum.is_empty() {
            return Err(format!(
                "registry metadata for `{}@{spelling}` has an empty checksum",
                name.as_str()
            ));
        }
        let instance = PackageInstanceKey::Registry {
            registry: OFFICIAL_REGISTRY.to_owned(),
            name: name.as_str().to_owned(),
            version: spelling,
            checksum: metadata.checksum.clone(),
        };
        if self.stack.iter().any(|(active, _)| active == &instance) {
            return Err(self.cycle(&instance));
        }
        if self.packages.contains_key(&instance) {
            return Ok(instance);
        }
        let root = canonical_directory(&metadata.root, "registry package materialization")?;
        let manifest_path = direct_manifest(&root)?;
        let manifest = read_manifest(&manifest_path)?;
        let package = validate_manifest_package(&manifest)?;
        if package.name.as_str() != name.as_str() {
            return Err(name_mismatch(name.as_str(), package.name.as_str()));
        }
        if package.version.as_str() != metadata.version {
            return Err(format!(
                "registry materialization version does not match metadata for `{}`",
                name.as_str()
            ));
        }
        if manifest.dependencies != metadata.dependencies {
            return Err(format!(
                "registry materialization dependencies do not match exact metadata for `{}@{}`",
                name.as_str(),
                metadata.version
            ));
        }
        self.push(&instance, name.as_str())?;
        let dependencies = self.resolve_dependencies(&root, &metadata.dependencies, true)?;
        self.stack.pop();
        let (source, kind) = select_source(&root, manifest.application.as_ref(), false)?;
        self.packages.insert(
            instance.clone(),
            ResolvedPackage {
                instance: instance.clone(),
                root,
                manifest: manifest_path,
                package,
                source,
                kind,
                dependencies,
            },
        );
        Ok(instance)
    }

    fn push(&mut self, instance: &PackageInstanceKey, name: &str) -> Result<(), String> {
        if self.stack.iter().any(|(active, _)| active == instance) {
            return Err(self.cycle(instance));
        }
        self.stack.push((instance.clone(), name.to_owned()));
        Ok(())
    }

    fn cycle(&self, target: &PackageInstanceKey) -> String {
        let position = self
            .stack
            .iter()
            .position(|(instance, _)| instance == target)
            .unwrap_or(0);
        let mut names = self.stack[position..]
            .iter()
            .map(|(_, name)| name.clone())
            .collect::<Vec<_>>();
        names.push(target.name().to_owned());
        format!("path dependency cycle: {}", names.join(" -> "))
    }
}

fn validate_manifest_package(manifest: &Manifest) -> Result<PackageMetadata, String> {
    let name = PackageName::new(manifest.package.name.clone())?;
    let version = PackageVersion::new(manifest.package.version.clone())?;
    if manifest
        .package
        .aether
        .as_deref()
        .is_some_and(|value| value != "1")
    {
        return Err("package.aether currently accepts only the compatibility line `1`".to_owned());
    }
    for (dependency, spec) in &manifest.dependencies {
        PackageName::new(dependency.clone())?;
        if let DependencySpec::Registry(requirement) = spec {
            VersionRequirement::parse(requirement)
                .map_err(|error| format!("dependency `{dependency}`: {error}"))?;
        }
    }
    Ok(PackageMetadata {
        name,
        version,
        aether: manifest.package.aether.clone(),
    })
}

fn name_mismatch(expected: &str, actual: &str) -> String {
    format!("dependency key `{expected}` does not match package.name `{actual}`")
}

fn canonical_directory(path: &Path, label: &str) -> Result<PathBuf, String> {
    let canonical = path
        .canonicalize()
        .map_err(|error| format!("cannot resolve {label} `{}`: {error}", path.display()))?;
    if !canonical.is_dir() {
        return Err(format!("{label} `{}` is not a directory", path.display()));
    }
    Ok(canonical)
}

fn direct_manifest(root: &Path) -> Result<PathBuf, String> {
    let direct = root.join("aether.toml");
    let canonical = direct.canonicalize().map_err(|error| {
        format!(
            "package target `{}` requires direct `aether.toml`: {error}",
            root.display()
        )
    })?;
    if !canonical.is_file() || canonical.parent() != Some(root) {
        return Err(format!(
            "package target `{}` requires a direct regular `aether.toml`",
            root.display()
        ));
    }
    Ok(canonical)
}

fn read_manifest(path: &Path) -> Result<Manifest, String> {
    let text = fs::read_to_string(path)
        .map_err(|error| format!("cannot read UTF-8 manifest `{}`: {error}", path.display()))?;
    toml::from_str(&text).map_err(|error| format!("invalid manifest `{}`: {error}", path.display()))
}

fn select_source(
    root: &Path,
    application: Option<&ManifestApplication>,
    allow_application: bool,
) -> Result<(PathBuf, ProjectKind), String> {
    let app = if let Some(entry) = application.and_then(|table| table.entry.as_deref()) {
        Some(resolve_entry(root, entry)?)
    } else {
        conventional_source(root, "src/main.ae")?
    };
    let library = conventional_source(root, "src/lib.ae")?;
    match (app, library) {
        (Some(_), Some(_)) => Err(
            "project has both application and library targets; multiple targets are not supported"
                .to_owned(),
        ),
        (Some(source), None) if allow_application => Ok((source, ProjectKind::Application)),
        (Some(_), None) => Err("dependencies must be libraries with `src/lib.ae`".to_owned()),
        (None, Some(source)) => Ok((source, ProjectKind::Library)),
        (None, None) => {
            Err("package has no source root (`src/main.ae` or `src/lib.ae`)".to_owned())
        }
    }
}

fn resolve_entry(root: &Path, entry: &Path) -> Result<PathBuf, String> {
    if entry.is_absolute() || entry.extension().and_then(|value| value.to_str()) != Some("ae") {
        return Err("application.entry must be a relative path ending in `.ae`".to_owned());
    }
    let resolved = root.join(entry).canonicalize().map_err(|error| {
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
            let resolved = spelling
                .canonicalize()
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

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields, rename_all = "kebab-case")]
struct LockFile {
    lock_version: u32,
    root: String,
    package: Vec<LockPackage>,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct LockPackage {
    id: String,
    name: String,
    version: String,
    source: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    checksum: Option<String>,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    dependencies: Vec<LockEdge>,
}

#[derive(Clone, Debug, Deserialize, Serialize, PartialEq, Eq, PartialOrd, Ord)]
#[serde(deny_unknown_fields)]
struct LockEdge {
    name: String,
    target: String,
}

fn serialize_lock(lock_root: &Path, graph: &ResolvedGraph) -> Result<String, String> {
    let lock = lock_from_graph(lock_root, graph)?;
    let body =
        toml::to_string(&lock).map_err(|error| format!("cannot serialize lockfile: {error}"))?;
    Ok(format!(
        "# This file is machine-generated by Aether. Do not edit.\n{body}"
    ))
}

fn lock_from_graph(lock_root: &Path, graph: &ResolvedGraph) -> Result<LockFile, String> {
    let mut ids = BTreeMap::new();
    for instance in graph.packages.keys() {
        ids.insert(instance.clone(), lock_id(lock_root, instance)?);
    }
    let root_id = ids
        .get(&graph.root)
        .ok_or_else(|| "resolved graph has no root node".to_owned())?
        .clone();
    let mut package = Vec::new();
    for (instance, node) in &graph.packages {
        let (source, checksum) = match instance {
            PackageInstanceKey::Root { .. } => ("root".to_owned(), None),
            PackageInstanceKey::Path { manifest, .. } => {
                let root = Path::new(manifest)
                    .parent()
                    .ok_or_else(|| "path manifest has no parent".to_owned())?;
                (
                    format!("path+{}", portable_relative(lock_root, root)?),
                    None,
                )
            }
            PackageInstanceKey::Registry {
                registry, checksum, ..
            } => (format!("registry+{registry}"), Some(checksum.clone())),
        };
        let mut dependencies = node
            .dependencies
            .iter()
            .map(|(name, target)| {
                Ok(LockEdge {
                    name: name.clone(),
                    target: ids
                        .get(target)
                        .ok_or_else(|| format!("dependency edge `{name}` has no resolved target"))?
                        .clone(),
                })
            })
            .collect::<Result<Vec<_>, String>>()?;
        dependencies.sort();
        package.push(LockPackage {
            id: ids[instance].clone(),
            name: node.package.name.as_str().to_owned(),
            version: node.package.version.as_str().to_owned(),
            source,
            checksum,
            dependencies,
        });
    }
    package.sort_by(|left, right| left.id.cmp(&right.id));
    Ok(LockFile {
        lock_version: 1,
        root: root_id,
        package,
    })
}

fn lock_id(lock_root: &Path, instance: &PackageInstanceKey) -> Result<String, String> {
    match instance {
        PackageInstanceKey::Root { name, version, .. } => Ok(format!("root:{name}@{version}")),
        PackageInstanceKey::Path {
            manifest,
            name,
            version,
        } => {
            let root = Path::new(manifest)
                .parent()
                .ok_or_else(|| "path manifest has no parent".to_owned())?;
            Ok(format!(
                "path+{}#{name}@{version}",
                portable_relative(lock_root, root)?
            ))
        }
        PackageInstanceKey::Registry {
            registry,
            name,
            version,
            checksum,
        } => Ok(format!("registry+{registry}:{name}@{version}#{checksum}")),
    }
}

fn portable_relative(base: &Path, target: &Path) -> Result<String, String> {
    let base = base
        .canonicalize()
        .map_err(|error| format!("cannot canonicalize lock root: {error}"))?;
    let target = target
        .canonicalize()
        .map_err(|error| format!("cannot canonicalize path package: {error}"))?;
    let base_components = normal_components(&base)?;
    let target_components = normal_components(&target)?;
    if base_components.first().map(|value| &value.0)
        != target_components.first().map(|value| &value.0)
    {
        return Err(format!(
            "path `{}` cannot be represented relative to lock root `{}`",
            target.display(),
            base.display()
        ));
    }
    let mut shared = 0;
    while shared < base_components.len()
        && shared < target_components.len()
        && base_components[shared] == target_components[shared]
    {
        shared += 1;
    }
    let mut output = vec!["..".to_owned(); base_components.len().saturating_sub(shared)];
    output.extend(
        target_components[shared..]
            .iter()
            .map(|(_, text)| text.clone()),
    );
    Ok(if output.is_empty() {
        ".".to_owned()
    } else {
        output.join("/")
    })
}

fn normal_components(path: &Path) -> Result<Vec<(u8, String)>, String> {
    path.components()
        .map(|component| {
            match component {
                Component::Prefix(value) => {
                    value.as_os_str().to_str().map(|text| (0, text.to_owned()))
                }
                Component::RootDir => Some((1, String::new())),
                Component::Normal(value) => value.to_str().map(|text| (2, text.to_owned())),
                Component::CurDir => Some((3, ".".to_owned())),
                Component::ParentDir => Some((4, "..".to_owned())),
            }
            .ok_or_else(|| format!("path `{}` is not portable UTF-8", path.display()))
        })
        .collect()
}

fn path_utf8(path: &Path) -> Result<&str, String> {
    path.to_str()
        .ok_or_else(|| format!("path `{}` is not valid UTF-8", path.display()))
}

fn read_lock(path: &Path) -> Result<LockFile, String> {
    let text = fs::read_to_string(path)
        .map_err(|error| format!("cannot read lockfile `{}`: {error}", path.display()))?;
    let lock: LockFile = toml::from_str(&text)
        .map_err(|error| format!("invalid lockfile `{}`: {error}", path.display()))?;
    validate_lock_shape(&lock)?;
    Ok(lock)
}

fn visit_locked_node<'a>(
    id: &'a str,
    by_id: &BTreeMap<&'a str, &'a LockPackage>,
    states: &mut BTreeMap<&'a str, u8>,
) -> Result<(), String> {
    if states.get(id) == Some(&1) {
        return Err(format!("lock graph contains a cycle through `{id}`"));
    }
    if states.get(id) == Some(&2) {
        return Ok(());
    }
    states.insert(id, 1);
    for edge in &by_id[id].dependencies {
        visit_locked_node(&edge.target, by_id, states)?;
    }
    states.insert(id, 2);
    Ok(())
}

fn validate_lock_shape(lock: &LockFile) -> Result<(), String> {
    if lock.lock_version != 1 {
        return Err(format!("unsupported lock-version {}", lock.lock_version));
    }
    let mut ids = BTreeSet::new();
    for package in &lock.package {
        if !ids.insert(package.id.as_str()) {
            return Err(format!("duplicate lock package id `{}`", package.id));
        }
    }
    if !ids.contains(lock.root.as_str()) {
        return Err("lock root is dangling".to_owned());
    }
    for package in &lock.package {
        let mut names = BTreeSet::new();
        for edge in &package.dependencies {
            if !ids.contains(edge.target.as_str()) {
                return Err(format!(
                    "lock edge `{}` has dangling target `{}`",
                    edge.name, edge.target
                ));
            }
            if !names.insert(edge.name.as_str()) {
                return Err(format!(
                    "lock package `{}` has duplicate dependency `{}`",
                    package.id, edge.name
                ));
            }
        }
    }
    let by_id = lock
        .package
        .iter()
        .map(|package| (package.id.as_str(), package))
        .collect::<BTreeMap<_, _>>();
    let mut states = BTreeMap::new();
    visit_locked_node(&lock.root, &by_id, &mut states)?;
    if states.len() != lock.package.len() {
        return Err("lock contains packages unreachable from root".to_owned());
    }
    Ok(())
}

#[allow(clippy::too_many_lines)]
fn validate_locked(
    lock_root: &Path,
    lock: &LockFile,
    registry: Option<&dyn RegistryProvider>,
) -> Result<ResolvedGraph, String> {
    validate_lock_shape(lock)?;
    let entries = lock
        .package
        .iter()
        .map(|entry| (entry.id.clone(), entry))
        .collect::<BTreeMap<_, _>>();
    let mut instances = BTreeMap::new();
    let mut manifests = BTreeMap::new();
    for entry in &lock.package {
        PackageName::new(entry.name.clone())?;
        PackageVersion::new(entry.version.clone())?;
        let (instance, root, manifest, parsed) = if entry.source == "root" {
            if entry.checksum.is_some() {
                return Err("root lock node cannot have checksum".to_owned());
            }
            let manifest = direct_manifest(lock_root)?;
            let parsed = read_manifest(&manifest)?;
            (
                PackageInstanceKey::Root {
                    manifest: path_utf8(&manifest)?.to_owned(),
                    name: entry.name.clone(),
                    version: entry.version.clone(),
                },
                lock_root.to_path_buf(),
                manifest,
                parsed,
            )
        } else if let Some(locator) = entry.source.strip_prefix("path+") {
            if entry.checksum.is_some()
                || Path::new(locator).is_absolute()
                || locator.contains('\\')
            {
                return Err(format!("invalid portable path source `{}`", entry.source));
            }
            let root = canonical_directory(&lock_root.join(locator), "locked path dependency")?;
            let manifest = direct_manifest(&root)?;
            let parsed = read_manifest(&manifest)?;
            (
                PackageInstanceKey::Path {
                    manifest: path_utf8(&manifest)?.to_owned(),
                    name: entry.name.clone(),
                    version: entry.version.clone(),
                },
                root,
                manifest,
                parsed,
            )
        } else if entry.source == format!("registry+{OFFICIAL_REGISTRY}") {
            let checksum = entry
                .checksum
                .clone()
                .ok_or_else(|| format!("registry lock node `{}` has no checksum", entry.id))?;
            let provider = registry.ok_or_else(|| format!("registry dependency `{}` cannot be validated: registry transport is not available", entry.name))?;
            let name = PackageName::new(entry.name.clone())?;
            let version = Version::parse(&entry.version)
                .map_err(|error| format!("invalid locked version: {error}"))?;
            let metadata = provider.metadata(&name, &version)?;
            if metadata.name != entry.name
                || metadata.version != entry.version
                || metadata.checksum != checksum
            {
                return Err(format!(
                    "registry metadata/checksum mismatch for `{}@{}`",
                    entry.name, entry.version
                ));
            }
            if metadata
                .dependencies
                .values()
                .any(|dependency| matches!(dependency, DependencySpec::Path(_)))
            {
                return Err(format!(
                    "registry package `{}@{}` declares a forbidden path dependency",
                    entry.name, entry.version
                ));
            }
            let root = canonical_directory(&metadata.root, "registry package materialization")?;
            let manifest = direct_manifest(&root)?;
            let parsed = read_manifest(&manifest)?;
            if parsed.dependencies != metadata.dependencies {
                return Err(format!(
                    "registry materialization dependencies do not match exact metadata for `{}@{}`",
                    entry.name, entry.version
                ));
            }
            (
                PackageInstanceKey::Registry {
                    registry: OFFICIAL_REGISTRY.to_owned(),
                    name: entry.name.clone(),
                    version: entry.version.clone(),
                    checksum,
                },
                root,
                manifest,
                parsed,
            )
        } else {
            return Err(format!("unsupported lock source `{}`", entry.source));
        };
        let package = validate_manifest_package(&parsed)?;
        if package.name.as_str() != entry.name || package.version.as_str() != entry.version {
            return Err(format!(
                "locked package `{}` no longer matches manifest name/version",
                entry.id
            ));
        }
        let expected_id = lock_id(lock_root, &instance)?;
        if expected_id != entry.id {
            return Err(format!(
                "lock package id `{}` does not match exact identity `{expected_id}`",
                entry.id
            ));
        }
        if instances.values().any(|existing| existing == &instance) {
            return Err(format!("duplicate exact package identity `{}`", entry.id));
        }
        instances.insert(entry.id.clone(), instance);
        manifests.insert(entry.id.clone(), (root, manifest, parsed, package));
    }
    let mut packages = BTreeMap::new();
    for entry in &lock.package {
        let instance = instances[&entry.id].clone();
        let (root, manifest_path, manifest, package) =
            manifests.remove(&entry.id).expect("locked manifest");
        let actual_names = manifest
            .dependencies
            .keys()
            .cloned()
            .collect::<BTreeSet<_>>();
        let locked_names = entry
            .dependencies
            .iter()
            .map(|edge| edge.name.clone())
            .collect::<BTreeSet<_>>();
        if actual_names != locked_names {
            return Err(format!(
                "locked dependency topology changed for `{}`",
                entry.name
            ));
        }
        let mut dependencies = BTreeMap::new();
        for edge in &entry.dependencies {
            let target_entry = entries[&edge.target];
            let spec = &manifest.dependencies[&edge.name];
            match spec {
                DependencySpec::Registry(requirement) => {
                    if !target_entry.source.starts_with("registry+") {
                        return Err(format!("dependency `{}` changed source class", edge.name));
                    }
                    let requirement = VersionRequirement::parse(requirement)?;
                    let version = Version::parse(&target_entry.version)
                        .map_err(|error| format!("invalid locked version: {error}"))?;
                    if !requirement.matches(&version) {
                        return Err(format!(
                            "locked version `{version}` no longer satisfies dependency `{}`",
                            edge.name
                        ));
                    }
                }
                DependencySpec::Path(path) => {
                    if !target_entry.source.starts_with("path+") {
                        return Err(format!("dependency `{}` changed source class", edge.name));
                    }
                    let actual = direct_manifest(&canonical_directory(
                        &root.join(&path.path),
                        "path dependency directory",
                    )?)?;
                    match &instances[&edge.target] {
                        PackageInstanceKey::Path { manifest, .. }
                            if Path::new(manifest) == actual => {}
                        _ => {
                            return Err(format!(
                                "locked path target changed for dependency `{}`",
                                edge.name
                            ));
                        }
                    }
                }
            }
            let target = instances[&edge.target].clone();
            if target.name() != edge.name {
                return Err(name_mismatch(&edge.name, target.name()));
            }
            dependencies.insert(edge.name.clone(), target);
        }
        let is_root = entry.id == lock.root;
        let (source, kind) = select_source(&root, manifest.application.as_ref(), is_root)?;
        packages.insert(
            instance.clone(),
            ResolvedPackage {
                instance,
                root,
                manifest: manifest_path,
                package,
                source,
                kind,
                dependencies,
            },
        );
    }
    let graph = ResolvedGraph {
        root: instances[&lock.root].clone(),
        packages,
    };
    let regenerated = lock_from_graph(lock_root, &graph)?;
    if regenerated.root != lock.root
        || regenerated
            .package
            .iter()
            .map(|entry| &entry.id)
            .collect::<Vec<_>>()
            != lock
                .package
                .iter()
                .map(|entry| &entry.id)
                .collect::<Vec<_>>()
    {
        return Err("lockfile is not canonical for the resolved graph".to_owned());
    }
    Ok(graph)
}

fn write_atomic(path: &Path, bytes: &[u8]) -> Result<(), String> {
    let parent = path
        .parent()
        .ok_or_else(|| "lockfile has no parent directory".to_owned())?;
    let temporary = parent.join(format!(".{LOCK_FILE}.tmp-{}", std::process::id()));
    let result = (|| {
        let mut file = OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&temporary)
            .map_err(|error| {
                format!(
                    "cannot create temporary lockfile `{}`: {error}",
                    temporary.display()
                )
            })?;
        file.write_all(bytes)
            .map_err(|error| format!("cannot write temporary lockfile: {error}"))?;
        file.sync_all()
            .map_err(|error| format!("cannot sync temporary lockfile: {error}"))?;
        fs::rename(&temporary, path).map_err(|error| {
            format!(
                "cannot atomically replace lockfile `{}`: {error}",
                path.display()
            )
        })
    })();
    if result.is_err() {
        let _ = fs::remove_file(&temporary);
    }
    result
}

impl fmt::Display for VersionRequirement {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(&self.original)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn requirement_grammar_and_caret_semantics() {
        for (text, accepted, rejected) in [
            ("1", "1.9.9", "2.0.0"),
            ("1.2", "1.8.0", "2.0.0"),
            ("1.2.3", "1.2.3", "2.0.0"),
            ("0.2", "0.2.9", "0.3.0"),
            ("0.2.3", "0.2.8", "0.3.0"),
            ("0.0.3", "0.0.3", "0.0.4"),
        ] {
            let requirement = VersionRequirement::parse(text).unwrap();
            assert!(
                requirement.matches(&Version::parse(accepted).unwrap()),
                "{text}"
            );
            assert!(
                !requirement.matches(&Version::parse(rejected).unwrap()),
                "{text}"
            );
            assert!(
                !requirement.matches(&Version::parse("1.5.0-alpha.1").unwrap()),
                "{text}"
            );
        }
        let exact = VersionRequirement::parse("=1.2.3-alpha.1+build").unwrap();
        assert!(exact.matches(&Version::parse("1.2.3-alpha.1+build").unwrap()));
        for invalid in [
            "",
            "*",
            "1.*",
            "~1.2",
            ">=1",
            "1 - 2",
            "1 || 2",
            "1,2",
            "01",
            "1.02",
            "^=1.2.3",
            "=1.2",
            "18446744073709551615",
            "0.18446744073709551615",
            "0.0.18446744073709551615",
        ] {
            assert!(VersionRequirement::parse(invalid).is_err(), "{invalid}");
        }
    }
}
