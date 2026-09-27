//! Optional virtual and user environment state built on the package V1 resolver.

use std::fs::{self, OpenOptions};
use std::path::{Path, PathBuf};

use fs2::FileExt;

use crate::{
    DependencySpec, LOCK_FILE, MANIFEST_FILE, PackageInstanceKey, ProjectKind, RegistryProvider,
    ResolvedGraph, Resolver, edit_dependency, latest_registry_release, parse_manifest_text,
    serialize_lock, short_compatible_requirement, sync_directory, write_exclusive_synced,
};

const ENVIRONMENT_MARKER: &str = "state/environment-v1";
const ENVIRONMENT_LOCK: &str = ".aether-package.lock";
const TRANSACTION_MARKER: &str = ".aether-environment-transaction";
const MANIFEST_BACKUP: &str = ".aether-env-manifest-backup";
const LOCK_BACKUP: &str = ".aether-env-lock-backup";
const BIN_BACKUP: &str = ".aether-env-bin-backup";
const MANIFEST_NEW: &str = ".aether-env-manifest-new";
const LOCK_NEW: &str = ".aether-env-lock-new";
const BIN_NEW: &str = ".aether-env-bin-new";

#[cfg(test)]
static ENVIRONMENT_FAULT_PHASE: std::sync::atomic::AtomicU8 = std::sync::atomic::AtomicU8::new(0);

const ENVIRONMENT_MANIFEST: &str = r#"[package]
name = "aetherEnvironment"
version = "0.0.0"
aether = "1"

[dependencies]
"#;

const ENVIRONMENT_SOURCE: &str = "package aetherEnvironment;\n";

/// One direct executable exposed by an environment.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct EnvironmentTool {
    /// Command name, exactly the package name.
    pub name: String,
    /// Exact resolved application instance to compile.
    pub instance: PackageInstanceKey,
    /// Stable managed artifact path under the environment state directory.
    pub artifact: PathBuf,
}

/// A fully resolved environment mutation awaiting tool builds and publication.
#[derive(Debug)]
pub struct EnvironmentMutation {
    root: PathBuf,
    old_manifest: Vec<u8>,
    new_manifest: Vec<u8>,
    new_lock: Vec<u8>,
    graph: ResolvedGraph,
    tools: Vec<EnvironmentTool>,
}

impl EnvironmentMutation {
    /// Resolved graph used both for lock publication and tool compilation.
    #[must_use]
    pub const fn graph(&self) -> &ResolvedGraph {
        &self.graph
    }

    /// Direct application roots which must have managed artifacts before commit.
    #[must_use]
    pub fn tools(&self) -> &[EnvironmentTool] {
        &self.tools
    }
}

/// Creates a new isolated environment with an empty root manifest and lock.
pub fn create_environment(path: &Path) -> Result<PathBuf, String> {
    if path.as_os_str().is_empty() {
        return Err("environment path cannot be empty".to_owned());
    }
    let absolute = if path.is_absolute() {
        path.to_path_buf()
    } else {
        std::env::current_dir()
            .map_err(|error| format!("cannot resolve current directory: {error}"))?
            .join(path)
    };
    if absolute.exists() {
        return Err(format!(
            "environment path `{}` already exists",
            absolute.display()
        ));
    }
    let parent = absolute
        .parent()
        .ok_or_else(|| format!("environment path `{}` has no parent", absolute.display()))?;
    fs::create_dir_all(parent).map_err(|error| {
        format!(
            "cannot create environment parent `{}`: {error}",
            parent.display()
        )
    })?;
    let temporary = parent.join(format!(
        ".aether-env-create-{}-{}",
        std::process::id(),
        unique_suffix()
    ));
    let result = (|| {
        fs::create_dir(&temporary)
            .map_err(|error| format!("cannot create temporary environment: {error}"))?;
        fs::create_dir(temporary.join("bin"))
            .map_err(|error| format!("cannot create environment bin directory: {error}"))?;
        fs::create_dir_all(temporary.join("state/tools"))
            .map_err(|error| format!("cannot create environment state directory: {error}"))?;
        fs::create_dir(temporary.join("src"))
            .map_err(|error| format!("cannot create environment source directory: {error}"))?;
        fs::write(temporary.join(MANIFEST_FILE), ENVIRONMENT_MANIFEST)
            .map_err(|error| format!("cannot write environment manifest: {error}"))?;
        fs::write(temporary.join("src/lib.ae"), ENVIRONMENT_SOURCE)
            .map_err(|error| format!("cannot write environment root source: {error}"))?;
        fs::write(temporary.join(ENVIRONMENT_MARKER), "version=1\n")
            .map_err(|error| format!("cannot write environment marker: {error}"))?;
        let graph = Resolver::environment(None).resolve_root(&temporary)?;
        let lock = serialize_lock(&temporary, &graph)?;
        fs::write(temporary.join(LOCK_FILE), lock)
            .map_err(|error| format!("cannot write environment lock: {error}"))?;
        sync_directory(&temporary)?;
        fs::rename(&temporary, &absolute)
            .map_err(|error| format!("cannot publish environment: {error}"))?;
        sync_directory(parent)?;
        absolute
            .canonicalize()
            .map_err(|error| format!("cannot resolve created environment: {error}"))
    })();
    if result.is_err() {
        let _ = fs::remove_dir_all(&temporary);
    }
    result
}

/// Resolves an install (or coherent reinstall/update) without publishing state yet.
pub fn prepare_environment_install(
    root: &Path,
    name: &str,
    registry: &dyn RegistryProvider,
) -> Result<EnvironmentMutation, String> {
    prepare_mutation(root, name, Some(registry), true)
}

/// Resolves removal and transitive pruning without publishing state yet.
pub fn prepare_environment_uninstall(
    root: &Path,
    name: &str,
    registry: Option<&dyn RegistryProvider>,
) -> Result<EnvironmentMutation, String> {
    prepare_mutation(root, name, registry, false)
}

fn prepare_mutation(
    root: &Path,
    name: &str,
    registry: Option<&dyn RegistryProvider>,
    install: bool,
) -> Result<EnvironmentMutation, String> {
    let root = validate_environment(root)?;
    let _operation_lock = lock_environment(&root)?;
    recover_environment_transaction(&root)?;
    let manifest_path = root.join(MANIFEST_FILE);
    let old_manifest = fs::read(&manifest_path)
        .map_err(|error| format!("cannot read environment manifest: {error}"))?;
    let old_text = std::str::from_utf8(&old_manifest)
        .map_err(|_| "environment manifest is not UTF-8".to_owned())?;
    let parsed = parse_manifest_text(&manifest_path, old_text)?;
    let package = crate::PackageName::new(name.to_owned())?;
    let candidate = if install {
        let registry = registry.ok_or_else(|| {
            "registry transport is not configured; pass `--registry <https-url>` or `--offline`"
                .to_owned()
        })?;
        let version = latest_registry_release(registry, &package)?;
        edit_dependency(
            &manifest_path,
            old_text,
            package.as_str(),
            Some(DependencySpec::Registry(short_compatible_requirement(
                &version,
            ))),
        )?
    } else {
        if !parsed.dependencies.contains_key(package.as_str()) {
            return Err(format!(
                "package `{}` is not installed in this environment",
                package.as_str()
            ));
        }
        edit_dependency(&manifest_path, old_text, package.as_str(), None)?
    };
    let candidate_manifest = parse_manifest_text(&manifest_path, &candidate)?;
    let graph =
        Resolver::environment(registry).resolve_root_manifest(&root, &candidate_manifest)?;
    let lock = serialize_lock(&root, &graph)?;
    let root_node = graph
        .packages
        .get(&graph.root)
        .ok_or_else(|| "environment resolution omitted its root".to_owned())?;
    let mut tools = Vec::new();
    for (dependency, instance) in &root_node.dependencies {
        let node = graph
            .packages
            .get(instance)
            .ok_or_else(|| format!("environment dependency `{dependency}` has no resolved node"))?;
        if node.kind == ProjectKind::Application {
            let version = node.package.version.as_str();
            tools.push(EnvironmentTool {
                name: dependency.clone(),
                instance: instance.clone(),
                artifact: root
                    .join("state/tools")
                    .join(dependency)
                    .join(version)
                    .join(dependency),
            });
        }
    }
    Ok(EnvironmentMutation {
        root,
        old_manifest,
        new_manifest: candidate.into_bytes(),
        new_lock: lock.into_bytes(),
        graph,
        tools,
    })
}

/// Atomically publishes the prepared manifest, lock, and complete managed launcher set.
pub fn commit_environment(mutation: &EnvironmentMutation) -> Result<(), String> {
    for tool in &mutation.tools {
        if !tool.artifact.is_file() {
            return Err(format!(
                "managed tool artifact `{}` was not built",
                tool.artifact.display()
            ));
        }
    }
    let root = &mutation.root;
    let lock_file = lock_environment(root)?;
    recover_environment_transaction(root)?;
    let current = fs::read(root.join(MANIFEST_FILE))
        .map_err(|error| format!("cannot reread environment manifest: {error}"))?;
    if current != mutation.old_manifest {
        return Err("environment changed concurrently; retry the operation".to_owned());
    }
    cleanup_environment_files(root);
    stage_launchers(root, &mutation.tools)?;
    write_exclusive_synced(&root.join(MANIFEST_BACKUP), &mutation.old_manifest)?;
    let old_lock = fs::read(root.join(LOCK_FILE))
        .map_err(|error| format!("cannot read previous environment lock: {error}"))?;
    write_exclusive_synced(&root.join(LOCK_BACKUP), &old_lock)?;
    write_exclusive_synced(&root.join(MANIFEST_NEW), &mutation.new_manifest)?;
    write_exclusive_synced(&root.join(LOCK_NEW), &mutation.new_lock)?;
    sync_directory(root)?;
    environment_checkpoint(1)?;
    write_exclusive_synced(&root.join(TRANSACTION_MARKER), b"version=1\n")?;
    sync_directory(root)?;

    let publish = (|| {
        environment_checkpoint(2)?;
        fs::rename(root.join(MANIFEST_NEW), root.join(MANIFEST_FILE))
            .map_err(|error| format!("cannot replace environment manifest: {error}"))?;
        fs::rename(root.join(LOCK_NEW), root.join(LOCK_FILE))
            .map_err(|error| format!("cannot replace environment lock: {error}"))?;
        environment_checkpoint(3)?;
        fs::rename(root.join("bin"), root.join(BIN_BACKUP))
            .map_err(|error| format!("cannot back up environment launchers: {error}"))?;
        fs::rename(root.join(BIN_NEW), root.join("bin"))
            .map_err(|error| format!("cannot replace environment launchers: {error}"))?;
        sync_directory(root)?;
        environment_checkpoint(4)?;
        fs::remove_file(root.join(TRANSACTION_MARKER))
            .map_err(|error| format!("cannot commit environment transaction: {error}"))?;
        sync_directory(root)?;
        cleanup_environment_files(root);
        Ok::<(), String>(())
    })();
    if let Err(error) = publish {
        recover_environment_transaction(root)?;
        return Err(format!(
            "environment publication failed and the previous state was recovered: {error}"
        ));
    }
    drop(lock_file);
    Ok(())
}

fn lock_environment(root: &Path) -> Result<fs::File, String> {
    let lock_file = OpenOptions::new()
        .read(true)
        .write(true)
        .create(true)
        .truncate(false)
        .open(root.join(ENVIRONMENT_LOCK))
        .map_err(|error| format!("cannot open environment operation lock: {error}"))?;
    lock_file
        .lock_exclusive()
        .map_err(|error| format!("cannot lock environment operation: {error}"))?;
    Ok(lock_file)
}

fn stage_launchers(root: &Path, tools: &[EnvironmentTool]) -> Result<(), String> {
    let staged = root.join(BIN_NEW);
    fs::create_dir(&staged)
        .map_err(|error| format!("cannot stage environment launchers: {error}"))?;
    for tool in tools {
        let launcher = staged.join(launcher_name(&tool.name));
        let contents = launcher_contents(&tool.artifact)?;
        fs::write(&launcher, contents)
            .map_err(|error| format!("cannot write launcher `{}`: {error}", launcher.display()))?;
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            fs::set_permissions(&launcher, fs::Permissions::from_mode(0o755)).map_err(|error| {
                format!(
                    "cannot make launcher `{}` executable: {error}",
                    launcher.display()
                )
            })?;
        }
    }
    sync_directory(&staged)
}

#[cfg(windows)]
fn launcher_name(name: &str) -> String {
    format!("{name}.cmd")
}

#[cfg(not(windows))]
fn launcher_name(name: &str) -> String {
    name.to_owned()
}

#[cfg(windows)]
fn launcher_contents(artifact: &Path) -> Result<String, String> {
    let path = artifact
        .to_str()
        .ok_or_else(|| "managed tool artifact path is not UTF-8".to_owned())?;
    Ok(format!("@echo off\r\n\"{path}\" %*\r\n"))
}

#[cfg(not(windows))]
fn launcher_contents(artifact: &Path) -> Result<String, String> {
    let path = artifact
        .to_str()
        .ok_or_else(|| "managed tool artifact path is not UTF-8".to_owned())?;
    let quoted = path.replace('\'', "'\\''");
    Ok(format!("#!/bin/sh\nexec '{quoted}' \"$@\"\n"))
}

fn validate_environment(path: &Path) -> Result<PathBuf, String> {
    let root = path
        .canonicalize()
        .map_err(|error| format!("cannot resolve environment `{}`: {error}", path.display()))?;
    if !root.is_dir() || !root.join(ENVIRONMENT_MARKER).is_file() {
        return Err(format!(
            "`{}` is not an Aether environment; run `aether env create <path>`",
            path.display()
        ));
    }
    Ok(root)
}

fn recover_environment_transaction(root: &Path) -> Result<(), String> {
    let marker = root.join(TRANSACTION_MARKER);
    if !marker.exists() {
        cleanup_environment_files(root);
        return Ok(());
    }
    let marker_text = fs::read_to_string(&marker)
        .map_err(|error| format!("cannot read environment transaction marker: {error}"))?;
    if marker_text != "version=1\n" {
        return Err("environment transaction marker is invalid; recovery required".to_owned());
    }
    if root.join(MANIFEST_BACKUP).exists() {
        fs::rename(root.join(MANIFEST_BACKUP), root.join(MANIFEST_FILE))
            .map_err(|error| format!("cannot restore environment manifest: {error}"))?;
    }
    if root.join(LOCK_BACKUP).exists() {
        fs::rename(root.join(LOCK_BACKUP), root.join(LOCK_FILE))
            .map_err(|error| format!("cannot restore environment lock: {error}"))?;
    }
    if root.join(BIN_BACKUP).exists() {
        if root.join("bin").exists() {
            fs::remove_dir_all(root.join("bin"))
                .map_err(|error| format!("cannot discard uncommitted launchers: {error}"))?;
        }
        fs::rename(root.join(BIN_BACKUP), root.join("bin"))
            .map_err(|error| format!("cannot restore environment launchers: {error}"))?;
    }
    fs::remove_file(marker)
        .map_err(|error| format!("cannot finish environment recovery: {error}"))?;
    sync_directory(root)?;
    cleanup_environment_files(root);
    Ok(())
}

fn cleanup_environment_files(root: &Path) {
    for file in [MANIFEST_BACKUP, LOCK_BACKUP, MANIFEST_NEW, LOCK_NEW] {
        let _ = fs::remove_file(root.join(file));
    }
    for directory in [BIN_BACKUP, BIN_NEW] {
        let _ = fs::remove_dir_all(root.join(directory));
    }
}

#[cfg(not(test))]
#[allow(clippy::unnecessary_wraps)]
fn environment_checkpoint(_phase: u8) -> Result<(), String> {
    Ok(())
}

#[cfg(test)]
fn environment_checkpoint(phase: u8) -> Result<(), String> {
    use std::sync::atomic::Ordering;
    if ENVIRONMENT_FAULT_PHASE.load(Ordering::SeqCst) == phase {
        Err(format!(
            "injected environment transaction failure at phase {phase}"
        ))
    } else {
        Ok(())
    }
}

fn unique_suffix() -> u64 {
    use std::sync::atomic::{AtomicU64, Ordering};
    static NEXT: AtomicU64 = AtomicU64::new(0);
    NEXT.fetch_add(1, Ordering::Relaxed)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{DependencySpec, PackageName, RegistryPackageMetadata, RegistryVersion};
    use semver::Version;
    use std::collections::BTreeMap;
    use std::fmt::Write as _;

    struct FakeRegistry {
        packages: BTreeMap<String, RegistryPackageMetadata>,
    }

    impl RegistryProvider for FakeRegistry {
        fn versions(&self, name: &PackageName) -> Result<Vec<RegistryVersion>, String> {
            let package = self
                .packages
                .get(name.as_str())
                .ok_or_else(|| "missing package".to_owned())?;
            Ok(vec![RegistryVersion {
                version: package.version.clone(),
                yanked: false,
            }])
        }

        fn metadata(
            &self,
            name: &PackageName,
            version: &Version,
        ) -> Result<RegistryPackageMetadata, String> {
            let package = self
                .packages
                .get(name.as_str())
                .ok_or_else(|| "missing package".to_owned())?;
            if package.version != version.to_string() {
                return Err("missing version".to_owned());
            }
            Ok(package.clone())
        }
    }

    fn fixture_root(label: &str) -> PathBuf {
        let root = std::env::temp_dir().join(format!(
            "aether-environment-{label}-{}-{}",
            std::process::id(),
            unique_suffix()
        ));
        fs::create_dir(&root).unwrap();
        root
    }

    fn add_package(
        registry: &mut FakeRegistry,
        parent: &Path,
        name: &str,
        application: bool,
        dependencies: &[(&str, &str)],
    ) {
        let root = parent.join(format!("registry-{name}"));
        fs::create_dir_all(root.join("src")).unwrap();
        let mut manifest = format!("[package]\nname='{name}'\nversion='1.0.0'\n");
        if application {
            manifest.push_str("[application]\n");
            fs::write(root.join("src/main.ae"), "int main(){return 0;}\n").unwrap();
        } else {
            fs::write(root.join("src/lib.ae"), format!("package {name};\n")).unwrap();
        }
        let mut specs = BTreeMap::new();
        if !dependencies.is_empty() {
            manifest.push_str("[dependencies]\n");
            for (dependency, requirement) in dependencies {
                writeln!(manifest, "{dependency}='{requirement}'").unwrap();
                specs.insert(
                    (*dependency).to_owned(),
                    DependencySpec::Registry((*requirement).to_owned()),
                );
            }
        }
        fs::write(root.join("aether.toml"), manifest).unwrap();
        registry.packages.insert(
            name.to_owned(),
            RegistryPackageMetadata {
                name: name.to_owned(),
                version: "1.0.0".to_owned(),
                checksum: format!("sha256:{name}"),
                dependencies: specs,
                root,
            },
        );
    }

    #[test]
    fn creates_closed_environment_layout() {
        let parent = fixture_root("create");
        let root = parent.join("environment with spaces");
        let created = create_environment(&root).unwrap();
        assert!(created.join("aether.toml").is_file());
        assert!(created.join("aether.lock").is_file());
        assert!(created.join("bin").is_dir());
        assert!(created.join("state/environment-v1").is_file());
        fs::remove_dir_all(parent).unwrap();
    }

    #[test]
    #[cfg(unix)]
    fn installs_libraries_and_tools_prunes_and_recovers_transactions() {
        use std::os::unix::fs::PermissionsExt;
        use std::sync::atomic::Ordering;

        let parent = fixture_root("operations");
        let environment = parent.join("environment");
        create_environment(&environment).unwrap();
        let mut registry = FakeRegistry {
            packages: BTreeMap::new(),
        };
        add_package(&mut registry, &parent, "shared", false, &[]);
        add_package(&mut registry, &parent, "tool", true, &[("shared", "1")]);
        add_package(&mut registry, &parent, "library", false, &[]);

        let library = prepare_environment_install(&environment, "library", &registry).unwrap();
        assert!(library.tools().is_empty());
        commit_environment(&library).unwrap();
        assert_eq!(fs::read_dir(environment.join("bin")).unwrap().count(), 0);

        let tool = prepare_environment_install(&environment, "tool", &registry).unwrap();
        assert_eq!(tool.tools().len(), 1);
        let artifact = &tool.tools()[0].artifact;
        fs::create_dir_all(artifact.parent().unwrap()).unwrap();
        fs::write(artifact, "#!/bin/sh\nexit 0\n").unwrap();
        fs::set_permissions(artifact, fs::Permissions::from_mode(0o755)).unwrap();
        commit_environment(&tool).unwrap();
        let launcher = environment.join("bin/tool");
        assert!(launcher.is_file());
        assert!(
            std::process::Command::new(&launcher)
                .status()
                .unwrap()
                .success()
        );
        let lock = fs::read_to_string(environment.join("aether.lock")).unwrap();
        assert!(lock.contains("tool@1.0.0"));
        assert!(lock.contains("shared@1.0.0"));

        let before_manifest = fs::read(environment.join("aether.toml")).unwrap();
        let before_lock = fs::read(environment.join("aether.lock")).unwrap();
        for phase in 1..=4 {
            let failed =
                prepare_environment_uninstall(&environment, "library", Some(&registry)).unwrap();
            ENVIRONMENT_FAULT_PHASE.store(phase, Ordering::SeqCst);
            assert!(commit_environment(&failed).is_err());
            ENVIRONMENT_FAULT_PHASE.store(0, Ordering::SeqCst);
            assert_eq!(
                fs::read(environment.join("aether.toml")).unwrap(),
                before_manifest
            );
            assert_eq!(
                fs::read(environment.join("aether.lock")).unwrap(),
                before_lock
            );
            assert!(launcher.is_file());
        }

        let remove_tool =
            prepare_environment_uninstall(&environment, "tool", Some(&registry)).unwrap();
        commit_environment(&remove_tool).unwrap();
        assert!(!launcher.exists());
        let lock = fs::read_to_string(environment.join("aether.lock")).unwrap();
        assert!(!lock.contains("tool@1.0.0"));
        assert!(!lock.contains("shared@1.0.0"));
        assert!(lock.contains("library@1.0.0"));
        fs::remove_dir_all(parent).unwrap();
    }
}
