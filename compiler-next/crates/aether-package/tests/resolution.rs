//! Resolver, lockfile, and in-memory registry qualification.

use std::cell::Cell;
use std::collections::BTreeMap;
use std::fmt::Write as _;
use std::fs;
use std::path::PathBuf;
use std::sync::atomic::{AtomicU64, Ordering};

use aether_package::{
    DependencyPath, DependencySpec, PackageInstanceKey, PackageName, RegistryPackageMetadata,
    RegistryProvider, RegistryVersion, add, add_path, remove, resolve, sync, update,
};
use semver::Version;

static NEXT_DIRECTORY: AtomicU64 = AtomicU64::new(0);

struct Directory(PathBuf);

impl Directory {
    fn new(label: &str) -> Self {
        let serial = NEXT_DIRECTORY.fetch_add(1, Ordering::Relaxed);
        let path = std::env::temp_dir().join(format!(
            "aether-package-{label}-{}-{serial}",
            std::process::id()
        ));
        fs::create_dir(&path).unwrap();
        Self(path)
    }

    fn write(&self, relative: &str, text: &str) {
        let path = self.0.join(relative);
        if let Some(parent) = path.parent() {
            fs::create_dir_all(parent).unwrap();
        }
        fs::write(path, text).unwrap();
    }
}

impl Drop for Directory {
    fn drop(&mut self) {
        fs::remove_dir_all(&self.0).unwrap();
    }
}

#[derive(Clone)]
struct Entry {
    yanked: bool,
    checksum: String,
    dependencies: BTreeMap<String, DependencySpec>,
    root: PathBuf,
}

#[derive(Default)]
struct MemoryRegistry {
    entries: BTreeMap<(String, String), Entry>,
    reverse: Cell<bool>,
}

impl MemoryRegistry {
    fn insert(
        &mut self,
        name: &str,
        version: &str,
        checksum: &str,
        root: PathBuf,
        dependencies: BTreeMap<String, DependencySpec>,
    ) {
        self.entries.insert(
            (name.to_owned(), version.to_owned()),
            Entry {
                yanked: false,
                checksum: checksum.to_owned(),
                dependencies,
                root,
            },
        );
    }

    fn yank(&mut self, name: &str, version: &str) {
        self.entries
            .get_mut(&(name.to_owned(), version.to_owned()))
            .unwrap()
            .yanked = true;
    }
}

impl RegistryProvider for MemoryRegistry {
    fn versions(&self, name: &PackageName) -> Result<Vec<RegistryVersion>, String> {
        let mut versions = self
            .entries
            .iter()
            .filter(|((entry_name, _), _)| entry_name == name.as_str())
            .map(|((_, version), entry)| RegistryVersion {
                version: version.clone(),
                yanked: entry.yanked,
            })
            .collect::<Vec<_>>();
        if self.reverse.replace(!self.reverse.get()) {
            versions.reverse();
        }
        Ok(versions)
    }

    fn metadata(
        &self,
        name: &PackageName,
        version: &Version,
    ) -> Result<RegistryPackageMetadata, String> {
        let key = (name.as_str().to_owned(), version.to_string());
        let entry = self
            .entries
            .get(&key)
            .ok_or_else(|| format!("missing {key:?}"))?;
        Ok(RegistryPackageMetadata {
            name: key.0,
            version: key.1,
            checksum: entry.checksum.clone(),
            dependencies: entry.dependencies.clone(),
            root: entry.root.clone(),
        })
    }
}

fn registry_dependency(requirement: &str) -> DependencySpec {
    DependencySpec::Registry(requirement.to_owned())
}

fn path_dependency(path: &str) -> DependencySpec {
    DependencySpec::Path(DependencyPath {
        path: PathBuf::from(path),
    })
}

fn manifest(name: &str, version: &str, dependencies: &[(&str, &str)]) -> String {
    let mut text = format!("[package]\nname={name:?}\nversion={version:?}\n");
    if !dependencies.is_empty() {
        text.push_str("[dependencies]\n");
        for (dependency, requirement) in dependencies {
            writeln!(text, "{dependency}={requirement:?}").unwrap();
        }
    }
    text
}

fn registry_package(
    directory: &Directory,
    relative: &str,
    name: &str,
    version: &str,
    dependencies: &[(&str, &str)],
) -> PathBuf {
    directory.write(
        &format!("{relative}/aether.toml"),
        &manifest(name, version, dependencies),
    );
    directory.write(
        &format!("{relative}/src/lib.ae"),
        &format!("package {name};"),
    );
    directory.0.join(relative)
}

fn selected_versions(graph: &aether_package::ResolvedGraph, name: &str) -> Vec<String> {
    graph
        .packages
        .keys()
        .filter_map(|instance| match instance {
            PackageInstanceKey::Registry {
                name: selected,
                version,
                ..
            } if selected == name => Some(version.clone()),
            _ => None,
        })
        .collect()
}

#[test]
fn edge_local_resolution_is_deterministic_multiversion_and_exactly_shared() {
    let directory = Directory::new("edge-local");
    directory.write("app/aether.toml", "[package]\nname='app'\nversion='0.1.0'\n[dependencies]\na='1'\nb='1'\nlocal={path='../local'}\n");
    directory.write("app/src/main.ae", "int main(){return 0;}");
    directory.write(
        "local/aether.toml",
        "[package]\nname='local'\nversion='1.0.0'\n[dependencies]\ncommon='1'\n",
    );
    directory.write("local/src/lib.ae", "package local;");

    let mut registry = MemoryRegistry::default();
    let common = registry_package(&directory, "registry/common", "common", "1.4.0", &[]);
    let math1 = registry_package(&directory, "registry/math1", "math", "1.9.0", &[]);
    let math2 = registry_package(&directory, "registry/math2", "math", "2.3.0", &[]);
    let a = registry_package(
        &directory,
        "registry/a",
        "a",
        "1.0.0",
        &[("common", "1"), ("math", "1")],
    );
    let b = registry_package(
        &directory,
        "registry/b",
        "b",
        "1.0.0",
        &[("common", "1"), ("math", "2")],
    );
    registry.insert("common", "1.4.0", "sha256:common", common, BTreeMap::new());
    registry.insert("math", "1.9.0", "sha256:math1", math1, BTreeMap::new());
    registry.insert("math", "2.3.0", "sha256:math2", math2, BTreeMap::new());
    registry.insert(
        "a",
        "1.0.0",
        "sha256:a",
        a,
        BTreeMap::from([
            ("common".to_owned(), registry_dependency("1")),
            ("math".to_owned(), registry_dependency("1")),
        ]),
    );
    registry.insert(
        "b",
        "1.0.0",
        "sha256:b",
        b,
        BTreeMap::from([
            ("common".to_owned(), registry_dependency("1")),
            ("math".to_owned(), registry_dependency("2")),
        ]),
    );

    let first = resolve(&directory.0.join("app"), Some(&registry)).unwrap();
    let second = resolve(&directory.0.join("app"), Some(&registry)).unwrap();
    assert_eq!(
        first, second,
        "provider response order must not affect resolution"
    );
    assert_eq!(selected_versions(&first, "math"), ["1.9.0", "2.3.0"]);
    assert_eq!(selected_versions(&first, "common"), ["1.4.0"]);
    assert!(
        first
            .packages
            .keys()
            .any(|key| matches!(key, PackageInstanceKey::Path { name, .. } if name == "local"))
    );
}

#[test]
fn sync_reuses_locked_release_update_moves_and_yank_rules_differ() {
    let directory = Directory::new("sync-update-yank");
    directory.write(
        "app/aether.toml",
        &manifest("app", "0.1.0", &[("math", "1")]),
    );
    directory.write("app/src/main.ae", "int main(){return 0;}");
    let math10 = registry_package(&directory, "registry/math10", "math", "1.0.0", &[]);
    let math11 = registry_package(&directory, "registry/math11", "math", "1.1.0", &[]);
    let math12 = registry_package(&directory, "registry/math12", "math", "1.2.0", &[]);
    let mut registry = MemoryRegistry::default();
    registry.insert("math", "1.0.0", "sha256:10", math10, BTreeMap::new());
    registry.insert("math", "1.1.0", "sha256:11", math11, BTreeMap::new());

    let initial = sync(&directory.0.join("app"), Some(&registry)).unwrap();
    assert_eq!(selected_versions(&initial, "math"), ["1.1.0"]);
    registry.insert("math", "1.2.0", "sha256:12", math12, BTreeMap::new());
    registry.yank("math", "1.1.0");
    let reused = sync(&directory.0.join("app"), Some(&registry)).unwrap();
    assert_eq!(
        selected_versions(&reused, "math"),
        ["1.1.0"],
        "locked yanked releases remain valid"
    );
    let refreshed = update(&directory.0.join("app"), Some(&registry)).unwrap();
    assert_eq!(selected_versions(&refreshed, "math"), ["1.2.0"]);
    registry.yank("math", "1.2.0");
    let fallback = update(&directory.0.join("app"), Some(&registry)).unwrap();
    assert_eq!(
        selected_versions(&fallback, "math"),
        ["1.0.0"],
        "new resolution excludes yanked releases"
    );
}

#[test]
fn lock_is_canonical_relative_and_manifest_divergence_preserves_it() {
    let directory = Directory::new("lock-relative");
    directory.write(
        "app/aether.toml",
        "[package]\nname='app'\nversion='0.1.0'\n[dependencies]\nlocal={path='../local'}\n",
    );
    directory.write("app/src/main.ae", "int main(){return 0;}");
    directory.write("local/aether.toml", &manifest("local", "1.0.0", &[]));
    directory.write("local/src/lib.ae", "package local;");
    sync(&directory.0.join("app"), None).unwrap();
    let lock_path = directory.0.join("app/aether.lock");
    let before = fs::read_to_string(&lock_path).unwrap();
    assert!(before.contains("lock-version = 1"));
    assert!(before.contains("source = \"path+../local\""));
    assert!(!before.contains(directory.0.to_str().unwrap()));

    directory.write(
        "app/aether.toml",
        "[package]\nname='app'\nversion='0.1.0'\n[dependencies]\nother='1'\n",
    );
    let error = sync(&directory.0.join("app"), None).unwrap_err();
    assert!(error.contains("run `aether update`"));
    assert_eq!(fs::read_to_string(lock_path).unwrap(), before);
}

#[test]
fn changed_path_topology_and_registry_checksum_fail_closed() {
    let directory = Directory::new("lock-validation");
    directory.write("app/aether.toml", "[package]\nname='app'\nversion='0.1.0'\n[dependencies]\nlocal={path='../local'}\nmath='1'\n");
    directory.write("app/src/main.ae", "int main(){return 0;}");
    directory.write("local/aether.toml", &manifest("local", "1.0.0", &[]));
    directory.write("local/src/lib.ae", "package local;");
    let math = registry_package(&directory, "registry/math", "math", "1.0.0", &[]);
    let mut registry = MemoryRegistry::default();
    registry.insert("math", "1.0.0", "sha256:original", math, BTreeMap::new());
    sync(&directory.0.join("app"), Some(&registry)).unwrap();

    registry
        .entries
        .get_mut(&("math".to_owned(), "1.0.0".to_owned()))
        .unwrap()
        .checksum = "sha256:changed".to_owned();
    assert!(
        sync(&directory.0.join("app"), Some(&registry))
            .unwrap_err()
            .contains("checksum mismatch")
    );
    registry
        .entries
        .get_mut(&("math".to_owned(), "1.0.0".to_owned()))
        .unwrap()
        .checksum = "sha256:original".to_owned();
    directory.write(
        "local/aether.toml",
        "[package]\nname='local'\nversion='1.0.0'\n[dependencies]\nextra='1'\n",
    );
    assert!(
        sync(&directory.0.join("app"), Some(&registry))
            .unwrap_err()
            .contains("topology changed")
    );
}

#[test]
fn registry_path_metadata_and_cycles_are_rejected() {
    let directory = Directory::new("registry-invalid");
    directory.write("app/aether.toml", &manifest("app", "0.1.0", &[("a", "1")]));
    directory.write("app/src/main.ae", "int main(){return 0;}");
    let a = registry_package(&directory, "registry/a", "a", "1.0.0", &[("b", "1")]);
    let b = registry_package(&directory, "registry/b", "b", "1.0.0", &[("a", "1")]);
    let mut registry = MemoryRegistry::default();
    registry.insert(
        "a",
        "1.0.0",
        "sha256:a",
        a.clone(),
        BTreeMap::from([("b".to_owned(), registry_dependency("1"))]),
    );
    registry.insert(
        "b",
        "1.0.0",
        "sha256:b",
        b,
        BTreeMap::from([("a".to_owned(), registry_dependency("1"))]),
    );
    assert!(
        resolve(&directory.0.join("app"), Some(&registry))
            .unwrap_err()
            .contains("cycle")
    );

    directory.write(
        "registry/a/aether.toml",
        "[package]\nname='a'\nversion='1.0.0'\n[dependencies]\nlocal={path='../../local'}\n",
    );
    registry
        .entries
        .get_mut(&("a".to_owned(), "1.0.0".to_owned()))
        .unwrap()
        .dependencies = BTreeMap::from([("local".to_owned(), path_dependency("../../local"))]);
    assert!(
        resolve(&directory.0.join("app"), Some(&registry))
            .unwrap_err()
            .contains("forbidden path dependency")
    );
}

#[test]
fn exact_prerelease_is_selectable_but_compatible_prerelease_is_not() {
    let directory = Directory::new("prerelease");
    directory.write(
        "app/aether.toml",
        &manifest("app", "0.1.0", &[("math", "=1.0.0-alpha.1")]),
    );
    directory.write("app/src/main.ae", "int main(){return 0;}");
    let pre = registry_package(&directory, "registry/pre", "math", "1.0.0-alpha.1", &[]);
    let mut registry = MemoryRegistry::default();
    registry.insert("math", "1.0.0-alpha.1", "sha256:pre", pre, BTreeMap::new());
    assert_eq!(
        selected_versions(
            &resolve(&directory.0.join("app"), Some(&registry)).unwrap(),
            "math"
        ),
        ["1.0.0-alpha.1"]
    );
    directory.write(
        "app/aether.toml",
        &manifest("app", "0.1.0", &[("math", "1")]),
    );
    assert!(
        resolve(&directory.0.join("app"), Some(&registry))
            .unwrap_err()
            .contains("no non-yanked version")
    );
}

#[test]
fn source_class_or_locked_constraint_changes_require_update() {
    let directory = Directory::new("source-change");
    directory.write(
        "app/aether.toml",
        &manifest("app", "0.1.0", &[("math", "1")]),
    );
    directory.write("app/src/main.ae", "int main(){return 0;}");
    let math = registry_package(&directory, "registry/math", "math", "1.0.0", &[]);
    let mut registry = MemoryRegistry::default();
    registry.insert("math", "1.0.0", "sha256:math", math, BTreeMap::new());
    sync(&directory.0.join("app"), Some(&registry)).unwrap();
    directory.write(
        "app/aether.toml",
        &manifest("app", "0.1.0", &[("math", "2")]),
    );
    assert!(
        sync(&directory.0.join("app"), Some(&registry))
            .unwrap_err()
            .contains("no longer satisfies")
    );

    directory.write("local/aether.toml", &manifest("math", "1.0.0", &[]));
    directory.write("local/src/lib.ae", "package math;");
    directory.write(
        "app/aether.toml",
        "[package]\nname='app'\nversion='0.1.0'\n[dependencies]\nmath={path='../local'}\n",
    );
    assert!(
        sync(&directory.0.join("app"), Some(&registry))
            .unwrap_err()
            .contains("changed source class")
    );
}

#[test]
fn malformed_lock_rejects_duplicate_dangling_and_cyclic_ids() {
    let directory = Directory::new("malformed-lock");
    directory.write("app/aether.toml", &manifest("app", "0.1.0", &[]));
    directory.write("app/src/main.ae", "int main(){return 0;}");
    let base = "lock-version = 1\nroot = 'root:app@0.1.0'\n\n[[package]]\nid = 'root:app@0.1.0'\nname = 'app'\nversion = '0.1.0'\nsource = 'root'\n";

    directory.write("app/aether.lock", &format!("{base}\n[[package]]\nid = 'root:app@0.1.0'\nname = 'app'\nversion = '0.1.0'\nsource = 'root'\n"));
    assert!(
        sync(&directory.0.join("app"), None)
            .unwrap_err()
            .contains("duplicate lock package id")
    );

    directory.write(
        "app/aether.lock",
        &format!("{base}dependencies = [{{ name = 'lost', target = 'missing' }}]\n"),
    );
    assert!(
        sync(&directory.0.join("app"), None)
            .unwrap_err()
            .contains("dangling target")
    );

    directory.write(
        "app/aether.lock",
        &format!("{base}dependencies = [{{ name = 'app', target = 'root:app@0.1.0' }}]\n"),
    );
    assert!(
        sync(&directory.0.join("app"), None)
            .unwrap_err()
            .contains("cycle")
    );
}

#[test]
fn equal_precedence_build_metadata_uses_utf8_spelling_tiebreak() {
    let directory = Directory::new("build-tiebreak");
    directory.write(
        "app/aether.toml",
        &manifest("app", "0.1.0", &[("math", "1")]),
    );
    directory.write("app/src/main.ae", "int main(){return 0;}");
    let aaa = registry_package(&directory, "registry/aaa", "math", "1.0.0+aaa", &[]);
    let zzz = registry_package(&directory, "registry/zzz", "math", "1.0.0+zzz", &[]);
    let mut registry = MemoryRegistry::default();
    registry.insert("math", "1.0.0+zzz", "sha256:zzz", zzz, BTreeMap::new());
    registry.insert("math", "1.0.0+aaa", "sha256:aaa", aaa, BTreeMap::new());
    assert_eq!(
        selected_versions(
            &resolve(&directory.0.join("app"), Some(&registry)).unwrap(),
            "math"
        ),
        ["1.0.0+zzz"]
    );
}

#[test]
fn add_preserves_manifest_layout_and_writes_short_zero_constraints() {
    let directory = Directory::new("add-command");
    directory.write(
        "app/aether.toml",
        "# keep this comment\n[package]\nname = 'app' # identity\nversion = '0.1.0'\n\n[application]\nentry = 'src/main.ae'\n",
    );
    directory.write("app/src/main.ae", "int main(){return 0;}");
    let zero = registry_package(&directory, "registry/zero", "zero", "0.3.7", &[]);
    let tiny = registry_package(&directory, "registry/tiny", "tiny", "0.0.5", &[]);
    let mut registry = MemoryRegistry::default();
    registry.insert("zero", "0.3.7", "sha256:zero", zero, BTreeMap::new());
    registry.insert("tiny", "0.0.5", "sha256:tiny", tiny, BTreeMap::new());

    add(&directory.0.join("app"), "zero", &registry).unwrap();
    add(&directory.0.join("app"), "tiny", &registry).unwrap();
    let manifest = fs::read_to_string(directory.0.join("app/aether.toml")).unwrap();
    assert!(manifest.contains("# keep this comment"));
    assert!(manifest.contains("name = 'app' # identity"));
    assert!(manifest.contains("zero = \"0.3\""));
    assert!(manifest.contains("tiny = \"0.0.5\""));
    assert!(directory.0.join("app/aether.lock").is_file());
    assert!(
        add(&directory.0.join("app"), "zero", &registry)
            .unwrap_err()
            .contains("already a direct dependency")
    );
}

#[test]
fn remove_prunes_graph_and_failed_mutations_preserve_both_files() {
    let directory = Directory::new("remove-command");
    directory.write(
        "app/aether.toml",
        "[package]\nname='app'\nversion='0.1.0'\n[dependencies]\ndirect={path='../direct'}\nkeep={path='../keep'}\n",
    );
    directory.write("app/src/main.ae", "int main(){return 0;}");
    directory.write(
        "direct/aether.toml",
        "[package]\nname='direct'\nversion='1.0.0'\n[dependencies]\ntransitive={path='../transitive'}\n",
    );
    directory.write("direct/src/lib.ae", "package direct;");
    directory.write(
        "transitive/aether.toml",
        &manifest("transitive", "1.0.0", &[]),
    );
    directory.write("transitive/src/lib.ae", "package transitive;");
    directory.write("keep/aether.toml", &manifest("keep", "1.0.0", &[]));
    directory.write("keep/src/lib.ae", "package keep;");
    sync(&directory.0.join("app"), None).unwrap();

    let before_manifest = fs::read(directory.0.join("app/aether.toml")).unwrap();
    let before_lock = fs::read(directory.0.join("app/aether.lock")).unwrap();
    assert!(
        remove(&directory.0.join("app"), "transitive", None)
            .unwrap_err()
            .contains("not a direct dependency")
    );
    assert_eq!(
        fs::read(directory.0.join("app/aether.toml")).unwrap(),
        before_manifest
    );
    assert_eq!(
        fs::read(directory.0.join("app/aether.lock")).unwrap(),
        before_lock
    );

    remove(&directory.0.join("app"), "direct", None).unwrap();
    let lock = fs::read_to_string(directory.0.join("app/aether.lock")).unwrap();
    assert!(!lock.contains("direct@1.0.0"));
    assert!(!lock.contains("transitive@1.0.0"));
    assert!(lock.contains("keep@1.0.0"));
}

#[test]
fn add_path_validates_name_and_publishes_exact_locator() {
    let directory = Directory::new("add-path-command");
    directory.write("app/aether.toml", &manifest("app", "0.1.0", &[]));
    directory.write("app/src/main.ae", "int main(){return 0;}");
    directory.write("local/aether.toml", &manifest("local", "1.0.0", &[]));
    directory.write("local/src/lib.ae", "package local;");
    add_path(
        &directory.0.join("app"),
        "local",
        PathBuf::from("../local").as_path(),
    )
    .unwrap();
    let manifest = fs::read_to_string(directory.0.join("app/aether.toml")).unwrap();
    assert!(manifest.contains("local = { path = \"../local\" }"));
}
